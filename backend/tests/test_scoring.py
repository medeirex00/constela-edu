"""Testes do motor de cálculo — a parte mais crítica do sistema."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models import (
    Aluno,
    Configuracao,
    DificuldadeTurma,
    Escola,
    Importacao,
    Matricula,
    NivelDificuldade,
    ReferenciaNormalizacao,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
)
from app.services import scoring


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")  # em memória
    Base.metadata.create_all(engine)
    sessao = sessionmaker(bind=engine)()
    yield sessao
    sessao.close()


def montar_escola(db, modo_referencia="manual"):
    escola = Escola(nome="ESCOLA TESTE", ano_letivo_ativo=2026)
    db.add(escola)
    db.flush()

    for namespace, valores in scoring.PESOS_PADRAO.items():
        db.add(Configuracao(escola_id=escola.id, namespace=namespace,
                            chave="valores", valor=valores))

    niveis = [
        NivelDificuldade(escola_id=escola.id, nome="Pré-Leitor",
                         codigos=["AA", "BB"], pontos_padrao=1.0, ordem=0),
        NivelDificuldade(escola_id=escola.id, nome="Nível 2",
                         codigos=["D", "E"], pontos_padrao=4.0, ordem=1),
    ]
    db.add_all(niveis)
    db.flush()

    referencias = ReferenciaNormalizacao(
        escola_id=escola.id,
        modo=modo_referencia,
        valores_manuais={
            "max_atividades": 100, "max_media": 100, "max_estrelas": 100,
            "max_livros": 10, "max_pontos_dificuldade": 20,
            "max_tentativas": 50, "max_acertos": 50, "max_tempo": 200,
        },
    )
    db.add(referencias)

    turma = Turma(escola_id=escola.id, nome="1º Ano A",
                  ano_escolar="1º Ano", ano_letivo=2026)
    db.add(turma)
    db.flush()

    importacao = Importacao(escola_id=escola.id, plataforma="matific", tipo="seed")
    db.add(importacao)
    db.flush()
    return escola, turma, importacao, niveis


def novo_aluno(db, escola, turma, nome):
    aluno = Aluno(escola_id=escola.id, nome=nome)
    db.add(aluno)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=aluno.id,
                     turma_id=turma.id, ano_letivo=2026))
    return aluno


# ---------------------------------------------------------------------------

def test_normalizacao_basica():
    assert scoring.normalizar(50, 100) == 50.0
    assert scoring.normalizar(0, 100) == 0.0
    assert scoring.normalizar(150, 100) == 100.0   # teto em 100
    assert scoring.normalizar(10, 0) == 0.0        # referência ausente


def test_pesos_defensivos_sempre_somam_um(db):
    """Mesmo com pesos inválidos no banco, o motor nunca gera nota > 100."""
    escola = Escola(nome="X", ano_letivo_ativo=2026)
    db.add(escola)
    db.flush()
    db.add(Configuracao(escola_id=escola.id, namespace="pesos.matific",
                        chave="valores",
                        valor={"atividades": 50, "media": 50, "estrelas": 100}))
    db.commit()
    pesos = scoring.obter_pesos(db, escola.id, "pesos.matific")
    assert pesos == {"atividades": 0.25, "media": 0.25, "estrelas": 0.5}
    assert abs(sum(pesos.values()) - 1.0) < 1e-9


def test_nota_matific_com_pesos_padrao(db):
    """PRD §33: normaliza, pondera (40/35/25) e soma."""
    escola, turma, importacao, _ = montar_escola(db)
    aluno = novo_aluno(db, escola, turma, "Aluno Único")
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id,
                           importacao_id=importacao.id,
                           atividades=100, pontuacao_media=80, estrelas=50))
    db.commit()

    scoring.recalcular_escola(db, escola.id)
    nota = db.query(scoring.Nota).filter_by(aluno_id=aluno.id).one()
    # 100*0.40 + 80*0.35 + 50*0.25 = 40 + 28 + 12.5
    assert nota.nota_matific == pytest.approx(80.5)
    assert nota.detalhes["matific"]["indicadores"][0]["contribuicao"] == pytest.approx(40.0)


def test_dificuldade_por_serie_sobrepoe_padrao(db):
    """PRD §39: o mesmo código pode valer pontos diferentes por série."""
    escola, turma, importacao, niveis = montar_escola(db)
    pre_leitor = niveis[0]
    # No 1º Ano, livros "AA"/"BB" valem 3 pontos em vez do padrão 1
    db.add(DificuldadeTurma(escola_id=escola.id, ano_escolar="1º Ano",
                            nivel_id=pre_leitor.id, pontos=3.0))
    aluno = novo_aluno(db, escola, turma, "Leitora")
    db.add(SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id,
                            importacao_id=importacao.id,
                            livros_unicos=3, livros_por_nivel={"AA": 2, "D": 1}))
    db.commit()

    scoring.recalcular_escola(db, escola.id)
    nota = db.query(scoring.Nota).filter_by(aluno_id=aluno.id).one()
    linhas = {l["indicador"]: l for l in nota.detalhes["elefante"]["indicadores"]}
    # 2 livros AA × 3 pts (override) + 1 livro D × 4 pts (padrão) = 10
    assert linhas["Pontos de dificuldade"]["valor"] == pytest.approx(10.0)


def test_livro_de_serie_diferente_usa_padrao(db):
    escola, turma, importacao, _ = montar_escola(db)
    aluno = novo_aluno(db, escola, turma, "Sem Override")
    db.add(SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id,
                            importacao_id=importacao.id,
                            livros_unicos=1, livros_por_nivel={"E": 2}))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    nota = db.query(scoring.Nota).filter_by(aluno_id=aluno.id).one()
    linhas = {l["indicador"]: l for l in nota.detalhes["elefante"]["indicadores"]}
    assert linhas["Pontos de dificuldade"]["valor"] == pytest.approx(8.0)  # 2 × 4


def test_desempate_segue_ordem_do_prd(db):
    """PRD §42: mesma nota geral → decide a maior nota do Elefante."""
    escola, turma, importacao, _ = montar_escola(db)
    forte_leitura = novo_aluno(db, escola, turma, "Zuleica")   # nome desfavorece
    forte_matific = novo_aluno(db, escola, turma, "Abel")      # nome favorece

    # Espelhados: mesmos números trocados entre módulos → mesma nota geral
    db.add_all([
        SnapshotMatific(escola_id=escola.id, aluno_id=forte_leitura.id,
                        importacao_id=importacao.id,
                        atividades=40, pontuacao_media=40, estrelas=40),
        SnapshotElefante(escola_id=escola.id, aluno_id=forte_leitura.id,
                         importacao_id=importacao.id,
                         livros_unicos=8, tempo_leitura_min=160,
                         questoes_tentativas=40, questoes_acertos=40,
                         livros_por_nivel={"D": 4}),
        SnapshotMatific(escola_id=escola.id, aluno_id=forte_matific.id,
                        importacao_id=importacao.id,
                        atividades=80, pontuacao_media=80, estrelas=80),
        SnapshotElefante(escola_id=escola.id, aluno_id=forte_matific.id,
                         importacao_id=importacao.id,
                         livros_unicos=4, tempo_leitura_min=80,
                         questoes_tentativas=20, questoes_acertos=20,
                         livros_por_nivel={"D": 2}),
    ])
    db.commit()

    scoring.recalcular_escola(db, escola.id)
    notas = {n.aluno_id: n for n in db.query(scoring.Nota).all()}
    assert notas[forte_leitura.id].nota_geral == pytest.approx(
        notas[forte_matific.id].nota_geral
    )
    # Empate na geral → vence quem tem maior nota no Elefante Letrado
    assert notas[forte_leitura.id].posicao == 1
    assert notas[forte_matific.id].posicao == 2


def test_recalculo_gera_ranking_completo_e_auditavel(db):
    escola, turma, importacao, _ = montar_escola(db, modo_referencia="auto")
    for indice in range(5):
        aluno = novo_aluno(db, escola, turma, f"Aluno {indice}")
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id,
                               importacao_id=importacao.id,
                               atividades=10 * (indice + 1),
                               pontuacao_media=60 + indice,
                               estrelas=20 * (indice + 1)))
    db.commit()

    total = scoring.recalcular_escola(db, escola.id)
    assert total == 5
    posicoes = sorted(n.posicao for n in db.query(scoring.Nota).all())
    assert posicoes == [1, 2, 3, 4, 5]
    melhor = db.query(scoring.Nota).filter_by(posicao=1).one()
    # Modo auto: quem tem os máximos da base normaliza em 100 em tudo
    assert melhor.nota_matific == pytest.approx(100.0)
    assert melhor.detalhes["modo_normalizacao"] == "auto"
    assert "referencias" in melhor.detalhes
