"""Promoção a Secretaria (`PUT /redes/{id}/usuarios`) derruba o que foi emitido
para o alcance antigo da conta.

A conta que passa a ter `rede_id` sai do alcance de UMA escola para o da rede
inteira. Sem esta regra, uma sessão aberta antes (ou um link de redefinição
pendente, gerado por quem administrava a escola) seguia valendo com o alcance
novo. A senha NÃO é trocada aqui (decisão do dono).
"""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_senha, hash_token, verificar_senha
from app.main import app
from app.models import Escola, LogAuditoria, Rede, TokenResetSenha, Usuario

API = "/api/v1"


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


def test_promocao_derruba_sessoes_e_links_pendentes(db):
    rede, futura, ja_sec = _cenario(db)
    versao_antes = futura.token_version or 0
    hash_antes = futura.senha_hash
    sessao_antiga = _login("coord@promo.local", "s3nh4-coord")
    assert sessao_antiga.get(f"{API}/auth/me").status_code == 200
    sessao_sec = _login("sec@promo.local", "s3nh4-sec")

    root = _login("root@promo.local", "s3nh4-root")
    r = root.put(f"{API}/redes/{rede.id}/usuarios",
                 json={"usuario_ids": [futura.id, ja_sec.id]})
    assert r.status_code == 200, r.text

    db.expire_all()
    promovida = db.get(Usuario, futura.id)
    assert promovida.rede_id == rede.id
    assert promovida.token_version == versao_antes + 1
    # A senha NÃO é trocada (decisão do dono): a mesma senha entra de novo.
    assert promovida.senha_hash == hash_antes
    assert verificar_senha("s3nh4-coord", promovida.senha_hash)
    # A sessão aberta antes da promoção caiu; um login novo funciona.
    assert sessao_antiga.get(f"{API}/auth/me").status_code == 401
    assert _login("coord@promo.local", "s3nh4-coord").get(f"{API}/auth/me").status_code == 200
    # O link pendente dela foi marcado como usado e não vale mais.
    link = db.execute(select(TokenResetSenha).where(
        TokenResetSenha.usuario_id == futura.id)).scalar_one()
    assert link.usado_em is not None
    r = TestClient(app).post(f"{API}/auth/redefinir-senha",
                             json={"token": "link-pendente-futura",
                                   "nova_senha": "outra-senha-forte-91"})
    assert r.status_code == 400

    # Quem JÁ era desta rede não foi promovido: sessão e link intactos.
    assert sessao_sec.get(f"{API}/auth/me").status_code == 200
    link_sec = db.execute(select(TokenResetSenha).where(
        TokenResetSenha.usuario_id == ja_sec.id)).scalar_one()
    assert link_sec.usado_em is None

    # Auditoria: uma linha por promoção + a lista no registro da rede.
    promocoes = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "usuario.promovido_a_secretaria")).scalars().all()
    assert [p.entidade_id for p in promocoes] == [futura.id]
    assert promocoes[0].detalhes == {"rede_id": rede.id, "rede_anterior": None,
                                     "sessoes_encerradas": True,
                                     "links_pendentes_invalidados": 1}
    definicao = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "rede.usuarios_definidos")).scalar_one()
    assert definicao.detalhes["promovidas"] == [futura.id]


def test_reenviar_a_mesma_lista_nao_derruba_ninguem(db):
    """Idempotente: quem já está na rede não é "promovido" de novo."""
    rede, futura, ja_sec = _cenario(db)
    root = _login("root@promo.local", "s3nh4-root")
    corpo = {"usuario_ids": [futura.id, ja_sec.id]}
    assert root.put(f"{API}/redes/{rede.id}/usuarios", json=corpo).status_code == 200
    sessao = _login("coord@promo.local", "s3nh4-coord")
    db.expire_all()
    versao = db.get(Usuario, futura.id).token_version
    assert root.put(f"{API}/redes/{rede.id}/usuarios", json=corpo).status_code == 200
    db.expire_all()
    assert db.get(Usuario, futura.id).token_version == versao
    assert sessao.get(f"{API}/auth/me").status_code == 200
    promocoes = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "usuario.promovido_a_secretaria")).scalars().all()
    assert len(promocoes) == 1
