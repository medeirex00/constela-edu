"""Assistente com provedor externo que responde 200 de um jeito anômalo (API_SEGURANCA-2).

Um proxy/CDN no caminho que devolve uma página HTML com 200, ou o provedor que
devolve ``content: null`` (recusa, chamada de ferramenta) ou texto vazio: o
assistente cai no modo local (contingência), nunca responde 404 com a mensagem
interna do parse nem 500. O "Testar configuração" do admin responde
``{ok: false}``. E só a conversa inexistente vira 404.

As respostas HTTP são de verdade (``httpx.MockTransport``): o SDK da Anthropic e o
``httpx`` fazem o parse real delas. Nada sai para a rede. Dados fictícios."""
import json

import anthropic
import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import assistente
from app.services.ia import ErroProvedorIA
from app.services.ia.provedores import AnthropicProvedor, OpenAIProvedor

API = "/api/v1"
HTML = "<html><body>Bad gateway (proxy)</body></html>"
CONVERSA = [{"papel": "usuario", "conteudo": "Como está a escola?"}]
_ANTHROPIC = anthropic.Anthropic  # a classe do SDK, antes de qualquer troca


def _resposta(corpo) -> httpx.Response:
    if isinstance(corpo, str):
        return httpx.Response(200, text=corpo, headers={"content-type": "text/html"})
    return httpx.Response(200, content=json.dumps(corpo).encode(),
                          headers={"content-type": "application/json"})


def _openai_responde(monkeypatch, corpo) -> None:
    """Toda chamada do OpenAIProvedor (``httpx.post``) recebe ``corpo`` com 200."""
    transporte = httpx.MockTransport(lambda _req: _resposta(corpo))

    def post(url, **kwargs):
        with httpx.Client(transport=transporte) as cliente:
            return cliente.post(url, **kwargs)
    monkeypatch.setattr(httpx, "post", post)


def _anthropic_responde(monkeypatch, corpo) -> None:
    """O cliente do SDK da Anthropic criado pelo provedor recebe ``corpo`` com 200."""
    class ComTransporte(_ANTHROPIC):
        def __init__(self, *args, **kwargs):
            kwargs["http_client"] = httpx.Client(
                transport=httpx.MockTransport(lambda _req: _resposta(corpo)))
            super().__init__(*args, **kwargs)
    monkeypatch.setattr(anthropic, "Anthropic", ComTransporte)


def _mensagem_anthropic(blocos, stop_reason="end_turn") -> dict:
    return {"id": "msg_ficticia", "type": "message", "role": "assistant",
            "model": "modelo-ficticio", "content": blocos, "stop_reason": stop_reason,
            "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}


def _liga(cliente_global, escola_id, provedor) -> None:
    r = cliente_global.put(f"{API}/escolas/{escola_id}/assistente/config",
                           json={"provedor": provedor, "api_key": "sk-ficticia-teste"})
    assert r.status_code == 200, r.text


def _sem_excecao(cliente) -> TestClient:
    """Cliente que devolve o 500 em vez de relançar a exceção do servidor."""
    c = TestClient(app, raise_server_exceptions=False)
    c.headers.update(cliente.headers)
    return c


# --- Os provedores: toda resposta anômala vira ErroProvedorIA ----------------------

@pytest.mark.parametrize("corpo", [
    HTML,                                                    # proxy/CDN: não é JSON
    {"choices": [{"message": {"content": None, "refusal": "não"}}]},
    {"choices": [{"message": {"content": "   "}}]},
    {"choices": [{"message": {"content": ["pedaço"]}}]},
    {"choices": None},
    [],
    None,
], ids=["html", "content-nulo", "content-vazio", "content-lista", "choices-nulo",
        "lista", "null"])
def test_openai_resposta_200_anomala_vira_erro_do_provedor(monkeypatch, corpo):
    _openai_responde(monkeypatch, corpo)
    with pytest.raises(ErroProvedorIA):
        OpenAIProvedor("sk-ficticia").responder("sistema", CONVERSA)


def test_openai_resposta_normal_continua_valendo(monkeypatch):
    _openai_responde(monkeypatch, {"choices": [{"message": {"content": "  Tudo bem.  "}}]})
    assert OpenAIProvedor("sk-ficticia").responder("sistema", CONVERSA) == "Tudo bem."


@pytest.mark.parametrize("corpo", [
    HTML,                                    # o SDK devolve o TEXTO cru, não um objeto
    _mensagem_anthropic([]),                 # nenhum bloco de texto
    _mensagem_anthropic([{"type": "text", "text": "  "}]),
], ids=["html", "sem-bloco-de-texto", "texto-vazio"])
def test_anthropic_resposta_200_anomala_vira_erro_do_provedor(monkeypatch, corpo):
    _anthropic_responde(monkeypatch, corpo)
    with pytest.raises(ErroProvedorIA):
        AnthropicProvedor("sk-ant-ficticia").responder("sistema", CONVERSA)


def test_anthropic_resposta_normal_e_recusa_continuam_valendo(monkeypatch):
    _anthropic_responde(monkeypatch, _mensagem_anthropic([{"type": "text", "text": " Oi. "}]))
    assert AnthropicProvedor("sk-ant-ficticia").responder("sistema", CONVERSA) == "Oi."
    _anthropic_responde(monkeypatch, _mensagem_anthropic([], stop_reason="refusal"))
    assert AnthropicProvedor("sk-ant-ficticia").responder("sistema", CONVERSA) \
        == "Não posso responder a essa pergunta."


# --- A rota do assistente: contingência local, nunca 404 com texto interno ---------

@pytest.mark.parametrize("provedor,corpo", [
    ("openai", HTML),
    ("openai", {"choices": [{"message": {"content": None, "refusal": "não"}}]}),
    ("anthropic", HTML),
    ("anthropic", _mensagem_anthropic([])),
], ids=["openai-html", "openai-content-nulo", "anthropic-html", "anthropic-vazio"])
def test_resposta_anomala_do_provedor_cai_no_modo_local(cliente, cliente_global, db,
                                                         escola_completa, monkeypatch,
                                                         provedor, corpo):
    escola_id = escola_completa["escola"].id
    _liga(cliente_global, escola_id, provedor)
    (_openai_responde if provedor == "openai" else _anthropic_responde)(monkeypatch, corpo)

    r = _sem_excecao(cliente).post(f"{API}/escolas/{escola_id}/assistente",
                                   json={"pergunta": "como está a escola?"})

    assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
    corpo_resposta = r.json()
    assert corpo_resposta["provedor"] == "local (contingência)"
    assert corpo_resposta["resposta"].strip()
    assert "Expecting value" not in r.text
    # A conversa ficou registrada, com a pergunta e a resposta do modo local.
    detalhe = cliente.get(f"{API}/escolas/{escola_id}/assistente/conversas/"
                          f"{corpo_resposta['conversa_id']}").json()
    assert [m["papel"] for m in detalhe["mensagens"]] == ["usuario", "assistente"]


def test_falha_inesperada_do_provedor_cai_no_modo_local(cliente, cliente_global, db,
                                                        escola_completa, monkeypatch):
    """Qualquer exceção do provedor externo (não só ErroProvedorIA) aciona o plano B."""
    escola_id = escola_completa["escola"].id
    _liga(cliente_global, escola_id, "openai")

    def explode(self, sistema, mensagens):
        raise RuntimeError("detalhe-interno-do-provedor")
    monkeypatch.setattr(OpenAIProvedor, "responder", explode)

    r = _sem_excecao(cliente).post(f"{API}/escolas/{escola_id}/assistente",
                                   json={"pergunta": "como está a escola?"})
    assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
    assert r.json()["provedor"] == "local (contingência)"
    assert "detalhe-interno" not in r.text


def test_erro_interno_que_nao_e_conversa_inexistente_nao_vira_404(cliente, db,
                                                                  escola_completa,
                                                                  monkeypatch):
    """Só "Conversa não encontrada" é 404. Outro ValueError (um defeito) é o 500
    genérico: não sai como 404 nem leva o texto interno para a tela."""
    escola_id = escola_completa["escola"].id

    def contexto_quebrado(db, escola_id):
        raise ValueError("texto-interno-do-defeito")
    monkeypatch.setattr(assistente, "montar_contexto", contexto_quebrado)

    r = _sem_excecao(cliente).post(f"{API}/escolas/{escola_id}/assistente",
                                   json={"pergunta": "como está a escola?"})
    assert r.status_code == 500, f"{r.status_code} {r.text[:200]}"
    assert "texto-interno" not in r.text


def test_conversa_inexistente_ou_de_outra_pessoa_continua_404(cliente, db, escola_completa):
    from app.core.security import hash_senha
    from app.models import ConversaIA, Usuario
    escola_id = escola_completa["escola"].id
    outro = Usuario(escola_id=escola_id, nome="Outra Pessoa", email="outra@t.local",
                    senha_hash=hash_senha("s3nh4abc"), cargo="coordenador")
    db.add(outro)
    db.flush()
    alheia = ConversaIA(escola_id=escola_id, usuario_id=outro.id, titulo="Alheia")
    db.add(alheia)
    db.commit()

    for conversa_id in (999_999, alheia.id):
        r = cliente.post(f"{API}/escolas/{escola_id}/assistente",
                         json={"pergunta": "e agora?", "conversa_id": conversa_id})
        assert r.status_code == 404, r.text
        assert r.json()["detail"] == "Conversa não encontrada."


# --- "Testar configuração": {ok: false}, nunca 500 ---------------------------------

def test_testar_configuracao_com_resposta_nao_json_responde_ok_false(cliente_global, db,
                                                                     escola_completa,
                                                                     monkeypatch):
    escola_id = escola_completa["escola"].id
    _liga(cliente_global, escola_id, "openai")
    _openai_responde(monkeypatch, HTML)

    r = _sem_excecao(cliente_global).post(
        f"{API}/escolas/{escola_id}/assistente/config/testar")
    assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
    assert r.json()["ok"] is False
    assert "Expecting value" not in r.text


def test_testar_configuracao_com_falha_inesperada_responde_ok_false(cliente_global, db,
                                                                    escola_completa,
                                                                    monkeypatch):
    escola_id = escola_completa["escola"].id
    _liga(cliente_global, escola_id, "openai")

    def explode(self, sistema, mensagens):
        raise RuntimeError("detalhe-interno-do-provedor")
    monkeypatch.setattr(OpenAIProvedor, "responder", explode)

    r = _sem_excecao(cliente_global).post(
        f"{API}/escolas/{escola_id}/assistente/config/testar")
    assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
    assert r.json()["ok"] is False
    assert r.json()["erro"]
    assert "detalhe-interno" not in r.text
