"""O .json do Placar do Matific (bookmarklet) que o ``json.loads`` não consegue ler
não vira 500: um aninhamento profundo demais levanta ``RecursionError`` (não
``ValueError``) e derrubava a prévia com "Erro interno". Segue como texto, como
qualquer outro JSON inválido. Dados fictícios."""
from fastapi.testclient import TestClient

from app.main import app
from app.routers.importacoes import _payload_matific_placar

_ANINHADO = ('{"fonte": "matific-placar", "alunos": [], "x": '
             + "[" * 200_000 + "]" * 200_000 + "}")


def test_payload_aninhado_demais_nao_e_placar():
    assert _payload_matific_placar(_ANINHADO) is None


def test_previa_do_placar_aninhado_nao_da_erro_interno(cliente, escola_completa):
    escola_id = escola_completa["escola"].id
    c = TestClient(app, raise_server_exceptions=False)
    c.headers.update(cliente.headers)
    r = c.post(f"/api/v1/escolas/{escola_id}/importacoes/analisar",
               files={"arquivo": ("placar.json", _ANINHADO.encode(), "application/json")})
    assert r.status_code < 500, r.text[:300]
