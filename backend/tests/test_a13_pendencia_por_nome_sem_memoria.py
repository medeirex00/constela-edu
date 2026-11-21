"""A13 sem memória por nome: a pendência aberta só pelo NOME, fechada pela linha
que volta COM a conta, não vira "decisão" nome+sala — nem nesta importação, nem
nas próximas — e não fecha quando o nome, sozinho, aponta outra ficha da sala.

Cenário (revisão independente da branch fix/pp-identidade): duas fichas na mesma
sala casam com o nome abreviado "ZEFA Q" e há uma pendência por nome "ZEFA Q"
(sem conta, sem candidato — o formato que a trava do nome abreviado produz).

  * V1 — numa mesma coleta, a conta já ligada a X vem como "ZEFA Q" e, abaixo,
    outra linha "ZEFA Q" SEM conta: antes, a primeira fechava a pendência por nome
    e gravava a memória nome+sala, e a segunda ia sozinha para X;
  * V2 — no upload manual com a conta, quem confirma escolhe X: antes, a pendência
    por nome fechava como decisão HUMANA e virava memória permanente;
  * o retrato que a pendência por nome guarda pode ser da OUTRA criança (Y): ele
    não sai da fila só porque a conta de X apareceu.
Dados fictícios.
"""
from sqlalchemy import select

from app.models import RevisaoIdentidade, SnapshotMatific
from app.services import identidade_aluno as ida
from tests.sync_integridade_comum import (aluno, aplicar, matific, pendentes, sem_disco,
                                          vincular)

K = "3 ANO A TARDE ANUAL (300396804)"
CHAVE_NOME = f"matific|nome:{ida.chave_nome('ZEFA Q')}|sala:3|A"


def _pendencia_nome(db, esc_id, contexto):
    rev = RevisaoIdentidade(escola_id=esc_id, chave=ida.chave_pendencia(CHAVE_NOME, "resumo"),
                            chave_identidade=CHAVE_NOME, plataforma="matific",
                            formato="resumo", nome_recebido="ZEFA Q",
                            motivo="nome_incompleto", candidatos=[],
                            linhas=[{"atividades": 1, "estrelas": 1}], contexto=contexto,
                            origem="importacao", ocorrencias=1, status="pendente")
    db.add(rev)
    db.commit()
    return rev.id


def _decidir_sem_conta(db, esc_id):
    ctx = ida.carregar_contexto(db, esc_id)
    return ida.decidir(ctx, ida.LinhaIdentidade(nome="ZEFA Q", plataforma="matific",
                                                turma_nome=K))


def _x_e_y(db, esc, t):
    x = aluno(db, esc.id, t, "Zefa Quaresma Lima")
    y = aluno(db, esc.id, t, "Zefa Quintana Borba")
    db.commit()
    return x.id, y.id


def test_v1_linha_sem_conta_da_mesma_coleta_nao_vai_sozinha_para_x(
        db, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    esc, t = escola_completa["escola"], escola_completa["turma"]
    xid, yid = _x_e_y(db, esc, t)
    vincular(db, esc.id, xid, "matific", "u-x")
    db.commit()
    rid = _pendencia_nome(db, esc.id, {})
    aplicar(db, esc, matific(K, [
        {"nome": "ZEFA Q", "nome_abrev": "ZEFA Q", "uuid": "u-x", "estrelas": 50,
         "atividades": 20},
        {"nome": "ZEFA Q", "nome_abrev": "ZEFA Q", "uuid": "", "estrelas": 7,
         "atividades": 3}]))
    snaps = db.execute(select(SnapshotMatific.aluno_id, SnapshotMatific.atividades)).all()
    assert (xid, 20) in snaps                       # a conta de X vale, como sempre
    assert (xid, 3) not in snaps and (yid, 3) not in snaps
    rev = db.get(RevisaoIdentidade, rid)
    assert rev.status == "pendente"
    assert [linha.get("atividades") for linha in rev.linhas] == [3]   # a linha sem conta


def test_conta_de_x_nao_tira_da_fila_o_retrato_que_pode_ser_de_y(
        db, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    esc, t = escola_completa["escola"], escola_completa["turma"]
    xid, _ = _x_e_y(db, esc, t)
    vincular(db, esc.id, xid, "matific", "u-x")
    db.commit()
    rid = _pendencia_nome(db, esc.id, {})
    aplicar(db, esc, matific(K, [{"nome": "ZEFA Q", "nome_abrev": "ZEFA Q", "uuid": "u-x",
                                  "estrelas": 50, "atividades": 20}]))
    rev = db.get(RevisaoIdentidade, rid)
    assert rev.status == "pendente"
    assert rev.linhas == [{"atividades": 1, "estrelas": 1}]


def test_v2_escolha_humana_da_conta_nao_fecha_a_pendencia_por_nome(cliente, db,
                                                                    escola_completa):
    esc, t = escola_completa["escola"], escola_completa["turma"]
    xid, yid = _x_e_y(db, esc, t)
    rid = _pendencia_nome(db, esc.id, {"data_referencia": "2026-11-01T12:00:00+00:00"})
    r = cliente.post(f"/api/v1/escolas/{esc.id}/importacoes/confirmar", json={
        "plataforma": "matific", "formato": "resumo", "tipo": "texto",
        "data_referencia": "2026-11-05T12:00:00+00:00",
        "linhas": [{"nome": "ZEFA Q", "aluno_id": xid,
                    "dados": {"turma_relatorio": K, "matific_uuid": "u-x",
                              "atividades": 20, "estrelas": 50}}]})
    assert r.status_code == 200, r.text
    db.expire_all()
    rev = db.get(RevisaoIdentidade, rid)
    assert rev.status == "pendente" and rev.resolvida_por_id is None
    d = _decidir_sem_conta(db, esc.id)
    assert d.acao == ida.REVISAR
    assert set(d.candidatos) == {xid, yid}


def test_escolha_humana_fecha_por_nome_so_como_automatica_e_sem_memoria(
        cliente, db, escola_completa):
    """X é a única ficha que o nome alcança, então a pendência por nome fecha —
    mas como AUTOMÁTICA: quem confirmou escolheu a ficha da conta, não respondeu a
    pergunta do nome. Um homônimo abreviado que chega depois reabre a dúvida."""
    esc, t = escola_completa["escola"], escola_completa["turma"]
    x = aluno(db, esc.id, t, "Zefa Quaresma Lima")
    db.commit()
    xid = x.id
    rid = _pendencia_nome(db, esc.id, {"data_referencia": "2026-11-01T12:00:00+00:00"})
    r = cliente.post(f"/api/v1/escolas/{esc.id}/importacoes/confirmar", json={
        "plataforma": "matific", "formato": "resumo", "tipo": "texto",
        "data_referencia": "2026-11-05T12:00:00+00:00",
        "linhas": [{"nome": "ZEFA Q", "aluno_id": xid,
                    "dados": {"turma_relatorio": K, "matific_uuid": "u-x",
                              "nome_incompleto": True,
                              "atividades": 20, "estrelas": 50}}]})
    assert r.status_code == 200, r.text
    db.expire_all()
    rev = db.get(RevisaoIdentidade, rid)
    assert rev.status == "resolvida" and rev.aluno_escolhido_id == xid
    assert rev.resolvida_por_id is None
    assert rev.resolucao["automatica"] is True
    assert rev.resolucao.get("pendencia_por_nome") is True
    assert CHAVE_NOME not in ida.carregar_contexto(db, esc.id).resolvidas
    # Chega a Y na mesma sala: a linha sem conta "ZEFA Q" volta a ser dúvida.
    y = aluno(db, esc.id, t, "Zefa Quintana Borba")
    db.commit()
    d = _decidir_sem_conta(db, esc.id)
    assert d.acao == ida.REVISAR
    assert set(d.candidatos) == {xid, y.id}
