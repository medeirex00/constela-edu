"""DEC-19 (RANKINGS-4, legado) — criança sem NENHUM dado não ganha posição nem 0,0
no Ranking Geral.

O Ranking Geral legado (``GET /ranking`` sem ``dimensao``) e a aba "Ranking Geral"
do app (``/sincronizacao``) listavam, com posição e 0,0, quem tem Nota mas nenhum
retrato de plataforma — o mesmo defeito que o telão e o Top 10 já não têm
(``so_com_dado``). Decisão técnica da auditoria: o mesmo corte nas duas listas.
O retrato ZERADO (abriu a plataforma e não produziu) é um zero legítimo e
continua. Dados 100% fictícios.
"""
from datetime import datetime

from app.models import Importacao, SnapshotMatific
from app.services import scoring
from tests.test_permissoes import cenario_professor  # noqa: F401 — fixture

API = "/api/v1"


def _cenario(db, escola_completa):
    """Ana tem Matific com atividade; João não tem dado nenhum; Sofia tem retrato
    zerado (zero legítimo)."""
    escola = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]
    imp = Importacao(escola_id=escola.id, plataforma="matific", tipo="seed")
    db.add(imp)
    db.flush()
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=ana.id, importacao_id=imp.id,
                           data_referencia=datetime(2026, 10, 10), atividades=30,
                           estrelas=90, pontuacao_media=3.0))
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=sofia.id, importacao_id=imp.id,
                           data_referencia=datetime(2026, 10, 10), atividades=0,
                           estrelas=0, pontuacao_media=0.0))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    return escola, ana, joao, sofia


def test_ranking_geral_da_gestao_sem_quem_nao_tem_dado(db, escola_completa, cliente):
    escola, ana, joao, sofia = _cenario(db, escola_completa)
    itens = cliente.get(f"{API}/escolas/{escola.id}/ranking").json()
    ids = [i["aluno_id"] for i in itens]
    assert joao.id not in ids, itens
    # O zero legítimo continua (aferido, retrato zerado), na posição carimbada.
    assert ids == [ana.id, sofia.id]


def test_aba_ranking_geral_do_app_sem_quem_nao_tem_dado(db, escola_completa, cliente):
    escola, ana, joao, sofia = _cenario(db, escola_completa)
    pacote = cliente.get(f"{API}/escolas/{escola.id}/sincronizacao").json()
    ids = [i["aluno_id"] for i in pacote["ranking"]]
    assert ids == [ana.id, sofia.id], pacote["ranking"]


def test_professor_ranking_painel_e_app_dizem_a_mesma_posicao(
        cenario_professor, escola_completa, db):  # noqa: F811
    """Professor: o Ranking Geral dele é renumerado 1..N entre quem TEM dado, e o
    Top 10 do Painel (web e app) e a aba do app dizem a mesma posição."""
    c = cenario_professor
    escola, ana, joao, sofia = _cenario(db, escola_completa)
    base = f"{API}/escolas/{escola.id}"
    web = c["professor"].get(f"{base}/ranking").json()
    painel = c["professor"].get(f"{base}/dashboard").json()
    pacote = c["professor"].get(f"{base}/sincronizacao").json()
    pos_web = {i["aluno_id"]: i["posicao"] for i in web}
    assert pos_web == {ana.id: 1, sofia.id: 2}, pos_web
    assert {i["n_aferidos"] for i in web} == {2}
    assert {i["aluno_id"]: i["posicao"] for i in painel["top10"]} == pos_web
    assert {i["aluno_id"]: i["posicao"] for i in pacote["ranking"]} == pos_web
    assert {i["aluno_id"]: i["posicao"] for i in pacote["dashboard"]["top10"]} == pos_web


def test_ranking_por_dimensao_nao_muda(db, escola_completa, cliente):
    """Controle: o ranking POR DIMENSÃO já só lista os aferidos dela."""
    escola, ana, joao, sofia = _cenario(db, escola_completa)
    itens = cliente.get(f"{API}/escolas/{escola.id}/ranking",
                        params={"dimensao": "matematica"}).json()
    assert [i["aluno_id"] for i in itens] == [ana.id, sofia.id]
