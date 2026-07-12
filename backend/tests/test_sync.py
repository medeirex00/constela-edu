"""Testes do Módulo de Sincronização Automática.

Cobre: cofre de credenciais (cifra/decifra/isolamento), conectores (fluxo com
navegador fake, sem browser real nem conta), e o orquestrador reusando o
pipeline de importação existente (conector → confirmar → snapshot).
"""
import asyncio

import pytest
from sqlalchemy import select

from app.sync import connectors, vault
from app.sync.interfaces import (
    ArquivoObtido,
    Contexto,
    Credenciais,
    Estrategia,
)


# --------------------------------------------------------------------------
# Navegador fake — exercita TODO o conector sem Playwright nem conta real
# --------------------------------------------------------------------------
class NavegadorFake:
    def __init__(self, *, logado=True, erro_login=False, bloqueado=False,
                 conteudo=b"PKxlsxfake"):
        self.logado, self.erro_login, self.conteudo = logado, erro_login, conteudo
        self.bloqueado = bloqueado          # simula CAPTCHA/desafio anti-robô
        self.valores_preenchidos: list[str] = []

    async def ir_para(self, url): pass
    async def preencher(self, seletor, valor): self.valores_preenchidos.append(valor)
    async def clicar(self, seletor): pass
    async def esperar(self, seletor, timeout_s=20):
        # Distingue "cheguei na área logada" (usa self.logado) de "o formulário
        # de login apareceu" (True) — o conector espera o form antes de digitar.
        marcas_logado = ("logout", "sair", "dashboard", "painel", "nav")
        if any(m in seletor for m in marcas_logado):
            return self.logado
        return True
    async def visivel(self, seletor):
        # Distingue o seletor de CAPTCHA/bloqueio do de mensagem de erro.
        marcas_bloqueio = ("captcha", "recaptcha", "hcaptcha", "challenge", "cloudflare")
        if any(m in seletor for m in marcas_bloqueio):
            return self.bloqueado
        return self.erro_login
    async def texto(self, seletor): return ""
    async def url_atual(self): return "https://x"
    async def baixar(self, seletor, timeout_s=60): return (self.conteudo, "rel.xlsx")
    async def fechar(self): pass


def _fabrica(nav):
    async def fab(**_kw):
        return nav
    return fab


def _contexto(escola_id=1):
    return Contexto(escola_id=escola_id, execucao_id=None,
                    log=lambda etapa, nivel, msg: None)


# --------------------------------------------------------------------------
# Cofre de credenciais
# --------------------------------------------------------------------------
def test_cofre_cifra_decifra_roundtrip(db, escola_completa):
    escola = escola_completa["escola"]
    vault.salvar_credencial(db, escola.id, "matific",
                            Credenciais(usuario="prof@x", senha="s3nh4-secreta"))
    linha = vault.obter_linha(db, escola.id, "matific")
    # em repouso está CIFRADO (a senha não aparece em claro)
    assert "s3nh4-secreta" not in linha.segredo_cifrado
    assert linha.status == "nao_validada"
    # decifra devolve o original
    cred = vault.obter_credencial(db, escola.id, "matific")
    assert cred.usuario == "prof@x" and cred.senha == "s3nh4-secreta"


def test_cofre_isola_por_escola(db, escola_completa):
    from app.models import Escola
    outra = Escola(nome="OUTRA", ano_letivo_ativo=2026)
    db.add(outra)
    db.flush()
    vault.salvar_credencial(db, escola_completa["escola"].id, "matific",
                            Credenciais(usuario="a", senha="b"))
    # a outra escola não enxerga a credencial da primeira
    assert vault.obter_credencial(db, outra.id, "matific") is None


def test_cofre_salvar_reseta_status_e_incrementa_versao(db, escola_completa):
    escola = escola_completa["escola"]
    l1 = vault.salvar_credencial(db, escola.id, "elefante",
                                 Credenciais(usuario="a", senha="b"))
    vault.marcar_status(db, l1, "valida")
    l2 = vault.salvar_credencial(db, escola.id, "elefante",
                                 Credenciais(usuario="a", senha="nova"))
    assert l2.status == "nao_validada" and l2.token_version == 2


# --------------------------------------------------------------------------
# Conectores
# --------------------------------------------------------------------------
def test_registro_tem_manual_matific_elefante():
    plats = {c.plataforma for c in connectors.listar()}
    assert {"manual", "matific", "elefante"} <= plats
    assert set(connectors.plataformas_automatizaveis()) == {"matific", "elefante"}
    assert connectors.obter("manual").estrategia == Estrategia.UPLOAD_MANUAL
    assert connectors.obter("matific").estrategia == Estrategia.NAVEGADOR


@pytest.mark.parametrize("plataforma", ["matific", "elefante"])
def test_testar_credenciais_ok_e_erro(plataforma):
    Classe = type(connectors.obter(plataforma))
    cred = Credenciais(usuario="prof@x", senha="segredo-nao-vaza")

    ok = asyncio.run(Classe(_fabrica(NavegadorFake(logado=True)))
                     .testar_credenciais(cred, _contexto()))
    assert ok.ok and ok.codigo == "ok"

    ruim = asyncio.run(Classe(_fabrica(NavegadorFake(logado=False, erro_login=True)))
                       .testar_credenciais(cred, _contexto()))
    assert not ruim.ok and ruim.codigo == "senha_invalida"


@pytest.mark.parametrize("plataforma", ["matific", "elefante"])
def test_testar_credenciais_erro_cru_do_navegador_nao_propaga(plataforma):
    """Se o navegador lança uma exceção CRUA (seletor mudou/timeout — NÃO
    ErroConector), testar_credenciais devolve ok=False claro (codigo
    'erro_navegador') em vez de estourar — a causa raiz do 500 em produção."""
    class NavegadorQuebra(NavegadorFake):
        async def preencher(self, seletor, valor):
            # imita o erro do Playwright: cita o seletor, nunca o valor digitado
            raise RuntimeError(f"Timeout 30000ms waiting for selector {seletor}")

    Classe = type(connectors.obter(plataforma))
    res = asyncio.run(Classe(_fabrica(NavegadorQuebra()))
                      .testar_credenciais(Credenciais(usuario="u", senha="p-secreta"),
                                          _contexto()))
    assert res.ok is False
    assert res.codigo == "erro_navegador"
    assert "p-secreta" not in res.mensagem          # não vaza a senha na mensagem


@pytest.mark.parametrize("plataforma", ["matific", "elefante"])
def test_login_sem_formulario_da_diagnostico_claro(plataforma):
    """Quando a página de login não mostra o formulário (endereço mudou,
    redirecionou p/ a home, ou exigiu verificação), o conector dá um erro CLARO
    e ACIONÁVEL (código 'pagina_login', com o endereço alcançado) — não um
    timeout cru nem a mensagem genérica."""
    class SemFormulario(NavegadorFake):
        async def esperar(self, seletor, timeout_s=20):
            return False  # nada aparece
        async def url_atual(self):
            return "https://www.matific.com/"  # redirecionou para a home

    Classe = type(connectors.obter(plataforma))
    res = asyncio.run(Classe(_fabrica(SemFormulario()))
                      .testar_credenciais(Credenciais(usuario="u", senha="p"),
                                          _contexto()))
    assert res.ok is False
    assert res.codigo == "pagina_login"
    assert "endereço atual" in res.mensagem and "manual" in res.mensagem.lower()


@pytest.mark.parametrize("plataforma", ["matific", "elefante"])
def test_login_detecta_captcha_bloqueio(plataforma):
    """Se a plataforma mostra CAPTCHA/desafio anti-robô, o conector devolve um
    erro ESPECÍFICO (código 'captcha') orientando a importação manual — não um
    'não confirmei o login' genérico."""
    Classe = type(connectors.obter(plataforma))
    res = asyncio.run(Classe(_fabrica(NavegadorFake(bloqueado=True)))
                      .testar_credenciais(Credenciais(usuario="u", senha="p"),
                                          _contexto()))
    assert res.ok is False
    assert res.codigo == "captcha"
    assert "manual" in res.mensagem.lower()


def test_login_registra_etapas_no_log():
    """O fluxo de login registra etapas CLARAS (abrir → formulário → enviar →
    resultado) em SincronizacaoLog, sem vazar a senha."""
    etapas: list[str] = []
    ctx = Contexto(escola_id=1, execucao_id=None,
                   log=lambda etapa, nivel, msg: etapas.append(msg))
    Classe = type(connectors.obter("matific"))
    asyncio.run(Classe(_fabrica(NavegadorFake(logado=True)))
                .testar_credenciais(Credenciais(usuario="u", senha="TOPSECRET"), ctx))
    texto = " | ".join(etapas)
    assert "Abrindo a página de login" in texto
    assert "Formulário encontrado" in texto
    assert "Enviando o formulário" in texto
    assert "Login confirmado" in texto
    assert "TOPSECRET" not in texto        # a senha NUNCA aparece no log


@pytest.mark.parametrize("plataforma", ["matific", "elefante"])
def test_diagnosticar_login_sem_credenciais(plataforma):
    """O diagnóstico (sem credenciais) abre a página e reporta se o formulário
    aparece e se há bloqueio — para validar o ambiente sem contas reais."""
    Classe = type(connectors.obter(plataforma))
    ok = asyncio.run(Classe(_fabrica(NavegadorFake()))
                     .diagnosticar_login(_contexto()))
    assert ok["formulario_encontrado"] is True
    # O diagnóstico confirma os TRÊS alvos do preenchimento/envio (usuário,
    # senha e botão) — assim "preencher usuário e senha" e "submeter" ficam
    # validados no ambiente real SEM credenciais.
    assert ok["usuario_encontrado"] is True
    assert ok["senha_encontrada"] is True
    assert ok["botao_encontrado"] is True
    assert ok["pre_passos_ok"] is True
    assert ok["bloqueio_detectado"] is False
    assert ok["erro"] is None
    assert ok["plataforma"] == plataforma

    bloq = asyncio.run(Classe(_fabrica(NavegadorFake(bloqueado=True)))
                       .diagnosticar_login(_contexto()))
    assert bloq["bloqueio_detectado"] is True


def test_conector_nao_vaza_senha_no_log():
    registros: list[str] = []
    ctx = Contexto(escola_id=1, execucao_id=None,
                   log=lambda e, n, m: registros.append(f"{e}{n}{m}"))
    Classe = type(connectors.obter("matific"))
    asyncio.run(Classe(_fabrica(NavegadorFake())).testar_credenciais(
        Credenciais(usuario="prof@x", senha="TOPSECRET"), ctx))
    assert all("TOPSECRET" not in r for r in registros)


def test_sincronizar_devolve_arquivo_para_pipeline():
    Classe = type(connectors.obter("matific"))
    arquivos = asyncio.run(Classe(_fabrica(NavegadorFake(conteudo=b"PKdados")))
                           .sincronizar(Credenciais(usuario="a", senha="b"), _contexto()))
    assert len(arquivos) == 1
    assert arquivos[0].plataforma == "matific" and arquivos[0].conteudo == b"PKdados"


# --------------------------------------------------------------------------
# Orquestrador — reusa o pipeline de importação existente
# --------------------------------------------------------------------------
def test_orquestrador_reusa_pipeline_cria_snapshot(db, escola_completa, monkeypatch):
    from app.models.plataformas import Importacao, SnapshotMatific
    from app.services import importacao as svc
    from app.sync import orchestrator

    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]  # "Ana Beatriz Souza"

    # _parsear controlado: uma linha Matific com o nome real da aluna.
    def fake_parsear(arquivo):
        analise = svc.Analise(plataforma="matific", formato="resumo",
                              turma_detectada="")
        analise.linhas = [svc.LinhaImportacao(
            numero=1, nome="Ana Beatriz Souza",
            dados={"atividades": 20, "estrelas": 5, "pontuacao_media": 85.0})]
        return analise, "xlsx"

    monkeypatch.setattr(orchestrator, "_parsear", fake_parsear)
    # sem tocar o disco: sem token -> confirmar pula o arquivamento
    monkeypatch.setattr(orchestrator.imp, "_guardar_temporario", lambda *a, **k: None)

    arquivo = ArquivoObtido(conteudo=b"PKxlsx", nome_arquivo="matific.xlsx",
                            plataforma="matific")
    res = orchestrator.aplicar_arquivo(
        db, escola, arquivo, usuario_id=None, recalcular=True, contexto=_contexto(escola.id))

    assert res["qtd_alunos"] == 1 and res["sem_dados"] is False
    # o pipeline REAL rodou: existe snapshot Matific para a Ana + uma Importacao
    snap = db.execute(select(SnapshotMatific).where(
        SnapshotMatific.escola_id == escola.id,
        SnapshotMatific.aluno_id == ana.id)).scalars().first()
    assert snap is not None
    assert db.execute(select(Importacao).where(
        Importacao.escola_id == escola.id)).scalars().first() is not None


def test_orquestrador_resolve_ator_admin_da_escola(db, escola_completa):
    from app.sync import orchestrator
    escola = escola_completa["escola"]
    # scheduler (usuario_id=None) resolve um admin/coordenador ATIVO da escola
    ator = orchestrator._resolver_ator(db, escola.id, None)
    assert ator is not None and ator.escola_id == escola.id
    assert ator.cargo in ("admin", "coordenador")


# --------------------------------------------------------------------------
# Motor de execução (fila, ciclo de vida, retry, agenda)
# --------------------------------------------------------------------------
from app.sync.interfaces import Conector, ErroConector, ResultadoValidacao


class ConectorFake(Conector):
    plataforma = "matific"
    versao = "9.9.9"
    estrategia = Estrategia.NAVEGADOR

    def __init__(self, arquivos=None, erro=None):
        self._arqs = arquivos or []
        self._erro = erro

    async def testar_credenciais(self, cred, ctx):
        return ResultadoValidacao(True, "ok", "ok")

    async def localizar_relatorios(self, cred, ctx):
        return []

    async def obter(self, cred, rel, ctx):
        raise NotImplementedError

    async def sincronizar(self, cred, ctx):
        ctx.log("download", "info", "baixando (fake)")
        if self._erro:
            raise self._erro
        return self._arqs


def _analise_ana():
    from app.services import importacao as svc
    a = svc.Analise(plataforma="matific", formato="resumo", turma_detectada="")
    a.linhas = [svc.LinhaImportacao(numero=1, nome="Ana Beatriz Souza",
                dados={"atividades": 10, "estrelas": 3, "pontuacao_media": 70.0})]
    return a, "xlsx"


def test_enfileirar_e_idempotente(db, escola_completa):
    from app.sync import service
    e = escola_completa["escola"].id
    a = service.enfileirar(db, e, "matific", origem="manual")
    b = service.enfileirar(db, e, "matific", origem="manual")  # não duplica
    assert a.id == b.id and a.status == "fila"


def test_executar_sucesso_cria_snapshot_e_logs(db, escola_completa, monkeypatch):
    from app.models.plataformas import SnapshotMatific
    from app.models.sincronizacao import SincronizacaoLog
    from app.sync import connectors, orchestrator, service, vault
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]

    vault.salvar_credencial(db, escola.id, "matific", Credenciais(usuario="u", senha="p"))
    arq = ArquivoObtido(conteudo=b"PKx", nome_arquivo="m.xlsx", plataforma="matific")
    monkeypatch.setitem(connectors._REGISTRO, "matific", ConectorFake(arquivos=[arq]))
    monkeypatch.setattr(orchestrator, "_parsear", lambda a: _analise_ana())

    ex = service.enfileirar(db, escola.id, "matific", origem="manual")
    service.executar(db, ex)

    assert ex.status == "concluida" and ex.qtd_alunos == 1 and ex.qtd_arquivos == 1
    assert db.query(SnapshotMatific).filter_by(escola_id=escola.id, aluno_id=ana.id).first()
    assert db.query(SincronizacaoLog).filter_by(execucao_id=ex.id).count() > 0
    # sucesso marca a credencial como válida
    assert vault.obter_linha(db, escola.id, "matific").status == "valida"


def test_executar_erro_recuperavel_reenfileira_com_backoff(db, escola_completa, monkeypatch):
    from app.models.sincronizacao import SincronizacaoAlerta, SincronizacaoExecucao
    from app.sync import connectors, service, vault
    escola = escola_completa["escola"]
    vault.salvar_credencial(db, escola.id, "matific", Credenciais(usuario="u", senha="p"))
    erro = ErroConector("timeout", codigo="timeout", recuperavel=True)
    monkeypatch.setitem(connectors._REGISTRO, "matific", ConectorFake(erro=erro))

    ex = service.enfileirar(db, escola.id, "matific", origem="scheduler")
    service.executar(db, ex)

    assert ex.status == "erro"
    # abriu alerta de timeout
    assert db.query(SincronizacaoAlerta).filter_by(escola_id=escola.id, tipo="timeout").first()
    # re-enfileirou uma tentativa 2 com disponivel_em no futuro (backoff)
    retry = db.query(SincronizacaoExecucao).filter_by(
        escola_id=escola.id, tentativa=2, status="fila").first()
    assert retry is not None and retry.disponivel_em is not None


def test_executar_senha_invalida_marca_credencial_e_nao_reenfileira(db, escola_completa, monkeypatch):
    from app.models.sincronizacao import SincronizacaoExecucao
    from app.sync import connectors, service, vault
    escola = escola_completa["escola"]
    vault.salvar_credencial(db, escola.id, "matific", Credenciais(usuario="u", senha="p"))
    erro = ErroConector("senha ruim", codigo="senha_invalida", recuperavel=False)
    monkeypatch.setitem(connectors._REGISTRO, "matific", ConectorFake(erro=erro))

    ex = service.enfileirar(db, escola.id, "matific", origem="scheduler")
    service.executar(db, ex)

    assert ex.status == "erro"
    assert vault.obter_linha(db, escola.id, "matific").status == "invalida"
    # não recuperável: nenhuma tentativa 2
    assert db.query(SincronizacaoExecucao).filter_by(
        escola_id=escola.id, tentativa=2).first() is None


def test_calcular_proxima_cadencias(db, escola_completa):
    from datetime import datetime
    from app.models.sincronizacao import SincronizacaoConfig
    from app.sync import service
    base = datetime(2026, 7, 11, 10, 0, 0)  # naive
    manual = SincronizacaoConfig(escola_id=1, plataforma="matific",
                                 ativo=True, cadencia="manual")
    assert service.calcular_proxima(manual, base) is None
    diaria = SincronizacaoConfig(escola_id=1, plataforma="matific",
                                 ativo=True, cadencia="diaria", hora_local="03:00")
    prox = service.calcular_proxima(diaria, base)
    assert prox.hour == 3 and prox.day == 12  # próximo dia às 03:00


# --------------------------------------------------------------------------
# API — isolamento multi-tenant e RBAC
# --------------------------------------------------------------------------
def test_api_isola_escola_e_exige_credencial(cliente, escola_completa):
    escola_id = escola_completa["escola"].id
    # status da própria escola: 200
    assert cliente.get(f"/api/v1/escolas/{escola_id}/sync/status").status_code == 200
    # escola de OUTREM (id+999): escola_autorizada barra (403/404)
    r = cliente.get(f"/api/v1/escolas/{escola_id + 999}/sync/status")
    assert r.status_code in (403, 404)
    # sincronizar sem credencial configurada -> 400 claro
    r2 = cliente.post(f"/api/v1/escolas/{escola_id}/sync/agora")
    assert r2.status_code == 400


def test_api_salvar_credenciais_valida_e_status(cliente, escola_completa, monkeypatch):
    from app.sync import connectors, service
    e = escola_completa["escola"].id
    monkeypatch.setitem(connectors._REGISTRO, "matific", ConectorFake())
    monkeypatch.setattr(service, "disparar_em_thread", lambda _id: None)

    r = cliente.put(f"/api/v1/escolas/{e}/sync/credenciais/matific",
                    json={"usuario": "prof@x", "senha": "segredo"})
    assert r.status_code == 200 and r.json()["ok"] is True

    st = cliente.get(f"/api/v1/escolas/{e}/sync/status").json()
    matific = next(p for p in st["plataformas"] if p["plataforma"] == "matific")
    assert matific["credencial_status"] == "valida" and matific["conectada"] is True

    # agora /agora enfileira (thread mockada) e devolve a execução
    ag = cliente.post(f"/api/v1/escolas/{e}/sync/agora?plataforma=matific")
    assert ag.status_code == 200 and ag.json()[0]["plataforma"] == "matific"
    # aparece no histórico
    hist = cliente.get(f"/api/v1/escolas/{e}/sync/historico").json()
    assert any(x["plataforma"] == "matific" for x in hist)


def test_api_salvar_credenciais_nunca_500_em_erro_de_navegador(
        cliente, escola_completa, monkeypatch):
    """Regressão do 500 em produção: quando a validação do login estoura no
    navegador (seletor mudou/timeout), o PUT responde 200 com ok=False e
    mensagem clara — a credencial FICA salva, sem vazar a senha, sem 500."""
    from app.sync import connectors, service

    e = escola_completa["escola"].id

    class NavegadorQuebra(NavegadorFake):
        async def ir_para(self, url):
            raise RuntimeError("net::ERR_TIMED_OUT ao abrir a página de login")

    ConectorReal = type(connectors.obter("matific"))    # conector REAL, browser fake
    monkeypatch.setitem(connectors._REGISTRO, "matific",
                        ConectorReal(_fabrica(NavegadorQuebra())))
    monkeypatch.setattr(service, "disparar_em_thread", lambda _id: None)

    r = cliente.put(f"/api/v1/escolas/{e}/sync/credenciais/matific",
                    json={"usuario": "prof@x", "senha": "senha-secreta"})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["ok"] is False
    assert corpo["codigo"] == "erro_navegador"
    assert "senha-secreta" not in (corpo["mensagem"] or "")

    # a credencial FOI gravada (fica como configurada/invalida, revalidável)
    st = cliente.get(f"/api/v1/escolas/{e}/sync/status").json()
    matific = next(p for p in st["plataformas"] if p["plataforma"] == "matific")
    assert matific["credencial_status"] == "invalida"
    assert st["integracao_configurada"] is True


def test_api_salvar_credenciais_conector_fora_do_contrato_nao_da_500(
        cliente, escola_completa, monkeypatch):
    """Rede de segurança do endpoint: mesmo um conector que viole o contrato e
    estoure em testar_credenciais não pode virar 500."""
    from app.sync import connectors

    e = escola_completa["escola"].id

    class ConectorEstoura(ConectorFake):
        async def testar_credenciais(self, cred, ctx):
            raise RuntimeError("boom inesperado")

    monkeypatch.setitem(connectors._REGISTRO, "matific", ConectorEstoura())
    r = cliente.put(f"/api/v1/escolas/{e}/sync/credenciais/matific",
                    json={"usuario": "u", "senha": "p"})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is False


def test_api_config_agenda_calcula_proxima(cliente, escola_completa):
    e = escola_completa["escola"].id
    r = cliente.put(f"/api/v1/escolas/{e}/sync/config/matific",
                    json={"ativo": True, "cadencia": "diaria", "hora_local": "03:00"})
    assert r.status_code == 200 and r.json()["proxima_execucao"] is not None


def test_api_logs_e_alertas(cliente, escola_completa, db):
    from app.sync import service
    e = escola_completa["escola"].id
    ex = service.enfileirar(db, e, "matific", origem="manual")
    service.registrar_log(db, ex, "download", "info", "baixando teste")
    service.abrir_alerta(db, e, "matific", "timeout", "demorou")
    db.commit()

    logs = cliente.get(f"/api/v1/escolas/{e}/sync/logs?execucao_id={ex.id}").json()
    assert any("baixando teste" in x["mensagem"] for x in logs)
    al = cliente.get(f"/api/v1/escolas/{e}/sync/alertas?resolvido=false").json()
    assert len(al) == 1 and al[0]["tipo"] == "timeout"
    assert cliente.post(f"/api/v1/escolas/{e}/sync/alertas/{al[0]['id']}/resolver").status_code == 204
    assert cliente.get(f"/api/v1/escolas/{e}/sync/alertas?resolvido=false").json() == []


def test_api_dashboard_exige_global(cliente, escola_completa):
    # o admin da escola NÃO é global -> 403 no painel cross-escola
    assert cliente.get("/api/v1/sync/dashboard").status_code == 403


def test_api_status_onboarding(cliente, escola_completa, monkeypatch):
    from app.sync import connectors, service
    e = escola_completa["escola"].id
    monkeypatch.setitem(connectors._REGISTRO, "matific", ConectorFake())
    monkeypatch.setattr(service, "disparar_em_thread", lambda _id: None)
    st = cliente.get(f"/api/v1/escolas/{e}/sync/status").json()
    assert st["lista_piloto_importada"] is True    # escola_completa já tem turma
    assert st["integracao_configurada"] is False   # sem credencial ainda
    cliente.put(f"/api/v1/escolas/{e}/sync/credenciais/matific",
                json={"usuario": "u", "senha": "p"})
    st2 = cliente.get(f"/api/v1/escolas/{e}/sync/status").json()
    assert st2["integracao_configurada"] is True   # Etapa 4: marcada


def test_scheduler_desligado_por_padrao():
    from app.sync import scheduler
    assert scheduler.iniciar() is False   # SYNC_SCHEDULER_ENABLED=False nos testes
    assert scheduler.ativo() is False


def test_uma_rodada_orquestra_agenda_e_fila(monkeypatch):
    from app.sync import scheduler, service
    chamou = {"agendados": 0, "executou": [], "reaper": 0}
    monkeypatch.setattr(service, "recuperar_execucoes_travadas",
                        lambda db: chamou.__setitem__("reaper", 1))
    monkeypatch.setattr(service, "enfileirar_agendados", lambda db: chamou.__setitem__("agendados", 1))

    class _FakeEx:
        id = 42
    monkeypatch.setattr(service, "proximas_da_fila", lambda db, limite: [_FakeEx()])
    monkeypatch.setattr(service, "executar_por_id", lambda eid: chamou["executou"].append(eid))
    scheduler._uma_rodada()
    assert chamou["agendados"] == 1 and chamou["executou"] == [42]


def test_orquestrador_sem_linhas_retorna_sem_dados(db, escola_completa, monkeypatch):
    from app.services import importacao as svc
    from app.sync import orchestrator
    escola = escola_completa["escola"]
    vazia = svc.Analise(plataforma="matific", formato="resumo")
    monkeypatch.setattr(orchestrator, "_parsear", lambda a: (vazia, "xlsx"))
    arq = ArquivoObtido(conteudo=b"PK", nome_arquivo="m.xlsx", plataforma="matific")
    res = orchestrator.aplicar_arquivo(db, escola, arq, usuario_id=None,
                                       recalcular=False, contexto=_contexto(escola.id))
    assert res["sem_dados"] is True and res["qtd_alunos"] == 0


def test_orquestrador_sem_ator_levanta_erro(db, monkeypatch):
    from app.models import Escola
    from app.services import importacao as svc
    from app.sync import orchestrator
    escola = Escola(nome="SEM ADMIN", ano_letivo_ativo=2026)
    db.add(escola)
    db.flush()
    a = svc.Analise(plataforma="matific", formato="resumo")
    a.linhas = [svc.LinhaImportacao(numero=1, nome="Fulano", dados={})]
    monkeypatch.setattr(orchestrator, "_parsear", lambda x: (a, "xlsx"))
    monkeypatch.setattr(orchestrator.imp, "_guardar_temporario", lambda *a, **k: None)
    import pytest
    with pytest.raises(RuntimeError):
        orchestrator.aplicar_arquivo(db, escola, ArquivoObtido(
            conteudo=b"PK", nome_arquivo="m.xlsx", plataforma="matific"),
            usuario_id=None, recalcular=False, contexto=_contexto(escola.id))


# --- conectores: localizar/obter, login não-confirmado, SSO, download vazio ---
def test_matific_localizar_e_obter(_=None):
    from app.sync.connectors.matific import ConectorMatific
    cred = Credenciais(usuario="a", senha="b")
    rels = asyncio.run(ConectorMatific(_fabrica(NavegadorFake())).localizar_relatorios(cred, _contexto()))
    assert len(rels) == 1 and rels[0].plataforma == "matific"
    arq = asyncio.run(ConectorMatific(_fabrica(NavegadorFake(conteudo=b"PKm")))
                      .obter(cred, rels[0], _contexto()))
    assert arq.conteudo == b"PKm" and arq.plataforma == "matific"


def test_login_nao_confirmado_e_recuperavel():
    from app.sync.connectors.matific import ConectorMatific
    # sem sucesso e sem erro visível -> falha_auth recuperável
    r = asyncio.run(ConectorMatific(_fabrica(NavegadorFake(logado=False, erro_login=False)))
                    .testar_credenciais(Credenciais(usuario="a", senha="b"), _contexto()))
    assert not r.ok and r.codigo == "falha_auth"


def test_elefante_sso_google_bloqueia_com_mensagem():
    from app.sync.connectors.elefante import ConectorElefante
    r = asyncio.run(ConectorElefante(_fabrica(NavegadorFake()))
                    .testar_credenciais(Credenciais(usuario="a", senha="b", extra={"sso": "google"}), _contexto()))
    assert not r.ok and "Google" in r.mensagem


def test_download_vazio_vira_erro():
    from app.sync.connectors.matific import ConectorMatific, _URL_LEADERBOARD
    from app.sync.interfaces import RelatorioDisponivel
    rel = RelatorioDisponivel(plataforma="matific", tipo="leaderboard", identificador=_URL_LEADERBOARD)
    r = asyncio.run(ConectorMatific(_fabrica(NavegadorFake())).testar_credenciais(
        Credenciais(usuario="a", senha="b"), _contexto()))
    assert r.ok  # login ok
    import pytest
    with pytest.raises(ErroConector):
        asyncio.run(ConectorMatific(_fabrica(NavegadorFake(conteudo=b"")))
                    .obter(Credenciais(usuario="a", senha="b"), rel, _contexto()))


# --- API: testar/remover/detalhe/sincronizar ---
def test_api_testar_remover_e_detalhe(cliente, escola_completa, monkeypatch):
    from app.sync import connectors, service
    e = escola_completa["escola"].id
    monkeypatch.setitem(connectors._REGISTRO, "matific", ConectorFake())
    monkeypatch.setattr(service, "disparar_em_thread", lambda _id: None)
    # testar sem credencial -> 400
    assert cliente.post(f"/api/v1/escolas/{e}/sync/credenciais/matific/testar").status_code == 400
    # salva -> testar -> 200
    cliente.put(f"/api/v1/escolas/{e}/sync/credenciais/matific",
                json={"usuario": "u", "senha": "p"})
    assert cliente.post(f"/api/v1/escolas/{e}/sync/credenciais/matific/testar").json()["ok"] is True
    # sincronizar agora enfileira
    rp = cliente.post(f"/api/v1/escolas/{e}/sync/agora?plataforma=matific")
    assert rp.status_code == 200
    exec_id = rp.json()[0]["id"]
    # detalhe da própria execução: 200; de id inexistente: 404
    assert cliente.get(f"/api/v1/escolas/{e}/sync/execucoes/{exec_id}").status_code == 200
    assert cliente.get(f"/api/v1/escolas/{e}/sync/execucoes/999999").status_code == 404
    # remover credencial: 204
    assert cliente.delete(f"/api/v1/escolas/{e}/sync/credenciais/matific").status_code == 204


def test_scheduler_liga_e_desliga(monkeypatch):
    from app.core.config import settings
    from app.sync import scheduler
    monkeypatch.setattr(settings, "SYNC_SCHEDULER_ENABLED", True)
    monkeypatch.setattr(settings, "SYNC_POLL_S", 1)
    monkeypatch.setattr(scheduler, "_uma_rodada", lambda: None)  # não toca banco real
    try:
        assert scheduler.iniciar() is True
        assert scheduler.ativo() is True
    finally:
        scheduler.parar(timeout=2)
    assert scheduler.ativo() is False


def test_enfileirar_agendados_enfileira_vencidos(db, escola_completa):
    from datetime import datetime
    from app.models.sincronizacao import SincronizacaoConfig, SincronizacaoExecucao
    from app.sync import service
    e = escola_completa["escola"].id
    db.add(SincronizacaoConfig(escola_id=e, plataforma="matific", ativo=True,
                               cadencia="diaria", hora_local="03:00",
                               proxima_execucao=datetime(2020, 1, 1)))
    db.commit()
    assert service.enfileirar_agendados(db) == 1
    assert db.query(SincronizacaoExecucao).filter_by(escola_id=e, origem="scheduler").first()


def test_calcular_proxima_semanal(db):
    from datetime import datetime
    from app.models.sincronizacao import SincronizacaoConfig
    from app.sync import service
    cfg = SincronizacaoConfig(escola_id=1, plataforma="matific", ativo=True,
                              cadencia="semanal", hora_local="03:00", dia_semana=0)
    prox = service.calcular_proxima(cfg, datetime(2026, 7, 11, 10, 0, 0))  # sábado
    assert prox is not None and prox.weekday() == 0  # segunda-feira


def test_executar_lento_abre_alerta(db, escola_completa, monkeypatch):
    from app.core.config import settings
    from app.models.sincronizacao import SincronizacaoAlerta
    from app.sync import connectors, orchestrator, service, vault
    monkeypatch.setattr(settings, "SYNC_LENTO_S", 0)  # qualquer duração vira "lento"
    escola = escola_completa["escola"]
    vault.salvar_credencial(db, escola.id, "matific", Credenciais(usuario="u", senha="p"))
    arq = ArquivoObtido(conteudo=b"PK", nome_arquivo="m.xlsx", plataforma="matific")
    monkeypatch.setitem(connectors._REGISTRO, "matific", ConectorFake(arquivos=[arq]))
    monkeypatch.setattr(orchestrator, "_parsear", lambda a: _analise_ana())
    ex = service.enfileirar(db, escola.id, "matific", origem="manual")
    service.executar(db, ex)
    assert db.query(SincronizacaoAlerta).filter_by(escola_id=escola.id, tipo="lento").first()


def test_dashboard_global_ok(db, escola_completa):
    from fastapi.testclient import TestClient
    from app.core.security import hash_senha
    from app.main import app
    from app.models import Usuario
    db.add(Usuario(escola_id=escola_completa["escola"].id, nome="Global",
                   email="global@teste.local", senha_hash=hash_senha("s3nh4g"),
                   cargo="admin", is_global=True))
    db.commit()
    c = TestClient(app)
    login = c.post("/api/v1/auth/login",
                   data={"username": "global@teste.local", "password": "s3nh4g"})
    c.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    r = c.get("/api/v1/sync/dashboard")
    assert r.status_code == 200 and "escolas_total" in r.json()


# --------------------------------------------------------------------------
# Concorrência, retry-limite, credencial ilegível, isolamento e cascata
# --------------------------------------------------------------------------
def test_indice_unico_barra_duas_execucoes_ativas(db, escola_completa):
    """Garantia de banco: no máximo UMA execução ativa por (escola, plataforma).
    Dois INSERTs ativos concorrentes → IntegrityError (o segundo perde)."""
    from sqlalchemy.exc import IntegrityError
    from app.models.sincronizacao import SincronizacaoExecucao
    e = escola_completa["escola"].id
    db.add(SincronizacaoExecucao(escola_id=e, plataforma="matific",
                                 origem="manual", status="fila"))
    db.flush()
    db.add(SincronizacaoExecucao(escola_id=e, plataforma="matific",
                                 origem="scheduler", status="executando"))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_reexecutar_execucao_ja_finalizada_nao_reprocessa(db, escola_completa, monkeypatch):
    """Claim atômico: chamar executar() de novo na MESMA execução (já não está
    em 'fila') não reprocessa — rowcount 0 e nenhum log/arquivo novo."""
    from app.models.sincronizacao import SincronizacaoLog
    from app.sync import connectors, orchestrator, service, vault
    escola = escola_completa["escola"]
    vault.salvar_credencial(db, escola.id, "matific", Credenciais(usuario="u", senha="p"))
    arq = ArquivoObtido(conteudo=b"PK", nome_arquivo="m.xlsx", plataforma="matific")
    monkeypatch.setitem(connectors._REGISTRO, "matific", ConectorFake(arquivos=[arq]))
    monkeypatch.setattr(orchestrator, "_parsear", lambda a: _analise_ana())
    ex = service.enfileirar(db, escola.id, "matific", origem="manual")
    service.executar(db, ex)
    assert ex.status == "concluida"
    logs1 = db.query(SincronizacaoLog).filter_by(execucao_id=ex.id).count()
    service.executar(db, ex)              # 2ª vez: claim WHERE status='fila' falha
    logs2 = db.query(SincronizacaoLog).filter_by(execucao_id=ex.id).count()
    assert logs1 == logs2                 # não reprocessou


def test_retry_para_no_limite_de_tentativas(db, escola_completa, monkeypatch):
    """Na ÚLTIMA tentativa (SYNC_MAX_TENTATIVAS), um erro recuperável não
    re-enfileira — a execução simplesmente termina em 'erro'."""
    from app.core.config import settings
    from app.models.sincronizacao import SincronizacaoExecucao
    from app.sync import connectors, service, vault
    e = escola_completa["escola"].id
    vault.salvar_credencial(db, e, "matific", Credenciais(usuario="u", senha="p"))
    erro = ErroConector("timeout", codigo="timeout", recuperavel=True)
    monkeypatch.setitem(connectors._REGISTRO, "matific", ConectorFake(erro=erro))
    ex = service.enfileirar(db, e, "matific", origem="scheduler",
                            tentativa=settings.SYNC_MAX_TENTATIVAS)
    service.executar(db, ex)
    assert ex.status == "erro"
    assert db.query(SincronizacaoExecucao).filter_by(
        escola_id=e, tentativa=settings.SYNC_MAX_TENTATIVAS + 1).first() is None


def test_credencial_indecifravel_vira_none(db, escola_completa):
    """SECRET_KEY trocada / segredo corrompido: obter_credencial devolve None em
    vez de estourar — o segredo ilegível nunca vira um crash."""
    e = escola_completa["escola"].id
    linha = vault.salvar_credencial(db, e, "matific", Credenciais(usuario="u", senha="p"))
    linha.segredo_cifrado = "isto-nao-decifra"   # simula rotação de chave
    db.flush()
    assert vault.obter_credencial(db, e, "matific") is None


def test_executar_credencial_ilegivel_marca_invalida(db, escola_completa, monkeypatch):
    """Execução com credencial ilegível falha de forma limpa (senha_invalida,
    não recuperável) e marca a credencial como inválida — sem retry infinito."""
    from app.models.sincronizacao import SincronizacaoExecucao
    from app.sync import connectors, service, vault
    e = escola_completa["escola"].id
    linha = vault.salvar_credencial(db, e, "matific", Credenciais(usuario="u", senha="p"))
    linha.segredo_cifrado = "corrompido"
    db.flush()
    monkeypatch.setitem(connectors._REGISTRO, "matific", ConectorFake(arquivos=[]))
    ex = service.enfileirar(db, e, "matific", origem="scheduler")
    service.executar(db, ex)
    assert ex.status == "erro"
    assert vault.obter_linha(db, e, "matific").status == "invalida"
    assert db.query(SincronizacaoExecucao).filter_by(
        escola_id=e, tentativa=2).first() is None   # não recuperável


def test_erro_generico_nao_vaza_segredo(db, escola_completa, monkeypatch):
    """Uma exceção INESPERADA (não ErroConector) é logada só pelo tipo — nunca
    com a mensagem crua, que poderia carregar segredo/PII."""
    from app.models.sincronizacao import SincronizacaoLog
    from app.sync import connectors, service, vault
    e = escola_completa["escola"].id
    vault.salvar_credencial(db, e, "matific", Credenciais(usuario="u", senha="p"))
    boom = ValueError("stacktrace com senha=TOPSECRET e aluno João")
    monkeypatch.setitem(connectors._REGISTRO, "matific", ConectorFake(erro=boom))
    ex = service.enfileirar(db, e, "matific", origem="manual")
    service.executar(db, ex)
    assert ex.status == "erro"
    assert "TOPSECRET" not in (ex.erro_resumo or "")
    msgs = [x.mensagem for x in db.query(SincronizacaoLog).filter_by(execucao_id=ex.id)]
    assert all("TOPSECRET" not in m for m in msgs)


def test_enfileirar_agendados_multi_escola(db, escola_completa):
    """Duas escolas com agenda vencida → cada uma enfileira a SUA execução, sem
    interferência entre tenants."""
    from datetime import datetime
    from app.models import Escola
    from app.models.sincronizacao import SincronizacaoConfig, SincronizacaoExecucao
    from app.sync import service
    e1 = escola_completa["escola"].id
    outra = Escola(nome="OUTRA ESCOLA", ano_letivo_ativo=2026)
    db.add(outra)
    db.flush()
    for eid in (e1, outra.id):
        db.add(SincronizacaoConfig(escola_id=eid, plataforma="matific", ativo=True,
                                   cadencia="diaria", hora_local="03:00",
                                   proxima_execucao=datetime(2020, 1, 1)))
    db.commit()
    assert service.enfileirar_agendados(db) == 2
    assert db.query(SincronizacaoExecucao).filter_by(
        escola_id=e1, origem="scheduler").count() == 1
    assert db.query(SincronizacaoExecucao).filter_by(
        escola_id=outra.id, origem="scheduler").count() == 1


def test_agora_sem_plataforma_pula_quem_nao_tem_credencial(cliente, escola_completa, monkeypatch):
    """/agora sem plataforma cobre todas as automatizáveis, mas pula em silêncio
    as que não têm credencial (só Matific configurada → só Matific enfileira)."""
    from app.sync import connectors, service
    e = escola_completa["escola"].id
    monkeypatch.setitem(connectors._REGISTRO, "matific", ConectorFake())
    monkeypatch.setattr(service, "disparar_em_thread", lambda _id: None)
    cliente.put(f"/api/v1/escolas/{e}/sync/credenciais/matific",
                json={"usuario": "u", "senha": "p"})
    r = cliente.post(f"/api/v1/escolas/{e}/sync/agora")   # sem ?plataforma
    assert r.status_code == 200
    assert {x["plataforma"] for x in r.json()} == {"matific"}


def test_config_desativar_limpa_proxima_execucao(cliente, escola_completa):
    """Desligar a agenda zera proxima_execucao — o worker não a pega mais."""
    e = escola_completa["escola"].id
    r1 = cliente.put(f"/api/v1/escolas/{e}/sync/config/matific",
                     json={"ativo": True, "cadencia": "diaria", "hora_local": "03:00"})
    assert r1.json()["proxima_execucao"] is not None
    r2 = cliente.put(f"/api/v1/escolas/{e}/sync/config/matific",
                     json={"ativo": False, "cadencia": "manual", "hora_local": "03:00"})
    assert r2.json()["proxima_execucao"] is None


def test_ondelete_execucao_cascata_logs_e_solta_alerta(db, escola_completa):
    """ON DELETE da execução: logs somem (CASCADE) e o alerta preserva o
    histórico com execucao_id em NULL (SET NULL)."""
    from app.models.sincronizacao import (
        SincronizacaoAlerta, SincronizacaoExecucao, SincronizacaoLog)
    from app.sync import service
    e = escola_completa["escola"].id
    ex = service.enfileirar(db, e, "matific", origem="manual")
    service.registrar_log(db, ex, "download", "info", "linha de log")
    service.abrir_alerta(db, e, "matific", "timeout", "erro", execucao_id=ex.id)
    db.commit()
    alerta = db.query(SincronizacaoAlerta).filter_by(escola_id=e).one()
    assert db.query(SincronizacaoLog).filter_by(execucao_id=ex.id).count() == 1
    db.delete(db.get(SincronizacaoExecucao, ex.id))
    db.commit()
    assert db.query(SincronizacaoLog).filter_by(execucao_id=ex.id).count() == 0
    db.refresh(alerta)
    assert alerta.execucao_id is None


def test_reaper_recupera_execucao_travada_e_reenfileira(db, escola_completa, monkeypatch):
    """Retomada após crash: uma execução presa em 'executando' além de
    SYNC_TRAVADA_S (worker morto/redeploy) é finalizada como 'erro' e
    re-enfileirada — a escola não fica travada pela exclusão mútua."""
    from datetime import datetime, timedelta, timezone
    from app.core.config import settings
    from app.models.sincronizacao import SincronizacaoAlerta, SincronizacaoExecucao
    from app.sync import service
    monkeypatch.setattr(settings, "SYNC_TRAVADA_S", 1800)
    e = escola_completa["escola"].id
    velho = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=3600)
    ex = service.enfileirar(db, e, "matific", origem="scheduler")
    ex.status = "executando"
    ex.iniciada_em = velho
    db.commit()

    assert service.recuperar_execucoes_travadas(db) == 1
    db.refresh(ex)
    assert ex.status == "erro"
    # re-enfileirou uma nova execução na fila (retomada)
    nova = db.query(SincronizacaoExecucao).filter_by(
        escola_id=e, status="fila", tentativa=2).first()
    assert nova is not None
    assert db.query(SincronizacaoAlerta).filter_by(
        escola_id=e, tipo="interrompida").first() is not None


def test_reaper_ignora_execucao_recente(db, escola_completa):
    """Uma execução que começou agora (viva) NÃO é recuperada — só as órfãs."""
    from app.sync import service
    e = escola_completa["escola"].id
    ex = service.enfileirar(db, e, "matific", origem="manual")
    ex.status = "executando"
    ex.iniciada_em = service._agora()   # começou agora
    db.commit()
    assert service.recuperar_execucoes_travadas(db) == 0
    db.refresh(ex)
    assert ex.status == "executando"    # intacta


def test_enfileirar_perde_corrida_do_reaper_ainda_honra_o_pedido(db, escola_completa, monkeypatch):
    """TOCTOU: se o reaper concorrente reivindica a órfã entre o SELECT e o
    UPDATE de enfileirar (na ÚLTIMA tentativa, sem re-enfileiramento), enfileirar
    NÃO pode devolver a órfã morta — precisa re-checar e criar a execução pedida,
    senão o clique do admin some em silêncio."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import update
    from app.core.config import settings
    from app.models.sincronizacao import SincronizacaoExecucao
    from app.sync import service
    monkeypatch.setattr(settings, "SYNC_TRAVADA_S", 1800)
    e = escola_completa["escola"].id
    orfa = service.enfileirar(db, e, "matific", origem="scheduler",
                              tentativa=settings.SYNC_MAX_TENTATIVAS)
    orfa.status = "executando"
    orfa.iniciada_em = (datetime.now(timezone.utc).replace(tzinfo=None)
                        - timedelta(seconds=3600))
    db.commit()

    # Simula o reaper concorrente vencendo a corrida: marca a órfã como 'erro' e
    # devolve False (ESTE chamador perdeu o claim atômico).
    def reaper_venceu(_db, ex):
        _db.execute(update(SincronizacaoExecucao)
                    .where(SincronizacaoExecucao.id == ex.id).values(status="erro"))
        _db.flush()
        return False
    monkeypatch.setattr(service, "_finalizar_travada", reaper_venceu)

    nova = service.enfileirar(db, e, "matific", origem="manual")
    assert nova.id != orfa.id and nova.status == "fila"   # pedido honrado, não perdido


def test_enfileirar_auto_cura_execucao_travada(db, escola_completa, monkeypatch):
    """enfileirar() auto-cura: se a 'ativa' é uma órfã presa em 'executando',
    ela é liberada e uma nova entra na fila (o botão volta a funcionar sem
    esperar o scheduler)."""
    from datetime import datetime, timedelta, timezone
    from app.core.config import settings
    from app.sync import service
    monkeypatch.setattr(settings, "SYNC_TRAVADA_S", 1800)
    e = escola_completa["escola"].id
    travada = service.enfileirar(db, e, "matific", origem="manual")
    travada.status = "executando"
    travada.iniciada_em = (datetime.now(timezone.utc).replace(tzinfo=None)
                           - timedelta(seconds=3600))
    db.commit()

    nova = service.enfileirar(db, e, "matific", origem="manual")
    assert nova.id != travada.id and nova.status == "fila"
    db.refresh(travada)
    assert travada.status == "erro"


def test_ondelete_escola_purga_todas_as_tabelas_sync(db):
    """Apagar a escola remove TODAS as 5 tabelas do módulo (CASCADE por
    escola_id) — sem deixar credencial/histórico órfão de outro tenant."""
    from app.models import Escola
    from app.models.sincronizacao import (
        PlataformaCredencial, SincronizacaoAlerta, SincronizacaoConfig,
        SincronizacaoExecucao, SincronizacaoLog)
    from app.sync import service, vault
    escola = Escola(nome="PURGE", ano_letivo_ativo=2026)
    db.add(escola)
    db.flush()
    eid = escola.id
    vault.salvar_credencial(db, eid, "matific", Credenciais(usuario="u", senha="p"))
    db.add(SincronizacaoConfig(escola_id=eid, plataforma="matific"))
    ex = service.enfileirar(db, eid, "matific", origem="manual")
    service.registrar_log(db, ex, "download", "info", "x")
    service.abrir_alerta(db, eid, "matific", "timeout", "y")
    db.commit()
    db.delete(db.get(Escola, eid))
    db.commit()
    for Modelo in (PlataformaCredencial, SincronizacaoConfig, SincronizacaoExecucao,
                   SincronizacaoLog, SincronizacaoAlerta):
        assert db.query(Modelo).filter_by(escola_id=eid).count() == 0
