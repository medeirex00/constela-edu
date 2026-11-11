"""A senha do admin inicial vinda do AMBIENTE (achado G_SCRIPTS-4).

O DEFEITO. ``ADMIN_INITIAL_PASSWORD`` é o caminho "para automatizar" do
``docs/PUBLICAR.md`` — uma execução cuja saída vai para log (CI, pre-deploy, ``docker
logs``). O seed imprimia ``Senha:  <a senha do ambiente>`` no stdout e aceitava a senha
sem a política do sistema (``security.validar_forca_senha``): uma conta de
ADMINISTRAÇÃO GLOBAL nascia com 4 dígitos, e o login dava 200.

A CORREÇÃO, provada aqui: a senha do ambiente passa pela mesma regra de todos os
fluxos de senha (fraca → o seed recusa com código ≠ 0, sem criar escola nem conta e
sem ecoar a senha) e nunca sai na tela; a saída só diz de onde ela veio. A senha
ALEATÓRIA (sem a variável) continua aparecendo uma vez, como antes.
"""
import secrets

import pytest
from sqlalchemy import func, select

from app.core.security import verificar_senha
from app.models import Escola, Usuario
from scripts import seed


def _admin(db) -> Usuario | None:
    return db.execute(select(Usuario).where(Usuario.email == seed.ADMIN_EMAIL)
                      ).scalar_one_or_none()


def test_senha_do_ambiente_nao_aparece_na_saida(db, monkeypatch, capsys):
    senha = "Inventada-" + secrets.token_urlsafe(12)
    monkeypatch.setenv("ADMIN_INITIAL_PASSWORD", senha)

    seed.seed_base(db)

    saida = capsys.readouterr()
    assert senha not in saida.out and senha not in saida.err
    assert "ADMIN_INITIAL_PASSWORD" in saida.out           # diz de onde a senha veio
    assert verificar_senha(senha, _admin(db).senha_hash)   # e ela vale no login


@pytest.mark.parametrize("fraca", [
    "4821",                                                # 4 dígitos: curta demais
    "12345678",                                            # senha comum
    seed.ADMIN_EMAIL,                                      # igual ao e-mail
])
def test_senha_fraca_do_ambiente_e_recusada(db, monkeypatch, capsys, fraca):
    monkeypatch.setenv("ADMIN_INITIAL_PASSWORD", fraca)

    with pytest.raises(SystemExit) as saida:
        seed.seed_base(db)

    assert saida.value.code not in (0, None)
    db.rollback()
    assert db.scalar(select(func.count()).select_from(Escola)) == 0
    assert db.scalar(select(func.count()).select_from(Usuario)) == 0
    texto = capsys.readouterr()
    assert "ADMIN_INITIAL_PASSWORD" in texto.err
    assert f"Senha:  {fraca}" not in texto.out


def test_senha_aleatoria_continua_exibida_uma_vez(db, monkeypatch, capsys):
    monkeypatch.delenv("ADMIN_INITIAL_PASSWORD", raising=False)

    seed.seed_base(db)

    linhas = [linha.strip() for linha in capsys.readouterr().out.splitlines()
              if linha.strip().startswith("Senha:")]
    assert len(linhas) == 1
    senha = linhas[0].removeprefix("Senha:").strip()
    assert verificar_senha(senha, _admin(db).senha_hash)
