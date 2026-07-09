"""Perfil do astronauta: leitura e as poucas escritas permitidas ao aluno."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.quest import schemas
from app.quest.deps import ContextoAluno, get_aluno_atual
from app.quest.services import perfis as svc
from app.services.audit import registrar

router = APIRouter(prefix="/quest/perfil", tags=["Quest — Perfil"])


def _montar(ctx: ContextoAluno) -> schemas.PerfilOut:
    saida = schemas.PerfilOut.model_validate(ctx.perfil)
    saida.primeiro_nome = (ctx.aluno.nome or "").strip().split(" ")[0].title()
    return saida


@router.get("", response_model=schemas.PerfilOut)
def meu_perfil(ctx: ContextoAluno = Depends(get_aluno_atual)):
    return _montar(ctx)


@router.get("/cores", response_model=list[str])
def cores_disponiveis():
    """Catálogo de cores do traje (fase Q0: único slot equipável)."""
    return list(svc.CORES_TRAJE)


@router.patch("/avatar", response_model=schemas.PerfilOut)
def trocar_avatar(dados: schemas.AvatarIn,
                  ctx: ContextoAluno = Depends(get_aluno_atual),
                  db: Session = Depends(get_db)):
    try:
        svc.atualizar_avatar(ctx.perfil, dados.model_dump(exclude_none=True))
    except ValueError as erro:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(erro))
    db.add(ctx.perfil)
    registrar(db, "quest.avatar", escola_id=ctx.escola_id,
              entidade="aluno", entidade_id=ctx.aluno.id,
              detalhes={"avatar": ctx.perfil.avatar})
    db.commit()
    db.refresh(ctx.perfil)
    return _montar(ctx)


@router.patch("/preferencias", response_model=schemas.PerfilOut)
def trocar_preferencias(dados: schemas.PreferenciasIn,
                        ctx: ContextoAluno = Depends(get_aluno_atual),
                        db: Session = Depends(get_db)):
    svc.atualizar_preferencias(ctx.perfil, dados.model_dump(exclude_none=True))
    db.add(ctx.perfil)
    db.commit()
    db.refresh(ctx.perfil)
    return _montar(ctx)
