"""Contratos Pydantic da API do Quest (aluno, professor e família)."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Autenticação infantil (sem senha — o código é a credencial)
# ---------------------------------------------------------------------------

class QuemIn(BaseModel):
    codigo: str = Field(min_length=3, max_length=30)


class QuemOut(BaseModel):
    """Confirmação "É você?" antes de entrar — o mínimo para a criança se
    reconhecer."""
    nome: str
    apelido: str
    avatar: dict


class EntrarIn(BaseModel):
    codigo: str = Field(min_length=3, max_length=30)


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
    # Como a criança pediu para ser chamada ("" = ainda não escolheu —
    # dispara a cerimônia da primeira vez no app). No banco é NULL até a
    # cerimônia; a API sempre devolve string.
    nome_exibicao: str | None = ""
    # Nome usado nas falas: nome_exibicao ou o primeiro nome do cadastro
    nome: str = ""
    # Dias desde o último login (alimenta a saudação com memória do Cosmo)
    dias_sem_jogar: int = 0
    # Código do próprio cartão — alimenta o "Quem vai jogar?" do aparelho
    codigo_login: str = ""


class SessaoOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    # Primeiro login da credencial — o app abre a cerimônia de boas-vindas
    primeira_vez: bool = False
    perfil: PerfilOut


# ---------------------------------------------------------------------------
# Perfil (escritas do aluno)
# ---------------------------------------------------------------------------

class AvatarIn(BaseModel):
    pele: str | None = None
    cabelo: str | None = None
    cor_cabelo: str | None = None
    top: str | None = None
    camiseta: str | None = None
    baixo: str | None = None
    calca: str | None = None
    tenis: str | None = None
    chapeu: str | None = None
    costas: str | None = None
    aura: str | None = None
    mao: str | None = None
    pet: str | None = None
    veiculo: str | None = None
    cor: str | None = None


class NomeIn(BaseModel):
    nome: str = Field(min_length=2, max_length=20)


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
    nome_exibicao: str | None = None
    apelido: str | None = None
    codigo_login: str | None = None
    ultimo_acesso: datetime | None = None
    tem_credencial: bool
