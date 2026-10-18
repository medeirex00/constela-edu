"""ICA oficial (etapa E2): parsers das planilhas do INEP, prévia/aplicação/desfazer,
precedência entre arquivos, permissões e a API de leitura da rede.

FIXTURES SINTÉTICAS no layout REAL dos arquivos "resultados e metas" do INEP
(linha 1 = rótulos, linha 2 = códigos das variáveis, observações no fim, 2025 em
inteiros × 2023/2024 com decimais, 2023 sem o ano no código do resultado, formato
de célula que mostra menos casas que o valor). Nenhum número, data ou texto de
rodapé aqui é do INEP: o repositório é público e os arquivos oficiais têm licença
CC BY-ND — não se copia nem recorte deles (decisão D13 do plano). Os números são
INVENTADOS e ficam longe dos oficiais (não são os do INEP com o inteiro trocado nem
com uma fração somada); só guardam as propriedades que os testes conferem.
"""
import io
import re
import zipfile
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.security import hash_senha
from app.main import app
from app.models import (Escola, ImportacaoIndicador, IndicadorReferencia, LogAuditoria,
                        Rede, ResultadoAvaliacao, Usuario)
from app.services.avaliacoes import ImportacaoRecusada
from app.services.indicadores import consulta, ica, pipeline

MUN = "3599999"            # município SINTÉTICO (UF 35)
NOME_MUN = "Município Sintético"
OUTRO = "3599998"

_ROTULOS = {
    "ANO": "ANO DA AVALIAÇÃO", "CO_UF": "CÓDIGO UF", "SG_UF": "SIGLA UF",
    "CO_MUNICIPIO": "CÓDIGO MUNICÍPIO", "NO_MUNICIPIO": "NOME DO MUNICÍPIO",
    "NO_TP_REDE": "REDE", "CD_UF": "CÓDIGO UF", "SIGLA_UF": "SIGLA UF",
    "NOME_UF": "NOME UF", "REDE": "REDE", "CO_NIVEL_ALFABETIZACAO": "NIVEL ALFABETIZAÇÃO",
    "NIVEIS_ALFABETIZACAO_2023": "NIVEL ALFABETIZAÇÃO",
    "PC_AVALIADOS_LP": "PERCENTUAL DE PARTICIPAÇÃO",
}
_METAS = [f"META_FINAL_{a}" for a in range(2024, 2031)]
_OBS = ["Observação 1: texto de rodapé sintético sobre os municípios sem resultado",
        "Observação 2: outro texto de rodapé sintético"]


def _codigos_municipios(layout: str) -> list[str]:
    if layout == "2023":
        resultados = ["PC_ALUNO_ALFABETIZADO"]
        nivel = "NIVEIS_ALFABETIZACAO_2023"
    else:
        anos = [2023, 2024] + ([2025] if layout == "2025" else [])
        resultados = [f"PC_ALUNO_ALFABETIZADO_{a}" for a in anos]
        nivel = "CO_NIVEL_ALFABETIZACAO"
    return ["ANO", "CO_UF", "SG_UF", "CO_MUNICIPIO", "NO_MUNICIPIO", "NO_TP_REDE",
            *resultados, *_METAS, nivel, "PC_AVALIADOS_LP"]


def _codigos_ufs(layout: str) -> list[str]:
    if layout == "2023":
        resultados = ["SAEB_2019", "SAEB_2021", "PC_ALUNO_ALFABETIZADO"]
    else:
        anos = [2023, 2024] + ([2025] if layout == "2025" else [])
        resultados = [f"PC_ALUNO_ALFABETIZADO_{a}" for a in anos]
    return ["ANO", "CD_UF", "SIGLA_UF", "NOME_UF", "REDE", *resultados, *_METAS,
            "PC_AVALIADOS_LP"]


def _com_data_interna(conteudo: bytes, quando: datetime) -> bytes:
    """O openpyxl regrava `modified` ao salvar: troca no docProps/core.xml (é onde o
    INEP deixa a data do arquivo, igual ao Last-Modified do servidor). Fixa também
    a data de criação e as datas das entradas do zip — que o openpyxl tira do
    relógio —, para o mesmo conteúdo gerar os MESMOS bytes: a aplicação confere o
    sha256 da prévia, e uma virada de segundo entre as duas chamadas mudaria o hash."""
    carimbo = quando.strftime("%Y-%m-%dT%H:%M:%SZ").encode()
    entrada, saida = zipfile.ZipFile(io.BytesIO(conteudo)), io.BytesIO()
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as novo:
        for item in entrada.infolist():
            dados = entrada.read(item.filename)
            if item.filename == "docProps/core.xml":
                dados = re.sub(rb"(<dcterms:(?:modified|created)[^>]*>)[^<]*"
                               rb"(</dcterms:(?:modified|created)>)",
                               rb"\g<1>" + carimbo + rb"\g<2>", dados)
            item.date_time = (2020, 1, 1, 0, 0, 0)
            novo.writestr(item, dados)
    return saida.getvalue()


def _sem_data_interna(conteudo: bytes, *, sem_core: bool = False) -> bytes:
    """O mesmo XLSX sem o dcterms:modified (ou sem o docProps/core.xml inteiro) —
    como sai de geradores que não gravam a data."""
    entrada, saida = zipfile.ZipFile(io.BytesIO(conteudo)), io.BytesIO()
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as novo:
        for item in entrada.infolist():
            dados = entrada.read(item.filename)
            if item.filename == "docProps/core.xml":
                if sem_core:
                    continue
                dados = re.sub(rb"<dcterms:modified[^>]*>[^<]*</dcterms:modified>", b"", dados)
            novo.writestr(item, dados)
    return saida.getvalue()


def _xlsx(codigos: list[str], linhas: list[dict], *, aba: str, quando: datetime | None = None,
          observacoes: list[str] = _OBS, formatos: dict[str, str] | None = None) -> bytes:
    """``formatos``: formato de célula (number_format) das linhas de dados, por código."""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = aba
    ws.append([_ROTULOS.get(c, c.replace("_", " ")) for c in codigos])   # linha 1: rótulos
    ws.append(codigos)                                                     # linha 2: códigos
    for linha in linhas:
        ws.append([linha.get(c) for c in codigos])
        for j, c in enumerate(codigos, start=1):
            if formatos and c in formatos:
                ws.cell(row=ws.max_row, column=j).number_format = formatos[c]
    ws.append([None] * len(codigos))
    for obs in observacoes:
        ws.append([obs] + [None] * (len(codigos) - 1))
    variaveis = wb.create_sheet("Variáveis")
    variaveis.append([None, "Níveis", "Percentual de alunos alfabetizados correspondente"])
    buf = io.BytesIO()
    wb.save(buf)
    return _com_data_interna(buf.getvalue(), quando) if quando else buf.getvalue()


def _municipio(ano: int, codigo: str = MUN, nome: str = NOME_MUN, rede: str = "MUNICIPAL",
               **valores) -> dict:
    return {"ANO": ano, "CO_UF": int(codigo[:2]), "SG_UF": "SP", "CO_MUNICIPIO": int(codigo),
            "NO_MUNICIPIO": nome, "NO_TP_REDE": rede, **valores}


# Números SINTÉTICOS (inventados para o teste), coerentes entre as três edições:
# 2025 em inteiros; 2024 e 2023 com decimais que arredondam para os inteiros. A meta
# final 80 é a da regra (metodologia), não resultado.
_METAS_2025 = dict(zip(_METAS, [25, 32, 34, 35, 36, 37, 80]))
_METAS_2024 = dict(zip(_METAS, [25.36, 31.93, 34.2, 35.4, 36.47, 36.6, 80]))
_METAS_2023 = dict(zip(_METAS, [25.3623456789012, 31.9312345678901, 34.2049999999,
                                35.3987654321, 36.4711111111, 36.6022222222, 80]))

# Datas internas SINTÉTICAS (não são as dos arquivos do INEP).
DATA_MUN_2025 = datetime(2026, 7, 15, 10, 0, 0)
DATA_MUN_2024 = datetime(2025, 12, 3, 9, 30, 0)
DATA_MUN_2023 = datetime(2024, 4, 22, 14, 5, 0)
DATA_UFS_2025 = datetime(2026, 7, 29, 11, 20, 0)
DATA_UFS_2023 = datetime(2024, 4, 22, 14, 4, 0)


def arq_mun_2025(**extra) -> bytes:
    alvo = _municipio(2025, PC_ALUNO_ALFABETIZADO_2023=26, PC_ALUNO_ALFABETIZADO_2024=22,
                      PC_ALUNO_ALFABETIZADO_2025=30, **_METAS_2025,
                      CO_NIVEL_ALFABETIZACAO=1, PC_AVALIADOS_LP=73)
    alvo.update(extra)
    outro = _municipio(2025, OUTRO, "Vizinho Sintético", PC_ALUNO_ALFABETIZADO_2023=88,
                       PC_ALUNO_ALFABETIZADO_2024=90, PC_ALUNO_ALFABETIZADO_2025=92,
                       **_METAS_2025, CO_NIVEL_ALFABETIZACAO=5, PC_AVALIADOS_LP=99.5)
    return _xlsx(_codigos_municipios("2025"), [outro, alvo], aba="Divulgação Alfabet Municipio",
                 quando=DATA_MUN_2025)


def arq_mun_2024() -> bytes:
    alvo = _municipio(2024, PC_ALUNO_ALFABETIZADO_2023=26.2, PC_ALUNO_ALFABETIZADO_2024=21.84,
                      **_METAS_2024, CO_NIVEL_ALFABETIZACAO=1, PC_AVALIADOS_LP=72.3112345)
    return _xlsx(_codigos_municipios("2024"), [alvo], aba="Divulgação Alfabet Municipio",
                 quando=DATA_MUN_2024, observacoes=[],
                 formatos={"PC_ALUNO_ALFABETIZADO_2024": "0.00", "PC_AVALIADOS_LP": "0.00"})


def arq_mun_2023() -> bytes:
    # Como no layout real: o formato do resultado MOSTRA 1 casa, mas o valor tem 2
    # (o formato não corta a precisão); o das metas mostra 2 (34,20; 80,00).
    alvo = _municipio(2023, PC_ALUNO_ALFABETIZADO=26.18, **_METAS_2023,
                      NIVEIS_ALFABETIZACAO_2023=0, PC_AVALIADOS_LP=71.4)
    return _xlsx(_codigos_municipios("2023"), [alvo], aba="Divulgação Alfabet Municipio",
                 quando=DATA_MUN_2023,
                 formatos={"PC_ALUNO_ALFABETIZADO": "0.0", "PC_AVALIADOS_LP": "0.0",
                           **dict.fromkeys(_METAS, "0.00")})


def arq_ufs_2025() -> bytes:
    metas_sp = dict(zip(_METAS, [26, 33, 35, 37, 38, 39, "> 80"]))
    metas_br = dict(zip(_METAS, [22, 23, 28, 37, 39, 40, "> 80"]))
    linhas = [
        {"ANO": 2025, "CD_UF": None, "SIGLA_UF": None, "NOME_UF": "Brasil", "REDE": "PÚBLICA",
         "PC_ALUNO_ALFABETIZADO_2023": 27, "PC_ALUNO_ALFABETIZADO_2024": 26,
         "PC_ALUNO_ALFABETIZADO_2025": 23, **metas_br, "PC_AVALIADOS_LP": 74},
        {"ANO": 2025, "CD_UF": 12, "SIGLA_UF": "AC", "NOME_UF": "Acre", "REDE": "PÚBLICA",
         "PC_ALUNO_ALFABETIZADO_2023": None, "PC_ALUNO_ALFABETIZADO_2024": 18,
         "PC_ALUNO_ALFABETIZADO_2025": 21, **metas_br, "PC_AVALIADOS_LP": 71},
        {"ANO": 2025, "CD_UF": 35, "SIGLA_UF": "SP", "NOME_UF": "São Paulo", "REDE": "PÚBLICA",
         "PC_ALUNO_ALFABETIZADO_2023": 18, "PC_ALUNO_ALFABETIZADO_2024": 26,
         "PC_ALUNO_ALFABETIZADO_2025": 34, **metas_sp, "PC_AVALIADOS_LP": 72},
        # Outra rede da mesma UF: ignorada (o ICA de UF/Brasil gravado é o da pública).
        {"ANO": 2025, "CD_UF": 35, "SIGLA_UF": "SP", "NOME_UF": "São Paulo", "REDE": "ESTADUAL",
         "PC_ALUNO_ALFABETIZADO_2023": 15, "PC_ALUNO_ALFABETIZADO_2024": 17,
         "PC_ALUNO_ALFABETIZADO_2025": 19, **metas_sp, "PC_AVALIADOS_LP": 75},
    ]
    return _xlsx(_codigos_ufs("2025"), linhas, aba="Divulgação Alfabet UF e Brasil",
                 quando=DATA_UFS_2025,
                 observacoes=["* Dado atualizado (nota sintética de rodapé)."])


def arq_ufs_2023() -> bytes:
    metas = dict(zip(_METAS, [21.4, 27.9, 29.3, 33.6, 34.2, 38.1, "> 80"]))
    linhas = [
        {"ANO": 2023, "CD_UF": None, "SIGLA_UF": None, "NOME_UF": "Brasil", "REDE": "PÚBLICA",
         "SAEB_2019": 71.6, "SAEB_2021": 21.3, "PC_ALUNO_ALFABETIZADO": 26.876543,
         **metas, "PC_AVALIADOS_LP": 74},
        {"ANO": 2023, "CD_UF": 35, "SIGLA_UF": "SP", "NOME_UF": "São Paulo", "REDE": "PÚBLICA",
         "SAEB_2019": 73.4, "SAEB_2021": 24.6, "PC_ALUNO_ALFABETIZADO": 18.12,
         **metas, "PC_AVALIADOS_LP": 73.5},
    ]
    return _xlsx(_codigos_ufs("2023"), linhas, aba="Divulgação Alfabet UF e Brasil",
                 quando=DATA_UFS_2023)


def _por_chave(leitura: ica.LeituraICA) -> dict:
    return {(ln.abrangencia, ln.indicador, ln.edicao): ln for ln in leitura.linhas}


# --- Parsers (puros) -------------------------------------------------------------

def test_municipios_2025_grava_so_a_linha_da_rede_em_inteiros():
    leitura = ica.ler_planilha_ica(arq_mun_2025(), "resultados_e_metas_municipios_2025_3.xlsx",
                                   codigo_ibge=MUN)
    assert leitura.parser == ica.PARSER_MUNICIPIOS
    assert leitura.edicao_arquivo == 2025
    assert leitura.arquivo_data == DATA_MUN_2025               # dcterms:modified do arquivo
    assert ica.AVISO_SEM_DATA not in leitura.avisos
    assert leitura.territorios == {MUN: NOME_MUN}            # o vizinho NÃO entra
    assert {ln.codigo_territorio for ln in leitura.linhas} == {MUN}
    assert all(ln.rede_ensino == "municipal" and ln.abrangencia == "municipio"
               and ln.etapa == "2_ano" and ln.componente == "lp" for ln in leitura.linhas)
    por = _por_chave(leitura)
    assert [por[("municipio", "percentual_alfabetizado", a)].valor
            for a in (2023, 2024, 2025)] == [26, 22, 30]
    assert all(por[("municipio", "percentual_alfabetizado", a)].casas_decimais == 0
               for a in (2023, 2024, 2025))
    assert [por[("municipio", "meta", a)].valor for a in range(2024, 2031)] == [
        25, 32, 34, 35, 36, 37, 80]
    assert por[("municipio", "nivel_municipio", 2025)].valor == 1
    assert por[("municipio", "participacao", 2025)].valor == 73
    assert len(leitura.linhas) == 12
    assert leitura.linhas_lidas == 2                           # observações não contam
    assert any(n.startswith("Observação 1") for n in leitura.notas_arquivo)


def test_municipios_2023_edicao_vem_da_coluna_ano_e_decimais_viram_2_casas():
    leitura = ica.ler_planilha_ica(arq_mun_2023(), "resultados_e_metas_municipios.xlsx",
                                   codigo_ibge=MUN)
    por = _por_chave(leitura)
    resultado = por[("municipio", "percentual_alfabetizado", 2023)]
    # o formato da célula mostra 1 casa, o valor publicado tem 2: valem as 2
    assert (resultado.valor, resultado.casas_decimais) == (26.18, 2)
    # metas com os 15 dígitos do cálculo → 2 casas (meio para cima)
    assert [por[("municipio", "meta", a)].valor for a in range(2024, 2031)] == [
        25.36, 31.93, 34.2, 35.4, 36.47, 36.6, 80]
    # a precisão é a PUBLICADA na coluna (formato 0,00): 34,20 e 80,00 têm 2 casas —
    # o zero final que o float perdeu não tira a casa
    assert {por[("municipio", "meta", a)].casas_decimais for a in range(2024, 2031)} == {2}
    assert por[("municipio", "nivel_municipio", 2023)].valor == 0  # NIVEIS_ALFABETIZACAO_2023
    participacao = por[("municipio", "participacao", 2023)]
    assert (participacao.valor, participacao.casas_decimais) == (71.4, 1)


def test_casas_decimais_sao_as_publicadas_na_coluna_nao_as_do_valor():
    """O float perde o zero final (27,90 → 27.9; 22,0 → 22), a coluna não: a precisão
    é o máximo de casas entre os valores da coluna (até 2), ou o que o formato da
    célula mostra, quando mostra mais. O formato que mostra MENOS não corta casas."""
    codigos = _codigos_municipios("2024")
    alvo = _municipio(2024, PC_ALUNO_ALFABETIZADO_2023=22, PC_ALUNO_ALFABETIZADO_2024=27.9,
                      **{**_METAS_2024, "META_FINAL_2024": 27.86, "META_FINAL_2030": 80},
                      CO_NIVEL_ALFABETIZACAO=1, PC_AVALIADOS_LP=72)
    vizinho = _municipio(2024, OUTRO, "Vizinho Sintético", PC_ALUNO_ALFABETIZADO_2023=88.1,
                         PC_ALUNO_ALFABETIZADO_2024=90.35, **_METAS_2024,
                         CO_NIVEL_ALFABETIZACAO=5, PC_AVALIADOS_LP=99.27)
    arq = _xlsx(codigos, [vizinho, alvo], aba="X",
                formatos={"META_FINAL_2030": "0.00", "PC_AVALIADOS_LP": "0"})
    por = _por_chave(ica.ler_planilha_ica(arq, "a.xlsx", codigo_ibge=MUN))
    casas = {k[1:]: (ln.valor, ln.casas_decimais) for k, ln in por.items()}
    assert casas[("percentual_alfabetizado", 2024)] == (27.9, 2)   # 27,90 (coluna de 2 casas)
    assert casas[("percentual_alfabetizado", 2023)] == (22, 1)     # 22,0 (coluna de 1 casa)
    assert casas[("meta", 2024)] == (27.86, 2)
    assert casas[("meta", 2030)] == (80, 2)                         # o formato mostra 80,00
    assert casas[("participacao", 2024)] == (72, 2)                 # formato "0" não corta
    assert casas[("nivel_municipio", 2024)] == (1, 0)


def test_colunas_localizadas_pelo_codigo_nao_pela_posicao():
    codigos = _codigos_municipios("2025")
    embaralhados = list(reversed(codigos))
    alvo = _municipio(2025, PC_ALUNO_ALFABETIZADO_2023=26, PC_ALUNO_ALFABETIZADO_2024=22,
                      PC_ALUNO_ALFABETIZADO_2025=30, **_METAS_2025,
                      CO_NIVEL_ALFABETIZACAO=1, PC_AVALIADOS_LP=73)
    normal = ica.ler_planilha_ica(_xlsx(codigos, [alvo], aba="X"), "a.xlsx", codigo_ibge=MUN)
    invertido = ica.ler_planilha_ica(_xlsx(embaralhados, [alvo], aba="X"), "a.xlsx",
                                     codigo_ibge=MUN)
    assert sorted(normal.linhas, key=lambda ln: ln.chave) == sorted(
        invertido.linhas, key=lambda ln: ln.chave)


_UF_SP = {"ANO": 2025, "CD_UF": 35, "SIGLA_UF": "SP", "NOME_UF": "São Paulo",
          "REDE": "PÚBLICA", "PC_ALUNO_ALFABETIZADO_2025": 34}


@pytest.mark.parametrize("layout, tirar, esperado", [
    ("municipios", "NO_TP_REDE", "NO_TP_REDE"),
    ("municipios", "ANO", "ANO"),
    ("municipios", "METAS", "META_FINAL_<ano>"),
    ("ufs", "REDE", "REDE"),
    ("ufs", "ANO", "ANO"),
    ("ufs", "METAS", "META_FINAL_<ano>"),
    ("ufs", "CD_UF", "CD_UF"),        # sem ele o arquivo nem é reconhecido como de UF
    ("ufs", "NOME_UF", "NOME_UF"),
])
def test_recusa_se_falta_coluna_exigida(layout, tirar, esperado):
    todos = _codigos_municipios("2025") if layout == "municipios" else _codigos_ufs("2025")
    codigos = [c for c in todos
               if c != tirar and not (tirar == "METAS" and c.startswith("META_FINAL"))]
    linha = (_municipio(2025, PC_ALUNO_ALFABETIZADO_2025=30) if layout == "municipios"
             else _UF_SP)
    arq = _xlsx(codigos, [linha], aba="X")
    with pytest.raises(ImportacaoRecusada, match=re.escape(esperado)):
        ica.ler_planilha_ica(arq, "a.xlsx", codigo_ibge=MUN)


def test_recusa_coluna_repetida_e_arquivo_que_nao_e_do_ica():
    codigos = _codigos_municipios("2025") + ["META_FINAL_2025"]
    with pytest.raises(ImportacaoRecusada, match="mais de uma vez"):
        ica.ler_planilha_ica(_xlsx(codigos, [], aba="X"), "a.xlsx", codigo_ibge=MUN)
    # Planilha de outra coisa (sem PC_ALUNO_ALFABETIZADO na linha técnica)
    with pytest.raises(ImportacaoRecusada, match="não parece a planilha oficial"):
        ica.ler_planilha_ica(_xlsx(["ID_ESCOLA", "VL_OBSERVADO_2023"], [], aba="X"),
                             "ideb.xlsx", codigo_ibge=MUN)
    with pytest.raises(ImportacaoRecusada, match="não é uma planilha XLSX"):
        ica.ler_planilha_ica(b"a;b\n1;2", "ica.csv", codigo_ibge=MUN)
    with pytest.raises(ImportacaoRecusada, match="Não consegui abrir"):
        ica.ler_planilha_ica(b"isto nao e um zip", "ica.xlsx", codigo_ibge=MUN)


def test_recusa_valor_fora_da_faixa():
    with pytest.raises(ImportacaoRecusada, match="fora da faixa"):
        ica.ler_planilha_ica(arq_mun_2025(PC_ALUNO_ALFABETIZADO_2025=120), "a.xlsx",
                             codigo_ibge=MUN)
    with pytest.raises(ImportacaoRecusada, match="escala oficial"):
        ica.ler_planilha_ica(arq_mun_2025(CO_NIVEL_ALFABETIZACAO=7), "a.xlsx",
                             codigo_ibge=MUN)


def test_so_a_rede_municipal_e_municipio_ausente_nao_grava_nada():
    estadual = _municipio(2025, rede="ESTADUAL", PC_ALUNO_ALFABETIZADO_2025=33, **_METAS_2025)
    leitura = ica.ler_planilha_ica(_xlsx(_codigos_municipios("2025"), [estadual], aba="X"),
                                   "a.xlsx", codigo_ibge=MUN)
    assert leitura.linhas == [] and "rede MUNICIPAL" in " ".join(leitura.avisos)

    leitura = ica.ler_planilha_ica(arq_mun_2025(), "a.xlsx", codigo_ibge="3511111")
    assert leitura.linhas == []
    assert "não está no arquivo" in " ".join(leitura.avisos)


def test_ausencia_nao_e_zero_com_o_motivo_do_arquivo():
    """Vazio/"-" = não divulgado; vazio com participação < 70% no próprio arquivo =
    participação baixa; meta 0 = sem meta (0% não é meta). Nunca valor 0."""
    arq = arq_mun_2025(PC_ALUNO_ALFABETIZADO_2023="-", PC_ALUNO_ALFABETIZADO_2025=None,
                       PC_AVALIADOS_LP=65, META_FINAL_2024=0)
    leitura = ica.ler_planilha_ica(arq, "a.xlsx", codigo_ibge=MUN)
    por = _por_chave(leitura)
    r23 = por[("municipio", "percentual_alfabetizado", 2023)]
    r25 = por[("municipio", "percentual_alfabetizado", 2025)]
    meta24 = por[("municipio", "meta", 2024)]
    assert (r23.valor, r23.motivo_ausencia) == (None, "nao_divulgado")
    assert (r25.valor, r25.motivo_ausencia) == (None, "participacao_baixa")
    assert (meta24.valor, meta24.motivo_ausencia) == (None, "sem_meta")
    assert any("META 2024 = 0" in a and "0% não é meta" in a for a in leitura.avisos)
    assert all(ln.valor != 0 for ln in leitura.linhas)


def test_ufs_grava_a_uf_da_rede_e_o_brasil_com_operador_da_meta():
    leitura = ica.ler_planilha_ica(arq_ufs_2025(), "resultados_e_metas_ufs_2025_v2.xlsx",
                                   codigo_ibge=MUN)
    assert leitura.parser == ica.PARSER_UFS and leitura.edicao_arquivo == 2025
    assert leitura.territorios == {"35": "São Paulo", "BR": "Brasil"}   # o Acre não entra
    por = _por_chave(leitura)
    # a linha ESTADUAL de SP (19) é ignorada: grava só a da rede pública
    assert por[("uf", "percentual_alfabetizado", 2025)].valor == 34
    assert len([ln for ln in leitura.linhas if ln.abrangencia == "uf"]) == 11
    assert por[("brasil", "percentual_alfabetizado", 2025)].valor == 23
    meta30 = por[("brasil", "meta", 2030)]
    assert (meta30.valor, meta30.operador) == (80, ">")              # "> 80" do arquivo
    assert all(ln.rede_ensino == "publica" for ln in leitura.linhas)
    assert not any(ln.indicador == "nivel_municipio" for ln in leitura.linhas)
    assert leitura.notas_arquivo == ["* Dado atualizado (nota sintética de rodapé)."]


def test_ufs_2023_ignora_o_saeb_antigo_com_aviso():
    leitura = ica.ler_planilha_ica(arq_ufs_2023(), "resultados_e_metas_ufs.xlsx",
                                   codigo_ibge=MUN)
    por = _por_chave(leitura)
    assert por[("brasil", "percentual_alfabetizado", 2023)].valor == 26.88
    assert not any(ln.edicao in (2019, 2021) for ln in leitura.linhas)
    assert any("SAEB_2019" in a for a in leitura.avisos)


# --- Pipeline: prévia, aplicação, precedência e desfazer --------------------------

@pytest.fixture()
def rede(db):
    r = Rede(nome="Rede Sintética", uf="SP", codigo_ibge=MUN, status="ativa")
    db.add(r)
    db.commit()
    return r


def _aplicar(db, rede, conteudo, nome="arquivo.xlsx"):
    p = pipeline.previa(db, rede, conteudo, nome, usuario_id=None)
    db.commit()
    a = pipeline.aplicar(db, rede, p["id"], conteudo, nome, usuario_id=None)
    db.commit()
    return a


def _estado(db) -> list[tuple]:
    db.expire_all()
    return sorted(
        (r.edicao, r.indicador, r.abrangencia, r.codigo_territorio, r.rede_ensino, r.valor,
         r.valor_detalhado, r.casas_decimais, r.operador, r.motivo_ausencia, r.unidade,
         r.importacao_id, r.detalhe_importacao_id, r.created_at, r.updated_at)
        for r in db.execute(select(IndicadorReferencia)).scalars())


def _valores(db) -> dict:
    db.expire_all()
    return {(r.abrangencia, r.indicador, r.edicao): (r.valor, r.valor_detalhado)
            for r in db.execute(select(IndicadorReferencia)).scalars()}


def test_previa_nao_grava_numero_nenhum(db, rede):
    p = pipeline.previa(db, rede, arq_mun_2025(), "m.xlsx", usuario_id=None)
    db.commit()
    assert db.scalar(select(func.count(IndicadorReferencia.id))) == 0
    imp = db.get(ImportacaoIndicador, p["id"])
    assert imp.status == "previa" and len(imp.arquivo_sha256) == 64
    assert imp.edicao_arquivo == 2025 and imp.parser == ica.PARSER_MUNICIPIOS
    assert p["contadores"]["novas"] == 12 and p["contadores"]["alteradas"] == 0
    assert {m["tipo"] for m in p["mudancas"]} == {"nova"}


def test_aplicar_duas_vezes_o_mesmo_arquivo_deixa_o_mesmo_estado(db, rede):
    _aplicar(db, rede, arq_mun_2025())
    _aplicar(db, rede, arq_ufs_2025())
    antes = _estado(db)
    a = _aplicar(db, rede, arq_mun_2025())
    b = _aplicar(db, rede, arq_ufs_2025())
    assert a["contadores"]["iguais"] == 12 and a["contadores"]["novas"] == 0
    assert a["contadores"]["alteradas"] == 0 and a["contadores"]["fonte_atualizada"] == 0
    assert b["contadores"]["iguais"] == 22
    assert _estado(db) == antes                    # nem a proveniência muda


def test_aplicar_exige_o_mesmo_arquivo_da_previa_e_uma_vez_so(db, rede):
    p = pipeline.previa(db, rede, arq_mun_2025(), "m.xlsx", usuario_id=None)
    db.commit()
    with pytest.raises(ImportacaoRecusada, match="não é o mesmo da prévia"):
        pipeline.aplicar(db, rede, p["id"], arq_mun_2024(), "m.xlsx", usuario_id=None)
    db.rollback()
    pipeline.aplicar(db, rede, p["id"], arq_mun_2025(), "m.xlsx", usuario_id=None)
    db.commit()
    with pytest.raises(ImportacaoRecusada, match="já foi aplicada"):
        pipeline.aplicar(db, rede, p["id"], arq_mun_2025(), "m.xlsx", usuario_id=None)


def test_precedencia_capa_do_mais_recente_e_decimais_como_detalhe_em_qualquer_ordem(db, rede):
    arquivos = [arq_mun_2025(), arq_mun_2024(), arq_mun_2023()]
    for conteudo in arquivos:
        _aplicar(db, rede, conteudo)
    v = _valores(db)
    # capa = 2025 (inteiros); detalhe = o de MAIS casas que arredonda (26,18 vence 26,2)
    assert v[("municipio", "percentual_alfabetizado", 2023)] == (26, 26.18)
    assert v[("municipio", "percentual_alfabetizado", 2024)] == (22, 21.84)
    assert v[("municipio", "percentual_alfabetizado", 2025)] == (30, None)
    assert v[("municipio", "meta", 2024)] == (25, 25.36)
    assert v[("municipio", "meta", 2028)] == (36, 36.47)
    # o arquivo de 2023 publica 80,00 (2 casas, mais que a capa inteira): vira detalhe
    assert v[("municipio", "meta", 2030)] == (80, 80)
    # nível e participação são da edição de cada arquivo
    assert v[("municipio", "nivel_municipio", 2023)] == (0, None)
    assert v[("municipio", "participacao", 2024)] == (72.31, None)
    ordem_direta = v

    # Mesmos valores importando na ordem inversa (num banco limpo).
    db.query(IndicadorReferencia).delete()
    db.query(ImportacaoIndicador).delete()
    db.commit()
    for conteudo in reversed(arquivos):
        _aplicar(db, rede, conteudo)
    assert _valores(db) == ordem_direta


def test_detalhe_que_nao_arredonda_e_descartado_com_aviso(db, rede):
    _aplicar(db, rede, arq_mun_2025())
    alvo = _municipio(2024, PC_ALUNO_ALFABETIZADO_2023=23.9, PC_ALUNO_ALFABETIZADO_2024=21.84,
                      **_METAS_2024, CO_NIVEL_ALFABETIZACAO=1, PC_AVALIADOS_LP=72.3)
    arq = _xlsx(_codigos_municipios("2024"), [alvo], aba="X", quando=datetime(2025, 11, 26))
    p = pipeline.previa(db, rede, arq, "m2024.xlsx", usuario_id=None)
    assert any("divergência entre arquivos" in a for a in p["avisos"])
    db.commit()
    pipeline.aplicar(db, rede, p["id"], arq, "m2024.xlsx", usuario_id=None)
    db.commit()
    assert _valores(db)[("municipio", "percentual_alfabetizado", 2023)] == (26, None)


def _versao_2025(valor, quando: datetime | None) -> bytes:
    alvo = _municipio(2025, PC_ALUNO_ALFABETIZADO_2023=26, PC_ALUNO_ALFABETIZADO_2024=22,
                      PC_ALUNO_ALFABETIZADO_2025=valor, **_METAS_2025,
                      CO_NIVEL_ALFABETIZACAO=1, PC_AVALIADOS_LP=73)
    return _xlsx(_codigos_municipios("2025"), [alvo], aba="X", quando=quando)


def _limpar(db):
    db.query(IndicadorReferencia).delete()
    db.query(ImportacaoIndicador).delete()
    db.commit()


def test_mesma_edicao_vence_a_versao_mais_nova_do_arquivo(db, rede):
    """v3 (data interna mais nova) traz o valor REVISADO, em QUALQUER ordem:
    reimportar a v2 depois não desfaz a revisão, e a v3 depois da v2 a aplica."""
    v3 = _versao_2025(30, datetime(2026, 7, 15))
    v2 = _versao_2025(29, datetime(2026, 5, 4))
    _aplicar(db, rede, v3)
    a = _aplicar(db, rede, v2)
    assert _valores(db)[("municipio", "percentual_alfabetizado", 2025)] == (30, None)
    assert a["contadores"]["alteradas"] == 0
    final = _valores(db)

    _limpar(db)
    _aplicar(db, rede, v2)
    b = _aplicar(db, rede, v3)
    assert _valores(db)[("municipio", "percentual_alfabetizado", 2025)] == (30, None)
    assert b["contadores"]["alteradas"] == 1                 # só o resultado revisado
    assert _valores(db) == final                             # a ordem não muda o fim


@pytest.mark.parametrize("sem_core", [False, True])
def test_arquivo_sem_data_interna_fica_sem_data_e_nao_vence_a_versao_datada(db, rede, sem_core):
    """Sem dcterms:modified (ou sem docProps/core.xml), a data fica NULA — nunca a hora
    da leitura, que o openpyxl põe no lugar. Assim a v2 sem data não passa à frente
    da v3 datada, em qualquer ordem, e reimportar a v2 não muda nada."""
    v3 = _versao_2025(30, datetime(2026, 7, 15))
    v2 = _sem_data_interna(_versao_2025(29, datetime(2026, 5, 4)), sem_core=sem_core)
    leitura = ica.ler_planilha_ica(v2, "resultados_e_metas_municipios_2025_2.xlsx",
                                   codigo_ibge=MUN)
    assert leitura.arquivo_data is None
    assert ica.AVISO_SEM_DATA in leitura.avisos

    _aplicar(db, rede, v3)
    estado = _estado(db)
    a = _aplicar(db, rede, v2)
    b = _aplicar(db, rede, v2)                               # o mesmo arquivo de novo
    assert _valores(db)[("municipio", "percentual_alfabetizado", 2025)] == (30, None)
    for c in (a["contadores"], b["contadores"]):
        assert (c["alteradas"], c["fonte_atualizada"], c["iguais"]) == (0, 0, 12)
    assert _estado(db) == estado                             # nem a proveniência muda
    assert a["arquivo_data"] is None and ica.AVISO_SEM_DATA in a["avisos"]
    selo = consulta.ica_da_rede(db, rede)["fontes"]
    # só a v3 está nos números (o selo nunca mostra a hora da importação como data)
    assert [f["arquivo_data"] for f in selo] == [datetime(2026, 7, 15).isoformat()]

    _limpar(db)
    _aplicar(db, rede, v2)
    c = _aplicar(db, rede, v3)                               # a revisão entra
    assert _valores(db)[("municipio", "percentual_alfabetizado", 2025)] == (30, None)
    assert c["contadores"]["alteradas"] == 1


def test_previa_avisa_data_interna_posterior_ao_last_modified(db, rede):
    """Data interna DEPOIS da publicação (Last-Modified informado) = arquivo salvo de
    novo depois de baixado: a prévia avisa (a precedência segue a data interna)."""
    salvo_de_novo = _versao_2025(29, datetime(2026, 10, 1, 9, 0))
    p = pipeline.previa(db, rede, salvo_de_novo, "m.xlsx", usuario_id=None,
                        last_modified_origem="Mon, 04 May 2026 12:00:00 GMT")
    assert any("posterior ao Last-Modified" in a for a in p["avisos"])
    ok = pipeline.previa(db, rede, arq_mun_2025(), "m.xlsx", usuario_id=None,
                         last_modified_origem="Wed, 15 Jul 2026 10:30:00 GMT")
    assert not any("Last-Modified" in a for a in ok["avisos"])
    ilegivel = pipeline.previa(db, rede, arq_mun_2025(), "m.xlsx", usuario_id=None,
                               last_modified_origem="ontem à tarde")
    assert not any("Last-Modified" in a for a in ilegivel["avisos"])


def test_decimal_terminado_em_zero_mantem_a_precisao_publicada(db, rede):
    """Números SINTÉTICOS. 27,90 × meta 27,86 publicados com 2 casas = +0,04 p.p.
    ("atingiu"); com a precisão do float (27,9 → 1 casa) seria empate. O mesmo vale
    para o DETALHE de uma capa inteira (29,90 × 31,02 = −1,12 p.p., não −1,1) e para
    um decimal que o float deixa inteiro (20,0 numa coluna de 1 casa continua
    detalhe da capa 20, em vez de sumir)."""
    m2024 = dict(_METAS_2024, META_FINAL_2024=27.86, META_FINAL_2025=31.02)
    alvo = _municipio(2024, PC_ALUNO_ALFABETIZADO_2023=20.0, PC_ALUNO_ALFABETIZADO_2024=27.9,
                      **m2024, CO_NIVEL_ALFABETIZACAO=1, PC_AVALIADOS_LP=72.25)
    vizinho = _municipio(2024, OUTRO, "Vizinho Sintético", PC_ALUNO_ALFABETIZADO_2023=88.1,
                         PC_ALUNO_ALFABETIZADO_2024=90.35, **_METAS_2024,
                         CO_NIVEL_ALFABETIZACAO=5, PC_AVALIADOS_LP=99.27)
    a2024 = _xlsx(_codigos_municipios("2024"), [vizinho, alvo], aba="X",
                  quando=datetime(2025, 12, 3))

    def resultado_2025(valor, quando, valor_vizinho):
        m2025 = dict(_METAS_2025, META_FINAL_2024=28, META_FINAL_2025=31)
        alvo = _municipio(2025, PC_ALUNO_ALFABETIZADO_2023=20, PC_ALUNO_ALFABETIZADO_2024=28,
                          PC_ALUNO_ALFABETIZADO_2025=valor, **m2025,
                          CO_NIVEL_ALFABETIZACAO=1, PC_AVALIADOS_LP=72)
        vizinho = _municipio(2025, OUTRO, "Vizinho Sintético", PC_ALUNO_ALFABETIZADO_2023=88,
                             PC_ALUNO_ALFABETIZADO_2024=90,
                             PC_ALUNO_ALFABETIZADO_2025=valor_vizinho, **_METAS_2025,
                             CO_NIVEL_ALFABETIZACAO=5, PC_AVALIADOS_LP=100)
        return _xlsx(_codigos_municipios("2025"), [vizinho, alvo], aba="X", quando=quando)
    v3 = resultado_2025(30, datetime(2026, 7, 15), 92)            # inteiros (capa)
    v2 = resultado_2025(29.9, datetime(2026, 5, 4), 91.85)        # 2 casas: 29,90

    # Só o arquivo de 2024: 27,90 × 27,86 na precisão publicada (2 casas).
    _aplicar(db, rede, a2024)
    mun = consulta.ica_da_rede(db, rede)["territorios"][0]
    r2024 = next(r for r in mun["resultados"] if r["edicao"] == 2024)
    assert (r2024["valor"], r2024["casas_decimais"]) == (27.9, 2)
    c2024 = next(c for c in mun["comparacoes"] if c["edicao"] == 2024)
    assert (c2024["diferenca_pp"], c2024["casas_decimais"], c2024["situacao"]) == (
        0.04, 2, "atingiu")

    def conferir():
        mun = consulta.ica_da_rede(db, rede)["territorios"][0]
        por = {r["edicao"]: r for r in mun["resultados"]}
        comp = {c["edicao"]: c for c in mun["comparacoes"]}
        # capa inteira; o decimal terminado em zero fica como detalhe COM a precisão
        assert (por[2023]["valor"], por[2023]["detalhe"]["valor"],
                por[2023]["detalhe"]["casas_decimais"]) == (20, 20.0, 1)
        assert (por[2024]["valor"], por[2024]["detalhe"]["valor"],
                por[2024]["detalhe"]["casas_decimais"]) == (28, 27.9, 2)
        assert (por[2025]["valor"], por[2025]["detalhe"]["valor"],
                por[2025]["detalhe"]["casas_decimais"]) == (30, 29.9, 2)
        # 28 × 28 empata na capa; o detalhe (2 casas) decide: +0,04
        assert (comp[2024]["diferenca_pp"], comp[2024]["diferenca_pp_detalhe"],
                comp[2024]["casas_decimais_detalhe"], comp[2024]["situacao"]) == (
            0, 0.04, 2, "atingiu")
        # 30 × 31 = −1 na capa; 29,90 × 31,02 = −1,12 no detalhe (2 casas, não −1,1)
        assert (comp[2025]["diferenca_pp"], comp[2025]["diferenca_pp_detalhe"],
                comp[2025]["casas_decimais_detalhe"]) == (-1, -1.12, 2)
        return _estado_sem_proveniencia(db)

    for conteudo in (v2, v3):
        _aplicar(db, rede, conteudo)
    ordem_direta = conferir()
    _limpar(db)
    for conteudo in (v3, v2, a2024):                              # ordem inversa
        _aplicar(db, rede, conteudo)
    assert conferir() == ordem_direta


def _estado_sem_proveniencia(db) -> list[tuple]:
    db.expire_all()
    return sorted(
        (r.edicao, r.indicador, r.abrangencia, r.valor, r.casas_decimais, r.valor_detalhado,
         r.casas_decimais_detalhe, r.operador, r.motivo_ausencia)
        for r in db.execute(select(IndicadorReferencia)).scalars())


def test_desfazer_volta_exatamente_ao_estado_anterior(db, rede):
    _aplicar(db, rede, arq_mun_2025())
    estado_antes = _estado(db)
    b = _aplicar(db, rede, arq_mun_2024())          # altera detalhes e cria linhas
    assert b["contadores"]["novas"] == 2 and b["contadores"]["alteradas"] == 8
    assert _estado(db) != estado_antes
    pipeline.desfazer(db, rede, b["id"], usuario_id=None)
    db.commit()
    assert _estado(db) == estado_antes              # inclusive updated_at e proveniência
    assert db.get(ImportacaoIndicador, b["id"]).status == "desfeita"


def test_desfazer_pelo_id_recusa_so_quando_uma_posterior_usa_os_mesmos_numeros(db, rede):
    """E3: desfazer é pelo id (não só a última). Uma importação anterior pode ser
    desfeita se nenhuma posterior viu os números dela; se viu, recusa e diz qual
    desfazer antes. A última sempre pode."""
    a = _aplicar(db, rede, arq_mun_2025())          # município
    b = _aplicar(db, rede, arq_ufs_2025())          # UF e Brasil: outros números
    so_b = [ln for ln in _estado(db) if ln[2] != "municipio"]
    pipeline.desfazer(db, rede, a["id"], usuario_id=None)   # anterior, sem conflito
    db.commit()
    assert _estado(db) == so_b                      # exatamente como se "a" nunca viesse

    c = _aplicar(db, rede, arq_mun_2025())
    d = _aplicar(db, rede, arq_mun_2024())          # mexe nos detalhes dos números de "c"
    with pytest.raises(ImportacaoRecusada, match=rf"#{d['id']} .*desfaça antes a #{d['id']}"):
        pipeline.desfazer(db, rede, c["id"], usuario_id=None)
    db.rollback()
    pipeline.desfazer(db, rede, d["id"], usuario_id=None)
    pipeline.desfazer(db, rede, c["id"], usuario_id=None)
    pipeline.desfazer(db, rede, b["id"], usuario_id=None)
    db.commit()
    assert db.scalar(select(func.count(IndicadorReferencia.id))) == 0
    with pytest.raises(ImportacaoRecusada, match="APLICADA"):
        pipeline.desfazer(db, rede, a["id"], usuario_id=None)


def test_desfazer_aplicada_sem_plano_recusa_em_vez_de_marcar_desfeita(db, rede):
    """Aplicada SEM plano de desfazer (nem na coluna, nem no ``resumo`` do formato
    antigo): o desfazer recusa e a lista não oferece o botão — antes, ela virava
    'desfeita' sem restaurar nada (os números ficavam apontando para ela)."""
    a = _aplicar(db, rede, arq_mun_2025())
    imp = db.get(ImportacaoIndicador, a["id"])
    imp.desfazer = None
    db.commit()
    depois = _estado(db)
    assert [i["pode_desfazer"] for i in pipeline.listar(db, rede)] == [False]
    with pytest.raises(ImportacaoRecusada, match="plano de desfazer"):
        pipeline.desfazer(db, rede, a["id"], usuario_id=None)
    db.rollback()
    assert db.get(ImportacaoIndicador, a["id"]).status == "aplicada"
    assert _estado(db) == depois


def test_desfazer_recusa_se_o_estado_mudou(db, rede):
    a = _aplicar(db, rede, arq_mun_2025())
    linha = db.execute(select(IndicadorReferencia).where(
        IndicadorReferencia.indicador == "participacao")).scalar_one()
    linha.valor = 12.0                              # mexida fora da importação
    db.commit()
    with pytest.raises(ImportacaoRecusada, match="já não estão como ela os deixou"):
        pipeline.desfazer(db, rede, a["id"], usuario_id=None)
    db.rollback()
    assert db.scalar(select(func.count(IndicadorReferencia.id))) == 12   # nada apagado


def test_rede_sem_codigo_ibge_a_previa_pede_o_codigo_sem_adivinhar(db):
    sem = Rede(nome="Rede Sem Código", uf="SP", status="ativa")
    db.add(sem)
    db.commit()
    with pytest.raises(ImportacaoRecusada, match="código IBGE"):
        pipeline.previa(db, sem, arq_mun_2025(), "m.xlsx", usuario_id=None)
    saida = consulta.ica_da_rede(db, sem)
    assert saida["pendencia"] == "codigo_ibge" and saida["territorios"] == []


def test_ica_nunca_vira_resultado_de_escola(db, rede):
    db.add(Escola(nome="EM Sintética", ano_letivo_ativo=2026, rede_id=rede.id,
                  codigo_inep="35999999"))
    db.commit()
    _aplicar(db, rede, arq_mun_2025())
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 0


# --- API: permissões e leitura ----------------------------------------------------

def _cliente(db, email: str, **campos) -> TestClient:
    db.add(Usuario(nome=email, email=email, senha_hash=hash_senha("s3nh4ica1"), **campos))
    db.commit()
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", data={"username": email, "password": "s3nh4ica1"})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _upload(cliente, rede_id, rota, conteudo, nome="resultados_e_metas_municipios_2025_3.xlsx",
            **form):
    return cliente.post(f"/api/v1/redes/{rede_id}/indicadores/ica/{rota}",
                        files={"arquivo": (nome, conteudo)}, data=form)


def _importar_api(cliente, rede_id, conteudo, nome="arquivo.xlsx"):
    p = _upload(cliente, rede_id, "previa", conteudo, nome)
    assert p.status_code == 200, p.text
    a = _upload(cliente, rede_id, "aplicar", conteudo, nome, previa_id=str(p.json()["id"]))
    assert a.status_code == 200, a.text
    return p.json(), a.json()


def test_permissoes_admin_importa_secretaria_le_escola_403(db, escola_completa, cliente_global,
                                                           rede):
    escola = escola_completa["escola"]
    secretaria = _cliente(db, "sec@ica.gov", cargo="coordenador", rede_id=rede.id)
    coordenador = _cliente(db, "coord@ica.escola", cargo="coordenador", escola_id=escola.id)
    professor = _cliente(db, "prof@ica.escola", cargo="professor", escola_id=escola.id)
    outra_rede = Rede(nome="Outra Rede", codigo_ibge=OUTRO, status="ativa")
    db.add(outra_rede)
    db.commit()
    secretaria_outra = _cliente(db, "sec@outra.gov", cargo="coordenador", rede_id=outra_rede.id)
    url = f"/api/v1/redes/{rede.id}/indicadores/ica"

    # Importar e desfazer: só o admin global.
    for quem in (secretaria, coordenador, professor):
        assert _upload(quem, rede.id, "previa", arq_mun_2025()).status_code == 403
        assert quem.get(f"/api/v1/redes/{rede.id}/indicadores/importacoes").status_code == 403
    _, aplicada = _importar_api(cliente_global, rede.id, arq_mun_2025())
    for quem in (secretaria, coordenador, professor):
        assert quem.post(f"/api/v1/redes/{rede.id}/indicadores/importacoes/"
                         f"{aplicada['id']}/desfazer").status_code == 403

    # Ler: a Secretaria da PRÓPRIA rede e o admin global; escola e outra rede, 403.
    assert secretaria.get(url).status_code == 200
    assert cliente_global.get(url).status_code == 200
    assert coordenador.get(url).status_code == 403
    assert professor.get(url).status_code == 403
    assert secretaria_outra.get(url).status_code == 403
    assert cliente_global.get("/api/v1/redes/999999/indicadores/ica").status_code == 404


def test_api_ica_serie_metas_nivel_participacao_sp_brasil_com_fonte(db, escola_completa,
                                                                    cliente_global, rede):
    _importar_api(cliente_global, rede.id, arq_mun_2025(),
                  "resultados_e_metas_municipios_2025_3.xlsx")
    _importar_api(cliente_global, rede.id, arq_mun_2024(), "resultados_e_metas_municipios_2024.xlsx")
    _importar_api(cliente_global, rede.id, arq_ufs_2025(), "resultados_e_metas_ufs_2025_v2.xlsx")
    secretaria = _cliente(db, "sec@ica.gov", cargo="coordenador", rede_id=rede.id)
    d = secretaria.get(f"/api/v1/redes/{rede.id}/indicadores/ica").json()

    assert d["tem_dados"] and d["codigo_ibge"] == MUN and d["pendencia"] is None
    assert d["indicador"]["orgao"] == "INEP" and "REDE" in d["aviso_rede"]
    mun, uf, br = d["territorios"]
    assert (mun["abrangencia"], mun["nome"], mun["rede_ensino"]) == (
        "municipio", NOME_MUN, "municipal")
    assert (uf["nome"], uf["rede_ensino"], br["nome"]) == ("São Paulo", "publica", "Brasil")
    assert [(r["edicao"], r["valor"]) for r in mun["resultados"]] == [
        (2023, 26), (2024, 22), (2025, 30)]
    assert mun["resultados"][1]["detalhe"]["valor"] == 21.84
    assert mun["resultados"][1]["detalhe"]["fonte"]["arquivo_nome"] == (
        "resultados_e_metas_municipios_2024.xlsx")
    assert [m["edicao"] for m in mun["metas"]] == list(range(2024, 2031))
    assert [(n["edicao"], n["valor"]) for n in mun["nivel"]] == [(2024, 1), (2025, 1)]
    assert [(p["edicao"], p["valor"]) for p in mun["participacao"]] == [(2024, 72.31), (2025, 73)]
    # cada número com a fonte: arquivo, edição do arquivo, data interna, importação
    fonte = mun["resultados"][2]["fonte"]
    assert fonte["arquivo_nome"] == "resultados_e_metas_municipios_2025_3.xlsx"
    assert fonte["edicao_arquivo"] == 2025 and fonte["arquivo_data"] == DATA_MUN_2025.isoformat()
    assert fonte["importado_em"] and fonte["fonte_nome"].startswith("INEP")
    # capa: 30 × meta 32 (−2 p.p.), na mesma precisão; 2024 também no detalhe
    destaque = mun["destaque"]
    assert destaque["resultado"]["valor"] == 30 and destaque["meta"]["valor"] == 32
    assert destaque["comparacao"]["diferenca_pp"] == -2
    assert destaque["comparacao"]["situacao"] == "nao_atingiu"
    c2024 = next(c for c in mun["comparacoes"] if c["edicao"] == 2024)
    assert (c2024["diferenca_pp"], c2024["diferenca_pp_detalhe"]) == (-3, -3.52)
    # SP 34 × 33, atingiu; Brasil 23 × 23 é empate na precisão divulgada (inconclusivo)
    assert uf["destaque"]["comparacao"]["situacao"] == "atingiu"
    assert br["destaque"]["comparacao"]["situacao"] == "inconclusivo"
    assert br["metas"][-1]["operador"] == ">"
    assert {f["arquivo_nome"] for f in d["fontes"]} == {
        "resultados_e_metas_municipios_2025_3.xlsx", "resultados_e_metas_municipios_2024.xlsx",
        "resultados_e_metas_ufs_2025_v2.xlsx"}


def test_api_sem_dado_vem_vazio_nao_zero(db, escola_completa, cliente_global, rede):
    d = cliente_global.get(f"/api/v1/redes/{rede.id}/indicadores/ica").json()
    assert d["tem_dados"] is False and d["fontes"] == []
    assert [t["abrangencia"] for t in d["territorios"]] == ["municipio", "uf", "brasil"]
    assert all(t["resultados"] == [] and t["destaque"] is None for t in d["territorios"])


def test_api_fluxo_previa_aplicar_listar_desfazer_e_auditoria(db, escola_completa,
                                                              cliente_global, rede):
    previa = _upload(cliente_global, rede.id, "previa", arq_mun_2025(),
                     url_origem="https://download.inep.gov.br/exemplo.xlsx",
                     last_modified_origem="Wed, 15 Jul 2026 10:30:00 GMT",
                     coletado_em="2026-10-16")
    assert previa.status_code == 200, previa.text
    assert db.scalar(select(func.count(IndicadorReferencia.id))) == 0
    # outro arquivo na aplicação: 400, nada gravado
    errado = _upload(cliente_global, rede.id, "aplicar", arq_mun_2024(),
                     previa_id=str(previa.json()["id"]))
    assert errado.status_code == 400 and "sha256" in errado.json()["detail"]
    ok = _upload(cliente_global, rede.id, "aplicar", arq_mun_2025(),
                 previa_id=str(previa.json()["id"]))
    assert ok.status_code == 200 and ok.json()["status"] == "aplicada"
    assert db.scalar(select(func.count(IndicadorReferencia.id))) == 12
    lista = cliente_global.get(f"/api/v1/redes/{rede.id}/indicadores/importacoes").json()
    assert lista[0]["id"] == ok.json()["id"] and lista[0]["pode_desfazer"] is True
    assert lista[0]["url_origem"] == "https://download.inep.gov.br/exemplo.xlsx"
    imp = db.get(ImportacaoIndicador, ok.json()["id"])
    assert imp.coletado_em == datetime(2026, 10, 16)
    assert imp.last_modified_origem == "Wed, 15 Jul 2026 10:30:00 GMT"
    desf = cliente_global.post(f"/api/v1/redes/{rede.id}/indicadores/importacoes/"
                               f"{ok.json()['id']}/desfazer")
    assert desf.status_code == 200 and desf.json()["status"] == "desfeita"
    db.expire_all()
    assert db.scalar(select(func.count(IndicadorReferencia.id))) == 0
    acoes = {a for (a,) in db.execute(select(LogAuditoria.acao))}
    assert {"indicador.importado", "indicador.desfeito"} <= acoes


def test_api_rede_sem_codigo_ibge_400_que_pede_o_codigo(db, escola_completa, cliente_global):
    sem = Rede(nome="Rede Sem Código", status="ativa")
    db.add(sem)
    db.commit()
    r = _upload(cliente_global, sem.id, "previa", arq_mun_2025())
    assert r.status_code == 400 and "código IBGE" in r.json()["detail"]
    assert db.scalar(select(func.count(ImportacaoIndicador.id))) == 0


def test_ica_fora_da_importacao_por_escola(db, escola_completa, cliente, cliente_global):
    """O ICA é da rede: não aparece no seletor da importação por escola e é
    recusado no upload por escola e no robô."""
    chaves = {a["chave"] for a in cliente.get("/api/v1/avaliacoes").json()}
    assert "ica" not in chaves and "crianca_alfabetizada" in chaves
    # (desde a E9 só o admin global importa por escola — decisão D4)
    r = cliente_global.post("/api/v1/avaliacoes/importar",
                            files={"arquivo": ("x.csv", b"CO;V\n35999999;30")},
                            data={"avaliacao": "ica", "edicao": "2025", "indicador": "x",
                                  "unidade": "percentual", "linha_dados": "1",
                                  "col_inep": "0", "col_valor": "1"})
    assert r.status_code == 400 and "da rede" in r.json()["detail"]
    f = cliente_global.post("/api/v1/avaliacoes/fontes", json={
        "avaliacao": "ica", "nome": "x", "url": "https://download.inep.gov.br/x.xlsx",
        "edicao": 2025, "indicador": "x", "unidade": "percentual",
        "mapeamento": {"linha_dados": 1}})
    assert f.status_code == 400
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 0


# --- O mesmo fluxo num PostgreSQL de verdade (JSON, float e timestamp do desfazer) --

from tests.test_migracoes_postgres import engine_postgres  # noqa: E402,F401 — fixture do PG de teste


@pytest.mark.postgres
def test_pipeline_no_postgres_aplica_reaplica_e_desfaz_exato(engine_postgres):
    from sqlalchemy.orm import sessionmaker

    from app.core.migracoes import aplicar_migracoes

    aplicar_migracoes(engine_postgres)
    db = sessionmaker(bind=engine_postgres)()
    try:
        rede_pg = Rede(nome="Rede Sintética PG", uf="SP", codigo_ibge=MUN, status="ativa")
        db.add(rede_pg)
        db.commit()
        _aplicar(db, rede_pg, arq_mun_2025())
        antes = _estado(db)
        b = _aplicar(db, rede_pg, arq_mun_2024())
        de_novo = _aplicar(db, rede_pg, arq_mun_2024())
        assert de_novo["contadores"]["iguais"] == 11 and de_novo["contadores"]["novas"] == 0
        assert _valores(db)[("municipio", "percentual_alfabetizado", 2024)] == (22, 21.84)
        pipeline.desfazer(db, rede_pg, de_novo["id"], usuario_id=None)
        pipeline.desfazer(db, rede_pg, b["id"], usuario_id=None)
        db.commit()
        assert _estado(db) == antes
    finally:
        db.close()
