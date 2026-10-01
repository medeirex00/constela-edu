"""O preset de bimestre tem de ser o do CALENDÁRIO DA REDE, não o do calendário.

Nasceu de uma auditoria feita no dia da cerimônia de premiação. A tela mandava
``?periodo=bimestre`` e ``periodos.resolver`` respondia com ``(mês-1)//2`` — o
bimestre do calendário civil. Em 01/10/2026 isso dava **01/09 a 31/10**, enquanto
o 3º bimestre oficial da rede é **24/07 a 04/10**: 61 dias contra 73, com apenas
34 em comum.

O efeito medido em produção naquele dia, no pódio de "Mais Livros Lidos":

    escola  1  oficial: YASMIM 150   ·  preset da tela: CESAR 32
    escola  7  oficial: VITOR   60   ·  preset da tela: KEVIN 38
    escola  8  oficial: GABRIEL 162  ·  preset da tela: LAUARA 108
    escola 11  oficial: KEMILY 115   ·  preset da tela: MARIA 65
    escola 17  oficial: ALICE   79   ·  preset da tela: ALICE 50

Quatro escolas de cinco coroariam a criança errada. Daí os dois travamentos
abaixo: a janela vem de ``app.services.bimestres`` (fonte única), e existe um
preset NUMERADO — porque "este bimestre" muda de janela sozinho quando o dia
vira, e um prêmio do 3º bimestre entregue em 05/10 não pode virar o 4º.
"""
from datetime import date

import pytest

from app.services import bimestres, periodos


def _datas(preset: str, hoje: date, ano_letivo: int = 2026):
    ini, fim, rotulo = periodos.resolver(preset, hoje, ano_letivo)
    return ini.date(), fim.date(), rotulo


# ---------------------------------------------------------------------------
# A janela é a oficial, não a do calendário civil
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("numero", [1, 2, 3, 4])
def test_bimestre_numerado_bate_exatamente_com_o_calendario_oficial(numero):
    oficial_i, oficial_f = bimestres.intervalo(numero, 2026)
    i, f, rotulo = _datas(f"bimestre_{numero}", date(2026, 10, 1))
    assert (i, f) == (oficial_i, oficial_f)
    assert rotulo.startswith(f"{numero}º bimestre")


def test_este_bimestre_em_1_de_outubro_e_o_TERCEIRO_e_nao_setembro_outubro():
    """A regressão exata que a auditoria encontrou."""
    i, f, rotulo = _datas("bimestre", date(2026, 10, 1))
    assert (i, f) == bimestres.intervalo(3, 2026)
    assert (i, f) == (date(2026, 7, 24), date(2026, 10, 4))
    assert "3º bimestre" in rotulo
    assert i != date(2026, 9, 1), "voltou a usar o bimestre do calendário civil"


def test_o_rotulo_diz_qual_bimestre_e_com_que_datas():
    """Quem lê o cabeçalho de um pódio precisa saber a janela sem perguntar."""
    _, _, rotulo = _datas("bimestre_3", date(2026, 10, 1))
    assert rotulo == "3º bimestre (24/07 a 04/10)"


@pytest.mark.parametrize("hoje,esperado", [
    (date(2026, 2, 2), 1),    # primeiro dia do ano letivo
    (date(2026, 4, 22), 1),   # último dia do 1º
    (date(2026, 4, 23), 2),   # primeiro do 2º
    (date(2026, 7, 23), 2),   # último do 2º
    (date(2026, 7, 24), 3),   # primeiro do 3º
    (date(2026, 10, 4), 3),   # último do 3º
    (date(2026, 10, 5), 4),   # primeiro do 4º
    (date(2026, 12, 31), 4),  # último do ano
])
def test_as_bordas_do_calendario_nao_escorregam_um_dia(hoje, esperado):
    assert _datas("bimestre", hoje)[:2] == bimestres.intervalo(esperado, 2026)


def test_recesso_de_janeiro_cai_no_primeiro_bimestre():
    """Fora dos quatro períodos a tela abre no 1º — o próximo a ser avaliado."""
    assert _datas("bimestre", date(2026, 1, 15))[:2] == bimestres.intervalo(1, 2026)


# ---------------------------------------------------------------------------
# Bimestre anterior
# ---------------------------------------------------------------------------
def test_bimestre_anterior_no_terceiro_e_o_segundo():
    assert _datas("bimestre_anterior", date(2026, 10, 1))[:2] == \
        bimestres.intervalo(2, 2026)


def test_bimestre_anterior_no_primeiro_nao_explode_sem_calendario_do_ano_passado():
    """2025 não tem calendário cadastrado: cai no legado, mas responde."""
    i, f, rotulo = _datas("bimestre_anterior", date(2026, 3, 1))
    assert i.year == 2025 and i < f
    assert rotulo == "Bimestre anterior"


# ---------------------------------------------------------------------------
# Ano sem calendário oficial: aproxima, nunca levanta erro
# ---------------------------------------------------------------------------
def test_ano_sem_calendario_nao_levanta_erro(monkeypatch):
    """2027 ainda não tem datas em ``bimestres.PERIODOS``. A emissão continua."""
    assert not bimestres.ano_com_calendario(2027)
    i, f, rotulo = _datas("bimestre", date(2027, 10, 1), ano_letivo=2027)
    assert i.year == f.year == 2027 and i <= f
    i2, f2, _ = _datas("bimestre_3", date(2027, 10, 1), ano_letivo=2027)
    assert i2.year == f2.year == 2027 and i2 <= f2


def test_numero_fora_da_faixa_nao_filtra_em_vez_de_quebrar():
    """Um número inventado não levanta erro nem inventa janela: não filtra."""
    assert periodos.resolver("bimestre_9", date(2026, 10, 1), 2026) ==         (None, None, "Todo o histórico")


# ---------------------------------------------------------------------------
# Contrato com a tela
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("preset", ["bimestre_1", "bimestre_2", "bimestre_3",
                                    "bimestre_4"])
def test_os_presets_numerados_estao_declarados_na_api(preset):
    assert preset in periodos.PRESETS


def test_os_presets_antigos_continuam_existindo():
    for preset in ("hoje", "semana", "mes", "mes_anterior", "bimestre",
                   "bimestre_anterior", "semestre", "ano_letivo", "tudo",
                   "personalizado"):
        assert preset in periodos.PRESETS
