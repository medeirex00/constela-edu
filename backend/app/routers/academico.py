from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import escola_autorizada, exigir_papeis, get_usuario_atual
from app.models import (
    Aluno,
    Escola,
    Leitura,
    Livro,
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
    FusaoAlunos,
    ProfessorCompletoIn,
    ProfessorCreate,
    ProfessorOut,
    TurmaCreate,
    TurmaOut,
    TurmaUpdate,
)
from app.services import periodos, permissoes, scoring
from app.services.audit import registrar

router = APIRouter(prefix="/escolas/{escola_id}", tags=["Acadêmico"])


def _ano_ativo(db: Session, escola_id: int) -> int:
    escola = db.get(Escola, escola_id)
    if escola is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Escola não encontrada.")
    return escola.ano_letivo_ativo


def _blindar_superficial(saida: AlunoOut) -> AlunoOut:
    """Professor vê APENAS dados superficiais do aluno (posição no ranking e
    pontos — modelo de permissões, permissoes.py). data_nascimento e observacoes
    (campo livre, potencialmente sensível) pertencem ao cadastro, não à visão
    superficial: são zerados antes de sair na resposta."""
    saida.data_nascimento = None
    saida.observacoes = None
    return saida


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
    # Professor: enxerga apenas os alunos das turmas designadas a ele.
    permitidas = permissoes.turmas_permitidas(db, escola_id, usuario)
    if permitidas is not None:
        consulta = consulta.where(Turma.id.in_(permitidas))

    total = db.execute(
        select(func.count()).select_from(consulta.order_by(None).subquery())
    ).scalar_one()
    linhas = db.execute(
        consulta.order_by(Aluno.nome).offset((pagina - 1) * por_pagina).limit(por_pagina)
    ).all()

    superficial = not permissoes.acesso_total(usuario)
    itens = []
    for aluno, turma in linhas:
        item = AlunoOut.model_validate(aluno)
        item.turma = turma.nome
        item.ano_escolar = turma.ano_escolar
        if superficial:
            _blindar_superficial(item)
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

    # Ficha cadastral: só as chaves conhecidas (mesmas da Lista Piloto) e
    # valores curtos — nada de dados arbitrários no JSON.
    from app.services.lista_piloto import ROTULOS_FICHA
    ficha = {chave: str(valor).strip()[:300]
             for chave, valor in (dados.ficha or {}).items()
             if chave in ROTULOS_FICHA and str(valor).strip()}

    aluno = Aluno(
        escola_id=escola_id,
        nome=dados.nome.strip(),
        numero_chamada=dados.numero_chamada,
        data_nascimento=dados.data_nascimento,
        observacoes=dados.observacoes,
        ficha=ficha,
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
    """Perfil com a explicação completa da nota (PRD §45, §54).

    Professor: só alunos das turmas dele, e em versão SUPERFICIAL (posição no
    ranking geral e pontos — sem o detalhamento do cálculo nem leituras)."""
    ano = _ano_ativo(db, escola_id)
    aluno = db.get(Aluno, aluno_id)
    if aluno is None or aluno.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aluno não encontrado.")
    permissoes.exigir_aluno_permitido(db, escola_id, ano, usuario, aluno_id)
    superficial = not permissoes.acesso_total(usuario)

    matricula = db.execute(
        select(Matricula, Turma)
        .join(Turma, Matricula.turma_id == Turma.id)
        .where(Matricula.aluno_id == aluno_id, Matricula.ano_letivo == ano)
    ).first()
    nota = db.execute(
        select(Nota).where(Nota.aluno_id == aluno_id, Nota.ano_letivo == ano)
    ).scalar_one_or_none()

    saida = AlunoOut.model_validate(aluno)
    if superficial:
        _blindar_superficial(saida)
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
        # Professor vê o superficial: notas e posição — sem o passo a passo do
        # cálculo nem a distribuição de leituras.
        detalhes=(nota.detalhes if nota else {}) if not superficial else {},
        calculada_em=nota.calculada_em if nota else None,
        leitura_niveis=leitura_niveis if not superficial else None,
        ficha=(aluno.ficha or {}) if not superficial else {},
    )


# --- Histórico de leituras por período (base das premiações) ----------------

@router.get("/alunos/{aluno_id}/leituras", response_model=dict)
def historico_leituras(
    aluno_id: int,
    escola_id: int = Depends(escola_autorizada),
    periodo: str = Query(default="tudo"),
    inicio: str | None = Query(default=None),
    fim: str | None = Query(default=None),
    dia: str | None = Query(default=None),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Histórico CRONOLÓGICO de leituras do aluno, filtrado por período:
    um preset ("hoje", "este bimestre"...), um intervalo `inicio`/`fim`
    (AAAA-MM-DD) ou um único `dia`. Cada leitura traz livro, nível, plataforma,
    data/hora, tempo e pontos de dificuldade.

    Dado ESPECÍFICO ("quando o aluno leu X livro"): professor não acessa."""
    permissoes.negar_restrito(db, escola_id, usuario)
    aluno = _aluno_da_escola(db, escola_id, aluno_id)
    ano = _ano_ativo(db, escola_id)
    try:
        if dia:
            d = periodos._parse_data(dia)
            ini, fim_dt, rotulo = periodos.resolver("personalizado", date.today(), ano, d, d)
            chave = "dia"
        else:
            ini, fim_dt, rotulo = periodos.resolver(
                periodo, date.today(), ano,
                periodos._parse_data(inicio), periodos._parse_data(fim))
            chave = periodo
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Data inválida (use o formato AAAA-MM-DD).") from exc

    consulta = (
        select(Leitura, Livro)
        .join(Livro, Leitura.livro_id == Livro.id)
        .where(Leitura.aluno_id == aluno.id)
    )
    if ini is not None:
        consulta = consulta.where(Leitura.data >= ini)
    if fim_dt is not None:
        consulta = consulta.where(Leitura.data <= fim_dt)
    consulta = consulta.order_by(Leitura.data.desc(), Leitura.id.desc())

    pontos_map = scoring.pontos_por_codigo(db, escola_id)
    itens = []
    for leitura, livro in db.execute(consulta).all():
        codigo = (livro.nivel_codigo or "").upper()
        itens.append({
            "id": leitura.id,
            "livro": livro.titulo,
            "nivel": livro.nivel_codigo,
            "categoria": livro.categoria,
            "plataforma": "elefante",
            "data": leitura.data.isoformat(),
            "tempo_leitura_min": leitura.tempo_leitura_min,
            "pontos": round(pontos_map.get(codigo, 0.0), 2),
        })
    resumo = {
        "total_livros": len(itens),
        "pontos": round(sum(i["pontos"] for i in itens), 2),
        "tempo_total_min": sum((i["tempo_leitura_min"] or 0) for i in itens),
    }
    return {
        "periodo": {"chave": chave, "rotulo": rotulo,
                    "inicio": ini.isoformat() if ini else None,
                    "fim": fim_dt.isoformat() if fim_dt else None},
        "resumo": resumo,
        "itens": itens,
    }


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

    # Apaga os filhos Edu explicitamente (mantém a ordem do recálculo/log);
    # os demais filhos (Quest, responsáveis) somem por ON DELETE CASCADE
    # (migração 0003) quando o aluno é deletado.
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

    # Direito ao esquecimento (LGPD): remove conversas do assistente que citem o
    # nome COMPLETO de algum aluno excluído (escopo da escola; a cascata da 0003
    # apaga as mensagens). Dados da IA são derivados — a fonte oficial já sumiu.
    from app.models import ConversaIA, MensagemIA
    ids_conversas: set[int] = set()
    for nome in {nomes[aid] for aid in ids if nomes[aid] and nomes[aid].strip()}:
        ids_conversas.update(db.execute(
            select(ConversaIA.id)
            .join(MensagemIA, MensagemIA.conversa_id == ConversaIA.id)
            .where(ConversaIA.escola_id == escola_id,
                   MensagemIA.conteudo.icontains(nome, autoescape=True))
        ).scalars())
    if ids_conversas:
        db.execute(delete(ConversaIA).where(ConversaIA.id.in_(ids_conversas)))
        registrar(db, "ia.conversas_esquecimento", escola_id=escola_id,
                  usuario_id=usuario.id,
                  detalhes={"conversas_removidas": len(ids_conversas),
                            "motivo": "exclusao_permanente_aluno"})
    db.commit()

    _recalcular_escola(db, escola_id)
    return {"mensagem": f"{len(ids)} aluno(s) excluído(s) permanentemente, com "
                        "todos os dados vinculados.", "afetados": len(ids)}


@router.post("/alunos/fundir", response_model=dict)
def fundir_alunos(
    dados: FusaoAlunos,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Funde dois cadastros do MESMO aluno (duplicados).

    Junta no `manter` TUDO do `remover` — snapshots Matific e Elefante,
    leituras, matrículas, notas e também o lado Quest (perfil + telemetria,
    credencial e responsáveis) — e apaga o `remover`. É o caso do aluno cujos
    dados vieram separados (Matific num cadastro, Elefante noutro).

    Conflitos são resolvidos sem perder nem duplicar:
      * leitura do mesmo livro nos dois → mantém uma (a releitura nunca
        pontua duas vezes, §35);
      * matrícula no mesmo ano nos dois → mantém a do `manter` (a turma
        dele prevalece);
      * perfil/credencial Quest é único por aluno → migra (com toda a
        telemetria) se o `manter` não tiver; se ambos tiverem, prevalece o do
        `manter` e o do `remover` é descartado (contado no log);
      * campos vazios do `manter` (foto, nº de chamada, nascimento,
        observações) são preenchidos com os do `remover`.
    Irreversível → exige confirmação textual "FUNDIR". Recalcula ao final."""
    if dados.confirmacao.strip().upper() != "FUNDIR":
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Confirmação inválida. Digite FUNDIR para confirmar.")
    if dados.manter_id == dados.remover_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Escolha dois alunos diferentes para fundir.")
    manter = _aluno_da_escola(db, escola_id, dados.manter_id)
    remover = _aluno_da_escola(db, escola_id, dados.remover_id)
    # Só funde alunos ATIVOS: manter um arquivado/excluído absorvendo um ativo
    # faria o aluno sumir de todas as telas (que filtram status "ativo").
    if manter.status != "ativo" or remover.status != "ativo":
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Só é possível fundir alunos ativos. Reative o "
                            "cadastro arquivado ou excluído antes de fundir.")
    manter_nome, remover_nome = manter.nome, remover.nome  # antes de apagar

    # Leituras: reatribui as de livros que o `manter` ainda não tem; as
    # repetidas (mesmo livro) são descartadas para não violar a unicidade.
    livros_do_manter = set(db.execute(
        select(Leitura.livro_id).where(Leitura.aluno_id == manter.id)
    ).scalars().all())
    leituras_remover = db.execute(
        select(Leitura).where(Leitura.aluno_id == remover.id)
    ).scalars().all()
    leituras_movidas = descartadas = 0
    for leitura in leituras_remover:
        if leitura.livro_id in livros_do_manter:
            db.delete(leitura)
            descartadas += 1
        else:
            leitura.aluno_id = manter.id
            livros_do_manter.add(leitura.livro_id)
            leituras_movidas += 1

    # Snapshots das plataformas: reatribuídos INTEGRALMENTE (é aqui que o
    # Matific de um cadastro se junta ao Elefante do outro).
    snaps_matific = db.execute(
        update(SnapshotMatific).where(SnapshotMatific.aluno_id == remover.id)
        .values(aluno_id=manter.id)
    ).rowcount
    snaps_elefante = db.execute(
        update(SnapshotElefante).where(SnapshotElefante.aluno_id == remover.id)
        .values(aluno_id=manter.id)
    ).rowcount

    # Matrículas: move as de anos que o `manter` ainda não tem; nos anos em
    # que ambos têm, mantém a do `manter` e descarta a do `remover`.
    anos_do_manter = set(db.execute(
        select(Matricula.ano_letivo).where(Matricula.aluno_id == manter.id)
    ).scalars().all())
    for matricula in db.execute(
        select(Matricula).where(Matricula.aluno_id == remover.id)
    ).scalars().all():
        if matricula.ano_letivo in anos_do_manter:
            db.delete(matricula)
        else:
            matricula.aluno_id = manter.id
            anos_do_manter.add(matricula.ano_letivo)

    # Notas: mesma lógica das matrículas — migra as de anos que o `manter`
    # não tem (preserva o histórico) e descarta as de anos em comum. A do ano
    # ATIVO é reescrita pelo recálculo no fim; as de anos passados NÃO são
    # recalculadas, por isso precisam ser preservadas por migração.
    anos_nota_manter = set(db.execute(
        select(Nota.ano_letivo).where(Nota.aluno_id == manter.id)
    ).scalars().all())
    for nota in db.execute(
        select(Nota).where(Nota.aluno_id == remover.id)
    ).scalars().all():
        if nota.ano_letivo in anos_nota_manter:
            db.delete(nota)
        else:
            nota.aluno_id = manter.id

    # Lado Quest: reatribui o que é do aluno para o `manter`. Sem isto, o
    # `db.delete(remover)` cascatearia (ON DELETE CASCADE, migração 0003) e
    # apagaria em SILÊNCIO o perfil, a telemetria (tentativas/progresso), a
    # credencial e os vínculos de responsáveis do `remover`.
    from app.quest.models import (  # noqa: E402
        QuestCredencialAluno,
        QuestPerfil,
        ResponsavelAluno,
    )

    quest_perfil_movido = quest_perfil_descartado = 0
    # Perfil é único por aluno; migrar o registro leva junto TODA a telemetria
    # (progresso/habilidades/tentativas apontam para perfil_id, que não muda).
    manter_tem_perfil = db.execute(
        select(QuestPerfil.id).where(QuestPerfil.aluno_id == manter.id)
    ).scalar_one_or_none() is not None
    for perfil in db.execute(
        select(QuestPerfil).where(QuestPerfil.aluno_id == remover.id)
    ).scalars().all():
        if manter_tem_perfil:
            db.delete(perfil)                 # descarte contado (não silencioso)
            quest_perfil_descartado += 1
        else:
            perfil.aluno_id = manter.id
            manter_tem_perfil = True
            quest_perfil_movido += 1

    manter_tem_cred = db.execute(
        select(QuestCredencialAluno.id)
        .where(QuestCredencialAluno.aluno_id == manter.id)
    ).scalar_one_or_none() is not None
    for cred in db.execute(
        select(QuestCredencialAluno).where(QuestCredencialAluno.aluno_id == remover.id)
    ).scalars().all():
        if manter_tem_cred:
            db.delete(cred)
        else:
            cred.aluno_id = manter.id
            manter_tem_cred = True

    # Responsáveis: unicidade (usuario_id, aluno_id) — migra o que o `manter`
    # ainda não tem com aquele responsável; os repetidos são descartados.
    resp_do_manter = set(db.execute(
        select(ResponsavelAluno.usuario_id)
        .where(ResponsavelAluno.aluno_id == manter.id)
    ).scalars().all())
    for vinculo in db.execute(
        select(ResponsavelAluno).where(ResponsavelAluno.aluno_id == remover.id)
    ).scalars().all():
        if vinculo.usuario_id in resp_do_manter:
            db.delete(vinculo)
        else:
            vinculo.aluno_id = manter.id
            resp_do_manter.add(vinculo.usuario_id)

    # Preenche lacunas do `manter` com dados do `remover` (nunca sobrescreve).
    if not manter.foto_url and remover.foto_url:
        manter.foto_url = remover.foto_url
    if manter.numero_chamada is None and remover.numero_chamada is not None:
        manter.numero_chamada = remover.numero_chamada
    if manter.data_nascimento is None and remover.data_nascimento is not None:
        manter.data_nascimento = remover.data_nascimento
    if not manter.observacoes and remover.observacoes:
        manter.observacoes = remover.observacoes

    manter_id = manter.id
    registrar(db, "aluno.fundido", escola_id=escola_id, usuario_id=usuario.id,
              entidade="aluno", entidade_id=manter_id,
              detalhes={"mantido": {"id": manter_id, "nome": manter_nome},
                        "removido": {"id": remover.id, "nome": remover_nome},
                        "leituras_movidas": leituras_movidas,
                        "leituras_descartadas": descartadas,
                        "snapshots_matific": snaps_matific,
                        "snapshots_elefante": snaps_elefante,
                        "quest_perfil_movido": quest_perfil_movido,
                        "quest_perfil_descartado": quest_perfil_descartado})
    # Garante que as reatribuições (UPDATE aluno_id) sejam gravadas ANTES do
    # DELETE do `remover` — assim o cascade não pega nada que foi movido.
    db.flush()
    db.delete(remover)
    db.commit()

    _recalcular_escola(db, escola_id)
    return {
        "mensagem": f"“{remover_nome}” foi fundido em “{manter_nome}”. "
                    f"{leituras_movidas} leitura(s) e "
                    f"{snaps_matific + snaps_elefante} registro(s) de plataforma "
                    "combinados.",
        "aluno_id": manter_id,
        "leituras_movidas": leituras_movidas,
        "leituras_descartadas": descartadas,
        "quest_perfil_movido": quest_perfil_movido,
        "quest_perfil_descartado": quest_perfil_descartado,
    }


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
    # Professor: só as turmas designadas a ele (isto também restringe os
    # filtros de turma em todas as telas).
    permitidas = permissoes.turmas_permitidas(db, escola_id, usuario)
    if permitidas is not None:
        consulta = consulta.where(Turma.id.in_(permitidas))
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
    permitidas = permissoes.turmas_permitidas(db, escola_id, usuario)
    if permitidas is not None and turma_id not in permitidas:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Turma não encontrada.")
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
    try:
        db.flush()
        registrar(db, "turma.criada", escola_id=escola_id, usuario_id=usuario.id,
                  entidade="turma", entidade_id=turma.id, detalhes={"nome": turma.nome})
        db.commit()
    except IntegrityError:
        # Corrida na criação manual (dois gestores, mesma turma): o índice único
        # uq_turma_escola_ano_nome barra a 2ª — vira 409, não 500 nem duplicata.
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Já existe a turma “{dados.nome.strip()}” no ano letivo "
                            f"{dados.ano_letivo}.")
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
    try:
        db.commit()
    except IntegrityError:  # renomear para uma turma que já existe (índice único)
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Já existe a turma “{nome}” no ano letivo {ano_letivo}.")
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
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
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


@router.post("/professores/completo", status_code=status.HTTP_201_CREATED)
def criar_professor_completo(
    dados: ProfessorCompletoIn,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Cadastro completo do professor em um passo: o registro na equipe, a
    turma sob responsabilidade e a CONTA DE ACESSO (cargo professor) com senha
    legível gerada — devolvida uma ÚNICA vez aqui (não é armazenada; se for
    perdida, use a redefinição de senha por token). O e-mail liga a conta às
    turmas dele (é assim que o acesso restrito descobre quais turmas mostrar)."""
    from app.core.security import gerar_senha_legivel, hash_senha

    email = dados.email.strip().lower()
    turma = None
    if dados.turma_id is not None:
        turma = db.get(Turma, dados.turma_id)
        if turma is None or turma.escola_id != escola_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Turma inválida para esta escola.")

    acesso = None
    if dados.criar_acesso:
        ja_existe = db.execute(
            select(Usuario).where(func.lower(Usuario.email) == email)
        ).scalar_one_or_none()
        if ja_existe is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Já existe uma conta com este e-mail — use outro ou desligue "
                "a criação do acesso.")
        senha = gerar_senha_legivel()
        db.add(Usuario(escola_id=escola_id, nome=dados.nome.strip(), email=email,
                       senha_hash=hash_senha(senha),
                       cargo="professor"))
        # Senha legível devolvida UMA vez ao criar o acesso — nunca é
        # armazenada em texto; se for perdida, use "Redefinir senha".
        acesso = {"email": email, "senha": senha}

    professor = Professor(escola_id=escola_id, nome=dados.nome.strip(), email=email)
    db.add(professor)
    db.flush()
    if turma is not None:
        turma.professor_id = professor.id

    registrar(db, "professor.criado", escola_id=escola_id, usuario_id=usuario.id,
              entidade="professor", entidade_id=professor.id,
              detalhes={"nome": professor.nome, "turma": turma.nome if turma else None,
                        "acesso_criado": dados.criar_acesso})
    db.commit()
    db.refresh(professor)
    return {
        "professor": ProfessorOut.model_validate(professor),
        "turma": turma.nome if turma else None,
        "acesso": acesso,
    }
