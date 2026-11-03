"""O ci.yml RODA as verificações que a prontidão cobra, em vez de só declará-las.

Lacunas do crítico de completude e97:
- V5: os testes `-m postgres` (travas FOR UPDATE, corridas entre transações, migrações
  e prontidão em processo separado) PULAVAM no CI, que só tinha SQLite. Agora um job
  os roda contra o PostgreSQL do serviço, com o ambiente do test-backend;
- V18: os testes de tela do Quest (o app das crianças) não rodavam em lugar nenhum;
- V1/V2: o job de imagens só fazia `docker build`, e o 1º boot da imagem nova seria a
  produção. Agora o backend SOBE com ENV=producao e é conferido por dentro.

O GitHub é quem roda o workflow; aqui ficam fixadas a forma dos jobs e a coerência
dos blocos embutidos (o Python compila, o shell passa no `bash -n`, e a sonda HTTP da
fumaça reprova cada coisa que promete pegar, contra um servidor de mentira).
"""
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import threading

import pytest

yaml = pytest.importorskip("yaml")

from sqlalchemy.engine import make_url  # noqa: E402

from app.core.config import BASE_DIR, PROJECT_ROOT  # noqa: E402

CI = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"


def _jobs():
    return yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"]


def _passo_que_roda(job, trecho):
    passos = [p for p in job.get("steps") or [] if trecho in str(p.get("run", ""))]
    assert passos, f"nenhum passo roda {trecho!r}"
    return passos[0]


def _linhas(run):
    return [linha.strip() for linha in run.splitlines()]


def _blocos_python(run):
    """Os scripts `python - <<'PY'` de um bloco `run:` (já sem a indentação do YAML)."""
    return re.findall(r"python - <<'PY'\n(.*?)\nPY(?:\n|$)", run, re.S)


def _python_da_versao(job):
    return next(p["with"]["python-version"] for p in job["steps"]
                if p.get("uses", "").startswith("actions/setup-python"))


def _psycopg_do_dockerfile():
    achado = re.search(r'"psycopg\[binary\]==([\d.]+)"',
                       (BASE_DIR / "Dockerfile").read_text(encoding="utf-8"))
    assert achado, "o Dockerfile não fixa mais o psycopg[binary]"
    return achado.group(1)


# --- todos os blocos do ci.yml (os jobs novos embutem Python e shell) ------------------

def _todos_os_blocos_python():
    for nome, job in _jobs().items():
        blocos = [b for p in job.get("steps") or []
                  for b in _blocos_python(str(p.get("run", "")))]
        for i, bloco in enumerate(blocos):
            yield pytest.param(bloco, id=f"{nome}-{i}")


@pytest.mark.parametrize("bloco", list(_todos_os_blocos_python()))
def test_todo_bloco_python_do_ci_compila(bloco):
    compile(bloco, "<ci.yml>", "exec")


def _bash():
    """Um bash de verdade (no Windows, o System32\\bash.exe é o lançador do WSL)."""
    caminho = shutil.which("bash")
    if not caminho or "system32" in caminho.lower():
        pytest.skip("sem bash POSIX nesta máquina")
    return caminho


def test_todo_bloco_run_do_ci_passa_no_bash_n():
    bash = _bash()
    falhas = []
    for nome, job in _jobs().items():
        for passo in job.get("steps") or []:
            if "run" not in passo:
                continue
            roteiro = re.sub(r"\$\{\{.*?\}\}", "X", passo["run"])
            r = subprocess.run([bash, "-n"], input=roteiro, capture_output=True, text=True,
                               encoding="utf-8", timeout=30)
            if r.returncode:
                falhas.append((nome, passo.get("name"), r.stderr.strip()[:300]))
    assert not falhas, falhas


# --- V5: a suíte PostgreSQL no CI ------------------------------------------------------

def test_job_postgres_roda_a_suite_marcada_contra_o_servico():
    job = _jobs()["test-backend-postgres"]
    servico = job["services"]["postgres"]
    assert str(servico["image"]).startswith("postgres:")
    url = make_url(job["env"]["DATABASE_URL"])
    assert url.drivername == "postgresql+psycopg"
    assert url.host in ("localhost", "127.0.0.1")
    assert f"{url.port}:5432" in [str(p) for p in servico["ports"]]
    assert (url.username, url.password, url.database) == (
        servico["env"]["POSTGRES_USER"], servico["env"]["POSTGRES_PASSWORD"],
        servico["env"]["POSTGRES_DB"])
    # As fixtures PULAM em banco sem "test" no nome: o job ficaria verde sem testar nada.
    assert "test" in url.database.lower()

    passo = _passo_que_roda(job, "python -m pytest")
    linhas = _linhas(passo["run"])
    chamadas = [linha for linha in linhas if linha.startswith("python -m pytest")]
    assert chamadas and all(" -m postgres" in linha for linha in chamadas)
    exporta = linhas.index('export TEST_DATABASE_URL_PG="$DATABASE_URL"')
    tira = linhas.index("unset DATABASE_URL")
    assert exporta < tira < linhas.index(chamadas[0])
    assert passo.get("working-directory") == "backend"
    assert not job.get("continue-on-error") and not passo.get("continue-on-error")


def test_job_postgres_tem_o_ambiente_do_test_backend_mais_o_driver():
    """Mesmo Python, mesmas dependências e nenhuma variável a mais além da URL do
    serviço (que o passo do pytest troca por TEST_DATABASE_URL_PG); o driver é o da
    imagem de produção, na mesma versão."""
    jobs = _jobs()
    base, pg = jobs["test-backend"], jobs["test-backend-postgres"]
    assert _python_da_versao(pg) == _python_da_versao(base)
    sem_url = {k: v for k, v in (pg.get("env") or {}).items() if k != "DATABASE_URL"}
    assert sem_url == (base.get("env") or {})
    instala = _passo_que_roda(pg, "pip install")["run"]
    assert "-r backend/requirements.txt -r backend/requirements-dev.txt" in instala
    assert f'"psycopg[binary]=={_psycopg_do_dockerfile()}"' in instala


def test_job_postgres_confere_o_banco_antes_de_rodar():
    """A conferência prévia usa a MESMA régua das fixtures (local, "test" no nome) e
    conecta de verdade; o -rs põe no log o motivo de cada teste pulado."""
    run = _passo_que_roda(_jobs()["test-backend-postgres"], "python -m pytest")["run"]
    (previa,) = _blocos_python(run)
    assert 'os.environ["TEST_DATABASE_URL_PG"]' in previa
    assert '"test" in (url.database or "").lower()' in previa
    assert 'url.host in ("127.0.0.1", "localhost", "::1")' in previa
    assert "engine.connect()" in previa
    assert run.index("<<'PY'") < run.index("python -m pytest")
    assert " -rs " in next(linha for linha in _linhas(run) if linha.startswith("python -m pytest"))


# --- V18: os testes do Quest no CI ----------------------------------------------------

def test_quest_tem_testes_e_o_ci_os_roda():
    pacote = json.loads((PROJECT_ROOT / "apps" / "quest" / "package.json")
                        .read_text(encoding="utf-8"))
    assert pacote["scripts"]["test"] == "vitest run"
    assert list((PROJECT_ROOT / "apps" / "quest" / "src" / "test").glob("*.test.tsx"))
    job = _jobs()["test-quest"]
    _passo_que_roda(job, "npm ci")
    passo = _passo_que_roda(job, "npm run test --workspace @constela/quest")
    assert not job.get("continue-on-error") and not passo.get("continue-on-error")


# --- V1/V2: a fumaça do container do backend ------------------------------------------

BASE_DA_SONDA = 'BASE = "http://127.0.0.1:8000"'
ESPERA_DA_SONDA = "time.monotonic() + 240"


def _fumaca():
    job = _jobs()["docker"]
    passos = job["steps"]
    build = next(i for i, p in enumerate(passos)
                 if "docker build -t sgpe-backend" in str(p.get("run", "")))
    fumaca = next(i for i, p in enumerate(passos) if "docker run" in str(p.get("run", "")))
    assert fumaca > build, "a fumaça precisa da imagem construída antes"
    return job, passos[fumaca]


def _comando_docker_run(run):
    """A linha do `docker run`, com as continuações (`\\`) juntadas."""
    juntas = run.replace("\\\n", " ")
    return next(linha for linha in juntas.splitlines() if linha.strip().startswith("docker run"))


def test_fumaca_sobe_a_imagem_do_backend_como_producao():
    job, passo = _fumaca()
    run = passo["run"]
    comando = _comando_docker_run(run)
    assert comando.rstrip().endswith(" sgpe-backend")
    for opcao in ("-e ENV=producao", "-e DOCS_HABILITADOS=false"):
        assert opcao in comando
    # As chaves vão pelo NOME (o docker lê do ambiente): nenhum valor na linha de comando.
    for chave in ("SECRET_KEY", "DATA_ENCRYPTION_KEY"):
        assert re.search(rf"-e {chave}(\s|$)", comando), chave
        gerada = re.search(
            rf"^{chave}=\"\$\(python3 -c 'import secrets; print\(secrets\.token_urlsafe\((\d+)\)\)'\)\"$",
            run, re.M)
        assert gerada, f"{chave} não é gerada na hora"
        assert int(gerada.group(1)) >= 32, f"{chave} curta (a produção exige 32+ caracteres)"
        assert f'echo "::add-mask::${chave}"' in run
    assert '[ "$SECRET_KEY" = "$DATA_ENCRYPTION_KEY" ]' in run
    # O banco é o do serviço postgres do job, alcançado por um alias na rede interna.
    url = make_url(re.search(r"-e DATABASE_URL=(\S+)", comando).group(1))
    servico = job["services"]["postgres"]["env"]
    assert url.drivername == "postgresql+psycopg"
    assert (url.username, url.password, url.database) == (
        servico["POSTGRES_USER"], servico["POSTGRES_PASSWORD"], servico["POSTGRES_DB"])
    assert 'PG_SERVICO="${{ job.services.postgres.id }}"' in run
    assert f'docker network connect --alias {url.host} "$REDE" "$PG_SERVICO"' in run
    assert passo.get("timeout-minutes")


def test_fumaca_sem_rede_externa_sem_porta_e_sem_segredo_real():
    job, passo = _fumaca()
    run = passo["run"]
    comando = _comando_docker_run(run)
    assert 'docker network create --internal "$REDE"' in run
    assert '--network "$REDE"' in comando
    assert "--network host" not in run and not re.search(r"\s(-p|--publish)\s", comando)
    expressoes = re.findall(r"\$\{\{(.*?)\}\}", json.dumps(job))
    assert not [e for e in expressoes if "secrets" in e], "a fumaça não usa segredo do repositório"
    assert not job.get("continue-on-error") and not passo.get("continue-on-error")


def test_fumaca_derruba_o_container_mesmo_quando_falha():
    run = _fumaca()[1]["run"]
    linhas = _linhas(run)
    assert linhas.index("trap derrubar EXIT") < next(
        i for i, linha in enumerate(linhas) if linha.startswith("docker run"))
    corpo = run[run.index("derrubar() {"):run.index("trap derrubar EXIT")]
    for trecho in ('docker logs --tail 300 "$API"', 'docker rm -f "$API"',
                   'docker network rm "$REDE"', 'exit "$codigo"'):
        assert trecho in corpo, trecho


def test_fumaca_confere_o_container_por_dentro():
    """Além do HTTP: o processo principal não é root, as pastas que a API grava aceitam
    escrita e o Chromium do robô abre (o crítico: "subir sem Chromium ou sem escrita")."""
    http_, conteiner = _blocos_python(_fumaca()[1]["run"])
    assert '"/proc/1/status"' in conteiner and 'uid != "0"' in conteiner
    assert "settings.UPLOADS_DIR, settings.EXPORTS_DIR" in conteiner
    assert "p.chromium.launch(headless=True).close()" in conteiner
    assert BASE_DA_SONDA in http_ and ESPERA_DA_SONDA in http_


# --- a sonda HTTP da fumaça, contra um servidor de mentira -----------------------------

_PRODUCAO = {
    "/api/health/ready": (200, '{"status": "ok", "banco": "ok", "schema": "em_dia"}'),
    "/metrics": (404, "nao encontrado\n"),
}


class _Falso(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        codigo, corpo = self.server.respostas.get(self.path, (404, '{"detail":"Not Found"}'))
        dados = corpo.encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def log_message(self, *args):
        pass


@pytest.mark.parametrize("ajuste, passa", [
    ({}, True),
    ({"/docs": (200, "<html>swagger</html>")}, False),
    ({"/redoc": (200, "<html>redoc</html>")}, False),
    ({"/openapi.json": (200, "{}")}, False),
    ({"/metrics": (200, "# TYPE constela_requisicoes counter\n")}, False),
    ({"/metrics": (200, "metrics desativado\n")}, False),
    ({"/api/health/ready": (503, '{"status": "degradado", "motivo": "migracao_pendente"}')},
     False),
    ({"/api/health/ready": (200, '{"status": "ok", "schema": "adiante_aceito"}')}, False),
], ids=["producao", "docs", "redoc", "openapi", "metrics-aberto", "metrics-200",
        "ready-503", "ready-sem-em_dia"])
def test_a_sonda_da_fumaca_reprova_o_que_promete_pegar(ajuste, passa):
    http_ = _blocos_python(_fumaca()[1]["run"])[0]
    servidor = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Falso)
    servidor.respostas = {**_PRODUCAO, **ajuste}
    linha = threading.Thread(target=servidor.serve_forever, daemon=True)
    linha.start()
    try:
        sonda = (http_.replace(BASE_DA_SONDA, f'BASE = "http://127.0.0.1:{servidor.server_port}"')
                 .replace(ESPERA_DA_SONDA, "time.monotonic() + 1"))
        assert BASE_DA_SONDA not in sonda and ESPERA_DA_SONDA not in sonda
        r = subprocess.run([sys.executable, "-c", sonda], capture_output=True, text=True,
                           encoding="utf-8", timeout=60,
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    finally:
        servidor.shutdown()
        servidor.server_close()
    assert (r.returncode == 0) is passa, (r.stdout, r.stderr)
