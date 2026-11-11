"""Exportação Excel: um caractere de controle num texto (nome colado de um PDF, vindo
da plataforma...) não derruba o arquivo da escola inteira.

O openpyxl levanta ``IllegalCharacterError`` para os caracteres de controle C0
(\\x00-\\x08, \\x0b, \\x0c, \\x0e-\\x1f) e ``gerar_xlsx`` é o único gerador de Excel: um
"Ana\\x02 Beatriz" dava 500 em toda exportação .xlsx (ranking, alunos, livros) até
alguém achar o nome. O CSV e o PDF já funcionavam. Achado API_SEGURANCA-4 (só a
exportação; a validação da entrada é de outra frente). Dados fictícios.
"""
import io

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.main import app
from app.models import Livro, Nota
from app.services import relatorios

API = "/api/v1"


def _valores(conteudo: bytes) -> list:
    ws = load_workbook(io.BytesIO(conteudo)).active
    return [c.value for linha in ws.iter_rows() for c in linha if c.value is not None]


@pytest.mark.parametrize("tipo", ["alunos", "ranking", "livros"])
def test_exportacao_xlsx_com_caractere_de_controle_nao_e_500(cliente, db, escola_completa,
                                                            tipo):
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    aluno.nome = "Ana\x02 Beatriz\x1f Souza"
    escola_completa["turma"].nome = "3º Ano A\x0b"
    db.add(Nota(escola_id=escola.id, aluno_id=aluno.id, ano_letivo=2026,
                nota_matific=50.0, nota_elefante=50.0, nota_geral=50.0, posicao=1,
                aferido_matematica=True, aferido_leitura=True))
    db.add(Livro(escola_id=escola.id, titulo="O Menino\x00 do Dedo Verde",
                 autor="Autor\x08 Ficticio", nivel_codigo="AA"))
    db.commit()
    c = TestClient(app, raise_server_exceptions=False)
    c.headers.update(cliente.headers)
    r = c.get(f"{API}/escolas/{escola.id}/relatorios/{tipo}", params={"formato": "xlsx"})
    assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
    valores = [v for v in _valores(r.content) if isinstance(v, str)]
    assert not any(ch in v for v in valores for ch in "\x00\x02\x08\x0b\x1f")
    esperado = {"alunos": "Ana Beatriz Souza", "ranking": "Ana Beatriz Souza",
                "livros": "O Menino do Dedo Verde"}[tipo]
    assert esperado in valores


def test_texto_que_vira_formula_depois_da_limpeza_continua_texto():
    """O caractere de controle sai ANTES da proteção contra fórmula: um
    "\\x02=HYPERLINK(...)" não vira fórmula viva."""
    conteudo = relatorios.gerar_xlsx("Lista", "Escola\x02 Ficticia", "#1B2A4A",
                                     ["Aluno"], [["\x02=HYPERLINK(\"x\",\"y\")"]])
    ws = load_workbook(io.BytesIO(conteudo)).active
    assert ws.cell(row=1, column=1).value == "Escola Ficticia — Lista"
    celula = ws.cell(row=3, column=1)
    assert celula.value == "=HYPERLINK(\"x\",\"y\")"
    assert celula.data_type == "s"


def test_texto_sem_caractere_de_controle_nao_muda():
    """Quebra de linha, tabulação e acentos são legais no Excel e ficam."""
    conteudo = relatorios.gerar_xlsx("Lista", "Escola", "#1B2A4A", ["Aluno", "Obs"],
                                     [["João Ácido", "linha 1\nlinha 2\tfim"]])
    assert _valores(conteudo)[-2:] == ["João Ácido", "linha 1\nlinha 2\tfim"]
