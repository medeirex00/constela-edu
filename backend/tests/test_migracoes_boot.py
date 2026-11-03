"""Migração segura para a sequência de produção (pre-deploy + ENV=producao).

* ``estado_do_schema`` classifica o banco contra as revisões DESTA imagem;
* ``aplicar_migracoes`` recusa banco ADIANTE do código (rollback de imagem) e,
  no PostgreSQL, toma a vez por advisory lock (dois migradores não correm);
* ``scripts.migrate`` é idempotente e devolve códigos de saída distintos;
* ``entrypoint.sh`` com argumentos roda só o comando (defesa do pre-deploy).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import shutil
import subprocess

import pytest
from sqlalchemy import create_engine, text

from app.core.config import BASE_DIR, settings
from app.core.migracoes import (
    SchemaAdianteDoCodigo,
    aplicar_migracoes,
    estado_do_schema,
)
from tests._infra_comum import (  # noqa: F401 — fixtures
    REV_FUTURA,
    assinatura,
    heads_do_codigo,
    levar_a,
    logging_preservado,
    marcar_versao,
    migrar_processo,
    pg_url,
    revisao_anterior_a_head,
    sqlite_url,
)


def _versao_manual(url: str, revisao: str) -> None:
    """Só a tabela de versão (o estado do schema lê apenas ela) — montagem barata."""
    engine = create_engine(url)
    try:
        with engine.begin() as c:
            c.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
            c.execute(text("INSERT INTO alembic_version VALUES (:v)"), {"v": revisao})
    finally:
        engine.dispose()


# --- Classificação -------------------------------------------------------------

def test_estado_do_schema_classifica_os_quatro_casos(tmp_path):
    def estado(nome, revisao=None):
        url = f"sqlite:///{(tmp_path / nome).as_posix()}"
        if revisao:
            _versao_manual(url, revisao)
        engine = create_engine(url)
        try:
            return estado_do_schema(engine)
        finally:
            engine.dispose()

    vazio = estado("vazio.db")
    assert vazio.situacao == "sem_versao" and vazio.falta_migrar

    atras = estado("atras.db", revisao_anterior_a_head())
    assert atras.situacao == "atras" and atras.falta_migrar
    assert atras.banco == (revisao_anterior_a_head(),)

    em_dia = estado("em_dia.db", heads_do_codigo()[0])
    assert em_dia.situacao == "em_dia" and not em_dia.falta_migrar
    assert list(em_dia.codigo) == heads_do_codigo()

    adiante = estado("adiante.db", REV_FUTURA)
    assert adiante.situacao == "adiante" and not adiante.falta_migrar
    assert adiante.desconhecidas == (REV_FUTURA,)


def test_heads_sao_lidas_uma_vez_por_processo(monkeypatch):
    """A leitura do diretório de migrações é cacheada; o readiness só faz o SELECT."""
    from app.core import migracoes

    migracoes._revisoes_do_codigo()            # aquece
    chamadas = []
    original = migracoes.ScriptDirectory.from_config
    monkeypatch.setattr(migracoes.ScriptDirectory, "from_config",
                        lambda *a, **k: chamadas.append(1) or original(*a, **k))
    for _ in range(5):
        migracoes._revisoes_do_codigo()
    assert chamadas == []


# --- Banco adiante do código (rollback de imagem) -------------------------------

def test_aplicar_migracoes_recusa_banco_adiante_sem_tocar_em_nada(sqlite_url):
    _versao_manual(sqlite_url, REV_FUTURA)
    antes = assinatura(sqlite_url)
    engine = create_engine(sqlite_url)
    try:
        with pytest.raises(SchemaAdianteDoCodigo, match="MAIS ANTIGO"):
            aplicar_migracoes(engine)
    finally:
        engine.dispose()
    assert assinatura(sqlite_url) == antes


def test_banco_adiante_aceito_por_id_exato_e_no_op(sqlite_url, monkeypatch):
    _versao_manual(sqlite_url, REV_FUTURA)
    antes = assinatura(sqlite_url)
    engine = create_engine(sqlite_url)
    try:
        monkeypatch.setattr(settings, "SCHEMA_ADIANTE_ACEITO", "9999_outra_revisao")
        with pytest.raises(SchemaAdianteDoCodigo):
            aplicar_migracoes(engine)                # id diferente: continua recusado
        monkeypatch.setattr(settings, "SCHEMA_ADIANTE_ACEITO", f" {REV_FUTURA} ")
        estado = aplicar_migracoes(engine)
    finally:
        engine.dispose()
    assert estado.situacao == "adiante"
    assert assinatura(sqlite_url) == antes


# --- '%' na DATABASE_URL (senha percent-codificada) ----------------------------
# A Config do Alembic é um ConfigParser com interpolação: o env.py gravava a URL crua
# e um '%' solto levantava "invalid interpolation syntax in '<URL inteira>'" — a senha
# ia para o log do deploy e nada migrava. O SQLAlchemy aceita a URL (decodifica %40).
# Senha FICTÍCIA.
_SENHA = "Fict@cia#Zq9%"
_SENHA_PCT = "Fict%40cia%23Zq9%25"          # a mesma, percent-codificada na URL


def test_senha_percent_codificada_na_url_nao_derruba_a_migracao(sqlite_url, monkeypatch):
    """A URL da aplicação (só lida pelo env.py; a conexão é a injetada) com '%' na
    senha: a migração leva o banco às heads, sem ValueError."""
    monkeypatch.setattr(settings, "DATABASE_URL",
                        f"postgresql+psycopg://u:{_SENHA_PCT}@127.0.0.1:1/x_test")
    engine = create_engine(sqlite_url)
    try:
        estado = aplicar_migracoes(engine)
    finally:
        engine.dispose()
    assert estado.situacao == "em_dia"
    assert assinatura(sqlite_url)["versao"] == heads_do_codigo()


def _scram_confere(verificador: str, senha: str) -> bool:
    """A conta que o servidor faz numa conexão por senha (SCRAM-SHA-256): a ServerKey
    derivada de ``senha`` bate com a guardada em ``pg_authid.rolpassword``?"""
    _, iteracoes_sal, chaves = verificador.split("$")
    iteracoes, sal = iteracoes_sal.split(":")
    salgada = hashlib.pbkdf2_hmac("sha256", senha.encode(), base64.b64decode(sal),
                                  int(iteracoes))
    chave = base64.b64encode(hmac.new(salgada, b"Server Key", "sha256").digest()).decode()
    return hmac.compare_digest(chave, chaves.split(":")[1])


@pytest.mark.postgres
def test_pre_deploy_de_producao_migra_com_senha_percent_codificada(pg_url):
    """O pre-deploy de verdade (processo novo, ENV=producao) com a senha percent-codificada
    na DATABASE_URL: sai 0, o banco fica nas heads e a senha não aparece na saída.

    A credencial do papel do SERVIÇO (a do ``pg_url``) não é trocada: o PostgreSQL do CI
    confere a senha (scram-sha-256 para quem chega de fora do contêiner) e uma senha
    inventada na URL dele derrubaria a autenticação. O teste cria um papel PRÓPRIO com a
    senha fictícia — dono do schema, não superusuário, como o papel do app em produção —,
    migra com ele e o apaga no fim. Onde a senha é conferida (CI), a autenticação prova
    que a senha decodificada da URL chega certa; no PG local 'trust', a mesma prova vem
    do verificador SCRAM que o servidor guardou para o papel."""
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import DBAPIError

    papel = f"pct_migr_test_{os.getpid()}"
    servico = create_engine(pg_url)
    try:
        with servico.begin() as c:
            c.execute(text(f"CREATE ROLE \"{papel}\" LOGIN NOSUPERUSER BYPASSRLS "
                           f"PASSWORD '{_SENHA}'"))
    except DBAPIError as exc:
        servico.dispose()
        pytest.skip(f"o usuário do PostgreSQL de teste não cria papel: {exc.orig}")
    try:
        with servico.begin() as c:
            c.execute(text(f'ALTER SCHEMA public OWNER TO "{papel}"'))
            verificador = c.execute(text("SELECT rolpassword FROM pg_authid WHERE rolname = :p"),
                                    {"p": papel}).scalar()
        url = make_url(pg_url).set(username=papel, password=_SENHA).render_as_string(
            hide_password=False)
        assert _SENHA_PCT in url and make_url(url).password == _SENHA
        if verificador.startswith("SCRAM-SHA-256$"):
            assert _scram_confere(verificador, _SENHA)
            assert not _scram_confere(verificador, _SENHA_PCT)
        p = migrar_processo(url, producao=True)
        saida = p.stdout + p.stderr
        assert p.returncode == 0, saida[-3000:].replace(_SENHA_PCT, "<senha>")
        assert assinatura(pg_url)["versao"] == heads_do_codigo()
        assert _SENHA_PCT not in saida and "Fict@cia#Zq9" not in saida
        with servico.connect() as c:                     # quem migrou foi o papel da URL
            assert c.execute(text("SELECT tableowner FROM pg_tables WHERE schemaname = "
                                  "'public' AND tablename = 'alembic_version'")).scalar() == papel
    finally:
        with servico.begin() as c:
            c.execute(text(f'REASSIGN OWNED BY "{papel}" TO CURRENT_USER'))
            c.execute(text(f'DROP OWNED BY "{papel}"'))
            c.execute(text(f'DROP ROLE "{papel}"'))
        servico.dispose()


# --- scripts.migrate: idempotência e códigos de saída ---------------------------

def _main_com(url, monkeypatch):
    from scripts import migrate

    engine = create_engine(url)
    monkeypatch.setattr(migrate, "engine", engine)
    try:
        return migrate.main()
    finally:
        engine.dispose()


def test_migrate_duas_vezes_e_idempotente_sqlite(sqlite_url, monkeypatch, capsys,
                                                 logging_preservado):
    assert _main_com(sqlite_url, monkeypatch) == 0
    saida1 = capsys.readouterr().out
    assert "Antes: schema sem_versao" in saida1 and "Running upgrade" in saida1
    assert "Depois: schema em_dia" in saida1
    depois_1 = assinatura(sqlite_url)
    assert depois_1["versao"] == heads_do_codigo()

    assert _main_com(sqlite_url, monkeypatch) == 0
    saida2 = capsys.readouterr().out
    assert "Antes: schema em_dia" in saida2 and "Running upgrade" not in saida2
    assert assinatura(sqlite_url) == depois_1


def test_migrate_sai_com_3_no_banco_adiante(sqlite_url, monkeypatch, capsys,
                                            logging_preservado):
    _versao_manual(sqlite_url, REV_FUTURA)
    antes = assinatura(sqlite_url)
    assert _main_com(sqlite_url, monkeypatch) == 3
    assert "RECUSADO" in capsys.readouterr().err
    assert assinatura(sqlite_url) == antes


@pytest.mark.postgres
def test_migrate_duas_vezes_e_idempotente_postgres(pg_url):
    levar_a(pg_url, revisao_anterior_a_head())
    p1 = migrar_processo(pg_url, producao=True)
    assert p1.returncode == 0, p1.stderr[-3000:]
    assert "Running upgrade" in p1.stdout
    depois_1 = assinatura(pg_url)
    assert depois_1["versao"] == heads_do_codigo()
    p2 = migrar_processo(pg_url, producao=True)
    assert p2.returncode == 0, p2.stderr[-3000:]
    assert "Antes: schema em_dia" in p2.stdout and "Running upgrade" not in p2.stdout
    assert assinatura(pg_url) == depois_1


@pytest.mark.postgres
def test_migrate_espera_a_vez_e_desiste_limpo_com_saida_2(pg_url):
    """Outro migrador segura o advisory lock: este espera MIGRACAO_ESPERA_VEZ, desiste
    com saída 2 e o banco fica intacto; com o lock solto, a próxima execução migra."""
    levar_a(pg_url, revisao_anterior_a_head())
    antes = assinatura(pg_url)
    engine = create_engine(pg_url)
    segura = engine.connect()
    try:
        segura.exec_driver_sql("SELECT pg_advisory_xact_lock(4714, 0)")   # transação aberta
        p = migrar_processo(pg_url, MIGRACAO_ESPERA_VEZ="1s", MIGRACAO_TENTATIVAS=1)
    finally:
        segura.close()
        engine.dispose()
    assert p.returncode == 2, (p.stdout[-2000:], p.stderr[-2000:])
    assert "DESISTI" in p.stderr
    assert assinatura(pg_url) == antes
    p2 = migrar_processo(pg_url)
    assert p2.returncode == 0, p2.stderr[-3000:]
    assert assinatura(pg_url)["versao"] == heads_do_codigo()


@pytest.mark.postgres
def test_migrate_recusa_banco_adiante_no_postgres(pg_url):
    levar_a(pg_url, "heads")
    marcar_versao(pg_url, REV_FUTURA)
    antes = assinatura(pg_url)
    p = migrar_processo(pg_url)
    assert p.returncode == 3 and "RECUSADO" in p.stderr
    assert assinatura(pg_url) == antes
    aceito = migrar_processo(pg_url, SCHEMA_ADIANTE_ACEITO=REV_FUTURA)
    assert aceito.returncode == 0, aceito.stderr[-3000:]
    assert assinatura(pg_url) == antes


# --- entrypoint.sh ---------------------------------------------------------------

def _falso(pasta, nome: str, registro) -> None:
    caminho = pasta / nome
    caminho.write_text(f'#!/bin/sh\necho "{nome} $*" >> "{registro.as_posix()}"\n',
                       encoding="utf-8", newline="\n")
    caminho.chmod(0o755)


@pytest.mark.skipif(shutil.which("sh") is None, reason="sem /bin/sh nesta máquina")
def test_entrypoint_sem_argumentos_migra_e_sobe_o_uvicorn(tmp_path):
    registro = tmp_path / "chamadas.txt"
    for nome in ("python", "uvicorn"):
        _falso(tmp_path, nome, registro)
    env = {**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}",
           "PORT": "8080", "WEB_CONCURRENCY": "1"}
    p = subprocess.run(["sh", (BASE_DIR / "entrypoint.sh").as_posix()], env=env,
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    chamadas = registro.read_text(encoding="utf-8").splitlines()
    assert chamadas[0] == "python -m scripts.migrate"
    assert chamadas[1].startswith("uvicorn app.main:app --host 0.0.0.0 --port 8080 --workers 1")


@pytest.mark.skipif(shutil.which("sh") is None, reason="sem /bin/sh nesta máquina")
def test_entrypoint_com_argumentos_roda_so_o_comando_e_devolve_a_saida(tmp_path):
    """O pre-deploy passado como argumento migra e TERMINA (sem uvicorn preso)."""
    registro = tmp_path / "chamadas.txt"
    for nome in ("python", "uvicorn"):
        _falso(tmp_path, nome, registro)
    env = {**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}"}
    p = subprocess.run(["sh", (BASE_DIR / "entrypoint.sh").as_posix(), "python", "-m", "scripts.migrate"],
                       env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    assert registro.read_text(encoding="utf-8").splitlines() == ["python -m scripts.migrate"]
    saida = subprocess.run(["sh", (BASE_DIR / "entrypoint.sh").as_posix(), "sh", "-c", "exit 3"],
                           env=env, capture_output=True, text=True, timeout=60)
    assert saida.returncode == 3
