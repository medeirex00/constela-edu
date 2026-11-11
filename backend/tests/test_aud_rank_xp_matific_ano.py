"""O XP do ano letivo não usa o contador do Matific de OUTRO ano.

O Matific informa contadores DO ANO; o motor, o dashboard, o telão e as
premiações só aceitam retrato do ano letivo (`scoring.snapshots_matific_do_ano`).
O XP da gamificação (Ranking de XP da página Conquistas, ficha do aluno, perfil
público, Quest) usava o ÚLTIMO retrato de qualquer ano: antes da 1ª coleta do
ano novo, o XP de 2026 vinha do contador de dez/2025 — e a criança sem nenhum
dado de matemática em 2026 liderava o Ranking de XP. Achado RANKINGS-7.

Só a parte do XP que vem dos INDICADORES (atividades e estrelas) é recortada
pelo ano. A regra das CONQUISTAS de matemática (valem por ano ou pela vida
toda?) é decisão do dono e fica como está — o bônus delas entra no XP como
sempre. Dados fictícios.

O QUE AINDA NÃO ESTÁ RESOLVIDO (REV-RANK-2): a correção tira só a parte dos
indicadores. A criança que só tem o contador de dez/2025 continua com o bônus
das conquistas de matemática avaliadas naquele retrato (1.150 XP no exemplo, em
vez de 2.150) e continua podendo liderar o Ranking de XP de 2026 sem nenhum dado
de matemática em 2026. Isso só muda com a decisão do dono RANKINGS-7-conquistas;
``test_sem_dado_de_matematica_no_ano_nao_lidera_o_ranking_de_xp`` registra esse
efeito como falha conhecida (xfail estrito).
"""
from datetime import datetime

import pytest

from app.models import Importacao, SnapshotMatific
from app.services import gamificacao as svc_gami
from app.services import scoring

API = "/api/v1"


def _retrato(db, esc, imp, aluno, quando, atividades, estrelas):
    db.add(SnapshotMatific(escola_id=esc.id, aluno_id=aluno.id, importacao_id=imp.id,
                           data_referencia=quando, atividades=atividades,
                           estrelas=estrelas, pontuacao_media=3.0))


def test_xp_de_2026_nao_usa_o_contador_do_matific_de_2025(cliente, db, escola_completa):
    esc = escola_completa["escola"]          # ano letivo ativo: 2026
    ana, joao, _ = escola_completa["alunos"]
    imp = Importacao(escola_id=esc.id, plataforma="matific", tipo="seed")
    db.add(imp)
    db.flush()
    # Ana: só o acumulado de dez/2025 (nenhum retrato em 2026).
    _retrato(db, esc, imp, ana, datetime(2025, 12, 10), atividades=200, estrelas=600)
    # João: retrato de 2025 e o de 2026 — vale o contador de 2026.
    _retrato(db, esc, imp, joao, datetime(2025, 12, 10), atividades=90, estrelas=270)
    _retrato(db, esc, imp, joao, datetime(2026, 10, 10), atividades=30, estrelas=90)
    db.commit()
    scoring.recalcular_escola(db, esc.id)
    base = f"{API}/escolas/{esc.id}/gamificacao"

    r = cliente.get(f"{base}/ranking-xp")
    assert r.status_code == 200, r.text
    ranking = {i["aluno_id"]: i for i in r.json()}
    ficha_ana = cliente.get(f"{base}/alunos/{ana.id}").json()
    ficha_joao = cliente.get(f"{base}/alunos/{joao.id}").json()

    # Ana não tem contador do Matific em 2026: nenhum XP de atividades/estrelas.
    assert ficha_ana["xp"] == ficha_ana["xp_conquistas"], (
        f"XP de 2026 calculado com o contador do Matific de 2025: {ficha_ana['xp']} "
        f"(conquistas: {ficha_ana['xp_conquistas']})")
    assert ranking[ana.id]["xp"] == ficha_ana["xp"]
    # João: o contador de 2026 (30 atividades x 2 + 90 estrelas x 1 = 150 XP).
    assert ficha_joao["xp"] == 150 + ficha_joao["xp_conquistas"]
    assert ranking[joao.id]["xp"] == ficha_joao["xp"]
    # Ranking de XP e ficha dizem o mesmo nível.
    assert ranking[ana.id]["nivel"] == ficha_ana["nivel"]
    assert ranking[joao.id]["nivel"] == ficha_joao["nivel"]


def test_regra_das_conquistas_de_matematica_nao_muda(db, escola_completa):
    """A correção é só do XP dos indicadores: as conquistas de matemática seguem a
    regra de hoje (o último retrato), à espera da decisão do dono."""
    esc = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    imp = Importacao(escola_id=esc.id, plataforma="matific", tipo="seed")
    db.add(imp)
    db.flush()
    _retrato(db, esc, imp, ana, datetime(2025, 12, 10), atividades=200, estrelas=600)
    db.commit()
    ficha = svc_gami.gamificacao_do_aluno(db, esc.id, ana.id)
    atingidas = {c["codigo"] for c in ficha["conquistas"] if c["atingida"]}
    assert {"primeiro_desafio", "matematico_bronze", "matematico_prata",
            "matematico_ouro", "chuva_estrelas"} <= atingidas
    assert ficha["xp_conquistas"] == 50 + 100 + 250 + 500 + 250


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "Decisão do dono RANKINGS-7-conquistas: até ela, a criança que só tem o "
    "contador do Matific do ano anterior mantém o bônus de XP das conquistas de "
    "matemática avaliadas nele (1.150 XP aqui) e pode liderar o Ranking de XP do "
    "ano novo. Quando a regra das conquistas mudar, este teste passa e o xfail "
    "estrito quebra a suíte: tire o marcador."))
def test_sem_dado_de_matematica_no_ano_nao_lidera_o_ranking_de_xp(cliente, db,
                                                                  escola_completa):
    """O cenário do achado RANKINGS-7 (a sonda do auditor
    ``test_xp_de_2026_nao_usa_o_contador_de_2025``), que 46de969c NÃO resolve por
    inteiro: Ana só tem o acumulado de dez/2025 e nenhum dado de matemática em
    2026 para o motor; João tem 30 atividades em 2026."""
    esc = escola_completa["escola"]          # ano letivo ativo: 2026
    ana, joao, _ = escola_completa["alunos"]
    imp = Importacao(escola_id=esc.id, plataforma="matific", tipo="seed")
    db.add(imp)
    db.flush()
    _retrato(db, esc, imp, ana, datetime(2025, 12, 10), atividades=200, estrelas=600)
    _retrato(db, esc, imp, joao, datetime(2026, 10, 10), atividades=30, estrelas=90)
    db.commit()
    scoring.recalcular_escola(db, esc.id)
    base = f"{API}/escolas/{esc.id}"

    r_xp = cliente.get(f"{base}/gamificacao/ranking-xp")
    r_mat = cliente.get(f"{base}/ranking", params={"dimensao": "matematica"})
    # Pré-condições com pytest.fail (não AssertionError): se o cenário quebrar,
    # o teste FALHA de verdade em vez de passar como "falha conhecida".
    if r_xp.status_code != 200 or r_mat.status_code != 200:
        pytest.fail(f"rotas: {r_xp.status_code} {r_xp.text} | {r_mat.status_code} {r_mat.text}")
    if ana.id in {i["aluno_id"] for i in r_mat.json()}:
        pytest.fail("cenário inválido: o motor deu dado de matemática de 2026 à Ana")
    xp = {i["aluno_id"]: i for i in r_xp.json()}

    # O que deveria valer: sem dado de matemática no ano, nenhum XP de matemática
    # no ano e nada de 1º lugar no Ranking de XP.
    assert xp[ana.id]["xp"] == 0, (
        f"bônus das conquistas de 2025 no XP de 2026: {xp[ana.id]['xp']} XP")
    assert r_xp.json()[0]["aluno_id"] != ana.id, (
        "sem dado de matemática em 2026 e 1º no Ranking de XP")
