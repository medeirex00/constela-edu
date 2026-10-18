"""SARESP oficial (etapa E4): parsers da SEDUC (IEE, SARESP por município e por
instância), prévia/aplicação/desfazer, substituição EXPLÍCITA da média calculada
(D2), 409 do INEP repetido, presets em "5_ano" e a regressão das consultas.

FIXTURES SINTÉTICAS no layout REAL dos arquivos abertos da SEDUC (nomes das
colunas, "º" no nome, caixa variável, BOM, ISO-8859-1, vírgula × ponto, "NULL",
colunas que não são indicador). Nenhum número, código de escola ou nome aqui é da
SEDUC: o repositório é público (decisão D13 do plano). Os valores são INVENTADOS,
longe dos oficiais; o município, os CIEs e os INEPs são fictícios.
"""
import codecs
from collections import Counter

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.security import hash_senha
from app.main import app
from app.models import (AvaliacaoExterna, Escola, ImportacaoIndicador, IndicadorReferencia,
                        LogAuditoria, Rede, ResultadoAvaliacao, Usuario)
from app.services import avaliacoes as svc
from app.services.avaliacoes import ImportacaoRecusada
from app.services.indicadores import escalas, pipeline_seduc, seduc

MUN = "3599999"            # IBGE SINTÉTICO (UF 35)
CODMUN = "901"             # CODMUN SINTÉTICO (não existe nos arquivos da SEDUC)
CIDADE = "CIDADE SINTETICA"
OUTRA_CIDADE = "OUTRA CIDADE FICTICIA"

# --- Fixtures do IEE ----------------------------------------------------------

_CAB_IEE = ["REDE DE ENSINO", "DIRETORIA", "MUNICIPIO", "CODIGO_ESCOLA", "CODIGO_INEP",
            "NOME_ESCOLA", "PROFICIENCIA_LINGUA_PORTUGUESA_2ºEF_{a}",
            "PROFICIENCIA_MATEMATICA_2ºEF_{a}", "PROFICIENCIA_LINGUA_PORTUGUESA_5ºEF_{a}",
            "PROFICIENCIA_MATEMATICA_5ºEF_{a}", "TAXA_PARCIPACAO_2_ANO",
            "TAXA_PARCIPACAO_5_ANO", "TPS", "IEE_ESCOLA_{a}", "META_IEE_{a}",
            "INDICE_CUMPRIMENTO_META_IEE_{a}(ICM)", "TOTAL_ALUNOS", " VALOR ", "ICM Pelo IQ"]

# (rede, diretoria, município, CIE, INEP, nome, LP2, MT2, LP5, MT5, part2, part5, TPS,
#  IEE, meta, ICM, total, valor, IQ) — tudo INVENTADO.
_ESCOLAS_IEE = [
    ("MUNICIPAL", "DIRETORIA FICTICIA", CIDADE, "990001", "35990001", "ESCOLA SINTETICA ALFA",
     "148,3", "139,6", "187,2", "196,8", "72,4", "68,9", "1", "5,12", "5,46", "0", "321",
     " R$ -   ", "NÃO"),
    ("MUNICIPAL", "DIRETORIA FICTICIA", CIDADE, "990002", "35990002", "ESCOLA SINTETICA BETA",
     "", "", "201,7", "189,4", "", "73,2", "1", "6,04", "5,9", "1", "118",
     "R$ 11.800,00", "SIM"),
    ("MUNICIPAL", "DIRETORIA FICTICIA", CIDADE, "990003", "35990003", "ESCOLA SINTETICA GAMA",
     "133,1", "127,5", "176,4", "181,9", "69,8", "71,2", "0", "4,50", "4,91", "0", "77",
     " R$ -   ", "NÃO"),
    # Homônimo da ALFA em OUTRO município (outro CIE, outro INEP): nunca casa.
    ("MUNICIPAL", "OUTRA DIRETORIA", OUTRA_CIDADE, "880001", "35880001",
     "ESCOLA SINTETICA ALFA", "160,9", "152,6", "209,3", "214,6", "74,1", "66,7", "1",
     "6,67", "6,2", "1", "402", "R$ 40.200,00", "SIM"),
]


def _iee(escolas=_ESCOLAS_IEE, *, ano: int | None = 2025, encoding="utf-8-sig",
         decimal=",", nulo="", minusculas=False, cabecalho=None, sem=()) -> bytes:
    cab = [c.format(a=ano) if ano else c.replace("_{a}", "") for c in (cabecalho or _CAB_IEE)]
    if minusculas:
        cab = [c.lower() for c in cab]
    idx = [j for j, c in enumerate(_CAB_IEE) if c not in sem]
    linhas = [";".join(cab[j] for j in idx)]
    for escola in escolas:
        cels = []
        for j in idx:
            v = escola[j]
            if 6 <= j <= 15:
                v = (nulo if v == "" else v.replace(",", decimal))
            cels.append(v)
        linhas.append(";".join(cels))
    texto = "\r\n".join(linhas) + "\r\n"
    if encoding == "utf-8-sig":
        return codecs.BOM_UTF8 + texto.encode("utf-8")
    return texto.encode(encoding)


def _ler_iee(conteudo, nome="Indice de Excelencia Educacional 2025-2026_0.csv", **kw):
    return seduc.ler_arquivo(conteudo, nome, codigo_ibge=MUN, **kw)


_CADASTRO = {"35990001": {"id": 11, "rede_id": 1, "nome": "EMEF Sintética Alfa"},
             "35990002": {"id": 12, "rede_id": 1, "nome": "EMEF Sintética Beta"}}


# --- Fixtures do SARESP por município / instância -----------------------------

_CAB_MUN = {
    "2023": "DEPADM;DEPBOL;NOMEDEPBOL;CODRMET;CODMUN;MUN;SERIE_ANO;COD_PER;PERIODO;CO_COMP;DS_COMP;MEDPROF",
    "2025": "DEPADM;DepBol;NomeDepBol;codRMet;CODMUN;MUN;SERIE_ANO;cod_per;periodo;co_comp;ds_comp;medprof",
}
_PERIODOS = {"1": "MANHÃ", "2": "TARDE", "9": "GERAL"}
_COMP = {"1": "LÍNGUA PORTUGUESA", "2": "MATEMÁTICA", "3": "CIÊNCIAS"}

# (depadm, codmun, mun, série, período, comp, medprof) — INVENTADOS.
_LINHAS_MUN = [
    ("2", CODMUN, CIDADE, "2º Ano EF", "9", "1", "158,4"),
    ("2", CODMUN, CIDADE, "2º Ano EF", "9", "2", "149,7"),
    ("2", CODMUN, CIDADE, "2º Ano EF", "1", "1", "161,0"),     # turno: fica de fora
    ("2", CODMUN, CIDADE, "5º Ano EF", "9", "1", "193,6"),
    ("2", CODMUN, CIDADE, "5º Ano EF", "9", "2", "204,1"),
    ("2", CODMUN, CIDADE, "5º Ano EF", "2", "2", "199,9"),     # turno: fica de fora
    ("2", CODMUN, CIDADE, "9º Ano EF", "9", "1", "251,2"),     # 9º ano: fica de fora
    ("1", CODMUN, CIDADE, "5º Ano EF", "9", "1", "199,3"),     # rede estadual no município
    ("1", CODMUN, CIDADE, "5º Ano EF", "9", "2", "208,8"),
    ("1", CODMUN, CIDADE, "EM-3ª série", "9", "2", "277,5"),   # EM: fica de fora
    ("2", "902", "CIDADE SINTETICA DO SUL", "5º Ano EF", "9", "1", "222,2"),   # outro CODMUN
    ("2", CODMUN, CIDADE, "5º Ano EF", "9", "3", "188,8"),     # Ciências (2022): fora
]


def _municipio(layout="2023", encoding="utf-8-sig", decimal=",", linhas=_LINHAS_MUN) -> bytes:
    cab = _CAB_MUN["2025" if layout == "2025" else "2023"]
    corpo = []
    for dep, codmun, mun, serie, per, comp, med in linhas:
        nome_rede = "Rede Estadual" if dep == "1" else "Rede Municipal"
        corpo.append(";".join([dep, dep, nome_rede, "5", codmun, mun, serie, per,
                               _PERIODOS[per], comp, _COMP[comp], med.replace(",", decimal)]))
    texto = "\r\n".join([cab, *corpo]) + "\r\n"
    if encoding == "utf-8-sig":
        return codecs.BOM_UTF8 + texto.encode("utf-8")
    return texto.encode(encoding)


_CAB_INST = {
    "2023": "DEPADM;DEPBOL;NOMEDEPBOL;CODRMET;REGIAOMETROPOLITANA;SERIE_ANO;COD_PER;PERIODO;CO_COMP;DS_COMP;MEDPROF",
    "2025": "DEPADM;DepBol;NomeDepBol;RegiaoMetropolitana;SERIE_ANO;cod_per;periodo;co_comp;ds_comp;medprof",
}
_LINHAS_INST = [
    ("1", "9", "ESTADO", "2º Ano EF", "9", "1", "166,6"),
    ("1", "9", "ESTADO", "5º Ano EF", "9", "2", "217,7"),
    ("2", "9", "ESTADO", "2º Ano EF", "9", "1", "154,3"),
    ("2", "9", "ESTADO", "5º Ano EF", "9", "2", "207,8"),
    ("2", "9", "ESTADO", "5º Ano EF", "1", "2", "205,0"),        # turno: fora
    ("2", "1", "Região Metropolitana Fictícia", "5º Ano EF", "9", "2", "201,1"),
    ("2", "7", "Interior", "5º Ano EF", "9", "2", "203,3"),
]


def _instancia(layout="2023", encoding="utf-8-sig", decimal=",") -> bytes:
    corpo = []
    for dep, rmet, regiao, serie, per, comp, med in _LINHAS_INST:
        nome_rede = "Rede Estadual" if dep == "1" else "Rede Municipal"
        cels = [dep, dep, nome_rede] + ([rmet] if layout == "2023" else []) + [
            regiao, serie, per, _PERIODOS[per], comp, _COMP[comp], med.replace(",", decimal)]
        corpo.append(";".join(cels))
    texto = "\r\n".join([_CAB_INST[layout], *corpo]) + "\r\n"
    if encoding == "utf-8-sig":
        return codecs.BOM_UTF8 + texto.encode("utf-8")
    return texto.encode(encoding)


def _ref(leitura) -> dict:
    return {(n.avaliacao, n.linha.indicador, n.linha.abrangencia, n.linha.codigo_inep,
             n.linha.rede_ensino, n.linha.etapa, n.linha.componente):
            (n.linha.valor, n.linha.motivo_ausencia) for n in leitura.referencia}


# =============================================================================
# Parsers
# =============================================================================

def test_iee_grava_2o_e_5o_em_etapas_separadas_pela_ponte_do_cadastro():
    leitura = seduc.recortar_iee(_ler_iee(_iee()), _CADASTRO, codigo_ibge=MUN)
    assert leitura.parser == seduc.PARSER_IEE and leitura.edicao_arquivo == 2025
    assert leitura.encoding == "utf-8-sig"
    esc = {(ln.escola_id, ln.etapa, ln.componente): (ln.valor, ln.motivo_ausencia)
           for ln in leitura.escolares}
    # 2º e 5º ano em etapas SEPARADAS, componente no vocabulário da tabela
    assert esc[(11, "2_ano", "portugues")] == (148.3, None)
    assert esc[(11, "2_ano", "matematica")] == (139.6, None)
    assert esc[(11, "5_ano", "portugues")] == (187.2, None)
    assert esc[(11, "5_ano", "matematica")] == (196.8, None)
    # sem 2º ano no arquivo: ausência com motivo, nunca zero
    assert esc[(12, "2_ano", "portugues")] == (None, "nao_divulgado")
    assert esc[(12, "5_ano", "matematica")] == (189.4, None)
    assert {ln.etapa for ln in leitura.escolares} == {"2_ano", "5_ano"}
    assert all(ln.edicao == 2025 and ln.unidade == "escala_saresp" for ln in leitura.escolares)
    ref = _ref(leitura)
    assert ref[("saresp", "participacao", "escola", "35990001", "municipal", "2_ano", "")] == (72.4, None)
    assert ref[("saresp", "participacao", "escola", "35990001", "municipal", "5_ano", "")] == (68.9, None)
    assert ref[("saresp", "participacao", "escola", "35990002", "municipal", "2_ano", "")] == (
        None, "nao_divulgado")
    assert ref[("saresp", "tps", "escola", "35990001", "municipal", "", "")] == (1, None)
    assert ref[("iee", "iee", "escola", "35990001", "municipal", "", "")] == (5.12, None)
    assert ref[("iee", "meta", "escola", "35990001", "municipal", "", "")] == (5.46, None)
    assert ref[("iee", "icm", "escola", "35990002", "municipal", "", "")] == (1, None)
    assert all(n.linha.codigo_territorio == MUN for n in leitura.referencia)
    casas = {(n.linha.indicador, n.linha.codigo_inep, n.linha.etapa): n.linha.casas_decimais
             for n in leitura.referencia if n.linha.valor is not None}
    assert casas[("iee", "35990001", "")] == 2 and casas[("meta", "35990002", "")] == 2   # 5,9 → 2 casas da coluna


def test_iee_iso8859_ponto_caixa_baixa_e_null_le_os_mesmos_numeros():
    base = seduc.recortar_iee(_ler_iee(_iee()), _CADASTRO, codigo_ibge=MUN)
    outro = seduc.recortar_iee(
        _ler_iee(_iee(encoding="iso-8859-1", decimal=".", nulo="NULL", minusculas=True)),
        _CADASTRO, codigo_ibge=MUN)
    assert outro.encoding == "iso-8859-1"
    assert sorted(base.escolares, key=lambda ln: ln.chave) == sorted(outro.escolares,
                                                                     key=lambda ln: ln.chave)
    assert _ref(base) == _ref(outro)
    sem_bom = _ler_iee(_iee(encoding="utf-8", decimal="."))
    assert sem_bom.encoding == "utf-8" and len(sem_bom.escolas_iee) == len(_ESCOLAS_IEE)


def test_iee_ignora_colunas_que_nao_sao_indicador_educacional():
    leitura = _ler_iee(_iee())
    assert leitura.colunas_ignoradas == ["ICM Pelo IQ", "TOTAL_ALUNOS", "VALOR"]
    assert any("não são indicador educacional" in a for a in leitura.avisos)
    recortada = seduc.recortar_iee(leitura, _CADASTRO, codigo_ibge=MUN)
    indicadores = {n.linha.indicador for n in recortada.referencia}
    assert indicadores == {"participacao", "tps", "iee", "meta", "icm"}


@pytest.mark.parametrize("ano, nome, informada, esperado", [
    (2025, "qualquer.csv", None, 2025),                                    # pela coluna
    (None, "Indice de Excelencia Educacional 2024-2025.csv", None, 2024),  # pelo nome
    (None, "iee.csv", 2024, 2024),                                         # informada
    (2025, "Indice de Excelencia Educacional 2025-2026_0.csv", 2025, 2025),
])
def test_iee_edicao_pela_coluna_pelo_nome_ou_informada(ano, nome, informada, esperado):
    leitura = _ler_iee(_iee(ano=ano), nome, edicao_informada=informada)
    assert leitura.edicao_arquivo == esperado


def test_iee_edicao_que_nao_se_sabe_ou_diverge_e_recusada():
    with pytest.raises(ImportacaoRecusada, match="ano do SARESP"):
        _ler_iee(_iee(ano=None), "iee.csv")
    with pytest.raises(ImportacaoRecusada, match="não confere"):
        _ler_iee(_iee(ano=2025), "iee.csv", edicao_informada=2024)


def test_iee_ponte_cie_inep_e_inep_derivado_marcado():
    sem_inep = list(_ESCOLAS_IEE)
    linha = list(sem_inep[1])
    linha[4] = "NULL"                      # o arquivo sem o INEP da BETA
    sem_inep[1] = tuple(linha)
    divergente = list(sem_inep[2])
    divergente[4] = "35123456"             # INEP que não segue "35" + CIE
    sem_inep[2] = tuple(divergente)
    leitura = seduc.recortar_iee(_ler_iee(_iee(sem_inep)), _CADASTRO, codigo_ibge=MUN)
    assert seduc.inep_derivado("990002") == "35990002"
    assert seduc.inep_derivado("4417") == "35004417"          # zeros à esquerda (fictício)
    assert seduc.inep_derivado("1234567") is None
    beta = next(e for e in leitura.escolas_casadas if e["escola_id"] == 12)
    assert beta["inep_derivado"] is True and beta["codigo_inep"] == "35990002"
    assert any("INEP DERIVADO" in a and "35990002" in a for a in leitura.avisos)
    assert any("diferente da regra" in a and "35123456" in a for a in leitura.avisos)
    # A ponte (do município da rede) só leva o que o arquivo traz — o derivado não.
    assert leitura.ponte == {"990001": "35990001", "990003": "35123456"}


def test_iee_homonimo_de_outro_municipio_nao_casa_e_fora_do_cadastro_e_listado():
    # No cadastro há uma escola SEM INEP com o mesmo nome da GAMA, e o homônimo da
    # ALFA existe em outro município: nada disso casa — só o código INEP casa.
    leitura = seduc.recortar_iee(_ler_iee(_iee()), _CADASTRO, codigo_ibge=MUN)
    assert {e["escola_id"] for e in leitura.escolas_casadas} == {11, 12}
    assert {ln.codigo_inep for ln in leitura.escolares} == {"35990001", "35990002"}
    assert "35880001" not in {n.linha.codigo_inep for n in leitura.referencia}
    assert [d["codigo_inep"] for d in leitura.fora_do_cadastro] == ["35990003"]
    assert leitura.fora_do_cadastro[0]["cie"] == "990003"
    assert leitura.territorios == {MUN: CIDADE}
    assert any("TPS = 0" in a for a in leitura.avisos) is False   # GAMA não casou


def test_iee_aviso_de_tps_zero_nas_casadas():
    cadastro = {**_CADASTRO, "35990003": {"id": 13, "rede_id": 1, "nome": "EMEF Gama"}}
    leitura = seduc.recortar_iee(_ler_iee(_iee()), cadastro, codigo_ibge=MUN)
    assert any("TPS = 0" in a and "35990003" in a for a in leitura.avisos)


@pytest.mark.parametrize("coluna, valor, faixa", [
    (6, "612,0", "escala do SARESP"), (10, "104,2", "0 a 100"), (12, "2", "0 ou 1"),
    (13, "11,3", "0 a 10"),
])
def test_iee_recusa_valor_fora_da_faixa(coluna, valor, faixa):
    escolas = list(_ESCOLAS_IEE)
    linha = list(escolas[0])
    linha[coluna] = valor
    escolas[0] = tuple(linha)
    with pytest.raises(ImportacaoRecusada, match=faixa):
        _ler_iee(_iee(escolas))


def test_iee_recusa_coluna_faltando_inep_repetido_e_texto_no_numero():
    with pytest.raises(ImportacaoRecusada, match="TAXA_PARCIPACAO_5_ANO"):
        _ler_iee(_iee(sem=("TAXA_PARCIPACAO_5_ANO",)))
    repetida = list(_ESCOLAS_IEE) + [_ESCOLAS_IEE[0]]
    with pytest.raises(ImportacaoRecusada, match="mais de uma linha"):
        _ler_iee(_iee(repetida))
    texto = list(_ESCOLAS_IEE)
    linha = list(texto[0])
    linha[8] = "sem dado"
    texto[0] = tuple(linha)
    with pytest.raises(ImportacaoRecusada, match="não é número"):
        _ler_iee(_iee(texto))


@pytest.mark.parametrize("layout, encoding, decimal", [
    ("2023", "utf-8-sig", ","),      # 2022/2023: UTF-8 com BOM, vírgula
    ("2023", "iso-8859-1", ","),     # 2024: ISO-8859-1
    ("2025", "utf-8", "."),          # 2025: UTF-8 sem BOM, ponto, caixa mista
    ("2025", "iso-8859-1", "."),
])
def test_saresp_municipio_layouts_e_encodings_dao_os_mesmos_numeros(layout, encoding, decimal):
    leitura = seduc.ler_arquivo(_municipio(layout, encoding, decimal),
                                "Proficiência do SARESP por Municipio de 2025_0.csv",
                                codigo_ibge=MUN, codmun=CODMUN)
    assert leitura.parser == seduc.PARSER_SARESP_MUNICIPIO and leitura.edicao_arquivo == 2025
    assert _ref(leitura) == {
        ("saresp", "proficiencia", "municipio", "", "municipal", "2_ano", "lp"): (158.4, None),
        ("saresp", "proficiencia", "municipio", "", "municipal", "2_ano", "mt"): (149.7, None),
        ("saresp", "proficiencia", "municipio", "", "municipal", "5_ano", "lp"): (193.6, None),
        ("saresp", "proficiencia", "municipio", "", "municipal", "5_ano", "mt"): (204.1, None),
        ("saresp", "proficiencia", "municipio", "", "estadual", "5_ano", "lp"): (199.3, None),
        ("saresp", "proficiencia", "municipio", "", "estadual", "5_ano", "mt"): (208.8, None),
    }
    assert all(n.linha.codigo_territorio == MUN and n.linha.casas_decimais == 1
               for n in leitura.referencia)
    assert leitura.territorios == {MUN: CIDADE}


def test_saresp_municipio_so_geral_so_2o_e_5o_e_lp_mt_com_avisos():
    leitura = seduc.ler_arquivo(_municipio(), "SARESP por Municipio de 2022_0.csv",
                                codigo_ibge=MUN, codmun=CODMUN)
    avisos = " | ".join(leitura.avisos)
    assert "2 linha(s) de turno" in avisos and "período GERAL" in avisos
    assert "2 linha(s) de outras séries" in avisos
    assert "1 linha(s) de Ciências" in avisos
    assert f"o CODMUN {CODMUN} é “{CIDADE}”" in avisos   # para conferir o código na prévia


def test_saresp_municipio_recorta_pelo_codmun_nao_pelo_nome():
    # O CODMUN 902 ("CIDADE SINTETICA DO SUL") começa com o mesmo nome: não entra.
    leitura = seduc.ler_arquivo(_municipio(), "x de 2025.csv", codigo_ibge=MUN, codmun=CODMUN)
    assert 222.2 not in {n.linha.valor for n in leitura.referencia}
    vizinho = seduc.ler_arquivo(_municipio(), "x de 2025.csv", codigo_ibge="3599998",
                                codmun="902")
    assert {n.linha.valor for n in vizinho.referencia} == {222.2}
    nenhum = seduc.ler_arquivo(_municipio(), "x de 2025.csv", codigo_ibge=MUN, codmun="999")
    assert nenhum.referencia == [] and any("CODMUN 999 não está" in a for a in nenhum.avisos)
    with pytest.raises(ImportacaoRecusada, match="CODMUN"):
        seduc.ler_arquivo(_municipio(), "x de 2025.csv", codigo_ibge=MUN, codmun=None)


def test_saresp_municipio_medprof_vazio_vira_ausencia_e_periodo_incoerente_recusa():
    linhas = [("2", CODMUN, CIDADE, "5º Ano EF", "9", "1", "")]
    leitura = seduc.ler_arquivo(_municipio(linhas=linhas), "x de 2024.csv", codigo_ibge=MUN,
                                codmun=CODMUN)
    assert [(n.linha.valor, n.linha.motivo_ausencia) for n in leitura.referencia] == [
        (None, "nao_divulgado")]
    incoerente = _municipio(linhas=[("2", CODMUN, CIDADE, "5º Ano EF", "9", "1", "190,1")])
    incoerente = incoerente.replace(b";9;GERAL;", b";1;GERAL;")
    with pytest.raises(ImportacaoRecusada, match="período"):
        seduc.ler_arquivo(incoerente, "x de 2024.csv", codigo_ibge=MUN, codmun=CODMUN)


def test_edicao_informada_fora_da_faixa_e_recusada():
    # A faixa de sanidade vale também para a edição DIGITADA (nome sem ano).
    for informada in (205, 20250):
        with pytest.raises(ImportacaoRecusada, match="fora do esperado"):
            seduc.ler_arquivo(_municipio(), "saresp_mun.csv", codigo_ibge=MUN, codmun=CODMUN,
                              edicao_informada=informada)
    leitura = seduc.ler_arquivo(_municipio(), "saresp_mun.csv", codigo_ibge=MUN,
                                codmun=CODMUN, edicao_informada=2024)
    assert leitura.edicao_arquivo == 2024


@pytest.mark.parametrize("layout, encoding, decimal", [
    ("2023", "utf-8-sig", ","), ("2023", "iso-8859-1", ","), ("2025", "utf-8", "."),
])
def test_saresp_instancia_so_estado_nas_duas_redes(layout, encoding, decimal):
    leitura = seduc.ler_arquivo(_instancia(layout, encoding, decimal),
                                "Proficiência do SARESP por instância de 2025_0.csv",
                                codigo_ibge=MUN)
    assert leitura.parser == seduc.PARSER_SARESP_INSTANCIA
    assert _ref(leitura) == {
        ("saresp", "proficiencia", "uf", "", "estadual", "2_ano", "lp"): (166.6, None),
        ("saresp", "proficiencia", "uf", "", "estadual", "5_ano", "mt"): (217.7, None),
        ("saresp", "proficiencia", "uf", "", "municipal", "2_ano", "lp"): (154.3, None),
        ("saresp", "proficiencia", "uf", "", "municipal", "5_ano", "mt"): (207.8, None),
    }
    assert all(n.linha.codigo_territorio == "35" for n in leitura.referencia)
    with pytest.raises(ImportacaoRecusada, match="São Paulo"):
        seduc.ler_arquivo(_instancia(layout, encoding, decimal), "x de 2025.csv",
                          codigo_ibge="4199999")


def test_arquivo_por_escola_xlsx_e_desconhecido_sao_recusados():
    por_escola = codecs.BOM_UTF8 + (
        "CODESC;NOMESC;SERIE_ANO;periodo;co_comp;medprof\r\n"
        "990001;ESCOLA SINTETICA ALFA;5º Ano EF;GERAL;1;190,2\r\n").encode("utf-8")
    with pytest.raises(ImportacaoRecusada, match="POR ESCOLA"):
        seduc.ler_arquivo(por_escola, "por escola de 2025.csv", codigo_ibge=MUN)
    with pytest.raises(ImportacaoRecusada, match="CSV"):
        seduc.ler_arquivo(b"PK\x03\x04resto", "x.xlsx", codigo_ibge=MUN)
    with pytest.raises(ImportacaoRecusada, match="Não reconheci"):
        seduc.ler_arquivo(b"A;B\r\n1;2\r\n", "x.csv", codigo_ibge=MUN)


def test_ler_numero_trata_virgula_ponto_milhar_e_null():
    assert seduc.ler_numero("87,3") == (87.3, 1, True)
    assert seduc.ler_numero("176.4") == (176.4, 1, True)
    assert seduc.ler_numero("1.234,56") == (1234.56, 2, True)
    assert seduc.ler_numero("NULL") == (None, 0, True)
    assert seduc.ler_numero(" ") == (None, 0, True)
    assert seduc.ler_numero("abc") == (None, 0, False)
    assert seduc.normalizar_coluna("PROFICIENCIA_LINGUA_PORTUGUESA_2ºEF_2025") == (
        "PROFICIENCIA_LINGUA_PORTUGUESA_2EF_2025")
    assert seduc.normalizar_coluna(" VALOR ") == "VALOR"
    assert seduc.normalizar_coluna("INDICE_CUMPRIMENTO_META_IEE_2025(ICM)") == (
        "INDICE_CUMPRIMENTO_META_IEE_2025_ICM")


# =============================================================================
# Pipeline: prévia, aplicação, substituição (D2) e desfazer
# =============================================================================

@pytest.fixture()
def rede(db):
    r = Rede(nome="Rede Sintética", uf="SP", codigo_ibge=MUN, codigo_municipio_estadual=CODMUN,
             status="ativa")
    outra = Rede(nome="Rede Vizinha Fictícia", uf="SP", codigo_ibge="3599998", status="ativa")
    db.add_all([r, outra])
    db.flush()
    db.add_all([
        Escola(nome="EMEF Sintética Alfa", ano_letivo_ativo=2026, rede_id=r.id,
               codigo_inep="35990001"),
        Escola(nome="EMEF Sintética Beta", ano_letivo_ativo=2026, rede_id=r.id,
               codigo_inep="35990002"),
        # sem INEP (como uma escola que ainda espera o código): não casa pelo nome
        Escola(nome="ESCOLA SINTETICA GAMA", ano_letivo_ativo=2026, rede_id=r.id),
        # o homônimo da ALFA, com o INEP dele, numa OUTRA rede: não entra nesta
        Escola(nome="ESCOLA SINTETICA ALFA", ano_letivo_ativo=2026, rede_id=outra.id,
               codigo_inep="35880001"),
    ])
    db.commit()
    return r


def _escola(db, inep) -> Escola:
    return db.execute(select(Escola).where(Escola.codigo_inep == inep)).scalar_one()


_NOME_IEE = "Indice de Excelencia Educacional 2025-2026_0.csv"


def _aplicar(db, rede, conteudo, nome=_NOME_IEE, **kw):
    p = pipeline_seduc.previa(db, rede, conteudo, nome, usuario_id=None)
    db.commit()
    a = pipeline_seduc.aplicar(db, rede, p["id"], conteudo, nome, usuario_id=None, **kw)
    db.commit()
    return p, a


def _estado(db) -> tuple:
    db.expire_all()
    res = sorted((r.avaliacao_id, r.edicao, r.indicador, r.escola_id, r.etapa, r.componente,
                  r.valor, r.motivo_ausencia, r.unidade, r.fonte, r.importacao_id,
                  r.codigo_inep, r.rede_id)
                 for r in db.execute(select(ResultadoAvaliacao)).scalars())
    ref = sorted((r.avaliacao_id, r.edicao, r.indicador, r.abrangencia, r.codigo_territorio,
                  r.codigo_inep, r.rede_ensino, r.etapa, r.componente, r.valor,
                  r.casas_decimais, r.motivo_ausencia, r.unidade, r.importacao_id,
                  r.created_at, r.updated_at)
                 for r in db.execute(select(IndicadorReferencia)).scalars())
    return res, ref


def _calculadas(db, rede, valores=((184.6, 198.3), (200.1, 190.0))):
    """As médias do SARESP 5º ano 2025 "calculadas pelo Constela" (importação manual
    antiga, SEM importacao_id) — números INVENTADOS."""
    av = svc.obter_avaliacao(db, "saresp")
    for inep, (lp, mt) in zip(("35990001", "35990002"), valores):
        e = _escola(db, inep)
        for comp, v in (("portugues", lp), ("matematica", mt)):
            db.add(ResultadoAvaliacao(avaliacao_id=av.id, edicao=2025, rede_id=rede.id,
                                      escola_id=e.id, codigo_inep=inep, etapa="5_ano",
                                      componente=comp, indicador="proficiencia", valor=v,
                                      unidade="escala_saresp",
                                      fonte="SARESP 2025 — calculo_sintetico.csv"))
    db.commit()


def test_previa_nao_grava_e_aplicar_duas_vezes_deixa_o_mesmo_estado(db, rede):
    p = pipeline_seduc.previa(db, rede, _iee(), _NOME_IEE, usuario_id=None)
    db.commit()
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 0
    assert db.scalar(select(func.count(IndicadorReferencia.id))) == 0
    imp = db.get(ImportacaoIndicador, p["id"])
    assert imp.status == "previa" and imp.parser == seduc.PARSER_IEE
    assert imp.edicao_arquivo == 2025 and len(imp.arquivo_sha256) == 64
    assert imp.licenca and "Secretaria da Educação do Estado de São Paulo" in imp.licenca
    # 2 escolas × (4 proficiências + 2 participações + TPS + IEE + meta + ICM)
    assert p["contadores"]["novas"] == 20 and p["contadores"]["escolas_casadas"] == 2
    assert p["contadores"]["fora_do_cadastro"] == 1 and p["substituicoes"] == []
    pipeline_seduc.aplicar(db, rede, p["id"], _iee(), _NOME_IEE, usuario_id=None)
    db.commit()
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 8
    assert db.scalar(select(func.count(IndicadorReferencia.id))) == 12
    antes = _estado(db)
    _, de_novo = _aplicar(db, rede, _iee())
    assert de_novo["contadores"]["iguais"] == 20 and de_novo["contadores"]["novas"] == 0
    assert _estado(db) == antes                       # nem a proveniência muda
    alfa = _escola(db, "35990001")
    linhas = {(r.etapa, r.componente): r for r in db.execute(select(ResultadoAvaliacao).where(
        ResultadoAvaliacao.escola_id == alfa.id)).scalars()}
    assert linhas[("2_ano", "portugues")].valor == 148.3
    assert linhas[("5_ano", "matematica")].importacao_id is not None
    beta = _escola(db, "35990002")
    sem = db.execute(select(ResultadoAvaliacao).where(
        ResultadoAvaliacao.escola_id == beta.id, ResultadoAvaliacao.etapa == "2_ano")).scalars().all()
    assert {(r.valor, r.motivo_ausencia) for r in sem} == {(None, "nao_divulgado")}
    # a homônima da outra rede não recebeu nada
    assert not db.execute(select(ResultadoAvaliacao).where(
        ResultadoAvaliacao.codigo_inep == "35880001")).first()
    iee = db.execute(select(AvaliacaoExterna).where(AvaliacaoExterna.chave == "iee")).scalar_one()
    assert iee.tipo == "indicador" and iee.orgao == "SEDUC-SP"


def test_aplicar_exige_o_mesmo_arquivo_e_uma_vez_so(db, rede):
    p = pipeline_seduc.previa(db, rede, _iee(), _NOME_IEE, usuario_id=None)
    db.commit()
    with pytest.raises(ImportacaoRecusada, match="não é o mesmo da prévia"):
        pipeline_seduc.aplicar(db, rede, p["id"], _iee(decimal="."), _NOME_IEE, usuario_id=None)
    db.rollback()
    pipeline_seduc.aplicar(db, rede, p["id"], _iee(), _NOME_IEE, usuario_id=None)
    db.commit()
    with pytest.raises(ImportacaoRecusada, match="já foi aplicada"):
        pipeline_seduc.aplicar(db, rede, p["id"], _iee(), _NOME_IEE, usuario_id=None)


_NOME_MUN = "Proficiência do SARESP por Municipio de {}_0.csv"
_NOME_INST = "Proficiência do SARESP por instância de {}_0.csv"


@pytest.mark.parametrize("fabrica, nome, novas", [(_municipio, _NOME_MUN, 6),
                                                  (_instancia, _NOME_INST, 4)])
def test_aplicar_le_pelo_nome_da_previa_e_nao_grava_noutra_edicao(db, rede, fabrica, nome,
                                                                  novas):
    # O sha256 não cobre o nome, e aqui a edição sai do nome: o MESMO conteúdo
    # reenviado na aplicação com "de 2023" não cai na edição 2023 (que a prévia não
    # mostrou) nem sobrescreve o 2023 já importado.
    _, a23 = _aplicar(db, rede, fabrica(), nome.format(2023))
    conteudo = fabrica("2025", "utf-8", ".")             # os mesmos números, outros bytes
    p = pipeline_seduc.previa(db, rede, conteudo, nome.format(2025), usuario_id=None)
    db.commit()
    assert p["edicao_arquivo"] == 2025 and p["contadores"]["novas"] == novas
    a = pipeline_seduc.aplicar(db, rede, p["id"], conteudo, nome.format(2023), usuario_id=None)
    db.commit()
    assert a["edicao_arquivo"] == 2025 and a["arquivo_nome"] == nome.format(2025)
    assert a["contadores"]["novas"] == novas and a["contadores"]["alteradas"] == 0
    assert {m["edicao"] for m in a["mudancas"]} == {2025}
    db.expire_all()
    por_edicao = Counter((r.edicao, r.importacao_id)
                         for r in db.execute(select(IndicadorReferencia)).scalars())
    assert por_edicao == {(2023, a23["id"]): novas, (2025, a["id"]): novas}


def test_aplicar_recusa_se_a_edicao_lida_nao_e_a_da_previa(db, rede):
    p = pipeline_seduc.previa(db, rede, _iee(), _NOME_IEE, usuario_id=None)
    # (simula o arquivo lido noutra edição entre a prévia e a aplicação)
    db.get(ImportacaoIndicador, p["id"]).edicao_arquivo = 2024
    db.commit()
    with pytest.raises(ImportacaoRecusada, match="não é a da prévia"):
        pipeline_seduc.aplicar(db, rede, p["id"], _iee(), _NOME_IEE, usuario_id=None)
    db.rollback()
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 0


def test_aplicar_recusa_se_o_codmun_da_rede_mudou_desde_a_previa(db, rede):
    nome = _NOME_MUN.format(2025)
    p = pipeline_seduc.previa(db, rede, _municipio(), nome, usuario_id=None)
    db.commit()
    assert p["territorios"] == {MUN: CIDADE}
    rede.codigo_municipio_estadual = "902"          # o CODMUN de OUTRA cidade do arquivo
    db.commit()
    with pytest.raises(ImportacaoRecusada, match="mudou desde a prévia \\(901 → 902\\)"):
        pipeline_seduc.aplicar(db, rede, p["id"], _municipio(), nome, usuario_id=None)
    db.rollback()
    assert db.scalar(select(func.count(IndicadorReferencia.id))) == 0
    rede.codigo_municipio_estadual = "0901"         # o mesmo código, com zero à esquerda
    db.commit()
    a = pipeline_seduc.aplicar(db, rede, p["id"], _municipio(), nome, usuario_id=None)
    db.commit()
    assert {m["depois"] for m in a["mudancas"]} == {158.4, 149.7, 193.6, 204.1, 199.3, 208.8}


def test_api_aplicar_usa_o_nome_da_previa(db, escola_completa, cliente_global, rede):
    conteudo = _municipio()
    p = _post(cliente_global, rede.id, "previa", conteudo, _NOME_MUN.format(2025))
    assert p.status_code == 200 and p.json()["edicao_arquivo"] == 2025
    ok = _post(cliente_global, rede.id, "aplicar", conteudo, _NOME_MUN.format(2022),
               previa_id=str(p.json()["id"]))
    assert ok.status_code == 200, ok.text
    db.expire_all()
    assert {r.edicao for r in db.execute(select(IndicadorReferencia)).scalars()} == {2025}


def test_desfazer_volta_exatamente_e_recusa_com_posterior_nos_mesmos_numeros(db, rede):
    vazio = _estado(db)
    _, a = _aplicar(db, rede, _iee())
    depois_a = _estado(db)
    corrigida = list(_ESCOLAS_IEE)
    linha = list(corrigida[0])
    linha[8] = "190,4"                    # republicação com a LP do 5º da ALFA revisada
    corrigida[0] = tuple(linha)
    _, b = _aplicar(db, rede, _iee(corrigida))
    assert b["contadores"]["alteradas"] == 1 and b["contadores"]["iguais"] == 19
    with pytest.raises(ImportacaoRecusada, match=f"desfaça antes a #{b['id']}"):
        pipeline_seduc.desfazer(db, rede, a["id"], usuario_id=None)
    db.rollback()
    lista = pipeline_seduc.listar(db, rede)
    assert [(i["id"], i["pode_desfazer"], i["bloqueada_por"]) for i in lista[:2]] == [
        (b["id"], True, None), (a["id"], False, b["id"])]
    pipeline_seduc.desfazer(db, rede, b["id"], usuario_id=None)
    db.commit()
    assert _estado(db) == depois_a
    pipeline_seduc.desfazer(db, rede, a["id"], usuario_id=None)
    db.commit()
    assert _estado(db) == vazio


def test_desfazer_recusa_se_o_estado_mudou(db, rede):
    _, a = _aplicar(db, rede, _iee())
    linha = db.execute(select(ResultadoAvaliacao).where(
        ResultadoAvaliacao.valor.isnot(None))).scalars().first()
    linha.valor = 1.5
    db.commit()
    with pytest.raises(ImportacaoRecusada, match="já não estão como ela os deixou"):
        pipeline_seduc.desfazer(db, rede, a["id"], usuario_id=None)


def test_substituicao_da_media_calculada_mostra_antes_depois_e_pode_ser_desfeita(db, rede):
    _calculadas(db, rede)
    antes = _estado(db)
    p = pipeline_seduc.previa(db, rede, _iee(), _NOME_IEE, usuario_id=None)
    db.commit()
    assert p["contadores"]["substituicoes"] == 4 and p["contadores"]["novas"] == 16
    subst = {(s["escola"], s["componente"]): s for s in p["substituicoes"]}
    alfa_lp = subst[("EMEF Sintética Alfa", "portugues")]
    assert alfa_lp["antes"] == {"valor": 184.6, "fonte": "SARESP 2025 — calculo_sintetico.csv",
                                "motivo_ausencia": None}
    assert alfa_lp["depois"]["valor"] == 187.2 and alfa_lp["diferenca"] == 2.6
    assert alfa_lp["etapa"] == "5_ano" and alfa_lp["codigo_inep"] == "35990001"
    assert subst[("EMEF Sintética Beta", "matematica")]["diferenca"] == -0.6
    assert _estado(db) == antes                                    # a prévia não grava
    # Sem resposta explícita: recusa, nada gravado.
    with pytest.raises(ImportacaoRecusada, match="responda explicitamente"):
        pipeline_seduc.aplicar(db, rede, p["id"], _iee(), _NOME_IEE, usuario_id=None)
    db.rollback()
    assert _estado(db) == antes
    a = pipeline_seduc.aplicar(db, rede, p["id"], _iee(), _NOME_IEE, usuario_id=None,
                               substituir_calculadas=True)
    db.commit()
    assert a["contadores"]["substituicoes_aplicadas"] == 4
    db.expire_all()
    alfa = _escola(db, "35990001")
    nova = db.execute(select(ResultadoAvaliacao).where(
        ResultadoAvaliacao.escola_id == alfa.id, ResultadoAvaliacao.etapa == "5_ano",
        ResultadoAvaliacao.componente == "portugues")).scalar_one()
    assert nova.valor == 187.2 and nova.importacao_id == a["id"]
    assert "oficial" in nova.fonte and _NOME_IEE in nova.fonte
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 8   # trocou, não duplicou
    pipeline_seduc.desfazer(db, rede, a["id"], usuario_id=None)
    db.commit()
    assert _estado(db) == antes            # o calculado volta, com a fonte antiga


def test_substituicao_recusada_mantem_as_calculadas_e_aplica_o_resto(db, rede):
    _calculadas(db, rede)
    _, a = _aplicar(db, rede, _iee(), substituir_calculadas=False)
    assert a["contadores"]["substituicoes_mantidas"] == 4
    db.expire_all()
    quinto = {(r.escola_id, r.componente): (r.valor, r.importacao_id)
              for r in db.execute(select(ResultadoAvaliacao).where(
                  ResultadoAvaliacao.etapa == "5_ano")).scalars()}
    alfa = _escola(db, "35990001")
    assert quinto[(alfa.id, "portugues")] == (184.6, None)        # o calculado ficou
    assert db.scalar(select(func.count(ResultadoAvaliacao.id)).where(
        ResultadoAvaliacao.etapa == "2_ano")) == 4                  # o resto entrou
    assert db.scalar(select(func.count(IndicadorReferencia.id))) == 12


def _manual_saresp_5_ano(db, *linhas):
    """Importação MANUAL (sem prévia) do SARESP 2025, 5º ano — números INVENTADOS."""
    csv_manual = "\n".join(["INEP;COMPONENTE;PROF", *linhas]).encode()
    svc.importar_resultados(db, csv_manual, "manual.csv", avaliacao_chave="saresp", edicao=2025,
                            indicador="proficiencia", unidade="escala_saresp", linha_dados=1,
                            col_inep=0, col_valor=2, col_componente=1, etapa_fixa="5_ano",
                            escopo_escolas=None)
    db.commit()


def test_substituicao_exige_o_mesmo_antes_que_a_previa_mostrou(db, rede):
    # A resposta da D2 vale para o ANTES × DEPOIS da prévia. Se, entre a prévia e a
    # aplicação, o ANTES de um número mostrado muda ou surgem números novos sem
    # proveniência oficial, a aplicação recusa — com "sim" ou com "não".
    _calculadas(db, rede, valores=((184.6, 198.3),))              # só a ALFA
    p1 = pipeline_seduc.previa(db, rede, _iee(), _NOME_IEE, usuario_id=None)
    db.commit()
    assert p1["contadores"]["substituicoes"] == 2
    _manual_saresp_5_ano(db, "35990001;portugues;151,7")        # o ANTES da LP da ALFA muda
    p2 = pipeline_seduc.previa(db, rede, _iee(), _NOME_IEE, usuario_id=None)
    db.commit()
    assert {s["antes"]["valor"] for s in p2["substituicoes"]} == {151.7, 198.3}
    _manual_saresp_5_ano(db, "35990002;portugues;171,4",       # a BETA ganha números manuais
                         "35990002;matematica;168,0")
    antes = _estado(db)
    for velha in (p1, p2):
        for resposta in (True, False):
            with pytest.raises(ImportacaoRecusada, match="mudaram desde a prévia"):
                pipeline_seduc.aplicar(db, rede, velha["id"], _iee(), _NOME_IEE,
                                       usuario_id=None, substituir_calculadas=resposta)
            db.rollback()
            assert _estado(db) == antes
    p3 = pipeline_seduc.previa(db, rede, _iee(), _NOME_IEE, usuario_id=None)
    db.commit()
    assert p3["contadores"]["substituicoes"] == 4
    a = pipeline_seduc.aplicar(db, rede, p3["id"], _iee(), _NOME_IEE, usuario_id=None,
                               substituir_calculadas=True)
    db.commit()
    assert a["contadores"]["substituicoes_aplicadas"] == 4
    pipeline_seduc.desfazer(db, rede, a["id"], usuario_id=None)
    db.commit()
    assert _estado(db) == antes


def test_importacao_manual_nao_sobrescreve_numero_oficial(db, rede):
    _aplicar(db, rede, _iee())
    csv_manual = "\n".join(["INEP;COMPONENTE;PROF", "35990001;portugues;111,1"]).encode()
    r = svc.importar_resultados(db, csv_manual, "manual.csv", avaliacao_chave="saresp",
                                edicao=2025, indicador="proficiencia", unidade="escala_saresp",
                                linha_dados=1, col_inep=0, col_valor=2, col_componente=1,
                                etapa_fixa="5_ano", escopo_escolas=None)
    db.commit()
    assert r["mantidos_oficiais"] == 1 and r["atualizados"] == 0 and r["inseridos"] == 0
    alfa = _escola(db, "35990001")
    assert db.execute(select(ResultadoAvaliacao.valor).where(
        ResultadoAvaliacao.escola_id == alfa.id, ResultadoAvaliacao.etapa == "5_ano",
        ResultadoAvaliacao.componente == "portugues")).scalar_one() == 187.2


def test_municipio_e_instancia_vao_para_referencia_na_rede_de_ensino_certa(db, rede):
    _, m = _aplicar(db, rede, _municipio(), "Proficiência do SARESP por Municipio de 2025_0.csv")
    _, i = _aplicar(db, rede, _instancia(), "Proficiência do SARESP por instância de 2025_0.csv")
    assert m["parser"] == seduc.PARSER_SARESP_MUNICIPIO and m["contadores"]["novas"] == 6
    assert i["parser"] == seduc.PARSER_SARESP_INSTANCIA and i["contadores"]["novas"] == 4
    linhas = {(r.abrangencia, r.codigo_territorio, r.rede_ensino, r.etapa, r.componente): r.valor
              for r in db.execute(select(IndicadorReferencia)).scalars()}
    assert linhas[("municipio", MUN, "municipal", "2_ano", "lp")] == 158.4
    assert linhas[("municipio", MUN, "estadual", "5_ano", "mt")] == 208.8
    assert linhas[("uf", "35", "municipal", "5_ano", "mt")] == 207.8
    assert linhas[("uf", "35", "estadual", "2_ano", "lp")] == 166.6
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 0   # nada por escola


def test_rede_sem_codmun_ou_sem_ibge_a_previa_pede_o_codigo(db, rede):
    rede.codigo_municipio_estadual = None
    db.commit()
    with pytest.raises(ImportacaoRecusada, match="CODMUN"):
        pipeline_seduc.previa(db, rede, _municipio(), "x de 2025.csv", usuario_id=None)
    db.rollback()
    rede.codigo_ibge = None
    db.commit()
    with pytest.raises(ImportacaoRecusada, match="código IBGE"):
        pipeline_seduc.previa(db, rede, _iee(), _NOME_IEE, usuario_id=None)
    db.rollback()
    assert db.scalar(select(func.count(ImportacaoIndicador.id))) == 0


def test_textos_de_proveniencia_cabem_nas_colunas():
    """O SQLite não impõe o tamanho do VARCHAR; o PostgreSQL de produção, sim."""
    assert len(pipeline_seduc.LICENCA) <= 200
    assert all(len(t) <= 500 for t in pipeline_seduc.CITACAO.values())
    assert all(len(t) <= 120 for t in pipeline_seduc.FONTE_NOME.values())


def test_precedencia_edicao_mais_nova_fica():
    from types import SimpleNamespace
    nova, velha = SimpleNamespace(edicao_arquivo=2025), SimpleNamespace(edicao_arquivo=2024)
    antes, depois = {"valor": 1.0}, {"valor": 2.0}
    assert pipeline_seduc._tipo(nova, velha, antes, depois, ("valor",)) == "mantida"
    assert pipeline_seduc._tipo(velha, nova, antes, depois, ("valor",)) == "alterada"
    assert pipeline_seduc._tipo(nova, nova, antes, dict(antes), ("valor",)) == "igual"


def test_ponte_cie_inep_das_importacoes_aplicadas(db, rede):
    _aplicar(db, rede, _iee())
    ponte = pipeline_seduc.ponte_cie_inep(db, rede)
    assert {cie: d["codigo_inep"] for cie, d in ponte.items()} == {
        "990001": "35990001", "990002": "35990002", "990003": "35990003"}
    assert "880001" not in ponte                    # outro município: fora da ponte da rede


# =============================================================================
# API: permissões, substituição explícita, 409 do INEP e o CODMUN da rede
# =============================================================================

def _cliente(db, email: str, **campos) -> TestClient:
    db.add(Usuario(nome=email, email=email, senha_hash=hash_senha("s3nh4saresp1"), **campos))
    db.commit()
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", data={"username": email, "password": "s3nh4saresp1"})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _post(cliente, rede_id, rota, conteudo, nome=_NOME_IEE, **form):
    return cliente.post(f"/api/v1/redes/{rede_id}/indicadores/saresp/{rota}",
                        files={"arquivo": (nome, conteudo)}, data=form)


def test_api_permissoes_fluxo_e_auditoria(db, escola_completa, cliente_global, rede):
    secretaria = _cliente(db, "sec@saresp.gov", cargo="coordenador", rede_id=rede.id)
    coordenador = _cliente(db, "coord@saresp.escola", cargo="coordenador",
                           escola_id=escola_completa["escola"].id)
    for quem in (secretaria, coordenador):
        assert _post(quem, rede.id, "previa", _iee()).status_code == 403
        assert quem.get(f"/api/v1/redes/{rede.id}/indicadores/saresp/importacoes").status_code == 403
    p = _post(cliente_global, rede.id, "previa", _iee(),
              url_origem="https://dados.educacao.sp.gov.br/exemplo.csv",
              last_modified_origem="Thu, 01 Jan 2026 10:00:00 GMT")
    assert p.status_code == 200, p.text
    assert p.json()["fora_do_cadastro"][0]["codigo_inep"] == "35990003"
    errado = _post(cliente_global, rede.id, "aplicar", _iee(decimal="."),
                   previa_id=str(p.json()["id"]))
    assert errado.status_code == 400 and "sha256" in errado.json()["detail"]
    ok = _post(cliente_global, rede.id, "aplicar", _iee(), previa_id=str(p.json()["id"]))
    assert ok.status_code == 200 and ok.json()["status"] == "aplicada"
    for quem in (secretaria, coordenador):
        assert quem.post(f"/api/v1/redes/{rede.id}/indicadores/saresp/importacoes/"
                         f"{ok.json()['id']}/desfazer").status_code == 403
    lista = cliente_global.get(f"/api/v1/redes/{rede.id}/indicadores/saresp/importacoes").json()
    assert lista[0]["id"] == ok.json()["id"] and lista[0]["pode_desfazer"] is True
    assert lista[0]["url_origem"] == "https://dados.educacao.sp.gov.br/exemplo.csv"
    # A importação do SARESP não aparece na lista do ICA (cada fluxo com a sua).
    ica = cliente_global.get(f"/api/v1/redes/{rede.id}/indicadores/importacoes").json()
    assert ok.json()["id"] not in {i["id"] for i in ica}
    desf = cliente_global.post(f"/api/v1/redes/{rede.id}/indicadores/saresp/importacoes/"
                               f"{ok.json()['id']}/desfazer")
    assert desf.status_code == 200 and desf.json()["status"] == "desfeita"
    db.expire_all()
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 0
    acoes = {a for (a,) in db.execute(select(LogAuditoria.acao))}
    assert {"indicador.importado", "indicador.desfeito"} <= acoes


def test_api_substituicao_exige_resposta_explicita(db, escola_completa, cliente_global, rede):
    _calculadas(db, rede)
    p = _post(cliente_global, rede.id, "previa", _iee())
    assert p.status_code == 200 and len(p.json()["substituicoes"]) == 4
    sem = _post(cliente_global, rede.id, "aplicar", _iee(), previa_id=str(p.json()["id"]))
    assert sem.status_code == 400 and "explicitamente" in sem.json()["detail"]
    invalida = _post(cliente_global, rede.id, "aplicar", _iee(), previa_id=str(p.json()["id"]),
                     substituir_calculadas="talvez")
    assert invalida.status_code == 400
    ok = _post(cliente_global, rede.id, "aplicar", _iee(), previa_id=str(p.json()["id"]),
               substituir_calculadas="sim")
    assert ok.status_code == 200, ok.text
    assert ok.json()["contadores"]["substituicoes_aplicadas"] == 4
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "indicador.importado")).scalar_one()
    assert log.detalhes["substituir_calculadas"] is True


def test_api_arquivo_nao_reconhecido_400_e_nada_registrado(db, escola_completa, cliente_global,
                                                          rede):
    r = _post(cliente_global, rede.id, "previa", b"A;B\r\n1;2\r\n", "x.csv")
    assert r.status_code == 400 and "Não reconheci" in r.json()["detail"]
    assert db.scalar(select(func.count(ImportacaoIndicador.id))) == 0


def test_patch_escola_com_inep_de_outra_escola_responde_409(db, escola_completa, cliente_global,
                                                           rede):
    gama = db.execute(select(Escola).where(Escola.nome == "ESCOLA SINTETICA GAMA")).scalar_one()
    alfa = _escola(db, "35990001")
    for codigo in ("35990001", "035990001", "35.990.001"):
        r = cliente_global.patch(f"/api/v1/redes/escolas/{gama.id}", json={"codigo_inep": codigo})
        assert r.status_code == 409, (codigo, r.text)
        assert "EMEF Sintética Alfa" in r.json()["detail"]
    # o INEP de escola de OUTRA rede também é de outra escola
    r = cliente_global.patch(f"/api/v1/redes/escolas/{gama.id}", json={"codigo_inep": "35880001"})
    assert r.status_code == 409
    db.expire_all()
    assert db.get(Escola, gama.id).codigo_inep is None
    # a própria escola regravando o seu código, um código livre e limpar: 200
    assert cliente_global.patch(f"/api/v1/redes/escolas/{alfa.id}",
                                json={"codigo_inep": "35990001"}).status_code == 200
    r = cliente_global.patch(f"/api/v1/redes/escolas/{gama.id}", json={"codigo_inep": "35990003"})
    assert r.status_code == 200 and r.json()["codigo_inep"] == "35990003"
    assert cliente_global.patch(f"/api/v1/redes/escolas/{gama.id}",
                                json={"codigo_inep": ""}).json()["codigo_inep"] is None


def test_banco_recusa_o_mesmo_inep_em_duas_escolas(db):
    from sqlalchemy.exc import IntegrityError
    db.add_all([Escola(nome="A", ano_letivo_ativo=2026, codigo_inep="35990009"),
                Escola(nome="B", ano_letivo_ativo=2026),
                Escola(nome="C", ano_letivo_ativo=2026)])     # várias sem INEP: livre
    db.commit()
    db.add(Escola(nome="D", ano_letivo_ativo=2026, codigo_inep="35990009"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_patch_rede_grava_e_limpa_o_codmun(db, escola_completa, cliente_global, rede):
    url = f"/api/v1/redes/{rede.id}"
    r = cliente_global.patch(url, json={"codigo_municipio_estadual": "903"})
    assert r.status_code == 200 and r.json()["codigo_municipio_estadual"] == "903"
    assert cliente_global.patch(url, json={"codigo_municipio_estadual": "abc"}).status_code == 422
    r = cliente_global.patch(url, json={"codigo_municipio_estadual": ""})
    assert r.status_code == 200 and r.json()["codigo_municipio_estadual"] is None
    gerenciar = cliente_global.get("/api/v1/redes/gerenciar").json()
    assert "codigo_municipio_estadual" in gerenciar["redes"][0]


# =============================================================================
# Regressão: consultas existentes, DELETE, presets e escalas
# =============================================================================

def test_opcoes_e_correlacao_ignoram_ausencias_e_numeros_de_referencia(db, rede):
    _aplicar(db, rede, _iee())
    _aplicar(db, rede, _municipio(), "Proficiência do SARESP por Municipio de 2025_0.csv")
    # uma série SÓ de ausências (a BETA no 2º ano) não pode virar opção nem ponto
    ops = svc.opcoes_rede(db, rede.id)
    series = {(o["avaliacao"], o["etapa"], o["componente"]) for o in ops}
    assert ("saresp", "2_ano", "portugues") in series and ("saresp", "5_ano", "matematica") in series
    assert all(o["avaliacao"] in ("saresp",) for o in ops)          # nada de iee/meta/município
    beta = _escola(db, "35990002")
    db.execute(ResultadoAvaliacao.__table__.delete().where(
        ResultadoAvaliacao.escola_id != beta.id))
    db.commit()
    ops = svc.opcoes_rede(db, rede.id)
    assert ("saresp", "2_ano", "portugues") not in {(o["avaliacao"], o["etapa"], o["componente"])
                                                    for o in ops}
    corr = svc.correlacao_rede(db, rede.id, avaliacao_chave="saresp", indicador="proficiencia",
                               edicao=2025, etapa="2_ano", componente="portugues")
    assert corr["pontos"] == [] and corr["evolucao"] == []          # ausência ≠ zero


def test_delete_so_de_escola_e_recusa_serie_com_numero_oficial(db, escola_completa,
                                                               cliente_global, rede):
    _aplicar(db, rede, _iee())
    _aplicar(db, rede, _municipio(), "Proficiência do SARESP por Municipio de 2025_0.csv")
    n_ref = db.scalar(select(func.count(IndicadorReferencia.id)))
    r = cliente_global.delete("/api/v1/avaliacoes/resultados?avaliacao=saresp&edicao=2025"
                              "&indicador=proficiencia&etapa=5_ano&componente=portugues")
    assert r.status_code == 409 and "desfaça a importação" in r.json()["detail"]
    db.expire_all()
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 8
    # série manual (sem prévia) da mesma tabela: apaga só ela; referência intocada
    _importar = "\n".join(["INEP;V", "35990001;6,1", "35990002;5,7"]).encode()
    svc.importar_resultados(db, _importar, "ideb.csv", avaliacao_chave="ideb", edicao=2023,
                            indicador="ideb", unidade="indice", linha_dados=1, col_inep=0,
                            col_valor=1, etapa_fixa="anos_iniciais", escopo_escolas=None)
    db.commit()
    r = cliente_global.delete("/api/v1/avaliacoes/resultados?avaliacao=ideb&edicao=2023"
                              "&indicador=ideb&etapa=anos_iniciais")
    assert r.status_code == 200 and r.json()["removidos"] == 2
    db.expire_all()
    assert db.scalar(select(func.count(IndicadorReferencia.id))) == n_ref


def _raw_saeb(pares) -> bytes:
    linhas = ["Resultados Anos Iniciais (1º ao 5º ano)", "SG_UF;ID_ESCOLA;VL_OBSERVADO_2023;"
              "VL_NOTA_MATEMATICA_2023;VL_NOTA_PORTUGUES_2023"]
    linhas += [f"SP;{inep};{ideb};{mt};{lp}" for inep, ideb, mt, lp in pares]
    return "\n".join(linhas).encode()


def test_presets_saeb_e_saresp_gravam_5_ano_e_o_ideb_continua_anos_iniciais(db, escola_completa,
                                                                            cliente_global):
    escola = escola_completa["escola"]
    escola.codigo_inep = "35990011"
    db.commit()
    arq = _raw_saeb([("35990011", "5,8", "211,4", "203,9")])
    for preset in ("ideb_ai", "saeb_ai"):
        r = cliente_global.post("/api/v1/avaliacoes/importar-preset",
                         data={"preset": preset, "edicao": 2023},
                         files={"arquivo": ("divulgacao_anos_iniciais_escolas.csv", arq)})
        assert r.status_code == 200, r.text
    saresp = "\n".join(["INEP;COMP;PROF", "35990011;portugues;183,3"]).encode()
    r = cliente_global.post("/api/v1/avaliacoes/importar-preset",
                     data={"preset": "saresp_ai", "edicao": 2024},
                     files={"arquivo": ("saresp.csv", saresp)})
    assert r.status_code == 200, r.text
    etapas = {(a, e) for a, e in db.execute(
        select(AvaliacaoExterna.chave, ResultadoAvaliacao.etapa).join(
            ResultadoAvaliacao, ResultadoAvaliacao.avaliacao_id == AvaliacaoExterna.id))}
    assert etapas == {("ideb", "anos_iniciais"), ("saeb", "5_ano"), ("saresp", "5_ano")}


def test_importacao_manual_de_saeb_ou_saresp_com_anos_iniciais_e_recusada(db, escola_completa,
                                                                          cliente_global):
    for avaliacao in ("saeb", "saresp"):
        r = cliente_global.post(
            "/api/v1/avaliacoes/importar",
            data={"avaliacao": avaliacao, "edicao": 2023, "indicador": "proficiencia",
                  "unidade": "escala_saeb", "linha_dados": 1, "col_inep": 0, "col_valor": 1,
                  "etapa_fixa": "anos_iniciais"},
            files={"arquivo": ("x.csv", b"INEP;V\n35990011;200,0")})
        assert r.status_code == 400 and "5_ano" in r.json()["detail"]
    r = cliente_global.post("/api/v1/avaliacoes/importar",
                     data={"avaliacao": "iee", "edicao": 2025, "indicador": "iee",
                           "unidade": "indice", "linha_dados": 1, "col_inep": 0,
                           "col_valor": 1},
                     files={"arquivo": ("x.csv", b"INEP;V\n35990011;5,0")})
    assert r.status_code == 400 and "SEDUC" in r.json()["detail"]
    assert "iee" not in {a["chave"] for a in cliente_global.get("/api/v1/avaliacoes").json()}
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 0


def test_etapa_anos_iniciais_lida_da_coluna_recusa_o_arquivo_inteiro(db, escola_completa,
                                                                     cliente_global):
    escola_completa["escola"].codigo_inep = "35990011"
    db.commit()

    def _importar(avaliacao, indicador, unidade, corpo):
        return cliente_global.post(
            "/api/v1/avaliacoes/importar",
            data={"avaliacao": avaliacao, "edicao": 2023, "indicador": indicador,
                  "unidade": unidade, "linha_dados": 1, "col_inep": 0, "col_valor": 2,
                  "col_etapa": 1},
            files={"arquivo": ("x.csv", ("INEP;ETAPA;V\n" + corpo).encode())})

    for avaliacao in ("saeb", "saresp"):
        for rotulo in ("anos_iniciais", "Anos Iniciais"):
            # a 1ª linha (5_ano) seria gravada antes de a 2ª ser lida: nada entra
            r = _importar(avaliacao, "proficiencia", "escala_saeb",
                          f"35990011;5_ano;200,0\n35990011;{rotulo};200,0")
            assert r.status_code == 400, r.text
            assert "1 linha(s)" in r.json()["detail"] and "5_ano" in r.json()["detail"]
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 0
    assert _importar("saeb", "proficiencia", "escala_saeb",
                     "35990011;5_ano;200,0").status_code == 200
    assert _importar("ideb", "ideb", "indice", "35990011;anos_iniciais;6,1").status_code == 200
    etapas = {(a, e) for a, e in db.execute(
        select(AvaliacaoExterna.chave, ResultadoAvaliacao.etapa).join(
            ResultadoAvaliacao, ResultadoAvaliacao.avaliacao_id == AvaliacaoExterna.id))}
    assert etapas == {("saeb", "5_ano"), ("ideb", "anos_iniciais")}


def test_fonte_do_robo_com_anos_iniciais_e_recusada_no_cadastro_e_na_coleta(
        db, escola_completa, cliente_global):
    from app.models import FonteAvaliacao

    def _fonte(avaliacao, mapeamento, indicador="proficiencia", unidade="escala_saeb"):
        return cliente_global.post("/api/v1/avaliacoes/fontes", json={
            "avaliacao": avaliacao, "nome": f"{avaliacao} sintética",
            "url": "https://exemplo.gov.br/x.csv", "edicao": 2023, "indicador": indicador,
            "unidade": unidade, "mapeamento": mapeamento})

    fixa = {"linha_dados": 1, "col_inep": 0, "col_valor": 1, "etapa_fixa": "anos_iniciais"}
    for avaliacao in ("saeb", "saresp"):
        r = _fonte(avaliacao, fixa)
        assert r.status_code == 400 and "5_ano" in r.json()["detail"]
    assert db.scalar(select(func.count(FonteAvaliacao.id))) == 0
    assert _fonte("ideb", fixa, "ideb", "indice").status_code == 201
    # Receita com a etapa na COLUNA: a coleta recusa o arquivo inteiro, sem gravar nada.
    r = _fonte("saeb", {"linha_dados": 1, "col_inep": 0, "col_valor": 2, "col_etapa": 1})
    assert r.status_code == 201, r.text
    escola_completa["escola"].codigo_inep = "35990011"
    db.commit()
    fonte = db.get(FonteAvaliacao, r.json()["id"])
    arquivo = b"INEP;ETAPA;V\n35990011;5_ano;200,0\n35990011;anos_iniciais;200,0"
    resumo = svc.coletar_fonte(db, fonte, baixador=lambda url: arquivo)
    db.commit()
    assert resumo["status"] == "erro" and "anos_iniciais" in fonte.ultimo_erro
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 0


def test_preset_devolve_e_audita_os_numeros_oficiais_mantidos(db, escola_completa,
                                                              cliente_global, rede):
    _aplicar(db, rede, _iee())
    manual = "\n".join(["INEP;COMP;PROF", "35990001;portugues;111,1"]).encode()
    r = cliente_global.post("/api/v1/avaliacoes/importar-preset",
                            data={"preset": "saresp_ai", "edicao": 2025},
                            files={"arquivo": ("saresp.csv", manual)})
    assert r.status_code == 200, r.text
    (serie,) = r.json()["series"]
    assert serie["mantidos_oficiais"] == 1 and serie["inseridos"] == serie["atualizados"] == 0
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "avaliacao.importada_preset")).scalar_one()
    assert log.detalhes["series"][0]["mantidos_oficiais"] == 1


def test_cortes_do_saresp_estao_todos_a_confirmar_e_nao_dao_nivel():
    assert escalas.CORTES_SARESP                      # a estrutura existe (2022–2025)
    assert all(not c.confirmado and c.situacao == "a_confirmar"
               and c.basico is c.adequado is c.avancado is None
               for c in escalas.CORTES_SARESP.values())
    r = escalas.classificar_saresp(205.0, 2024, "5_ano", "lp")
    assert r["nivel"] is None and r["distancia_adequado"] is None
    assert r["situacao"] == "a_confirmar" and r["calculo_do_constela"] is True
    # quando um corte for confirmado na fonte, a função classifica (estrutura pronta)
    confirmado = escalas.CortesSaresp(edicao=2099, etapa="5_ano", componente="lp", basico=10,
                                      adequado=20, avancado=30, situacao="confirmado",
                                      fonte="fixture sintética")
    escalas.CORTES_SARESP[(2099, "5_ano", "lp")] = confirmado
    try:
        assert escalas.classificar_saresp(15.0, 2099, "5_ano", "lp")["nivel"] == "basico"
        assert escalas.classificar_saresp(15.0, 2099, "5_ano", "lp")["distancia_adequado"] == 5.0
        assert escalas.classificar_saresp(31.0, 2099, "5_ano", "lp")["nivel"] == "avancado"
    finally:
        del escalas.CORTES_SARESP[(2099, "5_ano", "lp")]


def test_escalas_nao_se_misturam_saresp_2o_ano_nunca_com_o_ica():
    with pytest.raises(ValueError, match="não se comparam"):
        escalas.exigir_mesma_escala("escala_saresp", "escala_alfabetizacao")
    with pytest.raises(ValueError):
        escalas.exigir_mesma_escala("escala_saresp", "percentual")
    escalas.exigir_mesma_escala("escala_saresp", "escala_saresp")


# --- O mesmo fluxo num PostgreSQL de verdade ------------------------------------

from tests.test_migracoes_postgres import engine_postgres  # noqa: E402,F401 — fixture do PG de teste


@pytest.mark.postgres
def test_pipeline_seduc_no_postgres_substitui_reaplica_e_desfaz_exato(engine_postgres):
    from sqlalchemy.orm import sessionmaker

    from app.core.migracoes import aplicar_migracoes

    aplicar_migracoes(engine_postgres)
    db = sessionmaker(bind=engine_postgres)()
    try:
        r = Rede(nome="Rede Sintética PG", uf="SP", codigo_ibge=MUN,
                 codigo_municipio_estadual=CODMUN, status="ativa")
        db.add(r)
        db.flush()
        db.add_all([Escola(nome="EMEF Sintética Alfa", ano_letivo_ativo=2026, rede_id=r.id,
                           codigo_inep="35990001"),
                    Escola(nome="EMEF Sintética Beta", ano_letivo_ativo=2026, rede_id=r.id,
                           codigo_inep="35990002")])
        db.commit()
        _calculadas(db, r)
        antes = _estado(db)
        _, a = _aplicar(db, r, _iee(), substituir_calculadas=True)
        _, b = _aplicar(db, r, _iee())
        assert b["contadores"]["iguais"] == 20 and b["contadores"]["substituicoes"] == 0
        _aplicar(db, r, _municipio(), "Proficiência do SARESP por Municipio de 2025_0.csv")
        assert db.scalar(select(func.count(ResultadoAvaliacao.id)).where(
            ResultadoAvaliacao.valor.is_(None))) == 2                # ausências no PG
        lista = pipeline_seduc.listar(db, r)
        for item in lista:                                          # desfaz tudo, do fim
            if item["status"] == "aplicada":
                pipeline_seduc.desfazer(db, r, item["id"], usuario_id=None)
                db.commit()
        assert _estado(db) == antes
        assert a["contadores"]["substituicoes_aplicadas"] == 4
    finally:
        db.close()
