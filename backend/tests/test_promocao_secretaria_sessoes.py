"""Promoção a Secretaria (`PUT /redes/{id}/usuarios`) derruba o que foi emitido
para o alcance antigo da conta: sessões, links pendentes e a SENHA.

A conta que passa a ter `rede_id` sai do alcance de UMA escola para o da rede
inteira. Sem esta regra, uma sessão aberta antes (ou um link de redefinição
pendente, gerado por quem administrava a escola) seguia valendo com o alcance
novo — e a senha também: quem a conhecia (a escola, uma folha de credenciais
antiga, a senha derivada do nome) passava a ler o município inteiro.

Decisão 5 do dono: na promoção a senha atual deixa de valer e a conta só volta
a entrar por um link de redefinição gerado DEPOIS pelo admin global. Ficam de
fora a conta global e a do e-mail reservado ao dono (troca manual). Antes desta
decisão a regra era "a senha NÃO é trocada" — por isso o primeiro teste mudou.
"""
import re
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.security import hash_senha, hash_token, verificar_senha
from app.main import app
from app.models import Escola, LogAuditoria, Rede, TokenResetSenha, Usuario

API = "/api/v1"
SENHA_NOVA = "farol-cedro-lua-38"


def _tentar_login(email: str, senha: str):
    return TestClient(app).post(f"{API}/auth/login",
                                data={"username": email, "password": senha})


def _login(email: str, senha: str) -> TestClient:
    c = TestClient(app)
    r = c.post(f"{API}/auth/login", data={"username": email, "password": senha})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _cenario(db):
    rede = Rede(nome="Rede Promocao Sint", status="ativa")
    db.add(rede)
    db.flush()
    esc = Escola(nome="EM Promocao Sint", ano_letivo_ativo=2026, rede_id=rede.id,
                 status="ativa")
    db.add(esc)
    db.flush()
    root = Usuario(escola_id=esc.id, nome="Root Sint", email="root@promo.local",
                   senha_hash=hash_senha("s3nh4-root"), cargo="admin", is_global=True)
    futura = Usuario(escola_id=esc.id, nome="Coord Sint", email="coord@promo.local",
                     senha_hash=hash_senha("s3nh4-coord"), cargo="coordenador")
    ja_sec = Usuario(escola_id=None, nome="Sec Antiga Sint", email="sec@promo.local",
                     senha_hash=hash_senha("s3nh4-sec"), cargo="coordenador",
                     rede_id=rede.id)
    db.add_all([root, futura, ja_sec])
    db.flush()
    agora = datetime.now(timezone.utc)
    for uid, token in ((futura.id, "link-pendente-futura"), (ja_sec.id, "link-pendente-sec")):
        db.add(TokenResetSenha(usuario_id=uid, token_hash=hash_token(token),
                               expira_em=agora + timedelta(hours=1), criado_por=root.id))
    db.commit()
    return rede, futura, ja_sec


def _promocoes(db):
    db.expire_all()
    return db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "usuario.promovido_a_secretaria")
        .order_by(LogAuditoria.id)).scalars().all()


def _link_do_admin_global(root: TestClient, escola_id: int, usuario_id: int) -> str:
    """O caminho de volta da conta promovida COM escola: o admin global gera o
    link na tela de Usuários da escola de origem (a mesma rota da escola)."""
    r = root.post(f"{API}/escolas/{escola_id}/usuarios/{usuario_id}/redefinir-senha")
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _redefinir(token: str, senha: str = SENHA_NOVA):
    return TestClient(app).post(f"{API}/auth/redefinir-senha",
                                json={"token": token, "nova_senha": senha})


def test_promocao_derruba_sessoes_links_pendentes_e_a_senha(db):
    rede, futura, ja_sec = _cenario(db)
    versao_antes = futura.token_version or 0
    hash_antes = futura.senha_hash
    hash_sec_antes = ja_sec.senha_hash
    sessao_antiga = _login("coord@promo.local", "s3nh4-coord")
    assert sessao_antiga.get(f"{API}/auth/me").status_code == 200
    sessao_sec = _login("sec@promo.local", "s3nh4-sec")

    root = _login("root@promo.local", "s3nh4-root")
    r = root.put(f"{API}/redes/{rede.id}/usuarios",
                 json={"usuario_ids": [futura.id, ja_sec.id]})
    assert r.status_code == 200, r.text
    # Campo aditivo: QUAIS contas precisam do link — só a promovida agora.
    assert r.json()["usuario_ids"] == sorted([futura.id, ja_sec.id])
    assert r.json()["exigem_redefinicao"] == [
        {"id": futura.id, "nome": "Coord Sint", "email": "coord@promo.local",
         "escola_id": futura.escola_id}]

    db.expire_all()
    promovida = db.get(Usuario, futura.id)
    assert promovida.rede_id == rede.id
    assert promovida.token_version == versao_antes + 1
    # A senha do alcance antigo deixou de valer (Decisão 5): o hash é outro e
    # a senha antiga não entra mais — nem num login novo.
    assert promovida.senha_hash != hash_antes
    assert not verificar_senha("s3nh4-coord", promovida.senha_hash)
    assert _tentar_login("coord@promo.local", "s3nh4-coord").status_code == 401
    # A sessão aberta antes da promoção caiu.
    assert sessao_antiga.get(f"{API}/auth/me").status_code == 401
    # O link pendente dela foi marcado como usado e não vale mais.
    link = db.execute(select(TokenResetSenha).where(
        TokenResetSenha.usuario_id == futura.id)).scalar_one()
    assert link.usado_em is not None
    assert _redefinir("link-pendente-futura", "outra-senha-forte-91").status_code == 400

    # Quem JÁ era desta rede não foi promovido: senha, sessão e link intactos.
    assert db.get(Usuario, ja_sec.id).senha_hash == hash_sec_antes
    assert sessao_sec.get(f"{API}/auth/me").status_code == 200
    link_sec = db.execute(select(TokenResetSenha).where(
        TokenResetSenha.usuario_id == ja_sec.id)).scalar_one()
    assert link_sec.usado_em is None

    # Auditoria: uma linha por promoção + a lista no registro da rede.
    promocoes = _promocoes(db)
    assert [p.entidade_id for p in promocoes] == [futura.id]
    assert promocoes[0].detalhes == {"rede_id": rede.id, "rede_anterior": None,
                                     "sessoes_encerradas": True,
                                     "links_pendentes_invalidados": 1,
                                     "senha_invalidada": True}
    # Nenhuma senha nem hash vai para a auditoria.
    assert "s3nh4" not in str(promocoes[0].detalhes)
    assert promovida.senha_hash not in str(promocoes[0].detalhes)
    definicao = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "rede.usuarios_definidos")).scalar_one()
    assert definicao.detalhes["promovidas"] == [futura.id]
    assert definicao.detalhes["senhas_invalidadas"] == [futura.id]


def test_link_novo_gerado_depois_da_promocao_devolve_o_acesso(db):
    """O único caminho de volta: o admin global gera um link DEPOIS da
    promoção; a pessoa escolhe a senha e entra já com o alcance da rede."""
    rede, futura, ja_sec = _cenario(db)
    root = _login("root@promo.local", "s3nh4-root")
    assert root.put(f"{API}/redes/{rede.id}/usuarios",
                    json={"usuario_ids": [futura.id, ja_sec.id]}).status_code == 200
    assert _tentar_login("coord@promo.local", "s3nh4-coord").status_code == 401

    token = _link_do_admin_global(root, futura.escola_id, futura.id)
    assert TestClient(app).get(
        f"{API}/auth/redefinir-senha/{token}").json()["valido"] is True
    assert _redefinir(token).status_code == 200

    secretaria = _login("coord@promo.local", SENHA_NOVA)
    eu = secretaria.get(f"{API}/auth/me")
    assert eu.status_code == 200 and eu.json()["rede_id"] == rede.id
    assert secretaria.get(f"{API}/redes/{rede.id}/dashboard").status_code == 200
    # A senha anterior à promoção continua morta.
    assert _tentar_login("coord@promo.local", "s3nh4-coord").status_code == 401


def test_conta_sem_escola_promovida_volta_pelo_script_do_operador(db, monkeypatch, capsys):
    """Conta SEM escola não aparece em tela de Usuários nenhuma: o caminho de
    volta é `scripts/link_redefinicao.py`, com o admin global como autor."""
    import scripts.link_redefinicao as ferramenta

    rede, futura, ja_sec = _cenario(db)
    outra = Rede(nome="Outra Rede Sint", status="ativa")
    sem_escola = Usuario(escola_id=None, nome="Lia Sint", email="lia@promo.local",
                         senha_hash=hash_senha("s3nh4-lia"), cargo="coordenador")
    db.add_all([outra, sem_escola])
    db.commit()
    root_id = db.execute(select(Usuario.id).where(
        Usuario.email == "root@promo.local")).scalar_one()

    root = _login("root@promo.local", "s3nh4-root")
    r = root.put(f"{API}/redes/{outra.id}/usuarios", json={"usuario_ids": [sem_escola.id]})
    assert r.status_code == 200, r.text
    assert r.json()["exigem_redefinicao"] == [
        {"id": sem_escola.id, "nome": "Lia Sint", "email": "lia@promo.local",
         "escola_id": None}]
    assert _tentar_login("lia@promo.local", "s3nh4-lia").status_code == 401

    monkeypatch.setattr(ferramenta, "SessionLocal", sessionmaker(bind=db.get_bind()))
    assert ferramenta.main(["--usuario-id", str(sem_escola.id), "--por", str(root_id),
                            "--confirmar"]) == 0
    links = re.findall(r"\S+/redefinir-senha\?token=(\S+)", capsys.readouterr().out)
    assert len(links) == 1
    assert _redefinir(links[0]).status_code == 200
    assert _login("lia@promo.local", SENHA_NOVA).get(
        f"{API}/redes/{outra.id}/dashboard").status_code == 200


def test_conta_global_na_lista_nao_perde_a_senha(db):
    """A conta global nunca tem a senha invalidada: a troca dela é manual, e
    invalidá-la trancaria a administração da plataforma."""
    rede, futura, ja_sec = _cenario(db)
    root_u = db.execute(select(Usuario).where(
        Usuario.email == "root@promo.local")).scalar_one()
    hash_root = root_u.senha_hash
    root = _login("root@promo.local", "s3nh4-root")
    r = root.put(f"{API}/redes/{rede.id}/usuarios",
                 json={"usuario_ids": [root_u.id, futura.id]})
    assert r.status_code == 200, r.text
    assert [c["id"] for c in r.json()["exigem_redefinicao"]] == [futura.id]

    db.expire_all()
    assert db.get(Usuario, root_u.id).senha_hash == hash_root
    assert _tentar_login("root@promo.local", "s3nh4-root").status_code == 200
    detalhes = {p.entidade_id: p.detalhes for p in _promocoes(db)}
    assert detalhes[root_u.id]["senha_invalidada"] is False
    assert detalhes[root_u.id]["senha_mantida_por"] == "conta_global"
    assert detalhes[futura.id]["senha_invalidada"] is True


def test_email_reservado_ao_dono_nao_perde_a_senha(db, monkeypatch):
    """A conta com o e-mail de ADMIN_GLOBAL_EMAIL (ainda não promovida a global
    pelo boot) também fica de fora: a troca dela é manual, não por link."""
    rede, futura, ja_sec = _cenario(db)
    monkeypatch.setattr(settings, "ADMIN_GLOBAL_EMAIL", "coord@promo.local")
    hash_antes = futura.senha_hash
    root = _login("root@promo.local", "s3nh4-root")
    r = root.put(f"{API}/redes/{rede.id}/usuarios", json={"usuario_ids": [futura.id]})
    assert r.status_code == 200, r.text
    assert r.json()["exigem_redefinicao"] == []

    db.expire_all()
    assert db.get(Usuario, futura.id).senha_hash == hash_antes
    (promocao,) = _promocoes(db)
    assert promocao.detalhes["senha_invalidada"] is False
    assert promocao.detalhes["senha_mantida_por"] == "email_reservado_ao_dono"


def test_reenviar_a_mesma_lista_nao_derruba_ninguem(db):
    """Idempotente: quem já está na rede não é "promovido" de novo — nem perde
    a senha que escolheu pelo link depois da promoção."""
    rede, futura, ja_sec = _cenario(db)
    root = _login("root@promo.local", "s3nh4-root")
    corpo = {"usuario_ids": [futura.id, ja_sec.id]}
    assert root.put(f"{API}/redes/{rede.id}/usuarios", json=corpo).status_code == 200
    assert _redefinir(_link_do_admin_global(root, futura.escola_id, futura.id)
                      ).status_code == 200
    sessao = _login("coord@promo.local", SENHA_NOVA)
    db.expire_all()
    versao = db.get(Usuario, futura.id).token_version
    hash_escolhido = db.get(Usuario, futura.id).senha_hash

    r = root.put(f"{API}/redes/{rede.id}/usuarios", json=corpo)
    assert r.status_code == 200
    assert r.json()["exigem_redefinicao"] == []
    db.expire_all()
    assert db.get(Usuario, futura.id).token_version == versao
    assert db.get(Usuario, futura.id).senha_hash == hash_escolhido
    assert sessao.get(f"{API}/auth/me").status_code == 200
    assert _tentar_login("coord@promo.local", SENHA_NOVA).status_code == 200
    assert len(_promocoes(db)) == 1
