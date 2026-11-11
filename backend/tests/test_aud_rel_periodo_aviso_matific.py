"""Relatório por Período: o aviso "sem coleta no início" do MATIFIC fala do contador
do Matific, não do das questões do Elefante.

A frase "o contador que o Constela coleta é acumulado desde o início da conta e não
diz quando cada questão foi respondida" descreve o contador vitalício de questões do
Elefante. O do Matific é do ANO (coleta ``this-year``) e conta ATIVIDADES e estrelas
— o próprio PDF diz isso em "Como ler": "O Matific informa o total do ano". Achados
RELATORIOS-7 e REVERIFICACAO-3 (mesma causa). Escola e números INVENTADOS.
"""
import pathlib
import re
from datetime import date, datetime

import pytest

from app.services import relatorios_periodo as rp
from app.services import relatorios_periodo_pdf as rpp
from tests.test_relatorios_periodo import _snap_elefante, _snap_matific

HOJE = date(2026, 10, 5)


def _setembro_com_primeira_coleta_no_meio(db, escola_completa):
    escola = escola_completa["escola"]
    a = escola_completa["alunos"][0]
    # Primeira coleta do Matific e das questões no MEIO de setembro: sem coleta no início.
    _snap_matific(db, escola.id, a.id, datetime(2026, 9, 15, 12, 0), 40, 20)
    _snap_matific(db, escola.id, a.id, datetime(2026, 9, 29, 12, 0), 55, 26)
    _snap_elefante(db, escola.id, a.id, datetime(2026, 9, 15, 12, 0), 100, 80)
    _snap_elefante(db, escola.id, a.id, datetime(2026, 9, 29, 12, 0), 130, 100)
    db.commit()
    return rp.gerar(db, escola.id, preset="mes_anterior",
                    plataformas=("elefante", "matific"), hoje=HOJE)


def _motivos(dados, rotulo):
    aviso = next(a for a in rpp._avisos_cobertura(dados) if a["rotulo"] == rotulo)
    return " ".join(aviso["motivos"])


def test_aviso_do_matific_fala_do_contador_do_ano_e_de_atividades(db, escola_completa):
    dados = _setembro_com_primeira_coleta_no_meio(db, escola_completa)
    cob = dados["matific"]["cobertura"]
    assert cob["alunos_sem_inicio"] == 1 and not cob["inicio_do_contador_anual"]
    texto = _motivos(dados, "Matific")
    assert "sem coleta no início do período" in texto, texto
    assert "início da conta" not in texto, texto
    assert "questão" not in texto and "questões" not in texto, texto
    assert "total do ano" in texto and "cada atividade" in texto, texto
    assert "esse trecho não sai das coletas" in texto, texto
    # E o documento não se contradiz com o próprio "Como ler".
    assert "O Matific informa o total do ano" in rpp.montar_html(dados)


def test_aviso_das_questoes_do_elefante_continua_o_mesmo(db, escola_completa):
    dados = _setembro_com_primeira_coleta_no_meio(db, escola_completa)
    texto = _motivos(dados, "Questões do Elefante")
    assert ("o contador que o Constela coleta é acumulado desde o início da conta e não "
            "diz quando cada questão foi respondida, então esse trecho não sai das "
            "coletas") in texto, texto
    assert "O Elefante guarda o histórico datado por aluno" in texto


_TELA = (pathlib.Path(__file__).resolve().parents[2] / "apps" / "web" / "src" / "pages"
         / "RelatorioPeriodo.tsx")


@pytest.mark.skipif(not _TELA.exists(), reason="cópia sem apps/web")
def test_a_tela_usa_as_mesmas_frases_por_plataforma():
    """O aviso da tela (``AvisoCobertura``) e o do PDF dizem o mesmo motivo, letra por
    letra, para cada plataforma — mudou um lado sem o outro, este teste avisa."""
    fonte = re.sub(r'"\s*\+\s*"', "", _TELA.read_text(encoding="utf-8"))
    frases = rpp._POR_QUE_SEM_INICIO
    assert set(frases) == {"diferenca_de_coletas", "oficial_matific"}
    faltam = [f for f in frases.values() if f not in fonte]
    assert not faltam, faltam
