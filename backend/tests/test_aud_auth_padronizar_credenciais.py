"""AUTH-4: "Padronizar @" e "Corrigir professores duplicados" trocam a senha de
uma conta de professor nunca usada e entregam a nova na folha. Duas garantias:

* o link de redefinição PENDENTE da conta morre junto (a mesma regra da troca
  de senha pelo admin): senão quem tivesse o link antigo sobrescrevia a senha
  que o gestor acabou de entregar;
* o e-mail de login REAL (cadastro completo de professor) fica: só o e-mail
  gerado pelo sistema (``@professor.constelaedu.com``) acompanha o @ novo. Antes
  o e-mail real sumia da conta e do cadastro, sem cópia e sem aviso.

Dados fictícios."""
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_senha
from app.main import app
from app.models import Professor, Usuario

API = "/api/v1"


def _valido(token: str) -> bool:
    return TestClient(app).get(f"{API}/auth/redefinir-senha/{token}").json()["valido"]


def _login(usuario: str, senha: str) -> int:
    return TestClient(app).post(f"{API}/auth/login",
                                data={"username": usuario, "password": senha}).status_code


def _cadastro_completo(cliente, eid: int, nome: str, email: str) -> dict:
    r = cliente.post(f"{API}/escolas/{eid}/professores/completo",
                     json={"nome": nome, "email": email})
    assert r.status_code == 201, r.text
    return r.json()


def _link_pendente(cliente, db, eid: int, email: str) -> tuple[int, str]:
    conta = db.execute(select(Usuario).where(Usuario.email == email)).scalar_one()
    r = cliente.post(f"{API}/escolas/{eid}/usuarios/{conta.id}/redefinir-senha")
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    assert _valido(token)
    return conta.id, token


def _linha(folha: list[dict], nome: str) -> dict:
    linhas = [f for f in folha if f["nome"] == nome]
    assert len(linhas) == 1, folha
    return linhas[0]


# --- Padronizar @ -------------------------------------------------------------

def test_padronizar_mata_o_link_pendente_da_conta_que_ganha_senha_nova(
        cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    email = "rosana.sonda@escola-ficticia.com.br"
    _cadastro_completo(cliente, eid, "Rosana Sonda Ficticia", email)
    _, token = _link_pendente(cliente, db, eid, email)

    r = cliente.post(f"{API}/escolas/{eid}/professores/padronizar-usuarios")
    assert r.status_code == 200, r.text
    linha = _linha(r.json()["folha"], "Rosana Sonda Ficticia")
    assert linha["senha"], "a conta nunca usada deveria ganhar senha nova"
    assert _login(linha["usuario"], linha["senha"]) == 200
    assert not _valido(token), (
        "o link pendente sobreviveu à troca de senha da padronização")


def test_padronizar_mantem_o_email_real_de_login(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    email = "marta.sonda@escola-ficticia.com.br"
    _cadastro_completo(cliente, eid, "Marta Sonda Ficticia", email)

    r = cliente.post(f"{API}/escolas/{eid}/professores/padronizar-usuarios")
    assert r.status_code == 200, r.text
    linha = _linha(r.json()["folha"], "Marta Sonda Ficticia")
    assert linha["usuario"] == "MartaFicticia" and linha["senha"]

    db.expire_all()
    conta = db.execute(select(Usuario).where(
        Usuario.username == "MartaFicticia")).scalar_one()
    assert conta.email == email, (
        "padronizar o @ trocou o e-mail REAL de login por " + str(conta.email))
    prof = db.execute(select(Professor).where(
        Professor.nome == "Marta Sonda Ficticia")).scalar_one()
    assert prof.email == email          # o vínculo com as turmas segue pelo e-mail
    # A senha da folha entra pelo @ novo e pelo e-mail de sempre.
    assert _login("MartaFicticia", linha["senha"]) == 200
    assert _login(email, linha["senha"]) == 200


def test_padronizar_email_gerado_pelo_sistema_acompanha_o_novo_arroba(
        db, escola_completa):
    """Sem mudança para a conta criada pela importação: o e-mail dela é o
    gerado a partir do @ e continua acompanhando o @ novo."""
    from app.services import professores as P
    escola = escola_completa["escola"]
    prof = Professor(escola_id=escola.id, nome="Telma Sonda Testelli",
                     email="telma@professor.constelaedu.com")
    db.add(prof)
    db.add(Usuario(escola_id=escola.id, nome="Telma Sonda Testelli",
                   email="telma@professor.constelaedu.com", username="Telma",
                   senha_hash=hash_senha("x"), cargo="professor"))
    db.commit()

    folha = P.padronizar_usernames(db, escola.id)
    db.commit()

    assert _linha(folha, "Telma Sonda Testelli")["usuario"] == "TelmaTestelli"
    conta = db.execute(select(Usuario).where(
        Usuario.username == "TelmaTestelli")).scalar_one()
    db.refresh(prof)
    assert conta.email == "telmatestelli@professor.constelaedu.com"
    assert prof.email == conta.email


# --- Corrigir professores duplicados -----------------------------------------

def _duplicado_curto(db, eid: int, nome: str) -> int:
    """O cadastro curto (só o primeiro nome) que a importação do Matific criava."""
    email = f"{nome.lower()}@professor.constelaedu.com"
    curto = Professor(escola_id=eid, nome=nome, email=email)
    db.add(curto)
    db.add(Usuario(escola_id=eid, nome=nome, email=email, username=nome,
                   senha_hash=hash_senha("x"), cargo="professor"))
    db.commit()
    return curto.id


def test_corrigir_duplicados_mata_o_link_pendente_da_conta_que_fica(
        cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    email = "celia.sonda@escola-ficticia.com.br"
    _cadastro_completo(cliente, eid, "Celia Sonda Ficticia", email)
    loser = _duplicado_curto(db, eid, "Celia")
    _, token = _link_pendente(cliente, db, eid, email)

    r = cliente.post(f"{API}/escolas/{eid}/professores/duplicados/corrigir",
                     json={"loser_ids": [loser]})
    assert r.status_code == 200, r.text
    linha = _linha(r.json()["folha"], "Celia Sonda Ficticia")
    assert linha["senha"], "a conta nunca usada deveria ganhar senha nova"
    assert _login(linha["usuario"], linha["senha"]) == 200
    assert not _valido(token), (
        "o link pendente sobreviveu à troca de senha da fusão de duplicados")


def test_corrigir_duplicados_mantem_o_email_real_da_conta_que_fica(
        cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    email = "dalva.sonda@escola-ficticia.com.br"
    _cadastro_completo(cliente, eid, "Dalva Sonda Ficticia", email)
    loser = _duplicado_curto(db, eid, "Dalva")

    r = cliente.post(f"{API}/escolas/{eid}/professores/duplicados/corrigir",
                     json={"loser_ids": [loser]})
    assert r.status_code == 200, r.text
    linha = _linha(r.json()["folha"], "Dalva Sonda Ficticia")
    assert linha["usuario"] == "DalvaFicticia" and linha["senha"]

    db.expire_all()
    conta = db.execute(select(Usuario).where(
        Usuario.username == "DalvaFicticia")).scalar_one()
    assert conta.email == email, (
        "a fusão trocou o e-mail REAL de login por " + str(conta.email))
    fica = db.execute(select(Professor).where(
        Professor.nome == "Dalva Sonda Ficticia")).scalar_one()
    assert fica.email == email
    assert db.get(Professor, loser) is None
    assert _login(email, linha["senha"]) == 200
