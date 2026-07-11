"""Módulos Matific e Elefante Letrado + Catálogo de Livros (PRD §55–§57).

A edição manual NUNCA sobrescreve histórico: cada correção gera uma
importação do tipo "manual" e um novo snapshot, preservando a linha do
tempo (§68) e deixando o antes/depois no log de auditoria.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import escola_autorizada, exigir_papeis, get_usuario_atual
from app.models import (
    Aluno,
    Escola,
    Importacao,
    Leitura,
    Livro,
    Matricula,
    NivelDificuldade,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
    Usuario,
)
from app.schemas import (
    ElefanteAlunoOut,
    ElefanteEdicao,
    LivroCreate,
    LivroOut,
    LivroUpdate,
    MatificAlunoOut,
    MatificEdicao,
    NiveisLeituraEdicao,
)
from app.services import permissoes, scoring
from app.services.audit import registrar

router = APIRouter(prefix="/escolas/{escola_id}", tags=["Plataformas"])


def _linhas_modulo(db: Session, escola_id: int, modelo,
                   turma_ids: list[int] | None = None):
    """Alunos ativos do ano letivo com o snapshot mais recente da plataforma.

    "Mais recente" pela data_referencia (id desempata): um relatório de
    período antigo importado depois (backfill mensal do Matific) não pode
    virar o estado atual do módulo.

    `turma_ids` restringe às turmas informadas (professor vê só as dele);
    None = escola inteira (admin/coordenador)."""
    escola = db.get(Escola, escola_id)
    if escola is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Escola não encontrada.")
    ids = scoring.ids_snapshots_atuais(modelo, escola_id)
    consulta = (
        select(Aluno, Turma, modelo)
        .join(Matricula, (Matricula.aluno_id == Aluno.id)
              & (Matricula.ano_letivo == escola.ano_letivo_ativo))
        .join(Turma, Matricula.turma_id == Turma.id)
        .outerjoin(modelo, (modelo.aluno_id == Aluno.id) & modelo.id.in_(ids))
        .where(Aluno.escola_id == escola_id, Aluno.status == "ativo")
        .order_by(Aluno.nome)
    )
    if turma_ids is not None:
        consulta = consulta.where(Matricula.turma_id.in_(turma_ids))
    return db.execute(consulta).all()


def _aluno_da_escola(db: Session, escola_id: int, aluno_id: int) -> Aluno:
    aluno = db.get(Aluno, aluno_id)
    if aluno is None or aluno.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aluno não encontrado.")
    return aluno


def _importacao_manual(db, escola_id, usuario_id, plataforma) -> Importacao:
    importacao = Importacao(escola_id=escola_id, usuario_id=usuario_id,
                            plataforma=plataforma, tipo="manual", qtd_alunos=1)
    db.add(importacao)
    db.flush()
    return importacao


# --- Matific (PRD §55) --------------------------------------------------------

@router.get("/matific", response_model=list[MatificAlunoOut])
def modulo_matific(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    # Professor restrito vê só as turmas dele (None = escola inteira p/ admin/coord).
    permitidas = permissoes.turmas_permitidas(db, escola_id, usuario)
    return [
        MatificAlunoOut(
            aluno_id=aluno.id, nome=aluno.nome, turma=turma.nome,
            ano_escolar=turma.ano_escolar,
            atividades=snap.atividades if snap else 0,
            estrelas=snap.estrelas if snap else 0,
            pontuacao_media=snap.pontuacao_media if snap else 0.0,
            data_referencia=snap.data_referencia if snap else None,
        )
        for aluno, turma, snap in _linhas_modulo(
            db, escola_id, SnapshotMatific, turma_ids=permitidas)
    ]


@router.put("/matific/{aluno_id}", response_model=MatificAlunoOut)
def editar_matific(
    aluno_id: int,
    dados: MatificEdicao,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    aluno = _aluno_da_escola(db, escola_id, aluno_id)
    anterior = db.execute(
        select(SnapshotMatific)
        .where(SnapshotMatific.aluno_id == aluno_id)
        .order_by(SnapshotMatific.data_referencia.desc(),
                  SnapshotMatific.id.desc()).limit(1)
    ).scalar_one_or_none()

    importacao = _importacao_manual(db, escola_id, usuario.id, "matific")
    snap = SnapshotMatific(
        escola_id=escola_id, aluno_id=aluno_id, importacao_id=importacao.id,
        atividades=dados.atividades, estrelas=dados.estrelas,
        pontuacao_media=dados.pontuacao_media,
    )
    db.add(snap)
    registrar(db, "matific.editado", escola_id=escola_id, usuario_id=usuario.id,
              entidade="aluno", entidade_id=aluno_id,
              detalhes={
                  "motivo": dados.motivo,
                  "de": {"atividades": anterior.atividades if anterior else 0,
                         "estrelas": anterior.estrelas if anterior else 0,
                         "pontuacao_media": anterior.pontuacao_media if anterior else 0.0},
                  "para": dados.model_dump(exclude={"motivo"}),
              })
    db.commit()
    scoring.recalcular_escola(db, escola_id)
    db.refresh(snap)
    return MatificAlunoOut(
        aluno_id=aluno.id, nome=aluno.nome, turma=None, ano_escolar=None,
        atividades=snap.atividades, estrelas=snap.estrelas,
        pontuacao_media=snap.pontuacao_media, data_referencia=snap.data_referencia,
    )


# --- Elefante Letrado (PRD §56) -------------------------------------------------

@router.get("/elefante", response_model=list[ElefanteAlunoOut])
def modulo_elefante(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    # Professor restrito vê só as turmas dele (None = escola inteira p/ admin/coord).
    permitidas = permissoes.turmas_permitidas(db, escola_id, usuario)
    return [
        ElefanteAlunoOut(
            aluno_id=aluno.id, nome=aluno.nome, turma=turma.nome,
            ano_escolar=turma.ano_escolar,
            livros_unicos=snap.livros_unicos if snap else 0,
            tempo_leitura_min=snap.tempo_leitura_min if snap else 0,
            questoes_tentativas=snap.questoes_tentativas if snap else 0,
            questoes_acertos=snap.questoes_acertos if snap else 0,
            livros_por_nivel=snap.livros_por_nivel if snap else {},
            data_referencia=snap.data_referencia if snap else None,
        )
        for aluno, turma, snap in _linhas_modulo(
            db, escola_id, SnapshotElefante, turma_ids=permitidas)
    ]


@router.put("/elefante/{aluno_id}", response_model=ElefanteAlunoOut)
def editar_elefante(
    aluno_id: int,
    dados: ElefanteEdicao,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    if dados.questoes_acertos > dados.questoes_tentativas:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Acertos não podem exceder as tentativas.")
    aluno = _aluno_da_escola(db, escola_id, aluno_id)
    anterior = db.execute(
        select(SnapshotElefante)
        .where(SnapshotElefante.aluno_id == aluno_id)
        .order_by(SnapshotElefante.data_referencia.desc(),
                  SnapshotElefante.id.desc()).limit(1)
    ).scalar_one_or_none()

    por_nivel = {c.upper(): int(q) for c, q in dados.livros_por_nivel.items()}
    livros = dados.livros_unicos if dados.livros_unicos is not None else sum(por_nivel.values())

    importacao = _importacao_manual(db, escola_id, usuario.id, "elefante")
    snap = SnapshotElefante(
        escola_id=escola_id, aluno_id=aluno_id, importacao_id=importacao.id,
        livros_unicos=livros, tempo_leitura_min=dados.tempo_leitura_min,
        questoes_tentativas=dados.questoes_tentativas,
        questoes_acertos=dados.questoes_acertos,
        livros_por_nivel=por_nivel,
    )
    db.add(snap)
    registrar(db, "elefante.editado", escola_id=escola_id, usuario_id=usuario.id,
              entidade="aluno", entidade_id=aluno_id,
              detalhes={
                  "motivo": dados.motivo,
                  "de": {"livros_unicos": anterior.livros_unicos if anterior else 0,
                         "tempo_leitura_min": anterior.tempo_leitura_min if anterior else 0,
                         "questoes_tentativas": anterior.questoes_tentativas if anterior else 0,
                         "questoes_acertos": anterior.questoes_acertos if anterior else 0,
                         "livros_por_nivel": anterior.livros_por_nivel if anterior else {}},
                  "para": dados.model_dump(exclude={"motivo"}),
              })
    db.commit()
    scoring.recalcular_escola(db, escola_id)
    db.refresh(snap)
    return ElefanteAlunoOut(
        aluno_id=aluno.id, nome=aluno.nome, turma=None, ano_escolar=None,
        livros_unicos=snap.livros_unicos, tempo_leitura_min=snap.tempo_leitura_min,
        questoes_tentativas=snap.questoes_tentativas,
        questoes_acertos=snap.questoes_acertos,
        livros_por_nivel=snap.livros_por_nivel,
        data_referencia=snap.data_referencia,
    )


@router.put("/elefante/{aluno_id}/niveis", response_model=ElefanteAlunoOut)
def informar_niveis_leitura(
    aluno_id: int,
    dados: NiveisLeituraEdicao,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Informa os livros concluídos por FAIXA de dificuldade (§38). O total e
    os pontos de dificuldade são recalculados; tempo e questões do último
    snapshot são preservados. Só aceita códigos de faixa configurados."""
    aluno = _aluno_da_escola(db, escola_id, aluno_id)
    validos = {
        n.codigo for n in db.execute(
            select(NivelDificuldade).where(NivelDificuldade.escola_id == escola_id)
        ).scalars() if n.codigo
    }
    por_nivel: dict[str, int] = {}
    for codigo, quantidade in dados.faixas.items():
        if codigo not in validos:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Faixa desconhecida: “{codigo}”. Configure as faixas em Métricas.")
        if int(quantidade) < 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "A quantidade de livros não pode ser negativa.")
        por_nivel[codigo] = int(quantidade)

    anterior = db.execute(
        select(SnapshotElefante)
        .where(SnapshotElefante.aluno_id == aluno_id)
        .order_by(SnapshotElefante.data_referencia.desc(),
                  SnapshotElefante.id.desc()).limit(1)
    ).scalar_one_or_none()

    importacao = _importacao_manual(db, escola_id, usuario.id, "elefante")
    snap = SnapshotElefante(
        escola_id=escola_id, aluno_id=aluno_id, importacao_id=importacao.id,
        livros_unicos=sum(por_nivel.values()),
        tempo_leitura_min=anterior.tempo_leitura_min if anterior else 0,
        questoes_tentativas=anterior.questoes_tentativas if anterior else 0,
        questoes_acertos=anterior.questoes_acertos if anterior else 0,
        livros_por_nivel=por_nivel,
    )
    db.add(snap)
    registrar(db, "elefante.niveis_informados", escola_id=escola_id,
              usuario_id=usuario.id, entidade="aluno", entidade_id=aluno_id,
              detalhes={"motivo": dados.motivo, "faixas": por_nivel})
    db.commit()
    scoring.recalcular_escola(db, escola_id)
    db.refresh(snap)
    return ElefanteAlunoOut(
        aluno_id=aluno.id, nome=aluno.nome, turma=None, ano_escolar=None,
        livros_unicos=snap.livros_unicos, tempo_leitura_min=snap.tempo_leitura_min,
        questoes_tentativas=snap.questoes_tentativas,
        questoes_acertos=snap.questoes_acertos,
        livros_por_nivel=snap.livros_por_nivel,
        data_referencia=snap.data_referencia,
    )


# --- Catálogo de Livros (PRD §57) ----------------------------------------------

def _pontos_por_codigo(db: Session, escola_id: int) -> dict[str, float]:
    pontos: dict[str, float] = {}
    for nivel in db.execute(
        select(NivelDificuldade).where(NivelDificuldade.escola_id == escola_id)
    ).scalars():
        for codigo in nivel.codigos:
            pontos[codigo] = float(nivel.pontos_padrao)
    return pontos


@router.get("/livros", response_model=dict)
def listar_livros(
    escola_id: int = Depends(escola_autorizada),
    busca: str | None = Query(default=None),
    nivel: str | None = Query(default=None),
    categoria: str | None = Query(default=None),
    pagina: int = Query(default=1, ge=1),
    por_pagina: int = Query(default=25, ge=1, le=100),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    consulta = select(Livro).where(Livro.escola_id == escola_id)
    if busca:
        consulta = consulta.where(
            Livro.titulo.ilike(f"%{busca}%") | Livro.autor.ilike(f"%{busca}%")
        )
    if nivel:
        consulta = consulta.where(Livro.nivel_codigo == nivel.upper())
    if categoria:
        consulta = consulta.where(Livro.categoria == categoria)

    total = db.execute(
        select(func.count()).select_from(consulta.subquery())
    ).scalar_one()
    livros = db.execute(
        consulta.order_by(Livro.titulo).offset((pagina - 1) * por_pagina).limit(por_pagina)
    ).scalars().all()

    contagem = dict(db.execute(
        select(Leitura.livro_id, func.count(Leitura.id))
        .where(Leitura.escola_id == escola_id)
        .group_by(Leitura.livro_id)
    ).all())
    pontos = _pontos_por_codigo(db, escola_id)

    itens = []
    for livro in livros:
        item = LivroOut.model_validate(livro)
        item.pontos = pontos.get(livro.nivel_codigo, 0.0)
        item.leituras = contagem.get(livro.id, 0)
        itens.append(item)
    return {"total": total, "pagina": pagina, "por_pagina": por_pagina, "itens": itens}


@router.post("/livros", response_model=LivroOut, status_code=status.HTTP_201_CREATED)
def criar_livro(
    dados: LivroCreate,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    _titulo = dados.titulo.strip()
    _titulo_escapado = _titulo.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    existente = db.execute(
        select(Livro).where(
            Livro.escola_id == escola_id,
            Livro.titulo.ilike(_titulo_escapado, escape="\\"),
        ).limit(1)
    ).scalars().first()
    if existente:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Já existe um livro com este título no catálogo.")
    livro = Livro(escola_id=escola_id, titulo=dados.titulo.strip(), autor=dados.autor,
                  nivel_codigo=dados.nivel_codigo.upper(), categoria=dados.categoria,
                  paginas=dados.paginas)
    db.add(livro)
    db.flush()
    registrar(db, "livro.criado", escola_id=escola_id, usuario_id=usuario.id,
              entidade="livro", entidade_id=livro.id, detalhes={"titulo": livro.titulo})
    db.commit()
    db.refresh(livro)
    saida = LivroOut.model_validate(livro)
    saida.pontos = _pontos_por_codigo(db, escola_id).get(livro.nivel_codigo, 0.0)
    return saida


@router.patch("/livros/{livro_id}", response_model=LivroOut)
def atualizar_livro(
    livro_id: int,
    dados: LivroUpdate,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    livro = db.get(Livro, livro_id)
    if livro is None or livro.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Livro não encontrado.")
    alteracoes = dados.model_dump(exclude_unset=True)
    if "nivel_codigo" in alteracoes and alteracoes["nivel_codigo"]:
        alteracoes["nivel_codigo"] = alteracoes["nivel_codigo"].upper()
    for campo, valor in alteracoes.items():
        setattr(livro, campo, valor)
    registrar(db, "livro.atualizado", escola_id=escola_id, usuario_id=usuario.id,
              entidade="livro", entidade_id=livro.id, detalhes=alteracoes)
    db.commit()
    # Mudar o nível de um livro pode alterar pontos de dificuldade já contados
    scoring.recalcular_escola(db, escola_id)
    db.refresh(livro)
    saida = LivroOut.model_validate(livro)
    saida.pontos = _pontos_por_codigo(db, escola_id).get(livro.nivel_codigo, 0.0)
    return saida


@router.delete("/livros/{livro_id}")
def excluir_livro(
    livro_id: int,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    livro = db.get(Livro, livro_id)
    if livro is None or livro.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Livro não encontrado.")
    tem_leituras = db.execute(
        select(Leitura.id).where(Leitura.livro_id == livro_id).limit(1)
    ).scalar_one_or_none()
    if tem_leituras:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Este livro tem leituras registradas e não pode ser excluído — "
            "isso apagaria histórico de alunos.",
        )
    registrar(db, "livro.excluido", escola_id=escola_id, usuario_id=usuario.id,
              entidade="livro", entidade_id=livro.id, detalhes={"titulo": livro.titulo})
    db.delete(livro)
    db.commit()
    return {"mensagem": f"Livro “{livro.titulo}” excluído do catálogo."}
