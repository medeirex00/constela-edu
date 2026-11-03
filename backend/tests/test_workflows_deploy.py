"""Workflows do GitHub Actions: expressões que o GitHub aceita e deploy só com CI verde.

O deploy.yml falhava em TODO push ("Invalid workflow file … Unrecognized named-value:
'secrets'"): os passos da Vercel tinham `if: ${{ secrets.VERCEL_TOKEN != '' }}`, e o
contexto `secrets` não é permitido em `if:` — o GitHub recusa o arquivo inteiro, sem
criar job nenhum. Ele agora é só manual (workflow_dispatch), testa `env.VERCEL_TOKEN`
e nenhum job de deploy roda sem o portão `ci-verde`.

O analisador abaixo cobre a classe de erro que derrubou o arquivo — contexto ou
função fora do que aquele nível de `if:` aceita — e erros grosseiros de sintaxe; não
é o parser do GitHub (o actionlint seria o caminho completo).
"""
import re

import pytest

yaml = pytest.importorskip("yaml")

from app.core.config import PROJECT_ROOT  # noqa: E402

PASTA = PROJECT_ROOT / ".github" / "workflows"
WORKFLOWS = sorted(PASTA.glob("*.yml"))

# Contextos e funções que o GitHub aceita em cada `if:` (docs: "Contexts > Context
# availability" e "Expressions > Functions"). Nomes de contexto e de função não
# diferenciam maiúsculas; as palavras-chave (true, false, null, NaN, Infinity), sim —
# `False` vira um contexto desconhecido ("Unrecognized named-value").
CONTEXTOS = {
    "job": {"github", "needs", "vars", "inputs"},
    "passo": {"github", "needs", "vars", "inputs", "strategy", "matrix", "job", "runner",
              "env", "steps"},
}
_GERAIS = {"contains", "startswith", "endswith", "format", "join", "tojson", "fromjson",
           "case"}
_STATUS = {"always", "cancelled", "success", "failure"}
FUNCOES = {"job": _GERAIS | _STATUS, "passo": _GERAIS | _STATUS | {"hashfiles"}}
LITERAIS = {"true", "false", "null", "NaN", "Infinity"}


def _ler(arquivo):
    return yaml.safe_load(arquivo.read_text(encoding="utf-8"))


def _gatilhos(dados):
    return dados.get("on", dados.get(True))          # YAML 1.1 lê `on` como True


def _texto_do_if(valor) -> str:
    """O GitHub lê um `if: true`/`if: false` do YAML como o texto 'true'/'false'."""
    if isinstance(valor, bool):
        return "true" if valor else "false"
    return str(valor)


def _analisa(expressao: str):
    """(contextos, funções, problemas de sintaxe) de uma expressão, em minúsculas."""
    corpo = expressao.strip()
    if corpo.startswith("${{") and corpo.endswith("}}"):
        corpo = corpo[3:-2]
    problemas = []
    if corpo.count("'") % 2:
        problemas.append("aspas sem fechar")
    corpo = re.sub(r"'(?:[^']|'')*'", "''", corpo)                 # tira os textos
    if '"' in corpo:                     # fora de um texto: o GitHub só aceita aspas simples
        problemas.append("aspas duplas (o GitHub só aceita aspas simples)")
    pilha = []
    for c in corpo:
        if c in "([":
            pilha.append(c)
        elif c in ")]":
            if not pilha or {"(": ")", "[": "]"}[pilha.pop()] != c:
                problemas.append("parêntese/colchete sem par")
                break
    if pilha:
        problemas.append("parêntese/colchete sem fechar")
    if re.search(r"(?<![=!<>])=(?!=)", corpo):
        problemas.append("'=' sozinho (o operador é '==')")
    contextos, funcoes = set(), set()
    for m in re.finditer(r"(?<![\w.\-])([A-Za-z_][\w\-]*)", corpo):
        if m.group(1) in LITERAIS:                  # a palavra-chave, com a caixa exata
            continue
        nome = m.group(1).lower()
        if corpo[m.end():].lstrip().startswith("("):
            funcoes.add(nome)
        else:
            contextos.add(nome)
    return contextos, funcoes, problemas


def _ifs(dados):
    """(onde, nível, expressão) de cada `if:` de job e de passo."""
    for nome_job, job in (dados.get("jobs") or {}).items():
        if "if" in job:
            yield f"jobs.{nome_job}", "job", _texto_do_if(job["if"])
        for i, passo in enumerate(job.get("steps") or []):
            if "if" in passo:
                yield f"jobs.{nome_job}.steps[{i}]", "passo", _texto_do_if(passo["if"])


def _invalidos(expressao: str, nivel: str):
    contextos, funcoes, problemas = _analisa(expressao)
    return sorted(contextos - CONTEXTOS[nivel]) + sorted(
        f"{f}()" for f in funcoes - FUNCOES[nivel]) + problemas


@pytest.mark.parametrize("expressao, nivel, esperado", [
    ("${{ secrets.VERCEL_TOKEN != '' }}", "passo", ["secrets"]),      # o erro do main
    ("${{ env.VERCEL_TOKEN != '' }}", "passo", []),
    ("${{ env.X == 'a' }}", "job", ["env"]),                          # env não vale em job
    ("${{ !cancelled() && vars.X == 'a.b' }}", "job", []),
    ("${{ contains(github.ref, 'refs/tags') }}", "job", []),
    ("${{ format('{0}', secrets.T) != '' }}", "passo", ["secrets"]),
    ("${{ hashFiles('a.txt') != '' }}", "job", ["hashfiles()"]),     # só em passo
    ("${{ hashFiles('a.txt') != '' }}", "passo", []),
    ("${{ startsWit(github.ref, 'refs/tags') }}", "job", ["startswit()"]),
    ("${{ github.ref = 'refs/heads/main' }}", "job", ["'=' sozinho (o operador é '==')"]),
    ("${{ (github.ref == 'x' }}", "job", ["parêntese/colchete sem fechar"]),
    ("${{ Env.X != '' }}", "passo", []),                              # sem diferenciar maiúsculas
    ("${{ github.event['pull_request'] != null }}", "job", []),
    ("${{ github.ref == 'it''s' }}", "job", []),
    ("true", "job", []),
    ('${{ env.VERCEL_TOKEN != "" }}', "passo", ["aspas duplas (o GitHub só aceita aspas simples)"]),
    ('${{ inputs.x == "true" }}', "job", ["aspas duplas (o GitHub só aceita aspas simples)"]),
    ("${{ contains(fromJSON('[\"a\", \"b\"]'), github.ref) }}", "job", []),  # dentro do texto
    ("${{ github.event.repository.fork == False }}", "job", ["false"]),       # caixa errada
    ("${{ github.run_attempt < Infinity && github.run_number != NaN }}", "job", []),
    ("${{ case(github.ref == 'refs/heads/main', true, false) }}", "job", []),
])
def test_o_analisador_aponta_o_que_o_github_recusaria(expressao, nivel, esperado):
    assert _invalidos(expressao, nivel) == esperado


def test_if_booleano_do_yaml_e_lido_como_o_github_le():
    assert _texto_do_if(False) == "false" and _invalidos(_texto_do_if(False), "passo") == []


@pytest.mark.parametrize("arquivo", WORKFLOWS, ids=lambda p: p.name)
def test_todo_if_usa_so_o_que_o_github_aceita(arquivo):
    """A classe de erro que fazia o GitHub recusar o arquivo inteiro: um contexto ou
    uma função fora do que aquele nível de `if:` aceita, ou sintaxe quebrada."""
    invalidos = [(onde, problemas, expressao) for onde, nivel, expressao in _ifs(_ler(arquivo))
                 if (problemas := _invalidos(expressao, nivel))]
    assert not invalidos, f"{arquivo.name}: if: que o GitHub recusaria: {invalidos}"


def test_deploy_yml_so_roda_manualmente():
    assert set(_gatilhos(_ler(PASTA / "deploy.yml"))) == {"workflow_dispatch"}


def test_nenhum_job_de_deploy_roda_sem_o_ci_verde():
    """Publicar exige o portão: todo job além do ci-verde depende dele, e nenhum `if:`
    deles usa função de status — QUALQUER uma (success() inclusive, em qualquer caixa)
    tira o `success() &&` implícito e o job rodaria com o ci-verde reprovado ou
    pulado. Nenhum job ou passo engole erro."""
    jobs = _ler(PASTA / "deploy.yml")["jobs"]
    assert "ci-verde" in jobs
    for nome, job in jobs.items():
        if nome == "ci-verde":
            continue
        precisa = job.get("needs")
        precisa = [precisa] if isinstance(precisa, str) else (precisa or [])
        assert "ci-verde" in precisa, f"o job {nome} não depende do ci-verde"
        _, funcoes, _ = _analisa(_texto_do_if(job.get("if", "")))
        assert not funcoes & _STATUS, f"o job {nome} usa função de status no if: {funcoes}"
    for nome, job in jobs.items():
        assert not job.get("continue-on-error"), nome
        for passo in job.get("steps") or []:
            assert not passo.get("continue-on-error"), (nome, passo.get("name"))
    assert jobs["ci-verde"].get("permissions", {}).get("actions") == "read"


def test_ci_do_main_nunca_e_cancelado_pela_concorrencia():
    """Com o grupo de concorrência por ramo, dois pushes seguidos no main cancelavam o
    CI do primeiro (e um run pendente é sempre trocado pelo mais novo do grupo, mesmo
    sem cancel-in-progress); o "Wait for CI" do Railway, que ignora um CI cancelado
    quando outro workflow do commit passou, publicava um commit sem CI concluído. No
    main, cada run tem o seu grupo (run_id); só PR agrupa por ramo e cancela. A
    expressão é comparada INTEIRA: inverter o ternário volta ao grupo por ramo."""
    concorrencia = _ler(PASTA / "ci.yml")["concurrency"]
    grupo = str(concorrencia["group"]).replace(" ", "")
    cancela = str(concorrencia["cancel-in-progress"]).replace(" ", "")
    assert grupo == "ci-${{github.event_name=='pull_request'&&github.ref||github.run_id}}"
    assert cancela == "${{github.event_name=='pull_request'}}"


def test_o_job_ci_verde_roda_o_portao_do_repositorio():
    """O ci-verde baixa o commit e roda scripts/exigir_ci_verde.py (testado em
    test_exigir_ci_verde.py) com o repositório, o commit e o token do próprio run."""
    passos = _ler(PASTA / "deploy.yml")["jobs"]["ci-verde"]["steps"]
    assert passos[0].get("uses", "").startswith("actions/checkout@")
    portao = next(p for p in passos if "run" in p)
    assert portao["run"].strip() == "python3 backend/scripts/exigir_ci_verde.py"
    assert portao["env"] == {"GH_TOKEN": "${{ github.token }}",
                             "REPO": "${{ github.repository }}", "SHA": "${{ github.sha }}"}
    assert (PROJECT_ROOT / "backend" / "scripts" / "exigir_ci_verde.py").is_file()


def test_cada_job_de_deploy_refaz_o_portao_depois_da_aprovacao():
    """O ci-verde roda ANTES da aprovação do Environment, que pode vir horas depois; um
    re-run reprovado do CI nesse meio tempo vira a execução mais recente. Por isso TODO
    job além do ci-verde (a regra não depende de reconhecer o comando de deploy: `railway
    up`, `vercel --prod`, CLI com versão… todos caem nela):
    - baixa EXATAMENTE o commit conferido (checkout sem `ref`, ou `ref: github.sha`);
    - refaz o portão como 2º passo, sem `if:` (não pode ser pulado);
    - nenhum passo dele usa função de status no `if:` — always()/!cancelled()/failure()
      fariam o deploy rodar com o portão reprovado;
    - tem permissão de ler o Actions.
    O conjunto de jobs é fixo: um job novo obriga a revisar este teste."""
    jobs = _ler(PASTA / "deploy.yml")["jobs"]
    assert set(jobs) == {"ci-verde", "staging", "staging-web", "producao", "producao-web"}
    for nome, job in jobs.items():
        if nome == "ci-verde":
            continue
        passos = job.get("steps") or []
        checkout, portao = passos[0], passos[1]
        assert checkout.get("uses", "").startswith("actions/checkout@"), nome
        assert (checkout.get("with") or {}).get("ref") in (None, "${{ github.sha }}"), nome
        assert portao.get("run", "").strip() == "python3 backend/scripts/exigir_ci_verde.py", nome
        assert "if" not in portao, nome
        assert portao["env"] == {"GH_TOKEN": "${{ github.token }}",
                                 "REPO": "${{ github.repository }}", "SHA": "${{ github.sha }}"}
        for passo in passos:
            _, funcoes, _ = _analisa(_texto_do_if(passo.get("if", "")))
            assert not funcoes & _STATUS, (nome, passo.get("name"), funcoes)
        assert all("exigir_ci_verde" not in str(p.get("run", "")) for p in passos[2:]), nome
        assert any(("railway" in str(p.get("run", ""))) or ("vercel" in str(p.get("run", "")))
                   for p in passos[2:]), f"{nome} não publica nada depois do portão"
        assert job.get("permissions") == {"actions": "read", "contents": "read"}, nome


@pytest.mark.parametrize("se_do_passo", [
    "${{ always() }}", "${{ !cancelled() && env.VERCEL_TOKEN != '' }}",
    "${{ failure() || success() }}", "${{ Always() }}",
])
def test_o_analisador_pega_funcao_de_status_no_if_de_passo(se_do_passo):
    """Prova de que a regra acima recusaria um passo de deploy que ignora o portão."""
    _, funcoes, _ = _analisa(_texto_do_if(se_do_passo))
    assert funcoes & _STATUS


def test_o_ruleset_do_main_exige_todos_os_jobs_do_ci_e_da_seguranca():
    """.github/rulesets/protecao-main.json (importável; ainda não aplicado no GitHub):
    todo job do ci.yml e do security.yml é check obrigatório, e nenhum check exigido é
    um nome que nenhum job tem (o PR ficaria esperando para sempre). Exige também o
    ramo atualizado antes do merge e a mudança por PR."""
    import json
    regra = json.loads((PROJECT_ROOT / ".github" / "rulesets" / "protecao-main.json")
                       .read_text(encoding="utf-8"))
    checks = next(r for r in regra["rules"] if r["type"] == "required_status_checks")
    exigidos = {c["context"] for c in checks["parameters"]["required_status_checks"]}
    jobs = {job.get("name", nome) for arquivo in ("ci.yml", "security.yml")
            for nome, job in _ler(PASTA / arquivo)["jobs"].items()}
    assert jobs - exigidos == set(), "job sem check obrigatório no ruleset"
    assert exigidos - jobs == set(), "check obrigatório que nenhum job produz"
    assert checks["parameters"]["strict_required_status_checks_policy"] is True
    assert any(r["type"] == "pull_request" for r in regra["rules"])


def test_backend_e_web_publicam_em_jobs_separados():
    """Com o portão de CI ligado no Railway, o `railway up` é recusado (não traz o
    commit); se o web viesse depois dele no mesmo job (ou dependesse dele), o front
    ficaria sem caminho de publicação."""
    jobs = _ler(PASTA / "deploy.yml")["jobs"]
    publica = {}
    for nome, job in jobs.items():
        comandos = " ".join(str(p.get("run", "")) for p in job.get("steps") or [])
        publica[nome] = {"railway": "@railway/cli up" in comandos, "vercel": "vercel deploy" in comandos}
        assert not (publica[nome]["railway"] and publica[nome]["vercel"]), nome
    do_railway = {n for n, p in publica.items() if p["railway"]}
    for nome, p in publica.items():
        if p["vercel"]:
            precisa = jobs[nome].get("needs")
            precisa = {precisa} if isinstance(precisa, str) else set(precisa or [])
            assert not precisa & do_railway, f"o web ({nome}) depende do backend"
    assert do_railway and any(p["vercel"] for p in publica.values())
