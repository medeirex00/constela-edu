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
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import exigir_admin_global, get_usuario_atual
from app.models import Escola, Usuario

router = APIRouter(prefix="/presenca", tags=["Presença"])

# Janela de tolerância do "online": heartbeat de 30 s + folga p/ 1 batida perdida.
LIMIAR_ONLINE_SEG = 90


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

    linhas = db.execute(
        select(Usuario, Escola.nome)
        .outerjoin(Escola, Escola.id == Usuario.escola_id)
        .where(Usuario.status != "excluido")
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

    # Online primeiro; dentro de cada grupo, o mais recentemente visto no topo
    # (None por último) e, por fim, nome — ordem estável e útil para o gestor.
    sessoes.sort(key=lambda s: (
        not s.online,
        -(s.visto_em.timestamp() if s.visto_em else 0.0),
        s.nome.lower(),
    ))

    return SessoesOut(
        agora=agora,
        limiar_online_seg=LIMIAR_ONLINE_SEG,
        total=len(sessoes),
        online=sum(1 for s in sessoes if s.online),
        sessoes=sessoes,
    )
