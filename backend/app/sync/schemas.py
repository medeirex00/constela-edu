"""Schemas (Pydantic) da API do módulo de sincronização."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class _ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- entrada ----------------------------------------------------------------
class CredenciaisIn(BaseModel):
    usuario: str = Field(min_length=1, max_length=200)
    senha: str = Field(min_length=1, max_length=300)
    extra: dict = Field(default_factory=dict)


class ConfigIn(BaseModel):
    ativo: bool = False
    cadencia: str = Field(default="manual", pattern="^(manual|diaria|semanal)$")
    hora_local: str = Field(default="03:00", pattern=r"^\d{2}:\d{2}$")
    dia_semana: int | None = Field(default=None, ge=0, le=6)


# --- saída ------------------------------------------------------------------
class ResultadoTeste(BaseModel):
    ok: bool
    mensagem: str
    codigo: str | None = None


class ExecucaoOut(_ORM):
    id: int
    plataforma: str
    origem: str
    usuario_id: int | None
    status: str
    iniciada_em: datetime | None
    finalizada_em: datetime | None
    duracao_ms: int
    qtd_alunos: int
    qtd_turmas: int
    qtd_alteracoes: int
    qtd_arquivos: int
    qtd_erros: int
    parser_versao: str | None
    conector_versao: str | None
    tentativa: int
    erro_resumo: str | None
    created_at: datetime


class LogOut(_ORM):
    id: int
    execucao_id: int
    etapa: str
    nivel: str
    mensagem: str
    created_at: datetime


class AlertaOut(_ORM):
    id: int
    plataforma: str | None
    tipo: str
    severidade: str
    mensagem: str
    resolvido: bool
    resolvido_em: datetime | None
    created_at: datetime


class PlataformaStatus(BaseModel):
    plataforma: str
    estrategia: str
    conectada: bool                     # credencial válida
    credencial_status: str              # nao_configurada | nao_validada | valida | invalida
    validada_em: datetime | None = None
    ultimo_erro: str | None = None
    agendada: bool = False
    cadencia: str = "manual"
    hora_local: str = "03:00"
    dia_semana: int | None = None
    proxima_execucao: datetime | None = None
    ultima_execucao: ExecucaoOut | None = None


class EscolaStatus(BaseModel):
    escola_id: int
    escola_nome: str
    qtd_alunos: int
    qtd_turmas: int
    plataformas: list[PlataformaStatus]
    alertas_abertos: int
    # Estado do onboarding (fluxo "escola pronta em <5 min").
    lista_piloto_importada: bool = False   # já tem turmas cadastradas?
    integracao_configurada: bool = False   # já salvou ≥1 credencial de plataforma?


class DashboardOut(BaseModel):
    escolas_total: int
    escolas_configuradas: int
    escolas_sincronizadas: int
    escolas_com_erro: int
    em_andamento: int
    fila: int
    workers_ativos: int
    scheduler_ligado: bool
    ultima_sincronizacao: datetime | None
    duracao_ultima_ms: int | None
    tempo_medio_ms: int | None
    alertas_abertos: int
