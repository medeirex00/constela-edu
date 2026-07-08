"""Importação de relatórios das plataformas (PRD §15–§16, §50–§52).

Fluxo em duas etapas: `analisar` devolve a prévia (nada é gravado) e
`confirmar` grava somente as linhas aprovadas pelo usuário, registrando
tudo em `importacoes` e guardando o arquivo original em /uploads (§15).
"""
import logging
import re
import shutil
import time
import uuid
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
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import escola_autorizada, exigir_papeis, get_usuario_atual
from app.models import (
    Aluno,
    Escola,
    Importacao,
    Leitura,
    Livro,
    Matricula,
    NivelDificuldade,
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
from app.services import importacao as svc
from app.services import lista_piloto, perfis_pdf, planilhas, push, scoring
from app.services.audit import registrar

router = APIRouter(prefix="/escolas/{escola_id}/importacoes", tags=["Importações"])

logger = logging.getLogger("constela.importacao")

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
        nome_lower = arquivo_nome.lower()
        tipo_conteudo = arquivo.content_type or ""
        # Magic bytes "%PDF-" garantem a detecção mesmo sem extensão/content-type
        # (ex.: upload mobile com nome "relatorio" e tipo genérico octet-stream).
        eh_pdf = (nome_lower.endswith(".pdf") or tipo_conteudo == "application/pdf"
                  or conteudo[:5] == b"%PDF-")
        # Planilha Excel: .xlsx/.xlsm, content-type de spreadsheet, ou um ZIP
        # ("PK") que não seja PDF — o Matific exporta o relatório por turma assim.
        eh_planilha = (not eh_pdf and (
            nome_lower.endswith((".xlsx", ".xlsm", ".xls"))
            or "spreadsheet" in tipo_conteudo
            or tipo_conteudo == "application/vnd.ms-excel"
            or conteudo[:2] == b"PK"))
        if eh_planilha:
            _limpar_temporarios_orfaos()
            try:
                analise = planilhas.analisar_planilha(
                    conteudo, plataforma, nome_arquivo=arquivo_nome or "")
            except ValueError as exc:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
            except Exception as exc:  # noqa: BLE001 — planilha inesperada
                logger.exception("Falha ao ler planilha (escola %s, arquivo %r)",
                                 escola_id, arquivo_nome)
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
                analise = perfis_pdf.analisar_pdf(conteudo, plataforma,
                                                  nome_arquivo=arquivo_nome or "")
            except HTTPException:
                raise  # mensagem útil do parser genérico chega ao usuário
            except Exception as exc:
                logger.exception("Falha ao analisar PDF (escola %s, arquivo %r)",
                                 escola_id, arquivo_nome)
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "Não foi possível ler o PDF. O arquivo está íntegro?") from exc
            arquivo_token = _guardar_temporario(conteudo, "pdf")
            tipo = "pdf"
        else:
            texto = conteudo.decode("utf-8", errors="replace")
            tipo = "texto"
            analise = svc.analisar_texto(texto, plataforma)
    elif texto and texto.strip():
        tipo = "texto"
        analise = svc.analisar_texto(texto, plataforma)
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Envie um arquivo PDF ou cole o texto do relatório.")
    if analise.linhas:
        svc.casar_nomes(db, escola_id, analise.linhas)

    nomes_unicos = {svc.normalizar_nome(l.nome) for l in analise.linhas if l.nome}
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

_RE_SERIE_NO_NOME = re.compile(r"^\s*(\d)\s*[ºo°]?\s*(?:ano)?\b", re.IGNORECASE)


def _ano_escolar_do_nome(nome: str) -> str:
    """Deriva a série do nome da turma: "5 ANO B MANHA ANUAL" → "5º Ano"."""
    par = _RE_SERIE_NO_NOME.match(nome or "")
    return f"{par.group(1)}º Ano" if par else ""


def _turma_pelo_nome(db: Session, escola_id: int, ano: int, nome: str,
                     avisos: list[str], turmas_novas: dict) -> Turma | None:
    """Acha (case-insensitive) ou CRIA a turma com o nome lido do relatório —
    o primeiro import da escola funciona sem cadastrar turmas antes."""
    nome = (nome or "").strip()
    if not nome:
        return None
    chave = nome.casefold()
    if chave in turmas_novas:
        return turmas_novas[chave]
    turma = db.execute(
        select(Turma).where(Turma.escola_id == escola_id,
                            Turma.ano_letivo == ano,
                            func.lower(Turma.nome) == chave).limit(1)
    ).scalars().first()
    if turma is None:
        turma = Turma(escola_id=escola_id, nome=nome, ano_letivo=ano,
                      ano_escolar=_ano_escolar_do_nome(nome) or nome[:20])
        db.add(turma)
        db.flush()
        registrar(db, "turma.criada", escola_id=escola_id, entidade="turma",
                  entidade_id=turma.id,
                  detalhes={"nome": nome, "origem": "importacao"})
        avisos.append(f"Turma “{nome}” criada automaticamente a partir do relatório.")
    turmas_novas[chave] = turma
    return turma


def _resolver_aluno(db: Session, escola_id: int, ano: int, linha, avisos: list[str],
                    criados: dict | None = None,
                    turmas_novas: dict | None = None) -> Aluno | None:
    if linha.aluno_id is not None:
        aluno = db.get(Aluno, linha.aluno_id)
        if aluno is None or aluno.escola_id != escola_id:
            avisos.append(f"Linha “{linha.nome}”: aluno não pertence a esta escola — ignorada.")
            return None
        return aluno

    turma = None
    if linha.criar_em_turma_id is not None:
        turma = db.get(Turma, linha.criar_em_turma_id)
        if turma is None or turma.escola_id != escola_id:
            avisos.append(f"Linha “{linha.nome}”: turma inválida — ignorada.")
            return None
    elif getattr(linha, "criar_em_turma_nome", None):
        turma = _turma_pelo_nome(db, escola_id, ano, linha.criar_em_turma_nome,
                                 avisos, turmas_novas if turmas_novas is not None else {})

    if turma is not None:
        # Cria o aluno UMA vez por (nome, turma): no relatório individual há
        # centenas de linhas (uma por livro) para o mesmo aluno — sem isto,
        # cada livro criaria um aluno duplicado.
        chave = (svc.normalizar_nome(linha.nome), turma.id)
        if criados is not None and chave in criados:
            return criados[chave]
        aluno = Aluno(escola_id=escola_id, nome=linha.nome.strip())
        db.add(aluno)
        db.flush()
        db.add(Matricula(escola_id=escola_id, aluno_id=aluno.id,
                         turma_id=turma.id, ano_letivo=ano))
        if criados is not None:
            criados[chave] = aluno
        return aluno
    avisos.append(f"Linha “{linha.nome}”: sem aluno vinculado — ignorada.")
    return None


def _importar_matific(db, escola_id, importacao, aluno, dados, data_referencia):
    # Cada relatório do Matific traz um subconjunto das métricas: o PDF de
    # estrelas tem "estrelas"; o Excel por turma NÃO tem. Preservamos o valor
    # anterior de cada campo AUSENTE — assim os dois relatórios se COMPLEMENTAM
    # (nunca zeram um campo que outro relatório já preencheu).
    anterior = _snapshot_atual(db, escola_id, aluno.id, SnapshotMatific)
    atividades = (int(dados["atividades"]) if "atividades" in dados
                  else (anterior.atividades if anterior else 0))
    estrelas = (int(dados["estrelas"]) if "estrelas" in dados
                else (anterior.estrelas if anterior else 0))
    media = (float(dados["pontuacao_media"]) if "pontuacao_media" in dados
             else (anterior.pontuacao_media if anterior else 0.0))
    db.add(SnapshotMatific(
        escola_id=escola_id, aluno_id=aluno.id, importacao_id=importacao.id,
        data_referencia=data_referencia,
        atividades=atividades, estrelas=estrelas, pontuacao_media=media,
    ))


def _sem_fuso(momento):
    return momento.replace(tzinfo=None) if momento.tzinfo else momento


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
    dobrado. Backfill fora de ordem entre períodos: o mês entra no
    histórico; reimporte os meses seguintes (em ordem) para o acumulado
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

    ativ_rel = int(dados.get("atividades", 0) or 0)
    estrelas_rel = int(dados.get("estrelas", 0) or 0)
    media_rel = float(dados.get("pontuacao_media", 0) or 0.0)

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


def _importar_elefante_resumo(db, escola_id, importacao, aluno, dados, data_referencia):
    anterior = _snapshot_atual(db, escola_id, aluno.id, SnapshotElefante)
    por_nivel = dados.get("livros_por_nivel")
    if por_nivel is None:
        # Relatório sem a coluna de níveis: preserva a distribuição conhecida
        por_nivel = anterior.livros_por_nivel if anterior else {}
    livros = dados.get("livros_unicos")
    if livros is None:
        livros = sum(por_nivel.values()) if por_nivel else (anterior.livros_unicos if anterior else 0)
    db.add(SnapshotElefante(
        escola_id=escola_id, aluno_id=aluno.id, importacao_id=importacao.id,
        data_referencia=data_referencia,
        livros_unicos=int(livros),
        tempo_leitura_min=int(dados.get("tempo_leitura_min",
                                        anterior.tempo_leitura_min if anterior else 0)),
        questoes_tentativas=int(dados.get("questoes_tentativas",
                                          anterior.questoes_tentativas if anterior else 0)),
        questoes_acertos=int(dados.get("questoes_acertos",
                                       anterior.questoes_acertos if anterior else 0)),
        livros_por_nivel=por_nivel,
    ))


def _importar_elefante_leituras(db, escola_id, importacao, aluno, linhas, data_referencia, avisos):
    """Formato "uma linha por livro concluído": registra leituras únicas (§35).

    Todo o trabalho de banco é feito EM LOTE: uma consulta para o catálogo,
    uma para as leituras existentes e um único flush no final. A versão
    anterior consultava livro-a-livro (~600 idas ao banco por arquivo), o que
    num Postgres de rede (Supabase) transformava cada relatório em minutos.
    """
    # Catálogo da escola indexado por título case-insensitive — equivale ao
    # antigo ILIKE literal (primeiro correspondente vence em caso de duplicata).
    catalogo: dict[str, Livro] = {}
    for livro in db.execute(
        select(Livro).where(Livro.escola_id == escola_id).order_by(Livro.id)
    ).scalars():
        catalogo.setdefault(livro.titulo.strip().casefold(), livro)

    ja_lidos: set[int] = set(db.execute(
        select(Leitura.livro_id).where(Leitura.aluno_id == aluno.id)
    ).scalars().all())

    vistos: set[str] = set()  # títulos já processados NESTE lote
    novas: list[Leitura] = []
    for linha in linhas:
        titulo = str(linha.dados.get("livro", "")).strip()
        nivel = str(linha.dados.get("nivel", "")).strip().upper()
        if not titulo:
            avisos.append(f"Linha {linha.nome}: livro sem título — ignorada.")
            continue
        chave = titulo.casefold()
        livro = catalogo.get(chave)
        if livro is None:
            if not nivel:
                avisos.append(f"Livro “{titulo}” é novo e veio sem nível — ignorado.")
                continue
            livro = Livro(escola_id=escola_id, titulo=titulo, nivel_codigo=nivel,
                          categoria=linha.dados.get("genero") or None)
            db.add(livro)
            catalogo[chave] = livro  # dedup dentro do lote sem flush por livro
        # Releitura no MESMO relatório (livro repetido): dedup em memória —
        # senão a UniqueConstraint derrubaria a importação (autoflush=False).
        if chave in vistos:
            avisos.append(f"“{titulo}” aparece mais de uma vez no relatório de "
                          f"{aluno.nome} — contado uma vez (§35).")
            continue
        if livro.id is not None and livro.id in ja_lidos:
            avisos.append(f"“{titulo}” já constava para {aluno.nome} — releitura não pontua (§35).")
            continue
        vistos.add(chave)
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
        novas.append((livro, quando,
                      int(tempo_livro) if tempo_livro is not None else None))

    # Persiste PRIMEIRO os livros novos (ganham id) e então grava todas as
    # leituras num único INSERT executemany — uma ida ao banco, não N.
    db.flush()
    if novas:
        from sqlalchemy import insert
        db.execute(insert(Leitura), [
            {"escola_id": escola_id, "aluno_id": aluno.id, "livro_id": livro.id,
             "data": quando, "tempo_leitura_min": tempo}
            for livro, quando, tempo in novas
        ])

    # Snapshot derivado do total de leituras registradas
    leituras = db.execute(
        select(Livro.nivel_codigo)
        .join(Leitura, Leitura.livro_id == Livro.id)
        .where(Leitura.aluno_id == aluno.id)
    ).scalars().all()
    por_nivel: dict[str, int] = {}
    for codigo in leituras:
        por_nivel[codigo] = por_nivel.get(codigo, 0) + 1

    # Avisa se algum nível de letra não está em nenhuma faixa configurada:
    # esses livros contam no total, mas não geram pontos de dificuldade nem
    # aparecem no gráfico por nível até a letra ser incluída em Métricas.
    codigos_faixa = {
        c.upper()
        for nivel in db.execute(
            select(NivelDificuldade).where(NivelDificuldade.escola_id == escola_id)
        ).scalars()
        for c in (nivel.codigos or [])
    }
    fora = sorted({c for c in por_nivel if c and c.upper() not in codigos_faixa})
    if fora:
        avisos.append(
            f"{aluno.nome}: níveis {', '.join(fora)} não estão em nenhuma faixa "
            "de dificuldade — os livros contam no total, mas não pontuam por "
            "dificuldade. Inclua essas letras em Métricas → Dificuldade.")
    anterior = _snapshot_atual(db, escola_id, aluno.id, SnapshotElefante)
    # O resumo do relatório individual COMPLEMENTA o tempo de leitura de quem
    # ainda não tem snapshot; nunca rebaixa o valor vindo do relatório da turma.
    tempo_relatorio = max(
        (int(l.dados.get("tempo_leitura_min", 0) or 0) for l in linhas), default=0)
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


@router.post("/confirmar", response_model=ImportacaoResultadoOut)
def confirmar(
    dados: ImportacaoConfirm,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    inicio = time.monotonic()
    from app.models import Escola

    escola = db.get(Escola, escola_id)
    if escola is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Escola não encontrada.")
    if not dados.linhas:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nenhuma linha para importar.")

    data_referencia = dados.data_referencia or datetime.now(timezone.utc)
    avisos: list[str] = []

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
    for linha in dados.linhas:
        aluno = _resolver_aluno(db, escola_id, escola.ano_letivo_ativo, linha,
                                avisos, criados, turmas_novas)
        if aluno is None:
            continue
        resolvidos.setdefault(aluno.id, (aluno, []))[1].append(linha)

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

    for aluno, linhas_aluno in resolvidos.values():
        if dados.plataforma == "matific" and periodo_inicio is not None:
            _importar_matific_periodo(db, escola_id, importacao, aluno,
                                      linhas_aluno[-1].dados,
                                      periodo_inicio, periodo_fim,
                                      series.get(aluno.id, []), contadores)
        elif dados.plataforma == "matific":
            _importar_matific(db, escola_id, importacao, aluno,
                              linhas_aluno[-1].dados, data_referencia)
        elif dados.formato == "leituras":
            _importar_elefante_leituras(db, escola_id, importacao, aluno,
                                        linhas_aluno, data_referencia, avisos)
        else:
            _importar_elefante_resumo(db, escola_id, importacao, aluno,
                                      linhas_aluno[-1].dados, data_referencia)

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

    registrar(db, "importacao.concluida", escola_id=escola_id, usuario_id=usuario.id,
              entidade="importacao", entidade_id=importacao.id,
              detalhes={"plataforma": dados.plataforma, "tipo": dados.tipo,
                        "alunos": importacao.qtd_alunos, "avisos": avisos})
    db.commit()

    # No modo lote, o recálculo/push acontece UMA vez ao final (via /recalcular),
    # não a cada arquivo — economiza dezenas de recálculos numa turma inteira.
    if dados.recalcular:
        scoring.recalcular_escola(db, escola_id)
        from app.routers.publico import invalidar_cache_painel
        invalidar_cache_painel(escola_id)  # painel público reflete os novos dados

        plataforma_nome = "Matific" if dados.plataforma == "matific" else "Elefante Letrado"
        push.notificar_escola(
            db, escola_id,
            titulo="Novos dados no Constela Edu",
            corpo=f"{importacao.qtd_alunos} alunos atualizados na {plataforma_nome}. "
                  "As notas já foram recalculadas.",
            dados={"tela": "ranking"},
        )
        mensagem = (f"Importação concluída: {importacao.qtd_alunos} alunos atualizados. "
                    "Notas recalculadas automaticamente.")
    else:
        mensagem = f"{importacao.qtd_alunos} aluno(s) importado(s)."

    return ImportacaoResultadoOut(
        mensagem=mensagem,
        importacao_id=importacao.id,
        qtd_alunos=importacao.qtd_alunos,
        qtd_erros=importacao.qtd_erros,
        avisos=avisos,
    )


@router.post("/recalcular", response_model=dict)
def recalcular_agora(
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Recalcula notas/rankings da escola uma única vez — usado ao final de
    uma importação em lote, depois de vários /confirmar com recalcular=false."""
    from app.routers.publico import invalidar_cache_painel

    n = scoring.recalcular_escola(db, escola_id)
    invalidar_cache_painel(escola_id)
    push.notificar_escola(
        db, escola_id, titulo="Novos dados no Constela Edu",
        corpo="Importação em lote concluída. As notas já foram recalculadas.",
        dados={"tela": "ranking"})
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


def _norm(texto: str) -> str:
    return svc.normalizar_nome(texto or "")


def _chave_turma(nome: str) -> str:
    """Chave de turma insensível a ordinal/acento/caixa: "5º Ano B" == "5 ANO B".
    normalizar_nome NÃO remove º, então turmas bifurcariam sem isto."""
    return _norm(re.sub(r"[ºª°]", "", nome or ""))


# Tokens que aparecem em QUALQUER turma e não discriminam uma da outra — ficam
# de fora do overlap, senão "1º Ano A" e "4º Ano A" pareceriam a mesma sala
# (partilham "ano" e a letra é o que importa, não a palavra).
_STOP_TURMA = {"ano", "anos", "manha", "tarde", "noite", "integral", "anual",
               "matutino", "vespertino", "noturno", "turma", "sala"}


def _overlap_turma(a: set[str], b: set[str]) -> int:
    """Tokens de turma em comum, ignorando palavras ubíquas — para "1º Ano A"
    casar com "1 ANO A MANHÃ" (série+letra) mas NÃO com "4º Ano A"."""
    return len((a & b) - _STOP_TURMA)


def _nomes_compativeis(a: str, b: str) -> bool:
    """Dois nomes podem ser a MESMA pessoa? Usado como veto ao casar por RA:
    se o RA colide mas os nomes são claramente de pessoas diferentes (ex.: RA
    placeholder), não casa. Conservador: na dúvida, considera compatível."""
    if _norm(a) == _norm(b):
        return True
    ta, tb = svc.tokens_nome(a), svc.tokens_nome(b)
    if not ta or not tb:
        return True
    if ta[0] != tb[0]:
        return False
    if svc.casa_abreviado_posicional(ta, tb) or svc.casa_abreviado_posicional(tb, ta):
        return True
    return svc._similaridade(_norm(a), _norm(b)) >= 0.6


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
    return MatriculasAnaliseOut(
        escola_detectada=analise.escola_detectada, ano_letivo=analise.ano_letivo,
        total_turmas=len(turmas), total_alunos=len(identidades),
        total_registros=analise.total_alunos,
        turmas=turmas, avisos=analise.avisos,
    )


@router.post("/matriculas/confirmar", response_model=MatriculasResultadoOut)
async def confirmar_matriculas(
    request: Request,
    escola_id: int = Depends(escola_autorizada),
    arquivo: UploadFile = File(...),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Cria as turmas que faltam e matricula os alunos (ano letivo ativo),
    gravando nº de chamada, nascimento e a ficha cadastral. Reimportar
    atualiza os existentes (casa por RA, senão por nome + turma) — não
    duplica."""
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

    def _nasc(parsed) -> date | None:
        if not parsed.data_nascimento:
            return None
        try:
            return date.fromisoformat(parsed.data_nascimento)
        except ValueError:
            return None

    # ---- Pré-carga do estado da escola (poucas consultas, tudo em memória) ----
    # order_by garante escolha determinística de por_ra quando há RA repetido.
    alunos_todos = db.execute(
        select(Aluno).where(Aluno.escola_id == escola_id)
        .order_by(Aluno.id)).scalars().all()
    alunos_por_id = {a.id: a for a in alunos_todos}
    ativos = [a for a in alunos_todos if a.status != "excluido"]
    # RA casa até com excluído (reativa em vez de duplicar); nome/abreviado, não.
    por_ra: dict[str, Aluno] = {}
    for a in alunos_todos:
        ra = lista_piloto.ra_util((a.ficha or {}).get("ra"))
        if ra:
            por_ra.setdefault(ra, a)
    matricula_ano: dict[int, Matricula] = {
        m.aluno_id: m for m in db.execute(
            select(Matricula).where(Matricula.escola_id == escola_id,
                                    Matricula.ano_letivo == ano)).scalars()
    }
    por_nome_turma: dict[tuple[str, int], Aluno] = {}
    for m in matricula_ano.values():
        alvo = alunos_por_id.get(m.aluno_id)
        if alvo is not None and alvo.status != "excluido":
            por_nome_turma[(_norm(alvo.nome), m.turma_id)] = alvo

    # Turmas de cada aluno, de QUALQUER ano — o cadastro de upload pode estar num
    # ano detectado do relatório, não no ativo. Guardamos UMA lista de tokens POR
    # turma (não a união): unir tokens de turmas diferentes fabricaria overlap
    # (série de uma + letra de outra) com uma sala em que o aluno nunca esteve.
    turma_tokens_de: dict[int, list[set[str]]] = {}
    for aid, tnome in db.execute(
        select(Matricula.aluno_id, Turma.nome)
        .join(Turma, Matricula.turma_id == Turma.id)
        .where(Matricula.escola_id == escola_id)).all():
        turma_tokens_de.setdefault(aid, []).append(svc.tokens_turma(tnome))

    # Só cadastros com dados de upload (Matific/Elefante) entram no POOL de
    # candidatos a receber o nome completo — é o escopo do recurso.
    com_upload: set[int] = set()
    for tabela in (SnapshotMatific, SnapshotElefante, Leitura):
        for (aid,) in db.execute(
            select(tabela.aluno_id).where(tabela.escola_id == escola_id).distinct()):
            com_upload.add(aid)
    pool_por_primeiro: dict[str, list[Aluno]] = {}
    for a in ativos:
        if a.id in com_upload and not lista_piloto.ra_util((a.ficha or {}).get("ra")):
            toks = svc.tokens_nome(a.nome)
            if len(toks) >= 2:
                pool_por_primeiro.setdefault(toks[0], []).append(a)

    # ---- Turmas: cria as que faltam (chave insensível a º/acento/caixa) ----
    turmas_por_nome: dict[str, Turma] = {}
    for t in db.execute(select(Turma).where(Turma.escola_id == escola_id,
                                             Turma.ano_letivo == ano)).scalars():
        turmas_por_nome.setdefault(_chave_turma(t.nome), t)
    turmas_criadas = 0
    resolvidas: list[Turma] = []
    for t in analise.turmas:
        chave = _chave_turma(t.nome)
        turma = turmas_por_nome.get(chave)
        if turma is None:
            turma = Turma(escola_id=escola_id, nome=t.nome, ano_escolar=t.ano_escolar,
                          ano_letivo=ano, turno=t.turno,
                          observacoes=(f"Nº da classe (SED): {t.sed}" if t.sed else None))
            db.add(turma)
            db.flush()
            turmas_por_nome[chave] = turma
            turmas_criadas += 1
        resolvidas.append(turma)

    linhas = [(resolvidas[i], parsed)
              for i, t in enumerate(analise.turmas) for parsed in t.alunos]

    # ---- FASE 1: casamento ABREVIADO POSICIONAL (em memória, antes de gravar) --
    # Só para linhas que NÃO casam por RA nem por nome-completo-exato na turma.
    def _casaria_forte(turma, parsed) -> bool:
        ra = lista_piloto.ra_util(parsed.ficha.get("ra"))
        if ra and ra in por_ra and _nomes_compativeis(parsed.nome, por_ra[ra].nome):
            return True
        return (_norm(parsed.nome), turma.id) in por_nome_turma

    cand_por_idx: dict[int, list[Aluno]] = {}
    linhas_por_antigo: dict[int, list[int]] = {}
    for idx, (turma, parsed) in enumerate(linhas):
        if _casaria_forte(turma, parsed):
            continue
        f = svc.tokens_nome(parsed.nome)
        if len(f) < 2:
            continue
        turma_toks = svc.tokens_turma(turma.nome)
        nasc = _nasc(parsed)
        for antigo in pool_por_primeiro.get(f[0], []):
            if not svc.casa_abreviado_posicional(svc.tokens_nome(antigo.nome), f):
                continue
            # Precisa bater com ALGUMA turma real do aluno (série+letra), não com
            # a união de turmas de anos diferentes.
            if not any(_overlap_turma(turma_toks, ts) >= 2
                       for ts in turma_tokens_de.get(antigo.id, [])):
                continue  # turma diverge → não é o mesmo aluno
            if nasc and antigo.data_nascimento and nasc != antigo.data_nascimento:
                continue  # veto por nascimento divergente
            cand_por_idx.setdefault(idx, []).append(antigo)
            linhas_por_antigo.setdefault(antigo.id, []).append(idx)

    casar_abrev: dict[int, Aluno] = {}
    for idx, cands in cand_por_idx.items():
        # Unicidade bipartida: só casa 1:1 quando a linha tem UM candidato E esse
        # candidato não abrevia nenhuma outra linha do lote. Ambíguo → cria novo.
        if len(cands) == 1 and len(linhas_por_antigo[cands[0].id]) == 1:
            casar_abrev[idx] = cands[0]
        else:
            turma, parsed = linhas[idx]
            nomes = ", ".join(sorted({c.nome for c in cands}))
            avisos.append(
                f"“{parsed.nome}” pode ser o mesmo aluno de: {nomes} (cadastro(s) "
                "de importação anterior). Criado como novo — confira em Alunos e "
                "use “Fundir alunos” se for a mesma pessoa.")

    # ---- FASE 2: gravação na ordem do arquivo (preserva 1ª ocorrência) ----
    alunos_criados = alunos_atualizados = alunos_vinculados = 0
    ja_alocado: set[int] = set()
    for idx, (turma, parsed) in enumerate(linhas):
        ra = lista_piloto.ra_util(parsed.ficha.get("ra"))
        existente = por_ra.get(ra) if ra else None
        if existente is not None and not _nomes_compativeis(parsed.nome, existente.nome):
            existente = None  # RA colide mas nome é de outra pessoa (placeholder)
        if existente is None:
            existente = por_nome_turma.get((_norm(parsed.nome), turma.id))
        if existente is None:
            existente = casar_abrev.get(idx)  # abreviado posicional inequívoco
        nasc = _nasc(parsed)

        if existente is None:
            aluno = Aluno(escola_id=escola_id, nome=parsed.nome, status="ativo",
                          numero_chamada=parsed.numero_chamada,
                          data_nascimento=nasc, ficha=dict(parsed.ficha))
            db.add(aluno)
            db.flush()
            db.add(Matricula(escola_id=escola_id, aluno_id=aluno.id,
                             turma_id=turma.id, ano_letivo=ano))
            alunos_criados += 1
            if ra:
                por_ra[ra] = aluno
            por_nome_turma[(_norm(aluno.nome), turma.id)] = aluno
            matricula_ano[aluno.id] = None
            ja_alocado.add(aluno.id)
        else:
            nome_antigo = existente.nome
            # O Excel é a fonte da verdade da identidade: nome completo vence.
            existente.nome = parsed.nome
            if nasc and existente.data_nascimento is None:
                existente.data_nascimento = nasc
            if parsed.ficha:
                existente.ficha = {**(existente.ficha or {}), **parsed.ficha}
            if existente.status != "ativo":
                existente.status = "ativo"  # consta na lista atual → reativa
            # nº de chamada e matrícula pertencem à 1ª turma em que aparece.
            if existente.id not in ja_alocado:
                if parsed.numero_chamada is not None:
                    existente.numero_chamada = parsed.numero_chamada
                mat = matricula_ano.get(existente.id)
                if mat is None and existente.id not in matricula_ano:
                    db.add(Matricula(escola_id=escola_id, aluno_id=existente.id,
                                     turma_id=turma.id, ano_letivo=ano))
                    matricula_ano[existente.id] = None
                elif mat is not None and mat.turma_id != turma.id:
                    mat.turma_id = turma.id   # a planilha é a fonte da verdade
                ja_alocado.add(existente.id)
                if ra:
                    por_ra.setdefault(ra, existente)
                por_nome_turma[(_norm(existente.nome), turma.id)] = existente
                # Auditoria: todo vínculo que TROCA a identidade fica rastreável.
                if _norm(nome_antigo) != _norm(parsed.nome):
                    alunos_vinculados += 1
                    registrar(db, "aluno.identidade_vinculada", escola_id=escola_id,
                              usuario_id=usuario.id, entidade="aluno",
                              entidade_id=existente.id,
                              detalhes={"nome_antigo": nome_antigo,
                                        "nome_novo": parsed.nome, "ra": ra or None,
                                        "origem": "importacao_matriculas"})
                # Conta o aluno DISTINTO uma vez (não a cada turma em que aparece).
                alunos_atualizados += 1

    registrar(db, "matriculas.importadas", escola_id=escola_id, usuario_id=usuario.id,
              entidade="escola", entidade_id=escola_id,
              detalhes={"turmas_criadas": turmas_criadas,
                        "alunos_criados": alunos_criados,
                        "alunos_atualizados": alunos_atualizados,
                        "alunos_vinculados": alunos_vinculados})
    db.commit()

    scoring.recalcular_escola(db, escola_id)
    from app.routers.publico import invalidar_cache_painel
    invalidar_cache_painel(escola_id)
    extra = (f" {alunos_vinculados} cadastro(s) de importação anterior recebeu(ram) "
             "o nome completo.") if alunos_vinculados else ""
    return MatriculasResultadoOut(
        mensagem=(f"{turmas_criadas} turma(s) criada(s), {alunos_criados} aluno(s) "
                  f"cadastrado(s) e {alunos_atualizados} atualizado(s)." + extra),
        turmas_criadas=turmas_criadas, alunos_criados=alunos_criados,
        alunos_atualizados=alunos_atualizados, avisos=avisos,
    )


# --- Histórico (PRD §15) ------------------------------------------------------

@router.get("", response_model=list[ImportacaoOut])
def listar(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
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
