"""PER CAPITA da rede sem as Fases — numerador E denominador.

O ranking da rede ordena por livros ÷ alunos e estrelas ÷ alunos. As médias da
rede já cortavam a Educação Infantil (PR #36), mas o per capita contava a
criança da Fase nos dois lados: os livros dela somavam no numerador e a
matrícula dela diluía o denominador. Uma escola com EMEI subia (ou caía) no
ranking do Fundamental por causa de quem não concorre.

A cobertura (``total_alunos``, adoção) continua sobre TODOS os matriculados.
"""
from app.models import (Aluno, Escola, Importacao, Matricula, Rede, SnapshotElefante,
                        SnapshotMatific, Turma)
from app.services import rede as svc


def _escola(db, rede, nome, fundamental, fase):
    """``fundamental`` / ``fase`` = lista de (livros, estrelas) por criança."""
    esc = Escola(nome=nome, ano_letivo_ativo=2026, rede_id=rede.id, status="ativa")
    db.add(esc)
    db.flush()
    imp = Importacao(escola_id=esc.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    for rotulo, criancas in (("3º Ano", fundamental), ("1ª Fase", fase)):
        turma = Turma(escola_id=esc.id, nome=f"{rotulo} A", ano_escolar=rotulo,
                      ano_letivo=2026, status="ativa")
        db.add(turma)
        db.flush()
        for i, (livros, estrelas) in enumerate(criancas):
            a = Aluno(escola_id=esc.id, nome=f"Aluno Teste {nome} {rotulo} {i}", status="ativo")
            db.add(a)
            db.flush()
            db.add(Matricula(escola_id=esc.id, aluno_id=a.id, turma_id=turma.id,
                             ano_letivo=2026))
            db.add(SnapshotElefante(escola_id=esc.id, aluno_id=a.id, importacao_id=imp.id,
                                    livros_unicos=livros, tempo_leitura_min=livros * 10))
            db.add(SnapshotMatific(escola_id=esc.id, aluno_id=a.id, importacao_id=imp.id,
                                   estrelas=estrelas, atividades=estrelas // 2))
    return esc


def test_fase_nao_entra_no_per_capita_nem_muda_a_ordem(db):
    rede = Rede(nome="Rede Teste Per Capita", status="ativa")
    db.add(rede)
    db.flush()
    # A: 2 do Fundamental com 10 livros + 3 da Fase sem leitura (diluiriam A).
    _escola(db, rede, "ESCOLA A", fundamental=[(10, 40), (10, 40)],
            fase=[(0, 0), (0, 0), (0, 0)])
    # B: 2 do Fundamental com 8 livros + 1 da Fase com 50 (inflaria B).
    _escola(db, rede, "ESCOLA B", fundamental=[(8, 30), (8, 30)], fase=[(50, 200)])
    db.commit()

    leitura = svc.ranking_escolas(db, rede.id, metrica="livros_aluno")
    por_nome = {c["nome"]: c for c in leitura}
    a, b = por_nome["ESCOLA A"], por_nome["ESCOLA B"]
    # Só quem concorre: A = 20 ÷ 2 = 10; B = 16 ÷ 2 = 8 → A à frente.
    # (Com a Fase: A = 20 ÷ 5 = 4 e B = 66 ÷ 3 = 22 — a ordem se invertia.)
    assert a["livros_por_matricula"] == 10.0 and b["livros_por_matricula"] == 8.0
    assert [c["nome"] for c in leitura] == ["ESCOLA A", "ESCOLA B"]
    assert a["estrelas_por_matricula"] == 40.0 and b["estrelas_por_matricula"] == 30.0
    # Transparência: o numerador e o denominador do per capita vão no cartão.
    assert (a["alunos_premiaveis"], a["livros_premiaveis"]) == (2, 20)
    assert (b["alunos_premiaveis"], b["livros_premiaveis"]) == (2, 16)
    # COBERTURA não muda: a Fase continua matriculada e contada.
    assert a["total_alunos"] == 5 and b["total_alunos"] == 3
    assert b["livros"] == 66 and b["ativos_elefante"] == 3


def test_escola_so_com_a_fase_usando_a_plataforma_nao_pontua(db):
    rede = Rede(nome="Rede Teste So Fase", status="ativa")
    db.add(rede)
    db.flush()
    _escola(db, rede, "ESCOLA COM FUNDAMENTAL", fundamental=[(5, 10)], fase=[])
    _escola(db, rede, "ESCOLA SO EMEI USA", fundamental=[], fase=[(30, 90)])
    db.commit()
    cartoes = {c["nome"]: c for c in svc._kpis_da_rede(db, rede.id)}
    so_emei = cartoes["ESCOLA SO EMEI USA"]
    assert so_emei["livros_por_matricula"] == 0.0
    # Fora da coorte do índice (ausência de quem concorre ≠ desempenho zero).
    assert "leitura" not in so_emei["dimensoes_pontuadas"]
    assert cartoes["ESCOLA COM FUNDAMENTAL"]["pontuacao_leitura"] == 1000.0
