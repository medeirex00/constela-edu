"""G_VIRADA-8 (notificação): o aviso do sino da linha da Lista Piloto que foi para
revisão por "mudança de sala sem prova" leva à FICHA candidata, não à lista de Alunos.

A Lista Piloto não grava essa linha na fila de identidade: audita
``aluno.revisao_necessaria`` com ``entidade_id`` = a ficha candidata, e o aviso da
importação manda o gestor à própria ficha (três pontinhos › Editar dados › Turma). O
sino, porém, apontava para ``/alunos`` — a lista que só mostra quem tem matrícula no
ano ativo. Na virada, a ficha candidata não tem matrícula no ano novo: o link caía numa
lista sem a criança. Os outros motivos da Lista Piloto (nomes parecidos na mesma sala,
disputa entre linhas) continuam em ``/alunos``, onde está "Fundir duplicatas"; a
pendência gravada na fila continua nas Revisões de identidade. Dados fictícios.
"""
from sqlalchemy import select

from app.models import Notificacao
from app.services import audit
from tests.test_aud2_virada_revisao_sem_prova import (
    BRUNO, _bruno_da_coleta_no_4a_de_2026, _enviar, _planilha)


def _rotas(db, escola_id):
    db.expire_all()
    return [n.rota for n in db.execute(
        select(Notificacao).where(Notificacao.escola_id == escola_id,
                                  Notificacao.tipo == "aluno.revisao_necessaria")
        .order_by(Notificacao.id)).scalars()]


def test_aviso_da_mudanca_de_sala_sem_prova_abre_a_ficha_que_a_lista_nao_mostra(
        cliente, cliente_global, db, escola_completa):
    eid = escola_completa["escola"].id
    bid = _bruno_da_coleta_no_4a_de_2026(db, eid)
    assert cliente_global.patch(f"/api/v1/escolas/{eid}",
                                json={"ano_letivo_ativo": 2027}).status_code == 200
    resultado = _enviar(cliente, eid, _planilha(2027, ("5º Ano A", [BRUNO])))
    assert resultado["alunos_em_revisao"] == 1

    # A lista de Alunos (ano ativo) não traz a criança...
    lista = cliente.get(f"/api/v1/escolas/{eid}/alunos", params={"por_pagina": 1000}).json()
    assert bid not in [a["id"] for a in lista["itens"]]
    # ...a ficha dela abre.
    assert cliente.get(f"/api/v1/escolas/{eid}/alunos/{bid}/perfil").status_code == 200

    assert _rotas(db, eid) == [f"/alunos/{bid}"]
    feed = cliente.get("/api/v1/notificacoes").json()
    assert [n["rota"] for n in feed if n["tipo"] == "aluno.revisao_necessaria"] == [
        f"/alunos/{bid}"]


def test_os_outros_motivos_da_lista_piloto_seguem_em_alunos_e_a_fila_nas_revisoes(
        db, escola_completa):
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    for detalhes in ({"fonte": "importacao_matriculas", "motivo": "abreviacao"},
                     {"fonte": "importacao_matriculas",
                      "motivo": "disputado_por_varias_linhas"},
                     {"fonte": "importacao_matriculas"},
                     {"motivo": "mudanca_de_sala_sem_prova", "revisao_id": 9}):
        audit.registrar(db, "aluno.revisao_necessaria", escola_id=escola.id,
                        entidade="aluno", entidade_id=aluno.id, detalhes=detalhes)
    # Sem ficha candidata, a lista.
    audit.registrar(db, "aluno.revisao_necessaria", escola_id=escola.id,
                    entidade="aluno", entidade_id=None,
                    detalhes={"motivo": "mudanca_de_sala_sem_prova"})
    db.commit()
    assert _rotas(db, escola.id) == ["/alunos", "/alunos", "/alunos",
                                     "/revisoes-identidade", "/alunos"]
