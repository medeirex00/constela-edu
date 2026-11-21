"""S_G_GRUPO-1 (costura da fase D) — a matrícula do ano ativo numa turma de OUTRO ano (dado
legado de antes das travas de escrita) fica fora de toda população "da escola" que a
Secretaria vê, não só do cartão do Panorama da Rede (d48f87e0).

O cartão da rede, a Visão da Escola e o ranking da escola contam só quem está numa turma do
ano ativo. Três populações ainda contavam a matrícula do ano ativo em QUALQUER turma — cada
uma, cruzada com o cartão, devolvia os números da criança:

* o frescor da rede (``frescor_ranking.frescor_das_escolas``: alunos com dado, datas do dado
  mais novo e mais antigo) — as turmas premiáveis vinham de todos os anos;
* o lado "escola" do comparador (``evolucao._lado_escola``: total de alunos e indicadores);
* a coorte da Análise da rede (``analise.plataformas._parte_coorte``), por escola e série, com
  o ano escolar da turma antiga.

O cenário (8 crianças na turma do ano e a "canário" numa turma do ano passado) é o de
``test_aud3_rede_legado_turma_outro_ano``. Escolas e crianças FICTÍCIAS.
"""
from __future__ import annotations

from datetime import date

from app.core.tempo import hoje_br
from app.services import evolucao, frescor_ranking
from app.services.analise import plataformas as analise_plataformas
from tests._ano_letivo import escola_no_ano_de_hoje  # noqa: F401 — fixture
from tests.test_aud3_rede_legado_turma_outro_ano import CANARIO, _cenario


def _hoje() -> date:
    return hoje_br()


def test_frescor_da_rede_nao_conta_a_matricula_numa_turma_de_outro_ano(db, escola_completa):
    escola, _rede, _canario, _antiga = _cenario(db, escola_completa, legado=True)
    bloco = frescor_ranking.frescor_das_escolas(db, [escola], _hoje())[escola.id]
    # Antes: 9 — a criança da turma do ano passado entrava no "alunos com dado".
    # (Só a leitura: o retrato do cenário é de "ontem", e com o relógio na virada do ano
    # o Matific de ontem é de outro ano — fora da janela do contador do ano.)
    assert bloco["dimensoes"]["leitura"]["alunos_com_dado"] == 8


def test_frescor_controle_sem_legado_conta_as_nove(db, escola_completa):
    escola, _rede, _canario, _antiga = _cenario(db, escola_completa, legado=False)
    bloco = frescor_ranking.frescor_das_escolas(db, [escola], _hoje())[escola.id]
    assert bloco["dimensoes"]["leitura"]["alunos_com_dado"] == 9


def test_comparador_lado_escola_nao_conta_a_matricula_numa_turma_de_outro_ano(
        db, escola_completa):
    escola, _rede, _canario, _antiga = _cenario(db, escola_completa, legado=True)
    turma = escola_completa["turma"]
    resultado = evolucao.comparar(db, escola.id, "escola", escola.id, "turma", turma.id)
    lado_escola, lado_turma = resultado["a"], resultado["b"]
    # Antes: 9 alunos e os 37 livros / 1913 min da criança canário no lado "escola" —
    # escola − turma (a única do ano) devolvia os números dela.
    assert lado_escola["total_alunos"] == lado_turma["total_alunos"] == 8
    assert lado_escola["indicadores"]["livros_unicos"] == 80
    assert (lado_escola["indicadores"]["tempo_leitura_min"]
            == lado_turma["indicadores"]["tempo_leitura_min"])
    assert lado_escola["indicadores"]["livros_unicos"] != 80 + CANARIO["livros"]


def test_coorte_da_analise_da_rede_nao_conta_a_matricula_numa_turma_de_outro_ano(
        db, escola_completa):
    escola, _rede, canario, _antiga = _cenario(db, escola_completa, legado=True)
    contagens, coortes = analise_plataformas._coortes(db, [escola])
    # Antes: a canário entrava na coorte (e na série) com a turma do ano passado.
    assert canario.id not in coortes[escola.id]
    assert contagens[escola.id].total + contagens[escola.id].fora == 8
    assert contagens[escola.id].series == {3: 8}


def test_coorte_da_analise_controle_sem_legado(db, escola_completa):
    escola, _rede, canario, _antiga = _cenario(db, escola_completa, legado=False)
    contagens, coortes = analise_plataformas._coortes(db, [escola])
    assert canario.id in coortes[escola.id]
    assert contagens[escola.id].series == {3: 9}
