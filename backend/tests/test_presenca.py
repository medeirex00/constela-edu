"""Presença em tempo real: heartbeat + Monitor de Sessões Ativas.

Regras cobertas:
  * o heartbeat marca ``visto_em`` e é aberto a qualquer conta autenticada;
  * o monitor (`/presenca/sessoes`) é EXCLUSIVO do Admin Global (403 p/ o resto);
  * "online" = ``visto_em`` dentro da janela; fora dela, offline;
  * o join traz o nome da escola e a ordenação põe os online primeiro.
"""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_senha
from app.main import app
from app.models import Usuario

API = "/api/v1"


def _cliente_global(db, escola_id=1) -> TestClient:
    """Cliente autenticado como ADMIN GLOBAL — o único que vê o monitor."""
    db.add(Usuario(escola_id=escola_id, nome="Chefe Global",
                   email="global@teste.local", senha_hash=hash_senha("s3nh4"),
                   cargo="admin", is_global=True))
    db.commit()
    c = TestClient(app)
    tok = c.post(f"{API}/auth/login",
                 data={"username": "global@teste.local", "password": "s3nh4"}
                 ).json()["access_token"]
    c.headers["Authorization"] = f"Bearer {tok}"
    return c


def test_heartbeat_marca_presenca(cliente, db):
    r = cliente.post(f"{API}/presenca/heartbeat")
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}
    db.expire_all()
    u = db.execute(
        select(Usuario).where(Usuario.email == "admin@teste.local")
    ).scalar_one()
    assert u.visto_em is not None


def test_sessoes_exclusivo_do_admin_global(cliente):
    # `cliente` é admin de ESCOLA (is_global=False) → sem acesso ao monitor.
    r = cliente.get(f"{API}/presenca/sessoes")
    assert r.status_code == 403


def test_sessoes_lista_online_e_offline(cliente, db):
    gc = _cliente_global(db)
    # O global bate o heartbeat → online; o admin de escola nunca bateu → offline.
    assert gc.post(f"{API}/presenca/heartbeat").status_code == 200

    r = gc.get(f"{API}/presenca/sessoes")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["limiar_online_seg"] == 90
    assert "agora" in corpo

    por_email = {s["email"]: s for s in corpo["sessoes"]}
    assert por_email["global@teste.local"]["online"] is True
    assert por_email["admin@teste.local"]["online"] is False
    # O join traz o nome da escola do usuário.
    assert por_email["admin@teste.local"]["escola_nome"] == "ESCOLA TESTE"
    assert corpo["online"] == 1
    # Online vem primeiro na ordenação.
    assert corpo["sessoes"][0]["email"] == "global@teste.local"


def test_visto_em_antigo_fica_offline(cliente, db):
    gc = _cliente_global(db)
    # Heartbeat "há muito tempo" → fora da janela de tolerância → offline.
    u = db.execute(
        select(Usuario).where(Usuario.email == "global@teste.local")
    ).scalar_one()
    u.visto_em = datetime.now(timezone.utc) - timedelta(minutes=10)
    db.commit()

    r = gc.get(f"{API}/presenca/sessoes")
    por_email = {s["email"]: s for s in r.json()["sessoes"]}
    assert por_email["global@teste.local"]["online"] is False


def test_heartbeat_exige_autenticacao():
    c = TestClient(app)
    assert c.post(f"{API}/presenca/heartbeat").status_code == 401
