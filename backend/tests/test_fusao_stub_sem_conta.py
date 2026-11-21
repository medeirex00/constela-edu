"""A3 (resíduo) — CARACTERIZAÇÃO, não aprovação: stub SEM conta fundido na ficha
oficial leva a próxima coleta à revisão, UMA vez por conta.

Avaliado e mantido de propósito (não há forma segura de ligar sozinho):
  * na fusão, o stub não tem conta da plataforma — não se sabe QUAL conta é dele;
  * a memória das decisões humanas é por CONTA (``chave_identidade``); usar o
    nome do stub como memória ligaria a próxima conta que chegasse com esse nome,
    e o nome curto ("ZEFA QUARESMA", sem o último sobrenome) é justamente o caso
    em que o dono pode ser outra criança fora do cadastro (``matching.
    subconjunto_estrutural``) — o vínculo gravado seria permanente.
O custo fica pequeno de outro jeito: a pendência tem um candidato só e a triagem
a marca como "segura"; um clique a resolve, a decisão vira memória e as coletas
seguintes entram sozinhas. Dados fictícios."""
from app.services import alunos_fusao
from app.services import identidade_aluno as ida
from app.services import triagem_revisoes as tri
from tests.sync_integridade_comum import (aluno, aplicar, dono, elefante_resumo, fichas,
                                          pendentes, sem_disco)

K = "3 ANO A TARDE ANUAL (300396804)"


def test_stub_sem_conta_fundido_revisao_uma_vez_segura_e_memoria(db, cliente, escola_completa,
                                                                  monkeypatch):
    sem_disco(monkeypatch)
    esc, t, admin = escola_completa["escola"], escola_completa["turma"], escola_completa["admin"]
    oficial = aluno(db, esc.id, t, "Zefa Quaresma Lima", da_lista_piloto=True)
    stub = aluno(db, esc.id, t, "Zefa Quaresma")
    db.commit()
    oficial_id = oficial.id
    alunos_fusao.fundir_par(db, esc.id, oficial, stub, admin.id)
    db.commit()
    total = fichas(db, esc.id)

    linha = [{"studentId": 7702, "studentName": "Zefa Quaresma", "totalBooksRead": 5}]
    aplicar(db, esc, elefante_resumo(K, linha))
    # Nada é ligado nem criado sozinho: revisão, com a oficial como única candidata.
    assert dono(db, esc.id, "elefante", "7702") is None
    assert fichas(db, esc.id) == total
    [rev] = pendentes(db, esc.id)
    assert rev.motivo == "correspondencia_insegura"
    assert [c["aluno_id"] for c in rev.candidatos] == [oficial_id]
    triagem = tri.triar_revisoes(ida.carregar_contexto(db, esc.id), [rev])[rev.id]
    assert triagem.classificacao == tri.SEGURA

    r = cliente.post(f"/api/v1/escolas/{esc.id}/importacoes/revisoes/{rev.id}/resolver",
                     json={"aluno_id": oficial_id})
    assert r.status_code == 200, r.text
    db.expire_all()
    aplicar(db, esc, elefante_resumo(K, linha))
    assert pendentes(db, esc.id) == []
    assert dono(db, esc.id, "elefante", "7702") == oficial_id
