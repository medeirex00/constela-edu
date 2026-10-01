"""O bimestre vem do CALENDÁRIO, não do mês do relógio.

O mapa por mês acertava o meio de cada período e errava exatamente a borda — o
único lugar onde a pergunta importa. Pelo calendário da Rede Estadual de SP, o 3º
bimestre de 2026 termina em **04/10**; o mapa por mês já devolvia 4 no dia 01/10.
Uma entrega de certificados na primeira semana de outubro sairia com "4º
bimestre" num documento sobre o trabalho do 3º.
"""
from datetime import date

import pytest

from app.services import bimestres

API = "/api/v1"


# --------------------------------------------------------------------------
# As oito bordas. Se alguma destas quebrar, o calendário foi alterado.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("dia,esperado", [
    (date(2026, 2, 2), 1),    # primeiro dia letivo
    (date(2026, 4, 22), 1),   # último dia do 1º
    (date(2026, 4, 23), 2),   # primeiro dia do 2º
    (date(2026, 7, 23), 2),   # último dia do 2º
    (date(2026, 7, 24), 3),   # primeiro dia do 3º
    (date(2026, 10, 4), 3),   # último dia do 3º — a borda que motivou tudo
    (date(2026, 10, 5), 4),   # primeiro dia do 4º
    (date(2026, 12, 31), 4),  # último dia do ano
])
def test_as_oito_bordas_do_calendario(dia, esperado):
    assert bimestres.bimestre_da_data(dia) == esperado


def test_a_virada_que_o_mapa_por_mes_errava():
    """01/10/2026 ainda é 3º bimestre. O mapa por mês dizia 4."""
    assert bimestres.bimestre_da_data(date(2026, 10, 1)) == 3
    assert bimestres.por_mes_legado(10) == 4, "o legado continua como era"


def test_os_quatro_intervalos():
    assert bimestres.intervalo(1) == (date(2026, 2, 2), date(2026, 4, 22))
    assert bimestres.intervalo(2) == (date(2026, 4, 23), date(2026, 7, 23))
    assert bimestres.intervalo(3) == (date(2026, 7, 24), date(2026, 10, 4))
    assert bimestres.intervalo(4) == (date(2026, 10, 5), date(2026, 12, 31))


def test_os_intervalos_sao_contiguos_e_nao_se_sobrepoem():
    """Nenhum dia letivo cai em dois bimestres, e não há buraco entre eles."""
    for numero in (1, 2, 3):
        _, fim = bimestres.intervalo(numero)
        inicio_proximo, _ = bimestres.intervalo(numero + 1)
        assert (inicio_proximo - fim).days == 1, f"buraco/sobreposição após o {numero}º"


def test_o_recesso_de_janeiro_nao_pertence_a_bimestre_nenhum():
    """E o módulo não finge que pertence — devolve None em vez de chutar."""
    assert bimestres.bimestre_da_data(date(2026, 1, 1)) is None
    assert bimestres.bimestre_da_data(date(2026, 2, 1)) is None


def test_a_sugestao_sempre_devolve_um_numero():
    """Quem precisa abrir um seletor não pode receber None."""
    assert bimestres.bimestre_sugerido(date(2026, 1, 15)) == 1, "recesso → 1º"
    assert bimestres.bimestre_sugerido(date(2026, 10, 1)) == 3
    assert bimestres.bimestre_sugerido(date(2026, 10, 5)) == 4


def test_ano_sem_calendario_cai_no_legado_em_vez_de_estourar():
    assert not bimestres.ano_com_calendario(2027)
    assert bimestres.bimestre_sugerido(date(2027, 3, 10)) == 1
    with pytest.raises(ValueError):
        bimestres.intervalo(1, ano=2027)


def test_faixa_do_bimestre():
    for invalido in (0, 5, -1, 99):
        with pytest.raises(ValueError):
            bimestres.intervalo(invalido)
        with pytest.raises(ValueError):
            bimestres.rotulo(invalido)
    assert bimestres.rotulo(3) == "3º bimestre"


# --------------------------------------------------------------------------
# A escolha de quem emite manda — em 01/10/2026, qualquer um dos quatro.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("escolhido", [1, 2, 3, 4])
def test_em_01_10_2026_quem_emite_escolhe_qualquer_bimestre(escolhido):
    """O defeito era o documento afirmar o bimestre do RELÓGIO. Agora a escolha
    atravessa até o HTML, e o que está impresso é o que foi pedido."""
    from app.services.relatorios import _certificado_plataforma_html

    for plataforma in ("elefante", "matific"):
        html = _certificado_plataforma_html("EMEF X", "ANA", plataforma,
                                            bimestre=escolhido)
        assert f'<div class="campo bimestre">{escolhido}</div>' in html, plataforma
        for outro in (1, 2, 3, 4):
            if outro != escolhido:
                assert f'<div class="campo bimestre">{outro}</div>' not in html


def test_sem_escolha_o_padrao_e_o_calendario_e_nao_o_mes(monkeypatch):
    """A regressão que este teste trava: voltar a usar o mês do relógio."""
    from datetime import datetime

    from app.services import relatorios as svc

    monkeypatch.setattr(svc, "agora_br", lambda: datetime(2026, 10, 1, 9, 0))
    html = svc._certificado_plataforma_html("EMEF X", "ANA", "matific")
    assert '<div class="campo bimestre">3</div>' in html, (
        "01/10 é 3º bimestre pelo calendário; o mapa por mês diria 4")

    monkeypatch.setattr(svc, "agora_br", lambda: datetime(2026, 10, 5, 9, 0))
    html = svc._certificado_plataforma_html("EMEF X", "ANA", "matific")
    assert '<div class="campo bimestre">4</div>' in html, "05/10 já é 4º"


def test_a_data_de_emissao_e_independente_do_bimestre(monkeypatch):
    """São conceitos diferentes: o documento pode avaliar o 3º e ser emitido em
    01/10. A data impressa é sempre a da emissão."""
    from datetime import datetime

    from app.services import relatorios as svc

    monkeypatch.setattr(svc, "agora_br", lambda: datetime(2026, 10, 1, 9, 0))
    html = svc._certificado_plataforma_html("EMEF X", "ANA", "elefante", bimestre=1)
    assert '<div class="campo bimestre">1</div>' in html
    assert ">01<" in html and "outubro" in html and "2026" in html
