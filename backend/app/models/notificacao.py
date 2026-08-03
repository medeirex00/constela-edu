from datetime import datetime

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import agora


class Notificacao(Base):
    """Aviso ACIONÁVEL por perfil (Fase 2). Molde do SincronizacaoAlerta, porém
    genérico e roteado por ESCOPO (escola|rede|global): quem vê é decidido no
    servidor pelo escopo + escola_id/rede_id + o portão de PII.

    - ``rota``: deep-link para a tela onde se AGE sobre o aviso (ex.: /importacoes).
    - ``aluno_id``: só preenchido quando o aviso toca UMA criança — é o portão de
      PII. A Secretaria NUNCA recebe avisos com aluno_id nem de escopo 'escola';
      só recebe escopo 'rede' (agregado). O professor só recebe avisos cujo
      aluno_id está nas turmas dele.
    - Estado de leitura é POR USUÁRIO, em ``Usuario.notificacoes_lidas_ate_id``
      (guarda o maior id já visto) — barato e consistente entre dispositivos.
    """

    __tablename__ = "notificacoes"
    __table_args__ = (
        Index("ix_notificacoes_escopo_escola", "escopo", "escola_id"),
        Index("ix_notificacoes_escopo_rede", "escopo", "rede_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    escopo: Mapped[str] = mapped_column(String(10), index=True)  # escola|rede|global
    escola_id: Mapped[int | None] = mapped_column(
        ForeignKey("escolas.id", ondelete="CASCADE"), default=None, index=True)
    rede_id: Mapped[int | None] = mapped_column(
        ForeignKey("redes.id", ondelete="CASCADE"), default=None, index=True)
    tipo: Mapped[str] = mapped_column(String(40), index=True)
    severidade: Mapped[str] = mapped_column(String(8), default="info")  # info|aviso|critico
    titulo: Mapped[str] = mapped_column(String(200))
    rota: Mapped[str | None] = mapped_column(String(200), default=None)
    entidade: Mapped[str | None] = mapped_column(String(40), default=None)
    entidade_id: Mapped[int | None] = mapped_column(default=None)
    # Portão de PII: quando setado, o aviso toca uma criança específica.
    aluno_id: Mapped[int | None] = mapped_column(default=None)
    autor_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuarios.id", ondelete="SET NULL"), default=None)
    created_at: Mapped[datetime] = mapped_column(default=agora, index=True)
