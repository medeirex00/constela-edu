"""Notificações acionáveis por perfil (Fase 2a).

Camada FINA sobre o modelo Notificacao:
  * ``emitir_da_auditoria`` — chamada dentro de ``audit.registrar`` (choke point
    único): para os eventos que já existem, materializa 1 notificação de escopo
    ESCOLA com a ROTA da tela de ação.
  * ``feed`` / ``contar_nao_lidas`` / ``marcar_lidas`` — leitura POR PERFIL, no
    servidor (o backend é o portão). A Secretaria só recebe escopo 'rede'
    (agregado, sem PII); o professor só avisos das turmas dele; coordenador/admin
    a própria escola; admin global tudo. Regras de PII iguais às do resto do app
    (turmas_permitidas / e_secretaria).
"""
from __future__ import annotations

from typing import Callable

from sqlalchemy import and_, false, func, select
from sqlalchemy.orm import Session

from app.models import Escola, Notificacao, Usuario
from app.services import permissoes

# acao de auditoria -> (título, severidade, rota(entidade_id) -> str).
# Só os eventos com valor de notificação (import/config/usuários/plataformas/
# aluno criado). Relatório/certificado exportados são ações do próprio usuário —
# não viram aviso. TODOS são escopo ESCOLA (operação interna da escola).
NOTIFICAVEIS: dict[str, tuple[str, str, Callable[[int | None], str]]] = {
    "importacao.concluida": ("Nova importação de dados concluída", "info", lambda _: "/importacoes"),
    "pesos.alterados": ("Pesos do cálculo foram alterados", "info", lambda _: "/metricas"),
    "referencias.alteradas": ("Referências de normalização alteradas", "info", lambda _: "/metricas"),
    "dificuldade.alterada": ("Pontuação de dificuldade alterada", "info", lambda _: "/metricas"),
    "notas.recalculadas": ("Notas recalculadas", "info", lambda _: "/ranking"),
    "backup.gerado": ("Backup gerado", "info", lambda _: "/configuracoes"),
    "backup.restaurado": ("Backup restaurado", "aviso", lambda _: "/configuracoes"),
    "usuario.criado": ("Novo usuário criado", "info", lambda _: "/usuarios"),
    "matific.editado": ("Dados da Matific editados manualmente", "info", lambda _: "/matific"),
    "elefante.editado": ("Dados do Elefante Letrado editados manualmente", "info", lambda _: "/elefante"),
    "aluno.criado": ("Novo aluno cadastrado", "info",
                     lambda eid: f"/alunos/{eid}" if eid else "/alunos"),
}


def emitir_da_auditoria(db: Session, acao: str, escola_id: int | None,
                        autor_id: int | None = None, entidade: str | None = None,
                        entidade_id: int | None = None) -> None:
    """Materializa uma notificação de escopo ESCOLA para os eventos conhecidos.
    No-op silencioso para ações não notificáveis ou sem escola. Adiciona à sessão
    (o commit fica com a operação principal, como o próprio registrar())."""
    if escola_id is None:
        return
    spec = NOTIFICAVEIS.get(acao)
    if spec is None:
        return
    titulo, severidade, rota_de = spec
    aluno_id = entidade_id if entidade == "aluno" else None
    db.add(Notificacao(
        escopo="escola", escola_id=escola_id, tipo=acao, severidade=severidade,
        titulo=titulo, rota=rota_de(entidade_id), entidade=entidade,
        entidade_id=entidade_id, aluno_id=aluno_id, autor_id=autor_id,
    ))


def _condicao_feed(db: Session, usuario: Usuario):
    """Condição SQL do feed do usuário — a 'virada de chave' por perfil.

    Ordem importa: a Secretaria (rede_id, mesmo com cargo coordenador) é tratada
    ANTES de acesso_total, e recebe SÓ escopo 'rede' — nunca 'escola', nunca
    aluno_id. Assim, por construção, a Secretaria não recebe PII de criança."""
    if usuario.is_global:
        return Notificacao.escopo.in_(("global", "rede", "escola"))
    if permissoes.e_secretaria(usuario):
        return and_(Notificacao.escopo == "rede", Notificacao.rede_id == usuario.rede_id)
    if permissoes.acesso_total(usuario):  # coordenador/admin da própria escola
        return and_(Notificacao.escopo == "escola", Notificacao.escola_id == usuario.escola_id)
    # Professor: só avisos que tocam SEUS alunos (turmas designadas a ele).
    escola_id = usuario.escola_id
    if escola_id is None:
        return false()
    escola = db.get(Escola, escola_id)
    ano = escola.ano_letivo_ativo if escola else 0
    turmas = permissoes.turmas_permitidas(db, escola_id, usuario) or []
    alunos = permissoes.alunos_permitidos(db, escola_id, ano, turmas)
    if not alunos:
        return false()
    return and_(Notificacao.escopo == "escola",
                Notificacao.escola_id == escola_id,
                Notificacao.aluno_id.in_(alunos))


def feed(db: Session, usuario: Usuario, limite: int = 30) -> list[dict]:
    cond = _condicao_feed(db, usuario)
    lidas_ate = usuario.notificacoes_lidas_ate_id or 0
    linhas = db.execute(
        select(Notificacao, Usuario.nome)
        .outerjoin(Usuario, Notificacao.autor_id == Usuario.id)
        .where(cond)
        .order_by(Notificacao.id.desc())
        .limit(limite)
    ).all()
    return [
        {
            "id": n.id,
            "tipo": n.tipo,
            "severidade": n.severidade,
            "titulo": n.titulo,
            "rota": n.rota,
            "autor": autor,
            "data": n.created_at,
            "lida": n.id <= lidas_ate,
        }
        for n, autor in linhas
    ]


def contar_nao_lidas(db: Session, usuario: Usuario) -> int:
    cond = _condicao_feed(db, usuario)
    lidas_ate = usuario.notificacoes_lidas_ate_id or 0
    return int(db.execute(
        select(func.count()).select_from(Notificacao)
        .where(cond, Notificacao.id > lidas_ate)
    ).scalar_one())


def marcar_lidas(db: Session, usuario: Usuario) -> int:
    """Marca tudo como lido: avança o marcador do usuário até o maior id do feed
    dele. Retorna o novo marcador."""
    cond = _condicao_feed(db, usuario)
    maior = db.execute(select(func.max(Notificacao.id)).where(cond)).scalar()
    if maior and maior > (usuario.notificacoes_lidas_ate_id or 0):
        usuario.notificacoes_lidas_ate_id = maior
        db.commit()
    return usuario.notificacoes_lidas_ate_id or 0
