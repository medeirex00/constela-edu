"""Conta nova de professor, de ponta a ponta — da importação ao login.

    IMPORTAÇÃO → conta ativa SEM senha conhecida → coordenação gera o link →
    o professor define a senha → login (pelo @, sem diferenciar caixa) →
    sessão vale → nova redefinição → a sessão antiga cai.

Garante as duas metades da política da Fase 3A: nenhuma senha previsível abre
a conta, e a conta nunca fica sem caminho de acesso. Dados sintéticos.
"""
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_senha
from app.main import app
from app.models import LogAuditoria, Usuario
from app.services import professores

SENHA_GESTAO = "s3nh4-sintetica"


def _login(usuario: str, senha: str):
    return TestClient(app).post("/api/v1/auth/login",
                                data={"username": usuario, "password": senha})


def _cliente(usuario: str, senha: str) -> TestClient:
    r = _login(usuario, senha)
    assert r.status_code == 200, r.text
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _gerar_link(cliente: TestClient, escola_id: int, usuario_id: int) -> str:
    r = cliente.post(f"/api/v1/escolas/{escola_id}/usuarios/{usuario_id}/redefinir-senha")
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _definir(token: str, senha: str):
    return TestClient(app).post("/api/v1/auth/redefinir-senha",
                                json={"token": token, "nova_senha": senha})


def test_da_importacao_ao_login_pelo_link(db, escola_completa):
    escola = escola_completa["escola"]
    db.add(Usuario(escola_id=escola.id, nome="COORD_SINT", email="coord.sint@teste.local",
                   senha_hash=hash_senha(SENHA_GESTAO), cargo="coordenador"))
    professores.garantir_professor(db, escola.id, "Regiane Sint Sousa")
    db.commit()
    conta = db.execute(select(Usuario).where(Usuario.username == "RegianeSousa")).scalar_one()

    # 1. A conta nasce ATIVA, de professor, e nenhuma senha previsível a abre.
    assert (conta.status, conta.cargo) == ("ativo", "professor")
    previsiveis = professores._senhas_da_convencao_antiga(conta.nome, conta.username)
    previsiveis |= {"regiane123", "sousa123", "regianesousa", "12345678", conta.email}
    for senha in previsiveis:
        assert _login("RegianeSousa", senha).status_code == 401, senha

    # 2. Há caminho de acesso: a coordenação gera o link de uso único.
    coord = _cliente("coord.sint@teste.local", SENHA_GESTAO)
    token = _gerar_link(coord, escola.id, conta.id)
    assert TestClient(app).get(f"/api/v1/auth/redefinir-senha/{token}").json()["valido"] is True

    # 3. O professor escolhe a senha — e o link morre no primeiro uso.
    assert _definir(token, "farol-cedro-lua-38").status_code == 200
    assert _definir(token, "outra-senha-qualquer-91").status_code == 400

    # 4. Login pelo @ (sem diferenciar caixa) e a sessão vale.
    sessao_antiga = _cliente("regianesousa", "farol-cedro-lua-38")
    assert sessao_antiga.get("/api/v1/auth/me").status_code == 200

    # 5. Nova redefinição (pela administração): a sessão antiga cai e a senha
    #    anterior deixa de valer.
    admin = _cliente("admin@teste.local", "s3nh4")
    token2 = _gerar_link(admin, escola.id, conta.id)
    assert _definir(token2, "brisa-pinho-onda-15").status_code == 200
    assert sessao_antiga.get("/api/v1/auth/me").status_code == 401
    assert _login("RegianeSousa", "farol-cedro-lua-38").status_code == 401
    assert _login("RegianeSousa", "brisa-pinho-onda-15").status_code == 200

    # 6. Tudo auditado — e nem o token nem a senha entram na auditoria.
    logs = db.execute(select(LogAuditoria).where(
        LogAuditoria.entidade_id == conta.id)).scalars().all()
    acoes = [l.acao for l in logs]
    assert acoes.count("usuario.reset_solicitado") == 2
    assert acoes.count("usuario.senha_redefinida_por_token") == 2
    for log in logs:
        texto = str(log.detalhes)
        for segredo in (token, token2, "farol-cedro-lua-38", "brisa-pinho-onda-15"):
            assert segredo not in texto


def test_professor_nao_gera_link_de_colega_nem_a_importacao_reaproveita_conta(
        db, escola_completa):
    """O link é o único caminho de acesso — então ele não pode virar porta de
    tomada de conta: professor só gera para si; e reimportar o mesmo nome não
    cria segunda conta nem troca a senha de quem já entrou."""
    escola = escola_completa["escola"]
    professores.garantir_professor(db, escola.id, "Paula Sint Vilela")
    professores.garantir_professor(db, escola.id, "Sueli Sint Prado")
    db.commit()
    paula = db.execute(select(Usuario).where(Usuario.username == "PaulaVilela")).scalar_one()
    sueli = db.execute(select(Usuario).where(Usuario.username == "SueliPrado")).scalar_one()

    admin = _cliente("admin@teste.local", "s3nh4")
    assert _definir(_gerar_link(admin, escola.id, paula.id), "lago-figo-mar-27").status_code == 200
    db.refresh(paula)
    hash_escolhido = paula.senha_hash

    prof = _cliente("PaulaVilela", "lago-figo-mar-27")
    assert prof.post(f"/api/v1/escolas/{escola.id}/usuarios/{sueli.id}/redefinir-senha"
                     ).status_code == 403
    assert prof.post(f"/api/v1/escolas/{escola.id}/usuarios/{paula.id}/redefinir-senha"
                     ).status_code == 200

    _, criado = professores.garantir_professor(db, escola.id, "PAULA SINT VILELA")
    db.commit()
    db.refresh(paula)
    assert criado is False
    assert paula.senha_hash == hash_escolhido
    assert db.execute(select(Usuario).where(Usuario.nome.ilike("%vilela%"))).scalars().all() == [paula]


def test_a_senha_da_convencao_antiga_nao_volta_por_nenhum_caminho(db, escola_completa):
    """Depois da migração, quem se acostumou à regra antiga tenderia a escolhê-la
    de novo — e a conta voltaria a ser calculável pelo nome. Nenhum caminho de
    definir senha aceita: link, edição pela administração e criação manual."""
    escola = escola_completa["escola"]
    professores.garantir_professor(db, escola.id, "Joana Sint Lima")
    db.commit()
    conta = db.execute(select(Usuario).where(Usuario.username == "JoanaLima")).scalar_one()
    admin = _cliente("admin@teste.local", "s3nh4")

    token = _gerar_link(admin, escola.id, conta.id)
    assert TestClient(app).get(f"/api/v1/auth/redefinir-senha/{token}").json()["nome"] == "Joana"
    for senha in ("joanalima123", "Joana123", "JOANALIMA123"):
        r = _definir(token, senha)
        assert r.status_code == 422 and "padrão" in r.text, senha
    # A recusa não gasta o link: o professor tenta de novo com uma senha boa.
    assert _definir(token, "ilha-cedro-mar-64").status_code == 200

    url = f"/api/v1/escolas/{escola.id}/usuarios"
    r = admin.patch(f"{url}/{conta.id}", json={"senha": "joanalima123"})
    assert r.status_code == 422 and "padrão" in r.text
    nova = {"nome": "Marta Sint Rocha", "email": "marta.sint@constela-sint.com.br",
            "username": "martarocha", "cargo": "professor"}
    for senha in ("martarocha123", "Marta123"):
        r = admin.post(url, json={**nova, "senha": senha})
        assert r.status_code == 422 and "padrão" in r.text, senha
    assert admin.post(url, json={**nova, "senha": "lousa-figo-rio-58"}).status_code == 201


def test_a_importacao_nao_ensina_mais_a_senha_antiga(cliente, db, escola_completa):
    """A mensagem da Lista Piloto dizia ao gestor que a senha era 'Primeiro nome
    + 123' — falso desde a Fase 3A e ainda divulgava a regra."""
    from tests.test_lista_piloto import _upload
    escola_id = escola_completa["escola"].id
    r = cliente.post(f"/api/v1/escolas/{escola_id}/importacoes/matriculas/confirmar",
                     files=_upload())
    assert r.status_code == 200, r.text
    mensagem = r.json()["mensagem"]
    assert "ganharam conta de acesso" in mensagem
    assert "123" not in mensagem and "link de redefinição" in mensagem
