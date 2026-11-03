"""Fila × agendador desligado, frescor fora do agendador, ciclo de vida dos
alertas, trilha da importação e falha de banco no meio da execução.

Cenário de produção (20/10/2026): o agendador está DESLIGADO desde 17/09. Tudo
que dependia dele — rodar a nova tentativa, abrir o alerta de dado velho, fechar
alertas antigos — simplesmente não acontecia, e a tela mostrava "Sincronizando"
ou "Funcionando" no lugar da verdade.
"""
from datetime import timedelta

from sqlalchemy import func, select

from app.core.config import settings
from app.models.plataformas import Importacao
from app.models.sincronizacao import (SincronizacaoAlerta, SincronizacaoConfig,
                                       SincronizacaoExecucao, SincronizacaoLog)
from app.sync import connectors, orchestrator, service, vault
from app.sync.interfaces import (ArquivoObtido, Conector, Credenciais, ErroConector,
                                 Estrategia, ResultadoValidacao)
from app.sync.service import _agora


class _Conector(Conector):
    plataforma = "matific"
    versao = "teste"
    estrategia = Estrategia.NAVEGADOR

    def __init__(self, arquivos=None, erro=None):
        self._arqs, self._erro = arquivos or [], erro

    async def testar_credenciais(self, cred, ctx):
        return ResultadoValidacao(True, "ok", "ok")

    async def localizar_relatorios(self, cred, ctx):
        return []

    async def obter(self, cred, rel, ctx):
        raise NotImplementedError

    async def sincronizar(self, cred, ctx):
        if self._erro:
            raise self._erro
        return self._arqs


def _analise_ana():
    from app.services import importacao as svc
    a = svc.Analise(plataforma="matific", formato="resumo", turma_detectada="")
    a.linhas = [svc.LinhaImportacao(numero=1, nome="Ana Beatriz Souza",
                dados={"atividades": 10, "estrelas": 3, "pontuacao_media": 70.0})]
    return a, "xlsx"


def _preparar(db, escola_id, monkeypatch, **kw):
    vault.salvar_credencial(db, escola_id, "matific", Credenciais(usuario="u", senha="p"))
    db.commit()
    monkeypatch.setitem(connectors._REGISTRO, "matific", _Conector(**kw))
    monkeypatch.setattr(orchestrator, "_parsear", lambda a: _analise_ana())


def _arquivo():
    return ArquivoObtido(conteudo=b"PK", nome_arquivo="m.xlsx", plataforma="matific")


def _abertos(db, escola_id, tipo=None):
    q = select(SincronizacaoAlerta.tipo).where(SincronizacaoAlerta.escola_id == escola_id,
                                               SincronizacaoAlerta.resolvido.is_(False))
    if tipo:
        q = q.where(SincronizacaoAlerta.tipo == tipo)
    return sorted(db.execute(q).scalars().all())


def _status(cliente, escola_id, plataforma="matific"):
    r = cliente.get(f"/api/v1/escolas/{escola_id}/sync/status")
    assert r.status_code == 200, r.text
    corpo = r.json()
    return corpo, next(p for p in corpo["plataformas"] if p["plataforma"] == plataforma)


def _repeticao_pendente(db, escola_id, *, origem="manual"):
    """O que uma falha recuperável deixava para trás: a tentativa 2, na fila, com
    disponivel_em no futuro — que só o agendador roda."""
    ex = SincronizacaoExecucao(escola_id=escola_id, plataforma="matific", origem=origem,
                               status="fila", tentativa=2,
                               disponivel_em=_agora() + timedelta(minutes=5), parametros={})
    db.add(ex)
    db.commit()
    return ex


# --------------------------------------------------------------------------
# Achado 2 — repetição presa com o agendador desligado
# --------------------------------------------------------------------------
def test_agendador_desligado_nao_deixa_repeticao_que_nunca_vai_rodar(
        db, escola_completa, monkeypatch):
    e = escola_completa["escola"].id
    _preparar(db, e, monkeypatch,
              erro=ErroConector("timeout", codigo="timeout", recuperavel=True))
    assert settings.SYNC_SCHEDULER_ENABLED is False          # padrão (fail-safe)

    ex = service.enfileirar(db, e, "matific", origem="manual")
    service.executar(db, ex)

    assert ex.status == "erro"                               # a falha aparece
    assert db.query(SincronizacaoExecucao).filter_by(escola_id=e, status="fila").count() == 0
    msgs = [m for (m,) in db.query(SincronizacaoLog.mensagem).filter_by(execucao_id=ex.id)]
    assert any("agendador está desligado" in m for m in msgs)


def test_pedido_manual_assume_a_repeticao_pendente_com_as_datas_pedidas(
        db, escola_completa, cliente, monkeypatch):
    """Antes: "coletar o período" devolvia a tentativa 2 (sem datas) e coletava o
    ano inteiro, em silêncio. Agora o manual CANCELA a pendente (com registro) e
    entra no lugar, com os parâmetros pedidos."""
    e = escola_completa["escola"].id
    _preparar(db, e, monkeypatch, arquivos=[_arquivo()])
    disparadas: list[int] = []
    monkeypatch.setattr(service, "disparar_em_thread", disparadas.append)
    pendente = _repeticao_pendente(db, e)

    r = cliente.post(f"/api/v1/escolas/{e}/sync/agora?plataforma=matific"
                     "&inicio=2026-09-01&fim=2026-09-30")
    assert r.status_code == 200, r.text
    nova_id = r.json()[0]["id"]
    assert nova_id != pendente.id and disparadas == [nova_id]
    db.expire_all()
    nova = db.get(SincronizacaoExecucao, nova_id)
    assert nova.parametros == {"matific_start_date": "2026-09-01",
                               "matific_end_date": "2026-09-30"}
    assert nova.tentativa == 1 and nova.origem == "manual"
    velha = db.get(SincronizacaoExecucao, pendente.id)
    assert velha.status == "cancelada"
    log = db.query(SincronizacaoLog).filter_by(execucao_id=pendente.id).one()
    assert "pedido manual" in log.mensagem


def test_nova_tentativa_herda_o_periodo_pedido(db, escola_completa, monkeypatch):
    """Com o agendador ligado, a nova tentativa de uma coleta POR PERÍODO saía sem
    as datas (``parametros`` vazio) e coletava o ano inteiro."""
    monkeypatch.setattr(settings, "SYNC_SCHEDULER_ENABLED", True)
    e = escola_completa["escola"].id
    _preparar(db, e, monkeypatch,
              erro=ErroConector("timeout", codigo="timeout", recuperavel=True))
    periodo = {"matific_start_date": "2026-09-01", "matific_end_date": "2026-09-30"}
    ex = service.enfileirar(db, e, "matific", origem="manual", parametros=periodo)
    service.executar(db, ex)
    nova = db.query(SincronizacaoExecucao).filter_by(escola_id=e, status="fila").one()
    assert nova.tentativa == 2 and nova.parametros == periodo


def test_clique_repetido_do_mesmo_pedido_continua_deduplicado(db, escola_completa):
    e = escola_completa["escola"].id
    a = service.enfileirar(db, e, "matific", origem="manual")
    b = service.enfileirar(db, e, "matific", origem="manual")
    assert a.id == b.id and a.status == "fila"


def test_periodo_pedido_durante_execucao_em_andamento_responde_409(
        db, escola_completa, cliente, monkeypatch):
    e = escola_completa["escola"].id
    _preparar(db, e, monkeypatch, arquivos=[_arquivo()])
    monkeypatch.setattr(service, "disparar_em_thread", lambda _id: None)
    ex = service.enfileirar(db, e, "matific", origem="manual")
    ex.status, ex.iniciada_em = "executando", _agora()
    db.commit()
    r = cliente.post(f"/api/v1/escolas/{e}/sync/agora?plataforma=matific"
                     "&inicio=2026-09-01&fim=2026-09-30")
    assert r.status_code == 409
    assert "em andamento" in r.json()["detail"]


def test_status_libera_a_repeticao_orfa_e_nao_diz_sincronizando(
        db, escola_completa, cliente, monkeypatch):
    e = escola_completa["escola"].id
    _preparar(db, e, monkeypatch, arquivos=[_arquivo()])
    pendente = _repeticao_pendente(db, e, origem="scheduler")

    _, matific = _status(cliente, e)
    assert matific["ultima_execucao"]["id"] == pendente.id
    assert matific["ultima_execucao"]["status"] == "cancelada"
    assert matific["fila_parada"] is False
    db.expire_all()
    assert db.get(SincronizacaoExecucao, pendente.id).status == "cancelada"


def test_boot_libera_repeticao_orfa_sem_tocar_pedido_manual_recente(db, escola_completa):
    e = escola_completa["escola"].id
    pendente = _repeticao_pendente(db, e)
    recente = service.enfileirar(db, e, "elefante", origem="manual")   # thread viva
    db.commit()
    assert service.finalizar_orfas_no_boot(db) == 1
    db.expire_all()
    assert db.get(SincronizacaoExecucao, pendente.id).status == "cancelada"
    assert db.get(SincronizacaoExecucao, recente.id).status == "fila"


def test_com_agendador_ligado_a_repeticao_fica_para_ele(db, escola_completa, monkeypatch):
    monkeypatch.setattr(settings, "SYNC_SCHEDULER_ENABLED", True)
    e = escola_completa["escola"].id
    pendente = _repeticao_pendente(db, e)
    assert service.liberar_fila_sem_agendador(db) == 0
    db.refresh(pendente)
    assert pendente.status == "fila"


# --------------------------------------------------------------------------
# Achado 3 — alerta "dados desatualizados" fora do agendador
# --------------------------------------------------------------------------
def _agenda_antiga(db, escola_id, dias=5):
    marco = _agora() - timedelta(days=dias)
    db.add(SincronizacaoConfig(escola_id=escola_id, plataforma="matific", ativo=True,
                               cadencia="diaria", hora_local="03:00",
                               created_at=marco, updated_at=marco))
    db.commit()


def test_status_abre_o_alerta_de_dados_desatualizados_sem_agendador(
        db, escola_completa, cliente, monkeypatch):
    e = escola_completa["escola"].id
    _preparar(db, e, monkeypatch, arquivos=[_arquivo()])
    _agenda_antiga(db, e)
    db.add(SincronizacaoExecucao(escola_id=e, plataforma="matific", origem="manual",
                                 status="concluida",
                                 finalizada_em=_agora() - timedelta(days=4)))
    db.commit()

    corpo, matific = _status(cliente, e)
    assert matific["desatualizada"] is True
    assert matific["frescor"] == "desatualizado" and matific["idade_horas"] >= 96
    assert corpo["agendador_ativo"] is False
    db.expire_all()
    assert _abertos(db, e, "desatualizada") == ["desatualizada"]
    alerta = db.query(SincronizacaoAlerta).filter_by(escola_id=e, tipo="desatualizada").one()
    assert "pausada neste servidor" in alerta.mensagem     # a causa real, não "a agenda"

    # Ler de novo NÃO duplica; uma coleta manual bem-sucedida FECHA o alerta.
    _status(cliente, e)
    db.expire_all()
    assert len(_abertos(db, e, "desatualizada")) == 1
    ex = service.enfileirar(db, e, "matific", origem="manual")
    service.executar(db, ex)
    assert ex.status == "concluida"
    assert _abertos(db, e, "desatualizada") == []
    _, matific = _status(cliente, e)
    assert matific["frescor"] == "atualizado" and matific["desatualizada"] is False


def test_dashboard_conta_desatualizadas_pela_regra_e_nao_pelos_alertas(db, escola_completa):
    e = escola_completa["escola"].id
    _agenda_antiga(db, e)                     # nenhum alerta aberto ainda
    assert e in service.escolas_desatualizadas(db)
    assert _abertos(db, e) == []


def test_frescor_sem_agenda_tambem_envelhece(db, escola_completa):
    """Cadência manual não tem alerta automático, mas o dado de 10 dias não é
    "atualizado": o estado de frescor vale com ou sem agenda."""
    manual = SincronizacaoConfig(escola_id=1, plataforma="matific", ativo=False,
                                 cadencia="manual")
    assert service.frescor(manual, _agora() - timedelta(days=10))["frescor"] == "desatualizado"
    assert service.frescor(manual, _agora() - timedelta(hours=5))["frescor"] == "atualizado"
    assert service.frescor(None, None)["frescor"] == "sem_sucesso"


# --------------------------------------------------------------------------
# Ciclo de vida: o sucesso fecha TODA falha da integração
# --------------------------------------------------------------------------
def test_sucesso_fecha_alertas_antigos_de_qualquer_tipo(db, escola_completa, monkeypatch):
    """Em produção ficaram abertos desde jul/ago: falha_autenticacao (o tipo que a
    execução grava, mas o sucesso fechava 'falha_auth'), erro_navegador (código
    cru do salvar credencial), interrompida e parser_incompativel."""
    e = escola_completa["escola"].id
    _preparar(db, e, monkeypatch, arquivos=[_arquivo()])
    for tipo in ("falha_autenticacao", "erro_navegador", "interrompida",
                 "parser_incompativel", "captcha"):
        service.abrir_alerta(db, e, "matific", tipo, "antigo")
    service.abrir_alerta(db, e, "elefante", "timeout", "de outra plataforma")
    db.commit()

    ex = service.enfileirar(db, e, "matific", origem="manual")
    service.executar(db, ex)

    assert ex.status == "concluida"
    assert _abertos(db, e) == ["timeout"]                  # só o da outra plataforma


def test_lento_fecha_quando_a_execucao_volta_ao_normal(db, escola_completa, monkeypatch):
    e = escola_completa["escola"].id
    _preparar(db, e, monkeypatch, arquivos=[_arquivo()])
    service.abrir_alerta(db, e, "matific", "lento", "levou 150s")
    db.commit()
    ex = service.enfileirar(db, e, "matific", origem="manual")
    service.executar(db, ex)                               # rápida (fake)
    assert _abertos(db, e, "lento") == []


def test_lento_nao_fecha_com_um_sucesso_qualquer(db, escola_completa):
    """O que o COLETA-PLATAFORMAS §3 promete: 'lento' fecha só quando uma
    execução CONCLUI dentro do limite. Com menos de 5 concluídas no histórico o
    limite é o piso (120 s) — uma coleta completa do Elefante de minutos mantém
    o aviso aberto (o documento dizia que fechava na 1ª execução bem-sucedida)."""
    e = escola_completa["escola"].id
    service.abrir_alerta(db, e, "elefante", "lento", "levou 400s")
    demorada = SincronizacaoExecucao(escola_id=e, plataforma="elefante", origem="manual",
                                     status="concluida",
                                     duracao_ms=(settings.SYNC_LENTO_S + 80) * 1000)
    db.add(demorada)
    db.flush()
    service._avaliar_lentidao(db, demorada)
    assert _abertos(db, e, "lento") == ["lento"]
    rapida = SincronizacaoExecucao(escola_id=e, plataforma="elefante", origem="manual",
                                   status="concluida", duracao_ms=30_000)
    db.add(rapida)
    db.flush()
    service._avaliar_lentidao(db, rapida)
    assert _abertos(db, e, "lento") == []


def test_lento_e_relativo_ao_normal_da_integracao(db, escola_completa):
    """Com histórico, o limite é 2× a mediana (o Elefante leva minutos e era
    SEMPRE "lento" com o teto fixo de 120 s, então o alerta nunca fechava)."""
    e = escola_completa["escola"].id
    for _ in range(service.LENTO_MIN_HISTORICO):
        db.add(SincronizacaoExecucao(escola_id=e, plataforma="elefante", origem="scheduler",
                                     status="concluida", duracao_ms=500_000))
    db.commit()
    limite, mediana = service.limite_lento_ms(db, e, "elefante")
    assert mediana == 500_000 and limite == 1_000_000


def test_credencial_com_erro_de_navegador_nao_vira_senha_recusada(
        cliente, escola_completa, db, monkeypatch):
    e = escola_completa["escola"].id

    class _Quebra(_Conector):
        async def testar_credenciais(self, cred, ctx):
            return ResultadoValidacao(False, "A página não respondeu.", "erro_navegador")

    monkeypatch.setitem(connectors._REGISTRO, "matific", _Quebra())
    r = cliente.put(f"/api/v1/escolas/{e}/sync/credenciais/matific",
                    json={"usuario": "u", "senha": "p"})
    assert r.status_code == 200 and r.json()["ok"] is False
    db.expire_all()
    assert vault.obter_linha(db, e, "matific").status == "nao_validada"
    alerta = db.query(SincronizacaoAlerta).filter_by(escola_id=e, tipo="erro_navegador").one()
    assert alerta.severidade == "warn"                     # não é "senha errada"

    monkeypatch.setitem(connectors._REGISTRO, "matific", _Conector())
    r = cliente.post(f"/api/v1/escolas/{e}/sync/credenciais/matific/testar")
    assert r.json()["ok"] is True
    db.expire_all()
    assert _abertos(db, e) == []                           # login ok fecha o de acesso


def test_remover_credencial_fecha_as_falhas_da_integracao(cliente, escola_completa, db):
    e = escola_completa["escola"].id
    vault.salvar_credencial(db, e, "matific", Credenciais(usuario="u", senha="p"))
    for tipo in ("senha_invalida", "timeout", "lento"):
        service.abrir_alerta(db, e, "matific", tipo, "antigo")
    service.abrir_alerta(db, e, "matific", "desatualizada", "dado velho")
    db.commit()
    assert cliente.delete(f"/api/v1/escolas/{e}/sync/credenciais/matific").status_code == 204
    db.expire_all()
    assert _abertos(db, e) == ["desatualizada"]     # o dado continua velho de verdade


# --------------------------------------------------------------------------
# Achado 6 (API) — última tentativa × último sucesso, tipo da falha, sem dados
# --------------------------------------------------------------------------
def test_status_separa_ultima_tentativa_de_ultimo_sucesso(db, escola_completa, cliente,
                                                          monkeypatch):
    e = escola_completa["escola"].id
    _preparar(db, e, monkeypatch, arquivos=[_arquivo()])
    ok = service.enfileirar(db, e, "matific", origem="manual")
    service.executar(db, ok)
    monkeypatch.setitem(connectors._REGISTRO, "matific", _Conector(
        erro=ErroConector("Placar fora do ar", codigo="falha_download", recuperavel=True)))
    falha = service.enfileirar(db, e, "matific", origem="manual")
    service.executar(db, falha)

    _, matific = _status(cliente, e)
    assert matific["ultima_tentativa"]["id"] == falha.id
    assert matific["ultima_tentativa"]["status"] == "erro"
    assert matific["ultimo_sucesso_em"] is not None          # o de antes continua
    assert matific["frescor"] == "atualizado"                # o DADO está em dia…
    assert matific["falha_categoria"] == "indisponibilidade_externa"   # …mas a coleta falhou


def test_categoria_da_falha_por_tipo(db, escola_completa, cliente, monkeypatch):
    e = escola_completa["escola"].id
    casos = [("senha_invalida", False, "autenticacao"),
             ("captcha", True, "indisponibilidade_externa"),
             ("navegador_indisponivel", False, "indisponivel"),
             # Período pedido inválido: o pedido é que não é aceito — não é "erro
             # do nosso lado" (antes saía 'processamento').
             ("periodo_invalido", False, "configuracao")]
    for codigo, recuperavel, esperado in casos:
        _preparar(db, e, monkeypatch, erro=ErroConector("x", codigo=codigo,
                                                         recuperavel=recuperavel))
        ex = service.enfileirar(db, e, "matific", origem="manual")
        service.executar(db, ex)
        _, matific = _status(cliente, e)
        assert matific["falha_categoria"] == esperado, codigo
    # Falha inesperada (nossa): processamento.
    _preparar(db, e, monkeypatch, arquivos=[_arquivo()])
    monkeypatch.setattr(orchestrator, "aplicar_arquivo",
                        lambda *a, **k: (_ for _ in ()).throw(KeyError("x")))
    ex = service.enfileirar(db, e, "matific", origem="manual")
    service.executar(db, ex)
    _, matific = _status(cliente, e)
    assert matific["falha_categoria"] == "processamento"


def test_relatorio_sem_linhas_e_sem_dados_e_nao_sucesso(db, escola_completa, monkeypatch):
    """Arquivo chegou, mas vazio: 'sem_dados' — não renova o "último sucesso" e não
    fecha a falha de download anterior."""
    from app.services import importacao as svc
    e = escola_completa["escola"].id
    _preparar(db, e, monkeypatch, arquivos=[_arquivo()])
    monkeypatch.setattr(orchestrator, "_parsear", lambda a: (
        svc.Analise(plataforma="matific", formato="resumo"), "xlsx"))
    service.abrir_alerta(db, e, "matific", "falha_download", "antes")
    db.commit()
    ex = service.enfileirar(db, e, "matific", origem="manual")
    service.executar(db, ex)
    assert ex.status == "sem_dados"
    assert service.ultimo_sucesso_em(db, e, "matific") is None
    assert _abertos(db, e) == ["falha_download"]


# --------------------------------------------------------------------------
# Achado 5 — a execução aponta para a importação que gerou
# --------------------------------------------------------------------------
def test_execucao_grava_a_importacao_gerada(db, escola_completa, monkeypatch):
    e = escola_completa["escola"].id
    _preparar(db, e, monkeypatch, arquivos=[_arquivo(), _arquivo()])
    ex = service.enfileirar(db, e, "matific", origem="manual")
    service.executar(db, ex)
    assert ex.status == "concluida"
    imps = db.execute(select(Importacao.id).where(Importacao.escola_id == e)
                      .order_by(Importacao.id)).scalars().all()
    assert len(imps) == 2
    assert ex.importacao_id == imps[-1]
    msgs = [m for (m,) in db.query(SincronizacaoLog.mensagem).filter_by(execucao_id=ex.id)]
    assert any("2 importações geradas" in m for m in msgs)


def test_execucao_sem_dados_nao_aponta_importacao(db, escola_completa, monkeypatch):
    from app.services import importacao as svc
    e = escola_completa["escola"].id
    _preparar(db, e, monkeypatch, arquivos=[_arquivo()])
    monkeypatch.setattr(orchestrator, "_parsear", lambda a: (
        svc.Analise(plataforma="matific", formato="resumo"), "xlsx"))
    ex = service.enfileirar(db, e, "matific", origem="manual")
    service.executar(db, ex)
    assert ex.importacao_id is None


# --------------------------------------------------------------------------
# Achado 10 — falha de BANCO no meio da execução não a deixa presa
# --------------------------------------------------------------------------
def test_falha_de_banco_no_meio_termina_em_erro_e_nao_fica_executando(
        db, escola_completa, monkeypatch):
    """Antes: a sessão quebrada pelo IntegrityError fazia o próprio registro da
    falha estourar — a execução ficava 'executando', sem log, até o reaper de 30
    min (que só roda com o agendador ligado: em produção, para sempre)."""
    e = escola_completa["escola"].id
    _preparar(db, e, monkeypatch, arquivos=[_arquivo()])

    def quebra_o_banco(db_, escola, arquivo, **_kw):
        # Duas agendas para a mesma (escola, plataforma): viola a UNIQUE no flush.
        db_.add(SincronizacaoConfig(escola_id=escola.id, plataforma="elefante"))
        db_.add(SincronizacaoConfig(escola_id=escola.id, plataforma="elefante"))
        db_.flush()

    monkeypatch.setattr(orchestrator, "aplicar_arquivo", quebra_o_banco)
    ex = service.enfileirar(db, e, "matific", origem="manual")
    service.executar(db, ex)

    db.expire_all()
    final = db.get(SincronizacaoExecucao, ex.id)
    assert final.status == "erro" and final.finalizada_em is not None
    assert final.erro_resumo == "Falha inesperada: IntegrityError"
    assert db.scalar(select(func.count(SincronizacaoExecucao.id)).where(
        SincronizacaoExecucao.status == "executando")) == 0
