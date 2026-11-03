"""A imagem de produção não leva ferramenta de teste.

pytest e pytest-cov estavam no requirements.txt — o único que o Dockerfile instala —
e iam para o contêiner de produção. Agora moram no requirements-dev.txt, que o CI
instala junto e a imagem não copia.
"""
import re

from app.core.config import BASE_DIR, PROJECT_ROOT

_SO_DE_TESTE = {"pytest", "pytest-cov"}


def _pacotes(arquivo) -> set[str]:
    nomes = set()
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        linha = linha.split("#", 1)[0].strip()
        if linha and not linha.startswith("-"):
            nomes.add(re.split(r"[\[<>=!~ ;]", linha, maxsplit=1)[0].lower())
    return nomes


def test_requirements_de_producao_sem_ferramenta_de_teste():
    assert not _pacotes(BASE_DIR / "requirements.txt") & _SO_DE_TESTE


def test_ferramentas_de_teste_no_requirements_dev():
    assert _SO_DE_TESTE <= _pacotes(BASE_DIR / "requirements-dev.txt")


def test_dockerfile_instala_so_o_de_producao():
    texto = (BASE_DIR / "Dockerfile").read_text(encoding="utf-8")
    dockerfile = "\n".join(x for x in texto.splitlines() if not x.lstrip().startswith("#"))
    assert "requirements-dev" not in dockerfile
    assert "-r requirements.txt" in dockerfile


def test_ci_instala_os_dois_para_os_testes():
    ci = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "-r backend/requirements.txt -r backend/requirements-dev.txt" in ci
    seguranca = (PROJECT_ROOT / ".github" / "workflows" / "security.yml").read_text(
        encoding="utf-8")
    assert "-r backend/requirements.txt -r backend/requirements-dev.txt" in seguranca
