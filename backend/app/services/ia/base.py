"""Contrato comum de todos os provedores de IA (PRD §154)."""
from __future__ import annotations

from abc import ABC, abstractmethod


class ErroProvedorIA(RuntimeError):
    """Falha ao consultar o provedor (rede, chave inválida, limite etc.)."""


class ProvedorIA(ABC):
    nome: str = "base"

    @abstractmethod
    def responder(self, sistema: str, mensagens: list[dict]) -> str:
        """Gera a resposta do assistente.

        `mensagens` é a conversa no formato [{"papel": "usuario"|"assistente",
        "conteudo": str}, ...], sempre terminando com a pergunta do usuário.
        Implementações devem levantar ErroProvedorIA em qualquer falha.
        """
