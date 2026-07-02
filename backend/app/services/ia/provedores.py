"""Implementações dos provedores de IA (PRD §154).

* AnthropicProvedor — SDK oficial `anthropic` (Messages API).
* OpenAIProvedor   — HTTP direto via httpx (sem SDK adicional).
* LocalProvedor    — determinístico, responde lendo o contexto montado pelo
  backend; sem rede, sem chave. É o padrão e o plano B dos outros dois.
"""
from __future__ import annotations

import re
import unicodedata

from app.core.config import settings
from app.services.ia.base import ErroProvedorIA, ProvedorIA

MODELO_ANTHROPIC_PADRAO = "claude-opus-4-8"
MODELO_OPENAI_PADRAO = "gpt-4o"


class AnthropicProvedor(ProvedorIA):
    nome = "anthropic"

    def __init__(self, api_key: str, modelo: str | None = None):
        if not api_key:
            raise ErroProvedorIA("AI_API_KEY não configurada para o provedor Anthropic.")
        self._api_key = api_key
        self._modelo = modelo or MODELO_ANTHROPIC_PADRAO

    def responder(self, sistema: str, mensagens: list[dict]) -> str:
        import anthropic

        cliente = anthropic.Anthropic(api_key=self._api_key)
        try:
            resposta = cliente.messages.create(
                model=self._modelo,
                max_tokens=settings.AI_MAX_TOKENS,
                system=sistema,
                messages=[
                    {
                        "role": "user" if m["papel"] == "usuario" else "assistant",
                        "content": m["conteudo"],
                    }
                    for m in mensagens
                ],
            )
        except anthropic.APIError as erro:
            raise ErroProvedorIA(f"Falha no provedor Anthropic: {erro}") from erro
        if resposta.stop_reason == "refusal":
            return "Não posso responder a essa pergunta."
        return "".join(
            bloco.text for bloco in resposta.content if bloco.type == "text"
        ).strip()


class OpenAIProvedor(ProvedorIA):
    nome = "openai"

    def __init__(self, api_key: str, modelo: str | None = None):
        if not api_key:
            raise ErroProvedorIA("AI_API_KEY não configurada para o provedor OpenAI.")
        self._api_key = api_key
        self._modelo = modelo or MODELO_OPENAI_PADRAO

    def responder(self, sistema: str, mensagens: list[dict]) -> str:
        import httpx

        corpo = {
            "model": self._modelo,
            "max_tokens": settings.AI_MAX_TOKENS,
            "messages": [{"role": "system", "content": sistema}] + [
                {
                    "role": "user" if m["papel"] == "usuario" else "assistant",
                    "content": m["conteudo"],
                }
                for m in mensagens
            ],
        }
        try:
            resposta = httpx.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=corpo,
                timeout=60.0,
            )
            resposta.raise_for_status()
            dados = resposta.json()
            return dados["choices"][0]["message"]["content"].strip()
        except httpx.HTTPError as erro:
            raise ErroProvedorIA(f"Falha no provedor OpenAI: {erro}") from erro
        except (KeyError, IndexError) as erro:
            raise ErroProvedorIA("Resposta inesperada do provedor OpenAI.") from erro


def _plano(texto: str) -> str:
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )
    return sem_acento.casefold()


class LocalProvedor(ProvedorIA):
    """Assistente por regras: extrai a seção certa do contexto (que o backend
    montou a partir do banco) conforme as palavras da pergunta.

    Não é um modelo de linguagem — é o modo offline/sem-chave. As respostas
    citam apenas dados reais do contexto, portanto nunca "alucinam".
    """

    nome = "local"

    _SECOES = [
        (("alerta", "atencao", "preocup", "risco"), "ALERTAS"),
        (("evolu", "cresc", "melhor", "progresso"), "EVOLUCAO"),
        (("engaj", "indice", "persist"), "INDICES"),
        (("ranking", "posicao", "primeiro", "top", "melhores", "nota"), "RANKING"),
        (("turma", "serie", "sala"), "TURMAS"),
        (("resumo", "geral", "escola", "panorama", "visao"), "RESUMO"),
    ]

    def responder(self, sistema: str, mensagens: list[dict]) -> str:
        pergunta = _plano(mensagens[-1]["conteudo"]) if mensagens else ""
        secoes = self._extrair_secoes(sistema)

        # Pergunta sobre um aluno específico? Procura o nome no contexto.
        aluno = self._aluno_citado(pergunta, secoes.get("ALUNOS", ""))
        if aluno:
            return (f"Sobre {aluno['nome']} (dados do sistema):\n{aluno['linha']}\n\n"
                    "Posso detalhar evolução, alertas ou conquistas se você perguntar.")

        for palavras, chave in self._SECOES:
            if any(p in pergunta for p in palavras) and secoes.get(chave):
                return (f"{secoes[chave].strip()}\n\n"
                        "(Resposta gerada no modo local, somente com dados do sistema.)")

        resumo = secoes.get("RESUMO", "").strip()
        return (
            "Posso responder sobre rankings, evolução, índices pedagógicos, "
            "alertas e turmas desta escola — usando somente os dados do sistema.\n\n"
            + (resumo and f"Panorama atual:\n{resumo}\n\n" or "")
            + "Exemplos: “quem mais evoluiu este mês?”, “quais alunos precisam "
              "de atenção?”, “como está a turma 4º Ano A?”"
        ).strip()

    @staticmethod
    def _extrair_secoes(sistema: str) -> dict[str, str]:
        secoes: dict[str, str] = {}
        atual = None
        for linha in sistema.splitlines():
            marcador = re.fullmatch(r"### (\w+)", linha.strip())
            if marcador:
                atual = marcador.group(1)
                secoes[atual] = ""
            elif atual:
                secoes[atual] += linha + "\n"
        return secoes

    @staticmethod
    def _aluno_citado(pergunta: str, secao_alunos: str) -> dict | None:
        for linha in secao_alunos.splitlines():
            linha = linha.strip()
            if not linha.startswith("- "):
                continue
            nome = linha[2:].split(":", 1)[0].strip()
            if nome and _plano(nome) in pergunta:
                return {"nome": nome, "linha": linha}
        return None


def obter_provedor() -> ProvedorIA:
    """Fábrica: escolhe o provedor pela configuração (PRD §154)."""
    provedor = settings.AI_PROVIDER.strip().lower()
    modelo = settings.AI_MODEL or None
    if provedor == "anthropic":
        return AnthropicProvedor(settings.AI_API_KEY, modelo)
    if provedor == "openai":
        return OpenAIProvedor(settings.AI_API_KEY, modelo)
    return LocalProvedor()
