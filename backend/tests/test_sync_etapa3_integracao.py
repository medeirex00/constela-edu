"""As três frentes da Etapa 3 JUNTAS (ramo de teste ``rev/etapa3``): forma C do
"em dia" (``rev/em-dia-c``), proteção contra dados de outra escola
(``rev/escola-cruzada``) e métricas de sincronização (``rev/metricas-sync``).

Cada frente tem os próprios testes; aqui ficam só os cenários em que o
comportamento de uma depende da outra:

  1. credencial trocada pela de outra escola da plataforma: a escola externa
     recusa (``escola_externa_trocada``), a referência do "em dia" não anda, o
     ``desatualizada`` abre depois da cadência e as métricas mostram os dois;
  2. contas já efetivas em OUTRA escola do Constela (mesma escola externa, com o
     vínculo explícito — sem ele vale a recusa da decisão D8): cada
     linha vai para a revisão ``identidade_de_outra_escola`` — a coleta não
     conferiu nenhuma conta da escola, então é ``tudo_em_revisao`` (não em dia);
     depois que o gestor confirma uma, a coleta volta a ficar em dia com o alerta
     crítico ainda aberto para as que faltam;
  3. conta que enxerga duas escolas, sem vínculo: ``conta_multiescola`` nunca é
     "em dia" e aparece nas métricas com o próprio código.

Conectores reais com navegador falso; dados 100% fictícios; sem rede.
"""
from sqlalchemy import select

from app.models.academico import RevisaoIdentidade
from app.models.plataformas import SnapshotMatific
from app.services import politica_sync
from app.sync import escola_externa, service, vault
from tests._sync_nucleo_fakes import (
    API, SCHOOL_UUID, aluno_el, alertas_abertos, contagens, credencial, livro, rodar,
    snap_atual, vincular)
from tests.test_sync_em_dia_forma_c import _agenda_diaria, _recuar
from tests.test_sync_escola_cruzada import (
    ESC_A, ESC_B, NOME_A, NOME_B, NavEl, NavMt, _alerta, _nova_escola, _placar,
    instalar_navs)
from tests.test_sync_metricas import _amostra_global, _amostras, _coletor, _v

CID_ESCOLA, CID_OUTRA = 511434, 777001
FIN = "sync_execucoes_finalizadas_total"
ABERTOS = "sync_alertas_abertos"


def _turmas_da_escola(ec):
    a, b, c = ec["alunos"]
    return {CID_ESCOLA: {"nome": "3 ANO A TARDE ANUAL", "escola": NOME_A, "alunos": [
        aluno_el(9100001, a.nome, [livro("Livro Ficticio Um")]),
        aluno_el(9100002, b.nome, [livro("Livro Ficticio Dois", "E", "2026-09-05T10:00:00")]),
        aluno_el(9100003, c.nome, [livro("Livro Ficticio Tres", "D", "2026-09-06T10:00:00")])]}}


def _turmas_de_outra_escola():
    return {CID_OUTRA: {"nome": "3 ANO A TARDE ANUAL", "escola": NOME_B, "alunos": [
        aluno_el(9800001, "Crianca Ficticia Outra Escola Um", [livro("Livro Ficticio Cinco")]),
        aluno_el(9800002, "Crianca Ficticia Outra Escola Dois",
                 [livro("Livro Ficticio Seis", "E", "2026-09-08T10:00:00")])]}}


def _alertas_no_coletor(db, eid, plataforma):
    """{(tipo, severidade): n} do gauge ``sync_alertas_abertos`` lido do banco."""
    saida = {}
    for (nome, rotulos), valor in _amostras(_coletor(db)).items():
        r = dict(rotulos)
        if nome == ABERTOS and r["escola_id"] == str(eid) and r["plataforma"] == plataforma:
            saida[(r["tipo"], r["severidade"])] = valor
    return saida


# ---------------------------------------------------------------------------
# 1. Credencial trocada pela de outra escola da PLATAFORMA (Elefante)
# ---------------------------------------------------------------------------
def test_credencial_trocada_e_recusada_nao_anda_o_em_dia_e_aparece_nas_metricas(
        db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    politica_sync.definir(db, eid, "bloquear")
    db.commit()
    credencial(db, eid, "elefante")
    nav = NavEl(_turmas_da_escola(escola_completa), ativas=((ESC_A, NOME_A),),
                escola_da_turma={CID_ESCOLA: ESC_A})
    instalar_navs(monkeypatch, elefante=nav)
    ex1, erro = rodar(db, eid, "elefante")
    assert erro is None and ex1.status == "concluida" and ex1.qtd_alunos == 3
    assert escola_externa.obter(db, eid, "elefante")["id"] == str(ESC_A)   # aprendido
    _recuar(db, eid, "elefante", 3)
    cfg = _agenda_diaria(db, eid, "elefante", 10)
    referencia = service.ultimo_em_dia_em(db, eid, "elefante")
    assert referencia is not None

    # A credencial passa a ser a de OUTRA escola da plataforma (outras crianças).
    trocada = _amostra_global(FIN, plataforma="elefante", status="erro",
                              motivo="escola_externa_trocada")
    nav.turmas = _turmas_de_outra_escola()
    nav.ativas = [(ESC_B, NOME_B)]
    nav.escola_da_turma = {CID_OUTRA: ESC_B}
    nav.course_reports.clear()
    antes = contagens(db, eid)
    ex2, erro = rodar(db, eid, "elefante")
    assert erro is None
    # Frente escola: recusa ANTES de pedir dado de turma; nada aplicado.
    assert (ex2.status, ex2.motivo) == ("erro", "escola_externa_trocada")
    assert contagens(db, eid) == antes and nav.course_reports == []
    assert db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == eid)).first() is None     # nem revisão nasce
    # Frente em dia: a referência não anda e o crítico 'desatualizada' abre.
    assert service.ultimo_em_dia_em(db, eid, "elefante") == referencia
    db.refresh(cfg)
    assert service.esta_desatualizada(db, cfg)
    abertos = alertas_abertos(db, eid, "elefante")
    assert {"escola_externa_trocada", "desatualizada"} <= set(abertos), abertos
    # Frente métricas: o evento com o código próprio e os dois críticos no gauge.
    assert _amostra_global(FIN, plataforma="elefante", status="erro",
                           motivo="escola_externa_trocada") == trocada + 1
    gauge = _alertas_no_coletor(db, eid, "elefante")
    assert gauge.get(("escola_externa_trocada", "critico")) == 1
    assert gauge.get(("desatualizada", "critico")) == 1
    assert ("outro", "critico") not in gauge


# ---------------------------------------------------------------------------
# 2. Contas já efetivas em OUTRA escola do Constela (mesma escola externa)
# ---------------------------------------------------------------------------
def test_contas_de_outra_escola_do_constela_sao_tudo_em_revisao_ate_o_gestor_confirmar(
        db, escola_completa, cliente_global, monkeypatch):
    eid = escola_completa["escola"].id
    a, b, c = escola_completa["alunos"]
    outra, _t, donas = _nova_escola(db, nome="ESCOLA PRIMEIRA FICTICIA", com_alunos=[
        "Crianca Ficticia Primeira Um", "Crianca Ficticia Primeira Dois",
        "Crianca Ficticia Primeira Tres"])
    for dona, u in zip(donas, ("u-a", "u-b", "u-c")):
        vincular(db, outra.id, dona.id, "matific", u)
    # Vínculo EXPLÍCITO da escola externa (Admin Global): sem ele, a coleta em que
    # todas as contas são de outra escola é recusada antes de aplicar (decisão
    # D8, ``test_sync_escola_externa_decisoes.py``). Com ele, a escola externa já
    # foi conferida e cada conta segue para a revisão própria.
    escola_externa.salvar(db, eid, "matific", SCHOOL_UUID, origem="explicito")
    db.commit()
    antes_outra = contagens(db, outra.id)
    politica_sync.definir(db, eid, "bloquear")
    db.commit()
    credencial(db, eid, "matific")
    instalar_navs(monkeypatch, matific=NavMt(_placar(escola_completa)))
    tudo = _amostra_global(FIN, plataforma="matific", status="sem_atualizacao",
                           motivo="tudo_em_revisao")

    ex1, erro = rodar(db, eid, "matific")
    assert erro is None
    # Frente escola: as três contas vão para a revisão própria, nada aplicado.
    motivos = [r.motivo for r in db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == eid, RevisaoIdentidade.status == "pendente")).scalars()]
    assert sorted(motivos) == ["identidade_de_outra_escola"] * 3
    assert _alerta(db, eid, "identidade_de_outra_escola").severidade == "critico"
    # Frente em dia: nenhuma conta da escola conferida → 'tudo_em_revisao', não em dia.
    assert (ex1.status, ex1.motivo) == ("sem_atualizacao", "tudo_em_revisao")
    assert ex1.qtd_alunos == 0 and ex1.qtd_em_revisao == 3
    assert service.ultimo_em_dia_em(db, eid, "matific") is None
    pendente = _alerta(db, eid, "correspondencia_pendente")
    assert pendente.severidade == "warn" and "não conta como coleta em dia" in pendente.mensagem
    # Frente métricas.
    assert _amostra_global(FIN, plataforma="matific", status="sem_atualizacao",
                           motivo="tudo_em_revisao") == tudo + 1
    gauge = _alertas_no_coletor(db, eid, "matific")
    assert gauge.get(("identidade_de_outra_escola", "critico")) == 1
    assert gauge.get(("correspondencia_pendente", "warn")) == 1
    assert contagens(db, outra.id) == antes_outra                 # a outra escola intacta

    # O Admin Global confirma que a conta u-a é a da Ana daqui (conta efetiva em
    # outra escola: só ele confirma — decisão D10).
    rev_a = db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == eid, RevisaoIdentidade.id_externo == "u-a",
        RevisaoIdentidade.status == "pendente")).scalars().one()
    r = cliente_global.post(f"{API}/escolas/{eid}/importacoes/revisoes/{rev_a.id}/resolver",
                            json={"aluno_id": a.id})
    assert r.status_code == 200, r.text
    # A resolução já aplica a linha retida da u-a (o dado fica gravado na Ana).
    assert snap_atual(db, SnapshotMatific, a.id) is not None
    pendentes = _amostra_global(FIN, plataforma="matific", status="sem_atualizacao",
                                motivo="correspondencia_pendente")
    ex2, erro = rodar(db, eid, "matific")
    assert erro is None
    # A coleta seguinte CONFERE a conta da Ana (veio igual ao gravado) e as
    # outras duas continuam em revisão: correspondência pendente — em dia pela
    # forma C (≥1 conta da escola conferida), com o crítico ainda aberto.
    assert (ex2.status, ex2.motivo) == ("sem_atualizacao", "correspondencia_pendente")
    assert ex2.qtd_alunos == 0 and ex2.qtd_em_revisao == 2
    assert service.ultimo_em_dia_em(db, eid, "matific") == ex2.finalizada_em
    abertos = alertas_abertos(db, eid, "matific")
    assert {"identidade_de_outra_escola", "correspondencia_pendente"} <= set(abertos), abertos
    assert "desatualizada" not in abertos
    assert _alerta(db, eid, "identidade_de_outra_escola").mensagem.startswith("2 conta(s)")
    mensagem = _alerta(db, eid, "correspondencia_pendente").mensagem
    assert mensagem.startswith("Nenhum dado novo aplicado: 2 conta(s)"), mensagem
    assert "não conta como coleta em dia" not in mensagem
    assert _amostra_global(FIN, plataforma="matific", status="sem_atualizacao",
                           motivo="correspondencia_pendente") == pendentes + 1
    assert contagens(db, outra.id) == antes_outra


# ---------------------------------------------------------------------------
# 3. Conta que enxerga duas escolas, sem vínculo (Elefante)
# ---------------------------------------------------------------------------
def test_conta_multiescola_nunca_e_em_dia_e_aparece_nas_metricas(db, escola_completa,
                                                                  monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "elefante")
    turmas = {**_turmas_da_escola(escola_completa), **_turmas_de_outra_escola()}
    nav = NavEl(turmas, ativas=((ESC_A, NOME_A), (ESC_B, NOME_B)),
                escola_da_turma={CID_ESCOLA: ESC_A, CID_OUTRA: ESC_B})
    instalar_navs(monkeypatch, elefante=nav)
    multi = _amostra_global(FIN, plataforma="elefante", status="erro",
                            motivo="conta_multiescola")
    antes = contagens(db, eid)
    ex, erro = rodar(db, eid, "elefante")
    assert erro is None
    assert (ex.status, ex.motivo) == ("erro", "conta_multiescola")
    assert contagens(db, eid) == antes and nav.course_reports == []
    assert service.ultimo_em_dia_em(db, eid, "elefante") is None
    assert service.ultimo_sucesso_em(db, eid, "elefante") is None
    assert _amostra_global(FIN, plataforma="elefante", status="erro",
                           motivo="conta_multiescola") == multi + 1
    amostras = _amostras(_coletor(db))
    assert _v(amostras, ABERTOS, escola_id=str(eid), plataforma="elefante",
              tipo="conta_multiescola", severidade="critico") == 1
    # A credencial não é dada como válida nem como recusada (o login funcionou).
    status_cred = vault.obter_linha(db, eid, "elefante").status
    assert status_cred not in ("valida", "invalida")
    assert _v(amostras, "sync_credencial_status", escola_id=str(eid), plataforma="elefante",
              status=status_cred) == 1
