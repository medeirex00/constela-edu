"""CONTESTAÇÃO adversarial do P0 (cópia fora do repo).

Convenção: cada teste PASSA quando o sistema está SEGURO (o ataque falha).
Um teste que FALHA aponta uma brecha (ou, nos marcados "RESSALVA", um defeito
de robustez sem escalada). Mundo sintético de `test_isolamento_escopo`.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from tests._mundo_sintetico import SENHA, mundo  # noqa: F401  (fixture)
from app.core.config import settings
from app.core.database import _promover_admin_global, get_db
from app.core.security import hash_senha
from app.main import app
from app.models import Professor, Turma, Usuario
from app.routers import academico

DOM = "constela-sint.com.br"


def _url(mundo, resto, escola="x"):
    return f"/api/v1/escolas/{mundo.ids[escola]}{resto}"


def _email(mundo, chave, email):
    u = mundo.db.get(Usuario, mundo.ids["u_" + chave])
    u.email = email
    mundo.db.commit()
    return u


def _retrato_id(mundo, uid):
    mundo.db.expire_all()
    u = mundo.db.get(Usuario, uid)
    return None if u is None else (u.email, u.username, u.senha_hash, u.is_global,
                                   u.cargo, u.escola_id, u.rede_id, u.nome)


def _login(ident, senha=SENHA):
    return TestClient(app).post("/api/v1/auth/login",
                                data={"username": ident, "password": senha})


def _globais(mundo):
    mundo.db.expire_all()
    return {u.id for u in mundo.db.query(Usuario).filter(Usuario.is_global.is_(True))}


def _legado(mundo, nome, email, escola="x"):
    p = Professor(escola_id=mundo.ids[escola], nome=nome, email=email)
    mundo.db.add(p)
    mundo.db.commit()
    return p.id


# ---------------------------------------------------------------------------
# 1) CORRIDA: a checagem passa e, antes do commit, outra transação grava o
#    mesmo login. O índice único precisa decidir e a rota devolver 409 (não 500,
#    e nunca dois logins iguais).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("autoflush", [False, True], ids=["producao", "teste"])
def test_01_corrida_patch_vira_409(mundo, monkeypatch, autoflush):
    engine = mundo.db.get_bind()
    Sess = sessionmaker(bind=engine, autoflush=autoflush)

    def _get_db():
        s = Sess()
        try:
            yield s
        finally:
            s.close()

    cli = mundo.cli("coord_x")
    app.dependency_overrides[get_db] = _get_db
    original = academico._exigir_email_de_professor
    alvo = f"corrida@{DOM}"

    def _com_corrida(db, escola_id, email, conta_atual=None):
        original(db, escola_id, email, conta_atual=conta_atual)
        outra = Sess()
        outra.add(Usuario(escola_id=mundo.ids["y"], nome="CORRIDA_SINT", email=email,
                          senha_hash=hash_senha(SENHA), cargo="coordenador"))
        outra.commit()
        outra.close()

    monkeypatch.setattr(academico, "_exigir_email_de_professor", _com_corrida)
    pa = mundo.db.query(Professor).filter_by(nome="PROF_A_SINT").one()
    r = cli.patch(_url(mundo, f"/professores/{pa.id}"), json={"email": alvo})
    print(f"\n[01/{autoflush}] PATCH com corrida ->", r.status_code, r.text[:120])
    assert r.status_code == 409, r.text
    mundo.db.expire_all()
    assert mundo.db.get(Usuario, mundo.ids["u_prof_a"]).email == "prof_a@sint.local"
    assert mundo.db.query(Usuario).filter(Usuario.email == alvo).count() == 1
    assert mundo.db.get(Professor, pa.id).email == "prof_a@sint.local"


# ---------------------------------------------------------------------------
# 2) Conta EXCLUÍDA (lógica) continua reservada; restaurada, segue intacta.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("rota", ["simples", "completo_sem", "completo_com", "patch"])
def test_02_conta_excluida_continua_reservada(mundo, rota):
    cli = mundo.cli("coord_x")
    e = f"coord.y@{DOM}"
    u = _email(mundo, "coord_y", e)
    u.status = "excluido"
    mundo.db.commit()
    antes = _retrato_id(mundo, u.id)
    if rota == "simples":
        r = cli.post(_url(mundo, "/professores"), json={"nome": "ESP_SINT", "email": e})
    elif rota == "patch":
        sem = cli.post(_url(mundo, "/professores"), json={"nome": "SEM_CONTA_SINT"}).json()
        r = cli.patch(_url(mundo, f"/professores/{sem['id']}"), json={"email": e})
    else:
        r = cli.post(_url(mundo, "/professores/completo"),
                     json={"nome": "Esp Sint", "email": e,
                           "criar_acesso": rota == "completo_com"})
    print(f"\n[02/{rota}] e-mail de conta excluída ->", r.status_code)
    assert r.status_code == 409, r.text
    u = mundo.db.get(Usuario, mundo.ids["u_coord_y"])
    u.status = "ativo"
    mundo.db.commit()
    assert _retrato_id(mundo, u.id) == antes
    assert _login(e).status_code == 200


# ---------------------------------------------------------------------------
# 3) Espelho criado com e-mail LIVRE e, depois, a conta "volta" (restauração de
#    backup / recriação / promoção) na escola X com alcance de gestão, rede ou
#    global. TOCTOU: a checagem do cadastro já passou — o recorte por TIPO de
#    conta na edição e na fusão é que tem de segurar.
# ---------------------------------------------------------------------------
TIPOS = {
    "coordenador_x": dict(cargo="coordenador"),
    "admin_x": dict(cargo="admin"),
    "secretaria_cargo_professor": dict(cargo="professor", rede="r1"),
    "global_cargo_professor": dict(cargo="professor", is_global=True),
    "professor_y": dict(cargo="professor", escola="y"),
}


@pytest.mark.parametrize("tipo", list(TIPOS))
def test_03_espelho_antes_da_conta_existir(mundo, tipo):
    coord, adm = mundo.cli("coord_x"), mundo.cli("admin_x")
    e = f"volta.{tipo.replace('_', '')}@{DOM}"
    ids = {}
    for nome in ("Bia", "Bia Sint Souza", "Espelho Tres"):
        r = coord.post(_url(mundo, "/professores/completo"),
                       json={"nome": nome, "email": e, "criar_acesso": False})
        assert r.status_code == 201, r.text
        ids[nome] = r.json()["professor"]["id"]
    spec = TIPOS[tipo]
    u = Usuario(escola_id=mundo.ids[spec.get("escola", "x")], nome="VOLTOU_SINT", email=e,
                senha_hash=hash_senha(SENHA), cargo=spec["cargo"],
                rede_id=mundo.ids[spec["rede"]] if "rede" in spec else None,
                is_global=spec.get("is_global", False))
    mundo.db.add(u)
    mundo.db.commit()
    antes = _retrato_id(mundo, u.id)

    r = coord.patch(_url(mundo, f"/professores/{ids['Espelho Tres']}"),
                    json={"email": f"tres.novo.{tipo.replace('_', '')}@{DOM}"})
    assert r.status_code == 200, r.text
    assert _retrato_id(mundo, u.id) == antes, "PATCH reescreveu a conta que voltou"

    r = adm.post(_url(mundo, "/professores/duplicados/corrigir"),
                 json={"loser_ids": [ids["Bia"]]})
    assert r.status_code == 200, r.text
    folha = r.json()["folha"]
    print(f"\n[03/{tipo}] folha:", [(f['usuario'], bool(f['senha'])) for f in folha])
    assert _retrato_id(mundo, u.id) == antes, "fusão apagou/reescreveu a conta"
    assert not any(f.get("senha") for f in folha)

    r = adm.post(_url(mundo, "/professores/padronizar-usuarios"))
    assert r.status_code == 200, r.text
    assert _retrato_id(mundo, u.id) == antes, "padronização reescreveu a conta"
    assert _login(e).status_code == 200


# ---------------------------------------------------------------------------
# 4) Conta de professor VINCULADA e depois promovida a Secretaria (mantém cargo
#    professor e escola de origem). Edição, fusão, padronização e importação
#    não podem mais alcançá-la.
# ---------------------------------------------------------------------------
def test_04_vinculo_e_depois_promocao_a_secretaria(mundo):
    from app.services import professores as svc
    coord, adm, glob = mundo.cli("coord_x"), mundo.cli("admin_x"), mundo.cli("global")
    pa = mundo.db.query(Professor).filter_by(nome="PROF_A_SINT").one()
    r = glob.put(f"/api/v1/redes/{mundo.ids['r1']}/usuarios",
                 json={"usuario_ids": [mundo.ids["u_sec_r1"], mundo.ids["u_secadm_x"],
                                       mundo.ids["u_prof_a"]]})
    assert r.status_code == 200, r.text
    uid = mundo.ids["u_prof_a"]
    antes = _retrato_id(mundo, uid)
    assert antes[4] == "professor" and antes[5] == mundo.ids["x"] and antes[6] == mundo.ids["r1"]

    assert adm.patch(_url(mundo, f"/professores/{pa.id}"),
                     json={"nome": "Paula Sint Vilela"}).status_code == 200
    loser = _legado(mundo, "Paula", "prof_a@sint.local")
    r = adm.post(_url(mundo, "/professores/duplicados/corrigir"), json={"loser_ids": [loser]})
    assert r.status_code == 200, r.text
    print("\n[04] folha:", [(f['usuario'], bool(f['senha'])) for f in r.json()["folha"]])
    assert not any(f.get("senha") for f in r.json()["folha"])
    assert _retrato_id(mundo, uid)[:7] == antes[:7]

    assert adm.post(_url(mundo, "/professores/padronizar-usuarios")).status_code == 200
    assert _retrato_id(mundo, uid)[:7] == antes[:7]

    # importação: nome curto já cadastrado com o e-mail dela + nome completo novo
    curto = _legado(mundo, "Zuleica", "prof_a@sint.local")
    p, novo = svc.garantir_professor(mundo.db, mundo.ids["x"], "Zuleica Sint Completa")
    mundo.db.commit()
    assert p is not None and p.id == curto and not novo
    assert _retrato_id(mundo, uid)[7] == antes[7], "importação renomeou a Secretaria"

    r = coord.patch(_url(mundo, f"/professores/{pa.id}"), json={"email": f"pa.novo@{DOM}"})
    assert r.status_code == 200, r.text
    assert _retrato_id(mundo, uid)[:7] == antes[:7]
    lr = _login("prof_a@sint.local")
    assert lr.status_code == 200
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {lr.json()['access_token']}"
    assert c.get(f"/api/v1/redes/{mundo.ids['r1']}/dashboard").status_code == 200


# ---------------------------------------------------------------------------
# 5) Coordenador COM rede (= Secretaria) e conta de rede hospedada na escola:
#    nenhuma escrita em /professores nem na fusão.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("ator", ["sec_r1", "secadm_x"])
def test_05_conta_de_rede_nao_escreve(mundo, ator):
    cli = mundo.cli(ator)
    pa = mundo.db.query(Professor).filter_by(nome="PROF_A_SINT").one()
    codigos = [
        cli.post(_url(mundo, "/professores"), json={"nome": "R_SINT", "email": f"r@{DOM}"}).status_code,
        cli.post(_url(mundo, "/professores/completo"),
                 json={"nome": "R Sint", "email": f"r2@{DOM}", "criar_acesso": True}).status_code,
        cli.patch(_url(mundo, f"/professores/{pa.id}"), json={"email": f"r3@{DOM}"}).status_code,
        cli.post(_url(mundo, "/professores/duplicados/corrigir"), json={"loser_ids": []}).status_code,
        cli.post(_url(mundo, "/professores/padronizar-usuarios")).status_code,
        cli.put(_url(mundo, f"/usuarios/{mundo.ids['u_prof_a']}/turmas"),
                json={"turma_ids": []}).status_code,
    ]
    print(f"\n[05/{ator}]", codigos)
    assert all(c == 403 for c in codigos), codigos


# ---------------------------------------------------------------------------
# 6) Normalização: Unicode, caixa, forma "Nome <e-mail>", espaço invisível.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("variante, alvo_email", [
    ("Kelvin.y@" + DOM, "kelvin.y@" + DOM),                 # sinal Kelvin
    ("coord.y@ｃonstela-sint.com.br", "coord.y@" + DOM),     # domínio full-width
    ("Fulano <coord.y@" + DOM + ">", "coord.y@" + DOM),           # nome + endereço
    ("COORD.Y@" + DOM.upper(), "coord.y@" + DOM),
])
@pytest.mark.parametrize("rota", ["simples", "completo_sem", "patch"])
def test_06_variantes_unicode_colidem(mundo, variante, alvo_email, rota):
    cli = mundo.cli("coord_x")
    u = _email(mundo, "coord_y", alvo_email)
    antes = _retrato_id(mundo, u.id)
    if rota == "simples":
        r = cli.post(_url(mundo, "/professores"), json={"nome": "U_SINT", "email": variante})
    elif rota == "completo_sem":
        r = cli.post(_url(mundo, "/professores/completo"),
                     json={"nome": "U Sint", "email": variante, "criar_acesso": False})
    else:
        pa = mundo.db.query(Professor).filter_by(nome="PROF_A_SINT").one()
        r = cli.patch(_url(mundo, f"/professores/{pa.id}"), json={"email": variante})
    print(f"\n[06/{rota}] {ascii(variante)} ->", r.status_code)
    assert r.status_code in (409, 422), r.text
    assert _retrato_id(mundo, u.id) == antes
    mundo.db.expire_all()
    assert mundo.db.get(Usuario, mundo.ids["u_prof_a"]).email == "prof_a@sint.local"


def test_06b_espaco_invisivel_recusado(mundo):
    cli = mundo.cli("coord_x")
    r = cli.post(_url(mundo, "/professores"),
                 json={"nome": "Z_SINT", "email": "coord.y​@" + DOM})
    assert r.status_code == 422, r.text


DONO_K = "kdono@" + DOM


@pytest.mark.parametrize("variante", [
    "Kdono@" + DOM, "KDONO@" + DOM.upper(), "Dono <kdono@" + DOM + ">",
    "kdono@ｃonstela-sint.com.br",
])
@pytest.mark.parametrize("ator", ["coord_x", "admin_x", "global"])
def test_06c_reservado_por_variante_nao_entra(mundo, monkeypatch, variante, ator):
    monkeypatch.setattr(settings, "ADMIN_GLOBAL_EMAIL", DONO_K)
    cli = mundo.cli(ator)
    pa = mundo.db.query(Professor).filter_by(nome="PROF_A_SINT").one()
    codigos = [
        cli.post(_url(mundo, "/professores"), json={"nome": "D_SINT", "email": variante}).status_code,
        cli.post(_url(mundo, "/professores/completo"),
                 json={"nome": "D Sint", "email": variante, "criar_acesso": True}).status_code,
        cli.post(_url(mundo, "/professores/completo"),
                 json={"nome": "D Sint2", "email": variante, "criar_acesso": False}).status_code,
        cli.patch(_url(mundo, f"/professores/{pa.id}"), json={"email": variante}).status_code,
    ]
    print(f"\n[06c/{ator}] {ascii(variante)} ->", codigos)
    assert all(c in (403, 422) for c in codigos), codigos
    antes = _globais(mundo)
    _promover_admin_global(motor=mundo.db.get_bind())
    assert _globais(mundo) == antes


def test_06d_i_turco_nao_vira_reservado(mundo, monkeypatch):
    """'İ' vira 'i̇' (i + ponto combinante) no lower() do Python — o valor
    gravado não é o reservado; o boot (lower() do SQL sobre o gravado) também não."""
    monkeypatch.setattr(settings, "ADMIN_GLOBAL_EMAIL", "dino@" + DOM)
    cli = mundo.cli("coord_x")
    r = cli.post(_url(mundo, "/professores/completo"),
                 json={"nome": "Dino Sint", "email": "dİno@" + DOM, "criar_acesso": True})
    print("\n[06d] ->", r.status_code, ascii(r.json().get("acesso", {}) and r.json()["acesso"]["email"]))
    antes = _globais(mundo)
    _promover_admin_global(motor=mundo.db.get_bind())
    assert _globais(mundo) == antes


# ---------------------------------------------------------------------------
# 7) Username × e-mail: nenhuma rota deixa um login sem "@" (sombra do @ alheio
#    no login, que tenta e-mail antes de username) nem um @ com "@".
# ---------------------------------------------------------------------------
def test_07_username_e_email_nao_se_sombreiam(mundo):
    adm, coord = mundo.cli("admin_x"), mundo.cli("coord_x")
    r = adm.patch(_url(mundo, f"/usuarios/{mundo.ids['u_prof_a']}"),
                  json={"username": f"coord.y@{DOM}"})
    assert r.status_code == 422, r.text
    pa = mundo.db.query(Professor).filter_by(nome="PROF_A_SINT").one()
    assert coord.patch(_url(mundo, f"/professores/{pa.id}"),
                       json={"email": "coordy"}).status_code == 422
    assert coord.post(_url(mundo, "/professores/completo"),
                      json={"nome": "S Sint", "email": "coordy",
                            "criar_acesso": True}).status_code == 422


# ---------------------------------------------------------------------------
# 8) IDOR clássico: professor de outra escola por id.
# ---------------------------------------------------------------------------
def test_08_idor_professor_de_outra_escola(mundo):
    coord = mundo.cli("coord_x")
    pc = mundo.db.query(Professor).filter_by(nome="PROF_C_Y_SINT").one()
    assert coord.patch(_url(mundo, f"/professores/{pc.id}"),
                       json={"email": f"pc@{DOM}"}).status_code == 404
    assert coord.patch(_url(mundo, f"/professores/{pc.id}", escola="y"),
                       json={"email": f"pc@{DOM}"}).status_code == 403
    assert coord.delete(_url(mundo, f"/professores/{pc.id}")).status_code == 404
    assert coord.post(_url(mundo, "/professores", escola="y"),
                      json={"nome": "Y_SINT"}).status_code == 403
    mundo.db.expire_all()
    assert mundo.db.get(Professor, pc.id).email == "prof_c@sint.local"


# ---------------------------------------------------------------------------
# 9) Fusão/padronização: só admin (coordenador recebe 403).
# ---------------------------------------------------------------------------
def test_09_coordenador_nao_roda_fusao(mundo):
    coord = mundo.cli("coord_x")
    assert coord.post(_url(mundo, "/professores/duplicados/corrigir"),
                      json={"loser_ids": []}).status_code == 403
    assert coord.post(_url(mundo, "/professores/padronizar-usuarios")).status_code == 403


# ---------------------------------------------------------------------------
# 10) RESSALVA (robustez, sem escalada): o patch ABENÇOA dois Professores com o
#     e-mail da MESMA conta de professor ("vínculo"). Se esses dois forem par de
#     fusão, a fusão apaga a conta do duplicado — que é a MESMA do que fica.
# ---------------------------------------------------------------------------
def test_10_fusao_com_vinculo_compartilhado_nao_apaga_a_conta_do_que_fica(mundo):
    coord, adm = mundo.cli("coord_x"), mundo.cli("admin_x")
    ea = f"prof.a@{DOM}"
    _email(mundo, "prof_a", ea)
    pa = mundo.db.query(Professor).filter_by(nome="PROF_A_SINT").one()
    pa.email = ea
    mundo.db.commit()
    assert _login(ea).status_code == 200       # conta USADA
    assert adm.patch(_url(mundo, f"/professores/{pa.id}"),
                     json={"nome": "Ana Sint Souza"}).status_code == 200
    r = coord.post(_url(mundo, "/professores"),
                   json={"nome": "Ana", "email": ea})
    print("\n[10] coordenador cria 'Ana' com o e-mail da conta da prof A ->", r.status_code)
    assert r.status_code == 201, r.text            # vínculo permitido pelo patch
    r = adm.post(_url(mundo, "/professores/duplicados/corrigir"),
                 json={"loser_ids": [r.json()["id"]]})
    assert r.status_code == 200, r.text
    print("[10] folha:", r.json()["folha"])
    mundo.db.expire_all()
    assert mundo.db.get(Usuario, mundo.ids["u_prof_a"]) is not None, \
        "a fusão APAGOU a conta (já usada) da professora que FICA"


# ---------------------------------------------------------------------------
# 11) CONDICIONAL: ADMIN_GLOBAL_EMAIL no domínio que a padronização/importação
#     GERA (`@professor.constelaedu.com`) e a conta do dono ainda inexistente
#     (ambiente novo / restauração — o cenário que config.py diz proteger).
# ---------------------------------------------------------------------------
DONO_GERADO = "donosint@professor.constelaedu.com"


def test_11a_padronizacao_nao_gera_o_email_reservado(mundo, monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_GLOBAL_EMAIL", DONO_GERADO)
    adm = mundo.cli("admin_x")
    r = adm.post(_url(mundo, "/professores/completo"),
                 json={"nome": "Dono Sint", "email": f"tmp.dono@{DOM}", "criar_acesso": True})
    assert r.status_code == 201, r.text
    r = adm.post(_url(mundo, "/professores/padronizar-usuarios"))
    assert r.status_code == 200, r.text
    linha = [f for f in r.json()["folha"] if f["nome"] == "Dono Sint"]
    print("\n[11a] folha:", [(f["usuario"], bool(f["senha"])) for f in linha])
    mundo.db.expire_all()
    gravado = mundo.db.query(Usuario).filter(Usuario.email == DONO_GERADO).one_or_none()
    print("[11a] conta com o e-mail reservado:", gravado and (gravado.id, gravado.cargo))
    antes = _globais(mundo)
    _promover_admin_global(motor=mundo.db.get_bind())
    novos = _globais(mundo) - antes
    if novos and linha and linha[0]["senha"]:
        lr = _login(linha[0]["usuario"], linha[0]["senha"])
        print("[11a] login com a folha ->", lr.status_code,
              lr.json().get("usuario", {}).get("is_global"))
    assert not novos, f"admin da escola virou dono do global: {novos}"


def test_11b_importacao_nao_gera_o_email_reservado(mundo, monkeypatch):
    from app.services import professores as svc
    monkeypatch.setattr(settings, "ADMIN_GLOBAL_EMAIL", DONO_GERADO)
    p, novo = svc.garantir_professor(mundo.db, mundo.ids["x"], "Dono Sint")
    mundo.db.commit()
    mundo.db.expire_all()
    gravado = mundo.db.query(Usuario).filter(Usuario.email == DONO_GERADO).one_or_none()
    print("\n[11b] importação criou conta com o reservado:", gravado and gravado.id)
    if gravado is not None:
        # coordenador gera o link de redefinição de uma conta de professor
        coord = mundo.cli("coord_x")
        rr = coord.post(_url(mundo, f"/usuarios/{gravado.id}/redefinir-senha"))
        print("[11b] coordenador gera link de redefinição ->", rr.status_code)
    antes = _globais(mundo)
    _promover_admin_global(motor=mundo.db.get_bind())
    assert _globais(mundo) == antes


# ---------------------------------------------------------------------------
# 12) TEÓRICO: conta do dono ainda NÃO promovida e com cargo professor na
#     escola X (pré-boot). O vínculo por turmas cria o Professor com o e-mail
#     reservado; a edição reescreve o login do dono → a promoção do boot some.
# ---------------------------------------------------------------------------
def test_12_conta_do_dono_pre_boot_nao_e_reescrita(mundo, monkeypatch):
    dono = f"dono.pre@{DOM}"
    monkeypatch.setattr(settings, "ADMIN_GLOBAL_EMAIL", dono)
    coord = mundo.cli("coord_x")
    u = Usuario(escola_id=mundo.ids["x"], nome="DONO_PRE_SINT", email=dono,
                senha_hash=hash_senha(SENHA), cargo="professor")
    mundo.db.add(u)
    mundo.db.commit()
    r = coord.put(_url(mundo, f"/usuarios/{u.id}/turmas"),
                  json={"turma_ids": [mundo.ids["t_a26"]]})
    print("\n[12] coordenador designa turma à conta do dono ->", r.status_code)
    prof = mundo.db.query(Professor).filter(Professor.email == dono).one_or_none()
    if prof is not None:
        r = coord.patch(_url(mundo, f"/professores/{prof.id}"),
                        json={"email": f"dono.desviado@{DOM}"})
        print("[12] PATCH do espelho do dono ->", r.status_code)
    mundo.db.expire_all()
    assert mundo.db.get(Usuario, u.id).email == dono, "login do dono reescrito"


# ---------------------------------------------------------------------------
# 13) Atomicidade: 409 no PATCH não grava o nome; 409 no /completo não mexe
#     na turma.
# ---------------------------------------------------------------------------
def test_13_recusa_nao_grava_parcial(mundo):
    coord = mundo.cli("coord_x")
    _email(mundo, "coord_y", f"coord.y@{DOM}")
    pa = mundo.db.query(Professor).filter_by(nome="PROF_A_SINT").one()
    r = coord.patch(_url(mundo, f"/professores/{pa.id}"),
                    json={"nome": "NOME_NOVO_SINT", "email": f"coord.y@{DOM}"})
    assert r.status_code == 409
    mundo.db.expire_all()
    assert mundo.db.get(Professor, pa.id).nome == "PROF_A_SINT"
    t = mundo.db.get(Turma, mundo.ids["t_a26"])
    dono_turma = t.professor_id
    r = coord.post(_url(mundo, "/professores/completo"),
                   json={"nome": "T Sint", "email": f"coord.y@{DOM}",
                         "turma_id": t.id, "criar_acesso": False})
    assert r.status_code == 409
    mundo.db.expire_all()
    assert mundo.db.get(Turma, t.id).professor_id == dono_turma


# ---------------------------------------------------------------------------
# 12b) TEÓRICO, FORA do P0 (admin.py): a mesma conta do dono pré-boot, por
#      cargo professor/admin na escola, é administrável pelo gestor local
#      (link de redefinição do coordenador; senha pelo admin) → global no boot.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("cargo", ["professor", "admin"])
def test_12b_conta_do_dono_pre_boot_nao_e_administravel_pela_escola(mundo, monkeypatch, cargo):
    dono = f"dono.pre@{DOM}"
    monkeypatch.setattr(settings, "ADMIN_GLOBAL_EMAIL", dono)
    coord, adm = mundo.cli("coord_x"), mundo.cli("admin_x")
    u = Usuario(escola_id=mundo.ids["x"], nome="DONO_PRE_SINT", email=dono,
                senha_hash=hash_senha(SENHA), cargo=cargo)
    mundo.db.add(u)
    mundo.db.commit()
    rc = coord.post(_url(mundo, f"/usuarios/{u.id}/redefinir-senha")).status_code
    ra = adm.post(_url(mundo, f"/usuarios/{u.id}/redefinir-senha")).status_code
    from app.core.security import gerar_senha_legivel
    rs = adm.patch(_url(mundo, f"/usuarios/{u.id}"),
                   json={"senha": gerar_senha_legivel()}).status_code
    print(f"\n[12b/{cargo}] link coord={rc} link admin={ra} senha admin={rs}")
    assert rc == 403 and ra == 403 and rs == 403, (rc, ra, rs)


# ---------------------------------------------------------------------------
# 14) Mass assignment no POST simples: escola_id/id no corpo são ignorados.
# ---------------------------------------------------------------------------
def test_14_mass_assignment_ignorado(mundo):
    coord = mundo.cli("coord_x")
    r = coord.post(_url(mundo, "/professores"),
                   json={"nome": "MA_SINT", "escola_id": mundo.ids["y"], "id": 999999})
    assert r.status_code == 201, r.text
    mundo.db.expire_all()
    p = mundo.db.get(Professor, r.json()["id"])
    assert p.escola_id == mundo.ids["x"] and p.id != 999999
