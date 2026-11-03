"""Quest — portão das rotas do lado do aluno (QUEST_ALUNO_HABILITADO).

A auditoria de 20/10/2026 achou o login infantil ativo na API sem o app do aluno
publicado. Desativar é decisão do dono; aqui fica a configuração, com o padrão =
comportamento atual (ligado), e a prova de que desligada ela tira a superfície
inteira do aluno sem tocar no Edu (cartões do professor).
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.quest.config import config_quest

ROTAS_DO_ALUNO = [
    ("post", "/api/v1/quest/auth/quem", {"codigo": "SOL314"}),
    ("post", "/api/v1/quest/auth/entrar", {"codigo": "SOL314"}),
    ("post", "/api/v1/quest/auth/entrar-qr", {"qr_token": "x" * 24}),
    ("get", "/api/v1/quest/perfil", None),
    ("get", "/api/v1/quest/perfil/cores", None),
    ("get", "/api/v1/quest/conquistas", None),
]


def _chamar(metodo, url, corpo):
    cliente = TestClient(app)
    return cliente.post(url, json=corpo) if metodo == "post" else cliente.get(url)


def test_padrao_e_o_comportamento_atual():
    assert config_quest.QUEST_ALUNO_HABILITADO is True


@pytest.mark.parametrize("metodo,url,corpo", ROTAS_DO_ALUNO)
def test_desligado_responde_404_igual_rota_inexistente(db, monkeypatch, metodo, url, corpo):
    monkeypatch.setattr(config_quest, "QUEST_ALUNO_HABILITADO", False)
    r = _chamar(metodo, url, corpo)
    inexistente = TestClient(app).get("/api/v1/quest/rota-que-nao-existe")
    assert r.status_code == 404
    assert r.json() == inexistente.json()     # nada revela que o login está ali


def test_desligado_nao_toca_nos_cartoes_do_professor(cliente, db, escola_completa,
                                                    monkeypatch):
    monkeypatch.setattr(config_quest, "QUEST_ALUNO_HABILITADO", False)
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    r = cliente.post(f"/api/v1/escolas/{escola.id}/quest/turmas/{turma.id}/cartoes")
    assert r.status_code == 200, r.text
    assert r.content.startswith(b"%PDF")


def test_ligado_as_rotas_respondem(db):
    r = _chamar("post", "/api/v1/quest/auth/quem", {"codigo": "NAOEXISTE123"})
    assert r.status_code == 401                # existe e procurou o código
