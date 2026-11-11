"""Exclusão permanente (LGPD): o nascimento citado na fusão com conflito também sai.

O DEFEITO (REV-ALUNOS-3, sobre o ALUNOS-8). Quando a gestão funde duas fichas
APESAR da prova de serem crianças diferentes ("FUNDIR MESMO COM CONFLITO"), o log
``aluno.fundido_com_conflito`` guarda em ``divergencias`` o texto
"nascimento 2017-04-10 × 2017-04-09". Depois da exclusão permanente da criança,
as duas datas de nascimento continuavam ali: a redação só trocava chaves de nome
e as chaves de dado pessoal, e ``divergencias`` não é nenhuma delas.

O CONSERTO. Nas entradas da própria criança, o item de nascimento de
``divergencias`` vira "nascimento [removido]": o porquê técnico (houve conflito de
nascimento) fica; a data sai. O RA continua como está — decisão do dono.

Dados fictícios.
"""
import json
from datetime import date

from sqlalchemy import select

from app.models import Aluno, LogAuditoria
from tests.test_aud_alunos_esquecimento_apos_fusao import _excluir, _stub

API = "/api/v1"


def _fundir_com_conflito(cliente, escola_id, manter_id, remover_id):
    r = cliente.post(f"{API}/escolas/{escola_id}/alunos/fundir", json={
        "manter_id": manter_id, "remover_id": remover_id,
        "confirmacao": "FUNDIR", "confirmar_conflito": "FUNDIR MESMO COM CONFLITO"})
    assert r.status_code == 200, r.text


def _log_do_conflito(db, escola_id):
    db.expire_all()
    return db.execute(select(LogAuditoria).where(
        LogAuditoria.escola_id == escola_id,
        LogAuditoria.acao == "aluno.fundido_com_conflito")).scalars().one()


def test_nascimento_da_crianca_esquecida_sai_do_log_da_fusao_com_conflito(
        cliente, cliente_global, db, escola_completa):
    escola, turma, admin = (escola_completa["escola"], escola_completa["turma"],
                            escola_completa["admin"])
    oficial = escola_completa["alunos"][0]
    oficial.data_nascimento = date(2017, 4, 10)
    db.commit()
    stub_id = _stub(db, escola, turma, admin, "ANA B. SOUZA",
                    data_nascimento=date(2017, 4, 9))
    _fundir_com_conflito(cliente, escola.id, oficial.id, stub_id)
    oid = oficial.id
    antes = _log_do_conflito(db, escola.id).detalhes["divergencias"]
    assert "nascimento 2017-04-10 × 2017-04-09" in antes

    _excluir(cliente_global, escola.id, oid)
    db.expire_all()
    assert db.get(Aluno, oid) is None
    sobras = []
    for log in db.execute(select(LogAuditoria).where(
            LogAuditoria.escola_id == escola.id)).scalars():
        texto = json.dumps(log.detalhes or {}, ensure_ascii=False)
        for marca in ("2017-04-09", "2017-04-10"):
            if marca in texto:
                sobras.append((log.acao, log.entidade_id, marca, texto[:220]))
    for sobra in sobras:
        print("SOBRA:", sobra)
    assert not sobras, "o nascimento da criança esquecida ficou no log"

    # O porquê técnico continua: houve conflito de nascimento (só o valor sai).
    detalhes = _log_do_conflito(db, escola.id).detalhes
    assert "nascimento [removido]" in detalhes["divergencias"]
    assert detalhes["confirmacao_especifica"] == "FUNDIR MESMO COM CONFLITO"
    assert detalhes["manter_id"] == oid and detalhes["remover_id"] == stub_id


def test_conflito_de_quem_continua_na_escola_fica_intacto(cliente, cliente_global, db,
                                                          escola_completa):
    """A redação é só nas entradas da criança excluída: o log da fusão com
    conflito de OUTRA criança, que continua na escola, não é tocado."""
    escola, turma, admin = (escola_completa["escola"], escola_completa["turma"],
                            escola_completa["admin"])
    fica, sai = escola_completa["alunos"][0], escola_completa["alunos"][2]
    fica.data_nascimento = date(2017, 4, 10)
    db.commit()
    stub_id = _stub(db, escola, turma, admin, "ANA B. SOUZA",
                    data_nascimento=date(2017, 4, 9))
    _fundir_com_conflito(cliente, escola.id, fica.id, stub_id)
    _excluir(cliente_global, escola.id, sai.id)
    assert _log_do_conflito(db, escola.id).detalhes["divergencias"] == [
        "nascimento 2017-04-10 × 2017-04-09"]
