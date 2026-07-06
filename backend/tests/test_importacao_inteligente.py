"""Testes do parser multi-estratégia — os formatos que PDFs reais produzem.

Cada estratégia é coberta com um texto no formato que a extração de PDF
costuma gerar. O objetivo do produto: arrastar o PDF e funcionar.
"""
import pytest

from app.services import importacao as svc

# ---------------------------------------------------------------------------
# Estratégia TABELA com cabeçalhos DIFERENTES dos exatos (casamento difuso)
# ---------------------------------------------------------------------------

def test_tabela_com_sinonimos_e_variacoes_de_caixa():
    texto = (
        "ALUNO(A);Atividades Completas;Média de Pontuação;Total de Estrelas\n"
        "Ana Beatriz Souza;42;85,5;120\n"
        "João Pedro Barbosa;10;70;35\n"
    )
    analise = svc.analisar_texto(texto, plataforma="matific")
    assert analise.estrategia == "tabela"
    assert len(analise.linhas) == 2
    assert analise.linhas[0].dados == {
        "atividades": 42.0, "pontuacao_media": 85.5, "estrelas": 120.0}


def test_tabela_com_erro_de_digitacao_no_cabecalho():
    """'Atvidades finalizadas' (typo) casa por distância de edição."""
    texto = (
        "Nome\tAtvidades finalizadas\tEstrelas\n"
        "Ana Beatriz Souza\t42\t120\n"
    )
    analise = svc.analisar_texto(texto, plataforma="matific")
    assert analise.estrategia == "tabela"
    assert analise.linhas[0].dados["atividades"] == 42.0


def test_tabela_modo_layout_com_colunas_de_espacos():
    """Como o pypdf em modo layout entrega: colunas alinhadas por espaços."""
    texto = (
        "Relatório Matific                             Página 1\n"
        "Nome do aluno            Atividades    Pontuação média    Estrelas\n"
        "Ana Beatriz Souza        42            85,5               120\n"
        "João Pedro Barbosa       10            70                 35\n"
        "Total                    52                               155\n"
    )
    analise = svc.analisar_texto(texto)
    assert analise.plataforma == "matific"
    assert analise.estrategia == "tabela"
    assert len(analise.linhas) == 2


# ---------------------------------------------------------------------------
# Estratégia VERTICAL — cabeçalho em linhas separadas (extração comum de PDF)
# ---------------------------------------------------------------------------

TEXTO_PDF_VERTICAL = """Relatório de desempenho — Matific
Nome do aluno
Atividades
Pontuação média
Estrelas
Ana Beatriz Souza
42
85,5
120
João Pedro Barbosa
10
70
35
Página 1 de 1
"""


def test_pdf_com_cabecalho_vertical():
    analise = svc.analisar_texto(TEXTO_PDF_VERTICAL)
    assert analise.plataforma == "matific"
    assert analise.estrategia == "cabecalho_vertical"
    assert len(analise.linhas) == 2
    ana = analise.linhas[0]
    assert ana.nome == "Ana Beatriz Souza"
    assert ana.dados == {"atividades": 42.0, "pontuacao_media": 85.5, "estrelas": 120.0}


def test_pdf_vertical_elefante():
    texto = (
        "Elefante Letrado — leitura\n"
        "Aluno\nLivros lidos\nTempo de leitura\nQuestões\nAcertos\n"
        "Sofia Almeida Duarte\n7\n180\n25\n20\n"
    )
    analise = svc.analisar_texto(texto)
    assert analise.plataforma == "elefante"
    assert analise.estrategia == "cabecalho_vertical"
    assert analise.linhas[0].dados["livros_unicos"] == 7.0
    assert analise.linhas[0].dados["questoes_acertos"] == 20.0


# ---------------------------------------------------------------------------
# Estratégia RÓTULOS — blocos "Campo: valor"
# ---------------------------------------------------------------------------

def test_blocos_rotulo_valor():
    texto = (
        "Relatório Matific\n"
        "Aluno: Ana Beatriz Souza\n"
        "Atividades: 42\n"
        "Pontuação média: 85,5\n"
        "Estrelas: 120\n"
        "Aluno: João Pedro Barbosa\n"
        "Atividades: 10\n"
        "Estrelas: 35\n"
    )
    analise = svc.analisar_texto(texto)
    assert analise.estrategia == "rotulos"
    assert len(analise.linhas) == 2
    assert analise.linhas[0].dados["pontuacao_media"] == 85.5
    assert analise.linhas[1].dados == {"atividades": 10.0, "estrelas": 35.0}


# ---------------------------------------------------------------------------
# Estratégia POSICIONAL — sem cabeçalho nenhum
# ---------------------------------------------------------------------------

def test_linhas_posicionais_sem_cabecalho():
    texto = (
        "Matific — desempenho da turma em matemática\n"
        "Ana Beatriz Souza 42 85,5 120\n"
        "João Pedro Barbosa 10 70 35\n"
    )
    analise = svc.analisar_texto(texto)
    assert analise.estrategia == "posicional"
    assert len(analise.linhas) == 2
    assert analise.linhas[0].dados["atividades"] == 42.0
    # A suposição de ordem é anunciada para conferência na prévia
    assert any("ordem" in aviso for aviso in analise.linhas[0].avisos)


def test_posicional_com_coluna_faltando_gera_aviso_nao_erro():
    """PRD: campo ausente não interrompe — importa o que foi reconhecido."""
    texto = (
        "Relatório Matific de atividades e estrelas\n"
        "Ana Beatriz Souza 42 85,5\n"
    )
    analise = svc.analisar_texto(texto)
    linha = analise.linhas[0]
    assert linha.erros == []
    assert linha.dados["atividades"] == 42.0
    assert "estrelas" not in linha.dados
    assert any("ausentes" in aviso.casefold() for aviso in linha.avisos)


# ---------------------------------------------------------------------------
# Detecção, diagnóstico e mensagens
# ---------------------------------------------------------------------------

def test_mensagem_de_deteccao_automatica():
    analise = svc.analisar_texto(TEXTO_PDF_VERTICAL)
    assert analise.mensagem_deteccao == "Este arquivo pertence ao Matific."


def test_diagnostico_quando_nada_e_reconhecido():
    analise = svc.analisar_texto("apenas uma frase solta", plataforma="matific")
    assert analise.erros_gerais
    assert "estratégias" in analise.erros_gerais[0]


def test_pdf_digitalizado_sem_texto_tem_mensagem_clara():
    analise = svc.analisar_texto("", plataforma="matific")
    assert any("digitalizado" in erro for erro in analise.erros_gerais)


# ---------------------------------------------------------------------------
# PDF de verdade: gera com fpdf2, extrai com pypdf e analisa (ida e volta)
# ---------------------------------------------------------------------------

def _pdf_de_teste() -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=11)
    # fonte core do PDF é latin-1: sem travessão (—)
    pdf.cell(0, 8, "Relatório Matific - Turma 3º Ano A", new_x="LMARGIN", new_y="NEXT")
    linhas = [
        "Nome do aluno      Atividades    Pontuação média    Estrelas",
        "Ana Beatriz Souza      42            85,5              120",
        "João Pedro Barbosa     10            70                 35",
    ]
    for linha in linhas:
        pdf.cell(0, 8, linha, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def test_pdf_real_de_ponta_a_ponta():
    texto = svc.extrair_texto_pdf(_pdf_de_teste())
    analise = svc.analisar_texto(texto)
    assert analise.plataforma == "matific"
    nomes = [l.nome for l in analise.linhas if not l.erros]
    assert any("Ana" in nome for nome in nomes)
    ana = next(l for l in analise.linhas if "Ana" in l.nome)
    assert ana.dados.get("atividades") == 42.0


def test_pdf_real_pela_api(cliente, escola_completa):
    """Upload do PDF binário → prévia com alunos casados (fluxo completo)."""
    escola_id = escola_completa["escola"].id
    resposta = cliente.post(
        f"/api/v1/escolas/{escola_id}/importacoes/analisar",
        files={"arquivo": ("relatorio.pdf", _pdf_de_teste(), "application/pdf")},
    )
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["plataforma"] == "matific"
    # O perfil posicional pode assumir o arquivo e detalhar a mensagem
    assert corpo["mensagem_deteccao"].startswith("Este arquivo pertence ao Matific")
    assert corpo["total_alunos"] == 2
    ana = next(l for l in corpo["linhas"] if "Ana" in l["nome"])
    assert ana["correspondencia"]["status"] == "exato"
