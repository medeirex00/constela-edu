"""As duas escritas do painel tomam a mesma trava antes de ler a configuração."""
import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Escola, Usuario
from app.routers import publico
from tests.test_migracoes_postgres import engine_postgres  # noqa: F401 — fixture

pytestmark = pytest.mark.postgres


@pytest.fixture
def escola_e_gestor(engine_postgres):
    Base.metadata.create_all(engine_postgres)
    with Session(engine_postgres, autoflush=False) as db:
        escola = Escola(nome="Escola Fictícia das Decisões", ano_letivo_ativo=2026)
        db.add(escola)
        db.flush()
        gestor = Usuario(escola_id=escola.id, nome="Gestora de Teste", cargo="coordenador",
                         email="gestora-travas@teste.local", senha_hash="x")
        db.add(gestor)
        db.commit()
        yield db, escola.id, gestor


@pytest.mark.parametrize("rotacionar", [False, True], ids=["salvar", "novo-token"])
def test_painel_serializa_a_gravacao_antes_de_ler_a_config(
        engine_postgres, escola_e_gestor, rotacionar):
    db, escola_id, gestor = escola_e_gestor
    leituras = []

    def conferir_trava(conn, cursor, sql, params, contexto, executemany):
        if not sql.lstrip().startswith("SELECT") or "FROM configuracoes" not in sql:
            return
        with engine_postgres.connect() as outra:
            with pytest.raises(OperationalError) as erro:
                outra.execute(select(Escola.id).where(Escola.id == escola_id)
                              .with_for_update(nowait=True, key_share=True))
        leituras.append(erro.value.orig.sqlstate)

    event.listen(engine_postgres, "before_cursor_execute", conferir_trava)
    try:
        if rotacionar:
            resultado = publico.trocar_token(escola_id=escola_id, usuario=gestor, db=db)
        else:
            resultado = publico.salvar_config(publico.PainelConfigIn(ativo=True),
                                               escola_id=escola_id, usuario=gestor, db=db)
    finally:
        event.remove(engine_postgres, "before_cursor_execute", conferir_trava)

    assert leituras == ["55P03"]
    assert resultado["url"]
