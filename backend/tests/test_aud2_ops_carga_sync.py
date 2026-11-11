"""O teste de carga da fila (``scripts/carga_sync.py``) só mexe no que criou (achado G_SCRIPTS-6).

O DEFEITO. Os workers da carga reivindicavam QUALQUER execução com status 'fila' do
banco e a marcavam 'concluida' (com início e fim) sem rodar nada. Com
``--permitir-dados-reais`` — que o próprio script manda usar quando há escola de verdade
no banco, o normal num staging semeado —, uma coleta real enfileirada sumia como
"concluída" sem ter coletado nada (o "status mentiroso"), e o veredito dizia PASSOU com
mais reivindicadas que enfileiradas. O prefixo ``CARGA_TESTE_`` ia cru num LIKE, onde o
``_`` vale qualquer caractere: uma escola "CARGA TESTE ..." contava como de carga — a
trava não a via como real e a limpeza a apagava.

A CORREÇÃO, provada aqui: o claim só toca as execuções que a carga enfileirou; o
veredito reprova reivindicação fora da carga; o prefixo é comparado literalmente.

Banco: SQLite em arquivo temporário posto no lugar do banco do app. Nomes inventados.
"""
import sys

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import Escola, SincronizacaoExecucao
from scripts import carga_sync

ESCOLA_REAL = "Escola Inventada da Sonda de Carga"


@pytest.fixture()
def Sessao(tmp_path, monkeypatch):
    motor = create_engine(f"sqlite:///{(tmp_path / 'carga.db').as_posix()}",
                          connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(motor, "connect")
    def _fk_on(conexao, _registro):
        cur = conexao.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(motor)
    fabrica = sessionmaker(bind=motor)
    monkeypatch.setattr(carga_sync, "SessionLocal", fabrica)
    yield fabrica
    motor.dispose()


def _escola_com_coleta_na_fila(Sessao, nome: str = ESCOLA_REAL) -> int:
    with Sessao() as db:
        escola = Escola(nome=nome, ano_letivo_ativo=2026)
        db.add(escola)
        db.flush()
        ex = SincronizacaoExecucao(escola_id=escola.id, plataforma="matific",
                                   origem="manual", status="fila")
        db.add(ex)
        db.commit()
        return ex.id


def _rodar(monkeypatch, *argumentos: str) -> int:
    monkeypatch.setattr(sys, "argv", ["carga_sync.py", *argumentos])
    return carga_sync.main()


def test_coleta_real_na_fila_continua_na_fila(Sessao, monkeypatch, capsys):
    real_id = _escola_com_coleta_na_fila(Sessao)

    codigo = _rodar(monkeypatch, "--escolas", "3", "--workers", "2", "--go",
                    "--permitir-dados-reais")

    saida = capsys.readouterr().out
    with Sessao() as db:
        real = db.get(SincronizacaoExecucao, real_id)
        assert (real.status, real.iniciada_em, real.finalizada_em) == ("fila", None, None)
        assert list(db.execute(select(Escola.nome)).scalars()) == [ESCOLA_REAL]
    assert codigo == 0, saida
    assert "reivindicadas          : 3" in saida
    assert "VEREDITO: PASSOU" in saida


def test_veredito_reprova_reivindicacao_fora_da_carga(Sessao, monkeypatch, capsys):
    """Se um worker reivindicar o que a carga não enfileirou, o veredito não é PASSOU."""
    original = carga_sync._worker

    def _worker_que_invade(claimed, lock, *args, **kwargs):
        original(claimed, lock, *args, **kwargs)
        with lock:
            if -1 not in claimed:
                claimed.append(-1)                  # uma execução que não é da carga

    monkeypatch.setattr(carga_sync, "_worker", _worker_que_invade)

    codigo = _rodar(monkeypatch, "--escolas", "2", "--workers", "1", "--go")

    saida = capsys.readouterr().out
    assert codigo == 1, saida
    assert "VEREDITO: FALHOU" in saida


def test_escola_com_nome_parecido_com_o_prefixo_e_real(Sessao, monkeypatch, capsys):
    """'CARGA TESTE ...' não é escola de carga: a trava a conta como real e a limpeza
    não a apaga."""
    nome = "CARGA TESTE ESCOLA INVENTADA"
    _escola_com_coleta_na_fila(Sessao, nome)

    codigo = _rodar(monkeypatch, "--escolas", "2", "--workers", "1", "--go")

    assert codigo == 2, capsys.readouterr().out          # ABORTADO: há escola real
    with Sessao() as db:
        assert list(db.execute(select(Escola.nome)).scalars()) == [nome]

    codigo = _rodar(monkeypatch, "--escolas", "2", "--workers", "1", "--go",
                    "--permitir-dados-reais")

    assert codigo == 0, capsys.readouterr().out
    with Sessao() as db:
        assert list(db.execute(select(Escola.nome)).scalars()) == [nome]
