"""Inteligência Pedagógica e Assistente de IA (PRD §129–§172)."""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import escola_autorizada, get_usuario_atual
from app.models import ConversaIA, MensagemIA, Usuario
from app.services import assistente, insights
from app.services.audit import registrar

router = APIRouter(prefix="/escolas/{escola_id}", tags=["Inteligência Pedagógica"])


# --- Insights e alertas (PRD §129–§153) ----------------------------------------

@router.get("/insights")
def insights_da_escola(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Índices de engajamento/evolução/persistência + alertas automáticos."""
    return {
        "indices": insights.indices_da_escola(db, escola_id),
        "alertas": insights.alertas_da_escola(db, escola_id),
    }


# --- Assistente Pedagógico (PRD §155–§172) --------------------------------------

class PerguntaIn(BaseModel):
    pergunta: str = Field(min_length=2, max_length=2000)
    conversa_id: int | None = None


@router.post("/assistente")
def perguntar(
    dados: PerguntaIn,
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Chat com contexto montado no backend — a IA só vê dados desta escola."""
    try:
        resultado = assistente.perguntar(
            db, escola_id, usuario.id, dados.pergunta, dados.conversa_id
        )
    except ValueError as erro:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(erro))
    registrar(db, "assistente.pergunta", escola_id=escola_id, usuario_id=usuario.id,
              entidade="conversa_ia", entidade_id=resultado["conversa_id"],
              detalhes={"provedor": resultado["provedor"]})
    db.commit()
    return resultado


@router.get("/assistente/conversas")
def listar_conversas(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Histórico de conversas do usuário logado (PRD §160)."""
    conversas = db.execute(
        select(ConversaIA)
        .where(ConversaIA.escola_id == escola_id, ConversaIA.usuario_id == usuario.id)
        .order_by(ConversaIA.id.desc())
        .limit(30)
    ).scalars().all()
    return [
        {"id": c.id, "titulo": c.titulo, "provedor": c.provedor, "created_at": c.created_at}
        for c in conversas
    ]


@router.get("/assistente/conversas/{conversa_id}")
def mensagens_da_conversa(
    conversa_id: int,
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    conversa = db.get(ConversaIA, conversa_id)
    if conversa is None or conversa.escola_id != escola_id \
            or conversa.usuario_id != usuario.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversa não encontrada.")
    mensagens = db.execute(
        select(MensagemIA).where(MensagemIA.conversa_id == conversa_id)
        .order_by(MensagemIA.id)
    ).scalars().all()
    return {
        "id": conversa.id,
        "titulo": conversa.titulo,
        "provedor": conversa.provedor,
        "mensagens": [
            {"papel": m.papel, "conteudo": m.conteudo, "created_at": m.created_at}
            for m in mensagens
        ],
    }


@router.get("/assistente/status")
def status_do_assistente(
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Qual provedor está configurado (sem expor chaves)."""
    return {"provedor": settings.AI_PROVIDER, "modelo": settings.AI_MODEL or "padrão"}
