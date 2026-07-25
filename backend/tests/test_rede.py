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


# --- CRUD / provisionamento (admin global) ----------------------------------

def _admin_global(db, email="root@constela.local", senha="s3nh4rootglobal"):
    db.add(Usuario(nome="Root", email=email, senha_hash=hash_senha(senha),
                   cargo="admin", is_global=True))
    db.commit()
    return _login(email, senha)


def test_crud_rede_provisiona_escolas_coords_e_secretaria(db):
    # Duas escolas soltas (sem rede) + um usuário que vira Secretaria.
    e1 = Escola(nome="EM Centro", ano_letivo_ativo=2026, status="ativa")
    e2 = Escola(nome="EM Litoral", ano_letivo_ativo=2026, status="ativa")
    db.add_all([e1, e2])
    db.flush()
    futura_sec = Usuario(nome="Futura Secretaria", email="fut@sec.gov",
                         senha_hash=hash_senha("s3nh4futurasec"), cargo="coordenador")
    db.add(futura_sec)
    db.commit()
    e1_id, e2_id, sec_id = e1.id, e2.id, futura_sec.id

    root = _admin_global(db)

    # Cria a rede.
    r = root.post("/api/v1/redes", json={"nome": "Rede Municipal X", "uf": "SP"})
    assert r.status_code == 201, r.text
    rede_id = r.json()["id"]

    # Nome repetido é recusado (idempotência contra clique duplo).
    assert root.post("/api/v1/redes", json={"nome": "Rede Municipal X"}).status_code == 409

    # Vincula as duas escolas à rede.
    r = root.put(f"/api/v1/redes/{rede_id}/escolas", json={"escola_ids": [e1_id, e2_id]})
    assert r.status_code == 200, r.text
    assert r.json()["escola_ids"] == sorted([e1_id, e2_id])

    # Coordenadas de uma escola (para o mapa).
    r = root.patch(f"/api/v1/redes/escolas/{e1_id}",
                   json={"latitude": -23.62, "longitude": -45.41, "cidade": "Caraguatatuba"})
    assert r.status_code == 200, r.text
    assert r.json()["latitude"] == -23.62

    # Designa a Secretaria.
    r = root.put(f"/api/v1/redes/{rede_id}/usuarios", json={"usuario_ids": [sec_id]})
    assert r.status_code == 200, r.text

    # O painel agora enxerga as duas escolas, uma com coordenada.
    dash = root.get(f"/api/v1/redes/{rede_id}/dashboard").json()
    assert dash["totais"]["escolas"] == 2
    com_coord = [c for c in dash["escolas"] if c["latitude"] is not None]
    assert len(com_coord) == 1 and com_coord[0]["nome"] == "EM Centro"

    # A Secretaria designada agora enxerga a própria rede (rede_id aplicado).
    db.expire_all()
    sec = db.get(Usuario, sec_id)
    assert sec.rede_id == rede_id


def test_desvincular_escola_ao_redefinir_o_conjunto(db):
    rede = Rede(nome="Rede Y", status="ativa")
    db.add(rede)
    db.flush()
    e1 = Escola(nome="EM Uma", ano_letivo_ativo=2026, status="ativa", rede_id=rede.id)
    e2 = Escola(nome="EM Outra", ano_letivo_ativo=2026, status="ativa", rede_id=rede.id)
    db.add_all([e1, e2])
    db.commit()
    e1_id, e2_id, rede_id = e1.id, e2.id, rede.id

    root = _admin_global(db)
    # Redefine o conjunto para só a primeira: a segunda deve ser desvinculada.
    r = root.put(f"/api/v1/redes/{rede_id}/escolas", json={"escola_ids": [e1_id]})
    assert r.status_code == 200, r.text

    db.expire_all()
    assert db.get(Escola, e1_id).rede_id == rede_id
    assert db.get(Escola, e2_id).rede_id is None


def test_crud_rede_exige_admin_global(db):
    rede = Rede(nome="Rede Z", status="ativa")
    db.add(rede)
    db.add(Usuario(nome="Coord Local", email="local@esc.local",
                   senha_hash=hash_senha("s3nh4locallll"), cargo="admin",
                   escola_id=None))
    db.commit()
    rede_id = rede.id

    cliente = _login("local@esc.local", "s3nh4locallll")
    # Um admin NÃO-global não cria rede nem gerencia vínculos.
    assert cliente.post("/api/v1/redes", json={"nome": "Nova"}).status_code == 403
    assert cliente.get("/api/v1/redes/gerenciar").status_code == 403
    assert cliente.put(f"/api/v1/redes/{rede_id}/escolas",
                       json={"escola_ids": []}).status_code == 403
