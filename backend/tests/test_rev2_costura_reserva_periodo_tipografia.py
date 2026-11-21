"""REV2-COSTURA-4: a reserva do Relatório por Período escreve o nome da criança como ele é.

e37200c0 levou os PDFs de reserva (fpdf2) para o cp1252 (``services.texto_pdf``): o
apóstrofo tipográfico (Sant’Anna), as aspas curvas e o travessão existem nas fontes
nativas. A reserva do Relatório por Período ainda passava TODA célula — o nome da
criança, o da turma e o da escola inclusive — por ``_sem_tipografia``, que trocava
’ por ', “” por "" e — por -, porque o latin-1 não os tinha. Agora a normalização
só troca o que o cp1252 não tem (→, ≈, ―), que viraria "?". Dados fictícios.
"""
from app.services import relatorios_periodo_pdf as pdf
from tests.test_relatorios_periodo_pdf import (  # noqa: F401  (fixtures)
    _dados, _texto, cenario, sem_chromium)


def test_tipografia_do_cp1252_passa_intacta():
    texto = "Ana Sant’Anna — “Livros novos” … • D’Oeste – fim"
    assert pdf._sem_tipografia(texto) == texto


def test_o_que_o_cp1252_nao_tem_vira_o_equivalente_e_nao_interrogacao():
    assert pdf._sem_tipografia("a → b ≈ c ― d") == "a -> b ~ c - d"


def test_reserva_escreve_o_apostrofo_do_nome_e_o_travessao(db, cenario, sem_chromium):
    dados = _dados(db, cenario["escola"].id)
    assert dados["por_aluno"], "o cenário tem estudantes"
    dados["por_aluno"][0]["nome"] = "Ana Sant’Anna"
    dados["escola"]["nome"] = "Escola Ficticia D’Oeste"
    dados["periodo"]["rotulo"] = "Setembro — mês anterior"

    texto = _texto(pdf.gerar(dados, cor="#1B2A4A"))

    assert "Ana Sant’Anna" in texto, texto[:600]
    assert "Escola Ficticia D’Oeste" in texto, texto[:600]
    assert "Setembro — mês anterior" in texto, texto[:600]
    assert "Sant?Anna" not in texto and "Sant'Anna" not in texto
