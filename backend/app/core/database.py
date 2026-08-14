"""Sessão e engine do banco de dados.

SQLAlchemy 2.0 com ORM declarativo. O mesmo código funciona em SQLite
(desenvolvimento) e PostgreSQL (produção) — basta trocar DATABASE_URL.
"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

is_sqlite = settings.DATABASE_URL.startswith("sqlite")

if is_sqlite:
    engine = create_engine(
        settings.DATABASE_URL,
        connect_args={"check_same_thread": False},
    )
else:
    # Banco de rede (PostgreSQL em produção): pool dimensionado e verificação
    # de conexões mortas antes de reusar (pool_pre_ping) evitam erros
    # intermitentes após timeouts do banco. Total por worker uvicorn =
    # DB_POOL_SIZE + DB_MAX_OVERFLOW.
    engine = create_engine(
        settings.DATABASE_URL,
        pool_pre_ping=True,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_recycle=settings.DB_POOL_RECYCLE,
    )

if is_sqlite:
    # Garante integridade referencial no SQLite (desligada por padrão).
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Namespace fixo dos advisory locks de importação (o 1º argumento de
# pg_advisory_xact_lock separa nossos locks de qualquer outro uso futuro).
_NS_IMPORTACAO = 4711


def bloquear_escola_para_importacao(db, escola_id: int) -> None:
    """Serializa importações concorrentes da MESMA escola.

    A importação faz SELECT-then-INSERT de turmas/alunos casando contra o estado
    lido no INÍCIO; dois envios sobrepostos (double-click, retry de proxy/mobile)
    veem ambos o estado antigo e ambos criam — duplicando o corpo discente.

    PostgreSQL: ``pg_advisory_xact_lock`` faz a 2ª importação BLOQUEAR até a 1ª
    commitar; aí ela relê o estado já com as linhas criadas e CASA em vez de
    duplicar. É transacional — o lock cai sozinho no commit/rollback, então deve
    ser adquirido ANTES de carregar o estado e sem commit no meio.

    SQLite (dev/testes): no-op — banco de um único escritor; produção é Postgres.
    A defesa cross-DB para turmas é o índice único ``uq_turma_escola_ano_nome``
    (o insert de turma trata a colisão sem estourar 500)."""
    if db.get_bind().dialect.name == "postgresql":
        from sqlalchemy import text
        db.execute(text("SELECT pg_advisory_xact_lock(:ns, :escola)"),
                   {"ns": _NS_IMPORTACAO, "escola": int(escola_id)})


# Namespace dos advisory locks de COLETA de avaliação externa (separado do de
# importação para não colidirem entre si).
_NS_COLETA_AVALIACAO = 4712


def bloquear_fonte_para_coleta(db, fonte_id: int) -> None:
    """Serializa coletas concorrentes da MESMA fonte de avaliação externa (o
    scheduler e o "coletar agora" manual disparam o mesmo ``coletar_fonte``).

    PostgreSQL: ``pg_advisory_xact_lock`` faz a 2ª coleta BLOQUEAR até a 1ª
    commitar; aí ela relê os resultados já gravados e ATUALIZA em vez de duplicar
    (o importar_resultados faz SELECT-then-INSERT). Transacional — cai no commit;
    adquirir ANTES de baixar/importar e sem commit no meio.

    SQLite (dev/testes): no-op — banco de um só escritor. A defesa cross-DB é o
    índice único ``uq_resultado_natural`` (a 2ª inserção do mesmo fato esbarra)."""
    if db.get_bind().dialect.name == "postgresql":
        from sqlalchemy import text
        db.execute(text("SELECT pg_advisory_xact_lock(:ns, :fonte)"),
                   {"ns": _NS_COLETA_AVALIACAO, "fonte": int(fonte_id)})


# Namespace dos advisory locks do RECÁLCULO de notas (separado dos de
# importação e coleta — travas distintas não podem se bloquear entre si).
_NS_RECALCULO = 4713


def bloquear_escola_para_recalculo(db, escola_id: int) -> None:
    """Serializa recálculos concorrentes da MESMA escola.

    ``scoring.recalcular_escola`` faz SELECT-then-INSERT em ``notas``: lê o
    ranking inteiro, calcula em memória e grava uma linha por aluno. Dois
    recálculos sobrepostos da mesma escola (importação terminando + mudança de
    peso, /recalcular clicado duas vezes, sync automática junto do gestor) leem
    o MESMO estado e gravam um por cima do outro. As três consequências:

      * ``notas`` vazia → os dois INSERTem e ``uq_nota_aluno_ano`` estoura
        (UniqueViolation → HTTP 500 na cara do gestor);
      * ordens de ranking diferentes → DEADLOCK, porque a ordem dos INSERTs é a
        ordem do ranking;
      * ``notas`` já existente → os dois UPDATEam, sem erro nenhum, e vence
        quem gravar por último — que pode ser justamente quem LEU o estado mais
        velho. Corrupção silenciosa: é o dano real, o 500 é só o sintoma.

    PostgreSQL: ``pg_advisory_xact_lock`` faz o 2º recálculo BLOQUEAR até o 1º
    commitar; aí ele relê o estado já gravado e recalcula em cima dele — quem
    grava por último leu por último. É transacional (cai sozinho no commit do
    fim do recálculo), então deve ser adquirido ANTES de qualquer leitura que
    participe do cálculo e sem commit no meio.

    HIERARQUIA (regra de ouro contra deadlock ENTRE travas): nunca adquirir
    esta segurando ``_NS_IMPORTACAO`` (4711). Todos os chamadores de
    ``recalcular_escola`` comitam antes de chamá-lo — inclusive os dois
    endpoints de importação, que soltam 4711 no commit e só então recalculam.
    ``tests/test_recalculo_concorrencia.py`` guarda essa ordem.

    SQLite (dev/testes): no-op — banco de um único escritor; produção é
    Postgres. A defesa cross-DB é a própria ``uq_nota_aluno_ano``, que impede a
    duplicata virar permanente (ao custo do 500 que esta trava elimina)."""
    if db.get_bind().dialect.name == "postgresql":
        from sqlalchemy import text
        db.execute(text("SELECT pg_advisory_xact_lock(:ns, :escola)"),
                   {"ns": _NS_RECALCULO, "escola": int(escola_id)})


# --------------------------------------------------------------------------
# Correções de DADOS no início da aplicação.
#
# O SCHEMA é responsabilidade do Alembic (app/core/migracoes.py + alembic/).
# Aqui ficam apenas ajustes de DADOS idempotentes: o banco de produção não tem
# acesso administrativo direto, então estas correções rodam a cada boot (são
# baratas e seguras de repetir).
# --------------------------------------------------------------------------

# Conta do DONO do sistema: acesso global (todas as escolas). Idempotente —
# só escreve quando ainda não é global.
_EMAIL_ADMIN_GLOBAL = "edumedeiros1405@gmail.com"


def _promover_admin_global(motor=None) -> None:
    """Garante o acesso global do dono do sistema (idempotente)."""
    from sqlalchemy import inspect, text

    motor = motor or engine
    if "usuarios" not in inspect(motor).get_table_names():
        return
    with motor.begin() as conexao:
        conexao.execute(
            text("UPDATE usuarios SET is_global = :sim "
                 "WHERE lower(email) = :email AND is_global = :nao"),
            {"sim": True, "nao": False, "email": _EMAIL_ADMIN_GLOBAL})


def _backfill_codigo_niveis(motor=None) -> None:
    """Preenche o código estável das faixas antigas (deriva do nome)."""
    from sqlalchemy import inspect, text

    motor = motor or engine
    inspetor = inspect(motor)
    if "niveis_dificuldade" not in inspetor.get_table_names():
        return
    from app.models.configuracao import slug_nivel

    with motor.begin() as conexao:
        linhas = conexao.execute(text(
            "SELECT id, nome FROM niveis_dificuldade "
            "WHERE codigo IS NULL OR codigo = ''"
        )).all()
        for id_, nome in linhas:
            conexao.execute(
                text("UPDATE niveis_dificuldade SET codigo = :c WHERE id = :i"),
                {"c": slug_nivel(nome or "nivel"), "i": id_})


def _purgar_retencao_ia(motor=None) -> None:
    """Retenção LGPD das conversas do assistente no boot (garantia MÍNIMA; para
    cadência regular, agende `python -m scripts.purgar_ia`). Nunca derruba o
    boot: uma falha de purga é registrada e a aplicação segue."""
    from sqlalchemy import inspect
    from sqlalchemy.orm import Session

    motor = motor or engine
    if "conversas_ia" not in inspect(motor).get_table_names():
        return
    try:
        from app.services.assistente import purgar_conversas_ia_expiradas
        with Session(motor) as db:
            purgar_conversas_ia_expiradas(db)
    except Exception:  # noqa: BLE001 — purga de retenção nunca bloqueia o boot
        import logging
        logging.getLogger("constela").warning(
            "Purga de retenção de IA falhou no boot", exc_info=True)


def garantir_dados_base(motor=None) -> None:
    """Ajustes de dados idempotentes aplicados após as migrações de schema."""
    motor = motor or engine
    _backfill_codigo_niveis(motor)
    _promover_admin_global(motor)
    _purgar_retencao_ia(motor)
