"""DEC-36 (IMPORTACAO-6): "Deixar para a Revisão" segura a conta nas importações e
coletas SEGUINTES, até alguém resolver ou descartar a pendência.

A pendência ``deixada_para_revisao`` é decisão de gente. Antes ela não segurava
nada: se o próximo relatório (ou a coleta) trouxesse a mesma conta sem o pedido, o
motor decidia de novo sozinho — associava à ficha de nome igual ou, com a política
"permitir", criava a ficha — enquanto a pendência continuava aberta na fila. Agora
``carregar_contexto`` lê essas pendências e ``decidir`` manda a mesma conta (ou o
mesmo nome na mesma sala, sem conta) para a revisão em vez de associar ou criar,
como a trava de ``contas_repetidas_no_relatorio``. A escolha explícita de uma ficha
(um humano) continua valendo. Dados fictícios.
"""
import json

from sqlalchemy import func, select

from app.models import Aluno, IdentidadeExterna, RevisaoIdentidade, SnapshotMatific

API = "/api/v1"
DATA = "2026-08-14T12:00:00"
DATA_2 = "2026-08-21T12:00:00"


def _placar(*alunos):
    return json.dumps({"fonte": "matific-placar", "turma": "3º Ano A", "alunos": list(alunos)},
                      ensure_ascii=False)


def _analise(cliente, eid, texto):
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/analisar", data={"texto": texto})
    assert r.status_code == 200, r.text
    return r.json()


def _confirmar(cliente, eid, analise, linhas, data=DATA):
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/confirmar", json={
        "plataforma": analise["plataforma"], "formato": analise["formato"], "tipo": "texto",
        "recalcular": False, "linhas": linhas, "data_referencia": data})
    assert r.status_code == 200, r.text
    return r.json()


def _deixar(linha):
    return {"nome": linha["nome"], "dados": linha["dados"], "aluno_id": None,
            "criar_em_turma_id": None, "criar_em_turma_nome": "3º Ano A",
            "deixar_para_revisao": True}


def _como_veio(linha):
    """A linha como a coleta (ou quem só confirma a prévia) a manda: sem pedido."""
    return {"nome": linha["nome"], "dados": linha["dados"], "aluno_id": None,
            "criar_em_turma_id": None, "criar_em_turma_nome": "3º Ano A"}


def _pendentes(db, eid):
    db.expire_all()
    return db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == eid, RevisaoIdentidade.status == "pendente")
        .order_by(RevisaoIdentidade.id)).scalars().all()


def _contas(db, aluno_id):
    db.expire_all()
    return db.execute(select(IdentidadeExterna.id_externo).where(
        IdentidadeExterna.aluno_id == aluno_id)).scalars().all()


def _deixada_da_ana(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    texto = _placar({"nome": ana.nome, "uuid": "uuid-fict-ana", "estrelas": 9, "atividades": 2})
    analise = _analise(cliente, eid, texto)
    assert analise["linhas"][0]["correspondencia"]["status"] == "exato"
    _confirmar(cliente, eid, analise, [_deixar(analise["linhas"][0])])
    assert [r.motivo for r in _pendentes(db, eid)] == ["deixada_para_revisao"]
    return eid, ana.id, texto


def test_a_coleta_seguinte_nao_associa_a_conta_deixada_para_revisao(
        cliente, db, escola_completa):
    eid, ana_id, texto = _deixada_da_ana(cliente, db, escola_completa)

    analise = _analise(cliente, eid, texto)
    res = _confirmar(cliente, eid, analise, [_como_veio(analise["linhas"][0])], data=DATA_2)
    assert _contas(db, ana_id) == [], (
        "a importação seguinte associou a conta que alguém deixou para a Revisão")
    assert db.scalar(select(func.count()).select_from(SnapshotMatific).where(
        SnapshotMatific.aluno_id == ana_id)) == 0
    assert (res["qtd_alunos"], res["qtd_revisoes"]) == (0, 1), res
    pend = _pendentes(db, eid)
    assert [(r.motivo, r.id_externo) for r in pend] == [("deixada_para_revisao", "uuid-fict-ana")]
    assert pend[0].ocorrencias == 2                     # a MESMA pendência
    # A prévia diz o mesmo que a confirmação.
    corr = analise["linhas"][0]["correspondencia"]
    assert corr["motivo"] == "deixada_para_revisao", corr


def test_a_conta_deixada_nao_cria_ficha_no_relatorio_seguinte(cliente, db, escola_completa):
    """O cenário do achado: duas contas de mesmo nome, uma ignorada e a outra deixada
    para a Revisão. O relatório seguinte traz só a deixada: a ficha não nasce."""
    eid = escola_completa["escola"].id
    duas = _placar(
        {"nome": "Crianca Ficticia Repetida", "uuid": "uuid-fict-r1", "estrelas": 10,
         "atividades": 3},
        {"nome": "Crianca Ficticia Repetida", "uuid": "uuid-fict-r2", "estrelas": 20,
         "atividades": 4})
    analise = _analise(cliente, eid, duas)
    _confirmar(cliente, eid, analise, [_deixar(analise["linhas"][0])])
    so_r1 = _placar({"nome": "Crianca Ficticia Repetida", "uuid": "uuid-fict-r1",
                     "estrelas": 12, "atividades": 4})
    analise = _analise(cliente, eid, so_r1)
    _confirmar(cliente, eid, analise, [_como_veio(analise["linhas"][0])], data=DATA_2)
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Aluno).where(
        Aluno.escola_id == eid, Aluno.nome == "Crianca Ficticia Repetida")) == 0, (
        "a coleta seguinte criou a ficha que alguém deixou para a Revisão")
    assert [r.motivo for r in _pendentes(db, eid)] == ["deixada_para_revisao"]


def test_descartada_a_pendencia_a_conta_volta_a_associar(cliente, db, escola_completa):
    eid, ana_id, texto = _deixada_da_ana(cliente, db, escola_completa)
    rev = _pendentes(db, eid)[0]
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/revisoes/{rev.id}/descartar",
                     json={"motivo": "conferido: é a Ana (ficticio)"})
    assert r.status_code == 200, r.text
    analise = _analise(cliente, eid, texto)
    _confirmar(cliente, eid, analise, [_como_veio(analise["linhas"][0])], data=DATA_2)
    assert _contas(db, ana_id) == ["uuid-fict-ana"]


def test_escolha_explicita_da_ficha_continua_valendo(cliente, db, escola_completa):
    """Quem confirma escolhendo a ficha É a decisão humana que a revisão pedia."""
    eid, ana_id, texto = _deixada_da_ana(cliente, db, escola_completa)
    analise = _analise(cliente, eid, texto)
    linha = {**_como_veio(analise["linhas"][0]), "aluno_id": ana_id}
    _confirmar(cliente, eid, analise, [linha], data=DATA_2)
    assert _contas(db, ana_id) == ["uuid-fict-ana"]


def test_outra_conta_da_mesma_crianca_nao_fica_presa(cliente, db, escola_completa):
    """A trava é da CONTA deixada para a Revisão: outra linha (outra criança da
    turma) segue o caminho de sempre."""
    eid, _ana_id, _texto = _deixada_da_ana(cliente, db, escola_completa)
    joao = escola_completa["alunos"][1]
    analise = _analise(cliente, eid, _placar(
        {"nome": joao.nome, "uuid": "uuid-fict-joao", "estrelas": 5, "atividades": 1}))
    _confirmar(cliente, eid, analise, [_como_veio(analise["linhas"][0])], data=DATA_2)
    assert _contas(db, joao.id) == ["uuid-fict-joao"]
