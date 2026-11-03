"""Assistente de IA: ligar o provedor EXTERNO é só do Admin Global (A1 / P9).

Antes, o admin DA ESCOLA gravava no ``PUT /escolas/{id}/assistente/config`` o
provedor ``anthropic``/``openai`` com chave própria e passava a mandar o contexto
pseudonimizado das crianças (turmas, notas, índices, alertas) para servidores
fora do país, sem passar pelo Admin Global. Agora (decisão técnica análoga ao D7,
declarada ao dono como P9):

* ligar, reconfigurar (modelo) ou gravar a chave de um provedor externo exige o
  Admin Global (403 aos demais, ANTES de gravar: nada muda);
* o admin da escola continua VENDO o estado (``GET /config`` e ``/status``, sem a
  chave) e pode DESLIGAR, salvando o provedor ``local`` (sem rede) — que ele já
  podia salvar — e isso descarta a chave gravada;
* coordenação e Secretaria seguem sem gravar nada (como antes).

Dados fictícios.
"""
import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models import Configuracao, LogAuditoria

API = "/api/v1"


def _url(escola_id: int) -> str:
    return f"{API}/escolas/{escola_id}/assistente/config"


def _linha(db, escola_id: int) -> Configuracao | None:
    db.expire_all()
    return db.execute(select(Configuracao).where(
        Configuracao.escola_id == escola_id,
        Configuracao.namespace == "assistente")).scalar_one_or_none()


@pytest.mark.parametrize("corpo", [
    {"provedor": "anthropic", "api_key": "sk-ant-ficticia-1"},
    {"provedor": "openai", "api_key": "sk-openai-ficticia-1"},
    {"provedor": "anthropic"},                          # sem chave: 403, não 400
    {"provedor": "openai", "modelo": "gpt-ficticio"},
    {"provedor": "local", "api_key": "sk-ant-ficticia-2"},  # chave só pelo global
])
def test_admin_da_escola_nao_liga_provedor_externo_nem_grava_chave(
        cliente, db, escola_completa, corpo):
    escola_id = escola_completa["escola"].id
    r = cliente.put(_url(escola_id), json=corpo)
    assert r.status_code == 403, r.text
    assert "exclusivo do Admin Global" in r.json()["detail"]
    # Nada gravado e nada auditado como configurado.
    assert _linha(db, escola_id) is None
    assert db.query(LogAuditoria).filter_by(
        acao="assistente.configurado", escola_id=escola_id).count() == 0
    assert cliente.get(_url(escola_id)).json() == {
        "provedor": "local", "modelo": "", "chave_definida": False}


def test_admin_da_escola_salva_o_modo_local(cliente, db, escola_completa):
    """O provedor `local` (sem rede) continua permitido a quem já podia."""
    escola_id = escola_completa["escola"].id
    r = cliente.put(_url(escola_id), json={"provedor": "local", "api_key": "  "})
    assert r.status_code == 200, r.text
    assert r.json() == {"provedor": "local", "modelo": "", "chave_definida": False}


def test_global_liga_e_a_escola_ve_o_estado_e_desliga(
        cliente, cliente_global, db, escola_completa):
    escola_id = escola_completa["escola"].id
    url = _url(escola_id)
    ligado = cliente_global.put(url, json={"provedor": "anthropic",
                                           "api_key": "sk-ant-ficticia-3"})
    assert ligado.status_code == 200, ligado.text
    trilha = db.query(LogAuditoria).filter_by(
        acao="assistente.configurado", escola_id=escola_id).one()
    assert trilha.detalhes == {"provedor": "anthropic", "chave_alterada": True}

    # O admin da escola VÊ o estado (sem a chave)...
    lido = cliente.get(url)
    assert lido.status_code == 200
    assert lido.json() == {"provedor": "anthropic", "modelo": "", "chave_definida": True}
    assert "sk-ant" not in lido.text
    status = cliente.get(f"{API}/escolas/{escola_id}/assistente/status")
    assert status.status_code == 200 and status.json()["provedor"] == "anthropic"

    # ...não reconfigura o provedor externo do global (modelo, nem mantendo a chave)...
    for corpo in ({"provedor": "anthropic", "modelo": "claude-ficticio"},
                  {"provedor": "anthropic"},
                  {"provedor": "openai", "api_key": "sk-openai-ficticia-2"}):
        assert cliente.put(url, json=corpo).status_code == 403, corpo
    linha = _linha(db, escola_id)
    assert linha.valor["provedor"] == "anthropic" and linha.valor["modelo"] == ""
    assert linha.valor.get("api_key_cifrada")

    # ...e DESLIGA: volta ao modo local e a chave gravada é descartada.
    desligado = cliente.put(url, json={"provedor": "local"})
    assert desligado.status_code == 200, desligado.text
    assert desligado.json() == {"provedor": "local", "modelo": "", "chave_definida": False}
    linha = _linha(db, escola_id)
    assert linha.valor["provedor"] == "local"
    assert "api_key_cifrada" not in linha.valor
    assert db.query(LogAuditoria).filter_by(
        acao="assistente.configurado", escola_id=escola_id).count() == 2

    # Religar continua sendo só do global (a chave antiga não volta sozinha).
    assert cliente.put(url, json={"provedor": "anthropic"}).status_code == 403
    sem_chave = cliente_global.put(url, json={"provedor": "anthropic"})
    assert sem_chave.status_code == 400


def test_escola_que_herda_provedor_externo_do_ambiente_pode_desligar(
        cliente, db, escola_completa, monkeypatch):
    """Sem configuração própria, a escola espelha o AMBIENTE (AI_PROVIDER, decisão
    de quem opera o servidor). O admin da escola vê isso e pode desligar só a dele."""
    monkeypatch.setattr(settings, "AI_PROVIDER", "anthropic")
    monkeypatch.setattr(settings, "AI_API_KEY", "sk-ant-ambiente-ficticia")
    escola_id = escola_completa["escola"].id
    url = _url(escola_id)
    assert cliente.get(url).json() == {
        "provedor": "anthropic", "modelo": "", "chave_definida": True}
    assert cliente.put(url, json={"provedor": "local"}).status_code == 200
    assert cliente.get(url).json()["provedor"] == "local"
    from app.services import assistente
    assert assistente._provedor_da_escola(db, escola_id).nome == "local"


def test_coordenacao_segue_sem_gravar(db, escola_completa):
    from fastapi.testclient import TestClient

    from app.core.security import hash_senha
    from app.main import app
    from app.models import Usuario

    escola_id = escola_completa["escola"].id
    db.add(Usuario(escola_id=escola_id, nome="Coord Ficticia", email="coord.ia@teste.local",
                   senha_hash=hash_senha("s3nh4"), cargo="coordenador"))
    db.commit()
    c = TestClient(app)
    token = c.post(f"{API}/auth/login",
                   data={"username": "coord.ia@teste.local", "password": "s3nh4"}).json()
    c.headers["Authorization"] = f"Bearer {token['access_token']}"
    for corpo in ({"provedor": "local"}, {"provedor": "anthropic", "api_key": "x-ficticia"}):
        assert c.put(_url(escola_id), json=corpo).status_code == 403, corpo
    assert _linha(db, escola_id) is None
