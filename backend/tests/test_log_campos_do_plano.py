"""Os campos do log JSON que o PLANO de implantação monitora saem IGUAIS ao enviado.

O PLANO (acompanhamento depois do deploy) lê o log JSON da Railway: a contagem de
``sync_execucao_finalizada`` por status, motivo e origem, com ``duracao_ms`` e
``alunos_aplicados``; e o p95 de /sync/status, /sync/dashboard e /auth/login pela linha
``http_acesso`` (``metodo``, ``rota``, ``status``, ``dur_ms``). A redação de dado pessoal
do formatador (logexc, 30/10) alcança só o texto de EXCEÇÕES; o id grande, a duração de
7 dígitos e o motivo com maiúsculas e números saem como foram enviados. Mas os testes do
logsaidas liam o ``LogRecord`` e só conferiam ``origem``, com ids pequenos: uma redação
estendida à mensagem ou às strings do ``extra`` (``execucao=<numero>``, ``motivo=<nome>``)
cegaria o painel do PLANO sem nenhum teste reprovar (revisão integrada de 30/10, achado D).

Aqui tudo passa pelo ``FormatadorJson`` REAL, instalado por ``configurar_logging`` com
``LOG_JSON`` como em produção (o handler único da raiz, com o stdout trocado por um
buffer), e cada campo é conferido valor a valor, com o tipo, sem marcador de redação no
campo nem na mensagem. Dados FICTÍCIOS, sem rede.
"""
from __future__ import annotations

import io
import json
import logging
import sys
import threading
import time
import types
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core import observabilidade as obs
from app.core.config import settings
from app.core.security import hash_senha
from app.main import app
from app.models import Escola, Usuario
from app.models.sincronizacao import SincronizacaoExecucao
from app.sync import service

EVENTO = "sync_execucao_finalizada"
CAMPOS_DO_FIM = ("execucao_id", "escola_id", "plataforma", "status", "motivo", "duracao_ms",
                 "alunos_aplicados", "origem")
CAMPOS_DO_ACESSO = ("metodo", "rota", "status", "dur_ms")
MARCAS = ("<numero>", "<nome>", "<redigido>", "<token>", "<email>")
PLATAFORMAS = ("matific", "elefante", "letrado")
ORIGENS = sorted(service.ORIGENS_DO_FIM)

# (execucao_id, escola_id, status, motivo, duracao_ms, alunos_aplicados): ids de 6 a 10
# dígitos, duração de 3 a 8 dígitos, motivo em código e em texto com maiúsculas e números.
CASOS_DO_FIM = (
    (2147483647, 123456, "erro", "Timeout 2400000", 2400000, 0),
    (123456, 17, "erro", "Login Recusado Pela Plataforma", 123456, None),
    (9876543210, 2147483647, "parcial", "HTTP 503", 86400000, 123456),
    (123456, 2147483647, "concluida", None, 2400000, 123456),
    (2147483647, 1, "sem_atualizacao", "coleta_incompleta", 999, 501),
    (409, 123456, "cancelada", "Erro 123456789", None, None),
    (2147483647, 123456, "erro", "Coleta Incompleta", 1234567, 2147483647),
)

ESCOLA_ID = 123456
EMAIL_GLOBAL = "global.plano@teste.local"
EMAIL_ESCOLA = "admin.plano@teste.local"
SENHA = "s3nh4"                     # a mesma senha fictícia do conftest


@pytest.fixture
def log_json(monkeypatch):
    """O logging do processo como em produção — ``configurar_logging`` com
    ``LOG_JSON=True`` — escrevendo num buffer. Devolve a função que lê (e esvazia) as
    linhas JSON. O logging volta ao que era pelo conftest; os ganchos de exceção que o
    ``configurar_logging`` instala, pelo monkeypatch."""
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    buf = io.StringIO()
    stdout = sys.stdout
    sys.stdout = buf
    try:
        obs.configurar_logging(types.SimpleNamespace(LOG_LEVEL="INFO", LOG_JSON=True))
    finally:
        sys.stdout = stdout
    handlers = logging.getLogger().handlers
    assert len(handlers) == 1 and isinstance(handlers[0], obs.SaidaDoLog)
    assert isinstance(handlers[0].formatter, obs.FormatadorJson)
    assert handlers[0].stream is buf

    def ler() -> list[dict]:
        texto = buf.getvalue()
        buf.seek(0)
        buf.truncate()
        return [json.loads(linha) for linha in texto.splitlines() if linha.strip()]

    return ler


def _sem_marcas(ev: dict, campos) -> None:
    trecho = json.dumps({c: ev.get(c) for c in (*campos, "message", "msg")},
                        ensure_ascii=False)
    for marca in MARCAS:
        assert marca not in trecho, f"marcador de redação {marca} em {trecho}"


def _confere_fim(ev: dict, esperado: dict) -> None:
    """A linha do fim, campo a campo (valor E tipo), a mensagem e o nível."""
    for campo in CAMPOS_DO_FIM:
        assert campo in ev, f"{campo} faltando: {ev}"
        assert ev[campo] == esperado[campo], (campo, ev[campo], esperado[campo])
        assert type(ev[campo]) is type(esperado[campo]), (campo, ev[campo])
    mensagem = (f"{EVENTO} execucao={esperado['execucao_id']} "
                f"escola={esperado['escola_id']} plataforma={esperado['plataforma']} "
                f"status={esperado['status']} motivo={esperado['motivo'] or '-'}")
    assert ev["message"] == mensagem and ev["msg"] == mensagem, ev["message"]
    assert ev["logger"] == "constela.sync"
    concluiu = esperado["status"] == "concluida" and bool(esperado["alunos_aplicados"])
    assert (ev["level"], ev["nivel"]) == (("info", "INFO") if concluiu else ("warn", "WARNING"))
    _sem_marcas(ev, CAMPOS_DO_FIM)


def _fins(linhas: list[dict]) -> list[dict]:
    return [ev for ev in linhas if ev.get("message", "").startswith(EVENTO)]


# --------------------------------------------------------------------------
# (i) sync_execucao_finalizada: _escrever_fim, o fim de executar e o after_commit
# --------------------------------------------------------------------------
@pytest.mark.parametrize("origem", ORIGENS)
def test_linha_do_fim_sai_igual_ao_enviado_em_cada_origem(log_json, origem):
    for plataforma in PLATAFORMAS:
        for ex, es, status, motivo, duracao, alunos in CASOS_DO_FIM:
            service._escrever_fim(ex, es, plataforma, status, motivo, origem=origem,
                                  duracao_ms=duracao, alunos_aplicados=alunos)
            linhas = log_json()
            assert len(linhas) == 1, linhas
            _confere_fim(linhas[0], {
                "execucao_id": ex, "escola_id": es, "plataforma": plataforma,
                "status": status, "motivo": motivo, "duracao_ms": duracao,
                "alunos_aplicados": alunos, "origem": origem})


@pytest.mark.parametrize("plataforma", PLATAFORMAS)
def test_fim_de_executar_sai_com_duracao_e_alunos_aplicados(log_json, plataforma):
    """``_logar_fim_da_execucao``, o que o fim de ``executar`` chama: a duração e o
    status vêm do fim gravado; a contagem, dos alunos aplicados da apuração."""
    for status, motivo, duracao, aplicados in (
            ("concluida", None, 2400000, 123456), ("erro", "Timeout 2400000", 123456, 0),
            ("parcial", "HTTP 503", 1234567, 501)):
        ap = service._Apuracao(aplicados=set(range(aplicados)))
        service._logar_fim_da_execucao(2147483647, ESCOLA_ID, plataforma,
                                       (status, motivo, duracao), ap)
        linhas = log_json()
        assert len(linhas) == 1, linhas
        _confere_fim(linhas[0], {
            "execucao_id": 2147483647, "escola_id": ESCOLA_ID, "plataforma": plataforma,
            "status": status, "motivo": motivo, "duracao_ms": duracao,
            "alunos_aplicados": aplicados, "origem": "executar"})


def test_linha_anotada_sai_igual_no_commit_em_cada_origem(log_json, db):
    """O caminho real das saídas fora de ``executar``: ``_anotar_fim`` na transação
    aberta e a linha escrita pelo ``after_commit`` do commit da raiz."""
    for i, origem in enumerate(ORIGENS):
        for j, plataforma in enumerate(PLATAFORMAS):
            ex = (2147483647, 123456, 9876543210)[j]
            es = (123456, 2147483647, 17)[(i + j) % 3]
            alunos = (123456, 0, None)[(i + j) % 3]
            db.execute(text("select 1"))                 # a transação que o UPDATE abriria
            service._anotar_fim(db, ex, es, plataforma, "cancelada", origem=origem,
                                alunos_aplicados=alunos)
            assert log_json() == []                      # só depois do commit
            db.commit()
            linhas = log_json()
            assert len(linhas) == 1, linhas
            _confere_fim(linhas[0], {
                "execucao_id": ex, "escola_id": es, "plataforma": plataforma,
                "status": "cancelada", "motivo": None, "duracao_ms": None,
                "alunos_aplicados": alunos, "origem": origem})


# --------------------------------------------------------------------------
# (ii) http_acesso do middleware real, pelas rotas reais
# --------------------------------------------------------------------------
class _RelogioDoMiddleware:
    """O ``time`` do módulo de observabilidade com o ``perf_counter`` controlado: cada
    requisição lê o início e o fim, e a duração de cada uma sai de ``duracoes_s``, em
    ordem. O resto do módulo ``time`` é o de verdade."""

    def __init__(self, duracoes_s) -> None:
        self._duracoes = list(duracoes_s)
        self._inicio = None

    def perf_counter(self) -> float:
        if self._inicio is None:
            self._inicio = 1000.0
            return self._inicio
        fim, self._inicio = self._inicio + self._duracoes.pop(0), None
        return fim

    def __getattr__(self, nome):
        return getattr(time, nome)


def _dur_ms(duracao_s: float) -> float:
    """O ``dur_ms`` que o middleware calcula para essa duração (início em 1000,0 s)."""
    return round(((1000.0 + duracao_s) - 1000.0) * 1000, 1)


def _acessos(linhas: list[dict]) -> list[dict]:
    return [ev for ev in linhas if ev.get("message") == "http_acesso"]


def _confere_acesso(ev: dict, metodo: str, rota: str, status: int, duracao_s: float) -> None:
    esperado = {"metodo": metodo, "rota": rota, "status": status, "dur_ms": _dur_ms(duracao_s)}
    for campo in CAMPOS_DO_ACESSO:
        assert campo in ev, f"{campo} faltando: {ev}"
        assert ev[campo] == esperado[campo], (campo, ev[campo], esperado[campo])
        assert type(ev[campo]) is type(esperado[campo]), (campo, ev[campo])
    assert ev["msg"] == "http_acesso" and ev["logger"] == "constela.http"
    assert ev["level"] == ("error" if status >= 500 else "warn" if status >= 400 else "info")
    _sem_marcas(ev, CAMPOS_DO_ACESSO)


def _usuarios(db) -> None:
    """Escola de id grande, com um admin global (vê o painel) e um da escola (não vê)."""
    db.add(Escola(id=ESCOLA_ID, nome="ESCOLA FICTICIA DO PLANO", ano_letivo_ativo=2026))
    db.flush()
    db.add(Usuario(escola_id=ESCOLA_ID, nome="Admin Global Ficticio", email=EMAIL_GLOBAL,
                   senha_hash=hash_senha(SENHA), cargo="admin", is_global=True))
    db.add(Usuario(escola_id=ESCOLA_ID, nome="Admin Escola Ficticio", email=EMAIL_ESCOLA,
                   senha_hash=hash_senha(SENHA), cargo="admin"))
    db.commit()


def test_http_acesso_das_rotas_do_plano_sai_igual_ao_medido(log_json, db, monkeypatch):
    _usuarios(db)
    monkeypatch.setattr(settings, "SYNC_SCHEDULER_ENABLED", False)   # como em produção
    duracoes = (0.1875, 2400.0, 0.0425, 123.4567, 0.3125, 61.25, 1.5, 0.0005, 45.0)
    monkeypatch.setattr(obs, "time", _RelogioDoMiddleware(duracoes))
    cli = TestClient(app)
    status_ = f"/api/v1/escolas/{ESCOLA_ID}/sync/status"

    respostas = [
        cli.post("/api/v1/auth/login", data={"username": EMAIL_GLOBAL, "password": SENHA}),
        cli.post("/api/v1/auth/login",
                 data={"username": EMAIL_GLOBAL, "password": "senha-errada-ficticia"}),
    ]
    token = respostas[0].json()["access_token"]
    global_ = {"Authorization": f"Bearer {token}"}
    login_escola = cli.post("/api/v1/auth/login",
                            data={"username": EMAIL_ESCOLA, "password": SENHA})
    respostas.append(login_escola)
    escola = {"Authorization": f"Bearer {login_escola.json()['access_token']}"}
    respostas += [
        cli.get(status_, headers=global_),
        cli.get(status_),
        cli.get("/api/v1/sync/dashboard", headers=global_),
        cli.get("/api/v1/sync/dashboard", headers=escola),
        cli.get("/api/v1/sync/dashboard"),
    ]

    def _quebra(*_a, **_kw):
        raise RuntimeError("falha fictícia no meio do /status")

    monkeypatch.setattr(service, "liberar_fila_sem_agendador", _quebra)
    respostas.append(cli.get(status_, headers=global_))

    esperados = [
        ("POST", "/api/v1/auth/login", 200), ("POST", "/api/v1/auth/login", 401),
        ("POST", "/api/v1/auth/login", 200),
        ("GET", "/api/v1/escolas/{escola_id}/sync/status", 200),
        ("GET", "/api/v1/escolas/{escola_id}/sync/status", 401),
        ("GET", "/api/v1/sync/dashboard", 200), ("GET", "/api/v1/sync/dashboard", 403),
        ("GET", "/api/v1/sync/dashboard", 401),
        ("GET", "/api/v1/escolas/{escola_id}/sync/status", 500),
    ]
    assert [r.status_code for r in respostas] == [s for _, _, s in esperados], [
        (r.status_code, r.text[:200]) for r in respostas]
    acessos = _acessos(log_json())
    assert len(acessos) == len(esperados), acessos
    for ev, (metodo, rota, status), duracao in zip(acessos, esperados, duracoes):
        _confere_acesso(ev, metodo, rota, status, duracao)
    assert acessos[3]["escola_id"] == ESCOLA_ID          # o contexto da rota da escola


def test_status_que_libera_a_fila_loga_o_fim_e_o_acesso_iguais(log_json, db, monkeypatch):
    """O /status real com o agendador desligado (como em produção) cancela a agendada
    e a manual órfã: as duas linhas do fim (ids grandes) e a do acesso, pelo mesmo
    handler JSON, na mesma requisição."""
    _usuarios(db)
    monkeypatch.setattr(settings, "SYNC_SCHEDULER_ENABLED", False)
    db.add(SincronizacaoExecucao(id=2147483647, escola_id=ESCOLA_ID, plataforma="elefante",
                                 origem="scheduler", status="fila", tentativa=1,
                                 parametros={}))
    db.add(SincronizacaoExecucao(
        id=123456, escola_id=ESCOLA_ID, plataforma="matific", origem="manual",
        status="fila", tentativa=1, parametros={},
        created_at=service._agora() - timedelta(seconds=settings.SYNC_TRAVADA_S + 600)))
    db.commit()
    cli = TestClient(app)
    login = cli.post("/api/v1/auth/login", data={"username": EMAIL_GLOBAL, "password": SENHA})
    assert login.status_code == 200, login.text
    log_json()
    monkeypatch.setattr(obs, "time", _RelogioDoMiddleware([2400.0]))
    r = cli.get(f"/api/v1/escolas/{ESCOLA_ID}/sync/status",
                headers={"Authorization": f"Bearer {login.json()['access_token']}"})
    assert r.status_code == 200, r.text
    linhas = log_json()
    fins = sorted(_fins(linhas), key=lambda ev: ev["execucao_id"])
    assert len(fins) == 2, fins
    for ev, (ex, plataforma, origem) in zip(fins, (
            (123456, "matific", "fila_manual_orfa"),
            (2147483647, "elefante", "fila_sem_agendador"))):
        _confere_fim(ev, {                               # nunca rodou: 0 aplicado
            "execucao_id": ex, "escola_id": ESCOLA_ID, "plataforma": plataforma,
            "status": "cancelada", "motivo": None, "duracao_ms": None,
            "alunos_aplicados": 0, "origem": origem})
    acessos = _acessos(linhas)
    assert len(acessos) == 1, acessos
    _confere_acesso(acessos[0], "GET", "/api/v1/escolas/{escola_id}/sync/status", 200, 2400.0)
