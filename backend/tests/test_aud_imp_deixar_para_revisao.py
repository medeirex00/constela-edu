"""Auditoria (frente importação): "Deixar para a Revisão" é uma INSTRUÇÃO ao backend.

IMPORTACAO-6 (parte do backend): a tela mandava, para "Deixar para a Revisão", o
mesmo corpo de um "Criar" (a turma) e confiava que a confirmação repetiria a decisão
da prévia. Com duas contas de mesmo nome (contas_repetidas_no_relatorio), ignorar uma
delas fazia a outra chegar sozinha: o backend decidia CRIAR e a ficha nascia com os
números de uma das contas — a tela tinha dito "vai para Revisões de identidade".

Agora a linha de confirmação traz ``deixar_para_revisao``: a linha nunca associa nem
cria; vai para a fila com o motivo que o backend achar, ou — se para ele a linha
associaria ou criaria — com o motivo ``deixada_para_revisao``. Dados fictícios.
"""
import json

from sqlalchemy import func, select

API = "/api/v1"
DATA = "2026-08-14T12:00:00"

PLACAR_DUAS_CONTAS = json.dumps({"fonte": "matific-placar", "turma": "3º Ano A", "alunos": [
    {"nome": "Crianca Ficticia Repetida", "uuid": "uuid-fict-r1", "estrelas": 10,
     "atividades": 3},
    {"nome": "Crianca Ficticia Repetida", "uuid": "uuid-fict-r2", "estrelas": 20,
     "atividades": 4}]}, ensure_ascii=False)


def _analise(cliente, eid, texto):
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/analisar", data={"texto": texto})
    assert r.status_code == 200, r.text
    return r.json()


def _confirmar(cliente, eid, analise, linhas):
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/confirmar", json={
        "plataforma": analise["plataforma"], "formato": analise["formato"], "tipo": "texto",
        "recalcular": False, "linhas": linhas, "data_referencia": DATA})
    assert r.status_code == 200, r.text
    return r.json()


def _revisoes(db, eid):
    from app.models import RevisaoIdentidade
    db.expire_all()
    return db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == eid).order_by(RevisaoIdentidade.id)).scalars().all()


def _fichas(db, eid, nome):
    from app.models import Aluno
    db.expire_all()
    return db.scalar(select(func.count()).select_from(Aluno).where(
        Aluno.escola_id == eid, Aluno.nome == nome))


def _contas(db, aluno_id):
    from app.models import IdentidadeExterna
    db.expire_all()
    return db.execute(select(IdentidadeExterna.id_externo).where(
        IdentidadeExterna.aluno_id == aluno_id)).scalars().all()


def _deixar(linha, turma_relatorio="3º Ano A"):
    return {"nome": linha["nome"], "dados": linha["dados"], "aluno_id": None,
            "criar_em_turma_id": None, "criar_em_turma_nome": turma_relatorio,
            "deixar_para_revisao": True}


def test_ignorar_uma_das_duas_contas_nao_faz_a_outra_criar_ficha(cliente, db, escola_completa):
    """O cenário do achado: a conta 2 ignorada, a conta 1 "Deixar para a Revisão"."""
    eid = escola_completa["escola"].id
    analise = _analise(cliente, eid, PLACAR_DUAS_CONTAS)
    assert {linha["correspondencia"]["motivo"] for linha in analise["linhas"]} == {
        "contas_repetidas_no_relatorio"}
    res = _confirmar(cliente, eid, analise, [_deixar(analise["linhas"][0])])
    assert _fichas(db, eid, "Crianca Ficticia Repetida") == 0, (
        "'Deixar para a Revisão' criou a ficha com os números da conta 1")
    assert (res["qtd_alunos"], res["qtd_revisoes"]) == (0, 1), res
    revs = _revisoes(db, eid)
    assert [(r.motivo, r.id_externo) for r in revs] == [("deixada_para_revisao", "uuid-fict-r1")]
    lista = cliente.get(f"{API}/escolas/{eid}/importacoes/revisoes").json()
    assert lista[0]["motivo_texto"], lista[0]


def test_linha_que_o_backend_tambem_revisaria_fica_com_o_motivo_dele(
        cliente, db, escola_completa):
    """Com as duas contas no corpo e as duas deixadas para a Revisão, o motivo é o do
    backend (contas_repetidas_no_relatorio) — o mesmo da prévia."""
    eid = escola_completa["escola"].id
    analise = _analise(cliente, eid, PLACAR_DUAS_CONTAS)
    _confirmar(cliente, eid, analise, [_deixar(linha) for linha in analise["linhas"]])
    assert sorted(r.motivo for r in _revisoes(db, eid)) == [
        "contas_repetidas_no_relatorio", "contas_repetidas_no_relatorio"]
    assert _fichas(db, eid, "Crianca Ficticia Repetida") == 0


def test_deixar_para_revisao_nunca_associa(cliente, db, escola_completa):
    """A linha que associaria (nome idêntico na sala) também não associa: a conta não
    é vinculada à ficha e nada é gravado nela; a ficha fica como candidata."""
    eid = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    analise = _analise(cliente, eid, json.dumps({
        "fonte": "matific-placar", "turma": "3º Ano A", "alunos": [
            {"nome": ana.nome, "uuid": "uuid-fict-ana", "estrelas": 9, "atividades": 2}]}))
    assert analise["linhas"][0]["correspondencia"]["status"] == "exato"
    res = _confirmar(cliente, eid, analise, [_deixar(analise["linhas"][0])])
    assert (res["qtd_alunos"], res["qtd_revisoes"]) == (0, 1), res
    assert _contas(db, ana.id) == []
    revs = _revisoes(db, eid)
    assert [r.motivo for r in revs] == ["deixada_para_revisao"]
    assert [c["aluno_id"] for c in revs[0].candidatos] == [ana.id]


def test_sem_o_campo_o_criar_continua_criando(cliente, db, escola_completa):
    """Contraprova: sem ``deixar_para_revisao`` (o padrão, e o que a sincronização
    manda) nada muda — a conta sozinha cria a ficha, como antes."""
    eid, turma = escola_completa["escola"].id, escola_completa["turma"].id
    analise = _analise(cliente, eid, PLACAR_DUAS_CONTAS)
    linha = analise["linhas"][0]
    _confirmar(cliente, eid, analise, [{"nome": linha["nome"], "dados": linha["dados"],
                                        "aluno_id": None, "criar_em_turma_id": turma}])
    assert _fichas(db, eid, "Crianca Ficticia Repetida") == 1
