"""DESEMPENHO-2 (insights): o ``/insights`` lê configuração, contrato e coorte UMA vez por
requisição, não uma vez por serviço.

A rota chama ``series_e_dificuldade``, ``_alunos_com_leituras``, ``indices_da_escola`` e
``alertas_da_escola`` em separado; cada serviço abria o próprio bloco
``scoring.leituras_da_requisicao``, e a configuração da escola, o contrato da rede e a
coorte saíam do banco uma vez em cada um (cada ida custa ~0,2 s em produção). Com o bloco
na rota (que só lê), os serviços reaproveitam a memória dela. Dados fictícios.
"""
import collections

from tests.test_aud2_motor_consultas_repetidas import _medir, cenario  # noqa: F401


def test_insights_nao_repete_leitura_do_motor(db, cenario):  # noqa: F811
    escola_id = cenario["escola"].id
    idas = _medir(db, cenario["coordenacao"], f"/escolas/{escola_id}/insights")
    print(f"\n[coordenacao] /insights: {idas.resumo()}")
    repetidas = {sql[:120]: n for (sql, _p), n in collections.Counter(idas.comandos).items()
                 if n > 1 and "FROM escolas" not in sql}
    assert not repetidas, repetidas


def test_insights_do_professor_tambem(db, cenario):  # noqa: F811
    escola_id = cenario["escola"].id
    idas = _medir(db, cenario["professora"], f"/escolas/{escola_id}/insights")
    repetidas = {sql[:120]: n for (sql, _p), n in collections.Counter(idas.comandos).items()
                 if n > 1 and "FROM escolas" not in sql}
    assert not repetidas, repetidas
