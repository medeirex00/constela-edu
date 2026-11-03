"""Uma EXECUÇÃO recusada pela página de login fecha o alerta do navegador que não abriu.

Antes (resíduo da revisão de 01/11): o "Testar conexão" já fechava o alerta crítico
'plataforma_indisponivel' (``navegador_indisponivel``: o Chromium deste servidor não
abriu) quando a página de login respondia com uma recusa, mas a execução não. No
"Sincronizar agora" — o caminho da demo, com o agendador desligado —, a execução 1 sem
navegador e a execução 2 recusada pela página de login (senha, o CAPTCHA do Matific a
partir do datacenter, login não confirmado) deixavam dois alertas abertos: "a
plataforma está indisponível" ao lado do da recusa. Agora ``service._tratar_falha``
fecha o do navegador antes de abrir o da recusa, com o mesmo conjunto do teste de
conexão (``service.CODIGOS_RESPOSTA_DO_LOGIN``). Sem prova de que o navegador abriu
(conector sem sessão de navegador), o que não abriu de novo, o tempo esgotado, o
download que falhou e a falha inesperada não fecham; o navegador que CAI no meio é
``navegador_indisponivel`` e também não fecha (fim do arquivo).

Sem navegador real nem rede: o ``playwright.async_api`` é trocado por um falso (o mesmo
de ``test_navegador_indisponivel``) e a página de login é o navegador fake de
``test_sync``.
"""
from __future__ import annotations

import pytest

from app.core.config import settings
from app.models.sincronizacao import SincronizacaoExecucao
from app.sync import connectors, service, vault
from app.sync.connectors import navegador
from app.sync.connectors.matific import ConectorMatific
from app.sync.interfaces import Credenciais, ErroConector
from tests.test_sync import ConectorFake, NavegadorFake, _fabrica
from tests.test_sync_alerta_apos_teste_ok import (
    _RESPOSTAS_DO_LOGIN,
    _abertos,
    _conector_com_navegador_que_nao_abre,
    _status_da_credencial,
)


@pytest.fixture(autouse=True)
def _agendador_desligado(monkeypatch):
    """Como na produção e na demo: sem agendador, a falha recuperável não ganha nova
    tentativa na fila (a próxima execução é o clique seguinte)."""
    monkeypatch.setattr(settings, "SYNC_SCHEDULER_ENABLED", False)


def _salvar_credencial(db, eid) -> None:
    vault.salvar_credencial(db, eid, "matific", Credenciais(usuario="u", senha="p"))
    db.commit()


# --- o caminho da demo: "Sincronizar agora" pela rota ------------------------------

def _sincronizar_agora(cliente, db, eid, monkeypatch) -> SincronizacaoExecucao:
    """O botão "Sincronizar agora" do Matific: a rota enfileira e dispara a thread; aqui
    a thread é a chamada de ``executar`` logo depois da resposta, na sessão do teste."""
    disparadas: list[int] = []
    monkeypatch.setattr(service, "disparar_em_thread", disparadas.append)
    r = cliente.post(f"/api/v1/escolas/{eid}/sync/agora", params={"plataforma": "matific"})
    assert r.status_code == 200, r.text
    assert len(disparadas) == 1, disparadas
    db.expire_all()
    ex = db.get(SincronizacaoExecucao, disparadas[0])
    service.executar(db, ex)
    return ex


def _alertas_da_tela(cliente, eid) -> list[tuple[str, str]]:
    """Os alertas abertos como a tela de Sincronização os lê."""
    r = cliente.get(f"/api/v1/escolas/{eid}/sync/alertas", params={"resolvido": "false"})
    assert r.status_code == 200, r.text
    return sorted((a["tipo"], a["severidade"]) for a in r.json())


@pytest.mark.parametrize("nav, codigo, alerta", [
    (lambda: NavegadorFake(logado=False, erro_login=True), "senha_invalida",
     ("senha_invalida", "critico")),
    (lambda: NavegadorFake(bloqueado=True), "captcha", ("captcha", "warn")),
    (lambda: NavegadorFake(logado=False), "falha_auth", ("falha_autenticacao", "warn")),
])
def test_sincronizar_agora_recusado_no_login_depois_do_navegador_que_nao_abriu(
        cliente, db, escola_completa, monkeypatch, nav, codigo, alerta):
    eid = escola_completa["escola"].id
    _salvar_credencial(db, eid)

    # Execução 1: o Chromium deste servidor não abre.
    _conector_com_navegador_que_nao_abre(monkeypatch)
    ex1 = _sincronizar_agora(cliente, db, eid, monkeypatch)
    assert (ex1.status, ex1.motivo) == ("erro", "navegador_indisponivel")
    assert _alertas_da_tela(cliente, eid) == [("plataforma_indisponivel", "critico")]

    # Execução 2: o navegador abriu; a página de login respondeu e recusou.
    monkeypatch.setitem(connectors._REGISTRO, "matific", ConectorMatific(_fabrica(nav())))
    ex2 = _sincronizar_agora(cliente, db, eid, monkeypatch)
    assert (ex2.status, ex2.motivo) == ("erro", codigo)
    # Antes: [('plataforma_indisponivel', 'critico'), <o da recusa>] — dois na tela.
    assert _alertas_da_tela(cliente, eid) == [alerta]
    # Só a senha recusada marca a credencial como 'invalida' (como antes).
    assert (_status_da_credencial(db, eid) == "invalida") is (codigo == "senha_invalida")


# --- o conjunto inteiro, direto na execução ----------------------------------------

def _executar(db, eid) -> SincronizacaoExecucao:
    ex = service.enfileirar(db, eid, "matific", origem="manual")
    service.executar(db, ex)
    return ex


def _execucao_sem_navegador(db, eid, monkeypatch) -> None:
    """Execução 1, comum aos casos: o Chromium deste servidor não abre."""
    _salvar_credencial(db, eid)
    _conector_com_navegador_que_nao_abre(monkeypatch)
    ex = _executar(db, eid)
    assert ex.status == "erro"
    assert _abertos(db, eid) == [("plataforma_indisponivel", "critico")]


@pytest.mark.parametrize("codigo", _RESPOSTAS_DO_LOGIN)
def test_cada_resposta_da_pagina_de_login_na_execucao_fecha_o_alerta_do_navegador(
        db, escola_completa, monkeypatch, codigo):
    eid = escola_completa["escola"].id
    _execucao_sem_navegador(db, eid, monkeypatch)

    erro = ErroConector("recusado pela página de login (fictício)", codigo=codigo,
                        recuperavel=False)
    monkeypatch.setitem(connectors._REGISTRO, "matific", ConectorFake(erro=erro))
    ex = _executar(db, eid)
    assert (ex.status, ex.motivo) == ("erro", codigo)
    # Só o alerta da recusa fica aberto; o do navegador que não abriu foi fechado.
    assert _abertos(db, eid) == [service.alerta_do_codigo(codigo)]


@pytest.mark.parametrize("erro, codigo", [
    # O navegador que caiu no meio não prova que ele está bom.
    (ErroConector("o navegador caiu (fictício)", codigo="erro_navegador",
                  recuperavel=True), "erro_navegador"),
    # O Chromium que não abriu de novo: o mesmo alerta continua aberto (um só).
    (ErroConector(navegador.NAVEGADOR_NAO_ABRIU, codigo="navegador_indisponivel",
                  recuperavel=True), "navegador_indisponivel"),
    # Falhas da coleta e do Constela: nenhuma é resposta da página de login.
    (ErroConector("demorou (fictício)", codigo="timeout", recuperavel=True), "timeout"),
    (ErroConector("download vazio (fictício)", codigo="falha_download", recuperavel=True),
     "falha_download"),
    (RuntimeError("defeito fictício"), "erro_inesperado"),
])
def test_falha_que_nao_e_resposta_do_login_na_execucao_mantem_o_alerta_do_navegador(
        db, escola_completa, monkeypatch, erro, codigo):
    eid = escola_completa["escola"].id
    _execucao_sem_navegador(db, eid, monkeypatch)

    monkeypatch.setitem(connectors._REGISTRO, "matific", ConectorFake(erro=erro))
    ex = _executar(db, eid)
    assert (ex.status, ex.motivo) == ("erro", codigo)
    esperado = {("plataforma_indisponivel", "critico"), service.alerta_do_codigo(codigo)}
    assert _abertos(db, eid) == sorted(esperado)


# --- o navegador ABRIU e a coleta falhou (ou voltou incompleta) depois ----------------
# Resíduo da revisão da rodada 8: a execução que prova que o navegador abriu e a
# plataforma respondeu deixava o 'plataforma_indisponivel' crítico aberto quando não
# terminava com uma resposta da página de login — 'sem_dados', 'parcial' que gravou
# dado, school_student 401/403 (dois críticos na tela) e HTTP 500. Agora
# ``ConectorNavegador._executar_login`` marca ``coleta['navegador_abriu']`` quando a
# página de login responde, ``_encerrar_com_falha`` usa a marca (ou a coleta que
# voltou) e ``_concluir`` fecha o alerta em toda coleta que voltou. O navegador que CAI
# no meio da execução é ``navegador_indisponivel`` (como no ao vivo e no diagnóstico)
# e mantém o alerta — revisão cética de 01/11.

from tests._sync_nucleo_fakes import PlacarFake, credencial, instalar, novo_aluno, rodar  # noqa: E402
from tests.test_navegador_indisponivel import (  # noqa: E402
    _NAVEGADOR_QUE_CAIU,
    _NavQueCai,
    _target_closed,
)

_K1, _K2 = "3 ANO A (300396804)", "4 ANO B (300397061)"


def _execucao_1_sem_navegador_matific(db, eid, monkeypatch) -> None:
    credencial(db, eid, "matific")
    _conector_com_navegador_que_nao_abre(monkeypatch)
    ex, erro = rodar(db, eid, "matific")
    assert erro is None and (ex.status, ex.motivo) == ("erro", "navegador_indisponivel")
    assert _abertos(db, eid) == [("plataforma_indisponivel", "critico")]


@pytest.mark.parametrize("caso", ["sem_dados", "ss401", "ss403", "ss500", "lb403_parcial"])
def test_navegador_que_abriu_fecha_o_alerta_mesmo_quando_a_coleta_falha_depois(
        db, escola_completa, monkeypatch, caso):
    eid = escola_completa["escola"].id
    _execucao_1_sem_navegador_matific(db, eid, monkeypatch)

    placar = PlacarFake()
    placar.linhas = [] if caso == "sem_dados" else [
        ("u-a", escola_completa["alunos"][0].nome, _K1, 40, 10)]
    if caso.startswith("ss"):
        placar.status_ss = int(caso[2:])
    elif caso == "lb403_parcial":
        placar.status_lb = 403
    instalar(monkeypatch, placar=placar)
    ex, erro = rodar(db, eid, "matific")
    assert erro is None
    abertos = _abertos(db, eid)
    # Antes: ('plataforma_indisponivel', 'critico') ficava ao lado do alerta novo.
    assert ("plataforma_indisponivel", "critico") not in abertos, (ex.status, ex.motivo,
                                                                   abertos)
    if caso in ("ss401", "ss403"):
        assert abertos == [("sem_acesso_ao_dado", "critico")]


def test_parcial_que_falhou_depois_de_gravar_fecha_o_alerta_do_navegador(
        db, escola_completa, monkeypatch):
    from app.models import Turma
    from app.routers import importacoes as imp
    eid = escola_completa["escola"].id
    _execucao_1_sem_navegador_matific(db, eid, monkeypatch)
    a = escola_completa["alunos"][0]
    t2 = Turma(escola_id=eid, nome="4º Ano B", ano_escolar="4º Ano", ano_letivo=2026)
    db.add(t2)
    db.flush()
    d = novo_aluno(db, eid, t2, "Crianca Ficticia Quarto Ano")
    db.commit()
    placar = PlacarFake()
    placar.linhas = [("u-a", a.nome, _K1, 40, 10), ("u-d", d.nome, _K2, 8, 2)]
    instalar(monkeypatch, placar=placar)
    original = imp._importar_matific

    def quebra(db_, escola_id, importacao, aluno, *a_, **k):
        r = original(db_, escola_id, importacao, aluno, *a_, **k)
        if aluno.id == d.id:
            raise RuntimeError("falha simulada depois de gravar")
        return r
    monkeypatch.setattr(imp, "_importar_matific", quebra)
    ex, _ = rodar(db, eid, "matific")
    assert ex.status == "parcial"
    assert ("plataforma_indisponivel", "critico") not in _abertos(db, eid)


def _todos(db, eid) -> list[tuple[str, str, bool]]:
    from sqlalchemy import select

    from app.models.sincronizacao import SincronizacaoAlerta
    db.expire_all()
    return sorted((a.tipo, a.severidade, a.resolvido) for a in db.execute(
        select(SincronizacaoAlerta).where(SincronizacaoAlerta.escola_id == eid)).scalars())


@pytest.mark.parametrize("i", range(len(_NAVEGADOR_QUE_CAIU)))
def test_navegador_que_cai_na_primeira_pagina_mantem_o_alerta(db, escola_completa,
                                                              monkeypatch, i):
    """Antes: 'erro_inesperado' warn e o crítico fechado como se o navegador estivesse
    bom (a marca nascia quando a fábrica devolvia o objeto)."""
    eid = escola_completa["escola"].id
    _execucao_1_sem_navegador_matific(db, eid, monkeypatch)
    monkeypatch.setitem(connectors._REGISTRO, "matific",
                        ConectorMatific(_fabrica(_NavQueCai(_NAVEGADOR_QUE_CAIU[i]()))))
    ex, erro = rodar(db, eid, "matific")
    assert erro is None
    assert (ex.status, ex.motivo) == ("erro", "navegador_indisponivel")
    # Um só alerta, nunca fechado (nada de falso "resolvido" no histórico).
    assert _todos(db, eid) == [("plataforma_indisponivel", "critico", False)]


def test_navegador_que_cai_no_meio_da_coleta_mantem_o_alerta(db, escola_completa,
                                                             monkeypatch):
    """O conector embrulha a queda num 'falha_download' ("falhou na API"): antes o aviso
    culpava a plataforma e o crítico era fechado."""
    eid = escola_completa["escola"].id
    _execucao_1_sem_navegador_matific(db, eid, monkeypatch)
    placar = PlacarFake()
    placar.linhas = [("u-a", escola_completa["alunos"][0].nome, _K1, 40, 10)]
    placar.excecao_ss = _target_closed()
    instalar(monkeypatch, placar=placar)
    ex, erro = rodar(db, eid, "matific")
    assert erro is None
    assert (ex.status, ex.motivo) == ("erro", "navegador_indisponivel")
    assert _todos(db, eid) == [("plataforma_indisponivel", "critico", False)]


def test_fechamento_do_alerta_vai_ao_log_da_execucao(db, escola_completa, monkeypatch):
    from sqlalchemy import select

    from app.models.sincronizacao import SincronizacaoLog
    eid = escola_completa["escola"].id
    _execucao_1_sem_navegador_matific(db, eid, monkeypatch)
    placar = PlacarFake()
    placar.linhas = [("u-a", escola_completa["alunos"][0].nome, _K1, 40, 10)]
    placar.status_ss = 403
    instalar(monkeypatch, placar=placar)
    ex, _ = rodar(db, eid, "matific")
    mensagens = db.execute(select(SincronizacaoLog.mensagem).where(
        SincronizacaoLog.execucao_id == ex.id)).scalars().all()
    assert any(m.startswith("Alerta “plataforma indisponível”") for m in mensagens), mensagens


def test_parcial_cujo_fechamento_falha_ainda_fecha_o_alerta(db, escola_completa,
                                                           monkeypatch):
    """A coleta voltou, gravou e o próprio fechamento 'parcial' falhou (rollback): antes
    o rollback desfazia o fechamento do alerta e o crítico ficava aberto."""
    from app.models import Turma
    from app.routers import importacoes as imp
    eid = escola_completa["escola"].id
    _execucao_1_sem_navegador_matific(db, eid, monkeypatch)
    a = escola_completa["alunos"][0]
    t2 = Turma(escola_id=eid, nome="4º Ano B", ano_escolar="4º Ano", ano_letivo=2026)
    db.add(t2)
    db.flush()
    d = novo_aluno(db, eid, t2, "Crianca Ficticia Quarto Ano")
    db.commit()
    placar = PlacarFake()
    placar.linhas = [("u-a", a.nome, _K1, 40, 10), ("u-d", d.nome, _K2, 8, 2)]
    instalar(monkeypatch, placar=placar)
    original = imp._importar_matific

    def quebra(db_, escola_id, importacao, aluno, *a_, **k):
        r = original(db_, escola_id, importacao, aluno, *a_, **k)
        if aluno.id == d.id:
            raise RuntimeError("falha simulada depois de gravar")
        return r

    def mensagem_que_falha(*_a, **_k):
        raise RuntimeError("falha simulada ao fechar a parcial")
    monkeypatch.setattr(imp, "_importar_matific", quebra)
    monkeypatch.setattr(service, "_mensagem_parcial", mensagem_que_falha)
    ex, _ = rodar(db, eid, "matific")
    assert (ex.status, ex.motivo) == ("erro", "erro_inesperado")
    assert ("plataforma_indisponivel", "critico") not in _abertos(db, eid)


def test_coleta_que_voltou_sem_navegador_e_aplicacao_que_falhou_fecham_o_alerta(
        db, escola_completa, monkeypatch):
    """Conector sem sessão de navegador: a coleta VOLTOU (prova de que o servidor chega à
    plataforma) e a aplicação falhou antes de gravar — o crítico do navegador fecha."""
    from app.sync import orchestrator
    from app.sync.interfaces import ArquivoObtido
    eid = escola_completa["escola"].id
    _execucao_sem_navegador(db, eid, monkeypatch)
    arq = ArquivoObtido(conteudo=b"PKx", nome_arquivo="m.xlsx", plataforma="matific")
    monkeypatch.setitem(connectors._REGISTRO, "matific", ConectorFake(arquivos=[arq]))

    def aplicar_que_falha(*_a, **_k):
        raise RuntimeError("defeito fictício na aplicação")
    monkeypatch.setattr(orchestrator, "aplicar_arquivo", aplicar_que_falha)
    ex = _executar(db, eid)
    assert (ex.status, ex.motivo) == ("erro", "erro_inesperado")
    assert _abertos(db, eid) == [("erro_inesperado", "warn")]
