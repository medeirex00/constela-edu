"""Endereço de login das "opções avançadas" (extra['url_login']) × SSRF.

O Chromium do SERVIDOR abre esse endereço. Antes, um coordenador de escola
gravava qualquer coisa (http://169.254.169.254/..., http://127.0.0.1:8000/...,
file:///etc/passwd, página de terceiro com JavaScript) e o robô navegava até lá
em toda coleta; o endereço final ainda voltava na mensagem e no ``ultimo_erro``.

Agora:
  * ao SALVAR, ``extra`` só aceita as chaves conhecidas (url_login, sso) e o
    url_login só vale com https e host do site de uma plataforma (422 senão, nada
    gravado, nada aberto, sem repetir o endereço na mensagem);
  * antes de NAVEGAR, o conector confere de novo contra o domínio DELE (cobre a
    credencial gravada antes da trava): fora da lista, nada é aberto;
  * endereço de fora da lista (redirecionamento) não volta na mensagem nem no log.

Navegador falso, dados fictícios, sem rede.
"""
import asyncio

import pytest

from app.core.security import hash_senha
from app.models import Usuario
from app.sync import connectors, vault
from app.sync.connectors.base import url_na_lista
from app.sync.connectors.elefante import DOMINIOS_LOGIN as DOM_ELEFANTE
from app.sync.connectors.elefante import _URL_LOGIN as URL_ELEFANTE
from app.sync.connectors.elefante import ConectorElefante
from app.sync.connectors.matific import DOMINIOS_LOGIN as DOM_MATIFIC
from app.sync.connectors.matific import _URL_LOGIN as URL_MATIFIC
from app.sync.connectors.matific import ConectorMatific
from app.sync.interfaces import Contexto, Credenciais

API = "/api/v1"
CLASSES = {"elefante": ConectorElefante, "matific": ConectorMatific}
TODOS_OS_DOMINIOS = DOM_ELEFANTE + DOM_MATIFIC

# Endereços que o robô NUNCA pode abrir (nem gravar).
ALVOS_FORA = [
    "http://169.254.169.254/latest/meta-data/",          # metadados da nuvem
    "http://127.0.0.1:8000/metrics",                      # a própria API
    "file:///etc/passwd",
    "https://atacante.invalid/falso-login.html",          # página de terceiro
    "https://127.0.0.1/",
    "https://10.0.0.5/interno",
    "http://login.elefanteletrado.com.br/manager",        # host certo, sem https
    "http://www.matific.com/bra/pt-br/login-page/",
    "https://login.elefanteletrado.com.br@atacante.invalid/",   # usuário@host
    "https://atacante.invalid\\.matific.com/",            # Chromium lê "\" como "/"
    "https://atacante.invalid\\.elefanteletrado.com.br/",
    "https://matific.com.atacante.invalid/",              # sufixo enganoso
    "https://elefanteletrado.com.br.atacante.invalid/",
    "https://falsomatific.com/",                          # sem o ponto do subdomínio
    "https://www.matific.com:8443/",                      # porta fora do https padrão
    "https://www.matific.com /bra/",                      # espaço no meio
    "https://[::1]/",
    "https://www.matífic.com/",                     # Unicode no host
    "//www.matific.com/bra/",                             # sem esquema
    "javascript:alert(1)",
    "data:text/html,<script>fetch('http://10.0.0.1')</script>",
]


class NavRegistra:
    """Navegador falso que ANOTA cada endereço aberto.

    ``atual`` fixa o que ``url_atual`` devolve (um redirecionamento); sem ele,
    devolve o último endereço aberto. ``formulario``: o formulário de login
    aparece (e a área logada nunca), para chegar ao fim do fluxo."""

    def __init__(self, *, atual: str | None = None, formulario: bool = False):
        self.visitadas: list[str] = []
        self.atual, self.formulario = atual, formulario

    async def ir_para(self, url): self.visitadas.append(url)
    async def url_atual(self):
        return self.atual or (self.visitadas[-1] if self.visitadas else "about:blank")
    async def visivel(self, seletor):
        return self.formulario and "password" in seletor.lower()
    async def esperar(self, seletor, timeout_s=20):
        return self.formulario and "logout" not in seletor
    async def preencher(self, seletor, valor): pass
    async def clicar(self, seletor): pass
    async def fechar(self): pass


def _fabrica(nav):
    async def fab(**_kw):
        return nav
    return fab


def _contexto(registros=None):
    return Contexto(escola_id=1, execucao_id=None,
                    log=lambda etapa, nivel, msg: (registros is not None
                                                   and registros.append(msg)))


def _registrar_conector_falso(monkeypatch, plataforma, nav):
    """Conector REAL (com os domínios dele) sobre o navegador falso."""
    monkeypatch.setitem(connectors._REGISTRO, plataforma,
                        CLASSES[plataforma](_fabrica(nav)))


@pytest.fixture()
def coordenador(db, escola_completa):
    """Coordenador da escola (não é admin global): quem o achado mostrou explorando."""
    from fastapi.testclient import TestClient

    from app.main import app

    db.add(Usuario(escola_id=escola_completa["escola"].id, nome="Coord Fictício",
                   email="coord@x.invalid", senha_hash=hash_senha("s3nh4"),
                   cargo="coordenador"))
    db.commit()
    cli = TestClient(app)
    r = cli.post(f"{API}/auth/login",
                 data={"username": "coord@x.invalid", "password": "s3nh4"})
    assert r.status_code == 200, r.text
    cli.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return cli


def _mensagens_422(r) -> list[str]:
    assert r.status_code == 422, r.text
    return [str(e.get("msg", "")) for e in r.json()["detail"]]


# ---------------------------------------------------------------------------
# A regra: só https e host do site da plataforma
# ---------------------------------------------------------------------------
def test_endereco_oficial_e_subdominios_da_plataforma_valem():
    assert url_na_lista(URL_ELEFANTE, DOM_ELEFANTE)
    assert url_na_lista(URL_MATIFIC, DOM_MATIFIC)
    assert url_na_lista("https://login.elefanteletrado.com.br/welcome", DOM_ELEFANTE)
    assert url_na_lista("https://admin.elefanteletrado.com.br/reports/menu", DOM_ELEFANTE)
    assert url_na_lista("HTTPS://WWW.MATIFIC.COM/bra/pt-br/login-page/", DOM_MATIFIC)
    assert url_na_lista("https://www.matific.com:443/bra/pt-br/login-page/", DOM_MATIFIC)
    assert url_na_lista("https://matific.com/", DOM_MATIFIC)


@pytest.mark.parametrize("alvo", ALVOS_FORA)
def test_endereco_fora_do_site_da_plataforma_nao_vale(alvo):
    assert url_na_lista(alvo, TODOS_OS_DOMINIOS) is False


def test_endereco_de_uma_plataforma_nao_vale_na_outra():
    assert url_na_lista(URL_MATIFIC, DOM_ELEFANTE) is False
    assert url_na_lista(URL_ELEFANTE, DOM_MATIFIC) is False
    assert url_na_lista(URL_ELEFANTE, ()) is False        # conector sem domínios
    assert url_na_lista(None, DOM_MATIFIC) is False
    assert url_na_lista({"url": URL_MATIFIC}, DOM_MATIFIC) is False
    assert url_na_lista("https://www.matific.com/" + "a" * 600, DOM_MATIFIC) is False


# ---------------------------------------------------------------------------
# Ao salvar (PUT /credenciais): recusa antes de gravar e antes de abrir
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("plataforma", ["elefante", "matific"])
@pytest.mark.parametrize("alvo", [
    "http://169.254.169.254/latest/meta-data/",
    "http://127.0.0.1:8000/metrics",
    "file:///etc/passwd",
    "https://atacante.invalid/falso-login.html",
    "https://atacante.invalid\\.matific.com/",
])
def test_salvar_recusa_url_login_fora_do_site(coordenador, db, escola_completa,
                                               monkeypatch, plataforma, alvo):
    eid = escola_completa["escola"].id
    nav = NavRegistra()
    _registrar_conector_falso(monkeypatch, plataforma, nav)

    r = coordenador.put(f"{API}/escolas/{eid}/sync/credenciais/{plataforma}",
                        json={"usuario": "robo@x.invalid", "senha": "senha-ficticia",
                              "extra": {"url_login": alvo}})
    msgs = _mensagens_422(r)
    assert nav.visitadas == []                                # o robô não abriu nada
    db.expire_all()
    assert vault.obter_linha(db, eid, plataforma) is None     # nada foi gravado
    texto = " ".join(msgs)
    assert alvo not in texto and "atacante" not in texto      # não repete o endereço
    assert "https://" in texto and "matific.com" in texto and "elefanteletrado.com.br" in texto


@pytest.mark.parametrize("extra", [
    {"qualquer": "x" * 5000},
    {"url_login": URL_ELEFANTE, "outra_chave": "valor"},
    {"matific_start_date": "2026-01-01", "matific_end_date": "2026-01-31"},
    {"matific_duration": "this-year&school_id=outra"},
    {"sso": "x" * 500},
    {"url_login": 12345},
])
def test_salvar_recusa_opcao_avancada_desconhecida_ou_invalida(
        coordenador, db, escola_completa, monkeypatch, extra):
    eid = escola_completa["escola"].id
    nav = NavRegistra()
    _registrar_conector_falso(monkeypatch, "elefante", nav)

    r = coordenador.put(f"{API}/escolas/{eid}/sync/credenciais/elefante",
                        json={"usuario": "robo@x.invalid", "senha": "senha-ficticia",
                              "extra": extra})
    msgs = _mensagens_422(r)
    assert all("x" * 50 not in m for m in msgs)               # não ecoa a chave/valor
    assert nav.visitadas == []
    db.expire_all()
    assert vault.obter_linha(db, eid, "elefante") is None


@pytest.mark.parametrize("plataforma,url", [
    ("elefante", "https://login.elefanteletrado.com.br/welcome"),
    ("matific", "https://www.matific.com/bra/pt-br/login-page/"),
])
def test_salvar_aceita_url_login_do_site_da_plataforma(coordenador, db, escola_completa,
                                                       monkeypatch, plataforma, url):
    """A opção continua servindo ao que foi feita: apontar outra página de login
    do PRÓPRIO site quando a plataforma muda o endereço."""
    eid = escola_completa["escola"].id
    nav = NavRegistra()
    _registrar_conector_falso(monkeypatch, plataforma, nav)

    r = coordenador.put(f"{API}/escolas/{eid}/sync/credenciais/{plataforma}",
                        json={"usuario": "robo@x.invalid", "senha": "senha-ficticia",
                              "extra": {"url_login": f"  {url}  ", "sso": ""}})
    assert r.status_code == 200, r.text
    assert nav.visitadas == [url]
    db.expire_all()
    assert vault.obter_credencial(db, eid, plataforma).extra == {"url_login": url}


def test_salvar_sem_opcoes_avancadas_segue_igual(coordenador, db, escola_completa,
                                                 monkeypatch):
    eid = escola_completa["escola"].id
    nav = NavRegistra()
    _registrar_conector_falso(monkeypatch, "matific", nav)
    r = coordenador.put(f"{API}/escolas/{eid}/sync/credenciais/matific",
                        json={"usuario": "robo@x.invalid", "senha": "senha-ficticia"})
    assert r.status_code == 200, r.text
    assert nav.visitadas == [URL_MATIFIC]                     # o endereço oficial
    r = coordenador.put(f"{API}/escolas/{eid}/sync/credenciais/matific",
                        json={"usuario": "robo@x.invalid", "senha": "senha-ficticia",
                              "extra": {"url_login": "   "}})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert vault.obter_credencial(db, eid, "matific").extra == {}


# ---------------------------------------------------------------------------
# Antes de navegar: a credencial JÁ GRAVADA (antes da trava) também é conferida
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("plataforma", ["elefante", "matific"])
@pytest.mark.parametrize("alvo", [
    "http://169.254.169.254/latest/meta-data/",
    "file:///etc/passwd",
    "https://atacante.invalid/falso-login.html",
])
def test_credencial_gravada_com_url_fora_do_site_nao_e_aberta(
        coordenador, db, escola_completa, monkeypatch, plataforma, alvo):
    eid = escola_completa["escola"].id
    # Grava DIRETO no cofre, como ficou quem salvou antes desta correção.
    vault.salvar_credencial(db, eid, plataforma, Credenciais(
        usuario="robo@x.invalid", senha="senha-ficticia", extra={"url_login": alvo}))
    db.commit()
    nav = NavRegistra()
    _registrar_conector_falso(monkeypatch, plataforma, nav)

    r = coordenador.post(f"{API}/escolas/{eid}/sync/credenciais/{plataforma}/testar")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["ok"] is False and corpo["codigo"] == "pagina_login"
    assert nav.visitadas == []                                # nada foi aberto
    assert alvo not in corpo["mensagem"] and "atacante" not in corpo["mensagem"]
    assert "https://" in corpo["mensagem"] and "em branco" in corpo["mensagem"]

    st = coordenador.get(f"{API}/escolas/{eid}/sync/status").json()
    card = next(p for p in st["plataformas"] if p["plataforma"] == plataforma)
    assert card["credencial_status"] == "nao_validada"        # não é "senha errada"
    assert alvo not in (card["ultimo_erro"] or "")


def test_endereco_do_matific_nao_e_aberto_pelo_conector_do_elefante():
    """O PUT aceita o domínio de QUALQUER plataforma (não sabe qual é a da rota);
    o conector confere contra o domínio DELE antes de abrir."""
    nav = NavRegistra()
    registros: list[str] = []
    res = asyncio.run(ConectorElefante(_fabrica(nav)).testar_credenciais(
        Credenciais(usuario="u", senha="p", extra={"url_login": URL_MATIFIC}),
        _contexto(registros)))
    assert res.ok is False and res.codigo == "pagina_login"
    assert nav.visitadas == []
    assert URL_MATIFIC not in res.mensagem
    assert all(URL_MATIFIC not in m for m in registros)


# ---------------------------------------------------------------------------
# Endereço de fora da lista (redirecionamento) não volta para quem lê
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("plataforma", ["elefante", "matific"])
def test_redirecionamento_para_fora_nao_volta_na_mensagem_nem_no_log(plataforma):
    interno = "http://10.1.2.3/interno?token=ficticio"
    registros: list[str] = []
    nav = NavRegistra(atual=interno)                         # sem formulário
    res = asyncio.run(CLASSES[plataforma](_fabrica(nav)).testar_credenciais(
        Credenciais(usuario="u", senha="p"), _contexto(registros)))
    assert res.ok is False and res.codigo == "pagina_login"
    assert "endereço atual" in res.mensagem                  # a frase acionável fica
    assert "10.1.2.3" not in res.mensagem
    assert all("10.1.2.3" not in m for m in registros)


@pytest.mark.parametrize("plataforma", ["elefante", "matific"])
def test_endereco_final_fora_do_site_nao_volta_apos_enviar(plataforma):
    interno = "http://192.168.0.10/interno"
    registros: list[str] = []
    nav = NavRegistra(atual=interno, formulario=True)        # envia; nada confirma
    res = asyncio.run(CLASSES[plataforma](_fabrica(nav)).testar_credenciais(
        Credenciais(usuario="u", senha="p"), _contexto(registros)))
    assert res.ok is False and res.codigo == "falha_auth"
    assert "endereço final" in res.mensagem
    assert "192.168.0.10" not in res.mensagem
    assert all("192.168.0.10" not in m for m in registros)


def test_endereco_do_site_da_plataforma_continua_na_mensagem():
    """O diagnóstico útil fica: endereço do PRÓPRIO site aparece como antes."""
    pagina = "https://login.elefanteletrado.com.br/welcome"
    nav = NavRegistra(atual=pagina)
    res = asyncio.run(ConectorElefante(_fabrica(nav)).testar_credenciais(
        Credenciais(usuario="u", senha="p"), _contexto()))
    assert res.codigo == "pagina_login" and pagina in res.mensagem
