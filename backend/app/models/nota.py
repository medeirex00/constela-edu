from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.academico import Aluno
from app.models.base import agora


class Nota(Base):
    """Resultado calculado por aluno/ano letivo — cache do motor de cálculo.

    `detalhes` guarda o passo a passo completo do cálculo, permitindo a
    auditoria exigida no PRD §45 ("Como esta nota foi calculada").
    Recalculada integralmente a cada importação ou mudança de configuração
    (PRD §43); nunca editada manualmente.

    DESEMPENHO POR DIMENSÃO (Arquitetura 2, `docs/spec-arquitetura-2.md` §1.3):
    cada dimensão contratada tem, além da nota, o seu próprio par
    ``aferido_*`` / ``posicao_*``:

      * ``aferido_d`` — existe snapshot ATUAL da plataforma daquela dimensão
        para este aluno. É o discriminante entre "sem snapshot" (ausência: fora
        da ordenação, `—` na tela) e "snapshot zerado" (zero LEGÍTIMO: entra em
        último). NUNCA é `nota > 0` (spec §12.4).
      * ``posicao_d`` — posição CARIMBADA dentro da dimensão, contada apenas
        entre os aferidos dela. Carimbada (e não derivada na leitura) porque
        posição vai para certificado, cartaz, telão e app offline: posição que
        muda sozinha quando outro aluno é importado é fonte garantida de "o
        sistema mudou a nota do meu filho" (spec, Aprovação 1, opção 1A).

    ``nota_geral`` e ``posicao`` (global) são LEGADO: deixaram de ser a fonte
    oficial de ordenação, continuam sendo gravadas apenas enquanto os
    consumidores ainda não migrados (vitrines, web, mobile) não forem
    convertidos. Nada novo deve passar a lê-las.
    """

    __tablename__ = "notas"
    __table_args__ = (
        UniqueConstraint("aluno_id", "ano_letivo", name="uq_nota_aluno_ano"),
        # Caminho de leitura MAIS quente do sistema: ranking, top10 do
        # dashboard, painel público, média e exportação filtram sempre por
        # (escola_id, ano_letivo) e ordenam por posicao. O índice de coluna
        # única ix_notas_escola_id não distingue ano nem evita a ordenação;
        # este composto cobre o WHERE e o ORDER BY de uma vez.
        Index("ix_notas_escola_ano_posicao", "escola_id", "ano_letivo", "posicao"),
        # Um índice por DIMENSÃO, pelo mesmo motivo: o ranking de Leitura e o de
        # Matemática filtram por (escola_id, ano_letivo) e ordenam pela posição
        # DAQUELA dimensão. Sem eles o índice acima não serve (ordena por outra
        # coluna) e cada ranking vira varredura + sort.
        Index("ix_notas_escola_ano_pos_leitura", "escola_id", "ano_letivo",
              "posicao_leitura"),
        Index("ix_notas_escola_ano_pos_matematica", "escola_id", "ano_letivo",
              "posicao_matematica"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    aluno_id: Mapped[int] = mapped_column(
        ForeignKey("alunos.id", ondelete="CASCADE"), index=True)
    ano_letivo: Mapped[int] = mapped_column(index=True)
    # Notas LOCAIS: calculadas com a configuração da ESCOLA (pesos/dificuldade/
    # normalização que o coordenador pode personalizar). Servem SÓ o contexto
    # INTERNO da escola (ranking/competição interna). NUNCA devem ser lidas para
    # comparar escolas — para isso existem as colunas `*_institucional` abaixo.
    nota_matific: Mapped[float] = mapped_column(default=0.0)
    nota_elefante: Mapped[float] = mapped_column(default=0.0)
    # -----------------------------------------------------------------------
    # INSTITUCIONAL — a RÉGUA OFICIAL DA REDE (não editável pelo coordenador)
    # -----------------------------------------------------------------------
    # Calculadas SEMPRE com o perfil institucional fixo do Constela (dificuldade
    # A3 `exp(0,103·pos)` + pesos padrão + normalização linear P90), ignorando
    # qualquer configuração local. São as ÚNICAS notas que o ranking/dashboard/
    # KPI/relatório DA REDE pode consumir. Como não dependem de nenhuma escolha
    # do coordenador, alterar a config de uma escola não move a posição dela (nem
    # de nenhuma outra) no ranking da rede. Travado por
    # `backend/tests/test_scoring_institucional.py`.
    nota_elefante_institucional: Mapped[float] = mapped_column(default=0.0)
    nota_matific_institucional: Mapped[float] = mapped_column(default=0.0)
    # -----------------------------------------------------------------------
    # LEGADO / COMPATIBILIDADE — LEIA ANTES DE USAR
    # -----------------------------------------------------------------------
    # `nota_geral` (a composição entre dimensões) e `posicao` (a ordem única
    # derivada dela) NÃO são fonte oficial de ranking, de premiação nem de
    # nenhuma decisão de negócio. Continuam sendo GRAVADAS apenas enquanto os
    # consumidores ainda não migrados (telão público, Ranking Geral do web,
    # app mobile, exportação/cartaz, simulador) leem o campo.
    #
    # A verdade oficial é o desempenho POR DIMENSÃO, logo abaixo: cada dimensão
    # tem a sua nota, o seu `aferido_*` e a sua `posicao_*`, medidos SÓ com dado
    # da própria plataforma. Para ordenar, premiar, emitir certificado ou
    # comparar alunos, use a dimensão — nunca estas duas colunas.
    #
    # A regra é travada por teste: `backend/tests/test_legado_nota_geral.py`
    # (inventário + varredura de ordenação + sabotagem). O caminho de saída
    # está em `docs/plano-retirada-nota-geral.md`.
    nota_geral: Mapped[float] = mapped_column(default=0.0)
    posicao: Mapped[int | None] = mapped_column(default=None)
    # Por dimensão — a ordenação OFICIAL a partir da Arquitetura 2.
    aferido_leitura: Mapped[bool] = mapped_column(default=False)
    aferido_matematica: Mapped[bool] = mapped_column(default=False)
    posicao_leitura: Mapped[int | None] = mapped_column(default=None)
    posicao_matematica: Mapped[int | None] = mapped_column(default=None)
    detalhes: Mapped[dict] = mapped_column(JSON, default=dict)
    calculada_em: Mapped[datetime] = mapped_column(default=agora)

    aluno: Mapped[Aluno] = relationship()


class LogAuditoria(Base):
    """Trilha de auditoria permanente (PRD §17). Logs nunca são apagados."""

    __tablename__ = "logs_auditoria"

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int | None] = mapped_column(ForeignKey("escolas.id"), index=True)
    usuario_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"))
    acao: Mapped[str] = mapped_column(String(80), index=True)
    entidade: Mapped[str | None] = mapped_column(String(80))
    entidade_id: Mapped[int | None] = mapped_column(default=None)
    detalhes: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=agora, index=True)
