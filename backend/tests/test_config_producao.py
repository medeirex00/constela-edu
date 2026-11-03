"""Boot com ENV=producao recusa configuração perigosa; em dev, só aviso no log.

A3 (critério 9): a produção rodou sem ENV (= "dev") e sem nenhuma trava de
configuração além da SECRET_KEY. Já recusavam com ENV=producao: SECRET_KEY curta ou
padrão e SQLite (test_seguranca.py), ADMIN_GLOBAL_EMAIL malformado
(test_seguranca_privilegios.py) e chave anterior igual à atual (test_cifra_chaveiro.py).
Faltavam, e agora recusam (``Settings.riscos_de_producao``):

* DATA_ENCRYPTION_KEY ausente (ou só espaços) — os segredos em repouso caíam na chave
  derivada da SECRET_KEY, a mesma que assina os JWT;
* DATA_ENCRYPTION_KEY igual à SECRET_KEY — o mesmo efeito, em silêncio;
* CORS_ORIGINS com curinga '*' — com ``allow_credentials`` o Starlette devolve a origem
  de quem pedir;
* DOCS_HABILITADOS=true — /docs, /redoc e /openapi.json publicam o mapa da API.

Em dev nada disso derruba o boot: o log diz o que o ENV=producao vai recusar. A
mensagem nunca leva o valor de uma chave. Todos os valores aqui são fictícios.

Chaves de EXEMPLO (``CHAVES_DE_EXEMPLO``): o .env.example da raiz manda copiar para .env
e subir o compose, que roda com ENV=producao. A SECRET_KEY de exemplo tinha 32
caracteres e a DATA_ENCRYPTION_KEY de exemplo 34, e as duas passavam: a produção subia
assinando JWT e cifrando as credenciais das escolas com textos públicos do repositório.
Agora a SECRET_KEY de exemplo recusa o boot de produção (em dev vira a efêmera, como o
padrão do código) e a DEK de exemplo entra em ``riscos_de_producao``. Os testes leem os
dois .env.example para manter a lista em sincronia com eles.
"""
from __future__ import annotations

import json
import logging
import re
import secrets
import traceback
from urllib.parse import urlsplit

import pytest

from app.core.config import (
    BASE_DIR,
    CHAVES_DE_EXEMPLO,
    PROJECT_ROOT,
    Settings,
    avisos_de_configuracao,
    chave_de_exemplo,
    registrar_avisos_de_configuracao,
)
from tests._infra_comum import (  # noqa: F401 — fixture
    BOOT,
    MIGRAR,
    ambiente,
    rodar,
    sondar,
    sqlite_url,
)

# URL de PostgreSQL só para passar pela recusa do SQLite: nenhuma conexão é aberta.
_PG = "postgresql+psycopg://app@127.0.0.1:55432/config_producao_test"
_VARIAVEIS = ("ENV", "DATABASE_URL", "SECRET_KEY", "DATA_ENCRYPTION_KEY",
              "DATA_ENCRYPTION_KEYS_ANTERIORES", "CHAVE_CIFRA_LEGADA_ANTERIOR",
              "CORS_ORIGINS", "DOCS_HABILITADOS", "ADMIN_GLOBAL_EMAIL", "METRICS_PUBLICO")


def _chave(rotulo: str) -> str:
    return f"{rotulo}-{secrets.token_urlsafe(40)}"


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch):
    """Nenhuma variável do processo de teste vaza para o Settings() destes testes."""
    for nome in _VARIAVEIS:
        monkeypatch.delenv(nome, raising=False)


def _producao(**extra) -> Settings:
    valores = {"_env_file": None, "ENV": "producao", "DATABASE_URL": _PG,
               "SECRET_KEY": _chave("sk"), "DATA_ENCRYPTION_KEY": _chave("dek")}
    valores.update(extra)
    return Settings(**valores)


def _recusa(**extra) -> str:
    with pytest.raises(RuntimeError) as erro:
        _producao(**extra)
    return str(erro.value)


def test_producao_completa_sobe():
    s = _producao()
    assert s.em_producao and s.riscos_de_producao() == []
    assert s.DOCS_HABILITADOS is False
    assert "https://www.constelaedu.com" in s.CORS_ORIGINS
    assert avisos_de_configuracao(s) == []


@pytest.mark.parametrize("dek", ["", "   "])
def test_producao_recusa_dek_ausente(dek):
    sk = _chave("sk")
    mensagem = _recusa(SECRET_KEY=sk, DATA_ENCRYPTION_KEY=dek)
    assert "DATA_ENCRYPTION_KEY ausente" in mensagem
    assert "ENV=producao" in mensagem
    assert sk not in mensagem


@pytest.mark.parametrize("como", ["igual", "com_espacos"])
def test_producao_recusa_dek_igual_a_secret_key(como):
    sk = _chave("sk")
    dek = sk if como == "igual" else f"  {sk} "
    mensagem = _recusa(SECRET_KEY=sk, DATA_ENCRYPTION_KEY=dek)
    assert "DATA_ENCRYPTION_KEY igual à SECRET_KEY" in mensagem
    assert sk not in mensagem                              # a mensagem não leva valor


@pytest.mark.parametrize("origens", [["*"], ["https://www.constelaedu.com", "*"],
                                     ["https://*.constelaedu.com"]])
def test_producao_recusa_cors_com_curinga(origens):
    assert "CORS_ORIGINS com curinga" in _recusa(CORS_ORIGINS=origens)


def test_producao_recusa_docs_habilitados():
    assert "DOCS_HABILITADOS=true" in _recusa(DOCS_HABILITADOS=True)


def test_producao_lista_todos_os_problemas_de_uma_vez():
    """O operador corrige tudo num deploy só, em vez de descobrir um por vez."""
    mensagem = _recusa(DATA_ENCRYPTION_KEY="", CORS_ORIGINS=["*"], DOCS_HABILITADOS=True)
    for trecho in ("DATA_ENCRYPTION_KEY ausente", "CORS_ORIGINS com curinga",
                   "DOCS_HABILITADOS=true"):
        assert trecho in mensagem


def test_recusas_antigas_continuam_com_a_mesma_mensagem():
    """As travas de antes vêm primeiro: SECRET_KEY curta continua dizendo SECRET_KEY,
    mesmo com a DEK também ausente."""
    mensagem = _recusa(SECRET_KEY="curta", DATA_ENCRYPTION_KEY="")
    assert "SECRET_KEY inseguro" in mensagem and "DATA_ENCRYPTION_KEY" not in mensagem


def test_producao_pelas_variaveis_de_ambiente(monkeypatch):
    """O caminho real (painel do Railway): variáveis de ambiente, CORS em array JSON."""
    sk = _chave("sk")
    monkeypatch.setenv("ENV", "producao")
    monkeypatch.setenv("SECRET_KEY", sk)
    monkeypatch.setenv("DATABASE_URL", _PG)
    with pytest.raises(RuntimeError, match="DATA_ENCRYPTION_KEY ausente"):
        Settings(_env_file=None)
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", _chave("dek"))
    monkeypatch.setenv("CORS_ORIGINS", '["https://www.constelaedu.com", "*"]')
    monkeypatch.setenv("DOCS_HABILITADOS", "true")
    with pytest.raises(RuntimeError) as erro:
        Settings(_env_file=None)
    assert "CORS_ORIGINS com curinga" in str(erro.value)
    assert "DOCS_HABILITADOS=true" in str(erro.value)
    assert sk not in str(erro.value)
    monkeypatch.delenv("CORS_ORIGINS")
    monkeypatch.delenv("DOCS_HABILITADOS")
    assert Settings(_env_file=None).em_producao


# --- Chaves de exemplo publicadas no repositório ----------------------------------

def _variantes(exemplo: str) -> list[str]:
    """O valor colado como está, com espaços nas pontas e com outra caixa."""
    return [exemplo, f"  {exemplo} ", exemplo.upper(), exemplo.lower()]


@pytest.mark.parametrize("exemplo", sorted(CHAVES_DE_EXEMPLO))
def test_producao_recusa_secret_key_de_exemplo(exemplo):
    for valor in _variantes(exemplo):
        mensagem = _recusa(SECRET_KEY=valor)
        assert "SECRET_KEY inseguro" in mensagem
        assert exemplo.casefold() not in mensagem.casefold()   # a mensagem não leva valor


@pytest.mark.parametrize("exemplo", sorted(CHAVES_DE_EXEMPLO))
def test_producao_recusa_dek_de_exemplo(exemplo):
    for valor in _variantes(exemplo):
        mensagem = _recusa(DATA_ENCRYPTION_KEY=valor)
        assert "DATA_ENCRYPTION_KEY de exemplo" in mensagem
        assert "ENV=producao" in mensagem
        assert exemplo.casefold() not in mensagem.casefold()


def test_producao_recusa_o_par_que_o_env_example_trazia():
    """O caminho `cp .env.example .env && docker compose up -d` (o compose roda com
    ENV=producao) com as duas chaves que o .env.example da raiz trazia: recusa, e a
    trava da SECRET_KEY vem primeiro, com a mensagem de sempre."""
    mensagem = _recusa(SECRET_KEY="gere-uma-chave-longa-e-aleatoria",
                       DATA_ENCRYPTION_KEY="gere-outra-chave-longa-e-aleatoria")
    assert "SECRET_KEY inseguro" in mensagem
    assert "gere-" not in mensagem


def test_chave_de_exemplo_nao_pega_chave_de_verdade():
    assert not chave_de_exemplo(secrets.token_urlsafe(48))
    assert not chave_de_exemplo("")
    assert not chave_de_exemplo(None)
    assert not chave_de_exemplo("gere-uma-chave-longa-e-aleatoria-" + secrets.token_urlsafe(32))
    assert _producao().em_producao       # chaves aleatórias continuam subindo


def test_dev_secret_key_de_exemplo_vira_efemera_e_dek_de_exemplo_avisa():
    """Em dev nada recusa: a SECRET_KEY de exemplo é trocada pela efêmera (nenhum JWT
    é assinado com texto público) e a DEK de exemplo vira aviso no log do boot."""
    with pytest.warns(UserWarning, match="efêmera"):
        s = Settings(_env_file=None, ENV="dev", SECRET_KEY="gere-uma-chave-longa-e-aleatoria",
                     DATA_ENCRYPTION_KEY="gere-outra-chave-longa-e-aleatoria")
    assert s.SECRET_KEY_EFEMERA is True and not chave_de_exemplo(s.SECRET_KEY)
    avisos = avisos_de_configuracao(s)
    assert [a for a in avisos if "DATA_ENCRYPTION_KEY de exemplo" in a]
    assert not [a for a in avisos if "gere-" in a]


_RE_CHAVE_NO_EXEMPLO = re.compile(r"^\s*#?\s*(SECRET_KEY|DATA_ENCRYPTION_KEY)\s*=(.*)$")
_ENV_EXAMPLES = {"raiz": PROJECT_ROOT / ".env.example", "backend": BASE_DIR / ".env.example"}


def _chaves_do_exemplo(arquivo) -> dict[str, list[str]]:
    """Os valores de SECRET_KEY e DATA_ENCRYPTION_KEY num .env.example, também os das
    linhas comentadas (quem copia o arquivo descomenta)."""
    achados: dict[str, list[str]] = {"SECRET_KEY": [], "DATA_ENCRYPTION_KEY": []}
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        casou = _RE_CHAVE_NO_EXEMPLO.match(linha)
        if casou:
            achados[casou.group(1)].append(casou.group(2).strip().strip("\"'"))
    return achados


@pytest.mark.parametrize("onde", sorted(_ENV_EXAMPLES))
def test_nenhuma_chave_dos_env_example_passa_na_producao(onde):
    """Mantém os .env.example e ``CHAVES_DE_EXEMPLO`` em sincronia: qualquer valor que
    um .env.example ofereça para as duas chaves (vazio ou de exemplo) recusa o boot de
    produção. Um valor de exemplo novo num deles reprova aqui até entrar na lista."""
    achados = _chaves_do_exemplo(_ENV_EXAMPLES[onde])
    assert achados["SECRET_KEY"] and achados["DATA_ENCRYPTION_KEY"], (
        f"o .env.example ({onde}) perdeu a linha de uma das chaves: ajuste este teste")
    for valor in achados["SECRET_KEY"]:
        assert "SECRET_KEY inseguro" in _recusa(SECRET_KEY=valor)
    for valor in achados["DATA_ENCRYPTION_KEY"]:
        mensagem = _recusa(DATA_ENCRYPTION_KEY=valor)
        assert ("DATA_ENCRYPTION_KEY ausente" in mensagem
                or "DATA_ENCRYPTION_KEY de exemplo" in mensagem)


def test_compose_exige_as_duas_chaves_e_o_env_example_da_raiz_as_traz_vazias():
    """Primeira barreira do `cp .env.example .env && docker compose up -d`: o compose
    roda com ENV=producao e exige as duas chaves com ${VAR:?...}, que só falha com
    valor ausente ou VAZIO. Por isso o .env.example da raiz as traz vazias: copiado sem
    editar, o compose nem sobe (e, se subisse, a trava do boot recusaria)."""
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert re.search(r"^\s*ENV:\s*producao\b", compose, re.MULTILINE)
    assert "${SECRET_KEY:?" in compose and "${DATA_ENCRYPTION_KEY:?" in compose
    assert _chaves_do_exemplo(_ENV_EXAMPLES["raiz"]) == {
        "SECRET_KEY": [""], "DATA_ENCRYPTION_KEY": [""]}


def test_env_example_do_backend_nao_liga_docs_e_processo_de_producao_forca_false():
    """O onboarding (docs/CONTINUIDADE.md) manda copiar o backend/.env.example para
    backend/.env e rodar a suíte. Com DOCS_HABILITADOS=true descomentado ali, todo teste
    de processo com ENV=producao (cwd=backend) recusava o boot pelo /docs. Agora o
    exemplo deixa o /docs desligado e ``ambiente`` força false em produção."""
    texto = _ENV_EXAMPLES["backend"].read_text(encoding="utf-8")
    assert not re.search(r"^\s*DOCS_HABILITADOS\s*=\s*(true|1|yes|on)\b", texto,
                         re.IGNORECASE | re.MULTILINE)
    assert ambiente(_PG, producao=True)["DOCS_HABILITADOS"] == "false"
    assert ambiente(_PG, producao=True, DOCS_HABILITADOS="true")["DOCS_HABILITADOS"] == "true"


@pytest.mark.parametrize("onde", sorted(_ENV_EXAMPLES))
def test_env_example_copiado_inteiro_com_env_producao_nao_sobe(onde):
    """O arquivo inteiro como .env, com ENV=producao (o que o compose faz): recusa já
    na SECRET_KEY."""
    with pytest.raises(RuntimeError, match="SECRET_KEY inseguro"):
        Settings(_env_file=_ENV_EXAMPLES[onde], ENV="producao", DATABASE_URL=_PG)


# --- Roteiros da documentação: seguir o passo a passo sobe ---------------------------
# Revisão de integração do e97 (config-cifra-quest, prova 3): o docs/STAGING.md §2b
# mandava subir o staging com ENV=producao sem DATA_ENCRYPTION_KEY, e o boot recusa
# desde a trava da DEK. O roteiro e as travas do boot têm de andar juntos.

_STAGING = PROJECT_ROOT / "docs" / "STAGING.md"
_FRONT_STAGING = "https://staging.exemplo.invalid"
# Valor FICTÍCIO para cada variável que o §2b manda definir sem dar o valor literal.
_FICTICIO_DO_STAGING = {
    "DATABASE_URL": lambda: _PG,
    "SECRET_KEY": lambda: _chave("sk-staging"),
    "DATA_ENCRYPTION_KEY": lambda: _chave("dek-staging"),
    "PUBLIC_BASE_URL": lambda: _FRONT_STAGING,
    "QUEST_BASE_URL": lambda: "https://quest-staging.exemplo.invalid",
    # O §2b manda pôr no CORS só a origem exata do front de staging (= PUBLIC_BASE_URL).
    "CORS_ORIGINS": lambda: [_FRONT_STAGING],
}
_RE_VARIAVEL_NO_ROTEIRO = re.compile(r"`([A-Z][A-Z0-9_]*)(?:=([^`\s]*))?`")


def _secao_staging(inicio: str, fim: str) -> str:
    return _STAGING.read_text(encoding="utf-8").split(inicio, 1)[1].split(fim, 1)[0]


def _variaveis_do_staging() -> dict[str, str | list[str]]:
    """As variáveis que o §2b do STAGING.md manda definir no serviço de staging, com o
    valor literal do roteiro (``ENV=producao``) ou um fictício."""
    secao = _secao_staging("### 2b.", "### 2c.")
    literais: dict[str, set[str]] = {}
    for nome, valor in _RE_VARIAVEL_NO_ROTEIRO.findall(secao):
        literais.setdefault(nome, set())
        if valor:
            literais[nome].add(valor)
    valores: dict[str, str | list[str]] = {}
    for nome, vistos in literais.items():
        assert len(vistos) <= 1, f"o §2b dá dois valores para {nome}: {sorted(vistos)}"
        if vistos:
            valores[nome] = vistos.pop()
        else:
            assert nome in _FICTICIO_DO_STAGING, (
                f"o §2b do STAGING.md passou a pedir {nome}: dê um valor fictício a ela "
                "em _FICTICIO_DO_STAGING")
            valores[nome] = _FICTICIO_DO_STAGING[nome]()
    return valores


def test_roteiro_do_staging_sobe_com_env_producao():
    """Quem monta o staging seguindo o §2b (ENV=producao) passa pelas travas do boot."""
    valores = _variaveis_do_staging()
    assert valores.get("ENV") == "producao"
    s = Settings(_env_file=None, **valores)       # não pode levantar
    assert {"DATABASE_URL", "SECRET_KEY", "DATA_ENCRYPTION_KEY"} <= set(valores)
    assert s.em_producao and s.riscos_de_producao() == []
    assert s.SYNC_SCHEDULER_ENABLED is False      # o staging não coleta dados reais


def test_roteiro_do_staging_sem_a_dek_seria_recusado():
    """Controle: a linha da DEK no §2b é o que faz o roteiro subir (sem ela, a recusa
    que o achado reproduziu)."""
    valores = _variaveis_do_staging()
    valores.pop("DATA_ENCRYPTION_KEY")
    with pytest.raises(RuntimeError, match="DATA_ENCRYPTION_KEY ausente"):
        Settings(_env_file=None, **valores)


# 2ª revisão de integração do e97 (dados-config 3): o roteiro do §2b subia o staging,
# mas, com ENV=producao e sem CORS_ORIGINS, o CORS ficava no padrão de PRODUÇÃO e o
# navegador barrava o próprio front de staging (inclusive o login). O §2b passou a
# exigir CORS_ORIGINS com a origem exata do front de staging, e o §2c explica que os
# Previews por PR não falam com o backend de staging.

def _preflight_com_o_cors_do_main(origens: list[str], origem: str):
    """Preflight do login num CORSMiddleware com os MESMOS parâmetros do ``app.main``,
    trocando só as origens (as do Settings montado pelo roteiro)."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.testclient import TestClient

    from app.main import app as app_real

    cors = next(m for m in app_real.user_middleware if m.cls is CORSMiddleware)
    app = FastAPI()
    app.add_middleware(CORSMiddleware, **{**cors.kwargs, "allow_origins": origens})

    @app.post("/api/v1/auth/login")
    def _login():
        return {"ok": True}

    return TestClient(app).options("/api/v1/auth/login", headers={
        "Origin": origem, "Access-Control-Request-Method": "POST"})


def test_roteiro_do_staging_libera_o_proprio_front_no_cors():
    item = _secao_staging("### 2b.", "### 2c.").split("`CORS_ORIGINS`", 1)[1]
    assert "Obrigatória no staging" in item.split("\n   - ", 1)[0]
    valores = _variaveis_do_staging()
    assert valores["CORS_ORIGINS"] == [_FRONT_STAGING]
    s = Settings(_env_file=None, **valores)       # sem recusa
    assert s.em_producao and s.riscos_de_producao() == []
    assert _FRONT_STAGING in s.CORS_ORIGINS
    r = _preflight_com_o_cors_do_main(s.CORS_ORIGINS, _FRONT_STAGING)
    assert r.status_code == 200, r.text
    assert r.headers.get("access-control-allow-origin") == _FRONT_STAGING


def test_roteiro_do_staging_sem_cors_barraria_o_proprio_front():
    """Controle (a prova do achado, invertida): sem a linha do CORS_ORIGINS o boot sobe
    (era só isso que o teste do roteiro olhava), mas o CORS é o padrão de produção e o
    preflight do front de staging volta sem Access-Control-Allow-Origin."""
    valores = _variaveis_do_staging()
    valores.pop("CORS_ORIGINS")
    s = Settings(_env_file=None, **valores)
    assert s.riscos_de_producao() == []
    assert _FRONT_STAGING not in s.CORS_ORIGINS
    r = _preflight_com_o_cors_do_main(s.CORS_ORIGINS, _FRONT_STAGING)
    assert "access-control-allow-origin" not in r.headers


def test_exemplo_de_cors_do_roteiro_e_array_json_que_o_boot_aceita(monkeypatch):
    """O exemplo do §2b, colado como variável de ambiente (como no Railway), vira a
    lista de origens sem recusa: array JSON de origens https, sem barra no fim, sem
    caminho e sem '*'."""
    item = _secao_staging("### 2b.", "### 2c.").split("`CORS_ORIGINS`", 1)[1]
    item = item.split("\n   - ", 1)[0]
    exemplos = re.findall(r"`(\[[^`]*\])`", item)
    assert len(exemplos) == 1, exemplos
    origens = json.loads(exemplos[0])
    assert origens and all(isinstance(o, str) for o in origens)
    for origem in origens:
        partes = urlsplit(origem)
        assert partes.scheme == "https" and partes.netloc and "*" not in origem
        assert partes.path == "" and not partes.query
    valores = _variaveis_do_staging()
    valores.pop("CORS_ORIGINS")
    monkeypatch.setenv("CORS_ORIGINS", exemplos[0])
    s = Settings(_env_file=None, **valores)
    assert s.CORS_ORIGINS == origens and s.riscos_de_producao() == []


def test_staging_explica_que_preview_por_pr_nao_fala_com_o_backend():
    secao = _secao_staging("### 2c.", "## 3.")
    assert "Previews por PR não falam com o backend de staging" in secao
    assert "CORS_ORIGINS" in secao
    checklist = [linha for linha in _secao_staging("## 5.", "## 6.").splitlines()
                 if linha.startswith("|")]
    assert any("CORS_ORIGINS" in linha and "sem `*`" in linha for linha in checklist)


def test_continuidade_nao_chama_a_dek_de_opcional():
    linhas = [linha for linha in (PROJECT_ROOT / "docs" / "CONTINUIDADE.md").read_text(
        encoding="utf-8").splitlines() if linha.startswith("| `DATA_ENCRYPTION_KEY`")]
    assert len(linhas) == 1
    assert "opcional" not in linhas[0].lower()
    assert "obrigatória com `ENV=producao`" in linhas[0]


def _linha_do_inventario(inventario: str, servico: str) -> str:
    """A linha do inventário do §2 cuja coluna "Acesso / Serviço" cita ``servico``."""
    linhas = [linha for linha in inventario.splitlines()
              if linha.startswith("|") and servico in linha.split("|")[2]]
    assert len(linhas) == 1, (servico, linhas)
    return linhas[0]


def test_continuidade_poe_a_dek_no_inventario_do_cofre(monkeypatch):
    """2ª revisão de integração do e97 (dados-config 4): o §2 (o que vai para o cofre na
    sucessão) não listava a DATA_ENCRYPTION_KEY e dizia que a chave das credenciais "vem
    da SECRET_KEY" e que bastava transferir a SECRET_KEY. Com a DEK obrigatória, quem
    seguisse o plano perdia todas as credenciais das escolas."""
    texto = (PROJECT_ROOT / "docs" / "CONTINUIDADE.md").read_text(encoding="utf-8")
    inventario = texto.split("## 2.", 1)[1].split("## 3.", 1)[0]
    dek = _linha_do_inventario(inventario, "DATA_ENCRYPTION_KEY")
    assert "Cofre" in dek and "obrigatória" in dek and "ilegíveis" in dek
    assert "DATA_ENCRYPTION_KEYS_ANTERIORES" in dek
    assert "python -m scripts.recifrar_segredos --executar" in dek
    assert "a chave vem da SECRET_KEY" not in inventario
    assert "mas a SECRET_KEY sim" not in inventario
    credenciais = _linha_do_inventario(inventario, "Credenciais Matific/Elefante")
    assert "DATA_ENCRYPTION_KEY" in credenciais
    secret_key = _linha_do_inventario(inventario, "SECRET_KEY")
    assert "antes de rotacionar" in secret_key
    assert "CHAVE_CIFRA_LEGADA_ANTERIOR" in secret_key and "recifrar_segredos" in secret_key

    # O porquê, no código: a credencial cifrada hoje (SECRET_KEY + DEK) só abre com a DEK.
    from app.core import security
    from app.core.config import settings

    monkeypatch.setattr(settings, "SECRET_KEY", _chave("sk"))
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", _chave("dek"))
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEYS_ANTERIORES", "")
    monkeypatch.setattr(settings, "CHAVE_CIFRA_LEGADA_ANTERIOR", "")
    cifra = security.cifrar_segredo('{"usuario": "ficticio", "senha": "ficticia"}')
    assert security.decifrar_segredo(cifra) is not None
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", "")   # cofre só com a SECRET_KEY
    assert security.situacao_da_cifra(cifra) == security.CIFRA_ILEGIVEL


# --- Em dev: só aviso no log ------------------------------------------------------

def test_dev_nao_recusa_e_avisa_cada_risco_sem_valor(caplog):
    sk = _chave("sk")
    s = Settings(_env_file=None, ENV="dev", SECRET_KEY=sk, DATA_ENCRYPTION_KEY=sk,
                 CORS_ORIGINS=["*"], DOCS_HABILITADOS=True)
    avisos = avisos_de_configuracao(s)
    assert len(avisos) == 3
    assert all("ENV=producao recusaria" in a for a in avisos)
    logger = logging.getLogger("constela.teste_config")
    with caplog.at_level(logging.WARNING, logger="constela.teste_config"):
        assert registrar_avisos_de_configuracao(logger, s) == 3
    texto = caplog.text
    for trecho in ("DATA_ENCRYPTION_KEY igual à SECRET_KEY", "CORS_ORIGINS com curinga",
                   "DOCS_HABILITADOS=true"):
        assert trecho in texto
    assert sk not in texto
    assert all(r.levelno == logging.WARNING for r in caplog.records)


def _dev(**extra) -> Settings:
    valores = {"_env_file": None, "ENV": "dev", "SECRET_KEY": _chave("sk"),
               "DATA_ENCRYPTION_KEY": _chave("dek")}
    valores.update(extra)
    return Settings(**valores)


@pytest.mark.parametrize("valor", ["producao", "PRODUCAO", "producao ", " producao",
                                   "produção", "Produção ", "production", "prod", "PROD\t"])
def test_env_de_producao_com_espaco_acento_ou_caixa_liga_as_travas(valor):
    """Um espaço colado no painel ou o acento ('produção') desligavam em silêncio todas
    as travas: o ENV agora é comparado sem espaços nas pontas, caixa e acento."""
    assert _producao(ENV=valor).em_producao
    assert "DATA_ENCRYPTION_KEY ausente" in _recusa(ENV=valor, DATA_ENCRYPTION_KEY="")


@pytest.mark.parametrize("valor", ["dev", "DEV", " dev ", "development", "desenvolvimento",
                                   "local", "test", "teste"])
def test_env_de_dev_reconhecido_nao_avisa(valor):
    s = _dev(ENV=valor)
    assert not s.em_producao and avisos_de_configuracao(s) == []


@pytest.mark.parametrize("valor", ["staging", "homologacao", "prd", "producao-x", ""])
def test_env_nao_reconhecido_roda_como_dev_e_o_log_avisa(valor):
    """Nem dev nem produção: o app segue em modo dev (como sempre), mas o boot diz que
    nenhuma trava de produção vale — sem escrever o valor."""
    s = _dev(ENV=valor)
    assert not s.em_producao
    avisos = avisos_de_configuracao(s)
    assert len(avisos) == 1 and "ENV com valor não reconhecido" in avisos[0]
    assert not valor or valor not in avisos[0]


def test_metrics_publico_avisa_em_dev_e_e_ignorado_em_producao():
    """A produção roda em dev até o passo 2: um METRICS_PUBLICO=true esquecido no painel
    abriria o /metrics, e o boot não dizia nada."""
    avisos = avisos_de_configuracao(_dev(METRICS_PUBLICO=True))
    assert len(avisos) == 1 and "METRICS_PUBLICO=true" in avisos[0]
    assert avisos_de_configuracao(_producao(METRICS_PUBLICO=True)) == []


def test_dev_sem_dek_avisa_e_configuracao_completa_nao_avisa():
    s = Settings(_env_file=None, ENV="dev", SECRET_KEY=_chave("sk"))
    assert [a for a in avisos_de_configuracao(s) if "DATA_ENCRYPTION_KEY ausente" in a]
    completa = Settings(_env_file=None, ENV="dev", SECRET_KEY=_chave("sk"),
                        DATA_ENCRYPTION_KEY=_chave("dek"))
    assert avisos_de_configuracao(completa) == []


# --- Boot de verdade (processo novo, como o uvicorn) ------------------------------

_IMPORTAR = BOOT + "from app.main import app\nprint('APP_IMPORTADO')\n"


def test_processo_de_producao_sem_dek_nao_sobe_e_nao_mostra_segredo():
    """O import de app.main recusa ANTES de abrir o banco: o deploy reprova e o
    anterior segue no ar. A saída não leva a SECRET_KEY."""
    env = ambiente(_PG, producao=True, DATA_ENCRYPTION_KEY="")
    p = rodar(_IMPORTAR, env, timeout=120)
    saida = p.stdout + p.stderr
    assert p.returncode != 0 and "APP_IMPORTADO" not in p.stdout
    assert "DATA_ENCRYPTION_KEY ausente" in saida
    assert env["SECRET_KEY"] not in saida


def test_processo_de_producao_com_as_chaves_de_exemplo_nao_sobe():
    """O boot de verdade com as duas chaves que o .env.example da raiz trazia: o import
    recusa e a saída não leva nenhuma das duas."""
    env = ambiente(_PG, producao=True, SECRET_KEY="gere-uma-chave-longa-e-aleatoria",
                   DATA_ENCRYPTION_KEY="gere-outra-chave-longa-e-aleatoria")
    p = rodar(_IMPORTAR, env, timeout=120)
    saida = p.stdout + p.stderr
    assert p.returncode != 0 and "APP_IMPORTADO" not in p.stdout
    assert "SECRET_KEY inseguro" in saida
    assert "gere-uma-chave" not in saida and "gere-outra-chave" not in saida


def test_processo_de_producao_com_docs_nao_sobe():
    env = ambiente(_PG, producao=True, DOCS_HABILITADOS="true")
    p = rodar(_IMPORTAR, env, timeout=120)
    assert p.returncode != 0 and "APP_IMPORTADO" not in p.stdout
    assert "DOCS_HABILITADOS=true" in p.stderr
    assert env["DATA_ENCRYPTION_KEY"] not in p.stdout + p.stderr


def test_processo_de_dev_sobe_e_o_log_avisa(sqlite_url):
    """Em dev (a produção de hoje) o boot segue; o log JSON diz o que a produção
    recusaria."""
    r = sondar(sqlite_url, producao=False, DOCS_HABILITADOS="true",
               CORS_ORIGINS='["*"]')
    assert r["live"] == 200
    assert "o ENV=producao recusaria o boot" in r["_log"]
    assert "DOCS_HABILITADOS=true" in r["_log"] and "CORS_ORIGINS com curinga" in r["_log"]


# --- DATABASE_URL malformada: a recusa não ecoa a senha ---------------------------
# Sem o '@' entre senha e host, ou com espaço antes do esquema, o SQLAlchemy levanta um
# erro com o TEXTO da URL (senha junto) no import de app.core.database, antes do logging
# do app: o traceback cru ia para o log do deploy. Senha FICTÍCIA e host .invalid.
_MARCA_SENHA = "SenhaFicticiaQz7Lw2"
_URLS_MALFORMADAS = {
    "sem_arroba": f"postgresql+psycopg://u:{_MARCA_SENHA}h.exemplo.invalid:5432/d",
    "espaco_inicial": f" postgresql+psycopg://u:{_MARCA_SENHA}@h.exemplo.invalid:5432/d",
}


@pytest.mark.parametrize("producao", [False, True], ids=["dev", "producao"])
@pytest.mark.parametrize("caso", sorted(_URLS_MALFORMADAS))
def test_database_url_malformada_recusa_sem_mostrar_a_senha(caso, producao):
    """Em qualquer ENV (a produção roda sem ENV): RuntimeError com a orientação, sem a
    senha no texto nem no traceback, e sem a exceção original encadeada."""
    valores = {"_env_file": None, "DATABASE_URL": _URLS_MALFORMADAS[caso],
               "SECRET_KEY": _chave("sk"), "DATA_ENCRYPTION_KEY": _chave("dek")}
    if producao:
        valores["ENV"] = "producao"
    with pytest.raises(RuntimeError) as erro:
        Settings(**valores)
    texto = "".join(traceback.format_exception(erro.value))
    assert "DATABASE_URL malformada" in texto
    assert _MARCA_SENHA not in texto
    assert erro.value.__cause__ is None and erro.value.__context__ is None


@pytest.mark.parametrize("url", [
    _PG,
    "postgresql+psycopg://u:Fict%40cia%23Zq9@h.exemplo.invalid:6543/postgres",
    "postgresql+psycopg://u:SenhaFicticia@h.exemplo.invalid:5432/d?sslmode=require",
    "sqlite://",
    "sqlite:///:memory:",
])
def test_database_url_bem_formada_continua_aceita(url):
    """Controle: as formas que o app usa (PostgreSQL com senha percent-codificada e
    parâmetros, SQLite) passam pela trava."""
    assert _dev(DATABASE_URL=url).DATABASE_URL == url


@pytest.mark.parametrize("caso", sorted(_URLS_MALFORMADAS))
def test_processo_com_database_url_malformada_nao_sobe_e_nao_mostra_a_senha(caso):
    """O boot de verdade, nos dois caminhos do deploy: o import de app.main em dev (a
    produção de hoje) e o pre-deploy (scripts.migrate) com ENV=producao. Os dois saem
    com erro, e a saída inteira não tem a senha."""
    url = _URLS_MALFORMADAS[caso]
    for codigo, producao in ((_IMPORTAR, False), (MIGRAR, True)):
        p = rodar(codigo, ambiente(url, producao), timeout=120)
        saida = p.stdout + p.stderr
        assert p.returncode != 0 and "APP_IMPORTADO" not in p.stdout
        assert "DATABASE_URL malformada" in saida, saida[-2000:].replace(_MARCA_SENHA, "<s>")
        assert _MARCA_SENHA not in saida


# --- SECRET_KEY só de espaços/tabs/quebras de linha ------------------------------
# A trava contava os brancos no len(): 40 espaços passavam como chave de 40 caracteres
# e o JWT forjado com a chave em branco valia. A DEK só de espaços já era recusada.
_SECRET_KEYS_EM_BRANCO = [" " * 40, "\n" * 32, "\t \r\n" * 10, " " * 20 + "x" * 12]


@pytest.mark.parametrize("sk", _SECRET_KEYS_EM_BRANCO,
                         ids=["espacos", "quebras", "misto", "12_visiveis"])
def test_producao_recusa_secret_key_em_branco(sk):
    mensagem = _recusa(SECRET_KEY=sk)
    assert "SECRET_KEY com menos de 32 caracteres além de espaços" in mensagem
    assert "x" * 12 not in mensagem                      # a mensagem não leva o valor


@pytest.mark.parametrize("sk", _SECRET_KEYS_EM_BRANCO,
                         ids=["espacos", "quebras", "misto", "12_visiveis"])
def test_dev_secret_key_em_branco_avisa_e_fica_como_esta(sk):
    """Em dev (a produção de hoje) a chave não é trocada — trocá-la derrubaria as
    sessões e as cifras legadas —, mas o boot avisa o que o ENV=producao recusaria."""
    s = _dev(SECRET_KEY=sk)
    assert s.SECRET_KEY == sk and s.SECRET_KEY_EFEMERA is False
    assert [r for r in s.riscos_de_producao() if "SECRET_KEY com menos de 32" in r]
    assert [a for a in avisos_de_configuracao(s) if "SECRET_KEY com menos de 32" in a]


def test_secret_key_de_verdade_com_espacos_nas_pontas_nao_e_risco():
    """Controle: 32+ caracteres visíveis passam, mesmo com espaço colado nas pontas."""
    s = _producao(SECRET_KEY=f"  {_chave('sk')} ")
    assert s.riscos_de_producao() == []
