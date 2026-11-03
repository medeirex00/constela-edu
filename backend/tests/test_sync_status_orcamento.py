"""ORÇAMENTO de idas ao banco do GET /escolas/{id}/sync/status (e97z, 27/10).

Em produção cada instrução SQL é uma ida e volta inteira entre a API e o banco
(~195 ms medidos nos logs de 21/10, API e banco em regiões diferentes), e a tela
de Integrações relê o /status sem parar. No 34f1a23 (produção) eram 22 instruções
(~4,9 s); no 6fed992, 36 instruções e um COMMIT no meio de todo GET (~8 s com o
COMMIT, a nova conexão e a releitura da escola) — o polling da tela cancelava o
/status antes de ele voltar e o card ficava em "Carregando integrações…".

Este teste prende:
  * a leitura de REGIME (nada a gravar) em no máximo ``ORCAMENTO_REGIME``
    instruções e SEM COMMIT;
  * QUALQUER leitura (inclusive a que abre/fecha alerta ou libera a fila) abaixo
    das 22 do código em produção;
  * o COMMIT só quando a leitura gravou algo;
  * o número de instruções não cresce com o volume de dados.
A resposta continua a mesma: ``test_sync_status_dourado.py``.
"""
import pytest
from sqlalchemy import event

from tests import sync_status_cenarios as cenarios

ORCAMENTO_REGIME = 15
TETO_QUALQUER_LEITURA = 21          # < 22, o /status do 34f1a23
# Cenários cuja 1ª leitura GRAVA (alerta de frescor aberto/atualizado/fechado ou
# execução da fila cancelada); nos demais nenhuma leitura grava.
GRAVAM_NA_1A_LEITURA = {"dados_velhos", "fila_parada", "fora_do_plano"}


class Contador:
    def __init__(self, engine):
        self.engine = engine
        self.instrucoes: list[str] = []
        self.commits = 0

    def _instrucao(self, _conn, _cursor, sql, *_a):
        self.instrucoes.append(" ".join(sql.split())[:90])

    def _commit(self, _conn):
        self.commits += 1

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._instrucao)
        event.listen(self.engine, "commit", self._commit)
        return self

    def __exit__(self, *_exc):
        event.remove(self.engine, "before_cursor_execute", self._instrucao)
        event.remove(self.engine, "commit", self._commit)


def _medir(db, cliente, escola_id: int) -> Contador:
    with Contador(db.get_bind()) as contador:
        r = cliente.get(f"/api/v1/escolas/{escola_id}/sync/status")
    assert r.status_code == 200, r.text
    return contador


def _detalhe(c: Contador) -> str:
    return f"{len(c.instrucoes)} instruções, {c.commits} commit(s):\n  " + "\n  ".join(
        c.instrucoes)


@pytest.mark.parametrize("nome", list(cenarios.CENARIOS))
def test_status_cabe_no_orcamento_e_so_commita_quando_grava(
        nome, db, escola_completa, cliente_global, monkeypatch):
    cenarios.congelar(monkeypatch)
    eid = cenarios.CENARIOS[nome](db, escola_completa, monkeypatch)
    primeira = _medir(db, cliente_global, eid)
    regime = _medir(db, cliente_global, eid)
    print(f"\n[orcamento] {nome}: 1a={len(primeira.instrucoes)}/{primeira.commits} "
          f"regime={len(regime.instrucoes)}/{regime.commits}")

    for leitura in (primeira, regime):
        assert len(leitura.instrucoes) <= TETO_QUALQUER_LEITURA, _detalhe(leitura)
    # Regime: a 2ª leitura não tem nada a gravar.
    assert regime.commits == 0, "GET /status sem nada a gravar não commita\n" + _detalhe(regime)
    assert len(regime.instrucoes) <= ORCAMENTO_REGIME, _detalhe(regime)
    if nome in GRAVAM_NA_1A_LEITURA:
        assert primeira.commits >= 1, _detalhe(primeira)   # a gravação não se perde
    else:
        assert primeira.commits == 0, _detalhe(primeira)
        assert len(primeira.instrucoes) <= ORCAMENTO_REGIME, _detalhe(primeira)


def test_numero_de_instrucoes_nao_cresce_com_o_volume(monkeypatch, db, escola_completa,
                                                      cliente_global):
    cenarios.congelar(monkeypatch)
    eid = cenarios.configurada_em_dia(db, escola_completa, monkeypatch, fator=3)
    pequeno = len(_medir(db, cliente_global, eid).instrucoes)
    cenarios._volume(db, escola_completa, 6)   # mais alunos, snapshots, execuções e logs
    db.commit()
    grande = _medir(db, cliente_global, eid)
    assert len(grande.instrucoes) == pequeno, _detalhe(grande)
    assert grande.commits == 0
