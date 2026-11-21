"""O seed da instalação (``scripts/seed.py``) só semeia banco NOVO (achado G_SCRIPTS-3).

O DEFEITO. O ``main()`` do seed não conferia nem o ENV nem o conteúdo do banco. A única
guarda de "já semeado" procurava a escola de demonstração pelo nome ou a conta
``admin@constela.local``. Num banco com escolas e dono de verdade, sem essa conta, o
seed criava uma escola fictícia e uma 2ª conta de ADMINISTRAÇÃO GLOBAL; com ``--demo``,
ainda 15 crianças inventadas com notas. Saía com código 0, sem aviso, mesmo com
``ENV=producao``.

A CORREÇÃO, provada aqui:

* antes de migrar ou gravar qualquer coisa, o seed recusa (código ≠ 0) o banco que já
  tem escola que não é a dele ou conta de administração global que não é a inicial; a
  flag ``--forcar`` existe para o caso consciente;
* ``--demo`` (crianças inventadas) só roda com ENV de desenvolvimento, com ou sem
  ``--forcar``;
* o fluxo documentado continua: banco novo, inclusive com ``ENV=producao`` (passo 5 do
  ``docs/PUBLICAR.md``, ``docker compose exec backend python scripts/seed.py``), e
  rodar o seed de novo no banco que ele mesmo semeou (idempotente).

O ``main()`` roda contra um SQLite em memória posto no lugar do banco do app; as
migrações do Alembic viram o ``create_all`` (``test_alembic`` garante o mesmo schema).
Tudo inventado: escolas, contas e e-mails.
"""
import sys

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.database import Base
from app.models import Aluno, Escola, Usuario
from scripts import seed

ESCOLA_ALHEIA = "Escola Inventada Aurora Boreal"
DONO_ALHEIO = "dono@exemplo.invalid"


@pytest.fixture()
def banco(monkeypatch):
    """O banco do app trocado por um SQLite em memória (sem tabelas: banco novo)."""
    motor = create_engine("sqlite://", connect_args={"check_same_thread": False},
                          poolclass=StaticPool)
    Sessao = sessionmaker(bind=motor, autoflush=False)
    monkeypatch.setattr(seed, "engine", motor)
    monkeypatch.setattr(seed, "SessionLocal", Sessao)
    monkeypatch.setattr(seed, "aplicar_migracoes", lambda m: Base.metadata.create_all(m))
    monkeypatch.setattr(settings, "ENV", "dev")
    monkeypatch.delenv("ADMIN_INITIAL_PASSWORD", raising=False)
    yield motor, Sessao
    motor.dispose()


def _rodar(monkeypatch, *argumentos: str) -> None:
    monkeypatch.setattr(sys, "argv", ["seed.py", *argumentos])
    seed.main()


def _povoar(motor, Sessao, *, escola: bool = True, dono: bool = True) -> None:
    """Um banco "de verdade" (inventado): escola com criança e a conta global do dono."""
    Base.metadata.create_all(motor)
    with Sessao() as db:
        if escola:
            e = Escola(nome=ESCOLA_ALHEIA, ano_letivo_ativo=2026)
            db.add(e)
            db.flush()
            db.add(Aluno(escola_id=e.id, nome="Criança Inventada Um"))
        if dono:
            db.add(Usuario(escola_id=None, nome="Dono Inventado", email=DONO_ALHEIO,
                           senha_hash="x", cargo="admin", is_global=True))
        db.commit()


def _retrato(Sessao) -> dict:
    with Sessao() as db:
        return {
            "escolas": sorted(db.execute(select(Escola.nome)).scalars()),
            "globais": sorted(db.execute(select(Usuario.email)
                                         .where(Usuario.is_global.is_(True))).scalars()),
            "alunos": db.scalar(select(func.count()).select_from(Aluno)),
        }


@pytest.mark.parametrize("argumentos", [(), ("--demo",)])
@pytest.mark.parametrize("escola, dono", [(True, True), (True, False), (False, True)])
def test_seed_recusa_banco_com_dados_que_nao_sao_dele(banco, monkeypatch, capsys,
                                                      argumentos, escola, dono):
    motor, Sessao = banco
    _povoar(motor, Sessao, escola=escola, dono=dono)
    antes = _retrato(Sessao)

    with pytest.raises(SystemExit) as saida:
        _rodar(monkeypatch, *argumentos)

    assert saida.value.code not in (0, None)
    assert _retrato(Sessao) == antes                 # nenhuma conta, escola ou criança
    erro = capsys.readouterr().err
    assert "banco NOVO" in erro and "--forcar" in erro


def test_seed_recusa_antes_de_migrar(banco, monkeypatch):
    """A recusa vem antes das migrações: o banco alheio não é tocado de jeito nenhum."""
    motor, Sessao = banco
    _povoar(motor, Sessao)
    migrou = []
    monkeypatch.setattr(seed, "aplicar_migracoes", lambda m: migrou.append(m))

    with pytest.raises(SystemExit):
        _rodar(monkeypatch)
    assert migrou == []


def test_forcar_semeia_mesmo_com_dados_alheios(banco, monkeypatch, capsys):
    motor, Sessao = banco
    _povoar(motor, Sessao)

    _rodar(monkeypatch, "--forcar")

    depois = _retrato(Sessao)
    assert depois["escolas"] == sorted([ESCOLA_ALHEIA, seed.ESCOLA_DEMO])
    assert depois["globais"] == sorted([DONO_ALHEIO, seed.ADMIN_EMAIL])
    assert f"Escola {seed.ESCOLA_DEMO} criada" in capsys.readouterr().out


@pytest.mark.parametrize("env", ["dev", "producao"])
def test_banco_novo_continua_sendo_semeado(banco, monkeypatch, env):
    """O passo 5 do PUBLICAR.md: instalação nova, com ENV=producao no compose."""
    _, Sessao = banco
    monkeypatch.setattr(settings, "ENV", env)

    _rodar(monkeypatch)

    depois = _retrato(Sessao)
    assert depois == {"escolas": [seed.ESCOLA_DEMO], "globais": [seed.ADMIN_EMAIL],
                      "alunos": 0}


def test_seed_de_novo_no_banco_que_ele_semeou_continua_idempotente(banco, monkeypatch,
                                                                   capsys):
    _, Sessao = banco
    _rodar(monkeypatch, "--demo")
    antes = _retrato(Sessao)
    assert antes["alunos"] == len(seed.DEMO_ALUNOS)

    _rodar(monkeypatch, "--demo")

    assert _retrato(Sessao) == antes
    saida = capsys.readouterr().out
    assert "Seed já executado anteriormente" in saida
    assert "Dados de demonstração já existem" in saida


@pytest.mark.parametrize("env", ["producao", "staging"])
@pytest.mark.parametrize("argumentos", [("--demo",), ("--demo", "--forcar")])
def test_demo_so_roda_em_desenvolvimento(banco, monkeypatch, capsys, env, argumentos):
    motor, Sessao = banco
    monkeypatch.setattr(settings, "ENV", env)
    migrou = []
    monkeypatch.setattr(seed, "aplicar_migracoes", lambda m: migrou.append(m))

    with pytest.raises(SystemExit) as saida:
        _rodar(monkeypatch, *argumentos)

    assert saida.value.code not in (0, None)
    assert migrou == []                              # nada migrado, nada gravado
    assert "--demo" in capsys.readouterr().err
