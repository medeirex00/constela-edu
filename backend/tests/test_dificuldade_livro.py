"""Dificuldade por LIVRO (v1) — a fórmula pura, o catálogo e a resolução da regra.

Cobre os requisitos 1–9 e 16 do mandato: determinismo, série, ajuste limitado,
outlier, livro minúsculo, coerência dos níveis, fallback sem metadado, livro novo,
histórico protegido (parâmetros congelados) e execução repetida idêntica."""
import json
import math
import statistics

import pytest

from app.models import Configuracao
from app.services import dificuldade_livro as dl
from app.services import scoring


# --- fórmula pura -------------------------------------------------------------

def test_mesmo_livro_mesmo_aluno_mesmo_valor_em_execucoes_repetidas():
    a = [dl.calcular_dificuldade_livro("N", 1460, "3º Ano") for _ in range(5)]
    assert len(set(a)) == 1 and a[0] > 0


def test_base_e_a_a3_intocada_e_estendida_para_z_mais_e_faixas():
    for codigo in scoring.NIVEIS_ORDENADOS:            # AA..Z = exatamente a A3
        assert dl.base_nivel(codigo) == pytest.approx(scoring.peso_a3(codigo), abs=1e-5)
    assert dl.base_nivel("Z+") == pytest.approx(math.exp(scoring.A3_COEFICIENTE * 30), abs=1e-5)
    assert dl.base_nivel("Z+") > dl.base_nivel("Z")
    assert dl.base_nivel("A") < dl.base_nivel("A+") < dl.base_nivel("B")   # A+ provisório
    assert dl.base_nivel("nivel_2") == pytest.approx(math.exp(scoring.A3_COEFICIENTE * 10), abs=1e-5)
    assert dl.base_nivel("pre_leitor") < dl.base_nivel("nivel_1") < dl.base_nivel("nivel_5")
    assert dl.base_nivel("XYZ") == 0.0 and dl.base_nivel("") == 0.0     # sujo → 0, como a A3


def test_hierarquia_monotona_e_livro_excepcional_nunca_passa_do_tipico_3_letras_acima():
    ordem = list(scoring.NIVEIS_ORDENADOS) + ["Z+"]
    tipicos = [dl.RegraV1().valor_tipico(c, "5º Ano") for c in ordem]
    assert tipicos == sorted(tipicos)                                   # AA→Z→Z+ cresce
    # +35 % (teto) < 3 degraus da escada (exp(0,103·3) = 1,362): um livro
    # excepcional se APROXIMA da faixa seguinte mas não ultrapassa o típico de 3 letras acima.
    assert dl.PARAMS_V1["teto"] < math.exp(scoring.A3_COEFICIENTE * 3)
    for i, c in enumerate(scoring.NIVEIS_ORDENADOS[:-3]):
        assert dl.base_nivel(c) * dl.PARAMS_V1["teto"] < dl.base_nivel(scoring.NIVEIS_ORDENADOS[i + 3])


def test_livro_maior_no_mesmo_nivel_vale_mais_mas_limitado_ao_teto():
    med = dl.mediana_nivel("N")
    tipico = dl.calcular_dificuldade_livro("N", med, "5º Ano")
    dobro = dl.calcular_dificuldade_livro("N", 2 * med, "5º Ano")
    triplo = dl.calcular_dificuldade_livro("N", 3 * med, "5º Ano")
    dez_x = dl.calcular_dificuldade_livro("N", 10 * med, "5º Ano")
    assert tipico < dobro < triplo
    assert dobro == pytest.approx(tipico * (1 + 0.35 * math.log(2) / math.log(3)), rel=1e-4)
    assert triplo == pytest.approx(tipico * dl.PARAMS_V1["teto"], rel=1e-4)   # 3× = teto exato
    assert dez_x == triplo                                                    # além do teto: nada


def test_outlier_gigante_nao_explode_e_livro_minusculo_nao_zera():
    z_gigante = dl.calcular_dificuldade_livro("Z", 68915, "5º Ano")       # 9,3× a mediana do Z
    assert z_gigante == pytest.approx(dl.base_nivel("Z") * 1.35, rel=1e-4)
    r_minusculo = dl.calcular_dificuldade_livro("R", 15, "5º Ano")        # 0,004× a mediana do R
    assert r_minusculo == pytest.approx(dl.base_nivel("R") * 0.80, rel=1e-4)
    assert r_minusculo > dl.calcular_dificuldade_livro("H", 10_000, "5º Ano")  # nível ainda manda


def test_serie_muda_o_valor_da_mesma_leitura_conforme_a_regra():
    valores = [dl.calcular_dificuldade_livro("N", 1460, f"{s}º Ano") for s in (1, 2, 3, 4, 5)]
    assert valores == sorted(valores, reverse=True)
    assert valores[0] == pytest.approx(valores[4] * 1.40, rel=1e-4)
    assert valores[2] == pytest.approx(valores[4] * 1.20, rel=1e-4)
    assert dl.fator_serie("4º Ano B") == 1.10 and dl.fator_serie("Pré") == 1.0
    assert dl.fator_serie(None) == 1.0 and dl.fator_serie("6º Ano") == 1.0


def test_sem_metadado_o_fallback_e_deterministico_e_igual_ao_tipico():
    regra = dl.RegraV1()
    assert dl.ajuste_intrinseco("N", None) == 1.0 and dl.ajuste_intrinseco("N", 0) == 1.0
    assert dl.ajuste_intrinseco("N", "abc") == 1.0
    novo = regra.valor_livro("N", "Título Que Não Existe No Catálogo", "3º Ano")
    assert novo == regra.valor_tipico("N", "3º Ano") > 0
    assert regra.valor_livro("N", None, "3º Ano") == regra.valor_tipico("N", "3º Ano")
    with pytest.raises(ValueError):
        dl.calcular_dificuldade_livro("N", 100, "3º Ano", versao="elefante_dificuldade_v9")


# --- catálogo de referência ----------------------------------------------------

def test_catalogo_carrega_e_casa_titulos_sem_depender_de_acento_ou_caixa():
    cat = dl.catalogo()
    assert len(cat) >= 752
    livro = cat.buscar("o castelo encantado", "Z")
    assert livro is not None and livro.word_count == 68915
    assert cat.buscar("O CASTELO ENCANTADO", "z").id == livro.id
    assert cat.buscar("Alice Através do Espelho", "Z+").word_count == 26638   # tier Z+
    assert cat.buscar("Não Existe Este Livro", "A") is None


def test_parametros_congelados_batem_com_a_calibracao_e_nao_sao_mutaveis_em_runtime():
    """Histórico protegido: as medianas são CONSTANTES da versão. Com o catálogo de
    calibração (752) elas batem exatamente; um catálogo atualizado só pode
    desviá-las levemente (senão é hora de uma v2 explícita, não de editar a v1)."""
    cat = dl.catalogo()
    por_nivel: dict[str, list[int]] = {}
    for livro in cat.por_id.values():
        por_nivel.setdefault(livro.nivel, []).append(livro.word_count)
    for nivel, wcs in por_nivel.items():
        med = statistics.median(wcs)
        congelada = dl.PARAMS_V1["medianas_wordcount"][nivel]
        if len(cat) == dl.PARAMS_V1["calibracao"]["n_livros"]:
            assert med == congelada, nivel
        else:
            assert abs(med - congelada) <= 0.25 * congelada, nivel
    copia = dl.parametros_publicos()
    copia["alpha"] = 99.0                          # alterar a cópia não altera a regra
    assert dl.PARAMS_V1["alpha"] == 0.35
    assert dl.calcular_dificuldade_livro("N", 1460, "5º Ano") == pytest.approx(dl.base_nivel("N"), abs=1e-4)


def test_livro_novo_recebe_valor_automaticamente_e_o_do_tier_z_mais_vale_mais_que_z():
    regra = dl.RegraV1()
    assert regra.valor_livro("Z+", "A história do doutor Dolittle", "5º Ano") > regra.valor_tipico("Z", "5º Ano")
    # livro que ainda não está no catálogo (será acrescentado num próximo extrato)
    assert regra.valor_livro("Q", "Livro Novíssimo 2027", "2º Ano") == regra.valor_tipico("Q", "2º Ano")


def test_explicacao_decompoe_o_valor_de_forma_consistente():
    regra = dl.RegraV1()
    exp = regra.explicar("Z", "O Castelo Encantado", "1º Ano")
    assert exp["encontrado_no_catalogo"] is True and exp["word_count"] == 68915
    assert exp["valor"] == pytest.approx(
        exp["base_nivel"] * exp["ajuste_intrinseco"] * exp["fator_serie"], abs=1e-4)
    assert exp["fator_serie"] == 1.40 and exp["ajuste_intrinseco"] == 1.35
    assert exp["valor"] == pytest.approx(regra.valor_livro("Z", "O Castelo Encantado", "1º Ano"), abs=1e-4)


# --- híbrido snapshot + leituras itemizadas -------------------------------------

def test_hibrido_itemizados_valem_o_proprio_valor_e_o_restante_vale_o_tipico():
    regra = dl.RegraV1()
    leituras = [("O Castelo Encantado", "Z"), ("A coragem das coisas simples", "Z")]
    por_chave = regra.pontos_por_chave({"Z": 3, "D": 2}, "5º Ano", leituras=leituras)
    esperado_z = (regra.valor_livro("Z", "O Castelo Encantado", "5º Ano")
                  + regra.valor_livro("Z", "A coragem das coisas simples", "5º Ano")
                  + 1 * regra.valor_tipico("Z", "5º Ano"))
    assert por_chave["Z"] == pytest.approx(esperado_z, rel=1e-4)
    assert por_chave["D"] == pytest.approx(2 * regra.valor_tipico("D", "5º Ano"), rel=1e-4)
    assert regra.pontos_aluno({"Z": 3, "D": 2}, "5º Ano", leituras=leituras) == \
        pytest.approx(round(por_chave["Z"] + por_chave["D"], 2), abs=0.01)


def test_hibrido_snapshot_velho_usa_so_os_itemizados_e_contagem_negativa_vale_zero():
    regra = dl.RegraV1()
    leituras = [("O Castelo Encantado", "Z"), ("A coragem das coisas simples", "Z")]
    por_chave = regra.pontos_por_chave({"Z": 1}, "5º Ano", leituras=leituras)    # contagem < itens
    assert por_chave["Z"] == pytest.approx(sum(regra.valor_livro("Z", t, "5º Ano") for t, _ in leituras), rel=1e-4)
    sem_snapshot = regra.pontos_por_chave({}, "5º Ano", leituras=[("Domingo", "A")])
    assert sem_snapshot == {"A": pytest.approx(regra.valor_livro("A", "Domingo", "5º Ano"), rel=1e-4)}
    # Guarda da v2 (regra do dono): contagem negativa vale 0 — um snapshot manual
    # não subtrai pontos, e a evolução só passa ganhos positivos (_delta_niveis).
    # Na v1 o delta negativo passava como estava (−2 × típico).
    delta = regra.pontos_por_chave({"D": -2}, "5º Ano")
    assert delta == {"D": 0.0}
    assert regra.pontos_por_chave({"nivel_2": 2, "aa": 1}, "1º Ano") == {
        "nivel_2": pytest.approx(2 * regra.valor_tipico("nivel_2", "1º Ano"), rel=1e-4),
        "aa": pytest.approx(1 * regra.valor_tipico("AA", "1º Ano"), rel=1e-4)}


# --- resolução da regra por escola ------------------------------------------------

def test_escola_padrao_usa_a_v1_global_e_personalizada_usa_o_override_legado(db, escola_completa):
    esc = escola_completa["escola"]
    assert isinstance(dl.regra_da_escola(db, esc.id), dl.RegraV1)
    assert isinstance(dl.regra_institucional(), dl.RegraV1)
    db.add(Configuracao(escola_id=esc.id, namespace=scoring.PERFIL_SCORING_NS,
                        chave="modo", valor="personalizado"))
    db.commit()
    legada = dl.regra_da_escola(db, esc.id)
    assert isinstance(legada, dl.RegraEscolaLegada) and legada.versao == dl.VERSAO_LEGADA
    # a legada é a régua por faixa da fixture (AA/BB=1, D/E=4), igual para qualquer livro do nível
    assert legada.valor_livro("D", "O Castelo Encantado", "3º Ano") == 4.0
    assert legada.valor_livro("AA", None, "1º Ano") == 1.0
    assert legada.pontos_aluno({"AA": 2, "D": 3}, "3º Ano") == 2 * 1.0 + 3 * 4.0
    # e a institucional da MESMA escola continua sendo a v1 (a rede não vê o override)
    assert dl.regra_institucional().valor_livro("D", None, "3º Ano") == \
        pytest.approx(dl.base_nivel("D") * 1.20, rel=1e-4)


def test_duas_escolas_com_os_mesmos_dados_recebem_o_mesmo_valor_pela_regra_global(db, escola_completa):
    from app.models import Escola
    outra = Escola(nome="Outra Escola", cidade="X", ano_letivo_ativo=2026)
    db.add(outra)
    db.commit()
    r1 = dl.regra_da_escola(db, escola_completa["escola"].id)
    r2 = dl.regra_da_escola(db, outra.id)
    for nivel, titulo, serie in (("Z", "O Castelo Encantado", "1º Ano"), ("D", "Domingo", "4º Ano")):
        assert r1.valor_livro(nivel, titulo, serie) == r2.valor_livro(nivel, titulo, serie)


def test_parametros_publicos_sao_json_serializaveis_e_carimbam_a_versao():
    p = dl.parametros_publicos()
    # o sentido é "carimba a versão VIGENTE" (hoje a v2): a constante, não o literal
    assert json.dumps(p) and p["versao"] == dl.VERSAO_VIGENTE
    assert set(p["fator_serie"]) == {"1", "2", "3", "4", "5"} or set(p["fator_serie"]) == {1, 2, 3, 4, 5}
