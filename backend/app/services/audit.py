"""Registro de auditoria — nada relevante acontece sem ficar no log (PRD §17).

Retenção e minimização (auditoria de 20/10/2026, achado 4). O log é permanente e
guarda nomes; NÃO há regra jurídica definida de prazo. Aqui fica só o MECANISMO,
neutro e desligado por padrão (docs/lgpd/RETENCAO-TECNICA.md):

* minimização: com ``AUDITORIA_MINIMIZAR_NOMES=true`` (ou ``minimizar=True`` na
  chamada), a entrada sobre um aluno identificado por ``entidade_id`` deixa de
  gravar o nome dele quando o valor é o nome ATUAL do cadastro — o id basta para
  chegar a ele. Nome que DIFERE do cadastro (o da planilha, o recebido da
  plataforma, o anterior) é a evidência do registro e continua;
* expurgo por categoria (``RETENCAO_*_DIAS``; 0 = desligado), com simulação que
  só conta (``scripts/expurgar_retencao.py --dry-run``).
"""
from __future__ import annotations

import unicodedata
from datetime import datetime, timedelta, timezone

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import and_, delete, func, not_, or_, select
from sqlalchemy.orm import Session

from app.models import LogAuditoria


class ConfigRetencao(BaseSettings):
    """Lida do ambiente/.env como as demais. Mora aqui por posse de arquivo nesta
    rodada; o lugar natural é ``app.core.config.Settings`` (mesmos nomes)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Padrão = comportamento atual (o nome continua sendo gravado): ligar muda o
    # conteúdo da trilha de auditoria — decisão do dono.
    AUDITORIA_MINIMIZAR_NOMES: bool = False
    # Prazos em DIAS por categoria; 0 = não expurga (padrão de todas).
    RETENCAO_AUDITORIA_ACESSO_DIAS: int = 0
    RETENCAO_AUDITORIA_QUEST_DIAS: int = 0
    RETENCAO_AUDITORIA_ALUNOS_DIAS: int = 0
    RETENCAO_AUDITORIA_DEMAIS_DIAS: int = 0
    RETENCAO_SINCRONIZACAO_LOGS_DIAS: int = 0
    RETENCAO_NOTIFICACOES_DIAS: int = 0


config_retencao = ConfigRetencao()

# ---------------------------------------------------------------------------
# Minimização
# ---------------------------------------------------------------------------

# Chaves que, numa entrada sobre um aluno, guardam o NOME dele.
_CHAVES_DE_NOME_DO_ALUNO = frozenset({"nome", "aluno", "nome_exibicao", "apelido",
                                      "origem", "origem_linha", "nome_recebido"})


def _chave_nome(texto: str) -> str:
    sem_acento = "".join(c for c in unicodedata.normalize("NFD", texto or "")
                         if unicodedata.category(c) != "Mn")
    return " ".join(sem_acento.split()).casefold()


def minimizar_detalhes(db: Session, entidade: str | None, entidade_id: int | None,
                       detalhes: dict | None) -> dict:
    """``detalhes`` sem o nome ATUAL do aluno ``entidade_id`` (o id basta).
    Só remove o valor IGUAL ao do cadastro (sem acento/caixa/espaço extra), nas
    chaves de nome, em qualquer nível. Sem aluno identificado, devolve igual."""
    detalhes = dict(detalhes or {})
    if entidade != "aluno" or entidade_id is None or not detalhes:
        return detalhes
    from app.models import Aluno

    aluno = db.get(Aluno, entidade_id)
    alvo = _chave_nome(aluno.nome) if aluno is not None and aluno.nome else ""
    if not alvo:
        return detalhes

    def _limpar(valor):
        if isinstance(valor, dict):
            return {k: _limpar(v) for k, v in valor.items()
                    if not (k in _CHAVES_DE_NOME_DO_ALUNO and isinstance(v, str)
                            and _chave_nome(v) == alvo)}
        if isinstance(valor, list):
            return [_limpar(v) for v in valor]
        return valor

    return _limpar(detalhes)


def registrar(
    db: Session,
    acao: str,
    escola_id: int | None = None,
    usuario_id: int | None = None,
    entidade: str | None = None,
    entidade_id: int | None = None,
    detalhes: dict | None = None,
    minimizar: bool | None = None,
) -> None:
    """``minimizar``: None = segue ``AUDITORIA_MINIMIZAR_NOMES``; True/False força."""
    if minimizar is None:
        minimizar = config_retencao.AUDITORIA_MINIMIZAR_NOMES
    if minimizar:
        detalhes = minimizar_detalhes(db, entidade, entidade_id, detalhes)
    db.add(
        LogAuditoria(
            escola_id=escola_id,
            usuario_id=usuario_id,
            acao=acao,
            entidade=entidade,
            entidade_id=entidade_id,
            detalhes=detalhes or {},
        )
    )
    # Notificação acionável por perfil (Fase 2): para os eventos conhecidos,
    # materializa 1 aviso com a rota da tela de ação. Import local evita ciclo
    # (notificacoes importa models/permissoes, não audit). No-op para as demais
    # ações. Fica na MESMA sessão → commit atômico com a operação principal.
    from app.services import notificacoes as _notif
    _notif.emitir_da_auditoria(db, acao, escola_id, autor_id=usuario_id,
                               entidade=entidade, entidade_id=entidade_id)
    # commit fica a cargo da operação principal, mantendo atomicidade


# ---------------------------------------------------------------------------
# Expurgo por categoria (DESLIGADO por padrão)
# ---------------------------------------------------------------------------

# Registros de acesso (login do Edu e do Quest). Referência, não parecer: o Marco
# Civil (Lei 12.965/2014, art. 15) manda o provedor de aplicação guardar registros
# de acesso por no MÍNIMO 6 meses. Por isso o expurgo desta categoria recusa prazo
# menor que PISO_ACESSO_DIAS sem confirmação explícita (fail-safe técnico).
_ACOES_DE_ACESSO = ("login", "quest.login", "quest.login_falhou")
PISO_ACESSO_DIAS = 183

# Provas do próprio esquecimento/expurgo (sem nome): nunca entram no expurgo
# automático — são a evidência de que o pedido do titular foi cumprido. Rever
# junto com a decisão jurídica de prazos.
ACOES_PRESERVADAS = frozenset({
    "aluno.excluido_permanente", "aluno.esquecimento_fora_do_cadastro",
    "ia.conversas_esquecimento", "retencao.expurgo",
    # Resumo (ids e contagens) da exclusão física de turma com alunos (D19).
    "turma.exclusao_com_alunos",
    # Restauração do backup: leva o mapa {id novo: id do arquivo} das fichas
    # (só números), a linhagem que impede um arquivo anterior a ela de trazer de
    # volta a criança excluída de vez depois (``backup._excluidos_depois_do_backup``).
    "backup.restaurado",
})

CATEGORIAS = ("auditoria_acesso", "auditoria_quest", "auditoria_alunos",
              "auditoria_demais", "sincronizacao_logs", "notificacoes")

_VARIAVEL = {
    "auditoria_acesso": "RETENCAO_AUDITORIA_ACESSO_DIAS",
    "auditoria_quest": "RETENCAO_AUDITORIA_QUEST_DIAS",
    "auditoria_alunos": "RETENCAO_AUDITORIA_ALUNOS_DIAS",
    "auditoria_demais": "RETENCAO_AUDITORIA_DEMAIS_DIAS",
    "sincronizacao_logs": "RETENCAO_SINCRONIZACAO_LOGS_DIAS",
    "notificacoes": "RETENCAO_NOTIFICACOES_DIAS",
}


def _e_acesso():
    acao = LogAuditoria.acao
    return or_(acao.in_(_ACOES_DE_ACESSO), acao.like("login.%"))


def _e_alunos():
    acao = LogAuditoria.acao
    return or_(*(acao.like(f"{p}.%") for p in ("aluno", "matricula", "identidade",
                                                "revisao")))


def _filtro_auditoria(categoria: str):
    """Categorias DISJUNTAS: cada entrada cai em exatamente uma."""
    quest = LogAuditoria.acao.like("quest.%")
    filtros = {
        "auditoria_acesso": _e_acesso(),
        "auditoria_quest": and_(quest, not_(_e_acesso())),
        "auditoria_alunos": and_(_e_alunos(), not_(_e_acesso())),
        "auditoria_demais": and_(not_(_e_acesso()), not_(quest), not_(_e_alunos())),
    }
    return and_(filtros[categoria], LogAuditoria.acao.not_in(ACOES_PRESERVADAS))


def prazos_configurados() -> dict[str, int]:
    return {c: int(getattr(config_retencao, _VARIAVEL[c]) or 0) for c in CATEGORIAS}


def expurgar_retencao(db: Session, *, simular: bool = True,
                      prazos: dict[str, int] | None = None,
                      agora: datetime | None = None,
                      aceitar_abaixo_do_piso: bool = False) -> dict[str, dict]:
    """Apaga (ou, com ``simular``, só CONTA) o que passou do prazo de cada
    categoria. Prazo 0 (o padrão) = categoria desligada: nem conta. NÃO commita.
    Devolve {categoria: {"dias", "corte", "linhas"}} — sem dado pessoal."""
    from app.models import Notificacao, SincronizacaoLog

    prazos = {**prazos_configurados(), **(prazos or {})}
    desconhecidas = set(prazos) - set(CATEGORIAS)
    if desconhecidas:
        raise ValueError(f"categoria(s) desconhecida(s): {sorted(desconhecidas)}")
    dias_acesso = prazos.get("auditoria_acesso", 0)
    if 0 < dias_acesso < PISO_ACESSO_DIAS and not aceitar_abaixo_do_piso:
        raise ValueError(
            f"auditoria_acesso={dias_acesso} dias é menor que {PISO_ACESSO_DIAS} "
            "(6 meses — Marco Civil, art. 15, para registros de acesso). Confirme a "
            "decisão jurídica e use a opção explícita para abaixo do piso.")
    agora = (agora or datetime.now(timezone.utc)).replace(tzinfo=None)
    alvos = {
        **{c: (LogAuditoria, LogAuditoria.created_at, _filtro_auditoria(c))
           for c in CATEGORIAS if c.startswith("auditoria_")},
        "sincronizacao_logs": (SincronizacaoLog, SincronizacaoLog.created_at, None),
        "notificacoes": (Notificacao, Notificacao.created_at, None),
    }
    resultado: dict[str, dict] = {}
    for categoria in CATEGORIAS:
        dias = int(prazos.get(categoria) or 0)
        if dias <= 0:
            resultado[categoria] = {"dias": 0, "corte": None, "linhas": 0}
            continue
        modelo, coluna, filtro = alvos[categoria]
        corte = agora - timedelta(days=dias)
        condicao = coluna < corte if filtro is None else and_(coluna < corte, filtro)
        linhas = db.execute(select(func.count()).select_from(modelo)
                            .where(condicao)).scalar_one()
        if not simular and linhas:
            db.execute(delete(modelo).where(condicao)
                       .execution_options(synchronize_session=False))
        resultado[categoria] = {"dias": dias, "corte": corte.isoformat(timespec="seconds"),
                                "linhas": linhas}
    if not simular and any(r["linhas"] for r in resultado.values()):
        registrar(db, "retencao.expurgo",
                  detalhes={c: r["linhas"] for c, r in resultado.items() if r["dias"]})
    return resultado
