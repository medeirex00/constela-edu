from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import exigir_admin_global, exigir_papeis, get_usuario_atual
from app.models import Escola, Usuario
from app.schemas import EscolaCreate, EscolaOut, EscolaUpdate
from app.services.audit import registrar

router = APIRouter(prefix="/escolas", tags=["Escolas"])


@router.get("", response_model=list[EscolaOut])
def listar(
    incluir_inativas: bool = Query(default=False),
    usuario: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db),
):
    """Seletor ESCOLA da página inicial (PRD §10, §20). O admin GLOBAL pode
    pedir também as inativas (tela Escolas) — sem isso, uma escola inativada
    sumiria de todas as listas sem caminho de volta."""
    consulta = select(Escola).order_by(Escola.nome)
    if not (incluir_inativas and usuario.is_global):
        consulta = consulta.where(Escola.status == "ativa")
    if not usuario.is_global:
        # Secretaria (rede vinculada): vê TODAS as escolas da rede dela; usuário
        # de escola única continua preso à própria escola.
        if usuario.rede_id is not None:
            consulta = consulta.where(Escola.rede_id == usuario.rede_id)
        else:
            consulta = consulta.where(Escola.id == usuario.escola_id)
    return db.execute(consulta).scalars().all()


@router.post("", response_model=EscolaOut, status_code=status.HTTP_201_CREATED)
def criar(
    dados: EscolaCreate,
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """Criar novas escolas é exclusivo de administradores globais (§136).
    Um admin local não pode inventar escolas fora do seu domínio."""
    nome = dados.nome.strip()
    # Nome repetido criaria um segundo "inquilino" indistinguível no seletor
    # de escolas — recusa aqui (um clique duplo/reenvio nunca duplica a rede).
    repetida = db.execute(
        select(Escola).where(func.lower(Escola.nome) == nome.lower())
    ).scalar_one_or_none()
    if repetida is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Já existe uma escola chamada “{repetida.nome}”.")
    escola = Escola(**{**dados.model_dump(), "nome": nome})
    db.add(escola)
    db.flush()
    registrar(db, "escola.criada", escola_id=escola.id, usuario_id=usuario.id,
              entidade="escola", entidade_id=escola.id, detalhes={"nome": escola.nome})
    db.commit()
    db.refresh(escola)
    return escola


@router.patch("/{escola_id}", response_model=EscolaOut)
def atualizar(
    escola_id: int,
    dados: EscolaUpdate,
    usuario: Usuario = Depends(exigir_papeis("admin")),
    db: Session = Depends(get_db),
):
    escola = db.get(Escola, escola_id)
    if escola is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Escola não encontrada.")
    if not usuario.is_global and usuario.escola_id != escola_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Acesso negado a esta escola.")
    alteracoes = dados.model_dump(exclude_unset=True)
    for campo, valor in alteracoes.items():
        setattr(escola, campo, valor)
    registrar(db, "escola.atualizada", escola_id=escola.id, usuario_id=usuario.id,
              entidade="escola", entidade_id=escola.id, detalhes=alteracoes)
    db.commit()
    db.refresh(escola)
    return escola
