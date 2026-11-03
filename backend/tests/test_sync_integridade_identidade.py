"""Integridade da IDENTIDADE na sincronização (frente B, 22/10/2026).

O que estes testes travam, pelo caminho da sync (arquivo da API → parser →
porta única de identidade → gravação), com dados FICTÍCIOS — comportamentos que
já eram os certos e que as correções de turma/nome/id não podem quebrar:

  * associação AMBÍGUA continua indo para a revisão (nada de "o primeiro");
  * TRANSFERIDO não é reativado, não ganha ficha nova e não recebe dado sozinho;
  * criança já VINCULADA cuja matrícula está numa turma ARQUIVADA continua
    recebendo o dado na própria ficha (comportamento aprovado — mantido).

Nada aqui funde nem exclui ficha: o que é inseguro vira pendência. Os casos de
nome incompleto e de id duplicado estão nos arquivos ``…_nome_incompleto`` e
``…_id_duplicado``; os de turma, matrícula e ano letivo em ``…_turmas``.
"""
from app.models import Aluno
from tests.sync_integridade_comum import (aluno, aplicar, dono, elefante_resumo, fichas,
                                          matific, pendentes, sem_disco, snap_elefante,
                                          snap_matific, turma, turmas_de, vincular)

K = "3 ANO A TARDE ANUAL (300396804)"      # a sala "3º Ano A" do escola_completa


def test_associacao_ambigua_vai_para_revisao_sem_criar_nem_aplicar(
        db, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    escola, t = escola_completa["escola"], escola_completa["turma"]
    l1 = aluno(db, escola.id, t, "LUCAS FICTICIO SILVA")
    l2 = aluno(db, escola.id, t, "LUCAS FICTICIO SILVA")
    db.commit()
    antes = fichas(db, escola.id)

    aplicar(db, escola, matific(K, [{"nome": "LUCAS FICTICIO SILVA", "nome_abrev": "LUCAS S",
                                     "uuid": "u-lucas", "estrelas": 9, "atividades": 3}]))
    aplicar(db, escola, elefante_resumo("3 ANO A TARDE ANUAL", [
        {"studentId": 9100001, "studentName": "LUCAS FICTICIO SILVA", "totalBooksRead": 4}]))

    assert fichas(db, escola.id) == antes
    assert snap_matific(db, l1.id) is None and snap_matific(db, l2.id) is None
    assert snap_elefante(db, l1.id) is None and snap_elefante(db, l2.id) is None
    revs = pendentes(db, escola.id)
    assert {r.plataforma for r in revs} == {"matific", "elefante"}
    for r in revs:
        assert {c["aluno_id"] for c in r.candidatos} == {l1.id, l2.id}


def test_transferido_nao_reativa_nao_duplica_e_nao_recebe_sozinho(
        db, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    escola, t = escola_completa["escola"], escola_completa["turma"]
    vinculado = aluno(db, escola.id, t, "BRUNA FICTICIA SAIU", status="transferido")
    vincular(db, escola.id, vinculado.id, "matific", "u-bruna")
    pelo_nome = aluno(db, escola.id, t, "CAIO FICTICIO SAIU", status="transferido")
    db.commit()
    antes = fichas(db, escola.id)

    aplicar(db, escola, matific(K, [
        {"nome": vinculado.nome, "nome_abrev": "BRUNA S", "uuid": "u-bruna",
         "estrelas": 9, "atividades": 3},
        {"nome": pelo_nome.nome, "nome_abrev": "CAIO S", "uuid": "u-caio",
         "estrelas": 5, "atividades": 2}]))

    assert fichas(db, escola.id) == antes
    for a in (vinculado, pelo_nome):
        assert db.get(Aluno, a.id).status == "transferido"
        assert snap_matific(db, a.id) is None
    motivos = {r.nome_recebido: r.motivo for r in pendentes(db, escola.id)}
    assert motivos == {vinculado.nome: "identidade_de_ficha_inativa",
                       pelo_nome.nome: "ficha_inativa"}
    assert dono(db, escola.id, "matific", "u-caio") is None


def test_vinculado_em_turma_arquivada_recebe_na_propria_ficha(db, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    escola = escola_completa["escola"]
    arquivada = turma(db, escola.id, "1º Ano", "1º Ano", status="arquivada")
    turma(db, escola.id, "1ª Fase", "1ª Fase")
    crianca = aluno(db, escola.id, arquivada, "DIANA FICTICIA DO PRIMEIRO")
    vincular(db, escola.id, crianca.id, "matific", "u-diana")
    vincular(db, escola.id, crianca.id, "elefante", "9700002")
    db.commit()
    antes = fichas(db, escola.id)
    sala = "1 ANO A TARDE ANUAL (300000001)"

    aplicar(db, escola, matific(sala, [{"nome": crianca.nome, "nome_abrev": "DIANA D",
                                        "uuid": "u-diana", "estrelas": 12, "atividades": 4}]))
    aplicar(db, escola, elefante_resumo("1 ANO A TARDE ANUAL", [
        {"studentId": 9700002, "studentName": crianca.nome, "totalBooksRead": 3}]))

    s = snap_matific(db, crianca.id)
    assert s is not None and (s.estrelas, s.atividades) == (12, 4)
    assert snap_elefante(db, crianca.id).livros_unicos == 3
    assert fichas(db, escola.id) == antes
    assert turmas_de(db, crianca.id) == [arquivada.id]      # matrícula intacta
