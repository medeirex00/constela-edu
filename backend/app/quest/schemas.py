"""Contratos Pydantic da API do Quest (aluno, professor e família)."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Autenticação infantil
# ---------------------------------------------------------------------------

class FiguraOut(BaseModel):
    slug: str
    nome: str
    emoji: str


class QuemIn(BaseModel):
    codigo: str = Field(min_length=3, max_length=30)


class QuemOut(BaseModel):
    """Confirmação "É você?" antes do PIN — o mínimo para a criança se
    reconhecer, nada que sirva para enumerar dados."""
    primeiro_nome: str
    apelido: str
    avatar: dict


class EntrarIn(BaseModel):
    codigo: str = Field(min_length=3, max_length=30)
    pin: list[str] = Field(min_length=4, max_length=4)


class EntrarQrIn(BaseModel):
    qr_token: str = Field(min_length=8, max_length=64)


class PerfilOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    apelido: str
    codigo_amigo: str
    nivel: int
    xp_total: int
    moedas: int
    estrelas_total: int
    sequencia_dias: int
    avatar: dict
    preferencias: dict
    # Vem do cadastro (alunos.nome) — usado só na própria tela da criança
    primeiro_nome: str = ""


class SessaoOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    perfil: PerfilOut


# ---------------------------------------------------------------------------
# Perfil (escritas do aluno)
# ---------------------------------------------------------------------------

class AvatarIn(BaseModel):
    cor: str | None = None


class PreferenciasIn(BaseModel):
    som: bool | None = None
    musica: bool | None = None
    narracao: bool | None = None
    reduzir_animacoes: bool | None = None


# ---------------------------------------------------------------------------
# Professor (consumido pelo Edu web)
# ---------------------------------------------------------------------------

class AcessoAlunoOut(BaseModel):
    aluno_id: int
    nome: str
    apelido: str | None = None
    codigo_login: str | None = None
    ultimo_acesso: datetime | None = None
    tem_credencial: bool
