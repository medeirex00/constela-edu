"""CORS: o default (no código) inclui as origens de produção cross-origin.

Regressão do B1 (go-live): um deploy Vercel+Railway sem CORS_ORIGINS no
ambiente NÃO pode subir bloqueando todas as chamadas do navegador. O default
vive no código (convenção §14, como PUBLIC_BASE_URL/QUEST_BASE_URL) — setar
CORS_ORIGINS no provedor passa a ser opcional (para restringir).

CORS por ENV (A3, lacuna L4): com ENV=producao as origens de desenvolvimento local
(localhost e subdomínios, loopback, 0.0.0.0) e a origem opaca 'null' saem da lista —
do padrão e de um CORS_ORIGINS explícito —, o app desktop (Tauri) fica, e o curinga
'*' recusa o boot (tests/test_config_producao.py). Em dev nada muda.
"""
import json
import logging
import secrets

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, origem_de_desenvolvimento, registrar_avisos_de_configuracao
from app.main import app
from tests._infra_comum import BOOT, ambiente, levar_a, pg_url, rodar  # noqa: F401 — fixture

_cliente = TestClient(app)
_PG_FICTICIO = "postgresql+psycopg://app@127.0.0.1:55432/cors_producao_test"
_PRODUCAO_PADRAO = ["https://www.constelaedu.com", "https://quest.constelaedu.com",
                    "tauri://localhost", "http://tauri.localhost", "https://tauri.localhost"]


def _settings(env: str, **extra) -> Settings:
    """Settings novo, sem .env; nenhuma conexão é aberta (a URL só passa pela recusa
    do SQLite em produção)."""
    return Settings(_env_file=None, ENV=env, DATABASE_URL=_PG_FICTICIO,
                    SECRET_KEY=secrets.token_urlsafe(48),
                    DATA_ENCRYPTION_KEY=secrets.token_urlsafe(48), **extra)


@pytest.fixture
def sem_cors_no_ambiente(monkeypatch):
    for nome in ("CORS_ORIGINS", "CORS_ORIGINS_REMOVIDAS", "ENV", "DOCS_HABILITADOS"):
        monkeypatch.delenv(nome, raising=False)


def _preflight(origem: str):
    return _cliente.options(
        "/api/v1/quest/auth/entrar",
        headers={"Origin": origem, "Access-Control-Request-Method": "POST"},
    )


def test_cors_default_inclui_producao_e_preserva_dev_e_desktop():
    # Settings() é reavaliado do zero: prova o DEFAULT, independente de env.
    from app.core.config import Settings

    origens = Settings().CORS_ORIGINS
    assert "https://www.constelaedu.com" in origens
    assert "https://quest.constelaedu.com" in origens
    # Regressão: dev web e desktop (Tauri) continuam permitidos.
    assert "http://localhost:5173" in origens
    assert "http://127.0.0.1:5173" in origens
    assert "tauri://localhost" in origens


def test_cors_preflight_permite_front_de_producao():
    r = _preflight("https://www.constelaedu.com")
    assert r.headers.get("access-control-allow-origin") == "https://www.constelaedu.com"
    assert r.headers.get("access-control-allow-credentials") == "true"


def test_cors_preflight_permite_quest_de_producao():
    r = _preflight("https://quest.constelaedu.com")
    assert r.headers.get("access-control-allow-origin") == "https://quest.constelaedu.com"


def test_cors_preflight_nega_origem_desconhecida():
    r = _preflight("https://evil.example.com")
    # Origem fora da allowlist não recebe o cabeçalho — o navegador bloqueia.
    assert r.headers.get("access-control-allow-origin") is None


# --- CORS por ENV (A3, lacuna L4) -------------------------------------------------

@pytest.mark.parametrize("origem,de_dev", [
    ("http://localhost:5173", True),
    ("https://localhost", True),
    ("http://LOCALHOST:3000", True),
    ("http://127.0.0.1:5173", True),
    ("http://127.0.0.2:8080", True),
    ("http://[::1]:5173", True),
    ("http://0.0.0.0:8000", True),
    (" http://localhost:5173 ", True),
    ("http://app.localhost:5173", True),   # subdomínio de localhost = loopback
    ("https://a.b.LOCALHOST", True),
    ("http://localhost.:5173", True),      # ponto final do FQDN
    ("null", True),                        # origem opaca (arquivo, iframe em sandbox)
    (" NULL ", True),
    ("tauri://localhost", False),          # app desktop: esquema próprio
    ("http://tauri.localhost", False),     # app desktop: host do WebView
    ("https://tauri.localhost", False),
    ("http://tauri.localhost.", False),
    ("https://nulL.exemplo.com", False),
    ("https://www.constelaedu.com", False),
    ("https://localhost.exemplo.com", False),
    ("http://192.168.0.10:5173", False),   # rede local não é loopback
    ("*", False),                          # curinga: recusa o boot, não é filtrado
    ("", False),
    ("http://[::1", False),                # malformada não derruba
])
def test_origem_de_desenvolvimento(origem, de_dev):
    assert origem_de_desenvolvimento(origem) is de_dev


def test_producao_tira_as_origens_de_dev_do_padrao(sem_cors_no_ambiente):
    s = _settings("producao")
    assert s.CORS_ORIGINS == _PRODUCAO_PADRAO
    assert s.CORS_ORIGINS_REMOVIDAS == ["http://localhost:5173", "http://127.0.0.1:5173"]


def test_producao_tira_localhost_de_um_cors_explicito(sem_cors_no_ambiente):
    s = _settings("producao", CORS_ORIGINS=[
        "https://escola.exemplo.gov.br", "http://localhost:3000", "https://localhost",
        "http://127.0.0.2:8080", "http://[::1]:5173", "http://0.0.0.0:8000",
        "tauri://localhost", "http://tauri.localhost"])
    assert s.CORS_ORIGINS == ["https://escola.exemplo.gov.br", "tauri://localhost",
                              "http://tauri.localhost"]
    assert len(s.CORS_ORIGINS_REMOVIDAS) == 5


def test_producao_tira_null_e_subdominio_de_localhost(sem_cors_no_ambiente):
    """'null' (origem opaca: qualquer arquivo local ou iframe em sandbox a manda) e
    ``*.localhost`` (loopback nos navegadores) passavam no CORS de produção, com
    allow_credentials ligado. O host do app desktop (tauri.localhost) fica."""
    s = _settings("producao", CORS_ORIGINS=[
        "null", "https://www.constelaedu.com", "http://app.localhost:5173",
        "https://tauri.localhost"])
    assert s.CORS_ORIGINS == ["https://www.constelaedu.com", "https://tauri.localhost"]
    assert s.CORS_ORIGINS_REMOVIDAS == ["null", "http://app.localhost:5173"]
    assert "null" in _settings("dev", CORS_ORIGINS=["null"]).CORS_ORIGINS


def test_producao_pela_variavel_de_ambiente(sem_cors_no_ambiente, monkeypatch):
    """O caminho real (painel do Railway): CORS_ORIGINS em array JSON."""
    monkeypatch.setenv("CORS_ORIGINS",
                       '["https://www.constelaedu.com", "http://localhost:5173"]')
    assert _settings("producao").CORS_ORIGINS == ["https://www.constelaedu.com"]
    assert "http://localhost:5173" in _settings("dev").CORS_ORIGINS


def test_dev_mantem_a_lista_inteira(sem_cors_no_ambiente):
    s = _settings("dev")
    assert "http://localhost:5173" in s.CORS_ORIGINS
    assert "http://127.0.0.1:5173" in s.CORS_ORIGINS
    assert s.CORS_ORIGINS_REMOVIDAS == []


def test_removidas_nao_vem_do_ambiente(sem_cors_no_ambiente):
    assert _settings("dev", CORS_ORIGINS_REMOVIDAS=["https://x.exemplo"]
                     ).CORS_ORIGINS_REMOVIDAS == []
    assert _settings("producao", CORS_ORIGINS=["https://www.constelaedu.com"],
                     CORS_ORIGINS_REMOVIDAS=["https://x.exemplo"]
                     ).CORS_ORIGINS_REMOVIDAS == []


def test_log_do_boot_de_producao_diz_quais_sairam(sem_cors_no_ambiente, caplog):
    s = _settings("producao")
    logger = logging.getLogger("constela.teste_cors")
    with caplog.at_level(logging.INFO, logger="constela.teste_cors"):
        assert registrar_avisos_de_configuracao(logger, s) == 0     # nenhum aviso
    registros = [r for r in caplog.records if "CORS de produção" in r.getMessage()]
    assert len(registros) == 1 and registros[0].levelno == logging.INFO
    assert "http://localhost:5173" in registros[0].getMessage()
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="constela.teste_cors"):
        registrar_avisos_de_configuracao(logger, _settings("dev"))
    assert not [r for r in caplog.records if "CORS de produção" in r.getMessage()]


_PREFLIGHT = BOOT + (
    "import json\n"
    "from fastapi.testclient import TestClient\n"
    "from app.main import app\n"
    "c = TestClient(app)\n"
    "out = {}\n"
    "for origem in ('https://www.constelaedu.com', 'https://quest.constelaedu.com',\n"
    "               'tauri://localhost', 'http://localhost:5173', 'http://127.0.0.1:5173'):\n"
    "    r = c.options('/api/v1/auth/login', headers={'Origin': origem,\n"
    "                  'Access-Control-Request-Method': 'POST'})\n"
    "    out[origem] = r.headers.get('access-control-allow-origin')\n"
    "print('RESULTADO=' + json.dumps(out))\n"
)


@pytest.mark.postgres
def test_processo_de_producao_nega_preflight_de_localhost(pg_url):
    """Processo novo com ENV=producao (como o uvicorn no Railway), sem CORS_ORIGINS no
    ambiente: o front de produção e o app desktop passam; localhost não."""
    levar_a(pg_url, "heads")
    env = ambiente(pg_url, True)
    env.pop("CORS_ORIGINS", None)
    p = rodar(_PREFLIGHT, env)
    linhas = [x for x in p.stdout.splitlines() if x.startswith("RESULTADO=")]
    assert p.returncode == 0 and linhas, f"{p.stdout[-3000:]}\n{p.stderr[-3000:]}"
    r = json.loads(linhas[-1][len("RESULTADO="):])
    for origem in ("https://www.constelaedu.com", "https://quest.constelaedu.com",
                   "tauri://localhost"):
        assert r[origem] == origem
    assert r["http://localhost:5173"] is None and r["http://127.0.0.1:5173"] is None
    assert "CORS de produção sem as origens de desenvolvimento local" in p.stdout + p.stderr


def test_cors_expoe_o_nome_do_arquivo_baixado():
    """Web (Vercel) e API (Railway) são origens diferentes: sem expor o
    Content-Disposition, o navegador esconde o nome do PDF/planilha do JavaScript
    e o download cai no nome padrão do cliente."""
    r = _cliente.get("/api/health/live", headers={"Origin": "https://www.constelaedu.com"})
    expostos = r.headers.get("access-control-expose-headers", "").lower()
    assert "content-disposition" in expostos
    assert "x-request-id" in expostos
