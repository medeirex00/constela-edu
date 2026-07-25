"""Tier REDE / Secretaria de Educação: agrega as escolas da rede, isola entre
redes (IDOR) e nunca expõe PII de criança (só cartão por escola)."""
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import Aluno, Escola, Matricula, Nota, Rede, Turma, Usuario


def _login(email: str, senha: str) -> TestClient:
    cliente = TestClient(app)
    r = cliente.post("/api/v1/auth/login", data={"username": email, "password": senha})
    assert r.status_code == 200, r.text
    cliente.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return cliente


def _escola_com_notas(db, rede_id, nome, notas_gerais):
    esc = Escola(nome=nome, ano_letivo_ativo=2026, rede_id=rede_id, status="ativa")
    db.add(esc)
    db.flush()
    turma = Turma(escola_id=esc.id, nome="1º Ano A", ano_escolar="1º Ano",
                  ano_letivo=2026, status="ativa")
    db.add(turma)
    db.flush()
    for i, ng in enumerate(notas_gerais):
        a = Aluno(escola_id=esc.id, nome=f"Crianca {nome} {i}")
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=esc.id, aluno_id=a.id, turma_id=turma.id, ano_letivo=2026))
        db.add(Nota(escola_id=esc.id, aluno_id=a.id, ano_letivo=2026,
                    nota_geral=ng, posicao=i + 1))
    return esc


def test_secretaria_ve_agregado_da_rede_sem_pii(db):
    rede = Rede(nome="Rede Municipal de Caraguatatuba", uf="SP", status="ativa")
    db.add(rede)
    db.flush()
    _escola_com_notas(db, rede.id, "Escola Boa", [80.0, 70.0, 90.0])   # média 80
    _escola_com_notas(db, rede.id, "Escola Fraca", [20.0])             # média 20 → atenção
    db.add(Usuario(nome="Secretaria", email="sec@rede.gov",
                   senha_hash=hash_senha("s3nh4secretaria"), cargo="coordenador",
                   rede_id=rede.id))
    db.commit()

    cliente = _login("sec@rede.gov", "s3nh4secretaria")

    # Lista de redes: só a dele.
    assert [r["id"] for r in cliente.get("/api/v1/redes").json()] == [rede.id]

    resp = cliente.get(f"/api/v1/redes/{rede.id}/dashboard")
    assert resp.status_code == 200, resp.text
    dash = resp.json()
    assert dash["totais"]["escolas"] == 2
    assert dash["totais"]["alunos"] == 4
    assert {c["nome"] for c in dash["escolas"]} == {"Escola Boa", "Escola Fraca"}
    # Equidade: diferença entre a melhor (80) e a pior (20) escola.
    assert dash["equidade"]["gap_media"] == 60.0
    # Escola em atenção sinalizada, com motivo.
    assert [c["nome"] for c in dash["atencao"]] == ["Escola Fraca"]
    assert dash["totais"]["escolas_em_atencao"] == 1
    fraca = next(c for c in dash["escolas"] if c["nome"] == "Escola Fraca")
    assert fraca["precisa_atencao"] and fraca["motivo_atencao"]

    # PRIVACIDADE: a resposta agregada NÃO traz nome de criança.
    assert "Crianca" not in resp.text


def test_isolamento_entre_redes_bloqueia_idor(db):
    r1 = Rede(nome="Rede A", status="ativa")
    r2 = Rede(nome="Rede B", status="ativa")
    db.add_all([r1, r2])
    db.flush()
    db.add(Usuario(nome="Sec A", email="seca@rede.gov",
                   senha_hash=hash_senha("s3nh4redeaaa"), cargo="coordenador",
                   rede_id=r1.id))
    db.commit()

    cliente = _login("seca@rede.gov", "s3nh4redeaaa")
    assert cliente.get(f"/api/v1/redes/{r1.id}/dashboard").status_code == 200
    assert cliente.get(f"/api/v1/redes/{r2.id}/dashboard").status_code == 403  # outra rede


def test_usuario_de_escola_nao_ve_rede(db, escola_completa):
    escola = escola_completa["escola"]
    db.add(Usuario(escola_id=escola.id, nome="Coord Escola", email="coord@esc.local",
                   senha_hash=hash_senha("s3nh4coordddd"), cargo="coordenador"))
    db.commit()
    cliente = _login("coord@esc.local", "s3nh4coordddd")
    assert cliente.get("/api/v1/redes").json() == []
