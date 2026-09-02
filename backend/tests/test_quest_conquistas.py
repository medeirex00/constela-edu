"""Minhas Conquistas do ALUNO (Quest) — endpoint SELF.

Trava as regras de segurança do prompt: o aluno lista SÓ as próprias conquistas
(aluno_id vem da SESSÃO, não do cliente → sem IDOR), o backend é a fonte da
verdade (só GET, read-only — o aluno não concede/edita nada), e a descrição/
progresso/estado (desbloqueada × em andamento) chegam prontos.
"""
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.quest.models import QuestCredencialAluno


def _login_aluno(cliente, db, escola_completa, indice=0) -> TestClient:
    escola = escola_completa["escola"]
    turma = escola_completa["turma"]
    cliente.post(f"/api/v1/escolas/{escola.id}/quest/turmas/{turma.id}"
                 "/cartoes?regenerar=false")
    db.expire_all()
    cred = db.execute(
        select(QuestCredencialAluno).where(
            QuestCredencialAluno.aluno_id == escola_completa["alunos"][indice].id)
    ).scalar_one()
    token = TestClient(app).post(
        "/api/v1/quest/auth/entrar", json={"codigo": cred.codigo_login}
    ).json()["access_token"]
    c = TestClient(app)
    c.headers["Authorization"] = f"Bearer {token}"
    return c


def test_aluno_lista_as_proprias_conquistas_com_descricao_e_progresso(db, cliente, escola_completa):
    aluno0 = escola_completa["alunos"][0]
    c = _login_aluno(cliente, db, escola_completa, indice=0)
    r = c.get("/api/v1/quest/conquistas")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["aluno_id"] == aluno0.id
    conquistas = corpo["conquistas"]
    assert isinstance(conquistas, list) and conquistas
    exemplo = conquistas[0]
    # descrição/nome/ícone prontos (nada de "ACH_007"); progresso e estado presentes
    assert exemplo["nome"] and exemplo["descricao"]
    assert "progresso" in exemplo and "pct" in exemplo and "atingida" in exemplo
    # conquista BLOQUEADA (em andamento) aparece — o aluno começa sem tudo desbloqueado
    assert any(not con["atingida"] for con in conquistas)


def test_aluno_id_vem_da_sessao_nao_do_cliente(db, cliente, escola_completa):
    """Não há parâmetro aluno_id no endpoint: cada aluno recebe as SUAS conquistas
    pela credencial. Um aluno não tem como pedir as de outro (sem IDOR)."""
    a0, a1 = escola_completa["alunos"][0], escola_completa["alunos"][1]
    r0 = _login_aluno(cliente, db, escola_completa, indice=0).get("/api/v1/quest/conquistas")
    r1 = _login_aluno(cliente, db, escola_completa, indice=1).get("/api/v1/quest/conquistas")
    assert r0.json()["aluno_id"] == a0.id
    assert r1.json()["aluno_id"] == a1.id and a1.id != a0.id


def test_sem_token_nao_acessa(cliente):
    r = TestClient(app).get("/api/v1/quest/conquistas")
    assert r.status_code == 401


def test_endpoint_e_read_only_nao_ha_como_conceder(db, cliente, escola_completa):
    """A fonte da verdade é o backend: só existe GET. Tentar CONCEDER/alterar
    (POST/PUT) uma conquista pela API do aluno não é uma rota válida."""
    c = _login_aluno(cliente, db, escola_completa, indice=0)
    assert c.post("/api/v1/quest/conquistas", json={"codigo": "x"}).status_code in (404, 405)
    assert c.put("/api/v1/quest/conquistas", json={"codigo": "x"}).status_code in (404, 405)
