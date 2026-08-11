"""Médias 0–100 = DESEMPENHO (de quem usa) · adoção = COBERTURA (quantos usam).

Antes, a média da escola incluía como ZERO todo aluno matriculado sem dado da
plataforma — então ela media *desempenho × cobertura* e uma escola boa com
metade dos alunos fora aparecia como ruim. E a "adoção" contava linhas em
`notas` (que existem para todo matriculado), dando ~100% sempre.

Estes são os casos A–F pedidos pelo dono.
"""
import pytest

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


def _rede(db, nome="Rede Desempenho"):
    r = Rede(nome=nome, status="ativa")
    db.add(r)
    db.flush()
    return r


def _escola(db, rede_id, nome, alunos, *, notas_ele=None, notas_mat=None):
    """Escola com `alunos` matriculados ativos.

    ``notas_ele``/``notas_mat``: lista de notas por aluno (None na posição = o
    aluno NÃO tem dado daquela plataforma, ou seja, não recebe snapshot). A Nota
    é gravada para TODOS (como o motor faz), com 0 onde não há dado.
    """
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
    notas_ele = notas_ele or [None] * alunos
    notas_mat = notas_mat or [None] * alunos
    for i in range(alunos):
        a = Aluno(escola_id=esc.id, nome=f"Crianca {nome} {i}", status="ativo")
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=esc.id, aluno_id=a.id, turma_id=turma.id, ano_letivo=2026))
        ne, nm = notas_ele[i], notas_mat[i]
        if ne is not None:      # tem dado do Elefante
            db.add(SnapshotElefante(escola_id=esc.id, aluno_id=a.id, importacao_id=imp.id,
                                    livros_unicos=5, tempo_leitura_min=60))
        if nm is not None:      # tem dado do Matific
            db.add(SnapshotMatific(escola_id=esc.id, aluno_id=a.id, importacao_id=imp.id,
                                   atividades=20, estrelas=100))
        # O motor grava Nota para TODO matriculado — inclusive quem não usa (0).
        db.add(Nota(escola_id=esc.id, aluno_id=a.id, ano_letivo=2026,
                    nota_elefante=ne or 0.0, nota_matific=nm or 0.0,
                    nota_geral=((ne or 0.0) + (nm or 0.0)) / 2, posicao=i + 1))
    return esc


def _cartao(db, rede_id, nome):
    return next(c for c in svc._kpis_da_rede(db, rede_id) if c["nome"] == nome)


# --- Caso A: 100% de cobertura — nada muda ----------------------------------

def test_a_cobertura_total_mantem_a_media(db):
    rede = _rede(db)
    _escola(db, rede.id, "Escola A", 15,
            notas_ele=[70.0] * 15, notas_mat=[80.0] * 15)
    db.commit()

    c = _cartao(db, rede.id, "Escola A")
    assert c["media_elefante"] == 70.0
    assert c["media_matific"] == 80.0
    assert c["media_geral"] == 75.0            # (70 + 80) / 2
    assert c["adocao"] == 100.0                # todos usam


# --- Caso B: 8 de 15 com dados — a média é a dos 8 --------------------------

def test_b_meia_cobertura_nao_dilui_o_desempenho(db):
    """O caso que motivou tudo: 8 alunos com média 71,3 e 7 sem dado.
    A média da escola tem de ser 71,3 — não (8×71,3 + 7×0)/15 = 38,0."""
    rede = _rede(db)
    _escola(db, rede.id, "Escola B", 15,
            notas_ele=[71.3] * 8 + [None] * 7,
            notas_mat=[79.5] * 8 + [None] * 7)
    db.commit()

    c = _cartao(db, rede.id, "Escola B")
    assert c["media_elefante"] == 71.3         # e NÃO 38,0
    assert c["media_matific"] == 79.5
    assert c["media_geral"] == 75.4            # (71,3 + 79,5) / 2
    assert c["alunos_com_nota_elefante"] == 8  # a média saiu de 8 alunos
    # A cobertura aparece SEPARADA, sem contaminar o desempenho.
    assert c["alunos_com_dados"] == 8 and c["total_alunos"] == 15
    assert c["adocao"] == pytest.approx(53.3, abs=0.1)


# --- Caso C: só uma plataforma — sem teto de 50 -----------------------------

def test_c_uma_plataforma_nao_divide_por_dois(db):
    """Escola que só usa o Elefante: a geral é a nota de leitura, não a metade.
    Antes, nota_geral = 0,5·0 + 0,5·leitura criava um TETO de 50."""
    rede = _rede(db)
    _escola(db, rede.id, "So Elefante", 10, notas_ele=[75.0] * 10, notas_mat=None)
    db.commit()

    c = _cartao(db, rede.id, "So Elefante")
    assert c["media_elefante"] == 75.0
    assert c["media_matific"] == 0.0           # sem dados
    assert c["media_geral"] == 75.0            # e NÃO 37,5
    assert c["dimensoes_com_dados"] == ["leitura"]
    assert c["adocao_elefante"] == 100.0 and c["adocao_matific"] == 0.0


# --- Caso D: duas plataformas ----------------------------------------------

def test_d_duas_plataformas_media_das_duas(db):
    rede = _rede(db)
    _escola(db, rede.id, "Escola D", 10,
            notas_ele=[75.0] * 10, notas_mat=[80.0] * 10)
    db.commit()

    c = _cartao(db, rede.id, "Escola D")
    assert (c["media_elefante"], c["media_matific"]) == (75.0, 80.0)
    assert c["media_geral"] == 77.5
    assert c["dimensoes_com_dados"] == ["leitura", "matematica"]


# --- Caso E: adoção real, nunca 100% artificial -----------------------------

def test_e_adocao_reflete_uso_real_nao_linhas_de_nota(db):
    """15 matriculados, 8 com dado do Elefante e 12 do Matific."""
    rede = _rede(db)
    _escola(db, rede.id, "Escola E", 15,
            notas_ele=[70.0] * 8 + [None] * 7,
            notas_mat=[80.0] * 12 + [None] * 3)
    db.commit()

    c = _cartao(db, rede.id, "Escola E")
    assert c["adocao_elefante"] == pytest.approx(53.3, abs=0.1)   # 8/15
    assert c["adocao_matific"] == 80.0                            # 12/15
    # Cobertura geral = alunos com ALGUMA plataforma (união), não a soma.
    assert c["alunos_com_dados"] == 12 and c["adocao"] == 80.0
    assert c["adocao"] != 100.0                                   # o bug antigo


def test_e2_escola_sem_nenhum_dado_tem_adocao_zero(db):
    rede = _rede(db)
    _escola(db, rede.id, "Sem Dados", 10)      # ninguém usa nada
    db.commit()

    c = _cartao(db, rede.id, "Sem Dados")
    assert c["adocao"] == 0.0 and c["alunos_com_dados"] == 0
    assert c["media_geral"] == 0.0 and c["dimensoes_com_dados"] == []
    # O alerta de atenção agora DISPARA (antes com_dados vinha das linhas de
    # `notas`, que existem para todo matriculado, e a regra nunca era atingida).
    assert c["precisa_atencao"]
    assert "nenhum aluno com dados" in (c["motivo_atencao"] or "").lower()


# --- Caso F: duplicatas não inflam nada -------------------------------------

def test_f_aluno_duplicado_nao_infla_cobertura_nem_media(db):
    """A ficha duplicada (2º cadastro do mesmo aluno) conta enquanto está ativa,
    e SAI de todos os números — alunos, cobertura, média — ao ser arquivada
    (o desfecho da tela "Fundir duplicatas")."""
    rede = _rede(db)
    esc = _escola(db, rede.id, "Escola F", 10,
                  notas_ele=[70.0] * 10, notas_mat=[70.0] * 10)
    turma = db.query(Turma).filter(Turma.escola_id == esc.id).first()
    imp = db.query(Importacao).filter(Importacao.escola_id == esc.id).first()
    dup = Aluno(escola_id=esc.id, nome="Crianca Escola F 0 (duplicata)", status="ativo")
    db.add(dup)
    db.flush()
    db.add(Matricula(escola_id=esc.id, aluno_id=dup.id, turma_id=turma.id, ano_letivo=2026))
    db.add(SnapshotElefante(escola_id=esc.id, aluno_id=dup.id, importacao_id=imp.id,
                            livros_unicos=5, tempo_leitura_min=60))
    db.add(Nota(escola_id=esc.id, aluno_id=dup.id, ano_letivo=2026,
                nota_elefante=20.0, nota_matific=0.0, nota_geral=10.0, posicao=11))
    db.commit()

    c = _cartao(db, rede.id, "Escola F")
    assert c["total_alunos"] == 11             # passivo pendente de fusão

    dup.status = "arquivado"                   # fundida/arquivada
    db.commit()
    c = _cartao(db, rede.id, "Escola F")
    assert c["total_alunos"] == 10             # não infla o denominador
    assert c["alunos_com_dados"] == 10         # nem a cobertura
    assert c["media_elefante"] == 70.0         # nem puxa a média
    assert c["adocao"] == 100.0


# --- Regressão: um zero LEGÍTIMO continua contando --------------------------

def test_zero_de_quem_usa_a_plataforma_continua_na_media(db):
    """O corte é por EXISTÊNCIA de dado, não por nota > 0: quem usa a plataforma
    e ainda não produziu nada é um zero real e deve pesar na média."""
    rede = _rede(db)
    _escola(db, rede.id, "Com Zero Real", 2,
            notas_ele=[80.0, 0.0], notas_mat=None)   # os DOIS têm snapshot
    db.commit()

    c = _cartao(db, rede.id, "Com Zero Real")
    assert c["alunos_com_nota_elefante"] == 2
    assert c["media_elefante"] == 40.0          # (80 + 0) / 2 — o zero conta
