"""C-01 — a Nota Geral renormaliza sobre as dimensões DISPONÍVEIS do aluno.

O defeito: ``nota_geral`` era a média ponderada FIXA das duas plataformas, então
a ausência de dado entrava como ZERO e criava um **teto de 50** para quem usa uma
plataforma só. A criança que leu 30 livros (nota_elefante 100) ficava com 50 e
perdia posição, prêmio e certificado para quem leu 10 e também usou o Matific —
o Ranking Geral ordenava por ADESÃO, não por desempenho.

A correção é a MESMA regra que a escola já aplicava ("só quem tem dado da
plataforma entra na média", ``rede._medias_por_plataforma``), agora no ALUNO:
dimensão sem dado sai da conta e o peso é redistribuído entre as que sobraram.

O que estes testes travam:
  * quem usa as DUAS plataformas continua com a nota de antes, bit a bit;
  * quem usa uma só é avaliado pelo que fez, sem o teto de 50;
  * o corte é pela EXISTÊNCIA do snapshot, nunca por ``nota > 0`` (zero de quem
    usa a plataforma é um zero legítimo e continua pesando);
  * a explicação gravada em ``detalhes.geral`` reproduz a nota (auditabilidade);
  * a cascata com os MÓDULOS CONTRATADOS (contrato primeiro, dado depois) não
    duplica conceito nem quebra a rede de um módulo só.
"""
import pytest

from app.models import (
    Aluno,
    Configuracao,
    Escola,
    Importacao,
    Matricula,
    NivelDificuldade,
    Nota,
    Rede,
    ReferenciaNormalizacao,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
)
from app.services import modulos as svc_modulos
from app.services import scoring

# --- Perfis de aluno usados nos cenários -------------------------------------
# LEITOR: 30 livros de nível 4 (120 pontos de dificuldade), 100 questões certas.
# MEDIANO: um terço disso na leitura, mas com o Matific no máximo.
LEITOR_ELEFANTE = {"livros_unicos": 30, "tempo_leitura_min": 600,
                   "questoes_tentativas": 100, "questoes_acertos": 100,
                   "livros_por_nivel": {"D": 30}}
MEDIANO_ELEFANTE = {"livros_unicos": 10, "tempo_leitura_min": 200,
                    "questoes_tentativas": 40, "questoes_acertos": 40,
                    "livros_por_nivel": {"D": 10}}
MATIFIC_TOPO = {"atividades": 100, "pontuacao_media": 100.0, "estrelas": 100}


def montar_escola(db, *, com_rede=False):
    """Escola com os pesos padrão (geral 50/50) e referência AUTO."""
    rede = None
    if com_rede:
        rede = Rede(nome="Rede C01", status="ativa")
        db.add(rede)
        db.flush()
    escola = Escola(nome="EM C01", ano_letivo_ativo=2026, status="ativa",
                    rede_id=rede.id if rede else None)
    db.add(escola)
    db.flush()
    for namespace, valores in scoring.PESOS_PADRAO.items():
        db.add(Configuracao(escola_id=escola.id, namespace=namespace,
                            chave="valores", valor=valores))
    db.add(NivelDificuldade(escola_id=escola.id, nome="Nível 2", codigo="nivel_2",
                            codigos=["D", "E"], pontos_padrao=4.0, ordem=1))
    db.add(ReferenciaNormalizacao(escola_id=escola.id, modo="auto"))
    turma = Turma(escola_id=escola.id, nome="1ºA", ano_escolar="1º Ano",
                  ano_letivo=2026, status="ativa")
    db.add(turma)
    db.flush()
    importacao = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed")
    db.add(importacao)
    db.flush()
    return rede, escola, turma, importacao


def novo_aluno(db, escola, turma, importacao, nome, *, elefante=None, matific=None):
    aluno = Aluno(escola_id=escola.id, nome=nome, status="ativo")
    db.add(aluno)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=aluno.id, turma_id=turma.id,
                     ano_letivo=2026))
    if elefante is not None:
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id,
                                importacao_id=importacao.id, **elefante))
    if matific is not None:
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id,
                               importacao_id=importacao.id, **matific))
    return aluno


def notas_por_id(db, escola_id):
    return {n.aluno_id: n for n in db.query(Nota).filter(Nota.escola_id == escola_id)}


def conferir_explicacao(nota: Nota):
    """A conta EXIBIDA em ``detalhes.geral.pesos`` reproduz a nota gravada."""
    pesos = nota.detalhes["geral"]["pesos"]
    assert sum(pesos.values()) == pytest.approx(100.0, abs=0.01), (
        f"os percentuais exibidos precisam somar 100%: {pesos}")
    conta = sum((nota.nota_matific if chave == "matific" else nota.nota_elefante)
                * (pct / 100) for chave, pct in pesos.items())
    assert conta == pytest.approx(nota.nota_geral, abs=0.05), (
        f"a explicação {pesos} dá {conta:.2f}, mas a nota gravada é {nota.nota_geral}")


# --- O TESTE QUE IMPORTA ------------------------------------------------------

def test_leitor_excelente_de_uma_plataforma_nao_fica_atras_de_mediano_de_duas(db):
    """O cenário da auditoria, com o motor real: 12 alunos, escola 50/50.

    Seis leram 30 livros e não usam o Matific (nota_elefante 100); seis leram 10
    e usam o Matific. Antes, os leitores ficavam com **50,0** e caíam para as
    posições 7–12: quem lê 3× mais ficava em último. É a criança real perdendo
    prêmio hoje, no piloto."""
    _, escola, turma, imp = montar_escola(db)
    leitores = [novo_aluno(db, escola, turma, imp, f"Leitora {i}",
                           elefante=dict(LEITOR_ELEFANTE)) for i in range(6)]
    medianos = [novo_aluno(db, escola, turma, imp, f"Mediano {i}",
                           elefante=dict(MEDIANO_ELEFANTE),
                           matific=dict(MATIFIC_TOPO)) for i in range(6)]
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    notas = notas_por_id(db, escola.id)

    leitor, mediano = notas[leitores[0].id], notas[medianos[0].id]
    # A régua de cada plataforma NÃO mudou: o leitor é 100 na leitura.
    assert leitor.nota_elefante == pytest.approx(100.0, abs=0.01)
    assert leitor.nota_matific == 0.0                      # ausência, não desempenho
    assert mediano.nota_elefante < leitor.nota_elefante

    # A ausência de Matific não vale mais zero: a geral do leitor é a leitura.
    assert leitor.nota_geral == pytest.approx(leitor.nota_elefante, abs=0.01)
    assert leitor.nota_geral > mediano.nota_geral
    assert {notas[a.id].posicao for a in leitores} == {1, 2, 3, 4, 5, 6}
    assert {notas[a.id].posicao for a in medianos} == {7, 8, 9, 10, 11, 12}
    for n in notas.values():
        conferir_explicacao(n)


# --- Cenários de disponibilidade ---------------------------------------------

def test_aluno_com_as_duas_plataformas_mantem_a_nota_bit_a_bit(db):
    """Blindagem: com as duas dimensões disponíveis a renormalização é no-op —
    a conta continua sendo 50/50 e os pesos exibidos, 50 e 50."""
    _, escola, turma, imp = montar_escola(db)
    alunos = [novo_aluno(db, escola, turma, imp, f"Ambas {i}",
                         elefante={**MEDIANO_ELEFANTE, "livros_unicos": 5 + i},
                         matific={**MATIFIC_TOPO, "atividades": 20 + i})
              for i in range(10)]
    db.commit()
    scoring.recalcular_escola(db, escola.id)

    for aluno in alunos:
        n = notas_por_id(db, escola.id)[aluno.id]
        assert n.nota_geral == pytest.approx(
            round(n.nota_matific * 0.5 + n.nota_elefante * 0.5, 2), abs=0.01)
        assert n.detalhes["geral"]["pesos"] == {"matific": 50.0, "elefante": 50.0}
        assert n.detalhes["geral"]["dimensoes_com_dados"] == ["elefante", "matific"]


def test_so_elefante_a_geral_e_a_nota_de_leitura(db):
    _, escola, turma, imp = montar_escola(db)
    aluno = novo_aluno(db, escola, turma, imp, "Só Leitura",
                       elefante=dict(LEITOR_ELEFANTE))
    for i in range(9):   # coorte para a régua robusta existir
        novo_aluno(db, escola, turma, imp, f"Colega {i}",
                   elefante=dict(MEDIANO_ELEFANTE))
    db.commit()
    scoring.recalcular_escola(db, escola.id)

    n = notas_por_id(db, escola.id)[aluno.id]
    assert n.nota_geral == pytest.approx(n.nota_elefante, abs=0.01)
    assert n.detalhes["geral"]["pesos"] == {"elefante": 100.0}
    assert n.detalhes["geral"]["dimensoes_com_dados"] == ["elefante"]
    conferir_explicacao(n)


def test_so_matific_a_geral_e_a_nota_de_matematica(db):
    _, escola, turma, imp = montar_escola(db)
    aluno = novo_aluno(db, escola, turma, imp, "Só Matemática",
                       matific=dict(MATIFIC_TOPO))
    for i in range(9):
        novo_aluno(db, escola, turma, imp, f"Colega {i}",
                   matific={"atividades": 20, "pontuacao_media": 50.0, "estrelas": 20})
    db.commit()
    scoring.recalcular_escola(db, escola.id)

    n = notas_por_id(db, escola.id)[aluno.id]
    assert n.nota_geral == pytest.approx(n.nota_matific, abs=0.01)
    assert n.detalhes["geral"]["pesos"] == {"matific": 100.0}
    assert n.detalhes["geral"]["dimensoes_com_dados"] == ["matific"]
    conferir_explicacao(n)


def test_aluno_sem_nenhuma_plataforma_fica_zero_com_explicacao_coerente(db):
    """Sem NENHUMA dimensão disponível não há o que renormalizar: a nota é 0 (não
    é injustiça, é ausência total de dado) e a explicação continua fechando."""
    _, escola, turma, imp = montar_escola(db)
    sem_dado = novo_aluno(db, escola, turma, imp, "Sem Dado")
    novo_aluno(db, escola, turma, imp, "Com Dado", elefante=dict(LEITOR_ELEFANTE),
               matific=dict(MATIFIC_TOPO))
    db.commit()
    scoring.recalcular_escola(db, escola.id)

    n = notas_por_id(db, escola.id)[sem_dado.id]
    assert (n.nota_geral, n.nota_elefante, n.nota_matific) == (0.0, 0.0, 0.0)
    assert n.detalhes["geral"]["dimensoes_com_dados"] == []
    conferir_explicacao(n)                       # 0 × 50% + 0 × 50% = 0


def test_zero_de_quem_usa_a_plataforma_continua_pesando(db):
    """O corte é pela EXISTÊNCIA do snapshot, NUNCA por ``nota > 0``. Um aluno
    que abriu o Elefante e ainda não leu nada tem um zero LEGÍTIMO: ele NÃO pode
    ser promovido a 'só Matific' e ganhar do colega que usa as duas e lê."""
    _, escola, turma, imp = montar_escola(db)
    zerado = novo_aluno(db, escola, turma, imp, "Abriu E Nao Leu",
                        elefante={"livros_unicos": 0, "tempo_leitura_min": 0,
                                  "questoes_tentativas": 0, "questoes_acertos": 0,
                                  "livros_por_nivel": {}},
                        matific=dict(MATIFIC_TOPO))
    esforcado = novo_aluno(db, escola, turma, imp, "Usa As Duas E Le",
                           elefante=dict(MEDIANO_ELEFANTE), matific=dict(MATIFIC_TOPO))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    notas = notas_por_id(db, escola.id)

    assert notas[zerado.id].nota_elefante == 0.0
    # A dimensão EXISTE (há snapshot), então entra na conta com o seu zero.
    assert notas[zerado.id].detalhes["geral"]["dimensoes_com_dados"] == [
        "elefante", "matific"]
    assert notas[zerado.id].nota_geral < notas[esforcado.id].nota_geral
    assert notas[esforcado.id].posicao == 1


# --- Escola inteira em uma plataforma só -------------------------------------

def test_escola_so_elefante_nao_tem_teto_de_50(db):
    """Escola que só usa o Elefante: TODAS as notas gerais são a nota de leitura
    (antes, a escola inteira era comprimida no intervalo 0–50)."""
    _, escola, turma, imp = montar_escola(db)
    alunos = [novo_aluno(db, escola, turma, imp, f"Aluno {i}",
                         elefante={**MEDIANO_ELEFANTE, "livros_unicos": 2 + i * 3,
                                   "livros_por_nivel": {"D": 2 + i * 3}})
              for i in range(10)]
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    notas = notas_por_id(db, escola.id)

    assert max(n.nota_geral for n in notas.values()) > 50.0
    for aluno in alunos:
        n = notas[aluno.id]
        assert n.nota_geral == pytest.approx(n.nota_elefante, abs=0.01)
    # A ORDEM interna (quem lê mais vem antes) continua a mesma.
    assert notas[alunos[-1].id].posicao == 1


def test_escola_so_matific_nao_tem_teto_de_50(db):
    _, escola, turma, imp = montar_escola(db)
    alunos = [novo_aluno(db, escola, turma, imp, f"Aluno {i}",
                         matific={"atividades": 10 + i * 10,
                                  "pontuacao_media": 50.0 + i,
                                  "estrelas": 10 + i * 10})
              for i in range(10)]
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    notas = notas_por_id(db, escola.id)

    assert max(n.nota_geral for n in notas.values()) > 50.0
    for aluno in alunos:
        assert notas[aluno.id].nota_geral == pytest.approx(
            notas[aluno.id].nota_matific, abs=0.01)
    assert notas[alunos[-1].id].posicao == 1


# --- Cascata com os MÓDULOS CONTRATADOS (dois cortes, nunca duplicados) ------

def test_modulo_desativado_manda_no_contrato_e_o_dado_manda_dentro_dele(db):
    """Rede que só contratou LEITURA: o Matific sai da conta pelo CONTRATO, para
    todo mundo, mesmo para quem tem snapshot dele. A renormalização por dado não
    pode reintroduzi-lo nem produzir uma conta que não fecha."""
    rede, escola, turma, imp = montar_escola(db, com_rede=True)
    ambas = novo_aluno(db, escola, turma, imp, "Usa As Duas",
                       elefante=dict(LEITOR_ELEFANTE), matific=dict(MATIFIC_TOPO))
    so_matific = novo_aluno(db, escola, turma, imp, "Só Matific",
                            matific=dict(MATIFIC_TOPO))
    db.commit()
    svc_modulos.definir(db, rede.id, "matematica", False)
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    notas = notas_por_id(db, escola.id)

    n_ambas = notas[ambas.id]
    assert n_ambas.detalhes["geral"]["pesos"] == {"elefante": 100.0}
    assert n_ambas.nota_geral == pytest.approx(n_ambas.nota_elefante, abs=0.01)
    # Aluno cuja ÚNICA dimensão com dado não é contratada: degradação segura —
    # mantém os pesos do contrato (nota 0), nunca uma conta impossível.
    n_so_matific = notas[so_matific.id]
    assert n_so_matific.nota_geral == 0.0
    conferir_explicacao(n_so_matific)
    assert n_ambas.posicao == 1


def test_religar_o_modulo_devolve_a_conta_das_duas_dimensoes(db):
    rede, escola, turma, imp = montar_escola(db, com_rede=True)
    aluno = novo_aluno(db, escola, turma, imp, "Usa As Duas",
                       elefante=dict(MEDIANO_ELEFANTE), matific=dict(MATIFIC_TOPO))
    # Coorte para a régua não degenerar (com 1 aluno ele é o máximo de tudo e as
    # duas notas dariam 100, escondendo a diferença que o teste quer ver).
    for i in range(9):
        novo_aluno(db, escola, turma, imp, f"Colega {i}",
                   elefante=dict(LEITOR_ELEFANTE),
                   matific={"atividades": 20, "pontuacao_media": 50.0, "estrelas": 20})
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    antes = notas_por_id(db, escola.id)[aluno.id].nota_geral

    svc_modulos.definir(db, rede.id, "matematica", False)
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    assert notas_por_id(db, escola.id)[aluno.id].nota_geral != antes

    svc_modulos.definir(db, rede.id, "matematica", True)
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    assert notas_por_id(db, escola.id)[aluno.id].nota_geral == antes


# --- A função pura ------------------------------------------------------------

@pytest.mark.parametrize("pesos, dimensoes, esperado", [
    ({"matific": 0.5, "elefante": 0.5}, {"matific", "elefante"},
     {"matific": 0.5, "elefante": 0.5}),
    ({"matific": 0.5, "elefante": 0.5}, {"elefante"}, {"elefante": 1.0}),
    ({"matific": 0.5, "elefante": 0.5}, {"matific"}, {"matific": 1.0}),
    # Pesos assimétricos: a redistribuição é proporcional, não 50/50.
    ({"matific": 0.7, "elefante": 0.3}, {"elefante"}, {"elefante": 1.0}),
    # Sem dimensão disponível → devolve a entrada (degradação segura).
    ({"matific": 0.5, "elefante": 0.5}, set(),
     {"matific": 0.5, "elefante": 0.5}),
    # Dimensão com dado FORA do contrato → também degradação segura.
    ({"elefante": 1.0}, {"matific"}, {"elefante": 1.0}),
])
def test_pesos_geral_do_aluno(pesos, dimensoes, esperado):
    assert scoring.pesos_geral_do_aluno(pesos, dimensoes) == pytest.approx(esperado)


def test_pesos_geral_do_aluno_nao_muta_a_entrada():
    pesos = {"matific": 0.5, "elefante": 0.5}
    scoring.pesos_geral_do_aluno(pesos, {"elefante"})
    assert pesos == {"matific": 0.5, "elefante": 0.5}
