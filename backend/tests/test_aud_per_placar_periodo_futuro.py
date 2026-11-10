"""Placar AO VIVO do Matific: período que ainda não começou é recusado com uma frase
clara, e nenhuma data pedida passa de hoje (achado PERIODOS-4).

``aovivo.mapa_filtro`` fazia ``di, df = i.date(), min(f.date(), hoje)`` para "nunca
pedir data FUTURA", mas não conferia ``di <= df``: o "4º bimestre" escolhido em
setembro ia ao Matific como ``start_date=2026-10-05&end_date=2026-09-20`` (o mesmo
com o "Este bimestre" do recesso de janeiro, que é o 1º, e o "2º bimestre" em março).
A tela recebia o que a plataforma fizesse com isso, depois de um login e de uma
consulta à toa. E o personalizado mandava ``end_date`` no futuro, contra a mesma regra.
Dados fictícios; nenhuma plataforma real é consultada.
"""
from datetime import date

import pytest

from app.sync import aovivo
from app.sync.interfaces import ErroConector

API = "/api/v1"


@pytest.fixture(autouse=True)
def _limpar_cache():
    aovivo._cache.clear()
    yield
    aovivo._cache.clear()


@pytest.mark.parametrize("preset,hoje,comeca", [
    ("bimestre_4", date(2026, 9, 20), "05/10/2026"),   # o 4º ainda não começou
    ("bimestre", date(2026, 1, 20), "02/02/2026"),     # recesso de janeiro: "este" = o 1º
    ("bimestre_2", date(2026, 3, 10), "23/04/2026"),
])
def test_periodo_que_ainda_nao_comecou_e_recusado(preset, hoje, comeca):
    with pytest.raises(ErroConector) as exc:
        aovivo.mapa_filtro(preset, None, None, 2026, hoje)
    assert exc.value.codigo == "periodo_invalido"
    assert exc.value.recuperavel is False
    assert "ainda não começou" in str(exc.value) and comeca in str(exc.value)


def test_personalizado_que_comeca_no_futuro_e_recusado():
    with pytest.raises(ErroConector) as exc:
        aovivo.mapa_filtro("personalizado", "2026-08-01", "2026-08-31", 2026,
                           date(2026, 7, 14))
    assert exc.value.codigo == "periodo_invalido"
    assert "ainda não começou" in str(exc.value)


def test_personalizado_nunca_pede_data_futura():
    filtro, rotulo, di, df = aovivo.mapa_filtro(
        "personalizado", "2026-07-01", "2026-07-31", 2026, date(2026, 7, 14))
    assert filtro == "start_date=2026-07-01&end_date=2026-07-14"
    assert (di, df) == (date(2026, 7, 1), date(2026, 7, 14))
    assert rotulo == "01/07/2026 a 31/07/2026"            # o rótulo é o período pedido


def test_periodo_que_comeca_hoje_continua_valendo():
    filtro, *_ = aovivo.mapa_filtro("bimestre_4", None, None, 2026, date(2026, 10, 5))
    assert filtro == "start_date=2026-10-05&end_date=2026-10-05"


def test_rota_responde_400_sem_consultar_o_matific(cliente, escola_completa, monkeypatch):
    def nao_pode(*_a, **_k):
        raise AssertionError("consultou a credencial/plataforma para um período futuro")

    monkeypatch.setattr(aovivo.fuso, "hoje_local", lambda *_a, **_k: date(2026, 9, 20))
    monkeypatch.setattr(aovivo.vault, "obter_credencial", nao_pode)
    eid = escola_completa["escola"].id
    r = cliente.get(f"{API}/escolas/{eid}/sync/matific/placar-ao-vivo",
                    params={"periodo": "bimestre_4"})
    assert r.status_code == 400, r.text
    assert "ainda não começou" in r.json()["detail"]
