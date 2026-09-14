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


def test_rotulo_sem_serie_usa_fator_neutro():
    regra = dl.RegraV1()
    assert regra.valor_livro("D", "x", "Turma 12345") == pytest.approx(regra.valor_livro("D", "x", "5º Ano"))
