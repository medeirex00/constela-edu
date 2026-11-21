"""REG_NUMEROS-3 — Comparador (lado "aluno"): quem está FORA do ranking vigente não
mostra a posição gravada num cálculo antigo.

Desde o PEND-11 o recálculo limpa a posição de quem sai da população (Fase, ficha
inativa, sem matrícula do ano), mas a linha gravada antes disso fica como está até o
próximo recálculo da escola — por isso todo leitor filtra NA LEITURA (o Perfil e o
painel da turma já filtravam, ``academico._no_ranking_vigente``). O Comparador lia
``Nota.posicao``, ``posicao_leitura``/``posicao_matematica`` e o ``n_aferidos`` antigo
direto: a criança da Fase dizia "1º no Ranking Geral" ao lado do 1º de verdade.

Dados fictícios.
"""
from datetime import datetime

import pytest

from app.models import Aluno, Importacao, Matricula, Nota, SnapshotElefante, SnapshotMatific, Turma
from app.services import scoring

API = "/api/v1"


def _dados(db, esc, imp, aluno, n):
    db.add(SnapshotElefante(escola_id=esc.id, aluno_id=aluno.id, importacao_id=imp.id,
                            data_referencia=datetime(2026, 10, 1), livros_unicos=n,
                            tempo_leitura_min=10 * n, livros_por_nivel={"D": n}))
    db.add(SnapshotMatific(escola_id=esc.id, aluno_id=aluno.id, importacao_id=imp.id,
                           data_referencia=datetime(2026, 10, 1), atividades=n,
                           estrelas=2 * n, pontuacao_media=3.0))


@pytest.fixture()
def cenario(db, escola_completa):
    """Uma turma "1 FASE A" cadastrada como "1º Ano": a criança dela tem MAIS dado e fica
    em 1º. Depois a série é corrigida para "1ª Fase" e a ficha de outra criança é
    arquivada — e as duas linhas ficam com a posição carimbada no cálculo antigo (como
    as linhas gravadas antes do PEND-11, até o próximo recálculo da escola)."""
    esc = escola_completa["escola"]
    imp = Importacao(escola_id=esc.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    fase = Turma(escola_id=esc.id, nome="1 FASE A", ano_escolar="1º Ano",
                 ano_letivo=esc.ano_letivo_ativo, status="ativa")
    db.add(fase)
    db.flush()
    pequeno = Aluno(escola_id=esc.id, nome="Pequeno Fictício da Fase", status="ativo")
    db.add(pequeno)
    db.flush()
    db.add(Matricula(escola_id=esc.id, aluno_id=pequeno.id, turma_id=fase.id,
                     ano_letivo=esc.ano_letivo_ativo))
    _dados(db, esc, imp, pequeno, 50)
    for i, aluno in enumerate(escola_completa["alunos"]):
        _dados(db, esc, imp, aluno, 10 + 5 * i)
    db.commit()
    scoring.recalcular_escola(db, esc.id)

    def carimbo(aluno_id):
        nota = db.query(Nota).filter_by(aluno_id=aluno_id,
                                        ano_letivo=esc.ano_letivo_ativo).one()
        return nota.posicao, nota.posicao_leitura, nota.posicao_matematica

    antigos = {pequeno.id: carimbo(pequeno.id)}
    arquivada = escola_completa["alunos"][2]          # a 2ª com mais dado depois do pequeno
    antigos[arquivada.id] = carimbo(arquivada.id)
    assert antigos[pequeno.id] == (1, 1, 1)

    # A série é corrigida e a ficha é arquivada; o ranking é recalculado…
    fase.ano_escolar = "1ª Fase"
    arquivada.status = "arquivado"
    db.commit()
    scoring.recalcular_escola(db, esc.id)
    # …mas a linha antiga (gravada antes do PEND-11) guardava a posição de então.
    for aluno_id, (geral, leitura, matematica) in antigos.items():
        nota = db.query(Nota).filter_by(aluno_id=aluno_id,
                                        ano_letivo=esc.ano_letivo_ativo).one()
        nota.posicao, nota.posicao_leitura, nota.posicao_matematica = (
            geral, leitura, matematica)
    db.commit()
    return {"escola": esc, "pequeno": pequeno, "arquivada": arquivada}


def _comparar(cliente, esc, id_a, id_b):
    r = cliente.get(f"{API}/escolas/{esc.id}/comparar", params={
        "tipo_a": "aluno", "id_a": id_a, "tipo_b": "aluno", "id_b": id_b})
    assert r.status_code == 200, r.text
    return r.json()["a"], r.json()["b"]


@pytest.mark.parametrize("quem", ["pequeno", "arquivada"])
def test_comparador_nao_mostra_a_posicao_de_quem_saiu_do_ranking(cliente, cenario, quem):
    esc = cenario["escola"]
    ranking = cliente.get(f"{API}/escolas/{esc.id}/ranking").json()
    primeiro = ranking[0]
    fora = cenario[quem]
    assert primeiro["posicao"] == 1 and primeiro["aluno_id"] != fora.id
    assert fora.id not in {item["aluno_id"] for item in ranking}

    a, b = _comparar(cliente, esc, fora.id, primeiro["aluno_id"])
    assert a["notas"]["posicao"] is None, (
        f"Comparador diz '{a['notas']['posicao']}º no Ranking Geral' para quem está fora "
        f"do ranking; o 1º de verdade (lado B) diz '{b['notas']['posicao']}º'")
    for dimensao, bloco in a["dimensoes"].items():
        assert bloco["posicao"] is None, (dimensao, bloco)
        assert bloco["n_aferidos"] is None, (dimensao, bloco)
        # As notas continuam: só a posição era do cálculo antigo.
        assert bloco["nota"] is not None, (dimensao, bloco)
    # O lado do 1º de verdade não muda.
    assert b["notas"]["posicao"] == 1
    assert all(bloco["posicao"] == 1 and bloco["n_aferidos"]
               for bloco in b["dimensoes"].values()), b["dimensoes"]


def test_comparador_e_perfil_concordam_para_quem_saiu(cliente, cenario):
    esc, pequeno = cenario["escola"], cenario["pequeno"]
    perfil = cliente.get(f"{API}/escolas/{esc.id}/alunos/{pequeno.id}/perfil").json()
    outro = cenario["arquivada"]
    a, _ = _comparar(cliente, esc, pequeno.id, outro.id)
    assert perfil["posicao"] is None and a["notas"]["posicao"] is None
    assert [d["posicao"] for d in perfil["dimensoes"]] == [None, None]
