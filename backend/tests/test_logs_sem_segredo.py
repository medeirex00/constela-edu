"""O log do PRÓPRIO app não grava os segredos que andam na URL.

Três segredos chegam à API no caminho ou no corpo da requisição:

* token do painel público da ESCOLA (``/publico/{token}/painel`` e
  ``/publico/{token}/alunos/{id}``) — quem lê o log abre o telão com nomes de crianças;
* token da vitrine da REDE (``/publico/rede/{token}``);
* token de redefinição de senha (``/auth/redefinir-senha/{token}``) — quem lê troca a
  senha da conta enquanto o link vale;
* token do QR do Quest — vai no CORPO de ``POST /quest/auth/entrar-qr`` (o
  ``?qr=`` fica na URL do app do Quest, não na da API).

O log de acesso (``http_acesso``) grava só o MODELO da rota, e o log de erro e o
Sentry passam o caminho por ``redigir_caminho``. Furo achado na auditoria de 20/10: a
regra tirava o PRIMEIRO segmento depois de ``/publico/`` — na vitrine da rede esse
segmento é a palavra ``rede``, e o token, que vem depois, ia inteiro para o log de
erro e para o Sentry.

A linha de acesso do PRÓPRIO uvicorn (logger ``uvicorn.access``) grava a URL crua,
com a query string. Ela ESTÁ ao alcance do app (2ª revisão de 20/10): o uvicorn
configura o logging antes de importar o app e decide, por conexão, se grava o acesso
por ``hasHandlers()`` desse logger. O ``configurar_logging`` (que roda no import do
``app.main``) o deixa sem handler e sem propagar, e o servidor de verdade, com o
comando de partida de hoje (sem ``--no-access-log``), deixa de gravar a linha.

Erro de BANCO (2ª revisão de 20/10): a exceção do SQLAlchemy traz os PARÂMETROS da
instrução no próprio texto — o nome da criança num INSERT de aluno — e esse texto ia
para o ``erro_nao_tratado`` e para o Sentry. O engine do app esconde os parâmetros.
"""
from __future__ import annotations

import io
import json
import logging
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core import database
from app.core import observabilidade as obs
from app.core.config import BASE_DIR, settings
from app.core.security import hash_token
from app.main import app
from app.models import Aluno, Rede, TokenResetSenha
from tests._infra_comum import BOOT, ambiente, levar_a, rodar, sqlite_url  # noqa: F401 — fixture

# Valores fictícios, longos e únicos: qualquer pedaço deles no log é vazamento.
TOKEN_PAINEL_FALSO = "tokPainelFicticio7Qx2"
TOKEN_REDE = "tokRedeFicticio9Lm4Zp"
TOKEN_RESET = "tokResetFicticio3Vb8Nw"
TOKEN_QR = "tokQrFicticio5Hd1Ks6Jt"
# Nome de criança FICTÍCIO (sobrenomes inventados: não coincide com ninguém real).
NOME_FICTICIO = "Zuleica Testelli Sintetico"
BUSCA_PARTES = ("Zuleica", "Testelli")          # o termo do ?busca=, peça por peça

_LOGGERS = ("sqlalchemy.engine", "alembic", "httpx", "uvicorn", "uvicorn.error",
            "uvicorn.access")


@pytest.fixture
def logging_restaurado():
    """Devolve a raiz e os loggers de ``_LOGGERS`` como estavam (outros testes
    dependem deles, e o ``configurar_logging`` os mexe — inclusive o ``uvicorn.access``)."""
    raiz = logging.getLogger()
    salvo = (list(raiz.handlers), raiz.level,
             {n: (logging.getLogger(n).level, list(logging.getLogger(n).handlers),
                  logging.getLogger(n).propagate) for n in _LOGGERS})
    yield
    handlers, nivel, outros = salvo
    raiz.handlers[:] = handlers
    raiz.setLevel(nivel)
    for nome, (lvl, hs, prop) in outros.items():
        lg = logging.getLogger(nome)
        lg.setLevel(lvl)
        lg.handlers[:] = hs
        lg.propagate = prop


@pytest.fixture
def log_do_processo(monkeypatch, logging_restaurado):
    """O logging de PRODUÇÃO (``configurar_logging``: JSON no stdout) apontado para
    um buffer; devolve as linhas JSON. Restaura o logging do processo no fim."""
    saida = io.StringIO()
    monkeypatch.setattr(sys, "stdout", saida)
    obs.configurar_logging(settings)

    def linhas() -> list[dict]:
        return [json.loads(x) for x in saida.getvalue().splitlines() if x.startswith("{")]

    yield linhas


def _do_app(linhas: list[dict]) -> list[dict]:
    """Só o que o SERVIDOR escreveu. O ``httpx`` aqui é o do TestClient (o lado do
    cliente, que não existe em produção); o nível dele tem teste próprio."""
    return [x for x in linhas if not x["logger"].startswith(("httpx", "httpcore"))]


def _ativar_painel(cliente, escola_id: int) -> str:
    r = cliente.put(f"/api/v1/escolas/{escola_id}/painel-publico",
                    json={"ativo": True, "slides": ["ranking"], "intervalo_s": 8,
                          "max_posicoes": 5})
    assert r.status_code == 200, r.text
    return r.json()["url"].rsplit("/", 1)[-1]


def test_log_de_acesso_e_de_erro_nao_gravam_token_de_url_nem_do_qr(
        cliente, db, escola_completa, log_do_processo, monkeypatch):
    escola = escola_completa["escola"]
    token_painel = _ativar_painel(cliente, escola.id)
    aluno_id = escola_completa["alunos"][0].id
    db.add(Rede(nome="Rede Ficticia Logs", status="ativa", token_publico=TOKEN_REDE))
    admin_id = escola_completa["admin"].id
    db.add(TokenResetSenha(usuario_id=admin_id, criado_por=admin_id,
                           token_hash=hash_token(TOKEN_RESET),
                           expira_em=datetime.now(timezone.utc) + timedelta(hours=1)))
    db.commit()

    anonimo = TestClient(app, raise_server_exceptions=False)
    assert anonimo.get(f"/api/v1/publico/{token_painel}/painel").status_code == 200
    assert anonimo.get(
        f"/api/v1/publico/{token_painel}/alunos/{aluno_id}").status_code in (200, 404)
    assert anonimo.get(f"/api/v1/publico/{TOKEN_PAINEL_FALSO}/painel").status_code == 404
    assert anonimo.get(f"/api/v1/publico/{TOKEN_PAINEL_FALSO}/xyz").status_code == 404
    assert anonimo.get(f"/api/v1/publico/rede/{TOKEN_REDE}").status_code == 200
    r = anonimo.get(f"/api/v1/auth/redefinir-senha/{TOKEN_RESET}")
    assert r.status_code == 200 and r.json()["valido"] is True
    assert anonimo.post("/api/v1/quest/auth/entrar-qr",
                        json={"qr_token": TOKEN_QR}).status_code == 401

    # Erro NÃO tratado no meio da rota da vitrine: o caminho vai para o log de erro.
    from app.services import rede as svc_rede

    def _quebra(*_a, **_k):
        raise RuntimeError("falha simulada na vitrine")
    monkeypatch.setattr(svc_rede, "rede_pelo_token_publico", _quebra)
    assert anonimo.get(f"/api/v1/publico/rede/{TOKEN_REDE}").status_code == 500

    linhas = _do_app(log_do_processo())
    acessos = [x for x in linhas if x["message"] == "http_acesso"]
    # Controle: as requisições foram, sim, registradas (senão o teste não prova nada).
    assert {x["rota"] for x in acessos} >= {
        "/api/v1/publico/{token}/painel", "/api/v1/publico/{token}/alunos/{aluno_id}",
        "/api/v1/publico/rede/{token}", "/api/v1/auth/redefinir-senha/{token}",
        "/api/v1/quest/auth/entrar-qr", "<no_match>"}
    erros = [x for x in linhas if x["message"] == "erro_nao_tratado"]
    assert len(erros) == 1
    assert erros[0]["caminho"] == "/api/v1/publico/rede/<token>"

    texto = json.dumps(linhas, ensure_ascii=False)
    for segredo in (token_painel, TOKEN_PAINEL_FALSO, TOKEN_REDE, TOKEN_RESET, TOKEN_QR):
        assert segredo not in texto, f"token no log do app: {segredo[:6]}…"


@pytest.mark.parametrize("caminho, esperado", [
    ("/api/v1/publico/abc123/painel", "/api/v1/publico/<token>/painel"),
    ("/api/v1/publico/abc123/alunos/7", "/api/v1/publico/<token>/alunos/7"),
    ("/api/v1/publico/rede/abc123", "/api/v1/publico/rede/<token>"),
    ("/api/v1/publico/rede/abc123/", "/api/v1/publico/rede/<token>/"),
    ("/api/v1/auth/redefinir-senha/abc123", "/api/v1/auth/redefinir-senha/<token>"),
    ("https://api.exemplo.test/api/v1/publico/rede/abc123?x=1",
     "https://api.exemplo.test/api/v1/publico/rede/<token>?x=1"),
    ("/api/v1/escolas/3/painel-publico/novo-token", "/api/v1/escolas/3/painel-publico/novo-token"),
])
def test_redigir_caminho_tira_o_token_de_toda_rota_publica(caminho, esperado):
    assert obs.redigir_caminho(caminho) == esperado


def test_sentry_nao_recebe_o_token_da_vitrine_da_rede():
    evento = {"request": {"url": f"https://api.exemplo.test/api/v1/publico/rede/{TOKEN_REDE}",
                          "query_string": "a=1"}}
    saida = obs.higienizar_evento_sentry(evento)
    assert TOKEN_REDE not in json.dumps(saida)
    assert saida["request"]["url"].endswith("/publico/rede/<token>")


# --- Linha de acesso do PRÓPRIO uvicorn -------------------------------------------

# A ordem do servidor, sem porta nem rede: o ``uvicorn.Config`` instala os handlers
# dele (o de acesso grava a URL crua); o ``Config.load`` importa o ``app.main`` (que
# roda o ``configurar_logging``); só então cada conexão cria o protocolo, que lê
# ``hasHandlers()``. Em processo separado porque o ``Config`` roda ``dictConfig``, que
# fecha os handlers de log do processo inteiro.
PROTOCOLO_DO_UVICORN = BOOT + (
    "import asyncio, json, logging\n"
    "import uvicorn\n"
    "from uvicorn.protocols.http.h11_impl import H11Protocol\n"
    "from uvicorn.server import ServerState\n"
    "config = uvicorn.Config('app.main:app')\n"
    "antes = logging.getLogger('uvicorn.access').hasHandlers()\n"
    "config.load()\n"
    "laco = asyncio.new_event_loop()\n"
    "p = H11Protocol(config=config, server_state=ServerState(), app_state={}, _loop=laco)\n"
    "laco.close()\n"
    "print('RESULTADO=' + json.dumps({'antes_do_app': antes,\n"
    "                                 'protocolo_grava_acesso': p.access_log}))\n"
)


def test_o_import_do_app_desliga_a_linha_de_acesso_que_o_uvicorn_configurou(sqlite_url):
    levar_a(sqlite_url, "heads")              # o import não precisa migrar: sobe mais rápido
    p = rodar(PROTOCOLO_DO_UVICORN, ambiente(sqlite_url, producao=False))
    linhas = [x for x in p.stdout.splitlines() if x.startswith("RESULTADO=")]
    assert p.returncode == 0 and linhas, (
        f"saída {p.returncode}\n{p.stdout[-3000:]}\n{p.stderr[-3000:]}")
    # Controle: antes do app, o uvicorn gravaria o acesso; depois do import, a chave
    # que o protocolo consulta em cada conexão está desligada.
    assert json.loads(linhas[-1][len("RESULTADO="):]) == {
        "antes_do_app": True, "protocolo_grava_acesso": False}


# Sobe o servidor como o comando de partida de produção (``uvicorn app.main:app
# --host ... --port ...``, SEM ``--no-access-log``), pela CLI do próprio uvicorn. O
# BOOT desliga o diagnóstico de rede do boot (Chromium e serviços externos).
SERVIR_COMO_EM_PRODUCAO = BOOT + (
    "from uvicorn.main import main\n"
    "sys.argv = ['uvicorn', 'app.main:app', '--host', '127.0.0.1',\n"
    "            '--port', os.environ['TESTE_PORTA']]\n"
    "main()\n"
)


def _porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _esperar_no_ar(base: str, proc: subprocess.Popen, arquivo, limite_s: float = 180):
    fim = time.monotonic() + limite_s
    while time.monotonic() < fim:
        if proc.poll() is not None:
            pytest.fail(f"o servidor saiu com {proc.returncode}:\n"
                        f"{arquivo.read_text(encoding='utf-8', errors='replace')[-3000:]}")
        try:
            if httpx.get(f"{base}/api/health/live", timeout=2).status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.3)
    pytest.fail("o servidor não ficou no ar a tempo")


def test_servidor_uvicorn_de_verdade_nao_grava_token_nem_busca(sqlite_url, tmp_path):
    levar_a(sqlite_url, "heads")              # o import não precisa migrar: sobe mais rápido
    porta = _porta_livre()
    arquivo = tmp_path / "servidor.log"
    env = ambiente(sqlite_url, producao=False, TESTE_PORTA=porta, PYTHONUNBUFFERED="1")
    base = f"http://127.0.0.1:{porta}"
    with open(arquivo, "w", encoding="utf-8") as saida:
        proc = subprocess.Popen([sys.executable, "-c", SERVIR_COMO_EM_PRODUCAO],
                                cwd=str(BASE_DIR), env=env, stdout=saida,
                                stderr=subprocess.STDOUT)
        try:
            _esperar_no_ar(base, proc, arquivo)
            with httpx.Client(base_url=base, timeout=15) as c:
                assert c.get(f"/api/v1/publico/{TOKEN_PAINEL_FALSO}/painel").status_code == 404
                assert c.get(f"/api/v1/publico/rede/{TOKEN_REDE}").status_code == 404
                r = c.get(f"/api/v1/auth/redefinir-senha/{TOKEN_RESET}")
                assert r.status_code == 200 and r.json() == {"valido": False}
                r = c.get("/api/v1/escolas/1/alunos", params={"busca": " ".join(BUSCA_PARTES)})
                assert r.status_code == 401
        finally:
            proc.terminate()
            proc.wait(timeout=30)
    log = arquivo.read_text(encoding="utf-8", errors="replace")

    # Controle: o servidor de verdade atendeu, e o log de acesso do APP registrou as
    # quatro requisições pelo modelo da rota (o que sai é só a linha do uvicorn).
    linhas = [json.loads(x) for x in log.splitlines() if x.startswith("{")]
    rotas = {x.get("rota") for x in linhas if x.get("message") == "http_acesso"}
    assert rotas >= {"/api/v1/publico/{token}/painel", "/api/v1/publico/rede/{token}",
                     "/api/v1/auth/redefinir-senha/{token}",
                     "/api/v1/escolas/{escola_id}/alunos"}, log[-3000:]
    for segredo in (TOKEN_PAINEL_FALSO, TOKEN_REDE, TOKEN_RESET, *BUSCA_PARTES):
        assert segredo not in log, f"segredo no log do servidor: {segredo[:6]}…"


# --- Erro de banco: os parâmetros da instrução ------------------------------------

DSN_FICTICIO = "https://chaveficticia@sentry.exemplo.test/1"


@pytest.fixture
def sentry_na_memoria(monkeypatch):
    """O ``configurar_sentry`` de verdade (com o ``before_send`` do app), só com o
    ENVIO trocado por um transporte em memória: o que ele recebe é exatamente o que
    sairia do processo. Nada vai para a rede."""
    sentry_sdk = pytest.importorskip("sentry_sdk")
    from sentry_sdk.transport import Transport

    class _Transporte(Transport):
        def __init__(self):
            super().__init__({"dsn": DSN_FICTICIO})
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

    monkeypatch.setattr(obs, "_sentry", _SentryComTransporte())
    monkeypatch.setattr(obs, "_sentry_ativo", False)
    monkeypatch.setattr(settings, "SENTRY_DSN", DSN_FICTICIO)
    obs.configurar_sentry(settings)
    try:
        yield transporte
    finally:
        # Desliga o cliente: as integrações ficam instaladas, mas sem cliente ativo
        # viram passagem direta para os outros testes.
        sentry_sdk.get_client().close()
        sentry_sdk.get_global_scope().set_client(None)


def test_erro_de_banco_nao_leva_o_nome_da_crianca_ao_log_nem_ao_sentry(
        log_do_processo, sentry_na_memoria, monkeypatch):
    """INSERT de aluno que o banco recusa (escola inexistente: FOREIGN KEY), no
    ENGINE DO APP (``app.core.database.engine``, o de produção — não o da fixture
    ``db``), no meio de uma rota de verdade: o 500 passa pelo ObservabilidadeMiddleware,
    que grava o ``erro_nao_tratado`` com o traceback e entrega a exceção ao Sentry."""
    from app.services import rede as svc_rede

    def _grava_aluno_em_escola_que_nao_existe(*_a, **_k):
        with Session(database.engine) as sessao:
            sessao.add(Aluno(escola_id=987654321, nome=NOME_FICTICIO))
            sessao.flush()
    monkeypatch.setattr(svc_rede, "rede_pelo_token_publico",
                        _grava_aluno_em_escola_que_nao_existe)

    anonimo = TestClient(app, raise_server_exceptions=False)
    r = anonimo.get(f"/api/v1/publico/rede/{TOKEN_REDE}")
    assert r.status_code == 500 and NOME_FICTICIO not in r.text

    # Log: a linha de erro existe e leva o SQL (controle), mas não o valor.
    linhas = _do_app(log_do_processo())
    erros = [x for x in linhas if x["message"] == "erro_nao_tratado"]
    assert len(erros) == 1
    assert "INSERT INTO alunos" in erros[0]["excecao"]
    assert "SQL parameters hidden" in erros[0]["excecao"]
    texto_log = json.dumps(linhas, ensure_ascii=False)
    for parte in NOME_FICTICIO.split():
        assert parte not in texto_log, f"pedaço do nome no log: {parte}"

    # Sentry: o evento com a exceção saiu (controle) e nada do que saiu leva o nome.
    eventos = [item.payload.json for env in sentry_na_memoria.envelopes
               for item in env.items if item.type == "event"]
    valores = [v.get("value") or "" for ev in eventos
               for v in (ev.get("exception") or {}).get("values", [])]
    assert any("INSERT INTO alunos" in v for v in valores), eventos
    tudo = b"".join(env.serialize() for env in sentry_na_memoria.envelopes).decode(
        "utf-8", errors="replace")
    for parte in NOME_FICTICIO.split():
        assert parte not in tudo, f"pedaço do nome no Sentry: {parte}"


@pytest.mark.parametrize("url", ["sqlite:///constela.db",
                                 "postgresql+psycopg://usuario@localhost/constela_teste"])
def test_os_dois_ramos_do_engine_escondem_os_parametros(url):
    """O ramo PostgreSQL (produção) não roda no SQLite dos testes: confere-se a opção
    que ele passa ao ``create_engine``, e o engine vivo deste processo."""
    assert database.opcoes_do_engine(url)["hide_parameters"] is True
    assert database.engine.hide_parameters is True
