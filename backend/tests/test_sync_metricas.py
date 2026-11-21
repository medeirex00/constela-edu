"""Métricas Prometheus da sincronização (``app/sync/metricas.py``; S15 do e92).

O que se prova aqui, com dados FICTÍCIOS e sem rede:
  * valores certos do coletor que lê o BANCO na hora do scrape (idade por estado,
    último dado aplicado, ativas e presas, alertas, recálculo, credenciais);
  * nenhuma PII no /metrics (nomes, mensagens, erro_resumo, segredo);
  * a proteção do /metrics continua a mesma e o coletor nem roda sem autorização;
  * coletor que falha não derruba a rota nem deixa série parcial;
  * custo fixo por scrape (número de consultas) e consultas por índice (sem varrer
    execuções, logs ou alertas);
  * eventos em processo registrados no ponto único (fim de ``service.executar``).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY, CollectorRegistry, generate_latest
from prometheus_client.parser import text_string_to_metric_families
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.main import app
from app.models import Escola
from app.models.sincronizacao import (
    SincronizacaoAlerta,
    SincronizacaoConfig,
    SincronizacaoExecucao,
    SincronizacaoLog,
)
from app.sync import metricas, service, vault
from app.sync.interfaces import Credenciais
from tests._sync_nucleo_fakes import (
    NavElefante, PlacarFake, aluno_el, credencial, instalar, livro, rodar)

T = datetime(2026, 10, 23, 12, 0, 0)      # "agora" fixo dos testes (UTC naive)
H = timedelta(hours=1)
TOKEN = "token-de-teste-metrics-sync"
GRANDES = ("sincronizacao_execucoes", "sincronizacao_logs", "sincronizacao_alertas")


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------
def _fabrica(db):
    return sessionmaker(bind=db.get_bind())


def _coletor(db, agora=T):
    return metricas.ColetorSync(fabrica=_fabrica(db), relogio=lambda: agora)


def _amostras(coletor) -> dict:
    """{(nome, ((rótulo, valor), ...)): valor} de um scrape do coletor."""
    saida = {}
    for familia in coletor.collect():
        for s in familia.samples:
            chave = (s.name, tuple(sorted(s.labels.items())))
            assert chave not in saida, f"série repetida no scrape: {chave}"
            saida[chave] = s.value
    return saida


def _v(amostras, nome, **rotulos):
    return amostras.get((nome, tuple(sorted(rotulos.items()))))


def _series(amostras, nome):
    return {k[1]: v for k, v in amostras.items() if k[0] == nome}


def _exec(db, eid, plat, status, *, fim=None, inicio=None, criada=None, motivo=None,
          parametros=None, recalculo=False, disponivel=None, origem="manual",
          erro_resumo=None, qtd_alunos=0):
    ex = SincronizacaoExecucao(
        escola_id=eid, plataforma=plat, origem=origem, status=status, motivo=motivo,
        finalizada_em=fim, iniciada_em=inicio if inicio is not None else fim,
        created_at=criada or (inicio or fim or T), parametros=parametros or {},
        recalculo_pendente=recalculo, disponivel_em=disponivel, erro_resumo=erro_resumo,
        qtd_alunos=qtd_alunos)
    db.add(ex)
    db.flush()
    return ex


def _cred(db, eid, plat, status):
    linha = vault.salvar_credencial(db, eid, plat, Credenciais(
        usuario="robo-ficticio", senha="valor-ficticio-local"))
    linha.status = status
    db.flush()
    return linha


def _alerta(db, eid, plat, tipo, sev, *, resolvido=False, mensagem="alerta ficticio"):
    db.add(SincronizacaoAlerta(escola_id=eid, plataforma=plat, tipo=tipo, severidade=sev,
                               mensagem=mensagem, resolvido=resolvido))
    db.flush()


def _escola(db, nome):
    e = Escola(nome=nome, ano_letivo_ativo=2026)
    db.add(e)
    db.flush()
    return e.id


def _cenario(db, ec):
    """Três escolas fictícias com o estado descrito em cada bloco."""
    e1 = ec["escola"].id
    e2 = _escola(db, "ESCOLA FICTICIA DOIS")
    e3 = _escola(db, "ESCOLA FICTICIA TRES")
    # E1 — elefante: histórico, sem_atualizacao recente, erro antigo, executando presa
    _cred(db, e1, "elefante", "valida")
    _cred(db, e1, "matific", "invalida")
    _exec(db, e1, "elefante", "concluida", fim=T - 30 * H)
    _exec(db, e1, "elefante", "concluida", fim=T - 3 * H)
    _exec(db, e1, "elefante", "sem_atualizacao", fim=T - 1 * H, motivo="nada_mudou")
    _exec(db, e1, "elefante", "erro", fim=T - 48 * H, motivo="senha_invalida")
    _exec(db, e1, "elefante", "executando", inicio=T - 2 * H)
    # E1 — matific: parcial (com aluno aplicado) com marca de recálculo; coleta POR
    # PERÍODO mais nova
    _exec(db, e1, "matific", "parcial", fim=T - 5 * H, motivo="coleta_parcial", recalculo=True,
          qtd_alunos=2)
    _exec(db, e1, "matific", "concluida", fim=T - 1 * H,
          parametros={"matific_start_date": "2026-09-01", "matific_end_date": "2026-09-30"})
    _exec(db, e1, "matific", "fila", criada=T - timedelta(minutes=10))
    # E2 — agenda sem credencial (elefante) e credencial matific
    db.add(SincronizacaoConfig(escola_id=e2, plataforma="elefante", ativo=False,
                               cadencia="manual"))
    _cred(db, e2, "matific", "valida")
    viva = _exec(db, e2, "elefante", "fila", criada=T - 3 * H)
    db.add(SincronizacaoLog(execucao_id=viva.id, escola_id=e2, etapa="scheduler",
                            nivel="info", mensagem="Aguardando a vez",
                            created_at=T - timedelta(minutes=5)))
    _exec(db, e2, "matific", "cancelada", fim=T - 4 * H)
    _exec(db, e2, "matific", "fila", criada=T - 3 * H)          # sem sinal: presa
    # E3 — só credencial, sem nenhuma execução
    _cred(db, e3, "elefante", "nao_validada")
    # Alertas
    _alerta(db, e1, "elefante", "coleta_parcial", "warn")
    _alerta(db, e1, "matific", "senha_invalida", "critico")
    _alerta(db, e1, "elefante", "falha_download", "warn", resolvido=True)
    _alerta(db, e2, "matific", "recalculo_pendente", "critico")
    _alerta(db, e2, "matific", "lento", "warn", resolvido=True)
    _alerta(db, e3, "elefante", "falha_download", "warn")
    _alerta(db, e3, "elefante", "falha_download", "warn")
    _alerta(db, e3, None, "desatualizada", "critico")
    db.commit()
    return e1, e2, e3


# ---------------------------------------------------------------------------
# 1. Valores certos
# ---------------------------------------------------------------------------
def test_coletor_le_o_estado_do_banco_com_os_valores_certos(db, escola_completa):
    e1, e2, e3 = (str(i) for i in _cenario(db, escola_completa))
    a = _amostras(_coletor(db))
    idade = "sync_ultima_execucao_idade_segundos"
    # A última de cada estado (não a primeira, nem a soma).
    assert _v(a, idade, escola_id=e1, plataforma="elefante", status="concluida") == 3 * 3600
    assert _v(a, idade, escola_id=e1, plataforma="elefante",
              status="sem_atualizacao") == 3600
    assert _v(a, idade, escola_id=e1, plataforma="elefante", status="erro") == 48 * 3600
    # A coleta por período é a última 'concluida' do Matific…
    assert _v(a, idade, escola_id=e1, plataforma="matific", status="concluida") == 3600
    assert _v(a, idade, escola_id=e2, plataforma="matific", status="cancelada") == 4 * 3600
    # …mas não é "dado aplicado" no acumulado (regra de service.ultimo_sucesso_em).
    dado = "sync_ultimo_dado_aplicado_idade_segundos"
    assert _v(a, dado, escola_id=e1, plataforma="elefante") == 3 * 3600   # não a sem_atualizacao
    assert _v(a, dado, escola_id=e1, plataforma="matific") == 5 * 3600    # a parcial
    assert _v(a, dado, escola_id=e2, plataforma="matific") is None        # nunca aplicou
    assert {k for k in _series(a, idade) if dict(k)["escola_id"] == e3} == set()
    # Ativas e presas (SYNC_TRAVADA_S = 3600 s).
    assert settings.SYNC_TRAVADA_S == 3600
    ativas, presas = "sync_execucoes_ativas", "sync_execucoes_presas"
    assert _v(a, ativas, plataforma="elefante", status="executando") == 1
    assert _v(a, ativas, plataforma="elefante", status="fila") == 1
    assert _v(a, ativas, plataforma="matific", status="fila") == 2
    assert _v(a, ativas, plataforma="matific", status="executando") == 0     # zero explícito
    assert _v(a, presas, plataforma="elefante", status="executando") == 1    # 2 h > 1 h
    assert _v(a, presas, plataforma="elefante", status="fila") == 0          # deu sinal há 5 min
    assert _v(a, presas, plataforma="matific", status="fila") == 1           # 3 h sem sinal
    assert _v(a, presas, plataforma="matific", status="executando") == 0
    ativa = "sync_execucao_ativa_idade_segundos"
    assert _v(a, ativa, escola_id=e1, plataforma="elefante", status="executando") == 7200
    assert _v(a, ativa, escola_id=e1, plataforma="matific", status="fila") == 600
    assert _v(a, ativa, escola_id=e2, plataforma="elefante", status="fila") == 3 * 3600
    # Alertas abertos (os resolvidos ficam fora; plataforma vazia = 'nenhum').
    assert _series(a, "sync_alertas_abertos") == {
        (("escola_id", e1), ("plataforma", "elefante"), ("severidade", "warn"),
         ("tipo", "coleta_parcial")): 1,
        (("escola_id", e1), ("plataforma", "matific"), ("severidade", "critico"),
         ("tipo", "senha_invalida")): 1,
        (("escola_id", e2), ("plataforma", "matific"), ("severidade", "critico"),
         ("tipo", "recalculo_pendente")): 1,
        (("escola_id", e3), ("plataforma", "elefante"), ("severidade", "warn"),
         ("tipo", "falha_download")): 2,
        (("escola_id", e3), ("plataforma", "nenhum"), ("severidade", "critico"),
         ("tipo", "desatualizada")): 1,
    }
    # Recálculo pendente: marca numa execução (E1) ou alerta aberto (E2).
    assert _series(a, "sync_recalculo_pendente") == {
        (("escola_id", e1),): 1, (("escola_id", e2),): 1, (("escola_id", e3),): 0}
    assert _series(a, "sync_credencial_status") == {
        (("escola_id", e1), ("plataforma", "elefante"), ("status", "valida")): 1,
        (("escola_id", e1), ("plataforma", "matific"), ("status", "invalida")): 1,
        (("escola_id", e2), ("plataforma", "matific"), ("status", "valida")): 1,
        (("escola_id", e3), ("plataforma", "elefante"), ("status", "nao_validada")): 1,
    }
    assert _v(a, "sync_agendador_ligado") == 0
    assert _v(a, "sync_coletor_sucesso") == 1


def test_os_marcos_batem_com_as_regras_do_servico(db, escola_completa):
    """O coletor não tem regra própria: último dado = ``ultimo_sucesso_em``;
    recálculo = ``recalculo_pendente_aberto``; presa = ``_esta_travada`` /
    ``_manual_orfa`` (as que o reaper e o /status aplicam)."""
    ids = _cenario(db, escola_completa)
    a = _amostras(_coletor(db))
    for eid in ids:
        assert _v(a, "sync_recalculo_pendente", escola_id=str(eid)) == (
            1 if service.recalculo_pendente_aberto(db, eid) else 0)
        for plat in ("elefante", "matific"):
            ultimo = service.ultimo_sucesso_em(db, eid, plat)
            esperado = None if ultimo is None else (T - ultimo).total_seconds()
            assert _v(a, "sync_ultimo_dado_aplicado_idade_segundos",
                      escola_id=str(eid), plataforma=plat) == esperado
    presas = {"executando": 0, "fila": 0}
    monkey = pytest.MonkeyPatch()
    monkey.setattr(service, "_agora", lambda: T)
    try:
        for ex in db.query(SincronizacaoExecucao).filter(
                SincronizacaoExecucao.status.in_(("fila", "executando"))):
            if ex.status == "executando":
                presas["executando"] += service._esta_travada(ex)
            else:
                presas["fila"] += service._manual_orfa(ex, T)
    finally:
        monkey.undo()
    assert presas["executando"] == sum(v for k, v in _series(a, "sync_execucoes_presas").items()
                                       if dict(k)["status"] == "executando")
    assert presas["fila"] == sum(v for k, v in _series(a, "sync_execucoes_presas").items()
                                 if dict(k)["status"] == "fila")
    assert set(metricas.STATUS_FINALIZADOS) == set(service.STATUS_TERMINAIS) | {"cancelada"}


def test_parcial_sem_aluno_aplicado_nao_renova_o_ultimo_dado_aplicado(db, escola_completa):
    """P18: a 'parcial' com 0 aluno (D2(6): falhou só o endpoint dos nomes) não é
    "dado aplicado" — a idade continua contando da 'concluida'; a 'parcial' com
    aluno aplicado renova. A idade da última execução por estado não muda."""
    eid = escola_completa["escola"].id
    _cred(db, eid, "matific", "valida")
    _cred(db, eid, "elefante", "valida")
    _exec(db, eid, "matific", "concluida", fim=T - 30 * H, qtd_alunos=3)
    _exec(db, eid, "matific", "parcial", fim=T - 2 * H, motivo="coleta_parcial", qtd_alunos=0)
    _exec(db, eid, "elefante", "concluida", fim=T - 10 * H, qtd_alunos=3)
    _exec(db, eid, "elefante", "parcial", fim=T - 1 * H, motivo="coleta_parcial", qtd_alunos=1)
    db.commit()
    a = _amostras(_coletor(db))
    dado = "sync_ultimo_dado_aplicado_idade_segundos"
    assert _v(a, dado, escola_id=str(eid), plataforma="matific") == 30 * 3600
    assert _v(a, dado, escola_id=str(eid), plataforma="elefante") == 3600
    assert _v(a, "sync_ultima_execucao_idade_segundos", escola_id=str(eid),
              plataforma="matific", status="parcial") == 2 * 3600


def test_fila_de_nova_tentativa_com_disponivel_no_futuro_nao_e_presa(db, escola_completa):
    eid = escola_completa["escola"].id
    _cred(db, eid, "matific", "valida")
    _exec(db, eid, "matific", "fila", criada=T - 5 * H, disponivel=T + timedelta(minutes=5),
          origem="scheduler")
    db.commit()
    a = _amostras(_coletor(db))
    assert _v(a, "sync_execucoes_presas", plataforma="matific", status="fila") == 0
    assert _v(a, "sync_execucoes_ativas", plataforma="matific", status="fila") == 1


def test_presa_em_execucao_segue_o_sinal_de_vida_e_nao_a_idade(db, escola_completa,
                                                               monkeypatch):
    """A 'executando' presa da métrica é a que o reaper liberaria (``_esta_travada``):
    sem início nem log dentro de SYNC_SEM_SINAL_S. A coleta viva há 70 min (além de
    SYNC_TRAVADA_S) que escreveu no log há 2 min não é presa; a morta há 16 min, sem
    log, é. Pela idade (o critério antigo) as duas sairiam trocadas."""
    monkeypatch.setattr(settings, "SYNC_SEM_SINAL_S", 900)
    monkeypatch.setattr(settings, "SYNC_TRAVADA_S", 3600)
    eid = escola_completa["escola"].id
    viva = _exec(db, eid, "elefante", "executando", inicio=T - timedelta(minutes=70))
    db.add(SincronizacaoLog(execucao_id=viva.id, escola_id=eid, etapa="download",
                            nivel="info", mensagem="turma coletada (fake)",
                            created_at=T - timedelta(minutes=2)))
    _exec(db, eid, "matific", "executando", inicio=T - timedelta(minutes=16))
    db.commit()

    a = _amostras(_coletor(db))

    presas = "sync_execucoes_presas"
    assert _v(a, presas, plataforma="elefante", status="executando") == 0
    assert _v(a, presas, plataforma="matific", status="executando") == 1
    # A mesma decisão do reaper.
    monkeypatch.setattr(service, "_agora", lambda: T)
    assert [service._esta_travada(ex) for ex in db.query(SincronizacaoExecucao).filter(
        SincronizacaoExecucao.status == "executando").order_by(
        SincronizacaoExecucao.plataforma)] == [False, True]


def test_rotulo_fora_do_padrao_vira_outro_e_series_iguais_sao_somadas(db, escola_completa):
    """Dois valores livres que viram 'outro' não podem gerar a MESMA série duas
    vezes: o Prometheus recusaria o scrape inteiro."""
    eid = escola_completa["escola"].id
    _alerta(db, eid, "Plataforma A", "Tipo Livre", "warn")
    _alerta(db, eid, "Plataforma B", "Outro Tipo", "warn")
    db.commit()
    a = _amostras(_coletor(db))
    assert _series(a, "sync_alertas_abertos") == {
        (("escola_id", str(eid)), ("plataforma", "outro"), ("severidade", "warn"),
         ("tipo", "outro")): 2}
    registro = CollectorRegistry()
    registro.register(_coletor(db))
    nomes = [f.name for f in text_string_to_metric_families(generate_latest(registro).decode())]
    assert "sync_alertas_abertos" in nomes


# ---------------------------------------------------------------------------
# 2. Sem PII
# ---------------------------------------------------------------------------
NOMES = ("Ana Beatriz Souza", "João Pedro Barbosa", "Sofia Almeida Duarte")


@pytest.fixture()
def metricas_abertas(monkeypatch):
    monkeypatch.setattr(settings, "METRICS_TOKEN", TOKEN)
    monkeypatch.setattr(settings, "METRICS_PUBLICO", False)
    coletor = metricas.coletor_global()
    assert coletor is not None, "o app registra o coletor no boot"
    return coletor


def test_metrics_nao_expoe_nome_mensagem_nem_segredo(db, escola_completa, metricas_abertas,
                                                     monkeypatch):
    eid = escola_completa["escola"].id
    outra = _escola(db, "Escola Municipal Ficticia Jardim Exemplo")
    _cred(db, eid, "elefante", "valida")
    _cred(db, outra, "matific", "invalida")
    ex = _exec(db, eid, "elefante", "erro", fim=T - H, motivo="Motivo com Ana Beatriz Souza",
               erro_resumo=f"Falha ao casar {NOMES[1]}")
    db.add(SincronizacaoLog(execucao_id=ex.id, escola_id=eid, etapa="validacao",
                            nivel="warn", mensagem=f"“{NOMES[2]}” sem vínculo"))
    _alerta(db, eid, "elefante", "correspondencia_pendente", "warn",
            mensagem=f"{NOMES[0]} aguarda revisão")
    _alerta(db, outra, "Matific Sofia", "Tipo de Ana", "critico",
            mensagem="Escola Municipal Ficticia Jardim Exemplo")
    db.commit()
    monkeypatch.setattr(metricas_abertas, "fabrica", _fabrica(db))
    monkeypatch.setattr(metricas_abertas, "relogio", lambda: T)
    # Evento com motivo e código livres (higienizados no ponto único).
    metricas.execucao_finalizada(plataforma="elefante", status="erro",
                                 motivo=f"Erro: {NOMES[0]}", duracao_ms=1500,
                                 alunos_aplicados=0,
                                 falhas=[{"unidade": "turma", "codigo": NOMES[2]}])
    r = TestClient(app).get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
    corpo = r.text
    assert "sync_coletor_sucesso 1.0" in corpo
    assert 'sync_credencial_status{escola_id="%d",plataforma="matific",status="invalida"} 1.0' \
        % outra in corpo
    proibidos = [*NOMES, "Ana Beatriz", "Sofia", "Barbosa", "Jardim Exemplo", "ESCOLA TESTE",
                 "robo-ficticio", "valor-ficticio-local", "aguarda revisão", "sem vínculo",
                 "Falha ao casar"]
    for texto in proibidos:
        assert texto.lower() not in corpo.lower(), texto
    # Todo rótulo das séries sync_* é número ou código (o 'le' do histograma à parte).
    for familia in text_string_to_metric_families(corpo):
        if not familia.name.startswith("sync_"):
            continue
        for s in familia.samples:
            for rotulo, valor in s.labels.items():
                if rotulo == "le":
                    continue
                assert re.fullmatch(r"[a-z0-9_]{1,40}", valor), (familia.name, rotulo, valor)
    assert 'motivo="outro"' in corpo and 'codigo="outro"' in corpo


# ---------------------------------------------------------------------------
# 3. A proteção do /metrics continua e o coletor nem roda sem autorização
# ---------------------------------------------------------------------------
def test_protecao_do_metrics_continua_e_o_coletor_so_roda_autorizado(metricas_abertas,
                                                                      monkeypatch):
    chamadas = []
    monkeypatch.setattr(metricas_abertas, "_ler_banco",
                        lambda: chamadas.append(1) or [])
    c = TestClient(app)
    for cabecalho in ({}, {"Authorization": "Bearer errado"}, {"Authorization": "Basic x"}):
        r = c.get("/metrics", headers=cabecalho)
        assert r.status_code == 401 and "sync_" not in r.text
    assert chamadas == []
    # Sem token: 404 em qualquer ENV (e o METRICS_PUBLICO não vale em produção).
    monkeypatch.setattr(settings, "METRICS_TOKEN", "")
    for env, publico in (("dev", False), ("producao", True), ("", False)):
        monkeypatch.setattr(settings, "ENV", env)
        monkeypatch.setattr(settings, "METRICS_PUBLICO", publico)
        r = c.get("/metrics")
        assert r.status_code == 404 and "sync_" not in r.text
    assert chamadas == []
    monkeypatch.setattr(settings, "ENV", "dev")
    monkeypatch.setattr(settings, "METRICS_TOKEN", TOKEN)
    r = c.get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200 and "sync_coletor_sucesso 1.0" in r.text
    assert chamadas == [1]


# ---------------------------------------------------------------------------
# 4. Falha isolada
# ---------------------------------------------------------------------------
def test_coletor_que_falha_nao_derruba_o_metrics(db, escola_completa, metricas_abertas,
                                                 monkeypatch, caplog):
    _cenario(db, escola_completa)

    def _quebra():
        raise OperationalError("SELECT 1", {}, Exception("banco fora (simulado)"))

    monkeypatch.setattr(metricas_abertas, "fabrica", _quebra)
    with caplog.at_level(logging.WARNING, logger="constela.sync.metricas"):
        r = TestClient(app).get("/metrics", headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
    assert "http_requisicoes_total" in r.text          # o resto do /metrics sai normal
    assert "sync_coletor_sucesso 0.0" in r.text
    assert "sync_agendador_ligado 0.0" in r.text
    for nome in ("sync_ultima_execucao_idade_segundos{", "sync_alertas_abertos{",
                 "sync_credencial_status{"):
        assert nome not in r.text
    assert any("metricas_sync_coletor_falhou: OperationalError" in m for m in caplog.messages)


def test_falha_no_meio_da_leitura_nao_deixa_serie_parcial(db, escola_completa):
    _cenario(db, escola_completa)
    fabrica = _fabrica(db)

    def _sessao_que_quebra_na_terceira():
        sessao = fabrica()
        original = sessao.execute
        n = [0]

        def execute(*a, **k):
            n[0] += 1
            if n[0] == 3:
                raise OperationalError("SELECT", {}, Exception("queda simulada"))
            return original(*a, **k)

        sessao.execute = execute
        return sessao

    a = _amostras(metricas.ColetorSync(fabrica=_sessao_que_quebra_na_terceira,
                                       relogio=lambda: T))
    assert _v(a, "sync_coletor_sucesso") == 0
    assert not any(k[0] in ("sync_credencial_status", "sync_ultima_execucao_idade_segundos")
                   for k in a)        # a 1ª e a 2ª consultas deram certo, mas não saem


# ---------------------------------------------------------------------------
# 5. Custo: consultas fixas por scrape e por índice
# ---------------------------------------------------------------------------
class _Contador:
    def __init__(self, engine):
        self.engine, self.instrucoes = engine, []

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._ouvir)
        return self

    def __exit__(self, *exc):
        event.remove(self.engine, "before_cursor_execute", self._ouvir)

    def _ouvir(self, conn, cursor, statement, parameters, context, executemany):
        self.instrucoes.append((statement, parameters))

    @property
    def consultas(self):
        return [(s, p) for s, p in self.instrucoes if s.lstrip().upper().startswith("SELECT")]


def _historico(db, n_escolas, n_execucoes, n_logs, *, com_fila=False):
    for i in range(n_escolas):
        eid = _escola(db, f"ESCOLA FICTICIA CUSTO {i}")
        for plat in ("elefante", "matific"):
            _cred(db, eid, plat, "valida")
            for j in range(n_execucoes):
                ex = _exec(db, eid, plat, ("concluida", "sem_atualizacao", "erro")[j % 3],
                           fim=T - timedelta(hours=j + 1), motivo=None)
                for k in range(n_logs):
                    db.add(SincronizacaoLog(execucao_id=ex.id, escola_id=eid, etapa="download",
                                            nivel="info", mensagem=f"log ficticio {k}"))
            _alerta(db, eid, plat, "coleta_parcial", "warn")
            _alerta(db, eid, plat, "falha_download", "warn", resolvido=True)
        if com_fila:
            _exec(db, eid, "matific", "fila", criada=T - H)
    db.commit()


def _consultas_de_um_scrape(db):
    with _Contador(db.get_bind()) as cont:
        a = _amostras(_coletor(db))
    assert _v(a, "sync_coletor_sucesso") == 1
    return cont


def test_numero_de_consultas_por_scrape_nao_cresce_com_escolas_nem_historico(db):
    _historico(db, 1, 2, 1)
    pequeno = len(_consultas_de_um_scrape(db).consultas)
    _historico(db, 12, 30, 5)
    grande = len(_consultas_de_um_scrape(db).consultas)
    # 5 (eram 4): a revisão e95 tirou a marca de recálculo do par (credencial ou
    # agenda) e a lê por ESCOLA numa consulta própria — a regra de
    # service.recalculo_pendente_aberto, também para a escola sem integração.
    # Continua fixo: não cresce com escolas nem com o histórico.
    assert pequeno == grande == 5
    _historico(db, 2, 1, 1, com_fila=True)
    assert len(_consultas_de_um_scrape(db).consultas) == 6      # + o sinal de vida da fila


def test_consultas_do_scrape_usam_indice_e_nao_varrem_tabelas_grandes(db):
    """SQLite: nenhum 'SCAN' (varredura completa, de tabela ou de índice) nas tabelas
    que crescem com o tempo — só 'SEARCH' por índice. A rodada PostgreSQL
    (test_sync_metricas_pg.py) confere o mesmo com enable_seqscan=off."""
    _historico(db, 3, 10, 3, com_fila=True)
    cont = _consultas_de_um_scrape(db)
    conn = db.connection()
    planos = []
    for sql, params in cont.consultas:
        plano = " | ".join(str(linha[-1]) for linha in conn.exec_driver_sql(
            "EXPLAIN QUERY PLAN " + sql, params).all())
        planos.append(plano)
        for tabela in GRANDES:
            assert not re.search(rf"\bSCAN {tabela}\b", plano), plano
    usados = " ".join(planos)
    for indice in ("ix_sync_exec_frescor", "ix_sincronizacao_alertas_resolvido",
                   "ix_sincronizacao_logs_execucao_id"):
        assert indice in usados, usados


# ---------------------------------------------------------------------------
# 6. Eventos em processo: ponto único no fim de service.executar
# ---------------------------------------------------------------------------
def _amostra_global(nome, **rotulos):
    return REGISTRY.get_sample_value(nome, rotulos) or 0.0


def _soma_global(nome, **filtro):
    total = 0.0
    for familia in REGISTRY.collect():
        for s in familia.samples:
            if s.name == nome and all(s.labels.get(k) == v for k, v in filtro.items()):
                total += s.value
    return total


def _turma_elefante(ec):
    a, b, c = ec["alunos"]
    return {511434: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
        aluno_el(9100001, a.nome, [livro("Livro Ficticio Um")]),
        aluno_el(9100002, b.nome, [livro("Livro Ficticio Dois", "E", "2026-09-05T10:00:00")]),
        aluno_el(9100003, c.nome, [livro("Livro Ficticio Tres", "D", "2026-09-06T10:00:00")])]}}


def test_eventos_contam_cada_execucao_finalizada_uma_vez(db, escola_completa, monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    fin = "sync_execucoes_finalizadas_total"
    total_antes = _soma_global(fin)
    concl = _amostra_global(fin, plataforma="elefante", status="concluida", motivo="nenhum")
    nada = _amostra_global(fin, plataforma="elefante", status="sem_atualizacao",
                           motivo="nada_mudou")
    alunos = _amostra_global("sync_alunos_aplicados_total", plataforma="elefante")
    dur = _amostra_global("sync_execucao_duracao_segundos_count", plataforma="elefante",
                          status="concluida")
    credencial(db, eid, "elefante")
    instalar(monkeypatch, nav_elefante=NavElefante(_turma_elefante(ec)))

    ex1, erro = rodar(db, eid, "elefante")
    assert erro is None and ex1.status == "concluida" and ex1.qtd_alunos == 3
    assert _amostra_global(fin, plataforma="elefante", status="concluida",
                           motivo="nenhum") == concl + 1
    assert _amostra_global("sync_alunos_aplicados_total", plataforma="elefante") == alunos + 3
    assert _amostra_global("sync_execucao_duracao_segundos_count", plataforma="elefante",
                           status="concluida") == dur + 1

    ex2, _ = rodar(db, eid, "elefante")                      # repetição: nada mudou
    assert (ex2.status, ex2.motivo) == ("sem_atualizacao", "nada_mudou")
    assert _amostra_global(fin, plataforma="elefante", status="sem_atualizacao",
                           motivo="nada_mudou") == nada + 1
    assert _amostra_global("sync_alunos_aplicados_total", plataforma="elefante") == alunos + 3

    # Sem credencial: 'erro' com o código da falha como motivo.
    erro_antes = _amostra_global(fin, plataforma="matific", status="erro",
                                 motivo="senha_invalida")
    ex3, _ = rodar(db, eid, "matific")
    assert (ex3.status, ex3.motivo) == ("erro", "senha_invalida")
    assert _amostra_global(fin, plataforma="matific", status="erro",
                           motivo="senha_invalida") == erro_antes + 1
    assert _soma_global(fin) == total_antes + 3                # uma vez por execução


def test_falhas_por_unidade_batem_com_a_contabilidade_da_execucao(db, escola_completa,
                                                                  monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    a, b, c = ec["alunos"]
    credencial(db, eid, "matific")
    placar = PlacarFake()
    placar.linhas = [("u-a", a.nome, "3 ANO A (300396804)", 40, 10),
                     ("u-b", b.nome, "3 ANO A (300396804)", 30, 8)]
    instalar(monkeypatch, placar=placar)
    ex1, _ = rodar(db, eid, "matific")
    assert ex1.status == "concluida"
    placar.status_lb = 403                       # endpoint acessório falha
    placar.linhas = [("u-a", a.nome, "3 ANO A (300396804)", 45, 11),
                     ("u-b", b.nome, "3 ANO A (300396804)", 30, 8)]
    antes = _soma_global("sync_falhas_unidade_total", plataforma="matific")
    ex2, _ = rodar(db, eid, "matific")
    assert ex2.status == "parcial" and (ex2.qtd_falhas or 0) >= 1
    assert _soma_global("sync_falhas_unidade_total", plataforma="matific",
                        unidade="endpoint") >= 1
    assert _soma_global("sync_falhas_unidade_total", plataforma="matific") == \
        antes + ex2.qtd_falhas


def test_falha_ao_registrar_a_metrica_nao_afeta_a_execucao(db, escola_completa, monkeypatch,
                                                         caplog):
    ec = escola_completa
    eid = ec["escola"].id
    credencial(db, eid, "elefante")
    instalar(monkeypatch, nav_elefante=NavElefante(_turma_elefante(ec)))

    def _quebra(**_kw):
        raise RuntimeError("métrica quebrada (simulado)")

    monkeypatch.setattr(metricas, "execucao_finalizada", _quebra)
    with caplog.at_level(logging.WARNING, logger="constela.sync"):
        ex, erro = rodar(db, eid, "elefante")
    assert erro is None and ex.status == "concluida" and ex.qtd_alunos == 3
    assert ex.finalizada_em is not None
    assert any("metricas_sync_evento_falhou" in m for m in caplog.messages)


def test_claim_perdido_nao_conta_execucao(db, escola_completa):
    """Quem perde a corrida do claim (outro worker pegou) não registra evento."""
    eid = escola_completa["escola"].id
    ex = _exec(db, eid, "elefante", "concluida", fim=T)
    db.commit()
    antes = _soma_global("sync_execucoes_finalizadas_total")
    service.executar(db, ex)
    assert _soma_global("sync_execucoes_finalizadas_total") == antes
