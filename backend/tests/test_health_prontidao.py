"""/api/health/ready = banco acessível E schema nas heads do Alembic do código.

É o healthcheck do deploy no Railway. Antes ele só fazia ``SELECT 1``: com
ENV=producao e a migração não aplicada, diria "pronto" e o tráfego iria para um
processo que dá 500 nas rotas com colunas novas. Agora, migração pendente → 503
``migracao_pendente`` e o deploy anterior continua no ar.
"""
from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

import app.main as main_mod
from app.core.config import settings
from app.core.prontidao import Prontidao
from tests._infra_comum import (  # noqa: F401 — fixtures
    REV_FUTURA,
    assinatura,
    heads_do_codigo,
    levar_a,
    migrar_processo,
    pg_url,
    revisao_anterior_a_head,
    sondar,
)

cliente = TestClient(main_mod.app)


def _banco_com_versao(tmp_path, nome: str, revisao: str | None):
    engine = create_engine(f"sqlite:///{(tmp_path / nome).as_posix()}")
    if revisao:
        with engine.begin() as c:
            c.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
            c.execute(text("INSERT INTO alembic_version VALUES (:v)"), {"v": revisao})
    return engine


@pytest.fixture
def processo_novo(monkeypatch):
    """Prontidão de um processo que ACABOU de subir (nunca ficou pronto)."""
    nova = Prontidao()
    monkeypatch.setattr(main_mod, "prontidao", nova)
    return nova


def test_banco_nas_heads_responde_200_em_dia():
    r = cliente.get("/api/health/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "banco": "ok", "schema": "em_dia"}


@pytest.mark.parametrize("revisao", ["anterior", None])
def test_banco_atras_ou_sem_versao_responde_503_migracao_pendente(
        tmp_path, monkeypatch, processo_novo, revisao):
    rev = revisao_anterior_a_head() if revisao == "anterior" else None
    engine = _banco_com_versao(tmp_path, "atras.db", rev)
    monkeypatch.setattr(main_mod, "engine", engine)
    try:
        r = cliente.get("/api/health/ready")
    finally:
        engine.dispose()
    assert r.status_code == 503
    assert r.json() == {"status": "degradado", "banco": "ok", "motivo": "migracao_pendente"}
    # Sem detalhe sensível no corpo público: nenhuma revisão (nem do banco, nem do código).
    for revisao_id in heads_do_codigo() + [revisao_anterior_a_head()]:
        assert revisao_id not in r.text
    # O processo segue vivo (o orquestrador não reinicia em laço).
    assert cliente.get("/api/health/live").status_code == 200


def test_migracao_pendente_vai_para_o_log_uma_vez_com_as_revisoes(
        tmp_path, monkeypatch, processo_novo, caplog):
    engine = _banco_com_versao(tmp_path, "atras.db", revisao_anterior_a_head())
    monkeypatch.setattr(main_mod, "engine", engine)
    try:
        with caplog.at_level(logging.INFO, logger="constela"):
            for _ in range(3):
                assert cliente.get("/api/health/ready").status_code == 503
    finally:
        engine.dispose()
    erros = [r for r in caplog.records if "NÃO PRONTO" in r.getMessage()]
    assert len(erros) == 1 and erros[0].levelno == logging.ERROR
    assert revisao_anterior_a_head() in erros[0].getMessage()


def test_banco_adiante_no_boot_nao_fica_pronto_salvo_aceito(tmp_path, monkeypatch,
                                                            processo_novo):
    engine = _banco_com_versao(tmp_path, "adiante.db", REV_FUTURA)
    monkeypatch.setattr(main_mod, "engine", engine)
    try:
        r = cliente.get("/api/health/ready")
        assert r.status_code == 503 and r.json()["motivo"] == "schema_adiante"
        monkeypatch.setattr(settings, "SCHEMA_ADIANTE_ACEITO", REV_FUTURA)
        r = cliente.get("/api/health/ready")
        assert r.status_code == 200 and r.json()["schema"] == "adiante_aceito"
    finally:
        engine.dispose()


def test_banco_adiante_depois_de_pronto_continua_servindo(tmp_path, monkeypatch,
                                                          processo_novo):
    """Janela normal de deploy: o pre-deploy do PRÓXIMO deploy migrou enquanto este
    processo (que já estava pronto) ainda atende."""
    assert cliente.get("/api/health/ready").status_code == 200       # fica pronto
    engine = _banco_com_versao(tmp_path, "adiante.db", REV_FUTURA)
    monkeypatch.setattr(main_mod, "engine", engine)
    try:
        r = cliente.get("/api/health/ready")
    finally:
        engine.dispose()
    assert r.status_code == 200 and r.json()["schema"] == "adiante_apos_boot"


def test_processo_que_bootou_com_schema_errado_nao_fica_pronto_com_o_schema_em_dia(
        processo_novo, caplog):
    """O boot pulou o agendador, os ajustes de dados e a liberação de órfãs
    (``app.main`` chama ``exigir_reinicio``). Com o banco deste processo nas heads, o
    readiness segue 503 ``reinicio_pendente``: só um boot novo sobe essas peças. O
    ponta a ponta (boot de verdade + migração por fora) está em
    tests/test_boot_schema_errado_agendador.py."""
    processo_novo.exigir_reinicio("migracao_pendente")
    with caplog.at_level(logging.INFO, logger="constela"):
        for _ in range(3):
            r = cliente.get("/api/health/ready")
            assert r.status_code == 503
            assert r.json() == {"status": "degradado", "banco": "ok",
                                "motivo": "reinicio_pendente"}
    assert processo_novo.ja_pronto is False      # nunca serviu: nada de adiante_apos_boot
    avisos = [x for x in caplog.records if "REINICIE" in x.getMessage()]
    assert len(avisos) == 1 and avisos[0].levelno == logging.ERROR
    assert "migracao_pendente" in avisos[0].getMessage()
    # Sem revisão no corpo público, e o processo segue vivo.
    for revisao_id in heads_do_codigo():
        assert revisao_id not in r.text
    assert cliente.get("/api/health/live").status_code == 200


def test_processo_com_boot_completo_continua_ficando_pronto(processo_novo):
    """Controle do teste acima: sem a marca do boot, o mesmo banco dá 200."""
    r = cliente.get("/api/health/ready")
    assert r.status_code == 200 and r.json()["schema"] == "em_dia"


def test_banco_inacessivel_responde_503(tmp_path, monkeypatch, processo_novo):
    # Diretório que não existe: o SQLite não consegue abrir o arquivo.
    engine = create_engine(f"sqlite:///{(tmp_path / 'nao' / 'existe.db').as_posix()}")
    monkeypatch.setattr(main_mod, "engine", engine)
    r = cliente.get("/api/health/ready")
    assert r.status_code == 503
    assert r.json() == {"status": "degradado", "banco": "inacessivel",
                        "motivo": "banco_inacessivel"}


# --- HEAD nas sondas (lente OBSERVABILIDADE, 27/10) -------------------------------
# O log de produção tinha ~3 HEAD /api/health/ready por hora, todos 405: o @app.get do
# FastAPI não registra HEAD, e o monitor que sonda assim nunca media a prontidão.

def test_head_no_readiness_nao_e_405():
    for rota in ("/api/health/ready", "/api/health/live"):
        r = cliente.head(rota)
        assert r.status_code == 200, (rota, r.status_code)
    # O GET continua o mesmo.
    r = cliente.get("/api/health/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "banco": "ok", "schema": "em_dia"}


def test_head_no_readiness_acompanha_o_get_quando_nao_esta_pronto(tmp_path, monkeypatch,
                                                                processo_novo):
    """HEAD não é um "200 sempre": com migração pendente responde 503, como o GET."""
    engine = _banco_com_versao(tmp_path, "atras.db", revisao_anterior_a_head())
    monkeypatch.setattr(main_mod, "engine", engine)
    try:
        head = cliente.head("/api/health/ready")
        get = cliente.get("/api/health/ready")
    finally:
        engine.dispose()
    assert head.status_code == get.status_code == 503
    assert get.json()["motivo"] == "migracao_pendente"


def test_head_das_sondas_fica_fora_do_openapi():
    """O contrato publicado não muda: as sondas seguem só com GET no OpenAPI."""
    caminhos = main_mod.app.openapi()["paths"]
    for rota in ("/api/health/ready", "/api/health/live"):
        assert set(caminhos[rota]) == {"get"}, (rota, set(caminhos[rota]))


# --- ENV=producao em processo separado (PostgreSQL real) -------------------------

def _linhas_json(log: str) -> list[dict]:
    saida = []
    for linha in log.splitlines():
        if linha.startswith("{"):
            try:
                saida.append(json.loads(linha))
            except ValueError:
                pass
    return saida


@pytest.mark.postgres
def test_producao_com_banco_atras_nao_migra_e_ready_acusa_migracao_pendente(pg_url):
    levar_a(pg_url, revisao_anterior_a_head())
    antes = assinatura(pg_url)
    r = sondar(pg_url, producao=True)
    assert r["ready"] == 503 and r["ready_corpo"]["motivo"] == "migracao_pendente"
    assert r["live"] == 200
    assert "Running upgrade" not in r["_log"]            # o import NÃO migrou
    assert assinatura(pg_url) == antes                   # e não escreveu nada
    erros = [x for x in _linhas_json(r["_log"]) if "NÃO PRONTO" in x.get("message", "")]
    assert erros and erros[0]["level"] == "error"        # JSON no stdout, com level


@pytest.mark.postgres
def test_sequencia_pre_deploy_depois_producao_fica_pronto(pg_url):
    """A ordem do Railway: pre-deploy (scripts.migrate) num processo; o servidor com
    ENV=producao noutro — pronto, sem migrar no import."""
    levar_a(pg_url, revisao_anterior_a_head())
    p = migrar_processo(pg_url, producao=True)
    assert p.returncode == 0, p.stderr[-3000:]
    r = sondar(pg_url, producao=True)
    assert r["ready"] == 200 and r["ready_corpo"]["schema"] == "em_dia"
    assert "Running upgrade" not in r["_log"]
    assert assinatura(pg_url)["versao"] == heads_do_codigo()


@pytest.mark.postgres
def test_modo_dev_ainda_migra_no_import(pg_url):
    """O comportamento de HOJE em produção (sem ENV) continua: migra no import."""
    levar_a(pg_url, revisao_anterior_a_head())
    r = sondar(pg_url, producao=False)
    assert r["ready"] == 200 and r["ready_corpo"]["schema"] == "em_dia"
    assert "Running upgrade" in r["_log"]
    assert assinatura(pg_url)["versao"] == heads_do_codigo()
