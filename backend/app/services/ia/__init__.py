"""Camada AI Service isolada (PRD §154).

O frontend NUNCA fala com o modelo: toda chamada passa por aqui, com o
contexto montado no backend a partir do banco. O provedor é trocável por
configuração (AI_PROVIDER=local|anthropic|openai) sem tocar no resto do
código — e o provedor "local" responde por regras determinísticas, o que
mantém o assistente funcional sem chave de API e serve de contingência.
"""
from app.services.ia.base import ErroProvedorIA, ProvedorIA
from app.services.ia.provedores import obter_provedor

__all__ = ["ErroProvedorIA", "ProvedorIA", "obter_provedor"]
