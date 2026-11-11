"""Prévia da fusão: o bimestre da premiação diz o ano e se está em curso.

O DEFEITO (ALUNOS-2, PERIODOS-5, WEB-2). Na virada do ano (janeiro de 2027, escola
ainda no ano letivo 2026), ``leituras_repetidas`` devolvia como bimestre o 4º de
2026 só com número, rótulo e datas; as telas da fusão escreviam "(o bimestre
atual)" sempre que o número batia — e o 4º de 2026 já tinha acabado.

O CONSERTO: o bloco ``bimestre`` leva o ``ano`` letivo e ``atual`` (hoje está
dentro dele). A tela só diz "o bimestre atual" com ``atual``; senão escreve o
bimestre e o ano. Dados fictícios.
"""
from datetime import date, datetime

from app.models import Leitura, Livro
from app.services import alunos_fusao


def _par_com_livro_repetido(db, escola_completa):
    escola = escola_completa["escola"]
    a, b = escola_completa["alunos"][0], escola_completa["alunos"][1]
    livro = Livro(escola_id=escola.id, titulo="Livro Ficticio Virada", nivel_codigo="D")
    db.add(livro)
    db.flush()
    db.add(Leitura(escola_id=escola.id, aluno_id=a.id, livro_id=livro.id,
                   data=datetime(2026, 3, 10, 10, 0)))
    db.add(Leitura(escola_id=escola.id, aluno_id=b.id, livro_id=livro.id,
                   data=datetime(2026, 11, 20, 10, 0)))
    db.commit()
    return a.id, b.id


def test_na_virada_o_bimestre_diz_o_ano_e_que_ja_acabou(db, escola_completa):
    par = _par_com_livro_repetido(db, escola_completa)
    resumo = alunos_fusao.leituras_repetidas(db, 2026, [par], hoje=date(2027, 1, 15))[par]
    print("PREVIA NA VIRADA:", resumo["bimestre"])
    assert resumo["bimestre"] == {"numero": 4, "rotulo": "4º bimestre",
                                  "inicio": "2026-10-05", "fim": "2026-12-31",
                                  "ano": 2026, "atual": False}
    assert resumo["no_bimestre"] == 1


def test_dentro_do_bimestre_ele_e_o_atual(db, escola_completa):
    par = _par_com_livro_repetido(db, escola_completa)
    resumo = alunos_fusao.leituras_repetidas(db, 2026, [par], hoje=date(2026, 11, 25))[par]
    assert resumo["bimestre"]["numero"] == 4
    assert resumo["bimestre"]["ano"] == 2026 and resumo["bimestre"]["atual"] is True


def test_antes_do_inicio_do_ano_letivo_o_primeiro_nao_e_o_atual(db, escola_completa):
    """Janeiro, escola já no ano letivo novo: a premiação abre o 1º bimestre, que
    ainda não começou."""
    par = _par_com_livro_repetido(db, escola_completa)
    resumo = alunos_fusao.leituras_repetidas(db, 2026, [par], hoje=date(2026, 1, 20))[par]
    assert resumo["bimestre"]["numero"] == 1
    assert resumo["bimestre"]["atual"] is False


def test_rota_da_previa_leva_ano_e_atual(cliente, db, escola_completa):
    manter_id, remover_id = _par_com_livro_repetido(db, escola_completa)
    eid = escola_completa["escola"].id
    r = cliente.get(f"/api/v1/escolas/{eid}/alunos/fundir/previa",
                    params={"manter_id": manter_id, "remover_id": remover_id})
    assert r.status_code == 200, r.text
    bimestre = r.json()["leituras"]["bimestre"]
    assert bimestre["ano"] == 2026 and isinstance(bimestre["atual"], bool)
