"""Forma C do "em dia": achados da revisão adversarial e95 (frente emdia).

Cada teste FALHA no 5bf01c8 (ramo antes desta correção) e passa depois:

  1. coleta POR PERÍODO do Matific em que só aparece a criança sem vínculo não
     acusa "credencial de outra escola" (continua sem contar como em dia);
  2. vinculados todos de fichas inativas (transferidas) não recebem o texto da
     "primeira coleta";
  3. queda retida de conta de ficha INATIVA não conta como "conta da escola
     conferida";
  4. só linhas sem vínculo (fila vazia) não geram o texto "0 conta(s) ... na fila
     de revisão".

O que depende da plataforma (o Placar por período omite quem não jogou?) é
suposição a confirmar com o Matific; o código não depende dela para ser seguro:
coleta por período nunca conta como em dia.

Dados 100% fictícios; conectores reais com navegador falso; sem rede. Os mesmos
cenários rodam no PostgreSQL local em ``test_sync_em_dia_forma_c_revisao_pg.py``.
"""
import re

from sqlalchemy import update

from app.models import Aluno
from app.models.plataformas import SnapshotMatific
from app.services import politica_sync
from app.sync import service
from tests._sync_nucleo_fakes import (
    NavElefante, PlacarFake, aluno_el, credencial, instalar, livro, rodar, snap_atual,
    vincular)
from tests.test_sync_em_dia_forma_c import (
    CID_A, K, _agenda_diaria, _alerta, _da_escola, _status_plataforma)


def _mensagem(db, eid, plataforma="elefante"):
    alerta = _alerta(db, eid, "correspondencia_pendente", plataforma)
    assert alerta is not None, "o alerta 'correspondencia_pendente' devia estar aberto"
    return alerta.mensagem


def _matific_com_tres_vinculados(db, escola_completa, monkeypatch, linhas_extra=()):
    eid = escola_completa["escola"].id
    a, b, c = escola_completa["alunos"]
    politica_sync.definir(db, eid, "bloquear")
    credencial(db, eid, "matific")
    for al, u in ((a, "u-a"), (b, "u-b"), (c, "u-c")):
        vincular(db, eid, al.id, "matific", u)
    db.commit()
    placar = PlacarFake()
    placar.linhas = [("u-a", a.nome, K, 40, 10), ("u-b", b.nome, K, 30, 8),
                     ("u-c", c.nome, K, 20, 5), *linhas_extra]
    instalar(monkeypatch, placar=placar)
    ex1, erro = rodar(db, eid, "matific")
    assert erro is None and ex1.status == "concluida", (ex1.status, ex1.motivo)
    return eid, placar, ex1


# ---------------------------------------------------------------------------
# 1. Coleta por período só com a criança pendente: sem falso alarme
# ---------------------------------------------------------------------------
def test_periodo_so_com_pendente_nao_acusa_credencial_de_outra_escola(
        db, cliente, escola_completa, monkeypatch):
    """Semana da premiação: no período, só a criança sem vínculo jogou. Antes, a
    execução saía 'tudo_em_revisao' e o alerta e o card mandavam conferir se o
    acesso é de outra escola. Agora é 'correspondencia_pendente' — e o período
    continua sem contar como em dia. O acumulado com conta de outra escola
    continua 'tudo_em_revisao'."""
    fora = ("u-x1", "Crianca Ficticia Fora Da Lista", K, 5, 2)
    eid, placar, _ex1 = _matific_com_tres_vinculados(db, escola_completa, monkeypatch,
                                                     linhas_extra=(fora,))
    cfg = _agenda_diaria(db, eid, "matific", 10)
    em_dia = service.ultimo_em_dia_em(db, eid, "matific")
    placar.linhas = [("u-x1", "Crianca Ficticia Fora Da Lista", K, 3, 1)]
    ex2, erro = rodar(db, eid, "matific", parametros={"matific_start_date": "2026-10-05",
                                                     "matific_end_date": "2026-10-11"})
    assert erro is None
    assert (ex2.status, ex2.motivo) == ("sem_atualizacao", "correspondencia_pendente")
    msg = _mensagem(db, eid, "matific")
    assert "outra escola" not in msg and "não conta como coleta em dia" not in msg, msg
    p = _status_plataforma(cliente, eid, "matific")
    assert p["ultimo_motivo"] == "correspondencia_pendente"
    # O período não conta como em dia (decisão 3) e não abre 'desatualizada'.
    assert service.ultimo_em_dia_em(db, eid, "matific") == em_dia
    db.refresh(cfg)
    assert not service.esta_desatualizada(db, cfg)
    # Controle: o ACUMULADO só com conta desconhecida continua o sinal de alerta.
    placar.linhas = [("u-x9", "Crianca Ficticia Outra Escola", K, 9, 9)]
    ex3, _ = rodar(db, eid, "matific")
    assert (ex3.status, ex3.motivo) == ("sem_atualizacao", "tudo_em_revisao")
    assert "confira se o acesso cadastrado é o desta escola" in _mensagem(db, eid, "matific")


# ---------------------------------------------------------------------------
# 2. Vinculados todos de fichas inativas: texto próprio, não o da 1ª coleta
# ---------------------------------------------------------------------------
def test_vinculados_todos_de_fichas_inativas_tem_texto_proprio(db, escola_completa,
                                                               monkeypatch):
    eid = escola_completa["escola"].id
    politica_sync.definir(db, eid, "bloquear")
    db.commit()
    credencial(db, eid, "elefante")
    instalar(monkeypatch, nav_elefante=NavElefante(_da_escola(escola_completa)))
    ex1, _ = rodar(db, eid, "elefante")
    assert ex1.status == "concluida"
    db.execute(update(Aluno).where(Aluno.escola_id == eid).values(status="transferido"))
    db.commit()
    ex2, erro = rodar(db, eid, "elefante")
    assert erro is None
    # O status já estava certo no 5bf01c8: nenhuma criança ATIVA veio.
    assert (ex2.status, ex2.motivo) == ("sem_atualizacao", "tudo_em_revisao")
    msg = _mensagem(db, eid)
    assert "ainda não tem nenhuma conta vinculada" not in msg, msg
    assert "3 conta(s) vinculada(s)" in msg and "não estão ativos" in msg, msg
    assert len(msg) <= 500


# ---------------------------------------------------------------------------
# 3. Queda retida de conta de ficha inativa não "confere a escola"
# ---------------------------------------------------------------------------
def test_queda_de_conta_de_ficha_transferida_nao_conta_como_conferida(
        db, escola_completa, monkeypatch):
    """Credencial de outra escola: lá está a criança A (transferida para lá), com
    total menor que o gravado aqui, e uma criança desconhecida. Antes, a queda da
    ficha TRANSFERIDA era retida e contava como "conta da escola conferida": a
    coleta saía 'correspondencia_pendente' e em dia. Agora a linha dela vai para a
    revisão (ficha inativa), nada da escola foi conferido e não é em dia."""
    eid, placar, ex1 = _matific_com_tres_vinculados(db, escola_completa, monkeypatch)
    a = escola_completa["alunos"][0]
    db.execute(update(Aluno).where(Aluno.id == a.id).values(status="transferido"))
    db.commit()
    placar.linhas = [("u-a", a.nome, K, 39, 9),
                     ("u-x1", "Crianca Ficticia Outra Escola Um", K, 55, 12)]
    ex2, erro = rodar(db, eid, "matific")
    assert erro is None
    assert (ex2.status, ex2.motivo) == ("sem_atualizacao", "tudo_em_revisao")
    assert service.ultimo_em_dia_em(db, eid, "matific") == ex1.finalizada_em
    # O valor gravado da criança transferida não muda (nem rebaixa, nem aplica).
    snap = snap_atual(db, SnapshotMatific, a.id)
    assert (snap.estrelas, snap.atividades) == (40, 10)
    # Controle: a queda de uma criança ATIVA continua retida e conferindo a escola.
    b = escola_completa["alunos"][1]
    placar.linhas = [("u-b", b.nome, K, 29, 8),
                     ("u-x1", "Crianca Ficticia Outra Escola Um", K, 55, 12)]
    ex3, _ = rodar(db, eid, "matific")
    assert (ex3.status, ex3.motivo) == ("sem_atualizacao", "correspondencia_pendente")
    assert service.ultimo_em_dia_em(db, eid, "matific") == ex3.finalizada_em


# ---------------------------------------------------------------------------
# 4. Só linhas sem vínculo (fila vazia): sem "0 conta(s) ... fila de revisão"
# ---------------------------------------------------------------------------
def test_so_linhas_sem_vinculo_nao_diz_zero_contas_na_fila(db, escola_completa,
                                                          monkeypatch):
    """As contas que vêm não têm nome utilizável (só pontuação): a linha fica sem
    vínculo e a fila de revisão, vazia. O texto não manda à fila vazia.

    (Antes o veículo era a conta APOSENTADA; desde o achado 5 da revisão e95 ela
    é descarte com motivo próprio, fora de 'sem_vinculo' — ver
    ``test_sync_identidade_aposentada``.)"""
    eid = escola_completa["escola"].id
    politica_sync.definir(db, eid, "bloquear")
    db.commit()
    credencial(db, eid, "elefante")
    nav = NavElefante(_da_escola(escola_completa))
    instalar(monkeypatch, nav_elefante=nav)
    ex1, _ = rodar(db, eid, "elefante")
    assert ex1.status == "concluida"
    nav.turmas = {CID_A: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
        aluno_el(9100011, "...", [livro("Livro Ficticio Um")]),
        aluno_el(9100012, "--", [livro("Livro Ficticio Um")]),
        aluno_el(9100013, "*", [livro("Livro Ficticio Um")])]}}
    ex2, _ = rodar(db, eid, "elefante")
    assert (ex2.status, ex2.motivo, ex2.qtd_em_revisao) == (
        "sem_atualizacao", "tudo_em_revisao", 0)
    msg = _mensagem(db, eid)
    assert "0 conta(s)" not in msg, msg
    # Resumo e leituras do Elefante: as mesmas contas vêm em dois arquivos.
    assert re.search(r"\b[1-9]\d* linha\(s\) sem vínculo seguro com uma ficha", msg), msg

    # Mesmo texto na correspondência pendente comum: as três crianças conferidas
    # pelas contas efetivas e UMA linha sem nome utilizável a mais.
    nav.turmas = {CID_A: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
        *_da_escola(escola_completa)[CID_A]["alunos"],
        aluno_el(9100011, "...", [livro("Livro Ficticio Um")])]}}
    ex3, _ = rodar(db, eid, "elefante")
    assert (ex3.status, ex3.motivo) == ("sem_atualizacao", "correspondencia_pendente")
    msg = _mensagem(db, eid)
    assert "0 conta(s)" not in msg and "Resolva as pendências" not in msg, msg
    assert re.search(r"\b[1-9]\d* linha\(s\) sem vínculo seguro com uma ficha", msg), msg
