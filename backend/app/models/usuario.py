from datetime import datetime

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import agora


class Usuario(Base):
    __tablename__ = "usuarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    escola_id: Mapped[int | None] = mapped_column(ForeignKey("escolas.id"), index=True)
    nome: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    # Nome de usuário opcional (estilo @ do Instagram): único na rede toda,
    # sempre minúsculo — o login aceita e-mail OU nome de usuário.
    username: Mapped[str | None] = mapped_column(String(30), unique=True,
                                                 index=True, default=None)
    # Hash bcrypt irreversível — única forma de guardar a senha. Para dar
    # acesso a quem esqueceu a senha, use a redefinição por token (não há
    # cópia recuperável da senha em lugar nenhum).
    senha_hash: Mapped[str] = mapped_column(String(200))
    # admin | coordenador | professor (sem "visitante": público vê só o painel)
    cargo: Mapped[str] = mapped_column(String(30), default="professor")
    # Administrador global: gerencia todas as escolas (PRD §136)
    is_global: Mapped[bool] = mapped_column(default=False)
    # Secretaria de Educação: usuário com rede_id enxerga (agregado) TODAS as
    # escolas dessa rede — sem ser global e sem ver PII de criança de escola
    # nenhuma. Nulo = usuário de escola única (ou global).
    rede_id: Mapped[int | None] = mapped_column(
        ForeignKey("redes.id", ondelete="SET NULL"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="ativo")
    ultimo_acesso: Mapped[datetime | None] = mapped_column(default=None)
    # Última "batida" de presença (heartbeat do app aberto): alimenta o Monitor
    # de Sessões Ativas — "online" = visto_em recente. Diferente de ultimo_acesso
    # (que é o último ENTRAR); nulo até o primeiro heartbeat.
    visto_em: Mapped[datetime | None] = mapped_column(default=None)
    # Incrementado ao redefinir a senha: invalida tokens emitidos antes
    # (o token carrega a versão vigente na emissão). Sem estado de blacklist.
    token_version: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=agora)
