"""P7 — a série de `Turma.ano_escolar` só é reconhecida quando está MARCADA como
série (ordinal / "ano" / "série" / rótulo inteiro); "Turma 12345" não vira série."""
import pytest

from app.services import dificuldade_livro as dl


@pytest.mark.parametrize("rotulo, esperado", [
    ("1º Ano", 1), ("4º ANO B", 4), ("3ª série", 3), ("2° ano", 2), ("3a serie", 3),
    ("5º", 5), ("5", 5), ("5B", 5), ("Ano 3", 3), ("10º ano", 10),
    ("Turma 12345", None), ("Turma 3", None), ("EJA 2", None), ("Pré-escola", None),
    ("12345", None), ("", None), (None, None),
])
def test_serie_numero_so_reconhece_serie_marcada(rotulo, esperado):
    assert dl.serie_numero(rotulo) == esperado


# Rótulos COMPOSTOS (multisseriada, aceleração, integral, sala/turno no nome):
# a série MARCADA ("5º Ano") vence o ordinal SOLTO que aparece antes dela — o
# mesmo número da v1. Sem as duas passadas de `serie_numero`, o ordinal mais à
# esquerda ganhava e a turma inteira era pontuada como a série mais BAIXA (fator
# maior: "Multisseriada 1º ao 5º Ano" valia 1,40 em vez de 1,00).
@pytest.mark.parametrize("rotulo, esperado", [
    ("Multisseriada 1º ao 5º Ano", 5), ("EF - 1º ao 5º ano", 5),
    ("Turma 1º A - 4º Ano", 4), ("Sala do 1º andar 5º ano", 5),
    ("Aceleração 3º ao 5º ano", 5), ("Classe multisseriada 4º e 5º ano", 5),
    ("Integral 2º - 4º Ano", 4), ("Multi 1º/2º ano", 2), ("Turno 1º - 3º ano", 3),
    # o ordinal SOLTO continua valendo quando é o único sinal de série...
    ("EF1 - 3º", 3),
    # ...mas não quando há MAIS DE UM (intervalo: sem série única), nem na EJA
    ("EF1 - 1º ao 5º", None), ("Multisseriada 1º/2º", None), ("EJA 1ª Etapa", None),
])
def test_serie_marcada_vence_o_ordinal_solto(rotulo, esperado):
    assert dl.serie_numero(rotulo) == esperado


def test_rotulo_composto_pontua_como_a_serie_marcada():
    """O fator de série (logo, os pontos de dificuldade) de um rótulo composto é o
    da série MARCADA, não o da série mais baixa citada no rótulo."""
    assert dl.fator_serie("Multisseriada 1º ao 5º Ano") == dl.fator_serie("5º Ano") == 1.0
    assert dl.fator_serie("Turma 1º A - 4º Ano") == dl.fator_serie("4º Ano") == 1.10
    regra = dl.RegraV1()
    assert regra.valor_livro("K", "x", "Multisseriada 1º ao 5º Ano") == pytest.approx(
        regra.valor_livro("K", "x", "5º Ano"))


def test_rotulo_sem_serie_usa_fator_neutro():
    regra = dl.RegraV1()
    assert regra.valor_livro("D", "x", "Turma 12345") == pytest.approx(regra.valor_livro("D", "x", "5º Ano"))
