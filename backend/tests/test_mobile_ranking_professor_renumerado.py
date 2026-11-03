"""App mobile: o ranking do PROFESSOR no pacote ``/sincronizacao`` sai 1..N.

A web renumera o Ranking Geral do professor 1..N (``rankings.ranking_geral``,
travado por ``test_permissoes.test_professor_ranking_renumerado_1n``) e o Top 10
do painel também (``montar_dashboard``). O pacote do app devolvia ``ranking``
direto de ``_ranking(...)``, com a posição GLOBAL da escola: no MESMO pacote o
Top 10 do Painel dizia "1º" e a aba "Ranking Geral" dizia "100º" para a mesma
criança (revisão de integração 5, exportacoes-notificacoes, prova 501).

Regra travada aqui: professor — posições do app = Top 10 do pacote = web, 1..N;
gestão — posição global, como sempre. Dados fictícios.
"""
from app.models import Nota
from tests.test_permissoes import _cliente_como, cenario_professor  # noqa: F401 — fixture


def _notas(db, escola, alunos, fora):
    """Posições globais espaçadas (100, 103, 105, 110): o aluno de fora (turma B)
    fica no meio, então a posição global NÃO é 1..N para o professor."""
    posicoes = {alunos[0].id: 100, alunos[1].id: 105, alunos[2].id: 110, fora.id: 103}
    valores = {alunos[0].id: 50.0, alunos[1].id: 40.0, alunos[2].id: 30.0, fora.id: 45.0}
    for aid, pos in posicoes.items():
        db.add(Nota(escola_id=escola.id, aluno_id=aid, ano_letivo=2026,
                    nota_geral=valores[aid], posicao=pos))
    db.commit()


def test_app_renumera_o_ranking_do_professor_como_a_web(
        cenario_professor, escola_completa, db):  # noqa: F811
    c = cenario_professor
    escola = escola_completa["escola"]
    _notas(db, escola, escola_completa["alunos"], c["aluno_fora"])
    base = f"/api/v1/escolas/{escola.id}"

    web = c["professor"].get(f"{base}/ranking")
    pacote = c["professor"].get(f"{base}/sincronizacao")
    assert web.status_code == 200 and pacote.status_code == 200, (web.text, pacote.text)
    pacote = pacote.json()

    pos_web = {i["aluno_id"]: i["posicao"] for i in web.json()}
    pos_app = {i["aluno_id"]: i["posicao"] for i in pacote["ranking"]}
    pos_top = {i["aluno_id"]: i["posicao"] for i in pacote["dashboard"]["top10"]}
    assert set(pos_app) == {a.id for a in escola_completa["alunos"]}  # só a turma A
    assert sorted(pos_app.values()) == [1, 2, 3]
    # O mesmo pacote não pode dizer duas posições para a mesma criança.
    assert pos_app == pos_top, ("aba Ranking x Top 10 do Painel", pos_app, pos_top)
    # E o app diz o mesmo que a web para o mesmo professor.
    assert pos_app == pos_web, ("app x web", pos_app, pos_web)


def test_app_gestao_segue_com_a_posicao_global(cenario_professor, escola_completa,
                                               db):  # noqa: F811
    """Controle: para a gestão, a posição global nas duas rotas (nada muda)."""
    c = cenario_professor
    escola = escola_completa["escola"]
    _notas(db, escola, escola_completa["alunos"], c["aluno_fora"])
    base = f"/api/v1/escolas/{escola.id}"
    web = {i["aluno_id"]: i["posicao"]
           for i in c["coordenador"].get(f"{base}/ranking").json()}
    app = {i["aluno_id"]: i["posicao"]
           for i in c["coordenador"].get(f"{base}/sincronizacao").json()["ranking"]}
    assert web == app
    assert sorted(app.values()) == [100, 103, 105, 110]
