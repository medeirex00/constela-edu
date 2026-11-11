"""Implementações dos provedores de IA (PRD §154).

* AnthropicProvedor — SDK oficial `anthropic` (Messages API).
* OpenAIProvedor   — HTTP direto via httpx (sem SDK adicional).
* LocalProvedor    — determinístico, responde lendo o contexto montado pelo
  backend; sem rede, sem chave. É o padrão e o plano B dos outros dois.
"""
from __future__ import annotations

import re
import time
import unicodedata

import httpcore
import httpx

from app.core.config import settings
from app.services.ia.base import ErroProvedorIA, ProvedorIA

MODELO_ANTHROPIC_PADRAO = "claude-opus-4-8"
MODELO_OPENAI_PADRAO = "gpt-4o"
URL_OPENAI = "https://api.openai.com/v1/chat/completions"

# Prazo das chamadas aos provedores externos. Sem prazo, o SDK da Anthropic espera
# 600 s pela resposta e tenta mais 2 vezes: até ~30 min por pergunta, com a thread
# do worker presa. E o prazo do httpx vale POR OPERAÇÃO de rede (cada pedaço que
# chega recomeça a contagem): uma resposta gotejando (um proxy/CDN no caminho) nunca
# o estoura. Por isso cada chamada tem um PRAZO TOTAL, contado do início: toda
# operação de rede (conectar, TLS, enviar, receber cabeçalho e corpo) espera no
# máximo o que resta dele; esgotado, a chamada falha na hora e o assistente responde
# no modo local. Sem nova tentativa da Anthropic: a pausa do SDK antes dela (o que o
# provedor pedir, até 60 s) ficaria fora do prazo, e o modo local já cobre a falha.
# Pior caso de uma pergunta: PRAZO_TOTAL_S (fora dele, só a consulta de DNS, que
# tem o prazo do próprio sistema).
PRAZO_CONEXAO_S = 5.0
PRAZO_TOTAL_S = 60.0
NOVAS_TENTATIVAS_ANTHROPIC = 0


def _prazo() -> httpx.Timeout:
    """Prazo por operação, que o httpx exige; o total vem de ``_cliente_http``."""
    return httpx.Timeout(PRAZO_TOTAL_S, connect=PRAZO_CONEXAO_S)


class _RedeComPrazoTotal(httpcore.NetworkBackend):
    """A rede do httpcore em que cada operação espera no máximo o que resta até
    ``limite`` (``time.monotonic()``); passado o limite, falha sem esperar."""

    def __init__(self, limite: float):
        self._limite = limite
        self._rede = httpcore.SyncBackend()

    def espera(self, timeout: float | None,
               esgotado: type[httpcore.TimeoutException]) -> float:
        restante = self._limite - time.monotonic()
        if restante <= 0:
            raise esgotado("prazo total da chamada ao provedor de IA esgotado")
        return restante if timeout is None else min(timeout, restante)

    def connect_tcp(self, host, port, timeout=None, local_address=None,
                    socket_options=None):
        fluxo = self._rede.connect_tcp(
            host, port, timeout=self.espera(timeout, httpcore.ConnectTimeout),
            local_address=local_address, socket_options=socket_options)
        return _FluxoComPrazoTotal(fluxo, self)

    def connect_unix_socket(self, path, timeout=None, socket_options=None):
        fluxo = self._rede.connect_unix_socket(
            path, timeout=self.espera(timeout, httpcore.ConnectTimeout),
            socket_options=socket_options)
        return _FluxoComPrazoTotal(fluxo, self)

    def sleep(self, seconds: float) -> None:
        self._rede.sleep(seconds)


class _FluxoComPrazoTotal(httpcore.NetworkStream):
    def __init__(self, fluxo: httpcore.NetworkStream, rede: _RedeComPrazoTotal):
        self._fluxo, self._rede = fluxo, rede

    def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return self._fluxo.read(max_bytes,
                                timeout=self._rede.espera(timeout, httpcore.ReadTimeout))

    def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self._fluxo.write(buffer, timeout=self._rede.espera(timeout, httpcore.WriteTimeout))

    def close(self) -> None:
        self._fluxo.close()

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        fluxo = self._fluxo.start_tls(
            ssl_context, server_hostname=server_hostname,
            timeout=self._rede.espera(timeout, httpcore.ConnectTimeout))
        return _FluxoComPrazoTotal(fluxo, self._rede)

    def get_extra_info(self, info: str):
        return self._fluxo.get_extra_info(info)


class _TransporteComPrazoTotal(httpx.HTTPTransport):
    """O ``HTTPTransport`` padrão (mesmo TLS, mesmo mapa de erros do httpx) sobre a
    ``_RedeComPrazoTotal``. O httpx não deixa escolher a rede do httpcore: o pool
    é refeito com ela (httpx fixado em requirements.txt; a guarda abaixo e o
    teste do servidor gotejando acusam se a estrutura mudar)."""

    def __init__(self, limite: float):
        tls = httpx.create_ssl_context()
        super().__init__(verify=tls)
        if not isinstance(getattr(self, "_pool", None), httpcore.ConnectionPool):
            raise RuntimeError("httpx.HTTPTransport sem o _pool esperado: "
                               "rever _TransporteComPrazoTotal")
        self._pool = httpcore.ConnectionPool(ssl_context=tls,
                                             network_backend=_RedeComPrazoTotal(limite))


def _cliente_http(limite: float) -> httpx.Client:
    """Cliente HTTP de UMA chamada a provedor externo: nenhuma operação de rede
    passa de ``limite`` (``time.monotonic()``). Com o transporte próprio, o httpx
    não usa proxy de variável de ambiente (HTTPS_PROXY), que o sistema não usa."""
    return httpx.Client(transport=_TransporteComPrazoTotal(limite), timeout=_prazo())


class AnthropicProvedor(ProvedorIA):
    nome = "anthropic"

    def __init__(self, api_key: str, modelo: str | None = None):
        if not api_key:
            raise ErroProvedorIA("AI_API_KEY não configurada para o provedor Anthropic.")
        self._api_key = api_key
        self._modelo = modelo or MODELO_ANTHROPIC_PADRAO

    def responder(self, sistema: str, mensagens: list[dict]) -> str:
        import anthropic

        limite = time.monotonic() + PRAZO_TOTAL_S
        try:
            with _cliente_http(limite) as http:
                cliente = anthropic.Anthropic(api_key=self._api_key, timeout=_prazo(),
                                              max_retries=NOVAS_TENTATIVAS_ANTHROPIC,
                                              http_client=http)
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
        except anthropic.AnthropicError as erro:
            raise ErroProvedorIA(f"Falha no provedor Anthropic: {erro}") from erro
        # Um 200 fora do formato também é falha do provedor: a página HTML de um
        # proxy no caminho (o SDK a devolve como TEXTO cru, sem ``stop_reason``),
        # o JSON sem os campos, a resposta sem nenhum bloco de texto.
        try:
            if resposta.stop_reason == "refusal":
                return "Não posso responder a essa pergunta."
            texto = "".join(
                bloco.text for bloco in resposta.content if bloco.type == "text"
            ).strip()
        except (AttributeError, TypeError) as erro:
            raise ErroProvedorIA("Resposta inesperada do provedor Anthropic.") from erro
        if not texto:
            raise ErroProvedorIA("Resposta vazia do provedor Anthropic.")
        return texto


class OpenAIProvedor(ProvedorIA):
    nome = "openai"

    def __init__(self, api_key: str, modelo: str | None = None):
        if not api_key:
            raise ErroProvedorIA("AI_API_KEY não configurada para o provedor OpenAI.")
        self._api_key = api_key
        self._modelo = modelo or MODELO_OPENAI_PADRAO

    def responder(self, sistema: str, mensagens: list[dict]) -> str:
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
        limite = time.monotonic() + PRAZO_TOTAL_S
        try:
            with _cliente_http(limite) as cliente:
                resposta = cliente.post(
                    URL_OPENAI,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json=corpo,
                )
                resposta.raise_for_status()
                dados = resposta.json()
        except httpx.HTTPError as erro:
            raise ErroProvedorIA(f"Falha no provedor OpenAI: {erro}") from erro
        except ValueError as erro:
            # 200 com corpo que não é JSON (página HTML de um proxy/CDN no caminho).
            raise ErroProvedorIA("Resposta inesperada do provedor OpenAI.") from erro
        try:
            conteudo = dados["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as erro:
            raise ErroProvedorIA("Resposta inesperada do provedor OpenAI.") from erro
        if not isinstance(conteudo, str) or not conteudo.strip():
            # ``content`` nulo (recusa, chamada de ferramenta) ou vazio.
            raise ErroProvedorIA("Resposta vazia do provedor OpenAI.")
        return conteudo.strip()


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

        # Pergunta de um módulo que a rede não contratou: diz isso, em vez de um
        # pódio (de retrato antigo) ou de despejar outra seção.
        fora = self._fora_do_plano(pergunta, secoes.get("FORA_DO_PLANO", ""))
        if fora:
            return fora

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

    # Palavras de cada módulo na pergunta (as mesmas do pódio, em `_top_n`). A
    # chave é o começo da linha que assistente.montar_contexto escreve na seção
    # FORA_DO_PLANO ("- Matemática: não faz parte do plano desta rede; ...").
    _MODULOS_NA_PERGUNTA = (
        ("matematica", re.compile(r"\b(matific|matematica)\b")),
        ("leitura", re.compile(r"\b(elefante|leitura|portugues|letrado)\b")),
    )

    @classmethod
    def _fora_do_plano(cls, pergunta: str, secao_fora: str) -> str | None:
        linhas = [linha.strip()[2:] for linha in secao_fora.splitlines()
                  if linha.strip().startswith("- ")]
        citadas = [linha for modulo, padrao in cls._MODULOS_NA_PERGUNTA
                   if padrao.search(pergunta)
                   for linha in linhas if _plano(linha).startswith(modulo)]
        if not citadas:
            return None
        return ("\n".join(citadas)
                + "\n\n(Resposta gerada no modo local, somente com dados do sistema.)")

    # Linha da seção ALUNOS: "- NOME: turma T, 3º lugar, geral 8.5, Matific 7.0,
    # Elefante 9.0" — montada em assistente.montar_contexto. Cada plataforma é
    # opcional por si: a que a rede não contratou não vem na linha.
    # A turma ancora em "º lugar" (não na primeira vírgula) para nomes de turma
    # com vírgula ("4º Ano, Integral") não saírem truncados.
    _RE_ALUNO = re.compile(
        r"^- (?P<nome>.+?): turma (?P<turma>.+?), \S+º lugar, .*?"
        r"geral (?P<geral>\d+(?:[.,]\d+)?)"
        r"(?:, Matific (?P<matific>\d+(?:[.,]\d+)?))?"
        r"(?:, Elefante (?P<elefante>\d+(?:[.,]\d+)?))?")

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
            metrica, rotulo = "matific", "no Matific"
        elif re.search(r"\b(elefante|leitura|portugues|letrado)\b", pergunta):
            metrica, rotulo = "elefante", "no Elefante Letrado"
        else:
            metrica, rotulo = "geral", "da escola (nota geral)"

        achado = re.search(r"\b(\d+)\b", pergunta)
        n = int(achado.group(1)) if achado else (
            1 if re.search(r"\bmelhor\b", pergunta) else 5)
        n = max(1, min(n, 25))

        alunos = []
        for linha in secao_alunos.splitlines():
            par = cls._RE_ALUNO.match(linha.strip())
            if not par or par.group(metrica) is None:
                continue
            alunos.append((float(par.group(metrica).replace(",", ".")),
                           par.group("nome"), par.group("turma"), par))
        if not alunos:
            return None

        alunos.sort(key=lambda a: a[0], reverse=True)
        linhas = [
            f"{i}º: {nome} ({turma}) — nota {valor:.1f}"
            + (f" (geral {par.group('geral')})" if metrica != "geral" else "")
            for i, (valor, nome, turma, par) in enumerate(alunos[:n], start=1)
        ]
        titulo = (f"O melhor aluno {rotulo}" if n == 1
                  else f"Os {min(n, len(alunos))} melhores alunos {rotulo}")
        return (f"{titulo}, pelos dados do sistema:\n" + "\n".join(linhas)
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
