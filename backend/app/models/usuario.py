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
    # Escopo de REDE (Secretaria): quando setado, o usuário enxerga TODAS as
    # escolas desta rede (não só a própria) sem ser is_global. É o eixo de
    # ALCANCE, ortogonal ao `cargo` (que governa as AÇÕES). Ver services/permissoes.
    rede_id: Mapped[int | None] = mapped_column(
        ForeignKey("redes.id", ondelete="SET NULL"), index=True, default=None)
    # Vínculo FORTE professor↔cadastro (substitui o casamento frágil por e-mail).
    # Quando setado, define as turmas que o professor enxerga por FK, não por
    # string de e-mail. Nullable: contas de gestão não são professores.
    professor_id: Mapped[int | None] = mapped_column(
        ForeignKey("professores.id", ondelete="SET NULL"), index=True, default=None)
    status: Mapped[str] = mapped_column(String(20), default="ativo")
    ultimo_acesso: Mapped[datetime | None] = mapped_column(default=None)
    # Incrementado ao redefinir a senha: invalida tokens emitidos antes
    # (o token carrega a versão vigente na emissão). Sem estado de blacklist.
    token_version: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=agora)
