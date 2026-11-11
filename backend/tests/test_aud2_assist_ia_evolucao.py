"""Contexto do Assistente: a seção EVOLUCAO usa a régua do Ranking de Evolução.

O Ranking de Evolução da web, o app, o telão, o mural e o /insights chamam
``evolucao.ranking_evolucao(..., base_no_periodo=True)`` só com as turmas que
concorrem (sem as Fases). O contexto do Assistente ("evolução 30 dias", top 10)
ainda usava a régua antiga: a criança cujo 1º retrato caía no mês aparecia como
quem mais evoluiu, e as Fases entravam na lista (RANKINGS-2, outra superfície).
Dados 100% fictícios.
"""
from datetime import datetime, timedelta, timezone

from app.models import Aluno, Importacao, Matricula, SnapshotMatific, Turma
from app.services import assistente, scoring

API = "/api/v1"


def _secao(contexto: str, nome: str) -> str:
    return contexto.split(f"### {nome}\n", 1)[1].split("\n### ", 1)[0]


def _cenario(db, escola_completa):
    """1ª criança: PRIMEIRO retrato há 5 dias, com acumulado grande (de antes da
    janela). 2ª: cresceu de verdade nos 30 dias. Criança da Fase: o maior
    crescimento de todos, mas a turma não concorre."""
    escola = escola_completa["escola"]
    primeira, segunda, _terceira = escola_completa["alunos"]
    fase = Turma(escola_id=escola.id, nome="1ª Fase A", ano_escolar="1ª Fase",
                 ano_letivo=2026)
    db.add(fase)
    db.flush()
    pequena = Aluno(escola_id=escola.id, nome="Lia Inventada Moraes")
    db.add(pequena)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=pequena.id, turma_id=fase.id,
                     ano_letivo=2026))
    imp = Importacao(escola_id=escola.id, plataforma="matific", tipo="seed")
    db.add(imp)
    db.flush()
    agora = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=primeira.id, importacao_id=imp.id,
                           data_referencia=agora - timedelta(days=5),
                           atividades=120, estrelas=360, pontuacao_media=4.0))
    for aluno, final in ((segunda, 25), (pequena, 90)):
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                               data_referencia=agora - timedelta(days=60),
                               atividades=10, estrelas=30, pontuacao_media=3.0))
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                               data_referencia=agora - timedelta(days=5),
                               atividades=final, estrelas=3 * final, pontuacao_media=3.5))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    return escola, primeira, segunda, pequena


def test_evolucao_do_contexto_lidera_quem_cresceu_de_verdade(db, escola_completa):
    escola, primeira, segunda, _pequena = _cenario(db, escola_completa)
    linhas = _secao(assistente.montar_contexto(db, escola.id), "EVOLUCAO").splitlines()
    assert linhas and linhas[0].startswith(f"- 1º: {segunda.nome} "), linhas
    assert not any(ln.startswith(f"- 1º: {primeira.nome} ") for ln in linhas), linhas


def test_evolucao_do_contexto_sem_as_fases(db, escola_completa):
    escola, _primeira, _segunda, pequena = _cenario(db, escola_completa)
    evolucao = _secao(assistente.montar_contexto(db, escola.id), "EVOLUCAO")
    assert pequena.nome not in evolucao, evolucao


def test_evolucao_do_contexto_igual_ao_ranking_de_evolucao(cliente, db, escola_completa):
    escola, *_ = _cenario(db, escola_completa)
    web = cliente.get(f"{API}/escolas/{escola.id}/ranking-evolucao", params={"dias": 30})
    assert web.status_code == 200, web.text
    esperado = [(i["posicao"], i["nome"], round(i["nota_evolucao"], 1))
                for i in web.json()[:10]]
    linhas = _secao(assistente.montar_contexto(db, escola.id), "EVOLUCAO").splitlines()
    obtido = []
    for linha in linhas:
        posicao, resto = linha[2:].split("º: ", 1)
        nome = resto.split(" (", 1)[0]
        nota = float(resto.split("evolução ", 1)[1].split(" ", 1)[0])
        obtido.append((int(posicao), nome, nota))
    assert obtido == esperado
