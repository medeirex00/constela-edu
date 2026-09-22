from datetime import date, datetime

from sqlalchemy import JSON, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import agora


class Professor(Base):
    __tablename__ = "professores"

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    nome: Mapped[str] = mapped_column(String(200), index=True)
    email: Mapped[str | None] = mapped_column(String(200))
    observacoes: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(default=agora)


class Turma(Base):
    __tablename__ = "turmas"
    # Uma turma É identificada por (escola, ano letivo, nome): duas com a mesma
    # tripla são a MESMA sala. O índice único barra a duplicação sob importações
    # concorrentes (defesa cross-DB, além do advisory lock por escola no
    # Postgres). O import trata a colisão re-resolvendo para a existente.
    __table_args__ = (
        Index("uq_turma_escola_ano_nome", "escola_id", "ano_letivo", "nome",
              unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    nome: Mapped[str] = mapped_column(String(100))          # ex.: "4º Ano B"
    ano_escolar: Mapped[str] = mapped_column(String(30))     # série, ex.: "4º Ano"
    ano_letivo: Mapped[int] = mapped_column(index=True)
    professor_id: Mapped[int | None] = mapped_column(
        ForeignKey("professores.id", ondelete="SET NULL"))
    turno: Mapped[str | None] = mapped_column(String(20))    # manha|tarde|noite|integral
    # Código da sala na fonte externa (nº SED/Censo entre parênteses no relatório,
    # ex.: "4 ANO C INTEGRAL (300303525)" → "300303525"). Fica FORA do nome visível
    # e é a chave de dedup/idempotência mais forte no import: reimportar casa por
    # este código antes de qualquer heurística de nome.
    codigo_externo: Mapped[str | None] = mapped_column(String(40), index=True)
    capacidade_maxima: Mapped[int | None] = mapped_column(default=None)
    observacoes: Mapped[str | None] = mapped_column(String(2000))
    # "ativa" | "arquivada" — arquivar preserva o histórico sem poluir os filtros
    status: Mapped[str] = mapped_column(String(20), default="ativa", index=True)
    created_at: Mapped[datetime] = mapped_column(default=agora)

    professor: Mapped[Professor | None] = relationship()


class Aluno(Base):
    __tablename__ = "alunos"

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    nome: Mapped[str] = mapped_column(String(200), index=True)
    foto_url: Mapped[str | None] = mapped_column(String(500))
    data_nascimento: Mapped[date | None] = mapped_column(default=None)
    numero_chamada: Mapped[int | None] = mapped_column(default=None)
    # ativo | arquivado | excluido | fora_lista_piloto. Todas as consultas de
    # visão (rankings/relatórios/dashboards) filtram por "ativo", então qualquer
    # outro valor esconde o aluno SEM apagá-lo (reversível).
    status: Mapped[str] = mapped_column(String(20), default="ativo")
    # True quando o aluno veio (ou foi casado) por uma importação da Lista
    # Piloto. Só estes entram na reconciliação incremental: quem some de uma
    # nova lista vira "fora_lista_piloto"; alunos criados à mão ou por upload
    # (Matific/Elefante) NUNCA são afetados.
    da_lista_piloto: Mapped[bool] = mapped_column(default=False)
    observacoes: Mapped[str | None] = mapped_column(String(1000))
    # Ficha cadastral livre (JSON): dados da planilha de matrículas da escola
    # que não têm coluna própria — RA, RM, responsável, endereço, telefone,
    # RG, CPF, SUS, sexo, raça/cor, bolsa família, etc.
    ficha: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=agora)


class Matricula(Base):
    """Vínculo aluno ↔ turma por ano letivo.

    Preserva o histórico quando o aluno muda de série (PRD §14):
    nada é sobrescrito, cada ano letivo gera um novo registro.
    """

    __tablename__ = "matriculas"
    __table_args__ = (
        UniqueConstraint("aluno_id", "ano_letivo", name="uq_matricula_aluno_ano"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    aluno_id: Mapped[int] = mapped_column(
        ForeignKey("alunos.id", ondelete="CASCADE"), index=True)
    turma_id: Mapped[int] = mapped_column(ForeignKey("turmas.id"), index=True)
    ano_letivo: Mapped[int] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column(default=agora)

    aluno: Mapped[Aluno] = relationship()
    turma: Mapped[Turma] = relationship()


class IdentidadeExterna(Base):
    """Vínculo estável aluno ↔ id do aluno numa plataforma externa (UUID do
    Matific, id do Elefante). É a identificação CONFIÁVEL entre sincronizações:
    permite recasar o aluno mesmo se o nome mudar e, principalmente, detectar
    MUDANÇA DE TURMA com segurança (o UUID não muda quando o aluno troca de sala).
    Genérico por ``plataforma`` para o Elefante reusar a mesma arquitetura."""

    __tablename__ = "identidades_externas"
    __table_args__ = (
        # Um id externo aponta para UM aluno por escola/plataforma.
        UniqueConstraint("escola_id", "plataforma", "id_externo",
                         name="uq_identidade_externa"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    aluno_id: Mapped[int] = mapped_column(
        ForeignKey("alunos.id", ondelete="CASCADE"), index=True)
    plataforma: Mapped[str] = mapped_column(String(30))      # matific | elefante
    id_externo: Mapped[str] = mapped_column(String(80))       # UUID/id do aluno lá
    created_at: Mapped[datetime] = mapped_column(default=agora)


class RevisaoIdentidade(Base):
    """Linha de importação/sincronização cuja identidade NÃO pôde ser decidida com
    segurança (``identidade_aluno.decidir`` → REVISAR). Nada foi associado nem
    criado: a linha fica PRESERVADA aqui — nome recebido, identidade externa,
    turma informada, candidatos, motivo e os dados da linha — até um gestor
    escolher explicitamente o aluno (ou descartar). Resolver vincula a identidade
    externa ao aluno escolhido, aplica os dados e fica auditado; a próxima
    sincronização casa por essa identidade e não recria a duplicata.

    ``chave`` agrupa a MESMA pendência entre importações (identidade + tipo de
    dado + período): reimportar atualiza a pendência aberta em vez de empilhar.
    ``chave_identidade`` é a memória da decisão humana (quem é esta identidade)."""

    __tablename__ = "revisoes_identidade"
    __table_args__ = (
        Index("ix_revisoes_identidade_escola_status", "escola_id", "status"),
        Index("ix_revisoes_identidade_escola_chave", "escola_id", "chave"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    chave: Mapped[str] = mapped_column(String(400))
    chave_identidade: Mapped[str] = mapped_column(String(400))
    plataforma: Mapped[str] = mapped_column(String(30))        # matific | elefante
    formato: Mapped[str] = mapped_column(String(20), default="")
    id_externo: Mapped[str | None] = mapped_column(String(80))  # UUID/studentId
    nome_recebido: Mapped[str] = mapped_column(String(200))
    turma_informada: Mapped[str | None] = mapped_column(String(200))
    turma_id: Mapped[int | None] = mapped_column(
        ForeignKey("turmas.id", ondelete="SET NULL"))
    motivo: Mapped[str] = mapped_column(String(60))
    # [{aluno_id, nome, status, turma}] no momento da decisão
    candidatos: Mapped[list] = mapped_column(JSON, default=list)
    # dados das linhas (o que seria gravado) — leituras acumulam, resumo é retrato
    linhas: Mapped[list] = mapped_column(JSON, default=list)
    # formato/tipo/período/data de referência da importação de origem
    contexto: Mapped[dict] = mapped_column(JSON, default=dict)
    origem: Mapped[str] = mapped_column(String(20), default="importacao")
    importacao_id: Mapped[int | None] = mapped_column(
        ForeignKey("importacoes.id", ondelete="SET NULL"))
    ocorrencias: Mapped[int] = mapped_column(default=1)
    # pendente | resolvida | descartada
    status: Mapped[str] = mapped_column(String(20), default="pendente")
    aluno_escolhido_id: Mapped[int | None] = mapped_column(
        ForeignKey("alunos.id", ondelete="SET NULL"))
    resolvida_por_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"))
    resolvida_em: Mapped[datetime | None] = mapped_column(default=None)
    resolucao: Mapped[dict | None] = mapped_column(JSON, default=None)
    created_at: Mapped[datetime] = mapped_column(default=agora)
    atualizada_em: Mapped[datetime] = mapped_column(default=agora)
