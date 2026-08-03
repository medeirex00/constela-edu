"""Notificações acionáveis por perfil (Fase 2a).

Cobre: emissão a partir da auditoria (com a ROTA de ação), feed POR PERFIL,
blindagem de PII (a Secretaria só recebe escopo 'rede', nunca 'escola' nem
aluno_id; o professor só avisos das turmas dele) e o estado de leitura por
usuário (contador + marcar-lidas). O professor NÃO toma mais 403 (o feed antigo
derivado da auditoria barrava professor e Secretaria)."""
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import Aluno, Matricula, Notificacao, Professor, Rede, Turma, Usuario
from app.services import audit


def _login(email: str, senha: str = "s3nh4") -> TestClient:
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", data={"username": email, "password": senha})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _cenario(db, escola_completa):
    escola = escola_completa["escola"]
    turma = escola_completa["turma"]           # 3 alunos matriculados (2026)
    aluno_do_prof = escola_completa["alunos"][0]

    rede = Rede(nome="Rede Notif", status="ativa")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id

    # Professor vinculado à turma da escola (RBAC casa por Professor.email).
    prof = Professor(escola_id=escola.id, nome="Prof Notif", email="prof@notif.local")
    db.add(prof)
    db.flush()
    turma.professor_id = prof.id

    # Aluno FORA da turma do professor (outra turma, sem professor).
    turma2 = Turma(escola_id=escola.id, nome="Outra Turma", ano_escolar="4º Ano",
                   ano_letivo=2026)
    db.add(turma2)
    db.flush()
    fora = Aluno(escola_id=escola.id, nome="Aluno Fora", status="ativo")
    db.add(fora)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=fora.id, turma_id=turma2.id,
                     ano_letivo=2026))

    db.add(Usuario(escola_id=escola.id, nome="Secretaria", email="sec@notif.local",
                   senha_hash=hash_senha("s3nh4"), cargo="coordenador", rede_id=rede.id))
    db.add(Usuario(escola_id=escola.id, nome="Prof User", email="prof@notif.local",
                   senha_hash=hash_senha("s3nh4"), cargo="professor"))
    db.commit()
    return {"escola": escola.id, "rede": rede.id,
            "aluno_prof": aluno_do_prof.id, "fora": fora.id}


def test_emissao_da_auditoria_cria_notificacao_com_rota(db, escola_completa):
    ids = _cenario(db, escola_completa)
    audit.registrar(db, "importacao.concluida", escola_id=ids["escola"])
    db.commit()
    n = db.query(Notificacao).filter_by(tipo="importacao.concluida").first()
    assert n is not None
    assert n.escopo == "escola" and n.escola_id == ids["escola"]
    assert n.rota == "/importacoes"
    assert n.aluno_id is None


def test_feed_por_perfil_e_blindagem_de_pii(db, escola_completa):
    ids = _cenario(db, escola_completa)
    # Evento da escola (sem aluno) + aluno do prof + aluno de fora + evento de rede.
    audit.registrar(db, "importacao.concluida", escola_id=ids["escola"])
    audit.registrar(db, "aluno.criado", escola_id=ids["escola"],
                    entidade="aluno", entidade_id=ids["aluno_prof"])
    audit.registrar(db, "aluno.criado", escola_id=ids["escola"],
                    entidade="aluno", entidade_id=ids["fora"])
    db.add(Notificacao(escopo="rede", rede_id=ids["rede"], tipo="rede.teste",
                       titulo="Aviso da rede", rota="/rede"))
    db.commit()

    admin = _login("admin@teste.local")       # gestor da escola (cargo admin, não-global)
    sec = _login("sec@notif.local")
    prof = _login("prof@notif.local")

    tipos_admin = {n["tipo"] for n in admin.get("/api/v1/notificacoes").json()}
    assert "importacao.concluida" in tipos_admin
    assert "aluno.criado" in tipos_admin
    assert "rede.teste" not in tipos_admin     # rede não é da escola

    # Secretaria: SÓ escopo rede; nunca escola nem aluno_id (PII).
    feed_sec = sec.get("/api/v1/notificacoes").json()
    assert {n["tipo"] for n in feed_sec} == {"rede.teste"}
    assert all(n["rota"] == "/rede" for n in feed_sec)

    # Professor: só o aviso que toca o aluno DA TURMA dele (nem o import sem aluno,
    # nem o aluno de fora).
    feed_prof = prof.get("/api/v1/notificacoes").json()
    assert len(feed_prof) == 1
    assert feed_prof[0]["tipo"] == "aluno.criado"
    assert feed_prof[0]["rota"] == f"/alunos/{ids['aluno_prof']}"


def test_contador_e_marcar_lidas(db, escola_completa):
    ids = _cenario(db, escola_completa)
    audit.registrar(db, "importacao.concluida", escola_id=ids["escola"])
    audit.registrar(db, "notas.recalculadas", escola_id=ids["escola"])
    db.commit()

    admin = _login("admin@teste.local")
    assert admin.get("/api/v1/notificacoes/contador").json()["nao_lidas"] == 2
    assert admin.post("/api/v1/notificacoes/marcar-lidas").status_code == 204
    assert admin.get("/api/v1/notificacoes/contador").json()["nao_lidas"] == 0


def test_professor_nao_toma_403_no_feed(db, escola_completa):
    _cenario(db, escola_completa)
    prof = _login("prof@notif.local")
    assert prof.get("/api/v1/notificacoes").status_code == 200
    assert prof.get("/api/v1/notificacoes/contador").status_code == 200
