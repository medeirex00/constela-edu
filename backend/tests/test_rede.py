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


# --- Boletim da rede (PDF) --------------------------------------------------

_DADOS_BOLETIM = {
    "rede_id": 1,
    "totais": {"escolas": 3, "escolas_ativas": 3, "alunos": 120, "turmas": 9,
               "alunos_com_dados": 100, "adocao": 83.3, "media_geral": 62.5,
               "media_matific": 60.0, "media_elefante": 65.0, "escolas_em_atencao": 1},
    "equidade": {"gap_media": 40.0, "escola_maior_media": 80.0,
                 "escola_menor_media": 40.0, "escolas_abaixo_da_media": 1},
    "escolas": [
        {"escola_id": 1, "nome": "EM Alfa", "posicao": 1, "total_alunos": 40, "adocao": 95.0,
         "media_matific": 78.0, "media_elefante": 82.0, "media_geral": 80.0,
         "precisa_atencao": False, "motivo_atencao": None},
        {"escola_id": 3, "nome": "EM Gama", "posicao": 3, "total_alunos": 40, "adocao": 20.0,
         "media_matific": 40.0, "media_elefante": 40.0, "media_geral": 40.0,
         "precisa_atencao": True, "motivo_atencao": "Baixa adoção: só 20% dos alunos têm dados."},
    ],
    "atencao": [
        {"escola_id": 3, "nome": "EM Gama", "posicao": 3, "total_alunos": 40, "adocao": 20.0,
         "media_matific": 40.0, "media_elefante": 40.0, "media_geral": 40.0,
         "precisa_atencao": True, "motivo_atencao": "Baixa adoção: só 20% dos alunos têm dados."},
    ],
}


def _forcar_reserva_fpdf(monkeypatch):
    """Faz o boletim usar a RESERVA fpdf (sem depender do Chromium no ambiente
    de teste), forçando o caminho HTML→navegador a falhar."""
    from app.services import relatorios as rel

    def _boom(_html):
        raise RuntimeError("sem chromium (teste)")

    monkeypatch.setattr(rel, "_relatorio_html_pdf", _boom)


def test_boletim_shell_reune_os_dados_da_rede():
    from app.services import relatorios as rel
    html = rel._shell_boletim_rede("Rede Municipal X", _DADOS_BOLETIM)
    assert "Rede Municipal X" in html and "Boletim da Rede" in html
    assert "EM Alfa" in html and "EM Gama" in html          # ranking das escolas
    assert "precisam de atenção" in html                    # seção de atenção
    assert "Baixa adoção" in html                           # motivo da escola em atenção
    assert "Equidade entre escolas" in html
    # PRIVACIDADE: só escolas/agregados — nada de nome de criança no documento.
    assert "Crianca" not in html


def test_gerar_boletim_rede_produz_pdf(monkeypatch):
    from app.services import relatorios as rel
    _forcar_reserva_fpdf(monkeypatch)
    conteudo = rel.gerar_boletim_rede("Rede X", _DADOS_BOLETIM)
    assert conteudo[:4] == b"%PDF"  # PDF válido mesmo na reserva


def test_boletim_endpoint_pdf_e_isolamento(db, monkeypatch):
    _forcar_reserva_fpdf(monkeypatch)
    rede = Rede(nome="Rede do Boletim", status="ativa")
    outra = Rede(nome="Outra Rede", status="ativa")
    db.add_all([rede, outra])
    db.flush()
    _escola_com_notas(db, rede.id, "Escola Boletim", [80.0, 70.0])
    db.add(Usuario(nome="Sec", email="sec@bol.gov", senha_hash=hash_senha("s3nh4boletim1"),
                   cargo="coordenador", rede_id=rede.id))
    db.commit()

    cliente = _login("sec@bol.gov", "s3nh4boletim1")
    r = cliente.get(f"/api/v1/redes/{rede.id}/boletim")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:4] == b"%PDF"
    assert "boletim_rede" in r.headers.get("content-disposition", "")

    # Isolamento: a Secretaria de uma rede NÃO baixa o boletim de OUTRA (IDOR).
    assert cliente.get(f"/api/v1/redes/{outra.id}/boletim").status_code == 403


# --- Painel público da rede (top 5 escolas, sem PII) ------------------------

def _escola_publico(db, rede_id, nome, matific, elefante):
    esc = Escola(nome=nome, ano_letivo_ativo=2026, rede_id=rede_id, status="ativa")
    db.add(esc)
    db.flush()
    turma = Turma(escola_id=esc.id, nome="1A", ano_escolar="1º Ano", ano_letivo=2026,
                  status="ativa")
    db.add(turma)
    db.flush()
    a = Aluno(escola_id=esc.id, nome=f"Aluno {nome}")
    db.add(a)
    db.flush()
    db.add(Matricula(escola_id=esc.id, aluno_id=a.id, turma_id=turma.id, ano_letivo=2026))
    db.add(Nota(escola_id=esc.id, aluno_id=a.id, ano_letivo=2026,
                nota_geral=(matific + elefante) / 2, nota_matific=matific,
                nota_elefante=elefante, posicao=1))
    return esc


def test_painel_publico_top5_sem_pii(db):
    from app.services import rede as svc_rede
    rede = Rede(nome="Rede Pública", status="ativa")
    db.add(rede)
    db.flush()
    for i, (m, e) in enumerate([(90, 50), (80, 60), (70, 70), (60, 80), (50, 90), (40, 40)]):
        _escola_publico(db, rede.id, f"EM {i}", m, e)
    db.commit()

    p = svc_rede.painel_publico_rede(db, rede.id)
    assert p["rede_nome"] == "Rede Pública"
    assert len(p["top_matematica"]) == 5 and len(p["top_leitura"]) == 5
    assert p["top_matematica"][0]["valor"] == 90.0   # maior média Matific
    assert p["top_leitura"][0]["valor"] == 90.0       # maior média Elefante
    # PRIVACIDADE: só nome de ESCOLA + valor — nada de aluno/criança.
    import json
    texto = json.dumps(p, ensure_ascii=False).lower()
    assert "aluno" not in texto and "crianca" not in texto


def test_painel_publico_token_liga_desliga_e_endpoint(db):
    rede = Rede(nome="Rede Token", status="ativa")
    db.add(rede)
    db.flush()
    _escola_publico(db, rede.id, "EM A", 80.0, 70.0)
    db.commit()
    publico = TestClient(app)          # SEM login

    root = _admin_global(db)
    r = root.put(f"/api/v1/redes/{rede.id}/publico", json={"ativo": True})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    assert token and r.json()["ativo"] and "/rede/p/" in r.json()["url"]

    # Público sem login resolve o token e mostra os tops.
    pub = publico.get(f"/api/v1/publico/rede/{token}")
    assert pub.status_code == 200
    assert pub.json()["rede_nome"] == "Rede Token"
    assert pub.json()["top_matematica"][0]["valor"] == 80.0

    # Desligar invalida o link; token aleatório também é 404.
    root.put(f"/api/v1/redes/{rede.id}/publico", json={"ativo": False})
    assert publico.get(f"/api/v1/publico/rede/{token}").status_code == 404
    assert publico.get("/api/v1/publico/rede/inexistente").status_code == 404


def test_painel_publico_token_nao_ascii_nao_500(db):
    # Regressão (achado da revisão): token não-ASCII num endpoint SEM login não
    # pode virar 500 (secrets.compare_digest levanta TypeError com não-ASCII).
    # Com a vitrine LIGADA (há candidata), sem a guarda o compare rodaria e daria 500.
    rede = Rede(nome="Rede NA", status="ativa")
    db.add(rede)
    db.flush()
    _escola_publico(db, rede.id, "EM A", 80.0, 70.0)
    db.commit()
    _admin_global(db).put(f"/api/v1/redes/{rede.id}/publico", json={"ativo": True})

    publico = TestClient(app)
    assert publico.get("/api/v1/publico/rede/café").status_code == 404
    assert publico.get("/api/v1/publico/rede/%C3%A9").status_code == 404


def test_painel_publico_config_exige_a_rede(db):
    r1 = Rede(nome="Rede 1", status="ativa")
    r2 = Rede(nome="Rede 2", status="ativa")
    db.add_all([r1, r2])
    db.flush()
    db.add(Usuario(nome="Sec1", email="sec1@pub.gov", senha_hash=hash_senha("s3nh4publica1"),
                   cargo="coordenador", rede_id=r1.id))
    db.commit()
    cliente = _login("sec1@pub.gov", "s3nh4publica1")
    # A Secretaria da rede 1 liga o SEU painel...
    assert cliente.put(f"/api/v1/redes/{r1.id}/publico", json={"ativo": True}).status_code == 200
    # ...mas não pode ligar o de OUTRA rede (IDOR barrado).
    assert cliente.put(f"/api/v1/redes/{r2.id}/publico", json={"ativo": True}).status_code == 403
