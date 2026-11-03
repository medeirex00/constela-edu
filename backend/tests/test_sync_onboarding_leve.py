"""GET /escolas/{id}/sync/onboarding: o sinal do "Comece aqui" sem o /status inteiro.

A barra lateral (Layout → useOnboarding) buscava o GET /sync/status completo — o
endpoint mais caro da API, ~20 consultas — só para ler ``lista_piloto_importada``,
a cada montagem da navegação. Este endpoint devolve SÓ esse sinal, pela mesma
regra (a escola já tem turma) e com o mesmo acesso do /status, em uma consulta
além da autenticação. Dados fictícios.
"""
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.core.security import hash_senha
from app.main import app
from app.models import Escola, Usuario

API = "/api/v1"


def _onboarding(cliente, escola_id):
    return cliente.get(f"{API}/escolas/{escola_id}/sync/onboarding")


def _login(db, escola_id, email, cargo):
    db.add(Usuario(escola_id=escola_id, nome=f"Pessoa Ficticia {cargo}", email=email,
                   senha_hash=hash_senha("s3nh4"), cargo=cargo))
    db.commit()
    cli = TestClient(app)
    r = cli.post(f"{API}/auth/login", data={"username": email, "password": "s3nh4"})
    assert r.status_code == 200, r.text
    cli.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return cli


def test_mesmo_sinal_do_status(cliente_global, db, escola_completa):
    nova = Escola(nome="Escola Nova Ficticia", ano_letivo_ativo=2026)
    db.add(nova)
    db.commit()
    for eid, esperado in ((escola_completa["escola"].id, True), (nova.id, False)):
        r = _onboarding(cliente_global, eid)
        assert r.status_code == 200, r.text
        assert r.json() == {"lista_piloto_importada": esperado}
        status = cliente_global.get(f"{API}/escolas/{eid}/sync/status").json()
        assert status["lista_piloto_importada"] is esperado


def test_uma_consulta_alem_da_autenticacao_e_sem_commit(cliente, db, escola_completa):
    eid = escola_completa["escola"].id   # lido ANTES de contar (relê depois do commit)
    engine = db.get_bind()
    contagem = {"stmt": 0, "commit": 0}
    instrucoes = []

    def _stmt(_conn, _cursor, sql, *_a):
        contagem["stmt"] += 1
        instrucoes.append(" ".join(sql.split())[:80])

    def _commit(*_a, **_k):
        contagem["commit"] += 1

    event.listen(engine, "before_cursor_execute", _stmt)
    event.listen(engine, "commit", _commit)
    try:
        r = _onboarding(cliente, eid)
    finally:
        event.remove(engine, "before_cursor_execute", _stmt)
        event.remove(engine, "commit", _commit)
    assert r.status_code == 200 and r.json()["lista_piloto_importada"] is True
    # usuário + escola (autorização) + a turma
    assert contagem == {"stmt": 3, "commit": 0}, instrucoes


def test_mesmo_acesso_do_status(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    outra = Escola(nome="Outra Escola Ficticia", ano_letivo_ativo=2026)
    db.add(outra)
    db.commit()
    # Outra escola: negado, como no /status.
    assert _onboarding(cliente, outra.id).status_code == 403
    assert cliente.get(f"{API}/escolas/{outra.id}/sync/status").status_code == 403
    # Professor: negado, como no /status (o menu dele não tem "Comece aqui").
    prof = _login(db, eid, "professor.ficticio@teste.local", "professor")
    assert _onboarding(prof, eid).status_code == 403
    assert prof.get(f"{API}/escolas/{eid}/sync/status").status_code == 403
    # Coordenador da escola: liberado.
    coord = _login(db, eid, "coordenacao.ficticia@teste.local", "coordenador")
    assert _onboarding(coord, eid).json() == {"lista_piloto_importada": True}
