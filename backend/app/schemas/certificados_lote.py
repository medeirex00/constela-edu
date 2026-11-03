"""Contrato da emissão de certificados EM LOTE (identidade visual v2, decisão D7):
``POST /escolas/{id}/certificados/lote/previa`` e ``POST /escolas/{id}/certificados/lote``."""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

TETO_LOTE = 50
# Maior id que cabe na coluna (integer do PostgreSQL): acima disso o banco recusaria
# a consulta com erro 500 em vez de "aluno não encontrado".
_ID_MAXIMO = 2_147_483_647
ModeloCertificado = Literal["elefante", "matific"]


class PreviaLoteIn(BaseModel):
    modelo: ModeloCertificado | None = None
    aluno_ids: list[Annotated[int, Field(ge=1, le=_ID_MAXIMO)]] = Field(
        min_length=1, max_length=TETO_LOTE,
        description=f"1 a {TETO_LOTE} ids, na ordem da lista, sem repetidos")

    @field_validator("aluno_ids")
    @classmethod
    def _sem_repetidos(cls, ids: list[int]) -> list[int]:
        vistos: set[int] = set()
        repetidos: set[int] = set()
        for aluno_id in ids:
            (repetidos if aluno_id in vistos else vistos).add(aluno_id)
        if repetidos:
            raise ValueError(
                f"aluno_ids repetidos: {sorted(repetidos)} — cada aluno entra uma vez no lote.")
        return ids


class LoteIn(PreviaLoteIn):
    bimestre: int | None = Field(default=None, ge=1, le=4)


class ItemPreviaOut(BaseModel):
    aluno_id: int
    nome: str | None
    turma: str | None
    apto: bool
    motivo: str | None


class PreviaLoteOut(BaseModel):
    modelo: ModeloCertificado | None
    itens: list[ItemPreviaOut]
