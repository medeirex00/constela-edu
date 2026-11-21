"""O CI roda TODAS as suítes E2E do web, não só a principal (TESTES-4).

O job ``e2e`` rodava só ``npm run e2e`` (``playwright test`` com o playwright.config.ts,
testDir ./e2e). As outras duas suítes só rodavam à mão:

- playwright.analise.config.ts (./e2e-analise): a navegação dos 4 perfis, as travas de
  acesso por URL direta, o 403 das rotas da análise, a Secretaria sem nome de criança e
  a vitrine — contra o backend real, semeado com dados inventados;
- playwright.publico.config.ts (./e2e-publico): contrato e responsividade do telão da
  escola e da vitrine da rede (só o Vite; a API pública é simulada no teste).

Uma regressão em qualquer delas passava pelo CI verde. Esta catraca exige que TODA config
``playwright*.config.ts`` de apps/web seja invocada por um passo do ci.yml — a varredura
visual é a exceção declarada (ferramenta local de capturas: o próprio arquivo diz "Não roda
no CI") — e que o job de cada suíte tenha o que ela precisa para rodar de verdade.
"""
from __future__ import annotations

import re

import pytest

yaml = pytest.importorskip("yaml")

from app.core.config import PROJECT_ROOT  # noqa: E402

CI = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
WEB = PROJECT_ROOT / "apps" / "web"
FORA_DO_CI = {"playwright.visual.config.ts"}


def _jobs():
    return yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"]


def _roda(run: str, config: str) -> bool:
    if config == "playwright.config.ts":
        return ("npm run e2e --workspace @constela/web" in run
                or re.search(r"playwright test(?![^\n]*(\s-c\s|--config))", run) is not None)
    return re.search(rf"playwright test\b[^\n]*(\s-c\s+|--config[ =]){re.escape(config)}(\s|$)",
                     run) is not None


def _onde_roda(config: str):
    """(job, índice do passo, passo) de cada passo que roda a suíte da ``config``."""
    return [(job, i, passo) for job in _jobs().values()
            for i, passo in enumerate(job.get("steps") or [])
            if _roda(str(passo.get("run", "")), config)]


def _configs():
    return sorted(p.name for p in WEB.glob("playwright*.config.ts"))


def test_toda_config_do_playwright_roda_em_algum_passo_do_ci():
    configs = _configs()
    assert {"playwright.config.ts", "playwright.analise.config.ts",
            "playwright.publico.config.ts"} <= set(configs), configs
    faltam = [c for c in configs if c not in FORA_DO_CI and not _onde_roda(c)]
    assert not faltam, f"suítes E2E que o CI nunca roda: {faltam}"


def test_a_varredura_visual_fica_fora_do_ci_de_proposito():
    texto = (WEB / "playwright.visual.config.ts").read_text(encoding="utf-8")
    assert "Não roda no CI" in texto
    assert not _onde_roda("playwright.visual.config.ts")


@pytest.mark.parametrize("config", ["playwright.analise.config.ts",
                                    "playwright.publico.config.ts"])
def test_o_job_da_suite_tem_o_que_ela_precisa(config):
    onde = _onde_roda(config)
    assert onde, f"nenhum passo roda {config}"
    for job, i, passo in onde:
        # O -c é relativo: o passo roda dentro de apps/web.
        assert passo.get("working-directory") == "apps/web", passo
        # CI=true liga o forbidOnly: um test.only esquecido reprova em vez de pular o resto.
        assert str((passo.get("env") or {}).get("CI")) == "true", passo
        antes = job["steps"][:i]
        assert any("npm ci" in str(p.get("run", "")) for p in antes), "sem npm ci antes"
        assert any(re.search(r"playwright install\b[^\n]*chromium", str(p.get("run", "")))
                   for p in antes), "sem o Chromium do Playwright antes"


def test_a_suite_da_analise_sobe_o_backend_com_o_python_e_a_pasta_do_runner():
    onde = _onde_roda("playwright.analise.config.ts")
    assert onde, "nenhum passo roda playwright.analise.config.ts"
    for job, i, passo in onde:
        antes = job["steps"][:i]
        assert any("pip install -r backend/requirements.txt" in str(p.get("run", ""))
                   for p in antes), "o backend da análise precisa das dependências"
        assert any(str(p.get("uses", "")).startswith("actions/setup-python") for p in antes)
        env = passo.get("env") or {}
        # Sem E2E_PYTHON a config procura backend/.venv (não existe no runner) e cai no
        # `python` do PATH; explícito, não depende disso.
        assert env.get("E2E_PYTHON") == "python", env
        # O seed só apaga e recria o banco DENTRO desta pasta (caminho absoluto):
        # a do runner, descartável, nunca o checkout.
        assert str(env.get("E2E_ANALISE_PASTA", "")).startswith("${{ runner.temp }}/"), env
