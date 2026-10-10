"""P0 — o e-mail de um Professor não reescreve o login de conta alheia.

Acompanha `P0_academico.patch` (routers/academico.py) e
`P0b_servicos_professores.patch` (services/professores.py). Copiar para
backend/tests/ JUNTO com os dois patches.

A regra (autorização SÓ no servidor — escopo da rota + tipo da conta):
  * a única conta cujo login acompanha o e-mail de um Professor é a conta de
    PROFESSOR desta escola (cargo professor, mesma escola, sem rede, não global);
  * um Professor só recebe e-mail livre ou o da conta de professor desta escola;
  * o e-mail reservado ao dono (ADMIN_GLOBAL_EMAIL) nunca entra por Professor —
    nem pelo admin global (a conta que acompanha o Professor tem a senha do
    professor e o boot a promoveria a is_global);
  * colisão com o login (e-mail ou @username, sem diferenciar caixa) de outra
    conta → 409;
  * a fusão de duplicados só apaga/reescreve conta de professor desta escola.

Mundo sintético de `test_isolamento_escopo` (nenhum dado real). As contas do
mundo têm e-mail `@sint.local`, que o EmailStr recusa: quando a conta-alvo
precisa ser enviada pelo corpo, o teste troca o e-mail dela por um domínio
sintético válido ANTES (o ator já logou com o e-mail original).
"""
import pytest
from fastapi.testclient import TestClient

from tests._mundo_sintetico import SENHA, mundo  # noqa: F401  (fixture)
from app.core.config import settings
from app.core.security import hash_senha
from app.main import app
from app.models import Professor, Usuario

DONO = "dono.sint@constela-sint.com.br"


# --- utilitários --------------------------------------------------------------

def _url(mundo, resto, escola="x"):
    return f"/api/v1/escolas/{mundo.ids[escola]}{resto}"


def _email_valido(mundo, chave, email):
    """Dá à conta `u_<chave>` um e-mail que o validador aceita (domínio sintético)."""
    u = mundo.db.get(Usuario, mundo.ids["u_" + chave])
    u.email = email
    mundo.db.commit()
    return u


def _retrato(mundo, chave):
    mundo.db.expire_all()
    u = mundo.db.get(Usuario, mundo.ids["u_" + chave])
    return None if u is None else (u.email, u.username, u.senha_hash, u.is_global,
                                   u.cargo, u.escola_id, u.rede_id)


def _legado(mundo, nome, email, escola="x"):
    """Professor gravado DIRETO no banco (dado legado/pré-patch) — é o cenário
    em que a rota de criação já não barra mais nada."""
    p = Professor(escola_id=mundo.ids[escola], nome=nome, email=email)
    mundo.db.add(p)
    mundo.db.commit()
    return p.id


def _login(identificador, senha=SENHA):
    return TestClient(app).post("/api/v1/auth/login",
                                data={"username": identificador, "password": senha})


# --- NEGATIVOS: criação ------------------------------------------------------

@pytest.mark.parametrize("alvo, email", [
    ("coord_y", "coord.y@constela-sint.com.br"),        # outra escola
    ("global", "global.sint@constela-sint.com.br"),     # admin global
    ("sec_r1", "sec.r1@constela-sint.com.br"),          # Secretaria (sem escola)
    ("secadm_x", "sec.hospedada@constela-sint.com.br"),  # Secretaria com escola X de origem
    ("admin_x", "admin.x@constela-sint.com.br"),        # gestão da MESMA escola
])
@pytest.mark.parametrize("rota", ["simples", "completo_sem_acesso", "completo_com_acesso"])
def test_criar_professor_com_login_de_outra_conta_e_recusado(mundo, alvo, email, rota):
    cli = mundo.cli("coord_x")
    _email_valido(mundo, alvo, email)
    antes = _retrato(mundo, alvo)
    if rota == "simples":
        r = cli.post(_url(mundo, "/professores"), json={"nome": "ESPELHO_SINT", "email": email})
    else:
        r = cli.post(_url(mundo, "/professores/completo"),
                     json={"nome": "Espelho Sint", "email": email,
                           "criar_acesso": rota == "completo_com_acesso"})
    assert r.status_code == 409, r.text
    assert _retrato(mundo, alvo) == antes
    assert mundo.db.query(Professor).filter(Professor.email.ilike(email)).count() == 0


@pytest.mark.parametrize("variante", [
    "COORD.Y@Constela-Sint.com.br",           # caixa
    "  coord.y@constela-sint.com.br  ",       # espaços (o EmailStr apara)
    "Coord.Y@CONSTELA-SINT.COM.BR",
])
def test_colisao_ignora_caixa_e_espacos(mundo, variante):
    cli = mundo.cli("coord_x")
    _email_valido(mundo, "coord_y", "coord.y@constela-sint.com.br")
    antes = _retrato(mundo, "coord_y")
    r = cli.post(_url(mundo, "/professores"), json={"nome": "ESPELHO_SINT", "email": variante})
    assert r.status_code == 409, r.text
    pa = mundo.db.query(Professor).filter_by(nome="PROF_A_SINT").one()
    r = cli.patch(_url(mundo, f"/professores/{pa.id}"), json={"email": variante})
    assert r.status_code == 409, r.text
    assert _retrato(mundo, "coord_y") == antes


def test_username_de_outra_conta_tambem_colide(mundo):
    """O login aceita e-mail OU @username. A API não deixa um @ com "@", mas um
    dado legado pode ter — o e-mail novo não pode virar o login de outra conta."""
    db = mundo.db
    cli = mundo.cli("coord_x")
    legado = Usuario(escola_id=mundo.ids["y"], nome="LEGADO_SINT", email="legado@sint.local",
                     username="legado@constela-sint.com.br", senha_hash=hash_senha(SENHA),
                     cargo="coordenador")
    db.add(legado)
    db.commit()
    r = cli.post(_url(mundo, "/professores"),
                 json={"nome": "ESPELHO_SINT", "email": "LEGADO@constela-sint.com.br"})
    assert r.status_code == 409, r.text
    pa = db.query(Professor).filter_by(nome="PROF_A_SINT").one()
    r = cli.patch(_url(mundo, f"/professores/{pa.id}"),
                  json={"email": "legado@constela-sint.com.br"})
    assert r.status_code == 409, r.text
    db.expire_all()
    assert db.get(Usuario, mundo.ids["u_prof_a"]).email == "prof_a@sint.local"


@pytest.mark.parametrize("ator", ["coord_x", "global"])
def test_email_reservado_ao_dono_nunca_entra_por_professor(mundo, monkeypatch, ator):
    cli = mundo.cli(ator)
    monkeypatch.setattr(settings, "ADMIN_GLOBAL_EMAIL", DONO)
    for corpo, rota in (({"nome": "E_SINT", "email": DONO}, "/professores"),
                        ({"nome": "E Sint", "email": DONO.upper(), "criar_acesso": False},
                         "/professores/completo"),
                        ({"nome": "E Sint", "email": DONO, "criar_acesso": True},
                         "/professores/completo")):
        r = cli.post(_url(mundo, rota), json=corpo)
        assert r.status_code == 403, (rota, r.text)
    pa = mundo.db.query(Professor).filter_by(nome="PROF_A_SINT").one()
    r = cli.patch(_url(mundo, f"/professores/{pa.id}"), json={"email": DONO})
    assert r.status_code == 403, r.text
    mundo.db.expire_all()
    assert mundo.db.get(Usuario, mundo.ids["u_prof_a"]).email == "prof_a@sint.local"
    assert mundo.db.query(Usuario).filter(Usuario.email.ilike(DONO)).count() == 0


# --- NEGATIVOS: edição -------------------------------------------------------

@pytest.mark.parametrize("alvo", ["coord_y", "admin_x", "global", "sec_r1", "secadm_x"])
def test_editar_cadastro_legado_nao_reescreve_conta_alheia(mundo, alvo):
    """Professor (legado) gravado com o e-mail de uma conta que não é a de
    professor desta escola: a edição muda só o cadastro, nunca o login dela."""
    cli = mundo.cli("coord_x")
    antes = _retrato(mundo, alvo)
    pid = _legado(mundo, f"LEGADO_{alvo}", antes[0])
    r = cli.patch(_url(mundo, f"/professores/{pid}"),
                  json={"email": f"novo.{alvo.replace('_', '')}@constela-sint.com.br"})
    assert r.status_code == 200, r.text
    assert _retrato(mundo, alvo) == antes
    # o dono legítimo continua entrando com o login de sempre
    assert _login(antes[0]).status_code == 200


def test_editar_para_login_de_outra_conta_409_e_nada_muda(mundo):
    cli = mundo.cli("coord_x")
    _email_valido(mundo, "coord_y", "coord.y@constela-sint.com.br")
    _email_valido(mundo, "prof_b", "prof.b@constela-sint.com.br")
    pa = mundo.db.query(Professor).filter_by(nome="PROF_A_SINT").one()
    for email in ("coord.y@constela-sint.com.br",   # outra escola
                  "prof.b@constela-sint.com.br"):   # outra conta de professor da escola
        r = cli.patch(_url(mundo, f"/professores/{pa.id}"), json={"email": email})
        assert r.status_code == 409, (email, r.text)
    mundo.db.expire_all()
    assert mundo.db.get(Usuario, mundo.ids["u_prof_a"]).email == "prof_a@sint.local"
    assert mundo.db.get(Professor, pa.id).email == "prof_a@sint.local"


def test_professor_sem_conta_nao_vira_espelho_de_gestao(mundo):
    """Professor SEM conta não pode receber o e-mail de uma conta de gestão da
    própria escola (seria o espelho que a fusão de duplicados apagaria)."""
    cli = mundo.cli("coord_x")
    _email_valido(mundo, "admin_x", "admin.x@constela-sint.com.br")
    r = cli.post(_url(mundo, "/professores"), json={"nome": "SEM_CONTA_SINT"})
    assert r.status_code == 201, r.text
    r = cli.patch(_url(mundo, f"/professores/{r.json()['id']}"),
                  json={"email": "admin.x@constela-sint.com.br"})
    assert r.status_code == 409, r.text


def test_email_vazio_ou_nulo(mundo):
    cli = mundo.cli("coord_x")
    pa = mundo.db.query(Professor).filter_by(nome="PROF_A_SINT").one()
    assert cli.patch(_url(mundo, f"/professores/{pa.id}"), json={"email": ""}).status_code == 422
    assert cli.post(_url(mundo, "/professores"),
                    json={"nome": "X_SINT", "email": ""}).status_code == 422
    assert cli.post(_url(mundo, "/professores/completo"),
                    json={"nome": "X Sint", "email": "", "criar_acesso": False}).status_code == 422
    # null = "não mexer no e-mail" (só o nome muda)
    r = cli.patch(_url(mundo, f"/professores/{pa.id}"),
                  json={"email": None, "nome": "PROF_A_SINT_NOVO"})
    assert r.status_code == 200, r.text
    mundo.db.expire_all()
    assert mundo.db.get(Professor, pa.id).email == "prof_a@sint.local"
    assert mundo.db.get(Usuario, mundo.ids["u_prof_a"]).email == "prof_a@sint.local"


# --- NEGATIVO: fusão de duplicados (services/professores.py) -----------------

def test_fusao_nao_apaga_nem_reescreve_conta_de_rede_ou_de_gestao(mundo):
    """Cadastros legados com o e-mail da Secretaria hospedada na escola X e do
    coordenador da X: a fusão (admin da escola) não apaga nem reescreve essas
    contas e não devolve senha delas na folha."""
    adm = mundo.cli("admin_x")
    sec_antes = _retrato(mundo, "secadm_x")
    coord_antes = _retrato(mundo, "coord_x")
    # Secretaria como SOBREVIVENTE (seria reescrita) e coordenador como
    # DUPLICADO (seria apagado).
    _legado(mundo, "MARIA SINT SILVA", sec_antes[0])
    l1 = _legado(mundo, "MARIA", "maria.curta@constela-sint.com.br")
    l2 = _legado(mundo, "JOANA", coord_antes[0])
    _legado(mundo, "JOANA SINT SOUZA", "joana.sint@constela-sint.com.br")
    r = adm.post(_url(mundo, "/professores/duplicados/corrigir"), json={"loser_ids": [l1, l2]})
    assert r.status_code == 200, r.text
    assert all(f.get("senha") is None for f in r.json()["folha"]), r.json()
    assert _retrato(mundo, "secadm_x") == sec_antes
    assert _retrato(mundo, "coord_x") == coord_antes


# --- ESCALADA: a cena C da etapa 4 ------------------------------------------

def test_cena_C_coordenador_nao_vira_admin_global_no_boot(mundo, monkeypatch):
    """Cadeia completa da etapa 4: tirar o e-mail do dono da conta global e pô-lo
    numa conta cuja senha o coordenador conhece, por TODAS as portas (as duas
    rotas de criação e, se recusarem, um cadastro legado gravado direto no
    banco). As portas têm testes próprios acima; aqui se exige o RESULTADO:
    depois do boot (`_promover_admin_global`, a mesma função do startup) só a
    conta do dono é global, com o e-mail dela, e o coordenador segue preso à
    escola X."""
    from app.core.database import _promover_admin_global

    db = mundo.db
    cli = mundo.cli("coord_x")
    monkeypatch.setattr(settings, "ADMIN_GLOBAL_EMAIL", DONO)
    _email_valido(mundo, "global", DONO)
    _email_valido(mundo, "coord_x", "coord.x@constela-sint.com.br")

    def espelhos(email):
        ids = []
        for rota, corpo in (("/professores", {"nome": "ESPELHO", "email": email}),
                            ("/professores/completo",
                             {"nome": "Espelho Sint", "email": email, "criar_acesso": False})):
            r = cli.post(_url(mundo, rota), json=corpo)
            if r.status_code == 201:
                ids.append(r.json().get("id") or r.json()["professor"]["id"])
        ids.append(_legado(mundo, "ESPELHO_LEGADO", email))
        return ids

    # 1) tirar o e-mail do dono da conta global
    for pid in espelhos(DONO):
        cli.patch(_url(mundo, f"/professores/{pid}"),
                  json={"email": f"dono.sumiu.{pid}@atacante-sint.com.br"})
    # 2) pôr o e-mail do dono na PRÓPRIA conta do coordenador...
    for pid in espelhos("coord.x@constela-sint.com.br"):
        cli.patch(_url(mundo, f"/professores/{pid}"), json={"email": DONO})
    # ...ou numa conta de professor criada por ele (senha conhecida)
    r = cli.post(_url(mundo, "/professores/completo"),
                 json={"nome": "Cumplice Sint", "email": "cumplice@atacante-sint.com.br",
                       "criar_acesso": True})
    assert r.status_code == 201, r.text
    cli.patch(_url(mundo, f"/professores/{r.json()['professor']['id']}"), json={"email": DONO})

    # 3) reboot
    _promover_admin_global(motor=db.get_bind())
    db.expire_all()
    globais = {u.id for u in db.query(Usuario).filter(Usuario.is_global.is_(True))}
    assert globais == {mundo.ids["u_global"]}
    g = db.get(Usuario, mundo.ids["u_global"])
    assert g.email == DONO and g.is_global is True
    c = db.get(Usuario, mundo.ids["u_coord_x"])
    assert c.email == "coord.x@constela-sint.com.br" and c.is_global is False
    assert cli.get(_url(mundo, "/professores", escola="y")).status_code == 403


# --- POSITIVOS ---------------------------------------------------------------

def test_coordenador_muda_email_do_proprio_professor_e_a_conta_acompanha(mundo):
    cli = mundo.cli("coord_x")
    pa = mundo.db.query(Professor).filter_by(nome="PROF_A_SINT").one()
    r = cli.patch(_url(mundo, f"/professores/{pa.id}"),
                  json={"email": "Prof.A.Novo@Constela-Sint.com.br"})
    assert r.status_code == 200, r.text
    mundo.db.expire_all()
    assert mundo.db.get(Usuario, mundo.ids["u_prof_a"]).email == "prof.a.novo@constela-sint.com.br"
    assert mundo.db.get(Professor, pa.id).email == "prof.a.novo@constela-sint.com.br"
    assert _login("prof.a.novo@constela-sint.com.br").status_code == 200
    assert _login("prof_a@sint.local").status_code == 401


def test_admin_global_muda_email_de_professor(mundo):
    cli = mundo.cli("global")
    pb = mundo.db.query(Professor).filter_by(nome="PROF_B_SINT").one()
    r = cli.patch(_url(mundo, f"/professores/{pb.id}"),
                  json={"email": "prof.b.novo@constela-sint.com.br"})
    assert r.status_code == 200, r.text
    mundo.db.expire_all()
    assert mundo.db.get(Usuario, mundo.ids["u_prof_b"]).email == "prof.b.novo@constela-sint.com.br"


def test_professor_sem_conta_cadastra_e_edita_email_livre(mundo):
    cli = mundo.cli("coord_x")
    contas_antes = mundo.db.query(Usuario).count()
    r = cli.post(_url(mundo, "/professores"), json={"nome": "SEM_CONTA_SINT"})
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    for email in ("sem.conta@constela-sint.com.br", "sem.conta.2@constela-sint.com.br"):
        r = cli.patch(_url(mundo, f"/professores/{pid}"), json={"email": email})
        assert r.status_code == 200, r.text
        assert r.json()["email"] == email
    r = cli.post(_url(mundo, "/professores/completo"),
                 json={"nome": "Outro Sem Conta", "email": "Outro.Sem@Constela-Sint.com.br",
                       "criar_acesso": False})
    assert r.status_code == 201, r.text
    assert r.json()["professor"]["email"] == "outro.sem@constela-sint.com.br"
    assert mundo.db.query(Usuario).count() == contas_antes


def test_cadastro_vincula_a_conta_de_professor_da_propria_escola(mundo):
    """Conta de professor criada à mão (sem cadastro na equipe): cadastrar o
    Professor com o e-mail dela é o VÍNCULO legítimo — e a edição seguinte leva
    o login junto."""
    db = mundo.db
    cli = mundo.cli("coord_x")
    d = Usuario(escola_id=mundo.ids["x"], nome="PROF_D_SINT", email="prof.d@constela-sint.com.br",
                senha_hash=hash_senha(SENHA), cargo="professor")
    e = Usuario(escola_id=mundo.ids["x"], nome="PROF_E_SINT", email="prof.e@constela-sint.com.br",
                senha_hash=hash_senha(SENHA), cargo="professor")
    db.add_all([d, e])
    db.commit()
    r = cli.post(_url(mundo, "/professores"),
                 json={"nome": "PROF_D_SINT", "email": "PROF.D@constela-sint.com.br"})
    assert r.status_code == 201, r.text
    assert r.json()["email"].lower() == "prof.d@constela-sint.com.br"
    r2 = cli.post(_url(mundo, "/professores/completo"),
                  json={"nome": "Prof E Sint", "email": "prof.e@constela-sint.com.br",
                        "criar_acesso": False})
    assert r2.status_code == 201, r2.text
    # com criar_acesso=True a conta já existe → 409 (comportamento anterior)
    r3 = cli.post(_url(mundo, "/professores/completo"),
                  json={"nome": "Prof E Sint", "email": "prof.e@constela-sint.com.br",
                        "criar_acesso": True})
    assert r3.status_code == 409, r3.text
    r = cli.patch(_url(mundo, f"/professores/{r.json()['id']}"),
                  json={"email": "prof.d.novo@constela-sint.com.br"})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(Usuario, d.id).email == "prof.d.novo@constela-sint.com.br"


def test_reenviar_o_mesmo_email_nao_e_colisao(mundo):
    cli = mundo.cli("coord_x")
    _email_valido(mundo, "prof_a", "prof.a@constela-sint.com.br")
    pa = mundo.db.query(Professor).filter_by(nome="PROF_A_SINT").one()
    pa.email = "prof.a@constela-sint.com.br"
    mundo.db.commit()
    r = cli.patch(_url(mundo, f"/professores/{pa.id}"),
                  json={"email": "PROF.A@constela-sint.com.br", "nome": "PROF_A_SINT_2"})
    assert r.status_code == 200, r.text
    mundo.db.expire_all()
    assert mundo.db.get(Usuario, mundo.ids["u_prof_a"]).email == "prof.a@constela-sint.com.br"


def test_completo_com_acesso_segue_criando_conta_e_a_edicao_leva_o_login(mundo):
    cli = mundo.cli("coord_x")
    r = cli.post(_url(mundo, "/professores/completo"),
                 json={"nome": "Nova Prof Sint", "email": "nova.prof@constela-sint.com.br",
                       "criar_acesso": True})
    assert r.status_code == 201, r.text
    acesso = r.json()["acesso"]
    assert acesso and acesso["email"] == "nova.prof@constela-sint.com.br"
    pid = r.json()["professor"]["id"]
    r = cli.patch(_url(mundo, f"/professores/{pid}"),
                  json={"email": "nova.prof.2@constela-sint.com.br"})
    assert r.status_code == 200, r.text
    assert _login("nova.prof.2@constela-sint.com.br", acesso["senha"]).status_code == 200


def test_fusao_legitima_segue_funcionando(mundo):
    """Controle positivo da fusão: duplicata real entre contas de PROFESSOR desta
    escola segue fundindo (apaga a duplicada, padroniza a que fica)."""
    db = mundo.db
    adm = mundo.cli("admin_x")
    curta = Usuario(escola_id=mundo.ids["x"], nome="PAULA", email="paula@constela-sint.com.br",
                    senha_hash=hash_senha(SENHA), cargo="professor")
    cheia = Usuario(escola_id=mundo.ids["x"], nome="PAULA SINT NOGUEIRA",
                    email="paula.nogueira@constela-sint.com.br",
                    senha_hash=hash_senha(SENHA), cargo="professor")
    db.add_all([curta, cheia])
    db.commit()
    curta_id = curta.id
    loser = _legado(mundo, "PAULA", "paula@constela-sint.com.br")
    _legado(mundo, "PAULA SINT NOGUEIRA", "paula.nogueira@constela-sint.com.br")
    r = adm.post(_url(mundo, "/professores/duplicados/corrigir"), json={"loser_ids": [loser]})
    assert r.status_code == 200, r.text
    folha = r.json()["folha"]
    assert len(folha) == 1 and folha[0]["senha"], folha
    db.expire_all()
    assert db.get(Usuario, curta_id) is None
    assert _login(folha[0]["usuario"], folha[0]["senha"]).status_code == 200
