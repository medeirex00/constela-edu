"""PEND-49 (IMPORTACAO-14, PDF) — número impossível no PDF vira "ilegível" na prévia.

Um "inf" (ou "1e400") numa coluna de contagem estourava ``int(inf)`` com
OverflowError, que a conversão tolerante não pegava: a prévia inteira caía na
mensagem genérica "Não foi possível ler o PDF". Um número gigante (o RA ou o
telefone caído na coluna) passava pela prévia e só era recusado com 400 na
confirmação. Agora os dois viram aviso de campo ilegível na linha — a mesma régua
(``importacao.valor_plausivel``) da planilha e do /confirmar.

Páginas sintéticas no formato dos perfis (como em test_perfis_pdf.py); dados
fictícios.
"""
from app.services.perfis_pdf import Pagina, Palavra, PerfilElefanteTurma, PerfilMatific


def P(texto: str, x0: float, topo: float) -> Palavra:
    return Palavra(texto=texto, x0=x0, x1=x0 + 30.0, topo=topo)


def _matific(atividades: str, media: str, estrelas: str) -> list[Pagina]:
    palavras = [
        P("Matific", 40, 30),
        P("Atividades", 299.9, 100), P("Pontuação", 384.9, 100),
        P("Série", 51.7, 108), P("Aluno", 84.7, 108), P("Turma", 191.2, 108),
        P("Estrelas", 459.9, 108),
        P("Finalizadas", 299.9, 116), P("média", 384.9, 116),
        P("3", 191.2, 140), P("ANO", 199.5, 140), P("B", 224.2, 140),
        P("3", 51.7, 148), P("BIA", 84.7, 148), P("R", 142.5, 148),
        P(atividades, 299.9, 148), P(media, 384.9, 148), P(estrelas, 459.9, 148),
        P("5", 191.2, 180), P("ANO", 199.5, 180), P("B", 224.2, 180),
        P("5", 51.7, 188), P("TITO", 84.7, 188), P("V", 145.0, 188),
        P("30", 299.9, 188), P("3.50", 384.9, 188), P("90", 459.9, 188),
    ]
    return [Pagina(numero=1, palavras=palavras)]


def test_matific_media_infinita_e_numero_gigante_viram_ilegivel():
    """"1e400" é infinito para o float; "99999999999" é o RA caído na coluna."""
    analise = PerfilMatific().analisar(_matific("99999999999", "1e400", "200"))

    assert len(analise.linhas) == 2
    bia, tito = analise.linhas
    for campo in ("atividades", "pontuacao_media"):
        assert campo not in bia.dados, bia.dados
        assert any(f"“{campo}” ilegível" in a for a in bia.avisos), bia.avisos
    assert bia.dados["estrelas"] == 200
    # a outra linha segue inteira
    assert (tito.dados["atividades"], tito.dados["estrelas"]) == (30, 90)
    assert tito.avisos == []


def test_matific_valor_normal_continua_igual():
    analise = PerfilMatific().analisar(_matific("50", "4.10", "200"))
    bia = analise.linhas[0]
    assert (bia.dados["atividades"], bia.dados["pontuacao_media"],
            bia.dados["estrelas"]) == (50, 4.1, 200)
    assert bia.avisos == []


def _turma(livros: str, tempo: list) -> list[Pagina]:
    palavras = [
        P("Relatório", 40, 30), P("de", 92, 30), P("Performance", 106, 30),
        P("da", 172, 30), P("Turma", 186, 30),
        P("Tempo", 247.5, 200), P("Tempo", 468.0, 200),
        P("Nome", 24.7, 215), P("do", 63.0, 215), P("Leituras", 171.0, 215),
        P("de", 247.5, 215), P("Questões", 302.2, 215), P("Questões", 390.0, 215),
        P("de", 468.0, 215), P("Livros", 522.7, 215),
        P("Estudante", 24.7, 230), P("Nível", 126.7, 230), P("Concluídas", 171.0, 230),
        P("Leitura", 247.5, 230), P("Respondidas", 302.2, 230),
        P("Aprovadas", 390.0, 230), P("Escuta", 468.0, 230), P("Escutados", 522.7, 230),
        P("LIA", 24.7, 260), P("Q", 126.7, 260), P(livros, 171.0, 260),
        *tempo,
        P("inf", 302.2, 260), P("250", 390.0, 260),
    ]
    return [Pagina(numero=1, palavras=palavras)]


def test_elefante_turma_inf_e_duracao_gigante_viram_ilegivel():
    tempo = [P("99999999", 247.5, 260), P("h", 270.0, 263.3)]
    analise = PerfilElefanteTurma().analisar(_turma("inf", tempo))

    assert len(analise.linhas) == 1
    lia = analise.linhas[0]
    for campo in ("livros_unicos", "tempo_leitura_min", "questoes_tentativas"):
        assert campo not in lia.dados, lia.dados
        assert any(f"“{campo}” ilegível" in a for a in lia.avisos), lia.avisos
    assert lia.dados["questoes_acertos"] == 250
