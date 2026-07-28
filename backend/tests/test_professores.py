"""Criação AUTOMÁTICA de contas de professor (login = NomeSobrenome em CamelCase,
senha = o mesmo usuário em minúsculo + 123, ex.: paulavilela123). Idempotente
entre fontes (Lista Piloto e Elefante) e em reimportações; senha só como HASH;
username único na rede."""
from sqlalchemy import func, select

from app.core.security import verificar_senha
from app.models import Aluno, Professor, Turma, Usuario
from app.services import professores as svc


# --- Convenção pedida pelo gestor -------------------------------------------

def test_credenciais_seguem_a_convencao():
    assert svc.credenciais_professor("Paula Vilela") == ("PaulaVilela", "paulavilela123")
    # Vários nomes → Primeiro + ÚLTIMO.
    assert svc.credenciais_professor("Regiane Gomes Sousa") == ("RegianeSousa", "regianesousa123")
    # Um nome só.
    assert svc.credenciais_professor("Zuleide") == ("Zuleide", "zuleide123")
    # Acentos e caixa são normalizados (usuário sem acento; senha = o mesmo em minúsculo).
    assert svc.credenciais_professor("josé ANTÔNIO") == ("JoseAntonio", "joseantonio123")
    # Lixo → None (não cria conta).
    assert svc.credenciais_professor("   ") is None
    assert svc.credenciais_professor("") is None


def test_separa_varios_professores_de_um_campo():
    assert svc.nomes_de_professores("Paula Vilela, João Silva") == ["Paula Vilela", "João Silva"]
    assert svc.nomes_de_professores("Ana; Bruno / Carla e Diana") == \
        ["Ana", "Bruno", "Carla", "Diana"]
    # Dedup (case/acards) e limpeza de vazios.
    assert svc.nomes_de_professores("Paula, paula ,") == ["Paula"]
    assert svc.nomes_de_professores("") == []


# --- Criação/idempotência ----------------------------------------------------

def test_cria_professor_e_conta_de_login(db, escola_completa):
    escola = escola_completa["escola"]
    prof, novo = svc.garantir_professor(db, escola.id, "Paula Vilela")
    db.commit()
    assert novo is True and prof is not None

    user = db.execute(select(Usuario).where(Usuario.username == "PaulaVilela")).scalars().one()
    assert user.cargo == "professor" and user.status == "ativo"
    assert user.escola_id == escola.id
    # RBAC: o e-mail do Usuario casa com o do Professor (permissoes.turmas_permitidas).
    assert user.email == prof.email
    # Senha guardada só como HASH — nunca em texto puro.
    assert user.senha_hash != "paulavilela123"
    assert verificar_senha("paulavilela123", user.senha_hash)


def test_idempotente_nao_duplica(db, escola_completa):
    escola = escola_completa["escola"]
    svc.garantir_professor(db, escola.id, "Paula Vilela")
    db.commit()
    prof2, novo2 = svc.garantir_professor(db, escola.id, "PAULA vilela")  # mesma pessoa
    db.commit()
    assert novo2 is False
    n_users = db.execute(select(func.count()).select_from(Usuario)
                         .where(Usuario.username == "PaulaVilela")).scalar()
    n_profs = db.execute(select(func.count()).select_from(Professor)
                         .where(Professor.escola_id == escola.id)).scalar()
    assert n_users == 1 and n_profs == 1


def test_username_colidido_ganha_sufixo(db, escola_completa):
    """Dois 'João Silva' (mesmo nome de usuário) → o 2º vira JoaoSilva2 (username
    é único na REDE, colisão insensível à caixa). São pessoas diferentes (nomes
    idênticos, escolas/ordens)."""
    escola = escola_completa["escola"]
    # Ocupa 'joaosilva' com um usuário pré-existente qualquer.
    db.add(Usuario(escola_id=escola.id, nome="Outro", email="x@y.z",
                   username="joaosilva", senha_hash="h", cargo="professor"))
    db.commit()
    prof, novo = svc.garantir_professor(db, escola.id, "João Silva")
    db.commit()
    user = db.execute(select(Usuario).where(Usuario.email == prof.email)).scalars().one()
    assert novo is True and user.username == "JoaoSilva2"


def test_turma_cria_todos_e_vincula_titular(db, escola_completa):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    assert turma.professor_id is None

    criados = svc.garantir_professores_da_turma(
        db, escola.id, turma, "Paula Vilela, João Silva")
    db.commit()
    assert criados == 2
    # Titular = o PRIMEIRO da lista.
    titular = db.get(Professor, turma.professor_id)
    assert titular.nome == "Paula Vilela"

    # Reimportar a MESMA turma não duplica nem recria (idempotente).
    criados2 = svc.garantir_professores_da_turma(
        db, escola.id, turma, "Paula Vilela, João Silva")
    db.commit()
    assert criados2 == 0
    total = db.execute(select(func.count()).select_from(Usuario)
                       .where(Usuario.cargo == "professor")).scalar()
    assert total == 2


def test_resolver_turmas_cria_professores_da_lista_piloto(db, escola_completa):
    """Wiring do import da Lista Piloto: _resolver_turmas cria as turmas E as
    contas dos professores, devolvendo a contagem (3ª posição da tupla)."""
    from app.routers import importacoes as imp
    from app.services.lista_piloto import TurmaMatriculas

    escola = escola_completa["escola"]
    turmas_analise = [
        TurmaMatriculas(nome="4º Ano C", ano_escolar="4º Ano", professor="Regiane Gomes Sousa"),
        TurmaMatriculas(nome="4º Ano D", ano_escolar="4º Ano", professor="Paula Vilela"),
    ]
    resolvidas, criadas, profs = imp._resolver_turmas(db, escola.id, 2026, turmas_analise)
    db.commit()
    assert criadas == 2 and profs == 2
    # A turma ganhou o titular vinculado (RBAC).
    assert resolvidas[0].professor_id is not None
    titular = db.get(Professor, resolvidas[0].professor_id)
    assert titular.nome == "Regiane Gomes Sousa"
    assert db.execute(select(Usuario).where(Usuario.username == "RegianeSousa")
                      ).scalars().first() is not None


def test_cross_fonte_nao_duplica(db, escola_completa):
    """Lista Piloto cria 'Paula Vilela'; depois o Elefante detecta a mesma
    professora na mesma turma → nenhuma conta nova."""
    escola = escola_completa["escola"]
    t2 = Turma(escola_id=escola.id, nome="5º Ano B", ano_escolar="5º Ano", ano_letivo=2026)
    db.add(t2)
    db.flush()

    svc.garantir_professores_da_turma(db, escola.id, t2, "Paula Vilela")  # Lista Piloto
    db.commit()
    criados = svc.garantir_professores_da_turma(db, escola.id, t2, "Paula Vilela")  # Elefante
    db.commit()
    assert criados == 0


# --- Regressões da revisão de segurança -------------------------------------

def test_match_acento_insensivel_nao_duplica(db, escola_completa):
    """Lista Piloto grava 'Antônio Silva'; o Elefante manda 'Antonio Silva' (sem
    acento). É a MESMA pessoa → não cria segunda conta (senão viraria login
    fantasma sem acesso à turma)."""
    escola = escola_completa["escola"]
    svc.garantir_professor(db, escola.id, "Antônio Silva")
    db.commit()
    prof, novo = svc.garantir_professor(db, escola.id, "Antonio  SILVA")
    db.commit()
    assert novo is False
    assert db.execute(select(func.count()).select_from(Professor)
                      .where(Professor.escola_id == escola.id)).scalar() == 1


def test_email_ocupado_recebe_sufixo(db, escola_completa):
    """Username livre mas o e-mail derivado já existe → escolhe um par
    (username, email) AMBOS livres (o e-mail também é unique)."""
    escola = escola_completa["escola"]
    db.add(Usuario(escola_id=escola.id, nome="Outro", username="outrouser",
                   email="paulavilela@professor.constelaedu.com",
                   senha_hash="h", cargo="professor"))
    db.commit()
    prof, novo = svc.garantir_professor(db, escola.id, "Paula Vilela")
    db.commit()
    assert novo is True
    user = db.execute(select(Usuario).where(Usuario.email == prof.email)).scalars().one()
    assert user.username == "PaulaVilela2"
    assert prof.email == "paulavilela2@professor.constelaedu.com"


def test_falha_de_professor_nao_derruba_import_de_alunos(db, escola_completa, monkeypatch):
    """INVARIANTE: se a criação do professor explodir, o SAVEPOINT limpa a sessão
    e a importação de ALUNOS segue normalmente (professor é acessório)."""
    from app.routers import importacoes as imp
    from app.services import professores as profsvc
    from app.services.lista_piloto import TurmaMatriculas

    escola = escola_completa["escola"]

    def boom(_db, _escola_id, _turma, _txt):
        _db.add(Usuario(escola_id=_escola_id, nome="Ruim"))  # sem email/senha → flush falha
        _db.flush()
    monkeypatch.setattr(profsvc, "garantir_professores_da_turma", boom)

    turmas = [TurmaMatriculas(nome="6º Ano X", ano_escolar="6º Ano", professor="Paula Vilela")]
    resolvidas, criadas, profs = imp._resolver_turmas(db, escola.id, 2026, turmas)
    assert criadas == 1 and profs == 0  # professor falhou; a turma foi criada

    # A sessão NÃO foi poluída — o aluno entra sem PendingRollbackError.
    db.add(Aluno(escola_id=escola.id, nome="Aluno Pós-Falha"))
    db.flush()
    db.commit()
    assert db.execute(select(func.count()).select_from(Aluno)
                      .where(Aluno.nome == "Aluno Pós-Falha")).scalar() == 1


def test_coordenador_edita_nome_do_professor(db, escola_completa):
    """Coordenador pode COMPLETAR/EDITAR o nome do professor (ex.: apelido da
    Lista Piloto → nome completo). Professor comum não pode (403)."""
    from fastapi.testclient import TestClient

    from app.core.security import hash_senha
    from app.main import app

    escola = escola_completa["escola"]
    prof = Professor(escola_id=escola.id, nome="CAMILA")
    db.add(prof)
    db.add(Usuario(escola_id=escola.id, nome="Coord", email="coord@ed.local",
                   senha_hash=hash_senha("s3nh4"), cargo="coordenador"))
    db.add(Usuario(escola_id=escola.id, nome="Prof", email="prof@ed.local",
                   senha_hash=hash_senha("s3nh4"), cargo="professor"))
    db.commit()

    def login(email):
        c = TestClient(app)
        r = c.post("/api/v1/auth/login", data={"username": email, "password": "s3nh4"})
        assert r.status_code == 200, r.text
        c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        return c

    rota = f"/api/v1/escolas/{escola.id}/professores/{prof.id}"
    r = login("coord@ed.local").patch(rota, json={"nome": "Camila Souza Oliveira"})
    assert r.status_code == 200, r.text
    assert r.json()["nome"] == "Camila Souza Oliveira"
    db.refresh(prof)
    assert prof.nome == "Camila Souza Oliveira"
    # professor comum é barrado
    assert login("prof@ed.local").patch(rota, json={"nome": "X"}).status_code == 403
