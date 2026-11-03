"""Painel de gestão da turma (`GET /turmas/{id}/alunos`): `incluir_inativos`
serve à GESTÃO (restaurar ou apagar de vez, ações só de admin/coordenador).

O professor restrito à própria turma segue vendo só as fichas ATIVAS, como em
`/alunos`, no perfil e na evolução (`permissoes.alunos_permitidos` exclui
inativos por padrão). Antes, `?incluir_inativos=true` devolvia ao professor as
fichas excluídas, transferidas e arquivadas da turma dele, com nome, foto, nota
e posição.

Mundo sintético; nenhum dado real; nada sai para a internet.
"""
from fastapi.testclient import TestClient

from app.core.security import criar_token, hash_senha
from app.main import app
from app.models import Aluno, Escola, Matricula, Professor, Turma, Usuario

SENHA = "s3nh4-sintetica-inativos"
ATIVO = "ALUNO_ATIVO_TI"
INATIVOS = {"excluido": "ALUNO_EXCLUIDO_TI",
            "transferido": "ALUNO_TRANSFERIDO_TI",
            "arquivado": "ALUNO_ARQUIVADO_TI"}


def _cliente(usuario: Usuario) -> TestClient:
    c = TestClient(app)
    c.headers["Authorization"] = (
        f"Bearer {criar_token(usuario.id, usuario.token_version or 0)}")
    return c


def _usuario(db, escola_id: int, email: str, cargo: str) -> Usuario:
    u = Usuario(escola_id=escola_id, nome=email.split("@")[0].upper(),
                email=email, senha_hash=hash_senha(SENHA), cargo=cargo)
    db.add(u)
    db.commit()
    return u


def _mundo(db):
    escola = Escola(nome="ESCOLA_TURMA_INATIVOS", ano_letivo_ativo=2026)
    db.add(escola)
    db.flush()
    prof_u = _usuario(db, escola.id, "prof.ti@sint.local", "professor")
    coord = _usuario(db, escola.id, "coord.ti@sint.local", "coordenador")
    admin = _usuario(db, escola.id, "admin.ti@sint.local", "admin")
    prof = Professor(escola_id=escola.id, nome="PROF_TI",
                     email="prof.ti@sint.local")
    db.add(prof)
    db.flush()
    turma = Turma(escola_id=escola.id, nome="4º Ano A", ano_escolar="4º Ano",
                  ano_letivo=2026, professor_id=prof.id)
    db.add(turma)
    db.flush()
    for status_ficha, nome in (("ativo", ATIVO), *INATIVOS.items()):
        aluno = Aluno(escola_id=escola.id, nome=nome, status=status_ficha)
        db.add(aluno)
        db.flush()
        db.add(Matricula(escola_id=escola.id, aluno_id=aluno.id,
                         turma_id=turma.id, ano_letivo=2026))
    db.commit()
    return escola, turma, prof_u, coord, admin


def _nomes(usuario: Usuario, escola_id: int, turma_id: int, sufixo: str = "") -> set[str]:
    r = _cliente(usuario).get(
        f"/api/v1/escolas/{escola_id}/turmas/{turma_id}/alunos{sufixo}")
    assert r.status_code == 200, r.text
    return {item["nome"] for item in r.json()}


def test_professor_nao_recebe_fichas_inativas_com_incluir_inativos(db):
    escola, turma, prof_u, _coord, _admin = _mundo(db)
    assert _nomes(prof_u, escola.id, turma.id) == {ATIVO}
    assert _nomes(prof_u, escola.id, turma.id, "?incluir_inativos=true") == {ATIVO}


def test_gestao_continua_recebendo_fichas_inativas(db):
    escola, turma, _prof_u, coord, admin = _mundo(db)
    for quem in (coord, admin):
        assert _nomes(quem, escola.id, turma.id) == {ATIVO}
        assert (_nomes(quem, escola.id, turma.id, "?incluir_inativos=true")
                == {ATIVO, *INATIVOS.values()})
