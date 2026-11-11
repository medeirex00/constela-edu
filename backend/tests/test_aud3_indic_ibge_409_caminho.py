"""A recusa (409) do código IBGE de outra rede aponta um caminho que existe na tela —
revisão REV3-INDIC-4. Ela manda "tirar o código da outra rede", e a Gestão de redes passou
a editar e limpar o código IBGE da rede escolhida (antes, nenhuma tela fazia isso). Tudo
SINTÉTICO: o município 3599999 não existe.
"""
URL = "/api/v1/redes"
MUN = "3599999"


def test_409_do_ibge_diz_onde_tirar_o_codigo_e_o_vazio_limpa(cliente_global):
    norte = cliente_global.post(URL, json={"nome": "Rede Inventada Norte", "uf": "SP",
                                           "codigo_ibge": MUN})
    assert norte.status_code == 201, norte.text
    sul = cliente_global.post(URL, json={"nome": "Rede Inventada Sul", "uf": "SP"}).json()

    r = cliente_global.patch(f"{URL}/{sul['id']}", json={"codigo_ibge": MUN})
    assert r.status_code == 409, r.text
    assert "Gestão de redes" in r.json()["detail"], r.json()["detail"]
    assert "Rede Inventada Norte" in r.json()["detail"]

    # O caminho da tela: tirar (PATCH com "") o código da outra rede libera o código.
    limpa = cliente_global.patch(f"{URL}/{norte.json()['id']}", json={"codigo_ibge": ""})
    assert limpa.status_code == 200 and limpa.json()["codigo_ibge"] is None
    r = cliente_global.patch(f"{URL}/{sul['id']}", json={"codigo_ibge": MUN})
    assert r.status_code == 200 and r.json()["codigo_ibge"] == MUN
