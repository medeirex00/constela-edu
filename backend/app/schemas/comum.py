"""Schemas Pydantic — contrato da API.

Mantidos em um módulo único nesta fase; ao crescer, dividir por domínio
sem alterar os imports (o pacote reexporta tudo).
"""
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Autenticação -----------------------------------------------------------

class UsuarioOut(ORMModel):
    id: int
    nome: str
    email: str
    cargo: str
    is_global: bool
    escola_id: int | None
    status: str = "ativo"
    ultimo_acesso: datetime | None = None
    created_at: datetime | None = None


class LoginOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    usuario: UsuarioOut


# --- Escolas ----------------------------------------------------------------

class EscolaOut(ORMModel):
    id: int
    nome: str
    cidade: str | None
    estado: str | None
    logotipo_url: str | None
    ano_letivo_ativo: int
    status: str


class EscolaCreate(BaseModel):
    nome: str = Field(min_length=2, max_length=200)
    cidade: str | None = None
    estado: str | None = Field(default=None, max_length=2)
    ano_letivo_ativo: int = 2026


class EscolaUpdate(BaseModel):
    nome: str | None = None
    cidade: str | None = None
    estado: str | None = Field(default=None, max_length=2)
    logotipo_url: str | None = None
    ano_letivo_ativo: int | None = None
    status: str | None = None


# --- Acadêmico --------------------------------------------------------------

class ProfessorOut(ORMModel):
    id: int
    nome: str
    email: str | None
    observacoes: str | None


class ProfessorCreate(BaseModel):
    nome: str
    email: EmailStr | None = None
    observacoes: str | None = None


PADRAO_TURNO = "^(manha|tarde|noite|integral)$"


class TurmaOut(ORMModel):
    id: int
    nome: str
    ano_escolar: str
    ano_letivo: int
    professor_id: int | None
    turno: str | None = None
    capacidade_maxima: int | None = None
    observacoes: str | None = None
    status: str = "ativa"
    # Preenchidos na listagem para a tela de gestão
    professor_nome: str | None = None
    total_alunos: int = 0


class TurmaCreate(BaseModel):
    nome: str = Field(min_length=1, max_length=100)
    ano_escolar: str = Field(min_length=1, max_length=30)
    ano_letivo: int = Field(ge=2000, le=2100)
    professor_id: int | None = None
    turno: str | None = Field(default=None, pattern=PADRAO_TURNO)
    capacidade_maxima: int | None = Field(default=None, ge=1, le=500)
    observacoes: str | None = Field(default=None, max_length=2000)


class TurmaUpdate(BaseModel):
    """Atualização parcial — só o que foi enviado é alterado."""
    nome: str | None = Field(default=None, min_length=1, max_length=100)
    ano_escolar: str | None = Field(default=None, min_length=1, max_length=30)
    ano_letivo: int | None = Field(default=None, ge=2000, le=2100)
    professor_id: int | None = None
    turno: str | None = Field(default=None, pattern=PADRAO_TURNO)
    capacidade_maxima: int | None = Field(default=None, ge=1, le=500)
    observacoes: str | None = Field(default=None, max_length=2000)
    status: str | None = Field(default=None, pattern="^(ativa|arquivada)$")


class AlunoOut(ORMModel):
    id: int
    nome: str
    foto_url: str | None
    numero_chamada: int | None
    status: str
    turma: str | None = None
    ano_escolar: str | None = None


class AlunoCreate(BaseModel):
    nome: str = Field(min_length=2, max_length=200)
    turma_id: int
    numero_chamada: int | None = None
    data_nascimento: date | None = None
    observacoes: str | None = None


class AlunoPerfilOut(BaseModel):
    aluno: AlunoOut
    nota_matific: float
    nota_elefante: float
    nota_geral: float
    posicao: int | None
    detalhes: dict
    calculada_em: datetime | None


# --- Configurações ----------------------------------------------------------

class PesosOut(BaseModel):
    namespace: str
    valores: dict[str, float]
    soma: float


class PesosUpdate(BaseModel):
    valores: dict[str, float]


class NivelOut(ORMModel):
    id: int
    nome: str
    codigos: list
    pontos_padrao: float
    ordem: int


class DificuldadeSerieOut(BaseModel):
    ano_escolar: str
    pontos: dict[int, float]  # nivel_id -> pontos


class DificuldadeUpdate(BaseModel):
    ano_escolar: str
    nivel_id: int
    pontos: float = Field(ge=0)


class ReferenciasOut(BaseModel):
    modo: str
    valores_manuais: dict
    valores_em_uso: dict


class ReferenciasUpdate(BaseModel):
    modo: str = Field(pattern="^(auto|manual)$")
    valores_manuais: dict[str, float] = {}


# --- Ranking e Dashboard ----------------------------------------------------

class RankingItemOut(BaseModel):
    posicao: int
    aluno_id: int
    nome: str
    turma: str | None
    ano_escolar: str | None
    nota_matific: float
    nota_elefante: float
    nota_geral: float


class DashboardOut(BaseModel):
    escola: EscolaOut
    total_alunos: int
    total_turmas: int
    total_professores: int
    total_atividades: int
    total_livros: int
    tempo_leitura_min: int
    media_geral: float
    top10: list[RankingItemOut]
