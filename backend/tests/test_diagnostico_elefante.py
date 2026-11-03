"""Diagnóstico da Integração Elefante (auto-inventário): o conector sonda os
endpoints com a sessão autenticada e o serviço persiste + compara (diff)."""
import asyncio
import logging

import pytest

from app.sync import connectors, vault
from app.sync import diagnostico_elefante as diag
from app.sync.connectors import elefante
from app.sync.connectors.elefante import ConectorElefante
from app.sync.interfaces import Contexto, Credenciais, ErroConector

APIHOST = "https://prod-ecs-apiadmin.elefanteletrado.com.br"


# --- sinais de paginação (puro) ---------------------------------------------

def test_sinais_paginacao():
    assert ConectorElefante._sinais_paginacao([1, 2, 3]) == {
        "formato": "lista_simples", "itens": 3, "chaves_paginacao": []}
    p = ConectorElefante._sinais_paginacao(
        {"total": 120, "page": 1, "content": [1, 2]})
    assert p["formato"] == "objeto" and "total" in p["chaves_paginacao"]
    assert p["lista_em"] == "content" and p["itens"] == 2


# --- diff do inventário (puro) ----------------------------------------------

def test_comparar_primeira_vez():
    atual = {"endpoints": [{"nome": "a", "estrutura": "{x:num}"}]}
    d = diag._comparar(None, atual)
    assert d["primeira_vez"] and d["novos_endpoints"] == ["a"]


def test_comparar_detecta_mudancas():
    anterior = {"endpoints": [
        {"nome": "a", "estrutura": "{x:num}"},
        {"nome": "b", "estrutura": "{y:str}"}],
        "periodos_no_trafego": ["PERIODS.LIFETIME"]}
    atual = {"endpoints": [
        {"nome": "a", "estrutura": "{x:num, z:str}"},   # mudou
        {"nome": "c", "estrutura": "{w:num}"}],          # novo (b sumiu)
        "periodos_no_trafego": ["PERIODS.LIFETIME", "PERIODS.WEEK"]}
    d = diag._comparar(anterior, atual)
    assert d["novos_endpoints"] == ["c"]
    assert d["endpoints_sumidos"] == ["b"]
    assert d["estrutura_mudou"] == ["a"]
    assert any("mudou" in a for a in d["avisos"])
    assert any("PERIODS.WEEK" in a for a in d["avisos"])   # período novo detectado


# --- auto-inventário e2e (conector com navegador FAKE) ----------------------

class NavFake:
    def __init__(self, caps, respostas):
        self._caps, self._resp = caps, respostas

    async def ir_para(self, url): pass
    async def preencher(self, s, v): pass
    async def clicar(self, s): pass
    async def esperar(self, s, timeout_s=20): return True
    async def visivel(self, s): return "password" in s.lower() or "senha" in s.lower()
    async def texto(self, s): return ""
    async def url_atual(self): return "https://admin.elefanteletrado.com.br/reports/menu"
    async def fechar(self): pass
    async def coletar_respostas(self, url, timeout_s=25): return self._caps
    async def coletar_apos_acao(self, acao, timeout_s=20):
        try:
            await acao()
        except Exception:  # noqa: BLE001
            pass
        return []

    async def avaliar(self, expr):
        for frag, resp in self._resp.items():
            if frag in expr:
                return resp
        return {"ok": False, "status": 404, "body": None}


def _caps():
    return [
        {"url": f"{APIHOST}/school/active-schools", "json": [{"id": "123"}],
         "req_auth": "Bearer TESTE"},
        {"url": f"{APIHOST}/course/get-courses-students?schoolId=123"
                "&period=PERIODS.LIFETIME&products=1",
         "json": [{"id": "500", "student": [{"id": "9001"}]}],
         "req_auth": "Bearer TESTE"},
    ]


def _respostas():
    # o que cada endpoint devolve quando o conector chama _js_fetch
    aq = {"ok": True, "status": 200, "body": {
        "total": 42, "answeredQuestions": [
            {"questionId": 1, "correct": True, "answeredAt": "2026-03-10",
             "bookLevel": "C"}]}}
    return {
        "get-courses-students": {"ok": True, "status": 200,
                                 "body": [{"id": 500, "student": [{"id": 9001}]}]},
        "overall-course-report": {"ok": True, "status": 200,
                                  "body": {"students": [{"name": "x", "minutes": 10}]}},
        "overall-student-books-read": {"ok": True, "status": 200,
                                       "body": [{"bookId": 1, "lastReadWhen": "2026-03-01"}]},
        "overall-answered-questions": aq,
        "overall-student-report": {"ok": True, "status": 200, "body": {"history": []}},
    }


def test_diagnosticar_endpoints_captura_estrutura():
    nav = NavFake(_caps(), _respostas())

    async def fab(**_kw):
        return nav

    con = ConectorElefante(fab)
    ctx = Contexto(escola_id=1, execucao_id=None, log=lambda *a: None)
    inv = asyncio.run(con.diagnosticar_endpoints(Credenciais(usuario="u", senha="p"), ctx))

    assert inv["ok"] and inv["turmas"] == 1 and inv["auth"] == "jwt"
    assert inv["aceita_datas_personalizadas"] is True
    assert "PERIODS.LIFETIME" in inv["periodos_no_trafego"]
    por_nome = {e["nome"]: e for e in inv["endpoints"]}
    aq = por_nome["overall-answered-questions"]
    assert aq["status"] == 200
    # Estrutura capturada (só tipos/chaves) — inclui os campos por questão.
    assert "answeredQuestions" in aq["estrutura"] and "questionId" in aq["estrutura"]
    # Paginação detectada.
    assert "total" in aq["paginacao"]["chaves_paginacao"]
    assert aq["paginacao"]["lista_em"] == "answeredQuestions"
    # Parâmetros aceitos (do corpo do POST).
    assert "studentId" in aq["parametros"] and "period" in aq["parametros"]


def test_executar_sem_credencial(db, escola_completa):
    escola = escola_completa["escola"]
    with pytest.raises(ErroConector) as exc:
        diag.executar(db, escola.id)
    assert exc.value.codigo == "sem_credencial"


# --- falha de rede ou de navegador na coleta: resposta honesta, não 500 -------
# Antes: só o ``asyncio.TimeoutError`` era tratado. DNS que não resolve, conexão
# recusada ou o ``TimeoutError`` do Playwright (que não herda do asyncio) subiam crus
# e viravam 500 "Erro interno". Agora, como no placar ao vivo do Matific: 502 "Não
# foi possível rodar o diagnóstico agora…" (ou 504 no tempo esgotado), sem detalhe
# interno na resposta; o detalhe vai para o log. Erro NOSSO depois da coleta continua
# sendo erro nosso. Dados fictícios; sem rede (o navegador é substituído).

FORA_DO_AR = "Não foi possível rodar o diagnóstico agora"


class _NavQueFalha:
    """Navegador FAKE cujo ``ir_para`` falha como o Playwright falha sem rede (abrir
    a página de login é o primeiro passo do diagnóstico)."""

    def __init__(self, erro: Exception):
        self._erro = erro

    async def ir_para(self, url):
        raise self._erro

    async def fechar(self):
        pass


class _NavLento:
    """Navegador FAKE que não responde: estoura o teto do próprio diagnóstico."""

    async def ir_para(self, url):
        await asyncio.sleep(5)

    async def fechar(self):
        pass


class _ConectorQueResponde:
    """Conector FAKE cuja coleta dá certo (o que vem depois é o código nosso)."""

    async def diagnosticar_endpoints(self, cred, contexto):
        return {"ok": True, "turmas": 1,
                "endpoints": [{"nome": "a", "estrutura": "{x:num}"}]}


@pytest.fixture()
def escola_com_elefante(db, escola_completa):
    escola = escola_completa["escola"]
    vault.salvar_credencial(db, escola.id, "elefante", Credenciais(usuario="u", senha="p"))
    db.commit()
    return escola


def _usar_conector(monkeypatch, con) -> None:
    monkeypatch.setattr(connectors, "obter",
                        lambda plat: con if plat == "elefante" else None)


def _navegador_que_falha(monkeypatch, erro: Exception) -> None:
    async def fab(**_kw):
        return _NavQueFalha(erro)

    _usar_conector(monkeypatch, ConectorElefante(fab))


def _rodar_diagnostico(cliente, eid):
    return cliente.post(f"/api/v1/escolas/{eid}/sync/elefante/diagnostico")


def _sem_detalhe_interno(texto: str):
    for cru in ("Erro interno", "net::", "ERR_", "Traceback", "RuntimeError",
                "getaddrinfo", "Timeout 30000ms"):
        assert cru not in texto, cru


def _logs_da_coleta(caplog):
    return [r for r in caplog.records if r.name == "constela.sync"
            and r.getMessage().startswith("Diagnóstico do Elefante falhou na coleta")]


def test_dns_que_nao_resolve_vira_502_dizendo_que_foi_o_elefante(
        cliente, db, escola_com_elefante, monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="constela.sync")
    eid = escola_com_elefante.id
    erro = RuntimeError("net::ERR_NAME_NOT_RESOLVED at https://admin.elefanteletrado.com.br/")
    _navegador_que_falha(monkeypatch, erro)

    r = _rodar_diagnostico(cliente, eid)
    assert r.status_code == 502, r.text                # antes: 500 "Erro interno"
    assert r.json()["detail"].startswith(FORA_DO_AR)
    assert "Tente de novo em alguns minutos" in r.json()["detail"]
    _sem_detalhe_interno(r.text)
    # O detalhe técnico ficou no log do servidor (WARNING, com a exceção original).
    logs = _logs_da_coleta(caplog)
    assert len(logs) == 1 and logs[0].levelno == logging.WARNING
    assert "falhou na coleta (rede)" in logs[0].getMessage()
    assert logs[0].exc_info and logs[0].exc_info[1] is erro
    # Nada foi gravado como inventário.
    assert diag._carregar(db, eid) is None


def _timeout_do_playwright() -> Exception:
    """O ``TimeoutError`` do Playwright (o de verdade, quando instalado). Ele NÃO é o
    do asyncio — por isso escapava do ``except asyncio.TimeoutError``."""
    try:
        from playwright.async_api import TimeoutError as TimeoutDoPlaywright
    except ImportError:  # pragma: no cover - sem o pacote: a mesma forma
        TimeoutDoPlaywright = type("TimeoutError", (Exception,), {})
    return TimeoutDoPlaywright("Timeout 30000ms exceeded.")


def test_tempo_esgotado_do_playwright_vira_504(cliente, escola_com_elefante,
                                               monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="constela.sync")
    erro = _timeout_do_playwright()
    assert not isinstance(erro, asyncio.TimeoutError)
    _navegador_que_falha(monkeypatch, erro)

    r = _rodar_diagnostico(cliente, escola_com_elefante.id)
    assert r.status_code == 504, r.text                # antes: 500 "Erro interno"
    assert "demorou demais" in r.json()["detail"]
    _sem_detalhe_interno(r.text)
    logs = _logs_da_coleta(caplog)
    assert len(logs) == 1 and "tempo esgotado" in logs[0].getMessage()


def test_teto_do_proprio_diagnostico_continua_504(db, escola_com_elefante,
                                                  monkeypatch):
    async def fab(**_kw):
        return _NavLento()

    _usar_conector(monkeypatch, ConectorElefante(fab))
    monkeypatch.setattr(diag, "_TIMEOUT_S", 0.05)
    with pytest.raises(ErroConector) as exc:
        diag.executar(db, escola_com_elefante.id)
    assert exc.value.codigo == "timeout" and exc.value.recuperavel is True
    assert "demorou demais" in str(exc.value)


def test_erro_do_conector_continua_com_a_propria_mensagem(cliente, escola_com_elefante,
                                                          monkeypatch):
    """A rede de proteção nova não engole o que o conector já sabe dizer (aqui, o
    navegador do robô ausente: 503 com a mensagem dele)."""
    async def fab(**_kw):
        raise ErroConector("Playwright não está instalado neste ambiente.",
                           codigo="navegador_indisponivel", recuperavel=False)

    _usar_conector(monkeypatch, ConectorElefante(fab))
    r = _rodar_diagnostico(cliente, escola_com_elefante.id)
    assert r.status_code == 503, r.text
    assert r.json()["detail"] == "Playwright não está instalado neste ambiente."


def test_coleta_certa_grava_e_erro_nosso_depois_dela_nao_vira_culpa_do_elefante(
        db, escola_com_elefante, monkeypatch, caplog):
    """Só a COLETA é protegida: um defeito do Constela depois dela (diff, gravação)
    não pode ser apresentado como "o Elefante não respondeu"."""
    caplog.set_level(logging.WARNING, logger="constela.sync")
    eid = escola_com_elefante.id
    _usar_conector(monkeypatch, _ConectorQueResponde())

    feito = diag.executar(db, eid)                       # o caminho feliz segue igual
    assert feito["diff"]["primeira_vez"] is True
    assert diag._carregar(db, eid)["gerado_em"] == feito["inventario"]["gerado_em"]

    def _defeito(*_a, **_k):
        raise RuntimeError("defeito ficticio do Constela")

    monkeypatch.setattr(diag, "_comparar", _defeito)
    with pytest.raises(RuntimeError, match="defeito ficticio"):
        diag.executar(db, eid)
    assert _logs_da_coleta(caplog) == []


# --- de quem é a falha: só rede e navegador culpam o Elefante -------------------
# Antes: QUALQUER exceção no meio da coleta virava 502 "a conexão com o site do
# Elefante falhou", com log WARNING. Um defeito NOSSO no parsing do conector
# (KeyError, TypeError, AttributeError…) culpava o Elefante e, com o nível padrão da
# integração de logging do Sentry (ERROR), nem chegava ao Sentry. Agora só
# OSError/ConnectionError/TimeoutError e as exceções do Playwright/httpx/httpcore (e a
# marca net::ERR_ do Chromium) viram 502/504; o defeito nosso vai para o log ERROR e
# sobe cru (500). Grupo de exceções: olha cada uma; ``asyncio.CancelledError`` de
# dentro do conector vira 500 (não escapa como BaseException).


class _ConectorQueFalha:
    """Conector FAKE cuja coleta levanta ``erro`` (depois de um ``await``, como faria
    o parsing de uma resposta)."""

    def __init__(self, erro: BaseException):
        self._erro = erro

    async def diagnosticar_endpoints(self, cred, contexto):
        await asyncio.sleep(0)
        raise self._erro


def _logs_de_defeito_nosso(caplog):
    return [r for r in _logs_da_coleta(caplog)
            if r.getMessage().startswith(
                "Diagnóstico do Elefante falhou na coleta por um defeito do Constela")]


def test_defeito_nosso_no_meio_da_coleta_sobe_500_e_vai_para_o_log_error(
        cliente, db, escola_com_elefante, monkeypatch, caplog):
    """O defeito nosso de verdade: o parsing do conector quebra no meio da coleta."""
    caplog.set_level(logging.WARNING, logger="constela.sync")
    eid = escola_com_elefante.id
    erro = KeyError("campo_ficticio")
    _navegador_que_falha(monkeypatch, erro)

    r = _rodar_diagnostico(cliente, eid)
    assert r.status_code == 500, r.text                # antes: 502 "…o Elefante…"
    assert FORA_DO_AR not in r.text
    assert "Erro interno" in r.json()["detail"]        # a resposta do 500, sem detalhe
    assert "campo_ficticio" not in r.text
    logs = _logs_de_defeito_nosso(caplog)
    assert len(logs) == 1 and logs[0].levelno == logging.ERROR   # o Sentry vê
    assert logs[0].exc_info and logs[0].exc_info[1] is erro
    # O único log da coleta é o ERROR do defeito nosso: nem "(rede)" nem "(tempo esgotado)".
    assert len(_logs_da_coleta(caplog)) == 1
    assert diag._carregar(db, eid) is None


@pytest.mark.parametrize("erro", [TypeError("x"), AttributeError("x"),
                                  RuntimeError("defeito ficticio do conector")])
def test_outros_defeitos_nossos_na_coleta_sobem_crus(db, escola_com_elefante,
                                                     monkeypatch, caplog, erro):
    caplog.set_level(logging.WARNING, logger="constela.sync")
    _usar_conector(monkeypatch, _ConectorQueFalha(erro))
    with pytest.raises(type(erro)) as exc:
        diag.executar(db, escola_com_elefante.id)
    assert exc.value is erro
    assert [x.levelno for x in _logs_de_defeito_nosso(caplog)] == [logging.ERROR]


def _erro_httpx():
    import httpx
    return httpx.ConnectError("[Errno 11001] getaddrinfo failed")


def _erro_do_playwright():
    """A forma do ``playwright.async_api.Error`` (o pacote dele), sem importar o pacote."""
    tipo = type("Error", (Exception,), {"__module__": "playwright._impl._errors"})
    return tipo("Page.goto: net::ERR_CONNECTION_REFUSED")


@pytest.mark.parametrize("fabrica", [
    lambda: OSError("rede ficticia"), lambda: ConnectionResetError("rede ficticia"),
    _erro_httpx, _erro_do_playwright])
def test_rede_e_navegador_continuam_502(db, escola_com_elefante, monkeypatch, caplog,
                                        fabrica):
    caplog.set_level(logging.WARNING, logger="constela.sync")
    _usar_conector(monkeypatch, _ConectorQueFalha(fabrica()))
    with pytest.raises(ErroConector) as exc:
        diag.executar(db, escola_com_elefante.id)
    assert exc.value.codigo == "indisponivel_externo"
    assert str(exc.value).startswith(FORA_DO_AR)
    assert [x.levelno for x in _logs_da_coleta(caplog)] == [logging.WARNING]


def test_grupo_so_de_tempo_esgotado_vira_504(db, escola_com_elefante, monkeypatch):
    """Antes: o grupo com TimeoutError dentro saía 502, não 504."""
    grupo = ExceptionGroup("coleta", [TimeoutError(), _timeout_do_playwright()])
    _usar_conector(monkeypatch, _ConectorQueFalha(grupo))
    with pytest.raises(ErroConector) as exc:
        diag.executar(db, escola_com_elefante.id)
    assert exc.value.codigo == "timeout" and "demorou demais" in str(exc.value)


def test_grupo_de_rede_vira_502(db, escola_com_elefante, monkeypatch):
    grupo = ExceptionGroup("coleta", [ConnectionResetError(), TimeoutError()])
    _usar_conector(monkeypatch, _ConectorQueFalha(grupo))
    with pytest.raises(ErroConector) as exc:
        diag.executar(db, escola_com_elefante.id)
    assert exc.value.codigo == "indisponivel_externo"


def test_grupo_com_defeito_nosso_sobe_cru(db, escola_com_elefante, monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="constela.sync")
    grupo = ExceptionGroup("coleta", [ConnectionResetError(),
                                      ExceptionGroup("dentro", [KeyError("x")])])
    _usar_conector(monkeypatch, _ConectorQueFalha(grupo))
    with pytest.raises(ExceptionGroup) as exc:
        diag.executar(db, escola_com_elefante.id)
    assert exc.value is grupo
    assert [x.levelno for x in _logs_de_defeito_nosso(caplog)] == [logging.ERROR]


def test_grupo_com_erro_do_conector_passa_a_mensagem_dele(db, escola_com_elefante,
                                                          monkeypatch):
    captcha = ErroConector("O Elefante exibiu uma verificação de segurança (CAPTCHA).",
                           codigo="captcha", recuperavel=True)
    _usar_conector(monkeypatch, _ConectorQueFalha(
        ExceptionGroup("coleta", [ConnectionResetError(), captcha])))
    with pytest.raises(ErroConector) as exc:
        diag.executar(db, escola_com_elefante.id)
    assert exc.value is captcha


def test_cancelamento_de_dentro_do_conector_vira_500_e_nao_escapa(
        cliente, db, escola_com_elefante, monkeypatch, caplog):
    """Um ``asyncio.CancelledError`` que sai de DENTRO do conector (ninguém de fora
    cancelou; o teto da coleta vira TimeoutError) é BaseException: subia cru e escapava
    do tratamento de erro da rota. Agora é um RuntimeError (defeito nosso, 500) com o
    cancelamento como causa, e vai para o log ERROR."""
    caplog.set_level(logging.WARNING, logger="constela.sync")
    _usar_conector(monkeypatch, _ConectorQueFalha(asyncio.CancelledError()))
    with pytest.raises(RuntimeError) as exc:
        diag.executar(db, escola_com_elefante.id)
    assert isinstance(exc.value.__cause__, asyncio.CancelledError)
    assert [x.levelno for x in _logs_de_defeito_nosso(caplog)] == [logging.ERROR]

    r = _rodar_diagnostico(cliente, escola_com_elefante.id)
    assert r.status_code == 500 and "Erro interno" in r.json()["detail"]
