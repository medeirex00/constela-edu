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
                # O contexto da escola (~milhares de tokens) repete a cada
                # pergunta da conversa: o cache reduz custo/latência.
                cache_control={"type": "ephemeral"},
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

        # "Os 3 melhores do Matific", "top 5 no Elefante", "melhor aluno da
        # escola": monta o pódio certo, na métrica certa, com o N pedido.
        podio = self._top_n(pergunta, secoes.get("ALUNOS", ""))
        if podio:
            return podio

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

    # Linha da seção ALUNOS, montada em assistente.montar_contexto:
    #   "- NOME: turma T — Leitura (Elefante Letrado) 72.0 (3º lugar em Leitura);
    #    Matemática (Matific): não aferido"
    # Uma nota POR DISCIPLINA, só das contratadas; quem não é aferido numa
    # disciplina não tem número nela (é texto, nunca 0). A turma termina no
    # " — " (não na primeira vírgula) para nomes de turma com vírgula ("4º Ano,
    # Integral") não saírem truncados.
    _RE_ALUNO = re.compile(r"^- (?P<nome>.+?): turma (?P<turma>.+?) — (?P<notas>.+)$")
    _RE_NOTA = re.compile(
        r"(?P<disciplina>Leitura|Matemática) \([^)]*\) (?P<nota>\d+(?:[.,]\d+)?)"
        r"(?: \((?P<posicao>\d+)º lugar)?")
    _DISCIPLINAS = {"Leitura": "leitura", "Matemática": "matematica"}
    _ROTULOS = {"leitura": "em Leitura (Elefante Letrado)",
                "matematica": "em Matemática (Matific)"}

    @classmethod
    def _top_n(cls, pergunta: str, secao_alunos: str) -> str | None:
        # Evolução/alertas têm seções próprias: "melhor evolução", "top 3 que
        # mais evoluíram" ou "alunos em risco" NÃO são pódio de nota — deixa a
        # pergunta seguir para EVOLUCAO/ALERTAS em vez de responder errado.
        if re.search(r"evolu|cresc|progresso|melhorou|melhoraram|melhorando|"
                     r"alerta|risco|atencao|preocup", pergunta):
            return None
        if not re.search(r"\b(top|melhor(es)?|primeir[oa]s?)\b", pergunta):
            return None
        if not re.search(r"\b(alun[oa]s?|matific|elefante|matematica|leitura|"
                         r"portugues|letrado|nota|escola|geral)\b", pergunta):
            return None

        if re.search(r"\b(matific|matematica)\b", pergunta):
            disciplinas = ["matematica"]
        elif re.search(r"\b(elefante|leitura|portugues|letrado)\b", pergunta):
            disciplinas = ["leitura"]
        else:
            # Sem disciplina na pergunta ("o melhor aluno da escola"): não existe
            # uma nota única que junte as duas (Arquitetura 2) — a resposta
            # honesta é o pódio de CADA disciplina, lado a lado.
            disciplinas = ["leitura", "matematica"]

        achado = re.search(r"\b(\d+)\b", pergunta)
        n = int(achado.group(1)) if achado else (
            1 if re.search(r"\bmelhor\b", pergunta) else 5)
        n = max(1, min(n, 25))

        notas: dict[str, list] = {d: [] for d in disciplinas}
        for linha in secao_alunos.splitlines():
            par = cls._RE_ALUNO.match(linha.strip())
            if not par:
                continue
            for nota in cls._RE_NOTA.finditer(par.group("notas")):
                disciplina = cls._DISCIPLINAS[nota.group("disciplina")]
                if disciplina not in notas:
                    continue
                posicao = int(nota.group("posicao")) if nota.group("posicao") else None
                notas[disciplina].append(
                    (float(nota.group("nota").replace(",", ".")), posicao,
                     par.group("nome"), par.group("turma")))

        blocos = []
        for disciplina in disciplinas:
            # Só quem TEM nota na disciplina entra (o não aferido não tem número
            # na linha); desempate pela posição carimbada pelo motor.
            alunos = sorted(notas[disciplina],
                            key=lambda a: (-a[0], a[1] is None, a[1] or 0))
            if not alunos:
                continue
            rotulo = cls._ROTULOS[disciplina]
            titulo = (f"O melhor aluno {rotulo}" if n == 1
                      else f"Os {min(n, len(alunos))} melhores alunos {rotulo}")
            blocos.append(f"{titulo}, pelos dados do sistema:\n" + "\n".join(
                f"{i}º: {nome} ({turma}) — nota {valor:.1f}"
                for i, (valor, _pos, nome, turma) in enumerate(alunos[:n], start=1)))
        if not blocos:
            return None
        aviso = ("Cada disciplina tem o seu próprio ranking — não existe uma nota "
                 "única que junte as duas.\n\n" if len(disciplinas) > 1 else "")
        return (aviso + "\n\n".join(blocos)
                + "\n\n(Resposta gerada no modo local, somente com dados do sistema.)")

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


def obter_provedor(provedor: str | None = None, api_key: str | None = None,
                   modelo: str | None = None) -> ProvedorIA:
    """Fábrica: escolhe o provedor pela configuração da ESCOLA (parâmetros,
    salvos pela interface) ou, sem eles, pelas variáveis de ambiente.

    Os valores do ambiente só entram quando NENHUM provedor foi passado: uma
    escola com provedor próprio nunca "herda" a chave/modelo do ambiente
    (misturaria credenciais — inclusive de fornecedores diferentes)."""
    if provedor is None:
        provedor = settings.AI_PROVIDER
        api_key = api_key or settings.AI_API_KEY
        modelo = modelo or settings.AI_MODEL or None
    provedor = provedor.strip().lower()
    if provedor == "anthropic":
        return AnthropicProvedor(api_key or "", modelo)
    if provedor == "openai":
        return OpenAIProvedor(api_key or "", modelo)
    return LocalProvedor()
