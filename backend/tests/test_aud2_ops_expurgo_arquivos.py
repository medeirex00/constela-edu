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
from pathlib import Path

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


# ---------------------------------------------------------------------------
# REV2-OPS-1: só os arquivos com o NOME que o próprio app grava
# ---------------------------------------------------------------------------
# Em desenvolvimento (sem DADOS_DIR), EXPORTS_DIR é <raiz do repositório>/exports — a
# pasta onde o dono guarda as entregas — e o expurgo roda em todo boot do app. Antes, ele
# apagava QUALQUER arquivo de primeiro nível de EXPORTS_DIR (e qualquer *.pdf/*.xlsx de
# temporarios) mais velho que o prazo: um arquivo solto do dono sumia em 7 dias.


def test_boot_so_apaga_os_arquivos_com_o_nome_que_o_app_grava(pastas, monkeypatch):
    temporarios = settings.UPLOADS_DIR / "temporarios"
    previa_do_app = _arquivo(temporarios / ("0123456789abcdef" * 2 + ".xlsx"), 72 * HORA)
    copias_do_app = [
        _arquivo(settings.EXPORTS_DIR / nome, 30 * DIA)
        for nome in ("ranking_20261001_120000.csv", "alunos_20261001_120000.xlsx",
                     "livros_20261001_120000.pdf", "ranking_cartaz_20261001_120000.pdf",
                     "ranking_cartaz_matematica_20261001_120000.pdf")]
    de_outro_dono = [
        _arquivo(settings.EXPORTS_DIR / nome, 30 * DIA)
        for nome in ("PROPOSTA-ficticia.pdf", "contrato_ficticio.pdf", "notas.txt",
                     "Ranking_20261001_120000.pdf", "alunos_20261001_120000.docx",
                     "alunos-copia_20261001_120000.pdf", "alunos_20261001_1200.pdf",
                     "alunos_20261001_120000.pdf.bak")]
    de_outro_dono += [
        _arquivo(temporarios / nome, 30 * DIA)
        for nome in ("anotacao-do-operador.pdf", "g" * 32 + ".pdf", "a" * 31 + ".pdf",
                     "a" * 32 + ".csv", "A" * 32 + ".pdf", "a" * 32 + ".pdf.bak")]

    _boot_do_app(monkeypatch)

    assert not previa_do_app.exists(), "a prévia vencida com o nome do app sobreviveu"
    sobreviventes = [c.name for c in copias_do_app if c.exists()]
    assert not sobreviventes, f"cópias vencidas com o nome do app sobreviveram: {sobreviventes}"
    apagados = [a.name for a in de_outro_dono if not a.exists()]
    assert not apagados, f"o expurgo apagou arquivos que o app não grava: {apagados}"


def test_o_padrao_da_previa_e_o_mesmo_token_da_rota_de_importacao(pastas):
    """O nome que ``_guardar_temporario`` grava (também pela sincronização) é o que o
    expurgo reconhece; e a regra é a mesma que a confirmação aceita (``_TOKEN_VALIDO``)."""
    from app.core import expurgo_arquivos
    from app.routers import importacoes

    assert expurgo_arquivos.NOME_DA_PREVIA.pattern == importacoes._TOKEN_VALIDO.pattern
    for extensao in ("pdf", "xlsx"):
        token = importacoes._guardar_temporario(b"conteudo ficticio", extensao)
        assert token and (settings.UPLOADS_DIR / "temporarios" / token).is_file()
        assert expurgo_arquivos.NOME_DA_PREVIA.fullmatch(token), token


def test_as_copias_que_as_rotas_gravam_tem_o_nome_que_o_expurgo_reconhece(pastas, cliente,
                                                                         escola_completa,
                                                                         monkeypatch):
    """Cada relatório exportado (os 3 tipos, nos 3 formatos que não abrem navegador) e os 3
    cartazes deixam em EXPORTS_DIR uma cópia com nome que o expurgo reconhece — senão a
    cópia, com nomes de crianças, nunca expiraria."""
    from app.core import expurgo_arquivos
    from app.services import relatorios as svc

    monkeypatch.setattr(svc, "gerar_cartaz_ranking", lambda *a, **k: b"%PDF-1.4 ficticio")
    monkeypatch.setattr(svc, "gerar_lista_alunos_pdf", lambda *a, **k: b"%PDF-1.4 ficticio")
    monkeypatch.setattr(svc, "gerar_catalogo_livros_pdf",
                        lambda *a, **k: b"%PDF-1.4 ficticio")
    base = f"/api/v1/escolas/{escola_completa['escola'].id}"
    urls = [f"{base}/relatorios/{tipo}?formato={formato}"
            for tipo in sorted(svc.FONTES) for formato in ("csv", "xlsx")]
    urls += [f"{base}/relatorios/{tipo}?formato=pdf" for tipo in sorted(svc.FONTES)]
    urls += [f"{base}/ranking/cartaz", f"{base}/ranking/cartaz?dimensao=leitura",
             f"{base}/ranking/cartaz?dimensao=matematica"]
    for url in urls:
        resposta = cliente.get(url)
        assert resposta.status_code == 200, (url, resposta.status_code, resposta.text[:200])

    copias = sorted(a.name for a in settings.EXPORTS_DIR.iterdir() if a.is_file())
    assert len(copias) == len(urls), copias
    fora = [nome for nome in copias if not expurgo_arquivos.NOME_DA_COPIA.fullmatch(nome)]
    assert not fora, f"cópias que o expurgo não reconhece (nunca expirariam): {fora}"


def test_a_suite_nao_grava_nas_pastas_do_checkout():
    """Sem DADOS_DIR, UPLOADS_DIR e EXPORTS_DIR seriam as pastas do repositório, e todo
    ``with TestClient(app)`` (o boot liga o expurgo) e toda exportação de teste mexeria
    nelas. O conftest aponta as duas para uma pasta temporária da sessão."""
    from app.core.config import PROJECT_ROOT

    raiz = PROJECT_ROOT.resolve()
    for pasta in (settings.UPLOADS_DIR, settings.EXPORTS_DIR):
        assert not Path(pasta).resolve().is_relative_to(raiz), pasta
    assert os.environ.get("UPLOADS_DIR") == str(settings.UPLOADS_DIR)  # subprocessos herdam
    assert os.environ.get("EXPORTS_DIR") == str(settings.EXPORTS_DIR)
