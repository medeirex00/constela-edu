"""Ideb e Saeb da REDE MUNICIPAL na leitura da rede (etapa E8b):
``GET /redes/{id}/indicadores/ideb`` → ``rede_municipal``, ``contexto_amostral`` e
``pendentes``.

O que a API garante (plano, 4.6, 4.8, 4.9 e 5.1):

* o Ideb da REDE MUNICIPAL (2005–AAAA) com as metas (meta × observado na precisão
  publicada, a regra das escolas) e a comparação na MESMA rede com o Brasil nas redes
  municipais; a UF, que o arquivo de UF do INEP só traz na rede PÚBLICA, vem como
  contexto de OUTRA rede, rotulada, e a API diz por quê — e, se o arquivo trouxer a
  rede municipal da UF, ela vira comparação na mesma rede;
* a nota do Saeb que vem DENTRO do Ideb só na seção do Ideb, com o universo do INEP
  (escolas urbanas) no rótulo, nunca cruzada com a média da planilha;
* o Saeb do 5º ano da PLANILHA (média e níveis LP 0–9 e MT 0–10) da rede, da UF e do
  Brasil nas redes municipais, na localização TOTAL (explícita — a Urbana não entra), com
  a régua dos níveis e a fonte dos cortes;
* o contexto AMOSTRAL do 2º ano e a taxa de alfabetização de 2021, só da UF e do Brasil,
  rotulados ("amostral, só contexto"; "não é o ICA");
* nada de "aguardando o arquivo oficial": com tudo importado, só a planilha do Saeb 2023
  (adiada) fica em ``pendentes``; sem importação, o que falta pelo nome do arquivo;
* ausência ≠ 0; permissões como antes (Secretaria da própria rede e admin global).

FIXTURES SINTÉTICAS — as fábricas INVENTADAS dos testes da E6a, da E6b e da E7 (layout
real dos arquivos do INEP; o município, os INEPs, os nomes, as datas e TODOS os números
são fictícios e longe dos oficiais — D13: repositório público, licença CC BY-ND).
"""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_senha
from app.main import app
from app.models import Escola, Rede, Usuario
from app.services.indicadores import (consulta_ideb, consulta_ideb_rede, escalas,
                                      ideb_territorio, pipeline_ideb, pipeline_saeb, preparar)
from tests import test_indicadores_ideb as ti
from tests import test_indicadores_ideb_territorio as tt
from tests import test_indicadores_saeb_planilha as ts

MUN = ti.MUN
assert MUN == tt.MUN == ts.MUN          # o mesmo IBGE SINTÉTICO nas três fábricas
# Outro município SINTÉTICO de SP que a planilha sintética do Saeb NÃO traz.
MUN_FORA_DA_PLANILHA = "3599997"
assert MUN_FORA_DA_PLANILHA not in {c for c, _ in ts.MUNICIPIOS}
# O nome da planilha do Saeb do INEP por edição (o de 2019 é outro molde).
ARQUIVOS_PLANILHA = {2019: "Resultados_Saeb_2019_Brasil_Estados_Municipios.xlsx",
                     2021: "saeb_2021_brasil_estados_municipios.xlsx",
                     2025: "saeb_2025_brasil_estados_municipios_censitario.xlsx"}

# A ALFA com a edição 2025 (os números INVENTADOS do teste da E6a).
ALFA_2025 = {**ti.ALFA, "valores": {**ti.ALFA["valores"], **ti._valores(ti._ALFA_2025, {})}}
EDICOES = (2019, 2021, 2023, 2025)

# A UF como no arquivo de UF do INEP: SEM a rede municipal (só Total, Pública, Privada e
# Estadual). A pública com números próprios (INVENTADOS), para não coincidir com a rede.
UF_SEM_MUNICIPAL = [
    {"territorio": "Sudeste", "rede": "Total", "valores": tt.valores(4)},
    {"territorio": "São Paulo", "rede": "Total (4)", "valores": tt.valores(2)},
    {"territorio": "São Paulo", "rede": "Pública (4)", "valores": tt.valores(5)},
    {"territorio": "São Paulo", "rede": "Privada", "valores": tt.valores(4)},
    {"territorio": "São Paulo", "rede": "Estadual", "valores": tt.valores(3)},
]
UF_COM_MUNICIPAL = [*UF_SEM_MUNICIPAL,
                    {"territorio": "São Paulo", "rede": "Municipal", "valores": tt.valores(6)}]

# Planilha do Saeb: a Urbana da rede DIFERENTE da Total (o caso que importa) e a UF nas
# redes municipais com média própria — números INVENTADOS.
TROCAS_SAEB = {(MUN, "Municipal", "Urbana", ""): {"MEDIA_5_LP": 133.9, "MEDIA_5_MT": 138.6},
               ("35", "Municipal", "Total", "Total"): {"MEDIA_5_LP": 104.6}}


@pytest.fixture()
def rede(db):
    r = Rede(nome="Rede Sintética do Ideb", uf="SP", codigo_ibge=MUN, status="ativa")
    vizinha = Rede(nome="Rede Vizinha Fictícia", uf="SP", codigo_ibge=ti.OUTRO_MUN,
                   status="ativa")
    db.add_all([r, vizinha])
    db.flush()
    db.add_all([
        Escola(nome="EMEF Sintética Beta", ano_letivo_ativo=2026, rede_id=r.id,
               codigo_inep="35990102"),
        Escola(nome="EMEF Sintética Alfa", ano_letivo_ativo=2026, rede_id=r.id,
               codigo_inep="35990101"),
    ])
    db.commit()
    return r


def _ideb(db, rede, pacote) -> dict:
    return ti._aplicar(db, rede, pacote)[1]


def _saeb(db, rede, pacote) -> dict:
    p = pipeline_saeb.previa(db, rede, pacote, "pacote.zip", usuario_id=None)
    db.commit()
    a = pipeline_saeb.aplicar(db, rede, p["id"], pacote, "pacote.zip", usuario_id=None)
    db.commit()
    return a


def _pacotes_territorio(tmp_path, uf_linhas=UF_SEM_MUNICIPAL) -> list[bytes]:
    return [
        tt._preparar(tmp_path, tt.planilha([tt.HOMONIMO, tt.MUNICIPAL, tt.PUBLICA])).pacote,
        tt._preparar(tmp_path, tt.planilha(uf_linhas, layout="uf", p_repetido=True),
                     nome="divulgacao_regioes_ufs_ideb_2025.zip").pacote,
        tt._preparar(tmp_path, tt.planilha(tt.BRASIL_LINHAS, layout="brasil"),
                     nome="divulgacao_brasil_ideb_2025.zip").pacote,
    ]


def _pacotes_saeb(tmp_path) -> list[bytes]:
    return [
        ts._preparar(tmp_path, ts.planilha(ano=2019, trocas=TROCAS_SAEB),
                     nome="saeb_2019_brasil_estados_municipios.xlsx").pacote,
        ts._preparar(tmp_path, ts.planilha(ano=2021, segundo_ano=True, trocas=TROCAS_SAEB),
                     nome="saeb_2021_brasil_estados_municipios.xlsx").pacote,
        ts._preparar(tmp_path, ts.planilha(ano=2021, segundo_ano=True, tx=True, quinto=False,
                                           municipios=False),
                     nome="saeb_2021_brasil_estados_municipios_c_tx_alfabetizado.xlsx").pacote,
        ts._preparar(tmp_path, ts.planilha(ano=2025, trocas=TROCAS_SAEB),
                     nome="saeb_2025_brasil_estados_municipios_censitario.xlsx").pacote,
    ]


def _importar_tudo(db, rede, tmp_path, *, uf_linhas=UF_SEM_MUNICIPAL) -> dict:
    escolas = ti.planilha([ALFA_2025, ti.BETA, ti.ESTADUAL], edicoes=EDICOES,
                          metas=(2019, 2021))
    ids = {"escolas": _ideb(db, rede, ti._preparar(tmp_path, escolas).pacote)["id"]}
    for chave, pacote in zip(("municipio", "uf", "brasil"),
                             _pacotes_territorio(tmp_path, uf_linhas)):
        ids[chave] = _ideb(db, rede, pacote)["id"]
    for chave, pacote in zip(("saeb_2019", "saeb_2021", "saeb_2021_tx", "saeb_2025"),
                             _pacotes_saeb(tmp_path)):
        ids[chave] = _saeb(db, rede, pacote)["id"]
    return ids


def _ler(db, rede) -> dict:
    db.expire_all()
    return consulta_ideb.ideb_da_rede(db, rede)


def _t(bloco: dict, chave: str) -> dict:
    return next(t for t in bloco["territorios"] if t["chave"] == chave)


def _ed(serie: list[dict], edicao: int) -> dict:
    return next(e for e in serie if e["edicao"] == edicao)


def _fonte_ids(no) -> set[int]:
    """Todos os ``fonte_id`` de um pedaço da resposta."""
    if isinstance(no, dict):
        proprios = {no["fonte_id"]} if no.get("fonte_id") is not None else set()
        return proprios.union(*(_fonte_ids(v) for v in no.values()))
    if isinstance(no, list):
        return set().union(*(_fonte_ids(v) for v in no)) if no else set()
    return set()


# =============================================================================
# Ideb da rede municipal: série, metas, mesma rede × outra rede rotulada
# =============================================================================

def test_ideb_da_rede_com_metas_e_a_comparacao_na_mesma_rede(db, rede, tmp_path):
    ids = _importar_tudo(db, rede, tmp_path)
    d = _ler(db, rede)
    ideb = d["rede_municipal"]["ideb"]
    assert d["rede_municipal"]["tem_dados"] and ideb["tem_dados"]

    # Ordem FIXA: a mesma rede primeiro (rede municipal e Brasil municipal); a UF, só na
    # rede pública no arquivo de UF, por último — OUTRA rede, só contexto.
    assert [(t["chave"], t["rede_ensino"], t["mesma_rede"]) for t in ideb["territorios"]] == [
        ("rede_municipal", "municipal", True), ("brasil_redes_municipais", "municipal", True),
        ("uf_rede_publica", "publica", False)]
    mun, br, sp = ideb["territorios"]
    assert (mun["rotulo"], br["rotulo"]) == ("Cidade Sintética — rede municipal",
                                             "Brasil — redes municipais")
    assert sp["rotulo"] == "São Paulo — rede pública (estadual e municipal)"
    assert sp["contexto"] is True and sp["rotulo_contexto"] == "outra rede, só contexto"
    assert "não traz a rede municipal de São Paulo" in sp["motivo_contexto"]
    assert mun["rotulo_contexto"] is None and mun["motivo_contexto"] is None
    assert ideb["uf_sem_rede_municipal"] is True
    assert "não traz a rede municipal de São Paulo" in ideb["texto_uf_sem_rede_municipal"]
    assert "total, pública e estadual" in ideb["texto_uf_sem_rede_municipal"]
    assert ideb["edicoes"] == list(EDICOES) and ideb["anos_meta"] == [2019, 2021]

    # Os números do arquivo do município (rede MUNICIPAL; a Pública e o homônimo, nunca).
    v = tt.MUNICIPAL["valores"]
    m19 = _ed(mun["serie"], 2019)
    assert (m19["ideb"]["valor"], m19["ideb"]["casas_decimais"]) == (v["VL_OBSERVADO_2019"], 1)
    assert m19["meta"]["valor"] == v["VL_PROJECAO_2019"]
    assert m19["comparacao_meta"]["situacao"] == (
        "atingiu" if v["VL_OBSERVADO_2019"] >= v["VL_PROJECAO_2019"] else "nao_atingiu")
    assert m19["nota_n"]["valor"] == v["VL_NOTA_MEDIA_2019"]
    assert m19["rendimento_p"]["valor"] == v["VL_INDICADOR_REND_2019"]
    assert m19["aprovacao"]["valor"] == v["VL_APROVACAO_2019_SI_4"]
    assert all(n["proveniencia"] == "oficial" and n["fonte_id"] == ids["municipio"]
               for n in (m19["ideb"], m19["meta"], m19["nota_n"]))
    # Depois do 1º ciclo (2023, 2025): o INEP não definiu meta — nada comparado.
    for ed in (2023, 2025):
        e = _ed(mun["serie"], ed)
        assert e["meta"] is None and e["comparacao_meta"] is None
        assert e["sem_meta"] == "depois_do_1o_ciclo"
    m25 = _ed(mun["serie"], 2025)
    assert m25["ideb"]["valor"] == v["VL_OBSERVADO_2025"]
    # O Brasil na MESMA rede (municipal) e a UF na pública, cada um do SEU arquivo.
    b25 = _ed(br["serie"], 2025)
    assert b25["ideb"]["valor"] == tt.BRASIL_LINHAS[2]["valores"]["VL_OBSERVADO_2025"]
    assert b25["ideb"]["fonte_id"] == ids["brasil"]
    s25 = _ed(sp["serie"], 2025)
    assert s25["ideb"]["valor"] == UF_SEM_MUNICIPAL[2]["valores"]["VL_OBSERVADO_2025"]
    assert s25["ideb"]["fonte_id"] == ids["uf"]
    assert _ed(sp["serie"], 2019)["comparacao_meta"] is not None
    # Toda fonte citada está na lista de fontes (arquivo, edição, data).
    fontes = {f["importacao_id"]: f for f in d["fontes"]}
    assert _fonte_ids(d["rede_municipal"]) <= set(fontes)
    assert fontes[ids["municipio"]]["parser"] == "inep_ideb_municipios"
    assert fontes[ids["uf"]]["parser"] == "inep_ideb_uf_brasil"


def test_uf_com_a_rede_municipal_no_arquivo_vira_comparacao_na_mesma_rede(db, rede, tmp_path):
    _importar_tudo(db, rede, tmp_path, uf_linhas=UF_COM_MUNICIPAL)
    ideb = _ler(db, rede)["rede_municipal"]["ideb"]
    assert [(t["chave"], t["mesma_rede"]) for t in ideb["territorios"]] == [
        ("rede_municipal", True), ("uf_redes_municipais", True),
        ("brasil_redes_municipais", True)]
    sp = _t(ideb, "uf_redes_municipais")
    assert sp["rotulo"] == "São Paulo — redes municipais" and sp["contexto"] is False
    assert _ed(sp["serie"], 2025)["ideb"]["valor"] == UF_COM_MUNICIPAL[-1]["valores"][
        "VL_OBSERVADO_2025"]
    assert ideb["uf_sem_rede_municipal"] is False and ideb["texto_uf_sem_rede_municipal"] is None
    assert all(t["chave"] != "uf_rede_publica" for t in ideb["territorios"])


def test_ausencia_no_ideb_da_rede_nunca_vira_zero(db, rede, tmp_path):
    _importar_tudo(db, rede, tmp_path)
    mun = _t(_ler(db, rede)["rede_municipal"]["ideb"], "rede_municipal")
    m23 = _ed(mun["serie"], 2023)
    # "ND" no arquivo do município: Ideb não divulgado (valor nulo + motivo), nunca 0.
    assert m23["ideb"]["valor"] is None and m23["ideb"]["motivo_ausencia"] == "nao_divulgado"
    assert m23["ideb"]["casas_decimais"] is None and m23["comparacao_meta"] is None
    # A aprovação da rede é a do 1º ao 5º ano (a do 1º ano, "-" em 2019, não entra aqui).
    assert _ed(mun["serie"], 2019)["aprovacao"]["valor"] == tt.MUNICIPAL["valores"][
        "VL_APROVACAO_2019_SI_4"]


# =============================================================================
# A nota do Saeb do Ideb: só na seção do Ideb, com o universo, nunca cruzada
# =============================================================================

def test_nota_do_saeb_do_ideb_so_na_secao_do_ideb_com_o_universo(db, rede, tmp_path):
    _importar_tudo(db, rede, tmp_path)
    rede_mun = _ler(db, rede)["rede_municipal"]
    mun = _t(rede_mun["ideb"], "rede_municipal")
    # O universo do INEP no Ideb do território: as escolas URBANAS (rótulo pronto).
    assert mun["universo_saeb"]["chave"] == ideb_territorio.UNIVERSO_URBANAS
    assert mun["universo_saeb"]["rotulo"].startswith("Só escolas urbanas")
    assert set(mun["universo_saeb"]["indicadores"]) == {"ideb", "nota_saeb", "nota_n"}
    for t in rede_mun["ideb"]["territorios"]:
        assert t["universo_saeb"]["chave"] == ideb_territorio.universo_saeb(t["abrangencia"],
                                                                           t["rede_ensino"])
    nota = _ed(mun["serie"], 2025)["nota_saeb"]
    v = tt.MUNICIPAL["valores"]
    assert (nota["lp"]["valor"], nota["mt"]["valor"]) == (v["VL_NOTA_PORTUGUES_2025"],
                                                         v["VL_NOTA_MATEMATICA_2025"])
    assert nota["lp"]["casas_decimais"] == 2                    # precisão publicada do Saeb
    # A média da planilha é OUTRA chave (Total), noutra seção — e é outro número.
    planilha = _ed(_t(rede_mun["saeb"], "rede_municipal")["edicoes"], 2025)["media"]
    assert planilha["lp"]["valor"] != nota["lp"]["valor"]
    # Nenhuma seção mistura as duas chaves.
    texto_ideb = json.dumps(rede_mun["ideb"])
    texto_saeb = json.dumps(rede_mun["saeb"])
    assert '"media"' not in texto_ideb and '"niveis"' not in texto_ideb
    assert "nota_saeb" not in texto_saeb
    assert "nunca se compara com a média “Total” da planilha" in rede_mun["avisos"]["universo"]
    assert "Não é a nota do Saeb do Ideb" in rede_mun["avisos"]["saeb_planilha"]


# =============================================================================
# Saeb do 5º ano da planilha: média, níveis e a régua (localização Total)
# =============================================================================

def test_saeb_da_planilha_media_e_niveis_na_localizacao_total(db, rede, tmp_path):
    ids = _importar_tudo(db, rede, tmp_path)
    saeb = _ler(db, rede)["rede_municipal"]["saeb"]
    assert saeb["tem_dados"] and saeb["edicoes"] == [2019, 2021, 2025]
    # As planilhas que ESTA rede importou (a da taxa, sem a aba dos municípios, não conta).
    assert saeb["edicoes_importadas_rede"] == [2019, 2021, 2025]
    assert saeb["localizacao"] == "total"
    assert saeb["rotulo_localizacao"] == "Total (escolas urbanas e rurais)"
    # A MESMA dependência (municipal) nos três, em ordem fixa.
    assert [(t["chave"], t["rede_ensino"], t["localizacao"], t["mesma_rede"])
            for t in saeb["territorios"]] == [
        ("rede_municipal", "municipal", "total", True),
        ("uf_redes_municipais", "municipal", "total", True),
        ("brasil_redes_municipais", "municipal", "total", True)]
    mun, sp, br = saeb["territorios"]
    assert (sp["rotulo"], br["rotulo"]) == ("São Paulo — redes municipais",
                                            "Brasil — redes municipais")
    m25 = _ed(mun["edicoes"], 2025)
    # A Total da planilha (101,3 — semente 0), NÃO a Urbana (trocada para 133,9).
    assert (m25["media"]["lp"]["valor"], m25["media"]["lp"]["casas_decimais"]) == (101.3, 2)
    assert m25["media"]["lp"]["fonte_id"] == ids["saeb_2025"]
    assert _ed(sp["edicoes"], 2025)["media"]["lp"]["valor"] == 104.6
    assert _ed(mun["edicoes"], 2019)["media"]["lp"]["fonte_id"] == ids["saeb_2019"]

    lp, mt = m25["niveis"]["lp"], m25["niveis"]["mt"]
    assert [n["nivel"] for n in lp["niveis"]] == list(range(10))
    assert [n["nivel"] for n in mt["niveis"]] == list(range(11))    # 0 a 10, pelo NÚMERO
    assert [n["valor"] for n in lp["niveis"]] == ts._DIST_LP5
    assert lp["soma"] == 100.0 and mt["soma"] == 100.0
    assert (lp["niveis"][0]["inicio"], lp["niveis"][0]["fim"]) == (None, 125.0)
    assert (lp["niveis"][9]["inicio"], lp["niveis"][9]["fim"]) == (325.0, None)
    assert (mt["niveis"][10]["inicio"], mt["niveis"][10]["fim"]) == (350.0, None)

    regua = saeb["regua"]
    assert regua["lp"][1] == {"nivel": 1, "inicio": 125.0, "fim": 150.0}
    assert regua["mt"][-1] == {"nivel": 10, "inicio": 350.0, "fim": None}
    assert regua["fonte"] == escalas.FONTE_CORTES_SAEB_5
    assert "Dicionário da planilha de resultados do Saeb 2025" in regua["fonte"]
    assert regua["edicoes_com_cortes_no_arquivo"] == [2025]
    assert "2019 e 2021" in regua["texto_outras_edicoes"]


def test_nivel_sem_numero_nao_vira_zero_e_a_soma_nao_e_inventada(db, rede, tmp_path):
    trocas = {(MUN, "Municipal", "Total", ""): {"nivel_3_LP5": "-"}}
    _saeb(db, rede, ts._preparar(tmp_path, ts.planilha(ano=2025, trocas=trocas)).pacote)
    m25 = _ed(_t(_ler(db, rede)["rede_municipal"]["saeb"], "rede_municipal")["edicoes"], 2025)
    n3 = m25["niveis"]["lp"]["niveis"][3]
    assert n3["valor"] is None and n3["motivo_ausencia"] == "nao_divulgado"
    assert m25["niveis"]["lp"]["soma"] is None              # nada é somado sem o nível
    assert m25["niveis"]["mt"]["soma"] == 100.0


# =============================================================================
# Contexto amostral: 2º ano e taxa de alfabetização de 2021 (UF e Brasil)
# =============================================================================

def test_contexto_amostral_so_uf_e_brasil_rotulado_e_nao_e_o_ica(db, rede, tmp_path):
    _importar_tudo(db, rede, tmp_path)
    d = _ler(db, rede)
    c = d["contexto_amostral"]
    assert c["tem_dados"] and c["desenho"] == "amostral" and c["etapa"] == "2_ano"
    assert c["edicoes"] == [2021]
    assert [(t["chave"], t["abrangencia"]) for t in c["territorios"]] == [
        ("uf_redes_municipais", "uf"), ("brasil_redes_municipais", "brasil")]
    assert all(t["abrangencia"] != "municipio" for t in c["territorios"])
    sp = c["territorios"][0]
    assert sp["rotulo"] == "São Paulo — redes municipais (amostral, só contexto)"
    assert sp["desenho"] == "amostral"
    e21 = sp["edicoes"][0]
    assert e21["media"]["lp"]["valor"] == 612.4 and e21["media"]["mt"]["valor"] == 621.7
    assert e21["tx_alfabetizado"]["valor"] == 11.2
    assert "AMOSTRAL" in c["aviso"] and "não é número da rede" in c["aviso"]
    assert "NÃO é o Indicador Criança Alfabetizada (ICA)" in c["nao_e_ica"]
    # O 2º ano nunca entra no bloco do Saeb da rede: lá, 2021 é a média do 5º ano.
    uf21 = _ed(_t(d["rede_municipal"]["saeb"], "uf_redes_municipais")["edicoes"], 2021)
    assert uf21["media"]["lp"]["valor"] == 104.6


# =============================================================================
# Sem avisos obsoletos; o que falta, pelo nome do arquivo
# =============================================================================

def test_com_tudo_importado_so_a_planilha_de_2023_fica_pendente(db, rede, tmp_path):
    _importar_tudo(db, rede, tmp_path)
    d = _ler(db, rede)
    assert d["pendentes"] == [{
        "chave": "saeb_planilha_2023", "edicao": 2023, "situacao": "adiado",
        "arquivo": "planilha_de_resultados_2023.rar",
        "texto": consulta_ideb_rede.AVISOS["saeb_2023"]}]
    assert "adiado" in d["pendentes"][0]["texto"]
    texto = json.dumps(d, ensure_ascii=False).casefold()
    assert "aguardando" not in texto and "não foram autorizados" not in texto
    assert "comparacoes" not in d                     # o bloco "aguardando" saiu da API
    assert 2025 in d["edicoes"]
    alfa = next(linha for linha in d["escolas"] if linha["nome"] == "EMEF Sintética Alfa")
    assert _ed(alfa["serie"], 2025)["ideb"]["valor"] == 1.9
    # O aviso de comparabilidade vale para a série TODA (escolas e rede).
    assert "(2019–2025)" in d["avisos"]["comparabilidade"]
    assert "série TODA" in d["avisos"]["comparabilidade"]


def test_sem_o_territorio_importado_a_api_diz_o_que_falta_sem_aguardando(db, rede, tmp_path):
    _ideb(db, rede, ti._preparar(tmp_path).pacote)             # só por escola, 2019–2023
    d = _ler(db, rede)
    assert [(p["chave"], p["situacao"]) for p in d["pendentes"]] == [
        ("ideb_escolas_2025", "sem_importacao"), ("ideb_municipio", "sem_importacao"),
        ("ideb_uf", "sem_importacao"), ("ideb_brasil", "sem_importacao"),
        ("saeb_planilha_2019", "sem_importacao"), ("saeb_planilha_2021", "sem_importacao"),
        ("saeb_planilha_2025", "sem_importacao"), ("saeb_2021_taxa", "sem_importacao"),
        ("saeb_planilha_2023", "adiado")]
    p = {x["chave"]: x for x in d["pendentes"]}
    assert p["ideb_municipio"]["arquivo"] == "divulgacao_anos_iniciais_municipios_AAAA.zip"
    # A planilha do Saeb pelo nome de CADA edição (o de 2019 é outro molde do INEP).
    assert {ed: p[f"saeb_planilha_{ed}"]["arquivo"] for ed in (2019, 2021, 2025)} == (
        ARQUIVOS_PLANILHA)
    assert "não foi importado" in p["ideb_escolas_2025"]["texto"]
    assert "aguardando" not in json.dumps(d, ensure_ascii=False).casefold()
    rede_mun = d["rede_municipal"]
    assert rede_mun["tem_dados"] is False and d["contexto_amostral"]["tem_dados"] is False
    assert all(t["serie"] == [] and t["tem_dados"] is False
               for t in rede_mun["ideb"]["territorios"])
    # Sem a UF importada, nada de "o arquivo não traz a rede municipal" (não sabemos).
    assert rede_mun["ideb"]["uf_sem_rede_municipal"] is False
    assert _t(rede_mun["ideb"], "uf_rede_publica")["motivo_contexto"] is None
    assert d["tem_dados"] is True and d["tem_dados_escolas"] is True


def test_so_a_rede_importada_tem_dados_sem_escolas(db, rede, tmp_path):
    for pacote in _pacotes_territorio(tmp_path):
        _ideb(db, rede, pacote)
    d = _ler(db, rede)
    assert d["tem_dados"] is True and d["tem_dados_escolas"] is False
    assert d["edicoes"] == [] and d["municipio"] == "Cidade Sintética"
    assert d["rede_municipal"]["ideb"]["tem_dados"] is True


def test_municipio_e_brasil_sem_o_arquivo_de_uf_nada_se_afirma_sobre_esse_arquivo(db, rede,
                                                                                   tmp_path):
    municipio, uf, brasil = _pacotes_territorio(tmp_path)
    _ideb(db, rede, municipio)
    _ideb(db, rede, brasil)
    d = _ler(db, rede)
    ideb = d["rede_municipal"]["ideb"]
    assert d["rede_municipal"]["tem_dados"] is True and _t(ideb, "rede_municipal")["tem_dados"]
    sp = _t(ideb, "uf_rede_publica")
    assert sp["serie"] == [] and sp["tem_dados"] is False
    # A rede pública é outra rede (o rótulo vale), mas o que o arquivo de UF traz NÃO se
    # afirma sem ele: nem o motivo do território, nem o texto do bloco.
    assert sp["rotulo_contexto"] == "outra rede, só contexto"
    assert sp["motivo_contexto"] is None
    assert ideb["uf_sem_rede_municipal"] is False and ideb["texto_uf_sem_rede_municipal"] is None
    assert "não traz a rede municipal" not in json.dumps(ideb, ensure_ascii=False)
    pend = {p["chave"] for p in d["pendentes"]}
    assert "ideb_uf" in pend and {"ideb_municipio", "ideb_brasil"}.isdisjoint(pend)
    # Com o arquivo de UF, o motivo volta (agora se sabe que ele não traz a municipal).
    _ideb(db, rede, uf)
    sp = _t(_ler(db, rede)["rede_municipal"]["ideb"], "uf_rede_publica")
    assert sp["tem_dados"] and "não traz a rede municipal de São Paulo" in sp["motivo_contexto"]


def test_outra_rede_da_uf_sem_importacao_propria_a_uf_e_o_brasil_nao_contam_como_dela(
        db, rede, tmp_path):
    _importar_tudo(db, rede, tmp_path)
    vizinha = db.execute(select(Rede).where(Rede.nome == "Rede Vizinha Fictícia")).scalar_one()
    d = _ler(db, vizinha)
    rede_mun = d["rede_municipal"]
    # A UF e o Brasil (referência pública, que a OUTRA rede importou) estão na base...
    assert rede_mun["ideb"]["tem_dados"] is True and rede_mun["saeb"]["tem_dados"] is True
    assert _t(rede_mun["saeb"], "uf_redes_municipais")["edicoes"] != []
    # ... mas não são número DESTA rede nem planilha importada para ela.
    assert _t(rede_mun["saeb"], "rede_municipal")["edicoes"] == []
    assert rede_mun["saeb"]["edicoes_importadas_rede"] == []
    assert rede_mun["tem_dados"] is False
    pend = {p["chave"]: p for p in d["pendentes"]}
    for ed in (2019, 2021, 2025):
        assert pend[f"saeb_planilha_{ed}"]["situacao"] == "sem_importacao"
        assert pend[f"saeb_planilha_{ed}"]["arquivo"] == ARQUIVOS_PLANILHA[ed]
    assert pend["ideb_municipio"]["situacao"] == "sem_importacao"
    # Há o que mostrar (a referência): a aba aparece, com o que falta para esta rede.
    assert d["tem_dados"] is True
    # Nenhum número do município da outra rede.
    texto = json.dumps(d, ensure_ascii=False)
    assert MUN not in texto and "Cidade Sintética" not in texto


def test_planilha_importada_pela_rede_sem_linha_do_municipio_nao_fica_pendente(db, tmp_path):
    r = Rede(nome="Rede Fora da Planilha Fictícia", uf="SP", codigo_ibge=MUN_FORA_DA_PLANILHA,
             status="ativa")
    db.add(r)
    db.commit()
    caminho = tmp_path / ARQUIVOS_PLANILHA[2025]
    caminho.write_bytes(ts.planilha(ano=2025))
    preparo = preparar.preparar_saeb(codigo_ibge=MUN_FORA_DA_PLANILHA, planilha=caminho,
                                     agora=ts.AGORA,
                                     url="https://exemplo.invalido/saeb_sintetico.xlsx")
    imp_id = _saeb(db, r, preparo.pacote)["id"]
    d = _ler(db, r)
    saeb = d["rede_municipal"]["saeb"]
    # A planilha foi importada PARA esta rede, só não traz o município: não falta importar.
    assert saeb["edicoes_importadas_rede"] == [2025]
    assert _t(saeb, "rede_municipal")["edicoes"] == []
    assert d["rede_municipal"]["tem_dados"] is False
    pend = {p["chave"] for p in d["pendentes"]}
    assert "saeb_planilha_2025" not in pend
    assert {"saeb_planilha_2019", "saeb_planilha_2021"} <= pend
    # Desfeita, volta a faltar.
    pipeline_saeb.desfazer(db, r, imp_id, usuario_id=None)
    db.commit()
    d = _ler(db, r)
    assert d["rede_municipal"]["saeb"]["edicoes_importadas_rede"] == []
    assert "saeb_planilha_2025" in {p["chave"] for p in d["pendentes"]}


def test_so_a_planilha_da_taxa_nao_conta_como_a_planilha_do_saeb_de_2021(db, rede, tmp_path):
    _saeb(db, rede, _pacotes_saeb(tmp_path)[2])          # a da taxa: só estado e Brasil
    d = _ler(db, rede)
    assert d["contexto_amostral"]["tem_dados"] is True
    assert d["rede_municipal"]["saeb"]["edicoes_importadas_rede"] == []
    pend = {p["chave"] for p in d["pendentes"]}
    assert "saeb_planilha_2021" in pend and "saeb_2021_taxa" not in pend


def test_rede_sem_codigo_ibge_vem_vazia_e_pede_o_cadastro(db, rede):
    rede.codigo_ibge = None
    db.commit()
    d = _ler(db, rede)
    assert d["pendencias"] == ["codigo_ibge"]
    assert d["rede_municipal"]["ideb"]["territorios"] == []
    assert d["rede_municipal"]["saeb"]["regua"]["fonte"] == escalas.FONTE_CORTES_SAEB_5
    assert d["contexto_amostral"]["territorios"] == [] and d["tem_dados"] is False


def test_desfazer_o_territorio_e_o_saeb_volta_a_leitura_anterior(db, rede, tmp_path):
    _ideb(db, rede, ti._preparar(tmp_path).pacote)
    antes = _ler(db, rede)
    ids = []
    for pacote in _pacotes_territorio(tmp_path):
        ids.append((pipeline_ideb, _ideb(db, rede, pacote)["id"]))
    for pacote in _pacotes_saeb(tmp_path):
        ids.append((pipeline_saeb, _saeb(db, rede, pacote)["id"]))
    assert _ler(db, rede) != antes
    for modulo, imp_id in reversed(ids):
        modulo.desfazer(db, rede, imp_id, usuario_id=None)
        db.commit()
    assert _ler(db, rede) == antes


# =============================================================================
# Permissões (como antes)
# =============================================================================

def _cliente(db, email: str, **campos) -> TestClient:
    db.add(Usuario(nome=email, email=email, senha_hash=hash_senha("s3nh4leitura"), **campos))
    db.commit()
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", data={"username": email, "password": "s3nh4leitura"})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def test_permissoes_e_o_contrato_pela_api(db, escola_completa, cliente_global, rede, tmp_path):
    _importar_tudo(db, rede, tmp_path)
    escola = escola_completa["escola"]
    vizinha = db.execute(select(Rede).where(Rede.nome == "Rede Vizinha Fictícia")).scalar_one()
    url = f"/api/v1/redes/{rede.id}/indicadores/ideb"
    secretaria = _cliente(db, "sec@rede-ideb.gov", cargo="coordenador", rede_id=rede.id)
    outra = _cliente(db, "sec@vizinha-rede-ideb.gov", cargo="coordenador", rede_id=vizinha.id)
    coordenador = _cliente(db, "coord@rede-ideb.escola", cargo="coordenador",
                           escola_id=escola.id)
    professor = _cliente(db, "prof@rede-ideb.escola", cargo="professor", escola_id=escola.id)
    for quem in (outra, coordenador, professor):
        assert quem.get(url).status_code == 403
    r = secretaria.get(url)
    assert r.status_code == 200
    d = r.json()
    assert set(d) >= {"rede_municipal", "contexto_amostral", "pendentes", "escolas", "fontes"}
    assert set(d["rede_municipal"]) == {"ideb", "saeb", "avisos", "tem_dados"}
    assert d["rede_municipal"]["ideb"]["territorios"][0]["serie"][0]["edicao"] == 2019
    assert cliente_global.get(url).json() == d
    # A Secretaria de outra rede lê a DELA: a UF e o Brasil são referência pública (pelo
    # código), mas os números da rede municipal desta rede nunca aparecem lá.
    dv = outra.get(f"/api/v1/redes/{vizinha.id}/indicadores/ideb").json()
    mun_v = _t(dv["rede_municipal"]["ideb"], "rede_municipal")
    assert mun_v["codigo_territorio"] == ti.OUTRO_MUN and mun_v["serie"] == []
    assert mun_v["tem_dados"] is False
    assert _t(dv["rede_municipal"]["saeb"], "rede_municipal")["edicoes"] == []
    assert _t(dv["rede_municipal"]["ideb"], "brasil_redes_municipais")["tem_dados"] is True
    assert dv["rede_municipal"]["tem_dados"] is False        # a UF e o Brasil não são dela
    pend_v = {p["chave"]: p["situacao"] for p in dv["pendentes"]}
    assert pend_v["ideb_municipio"] == "sem_importacao"
    for ed in (2019, 2021, 2025):
        assert pend_v[f"saeb_planilha_{ed}"] == "sem_importacao"


# =============================================================================
# PostgreSQL
# =============================================================================

from tests.test_migracoes_postgres import engine_postgres  # noqa: E402,F401 — fixture do PG de teste


@pytest.mark.postgres
def test_rede_municipal_no_postgres(engine_postgres, tmp_path):
    from sqlalchemy.orm import sessionmaker

    from app.core.migracoes import aplicar_migracoes

    aplicar_migracoes(engine_postgres)
    db = sessionmaker(bind=engine_postgres)()
    try:
        r = Rede(nome="Rede Sintética PG", uf="SP", codigo_ibge=MUN, status="ativa")
        db.add(r)
        db.flush()
        db.add_all([Escola(nome="EMEF Sintética Alfa", ano_letivo_ativo=2026, rede_id=r.id,
                           codigo_inep="35990101")])
        db.commit()
        _importar_tudo(db, r, tmp_path)
        d = consulta_ideb.ideb_da_rede(db, r)
        ideb = d["rede_municipal"]["ideb"]
        assert [t["chave"] for t in ideb["territorios"]] == [
            "rede_municipal", "brasil_redes_municipais", "uf_rede_publica"]
        mt = _ed(_t(d["rede_municipal"]["saeb"], "rede_municipal")["edicoes"], 2025)[
            "niveis"]["mt"]
        assert [n["nivel"] for n in mt["niveis"]] == list(range(11)) and mt["soma"] == 100.0
        assert d["contexto_amostral"]["edicoes"] == [2021]
        assert [p["chave"] for p in d["pendentes"]] == ["saeb_planilha_2023"]
    finally:
        db.close()
