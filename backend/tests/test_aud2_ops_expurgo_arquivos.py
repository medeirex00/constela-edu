"""Prévias não confirmadas e cópias de relatórios exportados expiram SOZINHAS (UPLOADS-5).

O prazo documentado (24 h para a prévia em ``UPLOADS_DIR/temporarios``; a retenção
``EXPORTS_RETENCAO_DIAS`` para as cópias em ``EXPORTS_DIR``) só era aplicado dentro de
OUTRA ação: uma nova análise de PDF/XLSX ou uma nova exportação. Sem elas (férias, escola
que importa pouco, sincronização, que grava no mesmo ``temporarios`` e nunca limpava), os
arquivos com nomes de crianças ficavam no disco sem prazo — e o expurgo da exclusão de
aluno (LGPD) deixa as prévias de fora justamente porque "expiram sozinhas".

Agora ``app/core/expurgo_arquivos.py`` roda no boot (startup do app) e a cada hora numa
thread por processo. Os ORIGINAIS confirmados (``UPLOADS_DIR/<plataforma>/``) não entram:
o prazo deles é decisão do dono. Tudo fictício, em pastas temporárias do teste.
"""
import os
import time

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

HORA = 3600
DIA = 24 * HORA


def _arquivo(caminho, idade_s: float, agora: float | None = None):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(b"%PDF-1.4 conteudo ficticio")
    momento = (agora if agora is not None else time.time()) - idade_s
    os.utime(caminho, (momento, momento))
    return caminho


@pytest.fixture()
def pastas(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "UPLOADS_DIR", tmp_path / "uploads")
    monkeypatch.setattr(settings, "EXPORTS_DIR", tmp_path / "exports")
    monkeypatch.setattr(settings, "EXPORTS_RETENCAO_DIAS", 7)
    return tmp_path


@pytest.fixture(autouse=True)
def _sem_expurgador_sobrando():
    yield
    try:
        from app.core import expurgo_arquivos
    except ImportError:
        return
    expurgo_arquivos.parar()


def _boot_do_app(monkeypatch):
    """O ciclo de vida do app de verdade (startup e shutdown). O shutdown também para o
    agendador da sync, cujo sinal de parada é do módulo e ficaria ligado para os testes
    seguintes: aqui o ``parar`` dele é trocado por nada (como em test_mantenedor_do_pool)."""
    from app.sync import scheduler as sync_scheduler

    monkeypatch.setattr(sync_scheduler, "parar", lambda *a, **k: None)
    with TestClient(app):
        pass


def test_boot_apaga_previa_e_copia_vencidas_sem_nova_analise_nem_exportacao(pastas,
                                                                           monkeypatch):
    temporarios = settings.UPLOADS_DIR / "temporarios"
    previa_velha = _arquivo(temporarios / ("a" * 32 + ".pdf"), 72 * HORA)
    planilha_velha = _arquivo(temporarios / ("b" * 32 + ".xlsx"), 25 * HORA)
    previa_nova = _arquivo(temporarios / ("c" * 32 + ".pdf"), 1 * HORA)
    original_confirmado = _arquivo(settings.UPLOADS_DIR / "matific" / "20260101_000000_x.pdf",
                                   300 * DIA)
    copia_velha = _arquivo(settings.EXPORTS_DIR / "alunos_20261001_120000.pdf", 10 * DIA)
    copia_nova = _arquivo(settings.EXPORTS_DIR / "ranking_20261110_120000.xlsx", 1 * DIA)
    gitkeep = _arquivo(settings.EXPORTS_DIR / ".gitkeep", 300 * DIA)
    subpasta = settings.EXPORTS_DIR / "pasta-do-operador"
    _arquivo(subpasta / "guardado.pdf", 300 * DIA)

    _boot_do_app(monkeypatch)

    assert not previa_velha.exists(), "a prévia de 72 h (prazo: 24 h) sobreviveu ao boot"
    assert not planilha_velha.exists()
    assert not copia_velha.exists(), "a cópia de 10 dias (retenção: 7) sobreviveu ao boot"
    # O que está no prazo, o original confirmado (decisão do dono), os arquivos de
    # infraestrutura e as subpastas ficam.
    assert previa_nova.exists() and copia_nova.exists()
    assert original_confirmado.exists()
    assert gitkeep.exists() and (subpasta / "guardado.pdf").exists()


def test_ciclo_periodico_apaga_o_que_vence_depois_do_boot(pastas):
    """Com o relógio fixado: no boot a prévia (1 h) e a cópia (6 dias) estão no prazo; o
    relógio anda 25 h e o CICLO seguinte, sem nenhuma análise ou exportação, as apaga."""
    from app.core import expurgo_arquivos

    agora = time.time()
    relogio = {"agora": agora}
    previa = _arquivo(settings.UPLOADS_DIR / "temporarios" / ("d" * 32 + ".pdf"), HORA, agora)
    copia = _arquivo(settings.EXPORTS_DIR / "livros_20261105_120000.csv", 6 * DIA, agora)

    assert expurgo_arquivos.iniciar(intervalo_s=0.05, relogio=lambda: relogio["agora"])
    assert expurgo_arquivos.ativo()
    time.sleep(0.2)                                  # boot e alguns ciclos: nada vence
    assert previa.exists() and copia.exists()

    relogio["agora"] = agora + 25 * HORA
    limite = time.monotonic() + 10
    while (previa.exists() or copia.exists()) and time.monotonic() < limite:
        time.sleep(0.02)
    assert not previa.exists(), "o ciclo periódico não apagou a prévia vencida"
    assert not copia.exists(), "o ciclo periódico não apagou a cópia vencida"

    expurgo_arquivos.parar()
    assert not expurgo_arquivos.ativo()


def test_iniciar_idempotente_thread_daemon_e_o_shutdown_para(pastas, monkeypatch):
    from app.core import expurgo_arquivos

    assert expurgo_arquivos.iniciar(intervalo_s=60)
    primeiro = expurgo_arquivos._atual
    assert primeiro._thread.daemon
    assert expurgo_arquivos.iniciar(intervalo_s=60) and expurgo_arquivos._atual is primeiro
    expurgo_arquivos.parar()
    assert not expurgo_arquivos.ativo()
    expurgo_arquivos.parar()                         # sem expurgador: nada a fazer

    _boot_do_app(monkeypatch)                        # o app liga no startup e para no shutdown
    assert not expurgo_arquivos.ativo()


def test_retencao_zero_desliga_so_as_copias_e_pasta_ausente_nao_quebra(pastas, monkeypatch):
    from app.core import expurgo_arquivos

    assert expurgo_arquivos.expurgar() == (0, 0)     # nenhuma das pastas existe ainda
    monkeypatch.setattr(settings, "EXPORTS_RETENCAO_DIAS", 0)
    previa = _arquivo(settings.UPLOADS_DIR / "temporarios" / ("e" * 32 + ".pdf"), 30 * HORA)
    copia = _arquivo(settings.EXPORTS_DIR / "alunos_20260101_120000.pdf", 300 * DIA)
    assert expurgo_arquivos.expurgar() == (1, 0)
    assert not previa.exists() and copia.exists()


def test_falha_numa_pasta_nao_impede_a_outra_nem_levanta(pastas, monkeypatch):
    from app.core import expurgo_arquivos

    def quebra(*_a, **_k):
        raise RuntimeError("falso")

    copia = _arquivo(settings.EXPORTS_DIR / "alunos_20260101_120000.pdf", 30 * DIA)
    monkeypatch.setattr(expurgo_arquivos, "limpar_temporarios", quebra)
    assert expurgo_arquivos.expurgar() == (0, 1)
    assert not copia.exists()


def test_o_prazo_da_previa_e_o_mesmo_da_rota_de_importacao():
    """Enquanto a rota de importação guardar a própria cópia do prazo, as duas não podem
    divergir (o expurgo de fundo apagaria antes ou depois do que a tela promete)."""
    from app.core import expurgo_arquivos
    from app.routers import importacoes

    assert expurgo_arquivos.IDADE_MAXIMA_TEMP_S == 24 * HORA
    assert getattr(importacoes, "IDADE_MAXIMA_TEMP_S",
                   expurgo_arquivos.IDADE_MAXIMA_TEMP_S) == expurgo_arquivos.IDADE_MAXIMA_TEMP_S
