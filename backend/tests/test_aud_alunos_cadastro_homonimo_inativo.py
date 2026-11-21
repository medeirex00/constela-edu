"""“Adicionar aluno” com o nome de uma ficha ARQUIVADA, transferida ou fora da Lista
Piloto da mesma turma: o 409 diz que a ficha existe mas está fora da lista, e o
caminho para trazê-la de volta.

A porta única de identidade reconhece de propósito as fichas inativas da turma
(não duplicar a criança). Mas o 409 dizia "já está cadastrado nesta turma. Use o
cadastro existente" — e a busca de Alunos e o painel da turma (sem "Mostrar
arquivados") só mostram os ativos: o gestor não achava o cadastro que a mensagem
mandava usar.

Achado ALUNOS-7 da auditoria. Dados fictícios.
"""
import pytest

from app.models import Aluno, Matricula

API = "/api/v1"
SITUACOES = {"arquivado": "arquivad", "transferido": "transferid",
             "fora_lista_piloto": "fora da Lista Piloto"}


@pytest.mark.parametrize("status", list(SITUACOES))
def test_409_do_homonimo_inativo_diz_a_situacao_e_o_caminho(cliente, db, escola_completa,
                                                            status):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    ana = escola_completa["alunos"][0]
    ana.status = status
    db.commit()
    base = f"{API}/escolas/{escola.id}"
    assert cliente.get(f"{base}/alunos", params={"busca": "Ana Beatriz"}).json()["total"] == 0

    r = cliente.post(f"{base}/alunos", json={"nome": "Ana Beatriz Souza", "turma_id": turma.id})
    assert r.status_code == 409, r.text
    detalhe = r.json()["detail"]
    assert SITUACOES[status] in detalhe, detalhe
    assert "“Mostrar arquivados”" in detalhe and "“Reativar”" in detalhe, detalhe
    assert "Use o cadastro existente" not in detalhe, detalhe
    # Continua sem duplicar: nenhuma ficha nova.
    db.expire_all()
    assert db.query(Aluno).filter_by(escola_id=escola.id, nome="Ana Beatriz Souza").count() == 1


def test_409_do_homonimo_ativo_continua_como_antes(cliente, escola_completa):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    r = cliente.post(f"{API}/escolas/{escola.id}/alunos",
                     json={"nome": "Ana Beatriz Souza", "turma_id": turma.id})
    assert r.status_code == 409, r.text
    detalhe = r.json()["detail"]
    assert "já está cadastrado nesta turma. Use o cadastro existente." in detalhe
    assert "Reativar" not in detalhe


def test_correspondencia_insegura_com_ficha_inativa_diz_onde_ela_esta(cliente, db,
                                                                      escola_completa):
    """Nome parecido (não idêntico) com uma ficha ARQUIVADA da turma: o motor não
    decide sozinho (revisão) e a mensagem mandava conferir "a lista da turma", que
    não mostra a arquivada."""
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    parecida = Aluno(escola_id=escola.id, nome="Benedita Ficticia Laranjeira Prado",
                     status="arquivado")
    db.add(parecida)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=parecida.id, turma_id=turma.id,
                     ano_letivo=2026))
    db.commit()
    r = cliente.post(f"{API}/escolas/{escola.id}/alunos",
                     json={"nome": "Benedita Ficticia Prado", "turma_id": turma.id})
    assert r.status_code == 409, r.text
    detalhe = r.json()["detail"]
    assert "muito parecido" in detalhe, detalhe
    assert "“Mostrar arquivados”" in detalhe and "Benedita Ficticia Laranjeira Prado" in detalhe, \
        detalhe


def test_correspondencia_insegura_com_ficha_ativa_continua_como_antes(cliente, db,
                                                                      escola_completa):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    parecida = Aluno(escola_id=escola.id, nome="Benedita Ficticia Laranjeira Prado")
    db.add(parecida)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=parecida.id, turma_id=turma.id,
                     ano_letivo=2026))
    db.commit()
    r = cliente.post(f"{API}/escolas/{escola.id}/alunos",
                     json={"nome": "Benedita Ficticia Prado", "turma_id": turma.id})
    assert r.status_code == 409, r.text
    detalhe = r.json()["detail"]
    assert "Confira a lista da turma antes de cadastrar." in detalhe
    assert "Mostrar arquivados" not in detalhe
