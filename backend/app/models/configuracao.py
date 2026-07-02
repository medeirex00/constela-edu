from datetime import datetime

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import agora


class Configuracao(Base):
    """Armazenamento chave-valor de TODOS os pesos e regras do sistema.

    Nada de peso "hardcoded" (PRD §5, §29): o motor de cálculo lê daqui.
    `valor` é JSON, o que permite números, dicionários ou listas.

    Namespaces usados na Fase 1:
      pesos.matific   -> {"atividades": 40, "media": 35, "estrelas": 25}
      pesos.elefante  -> {"livros": 35, "dificuldade": 30, "questoes": 30, "tempo": 5}
      pesos.questoes  -> {"tentativas": 30, "acertos": 70}
      pesos.geral     -> {"matific": 50, "elefante": 50}
      desempate.criterios -> lista ordenada (PRD §42)
    """

    __tablename__ = "configuracoes"
    __table_args__ = (
        UniqueConstraint("escola_id", "namespace", "chave", name="uq_config"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    namespace: Mapped[str] = mapped_column(String(60), index=True)
    chave: Mapped[str] = mapped_column(String(60))
    valor: Mapped[dict | list | int | float | str] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(default=agora, onupdate=agora)


class NivelDificuldade(Base):
    """Categorias de dificuldade dos livros (PRD §38). Totalmente editáveis."""

    __tablename__ = "niveis_dificuldade"

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    nome: Mapped[str] = mapped_column(String(60))            # ex.: "Pré-Leitor"
    codigos: Mapped[list] = mapped_column(JSON)               # ex.: ["AA","BB","CC","DD"]
    pontos_padrao: Mapped[float] = mapped_column(default=1.0)
    ordem: Mapped[int] = mapped_column(default=0)


class DificuldadeTurma(Base):
    """Pontuação de cada nível por série (PRD §39, §61).

    Permite que "AA" valha 3 pontos no 1º Ano e 0 no 5º Ano,
    equilibrando a competição entre séries.
    """

    __tablename__ = "dificuldade_turma"
    __table_args__ = (
        UniqueConstraint("escola_id", "ano_escolar", "nivel_id", name="uq_dif_serie_nivel"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    ano_escolar: Mapped[str] = mapped_column(String(30), index=True)  # ex.: "1º Ano"
    nivel_id: Mapped[int] = mapped_column(ForeignKey("niveis_dificuldade.id"))
    pontos: Mapped[float] = mapped_column(default=0.0)
    updated_at: Mapped[datetime] = mapped_column(default=agora, onupdate=agora)


class ReferenciaNormalizacao(Base):
    """Referências usadas para levar todo indicador à escala 0–100 (PRD §31, §62)."""

    __tablename__ = "referencias_normalizacao"

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), unique=True, index=True)
    modo: Mapped[str] = mapped_column(String(20), default="auto")  # auto | manual
    # Valores usados apenas no modo manual; no modo auto o motor calcula os máximos.
    valores_manuais: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(default=agora, onupdate=agora)
