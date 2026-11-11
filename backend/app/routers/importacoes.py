"""Importação de relatórios das plataformas (PRD §15–§16, §50–§52).

Fluxo em duas etapas: `analisar` devolve a prévia (nada é gravado) e
`confirmar` grava somente as linhas aprovadas pelo usuário, registrando
tudo em `importacoes` e guardando o arquivo original em /uploads (§15).
"""
import json
import logging
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time as hora_zero, timedelta, timezone
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from pydantic import PrivateAttr
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.database import bloquear_escola_para_importacao, get_db
from app.core.deps import escola_autorizada, exigir_papeis
from app.core.tempo import FUSO_BR, para_br
from app.services.eventos import chave_evento, ingerir_eventos
from app.models import (
    Aluno,
    Escola,
    IdentidadeExterna,
    Importacao,
    Leitura,
    Livro,
    Matricula,
    NivelDificuldade,
    RevisaoIdentidade,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
    Usuario,
)
from app.schemas import (
    AnaliseOut,
    ImportacaoConfirm,
    ImportacaoOut,
    ImportacaoResultadoOut,
    MatriculasAnaliseOut,
    MatriculasResultadoOut,
    MatriculaTurmaOut,
)
from app.schemas.importacao import (
    DefinirIdentidadeEfetivaIn,
    DescartarRevisaoIn,
    ReativarIdentidadeIn,
    ResolucaoRevisaoOut,
    ResolverRevisaoIn,
    RevisaoIdentidadeOut,
)
from app.services import elegibilidade, identidade_aluno as ida
from app.services import importacao as svc
from app.services import lista_piloto, matching, matriculas, perfis_pdf, planilhas
from app.services import dificuldade_livro, professores, push, scoring
from app.services import identidade_efetiva, politica_sync, triagem_revisoes
from app.services import turma_arquivada
from app.services import modulos as svc_modulos
from app.services.audit import registrar
from app.models.base import agora
from app.models.plataformas import IMPORTACAO_SEM_QUESTOES

router = APIRouter(prefix="/escolas/{escola_id}/importacoes", tags=["Importações"])

logger = logging.getLogger("constela.importacao")
# O que só acontece na importação feita PELA SINCRONIZAÇÃO vai para o log dela.
logger_sync = logging.getLogger("constela.sync")


def _num(valor, tipo):
    """Coerção de um valor NUMÉRICO vindo do payload do cliente: um valor não
    numérico (cliente adulterado, bug de front) vira 400, não 500."""
    try:
        return tipo(valor)
    except (ValueError, TypeError) as erro:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "O relatório contém um valor numérico inválido.",
        ) from erro

TAMANHO_MAXIMO = 10 * 1024 * 1024  # 10 MB
IDADE_MAXIMA_TEMP_S = 24 * 3600     # PDFs de prévia não confirmados expiram em 24h
_TOKEN_VALIDO = re.compile(r"^[0-9a-f]{32}\.(pdf|xlsx)$")


def _limpar_temporarios_orfaos() -> None:
    """Remove arquivos de prévia abandonados (usuário fechou sem confirmar).
    Chamado a cada nova análise — barato e evita crescimento sem limite."""
    import itertools

    pasta = settings.UPLOADS_DIR / "temporarios"
    if not pasta.exists():
        return
    limite = time.time() - IDADE_MAXIMA_TEMP_S
    for arquivo in itertools.chain(pasta.glob("*.pdf"), pasta.glob("*.xlsx")):
        try:
            if arquivo.stat().st_mtime < limite:
                arquivo.unlink(missing_ok=True)
        except OSError:
            pass


def _guardar_temporario(conteudo: bytes, extensao: str) -> str | None:
    """Arquiva o original em /temporarios até a confirmação (§15).

    MELHOR ESFORÇO: se o disco não estiver gravável (ex.: deploy sem volume ou
    sem permissão), a importação segue normalmente sem o arquivamento — nunca
    derruba a análise com 500 por causa do armazenamento do original."""
    token = f"{uuid.uuid4().hex}.{extensao}"
    destino = settings.UPLOADS_DIR / "temporarios" / token
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(conteudo)
        return token
    except OSError:
        logger.warning(
            "Sem acesso de escrita em %s — o arquivo original não será "
            "arquivado (defina UPLOADS_DIR para um diretório gravável).",
            destino.parent)
        return None


def _snapshot_atual(db: Session, escola_id: int, aluno_id: int, modelo, *, ate=None):
    # Ordena por data_referencia (id desempata): importar um relatório de um
    # período ANTIGO (backfill mensal do Matific) não pode virar o "estado
    # atual" só por ter id maior. ``ate`` (UTC naive): ignora retratos datados
    # depois dele — ver ``_teto_retrato_valido``.
    consulta = select(modelo).where(modelo.escola_id == escola_id, modelo.aluno_id == aluno_id)
    if ate is not None:
        consulta = consulta.where(modelo.data_referencia <= ate)
    return db.execute(
        consulta.order_by(modelo.data_referencia.desc(), modelo.id.desc()).limit(1)
    ).scalar_one_or_none()


# Uma execução de sincronização "executando" sem fim registrado (processo caiu)
# não vale como janela para sempre.
_JANELA_MAX_SINCRONIZACAO = timedelta(hours=12)
_FOLGA_JANELA_SINCRONIZACAO = timedelta(minutes=1)
# Retrato datado acima de agora + esta folga não conta como "o retrato atual" ao
# decidir o que é retrodatado e de onde herdar (``_teto_retrato_valido``).
_FOLGA_DATA_FUTURA = timedelta(minutes=10)


def _agora_utc() -> datetime:
    """Agora em UTC naive (a convenção do ``data_referencia`` gravado). Ponto ÚNICO
    do relógio nas regras de data do /confirmar — os testes o fixam."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _teto_retrato_valido(agora_utc: datetime) -> datetime:
    """Até quando um retrato gravado vale como dado JÁ ACONTECIDO. Retrato datado
    no futuro é legado (o servidor aceitava qualquer data no upload manual): se
    contasse como o atual, a coleta de hoje viraria "retrodatada" — e a
    sincronização da escola inteira era recusada com um diagnóstico errado."""
    return agora_utc + _FOLGA_DATA_FUTURA


def _dia_em_brasilia(momento) -> date | None:
    """O dia (de Brasília) de um instante, ou None se a conversão estoura o
    calendário (ano 1 com fuso positivo, 9999 com -14:00): data absurda vira 422,
    nunca 500."""
    try:
        return para_br(momento).date()
    except (OverflowError, ValueError):
        return None


def _inicio_do_dia_em_brasilia(momento) -> datetime | None:
    """A meia-noite (de Brasília) do dia deste instante, em UTC naive."""
    dia = _dia_em_brasilia(momento)
    if dia is None:
        return None
    try:
        meia_noite = datetime.combine(dia, hora_zero(0, 0), tzinfo=FUSO_BR)
        return meia_noite.astimezone(timezone.utc).replace(tzinfo=None)
    except (OverflowError, ValueError):
        return None


def _janela_antes(momento: datetime) -> datetime:
    """``momento`` menos ``_JANELA_MAX_SINCRONIZACAO``, sem passar do início do
    calendário: o retrato legado do dia 0001-01-01 de Brasília (meia-noite às 03h UTC)
    estourava a subtração com OverflowError — 500 no upload manual sem data. Para
    filtrar execuções, "desde o início do calendário" é o mesmo que "desde sempre"."""
    return max(momento, datetime.min + _JANELA_MAX_SINCRONIZACAO) - _JANELA_MAX_SINCRONIZACAO


def _dia_txt(dia: date) -> str:
    # À mão: o %Y do strftime não preenche anos com menos de 4 dígitos em todo SO.
    return f"{dia.day:02d}/{dia.month:02d}/{dia.year:04d}"


def _primeiro_dia_aceito(escola, agora_utc: datetime) -> date:
    """Piso da data do relatório: 1º de janeiro do ano letivo ANTERIOR ao ativo da
    escola (sem ano letivo, o anterior ao de hoje em Brasília). Antes disso é quase
    sempre erro de digitação — 2006 em vez de 2026 — e o ponto viraria a base de
    toda janela sem retrato anterior."""
    ano = getattr(escola, "ano_letivo_ativo", None) or para_br(agora_utc).year
    return date(max(ano - 1, 1), 1, 1)


def _conferir_data_do_relatorio(data_referencia: datetime, escola,
                                agora_utc: datetime, *, com_piso: bool = True) -> datetime:
    """Regras da DATA DO RELATÓRIO informada no upload manual (a sincronização não
    manda data). Recusa (422) data absurda ou anterior ao piso e dia de Brasília
    depois de hoje. Do dia de HOJE mas adiantada (relógio do aparelho à frente, e
    a tela manda "agora" quando a data é hoje), grava com o agora — antes, a 10 min
    de folga recusava o "hoje" de um notebook com o relógio errado. Devolve o
    instante a gravar. ``com_piso=False``: a data não foi digitada agora (ver
    ``piso_da_data`` em ``_confirmar_sem_commit``) — só a data absurda é recusada."""
    dia = _dia_em_brasilia(data_referencia)
    piso = _primeiro_dia_aceito(escola, agora_utc)
    if dia is None or (com_piso and dia < piso):
        quando = f"{_dia_txt(dia)} é anterior a {_dia_txt(piso)}" if dia else "fora do calendário"
        raise HTTPException(
            422,
            f"A data do relatório parece errada: {quando}. Confira o ano (o relatório "
            "precisa ser do ano letivo da escola ou do anterior). Nada foi gravado.")
    if dia > para_br(agora_utc).date():
        raise HTTPException(
            422,
            "A data do relatório está no futuro. Informe a data em que o relatório "
            "foi gerado na plataforma (hoje ou antes). Nada foi gravado.")
    if _instante_utc(data_referencia) > agora_utc:
        return agora_utc.replace(tzinfo=timezone.utc)
    return data_referencia


def _conferir_periodo_do_relatorio(dados: ImportacaoConfirm, escola,
                                   agora_utc: datetime, *, com_piso: bool = True) -> None:
    """O piso de ``_primeiro_dia_aceito`` também vale para o "Intervalo de datas"
    do Matific no upload manual: um início no ano 1 estourava o calendário (500) ao
    datar o retrato-base na véspera, e um de 1990 criava esse retrato em 1990. As
    datas do intervalo são as do calendário impresso (sem fuso), como na importação
    por período. ``com_piso=False`` (a pendência LEGADA reaplicada pelo /resolver,
    ver ``piso_da_data``): só o dia sem véspera no calendário (0001-01-01) é
    recusado — 422, em vez do OverflowError (500) ao datar o retrato-base."""
    if dados.plataforma != "matific" or dados.periodo_inicio is None \
            or dados.periodo_fim is None:
        return
    piso = _primeiro_dia_aceito(escola, agora_utc) if com_piso else date(1, 1, 2)
    for momento in (dados.periodo_inicio, dados.periodo_fim):
        dia = momento.replace(tzinfo=None).date()
        if dia < piso:
            quando = (f"{_dia_txt(dia)} é anterior a {_dia_txt(piso)}" if com_piso
                      else f"{_dia_txt(dia)} está fora do calendário")
            raise HTTPException(
                422,
                f"O intervalo de datas do relatório parece errado: {quando}. Confira o "
                "ano. Nada foi gravado.")


def _importacoes_da_sincronizacao(db: Session, escola_id: int, plataforma: str,
                                  importacao_ids) -> set[int]:
    """Quais destas importações vieram da SINCRONIZAÇÃO automática (não do upload
    manual). A importação não tem coluna de origem (e isto não pede migração): a
    prova é a própria execução da sincronização — a importação registrada nela, ou
    criada DENTRO da janela de uma execução desta escola e plataforma (a
    sincronização importa cada arquivo pelo mesmo /confirmar, no meio da execução).
    Um upload manual feito durante uma sincronização da mesma escola conta como
    dela: o erro, se houver, é pedir a data a mais, nunca gravar por cima."""
    from app.models import SincronizacaoExecucao as Execucao

    ids = {i for i in importacao_ids if i is not None}
    if not ids:
        return set()
    criadas = {
        imp_id: _instante_utc(criada)
        for imp_id, criada in db.execute(
            select(Importacao.id, Importacao.created_at)
            .where(Importacao.escola_id == escola_id, Importacao.id.in_(ids)))
        if criada is not None
    }
    if not criadas:
        return set()
    primeira = min(criadas.values()) - _JANELA_MAX_SINCRONIZACAO - _FOLGA_JANELA_SINCRONIZACAO
    ultima = max(criadas.values()) + _FOLGA_JANELA_SINCRONIZACAO
    execucoes = db.execute(
        select(Execucao.importacao_id, Execucao.iniciada_em, Execucao.finalizada_em)
        .where(Execucao.escola_id == escola_id, Execucao.plataforma == plataforma,
               Execucao.iniciada_em.isnot(None),
               Execucao.iniciada_em >= primeira, Execucao.iniciada_em <= ultima)
    ).all()
    diretas = {e.importacao_id for e in execucoes if e.importacao_id in criadas}
    janelas = []
    for e in execucoes:
        inicio = _instante_utc(e.iniciada_em)
        teto = inicio + _JANELA_MAX_SINCRONIZACAO
        fim = _instante_utc(e.finalizada_em) if e.finalizada_em is not None else teto
        janelas.append((inicio - _FOLGA_JANELA_SINCRONIZACAO,
                        min(fim, teto) + _FOLGA_JANELA_SINCRONIZACAO))
    return diretas | {imp_id for imp_id, criada in criadas.items()
                      if any(ini <= criada <= fim for ini, fim in janelas)}


def _alunos_com_sincronizacao_desde_o_retrato(db: Session, escola_id: int, plataforma: str,
                                              retratos: dict) -> set[int]:
    """Alunos cujo retrato ATUAL é de um dia (de Brasília) em que uma execução da
    sincronização desta escola e plataforma ainda RODAVA, ou de ANTES dela. Não
    depende de quem gravou o retrato por último: um upload COM data do mesmo dia
    complementa o retrato da sync no lugar e troca o ``importacao_id`` para o manual
    — sem esta regra, o upload SEM data seguinte passava e trocava, "como hoje", o
    que a sync coletou. Conta a JANELA da execução (até o fim dela, no máximo
    ``_JANELA_MAX_SINCRONIZACAO`` depois do início), não só o início: a sync que
    começa às 23h58 e grava o retrato às 00h02 é do dia do retrato — contando só o
    início, ela era "de ontem" e escapava. Qualquer execução conta (até a que
    falhou, ou a que caiu sem fim registrado): o erro, se houver, é pedir a data a
    mais, nunca gravar por cima."""
    from app.models import SincronizacaoExecucao as Execucao

    inicios = {}
    for aluno_id, snap in retratos.items():
        if snap is None or snap.data_referencia is None:
            continue
        inicio = _inicio_do_dia_em_brasilia(snap.data_referencia)
        if inicio is not None:
            inicios[aluno_id] = inicio
    if not inicios:
        return set()
    # Uma execução termina no máximo ``_JANELA_MAX_SINCRONIZACAO`` depois de começar:
    # a que chega ao dia mais antigo começou, no máximo, essa janela antes dele.
    filtro = (Execucao.escola_id == escola_id, Execucao.plataforma == plataforma,
              Execucao.iniciada_em.isnot(None),
              Execucao.iniciada_em >= _janela_antes(min(inicios.values())))
    ultima = db.scalar(select(func.max(Execucao.iniciada_em)).where(*filtro))
    if ultima is None:
        return set()
    # O fim mais tardio está entre as execuções iniciadas na janela antes da última
    # (o fim de cada uma fica entre o início e início + janela): poucas linhas,
    # nunca o histórico inteiro de sincronizações da escola. O início da última já é
    # um fim mínimo (a regra de antes, pelo início, continua contida nesta).
    fins = [_instante_utc(ultima)]
    for iniciada, finalizada in db.execute(
            select(Execucao.iniciada_em, Execucao.finalizada_em)
            .where(*filtro,
                   Execucao.iniciada_em >= _janela_antes(_instante_utc(ultima)))):
        iniciada = _instante_utc(iniciada)
        teto = iniciada + _JANELA_MAX_SINCRONIZACAO
        fim = min(_instante_utc(finalizada), teto) if finalizada is not None else teto
        fins.append(max(fim, iniciada))
    ultimo_fim = max(fins)
    return {aluno_id for aluno_id, inicio in inicios.items() if inicio <= ultimo_fim}


# Sentinela: "não pré-carregado — consulte o snapshot você mesmo".
_SEM_PRECARGA = object()


def _mapa_snapshot_atual(db: Session, escola_id: int, aluno_ids, modelo, *,
                         ate=None) -> dict:
    """Último snapshot (por data_referencia, id) de CADA aluno, numa ÚNICA
    consulta. Equivale a chamar _snapshot_atual por aluno, sem o N+1: ordena
    ascendente e o último visto por aluno é o mais recente. Como a sessão usa
    autoflush=False, é semanticamente idêntico ao SELECT por aluno. ``ate`` (UTC
    naive): ignora retratos datados depois dele (``_teto_retrato_valido``)."""
    ids = list(aluno_ids)
    if not ids:
        return {}
    mapa: dict = {}
    consulta = select(modelo).where(modelo.escola_id == escola_id, modelo.aluno_id.in_(ids))
    if ate is not None:
        consulta = consulta.where(modelo.data_referencia <= ate)
    for snap in db.execute(
        consulta.order_by(modelo.data_referencia.asc(), modelo.id.asc())
    ).scalars():
        mapa[snap.aluno_id] = snap
    return mapa


def _retrodatado(atual, data_referencia) -> bool:
    """O relatório é de um DIA (de Brasília) ANTERIOR ao do retrato atual do aluno?
    Do mesmo dia ou mais novo, vale o de sempre: complementa/atualiza no lugar o
    retrato do dia, ou nasce o retrato novo herdando do atual."""
    if atual is None or atual.data_referencia is None or data_referencia is None:
        return False
    return (not _mesmo_dia(atual.data_referencia, data_referencia)
            and _instante_utc(data_referencia) < _instante_utc(atual.data_referencia))


def _mapa_retrato_na_data(db: Session, escola_id: int, aluno_ids, modelo,
                          data_referencia, *, ate=None) -> dict:
    """O retrato que VALIA na data do relatório, de cada aluno, numa ÚNICA consulta:
    o do MESMO DIA (de Brasília) — que o relatório complementa no lugar, como faz
    com o retrato atual do dia — ou, sem ele, o último ANTES dessa data. Aluno sem
    nenhum fica fora do mapa: não há de onde herdar o que o relatório não traz.
    ``ate`` (UTC naive): retrato datado depois dele não vale (``_teto_retrato_valido``)."""
    ids = list(aluno_ids)
    if not ids:
        return {}
    ref = _instante_utc(data_referencia)
    # O dia de Brasília do relatório acaba menos de 24 h depois do instante dele.
    limite = ref + timedelta(days=1)
    if ate is not None:
        limite = min(limite, ate)
    antes: dict = {}
    do_dia: dict = {}
    for snap in db.execute(
        select(modelo)
        .where(modelo.escola_id == escola_id, modelo.aluno_id.in_(ids),
               modelo.data_referencia <= limite)
        .order_by(modelo.data_referencia.asc(), modelo.id.asc())
    ).scalars():
        if _mesmo_dia(snap.data_referencia, data_referencia):
            do_dia[snap.aluno_id] = snap
        elif _instante_utc(snap.data_referencia) <= ref:
            antes[snap.aluno_id] = snap
    return {**antes, **do_dia}


# Rótulos (sem PII) dos campos de retrato que um relatório pode não trazer.
_ROTULO_CAMPO_RETRATO = {
    "atividades": "atividades", "estrelas": "estrelas", "pontuacao_media": "pontuação média",
    "livros_unicos": "livros lidos", "livros_por_nivel": "livros por nível",
    "tempo_leitura_min": "tempo de leitura", "questoes_tentativas": "questões respondidas",
    "questoes_acertos": "questões aprovadas",
}


def _campos_herdados(plataforma: str, dados: dict) -> list[str]:
    """Campos que a linha NÃO traz e que ``_importar_matific`` /
    ``_importar_elefante_resumo`` completariam com o retrato anterior — a mesma
    regra de "ausente" de cada um (chave fora do dicionário; no Elefante, níveis e
    livros como ``None``, e livros só herdam sem a distribuição por nível)."""
    if plataforma == "matific":
        return [c for c in ("atividades", "estrelas", "pontuacao_media") if c not in dados]
    faltam = []
    if dados.get("livros_por_nivel") is None:
        faltam.append("livros_por_nivel")
    if dados.get("livros_unicos") is None and not dados.get("livros_por_nivel"):
        faltam.append("livros_unicos")
    faltam.extend(c for c in ("tempo_leitura_min", "questoes_tentativas", "questoes_acertos")
                  if c not in dados)
    return faltam


# --- Etapa 1: prévia (PRD §51) ------------------------------------------------

@router.post("/analisar", response_model=AnaliseOut)
async def analisar(
    request: Request,
    escola_id: int = Depends(escola_autorizada),
    arquivo: UploadFile | None = File(default=None),
    texto: str | None = Form(default=None),
    plataforma: str | None = Form(default=None),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    if plataforma not in (None, "", "matific", "elefante"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Plataforma desconhecida.")
    plataforma = plataforma or None
    # CONTRATO: plataforma de módulo fora do plano da rede não é importada
    # (minimização). Escolhida no formulário → 403 antes de ler o arquivo;
    # detectada pelo parser → 403 depois da análise, ANTES de arquivar o original
    # e de casar nomes (nada da prévia fica no disco nem no banco).
    modulos = svc_modulos.modulos_da_escola(db, db.get(Escola, escola_id))
    svc_modulos.exigir_plataforma(modulos, plataforma)

    # Rejeita corpos gigantes pelo Content-Length antes de ler o arquivo.
    declarado = request.headers.get("content-length")
    if declarado and declarado.isdigit() and int(declarado) > TAMANHO_MAXIMO + 1_000_000:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            "Arquivo acima de 10 MB.")

    arquivo_token = None
    arquivo_nome = None
    guardar_como = None     # extensão do original a arquivar (depois do contrato)
    if arquivo is not None:
        conteudo = await arquivo.read()
        if len(conteudo) > TAMANHO_MAXIMO:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                                "Arquivo acima de 10 MB.")
        arquivo_nome = arquivo.filename or "relatorio"
        # Detecção de tipo por FONTE ÚNICA (mesma regra usada pelo sync/
        # orchestrator) — cobre nome, content-type e magic bytes (PDF, ZIP do
        # xlsx e OLE2 do xls) mesmo sem extensão confiável (upload mobile).
        tipo_arquivo = svc.detectar_tipo(conteudo, arquivo_nome, arquivo.content_type or "")
        eh_pdf = tipo_arquivo == "pdf"
        eh_planilha = tipo_arquivo == "xlsx"
        if eh_planilha:
            _limpar_temporarios_orfaos()
            try:
                # Parsing CPU-bound (openpyxl) fora do event loop — não trava os
                # demais requests durante a leitura da planilha. O teto do
                # DESCOMPRIMIDO (bomba de descompressão: o limite de 10 MB acima é do
                # arquivo COMPRIMIDO) e o orçamento de leitura ficam dentro do parser
                # e chegam aqui como PlanilhaRecusada.
                analise = await run_in_threadpool(
                    planilhas.analisar_planilha,
                    conteudo, plataforma, nome_arquivo=arquivo_nome or "")
            except planilhas.PlanilhaRecusada as exc:
                raise HTTPException(exc.status_http, str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
            except Exception as exc:  # noqa: BLE001 — planilha inesperada
                # NÃO logar o filename: relatórios individuais trazem o nome do
                # aluno (PII de menor) no nome do arquivo, e o log/Sentry são
                # processadores retidos (LGPD/§14). Contexto de debug não-PII:
                logger.exception("Falha ao ler planilha (escola %s, tipo xlsx, %d bytes)",
                                 escola_id, len(conteudo))
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "Não foi possível ler a planilha. O arquivo está íntegro?") from exc
            guardar_como = "xlsx"
            tipo = "xlsx"
        elif eh_pdf:
            _limpar_temporarios_orfaos()
            try:
                # Perfis posicionais (formatos reais) com as 4 estratégias
                # genéricas de texto como rede de segurança.
                # Parsing CPU-bound (pdfplumber/pypdf) fora do event loop. O teto do
                # DESCOMPRIMIDO e das páginas (bomba de descompressão: o limite de 10 MB
                # acima é do arquivo COMPRIMIDO) fica dentro do parser, antes do
                # pdfplumber, e chega aqui como PdfRecusado (413/422).
                analise = await run_in_threadpool(
                    perfis_pdf.analisar_pdf, conteudo, plataforma,
                    nome_arquivo=arquivo_nome or "")
            except perfis_pdf.PdfRecusado as exc:
                raise HTTPException(exc.status_http, str(exc)) from exc
            except HTTPException:
                raise  # mensagem útil do parser genérico chega ao usuário
            except Exception as exc:
                # NÃO logar o filename (nome do aluno = PII de menor) — ver acima.
                logger.exception("Falha ao analisar PDF (escola %s, tipo pdf, %d bytes)",
                                 escola_id, len(conteudo))
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "Não foi possível ler o PDF. O arquivo está íntegro?") from exc
            guardar_como = "pdf"
            tipo = "pdf"
        else:
            texto = conteudo.decode("utf-8", errors="replace")
            tipo = "texto"
            payload_mat = _payload_matific_placar(texto)
            analise = (svc.analisar_matific_api(payload_mat) if payload_mat is not None
                       else await run_in_threadpool(svc.analisar_texto, texto, plataforma))
    elif texto and texto.strip():
        tipo = "texto"
        payload_mat = _payload_matific_placar(texto)
        analise = (svc.analisar_matific_api(payload_mat) if payload_mat is not None
                   else await run_in_threadpool(svc.analisar_texto, texto, plataforma))
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Envie um arquivo PDF ou cole o texto do relatório.")
    svc_modulos.exigir_plataforma(modulos, analise.plataforma)
    if guardar_como:
        arquivo_token = _guardar_temporario(conteudo, guardar_como)
    if analise.linhas:
        # PRÉVIA = CONFIRMAÇÃO: a mesma porta única de identidade do /confirmar.
        svc.casar_nomes(db, escola_id, analise.linhas, plataforma=analise.plataforma,
                        turma_padrao=analise.turma_detectada)

    nomes_unicos = {svc.chave_nome(l.nome) for l in analise.linhas if l.nome}
    # A escola do relatório × a cadastrada: só AVISO (nomes variam; a identidade
    # das contas é que barra a conta de outra escola — ``marcar_ids_de_outra_escola``).
    from app.sync import escola_externa
    escola_cadastrada = db.get(Escola, escola_id)
    escola_detectada = str(getattr(analise, "escola_detectada", "") or "").strip()
    aviso_escola = escola_externa.aviso_de_nome(
        escola_detectada, escola_cadastrada.nome if escola_cadastrada else "")
    return AnaliseOut(
        plataforma=analise.plataforma,
        formato=analise.formato,
        tipo=tipo,
        arquivo_token=arquivo_token,
        arquivo_nome=arquivo_nome,
        estrategia=analise.estrategia,
        mensagem_deteccao=analise.mensagem_deteccao,
        turma_detectada=analise.turma_detectada,
        escola_detectada=escola_detectada[:200],
        aviso_escola=aviso_escola,
        origem_nome=analise.origem_nome,
        periodo_inicio=analise.periodo_inicio,
        periodo_fim=analise.periodo_fim,
        criacao_bloqueada_por_politica=not politica_sync.pode_criar_aluno(db, escola_id),
        total_alunos=len(nomes_unicos),
        total_linhas=len(analise.linhas),
        total_erros=sum(1 for l in analise.linhas if l.erros) + len(analise.erros_gerais),
        total_avisos=sum(1 for l in analise.linhas if l.avisos),
        erros_gerais=analise.erros_gerais,
        linhas=[
            {
                "numero": l.numero,
                "nome": l.nome,
                "dados": l.dados,
                "erros": l.erros,
                "avisos": l.avisos,
                "correspondencia": l.correspondencia,
            }
            for l in analise.linhas
        ],
    )


# --- Etapa 2: confirmação -----------------------------------------------------

def _payload_matific_placar(texto: str) -> dict | None:
    """Reconhece o JSON exportado pelo bookmarklet do Placar do Matific (coleta
    pela API interna, feita na aba logada do gestor — sem PDF, com nome completo).
    Marcado por ``fonte='matific-placar'`` + ``alunos[]``. Devolve o payload ou
    None (aí segue como texto normal)."""
    t = (texto or "").lstrip()
    if not t.startswith("{") or "matific-placar" not in t:
        return None
    try:
        dados = json.loads(t)
    except (ValueError, TypeError):
        return None
    if (isinstance(dados, dict) and dados.get("fonte") == "matific-placar"
            and isinstance(dados.get("alunos"), list)):
        return dados
    return None


_RE_SERIE_NO_NOME = re.compile(r"^\s*(\d)\s*[ºo°]?\s*(?:ano)?\b", re.IGNORECASE)


#: "1 FASE A", "2 FASE B" — o mesmo dígito à frente, mas de uma ETAPA, não de um
#: ano. Captura o dígito e a palavra para o rótulo sair fiel.
_RE_ETAPA_NO_NOME = re.compile(
    r"^\s*(\d)\s*[ªa]?\s*(fase|etapa)\b", re.IGNORECASE)


def _ano_escolar_do_nome(nome: str) -> str:
    """Deriva a série do nome da turma: "5 ANO B MANHA ANUAL" → "5º Ano".

    FABRICAVA ANO A PARTIR DE FASE. O ``(?:ano)?`` do padrão é OPCIONAL, então
    "1 FASE A" casava o dígito, não casava "ano", e saía daqui como ``"1º Ano"``
    — uma turma de Educação Infantil entrando no banco com rótulo de Fundamental.
    Depois disso nenhuma regra a jusante consegue excluí-la da premiação: o dado
    já chegou mentindo. Agora a etapa é reconhecida ANTES e o rótulo sai fiel
    ("1ª Fase"), que é o mesmo que a Lista Piloto grava quando vem a aba certa.
    """
    etapa = _RE_ETAPA_NO_NOME.match(nome or "")
    if etapa:
        return f"{etapa.group(1)}ª {etapa.group(2).capitalize()}"
    par = _RE_SERIE_NO_NOME.match(nome or "")
    return f"{par.group(1)}º Ano" if par else ""


def _inserir_turma(db: Session, escola_id: int, ano: int, nome: str,
                   ano_escolar: str, *, turno: str | None = None,
                   observacoes: str | None = None,
                   codigo_externo: str | None = None) -> tuple[Turma, bool]:
    """Cria a turma isolando a colisão do índice único uq_turma_escola_ano_nome
    num savepoint: se uma importação concorrente já criou a MESMA turma (mesmo
    escola+ano+nome), devolve a existente em vez de estourar 500 — mesmo padrão
    de _inserir_credencial_nova. Retorna (turma, criada_agora)."""
    try:
        with db.begin_nested():
            turma = Turma(escola_id=escola_id, nome=nome, ano_letivo=ano,
                          ano_escolar=ano_escolar, turno=turno,
                          observacoes=observacoes, codigo_externo=codigo_externo or None)
            db.add(turma)
            db.flush()
        return turma, True
    except IntegrityError:
        existente = db.execute(
            select(Turma).where(Turma.escola_id == escola_id,
                                Turma.ano_letivo == ano,
                                Turma.nome == nome).limit(1)
        ).scalars().first()
        if existente is None:  # colisão que não é a nossa: repropaga
            raise
        return existente, False


def _turma_pelo_nome(db: Session, escola_id: int, ano: int, nome: str,
                     avisos: list[str], turmas_novas: dict,
                     permitir_criar: bool = True) -> Turma | None:
    """Acha ou CRIA a turma do relatório, SEMPRE pela identidade CANÔNICA (a mesma
    do caminho da Lista Piloto), nunca pelo nome cru. Ordem de casamento:
      1) código externo (SED/Censo entre parênteses) — idempotência mais forte;
      2) chave canônica série+letra (chave_turma_norm) contra TODAS as turmas da
         escola/ano — "4 ANO C INTEGRAL (300303525)" reaproveita "4ºC";
      3) na dúvida (formato sem série+letra: Maternal/Pré/EJA), cria.
    Ao criar, grava o NOME NORMALIZADO ("4ºC") e o código externo FORA do nome.
    O cache do lote é indexado pela chave canônica, então variantes da mesma sala
    no mesmo arquivo colapsam.
    ``permitir_criar=False`` (sincronização automática) NÃO cria turma que não exista
    no cadastro — só reaproveita a canônica; turma desconhecida vira aviso p/ análise
    (gate anti-turma-fantasma). A Lista Piloto e o import manual (opt-in) passam True."""
    nome_cru = (nome or "").strip()
    if not nome_cru:
        return None
    codigo = matriculas.codigo_externo_do_nome(nome_cru)
    chave = matriculas.chave_turma_norm(nome_cru)
    if chave in turmas_novas:
        turma = turmas_novas[chave]
        if codigo and not turma.codigo_externo:   # completa o código em reencontros
            turma.codigo_externo = codigo
        return turma

    turma: Turma | None = None
    if codigo:
        por_codigo = db.execute(
            select(Turma).where(Turma.escola_id == escola_id,
                                Turma.ano_letivo == ano,
                                Turma.codigo_externo == codigo).order_by(Turma.id)
        ).scalars().all()
        if len(por_codigo) == 1:
            turma = por_codigo[0]
    if turma is None:
        # Casa pela chave canônica (série+letra) contra as turmas já cadastradas —
        # resolve o furo do formato ("4ºC" vs "4 ANO C INTEGRAL (cod)") que o nome
        # exato/overlap frágil deixava passar. (Roda 1x por sala distinta: o cache
        # por chave abaixo evita repetir a varredura para cada aluno da turma.)
        # NUNCA "a primeira que aparecer": com 2+ turmas na mesma sala, só decide
        # pelo nome idêntico; sem isso, não escolhe (a linha vai para revisão).
        mesma_sala = [t for t in db.execute(
            select(Turma).where(Turma.escola_id == escola_id,
                                Turma.ano_letivo == ano).order_by(Turma.id)).scalars()
            if matriculas.chave_turma_norm(t.nome) == chave]
        if len(mesma_sala) == 1:
            turma = mesma_sala[0]
        elif len(mesma_sala) > 1:
            alvos = {nome_cru.casefold(), matriculas.nome_turma_exibicao(nome_cru).casefold()}
            iguais = [t for t in mesma_sala if t.nome.strip().casefold() in alvos]
            if len(iguais) != 1:
                aviso = (f"Mais de uma turma cadastrada corresponde a “{nome_cru}” "
                         f"({', '.join(t.nome for t in mesma_sala)}) — nenhum aluno foi "
                         "criado por esta linha; escolha a turma na revisão.")
                if aviso not in avisos:
                    avisos.append(aviso)
                return None
            turma = iguais[0]
    if turma is None:
        if not permitir_criar:
            # GATE anti-turma-fantasma (item 4): a turma do relatório da plataforma
            # NÃO existe no cadastro da escola e este fluxo (sincronização automática)
            # não pode inventar turma. Não cria; avisa p/ análise. A Lista Piloto
            # (fonte oficial) e o import manual com opt-in continuam podendo criar.
            aviso = (
                f"A turma “{matriculas.nome_turma_exibicao(nome_cru)}” do relatório "
                "não existe no cadastro desta escola — nenhum aluno foi criado nela "
                "(sincronização automática não cria turmas). Cadastre-a pela Lista "
                "Piloto ou associe manualmente.")
            if aviso not in avisos:
                avisos.append(aviso)
            return None
        nome_norm = matriculas.nome_turma_exibicao(nome_cru)
        turma, criada = _inserir_turma(
            db, escola_id, ano, nome_norm,
            _ano_escolar_do_nome(nome_cru) or _ano_escolar_do_nome(nome_norm) or nome_norm[:20],
            codigo_externo=codigo or None)
        if criada:
            registrar(db, "turma.criada", escola_id=escola_id, entidade="turma",
                      entidade_id=turma.id,
                      detalhes={"nome": nome_norm, "codigo_externo": codigo or None,
                                "origem": "importacao"})
            avisos.append(
                f"Turma “{nome_norm}” criada automaticamente a partir do relatório.")
    elif codigo and not turma.codigo_externo:
        turma.codigo_externo = codigo             # idempotência p/ próximas syncs
    turmas_novas[chave] = turma
    return turma


def _ra_forte(valor) -> str:
    """RA utilizável como IDENTIDADE, normalizado (``lista_piloto.ra_util``): tira
    pontuação/caixa e devolve "" para placeholders ('0', 'S/RA'...). Usado nos DOIS
    lados de toda comparação — se um lado viesse cru ("901.000.001-0") e o outro
    normalizado ("9010000010"), o motor leria RAs "divergentes" e vetaria o
    casamento da MESMA criança (duplicata), e dois placeholders "0" iguais
    "corroborariam" crianças diferentes."""
    return ida.ra_forte(valor)


def _aluno_existente_na_turma(db: Session, escola_id: int, ano: int,
                              turma_id: int, nome: str, numero_chamada: int | None = None,
                              nascimento=None, ra: str | None = None) -> Aluno | None:
    """Aluno já matriculado nesta turma/ano cujo nome normalizado casa. Torna o
    /confirmar idempotente sob a trava por escola: um reenvio sobreposto do MESMO
    relatório (double-click, retry de proxy/mobile) reaproveita em vez de recriar
    — alunos não têm unique constraint (dois homônimos reais são legítimos), então
    a defesa é este re-casamento contra o banco (mesma filosofia do /matriculas).
    VETO de identidade: se o cadastro de mesmo nome tem nascimento/RA/nº de chamada
    DIVERGENTE da linha, é OUTRA criança (gêmeo/homônimo) — não reusa (senão o caso
    "conflito de identidade" cairia num vínculo silencioso pelo nome exato)."""
    alvo = svc.chave_nome(nome)
    linha_ident = matching.Identidade(chamada=numero_chamada, nascimento=nascimento,
                                      ra=_ra_forte(ra))
    achados: list[Aluno] = []
    for aluno in db.execute(
        select(Aluno).join(Matricula, Matricula.aluno_id == Aluno.id)
        .where(Aluno.escola_id == escola_id, Matricula.turma_id == turma_id,
               Matricula.ano_letivo == ano, Aluno.status != "excluido")
    ).scalars():
        if svc.chave_nome(aluno.nome) != alvo:
            continue
        if matching.conflito_identidade(linha_ident, matching.Identidade(
                chamada=aluno.numero_chamada, nascimento=aluno.data_nascimento,
                ra=_ra_forte((aluno.ficha or {}).get("ra")))):
            continue                  # mesmo nome, identidade prova ser outra criança
        achados.append(aluno)
    # 1 match não-conflitante → reusa (idempotência de reenvio do MESMO relatório).
    # 2+ (HOMÔNIMOS reais na turma, sem identificador que os desempate) → AMBÍGUO:
    # não reusa nenhum às cegas; devolve None para o casamento pelo motor decidir
    # (2+ candidatos → revisão, nunca atribui os dados à criança errada).
    return achados[0] if len(achados) == 1 else None


def _roster_identidades(db: Session, escola_id: int, ano: int, turma_id: int
                        ) -> tuple[list[matching.Identidade], dict[int, Aluno]]:
    """Alunos matriculados na turma/ano como ``Identidade`` (para o motor) + mapa
    id→Aluno (para devolver o objeto ao vincular).

    NÃO filtra por ``status``. "Saiu da lista atual" (``fora_lista_piloto``) e
    "foi arquivado" NÃO são "não existe": a pessoa continua no banco e continua
    sendo uma identidade válida. Filtrar aqui era a 2ª causa raiz das duplicatas
    — bastava a criança cair da Lista Piloto (o que ``_marcar_fora_da_lista`` faz
    sozinho a cada confirmação) para a importação seguinte da plataforma não a
    encontrar e abrir uma segunda ficha, calada.

    Resolver IDENTIDADE e decidir MATRÍCULA são coisas separadas: reconhecer o
    aluno aqui não reativa ninguém — quem estava arquivado segue arquivado."""
    ids: list[matching.Identidade] = []
    por_id: dict[int, Aluno] = {}
    for aluno in db.execute(
        select(Aluno).join(Matricula, Matricula.aluno_id == Aluno.id)
        .where(Aluno.escola_id == escola_id, Matricula.turma_id == turma_id,
               Matricula.ano_letivo == ano, Aluno.status != "excluido")
    ).scalars():
        por_id[aluno.id] = aluno
        ids.append(_identidade_do_aluno(aluno))
    return ids, por_id


def _identidade_do_aluno(aluno: Aluno) -> matching.Identidade:
    """Aluno do banco → ``matching.Identidade`` (a moeda do motor único). Um só
    lugar monta isto, para que TODOS os fluxos comparem os mesmos campos com a
    mesma normalização (RA por ``_ra_forte``)."""
    return ida.identidade_do_aluno(aluno)


def _casar_no_roster(db: Session, escola_id: int, ano: int, nome: str,
                     turma: Turma, numero_chamada: int | None = None,
                     nascimento=None, ra: str | None = None,
                     *, permitir_subconjunto_unico: bool = False
                     ) -> tuple[Aluno | None, str]:
    """Casa a linha de plataforma (Elefante/Matific) contra o ROSTER da turma
    canônica ANTES de criar — o núcleo de "1 aluno = 1 perfil". Delega ao MOTOR
    ÚNICO (``matching.classificar_linha``, o mesmo da prévia/detecção) e traduz o
    status para a confiança do import:
      * VINCULADO → "alta"  (auto-vincula: nome exato/abreviação OU variante/typo de
        grafia com 1 único candidato na turma, ou identificador forte — chamada/RA/
        nascimento/UUID — corroborando);
      * REVISAR   → "media" (correspondência INSEGURA → NÃO cria; vai p/ revisão),
        com QUALQUER número de candidatos;
      * BLOQUEADO/NOVO → "baixa" (cria novo — bloqueado = nome casa mas a identidade
        prova ser outra criança; novo = ninguém plausível).

    "REVISAR significa REVISAR": antes, um REVISAR de candidato ÚNICO (parcial /
    subconjunto de nome) escapava pelo `len(candidatos) >= 2` e virava "baixa" —
    o import criava a ficha e contava com a fusão manual depois. Era a 1ª causa
    raiz das duplicatas. Confiança BAIXA agora significa "o motor não achou
    ninguém plausível", nunca "não deu para decidir"."""
    if not svc.tokens_nome(nome):
        return None, "baixa"
    linha = matching.Identidade(nome=nome, chamada=numero_chamada,
                                nascimento=nascimento, ra=_ra_forte(ra))
    roster, por_id = _roster_identidades(db, escola_id, ano, turma.id)
    # `permitir_subconjunto_unico` (ligado SÓ pelo import de PLATAFORMA, ver
    # _resolver_aluno; NUNCA no cadastro manual/roster): a planilha da plataforma só
    # traz alunos matriculados → 1 único candidato PARCIAL (nome subconjunto) na turma
    # é atribuição determinística ao dono, não fusão (ver classificar_linha).
    # Ambiguidade e grafia insegura seguem em revisão.
    res = matching.classificar_linha(
        linha, roster, permitir_subconjunto_unico=permitir_subconjunto_unico)
    if res.status == matching.VINCULADO and res.aluno_id in por_id:
        return por_id[res.aluno_id], "alta"
    if res.status == matching.REVISAR:
        return None, "media"          # INSEGURO (1, 2 ou N candidatos) → revisão
    # Chega aqui só: NOVO (ninguém plausível) ou BLOQUEADO (identidade prova ser
    # outra criança). Nos dois, criar uma ficha nova é a decisão CORRETA.
    return None, "baixa"


def _resolver_aluno(db: Session, escola_id: int, ano: int, linha, avisos: list[str],
                    criados: dict | None = None,
                    turmas_novas: dict | None = None,
                    permitir_criar_turma: bool = True, *,
                    permitir_criar_aluno: bool = True,
                    plataforma: str | None = None,
                    ctx: "ida.Contexto | None" = None,
                    revisoes: "ida.ColetorRevisoes | None" = None,
                    usuario_id: int | None = None,
                    encerrar_revisoes: bool = True,
                    descartes: dict | None = None) -> Aluno | None:
    """Aplica à linha a decisão da PORTA ÚNICA de identidade
    (``identidade_aluno.decidir``) — a MESMA que a prévia mostrou:

      * ASSOCIAR → devolve a ficha e grava a identidade externa (UUID do Matific /
        studentId do Elefante) nela, para a próxima sincronização casar direto; e
        ENCERRA a revisão pendente desta mesma identidade e do mesmo tipo de dado,
        que a linha acabou de responder (``_encerrar_revisoes_respondidas`` —
        ``encerrar_revisoes=False`` só no /resolver, que fecha as pendências ele
        mesmo);
      * REVISAR  → NÃO associa e NÃO cria: a linha vai INTEIRA para a fila de
        revisão (``RevisaoIdentidade``), com candidatos e motivo, e é devolvida em
        ``ignorados`` (a sync não avança o cursor desse aluno);
      * CRIAR    → só quando não há candidato algum: cria a ficha na turma da sala
        (decidida sem chute) e grava a identidade externa já na criação.

    Linha que a ESCOLA já decidiu não aplicar (``MOTIVOS_DESCARTE_DECIDIDO`` —
    conta aposentada) é contada em ``descartes[motivo]`` quando o chamador passa o
    dict: o núcleo a tira de ``ignorados`` e de 'sem_vinculo'.

    ``ctx``/``revisoes`` vêm do /confirmar (estado carregado 1x, fila gravada no
    fim); chamado avulso, carrega o próprio estado e grava a revisão na hora."""
    dados = getattr(linha, "dados", None) or {}
    if ctx is None:
        ctx = ida.carregar_contexto(db, escola_id, ano)
    turmas_novas = turmas_novas if turmas_novas is not None else {}

    ident, turma_nome, turma_invalida = _identidade_da_linha(db, escola_id, linha, plataforma)
    if turma_invalida:
        avisos.append(f"Linha “{linha.nome}”: turma inválida — ignorada.")
        return None
    if linha.aluno_id is None and not svc.tokens_nome(linha.nome):
        avisos.append(f"Linha “{linha.nome}”: sem nome utilizável — ignorada.")
        return None
    decisao = ida.decidir(ctx, ident)
    if getattr(linha, "deixar_para_revisao", False) and decisao.acao in (ida.ASSOCIAR,
                                                                          ida.CRIAR):
        # "Deixar para a Revisão" é uma instrução, não um palpite: a linha não
        # associa nem cria, mesmo quando o contexto mudou desde a prévia (a outra
        # conta da disputa foi ignorada, por exemplo). Com o motivo do backend quando
        # ele também revisaria (abaixo); senão, com o pedido de quem confirmou.
        decisao = replace(decisao, acao=ida.REVISAR, motivo="deixada_para_revisao")

    if decisao.acao == ida.IGNORAR:
        if decisao.motivo == "identidade_aposentada":
            alvo = ctx.alunos.get(decisao.aluno_id)
            avisos.append(
                f"“{linha.nome}”: esta conta da plataforma foi APOSENTADA no Constela "
                f"para {alvo.nome if alvo else 'o aluno'} — a criança tem outra conta "
                "nesta plataforma, e a escola escolheu qual vale. A linha não foi "
                "aplicada e o histórico dela continua guardado. (A conta segue "
                "existindo na plataforma: a aposentadoria é interna do Constela.)")
            if descartes is not None:
                descartes[decisao.motivo] = descartes.get(decisao.motivo, 0) + 1
            return None
        avisos.append(f"Linha “{linha.nome}”: "
                      + ("aluno não pertence a esta escola" if decisao.motivo == "aluno_de_outra_escola"
                         else "a ficha escolhida foi excluída e não recebe dados")
                      + " — ignorada.")
        return None

    if decisao.acao == ida.REVISAR:
        _enfileirar_revisao(db, escola_id, ctx, ident, decisao, dados, avisos,
                            revisoes, usuario_id)
        return None

    if decisao.acao == ida.ASSOCIAR:
        aluno = ctx.alunos[decisao.aluno_id]
        vinculou = _vincular_identidade(db, escola_id, aluno.id, ident.plataforma,
                                        ident.id_externo, ctx=ctx, usuario_id=usuario_id)
        outra_escola = (ctx.ids_de_outra_escola.get((ident.plataforma, ident.id_externo))
                        if decisao.via == "explicito" and ident.id_externo else None)
        if outra_escola is not None and vinculou:
            # D10 na importação manual: a escolha explícita de uma conta EFETIVA em
            # outra escola só chega aqui com o Admin Global (``decidir``, passo 0;
            # a da gestão da escola foi para a revisão). Aviso do efeito lá e trilha
            # própria (quem, qual conta, qual outra escola) — como no /resolver.
            avisos.append(f"“{linha.nome}”: {ida.AVISO_CONTA_DE_OUTRA_ESCOLA}")
            registrar(db, "identidade.importacao_outra_escola_confirmada",
                      escola_id=escola_id, usuario_id=usuario_id, entidade="aluno",
                      entidade_id=aluno.id,
                      detalhes={"plataforma": ident.plataforma,
                                "id_externo": ident.id_externo,
                                "outra_escola_id": outra_escola,
                                "importacao_id": getattr(revisoes, "importacao_id", None),
                                "aviso": "conta continua efetiva na outra escola"})
        _marcar_via(linha, decisao.via)
        chave_log = (svc.chave_nome(linha.nome), aluno.id)
        if (decisao.via not in ("identidade", "exato", "explicito", "ra", "revisao")
                and (criados is None or chave_log not in criados)):
            # AUDITORIA (regra §17): vínculo decidido pelo motor sem nome idêntico
            # (abreviação, parcial estrutural, grafia segura, identificador).
            turma = ctx.turma_do_aluno(aluno.id)
            detalhes = {"origem": linha.nome, "aluno": aluno.nome,
                        "turma": turma.nome if turma is not None else turma_nome,
                        "confianca": "alta", "candidatos": 1,
                        "correspondencia": decisao.via,
                        "motivo": "único candidato plausível na mesma sala"}
            if decisao.preteridos:
                # DESEMPATE "oficial × duplicata" (``lista_piloto_unica``): havia
                # MAIS de um candidato na sala. O rastro diz quantos, quem perdeu e
                # por quê — "1 candidato" seria falso e esconderia as fichas que a
                # fusão administrativa ainda precisa juntar à oficial.
                detalhes.update(
                    candidatos=1 + len(decisao.preteridos),
                    preteridos=_preteridos(ctx, decisao.preteridos),
                    motivo=_MOTIVO_DESEMPATE)
            registrar(db, "aluno.vinculado_auto", escola_id=escola_id,
                      usuario_id=usuario_id, entidade="aluno", entidade_id=aluno.id,
                      detalhes=detalhes)
        if encerrar_revisoes:
            _encerrar_revisoes_respondidas(
                db, escola_id, ctx, ident, decisao, aluno, avisos,
                coletor=revisoes, usuario_id=usuario_id)
        if criados is not None:
            criados[chave_log] = aluno
        return aluno

    # CRIAR — nenhum candidato plausível. Turma: a decidida pela porta única; se a
    # sala ainda não tem turma cadastrada, cria (import manual) ou revisa (sync).
    turma = ctx.turmas.get(decisao.turma_id) if decisao.turma_id is not None else None
    if turma is None and decisao.turma_id is not None:
        turma = db.get(Turma, decisao.turma_id)
    if turma is None:
        turma = (_turma_pelo_nome(db, escola_id, ano, str(turma_nome), avisos, turmas_novas,
                                  permitir_criar=permitir_criar_turma)
                 if str(turma_nome).strip() else None)
        if turma is None:
            # Sem turma onde criar (linha sem turma, ou turma fora do cadastro na
            # sincronização): a linha NÃO se perde — vai para a revisão.
            _enfileirar_revisao(db, escola_id, ctx, ident,
                                replace(decisao, acao=ida.REVISAR,
                                        motivo=("turma_nao_cadastrada"
                                                if str(turma_nome).strip() else "sem_turma")),
                                dados, avisos, revisoes, usuario_id)
            return None
        ctx.registrar_turma(turma)

    # REDE DE SEGURANÇA da turma de destino, qualquer que tenha sido o caminho até
    # ela (porta única, código externo do relatório, turma escolhida): ficha e
    # matrícula NOVAS só nascem em turma ATIVA do ANO LETIVO ATIVO. A criança que já
    # está numa turma arquivada continua recebendo dados pelo ASSOCIAR acima — isto
    # só barra a criação.
    # Também a ETAPA: "1 ANO A …" não nasce na "1ºA" de ano_escolar "1ª Fase" (é o
    # nome que ``nome_turma_exibicao`` dá a "Fase 1A"/"Pré 1 A"): série e letra
    # batem, a etapa não — antes a ficha nascia na Educação Infantil, sem revisão.
    # A comparação é entre a turma do RELATÓRIO e a de destino: com a turma
    # escolhida, ``turma_nome`` é o nome dela — comparar com ele era comparar a
    # turma com ela mesma.
    motivo_turma = ("turma_fora_do_ano_letivo" if turma.ano_letivo != ano
                    else "turma_arquivada" if not ida.turma_ativa(turma)
                    else "turma_de_outra_etapa" if ida.turma_de_outra_etapa(
                        ident.turma_relatorio, turma)
                    else "")
    if motivo_turma:
        _enfileirar_revisao(db, escola_id, ctx, ident,
                            replace(decisao, acao=ida.REVISAR, motivo=motivo_turma,
                                    turma_id=None),
                            dados, avisos, revisoes, usuario_id)
        return None

    # POLÍTICA DE MATRÍCULA (``services/politica_sync``): numa escola cuja fonte
    # de matrícula é a Lista Piloto, a plataforma NÃO cria criança. Aqui, e não
    # antes, porque "sem turma" e "turma fora do cadastro" já têm o caminho e o
    # motivo deles — a trava só pega a linha que REALMENTE criaria uma ficha, e
    # a pendência nasce com a turma já resolvida.
    if not permitir_criar_aluno:
        if decisao.vetados:
            # O motor ACHOU alguém de nome igual e o vetou porque RA/nascimento/
            # id externo provaram ser outra criança. A pendência fica sem
            # candidato de propósito (associar seria juntar crianças diferentes),
            # mas quem for decidir precisa saber que esse homônimo existe — senão
            # a tela diz "nenhum aluno corresponde" e convida a criar uma ficha
            # que talvez seja a terceira da mesma criança.
            quem = ", ".join(
                c["nome"] for c in ida.descrever_candidatos(ctx, decisao.vetados))
            avisos.append(
                f"“{linha.nome}”: a política desta escola não deixa a "
                f"plataforma criar ficha. Atenção: {quem} tem nome "
                "compatível mas foi DESCARTADO porque o RA, o nascimento ou a "
                "conta da plataforma provam ser outra criança — confira na Lista "
                "Piloto antes de decidir.")
        _enfileirar_revisao(db, escola_id, ctx, ident,
                            replace(decisao, acao=ida.REVISAR,
                                    motivo="criacao_bloqueada_por_politica"),
                            dados, avisos, revisoes, usuario_id)
        return None

    # A ficha nasce com o nome SEM o sufixo de turma digitado junto ("… LIMA 3A"),
    # pela mesma regra que já o tirava do casamento; a pendência e o log guardam o
    # nome recebido.
    aluno = Aluno(escola_id=escola_id, nome=ida.nome_sem_sufixo_de_turma(
        linha.nome, decisao.chave_sala, ida.chave_sala(ident.turma_nome)))
    db.add(aluno)
    db.flush()
    db.add(Matricula(escola_id=escola_id, aluno_id=aluno.id,
                     turma_id=turma.id, ano_letivo=ano))
    ctx.registrar_aluno(aluno)
    ctx.registrar_matricula(aluno.id, turma.id)
    registrar(db, "aluno.criado_auto", escola_id=escola_id, usuario_id=usuario_id,
              entidade="aluno", entidade_id=aluno.id,
              detalhes={"origem": linha.nome, "turma": turma.nome,
                        "plataforma": ident.plataforma or None,
                        "decisao": "NEW_STUDENT",
                        "motivo": ("identidade prova ser outra criança"
                                   if decisao.vetados
                                   else "nenhum candidato plausivel")})
    _vincular_identidade(db, escola_id, aluno.id, ident.plataforma, ident.id_externo,
                         ctx=ctx, usuario_id=usuario_id)
    _marcar_via(linha, "criado")
    if criados is not None:
        criados[(svc.chave_nome(linha.nome), turma.id)] = aluno
    return aluno


def _identidade_da_linha(db: Session, escola_id: int, linha, plataforma: str | None
                         ) -> tuple["ida.LinhaIdentidade", str, bool]:
    """A ``LinhaIdentidade`` de uma linha de confirmação — o MESMO cálculo para a
    decisão (``_resolver_aluno``) e para o pré-passe das contas em disputa
    (``ida.marcar_fichas_disputadas``). Devolve (identidade, turma_nome,
    turma_invalida): turma escolhida que não é desta escola invalida a linha."""
    dados = getattr(linha, "dados", None) or {}
    turma_explicita = None
    if linha.aluno_id is None and getattr(linha, "criar_em_turma_id", None) is not None:
        turma_explicita = db.get(Turma, linha.criar_em_turma_id)
        if turma_explicita is None or turma_explicita.escola_id != escola_id:
            return ida.linha_de_dados(linha.nome, dados, plataforma=plataforma), "", True
    turma_nome = (turma_explicita.nome if turma_explicita is not None
                  else getattr(linha, "criar_em_turma_nome", None)
                  or dados.get("turma_relatorio") or "")
    # A turma do RELATÓRIO, separada do destino (a escolhida, ou a que o nome
    # pede): é contra ela que se confere a etapa do destino.
    turma_relatorio = str(dados.get("turma_relatorio")
                          or getattr(linha, "criar_em_turma_nome", None) or "")
    ident = ida.linha_de_dados(
        linha.nome, dados, plataforma=plataforma, turma_nome=str(turma_nome),
        turma_id=turma_explicita.id if turma_explicita is not None else None,
        aluno_id=linha.aluno_id, turma_relatorio=turma_relatorio)
    if getattr(linha, "numero_chamada", None) is not None:
        ident = replace(ident, chamada=linha.numero_chamada)
    return ident, str(turma_nome), False


def _marcar_via(linha, via: str) -> None:
    """Registra na linha COMO o aluno foi identificado (a sincronização só move de
    turma quem veio pela identidade externa já vinculada)."""
    try:
        linha.via = via
    except (AttributeError, ValueError, TypeError):
        pass


# O motivo VERDADEIRO do desempate "oficial × duplicata" (``identidade_aluno.
# _oficial_entre_duplicatas``), para a auditoria e para a revisão encerrada.
_MOTIVO_DESEMPATE = ("única ficha da Lista Piloto compatível na sala; as outras são "
                     "duplicatas dela (mesmo nome ou abreviado), fora da Lista Piloto")

# A regra de cada via de ASSOCIAR, em uma frase: é o "por quê" gravado na revisão
# que o sistema encerra sozinho — quem abrir a fila depois entende a decisão sem
# precisar ler o código.
_REGRA_DA_VIA = {
    "identidade": "vínculo pela conta da plataforma",
    "uuid": "vínculo pela conta da plataforma",
    "ra": "RA da escola, com nome compatível",
    "exato": "nome idêntico, candidato único",
    "identificador": "nº de chamada, RA ou nascimento confirmando o candidato da sala",
    "abreviacao": "nome abreviado, candidato único na sala",
    "parcial": "nome do meio omitido, candidato único na sala",
    "variante": "grafia segura num nome do meio, candidato único na sala",
    "typo": "grafia segura num nome do meio, candidato único na sala",
    "lista_piloto_unica": ("única ficha da Lista Piloto compatível; as demais são "
                           "duplicatas dela (mesmo nome ou abreviado), fora da Lista Piloto"),
    "revisao": "mesma escolha de uma revisão já resolvida desta identidade",
}

# Quando quem confirmou FIXOU a ficha da linha (prévia aceita ou alternativa
# escolhida na tela): a revisão é encerrada por essa pessoa, não pelo sistema.
_REGRA_ESCOLHA_HUMANA = ("ficha fixada por quem confirmou a importação "
                         "(prévia aceita ou alternativa escolhida)")

# A13: a pendência aberta só pelo NOME (linha sem a conta) que a linha COM a conta
# responde. É sempre o sistema que a encerra — ninguém viu essa pendência —, e só
# quando o nome, sozinho, não aponta para nenhuma outra ficha.
_REGRA_PENDENCIA_POR_NOME = ("a mesma criança voltou com a conta da plataforma: mesmo "
                             "nome, mesma sala, e o nome sozinho não aponta outra ficha")

# Vias que NÃO casam pelo nome — a conta da plataforma, a escolha explícita e a
# memória de uma decisão humana. Só nas outras o sufixo de turma retirado do nome
# ("… RIBEIRO 2B") fez parte do casamento e cabe na regra.
_VIAS_SEM_NOME = frozenset({"identidade", "uuid", "explicito", "revisao"})

# Motivos cuja PERGUNTA é o próprio vínculo da conta: quem confirmou disse que a
# linha da conta U é de BRUNA, mas U está na ficha de BEATRIZ. A sincronização que
# casa por essa MESMA conta só repete o estado contestado — não responde nada.
# Só o /resolver, que pode transferir a conta, encerra essa pendência.
_SO_O_GESTOR_ENCERRA = frozenset({"identidade_de_outro_aluno"})

# D10/D11: pendência de conta EFETIVA em outra escola do Constela — de QUALQUER
# motivo — a gestão da escola não encerra pela importação manual com a ficha
# fixada; só o Admin Global. Não entra em ``_SO_O_GESTOR_ENCERRA`` (estático,
# por motivo) porque depende do estado de AGORA da conta, e a sincronização ainda
# encerra sozinha quando a conta deixa de ser de outra escola, ou pela memória da
# decisão do Admin Global — ver ``_retida_pelo_d10``.


def _preteridos(ctx: "ida.Contexto", ids) -> list[dict]:
    """As fichas deixadas de lado no desempate: id e nome (o nome é o que deixa a
    auditoria legível; a anonimização LGPD do log o alcança dentro da lista)."""
    return [{"aluno_id": c["aluno_id"], "nome": c["nome"]}
            for c in ida.descrever_candidatos(ctx, ids)]


def _instante(texto) -> datetime | None:
    try:
        return datetime.fromisoformat(str(texto)) if texto else None
    except ValueError:
        return None


# Os campos do retrato que as Questões do período medem (os mesmos de
# ``sync.orchestrator.CAMPOS_QUESTOES``, que importa este módulo).
_CAMPOS_QUESTOES = ("questoes_tentativas", "questoes_acertos")


def _guarda_questoes(rev: RevisaoIdentidade) -> bool:
    """A pendência guarda um retrato com as questões (alguma linha traz o campo)?"""
    return any(isinstance(linha, dict) and any(linha.get(c) is not None
                                               for c in _CAMPOS_QUESTOES)
               for linha in rev.linhas or [])


def _linha_substitui_o_congelado(rev: RevisaoIdentidade, chaves_da_linha: set[str],
                                 coletor: "ida.ColetorRevisoes", *,
                                 sem_questoes: bool = False) -> bool:
    """Esta linha traz o MESMO dado que a pendência guardava, tão novo quanto ou
    mais? Só então encerrar sem aplicar o congelado não perde nada — é o mesmo
    juízo que o /resolver faz com ``_retrato_superado``, antecipado.

      * MESMO TIPO DE DADO: a ``chave`` da pendência (identidade + formato +
        período) é a que esta linha atualizaria se fosse para a revisão. A irmã de
        OUTRO tipo (leituras numa importação de resumo, outro período do Matific)
        guarda dado que esta importação não traz: continua pendente até chegar
        uma linha do tipo dela, ou até o gestor resolvê-la (o /resolver aplica).
        Caso real (backup de 05/10): o cursor incremental do Elefante já tinha o
        total de livros de crianças em revisão, então a sincronização diária traz
        só o resumo delas — encerrar a irmã de leituras ali deixaria de fora
        livros que só a pendência guardava;
      * conta contestada (``_SO_O_GESTOR_ENCERRA``): nunca por aqui;
      * LEITURAS: só a sincronização encerra — o conector busca a lista de livros
        da criança no período LIFETIME (``elefante._corpo_relatorio``), que contém
        tudo o que a pendência acumulou. Um arquivo manual pode trazer só parte
        dos livros: a pendência fica para o gestor;
      * RETRATO (resumo, placar): a pendência guarda o retrato da importação que a
        abriu. Se ele é de um dia POSTERIOR ao desta importação (relatório antigo
        importado à mão), ele é o mais novo — fica para o /resolver aplicá-lo. O
        DIA é o de Brasília, o critério de ``_mesmo_dia`` (o mesmo com que o
        /resolver descarta o retrato do mesmo dia em ``_retrato_superado``): antes
        comparava a data UTC, e das 21h à meia-noite (BRT) a linha das 22h "era
        do dia seguinte" — encerrava a pendência de um retrato da 00h30 do dia
        seguinte (BRT), mais novo, e deixava pendente a de um retrato das 22h do
        mesmo dia, que o /resolver nunca reaplicaria. Data LEGADA fora do
        calendário (``0001-01-01T00:00:00+00:00``, que estoura na conversão para
        Brasília): a pendência fica para o gestor — antes o ``OverflowError``
        derrubava a sincronização da escola inteira;
      * QUESTÕES QUE NÃO VIERAM (S9, ``sem_questoes``: a importação desta linha é
        ``IMPORTACAO_SEM_QUESTOES``): a linha não traz as questões, então não
        substitui o retrato guardado que as traz — a medida dele é a última das
        questões. Encerrada aqui, ela sumia: com ``sem_retrato_repetido`` nada novo
        era gravado (ou o retrato novo só repetia as questões de antes) e o
        Relatório por Período perdia o ponto. Fica para o /resolver, ou para a
        próxima coleta que trouxer as questões."""
    if rev.chave not in chaves_da_linha or rev.motivo in _SO_O_GESTOR_ENCERRA:
        return False
    if rev.formato == "leituras":
        return coletor.origem == "sincronizacao"
    if sem_questoes and _guarda_questoes(rev):
        return False
    congelada = _instante((rev.contexto or {}).get("data_referencia"))
    if congelada is None:
        return True          # sem data: o /resolver nunca reaplicaria esse retrato
    if coletor.origem != "sincronizacao" and not (coletor.contexto or {}).get("data_informada"):
        # Arquivo enviado à mão sem a data do relatório: a "data desta importação"
        # é só o relógio de agora, e o relatório pode ser antigo. Fica para o
        # /resolver, que compara com o retrato mais recente de verdade.
        return False
    atual = _instante((coletor.contexto or {}).get("data_referencia"))
    dia_atual = _dia_em_brasilia(atual) if atual is not None else None
    dia_congelado = _dia_em_brasilia(congelada)
    return dia_atual is not None and dia_congelado is not None and dia_atual >= dia_congelado


def _motor_escolheria(ctx: "ida.Contexto", ident: "ida.LinhaIdentidade",
                      aluno: Aluno) -> "ida.Decisao | None":
    """A ficha FIXADA por quem confirmou é a mesma que o motor escolheria sozinho?
    Então foi a sugestão da prévia aceita como veio — não uma escolha de gente —
    e a pendência encerra como AUTOMÁTICA (não vira memória que desligaria, nas
    próximas importações, a guarda de homônimo novo e a de ficha inativa).
    Devolve a decisão do motor nesse caso (para gravar a regra DELE), senão None.

    A conta da plataforma acabou de ser gravada nesta mesma linha e sempre
    "concordaria"; por isso o motor decide pelo NOME — mas as travas da CONTA
    valem antes: conta aposentada ou OUTRA conta desta plataforma na ficha
    fixada são situações em que o motor nunca associaria sozinho (é gente
    passando por cima da trava), e a escolha é humana."""
    if ident.id_externo:
        if (ident.plataforma, ident.id_externo) in ctx.aposentadas:
            return None
        if ctx.ids_do_aluno.get((aluno.id, ident.plataforma), set()) - {ident.id_externo}:
            return None
    dec = ida.decidir(ctx, replace(ident, aluno_id=None, id_externo=""))
    return dec if dec.acao == ida.ASSOCIAR and dec.aluno_id == aluno.id else None


def _retida_pelo_d10(db: Session, escola_id: int, ctx: "ida.Contexto",
                     ident: "ida.LinhaIdentidade", rev: RevisaoIdentidade,
                     cache: dict[tuple[str, str], bool]) -> bool:
    """A pendência desta linha fica na fila porque a conta é de outra escola (D10/D11)?

    Caso (4ª revisão de integração do e97): a conta U já vale aqui na ficha da
    Ana, e o Admin Global a confirmou também na outra escola. A coleta seguinte
    daqui manda U para a revisão ``identidade_de_outra_escola``, e o /resolver
    dela é 403 para a gestão. Mas a importação manual com a ficha da Ana fixada
    cai no passo 0 de ``decidir`` (``dono == aluno`` → ASSOCIAR via
    ``identidade``, sem a trava do D10, que só vale quando a conta ainda não está
    ligada aqui), e esta função encerrava a pendência pela gestão. Com nome não
    idêntico, o encerramento era DECISÃO HUMANA, virava memória
    (``carregar_contexto``) e a coleta seguinte associava U sozinha: a
    confirmação do D10 feita sem o Admin Global, sem aviso e sem auditoria.

    QUALQUER motivo (marco 3 do e97): a pendência da mesma conta aberta por
    outro motivo ANTES de a conta virar efetiva na outra escola (ex.:
    ``identidade_de_ficha_inativa`` — a Ana transferida daqui) dava o mesmo
    atalho. Encerrada pela gestão com nome não idêntico, virava a mesma memória
    que o passo 0d (``_confirmado_por_humano``) da coleta seguinte respeita. O
    /resolver já barra a gestão em qualquer motivo (o D10 dele olha a conta, não
    o motivo); esta trava agora também.

    Retida: ficha FIXADA na linha (escolha de quem confirmou) por quem NÃO é o
    Admin Global (``ctx.confirma_conta_de_outra_escola``), com a conta ainda
    efetiva em outra escola (``ida.efetivas_em_outra_escola``, a regra única). O
    dado da linha continua aplicado (a conta que já vale aqui não é barrada); só
    a pendência não fecha. Seguem a regra geral: a sincronização (linha sem ficha
    fixada — só associa essa conta com a memória da decisão do Admin Global, ou
    depois que ela deixou de ser de outra escola) e o Admin Global."""
    if ident.aluno_id is None or ctx.confirma_conta_de_outra_escola:
        return False
    plataforma = rev.plataforma or ident.plataforma
    id_externo = rev.id_externo or ident.id_externo
    if not plataforma or not id_externo:
        return False
    chave = (plataforma, id_externo)
    if chave not in cache:
        cache[chave] = id_externo in ida.efetivas_em_outra_escola(
            db, escola_id, plataforma, [id_externo])
    return cache[chave]


def _encerrar_revisoes_respondidas(db: Session, escola_id: int, ctx: "ida.Contexto",
                                   ident: "ida.LinhaIdentidade", decisao: "ida.Decisao",
                                   aluno: Aluno, avisos: list[str], *,
                                   coletor: "ida.ColetorRevisoes | None",
                                   usuario_id: int | None) -> list[int]:
    """A linha acabou de ser ASSOCIADA: a revisão PENDENTE da MESMA identidade
    (mesma escola, mesma ``chave_identidade``) e do MESMO tipo de dado perguntava
    exatamente isto, e a pergunta foi respondida. Sem este passo ela ficava
    "pendente" para sempre, porque só o /resolver e o /descartar mudam o status —
    a fila acumulava casos já decididos.

    Encerra como RESOLVIDA: ``aluno_escolhido_id`` = o associado; ``resolucao``
    com a via, a regra (e os preteridos do desempate) e ``dados_superados`` (o
    congelado não é aplicado — ver abaixo).
      * decisão do SISTEMA (linha sem ficha fixada — a sincronização):
        ``resolvida_por_id`` None, ``automatica: true``, auditoria
        ``revisao.encerrada_automaticamente``;
      * ficha FIXADA por quem confirmou (prévia aceita, alternativa escolhida):
        é decisão dessa pessoa — ``resolvida_por_id`` = ela, ``automatica:
        false``, auditoria ``identidade.revisao_resolvida`` (a mesma do /resolver).
    A escolha entra em ``ctx.resolvidas`` para as próximas linhas DESTA
    importação. A encerrada pelo sistema não volta como memória nas próximas
    (``identidade_aluno.carregar_contexto``): lá a linha é decidida de novo pela
    regra — e a que tem conta da plataforma casa pelo vínculo gravado na ficha.

    Os DADOS CONGELADOS na revisão NÃO são aplicados: só se encerra a pendência
    cujo dado ESTA linha substitui (``_linha_substitui_o_congelado`` — mesmo tipo
    de dado, retrato não mais antigo, leituras só pela sincronização; na coleta
    sem as questões (S9), só o retrato guardado que também não as tem). Retrato:
    vale o desta linha, e o /resolver descartaria o congelado
    (``_retrato_superado``). Leituras: a lista LIFETIME da sincronização contém
    os livros guardados (e a UNIQUE de Leitura impede duplicar). Pendência que esta
    linha NÃO substitui continua na fila, intacta. A pendência (de qualquer
    motivo) com a ficha fixada pela gestão da escola, de conta ainda efetiva em
    outra escola, também fica (``_retida_pelo_d10``): só o Admin Global a
    encerra.

    Pendências vêm de ``ctx.pendentes`` (lidas UMA vez por importação) e saem de
    lá na primeira linha ASSOCIADA da identidade: nenhuma consulta por linha. A
    PRÉVIA nunca passa por aqui (``importacao.casar_nomes`` só chama ``decidir``),
    e sem o coletor da importação (que diz o tipo de dado) nada é encerrado.
    Devolve os ids encerrados."""
    if coletor is None:
        return []
    # A chave sob a sala RECONHECIDA e, quando difere, a da sala do RELATÓRIO
    # (pendências gravadas antes de ``sala_efetiva`` existir) — o mesmo par que
    # ``Contexto.decisao_humana`` consulta. Linha com identidade externa tem uma
    # chave só (não depende da sala). [:400]: o tamanho gravado na revisão.
    chaves = list(dict.fromkeys(
        c[:400] for c in (ida.chave_identidade(ident, decisao.chave_sala),
                          ida.chave_identidade(ident, ida.chave_sala(ident.turma_nome)))))
    # A13: a linha que agora traz a CONTA da plataforma responde também a pendência
    # aberta por NOME (mesmo nome, mesma sala) quando ela chegou SEM a conta — antes
    # a chave mudava de nome+sala para id e a pendência ficava aberta para sempre.
    # Mesmas guardas de sempre (``_linha_substitui_o_congelado``, D10) e mais duas:
    # a pendência por nome só fecha se não apontava para OUTRA ficha e se o nome
    # sozinho, decidido hoje, também não aponta. E fecha sempre como AUTOMÁTICA, sem
    # virar memória nome+sala (nem nesta importação, nem nas próximas).
    chaves_por_nome: list[str] = []
    if ident.id_externo:
        sem_conta = replace(ident, id_externo="")
        chaves_por_nome = [c for c in dict.fromkeys(
            c[:400] for c in (ida.chave_identidade(sem_conta, decisao.chave_sala),
                              ida.chave_identidade(sem_conta, ida.chave_sala(ident.turma_nome))))
            if c not in chaves]
    ids = [rid for c in chaves for rid in ctx.pendentes.pop(c, [])]
    ids_por_nome = {rid for c in chaves_por_nome for rid in ctx.pendentes.pop(c, [])}
    ids += sorted(ids_por_nome)
    if not ids:
        return []
    # S9: a importação desta linha veio sem as questões? (a marca é dela, gravada
    # antes das linhas; ``db.get`` acha a importação já na sessão, sem consulta).
    importacao = db.get(Importacao, coletor.importacao_id) if coletor.importacao_id else None
    sem_questoes = importacao is not None and importacao.status == IMPORTACAO_SEM_QUESTOES
    contexto = coletor.contexto or {}
    chaves_da_linha = {ida.chave_pendencia(c, coletor.formato,
                                           str(contexto.get("periodo_inicio") or ""),
                                           str(contexto.get("periodo_fim") or ""))
                       for c in (*chaves, *chaves_por_nome)}
    motor = _motor_escolheria(ctx, ident, aluno) if ident.aluno_id is not None else None
    humana = ident.aluno_id is not None and motor is None
    if motor is not None:
        decisao = motor        # a regra gravada é a do motor, não "explicito"
    if humana:
        regra = _REGRA_ESCOLHA_HUMANA
    else:
        regra = _REGRA_DA_VIA.get(decisao.via, f"decisão automática ({decisao.via})")
        if (decisao.via not in _VIAS_SEM_NOME
                and ida._nome_para_casar(ident.nome, decisao.chave_sala,
                                         ida.chave_sala(ident.turma_nome)) != ident.nome):
            # "… RIBEIRO 2B" casou como nome idêntico: a regra diz que o sufixo saiu.
            regra += ", sem o sufixo de turma digitado junto do nome"
    # A13: o nome SOZINHO (a linha sem a conta, como a pendência por nome a recebeu)
    # aponta para outra ficha da escola? Então a pendência por nome pode ser de OUTRA
    # criança com o mesmo nome (abreviado) na sala: não fecha — fica para um humano,
    # com o retrato que ela guarda. Decidido uma vez, só se houver pendência por nome.
    nome_aponta_outra = False
    if ids_por_nome:
        pelo_nome = ida.decidir(ctx, replace(ident, id_externo="", aluno_id=None))
        nome_aponta_outra = bool(
            {i for i in (*pelo_nome.candidatos, pelo_nome.aluno_id) if i is not None}
            - {aluno.id})
    preteridos = _preteridos(ctx, decisao.preteridos)
    momento = agora()
    encerradas: list[int] = []
    encerradas_por_humano = 0
    regras_automaticas: list[str] = []
    ficaram: list[RevisaoIdentidade] = []
    retidas_d10: list[RevisaoIdentidade] = []
    contas_de_outra_escola: dict[tuple[str, str], bool] = {}
    for rid in ids:
        rev = db.get(RevisaoIdentidade, rid)
        if rev is None or rev.escola_id != escola_id or rev.status != "pendente":
            continue                     # já decidida por outro caminho: não mexe
        if _retida_pelo_d10(db, escola_id, ctx, ident, rev, contas_de_outra_escola):
            retidas_d10.append(rev)      # D10/D11: só o Admin Global encerra
            continue
        por_nome = rid in ids_por_nome
        if por_nome and (nome_aponta_outra or any(
                c.get("aluno_id") not in (None, aluno.id) for c in (rev.candidatos or [])
                if isinstance(c, dict))):
            ficaram.append(rev)          # a pendência por nome pode ser de outra ficha
            continue
        if not _linha_substitui_o_congelado(rev, chaves_da_linha, coletor,
                                            sem_questoes=sem_questoes):
            ficaram.append(rev)
            continue
        # A pendência por NOME nunca é encerrada como decisão de gente, nem quando a
        # ficha da linha foi fixada por quem confirmou: essa pessoa escolheu a ficha
        # da CONTA e nunca viu a pergunta "de quem é este nome nesta sala". Encerrada
        # como humana, viraria memória nome+sala (``carregar_contexto``) e toda linha
        # SEM conta com esse nome iria sozinha para a ficha — mesmo com um homônimo
        # abreviado na sala.
        humana_rev = humana and not por_nome
        regra_rev = _REGRA_PENDENCIA_POR_NOME if por_nome else regra
        dados_superados = {"motivo": "substituidos_pela_linha_desta_importacao",
                           "formato": rev.formato, "plataforma": rev.plataforma,
                           "data_congelada": (rev.contexto or {}).get("data_referencia") or None,
                           "data_desta_importacao": contexto.get("data_referencia") or None}
        resolucao = {"acao": "associar", "aluno_id": aluno.id, "automatica": not humana_rev,
                     "via": decisao.via, "regra": regra_rev,
                     "dados_superados": dados_superados}
        if humana_rev:
            resolucao["resolvida_na"] = "confirmacao_da_importacao"
        if por_nome:
            resolucao["pendencia_por_nome"] = True
        if preteridos:
            # Só o id: a revisão não passa pela redação LGPD da exclusão
            # permanente (os logs passam, e lá o nome fica).
            resolucao["preteridos"] = [{"aluno_id": p["aluno_id"]} for p in preteridos]
        if coletor.importacao_id is not None:
            resolucao["importacao_id"] = coletor.importacao_id
        rev.status = "resolvida"
        rev.aluno_escolhido_id = aluno.id
        rev.resolvida_por_id = usuario_id if humana_rev else None
        rev.resolvida_em = momento
        rev.resolucao = resolucao
        if not por_nome:
            # Memória desta importação só para a chave da PRÓPRIA linha; a chave
            # nome+sala da pendência por nome continua decidida pela regra.
            ctx.resolvidas[rev.chave_identidade] = aluno.id
        candidatos = [c.get("aluno_id") for c in (rev.candidatos or [])]
        if humana_rev:
            encerradas_por_humano += 1
            registrar(db, "identidade.revisao_resolvida", escola_id=escola_id,
                      usuario_id=usuario_id, entidade="aluno", entidade_id=aluno.id,
                      detalhes={"revisao_id": rev.id, "plataforma": rev.plataforma,
                                "formato": rev.formato, "motivo": rev.motivo,
                                "acao": "associar", "origem": rev.nome_recebido,
                                "dados_superados": dados_superados,
                                "candidatos": candidatos,
                                "resolvida_na": "confirmacao_da_importacao",
                                "via": decisao.via,
                                "importacao_id": coletor.importacao_id})
        else:
            registrar(db, "revisao.encerrada_automaticamente", escola_id=escola_id,
                      usuario_id=usuario_id, entidade="aluno", entidade_id=aluno.id,
                      detalhes={"revisao_id": rev.id, "plataforma": rev.plataforma,
                                "formato": rev.formato, "motivo": rev.motivo,
                                "origem": rev.nome_recebido, "aluno": aluno.nome,
                                "via": decisao.via, "regra": regra_rev,
                                "preteridos": preteridos,
                                "dados_superados": dados_superados,
                                "importacao_id": coletor.importacao_id,
                                "candidatos": candidatos})
            if regra_rev not in regras_automaticas:
                regras_automaticas.append(regra_rev)
        encerradas.append(rev.id)
    if encerradas:
        automaticas = len(encerradas) - encerradas_por_humano
        if not automaticas:
            como = "resolvidas pela sua confirmação"
        elif not encerradas_por_humano:
            como = f"encerradas automaticamente ({'; '.join(regras_automaticas)})"
        else:
            como = (f"resolvidas pela sua confirmação ({encerradas_por_humano}) ou "
                    f"encerradas automaticamente ({automaticas}: "
                    f"{'; '.join(regras_automaticas)})")
        aviso = (f"“{ident.nome}”: {len(encerradas)} pendência(s) de revisão desta "
                 f"identidade foram {como} — o dado desta importação foi para "
                 f"{aluno.nome} e substitui o que elas guardavam.")
        if ficaram:
            tipos = ", ".join(sorted({r.formato or "resumo" for r in ficaram}))
            aviso += (f" Continuam na fila {len(ficaram)} pendência(s) dela ({tipos}) "
                      "que esta linha não responde.")
        avisos.append(aviso)
    if retidas_d10:
        avisos.append(
            f"“{ident.nome}”: o dado desta importação foi para {aluno.nome}, mas "
            f"{len(retidas_d10)} pendência(s) de revisão desta conta continuam na "
            "fila: a conta está vinculada também a um aluno de OUTRA escola do "
            "Constela, e só o Admin Global encerra essa pendência, em Revisão de "
            "identidade.")
    return encerradas


def _enfileirar_revisao(db: Session, escola_id: int, ctx: "ida.Contexto",
                        ident: "ida.LinhaIdentidade", decisao: "ida.Decisao",
                        dados: dict, avisos: list[str],
                        revisoes: "ida.ColetorRevisoes | None",
                        usuario_id: int | None) -> None:
    """A linha NÃO é descartada: entra na fila de revisão com tudo o que é preciso
    para um gestor decidir depois (nome, identidade externa, turma, candidatos,
    motivo, dados). Várias linhas do mesmo aluno viram UMA pendência."""
    avulso = revisoes is None
    coletor = revisoes if revisoes is not None else ida.ColetorRevisoes()
    antes = len(coletor.pendencias)
    coletor.adicionar(ctx, ident, decisao, dados)
    if len(coletor.pendencias) > antes:
        texto = ida.MOTIVOS.get(decisao.motivo, decisao.motivo)
        cands = ida.descrever_candidatos(ctx, decisao.candidatos)
        if decisao.motivo == "deixada_para_revisao":
            # Pedido de quem confirmou: não é "correspondência insegura".
            avisos.append(f"“{ident.nome}”: {texto}.")
        elif cands:
            quem = ", ".join(
                c["nome"] + (f" (ficha “{c['status']}”)" if c["status"] != "ativo" else "")
                for c in cands)
            avisos.append(
                f"“{ident.nome}”: {texto} — {quem}. A correspondência não é segura: NÃO "
                "foi criada uma 2ª ficha nem os dados foram associados. A linha ficou "
                "como pendência na fila de revisão de identidade para um gestor "
                "escolher o aluno.")
        else:
            avisos.append(
                f"“{ident.nome}”: {texto} — nenhum aluno foi associado nem criado. A "
                "linha ficou como pendência na fila de revisão de identidade para um "
                "gestor decidir.")
    if avulso:
        _gravar_revisoes(db, escola_id, coletor, usuario_id)


_MOTIVOS_DE_TURMA = ida.MOTIVOS_DE_TURMA


def _gravar_revisoes(db: Session, escola_id: int, coletor: "ida.ColetorRevisoes",
                     usuario_id: int | None) -> list[RevisaoIdentidade]:
    """Grava/atualiza a fila e audita cada pendência (vira notificação da escola)."""
    gravadas = coletor.gravar(db, escola_id)
    for rev in gravadas:
        cands = [c.get("aluno_id") for c in (rev.candidatos or []) if c.get("aluno_id")]
        # Problema de TURMA (sem turma, fora do cadastro, ambígua) é "linha sem aluno
        # vinculado"; o resto é identidade ambígua. As duas contam como pendência.
        acao = ("importacao.linha_ignorada" if rev.motivo in _MOTIVOS_DE_TURMA
                else "aluno.revisao_necessaria")
        registrar(db, acao, escola_id=escola_id,
                  usuario_id=usuario_id, entidade="aluno",
                  entidade_id=cands[0] if cands else None,
                  detalhes={"origem": rev.nome_recebido, "turma": rev.turma_informada,
                            "plataforma": rev.plataforma, "decisao": "REVIEW_REQUIRED",
                            "motivo": rev.motivo, "candidatos": cands,
                            "revisao_id": rev.id, "ocorrencias": rev.ocorrencias})
    return gravadas


def _vincular_identidade(db: Session, escola_id: int, aluno_id: int,
                         plataforma: str, id_externo: str, *,
                         ctx: "ida.Contexto | None" = None,
                         usuario_id: int | None = None) -> bool:
    """Grava o vínculo aluno ↔ id externo (UUID do Matific / studentId do
    Elefante). Idempotente e seguro sob concorrência (savepoint na unique).

    NUNCA tira a identidade de outra ficha existente (ativa ou inativa) — isso só
    acontece por decisão explícita de um gestor na fila de revisão. A única
    reatribuição automática é a de uma ficha EXCLUÍDA (que não é reutilizada e,
    portanto, não pode segurar a identidade) — e fica auditada."""
    if not (plataforma and id_externo):
        return False
    ja = db.execute(select(IdentidadeExterna).where(
        IdentidadeExterna.escola_id == escola_id,
        IdentidadeExterna.plataforma == plataforma,
        IdentidadeExterna.id_externo == id_externo)).scalars().first()
    if ja is not None:
        # Aposentada NUNCA é reativada de passagem: quem decidiu aposentar tem
        # de decidir reativar, pelo caminho explícito e auditado.
        if ja.status == "aposentada":
            return False
        if ja.aluno_id == aluno_id:
            return True
        dono = db.get(Aluno, ja.aluno_id)
        if dono is not None and dono.status != "excluido":
            return False
        antigo = ja.aluno_id
        ja.aluno_id = aluno_id
        db.flush()
        registrar(db, "identidade.reatribuida", escola_id=escola_id,
                  usuario_id=usuario_id, entidade="aluno", entidade_id=aluno_id,
                  detalhes={"plataforma": plataforma, "id_externo": id_externo,
                            "de_aluno_id": antigo, "para_aluno_id": aluno_id,
                            "motivo": "ficha_anterior_excluida"})
        if ctx is not None:
            ctx.vincular(aluno_id, plataforma, id_externo)
        return True
    try:
        with db.begin_nested():
            db.add(IdentidadeExterna(escola_id=escola_id, aluno_id=aluno_id,
                                     plataforma=plataforma, id_externo=id_externo))
            db.flush()
    except IntegrityError:
        return False  # corrida: outro processo vinculou primeiro — não rouba
    if ctx is not None:
        ctx.vincular(aluno_id, plataforma, id_externo)
    return True


def _turma_existente_por_tokens(db: Session, escola_id: int, ano: int,
                                klass_nome: str) -> Turma | None:
    """Turma JÁ CADASTRADA da escola/ano que casa com o nome do Matific por
    sobreposição de tokens (série+letra) — a MESMA noção de identidade de turma
    do resto do sistema (``overlap_turma``). Ex.: "5 ANO B MANHA ANUAL" casa com
    "5º Ano B". NUNCA cria turma. Devolve None se nenhuma casar de forma
    INEQUÍVOCA (nenhuma ≥2, ou empate no melhor overlap) — porque mover criança
    de sala sem supervisão exige certeza.

    Só serve de destino turma ATIVA e da MESMA ETAPA do rótulo do Matific
    (``matriculas.etapa_da_sala``): "1 ANO A …" e "1ª Fase A" partilham série e
    letra, mas mover para a Fase (ou para uma turma arquivada) é matricular a
    criança onde ela não está."""
    alvo = svc.tokens_turma(klass_nome)
    if not alvo:
        return None
    etapa = matriculas.etapa_da_sala(klass_nome)
    candidatas: list[tuple[int, Turma]] = []
    for turma in db.execute(
        select(Turma).where(Turma.escola_id == escola_id,
                            Turma.ano_letivo == ano)).scalars():
        if (not ida.turma_ativa(turma)
                or matriculas.etapa_da_sala(turma.nome, turma.ano_escolar or "") != etapa):
            continue
        ov = matriculas.overlap_turma(alvo, svc.tokens_turma(turma.nome))
        if ov >= 2:                       # série + letra em comum
            candidatas.append((ov, turma))
    if not candidatas:
        return None
    candidatas.sort(key=lambda par: par[0], reverse=True)
    if len(candidatas) > 1 and candidatas[0][0] == candidatas[1][0]:
        return None                       # empate → ambíguo → não arrisca
    return candidatas[0][1]


def _sincronizar_turma_matific(db: Session, escola_id: int, ano: int,
                               resolvidos: dict, avisos: list[str], *,
                               ctx: "ida.Contexto | None" = None,
                               movidos_ids: list[int] | None = None) -> int:
    """Na sync AUTOMÁTICA do Matific: vincula o UUID (identificação confiável) e
    MOVE a matrícula quando a turma reportada mudou. Regras de segurança (mexe em
    dado de criança, sem humano no loop):

    * só age em quem foi identificado pela IDENTIDADE EXTERNA já vinculada (via
      'identidade') — nunca por nome. O UUID é gravado pela confirmação no 1º
      encontro; só a PARTIR daí a turma pode mudar;
    * identidade de turma é por TOKENS (série+letra), não por string crua — o
      ``klassName`` do Matific ("5 ANO B MANHA ANUAL") NÃO cria uma turma-fantasma
      quando já existe a "5º Ano B";
    * só move entre turmas JÁ CADASTRADAS e de forma INEQUÍVOCA. Se o Matific
      apontar uma turma que não casa com nenhuma cadastrada, NÃO move nem cria —
      só registra um aviso para revisão humana;
    * a sala reconhecida pela série (``Contexto.sala_efetiva`` — "4 ANO A
      INTEGRAL" × "4º Ano", única turma ativa da série e da etapa) é a MESMA
      turma: não move nem avisa (antes saía um aviso falso a cada coleta);
    * destino só turma ATIVA e da mesma ETAPA (``_turma_existente_por_tokens``);
    * com a política ``bloquear`` (``politica_sync.pode_mover_matricula``) a
      matrícula segue a Lista Piloto, pela mesma regra que impede a sync de criar
      ficha (a plataforma não matricula; P15 é a recomendação de 26/10, aplicada por
      decorrer dessa regra — o dono pode objetar): vincula o UUID, mas NÃO move — a
      turma divergente vira aviso. Antes a coleta movia e o reenvio da Lista
      Piloto devolvia: a matrícula ia e voltava. A trava fica AQUI, e não só no
      chamador, para nenhum caminho que chame esta rotina furar a política.

    Devolve quantos alunos foram movidos; ``movidos_ids`` (quando passado) recebe
    os ids — a matrícula movida é dado alterado (ranking por turma, posição), e o
    /confirmar os conta como aplicados para a sync recalcular as notas."""
    movidos = 0
    mover: bool | None = None   # a política só é lida quando há o que mover
    if ctx is None and resolvidos:
        ctx = ida.carregar_contexto(db, escola_id, ano)
    for aluno, linhas in resolvidos.values():
        linha = linhas[-1]
        uuid = str((linha.dados or {}).get("matific_uuid") or "").strip()
        if not uuid:
            continue
        via = getattr(linha, "via", None)
        if not via:
            continue  # não passou pela porta única de identidade: não toca em nada
        _vincular_identidade(db, escola_id, aluno.id, "matific", uuid)  # idempotente
        if via != "identidade":
            continue  # 1ª vez (casou por nome): só vincula; move pela identidade
        if (linha.dados or {}).get("turma_ambigua"):
            continue  # a conta veio em mais de uma turma do Placar: turma incerta
        turma_nome = str((linha.dados or {}).get("turma_relatorio") or "").strip()
        if not turma_nome:
            continue
        matricula = db.execute(select(Matricula).where(
            Matricula.aluno_id == aluno.id,
            Matricula.ano_letivo == ano)).scalars().first()
        if matricula is None:
            continue
        atual = db.get(Turma, matricula.turma_id)
        # Mesma turma (tokens série+letra, ou a sala reconhecida pela série) →
        # nada a fazer (evita turma-fantasma e aviso falso).
        if atual is not None and (
                matriculas.overlap_turma(
                    svc.tokens_turma(atual.nome), svc.tokens_turma(turma_nome)) >= 2
                or ctx.sala_efetiva(ida.chave_sala(turma_nome), turma_nome)
                == ida.chave_sala(atual.nome)):
            continue
        nova = _turma_existente_por_tokens(db, escola_id, ano, turma_nome)
        if nova is None:
            avisos.append(
                f"{aluno.nome}: o Matific indica a turma “{turma_nome}”, que não "
                "casa com nenhuma turma cadastrada — revise manualmente (não movi "
                "automaticamente).")
            continue
        if nova.id == matricula.turma_id:
            continue
        if mover is None:
            mover = politica_sync.pode_mover_matricula(db, escola_id)
        if not mover:
            # Política 'bloquear': a matrícula vem da Lista Piloto (a planilha é a
            # fonte da verdade). A plataforma não move: só avisa.
            avisos.append(
                f"{aluno.nome}: o Matific indica a turma “{nova.nome}”; a matrícula "
                "segue a Lista Piloto (política 'bloquear') — não movi.")
            continue
        antiga = atual.nome if atual is not None else "—"
        matricula.turma_id = nova.id
        db.flush()
        registrar(db, "matricula.turma_sincronizada", escola_id=escola_id,
                  entidade="aluno", entidade_id=aluno.id,
                  detalhes={"de": antiga, "para": nova.nome, "origem": "matific"})
        avisos.append(f"{aluno.nome}: movido de “{antiga}” para “{nova.nome}” "
                      "(mudança de turma detectada no Matific).")
        movidos += 1
        if movidos_ids is not None:
            movidos_ids.append(aluno.id)
    return movidos


def _importar_matific(db, escola_id, importacao, aluno, dados, data_referencia,
                      anterior=_SEM_PRECARGA):
    # Cada relatório do Matific traz um subconjunto das métricas: o PDF de
    # estrelas tem "estrelas"; o Excel por turma NÃO tem. Preservamos o valor
    # anterior de cada campo AUSENTE — assim os dois relatórios se COMPLEMENTAM
    # (nunca zeram um campo que outro relatório já preencheu).
    # `anterior` pode vir pré-carregado em lote pelo /confirmar (evita o N+1) — e,
    # num relatório RETRODATADO, é o retrato que valia NA DATA dele
    # (``_mapa_retrato_na_data``), nunca o mais novo.
    if anterior is _SEM_PRECARGA:
        anterior = _snapshot_atual(db, escola_id, aluno.id, SnapshotMatific)
    atividades = (_num(dados["atividades"], int) if "atividades" in dados
                  else (anterior.atividades if anterior else 0))
    estrelas = (_num(dados["estrelas"], int) if "estrelas" in dados
                else (anterior.estrelas if anterior else 0))
    media = (_num(dados["pontuacao_media"], float) if "pontuacao_media" in dados
             else (anterior.pontuacao_media if anterior else 0.0))
    # Reimportar/complementar no MESMO dia atualiza o snapshot do dia
    # (idempotente) em vez de empilhar um segundo ponto. Semântica COMPLEMENTAR
    # preservada: os valores acima já resolveram "campo presente vence; ausente
    # herda o anterior" — o relatório mais recente é a fonte autoritativa (o
    # Excel por turma pode legitimamente corrigir as atividades para MENOS sem
    # que as estrelas do PDF anterior se percam).
    # Devolve se o dado do aluno MUDOU (novo retrato com valor diferente do atual,
    # ou primeiro retrato) — é a conta de "alunos aplicados" da sincronização. Um
    # retrato novo com os mesmos números continua sendo gravado (série diária),
    # mas não conta como atualização.
    mudou = anterior is None or (anterior.atividades, anterior.estrelas,
                                 anterior.pontuacao_media) != (atividades, estrelas, media)
    if anterior is not None and _mesmo_dia(anterior.data_referencia, data_referencia):
        anterior.atividades = atividades
        anterior.estrelas = estrelas
        anterior.pontuacao_media = media
        anterior.importacao_id = importacao.id
        _avancar_data(anterior, data_referencia)
        return mudou
    db.add(SnapshotMatific(
        escola_id=escola_id, aluno_id=aluno.id, importacao_id=importacao.id,
        data_referencia=data_referencia,
        atividades=atividades, estrelas=estrelas, pontuacao_media=media,
    ))
    return mudou


def _sem_fuso(momento):
    return momento.replace(tzinfo=None) if momento.tzinfo else momento


def _instante_utc(momento):
    """O MESMO instante em UTC naive, para comparar "antes/depois": naive é UTC (a
    convenção do ``data_referencia`` gravado, ver ``app.sync.fuso``); com fuso, é
    CONVERTIDO. ``_sem_fuso`` só tira o fuso: "14h -03:00" (17h UTC) virava "14h"
    e perdia para "16h" UTC — erro de até 3 h na ordem de dois instantes."""
    if momento.tzinfo is None:
        return momento
    return momento.astimezone(timezone.utc).replace(tzinfo=None)


def _instante_utc_no_calendario(momento) -> datetime | None:
    """``_instante_utc`` para data que vem do banco ou de dado LEGADO: None se ela
    não existe no calendário em UTC ou no dia de Brasília (0001-01-01 com fuso
    positivo, ou antes das 03h UTC; 9999-12-31 com fuso negativo) — em vez do
    OverflowError que virava 500."""
    try:
        utc = _instante_utc(momento)
    except (OverflowError, ValueError):
        return None
    return utc if _dia_em_brasilia(utc) is not None else None


def _avancar_data(snapshot, data_referencia) -> None:
    """Na reescrita NO LUGAR do retrato do dia, a data acompanha o valor novo
    (nunca recua). Antes o valor das 13h de 23/10 ficava com a data das 21h30 de
    22/10 (Brasília) — o cartaz e o certificado imprimiam o dia anterior, e um
    período que termina em 22/10 passava a incluir atividade de 23/10. A ordem é
    a dos INSTANTES (``_instante_utc``), não a da hora de parede."""
    if data_referencia is None or snapshot.data_referencia is None:
        return
    if _instante_utc(data_referencia) > _instante_utc(snapshot.data_referencia):
        snapshot.data_referencia = data_referencia


def _mesmo_dia(a, b) -> bool:
    """True se dois instantes caem no MESMO dia de BRASÍLIA (o dia da escola).
    Usado para tornar reimportações do mesmo dia idempotentes: em vez de empilhar
    um segundo ponto no histórico diário, o snapshot do dia é atualizado no lugar.

    Naive = UTC (a convenção do ``data_referencia`` gravado, ver
    ``app.sync.fuso``); com fuso, convertido. Antes comparava a data UTC crua: das
    21h à meia-noite (BRT) o UTC já é o dia seguinte — a coleta das 22h e a da
    manhã seguinte colapsavam num retrato só (o da noite sumia do histórico),
    enquanto a das 20h e a das 22h do MESMO dia viravam dois.

    Data legada fora do calendário (retrato de 0001-01-01, que estoura na conversão
    para Brasília) não é "o mesmo dia" de nada: antes o ``OverflowError`` derrubava
    a sincronização da escola inteira e o upload manual dava 500."""
    if a is None or b is None:
        return False
    dia_a = _dia_em_brasilia(a)
    return dia_a is not None and dia_a == _dia_em_brasilia(b)


def _importar_matific_periodo(db, escola_id, importacao, aluno, dados,
                              inicio, fim, serie, contadores, *, em_andamento: bool = False):
    """Relatório Matific POR PERÍODO ("Intervalo de datas" no leaderboard).

    Os números do relatório são o que o aluno fez DENTRO do intervalo — nada
    de substituir o acumulado. Regras:
      * base = último snapshot ANTERIOR ao início do intervalo;
      * candidato = base + valores do relatório (média PONDERADA por
        atividades);
      * PISO anti-regressão: o novo snapshot nunca fica abaixo do maior
        acumulado já registrado ATÉ o fim do intervalo — um relatório
        acumulado antigo datado dentro do período (a migração do fluxo
        antigo para o mensal) jamais derruba o estado atual;
      * sem base: nasce um snapshot-base na véspera do início valendo
        exatamente (novo − ganhos) — premiações e evolução do período
        enxergam o ganho do relatório, nunca zero nem o acumulado de
        outra época;
      * o snapshot é datado no fim do intervalo, LIMITADO a agora — um
        período em andamento não gera data futura que esconderia edições
        manuais feitas depois.
    Reimportar o mesmo período recalcula sobre a mesma base — não soma
    dobrado — e ATUALIZA NO LUGAR o snapshot já datado no mesmo fim (nunca
    empilha um segundo ponto com a mesma data: o histórico fica rastreável,
    um ponto por período). Backfill fora de ordem entre períodos: o mês entra
    no histórico; reimporte os meses seguintes (em ordem) para o acumulado
    incorporá-lo.
    """
    base = None
    ultimo_ate_fim = None
    ja_no_periodo = False
    posteriores = False
    for snap in serie:
        ref = _sem_fuso(snap.data_referencia)
        if ref < inicio:
            base = snap
        elif ref <= fim:
            ja_no_periodo = True
        if ref <= fim:
            ultimo_ate_fim = snap
        else:
            posteriores = True

    ativ_rel = _num(dados.get("atividades", 0) or 0, int)
    estrelas_rel = _num(dados.get("estrelas", 0) or 0, int)
    media_rel = _num(dados.get("pontuacao_media", 0) or 0.0, float)

    base_ativ = base.atividades if base else 0
    base_estrelas = base.estrelas if base else 0
    base_media = base.pontuacao_media if base else 0.0
    cand_ativ = base_ativ + ativ_rel
    cand_estrelas = base_estrelas + estrelas_rel
    cand_media = (round((base_media * base_ativ + media_rel * ativ_rel)
                        / cand_ativ, 4) if cand_ativ else 0.0)

    # Piso: acumulado já registrado até o fim do intervalo (idempotente para
    # reimportação — o snapshot anterior do próprio período vale base+ganhos).
    piso_ativ = ultimo_ate_fim.atividades if ultimo_ate_fim else 0
    piso_estrelas = ultimo_ate_fim.estrelas if ultimo_ate_fim else 0
    novo_ativ = max(cand_ativ, piso_ativ)
    novo_estrelas = max(cand_estrelas, piso_estrelas)
    if piso_ativ > cand_ativ:
        novo_media = ultimo_ate_fim.pontuacao_media
        contadores["preservados"] += 1
    else:
        novo_media = cand_media

    # Mudou = nasce um retrato do período (não havia um datado neste fim) ou o
    # que havia muda de valor (ver "mudou" em ``_importar_matific``).
    mudou = True
    if base is None:
        # Snapshot-base na véspera do início valendo (novo − ganhos): o delta
        # do período é exatamente o ganho do relatório, e um acumulado antigo
        # que caiu dentro do intervalo não é atribuído a este período.
        base_ativ_virtual = max(0, novo_ativ - ativ_rel)
        db.add(SnapshotMatific(
            escola_id=escola_id, aluno_id=aluno.id, importacao_id=importacao.id,
            data_referencia=inicio - timedelta(seconds=1),
            atividades=base_ativ_virtual,
            estrelas=max(0, novo_estrelas - estrelas_rel),
            pontuacao_media=(ultimo_ate_fim.pontuacao_media
                             if ultimo_ate_fim and base_ativ_virtual else 0.0),
        ))

    # Snapshot já datado EXATAMENTE no fim deste período (reimportação): atualiza
    # o mais recente deles no lugar, com a importação nova como origem. Linhas
    # duplicadas antigas (de antes desta regra) ficam intactas — nada é apagado.
    mesmo_fim = None
    for snap in serie:
        if _sem_fuso(snap.data_referencia) == fim:
            mesmo_fim = snap
    if (mesmo_fim is None and em_andamento and ultimo_ate_fim is not None
            and _sem_fuso(ultimo_ate_fim.data_referencia) >= inicio
            and _mesmo_dia(ultimo_ate_fim.data_referencia, fim)):
        # Período EM ANDAMENTO: o fim foi cortado em "agora", então cada coleta
        # tem um fim diferente e nunca batia com o retrato anterior — cada
        # repetição SEM mudança empilhava um retrato e saía "N alunos com dado
        # novo" (recálculo, notificação, último sucesso renovado). O retrato do
        # MESMO DIA dentro do período é atualizado no lugar (como no acumulado),
        # com a data acompanhando.
        mesmo_fim = ultimo_ate_fim
    if mesmo_fim is not None:
        mudou = base is None or (mesmo_fim.atividades, mesmo_fim.estrelas,
                                 mesmo_fim.pontuacao_media) != (novo_ativ, novo_estrelas,
                                                                novo_media)
        mesmo_fim.atividades = novo_ativ
        mesmo_fim.estrelas = novo_estrelas
        mesmo_fim.pontuacao_media = novo_media
        mesmo_fim.importacao_id = importacao.id
        _avancar_data(mesmo_fim, fim)
    else:
        # Retrato novo: "mudou" só se o valor difere do último até o fim (antes,
        # sempre True — uma coleta de período em andamento no dia seguinte, sem
        # nenhuma atividade nova, contava todos os alunos como atualizados).
        if base is not None:
            mudou = ultimo_ate_fim is None or (
                ultimo_ate_fim.atividades, ultimo_ate_fim.estrelas,
                ultimo_ate_fim.pontuacao_media) != (novo_ativ, novo_estrelas, novo_media)
        db.add(SnapshotMatific(
            escola_id=escola_id, aluno_id=aluno.id, importacao_id=importacao.id,
            data_referencia=fim,
            atividades=novo_ativ, estrelas=novo_estrelas,
            pontuacao_media=novo_media,
        ))
    if ja_no_periodo:
        contadores["reimportados"] += 1
    if posteriores:
        contadores["historico"] += 1
    return mudou


def _importar_elefante_resumo(db, escola_id, importacao, aluno, dados, data_referencia,
                              anterior=_SEM_PRECARGA, avisos: list | None = None,
                              sem_retrato_repetido: bool = False):
    # `anterior` pode vir pré-carregado em lote pelo /confirmar (evita o N+1) — e,
    # num relatório RETRODATADO, é o retrato que valia NA DATA dele
    # (``_mapa_retrato_na_data``), nunca o mais novo.
    if anterior is _SEM_PRECARGA:
        anterior = _snapshot_atual(db, escola_id, aluno.id, SnapshotElefante)
    por_nivel = dados.get("livros_por_nivel")
    if por_nivel is None:
        # Relatório sem a coluna de níveis: preserva a distribuição conhecida
        por_nivel = anterior.livros_por_nivel if anterior else {}
    livros = dados.get("livros_unicos")
    if livros is None:
        livros = (sum(_num(v, int) for v in por_nivel.values()) if por_nivel
                  else (anterior.livros_unicos if anterior else 0))
    livros_unicos = _num(livros, int)
    if avisos is not None and livros_unicos > 0 and not any(
            _num(v, int) for v in (por_nivel or {}).values()):
        # Livros contados, distribuição por nível DESCONHECIDA: a dificuldade não
        # é "zero" — o motor carimba `dificuldade.incompleto` e a tela deve dizer.
        avisos.append(
            f"{aluno.nome}: o relatório traz {livros_unicos} livro(s) mas NÃO a "
            "distribuição por nível — a dificuldade fica desconhecida (não zero) "
            "até importar o relatório individual ou a sincronização trazer os livros.")
    tempo = _num(dados.get("tempo_leitura_min",
                           anterior.tempo_leitura_min if anterior else 0), int)
    tentativas = _num(dados.get("questoes_tentativas",
                                anterior.questoes_tentativas if anterior else 0), int)
    acertos = _num(dados.get("questoes_acertos",
                             anterior.questoes_acertos if anterior else 0), int)
    # Reimportar/complementar no MESMO dia atualiza o snapshot do dia
    # (idempotente). Semântica COMPLEMENTAR: os campos já foram resolvidos acima
    # como "presente vence; ausente herda o anterior" — o relatório mais recente
    # é a fonte autoritativa.
    # Mudou? (a mesma régua de ``_importar_matific``: primeiro retrato ou valor
    # diferente do atual).
    mudou = anterior is None or (
        anterior.livros_unicos, anterior.tempo_leitura_min, anterior.questoes_tentativas,
        anterior.questoes_acertos, anterior.livros_por_nivel or {},
    ) != (livros_unicos, tempo, tentativas, acertos, por_nivel or {})
    if sem_retrato_repetido and anterior is not None and not mudou:
        # A resposta perdeu tempo/questões (S9): um retrato com os MESMOS números e a
        # data de hoje diria que foram medidos hoje — as Questões do período o
        # leriam como "0 no período". Sem ele, a última medida continua a de antes
        # e o relatório declara a cobertura como ela é.
        return False
    if anterior is not None and _mesmo_dia(anterior.data_referencia, data_referencia):
        anterior.livros_unicos = livros_unicos
        anterior.tempo_leitura_min = tempo
        anterior.questoes_tentativas = tentativas
        anterior.questoes_acertos = acertos
        anterior.livros_por_nivel = por_nivel
        anterior.importacao_id = importacao.id
        _avancar_data(anterior, data_referencia)
        return mudou
    db.add(SnapshotElefante(
        escola_id=escola_id, aluno_id=aluno.id, importacao_id=importacao.id,
        data_referencia=data_referencia,
        livros_unicos=livros_unicos,
        tempo_leitura_min=tempo,
        questoes_tentativas=tentativas,
        questoes_acertos=acertos,
        livros_por_nivel=por_nivel,
    ))
    return mudou


# Vocabulário OFICIAL de níveis do Elefante (escada A3 AA…Z + tier Z+ e A+). Sem
# casamento no catálogo oficial, o nível da linha precisa ser um destes.
_NIVEIS_OFICIAIS = frozenset(scoring.NIVEIS_ORDENADOS) | {"Z+", "A+"}


def _id_oficial(valor) -> int | None:
    """``elefante_id`` da linha como inteiro positivo (a API manda int; uma
    planilha pode mandar texto numérico). Qualquer outra coisa → None."""
    if isinstance(valor, bool):
        return None
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    if isinstance(valor, str) and valor.strip().isdigit():
        valor = int(valor.strip())
    return valor if isinstance(valor, int) and valor > 0 else None


class _AcervoEscola:
    """Livros da escola indexados pela IDENTIDADE OFICIAL — carregado UMA vez por
    importação/sincronização e compartilhado entre todos os alunos do lote (era
    relido por aluno).

    Casamento de uma linha (``resolver``), nesta ordem:
      1. id oficial vindo da linha (``dados["elefante_id"]``, API do Elefante);
      2. id resolvido no catálogo oficial por título+nível;
      3. livro da escola com o mesmo (título normalizado, nível oficial);
      4. livro da escola com o mesmo título — só se for ÚNICO e sem conflito de
         nível (homônimos oficiais, ex.: "Cadê?" B e BB ou "Chapeuzinho Vermelho"
         I e K, são livros DISTINTOS).

    NÍVEL DE REFERÊNCIA da linha (``nivel_ref``): o do CATÁLOGO quando houve
    casamento real (``meta is not None``); senão o informado pelo RELATÓRIO —
    que a escola controla (planilha/PDF/corpo do /confirmar) e que NUNCA é
    autoritativo. Reconciliação de um livro existente (uma vez por importação):
      * vincula ``elefante_id``/``word_count`` se faltarem — só com id que
        EXISTE no catálogo oficial (auditoria AGREGADA);
      * ``nivel_fonte`` = nível de referência (último nível recebido);
      * COM casamento no catálogo e oficial ≠ efetivo: com
        ``origem_nivel='admin_global'`` o efetivo é PRESERVADO e a divergência
        auditada (``livro.nivel_divergente``, só quando ``nivel_fonte`` muda);
        com ``fonte``/``legado`` o efetivo volta ao oficial
        (``livro.nivel_oficial_restaurado``, com de/para).
      * SEM casamento no catálogo: o nível efetivo NUNCA é reescrito (a escola
        não renivela livro pela planilha) — grava-se apenas ``nivel_fonte`` e a
        divergência vai para ``livro.nivel_divergente`` com ``no_catalogo``
        False; o aviso diz "nível informado pelo relatório", jamais "voltou ao
        nível oficial".
    Nenhum histórico é apagado: leituras seguem apontando para o mesmo livro.
    """

    def __init__(self, db, escola_id: int):
        self.escola_id = escola_id
        self.oficial = dificuldade_livro.catalogo()
        self.por_id: dict[int, Livro] = {}
        self.por_titulo_nivel: dict[tuple[str, str], Livro] = {}
        self.por_titulo: dict[str, list[Livro]] = {}
        self._conciliados: set[int] = set()        # id() dos livros já reconciliados
        self._avisados: set[tuple[str, str]] = set()
        self.vinculados: list[dict] = []
        # id da linha → (título da linha, motivo do descarte)
        self.ids_descartados: dict[int, tuple[str, str]] = {}
        self.restaurados = 0
        self.divergentes = 0
        self.fora_catalogo = 0     # livros SEM casamento no catálogo com nível divergente
        for livro in db.execute(
            select(Livro).where(Livro.escola_id == escola_id).order_by(Livro.id)
        ).scalars():
            self._indexar(livro)

    def _indexar(self, livro: Livro) -> None:
        chave = dificuldade_livro.normalizar_titulo(livro.titulo)
        self.por_titulo_nivel.setdefault((chave, livro.nivel_codigo), livro)
        self.por_titulo.setdefault(chave, []).append(livro)
        if livro.elefante_id is not None:
            self.por_id.setdefault(livro.elefante_id, livro)

    def _reindexar_nivel(self, livro: Livro, nivel_antigo: str) -> None:
        chave = dificuldade_livro.normalizar_titulo(livro.titulo)
        if self.por_titulo_nivel.get((chave, nivel_antigo)) is livro:
            del self.por_titulo_nivel[(chave, nivel_antigo)]
        self.por_titulo_nivel.setdefault((chave, livro.nivel_codigo), livro)

    @staticmethod
    def _conflita_id(livro: Livro, eid: int | None) -> bool:
        return livro.elefante_id is not None and eid is not None and livro.elefante_id != eid

    def _conflita_nivel(self, livro: Livro, chave: str, nivel_oficial: str | None) -> bool:
        """Título homônimo no catálogo oficial e o livro da escola está em OUTRO
        nível: são livros diferentes, não casar pelo título."""
        if not nivel_oficial or len(self.oficial.por_titulo.get(chave) or []) < 2:
            return False
        return (livro.nivel_fonte or livro.nivel_codigo) != nivel_oficial

    def resolver(self, titulo: str, nivel_linha: str, eid_linha: int | None):
        """``(livro da escola | None, id oficial | None, metadados do catálogo |
        None, nível de referência | None)``. O nível de referência é o do
        CATÁLOGO quando houve casamento (``meta``); sem casamento é só o nível
        informado pelo relatório, usado para ACHAR o livro da escola — nunca
        como "nível oficial". Não altera nada."""
        chave = dificuldade_livro.normalizar_titulo(titulo)
        if eid_linha is not None:
            eid, meta = eid_linha, self.oficial.por_id.get(eid_linha)
        else:
            meta = self.oficial.buscar(titulo, nivel_linha)
            eid = meta.id if meta is not None else None
        nivel_ref = meta.nivel if meta is not None else (nivel_linha or None)
        livro = self.por_id.get(eid) if eid is not None else None
        if livro is None and nivel_ref:
            candidato = self.por_titulo_nivel.get((chave, nivel_ref))
            if candidato is not None and not self._conflita_id(candidato, eid):
                livro = candidato
        if livro is None:
            candidatos = [l for l in self.por_titulo.get(chave, [])
                          if not self._conflita_id(l, eid)]
            if len(candidatos) == 1 and not self._conflita_nivel(
                    candidatos[0], chave, nivel_ref):
                livro = candidatos[0]
        return livro, eid, meta, nivel_ref

    def _id_da_linha(self, dados: dict, titulo: str, nivel_linha: str) -> int | None:
        """Id oficial da linha — só vale com casamento de TÍTULO no catálogo.

        O ``elefante_id`` chega pelo corpo do /confirmar (planilha, PDF, JSON
        montado à mão) ou pela API do Elefante; em ambos os casos ele só
        identifica este livro quando a entrada do catálogo com esse id tem o
        MESMO título normalizado da linha. O nível da linha NÃO valida um id (a
        escola controla o relatório e poderia forjar o par nível+id de outro
        livro para trocar identidade, wordCount e nível). Id ausente do catálogo
        também não vincula — vincular um id desconhecido cria duplicata quando o
        id verdadeiro chega depois. Nos dois casos a linha cai no casamento por
        título+nível e o descarte vai para o aviso/auditoria da importação."""
        eid = _id_oficial(dados.get("elefante_id"))
        if eid is None:
            return None
        meta = self.oficial.por_id.get(eid)
        if meta is None:
            self.ids_descartados.setdefault(eid, (titulo, "fora_do_catalogo"))
            return None
        if (dificuldade_livro.normalizar_titulo(meta.titulo)
                == dificuldade_livro.normalizar_titulo(titulo)):
            return eid
        self.ids_descartados.setdefault(eid, (titulo, "titulo_diferente"))
        return None

    def livro_da_linha(self, db, importacao, titulo: str, nivel_linha: str,
                       dados: dict, avisos: list) -> tuple[Livro | None, bool]:
        """Resolve a linha e devolve ``(livro, rejeitada)``: o livro (existente,
        reconciliado, ou novo) ou None quando a linha é ignorada; ``rejeitada``
        marca nível fora do vocabulário (sem leitura e sem evento)."""
        chave = dificuldade_livro.normalizar_titulo(titulo)
        livro, eid, meta, nivel_ref = self.resolver(
            titulo, nivel_linha, self._id_da_linha(dados, titulo, nivel_linha))
        if livro is not None and meta is None and livro.elefante_id is not None:
            # Livro da escola JÁ vinculado ao catálogo: o nível oficial é o do id
            # dele — uma linha sem casamento no catálogo (ex.: planilha com nível
            # de homônimo) nunca troca o ``nivel_fonte`` pelo nível da linha.
            meta_livro = self.oficial.por_id.get(livro.elefante_id)
            if meta_livro is not None:
                meta, nivel_ref = meta_livro, meta_livro.nivel
        if meta is None and nivel_linha and nivel_linha not in _NIVEIS_OFICIAIS:
            if (chave, nivel_linha) not in self._avisados:
                self._avisados.add((chave, nivel_linha))
                avisos.append(
                    f"Livro “{titulo}”: o nível “{nivel_linha}” não existe no Elefante "
                    "Letrado (AA…Z, Z+, A+) — linha ignorada.")
            return None, True
        if meta is not None and nivel_linha and nivel_linha != meta.nivel \
                and (chave, nivel_linha) not in self._avisados:
            self._avisados.add((chave, nivel_linha))
            avisos.append(
                f"“{titulo}”: o relatório informa o nível {nivel_linha}, mas o nível "
                f"oficial no catálogo do Elefante é {meta.nivel} — vale o oficial.")
        if livro is None:
            if not nivel_ref:
                avisos.append(f"Livro “{titulo}” é novo e veio sem nível — ignorado.")
                return None, False
            # FORA do catálogo oficial o nível é o que o relatório informou: o
            # livro nasce como ``legado`` (alteração local), não como se viesse
            # da fonte oficial. Só com casamento real no catálogo é ``fonte``.
            livro = Livro(escola_id=self.escola_id, titulo=titulo,
                          nivel_codigo=nivel_ref, nivel_fonte=nivel_ref,
                          origem_nivel="fonte" if meta is not None else "legado",
                          elefante_id=eid if meta is not None else None,
                          word_count=meta.word_count if meta is not None else None,
                          categoria=dados.get("genero") or None)
            db.add(livro)
            self._indexar(livro)       # dedup dentro do lote sem flush por livro
            self._conciliados.add(id(livro))
            return livro, False
        self._conciliar(db, importacao, livro, eid, meta, nivel_ref)
        return livro, False

    def _conciliar(self, db, importacao, livro: Livro, eid, meta, nivel_ref) -> None:
        if id(livro) in self._conciliados:
            return
        self._conciliados.add(id(livro))
        if (eid is not None and livro.elefante_id is None
                and self.oficial.por_id.get(eid) is not None):
            # Só vincula id que EXISTE no catálogo oficial: um id desconhecido
            # (outra entidade da API) tomaria a identidade do livro e viraria
            # duplicata quando o id verdadeiro chegasse.
            livro.elefante_id = eid
            self.por_id.setdefault(eid, livro)
            self.vinculados.append({"livro_id": livro.id, "elefante_id": eid})
        if meta is not None and livro.word_count is None and livro.elefante_id == meta.id:
            livro.word_count = meta.word_count
        if not nivel_ref:
            return
        fonte_anterior = livro.nivel_fonte
        livro.nivel_fonte = nivel_ref
        if livro.nivel_codigo == nivel_ref:
            return
        detalhes = {"titulo": livro.titulo, "elefante_id": livro.elefante_id,
                    "importacao_id": importacao.id}
        if meta is None:
            # SEM casamento no catálogo oficial: o nível veio do RELATÓRIO, que a
            # escola controla — NUNCA reescreve o nível em uso (seria renivelar o
            # livro da escola inteira por planilha). Registra a divergência com o
            # nome honesto; o aviso não fala em "nível oficial".
            if fonte_anterior != nivel_ref:
                self.fora_catalogo += 1
                registrar(db, "livro.nivel_divergente", escola_id=self.escola_id,
                          usuario_id=importacao.usuario_id, entidade="livro",
                          entidade_id=livro.id,
                          detalhes={**detalhes, "no_catalogo": False,
                                    "nivel_efetivo": livro.nivel_codigo,
                                    "nivel_relatorio": {"de": fonte_anterior,
                                                        "para": nivel_ref}})
            return
        if livro.origem_nivel == "admin_global":
            # Correção deliberada do Admin Global: PRESERVADA. Só audita quando a
            # fonte traz um nível novo (não a cada sincronização).
            if fonte_anterior != nivel_ref:
                self.divergentes += 1
                registrar(db, "livro.nivel_divergente", escola_id=self.escola_id,
                          usuario_id=importacao.usuario_id, entidade="livro",
                          entidade_id=livro.id,
                          detalhes={**detalhes, "no_catalogo": True,
                                    "nivel_efetivo": livro.nivel_codigo,
                                    "nivel_fonte": {"de": fonte_anterior,
                                                    "para": nivel_ref}})
            return
        # Alteração local (legado) ou nível antigo da fonte: volta ao oficial —
        # aqui ``meta`` existe, então este É o nível do catálogo oficial.
        de, origem = livro.nivel_codigo, livro.origem_nivel
        livro.nivel_codigo = nivel_ref
        livro.origem_nivel = "fonte"
        livro.atualizado_em = agora()
        self._reindexar_nivel(livro, de)
        self.restaurados += 1
        registrar(db, "livro.nivel_oficial_restaurado", escola_id=self.escola_id,
                  usuario_id=importacao.usuario_id, entidade="livro", entidade_id=livro.id,
                  detalhes={**detalhes, "de": de, "para": nivel_ref,
                            "origem_anterior": origem})

    def finalizar(self, db, importacao, avisos: list) -> None:
        """Auditoria AGREGADA por importação dos vínculos à identidade oficial
        (uma linha, não uma por livro) e avisos-resumo das reconciliações."""
        if self.vinculados:
            registrar(db, "livro.vinculado_catalogo", escola_id=self.escola_id,
                      usuario_id=importacao.usuario_id, entidade="importacao",
                      entidade_id=importacao.id,
                      detalhes={"qtd": len(self.vinculados),
                                "livros": self.vinculados[:500]})
        if self.ids_descartados:
            registrar(db, "livro.id_oficial_inconsistente", escola_id=self.escola_id,
                      usuario_id=importacao.usuario_id, entidade="importacao",
                      entidade_id=importacao.id,
                      detalhes={"qtd": len(self.ids_descartados),
                                "ids": [{"elefante_id": eid, "titulo_linha": titulo,
                                         "motivo": motivo}
                                        for eid, (titulo, motivo) in
                                        list(self.ids_descartados.items())[:200]]})
            avisos.append(
                f"{len(self.ids_descartados)} id(s) de livro do relatório não batem "
                "com o catálogo oficial (id inexistente ou de outro título) — "
                "ignorados; esses livros foram casados por título e nível. "
                "Registrado na auditoria.")
        if self.restaurados:
            avisos.append(
                f"{self.restaurados} livro(s) voltaram ao nível oficial do catálogo do "
                "Elefante (havia alteração local) — registrado na auditoria.")
        if self.fora_catalogo:
            avisos.append(
                f"{self.fora_catalogo} livro(s) NÃO estão no catálogo oficial do "
                "Elefante e o nível informado pelo relatório é diferente do nível em "
                "uso — o nível em uso foi preservado (a escola não renivela livro por "
                "importação) e a divergência registrada na auditoria.")
        if self.divergentes:
            avisos.append(
                f"{self.divergentes} livro(s) mantêm o nível corrigido pelo Admin "
                "Global, diferente do nível oficial — divergência registrada na auditoria.")


def _catalogo_livros(db, escola_id: int) -> _AcervoEscola:
    """Acervo da escola indexado pela identidade oficial — UMA vez por sync."""
    return _AcervoEscola(db, escola_id)


def _codigos_faixa_escola(db, escola_id: int) -> set:
    """Letras de nível que estão em ALGUMA faixa configurada (UMA vez por sync)."""
    return {
        c.upper()
        for nivel in db.execute(
            select(NivelDificuldade).where(NivelDificuldade.escola_id == escola_id)
        ).scalars()
        for c in (nivel.codigos or [])
    }


def _ja_lidos_por_aluno(db, aluno_ids) -> dict:
    """{aluno_id: set(livro_id)} das leituras já gravadas — UMA consulta em lote
    (era uma por aluno). Dedup de releitura (§35) sem N idas ao banco."""
    mapa: dict[int, set] = {}
    ids = list(aluno_ids)
    if not ids:
        return mapa
    for aid, lid in db.execute(
        select(Leitura.aluno_id, Leitura.livro_id)
        .where(Leitura.aluno_id.in_(ids))
    ).all():
        mapa.setdefault(aid, set()).add(lid)
    return mapa


def _data_do_retrato_das_leituras(data_referencia, ultima_leitura):
    """Data do retrato DERIVADO do relatório individual: max(data do relatório,
    leitura mais nova do aluno), nunca depois de agora. O retrato é o TOTAL de todas
    as leituras registradas: datado antes da mais nova, contaria uma leitura de
    outubro num ponto de agosto (relatório individual com data passada, só pela
    API, e sem retrato válido posterior). Leitura com data no futuro (ou absurda)
    não leva o retrato para o futuro. ``Leitura.data`` é naive (UTC, a convenção do
    ``data_referencia``). Na sincronização e no upload sem data, a data do relatório
    já é o agora do início da importação: só uma leitura datada depois disso a
    moveria, e no máximo até agora."""
    if ultima_leitura is None:
        return data_referencia
    candidata = min(_instante_utc(ultima_leitura), _agora_utc())
    if candidata <= _instante_utc(data_referencia):
        return data_referencia
    return candidata.replace(tzinfo=timezone.utc)


def _importar_elefante_leituras(db, escola_id, importacao, aluno, linhas,
                                data_referencia, avisos, catalogo, ja_lidos,
                                codigos_faixa, *, sem_retrato_repetido: bool = False):
    """Formato "uma linha por livro concluído": registra leituras únicas (§35).

    Todo o trabalho de banco é feito EM LOTE. O ``catalogo`` (livros da escola),
    o ``ja_lidos`` (livros já lidos por este aluno) e o ``codigos_faixa`` (níveis
    configurados) são carregados UMA vez por sincronização e passados — antes
    eram relidos por ALUNO (~190× numa escola de 10 turmas), o que no Postgres de
    rede (Supabase) transformava a coleta do Elefante em ~15 min. Livros criados
    aqui entram no ``catalogo`` compartilhado (dedup também entre alunos do lote).

    IDENTIDADE: cada linha é resolvida pelo ``_AcervoEscola`` (id oficial →
    catálogo por título+nível → título+nível da escola → título único sem
    conflito). A deduplicação de releitura é pela IDENTIDADE do livro, não pelo
    título — homônimos oficiais ("Cadê?" B e BB) são livros distintos e as duas
    leituras contam. A linha do tempo usa a MESMA resolução.

    NÍVEL CONGELADO: toda leitura nova nasce com ``Leitura.nivel_codigo`` = o
    nível EFETIVO do livro NESTE momento — que, depois da reconciliação do
    ``_AcervoEscola``, é o nível OFICIAL do catálogo quando houve casamento (o
    relatório da escola diverge? vale o oficial), a correção deliberada do Admin
    Global quando existe (``origem_nivel='admin_global'`` é preservada) ou, só
    para livro FORA do catálogo, o nível da linha já validado. Junto vai
    ``catalogo_versao`` = o mesmo carimbo de versão (sha curto do arquivo) que a
    nota usa. Consequência: renivelar um livro depois NÃO reescreve o passado —
    a distribuição por nível do aluno usa
    ``coalesce(Leitura.nivel_codigo, Livro.nivel_codigo)`` e só as leituras
    anteriores a esta versão (nível nulo) seguem o nível atual do livro.

    ``EventoAluno.nivel_codigo`` NÃO muda de semântica: continua sendo o nível da
    FONTE no instante do evento (o do livro resolvido; sem livro, o da linha).
    Como a resolução é a MESMA da leitura, o evento e o nível congelado da
    leitura nascem coerentes; releituras (§35 não pontua) geram evento e nenhuma
    leitura, então só o evento guarda aquele instante.
    """
    vistos: set[int] = set()            # id() dos livros já processados NESTE lote
    resolvidos: dict[int, Livro] = {}   # nº da linha → livro resolvido (linha do tempo)
    rejeitadas: set[int] = set()        # nível fora do vocabulário: sem leitura nem evento
    # (livro, quando, tempo, nível congelado) de cada leitura nova deste aluno.
    novas: list[tuple] = []
    # Versão do catálogo VIGENTE nesta importação — carimbo idêntico ao que a
    # nota grava em ``detalhes.elefante.dificuldade.catalogo``. None sem arquivo.
    versao_cat = dificuldade_livro.versao_catalogo().get("versao")
    for indice, linha in enumerate(linhas):
        titulo = str(linha.dados.get("livro", "")).strip()
        nivel = str(linha.dados.get("nivel", "")).strip().upper()
        if not titulo:
            avisos.append(f"Linha {linha.nome}: livro sem título — ignorada.")
            continue
        livro, rejeitada = catalogo.livro_da_linha(db, importacao, titulo, nivel,
                                                   linha.dados, avisos)
        if rejeitada:
            rejeitadas.add(indice)
        if livro is None:
            continue
        resolvidos[indice] = livro
        # Releitura no MESMO relatório (livro repetido): dedup em memória —
        # senão a UniqueConstraint derrubaria a importação (autoflush=False).
        if id(livro) in vistos:
            avisos.append(f"“{titulo}” aparece mais de uma vez no relatório de "
                          f"{aluno.nome} — contado uma vez (§35).")
            continue
        if livro.id is not None and livro.id in ja_lidos:
            avisos.append(f"“{titulo}” já constava para {aluno.nome} — releitura não pontua (§35).")
            continue
        vistos.add(id(livro))
        # Relatórios individuais informam a data e o HORÁRIO reais da conclusão.
        quando = data_referencia
        try:
            bruto = linha.dados.get("data")
            if bruto:
                quando = datetime.fromisoformat(str(bruto))
        except ValueError:
            pass
        # Guarda sempre naive (a data do relatório é naive; o padrão é aware):
        # os filtros por período comparam datetimes homogêneos.
        if quando.tzinfo is not None:
            quando = quando.replace(tzinfo=None)
        tempo_livro = linha.dados.get("tempo_livro_min")
        # O nível é lido AQUI, depois da reconciliação desta linha: é o nível
        # efetivo do livro no instante em que a leitura passa a existir.
        novas.append((livro, quando,
                      _num(tempo_livro, int) if tempo_livro is not None else None,
                      livro.nivel_codigo))

    # Persiste PRIMEIRO os livros novos (ganham id) e então grava todas as
    # leituras num único INSERT executemany — uma ida ao banco, não N.
    db.flush()
    if novas:
        from sqlalchemy import insert
        db.execute(insert(Leitura), [
            {"escola_id": escola_id, "aluno_id": aluno.id, "livro_id": livro.id,
             "data": quando, "tempo_leitura_min": tempo,
             # NÍVEL CONGELADO + versão do catálogo que o resolveu.
             "nivel_codigo": nivel or None, "catalogo_versao": versao_cat}
            for livro, quando, tempo, nivel in novas
        ])

    # ESPELHO evento a evento (linha do tempo): 1 EventoAluno por leitura do
    # histórico individual — inclui RELEITURAS (cada linha tem sua data/hora
    # própria, diferente das leituras que pontuam o livro uma única vez §35).
    # Idempotente por chave_natural: reimportar o mesmo relatório não duplica.
    eventos: list[dict] = []
    for indice, linha in enumerate(linhas):
        if indice in rejeitadas:
            continue  # nível fora do vocabulário oficial: a linha foi ignorada
        titulo = str(linha.dados.get("livro", "")).strip()
        bruto = linha.dados.get("data")
        if not titulo or not bruto:
            continue  # um evento de leitura exige título e data/hora reais
        try:
            quando = datetime.fromisoformat(str(bruto))
        except ValueError:
            continue
        if quando.tzinfo is not None:
            quando = quando.replace(tzinfo=None)
        tempo_livro = linha.dados.get("tempo_livro_min")
        genero = str(linha.dados.get("genero", "")).strip(" ,")
        livro = resolvidos.get(indice)   # a MESMA resolução da leitura
        # Nível da FONTE no instante do evento — semântica INALTERADA (o espelho
        # registra o que a plataforma mostrava). Vem da MESMA resolução da
        # leitura, então é o mesmo valor congelado em ``Leitura.nivel_codigo``
        # para a linha que pontuou; quem PONTUA lê a leitura, não o evento.
        nivel = (livro.nivel_codigo if livro is not None
                 else str(linha.dados.get("nivel", "")).strip().upper())
        eventos.append({
            "escola_id": escola_id, "aluno_id": aluno.id,
            "importacao_id": importacao.id, "plataforma": "elefante",
            "tipo_evento": "leitura", "ocorrido_em": quando,
            "chave_natural": chave_evento("elefante", "leitura", aluno.id,
                                          titulo, quando),
            "conteudo_titulo": titulo[:300], "nivel_codigo": nivel or None,
            "tempo_segundos": (_num(tempo_livro, int) * 60
                               if tempo_livro is not None else None),
            "livro_id": (livro.id if livro is not None else None),
            "dados": ({"genero": genero} if genero else {}),
        })
    n_eventos = ingerir_eventos(db, aluno.id, "elefante", eventos)

    # Snapshot derivado do total de leituras registradas. O nível de CADA
    # leitura é o CONGELADO (``Leitura.nivel_codigo``, gravado na importação que
    # a criou); só leitura anterior a esta versão (nível nulo) cai no nível atual
    # do livro. Assim renivelar um livro depois não muda, sozinha, a
    # distribuição por nível do aluno numa reimportação.
    # A data de cada leitura vem na MESMA consulta: a mais nova data o retrato.
    registradas = db.execute(
        select(func.coalesce(Leitura.nivel_codigo, Livro.nivel_codigo), Leitura.data)
        .select_from(Leitura)
        .join(Livro, Leitura.livro_id == Livro.id)
        .where(Leitura.aluno_id == aluno.id)
    ).all()
    leituras = [codigo for codigo, _ in registradas]
    por_nivel: dict[str, int] = {}
    for codigo in leituras:
        por_nivel[codigo] = por_nivel.get(codigo, 0) + 1
    data_retrato = _data_do_retrato_das_leituras(
        data_referencia, max((d for _, d in registradas if d is not None), default=None))

    # Avisa se algum nível de letra não está em nenhuma faixa cadastrada: na
    # regra global (v1) toda letra AA–Z/Z+/A+ PONTUA pela régua A3 — a letra só
    # não aparece no gráfico por faixa (e, no perfil personalizado, não pontua
    # pela régua da escola) até ser incluída em Métricas.
    # (``codigos_faixa`` já vem carregado uma vez por sincronização.)
    fora = sorted({c for c in por_nivel if c and c.upper() not in codigos_faixa})
    if fora:
        avisos.append(
            f"{aluno.nome}: níveis {', '.join(fora)} não estão em nenhuma faixa "
            "cadastrada — pontuam pela régua global, mas não aparecem no gráfico "
            "por faixa (e não pontuam na régua personalizada) até serem incluídos "
            "em Métricas → Dificuldade.")
    # Retrato datado no futuro (legado) não é o atual — ver ``_teto_retrato_valido``.
    anterior = _snapshot_atual(db, escola_id, aluno.id, SnapshotElefante,
                               ate=_teto_retrato_valido(_agora_utc()))
    # O resumo do relatório individual COMPLEMENTA o tempo de leitura de quem
    # ainda não tem snapshot; nunca rebaixa o valor vindo do relatório da turma.
    tempo_relatorio = max(
        (_num(l.dados.get("tempo_leitura_min", 0) or 0, int) for l in linhas), default=0)
    # O contador da plataforma (relatório da turma) pode ser maior que o
    # histórico listado — o detalhamento individual nunca rebaixa a conta.
    livros_unicos = max(len(leituras), anterior.livros_unicos if anterior else 0)
    tempo = max(anterior.tempo_leitura_min if anterior else 0, tempo_relatorio)
    retrato_mudou = anterior is None or (
        anterior.livros_unicos, anterior.tempo_leitura_min, anterior.livros_por_nivel or {},
    ) != (livros_unicos, tempo, por_nivel or {})
    if anterior is not None and (_mesmo_dia(anterior.data_referencia, data_retrato)
                                 or _retrodatado(anterior, data_retrato)):
        # MESMO DIA (de Brasília): o retrato do dia é atualizado NO LUGAR, como no
        # resumo e no Matific — e só se algo mudou. Antes cada arquivo de leituras
        # EMPILHAVA um retrato: a coleta gravava dois por aluno (resumo + leituras)
        # e a 2ª coleta do dia, sem mudança nenhuma, somava mais um (A2 §3.18). As
        # questões ficam as do retrato do dia (vêm do resumo); livros e tempo
        # nunca baixam (máximo acima); a data acompanha o valor novo.
        # DATA ANTERIOR ao retrato atual (relatório individual com data passada,
        # só pela API): também no lugar, com a data max(relatório, atual) — o
        # retrato derivado é o TOTAL de todas as leituras registradas, não o que
        # valia naquela data. Antes nascia um ponto NA DATA com livros, tempo e
        # questões do retrato mais novo (os números de outubro num ponto de
        # agosto). A data passada fica nas Leituras e nos EventoAluno.
        # A data do retrato derivado nunca fica antes da leitura mais nova
        # (``_data_do_retrato_das_leituras``).
        if retrato_mudou:
            anterior.livros_unicos = livros_unicos
            anterior.tempo_leitura_min = tempo
            anterior.livros_por_nivel = por_nivel
            anterior.importacao_id = importacao.id
            _avancar_data(anterior, data_retrato)
    elif sem_retrato_repetido and anterior is not None and not retrato_mudou:
        # S9: a resposta desta coleta perdeu tempo/questões. Um retrato novo aqui só
        # repetiria os números de antes com a data de hoje (as Questões do período o
        # leriam como "0 no período"); as leituras novas já ficaram gravadas acima.
        pass
    else:
        db.add(SnapshotElefante(
            escola_id=escola_id, aluno_id=aluno.id, importacao_id=importacao.id,
            data_referencia=data_retrato,
            livros_unicos=livros_unicos,
            tempo_leitura_min=tempo,
            questoes_tentativas=anterior.questoes_tentativas if anterior else 0,
            questoes_acertos=anterior.questoes_acertos if anterior else 0,
            livros_por_nivel=por_nivel,
        ))
    # Mudou = leitura nova, evento novo da linha do tempo ou retrato com outro
    # valor (a conta de "alunos aplicados" da sincronização).
    return bool(novas) or n_eventos > 0 or retrato_mudou


def _finalizar_importacao(db: Session, escola_id: int, *, corpo: str) -> int:
    """Fecha uma importação: recalcula notas/rankings, invalida o cache do painel
    público e notifica a escola. Ponto ÚNICO de finalização — usado pelo
    /confirmar (recalcular=true) e pelo /recalcular (fim do lote), para os dois
    nunca divergirem no que fazem ao terminar."""
    n = scoring.recalcular_escola(db, escola_id)
    # Recálculo que deu certo fecha a pendência que uma sincronização deixou
    # (dado gravado, notas não recalculadas) — vale também para o /recalcular.
    from app.sync import service as sync_service
    if sync_service.resolver_recalculo_pendente(db, escola_id):
        db.commit()
    _pos_commit_importacao(db, escola_id, corpo=corpo)
    return n


def _pos_commit_importacao(db: Session, escola_id: int, *, corpo: str,
                           aluno_id: int | None = None) -> None:
    """Efeitos que NÃO pertencem à transação: cache em memória do processo e push
    para os aparelhos. Ficam DEPOIS do commit de propósito — notificar antes de
    a transação fechar avisaria sobre dado que pode nem existir, e o próprio
    ``notificar_escola`` commita ao limpar token morto (o que abriria a transação
    do chamador no meio). Não é reversível por rollback: é melhor esforço.

    ``aluno_id``: o aviso é de UMA criança (leva o primeiro nome) e só vai a quem a
    enxerga pela API (``push.notificar_escola``)."""
    from app.routers.publico import invalidar_cache_painel

    invalidar_cache_painel(escola_id)  # painel público reflete os novos dados
    push.notificar_escola(
        db, escola_id, titulo="Novos dados no Constela Edu",
        corpo=corpo, dados={"tela": "ranking"}, aluno_id=aluno_id)


class _ConfirmacaoDaSincronizacao(ImportacaoConfirm):
    """O MESMO pedido de importação, montado pelo ORQUESTRADOR da sincronização
    automática (``confirmacao_da_sincronizacao``). O tipo é o sinal do SERVIDOR de
    que a importação vem da coleta: nunca chega pelo corpo HTTP (a rota declara
    ``ImportacaoConfirm``). ``sincronizar_turma`` não serve de prova — é um campo
    aberto do schema, que qualquer admin/coordenador pode mandar pela API."""

    # A resposta perdeu tempo/questões em TODAS as linhas (S9): o retrato que só
    # repetiria os números de antes com a data de hoje não é gravado.
    _sem_retrato_repetido: bool = PrivateAttr(default=False)
    # As questões não vieram nesta execução (S9): os retratos desta importação levam
    # as da coleta anterior — a importação é marcada (``IMPORTACAO_SEM_QUESTOES``) e
    # as Questões do período não os usam como borda.
    _questoes_herdadas: bool = PrivateAttr(default=False)


def confirmacao_da_sincronizacao(dados: ImportacaoConfirm, *,
                                 sem_retrato_repetido: bool = False,
                                 questoes_herdadas: bool = False) -> ImportacaoConfirm:
    """Marca o pedido montado pela sincronização automática (só o orquestrador
    chama). Os valores já foram validados ao montar ``dados``: nada é revalidado e
    os campos informados continuam os mesmos."""
    marcado = _ConfirmacaoDaSincronizacao.model_construct(
        _fields_set=set(dados.model_fields_set),
        **{campo: getattr(dados, campo) for campo in ImportacaoConfirm.model_fields})
    marcado._sem_retrato_repetido = bool(sem_retrato_repetido)
    marcado._questoes_herdadas = bool(questoes_herdadas)
    return marcado


def _exigir_uma_linha_por_ficha_fixada(db: Session, escola_id: int,
                                       dados: ImportacaoConfirm) -> None:
    """DUAS LINHAS FIXADAS NA MESMA FICHA, com contas da plataforma diferentes ou com
    números diferentes no retrato: 422 antes de gravar qualquer coisa.

    A escolha explícita (``aluno_id``) sempre associa (``identidade_aluno.decidir``,
    passo 0); o núcleo agrupa as linhas por aluno e grava só a ÚLTIMA do retrato
    (``linhas_aluno[-1]``). Com a mesma ficha escolhida em duas linhas, o retrato
    dependia da ordem do arquivo, sem aviso, e as duas contas iam para a ficha (as
    coletas seguintes mandavam as duas para a Revisão). É a guarda que o /resolver já
    tem (``linhas_divergentes_do_mesmo_id``), aqui na entrada: quem confirma escolhe
    a linha que vale. A mesma linha repetida (mesma conta, mesmos números — a
    criança em duas turmas do Placar) e as linhas de livro (leituras, que somam) de
    uma conta só seguem normais. Só a escolha explícita entra: a sincronização não
    fixa ficha, e a linha deixada para a Revisão não associa."""
    por_aluno: dict[int, list] = {}
    for linha in dados.linhas:
        if linha.aluno_id is not None and not getattr(linha, "deixar_para_revisao", False):
            por_aluno.setdefault(linha.aluno_id, []).append(linha)
    suspeitos = {aid for aid, linhas in por_aluno.items() if len(linhas) > 1}
    if not suspeitos:
        return
    em_conflito = []
    for aid in sorted(suspeitos):
        linhas = por_aluno[aid]
        contas = {conta for ids in ida.contas_das_linhas(linhas, dados.plataforma).values()
                  for conta in ids}
        if len(contas) > 1 or ida.linhas_divergentes([l.dados or {} for l in linhas]):
            em_conflito.append(aid)
    if not em_conflito:
        return
    # Só fichas DESTA escola entram no texto (a de outra escola a linha ignora).
    nomes = db.execute(select(Aluno.nome).where(
        Aluno.escola_id == escola_id, Aluno.id.in_(em_conflito)).order_by(Aluno.nome)
    ).scalars().all()
    if not nomes:
        return
    raise HTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        "Mais de uma linha do relatório foi ligada ao mesmo aluno ("
        + ", ".join(f"“{n}”" for n in nomes)
        + "), com contas da plataforma ou números diferentes. Só uma linha pode ir "
        "para cada aluno: a importação guardaria apenas a última e ligaria as duas "
        "contas à mesma ficha. Ligue o aluno a uma linha só e deixe a outra para a "
        "Revisão de identidade. Nada foi gravado.")


@router.post("/confirmar", response_model=ImportacaoResultadoOut)
def confirmar(
    dados: ImportacaoConfirm,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Aplica a importação e COMMITA. O trabalho em si está em
    ``_confirmar_sem_commit``; aqui só se fecha a transação, recalcula quando
    pedido e dispara os efeitos de pós-commit. Quem precisa de uma transação
    MAIOR (o ``/resolver`` de revisão, que aplica várias irmãs) chama o núcleo
    direto e commita uma vez só.

    Plataforma de módulo fora do plano da rede → 403, antes de gravar qualquer
    coisa (a mesma trava da prévia; a sincronização tem a dela no serviço)."""
    svc_modulos.exigir_plataforma(
        svc_modulos.modulos_da_escola(db, db.get(Escola, escola_id)), dados.plataforma)
    _exigir_uma_linha_por_ficha_fixada(db, escola_id, dados)
    da_sync = isinstance(dados, _ConfirmacaoDaSincronizacao)
    nucleo = _confirmar_sem_commit(
        dados=dados, escola_id=escola_id, usuario=usuario, db=db,
        da_sincronizacao=da_sync,
        sem_retrato_repetido=da_sync and dados._sem_retrato_repetido,
        questoes_herdadas=da_sync and dados._questoes_herdadas)
    db.commit()

    # No modo lote, o recálculo/push acontece UMA vez ao final (via /recalcular),
    # não a cada arquivo — economiza dezenas de recálculos numa turma inteira.
    # "Atualizados" = alunos cujo dado MUDOU (``alunos_aplicados_ids``); os demais
    # foram conferidos sem mudança. Antes, repetir o mesmo relatório dizia (e
    # notificava) "N alunos atualizados" com nada novo.
    n_aplicados = len(nucleo.alunos_aplicados_ids)
    conferidos = max(0, nucleo.qtd_alunos - n_aplicados)
    resto = (f" ({conferidos} aluno(s) conferido(s) sem mudança)" if conferidos else "")
    if dados.recalcular:
        plataforma_nome = "Matific" if dados.plataforma == "matific" else "Elefante Letrado"
        # Sem aluno com dado novo (o mesmo relatório de novo), o push não diz "0 alunos
        # atualizados" a todos os aparelhos: diz que as notas foram recalculadas com o
        # que já estava gravado (o mesmo texto da sync, ``_recalcular_ao_final``). A
        # finalização segue igual (recálculo, pendência, cache do painel público).
        if n_aplicados:
            corpo = (f"{n_aplicados} alunos atualizados na {plataforma_nome}. "
                     "As notas já foram recalculadas.")
        else:
            corpo = f"Notas recalculadas com os dados já gravados da {plataforma_nome}."
        _finalizar_importacao(db, escola_id, corpo=corpo)
        mensagem = (f"Importação concluída: {n_aplicados} alunos atualizados{resto}. "
                    "Notas recalculadas automaticamente.")
    else:
        mensagem = f"{n_aplicados} aluno(s) com dado novo importado(s){resto}."
    if nucleo.criacao_bloqueada:
        # O MOTIVO na frase principal (a tela a mostra em destaque): a política
        # 'bloquear' barrou a ficha nova — não é falha da importação.
        mensagem += (f" {nucleo.criacao_bloqueada} aluno(s) sem ficha não foram criados: a "
                     "política desta escola não deixa a plataforma criar ficha (a "
                     "matrícula vem da Lista Piloto). Eles ficaram em Revisão de "
                     "identidade para um gestor apontar a ficha certa.")

    return ImportacaoResultadoOut(
        mensagem=mensagem,
        importacao_id=nucleo.importacao_id,
        qtd_alunos=nucleo.qtd_alunos,
        qtd_erros=nucleo.qtd_erros,
        avisos=nucleo.avisos,
        ignorados=nucleo.ignorados,
        qtd_revisoes=nucleo.qtd_revisoes,
        alunos_aplicados_ids=nucleo.alunos_aplicados_ids,
        linhas_recebidas=nucleo.linhas_recebidas,
        linhas_em_revisao=nucleo.linhas_em_revisao,
        linhas_descartadas=nucleo.linhas_descartadas,
        avisos_criticos=nucleo.avisos_criticos,
        contas_em_revisao=nucleo.contas_em_revisao,
        ids_de_outra_escola=nucleo.ids_de_outra_escola,
        criacao_bloqueada=nucleo.criacao_bloqueada,
    )


@dataclass
class _NucleoImportacao:
    """O que o núcleo produziu, ainda NÃO commitado."""
    importacao_id: int
    qtd_alunos: int
    qtd_erros: int
    avisos: list[str]
    ignorados: list[dict]
    qtd_revisoes: int
    # Contabilidade HONESTA (a sync decide o status por ela): alunos cujo dado
    # mudou de fato (retrato novo com outro valor, leitura/evento novo), linhas
    # recebidas, linhas que foram para a fila de revisão e linhas que não viraram
    # dado, por motivo ('sem_vinculo', 'campos_ausentes', 'identidade_aposentada'
    # — esta é decisão da escola, não pendência nem defeito). ``avisos_criticos``
    # são códigos estáveis sem PII (ex.: 'campos_ausentes:atividades').
    alunos_aplicados_ids: list[int] = field(default_factory=list)
    linhas_recebidas: int = 0
    linhas_em_revisao: int = 0
    linhas_descartadas: dict = field(default_factory=dict)
    avisos_criticos: list[str] = field(default_factory=list)
    # Contas DISTINTAS (por nome normalizado) que foram para a revisão — uma
    # criança sem ficha com 5 livros é 1 conta e 5 linhas.
    contas_em_revisao: int = 0
    # Ids externos que já são efetivos em OUTRA escola (revisão própria).
    ids_de_outra_escola: list[str] = field(default_factory=list)
    # Pendências 'criacao_bloqueada_por_politica' (ficha nova barrada pela política).
    criacao_bloqueada: int = 0


# Campos SEM os quais uma linha da SINCRONIZAÇÃO não vira retrato: o retrato
# herdaria o valor anterior com a data de hoje ("congela com data nova" — o caso
# de um campo renomeado na API). Na importação manual nada muda: os relatórios se
# COMPLEMENTAM (o Excel do Matific não tem estrelas) e há prévia com um humano.
# Só os campos-título de cada plataforma: tempo e questões do Elefante podem
# faltar (a API e os relatórios antigos nem sempre os mandam) e seguem herdados.
CAMPOS_ESSENCIAIS_SYNC: dict[tuple[str, str], tuple[str, ...]] = {
    ("matific", "resumo"): ("atividades", "estrelas"),
    ("elefante", "resumo"): ("livros_unicos",),
}


def campos_essenciais_ausentes(plataforma: str, formato: str, linhas) -> tuple[list, list[str]]:
    """(linhas com todos os campos essenciais, campos ausentes em alguma linha)."""
    exigidos = CAMPOS_ESSENCIAIS_SYNC.get((plataforma or "", formato or ""))
    if not exigidos:
        return list(linhas), []
    validas, ausentes = [], set()
    for linha in linhas:
        dados_linha = getattr(linha, "dados", None) or {}
        faltam = [c for c in exigidos if dados_linha.get(c) is None]
        if faltam:
            ausentes.update(faltam)
        else:
            validas.append(linha)
    return validas, sorted(ausentes)


def _confirmar_sem_commit(
    *,
    dados: ImportacaoConfirm,
    escola_id: int,
    usuario: Usuario,
    db: Session,
    encerrar_revisoes: bool = True,
    da_sincronizacao: bool = False,
    piso_da_data: bool = True,
    sem_retrato_repetido: bool = False,
    questoes_herdadas: bool = False,
) -> _NucleoImportacao:
    """TODO o trabalho do /confirmar, SEM commit e SEM efeito externo.

    É aqui que a importação acontece: identidade, turmas, snapshots, leituras,
    eventos e a fila de revisão. Nada de ``db.commit()`` — quem chama decide
    quando fechar. Assim o ``/resolver`` aplica várias pendências irmãs e fecha
    tudo numa transação única: falhou no meio, nada fica.

    ``encerrar_revisoes``: linha ASSOCIADA encerra a revisão pendente da mesma
    identidade e do mesmo tipo de dado (``_encerrar_revisoes_respondidas``). O
    /resolver passa False — é ele quem fecha as pendências (todas as irmãs, com o
    gestor como autor e o dado congelado aplicado); encerrá-las aqui, no meio da
    reaplicação, deixaria uma segunda auditoria, sem o resultado dele.

    ``da_sincronizacao``: sinal INTERNO (fora do schema público) de que o pedido
    vem da sincronização automática — o /confirmar o liga só para o pedido montado
    pelo orquestrador (``confirmacao_da_sincronizacao``). Dispensa as regras do
    upload MANUAL: a data do relatório (coleta usa o relógio de agora), as regras
    da data informada (``_conferir_data_do_relatorio``) e a recusa do relatório
    retrodatado sem base (a sync grava como antes, com aviso no log).

    ``piso_da_data``: o /resolver passa False — a data da pendência é a que a
    importação original gravou (registro do servidor, não digitada agora): uma
    pendência antiga não fica sem solução porque a escola avançou o ano letivo.

    ``questoes_herdadas`` (só a sincronização, S9): as questões não vieram da
    plataforma nesta execução; a importação nasce com o status
    ``IMPORTACAO_SEM_QUESTOES`` e os retratos dela não medem as questões."""
    inicio = time.monotonic()
    from app.models import Escola

    # O Matific não tem relatório individual: nenhum analisador nem a sincronização
    # produzem essa combinação, e ela ia para ``_importar_matific`` escapando das
    # regras do total acumulado (a recusa sem data olha o formato "resumo").
    if dados.plataforma == "matific" and dados.formato == "leituras":
        raise HTTPException(422, "O Matific não tem relatório individual de leituras.")
    escola = db.get(Escola, escola_id)
    if escola is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Escola não encontrada.")
    if not dados.linhas:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nenhuma linha para importar.")
    agora_utc = _agora_utc()
    # DATA DO RELATÓRIO (upload manual): no futuro, o retrato viraria o "atual" até
    # lá, por cima de toda coleta; de 1990 (ou do ano 1, que estourava em 500),
    # viraria a base de toda janela. A tela limita o campo ao mesmo intervalo.
    data_informada = dados.data_referencia
    if not da_sincronizacao:
        if data_informada is not None:
            data_informada = _conferir_data_do_relatorio(data_informada, escola, agora_utc,
                                                         com_piso=piso_da_data)
        _conferir_periodo_do_relatorio(dados, escola, agora_utc, com_piso=piso_da_data)

    # Serializa importações concorrentes desta escola. A trava (Postgres; no-op
    # em SQLite) garante que o 2º envio sobreposto leia o que o 1º commitou;
    # combinada com o re-casamento contra o banco — turma via índice único +
    # _inserir_turma, aluno via _aluno_existente_na_turma — um double-click/retry
    # do MESMO relatório reaproveita em vez de duplicar turmas/alunos.
    bloquear_escola_para_importacao(db, escola_id)

    data_referencia = data_informada or agora_utc.replace(tzinfo=timezone.utc)
    avisos: list[str] = []
    # SYNC: linha sem campo ESSENCIAL não vira retrato herdado com data nova
    # (``CAMPOS_ESSENCIAIS_SYNC``). A identidade dela é resolvida como sempre (o
    # vínculo/a revisão valem), mas nenhum dado é gravado: fica contada, com
    # aviso crítico. Na importação manual nada muda.
    exigidos = (CAMPOS_ESSENCIAIS_SYNC.get((dados.plataforma, dados.formato))
                if getattr(dados, "sincronizar_turma", False) else None)
    ausentes_sync: set[str] = set()
    linhas_descartadas: dict[str, int] = {}
    # O que a fila de revisão guarda para reaplicar a linha depois (mesmo pipeline).
    contexto_revisao = {
        "tipo": dados.tipo,
        "data_referencia": data_referencia.isoformat(),
        # A data veio do relatório (ou da sincronização)? Sem ela, a acima é o
        # relógio de agora — ver ``_linha_substitui_o_congelado``.
        "data_informada": dados.data_referencia is not None,
        "periodo_inicio": dados.periodo_inicio.isoformat() if dados.periodo_inicio else "",
        "periodo_fim": dados.periodo_fim.isoformat() if dados.periodo_fim else "",
    }

    # Intervalo do relatório (Matific "Intervalo de datas"): o fim impresso é
    # o limite EXCLUSIVO do leaderboard — o snapshot é datado na véspera
    # (23:59:59), caindo dentro do mês/semana a que os dados pertencem.
    periodo_inicio = periodo_fim = None
    periodo_em_andamento = False
    if (dados.plataforma == "matific"
            and dados.periodo_inicio is not None and dados.periodo_fim is not None):
        periodo_inicio = dados.periodo_inicio.replace(tzinfo=None)
        periodo_fim = dados.periodo_fim.replace(tzinfo=None)
        if periodo_fim.time() == hora_zero(0, 0):
            periodo_fim -= timedelta(seconds=1)
        # Período EM ANDAMENTO (relatório do mês corrente): o snapshot é
        # datado agora, nunca no futuro — uma data futura ficaria acima de
        # qualquer edição manual feita depois, escondendo-a dos rankings.
        agora_ref = agora_utc
        if periodo_fim > agora_ref:
            periodo_fim = agora_ref
            periodo_em_andamento = True
        if periodo_fim <= periodo_inicio:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Intervalo de datas do relatório inválido.")
        data_referencia = periodo_fim

    # Move o arquivo original de /temporarios para a pasta definitiva (§15).
    # arquivo_token e arquivo_nome vêm do cliente: ambos são saneados contra
    # path traversal antes de tocar o disco (nunca escapar de UPLOADS_DIR). O
    # caminho é validado AQUI, mas o arquivo só é movido depois das recusas da
    # importação (``mover_original``): recusada, o original fica em /temporarios e
    # o mesmo token serve para confirmar de novo (ex.: com a data do relatório).
    arquivo_final = None
    mover_original: tuple[Path, Path] | None = None
    if dados.arquivo_token:
        if not _TOKEN_VALIDO.match(dados.arquivo_token):
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Token de arquivo inválido.")
        base_uploads = settings.UPLOADS_DIR.resolve()
        pasta_temp = (base_uploads / "temporarios").resolve()
        origem = (pasta_temp / dados.arquivo_token).resolve()
        # A origem precisa estar contida em /temporarios (bloqueia mover/apagar
        # arquivo sensível de fora via token forjado).
        if not origem.is_relative_to(pasta_temp):
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Token de arquivo inválido.")
        if origem.exists():
            # Deriva um nome seguro só do basename do nome enviado.
            base_nome = Path(dados.arquivo_nome or "").name
            if not base_nome or not base_nome.lower().endswith((".pdf", ".xlsx")):
                base_nome = dados.arquivo_token
            nome = f"{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_{base_nome}"
            destino = (base_uploads / dados.plataforma / nome).resolve()
            if not destino.is_relative_to(base_uploads):
                raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                    "Nome de arquivo inválido.")
            mover_original = (origem, destino)
            arquivo_final = f"uploads/{dados.plataforma}/{nome}"

    importacao = Importacao(
        escola_id=escola_id, usuario_id=usuario.id,
        plataforma=dados.plataforma, tipo=dados.tipo,
        arquivo_original=arquivo_final or dados.arquivo_nome,
        status=IMPORTACAO_SEM_QUESTOES if questoes_herdadas else "concluida",
    )
    db.add(importacao)
    db.flush()

    # Agrupa por aluno resolvido; no formato "leituras" um aluno tem várias linhas
    resolvidos: dict[int, tuple[Aluno, list]] = {}
    criados: dict[tuple[str, int], Aluno] = {}  # dedup de alunos criados
    turmas_novas: dict = {}                     # turma criada pelo nome: 1x só
    ignorados: list[str] = []                   # linhas SEM aluno (nunca silêncio)
    # PORTA ÚNICA de identidade: estado da escola lido UMA vez (e mantido vivo a
    # cada aluno criado/identidade gravada) e a fila de revisão desta importação.
    ctx_identidade = ida.carregar_contexto(db, escola_id, escola.ano_letivo_ativo)
    # Id externo repetido NESTE relatório com nomes diferentes: nenhuma das linhas
    # aplica número (revisão "id_externo_duplicado") — a mesma marca da prévia.
    ida.marcar_ids_em_conflito(ctx_identidade, dados.linhas, dados.plataforma)
    # Conta já EFETIVA em OUTRA escola do Constela: nenhuma linha dela aplica
    # número aqui (revisão "identidade_de_outra_escola") — a mesma marca da prévia.
    ida.marcar_ids_de_outra_escola(db, ctx_identidade, dados.linhas, dados.plataforma)
    # D10: só o Admin Global fixa a ficha de uma conta dessas na confirmação (com
    # aviso e auditoria em ``_resolver_aluno``); a escolha da gestão da escola vai
    # para a revisão, como no /resolver.
    ctx_identidade.confirma_conta_de_outra_escola = bool(getattr(usuario, "is_global", False))
    # Duas contas AINDA SEM VÍNCULO que levariam a MESMA ficha neste relatório:
    # nenhuma leva (revisão para as duas), em vez de a primeira linha do arquivo
    # vencer — a mesma marca da prévia, depois das duas acima.
    idents_da_importacao = []
    for linha in dados.linhas:
        ident, _turma, invalida = _identidade_da_linha(db, escola_id, linha, dados.plataforma)
        if not invalida and (linha.aluno_id is not None or svc.tokens_nome(linha.nome)):
            idents_da_importacao.append(ident)
    ida.marcar_fichas_disputadas(ctx_identidade, idents_da_importacao)
    coletor = ida.ColetorRevisoes(
        formato=dados.formato, contexto=contexto_revisao,
        origem="sincronizacao" if getattr(dados, "sincronizar_turma", False) else "importacao",
        importacao_id=importacao.id)
    linhas_em_revisao = 0
    contas_em_revisao: set[str] = set()   # contas DISTINTAS (uma criança, N livros)
    # POLÍTICA DE MATRÍCULA (``services/politica_sync``, decisão D5): vale para o
    # upload manual de relatório de plataforma e para a sincronização. Com
    # 'bloquear' (a matrícula vem da Lista Piloto) a importação NÃO cria ficha —
    # a linha sem candidato seguro vai para a revisão
    # 'criacao_bloqueada_por_politica'. O corpo só pode RESTRINGIR (False); um
    # True explícito não fura a política, que é do Admin Global. E turma nova só
    # nasce para receber ficha nova: sem ficha, nada de turma vazia pelo nome do
    # relatório (a linha fica 'turma_nao_cadastrada', como na sincronização).
    pode_criar_aluno = (politica_sync.pode_criar_aluno(db, escola_id)
                        and getattr(dados, "permitir_criar_aluno", None) is not False)
    pode_criar_turma = bool(getattr(dados, "permitir_criar_turma", True)) and pode_criar_aluno
    for linha in dados.linhas:
        faltam = [c for c in exigidos or () if (linha.dados or {}).get(c) is None]
        if faltam:
            # Linha sem campo ESSENCIAL não vira dado: a identidade dela só vale
            # para quem JÁ tem ficha (vínculo da conta). Nada nasce dela — nem
            # ficha, nem matrícula, nem pendência que um dia reaplicaria um número
            # que não veio (antes nascia a ficha, sem dado e sem recálculo). A
            # revisão que ela tentaria abrir vai para um coletor descartado.
            _resolver_aluno(db, escola_id, escola.ano_letivo_ativo, linha,
                            [], criados, turmas_novas,   # avisos de pendência: descartados
                            permitir_criar_turma=False, permitir_criar_aluno=False,
                            plataforma=dados.plataforma, ctx=ctx_identidade,
                            revisoes=ida.ColetorRevisoes(
                                formato=dados.formato, contexto=contexto_revisao,
                                origem="sincronizacao", importacao_id=importacao.id),
                            usuario_id=usuario.id, encerrar_revisoes=False)
            ausentes_sync.update(faltam)
            linhas_descartadas["campos_ausentes"] = linhas_descartadas.get("campos_ausentes", 0) + 1
            continue
        na_fila = sum(len(p.linhas) for p in coletor.pendencias.values())
        decididas = sum(linhas_descartadas.get(m, 0) for m in ida.MOTIVOS_DESCARTE_DECIDIDO)
        aluno = _resolver_aluno(db, escola_id, escola.ano_letivo_ativo, linha,
                                avisos, criados, turmas_novas,
                                permitir_criar_turma=pode_criar_turma,
                                permitir_criar_aluno=pode_criar_aluno,
                                plataforma=dados.plataforma, ctx=ctx_identidade,
                                revisoes=coletor, usuario_id=usuario.id,
                                encerrar_revisoes=encerrar_revisoes,
                                descartes=linhas_descartadas)
        if aluno is None:
            if sum(linhas_descartadas.get(m, 0)
                   for m in ida.MOTIVOS_DESCARTE_DECIDIDO) > decididas:
                # A ESCOLA já decidiu (conta aposentada): descarte com motivo
                # próprio, já contado. Fora de ``ignorados`` — o nome da conta
                # aposentada é o da criança, e a sync desfazia o cursor DELA a
                # cada coleta — e fora de 'sem_vinculo' (pendência permanente que
                # nunca deixava a integração chegar a "nada mudou").
                continue
            chave_ign = svc.chave_nome(linha.nome)
            if chave_ign not in ignorados:
                ignorados.append(chave_ign)
            # Foi para a fila de revisão (linha preservada) ou ficou sem vínculo?
            if sum(len(p.linhas) for p in coletor.pendencias.values()) > na_fila:
                linhas_em_revisao += 1
                contas_em_revisao.add(chave_ign)
            else:
                linhas_descartadas["sem_vinculo"] = linhas_descartadas.get("sem_vinculo", 0) + 1
            continue
        resolvidos.setdefault(aluno.id, (aluno, []))[1].append(linha)
    revisoes_gravadas = _gravar_revisoes(db, escola_id, coletor, usuario.id)
    ids_de_outra_escola = sorted({p.id_externo for p in coletor.pendencias.values()
                                  if p.motivo == "identidade_de_outra_escola"
                                  and p.id_externo})
    # Alunos (pendências distintas) que virariam ficha nova e a política barrou.
    criacao_bloqueada = sum(1 for p in coletor.pendencias.values()
                            if p.motivo == "criacao_bloqueada_por_politica")
    avisos_criticos: list[str] = []
    if ausentes_sync:
        avisos_criticos.append("campos_ausentes:" + ",".join(sorted(ausentes_sync)))
        avisos.append(
            f"{linhas_descartadas['campos_ausentes']} linha(s) sem "
            f"{', '.join(sorted(ausentes_sync))} na resposta da plataforma — dado não "
            "gravado (o valor anterior não é repetido com a data de hoje).")

    # MUDANÇA AUTOMÁTICA DE TURMA (só na sync automática do Matific): vincula o
    # UUID e move a matrícula de quem trocou de sala — só com a política
    # 'permitir'; com 'bloquear' a matrícula segue a Lista Piloto e a turma
    # divergente vira aviso (P15). Antes do recálculo para o ranking já refletir a
    # turma nova.
    movidos_ids: list[int] = []
    if getattr(dados, "sincronizar_turma", False) and dados.plataforma == "matific" \
            and resolvidos:
        _sincronizar_turma_matific(
            db, escola_id, escola.ano_letivo_ativo, resolvidos, avisos,
            ctx=ctx_identidade, movidos_ids=movidos_ids)

    # Import por período: as séries de snapshots dos alunos envolvidos vêm
    # numa ÚNICA consulta (212 alunos = 1 ida ao banco, não 212).
    series: dict[int, list] = {}
    contadores = {"reimportados": 0, "historico": 0, "preservados": 0}
    if periodo_inicio is not None and resolvidos:
        for snap in db.execute(
            select(SnapshotMatific)
            .where(SnapshotMatific.escola_id == escola_id,
                   SnapshotMatific.aluno_id.in_(list(resolvidos)))
            .order_by(SnapshotMatific.data_referencia, SnapshotMatific.id)
        ).scalars():
            series.setdefault(snap.aluno_id, []).append(snap)

    # Snapshot ANTERIOR de cada aluno numa ÚNICA consulta (o caminho por período
    # já fazia isso com `series`; aqui cobrimos o comum matific/elefante-resumo,
    # que antes chamava _snapshot_atual 1x por aluno = N+1). None em `.get` já é
    # o valor certo (aluno sem snapshot anterior). Retrato datado no futuro (legado)
    # não conta como o atual (``_teto_retrato_valido``), na sync e no upload manual.
    teto_retrato = _teto_retrato_valido(agora_utc)
    anteriores: dict = {}
    if resolvidos:
        if dados.plataforma == "matific" and periodo_inicio is None:
            anteriores = _mapa_snapshot_atual(db, escola_id, resolvidos.keys(), SnapshotMatific,
                                              ate=teto_retrato)
        elif dados.plataforma != "matific" and dados.formato != "leituras":
            anteriores = _mapa_snapshot_atual(db, escola_id, resolvidos.keys(), SnapshotElefante,
                                              ate=teto_retrato)

    # UPLOAD MANUAL SEM A DATA DO RELATÓRIO, no total acumulado: a data seria só o
    # relógio de agora e o relatório pode ser antigo. Se o retrato atual de algum
    # aluno veio da SINCRONIZAÇÃO, gravar viraria "o dado de hoje" por cima de um
    # dado coletado (talvez mais novo) — ou o sobrescreveria no lugar, se for do
    # mesmo dia. Recusa ANTES de gravar qualquer retrato, pedindo a data. Entre
    # uploads manuais (o Excel complementando o PDF no mesmo dia) nada muda. A
    # sincronização (``da_sincronizacao``, sinal do servidor — nunca o campo
    # ``sincronizar_turma`` do corpo, que qualquer cliente da API manda), o
    # relatório por período (que traz as próprias datas) e o relatório individual
    # (leituras, que só somam) seguem.
    # "Veio da sincronização" tem duas provas: a importação do retrato (registrada
    # na execução, ou criada na janela dela) e — porque um upload COM data do mesmo
    # dia complementa o retrato no lugar e apaga a primeira — uma execução da sync
    # iniciada no dia do retrato atual, ou depois (``_alunos_com_sincronizacao_desde_o_retrato``).
    if (dados.data_referencia is None and not da_sincronizacao and periodo_inicio is None
            and (dados.formato == "resumo" or dados.plataforma == "matific") and anteriores):
        da_sync = _importacoes_da_sincronizacao(
            db, escola_id, dados.plataforma,
            {snap.importacao_id for snap in anteriores.values() if snap is not None})
        cobertos = {aid for aid, snap in anteriores.items()
                    if snap is not None and snap.importacao_id in da_sync}
        cobertos |= _alunos_com_sincronizacao_desde_o_retrato(
            db, escola_id, dados.plataforma, anteriores)
        if cobertos:
            raise HTTPException(
                422,
                "Informe a data do relatório para importar este arquivo. "
                f"{len(cobertos)} aluno(s) têm dados trazidos pela sincronização automática "
                "ou anteriores à última sincronização; sem a data em que o relatório foi "
                "gerado na plataforma, um arquivo antigo passaria por dado de hoje e "
                "apagaria o que foi coletado. Nada foi gravado.")

    # RELATÓRIO RETRODATADO: de um dia (de Brasília) anterior ao retrato atual do
    # aluno — com a data do relatório, que a tela agora exige, é o caso normal de um
    # arquivo antigo. O que ele NÃO traz (o Excel por turma do Matific não tem
    # estrelas; o relatório da turma do Elefante não tem os livros por nível) vem
    # do retrato que VALIA naquela data — o do mesmo dia, complementado no lugar,
    # ou o último antes dela —, NUNCA do mais novo: as estrelas de outubro iam
    # parar num ponto de agosto, e a evolução, os rankings e as premiações de
    # setembro (base = último retrato antes do início, ``evolucao._janela``)
    # ficavam errados para sempre. Sem retrato naquela data nem antes, não há de
    # onde herdar com segurança (zero também falsearia o ganho dos períodos
    # seguintes): recusa ANTES de gravar e de mover o original. Relatório do mesmo
    # dia do retrato atual, ou mais novo: o de sempre (herda do atual).
    # Na SINCRONIZAÇÃO a coleta é de agora: só fica "retrodatada" diante de um
    # retrato válido (até ``teto_retrato``) do dia seguinte de Brasília — e, sem
    # base, NÃO recusa a escola: grava como antes (herda do retrato mais novo
    # válido), com aviso no log. Recusar parava a coleta da escola todo dia, com
    # o diagnóstico errado ("relatório mais antigo… confira a data informada").
    base_retrato = dict(anteriores)
    retro = {aid for aid, snap in anteriores.items() if _retrodatado(snap, data_referencia)}
    if retro:
        modelo_retrato = SnapshotMatific if dados.plataforma == "matific" else SnapshotElefante
        na_data = _mapa_retrato_na_data(db, escola_id, retro, modelo_retrato, data_referencia,
                                        ate=teto_retrato)
        sem_base: set[int] = set()
        campos_sem_base: set[str] = set()
        for aid in retro:
            base = na_data.get(aid)
            faltam = ([] if base is not None
                      else _campos_herdados(dados.plataforma, resolvidos[aid][1][-1].dados or {}))
            if faltam:
                # Fica com o retrato mais novo válido como base: só a sync segue.
                sem_base.add(aid)
                campos_sem_base.update(faltam)
            else:
                base_retrato[aid] = base
        if sem_base and da_sincronizacao:
            # Sem nome de aluno no log: só contagem e campos.
            logger_sync.warning(
                "Sincronização da escola %s (%s): %d aluno(s) com retrato mais novo que "
                "a coleta e sem retrato anterior de onde completar %s; gravado como "
                "antes (herdando do retrato mais novo válido), sem recusar a escola.",
                escola_id, dados.plataforma, len(sem_base),
                ", ".join(sorted(campos_sem_base)))
        elif sem_base:
            rotulos = ", ".join(rotulo for campo, rotulo in _ROTULO_CAMPO_RETRATO.items()
                                if campo in campos_sem_base)
            if dados.data_referencia is None:
                # Sem data no pedido (só pela API): o relatório seria datado de agora.
                raise HTTPException(
                    422,
                    "Informe a data do relatório para importar este arquivo. Sem ela, "
                    f"ele seria gravado como de hoje ({_dia_txt(para_br(data_referencia).date())}), "
                    f"mas {len(sem_base)} aluno(s) já têm dados com data posterior e o "
                    f"arquivo não traz: {rotulos}. Nada foi gravado.")
            raise HTTPException(
                422,
                f"O relatório de {_dia_txt(para_br(data_referencia).date())} é mais antigo "
                f"que os dados que {len(sem_base)} aluno(s) já têm e não traz: {rotulos}. "
                "Esses alunos não têm retrato nessa data (nem antes) de onde completar o "
                "que falta, e usar os números mais novos poria dados de outra época no "
                "histórico (evolução, rankings e premiações). Para registrar este "
                "relatório, importe antes, com a mesma data, um relatório que traga esses "
                "dados, ou confira a data informada. Nada foi gravado.")

    if mover_original is not None:
        origem, destino = mover_original
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(origem), str(destino))

    # PERFORMANCE das leituras (Elefante): catálogo de livros, faixas de nível e
    # "já lidos" carregados UMA vez para o arquivo inteiro — antes eram relidos
    # por aluno (~190× numa escola de 10 turmas), o gargalo da sync de ~15 min.
    cat_livros = cod_faixa = ja_lidos_map = None
    if dados.formato == "leituras" and resolvidos:
        cat_livros = _catalogo_livros(db, escola_id)
        cod_faixa = _codigos_faixa_escola(db, escola_id)
        ja_lidos_map = _ja_lidos_por_aluno(db, [a.id for a, _ in resolvidos.values()])

    aplicados: list[int] = []        # alunos cujo dado MUDOU nesta importação
    for aluno, linhas_aluno in resolvidos.values():
        if dados.plataforma == "matific" and periodo_inicio is not None:
            mudou = _importar_matific_periodo(db, escola_id, importacao, aluno,
                                              linhas_aluno[-1].dados,
                                              periodo_inicio, periodo_fim,
                                              series.get(aluno.id, []), contadores,
                                              em_andamento=periodo_em_andamento)
        elif dados.plataforma == "matific":
            mudou = _importar_matific(db, escola_id, importacao, aluno,
                                      linhas_aluno[-1].dados, data_referencia,
                                      anterior=base_retrato.get(aluno.id))
        elif dados.formato == "leituras":
            mudou = _importar_elefante_leituras(db, escola_id, importacao, aluno,
                                                linhas_aluno, data_referencia, avisos,
                                                cat_livros, ja_lidos_map.get(aluno.id, set()),
                                                cod_faixa,
                                                sem_retrato_repetido=sem_retrato_repetido)
        else:
            mudou = _importar_elefante_resumo(db, escola_id, importacao, aluno,
                                              linhas_aluno[-1].dados, data_referencia,
                                              anterior=base_retrato.get(aluno.id),
                                              avisos=avisos,
                                              sem_retrato_repetido=sem_retrato_repetido)
        if mudou:
            aplicados.append(aluno.id)
    # Matrícula movida pela sync também é dado alterado (turma do ranking,
    # posição): sem isto, a troca de turma sem número novo terminava "nada mudou"
    # e as notas ficavam com a turma antiga até a próxima mudança de número.
    aplicados.extend(i for i in movidos_ids if i not in aplicados)

    if cat_livros is not None:
        # Auditoria agregada dos vínculos à identidade oficial (1 linha por import).
        cat_livros.finalizar(db, importacao, avisos)

    if contadores["reimportados"]:
        avisos.append(
            f"{contadores['reimportados']} aluno(s) já tinham dados datados "
            "dentro deste intervalo — os valores do período foram "
            "recalculados sem somar duas vezes.")
    if contadores["preservados"]:
        avisos.append(
            f"{contadores['preservados']} aluno(s) tinham um total acumulado "
            "MAIOR que a soma dos períodos importados — o total atual foi "
            "preservado (a diferença fica atribuída a antes dos períodos).")
    if contadores["historico"]:
        avisos.append(
            f"{contadores['historico']} aluno(s) já têm dados mais recentes "
            "que este intervalo — o mês entrou no histórico (evolução e "
            "premiações). Para o TOTAL acumulado incorporá-lo, reimporte os "
            "meses seguintes em ordem.")

    importacao.qtd_alunos = len(resolvidos)
    importacao.qtd_erros = len(dados.linhas) - sum(len(l) for _, l in resolvidos.values())
    importacao.tempo_ms = int((time.monotonic() - inicio) * 1000)

    # LGPD/§15: o log de auditoria é permanente — não persistir os avisos brutos,
    # que podem citar nomes de alunos. Guardamos só a CONTAGEM (os avisos
    # completos seguem na resposta HTTP para quem confirmou a importação).
    registrar(db, "importacao.concluida", escola_id=escola_id, usuario_id=usuario.id,
              entidade="importacao", entidade_id=importacao.id,
              detalhes={"plataforma": dados.plataforma, "tipo": dados.tipo,
                        "alunos": importacao.qtd_alunos, "qtd_avisos": len(avisos)})
    # `importacao.id` já existe: veio do flush lá de cima, não do commit.
    db.flush()
    return _NucleoImportacao(
        importacao_id=importacao.id,
        qtd_alunos=importacao.qtd_alunos,
        qtd_erros=importacao.qtd_erros,
        avisos=avisos,
        ignorados=ignorados,
        qtd_revisoes=len(revisoes_gravadas),
        alunos_aplicados_ids=aplicados,
        linhas_recebidas=len(dados.linhas),
        linhas_em_revisao=linhas_em_revisao,
        linhas_descartadas=linhas_descartadas,
        avisos_criticos=avisos_criticos,
        contas_em_revisao=len(contas_em_revisao),
        ids_de_outra_escola=ids_de_outra_escola,
        criacao_bloqueada=criacao_bloqueada,
    )


@router.post("/recalcular", response_model=dict)
def recalcular_agora(
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Recalcula notas/rankings da escola uma única vez — usado ao final de
    uma importação em lote, depois de vários /confirmar com recalcular=false."""
    n = _finalizar_importacao(
        db, escola_id,
        corpo="Importação em lote concluída. As notas já foram recalculadas.")
    return {"mensagem": f"Notas recalculadas para {n} aluno(s).", "alunos": n}


# --- Planilha de matrículas da escola ("Lista Piloto") -----------------------

async def _ler_planilha_matriculas(request: Request, arquivo: UploadFile) -> tuple[bytes, str]:
    declarado = request.headers.get("content-length")
    if declarado and declarado.isdigit() and int(declarado) > TAMANHO_MAXIMO + 1_000_000:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Arquivo acima de 10 MB.")
    conteudo = await arquivo.read()
    if len(conteudo) > TAMANHO_MAXIMO:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Arquivo acima de 10 MB.")
    nome = arquivo.filename or "matriculas"
    ehxls = conteudo[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # OLE2 (.xls)
    ehzip = conteudo[:2] == b"PK"                                # .xlsx (zip)
    if not (ehxls or ehzip or nome.lower().endswith((".xls", ".xlsx", ".xlsm"))):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Envie a planilha de matrículas em Excel (.xls ou .xlsx).")
    if not ehxls:
        # Teto do DESCOMPRIMIDO antes do openpyxl. Aqui, e não só no serviço: lá a
        # falha de leitura vira aviso com 200; a planilha inflada merece a recusa.
        try:
            await run_in_threadpool(planilhas.exigir_xlsx_contido, conteudo)
        except planilhas.PlanilhaRecusada as exc:
            raise HTTPException(exc.status_http, str(exc)) from exc
    return conteudo, nome


async def _analisar_lista_piloto(conteudo: bytes, nome: str):
    """A análise do serviço. A planilha que estoura o orçamento de leitura (linhas
    e células percorridas, ``planilhas.OrcamentoLeitura``) também é recusada com a
    mensagem (413), e não vira aviso com 200."""
    try:
        return await run_in_threadpool(lista_piloto.analisar_matriculas, conteudo, nome)
    except planilhas.PlanilhaRecusada as exc:
        raise HTTPException(exc.status_http, str(exc)) from exc


# Os helpers puros de nome/turma migraram para services/matriculas.py (testáveis
# isoladamente e reutilizados pela análise e pela confirmação). Aliases locais:
_norm = svc.chave_nome
_chave_turma = matriculas.chave_turma


@router.post("/matriculas/analisar", response_model=MatriculasAnaliseOut)
async def analisar_matriculas(
    request: Request,
    escola_id: int = Depends(escola_autorizada),
    arquivo: UploadFile = File(...),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Prévia da planilha de matrículas: turmas e alunos detectados, com quais
    turmas já existem — nada é gravado."""
    conteudo, nome = await _ler_planilha_matriculas(request, arquivo)
    analise = await _analisar_lista_piloto(conteudo, nome)
    escola = db.get(Escola, escola_id)
    if escola is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Escola não encontrada.")
    ano = escola.ano_letivo_ativo
    cadastradas = db.execute(
        select(Turma).where(Turma.escola_id == escola_id, Turma.ano_letivo == ano)
    ).scalars().all()
    existentes = {_chave_turma(t.nome) for t in cadastradas}
    # Chaves cuja ÚNICA turma cadastrada está arquivada: a confirmação não aplica
    # as linhas delas (``_persistir_linhas``) — a prévia já avisa.
    so_arquivadas = existentes - {_chave_turma(t.nome) for t in cadastradas
                                  if ida.turma_ativa(t)}
    avisos_arquivadas = [
        matriculas.aviso_turma_arquivada(
            next(c.nome for c in cadastradas if _chave_turma(c.nome) == _chave_turma(t.nome)),
            len(t.alunos), previa=True)
        for t in analise.turmas if _chave_turma(t.nome) in so_arquivadas]
    # Turma NOVA que não cabe nas colunas: a prévia avisa o mesmo que a
    # confirmação fará (``_resolver_turmas``) e mostra a série como será gravada.
    avisos_colunas: list[str] = []
    turmas: list[MatriculaTurmaOut] = []
    criaveis: set[str] = set()
    for t in analise.turmas:
        chave = _chave_turma(t.nome)
        serie = t.ano_escolar
        if chave not in existentes and chave not in criaveis:
            conferida, avisos_turma = lista_piloto.conferir_turma_nova(t, previa=True)
            avisos_colunas.extend(avisos_turma)
            if conferida is not None:
                serie = conferida
                criaveis.add(chave)
        turmas.append(MatriculaTurmaOut(
            nome=t.nome, ano_escolar=serie, turno=t.turno,
            professor=t.professor, sed=t.sed, total_alunos=len(t.alunos),
            ja_existe=chave in existentes,
            exemplos=[a.nome for a in t.alunos[:4]],
        ))
    # Alunos DISTINTOS (o que será realmente cadastrado): o mesmo aluno pode
    # aparecer em duas turmas; conta uma vez (por RA válido, senão nome+turma).
    identidades: set = set()
    for t in analise.turmas:
        for a in t.alunos:
            ra = lista_piloto.ra_util(a.ficha.get("ra"))
            identidades.add(ra or (_norm(a.nome), _chave_turma(t.nome)))

    # Resumo novos × atualizar (casamento LEVE, só para a prévia — a confirmação
    # usa o casamento completo em services/matriculas). Existe por RA, senão por
    # (nome normalizado, turma) do ano ativo.
    ras_existentes: set[str] = set()
    nome_turma_existentes: set = set()
    for aluno, turma_nome in db.execute(
        select(Aluno, Turma.nome)
        .join(Matricula, Matricula.aluno_id == Aluno.id)
        .join(Turma, Turma.id == Matricula.turma_id)
        .where(Aluno.escola_id == escola_id, Matricula.ano_letivo == ano)
    ):
        ra = lista_piloto.ra_util((aluno.ficha or {}).get("ra"))
        if ra:
            ras_existentes.add(ra)
        nome_turma_existentes.add((_norm(aluno.nome), _chave_turma(turma_nome)))
    def _ja_cadastrado(ident) -> bool:
        if isinstance(ident, str):
            return ident in ras_existentes
        return ident in nome_turma_existentes
    atualizar = sum(1 for ident in identidades if _ja_cadastrado(ident))

    return MatriculasAnaliseOut(
        escola_detectada=analise.escola_detectada, ano_letivo=analise.ano_letivo,
        total_turmas=len(turmas), total_alunos=len(identidades),
        total_registros=analise.total_alunos,
        alunos_novos=len(identidades) - atualizar, alunos_atualizar=atualizar,
        turmas_existentes=sum(1 for t in turmas if t.ja_existe),
        turmas=turmas,
        avisos=list(analise.avisos) + avisos_colunas + avisos_arquivadas,
    )


# --- Importação da planilha de matrículas (Lista Piloto) --------------------
# O CASAMENTO (puro) vive em services/matriculas.py; aqui ficam só as etapas
# com efeito colateral: carregar o estado, criar turmas e persistir.

@dataclass
class _EstadoEscola:
    """Estado atual da escola pré-carregado (poucas consultas, tudo em memória)."""
    alunos_por_id: dict[int, Aluno]                # ORM — usado na persistência
    matricula_ano: dict[int, Matricula | None]
    ctx: matriculas.ContextoCasamento              # índices do MOTOR ÚNICO

    def registrar(self, aluno: Aluno, chave_sala: str | None = None) -> None:
        """Reflete no índice do motor o aluno recém-criado/alterado — as linhas
        SEGUINTES do mesmo arquivo passam a enxergá-lo."""
        self.alunos_por_id[aluno.id] = aluno
        self.ctx.registrar(_identidade_do_aluno(aluno), chave_sala)


def _carregar_estado(db: Session, escola_id: int, ano: int) -> _EstadoEscola:
    """Lê o estado da escola e monta os índices de IDENTIDADE (impuro: só DB).

    São três índices, e nenhum deles é um "motor" próprio — todos alimentam o
    ``matching`` (ver ``matriculas.resolver_linha``):
      * RA → aluno, escola inteira, INCLUSIVE excluído (RA é identificador forte:
        reativa em vez de duplicar);
      * roster por SALA (chave série+letra, ano ativo) — o roster que o motor
        recebe, idêntico ao dos imports de plataforma. Indexar por chave de SALA
        (e não por ``turma_id``) faz o aluno criado pelo Matific numa linha de
        turma paralela ("1 ANO A MANHA (300…)") ser candidato da linha da Lista
        Piloto ("1ºA") — era por aí que a duplicata entrava;
      * nome → alunos da escola, para reconhecer MUDANÇA DE SALA.
    """
    # order_by garante escolha determinística de por_ra quando há RA repetido.
    alunos_todos = db.execute(
        select(Aluno).where(Aluno.escola_id == escola_id)
        .order_by(Aluno.id)).scalars().all()
    alunos_por_id = {a.id: a for a in alunos_todos}

    matricula_ano: dict[int, Matricula | None] = {
        m.aluno_id: m for m in db.execute(
            select(Matricula).where(Matricula.escola_id == escola_id,
                                    Matricula.ano_letivo == ano)).scalars()
    }
    chave_da_turma: dict[int, str] = {
        t.id: _chave_turma(t.nome) for t in db.execute(
            select(Turma).where(Turma.escola_id == escola_id)).scalars()
    }
    # Sala ATUAL de cada aluno: a do ano ativo; quem não tem matrícula no ano
    # herda a da matrícula mais recente (aluno de anos anteriores sendo
    # rematriculado na MESMA sala continua sendo a mesma pessoa).
    sala_de: dict[int, str] = {}
    for aid, tid, _ano_m in db.execute(
        select(Matricula.aluno_id, Matricula.turma_id, Matricula.ano_letivo)
        .where(Matricula.escola_id == escola_id)
        .order_by(Matricula.ano_letivo)).all():
        sala_de[aid] = chave_da_turma.get(tid, "")
    for aid, m in matricula_ano.items():
        if m is not None:
            sala_de[aid] = chave_da_turma.get(m.turma_id, "")

    ctx = matriculas.ContextoCasamento()
    for a in alunos_todos:
        ident = _identidade_do_aluno(a)
        if a.status == "excluido":
            ctx.registrar_ra(ident)     # só o RA identifica um excluído
            continue
        ctx.registrar(ident, sala_de.get(a.id))
    return _EstadoEscola(alunos_por_id, matricula_ano, ctx)


def _resolver_turmas(db: Session, escola_id: int, ano: int, turmas_analise,
                     avisos: list[str] | None = None,
                     ) -> tuple[list[Turma | None], int, int]:
    """Cria as turmas que faltam (chave insensível a º/acento/caixa) e devolve,
    na ordem da análise, a Turma resolvida de cada uma + quantas turmas foram
    criadas + quantas CONTAS de professor foram criadas automaticamente.

    A turma NOVA que não cabe nas colunas (``lista_piloto.conferir_turma_nova``:
    nome longo demais, ou série que não dá para cortar sem mudar a leitura) não
    é criada: sai ``None`` na posição dela e o motivo vai para ``avisos`` — no
    PostgreSQL ela derrubava o arquivo inteiro com 500."""
    turmas_por_nome: dict[str, Turma] = {}
    # Duas turmas com a mesma chave (uma arquivada, outra ativa): vale a ATIVA —
    # a arquivada não recebe matrícula nova (ver ``_persistir_linhas``).
    existentes = db.execute(select(Turma).where(Turma.escola_id == escola_id,
                                                Turma.ano_letivo == ano)).scalars().all()
    for t in sorted(existentes, key=lambda t: (not ida.turma_ativa(t), t.id)):
        turmas_por_nome.setdefault(_chave_turma(t.nome), t)
    criadas = 0
    profs_criados = 0
    resolvidas: list[Turma | None] = []
    for t in turmas_analise:
        chave = _chave_turma(t.nome)
        turma = turmas_por_nome.get(chave)
        if turma is None:
            serie, avisos_turma = lista_piloto.conferir_turma_nova(t)
            if avisos is not None:
                avisos.extend(avisos_turma)
            if serie is None:
                resolvidas.append(None)       # não cabe: a aba fica de fora
                continue
            turma, criada = _inserir_turma(
                db, escola_id, ano, t.nome, serie, turno=t.turno,
                observacoes=(f"Nº da classe (SED): {t.sed}" if t.sed else None),
                codigo_externo=(t.sed or None))
            turmas_por_nome[chave] = turma
            if criada:
                criadas += 1
        elif t.sed and not turma.codigo_externo:
            turma.codigo_externo = t.sed          # completa o código em reimports
        # Cria a conta de login de cada professor da turma (idempotente) e
        # vincula o titular para o RBAC. O SAVEPOINT garante que QUALQUER falha
        # aqui desfaça só o professor — nunca polui a transação nem derruba a
        # importação de alunos (que é o essencial).
        try:
            with db.begin_nested():
                profs_criados += professores.garantir_professores_da_turma(
                    db, escola_id, turma, getattr(t, "professor", "") or "")
        except Exception:  # noqa: BLE001 — professor é acessório; aluno é o essencial
            logging.getLogger(__name__).exception("falha ao criar professor da turma")
        resolvidas.append(turma)
    return resolvidas, criadas, profs_criados


def _linha_matricula(turma: Turma, parsed) -> matriculas.LinhaMatricula:
    """Adapta (Turma ORM, aluno parseado) → LinhaMatricula plana p/ a resolução."""
    return matriculas.LinhaMatricula(
        nome=parsed.nome,
        ra=_ra_forte(parsed.ficha.get("ra")),
        nascimento=matriculas.parse_nascimento(parsed.data_nascimento),
        turma_id=turma.id,
        chave_sala=_chave_turma(turma.nome),
        chamada=parsed.numero_chamada)


@dataclass
class _Resultado:
    criados: int = 0
    atualizados: int = 0
    vinculados: int = 0
    em_revisao: int = 0
    vistos: set[int] = field(default_factory=set)
    avisos: list[str] = field(default_factory=list)
    # Linhas NÃO aplicadas por estarem numa turma ARQUIVADA: turma_id → (turma, n).
    em_turma_arquivada: dict[int, tuple[Turma, int]] = field(default_factory=dict)
    # Fichas EXCLUÍDAS que a linha reativaria, mas cuja conta da plataforma hoje é
    # a identidade efetiva de um aluno de OUTRA escola (D10): não reativadas.
    retidas_conta_de_outra_escola: set[int] = field(default_factory=set)

    @property
    def linhas_em_turma_arquivada(self) -> int:
        return sum(n for _t, n in self.em_turma_arquivada.values())


def _reter_reativacao_conta_de_outra_escola(
        db: Session, escola_id: int, usuario: Usuario, res: _Resultado, existente: Aluno,
        turma: Turma, conflitos: list["identidade_efetiva.ContaDeOutraEscola"]) -> None:
    """D10 pela ficha, no caminho AUTOMÁTICO (Lista Piloto). A linha reconheceu
    pelo RA uma ficha EXCLUÍDA e a reativaria, mas a conta da plataforma dessa
    ficha hoje é a identidade efetiva de um aluno de OUTRA escola
    (``identidade_efetiva.contas_de_outra_escola_da_ficha``). Reativar faria a
    conta valer nas duas escolas sem ninguém decidir.

    Opção escolhida (a mais segura das três avaliadas): a linha vai para REVISÃO
    no sentido da Lista Piloto — não cria e NÃO altera nada (status, nome, ficha,
    matrícula e identidade ficam como estavam), avisa e audita. Descartadas:
      * aposentar a conta aqui e reativar a ficha: criaria um estado que a API
        nunca cria (a conta única aposentada, que ``definir_efetiva`` recusa), e
        a coleta seguinte desta escola descartaria a conta EM SILÊNCIO
        (``MOTIVOS_DESCARTE_DECIDIDO``) mesmo que a criança tenha mesmo voltado —
        uma decisão de identidade tomada por uma planilha, sem motivo humano;
      * reativar a ficha e só avisar: é o defeito (a conta vale nas duas).
    A reativação legítima não se perde: se a criança voltou, o Admin Global
    confere com as duas escolas e reativa em Alunos (``/alunos/acoes``, com aviso
    e auditoria); quando a conta deixar de valer na outra escola (a ficha de lá
    excluída), o próximo envio da planilha reativa e aplica a linha sozinho. As
    outras linhas do arquivo seguem normalmente. Vale para qualquer usuário: a
    planilha não é uma decisão do Admin Global sobre a conta.

    A ficha entra em ``vistos`` (está na lista; a reconciliação não mexe em
    excluída de qualquer forma) e o aviso/auditoria saem uma vez por ficha, mesmo
    que ela apareça em mais de uma turma."""
    res.vistos.add(existente.id)
    if existente.id in res.retidas_conta_de_outra_escola:
        return
    res.retidas_conta_de_outra_escola.add(existente.id)
    res.avisos.append(matriculas.aviso_reativacao_retida_conta_de_outra_escola(
        existente.nome, turma.nome))
    for c in conflitos:
        registrar(db, "aluno.reativacao_retida_conta_de_outra_escola",
                  escola_id=escola_id, usuario_id=usuario.id, entidade="aluno",
                  entidade_id=existente.id,
                  detalhes={"plataforma": c.plataforma, "id_externo": c.id_externo,
                            "outra_escola_id": c.outra_escola_id,
                            "turma_id": turma.id, "status": existente.status,
                            "acao": "nada alterado: a ficha continua excluída",
                            "origem": "importacao_matriculas"})


def _persistir_linhas(db: Session, escola_id: int, ano: int, usuario: Usuario,
                      linhas: list[tuple[Turma, object]],
                      estado: _EstadoEscola) -> _Resultado:
    """Grava na ORDEM do arquivo (preserva a 1ª ocorrência de cada aluno).

    IDENTIDADE é decidida pela PORTA ÚNICA (``matriculas.resolver_linha`` →
    ``matching``); aqui só se aplica a decisão e se cuida da MATRÍCULA, que é outra
    coisa: mudar de turma não faz de ninguém uma pessoa nova, e reconhecer quem é
    NÃO reativa ninguém (a reativação vem de constar na lista, logo abaixo).

    Antes desta função havia um 2º motor de identidade (índices de RA/nome-exato+
    turma/abreviado-posicional e um ``Aluno(...)`` direto quando os três falhavam):
    variação de grafia sem RA virava uma 2ª ficha, calada. Agora existem só três
    desfechos — REUSAR, REVISAR (não cria, não altera, avisa) e CRIAR.

    D10 pela ficha (revisão de integração do e97): o REUSAR que reativaria uma
    ficha EXCLUÍDA (o RA a reconhece) cuja conta da plataforma hoje é a
    identidade efetiva de um aluno de OUTRA escola NÃO reativa nada — vale para
    qualquer usuário, inclusive o Admin Global, porque a planilha não é uma
    decisão sobre a conta. Ver ``_reter_reativacao_conta_de_outra_escola``."""
    res = _Resultado()
    ja_alocado: set[int] = set()
    planas = [_linha_matricula(turma, parsed) for turma, parsed in linhas]
    # Unicidade 1:1 do LOTE: um cadastro abreviado que serve a DUAS linhas não
    # pode ser entregue à primeira do arquivo (seria um chute que gruda os dados
    # de uma criança na ficha da outra) — as duas vão para revisão.
    disputados = matriculas.candidatos_disputados(planas, estado.ctx)
    estado.ctx.reivindicados = matriculas.reivindicados_no_arquivo(planas, estado.ctx)
    for (turma, parsed), linha in zip(linhas, planas):
        decisao = matriculas.arbitrar_disputa(
            matriculas.resolver_linha(linha, estado.ctx), disputados)

        if decisao.acao == matriculas.REVISAR:
            # NÃO cria e NÃO altera: correspondência insegura/ambígua. Os candidatos
            # entram em `vistos` para a reconciliação não marcá-los "fora da lista"
            # (a linha diz que alguém DAQUELE grupo está na lista — só não se sabe
            # quem), e o gestor decide em Alunos › Fundir duplicatas.
            res.em_revisao += 1
            res.vistos.update(decisao.candidatos)
            nomes = ", ".join(sorted(
                estado.alunos_por_id[i].nome for i in decisao.candidatos
                if i in estado.alunos_por_id)) or "cadastro já existente"
            res.avisos.append(matriculas.aviso_revisao(parsed.nome, turma.nome, nomes))
            registrar(db, "aluno.revisao_necessaria", escola_id=escola_id,
                      usuario_id=usuario.id, entidade="aluno",
                      entidade_id=decisao.aluno_id,
                      detalhes={"origem": parsed.nome, "turma": turma.nome,
                                "decisao": "REVIEW_REQUIRED", "motivo": decisao.motivo,
                                "candidatos": list(decisao.candidatos),
                                "fonte": "importacao_matriculas"})
            continue

        if not ida.turma_ativa(turma):
            # TURMA ARQUIVADA: a linha não é aplicada — nem ficha nova, nem
            # matrícula nova, nem troca de turma, nem alteração na ficha de quem
            # já está nela (as matrículas existentes ficam como estão). Quem a
            # linha RECONHECE continua "visto" na lista: a reconciliação não o
            # marca "fora da lista" só porque a turma dele foi arquivada. O aviso
            # (um por turma, no fim) diz como reativar.
            _t, n = res.em_turma_arquivada.get(turma.id, (turma, 0))
            res.em_turma_arquivada[turma.id] = (turma, n + 1)
            if decisao.acao == matriculas.REUSAR and decisao.aluno_id is not None:
                res.vistos.add(decisao.aluno_id)
                estado.ctx.reivindicados.add(decisao.aluno_id)
            continue

        nasc = matriculas.parse_nascimento(parsed.data_nascimento)
        if decisao.acao == matriculas.CRIAR:
            aluno = Aluno(escola_id=escola_id, nome=parsed.nome, status="ativo",
                          numero_chamada=parsed.numero_chamada,
                          data_nascimento=nasc, ficha=dict(parsed.ficha),
                          da_lista_piloto=True)
            db.add(aluno)
            db.flush()
            db.add(Matricula(escola_id=escola_id, aluno_id=aluno.id,
                             turma_id=turma.id, ano_letivo=ano))
            res.criados += 1
            registrar(db, "aluno.criado_auto", escola_id=escola_id,
                      usuario_id=usuario.id, entidade="aluno", entidade_id=aluno.id,
                      detalhes={"origem": parsed.nome, "turma": turma.nome,
                                "decisao": "NEW_STUDENT", "motivo": decisao.motivo,
                                "fonte": "importacao_matriculas"})
            estado.matricula_ano[aluno.id] = None
            ja_alocado.add(aluno.id)
            res.vistos.add(aluno.id)
            estado.registrar(aluno, linha.chave_sala)
            estado.ctx.reivindicados.add(aluno.id)
            continue

        existente = estado.alunos_por_id[decisao.aluno_id]   # REUSAR
        estado.ctx.reivindicados.add(existente.id)
        if (existente.status == identidade_efetiva.EXCLUIDO
                and elegibilidade.participa_de_premiacao(turma.ano_escolar)):
            # Esta linha REATIVARIA a ficha excluída (ver o bloco de status
            # abaixo). D10: se a conta dela hoje vale em outra escola, nada muda.
            conflitos = identidade_efetiva.contas_de_outra_escola_da_ficha(
                db, escola_id, [existente], "ativo")
            if conflitos:
                _reter_reativacao_conta_de_outra_escola(
                    db, escola_id, usuario, res, existente, turma, conflitos)
                continue
        nome_antigo = existente.nome
        # O Excel é a fonte da verdade do nome — exceto para ENCURTAR: uma linha
        # abreviada ("MARIA E. SILVA") não pode apagar o nome completo já
        # cadastrado, senão a própria importação degrada a identidade e a
        # criança fica irreconhecível na vez seguinte.
        if not matriculas.nome_menos_informativo(parsed.nome, existente.nome):
            existente.nome = parsed.nome
        existente.da_lista_piloto = True   # consta na lista → membro do piloto
        if nasc and existente.data_nascimento is None:
            existente.data_nascimento = nasc
        elif nasc and existente.data_nascimento != nasc:
            # NUNCA sobrescreve (a data da ficha pode ter vindo de fonte melhor),
            # mas também não cala: divergência de nascimento é o veto de
            # identidade mais forte do motor e é assim que nasce uma 2ª ficha.
            # O aviso vive só na resposta da importação; o log é o que sobra
            # para conferir depois que a tela foi fechada.
            res.avisos.append(matriculas.aviso_nascimento_divergente(
                existente.nome, turma.nome, existente.data_nascimento, nasc))
            registrar(db, "aluno.nascimento_divergente", escola_id=escola_id,
                      usuario_id=usuario.id, entidade="aluno",
                      entidade_id=existente.id,
                      detalhes={"nome": existente.nome, "turma": turma.nome,
                                "na_ficha": str(existente.data_nascimento),
                                "na_planilha": str(nasc),
                                "acao": "preservado o da ficha; nada foi alterado",
                                "origem": "importacao_matriculas"})
        if parsed.ficha:
            existente.ficha = {**(existente.ficha or {}), **parsed.ficha}
        if existente.status == "transferido":
            # SAIU DA ESCOLA, por decisão de um gestor. Quem saiu normalmente
            # CONTINUA na planilha — a movimentação fica numa coluna que este
            # importador não interpreta —, então reativar "porque consta na
            # lista" desfaria a decisão a cada envio, em silêncio. Aqui a
            # importação não toca no status e AVISA: se a criança voltou mesmo,
            # o caminho é Reativar explicitamente, com auditoria.
            res.avisos.append(matriculas.aviso_transferido(existente.nome, turma.nome))
        elif existente.status != "ativo":
            if not elegibilidade.participa_de_premiacao(turma.ano_escolar):
                # LINHA DE FASE NÃO REATIVA NINGUÉM. A Lista Piloto oficial traz
                # as abas da Educação Infantil junto com as do Fundamental, e
                # elas não concorrem a premiação nenhuma. Reativar uma ficha
                # inativa por causa de uma linha de Fase devolveria a criança à
                # população ativa por um motivo que não dá direito a prêmio — e
                # desfaria, em silêncio, uma decisão anterior. A linha continua
                # sendo aplicada (nome, ficha, turma); só o status não muda.
                res.avisos.append(
                    matriculas.aviso_fase_nao_reativa(existente.nome, turma.nome))
            else:
                # Consta na lista atual → reativa (inclusive quem estava
                # "fora_lista_piloto" numa importação anterior).
                existente.status = "ativo"
        res.vistos.add(existente.id)
        # nº de chamada e matrícula pertencem à 1ª turma em que aparece.
        if existente.id not in ja_alocado:
            if parsed.numero_chamada is not None:
                existente.numero_chamada = parsed.numero_chamada
            mat = estado.matricula_ano.get(existente.id)
            if mat is None and existente.id not in estado.matricula_ano:
                db.add(Matricula(escola_id=escola_id, aluno_id=existente.id,
                                 turma_id=turma.id, ano_letivo=ano))
                estado.matricula_ano[existente.id] = None
            elif mat is not None and mat.turma_id != turma.id:
                mat.turma_id = turma.id   # a planilha é a fonte da verdade
            ja_alocado.add(existente.id)
            # Auditoria: todo vínculo que TROCA a identidade fica rastreável.
            # Compara com o nome REALMENTE gravado (a linha pode ter sido
            # recusada por encurtar) — o log nunca anuncia uma troca que não houve.
            if _norm(nome_antigo) != _norm(existente.nome):
                res.vinculados += 1
                registrar(db, "aluno.identidade_vinculada", escola_id=escola_id,
                          usuario_id=usuario.id, entidade="aluno",
                          entidade_id=existente.id,
                          detalhes={"nome_antigo": nome_antigo,
                                    "nome_novo": existente.nome,
                                    "origem_linha": parsed.nome,
                                    "ra": linha.ra or None,
                                    "motivo": decisao.motivo,
                                    "origem": "importacao_matriculas"})
            # Conta o aluno DISTINTO uma vez (não a cada turma em que aparece).
            res.atualizados += 1
            estado.registrar(existente, linha.chave_sala)
        else:
            estado.registrar(existente)    # 2ª turma: identidade sim, sala não
    for turma, n in res.em_turma_arquivada.values():
        res.avisos.append(matriculas.aviso_turma_arquivada(turma.nome, n))
        registrar(db, "matriculas.turma_arquivada_ignorada", escola_id=escola_id,
                  usuario_id=usuario.id, entidade="turma", entidade_id=turma.id,
                  detalhes={"turma": turma.nome, "linhas_nao_aplicadas": n,
                            "origem": "importacao_matriculas"})
    return res


def _marcar_fora_da_lista(db: Session, escola_id: int, ano: int, usuario: Usuario,
                          estado: _EstadoEscola, vistos: set[int],
                          turmas_import: set[int]) -> int:
    """Reconciliação incremental: alunos da Lista Piloto (``da_lista_piloto``),
    ATIVOS e matriculados no ano letivo NAS TURMAS QUE VIERAM NESTA IMPORTAÇÃO,
    que NÃO aparecem na nova lista viram ``status="fora_lista_piloto"`` —
    permanecem cadastrados (nunca apagados), somem das visões (todo filtro usa
    ``status=="ativo"``) e podem depois ser reativados, transferidos ou
    arquivados.

    ESCOPO POR TURMA (``turmas_import``): só reconcilia dentro das turmas
    presentes no arquivo. Assim, subir a planilha de UMA turma NÃO tira da lista
    os alunos das OUTRAS turmas (que nem foram enviadas). Idempotente: reimportar
    a mesma lista não marca ninguém; quem reaparece é reativado em
    ``_persistir_linhas``. Alunos criados à mão ou por upload
    (``da_lista_piloto`` False) são sempre preservados. Devolve quantos marcou."""
    marcados = 0
    for aluno_id, matricula in list(estado.matricula_ano.items()):
        if aluno_id in vistos:
            continue
        # Só as turmas enviadas nesta importação entram na reconciliação.
        if matricula is None or matricula.turma_id not in turmas_import:
            continue
        aluno = estado.alunos_por_id.get(aluno_id)
        if aluno is None or aluno.status != "ativo" or not aluno.da_lista_piloto:
            continue
        aluno.status = "fora_lista_piloto"
        marcados += 1
        registrar(db, "aluno.fora_lista_piloto", escola_id=escola_id,
                  usuario_id=usuario.id, entidade="aluno", entidade_id=aluno_id,
                  detalhes={"nome": aluno.nome, "origem": "importacao_matriculas"})
    return marcados


@router.post("/matriculas/confirmar", response_model=MatriculasResultadoOut)
async def confirmar_matriculas(
    request: Request,
    escola_id: int = Depends(escola_autorizada),
    arquivo: UploadFile = File(...),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Cria as turmas que faltam e matricula os alunos (ano letivo ativo),
    gravando nº de chamada, nascimento e a ficha cadastral. Reimportar não
    duplica: a identidade sai da PORTA ÚNICA (``matriculas.resolver_linha`` →
    ``services.matching``), que reusa quando é seguro, manda para revisão quando
    é inseguro e só cria quando não há candidato. Orquestra: analisar → travar a
    escola → carregar estado → criar turmas → persistir → recalcular."""
    conteudo, nome = await _ler_planilha_matriculas(request, arquivo)
    analise = await _analisar_lista_piloto(conteudo, nome)
    if not analise.turmas:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Nenhuma turma reconhecida na planilha.")
    escola = db.get(Escola, escola_id)
    if escola is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Escola não encontrada.")
    ano = escola.ano_letivo_ativo
    avisos = list(analise.avisos)

    # Serializa importações concorrentes desta escola ANTES de ler o estado: o
    # casamento roda contra o estado carregado uma vez, então dois envios
    # sobrepostos duplicariam turmas/alunos sem esta trava (no-op em SQLite).
    bloquear_escola_para_importacao(db, escola_id)
    estado = _carregar_estado(db, escola_id, ano)
    resolvidas, turmas_criadas, profs_criados = _resolver_turmas(
        db, escola_id, ano, analise.turmas, avisos)
    # A turma nova que não coube nas colunas (``None``) fica de fora inteira.
    linhas = [(resolvidas[i], parsed)
              for i, t in enumerate(analise.turmas) if resolvidas[i] is not None
              for parsed in t.alunos]

    # FASE 1 — identidade + matrícula, linha a linha, pela PORTA ÚNICA.
    persistido = _persistir_linhas(db, escola_id, ano, usuario, linhas, estado)
    alunos_criados = persistido.criados
    alunos_atualizados = persistido.atualizados
    alunos_vinculados = persistido.vinculados
    avisos.extend(persistido.avisos)

    # FASE 2 — reconciliação incremental: quem saiu da lista vira "fora da lista
    # piloto" (nunca apagado). Escopo = SÓ as turmas enviadas neste arquivo, para
    # que subir uma turma só não afete as demais. Idempotente. Turma ARQUIVADA
    # fica fora: as linhas dela não foram aplicadas, então ninguém dela sai da
    # lista por causa deste envio. A turma com linha PULADA por não caber nas
    # colunas (``TurmaMatriculas.linhas_puladas``) também: a criança daquela
    # linha não foi vista e sumiria das visões como "fora da lista".
    com_linha_pulada = {resolvidas[i].id for i, t in enumerate(analise.turmas)
                        if resolvidas[i] is not None and t.linhas_puladas}
    turmas_import = {t.id for t in resolvidas
                     if t is not None and ida.turma_ativa(t)} - com_linha_pulada
    alunos_fora_lista = _marcar_fora_da_lista(
        db, escola_id, ano, usuario, estado, persistido.vistos, turmas_import)

    registrar(db, "matriculas.importadas", escola_id=escola_id, usuario_id=usuario.id,
              entidade="escola", entidade_id=escola_id,
              detalhes={"turmas_criadas": turmas_criadas,
                        "professores_criados": profs_criados,
                        "alunos_criados": alunos_criados,
                        "alunos_atualizados": alunos_atualizados,
                        "alunos_vinculados": alunos_vinculados,
                        "alunos_em_revisao": persistido.em_revisao,
                        "alunos_reativacao_retida_conta_de_outra_escola":
                            len(persistido.retidas_conta_de_outra_escola),
                        "alunos_fora_lista": alunos_fora_lista,
                        "linhas_em_turma_arquivada": persistido.linhas_em_turma_arquivada})
    db.commit()

    scoring.recalcular_escola(db, escola_id)
    from app.routers.publico import invalidar_cache_painel
    invalidar_cache_painel(escola_id)
    extra = (f" {alunos_vinculados} cadastro(s) de importação anterior recebeu(ram) "
             "o nome completo.") if alunos_vinculados else ""
    if profs_criados:
        extra += (f" {profs_criados} professor(es) ganharam conta de acesso "
                  "automática (usuário = NomeSobrenome). A conta nasce sem senha: "
                  "para o primeiro acesso, gere o link de redefinição em Usuários.")
    if alunos_fora_lista:
        extra += (f" {alunos_fora_lista} aluno(s) que não constam mais na lista "
                  "foram marcados como “fora da lista piloto” — continuam "
                  "cadastrados (nada foi apagado); reative, transfira ou arquive "
                  "quando quiser.")
    if persistido.em_revisao:
        extra += (f" {persistido.em_revisao} linha(s) ficaram para REVISÃO: parecem "
                  "ser alunos já cadastrados, mas a correspondência não é segura — "
                  "nada foi criado nelas (senão viraria ficha duplicada). Veja os "
                  "avisos abaixo.")
    if persistido.retidas_conta_de_outra_escola:
        extra += (f" {len(persistido.retidas_conta_de_outra_escola)} ficha(s) excluída(s) "
                  "NÃO foram reativadas: a conta da plataforma delas hoje é a "
                  "identidade de um aluno de outra escola do Constela, e nada foi "
                  "alterado nelas. Veja os avisos abaixo.")
    if persistido.em_turma_arquivada:
        extra += (f" {persistido.linhas_em_turma_arquivada} linha(s) estão em turma "
                  "ARQUIVADA e não foram aplicadas (nenhuma matrícula existente foi "
                  "alterada) — reative a turma e envie a planilha de novo. Veja os "
                  "avisos abaixo.")
    return MatriculasResultadoOut(
        mensagem=(f"{turmas_criadas} turma(s) criada(s), {alunos_criados} aluno(s) "
                  f"cadastrado(s) e {alunos_atualizados} atualizado(s)." + extra),
        turmas_criadas=turmas_criadas, alunos_criados=alunos_criados,
        alunos_atualizados=alunos_atualizados,
        alunos_fora_lista=alunos_fora_lista,
        alunos_em_revisao=persistido.em_revisao,
        professores_criados=profs_criados, avisos=avisos,
    )


# --- Histórico (PRD §15) ------------------------------------------------------

# --- Fila de revisão de identidade --------------------------------------------
# A linha ambígua de uma importação/sincronização NÃO é descartada: fica aqui até
# um gestor decidir EXPLICITAMENTE de quem são os dados. Nada é fundido: resolver
# escolhe a ficha dona (ou cria uma nova, se o gestor decidir que é outra
# criança), vincula a identidade externa a ela, aplica os dados guardados pelo
# pipeline normal de importação e audita. A fusão de fichas duplicadas continua
# sendo a ação separada de Alunos › Fundir duplicatas.

# A listagem da fila devolve no máximo as N revisões mais recentes.
LIMITE_LISTA_REVISOES = 500


def _revisao_out(rev: RevisaoIdentidade, triagem: dict | None = None,
                 nomes: tuple[str, dict[str, str]] | None = None) -> RevisaoIdentidadeOut:
    saida = RevisaoIdentidadeOut.model_validate(rev)
    saida.motivo_texto = ida.MOTIVOS.get(rev.motivo, rev.motivo)
    saida.triagem = triagem
    if nomes is not None:
        saida.nome_ficha_nova, saida.nome_ficha_nova_por_turma = nomes
    return saida


def _nome_da_ficha_nova(rev: RevisaoIdentidade, turma_nome: str) -> str:
    """O nome que "Criar novo aluno" grava na turma escolhida: o recebido, sem o
    sufixo de turma digitado junto (A10) — o da sala da turma escolhida ou o da sala
    que a linha informou (a mesma regra da criação pela importação)."""
    return ida.nome_sem_sufixo_de_turma(rev.nome_recebido, ida.chave_sala(turma_nome),
                                        ida.chave_sala(rev.turma_informada or ""))


def _nomes_da_ficha_nova(db: Session, escola_id: int, revisoes: list[RevisaoIdentidade],
                         ) -> dict[int, tuple[str, dict[str, str]]]:
    """Para a tela prometer o nome que o /resolver grava: por pendência, o nome padrão
    e ``{turma_id: nome}`` só das turmas em que ele muda (o sufixo daquela sala sai).
    Sufixo de turma tem dígito: nome sem dígito é o recebido, sem conta nenhuma."""
    saida = {r.id: ((r.nome_recebido or "").strip(), {}) for r in revisoes}
    com_digito = [r for r in revisoes if any(c.isdigit() for c in (r.nome_recebido or ""))]
    if not com_digito:
        return saida
    salas: dict[str, tuple[str, list[int]]] = {}
    for tid, nome in db.execute(select(Turma.id, Turma.nome)
                                .where(Turma.escola_id == escola_id)).all():
        salas.setdefault(ida.chave_sala(nome), (nome, []))[1].append(tid)
    for r in com_digito:
        padrao = _nome_da_ficha_nova(r, "")
        por_turma: dict[str, str] = {}
        for nome_turma, tids in salas.values():
            nome = _nome_da_ficha_nova(r, nome_turma)
            if nome != padrao:
                por_turma.update({str(t): nome for t in tids})
        saida[r.id] = (padrao, por_turma)
    return saida


def _revisao_da_escola(db: Session, escola_id: int, revisao_id: int) -> RevisaoIdentidade:
    rev = db.get(RevisaoIdentidade, revisao_id)
    if rev is None or rev.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Revisão não encontrada.")
    return rev


@router.get("/revisoes", response_model=list[RevisaoIdentidadeOut])
def listar_revisoes(
    situacao: str = "pendente",
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Fila de revisão de identidade da escola (padrão: só as pendentes;
    ``situacao=todas`` inclui resolvidas e descartadas)."""
    consulta = select(RevisaoIdentidade).where(RevisaoIdentidade.escola_id == escola_id)
    if situacao != "todas":
        if situacao not in ("pendente", "resolvida", "descartada"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Situação inválida.")
        consulta = consulta.where(RevisaoIdentidade.status == situacao)
    revisoes = db.execute(
        consulta.order_by(RevisaoIdentidade.atualizada_em.desc(),
                          RevisaoIdentidade.id.desc()).limit(LIMITE_LISTA_REVISOES)).scalars().all()
    # Cada PENDÊNCIA vem com a TRIAGEM (o selo da tela de Revisões): dá para
    # encerrar com segurança, e por quê. Só leitura e determinística — não decide
    # nada, apenas explica. Ela precisa do estado da escola inteiro (contas, fichas,
    # turmas, decisões), então o contexto só é carregado quando há pendência na
    # página: a lista de resolvidas/descartadas não paga esse custo.
    pendentes = [r for r in revisoes if r.status == "pendente"]
    triagens: dict[int, dict] = {}
    nomes: dict[int, tuple[str, dict[str, str]]] = {}
    if pendentes:
        ctx = ida.carregar_contexto(db, escola_id)
        triagens = {rid: t.como_dict() for rid, t in triagem_revisoes.triar_revisoes(
            ctx, list(revisoes)).items()}
        nomes = _nomes_da_ficha_nova(db, escola_id, pendentes)
    return [_revisao_out(r, triagens.get(r.id), nomes.get(r.id)) for r in revisoes]


@router.get("/contagem-revisoes", response_model=dict)
def contar_revisoes(
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """O TOTAL de pendências da escola, por motivo. A lista de /revisoes para em
    ``LIMITE_LISTA_REVISOES`` (as mais recentes) e o contador da tela saturava
    nesse número; aqui é uma contagem, sem carregar fila nem triagem."""
    por_motivo = {motivo: int(n) for motivo, n in db.execute(
        select(RevisaoIdentidade.motivo, func.count())
        .where(RevisaoIdentidade.escola_id == escola_id,
               RevisaoIdentidade.status == "pendente")
        .group_by(RevisaoIdentidade.motivo)).all()}
    return {"pendentes": sum(por_motivo.values()), "por_motivo": por_motivo,
            "limite_da_lista": LIMITE_LISTA_REVISOES}


def _confirmacao_da_revisao(rev: RevisaoIdentidade, aluno_id: int,
                            recalcular: bool) -> ImportacaoConfirm | None:
    """Recompõe a importação original desta pendência, agora com o aluno FIXADO
    pela decisão do gestor — os dados passam pelo MESMO pipeline do /confirmar."""
    if not rev.linhas:
        return None
    ctx = rev.contexto or {}
    formato = rev.formato if rev.formato in ("resumo", "leituras") else "resumo"
    tipo = ctx.get("tipo") if ctx.get("tipo") in ("pdf", "texto", "xlsx") else "texto"
    return ImportacaoConfirm(
        plataforma=rev.plataforma, formato=formato, tipo=tipo,
        data_referencia=ctx.get("data_referencia") or None,
        periodo_inicio=ctx.get("periodo_inicio") or None,
        periodo_fim=ctx.get("periodo_fim") or None,
        linhas=[{"nome": rev.nome_recebido, "dados": d, "aluno_id": aluno_id}
                for d in rev.linhas],
        recalcular=recalcular, sincronizar_turma=False, permitir_criar_turma=False)


def _retrato_superado(db: Session, escola_id: int, aluno_id: int,
                      rev: RevisaoIdentidade) -> dict | None:
    """O retrato guardado nesta pendência já foi superado pelo que está gravado?

    Uma pendência guarda a linha do dia em que foi aberta. Se uma sincronização
    posterior já gravou o retrato daquele aluno, reaplicar a linha velha não
    acrescenta nada e ainda suja o histórico com um ponto retrodatado. Aqui só se
    DECIDE isso; quem grava snapshot continua sendo o pipeline de importação, com
    a mesma semântica de sempre (um relatório histórico pode ser registrado sem
    virar o estado atual, que é sempre o mais recente por ``data_referencia``).

    Só vale para RETRATO. ``leituras`` do Elefante nunca é filtrado: leituras se
    ACUMULAM e o pipeline já é idempotente (dedup por livro já lido + unicidade
    ``aluno_id, livro_id``), então reaplicar só acrescenta o que faltava.

    Devolve ``None`` quando o payload deve ser aplicado, ou um dicionário com o
    motivo (vai para a auditoria e para ``rev.resolucao``). Não compara CONTADORES
    e não usa ``max()``: a comparação é de DATA, porque retrato é substituível e
    quem vale é o mais recente — que já está no banco.

    Data LEGADA fora do calendário (``0001-01-01T00:00:00+03:00``, ou o ano 1 antes
    das 03h UTC, que em Brasília ainda é o ano 0): nunca reaplicar, com ou sem
    retrato gravado. Antes a conversão estourava aqui (OverflowError → 500) e, sem
    retrato, o pipeline recusava a data (422): a pendência nunca saía da fila."""
    if rev.formato == "leituras":
        return None
    modelo = SnapshotMatific if rev.plataforma == "matific" else SnapshotElefante
    snap = _snapshot_atual(db, escola_id, aluno_id, modelo)
    congelada_txt = (rev.contexto or {}).get("data_referencia") or ""
    atual_txt = (snap.data_referencia.isoformat()
                 if snap is not None and snap.data_referencia else None)
    base = {"formato": rev.formato, "plataforma": rev.plataforma,
            "data_congelada": congelada_txt or None, "data_snapshot_atual": atual_txt}
    try:
        congelada = datetime.fromisoformat(congelada_txt) if congelada_txt else None
    except ValueError:
        congelada = None
    if congelada is not None and _instante_utc_no_calendario(congelada) is None:
        return {**base, "motivo": "data_referencia_fora_do_calendario"}
    if snap is None:
        return None                      # nada gravado: o congelado é o que há
    if congelada is None:
        # Sem data, o pipeline gravaria com a data de HOJE e a linha velha viraria
        # o estado atual. É o pior caso: nunca reaplicar.
        return {**base, "motivo": "data_referencia_ausente"}
    congelada = _instante_utc(congelada)     # UTC naive (ver ``_superado_pela_data``)
    if modelo is SnapshotElefante and _guarda_questoes_medidas(db, rev):
        # QUESTÕES QUE NÃO VIERAM (S9): o retrato gravado por uma coleta sem as
        # questões (``IMPORTACAO_SEM_QUESTOES``) tem a data da coleta, mas as
        # questões HERDADAS do anterior — não supera, nas questões, o guardado que as
        # mediu. Antes ele contava como "o mais recente": quem leu um livro novo
        # ganhava esse retrato no dia da coleta, e o /resolver descartava o guardado
        # (``snapshot_mais_recente``) — a medida sumia e o Relatório por Período
        # ficava sem número. A comparação é com o último retrato que MEDE as
        # questões; o guardado entra como ponto do histórico (o pipeline o grava
        # retrodatado, sem virar o estado atual) e os retratos S9 posteriores passam
        # a herdar dele (``_retratos_sem_questoes_herdam_do_aplicado``).
        medido = _ultimo_retrato_que_mede_as_questoes(db, escola_id, aluno_id)
        superado = (_superado_pela_data(base, medido, congelada)
                    if medido is not None else None)
        if superado is not None:
            return superado
        do_dia = next((s for s in _retratos_sem_questoes(db, escola_id, aluno_id)
                       if _mesmo_dia(s.data_referencia, congelada)), None)
        if do_dia is not None:
            # A mesma regra do "mesmo dia" contra o retrato S9: o pipeline
            # atualizaria NO LUGAR o retrato da coleta daquele dia, e os livros e o
            # tempo dele (medidos) virariam os do guardado, talvez mais antigos.
            return {**base, "motivo": "mesmo_dia_de_retrato_sem_questoes",
                    "data_retrato_sem_questoes": do_dia.data_referencia.isoformat()}
        return None
    return _superado_pela_data(base, snap, congelada)


def _superado_pela_data(base: dict, snap, congelada: datetime) -> dict | None:
    """O juízo de DATA de ``_retrato_superado`` contra um retrato gravado
    (``congelada`` já em UTC naive)."""
    # Os dois INSTANTES, convertidos (naive = UTC; com fuso, para UTC). Antes o
    # fuso era só cortado: a data congelada "01h de 24/10 -03:00" (04h UTC, dia 24
    # em Brasília) virava "01h UTC" — dia 23 em Brasília e mais antiga que um
    # retrato das 02h UTC, e a pendência MAIS NOVA era descartada como superada.
    atual = _instante_utc(snap.data_referencia)
    if _mesmo_dia(atual, congelada):
        # Mesmo dia: o pipeline atualizaria o retrato NO LUGAR, e o valor novo
        # desapareceria sem deixar linha no histórico. É o caso mais perigoso,
        # por isso é diagnosticado ANTES do simples "mais recente".
        return {**base, "motivo": "mesmo_dia_do_snapshot_atual"}
    if atual > congelada:
        return {**base, "motivo": "snapshot_mais_recente"}
    return None


def _guarda_questoes_medidas(db: Session, rev: RevisaoIdentidade) -> bool:
    """A pendência guarda um retrato que MEDIU as questões: alguma linha traz o
    campo e a importação que a abriu não é uma coleta S9 (sem as questões)."""
    if not _guarda_questoes(rev):
        return False
    origem = db.get(Importacao, rev.importacao_id) if rev.importacao_id else None
    return origem is None or origem.status != IMPORTACAO_SEM_QUESTOES


def _retratos_elefante_com_status(db: Session, escola_id: int, aluno_id: int, *,
                                  depois_de: datetime | None = None):
    """(retrato, status da importação) do Elefante do aluno, do mais antigo ao mais
    novo (data, id). ``depois_de``: só os de data posterior."""
    consulta = (select(SnapshotElefante, Importacao.status)
                .outerjoin(Importacao, Importacao.id == SnapshotElefante.importacao_id)
                .where(SnapshotElefante.escola_id == escola_id,
                       SnapshotElefante.aluno_id == aluno_id))
    if depois_de is not None:
        consulta = consulta.where(SnapshotElefante.data_referencia > depois_de)
    return db.execute(consulta.order_by(SnapshotElefante.data_referencia.asc(),
                                        SnapshotElefante.id.asc())).all()


def _ultimo_retrato_que_mede_as_questoes(db: Session, escola_id: int, aluno_id: int):
    """O retrato do Elefante mais recente que não veio de uma coleta S9."""
    medem = [s for s, situacao in _retratos_elefante_com_status(db, escola_id, aluno_id)
             if situacao != IMPORTACAO_SEM_QUESTOES]
    return medem[-1] if medem else None


def _retratos_sem_questoes(db: Session, escola_id: int, aluno_id: int) -> list:
    """Os retratos do Elefante gravados por coletas S9 (questões herdadas)."""
    return [s for s, situacao in _retratos_elefante_com_status(db, escola_id, aluno_id)
            if situacao == IMPORTACAO_SEM_QUESTOES]


def _retratos_sem_questoes_herdam_do_aplicado(db: Session, escola_id: int, aluno_id: int,
                                              importacao_id: int) -> int:
    """Depois de o /resolver gravar, retrodatado, o retrato guardado que MEDIU as
    questões: os retratos S9 POSTERIORES a ele herdaram as questões do retrato que
    valia na hora da coleta (o anterior ao guardado). Passam a herdar do aplicado —
    o que teriam herdado se a pendência já estivesse resolvida na coleta —, até o
    próximo retrato que mede as questões. Sem isto o estado atual (o retrato S9 mais
    novo) continuava com as questões de antes, e a série "caía" depois do ponto
    aplicado. Só as QUESTÕES mudam (livros e tempo desses retratos são medidos).
    Devolve quantos retratos mudaram."""
    aplicado = db.execute(
        select(SnapshotElefante)
        .where(SnapshotElefante.escola_id == escola_id,
               SnapshotElefante.aluno_id == aluno_id,
               SnapshotElefante.importacao_id == importacao_id)
        .order_by(SnapshotElefante.data_referencia.desc(), SnapshotElefante.id.desc())
        .limit(1)).scalar_one_or_none()
    if aplicado is None:
        return 0
    questoes = (aplicado.questoes_tentativas, aplicado.questoes_acertos)
    mudaram = 0
    for snap, situacao in _retratos_elefante_com_status(
            db, escola_id, aluno_id, depois_de=aplicado.data_referencia):
        if situacao != IMPORTACAO_SEM_QUESTOES:
            break                    # mede as questões: dali em diante herdam dele
        if (snap.questoes_tentativas, snap.questoes_acertos) != questoes:
            snap.questoes_tentativas, snap.questoes_acertos = questoes
            mudaram += 1
    return mudaram


@router.post("/revisoes/{revisao_id}/resolver", response_model=ResolucaoRevisaoOut)
def resolver_revisao(
    revisao_id: int,
    corpo: ResolverRevisaoIn,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Decisão EXPLÍCITA do gestor sobre uma pendência: ``aluno_id`` (a ficha dona
    dos dados) OU ``criar_em_turma_id`` (é outra criança: ficha nova nessa turma).

    0. conta da plataforma já EFETIVA em outra escola do Constela (decisão D10):
       só o Admin Global confirma (403 para a gestão da escola), com aviso na
       resposta e auditoria ``identidade.revisao_outra_escola_confirmada``;
    1. a identidade externa da linha passa a apontar para o aluno escolhido (se
       estava em outra ficha, é transferida — e isso fica auditado);
    2. os dados guardados são aplicados pelo pipeline normal de importação —
       menos o RETRATO já superado por uma sincronização posterior, que fica
       registrado como tal em vez de ressuscitar números velhos
       (``_retrato_superado``); ``leituras`` sempre se aplica, porque acumula;
    3. SÓ ENTÃO a pendência (e as irmãs da MESMA identidade, ex.: resumo +
       leituras) é marcada como resolvida, com quem decidiu e quando. Falhar no
       meio deixa tudo pendente e o gestor tenta de novo pela tela;
    4. a próxima sincronização casa pela identidade e não recria a duplicata.
    Nunca funde fichas.

    D17: ``criar_em_turma_id`` de turma ARQUIVADA é 409 antes de gravar
    (``turma_arquivada.exigir_turma_ativa``) — a ficha nova nasce "ativa", e a
    fila não pode desfazer a rede de segurança do /confirmar (motivo
    ``turma_arquivada``) que a criou. Turma ATIVA de OUTRO ano letivo também é
    409 antes de gravar (``turma_arquivada.exigir_destino_do_ano_ativo``, a mesma
    trava de cadastrar e transferir): a ficha nova nasce com a matrícula do ano
    ativo, que numa turma de outro ano contaria na escola e sumiria das turmas do
    ano — a criança chegava à Secretaria por subtração. A pendência continua
    pendente e o gestor escolhe uma turma do ano."""
    if (corpo.aluno_id is None) == (corpo.criar_em_turma_id is None):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Informe o aluno escolhido OU a turma da ficha nova.")
    bloquear_escola_para_importacao(db, escola_id)
    rev = _revisao_da_escola(db, escola_id, revisao_id)
    if rev.status != "pendente":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Esta revisão já está {rev.status}.")
    escola = db.get(Escola, escola_id)
    avisos: list[str] = []

    # Conta APOSENTADA não volta por aqui. A escola já decidiu que ela não
    # representa a criança no Constela; resolver a pendência dela reassociaria
    # os dados em silêncio e desfaria a decisão sem auditoria. Para voltar atrás
    # existe o caminho explícito: /identidades/{plataforma}/reativar.
    if rev.id_externo:
        aposentada = db.execute(select(IdentidadeExterna).where(
            IdentidadeExterna.escola_id == escola_id,
            IdentidadeExterna.plataforma == rev.plataforma,
            IdentidadeExterna.id_externo == rev.id_externo,
            IdentidadeExterna.status == "aposentada")).scalars().first()
        if aposentada is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"A conta {rev.id_externo} está aposentada nesta ficha e não "
                "recebe dados. Para voltar a usá-la, reative-a explicitamente "
                "em Identidades do aluno.")

    # D10 (risco V): conta da plataforma que já é a identidade EFETIVA de um aluno
    # de OUTRA escola do Constela (a revisão 'identidade_de_outra_escola', ou
    # outra pendência da mesma conta). Confirmar aqui faz a conta valer nas duas
    # escolas, e a coleta seguinte da outra escola manda a criança de lá para a
    # revisão (deixa de atualizar, com alerta crítico). Só o Admin Global decide,
    # com aviso na resposta e auditoria própria; a outra escola não é alterada.
    outra_escola = None
    if rev.id_externo:
        outra_escola = ida.efetivas_em_outra_escola(
            db, escola_id, rev.plataforma, [rev.id_externo]).get(rev.id_externo)
    if outra_escola is not None:
        if not usuario.is_global:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Esta conta da plataforma já está vinculada a um aluno de OUTRA escola "
                "do Constela. Confirmá-la aqui faria a criança de lá deixar de ser "
                "atualizada (a conta cai em revisão na próxima coleta daquela escola): "
                "só o Admin Global confirma, depois de conferir com as duas escolas. Se "
                "a conta não é de uma criança desta escola, descarte a pendência.")
        avisos.append(ida.AVISO_CONTA_DE_OUTRA_ESCOLA)

    if corpo.aluno_id is not None:
        aluno = db.get(Aluno, corpo.aluno_id)
        if aluno is None or aluno.escola_id != escola_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "O aluno escolhido não pertence a esta escola.")
        if aluno.status == "excluido":
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "A ficha escolhida foi excluída e não recebe dados.")
        if aluno.status != "ativo":
            avisos.append(f"{aluno.nome} está com a ficha “{aluno.status}”: os dados "
                          "foram aplicados, mas ele só volta ao ranking quando for "
                          "reativado em Alunos.")
        acao = "associar"
    else:
        turma = db.get(Turma, corpo.criar_em_turma_id)
        if turma is None or turma.escola_id != escola_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Turma inválida.")
        # D17: a ficha nova nasce "ativa" — turma arquivada não a recebe (a mesma
        # recusa de transferir, cadastrar e reativar; a trava da escola já foi
        # tomada no topo). 409 antes de gravar: a pendência continua pendente, e
        # o gestor escolhe uma turma ativa ou reativa a turma.
        turma_arquivada.exigir_turma_ativa(turma)
        # Nem turma de OUTRO ano letivo: a matrícula que nasce é a do ano ativo.
        turma_arquivada.exigir_destino_do_ano_ativo(turma, escola.ano_letivo_ativo)
        # Sem o sufixo de turma digitado junto do nome (a mesma regra da criação
        # pela importação); a pendência continua guardando o nome recebido. É o
        # nome que a listagem mostra (``_nomes_da_ficha_nova``).
        aluno = Aluno(escola_id=escola_id, nome=_nome_da_ficha_nova(rev, turma.nome))
        db.add(aluno)
        db.flush()
        db.add(Matricula(escola_id=escola_id, aluno_id=aluno.id, turma_id=turma.id,
                         ano_letivo=escola.ano_letivo_ativo))
        registrar(db, "aluno.criado", escola_id=escola_id, usuario_id=usuario.id,
                  entidade="aluno", entidade_id=aluno.id,
                  detalhes={"origem": "revisao_identidade", "revisao_id": rev.id,
                            "turma": turma.nome, "plataforma": rev.plataforma})
        acao = "criar"

    if rev.id_externo:
        ident = db.execute(select(IdentidadeExterna).where(
            IdentidadeExterna.escola_id == escola_id,
            IdentidadeExterna.plataforma == rev.plataforma,
            IdentidadeExterna.id_externo == rev.id_externo)).scalars().first()
        if ident is None:
            db.add(IdentidadeExterna(escola_id=escola_id, aluno_id=aluno.id,
                                     plataforma=rev.plataforma, id_externo=rev.id_externo))
        elif ident.aluno_id != aluno.id:
            antigo = ident.aluno_id
            ident.aluno_id = aluno.id
            registrar(db, "identidade.reatribuida", escola_id=escola_id,
                      usuario_id=usuario.id, entidade="aluno", entidade_id=aluno.id,
                      detalhes={"plataforma": rev.plataforma, "id_externo": rev.id_externo,
                                "de_aluno_id": antigo, "para_aluno_id": aluno.id,
                                "motivo": "revisao_resolvida", "revisao_id": rev.id})
            avisos.append("A conta da plataforma estava ligada a outra ficha e foi "
                          "transferida para a ficha escolhida.")
        db.flush()
        if outra_escola is not None:
            # D10: a confirmação do Admin Global de uma conta efetiva noutra escola
            # fica com trilha própria (quem, qual conta, qual outra escola).
            registrar(db, "identidade.revisao_outra_escola_confirmada", escola_id=escola_id,
                      usuario_id=usuario.id, entidade="aluno", entidade_id=aluno.id,
                      detalhes={"revisao_id": rev.id, "plataforma": rev.plataforma,
                                "id_externo": rev.id_externo, "motivo": rev.motivo,
                                "acao": acao, "outra_escola_id": outra_escola,
                                "aviso": "conta continua efetiva na outra escola"})

    # A mesma identidade pode ter mais de uma pendência (resumo, leituras, períodos
    # do Matific): a decisão do gestor vale para todas.
    irmas = db.execute(
        select(RevisaoIdentidade).where(
            RevisaoIdentidade.escola_id == escola_id,
            RevisaoIdentidade.chave_identidade == rev.chave_identidade,
            RevisaoIdentidade.status == "pendente",
            RevisaoIdentidade.id != rev.id)
        .order_by(RevisaoIdentidade.id)).scalars().all()
    resolvidas = [rev, *irmas]

    # RETRATO SUPERADO: o payload congelado de um resumo pode ser mais ANTIGO que
    # o que a sincronização já gravou. Aí o que importa é o vínculo de identidade
    # — ressuscitar a foto velha só sujaria o histórico. Leituras nunca entram
    # aqui: acumulam e o pipeline deduplica.
    superadas: dict[int, dict] = {}
    com_dados: list[RevisaoIdentidade] = []
    for r in resolvidas:
        if not r.linhas:
            continue
        if r.motivo == "id_externo_duplicado" and ida.linhas_divergentes(r.linhas):
            # O mesmo id veio em linhas de retrato com números DIFERENTES: qualquer
            # uma que se aplicasse seria um chute (o pipeline fica com a última).
            # Vale só o vínculo; os números entram numa coleta em que a conta venha
            # uma vez só.
            superadas[r.id] = {"formato": r.formato, "plataforma": r.plataforma,
                               "motivo": "linhas_divergentes_do_mesmo_id"}
            avisos.append(
                f"Os dados guardados nesta pendência ({r.plataforma}/{r.formato}) "
                "vieram em mais de uma linha com números diferentes para a mesma "
                "conta: só o vínculo de identidade foi aplicado, sem escolher "
                "números. O retrato desta conta entra na próxima sincronização em "
                "que ela vier uma vez só e sem outra pendência de id duplicado.")
            continue
        motivo_superado = _retrato_superado(db, escola_id, aluno.id, r)
        if motivo_superado is None:
            com_dados.append(r)
        elif motivo_superado["motivo"] == "data_referencia_fora_do_calendario":
            superadas[r.id] = motivo_superado
            avisos.append(
                f"Os dados guardados nesta pendência ({r.plataforma}/{r.formato}) têm "
                "uma data fora do calendário (registro antigo): só o vínculo de "
                "identidade foi aplicado, e o retrato atual do aluno ficou como estava.")
        else:
            superadas[r.id] = motivo_superado
            avisos.append(
                f"Os dados guardados nesta pendência ({r.plataforma}/{r.formato}) já "
                "foram superados pela sincronização: só o vínculo de identidade foi "
                "aplicado, e o retrato atual do aluno ficou como estava.")

    # UMA TRANSAÇÃO SÓ: vincula a identidade, aplica TODAS as irmãs, recalcula e
    # só então fecha as pendências — tudo no mesmo BEGIN. Por isso se chama o
    # NÚCLEO do /confirmar (`_confirmar_sem_commit`) e não a rota: a rota commita
    # a cada chamada, e um erro na 2ª irmã deixaria a 1ª gravada para sempre.
    # Falhou em qualquer ponto -> ROLLBACK e tudo continua pendente.
    importacoes: list[int] = []
    herdadas: dict[int, int] = {}    # pendência -> retratos S9 que herdaram as questões
    for r in com_dados:
        conf = _confirmacao_da_revisao(r, aluno.id, recalcular=False)
        # S9: a linha guardada veio de uma coleta em que a plataforma NÃO mandou as
        # questões (a importação de origem está marcada). Reaplicada sem a marca, o
        # retrato nascia numa importação "concluida" e virava borda das Questões do
        # período ("0 no período", ou o contador vitalício na coleta seguinte, com
        # cobertura "completa"). Herda a marca e a regra de não repetir retrato — as
        # mesmas que a sincronização aplicou às linhas que entraram direto.
        origem = db.get(Importacao, r.importacao_id) if r.importacao_id else None
        sem_questoes = origem is not None and origem.status == IMPORTACAO_SEM_QUESTOES
        # encerrar_revisoes=False: estas pendências são fechadas logo abaixo, pelo
        # gestor — não como "encerradas automaticamente".
        # piso_da_data=False: a data é a da importação original (registro do servidor).
        nucleo = _confirmar_sem_commit(dados=conf, escola_id=escola_id,
                                       usuario=usuario, db=db, encerrar_revisoes=False,
                                       piso_da_data=False,
                                       sem_retrato_repetido=sem_questoes,
                                       questoes_herdadas=sem_questoes)
        importacoes.append(nucleo.importacao_id)
        avisos.extend(nucleo.avisos)
        if (r.plataforma == "elefante" and r.formato != "leituras"
                and _guarda_questoes_medidas(db, r)):
            herdaram = _retratos_sem_questoes_herdam_do_aplicado(
                db, escola_id, aluno.id, nucleo.importacao_id)
            if herdaram:
                herdadas[r.id] = herdaram

    # Recálculo DENTRO da transação (uma vez só, no fim das irmãs, e não a cada
    # uma): `commit=False` deixa o fechamento para o commit único lá embaixo.
    if com_dados:
        scoring.recalcular_escola(db, escola_id, commit=False)

    momento = agora()
    for r in resolvidas:
        r.status = "resolvida"
        r.aluno_escolhido_id = aluno.id
        r.resolvida_por_id = usuario.id
        r.resolvida_em = momento
        r.resolucao = {"acao": acao, "aluno_id": aluno.id,
                       "revisao_origem": rev.id}
        if r.id in superadas:
            r.resolucao["dados_superados"] = superadas[r.id]
        detalhes = {"revisao_id": r.id, "plataforma": r.plataforma,
                    "formato": r.formato, "motivo": r.motivo, "acao": acao,
                    "nome_recebido": r.nome_recebido,
                    "dados_superados": superadas.get(r.id),
                    "candidatos": [c.get("aluno_id") for c in (r.candidatos or [])]}
        if r.id in herdadas:
            # Retratos S9 posteriores que passaram a herdar as questões do aplicado.
            r.resolucao["retratos_sem_questoes_atualizados"] = herdadas[r.id]
            detalhes["retratos_sem_questoes_atualizados"] = herdadas[r.id]
        registrar(db, "identidade.revisao_resolvida", escola_id=escola_id,
                  usuario_id=usuario.id, entidade="aluno", entidade_id=aluno.id,
                  detalhes=detalhes)
    db.commit()                      # <- ÚNICO commit de todo o fluxo

    # DEPOIS do commit: cache do painel e push. Fora da transação de propósito —
    # avisar a escola sobre dado que ainda pode sofrer rollback seria mentira, e
    # o próprio push commita ao limpar token morto.
    if com_dados:
        _pos_commit_importacao(
            db, escola_id, corpo=push.corpo_dados_atualizados(aluno.nome),
            aluno_id=aluno.id)
    db.refresh(rev)
    return ResolucaoRevisaoOut(
        revisao=_revisao_out(rev), aluno_id=aluno.id,
        revisoes_resolvidas=[r.id for r in resolvidas], importacoes=importacoes,
        avisos=avisos)


@router.get("/identidades/{plataforma}/aluno/{aluno_id}", response_model=list[dict])
def listar_identidades_do_aluno(
    plataforma: str,
    aluno_id: int,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """As contas que este aluno tem NESTA plataforma, com o estado de cada uma —
    a que vale hoje e as aposentadas, com quem decidiu, quando e por quê."""
    aluno = db.get(Aluno, aluno_id)
    if aluno is None or aluno.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aluno não encontrado.")
    saida = []
    for i in identidade_efetiva.identidades_do_aluno(db, escola_id, aluno_id, plataforma):
        quem = db.get(Usuario, i.aposentada_por_id) if i.aposentada_por_id else None
        saida.append({"id": i.id, "id_externo": i.id_externo, "status": i.status,
                      "created_at": i.created_at, "aposentada_em": i.aposentada_em,
                      "aposentada_por": quem.nome if quem else None,
                      "motivo_aposentadoria": i.motivo_aposentadoria})
    return saida


@router.post("/identidades/{plataforma}/efetiva", response_model=dict)
def definir_identidade_efetiva(
    plataforma: str,
    corpo: DefinirIdentidadeEfetivaIn,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """CONTA DUPLICADA: a criança tem mais de uma conta nesta plataforma e a
    escola diz qual vale no Constela.

    A conta escolhida passa a ser a identidade EFETIVA; as outras ficam
    APOSENTADAS — preservadas com todo o histórico, mas fora da importação, do
    retrato e da pontuação, e sem voltar a se associar sozinha. Nada é apagado.

    Isto é decisão INTERNA do Constela: a conta continua existindo na plataforma
    externa, e nada é desativado lá. A operação é reversível (``/reativar``) e
    fica auditada com quem decidiu, quando, o estado anterior e o posterior.

    D10: escolher uma conta APOSENTADA que já é efetiva em OUTRA escola do
    Constela é só do Admin Global (403 para a gestão da escola); ele segue com
    ``avisos`` na resposta e auditoria própria."""
    bloquear_escola_para_importacao(db, escola_id)
    try:
        r = identidade_efetiva.definir_efetiva(
            db, escola_id, aluno_id=corpo.aluno_id, plataforma=plataforma,
            id_externo_efetivo=corpo.id_externo_efetivo,
            aposentar=list(corpo.aposentar), motivo=corpo.motivo,
            usuario_id=usuario.id, admin_global=bool(usuario.is_global))
    except identidade_efetiva.ErroIdentidade as exc:
        db.rollback()
        raise HTTPException(_status_erro_identidade(exc), str(exc)) from exc
    db.commit()
    return {**r.como_dict(),
            "observacao": ("Decisão interna do Constela: a conta aposentada "
                           "continua existindo na plataforma externa.")}


@router.post("/identidades/{plataforma}/reativar", response_model=dict)
def reativar_identidade(
    plataforma: str,
    corpo: ReativarIdentidadeIn,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Desfaz uma aposentadoria — só quando isso não deixa duas contas efetivas.

    D10 (risco V): reativar uma conta que já é a identidade efetiva de um aluno de
    OUTRA escola do Constela faria a conta valer nas duas — e a coleta seguinte da
    outra escola mandaria a criança de lá para a revisão. Só o Admin Global
    reativa (403 para a gestão da escola), com ``avisos`` na resposta e auditoria
    ``identidade.reativacao_outra_escola_confirmada``; a outra escola não muda."""
    bloquear_escola_para_importacao(db, escola_id)
    try:
        r = identidade_efetiva.reativar(
            db, escola_id, aluno_id=corpo.aluno_id, plataforma=plataforma,
            id_externo=corpo.id_externo, motivo=corpo.motivo, usuario_id=usuario.id,
            admin_global=bool(usuario.is_global))
    except identidade_efetiva.ErroIdentidade as exc:
        db.rollback()
        raise HTTPException(_status_erro_identidade(exc), str(exc)) from exc
    db.commit()
    return r.como_dict()


def _status_erro_identidade(exc: "identidade_efetiva.ErroIdentidade") -> int:
    """403 só para a trava do D10 (conta efetiva em outra escola, sem Admin
    Global); as demais validações continuam 400."""
    if exc.codigo == identidade_efetiva.CODIGO_CONTA_DE_OUTRA_ESCOLA:
        return status.HTTP_403_FORBIDDEN
    return status.HTTP_400_BAD_REQUEST


@router.post("/revisoes/{revisao_id}/descartar", response_model=RevisaoIdentidadeOut)
def descartar_revisao(
    revisao_id: int,
    corpo: DescartarRevisaoIn,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """O gestor decide que estes dados NÃO devem ir para ninguém (linha de teste,
    aluno que não é da escola…). Nada é associado nem criado; fica auditado. Se a
    mesma linha voltar numa importação futura, abre uma pendência nova."""
    rev = _revisao_da_escola(db, escola_id, revisao_id)
    if rev.status != "pendente":
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Esta revisão já está {rev.status}.")
    rev.status = "descartada"
    rev.resolvida_por_id = usuario.id
    rev.resolvida_em = agora()
    rev.resolucao = {"acao": "descartar", "motivo": corpo.motivo.strip()}
    registrar(db, "identidade.revisao_descartada", escola_id=escola_id,
              usuario_id=usuario.id, entidade="revisao_identidade", entidade_id=rev.id,
              detalhes={"revisao_id": rev.id, "plataforma": rev.plataforma,
                        "motivo": rev.motivo, "justificativa": corpo.motivo.strip()})
    db.commit()
    db.refresh(rev)
    return _revisao_out(rev)


@router.get("", response_model=list[ImportacaoOut])
def listar(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
):
    linhas = db.execute(
        select(Importacao, Usuario.nome)
        .outerjoin(Usuario, Importacao.usuario_id == Usuario.id)
        .where(Importacao.escola_id == escola_id)
        .order_by(Importacao.id.desc())
        .limit(100)
    ).all()
    saida = []
    for importacao, usuario_nome in linhas:
        item = ImportacaoOut.model_validate(importacao)
        item.usuario_nome = usuario_nome
        saida.append(item)
    return saida
