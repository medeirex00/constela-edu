"""Endpoints de apoio ao app mobile: dispositivos push e sincronização.

Decisões:
  * `/sincronizacao` devolve TUDO que o app precisa em UMA viagem de rede
    (dashboard, ranking, evolução, alertas e mural) + carimbo `gerado_em`.
    No celular, menos round-trips = menos bateria e melhor uso de redes
    ruins; o app guarda o pacote em cache e o reexibe offline.
  * Dispositivos são upsert pelo token: o mesmo aparelho que troca de
    conta passa a pertencer ao novo usuário/escola. Só token no formato do
    Expo, e no máximo `MAX_APARELHOS_POR_CONTA` aparelhos por conta.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import escola_autorizada, get_usuario_atual
from app.models import DispositivoMovel, Escola, Usuario
from app.models.base import agora
from app.routers.rankings import _ranking, montar_dashboard
from app.services import elegibilidade, evolucao, gamificacao, insights, permissoes
from app.services import push as svc_push
from app.services.audit import registrar

router = APIRouter(prefix="/escolas/{escola_id}", tags=["Mobile"])


# --- Dispositivos (notificações push) -------------------------------------------

# Teto de aparelhos por conta. Uma pessoa usa o celular e, às vezes, um tablet; o
# app se registra a cada abertura. Sem teto, qualquer conta da escola (até um
# professor) gravava milhares de tokens por script, e cada aviso da escola passava
# a fazer N/100 chamadas ao Expo dentro da requisição que o disparou.
MAX_APARELHOS_POR_CONTA = 5


class DispositivoIn(BaseModel):
    # O token que o app recebe de getExpoPushTokenAsync (push.PADRAO_TOKEN_EXPO).
    token_push: str = Field(min_length=10, max_length=200,
                            pattern=svc_push.PADRAO_TOKEN_EXPO)
    plataforma: str = Field(pattern="^(android|ios)$")


def _aparelhos_alem_do_teto(db: Session, usuario_id: int, manter_id: int) -> list[int]:
    """Ids dos aparelhos da conta que passam do teto, sem contar ``manter_id`` (o
    que acabou de se registrar). Sai quem está há mais tempo sem se registrar
    (``updated_at``; o registro renova a data), depois o de id menor."""
    return list(db.execute(
        select(DispositivoMovel.id)
        .where(DispositivoMovel.usuario_id == usuario_id,
               DispositivoMovel.id != manter_id)
        .order_by(DispositivoMovel.updated_at.desc(), DispositivoMovel.id.desc())
        .offset(MAX_APARELHOS_POR_CONTA - 1)
    ).scalars().all())


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
        # Registrar de novo = o aparelho está em uso: conta como o mais recente no
        # teto por conta (sem isto, o updated_at só mudava se algum campo mudasse).
        dispositivo.updated_at = agora()
        if dono_anterior != usuario.id:
            registrar(db, "dispositivo.reassociado", escola_id=escola_id,
                      usuario_id=usuario.id,
                      detalhes={"plataforma": dados.plataforma,
                                "dono_anterior": dono_anterior})
    db.flush()
    excedentes = _aparelhos_alem_do_teto(db, usuario.id, dispositivo.id)
    if excedentes:
        db.execute(delete(DispositivoMovel).where(DispositivoMovel.id.in_(excedentes)))
        registrar(db, "dispositivo.excedente_removido", escola_id=escola_id,
                  usuario_id=usuario.id,
                  detalhes={"removidos": len(excedentes),
                            "limite": MAX_APARELHOS_POR_CONTA})
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
    # AS FASES NÃO CONCORREM: a evolução e o mural do app recortam as turmas
    # premiáveis, como o telão e a web (`routers/evolucao.ranking_evolucao`). O
    # escopo do professor não muda (interseção); a régua segue a da escola.
    premiaveis = elegibilidade.turmas_premiaveis(db, escola_id, escola.ano_letivo_ativo)
    concorrem = set(premiaveis)
    recorte = (premiaveis if permitidas is None
               else [t for t in permitidas if t in concorrem])

    # Carrega UMA vez as varreduras caras (séries de snapshot + dificuldade) e
    # injeta em todos os consumidores desta request (alertas, mural, evolução) —
    # antes, cada um relia as tabelas de snapshot (~3x cada por request). Mesma
    # estratégia do mural/M4.
    serie_m, serie_e, mapa_dif = evolucao.series_e_dificuldade(db, escola_id)

    alertas = insights.alertas_da_escola(db, escola_id, serie_m=serie_m, serie_e=serie_e)
    if permitidas is None:
        # Acesso total (admin/coordenador): mural da vitrine da escola inteira.
        eventos_mural = gamificacao.mural(
            db, escola_id, serie_m=serie_m, serie_e=serie_e, mapa_dif=mapa_dif,
            turma_ids=premiaveis)["eventos"]
    else:
        # Professor restrito: sem mural (é vitrine da escola inteira, como no
        # web, que o bloqueia com negar_restrito) e alertas só das turmas dele.
        eventos_mural = []
        alunos = permissoes.alunos_permitidos(db, escola_id,
                                              escola.ano_letivo_ativo, permitidas)
        alertas = permissoes.filtrar_por_aluno(alertas, alunos)

    ranking = _ranking(db, escola_id, escola.ano_letivo_ativo, turma_ids=permitidas)
    if permitidas is not None:
        # Professor: posição RELATIVA às turmas dele (1..N), como a web
        # (`rankings.ranking_geral`) e o Top 10 deste mesmo pacote
        # (`montar_dashboard`) — a aba "Ranking Geral" e o Painel do app não
        # podem dar duas posições à mesma criança. Gestão: a posição global.
        for posicao, item in enumerate(ranking, start=1):
            item.posicao = posicao

    return {
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "dashboard": montar_dashboard(db, escola_id, turma_ids=permitidas),
        "ranking": ranking,
        "evolucao": [
            {
                "posicao": item.posicao,
                "aluno_id": item.aluno_id,
                "nome": item.nome,
                "turma": item.turma,
                "nota_evolucao": item.nota_evolucao,
            }
            # Régua JUSTA (`base_no_periodo=True`), a mesma da web
            # (`routers/evolucao.ranking_evolucao`) e do telão: sem retrato
            # anterior à janela, o acumulado de vida não vira "evolução" — só
            # quem cresceu de verdade nos 30 dias sobe.
            for item in evolucao.ranking_evolucao(
                db, escola_id, dias=30, turma_ids=recorte, base_no_periodo=True,
                serie_m=serie_m, serie_e=serie_e, mapa_dif=mapa_dif)[:20]
        ],
        "alertas": alertas,
        "mural": eventos_mural,
    }
