"""Provedor externo de IA com prazo curto e sem a transação do banco aberta (API_SEGURANCA-3).

* O cliente da Anthropic nasce com prazo curto (o padrão do SDK é 600 s de leitura
  e 2 novas tentativas: até ~30 min por pergunta, com a thread do worker presa). O
  prazo TOTAL de cada chamada, com servidor gotejando, está em
  ``test_aud_misc_assistente_prazo_total.py``.
* Durante a chamada de rede ao provedor externo (assistente e "Testar
  configuração"), a sessão do banco da requisição NÃO está numa transação: a
  conexão volta ao pool em vez de ficar "idle in transaction" com o INSERT da
  conversa pendente. A conversa e as mensagens são gravadas depois.

O par ``*_pg.py`` roda os mesmos testes num PostgreSQL local descartável e confere
o ``pg_stat_activity``. Nada sai para a rede. Dados fictícios."""
import time

import anthropic
import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import ConversaIA, MensagemIA
from app.services import assistente
from app.services.ia import ErroProvedorIA, provedores
from app.services.ia.base import ProvedorIA
from app.services.ia.provedores import AnthropicProvedor, OpenAIProvedor

API = "/api/v1"
CONVERSA = [{"papel": "usuario", "conteudo": "Como está a escola?"}]
_ANTHROPIC = anthropic.Anthropic  # a classe do SDK, antes de qualquer troca
_MENSAGEM_OK = {"id": "msg_ficticia", "type": "message", "role": "assistant",
                "model": "modelo-ficticio", "stop_reason": "end_turn",
                "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1},
                "content": [{"type": "text", "text": "Tudo bem."}]}


# --- Prazo dos clientes -------------------------------------------------------------

def test_cliente_anthropic_tem_prazo_curto_e_no_maximo_uma_nova_tentativa(monkeypatch):
    criados = []

    class Espiao(_ANTHROPIC):
        def __init__(self, *args, **kwargs):
            kwargs["http_client"] = httpx.Client(transport=httpx.MockTransport(
                lambda _req: httpx.Response(200, json=_MENSAGEM_OK)))
            super().__init__(*args, **kwargs)
            criados.append(self)
    monkeypatch.setattr(anthropic, "Anthropic", Espiao)

    assert AnthropicProvedor("sk-ant-ficticia").responder("sistema", CONVERSA) == "Tudo bem."

    prazo, tentativas = criados[0].timeout, criados[0].max_retries + 1
    leitura = prazo.read if isinstance(prazo, httpx.Timeout) else prazo
    conexao = prazo.connect if isinstance(prazo, httpx.Timeout) else prazo
    assert leitura <= 60 and conexao <= 10 and tentativas <= 2, (
        f"prazo de leitura {leitura} s, conexão {conexao} s, {tentativas} tentativas "
        f"=> até {leitura * tentativas} s por pergunta")


def test_openai_continua_com_prazo_curto(monkeypatch):
    restantes = []

    def cliente(limite):
        restantes.append(limite - time.monotonic())
        return httpx.Client(transport=httpx.MockTransport(lambda _req: httpx.Response(
            200, json={"choices": [{"message": {"content": "Oi."}}]})))
    monkeypatch.setattr(provedores, "_cliente_http", cliente)

    assert OpenAIProvedor("sk-ficticia").responder("sistema", CONVERSA) == "Oi."
    # O prazo TOTAL da chamada (conectar, enviar e receber), contado do início.
    assert restantes and 0 < restantes[0] <= 60


# --- Nenhuma transação aberta durante a chamada externa --------------------------

class _ExternoEspiao(ProvedorIA):
    """Provedor "externo" que anota o estado da sessão do banco da requisição no
    instante da chamada de rede. ``acao`` roda dentro da chamada (o tempo da rede)."""

    nome = "anthropic"

    def __init__(self, sessao: Session, vistos: list, falha: Exception | None = None,
                 acao=None):
        self._sessao, self._vistos, self._falha, self._acao = sessao, vistos, falha, acao

    def responder(self, sistema, mensagens):
        self._vistos.append({
            "em_transacao": self._sessao.in_transaction(),
            "pendentes": [type(o).__name__ for o in (*self._sessao.new, *self._sessao.dirty)],
            "mensagens": [m["papel"] for m in mensagens],
        })
        if self._acao:
            self._acao()
        if self._falha:
            raise self._falha
        return "Resposta do provedor externo."


def _espiar(monkeypatch, vistos, **kwargs) -> None:
    monkeypatch.setattr(assistente, "_provedor_da_escola",
                        lambda sessao, _escola_id: _ExternoEspiao(sessao, vistos, **kwargs))


def _mensagens(db, conversa_id) -> list[str]:
    db.rollback()  # lê o que as sessões da rota gravaram
    return [m.papel for m in db.execute(
        select(MensagemIA).where(MensagemIA.conversa_id == conversa_id)
        .order_by(MensagemIA.id)).scalars()]


def test_conversa_nova_sem_transacao_aberta_durante_a_chamada_externa(cliente, db,
                                                                       escola_completa,
                                                                       monkeypatch):
    escola_id = escola_completa["escola"].id
    vistos: list = []
    _espiar(monkeypatch, vistos)

    r = cliente.post(f"{API}/escolas/{escola_id}/assistente", json={"pergunta": "resumo"})

    assert r.status_code == 200, r.text
    assert vistos and vistos[0]["em_transacao"] is False, f"durante a chamada: {vistos}"
    assert vistos[0]["pendentes"] == []
    corpo = r.json()
    assert corpo["provedor"] == "anthropic"
    assert corpo["resposta"] == "Resposta do provedor externo."
    # Depois da chamada, a conversa e as duas mensagens ficam gravadas.
    assert _mensagens(db, corpo["conversa_id"]) == ["usuario", "assistente"]
    assert db.get(ConversaIA, corpo["conversa_id"]).provedor == "anthropic"


def test_conversa_continuada_sem_transacao_aberta_e_com_o_historico(cliente, db,
                                                                     escola_completa,
                                                                     monkeypatch):
    escola_id = escola_completa["escola"].id
    vistos: list = []
    _espiar(monkeypatch, vistos)
    primeira = cliente.post(f"{API}/escolas/{escola_id}/assistente",
                            json={"pergunta": "resumo"}).json()

    r = cliente.post(f"{API}/escolas/{escola_id}/assistente",
                     json={"pergunta": "e os alertas?",
                           "conversa_id": primeira["conversa_id"]})

    assert r.status_code == 200, r.text
    assert r.json()["conversa_id"] == primeira["conversa_id"]
    assert vistos[1]["em_transacao"] is False, f"durante a chamada: {vistos[1]}"
    # O histórico da conversa foi junto com a pergunta nova.
    assert vistos[1]["mensagens"] == ["usuario", "assistente", "usuario"]
    assert _mensagens(db, primeira["conversa_id"]) == ["usuario", "assistente"] * 2


def test_contingencia_tambem_sem_transacao_aberta(cliente, db, escola_completa,
                                                  monkeypatch):
    escola_id = escola_completa["escola"].id
    vistos: list = []
    _espiar(monkeypatch, vistos, falha=ErroProvedorIA("provedor fora do ar"))

    r = cliente.post(f"{API}/escolas/{escola_id}/assistente", json={"pergunta": "resumo"})

    assert r.status_code == 200, r.text
    assert vistos[0]["em_transacao"] is False, f"durante a chamada: {vistos}"
    assert r.json()["provedor"] == "local (contingência)"
    assert _mensagens(db, r.json()["conversa_id"]) == ["usuario", "assistente"]


def test_conversa_apagada_durante_a_chamada_externa_responde_404(cliente, db,
                                                                 escola_completa,
                                                                 monkeypatch):
    """Sem a transação aberta, a conversa pode sumir enquanto o provedor responde
    (retenção, exclusão da conta): 404, não 500 nem mensagem órfã."""
    escola_id = escola_completa["escola"].id
    vistos: list = []
    _espiar(monkeypatch, vistos)
    conversa_id = cliente.post(f"{API}/escolas/{escola_id}/assistente",
                               json={"pergunta": "resumo"}).json()["conversa_id"]

    def apagar():
        with Session(db.get_bind()) as outra:
            outra.execute(delete(ConversaIA).where(ConversaIA.id == conversa_id))
            outra.commit()
    _espiar(monkeypatch, vistos, acao=apagar)

    r = cliente.post(f"{API}/escolas/{escola_id}/assistente",
                     json={"pergunta": "e agora?", "conversa_id": conversa_id})

    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "Conversa não encontrada."
    assert _mensagens(db, conversa_id) == []


def test_testar_configuracao_sem_transacao_aberta_durante_a_chamada(cliente_global, db,
                                                                   escola_completa,
                                                                   monkeypatch):
    escola_id = escola_completa["escola"].id
    vistos: list = []
    _espiar(monkeypatch, vistos)

    r = cliente_global.post(f"{API}/escolas/{escola_id}/assistente/config/testar")

    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert vistos and vistos[0]["em_transacao"] is False, f"durante a chamada: {vistos}"


def test_modo_local_continua_gravando_a_conversa(cliente, db, escola_completa):
    """O modo local (padrão) não chama a rede: segue como antes, conversa gravada."""
    escola_id = escola_completa["escola"].id
    r = cliente.post(f"{API}/escolas/{escola_id}/assistente", json={"pergunta": "resumo"})
    assert r.status_code == 200, r.text
    assert r.json()["provedor"] == "local"
    assert _mensagens(db, r.json()["conversa_id"]) == ["usuario", "assistente"]
