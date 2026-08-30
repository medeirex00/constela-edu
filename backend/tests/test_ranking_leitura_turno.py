"""Competição escolar de leitura DIVIDIDA POR TURNO (Turma.turno).

Regras congeladas que estes testes travam:
  * dentro de um turno competem TODOS os alunos ativos do 1º ao 5º ano juntos;
  * a nota é a MESMA régua da escola (P90 da escola inteira, A3) — série, turma e
    turno NÃO entram na pontuação;
  * o turno só forma o grupo; a posição reinicia em 1 a cada turno;
  * turnos são descobertos do banco (nada de turma/série/turno hardcoded).
"""
from sqlalchemy import select

from app.models import (
    Aluno,
    Importacao,
    Matricula,
    Nota,
    SnapshotElefante,
    Turma,
)
from app.services import scoring

API = "/api/v1"


def _imp(db, escola_id):
    imp = Importacao(escola_id=escola_id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    return imp


def _turma(db, escola_id, nome, ano_escolar, turno):
    t = Turma(escola_id=escola_id, nome=nome, ano_escolar=ano_escolar,
              ano_letivo=2026, turno=turno, status="ativa")
    db.add(t)
    db.flush()
    return t


def _leitor(db, escola_id, imp, turma, nome, por_nivel, tempo=0, tent=0, acert=0):
    a = Aluno(escola_id=escola_id, nome=nome, status="ativo")
    db.add(a)
    db.flush()
    db.add(Matricula(escola_id=escola_id, aluno_id=a.id, turma_id=turma.id, ano_letivo=2026))
    db.add(SnapshotElefante(
        escola_id=escola_id, aluno_id=a.id, importacao_id=imp.id,
        livros_unicos=sum(por_nivel.values()), livros_por_nivel=dict(por_nivel),
        tempo_leitura_min=tempo, questoes_tentativas=tent, questoes_acertos=acert))
    return a


def _turnos(cliente, escola_id):
    r = cliente.get(f"{API}/escolas/{escola_id}/ranking/leitura/turnos")
    assert r.status_code == 200, r.text
    return r.json()


def _por_turno(resposta):
    return {g["turno"]: g for g in resposta}


def _nome_por_pos(grupo):
    return [a["nome"] for a in sorted(grupo["alunos"], key=lambda x: x["posicao"])]


# --------------------------------------------------------------------------

def test_um_turno_1o_ao_5o_juntos_e_series_nao_favorecem(cliente, db, escola_completa):
    """(item 5, 11.1, 11.2, 11.5, 11.14) 1º–5º no mesmo turno; engajamento decide,
    não a série; nota entre 0 e 100."""
    esc = escola_completa["escola"]
    imp = _imp(db, esc.id)
    manha = _turma(db, esc.id, "Única A", "vespertino_ignorado", "manha")
    # série NO nome da turma é irrelevante; uso o campo ano_escolar de propósito.
    t1 = _turma(db, esc.id, "1A", "1º Ano", "manha")
    t3 = _turma(db, esc.id, "3A", "3º Ano", "manha")
    t5 = _turma(db, esc.id, "5A", "5º Ano", "manha")
    _leitor(db, esc.id, imp, t1, "Um engajado (1o)", {"C": 25}, tempo=300, tent=40, acert=30)
    _leitor(db, esc.id, imp, t3, "Tres alto (3o)", {"H": 28}, tempo=380, tent=50, acert=38)
    _leitor(db, esc.id, imp, t5, "Cinco fraco (5o)", {"V": 2}, tempo=30, tent=4, acert=1)
    db.commit()
    scoring.recalcular_escola(db, esc.id)

    grupos = _por_turno(_turnos(cliente, esc.id))
    assert set(grupos) == {"manha"}          # um turno só (item 11.11)
    manha_g = grupos["manha"]
    notas = {a["nome"]: a["nota_elefante"] for a in manha_g["alunos"]}
    # todas as notas em [0, 100]
    assert all(0.0 <= n <= 100.0 for n in notas.values())
    # 1º e 3º engajados acima do 5º fraco
    assert notas["Um engajado (1o)"] > notas["Cinco fraco (5o)"]
    assert notas["Tres alto (3o)"] > notas["Cinco fraco (5o)"]
    # séries diferentes no MESMO ranking
    series = {a["ano_escolar"] for a in manha_g["alunos"]}
    assert {"1º Ano", "3º Ano", "5º Ano"} <= series


def test_serie_turma_turno_nao_alteram_a_nota(cliente, db, escola_completa):
    """(regra 2/3, item 11.3, 11.4) dois alunos com dados de leitura IDÊNTICOS têm
    a MESMA nota, independentemente de série, turma e turno."""
    esc = escola_completa["escola"]
    imp = _imp(db, esc.id)
    t_a = _turma(db, esc.id, "1A", "1º Ano", "manha")
    t_b = _turma(db, esc.id, "5B", "5º Ano", "tarde")
    dados = {"D": 8, "H": 4}
    _leitor(db, esc.id, imp, t_a, "Gemeo Manha 1o", dados, tempo=120, tent=20, acert=12)
    _leitor(db, esc.id, imp, t_b, "Gemeo Tarde 5o", dados, tempo=120, tent=20, acert=12)
    db.commit()
    scoring.recalcular_escola(db, esc.id)

    notas = {n.aluno_id: n.nota_elefante for n in db.execute(
        select(Nota).where(Nota.escola_id == esc.id)).scalars()
        if n.nota_elefante > 0}
    valores = set(round(v, 4) for v in notas.values())
    # os dois gêmeos (mesmos dados) => mesma nota, apesar de 1º/manhã vs 5º/tarde
    assert len(valores) == 1, f"séries/turnos diferentes mudaram a nota: {notas}"


def test_dois_turnos_isolados_e_posicao_reinicia(cliente, db, escola_completa):
    """(itens 6, 7, 8, 11.5, 11.6, 11.7, 11.8) manhã e tarde são rankings
    disjuntos; a posição reinicia em 1 em cada turno."""
    esc = escola_completa["escola"]
    imp = _imp(db, esc.id)
    # MANHÃ: 1A,1B,2A,2B,3A   TARDE: 3B,4A,4B,5A,5B  (composição arbitrária)
    for nome, serie in [("1A", "1º Ano"), ("1B", "1º Ano"), ("2A", "2º Ano"),
                        ("2B", "2º Ano"), ("3A", "3º Ano")]:
        t = _turma(db, esc.id, nome, serie, "manha")
        _leitor(db, esc.id, imp, t, f"M {nome}", {"F": 10 + len(nome)}, tempo=100)
    for nome, serie in [("3B", "3º Ano"), ("4A", "4º Ano"), ("4B", "4º Ano"),
                        ("5A", "5º Ano"), ("5B", "5º Ano")]:
        t = _turma(db, esc.id, nome, serie, "tarde")
        _leitor(db, esc.id, imp, t, f"T {nome}", {"J": 8 + len(nome)}, tempo=100)
    db.commit()
    scoring.recalcular_escola(db, esc.id)

    grupos = _por_turno(_turnos(cliente, esc.id))
    assert set(grupos) == {"manha", "tarde"}
    nomes_manha = {a["nome"] for a in grupos["manha"]["alunos"]}
    nomes_tarde = {a["nome"] for a in grupos["tarde"]["alunos"]}
    # isolamento total
    assert nomes_manha.isdisjoint(nomes_tarde)
    assert all(n.startswith("M ") for n in nomes_manha)
    assert all(n.startswith("T ") for n in nomes_tarde)
    # posição reinicia em 1 em cada turno
    for g in grupos.values():
        posicoes = sorted(a["posicao"] for a in g["alunos"])
        assert posicoes == list(range(1, len(posicoes) + 1))
    assert grupos["manha"]["total"] == 5 and grupos["tarde"]["total"] == 5


def test_mudar_turno_move_grupo_sem_mudar_nota(cliente, db, escola_completa):
    """(item 11.4, 11.13) alterar só o turno da turma move o aluno de ranking, mas
    a nota é a mesma."""
    esc = escola_completa["escola"]
    imp = _imp(db, esc.id)
    t = _turma(db, esc.id, "3A", "3º Ano", "manha")
    outra = _turma(db, esc.id, "3B", "3º Ano", "tarde")
    _leitor(db, esc.id, imp, t, "Movel", {"G": 12}, tempo=140, tent=18, acert=12)
    _leitor(db, esc.id, imp, outra, "Fixo Tarde", {"G": 6}, tempo=70)
    db.commit()
    scoring.recalcular_escola(db, esc.id)

    antes = _por_turno(_turnos(cliente, esc.id))
    assert "Movel" in {a["nome"] for a in antes["manha"]["alunos"]}
    nota_antes = next(a["nota_elefante"] for a in antes["manha"]["alunos"] if a["nome"] == "Movel")

    # muda SÓ o turno da turma do aluno
    t.turno = "tarde"
    db.commit()
    depois = _por_turno(_turnos(cliente, esc.id))
    assert "manha" not in depois  # a única turma de manhã virou tarde
    nota_depois = next(a["nota_elefante"] for a in depois["tarde"]["alunos"] if a["nome"] == "Movel")
    assert nota_depois == nota_antes  # turno não mexe na nota


def test_turnos_arbitrarios_descobertos_do_banco(cliente, db, escola_completa):
    """(itens 9, 10, 12, 11.9, 11.10, 11.12) turnos NÃO conhecidos previamente
    (ex.: 'integral', 'noite') funcionam; nada de turma/série hardcoded."""
    esc = escola_completa["escola"]
    imp = _imp(db, esc.id)
    for turno in ["manha", "tarde", "integral", "noite"]:
        t = _turma(db, esc.id, f"Turma-{turno}", "2º Ano", turno)
        _leitor(db, esc.id, imp, t, f"Aluno {turno}", {"E": 9}, tempo=100)
    db.commit()
    scoring.recalcular_escola(db, esc.id)

    grupos = _por_turno(_turnos(cliente, esc.id))
    assert set(grupos) == {"manha", "tarde", "integral", "noite"}
    # rótulo de apresentação vem formatado, mas o turno cru é a origem
    assert grupos["integral"]["turno_rotulo"] == "Integral"
    assert grupos["noite"]["turno_rotulo"] == "Noite"
    # cada turno tem exatamente o seu aluno
    for turno, g in grupos.items():
        assert [a["nome"] for a in g["alunos"]] == [f"Aluno {turno}"]


def test_turno_nulo_vira_grupo_sem_turno_isolado(cliente, db, escola_completa):
    """(itens 12, 17-NULL) turma com `Turma.turno = NULL` forma um grupo próprio
    'Sem turno' — o aluno NUNCA é colocado silenciosamente em Manhã/Tarde/etc."""
    esc = escola_completa["escola"]
    imp = _imp(db, esc.id)
    t_manha = _turma(db, esc.id, "3A", "3º Ano", "manha")
    t_nula = _turma(db, esc.id, "2A", "2º Ano", None)   # turno NULO
    _leitor(db, esc.id, imp, t_manha, "De Manha", {"G": 12}, tempo=140)
    _leitor(db, esc.id, imp, t_nula, "Sem Turno", {"F": 10}, tempo=110)
    db.commit()
    scoring.recalcular_escola(db, esc.id)

    grupos = _por_turno(_turnos(cliente, esc.id))
    assert "manha" in grupos and None in grupos
    # o aluno da turma sem turno está SÓ no grupo "Sem turno"
    assert [a["nome"] for a in grupos[None]["alunos"]] == ["Sem Turno"]
    assert grupos[None]["turno_rotulo"] == "Sem turno"
    assert "Sem Turno" not in {a["nome"] for a in grupos["manha"]["alunos"]}
    # e o grupo "Sem turno" tem sua própria posição 1..N
    assert grupos[None]["alunos"][0]["posicao"] == 1


def test_empate_deterministico(cliente, db, escola_completa):
    """(item 11.15) dois alunos com dados idênticos empatam e a ordem é estável
    entre chamadas, pelo desempate determinístico (…-> nome -> aluno.id)."""
    esc = escola_completa["escola"]
    imp = _imp(db, esc.id)
    t = _turma(db, esc.id, "3A", "3º Ano", "manha")
    _leitor(db, esc.id, imp, t, "Bruno", {"F": 10}, tempo=100, tent=10, acert=6)
    _leitor(db, esc.id, imp, t, "Ana", {"F": 10}, tempo=100, tent=10, acert=6)
    db.commit()
    scoring.recalcular_escola(db, esc.id)

    ordem1 = _nome_por_pos(_por_turno(_turnos(cliente, esc.id))["manha"])
    ordem2 = _nome_por_pos(_por_turno(_turnos(cliente, esc.id))["manha"])
    assert ordem1 == ordem2               # estável entre chamadas
    assert set(ordem1) == {"Ana", "Bruno"}
    # notas idênticas (empate real), desempate por nome (Ana antes de Bruno)
    g = _por_turno(_turnos(cliente, esc.id))["manha"]
    notas = {a["nome"]: a["nota_elefante"] for a in g["alunos"]}
    assert notas["Ana"] == notas["Bruno"]
    assert ordem1 == ["Ana", "Bruno"]
