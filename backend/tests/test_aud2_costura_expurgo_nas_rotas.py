"""REV2-OPS-1 / UPLOADS-5: o expurgo que as ROTAS fazem segue a regra única do expurgo de
fundo (``app/core/expurgo_arquivos.py``): só apaga os arquivos com o NOME que o próprio
app grava.

O expurgo de fundo já filtrava pelo nome (``NOME_DA_PREVIA``, ``NOME_DA_COPIA``), mas as
duas cópias antigas da regra, nas rotas, não:

* ``routers/relatorios._expurgar_exports_antigos`` (a cada nova exportação) apagava
  QUALQUER arquivo de primeiro nível de ``EXPORTS_DIR`` mais velho que a retenção — em
  desenvolvimento, ``<repo>/exports``, onde o dono guarda as entregas;
* ``routers/importacoes._limpar_temporarios_orfaos`` (a cada análise de PDF/XLSX) apagava
  QUALQUER ``*.pdf``/``*.xlsx`` de ``temporarios`` com mais de 24 h.

Agora as duas chamam a função compartilhada. Tudo fictício, em pastas temporárias.
"""
import os
import time

import pytest

from app.core import expurgo_arquivos
from app.core.config import settings
from app.routers import importacoes, relatorios

DIA = 24 * 3600


def _arquivo(caminho, idade_s):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(b"conteudo ficticio")
    momento = time.time() - idade_s
    os.utime(caminho, (momento, momento))
    return caminho


@pytest.fixture()
def pastas(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOADS_DIR", tmp_path / "uploads")
    monkeypatch.setattr(settings, "EXPORTS_DIR", tmp_path / "exports")
    monkeypatch.setattr(settings, "EXPORTS_RETENCAO_DIAS", 7)
    return tmp_path


def test_a_exportacao_nao_apaga_o_arquivo_do_dono_em_exports(pastas):
    exports = pastas / "exports"
    do_dono = _arquivo(exports / "Entrega-Ficticia-Para-A-Rede.pdf", 30 * DIA)
    copia_vencida = _arquivo(exports / "ranking_20260101_101010.csv", 30 * DIA)
    copia_recente = _arquivo(exports / "alunos_20261110_101010.xlsx", 1 * DIA)

    relatorios._expurgar_exports_antigos()

    assert do_dono.exists(), "a rota apagou um arquivo que o app não gravou"
    assert not copia_vencida.exists()
    assert copia_recente.exists()


def test_a_analise_nao_apaga_o_pdf_solto_em_temporarios(pastas):
    temporarios = pastas / "uploads" / "temporarios"
    solto = _arquivo(temporarios / "relatorio-ficticio-do-operador.pdf", 3 * DIA)
    previa_vencida = _arquivo(temporarios / ("a" * 32 + ".xlsx"), 2 * DIA)
    previa_recente = _arquivo(temporarios / ("b" * 32 + ".pdf"), 3600)

    importacoes._limpar_temporarios_orfaos()

    assert solto.exists(), "a rota apagou um arquivo que não é prévia do app"
    assert not previa_vencida.exists()
    assert previa_recente.exists()


def test_a_rota_de_importacao_usa_o_prazo_e_o_nome_da_regra_unica():
    assert importacoes.IDADE_MAXIMA_TEMP_S is expurgo_arquivos.IDADE_MAXIMA_TEMP_S
    assert importacoes._TOKEN_VALIDO is expurgo_arquivos.NOME_DA_PREVIA
