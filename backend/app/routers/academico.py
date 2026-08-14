from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import bloquear_escola_para_importacao, get_db
from app.core.deps import escola_autorizada, exigir_papeis, get_usuario_atual
from app.core.tempo import hoje_br
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
    ConsolidarTurmasIn,
    CorrigirDuplicadosAlunos,
    ExclusaoPermanenteAlunos,
    ExcluirTurmas,
    FusaoAlunos,
    ProfessorCompletoIn,
    ProfessorCreate,
    ProfessorOut,
    ProfessorUpdate,
    TurmaCreate,
    TurmaOut,
    TurmaUpdate,
)
from app.services import (
    alunos_dedup,
    alunos_fusao,
    periodos,
    permissoes,
    scoring,
    turmas_dedup,
)
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
    # Mesma trava das importações: serializa a criação de alunos da MESMA escola,
    # senão dois cadastros simultâneos leem "não existe" e criam os dois. É
    # transacional (cai no commit) e no-op no SQLite.
    bloquear_escola_para_importacao(db, escola_id)
    turma = db.get(Turma, dados.turma_id)
    if turma is None or turma.escola_id != escola_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Turma inválida para esta escola.")

    # Ficha cadastral: só as chaves conhecidas (mesmas da Lista Piloto) e
    # valores curtos — nada de dados arbitrários no JSON.
    from app.services.lista_piloto import ROTULOS_FICHA
    ficha = {chave: str(valor).strip()[:300]
             for chave, valor in (dados.ficha or {}).items()
             if chave in ROTULOS_FICHA and str(valor).strip()}

    # PORTA ÚNICA DE IDENTIDADE: o cadastro manual era o último caminho que criava
    # aluno sem perguntar "essa pessoa já existe?". Passa pela MESMA resolução das
    # importações. Homônimo REAL continua podendo ser cadastrado: o veto por
    # identidade (nº de chamada / nascimento / RA divergentes) faz o candidato não
    # casar, e aí a criação segue normalmente.
    from app.routers import importacoes as imp
    ra_informado = str(ficha.get("ra", "")).strip() or None
    ja = imp._aluno_existente_na_turma(db, escola_id, ano, turma.id, dados.nome,
                                       dados.numero_chamada, dados.data_nascimento,
                                       ra_informado)
    confianca = "baixa"
    if ja is None:
        ja, confianca = imp._casar_no_roster(db, escola_id, ano, dados.nome, turma,
                                             dados.numero_chamada,
                                             dados.data_nascimento, ra_informado)
    if ja is not None:
        registrar(db, "aluno.criacao_recusada", escola_id=escola_id, usuario_id=usuario.id,
                  entidade="aluno", entidade_id=ja.id,
                  detalhes={"nome": dados.nome, "decisao": "EXACT_MATCH",
                            "motivo": "aluno_ja_cadastrado_na_turma"})
        db.commit()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"“{ja.nome}” já está cadastrado nesta turma. Use o cadastro existente. "
            "Se for outra criança de mesmo nome, informe o nº de chamada ou a data "
            "de nascimento para diferenciar.")
    if confianca == "media":
        registrar(db, "aluno.criacao_recusada", escola_id=escola_id, usuario_id=usuario.id,
                  entidade="aluno", entidade_id=None,
                  detalhes={"nome": dados.nome, "decisao": "REVIEW_REQUIRED",
                            "motivo": "correspondencia_insegura"})
        db.commit()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"“{dados.nome}” é muito parecido com um aluno já cadastrado nesta turma. "
            "Confira a lista da turma antes de cadastrar. Se for outra criança, informe "
            "o nº de chamada ou a data de nascimento para diferenciar.")

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

    Professor: só alunos das turmas dele. Vê as notas, a posição e o PASSO A
    PASSO do cálculo (liberado pelo dono); a ficha cadastral (dados pessoais) e a
    distribuição de leituras seguem restritas à gestão."""
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

    # Distribuição de leitura por faixa de dificuldade (gráfico + estatísticas).
    # Snapshot ATUAL por (data_referencia, id), não por max(id): um import
    # retroativo (backfill) grava id maior com data menor e NÃO pode virar o
    # estado atual. Mesma régua do dashboard/ranking (scoring.ids_snapshots_atuais).
    snap_e = db.execute(
        select(SnapshotElefante)
        .where(SnapshotElefante.escola_id == escola_id,
               SnapshotElefante.aluno_id == aluno_id,
               SnapshotElefante.id.in_(
                   scoring.ids_snapshots_atuais(SnapshotElefante, escola_id)))
    ).scalar_one_or_none()
    leitura_niveis = scoring.distribuicao_niveis(
        db, escola_id, snap_e.livros_por_nivel if snap_e else {}, ano_escolar)

    return AlunoPerfilOut(
        aluno=saida,
        nota_matific=nota.nota_matific if nota else 0.0,
        nota_elefante=nota.nota_elefante if nota else 0.0,
        nota_geral=nota.nota_geral if nota else 0.0,
        posicao=nota.posicao if nota else None,
        # O professor também vê o PASSO A PASSO do cálculo (liberado pelo dono) —
        # só das crianças das turmas dele (exigir_aluno_permitido acima barra as
        # de fora). A ficha cadastral (dados pessoais) e as leituras seguem só p/
        # gestão.
        detalhes=(nota.detalhes if nota else {}),
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
    permissoes.negar_dado_individual(db, escola_id, usuario)
    aluno = _aluno_da_escola(db, escola_id, aluno_id)
    ano = _ano_ativo(db, escola_id)
    try:
        if dia:
            d = periodos._parse_data(dia)
            ini, fim_dt, rotulo = periodos.resolver("personalizado", hoje_br(), ano, d, d)
            chave = "dia"
        else:
            ini, fim_dt, rotulo = periodos.resolver(
                periodo, hoje_br(), ano,
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

    # Pontos resolvidos pela TURMA do aluno (TURMA>SÉRIE>padrão) — mesma régua do
    # ranking anual, não a pontuação padrão da escola.
    mat = db.execute(
        select(Turma.id, Turma.ano_escolar)
        .join(Matricula, Matricula.turma_id == Turma.id)
        .where(Matricula.aluno_id == aluno.id, Matricula.ano_letivo == ano)
    ).first()
    _turma_id, _ano_escolar = (mat[0], mat[1]) if mat else (None, None)
    pontos_map = scoring.pontos_por_codigo(db, escola_id, _turma_id, _ano_escolar)
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


def _anonimizar_logs_do_aluno(db: Session, escola_id: int,
                              aluno_ids: list[int], nomes: set[str]) -> None:
    """Redige o nome civil das entradas ANTERIORES do log de auditoria que se
    referem ao aluno excluído (LGPD/esquecimento).

    Escopo: entradas cujo ``entidade_id`` é o próprio aluno (criação, edição,
    fusão em que ele foi o mantido). O ``entidade_id`` permanece como referência
    ANÔNIMA (o registro do "quê/quando/por quem" é preservado para auditoria);
    apenas o nome em texto claro é trocado por ``"[removido]"``."""
    from app.models import LogAuditoria  # noqa: E402
    nomes_limpos = {n for n in nomes if n and n.strip()}

    def _redigir(valor):
        if isinstance(valor, dict):
            return {chave: ("[removido]" if chave == "nome" else _redigir(v))
                    for chave, v in valor.items()}
        if isinstance(valor, list):
            return [_redigir(v) for v in valor]
        if isinstance(valor, str) and valor in nomes_limpos:
            return "[removido]"
        return valor

    logs = db.execute(
        select(LogAuditoria).where(
            LogAuditoria.escola_id == escola_id,
            LogAuditoria.entidade == "aluno",
            LogAuditoria.entidade_id.in_(aluno_ids),
        )
    ).scalars().all()
    for log in logs:
        if log.detalhes:
            log.detalhes = _redigir(log.detalhes)  # reatribui → dirty tracking


def _apagar_alunos_e_dados(db: Session, escola_id: int, usuario: Usuario,
                           aluno_ids: list[int]) -> int:
    """Exclusão FÍSICA de alunos + TODOS os dados vinculados (leituras, snapshots
    Matific/Elefante, notas, matrículas) e — LGPD/direito ao esquecimento — as
    conversas da IA que citem o nome. Auditado (§17). NÃO commita nem recalcula:
    o chamador decide. Reusado pela exclusão permanente e pela exclusão de turma
    com alunos. Devolve quantos alunos foram removidos."""
    nomes = {a.id: a.nome for a in db.execute(
        select(Aluno).where(Aluno.escola_id == escola_id, Aluno.id.in_(aluno_ids))
    ).scalars()}
    ids = list(nomes)
    if not ids:
        return 0
    # Filhos Edu explícitos (ordem p/ recálculo/log); Quest/responsáveis somem
    # por ON DELETE CASCADE (migração 0003) ao deletar o aluno.
    db.execute(delete(Leitura).where(Leitura.aluno_id.in_(ids)))
    db.execute(delete(SnapshotMatific).where(SnapshotMatific.aluno_id.in_(ids)))
    db.execute(delete(SnapshotElefante).where(SnapshotElefante.aluno_id.in_(ids)))
    db.execute(delete(Nota).where(Nota.aluno_id.in_(ids)))
    db.execute(delete(Matricula).where(Matricula.aluno_id.in_(ids)))
    # LGPD/esquecimento: NÃO gravar o nome da criança no log permanente (o
    # entidade_id basta como referência; o nome, uma vez apagado, não deve
    # sobreviver em texto claro). Guarda só a contagem por lote.
    for aid in ids:
        registrar(db, "aluno.excluido_permanente", escola_id=escola_id,
                  usuario_id=usuario.id, entidade="aluno", entidade_id=aid,
                  detalhes={"tipo": "exclusao_permanente"})
    # E anonimiza as entradas ANTERIORES do log que citam o nome deste aluno
    # (criação/edição/fusão/importação) — sem isso o nome civil do menor
    # persistiria para sempre no histórico de auditoria.
    _anonimizar_logs_do_aluno(db, escola_id, ids, set(nomes.values()))
    db.execute(delete(Aluno).where(Aluno.id.in_(ids)))

    # LGPD: esquecimento das conversas da IA que citem o nome COMPLETO de algum
    # aluno excluído (a cascata da 0003 apaga as mensagens).
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
    return len(ids)


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
    n = _apagar_alunos_e_dados(db, escola_id, usuario, [a.id for a in alunos])
    db.commit()
    _recalcular_escola(db, escola_id)
    return {"mensagem": f"{n} aluno(s) excluído(s) permanentemente, com "
                        "todos os dados vinculados.", "afetados": n}


@router.post("/alunos/fundir", response_model=dict)
def fundir_alunos(
    dados: FusaoAlunos,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Funde dois cadastros do MESMO aluno (duplicados).

    Junta no `manter` TUDO do `remover` — snapshots Matific e Elefante,
    leituras, matrículas, notas, a linha do tempo de eventos, o vínculo de
    identidade externa (UUID das plataformas) e também o lado Quest (perfil +
    telemetria, credencial e responsáveis) — e apaga o `remover`. É o caso do
    aluno cujos dados vieram separados (Matific num cadastro, Elefante noutro).

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

    # Núcleo compartilhado com a fusão em lote (Fundir duplicatas): reatribui/
    # deduplica cada relação, funde a ficha, registra a auditoria (com a foto
    # pré-fusão) e apaga o `remover`. Não commita nem recalcula — isso é aqui.
    r = alunos_fusao.fundir_par(db, escola_id, manter, remover, usuario.id)
    db.commit()
    _recalcular_escola(db, escola_id)
    return {
        "mensagem": f"“{r['remover_nome']}” foi fundido em “{r['manter_nome']}”. "
                    f"{r['leituras_movidas']} leitura(s) e "
                    f"{r['snapshots_matific'] + r['snapshots_elefante']} "
                    "registro(s) de plataforma combinados.",
        **r,
    }


@router.get("/alunos/duplicados", response_model=dict)
def alunos_duplicados(
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """PRÉVIA da fusão em lote (read-only): candidatos a aluno duplicado por
    nível de confiança (nome idêntico/subconjunto/abreviação + MESMA turma).
    Nada é alterado; o gestor marca quais confirmar. Admin global e coordenador
    da PRÓPRIA escola veem. A Secretaria (rede) é barrada: a prévia lista NOMES
    de criança (LGPD) — escola_autorizada só nega a ESCRITA, não este GET."""
    permissoes.negar_dado_individual(db, escola_id, usuario)
    candidatos = alunos_dedup.plano_deduplicacao(db, escola_id)
    return {"candidatos": candidatos, "total": len(candidatos),
            "alta": sum(1 for c in candidatos if c["confianca"] == "alta"),
            "provavel": sum(1 for c in candidatos if c["confianca"] == "provavel"),
            "revisar": sum(1 for c in candidatos if c["confianca"] == "revisar")}


@router.post("/alunos/duplicados/corrigir", response_model=dict)
def corrigir_alunos_duplicados(
    dados: CorrigirDuplicadosAlunos,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Aplica só as fusões CONFIRMADAS (``loser_ids``), par-a-par, numa única
    transação — UM commit e UM recálculo de escola no fim. Cada par vira um log
    ``aluno.fundido`` (com a foto pré-fusão); falhas individuais são reportadas
    sem abortar o lote. Irreversível → exige confirmação "FUNDIR"."""
    if dados.confirmacao.strip().upper() != "FUNDIR":
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Confirmação inválida. Digite FUNDIR para confirmar.")
    resultado = alunos_dedup.aplicar_deduplicacao(
        db, escola_id, dados.loser_ids, usuario.id)
    registrar(db, "aluno.duplicados_corrigidos", escola_id=escola_id,
              usuario_id=usuario.id, entidade="escola", entidade_id=escola_id,
              detalhes={"fusoes": resultado["fundidos"],
                        "falhas": len(resultado["falhas"])})
    db.commit()
    if resultado["fundidos"]:
        _recalcular_escola(db, escola_id)
    n = resultado["fundidos"]
    return {**resultado,
            "mensagem": (f"{n} fusão(ões) aplicada(s)." if n
                         else "Nenhuma fusão aplicada.")}


# A fusão AUTOMÁTICA do passivo foi removida (revisão adversarial: nenhum sinal é
# seguro o bastante para fundir/deletar registro de criança sem revisão humana).
# O passivo é resolvido pela ferramenta MANUAL acima (detecção + Selecionar todos).


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
    # Contagem CRUA (qualquer ano/situação): é o que a exclusão enxerga.
    saida.total_matriculas = db.execute(
        select(func.count()).select_from(Matricula)
        .where(Matricula.turma_id == turma.id)
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
    # Matrículas CRUAS por turma (qualquer ano/situação) — subconsulta
    # correlacionada para não conflitar com o JOIN filtrado do total_alunos.
    sub_matriculas = (
        select(func.count())
        .select_from(Matricula)
        .where(Matricula.turma_id == Turma.id)
        .correlate(Turma)
        .scalar_subquery()
    )
    consulta = (
        select(Turma, Professor.nome, func.count(Aluno.id), sub_matriculas)
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
    for turma, professor_nome, total_alunos, total_matriculas in db.execute(consulta).all():
        item = TurmaOut.model_validate(turma)
        item.professor_nome = professor_nome
        item.total_alunos = total_alunos
        item.total_matriculas = total_matriculas
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


def _excluir_turmas(db: Session, escola_id: int, usuario: Usuario,
                    turma_ids: list[int], com_alunos: bool) -> dict:
    """Exclui turmas (validadas por escola).

    Com ``com_alunos``: apaga fisicamente (com todos os dados) SOMENTE os alunos
    cujas matrículas estão TODAS dentro das turmas selecionadas. Um aluno que
    ainda tenha matrícula em OUTRA turma (ex.: o ano letivo ativo, quando se
    exclui uma turma antiga) NÃO é apagado — é apenas DESVINCULADO das turmas
    excluídas, preservando a ficha e os dados dos outros anos. Isso evita apagar
    permanentemente a criança e os dados atuais dela ao limpar um histórico.

    Sem ``com_alunos``: as turmas com QUALQUER matrícula ficam BLOQUEADAS (só as
    vazias são excluídas). Recalcula uma vez ao final se algum aluno foi afetado.
    Devolve: excluidas, bloqueadas, alunos_excluidos, alunos_desvinculados."""
    turmas = list(db.execute(
        select(Turma).where(Turma.escola_id == escola_id, Turma.id.in_(turma_ids))
    ).scalars())
    if not turmas:
        return {"excluidas": 0, "bloqueadas": 0, "alunos_excluidos": 0,
                "alunos_desvinculados": 0}
    ids = [t.id for t in turmas]
    # Alunos com matrícula (qualquer ano/situação) em alguma das turmas.
    aluno_ids = list(db.execute(
        select(Matricula.aluno_id).where(Matricula.turma_id.in_(ids)).distinct()
    ).scalars())

    a_excluir = turmas
    bloqueadas = 0
    alunos_excluidos = 0
    alunos_desvinculados = 0
    if aluno_ids:
        if com_alunos:
            # Quem AINDA tem matrícula fora do conjunto excluído é preservado.
            ainda = set(db.execute(
                select(Matricula.aluno_id).where(
                    Matricula.aluno_id.in_(aluno_ids),
                    Matricula.turma_id.notin_(ids),
                ).distinct()
            ).scalars())
            apagar = [aid for aid in aluno_ids if aid not in ainda]
            if apagar:
                # Só destes as matrículas estão todas nas turmas excluídas.
                alunos_excluidos = _apagar_alunos_e_dados(db, escola_id, usuario, apagar)
            if ainda:
                # Remove APENAS o vínculo com as turmas excluídas (mantém o aluno).
                db.execute(delete(Matricula).where(
                    Matricula.aluno_id.in_(ainda), Matricula.turma_id.in_(ids)))
                alunos_desvinculados = len(ainda)
                registrar(db, "turma.alunos_desvinculados", escola_id=escola_id,
                          usuario_id=usuario.id,
                          detalhes={"turmas": ids, "alunos": alunos_desvinculados,
                                    "motivo": "exclusao_turma_com_alunos_matriculado_em_outra"})
        else:
            com = set(db.execute(
                select(Matricula.turma_id).where(Matricula.turma_id.in_(ids)).distinct()
            ).scalars())
            a_excluir = [t for t in turmas if t.id not in com]
            bloqueadas = len(turmas) - len(a_excluir)

    for t in a_excluir:
        registrar(db, "turma.excluida", escola_id=escola_id, usuario_id=usuario.id,
                  entidade="turma", entidade_id=t.id,
                  detalhes={"nome": t.nome, "com_alunos": com_alunos})
        db.delete(t)
    db.commit()
    if alunos_excluidos or alunos_desvinculados:
        _recalcular_escola(db, escola_id)
    return {"excluidas": len(a_excluir), "bloqueadas": bloqueadas,
            "alunos_excluidos": alunos_excluidos,
            "alunos_desvinculados": alunos_desvinculados}


@router.delete("/turmas/{turma_id}", response_model=dict)
def excluir_turma(
    turma_id: int,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
    com_alunos: bool = Query(default=False),
):
    """Exclusão definitiva de uma turma. Por padrão é BLOQUEADA se houver alunos
    vinculados (arquive para preservar o histórico). Com ``com_alunos=true``,
    remove TAMBÉM os alunos matriculados na turma e todos os seus dados
    (leituras, snapshots, notas, matrículas) — irreversível."""
    turma = _turma_da_escola(db, escola_id, turma_id)
    nome = turma.nome
    if not com_alunos:
        # Trava clássica: sem alunos → exclui; com alunos → 409 orientando a
        # mover/remover, arquivar, ou usar com_alunos=true (apagar tudo).
        vinculados = db.execute(
            select(func.count()).select_from(Matricula)
            .where(Matricula.turma_id == turma.id)
        ).scalar_one()
        if vinculados:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"A turma “{nome}” possui {vinculados} aluno(s) vinculado(s). "
                "Mova ou remova os alunos antes de excluir — ou exclua a turma "
                "junto com os alunos, ou arquive a turma para preservar o "
                "histórico.")
    r = _excluir_turmas(db, escola_id, usuario, [turma.id], com_alunos)
    msg = f"Turma “{nome}” excluída"
    if r["alunos_excluidos"]:
        msg += f" com {r['alunos_excluidos']} aluno(s) e todos os dados"
    if r["alunos_desvinculados"]:
        msg += (f" ({r['alunos_desvinculados']} aluno(s) mantido(s) por ainda "
                "estarem em outra turma)")
    msg += "."
    return {"mensagem": msg, **r}


@router.post("/turmas/excluir", response_model=dict)
def excluir_turmas_massa(
    dados: ExcluirTurmas,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Exclusão em massa de turmas (botão 'excluir selecionadas'). Com
    ``com_alunos``, remove também os alunos e seus dados. Sem, as turmas com
    alunos são mantidas e reportadas em ``bloqueadas``."""
    r = _excluir_turmas(db, escola_id, usuario, dados.turma_ids, dados.com_alunos)
    partes = [f"{r['excluidas']} turma(s) excluída(s)"]
    if r["alunos_excluidos"]:
        partes.append(f"{r['alunos_excluidos']} aluno(s) e todos os dados removidos")
    if r["alunos_desvinculados"]:
        partes.append(f"{r['alunos_desvinculados']} aluno(s) mantido(s) por ainda "
                      "estarem em outra turma")
    if r["bloqueadas"]:
        partes.append(f"{r['bloqueadas']} com alunos foram mantida(s) — use "
                      "‘excluir com os alunos’ para removê-las")
    return {"mensagem": "; ".join(partes) + ".", **r}


@router.get("/turmas/duplicadas", response_model=list[dict])
def listar_turmas_duplicadas(
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Grupos de turmas que são a MESMA sala escrita de formas diferentes
    (ex.: '1 ANO A TARDE ANUAL (300302821)' e '1ºA'). Sugere como canônica o
    nome curto/padronizado e lista as duplicadas com a contagem de alunos."""
    return turmas_dedup.detectar(db, escola_id)


@router.post("/turmas/duplicadas/corrigir", response_model=dict)
def corrigir_turmas_duplicadas(
    grupos: list[ConsolidarTurmasIn],
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Consolida os grupos escolhidos: move as matrículas das duplicadas para a
    canônica, herda o titular quando ela não tem e remove as turmas duplicadas.
    Recalcula ao final. Não funde alunos — reporta possíveis duplicados."""
    resumos: list[dict] = []
    try:
        for g in grupos:
            resumos.append(turmas_dedup.consolidar(db, escola_id, g.canonica_id, g.duplicada_ids))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    total_rem = sum(r["turmas_removidas"] for r in resumos)
    total_mov = sum(r["alunos_movidos"] for r in resumos)
    dup_total = sum(r["possiveis_alunos_duplicados"] for r in resumos)
    registrar(db, "turmas.consolidadas", escola_id=escola_id, usuario_id=usuario.id,
              entidade="turma", detalhes={"grupos": len(grupos),
                                          "removidas": total_rem, "alunos_movidos": total_mov})
    db.commit()
    _recalcular_escola(db, escola_id)

    msg = f"{total_rem} turma(s) duplicada(s) consolidada(s); {total_mov} aluno(s) migrado(s)."
    if dup_total:
        msg += (f" Atenção: {dup_total} nome(s) aparecem repetidos na(s) turma(s) — "
                "confira em Alunos e use “Fundir alunos” se for a mesma pessoa.")
    return {"mensagem": msg, "grupos": resumos, "turmas_removidas": total_rem,
            "alunos_movidos": total_mov, "possiveis_alunos_duplicados": dup_total}


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


@router.patch("/professores/{professor_id}", response_model=ProfessorOut)
def atualizar_professor(
    professor_id: int,
    dados: ProfessorUpdate,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Edita o NOME e/ou o E-MAIL do professor — ex.: completar um nome que veio
    só como apelido na importação, ou corrigir o e-mail. O e-mail é o LOGIN do
    professor e o que liga a conta às turmas dele: por isso, ao trocá-lo, a conta
    de acesso vinculada é atualizada junto (senão o professor perderia as turmas).
    Não mexe nos vínculos de turma (esses continuam pelo botão de vincular turmas)."""
    professor = db.get(Professor, professor_id)
    if professor is None or professor.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Professor não encontrado.")

    campos = dados.model_dump(exclude_unset=True)
    if campos.get("nome"):
        professor.nome = campos["nome"].strip()
    if campos.get("email"):
        novo_email = str(campos["email"]).strip().lower()
        # Conta de login atualmente vinculada a este professor (casa pelo e-mail
        # ATUAL do professor). Se existir, o e-mail dela precisa acompanhar a
        # troca — é o mesmo e-mail que o RBAC usa para achar as turmas do prof.
        conta = None
        if professor.email:
            conta = db.execute(
                select(Usuario).where(func.lower(Usuario.email) == professor.email.strip().lower())
            ).scalar_one_or_none()
        if conta is not None:
            # Vou trocar o e-mail (login) da conta → não pode colidir com OUTRA.
            colisao = db.execute(
                select(Usuario).where(func.lower(Usuario.email) == novo_email, Usuario.id != conta.id)
            ).scalar_one_or_none()
            if colisao is not None:
                raise HTTPException(status.HTTP_409_CONFLICT,
                                    "Este e-mail já está em uso por outra conta de acesso.")
            conta.email = novo_email
        professor.email = novo_email

    registrar(db, "professor.atualizado", escola_id=escola_id, usuario_id=usuario.id,
              entidade="professor", entidade_id=professor.id,
              detalhes={"nome": professor.nome, "email": professor.email})
    db.commit()
    db.refresh(professor)
    return professor


@router.delete("/professores/{professor_id}", response_model=dict)
def excluir_professor(
    professor_id: int,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Remove o professor da equipe da escola. As TURMAS dele NÃO são apagadas —
    apenas ficam sem titular (professor_id nulo), para você revincular depois. A
    CONTA DE ACESSO (login) não é tocada aqui: para tirar o acesso, exclua também
    o usuário na tela de Usuários."""
    professor = db.get(Professor, professor_id)
    if professor is None or professor.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Professor não encontrado.")
    # Solta as turmas antes de excluir (evita quebrar o vínculo e não apaga as
    # salas — elas só ficam sem titular).
    turmas = db.execute(
        select(Turma).where(Turma.professor_id == professor_id)
    ).scalars().all()
    for turma in turmas:
        turma.professor_id = None
    nome = professor.nome
    db.delete(professor)
    registrar(db, "professor.excluido", escola_id=escola_id, usuario_id=usuario.id,
              entidade="professor", entidade_id=professor_id,
              detalhes={"nome": nome, "turmas_desvinculadas": len(turmas)})
    db.commit()
    return {"mensagem": f"Professor “{nome}” removido."
                        + (f" {len(turmas)} turma(s) ficaram sem titular."
                           if turmas else "")}


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
