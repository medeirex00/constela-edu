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
    # Blindagem: "os dados estão envelhecendo em silêncio?" — quando foi a última
    # sincronização BEM-SUCEDIDA e se já passou do limite da cadência.
    ultimo_sucesso_em: datetime | None = None
    desatualizada: bool = False
    # Contagens HONESTAS da cobertura dos dados — cada número é um COUNT do banco,
    # nada é inferido. Universo: alunos ATIVOS matriculados no ano letivo ativo.
    # `None` = NÃO DÁ PARA CONTAR (plataforma sem tabela de snapshot ou escola
    # sem ano letivo ativo) — diferente de `0`, que é "contei e não há ninguém".
    alunos_com_dados: int | None = None  # com ≥1 snapshot desta plataforma
    alunos_sem_dados: int | None = None  # sem nenhum snapshot desta plataforma
    # Só Elefante: snapshot ATUAL com livros_unicos == 0 ("usa e ainda não
    # produziu" — um zero legítimo, diferente de "sem dado"). Matific: None.
    alunos_com_zero_registros: int | None = None
    # Frescor do dado dos alunos PONTUADOS: max(data_referencia) só dos snapshots
    # de alunos do MESMO universo acima (ativos + matriculados no ano ativo). Um
    # arquivado ou um aluno de outro ano não pode fazer a integração parecer em
    # dia. None = sem snapshot no universo (ou não dá para contar).
    dado_mais_recente_em: datetime | None = None


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
    # Pendências de CORRESPONDÊNCIA dos últimos 30 dias (LogAuditoria com
    # `aluno.revisao_necessaria` ou `importacao.linha_ignorada`): o que a escola
    # precisa revisar para a integração ficar íntegra. 0 = nada pendente.
    pendencias_correspondencia_30d: int = 0


class DashboardOut(BaseModel):
    escolas_total: int
    escolas_configuradas: int
    escolas_sincronizadas: int
    escolas_com_erro: int
    escolas_desatualizadas: int = 0   # dado envelhecendo em silêncio (sem sucesso há X)
    em_andamento: int
    fila: int
    workers_ativos: int
    scheduler_ligado: bool
    ultima_sincronizacao: datetime | None
    duracao_ultima_ms: int | None
    tempo_medio_ms: int | None
    alertas_abertos: int
