"""Relatório em TEXTO (.txt/.csv/.tsv) e CSV das avaliações salvos fora do UTF-8.

Antes: o upload de relatório decodificava todo arquivo de texto com
``decode("utf-8", errors="replace")`` e o leitor das avaliações com
``decode("utf-8-sig", errors="replace")``. O "CSV" do Excel em português (Windows-1252)
virava "Jo�o" na prévia — a criança cadastrada ia para a revisão e a nova nascia com o
nome estragado — e o "Texto Unicode" (UTF-16) nem era reconhecido. No CSV das
avaliações, o componente gravado virava "Matem�tica".

Agora uma regra só (``services/codificacao.decodificar_texto``): BOM manda, senão
UTF-8 estrito, senão Windows-1252. E o "�" que ainda sobrar no nome (byte que nenhuma
das duas lê) marca a linha com erro na prévia e a ignora no /confirmar: nenhuma ficha
nasce com ele. Tudo fictício (a escola do conftest tem "João Pedro Barbosa").
"""
import codecs

import pytest

from app.models import Aluno, ResultadoAvaliacao
from app.services import avaliacoes
from app.services.codificacao import decodificar_texto

TEXTO_MATIFIC = (
    "Relatório Matific — Turma 3º Ano A\n"
    "Nome do aluno\tAtividades finalizadas\tPontuação média\tEstrelas\n"
    "Ana Beatriz Souza\t42\t85,5\t120\n"
    "João Pedro Barbosa\t10\t70\t35\n"
    "Lúcia Fictícia Conceição\t7\t60\t12\n"
)
NOMES = ["Ana Beatriz Souza", "João Pedro Barbosa", "Lúcia Fictícia Conceição"]

CODIFICACOES = {
    "cp1252": lambda t: t.encode("cp1252"),
    "latin-1": lambda t: t.replace("—", "-").encode("latin-1"),
    "utf-16 (Texto Unicode do Excel)": lambda t: t.encode("utf-16"),
    "utf-16-be com BOM": lambda t: codecs.BOM_UTF16_BE + t.encode("utf-16-be"),
    "utf-8 com BOM": lambda t: t.encode("utf-8-sig"),
    "utf-8": lambda t: t.encode("utf-8"),
}


def _analisar(cliente, escola_id, conteudo: bytes, nome: str = "relatorio.txt",
              ct: str = "text/plain"):
    r = cliente.post(f"/api/v1/escolas/{escola_id}/importacoes/analisar",
                     files={"arquivo": (nome, conteudo, ct)})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("codificacao", list(CODIFICACOES))
def test_decodificar_texto_le_as_codificacoes_do_excel(codificacao):
    esperado = TEXTO_MATIFIC if codificacao != "latin-1" else TEXTO_MATIFIC.replace("—", "-")
    assert decodificar_texto(CODIFICACOES[codificacao](TEXTO_MATIFIC)) == esperado


def test_decodificar_texto_nunca_levanta_e_marca_o_byte_ilegivel():
    # 0x81 não existe no Windows-1252 nem forma UTF-8: vira "�", sem exceção.
    assert decodificar_texto(b"Jo\x81o") == "Jo�o"
    assert decodificar_texto(b"") == ""


@pytest.mark.parametrize("codificacao", list(CODIFICACOES))
def test_previa_le_os_nomes_em_qualquer_codificacao_do_excel(cliente, escola_completa,
                                                            codificacao):
    corpo = _analisar(cliente, escola_completa["escola"].id,
                      CODIFICACOES[codificacao](TEXTO_MATIFIC))
    nomes = [linha["nome"] for linha in corpo["linhas"]]
    assert corpo["total_linhas"] == 3, corpo["erros_gerais"]
    assert nomes == NOMES
    status = {linha["nome"]: linha["correspondencia"]["status"] for linha in corpo["linhas"]}
    assert status["João Pedro Barbosa"] == "exato"     # a cadastrada casa, não vai à revisão
    assert status["Lúcia Fictícia Conceição"] == "nao_encontrado"


def _confirmar(cliente, escola_completa, corpo: dict, linhas: list[dict] | None = None):
    turma_id = escola_completa["turma"].id
    if linhas is None:
        linhas = []
        for linha in corpo["linhas"]:
            c = linha["correspondencia"] or {}
            casou = c.get("status") in ("exato", "vinculado")
            linhas.append({"nome": linha["nome"], "dados": linha["dados"],
                           "aluno_id": c.get("aluno_id") if casou else None,
                           "criar_em_turma_id": None if casou else turma_id})
    return cliente.post(
        f"/api/v1/escolas/{escola_completa['escola'].id}/importacoes/confirmar",
        json={"plataforma": corpo["plataforma"], "formato": corpo["formato"],
              "tipo": "texto", "linhas": linhas})


def test_confirmar_relatorio_em_cp1252_cria_a_ficha_com_o_nome_certo(cliente, db,
                                                                    escola_completa):
    corpo = _analisar(cliente, escola_completa["escola"].id,
                      TEXTO_MATIFIC.encode("cp1252"), "relatorio_matific.csv", "text/csv")
    r = _confirmar(cliente, escola_completa, corpo)
    assert r.status_code == 200, r.text
    nomes = sorted(a.nome for a in db.query(Aluno).filter(
        Aluno.escola_id == escola_completa["escola"].id))
    assert nomes == sorted([*NOMES, "Sofia Almeida Duarte"])


def test_previa_marca_com_erro_o_nome_que_ainda_tem_letra_ilegivel(cliente,
                                                                  escola_completa):
    """Byte que nem o UTF-8 nem o Windows-1252 leem (0x81): a linha sai com erro (a
    tela não a envia) em vez de oferecer criar a ficha com "�"."""
    bruto = TEXTO_MATIFIC.encode("cp1252").replace(b"L\xfacia", b"L\x81cia")
    corpo = _analisar(cliente, escola_completa["escola"].id, bruto)
    por_nome = {linha["nome"]: linha for linha in corpo["linhas"]}
    ilegivel = por_nome["L�cia Fictícia Conceição"]
    assert any("ilegível" in erro for erro in ilegivel["erros"]), ilegivel["erros"]
    assert not por_nome["João Pedro Barbosa"]["erros"]


def test_confirmar_ignora_a_linha_com_letra_ilegivel_no_nome(cliente, db, escola_completa):
    """A mesma regra no /confirmar (quem chama a API direto): a linha é ignorada com
    aviso e nenhuma ficha nasce com "�"."""
    corpo = _analisar(cliente, escola_completa["escola"].id, TEXTO_MATIFIC.encode("utf-8"))
    linhas = [{"nome": "L�cia Fict�cia", "dados": corpo["linhas"][2]["dados"],
               "aluno_id": None, "criar_em_turma_id": escola_completa["turma"].id}]
    r = _confirmar(cliente, escola_completa, corpo, linhas)
    assert r.status_code == 200, r.text
    assert any("ilegível" in aviso for aviso in r.json()["avisos"]), r.json()["avisos"]
    nomes = [a.nome for a in db.query(Aluno).filter(
        Aluno.escola_id == escola_completa["escola"].id)]
    assert not any("�" in nome for nome in nomes), nomes


@pytest.mark.parametrize("codificacao", ["cp1252", "utf-16 (Texto Unicode do Excel)",
                                         "utf-8 com BOM"])
def test_csv_de_avaliacao_grava_o_componente_com_acento(db, escola_completa, codificacao):
    escola = escola_completa["escola"]
    escola.codigo_inep = "35000001"
    db.commit()
    csv_txt = "INEP;Componente;Nota\n35000001;Matemática;210,5\n35000001;Português;198,0\n"
    avaliacoes.importar_resultados(
        db, CODIFICACOES[codificacao](csv_txt), "saresp_preparado.csv",
        avaliacao_chave="saresp", edicao=2025, indicador="proficiencia",
        unidade="escala_saresp", linha_dados=1, col_inep=0, col_valor=2,
        col_componente=1, etapa_fixa="5_ano")
    db.commit()
    assert sorted(r.componente for r in db.query(ResultadoAvaliacao)) == [
        "Matemática", "Português"]


def test_grade_das_avaliacoes_em_cp1252_le_o_municipio_com_acento():
    """O /casar-inep lê pelo mesmo leitor (``_iterar_grade``)."""
    csv_txt = "UF;Município;INEP;Escola\nSP;São José dos Campos;35000001;EMEF Fictícia\n"
    grade = avaliacoes.analisar_planilha(csv_txt.encode("cp1252"), "ideb_escolas.csv")
    assert grade["primeiras_linhas"][1] == ["SP", "São José dos Campos", "35000001",
                                           "EMEF Fictícia"]
