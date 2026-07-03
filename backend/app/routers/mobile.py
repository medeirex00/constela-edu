"""Endpoints de apoio ao app mobile: dispositivos push e sincronização.

Decisões:
  * `/sincronizacao` devolve TUDO que o app precisa em UMA viagem de rede
    (dashboard, ranking, evolução, alertas e mural) + carimbo `gerado_em`.
    No celular, menos round-trips = menos bateria e melhor uso de redes
    ruins; o app guarda o pacote em cache e o reexibe offline.
  * Dispositivos são upsert pelo token: o mesmo aparelho que troca de
    conta passa a pertencer ao novo usuário/escola.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import escola_autorizada, get_usuario_atual
from app.models import DispositivoMovel, Escola, Usuario
from app.routers.rankings import _ranking, montar_dashboard
from app.services import evolucao, gamificacao, insights
from app.services.audit import registrar

router = APIRouter(prefix="/escolas/{escola_id}", tags=["Mobile"])


# --- Dispositivos (notificações push) -------------------------------------------

class DispositivoIn(BaseModel):
    token_push: str = Field(min_length=10, max_length=200)
    plataforma: str = Field(pattern="^(android|ios)$")


@router.post("/dispositivos")
def registrar_dispositivo(
    dados: DispositivoIn,
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    dispositivo = db.execute(
        select(DispositivoMovel).where(DispositivoMovel.token_push == dados.token_push)
    ).scalar_one_or_none()
    if dispositivo is None:
        dispositivo = DispositivoMovel(
            escola_id=escola_id, usuario_id=usuario.id,
            token_push=dados.token_push, plataforma=dados.plataforma,
        )
        db.add(dispositivo)
        registrar(db, "dispositivo.registrado", escola_id=escola_id,
                  usuario_id=usuario.id, detalhes={"plataforma": dados.plataforma})
    else:
        # O aparelho trocou de dono/escola: atualiza o vínculo
        dispositivo.escola_id = escola_id
        dispositivo.usuario_id = usuario.id
        dispositivo.plataforma = dados.plataforma
    db.commit()
    db.refresh(dispositivo)
    return {"id": dispositivo.id, "plataforma": dispositivo.plataforma}


class DispositivoRemover(BaseModel):
    token_push: str = Field(min_length=10, max_length=200)


@router.post("/dispositivos/remover")
def remover_dispositivo(
    dados: DispositivoRemover,
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Chamado no logout do app — o aparelho para de receber push."""
    dispositivo = db.execute(
        select(DispositivoMovel).where(
            DispositivoMovel.token_push == dados.token_push,
            DispositivoMovel.usuario_id == usuario.id,
        )
    ).scalar_one_or_none()
    if dispositivo is not None:
        db.delete(dispositivo)
        db.commit()
    return {"mensagem": "Dispositivo removido."}


# --- Sincronização (offline-first) -----------------------------------------------

@router.get("/sincronizacao")
def sincronizar(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Pacote consolidado para o app hidratar todas as telas de uma vez."""
    escola = db.get(Escola, escola_id)
    mural = gamificacao.mural(db, escola_id)
    return {
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "dashboard": montar_dashboard(db, escola_id),
        "ranking": _ranking(db, escola_id, escola.ano_letivo_ativo),
        "evolucao": [
            {
                "posicao": item.posicao,
                "aluno_id": item.aluno_id,
                "nome": item.nome,
                "turma": item.turma,
                "nota_evolucao": item.nota_evolucao,
            }
            for item in evolucao.ranking_evolucao(db, escola_id, dias=30)[:20]
        ],
        "alertas": insights.alertas_da_escola(db, escola_id),
        "mural": mural["eventos"],
    }
