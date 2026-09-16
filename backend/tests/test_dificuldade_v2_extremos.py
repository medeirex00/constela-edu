"""Dificuldade por livro v2 — casos extremos, guardas e identidade oficial.

A fórmula da v2 é a da v1 (a definida pelo dono):

    pontos = BaseDoNível × clamp(1 + 0,35·ln(wc / mediana)/ln 3, 0,80, 1,35) × FatorSérie

Aqui se prova que ela é positiva e determinística para livros de ~100 e ~751
palavras em níveis de toda a escada, que o fator de série é exato, que o clamp
segura os dois extremos, que nenhuma entrada suja produz NaN, infinito ou valor
negativo, que o fallback de wordCount é auditável e que o livro resolvido pelo id
oficial do Elefante vale o mesmo que o resolvido pelo título."""
import hashlib
import json
import math

import pytest
from sqlalchemy import select

from app.models import Configuracao, Leitura, Livro, Nota
from app.services import dificuldade_livro as dl
from app.services import rede, scoring

NIVEIS = ("AA", "DD", "A", "K", "O", "R", "U", "W", "Z+")
PALAVRAS = (100, 751)
SERIES = ("1º Ano", "2º Ano", "3º Ano", "4º Ano", "5º Ano")
FATORES = (1.40, 1.30, 1.20, 1.10, 1.00)
NAN, INF = float("nan"), float("inf")


def _valido(x) -> bool:
    return isinstance(x, float) and math.isfinite(x) and x >= 0.0


def _esperado(nivel: str, wc: float, fator: float = 1.0) -> float:
    p = dl.PARAMS_VIGENTES
    ajuste = 1 + p["alpha"] * math.log(wc / p["medianas_wordcount"][nivel]) / math.log(p["razao_log"])
    return dl.base_nivel(nivel) * max(p["piso"], min(p["teto"], ajuste)) * fator


def _castelo():
    livro = dl.catalogo().buscar("O Castelo Encantado", "Z")
    assert livro is not None and livro.word_count == 68915
    return livro


def _livro_real(alvo: int):
    """Livro REAL do catálogo com wordCount mais próximo do alvo (determinístico)
    e que o título+nível resolve para ele mesmo (sem homônimo no nível)."""
    cat = dl.catalogo()
    candidatos = [b for b in cat.por_id.values() if cat.buscar(b.titulo, b.nivel) is b]
    return min(candidatos, key=lambda b: (abs(b.word_count - alvo), b.id))


# --- versão -------------------------------------------------------------------------

def test_versao_vigente_e_v2_com_os_mesmos_parametros_da_v1():
    assert dl.VERSAO_VIGENTE == dl.VERSAO_V2 == "elefante_dificuldade_v2"
    assert dl.VERSAO_V1 == "elefante_dificuldade_v1"
    assert dl.RegraV1 is dl.RegraGlobal and dl.RegraGlobal.versao == dl.VERSAO_VIGENTE
    sem_meta_v1 = {k: v for k, v in dl.PARAMS_V1.items() if k != "versao"}
    sem_meta_v2 = {k: v for k, v in dl.PARAMS_V2.items() if k not in ("versao", "mudancas_desde_v1")}
    assert sem_meta_v1 == sem_meta_v2
    assert dl.PARAMS_V2["medianas_wordcount"] is not dl.PARAMS_V1["medianas_wordcount"]   # cópia
    assert dl.PARAMS_V2["versao"] == dl.VERSAO_V2 and dl.PARAMS_V1["versao"] == dl.VERSAO_V1
    assert len(dl.PARAMS_V2["mudancas_desde_v1"]) >= 5
    assert dl.parametros_publicos()["versao"] == dl.VERSAO_V2
    for nivel in NIVEIS:
        for wc in PALAVRAS:
            assert dl.calcular_dificuldade_livro(nivel, wc, "2º Ano", versao=dl.VERSAO_V1) == \
                dl.calcular_dificuldade_livro(nivel, wc, "2º Ano", versao=dl.VERSAO_V2)
    for desconhecida in ("elefante_dificuldade_v3", "", None, "V2"):
        with pytest.raises(ValueError):
            dl.calcular_dificuldade_livro("K", 751, "2º Ano", versao=desconhecida)


# --- livros de ~100 e ~751 palavras pela escada -------------------------------------------

@pytest.mark.parametrize("nivel", NIVEIS)
@pytest.mark.parametrize("wc", PALAVRAS)
def test_pontuacao_positiva_deterministica_e_igual_a_formula(nivel, wc):
    for serie, fator in zip(SERIES, FATORES):
        valores = {dl.calcular_dificuldade_livro(nivel, wc, serie) for _ in range(5)}
        assert len(valores) == 1                                   # determinístico
        valor = valores.pop()
        assert _valido(valor) and valor > 0
        assert valor == pytest.approx(_esperado(nivel, wc, fator), abs=1e-4)


def test_diferenca_dentro_do_mesmo_nivel_e_clamp_nos_extremos():
    for nivel in NIVEIS:
        curto = dl.calcular_dificuldade_livro(nivel, 100, "5º Ano")
        longo = dl.calcular_dificuldade_livro(nivel, 751, "5º Ano")
        assert longo >= curto, nivel                               # monótono no wordCount
    # onde nenhum dos dois bate no clamp, o maior vale mais
    for nivel in ("DD", "A", "K"):
        assert dl.calcular_dificuldade_livro(nivel, 751, "5º Ano") > \
            dl.calcular_dificuldade_livro(nivel, 100, "5º Ano"), nivel
    # AA (mediana 12): 100 e 751 palavras já estão no TETO — valem o mesmo
    assert dl.ajuste_intrinseco("AA", 100) == dl.ajuste_intrinseco("AA", 751) == 1.35
    # O, R, U, W, Z+: 100 e 751 palavras estão no PISO — valem o mesmo
    for nivel in ("O", "R", "U", "W", "Z+"):
        assert dl.ajuste_intrinseco(nivel, 100) == dl.ajuste_intrinseco(nivel, 751) == 0.80, nivel
    assert dl.ajuste_intrinseco("DD", 100) == 1.0                   # exatamente a mediana
    assert dl.ajuste_intrinseco("K", 751) == pytest.approx(1 + 0.35 * math.log(751 / 822) / math.log(3), abs=1e-6)


def test_piso_e_teto_do_clamp_com_valores_extremos():
    p = dl.PARAMS_VIGENTES
    assert dl.ajuste_intrinseco("Z+", 100) == p["piso"]
    assert dl.ajuste_intrinseco("AA", 751) == p["teto"]
    for wc in (1e300, 1.7e308, 10**20):
        assert dl.ajuste_intrinseco("K", wc) == p["teto"]
    for wc in (1e-300, 5e-324, 0.5):                               # 5e-324: razão subnormal
        assert dl.ajuste_intrinseco("K", wc) == p["piso"]
    assert dl.calcular_dificuldade_livro("Z+", 1.7e308, "1º Ano") == \
        pytest.approx(dl.base_nivel("Z+") * 1.35 * 1.40, abs=1e-4)
    assert dl.calcular_dificuldade_livro("AA", 5e-324, "5º Ano") == pytest.approx(0.80, abs=1e-4)


def test_fator_de_serie_exato_e_ordenado():
    for nivel in NIVEIS:
        valores = [dl.calcular_dificuldade_livro(nivel, 751, s) for s in SERIES]
        assert valores == sorted(valores, reverse=True) and len(set(valores)) == 5   # 1º > … > 5º
        for valor, fator in zip(valores, FATORES):
            assert valor / valores[-1] == pytest.approx(fator, rel=1e-3), (nivel, fator)
    assert [dl.fator_serie(s) for s in SERIES] == list(FATORES)
    assert dl.fator_serie("Série desconhecida") == dl.fator_serie(None) == 1.0
    assert dl.fator_serie("6º Ano") == dl.fator_serie("Turma 12345") == 1.0


# --- fallback de wordCount ----------------------------------------------------------------

@pytest.mark.parametrize("sujo, status", [
    (None, "ausente"), ("", "ausente"), ("   ", "ausente"),
    (0, "invalido"), (-5, "invalido"), ("abc", "invalido"), (NAN, "invalido"),
    (INF, "invalido"), (-INF, "invalido"), (True, "invalido"), ([751], "invalido"),
])
def test_word_count_invalido_ou_ausente_cai_no_livro_tipico(sujo, status):
    assert dl.resolver_word_count("K", sujo) == (None, status)
    assert dl.ajuste_intrinseco("K", sujo) == 1.0
    regra = dl.RegraGlobal()
    for serie in SERIES:
        assert dl.calcular_dificuldade_livro("K", sujo, serie) == regra.valor_tipico("K", serie) > 0
    exp = dl.explicar_dificuldade("K", sujo, "1º Ano")
    assert exp["word_count_status"] == status and exp["ajuste_intrinseco"] == 1.0
    json.dumps(exp, allow_nan=False)                               # nada de NaN na explicação


def test_resolver_word_count_valido_e_sem_mediana():
    assert dl.resolver_word_count("K", 751) == (751.0, "catalogo")
    assert dl.resolver_word_count("k", "751") == (751.0, "catalogo")       # texto numérico, nível sem caixa
    assert dl.resolver_word_count("nivel_2", 500) == (500.0, "sem_mediana")   # faixa: sem mediana
    assert dl.resolver_word_count("XYZ", 500) == (500.0, "sem_mediana")
    assert dl.ajuste_intrinseco("nivel_2", 500) == 1.0
    assert dl.explicar_dificuldade("nivel_2", 500, "3º Ano")["word_count_status"] == "sem_mediana"


# --- guardas --------------------------------------------------------------------------------

def test_nivel_desconhecido_vale_zero_nunca_negativo():
    regra = dl.RegraGlobal()
    for nivel in ("XYZ", "", None, "Z++", "-1", "nivel_9"):
        assert dl.base_nivel(nivel) == 0.0
        assert dl.calcular_dificuldade_livro(nivel, 751, "1º Ano") == 0.0
        assert regra.valor_tipico(nivel, "1º Ano") == 0.0
        assert regra.valor_livro(nivel, "O Castelo Encantado", "1º Ano") == 0.0
    assert regra.pontos_por_chave({"XYZ": 3}, "1º Ano") == {"XYZ": 0.0}


def test_contagem_negativa_ou_nao_finita_vale_zero():
    regra = dl.RegraGlobal()
    sujos = {"D": -2, "K": NAN, "N": INF, "O": "abc", "R": None, "U": -INF, "W": -0.5}
    por_chave = regra.pontos_por_chave(sujos, "5º Ano")
    assert por_chave == {chave: 0.0 for chave in sujos}
    assert regra.pontos_aluno(sujos, "5º Ano") == 0.0
    # contagem negativa não "desconta" leitura itemizada: o item vale o seu valor
    castelo = ("O Castelo Encantado", "Z")
    com_item = regra.pontos_por_chave({"Z": -3}, "5º Ano", leituras=[castelo])
    assert com_item == {"Z": pytest.approx(regra.valor_livro("Z", castelo[0], "5º Ano"), abs=1e-4)}
    # contagem válida continua valendo o típico
    assert regra.pontos_por_chave({"D": 2, "K": -1}, "5º Ano") == {
        "D": pytest.approx(2 * regra.valor_tipico("D", "5º Ano"), abs=1e-4), "K": 0.0}


def test_contagem_gigante_satura_em_vez_de_estourar():
    """Inteiro FORA do alcance do float (o JSON aceita `10**400`): a contagem
    satura no teto. Sem isso, `1e308 × típico` estourava para infinito — que a
    guarda de saída zera, ou seja MAIS livros valendo MENOS — e `10**400`
    levantava `OverflowError: int too large to convert to float`."""
    regra = dl.RegraGlobal()
    assert dl._contagem_segura(10**400) == dl._contagem_segura(1e308) == dl.TETO_CONTAGEM
    assert dl._contagem_segura(10**6) == 10**6                      # valor plausível intacto
    referencia = regra.pontos_aluno({"Z+": 10**6}, "5º Ano")
    assert _valido(referencia) and referencia > 0
    for gigante in (10**12, 1e308, 10**400, 10**400 * 7):
        valor = regra.pontos_aluno({"Z+": gigante}, "5º Ano")
        assert _valido(valor) and valor >= referencia, gigante      # monotônico
    por_chave = regra.pontos_por_chave({"Z+": 10**400, "D": 1e308}, "1º Ano")
    assert all(_valido(v) and v > 0 for v in por_chave.values())
    json.dumps(por_chave, allow_nan=False)


def test_varredura_nenhum_nan_infinito_ou_negativo():
    regra = dl.RegraGlobal()
    niveis = list(scoring.NIVEIS_ORDENADOS) + ["Z+", "A+", "pre_leitor", "nivel_5", "XYZ", "", None]
    palavras = (None, 0, -1, 1, 5e-324, 1e-300, 100, 751, 10**6, 1.7e308, NAN, INF, -INF, "abc")
    series = list(SERIES) + [None, "", "Turma 12345", "Terceiro Ano", "EF1 - 3º"]
    for nivel in niveis:
        for serie in series:
            assert _valido(regra.valor_tipico(nivel, serie))
            for wc in palavras:
                valor = dl.calcular_dificuldade_livro(nivel, wc, serie)
                assert _valido(valor), (nivel, wc, serie)
    total = regra.pontos_aluno({"Z": 10**6, "AA": NAN, "D": -9}, "1º Ano")
    assert _valido(total) and total > 0


# --- identidade oficial (elefante_id) ---------------------------------------------------------

def test_resolucao_por_elefante_id_igual_a_resolucao_por_titulo():
    regra = dl.RegraGlobal()
    castelo = _castelo()
    por_titulo = regra.valor_livro("Z", "O Castelo Encantado", "3º Ano")
    por_id = regra.valor_livro("Z", None, "3º Ano", elefante_id=castelo.id)
    assert por_id == por_titulo > regra.valor_tipico("Z", "3º Ano")
    # o id manda sobre um título divergente (renomeado na escola) e aceita id em texto
    assert regra.valor_livro("Z", "Castelo (cópia da escola)", "3º Ano", elefante_id=castelo.id) == por_titulo
    assert regra.valor_livro("Z", None, "3º Ano", elefante_id=str(castelo.id)) == por_titulo
    # livros reais de ~100 e ~751 palavras: id e título dão o MESMO valor
    for alvo in PALAVRAS:
        livro = _livro_real(alvo)
        for serie in SERIES:
            assert regra.valor_livro(livro.nivel, None, serie, elefante_id=livro.id) == \
                regra.valor_livro(livro.nivel, livro.titulo, serie) > 0
    exp_id = regra.explicar("Z", "Título qualquer", "3º Ano", elefante_id=castelo.id)
    assert (exp_id["resolvido_por"], exp_id["word_count_status"], exp_id["elefante_id"]) == \
        ("elefante_id", "catalogo", castelo.id)
    assert exp_id["valor"] == pytest.approx(por_titulo, abs=1e-4)
    exp_titulo = regra.explicar("Z", "O Castelo Encantado", "3º Ano")
    assert exp_titulo["resolvido_por"] == "titulo_nivel" and exp_titulo["elefante_id"] == castelo.id
    assert regra.metadados(None, "Z", elefante_id=castelo.id) == castelo


def test_id_fora_do_catalogo_cai_no_titulo_e_depois_no_tipico():
    regra = dl.RegraGlobal()
    fora = 10**9
    assert dl.catalogo().buscar_por_id(fora) is None
    assert regra.valor_livro("Z", "O Castelo Encantado", "3º Ano", elefante_id=fora) == \
        regra.valor_livro("Z", "O Castelo Encantado", "3º Ano")
    assert regra.valor_livro("Z", "Livro Que Não Existe", "3º Ano", elefante_id=fora) == \
        regra.valor_tipico("Z", "3º Ano")
    exp = regra.explicar("Z", "Livro Que Não Existe", "3º Ano", elefante_id=fora)
    assert exp["resolvido_por"] is None and exp["word_count_status"] == "ausente"
    assert exp["elefante_id"] == fora and exp["encontrado_no_catalogo"] is False
    for sujo in (None, True, "abc", NAN, INF, 1.5):
        assert regra.valor_livro("Z", None, "3º Ano", elefante_id=sujo) == regra.valor_tipico("Z", "3º Ano")
    # id inteiro vindo como float (JSON) resolve igual ao inteiro; fração não resolve
    castelo = _castelo()
    assert regra.valor_livro("Z", None, "3º Ano", elefante_id=float(castelo.id)) == \
        regra.valor_livro("Z", None, "3º Ano", elefante_id=castelo.id)
    assert regra.valor_livro("Z", None, "3º Ano", elefante_id=castelo.id + 0.5) == \
        regra.valor_tipico("Z", "3º Ano")


def test_mesmo_livro_mesmo_nivel_mesmo_catalogo_mesmo_valor():
    pacote = json.loads(dl.CAMINHO_CATALOGO.read_text(encoding="utf-8"))
    nova = dl.RegraGlobal(dl.Catalogo(pacote))                     # outra instância do MESMO arquivo
    atual = dl.RegraGlobal()
    castelo = _castelo()
    for serie in SERIES:
        assert nova.valor_livro("Z", None, serie, elefante_id=castelo.id) == \
            atual.valor_livro("Z", None, serie, elefante_id=castelo.id)
    versao = dl.versao_catalogo()
    assert versao == {"versao": hashlib.sha256(dl.CAMINHO_CATALOGO.read_bytes()).hexdigest()[:12],
                      "n_livros": len(dl.catalogo())}
    versao["versao"] = "mutado"                                    # cópia: o cache não muda
    assert dl.versao_catalogo()["versao"] != "mutado"


def test_leitura_item_quarto_campo_opcional_e_compativel():
    castelo = _castelo()
    item3 = dl.LeituraItem("t", "D", 10)
    assert item3.elefante_id is None and item3[2] == 10 and len(item3) == 4
    item4 = dl.LeituraItem("Título divergente", "Z", 0, castelo.id)
    assert item4.elefante_id == item4[3] == castelo.id
    regra = dl.RegraGlobal()
    assert regra.pontos_por_chave({}, "5º Ano", leituras=[item4]) == {
        "Z": pytest.approx(regra.valor_livro("Z", "O Castelo Encantado", "5º Ano"), abs=1e-4)}
    # tuplas de 2 campos (rankings/premiações) continuam aceitas
    assert regra.pontos_por_chave({}, "5º Ano", leituras=[("O Castelo Encantado", "Z")]) == \
        regra.pontos_por_chave({}, "5º Ano", leituras=[item4])
    insumo = dl.reconciliar_insumo(1, None, [item3, dl.LeituraItem("u", "D", 5, 42)])
    assert (insumo.livros_unicos, insumo.tempo_leitura_min) == (2, 15)


# --- série ----------------------------------------------------------------------------------

@pytest.mark.parametrize("rotulo, esperado", [
    ("Primeiro Ano", 1), ("SEGUNDO ANO", 2), ("terceiro ano", 3), ("Quarto Ano B", 4),
    ("Quinto Ano", 5), ("Primeira Série", 1), ("primeira serie", 1), ("QUARTA SÉRIE", 4),
    ("3.º ano", 3), ("3.º Ano B", 3), ("EF1 - 3º", 3), ("EF1 - 3º Ano", 3), ("3º B", 3),
    ("1º Ano", 1), ("Ano 3", 3), ("5B", 5), ("1ºA", 1), ("3ºD", 3), ("3.º B", 3),
    ("Turma 12345", None), ("Turma 3", None), ("EJA 2", None), ("EF1", None),
    ("Segundo Semestre", None), ("Pré-escola", None),
    # ordinal solto que é etapa/período, ou rótulo da EJA, não vira série
    ("EJA 1ª Etapa", None), ("EJA 2º Segmento", None), ("EJA 3º", None),
    ("Turma A - 3º Período", None), ("EF1 - 2º Bimestre", None),
])
def test_serie_por_extenso_e_rotulos_novos(rotulo, esperado):
    assert dl.serie_numero(rotulo) == esperado


def test_fator_de_serie_por_extenso_igual_ao_numerico():
    for extenso, numerico in (("Primeiro Ano", "1º Ano"), ("Terceiro Ano", "3º Ano"),
                              ("EF1 - 3º", "3º Ano"), ("3.º ano", "3º Ano")):
        assert dl.fator_serie(extenso) == dl.fator_serie(numerico)
        assert dl.calcular_dificuldade_livro("N", 1460, extenso) == \
            dl.calcular_dificuldade_livro("N", 1460, numerico)


# --- banco: regra legada, leituras itemizadas, carimbo e recálculo explícito -------------------

def test_regra_legada_aceita_e_ignora_elefante_id_e_tem_guardas(db, escola_completa):
    esc = escola_completa["escola"]
    db.add(Configuracao(escola_id=esc.id, namespace=scoring.PERFIL_SCORING_NS,
                        chave="modo", valor="personalizado"))
    db.commit()
    legada = dl.regra_da_escola(db, esc.id)
    assert isinstance(legada, dl.RegraEscolaLegada)
    castelo = _castelo()
    assert legada.valor_livro("D", "O Castelo Encantado", "3º Ano", elefante_id=castelo.id) == 4.0
    assert legada.valor_livro("D", None, "3º Ano", 999, elefante_id=castelo.id) == 4.0
    assert legada.explicar("D", None, "3º Ano", elefante_id=castelo.id)["valor"] == 4.0
    assert legada.pontos_aluno({"AA": -2, "D": 3}, "3º Ano") == 12.0
    assert legada.pontos_por_chave({"D": -2, "AA": NAN}, "3º Ano") == {"D": 0.0, "AA": 0.0}


def test_leituras_carregam_elefante_id_e_nota_carimba_v2_e_catalogo(db, escola_completa):
    esc, aluno = escola_completa["escola"], escola_completa["alunos"][0]
    castelo = _castelo()
    livro = Livro(escola_id=esc.id, titulo="Castelo (título da escola)", nivel_codigo="Z",
                  elefante_id=castelo.id)
    db.add(livro)
    db.flush()
    db.add(Leitura(escola_id=esc.id, aluno_id=aluno.id, livro_id=livro.id, tempo_leitura_min=30))
    db.commit()

    itens = dl.leituras_por_aluno(db, esc.id)[aluno.id]
    assert itens == [dl.LeituraItem("Castelo (título da escola)", "Z", 30, castelo.id)]

    scoring.recalcular_escola(db, esc.id)
    nota = db.execute(select(Nota).where(Nota.aluno_id == aluno.id)).scalar_one()
    esperado = dl.RegraGlobal().valor_livro("Z", "O Castelo Encantado", "3º Ano")
    assert nota.detalhes["dimensoes"]["leitura"]["dados"]["pontos_dificuldade"] == pytest.approx(esperado, abs=0.01)
    assert esperado > dl.RegraGlobal().valor_tipico("Z", "3º Ano")          # veio pelo id, não pelo típico
    dificuldade = nota.detalhes["elefante"]["dificuldade"]
    assert dificuldade["versao"] == dl.VERSAO_VIGENTE == "elefante_dificuldade_v2"
    assert dificuldade["catalogo"] == dl.versao_catalogo()
    assert len(dificuldade["catalogo"]["versao"]) == 12 and dificuldade["catalogo"]["n_livros"] >= 752
    assert nota.detalhes["regua_institucional"]["versao_dificuldade"] == dl.VERSAO_VIGENTE


def test_pendentes_inclui_nota_carimbada_com_versao_antiga_sem_recalcular_sozinho(db, escola_completa):
    from scripts import recalcular_institucional as script

    esc = escola_completa["escola"]
    scoring.recalcular_escola(db, esc.id)
    assert script.escolas_com_versao_desatualizada(db) == []
    assert esc.id not in script.escolas_pendentes(db)

    # uma Nota gravada pela régua anterior (carimbo v1)
    nota = db.execute(select(Nota).where(Nota.escola_id == esc.id)).scalars().first()
    nota.detalhes = {**nota.detalhes, "regua_institucional": {
        "versao_dificuldade": dl.VERSAO_V1, "perfil_local": "institucional"}}
    db.commit()
    assert script.escolas_com_versao_desatualizada(db) == [esc.id]
    assert esc.id in script.escolas_pendentes(db)
    # A rede continua AGREGANDO a nota v1 (ela tem carimbo) — nada é recalculado
    # até a ação explícita. O painel, porém, passa a listá-la como PENDENTE: desde
    # esta rodada `rede._pendentes_recalculo` usa a mesma regra do `--pendentes`
    # (sem carimbo OU versão ≠ da vigente), senão a régua antiga ficava invisível.
    assert esc.id in rede.escolas_com_notas_pendentes(db)
    db.refresh(nota)
    assert nota.detalhes["regua_institucional"]["versao_dificuldade"] == dl.VERSAO_V1

    scoring.recalcular_escola(db, esc.id)                           # recálculo EXPLÍCITO
    assert script.escolas_com_versao_desatualizada(db) == []        # idempotente


def test_main_do_script_com_pendentes_usa_a_selecao_por_versao(db, escola_completa, monkeypatch, capsys):
    """O ``--pendentes`` do ``main()`` (não só o helper) pega a escola com nota v1."""
    import sys

    from scripts import recalcular_institucional as script

    class _SessaoSemFechar:                       # main() fecha a sessão no finally
        def __init__(self, sessao):
            self._sessao = sessao

        def __getattr__(self, nome):
            return getattr(self._sessao, nome)

        def close(self):
            pass

    esc_id = escola_completa["escola"].id
    scoring.recalcular_escola(db, esc_id)
    nota = db.execute(select(Nota).where(Nota.escola_id == esc_id)).scalars().first()
    nota.detalhes = {**nota.detalhes, "regua_institucional": {
        "versao_dificuldade": dl.VERSAO_V1, "perfil_local": "institucional"}}
    db.commit()
    # tem carimbo (v1): a rede AGREGA a nota, e desde esta rodada também a conta
    # como pendente de recálculo (mesma regra do `--pendentes`).
    assert esc_id in rede.escolas_com_notas_pendentes(db)
    monkeypatch.setattr(script, "SessionLocal", lambda: _SessaoSemFechar(db))

    monkeypatch.setattr(sys, "argv", ["recalcular_institucional", "--pendentes", "--dry-run"])
    assert script.main() == 0
    saida = capsys.readouterr().out
    assert "Escolas a recalcular: 1" in saida and f"escola {esc_id} " in saida
    assert script.escolas_com_versao_desatualizada(db) == [esc_id]  # dry-run não grava

    monkeypatch.setattr(sys, "argv", ["recalcular_institucional", "--pendentes"])
    assert script.main() == 0
    assert script.escolas_pendentes(db) == []                       # idempotente
    monkeypatch.setattr(sys, "argv", ["recalcular_institucional", "--pendentes", "--dry-run"])
    assert script.main() == 0
    assert "Escolas a recalcular: 0" in capsys.readouterr().out


def test_word_count_gigante_satura_no_teto_em_vez_de_virar_invalido():
    """Inteiro FORA do alcance do float como wordCount (`10**400`, que o JSON
    aceita): satura no maior float finito e recebe a MESMA leitura que `1e308` —
    outlier gigante, ajuste no TETO. Antes havia um degrau para o mesmo tipo de
    sujeira: `1e308` valia 1,35 e `10**400` caía em `invalido` (1,0, o livro
    TÍPICO do nível)."""
    import sys

    teto = dl.PARAMS_VIGENTES["teto"]
    wc_gigante, status_gigante = dl.resolver_word_count("K", 10**400)
    assert (wc_gigante, status_gigante) == (sys.float_info.max, "catalogo")
    assert dl.resolver_word_count("K", 1e308) == (1e308, "catalogo")
    assert dl.ajuste_intrinseco("K", 10**400) == dl.ajuste_intrinseco("K", 1e308) == teto
    # gigante NEGATIVO continua inválido: o livro vale o típico do nível
    assert dl.resolver_word_count("K", -(10**400)) == (None, "invalido")
    assert dl.ajuste_intrinseco("K", -(10**400)) == 1.0
    exp = dl.explicar_dificuldade("K", 10**400, "1º Ano")
    assert exp["word_count_status"] == "catalogo" and exp["ajuste_intrinseco"] == teto
    json.dumps(exp, allow_nan=False)
    valor = dl.calcular_dificuldade_livro("K", 10**400, "1º Ano")
    assert _valido(valor) and valor > 0
