"""Consolidação de turmas duplicadas: chave canônica + detecção + migração.

Cobre o caso do dono: "1 ANO A TARDE ANUAL (300302821)" e "1ºA" são a MESMA
sala; a curta é a canônica e os alunos da longa migram para ela.
"""
from app.core.security import hash_senha
from app.models import Aluno, Matricula, Professor, Turma, Usuario
from app.services import matriculas as mat
from app.services import turmas_dedup

API = "/api/v1"


def test_chave_canonica_reconhece_a_mesma_sala():
    k = mat.chave_canonica
    # Forma longa (SED) e curta (Lista Piloto) → mesma chave.
    assert k("1 ANO A TARDE ANUAL (300302821)") == "1|A|T"
    assert k("1ºA", "1º Ano", "tarde") == "1|A|T"
    assert k("1 ANO A TARDE ANUAL (300302821)") == k("1ºA", turno="tarde")
    assert k("2 ANO B INTEGRAL (300303178)") == "2|B|I"
    # A letra é a da SALA — não pega o "A" de ANUAL.
    assert k("1 ANO A TARDE ANUAL").startswith("1|A")
    # Turnos diferentes NÃO se fundem.
    assert k("1º Ano A manhã") != k("1º Ano A tarde")
    assert k("1 ANO A MANHA") == "1|A|M"
    # Formatos fora do padrão série+letra caem no nome normalizado (não fundem).
    assert "|" not in k("Maternal II")
    assert "|" not in k("EJA")


def _cenario(db, escola_id):
    curta = Turma(escola_id=escola_id, nome="1ºA", ano_escolar="1ºA",
                  ano_letivo=2026, turno="tarde")
    longa = Turma(escola_id=escola_id, nome="1 ANO A TARDE ANUAL (300302821)",
                  ano_escolar="1º Ano", ano_letivo=2026)
    db.add_all([curta, longa])
    db.flush()
    for nome, turma in [("Ana Souza", curta), ("Bia Lima", curta), ("Caio Melo", longa)]:
        a = Aluno(escola_id=escola_id, nome=nome)
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=escola_id, aluno_id=a.id, turma_id=turma.id, ano_letivo=2026))
    db.commit()
    return curta, longa


def test_detectar_sugere_a_curta_como_canonica(db, escola_completa):
    escola = escola_completa["escola"]
    curta, longa = _cenario(db, escola.id)
    grupos = turmas_dedup.detectar(db, escola.id)
    g = next(x for x in grupos if x["chave"] == "1|A|T")
    assert g["canonica"]["nome"] == "1ºA"          # curta = canônica
    assert g["canonica"]["alunos"] == 2
    assert [d["nome"] for d in g["duplicadas"]] == ["1 ANO A TARDE ANUAL (300302821)"]
    assert g["duplicadas"][0]["alunos"] == 1


def test_consolidar_move_alunos_e_remove_a_duplicada(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    curta, longa = _cenario(db, escola.id)

    r = cliente.post(f"{API}/escolas/{escola.id}/turmas/duplicadas/corrigir",
                     json=[{"canonica_id": curta.id, "duplicada_ids": [longa.id]}])
    assert r.status_code == 200, r.text
    assert r.json()["alunos_movidos"] == 1
    assert r.json()["turmas_removidas"] == 1

    # Verifica pela própria API (sessão fresca, autoritativa): a longa sumiu da
    # lista e a curta reúne os 3 alunos.
    nomes = [t["nome"] for t in cliente.get(f"{API}/escolas/{escola.id}/turmas").json()]
    assert "1 ANO A TARDE ANUAL (300302821)" not in nomes
    assert "1ºA" in nomes
    alunos = cliente.get(f"{API}/escolas/{escola.id}/turmas/{curta.id}/alunos").json()
    assert len(alunos) == 3


def test_consolidar_e_bloqueado_para_professor(db, escola_completa):
    from fastapi.testclient import TestClient

    from app.main import app
    escola = escola_completa["escola"]
    curta, longa = _cenario(db, escola.id)
    db.add(Usuario(escola_id=escola.id, nome="Prof", email="prof@ed.local",
                   senha_hash=hash_senha("s3nh4"), cargo="professor"))
    db.commit()

    c = TestClient(app)
    tok = c.post("/api/v1/auth/login", data={"username": "prof@ed.local", "password": "s3nh4"}).json()
    c.headers["Authorization"] = f"Bearer {tok['access_token']}"
    r = c.post(f"{API}/escolas/{escola.id}/turmas/duplicadas/corrigir",
               json=[{"canonica_id": curta.id, "duplicada_ids": [longa.id]}])
    assert r.status_code == 403


def test_prioridade_professor_vira_canonica(db, escola_completa):
    """Item 5: a turma COM professor é a principal, mesmo com nome mais longo e
    menos alunos que a duplicada sem professor."""
    escola = escola_completa["escola"]
    prof = Professor(escola_id=escola.id, nome="Prof A")
    db.add(prof)
    db.flush()
    curta = Turma(escola_id=escola.id, nome="1ºA", ano_escolar="1ºA",
                  ano_letivo=2026, turno="tarde")                 # 2 alunos, SEM professor
    longa = Turma(escola_id=escola.id, nome="1 ANO A TARDE ANUAL (300302821)",
                  ano_escolar="1º Ano", ano_letivo=2026, professor_id=prof.id)  # 1 aluno, COM professor
    db.add_all([curta, longa])
    db.flush()
    for nome, t in [("A1", curta), ("A2", curta), ("B1", longa)]:
        a = Aluno(escola_id=escola.id, nome=nome)
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=t.id, ano_letivo=2026))
    db.commit()

    g = next(x for x in turmas_dedup.detectar(db, escola.id) if x["chave"] == "1|A|T")
    assert g["canonica"]["id"] == longa.id     # tem professor → canônica (item 5, prioridade 1)


def test_professores_diferentes_nao_sao_unidos(db, escola_completa):
    """Item 7: mesma sala aparente (1|A|T) mas titulares DIFERENTES = grupos
    distintos → não entram para consolidação."""
    escola = escola_completa["escola"]
    p1 = Professor(escola_id=escola.id, nome="P1")
    p2 = Professor(escola_id=escola.id, nome="P2")
    db.add_all([p1, p2])
    db.flush()
    db.add_all([
        Turma(escola_id=escola.id, nome="1ºA", ano_escolar="1ºA",
              ano_letivo=2026, turno="tarde", professor_id=p1.id),
        Turma(escola_id=escola.id, nome="1 ANO A TARDE (x)", ano_escolar="1º Ano",
              ano_letivo=2026, professor_id=p2.id),
    ])
    db.commit()
    assert not any(x["chave"] == "1|A|T" for x in turmas_dedup.detectar(db, escola.id))
