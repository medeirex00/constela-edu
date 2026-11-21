"""Pré-requisitos para religar o agendador de sincronização (P3) — sem ligá-lo.

Prova, com dados fictícios e sem rede:

* o agendador continua DESLIGADO por padrão, e ``SYNC_SCHEDULER_FORCAR`` sozinho
  não o liga;
* ligado pela variável, RECUSA iniciar quando um pré-requisito crítico falha (log
  claro, sem levantar), inclusive quando a própria verificação estoura;
* inicia quando todos os críticos estão ok (loop trocado por um falso, sem rodada
  real) — e o forçar passa por cima da recusa;
* cada verificação, nos dois sentidos: teto, coerência teto × limpeza de órfãs,
  status honesto, selo de frescor, execuções presas, credenciais legíveis,
  recálculo pendente, fuso de Brasília, janela do backup, workers/semáforo;
* o horário da agenda é de BRASÍLIA (03:00 = 06:00 UTC) — os pares 08:00/11:00
  só dão o resultado esperado se a conversão for em America/Sao_Paulo;
* tudo só de leitura, e o painel global (só admin global) mostra o bloco sem
  segredo.

Os ganchos que dependem das outras frentes (teto, estados e colunas da 0039) são
substituídos nos testes que exercitam o caminho "pronto"; os demais testes valem
igual antes e depois da integração.
"""
from __future__ import annotations

import json
import logging
import time as _time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, settings
from app.models import Escola
from app.models.sincronizacao import (
    PlataformaCredencial,
    SincronizacaoAlerta,
    SincronizacaoConfig,
    SincronizacaoExecucao,
    SincronizacaoLog,
)
from app.sync import fuso, prerequisitos, scheduler, service, vault
from app.sync.interfaces import Credenciais
from tests._infra_comum import (  # noqa: F401 — fixtures
    BOOT,
    ambiente,
    levar_a,
    pg_url,
    rodar,
    sqlite_url,
)

# 22/10/2026 15:00 UTC = 12:00 em Brasília (fora da janela do backup).
AGORA = datetime(2026, 10, 22, 15, 0)
SENHA_FICTICIA = "senha-ficticia-nao-real-123"
USUARIO_FICTICIO = "usuario.ficticio@exemplo.test"


class Cfg:
    """``settings`` com sobreposições — o objeto real não aceita campo que a
    versão ainda não declara (ex.: ``SYNC_TETO_EXECUCAO_S``, da frente A)."""

    def __init__(self, **sobre):
        self.__dict__["_sobre"] = sobre

    def __getattr__(self, nome):
        sobre = self.__dict__["_sobre"]
        if nome in sobre:
            return sobre[nome]
        return getattr(settings, nome)


def cfg_pronta(**extra) -> Cfg:
    base = {"SYNC_TETO_EXECUCAO_S": 2700, "SYNC_TRAVADA_S": 3600}
    base.update(extra)
    return Cfg(**base)


def verificar(db, cfg, vid: str):
    resultado = {v.id: v for v in prerequisitos.prerequisitos_agendador(db, cfg, agora=AGORA)}
    return resultado[vid]


def agenda(db, escola_id: int, plataforma: str = "elefante", hora: str = "03:00", *,
           cadencia: str = "diaria", ativo: bool = True, proxima="calcular"):
    cfg = SincronizacaoConfig(escola_id=escola_id, plataforma=plataforma, ativo=ativo,
                              cadencia=cadencia, hora_local=hora)
    db.add(cfg)
    db.flush()
    cfg.proxima_execucao = (service.calcular_proxima(cfg, AGORA) if proxima == "calcular"
                            else proxima)
    db.commit()
    return cfg


def credencial(db, escola_id: int, plataforma: str = "elefante", *, legivel: bool = True):
    linha = vault.salvar_credencial(
        db, escola_id, plataforma,
        Credenciais(usuario=USUARIO_FICTICIO, senha=SENHA_FICTICIA))
    if not legivel:
        linha.segredo_cifrado = "isto-nao-e-um-token-fernet"   # chave trocada/corrompido
    db.commit()
    return linha


def escolas_extras(db, n: int) -> list[int]:
    ids = []
    for i in range(n):
        e = Escola(nome=f"ESCOLA FICTICIA {i}", ano_letivo_ativo=2026)
        db.add(e)
        db.flush()
        ids.append(e.id)
    db.commit()
    return ids


def preparar_versao_pronta(monkeypatch):
    """Simula os ganchos das outras frentes (status honesto + 0039)."""
    monkeypatch.setattr(service, "ESTADOS_FINAIS", prerequisitos.ESTADOS_CONTRATO,
                        raising=False)
    monkeypatch.setattr(prerequisitos, "_colunas_no_modelo",
                        lambda: set(prerequisitos.COLUNAS_CONTRATO) | {"id", "status"})
    monkeypatch.setattr(prerequisitos, "_colunas_no_banco",
                        lambda db: set(prerequisitos.COLUNAS_CONTRATO) | {"id", "status"})
    monkeypatch.setattr(prerequisitos, "_recalculos_pendentes", lambda db: [])


@pytest.fixture
def agendador_limpo(monkeypatch):
    """Estado do agendador isolado: nenhuma thread sobra e o sinal de parar volta
    ao normal (``_uma_rodada`` de outro teste para de processar com ele ligado)."""
    monkeypatch.setattr(scheduler, "_decisao", None)
    monkeypatch.setattr(scheduler, "_thread", None)
    yield
    scheduler.parar(timeout=2)
    assert not scheduler.ativo()
    scheduler._parar.clear()


def loop_falso(monkeypatch) -> list:
    """Troca o laço do agendador por um que só espera o sinal de parar: prova que a
    thread subiu sem rodar nenhuma rodada (sem banco, sem fila, sem rede)."""
    voltas: list = []

    def _loop():
        voltas.append("subiu")
        scheduler._parar.wait(5)

    monkeypatch.setattr(scheduler, "_loop", _loop)
    return voltas


def sessao_do_teste(monkeypatch, db):
    monkeypatch.setattr(scheduler, "_abrir_sessao", lambda: Session(bind=db.get_bind()))


def esperar(condicao, prazo_s: float = 2.0) -> bool:
    fim = _time.monotonic() + prazo_s
    while _time.monotonic() < fim:
        if condicao():
            return True
        _time.sleep(0.01)
    return condicao()


# --------------------------------------------------------------------------
# O portão do agendador
# --------------------------------------------------------------------------
def test_desligado_por_padrao_e_forcar_sozinho_nao_liga(monkeypatch, agendador_limpo):
    assert Settings.model_fields["SYNC_SCHEDULER_ENABLED"].default is False
    assert Settings.model_fields["SYNC_SCHEDULER_FORCAR"].default == "false"
    assert settings.SYNC_SCHEDULER_ENABLED is False
    verificou = []
    monkeypatch.setattr(scheduler, "_avaliar_prerequisitos",
                        lambda: verificou.append(1) or [])
    monkeypatch.setattr(settings, "SYNC_SCHEDULER_FORCAR", "true")
    voltas = loop_falso(monkeypatch)
    assert scheduler.iniciar() is False
    assert scheduler.ativo() is False and voltas == []
    assert verificou == []                    # desligado nem chega a verificar
    assert scheduler.decisao() == "desligado"


@pytest.mark.parametrize("valor, forca", [
    ("true", True), (" TRUE ", True), ("1", True), ("sim", True), ("on", True),
    ("false", False), ("", False), (None, False), ("talvez", False), ("0", False),
])
def test_forcar_e_texto_e_so_os_valores_de_ligado_forcam(valor, forca):
    assert prerequisitos.forcar_habilitado(Cfg(SYNC_SCHEDULER_FORCAR=valor)) is forca


def test_recusa_iniciar_com_prerequisito_critico_falho(db, monkeypatch, caplog,
                                                      agendador_limpo):
    monkeypatch.setattr(settings, "SYNC_SCHEDULER_ENABLED", True)
    monkeypatch.setattr(settings, "SYNC_SCHEDULER_FORCAR", "false")
    # Falha CRÍTICA real e independente da versão: nenhum worker.
    monkeypatch.setattr(settings, "SYNC_WORKERS", 0)
    sessao_do_teste(monkeypatch, db)
    voltas = loop_falso(monkeypatch)
    with caplog.at_level(logging.INFO, logger="constela.sync"):
        assert scheduler.iniciar() is False
    assert scheduler.ativo() is False and voltas == []
    assert scheduler.decisao() == "recusado"
    erros = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(erros) == 1, erros
    assert "NÃO iniciado" in erros[0]
    assert "workers_semaforo" in erros[0]
    assert "REATIVAR-AGENDADOR" in erros[0]


def test_verificacao_que_estoura_recusa_sem_levantar(monkeypatch, caplog, agendador_limpo):
    monkeypatch.setattr(settings, "SYNC_SCHEDULER_ENABLED", True)
    monkeypatch.setattr(settings, "SYNC_SCHEDULER_FORCAR", "false")

    def _sem_banco():
        raise RuntimeError("banco fora do ar (ensaio)")

    monkeypatch.setattr(scheduler, "_abrir_sessao", _sem_banco)
    voltas = loop_falso(monkeypatch)
    with caplog.at_level(logging.INFO, logger="constela.sync"):
        assert scheduler.iniciar() is False       # não levanta: o app segue de pé
    assert scheduler.ativo() is False and voltas == []
    assert scheduler.decisao() == "recusado"
    texto = " ".join(r.getMessage() for r in caplog.records)
    assert "verificação indisponível (RuntimeError)" in texto


def test_forcar_inicia_apesar_do_prerequisito_falho(db, monkeypatch, caplog,
                                                   agendador_limpo):
    monkeypatch.setattr(settings, "SYNC_SCHEDULER_ENABLED", True)
    monkeypatch.setattr(settings, "SYNC_SCHEDULER_FORCAR", "true")
    monkeypatch.setattr(settings, "SYNC_WORKERS", 0)
    sessao_do_teste(monkeypatch, db)
    voltas = loop_falso(monkeypatch)
    with caplog.at_level(logging.INFO, logger="constela.sync"):
        assert scheduler.iniciar() is True
    assert esperar(lambda: voltas == ["subiu"])
    assert scheduler.decisao() == "forcado"
    avisos = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("À FORÇA" in m and "workers_semaforo" in m for m in avisos), avisos


def test_inicia_quando_todos_os_criticos_estao_ok(monkeypatch, agendador_limpo):
    """Só os CRÍTICOS decidem: um aviso falho não impede o início."""
    monkeypatch.setattr(settings, "SYNC_SCHEDULER_ENABLED", True)
    monkeypatch.setattr(settings, "SYNC_SCHEDULER_FORCAR", "false")
    monkeypatch.setattr(scheduler, "_avaliar_prerequisitos", lambda: [
        prerequisitos.Verificacao("teto_execucao", True, True, "ok"),
        prerequisitos.Verificacao("fila_da_agenda", False, False, "só aviso"),
    ])
    voltas = loop_falso(monkeypatch)
    assert scheduler.iniciar() is True
    assert esperar(lambda: voltas == ["subiu"])
    assert scheduler.ativo() is True and scheduler.decisao() == "iniciado"
    assert scheduler.iniciar() is False           # já rodando: não sobe outra thread
    scheduler.parar(timeout=2)
    assert scheduler.ativo() is False


def test_inicia_com_as_verificacoes_reais_num_banco_pronto(db, escola_completa,
                                                          monkeypatch, agendador_limpo):
    """Ponta a ponta do portão com as verificações REAIS: agenda às 03:00 de
    Brasília com credencial legível, teto coerente. Só os ganchos das outras frentes
    (estados e colunas da 0039) são simulados."""
    e = escola_completa["escola"].id
    agenda(db, e, "elefante", "03:00")
    credencial(db, e, "elefante")
    preparar_versao_pronta(monkeypatch)
    monkeypatch.setattr(scheduler, "settings", cfg_pronta(
        SYNC_SCHEDULER_ENABLED=True, SYNC_SCHEDULER_FORCAR="false"))
    sessao_do_teste(monkeypatch, db)
    voltas = loop_falso(monkeypatch)
    assert scheduler.iniciar() is True, prerequisitos.criticos_falhos(
        prerequisitos.prerequisitos_agendador(db, scheduler.settings))
    assert esperar(lambda: voltas == ["subiu"])
    assert scheduler.decisao() == "iniciado"


def test_credencial_ilegivel_recusa_o_inicio_no_banco_pronto(db, escola_completa,
                                                            monkeypatch, agendador_limpo):
    e = escola_completa["escola"].id
    agenda(db, e, "elefante", "03:00")
    credencial(db, e, "elefante", legivel=False)
    preparar_versao_pronta(monkeypatch)
    monkeypatch.setattr(scheduler, "settings", cfg_pronta(
        SYNC_SCHEDULER_ENABLED=True, SYNC_SCHEDULER_FORCAR="false"))
    sessao_do_teste(monkeypatch, db)
    voltas = loop_falso(monkeypatch)
    assert scheduler.iniciar() is False
    assert voltas == [] and scheduler.decisao() == "recusado"


def test_banco_pronto_passa_em_todas_as_verificacoes(db, escola_completa, monkeypatch):
    e = escola_completa["escola"].id
    agenda(db, e, "elefante", "03:00")
    agenda(db, e, "matific", "03:30")
    credencial(db, e, "elefante")
    credencial(db, e, "matific")
    preparar_versao_pronta(monkeypatch)
    verificacoes = prerequisitos.prerequisitos_agendador(db, cfg_pronta(), agora=AGORA)
    assert [v.id for v in verificacoes] == [v for v, _, _ in prerequisitos._VERIFICACOES]
    falhas = [v for v in verificacoes if not v.ok]
    assert falhas == [], falhas
    assert prerequisitos.pode_iniciar(verificacoes)


# --------------------------------------------------------------------------
# Verificações, uma a uma
# --------------------------------------------------------------------------
@pytest.mark.parametrize("teto, ok, trecho", [
    (None, False, "não existe nesta versão"),
    (0, False, "maior que zero"),
    (-5, False, "maior que zero"),
    ("abc", False, "maior que zero"),
    (2700, True, "2700 s (45 min)"),
])
def test_teto_de_execucao(db, teto, ok, trecho):
    v = verificar(db, Cfg(SYNC_TETO_EXECUCAO_S=teto), "teto_execucao")
    assert v.critico and v.ok is ok and trecho in v.motivo


def test_teto_ausente_no_settings_desta_versao_falha(db):
    """Sem o campo no objeto de configuração (versão sem a frente A): falha."""
    v = verificar(db, settings, "teto_execucao")
    if getattr(settings, "SYNC_TETO_EXECUCAO_S", None) is None:
        assert v.ok is False and "não existe nesta versão" in v.motivo
    else:                                  # versão integrada: o campo existe
        assert v.ok is (int(settings.SYNC_TETO_EXECUCAO_S) > 0)


@pytest.mark.parametrize("teto, travada, timeout, ok, trecho", [
    (2700, 1800, 180, False, "SYNC_TRAVADA_S (1800 s) não passa do teto (2700 s)"),
    (2700, 2700, 180, False, "não passa do teto"),
    (2700, 3600, 180, True, "SYNC_TRAVADA_S (3600 s) > teto (2700 s)"),
    (120, 3600, 180, False, "SYNC_TIMEOUT_S (180 s, por etapa) maior que o teto"),
    (None, 3600, 180, False, "Sem teto total"),
])
def test_teto_coerente_com_a_limpeza_de_orfas(db, teto, travada, timeout, ok, trecho):
    v = verificar(db, Cfg(SYNC_TETO_EXECUCAO_S=teto, SYNC_TRAVADA_S=travada,
                          SYNC_TIMEOUT_S=timeout), "teto_coerente")
    assert v.critico and v.ok is ok and trecho in v.motivo, v.motivo


def test_teto_coerente_diz_o_que_ainda_depende_de_sync_travada(db):
    """Com o sinal de vida, a órfã em 'executando' é decidida por SYNC_SEM_SINAL_S e
    pelo log: a limpeza de órfãs não mata mais a coleta viva entre SYNC_TRAVADA_S e o
    teto. O motivo dava essa justificativa (falsa); agora diz o que de fato depende
    de SYNC_TRAVADA_S, sem mudar o critério. A verificação 'execucoes_presas' também
    decide a 'executando' pelo sinal de vida (G_AUTOMACAO-3): não entra mais no
    motivo."""
    v = verificar(db, Cfg(SYNC_TETO_EXECUCAO_S=2700, SYNC_TRAVADA_S=1800,
                          SYNC_TIMEOUT_S=180), "teto_coerente")
    assert v.ok is False
    assert "limpeza de órfãs" not in v.motivo and "interrompida" not in v.motivo
    assert "'execucoes_presas'" not in v.motivo
    assert "sinal de vida" in v.motivo and "(3600 s)" in v.motivo, v.motivo


def test_status_honesto_exige_os_estados_e_as_colunas_do_contrato(db, monkeypatch):
    monkeypatch.setattr(prerequisitos, "_estados_declarados",
                        lambda: ({"concluida", "sem_dados", "erro"}, "ensaio"))
    monkeypatch.setattr(prerequisitos, "_colunas_no_modelo",
                        lambda: set(prerequisitos.COLUNAS_CONTRATO))
    monkeypatch.setattr(prerequisitos, "_colunas_no_banco", lambda db: {"qtd_linhas"})
    v = verificar(db, cfg_pronta(), "status_honesto")
    assert v.critico and v.ok is False
    assert "parcial, sem_atualizacao" in v.motivo
    assert "colunas ausentes no banco" in v.motivo and "recalculo_pendente" in v.motivo
    assert "no modelo" not in v.motivo
    monkeypatch.setattr(prerequisitos, "_estados_declarados",
                        lambda: (set(prerequisitos.ESTADOS_CONTRATO), "ensaio"))
    monkeypatch.setattr(prerequisitos, "_colunas_no_banco",
                        lambda db: set(prerequisitos.COLUNAS_CONTRATO))
    assert verificar(db, cfg_pronta(), "status_honesto").ok is True


def test_estados_declarados_vem_da_constante_ou_do_codigo(monkeypatch):
    declarados, _ = prerequisitos._estados_declarados()
    assert {"concluida", "sem_dados", "erro"} <= declarados <= set(
        prerequisitos.ESTADOS_CONTRATO) | set(getattr(service, "ESTADOS_FINAIS", ()))
    monkeypatch.setattr(service, "ESTADOS_FINAIS", ("concluida", "parcial"), raising=False)
    assert prerequisitos._estados_declarados() == ({"concluida", "parcial"},
                                                   "service.ESTADOS_FINAIS")


def test_selo_de_frescor_disponivel(db, monkeypatch):
    assert verificar(db, cfg_pronta(), "selo_frescor").ok is True
    from app.services import frescor_ranking
    monkeypatch.delattr(frescor_ranking, "frescor_da_escola")
    v = verificar(db, cfg_pronta(), "selo_frescor")
    assert v.critico and v.ok is False and "frescor_da_escola" in v.motivo


def test_execucoes_presas(db, escola_completa):
    e = escola_completa["escola"].id
    outra, terceira = escolas_extras(db, 2)
    cfg = cfg_pronta()                    # teto 45 min, limpeza de órfãs 60 min
    assert verificar(db, cfg, "execucoes_presas").ok is True
    # 'executando' há 5 min: viva.
    db.add(SincronizacaoExecucao(escola_id=e, plataforma="matific", origem="manual",
                                 status="executando", iniciada_em=AGORA - timedelta(minutes=5),
                                 created_at=AGORA - timedelta(minutes=5)))
    db.commit()
    assert verificar(db, cfg, "execucoes_presas").ok is True
    # 'executando' há 50 min sem nenhum registro no log: sem sinal de vida há mais de
    # SYNC_SEM_SINAL_S (15 min) — presa (a idade sozinha não decide; G_AUTOMACAO-3).
    presa = SincronizacaoExecucao(escola_id=e, plataforma="elefante", origem="manual",
                                  status="executando",
                                  iniciada_em=AGORA - timedelta(minutes=50),
                                  created_at=AGORA - timedelta(minutes=50))
    db.add(presa)
    db.commit()
    v = verificar(db, cfg, "execucoes_presas")
    assert v.critico and v.ok is False and f"#{presa.id} escola {e}/elefante" in v.motivo
    presa.status = "erro"
    db.commit()
    # Na fila há 2 h, sem sinal de vida: presa.
    fila = SincronizacaoExecucao(escola_id=outra, plataforma="matific", origem="manual",
                                 status="fila", created_at=AGORA - timedelta(hours=2))
    db.add(fila)
    db.commit()
    v = verificar(db, cfg, "execucoes_presas")
    assert v.ok is False and f"#{fila.id}" in v.motivo and "sem sinal de vida" in v.motivo
    # Com sinal de vida recente (a thread que espera a vez escreve no log): viva.
    db.add(SincronizacaoLog(execucao_id=fila.id, escola_id=outra, etapa="scheduler",
                            nivel="info", mensagem="aguardando a vez (ensaio)",
                            created_at=AGORA - timedelta(minutes=3)))
    db.commit()
    assert verificar(db, cfg, "execucoes_presas").ok is True
    # Nova tentativa marcada para daqui a pouco: não está presa.
    db.add(SincronizacaoExecucao(escola_id=terceira, plataforma="matific",
                                 origem="scheduler", status="fila",
                                 created_at=AGORA - timedelta(hours=3),
                                 disponivel_em=AGORA - timedelta(minutes=10)))
    db.commit()
    assert verificar(db, cfg, "execucoes_presas").ok is True


def test_credenciais_legiveis_em_todas_as_agendas_ativas(db, escola_completa):
    e = escola_completa["escola"].id
    outra, terceira = escolas_extras(db, 2)
    cfg = cfg_pronta()
    agenda(db, e, "elefante", "03:00")
    credencial(db, e, "elefante")
    assert verificar(db, cfg, "credenciais_legiveis").ok is True
    # Agenda ativa SEM credencial: o agendador falharia todo dia.
    agenda(db, outra, "matific", "03:00")
    v = verificar(db, cfg, "credenciais_legiveis")
    assert v.critico and v.ok is False and f"escola {outra}/matific" in v.motivo
    # Credencial ilegível (chave trocada): mesma falha, sem vazar nada.
    credencial(db, outra, "matific", legivel=False)
    v = verificar(db, cfg, "credenciais_legiveis")
    assert v.ok is False and f"escola {outra}/matific" in v.motivo
    assert SENHA_FICTICIA not in v.motivo and USUARIO_FICTICIO not in v.motivo
    # Agenda MANUAL não roda sozinha: não entra na conta.
    db.execute(SincronizacaoConfig.__table__.update()
               .where(SincronizacaoConfig.escola_id == outra)
               .values(cadencia="manual"))
    db.commit()
    assert verificar(db, cfg, "credenciais_legiveis").ok is True
    # Credencial SEM agenda ganha agenda diária ao ligar: é conferida também.
    credencial(db, terceira, "elefante", legivel=False)
    v = verificar(db, cfg, "credenciais_legiveis")
    assert v.ok is False and f"escola {terceira}/elefante" in v.motivo


def test_recalculo_pendente_por_alerta_aberto(db, escola_completa, monkeypatch):
    e = escola_completa["escola"].id
    monkeypatch.setattr(prerequisitos, "_recalculos_pendentes", lambda db: [])
    assert verificar(db, cfg_pronta(), "recalculo_sem_pendencia").ok is True
    alerta = SincronizacaoAlerta(escola_id=e, plataforma="elefante",
                                 tipo="recalculo_pendente", severidade="critico",
                                 mensagem="Recálculo falhou (ensaio).")
    db.add(alerta)
    db.commit()
    v = verificar(db, cfg_pronta(), "recalculo_sem_pendencia")
    assert v.critico and v.ok is False and f"escola {e}/elefante" in v.motivo
    alerta.resolvido = True
    db.commit()
    assert verificar(db, cfg_pronta(), "recalculo_sem_pendencia").ok is True


def test_recalculo_nao_verificavel_sem_a_coluna_falha(db, monkeypatch):
    monkeypatch.setattr(prerequisitos, "_recalculos_pendentes", lambda db: None)
    v = verificar(db, cfg_pronta(), "recalculo_sem_pendencia")
    assert v.critico and v.ok is False and v.motivo.startswith("Não verificável")


def test_recalculo_pendente_pela_coluna_da_0039(db, escola_completa):
    """Vale nas DUAS versões: sem a coluna (esta base), "não verificável"; com a
    coluna (depois da frente A), a marca só some com uma execução POSTERIOR com
    dado aplicado e recálculo feito."""
    e = escola_completa["escola"].id
    if "recalculo_pendente" not in SincronizacaoExecucao.__table__.columns:
        assert prerequisitos._recalculos_pendentes(db) is None
        return
    marcada = SincronizacaoExecucao(escola_id=e, plataforma="elefante", origem="manual",
                                    status="parcial", iniciada_em=AGORA, finalizada_em=AGORA)
    marcada.recalculo_pendente = True
    db.add(marcada)
    db.commit()
    assert prerequisitos._recalculos_pendentes(db) == [f"escola {e}/elefante"]
    depois = SincronizacaoExecucao(escola_id=e, plataforma="elefante", origem="manual",
                                   status="concluida", iniciada_em=AGORA,
                                   finalizada_em=AGORA)
    depois.recalculo_pendente = False
    db.add(depois)
    db.commit()
    assert prerequisitos._recalculos_pendentes(db) == []


# --- horário: Brasília e janela do backup ----------------------------------
@pytest.mark.parametrize("hora, cruza", [
    ("03:00", False),   # 06:00–06:45 UTC
    ("08:00", True),    # 11:00 UTC: dentro (se fosse UTC, 08:00 passaria)
    ("11:00", False),   # 14:00 UTC: fora (se fosse UTC, 11:00 cruzaria)
    ("07:00", True),    # 10:00–10:45 UTC: o PIOR CASO (teto) entra no backup
    ("06:40", False),   # 09:40–10:25 UTC
    ("10:29", True),    # 13:29 UTC
    ("10:30", False),   # 13:30 UTC: o backup já terminou
    ("23:00", False),   # 02:00 UTC do dia seguinte
])
def test_horario_da_agenda_em_brasilia_fora_do_backup(db, escola_completa, hora, cruza):
    e = escola_completa["escola"].id
    agenda(db, e, "elefante", hora)
    v = verificar(db, cfg_pronta(), "horario_fora_do_backup")
    assert v.critico and v.ok is (not cruza), v.motivo
    if cruza:
        assert f"escola {e}/elefante às {hora} de Brasília" in v.motivo
        assert "10:30–13:30 UTC = 07:30–10:30 em Brasília" in v.motivo


def test_o_pior_caso_da_janela_e_o_teto(db, escola_completa):
    e = escola_completa["escola"].id
    agenda(db, e, "elefante", "07:00")                    # 10:00 UTC
    assert verificar(db, cfg_pronta(SYNC_TETO_EXECUCAO_S=2700),
                     "horario_fora_do_backup").ok is False   # até 10:45
    assert verificar(db, cfg_pronta(SYNC_TETO_EXECUCAO_S=1200),
                     "horario_fora_do_backup").ok is True    # até 10:20


def test_agenda_automatica_das_03h_e_conferida_no_horario(db, escola_completa):
    """Credencial sem agenda: o agendador cria uma diária às 03:00 (Brasília) — a
    verificação já a considera, e o alcance avisa (sem bloquear)."""
    e = escola_completa["escola"].id
    credencial(db, e, "matific")
    v = verificar(db, cfg_pronta(), "horario_fora_do_backup")
    assert v.ok is True and "1 agenda(s)" in v.motivo
    alcance = verificar(db, cfg_pronta(), "alcance_ao_ligar")
    assert alcance.critico is False and alcance.ok is False
    assert f"escola {e}/matific" in alcance.motivo and "03:00 de Brasília" in alcance.motivo


def test_calculo_da_agenda_em_america_sao_paulo(db, escola_completa, monkeypatch):
    e = escola_completa["escola"].id
    assert fuso.NOME_FUSO_LOCAL == "America/Sao_Paulo"
    v = verificar(db, cfg_pronta(), "fuso_da_agenda")
    assert v.critico and v.ok is True and "03:00 de Brasília = 06:00 UTC" in v.motivo
    # Agenda gravada pela regra ANTIGA (03:00 no relógio UTC = meia-noite em
    # Brasília): a próxima execução está fora do horário escolhido.
    agenda(db, e, "elefante", "03:00", proxima=datetime(2026, 10, 23, 3, 0))
    v = verificar(db, cfg_pronta(), "fuso_da_agenda")
    assert v.ok is False and f"escola {e}/elefante marcada para 03:00" in v.motivo
    assert "00:00 de Brasília" in v.motivo


def test_fuso_em_utc_reprova_o_calculo(db, monkeypatch):
    monkeypatch.setattr(fuso, "FUSO_LOCAL", timezone.utc)
    v = verificar(db, cfg_pronta(), "fuso_da_agenda")
    assert v.ok is False and "calculou 16/01 03:00 UTC" in v.motivo


def test_fila_da_agenda_em_serie_e_so_aviso(db, escola_completa, monkeypatch):
    """10 coletas às 03:00, cada uma no teto (45 min), uma por vez: a 7ª começaria
    às 10:30 UTC — aviso para espalhar os horários; NÃO bloqueia o início."""
    ids = [escola_completa["escola"].id] + escolas_extras(db, 4)
    for eid in ids:
        for plat in ("elefante", "matific"):
            agenda(db, eid, plat, "03:00")
            credencial(db, eid, plat)
    preparar_versao_pronta(monkeypatch)
    verificacoes = prerequisitos.prerequisitos_agendador(db, cfg_pronta(), agora=AGORA)
    fila = next(v for v in verificacoes if v.id == "fila_da_agenda")
    assert fila.critico is False and fila.ok is False
    assert "10 coleta(s), 45 min cada" in fila.motivo
    assert prerequisitos.pode_iniciar(verificacoes)
    # Duas coletas cabem com folga.
    db.execute(SincronizacaoConfig.__table__.update()
               .where(SincronizacaoConfig.escola_id.in_(ids[1:])).values(ativo=False))
    db.commit()
    assert verificar(db, cfg_pronta(), "fila_da_agenda").ok is True


# --- workers e semáforo ----------------------------------------------------
def test_workers_e_semaforo(db, monkeypatch):
    monkeypatch.setenv("WEB_CONCURRENCY", "3")
    v = verificar(db, cfg_pronta(), "workers_semaforo")
    assert v.critico and v.ok is True and "até 6 coleta(s)" in v.motivo
    assert verificar(db, cfg_pronta(SYNC_WORKERS=0), "workers_semaforo").ok is False
    assert verificar(db, cfg_pronta(SYNC_POLL_S=0), "workers_semaforo").ok is False
    # O semáforo das manuais nasceu com 1 vaga (SYNC_WORKERS do boot): outra
    # configuração em vigor é incoerente até reiniciar.
    vagas = getattr(service._semaforo_manual, "_initial_value", None)
    if vagas is not None:
        v = verificar(db, cfg_pronta(SYNC_WORKERS=vagas + 2), "workers_semaforo")
        assert v.ok is False and "semáforo" in v.motivo


# --- só leitura e robustez -------------------------------------------------
def _contagens(db) -> dict:
    return {m.__tablename__: db.scalar(select(func.count()).select_from(m))
            for m in (SincronizacaoConfig, SincronizacaoExecucao, SincronizacaoLog,
                      SincronizacaoAlerta, PlataformaCredencial)}


def test_verificacoes_sao_so_leitura(db, escola_completa):
    e = escola_completa["escola"].id
    outra = escolas_extras(db, 1)[0]
    agenda(db, e, "elefante", "08:00")                       # cruza o backup
    credencial(db, e, "elefante", legivel=False)
    credencial(db, outra, "matific")                         # ganharia agenda sozinha
    db.add(SincronizacaoExecucao(escola_id=e, plataforma="matific", origem="scheduler",
                                 status="fila", created_at=AGORA - timedelta(hours=5)))
    db.commit()
    status_antes = {c.id: c.status for c in db.execute(
        select(PlataformaCredencial)).scalars()}
    antes = _contagens(db)
    verificacoes = prerequisitos.prerequisitos_agendador(db, cfg_pronta(), agora=AGORA)
    assert not prerequisitos.pode_iniciar(verificacoes)
    assert not db.new and not db.dirty and not db.deleted
    db.rollback()
    assert _contagens(db) == antes            # nenhuma agenda criada, nada cancelado
    assert {c.id: c.status for c in db.execute(
        select(PlataformaCredencial)).scalars()} == status_antes


def test_verificacao_que_estoura_vira_falha_e_nao_derruba(db, monkeypatch):
    def _quebra(ctx):
        raise RuntimeError("ensaio")

    monkeypatch.setattr(prerequisitos, "_VERIFICACOES", (
        ("quebrada", True, _quebra),
        ("selo_frescor", True, prerequisitos._v_selo_frescor),
    ))
    v = prerequisitos.prerequisitos_agendador(db, cfg_pronta(), agora=AGORA)
    assert [(x.id, x.ok) for x in v] == [("quebrada", False), ("selo_frescor", True)]
    assert v[0].motivo == "Não verificável (RuntimeError)."


# --------------------------------------------------------------------------
# Painel global: só admin global, bloco mínimo e sem segredo
# --------------------------------------------------------------------------
def test_painel_global_expoe_os_prerequisitos_sem_segredo(db, escola_completa,
                                                         cliente_global):
    e = escola_completa["escola"].id
    agenda(db, e, "elefante", "03:00")
    credencial(db, e, "elefante", legivel=False)
    antes = _contagens(db)
    r = cliente_global.get("/api/v1/sync/dashboard")
    assert r.status_code == 200, r.text
    bloco = r.json()["prerequisitos_agendador"]
    assert set(bloco) == {"habilitado", "forcar", "pode_iniciar", "decisao_no_boot",
                          "criticos_falhos", "verificacoes"}
    assert bloco["habilitado"] is False and bloco["forcar"] is False
    assert [v["id"] for v in bloco["verificacoes"]] == [
        v for v, _, _ in prerequisitos._VERIFICACOES]
    assert all(set(v) == {"id", "ok", "critico", "motivo"} for v in bloco["verificacoes"])
    assert bloco["pode_iniciar"] is False
    assert "credenciais_legiveis" in bloco["criticos_falhos"]
    assert SENHA_FICTICIA not in r.text and USUARIO_FICTICIO not in r.text
    assert "ESCOLA TESTE" not in json.dumps(bloco)
    assert _contagens(db) == antes            # GET não escreve


def test_painel_global_continua_de_pe_se_os_prerequisitos_falham(db, escola_completa,
                                                                cliente_global,
                                                                monkeypatch):
    def _quebra(*a, **k):
        raise RuntimeError("ensaio")

    monkeypatch.setattr(prerequisitos, "para_painel", _quebra)
    r = cliente_global.get("/api/v1/sync/dashboard")
    assert r.status_code == 200, r.text
    assert r.json()["prerequisitos_agendador"] is None
    assert "escolas_total" in r.json()


def test_painel_global_continua_proibido_fora_do_admin_global(cliente):
    assert cliente.get("/api/v1/sync/dashboard").status_code == 403


# --------------------------------------------------------------------------
# Boot real (processo separado): ligado pela variável, recusa sem derrubar
# --------------------------------------------------------------------------
SUBIR_E_SONDAR = BOOT + (
    "import json\n"
    "import app.core.migracoes as _m\n"
    "_m.aplicar_migracoes = lambda engine: None\n"
    "import app.sync.scheduler as _s\n"
    "_s._uma_rodada = lambda: None\n"
    "from fastapi.testclient import TestClient\n"
    "import app.main as _main\n"
    "c = TestClient(_main.app, raise_server_exceptions=False)\n"
    "print('RESULTADO=' + json.dumps({'ativo': _s.ativo(), 'decisao': _s.decisao(),\n"
    "    'motivo': _main._motivo_boot, 'live': c.get('/api/health/live').status_code,\n"
    "    'ready': c.get('/api/health/ready').status_code}))\n"
    "_s.parar()\n"
)


def _subir(url: str, **extra) -> dict:
    p = rodar(SUBIR_E_SONDAR, ambiente(url, False, SYNC_SCHEDULER_ENABLED="true",
                                       SYNC_WORKERS="0", **extra))
    linhas = [x for x in p.stdout.splitlines() if x.startswith("RESULTADO=")]
    assert p.returncode == 0 and linhas, (
        f"saída {p.returncode}\n{p.stdout[-3000:]}\n{p.stderr[-3000:]}")
    resultado = json.loads(linhas[-1][len("RESULTADO="):])
    resultado["_log"] = p.stdout + p.stderr
    return resultado


def test_boot_ligado_com_prerequisito_falho_recusa_e_app_fica_de_pe(sqlite_url):
    levar_a(sqlite_url, "heads")
    r = _subir(sqlite_url)
    assert r["motivo"] == "em_dia"
    assert r["ativo"] is False and r["decisao"] == "recusado"
    assert r["live"] == 200 and r["ready"] == 200          # o app segue servindo
    assert "NÃO iniciado" in r["_log"] and "workers_semaforo" in r["_log"]


def test_boot_ligado_e_forcado_inicia(sqlite_url):
    levar_a(sqlite_url, "heads")
    r = _subir(sqlite_url, SYNC_SCHEDULER_FORCAR="true")
    assert r["ativo"] is True and r["decisao"] == "forcado"
    assert "À FORÇA" in r["_log"]


# --------------------------------------------------------------------------
# PostgreSQL real: consulta que falha aborta a transação — as seguintes leem
# --------------------------------------------------------------------------
@pytest.mark.postgres
def test_postgres_verificacao_que_falha_nao_contamina_as_seguintes(pg_url, monkeypatch):
    from sqlalchemy import create_engine, text

    levar_a(pg_url, "heads")
    engine = create_engine(pg_url)
    try:
        def _quebra_no_banco(ctx):
            ctx.db.execute(text("SELECT * FROM tabela_que_nao_existe_e93"))

        monkeypatch.setattr(prerequisitos, "_VERIFICACOES", (
            ("quebrada", True, _quebra_no_banco),
            ("execucoes_presas", True, prerequisitos._v_execucoes_presas),
            ("status_honesto", True, prerequisitos._v_status_honesto),
            ("credenciais_legiveis", True, prerequisitos._v_credenciais_legiveis),
        ))
        with Session(engine) as db:
            v = prerequisitos.prerequisitos_agendador(db, cfg_pronta(), agora=AGORA)
            assert v[0].ok is False and v[0].motivo.startswith("Não verificável")
            assert v[1].ok is True, v[1].motivo
            assert not v[2].motivo.startswith("Não verificável"), v[2].motivo
            assert v[3].ok is True, v[3].motivo
    finally:
        engine.dispose()


@pytest.mark.postgres
def test_postgres_boot_de_producao_ligado_com_falha_recusa_e_app_fica_vivo(pg_url):
    levar_a(pg_url, "heads")
    p = rodar(SUBIR_E_SONDAR, ambiente(pg_url, True, SYNC_SCHEDULER_ENABLED="true",
                                       SYNC_WORKERS="0"))
    linhas = [x for x in p.stdout.splitlines() if x.startswith("RESULTADO=")]
    assert p.returncode == 0 and linhas, (
        f"saída {p.returncode}\n{p.stdout[-3000:]}\n{p.stderr[-3000:]}")
    r = json.loads(linhas[-1][len("RESULTADO="):])
    assert r["motivo"] == "em_dia"
    assert r["ativo"] is False and r["decisao"] == "recusado" and r["live"] == 200
    assert "NÃO iniciado" in (p.stdout + p.stderr)
