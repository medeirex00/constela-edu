"""Integridade referencial: comportamento REAL de ON DELETE das FKs.

O conftest padrão roda com a checagem de FK DESLIGADA (SQLite default). Aqui
usamos um engine próprio com PRAGMA foreign_keys=ON (como a aplicação em
produção) para exercitar CASCADE / SET NULL / RESTRICT de verdade.
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models        # noqa: F401
import app.quest.models  # noqa: F401
from app.core.database import Base
from app.models import (
    Aluno, ConversaIA, DispositivoMovel, Escola, Importacao, Leitura, Livro,
    LogAuditoria, Matricula, MensagemIA, Nota, Professor, TokenResetSenha,
    Turma, Usuario,
)
from app.quest.models import QuestCredencialAluno, QuestPerfil


@pytest.fixture()
def sessao():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _rec):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(engine)
    Sess = sessionmaker(bind=engine)
    s = Sess()
    yield s
    s.close()
    engine.dispose()


def _conta(s, modelo) -> int:
    return s.execute(select(func.count()).select_from(modelo)).scalar()


def _escola(s) -> Escola:
    e = Escola(nome="E", ano_letivo_ativo=2026)
    s.add(e)
    s.flush()
    return e


def test_apagar_aluno_cascateia_filhos_mas_preserva_livro(sessao):
    s = sessao
    e = _escola(s)
    a = Aluno(escola_id=e.id, nome="Aluno X")
    liv = Livro(escola_id=e.id, titulo="L", nivel_codigo="AA")
    s.add_all([a, liv])
    s.flush()
    t = Turma(escola_id=e.id, nome="T", ano_escolar="1º Ano", ano_letivo=2026)
    s.add(t)
    s.flush()
    s.add_all([
        Leitura(escola_id=e.id, aluno_id=a.id, livro_id=liv.id),
        Nota(escola_id=e.id, aluno_id=a.id, ano_letivo=2026),
        Matricula(escola_id=e.id, aluno_id=a.id, turma_id=t.id, ano_letivo=2026),
        QuestPerfil(escola_id=e.id, aluno_id=a.id, apelido="X", codigo_amigo="AX01"),
        QuestCredencialAluno(escola_id=e.id, aluno_id=a.id,
                             codigo_login="SOL1", qr_token="qr-ax"),
    ])
    s.commit()

    s.delete(a)
    s.commit()

    assert _conta(s, Leitura) == 0
    assert _conta(s, Nota) == 0
    assert _conta(s, Matricula) == 0
    assert _conta(s, QuestPerfil) == 0          # antes falhava (não tratado)
    assert _conta(s, QuestCredencialAluno) == 0  # antes falhava
    assert s.get(Livro, liv.id) is not None      # livro NÃO some, só a leitura
    assert s.get(Turma, t.id) is not None         # turma NÃO some, só a matrícula


def test_apagar_usuario_cascateia_pessoal_e_anula_autoria(sessao):
    s = sessao
    e = _escola(s)
    u = Usuario(escola_id=e.id, nome="U", email="u@x.local",
                senha_hash="h", cargo="admin")
    s.add(u)
    s.flush()
    c = ConversaIA(escola_id=e.id, usuario_id=u.id)
    s.add(c)
    s.flush()
    imp = Importacao(escola_id=e.id, usuario_id=u.id, plataforma="matific", tipo="pdf")
    log = LogAuditoria(escola_id=e.id, usuario_id=u.id, acao="teste")
    s.add_all([
        TokenResetSenha(usuario_id=u.id, token_hash="abc",
                        expira_em=datetime.now(timezone.utc)),
        MensagemIA(conversa_id=c.id, papel="usuario", conteudo="oi"),
        DispositivoMovel(escola_id=e.id, usuario_id=u.id,
                         token_push="tok", plataforma="android"),
        imp, log,
    ])
    s.commit()

    s.delete(u)
    s.commit()

    # CASCADE — dados pessoais somem (inclui o cascade em cadeia conversa→mensagem)
    assert _conta(s, TokenResetSenha) == 0       # corrige o bug do reset de senha
    assert _conta(s, ConversaIA) == 0
    assert _conta(s, MensagemIA) == 0
    assert _conta(s, DispositivoMovel) == 0
    # SET NULL — história institucional preservada, sem autoria
    assert s.get(Importacao, imp.id).usuario_id is None
    assert s.get(LogAuditoria, log.id).usuario_id is None


def test_apagar_professor_desvincula_a_turma(sessao):
    s = sessao
    e = _escola(s)
    p = Professor(escola_id=e.id, nome="P")
    s.add(p)
    s.flush()
    t = Turma(escola_id=e.id, nome="T", ano_escolar="1º Ano", ano_letivo=2026,
              professor_id=p.id)
    s.add(t)
    s.commit()

    s.delete(p)
    s.commit()

    assert s.get(Turma, t.id).professor_id is None   # SET NULL: turma sobrevive


def test_restrict_bloqueia_apagar_livro_e_turma_com_dependentes(sessao):
    s = sessao
    e = _escola(s)
    a = Aluno(escola_id=e.id, nome="A")
    liv = Livro(escola_id=e.id, titulo="L", nivel_codigo="AA")
    s.add_all([a, liv])
    s.flush()
    t = Turma(escola_id=e.id, nome="T", ano_escolar="1º Ano", ano_letivo=2026)
    s.add(t)
    s.flush()
    s.add_all([
        Leitura(escola_id=e.id, aluno_id=a.id, livro_id=liv.id),
        Matricula(escola_id=e.id, aluno_id=a.id, turma_id=t.id, ano_letivo=2026),
    ])
    s.commit()

    # Livro com leituras: NO ACTION bloqueia (preserva histórico)
    with pytest.raises(IntegrityError):
        s.delete(liv)
        s.commit()
    s.rollback()

    # Turma com matrícula: NO ACTION bloqueia (o app oferece "arquivar")
    with pytest.raises(IntegrityError):
        s.delete(t)
        s.commit()
    s.rollback()
