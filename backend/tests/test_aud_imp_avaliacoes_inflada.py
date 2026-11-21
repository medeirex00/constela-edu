"""Planilha inflada e dimensão declarada enorme nos leitores das AVALIAÇÕES EXTERNAS
(``avaliacoes._iterar_grade``: /avaliacoes/analisar, /importar, /importar-preset,
/redes/{id}/casar-inep e a coleta "coletar agora") e do ICA (``ica._abrir``).

Antes: os dois abriam o .xlsx com ``load_workbook(read_only=True)`` sem a guarda única
(``planilhas.exigir_xlsx_contido``) e liam as linhas sem teto de colunas: 41 KB
enviados alocavam 80 MB (a sharedStrings inteira), e uma dimensão A1:XFD3000 de
2 KB devolvia linhas de 16.384 colunas (1,8 s; até A1:XFD1048576, minutos).

Agora a guarda roda ANTES do openpyxl (teto calibrado para o arquivo grande do INEP
nas avaliações; o padrão no ICA), a tabela de textos tem teto próprio, e a leitura
tem teto de colunas e de linhas. Tudo fictício e em memória.
"""
import io
import os
import time
import tracemalloc
import zipfile

import pytest

from app.models import ResultadoAvaliacao
from app.services import avaliacoes, planilhas
from app.services.avaliacoes import ImportacaoRecusada
from app.services.indicadores import ica
from tests.test_planilha_inflada import (
    _PARTES,
    MB,
    TETO_S,
    _celula,
    _dimensao_enorme,
    _xlsx_celula_gigante,
    _xlsx_folhas,
)


@pytest.fixture(scope="module")
def bomba() -> bytes:
    conteudo = _xlsx_celula_gigante(40 * MB)          # < 100 KB enviados
    assert len(conteudo) < 100_000
    return conteudo


def _no_zip(nome: str, conteudo: bytes) -> bytes:
    """Como o INEP publica: o .xlsx dentro de um .zip."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        z.writestr(nome, conteudo)
    return buf.getvalue()


def _xlsx_textos_sem_repeticao(tamanho: int) -> bytes:
    """Um .xlsx com UMA célula de ``tamanho`` caracteres que NÃO se repetem (razão de
    compressão de planilha comum, ~2x): passa pela razão, não pelo tamanho."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for nome, texto in _PARTES.items():
            z.writestr(nome, texto)
        z.writestr("xl/sharedStrings.xml",
                   b'<?xml version="1.0" encoding="UTF-8"?><sst xmlns="http://schemas.'
                   b'openxmlformats.org/spreadsheetml/2006/main" count="1" uniqueCount="1">'
                   b"<si><t>" + os.urandom(tamanho // 2).hex().encode() + b"</t></si></sst>")
    return buf.getvalue()


def _medir(funcao):
    tracemalloc.start()
    t0 = time.monotonic()
    try:
        funcao()
    finally:
        dt = time.monotonic() - t0
        _, pico = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    return pico, dt


@pytest.mark.parametrize("nome", ["resultado_ideb.xlsx", "divulgacao_escolas.zip"])
def test_avaliacoes_recusam_a_bomba_antes_de_abrir(bomba, nome):
    conteudo = _no_zip("divulgacao_escolas.xlsx", bomba) if nome.endswith(".zip") else bomba
    erro = []

    def analisar():
        with pytest.raises(ImportacaoRecusada) as exc:
            avaliacoes.analisar_planilha(conteudo, nome)
        erro.append(str(exc.value))

    pico, dt = _medir(analisar)
    assert pico < 10 * MB, f"{pico / MB:.0f} MB alocados"
    assert dt < TETO_S
    assert "Nada foi gravado" in erro[0]


def test_importar_resultados_recusa_a_bomba_sem_gravar(db, escola_completa, bomba):
    escola_completa["escola"].codigo_inep = "35000001"
    db.commit()
    with pytest.raises(ImportacaoRecusada):
        avaliacoes.importar_resultados(
            db, bomba, "resultado.xlsx", avaliacao_chave="ideb", edicao=2023,
            indicador="ideb", unidade="indice", linha_dados=1, col_inep=0, col_valor=1,
            etapa_fixa="anos_iniciais")
    assert db.query(ResultadoAvaliacao).count() == 0


def test_rota_importar_recusa_a_bomba_com_400(cliente_global, bomba):
    r = cliente_global.post(
        "/api/v1/avaliacoes/importar",
        data={"avaliacao": "ideb", "edicao": 2023, "indicador": "ideb", "unidade": "indice",
              "linha_dados": 1, "col_inep": 0, "col_valor": 1, "etapa_fixa": "anos_iniciais"},
        files={"arquivo": ("resultado.xlsx", bomba, "application/octet-stream")})
    assert r.status_code == 400, r.text
    assert "Nada foi gravado" in r.json()["detail"]


def test_coleta_registra_a_recusa_como_erro(db, bomba):
    """O "coletar agora" (URL de terceiro) com a bomba: erro registrado, nada gravado."""
    from tests.test_avaliacoes_fontes import _fonte

    fonte = _fonte(db)
    fonte.url = "https://download.inep.gov.br/ideb/resultado.xlsx"   # o tipo vem do nome
    saida = avaliacoes.coletar_fonte(db, fonte, baixador=lambda _url: bomba)
    db.commit()
    assert saida["status"] == "erro"
    assert fonte.ultimo_erro.startswith("ImportacaoRecusada")
    assert db.query(ResultadoAvaliacao).count() == 0


def test_tabela_de_textos_acima_do_teto_e_recusada_mesmo_com_razao_normal(monkeypatch):
    """O teto do total das avaliações é alto (o .xlsx do INEP é grande); a tabela de
    textos — que o openpyxl carrega INTEIRA — tem teto próprio."""
    monkeypatch.setattr(avaliacoes, "_XLSX_MAX_TEXTOS", 1 * MB)
    conteudo = _xlsx_textos_sem_repeticao(2 * MB)
    planilhas.exigir_xlsx_contido(conteudo)          # a guarda única deixa passar
    with pytest.raises(ImportacaoRecusada, match="tabela de textos"):
        avaliacoes.analisar_planilha(conteudo, "resultado.xlsx")


def test_teto_do_total_tem_mensagem_das_avaliacoes(monkeypatch):
    monkeypatch.setattr(avaliacoes, "_XLSX_MAX_DESCOMPRIMIDO", 1 * MB)
    conteudo = _xlsx_celula_gigante(2 * MB)
    with pytest.raises(ImportacaoRecusada) as exc:
        avaliacoes.analisar_planilha(conteudo, "resultado.xlsx")
    assert "Lista Piloto" not in str(exc.value) and "Nada foi gravado" in str(exc.value)


def test_dimensao_declarada_nao_alarga_a_leitura_das_avaliacoes():
    arquivo = _dimensao_enorme(3000)
    t0 = time.monotonic()
    resultado = avaliacoes.analisar_planilha(arquivo, "resultado.xlsx")
    dt = time.monotonic() - t0
    assert resultado["n_colunas"] <= planilhas.MAX_COLUNAS_LIDAS, resultado["n_colunas"]
    assert resultado["primeiras_linhas"][0][0] == "1"
    assert dt < TETO_S


def test_dimensao_e_linha_alem_do_excel_terminam_rapido():
    """A1:XFD1048576 e uma linha r="50000000" (além do que o Excel aceita): a leitura
    para no limite do Excel, sem percorrer 16.384 colunas nem 50 milhões de linhas."""
    for arquivo in (_dimensao_enorme(1_048_576),
                    _xlsx_folhas([(None, '<row r="50000000">'
                                   + _celula("A50000000", 7) + "</row>")])):
        t0 = time.monotonic()
        linhas = list(avaliacoes._iterar_grade(arquivo, "resultado.xlsx"))
        assert time.monotonic() - t0 < TETO_S
        assert all(len(linha) <= planilhas.MAX_COLUNAS_LIDAS for linha in linhas)


def test_celula_alem_do_teto_de_colunas_fica_de_fora():
    """Sem dimensão declarada: a linha vai até a última célula preenchida, como antes,
    mas a célula além do teto de colunas não a alarga até a coluna 16.384."""
    linha = "".join(_celula(ref, v) for ref, v in (("A1", "INEP"), ("B1", "VALOR"),
                                                   ("XFD1", "isca")))
    resultado = avaliacoes.analisar_planilha(_xlsx_folhas([(None, f'<row r="1">{linha}</row>')]),
                                             "resultado.xlsx")
    assert resultado["primeiras_linhas"] == [["INEP", "VALOR"]]


def test_planilha_legitima_das_avaliacoes_continua_igual():
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Pré-âmbulo"])
    ws.append(["INEP", "Componente", "Nota", None])
    ws.append(["35000001", "Matemática", 210.5, None])
    buf = io.BytesIO()
    wb.save(buf)
    resultado = avaliacoes.analisar_planilha(buf.getvalue(), "saresp.xlsx")
    assert resultado["linhas_lidas"] == 3
    # A largura declarada (4 colunas) continua a da grade, como antes.
    assert resultado["n_colunas"] == 4
    assert resultado["primeiras_linhas"][2] == ["35000001", "Matemática", "210.5", ""]


def test_ica_recusa_a_bomba_antes_de_abrir(bomba):
    def abrir():
        with pytest.raises(ImportacaoRecusada, match="Nada foi gravado"):
            ica._abrir(bomba, "resultados_e_metas_municipios.xlsx")

    pico, dt = _medir(abrir)
    assert pico < 10 * MB, f"{pico / MB:.0f} MB alocados"
    assert dt < TETO_S


def test_ica_dimensao_declarada_nao_alarga_a_leitura():
    """A linha de códigos do ICA com dimensão A1:XFD20000: a leitura não completa cada
    linha até a coluna 16.384 (célula a célula, com o formato) — antes, ~1 ms por
    linha, vazia ou não."""
    from tests.test_indicadores_ica import MUN, _codigos_municipios

    codigos = _codigos_municipios("2025")
    letras = [chr(ord("A") + i) if i < 26 else "A" + chr(ord("A") + i - 26)
              for i in range(len(codigos))]
    cabecalho = "".join(_celula(f"{c}2", v) for c, v in zip(letras, codigos))
    miolo = (f'<row r="1">{_celula("A1", "Resultados")}</row><row r="2">{cabecalho}</row>'
             f'<row r="20000">{_celula("A20000", "x")}</row>')
    arquivo = _xlsx_folhas([("A1:XFD20000", miolo)])
    t0 = time.monotonic()
    with pytest.raises(ImportacaoRecusada):
        ica.ler_planilha_ica(arquivo, "resultados_e_metas_municipios.xlsx", codigo_ibge=MUN)
    assert time.monotonic() - t0 < TETO_S
