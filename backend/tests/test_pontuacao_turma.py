"""Pontuação por nível LIVRE e configurável POR TURMA (PRD §39).

Cada turma pode valer pontos diferentes por nível de livro; turmas sem config
custom herdam o padrão da escola (comportamento preservado).
"""
from app.models import PontuacaoNivelTurma, Turma
from app.services import scoring


def _override(db, escola_id, turma_id, pontos):
    db.add(PontuacaoNivelTurma(escola_id=escola_id, turma_id=turma_id,
                               pontos_por_codigo=pontos))
    db.commit()


def test_mesmo_nivel_pontua_diferente_por_turma(db, escola_completa):
    """Lógica do dono: o MESMO nível de livro pode valer pontos DIFERENTES
    conforme a turma. 'Dificuldade por turma' é a fonte da pontuação FINAL;
    'Níveis de dificuldade' é só a referência/base (fallback de quem não
    configurou aquele código). Espelha o exemplo K=10 no 2ºB vs K=6 no 3ºB —
    aqui com o código "D" (referência/padrão = 4 na escola_completa)."""
    escola = escola_completa["escola"]
    turma_a = escola_completa["turma"]                        # já existe (3º Ano A)
    turma_b = Turma(escola_id=escola.id, nome="3º Ano B", ano_escolar="3º Ano",
                    ano_letivo=turma_a.ano_letivo, turno="tarde")
    turma_c = Turma(escola_id=escola.id, nome="3º Ano C", ano_escolar="3º Ano",
                    ano_letivo=turma_a.ano_letivo, turno="tarde")
    db.add_all([turma_b, turma_c])
    db.commit()

    # Dificuldade por turma: mesmo código "D" vale 10 no A e 6 no B; a turma C
    # não configura nada → cai na REFERÊNCIA dos Níveis (padrão = 4).
    _override(db, escola.id, turma_a.id, {"D": 10.0})
    _override(db, escola.id, turma_b.id, {"D": 6.0})

    mapa = scoring._mapa_dificuldade(db, escola.id)
    livro = {"D": 1}                                          # 1 livro nível D (Elefante)
    assert scoring._pontos_dificuldade(livro, "3º Ano", mapa, turma_id=turma_a.id) == 10.0
    assert scoring._pontos_dificuldade(livro, "3º Ano", mapa, turma_id=turma_b.id) == 6.0
    # Turma sem config → referência/base dos Níveis (NÃO some, NÃO vira a final universal).
    assert scoring._pontos_dificuldade(livro, "3º Ano", mapa, turma_id=turma_c.id) == 4.0


def test_pontos_por_codigo_padrao_e_por_turma(db, escola_completa):
    escola = escola_completa["escola"]
    turma = escola_completa["turma"]

    # Sem override: padrão da escola (AA/BB=1, D/E=4).
    padrao = scoring.pontos_por_codigo(db, escola.id)
    assert padrao == {"AA": 1.0, "BB": 1.0, "D": 4.0, "E": 4.0}
    # Sem override, com turma_id: continua o padrão.
    assert scoring.pontos_por_codigo(db, escola.id, turma.id) == padrao

    _override(db, escola.id, turma.id, {"AA": 10.0, "D": 20.0})
    por_turma = scoring.pontos_por_codigo(db, escola.id, turma.id)
    assert por_turma["AA"] == 10.0 and por_turma["D"] == 20.0     # override
    assert por_turma["BB"] == 1.0 and por_turma["E"] == 4.0       # herdou o padrão
    # A escola em geral (sem turma) NÃO muda.
    assert scoring.pontos_por_codigo(db, escola.id) == padrao


def test_mapa_pontos_turmas_e_dificuldade(db, escola_completa):
    escola = escola_completa["escola"]
    turma = escola_completa["turma"]
    _override(db, escola.id, turma.id, {"AA": 10.0})

    mapa = scoring.mapa_pontos_turmas(db, escola.id)
    assert mapa[None]["AA"] == 1.0                 # padrão
    assert mapa[turma.id]["AA"] == 10.0            # turma custom

    mapa_dif = scoring._mapa_dificuldade(db, escola.id)
    # 3 livros AA: com a turma custom = 30; sem turma = 3 (padrão).
    assert scoring._pontos_dificuldade({"AA": 3}, "3º Ano", mapa_dif, turma_id=turma.id) == 30.0
    assert scoring._pontos_dificuldade({"AA": 3}, "3º Ano", mapa_dif) == 3.0


def test_api_pontuacao_turma_crud(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    turma = escola_completa["turma"]
    base = f"/api/v1/escolas/{escola.id}/configuracoes/pontuacao-turma"

    # GET traz o catálogo (AA,BB,D,E) e a turma ainda sem override.
    r = cliente.get(base)
    assert r.status_code == 200
    corpo = r.json()
    assert {c["codigo"] for c in corpo["catalogo"]} == {"AA", "BB", "D", "E"}
    minha = next(t for t in corpo["turmas"] if t["turma_id"] == turma.id)
    assert minha["pontos"] == {}

    # PUT salva a tabela da turma.
    r = cliente.put(base, json={"turma_id": turma.id, "pontos": {"AA": 7, "D": 15}})
    assert r.status_code == 200
    assert r.json()["pontos"] == {"AA": 7.0, "D": 15.0}

    # GET reflete + o scoring já enxerga.
    r = cliente.get(base)
    minha = next(t for t in r.json()["turmas"] if t["turma_id"] == turma.id)
    assert minha["pontos"] == {"AA": 7.0, "D": 15.0}
    assert scoring.pontos_por_codigo(db, escola.id, turma.id)["AA"] == 7.0

    # Código inexistente → 400.
    r = cliente.put(base, json={"turma_id": turma.id, "pontos": {"ZZ": 3}})
    assert r.status_code == 400
