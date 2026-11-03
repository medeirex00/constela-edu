"""Limite de tentativas PERSISTENTE (0037): do login infantil do Quest e dos tetos de
falhas do login do Edu.

Nasceu para o login por código do Quest; desde 31/10/2026 guarda também os tetos de
falhas POR IP e GLOBAL do /auth/login do Edu, nas dimensões ``edu_login_ip_falha`` e
``edu_login_global_falha`` (routers/auth.py; teto e janela pelas variáveis
EDU_LOGIN_TETO_*), que nunca se misturam com as do Quest. Os limites do Edu por
conta e por (conta, IP) seguem só em memória.

O limitador em memória (app.core.rate_limit) zera a cada reinício e não é
compartilhado entre workers/réplicas: com N processos o orçamento por chave vira
N vezes o teto, e um deploy devolve o orçamento inteiro a quem estava sendo
barrado. Como o código do Quest É a credencial (sem senha) e o espaço do formato
atual é pequeno (~1,3×10^5), o teto precisa valer no banco.

Uma linha por (dimensão, valor): ``chave`` = ``"<dimensão>:<HMAC do valor>"`` —
nem o IP nem o código digitado ficam em texto no banco (LGPD/minimização; o
código errado de uma criança é quase sempre o código CERTO de outra). Contador
de janela fixa + ``bloqueado_ate`` (bloqueio temporário). As linhas vencidas são
apagadas pelo próprio limitador (faxina técnica, não é política de retenção).
"""
from datetime import datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class QuestLimiteAcesso(Base):
    __tablename__ = "quest_limites_acesso"

    id: Mapped[int] = mapped_column(primary_key=True)
    chave: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    falhas: Mapped[int] = mapped_column(default=0)
    # Início da janela corrente (UTC sem fuso, como o resto do schema).
    janela_inicio: Mapped[datetime]
    # Enquanto no futuro, a chave está bloqueada (429), mesmo depois de reiniciar.
    bloqueado_ate: Mapped[datetime | None] = mapped_column(default=None)
    atualizado_em: Mapped[datetime] = mapped_column(index=True)
