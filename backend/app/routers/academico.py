from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import escola_autorizada, exigir_papeis, get_usuario_atual
from app.models import Aluno, Escola, Matricula, Nota, Professor, Turma, Usuario
from app.schemas import (
    AlunoCreate,
    AlunoOut,
    AlunoPerfilOut,
    ProfessorCreate,
    ProfessorOut,
    TurmaCreate,
    TurmaOut,
    TurmaUpdate,
)
from app.services.audit import registrar

router = APIRouter(prefix="/escolas/{escola_id}", tags=["Acadêmico"])


def _ano_ativo(db: Session, escola_id: int) -> int:
    escola = db.get(Escola, escola_id)
    if escola is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Escola não encontrada.")
    return escola.ano_letivo_ativo


# --- Alunos -----------------------------------------------------------------

@router.get("/alunos", response_model=dict)
def listar_alunos(
    escola_id: int = Depends(escola_autorizada),
    busca: str | None = Query(default=None),
    turma_id: int | None = Query(default=None),
    ano_escolar: str | None = Query(default=None),
    pagina: int = Query(default=1, ge=1),
    por_pagina: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Lista paginada (PRD §23) com busca e filtros (PRD §53)."""
    ano = _ano_ativo(db, escola_id)
    consulta = (
        select(Aluno, Turma)
        .join(Matricula, Matricula.aluno_id == Aluno.id)
        .join(Turma, Matricula.turma_id == Turma.id)
        .where(
            Aluno.escola_id == escola_id,
            Matricula.ano_letivo == ano,
            Aluno.status == "ativo",
        )
    )
    if busca:
        consulta = consulta.where(Aluno.nome.ilike(f"%{busca}%"))
    if turma_id:
        consulta = consulta.where(Turma.id == turma_id)
    if ano_escolar:
        consulta = consulta.where(Turma.ano_escolar == ano_escolar)

    total = db.execute(
        select(func.count()).select_from(consulta.order_by(None).subquery())
    ).scalar_one()
    linhas = db.execute(
        consulta.order_by(Aluno.nome).offset((pagina - 1) * por_pagina).limit(por_pagina)
    ).all()

    itens = []
    for aluno, turma in linhas:
        item = AlunoOut.model_validate(aluno)
        item.turma = turma.nome
        item.ano_escolar = turma.ano_escolar
        itens.append(item)
    return {"total": total, "pagina": pagina, "por_pagina": por_pagina, "itens": itens}


@router.post("/alunos", response_model=AlunoOut, status_code=status.HTTP_201_CREATED)
def criar_aluno(
    dados: AlunoCreate,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    ano = _ano_ativo(db, escola_id)
    turma = db.get(Turma, dados.turma_id)
    if turma is None or turma.escola_id != escola_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Turma inválida para esta escola.")

    aluno = Aluno(
        escola_id=escola_id,
        nome=dados.nome.strip(),
        numero_chamada=dados.numero_chamada,
        data_nascimento=dados.data_nascimento,
        observacoes=dados.observacoes,
    )
    db.add(aluno)
    db.flush()
    db.add(Matricula(escola_id=escola_id, aluno_id=aluno.id, turma_id=turma.id, ano_letivo=ano))
    registrar(db, "aluno.criado", escola_id=escola_id, usuario_id=usuario.id,
              entidade="aluno", entidade_id=aluno.id, detalhes={"nome": aluno.nome})
    db.commit()
    db.refresh(aluno)
    saida = AlunoOut.model_validate(aluno)
    saida.turma = turma.nome
    saida.ano_escolar = turma.ano_escolar
    return saida


@router.get("/alunos/{aluno_id}/perfil", response_model=AlunoPerfilOut)
def perfil_aluno(
    aluno_id: int,
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Perfil com a explicação completa da nota (PRD §45, §54)."""
    ano = _ano_ativo(db, escola_id)
    aluno = db.get(Aluno, aluno_id)
    if aluno is None or aluno.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aluno não encontrado.")

    matricula = db.execute(
        select(Matricula, Turma)
        .join(Turma, Matricula.turma_id == Turma.id)
        .where(Matricula.aluno_id == aluno_id, Matricula.ano_letivo == ano)
    ).first()
    nota = db.execute(
        select(Nota).where(Nota.aluno_id == aluno_id, Nota.ano_letivo == ano)
    ).scalar_one_or_none()

    saida = AlunoOut.model_validate(aluno)
    if matricula:
        saida.turma = matricula[1].nome
        saida.ano_escolar = matricula[1].ano_escolar
    return AlunoPerfilOut(
        aluno=saida,
        nota_matific=nota.nota_matific if nota else 0.0,
        nota_elefante=nota.nota_elefante if nota else 0.0,
        nota_geral=nota.nota_geral if nota else 0.0,
        posicao=nota.posicao if nota else None,
        detalhes=nota.detalhes if nota else {},
        calculada_em=nota.calculada_em if nota else None,
    )


# --- Turmas e Professores ---------------------------------------------------

def _validar_professor(db: Session, escola_id: int, professor_id: int | None) -> None:
    if professor_id is None:
        return
    professor = db.get(Professor, professor_id)
    if professor is None or professor.escola_id != escola_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Professor inválido para esta escola.")


def _validar_nome_unico(db: Session, escola_id: int, nome: str, ano_letivo: int,
                        ignorar_id: int | None = None) -> None:
    consulta = select(Turma).where(
        Turma.escola_id == escola_id,
        Turma.ano_letivo == ano_letivo,
        func.lower(Turma.nome) == nome.strip().lower(),
    )
    if ignorar_id is not None:
        consulta = consulta.where(Turma.id != ignorar_id)
    if db.execute(consulta).scalars().first() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Já existe a turma “{nome.strip()}” no ano letivo "
                            f"{ano_letivo}.")


def _turma_da_escola(db: Session, escola_id: int, turma_id: int) -> Turma:
    turma = db.get(Turma, turma_id)
    if turma is None or turma.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Turma não encontrada.")
    return turma


def _turma_out(db: Session, turma: Turma) -> TurmaOut:
    saida = TurmaOut.model_validate(turma)
    if turma.professor_id:
        professor = db.get(Professor, turma.professor_id)
        saida.professor_nome = professor.nome if professor else None
    saida.total_alunos = db.execute(
        select(func.count())
        .select_from(Matricula)
        .join(Aluno, Aluno.id == Matricula.aluno_id)
        .where(Matricula.turma_id == turma.id,
               Matricula.ano_letivo == turma.ano_letivo,
               Aluno.status == "ativo")
    ).scalar_one()
    return saida


@router.get("/turmas", response_model=list[TurmaOut])
def listar_turmas(
    escola_id: int = Depends(escola_autorizada),
    todas: bool = Query(default=False),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Turmas ativas do ano letivo ativo; `todas=true` inclui arquivadas e
    outros anos (tela de gestão). Filtros e seletores usam o padrão."""
    ano = _ano_ativo(db, escola_id)
    consulta = (
        select(Turma, Professor.nome, func.count(Aluno.id))
        .outerjoin(Professor, Turma.professor_id == Professor.id)
        .outerjoin(Matricula, (Matricula.turma_id == Turma.id)
                   & (Matricula.ano_letivo == Turma.ano_letivo))
        .outerjoin(Aluno, (Aluno.id == Matricula.aluno_id)
                   & (Aluno.status == "ativo"))
        .where(Turma.escola_id == escola_id)
        .group_by(Turma.id, Professor.nome)
        .order_by(Turma.ano_letivo.desc(), Turma.ano_escolar, Turma.nome)
    )
    if not todas:
        consulta = consulta.where(Turma.ano_letivo == ano,
                                  Turma.status == "ativa")
    saida = []
    for turma, professor_nome, total_alunos in db.execute(consulta).all():
        item = TurmaOut.model_validate(turma)
        item.professor_nome = professor_nome
        item.total_alunos = total_alunos
        saida.append(item)
    return saida


@router.post("/turmas", response_model=TurmaOut, status_code=status.HTTP_201_CREATED)
def criar_turma(
    dados: TurmaCreate,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    _validar_professor(db, escola_id, dados.professor_id)
    _validar_nome_unico(db, escola_id, dados.nome, dados.ano_letivo)
    turma = Turma(escola_id=escola_id, **{**dados.model_dump(),
                                          "nome": dados.nome.strip()})
    db.add(turma)
    db.flush()
    registrar(db, "turma.criada", escola_id=escola_id, usuario_id=usuario.id,
              entidade="turma", entidade_id=turma.id, detalhes={"nome": turma.nome})
    db.commit()
    db.refresh(turma)
    return _turma_out(db, turma)


@router.put("/turmas/{turma_id}", response_model=TurmaOut)
def atualizar_turma(
    turma_id: int,
    dados: TurmaUpdate,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Edição parcial — também cobre Arquivar/Reativar via `status`."""
    turma = _turma_da_escola(db, escola_id, turma_id)
    campos = dados.model_dump(exclude_unset=True)
    if "professor_id" in campos:
        _validar_professor(db, escola_id, campos["professor_id"])
    nome = campos.get("nome", turma.nome).strip()
    ano_letivo = campos.get("ano_letivo", turma.ano_letivo)
    if "nome" in campos or "ano_letivo" in campos:
        _validar_nome_unico(db, escola_id, nome, ano_letivo, ignorar_id=turma.id)
    if "nome" in campos:
        campos["nome"] = nome
    for chave, valor in campos.items():
        setattr(turma, chave, valor)
    registrar(db, "turma.atualizada", escola_id=escola_id, usuario_id=usuario.id,
              entidade="turma", entidade_id=turma.id, detalhes=campos)
    db.commit()
    db.refresh(turma)
    return _turma_out(db, turma)


@router.delete("/turmas/{turma_id}", response_model=dict)
def excluir_turma(
    turma_id: int,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Exclusão definitiva — bloqueada enquanto houver alunos vinculados."""
    turma = _turma_da_escola(db, escola_id, turma_id)
    vinculados = db.execute(
        select(func.count()).select_from(Matricula)
        .where(Matricula.turma_id == turma.id)
    ).scalar_one()
    if vinculados:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"A turma “{turma.nome}” possui {vinculados} aluno(s) vinculado(s). "
            "Mova ou remova os alunos antes de excluir — ou arquive a turma "
            "para preservar o histórico.")
    nome = turma.nome
    db.delete(turma)
    registrar(db, "turma.excluida", escola_id=escola_id, usuario_id=usuario.id,
              entidade="turma", entidade_id=turma_id, detalhes={"nome": nome})
    db.commit()
    return {"mensagem": f"Turma “{nome}” excluída."}


@router.get("/professores", response_model=list[ProfessorOut])
def listar_professores(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    return db.execute(
        select(Professor).where(Professor.escola_id == escola_id).order_by(Professor.nome)
    ).scalars().all()


@router.post("/professores", response_model=ProfessorOut, status_code=status.HTTP_201_CREATED)
def criar_professor(
    dados: ProfessorCreate,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    professor = Professor(escola_id=escola_id, **dados.model_dump())
    db.add(professor)
    registrar(db, "professor.criado", escola_id=escola_id, usuario_id=usuario.id,
              entidade="professor", detalhes={"nome": dados.nome})
    db.commit()
    db.refresh(professor)
    return professor
