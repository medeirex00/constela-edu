"""G_LGPD-2 (expurgo): o expurgo da categoria ``auditoria_alunos`` não apaga a LIGAÇÃO da
fusão — reduz ``aluno.fundido`` aos ids.

``backup._mesma_crianca``, ``eventos._fichas_absorvidas`` e
``exclusao_aluno.fichas_absorvidas`` leem no log ``aluno.fundido`` que duas fichas são a
mesma criança. Com o expurgo ligado (desligado por padrão), a linha vencida era APAGADA:
a ligação sumia e o backup de antes da fusão, restaurado, trazia de volta a duplicata da
criança excluída de vez (nome, retrato, conta da plataforma). ``aluno.fundido`` não
estava em ``ACOES_PRESERVADAS``.

Agora a linha vencida fica, reduzida a ``{"mantido": {"id"}, "removido": {"id"}}`` — sem
nome, sem ``foto_pre_fusao`` nem o resto do detalhe — e o resultado do expurgo conta as
reduções à parte. Dados fictícios.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import LogAuditoria
from app.services.audit import expurgar_retencao
from tests.test_aud2_backup_restauracao_fusao import (
    AVISO_1, _arquivo, _cena, _da_crianca, _excluir, _fundir, _restaurar)


def _depois(dias):
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=dias)


def test_expurgo_vencido_nao_desfaz_a_ligacao_da_fusao(db, escola_completa, cliente,
                                                       cliente_global):
    eid, dup_id, ofi_id, nome_dup = _cena(db, escola_completa)
    arquivo = _arquivo(db, eid)                      # backup de antes da fusão
    _fundir(cliente, eid, ofi_id, dup_id)
    _excluir(cliente_global, eid, ofi_id)

    simulado = expurgar_retencao(db, simular=True, prazos={"auditoria_alunos": 1},
                                 agora=_depois(10))
    assert simulado["auditoria_alunos"]["reduzidas"] == 1
    resultado = expurgar_retencao(db, simular=False, prazos={"auditoria_alunos": 1},
                                  agora=_depois(10))
    db.commit()
    assert resultado["auditoria_alunos"]["reduzidas"] == 1

    [fusao] = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "aluno.fundido")).scalars().all()
    assert fusao.detalhes == {"mantido": {"id": ofi_id}, "removido": {"id": dup_id}}

    corpo = _restaurar(cliente_global, eid, arquivo)
    assert _da_crianca(db, eid, nome_dup) == {"fichas": [], "retratos": [], "contas": []}, (
        "depois do expurgo, a restauração trouxe de volta a duplicata da criança excluída")
    assert corpo["avisos"] == [AVISO_1]


def test_a_fusao_ja_reduzida_nao_conta_de_novo(db, escola_completa, cliente, cliente_global):
    eid, dup_id, ofi_id, _nome = _cena(db, escola_completa)
    _fundir(cliente, eid, ofi_id, dup_id)
    expurgar_retencao(db, simular=False, prazos={"auditoria_alunos": 1}, agora=_depois(10))
    db.commit()
    de_novo = expurgar_retencao(db, simular=False, prazos={"auditoria_alunos": 1},
                                agora=_depois(20))
    db.commit()
    assert de_novo["auditoria_alunos"]["reduzidas"] == 0


def test_a_fusao_dentro_do_prazo_fica_inteira(db, escola_completa, cliente):
    eid, dup_id, ofi_id, _nome = _cena(db, escola_completa)
    _fundir(cliente, eid, ofi_id, dup_id)
    db.expire_all()
    antes = db.execute(select(LogAuditoria.detalhes).where(
        LogAuditoria.acao == "aluno.fundido")).scalar_one()
    resultado = expurgar_retencao(db, simular=False, prazos={"auditoria_alunos": 365},
                                  agora=_depois(10))
    db.commit()
    assert resultado["auditoria_alunos"]["reduzidas"] == 0
    db.expire_all()
    assert db.execute(select(LogAuditoria.detalhes).where(
        LogAuditoria.acao == "aluno.fundido")).scalar_one() == antes
