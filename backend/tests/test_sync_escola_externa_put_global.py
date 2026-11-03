"""Vínculo da escola EXTERNA: o PUT é só do Admin Global (achado e97/autorização 2).

Antes, o coordenador (ou admin) de QUALQUER escola gravava no vínculo dele o
schoolId de outra escola (sem credencial nenhuma) e travava a sincronização da
dona (``escola_externa_em_outra_escola``); a dona levava 409 ao gravar o próprio
id, e a mensagem que ela recebia trazia o id interno da escola que reservou.
Agora: o PUT exige o Admin Global (a mitigação que o docs/SINCRONIZACAO.md já
recomendava); GET e DELETE seguem com a escola; a mensagem da coleta não cita o
id interno da outra escola, que fica só na auditoria. Dados fictícios.
"""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import Escola, LogAuditoria, Usuario
from app.sync import escola_externa
from app.sync.interfaces import ErroConector

API = "/api/v1"
ID_B = "525252"


def _login(email: str) -> TestClient:
    c = TestClient(app)
    r = c.post(f"{API}/auth/login", data={"username": email, "password": "s3nh4"})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


@pytest.fixture()
def duas_escolas(db, escola_completa):
    a = escola_completa["escola"]
    db.add(Usuario(escola_id=a.id, nome="Coord A Ficticio", email="coord.a.ext@teste.local",
                   senha_hash=hash_senha("s3nh4"), cargo="coordenador"))
    b = Escola(nome="ESCOLA B FICTICIA", ano_letivo_ativo=2026)
    db.add(b)
    db.flush()
    db.add(Usuario(escola_id=b.id, nome="Coord B Ficticio", email="coord.b.ext@teste.local",
                   senha_hash=hash_senha("s3nh4"), cargo="coordenador"))
    db.commit()
    return a, b


def _url(escola_id: int) -> str:
    return f"{API}/escolas/{escola_id}/sync/escola-externa/elefante"


@pytest.mark.parametrize("quem", ["coordenador", "admin"])
def test_gestor_da_escola_nao_grava_vinculo(db, duas_escolas, cliente, quem):
    a, b = duas_escolas
    c = _login("coord.a.ext@teste.local") if quem == "coordenador" else cliente
    r = c.put(_url(a.id), json={"id_externo": ID_B, "nome": "x"})
    assert r.status_code == 403, r.text
    assert "administradores globais" in r.json()["detail"]
    assert escola_externa.obter(db, a.id, "elefante") is None
    # A dona não fica travada: o id dela segue livre (ninguém o reservou).
    assert escola_externa.escolas_com_o_mesmo_vinculo(db, "elefante", ID_B) == []


def test_admin_global_grava_e_a_escola_segue_lendo_e_desfazendo(db, duas_escolas,
                                                               cliente_global):
    a, _ = duas_escolas
    r = cliente_global.put(_url(a.id), json={"id_externo": ID_B, "nome": "ESCOLA FICT"})
    assert r.status_code == 200, r.text
    assert r.json()["id_externo"] == ID_B
    coord_a = _login("coord.a.ext@teste.local")
    lido = coord_a.get(_url(a.id))
    assert lido.status_code == 200 and lido.json()["id_externo"] == ID_B   # GET: igual
    assert coord_a.delete(_url(a.id)).status_code == 204                  # DELETE: igual
    db.expire_all()
    assert escola_externa.obter(db, a.id, "elefante") is None


def _coleta_da_b(db, b):
    from app.sync import service
    execucao = SimpleNamespace(escola_id=b.id, plataforma="elefante")
    conector = SimpleNamespace(confere_escola_externa=True)
    ctx = SimpleNamespace(coleta={"escola_externa": {"id": ID_B, "nome": b.nome}})
    return service._conferir_escola_externa(db, execucao, b, conector, ctx, vinculo=None)


def test_mensagem_da_coleta_nao_revela_o_id_interno_da_outra_escola(
        db, duas_escolas, cliente_global):
    a, b = duas_escolas
    assert cliente_global.put(_url(a.id), json={"id_externo": ID_B}).status_code == 200
    with pytest.raises(ErroConector) as exc:
        _coleta_da_b(db, b)
    assert exc.value.codigo == escola_externa.ESCOLA_EM_OUTRA_ESCOLA
    mensagem = str(exc.value)
    assert "outra escola do Constela" in mensagem
    assert f"id {a.id}" not in mensagem and f"({a.id})" not in mensagem
    # O id fica na AUDITORIA (lida pelo suporte/global, não pela escola).
    db.expire_all()
    trilha = db.query(LogAuditoria).filter_by(
        acao="sync.escola_externa_em_outra_escola", escola_id=b.id).one()
    assert trilha.detalhes["outras_escolas"] == [a.id]
    assert trilha.detalhes["id_externo"] == ID_B
