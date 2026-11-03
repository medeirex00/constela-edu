"""Integração das frentes A–E da Etapa 2 (sync) — o contrato de ponta a ponta.

Cada frente testou a sua parte isolada sobre o c5e78d3. Aqui ficam os pontos em
que uma depende da outra, no ramo de integração (fix/sync-integridade):

* teto da coleta (A) × limpeza de órfãs e pré-requisito ``teto_coerente`` (E);
* estados do serviço (A) × ``status_honesto`` (E) e o selo de frescor (C);
* recálculo pendente (A) × pré-requisito ``recalculo_sem_pendencia`` (E) e a
  marca no histórico que a tela (D) mostra;
* código do erro (A) no ``motivo`` da execução e no ``ultimo_motivo`` do /status,
  que é de onde a tela (D) traduz a falha;
* revisões novas de identidade (B) contadas em ``qtd_em_revisao`` e decidindo o
  status (A);
* o painel global (A) com o bloco de pré-requisitos (E).

Dados 100% fictícios; conectores reais com navegador falso; nenhuma conexão
externa (plugin ``sem_rede_e1``).
"""
from __future__ import annotations

from sqlalchemy import select

from app.core.config import Settings, settings
from app.models import Aluno
from app.models.plataformas import SnapshotMatific
from app.models.sincronizacao import SincronizacaoExecucao
from app.services import frescor_ranking
from app.sync import prerequisitos, service
from tests._sync_nucleo_fakes import (API, PlacarFake, alertas_abertos, credencial, instalar,
                                      rodar, snap_atual)

K = "3 ANO A (300396804)"          # a sala "3º Ano A" do escola_completa


def _verificacao(db, vid: str):
    return {v.id: v for v in prerequisitos.prerequisitos_agendador(db)}[vid]


def _matific(db, ec, monkeypatch, linhas=None):
    eid = ec["escola"].id
    a, b, c = ec["alunos"]
    credencial(db, eid, "matific")
    placar = PlacarFake()
    placar.linhas = linhas if linhas is not None else [
        ("u-a", a.nome, K, 40, 10), ("u-b", b.nome, K, 30, 8), ("u-c", c.nome, K, 20, 5)]
    instalar(monkeypatch, placar=placar)
    return eid, (a, b, c), placar


# ---------------------------------------------------------------------------
# 1. Teto (A) × limpeza de órfãs (E)
# ---------------------------------------------------------------------------
def test_padrao_da_limpeza_de_orfas_passa_do_teto_da_coleta():
    """Com 30 min de SYNC_TRAVADA_S e 45 min de teto, uma coleta VIVA entre 30 e
    45 min era finalizada como 'interrompida' pela limpeza de órfãs."""
    campos = Settings.model_fields
    teto = campos["SYNC_TETO_EXECUCAO_S"].default
    travada = campos["SYNC_TRAVADA_S"].default
    assert travada > teto >= campos["SYNC_TIMEOUT_S"].default
    assert travada - teto >= 10 * 60       # folga para a aplicação e o recálculo


def test_pre_requisitos_de_teto_e_estados_passam_com_o_codigo_integrado(db, monkeypatch):
    monkeypatch.setattr(settings, "SYNC_TETO_EXECUCAO_S",
                        Settings.model_fields["SYNC_TETO_EXECUCAO_S"].default)
    monkeypatch.setattr(settings, "SYNC_TRAVADA_S",
                        Settings.model_fields["SYNC_TRAVADA_S"].default)
    for vid in ("teto_execucao", "teto_coerente", "status_honesto", "selo_frescor",
                "recalculo_sem_pendencia"):
        v = _verificacao(db, vid)
        assert v.ok, (vid, v.motivo)
    assert set(service.ESTADOS_FINAIS) == set(prerequisitos.ESTADOS_CONTRATO)
    # "Último sucesso" é o mesmo no selo do ranking (C) e no /status (A).
    assert set(frescor_ranking.STATUS_COM_DADO_APLICADO) == set(service.STATUS_COM_DADO)


# ---------------------------------------------------------------------------
# 2. Recálculo pendente (A) × pré-requisito (E) × histórico (D)
# ---------------------------------------------------------------------------
def _falhar_recalculo(monkeypatch):
    original = service._recalcular_ao_final

    def falha(*_a, **_k):
        raise RuntimeError("recálculo falhou (simulado)")
    monkeypatch.setattr(service, "_recalcular_ao_final", falha)
    return original


def test_recalcular_manual_solta_o_pre_requisito_e_a_marca_do_historico(
        db, cliente, escola_completa, monkeypatch):
    eid, _al, _placar = _matific(db, escola_completa, monkeypatch)
    _falhar_recalculo(monkeypatch)
    ex, erro = rodar(db, eid, "matific")
    assert erro is None and ex.status == "concluida" and ex.recalculo_pendente is True
    assert _verificacao(db, "recalculo_sem_pendencia").ok is False

    r = cliente.post(f"{API}/escolas/{eid}/importacoes/recalcular")
    assert r.status_code == 200, r.text
    db.expire_all()
    assert "recalculo_pendente" not in alertas_abertos(db, eid, "matific")
    assert db.get(SincronizacaoExecucao, ex.id).recalculo_pendente is False
    v = _verificacao(db, "recalculo_sem_pendencia")
    assert v.ok, v.motivo
    h = cliente.get(f"{API}/escolas/{eid}/sync/historico").json()
    assert [e["recalculo_pendente"] for e in h] == [False]
    st = cliente.get(f"{API}/escolas/{eid}/sync/status").json()
    mt = next(p for p in st["plataformas"] if p["plataforma"] == "matific")
    assert mt["recalculo_pendente"] is False


def test_nada_mudou_que_refaz_o_recalculo_tambem_solta_o_pre_requisito(
        db, escola_completa, monkeypatch):
    eid, _al, _placar = _matific(db, escola_completa, monkeypatch)
    original = _falhar_recalculo(monkeypatch)
    ex, _ = rodar(db, eid, "matific")
    assert ex.recalculo_pendente is True
    monkeypatch.setattr(service, "_recalcular_ao_final", original)
    ex2, _ = rodar(db, eid, "matific")            # mesma coleta: nada mudou
    assert ex2.status == "sem_atualizacao" and ex2.motivo == "nada_mudou"
    db.expire_all()
    assert db.get(SincronizacaoExecucao, ex.id).recalculo_pendente is False
    v = _verificacao(db, "recalculo_sem_pendencia")
    assert v.ok, v.motivo


def test_alerta_resolvido_a_mao_sem_recalcular_continua_bloqueando(
        db, cliente, escola_completa, monkeypatch):
    """Fechar o alerta pela tela não recalcula nada: a marca da execução segura
    o pré-requisito até um recálculo de verdade."""
    eid, _al, _placar = _matific(db, escola_completa, monkeypatch)
    _falhar_recalculo(monkeypatch)
    ex, _ = rodar(db, eid, "matific")
    alerta = next(a for a in cliente.get(f"{API}/escolas/{eid}/sync/alertas?resolvido=false")
                  .json() if a["tipo"] == "recalculo_pendente")
    r = cliente.post(f"{API}/escolas/{eid}/sync/alertas/{alerta['id']}/resolver")
    assert r.status_code in (200, 204), r.text
    db.expire_all()
    assert db.get(SincronizacaoExecucao, ex.id).recalculo_pendente is True
    assert _verificacao(db, "recalculo_sem_pendencia").ok is False


def test_recalcular_depois_do_alerta_resolvido_a_mao_grava_a_marca_zerada(
        db, cliente, escola_completa, monkeypatch):
    """Alerta fechado à mão e DEPOIS um /recalcular que dá certo: a marca das
    execuções tem de ficar zerada no banco. Sem alerta aberto para fechar, o
    zeramento da marca ficava fora de qualquer commit e se perdia ao fechar a
    sessão da requisição — o histórico e o pré-requisito seguiam travados."""
    eid, _al, _placar = _matific(db, escola_completa, monkeypatch)
    _falhar_recalculo(monkeypatch)
    ex, _ = rodar(db, eid, "matific")
    alerta = next(a for a in cliente.get(f"{API}/escolas/{eid}/sync/alertas?resolvido=false")
                  .json() if a["tipo"] == "recalculo_pendente")
    assert cliente.post(
        f"{API}/escolas/{eid}/sync/alertas/{alerta['id']}/resolver").status_code in (200, 204)
    # Fechar o alerta não recalculou nada: o /status segue dizendo (é de onde a
    # tela oferece "Recalcular agora"), coerente com o histórico e o pré-requisito.
    assert _recalculo_no_status(cliente, eid) is True

    r = cliente.post(f"{API}/escolas/{eid}/importacoes/recalcular")
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(SincronizacaoExecucao, ex.id).recalculo_pendente is False
    v = _verificacao(db, "recalculo_sem_pendencia")
    assert v.ok, v.motivo
    h = cliente.get(f"{API}/escolas/{eid}/sync/historico").json()
    assert [e["recalculo_pendente"] for e in h] == [False]
    assert _recalculo_no_status(cliente, eid) is False


def _recalculo_no_status(cliente, eid) -> bool:
    st = cliente.get(f"{API}/escolas/{eid}/sync/status").json()
    return next(p for p in st["plataformas"] if p["plataforma"] == "matific")[
        "recalculo_pendente"]


def test_coleta_seguinte_recalcula_a_marca_que_sobrou_do_alerta_fechado_a_mao(
        db, cliente, escola_completa, monkeypatch):
    """A marca que sobrou (alerta fechado à mão) faz a coleta seguinte recalcular
    mesmo sem dado novo — como faria com o alerta aberto — e então solta."""
    eid, _al, _placar = _matific(db, escola_completa, monkeypatch)
    original = _falhar_recalculo(monkeypatch)
    ex, _ = rodar(db, eid, "matific")
    alerta = next(a for a in cliente.get(f"{API}/escolas/{eid}/sync/alertas?resolvido=false")
                  .json() if a["tipo"] == "recalculo_pendente")
    assert cliente.post(
        f"{API}/escolas/{eid}/sync/alertas/{alerta['id']}/resolver").status_code in (200, 204)
    monkeypatch.setattr(service, "_recalcular_ao_final", original)
    ex2, _ = rodar(db, eid, "matific")            # mesma coleta: nada mudou
    assert ex2.status == "sem_atualizacao" and ex2.motivo == "nada_mudou"
    db.expire_all()
    assert db.get(SincronizacaoExecucao, ex.id).recalculo_pendente is False
    assert _verificacao(db, "recalculo_sem_pendencia").ok
    assert _recalculo_no_status(cliente, eid) is False


# ---------------------------------------------------------------------------
# 3. Código do erro (A) → motivo / ultimo_motivo (o que a tela D traduz)
# ---------------------------------------------------------------------------
def test_erro_de_acesso_ao_dado_chega_a_tela_pelo_motivo(
        db, cliente, escola_completa, monkeypatch):
    eid, _al, placar = _matific(db, escola_completa, monkeypatch)
    placar.status_ss = 403
    ex, erro = rodar(db, eid, "matific")
    assert erro is None and ex.status == "erro" and ex.motivo == "sem_acesso_ao_dado"
    st = cliente.get(f"{API}/escolas/{eid}/sync/status").json()
    mt = next(p for p in st["plataformas"] if p["plataforma"] == "matific")
    assert (mt["ultimo_status"], mt["ultimo_motivo"]) == ("erro", "sem_acesso_ao_dado")
    assert mt["ultima_tentativa"]["motivo"] == "sem_acesso_ao_dado"
    h = cliente.get(f"{API}/escolas/{eid}/sync/historico").json()
    assert (h[0]["status"], h[0]["motivo"]) == ("erro", "sem_acesso_ao_dado")


def test_erro_por_teto_de_tempo_tem_motivo_timeout(db, escola_completa, monkeypatch):
    eid, _al, placar = _matific(db, escola_completa, monkeypatch)
    monkeypatch.setattr(settings, "SYNC_TETO_EXECUCAO_S", 1)
    placar.atraso_s = 2.5
    ex, _ = rodar(db, eid, "matific")
    assert ex.status == "erro" and ex.motivo == "timeout"


def test_motivo_do_erro_pela_contabilidade_e_o_codigo_dominante(
        db, escola_completa, monkeypatch):
    """Resposta fora do formato (campos renomeados): nenhum dado aplicado e o
    arquivo perdeu campo essencial — o motivo é o CÓDIGO dominante das falhas
    ('parser_incompativel'), que a tela traduz ("formato do relatório mudou").
    Antes era 'coleta_incompleta' e o histórico dizia só "falhou" (revisão e93,
    achado 12)."""
    eid, _al, placar = _matific(db, escola_completa, monkeypatch)
    placar.renomear = {"activities_completed": "atividades_feitas", "score": "pontos"}
    ex, _ = rodar(db, eid, "matific")
    assert ex.status == "erro" and ex.motivo == "parser_incompativel"


# ---------------------------------------------------------------------------
# 4. Identidade (B) × contabilidade e status (A)
# ---------------------------------------------------------------------------
def test_nome_incompleto_do_matific_conta_em_revisao_e_nao_cria_ficha(
        db, escola_completa, monkeypatch):
    """Sem competição no Matific o nome cheio não vem: a linha só tem o
    abreviado ("ANA S"). Frente B: revisão 'nome_incompleto', nenhuma ficha.
    Frente A: nada aplicado → 'sem_atualizacao'. Ajuste da Etapa 3 (forma C): o
    motivo era 'correspondencia_pendente'; nenhuma das contas é vinculada nesta
    escola, então nenhuma foi conferida e o motivo é 'tudo_em_revisao' (não é "em
    dia"). O alerta continua o 'correspondencia_pendente'."""
    eid, _al, placar = _matific(db, escola_completa, monkeypatch)
    placar.com_competicao = False
    antes = db.execute(select(Aluno.id).where(Aluno.escola_id == eid)).scalars().all()
    ex, erro = rodar(db, eid, "matific")
    assert erro is None
    assert (ex.status, ex.motivo) == ("sem_atualizacao", "tudo_em_revisao")
    assert ex.qtd_linhas == 3 and ex.qtd_em_revisao == 3 and ex.qtd_alunos == 0
    assert db.execute(select(Aluno.id).where(Aluno.escola_id == eid)).scalars().all() == antes
    assert "correspondencia_pendente" in alertas_abertos(db, eid, "matific")
    assert service.ultimo_sucesso_em(db, eid, "matific") is None


def test_uuid_repetido_no_placar_vai_para_revisao_e_o_resto_entra(
        db, escola_completa, monkeypatch):
    """Duas contas coladas no mesmo uuid (B: 'id_externo_duplicado') não aplicam
    número em ninguém; a terceira criança entra normalmente — a execução é
    'concluida' (revisão não é falha). "Em revisão" conta CONTAS distintas
    (revisão e93, regressão R5): as duas linhas são de UM uuid, com o mesmo nome
    cheio do student-leaderboard — 1 conta."""
    ec = escola_completa
    a, b, c = ec["alunos"]
    eid, _al, _placar = _matific(db, ec, monkeypatch, linhas=[
        ("u-dup", a.nome, K, 40, 10), ("u-dup", b.nome, K, 30, 8), ("u-c", c.nome, K, 20, 5)])
    ex, erro = rodar(db, eid, "matific")
    assert erro is None
    assert ex.status == "concluida" and ex.qtd_alunos == 1
    assert ex.qtd_em_revisao == 1 and ex.qtd_linhas == 3
    assert snap_atual(db, SnapshotMatific, a.id) is None
    assert snap_atual(db, SnapshotMatific, b.id) is None
    assert snap_atual(db, SnapshotMatific, c.id).atividades == 5


# ---------------------------------------------------------------------------
# 5. Painel global (A) com os pré-requisitos (E)
# ---------------------------------------------------------------------------
def test_painel_global_traz_pre_requisitos_com_estados_e_teto_ok(
        db, cliente_global, escola_completa, monkeypatch):
    monkeypatch.setattr(settings, "SYNC_TETO_EXECUCAO_S",
                        Settings.model_fields["SYNC_TETO_EXECUCAO_S"].default)
    monkeypatch.setattr(settings, "SYNC_TRAVADA_S",
                        Settings.model_fields["SYNC_TRAVADA_S"].default)
    r = cliente_global.get(f"{API}/sync/dashboard")
    assert r.status_code == 200, r.text
    bloco = r.json()["prerequisitos_agendador"]
    assert bloco is not None and bloco["habilitado"] is False
    falhos = set(bloco["criticos_falhos"])
    assert not falhos & {"teto_execucao", "teto_coerente", "status_honesto", "selo_frescor",
                         "recalculo_sem_pendencia"}, bloco
