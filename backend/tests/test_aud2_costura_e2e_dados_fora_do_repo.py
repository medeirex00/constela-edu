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


def _problemas(nome: str, fonte: str) -> list[str]:
    """O que impede o backend do E2E de gravar só no temporário, lido no BACKEND_ENV.

    A conferência é na LINHA do próprio ``DADOS_DIR`` (REV2-COSTURA-6): procurar
    ``tmpdir()`` no arquivo todo deixava passar o ``DADOS_DIR`` apontado para
    ``<repo>/exports`` no ``playwright.analise.config.ts``, que já usa ``os.tmpdir()``
    na ``PASTA_DADOS``. ``UPLOADS_DIR``/``EXPORTS_DIR`` no mesmo bloco seguem a mesma
    regra: se aparecerem, valem mais que o ``DADOS_DIR``."""
    bloco = re.search(r"const BACKEND_ENV[^=]*=\s*\{(.*?)\n\};", fonte, re.S)
    if not bloco:
        return [f"{nome}: o BACKEND_ENV mudou de forma; ajuste o leitor deste teste"]
    corpo = bloco.group(1)
    if not re.search(r"^\s*DADOS_DIR\s*:", corpo, re.M):
        return [f"{nome}: o backend do E2E sobe sem DADOS_DIR e grava em <repo>/exports e "
                "<repo>/backend/uploads (o expurgo de fundo aplica a retenção ali)"]
    problemas = []
    for chave in ("DADOS_DIR", "UPLOADS_DIR", "EXPORTS_DIR"):
        for linha in re.findall(rf"^\s*{chave}\s*:.*$", corpo, re.M):
            if "tmpdir()" not in linha:
                problemas.append(f"{nome}: {chave} fora do temporário do sistema "
                                 f"(os.tmpdir() na mesma linha): {linha.strip()}")
    return problemas


def test_todo_backend_do_e2e_grava_fora_do_repositorio():
    problemas = [p for nome, fonte in _configs_que_sobem_o_backend()
                 for p in _problemas(nome, fonte)]
    assert not problemas, problemas


def test_dados_dir_apontado_para_o_repositorio_e_recusado():
    """A prova do leitor: a config da análise (que já usa ``os.tmpdir()`` noutra linha)
    com o ``DADOS_DIR`` em ``<repo>/exports`` é recusada; antes ficava verde. E um
    ``EXPORTS_DIR`` fora do temporário também."""
    fonte = (WEB / "playwright.analise.config.ts").read_text(encoding="utf-8")
    atual = re.search(r"^\s*DADOS_DIR\s*:.*$", fonte, re.M).group(0)
    para_o_repo = '  DADOS_DIR: path.join(BACKEND_DIR, "..", "exports"),'
    mexida = fonte.replace(atual, para_o_repo)
    assert "tmpdir()" in mexida                # o arquivo continua usando o temporário
    assert _problemas("playwright.analise.config.ts", mexida)
    com_exports = fonte.replace(
        atual, atual + '\n  EXPORTS_DIR: path.join(BACKEND_DIR, "..", "exports"),')
    assert _problemas("playwright.analise.config.ts", com_exports)
    assert not _problemas("playwright.analise.config.ts", fonte)
