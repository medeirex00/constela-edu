"""Perfis de acesso: escopo unificado (escola/rede/global), vínculo forte
professor↔turma por FK, e ISOLAMENTO REAL do tier de rede/Secretaria (IDOR
entre redes barrado no backend — não só escondido no front)."""
import pytest
from fastapi.testclient import TestClient

from app.core.security import criar_token, hash_senha
from app.main import app
from app.models import (
    Aluno,
    Escola,
    Matricula,
    Nota,
    Professor,
    Rede,
    Turma,
    Usuario,
)
from app.services import permissoes


def _headers(usuario: Usuario) -> dict:
    return {"Authorization": f"Bearer {criar_token(usuario.id, usuario.token_version or 0)}"}


def _cliente(usuario: Usuario) -> TestClient:
    c = TestClient(app)
    c.headers.update(_headers(usuario))
    return c


@pytest.fixture()
def rede_setup(db):
    """Duas redes municipais. Rede A tem 2 escolas (a1 com dados, a2 vazia);
    Rede B tem 1 escola. Usuários: secretaria A, secretaria B, admin global e um
    coordenador de escola única (sem rede)."""
    rede_a = Rede(nome="Rede Municipal A", uf="SP")
    rede_b = Rede(nome="Rede Municipal B", uf="SP")
    db.add_all([rede_a, rede_b])
    db.flush()

    a1 = Escola(nome="EM Alfa", ano_letivo_ativo=2026, rede_id=rede_a.id,
                latitude=-23.62, longitude=-45.41)
    a2 = Escola(nome="EM Beta", ano_letivo_ativo=2026, rede_id=rede_a.id)
    b1 = Escola(nome="EM Gama", ano_letivo_ativo=2026, rede_id=rede_b.id)
    db.add_all([a1, a2, b1])
    db.flush()

    # Secretaria/Admin Supremo da rede = admin (ações) + rede_id (alcance).
    sec_a = Usuario(nome="Sec A", email="seca@t.local", senha_hash=hash_senha("x"),
                    cargo="admin", rede_id=rede_a.id, escola_id=a1.id)
    sec_b = Usuario(nome="Sec B", email="secb@t.local", senha_hash=hash_senha("x"),
                    cargo="coordenador", rede_id=rede_b.id, escola_id=b1.id)
    glob = Usuario(nome="Global", email="glob@t.local", senha_hash=hash_senha("x"),
                   cargo="admin", is_global=True)
    coord_escola = Usuario(nome="Coord Escola", email="ce@t.local",
                           senha_hash=hash_senha("x"), cargo="coordenador",
                           escola_id=a1.id)
    professor = Usuario(nome="Prof A1", email="prof@t.local",
                        senha_hash=hash_senha("x"), cargo="professor", escola_id=a1.id)
    db.add_all([sec_a, sec_b, glob, coord_escola, professor])
    db.flush()

    # Dados em a1: 1 turma, 3 alunos com nota (para o dashboard ter conteúdo).
    turma = Turma(escola_id=a1.id, nome="1º Ano A", ano_escolar="1º Ano", ano_letivo=2026)
    db.add(turma)
    db.flush()
    for i in range(3):
        aluno = Aluno(escola_id=a1.id, nome=f"Aluno {i}")
        db.add(aluno)
        db.flush()
        db.add(Matricula(escola_id=a1.id, aluno_id=aluno.id, turma_id=turma.id,
                         ano_letivo=2026))
        db.add(Nota(escola_id=a1.id, aluno_id=aluno.id, ano_letivo=2026,
                    nota_geral=9.0 - i, nota_matific=8.0, nota_elefante=7.0, posicao=i + 1))
    db.commit()
    return {"rede_a": rede_a, "rede_b": rede_b, "a1": a1, "a2": a2, "b1": b1,
            "sec_a": sec_a, "sec_b": sec_b, "glob": glob,
            "coord_escola": coord_escola, "professor": professor}


# --------------------------------------------------------------- escopo_escolas

def test_escopo_escolas_por_tipo_de_usuario(db, rede_setup):
    s = rede_setup
    # Global → None (todas).
    assert permissoes.escopo_escolas(db, s["glob"]) is None
    # Secretaria da rede A → as duas escolas da rede A (não a de B).
    assert permissoes.escopo_escolas(db, s["sec_a"]) == {s["a1"].id, s["a2"].id}
    # Coordenador de escola única → só a própria escola.
    assert permissoes.escopo_escolas(db, s["coord_escola"]) == {s["a1"].id}
    # Usuário sem escola e sem rede → fail-closed (nenhuma).
    orfao = Usuario(nome="Orfao", email="o@t.local", senha_hash=hash_senha("x"),
                    cargo="professor")
    db.add(orfao)
    db.flush()
    assert permissoes.escopo_escolas(db, orfao) == set()


# ------------------------------------------------------- professor por FK (forte)

def test_turmas_permitidas_prefere_fk_sobre_email(db, escola_completa):
    """O vínculo por FK (`professor_id`) vale mesmo com e-mail DIVERGENTE — o
    ponto do fix: acabar com a fragilidade do casamento por string de e-mail."""
    escola = escola_completa["escola"]
    turma = escola_completa["turma"]
    professor = Professor(escola_id=escola.id, nome="Prof. Ana", email="cadastro@x.local")
    db.add(professor)
    db.flush()
    turma.professor_id = professor.id
    # Usuário com e-mail TOTALMENTE diferente do cadastro, mas FK setada.
    u = Usuario(escola_id=escola.id, nome="Ana", email="outro-email@y.local",
                senha_hash=hash_senha("x"), cargo="professor", professor_id=professor.id)
    db.add(u)
    db.commit()

    # Pelo e-mail não casaria (divergente); pela FK, casa e retorna a turma dele.
    assert permissoes.turmas_permitidas(db, escola.id, u) == [turma.id]


def test_professor_por_fk_so_ve_suas_turmas_via_http(db, escola_completa):
    escola = escola_completa["escola"]
    turma_a = escola_completa["turma"]
    turma_b = Turma(escola_id=escola.id, nome="2º Ano B", ano_escolar="2º Ano", ano_letivo=2026)
    db.add(turma_b)
    db.flush()
    fora = Aluno(escola_id=escola.id, nome="Aluno Fora")
    db.add(fora)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=fora.id, turma_id=turma_b.id, ano_letivo=2026))
    professor = Professor(escola_id=escola.id, nome="Prof FK", email=None)  # sem e-mail!
    db.add(professor)
    db.flush()
    turma_a.professor_id = professor.id
    u = Usuario(escola_id=escola.id, nome="ProfFK", email="proffk@t.local",
                senha_hash=hash_senha("x"), cargo="professor", professor_id=professor.id)
    db.add(u)
    db.commit()

    base = f"/api/v1/escolas/{escola.id}"
    itens = _cliente(u).get(f"{base}/alunos").json()["itens"]
    nomes = [a["nome"] for a in itens]
    assert "Aluno Fora" not in nomes and len(nomes) == 3   # só a turma A


# ---------------------------------------------------------- tier de rede (IDOR)

def test_rede_dashboard_so_da_propria_rede(rede_setup):
    s = rede_setup
    r = _cliente(s["sec_a"]).get(f"/api/v1/redes/{s['rede_a'].id}/dashboard")
    assert r.status_code == 200
    corpo = r.json()
    ids = {e["escola_id"] for e in corpo["escolas"]}
    assert ids == {s["a1"].id, s["a2"].id}                 # só as escolas da rede A
    assert corpo["totais"]["escolas"] == 2
    assert corpo["totais"]["alunos"] == 3                   # os 3 de a1


def test_rede_idor_bloqueia_outra_rede(rede_setup):
    """A secretaria da rede A NÃO acessa a rede B (403) — isolamento real."""
    s = rede_setup
    for caminho in ("dashboard", "ranking"):
        r = _cliente(s["sec_a"]).get(f"/api/v1/redes/{s['rede_b'].id}/{caminho}")
        assert r.status_code == 403, f"{caminho}: {r.status_code}"


def test_coordenador_de_escola_nao_acessa_rede(rede_setup):
    """Coordenador de escola única (sem rede_id) não entra em nenhuma /redes/*."""
    s = rede_setup
    r = _cliente(s["coord_escola"]).get(f"/api/v1/redes/{s['rede_a'].id}/dashboard")
    assert r.status_code == 403


def test_global_acessa_qualquer_rede(rede_setup):
    s = rede_setup
    for rede in (s["rede_a"], s["rede_b"]):
        assert _cliente(s["glob"]).get(f"/api/v1/redes/{rede.id}/dashboard").status_code == 200


def test_listar_redes_por_escopo(rede_setup):
    s = rede_setup
    # Secretaria A vê só a rede A.
    ra = _cliente(s["sec_a"]).get("/api/v1/redes").json()
    assert [r["id"] for r in ra] == [s["rede_a"].id]
    # Global vê todas.
    todas = {r["id"] for r in _cliente(s["glob"]).get("/api/v1/redes").json()}
    assert todas == {s["rede_a"].id, s["rede_b"].id}
    # Coordenador de escola não vê nenhuma.
    assert _cliente(s["coord_escola"]).get("/api/v1/redes").json() == []


def test_escola_autorizada_respeita_escopo_de_rede(rede_setup):
    """A secretaria da rede A acessa dados de QUALQUER escola da rede A (a2), mas
    NÃO de uma escola da rede B (b1) — o isolamento por escola agora entende rede."""
    s = rede_setup
    c = _cliente(s["sec_a"])
    # a2 é da rede A → dashboard da escola abre (200).
    assert c.get(f"/api/v1/escolas/{s['a2'].id}/dashboard").status_code == 200
    # b1 é de outra rede → 403.
    assert c.get(f"/api/v1/escolas/{s['b1'].id}/dashboard").status_code == 403


def test_seletor_de_escolas_escopado_a_rede(rede_setup):
    """GET /escolas para a secretaria A traz as escolas da rede A (não as de B)."""
    s = rede_setup
    nomes = {e["nome"] for e in _cliente(s["sec_a"]).get("/api/v1/escolas").json()}
    assert nomes == {"EM Alfa", "EM Beta"}                  # rede A; sem "EM Gama"


def test_ranking_municipal_por_escola(rede_setup):
    s = rede_setup
    r = _cliente(s["sec_a"]).get(f"/api/v1/redes/{s['rede_a'].id}/ranking").json()
    # Só escolas com dados entram (a1); a2 (sem nota) fica fora. Ranking é por
    # ESCOLA (não expõe criança individual entre escolas).
    assert [e["escola_id"] for e in r] == [s["a1"].id]
    assert r[0]["posicao"] == 1 and "media_geral" in r[0]


# ------------------------------------------------- MATRIZ IDOR (cross-escopo)

def test_idor_matriz_por_escopo(rede_setup):
    """A tabela-verdade de acesso a dados de UMA escola (dashboard), por perfil.
    Tudo imposto no backend — o front nem entra na conta."""
    s = rede_setup
    a1, a2, b1 = s["a1"].id, s["a2"].id, s["b1"].id

    def dash(user, escola_id):
        return _cliente(user).get(f"/api/v1/escolas/{escola_id}/dashboard").status_code

    # Professor da a1: sua escola OK; outra escola (mesma "rede", mas ele não é
    # de rede) e escola de outra rede → 403.
    assert dash(s["professor"], a1) == 200
    assert dash(s["professor"], a2) == 403      # professor -> outra escola
    assert dash(s["professor"], b1) == 403
    # Coordenador de UMA escola: só a dele (não vê a2, mesmo da mesma rede —
    # coordenador comum é escola-scoped, não rede-scoped).
    assert dash(s["coord_escola"], a1) == 200
    assert dash(s["coord_escola"], a2) == 403   # coordenador -> outra escola
    assert dash(s["coord_escola"], b1) == 403
    # Secretaria da rede A: qualquer escola da rede A; nunca a de B.
    assert dash(s["sec_a"], a1) == 200 and dash(s["sec_a"], a2) == 200
    assert dash(s["sec_a"], b1) == 403          # secretaria -> outra rede
    # Admin global: tudo.
    assert dash(s["glob"], a1) == 200 and dash(s["glob"], b1) == 200


def test_consolidado_por_professor_gestor_only(rede_setup, db):
    """O consolidado por professor é gestão: coordenador vê; professor 403."""
    s = rede_setup
    url = f"/api/v1/escolas/{s['a1'].id}/consolidado-professores"
    assert _cliente(s["coord_escola"]).get(url).status_code == 200
    assert _cliente(s["professor"]).get(url).status_code == 403


def test_secretaria_corrige_geo_de_escola_da_rede(rede_setup):
    """A Secretaria (admin+rede) corrige o pino de QUALQUER escola da sua rede
    (PATCH), inclusive uma que não é a 'sua' escola-base; barrada em outra rede."""
    s = rede_setup
    c = _cliente(s["sec_a"])
    ok = c.patch(f"/api/v1/escolas/{s['a2'].id}", json={"latitude": -23.6, "longitude": -45.4})
    assert ok.status_code == 200, ok.text
    assert ok.json()["latitude"] == -23.6
    assert c.patch(f"/api/v1/escolas/{s['b1'].id}", json={"latitude": 0.0}).status_code == 403


def test_ranking_da_rede_traz_posicao_no_dashboard(rede_setup):
    """O dashboard da rede já numera as escolas (posicao 1..N) — a tela não
    precisa do endpoint /ranking para exibir o ranking."""
    s = rede_setup
    corpo = _cliente(s["sec_a"]).get(f"/api/v1/redes/{s['rede_a'].id}/dashboard").json()
    assert corpo["escolas"][0]["posicao"] == 1
    assert [e["posicao"] for e in corpo["escolas"]] == list(range(1, len(corpo["escolas"]) + 1))
