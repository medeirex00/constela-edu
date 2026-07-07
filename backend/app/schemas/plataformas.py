"""Schemas dos módulos Matific, Elefante Letrado e Catálogo de Livros (PRD §55–§57)."""
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.comum import ORMModel


class MatificAlunoOut(BaseModel):
    aluno_id: int
    nome: str
    turma: str | None
    ano_escolar: str | None
    atividades: int
    estrelas: int
    pontuacao_media: float
    data_referencia: datetime | None


class MatificEdicao(BaseModel):
    atividades: int = Field(ge=0)
    estrelas: int = Field(ge=0)
    pontuacao_media: float = Field(ge=0, le=100)
    motivo: str | None = None


class ElefanteAlunoOut(BaseModel):
    aluno_id: int
    nome: str
    turma: str | None
    ano_escolar: str | None
    livros_unicos: int
    tempo_leitura_min: int
    questoes_tentativas: int
    questoes_acertos: int
    livros_por_nivel: dict
    data_referencia: datetime | None


class ElefanteEdicao(BaseModel):
    livros_unicos: int | None = Field(default=None, ge=0)
    tempo_leitura_min: int = Field(ge=0)
    questoes_tentativas: int = Field(ge=0)
    questoes_acertos: int = Field(ge=0)
    livros_por_nivel: dict[str, int] = {}
    motivo: str | None = None


class NiveisLeituraEdicao(BaseModel):
    """Informar os livros concluídos por FAIXA de dificuldade (ex.:
    {"pre_leitor": 8, "nivel_1": 15, ...}). O total e os pontos de dificuldade
    são derivados; as demais métricas do Elefante são preservadas."""
    faixas: dict[str, int]
    motivo: str | None = None


class LivroOut(ORMModel):
    id: int
    titulo: str
    autor: str | None
    nivel_codigo: str
    categoria: str | None
    paginas: int | None
    pontos: float = 0.0
    leituras: int = 0


class LivroCreate(BaseModel):
    titulo: str = Field(min_length=1, max_length=300)
    autor: str | None = None
    nivel_codigo: str = Field(min_length=1, max_length=5)
    categoria: str | None = None
    paginas: int | None = Field(default=None, ge=1)


class LivroUpdate(BaseModel):
    titulo: str | None = Field(default=None, min_length=1, max_length=300)
    autor: str | None = None
    nivel_codigo: str | None = Field(default=None, min_length=1, max_length=5)
    categoria: str | None = None
    paginas: int | None = Field(default=None, ge=1)
