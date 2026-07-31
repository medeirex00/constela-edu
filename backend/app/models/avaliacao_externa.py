"""Avaliações externas (SAEB, IDEB, SARESP, Criança Alfabetizada, ...).

Estrutura GENÉRICA e extensível: adicionar uma avaliação nova é uma linha no
catálogo (``AvaliacaoExterna``) + um parser — sem refazer o modelo. Os resultados
vão todos para a MESMA tabela de fatos (``ResultadoAvaliacao``), em qualquer
granularidade que a fonte oficial publique. Os níveis que a fonte NÃO fornece
ficam NULOS — nunca inventados/forçados (regra do dono).

O casamento entre bases é pelo CÓDIGO INEP da escola (8 dígitos) — não pelo nome.
O IDEB é um INDICADOR derivado (desempenho × fluxo), então entra no catálogo com
``tipo='indicador'``, conceitualmente separado das avaliações de desempenho.
"""
from datetime import datetime

from sqlalchemy import Float, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import agora


class AvaliacaoExterna(Base):
    """Catálogo de avaliações/indicadores externos. Uma linha por fonte."""

    __tablename__ = "avaliacoes_externas"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Chave estável usada no código/import (ex.: "saeb", "ideb", "saresp").
    chave: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    nome: Mapped[str] = mapped_column(String(120))
    # "avaliacao" (mede desempenho) | "indicador" (derivado, ex.: IDEB).
    tipo: Mapped[str] = mapped_column(String(20), default="avaliacao")
    orgao: Mapped[str | None] = mapped_column(String(80), default=None)
    descricao: Mapped[str | None] = mapped_column(String(500), default=None)
    created_at: Mapped[datetime] = mapped_column(default=agora)


class ResultadoAvaliacao(Base):
    """Um resultado (fato) de uma avaliação externa, na granularidade da fonte.

    Só o que a fonte publica é preenchido; o resto fica NULO. Ex.: o IDEB por
    escola preenche escola/etapa e deixa componente/turma nulos; o SARESP pode
    preencher até turma; o SAEB por escola vai até componente (sem turma/aluno).
    """

    __tablename__ = "resultados_avaliacao"

    id: Mapped[int] = mapped_column(primary_key=True)
    avaliacao_id: Mapped[int] = mapped_column(
        ForeignKey("avaliacoes_externas.id", ondelete="CASCADE"), index=True)
    edicao: Mapped[int] = mapped_column(index=True)  # ano/edição (ex.: 2023)

    # Alcance. escola_id nulo = agregado (rede/UF/município). rede_id denormalizado
    # (da escola casada) para consultas por rede sem join.
    rede_id: Mapped[int | None] = mapped_column(
        ForeignKey("redes.id", ondelete="SET NULL"), index=True, default=None)
    escola_id: Mapped[int | None] = mapped_column(
        ForeignKey("escolas.id", ondelete="CASCADE"), index=True, default=None)
    # Código INEP CRU do arquivo — guardado mesmo quando não casa com nenhuma
    # escola (auditoria + recasamento futuro sem depender do nome).
    codigo_inep: Mapped[str | None] = mapped_column(String(8), index=True, default=None)

    # Dimensões (só as que a fonte dá).
    etapa: Mapped[str | None] = mapped_column(String(40), default=None)
    componente: Mapped[str | None] = mapped_column(String(40), default=None)
    turma: Mapped[str | None] = mapped_column(String(60), default=None)

    # A medida.
    indicador: Mapped[str] = mapped_column(String(60))   # "proficiencia" | "ideb" | ...
    valor: Mapped[float] = mapped_column(Float)
    unidade: Mapped[str] = mapped_column(String(30))     # "escala_saeb" | "indice" | "percentual"

    # Proveniência (arquivo/edição de onde veio), para o cruzamento ser auditável.
    fonte: Mapped[str | None] = mapped_column(String(200), default=None)
    created_at: Mapped[datetime] = mapped_column(default=agora)

    __table_args__ = (
        # Consulta típica: série histórica de um indicador por escola/etapa.
        Index("ix_resultado_escola_avaliacao",
              "escola_id", "avaliacao_id", "etapa", "componente", "edicao"),
        # Chave NATURAL do fato: impede linhas duplicadas sob coleta concorrente
        # (scheduler + "coletar agora"). COALESCE trata os NULOS (etapa/componente/
        # turma que a fonte não fornece) como '' — senão o UNIQUE os veria como
        # distintos e não barraria a duplicata. Só linhas casadas (escola_id) são
        # gravadas, então escola_id entra direto.
        Index("uq_resultado_natural", "avaliacao_id", "edicao", "indicador",
              "escola_id", text("COALESCE(etapa, '')"),
              text("COALESCE(componente, '')"), text("COALESCE(turma, '')"),
              unique=True),
    )
