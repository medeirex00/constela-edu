"""O exemplo da pontuação não abre o acervo da escola para a Secretaria (REV3-PLAT-1).

O S_G_GRUPO-2 fechou o ``GET /escolas/{id}/livros`` para a Secretaria: o acervo nasce
da coleta, a partir das leituras das crianças, e numa escola em que só 1 (ou 2)
crianças leram ele é o histórico de leitura delas. Mas o "Quer ver um exemplo?" da
pontuação (``GET .../configuracoes/pontuacao/exemplo/elefante?livro_id=K``) devolvia
em ``entrada`` o título e o nível de cada livro do acervo — os ids são sequenciais, e
o livro de outra escola dá 404: varrer ``livro_id`` dava a lista do que a única
leitora leu.

Agora a forma ``livro_id`` é 403 para a Secretaria (em qualquer id, sem dizer se o
livro existe); por nível e pelo catálogo oficial (``elefante_id``) o exemplo segue
aberto a ela. A coordenação da escola e o Admin Global seguem com o exemplo pelo
acervo. Dados fictícios (o cenário é o de ``test_aud3_plat_livros_secretaria``).
"""
import pytest
from sqlalchemy import select

from app.models import Livro
from app.services import dificuldade_livro
from tests.test_aud3_plat_livros_secretaria import API, _escola_com_leitoras, _login


def _url(escola_id: int) -> str:
    return f"{API}/escolas/{escola_id}/configuracoes/pontuacao/exemplo/elefante"


def _ids_do_acervo(db, escola_id: int) -> list[int]:
    return sorted(db.execute(select(Livro.id).where(
        Livro.escola_id == escola_id)).scalars().all())


@pytest.mark.parametrize("email", ["sec.coord@catalogo.local", "sec.admin@catalogo.local"])
def test_secretaria_nao_varre_o_acervo_pelo_exemplo(db, escola_completa, email):
    cena = _escola_com_leitoras(db, escola_completa, 1)
    ids = _ids_do_acervo(db, cena["escola_id"])
    assert len(ids) == 37
    sec = _login(email)
    url = _url(cena["escola_id"])
    # Todos os livros do acervo e um id que não existe: a mesma recusa (sem oráculo).
    for livro_id in [*ids, ids[-1] + 1000]:
        r = sec.get(url, params={"serie": "4", "livro_id": livro_id})
        assert r.status_code == 403, (
            f"a Secretaria abriu o livro {livro_id} do acervo pelo exemplo: "
            f"{r.status_code} {r.text[:300]}")
        assert "TITULO INVENTADO" not in r.text and "entrada" not in r.json()
        assert "acervo" in r.json()["detail"], r.text


@pytest.mark.parametrize("email", ["sec.coord@catalogo.local", "sec.admin@catalogo.local"])
def test_secretaria_segue_com_o_exemplo_por_nivel_e_pelo_catalogo_oficial(
        db, escola_completa, email):
    cena = _escola_com_leitoras(db, escola_completa, 1)
    sec = _login(email)
    url = _url(cena["escola_id"])
    r = sec.get(url, params={"serie": "4", "nivel": "D"})
    assert r.status_code == 200, r.text
    assert r.json()["entrada"]["origem"] == "nivel"
    oficiais = dificuldade_livro.catalogo().por_id
    if oficiais:
        eid = next(iter(oficiais))
        r = sec.get(url, params={"serie": "4", "elefante_id": eid})
        assert r.status_code == 200, r.text
        assert r.json()["entrada"]["origem"] == "catalogo"


@pytest.mark.parametrize("email", ["coord@catalogo.local", "global@catalogo.local"])
def test_coordenacao_e_admin_global_seguem_com_o_exemplo_pelo_acervo(db, escola_completa,
                                                                     email):
    cena = _escola_com_leitoras(db, escola_completa, 1)
    primeiro = _ids_do_acervo(db, cena["escola_id"])[0]
    r = _login(email).get(_url(cena["escola_id"]),
                          params={"serie": "4", "livro_id": primeiro})
    assert r.status_code == 200, r.text
    entrada = r.json()["entrada"]
    assert (entrada["origem"], entrada["titulo"]) == ("acervo", "TITULO INVENTADO 00")
