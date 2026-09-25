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
from datetime import datetime, time as hora_zero, timedelta, timezone
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
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.database import bloquear_escola_para_importacao, get_db
from app.core.deps import escola_autorizada, exigir_papeis
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
    DescartarRevisaoIn,
    ResolucaoRevisaoOut,
    ResolverRevisaoIn,
    RevisaoIdentidadeOut,
)
from app.services import identidade_aluno as ida
from app.services import importacao as svc
from app.services import lista_piloto, matching, matriculas, perfis_pdf, planilhas
from app.services import dificuldade_livro, professores, push, scoring
from app.services import triagem_revisoes
from app.services.audit import registrar
from app.models.base import agora

router = APIRouter(prefix="/escolas/{escola_id}/importacoes", tags=["Importações"])

logger = logging.getLogger("constela.importacao")


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


def _snapshot_atual(db: Session, escola_id: int, aluno_id: int, modelo):
    # Ordena por data_referencia (id desempata): importar um relatório de um
    # período ANTIGO (backfill mensal do Matific) não pode virar o "estado
    # atual" só por ter id maior.
    return db.execute(
        select(modelo)
        .where(modelo.escola_id == escola_id, modelo.aluno_id == aluno_id)
        .order_by(modelo.data_referencia.desc(), modelo.id.desc())
        .limit(1)
    ).scalar_one_or_none()


# Sentinela: "não pré-carregado — consulte o snapshot você mesmo".
_SEM_PRECARGA = object()


def _mapa_snapshot_atual(db: Session, escola_id: int, aluno_ids, modelo) -> dict:
    """Último snapshot (por data_referencia, id) de CADA aluno, numa ÚNICA
    consulta. Equivale a chamar _snapshot_atual por aluno, sem o N+1: ordena
    ascendente e o último visto por aluno é o mais recente. Como a sessão usa
    autoflush=False, é semanticamente idêntico ao SELECT por aluno."""
    ids = list(aluno_ids)
    if not ids:
        return {}
    mapa: dict = {}
    for snap in db.execute(
        select(modelo)
        .where(modelo.escola_id == escola_id, modelo.aluno_id.in_(ids))
        .order_by(modelo.data_referencia.asc(), modelo.id.asc())
    ).scalars():
        mapa[snap.aluno_id] = snap
    return mapa


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

    # Rejeita corpos gigantes pelo Content-Length antes de ler o arquivo.
    declarado = request.headers.get("content-length")
    if declarado and declarado.isdigit() and int(declarado) > TAMANHO_MAXIMO + 1_000_000:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            "Arquivo acima de 10 MB.")

    arquivo_token = None
    arquivo_nome = None
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
                # demais requests durante a leitura da planilha.
                analise = await run_in_threadpool(
                    planilhas.analisar_planilha,
                    conteudo, plataforma, nome_arquivo=arquivo_nome or "")
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
            arquivo_token = _guardar_temporario(conteudo, "xlsx")
            tipo = "xlsx"
        elif eh_pdf:
            _limpar_temporarios_orfaos()
            try:
                # Perfis posicionais (formatos reais) com as 4 estratégias
                # genéricas de texto como rede de segurança.
                # Parsing CPU-bound (pdfplumber/pypdf) fora do event loop.
                analise = await run_in_threadpool(
                    perfis_pdf.analisar_pdf, conteudo, plataforma,
                    nome_arquivo=arquivo_nome or "")
            except HTTPException:
                raise  # mensagem útil do parser genérico chega ao usuário
            except Exception as exc:
                # NÃO logar o filename (nome do aluno = PII de menor) — ver acima.
                logger.exception("Falha ao analisar PDF (escola %s, tipo pdf, %d bytes)",
                                 escola_id, len(conteudo))
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "Não foi possível ler o PDF. O arquivo está íntegro?") from exc
            arquivo_token = _guardar_temporario(conteudo, "pdf")
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
    if analise.linhas:
        # PRÉVIA = CONFIRMAÇÃO: a mesma porta única de identidade do /confirmar.
        svc.casar_nomes(db, escola_id, analise.linhas, plataforma=analise.plataforma,
                        turma_padrao=analise.turma_detectada)

    nomes_unicos = {svc.chave_nome(l.nome) for l in analise.linhas if l.nome}
    return AnaliseOut(
        plataforma=analise.plataforma,
        formato=analise.formato,
        tipo=tipo,
        arquivo_token=arquivo_token,
        arquivo_nome=arquivo_nome,
        estrategia=analise.estrategia,
        mensagem_deteccao=analise.mensagem_deteccao,
        turma_detectada=analise.turma_detectada,
        origem_nome=analise.origem_nome,
        periodo_inicio=analise.periodo_inicio,
        periodo_fim=analise.periodo_fim,
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


def _ano_escolar_do_nome(nome: str) -> str:
    """Deriva a série do nome da turma: "5 ANO B MANHA ANUAL" → "5º Ano"."""
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
    lados de toda comparação — se um lado viesse cru ("123.100.026-0") e o outro
    normalizado ("1231000260"), o motor leria RAs "divergentes" e vetaria o
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
                    plataforma: str | None = None,
                    ctx: "ida.Contexto | None" = None,
                    revisoes: "ida.ColetorRevisoes | None" = None,
                    usuario_id: int | None = None) -> Aluno | None:
    """Aplica à linha a decisão da PORTA ÚNICA de identidade
    (``identidade_aluno.decidir``) — a MESMA que a prévia mostrou:

      * ASSOCIAR → devolve a ficha e grava a identidade externa (UUID do Matific /
        studentId do Elefante) nela, para a próxima sincronização casar direto;
      * REVISAR  → NÃO associa e NÃO cria: a linha vai INTEIRA para a fila de
        revisão (``RevisaoIdentidade``), com candidatos e motivo, e é devolvida em
        ``ignorados`` (a sync não avança o cursor desse aluno);
      * CRIAR    → só quando não há candidato algum: cria a ficha na turma da sala
        (decidida sem chute) e grava a identidade externa já na criação.

    ``ctx``/``revisoes`` vêm do /confirmar (estado carregado 1x, fila gravada no
    fim); chamado avulso, carrega o próprio estado e grava a revisão na hora."""
    dados = getattr(linha, "dados", None) or {}
    if ctx is None:
        ctx = ida.carregar_contexto(db, escola_id, ano)
    turmas_novas = turmas_novas if turmas_novas is not None else {}

    turma_explicita = None
    if linha.aluno_id is None and linha.criar_em_turma_id is not None:
        turma_explicita = db.get(Turma, linha.criar_em_turma_id)
        if turma_explicita is None or turma_explicita.escola_id != escola_id:
            avisos.append(f"Linha “{linha.nome}”: turma inválida — ignorada.")
            return None
    turma_nome = (turma_explicita.nome if turma_explicita is not None
                  else getattr(linha, "criar_em_turma_nome", None)
                  or dados.get("turma_relatorio") or "")
    ident = ida.linha_de_dados(
        linha.nome, dados, plataforma=plataforma, turma_nome=str(turma_nome),
        turma_id=turma_explicita.id if turma_explicita is not None else None,
        aluno_id=linha.aluno_id)
    if getattr(linha, "numero_chamada", None) is not None:
        ident = replace(ident, chamada=linha.numero_chamada)
    if linha.aluno_id is None and not svc.tokens_nome(linha.nome):
        avisos.append(f"Linha “{linha.nome}”: sem nome utilizável — ignorada.")
        return None
    decisao = ida.decidir(ctx, ident)

    if decisao.acao == ida.IGNORAR:
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
        _vincular_identidade(db, escola_id, aluno.id, ident.plataforma, ident.id_externo,
                             ctx=ctx, usuario_id=usuario_id)
        _marcar_via(linha, decisao.via)
        chave_log = (svc.chave_nome(linha.nome), aluno.id)
        if (decisao.via not in ("identidade", "exato", "explicito", "ra", "revisao")
                and (criados is None or chave_log not in criados)):
            # AUDITORIA (regra §17): vínculo decidido pelo motor sem nome idêntico
            # (abreviação, parcial estrutural, grafia segura, identificador).
            turma = ctx.turma_do_aluno(aluno.id)
            registrar(db, "aluno.vinculado_auto", escola_id=escola_id,
                      usuario_id=usuario_id, entidade="aluno", entidade_id=aluno.id,
                      detalhes={"origem": linha.nome, "aluno": aluno.nome,
                                "turma": turma.nome if turma is not None else turma_nome,
                                "confianca": "alta", "candidatos": 1,
                                "correspondencia": decisao.via,
                                "motivo": "único candidato plausível na mesma sala"})
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
    aluno = Aluno(escola_id=escola_id, nome=linha.nome.strip())
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


def _marcar_via(linha, via: str) -> None:
    """Registra na linha COMO o aluno foi identificado (a sincronização só move de
    turma quem veio pela identidade externa já vinculada)."""
    try:
        linha.via = via
    except (AttributeError, ValueError, TypeError):
        pass


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
        if cands:
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


_MOTIVOS_DE_TURMA = frozenset({"sem_turma", "turma_nao_cadastrada", "turma_ambigua"})


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
    de sala sem supervisão exige certeza."""
    alvo = svc.tokens_turma(klass_nome)
    if not alvo:
        return None
    candidatas: list[tuple[int, Turma]] = []
    for turma in db.execute(
        select(Turma).where(Turma.escola_id == escola_id,
                            Turma.ano_letivo == ano)).scalars():
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
                               resolvidos: dict, avisos: list[str]) -> int:
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
      só registra um aviso para revisão humana.

    Devolve quantos alunos foram movidos."""
    movidos = 0
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
        turma_nome = str((linha.dados or {}).get("turma_relatorio") or "").strip()
        if not turma_nome:
            continue
        matricula = db.execute(select(Matricula).where(
            Matricula.aluno_id == aluno.id,
            Matricula.ano_letivo == ano)).scalars().first()
        if matricula is None:
            continue
        atual = db.get(Turma, matricula.turma_id)
        # Mesma turma (tokens série+letra) → nada a fazer (evita turma-fantasma).
        if atual is not None and matriculas.overlap_turma(
                svc.tokens_turma(atual.nome), svc.tokens_turma(turma_nome)) >= 2:
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
        antiga = atual.nome if atual is not None else "—"
        matricula.turma_id = nova.id
        db.flush()
        registrar(db, "matricula.turma_sincronizada", escola_id=escola_id,
                  entidade="aluno", entidade_id=aluno.id,
                  detalhes={"de": antiga, "para": nova.nome, "origem": "matific"})
        avisos.append(f"{aluno.nome}: movido de “{antiga}” para “{nova.nome}” "
                      "(mudança de turma detectada no Matific).")
        movidos += 1
    return movidos


def _importar_matific(db, escola_id, importacao, aluno, dados, data_referencia,
                      anterior=_SEM_PRECARGA):
    # Cada relatório do Matific traz um subconjunto das métricas: o PDF de
    # estrelas tem "estrelas"; o Excel por turma NÃO tem. Preservamos o valor
    # anterior de cada campo AUSENTE — assim os dois relatórios se COMPLEMENTAM
    # (nunca zeram um campo que outro relatório já preencheu).
    # `anterior` pode vir pré-carregado em lote pelo /confirmar (evita o N+1).
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
    if anterior is not None and _mesmo_dia(anterior.data_referencia, data_referencia):
        anterior.atividades = atividades
        anterior.estrelas = estrelas
        anterior.pontuacao_media = media
        anterior.importacao_id = importacao.id
        return
    db.add(SnapshotMatific(
        escola_id=escola_id, aluno_id=aluno.id, importacao_id=importacao.id,
        data_referencia=data_referencia,
        atividades=atividades, estrelas=estrelas, pontuacao_media=media,
    ))


def _sem_fuso(momento):
    return momento.replace(tzinfo=None) if momento.tzinfo else momento


def _mesmo_dia(a, b) -> bool:
    """True se dois instantes caem no MESMO dia (ignora fuso). Usado para tornar
    reimportações do mesmo dia idempotentes: em vez de empilhar um segundo ponto
    no histórico diário, o snapshot do dia é atualizado no lugar."""
    if a is None or b is None:
        return False
    return _sem_fuso(a).date() == _sem_fuso(b).date()


def _importar_matific_periodo(db, escola_id, importacao, aluno, dados,
                              inicio, fim, serie, contadores):
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
    if mesmo_fim is not None:
        mesmo_fim.atividades = novo_ativ
        mesmo_fim.estrelas = novo_estrelas
        mesmo_fim.pontuacao_media = novo_media
        mesmo_fim.importacao_id = importacao.id
    else:
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


def _importar_elefante_resumo(db, escola_id, importacao, aluno, dados, data_referencia,
                              anterior=_SEM_PRECARGA, avisos: list | None = None):
    # `anterior` pode vir pré-carregado em lote pelo /confirmar (evita o N+1).
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
    if anterior is not None and _mesmo_dia(anterior.data_referencia, data_referencia):
        anterior.livros_unicos = livros_unicos
        anterior.tempo_leitura_min = tempo
        anterior.questoes_tentativas = tentativas
        anterior.questoes_acertos = acertos
        anterior.livros_por_nivel = por_nivel
        anterior.importacao_id = importacao.id
        return
    db.add(SnapshotElefante(
        escola_id=escola_id, aluno_id=aluno.id, importacao_id=importacao.id,
        data_referencia=data_referencia,
        livros_unicos=livros_unicos,
        tempo_leitura_min=tempo,
        questoes_tentativas=tentativas,
        questoes_acertos=acertos,
        livros_por_nivel=por_nivel,
    ))


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


def _importar_elefante_leituras(db, escola_id, importacao, aluno, linhas,
                                data_referencia, avisos, catalogo, ja_lidos,
                                codigos_faixa):
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
    ingerir_eventos(db, aluno.id, "elefante", eventos)

    # Snapshot derivado do total de leituras registradas. O nível de CADA
    # leitura é o CONGELADO (``Leitura.nivel_codigo``, gravado na importação que
    # a criou); só leitura anterior a esta versão (nível nulo) cai no nível atual
    # do livro. Assim renivelar um livro depois não muda, sozinha, a
    # distribuição por nível do aluno numa reimportação.
    leituras = db.execute(
        select(func.coalesce(Leitura.nivel_codigo, Livro.nivel_codigo))
        .select_from(Leitura)
        .join(Livro, Leitura.livro_id == Livro.id)
        .where(Leitura.aluno_id == aluno.id)
    ).scalars().all()
    por_nivel: dict[str, int] = {}
    for codigo in leituras:
        por_nivel[codigo] = por_nivel.get(codigo, 0) + 1

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
    anterior = _snapshot_atual(db, escola_id, aluno.id, SnapshotElefante)
    # O resumo do relatório individual COMPLEMENTA o tempo de leitura de quem
    # ainda não tem snapshot; nunca rebaixa o valor vindo do relatório da turma.
    tempo_relatorio = max(
        (_num(l.dados.get("tempo_leitura_min", 0) or 0, int) for l in linhas), default=0)
    db.add(SnapshotElefante(
        escola_id=escola_id, aluno_id=aluno.id, importacao_id=importacao.id,
        data_referencia=data_referencia,
        # O contador da plataforma (relatório da turma) pode ser maior que o
        # histórico listado — o detalhamento individual nunca rebaixa a conta.
        livros_unicos=max(len(leituras),
                          anterior.livros_unicos if anterior else 0),
        tempo_leitura_min=max(anterior.tempo_leitura_min if anterior else 0,
                              tempo_relatorio),
        questoes_tentativas=anterior.questoes_tentativas if anterior else 0,
        questoes_acertos=anterior.questoes_acertos if anterior else 0,
        livros_por_nivel=por_nivel,
    ))


def _finalizar_importacao(db: Session, escola_id: int, *, corpo: str) -> int:
    """Fecha uma importação: recalcula notas/rankings, invalida o cache do painel
    público e notifica a escola. Ponto ÚNICO de finalização — usado pelo
    /confirmar (recalcular=true) e pelo /recalcular (fim do lote), para os dois
    nunca divergirem no que fazem ao terminar."""
    n = scoring.recalcular_escola(db, escola_id)
    _pos_commit_importacao(db, escola_id, corpo=corpo)
    return n


def _pos_commit_importacao(db: Session, escola_id: int, *, corpo: str) -> None:
    """Efeitos que NÃO pertencem à transação: cache em memória do processo e push
    para os aparelhos. Ficam DEPOIS do commit de propósito — notificar antes de
    a transação fechar avisaria sobre dado que pode nem existir, e o próprio
    ``notificar_escola`` commita ao limpar token morto (o que abriria a transação
    do chamador no meio). Não é reversível por rollback: é melhor esforço."""
    from app.routers.publico import invalidar_cache_painel

    invalidar_cache_painel(escola_id)  # painel público reflete os novos dados
    push.notificar_escola(
        db, escola_id, titulo="Novos dados no Constela Edu",
        corpo=corpo, dados={"tela": "ranking"})


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
    direto e commita uma vez só."""
    nucleo = _confirmar_sem_commit(dados=dados, escola_id=escola_id,
                                   usuario=usuario, db=db)
    db.commit()

    # No modo lote, o recálculo/push acontece UMA vez ao final (via /recalcular),
    # não a cada arquivo — economiza dezenas de recálculos numa turma inteira.
    if dados.recalcular:
        plataforma_nome = "Matific" if dados.plataforma == "matific" else "Elefante Letrado"
        _finalizar_importacao(
            db, escola_id,
            corpo=f"{nucleo.qtd_alunos} alunos atualizados na {plataforma_nome}. "
                  "As notas já foram recalculadas.")
        mensagem = (f"Importação concluída: {nucleo.qtd_alunos} alunos atualizados. "
                    "Notas recalculadas automaticamente.")
    else:
        mensagem = f"{nucleo.qtd_alunos} aluno(s) importado(s)."

    return ImportacaoResultadoOut(
        mensagem=mensagem,
        importacao_id=nucleo.importacao_id,
        qtd_alunos=nucleo.qtd_alunos,
        qtd_erros=nucleo.qtd_erros,
        avisos=nucleo.avisos,
        ignorados=nucleo.ignorados,
        qtd_revisoes=nucleo.qtd_revisoes,
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


def _confirmar_sem_commit(
    *,
    dados: ImportacaoConfirm,
    escola_id: int,
    usuario: Usuario,
    db: Session,
) -> _NucleoImportacao:
    """TODO o trabalho do /confirmar, SEM commit e SEM efeito externo.

    É aqui que a importação acontece: identidade, turmas, snapshots, leituras,
    eventos e a fila de revisão. Nada de ``db.commit()`` — quem chama decide
    quando fechar. Assim o ``/resolver`` aplica várias pendências irmãs e fecha
    tudo numa transação única: falhou no meio, nada fica."""
    inicio = time.monotonic()
    from app.models import Escola

    escola = db.get(Escola, escola_id)
    if escola is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Escola não encontrada.")
    if not dados.linhas:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nenhuma linha para importar.")

    # Serializa importações concorrentes desta escola. A trava (Postgres; no-op
    # em SQLite) garante que o 2º envio sobreposto leia o que o 1º commitou;
    # combinada com o re-casamento contra o banco — turma via índice único +
    # _inserir_turma, aluno via _aluno_existente_na_turma — um double-click/retry
    # do MESMO relatório reaproveita em vez de duplicar turmas/alunos.
    bloquear_escola_para_importacao(db, escola_id)

    data_referencia = dados.data_referencia or datetime.now(timezone.utc)
    avisos: list[str] = []
    # O que a fila de revisão guarda para reaplicar a linha depois (mesmo pipeline).
    contexto_revisao = {
        "tipo": dados.tipo,
        "data_referencia": data_referencia.isoformat(),
        "periodo_inicio": dados.periodo_inicio.isoformat() if dados.periodo_inicio else "",
        "periodo_fim": dados.periodo_fim.isoformat() if dados.periodo_fim else "",
    }

    # Intervalo do relatório (Matific "Intervalo de datas"): o fim impresso é
    # o limite EXCLUSIVO do leaderboard — o snapshot é datado na véspera
    # (23:59:59), caindo dentro do mês/semana a que os dados pertencem.
    periodo_inicio = periodo_fim = None
    if (dados.plataforma == "matific"
            and dados.periodo_inicio is not None and dados.periodo_fim is not None):
        periodo_inicio = dados.periodo_inicio.replace(tzinfo=None)
        periodo_fim = dados.periodo_fim.replace(tzinfo=None)
        if periodo_fim.time() == hora_zero(0, 0):
            periodo_fim -= timedelta(seconds=1)
        # Período EM ANDAMENTO (relatório do mês corrente): o snapshot é
        # datado agora, nunca no futuro — uma data futura ficaria acima de
        # qualquer edição manual feita depois, escondendo-a dos rankings.
        agora_ref = datetime.now(timezone.utc).replace(tzinfo=None)
        if periodo_fim > agora_ref:
            periodo_fim = agora_ref
        if periodo_fim <= periodo_inicio:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Intervalo de datas do relatório inválido.")
        data_referencia = periodo_fim

    # Move o arquivo original de /temporarios para a pasta definitiva (§15).
    # arquivo_token e arquivo_nome vêm do cliente: ambos são saneados contra
    # path traversal antes de tocar o disco (nunca escapar de UPLOADS_DIR).
    arquivo_final = None
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
            destino.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(origem), str(destino))
            arquivo_final = f"uploads/{dados.plataforma}/{nome}"

    importacao = Importacao(
        escola_id=escola_id, usuario_id=usuario.id,
        plataforma=dados.plataforma, tipo=dados.tipo,
        arquivo_original=arquivo_final or dados.arquivo_nome,
        status="concluida",
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
    coletor = ida.ColetorRevisoes(
        formato=dados.formato, contexto=contexto_revisao,
        origem="sincronizacao" if getattr(dados, "sincronizar_turma", False) else "importacao",
        importacao_id=importacao.id)
    for linha in dados.linhas:
        aluno = _resolver_aluno(db, escola_id, escola.ano_letivo_ativo, linha,
                                avisos, criados, turmas_novas,
                                permitir_criar_turma=getattr(
                                    dados, "permitir_criar_turma", True),
                                plataforma=dados.plataforma, ctx=ctx_identidade,
                                revisoes=coletor, usuario_id=usuario.id)
        if aluno is None:
            chave_ign = svc.chave_nome(linha.nome)
            if chave_ign not in ignorados:
                ignorados.append(chave_ign)
            continue
        resolvidos.setdefault(aluno.id, (aluno, []))[1].append(linha)
    revisoes_gravadas = _gravar_revisoes(db, escola_id, coletor, usuario.id)

    # MUDANÇA AUTOMÁTICA DE TURMA (só na sync automática do Matific): vincula o
    # UUID e move a matrícula de quem trocou de sala. Antes do recálculo para o
    # ranking já refletir a turma nova.
    if getattr(dados, "sincronizar_turma", False) and dados.plataforma == "matific" \
            and resolvidos:
        _sincronizar_turma_matific(
            db, escola_id, escola.ano_letivo_ativo, resolvidos, avisos)

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
    # o valor certo (aluno sem snapshot anterior).
    anteriores: dict = {}
    if resolvidos:
        if dados.plataforma == "matific" and periodo_inicio is None:
            anteriores = _mapa_snapshot_atual(db, escola_id, resolvidos.keys(), SnapshotMatific)
        elif dados.plataforma != "matific" and dados.formato != "leituras":
            anteriores = _mapa_snapshot_atual(db, escola_id, resolvidos.keys(), SnapshotElefante)

    # PERFORMANCE das leituras (Elefante): catálogo de livros, faixas de nível e
    # "já lidos" carregados UMA vez para o arquivo inteiro — antes eram relidos
    # por aluno (~190× numa escola de 10 turmas), o gargalo da sync de ~15 min.
    cat_livros = cod_faixa = ja_lidos_map = None
    if dados.formato == "leituras" and resolvidos:
        cat_livros = _catalogo_livros(db, escola_id)
        cod_faixa = _codigos_faixa_escola(db, escola_id)
        ja_lidos_map = _ja_lidos_por_aluno(db, [a.id for a, _ in resolvidos.values()])

    for aluno, linhas_aluno in resolvidos.values():
        if dados.plataforma == "matific" and periodo_inicio is not None:
            _importar_matific_periodo(db, escola_id, importacao, aluno,
                                      linhas_aluno[-1].dados,
                                      periodo_inicio, periodo_fim,
                                      series.get(aluno.id, []), contadores)
        elif dados.plataforma == "matific":
            _importar_matific(db, escola_id, importacao, aluno,
                              linhas_aluno[-1].dados, data_referencia,
                              anterior=anteriores.get(aluno.id))
        elif dados.formato == "leituras":
            _importar_elefante_leituras(db, escola_id, importacao, aluno,
                                        linhas_aluno, data_referencia, avisos,
                                        cat_livros, ja_lidos_map.get(aluno.id, set()),
                                        cod_faixa)
        else:
            _importar_elefante_resumo(db, escola_id, importacao, aluno,
                                      linhas_aluno[-1].dados, data_referencia,
                                      anterior=anteriores.get(aluno.id), avisos=avisos)

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
    return conteudo, nome


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
    analise = await run_in_threadpool(lista_piloto.analisar_matriculas, conteudo, nome)
    escola = db.get(Escola, escola_id)
    if escola is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Escola não encontrada.")
    ano = escola.ano_letivo_ativo
    existentes = {
        _chave_turma(t.nome) for t in db.execute(
            select(Turma).where(Turma.escola_id == escola_id, Turma.ano_letivo == ano)
        ).scalars()
    }
    turmas = [
        MatriculaTurmaOut(
            nome=t.nome, ano_escolar=t.ano_escolar, turno=t.turno,
            professor=t.professor, sed=t.sed, total_alunos=len(t.alunos),
            ja_existe=_chave_turma(t.nome) in existentes,
            exemplos=[a.nome for a in t.alunos[:4]],
        )
        for t in analise.turmas
    ]
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
        turmas=turmas, avisos=analise.avisos,
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


def _resolver_turmas(db: Session, escola_id: int, ano: int,
                     turmas_analise) -> tuple[list[Turma], int, int]:
    """Cria as turmas que faltam (chave insensível a º/acento/caixa) e devolve,
    na ordem da análise, a Turma resolvida de cada uma + quantas turmas foram
    criadas + quantas CONTAS de professor foram criadas automaticamente."""
    turmas_por_nome: dict[str, Turma] = {}
    for t in db.execute(select(Turma).where(Turma.escola_id == escola_id,
                                            Turma.ano_letivo == ano)).scalars():
        turmas_por_nome.setdefault(_chave_turma(t.nome), t)
    criadas = 0
    profs_criados = 0
    resolvidas: list[Turma] = []
    for t in turmas_analise:
        chave = _chave_turma(t.nome)
        turma = turmas_por_nome.get(chave)
        if turma is None:
            turma, criada = _inserir_turma(
                db, escola_id, ano, t.nome, t.ano_escolar, turno=t.turno,
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
    desfechos — REUSAR, REVISAR (não cria, não altera, avisa) e CRIAR."""
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
        if parsed.ficha:
            existente.ficha = {**(existente.ficha or {}), **parsed.ficha}
        if existente.status != "ativo":
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
    analise = await run_in_threadpool(lista_piloto.analisar_matriculas, conteudo, nome)
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
        db, escola_id, ano, analise.turmas)
    linhas = [(resolvidas[i], parsed)
              for i, t in enumerate(analise.turmas) for parsed in t.alunos]

    # FASE 1 — identidade + matrícula, linha a linha, pela PORTA ÚNICA.
    persistido = _persistir_linhas(db, escola_id, ano, usuario, linhas, estado)
    alunos_criados = persistido.criados
    alunos_atualizados = persistido.atualizados
    alunos_vinculados = persistido.vinculados
    avisos.extend(persistido.avisos)

    # FASE 2 — reconciliação incremental: quem saiu da lista vira "fora da lista
    # piloto" (nunca apagado). Escopo = SÓ as turmas enviadas neste arquivo, para
    # que subir uma turma só não afete as demais. Idempotente.
    turmas_import = {t.id for t in resolvidas}
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
                        "alunos_fora_lista": alunos_fora_lista})
    db.commit()

    scoring.recalcular_escola(db, escola_id)
    from app.routers.publico import invalidar_cache_painel
    invalidar_cache_painel(escola_id)
    extra = (f" {alunos_vinculados} cadastro(s) de importação anterior recebeu(ram) "
             "o nome completo.") if alunos_vinculados else ""
    if profs_criados:
        extra += (f" {profs_criados} professor(es) ganharam conta de acesso "
                  "automática (usuário = NomeSobrenome, senha = Primeiro nome + 123 "
                  "— peça para trocarem no primeiro acesso).")
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

def _revisao_out(rev: RevisaoIdentidade, triagem: dict | None = None) -> RevisaoIdentidadeOut:
    saida = RevisaoIdentidadeOut.model_validate(rev)
    saida.motivo_texto = ida.MOTIVOS.get(rev.motivo, rev.motivo)
    saida.triagem = triagem
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
                          RevisaoIdentidade.id.desc()).limit(500)).scalars().all()
    # Cada pendência vem com a TRIAGEM: dá para encerrar com segurança, e por quê.
    # Só leitura e determinística — não decide nada, apenas explica.
    triagens: dict[int, dict] = {}
    if revisoes:
        ctx = ida.carregar_contexto(db, escola_id)
        triagens = {rid: t.como_dict() for rid, t in triagem_revisoes.triar_revisoes(
            ctx, list(revisoes)).items()}
    return [_revisao_out(r, triagens.get(r.id)) for r in revisoes]


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
    quem vale é o mais recente — que já está no banco."""
    if rev.formato == "leituras":
        return None
    modelo = SnapshotMatific if rev.plataforma == "matific" else SnapshotElefante
    snap = _snapshot_atual(db, escola_id, aluno_id, modelo)
    if snap is None:
        return None                      # nada gravado: o congelado é o que há
    congelada_txt = (rev.contexto or {}).get("data_referencia") or ""
    atual_txt = snap.data_referencia.isoformat() if snap.data_referencia else None
    base = {"formato": rev.formato, "plataforma": rev.plataforma,
            "data_congelada": congelada_txt or None, "data_snapshot_atual": atual_txt}
    try:
        congelada = datetime.fromisoformat(congelada_txt) if congelada_txt else None
    except ValueError:
        congelada = None
    if congelada is None:
        # Sem data, o pipeline gravaria com a data de HOJE e a linha velha viraria
        # o estado atual. É o pior caso: nunca reaplicar.
        return {**base, "motivo": "data_referencia_ausente"}
    atual = _sem_fuso(snap.data_referencia)
    congelada = _sem_fuso(congelada)
    if _mesmo_dia(snap.data_referencia, congelada):
        # Mesmo dia: o pipeline atualizaria o retrato NO LUGAR, e o valor novo
        # desapareceria sem deixar linha no histórico. É o caso mais perigoso,
        # por isso é diagnosticado ANTES do simples "mais recente".
        return {**base, "motivo": "mesmo_dia_do_snapshot_atual"}
    if atual > congelada:
        return {**base, "motivo": "snapshot_mais_recente"}
    return None


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
    Nunca funde fichas."""
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
        aluno = Aluno(escola_id=escola_id, nome=rev.nome_recebido.strip())
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
        motivo_superado = _retrato_superado(db, escola_id, aluno.id, r)
        if motivo_superado is None:
            com_dados.append(r)
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
    for r in com_dados:
        conf = _confirmacao_da_revisao(r, aluno.id, recalcular=False)
        nucleo = _confirmar_sem_commit(dados=conf, escola_id=escola_id,
                                       usuario=usuario, db=db)
        importacoes.append(nucleo.importacao_id)
        avisos.extend(nucleo.avisos)

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
        registrar(db, "identidade.revisao_resolvida", escola_id=escola_id,
                  usuario_id=usuario.id, entidade="aluno", entidade_id=aluno.id,
                  detalhes={"revisao_id": r.id, "plataforma": r.plataforma,
                            "formato": r.formato, "motivo": r.motivo, "acao": acao,
                            "nome_recebido": r.nome_recebido,
                            "dados_superados": superadas.get(r.id),
                            "candidatos": [c.get("aluno_id") for c in (r.candidatos or [])]})
    db.commit()                      # <- ÚNICO commit de todo o fluxo

    # DEPOIS do commit: cache do painel e push. Fora da transação de propósito —
    # avisar a escola sobre dado que ainda pode sofrer rollback seria mentira, e
    # o próprio push commita ao limpar token morto.
    if com_dados:
        _pos_commit_importacao(
            db, escola_id,
            corpo=f"{aluno.nome} teve os dados da plataforma atualizados. "
                  "As notas já foram recalculadas.")
    db.refresh(rev)
    return ResolucaoRevisaoOut(
        revisao=_revisao_out(rev), aluno_id=aluno.id,
        revisoes_resolvidas=[r.id for r in resolvidas], importacoes=importacoes,
        avisos=avisos)


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
