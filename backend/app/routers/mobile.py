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
from app.services import evolucao, gamificacao, insights, permissoes
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
        # O aparelho trocou de dono/escola: atualiza o vínculo. O token_push é
        # um segredo do app da vítima (só quem tem o aparelho o conhece), mas a
        # TROCA DE DONO fica registrada na auditoria para ser rastreável.
        dono_anterior = dispositivo.usuario_id
        dispositivo.escola_id = escola_id
        dispositivo.usuario_id = usuario.id
        dispositivo.plataforma = dados.plataforma
        if dono_anterior != usuario.id:
            registrar(db, "dispositivo.reassociado", escola_id=escola_id,
                      usuario_id=usuario.id,
                      detalhes={"plataforma": dados.plataforma,
                                "dono_anterior": dono_anterior})
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
    """Pacote consolidado para o app hidratar todas as telas de uma vez.

    Mesmo escopo por papel da web: admin/coordenador enxergam a escola inteira;
    professor recebe SOMENTE as turmas dele (`turmas_permitidas`). Sem isso, o
    sync vazaria nomes e notas de toda a escola para um professor restrito.
    """
    escola = db.get(Escola, escola_id)
    permitidas = permissoes.turmas_permitidas(db, escola_id, usuario)

    # Carrega UMA vez as varreduras caras (séries de snapshot + dificuldade) e
    # injeta em todos os consumidores desta request (alertas, mural, evolução) —
    # antes, cada um relia as tabelas de snapshot (~3x cada por request). Mesma
    # estratégia do mural/M4.
    serie_m, serie_e, mapa_dif = evolucao.series_e_dificuldade(db, escola_id)

    alertas = insights.alertas_da_escola(db, escola_id, serie_m=serie_m, serie_e=serie_e)
    if permitidas is None:
        # Acesso total (admin/coordenador): mural da vitrine da escola inteira.
        eventos_mural = gamificacao.mural(
            db, escola_id, serie_m=serie_m, serie_e=serie_e, mapa_dif=mapa_dif)["eventos"]
    else:
        # Professor restrito: sem mural (é vitrine da escola inteira, como no
        # web, que o bloqueia com negar_restrito) e alertas só das turmas dele.
        eventos_mural = []
        alunos = permissoes.alunos_permitidos(db, escola_id,
                                              escola.ano_letivo_ativo, permitidas)
        alertas = permissoes.filtrar_por_aluno(alertas, alunos)

    return {
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "dashboard": montar_dashboard(db, escola_id, turma_ids=permitidas),
        "ranking": _ranking(db, escola_id, escola.ano_letivo_ativo, turma_ids=permitidas),
        "evolucao": [
            {
                "posicao": item.posicao,
                "aluno_id": item.aluno_id,
                "nome": item.nome,
                "turma": item.turma,
                "nota_evolucao": item.nota_evolucao,
            }
            for item in evolucao.ranking_evolucao(
                db, escola_id, dias=30, turma_ids=permitidas,
                serie_m=serie_m, serie_e=serie_e, mapa_dif=mapa_dif)[:20]
        ],
        "alertas": alertas,
        "mural": eventos_mural,
    }
