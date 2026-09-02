"""Minhas Conquistas do ALUNO (Quest) — endpoint SELF, resolvido pela SESSÃO.

O aluno vê SÓ as próprias conquistas: o ``aluno_id`` (e a escola) vêm da
credencial via ``get_aluno_atual``, NUNCA do cliente. Sem isso, reaproveitar o
endpoint de gestor (que recebe ``aluno_id`` no path) viraria IDOR — o aluno
trocaria o id e veria as conquistas de outro.

Read-only e a FONTE DA VERDADE é o backend: o app não concede nem altera nada; só
lê o que ``gamificacao.gamificacao_do_aluno`` deriva dos snapshots (Matific/
Elefante). O aluno não consegue se auto-conceder uma conquista pelo cliente.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.quest.deps import ContextoAluno, get_aluno_atual
from app.services import gamificacao

router = APIRouter(prefix="/quest", tags=["Quest — Conquistas"])


@router.get("/conquistas")
def minhas_conquistas(ctx: ContextoAluno = Depends(get_aluno_atual),
                      db: Session = Depends(get_db)) -> dict:
    """Conquistas do PRÓPRIO aluno: desbloqueadas e em andamento, cada uma com
    nome, descrição, ícone, categoria, progresso e data de desbloqueio (quando
    houver). ``aluno_id``/``escola_id`` vêm da SESSÃO — o cliente não escolhe."""
    return gamificacao.gamificacao_do_aluno(db, ctx.escola_id, ctx.aluno.id)
