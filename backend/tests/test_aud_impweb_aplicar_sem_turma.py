"""Revisão (tela de Importações): "Aplicar a todos: turma do relatório (nova)" e a
criança SEM turma no relatório.

REV-IMPWEB-1 (regressão de 2ae0f71e, IMPORTACAO-1): no Placar da escola sem turma no
topo, uma criança da "1 ANO A" (a escola não tem a 1ºA: ``turma_nova``) e outra sem
turma (nenhuma das três pistas). O botão aparece pela primeira; o clique punha "Criar
na turma do relatório" também na segunda — a tela a contava como importada e nova, e
mandava ``criar_em_turma_nome`` nulo, que o backend manda para Revisões (``sem_turma``).
Aqui, as respostas reais que o teste da tela (AudAplicarSemTurma.test.tsx) usa e o que
cada corpo faz no backend. Dados fictícios.
"""
from tests.aud_impweb_exemplos import (
    _analise, _confirmar, _exemplo, _fichas, _linha, _motivos, _placar, _relatorio, _turmas,
    _turmas_do_aluno)

COM_TURMA = "Crianca Ficticia Com Turma"
SEM_TURMA = "Crianca Ficticia Sem Turma"


def _previa(cliente, eid):
    return _analise(cliente, eid, _placar(None, [
        {"nome": COM_TURMA, "uuid": "uuid-fict-com-turma", "estrelas": 5, "atividades": 1,
         "turma": "1 ANO A"},
        {"nome": SEM_TURMA, "uuid": "uuid-fict-sem-turma", "estrelas": 7, "atividades": 2,
         "turma": ""}]))


def test_placar_sem_turma_a_previa_so_da_turma_a_quem_tem(cliente, db, escola_completa):
    """A prévia diz a turma nova (1ºA) da primeira; a segunda não tem turma do relatório
    (nem na linha nem no cabeçalho) nem turma decidida."""
    eid = escola_completa["escola"].id
    analise = _previa(cliente, eid)
    assert analise["turma_detectada"] == ""
    com, sem = analise["linhas"]
    assert (com["nome"], sem["nome"]) == (COM_TURMA, SEM_TURMA)
    c, s = com["correspondencia"], sem["correspondencia"]
    assert (c["status"], c["turma_id"], c["turma_nova"]) == ("nao_encontrado", None, "1ºA")
    assert (s["status"], s["turma_id"], s["turma_nova"]) == ("nao_encontrado", None, None)
    assert _relatorio(analise, com) == "1 ANO A"
    assert not _relatorio(analise, sem)
    _exemplo("placar_sem_turma_analise.json", analise)
    _exemplo("placar_sem_turma_turmas.json", _turmas(cliente, eid))


def test_corpo_antigo_a_linha_sem_turma_vai_para_a_revisao(cliente, db, escola_completa):
    """O corpo de antes da correção: "Criar na turma do relatório" nas duas, a segunda
    com o nome da turma nulo. O backend não cria a ficha dela — abre a pendência
    ``sem_turma``; a tela dizia "2 de 2 serão importados" e "2 aluno(s) novo(s)"."""
    eid = escola_completa["escola"].id
    analise = _previa(cliente, eid)
    com, sem = analise["linhas"]
    antes = _fichas(db, eid)
    r = _confirmar(cliente, eid, analise, [
        _linha(com, criar_em_turma_nome=_relatorio(analise, com)),
        _linha(sem, criar_em_turma_nome=None)])
    assert _fichas(db, eid) - antes == 1
    assert _motivos(db, eid) == ["sem_turma"]
    assert _turmas_do_aluno(db, eid, COM_TURMA) == ["1ºA"]
    assert _turmas_do_aluno(db, eid, SEM_TURMA) == []
    assert r["qtd_alunos"] == 1


def test_corpo_novo_so_a_crianca_com_turma_vai_e_nasce_na_1a(cliente, db, escola_completa):
    """O corpo que a tela manda agora: a linha sem turma fica em "Ignorar" (o destino
    dela antes do clique) e não vai; a outra nasce na 1ºA nova, sem pendência."""
    eid = escola_completa["escola"].id
    analise = _previa(cliente, eid)
    com, _sem = analise["linhas"]
    antes = _fichas(db, eid)
    r = _confirmar(cliente, eid, analise, [
        _linha(com, criar_em_turma_nome=_relatorio(analise, com))])
    assert _fichas(db, eid) - antes == 1
    assert _motivos(db, eid) == []
    assert _turmas_do_aluno(db, eid, COM_TURMA) == ["1ºA"]
    assert r["qtd_alunos"] == 1
