"""Integridade do NÚCLEO da sincronização (Etapa 2, frente A): teto de tempo, falha
DEPOIS de gravar (exceção comum e IntegrityError), recálculo e recalculo_pendente,
repetição sem duplicar, período preservado na retentativa e período de 1 dia nos
três modos de MATIFIC_END_DATE. Adaptado dos ensaios e92 (S4, S5, S7, S10; P02,
P05, P20). Dados fictícios; conectores reais com navegador falso; sem rede.
"""
import time
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select, text

from app.core.config import settings
from app.models import Aluno, Turma
from app.models.plataformas import Leitura, SnapshotElefante, SnapshotMatific
from app.models.sincronizacao import SincronizacaoExecucao
from app.routers import importacoes as imp
from app.sync import aovivo, orchestrator, service
from tests._sync_nucleo_fakes import (
    API, NavElefante, PlacarFake, aluno_el, alertas_abertos, contagens, credencial,
    execucoes, instalar, livro, logs, nota, novo_aluno, ranking, rodar, snap_atual, vincular)
from tests._ano_letivo import no_ano_de_hoje

K1, K2 = "3 ANO A (300396804)", "4 ANO B (300397061)"
P_SET = {"matific_start_date": "2026-09-01", "matific_end_date": "2026-09-30"}


def _notas_refletem_retratos(db, eid):
    """[(aluno_id, dimensão, retrato, nota)] dos retratos gravados que NÃO chegaram
    à Nota (o ranking ficaria atrás dos dados)."""
    divergentes = []
    for (aid,) in db.execute(select(Aluno.id).where(Aluno.escola_id == eid)).all():
        se = snap_atual(db, SnapshotElefante, aid)
        sm = snap_atual(db, SnapshotMatific, aid)
        n = nota(db, aid)
        det = ((n.detalhes or {}).get("dimensoes") or {}) if n else {}
        if se is not None:
            dados = (det.get("leitura") or {}).get("dados") or {}
            if not (n and n.aferido_leitura and dados.get("livros_unicos") == se.livros_unicos):
                divergentes.append((aid, "leitura", se.livros_unicos, dados.get("livros_unicos")))
        if sm is not None:
            dados = (det.get("matematica") or {}).get("dados") or {}
            if not (n and n.aferido_matematica and dados.get("atividades") == sm.atividades):
                divergentes.append((aid, "matematica", sm.atividades, dados.get("atividades")))
    return divergentes


def _matific_duas_turmas(db, ec, monkeypatch):
    eid = ec["escola"].id
    a = ec["alunos"][0]
    t2 = Turma(escola_id=eid, nome="4º Ano B", ano_escolar="4º Ano",
               ano_letivo=ec["escola"].ano_letivo_ativo)
    db.add(t2)
    db.flush()
    d = novo_aluno(db, eid, t2, "Crianca Ficticia Quarto Ano")
    db.commit()
    credencial(db, eid, "matific")
    placar = PlacarFake()
    placar.linhas = [("u-a", a.nome, K1, 40, 10), ("u-d", d.nome, K2, 8, 2)]
    instalar(monkeypatch, placar=placar)
    return eid, a, d, placar


def _elefante_duas_turmas(db, ec, monkeypatch):
    eid = ec["escola"].id
    a, b, _c = ec["alunos"]
    t2 = Turma(escola_id=eid, nome="4º Ano B", ano_escolar="4º Ano",
               ano_letivo=ec["escola"].ano_letivo_ativo)
    db.add(t2)
    db.flush()
    d = novo_aluno(db, eid, t2, "Crianca Ficticia Quarto Ano")
    db.commit()
    credencial(db, eid, "elefante")
    turmas = {511434: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
                  aluno_el(9100001, a.nome, [livro("Livro Ficticio Um")]),
                  aluno_el(9100002, b.nome, [livro("Livro Ficticio Dois", "E", "2026-09-05T10:00:00")])]},
              600001: {"nome": "4 ANO B TARDE ANUAL", "alunos": [
                  aluno_el(9200001, d.nome, [livro("Livro Ficticio Tres", "D", "2026-09-07T10:00:00")])]}}
    nav = NavElefante(turmas)
    instalar(monkeypatch, nav_elefante=nav)
    return eid, (a, b), d, nav


def _quebrar_leituras_de(monkeypatch, aluno_id, exc_factory):
    original = imp._importar_elefante_leituras

    def quebra(db_, escola_id, importacao, aluno, *a, **k):
        r = original(db_, escola_id, importacao, aluno, *a, **k)
        if aluno.id == aluno_id:
            db_.flush()
            raise exc_factory(db_, escola_id, aluno)
        return r
    monkeypatch.setattr(imp, "_importar_elefante_leituras", quebra)
    return original


def _duplicar_leitura(db_, escola_id, aluno):
    lida = db_.execute(select(Leitura).where(Leitura.aluno_id == aluno.id)).scalars().first()
    db_.add(Leitura(escola_id=escola_id, aluno_id=aluno.id, livro_id=lida.livro_id,
                    data=lida.data))
    db_.flush()               # viola a UNIQUE de Leitura → IntegrityError no flush
    return RuntimeError("não deveria chegar aqui")


# ===========================================================================
# 1. TETO DE TEMPO TOTAL (SYNC_TETO_EXECUCAO_S)
# ===========================================================================
@pytest.mark.parametrize("plataforma", ["elefante", "matific"])
def test_teto_total_aborta_perto_do_teto_e_termina_erro_timeout(
        db, escola_completa, monkeypatch, plataforma):
    ec = escola_completa
    eid = ec["escola"].id
    a = ec["alunos"][0]
    credencial(db, eid, plataforma)
    monkeypatch.setattr(settings, "SYNC_TETO_EXECUCAO_S", 1)
    if plataforma == "elefante":
        turmas = {511434: {"nome": "3 ANO A TARDE ANUAL",
                           "alunos": [aluno_el(9100001, a.nome, [livro("Livro Ficticio Um")])]}}
        instalar(monkeypatch, nav_elefante=NavElefante(turmas, atraso_s=2.5))
    else:
        placar = PlacarFake()
        placar.linhas = [("u-a", a.nome, K1, 40, 10)]
        placar.atraso_s = 2.5
        instalar(monkeypatch, placar=placar)
    t0 = time.monotonic()
    ex, erro = rodar(db, eid, plataforma)
    dur = time.monotonic() - t0
    assert erro is None and dur < 2.0, f"durou {dur:.1f}s com teto de 1s"
    assert ex.status == "erro" and ex.finalizada_em is not None
    assert "teto de 1s" in ex.erro_resumo
    assert "timeout" in alertas_abertos(db, eid, plataforma)
    assert service._execucao_ativa(db, eid, plataforma) is None      # não ficou 'executando'
    assert service.ultimo_sucesso_em(db, eid, plataforma) is None


def test_teto_padrao_tem_folga_sobre_a_maior_coleta_vista():
    # A #407 do Elefante levou ~17 min: o teto padrão não pode abortá-la.
    assert settings.SYNC_TETO_EXECUCAO_S >= 17 * 60 * 2


# ===========================================================================
# 2. FALHA DEPOIS DE GRAVAR → 'parcial' (falha_apos_gravacao) + recálculo
# ===========================================================================
@no_ano_de_hoje
def test_matific_excecao_no_2o_arquivo_e_parcial_e_o_gravado_esta_nas_notas(
        db, cliente, escola_completa, monkeypatch):
    eid, a, d, placar = _matific_duas_turmas(db, escola_completa, monkeypatch)
    rodar(db, eid, "matific")                                  # 1ª sync completa
    placar.linhas = [("u-a", a.nome, K1, 200, 60), ("u-d", d.nome, K2, 9, 3)]
    original = imp._importar_matific

    def quebra(db_, escola_id, importacao, aluno, *a_, **k):
        r = original(db_, escola_id, importacao, aluno, *a_, **k)
        if aluno.id == d.id:
            raise RuntimeError("falha simulada depois de gravar")
        return r
    monkeypatch.setattr(imp, "_importar_matific", quebra)
    ex, erro = rodar(db, eid, "matific")
    assert erro is None
    assert ex.status == "parcial" and ex.motivo == "falha_apos_gravacao"
    assert ex.qtd_alunos == 1 and ex.recalculo_pendente is False
    assert any(n == "error" for _e, n, _m in logs(db, ex.id))
    assert {"coleta_parcial", "erro_inesperado"} <= set(alertas_abertos(db, eid, "matific"))
    # O que entrou (a) está nas notas e no /ranking; o arquivo que falhou (d) não deixou nada.
    assert _notas_refletem_retratos(db, eid) == []
    sa = snap_atual(db, SnapshotMatific, a.id)
    rk = ranking(cliente, eid, "matematica")
    assert (rk[a.id]["dados"]["atividades"], rk[a.id]["dados"]["estrelas"]) == (60, 200) \
        == (sa.atividades, sa.estrelas)
    assert snap_atual(db, SnapshotMatific, d.id).atividades == 2
    # Falha no meio não salva o cursor nem marca a coleta completa.
    assert service._execucao_ativa(db, eid, "matific") is None


def test_elefante_excecao_no_meio_e_parcial_sem_leitura_parcial_e_com_notas(
        db, escola_completa, monkeypatch):
    eid, _ab, d, _nav = _elefante_duas_turmas(db, escola_completa, monkeypatch)
    _quebrar_leituras_de(monkeypatch, d.id, lambda *_: RuntimeError("falha simulada"))
    ex, erro = rodar(db, eid, "elefante")
    assert erro is None
    assert ex.status == "parcial" and ex.motivo == "falha_apos_gravacao"
    assert db.scalar(select(func.count()).select_from(Leitura).where(Leitura.aluno_id == d.id)) == 0
    assert _notas_refletem_retratos(db, eid) == []
    # Sem cursor salvo: a próxima coleta busca tudo de novo.
    assert service._carregar_contadores(db, eid, "elefante") == {}


def test_elefante_integrity_error_no_flush_e_parcial_sem_travar_e_a_seguinte_conclui(
        db, escola_completa, monkeypatch):
    eid, _ab, d, _nav = _elefante_duas_turmas(db, escola_completa, monkeypatch)
    original = _quebrar_leituras_de(monkeypatch, d.id, _duplicar_leitura)
    ex, erro = rodar(db, eid, "elefante")
    assert erro is None
    assert ex.status == "parcial" and ex.motivo == "falha_apos_gravacao"
    assert ex.finalizada_em is not None
    assert sum(1 for _e, n, _m in logs(db, ex.id) if n == "error") >= 1
    assert service._execucao_ativa(db, eid, "elefante") is None
    assert _notas_refletem_retratos(db, eid) == []
    monkeypatch.setattr(imp, "_importar_elefante_leituras", original)
    ex2, erro2 = rodar(db, eid, "elefante")
    assert erro2 is None and ex2.status == "concluida"
    assert snap_atual(db, SnapshotElefante, d.id) is not None
    assert _notas_refletem_retratos(db, eid) == []
    assert "coleta_parcial" not in alertas_abertos(db, eid, "elefante")


def test_falha_antes_de_gravar_continua_erro_sem_dado(db, escola_completa, monkeypatch):
    from sqlalchemy.exc import OperationalError
    eid, _a, _d, _p = _matific_duas_turmas(db, escola_completa, monkeypatch)

    def quebra(db_, escola, arquivo, **kw):
        raise OperationalError("SELECT 1", {}, Exception("conexão perdida (simulada)"))
    monkeypatch.setattr(orchestrator, "aplicar_arquivo", quebra)
    ex, erro = rodar(db, eid, "matific")
    assert erro is None and ex.status == "erro"
    assert db.scalar(select(func.count()).select_from(SnapshotMatific)) == 0
    assert service.vault.obter_linha(db, eid, "matific").status == "nao_validada"


# ===========================================================================
# 3. Recálculo que falha → recalculo_pendente + alerta crítico; fecha no próximo
# ===========================================================================
@no_ano_de_hoje
def test_recalculo_que_falha_fica_pendente_e_fecha_no_proximo(
        db, cliente, escola_completa, monkeypatch):
    eid, a, d, placar = _matific_duas_turmas(db, escola_completa, monkeypatch)
    original = service._recalcular_ao_final

    def falha(*_a, **_k):
        raise RuntimeError("recálculo falhou (simulado)")
    monkeypatch.setattr(service, "_recalcular_ao_final", falha)
    ex, erro = rodar(db, eid, "matific")
    assert erro is None
    assert ex.status == "concluida" and ex.recalculo_pendente is True    # o dado entrou
    assert "recalculo_pendente" in alertas_abertos(db, eid, "matific")
    st = cliente.get(f"{API}/escolas/{eid}/sync/status").json()
    mt = next(p for p in st["plataformas"] if p["plataforma"] == "matific")
    assert mt["recalculo_pendente"] is True
    # A próxima sincronização (nada mudou) refaz o recálculo pendente e o fecha.
    monkeypatch.setattr(service, "_recalcular_ao_final", original)
    ex2, _ = rodar(db, eid, "matific")
    assert ex2.status == "sem_atualizacao" and ex2.recalculo_pendente is False
    assert "recalculo_pendente" not in alertas_abertos(db, eid, "matific")
    assert _notas_refletem_retratos(db, eid) == []


def test_recalcular_manual_fecha_o_recalculo_pendente(db, cliente, escola_completa, monkeypatch):
    eid, _a, _d, _p = _matific_duas_turmas(db, escola_completa, monkeypatch)
    monkeypatch.setattr(service, "_recalcular_ao_final",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    rodar(db, eid, "matific")
    assert "recalculo_pendente" in alertas_abertos(db, eid, "matific")
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/recalcular")
    assert r.status_code == 200, r.text
    db.expire_all()
    assert "recalculo_pendente" not in alertas_abertos(db, eid, "matific")


# ===========================================================================
# 4. REPETIÇÃO não duplica: 2ª coleta igual = 'sem_atualizacao' (nada_mudou)
# ===========================================================================
NUCLEO = ("alunos", "matriculas", "turmas", "identidades", "leituras", "eventos", "livros",
          "notas", "revisoes")


def test_repeticao_no_mesmo_dia_e_no_seguinte_nao_duplica_e_nao_e_sucesso(
        db, escola_completa, monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    a, b, _c = ec["alunos"]
    credencial(db, eid, "elefante")
    turmas = {511434: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
        aluno_el(9100001, a.nome, [livro("Livro Ficticio Um"),
                                   livro("Livro Ficticio Dois", "E", "2026-09-10T10:00:00")]),
        aluno_el(9100002, b.nome, [livro("Livro Ficticio Dois", "E", "2026-09-05T08:00:00")])]}}
    instalar(monkeypatch, nav_elefante=NavElefante(turmas))
    medidas = []
    for _ in range(3):
        ex, _ = rodar(db, eid, "elefante")
        medidas.append((ex.status, ex.motivo, ex.qtd_alunos, contagens(db, eid)))
    db.execute(text("UPDATE snapshots_elefante SET data_referencia = :d"), {"d": "2026-10-20 12:00:00"})
    db.execute(text("DELETE FROM configuracoes WHERE chave LIKE '%ultima_coleta_completa%'"))
    db.commit()
    ex, _ = rodar(db, eid, "elefante")
    medidas.append((ex.status, ex.motivo, ex.qtd_alunos, contagens(db, eid)))
    assert medidas[0][:3] == ("concluida", None, 2)
    assert all(m[:3] == ("sem_atualizacao", "nada_mudou", 0) for m in medidas[1:])
    for k in NUCLEO:
        assert len({m[3][k] for m in medidas}) == 1, k
    primeira = execucoes(db, eid, "elefante")[0]
    # Último sucesso = a 1ª (a única que aplicou dado); verificação = a última.
    assert service.ultimo_sucesso_em(db, eid, "elefante") == primeira.finalizada_em
    assert service.ultima_verificacao_em(db, eid, "elefante") == ex.finalizada_em


def test_nada_mudou_fecha_desatualizada_e_falhas(db, escola_completa, monkeypatch):
    from app.models.sincronizacao import SincronizacaoConfig
    ec = escola_completa
    eid = ec["escola"].id
    a = ec["alunos"][0]
    credencial(db, eid, "matific")
    placar = PlacarFake()
    placar.linhas = [("u-a", a.nome, K1, 40, 10)]
    instalar(monkeypatch, placar=placar)
    rodar(db, eid, "matific")
    cfg = SincronizacaoConfig(escola_id=eid, plataforma="matific", ativo=True, cadencia="diaria")
    db.add(cfg)
    db.execute(text("UPDATE sincronizacao_execucoes SET finalizada_em = '2026-01-01 00:00:00'"))
    db.commit()
    service.atualizar_alerta_desatualizada(db, cfg)
    service.abrir_alerta(db, eid, "matific", "falha_download", "falha anterior (simulada)")
    db.commit()
    assert {"desatualizada", "falha_download"} <= set(alertas_abertos(db, eid, "matific"))
    ex, _ = rodar(db, eid, "matific")
    assert ex.status == "sem_atualizacao" and ex.motivo == "nada_mudou"
    assert alertas_abertos(db, eid, "matific") == []


# ===========================================================================
# 5. PERÍODO preservado (retentativa e pedido depois de falha)
# ===========================================================================
def test_retentativa_com_agendador_preserva_e_coleta_o_periodo(db, escola_completa, monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    a = ec["alunos"][0]
    credencial(db, eid, "matific")
    monkeypatch.setattr(settings, "SYNC_SCHEDULER_ENABLED", True)
    placar = PlacarFake()
    placar.linhas = [("u-a", a.nome, K1, 40, 10)]
    placar.excecao_ss = RuntimeError("falha simulada")
    instalar(monkeypatch, placar=placar)
    rodar(db, eid, "matific", parametros=P_SET)
    retry = [e for e in execucoes(db, eid, "matific") if e.status == "fila"]
    assert len(retry) == 1 and retry[0].tentativa == 2 and retry[0].parametros == P_SET
    retry[0].disponivel_em = service._agora() - timedelta(seconds=1)
    db.commit()
    placar.excecao_ss = None
    for ex in service.proximas_da_fila(db):
        service.executar(db, ex)
    db.expire_all()
    assert placar.filtros[-1] == "start_date=2026-09-01&end_date=2026-09-30"
    s = snap_atual(db, SnapshotMatific, a.id)
    assert s is not None and str(s.data_referencia)[:7] == "2026-09"


def test_sem_agendador_falha_nao_deixa_retentativa_orfa(db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "matific")
    placar = PlacarFake()
    placar.excecao_ss = RuntimeError("falha simulada")
    instalar(monkeypatch, placar=placar)
    assert settings.SYNC_SCHEDULER_ENABLED is False
    ex, _ = rodar(db, eid, "matific", parametros=P_SET)
    assert ex.status == "erro"
    assert [e.id for e in execucoes(db, eid, "matific") if e.status == "fila"] == []


def _rota_sincrona(db, monkeypatch):
    monkeypatch.setattr(service, "disparar_em_thread",
                        lambda exid: service.executar(db, db.get(SincronizacaoExecucao, exid)))


def _matific_vinculado(db, ec, monkeypatch):
    eid = ec["escola"].id
    a = ec["alunos"][0]
    credencial(db, eid, "matific")
    vincular(db, eid, a.id, "matific", "u-a")
    db.commit()
    placar = PlacarFake()
    placar.linhas = [("u-a", a.nome, K1, 50, 20)]
    instalar(monkeypatch, placar=placar)
    _rota_sincrona(db, monkeypatch)
    return eid, a, placar


def _datas(db, aid):
    return sorted(str(s.data_referencia)[:10] for s in db.execute(
        select(SnapshotMatific).where(SnapshotMatific.aluno_id == aid)).scalars())


def test_pedido_de_periodo_depois_de_falha_coleta_e_expoe_o_periodo(
        db, cliente, escola_completa, monkeypatch):
    eid, a, placar = _matific_vinculado(db, escola_completa, monkeypatch)
    placar.excecao_ss = RuntimeError("falha simulada")
    cliente.post(f"{API}/escolas/{eid}/sync/agora?plataforma=matific&inicio=2026-09-01&fim=2026-09-30")
    placar.excecao_ss = None
    r = cliente.post(f"{API}/escolas/{eid}/sync/agora?plataforma=matific&inicio=2026-10-01&fim=2026-10-15")
    assert r.status_code == 200, r.text
    assert r.json()[0]["periodo"] == {"inicio": "2026-10-01", "fim": "2026-10-15"}
    db.expire_all()
    assert placar.filtros[-1] == "start_date=2026-10-01&end_date=2026-10-15"
    assert execucoes(db, eid, "matific")[-1].parametros == {
        "matific_start_date": "2026-10-01", "matific_end_date": "2026-10-15"}
    assert any(d.startswith("2026-10-1") for d in _datas(db, a.id))


# ===========================================================================
# 6. PERÍODO DE 1 DIA nos três modos de MATIFIC_END_DATE
# ===========================================================================
def test_um_dia_com_semantica_desconhecida_e_recusado_na_rota(
        db, cliente, escola_completa, monkeypatch):
    eid, _a, placar = _matific_vinculado(db, escola_completa, monkeypatch)
    assert settings.MATIFIC_END_DATE == "desconhecida"
    r = cliente.post(f"{API}/escolas/{eid}/sync/agora?plataforma=matific&inicio=2026-10-21&fim=2026-10-21")
    assert r.status_code == 400
    assert "ainda não foi confirmada" in r.json()["detail"]
    assert "pelo menos 2 dias" in r.json()["detail"]
    assert execucoes(db, eid, "matific") == [] and placar.filtros == []
    # Sem plataforma (todas): o Matific está entre elas — também recusa.
    assert cliente.post(f"{API}/escolas/{eid}/sync/agora?inicio=2026-10-21&fim=2026-10-21"
                        ).status_code == 400


def test_um_dia_desconhecida_na_fila_nao_vira_erro_interno(db, escola_completa, monkeypatch):
    """Execução antiga na fila com início = fim (ou criada por fora da rota): o
    conector recusa com código próprio, sem 400 interno nem retentativa."""
    eid, _a, placar = _matific_vinculado(db, escola_completa, monkeypatch)
    ex, _ = rodar(db, eid, "matific", parametros={"matific_start_date": "2026-10-21",
                                                   "matific_end_date": "2026-10-21"})
    assert ex.status == "erro" and "pelo menos 2 dias" in ex.erro_resumo
    assert "periodo_invalido" in alertas_abertos(db, eid, "matific")
    assert placar.filtros == []


def test_dois_dias_com_semantica_desconhecida_nao_muda(db, cliente, escola_completa, monkeypatch):
    eid, a, placar = _matific_vinculado(db, escola_completa, monkeypatch)
    r = cliente.post(f"{API}/escolas/{eid}/sync/agora?plataforma=matific&inicio=2026-10-20&fim=2026-10-21")
    assert r.status_code == 200
    db.expire_all()
    assert placar.filtros[-1] == "start_date=2026-10-20&end_date=2026-10-21"
    assert execucoes(db, eid, "matific")[0].status == "concluida"
    assert _datas(db, a.id)[-1] == "2026-10-20"      # o de sempre: véspera do fim


@pytest.mark.parametrize("modo,end_date", [("inclusiva", "2026-10-21"),
                                           ("exclusiva", "2026-10-22")])
def test_um_dia_com_semantica_confirmada_conclui_com_retrato_no_dia(
        db, cliente, escola_completa, monkeypatch, modo, end_date):
    monkeypatch.setattr(settings, "MATIFIC_END_DATE", modo)
    eid, a, placar = _matific_vinculado(db, escola_completa, monkeypatch)
    st = cliente.get(f"{API}/escolas/{eid}/sync/status").json()
    assert next(p for p in st["plataformas"]
                if p["plataforma"] == "matific")["periodo_um_dia_permitido"] is True
    r = cliente.post(f"{API}/escolas/{eid}/sync/agora?plataforma=matific&inicio=2026-10-21&fim=2026-10-21")
    assert r.status_code == 200, r.text
    db.expire_all()
    ex = execucoes(db, eid, "matific")[0]
    assert ex.status == "concluida", ex.erro_resumo
    assert placar.filtros[-1] == f"start_date=2026-10-21&end_date={end_date}"
    assert "2026-10-21" in _datas(db, a.id)
    assert [e.id for e in execucoes(db, eid, "matific") if e.status == "fila"] == []


@pytest.mark.parametrize("modo,end_date,retrato", [
    ("desconhecida", "2026-10-21", "2026-10-20"),
    ("inclusiva", "2026-10-21", "2026-10-21"),
    ("exclusiva", "2026-10-22", "2026-10-21")])
def test_semantica_consistente_entre_sync_e_placar_ao_vivo(
        db, escola_completa, monkeypatch, modo, end_date, retrato):
    monkeypatch.setattr(settings, "MATIFIC_END_DATE", modo)
    eid, a, placar = _matific_vinculado(db, escola_completa, monkeypatch)
    rodar(db, eid, "matific", parametros={"matific_start_date": "2026-10-20",
                                          "matific_end_date": "2026-10-21"})
    assert placar.filtros[-1] == f"start_date=2026-10-20&end_date={end_date}"
    assert _datas(db, a.id)[-1] == retrato
    filtro, _r, di, df = aovivo.mapa_filtro("personalizado", "2026-10-20", "2026-10-21",
                                            2026, date(2026, 10, 22))
    assert filtro == f"start_date=2026-10-20&end_date={end_date}"
    assert (di, df) == (date(2026, 10, 20), date(2026, 10, 21))   # o rótulo não muda
    filtro_hoje, *_ = aovivo.mapa_filtro("hoje", None, None, 2026, date(2026, 10, 22))
    fim_hoje = "2026-10-23" if modo == "exclusiva" else "2026-10-22"
    assert filtro_hoje == f"start_date=2026-10-22&end_date={fim_hoje}"


def test_valor_estranho_de_matific_end_date_vale_desconhecida(monkeypatch):
    from app.sync.connectors import matific
    monkeypatch.setattr(settings, "MATIFIC_END_DATE", "sim")
    assert matific.semantica_fim() == "desconhecida"
    assert matific.periodo_um_dia_permitido() is False
