"""Presença em tempo real: heartbeat + Monitor de Sessões Ativas.

Duas rotas, sem estado extra além de ``usuarios.visto_em``:

  * ``POST /presenca/heartbeat`` — QUALQUER usuário autenticado registra que
    está com o app aberto (o front pinga a cada ~30 s). Uma única UPDATE barata.
  * ``GET  /presenca/sessoes`` — EXCLUSIVO do Admin Global: lista todos os
    usuários com o status de presença (online/offline), a última atividade e o
    último acesso. "Online" = ``visto_em`` dentro da janela de tolerância.

Sem WebSocket: o monitor faz *polling* leve. A janela (``LIMIAR_ONLINE_SEG``)
cobre uma batida perdida — com heartbeat de 30 s, 90 s tolera um atraso de rede.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import exigir_admin_global, get_usuario_atual
from app.models import Escola, Usuario

router = APIRouter(prefix="/presenca", tags=["Presença"])

# Janela de tolerância do "online": heartbeat de 30 s + folga p/ 1 batida perdida.
LIMIAR_ONLINE_SEG = 90
# Teto de linhas materializadas: o monitor mostra as sessões MAIS RECENTES. Os
# totais (total/online) vêm de COUNT no banco, então continuam exatos mesmo se a
# tabela for cortada aqui — o front nunca precisa de todos os inativos de uma vez.
MAX_SESSOES = 1000


class SessaoOut(BaseModel):
    id: int
    nome: str
    email: str
    cargo: str
    is_global: bool
    rede_id: int | None
    escola_id: int | None
    escola_nome: str | None
    # Situação da CONTA (ativo/inativo) — não confundir com o "online" de presença.
    status: str
    online: bool
    # Última batida de presença e último ENTRAR (ambos UTC com fuso explícito).
    visto_em: datetime | None
    ultimo_acesso: datetime | None


class SessoesOut(BaseModel):
    # Instante do servidor: o front calcula "há X min" contra ESTE relógio
    # (imune ao relógio/fuso do navegador).
    agora: datetime
    limiar_online_seg: int
    total: int
    online: int
    sessoes: list[SessaoOut]


def _utc(dt: datetime | None) -> datetime | None:
    """Marca como UTC as datas ingênuas do banco (o SQLite não guarda fuso)."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


@router.post("/heartbeat", response_model=dict)
def heartbeat(
    usuario: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db),
):
    """Marca o usuário como presente AGORA. Leve de propósito: uma só escrita,
    sem recalcular nada. Aberto a qualquer conta autenticada (inclusive a
    Secretaria) — presença não é operação de escola."""
    usuario.visto_em = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@router.get("/sessoes", response_model=SessoesOut)
def listar_sessoes(
    _: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """Monitor de Sessões Ativas (Admin Global): todos os usuários com o status
    de presença. Não expõe senha nem PII de aluno — só quem opera o sistema."""
    agora = datetime.now(timezone.utc)
    corte = agora - timedelta(seconds=LIMIAR_ONLINE_SEG)
    corte_db = corte.replace(tzinfo=None)  # coluna guardada ingênua (UTC)

    ativos = Usuario.status != "excluido"
    # Totais direto no banco: exatos mesmo com a tabela cortada em MAX_SESSOES.
    total = db.execute(
        select(func.count()).select_from(Usuario).where(ativos)
    ).scalar_one()
    online_total = db.execute(
        select(func.count()).select_from(Usuario)
        .where(ativos, Usuario.visto_em.is_not(None), Usuario.visto_em >= corte_db)
    ).scalar_one()

    # Só as sessões MAIS RECENTES (online sempre no topo, pois têm o visto_em mais
    # alto). Ordena e corta no banco — antes materializava TODOS os usuários e
    # ordenava em Python. `is_(None)` primeiro garante nulos por último nos dois
    # bancos (o NULLS LAST do DESC difere entre SQLite e Postgres).
    linhas = db.execute(
        select(Usuario, Escola.nome)
        .outerjoin(Escola, Escola.id == Usuario.escola_id)
        .where(ativos)
        .order_by(Usuario.visto_em.is_(None), Usuario.visto_em.desc(), Usuario.nome)
        .limit(MAX_SESSOES)
    ).all()

    sessoes: list[SessaoOut] = []
    for u, escola_nome in linhas:
        visto = _utc(u.visto_em)
        online = visto is not None and visto >= corte
        sessoes.append(SessaoOut(
            id=u.id,
            nome=u.nome,
            email=u.email,
            cargo=u.cargo,
            is_global=u.is_global,
            rede_id=u.rede_id,
            escola_id=u.escola_id,
            escola_nome=escola_nome,
            status=u.status,
            online=online,
            visto_em=visto,
            ultimo_acesso=_utc(u.ultimo_acesso),
        ))

    return SessoesOut(
        agora=agora,
        limiar_online_seg=LIMIAR_ONLINE_SEG,
        total=total,
        online=online_total,
        sessoes=sessoes,
    )
