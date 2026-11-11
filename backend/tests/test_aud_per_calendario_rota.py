"""A web lê o calendário oficial dos bimestres do BACKEND (auditoria PERIODOS-7 e
RELATORIOS-6).

Antes, ``apps/web/src/lib/calendarioBimestres.ts`` tinha só 2026 fixo: de 2027 em
diante o certificado da plataforma (individual e em lote) abria no "1º bimestre"
dizendo "pelo calendário oficial" e MANDAVA esse número ao backend — mesmo com o
calendário de 2027 cadastrado em ``BIMESTRES_CALENDARIO``, que a web nunca via.

A rota ``GET /escolas/{id}/configuracoes/calendario-bimestres?ano=`` devolve o
calendário da MESMA fonte que o backend usa (``services/bimestres.calendario``):
a constante de 2026, a variável de ambiente para os anos novos e ``null`` para
ano sem calendário — nunca o mapa por mês aproximado, que a tela não pode chamar de
oficial. Datas fictícias.
"""
import json
import pathlib
import re

import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import Escola, Rede, Usuario
from app.services import bimestres

_EXEMPLO_2027 = [["2027-02-01", "2027-04-23"], ["2027-04-26", "2027-07-09"],
                 ["2027-07-26", "2027-10-01"], ["2027-10-04", "2027-12-17"]]


@pytest.fixture(autouse=True)
def _calendario_limpo(monkeypatch):
    monkeypatch.delenv(bimestres.VARIAVEL_CALENDARIO, raising=False)
    bimestres._ler_calendario.cache_clear()
    yield
    bimestres._ler_calendario.cache_clear()


def _url(escola_id: int, ano: int | None = None) -> str:
    sufixo = f"?ano={ano}" if ano is not None else ""
    return f"/api/v1/escolas/{escola_id}/configuracoes/calendario-bimestres{sufixo}"


def _login(email: str) -> TestClient:
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", data={"username": email, "password": "s3nh4"})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def test_2026_vem_da_constante_oficial(cliente, escola_completa):
    r = cliente.get(_url(escola_completa["escola"].id, 2026))
    assert r.status_code == 200, r.text
    assert r.json() == {"ano": 2026, "bimestres": [
        {"numero": 1, "inicio": "2026-02-02", "fim": "2026-04-22"},
        {"numero": 2, "inicio": "2026-04-23", "fim": "2026-07-23"},
        {"numero": 3, "inicio": "2026-07-24", "fim": "2026-10-04"},
        {"numero": 4, "inicio": "2026-10-05", "fim": "2026-12-31"},
    ]}


def test_ano_sem_calendario_e_null_nunca_o_mapa_por_mes(cliente, escola_completa):
    r = cliente.get(_url(escola_completa["escola"].id, 2027))
    assert r.status_code == 200, r.text
    assert r.json() == {"ano": 2027, "bimestres": None}


def test_ano_cadastrado_na_variavel_chega_a_web(cliente, escola_completa, monkeypatch):
    monkeypatch.setenv(bimestres.VARIAVEL_CALENDARIO, json.dumps({"2027": _EXEMPLO_2027}))
    r = cliente.get(_url(escola_completa["escola"].id, 2027))
    assert r.status_code == 200, r.text
    assert r.json()["bimestres"] == [
        {"numero": n, "inicio": i, "fim": f} for n, (i, f) in enumerate(_EXEMPLO_2027, 1)]


def test_sem_ano_e_o_ano_de_hoje_em_brasilia(cliente, escola_completa, monkeypatch):
    from datetime import date

    from app.routers import configuracoes
    monkeypatch.setattr(configuracoes, "hoje_br", lambda: date(2027, 10, 15))
    monkeypatch.setenv(bimestres.VARIAVEL_CALENDARIO, json.dumps({"2027": _EXEMPLO_2027}))
    r = cliente.get(_url(escola_completa["escola"].id))
    assert r.status_code == 200, r.text
    assert r.json()["ano"] == 2027
    assert r.json()["bimestres"][3] == {"numero": 4, "inicio": "2027-10-04", "fim": "2027-12-17"}


@pytest.mark.parametrize("ano", [1999, 2101, "dois-mil"])
def test_ano_fora_da_faixa_e_422(cliente, escola_completa, ano):
    r = cliente.get(f"{_url(escola_completa['escola'].id)}?ano={ano}")
    assert r.status_code == 422, r.text


def test_quem_le_a_escola_le_o_calendario_e_outra_escola_nao(db, escola_completa):
    """Professor (menu, Ranking) e Secretaria (rede da escola) leem; usuário de
    outra escola, não. Sem token, 401."""
    escola = escola_completa["escola"]
    rede = Rede(nome="Rede Ficticia", status="ativa")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    outra = Escola(nome="Outra Escola Ficticia", status="ativa")
    db.add(outra)
    db.flush()
    db.add_all([
        Usuario(escola_id=escola.id, nome="Prof", email="prof@cal.local",
                senha_hash=hash_senha("s3nh4"), cargo="professor"),
        Usuario(escola_id=escola.id, nome="Secretaria", email="sec@cal.local",
                senha_hash=hash_senha("s3nh4"), cargo="coordenador", rede_id=rede.id),
        Usuario(escola_id=outra.id, nome="Coord de fora", email="fora@cal.local",
                senha_hash=hash_senha("s3nh4"), cargo="coordenador"),
    ])
    db.commit()

    assert _login("prof@cal.local").get(_url(escola.id, 2026)).status_code == 200
    assert _login("sec@cal.local").get(_url(escola.id, 2026)).status_code == 200
    assert _login("fora@cal.local").get(_url(escola.id, 2026)).status_code == 403
    assert TestClient(app).get(_url(escola.id, 2026)).status_code == 401


def test_copia_de_2026_da_web_e_a_mesma_do_backend():
    """A web guarda 2026 só para a primeira pintura (antes de a rota responder): se
    alguém mexer num lado só, isto cai."""
    fonte = (pathlib.Path(__file__).resolve().parents[2] / "apps" / "web" / "src" / "lib"
             / "calendarioBimestres.ts").read_text(encoding="utf-8")
    bloco = fonte[fonte.index("const EMBUTIDO_2026"):]
    bloco = bloco[:bloco.index("};")]
    copia = [{"numero": int(n), "inicio": i, "fim": f} for n, i, f in re.findall(
        r'numero:\s*(\d),\s*inicio:\s*"([\d-]+)",\s*fim:\s*"([\d-]+)"', bloco)]
    assert "ano: 2026" in bloco
    assert copia == bimestres.calendario_publico(2026)
