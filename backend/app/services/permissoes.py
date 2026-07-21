"""Permissões por papel (a "virada de chave" do acesso).

Regras aplicadas NO SERVIDOR (o frontend só esconde o que aqui é bloqueado):

  * admin / coordenador / conta global — acesso total à escola (o que separa
    admin de coordenador são as ações administrativas já protegidas por
    `exigir_papeis("admin")`/admin global: gestão de usuários, escolas, backup).
  * professor — enxerga APENAS as turmas designadas a ele e dados
    SUPERFICIAIS dos seus alunos (posição no ranking geral e pontos). Nada de
    histórico de leituras, evolução detalhada, visão da escola, cadastro de
    professores, métricas ou configurações.

O vínculo professor ↔ turmas vem do cadastro de Professores: o registro cujo
e-mail é o MESMO do usuário logado; as turmas designadas são as que apontam
para esse professor. Sem vínculo → lista vazia (não vê aluno nenhum).
"""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Aluno, Escola, Matricula, Professor, Turma, Usuario

CARGOS_TOTAIS = ("admin", "coordenador")


def acesso_total(usuario: Usuario) -> bool:
    return bool(usuario.is_global) or usuario.cargo in CARGOS_TOTAIS


def escopo_escolas(db: Session, usuario: Usuario) -> set[int] | None:
    """Fonte ÚNICA do ALCANCE de um usuário: quais escolas ele enxerga.

    Retorna:
      * ``None``  → TODAS as escolas (admin global da plataforma).
      * ``{ids}`` → conjunto explícito (rede/secretaria = todas as escolas da
                    rede; usuário comum = só a própria escola).
      * ``set()`` → nenhuma (fail-closed: sem escola e sem rede).

    Isto GENERALIZA o isolamento por escola sem mudar o caso comum: um usuário
    de escola única devolve ``{escola_id}`` — comportamento idêntico ao antigo.
    O eixo de alcance (quantas escolas) é ortogonal ao ``cargo`` (quais ações).
    """
    if usuario.is_global:
        return None
    if usuario.rede_id is not None:
        return set(db.execute(
            select(Escola.id).where(Escola.rede_id == usuario.rede_id)
        ).scalars().all())
    if usuario.escola_id is not None:
        return {usuario.escola_id}
    return set()


def turmas_permitidas(db: Session, escola_id: int, usuario: Usuario) -> list[int] | None:
    """None = sem restrição. Lista (pode ser vazia) = restrito a essas turmas.

    Vínculo FORTE por FK (`usuario.professor_id`) — preferido, imune a divergência
    de e-mail. O casamento por e-mail continua como FALLBACK para contas ainda
    não migradas (professores criados antes da FK)."""
    if acesso_total(usuario):
        return None
    if usuario.professor_id is not None:
        return list(db.execute(
            select(Turma.id).where(Turma.escola_id == escola_id,
                                   Turma.professor_id == usuario.professor_id)
        ).scalars().all())
    email = (usuario.email or "").strip().lower()
    if not email:
        return []
    return list(db.execute(
        select(Turma.id)
        .join(Professor, Turma.professor_id == Professor.id)
        .where(Turma.escola_id == escola_id,
               func.lower(Professor.email) == email)
    ).scalars().all())


def alunos_permitidos(db: Session, escola_id: int, ano: int,
                      turma_ids: list[int]) -> set[int]:
    """Ids dos alunos matriculados (ano ativo) nas turmas permitidas."""
    if not turma_ids:
        return set()
    return set(db.execute(
        select(Matricula.aluno_id)
        .join(Aluno, Aluno.id == Matricula.aluno_id)
        .where(Matricula.escola_id == escola_id,
               Matricula.ano_letivo == ano,
               Matricula.turma_id.in_(turma_ids),
               Aluno.status == "ativo")
    ).scalars().all())


def negar_restrito(db: Session, escola_id: int, usuario: Usuario) -> None:
    """403 para quem não tem acesso total (telas exclusivas de gestão)."""
    if not acesso_total(usuario):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Seu perfil não tem acesso a esta área.")


def exigir_aluno_permitido(db: Session, escola_id: int, ano: int,
                           usuario: Usuario, aluno_id: int) -> None:
    """404 quando o professor tenta abrir aluno fora das turmas dele (404 e
    não 403 para não revelar a existência do aluno)."""
    ids = turmas_permitidas(db, escola_id, usuario)
    if ids is None:
        return
    if aluno_id not in alunos_permitidos(db, escola_id, ano, ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aluno não encontrado.")


def exigir_turma_permitida(db: Session, escola_id: int, usuario: Usuario,
                           turma_id: int) -> None:
    """404 quando o professor tenta abrir turma fora das dele (404 e não 403
    para não revelar a existência da turma — igual a exigir_aluno_permitido)."""
    ids = turmas_permitidas(db, escola_id, usuario)
    if ids is None:
        return
    if turma_id not in ids:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Turma não encontrada.")


def filtrar_por_aluno(itens: list[dict], permitidos: set[int]) -> list[dict]:
    """Mantém apenas itens cujo aluno_id é permitido (listas de rankings,
    insights, gamificação...)."""
    return [item for item in itens if item.get("aluno_id") in permitidos]
