"""Auditoria (tela de Importações): o aluno novo nasce na turma que a prévia disse.

IMPORTACAO-1: a tela adivinhava a turma pelo nome (``acharTurmaPorNome`` casava a
letra "a" dentro de "ano"/"fase") e mandava criar a criança do "1 ANO A" na "1º Ano B"
ou na "1ª Fase A". Agora ela usa a turma da correspondência. Aqui, as respostas reais
que os testes da tela usam e o que o corpo da tela faz no backend. Dados fictícios.
"""
import pytest

from tests.aud_impweb_exemplos import (
    API, _analise, _confirmar, _exemplo, _linha, _placar, _relatorio, _turma, _turmas,
    _turmas_do_aluno, _uma)


# --- IMPORTACAO-1: a turma do aluno novo é a que o backend decidiu ------------------

def test_turma_nova_a_crianca_do_1_ano_a_nasce_na_1a_nova(cliente, db, escola_completa):
    """A escola tem "1º Ano B" e não tem a 1ºA. A tela mandava criar na "1º Ano B" (o
    "a" de "ano"); agora "Criar na turma do relatório", com o nome dele."""
    eid = escola_completa["escola"].id
    _turma(db, eid, "1º Ano B", "1º Ano")
    analise = _analise(cliente, eid, _uma("1 ANO A", "Crianca Ficticia Umbelina", "uuid-fict-1a"))
    corr = analise["linhas"][0]["correspondencia"]
    assert (corr["status"], corr["turma_id"], corr["turma_nova"]) == ("nao_encontrado", None, "1ºA")
    _exemplo("turma_nova_analise.json", analise)
    _exemplo("turma_nova_turmas.json", _turmas(cliente, eid))
    linha = analise["linhas"][0]
    _confirmar(cliente, eid, analise, [_linha(linha, criar_em_turma_nome=_relatorio(analise, linha))])
    assert _turmas_do_aluno(db, eid, "Crianca Ficticia Umbelina") == ["1ºA"]


def test_fase_a_crianca_do_1_ano_a_nao_nasce_na_fase(cliente, db, escola_completa):
    """A escola só tem a "1ª Fase A" (Educação Infantil): a criança do "1 ANO A" nasce
    numa 1ºA nova do Fundamental, não na Fase."""
    eid = escola_completa["escola"].id
    _turma(db, eid, "1ª Fase A", "1ª Fase")
    analise = _analise(cliente, eid, _uma("1 ANO A", "Crianca Ficticia Primeiro Ano",
                                          "uuid-fict-1ano"))
    corr = analise["linhas"][0]["correspondencia"]
    assert (corr["status"], corr["turma_id"], corr["turma_nova"]) == ("nao_encontrado", None, "1ºA")
    _exemplo("fase_analise.json", analise)
    _exemplo("fase_turmas.json", _turmas(cliente, eid))
    linha = analise["linhas"][0]
    _confirmar(cliente, eid, analise, [_linha(linha, criar_em_turma_nome=_relatorio(analise, linha))])
    assert _turmas_do_aluno(db, eid, "Crianca Ficticia Primeiro Ano") == ["1ºA"]


def test_aplicar_cada_crianca_nova_ja_vem_com_a_turma_dela(cliente, db, escola_completa):
    """Placar da escola sem turma no topo: cada linha traz a sua ("4º Ano B"), e a
    prévia diz a turma cadastrada de cada criança nova — a tela manda criar nela."""
    eid = escola_completa["escola"].id
    t4b = _turma(db, eid, "4º Ano B", "4º Ano")
    analise = _analise(cliente, eid, _placar(None, [
        {"nome": "Crianca Ficticia Quarto Um", "turma": "4º Ano B", "uuid": "uuid-fict-4b1",
         "estrelas": 5, "atividades": 1},
        {"nome": "Crianca Ficticia Quarto Dois", "turma": "4º Ano B", "uuid": "uuid-fict-4b2",
         "estrelas": 6, "atividades": 2}]))
    assert [(l["correspondencia"]["status"], l["correspondencia"]["turma_id"])
            for l in analise["linhas"]] == [("nao_encontrado", t4b)] * 2
    _exemplo("aplicar_analise.json", analise)
    _exemplo("aplicar_turmas.json", _turmas(cliente, eid))
    _confirmar(cliente, eid, analise, [_linha(l, criar_em_turma_id=t4b) for l in analise["linhas"]])
    assert _turmas_do_aluno(db, eid, "Crianca Ficticia Quarto Um") == ["4º Ano B"]
    assert _turmas_do_aluno(db, eid, "Crianca Ficticia Quarto Dois") == ["4º Ano B"]


# --- IMPORTACAO-1 no lote: relatório individual -----------------------------------

@pytest.mark.parametrize("caso,turma_pdf", [("lote_turma_nova", "1 ANO A"),
                                            ("lote_turma_cadastrada", "3 ANO A")])
def test_lote_relatorio_individual_turma_da_previa(cliente, db, escola_completa, caso,
                                                   turma_pdf):
    """Relatório individual de uma criança sem ficha. Sem a 1ºA no cadastro (só a "1º
    Ano B"), a prévia diz a turma nova — o lote não pode criar na "1º Ano B"; com a
    turma da sala cadastrada ("3º Ano A"), a prévia diz qual é."""
    from tests.test_import_individual import _pdf_individual

    eid = escola_completa["escola"].id
    _turma(db, eid, "1º Ano B", "1º Ano")
    pdf = _pdf_individual(nome="CRIANCA FICTICIA LOTE", turma=turma_pdf)
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/analisar",
                     files={"arquivo": ("relatorio-ficticio.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text
    analise = r.json()
    corr = analise["linhas"][0]["correspondencia"]
    assert corr["status"] == "nao_encontrado", corr
    if caso == "lote_turma_nova":
        assert (corr["turma_id"], corr["turma_nova"]) == (None, "1ºA"), corr
    else:
        assert (corr["turma_id"], corr["turma_nova"]) == (escola_completa["turma"].id, None), corr
    _exemplo(f"{caso}_analise.json", analise)
    _exemplo("lote_turmas.json", _turmas(cliente, eid))
