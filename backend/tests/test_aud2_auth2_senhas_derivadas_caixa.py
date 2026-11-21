"""``scripts.senhas_derivadas --contagens`` e a trava do login falam a mesma língua
sobre as caixas (G_SCRIPTS-2).

A trava do login (``routers/auth.py::_senha_da_convencao_antiga``) recusa com 403 o
nome/@ + "123" em QUALQUER combinação de maiúsculas e minúsculas: compara o texto
digitado. O script do checklist pré-deploy só consegue conferir com bcrypt 4 caixas
fixas (como está, minúsculas, MAIÚSCULAS e só a primeira maiúscula). Antes, uma conta
GLOBAL com a senha do próprio nome em outra caixa saía como "globais: 0 → segue" e,
depois do deploy, recebia o 403 sem volta garantida.

Decisão: a trava do login fica como está (afrouxá-la para as 4 caixas deixaria entrar
"aNaSilva123" — senha do nome, só com outra caixa). O script passa a dizer o limite e
a mandar confirmar com cada administrador global. A regra que o teste cobra, para toda
caixa: se o login recusa a senha, ou o script a conta ou a saída avisa que aquela
combinação fica de fora.

Conta e senhas fictícias; bcrypt de custo 4 só para o teste andar rápido."""
import sys

import pytest
from fastapi.testclient import TestClient
from passlib.hash import bcrypt as bcrypt_rapido
from sqlalchemy.orm import sessionmaker

from app.core import rate_limit
from app.main import app
from app.models import Usuario

AVISO = ("o login recusa com 403 o nome ou o usuário + 123 em QUALQUER combinação de "
         "maiúsculas e minúsculas")


def _rodar(monkeypatch, capsys, db, *args) -> str:
    import scripts.senhas_derivadas as etapa
    monkeypatch.setattr(etapa, "SessionLocal", sessionmaker(bind=db.get_bind()))
    monkeypatch.setattr(sys, "argv", ["senhas_derivadas", *args])
    assert etapa.main() == 0
    return capsys.readouterr().out


@pytest.mark.parametrize("senha, nas_quatro_caixas", [
    ("AnaFicticia123", True),        # como está (o @ guardado em CamelCase)
    ("anaficticia123", True),        # minúsculas
    ("ANAFICTICIA123", True),        # MAIÚSCULAS
    ("Anaficticia123", True),        # só a primeira maiúscula
    ("anaFicticia123", False),       # outra combinação: o caso da auditoria
    ("aNAFICTICIA123", False),
])
def test_contagens_contam_ou_avisam_toda_senha_que_o_login_recusa(
        db, escola_completa, monkeypatch, capsys, senha, nas_quatro_caixas):
    db.add(Usuario(escola_id=escola_completa["escola"].id, nome="Ana Ficticia",
                   username="AnaFicticia", email="ana.global@teste.local",
                   senha_hash=bcrypt_rapido.using(rounds=4).hash(senha), cargo="admin",
                   is_global=True))
    db.commit()

    r = TestClient(app).post("/api/v1/auth/login",
                             data={"username": "AnaFicticia", "password": senha})
    assert r.status_code == 403, r.text            # a trava recusa em qualquer caixa
    assert r.json()["detail"].startswith("Senha expirada")
    rate_limit.limitador_login._eventos.clear()

    saida = _rodar(monkeypatch, capsys, db, "--contagens")
    linhas = saida.strip().splitlines()
    if nas_quatro_caixas:
        assert "globais: 1" in linhas
        assert any(x.startswith("ATENÇÃO: há conta GLOBAL") for x in linhas)
    else:
        assert "globais: 0" in linhas
        # Fora das 4 caixas: a saída não pode dizer "nenhuma" sem ressalva.
        assert ("nenhuma conta global com senha derivada nas 4 caixas conferidas "
                "(ver o limite abaixo).") in linhas
        assert "nenhuma conta global com senha derivada." not in linhas
    aviso = [x for x in linhas if AVISO in x]
    assert len(aviso) == 1
    assert "confirme com cada administrador global" in aviso[0]
    assert "AnaFicticia" not in saida and "@" not in saida and senha not in saida


def test_diagnostico_tambem_avisa_o_limite_das_caixas(db, escola_completa, monkeypatch,
                                                      capsys):
    saida = _rodar(monkeypatch, capsys, db)
    assert AVISO in saida
