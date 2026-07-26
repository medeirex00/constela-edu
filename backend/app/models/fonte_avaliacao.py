"""Fonte de COLETA AUTOMÁTICA de avaliação externa (o "robô coletor").

Guarda a receita para o software baixar sozinho o arquivo oficial (URL fixa do
INEP/SEDUC) e importá-lo — sem a Secretaria subir nada. A receita = URL + o
MAPEAMENTO de colunas (definido UMA vez, ao subir o arquivo real na tela, para
não chutar o formato). É GLOBAL (admin global configura; casa por código INEP e
serve todas as redes). Idempotente: recoletar re-importa (atualiza, não duplica).

O download em si é injetável/robusto — o INEP bloqueia acesso "cru", então o
sucesso depende do ambiente alcançar o servidor; a falha vira status (nunca
quebra em silêncio — o painel mostra ultimo_status/ultimo_erro).
"""
from datetime import datetime

from sqlalchemy import JSON, Boolean, ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import agora


class FonteAvaliacao(Base):
    __tablename__ = "fontes_avaliacao"

    id: Mapped[int] = mapped_column(primary_key=True)
    avaliacao_id: Mapped[int] = mapped_column(
        ForeignKey("avaliacoes_externas.id", ondelete="CASCADE"), index=True)
    nome: Mapped[str] = mapped_column(String(160))          # "IDEB Anos Iniciais 2023"
    url: Mapped[str] = mapped_column(String(500))           # arquivo oficial (XLSX/CSV/ZIP)
    edicao: Mapped[int] = mapped_column()                   # ano/edição
    indicador: Mapped[str] = mapped_column(String(60))
    unidade: Mapped[str] = mapped_column(String(30))
    # Mapeamento de colunas (a "receita"): linha_dados, col_inep, col_valor,
    # col_etapa/col_componente/col_turma, etapa_fixa, componente_fixo.
    mapeamento: Mapped[dict] = mapped_column(JSON, default=dict,
                                             server_default=text("'{}'"))
    cadencia: Mapped[str] = mapped_column(String(20), default="manual")  # manual | mensal
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)

    ultima_coleta: Mapped[datetime | None] = mapped_column(default=None)
    proxima_coleta: Mapped[datetime | None] = mapped_column(default=None, index=True)
    # ok | erro | nunca
    ultimo_status: Mapped[str] = mapped_column(String(12), default="nunca")
    ultimo_erro: Mapped[str | None] = mapped_column(String(300), default=None)
    ultimo_resumo: Mapped[dict] = mapped_column(JSON, default=dict,
                                                server_default=text("'{}'"))
    created_at: Mapped[datetime] = mapped_column(default=agora)
