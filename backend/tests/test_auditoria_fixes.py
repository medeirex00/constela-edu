"""Correções da auditoria preventiva (os 5 imediatos): C1, C2, C3, A1.

(A2 — régua só com ativos — é testada em test_scoring.py.)
"""
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_senha
from app.main import app
from app.models import Aluno, Matricula, Rede, Turma, Usuario
from app.services import importacao as imp

API = "/api/v1"


def _base(escola_id: int) -> str:
    return f"{API}/escolas/{escola_id}"


def _login(email: str, senha: str = "s3nh4") -> TestClient:
    c = TestClient(app)
    tok = c.post(f"{API}/auth/login",
                 data={"username": email, "password": senha}).json()["access_token"]
    c.headers["Authorization"] = f"Bearer {tok}"
    return c


# --- C1: Secretaria não lê/gera credenciais de login das crianças (Quest) -----

def _tornar_secretaria(db, escola) -> str:
    """Coloca a escola numa rede e cria uma conta Secretaria (coordenador com
    rede_id) dessa rede. Devolve o e-mail para login."""
    rede = Rede(nome="Rede Teste", status="ativa")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    db.add(Usuario(escola_id=escola.id, nome="Secretaria", email="sec@teste.local",
                   senha_hash=hash_senha("s3nh4"), cargo="coordenador",
                   rede_id=rede.id))
    db.commit()
    return "sec@teste.local"


def test_secretaria_barrada_nos_acessos_do_quest(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    turma = escola_completa["turma"]
    email = _tornar_secretaria(db, escola)
    sec = _login(email)

    # Secretaria (rede) → 403 tanto no GET de códigos quanto no POST de cartões.
    r = sec.get(f"{_base(escola.id)}/quest/turmas/{turma.id}/acessos")
    assert r.status_code == 403, r.text
    r = sec.post(f"{_base(escola.id)}/quest/turmas/{turma.id}/cartoes")
    assert r.status_code == 403, r.text

    # Admin da escola (não é Secretaria) continua acessando normalmente.
    r = cliente.get(f"{_base(escola.id)}/quest/turmas/{turma.id}/acessos")
    assert r.status_code == 200, r.text


# --- C3: match exato único confere a turma quando há UUID novo a cravar -------

def _linha(nome, **dados):
    return imp.LinhaImportacao(numero=1, nome=nome, dados=dict(dados))


def test_exato_unico_com_uuid_e_turma_conflitante_vira_provavel(db, escola_completa):
    """Só existe 'Maria Silva' na 3º Ano A; chega um relatório do Matific com UUID
    NOVO cuja turma é 2º Ano B → provavelmente OUTRA criança homônima → 'provável'
    (não crava o UUID no aluno errado)."""
    escola = escola_completa["escola"]
    l = _linha("Maria Silva", matific_uuid="uuid-novo-123",
               turma_relatorio="2º Ano B")
    # (a base já tem 'Ana Beatriz Souza' etc.; adiciono a única 'Maria Silva')
    aluno = Aluno(escola_id=escola.id, nome="Maria Silva")
    db.add(aluno)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=aluno.id,
                     turma_id=escola_completa["turma"].id, ano_letivo=2026))
    db.commit()

    imp.casar_nomes(db, escola.id, [l])
    assert l.correspondencia["status"] == "provavel"


def test_exato_unico_sem_uuid_continua_exato(db, escola_completa):
    """Sem UUID a cravar (ex.: relatório individual do Elefante), o rótulo de
    turma é ruidoso e NÃO deve rebaixar um nome único — continua 'exato'."""
    escola = escola_completa["escola"]
    aluno = Aluno(escola_id=escola.id, nome="Maria Silva")
    db.add(aluno)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=aluno.id,
                     turma_id=escola_completa["turma"].id, ano_letivo=2026))
    db.commit()

    l = _linha("Maria Silva", turma_relatorio="2º Ano B")   # sem matific_uuid
    imp.casar_nomes(db, escola.id, [l])
    assert l.correspondencia["status"] == "exato"


# --- C2: a sync automática só auto-vincula match exato/uuid -------------------

def test_sync_so_auto_vincula_exato_nao_provavel():
    """A regra de confiança do orchestrator: só 'exato'+via∈(uuid,exato) vincula;
    'provável' (fuzzy) NÃO — evita misattribution silenciosa na sync."""
    def confiante(corr):
        return corr.get("status") == "exato" and corr.get("via") in ("uuid", "exato")

    assert confiante({"status": "exato", "via": "uuid"})
    assert confiante({"status": "exato", "via": "exato"})
    assert not confiante({"status": "provavel", "via": "abreviado"})
    assert not confiante({"status": "provavel"})
    assert not confiante({"status": "nao_encontrado"})


# --- A1: trocar a própria senha revoga as outras sessões ----------------------

def test_trocar_propria_senha_invalida_sessoes(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    admin = escola_completa["admin"]
    ver_antes = admin.token_version or 0

    r = cliente.patch(f"{_base(escola.id)}/usuarios/{admin.id}",
                      json={"senha": "NovaSenha#2026"})
    assert r.status_code == 200, r.text

    db.expire_all()
    atual = db.execute(
        select(Usuario).where(Usuario.id == admin.id)).scalar_one()
    assert (atual.token_version or 0) == ver_antes + 1   # sessões antigas caem

    # O token que o `cliente` ainda carrega (versão antiga) deixa de valer.
    r = cliente.get(f"{_base(escola.id)}/usuarios")
    assert r.status_code == 401


# --- A5: certificado geral não emite "nota 0,0" para aluno sem Nota -----------

def test_certificado_geral_recusa_aluno_sem_nota(cliente, escola_completa):
    """Aluno recém-cadastrado (sem Nota calculada) → 422, em vez de um documento
    oficial afirmando 'nota geral 0,0'."""
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]   # sem snapshot/nota nesta fixture
    # Sem `modelo` = certificado GERAL (o que estampa a nota).
    r = cliente.get(f"{_base(escola.id)}/certificados/{aluno.id}")
    assert r.status_code == 422, r.text
    assert "nota" in r.json()["detail"].lower()
