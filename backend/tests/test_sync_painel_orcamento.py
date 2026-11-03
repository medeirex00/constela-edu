"""ORÇAMENTO de idas ao banco do GET /sync/dashboard (painel global; e97x, 28/10).

Em produção cada instrução SQL é uma ida e volta inteira entre a API e o banco
(~195 ms: API na Califórnia, banco em São Paulo), e a tela de Integrações do admin
global relê o painel a cada ciclo do polling. No 34f1a23 (produção) o painel tinha
12 instruções, fixas. No 7440226/6251075, com os pré-requisitos do agendador e a
trava de contrato, passou a crescer com o número de agendas: 25/56/194 instruções
para 0/5/28 escolas com agenda vencida — o contrato da rede relido por agenda
vencida (``escolas_desatualizadas`` → ``plataforma_no_plano``), a credencial
relida por agenda (``_v_credenciais_legiveis``), as colunas da tabela de execuções
lidas duas vezes e um ``count`` por execução com recálculo pendente. Com 28 agendas
vencidas são ~38 s, acima do timeout de 15 s do ``useApi``: o painel não carrega.

Este teste prende:
  * no máximo ``ORCAMENTO`` instruções por leitura, SEM COMMIT, com 0, 5 ou 28
    escolas de agenda vencida (escolas de rede e avulsas);
  * o número de instruções não cresce com o número de agendas vencidas, nem com o
    que não é agenda (execuções presas, recálculos pendentes, escolas sem agenda).
A resposta continua a mesma: ``test_sync_painel_dourado.py``.
"""
import pytest

from tests import sync_painel_cenarios as cenarios
from tests.test_sync_status_orcamento import Contador, _detalhe

ORCAMENTO = 15


def _medir(db, cliente) -> Contador:
    with Contador(db.get_bind()) as contador:
        r = cliente.get("/api/v1/sync/dashboard")
    assert r.status_code == 200, r.text
    return contador


@pytest.mark.parametrize("vencidas", [0, 5, 28])
def test_painel_cabe_no_orcamento_e_nao_commita(vencidas, db, escola_completa,
                                                 cliente_global, monkeypatch):
    cenarios.congelar(monkeypatch)
    cenarios.mundo(db, escola_completa, vencidas=vencidas)
    for leitura in (_medir(db, cliente_global), _medir(db, cliente_global)):
        print(f"\n[orcamento-painel] vencidas={vencidas}: {len(leitura.instrucoes)} "
              f"instruções, {leitura.commits} commit(s)")
        assert len(leitura.instrucoes) <= ORCAMENTO, _detalhe(leitura)
        assert leitura.commits == 0, "o painel só lê\n" + _detalhe(leitura)


def test_numero_de_instrucoes_nao_cresce_com_agendas_nem_extras(db, escola_completa,
                                                                cliente_global, monkeypatch):
    cenarios.congelar(monkeypatch)
    cenarios.mundo(db, escola_completa, vencidas=5, n_escolas=6)
    pequeno = _medir(db, cliente_global)
    # Mais 22 escolas com agenda (as 22 vencidas, de rede e avulsas) e o triplo do
    # que não é agenda (presas, recálculos pendentes, escolas sem agenda).
    cenarios._extras(db, cenarios._rede(db, "Rede Ficticia Extra"), 3)
    from app.models import Escola
    novas = [Escola(nome=f"Escola Ficticia Nova {i:02d}", ano_letivo_ativo=2026)
             for i in range(22)]
    db.add_all(novas)
    db.flush()
    for i, escola in enumerate(novas):
        for j, plat in enumerate(("elefante", "matific")):
            cenarios._cred(db, escola.id, plat, legivel=i % 4 != 1)
            cenarios._agenda(db, escola.id, plat, i)
            cenarios._execucao(db, escola.id, plat, "concluida",
                               horas=24 * 12 + i * 0.1 + j * 0.05, qtd_alunos=2)
    db.commit()
    grande = _medir(db, cliente_global)
    print(f"\n[orcamento-painel] pequeno={len(pequeno.instrucoes)} grande={len(grande.instrucoes)}")
    assert len(grande.instrucoes) == len(pequeno.instrucoes), (
        _detalhe(pequeno) + "\n---\n" + _detalhe(grande))
    assert grande.commits == 0
