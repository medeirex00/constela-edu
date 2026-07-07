from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import escola_autorizada, exigir_papeis, get_usuario_atual
from app.models import (
    Aluno,
    Escola,
    Leitura,
    Matricula,
    Nota,
    Professor,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
    Usuario,
)
from app.schemas import (
    AcaoAlunos,
    AlunoCreate,
    AlunoGestaoOut,
    AlunoOut,
    AlunoPerfilOut,
    AlunoUpdate,
    ExclusaoPermanenteAlunos,
    ProfessorCreate,
    ProfessorOut,
    TurmaCreate,
    TurmaOut,
    TurmaUpdate,
)
from app.services import scoring
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
    ano_escolar = ""
    if matricula:
        saida.turma = matricula[1].nome
        saida.ano_escolar = matricula[1].ano_escolar
        ano_escolar = matricula[1].ano_escolar

    # Distribuição de leitura por faixa de dificuldade (gráfico + estatísticas)
    snap_e = db.execute(
        select(SnapshotElefante)
        .where(SnapshotElefante.escola_id == escola_id,
               SnapshotElefante.aluno_id == aluno_id)
        .order_by(SnapshotElefante.id.desc()).limit(1)
    ).scalar_one_or_none()
    leitura_niveis = scoring.distribuicao_niveis(
        db, escola_id, snap_e.livros_por_nivel if snap_e else {}, ano_escolar)

    return AlunoPerfilOut(
        aluno=saida,
        nota_matific=nota.nota_matific if nota else 0.0,
        nota_elefante=nota.nota_elefante if nota else 0.0,
        nota_geral=nota.nota_geral if nota else 0.0,
        posicao=nota.posicao if nota else None,
        detalhes=nota.detalhes if nota else {},
        calculada_em=nota.calculada_em if nota else None,
        leitura_niveis=leitura_niveis,
    )


# --- Gestão de alunos: editar, arquivar/reativar, transferir, excluir --------

def _aluno_da_escola(db: Session, escola_id: int, aluno_id: int) -> Aluno:
    aluno = db.get(Aluno, aluno_id)
    if aluno is None or aluno.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aluno não encontrado.")
    return aluno


def _alunos_selecionados(db: Session, escola_id: int, aluno_ids: list[int]) -> list[Aluno]:
    """Alunos da lista que PERTENCEM a esta escola (ignora ids de fora)."""
    alunos = db.execute(
        select(Aluno).where(Aluno.id.in_(aluno_ids), Aluno.escola_id == escola_id)
    ).scalars().all()
    if not alunos:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nenhum aluno válido selecionado.")
    return alunos


def _recalcular_escola(db: Session, escola_id: int) -> None:
    """Recalcula notas/rankings e invalida o cache do painel — dashboards,
    estatísticas e gráficos se atualizam sem recarregar a página."""
    from app.routers.publico import invalidar_cache_painel
    scoring.recalcular_escola(db, escola_id)
    invalidar_cache_painel(escola_id)


@router.patch("/alunos/{aluno_id}", response_model=AlunoOut)
def atualizar_aluno(
    aluno_id: int,
    dados: AlunoUpdate,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Edita o cadastro (nome, nº de chamada, nascimento, observações)."""
    aluno = _aluno_da_escola(db, escola_id, aluno_id)
    campos = dados.model_dump(exclude_unset=True)
    if not campos:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nada para atualizar.")
    if campos.get("nome"):
        campos["nome"] = campos["nome"].strip()
    for chave, valor in campos.items():
        setattr(aluno, chave, valor)
    registrar(db, "aluno.atualizado", escola_id=escola_id, usuario_id=usuario.id,
              entidade="aluno", entidade_id=aluno.id,
              detalhes={"nome": aluno.nome, "campos": sorted(campos.keys())})
    db.commit()
    db.refresh(aluno)
    ano = _ano_ativo(db, escola_id)
    turma = db.execute(
        select(Turma).join(Matricula, Matricula.turma_id == Turma.id)
        .where(Matricula.aluno_id == aluno.id, Matricula.ano_letivo == ano)
    ).scalar_one_or_none()
    saida = AlunoOut.model_validate(aluno)
    if turma:
        saida.turma = turma.nome
        saida.ano_escolar = turma.ano_escolar
    return saida


_STATUS_ACAO = {"arquivar": "arquivado", "reativar": "ativo", "excluir": "excluido"}


@router.post("/alunos/acoes", response_model=dict)
def acoes_em_alunos(
    dados: AcaoAlunos,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Ações em massa (ou individual): arquivar, reativar, excluir (lógico) e
    transferir de turma. Ao final recalcula notas/rankings e invalida o cache."""
    alunos = _alunos_selecionados(db, escola_id, dados.aluno_ids)
    ids = [a.id for a in alunos]
    ano = _ano_ativo(db, escola_id)

    if dados.acao == "transferir":
        if not dados.turma_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Selecione a turma de destino.")
        turma = _turma_da_escola(db, escola_id, dados.turma_id)
        db.execute(
            update(Matricula)
            .where(Matricula.aluno_id.in_(ids), Matricula.ano_letivo == ano)
            .values(turma_id=turma.id)
        )
        # Alunos sem matrícula no ano ativo ganham uma nova na turma destino.
        com_matricula = set(db.execute(
            select(Matricula.aluno_id)
            .where(Matricula.aluno_id.in_(ids), Matricula.ano_letivo == ano)
        ).scalars().all())
        for aid in ids:
            if aid not in com_matricula:
                db.add(Matricula(escola_id=escola_id, aluno_id=aid,
                                 turma_id=turma.id, ano_letivo=ano))
        registrar(db, "aluno.transferido", escola_id=escola_id, usuario_id=usuario.id,
                  entidade="aluno", detalhes={"alunos": ids, "turma_id": turma.id,
                                              "turma": turma.nome})
        mensagem = f"{len(ids)} aluno(s) transferido(s) para {turma.nome}."
        recalcular = False  # a nota não muda; só a turma/contagem
    else:
        novo_status = _STATUS_ACAO[dados.acao]
        for aluno in alunos:
            aluno.status = novo_status
        registrar(db, f"aluno.{dados.acao}", escola_id=escola_id, usuario_id=usuario.id,
                  entidade="aluno", detalhes={"alunos": ids, "status": novo_status})
        rotulos = {"arquivar": "arquivado(s)", "reativar": "reativado(s)",
                   "excluir": "excluído(s)"}
        mensagem = f"{len(ids)} aluno(s) {rotulos[dados.acao]}."
        recalcular = True  # muda o conjunto de alunos ativos → rankings mudam

    db.commit()
    if recalcular:
        _recalcular_escola(db, escola_id)
    else:
        from app.routers.publico import invalidar_cache_painel
        invalidar_cache_painel(escola_id)
    return {"mensagem": mensagem, "afetados": len(ids)}


@router.post("/alunos/excluir-permanente", response_model=dict)
def excluir_alunos_permanente(
    dados: ExclusaoPermanenteAlunos,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Exclusão FÍSICA e IRREVERSÍVEL: remove o aluno e TODOS os registros
    vinculados (leituras, snapshots Matific/Elefante, notas, matrículas).
    Exige confirmação textual ("EXCLUIR"). A auditoria é preservada (§17)."""
    if dados.confirmacao.strip().upper() != "EXCLUIR":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Confirmação inválida. Digite EXCLUIR para confirmar a exclusão "
            "permanente e irreversível.")
    alunos = _alunos_selecionados(db, escola_id, dados.aluno_ids)
    ids = [a.id for a in alunos]
    nomes = {a.id: a.nome for a in alunos}

    # Apaga os filhos ANTES do aluno (nenhuma FK tem cascade automático).
    db.execute(delete(Leitura).where(Leitura.aluno_id.in_(ids)))
    db.execute(delete(SnapshotMatific).where(SnapshotMatific.aluno_id.in_(ids)))
    db.execute(delete(SnapshotElefante).where(SnapshotElefante.aluno_id.in_(ids)))
    db.execute(delete(Nota).where(Nota.aluno_id.in_(ids)))
    db.execute(delete(Matricula).where(Matricula.aluno_id.in_(ids)))
    # Auditoria ANTES de apagar o aluno (entidade_id fica só como referência).
    for aid in ids:
        registrar(db, "aluno.excluido_permanente", escola_id=escola_id,
                  usuario_id=usuario.id, entidade="aluno", entidade_id=aid,
                  detalhes={"nome": nomes[aid], "tipo": "exclusao_permanente"})
    db.execute(delete(Aluno).where(Aluno.id.in_(ids)))
    db.commit()

    _recalcular_escola(db, escola_id)
    return {"mensagem": f"{len(ids)} aluno(s) excluído(s) permanentemente, com "
                        "todos os dados vinculados.", "afetados": len(ids)}


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


def _ordem_alunos(ordenar: str) -> list:
    """Cláusulas ORDER BY portáveis (SQLite/Postgres) por critério do painel.
    Os ".is_(None)" jogam os NULOS para o fim de forma independente do banco."""
    if ordenar == "data":
        return [Aluno.created_at.desc()]
    if ordenar == "chamada":
        return [Aluno.numero_chamada.is_(None), Aluno.numero_chamada.asc()]
    if ordenar == "desempenho":
        return [Nota.nota_geral.is_(None), Nota.nota_geral.desc()]
    # "nome" | "alfabetica" | "serie" (numa turma a série é única) | padrão
    return [Aluno.nome.asc()]


@router.get("/turmas/{turma_id}/alunos", response_model=list[AlunoGestaoOut])
def listar_alunos_da_turma(
    turma_id: int,
    escola_id: int = Depends(escola_autorizada),
    busca: str | None = Query(default=None),
    ordenar: str = Query(default="nome"),
    incluir_inativos: bool = Query(default=False),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Alunos da turma para o painel de gestão: com nota, posição e data de
    cadastro; busca por nome e ordenação. `incluir_inativos` traz também os
    arquivados/excluídos (para restaurar ou apagar de vez)."""
    turma = _turma_da_escola(db, escola_id, turma_id)
    consulta = (
        select(Aluno, Nota)
        .join(Matricula, Matricula.aluno_id == Aluno.id)
        .outerjoin(Nota, (Nota.aluno_id == Aluno.id)
                   & (Nota.ano_letivo == turma.ano_letivo))
        .where(Aluno.escola_id == escola_id,
               Matricula.turma_id == turma_id,
               Matricula.ano_letivo == turma.ano_letivo)
    )
    if not incluir_inativos:
        consulta = consulta.where(Aluno.status == "ativo")
    if busca:
        consulta = consulta.where(Aluno.nome.ilike(f"%{busca}%"))
    consulta = consulta.order_by(*_ordem_alunos(ordenar), Aluno.nome.asc())

    saida = []
    for aluno, nota in db.execute(consulta).all():
        item = AlunoGestaoOut.model_validate(aluno)
        item.turma = turma.nome
        item.ano_escolar = turma.ano_escolar
        item.nota_geral = nota.nota_geral if nota else None
        item.posicao = nota.posicao if nota else None
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
