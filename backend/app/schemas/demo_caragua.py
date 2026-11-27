from typing import Annotated, Literal

from pydantic import BaseModel, Field

RegiaoId = Literal["norte", "centro", "sul", "serra"]
NotaDemonstracao = Annotated[float, Field(ge=0, le=100)]
Quantidade = Annotated[int, Field(ge=0)]


class EscolaDemonstracao(BaseModel, frozen=True):
    id: str
    nome: str
    regiao: RegiaoId
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    nota: NotaDemonstracao | None
    com_dados: Quantidade
    matriculados: Quantidade


class RegiaoDemonstracao(BaseModel, frozen=True):
    id: RegiaoId
    nome: str
    contexto: str


class AvaliacaoDemonstracao(BaseModel, frozen=True):
    escola_id: str
    avaliacao: Literal["SARESP", "SAEB"]
    edicao: int
    serie: str
    disciplina: Literal["Língua Portuguesa", "Matemática"]
    resultado: float | None


class DemonstracaoCaragua(BaseModel, frozen=True):
    escolas: tuple[EscolaDemonstracao, ...]
    regioes: tuple[RegiaoDemonstracao, ...]
    avaliacoes: tuple[AvaliacaoDemonstracao, ...]
