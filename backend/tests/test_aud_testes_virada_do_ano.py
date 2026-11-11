"""A suíte não depende do ano em que roda (achados TESTES-1 e PERIODOS-9).

O DEFEITO. Os testes que gravam retratos e leituras "agora" usavam escolas de ano letivo
escrito no código (2026: a ``escola_completa`` do conftest e as fixtures próprias dos
módulos). O produto mede o ano letivo pela janela civil do dado (o contador do ANO do
Matific, ranking, painel público, retenção de queda do sync): a partir de 01/01/2027
00:00 UTC — 31/12 às 21h em Brasília, a hora do runner do CI — o dado de "agora" saía do
ano da escola e mais de cem testes ficavam vermelhos sem nenhuma mudança de código. Uma
janela escrita no código (``datetime(2026, 12, 31)``) já quebrava em 31/12.

A CORREÇÃO (``tests._ano_letivo``): o teste que grava "agora" põe a escola no ano de hoje
(``ANO``, que segue o relógio); o de datas fixas segue no ano delas; a janela "até hoje"
acaba no fim de hoje.

A GUARDA. Representantes de cada causa rodam num processo novo com o relógio ADIANTADO
(``tests._relogio_adiantado``): na noite de 31/12 em Brasília, no começo de janeiro e no
meio de janeiro do ano que vem. Dados fictícios dos próprios testes.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests._ano_letivo import ANO

BACKEND = Path(__file__).resolve().parents[1]

#: Um ou dois por causa: a escola de teste no ano de hoje (a ``escola_completa`` e a
#: fixture própria do módulo; o dado que o próprio fluxo do app grava "agora" na
#: importação e na sync; a data "no futuro"), e a janela escrita no código.
REPRESENTANTES = [
    "tests/test_publico.py::test_painel_publico_sem_login",
    "tests/test_scoring.py::test_nota_matific_com_pesos_padrao",
    "tests/test_ranking_rede.py::test_6_pontuacao_geral_e_a_media_das_dimensoes",
    "tests/test_importacao.py::test_confirmar_importacao_matific_gera_snapshot_e_recalcula",
    "tests/test_sync_integridade_resultados_ponta_a_ponta.py"
    "::test_retrato_gravado_chega_a_nota_aos_rankings_e_as_premiacoes",
    "tests/test_leituras_restauracao.py::test_recusa_data_no_futuro[ano_de_hoje]",
    "tests/test_matific_periodo.py::test_evolucao_ordena_por_data_apos_backfill",
]

INSTANTES = [
    f"{ANO}-12-31T22:00:00-03:00",       # 01h de 01/01 em UTC: o runner já virou o ano
    f"{ANO + 1}-01-01T03:30:00+00:00",   # 00h30 de 01/01 em Brasília: "ontem" é o ano passado
    f"{ANO + 1}-01-15T12:00:00+00:00",   # "60 dias atrás" ainda é o ano passado
]


@pytest.mark.parametrize("instante", INSTANTES)
def test_representantes_passam_com_o_relogio_adiantado(instante, tmp_path):
    env = {**os.environ, "RELOGIO_ADIANTADO": instante}
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-rf", "-p", "no:cacheprovider",
         "-p", "tests._relogio_adiantado", "--basetemp", str(tmp_path / "bt"),
         *REPRESENTANTES],
        cwd=BACKEND, env=env, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=600)
    resumo = [linha[:200] for linha in r.stdout.splitlines()
              if linha.startswith(("FAILED", "ERROR")) or " passed" in linha
              or " failed" in linha or " error" in linha]
    assert r.returncode == 0, f"relógio em {instante}:\n" + "\n".join(resumo or [r.stderr[-2000:]])
