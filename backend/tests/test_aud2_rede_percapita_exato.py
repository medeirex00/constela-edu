"""G_ANALISE-4 — o PER CAPITA da rede é comparado pela conta exata e arredondado só
para exibir (meio para cima, como a análise).

``_cartoes_da_rede`` gravava ``livros_por_matricula = round(livros ÷ alunos, 1)`` (o
``round`` meio-par do Python) e esse valor JÁ arredondado era a régua e a entrada do
índice 0–1000, a chave de ordem do Ranking da Rede e a dos destaques e da vitrine. A
escola com 98 livros para 8 alunos (12,25) empatava com a de 12,2: as duas recebiam
índice 1000 ("a melhor da rede") e o desempate pela adoção dava o 1º lugar à outra.

Redes, escolas e crianças FICTÍCIAS; números escolhidos à mão.
"""
from datetime import datetime

import pytest

from app.models import Importacao, SnapshotElefante, SnapshotMatific
from app.services import rede as svc
from tests.test_analise_base import nova_escola, nova_rede, turma_com_alunos

QUANDO = datetime(2026, 9, 30, 3, 0)


def _retratos(db, escola, alunos, livros, estrelas):
    imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed", status="concluida")
    db.add(imp)
    db.flush()
    for a, lv, es in zip(alunos, livros, estrelas):
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=a.id, importacao_id=imp.id,
                                data_referencia=QUANDO, livros_unicos=lv,
                                tempo_leitura_min=10 * lv, questoes_tentativas=0,
                                questoes_acertos=0, livros_por_nivel={}))
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=a.id, importacao_id=imp.id,
                               data_referencia=QUANDO, atividades=10, estrelas=es,
                               pontuacao_media=0.0))
    db.flush()


def _mundo(db, codigo="3599981"):
    """Xis: 8 do 3º ano, 98 livros (12,25 por aluno) e 240 estrelas (30), mais 2 da
    1ª Fase sem dado — adoção do Elefante 80%. Ypsilon: 10 do 3º ano, 122 livros (12,2)
    e 400 estrelas (40) — adoção 100%. Zeta: 5 do 3º ano, 10 livros (2) e 100 estrelas
    (20), mais 5 da 1ª Fase com retratos enormes (não concorrem)."""
    rede = nova_rede(db, nome=f"Rede Inventada Conta à Mão {codigo}", codigo=codigo)
    x = nova_escola(db, rede, "EMEF Inventada Xis", None)
    _retratos(db, x, turma_com_alunos(db, x, "3º Ano", 8), [12] * 6 + [13, 13], [30] * 8)
    turma_com_alunos(db, x, "1ª Fase", 2)
    y = nova_escola(db, rede, "EMEF Inventada Ypsilon", None)
    _retratos(db, y, turma_com_alunos(db, y, "3º Ano", 10), [12] * 8 + [13, 13], [40] * 10)
    z = nova_escola(db, rede, "EMEF Inventada Zeta", None)
    _retratos(db, z, turma_com_alunos(db, z, "3º Ano", 5), [2] * 5, [20] * 5)
    _retratos(db, z, turma_com_alunos(db, z, "1ª Fase", 5), [500] * 5, [9000] * 5)
    db.commit()
    return rede


def test_indice_e_regua_saem_do_per_capita_exato(db):
    rede = _mundo(db)
    cartoes = {c["nome"]: c for c in svc.dashboard_rede(db, rede.id)["escolas"]}
    x, y, z = (cartoes[f"EMEF Inventada {n}"] for n in ("Xis", "Ypsilon", "Zeta"))
    # Exibição: 98 ÷ 8 = 12,25 → 12,3 (meio para cima); antes 12,2 (meio-par), igual a Ypsilon.
    assert (x["livros_por_matricula"], y["livros_por_matricula"]) == (12.3, 12.2)
    # Régua = 12,25 (a melhor de verdade): Ypsilon 12,2 ÷ 12,25 × 1000 = 995,9 (antes 1000)
    # e Zeta 2 ÷ 12,25 × 1000 = 163,3 (antes 2 ÷ 12,2 = 163,9).
    assert x["pontuacao_leitura"] == 1000.0
    assert y["pontuacao_leitura"] == 995.9
    assert z["pontuacao_leitura"] == 163.3
    assert (x["pontuacao_matematica"], y["pontuacao_matematica"]) == (750.0, 1000.0)
    assert y["pontuacao_geral"] == pytest.approx(998.0, abs=0.1)


def test_aba_leitura_ordena_pelo_per_capita_exato(db):
    rede = _mundo(db)
    for secretaria in (False, True):
        leitura = svc.ranking_escolas(db, rede.id, metrica="livros_aluno", secretaria=secretaria)
        # Xis (12,25) à frente de Ypsilon (12,2); antes empatavam em 12,2 e a adoção do
        # Elefante (Ypsilon 100% × Xis 80%) dava o 1º lugar a Ypsilon.
        assert [(r["posicao"], r["nome"]) for r in leitura] == [
            (1, "EMEF Inventada Xis"), (2, "EMEF Inventada Ypsilon"), (3, "EMEF Inventada Zeta")]
        indice = svc.ranking_escolas(db, rede.id, metrica="indice_leitura", secretaria=secretaria)
        assert [r["nome"] for r in indice][:2] == ["EMEF Inventada Xis", "EMEF Inventada Ypsilon"]


def test_mesmo_valor_exibido_nao_empata_quem_le_mais(db):
    """12,24 e 12,2 aparecem os dois como 12,2: a ordem é a da conta exata, não a do
    desempate (que daria o 1º lugar à de adoção maior)."""
    rede = nova_rede(db, nome="Rede Inventada Quase Empate", codigo="3599982")
    p = nova_escola(db, rede, "EMEF Inventada Pi", None)
    criancas = turma_com_alunos(db, p, "3º Ano", 25)
    _retratos(db, p, criancas[:24], [13] * 18 + [12] * 6, [10] * 24)   # 306 ÷ 25 = 12,24
    q = nova_escola(db, rede, "EMEF Inventada Qui", None)
    _retratos(db, q, turma_com_alunos(db, q, "3º Ano", 10), [12] * 8 + [13, 13], [10] * 10)
    db.commit()
    leitura = svc.ranking_escolas(db, rede.id, metrica="livros_aluno")
    assert [(r["nome"], r["livros_por_matricula"]) for r in leitura] == [
        ("EMEF Inventada Pi", 12.2), ("EMEF Inventada Qui", 12.2)]
    assert [r["pontuacao_leitura"] for r in leitura] == [1000.0, 996.7]


def test_destaques_e_vitrine_ordenam_pela_conta_exata(db):
    rede = _mundo(db)
    esperado = [("EMEF Inventada Xis", 12.3), ("EMEF Inventada Ypsilon", 12.2),
                ("EMEF Inventada Zeta", 2.0)]
    vitrine = svc.painel_publico_rede(db, rede.id)["top_leitura"]
    assert [(e["nome"], e["valor"]) for e in vitrine] == esperado
    destaques = svc.destaques_rede(db, rede.id)["leitura"]["escolas"]
    assert [(e["nome"], e["valor"]) for e in destaques] == esperado


def test_panorama_global_compara_redes_pelo_per_capita_exato(db):
    """Duas redes de uma escola cada, com 12,25 e 12,2 livros por aluno e as mesmas 30
    estrelas por aluno: antes as duas saíam com 12,2 e índice 1000."""
    um = nova_rede(db, nome="Rede Inventada Um", codigo="3599983")
    e1 = nova_escola(db, um, "EMEF Inventada Um", None)
    _retratos(db, e1, turma_com_alunos(db, e1, "3º Ano", 8), [12] * 6 + [13, 13], [30] * 8)
    dois = nova_rede(db, nome="Rede Inventada Dois", codigo="3599984")
    e2 = nova_escola(db, dois, "EMEF Inventada Dois", None)
    _retratos(db, e2, turma_com_alunos(db, e2, "3º Ano", 10), [12] * 8 + [13, 13], [30] * 10)
    db.commit()
    redes = {r["nome"]: r for r in svc.dashboard_global(db)["redes"]}
    r1, r2 = redes["Rede Inventada Um"], redes["Rede Inventada Dois"]
    assert (r1["livros_por_matricula"], r2["livros_por_matricula"]) == (12.3, 12.2)
    assert (r1["pontuacao_leitura"], r2["pontuacao_leitura"]) == (1000.0, 995.9)
    assert (r1["posicao"], r2["posicao"]) == (1, 2)
