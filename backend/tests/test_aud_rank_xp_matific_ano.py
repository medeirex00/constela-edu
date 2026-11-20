"""Ranking de XP, regra de 2026 e virada para XP do ano letivo em 2027.

Matific parte de zero no ano novo. Elefante traz contadores vitalícios e o
ganho é medido entre retratos. Conquistas da ficha permanecem no histórico.
Todos os dados são fictícios.
"""
from datetime import datetime

from app.models import Importacao, Matricula, SnapshotElefante, SnapshotMatific, Turma
from app.services import gamificacao as svc_gami
from app.services import scoring
from app.services.evolucao import IMPORTACAO_SEM_QUESTOES

API = "/api/v1"


def _retrato(db, esc, imp, aluno, quando, atividades, estrelas):
    db.add(SnapshotMatific(escola_id=esc.id, aluno_id=aluno.id, importacao_id=imp.id,
                           data_referencia=quando, atividades=atividades,
                           estrelas=estrelas, pontuacao_media=3.0))


def _virar_para_2027(db, escola, alunos):
    turma = Turma(escola_id=escola.id, nome="4º Ano A", ano_escolar="4º Ano", ano_letivo=2027)
    db.add(turma)
    db.flush()
    for aluno in alunos:
        db.add(Matricula(escola_id=escola.id, aluno_id=aluno.id, turma_id=turma.id, ano_letivo=2027))
    escola.ano_letivo_ativo = 2027
    db.commit()


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


def test_regra_das_conquistas_de_matematica_em_2026_nao_muda(db, escola_completa):
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


def test_virada_para_2027_separa_xp_do_ano_e_conquistas_historicas(cliente, db, escola_completa):
    esc = escola_completa["escola"]
    alunos = escola_completa["alunos"]
    ana, joao, _ = alunos
    imp = Importacao(escola_id=esc.id, plataforma="matific", tipo="seed")
    db.add(imp)
    db.flush()
    _retrato(db, esc, imp, ana, datetime(2026, 12, 10), atividades=200, estrelas=600)
    db.commit()
    base = f"{API}/escolas/{esc.id}/gamificacao"
    r_2026 = cliente.get(f"{base}/ranking-xp")
    assert r_2026.status_code == 200, r_2026.text
    assert r_2026.json()[0]["aluno_id"] == ana.id
    assert r_2026.json()[0]["xp"] == 2_150

    _virar_para_2027(db, esc, alunos)
    _retrato(db, esc, imp, joao, datetime(2027, 1, 10), atividades=30, estrelas=90)
    _retrato(db, esc, imp, joao, datetime(2028, 1, 1), atividades=200, estrelas=600)
    db.commit()
    scoring.recalcular_escola(db, esc.id)
    r_2027 = cliente.get(f"{base}/ranking-xp")
    assert r_2027.status_code == 200, r_2027.text
    xp = {item["aluno_id"]: item for item in r_2027.json()}
    assert xp[ana.id]["xp"] == 0
    assert xp[ana.id]["conquistas"] == 0
    assert (xp[joao.id]["posicao"], xp[joao.id]["xp"], xp[joao.id]["nivel"]) == (1, 300, 4)
    assert xp[joao.id]["conquistas"] == 2

    # Repetir o limiar de uma conquista antiga no ano novo não paga outro bônus.
    _retrato(db, esc, imp, ana, datetime(2027, 1, 11), atividades=10, estrelas=30)
    db.commit()
    r_2027 = cliente.get(f"{base}/ranking-xp")
    assert r_2027.status_code == 200, r_2027.text
    xp_ana = next(item for item in r_2027.json() if item["aluno_id"] == ana.id)
    assert (xp_ana["xp"], xp_ana["conquistas"]) == (50, 0)

    ficha = cliente.get(f"{base}/alunos/{ana.id}")
    assert ficha.status_code == 200, ficha.text
    assert ficha.json()["xp_conquistas"] == 1_150
    assert ficha.json()["xp"] == 1_200
    ouro = next(c for c in ficha.json()["conquistas"] if c["codigo"] == "matematico_ouro")
    assert ouro["atingida"]
    assert ouro["data"].startswith("2026-12-10")


def test_ranking_2027_soma_so_ganho_medido_do_elefante_e_conquista_nova(cliente, db, escola_completa):
    esc = escola_completa["escola"]
    alunos = escola_completa["alunos"]
    ana, joao, sofia = alunos
    _virar_para_2027(db, esc, alunos)
    imp = Importacao(escola_id=esc.id, plataforma="elefante", tipo="seed")
    imp_sem_questoes = Importacao(escola_id=esc.id, plataforma="elefante", tipo="seed",
                                  status=IMPORTACAO_SEM_QUESTOES)
    db.add_all([imp, imp_sem_questoes])
    db.flush()

    def _leitura(aluno, quando, livros, minutos, acertos, tentativas, importacao=imp):
        db.add(SnapshotElefante(escola_id=esc.id, aluno_id=aluno.id, importacao_id=importacao.id,
                                data_referencia=quando, livros_unicos=livros, tempo_leitura_min=minutos,
                                questoes_acertos=acertos, questoes_tentativas=tentativas))

    _leitura(ana, datetime(2026, 12, 31, 23, 59), 9, 200, 12, 20)
    _leitura(ana, datetime(2027, 1, 10), 11, 210, 16, 25)
    # A próxima coleta mediu livros, mas não mediu questões. Não é borda de questões.
    _leitura(ana, datetime(2027, 1, 11), 11, 210, 40, 40, imp_sem_questoes)
    _leitura(joao, datetime(2026, 12, 31), 30, 120, 20, 30)
    # A primeira coleta da Sofia trouxe um acumulado sem data. Só o ganho observado depois conta.
    _leitura(sofia, datetime(2027, 1, 10), 30, 600, 20, 25)
    _leitura(sofia, datetime(2027, 1, 11), 32, 610, 24, 30)
    db.commit()
    r = cliente.get(f"{API}/escolas/{esc.id}/gamificacao/ranking-xp")
    assert r.status_code == 200, r.text
    xp = {item["aluno_id"]: item for item in r.json()}
    assert (xp[ana.id]["xp"], xp[ana.id]["conquistas"]) == (134, 1)  # 20 + 2 + 12 + 100
    assert (xp[joao.id]["xp"], xp[joao.id]["conquistas"]) == (0, 0)
    assert (xp[sofia.id]["xp"], xp[sofia.id]["conquistas"]) == (34, 0)
