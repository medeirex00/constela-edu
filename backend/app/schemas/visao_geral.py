"""Contrato das rotas da Visão Geral (identidade visual v2): ``/visao-geral`` e
``/atividade-semanal``. O modelo de resposta é o CONTRATO: um campo que o serviço
deixar de mandar, ou mandar com outro tipo, vira erro no teste em vez de chegar torto
à tela."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ----------------------------------------------------------------- Visão geral
Cobertura = Literal["completa", "parcial", "sem_dado"]


class PeriodoVisaoOut(BaseModel):
    chave: str
    rotulo: str
    inicio: str = Field(description="AAAA-MM-DD")
    fim: str = Field(description="AAAA-MM-DD")
    dias_decorridos: int
    dias_total: int


class ComparacaoOut(BaseModel):
    rotulo: str
    inicio: str = Field(description="AAAA-MM-DD")
    fim: str = Field(description="AAAA-MM-DD")


class AlunosVisaoOut(BaseModel):
    total: int
    ativos: int | None
    ativos_anterior: int | None
    ativos_leitura: int | None
    ativos_matematica: int | None


class LeituraVisaoOut(BaseModel):
    contratado: bool
    livros: int | None
    livros_anterior: int | None
    tempo_min: int | None
    tempo_min_anterior: int | None
    cobertura: Cobertura = Field(
        description="completa = o Elefante Letrado foi coletado até a véspera do último "
                    "dia do período; parcial = a coleta parou antes (os números contam "
                    "só até coletado_ate); sem_dado = sem número no período")
    coletado_ate: str | None = Field(
        description="AAAA-MM-DD (Brasília): último dia já coletado do Elefante Letrado "
                    "para estes alunos; null = nunca coletado (ou fora do plano)")


class MatematicaVisaoOut(BaseModel):
    contratado: bool
    atividades: int | None
    atividades_anterior: int | None
    cobertura: Cobertura


class VisaoGeralOut(BaseModel):
    periodo: PeriodoVisaoOut
    comparacao: ComparacaoOut | None
    alunos: AlunosVisaoOut
    leitura: LeituraVisaoOut
    matematica: MatematicaVisaoOut
    atualizado_em: str | None = Field(description="ISO 8601 com fuso (UTC)")


# ---------------------------------------------------------- Atividade semanal
class SemanaOut(BaseModel):
    inicio: str = Field(description="AAAA-MM-DD (segunda-feira)")
    fim: str = Field(description="AAAA-MM-DD (domingo)")
    leitura_alunos: int | None
    leitura_pct: float | None
    matematica_alunos: int | None
    matematica_pct: float | None


class AtividadeSemanalOut(BaseModel):
    denominador: int
    leitura_contratado: bool
    matematica_contratado: bool
    observacao: str
    semanas: list[SemanaOut]
