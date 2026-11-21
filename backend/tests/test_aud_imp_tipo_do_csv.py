"""Relatório .csv/.txt enviado pelo navegador do Windows com o Excel instalado.

Nesse computador o navegador manda o .csv com o tipo ``application/vnd.ms-excel`` (é o
que o Windows registra para a extensão). ``importacao.detectar_tipo`` tratava esse
tipo como PLANILHA antes de olhar a extensão de texto: o .csv ia para o leitor de
.xlsx e a prévia respondia 400 ("Não foi possível abrir a planilha. Confirme que é um
arquivo Excel (.xlsx) válido.") — o caminho do "CSV do Excel" nem chegava ao leitor
de texto. Agora a assinatura do conteúdo manda (PDF, zip do .xlsx, OLE2 do .xls); sem
ela, a extensão de texto vence o tipo que o navegador adivinha. Tudo fictício.
"""
import pytest

from app.services.importacao import detectar_tipo

CT_EXCEL_DO_WINDOWS = "application/vnd.ms-excel"
TEXTO = ("Relatório Matific — Turma 3º Ano A\n"
         "Nome do aluno\tAtividades finalizadas\tPontuação média\tEstrelas\n"
         "Ana Beatriz Souza\t42\t85,5\t120\n"
         "João Pedro Barbosa\t10\t70\t35\n")


@pytest.mark.parametrize("nome", ["relatorio.csv", "relatorio.txt", "relatorio.tsv",
                                  "RELATORIO.CSV"])
def test_texto_com_tipo_do_excel_e_texto(nome):
    assert detectar_tipo(TEXTO.encode("cp1252"), nome, CT_EXCEL_DO_WINDOWS) == "texto"


def test_a_assinatura_do_conteudo_continua_mandando():
    # .xlsx/.xls renomeado para .csv continua planilha; PDF continua PDF.
    assert detectar_tipo(b"PK\x03\x04resto", "relatorio.csv", CT_EXCEL_DO_WINDOWS) == "xlsx"
    assert detectar_tipo(b"\xd0\xcf\x11\xe0resto", "relatorio.txt", "") == "xlsx"
    assert detectar_tipo(b"%PDF-1.7\n", "relatorio.csv", "") == "pdf"
    # Sem extensão de texto, o tipo do navegador ainda vale.
    assert detectar_tipo(b"qualquer", "relatorio", CT_EXCEL_DO_WINDOWS) == "xlsx"
    assert detectar_tipo(b"qualquer", "relatorio.xls", "") == "xlsx"


def test_previa_do_csv_enviado_pelo_windows_le_os_nomes(cliente, escola_completa):
    r = cliente.post(
        f"/api/v1/escolas/{escola_completa['escola'].id}/importacoes/analisar",
        files={"arquivo": ("relatorio.csv", TEXTO.encode("cp1252"), CT_EXCEL_DO_WINDOWS)})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["tipo"] == "texto"
    assert [linha["nome"] for linha in corpo["linhas"]] == ["Ana Beatriz Souza",
                                                            "João Pedro Barbosa"]
