"""Links de redefinição que uma conta GEROU morrem quando ela perde o poder de gerá-los.

Achado da revisão de integração do e97 (auth-escopo, prova 2/4): a revogação do
f3f1abf (``admin._revogar_acessos``) só alcançava os links em que a conta era o ALVO.
Os links que ela tinha gerado para OUTRAS contas (``criado_por``) ficavam só
SUSPENSOS enquanto ela estava inativa, excluída, com outro cargo ou na Secretaria
(``auth._criador_ainda_pode``) e voltavam a valer na reativação, na restauração ou
quando o cargo era devolvido, dentro da validade de 60 min. Cenário: a sessão da
coordenadora C é usada para gerar o link da professora P; o admin desativa C (o link
"morre" na tela) e a reativa depois de conversar com ela: o MESMO link definia a senha
de P. Trocar a senha de C também não o derrubava.

Os primeiros testes são as provas com o resultado invertido. Os controles garantem que
o link de quem não mudou continua valendo. Dados 100% fictícios; sem rede.
"""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_senha, hash_token
from app.main import app
from app.models import LogAuditoria, Rede, TokenResetSenha, Usuario
from app.routers.admin import _invalidar_links_emitidos

API = "/api/v1"
FORTE = "Gira-sol Ficticio 2026!"
SENHA_C = "Senha-Coord-Ficticia-9"
SENHA_P = "Senha-Prof-Ficticia-9"


def _login(email, senha):
    return TestClient(app).post(f"{API}/auth/login", data={"username": email, "password": senha})


def _contas(db, escola_completa):
    eid = escola_completa["escola"].id
    coord = Usuario(escola_id=eid, nome="Coordenadora Ficticia", email="coord@teste.local",
                    senha_hash=hash_senha(SENHA_C), cargo="coordenador")
    prof = Usuario(escola_id=eid, nome="Professora Ficticia", email="prof@teste.local",
                   senha_hash=hash_senha(SENHA_P), cargo="professor")
    db.add_all([coord, prof])
    db.commit()
    return eid, coord.id, prof.id


def _link_de_p_gerado_por_c(eid, prof_id):
    r = _login("coord@teste.local", SENHA_C)
    assert r.status_code == 200, r.text
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    r = c.post(f"{API}/escolas/{eid}/usuarios/{prof_id}/redefinir-senha")
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _valido(token):
    return TestClient(app).get(f"{API}/auth/redefinir-senha/{token}").json()["valido"]


def _consumir(token):
    return TestClient(app).post(f"{API}/auth/redefinir-senha",
                                json={"token": token, "nova_senha": FORTE})


def _link_morto_e_senha_de_p_intacta(db, prof_id, token):
    db.expire_all()
    reg = db.execute(select(TokenResetSenha).where(
        TokenResetSenha.usuario_id == prof_id)).scalar_one()
    assert reg.usado_em is not None                 # invalidado de vez, não só suspenso
    assert _valido(token) is False
    assert _consumir(token).status_code == 400
    assert _login("prof@teste.local", FORTE).status_code == 401
    assert _login("prof@teste.local", SENHA_P).status_code == 200


def _auditoria(db, acao, entidade_id):
    return db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == acao, LogAuditoria.entidade_id == entidade_id)
    ).scalars().one().detalhes


# --- Provas invertidas ----------------------------------------------------------------

def test_desativar_a_coordenadora_mata_o_link_que_ela_gerou_e_reativar_nao_o_devolve(
        db, escola_completa, cliente):
    eid, coord_id, prof_id = _contas(db, escola_completa)
    token = _link_de_p_gerado_por_c(eid, prof_id)
    assert _valido(token) is True

    r = cliente.patch(f"{API}/escolas/{eid}/usuarios/{coord_id}", json={"status": "inativo"})
    assert r.status_code == 200, r.text
    detalhes = _auditoria(db, "usuario.desativado", coord_id)
    assert detalhes["links_emitidos_invalidados"] == 1
    assert detalhes["links_pendentes_invalidados"] == 0      # nenhum link PARA ela
    assert _valido(token) is False

    r = cliente.patch(f"{API}/escolas/{eid}/usuarios/{coord_id}", json={"status": "ativo"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ativo"
    _link_morto_e_senha_de_p_intacta(db, prof_id, token)
    # A reativação também passa pela invalidação (pega link de antes desta correção).
    assert _auditoria(db, "usuario.reativado", coord_id)["links_emitidos_invalidados"] == 0


def test_excluir_e_restaurar_a_coordenadora_nao_ressuscita_o_link(db, escola_completa, cliente):
    eid, coord_id, prof_id = _contas(db, escola_completa)
    token = _link_de_p_gerado_por_c(eid, prof_id)
    r = cliente.delete(f"{API}/escolas/{eid}/usuarios/{coord_id}")
    assert r.status_code == 200, r.text
    detalhes = _auditoria(db, "usuario.excluido", coord_id)
    assert detalhes["links_emitidos_invalidados"] == 1
    assert detalhes["sessoes_encerradas"] is True
    r = cliente.patch(f"{API}/escolas/{eid}/usuarios/{coord_id}", json={"status": "ativo"})
    assert r.status_code == 200, r.text
    _link_morto_e_senha_de_p_intacta(db, prof_id, token)


def test_trocar_a_senha_da_coordenadora_mata_o_link_que_ela_gerou(db, escola_completa, cliente):
    eid, coord_id, prof_id = _contas(db, escola_completa)
    token = _link_de_p_gerado_por_c(eid, prof_id)
    r = cliente.patch(f"{API}/escolas/{eid}/usuarios/{coord_id}",
                      json={"senha": "Outra-Senha-Ficticia-7"})
    assert r.status_code == 200, r.text
    assert _auditoria(db, "usuario.senha_redefinida", coord_id)[
        "links_emitidos_invalidados"] == 1
    _link_morto_e_senha_de_p_intacta(db, prof_id, token)


def test_rebaixar_e_promover_de_volta_nao_ressuscita_o_link(db, escola_completa, cliente):
    eid, coord_id, prof_id = _contas(db, escola_completa)
    token = _link_de_p_gerado_por_c(eid, prof_id)
    r = cliente.patch(f"{API}/escolas/{eid}/usuarios/{coord_id}", json={"cargo": "professor"})
    assert r.status_code == 200, r.text
    assert _valido(token) is False
    r = cliente.patch(f"{API}/escolas/{eid}/usuarios/{coord_id}", json={"cargo": "coordenador"})
    assert r.status_code == 200, r.text
    _link_morto_e_senha_de_p_intacta(db, prof_id, token)
    contagens = [log.detalhes.get("links_emitidos_invalidados") for log in db.execute(
        select(LogAuditoria).where(LogAuditoria.acao == "usuario.permissoes_alteradas",
                                   LogAuditoria.entidade_id == coord_id)
        .order_by(LogAuditoria.id)).scalars()]
    assert contagens == [1, 0]


def test_promover_a_secretaria_e_tirar_da_rede_nao_ressuscita_o_link(
        db, escola_completa, cliente_global):
    eid, coord_id, prof_id = _contas(db, escola_completa)
    rede = Rede(nome="Rede Ficticia Links", status="ativa")
    db.add(rede)
    db.flush()
    escola_completa["escola"].rede_id = rede.id
    db.commit()
    token = _link_de_p_gerado_por_c(eid, prof_id)

    r = cliente_global.put(f"{API}/redes/{rede.id}/usuarios", json={"usuario_ids": [coord_id]})
    assert r.status_code == 200, r.text
    detalhes = _auditoria(db, "usuario.promovido_a_secretaria", coord_id)
    assert detalhes["links_emitidos_invalidados"] == 1
    assert detalhes["links_pendentes_invalidados"] == 0
    assert _valido(token) is False

    # Sai da rede (volta a ser só coordenadora da escola): o link segue morto.
    r = cliente_global.put(f"{API}/redes/{rede.id}/usuarios", json={"usuario_ids": []})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(Usuario, coord_id).rede_id is None
    _link_morto_e_senha_de_p_intacta(db, prof_id, token)


# --- Controles: quem não mudou não perde nada ---------------------------------------

def test_link_do_admin_ativo_sem_mudanca_continua_valendo(db, escola_completa, cliente):
    eid, coord_id, prof_id = _contas(db, escola_completa)
    token = cliente.post(f"{API}/escolas/{eid}/usuarios/{prof_id}/redefinir-senha"
                         ).json()["token"]
    # Mexer em OUTRA conta (desativar e reativar a coordenadora) não toca o link do admin.
    base = f"{API}/escolas/{eid}/usuarios/{coord_id}"
    assert cliente.patch(base, json={"status": "inativo"}).status_code == 200
    assert cliente.patch(base, json={"status": "ativo"}).status_code == 200
    assert _valido(token) is True
    assert _consumir(token).status_code == 200
    assert _login("prof@teste.local", FORTE).status_code == 200


def test_editar_a_coordenadora_sem_mudar_cargo_situacao_nem_senha_mantem_o_link(
        db, escola_completa, cliente):
    """Renomear, mandar o MESMO cargo ou a MESMA situação não é perda de poder."""
    eid, coord_id, prof_id = _contas(db, escola_completa)
    token = _link_de_p_gerado_por_c(eid, prof_id)
    base = f"{API}/escolas/{eid}/usuarios/{coord_id}"
    assert cliente.patch(base, json={"nome": "Coordenadora Renomeada"}).status_code == 200
    assert cliente.patch(base, json={"cargo": "coordenador"}).status_code == 200
    assert cliente.patch(base, json={"status": "ativo"}).status_code == 200
    assert _valido(token) is True
    assert _consumir(token).status_code == 200


def test_invalidar_links_emitidos_so_alcanca_os_pendentes_que_a_conta_gerou_para_outros(
        db, escola_completa):
    eid, coord_id, prof_id = _contas(db, escola_completa)
    admin_id = escola_completa["admin"].id
    agora = datetime.now(timezone.utc)
    expira = agora + timedelta(hours=1)
    usado = agora - timedelta(minutes=5)
    linhas = {
        "para_p_por_c": TokenResetSenha(usuario_id=prof_id, criado_por=coord_id,
                                        token_hash=hash_token("t-para-p-por-c"),
                                        expira_em=expira),
        "para_si": TokenResetSenha(usuario_id=coord_id, criado_por=coord_id,
                                   token_hash=hash_token("t-para-si"), expira_em=expira),
        "ja_usado": TokenResetSenha(usuario_id=prof_id, criado_por=coord_id,
                                    token_hash=hash_token("t-ja-usado"), expira_em=expira,
                                    usado_em=usado),
        "de_outro_autor": TokenResetSenha(usuario_id=prof_id, criado_por=admin_id,
                                          token_hash=hash_token("t-outro-autor"),
                                          expira_em=expira),
    }
    db.add_all(linhas.values())
    db.commit()

    assert _invalidar_links_emitidos(db, coord_id, agora) == 1
    db.commit()
    db.expire_all()
    assert linhas["para_p_por_c"].usado_em is not None
    assert linhas["para_si"].usado_em is None            # é de _invalidar_links_pendentes
    assert linhas["de_outro_autor"].usado_em is None
    assert linhas["ja_usado"].usado_em.replace(tzinfo=None) == usado.replace(tzinfo=None)
