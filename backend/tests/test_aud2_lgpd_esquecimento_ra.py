"""Exclusão permanente (LGPD): o RA da criança também sai do log da fusão (DEC-14).

O DEFEITO (ALUNOS-8-RA, decidido pelo condutor da auditoria). Depois do
esquecimento, duas entradas do log ainda guardavam o RA da criança:
  * a ``foto_pre_fusao`` de ``aluno.fundido`` — o retrato da ficha absorvida, com a
    ``ficha`` dela (``{"ra": ...}``). É um retrato do cadastro, não o motivo de
    nenhuma decisão;
  * o item "RA X × Y" das ``divergencias`` de ``aluno.fundido_com_conflito``.
A redação já trocava o nascimento ("nascimento [removido]") e deixava o RA, tratado
como "porquê técnico".

O CONSERTO. Nas entradas da própria criança, o RA da ``ficha`` da foto pré-fusão
vira "[removido]" e o item de RA das divergências vira "RA [removido]": o registro
de que houve conflito continua, o número não. O RA que é o MOTIVO de uma decisão
(o vínculo feito pelo RA, ``aluno.identidade_vinculada``) continua.

Dados fictícios.
"""
import json
from datetime import date

from sqlalchemy import select

from app.models import Aluno, LogAuditoria
from tests.test_aud_alunos_esquecimento_apos_fusao import _excluir, _fundir, _stub

API = "/api/v1"
RA_DELA = "987650001"
RA_DO_STUB = "987650002"
RA_DE_QUEM_FICA = "987650003"


def _fundir_com_conflito(cliente, escola_id, manter_id, remover_id):
    r = cliente.post(f"{API}/escolas/{escola_id}/alunos/fundir", json={
        "manter_id": manter_id, "remover_id": remover_id,
        "confirmacao": "FUNDIR", "confirmar_conflito": "FUNDIR MESMO COM CONFLITO"})
    assert r.status_code == 200, r.text


def _log(db, escola_id, acao):
    db.expire_all()
    return db.execute(select(LogAuditoria).where(
        LogAuditoria.escola_id == escola_id, LogAuditoria.acao == acao)).scalars().one()


def _sobras(db, escola_id, marcas):
    db.expire_all()
    achadas = []
    for log in db.execute(select(LogAuditoria).where(
            LogAuditoria.escola_id == escola_id)).scalars():
        texto = json.dumps(log.detalhes or {}, ensure_ascii=False)
        achadas += [(log.acao, m) for m in marcas if m in texto]
    return achadas


def test_ra_da_crianca_esquecida_sai_da_foto_e_das_divergencias(
        cliente, cliente_global, db, escola_completa):
    escola, turma, admin = (escola_completa["escola"], escola_completa["turma"],
                            escola_completa["admin"])
    oficial = escola_completa["alunos"][0]
    oficial.ficha = {"ra": RA_DELA}
    oficial.data_nascimento = date(2017, 4, 10)
    db.commit()
    stub_id = _stub(db, escola, turma, admin, "ANA B. SOUZA",
                    data_nascimento=date(2017, 4, 9), ficha={"ra": RA_DO_STUB})
    _fundir_com_conflito(cliente, escola.id, oficial.id, stub_id)
    oid = oficial.id
    antes = _log(db, escola.id, "aluno.fundido_com_conflito").detalhes["divergencias"]
    assert f"RA {RA_DELA} × {RA_DO_STUB}" in antes
    assert _log(db, escola.id, "aluno.fundido").detalhes["foto_pre_fusao"]["ficha"] == {
        "ra": RA_DO_STUB}

    _excluir(cliente_global, escola.id, oid)
    assert db.get(Aluno, oid) is None
    sobras = _sobras(db, escola.id, (RA_DELA, RA_DO_STUB, "2017-04-09", "2017-04-10"))
    print("RA/NASCIMENTO QUE FICARAM NO LOG:", sobras)
    assert not sobras, "o RA da criança esquecida ficou no log"

    # O registro de que houve conflito (e de qual tipo) continua; o número sai.
    conflito = _log(db, escola.id, "aluno.fundido_com_conflito").detalhes
    assert conflito["divergencias"] == ["nascimento [removido]", "RA [removido]"]
    assert conflito["manter_id"] == oid and conflito["remover_id"] == stub_id
    foto = _log(db, escola.id, "aluno.fundido").detalhes["foto_pre_fusao"]
    assert foto["ficha"] == {"ra": "[removido]"}
    assert foto["id"] == stub_id and foto["contagens"] is not None


def test_ra_de_quem_continua_na_escola_fica_intacto(cliente, cliente_global, db,
                                                    escola_completa):
    """Só as entradas da criança excluída: a fusão de OUTRA criança, que continua,
    guarda o RA dela como estava."""
    escola, turma, admin = (escola_completa["escola"], escola_completa["turma"],
                            escola_completa["admin"])
    fica, sai = escola_completa["alunos"][0], escola_completa["alunos"][2]
    fica.ficha = {"ra": RA_DE_QUEM_FICA}
    db.commit()
    stub_id = _stub(db, escola, turma, admin, "ANA B. SOUZA", ficha={"ra": RA_DO_STUB})
    _fundir_com_conflito(cliente, escola.id, fica.id, stub_id)
    _excluir(cliente_global, escola.id, sai.id)
    assert _log(db, escola.id, "aluno.fundido_com_conflito").detalhes["divergencias"] == [
        f"RA {RA_DE_QUEM_FICA} × {RA_DO_STUB}"]
    assert _log(db, escola.id, "aluno.fundido").detalhes["foto_pre_fusao"]["ficha"] == {
        "ra": RA_DO_STUB}


def test_fusao_sem_conflito_tambem_perde_o_ra_da_foto(cliente, cliente_global, db,
                                                      escola_completa):
    escola, turma, admin = (escola_completa["escola"], escola_completa["turma"],
                            escola_completa["admin"])
    oficial_id = escola_completa["alunos"][0].id
    stub_id = _stub(db, escola, turma, admin, "ANA B. SOUZA", ficha={"ra": RA_DO_STUB})
    _fundir(cliente, escola.id, oficial_id, stub_id)
    _excluir(cliente_global, escola.id, oficial_id)
    assert _sobras(db, escola.id, (RA_DO_STUB,)) == []
    assert _log(db, escola.id, "aluno.fundido").detalhes["foto_pre_fusao"]["ficha"] == {
        "ra": "[removido]"}
