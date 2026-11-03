"""Elefante: contas JÁ vinculadas que não vieram no relatório da coleta COMPLETA
geram aviso com a contagem ('contas_ausentes'), como o Matific — sem mudar o
status do aluno nem o da execução e sem apagar dado.

Antes (e90 ``test_dado_que_sumiu…``, A2 §3.8) a criança que sumia do relatório de
turma ficava com o dado parado e nada avisava: o serviço só abria
'contas_ausentes' para o Matific. Dados 100% fictícios; conector real com
navegador falso; sem rede.
"""
from sqlalchemy import select, text

from app.models import Aluno
from app.models.plataformas import SnapshotElefante
from app.models.sincronizacao import SincronizacaoAlerta
from app.sync import service
from tests._sync_nucleo_fakes import (NavElefante, aluno_el, alertas_abertos, credencial,
                                      ident, instalar, livro, logs, rodar, snap_atual)

T1, T2 = 511434, 600001


def _turmas(a, b):
    return {T1: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
        aluno_el(9100001, a.nome, [livro("Livro Ficticio Um")]),
        aluno_el(9100002, b.nome, [livro("Livro Ficticio Dois", "E", "2026-09-05T10:00:00")])]}}


def _forcar_coleta_completa(db):
    db.execute(text("DELETE FROM configuracoes WHERE chave LIKE '%ultima_coleta_completa%'"))
    db.commit()


def _mensagem(db, eid):
    return db.execute(select(SincronizacaoAlerta.mensagem).where(
        SincronizacaoAlerta.escola_id == eid, SincronizacaoAlerta.plataforma == "elefante",
        SincronizacaoAlerta.tipo == "contas_ausentes",
        SincronizacaoAlerta.resolvido.is_(False))).scalars().first()


def test_conta_vinculada_que_some_da_coleta_completa_gera_aviso_sem_mudar_status(
        db, escola_completa, monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    a, b, _c = ec["alunos"]
    credencial(db, eid, "elefante")
    turmas = _turmas(a, b)
    instalar(monkeypatch, nav_elefante=NavElefante(turmas))

    ex1, _ = rodar(db, eid, "elefante")                     # 1ª coleta: completa (sem cursor)
    assert ex1.status == "concluida"
    assert ident(db, eid, "elefante", 9100002) == b.id    # a conta de b ficou vinculada
    assert "contas_ausentes" not in alertas_abertos(db, eid, "elefante")
    snap_b = snap_atual(db, SnapshotElefante, b.id)
    retrato_b = (snap_b.id, snap_b.livros_unicos, snap_b.tempo_leitura_min)

    # b some do relatório de turma; a coleta seguinte é a recoleta completa
    turmas[T1]["alunos"] = [x for x in turmas[T1]["alunos"] if x["sid"] != 9100002]
    _forcar_coleta_completa(db)
    ex2, _ = rodar(db, eid, "elefante")
    assert (ex2.status, ex2.motivo) == ("sem_atualizacao", "nada_mudou")   # status não muda
    assert "contas_ausentes" in alertas_abertos(db, eid, "elefante")
    mensagem = _mensagem(db, eid)
    assert mensagem.startswith("1 conta(s) do Elefante Letrado")
    assert b.nome not in mensagem                          # só a contagem, sem nome
    assert any(m == mensagem for _e, _n, m in logs(db, ex2.id))
    db.expire_all()
    assert db.get(Aluno, b.id).status == "ativo"           # a ficha não muda
    snap_b = snap_atual(db, SnapshotElefante, b.id)
    assert (snap_b.id, snap_b.livros_unicos, snap_b.tempo_leitura_min) == retrato_b
    # o aviso não é "falha da execução": não explica erro, não é categoria de falha
    assert "contas_ausentes" in service.TIPOS_REGRA_PROPRIA

    # coleta INCREMENTAL (não completa): não avalia — o aviso fica como está
    ex3, _ = rodar(db, eid, "elefante")
    assert ex3.status == "sem_atualizacao"
    assert "contas_ausentes" in alertas_abertos(db, eid, "elefante")

    # b volta e a coleta completa seguinte confere todas: o aviso fecha
    turmas[T1]["alunos"] = _turmas(a, b)[T1]["alunos"]
    _forcar_coleta_completa(db)
    rodar(db, eid, "elefante")
    assert "contas_ausentes" not in alertas_abertos(db, eid, "elefante")


def test_turma_que_falhou_nao_conta_como_ausencia(db, escola_completa, monkeypatch):
    """Aluno de uma turma que NÃO respondeu não "sumiu do relatório": a coleta já é
    'parcial' (alerta 'coleta_parcial'); somar 'contas_ausentes' seria dobrar o
    alarme e culpar a conta."""
    from app.models import Turma
    from tests._sync_nucleo_fakes import novo_aluno, vincular
    ec = escola_completa
    eid = ec["escola"].id
    a, b, _c = ec["alunos"]
    t2 = Turma(escola_id=eid, nome="4º Ano B", ano_escolar="4º Ano", ano_letivo=2026)
    db.add(t2)
    db.flush()
    d = novo_aluno(db, eid, t2, "Crianca Ficticia Quarto Ano")
    vincular(db, eid, d.id, "elefante", 9200001)
    db.commit()
    credencial(db, eid, "elefante")
    turmas = _turmas(a, b)
    turmas[T2] = {"nome": "4 ANO B TARDE ANUAL", "alunos": [
        aluno_el(9200001, d.nome, [livro("Livro Ficticio Tres", "D", "2026-09-07T10:00:00")])]}
    instalar(monkeypatch, nav_elefante=NavElefante(turmas, erro_turma={T2: 500}))

    ex, _ = rodar(db, eid, "elefante")
    assert ex.status == "parcial"
    abertos = alertas_abertos(db, eid, "elefante")
    assert "coleta_parcial" in abertos and "contas_ausentes" not in abertos


def test_matific_continua_avisando_no_acumulado(db, escola_completa, monkeypatch):
    """A generalização não muda o Matific: o acumulado do ano avisa como antes."""
    from tests._sync_nucleo_fakes import PlacarFake, vincular
    ec = escola_completa
    eid = ec["escola"].id
    a, b, _c = ec["alunos"]
    vincular(db, eid, b.id, "matific", "u-b")
    db.commit()
    credencial(db, eid, "matific")
    placar = PlacarFake()
    placar.linhas = [("u-a", a.nome, "3 ANO A (300396804)", 40, 10)]
    instalar(monkeypatch, placar=placar)
    rodar(db, eid, "matific")
    assert "contas_ausentes" in alertas_abertos(db, eid, "matific")
    mensagem = db.execute(select(SincronizacaoAlerta.mensagem).where(
        SincronizacaoAlerta.escola_id == eid, SincronizacaoAlerta.tipo == "contas_ausentes",
        SincronizacaoAlerta.resolvido.is_(False))).scalars().first()
    assert mensagem.startswith("1 conta(s) do Matific") and "no Placar desta coleta" in mensagem


def test_student_id_com_espacos_ou_ponto_zero_nao_vira_conta_ausente(
        db, escola_completa, monkeypatch):
    """Rodada 3 do e97: o conector anotava ``ids_recebidos`` com str(studentId) +
    isdigit(), mas a identidade é gravada por ``importacao.student_id_elefante``
    (sem espaços, sem o sufixo ".0"). Com " 9100002 " e 9100001.0 a conta "9100002"
    / "9100001" era gravada e NÃO entrava em ``ids_recebidos`` — a coleta completa
    avisava 'contas_ausentes' por engano (as duas, já na 1ª coleta). Agora os dois
    lados usam a mesma regra."""
    from app.services.importacao import student_id_elefante

    assert student_id_elefante(" 9100002 ") == student_id_elefante(9100002.0) \
        == student_id_elefante("9100002.0") == "9100002"
    assert student_id_elefante("000") == "" and student_id_elefante(None) == ""
    ec = escola_completa
    eid = ec["escola"].id
    a, b, _c = ec["alunos"]
    credencial(db, eid, "elefante")
    turmas = {T1: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
        aluno_el(9100001.0, a.nome, [livro("Livro Ficticio Um")]),
        aluno_el(" 9100002 ", b.nome, [livro("Livro Ficticio Dois")])]}}
    instalar(monkeypatch, nav_elefante=NavElefante(turmas))

    ex1, _ = rodar(db, eid, "elefante")                     # 1ª coleta: completa
    assert ex1.status in ("concluida", "parcial", "sem_atualizacao"), (ex1.status, ex1.motivo)
    assert ident(db, eid, "elefante", 9100001) == a.id
    assert ident(db, eid, "elefante", 9100002) == b.id
    assert "contas_ausentes" not in alertas_abertos(db, eid, "elefante")

    _forcar_coleta_completa(db)                              # recoleta completa
    rodar(db, eid, "elefante")
    assert "contas_ausentes" not in alertas_abertos(db, eid, "elefante")
