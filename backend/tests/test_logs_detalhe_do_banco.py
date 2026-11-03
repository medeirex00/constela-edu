"""O DETAIL que o PostgreSQL escreve no erro não leva dado de criança ao log nem ao Sentry.

``hide_parameters`` (core/database.py) tira os PARÂMETROS que o SQLAlchemy põe na
mensagem; mas numa violação de NOT NULL/CHECK o próprio servidor copia a linha
inteira no texto do erro ("Failing row contains (…)") e, numa de UNIQUE/FK, o valor
da chave ("Key (coluna)=(valor) …"). Isso chegava ao ``erro_nao_tratado`` e ao
evento do Sentry. Os valores saem; os nomes das colunas ficam para o diagnóstico.
"""
import json
import logging
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core import observabilidade as obs

NOME_FICTICIO = "Zuleica Testelli Sintetico"
SEGUNDA_LINHA = "segunda linha Ficticia"
# Teto de tempo dos testes de custo linear: o mesmo padrão de test_planilha_inflada.py.
# 2 s numa máquina comum (os de texto adversarial usam a metade: 1 s, como antes); no
# CI (cobertura ligada, runner compartilhado 2–3x mais lento) 12 s e 6 s. Medido com
# --cov=app numa máquina comum: 0,01–0,2 s. A regressão que eles pegam é quadrática
# (1 MB não terminava em 300 s), longe de qualquer um dos tetos. TESTE_TETO_TEMPO_S
# sobrepõe o valor (o de 2 s; os outros seguem a proporção).
TETO_S = float(os.environ.get("TESTE_TETO_TEMPO_S") or (12 if os.environ.get("CI") else 2))


def test_redige_linha_recusada_e_valor_de_chave():
    linha = ('null value in column "escola_id" of relation "alunos" violates not-null '
             'constraint\nDETAIL:  Failing row contains (7, null, ' + NOME_FICTICIO +
             ', 2017-03-04, ativo).')
    chave = ('duplicate key value violates unique constraint "uq_x"\nDETAIL:  Key '
             '(escola_id, nome)=(3, ' + NOME_FICTICIO + ') already exists.')
    for texto in (linha, chave):
        redigido = obs.redigir_detalhe_do_banco(texto)
        for parte in NOME_FICTICIO.split():
            assert parte not in redigido
        assert "<redigido>" in redigido
    assert '"escola_id"' in obs.redigir_detalhe_do_banco(linha)        # o diagnóstico fica
    # Sem a exceção, o texto é cortado no DETAIL (a restrição, antes dele, fica); com
    # ela, ficam também os nomes das colunas.
    assert obs.redigir_detalhe_do_banco(chave).endswith('"uq_x"\nDETAIL:  <redigido>')
    detalhe = chave.split("DETAIL:  ")[1]
    assert obs.redigir_detalhe_do_banco(chave, _ErroDoBanco(chave, detalhe)).endswith(
        "DETAIL:  Key (escola_id, nome)=(<redigido>) already exists.")
    assert obs.redigir_detalhe_do_banco("erro qualquer") == "erro qualquer"


@pytest.fixture
def engine_postgres():
    url = os.environ.get("TEST_DATABASE_URL_PG")
    if not url:
        pytest.skip("defina TEST_DATABASE_URL_PG para rodar contra PostgreSQL real")
    if "test" not in (make_url(url).database or "").lower():
        pytest.skip("TEST_DATABASE_URL_PG precisa apontar para banco de teste")
    engine = create_engine(url, hide_parameters=True)
    with engine.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS _detalhe_teste"))
        c.execute(text("CREATE TABLE _detalhe_teste (id serial primary key, escola_id int NOT NULL, "
                       "nome text NOT NULL UNIQUE)"))
    yield engine
    with engine.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS _detalhe_teste"))
    engine.dispose()


@pytest.mark.postgres
@pytest.mark.parametrize("caso", ["not_null", "unique"])
def test_erro_real_do_postgres_sai_sem_o_nome_no_log_e_no_sentry(engine_postgres, caso):
    if caso == "unique":
        with engine_postgres.begin() as c:
            c.execute(text("INSERT INTO _detalhe_teste (escola_id, nome) VALUES (1, :n)"),
                      {"n": NOME_FICTICIO})
    with pytest.raises(IntegrityError) as erro:
        with engine_postgres.begin() as c:
            c.execute(text("INSERT INTO _detalhe_teste (escola_id, nome) VALUES (:e, :n)"),
                      {"e": None if caso == "not_null" else 2, "n": NOME_FICTICIO})
    bruto = str(erro.value)
    assert "DETAIL" in bruto and NOME_FICTICIO.split()[1] in bruto     # controle: o servidor copiou

    registro = logging.LogRecord("constela", logging.ERROR, __file__, 1, "erro_nao_tratado",
                                 None, (type(erro.value), erro.value, erro.tb))
    linha_log = obs.FormatadorJson().format(registro)
    evento = obs.higienizar_evento_sentry(
        {"exception": {"values": [{"type": "IntegrityError", "value": bruto}]},
         "logentry": {"message": bruto}})
    for parte in NOME_FICTICIO.split():
        assert parte not in linha_log, f"pedaço do nome no log: {parte}"
        assert parte not in str(evento), f"pedaço do nome no Sentry: {parte}"
    assert "<redigido>" in linha_log



def test_valor_com_quebra_de_linha_tambem_e_redigido():
    """As observações do aluno são textarea: a 1ª linha do DETAIL acabava no meio do
    valor, sem o ')' — a regex de uma linha não casava e nada era redigido."""
    detalhe = ("Failing row contains (1, 7, null, 2017-03-04, " + NOME_FICTICIO +
               " linha 1\nlinha 2 Testelli, {\"ra\": \"000000001\"}).")
    texto = ("sqlalchemy.exc.IntegrityError: (psycopg.errors.NotNullViolation) null value "
             "in column \"nome\" violates not-null constraint\nDETAIL:  " + detalhe +
             "\n[SQL: UPDATE alunos SET nome=%(nome)s]\n[SQL parameters hidden due to "
             "hide_parameters=True]")
    redigido = obs.redigir_detalhe_do_banco(texto)
    for parte in NOME_FICTICIO.split() + ["000000001", "2017-03-04", "linha 2"]:
        assert parte not in redigido, parte
    assert redigido.endswith("DETAIL:  <redigido>") and '"nome"' in redigido
    exato = obs.redigir_detalhe_do_banco(texto, _ErroDoBanco(texto, detalhe))
    assert "Failing row contains (<redigido>).\n[SQL: UPDATE alunos" in exato
    chave = 'Key (lower(nome::text))=(' + NOME_FICTICIO + '\nTestelli) already exists.'
    assert NOME_FICTICIO.split()[0] not in obs.redigir_detalhe_do_banco(chave)


@pytest.mark.postgres
def test_erro_real_com_quebra_de_linha_no_valor(engine_postgres):
    # Por variável: o traceback mostra a linha do código-fonte da chamada, e um
    # literal ali apareceria no log sem ter vindo do banco.
    valor = NOME_FICTICIO + "\n" + SEGUNDA_LINHA
    with pytest.raises(IntegrityError) as erro:
        with engine_postgres.begin() as c:
            c.execute(text("INSERT INTO _detalhe_teste (escola_id, nome) VALUES (NULL, :n)"),
                      {"n": valor})
    registro = logging.LogRecord("constela", logging.ERROR, __file__, 1, "erro_nao_tratado",
                                 None, (type(erro.value), erro.value, erro.tb))
    linha_log = obs.FormatadorJson().format(registro)
    evento = obs.higienizar_evento_sentry(
        {"exception": {"values": [{"type": "IntegrityError", "value": str(erro.value)}]}},
        {"exc_info": (type(erro.value), erro.value, erro.tb)})
    for parte in NOME_FICTICIO.split() + SEGUNDA_LINHA.split()[::2]:
        assert parte not in linha_log, f"pedaço no log: {parte}"
        assert parte not in str(evento), f"pedaço no Sentry: {parte}"


def test_patch_de_aluno_com_nome_nulo_e_422_e_nao_toca_o_banco():
    """O 500 que levava a linha do aluno ao log nascia de um PATCH com
    ``"nome": null``; agora o esquema recusa antes."""
    from pydantic import ValidationError

    from app.schemas import AlunoUpdate
    with pytest.raises(ValidationError):
        AlunoUpdate.model_validate({"nome": None})
    assert AlunoUpdate.model_validate({}).model_dump(exclude_unset=True) == {}
    assert AlunoUpdate.model_validate({"observacoes": None}).model_dump(
        exclude_unset=True) == {"observacoes": None}


# --- valor com ")" + linha em branco, CRLF e custo -----------------------------------

PARAGRAFO_1 = "Acompanhamento (semanal)"
PARAGRAFO_2 = "Segundo Paragrafo Ficticio"
RESPONSAVEL = "Responsavel Testelli"


class _Diag:
    def __init__(self, detalhe):
        self.message_detail = detalhe


class _ErroDoBanco(Exception):
    """Imita o psycopg: o DETAIL exato fica em ``diag.message_detail``."""

    def __init__(self, texto, detalhe):
        super().__init__(texto)
        self.diag = _Diag(detalhe)


@pytest.mark.parametrize("quebra", ["\n", "\r\n"])
def test_parenteses_e_linha_em_branco_dentro_do_valor_nao_encerram_a_redacao(quebra):
    """Observações em parágrafos: um ")" seguido de linha em branco DENTRO do valor
    encerrava a redação, e o resto da linha (2º parágrafo, a ficha) ia ao log."""
    detalhe = ("Failing row contains (1, 7, null, " + PARAGRAFO_1 + "." + quebra + quebra +
               PARAGRAFO_2 + ", {\"responsavel\": \"" + RESPONSAVEL + "\"}, 2026-10-21).")
    texto = ("sqlalchemy.exc.IntegrityError: (psycopg.errors.NotNullViolation) null value in "
             "column \"nome\" violates not-null constraint" + quebra + "DETAIL:  " + detalhe +
             quebra + "[SQL: INSERT INTO alunos (nome) VALUES (%(nome)s)]")
    for excecao in (None, _ErroDoBanco(texto, detalhe)):
        redigido = obs.redigir_detalhe_do_banco(texto, excecao)
        for parte in (PARAGRAFO_2.split() + RESPONSAVEL.split() + ["semanal"]):
            assert parte not in redigido, (excecao is not None, parte)
        assert '"nome"' in redigido
        if excecao is None:                         # sem o DETAIL exato: corta ali
            assert redigido.endswith("DETAIL:  <redigido>")
        else:
            assert "[SQL: INSERT INTO alunos" in redigido


def test_caminho_exato_redige_pela_estrutura_do_detalhe():
    chave = 'Key (escola_id, nome)=(3, ' + PARAGRAFO_1 + ')\n\n' + PARAGRAFO_2 + ') already exists.'
    redigido = obs.redigir_detalhe_do_banco("DETAIL:  " + chave, _ErroDoBanco("x", chave))
    assert redigido == "DETAIL:  Key (escola_id, nome)=(<redigido>) already exists."
    fk = 'Key (escola_id)=(' + PARAGRAFO_2 + ') is not present in table "escolas".'
    assert obs.redigir_detalhe_do_banco(fk, _ErroDoBanco("x", fk)) == (
        'Key (escola_id)=(<redigido>) is not present in table "escolas".')


_ADVERSARIOS = {
    "linha-1mb": lambda: "Failing row contains (" + ")" + " " * 1_000_000,
    "chave-400x": lambda: ("Key (a)=(" + ")" + " " * 3_000) * 400,
    "linha-50x": lambda: ("Failing row contains (" + ")" + " " * 8_000) * 50,
    "chave-sem-valor-2mb": lambda: "x" * 1_000_000 + "Key (" + "y" * 1_000_000,
}


@pytest.mark.parametrize("caso", sorted(_ADVERSARIOS))
def test_custo_linear_em_texto_adversarial(caso):
    """A regex anterior era quadrática nesses textos (1 MB não terminava em 300 s) e
    prendia o GIL: o worker inteiro parava enquanto um log era formatado. (O texto é
    montado aqui dentro: no id do teste ele estouraria a variável de ambiente.)"""
    import time
    texto = _ADVERSARIOS[caso]()
    comeco = time.perf_counter()
    obs.redigir_detalhe_do_banco(texto)
    assert time.perf_counter() - comeco < TETO_S / 2


@pytest.mark.postgres
def test_erro_real_com_paragrafo_e_coluna_seguinte(engine_postgres):
    with engine_postgres.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS _detalhe_teste2"))
        c.execute(text("CREATE TABLE _detalhe_teste2 (id serial primary key, nome text NOT NULL, "
                       "observacoes text, ficha text)"))
    obs_valor = PARAGRAFO_1 + "\n\n" + PARAGRAFO_2
    ficha_valor = RESPONSAVEL
    try:
        with pytest.raises(IntegrityError) as erro:
            with engine_postgres.begin() as c:
                c.execute(text("INSERT INTO _detalhe_teste2 (nome, observacoes, ficha) "
                               "VALUES (NULL, :o, :f)"), {"o": obs_valor, "f": ficha_valor})
        info = (type(erro.value), erro.value, erro.tb)
        linha_log = obs.FormatadorJson().format(logging.LogRecord(
            "constela", logging.ERROR, __file__, 1, "erro_nao_tratado", None, info))
        com_hint = obs.higienizar_evento_sentry(
            {"exception": {"values": [{"type": "IntegrityError", "value": str(erro.value)}]}},
            {"exc_info": info})
        sem_hint = obs.higienizar_evento_sentry(
            {"exception": {"values": [{"type": "IntegrityError", "value": str(erro.value)}]}})
        for parte in PARAGRAFO_2.split() + RESPONSAVEL.split():
            assert parte not in linha_log, f"no log: {parte}"
            assert parte not in str(com_hint), f"no Sentry (com hint): {parte}"
            assert parte not in str(sem_hint), f"no Sentry (sem hint): {parte}"
    finally:
        with engine_postgres.begin() as c:
            c.execute(text("DROP TABLE IF EXISTS _detalhe_teste2"))


# --- EXCLUDE, message e muitas ocorrências --------------------------------------

def test_exclude_redige_os_dois_valores_pelo_caminho_exato():
    detalhe = ("Key (nome)=(" + NOME_FICTICIO + ") conflicts with existing key (nome)=(" +
               PARAGRAFO_2 + ").")
    redigido = obs.redigir_detalhe_do_banco("DETAIL:  " + detalhe, _ErroDoBanco("x", detalhe))
    assert redigido == ("DETAIL:  Key (nome)=(<redigido>) conflicts with existing key "
                        "(nome)=(<redigido>).")


def test_message_do_log_falha_fechado_e_o_traceback_usa_o_detalhe_exato():
    """A mensagem não tem dono (pode trazer o texto de qualquer erro): falha fechado.
    No traceback, a exceção tem o DETAIL dela e fica com a forma exata."""
    detalhe = "Failing row contains (1, " + PARAGRAFO_1 + ").\n\n" + PARAGRAFO_2 + ")."
    erro = _ErroDoBanco("null value\nDETAIL:  " + detalhe, detalhe)
    registro = logging.LogRecord("constela", logging.ERROR, __file__, 1,
                                 "falha ao gravar: %s", (erro,), (type(erro), erro, None))
    evento = json.loads(obs.FormatadorJson().format(registro))
    for campo in ("message", "msg", "excecao"):
        assert PARAGRAFO_2.split()[0] not in evento[campo], campo
    assert evento["message"] == "falha ao gravar: null value\nDETAIL:  <redigido>"
    assert evento["excecao"].endswith(
        "_ErroDoBanco: null value\nDETAIL:  Failing row contains (<redigido>).")


_MUITOS = {
    "key-200mil": lambda: "Key (" * 200_000,
    "key-sep-40mil": lambda: ("Key (a)=(" + "x" * 10 + "\n[SQL: ") * 40_000,
    "linha-fim-40mil": lambda: ("Failing row contains (" + "y" * 10 + "\n[SQL: ") * 40_000,
    "exclude-20mil": lambda: ("Key (a)=(v) conflicts with existing key (a)=(w" + "\n[SQL: ") * 20_000,
}


@pytest.mark.parametrize("caso", sorted(_MUITOS))
def test_custo_linear_com_muitas_ocorrencias(caso):
    import time
    texto = _MUITOS[caso]()
    comeco = time.perf_counter()
    obs.redigir_detalhe_do_banco(texto)
    assert time.perf_counter() - comeco < TETO_S


@pytest.mark.postgres
def test_erro_real_de_exclude(engine_postgres):
    with engine_postgres.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS _detalhe_exclude"))
        c.execute(text("CREATE TABLE _detalhe_exclude (id serial primary key, nome text, "
                       "EXCLUDE USING btree (nome WITH =))"))
        c.execute(text("INSERT INTO _detalhe_exclude (nome) VALUES (:n)"), {"n": NOME_FICTICIO})
    try:
        with pytest.raises(IntegrityError) as erro:
            with engine_postgres.begin() as c:
                c.execute(text("INSERT INTO _detalhe_exclude (nome) VALUES (:n)"),
                          {"n": NOME_FICTICIO})
        info = (type(erro.value), erro.value, erro.tb)
        linha_log = obs.FormatadorJson().format(logging.LogRecord(
            "constela", logging.ERROR, __file__, 1, "erro_nao_tratado", None, info))
        com_hint = obs.higienizar_evento_sentry(
            {"exception": {"values": [{"type": "IntegrityError", "value": str(erro.value)}]}},
            {"exc_info": info})
        sem_hint = obs.higienizar_evento_sentry(
            {"exception": {"values": [{"type": "IntegrityError", "value": str(erro.value)}]}})
        for parte in NOME_FICTICIO.split():
            assert parte not in linha_log, f"no log: {parte}"
            assert parte not in str(com_hint), f"no Sentry (com hint): {parte}"
            assert parte not in str(sem_hint), f"no Sentry (sem hint): {parte}"
        assert "conflicts with existing key" in linha_log          # o diagnóstico fica
    finally:
        with engine_postgres.begin() as c:
            c.execute(text("DROP TABLE IF EXISTS _detalhe_exclude"))


@pytest.mark.postgres
@pytest.mark.parametrize("caso", ["not_null_na_funcao", "unique_na_funcao"])
def test_detalhe_seguido_de_context_mantem_o_diagnostico(engine_postgres, caso):
    """Erro de dentro de função/trigger/cascata: o PostgreSQL põe "CONTEXT:" depois do
    DETAIL. O valor sai; o tipo da exceção, o [SQL: …] e a cadeia ficam."""
    with engine_postgres.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS _detalhe_ctx"))
        c.execute(text("CREATE TABLE _detalhe_ctx (id serial primary key, nome text NOT NULL "
                       "UNIQUE, obs text)"))
        c.execute(text(
            "CREATE OR REPLACE FUNCTION _detalhe_ctx_ins(n text, o text) RETURNS void "
            "LANGUAGE plpgsql AS $$ BEGIN INSERT INTO _detalhe_ctx (nome, obs) VALUES (n, o); "
            "END $$"))
        c.execute(text("INSERT INTO _detalhe_ctx (nome) VALUES (:n)"), {"n": NOME_FICTICIO})
    nome = None if caso == "not_null_na_funcao" else NOME_FICTICIO
    try:
        with pytest.raises(IntegrityError) as erro:
            with engine_postgres.begin() as c:
                c.execute(text("SELECT _detalhe_ctx_ins(:n, :o)"),
                          {"n": nome, "o": PARAGRAFO_2})
        assert "CONTEXT:" in str(erro.value)                         # controle
        info = (type(erro.value), erro.value, erro.tb)
        evento = json.loads(obs.FormatadorJson().format(logging.LogRecord(
            "constela", logging.ERROR, __file__, 1, "erro_nao_tratado", None, info)))
        sentry = obs.higienizar_evento_sentry(
            {"exception": {"values": [{"type": "IntegrityError", "value": str(erro.value)}]}},
            {"exc_info": info})
        for parte in NOME_FICTICIO.split() + PARAGRAFO_2.split():
            assert parte not in evento["excecao"], parte
            assert parte not in str(sentry), parte
        for diagnostico in ("sqlalchemy.exc.IntegrityError", "[SQL: SELECT _detalhe_ctx_ins",
                            "The above exception was the direct cause"):
            assert diagnostico in evento["excecao"], diagnostico
        if caso == "unique_na_funcao":
            assert "already exists." in str(sentry)
    finally:
        with engine_postgres.begin() as c:
            c.execute(text("DROP FUNCTION IF EXISTS _detalhe_ctx_ins(text, text)"))
            c.execute(text("DROP TABLE IF EXISTS _detalhe_ctx"))


# --- marcador forjado no valor, DETAILs que se cruzam, Sentry e PendingRollbackError

# Todo marcador que vem depois de um DETAIL no texto de um erro/traceback, COMPLETO.
MARCADORES = ("\n[SQL: ", "\nHINT:  ", "\nCONTEXT:  ", "\n(Background on this error at: ",
              "\n\nThe above exception was the direct cause of the following exception:",
              "\n\nDuring handling of the above exception, another exception occurred:")
SQL = "\n[SQL: INSERT INTO alunos (nome) VALUES (%(nome)s)]"


def _detalhe_forjado(forma, marcador, fim_forjado):
    """DETAIL cujo valor tem um marcador — e, se ``fim_forjado``, o fim estrutural
    (")." ou o rabo de uma chave) logo antes dele, imitando o fim do DETAIL."""
    if forma == "linha":
        return ("Failing row contains (1, Obs (x" + (")." if fim_forjado else "") + marcador +
                PARAGRAFO_2 + ", " + RESPONSAVEL + ")."), "Failing row contains (<redigido>)."
    if forma == "chave":
        return ("Key (escola_id, nome)=(3, Obs" + (") already exists." if fim_forjado else "") +
                marcador + PARAGRAFO_2 + ") already exists."), (
                    "Key (escola_id, nome)=(<redigido>) already exists.")
    return ("Key (nome)=(Obs" + (")." if fim_forjado else "") + marcador + PARAGRAFO_2 +
            ") conflicts with existing key (nome)=(" + RESPONSAVEL + ")."), (
                "Key (nome)=(<redigido>) conflicts with existing key (nome)=(<redigido>).")


@pytest.mark.parametrize("marcador", MARCADORES)
@pytest.mark.parametrize("forma", ["linha", "chave", "exclude"])
@pytest.mark.parametrize("fim_forjado", [False, True])
def test_marcador_dentro_do_valor_nao_encerra_a_redacao(marcador, forma, fim_forjado):
    """O valor (observações, nome) pode conter QUALQUER marcador, até o separador de
    exceções do traceback, com ou sem o fim estrutural forjado antes dele. Sem a
    exceção, nada depois do DETAIL sai; com ela, sai a forma exata e o resto fica."""
    detalhe, forma_exata = _detalhe_forjado(forma, marcador, fim_forjado)
    texto = "erro\nDETAIL:  " + detalhe + SQL
    assert obs.redigir_detalhe_do_banco(texto) == "erro\nDETAIL:  <redigido>"
    assert obs.redigir_detalhe_do_banco(texto, _ErroDoBanco(texto, detalhe)) == (
        "erro\nDETAIL:  " + forma_exata + SQL)


def test_separador_partido_entre_duas_colunas_da_linha():
    """A linha junta as colunas com ", " — e o separador "During handling of the above
    exception, another exception occurred:" tem ", ": duas colunas vizinhas o montam."""
    detalhe = ("Failing row contains (1, null, Obs\n\nDuring handling of the above exception, "
               "another exception occurred:\n" + PARAGRAFO_2 + ", " + RESPONSAVEL + ").")
    texto = "erro\nDETAIL:  " + detalhe + SQL
    assert obs.redigir_detalhe_do_banco(texto) == "erro\nDETAIL:  <redigido>"
    assert obs.redigir_detalhe_do_banco(texto, _ErroDoBanco(texto, detalhe)) == (
        "erro\nDETAIL:  Failing row contains (<redigido>)." + SQL)


def _erro_do_sqlalchemy(texto, detalhe_proprio, detalhe_do_orig):
    """Um erro do SQLAlchemy com DOIS DETAILs próprios (o dele e o do ``orig``)."""
    from sqlalchemy.exc import IntegrityError as ErroDeIntegridade
    erro = ErroDeIntegridade("INSERT", None, _ErroDoBanco(texto, detalhe_do_orig))
    erro.diag = _Diag(detalhe_proprio)
    return erro


def test_detalhes_exatos_que_se_cruzam_cortam_o_texto():
    """Dois DETAILs do mesmo dono que se cruzam no texto (o fim de um é o começo do
    outro): não há fronteira confiável, e o texto é cortado no primeiro."""
    primeiro = "Key (id)=(1) already exists.Key (nome)=(Obs) already exists."
    segundo = "Key (nome)=(Obs) already exists." + PARAGRAFO_2 + ") already exists."
    texto = "erro\nDETAIL:  Key (id)=(1) already exists." + segundo + SQL
    erro = _erro_do_sqlalchemy(texto, primeiro, segundo)
    assert obs.redigir_detalhe_do_banco(texto, erro) == "erro\nDETAIL:  <redigido>"
    # Contido no outro: some com ele, e o resto do texto fica.
    texto = "erro\nDETAIL:  " + segundo + SQL
    erro = _erro_do_sqlalchemy(texto, segundo, "Key (nome)=(Obs) already exists.")
    assert obs.redigir_detalhe_do_banco(texto, erro) == (
        "erro\nDETAIL:  Key (nome)=(<redigido>) already exists." + SQL)


def test_sentry_redige_params_breadcrumbs_e_extra():
    """O DETAIL chega ao Sentry também pelos ``params`` do log (a exceção vira repr,
    com a quebra escapada), pelos breadcrumbs (linhas de log anteriores ao erro) e
    pelo ``extra``. Todo texto do evento passa pela redação."""
    repr_do_erro = ("UniqueViolation('duplicate key value violates unique constraint \"uq\"\\n"
                    "DETAIL:  Key (nome)=(" + NOME_FICTICIO + ") already exists.')")
    evento = obs.higienizar_evento_sentry({
        "logentry": {"message": "falha ao gravar: %s", "params": [repr_do_erro]},
        "breadcrumbs": {"values": [
            {"message": "aviso: Failing row contains (1, " + NOME_FICTICIO + ")."}]},
        "extra": {"erro": ("Key (nome)=(" + NOME_FICTICIO + ") already exists.",)},
        "request": {"url": "https://x/api/publico/segredo?busca=a", "query_string": "busca=a"},
    })
    for parte in NOME_FICTICIO.split():
        assert parte not in str(evento), parte
    assert evento["logentry"]["params"] == [
        "UniqueViolation('duplicate key value violates unique constraint \"uq\"\\n"
        "DETAIL:  <redigido>"]
    assert evento["request"]["query_string"] == "<redigido>"
    assert "segredo" not in evento["request"]["url"]


def test_log_json_redige_o_extra_sem_mexer_no_objeto_do_app():
    falhas = [{"escola_id": 1, "erro": "x\nDETAIL:  Failing row contains (1, " +
               NOME_FICTICIO + ")."}]
    registro = logging.LogRecord("constela", logging.WARNING, __file__, 1, "recalculo",
                                 None, None)
    registro.falhas = falhas
    registro.objeto = _ErroDoBanco("y\nDETAIL:  Key (nome)=(" + NOME_FICTICIO +
                                   ") already exists.", "z")
    linha = obs.FormatadorJson().format(registro)
    for parte in NOME_FICTICIO.split():
        assert parte not in linha, parte
    evento = json.loads(linha)
    assert evento["falhas"] == [{"escola_id": 1, "erro": "x\nDETAIL:  <redigido>"}]
    assert NOME_FICTICIO in falhas[0]["erro"]          # o objeto do app fica intacto


def test_sentry_sem_o_detalhe_exato_falha_fechado():
    """O SDK corta valores longos ANTES do before_send: o DETAIL exato deixa de estar
    no texto (e o fim estrutural some com o corte). Aí tudo a partir do DETAIL sai."""
    detalhe = "Failing row contains (1, " + "x" * 1100 + ", " + PARAGRAFO_2 + ")."
    cortado = ("null value in column \"nome\"\nDETAIL:  " + detalhe)[:1021] + "..."
    erro = _ErroDoBanco("null value\nDETAIL:  " + detalhe, detalhe)
    evento = obs.higienizar_evento_sentry(
        {"exception": {"values": [{"type": "IntegrityError", "value": cortado}]}},
        {"exc_info": (type(erro), erro, None)})
    valor = evento["exception"]["values"][0]["value"]
    assert valor == "null value in column \"nome\"\nDETAIL:  <redigido>"


@pytest.mark.postgres
def test_pending_rollback_error_real_sai_sem_o_valor(engine_postgres):
    """PendingRollbackError copia o DETAIL inteiro no próprio texto e não traz a
    exceção original na cadeia: o texto é cortado no DETAIL (falha fechada)."""
    from sqlalchemy import Column, Integer, Text
    from sqlalchemy.exc import PendingRollbackError
    from sqlalchemy.orm import Session as Sessao
    from sqlalchemy.orm import declarative_base

    Base = declarative_base()

    class Linha(Base):
        __tablename__ = "_detalhe_pend"
        id = Column(Integer, primary_key=True)
        nome = Column(Text)
        observacoes = Column(Text)
        ficha = Column(Text)

    with engine_postgres.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS _detalhe_pend"))
        c.execute(text("CREATE TABLE _detalhe_pend (id serial primary key, nome text NOT NULL, "
                       "observacoes text, ficha text)"))
    valor_obs = "Obs (x)." + "\n[SQL: " + PARAGRAFO_2
    try:
        sessao = Sessao(engine_postgres)
        sessao.add(Linha(nome=None, observacoes=valor_obs, ficha=RESPONSAVEL))
        with pytest.raises(IntegrityError):
            sessao.flush()                       # o erro é engolido por quem chamou...
        with pytest.raises(PendingRollbackError) as pendente:
            sessao.execute(text("SELECT 1"))     # ...e reaparece aqui, com o DETAIL no texto
        sessao.close()
        erro = pendente.value
        info = (type(erro), erro, erro.__traceback__)
        linha_log = obs.FormatadorJson().format(logging.LogRecord(
            "constela", logging.ERROR, __file__, 1, "erro_nao_tratado", None, info))
        sentry = obs.higienizar_evento_sentry(
            {"exception": {"values": [{"type": "PendingRollbackError", "value": str(erro)}]}},
            {"exc_info": info})
        for parte in PARAGRAFO_2.split() + RESPONSAVEL.split():
            assert parte not in linha_log, f"no log: {parte}"
            assert parte not in str(sentry), f"no Sentry: {parte}"
        for diagnostico in ("PendingRollbackError", "violates not-null constraint",
                            "_detalhe_pend"):
            assert diagnostico in linha_log, diagnostico                 # o que vem antes fica
    finally:
        with engine_postgres.begin() as c:
            c.execute(text("DROP TABLE IF EXISTS _detalhe_pend"))


def test_custo_linear_com_muitas_ocorrencias_do_detalhe_exato():
    import time
    detalhe = "Key (a)=(v) already exists."
    texto = ("DETAIL:  " + detalhe + "\n[SQL: x]\n") * 40_000 + "Key (" * 100_000
    erro = _ErroDoBanco(texto, detalhe)
    comeco = time.perf_counter()
    redigido = obs.redigir_detalhe_do_banco(texto, erro)
    assert time.perf_counter() - comeco < TETO_S
    assert redigido.count("Key (a)=(<redigido>) already exists.") == 40_000


# --- PostgreSQL real com o separador de cadeia DENTRO do valor ----------------------

_TABELAS_CADEIA = {
    "unique_composto": "escola_id int, nome text, obs text, ficha text, UNIQUE (escola_id, nome)",
    "exclude": "escola_id int, nome text, obs text, ficha text, EXCLUDE USING btree (nome WITH =)",
    "not_null_partido": "escola_id int NOT NULL, nome text, obs text, ficha text",
}


@pytest.mark.postgres
@pytest.mark.parametrize("caso", sorted(_TABELAS_CADEIA))
def test_erro_real_com_separador_de_cadeia_no_valor(engine_postgres, caso):
    """O separador de exceções do traceback escrito no valor (observações, nome) não
    encerra a redação. No log com a exceção sai a forma exata, e o resto do traceback
    fica; sem a exceção (mensagem, Sentry sem hint), o texto é cortado no DETAIL. No
    NOT NULL, duas colunas vizinhas montam o separador que tem ", "."""
    with engine_postgres.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS _detalhe_cadeia"))
        c.execute(text("CREATE TABLE _detalhe_cadeia (id serial primary key, " +
                       _TABELAS_CADEIA[caso] + ")"))
    # Por variável (não literal na chamada): o traceback mostra a linha do código.
    nome = "Obs" + MARCADORES[4] + "\n" + PARAGRAFO_2
    obs_valor = "Obs\n\nDuring handling of the above exception"
    ficha_valor = "another exception occurred:\n" + RESPONSAVEL
    parametros = {"e": None if caso == "not_null_partido" else 1,
                  "n": "x" if caso == "not_null_partido" else nome,
                  "o": obs_valor, "f": ficha_valor}
    inserir = text("INSERT INTO _detalhe_cadeia (escola_id, nome, obs, ficha) "
                   "VALUES (:e, :n, :o, :f)")
    try:
        if caso != "not_null_partido":
            with engine_postgres.begin() as c:
                c.execute(inserir, parametros)
        with pytest.raises(IntegrityError) as erro:
            with engine_postgres.begin() as c:
                c.execute(inserir, parametros)
        bruto = str(erro.value)
        assert RESPONSAVEL.split()[0] in bruto or PARAGRAFO_2.split()[0] in bruto  # controle
        info = (type(erro.value), erro.value, erro.tb)
        evento = json.loads(obs.FormatadorJson().format(logging.LogRecord(
            "constela", logging.ERROR, __file__, 1, "erro_nao_tratado", None, info)))
        sem_excecao = json.loads(obs.FormatadorJson().format(logging.LogRecord(
            "constela", logging.ERROR, __file__, 1, "falha: %s", (bruto,), None)))
        com_hint = obs.higienizar_evento_sentry(
            {"exception": {"values": [{"type": "IntegrityError", "value": bruto}]}},
            {"exc_info": info})
        sem_hint = obs.higienizar_evento_sentry(
            {"exception": {"values": [{"type": "IntegrityError", "value": bruto}]}})
        for parte in PARAGRAFO_2.split() + RESPONSAVEL.split():
            assert parte not in json.dumps(evento), f"no log: {parte}"
            assert parte not in json.dumps(sem_excecao), f"no log sem exceção: {parte}"
            assert parte not in str(com_hint), f"no Sentry (com hint): {parte}"
            assert parte not in str(sem_hint), f"no Sentry (sem hint): {parte}"
        for diagnostico in ("sqlalchemy.exc.IntegrityError", "[SQL: INSERT INTO _detalhe_cadeia",
                            "The above exception was the direct cause"):
            assert diagnostico in evento["excecao"], diagnostico      # com a exceção, fica
        assert sem_excecao["message"].endswith("DETAIL:  <redigido>")
    finally:
        with engine_postgres.begin() as c:
            c.execute(text("DROP TABLE IF EXISTS _detalhe_cadeia"))


# --- o DETAIL exato só vale no texto do erro dono; robustez do log ------------------

D_CURTO = "Key (nome)=(Obs) already exists."
D_LONGO = D_CURTO + "\n" + PARAGRAFO_2 + ") already exists."


def test_detalhe_de_outro_erro_com_o_mesmo_comeco_nao_passa_por_exato():
    """O DETAIL exato do erro do log casava com o COMEÇO do DETAIL de outro erro (valor
    forjado com o rabo do PostgreSQL), e o resto desse outro saía como estrutura."""
    curto = _ErroDoBanco("dup\nDETAIL:  " + D_CURTO, D_CURTO)
    longo = _ErroDoBanco("dup\nDETAIL:  " + D_LONGO, D_LONGO)
    # (a) A mensagem traz o texto de um erro guardado antes; o exc_info é outro.
    evento = json.loads(obs.FormatadorJson().format(logging.LogRecord(
        "constela", logging.ERROR, __file__, 1, "falha anterior: %s", (longo,),
        (type(curto), curto, None))))
    # (b) Um erro sem diag que copia o texto do outro (como o PendingRollbackError),
    # levantado ao tratar o curto.
    try:
        try:
            raise curto
        except _ErroDoBanco:
            raise RuntimeError("Original exception was: dup\nDETAIL:  " + D_LONGO)
    except RuntimeError as copia:
        info = (RuntimeError, copia, copia.__traceback__)
    pendente = json.loads(obs.FormatadorJson().format(logging.LogRecord(
        "constela", logging.ERROR, __file__, 1, "erro_nao_tratado", None, info)))
    for parte in PARAGRAFO_2.split():
        assert parte not in json.dumps(evento), parte
        assert parte not in json.dumps(pendente), parte
    assert evento["message"] == "falha anterior: dup\nDETAIL:  <redigido>"
    assert "_ErroDoBanco: dup\nDETAIL:  Key (nome)=(<redigido>) already exists." in (
        pendente["excecao"])                                       # o curto: forma exata
    assert "During handling of the above exception" in pendente["excecao"]
    assert pendente["excecao"].endswith("Original exception was: dup\nDETAIL:  <redigido>")


def test_sentry_valor_cortado_nao_usa_o_detalhe_exato_de_outro_erro():
    """Na cadeia, o DETAIL de um erro é o começo do DETAIL de outro, cujo valor o SDK
    cortou: o valor cortado não é o texto inteiro de nenhum erro e falha fechado."""
    longo_d = D_CURTO + "\n" + PARAGRAFO_2 + " " + "x" * 1100 + ") already exists."
    longo = _ErroDoBanco("dup\nDETAIL:  " + longo_d, longo_d)
    curto = _ErroDoBanco("dup\nDETAIL:  " + D_CURTO, D_CURTO)
    curto.__context__ = longo
    evento = obs.higienizar_evento_sentry(
        {"exception": {"values": [{"type": "_ErroDoBanco", "value": str(longo)[:1021] + "..."},
                                  {"type": "_ErroDoBanco", "value": str(curto)}]}},
        {"exc_info": (type(curto), curto, None)})
    valores = evento["exception"]["values"]
    assert valores[0]["value"] == "dup\nDETAIL:  <redigido>"
    assert valores[1]["value"] == "dup\nDETAIL:  Key (nome)=(<redigido>) already exists."
    for parte in PARAGRAFO_2.split():
        assert parte not in str(evento), parte


def test_chave_de_indice_de_expressao_longa_sem_a_excecao():
    """Entre "Key (" e ")=(" o PostgreSQL escreve a expressão do índice, sem tamanho
    máximo: a distância não pode limitar o reconhecimento do DETAIL."""
    expressao = "lower(" * 1000 + "nome" + ")" * 1000
    texto = ("erro\nDETAIL:  Key (" + expressao + ")=(" + PARAGRAFO_2 + ") already exists." +
             SQL)
    assert obs.redigir_detalhe_do_banco(texto) == "erro\nDETAIL:  <redigido>"


def test_traceback_redigido_tem_o_formato_do_python():
    import traceback
    try:
        try:
            1 / 0
        except ZeroDivisionError as causa:
            raise ValueError("valor") from causa
    except ValueError as erro:
        info = (ValueError, erro, erro.__traceback__)
    assert obs.traceback_redigido(info[1]) == "".join(
        traceback.format_exception(*info)).rstrip("\n")
    registro = logging.LogRecord("constela", logging.ERROR, __file__, 1, "x", None, info)
    assert json.loads(obs.FormatadorJson().format(registro))["excecao"] == (
        logging.Formatter().formatException(info))


def test_log_json_nunca_levanta_e_trata_ciclo_e_chave(capsys):
    """O formatador nunca levanta: o handleError do logging imprimiria no stderr a
    mensagem e os argumentos CRUS. Ciclo no extra vira marcador; chave também é texto."""
    import io
    ciclo = {}
    ciclo["eu"] = ciclo
    registro = logging.LogRecord("constela", logging.INFO, __file__, 1, "ok", None, None)
    registro.ciclo = ciclo
    registro.falhas = {"Key (nome)=(" + NOME_FICTICIO + ") already exists.": 1}
    evento = json.loads(obs.FormatadorJson().format(registro))
    assert evento["ciclo"] == {"eu": "<estrutura omitida>"}
    assert evento["falhas"] == {"<redigido>": 1}
    quebrado = logging.LogRecord("constela", logging.ERROR, __file__, 1, "%d",
                                 ("Failing row contains (1, " + NOME_FICTICIO + ").",), None)
    saida = io.StringIO()
    handler = logging.StreamHandler(saida)
    handler.setFormatter(obs.FormatadorJson())
    handler.emit(quebrado)
    impresso = saida.getvalue() + capsys.readouterr().err
    for parte in NOME_FICTICIO.split():
        assert parte not in impresso, parte
    assert json.loads(saida.getvalue())["erro_de_formatacao"] == "TypeError"


def test_formatador_de_texto_tambem_redige():
    """LOG_JSON=false (desenvolvimento): o mesmo cuidado no formato legível."""
    try:
        raise _ErroDoBanco("dup\nDETAIL:  " + D_LONGO, D_LONGO)
    except _ErroDoBanco as erro:
        info = (type(erro), erro, erro.__traceback__)
    formatador = obs.FormatadorTexto("%(levelname)s %(name)s: %(message)s")
    texto = formatador.format(logging.LogRecord(
        "constela", logging.ERROR, __file__, 1, "falha: %s", (info[1],), info))
    for parte in PARAGRAFO_2.split():
        assert parte not in texto, parte
    assert texto.startswith("ERROR constela: falha: dup\nDETAIL:  <redigido>\nTraceback")
    assert texto.endswith("DETAIL:  Key (nome)=(<redigido>) already exists.")


@pytest.mark.postgres
def test_erro_real_pending_rollback_dentro_do_tratamento_de_outro_erro(engine_postgres):
    """PendingRollbackError (sem diag, copia o DETAIL do flush que falhou) levantado ao
    tratar OUTRO IntegrityError cujo DETAIL é o começo do primeiro."""
    from sqlalchemy import Column, Integer, Text
    from sqlalchemy.exc import PendingRollbackError
    from sqlalchemy.orm import Session as Sessao
    from sqlalchemy.orm import declarative_base

    Base = declarative_base()

    class Linha(Base):
        __tablename__ = "_detalhe_pfx"
        id = Column(Integer, primary_key=True)
        nome = Column(Text)

    curto_valor, longo_valor = "Obs", "Obs) already exists.\n" + PARAGRAFO_2
    with engine_postgres.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS _detalhe_pfx"))
        c.execute(text("CREATE TABLE _detalhe_pfx (id serial primary key, nome text UNIQUE)"))
        c.execute(text("INSERT INTO _detalhe_pfx (nome) VALUES (:a), (:b)"),
                  {"a": curto_valor, "b": longo_valor})
    try:
        sessao = Sessao(engine_postgres)
        sessao.add(Linha(nome=longo_valor))
        with pytest.raises(IntegrityError):
            sessao.flush()                       # engolido por quem chamou, sem rollback
        try:
            with engine_postgres.begin() as c:
                c.execute(text("INSERT INTO _detalhe_pfx (nome) VALUES (:n)"),
                          {"n": curto_valor})
        except IntegrityError:
            with pytest.raises(PendingRollbackError) as pendente:
                sessao.execute(text("SELECT 1"))
        sessao.close()
        erro = pendente.value
        assert isinstance(erro.__context__, IntegrityError)              # controle
        info = (type(erro), erro, erro.__traceback__)
        evento = json.loads(obs.FormatadorJson().format(logging.LogRecord(
            "constela", logging.ERROR, __file__, 1, "erro_nao_tratado", None, info)))
        sentry = obs.higienizar_evento_sentry(
            {"exception": {"values": [{"type": "PendingRollbackError", "value": str(erro)},
                                      {"type": "IntegrityError",
                                       "value": str(erro.__context__)}]}},
            {"exc_info": info})
        for parte in PARAGRAFO_2.split():
            assert parte not in evento["excecao"], f"no log: {parte}"
            assert parte not in str(sentry), f"no Sentry: {parte}"
        assert "DETAIL:  Key (nome)=(<redigido>) already exists.\n[SQL: INSERT INTO _detalhe_pfx" in (
            evento["excecao"])                                   # o do contexto: exato
        assert "During handling of the above exception" in evento["excecao"]
    finally:
        with engine_postgres.begin() as c:
            c.execute(text("DROP TABLE IF EXISTS _detalhe_pfx"))


@pytest.mark.postgres
def test_erro_real_de_indice_de_expressao_longa(engine_postgres):
    """A expressão do índice (mais de 4096 caracteres) entre "Key (" e ")=(" não
    impede o corte sem a exceção; com ela, sai a forma exata."""
    expressao = "lower(" * 800 + "nome" + ")" * 800
    valor = PARAGRAFO_2
    with engine_postgres.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS _detalhe_expr"))
        c.execute(text("CREATE TABLE _detalhe_expr (id serial primary key, nome text)"))
        c.execute(text("CREATE UNIQUE INDEX _detalhe_expr_ix ON _detalhe_expr ((" +
                       expressao + "))"))
        c.execute(text("INSERT INTO _detalhe_expr (nome) VALUES (:n)"), {"n": valor})
    try:
        with pytest.raises(IntegrityError) as erro:
            with engine_postgres.begin() as c:
                c.execute(text("INSERT INTO _detalhe_expr (nome) VALUES (:n)"), {"n": valor})
        bruto = str(erro.value)
        assert bruto.index(")=(") - bruto.index("Key (") > 4096                # controle
        info = (type(erro.value), erro.value, erro.tb)
        com_excecao = json.loads(obs.FormatadorJson().format(logging.LogRecord(
            "constela", logging.ERROR, __file__, 1, "erro_nao_tratado", None, info)))
        sem_excecao = json.loads(obs.FormatadorJson().format(logging.LogRecord(
            "constela", logging.ERROR, __file__, 1, "falha: %s", (bruto,), None)))
        for parte in PARAGRAFO_2.lower().split():           # o índice guarda minúsculas
            assert parte not in json.dumps(com_excecao).lower(), parte
            assert parte not in json.dumps(sem_excecao).lower(), parte
        assert sem_excecao["message"].endswith("DETAIL:  <redigido>")
        assert "[SQL: INSERT INTO _detalhe_expr" in com_excecao["excecao"]
    finally:
        with engine_postgres.begin() as c:
            c.execute(text("DROP TABLE IF EXISTS _detalhe_expr"))


# --- CONTEXT e QUERY também levam valor; fidelidade e custo do traceback ------------

class _DiagCompleto:
    def __init__(self, detalhe=None, contexto=None, consulta=None):
        self.message_detail, self.context, self.internal_query = detalhe, contexto, consulta


def test_context_e_query_saem_inteiros_com_e_sem_o_dono():
    """CONTEXT com os parâmetros do portal (log_parameter_max_length_on_error ligado)
    ou com o comando de um EXECUTE, e QUERY de uma função: valores fora do DETAIL."""
    contexto = "unnamed portal with parameters: $1 = '" + PARAGRAFO_2 + "'"
    consulta = "INSERT INTO t VALUES ('" + RESPONSAVEL + "')"
    texto = ("value too long for type character varying(5)\nCONTEXT:  " + contexto +
             "\nQUERY:  " + consulta + SQL)
    erro = _ErroDoBanco(texto, None)
    erro.diag = _DiagCompleto(contexto=contexto, consulta=consulta)
    assert obs.redigir_detalhe_do_banco(texto, erro) == (
        "value too long for type character varying(5)\nCONTEXT:  <redigido>\n"
        "QUERY:  <redigido>" + SQL)
    assert obs.redigir_detalhe_do_banco(texto) == (
        "value too long for type character varying(5)\nCONTEXT:  <redigido>")
    # DETAIL de formato desconhecido (JSON inválido) também sai inteiro.
    detalhe = 'Token "' + PARAGRAFO_2 + '" is invalid.'
    texto = "invalid input syntax for type json\nDETAIL:  " + detalhe + "\nCONTEXT:  JSON data"
    erro = _ErroDoBanco(texto, detalhe)
    assert obs.redigir_detalhe_do_banco(texto) == (
        "invalid input syntax for type json\nDETAIL:  <redigido>")
    assert PARAGRAFO_2.split()[0] not in obs.redigir_detalhe_do_banco(texto, erro)


def test_traceback_redigido_mantem_sugestao_e_custo_linear_na_cadeia_longa():
    import time
    import traceback
    try:
        eval("variavel_que_nao_existe_qz")
    except NameError as erro:
        info = (NameError, erro, erro.__traceback__)
    assert obs.traceback_redigido(info[1]) == "".join(
        traceback.format_exception(*info)).rstrip("\n")
    # Cadeia longa: o mesmo trabalho do format_exception (um TracebackException só).
    atual = ValueError("0")
    for i in range(1, 3000):
        proximo = ValueError(str(i))
        proximo.__context__ = atual
        atual = proximo
    comeco = time.perf_counter()
    traceback.format_exception(atual)
    referencia = time.perf_counter() - comeco
    comeco = time.perf_counter()
    texto = obs.traceback_redigido(atual)
    assert time.perf_counter() - comeco < max(TETO_S / 2, 5 * referencia)
    assert texto.startswith("[exceções mais antigas omitidas") and texto.count("ValueError:") == 64


_GUC_LIGADO = {"options": "-c log_parameter_max_length_on_error=64"}


@pytest.mark.postgres
@pytest.mark.parametrize("caso", ["unique", "not_null", "varchar", "json", "execute_format"])
def test_erro_real_com_valores_no_context(engine_postgres, caso):
    """Com log_parameter_max_length_on_error ligado (o padrão é 0; em produção está 0),
    TODO erro de comando com parâmetros leva os valores no CONTEXT; um JSON inválido
    e um EXECUTE com %L levam valores no DETAIL/CONTEXT mesmo no padrão."""
    url = engine_postgres.url
    engine = create_engine(url, hide_parameters=True, connect_args=_GUC_LIGADO)
    with engine.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS _detalhe_ctx2"))
        c.execute(text("CREATE TABLE _detalhe_ctx2 (id serial primary key, nome text UNIQUE, "
                       "escola_id int NOT NULL DEFAULT 1, curto varchar(5), j jsonb)"))
        c.execute(text("CREATE OR REPLACE FUNCTION _detalhe_ctx2_ins(n text) RETURNS void "
                       "LANGUAGE plpgsql AS $$ BEGIN EXECUTE format('INSERT INTO "
                       "_detalhe_ctx2 (nome) VALUES (%L)', n); END $$"))
        c.execute(text("INSERT INTO _detalhe_ctx2 (nome) VALUES (:n)"), {"n": PARAGRAFO_2})
    comandos = {
        "unique": ("INSERT INTO _detalhe_ctx2 (nome) VALUES (:n)", {"n": PARAGRAFO_2}),
        "not_null": ("INSERT INTO _detalhe_ctx2 (nome, escola_id) VALUES (:n, :e)",
                     {"n": PARAGRAFO_2 + " 2", "e": None}),
        "varchar": ("INSERT INTO _detalhe_ctx2 (nome, curto) VALUES (:n, :c)",
                    {"n": "x", "c": PARAGRAFO_2}),
        "json": ("INSERT INTO _detalhe_ctx2 (nome, j) VALUES (:n, CAST(:j AS jsonb))",
                 {"n": "y", "j": "{" + PARAGRAFO_2}),
        "execute_format": ("SELECT _detalhe_ctx2_ins(:n)", {"n": PARAGRAFO_2}),
    }
    sql, parametros = comandos[caso]
    try:
        with pytest.raises(DBAPIError) as erro:
            with engine.begin() as c:
                c.execute(text(sql), parametros)
        bruto = str(erro.value)
        assert PARAGRAFO_2.split()[0] in bruto                          # controle
        info = (type(erro.value), erro.value, erro.tb)
        com_excecao = json.loads(obs.FormatadorJson().format(logging.LogRecord(
            "constela", logging.ERROR, __file__, 1, "erro_nao_tratado", None, info)))
        sem_excecao = json.loads(obs.FormatadorJson().format(logging.LogRecord(
            "constela", logging.ERROR, __file__, 1, "falha: %s", (bruto,), None)))
        texto = obs.FormatadorTexto("%(message)s").format(logging.LogRecord(
            "constela", logging.ERROR, __file__, 1, "falha: %s", (erro.value,), info))
        com_hint = obs.higienizar_evento_sentry(
            {"exception": {"values": [{"type": type(erro.value).__name__, "value": bruto}]}},
            {"exc_info": info})
        sem_hint = obs.higienizar_evento_sentry(
            {"exception": {"values": [{"type": type(erro.value).__name__, "value": bruto}]}})
        for parte in PARAGRAFO_2.split():
            assert parte not in json.dumps(com_excecao), f"log com exceção: {parte}"
            assert parte not in json.dumps(sem_excecao), f"log sem exceção: {parte}"
            assert parte not in texto, f"formato de texto: {parte}"
            assert parte not in str(com_hint), f"Sentry com hint: {parte}"
            assert parte not in str(sem_hint), f"Sentry sem hint: {parte}"
        assert "[SQL: " in com_excecao["excecao"]                    # o diagnóstico fica
    finally:
        with engine.begin() as c:
            c.execute(text("DROP FUNCTION IF EXISTS _detalhe_ctx2_ins(text)"))
            c.execute(text("DROP TABLE IF EXISTS _detalhe_ctx2"))
        engine.dispose()


# --- LINE da posição, causa raiz com contexto suprimido, grupos e escrita do log -----

def test_bloco_line_da_posicao_sai_com_e_sem_o_dono():
    """O libpq mostra a posição do erro com "LINE n: <janela da consulta>" e um "^"
    embaixo; a consulta de um EXECUTE format('%L') traz os literais."""
    janela = "INSERT INTO f (nome, idade) VALUES ('" + PARAGRAFO_2 + "', 'dez')"
    texto = ('invalid input syntax for type integer: "dez"\nLINE 1: ' + janela + "\n" +
             " " * 40 + "^\nQUERY:  " + janela + "\nCONTEXT:  PL/pgSQL function ins" + SQL)
    erro = _ErroDoBanco(texto, None)
    erro.diag = _DiagCompleto(consulta=janela, contexto="PL/pgSQL function ins")
    assert obs.redigir_detalhe_do_banco(texto, erro) == (
        'invalid input syntax for type integer: "dez"\nLINE 1: <redigido>\n'
        "QUERY:  <redigido>\nCONTEXT:  <redigido>" + SQL)
    assert obs.redigir_detalhe_do_banco(texto) == (
        'invalid input syntax for type integer: "dez"\nLINE 1: <redigido>')


def test_contexto_suprimido_nao_some_com_a_causa_raiz():
    """raise B from C dentro de except A, depois que o bloco que pegou C terminou: C e B
    têm o mesmo __context__ (A). Sem compact=True, A sumia do traceback."""
    import traceback

    class ErroDeNegocio(Exception):
        pass

    try:
        try:
            raise KeyError("raiz")
        except KeyError:
            try:
                raise ValueError("refazer")
            except ValueError as falha:
                ultima = falha
            raise ErroDeNegocio("falhou") from ultima
    except ErroDeNegocio as erro:
        info = (ErroDeNegocio, erro, erro.__traceback__)
    nosso = obs.traceback_redigido(info[1])
    assert nosso == "".join(traceback.format_exception(*info)).rstrip("\n")
    assert "KeyError: 'raiz'" in nosso


def test_grupo_respeita_largura_e_profundidade():
    largo = ExceptionGroup("largo", [ValueError(f"membro {i}") for i in range(20)])
    texto = obs.traceback_redigido(largo)
    assert texto.count("ValueError: membro") == 15
    assert "e mais 5 exceções" in texto
    fundo = ValueError("folha")
    for i in range(13):
        fundo = ExceptionGroup(f"nivel {i}", [fundo])
    texto = obs.traceback_redigido(fundo)
    assert "limite de 10 níveis de grupo" in texto and "folha" not in texto


def test_escrita_do_log_nao_imprime_os_argumentos_crus(capsys):
    """Um surrogate isolado (JSON com "\\ud800") faria a escrita no stdout falhar, e o
    handleError PADRÃO imprimiria a mensagem e os argumentos crus no stderr."""
    import io
    registro = logging.LogRecord("constela", logging.ERROR, __file__, 1, "falha: %s",
                                 ("nome \ud800 " + NOME_FICTICIO,), None)
    linha = obs.FormatadorJson().format(registro)
    linha.encode("utf-8")                                     # escrevível
    assert NOME_FICTICIO in json.loads(linha)["message"]      # sem DETAIL: nada a redigir

    class SaidaQuebrada(io.StringIO):
        def write(self, _texto):
            raise OSError("stdout fechado")

    handler = obs.SaidaDoLog(SaidaQuebrada())
    handler.setFormatter(obs.FormatadorJson())
    segredo = "x\nDETAIL:  Failing row contains (1, " + NOME_FICTICIO + ")."
    handler.emit(logging.LogRecord("constela", logging.ERROR, __file__, 1, "falha: %s",
                                   (segredo,), None))
    erro_impresso = capsys.readouterr().err
    assert erro_impresso == "<falha ao escrever o log de constela: OSError>\n"


def test_configurar_logging_usa_a_saida_segura():
    raiz = logging.getLogger()
    antes, nivel = list(raiz.handlers), raiz.level
    try:
        class Config:
            LOG_LEVEL, LOG_JSON = "INFO", True
        obs.configurar_logging(Config)
        assert any(isinstance(h, obs.SaidaDoLog) and isinstance(h.formatter, obs.FormatadorJson)
                   for h in raiz.handlers)
        Config.LOG_JSON = False
        obs.configurar_logging(Config)
        assert any(isinstance(h, obs.SaidaDoLog) and isinstance(h.formatter, obs.FormatadorTexto)
                   for h in raiz.handlers)
    finally:
        for h in list(raiz.handlers):
            raiz.removeHandler(h)
        for h in antes:
            raiz.addHandler(h)
        raiz.setLevel(nivel)


@pytest.mark.postgres
@pytest.mark.parametrize("caso", ["idade_invalida", "coluna_longa", "quebra_de_linha", "tab"])
def test_erro_real_com_linha_da_posicao_de_um_execute(engine_postgres, caso):
    """Erro de ANÁLISE do comando de um EXECUTE format('%L'): o libpq escreve a janela
    da consulta (com os literais) na linha "LINE n:" antes de QUERY e CONTEXT."""
    with engine_postgres.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS _detalhe_line"))
        c.execute(text("CREATE TABLE _detalhe_line (id serial primary key, nome text, idade int)"))
        c.execute(text(
            "CREATE OR REPLACE FUNCTION _detalhe_line_ins(n text, i text) RETURNS void "
            "LANGUAGE plpgsql AS $$ BEGIN EXECUTE format('INSERT INTO _detalhe_line "
            "(nome, idade) VALUES (%L, %L)', n, i); END $$"))
        c.execute(text(
            "CREATE OR REPLACE FUNCTION _detalhe_line_col(n text) RETURNS void "
            "LANGUAGE plpgsql AS $$ BEGIN EXECUTE format('SELECT %L, coluna_que_nao_existe "
            "FROM _detalhe_line', n); END $$"))
    comandos = {
        "idade_invalida": ("SELECT _detalhe_line_ins(:n, :i)", {"n": PARAGRAFO_2, "i": "dez"}),
        "coluna_longa": ("SELECT _detalhe_line_col(:n)", {"n": "x" * 80 + " " + PARAGRAFO_2}),
        "quebra_de_linha": ("SELECT _detalhe_line_col(:n)", {"n": "a\n" + PARAGRAFO_2}),
        "tab": ("SELECT _detalhe_line_col(:n)", {"n": "a\t" + PARAGRAFO_2}),
    }
    sql, parametros = comandos[caso]
    try:
        with pytest.raises(DBAPIError) as erro:
            with engine_postgres.begin() as c:
                c.execute(text(sql), parametros)
        bruto = str(erro.value)
        assert "LINE " in bruto and PARAGRAFO_2.split()[-1] in bruto.split("QUERY:")[0]  # controle
        info = (type(erro.value), erro.value, erro.tb)
        com_excecao = json.loads(obs.FormatadorJson().format(logging.LogRecord(
            "constela", logging.ERROR, __file__, 1, "erro_nao_tratado", None, info)))
        sem_excecao = json.loads(obs.FormatadorJson().format(logging.LogRecord(
            "constela", logging.ERROR, __file__, 1, "falha: %s", (bruto,), None)))
        texto = obs.FormatadorTexto("%(message)s").format(logging.LogRecord(
            "constela", logging.ERROR, __file__, 1, "falha: %s", (erro.value,), info))
        com_hint = obs.higienizar_evento_sentry(
            {"exception": {"values": [{"type": type(erro.value).__name__, "value": bruto}]}},
            {"exc_info": info})
        sem_hint = obs.higienizar_evento_sentry(
            {"exception": {"values": [{"type": type(erro.value).__name__, "value": bruto}]}})
        for parte in PARAGRAFO_2.split():
            assert parte not in json.dumps(com_excecao), f"log com exceção: {parte}"
            assert parte not in json.dumps(sem_excecao), f"log sem exceção: {parte}"
            assert parte not in texto, f"formato de texto: {parte}"
            assert parte not in str(com_hint), f"Sentry com hint: {parte}"
            assert parte not in str(sem_hint), f"Sentry sem hint: {parte}"
        assert "[SQL: SELECT _detalhe_line_" in com_excecao["excecao"]     # o diagnóstico fica
    finally:
        with engine_postgres.begin() as c:
            c.execute(text("DROP FUNCTION IF EXISTS _detalhe_line_ins(text, text)"))
            c.execute(text("DROP FUNCTION IF EXISTS _detalhe_line_col(text)"))
            c.execute(text("DROP TABLE IF EXISTS _detalhe_line"))


# --- exceção não tratada (thread e processo), "Sincronizar agora" e notas -----------

def test_excecao_nao_tratada_em_thread_e_no_processo_vai_para_o_log_redigida(capsys):
    """Sem gancho, o excepthook PADRÃO imprimia o traceback cru no stderr (o DETAIL do
    banco junto, no log do Railway) sem passar pelo formatador."""
    import sys
    import threading
    raiz = logging.getLogger()
    antes, nivel = list(raiz.handlers), raiz.level
    gancho_processo, gancho_thread = sys.excepthook, threading.excepthook
    detalhe = "Failing row contains (1, " + NOME_FICTICIO + ")."
    try:
        class Config:
            LOG_LEVEL, LOG_JSON = "INFO", True
        obs.configurar_logging(Config)

        def alvo():
            raise _ErroDoBanco("null value\nDETAIL:  " + detalhe, detalhe)

        thread = threading.Thread(target=alvo, name="sync-manual-teste")
        thread.start()
        thread.join()
        try:
            raise _ErroDoBanco("null value\nDETAIL:  " + detalhe, detalhe)
        except _ErroDoBanco as erro:
            sys.excepthook(type(erro), erro, erro.__traceback__)
        saida = capsys.readouterr()
    finally:
        sys.excepthook, threading.excepthook = gancho_processo, gancho_thread
        for h in list(raiz.handlers):
            raiz.removeHandler(h)
        for h in antes:
            raiz.addHandler(h)
        raiz.setLevel(nivel)
    for parte in NOME_FICTICIO.split():
        assert parte not in saida.out + saida.err, parte
    linhas = [json.loads(linha) for linha in saida.out.splitlines() if linha.startswith("{")]
    nao_tratadas = [linha for linha in linhas if linha["message"] == "excecao_nao_tratada"]
    assert [linha.get("nome_da_thread") for linha in nao_tratadas] == ["sync-manual-teste", None]
    for linha in nao_tratadas:
        assert "DETAIL:  Failing row contains (<redigido>)." in linha["excecao"]


def test_sincronizar_agora_registra_a_falha_da_thread_no_log(monkeypatch, caplog):
    """A thread do "Sincronizar agora" não tinha except: a exceção que escapava de
    executar() (ex.: o rollback falha depois de um IntegrityError) morria no excepthook."""
    import threading

    from app.sync import service
    detalhe = "Failing row contains (1, " + NOME_FICTICIO + ")."
    escapou = []
    monkeypatch.setattr(threading, "excepthook", lambda args: escapou.append(args.exc_type))

    def executar_que_falha(_execucao_id):
        raise _ErroDoBanco("null value\nDETAIL:  " + detalhe, detalhe)

    monkeypatch.setattr(service, "executar_por_id", executar_que_falha)
    with caplog.at_level(logging.ERROR, logger="constela.sync"):
        service.disparar_em_thread(987654)
        for thread in threading.enumerate():
            if thread.name == "sync-manual-987654":
                thread.join(timeout=10)
    assert escapou == []
    registro = next(r for r in caplog.records if r.getMessage() == "sync_manual_falhou")
    assert registro.execucao_id == 987654 and registro.exc_info is not None
    linha = obs.FormatadorJson().format(registro)
    for parte in NOME_FICTICIO.split():
        assert parte not in linha, parte


def test_notas_da_excecao_nao_sao_texto_do_dono():
    """Uma nota (add_note) pode trazer o texto de OUTRO erro; com o DETAIL do dono
    casando com o começo do DETAIL desse outro, o resto saía como estrutura."""
    erro = _ErroDoBanco("dup\nDETAIL:  " + D_CURTO, D_CURTO)
    erro.add_note("antes: dup\nDETAIL:  " + D_LONGO)
    try:
        raise erro
    except _ErroDoBanco as capturado:
        info = (type(capturado), capturado, capturado.__traceback__)
    texto = obs.traceback_redigido(info[1])
    for parte in PARAGRAFO_2.split():
        assert parte not in texto, parte
    assert "DETAIL:  Key (nome)=(<redigido>) already exists.\nantes: dup\nDETAIL:  <redigido>" in texto
    from sentry_sdk.utils import get_error_message
    evento = obs.higienizar_evento_sentry(
        {"exception": {"values": [{"type": "_ErroDoBanco", "value": get_error_message(erro)}]}},
        {"exc_info": info})
    for parte in PARAGRAFO_2.split():
        assert parte not in str(evento), parte
    assert evento["exception"]["values"][0]["value"] == (
        "dup\nDETAIL:  Key (nome)=(<redigido>) already exists.\nantes: dup\nDETAIL:  <redigido>")


def test_sentry_nao_muda_o_erro_e_detail_em_lista_falha_fechado():
    """O get_error_message do SDK ESTENDE a lista ``.detail`` de um erro do SQLAlchemy
    com as notas (letra por letra): a higiene não pode chamá-lo nem mudar o erro."""
    from sqlalchemy.exc import IntegrityError as ErroDeIntegridade
    orig = _ErroDoBanco("dup\nDETAIL:  " + D_LONGO, D_LONGO)
    erro = ErroDeIntegridade("INSERT", None, orig)
    erro.detail = ["raised as a result of Query-invoked autoflush"]
    erro.add_note("nota: dup\nDETAIL:  " + D_LONGO)
    detail_antes = list(erro.detail)
    valor = "(_ErroDoBanco) dup\nDETAIL:  " + D_LONGO
    evento = obs.higienizar_evento_sentry(
        {"exception": {"values": [{"type": "IntegrityError", "value": valor}]}},
        {"exc_info": (type(erro), erro, None)})
    assert erro.detail == detail_antes                           # o erro ficou intacto
    assert evento["exception"]["values"][0]["value"] == "(_ErroDoBanco) dup\nDETAIL:  <redigido>"
    for parte in PARAGRAFO_2.split():
        assert parte not in str(evento), parte


def test_excecao_nao_tratada_aparece_mesmo_com_log_level_critical(capsys):
    import sys
    import threading
    raiz = logging.getLogger()
    antes, nivel = list(raiz.handlers), raiz.level
    gancho_processo, gancho_thread = sys.excepthook, threading.excepthook
    try:
        class Config:
            LOG_LEVEL, LOG_JSON = "CRITICAL", True
        obs.configurar_logging(Config)
        try:
            raise RuntimeError("migração falhou")
        except RuntimeError as erro:
            sys.excepthook(type(erro), erro, erro.__traceback__)
        saida = capsys.readouterr()
    finally:
        sys.excepthook, threading.excepthook = gancho_processo, gancho_thread
        for h in list(raiz.handlers):
            raiz.removeHandler(h)
        for h in antes:
            raiz.addHandler(h)
        raiz.setLevel(nivel)
    linha = json.loads(saida.out.strip().splitlines()[-1])
    assert linha["message"] == "excecao_nao_tratada" and "RuntimeError: migração falhou" in (
        linha["excecao"])


# --- Sentry real: value em lista (autoflush + nota) --------------------------------

@pytest.fixture
def sentry_real(monkeypatch):
    """O ``configurar_sentry`` de verdade, só com o ENVIO trocado por um transporte em
    memória (nada vai para a rede); a troca do ``get_error_message`` é desfeita no fim."""
    sentry_sdk = pytest.importorskip("sentry_sdk")
    import sentry_sdk.utils as utilitarios
    from sentry_sdk.transport import Transport

    from app.core.config import settings
    dsn = "https://chaveficticia@sentry.exemplo.test/1"

    class _Transporte(Transport):
        def __init__(self):
            super().__init__({"dsn": dsn})
            self.envelopes = []

        def capture_envelope(self, envelope):
            self.envelopes.append(envelope)

    transporte = _Transporte()
    init_real = sentry_sdk.init

    class _SentryComTransporte:
        def __getattr__(self, nome):
            return getattr(sentry_sdk, nome)

        def init(self, **opcoes):
            return init_real(transport=transporte, **opcoes)

    monkeypatch.setattr(utilitarios, "get_error_message", utilitarios.get_error_message)
    monkeypatch.setattr(obs, "_sentry", _SentryComTransporte())
    monkeypatch.setattr(obs, "_sentry_ativo", False)
    monkeypatch.setattr(settings, "SENTRY_DSN", dsn)
    obs.configurar_sentry(settings)
    try:
        yield transporte
    finally:
        sentry_sdk.get_client().close()
        sentry_sdk.get_global_scope().set_client(None)


def _corpo_dos_envelopes(transporte) -> str:
    return b"".join(envelope.serialize() for envelope in transporte.envelopes).decode(
        "utf-8", "replace")


def test_sentry_value_em_lista_e_pedacos_que_formam_um_detail_falham_fechado():
    """O SDK pode entregar o value como LISTA (o .detail de um erro do SQLAlchemy
    estendido com as notas, letra por letra): redigido como um texto só."""
    letras = list("contexto: dup\nDETAIL:  " + D_LONGO)
    evento = obs.higienizar_evento_sentry(
        {"exception": {"values": [{"type": "IntegrityError", "value": letras}]},
         "extra": {"pedacos": ["DETAIL:  Key (nome)=(", PARAGRAFO_2, ") already exists."]}})
    for parte in PARAGRAFO_2.split():
        assert parte not in str(evento), parte
    assert evento["exception"]["values"][0]["value"] == "contexto: dup\nDETAIL:  <redigido>"


@pytest.mark.postgres
def test_erro_real_do_autoflush_com_nota_no_sentry_real(engine_postgres, sentry_real):
    """Caminho do SDK de verdade: IntegrityError do autoflush (``.detail`` em lista) com
    uma nota que copia o erro do driver. O SDK estendia a lista do PRÓPRIO erro com a
    nota letra por letra e mandava os caracteres soltos; agora o erro fica intacto e
    nada do valor sai no envelope."""
    import sentry_sdk
    from sqlalchemy import Column, Integer, Text
    from sqlalchemy.orm import Session as Sessao
    from sqlalchemy.orm import declarative_base

    Base = declarative_base()

    class Linha(Base):
        __tablename__ = "_detalhe_autoflush"
        id = Column(Integer, primary_key=True)
        nome = Column(Text, unique=True)

    with engine_postgres.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS _detalhe_autoflush"))
        c.execute(text("CREATE TABLE _detalhe_autoflush (id serial primary key, nome text UNIQUE)"))
        c.execute(text("INSERT INTO _detalhe_autoflush (nome) VALUES (:n)"), {"n": NOME_FICTICIO})
    try:
        sessao = Sessao(engine_postgres)
        sessao.add(Linha(nome=NOME_FICTICIO))
        with pytest.raises(IntegrityError) as pego:
            sessao.query(Linha).all()                  # o autoflush grava antes da consulta
        erro = pego.value
        assert erro.detail, "controle: o erro do autoflush tem .detail"
        erro.add_note("contexto: " + str(erro.orig))
        detail_antes = list(erro.detail)
        sentry_sdk.capture_exception(erro)
        sentry_sdk.flush()
        sessao.close()
        assert erro.detail == detail_antes                       # o erro ficou intacto
        corpo = _corpo_dos_envelopes(sentry_real)
        assert sentry_real.envelopes, "controle: o evento foi capturado"
        for parte in NOME_FICTICIO.split():
            assert parte not in corpo, f"no envelope do Sentry: {parte}"
    finally:
        with engine_postgres.begin() as c:
            c.execute(text("DROP TABLE IF EXISTS _detalhe_autoflush"))
