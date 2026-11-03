"""ORÇAMENTO de idas ao banco de escola DE REDE: o GET /sync/status e o POST
/sync/agora custam o MESMO que na escola avulsa (e97x, 28/10).

No 6251075 a trava de contrato (``plataforma_no_plano`` → ``modulos_da_rede``)
relia ``modulos_rede`` uma vez por plataforma com agenda no /status — 16 idas na
escola de rede contra 14 na avulsa, medidas no fio com PostgreSQL (~3,16 s contra
~2,77 s a ~195 ms por ida) — e o /agora relia a escola (o objeto carregado pela
autorização da rota já tinha saído do mapa de identidade) e depois o contrato: 1
ida a mais que a avulsa, ao criar e ao reaproveitar. Pertencer a uma rede é o
caso das escolas de Caraguatatuba.

O contrato agora vem na MESMA consulta que já lê a escola (/status) ou numa
consulta só que junta escola e contrato (/agora). A resposta continua a mesma:
``test_sync_rede_dourado.py``.
"""
import pytest

from app.models.sincronizacao import SincronizacaoExecucao
from tests import sync_status_cenarios as cenarios
from tests.test_sync_rede_dourado import na_rede, pedir_agora, preparar_agora
from tests.test_sync_status_orcamento import Contador, _detalhe


def _status(db, cliente, eid: int) -> Contador:
    with Contador(db.get_bind()) as contador:
        r = cliente.get(f"/api/v1/escolas/{eid}/sync/status")
    assert r.status_code == 200, r.text
    contador.json = r.json()
    return contador


@pytest.mark.parametrize("nome", list(cenarios.CENARIOS))
def test_status_de_rede_custa_o_mesmo_que_o_da_avulsa(nome, db, escola_completa,
                                                       cliente_global, monkeypatch):
    """Em regime (nada a gravar): a mesma escola, avulsa e numa rede que contratou
    tudo, faz o mesmo número de instruções e diz a mesma coisa."""
    cenarios.congelar(monkeypatch)
    eid = cenarios.CENARIOS[nome](db, escola_completa, monkeypatch)
    na_rede(db, eid, "avulsa")
    _status(db, cliente_global, eid)                 # a 1ª leitura pode gravar
    avulsa = _status(db, cliente_global, eid)
    na_rede(db, eid, "rede_toda")
    rede = _status(db, cliente_global, eid)
    print(f"\n[orcamento-rede] status {nome}: avulsa={len(avulsa.instrucoes)} "
          f"rede={len(rede.instrucoes)}")
    assert avulsa.commits == rede.commits == 0, _detalhe(rede)
    assert len(rede.instrucoes) == len(avulsa.instrucoes), (
        _detalhe(avulsa) + "\n--- rede ---\n" + _detalhe(rede))
    assert rede.json == avulsa.json


def test_status_de_rede_sem_um_modulo_nao_paga_ida_a_mais(db, escola_completa,
                                                          cliente_global, monkeypatch):
    """Rede SEM Matemática (o alerta do Matific foi fechado na 1ª leitura): em
    regime, o mesmo número de instruções da avulsa em dia."""
    cenarios.congelar(monkeypatch)
    eid = cenarios.fora_do_plano(db, escola_completa, monkeypatch)
    _status(db, cliente_global, eid)
    rede = _status(db, cliente_global, eid)
    na_rede(db, eid, "avulsa")
    cenarios._execucao(db, eid, "matific", "concluida", horas=2, qtd_alunos=3)
    db.commit()
    _status(db, cliente_global, eid)
    avulsa = _status(db, cliente_global, eid)
    print(f"\n[orcamento-rede] status sem_matematica: avulsa={len(avulsa.instrucoes)} "
          f"rede={len(rede.instrucoes)}")
    assert rede.commits == avulsa.commits == 0
    assert len(rede.instrucoes) == len(avulsa.instrucoes), (
        _detalhe(avulsa) + "\n--- rede ---\n" + _detalhe(rede))


def _agora(db, cliente, eid: int) -> Contador:
    with Contador(db.get_bind()) as contador:
        r = pedir_agora(cliente, eid)
    assert r.status_code == 200, r.text
    return contador


def _concluir_ativas(db, eid: int) -> None:
    for ex in db.query(SincronizacaoExecucao).filter(
            SincronizacaoExecucao.escola_id == eid,
            SincronizacaoExecucao.status.in_(("fila", "executando"))):
        ex.status = "concluida"
        ex.finalizada_em = cenarios.AGORA
    db.commit()


def test_agora_de_rede_custa_o_mesmo_que_o_da_avulsa(db, escola_completa, cliente_global,
                                                     monkeypatch):
    """Ao CRIAR as duas execuções e ao REAPROVEITAR as ativas: a escola de rede faz
    o mesmo número de instruções (e de commits) que a avulsa."""
    eid = preparar_agora(db, escola_completa, monkeypatch, "cria_e_reaproveita")
    cria_avulsa = _agora(db, cliente_global, eid)
    reaproveita_avulsa = _agora(db, cliente_global, eid)
    _concluir_ativas(db, eid)
    na_rede(db, eid, "rede_toda")
    cria_rede = _agora(db, cliente_global, eid)
    reaproveita_rede = _agora(db, cliente_global, eid)
    print(f"\n[orcamento-rede] agora: cria avulsa={len(cria_avulsa.instrucoes)} "
          f"rede={len(cria_rede.instrucoes)}; reaproveita avulsa="
          f"{len(reaproveita_avulsa.instrucoes)} rede={len(reaproveita_rede.instrucoes)}")
    for avulsa, rede in ((cria_avulsa, cria_rede), (reaproveita_avulsa, reaproveita_rede)):
        assert len(rede.instrucoes) == len(avulsa.instrucoes), (
            _detalhe(avulsa) + "\n--- rede ---\n" + _detalhe(rede))
        assert rede.commits == avulsa.commits == 1
