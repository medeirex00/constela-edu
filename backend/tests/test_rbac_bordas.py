"""Bordas da autorização que a matriz genérica (``test_rbac_matriz.py``) não monta
sozinha: corpos MISTOS (id próprio + id de outra escola no mesmo pedido), sessão de
conta desligada, o token do aluno do Quest nas rotas da equipe (e o contrário) e o
painel público por token. Mesmo mundo sintético da matriz (``tests/_rbac_mundo.py``)."""
from datetime import datetime, timedelta, timezone

import jwt
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from tests._rbac_mundo import TOKEN_PAINEL_X, Banco, isolar_rbac, mundo


def _chamar(mundo, perfil, metodo, url, **kw):
    banco = Banco(mundo["modelo"])
    try:
        cab = {"Authorization": f"Bearer {mundo['tokens'][perfil]}"} if perfil else {}
        r = TestClient(app, raise_server_exceptions=False).request(metodo, url, headers=cab, **kw)
        linhas = {
            "matriculas": banco.conn.execute(
                "select aluno_id, turma_id from matriculas").fetchall(),
            "turmas": banco.conn.execute("select id, professor_id, escola_id from turmas").fetchall(),
            "alunos": banco.conn.execute("select id, status, escola_id from alunos").fetchall(),
        }
    finally:
        banco.fechar()
    return r, linhas


def test_transferir_aluno_proprio_para_turma_de_outra_escola(mundo):
    i = mundo["ids"]
    for perfil in ("coord_x", "admin_x", "global"):
        r, lin = _chamar(mundo, perfil, "POST", f"/api/v1/escolas/{i['eX']}/alunos/acoes",
                         json={"aluno_ids": [i["aT_1"]], "acao": "transferir",
                               "turma_id": i["tY"], "turma_origem_id": i["tT"]})
        assert r.status_code in (400, 404, 409), (perfil, r.status_code, r.text)
        assert (i["aT_1"], i["tY"]) not in lin["matriculas"]


def test_acao_em_lote_com_aluno_de_outra_escola_misturado(mundo):
    i = mundo["ids"]
    r, lin = _chamar(mundo, "coord_x", "POST", f"/api/v1/escolas/{i['eX']}/alunos/acoes",
                     json={"aluno_ids": [i["aT_1"], i["aY_1"]], "acao": "arquivar"})
    status_y = {a: s for a, s, _e in lin["alunos"]}[i["aY_1"]]
    assert status_y == "ativo", r.text


def test_turma_propria_com_titular_de_outra_escola(mundo):
    i = mundo["ids"]
    r, lin = _chamar(mundo, "coord_x", "PUT", f"/api/v1/escolas/{i['eX']}/turmas/{i['tT']}",
                     json={"professor_id": i["pY"]})
    assert r.status_code in (400, 404, 422), r.text
    assert {t: p for t, p, _e in lin["turmas"]}[i["tT"]] != i["pY"]


def test_designar_turma_de_outra_escola_ao_professor(mundo):
    i = mundo["ids"]
    r, lin = _chamar(mundo, "coord_x", "PUT",
                     f"/api/v1/escolas/{i['eX']}/usuarios/{i['u_prof_t']}/turmas",
                     json={"turma_ids": [i["tT"], i["tY"]]})
    assert r.status_code == 400, r.text
    assert {t: p for t, p, _e in lin["turmas"]}[i["tY"]] == i["pY"]


def test_excluir_turmas_em_lote_nao_toca_outra_escola(mundo):
    i = mundo["ids"]
    r, lin = _chamar(mundo, "admin_x", "POST", f"/api/v1/escolas/{i['eX']}/turmas/excluir",
                     json={"turma_ids": [i["tY"], i["tX2"]], "com_alunos": True})
    assert {t for t, _p, _e in lin["turmas"]} >= {i["tY"], i["tX2"]}, r.text


def test_token_do_aluno_do_quest_nao_abre_rota_da_equipe(mundo):
    i = mundo["ids"]
    agora = datetime.now(timezone.utc)
    # Token com papel "aluno" e o MESMO sub numérico de uma conta da equipe.
    falso = jwt.encode({"sub": str(i["u_global"]), "ver": 0, "papel": "aluno", "iat": agora,
                        "exp": agora + timedelta(minutes=5)},
                       settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    banco = Banco(mundo["modelo"])
    try:
        r = TestClient(app, raise_server_exceptions=False).get(
            f"/api/v1/escolas/{i['eY']}/alunos", headers={"Authorization": f"Bearer {falso}"})
    finally:
        banco.fechar()
    assert r.status_code == 401, r.text


def test_token_da_equipe_nao_abre_rota_do_aluno_do_quest(mundo):
    banco = Banco(mundo["modelo"])
    try:
        r = TestClient(app, raise_server_exceptions=False).get(
            "/api/v1/quest/perfil",
            headers={"Authorization": f"Bearer {mundo['tokens']['global']}"})
    finally:
        banco.fechar()
    assert r.status_code in (401, 404), r.text


def test_sessao_de_conta_desativada_cai(mundo):
    i = mundo["ids"]
    banco = Banco(mundo["modelo"])
    try:
        banco.conn.execute("update usuarios set status='inativo' where id=?", (i["u_coord_x"],))
        banco.conn.commit()
        r = TestClient(app, raise_server_exceptions=False).get(
            f"/api/v1/escolas/{i['eX']}/alunos",
            headers={"Authorization": f"Bearer {mundo['tokens']['coord_x']}"})
    finally:
        banco.fechar()
    assert r.status_code == 401, r.text


def test_publico_por_token_nao_abre_crianca_de_outra_escola(mundo):
    i = mundo["ids"]
    banco = Banco(mundo["modelo"])
    try:
        cli = TestClient(app, raise_server_exceptions=False)
        visivel = cli.get(f"/api/v1/publico/{TOKEN_PAINEL_X}/alunos/{i['aT_1']}")
        alheio = cli.get(f"/api/v1/publico/{TOKEN_PAINEL_X}/alunos/{i['aY_1']}")
    finally:
        banco.fechar()
    assert visivel.status_code == 200, visivel.text      # controle: o token funciona
    assert alheio.status_code == 404 and "VAZAY" not in alheio.text.upper()
