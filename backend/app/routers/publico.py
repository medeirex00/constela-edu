"""Painel Público (PRD §104–§128).

Duas metades:
  * `/painel-publico/*` (autenticado, admin/coordenador) — configuração:
    ativar/desativar, escolher slides, intervalo, tamanho do ranking,
    gerar QR code e trocar o token (invalida o link antigo).
  * `/publico/{token}/*` (SEM login) — dados exibidos no telão/celular.
    Somente dados pedagógicos saem por aqui: nome, turma, notas, posição,
    conquistas. Nada de datas de nascimento, observações ou contatos.
"""
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import escola_autorizada, exigir_papeis
from app.models import Aluno, Configuracao, Escola, Matricula, Nota, Turma, Usuario
from app.services import evolucao as svc_evolucao
from app.services import gamificacao as svc_gami
from app.services import relatorios as svc_relatorios
from app.services.audit import registrar

router = APIRouter(tags=["Painel Público"])

SLIDES_VALIDOS = ["ranking", "evolucao", "destaques", "mural"]
PADRAO = {
    "ativo": False,
    "slides": SLIDES_VALIDOS,
    "intervalo_s": 12,
    "max_posicoes": 10,
}


def _config_row(db: Session, escola_id: int) -> Configuracao | None:
    return db.execute(
        select(Configuracao).where(
            Configuracao.escola_id == escola_id,
            Configuracao.namespace == "painel_publico",
            Configuracao.chave == "valores",
        )
    ).scalar_one_or_none()


def _config(db: Session, escola_id: int) -> dict:
    row = _config_row(db, escola_id)
    valores = dict(PADRAO)
    if row:
        valores.update(row.valor or {})
    return valores


def _escola_pelo_token(db: Session, token: str) -> tuple[Escola, dict] | None:
    """Resolve o token público para uma escola com painel ativo."""
    if not token:
        return None
    linhas = db.execute(
        select(Configuracao).where(
            Configuracao.namespace == "painel_publico",
            Configuracao.chave == "valores",
        )
    ).scalars().all()
    for row in linhas:
        valores = row.valor or {}
        if valores.get("ativo") and secrets.compare_digest(str(valores.get("token", "")), token):
            escola = db.get(Escola, row.escola_id)
            if escola is not None and escola.status == "ativa":
                config = dict(PADRAO)
                config.update(valores)
                return escola, config
    return None


# ---------------------------------------------------------------------------
# Configuração (autenticado)
# ---------------------------------------------------------------------------

config_router = APIRouter(prefix="/escolas/{escola_id}/painel-publico",
                          tags=["Painel Público"])


class PainelConfigIn(BaseModel):
    ativo: bool
    slides: list[str] = Field(default=SLIDES_VALIDOS)
    intervalo_s: int = Field(default=12, ge=4, le=120)
    max_posicoes: int = Field(default=10, ge=3, le=50)


def _com_url(valores: dict) -> dict:
    token = valores.get("token")
    return {
        "ativo": valores.get("ativo", False),
        "slides": valores.get("slides", SLIDES_VALIDOS),
        "intervalo_s": valores.get("intervalo_s", 12),
        "max_posicoes": valores.get("max_posicoes", 10),
        "url": f"{settings.PUBLIC_BASE_URL}/p/{token}" if token else None,
    }


@config_router.get("")
def obter_config(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
):
    return _com_url(_config(db, escola_id))


@config_router.put("")
def salvar_config(
    dados: PainelConfigIn,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    slides = [s for s in dados.slides if s in SLIDES_VALIDOS]
    if not slides:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Escolha pelo menos um slide para o painel.")
    row = _config_row(db, escola_id)
    valores = dict((row.valor or {}) if row else {})
    valores.update(dados.model_dump())
    valores["slides"] = slides
    if valores["ativo"] and not valores.get("token"):
        valores["token"] = secrets.token_urlsafe(9)
    if row is None:
        row = Configuracao(escola_id=escola_id, namespace="painel_publico",
                           chave="valores", valor=valores)
        db.add(row)
    else:
        row.valor = valores
    registrar(db, "painel_publico.configurado", escola_id=escola_id, usuario_id=usuario.id,
              detalhes={"ativo": valores["ativo"], "slides": slides})
    db.commit()
    return _com_url(valores)


@config_router.post("/novo-token")
def trocar_token(
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Gera um novo endereço público — o link antigo deixa de funcionar."""
    row = _config_row(db, escola_id)
    valores = dict((row.valor or {}) if row else dict(PADRAO))
    valores["token"] = secrets.token_urlsafe(9)
    if row is None:
        row = Configuracao(escola_id=escola_id, namespace="painel_publico",
                           chave="valores", valor=valores)
        db.add(row)
    else:
        row.valor = valores
    registrar(db, "painel_publico.token_trocado", escola_id=escola_id, usuario_id=usuario.id)
    db.commit()
    return _com_url(valores)


@config_router.get("/qr")
def qr_code(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
):
    """QR code (SVG) apontando para o painel público (PRD §118)."""
    import segno

    valores = _config(db, escola_id)
    token = valores.get("token")
    if not valores.get("ativo") or not token:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Ative o painel público antes de gerar o QR code.")
    url = f"{settings.PUBLIC_BASE_URL}/p/{token}"
    qr = segno.make(url, error="m")
    import io
    buffer = io.BytesIO()
    qr.save(buffer, kind="svg", scale=6, dark="#1B2A4A", border=2)
    return Response(
        content=buffer.getvalue(),
        media_type="image/svg+xml",
        headers={"Content-Disposition": 'attachment; filename="painel_publico_qr.svg"'},
    )


# ---------------------------------------------------------------------------
# Acesso público (sem login) — somente dados pedagógicos
# ---------------------------------------------------------------------------

publico_router = APIRouter(prefix="/publico", tags=["Painel Público"])


def _dados_publicos(db: Session, escola: Escola, config: dict) -> dict:
    limite = int(config.get("max_posicoes", 10))
    ranking = db.execute(
        select(Nota, Aluno, Turma)
        .join(Aluno, Nota.aluno_id == Aluno.id)
        .join(Matricula, (Matricula.aluno_id == Aluno.id)
              & (Matricula.ano_letivo == escola.ano_letivo_ativo))
        .join(Turma, Matricula.turma_id == Turma.id)
        # Aluno.status: painel PÚBLICO (sem login) nunca pode listar criança
        # arquivada/excluída — a Nota órfã dela não some no recálculo.
        .where(Nota.escola_id == escola.id, Nota.ano_letivo == escola.ano_letivo_ativo,
               Aluno.status == "ativo")
        .order_by(Nota.posicao)
        .limit(limite)
    ).all()

    evolucao_itens = svc_evolucao.ranking_evolucao(db, escola.id, dias=30)[:limite]
    mural = svc_gami.mural(db, escola.id)

    return {
        "escola": {
            "nome": escola.nome,
            "cor_primaria": svc_relatorios.cor_primaria(db, escola.id),
        },
        "slides": config.get("slides", SLIDES_VALIDOS),
        "intervalo_s": config.get("intervalo_s", 12),
        "ranking": [
            {
                "posicao": nota.posicao,
                "aluno_id": aluno.id,
                "nome": aluno.nome,
                "turma": turma.nome,
                "nota_geral": nota.nota_geral,
            }
            for nota, aluno, turma in ranking
        ],
        "evolucao": [
            {
                "posicao": item.posicao,
                "aluno_id": item.aluno_id,
                "nome": item.nome,
                "turma": item.turma,
                "nota_evolucao": item.nota_evolucao,
            }
            for item in evolucao_itens
        ],
        "destaques": mural["destaques"],
        "mural": [
            {"icone": evento["icone"], "texto": evento["texto"]}
            for evento in mural["eventos"][:10]
        ],
    }


# Cache em memória do painel público (por escola). O telão faz polling a cada
# poucos segundos e a recomputação é cara (mural + rankings); um TTL curto
# absorve os polls sem servir dados velhos. Por worker uvicorn — aceitável,
# pois os dados mudam poucas vezes por semana.
TTL_PAINEL_S = 60
_cache_painel: dict[int, tuple[float, dict]] = {}
# Ids exibidos no painel (por escola). Cacheados para o perfil público NÃO
# recomputar a evolução da escola inteira a cada abertura de aluno (mesmo TTL).
_cache_visiveis: dict[int, tuple[float, set[int]]] = {}


@publico_router.get("/{token}/painel")
def painel_publico(token: str, response: Response, db: Session = Depends(get_db)):
    resolvido = _escola_pelo_token(db, token)
    if resolvido is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Painel não encontrado ou desativado.")
    escola, config = resolvido
    agora = time.monotonic()
    em_cache = _cache_painel.get(escola.id)
    if em_cache and agora - em_cache[0] < TTL_PAINEL_S:
        dados = em_cache[1]
    else:
        dados = _dados_publicos(db, escola, config)
        _cache_painel[escola.id] = (agora, dados)
    # O próprio navegador/proxy também absorve parte dos polls.
    response.headers["Cache-Control"] = f"public, max-age={TTL_PAINEL_S}"
    return dados


def invalidar_cache_painel(escola_id: int | None = None) -> None:
    """Chamado após recálculo/importação para o painel refletir logo."""
    if escola_id is None:
        _cache_painel.clear()
        _cache_visiveis.clear()
    else:
        _cache_painel.pop(escola_id, None)
        _cache_visiveis.pop(escola_id, None)


def _ids_visiveis(db: Session, escola: Escola, config: dict) -> set[int]:
    """Ids dos alunos REALMENTE exibidos no painel (ranking + evolução, top-N).

    O perfil público só abre para quem já aparece no telão. Sem isto, o token
    público (impresso no QR do telão) permitiria varrer aluno_id=1,2,3… e coletar
    nome+notas de TODA a escola — IDOR/enumeração de PII de crianças.

    Resultado cacheado por TTL_PAINEL_S: sem cache, cada abertura de perfil
    recomputaria a evolução da escola inteira (consulta cara, sem login)."""
    agora = time.monotonic()
    em_cache = _cache_visiveis.get(escola.id)
    if em_cache and agora - em_cache[0] < TTL_PAINEL_S:
        return em_cache[1]
    limite = int(config.get("max_posicoes", 10))
    ids = set(db.execute(
        select(Aluno.id)
        .join(Nota, Nota.aluno_id == Aluno.id)
        .join(Matricula, (Matricula.aluno_id == Aluno.id)
              & (Matricula.ano_letivo == escola.ano_letivo_ativo))
        .where(Nota.escola_id == escola.id,
               Nota.ano_letivo == escola.ano_letivo_ativo,
               Aluno.status == "ativo")
        .order_by(Nota.posicao)
        .limit(limite)
    ).scalars())
    # A evolução também é exibida (slide próprio) — seus alunos podem ser abertos.
    for item in svc_evolucao.ranking_evolucao(db, escola.id, dias=30)[:limite]:
        ids.add(item.aluno_id)
    _cache_visiveis[escola.id] = (agora, ids)
    return ids


@publico_router.get("/{token}/alunos/{aluno_id}")
def perfil_publico(token: str, aluno_id: int, db: Session = Depends(get_db)):
    """Perfil público restrito a dados pedagógicos (PRD §120)."""
    resolvido = _escola_pelo_token(db, token)
    if resolvido is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "Painel não encontrado ou desativado.")
    escola, config = resolvido
    aluno = db.get(Aluno, aluno_id)
    # Só alunos exibidos no painel: bloqueia enumeração por aluno_id sequencial.
    if (aluno is None or aluno.escola_id != escola.id or aluno.status != "ativo"
            or aluno_id not in _ids_visiveis(db, escola, config)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aluno não encontrado.")

    matricula = db.execute(
        select(Matricula, Turma)
        .join(Turma, Matricula.turma_id == Turma.id)
        .where(Matricula.aluno_id == aluno_id,
               Matricula.ano_letivo == escola.ano_letivo_ativo)
    ).first()
    nota = db.execute(
        select(Nota).where(Nota.aluno_id == aluno_id,
                           Nota.ano_letivo == escola.ano_letivo_ativo)
    ).scalar_one_or_none()
    gamificacao = svc_gami.gamificacao_do_aluno(db, escola.id, aluno_id)

    # Estritamente pedagógico: nome, turma, notas e conquistas.
    return {
        "nome": aluno.nome,
        "turma": matricula[1].nome if matricula else None,
        "posicao": nota.posicao if nota else None,
        "nota_matific": nota.nota_matific if nota else 0.0,
        "nota_elefante": nota.nota_elefante if nota else 0.0,
        "nota_geral": nota.nota_geral if nota else 0.0,
        "nivel": gamificacao["nivel"],
        "xp": gamificacao["xp"],
        "conquistas": [
            {"nome": c["nome"], "icone": c["icone"], "descricao": c["descricao"]}
            for c in gamificacao["conquistas"] if c["atingida"]
        ],
        "escola": escola.nome,
    }


# O router "pai" agrega os dois para o main.py registrar de uma vez
router.include_router(config_router)
router.include_router(publico_router)
