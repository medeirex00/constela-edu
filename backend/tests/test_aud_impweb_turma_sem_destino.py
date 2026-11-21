"""Auditoria (tela de Importações): turma ambígua ou de outra etapa vai para a Revisão.

IMPORTACAO-7/REVERIFICACAO-1/IMPORTACAO-3: a tela tratava só a turma arquivada como
"sem destino"; com turma ambígua ou de outra etapa ela pré-escolhia uma turma ou
oferecia "Criar na turma do relatório" e contava a linha como importada. Aqui, as
respostas reais e o que cada corpo da tela faz no backend. Dados fictícios.
"""
import pytest

from tests.aud_impweb_exemplos import (
    _analise, _confirmar, _exemplo, _fichas, _linha, _motivos, _relatorio, _turma, _turmas,
    _turmas_do_aluno, _uma)


# --- IMPORTACAO-7, REVERIFICACAO-1, IMPORTACAO-3: turma sem destino ----------------

@pytest.mark.parametrize("caso,turmas,relatorio", [
    ("ambigua", [("3ª Série A", "3º Ano")], "3 ANO A"),
    ("ambigua_turno", [("5º Ano A Manhã", "5º Ano"), ("5º Ano A Tarde", "5º Ano")], "5º Ano A"),
])
def test_turma_ambigua_deixar_para_a_revisao_nao_cria(cliente, db, escola_completa, caso, turmas,
                                                      relatorio):
    """Mais de uma turma cadastrada para a sala: o destino padrão da tela ("Deixar para
    a Revisão") não cria ficha nem turma; a turma escolhida em "Criar aluno novo…" cria."""
    eid = escola_completa["escola"].id
    ids = [_turma(db, eid, nome, ano) for nome, ano in turmas]
    nome = f"Crianca Ficticia {caso.title()}"
    analise = _analise(cliente, eid, _uma(relatorio, nome, f"uuid-fict-{caso}"))
    corr = analise["linhas"][0]["correspondencia"]
    assert (corr["status"], corr["motivo"]) == ("revisar", "turma_ambigua"), corr
    _exemplo(f"{caso}_analise.json", analise)
    _exemplo(f"{caso}_turmas.json", _turmas(cliente, eid))
    linha = analise["linhas"][0]
    antes = _fichas(db, eid)
    revisao = _confirmar(cliente, eid, analise, [_linha(
        linha, deixar_para_revisao=True, criar_em_turma_nome=_relatorio(analise, linha))])
    assert (revisao["qtd_alunos"], revisao["qtd_revisoes"]) == (0, 1), revisao
    assert _fichas(db, eid) == antes
    assert _motivos(db, eid) == ["turma_ambigua"]
    _exemplo(f"{caso}_confirmar_revisao.json", revisao)
    _confirmar(cliente, eid, analise, [_linha(linha, criar_em_turma_id=ids[-1])])
    assert _turmas_do_aluno(db, eid, nome) == [turmas[-1][0]]


def test_turma_de_outra_etapa_so_a_turma_da_mesma_etapa_recebe(cliente, db, escola_completa):
    """A escola tem a "1ºA" da Fase (o nome que a Lista Piloto dá à "Fase 1A") e o
    relatório é do "1 ANO A": a prévia já diz "turma de outra etapa". O destino padrão
    da tela não cria; "Criar" na 1ºA da Fase também vira revisão (a tela conta como
    Revisão); numa turma do Fundamental, cria."""
    eid, t3a = escola_completa["escola"].id, escola_completa["turma"].id
    fase = _turma(db, eid, "1ºA", "1ª Fase")
    nome = "Crianca Ficticia Etapa"
    analise = _analise(cliente, eid, _uma("1 ANO A TARDE ANUAL", nome, "uuid-fict-etapa"))
    corr = analise["linhas"][0]["correspondencia"]
    assert (corr["status"], corr["motivo"]) == ("revisar", "turma_de_outra_etapa"), corr
    _exemplo("etapa_analise.json", analise)
    _exemplo("etapa_turmas.json", _turmas(cliente, eid))
    linha = analise["linhas"][0]
    antes = _fichas(db, eid)
    padrao = _confirmar(cliente, eid, analise, [_linha(
        linha, deixar_para_revisao=True, criar_em_turma_nome=_relatorio(analise, linha))])
    assert (padrao["qtd_alunos"], padrao["qtd_revisoes"]) == (0, 1), padrao
    na_fase = _confirmar(cliente, eid, analise, [_linha(linha, criar_em_turma_id=fase)])
    assert (na_fase["qtd_alunos"], na_fase["qtd_revisoes"]) == (0, 1), na_fase
    _exemplo("etapa_confirmar_na_fase.json", na_fase)
    assert _fichas(db, eid) == antes
    assert set(_motivos(db, eid)) == {"turma_de_outra_etapa"}
    _confirmar(cliente, eid, analise, [_linha(linha, criar_em_turma_id=t3a)])
    assert _turmas_do_aluno(db, eid, nome) == ["3º Ano A"]
