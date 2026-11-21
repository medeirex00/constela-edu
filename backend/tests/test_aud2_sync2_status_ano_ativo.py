"""GET /sync/status conta alunos e turmas do ANO LETIVO ATIVO, como /alunos e /turmas.

Antes contava todo aluno 'ativo' da escola e toda turma de qualquer ano (também as
arquivadas). Na virada (ano ativo 2027, Lista Piloto 2027 enviada), o "Comece aqui"
e Integrações mostravam alunos e turmas somando os dois anos, enquanto /alunos (ano
ativo) mostrava só os de 2027: "6 aluno(s)" num lugar e "2" no outro.

O sinal ``lista_piloto_importada`` (o "Comece aqui" da barra lateral) não muda aqui:
se a virada deve voltar a pedir a Lista Piloto do ano novo é decisão do dono.

Dados 100% fictícios.
"""
from app.models import Aluno, Matricula, Turma

API = "/api/v1"


def _status(cliente, eid):
    r = cliente.get(f"{API}/escolas/{eid}/sync/status")
    assert r.status_code == 200, r.text
    return r.json()


def _alunos_do_ano(cliente, eid) -> int:
    r = cliente.get(f"{API}/escolas/{eid}/alunos", params={"por_pagina": 1000})
    assert r.status_code == 200, r.text
    return r.json()["total"]


def _turmas_do_ano(cliente, eid) -> int:
    r = cliente.get(f"{API}/escolas/{eid}/turmas")
    assert r.status_code == 200, r.text
    return len(r.json())


def _onboarding(cliente, eid) -> bool:
    r = cliente.get(f"{API}/escolas/{eid}/sync/onboarding")
    assert r.status_code == 200, r.text
    return r.json()["lista_piloto_importada"]


def _ano_anterior_e_arquivada(db, escola_completa):
    """2025: uma turma com quem se formou (só matrícula de 2025) e com a Ana (que segue
    em 2026); 2026: uma turma arquivada, sem ninguém."""
    escola = escola_completa["escola"]
    t2025 = Turma(escola_id=escola.id, nome="2º Ano A", ano_escolar="2º Ano",
                  ano_letivo=2025)
    arquivada = Turma(escola_id=escola.id, nome="3º Ano Z", ano_escolar="3º Ano",
                      ano_letivo=2026, status="arquivada")
    db.add_all([t2025, arquivada])
    db.flush()
    formando = Aluno(escola_id=escola.id, nome="Pessoa Ficticia Que Saiu")
    db.add(formando)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=formando.id, turma_id=t2025.id,
                     ano_letivo=2025))
    db.add(Matricula(escola_id=escola.id, aluno_id=escola_completa["alunos"][0].id,
                     turma_id=t2025.id, ano_letivo=2025))
    db.commit()


def test_status_conta_alunos_e_turmas_do_ano_ativo(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    _ano_anterior_e_arquivada(db, escola_completa)

    s = _status(cliente, eid)
    # Antes: 4 alunos (o que saiu entra) e 3 turmas (a de 2025 e a arquivada entram).
    assert (s["qtd_alunos"], s["qtd_turmas"]) == (3, 1), s
    assert s["qtd_alunos"] == _alunos_do_ano(cliente, eid)
    assert s["qtd_turmas"] == _turmas_do_ano(cliente, eid)
    assert s["lista_piloto_importada"] is True


def test_na_virada_o_status_nao_soma_os_dois_anos(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    eid = escola.id
    _ano_anterior_e_arquivada(db, escola_completa)
    escola.ano_letivo_ativo = 2027                     # o Admin Global virou o ano
    t2027 = Turma(escola_id=eid, nome="4º Ano A", ano_escolar="4º Ano", ano_letivo=2027)
    db.add(t2027)
    db.flush()
    for aluno in escola_completa["alunos"][:2]:        # a Lista 2027 trouxe dois
        db.add(Matricula(escola_id=eid, aluno_id=aluno.id, turma_id=t2027.id,
                         ano_letivo=2027))
    db.commit()

    s = _status(cliente, eid)
    # Antes: 4 alunos e 4 turmas, somando 2025, 2026 e 2027.
    assert (s["qtd_alunos"], s["qtd_turmas"]) == (2, 1), s
    assert s["qtd_alunos"] == _alunos_do_ano(cliente, eid)
    assert s["qtd_turmas"] == _turmas_do_ano(cliente, eid)
    # O sinal do onboarding segue o mesmo nos dois endpoints.
    assert s["lista_piloto_importada"] is _onboarding(cliente, eid) is True


def test_ano_novo_ainda_sem_lista_mostra_zero_sem_esconder_o_sinal(cliente, db,
                                                                  escola_completa):
    escola = escola_completa["escola"]
    escola.ano_letivo_ativo = 2027
    db.commit()
    s = _status(cliente, escola.id)
    assert (s["qtd_alunos"], s["qtd_turmas"]) == (0, 0), s
    assert s["qtd_alunos"] == _alunos_do_ano(cliente, escola.id)
    # Decisão do dono (não tomada aqui): hoje o sinal diz "a escola já tem turmas".
    assert s["lista_piloto_importada"] is _onboarding(cliente, escola.id) is True
