"""Modelos do Módulo de Sincronização Automática de Plataformas.

Automatiza a OBTENÇÃO dos relatórios das plataformas externas (Matific,
Elefante Letrado, …) e os entrega ao pipeline de importação JÁ EXISTENTE
(analisar → confirmar → snapshot → scoring → ranking → Quest). O upload manual
continua intacto como fallback.

Cinco entidades, todas isoladas por ``escola_id`` (multi-tenant):

* ``PlataformaCredencial`` — cofre: credencial da plataforma CIFRADA (Fernet).
* ``SincronizacaoConfig``  — agenda por (escola, plataforma) do scheduler.
* ``SincronizacaoExecucao``— histórico PERMANENTE de cada execução (nunca apaga).
* ``SincronizacaoLog``     — log detalhado por etapa (pesquisável); sem segredos.
* ``SincronizacaoAlerta``  — alertas operacionais (senha inválida, timeout, …).

Nada aqui guarda senha em texto: o segredo mora só em ``segredo_cifrado`` e a
chave de cifra vem da ``SECRET_KEY`` (fora do banco). Ver ``app/sync/vault.py``.
"""
from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import agora


class PlataformaCredencial(Base):
    """Credencial de uma plataforma externa para UMA escola, CIFRADA.

    ``segredo_cifrado`` guarda um JSON cifrado (Fernet) com o que o conector
    precisa para logar (ex.: ``{"usuario": ..., "senha": ...}``). A senha em
    texto NUNCA é persistida nem devolvida ao navegador. ``token_version``
    prepara a rotação futura (invalida sessões/credenciais antigas)."""

    __tablename__ = "plataforma_credenciais"

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(
        ForeignKey("escolas.id", ondelete="CASCADE"), index=True)
    plataforma: Mapped[str] = mapped_column(String(30))  # matific | elefante | ...
    segredo_cifrado: Mapped[str] = mapped_column(Text)   # Fernet(JSON)
    # nao_validada | valida | invalida | expirada
    status: Mapped[str] = mapped_column(String(20), default="nao_validada")
    validada_em: Mapped[datetime | None] = mapped_column(default=None)
    ultimo_erro: Mapped[str | None] = mapped_column(String(300), default=None)
    token_version: Mapped[int] = mapped_column(default=1)  # rotação futura
    created_at: Mapped[datetime] = mapped_column(default=agora)
    updated_at: Mapped[datetime] = mapped_column(default=agora, onupdate=agora)

    __table_args__ = (
        UniqueConstraint("escola_id", "plataforma", name="uq_credencial_escola_plat"),
    )


class SincronizacaoConfig(Base):
    """Agenda do scheduler por (escola, plataforma).

    ``cadencia`` = manual (só sob demanda) | diaria | semanal. ``proxima_execucao``
    é materializada para o worker varrer o que venceu numa única consulta."""

    __tablename__ = "sincronizacao_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(
        ForeignKey("escolas.id", ondelete="CASCADE"), index=True)
    plataforma: Mapped[str] = mapped_column(String(30))
    ativo: Mapped[bool] = mapped_column(default=False)
    cadencia: Mapped[str] = mapped_column(String(20), default="manual")
    hora_local: Mapped[str] = mapped_column(String(5), default="03:00")  # "HH:MM"
    dia_semana: Mapped[int | None] = mapped_column(default=None)  # 0=segunda (semanal)
    proxima_execucao: Mapped[datetime | None] = mapped_column(default=None, index=True)
    created_at: Mapped[datetime] = mapped_column(default=agora)
    updated_at: Mapped[datetime] = mapped_column(default=agora, onupdate=agora)

    __table_args__ = (
        UniqueConstraint("escola_id", "plataforma", name="uq_syncconfig_escola_plat"),
    )


class SincronizacaoExecucao(Base):
    """Histórico PERMANENTE de uma execução de sincronização (nunca apagado).

    Guarda tudo o que o painel de histórico exige: origem (manual/scheduler),
    responsável, contadores, versão do parser e o link para a ``Importacao``
    gerada (a trilha do pipeline atual)."""

    __tablename__ = "sincronizacao_execucoes"

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(
        ForeignKey("escolas.id", ondelete="CASCADE"), index=True)
    plataforma: Mapped[str] = mapped_column(String(30))
    origem: Mapped[str] = mapped_column(String(12))  # manual | scheduler
    usuario_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"), default=None)
    # fila | executando | concluida | erro | cancelada | sem_dados
    status: Mapped[str] = mapped_column(String(16), default="fila", index=True)
    # Momento mais cedo em que o worker pode pegar esta execução (backoff de
    # retry / agendamento). None = disponível já.
    disponivel_em: Mapped[datetime | None] = mapped_column(default=None, index=True)
    iniciada_em: Mapped[datetime | None] = mapped_column(default=None)
    finalizada_em: Mapped[datetime | None] = mapped_column(default=None)
    duracao_ms: Mapped[int] = mapped_column(default=0)
    qtd_alunos: Mapped[int] = mapped_column(default=0)
    qtd_turmas: Mapped[int] = mapped_column(default=0)
    qtd_alteracoes: Mapped[int] = mapped_column(default=0)
    qtd_arquivos: Mapped[int] = mapped_column(default=0)
    qtd_erros: Mapped[int] = mapped_column(default=0)
    parser_versao: Mapped[str | None] = mapped_column(String(20), default=None)
    conector_versao: Mapped[str | None] = mapped_column(String(20), default=None)
    importacao_id: Mapped[int | None] = mapped_column(
        ForeignKey("importacoes.id", ondelete="SET NULL"), default=None)
    tentativa: Mapped[int] = mapped_column(default=1)
    erro_resumo: Mapped[str | None] = mapped_column(String(300), default=None)
    # Parâmetros específicos DESTA execução (ex.: janela de datas do Matific
    # p/ coleta por período). Vazio = sync normal. Persistido porque o worker
    # roda numa thread que relê a linha pelo id.
    parametros: Mapped[dict] = mapped_column(JSON, default=dict, server_default=text("'{}'"))
    created_at: Mapped[datetime] = mapped_column(default=agora)

    __table_args__ = (
        Index("ix_sync_exec_escola_inicio", "escola_id", "iniciada_em"),
        # EXCLUSÃO MÚTUA no banco: no máximo UMA execução ativa (fila/executando)
        # por (escola, plataforma). Índice único PARCIAL — garante, sob múltiplos
        # workers/réplicas, que dois enfileiramentos concorrentes não criem duas
        # execuções ativas para a mesma escola (evita import/recálculo dobrado).
        Index("uq_sync_exec_ativa", "escola_id", "plataforma", unique=True,
              postgresql_where=text("status IN ('fila', 'executando')"),
              sqlite_where=text("status IN ('fila', 'executando')")),
    )


class SincronizacaoLog(Base):
    """Log estruturado por etapa de uma execução (pesquisável no painel).

    NUNCA registra senha/segredo — só descrições operacionais. ``etapa`` cobre:
    autenticacao, download, parser, validacao, importacao, snapshot, ranking,
    quest, scheduler."""

    __tablename__ = "sincronizacao_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    execucao_id: Mapped[int] = mapped_column(
        ForeignKey("sincronizacao_execucoes.id", ondelete="CASCADE"), index=True)
    escola_id: Mapped[int] = mapped_column(  # denormalizado p/ isolamento/filtro
        ForeignKey("escolas.id", ondelete="CASCADE"), index=True)
    etapa: Mapped[str] = mapped_column(String(20), index=True)
    nivel: Mapped[str] = mapped_column(String(8), default="info")  # info|warn|error
    mensagem: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(default=agora, index=True)


class SincronizacaoAlerta(Base):
    """Alerta operacional acionável (senha inválida/expirada, timeout, parser
    incompatível, plataforma indisponível, sincronização lenta, …)."""

    __tablename__ = "sincronizacao_alertas"

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(
        ForeignKey("escolas.id", ondelete="CASCADE"), index=True)
    plataforma: Mapped[str | None] = mapped_column(String(30), default=None)
    tipo: Mapped[str] = mapped_column(String(30), index=True)
    severidade: Mapped[str] = mapped_column(String(8), default="warn")  # info|warn|critico
    mensagem: Mapped[str] = mapped_column(String(500))
    resolvido: Mapped[bool] = mapped_column(default=False, index=True)
    resolvido_em: Mapped[datetime | None] = mapped_column(default=None)
    execucao_id: Mapped[int | None] = mapped_column(
        ForeignKey("sincronizacao_execucoes.id", ondelete="SET NULL"), default=None)
    created_at: Mapped[datetime] = mapped_column(default=agora, index=True)
