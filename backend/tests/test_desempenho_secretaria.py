"""Desempenho das telas da Secretaria — o NÚMERO de consultas ao banco (em produção a API fica a
~195 ms do banco por consulta), sem mudar nenhum número.

* o painel da rede e os destaques leem os cartões das escolas em poucas consultas, as mesmas
  para qualquer número de escolas (antes: 22 e 21);
* a análise da escola só com as avaliações (``com_plataformas=False``, a ficha e a comparação
  da Secretaria) é a análise completa sem o bloco das plataformas;
* as leituras repetidas dos indicadores oficiais saem do banco uma vez dentro de
  ``leituras_da_requisicao`` e são as mesmas da consulta direta; fora dele, nada muda.

Dados INVENTADOS (``test_analise_base``; decisão D13).
"""
from sqlalchemy import event

from app.services import rede as svc_rede
from app.services.analise import escola as svc_escola
from app.services.indicadores import leituras_da_requisicao as leituras
from tests.test_analise_base import HOJE, mundo_indicadores, mundo_plataformas, nova_escola


class _Contador:
    def __init__(self, db):
        self.engine, self.n = db.get_bind(), 0

    def _conta(self, *_a, **_k):
        self.n += 1

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._conta)
        return self

    def __exit__(self, *_exc):
        event.remove(self.engine, "before_cursor_execute", self._conta)


def _consultas(db, funcao) -> int:
    db.expire_all()
    with _Contador(db) as c:
        funcao()
    return c.n


def test_painel_e_destaques_com_o_mesmo_numero_de_consultas_para_qualquer_rede(db):
    base = mundo_plataformas(db)
    rede = base["rede"]
    rid = rede.id                       # (lido antes: o expire_all do teste o recarregaria)
    antes = {s: (_consultas(db, lambda s=s: svc_rede.dashboard_rede(db, rid, secretaria=s)),
                 _consultas(db, lambda s=s: svc_rede.destaques_rede(db, rid, secretaria=s)))
             for s in (True, False)}
    for i in range(5):
        nova_escola(db, rede, f"EMEF Fictícia Extra {i}", f"359901{70 + i}")
    db.commit()
    depois = {s: (_consultas(db, lambda s=s: svc_rede.dashboard_rede(db, rid, secretaria=s)),
                  _consultas(db, lambda s=s: svc_rede.destaques_rede(db, rid, secretaria=s)))
              for s in (True, False)}
    print(f"\npainel e destaques: {antes} -> com mais 5 escolas {depois} consultas")
    assert antes == depois
    # escolas, módulos e as DUAS leituras dos cartões (o painel junta as notas pendentes)
    assert all(painel <= 4 and destaques <= 4 for painel, destaques in depois.values())


def test_analise_so_das_avaliacoes_e_a_completa_sem_as_plataformas(db):
    base = mundo_plataformas(db)
    for escola in base["escolas"].values():
        for escopo in (True, False):
            completa = svc_escola.analise_da_escola(db, escola, hoje=HOJE, escopo_rede=escopo)
            n_completa = _consultas(db, lambda e=escola, x=escopo: svc_escola.analise_da_escola(
                db, e, hoje=HOJE, escopo_rede=x))
            n_so = _consultas(db, lambda e=escola, x=escopo: svc_escola.analise_da_escola(
                db, e, hoje=HOJE, escopo_rede=x, com_plataformas=False))
            so = svc_escola.analise_da_escola(db, escola, hoje=HOJE, escopo_rede=escopo,
                                              com_plataformas=False)
            assert so == {**completa, "plataformas": None}
            assert n_so < n_completa                     # a escola não é medida


def test_leituras_da_requisicao_sao_as_da_consulta_direta(db):
    base = mundo_indicadores(db)
    codigo = base["imps"]["ica"].codigo_territorio_alvo
    direto = (leituras.avaliacao(db, "saresp"), leituras.avaliacao(db, "nao_existe"),
              sorted(i.id for i in leituras.aplicadas_do_territorio(db, codigo, ("seduc_iee",))),
              sorted(e.id for e in leituras.escolas_da_rede(db, base["rede"].id)))
    with leituras.leituras_da_requisicao(db):
        with _Contador(db) as c:
            lote = (leituras.avaliacao(db, "saresp"), leituras.avaliacao(db, "nao_existe"),
                    sorted(i.id for i in leituras.aplicadas_do_territorio(db, codigo,
                                                                         ("seduc_iee",))),
                    sorted(e.id for e in leituras.escolas_da_rede(db, base["rede"].id)))
            for _ in range(3):                           # repetidas: da memória
                leituras.avaliacao(db, "ideb")
                leituras.aplicadas_do_territorio(db, codigo, ("inep_ideb_escolas",))
                leituras.escolas_da_rede(db, base["rede"].id)
        assert c.n == 3                                  # catálogo, importações, escolas
    assert lote == direto
    with _Contador(db) as c:                             # fora do bloco: consulta direta
        leituras.avaliacao(db, "saresp")
        leituras.avaliacao(db, "saresp")
    assert c.n == 2


def test_rede_muito_grande_le_os_ramos_um_a_um_com_o_mesmo_resultado(db, monkeypatch):
    """Acima do teto de parâmetros por comando (o PostgreSQL aceita 65.535; cada valor de um
    IN é um), os ramos vão um a um, com o mesmo SQL: a resposta é a mesma."""
    base = mundo_plataformas(db)
    rid = base["rede"].id
    juntos = [svc_rede.dashboard_rede(db, rid, secretaria=s) for s in (True, False)]
    juntos += [svc_rede.destaques_rede(db, rid, secretaria=s) for s in (True, False)]
    monkeypatch.setattr(svc_rede, "_TETO_PARAMETROS", 0)
    um_a_um = [svc_rede.dashboard_rede(db, rid, secretaria=s) for s in (True, False)]
    um_a_um += [svc_rede.destaques_rede(db, rid, secretaria=s) for s in (True, False)]
    assert um_a_um == juntos


def test_analise_so_das_avaliacoes_valida_o_periodo_como_a_completa(db):
    import pytest

    from app.services.analise import AnaliseInvalida
    base = mundo_plataformas(db)
    escola = next(iter(base["escolas"].values()))
    for pedido in ({"preset": "nao_existe"},
                   {"preset": "personalizado", "inicio": HOJE.replace(year=1800), "fim": HOJE}):
        with pytest.raises(AnaliseInvalida) as completa:
            svc_escola.analise_da_escola(db, escola, hoje=HOJE, **pedido)
        with pytest.raises(AnaliseInvalida) as so:
            svc_escola.analise_da_escola(db, escola, hoje=HOJE, com_plataformas=False, **pedido)
        assert (str(so.value), so.value.status) == (str(completa.value), completa.value.status)
