"""O robô de avaliações (coletar_fonte) confere o arquivo baixado antes de gravar —
auditoria S_G_INDICADORES-2. Tudo SINTÉTICO (a fábrica ``_zip_inep`` dos testes: as
células que não são a variável pedida recebem o ÍNDICE da coluna como isca).

O robô baixa sempre a mesma URL e lia o arquivo pelas POSIÇÕES do mapeamento, sem as
conferências do 1 clique: com uma coluna a menos gravava a isca (115,0) como Ideb 2023,
e com o arquivo de Anos Finais gravava o Ideb de anos finais como anos iniciais — sempre
com status 'ok'. Agora:
* no arquivo oficial do INEP, as colunas são achadas pelo NOME da variável e a etapa é
  conferida pelo topo (como no 1 clique);
* nos outros arquivos, o cabeçalho das colunas mapeadas tem de ser o conferido;
* o conferido vem da tela (o arquivo analisado ao montar a fonte) ou, numa fonte antiga,
  da 1ª coleta;
* um número fora da faixa da unidade (Ideb de 0 a 10, percentual de 0 a 100...) recusa o
  arquivo inteiro, também na importação manual. Nada é gravado quando não confere.
"""
import pytest
from sqlalchemy import func, select

from app.models import FonteAvaliacao, ResultadoAvaliacao
from app.services import avaliacoes as svc
from tests.test_avaliacoes import _ANOS_2023, _zip_inep

INEP = "35012345"
URL_INEP = "https://exemplo.invalido/divulgacao_anos_iniciais_escolas_2023.zip"
MAPEAMENTO_INEP = {"linha_dados": 8, "col_inep": 3, "col_valor": 115,
                   "etapa_fixa": "anos_iniciais"}


def _csv(linhas) -> bytes:
    return "\n".join(";".join(c for c in linha) for linha in linhas).encode("utf-8")


def _fonte(db, *, url=URL_INEP, mapeamento=None, unidade="indice"):
    av = svc.obter_avaliacao(db, "ideb")
    f = FonteAvaliacao(avaliacao_id=av.id, nome="IDEB AI 2023 (inventada)", url=url,
                       edicao=2023, indicador="ideb", unidade=unidade, cadencia="manual",
                       mapeamento=dict(mapeamento or MAPEAMENTO_INEP))
    db.add(f)
    db.commit()
    return f


def _gravados(db):
    db.expire_all()
    return sorted(r.valor for r in db.execute(select(ResultadoAvaliacao)).scalars())


def _limpar(db):
    for r in db.execute(select(ResultadoAvaliacao)).scalars():
        db.delete(r)
    db.commit()


def _coletar(db, fonte, arquivo):
    saida = svc.coletar_fonte(db, fonte, baixador=lambda _url: arquivo)
    db.commit()
    return saida


@pytest.fixture()
def escola(db, escola_completa):
    e = escola_completa["escola"]
    e.codigo_inep = INEP
    db.commit()
    return e


def test_arquivo_do_inep_com_uma_coluna_a_menos_e_lido_pelo_nome(db, escola):
    fonte = _fonte(db)
    original = _zip_inep(_ANOS_2023, [(INEP, {"VL_OBSERVADO_2023": "5.9"})])
    assert _coletar(db, fonte, original)["status"] == "ok"
    assert _gravados(db) == [5.9]
    _limpar(db)

    retificado = _zip_inep(_ANOS_2023, [(INEP, {"VL_OBSERVADO_2023": "5.9"})],
                           sem=("VL_APROVACAO_2005_SI",))
    saida = _coletar(db, fonte, retificado)
    assert _gravados(db) == [5.9]                 # a variável certa, não a isca (115)
    assert saida["status"] == "ok", saida
    db.refresh(fonte)
    # A 1ª coleta de uma fonte antiga guardou o que conferiu: a variável e a etapa.
    assert fonte.mapeamento["cabecalho"] == {
        "colunas": {"col_inep": "ID_ESCOLA", "col_valor": "VL_OBSERVADO_2023"},
        "etapa_do_arquivo": "anos_iniciais"}


def test_arquivo_de_anos_finais_na_mesma_url_e_recusado_sem_gravar(db, escola):
    fonte = _fonte(db)
    assert _coletar(db, fonte, _zip_inep(_ANOS_2023, [(INEP, {"VL_OBSERVADO_2023": "5.9"})])
                    )["status"] == "ok"
    _limpar(db)
    finais = _zip_inep(_ANOS_2023, [(INEP, {"VL_OBSERVADO_2023": "4.4"})],
                       etapa=("Anos Finais", "6º ao 9º ano"))
    saida = _coletar(db, fonte, finais)
    assert saida["status"] == "erro", saida
    assert "etapa" in fonte.ultimo_erro and "Nada foi gravado" in fonte.ultimo_erro
    assert _gravados(db) == []


def test_fonte_nova_ja_na_1a_coleta_confere_a_etapa_pela_etapa_fixa(db, escola):
    fonte = _fonte(db)            # sem nada conferido ainda; a etapa fixa é anos_iniciais
    finais = _zip_inep(_ANOS_2023, [(INEP, {"VL_OBSERVADO_2023": "4.4"})],
                       etapa=("Anos Finais", "6º ao 9º ano"))
    assert _coletar(db, fonte, finais)["status"] == "erro"
    assert _gravados(db) == []
    db.refresh(fonte)
    assert "cabecalho" not in fonte.mapeamento     # o que falhou não vira referência


def test_fonte_montada_na_tela_confere_as_colunas_que_o_gestor_viu(db, cliente_global, escola):
    corpo = {"avaliacao": "ideb", "nome": "IDEB AI 2023", "url": URL_INEP, "edicao": 2023,
             "indicador": "ideb", "unidade": "indice", "cadencia": "manual",
             "mapeamento": {**MAPEAMENTO_INEP,
                            "cabecalho": {"col_inep": "ID_ESCOLA",
                                          "col_valor": "VL_OBSERVADO_2023"}}}
    r = cliente_global.post("/api/v1/avaliacoes/fontes", json=corpo)
    assert r.status_code == 201, r.text
    assert r.json()["mapeamento"]["cabecalho"] == {
        "colunas": {"col_inep": "ID_ESCOLA", "col_valor": "VL_OBSERVADO_2023"}}
    fonte = db.get(FonteAvaliacao, r.json()["id"])
    # A URL já serve o arquivo com uma coluna a menos: a 1ª coleta acha pelo nome.
    retificado = _zip_inep(_ANOS_2023, [(INEP, {"VL_OBSERVADO_2023": "5.9"})],
                           sem=("VL_APROVACAO_2005_SI",))
    assert _coletar(db, fonte, retificado)["status"] == "ok"
    assert _gravados(db) == [5.9]


def test_planilha_comum_com_o_cabecalho_mudado_e_recusada(db, escola):
    mapeamento = {"linha_dados": 2, "col_inep": 0, "col_valor": 2,
                  "etapa_fixa": "anos_iniciais"}
    fonte = _fonte(db, url="https://exemplo.invalido/ideb_inventado.csv", mapeamento=mapeamento)
    original = _csv([["Resultados inventados"], ["CO_ESCOLA", "NO_ESCOLA", "IDEB_2023"],
                     [INEP, "EM Inventada", "6,1"]])
    assert _coletar(db, fonte, original)["status"] == "ok"
    _limpar(db)
    trocado = _csv([["Resultados inventados"], ["CO_ESCOLA", "NO_ESCOLA", "TAXA_APROVACAO"],
                    [INEP, "EM Inventada", "7,5"]])
    saida = _coletar(db, fonte, trocado)
    assert saida["status"] == "erro", saida
    assert "IDEB_2023" in fonte.ultimo_erro and "TAXA_APROVACAO" in fonte.ultimo_erro
    assert _gravados(db) == []


def test_numero_fora_da_faixa_recusa_o_arquivo_inteiro(db, escola):
    fonte = _fonte(db, url="https://exemplo.invalido/sem_cabecalho.csv",
                   mapeamento={"linha_dados": 0, "col_inep": 0, "col_valor": 1,
                               "etapa_fixa": "anos_iniciais"})
    saida = _coletar(db, fonte, _csv([[INEP, "115"]]))
    assert saida["status"] == "erro", saida
    assert "de 0 a 10" in fonte.ultimo_erro
    assert _gravados(db) == []

    # A importação manual também recusa (nada gravado), e dentro da faixa grava.
    comum = dict(avaliacao_chave="crianca_alfabetizada", edicao=2025,
                 indicador="taxa_alfabetizacao", unidade="percentual", linha_dados=0,
                 col_inep=0, col_valor=1, etapa_fixa="2_ano", escopo_escolas=None)
    with pytest.raises(svc.ImportacaoRecusada, match="de 0 a 100"):
        svc.importar_resultados(db, _csv([[INEP, "112,5"]]), "manual.csv", **comum)
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 0
    assert svc.importar_resultados(db, _csv([[INEP, "72,5"]]), "manual.csv",
                                   **comum)["inseridos"] == 1
