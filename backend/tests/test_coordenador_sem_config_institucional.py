"""A coordenação NÃO altera configuração institucional — nem por chamada direta
à API (a tela esconder não basta).

Institucional = o que identifica a escola/cidade nos documentos e a operação de
administrador: cor primária, brasão da cidade e logo da prefeitura, dados
cadastrais da escola, provedor de IA, backup e restauração. As fórmulas
oficiais (pesos, referências, régua) já são travadas para quem não é Admin
Global em ``test_governanca_formula.py``.

Para cada rota: a coordenação recebe 403 e NADA muda (a leitura seguinte devolve
o mesmo); o administrador da escola, com o MESMO corpo, passa — prova de que o
403 vem do papel, não de validação. O que é da coordenação por desenho (editar
as medalhas) segue liberado.
"""
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.security import hash_senha
from app.main import app
from app.models import Escola, Usuario

API = "/api/v1"


def _login(email: str) -> TestClient:
    c = TestClient(app)
    r = c.post(f"{API}/auth/login", data={"username": email, "password": "s3nh4"})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


@pytest.fixture()
def coordenacao(db, escola_completa) -> TestClient:
    db.add(Usuario(escola_id=escola_completa["escola"].id, nome="Coordenacao",
                   email="coord@institucional.local", senha_hash=hash_senha("s3nh4"),
                   cargo="coordenador"))
    db.commit()
    return _login("coord@institucional.local")


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (8, 8), (10, 20, 30, 255)).save(buf, format="PNG")
    return buf.getvalue()


def test_cor_primaria(cliente, coordenacao, escola_completa):
    url = f"{API}/escolas/{escola_completa['escola'].id}/aparencia"
    antes = coordenacao.get(url).json()
    corpo = {"cor_primaria": "#AA0000", "mostrar_fotos": True}
    assert coordenacao.put(url, json=corpo).status_code == 403
    assert coordenacao.get(url).json() == antes
    assert cliente.put(url, json=corpo).status_code == 200          # admin da escola


@pytest.mark.parametrize("tipo", ["brasao", "prefeitura"])
def test_brasao_e_logo_da_prefeitura(cliente, coordenacao, escola_completa, tipo):
    escola_id = escola_completa["escola"].id
    url = f"{API}/escolas/{escola_id}/aparencia/logo?tipo={tipo}"
    arquivo = {"arquivo": ("logo.png", _png(), "image/png")}
    assert coordenacao.post(url, files=arquivo).status_code == 403
    assert coordenacao.get(f"{API}/escolas/{escola_id}/aparencia").json()[
        f"{tipo}_data_uri"] == ""
    assert cliente.post(url, files={"arquivo": ("logo.png", _png(), "image/png")}
                        ).status_code == 200
    assert coordenacao.delete(url).status_code == 403
    assert coordenacao.get(f"{API}/escolas/{escola_id}/aparencia").json()[
        f"{tipo}_data_uri"] != ""


def test_dados_cadastrais_da_escola(cliente, coordenacao, db, escola_completa):
    escola = escola_completa["escola"]
    url = f"{API}/escolas/{escola.id}"
    for corpo in ({"nome": "OUTRO NOME"}, {"cidade": "Outra"}, {"status": "inativa"}):
        assert coordenacao.patch(url, json=corpo).status_code == 403, corpo
    db.expire_all()
    atual = db.get(Escola, escola.id)
    assert (atual.nome, atual.status) == ("ESCOLA TESTE", "ativa")
    assert cliente.patch(url, json={"cidade": "Caraguatatuba"}).status_code == 200


def test_provedor_de_ia(cliente, coordenacao, escola_completa):
    url = f"{API}/escolas/{escola_completa['escola'].id}/assistente/config"
    corpo = {"provedor": "local"}
    assert coordenacao.put(url, json=corpo).status_code == 403
    assert cliente.put(url, json=corpo).status_code == 200


def test_backup_e_restauracao(coordenacao, escola_completa):
    escola_id = escola_completa["escola"].id
    assert coordenacao.get(f"{API}/escolas/{escola_id}/backup").status_code == 403
    r = coordenacao.post(f"{API}/escolas/{escola_id}/restaurar",
                         files={"arquivo": ("b.json", b"{}", "application/json")})
    assert r.status_code == 403


def test_medalhas_continuam_com_a_coordenacao(coordenacao, escola_completa):
    """O que é da coordenação por desenho segue liberado: editar as conquistas."""
    url = f"{API}/escolas/{escola_completa['escola'].id}/gamificacao/conquistas/definicoes"
    r = coordenacao.get(url)
    assert r.status_code == 200, r.text
