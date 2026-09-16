"""Guardas numéricas da normalização (``scoring``) — a régua P90 + mínimo de 8
alunos continua a mesma; o que se prova aqui é que NENHUMA entrada suja (NaN,
infinito, negativo, None, texto, coorte vazia, referência inexistente) produz
erro, NaN, infinito ou nota fora de [0, 100], e que valores válidos seguem dando
exatamente o que davam antes."""
import json
import math
from types import SimpleNamespace

import pytest

from app.services import scoring

NAN, INF = float("nan"), float("inf")
SUJOS = (None, NAN, INF, -INF, "abc", -1, -1e12, 0, 0.0)


def _nota_ok(x) -> bool:
    return isinstance(x, float) and math.isfinite(x) and 0.0 <= x <= 100.0


def _formula_antiga_saturada(valor, referencia, k):
    """A conta de antes, para valores válidos (bit a bit)."""
    f_ref = referencia / (referencia + k)
    return round(min(100.0, (float(valor) / (float(valor) + k)) / f_ref * 100.0), 2)


# --- normalizar ------------------------------------------------------------------

def test_normalizar_valores_validos_inalterados():
    assert scoring.normalizar(50, 100) == 50.0
    assert scoring.normalizar(150, 100) == 100.0
    assert scoring.normalizar(33, 7) == 100.0
    assert scoring.normalizar(1, 3) == round(1 / 3 * 100, 2)
    for v in (0.5, 1, 7, 12.34, 99.99):
        assert scoring.normalizar(v, 100) == round(min(100.0, v / 100 * 100.0), 2)


@pytest.mark.parametrize("sujo", SUJOS)
def test_normalizar_referencia_ou_valor_invalido_da_zero(sujo):
    assert scoring.normalizar(50, sujo) == 0.0
    assert scoring.normalizar(sujo, 100) == 0.0
    assert scoring.normalizar(sujo, sujo) == 0.0


def test_normalizar_valores_extremos_ficam_em_0_100():
    casos = [(1e12, 100), (1e12, 1e12), (1, 1e12), (1e300, 1e-300), (1e-300, 1e300),
             (5e-324, 1.0), (1.7e308, 1.7e308)]
    for valor, ref in casos:
        assert _nota_ok(scoring.normalizar(valor, ref)), (valor, ref)
    assert scoring.normalizar(1e12, 100) == 100.0
    assert scoring.normalizar(1e300, 1e-300) == 100.0      # razão estoura → teto, sem inf


# --- normalizar_saturado ------------------------------------------------------------

def test_saturado_valores_validos_batem_com_a_formula_antiga():
    for ref in (10, 100, 1234.5):
        for k in (1, 5, 50, 500):
            for v in (0.1, 1, 3, 9.99, ref * 0.5, ref):
                assert scoring.normalizar_saturado(v, ref, k) == _formula_antiga_saturada(v, ref, k)
    assert scoring.normalizar_saturado(100, 100, 50) == 100.0
    assert scoring.normalizar_saturado(50, 100, 50) == 75.0


@pytest.mark.parametrize("k", [None, 0, -1, NAN, INF, -INF, "abc"])
def test_saturado_k_invalido_cai_no_linear(k):
    assert scoring.normalizar_saturado(50, 100, k) == scoring.normalizar(50, 100) == 50.0


@pytest.mark.parametrize("sujo", SUJOS)
def test_saturado_referencia_ou_valor_invalido_da_zero(sujo):
    assert scoring.normalizar_saturado(50, sujo, 10) == 0.0
    assert scoring.normalizar_saturado(sujo, 100, 10) == 0.0


def test_saturado_valores_extremos_ficam_em_0_100():
    assert scoring.normalizar_saturado(1e12, 1e12, 1e12) == 100.0
    assert scoring.normalizar_saturado(5e11, 1e12, 1e12) == pytest.approx(66.67, abs=0.01)
    # soma estoura (ref + k = inf): mesma curva reescalada, sem NaN
    v, ref, k = 1e308, 1.7e308, 1.7e308
    esperado = (v / ref / (v / ref + 1.0)) / 0.5 * 100.0
    assert scoring.normalizar_saturado(v, ref, k) == pytest.approx(round(esperado, 2), abs=0.01)
    # fração some (k ≫ ref): limite linear
    assert _nota_ok(scoring.normalizar_saturado(1e-300, 1e-200, 1e300))
    for caso in [(1e12, 100, 50), (1, 1e12, 1e-12), (5e-324, 1.0, 1.0), (1.0, 1e308, 1e308)]:
        assert _nota_ok(scoring.normalizar_saturado(*caso)), caso


# --- percentil e referências ----------------------------------------------------------

def test_percentil_ignora_nao_finitos():
    assert scoring._percentil([1, 2, NAN, 3, INF, None, "x", -INF], 0.5) == 2.0
    assert scoring._percentil([NAN, INF, None], 0.9) == 0.0
    assert scoring._percentil([], 0.9) == 0.0
    assert scoring._percentil([float(x) for x in range(1, 21)], 0.9) == pytest.approx(18.1)
    assert math.isfinite(scoring._percentil([1e12, 1e12, 1e12], 0.9))


def test_referencias_robustas_minimo_de_8_alunos_inalterado():
    # 7 alunos: régua do MÁXIMO, sem saturação (regra antiga, intocada)
    refs, k = scoring.referencias_robustas({"atividades": [1, 2, 3, 4, 5, 6, 7]})
    assert refs["max_atividades"] == 7 and k == {}
    refs, k = scoring.referencias_robustas({"atividades": [10, 20, 30]})
    assert refs["max_atividades"] == 30 and k == {}
    # 8 alunos: P90 + k=mediana (volume)
    oito = [float(x) for x in range(1, 9)]
    refs, k = scoring.referencias_robustas({"atividades": oito})
    assert refs["max_atividades"] == pytest.approx(scoring._percentil(oito, 0.9))
    assert refs["max_atividades"] < 8.0 and k["atividades"] == pytest.approx(4.5)


def test_referencias_robustas_so_usam_valores_finitos():
    # amostra pequena com lixo: o máximo sai só dos finitos ≥ 0
    refs, k = scoring.referencias_robustas({"livros": [1, NAN, INF, -5, None, 3, "abc"]})
    assert refs["max_livros"] == 3 and k == {}
    refs, _ = scoring.referencias_robustas({"livros": [NAN, -1, -INF]})
    assert refs["max_livros"] == 0
    # coorte grande com lixo: ativos = finitos > 0
    refs, k = scoring.referencias_robustas({"livros": [NAN, INF, -3] + [float(x) for x in range(1, 9)]})
    assert refs["max_livros"] == pytest.approx(scoring._percentil(list(range(1, 9)), 0.9))
    assert k["livros"] == pytest.approx(4.5)
    # extremos
    refs, k = scoring.referencias_robustas({"tempo": [1e12] * 10})
    assert refs["max_tempo"] == 1e12 and k["tempo"] == 1e12
    assert scoring.referencias_robustas({}) == ({}, {})
    assert scoring.referencias_robustas({"livros": []}) == ({"max_livros": 0}, {})
    for valor in scoring.referencias_robustas({"media": [NAN, INF]})[0].values():
        assert math.isfinite(valor)


def _snap_m(atividades, media, estrelas):
    return SimpleNamespace(atividades=atividades, pontuacao_media=media, estrelas=estrelas)


def _snap_e(livros, tempo, tentativas=0, acertos=0):
    return SimpleNamespace(livros_unicos=livros, tempo_leitura_min=tempo,
                           questoes_tentativas=tentativas, questoes_acertos=acertos)


def test_referencias_auto_coorte_vazia_e_lixo():
    refs, k = scoring._referencias_auto({}, {}, {})
    assert set(refs) == set(scoring.CHAVES_REFERENCIA)
    assert all(v == 0 for v in refs.values()) and k == {}
    matific = {1: _snap_m(NAN, INF, -3), 2: _snap_m(5, 40.0, 2)}
    elefante = {1: _snap_e(-2, NAN), 2: _snap_e(3, 90)}
    refs, k = scoring._referencias_auto(matific, elefante, {1: NAN, 2: 7.5, 3: -1.0})
    assert refs["max_atividades"] == 5 and refs["max_media"] == 40.0 and refs["max_estrelas"] == 2
    assert refs["max_livros"] == 3 and refs["max_tempo"] == 90
    assert refs["max_pontos_dificuldade"] == 7.5
    assert all(math.isfinite(v) and v >= 0 for v in refs.values()) and k == {}


def test_referencias_auto_minimo_de_8_por_dimensao_inalterado():
    matific = {i: _snap_m(i, 10.0 * i, i) for i in range(1, 9)}         # 8: robusto
    elefante = {i: _snap_e(i, i * 10) for i in range(1, 8)}              # 7: máximo
    refs, k = scoring._referencias_auto(matific, elefante, {i: float(i) for i in range(1, 8)})
    assert refs["max_atividades"] < 8 and "atividades" in k
    assert refs["max_livros"] == 7 and "livros" not in k
    assert refs["max_pontos_dificuldade"] == 7.0


# --- cálculo por módulo ----------------------------------------------------------------

def test_calcular_sem_referencias_ou_coorte_vazia_da_nota_zero_sem_erro():
    p_m, pct_m = scoring._pesos_institucionais("pesos.matific")
    p_e, pct_e = scoring._pesos_institucionais("pesos.elefante")
    p_q, pct_q = scoring._pesos_institucionais("pesos.questoes")
    for refs in ({}, scoring._referencias_auto({}, {}, {})[0]):
        nota_m, linhas_m = scoring.calcular_matific(_snap_m(10, 80.0, 5), refs, p_m, pct_m, {})
        nota_e, linhas_e, det_q = scoring.calcular_elefante(
            _snap_e(4, 60, 10, 8), 12.5, refs, p_e, pct_e, p_q, pct_q, {})
        assert nota_m == 0.0 and nota_e == 0.0
        assert all(linha["referencia"] == 0 for linha in linhas_m)
        assert det_q["sub_nota"] == 0.0
        json.dumps([linhas_m, linhas_e, det_q], allow_nan=False)
    assert scoring.calcular_matific(None, {}, p_m, pct_m)[0] == 0.0
    assert scoring.calcular_elefante(None, 0.0, {}, p_e, pct_e, p_q, pct_q)[0] == 0.0


def test_calcular_com_entradas_sujas_fica_finito_em_0_100():
    p_m, pct_m = scoring._pesos_institucionais("pesos.matific")
    p_e, pct_e = scoring._pesos_institucionais("pesos.elefante")
    p_q, pct_q = scoring._pesos_institucionais("pesos.questoes")
    refs = {chave: 100.0 for chave in scoring.CHAVES_REFERENCIA}
    for sujo in SUJOS:
        nota_m, linhas_m = scoring.calcular_matific(_snap_m(sujo, sujo, sujo), refs, p_m, pct_m,
                                                    {"atividades": sujo, "estrelas": 50.0})
        nota_e, linhas_e, det_q = scoring.calcular_elefante(
            _snap_e(sujo, sujo, sujo, sujo), sujo, refs, p_e, pct_e, p_q, pct_q, {"livros": sujo})
        assert nota_m == 0.0 and nota_e == 0.0, sujo
        assert all(linha["valor"] == 0 for linha in linhas_m + linhas_e[:2])
        json.dumps([linhas_m, linhas_e, det_q], allow_nan=False)
    # referências sujas: nota 0, nunca exceção
    refs_sujas = {chave: NAN for chave in scoring.CHAVES_REFERENCIA}
    assert scoring.calcular_matific(_snap_m(5, 50.0, 3), refs_sujas, p_m, pct_m)[0] == 0.0
    assert scoring.calcular_elefante(_snap_e(5, 50), 9.0, refs_sujas, p_e, pct_e, p_q, pct_q)[0] == 0.0
    # pesos sujos: nota finita (0), sem NaN
    assert scoring.calcular_matific(_snap_m(5, 50.0, 3), refs, {"atividades": NAN}, pct_m)[0] == 0.0


def test_inteiro_fora_do_alcance_do_float_nao_levanta_e_vale_zero():
    """`10**400` é JSON válido, e `math.isfinite` LEVANTA `OverflowError` com ele:
    a guarda de entrada tem de tratá-lo como entrada suja (0), nunca deixar o erro
    subir do meio do cálculo da nota."""
    p_m, pct_m = scoring._pesos_institucionais("pesos.matific")
    p_e, pct_e = scoring._pesos_institucionais("pesos.elefante")
    p_q, pct_q = scoring._pesos_institucionais("pesos.questoes")
    refs = {chave: 100.0 for chave in scoring.CHAVES_REFERENCIA}
    for gigante in (10**400, -(10**400), 10**309):
        assert scoring._finito(gigante) is None
        assert scoring._entrada_nao_negativa(gigante) == 0
        assert scoring.normalizar(gigante, 100) == 0.0
        assert scoring.normalizar(50, gigante) == 0.0
        assert scoring.normalizar_saturado(gigante, 100, 50) == 0.0
        assert scoring.normalizar_saturado(50, 100, gigante) == 50.0      # k sujo → linear
        nota_m, linhas_m = scoring.calcular_matific(
            _snap_m(gigante, gigante, gigante), refs, p_m, pct_m, {"atividades": gigante})
        nota_e, linhas_e, det_q = scoring.calcular_elefante(
            _snap_e(gigante, gigante, gigante, gigante), gigante, refs, p_e, pct_e,
            p_q, pct_q, {"livros": gigante})
        assert nota_m == 0.0 and nota_e == 0.0, gigante
        json.dumps([linhas_m, linhas_e, det_q], allow_nan=False)
    # referência gigante: nota 0 (referência inválida), sem exceção
    refs_gigantes = {chave: 10**400 for chave in scoring.CHAVES_REFERENCIA}
    assert scoring.calcular_matific(_snap_m(5, 50.0, 3), refs_gigantes, p_m, pct_m)[0] == 0.0
    # na amostra, o gigante é ignorado como um NaN (mediana de [1, 3] = 2)
    assert scoring._percentil([1, 10**400, 3], 0.5) == 2.0
    refs_lixo, _ = scoring.referencias_robustas({"livros": [1, 10**400, 3]})
    assert refs_lixo["max_livros"] == 3


def test_calcular_com_valores_extremos_satura_em_100():
    p_m, pct_m = scoring._pesos_institucionais("pesos.matific")
    p_e, pct_e = scoring._pesos_institucionais("pesos.elefante")
    p_q, pct_q = scoring._pesos_institucionais("pesos.questoes")
    refs = {chave: 100.0 for chave in scoring.CHAVES_REFERENCIA}
    k = {"atividades": 50.0, "estrelas": 50.0, "livros": 50.0, "tempo": 50.0, "tentativas": 50.0}
    nota_m, _ = scoring.calcular_matific(_snap_m(1e12, 1e12, 1e12), refs, p_m, pct_m, k)
    nota_e, _, _ = scoring.calcular_elefante(_snap_e(1e12, 1e12, 1e12, 1e12), 1e12,
                                             refs, p_e, pct_e, p_q, pct_q, k)
    assert _nota_ok(nota_m) and nota_m == pytest.approx(100.0, abs=0.01)
    assert _nota_ok(nota_e) and nota_e == pytest.approx(100.0, abs=0.01)


def test_calcular_valores_validos_inalterados():
    """Sem sujeira, a conta é a mesma de antes (tipos preservados nos detalhes)."""
    p_m, pct_m = scoring._pesos_institucionais("pesos.matific")
    refs = {"max_atividades": 20, "max_media": 90.0, "max_estrelas": 10}
    nota, linhas = scoring.calcular_matific(_snap_m(10, 45.0, 5), refs, p_m, pct_m, {})
    esperado = round(50.0 * p_m.get("atividades", 0) + 50.0 * p_m.get("media", 0)
                     + 50.0 * p_m.get("estrelas", 0), 2)
    assert nota == esperado
    assert [linha["valor"] for linha in linhas] == [10, 45.0, 5]
    assert isinstance(linhas[0]["valor"], int) and linhas[0]["referencia"] == 20


# --- nota_geral (peso negativo na configuração) -----------------------------------

def test_nota_geral_com_peso_negativo_nao_fica_negativa(db, escola_completa):
    """`pesos.geral` = {matific: -50, elefante: 150} SOMA 100 e o PUT aceita, mas
    a nota do aluno com nota_matific > 0 e nota_elefante 0 seria NEGATIVA
    (80 × -0,5 + 0 × 1,5 = -40) — gravada em `Nota.nota_geral` e usada na ordem
    legada. A guarda `_nota_0_100` (a MESMA das notas por dimensão) mantém a nota
    em [0, 100]; os pesos negativos continuam chegando à conta (é isso que o
    teste discrimina), o que muda é só o resultado gravado."""
    from sqlalchemy import select

    from app.models import Configuracao, Importacao, Nota, SnapshotElefante, SnapshotMatific

    escola = escola_completa["escola"]
    linha = db.execute(select(Configuracao).where(
        Configuracao.escola_id == escola.id, Configuracao.namespace == "pesos.geral",
        Configuracao.chave == "valores")).scalar_one()
    linha.valor = {"matific": -50.0, "elefante": 150.0}
    db.add(Configuracao(escola_id=escola.id, namespace=scoring.PERFIL_SCORING_NS,
                        chave="modo", valor="personalizado"))
    importacao = Importacao(escola_id=escola.id, plataforma="matific", tipo="seed")
    db.add(importacao)
    db.flush()
    for i, aluno in enumerate(escola_completa["alunos"]):
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id,
                               importacao_id=importacao.id, atividades=10 * (i + 1),
                               estrelas=40 * (i + 1), pontuacao_media=3.0 + i))
        # Elefante ZERADO: nota_elefante 0 com snapshot presente (o aluno tem as
        # DUAS dimensões, então `pesos_geral_do_aluno` preserva as frações).
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id,
                                importacao_id=importacao.id, livros_unicos=0,
                                tempo_leitura_min=0, questoes_tentativas=0,
                                questoes_acertos=0, livros_por_nivel={}))
    db.commit()

    scoring.recalcular_escola(db, escola.id)
    db.expire_all()

    pesos = scoring.obter_pesos(db, escola.id, "pesos.geral")
    assert pesos == {"matific": -0.5, "elefante": 1.5}          # o PUT aceitou a soma 100
    notas = db.execute(select(Nota).where(Nota.escola_id == escola.id)).scalars().all()
    assert len(notas) == 3
    for nota in notas:
        fracoes = scoring.pesos_geral_do_aluno(pesos, {"matific", "elefante"})
        crua = nota.nota_matific * fracoes["matific"] + nota.nota_elefante * fracoes["elefante"]
        assert nota.nota_elefante == 0.0 and nota.nota_matific > 0
        assert crua < 0                                          # sem a guarda, seria negativa
        assert _nota_ok(nota.nota_geral) and nota.nota_geral == 0.0
    assert sorted(nota.posicao for nota in notas) == [1, 2, 3]   # ordem legada íntegra
