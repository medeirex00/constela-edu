"""A decisão de descartar usa a mesma trava da resolução e da coleta."""
import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.core.database import Base, _NS_IMPORTACAO
from app.models import Escola, RevisaoIdentidade, Usuario
from app.routers import importacoes
from app.schemas.importacao import DescartarRevisaoIn
from tests.test_migracoes_postgres import engine_postgres  # noqa: F401 — fixture


@pytest.mark.postgres
def test_descartar_trava_a_escola_antes_de_ler_a_revisao(engine_postgres):
    Base.metadata.create_all(engine_postgres)
    with Session(engine_postgres, autoflush=False) as db:
        escola = Escola(nome="Escola Fictícia das Decisões", ano_letivo_ativo=2026)
        db.add(escola)
        db.flush()
        escola_id = escola.id
        gestor = Usuario(escola_id=escola_id, nome="Gestora de Teste", cargo="coordenador",
                         email="gestora-travas@teste.local", senha_hash="x")
        rev = RevisaoIdentidade(escola_id=escola_id, chave="conta-ficticia",
                                chave_identidade="conta-ficticia", plataforma="matific",
                                nome_recebido="Aluno Fictício", motivo="sem_correspondencia")
        db.add_all([gestor, rev])
        db.flush()
        revisao_id = rev.id
        db.commit()
        db.expunge(rev)
        leituras = []

        def conferir_trava(conn, cursor, sql, params, contexto, executemany):
            if leituras or not sql.lstrip().startswith("SELECT"):
                return
            if "FROM revisoes_identidade" not in sql:
                return
            with engine_postgres.connect() as outra:
                livre = outra.execute(text("SELECT pg_try_advisory_xact_lock(:ns, :escola)"),
                                      {"ns": _NS_IMPORTACAO, "escola": escola_id}).scalar_one()
            leituras.append(livre)

        event.listen(engine_postgres, "before_cursor_execute", conferir_trava)
        try:
            resultado = importacoes.descartar_revisao(
                revisao_id, DescartarRevisaoIn(motivo="conta de teste"), escola_id, gestor, db)
        finally:
            event.remove(engine_postgres, "before_cursor_execute", conferir_trava)

        assert leituras == [False]
        assert resultado.status == "descartada"
