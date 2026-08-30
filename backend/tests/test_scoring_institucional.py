"""Separação SCORING INSTITUCIONAL (régua da REDE) × SCORING DA ESCOLA (interno).

A garantia central do produto: um coordenador pode personalizar a régua da
PRÓPRIA escola (ranking/competição interna), mas NADA que ele configure move a
posição de nenhuma escola no ranking da REDE. A rede compara sempre pelas colunas
``nota_*_institucional``, calculadas com o perfil fixo do Constela (dificuldade
A3 ``exp(0,103·pos)`` + pesos padrão + normalização linear/robusta P90), imune à
config local.

Cada teste abaixo é uma das 10 provas pedidas.
"""
import math

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import (
    Aluno,
    Configuracao,
    Escola,
    Importacao,
    Leitura,
    Livro,
    Matricula,
    NivelDificuldade,
    Nota,
    Rede,
    ReferenciaNormalizacao,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
)
from app.services import rede as svc_rede
from app.services import scoring


# --- helpers de cenário ------------------------------------------------------

def _rede(db, nome="Rede Municipal"):
    r = Rede(nome=nome, status="ativa")
    db.add(r)
    db.flush()
    return r


def _escola(db, rede_id, nome, leituras, estrelas=None):
    """Escola com uma turma e ``len(leituras)`` alunos. ``leituras[i]`` é um dict
    ``{nível: n_livros_únicos}`` do aluno i; vira um ``SnapshotElefante``. Config
    PADRÃO (institucional) por default. Já roda o recálculo. Devolve (escola, alunos)."""
    esc = Escola(nome=nome, ano_letivo_ativo=2026, rede_id=rede_id, status="ativa")
    db.add(esc)
    db.flush()
    # Dificuldade "de escola" (faixas históricas, distintas da A3) — só entra em
    # jogo se a escola for PERSONALIZADA; o perfil institucional a ignora.
    db.add(NivelDificuldade(escola_id=esc.id, nome="Faixa baixa", codigo="fb",
                            codigos=["AA", "A", "B", "C", "D"], pontos_padrao=1.0, ordem=0))
    db.add(NivelDificuldade(escola_id=esc.id, nome="Faixa alta", codigo="fa",
                            codigos=["K", "L", "M", "N", "O", "Z"], pontos_padrao=2.0, ordem=1))
    db.add(ReferenciaNormalizacao(escola_id=esc.id, modo="auto"))
    turma = Turma(escola_id=esc.id, nome="5A", ano_escolar="5º Ano", ano_letivo=2026,
                  status="ativa")
    db.add(turma)
    db.flush()
    imp = Importacao(escola_id=esc.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    alunos = []
    for i, por_nivel in enumerate(leituras):
        a = Aluno(escola_id=esc.id, nome=f"{nome} aluno {i}", status="ativo")
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=esc.id, aluno_id=a.id, turma_id=turma.id, ano_letivo=2026))
        db.add(SnapshotElefante(
            escola_id=esc.id, aluno_id=a.id, importacao_id=imp.id,
            livros_unicos=sum(por_nivel.values()), livros_por_nivel=dict(por_nivel)))
        if estrelas is not None:
            db.add(SnapshotMatific(escola_id=esc.id, aluno_id=a.id, importacao_id=imp.id,
                                   estrelas=estrelas[i], atividades=estrelas[i]))
        alunos.append(a)
    db.commit()
    scoring.recalcular_escola(db, esc.id)
    return esc, alunos


def _nota(db, escola_id, aluno_id):
    return db.execute(
        select(Nota).where(Nota.escola_id == escola_id, Nota.aluno_id == aluno_id)
    ).scalar_one()


def _personalizar(db, escola_id, *, pesos_elefante=None, pontos_faixa_alta=None):
    """Marca a escola como PERSONALIZADA e (opcional) muda pesos/dificuldade
    locais. Recalcula. A régua institucional NÃO deve se mover com nada disto."""
    db.add(Configuracao(escola_id=escola_id, namespace=scoring.PERFIL_SCORING_NS,
                        chave="modo", valor="personalizado"))
    if pesos_elefante is not None:
        row = db.execute(select(Configuracao).where(
            Configuracao.escola_id == escola_id,
            Configuracao.namespace == "pesos.elefante",
            Configuracao.chave == "valores")).scalar_one_or_none()
        if row is None:
            db.add(Configuracao(escola_id=escola_id, namespace="pesos.elefante",
                                chave="valores", valor=pesos_elefante))
        else:
            row.valor = pesos_elefante
    if pontos_faixa_alta is not None:
        nivel = db.execute(select(NivelDificuldade).where(
            NivelDificuldade.escola_id == escola_id,
            NivelDificuldade.codigo == "fa")).scalar_one()
        nivel.pontos_padrao = pontos_faixa_alta
    db.commit()
    scoring.recalcular_escola(db, escola_id)


# Um conjunto de leituras com ordem de dificuldade clara (aluno 0 > 1 > 2).
LEITURAS = [{"M": 3, "D": 1}, {"D": 2, "A": 1}, {"A": 1}]


# === (7) A3 é monotônica de AA até Z =========================================

def test_a3_monotonica_aa_ate_z():
    pesos = [scoring.peso_a3(n) for n in scoring.NIVEIS_ORDENADOS]
    assert pesos == sorted(pesos), "A3 tem de ser não-decrescente na ordem AA→Z"
    assert all(b > a for a, b in zip(pesos, pesos[1:])), "A3 é ESTRITAMENTE crescente"
    assert scoring.peso_a3("AA") == 1.0
    assert round(scoring.peso_a3("Z"), 2) == 19.83
    # As duas trilhas do Elefante: Pré-Leitor (AA–DD) vem ANTES de A–Z; DD < A.
    assert scoring.peso_a3("DD") < scoring.peso_a3("A")


# === (9) livro de nível inferior nunca ultrapassa o piso do nível superior ====

def test_nivel_inferior_nunca_passa_o_piso_do_superior():
    # A dificuldade institucional de um livro é peso_a3(nível), SEM qualquer
    # componente de tamanho/wordCount (A3 puro). Logo um livro de nível baixo
    # jamais alcança o valor de um nível mais alto, por mais "longo" que seja.
    assert "wordCount" not in scoring.A3_MAPA_DIFICULDADE["__padrao__"]
    for baixo, alto in [("A", "M"), ("D", "K"), ("M", "Z"), ("AA", "DD")]:
        um_baixo = scoring._pontos_dificuldade({baixo: 1}, "5º Ano",
                                               scoring.A3_MAPA_DIFICULDADE)
        um_alto = scoring._pontos_dificuldade({alto: 1}, "5º Ano",
                                              scoring.A3_MAPA_DIFICULDADE)
        assert um_baixo < um_alto


# === (8) releitura não soma dificuldade ======================================

def test_releitura_nao_soma_dificuldade(db):
    esc = Escola(nome="E", ano_letivo_ativo=2026, status="ativa")
    db.add(esc)
    db.flush()
    aluno = Aluno(escola_id=esc.id, nome="Rê Leitor", status="ativo")
    livro = Livro(escola_id=esc.id, titulo="O Mesmo Livro", nivel_codigo="M")
    db.add_all([aluno, livro])
    db.flush()
    db.add(Leitura(escola_id=esc.id, aluno_id=aluno.id, livro_id=livro.id))
    db.commit()
    # Reler o MESMO livro = mesma (aluno, livro): o índice único barra a segunda
    # linha, então o livro conta uma vez só na contagem que alimenta a dificuldade.
    db.add(Leitura(escola_id=esc.id, aluno_id=aluno.id, livro_id=livro.id))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


# === (1) mesmos dados + config diferente → MESMO resultado institucional ======

def test_mesmos_dados_config_diferente_mesmo_institucional(db):
    r = _rede(db)
    esc_a, alunos_a = _escola(db, r.id, "Escola A", LEITURAS)
    esc_b, alunos_b = _escola(db, r.id, "Escola B", LEITURAS)
    # A personaliza com pesos e dificuldade radicalmente diferentes; B fica padrão.
    _personalizar(db, esc_a.id,
                  pesos_elefante={"livros": 0.0, "dificuldade": 100.0,
                                  "questoes": 0.0, "tempo": 0.0},
                  pontos_faixa_alta=99.0)
    # As notas INSTITUCIONAIS por aluno têm de ser idênticas entre A e B.
    for aa, ab in zip(alunos_a, alunos_b):
        na = _nota(db, esc_a.id, aa.id)
        nb = _nota(db, esc_b.id, ab.id)
        assert na.nota_elefante_institucional == nb.nota_elefante_institucional
    # E a média institucional da rede é igual para as duas escolas.
    cartoes = {c["nome"]: c for c in svc_rede._kpis_da_rede(db, r.id)}
    assert cartoes["Escola A"]["media_elefante"] == cartoes["Escola B"]["media_elefante"]


# === (2,3,5) personalizar muda SÓ o interno, não o institucional/rede =========

def test_personalizar_muda_interno_nao_a_rede(db):
    r = _rede(db)
    esc, alunos = _escola(db, r.id, "Escola A", LEITURAS)
    antes = {a.id: _nota(db, esc.id, a.id) for a in alunos}
    inst_antes = {aid: n.nota_elefante_institucional for aid, n in antes.items()}
    local_antes = {aid: n.nota_elefante for aid, n in antes.items()}
    ranking_rede_antes = [c["nome"] for c in svc_rede.ranking_escolas(db, r.id)]

    # Personaliza: inverte a régua de dificuldade (faixa alta passa a valer MENOS
    # que a baixa) → a ordem INTERNA muda.
    _personalizar(db, esc.id, pontos_faixa_alta=0.1,
                  pesos_elefante={"livros": 0.0, "dificuldade": 100.0,
                                  "questoes": 0.0, "tempo": 0.0})
    depois = {a.id: _nota(db, esc.id, a.id) for a in alunos}

    # (5) ranking interno passou a respeitar a config personalizada: a nota LOCAL
    # de pelo menos um aluno mudou.
    assert any(depois[aid].nota_elefante != local_antes[aid] for aid in local_antes)
    # (3) a nota INSTITUCIONAL de todos os alunos NÃO mudou.
    for aid in inst_antes:
        assert depois[aid].nota_elefante_institucional == inst_antes[aid]
    # (2) a posição da escola no ranking da rede NÃO mudou.
    assert [c["nome"] for c in svc_rede.ranking_escolas(db, r.id)] == ranking_rede_antes


# === (4) config da Escola A não altera métrica institucional de B, C, D ========

def test_config_de_a_nao_afeta_bcd(db):
    r = _rede(db)
    esc_a, _ = _escola(db, r.id, "Escola A", LEITURAS)
    esc_b, _ = _escola(db, r.id, "Escola B", [{"K": 2}, {"D": 1}, {"A": 1}])
    esc_c, _ = _escola(db, r.id, "Escola C", [{"Z": 1}, {"M": 2}, {"A": 3}])
    esc_d, _ = _escola(db, r.id, "Escola D", [{"D": 5}, {"A": 2}])

    def medias_inst():
        return {c["nome"]: c["media_elefante"] for c in svc_rede._kpis_da_rede(db, r.id)}

    antes = medias_inst()
    _personalizar(db, esc_a.id, pontos_faixa_alta=99.0,
                  pesos_elefante={"livros": 100.0, "dificuldade": 0.0,
                                  "questoes": 0.0, "tempo": 0.0})
    depois = medias_inst()
    for nome in ("Escola B", "Escola C", "Escola D"):
        assert depois[nome] == antes[nome], f"{nome} não pode mudar por config de A"


# === (6) ranking da rede usa SOMENTE métrica institucional ====================

def test_ranking_rede_usa_somente_institucional(db):
    r = _rede(db)
    esc, alunos = _escola(db, r.id, "Escola A", LEITURAS)
    card_antes = {c["nome"]: c for c in svc_rede._kpis_da_rede(db, r.id)}["Escola A"]

    # Personaliza para INFLAR a nota LOCAL ao máximo (só dificuldade, faixa alta
    # com valor gigante). Se a rede lesse a nota local, a média explodiria.
    _personalizar(db, esc.id, pontos_faixa_alta=9999.0,
                  pesos_elefante={"livros": 0.0, "dificuldade": 100.0,
                                  "questoes": 0.0, "tempo": 0.0})
    card_depois = {c["nome"]: c for c in svc_rede._kpis_da_rede(db, r.id)}["Escola A"]
    assert card_depois["media_elefante"] == card_antes["media_elefante"]


# === (10) nenhum caminho de rede/global lê a nota calculada com config local ===

def test_rede_ignora_a_nota_local_mesmo_adulterada(db):
    r = _rede(db)
    esc, alunos = _escola(db, r.id, "Escola A", LEITURAS)
    inst_antes = {c["nome"]: c["media_elefante"]
                  for c in svc_rede._kpis_da_rede(db, r.id)}["Escola A"]

    # Adultera DIRETO as colunas LOCAIS (simula qualquer efeito de config local)
    # sem tocar nas institucionais. Se qualquer métrica de rede lesse a local,
    # este valor-sentinela apareceria.
    for a in alunos:
        n = _nota(db, esc.id, a.id)
        n.nota_elefante = 12345.0
        n.nota_matific = 12345.0
    db.commit()

    inst_depois = {c["nome"]: c["media_elefante"]
                   for c in svc_rede._kpis_da_rede(db, r.id)}["Escola A"]
    assert inst_depois == inst_antes
    # E a fonte da média da rede é comprovadamente a coluna institucional.
    import inspect
    fonte = inspect.getsource(svc_rede._kpis_da_rede)
    assert "nota_elefante_institucional" in fonte
    assert "Nota.nota_elefante)" not in fonte  # nunca a coluna LOCAL crua


# === (7) Padrão Constela é o estado inicial de uma escola nova ================

def test_escola_nova_nasce_padrao_constela(db):
    r = _rede(db)
    esc, alunos = _escola(db, r.id, "Escola Nova", LEITURAS)
    # Sem nenhuma Configuracao de perfil → padrão (institucional).
    assert scoring._scoring_personalizado(db, esc.id) is False
    # E a nota institucional já foi calculada e é positiva para quem leu.
    n0 = _nota(db, esc.id, alunos[0].id)
    assert n0.nota_elefante_institucional > 0
    # Em padrão, a nota local É a institucional (mesma régua).
    assert n0.nota_elefante == n0.nota_elefante_institucional


# === (5) config de A não move a POSIÇÃO de B, C, D no ranking da rede =========

def test_config_de_a_nao_move_posicao_de_bcd(db):
    r = _rede(db)
    _escola(db, r.id, "Escola A", LEITURAS)
    _escola(db, r.id, "Escola B", [{"K": 2}, {"D": 1}, {"A": 1}])
    _escola(db, r.id, "Escola C", [{"Z": 1}, {"M": 2}, {"A": 3}])
    esc_a = db.execute(select(Escola).where(Escola.nome == "Escola A")).scalar_one()

    def posicoes():
        return {c["nome"]: c["posicao"] for c in svc_rede.ranking_escolas(db, r.id)}

    antes = posicoes()
    _personalizar(db, esc_a.id, pontos_faixa_alta=99.0,
                  pesos_elefante={"livros": 0.0, "dificuldade": 100.0,
                                  "questoes": 0.0, "tempo": 0.0})
    depois = posicoes()
    for nome in ("Escola B", "Escola C"):
        assert depois[nome] == antes[nome]


# === (14) ranking da rede idêntico quando SÓ a config local de uma escola muda =

def test_ranking_rede_identico_quando_so_config_local_muda(db):
    r = _rede(db)
    _escola(db, r.id, "Escola A", LEITURAS)
    _escola(db, r.id, "Escola B", [{"K": 2}, {"D": 1}, {"A": 1}])
    _escola(db, r.id, "Escola C", [{"Z": 1}, {"M": 2}, {"A": 3}])
    esc_a = db.execute(select(Escola).where(Escola.nome == "Escola A")).scalar_one()

    ranking_antes = [(c["nome"], c["posicao"], c["pontuacao_geral"])
                     for c in svc_rede.ranking_escolas(db, r.id)]
    _personalizar(db, esc_a.id, pontos_faixa_alta=0.01,
                  pesos_elefante={"livros": 100.0, "dificuldade": 0.0,
                                  "questoes": 0.0, "tempo": 0.0})
    ranking_depois = [(c["nome"], c["posicao"], c["pontuacao_geral"])
                      for c in svc_rede.ranking_escolas(db, r.id)]
    assert ranking_depois == ranking_antes


# === endpoint /perfil-scoring: default institucional, troca, validação ========

def test_endpoint_perfil_scoring(cliente, escola_completa):
    escola_id = escola_completa["escola"].id
    base = f"/api/v1/escolas/{escola_id}/configuracoes/perfil-scoring"
    # Estado inicial: Padrão Constela.
    r = cliente.get(base)
    assert r.status_code == 200, r.text
    assert r.json()["modo"] == "institucional"
    # Troca para personalizado.
    r = cliente.put(base, json={"modo": "personalizado"})
    assert r.status_code == 200, r.text
    assert r.json()["modo"] == "personalizado"
    assert cliente.get(base).json()["modo"] == "personalizado"
    # Valor inválido é rejeitado.
    assert cliente.put(base, json={"modo": "qualquer"}).status_code == 400
