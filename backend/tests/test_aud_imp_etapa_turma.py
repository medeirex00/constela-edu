"""Auditoria (frente importação): a ETAPA da turma de destino da ficha nova.

Ficha e matrícula novas não nascem numa turma de OUTRA etapa que a do relatório
(Educação Infantil × Fundamental) — "1 ANO A …" não nasce na turma da Fase, nem o
contrário. A comparação é entre a turma que o RELATÓRIO informa e a turma de
destino (nome + ano_escolar), qualquer que tenha sido o caminho até ela.

IMPORTACAO-2: com a turma escolhida pelo gestor (``criar_em_turma_id``), a rede de
segurança comparava a turma escolhida com ela mesma — deixava a criança do 1º Ano
nascer na "1ª Fase A" e recusava a criança da Fase na "1ºA" de ano_escolar
"1ª Fase". Dados fictícios.
"""
import json

from sqlalchemy import select

API = "/api/v1"
DATA = "2026-08-14T12:00:00"


def _placar(turma, alunos):
    corpo = {"fonte": "matific-placar", "alunos": alunos}
    if turma is not None:
        corpo["turma"] = turma
    return json.dumps(corpo, ensure_ascii=False)


def _analise(cliente, eid, texto):
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/analisar", data={"texto": texto})
    assert r.status_code == 200, r.text
    return r.json()


def _confirmar(cliente, eid, analise, linhas):
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/confirmar", json={
        "plataforma": analise["plataforma"], "formato": analise["formato"], "tipo": "texto",
        "recalcular": False, "linhas": linhas, "data_referencia": DATA})
    assert r.status_code == 200, r.text
    return r.json()


def _turma(db, eid, nome, ano_escolar):
    from app.models import Turma
    t = Turma(escola_id=eid, nome=nome, ano_escolar=ano_escolar, ano_letivo=2026)
    db.add(t)
    db.commit()
    return t.id


def _turmas_do_aluno(db, eid, nome):
    from app.models import Aluno, Matricula, Turma
    db.expire_all()
    return db.execute(
        select(Turma.nome).join(Matricula, Matricula.turma_id == Turma.id)
        .join(Aluno, Aluno.id == Matricula.aluno_id)
        .where(Aluno.escola_id == eid, Aluno.nome == nome)).scalars().all()


def _motivos(db, eid):
    from app.models import RevisaoIdentidade
    db.expire_all()
    return [r.motivo for r in db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == eid)).scalars()]


def _criar_na_turma(analise, turma_id):
    return [{"nome": linha["nome"], "dados": linha["dados"], "aluno_id": None,
             "criar_em_turma_id": turma_id, "criar_em_turma_nome": None}
            for linha in analise["linhas"]]


def test_crianca_do_1_ano_nao_nasce_na_turma_da_fase_escolhida(cliente, db, escola_completa):
    """Relatório "1 ANO A", turma "1ª Fase A" (Educação Infantil) escolhida para a
    criança nova: a ficha não nasce lá — vai para a Revisão, turma de outra etapa."""
    eid = escola_completa["escola"].id
    fase = _turma(db, eid, "1ª Fase A", "1ª Fase")
    analise = _analise(cliente, eid, _placar("1 ANO A", [
        {"nome": "Crianca Ficticia Primeiro Ano", "uuid": "uuid-fict-1ano", "estrelas": 5,
         "atividades": 1}]))
    _confirmar(cliente, eid, analise, _criar_na_turma(analise, fase))
    assert _turmas_do_aluno(db, eid, "Crianca Ficticia Primeiro Ano") == [], (
        "a criança do '1 ANO A' nasceu na turma da Fase escolhida; revisões "
        f"{_motivos(db, eid)}")
    assert _motivos(db, eid) == ["turma_de_outra_etapa"]


def test_crianca_da_fase_nasce_na_turma_da_fase_escolhida(cliente, db, escola_completa):
    """Relatório "1 FASE A", turma "1ºA" de ano_escolar "1ª Fase" (o nome que
    ``nome_turma_exibicao`` dá a "Fase 1A") escolhida: a MESMA etapa — a ficha nasce."""
    eid = escola_completa["escola"].id
    fase = _turma(db, eid, "1ºA", "1ª Fase")
    analise = _analise(cliente, eid, _placar("1 FASE A", [
        {"nome": "Crianca Ficticia Da Fase", "uuid": "uuid-fict-fase", "estrelas": 5,
         "atividades": 1}]))
    assert analise["linhas"][0]["correspondencia"]["status"] == "nao_encontrado"
    _confirmar(cliente, eid, analise, _criar_na_turma(analise, fase))
    assert _turmas_do_aluno(db, eid, "Crianca Ficticia Da Fase") == ["1ºA"], (
        f"turma da MESMA etapa escolhida recusada: revisões {_motivos(db, eid)}")
    assert _motivos(db, eid) == []


def test_turma_do_fundamental_escolhida_para_crianca_da_fase_vai_para_revisao(
        cliente, db, escola_completa):
    """O outro lado da mesma regra: a criança do relatório "1 FASE A" não nasce na
    turma "3º Ano A" do Fundamental, mesmo escolhida."""
    eid, turma = escola_completa["escola"].id, escola_completa["turma"].id
    analise = _analise(cliente, eid, _placar("1 FASE A", [
        {"nome": "Crianca Ficticia Da Fase", "uuid": "uuid-fict-fase", "estrelas": 5,
         "atividades": 1}]))
    _confirmar(cliente, eid, analise, _criar_na_turma(analise, turma))
    assert _turmas_do_aluno(db, eid, "Crianca Ficticia Da Fase") == []
    assert _motivos(db, eid) == ["turma_de_outra_etapa"]


def test_sem_turma_no_relatorio_a_turma_escolhida_vale(cliente, db, escola_completa):
    """Relatório sem turma (nem no cabeçalho nem na linha): não há etapa do relatório
    para comparar — a turma escolhida pelo gestor recebe a ficha."""
    eid = escola_completa["escola"].id
    fase = _turma(db, eid, "1ª Fase A", "1ª Fase")
    analise = _analise(cliente, eid, _placar(None, [
        {"nome": "Crianca Ficticia Sem Turma", "uuid": "uuid-fict-sem", "estrelas": 5,
         "atividades": 1}]))
    _confirmar(cliente, eid, analise, _criar_na_turma(analise, fase))
    assert _turmas_do_aluno(db, eid, "Crianca Ficticia Sem Turma") == ["1ª Fase A"]
