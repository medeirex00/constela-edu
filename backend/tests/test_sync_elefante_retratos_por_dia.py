"""Investigação A2 §3.18: "2ª coleta do Elefante no mesmo dia, sem mudança,
acrescenta 3 retratos" (e92 ``test_11a``: série 6 → 9 → 9 → 15).

CAUSA (medida aqui, retrato por aluno e por dia de Brasília): a coleta do
Elefante grava dois arquivos por turma — o RESUMO (relatório de turma) e as
LEITURAS (livros com data). O resumo reescreve no lugar o retrato do mesmo dia
(``_importar_elefante_resumo``), mas ``_importar_elefante_leituras`` sempre
EMPILHAVA um retrato novo, sem olhar o dia. As leituras só vêm para quem o
cursor manda buscar, então:

  1ª coleta (sem cursor, completa)      resumo + leituras → 2 retratos/aluno
  2ª (recoleta completa: nunca marcada) leituras de todos → +1 retrato/aluno
  3ª (incremental, nada mudou)          sem leituras      → +0
  dia seguinte (completa de novo)       resumo + leituras → +2 retratos/aluno

(medido antes da correção com 2 alunos: 4 → 6 → 6, isto é, 3 retratos por aluno
no mesmo dia; com os 3 alunos do e92, 6 → 9 → 9 → 15.)

Era empilhamento indevido: o retrato que as leituras gravam é o MESMO retrato
do dia (só ``livros_unicos``/``tempo`` pelo máximo e a distribuição por nível
recontada das Leituras; as questões são copiadas do retrato atual), e o estado
atual é sempre o mais recente. A correção é idempotente: no mesmo dia de
Brasília as leituras atualizam o retrato do dia no lugar (só quando algo muda),
como o resumo e o Matific já faziam. Núcleo, notas e retrato atual iguais.
Dados 100% fictícios; conector real com navegador falso; sem rede.
"""
from collections import Counter

from sqlalchemy import select, text

from app.core.tempo import para_br
from app.models import Nota
from app.models.plataformas import SnapshotElefante
from tests._sync_nucleo_fakes import (NavElefante, aluno_el, contagens, credencial, instalar,
                                      livro, rodar, snap_atual)

NUCLEO = ("alunos", "matriculas", "turmas", "identidades", "leituras", "eventos", "livros",
          "notas", "revisoes")


def _turmas(a, b, *, sem_data=True):
    livros_a = [livro("Livro Ficticio Um"),
                livro("Livro Ficticio Dois", "E", "2026-09-10T10:00:00"),
                livro("Livro Ficticio Um", data="2026-09-20T09:15:00")]       # releitura
    if sem_data:
        livros_a.append(livro("Livro Ficticio Tres", data=None))   # a origem do e92
    return {511434: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
        aluno_el(9100001, a.nome, livros_a),
        aluno_el(9100002, b.nome, [livro("Livro Ficticio Dois", "E", "2026-09-05T08:00:00")])]}}


def _retratos_por_aluno_e_dia(db, eid):
    """{(aluno_id, dia de Brasília): quantos retratos do Elefante}."""
    return Counter(
        (aid, para_br(ref).date()) for aid, ref in db.execute(
            select(SnapshotElefante.aluno_id, SnapshotElefante.data_referencia)
            .where(SnapshotElefante.escola_id == eid)).all())


def _estado(db, eid, alunos):
    notas = sorted((n.aluno_id, round(n.nota_elefante or 0, 6))
                   for n in db.execute(select(Nota).where(Nota.escola_id == eid)).scalars())
    atuais = []
    for x in alunos:
        s = snap_atual(db, SnapshotElefante, x.id)
        atuais.append((x.id, s.livros_unicos, s.tempo_leitura_min, s.questoes_tentativas,
                       s.questoes_acertos, dict(s.livros_por_nivel or {})))
    return notas, atuais


def _envelhecer_um_dia(db):
    db.execute(text("UPDATE snapshots_elefante SET data_referencia = :d"),
               {"d": "2026-10-20 15:00:00"})
    db.execute(text("DELETE FROM configuracoes WHERE chave LIKE '%ultima_coleta_completa%'"))
    db.commit()


def test_repetir_a_coleta_no_mesmo_dia_nao_empilha_retrato(db, escola_completa, monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    a, b, _c = ec["alunos"]
    credencial(db, eid, "elefante")
    nav = NavElefante(_turmas(a, b))
    instalar(monkeypatch, nav_elefante=nav)

    medidas = []
    for _ in range(3):
        ex, _ = rodar(db, eid, "elefante")
        medidas.append((ex.status, contagens(db, eid), _retratos_por_aluno_e_dia(db, eid),
                        _estado(db, eid, (a, b)), len(nav.lotes)))
    # as leituras vieram nas duas primeiras (sem cursor; recoleta completa) e não na 3ª
    assert [m[4] for m in medidas] == [1, 2, 2]
    assert [m[0] for m in medidas][1:] == ["sem_atualizacao", "sem_atualizacao"]
    assert [m[1]["snap_el"] for m in medidas] == [2, 2, 2], [   # antes: 4 → 6 → 6
        (m[1]["snap_el"], sorted(m[2].values())) for m in medidas]
    for _s, _c, por_dia, _e, _l in medidas:
        assert set(por_dia.values()) == {1}, por_dia          # 1 retrato por aluno e dia
    for k in NUCLEO:
        assert len({m[1][k] for m in medidas}) == 1, k
    assert len({repr(m[3]) for m in medidas}) == 1             # notas e retrato atual iguais

    # dia seguinte: a recoleta completa grava UM retrato novo por aluno, no dia novo
    estado_antes = medidas[-1][3]
    _envelhecer_um_dia(db)
    ex, _ = rodar(db, eid, "elefante")
    por_dia = _retratos_por_aluno_e_dia(db, eid)
    assert set(por_dia.values()) == {1}, por_dia
    assert contagens(db, eid)["snap_el"] == 4                  # antes: 10
    assert sorted(Counter(aid for aid, _d in por_dia).values()) == [2, 2]
    notas, atuais = _estado(db, eid, (a, b))
    assert (notas, atuais) == estado_antes


def test_leituras_no_mesmo_dia_atualizam_o_retrato_e_preservam_as_questoes(
        db, escola_completa, monkeypatch):
    """Livro novo no mesmo dia: o retrato do dia passa a contá-lo (no lugar) e as
    questões do resumo continuam as do resumo — nada se perde, nada empilha."""
    ec = escola_completa
    eid = ec["escola"].id
    a, b, _c = ec["alunos"]
    credencial(db, eid, "elefante")
    turmas = _turmas(a, b, sem_data=False)
    instalar(monkeypatch, nav_elefante=NavElefante(turmas))
    rodar(db, eid, "elefante")
    antes = snap_atual(db, SnapshotElefante, b.id)
    questoes = (antes.questoes_tentativas, antes.questoes_acertos)
    livros_antes = antes.livros_unicos

    b_el = turmas[511434]["alunos"][1]
    b_el["livros"].append(livro("Livro Ficticio Quatro", "F", "2026-10-01T10:00:00"))
    b_el["total"] = len(b_el["livros"])
    ex, _ = rodar(db, eid, "elefante")
    assert ex.status == "concluida"
    por_dia = _retratos_por_aluno_e_dia(db, eid)
    assert set(por_dia.values()) == {1}, por_dia
    depois = snap_atual(db, SnapshotElefante, b.id)
    assert depois.livros_unicos == livros_antes + 1
    assert (depois.questoes_tentativas, depois.questoes_acertos) == questoes
    assert sum((depois.livros_por_nivel or {}).values()) == depois.livros_unicos
