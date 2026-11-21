"""UPLOADS-8 (parte da administração): arquivo que não é um backup JSON válido
volta 400 com a mensagem da tela — nunca 500 "Erro interno". Um número inteiro
com mais dígitos do que o Python converte (limite de 4.300) levanta um
``ValueError`` comum no ``json.loads``, que não é ``JSONDecodeError``. Dados
fictícios."""
import pytest
from fastapi.testclient import TestClient

from app.main import app

MSG = "O arquivo não é um backup JSON válido."


def _restaurar(cliente_global, escola_id: int, corpo: bytes):
    c = TestClient(app, raise_server_exceptions=False)
    c.headers.update(cliente_global.headers)
    return c.post(f"/api/v1/escolas/{escola_id}/restaurar",
                  files={"arquivo": ("backup.json", corpo, "application/json")})


@pytest.mark.parametrize("corpo", [
    pytest.param(b'{"versao": 1, "tabelas": {}, "x": ' + b"9" * 5000 + b"}",
                 id="inteiro-de-5000-digitos"),
    pytest.param(b"[" * 100_000 + b"]" * 100_000, id="aninhamento-profundo"),
    pytest.param("{\"x\": \"ç\"}".encode("latin-1"), id="nao-utf8"),
    pytest.param(b"{nao e json", id="sintaxe"),
])
def test_backup_invalido_volta_400_com_mensagem(db, escola_completa, cliente_global, corpo):
    r = _restaurar(cliente_global, escola_completa["escola"].id, corpo)
    assert r.status_code == 400, r.text[:300]
    assert r.json()["detail"] == MSG
