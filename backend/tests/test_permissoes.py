"""Permissões por papel: professor restrito às turmas dele (dados superficiais),
coordenador com acesso total à escola, e fim do cargo "visitante"."""
import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import Aluno, Matricula, Professor, Turma, Usuario


def _cliente_como(db, email: str, senha: str) -> TestClient:
    cliente = TestClient(app)
    resposta = cliente.post("/api/v1/auth/login",
                            data={"username": email, "password": senha})
    assert resposta.status_code == 200, resposta.text
    cliente.headers["Authorization"] = f"Bearer {resposta.json()['access_token']}"
    return cliente


@pytest.fixture()
def cenario_professor(db, escola_completa):
    """Escola com 2 turmas: a turma A (da fixture, com 3 alunos) designada ao
    professor logado; a turma B com 1 aluno FORA do alcance dele."""
    escola = escola_completa["escola"]
    turma_a = escola_completa["turma"]

    turma_b = Turma(escola_id=escola.id, nome="5º Ano B", ano_escolar="5º Ano",
                    ano_letivo=2026)
    db.add(turma_b)
    db.flush()
    outro = Aluno(escola_id=escola.id, nome="Aluno De Outra Turma")
    db.add(outro)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=outro.id,
                     turma_id=turma_b.id, ano_letivo=2026))

    # Vínculo: cadastro de Professor com o MESMO e-mail do usuário professor.
    professor = Professor(escola_id=escola.id, nome="Prof. Carla",
                          email="carla@teste.local")
    db.add(professor)
    db.flush()
    turma_a.professor_id = professor.id
    db.add(Usuario(escola_id=escola.id, nome="Carla", email="carla@teste.local",
                   senha_hash=hash_senha("s3nh4prof"), cargo="professor"))
    db.add(Usuario(escola_id=escola.id, nome="Coord", email="coord@teste.local",
                   senha_hash=hash_senha("s3nh4coord"), cargo="coordenador"))
    db.commit()

    return {
        "escola": escola, "turma_a": turma_a, "turma_b": turma_b,
        "aluno_da_turma": escola_completa["alunos"][0], "aluno_fora": outro,
        "professor": _cliente_como(db, "carla@teste.local", "s3nh4prof"),
        "coordenador": _cliente_como(db, "coord@teste.local", "s3nh4coord"),
    }


def test_professor_ve_apenas_alunos_das_suas_turmas(cenario_professor):
    c = cenario_professor
    base = f"/api/v1/escolas/{c['escola'].id}"
    r = c["professor"].get(f"{base}/alunos").json()
    nomes = [a["nome"] for a in r["itens"]]
    assert len(nomes) == 3                              # só a turma A
    assert "Aluno De Outra Turma" not in nomes

    turmas = c["professor"].get(f"{base}/turmas").json()
    assert [t["id"] for t in turmas] == [c["turma_a"].id]  # só a designada


def test_professor_perfil_superficial_e_sem_alunos_de_fora(cenario_professor):
    c = cenario_professor
    base = f"/api/v1/escolas/{c['escola'].id}"
    # Aluno da turma dele: perfil SUPERFICIAL (notas/posição, sem detalhes).
    perfil = c["professor"].get(f"{base}/alunos/{c['aluno_da_turma'].id}/perfil")
    assert perfil.status_code == 200
    corpo = perfil.json()
    assert corpo["detalhes"] == {}                       # sem passo a passo
    assert corpo["leitura_niveis"] is None               # sem distribuição
    # Aluno de outra turma: como se não existisse.
    fora = c["professor"].get(f"{base}/alunos/{c['aluno_fora'].id}/perfil")
    assert fora.status_code == 404


def test_professor_nao_acessa_dados_especificos_nem_gestao(cenario_professor):
    c = cenario_professor
    base = f"/api/v1/escolas/{c['escola'].id}"
    bloqueados = [
        f"{base}/alunos/{c['aluno_da_turma'].id}/leituras",       # histórico
        f"{base}/alunos/{c['aluno_da_turma'].id}/evolucao",       # detalhado
        f"{base}/alunos/{c['aluno_da_turma'].id}/evolucao-leitura",
        f"{base}/resumo-escola",                                   # visão escola
        f"{base}/professores",                                     # cadastro
        f"{base}/gamificacao/mural",                               # escola toda
        f"{base}/comparar?tipo_a=aluno&id_a=1&tipo_b=aluno&id_b=2",
    ]
    for url in bloqueados:
        resposta = c["professor"].get(url)
        assert resposta.status_code == 403, f"{url} -> {resposta.status_code}"
    assistente = c["professor"].post(f"{base}/assistente",
                                     json={"pergunta": "Como estão meus alunos?"})
    assert assistente.status_code == 403
    # Fundir alunos é gestão — professor não pode.
    fundir = c["professor"].post(f"{base}/alunos/fundir", json={
        "manter_id": c["aluno_da_turma"].id, "remover_id": c["aluno_fora"].id,
        "confirmacao": "FUNDIR"})
    assert fundir.status_code == 403


def test_professor_dashboard_conta_so_as_turmas_dele(cenario_professor):
    c = cenario_professor
    base = f"/api/v1/escolas/{c['escola'].id}"
    dash = c["professor"].get(f"{base}/dashboard").json()
    assert dash["total_alunos"] == 3                     # 4 na escola; 3 na turma A
    assert dash["total_turmas"] == 1
    nomes_top = [i["nome"] for i in dash["top10"]]
    assert "Aluno De Outra Turma" not in nomes_top


def test_coordenador_tem_acesso_total_a_escola(cenario_professor):
    c = cenario_professor
    base = f"/api/v1/escolas/{c['escola'].id}"
    assert c["coordenador"].get(f"{base}/resumo-escola").status_code == 200
    assert c["coordenador"].get(f"{base}/professores").status_code == 200
    alunos = c["coordenador"].get(f"{base}/alunos").json()
    assert alunos["total"] == 4                          # escola inteira
    dash = c["coordenador"].get(f"{base}/dashboard").json()
    assert dash["total_alunos"] == 4


def test_pesquisa_do_professor_so_traz_alunos_das_turmas_dele(cenario_professor):
    c = cenario_professor
    base = f"/api/v1/escolas/{c['escola'].id}"
    # "Aluno De Outra Turma" está na turma B (fora do alcance do professor).
    prof = c["professor"].get(f"{base}/pesquisa?q=aluno").json()
    assert "Aluno De Outra Turma" not in [a["nome"] for a in prof["alunos"]]
    # Professor não recebe registros de gestão (cadastro/catálogo).
    assert prof["professores"] == [] and prof["livros"] == []

    # Cada aluno vem com a turma (desambigua homônimos).
    algum = c["professor"].get(f"{base}/pesquisa?q=an").json()["alunos"]
    assert algum and all("turma" in a for a in algum)

    # O coordenador (acesso total) enxerga o aluno da outra turma.
    coord = c["coordenador"].get(f"{base}/pesquisa?q=aluno").json()
    assert "Aluno De Outra Turma" in [a["nome"] for a in coord["alunos"]]


def test_cargo_visitante_nao_pode_ser_criado(db, cenario_professor):
    c = cenario_professor
    base = f"/api/v1/escolas/{c['escola'].id}"
    admin = _cliente_como(db, "admin@teste.local", "s3nh4")
    r = admin.post(f"{base}/usuarios", json={
        "nome": "Visita", "email": "visita@teste.local",
        "senha": "SenhaForte123", "cargo": "visitante"})
    assert r.status_code in (400, 422)