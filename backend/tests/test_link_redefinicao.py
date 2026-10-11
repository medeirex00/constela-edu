"""`scripts/link_redefinicao.py`: o admin global gera o link de redefinição de
UMA conta não global — inclusive a conta SEM escola, que não tem rota.

Roda contra o banco em memória da suíte (a mesma sessão que a API dos testes
usa), para conferir o link de ponta a ponta: o consumo em
``POST /auth/redefinir-senha`` aceita o autor global (``_criador_ainda_pode``).
"""
import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.core.security import hash_senha, hash_token
from app.main import app
from app.models import LogAuditoria, Rede, TokenResetSenha, Usuario

SENHA_NOVA = "farol-cedro-lua-38"


@pytest.fixture()
def contas(db, escola_completa):
    rede = Rede(nome="REDE_LINK_SINT")
    db.add(rede)
    db.flush()
    globa = Usuario(escola_id=None, nome="Global Sint", email="global.sint@teste.local",
                    senha_hash=hash_senha("s3nh4-global"), cargo="admin", is_global=True)
    globa_inativa = Usuario(escola_id=None, nome="Global Inativa", email="gi.sint@teste.local",
                            senha_hash=hash_senha("s3nh4-global"), cargo="admin",
                            is_global=True, status="inativo")
    # Secretaria SEM escola: nenhuma tela de escola gera o link dela
    sem_escola = Usuario(escola_id=None, nome="Rosa Sint", email="rosa.sint@teste.local",
                         username="RosaSint", senha_hash=hash_senha("rosasint123"),
                         cargo="coordenador", rede_id=rede.id)
    professor = Usuario(escola_id=escola_completa["escola"].id, nome="Paula Sint",
                        email="paula.sint@teste.local", senha_hash=hash_senha("x" * 12),
                        cargo="professor")
    excluido = Usuario(escola_id=escola_completa["escola"].id, nome="Hugo Sint",
                       email="hugo.sint@teste.local", senha_hash=hash_senha("x" * 12),
                       cargo="professor", status="excluido")
    dono = Usuario(escola_id=escola_completa["escola"].id, nome="Dono Sint",
                   email="dono.sint@teste.local", senha_hash=hash_senha("x" * 12),
                   cargo="admin")
    db.add_all([globa, globa_inativa, sem_escola, professor, excluido, dono])
    db.commit()
    return {"global": globa, "global_inativa": globa_inativa, "sem_escola": sem_escola,
            "professor": professor, "excluido": excluido, "dono": dono,
            "admin_escola": escola_completa["admin"]}


def _rodar(db, monkeypatch, capsys, *args):
    import scripts.link_redefinicao as ferramenta
    monkeypatch.setattr(ferramenta, "SessionLocal", sessionmaker(bind=db.get_bind()))
    codigo = ferramenta.main([str(a) for a in args])
    saida = capsys.readouterr()
    return codigo, saida.out, saida.err


def _tokens(db, usuario_id):
    db.expire_all()
    return db.execute(select(TokenResetSenha).where(
        TokenResetSenha.usuario_id == usuario_id)).scalars().all()


def _pedidos(db, usuario_id):
    db.expire_all()
    return db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "usuario.reset_solicitado",
        LogAuditoria.entidade_id == usuario_id)).scalars().all()


def test_sem_confirmar_so_mostra_e_nao_grava(db, contas, monkeypatch, capsys):
    alvo = contas["sem_escola"]
    codigo, saida, _ = _rodar(db, monkeypatch, capsys, "--usuario-id", alvo.id,
                              "--por", contas["global"].id)
    assert codigo == 0
    assert "prévia — nada foi gravado" in saida
    assert "redefinir-senha?token=" not in saida
    assert _tokens(db, alvo.id) == [] and _pedidos(db, alvo.id) == []


def test_gera_o_link_da_conta_sem_escola_e_ele_funciona(db, contas, monkeypatch, capsys):
    alvo, autor = contas["sem_escola"], contas["global"]
    # um link antigo ainda pendente: deixa de valer
    antigo = TokenResetSenha(usuario_id=alvo.id, token_hash=hash_token("antigo-token-sint"),
                             expira_em=datetime.now(timezone.utc) + timedelta(hours=1),
                             criado_por=autor.id)
    db.add(antigo)
    db.commit()

    codigo, saida, _ = _rodar(db, monkeypatch, capsys, "--usuario-id", alvo.id,
                              "--por", autor.id, "--confirmar")
    assert codigo == 0
    links = re.findall(r"\S+/redefinir-senha\?token=(\S+)", saida)
    assert len(links) == 1                         # o link sai UMA vez
    token = links[0]
    assert saida.count(token) == 1

    registros = _tokens(db, alvo.id)
    assert len(registros) == 2
    novo = next(r for r in registros if r.token_hash == hash_token(token))
    assert novo.criado_por == autor.id and novo.usado_em is None
    assert next(r for r in registros if r.id == antigo.id).usado_em is not None

    pedidos = _pedidos(db, alvo.id)
    assert len(pedidos) == 1
    assert pedidos[0].usuario_id == autor.id
    assert pedidos[0].detalhes == {"email": alvo.email, "origem": "scripts/link_redefinicao"}
    assert token not in str(pedidos[0].detalhes)   # o token nunca vai para o log

    # De ponta a ponta: o consumo aceita o autor global e a senha passa a valer.
    cliente = TestClient(app)
    assert cliente.get(f"/api/v1/auth/redefinir-senha/{token}").json()["valido"] is True
    r = cliente.post("/api/v1/auth/redefinir-senha",
                     json={"token": token, "nova_senha": SENHA_NOVA})
    assert r.status_code == 200, r.text
    r = cliente.post("/api/v1/auth/login",
                     data={"username": alvo.email, "password": SENHA_NOVA})
    assert r.status_code == 200, r.text
    # e o link antigo morreu
    r = cliente.post("/api/v1/auth/redefinir-senha",
                     json={"token": "antigo-token-sint", "nova_senha": "outra-senha-91x"})
    assert r.status_code == 400


def test_gera_link_de_conta_com_escola(db, contas, monkeypatch, capsys):
    alvo = contas["professor"]
    codigo, saida, _ = _rodar(db, monkeypatch, capsys, "--usuario-id", alvo.id,
                              "--por", contas["global"].id, "--confirmar")
    assert codigo == 0 and "redefinir-senha?token=" in saida
    assert _pedidos(db, alvo.id)[0].escola_id == alvo.escola_id


@pytest.mark.parametrize("alvo_chave, autor_chave, trecho", [
    ("sem_escola", "admin_escola", "administração GLOBAL"),   # autor não global
    ("sem_escola", "global_inativa", "não está ativa"),
    ("global_inativa", "global", "administração global"),     # alvo global
    ("excluido", "global", "conta excluída"),
])
def test_recusa_sem_gravar(db, contas, monkeypatch, capsys, alvo_chave, autor_chave, trecho):
    alvo = contas[alvo_chave]
    codigo, saida, erro = _rodar(db, monkeypatch, capsys, "--usuario-id", alvo.id,
                                 "--por", contas[autor_chave].id, "--confirmar")
    assert codigo == 2
    assert trecho in erro and "Nada foi gravado" in erro
    assert "token=" not in saida
    assert _tokens(db, alvo.id) == [] and _pedidos(db, alvo.id) == []


def test_recusa_o_email_reservado_ao_dono(db, contas, monkeypatch, capsys):
    from app.core.config import settings
    monkeypatch.setattr(settings, "ADMIN_GLOBAL_EMAIL", contas["dono"].email)
    alvo = contas["dono"]
    codigo, _, erro = _rodar(db, monkeypatch, capsys, "--usuario-id", alvo.id,
                             "--por", contas["global"].id, "--confirmar")
    assert codigo == 2 and "reservado ao dono" in erro
    assert _tokens(db, alvo.id) == []


def test_recusa_conta_inexistente(db, contas, monkeypatch, capsys):
    codigo, _, erro = _rodar(db, monkeypatch, capsys, "--usuario-id", 999999,
                             "--por", contas["global"].id, "--confirmar")
    assert codigo == 2 and "não existe" in erro
    codigo, _, erro = _rodar(db, monkeypatch, capsys, "--usuario-id",
                             contas["professor"].id, "--por", 999999, "--confirmar")
    assert codigo == 2 and "não existe" in erro


@pytest.mark.parametrize("args", [[], ["--usuario-id", "1"], ["--por", "1"]])
def test_argparse_exige_alvo_e_autor(args, monkeypatch):
    import scripts.link_redefinicao as ferramenta

    def sem_banco():
        raise AssertionError("não deveria abrir o banco")

    monkeypatch.setattr(ferramenta, "SessionLocal", sem_banco)
    with pytest.raises(SystemExit) as saida:
        ferramenta.main(args)
    assert saida.value.code == 2
