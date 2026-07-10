"""Regressões de segurança pré-produção (auditoria de check-up)."""
import importlib

import pytest
from sqlalchemy import select

from app.core import config as config_mod
from app.core.rate_limit import limitador_login
from app.core.security import criar_token, validar_forca_senha
from app.models import LogAuditoria, Usuario


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    limitador_login._eventos.clear()
    yield
    limitador_login._eventos.clear()


# --- Política de senha --------------------------------------------------------

def test_politica_de_senha():
    assert validar_forca_senha("curta") is not None            # < 8
    assert validar_forca_senha("senha123") is not None         # comum
    assert validar_forca_senha("joao@escola.com.br", "joao@escola.com.br") is not None
    assert validar_forca_senha("Constela#Forte2026") is None


def test_criar_usuario_recusa_senha_fraca(cliente, escola_completa):
    escola = escola_completa["escola"]
    resposta = cliente.post(f"/api/v1/escolas/{escola.id}/usuarios", json={
        "nome": "Fraco Silva", "email": "fraco@escola.com.br",
        "senha": "12345678", "cargo": "professor"})
    assert resposta.status_code == 422


# --- Rate limiting e auditoria de login --------------------------------------

def test_login_bloqueia_forca_bruta(cliente, escola_completa):
    dados = {"username": "admin@teste.local", "password": "errada"}
    codigos = [cliente.post("/api/v1/auth/login", data=dados).status_code
               for _ in range(9)]
    assert codigos[:8] == [401] * 8      # 8 tentativas permitidas
    assert codigos[8] == 429             # a 9ª é bloqueada


def test_xff_forjado_nao_burla_o_limitador(cliente, escola_completa):
    """XFF forjado à ESQUERDA não cria buckets novos: com TRUSTED_PROXY_HOPS=1,
    o IP usado é o que o proxy APPENDA no fim (203.0.113.9). Variar o valor da
    esquerda (spoof) não zera o contador — a força-bruta ainda trava na 9ª."""
    dados = {"username": "admin@teste.local", "password": "errada"}
    codigos = [
        cliente.post("/api/v1/auth/login", data=dados,
                     headers={"X-Forwarded-For": f"9.9.9.{i}, 203.0.113.9"}).status_code
        for i in range(9)
    ]
    assert codigos[:8] == [401] * 8
    assert codigos[8] == 429   # o XFF variável NÃO burlou o limitador


def test_limitador_por_conta_bloqueia_mesmo_com_ips_diferentes(cliente, escola_completa):
    """20 falhas na MESMA conta, cada uma de um IP REAL diferente (rightmost),
    disparam o limitador POR CONTA (independente de IP) — defesa contra
    força-bruta distribuída que o limitador por (conta, IP) sozinho não pega."""
    dados = {"username": "admin@teste.local", "password": "errada"}
    codigos = [
        cliente.post("/api/v1/auth/login", data=dados,
                     headers={"X-Forwarded-For": f"203.0.113.{i}"}).status_code
        for i in range(22)
    ]
    # Cada IP é único -> o limitador por (conta,IP) nunca acumula (não trava).
    assert codigos[:20] == [401] * 20
    # ... mas o limitador POR CONTA acumula e bloqueia a partir da 21ª.
    assert codigos[20] == 429 and codigos[21] == 429


def test_login_falho_e_auditado(cliente, db, escola_completa):
    cliente.post("/api/v1/auth/login",
                 data={"username": "ninguem@escola.com.br", "password": "x"})
    log = db.execute(
        select(LogAuditoria).where(LogAuditoria.acao == "login.falhou")
        .order_by(LogAuditoria.id.desc())
    ).scalars().first()
    assert log is not None
    # "conta_inexistente": o login aceita e-mail OU nome de usuário.
    assert log.detalhes["motivo"] == "conta_inexistente"


# --- Invalidação de sessão ao trocar senha -----------------------------------

def test_troca_de_senha_invalida_sessoes(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    novo = cliente.post(f"/api/v1/escolas/{escola.id}/usuarios", json={
        "nome": "Rita Prof", "email": "rita@escola.com.br",
        "senha": "Constela#Forte2026", "cargo": "professor"}).json()

    # token válido do usuário recém-criado
    token = criar_token(novo["id"], 0)
    cabecalho = {"Authorization": f"Bearer {token}"}
    assert cliente.get("/api/v1/auth/me", headers=cabecalho).status_code == 200

    # admin redefine a senha -> token_version incrementa -> token antigo cai
    cliente.patch(f"/api/v1/escolas/{escola.id}/usuarios/{novo['id']}",
                  json={"senha": "OutraSenha#2026"})
    assert cliente.get("/api/v1/auth/me", headers=cabecalho).status_code == 401


# --- Autorização: criar escola é só de admin global --------------------------

def test_criar_escola_exige_admin_global(cliente, escola_completa):
    # admin local (fixture) não é global
    resposta = cliente.post("/api/v1/escolas",
                            json={"nome": "Escola Nova", "ano_letivo_ativo": 2026})
    assert resposta.status_code == 403
    assert "globais" in resposta.json()["detail"]


def test_escola_inexistente_da_404(cliente, escola_completa):
    resposta = cliente.get("/api/v1/escolas/99999/turmas")
    assert resposta.status_code in (403, 404)   # global→404, local→403 (isolamento)


# --- Fail-closed do SECRET_KEY em produção -----------------------------------

def test_secret_key_padrao_barra_producao(monkeypatch):
    monkeypatch.setenv("ENV", "producao")
    monkeypatch.setenv("SECRET_KEY", config_mod.SECRET_KEY_INSEGURA)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x:y@localhost/z")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        config_mod.Settings()


def test_sqlite_barra_producao(monkeypatch):
    monkeypatch.setenv("ENV", "producao")
    monkeypatch.setenv("SECRET_KEY", "x" * 48)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///efemero.db")
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        config_mod.Settings()


# --- Health check ------------------------------------------------------------

def test_health_checa_banco(cliente):
    resposta = cliente.get("/api/health")
    assert resposta.status_code == 200
    assert resposta.json()["status"] == "ok"


# --- Path traversal na confirmação de importação -----------------------------

def test_confirmar_recusa_token_malicioso(cliente, escola_completa):
    escola = escola_completa["escola"]
    for token in ("../../etc/passwd", "..%2f..%2fx.pdf", "arquivo.txt",
                  "/etc/shadow", "a" * 10 + ".pdf"):
        resposta = cliente.post(
            f"/api/v1/escolas/{escola.id}/importacoes/confirmar",
            json={"plataforma": "matific", "formato": "resumo", "tipo": "pdf",
                  "arquivo_token": token, "arquivo_nome": "x.pdf",
                  "linhas": [{"nome": "Ana Beatriz Souza",
                              "dados": {"atividades": 1}, "aluno_id": None}]})
        # token inválido é recusado antes de qualquer acesso a disco
        assert resposta.status_code == 400, (token, resposta.text)
