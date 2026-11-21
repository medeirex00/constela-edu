"""REG_NUMEROS-4 (item 2) — Assistente: as seções RANKING, os pódios e ALUNOS do contexto
da IA seguem a POPULAÇÃO do Ranking Geral.

A consulta de ``assistente.montar_contexto`` lia Nota × Matrícula do ano filtrando só a
ficha ativa: a Nota de quem foi para turma de Fase continuava na lista — com a posição
do cálculo antigo (duas crianças em 1º) ou, depois do recálculo que a limpa, como
"Noneº". E a criança sem NENHUM dado entrava com "Nº lugar, geral 0,0", que o Ranking
Geral, o Top 10 e o telão não mostram (DEC-19: ausência não é zero).

(O item 1, a régua da seção EVOLUCAO, já foi corrigido em a7456fb4 —
test_aud2_assist_ia_evolucao.py.)

Dados fictícios; o assistente roda no modo LOCAL (nada sai da máquina).
"""
from datetime import datetime

import pytest

from app.models import Aluno, Importacao, Matricula, Nota, SnapshotElefante, SnapshotMatific, Turma
from app.services import assistente, scoring

API = "/api/v1"


def _secao(contexto: str, nome: str) -> str:
    return contexto.split(f"### {nome}\n", 1)[1].split("\n### ", 1)[0]


def _dados(db, esc, imp, aluno, n):
    db.add(SnapshotElefante(escola_id=esc.id, aluno_id=aluno.id, importacao_id=imp.id,
                            data_referencia=datetime(2026, 10, 1), livros_unicos=n,
                            tempo_leitura_min=10 * n, livros_por_nivel={"D": n}))
    db.add(SnapshotMatific(escola_id=esc.id, aluno_id=aluno.id, importacao_id=imp.id,
                           data_referencia=datetime(2026, 10, 1), atividades=n,
                           estrelas=2 * n, pontuacao_media=3.0))


def _aluno(db, esc, turma, nome):
    a = Aluno(escola_id=esc.id, nome=nome, status="ativo")
    db.add(a)
    db.flush()
    db.add(Matricula(escola_id=esc.id, aluno_id=a.id, turma_id=turma.id,
                     ano_letivo=esc.ano_letivo_ativo))
    return a


@pytest.fixture()
def cenario(db, escola_completa):
    """Turma "1 FASE A" cadastrada como "1º Ano": os dois pequenos têm MAIS dado e ficam
    em 1º e 2º. Uma criança do 3º ano ainda não tem dado nenhum. Depois a coordenação
    corrige a série para "1ª Fase" (rota real, que recalcula)."""
    esc = escola_completa["escola"]
    imp = Importacao(escola_id=esc.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    fase = Turma(escola_id=esc.id, nome="1 FASE A", ano_escolar="1º Ano",
                 ano_letivo=esc.ano_letivo_ativo, status="ativa")
    db.add(fase)
    db.flush()
    pequenos = [_aluno(db, esc, fase, nome)
                for nome in ("Pequeno Um Fictício", "Pequeno Dois Fictício")]
    sem_dado = _aluno(db, esc, escola_completa["turma"], "Criança Fictícia Sem Coleta")
    for i, a in enumerate(pequenos):
        _dados(db, esc, imp, a, 50 - 5 * i)
    for i, a in enumerate(escola_completa["alunos"]):
        _dados(db, esc, imp, a, 10 + i)
    db.commit()
    scoring.recalcular_escola(db, esc.id)
    antigos = {}
    for a in pequenos:
        nota = db.query(Nota).filter_by(aluno_id=a.id, ano_letivo=esc.ano_letivo_ativo).one()
        antigos[a.id] = (nota.posicao, nota.posicao_leitura, nota.posicao_matematica)
    assert sorted(p for p, _l, _m in antigos.values()) == [1, 2]
    return {"escola": esc, "fase": fase, "pequenos": pequenos, "sem_dado": sem_dado,
            "antigos": antigos, "ativos": escola_completa["alunos"]}


def _corrigir_para_fase(cliente, cenario):
    esc, fase = cenario["escola"], cenario["fase"]
    r = cliente.put(f"{API}/escolas/{esc.id}/turmas/{fase.id}", json={"ano_escolar": "1ª Fase"})
    assert r.status_code == 200, r.text


def _recarimbar(db, cenario):
    """A linha gravada antes de o recálculo limpar a posição de quem sai (PEND-11) fica
    com a posição antiga até o próximo recálculo da escola."""
    for aluno_id, (geral, leitura, matematica) in cenario["antigos"].items():
        nota = db.query(Nota).filter_by(aluno_id=aluno_id).one()
        nota.posicao, nota.posicao_leitura, nota.posicao_matematica = (
            geral, leitura, matematica)
    db.commit()


@pytest.mark.parametrize("linha_antiga", [False, True],
                         ids=["depois_do_recalculo", "linha_antiga"])
def test_contexto_sem_as_fases_e_sem_posicao_repetida(cliente, db, cenario, linha_antiga):
    _corrigir_para_fase(cliente, cenario)
    if linha_antiga:
        _recarimbar(db, cenario)
    db.expire_all()
    contexto = assistente.montar_contexto(db, cenario["escola"].id)
    for nome_secao in ("RANKING", "RANKING_MATIFIC", "RANKING_ELEFANTE", "ALUNOS"):
        secao = _secao(contexto, nome_secao)
        for pequeno in cenario["pequenos"]:
            assert pequeno.nome not in secao, (nome_secao, secao)
        assert "None" not in secao, (nome_secao, secao)
    ranking = _secao(contexto, "RANKING").splitlines()
    primeiros = [ln for ln in ranking if ln.startswith("- 1º:")]
    assert len(primeiros) == 1, ranking
    # O RANKING do contexto é o Ranking Geral da escola (mesmos nomes, mesma ordem).
    geral = cliente.get(f"{API}/escolas/{cenario['escola'].id}/ranking").json()
    esperado = [(i["posicao"], i["nome"]) for i in geral][:15]
    obtido = [(int(ln[2:].split("º: ", 1)[0]), ln.split("º: ", 1)[1].split(" (", 1)[0])
              for ln in ranking]
    assert obtido == esperado


def test_crianca_sem_dado_nao_tem_lugar_nem_zero_no_contexto(cliente, db, cenario):
    _corrigir_para_fase(cliente, cenario)
    db.expire_all()
    contexto = assistente.montar_contexto(db, cenario["escola"].id)
    sem_dado = cenario["sem_dado"]
    for nome_secao in ("RANKING", "RANKING_MATIFIC", "RANKING_ELEFANTE"):
        assert sem_dado.nome not in _secao(contexto, nome_secao), nome_secao
    (linha,) = [ln for ln in _secao(contexto, "ALUNOS").splitlines() if sem_dado.nome in ln]
    assert "º lugar" not in linha and "geral" not in linha and "0.0" not in linha, linha
    assert "sem dados" in linha, linha
    for ativo in cenario["ativos"]:
        assert ativo.nome in _secao(contexto, "RANKING")
    assert "- Alunos com nota: 3" in _secao(contexto, "RESUMO")


def test_resposta_local_quem_esta_em_primeiro(cliente, db, cenario, monkeypatch):
    for var in ("AI_PROVIDER", "AI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    _corrigir_para_fase(cliente, cenario)
    _recarimbar(db, cenario)
    esc = cenario["escola"]
    r = cliente.post(f"{API}/escolas/{esc.id}/assistente",
                     json={"pergunta": "quem está em 1º no ranking?"})
    assert r.status_code == 200, r.text
    resposta = r.json()["resposta"]
    primeiros = [ln for ln in resposta.splitlines() if ln.startswith("- 1º:")]
    assert len(primeiros) == 1, resposta
    assert all(p.nome not in resposta for p in cenario["pequenos"]), resposta
