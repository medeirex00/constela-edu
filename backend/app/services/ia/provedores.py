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
        # escola": devolve o pódio OFICIAL da disciplina, com o N pedido.
        podio = self._top_n(pergunta, secoes)
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

    # O pódio sai das seções de RANKING DA DISCIPLINA que
    # `assistente.montar_contexto` escreve — RANKING_ELEFANTE e RANKING_MATIFIC —,
    # que já são a lista OFICIAL (a mesma de `GET /ranking?dimensao=`): só os
    # aferidos na disciplina, só quem CONCORRE (1º ao 5º ano), na posição que o
    # motor carimbou. Linha:
    #   "- 3º: NOME (TURMA) — nota 72.0"
    # Por que não remontar o pódio a partir da seção ALUNOS: lá aparece TODO
    # aluno ativo com Nota, inclusive a criança de turma de Fase cuja Nota
    # antiga o recálculo não apaga — ela não concorre, e um pódio reordenado
    # dali divergia do ranking oficial (achado da revisão de 2026-10-12).
    # A turma vai até o ÚLTIMO ") — nota", para nomes de turma com parênteses
    # ("4º Ano A (Integral)") não saírem truncados.
    _RE_PODIO = re.compile(
        r"^- (?P<lugar>\d+)º: (?P<nome>.+?) \((?P<turma>.+)\) — nota "
        r"(?P<nota>\d+(?:[.,]\d+)?)$")
    _SECAO_DA_DISCIPLINA = {"leitura": "RANKING_ELEFANTE",
                            "matematica": "RANKING_MATIFIC"}
    _ROTULOS = {"leitura": "em Leitura (Elefante Letrado)",
                "matematica": "em Matemática (Matific)"}
    # O que `montar_contexto` escreve na seção de pódio de uma disciplina que a
    # rede NÃO contratou (cascata contrato → dado).
    _FORA_DO_CONTRATO = "não faz parte do contrato"
    #: Teto do "top N". `montar_contexto` escreve as seções de pódio com este
    #: mesmo tamanho — senão "top 25" seria respondido com as 10 linhas que
    #: couberam, chamadas de "os 10 melhores", como se fossem a lista inteira.
    MAX_PODIO = 25

    @classmethod
    def _top_n(cls, pergunta: str, secoes: dict[str, str]) -> str | None:
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

        rodape = "\n\n(Resposta gerada no modo local, somente com dados do sistema.)"
        # Disciplinas que esta rede tem: a seção de pódio existe no contexto e
        # não diz "não faz parte do contrato".
        contratadas = [d for d, nome in cls._SECAO_DA_DISCIPLINA.items()
                       if nome in secoes
                       and cls._FORA_DO_CONTRATO not in secoes[nome]]

        if re.search(r"\b(matific|matematica)\b", pergunta):
            disciplinas = ["matematica"]
        elif re.search(r"\b(elefante|leitura|portugues|letrado)\b", pergunta):
            disciplinas = ["leitura"]
        else:
            # Sem disciplina na pergunta ("o melhor aluno da escola"): não existe
            # uma nota única que junte as disciplinas (Arquitetura 2) — a
            # resposta honesta é o pódio de CADA disciplina contratada.
            disciplinas = contratadas
        if len(disciplinas) == 1 and disciplinas[0] not in contratadas:
            # Pediu a disciplina que a rede não contratou: diz isso, em vez de
            # cair numa seção qualquer que "melhores" também casa.
            secao = secoes.get(cls._SECAO_DA_DISCIPLINA[disciplinas[0]], "").strip()
            return (secao.lstrip("- ") + rodape) if secao else None

        achado = re.search(r"\b(\d+)\b", pergunta)
        n = int(achado.group(1)) if achado else (
            1 if re.search(r"\bmelhor\b", pergunta) else 5)
        n = max(1, min(n, cls.MAX_PODIO))

        blocos = []
        for disciplina in disciplinas:
            # A seção já vem na ordem oficial, com o lugar oficial: o modo local
            # não reordena nem renumera — só corta no N pedido.
            alunos = [par for par in (
                cls._RE_PODIO.match(linha.strip())
                for linha in secoes[cls._SECAO_DA_DISCIPLINA[disciplina]].splitlines())
                if par][:n]
            rotulo = cls._ROTULOS[disciplina]
            if not alunos:
                blocos.append(f"Ainda não há alunos aferidos {rotulo}.")
                continue
            titulo = (f"O melhor aluno {rotulo}" if n == 1
                      else f"Os {len(alunos)} melhores alunos {rotulo}")
            blocos.append(f"{titulo}, pelos dados do sistema:\n" + "\n".join(
                f"{par.group('lugar')}º: {par.group('nome')} ({par.group('turma')})"
                f" — nota {float(par.group('nota').replace(',', '.')):.1f}"
                for par in alunos))
        if not blocos:
            return None
        aviso = ("Cada disciplina tem o seu próprio ranking — não existe uma nota "
                 "única que junte as duas.\n\n" if len(disciplinas) > 1 else "")
        return aviso + "\n\n".join(blocos) + rodape

    @staticmethod
    def _aluno_citado(pergunta: str, secao_alunos: str) -> dict | None:
        """O aluno cujo nome aparece na pergunta. Casa por PALAVRA inteira e,
        havendo mais de um, fica com o nome mais longo: "Ana Souza" está
        contido em "Mariana Souza" e em "Ana Souza Lima" — sem essas duas
        regras, a pergunta sobre a Mariana devolvia a linha da Ana (a seção
        ALUNOS é alfabética, e a Ana vem antes)."""
        citado = None
        for linha in secao_alunos.splitlines():
            linha = linha.strip()
            if not linha.startswith("- "):
                continue
            nome = linha[2:].split(":", 1)[0].strip()
            if (nome and re.search(rf"(?<!\w){re.escape(_plano(nome))}(?!\w)", pergunta)
                    and (citado is None or len(nome) > len(citado["nome"]))):
                citado = {"nome": nome, "linha": linha}
        return citado


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
