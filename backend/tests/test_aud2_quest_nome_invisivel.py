"""Quest — o nome escolhido pela criança não aceita letra invisível (G_QUEST-4).

``validar_nome_exibicao`` aceitava qualquer caractere com ``isalpha()``. O HANGUL
FILLER (U+3164, o "nome invisível" que circula em jogos) e os outros preenchimentos
do Hangul (U+115F, U+1160, U+FFA0) são da categoria Lo — "letra" para o Python —, mas
não desenham nada, e o ``strip()`` não os tira. A criança que colava três U+3164
passava a ser chamada de "" em toda fala, e o "É você, {nome}?" do /quem — que existe para quem
digitou o código errado perceber que a conta é de outra pessoa — saía em branco.

Agora o nome com caractere invisível é recusado (422, nada gravado) e um nome desses
que já esteja gravado não vai para as falas: elas usam o primeiro nome do cadastro.
Dados fictícios.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.quest.models import QuestCredencialAluno, QuestPerfil
from app.quest.routers import auth as quest_auth_router
from app.quest.services import perfis

INVISIVEIS = ["\u3164", "\u115f", "\u1160", "\uffa0"]


@pytest.fixture(autouse=True)
def _limitadores_limpos():
    for lim in (quest_auth_router.limitador_codigo, quest_auth_router.limitador_ip,
                quest_auth_router.limitador_codigo_conta,
                quest_auth_router.limitador_ip_falha,
                quest_auth_router.limitador_global_falha):
        lim._eventos.clear()
    yield


@pytest.mark.parametrize("invisivel", INVISIVEIS, ids=lambda c: f"U+{ord(c):04X}")
def test_validar_recusa_nome_so_de_preenchimento(invisivel):
    assert invisivel.isalpha() and invisivel.strip() == invisivel
    with pytest.raises(ValueError):
        perfis.validar_nome_exibicao(invisivel * 3)


@pytest.mark.parametrize("nome", ["Bia\u3164", "\u3164Bia", "Bi\u3164a", "Ana \uffa0 Luz"])
def test_validar_recusa_letra_invisivel_misturada(nome):
    with pytest.raises(ValueError):
        perfis.validar_nome_exibicao(nome)


@pytest.mark.parametrize("nome, salvo", [
    ("ana luz", "Ana Luz"), ("João", "João"), ("Zoë", "Zoë"), ("Mía", "Mía")])
def test_nomes_visiveis_continuam_aceitos(nome, salvo):
    assert perfis.validar_nome_exibicao(nome) == salvo


def test_patch_nome_invisivel_e_422_e_o_e_voce_mostra_um_nome(cliente, db, escola_completa):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    aluno = escola_completa["alunos"][0]
    r = cliente.post(f"/api/v1/escolas/{escola.id}/quest/turmas/{turma.id}/cartoes")
    assert r.status_code == 200, r.text
    db.expire_all()
    codigo = db.execute(select(QuestCredencialAluno.codigo_login)
                        .where(QuestCredencialAluno.aluno_id == aluno.id)).scalar_one()
    sessao = TestClient(app).post("/api/v1/quest/auth/entrar", json={"codigo": codigo})
    assert sessao.status_code == 200, sessao.text
    cab = {"Authorization": f"Bearer {sessao.json()['access_token']}"}

    r = TestClient(app).patch("/api/v1/quest/perfil/nome", headers=cab,
                              json={"nome": "\u3164\u3164\u3164"})
    assert r.status_code == 422, r.text
    db.expire_all()
    assert db.execute(select(QuestPerfil.nome_exibicao)
                      .where(QuestPerfil.aluno_id == aluno.id)).scalar_one() in (None, "")

    quem = TestClient(app).post("/api/v1/quest/auth/quem", json={"codigo": codigo})
    assert quem.status_code == 200, quem.text
    assert quem.json()["nome"] == perfis.primeiro_nome_cadastro(aluno.nome)


def test_nome_invisivel_ja_gravado_nao_vai_para_as_falas(db, escola_completa):
    aluno = escola_completa["alunos"][0]
    perfil = perfis.obter_ou_criar_perfil(db, aluno)
    perfil.nome_exibicao = "\u3164\u3164\u3164"   # gravado antes desta correção
    assert perfis.nome_para_falas(perfil, aluno.nome) == perfis.primeiro_nome_cadastro(aluno.nome)
