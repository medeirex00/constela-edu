"""REV2-OPS-1 (E2E): o backend que os E2E sobem grava uploads e exportações numa pasta
TEMPORÁRIA, nunca nas pastas do repositório.

O expurgo de fundo (``app/core/expurgo_arquivos.py``) roda no boot da API e aplica a
retenção em ``UPLOADS_DIR/temporarios`` e ``EXPORTS_DIR``. Sem ``DADOS_DIR`` (nem
``UPLOADS_DIR``/``EXPORTS_DIR``), em desenvolvimento essas pastas são as do repositório —
``<repo>/exports`` é onde o dono guarda as entregas. A suíte do backend já aponta as duas
para uma pasta temporária (``tests/conftest.py``); os ``playwright*.config.ts`` que sobem o
backend (``webServer`` com o seed/uvicorn) ainda subiam a API com as pastas do checkout.
Este teste lê cada config e exige ``DADOS_DIR`` no ambiente do backend.
"""
import pathlib
import re

WEB = pathlib.Path(__file__).resolve().parents[2] / "apps" / "web"


def _configs_que_sobem_o_backend():
    for config in sorted(WEB.glob("playwright*.config.ts")):
        fonte = config.read_text(encoding="utf-8")
        if "BACKEND_DIR" in fonte and "BACKEND_ENV" in fonte:
            yield config.name, fonte


def test_ha_configs_que_sobem_o_backend():
    assert {nome for nome, _ in _configs_que_sobem_o_backend()} >= {
        "playwright.config.ts", "playwright.analise.config.ts", "playwright.visual.config.ts"}


def test_todo_backend_do_e2e_grava_fora_do_repositorio():
    for nome, fonte in _configs_que_sobem_o_backend():
        bloco = re.search(r"const BACKEND_ENV[^=]*=\s*\{(.*?)\n\};", fonte, re.S)
        assert bloco, f"{nome}: o BACKEND_ENV mudou de forma; ajuste o leitor deste teste"
        corpo = bloco.group(1)
        assert re.search(r"^\s*DADOS_DIR\s*:", corpo, re.M), (
            f"{nome}: o backend do E2E sobe sem DADOS_DIR e grava em <repo>/exports e "
            "<repo>/backend/uploads (o expurgo de fundo aplica a retenção ali)")
        assert "tmpdir()" in fonte, f"{nome}: DADOS_DIR deve ficar no temporário do sistema"
