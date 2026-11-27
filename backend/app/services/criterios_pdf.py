"""Guia para famílias com a regra efetiva da escola, sem dados de alunos."""

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from app.core.tempo import hoje_br
from app.services import dificuldade_livro, matific_destaque
from app.services.relatorios import _latin1

_TITULO = "Critérios de pontuação"
_ROXO = (63, 45, 135)
_TEXTO = (34, 39, 57)
_SUAVE = (80, 85, 106)

_INDICADORES = {
    "livros": ("Livros únicos concluídos", "Cada título concluído conta uma vez."),
    "dificuldade": ("Dificuldade dos livros", "O nível e a regra em uso definem os pontos dos livros."),
    "questoes": ("Questões", "Perguntas de compreensão feitas depois da leitura."),
    "tempo": ("Tempo de leitura", "Minutos registrados no Elefante Letrado."),
    "atividades": ("Atividades finalizadas", "Atividades concluídas no Matific."),
    "media": ("Pontuação média", "Média das pontuações obtidas nas atividades."),
    "estrelas": ("Estrelas", "Estrelas conquistadas nas atividades."),
    "tentativas": ("Tentativas", "Vezes em que o aluno respondeu às questões."),
    "acertos": ("Acertos", "Respostas corretas nas questões de compreensão."),
}


def _numero(valor: float, casas: int = 1) -> str:
    return f"{valor:.{casas}f}".rstrip("0").rstrip(".").replace(".", ",")


class _Guia(FPDF):
    def __init__(self) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.set_margins(17, 16, 17)
        self.set_auto_page_break(auto=True, margin=18)
        self.alias_nb_pages()
        self.set_title(_TITULO)
        self.set_author("Constela Edu")

    def header(self) -> None:
        self.set_text_color(*_ROXO)
        self.set_font("helvetica", "B", 10)
        self.cell(0, 5, "Constela Edu", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(220, 215, 237)
        self.line(self.l_margin, self.get_y() + 2, self.w - self.r_margin, self.get_y() + 2)
        self.ln(7)

    def footer(self) -> None:
        self.set_y(-14)
        self.set_text_color(*_SUAVE)
        self.set_font("helvetica", size=9)
        self.cell(0, 5, f"Página {self.page_no()} de {{nb}}", align="R")


def _texto(pdf: FPDF, texto: str, *, tamanho: float = 10.5, estilo: str = "",
           cor: tuple[int, int, int] = _TEXTO) -> None:
    pdf.set_font("helvetica", estilo, tamanho)
    pdf.set_text_color(*cor)
    pdf.multi_cell(0, tamanho * 0.46, _latin1(texto), align="L",
                   new_x=XPos.LMARGIN, new_y=YPos.NEXT)


def _secao(pdf: FPDF, titulo: str) -> None:
    if pdf.will_page_break(20):
        pdf.add_page()
    _texto(pdf, titulo, tamanho=15, estilo="B", cor=_ROXO)
    pdf.ln(2)


def _item(pdf: FPDF, titulo: str, descricao: str) -> None:
    if pdf.will_page_break(17):
        pdf.add_page()
    _texto(pdf, titulo, estilo="B")
    _texto(pdf, descricao, tamanho=10, cor=_SUAVE)
    pdf.ln(2)


def _pesos(pdf: FPDF, titulo: str, pesos: dict[str, float]) -> None:
    if pdf.will_page_break(23):
        pdf.add_page()
    _texto(pdf, titulo, tamanho=12, estilo="B", cor=_ROXO)
    pdf.ln(1)
    for chave, valor in pesos.items():
        rotulo, descricao = _INDICADORES.get(chave, (chave, ""))
        _item(pdf, f"{rotulo} ({_numero(valor)}%)", descricao)
    pdf.ln(2)


def _explicar_premiacao(pdf: FPDF, leitura: bool, matematica: bool) -> None:
    _secao(pdf, "Regras da premiação")
    _texto(pdf, "Os pesos da nota compõem o desempenho em cada matéria. Cada prêmio segue seu próprio critério.")
    pdf.ln(3)
    if leitura:
        _item(pdf, "Melhor Leitor", "Maior soma de pontos de dificuldade dos livros lidos no período.")
        _item(pdf, "Mais Livros Lidos", "Maior número de livros lidos no período.")
        _item(pdf, "Mais Tempo de Leitura", "Maior número de minutos de leitura no período.")
    if matematica:
        ajuste = _numero(100 * matific_destaque.FRACAO_ZEROS_EXTRAS)
        _item(pdf, "Melhor Matemática",
              f"Maior média ajustada de estrelas, de 0 a 5. Divide-se o total de estrelas pelo número de "
              f"atividades mais {ajuste}% da mediana de atividades da escola no período.")
    _item(pdf, "Quem concorre e qual período conta",
          "Participam alunos ativos do 1º ao 5º ano, matriculados no ano letivo atual, com resultado maior que "
          "zero. A escola pode consultar por bimestre, mês, ano letivo ou outro intervalo. Só conta o que foi "
          "feito no período escolhido.")
    if matematica:
        _item(pdf, "Desempate de Melhor Matemática", "Mais estrelas, depois mais atividades concluídas.")
    _item(pdf, "Ordem de classificação",
          "A ordem alfabética resolve os empates restantes. "
          "A posição usa o valor completo, antes do arredondamento.")
    pdf.ln(3)
    _item(pdf, "O que a escola entrega",
          "Certificados. Para a emissão, o aluno precisa estar confirmado na Lista Piloto da escola. "
          "O modelo Geral exige também desempenho calculado.")


def _exemplos(pdf: FPDF, leitura: bool, matematica: bool, versao: str) -> None:
    _secao(pdf, "Como funciona na prática")
    if leitura:
        if versao == dificuldade_livro.VERSAO_LEGADA:
            detalhes = ("Os pontos de cada faixa seguem a regra própria da escola. "
                        "A pontuação também pode variar por série ou turma.")
        else:
            parametros = dificuldade_livro.PARAMS_POR_VERSAO[versao]
            reducao = _numero((1 - parametros["piso"]) * 100)
            aumento = _numero((parametros["teto"] - 1) * 100)
            fatores = ", ".join(f"{serie}º ano ×{_numero(fator)}"
                                for serie, fator in parametros["fator_serie"].items())
            detalhes = ("Os níveis de AA a Z indicam a dificuldade. Dentro de um nível, o tamanho do livro "
                        f"pode reduzir os pontos em até {reducao}% ou aumentar em até {aumento}%. "
                        f"A pontuação também varia pelo ano escolar ({fatores}).")
        _item(pdf, "Leitura · exemplo fictício",
              detalhes + " Terminar dois títulos e depois reler um deles conta como dois livros.")
    if matematica:
        atividades, estrelas, mediana = 20, 80, 20
        ajuste = mediana * matific_destaque.FRACAO_ZEROS_EXTRAS
        indice = matific_destaque.indice(atividades, estrelas, mediana)
        _item(pdf, "Matemática · exemplo fictício",
              f"Com {atividades} atividades, {estrelas} estrelas e uma mediana de {mediana} atividades na "
              f"escola, o índice de Melhor Matemática seria {estrelas} ÷ ({atividades} + "
              f"{_numero(ajuste)}) = {_numero(indice, 2)}.")


def gerar_criterios_pdf(escola_nome: str, regra: dict, pesos_geral: dict[str, float]) -> bytes:
    """Renderiza apenas os pesos oficiais, o plano e as explicações dos critérios."""
    pdf = _Guia()
    dimensoes = {item["dimensao"]: item for item in regra["dimensoes"] if item["contratada"]}
    leitura = dimensoes.get("leitura")
    matematica = dimensoes.get("matematica")

    pdf.add_page()
    _texto(pdf, _TITULO, tamanho=26, estilo="B")
    _texto(pdf, escola_nome, tamanho=13, estilo="B", cor=_ROXO)
    _texto(pdf, f"Regras em uso em {hoje_br():%d/%m/%Y}", tamanho=9.5, cor=_SUAVE)
    pdf.ln(6)

    _secao(pdf, "Como a pontuação é calculada")
    if regra["perfil"] == "personalizado":
        _texto(pdf, "Régua personalizada. O Constela usa as regras configuradas para esta escola.")
    else:
        _texto(pdf, "Régua Padrão Constela. A regra de cálculo é a mesma para toda a rede.")
    pdf.ln(2)
    _texto(pdf, "Cada matéria tem uma nota de 0 a 100. Cada critério contribui conforme seu peso. "
                "Quando falta dado de uma plataforma, o aluno fica fora do ranking daquela matéria.")
    pdf.ln(2)
    if regra["normalizacao"]["modo"] == "auto":
        _texto(pdf, "A comparação usa referências calculadas a partir dos colegas da própria escola.")
    else:
        _texto(pdf, "Os resultados são comparados com as referências definidas para esta escola.")
    pdf.ln(6)

    if not dimensoes:
        _texto(pdf, "O plano desta escola está sem matérias de pontuação.")
        return bytes(pdf.output())

    _secao(pdf, "Peso de cada critério na nota")
    if leitura:
        _pesos(pdf, "Leitura · Elefante Letrado", leitura["pesos"])
        _pesos(pdf, "Questões · divisão do peso de Leitura", leitura["subpesos_questoes"])
    if matematica:
        _pesos(pdf, "Matemática · Matific", matematica["pesos"])
    if leitura and matematica:
        leitura_pct = _numero(pesos_geral.get("elefante", 0))
        matematica_pct = _numero(pesos_geral.get("matific", 0))
        _item(pdf, "Nota Geral", f"Com as duas matérias aferidas, combina Leitura ({leitura_pct}%) e "
              f"Matemática ({matematica_pct}%). Com dados de uma só matéria, considera a nota disponível.")

    pdf.add_page()
    _explicar_premiacao(pdf, bool(leitura), bool(matematica))
    pdf.ln(3)
    _exemplos(pdf, bool(leitura), bool(matematica), regra["versoes"]["dificuldade"])
    return bytes(pdf.output())
