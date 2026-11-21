"""Regressão G_INDICADORES-3: o ruído binário do float da planilha do INEP não vira a
precisão PUBLICADA do Ideb por escola.

A planilha às vezes grava o número com o ruído do float (0,58 × 100 vira
57.99999999999999). O parser por escola escrevia a célula com ``repr`` e as casas desse
texto viravam a precisão da COLUNA (``leitura.casas``) e o ``casas_decimais`` gravado
de N, P, aprovação e meta: a tela mostrava "57,99999999999999%" — e todas as escolas da
coluna com 14 casas. O parser do território e o da planilha do Saeb já limpavam.

A limpeza vale na planilha (float) e no TEXTO do CSV do pacote — inclusive no pacote
gerado antes da correção, que traz o ruído escrito. Tudo SINTÉTICO (as fábricas do
teste da E6a: município, INEPs e números inventados).
"""
from app.services.indicadores import consulta_ideb, ideb, ideb_territorio, pacote_ideb, preparar
from tests.test_indicadores_ideb import AGORA, ALFA, BETA, MUN, _aplicar, _linhas, planilha, zip_ideb
from tests.test_indicadores_ideb_consulta import rede  # noqa: F401 — fixture

RUIDO_APROV = 0.58 * 100            # 57.99999999999999 (float): o "58" da planilha
RUIDO_N = 2.381946 + 1e-15          # 2.3819460000000006 (float): o "2,381946"
COL_APROV = "VL_APROVACAO_2019_SI_4"
COL_N = "VL_NOTA_MEDIA_2019"


def _planilha_com_ruido() -> bytes:
    alfa = {**ALFA, "valores": {**ALFA["valores"], COL_APROV: RUIDO_APROV, COL_N: RUIDO_N}}
    return planilha([alfa, BETA])


def test_ruido_do_float_nao_vira_a_precisao_da_coluna_nem_entra_no_pacote():
    assert repr(RUIDO_APROV) == "57.99999999999999" and len(repr(RUIDO_N).split(".")[1]) > 6
    linhas = _linhas(_planilha_com_ruido())
    lido = ideb.ler_grade(linhas, codigo_ibge=MUN)
    assert lido.casas[COL_APROV] == 1, "a precisão da coluna é a do ruído do float"
    assert lido.casas[COL_N] == 6
    alfa = next(e for e in lido.escolas if e.inep == "35990101")
    assert (alfa.celulas[COL_APROV].valor, alfa.celulas[COL_APROV].casas) == (58.0, 0)
    assert alfa.celulas[COL_N].valor == 2.381946
    # O CSV do pacote leva o número limpo — o mesmo texto do parser do território.
    csv = pacote_ideb.csv_do_recorte(lido).decode("utf-8")
    assert "57.99999999999999" not in csv and repr(RUIDO_N) not in csv
    assert ideb_territorio.texto_limpo(RUIDO_APROV) == "58"


def test_pacote_antigo_com_o_ruido_escrito_no_texto_tambem_sai_limpo():
    """O pacote gerado antes da correção traz o ``repr`` do float no CSV (texto): a
    leitura do servidor limpa do mesmo jeito (reimportá-lo corrige o que foi gravado)."""
    texto = [[ideb.texto_celula(c) for c in (linha or ())] for linha in
             _linhas(_planilha_com_ruido())]
    assert any("57.99999999999999" in linha for linha in texto)
    lido = ideb.ler_grade(texto, codigo_ibge=MUN)
    assert lido.casas[COL_APROV] == 1 and lido.casas[COL_N] == 6
    alfa = next(e for e in lido.escolas if e.inep == "35990101")
    assert alfa.celulas[COL_APROV].valor == 58.0


def test_numero_sem_ruido_fica_como_estava():
    # Zero final, vírgula e asterisco do INEP, 6 casas publicadas: nada muda.
    for valor, texto in ((6.0, "6.0"), ("123,47*", "123,47*"), (2.381946, "2.381946"),
                         ("ND", "ND"), (35990101, "35990101"), ("1.50", "1.50")):
        assert ideb.texto_sem_ruido(valor) == texto


def test_ideb_por_escola_na_tela_com_a_precisao_publicada(db, rede, tmp_path):
    caminho = tmp_path / "ideb.zip"
    caminho.write_bytes(zip_ideb(_planilha_com_ruido()))
    pacote = preparar.preparar_ideb(codigo_ibge=MUN, zip_local=caminho, agora=AGORA,
                                    url="https://exemplo.invalido/ideb_sintetico.zip").pacote
    _aplicar(db, rede, pacote)
    db.expire_all()
    d = consulta_ideb.ideb_da_rede(db, rede)
    linha = next(x for x in d["escolas"] if x["nome"] == "EMEF Sintética Alfa")
    e19 = next(x for x in linha["serie"] if x["edicao"] == 2019)
    aprov = e19["aprovacao"]["anos_iniciais"]
    assert aprov["casas_decimais"] == 1 and aprov["valor"] == 58.0
    assert e19["nota_n"]["casas_decimais"] == 6 and e19["nota_n"]["valor"] == 2.381946
    beta = next(x for x in d["escolas"] if x["nome"] == "EMEF Sintética Beta")
    b19 = next(x for x in beta["serie"] if x["edicao"] == 2019)
    assert b19["aprovacao"]["anos_iniciais"]["casas_decimais"] == 1   # a coluna inteira
