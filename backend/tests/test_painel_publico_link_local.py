"""Base do link do Painel Público da escola e da vitrine da rede: QUEM DECIDE É O SERVIDOR.

Numa instalação LOCAL (demo, ambiente de teste) o link e o QR apontavam para o domínio
publicado (``PUBLIC_BASE_URL``, padrão = produção), onde o token local não existe — a
vitrine "não abria". O contrato de ``publico.base_do_link_publico``:
  1. ``PUBLIC_BASE_URL`` definido de propósito (ambiente ou ``.env``) vence SEMPRE — é o
     endereço escolhido para os outros aparelhos; no celular, ``localhost`` é o celular;
  2. sem ele, a origem da tela, SÓ em loopback e exatamente ``esquema://host[:porta]``,
     remontada do host e da porta validados — nunca um domínio de fora no link;
  3. senão, o domínio publicado.
Todo endpoint que devolve o link (GET/PUT/novo-token/QR da escola, GET/PUT da vitrine da
rede) aceita a mesma ``origem`` na consulta e monta o link pela mesma regra."""
import pytest
import segno
from fastapi.testclient import TestClient

from app.core.config import Settings, settings
from app.core.security import hash_senha
from app.main import app
from app.models import Rede, Usuario
from app.routers import publico
from app.routers.publico import _base_configurada, base_do_link_publico

from .test_publico import _ativar_painel

API = "/api/v1"
LOCAL = "http://localhost:8050"
LOCAL_NA_CONSULTA = "?origem=http%3A%2F%2Flocalhost%3A8050"
# Valor FICTÍCIO de quem definiu PUBLIC_BASE_URL: o IP do servidor na rede local.
CONFIGURADA = "http://192.168.0.10:8040"
# O mesmo painel, editado sem mudar nada (o painel ativo preserva o token).
_EDICAO = {"ativo": True, "slides": ["ranking", "destaques"], "intervalo_s": 8,
           "max_posicoes": 5}


def _publicado() -> str:
    return settings.PUBLIC_BASE_URL.rstrip("/")


@pytest.fixture()
def sem_base_configurada(monkeypatch):
    """PUBLIC_BASE_URL no padrão do código, seja qual for o ambiente de quem roda os testes."""
    monkeypatch.setattr(publico, "_base_configurada", lambda: None)


@pytest.fixture()
def base_configurada(monkeypatch):
    """PUBLIC_BASE_URL definido de propósito pelo operador."""
    monkeypatch.setattr(publico, "_base_configurada", lambda: CONFIGURADA)


# --- A regra ---------------------------------------------------------------------------

@pytest.mark.usefixtures("sem_base_configurada")
@pytest.mark.parametrize("origem, base", [
    ("http://localhost:8050", "http://localhost:8050"),
    ("http://secretaria.localhost:8050", "http://secretaria.localhost:8050"),
    ("http://127.0.0.1:8040", "http://127.0.0.1:8040"),
    ("http://[::1]:8050", "http://[::1]:8050"),
    ("https://localhost", "https://localhost"),
    ("http://localhost:8050/", "http://localhost:8050"),     # a barra final sai
])
def test_origem_de_loopback_vira_a_base_do_link(origem, base):
    assert base_do_link_publico(origem) == base


@pytest.mark.usefixtures("sem_base_configurada")
@pytest.mark.parametrize("origem", [
    None, "", "https://evil.example", "http://localhost.evil.example",
    "http://evil.example/.localhost", "javascript:alert(1)", "ftp://localhost",
    "http://localhost:8050/caminho", "http://alguem@localhost:8050", "http://localhost:8050/?x=1",
    "http://localhost:8050#x", "http://10.0.0.5:8050",
    # O app de desktop no Windows: fala com o servidor de verdade, o link é o publicado.
    "http://tauri.localhost", "https://tauri.localhost", "http://tauri.localhost.",
    "não é url",
    # Barra invertida: o Python lê um host de loopback, o navegador lê evil.com.
    "http://evil.com\\.localhost", "http://:@evil.com\\@localhost", "http://localhost:8050\\",
    # Credencial, mesmo vazia; porta fora da faixa ou escrita de outro jeito.
    "http://:x@localhost:8050", "http://:@localhost:8050", "http://localhost:99999",
    "http://localhost:08050", "http://localhost:",
    # O navegador manda a origem em minúsculas: qualquer maiúscula não veio da tela.
    "http://LOCALHOST:8050", "http://Localhost:8050", "HTTP://localhost:8050",
    # Host com código percentual ou fora do ASCII.
    "http://evil.com%2f.localhost", "http://évil.localhost",
])
def test_qualquer_outra_origem_e_ignorada(origem):
    assert base_do_link_publico(origem) == _publicado()


@pytest.mark.usefixtures("base_configurada")
@pytest.mark.parametrize("origem", [
    None, "http://localhost:8050", "http://127.0.0.1:8040", "http://[::1]:8050",
    "https://evil.example",
])
def test_public_base_url_configurado_vence_a_origem_de_loopback(origem):
    assert base_do_link_publico(origem) == CONFIGURADA


def test_public_base_url_do_ambiente_conta_como_configurado(monkeypatch):
    """O pydantic-settings marca em ``model_fields_set`` o valor que veio do ambiente (ou do
    ``.env``); o padrão do código fica de fora. É o que ``_base_configurada`` lê."""
    monkeypatch.setenv("PUBLIC_BASE_URL", f"{CONFIGURADA}/")
    lida = Settings(_env_file=None)
    assert "PUBLIC_BASE_URL" in lida.model_fields_set
    monkeypatch.setattr(publico, "settings", lida)
    assert _base_configurada() == CONFIGURADA
    assert base_do_link_publico(LOCAL) == CONFIGURADA

    monkeypatch.delenv("PUBLIC_BASE_URL")
    padrao = Settings(_env_file=None)
    assert "PUBLIC_BASE_URL" not in padrao.model_fields_set
    monkeypatch.setattr(publico, "settings", padrao)
    assert _base_configurada() is None
    assert base_do_link_publico(LOCAL) == LOCAL
    assert base_do_link_publico(None) == padrao.PUBLIC_BASE_URL.rstrip("/")


# --- Painel Público da escola: GET, PUT, novo-token e QR -------------------------------

def _url_do_qr(monkeypatch, cliente, escola_id, consulta=""):
    vistos = []
    original = segno.make

    def espiao(conteudo, *a, **k):
        vistos.append(conteudo)
        return original(conteudo, *a, **k)

    monkeypatch.setattr(segno, "make", espiao)
    r = cliente.get(f"{API}/escolas/{escola_id}/painel-publico/qr{consulta}")
    assert r.status_code == 200 and b"<svg" in r.content
    return vistos[-1]


def _urls_da_escola(monkeypatch, cliente, escola_id, consulta) -> tuple[str, list[str]]:
    """O token novo e o link devolvido por GET, PUT, novo-token e QR — todos com a mesma
    consulta. O novo-token troca o token: o QR depois dele já leva o novo."""
    base = f"{API}/escolas/{escola_id}/painel-publico"
    urls = []
    r = cliente.get(f"{base}{consulta}")
    assert r.status_code == 200, r.text
    urls.append(r.json()["url"])
    r = cliente.put(f"{base}{consulta}", json=_EDICAO)
    assert r.status_code == 200, r.text
    urls.append(r.json()["url"])
    r = cliente.post(f"{base}/novo-token{consulta}")
    assert r.status_code == 200, r.text
    urls.append(r.json()["url"])
    token = r.json()["url"].rsplit("/", 1)[-1]
    urls.append(_url_do_qr(monkeypatch, cliente, escola_id, consulta))
    return token, urls


@pytest.mark.usefixtures("sem_base_configurada")
def test_link_da_escola_usa_a_origem_local_em_todos_os_endpoints(monkeypatch, cliente, db,
                                                                 escola_completa):
    escola_id = escola_completa["escola"].id
    token = _ativar_painel(cliente, escola_id)
    novo, urls = _urls_da_escola(monkeypatch, cliente, escola_id, LOCAL_NA_CONSULTA)
    assert novo != token
    assert urls == [f"{LOCAL}/p/{token}", f"{LOCAL}/p/{token}",
                    f"{LOCAL}/p/{novo}", f"{LOCAL}/p/{novo}"]


@pytest.mark.usefixtures("sem_base_configurada")
@pytest.mark.parametrize("consulta", [
    "", "?origem=https%3A%2F%2Fevil.example", "?origem=http%3A%2F%2Fevil.com%5C.localhost",
])
def test_link_da_escola_sem_origem_ou_com_origem_de_fora_usa_o_dominio_publicado(
        monkeypatch, cliente, db, escola_completa, consulta):
    escola_id = escola_completa["escola"].id
    token = _ativar_painel(cliente, escola_id)
    novo, urls = _urls_da_escola(monkeypatch, cliente, escola_id, consulta)
    assert urls == [f"{_publicado()}/p/{token}", f"{_publicado()}/p/{token}",
                    f"{_publicado()}/p/{novo}", f"{_publicado()}/p/{novo}"]


@pytest.mark.usefixtures("base_configurada")
def test_link_da_escola_com_public_base_url_configurado_ignora_a_origem_local(
        monkeypatch, cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    token = _ativar_painel(cliente, escola_id)
    novo, urls = _urls_da_escola(monkeypatch, cliente, escola_id, LOCAL_NA_CONSULTA)
    assert urls == [f"{CONFIGURADA}/p/{token}", f"{CONFIGURADA}/p/{token}",
                    f"{CONFIGURADA}/p/{novo}", f"{CONFIGURADA}/p/{novo}"]


# --- Vitrine da rede: GET e PUT -------------------------------------------------------

def _secretaria(db) -> tuple[TestClient, int, int]:
    """Cliente da Secretaria de uma rede, o id dela e o de OUTRA rede (fictícias)."""
    rede, outra = Rede(nome="Rede Vitrine", status="ativa"), Rede(nome="Outra", status="ativa")
    db.add_all([rede, outra])
    db.flush()
    db.add(Usuario(nome="Sec Vitrine", email="sec@vitrine.gov",
                   senha_hash=hash_senha("s3nh4vitrine1"), cargo="coordenador",
                   rede_id=rede.id))
    db.commit()
    cliente = TestClient(app)
    r = cliente.post(f"{API}/auth/login",
                     data={"username": "sec@vitrine.gov", "password": "s3nh4vitrine1"})
    assert r.status_code == 200, r.text
    cliente.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return cliente, rede.id, outra.id


@pytest.mark.usefixtures("sem_base_configurada")
def test_vitrine_da_rede_usa_a_origem_local_no_get_e_no_put(db):
    cliente, rede_id, outra_id = _secretaria(db)
    rota = f"{API}/redes/{rede_id}/publico"
    r = cliente.put(f"{rota}{LOCAL_NA_CONSULTA}", json={"ativo": True})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    assert r.json()["url"] == f"{LOCAL}/rede/p/{token}"
    assert cliente.get(f"{rota}{LOCAL_NA_CONSULTA}").json()["url"] == f"{LOCAL}/rede/p/{token}"
    # Sem origem ou com origem de fora: o domínio publicado.
    for consulta in ("", "?origem=https%3A%2F%2Fevil.example",
                     "?origem=http%3A%2F%2F%3A%40evil.com%5C%40localhost"):
        assert cliente.get(f"{rota}{consulta}").json()["url"] == f"{_publicado()}/rede/p/{token}"
    # A origem não abre a vitrine de outra rede (a autorização é a mesma).
    assert cliente.get(f"{API}/redes/{outra_id}/publico{LOCAL_NA_CONSULTA}").status_code == 403
    # Desligada, não há link.
    r = cliente.put(f"{rota}{LOCAL_NA_CONSULTA}", json={"ativo": False})
    assert r.status_code == 200 and r.json()["url"] is None


@pytest.mark.usefixtures("base_configurada")
def test_vitrine_da_rede_com_public_base_url_configurado_ignora_a_origem_local(db):
    cliente, rede_id, _ = _secretaria(db)
    rota = f"{API}/redes/{rede_id}/publico"
    r = cliente.put(f"{rota}{LOCAL_NA_CONSULTA}", json={"ativo": True})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    assert r.json()["url"] == f"{CONFIGURADA}/rede/p/{token}"
    r = cliente.get(f"{rota}{LOCAL_NA_CONSULTA}")
    assert r.json()["url"] == f"{CONFIGURADA}/rede/p/{token}"
