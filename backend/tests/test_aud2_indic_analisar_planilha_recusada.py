"""Regressão P-UPLOADS-4 (pendência deixada pela fase B): ``POST /avaliacoes/analisar``
com a planilha inflada.

Desde a guarda única de planilha inflada, ``analisar_planilha`` recusa o arquivo com
``ImportacaoRecusada`` ANTES de abri-lo ("... Nada foi gravado."). As rotas ``/importar``
e ``/importar-preset`` já devolviam essa recusa como 400; ``/analisar`` não a capturava
e respondia 500 ("Erro interno"), e a tela não mostrava o motivo. Tudo fictício e em
memória.
"""
import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import Usuario
from tests.test_planilha_inflada import MB, _xlsx_celula_gigante


@pytest.fixture()
def cliente_global(db) -> TestClient:
    db.add(Usuario(nome="Admin Fictício", email="admin.ficticio@exemplo.invalido",
                   senha_hash=hash_senha("s3nh4-ficticia"), cargo="admin", is_global=True))
    db.commit()
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post("/api/v1/auth/login", data={"username": "admin.ficticio@exemplo.invalido",
                                           "password": "s3nh4-ficticia"})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def test_analisar_planilha_inflada_responde_400_com_o_motivo(cliente_global):
    bomba = _xlsx_celula_gigante(40 * MB)            # < 100 KB enviados
    r = cliente_global.post(
        "/api/v1/avaliacoes/analisar",
        files={"arquivo": ("resultado_ficticio.xlsx", bomba,
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 400, (r.status_code, r.text)
    assert "Nada foi gravado" in r.json()["detail"]


def test_analisar_planilha_comum_continua_mostrando_a_grade(cliente_global):
    csv = "Resultado fictício\nCO_ESCOLA;IDEB\n35099901;5,1\n".encode("utf-8")
    r = cliente_global.post("/api/v1/avaliacoes/analisar",
                            files={"arquivo": ("ficticio.csv", csv, "text/csv")})
    assert r.status_code == 200, r.text
    assert r.json()["primeiras_linhas"][2] == ["35099901", "5,1"]
