"""Um teste de conexão que deu certo fecha o alerta do navegador que não abriu.

Antes: no "Testar conexão" (ou ao salvar a credencial), o Chromium que não abria dava
``navegador_indisponivel`` e abria o alerta 'plataforma_indisponivel' CRÍTICO; quando o
teste seguinte dava certo, só os alertas de ACESSO (``service.TIPOS_ACESSO``) eram
fechados. A credencial ficava 'valida' e o alerta crítico continuava na tela de
Sincronização até uma sincronização bem-sucedida — e o agendador está desligado. Agora
o login que funcionou fecha também esse alerta: ele prova que o navegador deste
servidor abre e que a plataforma respondeu.

Também: ``testar_credenciais`` não registra mais "Credencial recusada" quando o NOSSO
navegador não abriu — a credencial nem chegou à plataforma.

Resíduo da revisão (01/11): um teste que chegou à página de login e foi RECUSADO
(senha, CAPTCHA, login não confirmado…) também prova que o navegador abriu, mas o
alerta crítico do navegador continuava aberto ao lado do novo — a tela mostrava "a
plataforma está indisponível" e "senha recusada" juntos. Agora a recusa da página de
login fecha o do navegador antes de abrir o dela; o ``erro_navegador`` (que pode ser
o navegador que caiu no meio) não fecha.

Sem navegador real nem rede: o ``playwright.async_api`` é trocado por um falso (o
mesmo de ``test_navegador_indisponivel``) e o login que dá certo usa o navegador fake
de ``test_sync``.
"""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from app.models.sincronizacao import SincronizacaoAlerta
from app.sync import connectors, service, vault
from app.sync import router as sync_router
from app.sync.connectors.matific import ConectorMatific
from app.sync.interfaces import Contexto, Credenciais, ResultadoValidacao
from tests.test_navegador_indisponivel import (
    DETALHE_INTERNO,
    ErroDoPlaywright,
    _NavQueCai,
    _playwright_falso,
    _target_closed,
)
from tests.test_sync import NavegadorFake, _fabrica


def _abertos(db, eid) -> list[tuple[str, str]]:
    db.expire_all()
    return sorted((a.tipo, a.severidade) for a in db.execute(
        select(SincronizacaoAlerta).where(
            SincronizacaoAlerta.escola_id == eid,
            SincronizacaoAlerta.resolvido.is_(False))).scalars())


def _status_da_credencial(db, eid) -> str:
    db.expire_all()
    return vault.obter_linha(db, eid, "matific").status


def _conector_com_navegador_que_nao_abre(monkeypatch) -> None:
    """O conector REAL com a fábrica REAL (``abrir_playwright``) e um Chromium que não
    abre neste servidor."""
    _playwright_falso(monkeypatch, falha_launch=ErroDoPlaywright(DETALHE_INTERNO))
    monkeypatch.setitem(connectors._REGISTRO, "matific", ConectorMatific())


def _conector_com_login_que_funciona(monkeypatch) -> None:
    monkeypatch.setitem(connectors._REGISTRO, "matific",
                        ConectorMatific(_fabrica(NavegadorFake(logado=True))))


@pytest.mark.parametrize("como", ["testar", "salvar"])
def test_navegador_que_falha_depois_teste_ok_nao_deixa_alerta_aberto(
        cliente, db, escola_completa, monkeypatch, como):
    eid = escola_completa["escola"].id
    monkeypatch.setattr(service, "disparar_em_thread", lambda _id: None)
    _conector_com_navegador_que_nao_abre(monkeypatch)

    r = cliente.put(f"/api/v1/escolas/{eid}/sync/credenciais/matific",
                    json={"usuario": "u", "senha": "p"})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is False and r.json()["codigo"] == "navegador_indisponivel"
    assert _abertos(db, eid) == [("plataforma_indisponivel", "critico")]
    assert _status_da_credencial(db, eid) == "nao_validada"   # não 'invalida'

    # O navegador voltou a abrir e o login funciona.
    _conector_com_login_que_funciona(monkeypatch)
    if como == "testar":
        r = cliente.post(f"/api/v1/escolas/{eid}/sync/credenciais/matific/testar")
    else:
        r = cliente.put(f"/api/v1/escolas/{eid}/sync/credenciais/matific",
                        json={"usuario": "u", "senha": "p"})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert _status_da_credencial(db, eid) == "valida"
    assert _abertos(db, eid) == []        # antes: o crítico continuava aberto


def test_teste_ok_fecha_o_alerta_aberto_pela_execucao_mas_nao_os_de_outra_causa(
        cliente, db, escola_completa, monkeypatch):
    """O alerta do navegador aberto por uma EXECUÇÃO também perde a causa com o login
    que funcionou. Um alerta de coleta (tempo esgotado esperando a plataforma) não:
    o teste de conexão não prova que a coleta voltou."""
    eid = escola_completa["escola"].id
    vault.salvar_credencial(db, eid, "matific", Credenciais(usuario="u", senha="p"))
    db.commit()
    _conector_com_navegador_que_nao_abre(monkeypatch)
    ex = service.enfileirar(db, eid, "matific", origem="manual")
    service.executar(db, ex)
    service.abrir_alerta(db, eid, "matific", "timeout", "demorou (fictício)")
    db.commit()
    assert _abertos(db, eid) == [("plataforma_indisponivel", "critico"),
                                 ("timeout", "warn")]

    _conector_com_login_que_funciona(monkeypatch)
    r = cliente.post(f"/api/v1/escolas/{eid}/sync/credenciais/matific/testar")
    assert r.status_code == 200 and r.json()["ok"] is True, r.text
    assert _abertos(db, eid) == [("timeout", "warn")]


def test_teste_que_falha_de_novo_mantem_o_alerta(cliente, db, escola_completa,
                                                 monkeypatch):
    """Guarda: só o login que FUNCIONOU fecha o alerta do navegador."""
    eid = escola_completa["escola"].id
    _conector_com_navegador_que_nao_abre(monkeypatch)
    cliente.put(f"/api/v1/escolas/{eid}/sync/credenciais/matific",
                json={"usuario": "u", "senha": "p"})
    r = cliente.post(f"/api/v1/escolas/{eid}/sync/credenciais/matific/testar")
    assert r.json()["ok"] is False
    assert _abertos(db, eid) == [("plataforma_indisponivel", "critico")]
    assert _status_da_credencial(db, eid) == "nao_validada"


# --- o log do teste não diz "Credencial recusada" quando o navegador não abriu ------

def _contexto_que_registra(eid: int):
    eventos: list[tuple[str, str]] = []
    ctx = Contexto(escola_id=eid, execucao_id=None,
                   log=lambda etapa, nivel, msg: eventos.append((nivel, msg)))
    return ctx, eventos


def test_navegador_que_nao_abre_nao_registra_credencial_recusada(monkeypatch):
    _playwright_falso(monkeypatch, falha_launch=ErroDoPlaywright(DETALHE_INTERNO))
    ctx, eventos = _contexto_que_registra(1)
    res = asyncio.run(ConectorMatific().testar_credenciais(
        Credenciais(usuario="u", senha="p"), ctx))
    assert res.ok is False and res.codigo == "navegador_indisponivel"
    textos = [m for _n, m in eventos]
    assert not [m for m in textos if "Credencial recusada" in m]
    assert ("erro", f"Credencial não testada: {res.mensagem}") in eventos
    assert not [m for m in textos if "Executable" in m or "ms-playwright" in m]


def test_senha_recusada_continua_registrando_credencial_recusada():
    """Guarda: a recusa de verdade da plataforma segue com o registro de antes."""
    ctx, eventos = _contexto_que_registra(1)
    res = asyncio.run(ConectorMatific(_fabrica(NavegadorFake(logado=False, erro_login=True)))
                      .testar_credenciais(Credenciais(usuario="u", senha="p"), ctx))
    assert res.ok is False and res.codigo == "senha_invalida"
    assert [n for n, m in eventos if m.startswith("Credencial recusada: ")] == ["warn"]


# --- a recusa da PÁGINA DE LOGIN também fecha o alerta do navegador que não abriu ----

def _navegador_falhou_no_salvar(cliente, db, eid) -> None:
    """Primeiro passo comum: o Chromium não abre ao salvar a credencial."""
    r = cliente.put(f"/api/v1/escolas/{eid}/sync/credenciais/matific",
                    json={"usuario": "u", "senha": "p"})
    assert r.status_code == 200, r.text
    assert r.json()["codigo"] == "navegador_indisponivel"
    assert _abertos(db, eid) == [("plataforma_indisponivel", "critico")]


def _conector_com_navegador(monkeypatch, nav) -> None:
    monkeypatch.setitem(connectors._REGISTRO, "matific", ConectorMatific(_fabrica(nav)))


def _testar_ou_salvar(cliente, eid, como):
    if como == "testar":
        return cliente.post(f"/api/v1/escolas/{eid}/sync/credenciais/matific/testar")
    return cliente.put(f"/api/v1/escolas/{eid}/sync/credenciais/matific",
                       json={"usuario": "u", "senha": "p"})


@pytest.mark.parametrize("como", ["testar", "salvar"])
def test_navegador_que_falha_depois_senha_recusada_deixa_so_o_alerta_da_senha(
        cliente, db, escola_completa, monkeypatch, como):
    eid = escola_completa["escola"].id
    monkeypatch.setattr(service, "disparar_em_thread", lambda _id: None)
    _conector_com_navegador_que_nao_abre(monkeypatch)
    _navegador_falhou_no_salvar(cliente, db, eid)

    # O navegador voltou a abrir; a página de login respondeu e recusou a senha.
    _conector_com_navegador(monkeypatch, NavegadorFake(logado=False, erro_login=True))
    r = _testar_ou_salvar(cliente, eid, como)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is False and r.json()["codigo"] == "senha_invalida"
    assert _status_da_credencial(db, eid) == "invalida"
    # Antes: [('plataforma_indisponivel', 'critico'), ('senha_invalida', 'critico')].
    assert _abertos(db, eid) == [("senha_invalida", "critico")]


@pytest.mark.parametrize("nav, codigo, alerta", [
    (lambda: NavegadorFake(bloqueado=True), "captcha", ("captcha", "warn")),
    (lambda: NavegadorFake(logado=False), "falha_auth", ("falha_autenticacao", "warn")),
])
def test_outra_resposta_da_pagina_de_login_tambem_fecha_o_alerta_do_navegador(
        cliente, db, escola_completa, monkeypatch, nav, codigo, alerta):
    eid = escola_completa["escola"].id
    _conector_com_navegador_que_nao_abre(monkeypatch)
    _navegador_falhou_no_salvar(cliente, db, eid)

    _conector_com_navegador(monkeypatch, nav())
    r = _testar_ou_salvar(cliente, eid, "testar")
    assert r.json()["ok"] is False and r.json()["codigo"] == codigo, r.text
    assert _status_da_credencial(db, eid) == "nao_validada"    # não é senha errada
    assert _abertos(db, eid) == [alerta]


def test_navegador_que_cai_no_meio_do_teste_mantem_o_alerta_do_navegador(
        cliente, db, escola_completa, monkeypatch):
    """Guarda: ``erro_navegador`` (a falha inesperada no meio do teste, como o
    navegador que caiu) não prova que o navegador está bom — o alerta dele fica."""
    eid = escola_completa["escola"].id
    _conector_com_navegador_que_nao_abre(monkeypatch)
    _navegador_falhou_no_salvar(cliente, db, eid)

    _conector_com_navegador(monkeypatch, _NavQueCai(_target_closed()))
    r = _testar_ou_salvar(cliente, eid, "testar")
    assert r.json()["ok"] is False and r.json()["codigo"] == "erro_navegador", r.text
    assert _abertos(db, eid) == [("erro_navegador", "warn"),
                                 ("plataforma_indisponivel", "critico")]


# --- o conjunto inteiro, direto em ``_registrar_validacao`` -------------------------
# A lista é escrita aqui de propósito (não lida de ``service.CODIGOS_RESPOSTA_DO_LOGIN``):
# tirar um código do conjunto deixa o caso dele vermelho, e pôr um novo quebra a
# conferência abaixo — quem mexe no conjunto revê o teste.
_RESPOSTAS_DO_LOGIN = ["captcha", "falha_auth", "mfa", "pagina_login", "sem_escola",
                       "senha_expirada", "senha_invalida"]


def test_conjunto_das_respostas_do_login_e_o_esperado():
    assert service.CODIGOS_RESPOSTA_DO_LOGIN == frozenset(_RESPOSTAS_DO_LOGIN)


def _credencial_com_alerta_do_navegador(db, eid):
    """A credencial salva e o alerta crítico do Chromium que não abriu, aberto antes."""
    linha = vault.salvar_credencial(db, eid, "matific", Credenciais(usuario="u", senha="p"))
    tipo, severidade = service.alerta_do_codigo("navegador_indisponivel")
    service.abrir_alerta(db, eid, "matific", tipo, "o navegador não abriu (fictício)",
                         severidade=severidade)
    db.commit()
    assert _abertos(db, eid) == [("plataforma_indisponivel", "critico")]
    return linha


@pytest.mark.parametrize("codigo", _RESPOSTAS_DO_LOGIN)
def test_cada_resposta_da_pagina_de_login_fecha_o_alerta_do_navegador(
        db, escola_completa, codigo):
    eid = escola_completa["escola"].id
    linha = _credencial_com_alerta_do_navegador(db, eid)

    sync_router._registrar_validacao(db, eid, "matific", linha, ResultadoValidacao(
        ok=False, mensagem="x", codigo=codigo))
    db.commit()
    # Só o alerta da recusa fica aberto; o do navegador que não abriu foi fechado.
    assert _abertos(db, eid) == [service.alerta_do_codigo(codigo)]


@pytest.mark.parametrize("codigo", ["erro_navegador", "navegador_indisponivel", "timeout",
                                    None])
def test_falha_que_nao_e_resposta_da_pagina_de_login_mantem_o_alerta_do_navegador(
        db, escola_completa, codigo):
    """Guarda: o navegador que caiu no meio, o que não abriu de novo, o tempo esgotado
    e o resultado SEM código (o ``falha_auth`` de reserva é só o tipo do alerta) não
    provam que a página de login respondeu — o alerta do navegador continua aberto."""
    eid = escola_completa["escola"].id
    linha = _credencial_com_alerta_do_navegador(db, eid)

    sync_router._registrar_validacao(db, eid, "matific", linha, ResultadoValidacao(
        ok=False, mensagem="x", codigo=codigo))
    db.commit()
    esperado = {("plataforma_indisponivel", "critico"),
                service.alerta_do_codigo(codigo or "falha_auth")}
    assert _abertos(db, eid) == sorted(esperado)
