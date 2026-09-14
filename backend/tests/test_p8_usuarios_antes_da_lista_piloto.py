"""P8 — usuários da escola ANTES da Lista Piloto.

O Admin Global cria o primeiro usuário administrativo (coordenador) de uma
escola recém-criada — 0 turmas, 0 alunos, Lista Piloto não iniciada,
nenhuma integração. Dado acadêmico NÃO é pré-requisito de conta. O usuário
nasce vinculado exclusivamente à escola da URL, nunca global nem de rede; as
regras existentes (só admin/global cria; e-mail/@ únicos; senha forte;
auditoria) continuam valendo.
"""
from sqlalchemy import func, select

from app.core.security import hash_senha
from app.models import Aluno, LogAuditoria, Turma, Usuario

API = "/api/v1"
SENHA = "Constela#Forte2026"


def _login(cliente, email: str, senha: str = SENHA) -> dict:
    r = cliente.post(f"{API}/auth/login", data={"username": email, "password": senha})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _global(db) -> dict:
    """Admin Global SEM escola própria (a conta da rede), como em produção."""
    db.add(Usuario(escola_id=None, nome="Root", email="root@constela.local",
                   senha_hash=hash_senha(SENHA), cargo="admin", is_global=True))
    db.commit()
    return {"email": "root@constela.local"}


def _escola_vazia(cliente, chaves: dict, nome: str = "ESCOLA NOVA") -> int:
    r = cliente.post(f"{API}/escolas", headers=chaves,
                     json={"nome": nome, "cidade": "Caraguatatuba", "estado": "SP"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _coordenador(email: str = "coord@nova.escola.br") -> dict:
    return {"nome": "Coordenadora Nova", "email": email, "senha": SENHA, "cargo": "coordenador"}


# --- 1, 2, 3, 4: escola vazia, sem Lista Piloto, vínculo certo, sem escopo global ---

def test_admin_global_cria_coordenador_em_escola_sem_turmas_nem_alunos(cliente, db, escola_completa):
    chaves = _login(cliente, _global(db)["email"])
    nova = _escola_vazia(cliente, chaves)

    # A escola está realmente vazia e a Lista Piloto NÃO foi iniciada.
    assert db.scalar(select(func.count(Turma.id)).where(Turma.escola_id == nova)) == 0
    assert db.scalar(select(func.count(Aluno.id)).where(Aluno.escola_id == nova)) == 0
    status = cliente.get(f"{API}/escolas/{nova}/sync/status", headers=chaves)
    assert status.status_code == 200, status.text
    assert status.json()["lista_piloto_importada"] is False
    assert cliente.get(f"{API}/escolas/{nova}/usuarios", headers=chaves).json() == []

    r = cliente.post(f"{API}/escolas/{nova}/usuarios", headers=chaves, json=_coordenador())
    assert r.status_code == 201, r.text
    corpo = r.json()
    assert corpo["cargo"] == "coordenador"
    assert corpo["escola_id"] == nova                      # vinculado à escola aberta
    assert corpo["is_global"] is False and corpo["rede_id"] is None
    assert corpo["status"] == "ativo"

    criado = db.get(Usuario, corpo["id"])
    assert criado.escola_id == nova and not criado.is_global and criado.rede_id is None

    # A conta já entra e enxerga a própria escola (sem nada acadêmico).
    chaves_coord = _login(cliente, "coord@nova.escola.br")
    eu = cliente.get(f"{API}/auth/me", headers=chaves_coord)
    assert eu.status_code == 200 and eu.json()["escola_id"] == nova
    assert cliente.get(f"{API}/escolas/{nova}/usuarios", headers=chaves_coord).status_code == 200

    # Auditoria preservada (sem senha no log).
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.escola_id == nova, LogAuditoria.acao == "usuario.criado")).scalars().one()
    assert log.entidade_id == criado.id and log.detalhes["cargo"] == "coordenador"
    assert "senha" not in str(log.detalhes).lower()


def test_usuario_nao_recebe_escopo_global_mesmo_que_o_corpo_peca(cliente, db, escola_completa):
    chaves = _login(cliente, _global(db)["email"])
    nova = _escola_vazia(cliente, chaves)
    r = cliente.post(f"{API}/escolas/{nova}/usuarios", headers=chaves, json={
        **_coordenador("ambicioso@nova.escola.br"),
        "is_global": True, "rede_id": 1, "escola_id": escola_completa["escola"].id})
    assert r.status_code == 201, r.text
    criado = db.get(Usuario, r.json()["id"])
    assert criado.is_global is False and criado.rede_id is None
    assert criado.escola_id == nova                        # o corpo NÃO redireciona a escola
    # e a escola vizinha continua sem esse usuário
    assert criado.id not in {u["id"] for u in cliente.get(
        f"{API}/escolas/{escola_completa['escola'].id}/usuarios", headers=chaves).json()}


# --- 5: quem não é admin/global não cria usuário administrativo ---

def test_sem_permissao_nao_cria_usuario_administrativo(cliente, db, escola_completa):
    chaves_global = _login(cliente, _global(db)["email"])
    nova = _escola_vazia(cliente, chaves_global)
    escola = escola_completa["escola"]

    # coordenador e professor da escola 1 (criados pelo admin local da fixture)
    for cargo, email in (("coordenador", "coord@escola.com.br"), ("professor", "prof@escola.com.br")):
        r = cliente.post(f"{API}/escolas/{escola.id}/usuarios",
                         json={"nome": cargo.title(), "email": email, "senha": SENHA, "cargo": cargo})
        assert r.status_code == 201, r.text
        chaves = _login(cliente, email)
        # nem na própria escola (exige admin)…
        assert cliente.post(f"{API}/escolas/{escola.id}/usuarios", headers=chaves,
                            json=_coordenador(f"x-{cargo}@nova.escola.br")).status_code == 403
        # …nem na escola nova (fora do escopo)
        assert cliente.post(f"{API}/escolas/{nova}/usuarios", headers=chaves,
                            json=_coordenador(f"y-{cargo}@nova.escola.br")).status_code == 403

    # admin LOCAL de outra escola não alcança a escola nova (escopo por escola).
    # (`cliente` sem headers = o admin local da escola 1 da fixture, conftest.py)
    assert cliente.post(f"{API}/escolas/{nova}/usuarios",
                        json=_coordenador("z@nova.escola.br")).status_code == 403
    # anônimo
    assert cliente.post(f"{API}/escolas/{nova}/usuarios", headers={"Authorization": ""},
                        json=_coordenador("w@nova.escola.br")).status_code == 401
    assert cliente.get(f"{API}/escolas/{nova}/usuarios", headers=chaves_global).json() == []


# --- 6: unicidade de e-mail/login continua valendo ---

def test_email_e_login_duplicados_continuam_rejeitados(cliente, db, escola_completa):
    chaves = _login(cliente, _global(db)["email"])
    nova = _escola_vazia(cliente, chaves)
    outra = _escola_vazia(cliente, chaves, nome="OUTRA ESCOLA NOVA")
    ok = cliente.post(f"{API}/escolas/{nova}/usuarios", headers=chaves,
                      json={**_coordenador(), "username": "coord.nova"})
    assert ok.status_code == 201, ok.text
    # mesmo e-mail (com maiúsculas) → 409, inclusive noutra escola
    dup = cliente.post(f"{API}/escolas/{outra}/usuarios", headers=chaves,
                       json=_coordenador("COORD@nova.escola.br"))
    assert dup.status_code == 409, dup.text
    # mesmo @ → 409
    dup_login = cliente.post(f"{API}/escolas/{outra}/usuarios", headers=chaves,
                             json={**_coordenador("outro@nova.escola.br"), "username": "Coord.Nova"})
    assert dup_login.status_code == 409, dup_login.text
    # senha fraca continua recusada — e o motivo chega legível (detail em lista)
    fraca = cliente.post(f"{API}/escolas/{outra}/usuarios", headers=chaves,
                         json={**_coordenador("fraca@nova.escola.br"), "senha": "12345678"})
    assert fraca.status_code == 422, fraca.text
    assert any("senha" in str(item.get("msg", "")).lower() for item in fraca.json()["detail"])

    # homônimo de conta EXCLUÍDA (soft delete) ou inativa não é reativado nem
    # recriado por baixo dos panos: o e-mail segue ocupado → 409, nada muda na conta.
    alvo = ok.json()["id"]
    assert cliente.delete(f"{API}/escolas/{nova}/usuarios/{alvo}", headers=chaves).status_code == 200
    db.expire_all()
    assert db.get(Usuario, alvo).status == "excluido"
    repetido = cliente.post(f"{API}/escolas/{outra}/usuarios", headers=chaves, json=_coordenador())
    assert repetido.status_code == 409, repetido.text
    db.expire_all()
    assert db.get(Usuario, alvo).status == "excluido"          # não ressuscitou
    assert db.get(Usuario, alvo).escola_id == nova             # nem mudou de escola


# --- 7: escola já inicializada (Lista Piloto/turmas) segue funcionando ---

def test_escola_com_lista_piloto_iniciada_continua_aceitando_usuarios(cliente, db, escola_completa):
    escola = escola_completa["escola"]            # tem turma e alunos (Lista Piloto "iniciada")
    chaves = _login(cliente, _global(db)["email"])
    status = cliente.get(f"{API}/escolas/{escola.id}/sync/status", headers=chaves).json()
    assert status["lista_piloto_importada"] is True
    r = cliente.post(f"{API}/escolas/{escola.id}/usuarios", headers=chaves,
                     json=_coordenador("coord2@escola.com.br"))
    assert r.status_code == 201, r.text
    assert r.json()["escola_id"] == escola.id
    # e o admin local da própria escola também continua criando
    r2 = cliente.post(f"{API}/escolas/{escola.id}/usuarios",
                      json=_coordenador("coord3@escola.com.br"))
    assert r2.status_code == 201, r2.text
