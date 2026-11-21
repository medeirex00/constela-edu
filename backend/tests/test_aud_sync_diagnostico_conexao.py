"""O diagnóstico do Elefante solta a transação (e a conexão do pool) ANTES de rodar
o robô (login + sondagem, até 180 s) — a regra do módulo, a mesma do placar ao
vivo do Matific, da coleta (``service._executar_reivindicada``) e do "Testar
conexão". Antes, a requisição lia a credencial e segurava a conexão "idle in
transaction" durante toda a I/O externa. Dados fictícios; conector falso, nenhum
acesso externo.
"""
from app.core.database import get_db
from app.main import app
from app.sync import aovivo, connectors, vault
from app.sync.interfaces import Credenciais


def _espiar_sessoes(monkeypatch) -> list:
    sessoes = []
    anterior = app.dependency_overrides[get_db]

    def _get_db_espiao():
        for s in anterior():
            sessoes.append(s)
            yield s
    monkeypatch.setitem(app.dependency_overrides, get_db, _get_db_espiao)
    return sessoes


def test_diagnostico_nao_segura_a_transacao_durante_a_coleta(db, cliente, escola_completa,
                                                            monkeypatch):
    eid = escola_completa["escola"].id
    vault.salvar_credencial(db, eid, "elefante", Credenciais(usuario="u", senha="p"))
    db.commit()
    sessoes = _espiar_sessoes(monkeypatch)
    visto = {}

    class _Conector:
        async def diagnosticar_endpoints(self, cred, contexto):
            visto["transacao_aberta"] = [s.in_transaction() for s in sessoes]
            visto["credencial"] = (cred.usuario, cred.senha)
            return {"ok": True, "endpoints": [{"nome": "a", "estrutura": "{x:num}"}]}

    monkeypatch.setattr(connectors, "obter",
                        lambda plat: _Conector() if plat == "elefante" else None)
    r = cliente.post(f"/api/v1/escolas/{eid}/sync/elefante/diagnostico")
    assert r.status_code == 200, r.text
    assert visto["transacao_aberta"] == [False], (
        "a requisição do diagnóstico segura a transação (e a conexão do pool) "
        "durante toda a coleta no Elefante")
    # A credencial decifrada chegou ao robô e o inventário foi gravado depois.
    assert visto["credencial"] == ("u", "p")
    assert r.json()["diff"]["primeira_vez"] is True
    r2 = cliente.post(f"/api/v1/escolas/{eid}/sync/elefante/diagnostico")
    assert r2.status_code == 200 and r2.json()["anterior_em"], r2.text


def test_controle_placar_ao_vivo_solta_a_transacao_antes_da_coleta(db, cliente, escola_completa,
                                                                   monkeypatch):
    """Controle: o placar ao vivo do Matific já solta a conexão antes da I/O."""
    eid = escola_completa["escola"].id
    vault.salvar_credencial(db, eid, "matific", Credenciais(usuario="u", senha="p"))
    db.commit()
    sessoes = _espiar_sessoes(monkeypatch)
    visto = {}

    def _coletar(conector, cred, contexto, estado, filtro):
        visto["transacao_aberta"] = [s.in_transaction() for s in sessoes]
        return [], None
    monkeypatch.setattr(aovivo, "_coletar_http_first", _coletar)
    cliente.get(f"/api/v1/escolas/{eid}/sync/matific/placar-ao-vivo?periodo=mes")
    assert visto.get("transacao_aberta") == [False]
