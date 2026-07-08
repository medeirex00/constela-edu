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
    username: str | None = None
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
    # Um status fora do vocabulário faria a escola sumir de TODAS as listas
    # (o GET filtra por igualdade exata) sem caminho de volta pela interface.
    status: str | None = Field(default=None, pattern="^(ativa|inativa)$")


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
    # Para o modal "Editar aluno" pré-preencher todos os campos do cadastro.
    data_nascimento: date | None = None
    observacoes: str | None = None


class AlunoCreate(BaseModel):
    nome: str = Field(min_length=2, max_length=200)
    turma_id: int
    numero_chamada: int | None = None
    data_nascimento: date | None = None
    observacoes: str | None = None


class AlunoUpdate(BaseModel):
    """Edição parcial do cadastro do aluno (só os campos enviados mudam)."""
    nome: str | None = Field(default=None, min_length=2, max_length=200)
    numero_chamada: int | None = None
    data_nascimento: date | None = None
    observacoes: str | None = Field(default=None, max_length=1000)


class AlunoGestaoOut(ORMModel):
    """Aluno com nota e data de cadastro — usado no painel de gestão da turma."""
    id: int
    nome: str
    foto_url: str | None
    numero_chamada: int | None
    status: str
    turma: str | None = None
    ano_escolar: str | None = None
    created_at: datetime | None = None
    nota_geral: float | None = None
    posicao: int | None = None


class AcaoAlunos(BaseModel):
    """Ação em massa (ou individual) sobre alunos: arquivar, reativar, excluir
    (lógico) ou transferir de turma."""
    aluno_ids: list[int] = Field(min_length=1)
    acao: str = Field(pattern="^(arquivar|reativar|excluir|transferir)$")
    turma_id: int | None = None  # obrigatório quando acao == "transferir"


class ExclusaoPermanenteAlunos(BaseModel):
    """Exclusão FÍSICA irreversível: exige confirmação textual explícita."""
    aluno_ids: list[int] = Field(min_length=1)
    confirmacao: str = ""


class FaixaLeituraOut(BaseModel):
    codigo: str
    nome: str
    quantidade: int
    pontos_por_livro: float
    pontos: float
    percentual: float


class LeituraNiveisOut(BaseModel):
    faixas: list[FaixaLeituraOut]
    total_livros: int
    pontos_dificuldade: float
    faixa_predominante: str | None = None


class AlunoPerfilOut(BaseModel):
    aluno: AlunoOut
    nota_matific: float
    nota_elefante: float
    nota_geral: float
    posicao: int | None
    detalhes: dict
    calculada_em: datetime | None
    leitura_niveis: LeituraNiveisOut | None = None


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
    codigo: str | None = None
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
