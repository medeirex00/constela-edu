"""Schemas do fluxo de importação (PRD §15–§16, §50–§52)."""
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.comum import ORMModel


class CorrespondenciaOut(BaseModel):
    status: str  # exato | provavel | nao_encontrado
    aluno_id: int | None = None
    aluno_nome: str | None = None
    similaridade: float | None = None
    alternativas: list[dict] = []


class LinhaAnaliseOut(BaseModel):
    numero: int
    nome: str
    dados: dict
    erros: list[str]
    avisos: list[str]
    correspondencia: CorrespondenciaOut | None


class AnaliseOut(BaseModel):
    plataforma: str
    formato: str
    tipo: str  # pdf | texto
    arquivo_token: str | None
    arquivo_nome: str | None
    total_linhas: int
    total_erros: int
    erros_gerais: list[str]
    linhas: list[LinhaAnaliseOut]


class LinhaConfirmacao(BaseModel):
    nome: str
    dados: dict
    aluno_id: int | None = None
    criar_em_turma_id: int | None = None


class ImportacaoConfirm(BaseModel):
    plataforma: str = Field(pattern="^(matific|elefante)$")
    formato: str = Field(pattern="^(resumo|leituras)$")
    tipo: str = Field(pattern="^(pdf|texto)$")
    arquivo_token: str | None = None
    arquivo_nome: str | None = None
    data_referencia: datetime | None = None
    linhas: list[LinhaConfirmacao]


class ImportacaoOut(ORMModel):
    id: int
    plataforma: str
    tipo: str
    arquivo_original: str | None
    qtd_alunos: int
    qtd_erros: int
    tempo_ms: int
    status: str
    created_at: datetime
    usuario_nome: str | None = None


class ImportacaoResultadoOut(BaseModel):
    mensagem: str
    importacao_id: int
    qtd_alunos: int
    qtd_erros: int
    avisos: list[str] = []
