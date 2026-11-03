"""Portão de deploy (scripts/exigir_ci_verde.py): só publica o commit cujo CI do push no
main concluiu com sucesso. Roda no job ci-verde do deploy.yml e, se o dono configurar,
no Pre-deploy do Railway — onde fecha o buraco do "Wait for CI" (ele ignora um CI
cancelado quando outro workflow do mesmo commit passou)."""
import io
import json
import urllib.error

import pytest

from scripts import exigir_ci_verde as portao

SHA = "a" * 40
REPO = "org/repo"


def _run(conclusao, status="completed", event="push", ramo="main", sha=SHA,
         criado="2026-10-21T10:00:00Z", tentativa=1):
    return {"status": status, "conclusion": conclusao, "event": event, "head_branch": ramo,
            "head_sha": sha, "created_at": criado, "run_attempt": tentativa}


class _Api:
    """Faz o papel do urlopen: guarda o pedido e devolve (ou levanta) a resposta."""

    def __init__(self, execucoes=None, erro=None, corpo=None):
        self.execucoes, self.erro, self.corpo, self.pedidos = execucoes, erro, corpo, []

    def __call__(self, pedido, timeout=None):
        self.pedidos.append(pedido)
        if self.erro is not None:
            raise self.erro
        corpo = self.corpo if self.corpo is not None else json.dumps(
            {"workflow_runs": self.execucoes or []})
        return io.BytesIO(corpo.encode("utf-8"))


ENV = {"SHA": SHA, "REPO": REPO, "GH_TOKEN": "tok-de-teste"}


@pytest.mark.parametrize("execucoes, aprova", [
    ([_run("success")], True),
    ([_run("failure")], False),
    ([_run("cancelled")], False),                          # cancelado à mão: não publica
    ([_run(None, status="in_progress")], False),
    ([_run(None, status="queued")], False),
    ([], False),                                           # o CI nem rodou no main
    ([_run("success", event="pull_request", ramo="feat/x")], False),   # testou o merge
    ([_run("success", ramo="feat/x")], False),                         # outro ramo
    ([_run("success", sha="b" * 40)], False),                          # outro commit
    # a ordem da API não vale: o mais recente (pela data) decide
    ([_run("success", criado="2026-10-21T09:00:00Z"),
      _run("failure", criado="2026-10-21T11:00:00Z")], False),
    ([_run("success", criado="2026-10-21T11:00:00Z"),
      _run("failure", criado="2026-10-21T09:00:00Z")], True),
    # re-run: a tentativa mais nova da mesma execução decide
    ([_run("success", tentativa=1), _run("failure", tentativa=2)], False),
])
def test_so_aprova_o_ci_do_push_no_main_concluido_com_sucesso(execucoes, aprova, capsys):
    api = _Api(execucoes)
    assert (portao.main(ENV, api) == 0) is aprova
    saida = capsys.readouterr().out
    assert ("deploy recusado" in saida) is (not aprova)
    url = api.pedidos[0].full_url
    assert f"/repos/{REPO}/actions/workflows/ci.yml/runs?" in url
    assert f"head_sha={SHA}" in url and "event=push" in url and "branch=main" in url
    assert "tok-de-teste" not in saida                       # o token nunca aparece


@pytest.mark.parametrize("erro, corpo", [
    (urllib.error.HTTPError("u", 403, "Forbidden", {}, None), None),  # sem permissão
    (urllib.error.URLError("sem rede"), None),                          # API fora do ar
    (TimeoutError("lento"), None),
    (None, "<html>não é json</html>"),
])
def test_api_com_erro_recusa(erro, corpo, capsys):
    assert portao.main(ENV, _Api(erro=erro, corpo=corpo)) == 1
    assert "deploy recusado" in capsys.readouterr().out


@pytest.mark.parametrize("env", [
    {"REPO": REPO},                                         # sem commit (railway up manual)
    {"SHA": "abc123", "REPO": REPO},                        # commit curto
    {"SHA": SHA},                                           # sem repositório
    {"SHA": SHA, "REPO": "org/repo/../x"},
    {"SHA": SHA, "REPO": "org/repo?x=1"},
])
def test_sem_commit_ou_repositorio_valido_recusa_sem_consultar(env, capsys):
    api = _Api([_run("success")])
    assert portao.main(env, api) == 1
    assert api.pedidos == [] and "deploy recusado" in capsys.readouterr().out


def test_no_railway_usa_as_variaveis_do_git_do_deploy():
    api = _Api([_run("success")])
    env = {"RAILWAY_GIT_COMMIT_SHA": SHA, "RAILWAY_GIT_REPO_OWNER": "org",
           "RAILWAY_GIT_REPO_NAME": "repo"}
    assert portao.main(env, api) == 0
    assert f"/repos/{REPO}/" in api.pedidos[0].full_url
    assert "Authorization" not in api.pedidos[0].headers          # repo público: sem token


def test_token_vai_no_cabecalho():
    api = _Api([_run("success")])
    portao.main(ENV, api)
    assert api.pedidos[0].headers["Authorization"] == "Bearer tok-de-teste"


def test_argumentos_inesperados_recusam_sem_consultar(capsys):
    """Um `portão && migrate` passado sem shell (Pre-deploy de serviço com Dockerfile)
    chega como argumentos: recusar evita o deploy "verde" sem o migrate."""
    assert portao.principal(["&&", "python", "-m", "scripts.migrate"]) == 1
    assert "deploy recusado" in capsys.readouterr().out


def test_mensagem_mostra_o_codigo_http(capsys):
    erro = urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None)
    assert portao.main(ENV, _Api(erro=erro)) == 1
    assert "HTTP 429" in capsys.readouterr().out


@pytest.mark.parametrize("corpo", [
    json.dumps({"workflow_runs": "não é lista"}),
    json.dumps({"workflow_runs": [None, 3]}),
    json.dumps([1, 2]),
    json.dumps({"workflow_runs": [{"event": "push", "head_branch": "main", "head_sha": SHA,
                                   "created_at": None, "run_attempt": "2",
                                   "status": "completed", "conclusion": "success"},
                                  {"event": "push", "head_branch": "main", "head_sha": SHA,
                                   "created_at": None, "run_attempt": 3,
                                   "status": "completed", "conclusion": "success"}]}),
])
def test_resposta_com_formato_estranho_recusa_com_mensagem(corpo, capsys):
    """Nada de traceback: qualquer forma inesperada vira a recusa com o motivo."""
    assert portao.main(ENV, _Api(corpo=corpo)) == 1
    assert "deploy recusado" in capsys.readouterr().out


def test_o_migrate_roda_o_portao_antes_de_tocar_no_banco(monkeypatch):
    """EXIGIR_CI_VERDE=1 no serviço: o Pre-deploy continua `python -m scripts.migrate`
    (um comando só, sem shell) e o portão roda ANTES de qualquer acesso ao banco."""
    from scripts import migrate

    def nao_pode(*_a, **_k):
        raise AssertionError("o banco foi tocado com o portão recusando")

    monkeypatch.setattr(migrate.obs, "configurar_logging", lambda _s: None)
    monkeypatch.setattr(migrate, "estado_do_schema", nao_pode)
    monkeypatch.setattr(migrate, "aplicar_migracoes", nao_pode)
    monkeypatch.setattr(portao, "main", lambda: 1)
    monkeypatch.setenv("EXIGIR_CI_VERDE", "1")
    assert migrate.main() == migrate.SAIDA_PORTAO == 4


def test_sem_a_variavel_o_migrate_nao_consulta_o_ci(monkeypatch):
    from scripts import migrate

    class _Estado:
        def descrever(self):
            return "em dia"

    monkeypatch.setattr(migrate.obs, "configurar_logging", lambda _s: None)
    monkeypatch.setattr(migrate, "estado_do_schema", lambda _e: _Estado())
    monkeypatch.setattr(migrate, "aplicar_migracoes", lambda _e: _Estado())
    monkeypatch.setattr(migrate, "garantir_dados_base", lambda _e: None)
    monkeypatch.setattr(portao, "main", lambda: (_ for _ in ()).throw(AssertionError("consultou")))
    monkeypatch.delenv("EXIGIR_CI_VERDE", raising=False)
    assert migrate.main() == 0
    monkeypatch.setattr(portao, "main", lambda: 0)          # com a variável e o CI verde
    monkeypatch.setenv("EXIGIR_CI_VERDE", "1")
    assert migrate.main() == 0


@pytest.mark.parametrize("valor, ligado", [
    ("1", True), ("true", True), ("sim", True), ("yes", True), ("on", True), ("SIM", True),
    ("", False), ("0", False), ("false", False), ("não", False), ("off", False),
])
def test_valor_desconhecido_liga_o_portao(monkeypatch, valor, ligado):
    """Falha fechada: só vazio ou um "desligado" explícito desligam o portão."""
    from scripts import migrate
    monkeypatch.setenv("EXIGIR_CI_VERDE", valor)
    assert migrate._portao_ligado() is ligado
