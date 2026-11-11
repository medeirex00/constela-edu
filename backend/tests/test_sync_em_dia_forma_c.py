"""Regra do "em dia" na FORMA C (decisão 1 da revisão pré-implantação, Etapa 3).

Uma execução 'sem_atualizacao' por correspondência pendente só conta como "em
dia" (fecha o alerta crítico 'desatualizada' e serve de referência da regra única
de obsolescência) se a coleta CONFERIU ao menos uma conta já vinculada a um aluno
da escola: aplicou dado novo, comparou e achou igual, ou reteve um total menor do
Matific. Tudo em revisão e nenhuma conta conferida = motivo próprio
'tudo_em_revisao' (a assinatura de credencial de outra escola, de casamento
quebrado ou da 1ª coleta sem vínculo) e NÃO é em dia.

O resto da decisão 1 não muda: nada mudou, total retido e linhas descartadas
contam; 'parcial' por turma/lote/aluno que falhou não conta; 'parcial' só por
linhas descartadas conta.

Dados 100% fictícios; conectores reais com navegador falso; sem rede. Os mesmos
cenários rodam no PostgreSQL local em ``test_sync_em_dia_forma_c_pg.py``.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.security import hash_senha
from app.models import Turma, Usuario
from app.models.escola import Escola
from app.models.sincronizacao import SincronizacaoAlerta, SincronizacaoConfig, SincronizacaoExecucao
from app.services import politica_sync
from app.sync import service
from tests._sync_nucleo_fakes import (
    API, NavElefante, PlacarFake, aluno_el, alertas_abertos, credencial, execucoes, ident,
    instalar, livro, novo_aluno, rodar, vincular)
from tests._ano_letivo import no_ano_de_hoje

K = "3 ANO A (300396804)"
CID_A, CID_B, CID_OUTRA = 511434, 600001, 777001


def _agora():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _alerta(db, eid, tipo, plataforma="elefante"):
    return db.execute(select(SincronizacaoAlerta).where(
        SincronizacaoAlerta.escola_id == eid, SincronizacaoAlerta.plataforma == plataforma,
        SincronizacaoAlerta.tipo == tipo,
        SincronizacaoAlerta.resolvido.is_(False))).scalars().first()


def _agenda_diaria(db, eid, plataforma, desde_dias):
    """Agenda diária ativa desde ``desde_dias`` (a referência da obsolescência
    quando nunca houve coleta em dia). Limite da diária: 2 dias."""
    cfg = db.execute(select(SincronizacaoConfig).where(
        SincronizacaoConfig.escola_id == eid,
        SincronizacaoConfig.plataforma == plataforma)).scalars().first()
    if cfg is None:
        cfg = SincronizacaoConfig(escola_id=eid, plataforma=plataforma, ativo=True,
                                  cadencia="diaria", hora_local="03:00")
        db.add(cfg)
        db.commit()
    cfg.updated_at = _agora() - timedelta(days=desde_dias)
    db.commit()
    return cfg


def _recuar(db, eid, plataforma, dias):
    """O tempo passa: as execuções já feitas ficam ``dias`` mais antigas."""
    for ex in execucoes(db, eid, plataforma):
        for campo in ("finalizada_em", "iniciada_em", "created_at"):
            valor = getattr(ex, campo)
            if valor is not None:
                setattr(ex, campo, valor - timedelta(days=dias))
    db.commit()


def _da_escola(ec):
    """O Elefante da escola: as três crianças da Lista Piloto, cada uma com um livro."""
    a, b, c = ec["alunos"]
    return {CID_A: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
        aluno_el(9100001, a.nome, [livro("Livro Ficticio Um")]),
        aluno_el(9100002, b.nome, [livro("Livro Ficticio Dois", "E", "2026-09-05T10:00:00")]),
        aluno_el(9100003, c.nome, [livro("Livro Ficticio Tres", "D", "2026-09-06T10:00:00")])]}}


def _de_outra_escola():
    """O que uma credencial de OUTRA escola devolve: mesma série e rótulo de turma,
    outras crianças (nenhum studentId vinculado aqui, nenhum nome da Lista Piloto)."""
    return {CID_OUTRA: {"nome": "3 ANO A TARDE ANUAL", "escola": "OUTRA ESCOLA FICTICIA",
                        "alunos": [
        aluno_el(9800001, "Crianca Ficticia Outra Escola Um", [livro("Livro Ficticio Cinco")]),
        aluno_el(9800002, "Crianca Ficticia Outra Escola Dois",
                 [livro("Livro Ficticio Seis", "E", "2026-09-08T10:00:00")])]}}


def _escola_sem_alunos(db):
    """Escola com admin e turma, SEM nenhuma ficha (Lista Piloto não importada)."""
    escola = Escola(nome="ESCOLA FICTICIA SEM ALUNOS", ano_letivo_ativo=2026)
    db.add(escola)
    db.flush()
    db.add(Usuario(escola_id=escola.id, nome="Admin", email="admin-sem-alunos@teste.local",
                   senha_hash=hash_senha("s3nh4"), cargo="admin"))
    db.add(Turma(escola_id=escola.id, nome="3º Ano A", ano_escolar="3º Ano", ano_letivo=2026))
    db.commit()
    return escola.id


def _status_plataforma(cliente, eid, plataforma="elefante"):
    r = cliente.get(f"{API}/escolas/{eid}/sync/status")
    assert r.status_code == 200, r.text[:300]
    return next(p for p in r.json()["plataformas"] if p["plataforma"] == plataforma)


# ---------------------------------------------------------------------------
# 1. Escola sem nenhum aluno vinculado: 1ª coleta, tudo em revisão
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("cenario", ["fichas_sem_vinculo", "sem_fichas"])
def test_primeira_coleta_tudo_em_revisao_nao_e_em_dia_e_desatualizada_abre_depois(
        relogio_no_ano_letivo, db, escola_completa, monkeypatch, cenario):
    """Sem nenhuma conta vinculada e nenhum nome que case: 'tudo_em_revisao', o
    alerta 'correspondencia_pendente' (com o texto da 1ª coleta) e NENHUM "em dia".
    Dentro da cadência o 'desatualizada' não abre; passada a cadência, com a coleta
    diária igual, ele abre (no 5e388b6 a coleta contava como em dia e não abria)."""
    eid = (escola_completa["escola"].id if cenario == "fichas_sem_vinculo"
           else _escola_sem_alunos(db))
    politica_sync.definir(db, eid, "bloquear")
    db.commit()
    credencial(db, eid, "elefante")
    cfg = _agenda_diaria(db, eid, "elefante", 1)          # dentro do limite (2 dias)
    instalar(monkeypatch, nav_elefante=NavElefante(_de_outra_escola()))

    ex1, erro = rodar(db, eid, "elefante")
    assert erro is None
    # Comportamento primeiro (no 5e388b6 esta coleta já contava como "em dia").
    assert service.ultimo_em_dia_em(db, eid, "elefante") is None
    assert (ex1.status, ex1.motivo) == ("sem_atualizacao", "tudo_em_revisao")
    assert ex1.qtd_alunos == 0 and ex1.qtd_em_revisao >= 2
    assert service.ultimo_sucesso_em(db, eid, "elefante") is None
    assert service.ultima_verificacao_em(db, eid, "elefante") is None
    abertos = alertas_abertos(db, eid, "elefante")
    assert "correspondencia_pendente" in abertos and "desatualizada" not in abertos, abertos
    mensagem = _alerta(db, eid, "correspondencia_pendente").mensagem
    assert "nenhuma conta da escola conferida" in mensagem
    assert "não conta como coleta em dia" in mensagem
    assert "ainda não tem nenhuma conta vinculada" in mensagem

    # Passa a cadência: a agenda está ativa há 3 dias e a coleta de hoje é igual.
    _agenda_diaria(db, eid, "elefante", 3)
    ex2, _ = rodar(db, eid, "elefante")
    assert (ex2.status, ex2.motivo) == ("sem_atualizacao", "tudo_em_revisao")
    db.refresh(cfg)
    assert service.esta_desatualizada(db, cfg)
    desat = _alerta(db, eid, "desatualizada")
    assert desat is not None and desat.severidade == "critico"
    assert "correspondencia_pendente" in alertas_abertos(db, eid, "elefante")


# ---------------------------------------------------------------------------
# 2. Escola com vinculados, mas TODOS os alunos da coleta em revisão
# ---------------------------------------------------------------------------
def test_vinculados_e_coleta_toda_em_revisao_nao_e_em_dia(
        relogio_no_ano_letivo, db, cliente, escola_completa, monkeypatch):
    """A escola já tem as três contas vinculadas; a credencial passa a ver outra
    escola (outras crianças, mesmo rótulo de turma). Nenhuma conta da escola foi
    conferida: 'tudo_em_revisao', não em dia — o 'desatualizada' abre contra a
    última coleta boa (3 dias atrás) e o texto aponta o acesso de outra escola."""
    eid = escola_completa["escola"].id
    politica_sync.definir(db, eid, "bloquear")
    db.commit()
    credencial(db, eid, "elefante")
    nav = NavElefante(_da_escola(escola_completa))
    instalar(monkeypatch, nav_elefante=nav)
    ex1, _ = rodar(db, eid, "elefante")
    assert ex1.status == "concluida" and ex1.qtd_alunos == 3
    assert [ident(db, eid, "elefante", sid) for sid in (9100001, 9100002, 9100003)] == [
        al.id for al in escola_completa["alunos"]]            # as 3 contas vinculadas
    _recuar(db, eid, "elefante", 3)
    cfg = _agenda_diaria(db, eid, "elefante", 10)
    referencia = service.ultimo_em_dia_em(db, eid, "elefante")
    assert referencia is not None

    nav.turmas = _de_outra_escola()                       # credencial de outra escola
    ex2, erro = rodar(db, eid, "elefante")
    assert erro is None
    # Comportamento primeiro (no 5e388b6 a referência andava e o alerta não abria).
    assert service.ultimo_em_dia_em(db, eid, "elefante") == referencia   # não andou
    db.refresh(cfg)
    assert service.esta_desatualizada(db, cfg)
    assert _alerta(db, eid, "desatualizada") is not None
    assert (ex2.status, ex2.motivo) == ("sem_atualizacao", "tudo_em_revisao")
    assert ex2.qtd_alunos == 0 and ex2.qtd_em_revisao >= 2
    mensagem = _alerta(db, eid, "correspondencia_pendente").mensagem
    assert "A escola tem 3 conta(s) vinculada(s)" in mensagem
    assert "outra escola" in mensagem
    p = _status_plataforma(cliente, eid)
    assert p["ultimo_status"] == "sem_atualizacao" and p["ultimo_motivo"] == "tudo_em_revisao"
    assert p["desatualizada"] is True
    assert p["ultima_tentativa"]["motivo"] == "tudo_em_revisao"


def test_matific_credencial_de_outra_escola_tudo_em_revisao(
        relogio_no_ano_letivo, db, escola_completa, monkeypatch):
    """O mesmo no Matific: as três contas vinculadas por uuid somem e vêm outras
    (uuids e nomes desconhecidos). 'tudo_em_revisao', não em dia; o aviso
    'contas_ausentes' também abre (as vinculadas não vieram no Placar)."""
    eid = escola_completa["escola"].id
    a, b, c = escola_completa["alunos"]
    politica_sync.definir(db, eid, "bloquear")
    credencial(db, eid, "matific")
    for al, u in ((a, "u-a"), (b, "u-b"), (c, "u-c")):
        vincular(db, eid, al.id, "matific", u)
    db.commit()
    placar = PlacarFake()
    placar.linhas = [("u-a", a.nome, K, 40, 10), ("u-b", b.nome, K, 30, 8),
                     ("u-c", c.nome, K, 20, 5)]
    instalar(monkeypatch, placar=placar)
    ex1, _ = rodar(db, eid, "matific")
    assert ex1.status == "concluida"
    _recuar(db, eid, "matific", 3)
    cfg = _agenda_diaria(db, eid, "matific", 10)

    placar.linhas = [("u-x1", "Crianca Ficticia Outra Escola Um", K, 55, 12),
                     ("u-x2", "Crianca Ficticia Outra Escola Dois", K, 66, 13)]
    ex2, erro = rodar(db, eid, "matific")
    assert erro is None
    db.refresh(cfg)
    assert service.esta_desatualizada(db, cfg)
    assert (ex2.status, ex2.motivo) == ("sem_atualizacao", "tudo_em_revisao")
    abertos = alertas_abertos(db, eid, "matific")
    assert {"correspondencia_pendente", "contas_ausentes", "desatualizada"} <= set(abertos), abertos
    assert "A escola tem 3 conta(s) vinculada(s)" in _alerta(
        db, eid, "correspondencia_pendente", "matific").mensagem


# ---------------------------------------------------------------------------
# 3. Mistura: vinculados conferidos sem mudança + pendências → em dia
# ---------------------------------------------------------------------------
def test_mistura_vinculados_conferidos_e_pendencias_e_em_dia_com_alerta(
        relogio_no_ano_letivo, db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    politica_sync.definir(db, eid, "bloquear")
    db.commit()
    credencial(db, eid, "elefante")
    origem = _da_escola(escola_completa)
    nav = NavElefante(origem)
    instalar(monkeypatch, nav_elefante=nav)
    ex1, _ = rodar(db, eid, "elefante")
    assert ex1.status == "concluida"
    _recuar(db, eid, "elefante", 3)
    cfg = _agenda_diaria(db, eid, "elefante", 10)

    origem[CID_A]["alunos"].append(aluno_el(9300001, "Crianca Ficticia Fora Da Lista",
                                            [livro("Livro Ficticio Quatro")]))
    ex2, _ = rodar(db, eid, "elefante")
    assert (ex2.status, ex2.motivo) == ("sem_atualizacao", "correspondencia_pendente")
    assert ex2.qtd_alunos == 0
    assert service.ultimo_em_dia_em(db, eid, "elefante") == ex2.finalizada_em
    db.refresh(cfg)
    assert not service.esta_desatualizada(db, cfg)
    abertos = alertas_abertos(db, eid, "elefante")
    assert "correspondencia_pendente" in abertos and "desatualizada" not in abertos, abertos
    mensagem = _alerta(db, eid, "correspondencia_pendente").mensagem
    assert mensagem.startswith("Nenhum dado novo aplicado:")
    assert "nenhuma conta da escola conferida" not in mensagem


@no_ano_de_hoje
def test_matific_queda_retida_com_pendencia_conta_como_conferida(relogio_no_ano_letivo, db,
                                                                 escola_completa, monkeypatch):
    """Decisão registrada: o total menor RETIDO só acontece para uuid já vinculado
    NESTA escola, comparado com o retrato gravado — a coleta conferiu a escola.
    Queda retida + pendência é 'correspondencia_pendente' (em dia), com os alertas
    'queda_matific' e 'correspondencia_pendente'."""
    eid = escola_completa["escola"].id
    a, b, c = escola_completa["alunos"]
    politica_sync.definir(db, eid, "bloquear")
    credencial(db, eid, "matific")
    for al, u in ((a, "u-a"), (b, "u-b"), (c, "u-c")):
        vincular(db, eid, al.id, "matific", u)
    db.commit()
    placar = PlacarFake()
    placar.linhas = [("u-a", a.nome, K, 40, 10), ("u-b", b.nome, K, 30, 8),
                     ("u-c", c.nome, K, 20, 5)]
    instalar(monkeypatch, placar=placar)
    ex1, _ = rodar(db, eid, "matific")
    assert ex1.status == "concluida"
    _recuar(db, eid, "matific", 3)
    _agenda_diaria(db, eid, "matific", 10)

    placar.linhas = [("u-a", a.nome, K, 39, 9), ("u-b", b.nome, K, 29, 7),
                     ("u-c", c.nome, K, 19, 4),
                     ("u-x1", "Crianca Ficticia Fora Da Lista", K, 5, 2)]
    ex2, _ = rodar(db, eid, "matific")
    assert (ex2.status, ex2.motivo) == ("sem_atualizacao", "correspondencia_pendente")
    assert service.ultimo_em_dia_em(db, eid, "matific") == ex2.finalizada_em
    abertos = alertas_abertos(db, eid, "matific")
    assert {"queda_matific", "correspondencia_pendente"} <= set(abertos), abertos
    assert "desatualizada" not in abertos


# ---------------------------------------------------------------------------
# 4. Falha parcial por turma / lote / aluno → não em dia (não mudou)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("falha", ["turma", "lote", "aluno"])
def test_parcial_por_unidade_que_falhou_nao_e_em_dia(db, escola_completa, monkeypatch, falha):
    ec = escola_completa
    eid = ec["escola"].id
    a = ec["alunos"][0]
    t2 = Turma(escola_id=eid, nome="4º Ano B", ano_escolar="4º Ano", ano_letivo=2026)
    db.add(t2)
    db.commit()
    d = novo_aluno(db, eid, t2, "Crianca Ficticia Quarto Ano")
    db.commit()
    credencial(db, eid, "elefante")
    cfg = _agenda_diaria(db, eid, "elefante", 5)
    turmas = {CID_A: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
        aluno_el(9100001, a.nome, [livro("Livro Ficticio Um")])]},
        CID_B: {"nome": "4 ANO B TARDE ANUAL", "alunos": [
            aluno_el(9200001, d.nome, [livro("Livro Ficticio Quatro")])]}}
    falhas = {"turma": {"erro_turma": {CID_B: 500}},
              "lote": {"excecao_lote": {CID_B}},
              "aluno": {"status_aluno": {9200001: 500}}}[falha]
    instalar(monkeypatch, nav_elefante=NavElefante(turmas, **falhas))
    ex, erro = rodar(db, eid, "elefante")
    assert erro is None
    assert (ex.status, ex.motivo) == ("parcial", "coleta_parcial"), (ex.status, ex.motivo)
    assert (ex.qtd_falhas or 0) >= 1
    assert service.ultimo_em_dia_em(db, eid, "elefante") is None
    db.refresh(cfg)
    assert service.esta_desatualizada(db, cfg)
    assert _alerta(db, eid, "desatualizada") is not None
    assert "coleta_parcial" in alertas_abertos(db, eid, "elefante")


# ---------------------------------------------------------------------------
# 5. Parcial só por linhas descartadas → em dia (não mudou)
# ---------------------------------------------------------------------------
def test_parcial_so_por_linhas_descartadas_e_em_dia(db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "elefante")
    cfg = _agenda_diaria(db, eid, "elefante", 5)
    origem = _da_escola(escola_completa)
    origem[CID_A]["alunos"][0]["livros"].append(
        {"bookTitle": "Livro Ficticio Sem Data", "levelName": "D", "lastReadWhen": None,
         "totalTimeSpent": 60})
    origem[CID_A]["alunos"][0]["total"] = 2
    instalar(monkeypatch, nav_elefante=NavElefante(origem))
    ex, _ = rodar(db, eid, "elefante")
    assert (ex.status, ex.motivo) == ("parcial", "linhas_descartadas")
    assert service.ultimo_em_dia_em(db, eid, "elefante") == ex.finalizada_em
    db.refresh(cfg)
    assert not service.esta_desatualizada(db, cfg)
    abertos = alertas_abertos(db, eid, "elefante")
    assert "desatualizada" not in abertos and "coleta_parcial" in abertos, abertos


# ---------------------------------------------------------------------------
# 6. Nada mudou → em dia (não mudou)
# ---------------------------------------------------------------------------
def test_nada_mudou_e_em_dia(db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "elefante")
    instalar(monkeypatch, nav_elefante=NavElefante(_da_escola(escola_completa)))
    ex1, _ = rodar(db, eid, "elefante")
    assert ex1.status == "concluida"
    _recuar(db, eid, "elefante", 3)
    cfg = _agenda_diaria(db, eid, "elefante", 10)
    ex2, _ = rodar(db, eid, "elefante")
    assert (ex2.status, ex2.motivo) == ("sem_atualizacao", "nada_mudou")
    assert service.ultimo_em_dia_em(db, eid, "elefante") == ex2.finalizada_em
    db.refresh(cfg)
    assert not service.esta_desatualizada(db, cfg)
    assert "desatualizada" not in alertas_abertos(db, eid, "elefante")


# ---------------------------------------------------------------------------
# 7. Regra ÚNICA: /status, painel global e varredura do agendador decidem igual
# ---------------------------------------------------------------------------
def _fechar_desatualizada(db, eid):
    for al in db.execute(select(SincronizacaoAlerta).where(
            SincronizacaoAlerta.escola_id == eid,
            SincronizacaoAlerta.tipo == "desatualizada")).scalars():
        al.resolvido = True
    db.commit()


def _fontes(db, cliente, cliente_global, eid, cfg):
    """O que cada consumidor da regra única diz sobre a integração. A varredura do
    agendador roda PRIMEIRO, com o alerta fechado à mão: o alerta aberto depois
    dela é obra dela (o /status também o abriria)."""
    _fechar_desatualizada(db, eid)
    db.expire_all()
    varredura = service.verificar_obsolescencia(db)
    alerta_da_varredura = _alerta(db, eid, "desatualizada") is not None
    status = _status_plataforma(cliente, eid)["desatualizada"]
    painel = cliente_global.get(f"{API}/sync/dashboard").json()["escolas_desatualizadas"]
    db.expire_all()
    return {
        "varredura_agendador": varredura,
        "alerta_da_varredura": alerta_da_varredura,
        "status": status,
        "painel_global": painel,
        "escolas_desatualizadas": eid in service.escolas_desatualizadas(db),
        "esta_desatualizada": service.esta_desatualizada(db, db.get(SincronizacaoConfig, cfg.id)),
    }


def test_regra_unica_status_painel_e_agendador_seguem_a_forma_c(
        relogio_no_ano_letivo, db, cliente, cliente_global, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    a = escola_completa["alunos"][0]
    politica_sync.definir(db, eid, "bloquear")
    db.commit()
    credencial(db, eid, "elefante")
    cfg = _agenda_diaria(db, eid, "elefante", 3)
    origem = _de_outra_escola()
    nav = NavElefante(origem)
    instalar(monkeypatch, nav_elefante=nav)

    # (a) tudo em revisão, passada a cadência: TODOS dizem desatualizada.
    ex1, _ = rodar(db, eid, "elefante")
    fontes = _fontes(db, cliente, cliente_global, eid, cfg)
    assert fontes == {"varredura_agendador": 1, "alerta_da_varredura": True, "status": True,
                      "painel_global": 1, "escolas_desatualizadas": True,
                      "esta_desatualizada": True}, fontes
    assert ex1.motivo == "tudo_em_revisao"

    # (b) uma criança da escola entra (casa pelo nome e aplica) — em dia — e, três
    # dias depois, a coleta só a CONFERE sem mudança, com a pendência ainda lá.
    origem[CID_OUTRA]["alunos"].append(aluno_el(9100001, a.nome, [livro("Livro Ficticio Um")]))
    ex2, _ = rodar(db, eid, "elefante")
    assert ex2.status == "concluida"
    _recuar(db, eid, "elefante", 3)
    ex3, _ = rodar(db, eid, "elefante")
    assert (ex3.status, ex3.motivo) == ("sem_atualizacao", "correspondencia_pendente")
    fontes = _fontes(db, cliente, cliente_global, eid, cfg)
    assert fontes == {"varredura_agendador": 0, "alerta_da_varredura": False, "status": False,
                      "painel_global": 0, "escolas_desatualizadas": False,
                      "esta_desatualizada": False}, fontes
    assert _alerta(db, eid, "desatualizada") is None


# ---------------------------------------------------------------------------
# 8. Unidade: decidir_status, a apuração e o filtro do "em dia"
# ---------------------------------------------------------------------------
def test_decidir_status_forma_c():
    ap = service._Apuracao(linhas=3, em_revisao=2)
    assert service.decidir_status(ap) == ("sem_atualizacao", "tudo_em_revisao")
    ap.conferidos_sem_mudanca = 1
    assert service.decidir_status(ap) == ("sem_atualizacao", "correspondencia_pendente")
    ap.conferidos_sem_mudanca, ap.retidos_queda = 0, 1
    assert service.decidir_status(ap) == ("sem_atualizacao", "correspondencia_pendente")
    # Só linhas sem vínculo (nenhuma na fila) e nada conferido: o mesmo motivo.
    ap = service._Apuracao(linhas=2, ignorados={"x", "y"}, descartes={"sem_vinculo": 2})
    assert service.decidir_status(ap) == ("sem_atualizacao", "tudo_em_revisao")
    # O resto da regra não muda.
    assert service.decidir_status(service._Apuracao(linhas=3)) == ("sem_atualizacao",
                                                                   "nada_mudou")
    assert service.decidir_status(service._Apuracao(linhas=3, retidos_queda=1)) == (
        "sem_atualizacao", "queda_retida")


def test_apuracao_soma_os_conferidos_sem_mudanca():
    ap = service._Apuracao()
    ap.somar({"qtd_alunos": 3, "alunos_aplicados_ids": [], "linhas": 4, "em_revisao": 1,
              "conferidos_sem_mudanca": 3})
    assert ap.conferidos_sem_mudanca == 3 and ap.conferiu_a_escola
    # Resultado sem a chave: a mesma conta (resolvidos − aplicados).
    ap = service._Apuracao()
    ap.somar({"qtd_alunos": 2, "alunos_aplicados_ids": [7], "linhas": 2})
    assert ap.conferidos_sem_mudanca == 1
    # Arquivo vazio não confere nada.
    ap = service._Apuracao()
    ap.somar({"qtd_alunos": 0, "alunos_aplicados_ids": [], "sem_dados": True, "linhas": 0})
    assert ap.conferidos_sem_mudanca == 0 and not ap.conferiu_a_escola


@pytest.mark.parametrize("motivo, em_dia", [
    ("tudo_em_revisao", False), ("correspondencia_pendente", True), ("nada_mudou", True),
    ("queda_retida", True), ("linhas_descartadas", True), (None, True)])
def test_filtro_em_dia_por_motivo_do_sem_atualizacao(db, escola_completa, motivo, em_dia):
    """Motivo NULL (execução anterior à 0039) não é 'tudo_em_revisao'."""
    eid = escola_completa["escola"].id
    fim = _agora() - timedelta(hours=1)
    db.add(SincronizacaoExecucao(escola_id=eid, plataforma="elefante", origem="manual",
                                 status="sem_atualizacao", motivo=motivo, parametros={},
                                 iniciada_em=fim, finalizada_em=fim))
    db.commit()
    assert (service.ultimo_em_dia_em(db, eid, "elefante") is not None) is em_dia
