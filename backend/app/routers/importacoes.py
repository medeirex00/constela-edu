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
from datetime import datetime, timezone
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

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import escola_autorizada, exigir_papeis, get_usuario_atual
from app.models import (
    Aluno,
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
from app.schemas import AnaliseOut, ImportacaoConfirm, ImportacaoOut, ImportacaoResultadoOut
from app.services import importacao as svc
from app.services import perfis_pdf, push, scoring
from app.services.audit import registrar

router = APIRouter(prefix="/escolas/{escola_id}/importacoes", tags=["Importações"])

logger = logging.getLogger("constela.importacao")

TAMANHO_MAXIMO = 10 * 1024 * 1024  # 10 MB
IDADE_MAXIMA_TEMP_S = 24 * 3600     # PDFs de prévia não confirmados expiram em 24h
_TOKEN_VALIDO = re.compile(r"^[0-9a-f]{32}\.pdf$")


def _limpar_temporarios_orfaos() -> None:
    """Remove PDFs de prévia abandonados (usuário fechou sem confirmar).
    Chamado a cada nova análise — barato e evita crescimento sem limite."""
    pasta = settings.UPLOADS_DIR / "temporarios"
    if not pasta.exists():
        return
    limite = time.time() - IDADE_MAXIMA_TEMP_S
    for arquivo in pasta.glob("*.pdf"):
        try:
            if arquivo.stat().st_mtime < limite:
                arquivo.unlink(missing_ok=True)
        except OSError:
            pass


def _escapar_like(texto: str) -> str:
    """Neutraliza os curingas % e _ para comparação literal em ILIKE."""
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _snapshot_atual(db: Session, escola_id: int, aluno_id: int, modelo):
    return db.execute(
        select(modelo)
        .where(modelo.escola_id == escola_id, modelo.aluno_id == aluno_id)
        .order_by(modelo.id.desc())
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
        eh_pdf = arquivo_nome.lower().endswith(".pdf") or arquivo.content_type == "application/pdf"
        if eh_pdf:
            _limpar_temporarios_orfaos()
            try:
                # Perfis posicionais (formatos reais) com as 4 estratégias
                # genéricas de texto como rede de segurança.
                analise = perfis_pdf.analisar_pdf(conteudo, plataforma)
            except HTTPException:
                raise  # mensagem útil do parser genérico chega ao usuário
            except Exception as exc:
                logger.exception("Falha ao analisar PDF (escola %s, arquivo %r)",
                                 escola_id, arquivo_nome)
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "Não foi possível ler o PDF. O arquivo está íntegro?") from exc
            # Guarda o original em /uploads/temporarios até a confirmação (§15)
            arquivo_token = f"{uuid.uuid4().hex}.pdf"
            destino = settings.UPLOADS_DIR / "temporarios" / arquivo_token
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(conteudo)
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

def _resolver_aluno(db: Session, escola_id: int, ano: int, linha, avisos: list[str],
                    criados: dict | None = None) -> Aluno | None:
    if linha.aluno_id is not None:
        aluno = db.get(Aluno, linha.aluno_id)
        if aluno is None or aluno.escola_id != escola_id:
            avisos.append(f"Linha “{linha.nome}”: aluno não pertence a esta escola — ignorada.")
            return None
        return aluno
    if linha.criar_em_turma_id is not None:
        turma = db.get(Turma, linha.criar_em_turma_id)
        if turma is None or turma.escola_id != escola_id:
            avisos.append(f"Linha “{linha.nome}”: turma inválida — ignorada.")
            return None
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
    db.add(SnapshotMatific(
        escola_id=escola_id, aluno_id=aluno.id, importacao_id=importacao.id,
        data_referencia=data_referencia,
        atividades=int(dados.get("atividades", 0)),
        estrelas=int(dados.get("estrelas", 0)),
        pontuacao_media=float(dados.get("pontuacao_media", 0.0)),
    ))


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
    """Formato "uma linha por livro concluído": registra leituras únicas (§35)."""
    vistos: set[int] = set()  # livros já processados NESTE lote (autoflush=False)
    for linha in linhas:
        titulo = str(linha.dados.get("livro", "")).strip()
        nivel = str(linha.dados.get("nivel", "")).strip().upper()
        if not titulo:
            avisos.append(f"Linha {linha.nome}: livro sem título — ignorada.")
            continue
        # Comparação case-insensitive literal: escapa % e _ do título (senão
        # um livro chamado "100%" casaria com qualquer outro) e evita
        # MultipleResultsFound usando o primeiro correspondente.
        livro = db.execute(
            select(Livro).where(
                Livro.escola_id == escola_id,
                Livro.titulo.ilike(_escapar_like(titulo), escape="\\"),
            ).limit(1)
        ).scalars().first()
        if livro is None:
            if not nivel:
                avisos.append(f"Livro “{titulo}” é novo e veio sem nível — ignorado.")
                continue
            livro = Livro(escola_id=escola_id, titulo=titulo, nivel_codigo=nivel,
                          categoria=linha.dados.get("genero") or None)
            db.add(livro)
            db.flush()
        # Releitura no MESMO relatório (livro repetido): o guard de banco não
        # enxerga leituras pendentes (autoflush=False), então deduplicamos
        # também em memória — senão a UniqueConstraint derrubaria a importação.
        if livro.id in vistos:
            avisos.append(f"“{titulo}” aparece mais de uma vez no relatório de "
                          f"{aluno.nome} — contado uma vez (§35).")
            continue
        ja_lido = db.execute(
            select(Leitura).where(Leitura.aluno_id == aluno.id, Leitura.livro_id == livro.id)
        ).scalar_one_or_none()
        if ja_lido:
            avisos.append(f"“{titulo}” já constava para {aluno.nome} — releitura não pontua (§35).")
            continue
        vistos.add(livro.id)
        # Relatórios individuais informam a data real de conclusão do livro
        quando = data_referencia
        try:
            bruto = linha.dados.get("data")
            if bruto:
                quando = datetime.fromisoformat(str(bruto))
        except ValueError:
            pass
        db.add(Leitura(escola_id=escola_id, aluno_id=aluno.id,
                       livro_id=livro.id, data=quando))
    db.flush()

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
            if not base_nome or not base_nome.lower().endswith(".pdf"):
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
    for linha in dados.linhas:
        aluno = _resolver_aluno(db, escola_id, escola.ano_letivo_ativo, linha,
                                avisos, criados)
        if aluno is None:
            continue
        resolvidos.setdefault(aluno.id, (aluno, []))[1].append(linha)

    for aluno, linhas_aluno in resolvidos.values():
        if dados.plataforma == "matific":
            _importar_matific(db, escola_id, importacao, aluno,
                              linhas_aluno[-1].dados, data_referencia)
        elif dados.formato == "leituras":
            _importar_elefante_leituras(db, escola_id, importacao, aluno,
                                        linhas_aluno, data_referencia, avisos)
        else:
            _importar_elefante_resumo(db, escola_id, importacao, aluno,
                                      linhas_aluno[-1].dados, data_referencia)

    importacao.qtd_alunos = len(resolvidos)
    importacao.qtd_erros = len(dados.linhas) - sum(len(l) for _, l in resolvidos.values())
    importacao.tempo_ms = int((time.monotonic() - inicio) * 1000)

    registrar(db, "importacao.concluida", escola_id=escola_id, usuario_id=usuario.id,
              entidade="importacao", entidade_id=importacao.id,
              detalhes={"plataforma": dados.plataforma, "tipo": dados.tipo,
                        "alunos": importacao.qtd_alunos, "avisos": avisos})
    db.commit()
    scoring.recalcular_escola(db, escola_id)
    from app.routers.publico import invalidar_cache_painel
    invalidar_cache_painel(escola_id)  # painel público reflete os novos dados

    # Avisa os aparelhos da escola (melhor esforço — nunca falha a importação)
    plataforma_nome = "Matific" if dados.plataforma == "matific" else "Elefante Letrado"
    push.notificar_escola(
        db, escola_id,
        titulo="Novos dados no Constela Edu",
        corpo=f"{importacao.qtd_alunos} alunos atualizados na {plataforma_nome}. "
              "As notas já foram recalculadas.",
        dados={"tela": "ranking"},
    )

    return ImportacaoResultadoOut(
        mensagem=f"Importação concluída: {importacao.qtd_alunos} alunos atualizados. "
                 f"Notas recalculadas automaticamente.",
        importacao_id=importacao.id,
        qtd_alunos=importacao.qtd_alunos,
        qtd_erros=importacao.qtd_erros,
        avisos=avisos,
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
