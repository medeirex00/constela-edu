"""Permissões por papel (a "virada de chave" do acesso).

Regras aplicadas NO SERVIDOR (o frontend só esconde o que aqui é bloqueado):

  * admin / coordenador / conta global — acesso total à escola (o que separa
    admin de coordenador são as ações administrativas já protegidas por
    `exigir_papeis("admin")`/admin global: gestão de usuários, escolas, backup).
  * professor — enxerga APENAS as turmas designadas a ele no ano letivo ativo
    (`turmas_permitidas`): posição no ranking, pontos, o PASSO A PASSO do
    cálculo da nota e a EVOLUÇÃO por aluno (`/evolucao`, `/evolucao-leitura`)
    dos seus alunos — ambos liberados pelo dono (evolução em 03/08/2026; aluno
    de fora = 404 via `exigir_aluno_permitido`). Continua SEM histórico de
    leituras, linha do tempo, espelho, ficha cadastral (dados pessoais), visão
    da escola, métricas ou configurações (`negar_dado_individual` /
    `negar_restrito`).

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


def e_secretaria(usuario: Usuario) -> bool:
    """SEDUC/Secretaria: conta vinculada a uma REDE e NÃO global. AGREGA a rede,
    mas NUNCA enxerga dado individual de criança (LGPD) — só números por escola/
    rede. É a mesma definição de ``deps._e_secretaria`` (aqui sem importar deps,
    para evitar ciclo)."""
    return usuario.rede_id is not None and not usuario.is_global


def turmas_permitidas(db: Session, escola_id: int, usuario: Usuario) -> list[int] | None:
    """None = sem restrição. Lista (pode ser vazia) = restrito a essas turmas.

    Para o professor, são as turmas dele **no ano letivo ativo da escola** — a
    designação ATUAL. Turma de ano anterior não entra.

    Por que o ano importa (auditoria de segurança da Fase 3A). Nomes de turma
    se repetem entre anos ("3º Ano A" existe todo ano); só são únicos dentro do
    ano (`UNIQUE(escola_id, ano_letivo, nome)`). A exportação de relatórios
    recortava as linhas do professor comparando o NOME da turma; com turmas de
    qualquer ano aqui, a professora que deu o "3º Ano A" em 2025 e foi para
    outra turma em 2026 exportava também as crianças do "3º Ano A" de 2026, que
    é de outra pessoa — vazamento reproduzido em teste. Mesmo restrito ao ano
    ativo, o nome não equivale ao id: uma matrícula do ano ativo pode apontar
    para a turma homônima de outro ano. Por isso a exportação recorta pelo ID
    da turma da matrícula (`relatorios._recorte`), como a evolução
    (`alunos_permitidos`).

    Nenhum consumidor perde dado legítimo: todos os que mostram aluno já cruzam
    com as matrículas do ano ativo (`alunos_permitidos`). Saem apenas as rotas
    de turma de ANO ANTERIOR por id, que a interface do professor não usa.

    Escola sem ano letivo ativo definido mantém o comportamento anterior (sem
    filtro de ano): não há ano contra o qual recortar."""
    # Secretaria: nenhuma turma de trabalho → as telas INDIVIDUAIS (lista de
    # alunos, rankings nominais, insights por aluno, ficha) ficam vazias/404. Os
    # agregados por escola/rede NÃO passam por aqui (usam acesso_total/exigir_rede),
    # então a visão consolidada continua intacta. Vem ANTES de acesso_total porque
    # a conta da Secretaria costuma ter cargo 'coordenador'.
    if e_secretaria(usuario):
        return []
    if acesso_total(usuario):
        return None
    email = (usuario.email or "").strip().lower()
    if not email:
        return []
    consulta = (
        select(Turma.id)
        .join(Professor, Turma.professor_id == Professor.id)
        .where(Turma.escola_id == escola_id,
               func.lower(Professor.email) == email)
    )
    escola = db.get(Escola, escola_id)
    if escola is not None and escola.ano_letivo_ativo is not None:
        consulta = consulta.where(Turma.ano_letivo == escola.ano_letivo_ativo)
    return list(db.execute(consulta).scalars().all())


def alunos_permitidos(db: Session, escola_id: int, ano: int,
                      turma_ids: list[int], *, incluir_inativos: bool = False) -> set[int]:
    """Ids dos alunos matriculados (ano ativo) nas turmas permitidas. Só os ativos,
    salvo ``incluir_inativos`` (revogar o cartão do Quest de quem está inativo)."""
    if not turma_ids:
        return set()
    consulta = (
        select(Matricula.aluno_id)
        .join(Aluno, Aluno.id == Matricula.aluno_id)
        .where(Matricula.escola_id == escola_id,
               Matricula.ano_letivo == ano,
               Matricula.turma_id.in_(turma_ids))
    )
    if not incluir_inativos:
        consulta = consulta.where(Aluno.status == "ativo")
    return set(db.execute(consulta).scalars().all())


def negar_restrito(db: Session, escola_id: int, usuario: Usuario) -> None:
    """403 para quem não tem acesso total (telas exclusivas de gestão)."""
    if not acesso_total(usuario):
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Seu perfil não tem acesso a esta área.")


def negar_dado_individual(db: Session, escola_id: int, usuario: Usuario) -> None:
    """403 para professor restrito E para a Secretaria — telas de DADO INDIVIDUAL
    de criança (ficha/histórico/linha do tempo/espelho por aluno, comparador,
    certificados, mural nominal). A EVOLUÇÃO por aluno não passa por aqui: usa
    ``exigir_aluno_permitido`` (o professor vê a dos alunos dele; a Secretaria
    recebe 404). A Secretaria AGREGA a rede, mas não vê PII de criança (LGPD);
    só o gestor da PRÓPRIA escola (admin/coordenador sem rede) e o admin global.
    Para agregados sem PII (resumo por turma, config), use ``negar_restrito``."""
    if not acesso_total(usuario) or e_secretaria(usuario):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Seu perfil não tem acesso a dados individuais de alunos.")


def exigir_aluno_permitido(db: Session, escola_id: int, ano: int,
                           usuario: Usuario, aluno_id: int, *,
                           incluir_inativos: bool = False) -> None:
    """404 quando o professor tenta abrir aluno fora das turmas dele (404 e
    não 403 para não revelar a existência do aluno). ``incluir_inativos``: a
    matrícula na turma dele basta, qualquer que seja o status do aluno."""
    ids = turmas_permitidas(db, escola_id, usuario)
    if ids is None:
        return
    if aluno_id not in alunos_permitidos(db, escola_id, ano, ids,
                                         incluir_inativos=incluir_inativos):
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
