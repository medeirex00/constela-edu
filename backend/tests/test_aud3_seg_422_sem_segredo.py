"""O 422 de validação não devolve a senha (nem outro segredo) que a pessoa digitou
(REG_SEGURANCA-4).

O tratador global (``main._erro_de_validacao``) deixava no erro o ``input`` escalar
curto (texto de até 256 caracteres). A senha nova recusada pela política (curta ou
fraca) é um texto curto: voltava inteira, em claro, no corpo da resposta — também
na rota SEM login ``/auth/redefinir-senha``. As telas só usam o ``msg``. Agora o
``input`` sai quando o campo é um segredo (senha, código, token, chave de API...);
o resto do erro (onde e por quê) continua igual.

Dados fictícios.
"""
import asyncio
import json

from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from starlette.requests import Request

from app import main
from app.main import app

API = "/api/v1"
SENHA_CURTA = "Maria26"            # curta demais (7): a senha que a pessoa queria (fictícia)
SENHA_FRACA = "constelaedu"        # tamanho certo, recusada por ser comum (fictícia)


def _erro_do_campo(r, campo: str) -> dict:
    por_campo = {e["loc"][-1]: e for e in r.json()["detail"]}
    return por_campo[campo]


def test_redefinir_senha_sem_login_nao_devolve_a_senha(db, escola_completa):
    r = TestClient(app).post(f"{API}/auth/redefinir-senha",
                             json={"token": "token-ficticio-123", "nova_senha": SENHA_CURTA})
    assert r.status_code == 422
    assert SENHA_CURTA not in r.text, f"o 422 devolveu a senha digitada em claro: {r.text}"
    erro = _erro_do_campo(r, "nova_senha")
    assert "input" not in erro
    # O erro continua dizendo onde e por quê.
    assert erro["loc"] == ["body", "nova_senha"] and erro["type"] == "string_too_short"
    assert erro["msg"]


def test_troca_da_propria_senha_nao_devolve_a_senha(cliente, escola_completa):
    admin = escola_completa["admin"]
    r = cliente.patch(f"{API}/escolas/{escola_completa['escola'].id}/usuarios/{admin.id}",
                      json={"senha": SENHA_CURTA, "senha_atual": "s3nh4"})
    assert r.status_code == 422
    assert SENHA_CURTA not in r.text, f"o 422 devolveu a senha digitada em claro: {r.text}"
    assert "s3nh4" not in r.text


def test_senha_fraca_recusada_pelo_validador_nao_volta(cliente, escola_completa):
    """A recusa pela força (``validar_forca_senha`` no ``field_validator``)."""
    r = cliente.post(f"{API}/escolas/{escola_completa['escola'].id}/usuarios",
                     json={"nome": "Professora Ficticia", "email": "prof.ficticia@constela-sint.com.br",
                           "senha": SENHA_FRACA, "cargo": "professor"})
    assert r.status_code == 422, r.text
    assert SENHA_FRACA not in r.text, f"o 422 devolveu a senha digitada em claro: {r.text}"
    assert _erro_do_campo(r, "senha")["msg"]


def test_codigo_do_quest_nao_volta(db):
    """O código do cartão do Quest é a credencial da criança."""
    r = TestClient(app).post(f"{API}/quest/auth/entrar", json={"codigo": "Z9"})
    assert r.status_code == 422
    assert "input" not in _erro_do_campo(r, "codigo")


def _responder(erros: list[dict]) -> dict:
    pedido = Request({"type": "http", "method": "POST", "path": "/x", "headers": []})
    resposta = asyncio.run(main._erro_de_validacao(pedido, RequestValidationError(erros)))
    assert resposta.status_code == 422
    return json.loads(resposta.body)


def test_input_de_campo_secreto_sai_e_o_dos_outros_fica():
    erros = [
        {"type": "t", "loc": ("body", "senha"), "msg": "m", "input": "s1"},
        {"type": "t", "loc": ("body", "senha_atual"), "msg": "m", "input": "s2"},
        {"type": "t", "loc": ("body", "nova_senha"), "msg": "m", "input": "s3"},
        {"type": "t", "loc": ("body", "password"), "msg": "m", "input": "s4"},
        {"type": "t", "loc": ("body", "token"), "msg": "m", "input": "s5"},
        {"type": "t", "loc": ("body", "qr_token"), "msg": "m", "input": "s6"},
        {"type": "t", "loc": ("body", "codigo"), "msg": "m", "input": "s7"},
        {"type": "t", "loc": ("body", "api_key"), "msg": "m", "input": "s8"},
        {"type": "t", "loc": ("body", "token_push"), "msg": "m", "input": "s9"},
        {"type": "t", "loc": ("body", "credenciais", "senha"), "msg": "m", "input": "s10"},
        {"type": "t", "loc": ("body", "Senha"), "msg": "m", "input": "s11"},
        {"type": "t", "loc": ("body", "senhas", 0), "msg": "m", "input": "s12"},
        {"type": "t", "loc": ("cookie", "sessao"), "msg": "m", "input": "s13"},
        {"type": "t", "loc": ("body", "nome"), "msg": "m", "input": "curto"},
        {"type": "t", "loc": ("body", "ids", 3), "msg": "m", "input": "x"},
        {"type": "t", "loc": ("query", "limite"), "msg": "m", "input": 7},
    ]
    detalhe = _responder(erros)["detail"]
    assert len(detalhe) == len(erros)                   # nenhum erro some
    com_input = {tuple(e["loc"]): e["input"] for e in detalhe if "input" in e}
    assert com_input == {("body", "nome"): "curto", ("body", "ids", 3): "x",
                         ("query", "limite"): 7}
