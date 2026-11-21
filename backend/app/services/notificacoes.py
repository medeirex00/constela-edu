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
    # Importação/sync NÃO pode descartar linha em silêncio: a correspondência
    # insegura e a linha sem aluno vinculado viram notificação para a escola.
    # Rota de quando a pendência NÃO está na fila de revisão (a Lista Piloto manda
    # a correspondência insegura para Alunos › Fundir duplicatas; a "mudança de sala
    # sem prova", para a própria ficha: ``MOTIVOS_DO_LINK_DA_FICHA``); a que está na
    # fila leva às Revisões de identidade (``ROTA_REVISOES``, em
    # ``emitir_da_auditoria``).
    "aluno.revisao_necessaria": ("Importação: aluno com correspondência insegura — revisar",
                                 "aviso", lambda _: "/alunos"),
    "importacao.linha_ignorada": ("Importação: linha sem aluno vinculado — revisar",
                                  "aviso", lambda _: "/importacoes"),
}

# A tela onde o gestor decide as pendências da fila de identidade.
ROTA_REVISOES = "/revisoes-identidade"
# Os avisos que SÃO uma pendência: só eles vão para a fila quando a auditoria traz o
# ``revisao_id``. Os outros que trazem o id só citam a origem — o "Novo aluno
# cadastrado" da ficha criada pela fila leva à ficha nova, como qualquer outro.
AVISOS_DE_PENDENCIA = frozenset({"aluno.revisao_necessaria", "importacao.linha_ignorada"})
# Pendência da Lista Piloto (fora da fila) cujo caminho é a FICHA candidata
# (``entidade_id``), não a lista de Alunos. Na "mudança de sala sem prova" (a virada,
# G_VIRADA-8) a ficha não tem matrícula no ano ativo, e a lista /alunos, que só mostra
# quem tem, não a traz: o aviso da importação manda abrir a ficha (três pontinhos ›
# Editar dados › Turma), e o link do sino leva até ela. Os outros motivos seguem em
# /alunos, onde está "Fundir duplicatas".
MOTIVOS_DO_LINK_DA_FICHA = {"aluno.revisao_necessaria": frozenset({"mudanca_de_sala_sem_prova"})}

# GUARDAS DE PERFIL das telas para onde os avisos apontam. A fonte da regra é a
# web: ``apps/web/src/lib/rotasGuardadas.ts`` (o espelho das guardas do App.tsx).
# Aqui ficam só as rotas que os avisos DESTE módulo usam, com as MESMAS guardas;
# ``test_notificacoes_rotas_guardadas`` lê a tabela da web e falha se uma rota daqui
# divergir de lá ou se um aviso apontar para uma tela guardada que não está aqui.
# Rota fora do mapa não tem guarda. Quem não passa recebe o aviso SEM o link: na
# web, o link o mandaria de volta à página inicial (o professor recebe os avisos
# que tocam os alunos dele — inclusive "dados da Matific editados" e as pendências
# de identidade —, mas não abre as telas de operação da escola). O módulo
# contratado (RotaModulo) não entra: quem esconde o link de módulo fora do plano é
# a web (``podeAbrirRota``).
GUARDAS_DAS_ROTAS: dict[str, tuple[str, ...]] = {
    ROTA_REVISOES: ("RotaEscolaOp",),
    "/importacoes": ("RotaEscolaOp",),
    "/matific": ("RotaEscolaOp",),
    "/elefante": ("RotaEscolaOp",),
    "/metricas": ("RotaGestao",),
    "/configuracoes": ("RotaGestao", "RotaAdmin"),
    "/usuarios": ("RotaSemSecretaria",),
    "/alunos": ("RotaSemSecretaria",),
    "/alunos/:id": ("RotaSemSecretaria",),
}


def emitir_da_auditoria(db: Session, acao: str, escola_id: int | None,
                        autor_id: int | None = None, entidade: str | None = None,
                        entidade_id: int | None = None,
                        detalhes: dict | None = None) -> None:
    """Materializa uma notificação de escopo ESCOLA para os eventos conhecidos.
    No-op silencioso para ações não notificáveis ou sem escola. Adiciona à sessão
    (o commit fica com a operação principal, como o próprio registrar()).

    Pendência gravada na fila de revisão de identidade (a auditoria traz o
    ``revisao_id``) aponta para as Revisões de identidade — é lá que o gestor
    escolhe o aluno, cria a ficha ou descarta. Só a PENDÊNCIA
    (``AVISOS_DE_PENDENCIA``): a ficha criada pela fila também traz o id, de origem,
    e o aviso dela leva à ficha. Fora da fila, o motivo cujo caminho é a ficha
    (``MOTIVOS_DO_LINK_DA_FICHA``) leva à ficha candidata."""
    if escola_id is None:
        return
    spec = NOTIFICAVEIS.get(acao)
    if spec is None:
        return
    titulo, severidade, rota_de = spec
    rota = rota_de(entidade_id)
    if (acao in AVISOS_DE_PENDENCIA and isinstance(detalhes, dict)
            and "revisao_id" in detalhes):
        rota = ROTA_REVISOES
    elif (entidade == "aluno" and entidade_id and isinstance(detalhes, dict)
            and detalhes.get("motivo") in MOTIVOS_DO_LINK_DA_FICHA.get(acao, ())):
        rota = f"/alunos/{entidade_id}"
    aluno_id = entidade_id if entidade == "aluno" else None
    db.add(Notificacao(
        escopo="escola", escola_id=escola_id, tipo=acao, severidade=severidade,
        titulo=titulo, rota=rota, entidade=entidade,
        entidade_id=entidade_id, aluno_id=aluno_id, autor_id=autor_id,
    ))


def _admin(usuario: Usuario) -> bool:
    return bool(usuario.is_global) or usuario.cargo == "admin"


# O mesmo teste de cada guarda em App.tsx, sobre os campos de ``usePerfil()``:
# gestor = global ou admin/coordenador (``acesso_total``); secretaria = rede
# vinculada e não global (``e_secretaria``); admin = global ou cargo admin.
_PASSA: dict[str, Callable[[Usuario], bool]] = {
    "RotaGestao": lambda u: permissoes.acesso_total(u),
    "RotaEscolaOp": lambda u: permissoes.acesso_total(u) and not permissoes.e_secretaria(u),
    "RotaSemSecretaria": lambda u: not permissoes.e_secretaria(u),
    "RotaAdmin": lambda u: _admin(u) and not permissoes.e_secretaria(u),
}


def _segmentos(caminho: str) -> list[str]:
    return [s for s in caminho.split("?")[0].split("#")[0].split("/") if s]


def guardas_da_rota(rota: str) -> tuple[str, ...]:
    """As guardas da tela (mesmo casamento de ``podeAbrirRota``: ``:id`` casa
    qualquer segmento). Rota fora do mapa: nenhuma."""
    alvo = _segmentos(rota)
    for padrao, guardas in GUARDAS_DAS_ROTAS.items():
        p = _segmentos(padrao)
        if len(p) == len(alvo) and all(a.startswith(":") or a == b for a, b in zip(p, alvo)):
            return guardas
    return ()


def rota_para(usuario: Usuario, rota: str | None) -> str | None:
    """A rota do aviso para ESTE usuário: ``None`` quando alguma guarda da tela o
    barra (o aviso aparece, sem link)."""
    if rota and not all(_PASSA[g](usuario) for g in guardas_da_rota(rota)):
        return None
    return rota


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
            "rota": rota_para(usuario, n.rota),
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
