"""Nº de chamada fora do que a coluna guarda é recusado com 422, em português — no
cadastro manual e em “Editar dados”.

``Aluno.numero_chamada`` é INTEGER (32 bits com sinal no PostgreSQL). A Lista
Piloto já tratava o valor grande (``lista_piloto.MAX_NUMERO_CHAMADA``), mas
``AlunoCreate``/``AlunoUpdate`` aceitavam qualquer inteiro: no PostgreSQL o commit
estourava (``NumericValueOutOfRange``) e a resposta era 500 "Erro interno". O
SQLite não tem o limite — a prova no banco de produção está em
``test_aud_alunos_numero_chamada_limite_pg.py``.

Achado ALUNOS-9 da auditoria. Dados fictícios.
"""
import pytest

from app.services.lista_piloto import MAX_NUMERO_CHAMADA

API = "/api/v1"


@pytest.mark.parametrize("valor", [MAX_NUMERO_CHAMADA + 1, 3_000_000_000, -1])
def test_numero_de_chamada_fora_do_limite_e_422(cliente, escola_completa, valor):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    ana = escola_completa["alunos"][0]
    base = f"{API}/escolas/{escola.id}"
    r1 = cliente.post(f"{base}/alunos", json={"nome": "Crianca Ficticia Nova",
                                              "turma_id": turma.id,
                                              "numero_chamada": valor})
    r2 = cliente.patch(f"{base}/alunos/{ana.id}", json={"numero_chamada": valor})
    for r in (r1, r2):
        assert r.status_code == 422, f"{r.status_code} {r.text[:200]}"
        mensagens = " ".join(e["msg"] for e in r.json()["detail"])
        assert "nº de chamada" in mensagens.lower(), mensagens


def test_numero_de_chamada_valido_continua_aceito(cliente, escola_completa):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    ana = escola_completa["alunos"][0]
    base = f"{API}/escolas/{escola.id}"
    r = cliente.post(f"{base}/alunos", json={"nome": "Crianca Ficticia Nova",
                                             "turma_id": turma.id,
                                             "numero_chamada": MAX_NUMERO_CHAMADA})
    assert r.status_code == 201, r.text
    for valor in (0, 7, None):
        r = cliente.patch(f"{base}/alunos/{ana.id}", json={"numero_chamada": valor})
        assert r.status_code == 200, r.text
        assert r.json()["numero_chamada"] == valor
