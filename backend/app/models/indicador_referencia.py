"""Indicadores oficiais de REFERÊNCIA (município, UF e Brasil) e a proveniência deles.

Tabela ADITIVA, separada de ``resultados_avaliacao`` (que é só de escola): aqui
entram os números públicos que o INEP/SEDUC divulgam por território — o
Indicador Criança Alfabetizada (ICA) da rede municipal, de SP e do Brasil, as
metas oficiais, o nível e a participação. Mais tarde, os dados auxiliares por
escola (metas, participação, TPS, IEE...) pela mesma chave.

Sem ``rede_id`` e sem ``escola_id`` DE PROPÓSITO: são dados públicos de
referência, não pertencem a uma rede. A visibilidade é decidida na leitura
(``codigo_territorio = rede.codigo_ibge``; nas linhas de escola, pelo INEP das
escolas que o usuário enxerga). Por isso nada aqui some em cascata quando uma
escola é apagada, e o ``DELETE /avaliacoes/resultados`` não toca nesta tabela.

A chave natural é uma restrição única COMUM (sem ``COALESCE``, sem índice de
expressão): todas as colunas dela são NOT NULL — a dimensão que a fonte não tem
vira ``''``/``'total'`` —, então ela funciona igual no SQLite e no PostgreSQL.

AUSÊNCIA ≠ ZERO: sem resultado, ``valor`` fica nulo e ``motivo_ausencia`` diz por
quê (CHECK: um dos dois sempre existe). Nunca se imputa número.
"""
from datetime import datetime

from sqlalchemy import (CheckConstraint, Float, ForeignKey, Index, Integer, JSON,
                        SmallInteger, String, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import agora


class ImportacaoIndicador(Base):
    """Uma importação de arquivo oficial de indicador: proveniência + desfazer.

    A PRÉVIA fica registrada (``status='previa'``) com o sha256 do arquivo, sem
    gravar nenhum número. Aplicar exige reenviar o MESMO arquivo (mesmo sha256) —
    o servidor não guarda arquivos. ``resumo`` guarda os avisos e o que a importação
    viu no arquivo (pequeno: é lido em toda consulta); ``desfazer``, na aplicação, o
    estado ANTERIOR de cada linha tocada e todas as chaves do plano — é o que permite
    desfazer exatamente.
    """

    __tablename__ = "importacoes_indicador"
    __table_args__ = (
        Index("ix_importacoes_indicador_avaliacao_status", "avaliacao_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    avaliacao_id: Mapped[int] = mapped_column(
        ForeignKey("avaliacoes_externas.id", ondelete="CASCADE"))
    # Parser que leu o arquivo (chave estável) e a versão dele.
    parser: Mapped[str] = mapped_column(String(40))
    parser_versao: Mapped[str] = mapped_column(String(20))
    fonte_nome: Mapped[str] = mapped_column(String(120))
    url_origem: Mapped[str | None] = mapped_column(String(500), default=None)
    arquivo_nome: Mapped[str] = mapped_column(String(255))
    arquivo_sha256: Mapped[str] = mapped_column(String(64))
    arquivo_bytes: Mapped[int] = mapped_column(Integer)
    # Cabeçalho HTTP Last-Modified, quando quem importa o informa (texto cru).
    last_modified_origem: Mapped[str | None] = mapped_column(String(64), default=None)
    # Data de modificação gravada DENTRO do XLSX (docProps/core.xml) — nos arquivos
    # do ICA, o mesmo dia do Last-Modified do servidor do INEP (horas antes). Serve
    # de "arquivo de <data>" no selo e de desempate entre versões da mesma edição.
    # Arquivo sem essa data → nula (nunca a hora da leitura): não vence versão datada.
    arquivo_data: Mapped[datetime | None] = mapped_column(default=None)
    # Ano da avaliação que o arquivo divulga (coluna ANO): posição na série.
    edicao_arquivo: Mapped[int] = mapped_column(Integer)
    versao_rotulo: Mapped[str | None] = mapped_column(String(60), default=None)
    # Território usado para recortar o arquivo (IBGE do município da rede, UF).
    codigo_territorio_alvo: Mapped[str] = mapped_column(String(7))
    citacao: Mapped[str | None] = mapped_column(String(500), default=None)
    licenca: Mapped[str | None] = mapped_column(String(200), default=None)
    modo: Mapped[str] = mapped_column(String(20), default="upload")    # upload | pacote_cli | vigia
    status: Mapped[str] = mapped_column(String(20), default="previa")  # previa | aplicada | desfeita
    contadores: Mapped[dict] = mapped_column(JSON, default=dict)
    resumo: Mapped[dict] = mapped_column(JSON, default=dict)
    # O PLANO DE DESFAZER da aplicação (``criadas``, ``alteradas`` com o ANTES, e
    # ``chaves`` = todas as que o plano viu). Fora do ``resumo`` e ``deferred``: tem
    # uma entrada por número (MB no Ideb por escola) e só o desfazer e a lista de
    # importações o leem; as consultas (Ideb, SARESP, escola) carregam a importação
    # sem esta coluna. Nulo na prévia.
    desfazer: Mapped[dict | None] = mapped_column(JSON, default=None, deferred=True)
    pacote_sha256: Mapped[str | None] = mapped_column(String(64), default=None)
    usuario_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"), default=None)
    coletado_em: Mapped[datetime | None] = mapped_column(default=None)
    aplicado_em: Mapped[datetime | None] = mapped_column(default=None)
    desfeito_em: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=agora)


class IndicadorReferencia(Base):
    """Um número oficial de referência (ou a AUSÊNCIA dele, com o motivo).

    ``valor`` é o número de CAPA: o do arquivo oficial mais recente da série.
    ``valor_detalhado`` são as casas decimais de OUTRO arquivo, só quando o
    arredondamento bate com a capa (``detalhe_importacao_id`` diz de onde vieram).
    """

    __tablename__ = "indicadores_referencia"
    __table_args__ = (
        UniqueConstraint(
            "avaliacao_id", "edicao", "indicador", "abrangencia", "codigo_territorio",
            "codigo_inep", "rede_ensino", "localizacao", "etapa", "componente", "nivel",
            name="uq_indicador_referencia_natural"),
        CheckConstraint("valor IS NOT NULL OR motivo_ausencia IS NOT NULL",
                        name="ck_indicador_valor_ou_motivo"),
        # Leitura típica: os números de um território (município, UF, Brasil).
        Index("ix_indicadores_referencia_territorio",
              "codigo_territorio", "avaliacao_id", "indicador"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    avaliacao_id: Mapped[int] = mapped_column(
        ForeignKey("avaliacoes_externas.id", ondelete="CASCADE"))
    edicao: Mapped[int] = mapped_column(Integer)          # ano do resultado ou da meta
    # percentual_alfabetizado | meta | nivel_municipio | participacao | ...
    indicador: Mapped[str] = mapped_column(String(40))
    abrangencia: Mapped[str] = mapped_column(String(10))  # escola | municipio | uf | brasil
    # IBGE do município (7 dígitos), código da UF ("35") ou "BR".
    codigo_territorio: Mapped[str] = mapped_column(String(7))
    codigo_inep: Mapped[str] = mapped_column(String(8), default="", server_default="")
    # municipal | estadual | publica | total — normalizado do arquivo.
    rede_ensino: Mapped[str] = mapped_column(String(20))
    localizacao: Mapped[str] = mapped_column(String(10), default="total",
                                             server_default="total")
    etapa: Mapped[str] = mapped_column(String(20), default="", server_default="")
    componente: Mapped[str] = mapped_column(String(20), default="", server_default="")
    nivel: Mapped[str] = mapped_column(String(10), default="", server_default="")
    valor: Mapped[float | None] = mapped_column(Float, default=None)
    valor_detalhado: Mapped[float | None] = mapped_column(Float, default=None)
    detalhe_importacao_id: Mapped[int | None] = mapped_column(
        ForeignKey("importacoes_indicador.id", ondelete="SET NULL"), default=None)
    # ">" / ">=" quando a meta é "acima de"/"ou mais" (o texto vem do arquivo).
    operador: Mapped[str | None] = mapped_column(String(2), default=None)
    # Precisão PUBLICADA (da coluna no arquivo de origem), da capa e do detalhe: o
    # float perde o zero final (27,90 → 27.9), a precisão fica guardada aqui.
    casas_decimais: Mapped[int | None] = mapped_column(SmallInteger, default=None)
    casas_decimais_detalhe: Mapped[int | None] = mapped_column(SmallInteger, default=None)
    # percentual | nivel | escala_saeb | escala_alfabetizacao | escala_saresp | indice
    unidade: Mapped[str] = mapped_column(String(20))
    desenho: Mapped[str | None] = mapped_column(String(12), default=None)  # censitario | amostral
    # nao_divulgado | participacao_baixa | sem_meta | sem_etapa — só com evidência na fonte.
    motivo_ausencia: Mapped[str | None] = mapped_column(String(40), default=None)
    importacao_id: Mapped[int | None] = mapped_column(
        ForeignKey("importacoes_indicador.id", ondelete="SET NULL"), default=None)
    created_at: Mapped[datetime] = mapped_column(default=agora)
    updated_at: Mapped[datetime] = mapped_column(default=agora, onupdate=agora)
