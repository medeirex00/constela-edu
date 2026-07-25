"""Geocodificação de escolas (lat/long via OSM).

Serviço: montagem da consulta, geocoder INJETÁVEL (os testes nunca batem na
rede), e o lote que preenche/conta. Endpoint /redes/{id}/geocodificar: só admin
global, processa em lotes (idempotente — só as sem coordenada, salvo ?forcar).
"""
import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import Escola, Rede, Usuario
from app.services import geocodificacao as svc


# --- Serviço (sem app, geocoder falso) --------------------------------------

def test_montar_consulta_usa_campos_preenchidos():
    e = Escola(nome="EM Centro", cidade="Caraguatatuba", estado="SP")
    assert svc.montar_consulta(e) == "EM Centro, Caraguatatuba, SP, Brasil"
    # Campos vazios são ignorados (sem vírgulas duplas).
    assert svc.montar_consulta(Escola(nome="EM X")) == "EM X, Brasil"


def test_geocodificar_escola_exige_cidade():
    # Sem cidade, "Nome, Brasil" quase nunca localiza um prédio → nem chama o geocoder.
    chamou = []
    svc.geocodificar_escola(Escola(nome="EM X"), geocoder=lambda q: chamou.append(q) or (1.0, 2.0))
    assert chamou == []


def test_geocodificar_escola_chama_geocoder_com_a_consulta():
    e = Escola(nome="EM Centro", cidade="Caraguatatuba", estado="SP")
    vistos = []

    def fake(q):
        vistos.append(q)
        return (-23.6, -45.4)

    assert svc.geocodificar_escola(e, geocoder=fake) == (-23.6, -45.4)
    assert vistos == ["EM Centro, Caraguatatuba, SP, Brasil"]


def test_geocodificar_lote_preenche_coords_e_conta():
    achavel = Escola(nome="A", cidade="Caraguatatuba")
    nao_achavel = Escola(nome="B", cidade="Nárnia")
    sem_cidade = Escola(nome="C")

    def fake(q):
        return (-23.6, -45.4) if "Caraguatatuba" in q else None

    res = svc.geocodificar_lote([achavel, nao_achavel, sem_cidade], fake, intervalo=0)
    assert res == {"encontradas": 1, "falhas": 2}
    assert (achavel.latitude, achavel.longitude) == (-23.6, -45.4)
    assert nao_achavel.latitude is None and sem_cidade.latitude is None


class _FakeResp:
    def __init__(self, data, ok=True):
        self._data, self._ok = data, ok

    def raise_for_status(self):
        if not self._ok:
            raise RuntimeError("HTTP 500")

    def json(self):
        return self._data


def test_nominatim_nunca_levanta_e_valida_a_resposta(monkeypatch):
    """O geocodificador REAL: contrato 'nunca levanta' e as validações — sem rede
    (monkeypatch de httpx.get). Cobre feliz, vazio, chave faltando, fora de faixa,
    HTTP 500 e exceção de conexão."""
    def com(resp_ou_erro):
        def _get(*a, **k):
            if isinstance(resp_ou_erro, Exception):
                raise resp_ou_erro
            return resp_ou_erro
        monkeypatch.setattr(svc.httpx, "get", _get)

    com(_FakeResp([{"lat": "-23.6", "lon": "-45.4"}]))
    assert svc._nominatim("q") == (-23.6, -45.4)
    com(_FakeResp([]))                                      # sem resultado
    assert svc._nominatim("q") is None
    com(_FakeResp([{"lat": "-23.6"}]))                     # chave faltando
    assert svc._nominatim("q") is None
    com(_FakeResp([{"lat": "999", "lon": "-45.4"}]))       # latitude fora de faixa
    assert svc._nominatim("q") is None
    com(_FakeResp(None, ok=False))                         # HTTP 500
    assert svc._nominatim("q") is None
    com(ConnectionError("rede caiu"))                      # exceção de conexão
    assert svc._nominatim("q") is None


# --- Endpoint (app + geocoder falso via dependency_overrides) ---------------

def _login(email, senha):
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", data={"username": email, "password": senha})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


@pytest.fixture()
def geocoder_falso():
    """Sobrescreve o geocodificador real por um falso (achavel só em Caraguá) e
    zera o intervalo (sem sleep). Limpa os overrides ao fim."""
    def fake(consulta):
        return (-23.62, -45.41) if "Caraguatatuba" in consulta else None
    app.dependency_overrides[svc.get_geocoder] = lambda: fake
    app.dependency_overrides[svc.get_intervalo_geocode] = lambda: 0.0
    yield fake
    app.dependency_overrides.pop(svc.get_geocoder, None)
    app.dependency_overrides.pop(svc.get_intervalo_geocode, None)


def _rede_com_escolas(db, cidades):
    rede = Rede(nome="Rede Geo", status="ativa")
    db.add(rede)
    db.flush()
    escolas = []
    for i, cidade in enumerate(cidades):
        e = Escola(nome=f"EM {i}", ano_letivo_ativo=2026, status="ativa",
                   rede_id=rede.id, cidade=cidade, estado="SP")
        db.add(e)
        escolas.append(e)
    db.commit()
    return rede, escolas


def _root(db):
    db.add(Usuario(nome="Root", email="root@constela.local",
                   senha_hash=hash_senha("s3nh4rootglobal"), cargo="admin", is_global=True))
    db.commit()
    return _login("root@constela.local", "s3nh4rootglobal")


def test_geocodifica_a_rede_localizando_so_o_que_tem_cidade_valida(db, geocoder_falso):
    rede, escolas = _rede_com_escolas(db, ["Caraguatatuba", "Nárnia", None])
    root = _root(db)

    r = root.post(f"/api/v1/redes/{rede.id}/geocodificar")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["processadas"] == 3
    assert corpo["encontradas"] == 1
    assert corpo["falhas"] == 2
    assert corpo["restantes"] == 0
    assert corpo["ultimo_id"] == escolas[2].id  # cursor parou na última escola por id

    db.expire_all()
    achavel = db.get(Escola, escolas[0].id)
    assert (achavel.latitude, achavel.longitude) == (-23.62, -45.41)
    assert db.get(Escola, escolas[1].id).latitude is None  # cidade inexistente
    assert db.get(Escola, escolas[2].id).latitude is None  # sem cidade


def test_geocodificar_e_idempotente_pula_quem_ja_tem_coord(db, geocoder_falso):
    rede, escolas = _rede_com_escolas(db, ["Caraguatatuba"])
    escolas[0].latitude, escolas[0].longitude = 1.0, 2.0  # já posicionada
    db.commit()
    root = _root(db)

    r = root.post(f"/api/v1/redes/{rede.id}/geocodificar").json()
    assert r["processadas"] == 0 and r["restantes"] == 0  # nada a fazer
    db.expire_all()
    assert db.get(Escola, escolas[0].id).latitude == 1.0  # não sobrescreveu

    # Com ?forcar re-geocodifica mesmo quem já tinha.
    r2 = root.post(f"/api/v1/redes/{rede.id}/geocodificar?forcar=true").json()
    assert r2["processadas"] == 1 and r2["encontradas"] == 1
    db.expire_all()
    assert db.get(Escola, escolas[0].id).latitude == -23.62


def test_geocodificar_processa_em_lotes_com_cursor(db, geocoder_falso):
    rede, _ = _rede_com_escolas(db, ["Caraguatatuba"] * 3)
    root = _root(db)
    r = root.post(f"/api/v1/redes/{rede.id}/geocodificar?limite=2").json()
    assert r["processadas"] == 2 and r["restantes"] == 1
    # 2ª chamada avança pelo cursor (ultimo_id) — pega só a que sobrou.
    r2 = root.post(
        f"/api/v1/redes/{rede.id}/geocodificar?limite=2&depois_de={r['ultimo_id']}").json()
    assert r2["processadas"] == 1 and r2["restantes"] == 0


def test_geocodificar_avanca_sobre_nao_localizaveis(db, geocoder_falso):
    """REGRESSÃO (achado da revisão): o cursor tem de AVANÇAR mesmo quando uma
    escola falha no OSM — senão o lote trava nas falhas, martela o serviço e
    nunca alcança as escolas seguintes. Rede: achável, NÃO-achável, achável."""
    rede, escolas = _rede_com_escolas(db, ["Caraguatatuba", "Nárnia", "Caraguatatuba"])
    root = _root(db)

    # Simula o laço do frontend: lotes de 1, avançando o cursor até restantes==0.
    depois_de = 0
    passos = 0
    while True:
        r = root.post(
            f"/api/v1/redes/{rede.id}/geocodificar?limite=1&depois_de={depois_de}").json()
        depois_de = r["ultimo_id"]
        passos += 1
        if r["processadas"] == 0 or r["restantes"] <= 0:
            break
        assert passos < 10  # converge (não repete a falha infinitamente)

    db.expire_all()
    # A 3ª escola (achável, DEPOIS da falha) foi geocodificada — o cursor passou
    # da não-localizável em vez de travar nela.
    assert db.get(Escola, escolas[0].id).latitude is not None
    assert db.get(Escola, escolas[1].id).latitude is None   # não-localizável, tentada e pulada
    assert db.get(Escola, escolas[2].id).latitude is not None
    assert passos == 3  # cada escola vista exatamente uma vez


def test_geocodificar_exige_admin_global(db, geocoder_falso):
    rede, _ = _rede_com_escolas(db, ["Caraguatatuba"])
    db.add(Usuario(nome="Coord", email="c@x.local", senha_hash=hash_senha("s3nh4coordddd"),
                   cargo="admin", escola_id=None))
    db.commit()
    cliente = _login("c@x.local", "s3nh4coordddd")
    assert cliente.post(f"/api/v1/redes/{rede.id}/geocodificar").status_code == 403


def test_geocodificar_rede_inexistente_404(db, geocoder_falso):
    root = _root(db)
    assert root.post("/api/v1/redes/9999/geocodificar").status_code == 404
