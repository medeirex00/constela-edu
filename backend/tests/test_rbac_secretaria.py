"""RBAC da Secretaria (usuário com rede vinculada, não-global).

A Secretaria acompanha os resultados da REDE, mas NÃO opera as escolas:
- não pode ALTERAR métricas (mas pode LER);
- não pode importar, sincronizar nem rodar o diagnóstico Elefante.
O coordenador de escola (sem rede) e o admin global seguem com escrita normal.
Fecha o furo de a Secretaria ter cargo "coordenador" e ser tratada como um.
"""
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import Rede, Usuario


def _login(email: str, senha: str) -> TestClient:
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", data={"username": email, "password": senha})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _cenario(db, escola_completa):
    escola = escola_completa["escola"]
    rede = Rede(nome="Rede Teste", status="ativa")
    db.add(rede)
    db.flush()
    db.add(Usuario(escola_id=escola.id, nome="Coord Escola", email="coord@rbac.local",
                   senha_hash=hash_senha("s3nh4"), cargo="coordenador"))
    # Secretaria: cargo coordenador + rede vinculada (mantém escola_id — pior caso).
    db.add(Usuario(escola_id=escola.id, nome="Secretaria", email="sec@rbac.local",
                   senha_hash=hash_senha("s3nh4"), cargo="coordenador", rede_id=rede.id))
    db.commit()
    return escola.id


def test_secretaria_nao_altera_metricas_mas_le(db, escola_completa):
    eid = _cenario(db, escola_completa)
    coord = _login("coord@rbac.local", "s3nh4")
    sec = _login("sec@rbac.local", "s3nh4")
    corpo = {"pesos": {"matific": 50, "elefante": 50}}

    # ESCRITA: coordenador de escola passa da autorização (não é 403);
    # Secretaria é barrada com 403.
    assert coord.put(f"/api/v1/escolas/{eid}/configuracoes/pesos/geral", json=corpo).status_code != 403
    assert sec.put(f"/api/v1/escolas/{eid}/configuracoes/pesos/geral", json=corpo).status_code == 403

    # LEITURA: a Secretaria PODE ver as métricas (não é 403).
    assert sec.get(f"/api/v1/escolas/{eid}/configuracoes/pesos/geral").status_code != 403


def test_secretaria_bloqueada_em_sync_diagnostico_importacao(db, escola_completa):
    eid = _cenario(db, escola_completa)
    coord = _login("coord@rbac.local", "s3nh4")
    sec = _login("sec@rbac.local", "s3nh4")

    for metodo, rota in [
        ("post", f"/api/v1/escolas/{eid}/sync/agora"),
        ("post", f"/api/v1/escolas/{eid}/sync/elefante/diagnostico"),
        ("post", f"/api/v1/escolas/{eid}/importacoes/recalcular"),
    ]:
        assert getattr(sec, metodo)(rota, json={}).status_code == 403, rota
        # O coordenador de escola NÃO é barrado por papel/rede (403).
        assert getattr(coord, metodo)(rota, json={}).status_code != 403, rota
