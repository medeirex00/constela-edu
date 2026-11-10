"""Sessão e engine do banco de dados.

SQLAlchemy 2.0 com ORM declarativo. O mesmo código funciona em SQLite
(desenvolvimento) e PostgreSQL (produção) — basta trocar DATABASE_URL.
"""
import os

from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from starlette.requests import Request

from app.core.config import settings
from app.core.mantenedor_do_pool import marcar_abertura

is_sqlite = settings.DATABASE_URL.startswith("sqlite")


def argumentos_de_conexao_pg(url: str) -> dict:
    """``connect_args`` do driver PostgreSQL: o PRAZO para abrir uma conexão nova.

    Sem ``connect_timeout``, a conexão nova com um banco que não responde (host
    fora do ar, rede parada, proxy que aceita o TCP e não fala) fica presa no
    handshake pelo padrão do driver — 130 s no psycopg 3.2 da imagem —, com o
    worker uvicorn junto; o ``pool_pre_ping`` não ajuda, porque é justamente a
    reconexão que pendura. O prazo vem de ``DB_CONNECT_TIMEOUT`` (padrão 10 s) e
    vai ao psycopg como o ``connect_timeout`` da libpq (o driver não aceita
    menos de 2 s).

    Fica de fora (dicionário vazio): URL que não é PostgreSQL, ``DB_CONNECT_TIMEOUT``
    zero ou negativo (sem prazo do app, padrão do driver), URL que já declara o
    seu ``?connect_timeout=`` e ambiente com a variável ``PGCONNECT_TIMEOUT`` da
    libpq definida e não vazia (vale também ``0``) — o ``connect_args``
    sobrescreveria o da URL e esconderia o da variável (o psycopg só a lê quando o
    parâmetro não vem), e a escolha explícita do operador vale mais que o padrão."""
    u = make_url(url)
    if u.get_backend_name() != "postgresql" or "connect_timeout" in u.query:
        return {}
    if os.environ.get("PGCONNECT_TIMEOUT", "").strip():
        return {}
    prazo = settings.DB_CONNECT_TIMEOUT
    return {"connect_timeout": prazo} if prazo > 0 else {}


def opcoes_do_engine(url: str) -> dict:
    """Argumentos do ``create_engine`` para a URL (SQLite em dev, PostgreSQL em produção).

    ``hide_parameters=True`` nos DOIS ramos: sem ele, toda exceção de banco
    (IntegrityError, DataError, conexão caída no meio da consulta) traz
    ``[parameters: (...)]`` no próprio texto — o nome da criança no INSERT/UPDATE
    de aluno, o termo do ``?busca=``, o código ou o QR do Quest no caminho de
    transição. Esse texto vai inteiro para o log de erro (``erro_nao_tratado`` e o
    ``logger.exception`` da sync gravam o traceback) e para o Sentry (o valor da
    exceção; ``send_default_pii=False`` e ``include_local_variables=False`` não o
    cobrem). Com a opção, a mensagem mantém o SQL e troca os valores por "[SQL
    parameters hidden ...]". Não cobre o que o PRÓPRIO PostgreSQL escreve na
    mensagem (o ``DETAIL: Key (...)=(...)`` de uma violação de UNIQUE leva o valor
    da coluna indexada; nenhum índice único de hoje tem nome de pessoa)."""
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}, "hide_parameters": True}
    # Banco de rede (PostgreSQL em produção): pool dimensionado. Total por worker
    # uvicorn = DB_POOL_SIZE + DB_MAX_OVERFLOW. Conexão NOVA com prazo para abrir
    # (``argumentos_de_conexao_pg``). A conexão morta é pega pelo ping SÓ da conexão
    # parada (``instalar_ping_por_ociosidade``), não pelo ``pool_pre_ping`` (um ping a
    # cada retirada, uma ida ao banco a mais em toda requisição). O pool LIFO entrega a
    # conexão devolvida por último — a mais quente, que dispensa o ping; o FIFO padrão
    # entregaria a parada há mais tempo e o ping voltaria a ser pago.
    opcoes = {
        "pool_use_lifo": True,
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_recycle": settings.DB_POOL_RECYCLE,
        "hide_parameters": True,
    }
    connect_args = argumentos_de_conexao_pg(url)
    if connect_args:
        opcoes["connect_args"] = connect_args
    return opcoes


_ULTIMO_USO = "constela_ultimo_uso"


def instalar_ping_por_ociosidade(motor, limite_s: float | None = None) -> None:
    """Testa com um ping só a conexão que ficou PARADA no pool além do limite.

    Antes, ``pool_pre_ping`` mandava um ``SELECT 1`` a cada retirada do pool: em produção
    (API a ~195 ms do banco) era uma ida a mais em TODA requisição, mesmo na conexão
    usada um instante antes. Agora a hora do último uso fica no registro da conexão (ao
    abrir e ao devolver) e, na retirada, só a conexão parada há mais de ``limite_s``
    (padrão ``DB_PING_OCIOSO_S``, 30 s; ``0`` = sempre, como antes) é pingada. O ping é o
    do próprio dialeto (``do_ping``: em autocommit, sem abrir transação). Se ele falhar,
    ``InvalidatePoolError`` (uma ``DisconnectionError``): o pool descarta essa conexão e
    todas as abertas antes dela (o banco ou o pooler reiniciou: as outras também morreram)
    e entrega uma nova — o mesmo efeito do ``pool_pre_ping``.

    O que se aceita: a conexão que morre DENTRO da janela (reinício do banco ou do pooler
    há menos de ``limite_s`` do último uso) dá erro em UMA requisição; o SQLAlchemy vê a
    desconexão, invalida o pool, e a seguinte reconecta (o ``useApi`` do site repete 5xx
    uma vez). Use com ``pool_use_lifo`` (``opcoes_do_engine``)."""
    from time import monotonic

    from sqlalchemy.exc import InvalidatePoolError

    def _agora(_dbapi_connection, registro, *_a) -> None:
        registro.info[_ULTIMO_USO] = monotonic()

    def _na_retirada(dbapi_connection, registro, _proxy) -> None:
        limite = settings.DB_PING_OCIOSO_S if limite_s is None else limite_s
        ultimo = registro.info.get(_ULTIMO_USO)
        if ultimo is not None and monotonic() - ultimo < limite:
            return
        try:
            motor.dialect.do_ping(dbapi_connection)
        except motor.dialect.loaded_dbapi.Error as erro:
            raise InvalidatePoolError("a conexão parada no pool não respondeu ao ping") from erro
        registro.info[_ULTIMO_USO] = monotonic()

    event.listen(motor, "connect", _agora)
    event.listen(motor, "checkin", _agora)
    event.listen(motor, "checkout", _na_retirada)


def desligar_prepared_statements(motor) -> None:
    """``prepare_threshold = None`` em toda conexão nova do psycopg (os outros drivers: nada).

    O psycopg 3 prepara no servidor o comando executado 5 vezes na mesma conexão: a 6ª
    execução custa uma ida a mais (o PREPARE). Até aqui o ROLLBACK do fim de cada
    requisição zerava a contagem (e um DEALLOCATE ALL, mais uma ida, se algo tinha sido
    preparado). Nas leituras sem transação (``leitura_sem_transacao``) não há ROLLBACK: a
    contagem cresceria de requisição em requisição e o PREPARE cairia numa delas. Sem
    prepared statements, nenhuma das duas idas; o banco planeja cada comando (frações de
    milissegundo nestas consultas, contra ~195 ms de cada ida em produção)."""
    if motor.dialect.driver != "psycopg":
        return

    def _sem_prepared(dbapi_connection, _registro) -> None:
        dbapi_connection.prepare_threshold = None

    event.listen(motor, "connect", _sem_prepared)


def sessao_de_leitura(motor) -> sessionmaker:
    """As sessões das rotas ``leitura_sem_transacao``: o MESMO pool, em AUTOCOMMIT.

    O psycopg manda o BEGIN numa ida própria antes da primeira consulta, e o ``close`` da
    sessão manda o ROLLBACK em outra — duas idas ao banco (~195 ms cada em produção) que
    não trazem dado. Em AUTOCOMMIT cada consulta roda sozinha, sem BEGIN nem ROLLBACK. A
    consistência não muda: o isolamento é o padrão do PostgreSQL (READ COMMITTED), em que
    cada consulta já vê o seu próprio instante. A troca é local na conexão (o atributo
    ``autocommit`` do psycopg, sem ida) e o SQLAlchemy a desfaz ao devolver a conexão ao
    pool: as sessões que gravam continuam com transação."""
    return sessionmaker(bind=motor.execution_options(isolation_level="AUTOCOMMIT"),
                        autoflush=False, autocommit=False)


engine = create_engine(settings.DATABASE_URL, **opcoes_do_engine(settings.DATABASE_URL))

if not is_sqlite:
    instalar_ping_por_ociosidade(engine)
    desligar_prepared_statements(engine)
    # A hora de abertura de cada conexão: o mantenedor do pool reabre a que está perto do
    # ``pool_recycle`` antes que uma requisição a pegue (ligado no startup, ``app.main``).
    marcar_abertura(engine)

if is_sqlite:
    # Garante integridade referencial no SQLite (desligada por padrão).
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
# As rotas de leitura marcadas: sem transação no PostgreSQL; no SQLite (desenvolvimento e
# testes) a mesma sessão de sempre.
SessionLeitura = SessionLocal if is_sqlite else sessao_de_leitura(engine)


class Base(DeclarativeBase):
    pass


_MARCA_LEITURA = "_constela_leitura_sem_transacao"


def leitura_sem_transacao(endpoint):
    """Marca uma rota GET que SÓ LÊ para rodar sem transação (``SessionLeitura``).

    Lista FECHADA e explícita — não "todo GET": só a rota cujo código inteiro (a rota, as
    dependências e os serviços) nunca grava, nunca usa ``FOR UPDATE``, ``SET LOCAL``,
    advisory lock nem tabela temporária. ``tests/test_leitura_sem_transacao.py`` guarda a
    lista e roda cada rota marcada com uma sessão que recusa qualquer escrita. Vai logo
    abaixo do ``@router.get(...)``; devolve a própria função."""
    setattr(endpoint, _MARCA_LEITURA, True)
    return endpoint


def e_leitura_sem_transacao(endpoint) -> bool:
    return getattr(endpoint, _MARCA_LEITURA, False) is True


def get_db(request: Request = None):  # type: ignore[assignment]
    """A sessão da requisição. A rota marcada com ``leitura_sem_transacao`` recebe a de
    ``SessionLeitura``; as demais (e quem chama sem requisição: o boot, os scripts), a de
    ``SessionLocal``. O ``request`` vem do FastAPI (que o reconhece pela anotação); o
    endpoint é o da rota casada (``scope["endpoint"]``)."""
    leitura = request is not None and e_leitura_sem_transacao(request.scope.get("endpoint"))
    db = (SessionLeitura if leitura else SessionLocal)()
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
#
# O e-mail vem SEMPRE de configuração explícita (ADMIN_GLOBAL_EMAIL) e NUNCA do
# código. Cravá-lo aqui transformava cada ambiente NOVO — município novo,
# staging, homologação, restauração de desastre — numa conta administrativa
# reivindicável: bastava um admin de UMA escola criar um usuário com aquele
# e-mail e esperar o próximo boot para virar administrador global de todas as
# redes. Sem a variável declarada, este ajuste é um NO-OP (fail-closed).
def _promover_admin_global(motor=None) -> None:
    """Garante o acesso global do dono do sistema (idempotente).

    Só age quando ``ADMIN_GLOBAL_EMAIL`` está declarado no ambiente; nesse caso
    o mesmo e-mail fica RESERVADO contra criação por rotas de escola
    (``config.email_reservado_ao_dono``), fechando a reivindicação da conta.
    """
    from sqlalchemy import inspect, text

    email = (settings.ADMIN_GLOBAL_EMAIL or "").strip().lower()
    if not email:
        return
    motor = motor or engine
    if "usuarios" not in inspect(motor).get_table_names():
        return
    with motor.begin() as conexao:
        conexao.execute(
            text("UPDATE usuarios SET is_global = :sim "
                 "WHERE lower(email) = :email AND is_global = :nao"),
            {"sim": True, "nao": False, "email": email})


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
