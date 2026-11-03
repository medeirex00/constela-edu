"""Identidade do aluno no Quest: perfil (o astronauta), credencial de login
infantil e vínculo de responsáveis (docs/quest/02, grupo 1)."""
from datetime import date, datetime

from sqlalchemy import JSON, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import agora


class QuestPerfil(Base):
    """O astronauta — estado de jogo do aluno.

    `nivel`, `moedas` e `estrelas_total` são caches recalculáveis (a verdade
    vive no ledger e nas tentativas), mantidos por serem lidos em toda tela.
    """

    __tablename__ = "quest_perfis"

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    aluno_id: Mapped[int] = mapped_column(
        ForeignKey("alunos.id", ondelete="CASCADE"), unique=True)
    # Como a criança pediu para ser chamada (cerimônia da primeira vez);
    # vazio = usa o primeiro nome do cadastro
    nome_exibicao: Mapped[str | None] = mapped_column(String(40), default=None)
    # Nome de exibição fora da própria turma (LGPD: nome real só entre colegas)
    apelido: Mapped[str] = mapped_column(String(60))
    codigo_amigo: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    nivel: Mapped[int] = mapped_column(default=1)
    xp_total: Mapped[int] = mapped_column(default=0)
    moedas: Mapped[int] = mapped_column(default=0)
    estrelas_total: Mapped[int] = mapped_column(default=0)
    # "Chama do Cosmo": dias seguidos com atividade; o escudo perdoa 1 falta
    # por semana (renovado às segundas) — criança não controla a própria agenda
    sequencia_dias: Mapped[int] = mapped_column(default=0)
    escudo_sequencia: Mapped[bool] = mapped_column(default=True)
    ultimo_dia_ativo: Mapped[date | None] = mapped_column(default=None)
    # Itens equipados: {cor, roupa, chapeu, acessorio, pet, efeito, moldura}
    avatar: Mapped[dict] = mapped_column(JSON, default=dict)
    # {som, musica, narracao, reduzir_animacoes, ...}
    preferencias: Mapped[dict] = mapped_column(JSON, default=dict)
    # Nível adaptativo por mundo (1–5), invisível para a criança
    dificuldade: Mapped[dict] = mapped_column(JSON, default=dict)
    # Recursos sociais: desligado por padrão; escola/responsável habilita
    social_ativo: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(20), default="ativo")
    created_at: Mapped[datetime] = mapped_column(default=agora)


class QuestCredencialAluno(Base):
    """Login infantil — separado do estado de jogo.

    Decisão de produto: SEM senha/PIN, como no Elefante Letrado — o código
    impresso no cartão É a credencial e pode ficar exposto. A defesa contra
    abuso é o limitador de tentativas PERSISTENTE (quest_limites_acesso, por
    código, por código+IP e por IP) e o escopo mínimo do papel "aluno" (só o
    próprio jogo).

    Credenciais em repouso (0037): o login procura pelo ``codigo_login_hash``
    (HMAC-SHA256 com chave do servidor, que não fica no banco) e o QR pelo
    ``qr_token_hash`` (SHA-256 do token). As colunas ``codigo_login`` e
    ``qr_token`` em texto claro CONTINUAM até o dono confirmar a troca — o cartão
    impresso e a página do professor ainda mostram o código e a URL do QR a partir
    delas; enquanto existirem, um dump ainda dá acesso. Passo de remoção:
    docs/lgpd/RETENCAO-TECNICA.md (seção do Quest) — vale para as DUAS.
    """

    __tablename__ = "quest_credenciais_aluno"

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    aluno_id: Mapped[int] = mapped_column(
        ForeignKey("alunos.id", ondelete="CASCADE"), unique=True)
    # Curto, falável e só letras+números ("SOL1234") — único na rede toda.
    # TRANSIÇÃO: só para EXIBIR (cartão/professor) e para o fallback de linhas
    # sem hash; a autenticação vai pelo hash abaixo.
    codigo_login: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    # HMAC do código normalizado (64 hex). Nulo só em linha gravada por código
    # anterior à 0037 (restauração de backup antigo, réplica velha no deploy):
    # o primeiro login dela preenche. DESATUALIZADO quando o processo antigo
    # gira o código só no texto: enquanto o texto existir, o login confere os
    # dois e o cartão girado não entra (credenciais.buscar_por_codigo).
    codigo_login_hash: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True, default=None)
    # Login por QR nos tablets; trocável (regenerar cartão mata o antigo).
    # TRANSIÇÃO, como o codigo_login: só para montar a URL do QR (url_qr) e para o
    # fallback de linhas sem hash; a autenticação vai pelo hash abaixo.
    qr_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # SHA-256 do token (64 hex). Nulo só em linha gravada por código anterior à
    # 0037 (backup antigo, processo antigo no deploy): o primeiro login preenche.
    qr_token_hash: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True, default=None)
    # Incrementado ao regenerar o cartão: derruba sessões antigas (como no Edu)
    token_version: Mapped[int] = mapped_column(default=0)
    ultimo_acesso: Mapped[datetime | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=agora)

    aluno = relationship("Aluno")


class ResponsavelAluno(Base):
    """Vínculo responsável (usuarios, cargo=responsavel) ↔ aluno.

    O vínculo só nasce autorizado por alguém da escola — responsável nunca
    se auto-vincula a uma criança.
    """

    __tablename__ = "responsaveis_alunos"
    __table_args__ = (
        UniqueConstraint("usuario_id", "aluno_id", name="uq_responsavel_aluno"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int] = mapped_column(ForeignKey("escolas.id"), index=True)
    usuario_id: Mapped[int] = mapped_column(
        ForeignKey("usuarios.id", ondelete="CASCADE"), index=True)
    aluno_id: Mapped[int] = mapped_column(
        ForeignKey("alunos.id", ondelete="CASCADE"), index=True)
    parentesco: Mapped[str | None] = mapped_column(String(40))
    autorizado_por: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(default=agora)
