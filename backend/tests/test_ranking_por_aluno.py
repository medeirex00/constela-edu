"""Item 1 — ranking de escolas POR ALUNO (per capita ÷ matrícula) é JUSTO entre
escolas de tamanhos diferentes: a escola pequena e densa supera a grande e esparsa,
ao contrário do ranking por VOLUME absoluto (que favorece a escola grande). É a
conta do dono: 40 livros ÷ 2 alunos = 20/aluno supera 60 livros ÷ 5 alunos = 12/aluno.
"""
from app.models import (
    Aluno,
    Escola,
    Importacao,
    Matricula,
    Nota,
    Rede,
    SnapshotElefante,
    Turma,
)
from app.services import rede as svc_rede


def _escola_com_livros(db, rede_id, nome, n_alunos, livros_cada):
    esc = Escola(nome=nome, ano_letivo_ativo=2026, rede_id=rede_id, status="ativa")
    db.add(esc)
    db.flush()
    turma = Turma(escola_id=esc.id, nome="1ºA", ano_escolar="1º Ano",
                  ano_letivo=2026, status="ativa")
    db.add(turma)
    db.flush()
    imp = Importacao(escola_id=esc.id, plataforma="elefante", tipo="seed")
    db.add(imp)
    db.flush()
    for i in range(n_alunos):
        a = Aluno(escola_id=esc.id, nome=f"Crianca {nome} {i}", status="ativo")
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=esc.id, aluno_id=a.id, turma_id=turma.id,
                         ano_letivo=2026))
        db.add(Nota(escola_id=esc.id, aluno_id=a.id, ano_letivo=2026,
                    nota_geral=70.0, nota_elefante=70.0, posicao=i + 1))
        db.add(SnapshotElefante(escola_id=esc.id, aluno_id=a.id,
                                importacao_id=imp.id, livros_unicos=livros_cada))
    return esc


def test_ranking_por_aluno_favorece_a_escola_densa(db):
    rede = Rede(nome="Rede Item1", status="ativa")
    db.add(rede)
    db.flush()
    _escola_com_livros(db, rede.id, "Escola Pequena", 2, 20)   # 40 livros, 20/aluno
    _escola_com_livros(db, rede.id, "Escola Grande", 5, 12)    # 60 livros, 12/aluno
    db.commit()

    # ABSOLUTO (metrica=livros): a Grande (60 livros) vem na frente.
    por_volume = svc_rede.ranking_escolas(db, rede.id, metrica="livros")
    assert por_volume[0]["nome"] == "Escola Grande"

    # POR ALUNO (metrica=livros_aluno, ÷ matrícula): a Pequena (20/aluno) supera a
    # Grande (12/aluno) — a comparação justa que o dono pediu.
    por_aluno = svc_rede.ranking_escolas(db, rede.id, metrica="livros_aluno")
    assert por_aluno[0]["nome"] == "Escola Pequena"

    pequena = next(c for c in por_aluno if c["nome"] == "Escola Pequena")
    grande = next(c for c in por_aluno if c["nome"] == "Escola Grande")
    assert pequena["livros_por_matricula"] == 20.0
    assert grande["livros_por_matricula"] == 12.0
    assert grande["livros"] > pequena["livros"]          # absoluto ainda favorece a grande
