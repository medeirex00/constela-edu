"""DESEMPENHO-2 (ficha da escola relida): a rota por escola não relê a ficha da escola que
a dependência ``escola_autorizada`` acabou de ler.

O identity map do SQLAlchemy guarda referência FRACA: a Escola lida pela dependência era
descartada quando ela devolvia só o ``int``, e o ``db.get(Escola, escola_id)`` da rota
fazia o mesmo SELECT de novo — a única repetição que sobrava em /sincronizacao, no mural,
no ranking de evolução e no /insights (uma ida a mais, ~0,2 s em produção, em toda rota
por escola). Agora a dependência guarda a ficha na sessão da requisição. Dados fictícios.
"""
import collections

import pytest

from tests.test_aud2_motor_consultas_repetidas import _medir, cenario  # noqa: F401


@pytest.mark.parametrize("perfil,rota", [
    ("coordenacao", "/escolas/{id}/sincronizacao"),
    ("professora", "/escolas/{id}/sincronizacao"),
    ("coordenacao", "/escolas/{id}/gamificacao/mural"),
    ("coordenacao", "/escolas/{id}/ranking-evolucao"),
    ("coordenacao", "/escolas/{id}/insights"),
    ("coordenacao", "/escolas/{id}/dashboard"),
])
def test_a_ficha_da_escola_sai_do_banco_uma_vez(db, cenario, perfil, rota):  # noqa: F811
    idas = _medir(db, cenario[perfil], rota.format(id=cenario["escola"].id))
    da_escola = collections.Counter((sql, p) for sql, p in idas.comandos
                                    if "FROM escolas" in sql)
    assert max(da_escola.values(), default=0) <= 1, idas.resumo()


def test_a_escola_alterada_por_outra_sessao_e_relida_depois_do_commit(
        db, cliente, cliente_global, escola_completa):
    """A referência forte não congela a ficha: a mudança gravada por outra requisição
    aparece na seguinte (cada requisição tem a sua sessão; o commit expira os objetos)."""
    eid = escola_completa["escola"].id
    assert cliente.get(f"/api/v1/escolas/{eid}/dashboard").status_code == 200
    r = cliente_global.patch(f"/api/v1/escolas/{eid}", json={"nome": "Escola Ficticia Renomeada"})
    assert r.status_code == 200, r.text
    nomes = [e["nome"] for e in cliente.get("/api/v1/escolas").json()]
    assert "Escola Ficticia Renomeada" in nomes
