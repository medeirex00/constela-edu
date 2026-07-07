"""Perfis posicionais de PDF — réplicas anonimizadas dos relatórios reais.

As fixtures reproduzem os artefatos que os PDFs verdadeiros apresentam:
nomes quebrados em várias linhas, durações fatiadas ("42h"/"09min"/"01s"),
unidades deslocadas alguns pontos abaixo do número, turma "sanduíche" do
Matific (metade acima, metade abaixo da linha do aluno), botão lateral
espelhado ("oãinipO") e títulos de livro que contêm palavras de cabeçalho.
"""
import pytest
from sqlalchemy import select

from app.models import Aluno, Leitura, Livro, Matricula, SnapshotElefante, Turma
from app.services import importacao as svc
from app.services.perfis_pdf import (
    Pagina,
    Palavra,
    PerfilElefanteEstudante,
    PerfilElefanteTurma,
    PerfilMatific,
    analisar_pdf,
    compactar,
    duracao_em_minutos,
)


def P(texto: str, x0: float, topo: float) -> Palavra:
    return Palavra(texto=texto, x0=x0, x1=x0 + 30.0, topo=topo)


# ---------------------------------------------------------------------------
# Conversões
# ---------------------------------------------------------------------------

def test_duracao_em_minutos():
    assert duracao_em_minutos("19:40:02") == 1180
    assert duracao_em_minutos("0:06:04") == 6
    assert duracao_em_minutos("42 h 09 min 01 s") == 2529
    assert duracao_em_minutos("00 s") == 0
    assert duracao_em_minutos("55 min 15 s") == 55
    with pytest.raises(ValueError):
        duracao_em_minutos("sem tempo")


def test_compactar_ignora_espacamento_intra_letra():
    assert compactar("Re la tó r io  d e  P e r fo r m a n c e") == "relatoriodeperformance"


# ---------------------------------------------------------------------------
# Perfil Elefante Letrado — relatório da turma
# ---------------------------------------------------------------------------

def _paginas_turma() -> list[Pagina]:
    palavras = [
        # capa: título, intervalo de datas e nome da turma
        P("Relatório", 40, 30), P("de", 92, 30), P("Performance", 106, 30),
        P("da", 172, 30), P("Turma", 186, 30),
        P("01/02/2026", 40, 50), P("-", 100, 50), P("06/07/2026", 110, 50),
        P("9", 40, 70), P("ANO", 50, 70), P("Z", 76, 70), P("TESTE", 86, 70),
        # cabeçalho em 3 linhas visuais (como o PDF real)
        P("Tempo", 247.5, 200), P("Tempo", 468.0, 200),
        P("Nome", 24.7, 215), P("do", 63.0, 215), P("Leituras", 171.0, 215),
        P("de", 247.5, 215), P("Questões", 302.2, 215), P("Questões", 390.0, 215),
        P("de", 468.0, 215), P("Livros", 522.7, 215),
        P("Estudante", 24.7, 230), P("Nível", 126.7, 230), P("Concluídas", 171.0, 230),
        P("Leitura", 247.5, 230), P("Respondidas", 302.2, 230),
        P("Aprovadas", 390.0, 230), P("Escuta", 468.0, 230), P("Escutados", 522.7, 230),
        # 1ª estudante: nome em 3 linhas, duração fatiada, unidades deslocadas
        P("MARIA", 24.7, 260), P("Q", 126.7, 260), P("120", 171.0, 260),
        P("12", 247.5, 260), P("h", 260.5, 263.3), P("300", 302.2, 260),
        P("250", 390.0, 260), P("00", 468.0, 260), P("s", 481.5, 263.3),
        P("2", 522.7, 260),
        P("CLARA", 24.7, 275), P("30", 247.5, 275), P("min", 261.0, 278.3),
        P("TESTE", 24.7, 290), P("15", 247.5, 290), P("s", 258.0, 293.3),
        # 2º estudante: registro simples (tempo de escuta na coluna certa)
        P("JOAO", 24.7, 320), P("M", 126.7, 320), P("80", 171.0, 320),
        P("5", 247.5, 320), P("h", 253.0, 323.3), P("100", 302.2, 320),
        P("90", 390.0, 320), P("10", 468.0, 320), P("min", 480.0, 323.3),
        P("0", 522.7, 320),
    ]
    return [Pagina(numero=1, palavras=palavras)]


def test_perfil_turma_costura_nomes_e_duracoes():
    perfil = PerfilElefanteTurma()
    analise = perfil.analisar(_paginas_turma())

    assert len(analise.linhas) == 2
    maria, joao = analise.linhas
    assert maria.nome == "MARIA CLARA TESTE"
    assert {k: v for k, v in maria.dados.items() if k != "turma_relatorio"} == {
        "nivel": "Q", "livros_unicos": 120,
        "tempo_leitura_min": 750,  # 12h 30min 15s
        "questoes_tentativas": 300, "questoes_acertos": 250}
    assert maria.dados["turma_relatorio"] == "9 ANO Z TESTE"
    assert maria.erros == [] and maria.avisos == []
    assert joao.nome == "JOAO"
    assert joao.dados["tempo_leitura_min"] == 300      # 5h — escuta não vaza
    assert analise.turma_detectada == "9 ANO Z TESTE"
    assert "(9 ANO Z TESTE)" in analise.mensagem_deteccao


def test_perfil_turma_detectado_pelo_titulo_compactado():
    perfil = PerfilElefanteTurma()
    assert perfil.detecta("xxrelatoriodeperformancedaturmaxx")
    assert not perfil.detecta("relatoriodeperformancedoestudante")


# ---------------------------------------------------------------------------
# Perfil Matific — classificação de estrelas
# ---------------------------------------------------------------------------

def _paginas_matific() -> list[Pagina]:
    palavras = [
        P("Matific", 40, 30),
        # cabeçalho com rótulos empilhados
        P("Atividades", 299.9, 100), P("Pontuação", 384.9, 100),
        P("Série", 51.7, 108), P("Aluno", 84.7, 108), P("Turma", 191.2, 108),
        P("Estrelas", 459.9, 108),
        P("Finalizadas", 299.9, 116), P("média", 384.9, 116),
        # registro 1: turma sanduíche + botão lateral espelhado colado na linha
        P("3", 191.2, 140), P("ANO", 199.5, 140), P("B", 224.2, 140),
        P("MANHA", 232.5, 140),
        P("3", 51.7, 148), P("ANA", 84.7, 148), P("B", 142.5, 148),
        P("50", 299.9, 148), P("4.10", 384.9, 148), P("200", 459.9, 148),
        P("oãinipO", 560.0, 149),
        P("ANUAL", 191.2, 156), P("(123)", 225.7, 156),
        # registro 2
        P("5", 191.2, 180), P("ANO", 199.5, 180), P("B", 224.2, 180),
        P("MANHA", 232.5, 180),
        P("5", 51.7, 188), P("LUCAS", 84.7, 188), P("T", 145.0, 188),
        P("30", 299.9, 188), P("3.50", 384.9, 188), P("90", 459.9, 188),
        P("ANUAL", 191.2, 196), P("(456)", 225.7, 196),
        # rodapé de impressão
        P("06/07/2026,", 40, 700), P("16:10", 105, 700), P("Matific", 140, 700),
        P("https://www.matific.com/bra", 40, 712),
    ]
    return [Pagina(numero=1, palavras=palavras)]


def test_perfil_matific_monta_turma_sanduiche_e_ignora_rodape():
    perfil = PerfilMatific()
    analise = perfil.analisar(_paginas_matific())

    assert len(analise.linhas) == 2
    ana, lucas = analise.linhas
    assert ana.nome == "ANA B"
    assert ana.dados == {"atividades": 50, "pontuacao_media": 4.1, "estrelas": 200,
                         "serie": "3", "turma_relatorio": "3 ANO B MANHA ANUAL"}
    assert ana.avisos == []                      # "oãinipO" não contamina estrelas
    assert lucas.nome == "LUCAS T"
    assert lucas.dados["turma_relatorio"] == "5 ANO B MANHA ANUAL"


# ---------------------------------------------------------------------------
# Perfil Elefante Letrado — relatório individual do estudante
# ---------------------------------------------------------------------------

def _paginas_estudante() -> list[Pagina]:
    palavras = [
        P("Relatório", 40, 30), P("de", 92, 30), P("Performance", 106, 30),
        P("do", 172, 30), P("Estudante", 186, 30),
        P("01/02/2026", 40, 50), P("-", 100, 50), P("06/07/2026", 110, 50),
        P("MARIA", 40, 70), P("CLARA", 80, 70), P("TESTE", 120, 70),
        P("9", 40, 85), P("ANO", 48, 85), P("Z", 70, 85), P("-", 80, 85),
        P("ESCOLA", 88, 85), P("MODELO", 130, 85),
        P("Q", 40, 100),
        # resumo "Hábito de Leitura": rótulo em cima, valor embaixo
        P("Leituras", 15.7, 140), P("Concluídas", 58.0, 140),
        P("Tempo", 305.6, 140), P("de", 340.0, 140), P("Leitura", 354.0, 140),
        P("25", 15.7, 155), P("5:30:00", 305.6, 155),
        P("Histórico", 15.7, 200), P("de", 66.0, 200), P("Livros", 80.0, 200),
        P("Lidos", 115.0, 200),
        # cabeçalho da tabela (Tempo/de empilhados sobre Leitura)
        P("Tempo", 330.0, 230),
        P("de", 330.0, 242),
        P("Titulo", 15.7, 254), P("do", 47.0, 254), P("Livro", 62.0, 254),
        P("Nível", 180.0, 254), P("Gênero", 230.0, 254), P("Textual", 268.0, 254),
        P("Leitura", 330.0, 254), P("Data/Hora", 400.0, 254),
        # livro 1: título e gênero quebrados; hora na linha de baixo
        P("O", 15.7, 280), P("Pequeno", 25.0, 280), P("Livro", 70.0, 280),
        P("K", 180.0, 280), P("Fantasia,", 230.0, 280),
        P("0:06:04", 330.0, 280), P("01/07/2026", 400.0, 280),
        P("Azul", 15.7, 292), P("Aventura", 230.0, 292), P("11:38:36", 400.0, 292),
        # livro 2: título contém "Nível 2" e o nível do livro é "cc"
        P("Nível", 15.7, 310), P("2", 47.0, 310), P("cc", 180.0, 310),
        P("Humor", 230.0, 310), P("1:00:20", 330.0, 310), P("25/05/2026", 400.0, 310),
    ]
    return [Pagina(numero=1, palavras=palavras)]


def test_perfil_estudante_historico_completo():
    perfil = PerfilElefanteEstudante()
    analise = perfil.analisar(_paginas_estudante())

    assert analise.formato == "leituras"
    assert "MARIA CLARA TESTE" in analise.mensagem_deteccao
    assert "25 leituras" in analise.mensagem_deteccao
    assert len(analise.linhas) == 2

    livro1, livro2 = analise.linhas
    assert livro1.nome == "MARIA CLARA TESTE"
    assert livro1.dados["livro"] == "O Pequeno Livro Azul"
    assert livro1.dados["nivel"] == "K"
    assert livro1.dados["genero"] == "Fantasia, Aventura"
    assert livro1.dados["data"] == "2026-07-01"
    assert livro1.dados["tempo_livro_min"] == 6
    # tempo total do resumo vai na 1ª linha para complementar o snapshot
    assert livro1.dados["tempo_leitura_min"] == 330

    # a coluna x separa o TÍTULO "Nível 2" do nível "cc" do livro
    assert livro2.dados["livro"] == "Nível 2"
    assert livro2.dados["nivel"] == "CC"
    assert livro2.dados["data"] == "2026-05-25"
    assert livro2.dados["tempo_livro_min"] == 60


# ---------------------------------------------------------------------------
# Correspondência de nomes abreviados (Matific) com desempate por turma
# ---------------------------------------------------------------------------

def test_abreviado_unico_vira_provavel(db, escola_completa):
    linha = svc.LinhaImportacao(numero=1, nome="ANA B", dados={})
    svc.casar_nomes(db, escola_completa["escola"].id, [linha])
    assert linha.correspondencia["status"] == "provavel"
    assert linha.correspondencia["aluno_nome"] == "Ana Beatriz Souza"


def test_abreviado_ambiguo_desempata_pela_turma(db, escola_completa):
    escola = escola_completa["escola"]
    turma5 = Turma(escola_id=escola.id, nome="5º Ano B", ano_escolar="5º Ano",
                   ano_letivo=2026)
    db.add(turma5)
    db.flush()
    outra = Aluno(escola_id=escola.id, nome="Ana Barbosa Lima")
    db.add(outra)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=outra.id,
                     turma_id=turma5.id, ano_letivo=2026))
    db.commit()

    com_turma = svc.LinhaImportacao(
        numero=1, nome="ANA B", dados={"turma_relatorio": "5 ANO B MANHA ANUAL"})
    sem_turma = svc.LinhaImportacao(numero=2, nome="ANA B", dados={})
    svc.casar_nomes(db, escola.id, [com_turma, sem_turma])

    assert com_turma.correspondencia["status"] == "provavel"
    assert com_turma.correspondencia["aluno_nome"] == "Ana Barbosa Lima"
    # sem a pista da turma, a decisão fica com o usuário — nunca é automática
    assert sem_turma.correspondencia["status"] == "nao_encontrado"
    assert len(sem_turma.correspondencia["alternativas"]) == 2


# ---------------------------------------------------------------------------
# Ida e volta com PDF de verdade (fpdf2 → pdfplumber → perfil → API)
# ---------------------------------------------------------------------------

def _pdf_estudante() -> bytes:
    from fpdf import FPDF

    pdf = FPDF(unit="pt", format="A4")
    pdf.add_page()
    pdf.set_font("helvetica", size=10)
    t = pdf.text
    t(40, 40, "Relatório de Performance do Estudante")
    t(40, 60, "01/02/2026 - 06/07/2026")
    t(40, 80, "MARIA CLARA TESTE")
    t(40, 95, "9 ANO Z TESTE ANUAL - ESCOLA MODELO")
    t(40, 110, "Q")
    t(15.7, 140, "Leituras Concluídas")
    t(305.6, 140, "Tempo de Leitura")
    t(15.7, 155, "25")
    t(305.6, 155, "5:30:00")
    t(15.7, 200, "Histórico de Livros Lidos")
    t(330, 230, "Tempo")
    t(330, 242, "de")
    t(15.7, 254, "Titulo")
    t(47, 254, "do")
    t(62, 254, "Livro")
    t(180, 254, "Nível")
    t(230, 254, "Gênero")
    t(268, 254, "Textual")
    t(330, 254, "Leitura")
    t(400, 254, "Data/Hora")
    t(15.7, 280, "O Pequeno Livro")
    t(180, 280, "K")
    t(230, 280, "Fantasia,")
    t(330, 280, "0:06:04")
    t(400, 280, "01/07/2026")
    t(15.7, 292, "Azul")
    t(230, 292, "Aventura")
    t(400, 292, "11:38:36")
    t(15.7, 310, "Nível 2")
    t(180, 310, "cc")
    t(230, 310, "Humor")
    t(330, 310, "1:00:20")
    t(400, 310, "25/05/2026")
    return bytes(pdf.output())


def test_analisar_pdf_escolhe_perfil_estudante():
    analise = analisar_pdf(_pdf_estudante())
    assert analise.estrategia == "perfil_elefante_estudante"
    assert analise.formato == "leituras"
    assert len(analise.linhas) == 2
    assert analise.linhas[0].dados["livro"] == "O Pequeno Livro Azul"


def test_pdf_sem_perfil_cai_nas_estrategias_genericas():
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=11)
    for linha in [
        "Elefante Letrado - relatório de leitura",
        "Aluno                  Livros lidos    Tempo de leitura",
        "Ana Beatriz Souza      7               180",
    ]:
        pdf.cell(0, 8, linha, new_x="LMARGIN", new_y="NEXT")
    analise = analisar_pdf(bytes(pdf.output()))
    assert analise.plataforma == "elefante"
    assert not analise.estrategia.startswith("perfil_")
    assert analise.linhas and analise.linhas[0].dados["livros_unicos"] == 7.0


def test_importacao_individual_pela_api(cliente, db, escola_completa):
    """Upload do relatório individual → prévia → confirmação → banco."""
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]

    resposta = cliente.post(
        f"/api/v1/escolas/{escola_id}/importacoes/analisar",
        files={"arquivo": ("relatorio.pdf", _pdf_estudante(), "application/pdf")},
    )
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["plataforma"] == "elefante"
    assert corpo["formato"] == "leituras"
    assert "MARIA CLARA TESTE" in corpo["mensagem_deteccao"]
    assert corpo["total_alunos"] == 1
    assert corpo["total_linhas"] == 2

    confirmacao = cliente.post(
        f"/api/v1/escolas/{escola_id}/importacoes/confirmar",
        json={
            "plataforma": "elefante", "formato": "leituras", "tipo": "pdf",
            "linhas": [
                {"nome": l["nome"], "dados": l["dados"], "aluno_id": ana.id}
                for l in corpo["linhas"]
            ],
        },
    )
    assert confirmacao.status_code == 200, confirmacao.text

    livros = db.execute(select(Livro).where(Livro.escola_id == escola_id)).scalars().all()
    assert {l.titulo for l in livros} == {"O Pequeno Livro Azul", "Nível 2"}
    assert {l.categoria for l in livros} == {"Fantasia, Aventura", "Humor"}

    leituras = db.execute(
        select(Leitura).where(Leitura.aluno_id == ana.id)).scalars().all()
    assert sorted(l.data.strftime("%Y-%m-%d") for l in leituras) == [
        "2026-05-25", "2026-07-01"]          # data real de conclusão de cada livro

    snapshot = db.execute(
        select(SnapshotElefante)
        .where(SnapshotElefante.aluno_id == ana.id)
        .order_by(SnapshotElefante.id.desc())
    ).scalars().first()
    assert snapshot.livros_unicos == 2
    assert snapshot.livros_por_nivel == {"K": 1, "CC": 1}
    assert snapshot.tempo_leitura_min == 330  # complementado pelo resumo


# ---------------------------------------------------------------------------
# Robustez (achados da auditoria adversarial dos parsers)
# ---------------------------------------------------------------------------

def _cabecalho_matific() -> list:
    return [
        P("Matific", 40, 30),
        P("Atividades", 299.9, 100), P("Pontuação", 384.9, 100),
        P("Série", 51.7, 108), P("Aluno", 84.7, 108), P("Turma", 191.2, 108),
        P("Estrelas", 459.9, 108),
        P("Finalizadas", 299.9, 116), P("média", 384.9, 116),
    ]


def test_matific_nome_em_tres_linhas_nao_trunca():
    """O nome do aluno pode quebrar em 3 linhas visuais (o registro nasce na do
    meio): as pontas ficam a ~16pt e não podem ser descartadas pelo limiar de
    proximidade da turma (12pt), senão o nome sai truncado ('MICKAELLYN')."""
    palavras = _cabecalho_matific() + [
        P("KEMILLYN", 84.7, 540.0),                                   # ponta de cima
        P("2", 191.2, 548.0), P("ANO", 199.5, 548.0), P("B", 224.2, 548.0),
        P("TARDE", 232.5, 548.0),                                     # turma acima
        P("2", 51.7, 555.7), P("MICKAELLYN", 84.7, 555.7),           # linha de dados
        P("4", 299.9, 555.7), P("4.50", 384.9, 555.7), P("18", 459.9, 555.7),
        P("ANUAL", 191.2, 564.0), P("(698)", 225.7, 564.0),          # turma abaixo
        P("BARBOSA", 84.7, 571.5), P("D", 132.0, 571.5),             # ponta de baixo
    ]
    analise = PerfilMatific().analisar([Pagina(numero=1, palavras=palavras)])
    assert len(analise.linhas) == 1
    aluno = analise.linhas[0]
    assert aluno.nome == "KEMILLYN MICKAELLYN BARBOSA D"  # nome completo, não truncado
    assert aluno.dados["estrelas"] == 18
    assert aluno.dados["turma_relatorio"] == "2 ANO B TARDE ANUAL"


def test_matific_aluno_inativo_com_tracos_sobrevive():
    """Aluno sem engajamento pode vir '- - -' nas colunas numéricas — ainda é
    um aluno e a linha não pode sumir (§51)."""
    palavras = _cabecalho_matific() + [
        P("3", 191.2, 140), P("ANO", 199.5, 140), P("B", 224.2, 140),
        P("3", 51.7, 148), P("ANA", 84.7, 148), P("S", 142.5, 148),
        P("50", 299.9, 148), P("4.10", 384.9, 148), P("200", 459.9, 148),
        P("ANUAL", 191.2, 156),
        # aluno inativo: três traços
        P("3", 191.2, 180), P("ANO", 199.5, 180), P("B", 224.2, 180),
        P("3", 51.7, 188), P("PEDRO", 84.7, 188),
        P("-", 299.9, 188), P("-", 384.9, 188), P("-", 459.9, 188),
        P("ANUAL", 191.2, 196),
    ]
    analise = PerfilMatific().analisar([Pagina(numero=1, palavras=palavras)])
    nomes = [l.nome for l in analise.linhas]
    assert "PEDRO" in nomes                       # não some da importação
    pedro = next(l for l in analise.linhas if l.nome == "PEDRO")
    assert "atividades" not in pedro.dados        # traço ilegível → campo ausente
    assert pedro.avisos                            # avisou sobre a célula ilegível


def test_estudante_avisa_quando_nome_arquivo_diverge_do_conteudo():
    """Nome do arquivo tem prioridade, mas se DIVERGIR do conteúdo (PDF
    renomeado/trocado) um aviso é emitido — sem trocar a prioridade."""
    analise = PerfilElefanteEstudante().analisar(
        _paginas_estudante(),
        nome_arquivo="Relatório de performance do estudante - OUTRA PESSOA QUALQUER.pdf")
    assert analise.origem_nome == "arquivo"
    assert analise.linhas[0].nome == "OUTRA PESSOA QUALQUER"
    assert any("difere" in e.casefold() for e in analise.erros_gerais)


def test_estudante_nome_arquivo_igual_conteudo_nao_avisa():
    analise = PerfilElefanteEstudante().analisar(
        _paginas_estudante(),
        nome_arquivo="Relatório de performance do estudante - MARIA CLARA TESTE.pdf")
    assert analise.origem_nome == "arquivo"
    assert not any("difere" in e.casefold() for e in analise.erros_gerais)


def test_analisar_pdf_sem_extensao_e_content_type_generico(cliente, escola_completa):
    """PDF sem extensão .pdf e com content-type genérico (ex.: upload mobile)
    ainda é lido pelo perfil — detecção por magic bytes '%PDF-', não jogado no
    ramo de texto que corromperia o binário."""
    escola_id = escola_completa["escola"].id
    resposta = cliente.post(
        f"/api/v1/escolas/{escola_id}/importacoes/analisar",
        files={"arquivo": ("relatorio", _pdf_estudante(), "application/octet-stream")},
    )
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["plataforma"] == "elefante"
    assert corpo["tipo"] == "pdf"
    assert corpo["total_alunos"] == 1
