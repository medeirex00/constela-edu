"""Placar AO VIVO do Matific (Ranking de Matemática por Semana/Mês/Bimestre): o que o
professor vê e o que a tela recebe quando o Matific não responde.

1. RECORTE DO PROFESSOR. A rota já tirava os alunos das outras turmas, mas deixava em
   cada linha a ``posicao`` da escola inteira e devolvia ``total``/``com_link`` da
   escola: o professor via "3º, 5º" (e o pódio vazio, que exige a lista começando em
   1) enquanto nas abas Geral e Leitura via 1..N. Agora a posição é RELATIVA ao recorte
   (1..N na ordem do Placar) e as contagens são do recorte, como no Ranking Geral do
   professor. A gestão continua vendo a posição da escola inteira — e o resultado em
   cache (o mesmo objeto para todos) não é alterado pelo recorte.

2. FALHA DE REDE OU DE NAVEGADOR. Só ``asyncio.TimeoutError`` e ``ErroConector`` eram
   tratados: DNS que não resolve, conexão recusada ou o ``TimeoutError`` do Playwright
   (que não herda do asyncio) subiam crus e viravam 500 "Erro interno". Agora viram
   502 "Não foi possível consultar o Matific agora…" (ou 504 no tempo esgotado), sem
   detalhe interno na resposta. Erro NOSSO depois da coleta continua sendo erro nosso.

Dados 100% fictícios; sem rede (a coleta ou o navegador são substituídos).
"""
import asyncio
import logging
from datetime import datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import Aluno, Matricula, Professor, Turma, Usuario
from app.sync import aovivo, connectors, vault
from app.sync.connectors import matific
from app.sync.interfaces import Credenciais, ErroConector

API = "/api/v1"
FORA_DO_AR = "Não foi possível consultar o Matific agora"


@pytest.fixture(autouse=True)
def _limpar_cache():
    """O cache de resultado é global (por processo): zera entre testes."""
    aovivo._cache.clear()
    yield
    aovivo._cache.clear()


def _login(email: str, senha: str) -> TestClient:
    c = TestClient(app)
    r = c.post(f"{API}/auth/login", data={"username": email, "password": senha})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


@pytest.fixture()
def escola_com_professor(db, escola_completa):
    """Turma A (a da fixture: Ana, João, Sofia) do professor; turma B com um aluno
    fora do alcance dele; um coordenador (acesso à escola inteira)."""
    escola = escola_completa["escola"]
    turma_b = Turma(escola_id=escola.id, nome="5º Ano B", ano_escolar="5º Ano",
                    ano_letivo=2026)
    db.add(turma_b)
    db.flush()
    fora = Aluno(escola_id=escola.id, nome="Aluno Ficticio Da Turma B")
    db.add(fora)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=fora.id, turma_id=turma_b.id,
                     ano_letivo=2026))
    prof = Professor(escola_id=escola.id, nome="Prof Ficticia Placar",
                     email="prof.placar@teste.local")
    db.add(prof)
    db.flush()
    escola_completa["turma"].professor_id = prof.id
    db.add(Usuario(escola_id=escola.id, nome="Prof Ficticia Placar",
                   email="prof.placar@teste.local", senha_hash=hash_senha("s3nh4"),
                   cargo="professor"))
    db.add(Usuario(escola_id=escola.id, nome="Coord Ficticio Placar",
                   email="coord.placar@teste.local", senha_hash=hash_senha("s3nh4"),
                   cargo="coordenador"))
    vault.salvar_credencial(db, escola.id, "matific", Credenciais(usuario="u", senha="p"))
    db.commit()
    return {"escola": escola, "alunos": escola_completa["alunos"], "fora": fora}


class _ConectorSoHttp:  # placar_matific confere que o conector tem coletar_via_http
    def coletar_via_http(self, *a, **k):  # pragma: no cover - substituído
        raise AssertionError("substituído")


def _linha(nome, estrelas):
    return {"nome": nome, "turma": None, "serie": "3", "estrelas": estrelas,
            "atividades": 5}


def _get_placar(cliente, eid, **extra):
    params = {"periodo": "semana", **extra}
    return cliente.get(f"{API}/escolas/{eid}/sync/matific/placar-ao-vivo", params=params)


# ============================================================================
# 1. Recorte do professor: posição 1..N e contagens do recorte
# ============================================================================
def test_professor_ve_posicao_e_total_do_recorte_e_a_gestao_os_da_escola(
        escola_com_professor, monkeypatch):
    """O pipeline real (_fichas_da_escola + _montar_ranking + o recorte da rota); só a
    coleta é substituída. Placar da escola: 5 linhas; as 2 da turma do professor estão
    em 3º e 5º."""
    c = escola_com_professor
    eid = c["escola"].id
    ana, joao, _sofia = c["alunos"]
    linhas = [
        _linha("Pessoa Ficticia Sem Ficha", 100),     # 1º — sem link
        _linha(c["fora"].nome, 90),                   # 2º — outra turma
        _linha(ana.nome, 80),                         # 3º — do professor
        _linha("Outra Pessoa Ficticia", 70),          # 4º — sem link
        _linha(joao.nome, 60),                        # 5º — do professor
    ]
    monkeypatch.setattr(connectors, "obter",
                        lambda plat: _ConectorSoHttp() if plat == "matific" else None)
    coletas = []

    def _coleta(*_a, **_k):
        coletas.append(1)
        return [dict(x) for x in linhas], None

    monkeypatch.setattr(aovivo, "_coletar_http_first", _coleta)
    professor = _login("prof.placar@teste.local", "s3nh4")
    coordenador = _login("coord.placar@teste.local", "s3nh4")

    r = _get_placar(professor, eid)
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert [(i["aluno_id"], i["posicao"]) for i in corpo["itens"]] == \
        [(ana.id, 1), (joao.id, 2)]              # antes: [(ana, 3), (joao, 5)]
    assert corpo["total"] == 2 and corpo["com_link"] == 2   # antes: 5 e 3
    # O pódio da tela exige a lista começando em 1 (itensDoPodio).
    assert corpo["itens"][0]["posicao"] == 1
    # O resto da linha não muda (só a posição é relativa).
    assert corpo["itens"][0]["estrelas"] == 80 and corpo["itens"][1]["estrelas"] == 60

    # A gestão, logo depois (mesmo período → o MESMO objeto do cache): a escola inteira.
    r = _get_placar(coordenador, eid)
    assert r.status_code == 200, r.text
    gestao = r.json()
    assert gestao["cache"] is True and len(coletas) == 1
    assert [i["posicao"] for i in gestao["itens"]] == [1, 2, 3, 4, 5]
    assert [i["estrelas"] for i in gestao["itens"]] == [100, 90, 80, 70, 60]
    assert gestao["total"] == 5 and gestao["com_link"] == 3

    # E o professor de novo, pelo cache: continua 1..N.
    de_novo = _get_placar(professor, eid).json()
    assert [i["posicao"] for i in de_novo["itens"]] == [1, 2]
    assert de_novo["total"] == 2


def test_professor_sem_alunos_no_placar_recebe_lista_vazia_e_total_zero(
        escola_com_professor, monkeypatch):
    c = escola_com_professor
    monkeypatch.setattr(connectors, "obter",
                        lambda plat: _ConectorSoHttp() if plat == "matific" else None)
    monkeypatch.setattr(aovivo, "_coletar_http_first",
                        lambda *a, **k: ([_linha(c["fora"].nome, 90)], None))
    corpo = _get_placar(_login("prof.placar@teste.local", "s3nh4"), c["escola"].id).json()
    assert corpo["itens"] == [] and corpo["total"] == 0 and corpo["com_link"] == 0


# ============================================================================
# 2. Falha de rede ou de navegador: resposta honesta, não 500
# ============================================================================
class _NavQueFalha:
    """Navegador FAKE cujo ``ir_para`` falha como o Playwright falha sem rede."""

    def __init__(self, erro: Exception):
        self._erro = erro

    async def ir_para(self, url):
        raise self._erro

    async def fechar(self):
        pass


def _conector_com_navegador_que_falha(monkeypatch, erro: Exception):
    async def fab(**_kw):
        return _NavQueFalha(erro)

    con = matific.ConectorMatific(fab)
    monkeypatch.setattr(connectors, "obter", lambda plat: con if plat == "matific" else None)
    return con


def _sem_detalhe_interno(texto: str):
    for cru in ("Erro interno", "net::", "ERR_", "Traceback", "RuntimeError",
                "getaddrinfo", "Timeout 30000ms"):
        assert cru not in texto, cru


def test_dns_que_nao_resolve_vira_502_dizendo_que_foi_o_matific(
        cliente, escola_com_professor, monkeypatch):
    eid = escola_com_professor["escola"].id
    _conector_com_navegador_que_falha(
        monkeypatch, RuntimeError("net::ERR_NAME_NOT_RESOLVED at https://www.matific.com/"))
    r = _get_placar(cliente, eid, forcar="true")
    assert r.status_code == 502, r.text                # antes: 500 "Erro interno"
    assert r.json()["detail"].startswith(FORA_DO_AR)
    assert "Tente de novo em alguns minutos" in r.json()["detail"]
    _sem_detalhe_interno(r.text)


def _timeout_do_playwright() -> Exception:
    """O ``TimeoutError`` do Playwright (o de verdade, quando instalado). Ele NÃO é o
    do asyncio — por isso escapava do ``except asyncio.TimeoutError``."""
    try:
        from playwright.async_api import TimeoutError as TimeoutDoPlaywright
    except ImportError:  # pragma: no cover - sem o pacote: a mesma forma
        TimeoutDoPlaywright = type("TimeoutError", (Exception,), {})
    return TimeoutDoPlaywright("Timeout 30000ms exceeded.")


def test_tempo_esgotado_do_playwright_vira_504(cliente, escola_com_professor,
                                               monkeypatch):
    erro = _timeout_do_playwright()
    assert not isinstance(erro, asyncio.TimeoutError)
    eid = escola_com_professor["escola"].id
    _conector_com_navegador_que_falha(monkeypatch, erro)
    r = _get_placar(cliente, eid, forcar="true")
    assert r.status_code == 504, r.text                # antes: 500 "Erro interno"
    assert "demorou demais" in r.json()["detail"]
    _sem_detalhe_interno(r.text)


def test_sessao_salva_com_rede_fora_cai_no_navegador_e_responde_honesto(
        db, escola_com_professor, monkeypatch):
    """O caminho realista: sessão salva → HTTP sem rede (``http_indisponivel``) → o
    navegador entra para autenticar e também não abre a página."""
    eid = escola_com_professor["escola"].id
    agora = datetime(2026, 10, 30, 12, 0, 0)
    aovivo._salvar_sessao(db, eid, {"cookies": [
        {"name": "sessionid", "value": "x", "domain": ".matific.com"}]}, agora)

    class _SemRede:
        def __init__(self, **_kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False

        def get(self, url):
            raise httpx.ConnectError("[Errno 11001] getaddrinfo failed")

    monkeypatch.setattr(httpx, "Client", _SemRede)
    _conector_com_navegador_que_falha(
        monkeypatch, RuntimeError("net::ERR_INTERNET_DISCONNECTED"))
    with pytest.raises(ErroConector) as exc:
        aovivo.placar_matific(db, eid, periodo="semana", inicio=None, fim=None,
                              forcar=True, agora=agora)
    assert exc.value.codigo == "indisponivel_externo"
    assert exc.value.recuperavel is True
    assert str(exc.value).startswith(FORA_DO_AR)
    _sem_detalhe_interno(str(exc.value))


def test_erro_do_conector_continua_com_a_propria_mensagem(cliente, escola_com_professor,
                                                          monkeypatch):
    """A rede de proteção nova não engole o que o conector já sabe dizer."""
    eid = escola_com_professor["escola"].id
    monkeypatch.setattr(connectors, "obter",
                        lambda plat: _ConectorSoHttp() if plat == "matific" else None)

    def _captcha(*_a, **_k):
        raise ErroConector("O Matific exibiu uma verificação de segurança (CAPTCHA).",
                           codigo="captcha", recuperavel=True)

    monkeypatch.setattr(aovivo, "_coletar_http_first", _captcha)
    r = _get_placar(cliente, eid, forcar="true")
    assert r.status_code == 502, r.text
    assert "CAPTCHA" in r.json()["detail"] and FORA_DO_AR not in r.json()["detail"]


def test_erro_nosso_depois_da_coleta_nao_vira_culpa_do_matific(db, escola_com_professor,
                                                               monkeypatch):
    """Só a COLETA é protegida: um defeito do Constela depois dela não pode ser
    apresentado como "o Matific não respondeu"."""
    eid = escola_com_professor["escola"].id
    monkeypatch.setattr(connectors, "obter",
                        lambda plat: _ConectorSoHttp() if plat == "matific" else None)
    monkeypatch.setattr(aovivo, "_coletar_http_first",
                        lambda *a, **k: ([_linha("Pessoa Ficticia", 10)], None))

    def _defeito(*_a, **_k):
        raise RuntimeError("defeito ficticio do Constela")

    monkeypatch.setattr(aovivo, "_fichas_da_escola", _defeito)
    with pytest.raises(RuntimeError, match="defeito ficticio"):
        aovivo.placar_matific(db, eid, periodo="semana", inicio=None, fim=None,
                              forcar=True)


# ============================================================================
# 3. De quem é a falha: só rede e navegador culpam o Matific
# ============================================================================
# Antes: QUALQUER exceção no meio da consulta virava 502 "a conexão com o site do
# Matific falhou", com log WARNING — um defeito NOSSO (KeyError, TypeError,
# AttributeError…) culpava o Matific e não chegava ao Sentry. Agora só
# OSError/ConnectionError/TimeoutError e as exceções do Playwright/httpx/httpcore (e a
# marca net::ERR_ do Chromium) viram 502/504; o defeito nosso vai para o log ERROR e
# sobe cru (500). Grupo de exceções: olha cada uma; ``asyncio.CancelledError`` de
# dentro do conector vira 500 (não escapa como BaseException).


def _coleta_que_falha(monkeypatch, erro: BaseException):
    monkeypatch.setattr(connectors, "obter",
                        lambda plat: _ConectorSoHttp() if plat == "matific" else None)

    def _coleta(*_a, **_k):
        raise erro

    monkeypatch.setattr(aovivo, "_coletar_http_first", _coleta)


def _consultar(db, eid):
    return aovivo.placar_matific(db, eid, periodo="semana", inicio=None, fim=None,
                                 forcar=True)


def _logs_de_defeito_nosso(caplog):
    return [r for r in caplog.records if r.name == "constela.sync"
            and r.getMessage().startswith(
                "Consulta ao vivo do Matific falhou por um defeito do Constela")]


def test_defeito_nosso_no_meio_da_consulta_sobe_500_e_vai_para_o_log_error(
        cliente, escola_com_professor, monkeypatch, caplog):
    """O defeito nosso de verdade, pelo caminho real: o conector quebra no meio do
    login (aqui, um KeyError no navegador) — não é o Matific que não respondeu."""
    caplog.set_level(logging.WARNING, logger="constela.sync")
    eid = escola_com_professor["escola"].id
    erro = KeyError("campo_ficticio")
    _conector_com_navegador_que_falha(monkeypatch, erro)
    r = _get_placar(cliente, eid, forcar="true")
    assert r.status_code == 500, r.text                # antes: 502 "…o Matific…"
    assert FORA_DO_AR not in r.text and "campo_ficticio" not in r.text
    assert "Erro interno" in r.json()["detail"]
    logs = _logs_de_defeito_nosso(caplog)
    assert len(logs) == 1 and logs[0].levelno == logging.ERROR   # o Sentry vê
    assert logs[0].exc_info and logs[0].exc_info[1] is erro


@pytest.mark.parametrize("erro", [TypeError("x"), AttributeError("x"),
                                  RuntimeError("defeito ficticio do conector")])
def test_outros_defeitos_nossos_na_consulta_sobem_crus(db, escola_com_professor,
                                                       monkeypatch, caplog, erro):
    caplog.set_level(logging.WARNING, logger="constela.sync")
    _coleta_que_falha(monkeypatch, erro)
    with pytest.raises(type(erro)) as exc:
        _consultar(db, escola_com_professor["escola"].id)
    assert exc.value is erro
    assert [x.levelno for x in _logs_de_defeito_nosso(caplog)] == [logging.ERROR]


def _erro_do_playwright():
    """A forma do ``playwright.async_api.Error`` (o pacote dele), sem importar o pacote."""
    tipo = type("Error", (Exception,), {"__module__": "playwright._impl._errors"})
    return tipo("Page.goto: net::ERR_CONNECTION_REFUSED")


@pytest.mark.parametrize("fabrica", [
    lambda: OSError("rede ficticia"), lambda: ConnectionResetError("rede ficticia"),
    lambda: httpx.ReadError("conexão caiu"), _erro_do_playwright])
def test_rede_e_navegador_continuam_502(db, escola_com_professor, monkeypatch, fabrica):
    _coleta_que_falha(monkeypatch, fabrica())
    with pytest.raises(ErroConector) as exc:
        _consultar(db, escola_com_professor["escola"].id)
    assert exc.value.codigo == "indisponivel_externo"
    assert str(exc.value).startswith(FORA_DO_AR)


def test_grupo_so_de_tempo_esgotado_vira_504(db, escola_com_professor, monkeypatch):
    _coleta_que_falha(monkeypatch, ExceptionGroup(
        "coleta", [TimeoutError(), _timeout_do_playwright()]))
    with pytest.raises(ErroConector) as exc:
        _consultar(db, escola_com_professor["escola"].id)
    assert exc.value.codigo == "timeout" and "demorou demais" in str(exc.value)


def test_grupo_de_rede_vira_502_e_com_defeito_nosso_sobe_cru(db, escola_com_professor,
                                                             monkeypatch, caplog):
    caplog.set_level(logging.WARNING, logger="constela.sync")
    eid = escola_com_professor["escola"].id
    _coleta_que_falha(monkeypatch, ExceptionGroup(
        "coleta", [ConnectionResetError(), TimeoutError()]))
    with pytest.raises(ErroConector) as exc:
        _consultar(db, eid)
    assert exc.value.codigo == "indisponivel_externo"

    grupo = ExceptionGroup("coleta", [ConnectionResetError(),
                                      ExceptionGroup("dentro", [AttributeError("x")])])
    _coleta_que_falha(monkeypatch, grupo)
    with pytest.raises(ExceptionGroup) as exc_grupo:
        _consultar(db, eid)
    assert exc_grupo.value is grupo
    assert [x.levelno for x in _logs_de_defeito_nosso(caplog)] == [logging.ERROR]


def test_grupo_com_erro_do_conector_passa_a_mensagem_dele(db, escola_com_professor,
                                                          monkeypatch):
    captcha = ErroConector("O Matific exibiu uma verificação de segurança (CAPTCHA).",
                           codigo="captcha", recuperavel=True)
    _coleta_que_falha(monkeypatch, ExceptionGroup("coleta", [OSError(), captcha]))
    with pytest.raises(ErroConector) as exc:
        _consultar(db, escola_com_professor["escola"].id)
    assert exc.value is captcha


def test_cancelamento_de_dentro_do_conector_vira_500_e_nao_escapa(
        cliente, db, escola_com_professor, monkeypatch, caplog):
    """O ``asyncio.run`` devolve ``CancelledError`` quando a coleta é cancelada por
    DENTRO (ninguém de fora cancelou; o teto vira TimeoutError). É BaseException: subia
    cru e escapava do tratamento de erro da rota. Agora é um RuntimeError (defeito
    nosso, 500) com o cancelamento como causa, e vai para o log ERROR."""
    caplog.set_level(logging.WARNING, logger="constela.sync")
    eid = escola_com_professor["escola"].id
    monkeypatch.setattr(connectors, "obter",
                        lambda plat: _ConectorSoHttp() if plat == "matific" else None)

    def _coleta_cancelada(*_a, **_k):
        async def _dentro():
            await asyncio.sleep(0)
            raise asyncio.CancelledError()
        return asyncio.run(_dentro())

    monkeypatch.setattr(aovivo, "_coletar_http_first", _coleta_cancelada)
    with pytest.raises(RuntimeError) as exc:
        _consultar(db, eid)
    assert isinstance(exc.value.__cause__, asyncio.CancelledError)
    assert [x.levelno for x in _logs_de_defeito_nosso(caplog)] == [logging.ERROR]

    r = _get_placar(cliente, eid, forcar="true")
    assert r.status_code == 500 and "Erro interno" in r.json()["detail"]
