"""PATCH/POST /escolas: ``cidade`` e ``logotipo_url`` respeitam o tamanho da coluna
(achado da 2ª revisão de integração, contas-acesso 4).

Antes: ``Escola.cidade`` é String(120) e ``logotipo_url`` String(500), mas
``EscolaCreate``/``EscolaUpdate`` aceitavam qualquer tamanho. No PostgreSQL o valor
longo virava DataError no commit e a API respondia 500 ao admin da escola (PATCH)
e ao Admin Global (POST). Agora é 422 antes do banco, e nada é gravado. O mesmo
arquivo roda num PostgreSQL real em ``test_escola_tamanho_campos_pg.py`` (onde o
500 acontecia). Dados fictícios.
"""
import pytest
from sqlalchemy import func, select

from app.models import Escola

API = "/api/v1"


def _escola(db, escola_id: int) -> Escola:
    db.expire_all()
    return db.get(Escola, escola_id)


@pytest.mark.parametrize("corpo", [
    {"cidade": "x" * 121},
    {"logotipo_url": "x" * 501},
    # Um campo longo derruba o pedido inteiro: a cidade válida também não grava.
    {"cidade": "Cidade Ficticia", "logotipo_url": "x" * 501},
])
@pytest.mark.parametrize("quem", ["local", "global"])
def test_patch_campo_acima_da_coluna_responde_422_sem_gravar(
        db, escola_completa, cliente, cliente_global, corpo, quem):
    escola = escola_completa["escola"]
    c = cliente if quem == "local" else cliente_global
    r = c.patch(f"{API}/escolas/{escola.id}", json=corpo)
    assert r.status_code == 422, r.text
    gravada = _escola(db, escola.id)
    assert gravada.cidade is None
    assert gravada.logotipo_url is None


def test_patch_no_limite_da_coluna_grava(db, escola_completa, cliente):
    escola = escola_completa["escola"]
    cidade, logo = "C" * 120, "https://exemplo.invalid/" + "l" * (500 - 24)
    assert len(logo) == 500
    r = cliente.patch(f"{API}/escolas/{escola.id}",
                      json={"cidade": cidade, "logotipo_url": logo})
    assert r.status_code == 200, r.text
    gravada = _escola(db, escola.id)
    assert (gravada.cidade, gravada.logotipo_url) == (cidade, logo)


def test_post_cidade_acima_da_coluna_responde_422_sem_criar(db, escola_completa,
                                                            cliente_global):
    antes = db.execute(select(func.count(Escola.id))).scalar_one()
    r = cliente_global.post(f"{API}/escolas", json={
        "nome": "Escola Ficticia Nova", "cidade": "x" * 121})
    assert r.status_code == 422, r.text
    db.expire_all()
    assert db.execute(select(func.count(Escola.id))).scalar_one() == antes


def test_post_cidade_no_limite_da_coluna_cria(db, escola_completa, cliente_global):
    r = cliente_global.post(f"{API}/escolas", json={
        "nome": "Escola Ficticia Nova", "cidade": "C" * 120})
    assert r.status_code == 201, r.text
    assert _escola(db, r.json()["id"]).cidade == "C" * 120
