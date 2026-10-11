"""Consistência da pontuação — os cortes que a regra JÁ documentada exige.

Cada item abaixo é uma regra que o código já declarava num lugar e esquecia
noutro. Nenhuma regra nova: o mesmo corte, aplicado onde faltava.

1. AS FASES NÃO CONCORREM (``services.elegibilidade``, 1º–5º ano). O motor, a
   premiação, ``rankings._ranking`` e o painel público já cortavam; os rankings
   por PERÍODO (``/ranking/leitura``, ``/ranking/leitura/turnos`` e
   ``/ranking/matematica``) não — e eles são a base das premiações por período.

2. MATIFIC É CONTADOR DO ANO. ``/ranking/matematica`` e a premiação já só
   olhavam snapshots do ano letivo; o MOTOR tomava como "estado atual" o último
   snapshot de qualquer época, e um acumulado de dez/2025 virava a nota de
   Matemática de 2026 (e entrava na régua P90 de todo mundo). O Elefante NÃO
   recebe o corte: o contador dele é vitalício.

3. TETO DE 5 ESTRELAS POR ATIVIDADE: hoje só na premiação; aplicá-lo ao ranking
   de matemática por período é decisão do dono (nada muda aqui).

4. A MÉDIA DA REDE é do Fundamental I. A Nota antiga de uma criança da Educação
   Infantil (que o motor não atualiza mais) entrava em
   ``rede._medias_por_plataforma``. A cobertura (quem usa a plataforma) não muda.
"""
from datetime import date, datetime

import pytest
from sqlalchemy import select

from app.models import (
    Aluno,
    Importacao,
    Leitura,
    Livro,
    Matricula,
    Nota,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
)
from app.services import matific_destaque as md
from app.services import rede as svc_rede
from app.services import scoring

API = "/api/v1"


# --------------------------------------------------------------------------
# Fixtures locais
# --------------------------------------------------------------------------
def _imp(db, escola_id):
    imp = Importacao(escola_id=escola_id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    return imp


def _turma(db, escola, nome, ano_escolar, turno=None):
    t = Turma(escola_id=escola.id, nome=nome, ano_escolar=ano_escolar,
              ano_letivo=escola.ano_letivo_ativo, turno=turno, status="ativa")
    db.add(t)
    db.flush()
    return t


def _aluno(db, escola, turma, nome):
    a = Aluno(escola_id=escola.id, nome=nome, status="ativo")
    db.add(a)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=turma.id,
                     ano_letivo=turma.ano_letivo))
    db.flush()
    return a


def _snap_m(db, escola_id, imp, aluno_id, quando, atividades, estrelas):
    db.add(SnapshotMatific(
        escola_id=escola_id, aluno_id=aluno_id, importacao_id=imp.id,
        data_referencia=quando, atividades=atividades, estrelas=estrelas,
        pontuacao_media=round(estrelas / atividades, 2) if atividades else 0.0))


def _snap_e(db, escola_id, imp, aluno_id, quando, livros):
    db.add(SnapshotElefante(
        escola_id=escola_id, aluno_id=aluno_id, importacao_id=imp.id,
        data_referencia=quando, livros_unicos=livros,
        livros_por_nivel={"D": livros}, tempo_leitura_min=10 * livros))


def _ids(resposta):
    assert resposta.status_code == 200, resposta.text
    return {item["aluno_id"] for item in resposta.json()}


# --------------------------------------------------------------------------
# 1. As Fases não concorrem nos rankings por período
# --------------------------------------------------------------------------
def test_ranking_de_leitura_por_periodo_nao_lista_a_fase(cliente, db, escola_completa):
    """Os DOIS caminhos da rota: a leitura itemizada (com data) e, em "todo o
    histórico", o total do Elefante (snapshot). Uma criança da Fase em cada um
    — nenhuma pode aparecer, nem com volume maior que o do Fundamental."""
    escola = escola_completa["escola"]
    imp = _imp(db, escola.id)
    fund = _turma(db, escola, "4º Ano L", "4º Ano")
    emei = _turma(db, escola, "1ª Fase L", "1ª Fase")
    do_fund = _aluno(db, escola, fund, "LEITOR DO FUNDAMENTAL")
    fase_itemizada = _aluno(db, escola, emei, "FASE COM LEITURA DATADA")
    fase_snapshot = _aluno(db, escola, emei, "FASE SO COM SNAPSHOT")
    livros = [Livro(escola_id=escola.id, titulo=f"O Mapa Perdido {i}", nivel_codigo="D")
              for i in range(5)]
    db.add_all(livros)
    db.flush()
    for aluno, n in ((do_fund, 1), (fase_itemizada, 5)):
        for i in range(n):
            db.add(Leitura(escola_id=escola.id, aluno_id=aluno.id, livro_id=livros[i].id,
                           data=datetime(2026, 5, 10 + i), tempo_leitura_min=20,
                           nivel_codigo="D"))
    _snap_e(db, escola.id, imp, fase_snapshot.id, datetime(2026, 5, 20), 30)
    db.commit()

    url = f"{API}/escolas/{escola.id}/ranking/leitura"
    tudo = _ids(cliente.get(url))
    assert do_fund.id in tudo
    assert fase_itemizada.id not in tudo, "leitura datada da Fase não concorre"
    assert fase_snapshot.id not in tudo, "total do Elefante da Fase não concorre"

    recorte = _ids(cliente.get(url, params={
        "periodo": "personalizado", "inicio": "2026-05-01", "fim": "2026-05-31"}))
    assert recorte == {do_fund.id}
    # Posição sem buraco: o 1º do Fundamental continua sendo o 1º.
    assert cliente.get(url).json()[0]["aluno_id"] == do_fund.id


def test_ranking_de_leitura_por_turno_nao_lista_a_fase(cliente, db, escola_completa):
    """A Nota ANTIGA da Fase (o recálculo não apaga a linha de quem saiu da
    população) não pode voltar a disputar dentro do turno dela."""
    escola = escola_completa["escola"]
    fund = _turma(db, escola, "5º Ano T", "5º Ano", turno="manha")
    emei = _turma(db, escola, "2ª Fase T", "2ª Fase", turno="manha")
    do_fund = _aluno(db, escola, fund, "DO FUNDAMENTAL NO TURNO")
    da_fase = _aluno(db, escola, emei, "DA FASE NO TURNO")
    for aluno, nota, pos in ((do_fund, 40.0, 2), (da_fase, 99.0, 1)):
        db.add(Nota(escola_id=escola.id, aluno_id=aluno.id, ano_letivo=2026,
                    nota_elefante=nota, aferido_leitura=True, posicao_leitura=pos))
    db.commit()

    r = cliente.get(f"{API}/escolas/{escola.id}/ranking/leitura/turnos")
    assert r.status_code == 200, r.text
    manha = next(g for g in r.json() if g["turno"] == "manha")
    ids = [a["aluno_id"] for a in manha["alunos"]]
    assert da_fase.id not in ids
    assert ids == [do_fund.id]
    assert manha["alunos"][0]["posicao"] == 1
    assert manha["total"] == 1


def test_ranking_de_matematica_por_periodo_nao_lista_a_fase(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    imp = _imp(db, escola.id)
    fund = _turma(db, escola, "3º Ano M", "3º Ano")
    emei = _turma(db, escola, "1ª Fase M", "1ª Fase")
    do_fund = _aluno(db, escola, fund, "MATEMATICO DO FUNDAMENTAL")
    da_fase = _aluno(db, escola, emei, "MATEMATICO DA FASE")
    _snap_m(db, escola.id, imp, do_fund.id, datetime(2026, 5, 1), 10, 40)
    _snap_m(db, escola.id, imp, da_fase.id, datetime(2026, 5, 1), 80, 380)
    db.commit()

    ids = _ids(cliente.get(f"{API}/escolas/{escola.id}/ranking/matematica"))
    assert do_fund.id in ids
    assert da_fase.id not in ids, "a Fase não concorre, nem com mais estrelas"


# --------------------------------------------------------------------------
# 2. O motor só lê o Matific do ANO LETIVO (o Elefante, não)
# --------------------------------------------------------------------------
def _matematica(db, escola_id) -> dict[int, tuple]:
    db.expire_all()
    return {n.aluno_id: (n.nota_matific, n.nota_matific_institucional,
                         n.aferido_matematica, n.posicao_matematica,
                         (n.detalhes or {}).get("dimensoes", {}).get("matematica"))
            for n in db.execute(select(Nota).where(Nota.escola_id == escola_id)).scalars()}


def test_motor_ignora_matific_de_outro_ano_e_nada_muda_para_quem_tem_coleta_no_ano(
        db, escola_completa):
    """Ana e João têm coleta em 2026; Sofia só em dez/2025.

    * Sofia NÃO é aferida em Matemática (ausência no ano, não zero) — e o
      acumulado dela, enorme, não entra na régua P90 dos outros;
    * Ana e João ficam EXATAMENTE como estariam sem a coleta velha da Sofia;
    * coleta de outro ano de quem já tem coleta no ano não muda nada (nem a de
      2025, anterior, nem uma de 2027, posterior à virada)."""
    escola = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]
    imp = _imp(db, escola.id)
    _snap_m(db, escola.id, imp, ana.id, datetime(2026, 3, 1), 50, 120)
    _snap_m(db, escola.id, imp, joao.id, datetime(2026, 4, 1), 10, 20)
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    referencia = _matematica(db, escola.id)
    assert referencia[ana.id][2] is True and referencia[joao.id][2] is True

    # Coleta de dez/2025 da Sofia (contador do ano anterior, maior que tudo).
    _snap_m(db, escola.id, imp, sofia.id, datetime(2025, 12, 15), 300, 1400)
    # Coletas fora do ano para quem JÁ tem coleta no ano.
    _snap_m(db, escola.id, imp, joao.id, datetime(2025, 11, 30), 900, 4000)
    _snap_m(db, escola.id, imp, ana.id, datetime(2027, 1, 20), 2, 8)
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    depois = _matematica(db, escola.id)

    assert depois[ana.id] == referencia[ana.id]
    assert depois[joao.id] == referencia[joao.id]
    nota_sofia, inst_sofia, aferida, posicao, _ = depois[sofia.id]
    assert aferida is False, "coleta só do ano anterior não afere Matemática"
    assert posicao is None
    assert nota_sofia == 0.0 and inst_sofia == 0.0


def test_estado_atual_do_matific_no_motor_e_o_ultimo_snapshot_do_ano(db, escola_completa):
    """A janela vale ANTES de escolher o "último": quem tem 2026 e 2027 é
    medido pelo de 2026; quem só tem coleta dentro do ano não muda nada."""
    escola = escola_completa["escola"]
    ana, joao, _ = escola_completa["alunos"]
    imp = _imp(db, escola.id)
    _snap_m(db, escola.id, imp, ana.id, datetime(2026, 9, 1), 40, 150)
    _snap_m(db, escola.id, imp, ana.id, datetime(2027, 1, 5), 3, 10)
    _snap_m(db, escola.id, imp, joao.id, datetime(2026, 2, 1), 5, 10)
    _snap_m(db, escola.id, imp, joao.id, datetime(2026, 8, 1), 25, 90)
    db.commit()

    janela = md.janela_ano_letivo(2026)
    do_ano = scoring._snapshots_atuais(db, escola.id, SnapshotMatific, janela=janela)
    assert do_ano[ana.id].atividades == 40
    assert do_ano[joao.id].atividades == 25
    # Sem janela, o comportamento de sempre (último de qualquer época).
    sem_janela = scoring._snapshots_atuais(db, escola.id, SnapshotMatific)
    assert sem_janela[ana.id].atividades == 3
    assert sem_janela[joao.id].id == do_ano[joao.id].id


def test_elefante_e_vitalicio_e_nao_recebe_o_corte_do_ano(db, escola_completa):
    escola = escola_completa["escola"]
    _, _, sofia = escola_completa["alunos"]
    imp = _imp(db, escola.id)
    _snap_e(db, escola.id, imp, sofia.id, datetime(2025, 11, 30), 12)
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    db.expire_all()
    nota = db.execute(select(Nota).where(Nota.aluno_id == sofia.id)).scalars().one()
    assert nota.aferido_leitura is True
    assert nota.nota_elefante > 0


# --------------------------------------------------------------------------
# 4. A média da rede é do Fundamental I
# --------------------------------------------------------------------------
def test_media_da_rede_nao_inclui_a_nota_antiga_da_fase(db, escola_completa):
    escola = escola_completa["escola"]
    ana, joao, _ = escola_completa["alunos"]
    imp = _imp(db, escola.id)
    _snap_e(db, escola.id, imp, ana.id, datetime(2026, 5, 1), 10)
    _snap_e(db, escola.id, imp, joao.id, datetime(2026, 5, 1), 4)
    db.commit()
    scoring.recalcular_escola(db, escola.id)

    def _media():
        return svc_rede._medias_por_plataforma(
            db, [escola.id], SnapshotElefante, Nota.nota_elefante_institucional)[escola.id]

    referencia = _media()
    assert referencia[0] == 2

    # A Nota ANTIGA, carimbada, de uma criança da Fase que tem dado do Elefante:
    # exatamente o que o motor deixa para trás quando a tira da população.
    emei = _turma(db, escola, "1ª Fase R", "1ª Fase")
    da_fase = _aluno(db, escola, emei, "NOTA CONGELADA DA FASE")
    da_fase.data_nascimento = date(2021, 2, 2)
    _snap_e(db, escola.id, imp, da_fase.id, datetime(2026, 5, 1), 40)
    db.add(Nota(escola_id=escola.id, aluno_id=da_fase.id, ano_letivo=2026,
                nota_elefante=100.0, nota_elefante_institucional=100.0,
                aferido_leitura=True, detalhes=scoring.carimbo_institucional()))
    db.commit()

    assert _media() == referencia, "a Fase não compõe o desempenho da rede"
    # Cobertura NÃO muda: a criança segue matriculada e usando a plataforma.
    assert svc_rede._alunos_com_qualquer_dado(db, [escola.id])[escola.id] == 3



# --------------------------------------------------------------------------
# 2 + 4. Quem faz MÉDIA decide "aferido" e "concorre" como o motor
# --------------------------------------------------------------------------
# Se o motor deixa a criança de fora (Matific só do ano anterior, ou turma da
# Fase) e a média a conta, ela entra como o 0,0 que o motor gravou — ou com a
# nota congelada que ninguém recalcula. Painel da rede, dashboard da escola,
# resumo de turma/escola e comparador têm de usar a MESMA definição.
def _desempenho_dashboard(db, escola):
    from app.routers.rankings import _desempenho_da_escola
    return _desempenho_da_escola(db, escola.id, escola.ano_letivo_ativo,
                                 scoring.dimensoes_contratadas(db, escola), None)


def test_matific_so_do_ano_anterior_nao_vira_zero_em_nenhuma_media(db, escola_completa):
    from app.services import evolucao

    escola = escola_completa["escola"]
    turma = escola_completa["turma"]
    ana, joao, sofia = escola_completa["alunos"]
    imp = _imp(db, escola.id)
    _snap_m(db, escola.id, imp, ana.id, datetime(2026, 3, 1), 50, 120)
    _snap_m(db, escola.id, imp, joao.id, datetime(2026, 4, 1), 10, 20)
    _snap_m(db, escola.id, imp, sofia.id, datetime(2025, 12, 15), 300, 1400)
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    db.expire_all()
    notas = {n.aluno_id: n for n in db.execute(
        select(Nota).where(Nota.escola_id == escola.id)).scalars()}
    assert notas[sofia.id].aferido_matematica is False
    esperado_inst = (notas[ana.id].nota_matific_institucional
                     + notas[joao.id].nota_matific_institucional) / 2
    esperado_local = (notas[ana.id].nota_matific + notas[joao.id].nota_matific) / 2

    # Painel da rede.
    n, media = svc_rede._medias_por_plataforma(
        db, [escola.id], SnapshotMatific, Nota.nota_matific_institucional)[escola.id]
    assert n == 2
    assert media == pytest.approx(esperado_inst)

    # Dashboard da escola: o desempenho corta; o ALCANCE (cobertura) não.
    painel = _desempenho_dashboard(db, escola)
    assert painel["n_matematica"] == 2
    assert painel["media_matematica"] == round(esperado_local, 1)
    assert painel["com_dados"] == 3

    # Resumo da turma (e o lado "turma" do comparador, que sai dele).
    resumo = evolucao.resumo_turma(db, escola.id, turma.id)
    assert resumo["n_matematica"] == 2
    assert resumo["media_matematica"] == round(esperado_local, 2)
    assert resumo["adocao_matematica"] == 100.0, "cobertura: os três usam o Matific"
    turma_escola = next(t for t in evolucao.resumo_escola(db, escola.id)["turmas"]
                        if t["turma"]["id"] == turma.id)
    assert turma_escola["n_matematica"] == 2
    assert turma_escola["media_matematica"] == resumo["media_matematica"]
    lado_turma = evolucao._lado_turma(db, escola.id, turma.id)
    assert lado_turma["dimensoes"]["matematica"]["n_aferidos"] == 2

    # Comparador: a Sofia aparece SEM DADO em Matemática, não com 0,0.
    sofia_lado = evolucao._lado_aluno(db, escola.id, sofia.id)["dimensoes"]["matematica"]
    assert sofia_lado["aferido"] is False
    assert sofia_lado["nota"] is None
    ana_lado = evolucao._lado_aluno(db, escola.id, ana.id)["dimensoes"]["matematica"]
    assert ana_lado["aferido"] is True
    lado_escola = evolucao._lado_escola(db, escola.id)
    assert lado_escola["dimensoes"]["matematica"]["n_aferidos"] == 2
    assert lado_escola["dimensoes"]["matematica"]["nota"] == round(esperado_local, 1)


def test_fase_fica_fora_do_desempenho_da_escola_em_todas_as_telas(db, escola_completa):
    """O dashboard da escola e o lado "escola" do comparador prometem o MESMO
    número do cartão da escola no painel da rede. Com o corte só na rede, a
    Nota congelada da Fase separava os três."""
    from app.services import evolucao

    escola = escola_completa["escola"]
    ana, joao, _ = escola_completa["alunos"]
    imp = _imp(db, escola.id)
    _snap_e(db, escola.id, imp, ana.id, datetime(2026, 5, 1), 10)
    _snap_e(db, escola.id, imp, joao.id, datetime(2026, 5, 1), 4)
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    antes_painel = _desempenho_dashboard(db, escola)
    antes_lado = evolucao._lado_escola(db, escola.id)["dimensoes"]["leitura"]

    emei = _turma(db, escola, "1ª Fase D", "1ª Fase")
    da_fase = _aluno(db, escola, emei, "NOTA CONGELADA DA FASE D")
    _snap_e(db, escola.id, imp, da_fase.id, datetime(2026, 5, 1), 40)
    db.add(Nota(escola_id=escola.id, aluno_id=da_fase.id, ano_letivo=2026,
                nota_elefante=100.0, nota_elefante_institucional=100.0,
                aferido_leitura=True, detalhes=scoring.carimbo_institucional()))
    db.commit()

    painel = _desempenho_dashboard(db, escola)
    assert painel["n_leitura"] == antes_painel["n_leitura"] == 2
    assert painel["media_leitura"] == antes_painel["media_leitura"]
    assert painel["com_dados"] == antes_painel["com_dados"] + 1, "alcance é cobertura"
    lado = evolucao._lado_escola(db, escola.id)
    assert lado["dimensoes"]["leitura"] == antes_lado
    assert lado["total_alunos"] == 4
    n_rede, _ = svc_rede._medias_por_plataforma(
        db, [escola.id], SnapshotElefante, Nota.nota_elefante_institucional)[escola.id]
    assert n_rede == painel["n_leitura"] == lado["dimensoes"]["leitura"]["n_aferidos"]
