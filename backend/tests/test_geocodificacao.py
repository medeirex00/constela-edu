"""Geocodificação de escolas — SEM chamada externa (geocoder injetado).

Os testes automatizados nunca batem no Nominatim: passam um `geocoder` falso.
Cobrem a montagem da consulta, o caminho de sucesso, o de "não encontrada" e a
guarda de endereço insuficiente; e a correção MANUAL de coordenadas via API."""
from app.models import Escola
from app.services.geocodificacao import geocodificar_escola, montar_consulta


def test_montar_consulta_usa_endereco_cidade_uf():
    escola = Escola(nome="EM Alfa", endereco="Rua X, 10", bairro="Centro",
                    cidade="Caraguatatuba", estado="SP")
    q = montar_consulta(escola)
    assert "EM Alfa" in q and "Rua X, 10" in q and "Caraguatatuba" in q and "SP" in q
    assert q.endswith("Brasil")


def test_geocodificar_sucesso_usa_geocoder_injetado():
    escola = Escola(nome="EM Alfa", cidade="Caraguatatuba", estado="SP")
    chamado = {}
    def falso(consulta):
        chamado["q"] = consulta
        return (-23.6205, -45.4130)
    assert geocodificar_escola(escola, geocoder=falso) == (-23.6205, -45.4130)
    assert "Caraguatatuba" in chamado["q"]              # a consulta foi montada


def test_geocodificar_none_quando_nao_encontra():
    escola = Escola(nome="EM Beta", cidade="Cidade Inexistente", estado="SP")
    assert geocodificar_escola(escola, geocoder=lambda q: None) is None


def test_geocodificar_sem_cidade_nao_consulta():
    """Sem cidade, um 'Nome, Brasil' quase nunca localiza um prédio — nem chama
    o geocodificador (evita requisição inútil)."""
    escola = Escola(nome="EM Gama")
    chamou = {"n": 0}
    def espiao(q):
        chamou["n"] += 1
        return (0.0, 0.0)
    assert geocodificar_escola(escola, geocoder=espiao) is None
    assert chamou["n"] == 0


def test_correcao_manual_de_coordenadas_via_api(cliente, escola_completa):
    """PATCH /escolas/{id} (admin) grava latitude/longitude à mão."""
    escola_id = escola_completa["escola"].id
    r = cliente.patch(f"/api/v1/escolas/{escola_id}",
                      json={"latitude": -23.62, "longitude": -45.41})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["latitude"] == -23.62 and corpo["longitude"] == -45.41
