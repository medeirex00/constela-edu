"""Auditoria (frente importação): "Erros" do histórico de importações.

IMPORTACAO-12: ``importacao.qtd_erros = len(linhas) - linhas aplicadas`` contava
como erro toda linha que não virou dado — inclusive as que foram para Revisões de
identidade, que não são erro (a linha está guardada, esperando uma decisão). O
histórico mostrava "Erros 2" num selo vermelho para um Placar sem nenhuma linha
ilegível, e o coordenador achava que o arquivo tinha falhado.

Agora ``qtd_erros`` (no histórico e na resposta do /confirmar) conta só as linhas
descartadas por defeito (sem nome utilizável, turma inválida, campos ausentes, aluno
de outra escola). Em revisão vai em ``linhas_em_revisao``; a conta aposentada é
decisão da escola, não erro. Dados fictícios.
"""
import json

API = "/api/v1"
DATA = "2026-08-14T12:00:00"


def _analise(cliente, eid, alunos):
    texto = json.dumps({"fonte": "matific-placar", "turma": "3º Ano A", "alunos": alunos},
                       ensure_ascii=False)
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/analisar", data={"texto": texto})
    assert r.status_code == 200, r.text
    return r.json()


def _confirmar(cliente, eid, analise, linhas):
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/confirmar", json={
        "plataforma": analise["plataforma"], "formato": analise["formato"], "tipo": "texto",
        "recalcular": False, "linhas": linhas, "data_referencia": DATA})
    assert r.status_code == 200, r.text
    return r.json()


def _historico(cliente, eid):
    r = cliente.get(f"{API}/escolas/{eid}/importacoes")
    assert r.status_code == 200, r.text
    return r.json()


def test_linha_em_revisao_nao_e_erro(cliente, db, escola_completa):
    eid, turma = escola_completa["escola"].id, escola_completa["turma"].id
    analise = _analise(cliente, eid, [
        {"nome": "Crianca Ficticia Repetida", "uuid": "uuid-fict-r1", "estrelas": 1,
         "atividades": 1},
        {"nome": "Crianca Ficticia Repetida", "uuid": "uuid-fict-r2", "estrelas": 2,
         "atividades": 1}])
    assert analise["total_erros"] == 0
    linhas = [{"nome": linha["nome"], "dados": linha["dados"], "aluno_id": None,
               "criar_em_turma_id": turma} for linha in analise["linhas"]]
    res = _confirmar(cliente, eid, analise, linhas)
    assert (res["qtd_revisoes"], res["linhas_em_revisao"]) == (2, 2), res
    assert res["qtd_erros"] == 0, res
    assert _historico(cliente, eid)[0]["qtd_erros"] == 0, (
        "as 2 linhas que foram para a Revisão aparecem como 'Erros' no histórico")


def test_linha_com_defeito_continua_erro(cliente, db, escola_completa):
    """A linha sem nome utilizável é descartada por defeito: conta como erro; a outra,
    aplicada, não."""
    eid = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    analise = _analise(cliente, eid, [
        {"nome": ana.nome, "uuid": "uuid-fict-ana", "estrelas": 9, "atividades": 2}])
    linhas = [{"nome": analise["linhas"][0]["nome"], "dados": analise["linhas"][0]["dados"],
               "aluno_id": ana.id},
              {"nome": "--", "dados": {"estrelas": 1, "atividades": 1}, "aluno_id": None}]
    res = _confirmar(cliente, eid, analise, linhas)
    assert (res["qtd_alunos"], res["qtd_erros"]) == (1, 1), res
    assert _historico(cliente, eid)[0]["qtd_erros"] == 1
