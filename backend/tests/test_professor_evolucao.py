"""Evolução por aluno e o PROFESSOR (decisão do dono de 03/08/2026).

O professor vê a evolução (`/evolucao` e `/evolucao-leitura`) só dos alunos
das turmas DELE no ano letivo ativo. Aluno de outra turma: 404 (não revela que
existe). Outra escola: 403. Sem login: 401. Coordenador/admin: qualquer aluno
da escola. Secretaria: sem dado individual (404). Linha do tempo e espelho
continuam só de gestão (professor 403).
"""
import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import Aluno, Escola, Matricula, Professor, Rede, Turma, Usuario

ROTAS_ABERTAS = ("evolucao", "evolucao-leitura")
ROTAS_DE_GESTAO = ("linha-do-tempo", "espelho")


def _login(email: str, senha: str = "s3nh4") -> TestClient:
    cliente = TestClient(app)
    r = cliente.post("/api/v1/auth/login", data={"username": email, "password": senha})
    assert r.status_code == 200, r.text
    cliente.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return cliente


@pytest.fixture()
def mundo(db, escola_completa):
    escola = escola_completa["escola"]
    turma = escola_completa["turma"]                 # 3 alunos matriculados (2026)
    rede = Rede(nome="Rede EV", status="ativa")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id

    prof = Professor(escola_id=escola.id, nome="Prof EV", email="prof@ev.local")
    db.add(prof)
    db.flush()
    turma.professor_id = prof.id

    turma2 = Turma(escola_id=escola.id, nome="Outra Turma", ano_escolar="4º Ano",
                   ano_letivo=2026)
    db.add(turma2)
    db.flush()
    fora = Aluno(escola_id=escola.id, nome="Aluno Fora", status="ativo")
    db.add(fora)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=fora.id, turma_id=turma2.id,
                     ano_letivo=2026))

    outra = Escola(nome="OUTRA ESCOLA", ano_letivo_ativo=2026)
    db.add(outra)
    db.flush()
    t_outra = Turma(escola_id=outra.id, nome="1º Ano A", ano_escolar="1º Ano",
                    ano_letivo=2026)
    db.add(t_outra)
    db.flush()
    al_outra = Aluno(escola_id=outra.id, nome="Aluno Outra Escola", status="ativo")
    db.add(al_outra)
    db.flush()
    db.add(Matricula(escola_id=outra.id, aluno_id=al_outra.id, turma_id=t_outra.id,
                     ano_letivo=2026))

    for email, cargo, escola_id, rede_id in (
            ("prof@ev.local", "professor", escola.id, None),
            ("coord@ev.local", "coordenador", escola.id, None),
            ("sec@ev.local", "coordenador", None, rede.id)):
        db.add(Usuario(escola_id=escola_id, rede_id=rede_id, nome=email, email=email,
                       senha_hash=hash_senha("s3nh4"), cargo=cargo))
    db.commit()
    return {"escola": escola.id, "outra": outra.id,
            "meu": escola_completa["alunos"][0], "fora": fora, "al_outra": al_outra}


def _url(escola_id, aluno_id, rota):
    return f"/api/v1/escolas/{escola_id}/alunos/{aluno_id}/{rota}"


@pytest.mark.parametrize("rota", ROTAS_ABERTAS)
def test_professor_ve_evolucao_dos_seus_alunos(mundo, rota):
    r = _login("prof@ev.local").get(_url(mundo["escola"], mundo["meu"].id, rota))
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("rota", ROTAS_ABERTAS)
def test_professor_nao_ve_evolucao_de_outra_turma(mundo, rota):
    r = _login("prof@ev.local").get(_url(mundo["escola"], mundo["fora"].id, rota))
    assert r.status_code == 404


@pytest.mark.parametrize("rota", ROTAS_ABERTAS)
def test_professor_nao_ve_evolucao_de_outra_escola(mundo, rota):
    r = _login("prof@ev.local").get(_url(mundo["outra"], mundo["al_outra"].id, rota))
    assert r.status_code == 403
    # Mesmo pondo o id do aluno de fora na URL da PRÓPRIA escola: 404.
    r = _login("prof@ev.local").get(_url(mundo["escola"], mundo["al_outra"].id, rota))
    assert r.status_code == 404


@pytest.mark.parametrize("rota", ROTAS_ABERTAS)
def test_turma_de_ano_anterior_nao_abre_evolucao(mundo, db, rota):
    """O escopo é o das turmas do professor no ANO LETIVO ATIVO (o mesmo recorte
    da exportação). A turma que ele deu no ano passado, com o MESMO nome de uma
    turma deste ano que é de outra pessoa, não abre a evolução de quem estudou
    nela e hoje está na turma da colega. A turma atual dele continua abrindo."""
    prof = db.query(Professor).filter_by(email="prof@ev.local").one()
    antiga = Turma(escola_id=mundo["escola"], nome="Outra Turma", ano_escolar="3º Ano",
                   ano_letivo=2025, professor_id=prof.id)
    db.add(antiga)
    db.flush()
    db.add(Matricula(escola_id=mundo["escola"], aluno_id=mundo["fora"].id,
                     turma_id=antiga.id, ano_letivo=2025))
    db.commit()
    cliente = _login("prof@ev.local")
    assert cliente.get(_url(mundo["escola"], mundo["fora"].id, rota)).status_code == 404
    assert cliente.get(_url(mundo["escola"], mundo["meu"].id, rota)).status_code == 200


@pytest.mark.parametrize("rota", ROTAS_ABERTAS + ROTAS_DE_GESTAO)
def test_evolucao_exige_login(mundo, rota):
    assert TestClient(app).get(_url(mundo["escola"], mundo["meu"].id, rota)).status_code == 401


@pytest.mark.parametrize("rota", ROTAS_ABERTAS)
def test_professor_perde_acesso_quando_o_aluno_sai_da_turma(mundo, db, rota):
    aluno = mundo["meu"]
    aluno.status = "transferido"
    db.commit()
    r = _login("prof@ev.local").get(_url(mundo["escola"], aluno.id, rota))
    assert r.status_code == 404


def test_evolucao_do_professor_nao_traz_dado_cadastral(mundo, db):
    from datetime import date
    aluno = mundo["meu"]
    aluno.data_nascimento = date(2018, 5, 4)
    aluno.observacoes = "anotação sensível"
    db.commit()
    corpo = _login("prof@ev.local").get(_url(mundo["escola"], aluno.id, "evolucao")).json()
    assert set(corpo) == {"aluno_id", "nome", "linha_do_tempo", "resumo"}
    texto = str(corpo)
    assert "2018-05-04" not in texto and "anotação sensível" not in texto


def test_coordenador_ve_qualquer_aluno_e_secretaria_nao(mundo):
    coord, sec = _login("coord@ev.local"), _login("sec@ev.local")
    for rota in ROTAS_ABERTAS:
        assert coord.get(_url(mundo["escola"], mundo["fora"].id, rota)).status_code == 200
        assert sec.get(_url(mundo["escola"], mundo["meu"].id, rota)).status_code == 404


@pytest.mark.parametrize("rota", ROTAS_DE_GESTAO)
def test_professor_segue_sem_linha_do_tempo_nem_espelho(mundo, rota):
    r = _login("prof@ev.local").get(_url(mundo["escola"], mundo["meu"].id, rota))
    assert r.status_code == 403
