"""Assistente com provedor EXTERNO: nenhum dado identificável de aluno sai (A1).

O provedor externo é substituído por um FALSO que captura o que iria pela rede:
o ``anthropic.Anthropic`` (``messages.create``) e o cliente HTTP da OpenAI
(``provedores._cliente_http``, com um transporte falso do httpx). O
fluxo é o real, ponta a ponta: o Admin Global liga o provedor pela API (P9), o
admin da escola pergunta pela API e a configuração da escola escolhe o provedor.

Antes, só o nome COMPLETO (sem diferenciar caixa) virava "Aluno NNN": o primeiro
nome sozinho, o nome sem acento ("joao"), o RA e o e-mail digitados na pergunta
saíam como foram escritos, e voltavam a sair a cada pergunta seguinte, no
histórico. Dados fictícios.
"""
import json
import re
import unicodedata
from types import SimpleNamespace

import pytest

from app.models import Importacao, SnapshotMatific
from app.services import assistente, scoring

API = "/api/v1"
RA_ANA = "000111222333-4"        # RA longo, formatado com zeros à esquerda
RA_JOAO = "4321"                 # RA curto: só sai pelo valor conhecido da ficha
RA_SOFIA = "000987654321-X"      # RA com dígito verificador "X"
EMAIL = "ana.souza.ficticia@exemplo.invalid"
TELEFONE = "(12) 99876-5432"
PARTICULAS = {"de", "da", "do", "das", "dos", "e"}


def _plano(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto)
                   if unicodedata.category(c) != "Mn").casefold()


def _palavras(texto: str) -> set[str]:
    return set(re.findall(r"[^\W\d_]+", _plano(texto)))


def _numeros(texto: str) -> set[str]:
    """Os dígitos de cada número do texto (separadores . - / no meio)."""
    return {re.sub(r"\D", "", n) for n in re.findall(r"\d(?:[.\-/]?\d)*", texto)}


def _textos(valor):
    """Todas as strings do corpo capturado (system, messages, model...)."""
    if isinstance(valor, str):
        yield valor
    elif isinstance(valor, dict):
        for item in valor.values():
            yield from _textos(item)
    elif isinstance(valor, (list, tuple)):
        for item in valor:
            yield from _textos(item)


@pytest.fixture()
def escola_com_fichas(db, escola_completa):
    """Os 3 alunos fictícios com RA na ficha e nota calculada (aparecem no
    ranking, nos índices e, os sem dados, nos alertas do contexto)."""
    escola = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]   # "João" com acento no banco
    ana.ficha = {"ra": RA_ANA}
    joao.ficha = {"ra": RA_JOAO}
    sofia.ficha = {"ra": RA_SOFIA}
    importacao = Importacao(escola_id=escola.id, plataforma="matific", tipo="seed")
    db.add(importacao)
    db.flush()
    from datetime import datetime, timedelta, timezone
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=ana.id,
                           importacao_id=importacao.id,
                           data_referencia=datetime.now(timezone.utc) - timedelta(days=1),
                           atividades=50, estrelas=150, pontuacao_media=85))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    return escola_completa


class _Captura:
    """O que o provedor falso recebeu: o CORPO que iria pela rede, por chamada."""

    def __init__(self):
        self.corpos: list[dict] = []
        self.cabecalhos: list[dict] = []
        self.api_key = None

    def texto(self, n: int = -1) -> str:
        return "\n".join(_textos(self.corpos[n]))


def _falso_anthropic(monkeypatch, captura: _Captura):
    import anthropic

    class Mensagens:
        def create(self, **kwargs):
            captura.corpos.append(kwargs)
            token = re.search(r"Aluno \d+", kwargs["system"]).group(0)
            return SimpleNamespace(stop_reason="end_turn", content=[
                SimpleNamespace(type="text", text=f"O destaque é {token}.")])

    class Cliente:
        def __init__(self, api_key, **_opcoes):  # timeout, max_retries (o prazo)
            captura.api_key = api_key
            self.messages = Mensagens()

    monkeypatch.setattr(anthropic, "Anthropic", Cliente)


# Cabeçalhos que o próprio httpx põe em todo pedido; o resto veio do provedor.
_CABECALHOS_DO_HTTPX = {"host", "accept", "accept-encoding", "connection", "user-agent",
                        "content-length", "content-type"}


def _falso_openai(monkeypatch, captura: _Captura):
    import httpx

    from app.services.ia import provedores

    def responder(pedido: httpx.Request) -> httpx.Response:
        assert str(pedido.url) == "https://api.openai.com/v1/chat/completions"
        corpo = json.loads(pedido.content)
        captura.corpos.append(corpo)
        captura.cabecalhos.append({
            nome.decode(): valor.decode() for nome, valor in pedido.headers.raw
            if nome.decode().lower() not in _CABECALHOS_DO_HTTPX})
        token = re.search(r"Aluno \d+", corpo["messages"][0]["content"]).group(0)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": f"O destaque é {token}."}}]})

    monkeypatch.setattr(provedores, "_cliente_http", lambda _limite: httpx.Client(
        transport=httpx.MockTransport(responder)))


def _pergunta_com_tudo(ana, joao, sofia) -> str:
    return (f"Compare {_plano(joao.nome)} com a Ana e com a sofia Duarte "
            f"(RA {RA_ANA}, RA {RA_JOAO}, RA 111.222.333-4 e RA {RA_SOFIA}; "
            f"colados à letra: RA{RA_ANA}, RA nº{RA_ANA}, RA{RA_JOAO} e "
            f"ra_{RA_SOFIA}); contato {EMAIL} ou {TELEFONE}. "
            f"Quem está no top 3 desde 01/09/2026?")


def _sem_dado_identificavel(enviado: str, alunos) -> None:
    palavras = _palavras(enviado)
    for aluno in alunos:
        assert _plano(aluno.nome) not in _plano(enviado), f"vazou nome: {aluno.nome}"
        pedacos = {p for p in _palavras(aluno.nome) if len(p) >= 3} - PARTICULAS
        assert not (pedacos & palavras), f"vazou pedaço de nome: {pedacos & palavras}"
    numeros = _numeros(enviado)
    for ra in ("111222333", "987654321", "998765432"):
        assert not any(ra in n for n in numeros), f"vazou número de documento: {ra}"
    assert not re.search(rf"(?<!\d){RA_JOAO}(?!\d)", enviado), "vazou RA curto"
    assert "@" not in enviado and "exemplo.invalid" not in enviado, "vazou e-mail"


@pytest.mark.parametrize("provedor", ["anthropic", "openai"])
def test_payload_externo_sem_nome_ra_nem_email_e_resposta_reidentificada(
        cliente, cliente_global, db, escola_com_fichas, monkeypatch, provedor):
    escola = escola_com_fichas["escola"]
    alunos = escola_com_fichas["alunos"]
    ana, joao, sofia = alunos
    captura = _Captura()
    (_falso_anthropic if provedor == "anthropic" else _falso_openai)(monkeypatch, captura)
    ligado = cliente_global.put(f"{API}/escolas/{escola.id}/assistente/config",
                                json={"provedor": provedor, "api_key": "chave-ficticia-ia"})
    assert ligado.status_code == 200, ligado.text

    url = f"{API}/escolas/{escola.id}/assistente"
    r = cliente.post(url, json={"pergunta": _pergunta_com_tudo(ana, joao, sofia)})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["provedor"] == provedor
    assert len(captura.corpos) == 1

    enviado = captura.texto()
    _sem_dado_identificavel(enviado, alunos)
    assert "chave-ficticia-ia" not in enviado         # a chave não vai no corpo
    # O que serve à pergunta continua lá; o que identifica virou marcador.
    assert "top 3" in enviado and "01/09/2026" in enviado
    assert re.search(r"Aluno \d+", enviado)           # nome completo -> token
    # Os marcadores, conferidos na PERGUNTA que sai (as instruções os citam).
    pergunta_enviada = captura.corpos[0]["messages"][-1]["content"]
    assert re.search(r"Aluno \d+", pergunta_enviada)  # "joao pedro barbosa"
    assert "[nome omitido]" in pergunta_enviada       # primeiro nome sozinho
    assert "[e-mail omitido]" in pergunta_enviada
    # 4 RA espaçados + 4 colados à letra + o telefone; a data fica.
    assert pergunta_enviada.count("[identificador omitido]") == 9
    assert "top 3" in pergunta_enviada and "01/09/2026" in pergunta_enviada
    # A resposta volta reidentificada para quem perguntou (e é o que fica gravado).
    assert any(a.nome in corpo["resposta"] for a in alunos)

    # 2ª pergunta na MESMA conversa: o histórico (pergunta crua + resposta já
    # reidentificada, com nome real) é limpo de novo antes de sair.
    r2 = cliente.post(url, json={"pergunta": "E a Sofia?",
                                 "conversa_id": corpo["conversa_id"]})
    assert r2.status_code == 200, r2.text
    assert len(captura.corpos) == 2
    _sem_dado_identificavel(captura.texto(), alunos)

    # Fora o corpo, só a chave (no cabeçalho/cliente): nenhum campo de usuário.
    if provedor == "openai":
        assert captura.cabecalhos[0] == {"Authorization": "Bearer chave-ficticia-ia"}
        assert set(captura.corpos[0]) == {"model", "max_tokens", "messages"}
    else:
        assert captura.api_key == "chave-ficticia-ia"
        assert set(captura.corpos[0]) == {
            "model", "max_tokens", "cache_control", "system", "messages"}


@pytest.mark.parametrize("provedor", ["anthropic", "openai"])
@pytest.mark.parametrize("pergunta,ra,sai", [
    (f"Como está o aluno de RA{RA_ANA}?", RA_ANA,
     "Como está o aluno de RA[identificador omitido]?"),
    (f"Como está o aluno RA nº{RA_ANA}?", RA_ANA,
     "Como está o aluno RA nº[identificador omitido]?"),
    (f"E o RA{RA_JOAO}?", RA_JOAO, "E o RA[identificador omitido]?"),
], ids=["ra_longo", "ra_longo_no", "ra_curto_da_ficha"])
def test_ra_colado_a_letra_nao_sai_para_o_provedor_externo(
        cliente, cliente_global, escola_com_fichas, monkeypatch, provedor, pergunta, ra,
        sai):
    """Antes, a borda do número era de PALAVRA: "RA123…" e "nº123…" (o "º" é
    letra) não casavam, e o RA saía inteiro, até o curto conhecido da ficha."""
    escola = escola_com_fichas["escola"]
    captura = _Captura()
    (_falso_anthropic if provedor == "anthropic" else _falso_openai)(monkeypatch, captura)
    ligado = cliente_global.put(f"{API}/escolas/{escola.id}/assistente/config",
                                json={"provedor": provedor, "api_key": "chave-ficticia-ia"})
    assert ligado.status_code == 200, ligado.text

    r = cliente.post(f"{API}/escolas/{escola.id}/assistente", json={"pergunta": pergunta})
    assert r.status_code == 200, r.text
    assert r.json()["provedor"] == provedor and len(captura.corpos) == 1
    enviado = captura.texto()
    _sem_dado_identificavel(enviado, escola_com_fichas["alunos"])
    assert not re.search(rf"(?<!\d){re.escape(ra)}(?!\d)", enviado), f"vazou RA: {ra}"
    # A pergunta que sai (última mensagem) é a escrita, só com o RA trocado.
    assert captura.corpos[0]["messages"][-1]["content"] == sai


def test_modo_local_nao_pseudonimiza(cliente, db, escola_com_fichas):
    """O `local` roda no backend, sem rede: segue respondendo com o nome real."""
    escola = escola_com_fichas["escola"]
    ana = escola_com_fichas["alunos"][0]
    r = cliente.post(f"{API}/escolas/{escola.id}/assistente",
                     json={"pergunta": f"como está {ana.nome}?"})
    assert r.status_code == 200, r.text
    assert r.json()["provedor"] == "local" and ana.nome in r.json()["resposta"]


# --- O limpador, peça por peça -------------------------------------------------------

MAPA = {"Ana Beatriz Souza": "Aluno 01", "João Pedro Barbosa": "Aluno 02",
        "Maria das Dores Dias": "Aluno 03", "Carlos Silva Filho": "Aluno 04"}


def _limpo(texto, identificadores=(), conversa=True):
    return assistente._pseudonimizar(texto, MAPA, identificadores, conversa=conversa)


@pytest.mark.parametrize("escrito", [
    "Ana Beatriz Souza", "ANA BEATRIZ SOUZA", "ana beatriz souza", "Âna Beatríz Sóuza",
    "Ana  Beatriz\nSouza", "Ana-Beatriz Souza",
])
def test_nome_completo_em_qualquer_caixa_ou_acento_vira_token(escrito):
    assert _limpo(f"como está {escrito}?") == "como está Aluno 01?"


def test_nome_sem_acento_casa_o_do_banco_com_acento():
    assert _limpo("e o joao pedro barbosa?") == "e o Aluno 02?"
    assert _limpo("e o JOÃO PEDRO BARBOSA?") == "e o Aluno 02?"


def test_pedaco_de_nome_na_conversa_vira_marcador():
    assert _limpo("como está a ana?") == "como está a [nome omitido]?"
    assert _limpo("e o João Barbosa?") == "e o [nome omitido] [nome omitido]?"
    # Partícula e sufixo sozinhos não identificam: ficam.
    assert _limpo("o filho da escola") == "o filho da escola"
    # Privacidade antes de precisão: "dias" é sobrenome de um aluno.
    assert _limpo("há 3 dias") == "há 3 [nome omitido]"


def test_contexto_troca_so_o_nome_completo_e_preserva_os_textos_fixos():
    contexto = ("- Maria das Dores Dias está sem novos dados há 12 dias.\n"
                "- Escola: EMEF Ana Rosa; turma 3º Ano A; Alunos com nota: 4321")
    assert _limpo(contexto, ["4321"], conversa=False) == (
        "- Aluno 03 está sem novos dados há 12 dias.\n"
        "- Escola: EMEF Ana Rosa; turma 3º Ano A; Alunos com nota: 4321")


def test_email_e_numeros_de_documento_saem_datas_e_contagens_ficam():
    texto = ("RA 000123456789-0, RA 123456789X, CPF 123.456.789-00, RG 12.345.678-9, "
             "tel (12) 99876-5432, CEP 11600-000, e-mail ana_b+1@escola.exemplo.invalid. "
             "Top 5 do 3º Ano A, nota 8.5, 120 atividades, em 2026, desde 01/09/2026 "
             "ou 2026-09-01.")
    limpo = _limpo(texto)
    assert limpo == (
        "RA [identificador omitido], RA [identificador omitido], CPF [identificador "
        "omitido], RG [identificador omitido], tel (12) [identificador omitido], CEP "
        "[identificador omitido], e-mail [e-mail omitido]. "
        "Top 5 do 3º Ano A, nota 8.5, 120 atividades, em 2026, desde 01/09/2026 "
        "ou 2026-09-01.")


def test_ra_curto_conhecido_sai_so_na_conversa():
    assert _limpo("o RA 4321 e o 4320", ["4321"]) == "o RA [identificador omitido] e o 4320"
    assert _limpo("o RA 0004321", ["4321"]) == "o RA [identificador omitido]"
    assert _limpo("o RA 4321", ["4321"], conversa=False) == "o RA 4321"


@pytest.mark.parametrize("escrito,sai", [
    ("o aluno RA123456789 faltou", "o aluno RA[identificador omitido] faltou"),
    ("RA nº123456789-0", "RA nº[identificador omitido]"),   # "º" é letra
    ("RA000111222333-4", "RA[identificador omitido]"),
    ("RA nº000111222333-4", "RA nº[identificador omitido]"),
    ("ra_123456789", "ra_[identificador omitido]"),
    ("RA 123456789SP", "RA [identificador omitido]SP"),
    ("CPF12345678900", "CPF[identificador omitido]"),
    ("RA4321", "RA[identificador omitido]"),               # RA curto da ficha
    ("RA nº4321", "RA nº[identificador omitido]"),
    ("ra_4321", "ra_[identificador omitido]"),
    ("RA4321X e 4321-x", "RA[identificador omitido] e [identificador omitido]"),
    ("RA4321xis", "RA[identificador omitido]xis"),         # "x" de palavra não é DV
])
def test_numero_colado_a_letra_tambem_sai(escrito, sai):
    """Antes a borda do número era de PALAVRA (\\w): colado a letra, ao "_" ou ao
    "º" de "nº", o número nem era avaliado e saía inteiro."""
    assert _limpo(escrito, ["4321"]) == sai


def test_ra_da_ficha_com_letra_casa_pelos_digitos():
    assert _limpo("RA A1234, RAA1234 e 1234", ["A1234"]) == (
        "RA A[identificador omitido], RAA[identificador omitido] e "
        "[identificador omitido]")
    assert _limpo("o RA 4321", ["4321-X"]) == "o RA [identificador omitido]"
    # Menos de 4 dígitos seguidos não vira chave (nem "12" nem "34").
    assert _limpo("o 12 e o 34", ["12A34"]) == "o 12 e o 34"


def test_borda_de_digito_preserva_ordinais_notas_contagens_e_datas():
    texto = ("o 3º ano, 5ºA, 1º lugar, nota 8.5, top 3, 10x por semana, em 2026, "
             "desde 01/09/2026 ou 2026-09-01, 43210 e 54321, Aluno 01")
    assert _limpo(texto, ["4321"]) == texto
    assert _limpo(texto, ["4321"], conversa=False) == texto


def test_reidentificacao_volta_o_token_ao_nome():
    assert assistente._reidentificar("Aluno 02 e Aluno 01", MAPA) == (
        "João Pedro Barbosa e Ana Beatriz Souza")


def test_mapa_cobre_aluno_com_nota_na_escola_e_ficha_noutra(db, escola_completa):
    """Aluno cuja ficha hoje é de outra escola, mas que ainda tem nota/matrícula
    aqui, entra no mapa: se o nome dele cair no contexto, sai como token."""
    from app.models import Escola, Matricula
    escola = escola_completa["escola"]
    outra = Escola(nome="ESCOLA B FICTICIA", ano_letivo_ativo=2026)
    db.add(outra)
    db.flush()
    sofia = escola_completa["alunos"][2]
    sofia.escola_id = outra.id                 # ficha mudou de escola
    db.commit()
    assert db.query(Matricula).filter_by(aluno_id=sofia.id, escola_id=escola.id).count()
    assert sofia.nome in assistente._mapa_pseudonimos(db, escola.id)
