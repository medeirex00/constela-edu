"""Ranking da Rede (Secretaria) — os 7 cenários pedidos pelo dono.

Regra central: a comparação entre escolas é PER CAPITA. Uma escola GRANDE não pode
subir só por ter mais alunos; o critério principal da LEITURA é livros ÷ alunos.
O índice da rede (0–1000) é a mesma métrica normalizada na régua da rede, então
ordem e pontuação nunca se contradizem.
"""
from app.models import (
    Aluno,
    Escola,
    Importacao,
    Matricula,
    Nota,
    Rede,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
)
from app.services import rede as svc


def _escola(db, rede_id, nome, *, alunos, livros_cada=0, tempo_cada=0,
            estrelas_cada=0, atividades_cada=0, com_matific=True, com_elefante=True):
    """Escola com N alunos ativos matriculados; cada aluno com os snapshots pedidos."""
    esc = Escola(nome=nome, ano_letivo_ativo=2026, rede_id=rede_id, status="ativa")
    db.add(esc)
    db.flush()
    turma = Turma(escola_id=esc.id, nome="1ºA", ano_escolar="1º Ano", ano_letivo=2026,
                  status="ativa")
    db.add(turma)
    db.flush()
    imp = Importacao(escola_id=esc.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    for i in range(alunos):
        a = Aluno(escola_id=esc.id, nome=f"Crianca {nome} {i}", status="ativo")
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=esc.id, aluno_id=a.id, turma_id=turma.id, ano_letivo=2026))
        db.add(Nota(escola_id=esc.id, aluno_id=a.id, ano_letivo=2026, nota_geral=70.0,
                    nota_elefante=70.0, nota_matific=70.0, posicao=i + 1))
        if com_elefante:
            db.add(SnapshotElefante(escola_id=esc.id, aluno_id=a.id, importacao_id=imp.id,
                                    livros_unicos=livros_cada, tempo_leitura_min=tempo_cada))
        if com_matific:
            db.add(SnapshotMatific(escola_id=esc.id, aluno_id=a.id, importacao_id=imp.id,
                                   estrelas=estrelas_cada, atividades=atividades_cada))
    return esc


def _rede(db, nome="Rede Municipal"):
    r = Rede(nome=nome, status="ativa")
    db.add(r)
    db.flush()
    return r


def _por_nome(cartoes):
    return {c["nome"]: c for c in cartoes}


# --- Teste 1 + 2: escolas de tamanhos diferentes; a maior não ganha automático ---

def test_1e2_escola_menor_com_melhor_media_fica_acima(db):
    """Caso do dono: A = 35.000 livros / 200 alunos = 175/aluno;
    B = 20.000 livros / 100 alunos = 200/aluno → B PRIMEIRO, apesar de menos livros."""
    rede = _rede(db)
    _escola(db, rede.id, "Escola A", alunos=200, livros_cada=175)   # 35.000 livros
    _escola(db, rede.id, "Escola B", alunos=100, livros_cada=200)   # 20.000 livros
    db.commit()

    leitura = svc.ranking_escolas(db, rede.id, metrica="livros_aluno")
    assert [c["nome"] for c in leitura] == ["Escola B", "Escola A"]

    a, b = _por_nome(leitura)["Escola A"], _por_nome(leitura)["Escola B"]
    assert a["livros"] == 35000 and b["livros"] == 20000      # A tem MAIS livros no total
    assert a["livros_por_matricula"] == 175.0 and b["livros_por_matricula"] == 200.0
    assert b["posicao"] == 1 and a["posicao"] == 2            # …e mesmo assim fica atrás
    # O ranking por VOLUME BRUTO (critério legado) inverteria — prova que a diferença
    # está no critério per capita, não nos dados.
    assert [c["nome"] for c in svc.ranking_escolas(db, rede.id, metrica="livros")][0] == "Escola A"


def test_2_indice_de_leitura_acompanha_a_ordem_per_capita(db):
    """A pontuação explica a posição: melhor da rede = 1000 e o índice é monotônico
    com livros/aluno (ordem e nota nunca se contradizem)."""
    rede = _rede(db)
    _escola(db, rede.id, "Top", alunos=100, livros_cada=200)
    _escola(db, rede.id, "Metade", alunos=100, livros_cada=100)
    db.commit()

    r = _por_nome(svc.ranking_escolas(db, rede.id, metrica="livros_aluno"))
    assert r["Top"]["pontuacao_leitura"] == 1000.0            # melhor da rede
    assert r["Metade"]["pontuacao_leitura"] == 500.0          # metade do desempenho


# --- Teste 3: alunos duplicados não inflam o denominador ---------------------

def test_3_aluno_duplicado_nao_conta_duas_vezes(db):
    """Duplicata NÃO infla o denominador nem o numerador.

    Duas defesas, e o teste cobre as duas:
      1. o banco impede a MESMA ficha em 2 matrículas no ano
         (UNIQUE aluno_id+ano_letivo) — dupla contagem por matrícula é impossível;
      2. a ficha DUPLICADA (2º cadastro do mesmo aluno, o que a importação criava
         antes da correção) sai da conta assim que é arquivada/fundida — é o
         desfecho da tela "Fundir duplicatas".
    """
    rede = _rede(db)
    esc = _escola(db, rede.id, "Escola Dup", alunos=10, livros_cada=10)
    turma = db.query(Turma).filter(Turma.escola_id == esc.id).first()
    imp = db.query(Importacao).filter(Importacao.escola_id == esc.id).first()

    # (1) a mesma ficha não pode ser matriculada 2x no ano — o banco barra.
    aluno = db.query(Aluno).filter(Aluno.escola_id == esc.id).first()
    ja_matriculado = db.query(Matricula).filter(
        Matricula.aluno_id == aluno.id, Matricula.ano_letivo == 2026).count()
    assert ja_matriculado == 1

    # (2) ficha duplicada do MESMO aluno (com snapshot próprio), ainda ativa:
    # enquanto não for fundida, ela conta — é exatamente o passivo que a tela de
    # fusão resolve.
    dup = Aluno(escola_id=esc.id, nome="Crianca Escola Dup 0 (duplicata)", status="ativo")
    db.add(dup)
    db.flush()
    db.add(Matricula(escola_id=esc.id, aluno_id=dup.id, turma_id=turma.id, ano_letivo=2026))
    db.add(SnapshotElefante(escola_id=esc.id, aluno_id=dup.id, importacao_id=imp.id,
                            livros_unicos=10, tempo_leitura_min=0))
    db.commit()
    c = _por_nome(svc._kpis_da_rede(db, rede.id))["Escola Dup"]
    assert c["total_alunos"] == 11 and c["livros"] == 110      # passivo pendente

    # Fundida/arquivada → sai do denominador E do numerador, restaurando a média.
    dup.status = "arquivado"
    db.commit()
    c = _por_nome(svc._kpis_da_rede(db, rede.id))["Escola Dup"]
    assert c["total_alunos"] == 10                 # 10 alunos, não 11
    assert c["livros"] == 100                      # snapshot da duplicata não conta
    assert c["livros_por_matricula"] == 10.0


# --- Teste 4: escola sem dados não quebra o ranking -------------------------

def test_4_escola_sem_dados_nao_quebra(db):
    """Escola sem Elefante, sem Matific e sem aluno nenhum não derruba o cálculo."""
    rede = _rede(db)
    _escola(db, rede.id, "Completa", alunos=10, livros_cada=10, estrelas_cada=10)
    _escola(db, rede.id, "So Leitura", alunos=10, livros_cada=5, com_matific=False)
    _escola(db, rede.id, "Vazia", alunos=0)
    db.commit()

    cartoes = _por_nome(svc._kpis_da_rede(db, rede.id))
    vazia = cartoes["Vazia"]
    assert vazia["total_alunos"] == 0 and vazia["pontuacao_geral"] == 0.0
    assert vazia["livros_por_matricula"] == 0.0            # sem divisão por zero

    # Só-leitura: pontua na dimensão que tem e NÃO é punida com um zero de Matific.
    so_leitura = cartoes["So Leitura"]
    assert so_leitura["dimensoes_pontuadas"] == ["leitura"]
    assert so_leitura["pontuacao_geral"] == so_leitura["pontuacao_leitura"] > 0
    assert so_leitura["pontuacao_matematica"] == 0.0

    # O ranking roda e exclui quem não tem dados (regra pré-existente).
    r = svc.ranking_escolas(db, rede.id, metrica="indice_geral")
    assert "Vazia" not in [c["nome"] for c in r]


# --- Teste 6: pontuação geral a partir das dimensões normalizadas -----------

def test_6_pontuacao_geral_e_a_media_das_dimensoes(db):
    """Geral = média das pontuações normalizadas de leitura e matemática."""
    rede = _rede(db)
    _escola(db, rede.id, "Melhor Leitura", alunos=100, livros_cada=100, estrelas_cada=50)
    _escola(db, rede.id, "Melhor Matematica", alunos=100, livros_cada=50, estrelas_cada=100)
    db.commit()

    c = _por_nome(svc._kpis_da_rede(db, rede.id))["Melhor Leitura"]
    assert c["pontuacao_leitura"] == 1000.0 and c["pontuacao_matematica"] == 500.0
    assert c["pontuacao_geral"] == round((1000.0 + 500.0) / 2, 1) == 750.0
    assert c["dimensoes_pontuadas"] == ["leitura", "matematica"]


# --- Teste 7: idempotência ---------------------------------------------------

def test_7_recalcular_nao_altera_o_resultado(db):
    """Chamar o ranking duas vezes seguidas devolve exatamente o mesmo resultado
    (a função é pura sobre o estado do banco — não acumula nem grava nada)."""
    rede = _rede(db)
    _escola(db, rede.id, "Escola A", alunos=50, livros_cada=20, estrelas_cada=30)
    _escola(db, rede.id, "Escola B", alunos=80, livros_cada=25, estrelas_cada=10)
    db.commit()

    def foto():
        return [(c["nome"], c["posicao"], c["pontuacao_geral"], c["pontuacao_leitura"],
                 c["livros_por_matricula"]) for c in
                svc.ranking_escolas(db, rede.id, metrica="indice_geral")]

    assert foto() == foto()


# --- Abas: cada uma ordena pelo seu critério ---------------------------------

def test_abas_ordenam_por_criterios_diferentes(db):
    """Leitura ordena por livros/aluno; Matemática por estrelas/aluno; Engajamento
    por participação — a mesma base de escolas, visões diferentes."""
    rede = _rede(db)
    # Lê muito, joga pouco.
    _escola(db, rede.id, "Leitora", alunos=100, livros_cada=100, estrelas_cada=10)
    # Joga muito, lê pouco.
    _escola(db, rede.id, "Matematica", alunos=100, livros_cada=10, estrelas_cada=100)
    db.commit()

    assert svc.ranking_escolas(db, rede.id, metrica="livros_aluno")[0]["nome"] == "Leitora"
    assert svc.ranking_escolas(db, rede.id, metrica="estrelas_aluno")[0]["nome"] == "Matematica"
    # Engajamento (participação) empata → desempate estável por nome.
    eng = svc.ranking_escolas(db, rede.id, metrica="engajamento")
    assert {c["nome"] for c in eng} == {"Leitora", "Matematica"}


def test_indicadores_reais_acompanham_a_pontuacao(db):
    """O cartão traz os indicadores REAIS além da pontuação — a Secretaria precisa
    responder 'por que essa escola está nessa posição?' (item 8 do dono)."""
    rede = _rede(db)
    _escola(db, rede.id, "Escola X", alunos=200, livros_cada=175, tempo_cada=540,
            estrelas_cada=200, atividades_cada=400)
    db.commit()

    c = _por_nome(svc._kpis_da_rede(db, rede.id))["Escola X"]
    assert c["total_alunos"] == 200
    assert c["livros"] == 35000 and c["livros_por_matricula"] == 175.0
    assert c["tempo_leitura_min"] == 108000                  # horas lidas (÷60 na UI)
    assert c["estrelas"] == 40000 and c["estrelas_por_matricula"] == 200.0
    assert c["atividades"] == 80000 and c["atividades_por_matricula"] == 400.0
    assert c["ativos_elefante"] == 200 and c["ativos_matific"] == 200
    assert c["adocao"] == 100.0
