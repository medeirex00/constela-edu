"""Placar AO VIVO do Matific: depois de remover ou trocar a credencial, o ranking da
conta antiga (nomes e posições de crianças) nunca volta à tela.

O cache curto de resultado é POR PROCESSO e era consultado ANTES de conferir a
credencial: o ``invalidar_cache`` do DELETE/PUT só limpa o processo que atendeu o
pedido, e uma consulta que já estava em andamento gravava o resultado DEPOIS da
remoção. Resultado: até 60 s de "200 cache" com a conta removida no outro worker e,
com uma consulta em andamento, também no mesmo. A sessão (cookies) salva no fim de uma
consulta em andamento tinha o mesmo furo: gravada depois da troca da credencial, a
consulta seguinte entrava no Matific com a conta antiga.

Agora o cache e a sessão levam o carimbo da credencial lida no INÍCIO da consulta, e
só valem para a mesma credencial. Sem credencial, nada do cache é servido.

Dados 100% fictícios; sem rede (a coleta é substituída e o login também).
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.sync import aovivo, connectors, service
from app.sync.interfaces import ResultadoValidacao

API = "/api/v1"


@pytest.fixture(autouse=True)
def _limpar_cache():
    aovivo._cache.clear()
    yield
    aovivo._cache.clear()


class _ConectorFicticio:
    """Valida qualquer login (o PUT da credencial) e passa na conferência do placar
    (que exige ``coletar_via_http``); a coleta em si é substituída no teste."""

    async def testar_credenciais(self, cred, ctx):
        return ResultadoValidacao(True, "ok", "ok")

    def coletar_via_http(self, *a, **k):  # pragma: no cover - substituída
        raise AssertionError("substituída")


def _linhas_da_conta(usuario: str) -> list[dict]:
    return [{"nome": f"Crianca Ficticia Da {usuario}", "turma": None, "serie": "3",
             "estrelas": 50, "atividades": 5}]


@pytest.fixture()
def placar(cliente, escola_completa, monkeypatch):
    """Escola com a credencial ``conta-antiga`` salva pela tela e a coleta do Placar
    substituída: cada consulta devolve uma linha que diz de qual conta veio."""
    eid = escola_completa["escola"].id
    monkeypatch.setitem(connectors._REGISTRO, "matific", _ConectorFicticio())
    monkeypatch.setattr(service, "disparar_em_thread", lambda _id: None)
    estado = {"coletas": [], "durante": None}

    def _coleta(conector, cred, contexto, sessao, filtro):
        estado["coletas"].append({"conta": cred.usuario, "sessao": sessao})
        durante, estado["durante"] = estado["durante"], None
        if durante is not None:
            durante()                    # outro pedido chega no meio da consulta
        return _linhas_da_conta(cred.usuario), {
            "cookies": [{"name": "sessionid", "value": f"sessao-{cred.usuario}"}]}

    monkeypatch.setattr(aovivo, "_coletar_http_first", _coleta)
    r = cliente.put(f"{API}/escolas/{eid}/sync/credenciais/matific",
                    json={"usuario": "conta-antiga", "senha": "senha-ficticia"})
    assert r.status_code == 200 and r.json()["ok"] is True, r.text
    return {"eid": eid, "cliente": cliente, "estado": estado}


def _get(p, **extra):
    return p["cliente"].get(f"{API}/escolas/{p['eid']}/sync/matific/placar-ao-vivo",
                            params={"periodo": "semana", **extra})


def _nomes(r) -> list[str]:
    return [i["nome"] for i in r.json()["itens"]]


def _em_outro_processo(monkeypatch):
    """O DELETE/PUT cai no OUTRO worker: o ``invalidar_cache`` não roda neste."""
    monkeypatch.setattr(aovivo, "invalidar_cache", lambda *_a, **_k: None)


def test_credencial_removida_em_outro_worker_nao_serve_o_ranking_em_cache(
        placar, monkeypatch):
    r1 = _get(placar)
    assert r1.status_code == 200 and _nomes(r1) == ["Crianca Ficticia Da conta-antiga"]

    _em_outro_processo(monkeypatch)
    rd = placar["cliente"].delete(f"{API}/escolas/{placar['eid']}/sync/credenciais/matific")
    assert rd.status_code == 204

    r2 = _get(placar)
    # Antes: 200 com "cache": true e a criança da conta removida, por até 60 s.
    assert r2.status_code == 400, r2.text
    assert "não estão configuradas" in r2.json()["detail"]


def test_credencial_trocada_em_outro_worker_consulta_a_conta_nova(placar, monkeypatch):
    r1 = _get(placar)
    assert _nomes(r1) == ["Crianca Ficticia Da conta-antiga"]

    _em_outro_processo(monkeypatch)
    rp = placar["cliente"].put(
        f"{API}/escolas/{placar['eid']}/sync/credenciais/matific",
        json={"usuario": "conta-nova", "senha": "outra-senha-ficticia"})
    assert rp.status_code == 200, rp.text

    r2 = _get(placar)
    assert r2.status_code == 200, r2.text
    # Antes: o ranking da conta antiga, marcado "cache".
    assert r2.json()["cache"] is False
    assert _nomes(r2) == ["Crianca Ficticia Da conta-nova"]
    assert [c["conta"] for c in placar["estado"]["coletas"]] == ["conta-antiga", "conta-nova"]


def test_consulta_em_andamento_durante_a_remocao_nao_enche_o_cache(placar):
    """Mesmo worker: o DELETE (com o ``invalidar_cache`` de verdade) chega enquanto a
    consulta da conta antiga ainda roda; ela termina depois e gravava o cache."""
    outro = TestClient(app)
    outro.headers.update(placar["cliente"].headers)
    url = f"{API}/escolas/{placar['eid']}/sync/credenciais/matific"

    def _remover():
        assert outro.delete(url).status_code == 204

    placar["estado"]["durante"] = _remover
    r1 = _get(placar)
    assert r1.status_code == 200          # começou antes da remoção: responde a ela
    assert _nomes(r1) == ["Crianca Ficticia Da conta-antiga"]

    for _ in range(2):
        r = _get(placar)
        # Antes: 200 "cache" com a criança da conta removida por mais 60 s.
        assert r.status_code == 400, r.text
        assert "não estão configuradas" in r.json()["detail"]


def test_sessao_da_conta_antiga_gravada_depois_da_troca_nao_e_reaproveitada(placar):
    """A consulta em andamento termina DEPOIS do PUT da conta nova (que esquece a
    sessão) e grava os cookies da conta antiga; a consulta seguinte entrava no Matific
    com eles (o HTTP direto devolveria o Placar da conta antiga como se fosse o novo)."""
    outro = TestClient(app)
    outro.headers.update(placar["cliente"].headers)
    url = f"{API}/escolas/{placar['eid']}/sync/credenciais/matific"

    def _trocar():
        r = outro.put(url, json={"usuario": "conta-nova", "senha": "outra-senha-ficticia"})
        assert r.status_code == 200, r.text

    placar["estado"]["durante"] = _trocar
    assert _get(placar, forcar="true").status_code == 200

    r2 = _get(placar, forcar="true")
    assert r2.status_code == 200, r2.text
    segunda = placar["estado"]["coletas"][1]
    assert segunda["conta"] == "conta-nova"
    # Antes: {"cookies": [{"name": "sessionid", "value": "sessao-conta-antiga"}]}.
    assert segunda["sessao"] is None

    # A sessão gravada pela conta nova continua sendo reaproveitada por ela.
    assert _get(placar, forcar="true").status_code == 200
    terceira = placar["estado"]["coletas"][2]
    assert terceira["sessao"]["cookies"][0]["value"] == "sessao-conta-nova"
