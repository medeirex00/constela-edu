"""O robô de avaliações não adota como referência o que a 1ª coleta não conferiu —
revisão REV3-INDIC-2 (sobre S_G_INDICADORES-2). Tudo SINTÉTICO (a fábrica ``_zip_inep`` dos
testes; INEP e URL inventados).

Num arquivo oficial do INEP sem referência guardada, a 1ª coleta lia o NOME que estivesse
na posição mapeada e adotava a etapa que o topo do arquivo declarasse, gravando com status
'ok' e guardando o erro como referência das coletas seguintes:
* V1 — fonte sem ``cabecalho`` (antiga, ou criada pela API) e a URL já serve o arquivo com
  uma coluna a menos: a vizinha VL_PROJECAO_2007 (4,2, dentro da faixa do Ideb) virava o
  "Ideb 2023";
* V2 — fonte montada na tela sem etapa fixa (o preset do IDEB não a preenche): a tela
  mandava só os nomes das colunas, iguais em Anos Iniciais e Anos Finais, e a 1ª coleta
  aceitava o arquivo de Anos Finais.
Agora a tela manda as linhas do topo do arquivo conferido (o backend tira delas a etapa) e,
sem referência, a coluna do valor tem de ser uma variável da edição da fonte (como o
VL_OBSERVADO_{edição} do 1 clique) e a etapa tem de vir do que foi conferido ou da etapa
fixa. Nada é gravado e nada vira referência quando não confere.
"""
import pytest
from sqlalchemy import select

from app.models import FonteAvaliacao, ResultadoAvaliacao
from app.services import avaliacoes as svc
from tests.test_avaliacoes import _ANOS_2023, _variaveis_inep, _zip_inep

INEP = "35012345"
URL = "https://exemplo.invalido/divulgacao_anos_iniciais_escolas_2023.zip"
FINAIS = ("Anos Finais", "6º ao 9º ano")
# As linhas do topo do arquivo de Anos Iniciais como a tela as mostra (``primeiras_linhas``,
# sem as células vazias), até a linha técnica — a linha antes dos dados (linha_dados 8).
TOPO_INICIAIS = [
    ["Ministério da Educação"],
    ["Instituto Nacional de Estudos e Pesquisas Educacionais"],
    ["Ensino Fundamental Regular - Anos Iniciais"],
    ["Indicadores nos anos de 2005 a 2023 (sintético)"],
    ["Sigla da UF", "Código do Município", "Nome do Município", "Código da Escola",
     "Nome da Escola", "Rede", "Taxa de Aprovação"],
    ["Matemática", "Língua Portuguesa", "Nota Média"],
    ["1º ao 5º ano", "1º", "2º", "3º", "4º"],
    _variaveis_inep(_ANOS_2023),
]
CABECALHO_DA_TELA = {"col_inep": "ID_ESCOLA", "col_valor": "VL_OBSERVADO_2023"}


@pytest.fixture()
def escola(db, escola_completa):
    e = escola_completa["escola"]
    e.codigo_inep = INEP
    db.commit()
    return e


def _gravados(db):
    db.expire_all()
    return [(r.valor, r.etapa) for r in db.execute(select(ResultadoAvaliacao)).scalars()]


def _coletar(db, fonte, arquivo):
    saida = svc.coletar_fonte(db, fonte, baixador=lambda _u: arquivo)
    db.commit()
    db.refresh(fonte)
    return saida


def _pela_tela(db, cliente, *, etapa_fixa=None, topo=None):
    mapeamento = {"linha_dados": 8, "col_inep": 3, "col_valor": 115, "etapa_fixa": etapa_fixa,
                  "cabecalho": CABECALHO_DA_TELA}
    if topo is not None:
        mapeamento["topo"] = topo
    r = cliente.post("/api/v1/avaliacoes/fontes", json={
        "avaliacao": "ideb", "nome": "IDEB 2023", "url": URL, "edicao": 2023,
        "indicador": "ideb", "unidade": "indice", "cadencia": "manual",
        "mapeamento": mapeamento})
    assert r.status_code == 201, r.text
    return db.get(FonteAvaliacao, r.json()["id"]), r.json()


def test_v1_fonte_sem_referencia_nao_adota_a_vizinha_da_coluna_do_valor(db, escola):
    av = svc.obter_avaliacao(db, "ideb")
    fonte = FonteAvaliacao(avaliacao_id=av.id, nome="IDEB AI 2023 (inventada)", url=URL,
                           edicao=2023, indicador="ideb", unidade="indice", cadencia="manual",
                           mapeamento={"linha_dados": 8, "col_inep": 3, "col_valor": 115,
                                       "etapa_fixa": "anos_iniciais"})
    db.add(fonte)
    db.commit()
    arquivo = _zip_inep(_ANOS_2023, [(INEP, {"VL_OBSERVADO_2023": "5.9",
                                             "VL_PROJECAO_2007": "4.2"})],
                        sem=("VL_APROVACAO_2005_SI",))
    saida = _coletar(db, fonte, arquivo)
    assert saida["status"] == "erro", (
        f"a 1ª coleta gravou {_gravados(db)} como Ideb 2023 e guardou "
        f"{fonte.mapeamento.get('cabecalho')} como referência")
    assert "VL_PROJECAO_2007" in fonte.ultimo_erro and "2023" in fonte.ultimo_erro
    assert "Nada foi gravado" in fonte.ultimo_erro
    assert _gravados(db) == []
    assert "cabecalho" not in fonte.mapeamento         # o que falhou não vira referência


def test_v2_fonte_da_tela_sem_etapa_conferida_nem_fixa_nao_adota_a_etapa_do_topo(
        db, cliente_global, escola):
    fonte, _ = _pela_tela(db, cliente_global)          # a tela antiga: sem as linhas do topo
    finais = _zip_inep(_ANOS_2023, [(INEP, {"VL_OBSERVADO_2023": "4.4"})], etapa=FINAIS)
    saida = _coletar(db, fonte, finais)
    assert saida["status"] == "erro", (
        f"o arquivo de Anos Finais foi aceito: gravou {_gravados(db)} e a referência virou "
        f"{fonte.mapeamento.get('cabecalho')}")
    assert "etapa" in fonte.ultimo_erro and "Nada foi gravado" in fonte.ultimo_erro
    assert _gravados(db) == []
    assert fonte.mapeamento["cabecalho"] == {"colunas": CABECALHO_DA_TELA}  # nada adotado


def test_fonte_da_tela_guarda_a_etapa_do_arquivo_conferido_e_recusa_outra_etapa(
        db, cliente_global, escola):
    fonte, saida_api = _pela_tela(db, cliente_global, topo=TOPO_INICIAIS)
    assert saida_api["mapeamento"]["cabecalho"] == {
        "colunas": CABECALHO_DA_TELA, "etapa_do_arquivo": "anos_iniciais"}
    assert "topo" not in saida_api["mapeamento"]       # só a etapa tirada dele fica guardada

    finais = _zip_inep(_ANOS_2023, [(INEP, {"VL_OBSERVADO_2023": "4.4"})], etapa=FINAIS)
    assert _coletar(db, fonte, finais)["status"] == "erro"
    assert _gravados(db) == []
    iniciais = _zip_inep(_ANOS_2023, [(INEP, {"VL_OBSERVADO_2023": "5.9"})],
                         sem=("VL_APROVACAO_2005_SI",))
    assert _coletar(db, fonte, iniciais)["status"] == "ok", fonte.ultimo_erro
    assert [v for v, _ in _gravados(db)] == [5.9]


def test_topo_de_uma_planilha_comum_nao_vira_etapa_do_inep(db, cliente_global, escola):
    """As linhas do topo de um arquivo que não é o do INEP (sem a linha técnica) não dão
    etapa: a fonte de planilha comum segue conferida só pelo cabeçalho."""
    r = cliente_global.post("/api/v1/avaliacoes/fontes", json={
        "avaliacao": "ideb", "nome": "IDEB inventado", "edicao": 2023,
        "url": "https://exemplo.invalido/ideb_inventado.csv",
        "indicador": "ideb", "unidade": "indice", "cadencia": "manual",
        "mapeamento": {"linha_dados": 2, "col_inep": 0, "col_valor": 2,
                       "cabecalho": {"col_inep": "CO_ESCOLA", "col_valor": "IDEB_2023"},
                       "topo": [["Resultados inventados - Anos Iniciais"],
                                ["CO_ESCOLA", "NO_ESCOLA", "IDEB_2023"]]}})
    assert r.status_code == 201, r.text
    assert r.json()["mapeamento"]["cabecalho"] == {
        "colunas": {"col_inep": "CO_ESCOLA", "col_valor": "IDEB_2023"}}
    fonte = db.get(FonteAvaliacao, r.json()["id"])
    csv = "Resultados inventados - Anos Iniciais\nCO_ESCOLA;NO_ESCOLA;IDEB_2023\n" \
          f"{INEP};EM Inventada;6,1\n"
    assert _coletar(db, fonte, csv.encode("utf-8"))["status"] == "ok", fonte.ultimo_erro
    assert [v for v, _ in _gravados(db)] == [6.1]


def test_fonte_sem_referencia_com_a_variavel_da_edicao_continua_aceita(db, escola):
    """A fonte antiga (sem ``cabecalho``) com a etapa fixa e o arquivo certo continua
    coletando, e a 1ª coleta guarda o que conferiu."""
    av = svc.obter_avaliacao(db, "ideb")
    fonte = FonteAvaliacao(avaliacao_id=av.id, nome="IDEB AI 2023 (inventada)", url=URL,
                           edicao=2023, indicador="ideb", unidade="indice", cadencia="manual",
                           mapeamento={"linha_dados": 8, "col_inep": 3, "col_valor": 115,
                                       "etapa_fixa": "anos_iniciais"})
    db.add(fonte)
    db.commit()
    saida = _coletar(db, fonte, _zip_inep(_ANOS_2023, [(INEP, {"VL_OBSERVADO_2023": "5.9"})]))
    assert saida["status"] == "ok", fonte.ultimo_erro
    assert _gravados(db) == [(5.9, "anos_iniciais")]
    assert fonte.mapeamento["cabecalho"] == {"colunas": CABECALHO_DA_TELA,
                                             "etapa_do_arquivo": "anos_iniciais"}


@pytest.mark.parametrize("topo", [
    [["x"] * 1001],                                     # células demais numa linha
    [["x" * 501]],                                      # célula longa demais
    [["x"]] * 21,                                       # linhas demais (o topo tem até 20)
])
def test_topo_grande_demais_e_recusado(cliente_global, topo):
    r = cliente_global.post("/api/v1/avaliacoes/fontes", json={
        "avaliacao": "ideb", "nome": "IDEB 2023", "url": URL, "edicao": 2023,
        "indicador": "ideb", "unidade": "indice", "cadencia": "manual",
        "mapeamento": {"linha_dados": 8, "col_inep": 3, "col_valor": 115, "topo": topo}})
    assert r.status_code == 422, r.text


def test_fonte_sem_referencia_com_o_codigo_fora_de_id_escola_e_recusada(db, escola):
    """Sem referência, o código também tem de vir de ID_ESCOLA (como no 1 clique): a
    coluna mapeada que caiu em outra variável não vira a referência das coletas."""
    av = svc.obter_avaliacao(db, "ideb")
    fonte = FonteAvaliacao(avaliacao_id=av.id, nome="IDEB AI 2023 (inventada)", url=URL,
                           edicao=2023, indicador="ideb", unidade="indice", cadencia="manual",
                           mapeamento={"linha_dados": 8, "col_inep": 4, "col_valor": 115,
                                       "etapa_fixa": "anos_iniciais"})
    db.add(fonte)
    db.commit()
    saida = _coletar(db, fonte, _zip_inep(_ANOS_2023, [(INEP, {"VL_OBSERVADO_2023": "5.9"})]))
    assert saida["status"] == "erro", saida
    assert "NO_ESCOLA" in fonte.ultimo_erro and "ID_ESCOLA" in fonte.ultimo_erro
    assert _gravados(db) == []
    assert "cabecalho" not in fonte.mapeamento
