"""Testes da Fase 5 — Painel Público sem login, restrito a dados pedagógicos."""
from app.models import Importacao, SnapshotMatific
from app.services import scoring


def _ativar_painel(cliente, escola_id: int) -> str:
    resposta = cliente.put(
        f"/api/v1/escolas/{escola_id}/painel-publico",
        json={"ativo": True, "slides": ["ranking", "destaques"],
              "intervalo_s": 8, "max_posicoes": 5},
    )
    assert resposta.status_code == 200, resposta.text
    url = resposta.json()["url"]
    assert url is not None
    # Regressão: sem PUBLIC_BASE_URL no ambiente, o link deve apontar para o
    # site publicado — nunca para "localhost", que não abre em outro aparelho.
    assert "localhost" not in url
    return url.rsplit("/", 1)[-1]  # token


def _com_notas(db, escola_completa):
    escola = escola_completa["escola"]
    importacao = Importacao(escola_id=escola.id, plataforma="matific", tipo="seed")
    db.add(importacao)
    db.flush()
    for indice, aluno in enumerate(escola_completa["alunos"]):
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id,
                               importacao_id=importacao.id,
                               atividades=10 * (indice + 1), estrelas=20,
                               pontuacao_media=70))
    db.commit()
    scoring.recalcular_escola(db, escola.id)


def test_painel_desativado_retorna_404(cliente, db, escola_completa):
    resposta = cliente.get("/api/v1/publico/token-inexistente/painel")
    assert resposta.status_code == 404


def test_painel_publico_sem_login(cliente, db, escola_completa):
    _com_notas(db, escola_completa)
    token = _ativar_painel(cliente, escola_completa["escola"].id)

    from fastapi.testclient import TestClient
    from app.main import app
    anonimo = TestClient(app)  # sem Authorization
    resposta = anonimo.get(f"/api/v1/publico/{token}/painel")
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["escola"]["nome"] == "ESCOLA TESTE"
    assert corpo["slides"] == ["ranking", "destaques"]
    assert corpo["intervalo_s"] == 8
    assert len(corpo["ranking"]) == 3
    # Somente campos pedagógicos no ranking público
    assert set(corpo["ranking"][0].keys()) == {
        "posicao", "aluno_id", "nome", "turma", "nota_geral"}


def test_max_posicoes_limita_o_ranking(cliente, db, escola_completa):
    _com_notas(db, escola_completa)
    escola_id = escola_completa["escola"].id
    cliente.put(
        f"/api/v1/escolas/{escola_id}/painel-publico",
        json={"ativo": True, "slides": ["ranking"], "intervalo_s": 10, "max_posicoes": 3},
    )
    token = cliente.get(f"/api/v1/escolas/{escola_id}/painel-publico").json()["url"].rsplit("/", 1)[-1]
    corpo = cliente.get(f"/api/v1/publico/{token}/painel").json()
    assert len(corpo["ranking"]) == 3


def test_perfil_publico_restrito_a_dados_pedagogicos(cliente, db, escola_completa):
    _com_notas(db, escola_completa)
    token = _ativar_painel(cliente, escola_completa["escola"].id)
    ana = escola_completa["alunos"][0]

    from fastapi.testclient import TestClient
    from app.main import app
    anonimo = TestClient(app)
    resposta = anonimo.get(f"/api/v1/publico/{token}/alunos/{ana.id}")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["nome"] == ana.nome
    assert "conquistas" in corpo
    # Nada de dados pessoais sensíveis (PRD §120)
    for campo in ("data_nascimento", "observacoes", "numero_chamada", "email", "foto_url"):
        assert campo not in corpo


def test_trocar_token_invalida_o_link_antigo(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    token_antigo = _ativar_painel(cliente, escola_id)
    assert cliente.get(f"/api/v1/publico/{token_antigo}/painel").status_code == 200

    novo = cliente.post(f"/api/v1/escolas/{escola_id}/painel-publico/novo-token")
    assert novo.status_code == 200
    token_novo = novo.json()["url"].rsplit("/", 1)[-1]
    assert token_novo != token_antigo
    assert cliente.get(f"/api/v1/publico/{token_antigo}/painel").status_code == 404
    assert cliente.get(f"/api/v1/publico/{token_novo}/painel").status_code == 200


def test_desativar_painel_bloqueia_acesso(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    token = _ativar_painel(cliente, escola_id)
    cliente.put(
        f"/api/v1/escolas/{escola_id}/painel-publico",
        json={"ativo": False, "slides": ["ranking"], "intervalo_s": 10, "max_posicoes": 10},
    )
    assert cliente.get(f"/api/v1/publico/{token}/painel").status_code == 404


def test_qr_code_svg(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    _ativar_painel(cliente, escola_id)
    resposta = cliente.get(f"/api/v1/escolas/{escola_id}/painel-publico/qr")
    assert resposta.status_code == 200
    assert resposta.headers["content-type"].startswith("image/svg")
    assert b"<svg" in resposta.content


def test_configuracao_exige_papel(cliente, db, escola_completa):
    from app.core.security import hash_senha
    from app.models import Usuario
    escola = escola_completa["escola"]
    db.add(Usuario(escola_id=escola.id, nome="Visitante", email="visita@teste.com.br",
                   senha_hash=hash_senha("s3nh4"), cargo="visitante"))
    db.commit()
    from fastapi.testclient import TestClient
    from app.main import app
    visitante = TestClient(app)
    login = visitante.post("/api/v1/auth/login",
                           data={"username": "visita@teste.com.br", "password": "s3nh4"})
    visitante.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    resposta = visitante.put(
        f"/api/v1/escolas/{escola.id}/painel-publico",
        json={"ativo": True, "slides": ["ranking"], "intervalo_s": 10, "max_posicoes": 10},
    )
    assert resposta.status_code == 403
