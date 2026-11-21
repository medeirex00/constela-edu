"""Fusão em cadeia: a mesma leitura não pode ficar duas vezes na linha do tempo.

O DEFEITO (REV-ALUNOS-2, sobre o conserto do ALUNOS-3). ``fundir_par`` só
reconhecia como "a mesma linha do relatório" a cópia cuja chave prova ter
nascido na ficha que fica ou na que sai. Quando as duas cópias tinham vindo de
fichas absorvidas ANTES (D absorveu Z, X absorveu Y, depois D absorve X),
nenhuma chave provava origem e as duas ficavam.

O CONSERTO. As origens possíveis de cada lado são a própria ficha e todas as que
ela absorveu, direta ou em cadeia (log ``aluno.fundido``) — o mesmo fecho que a
limpeza do passivo já usava.

Dados fictícios.
"""
from datetime import datetime

from sqlalchemy import select

from app.models import Aluno, LogAuditoria, Matricula
from app.services.eventos import chave_evento
from tests.test_aud_alunos_fusao_eventos import (
    MARCO,
    TITULO,
    _eventos,
    _fundir,
    _importar,
)

T_MARCO = datetime(2026, 3, 10, 10, 0)


def _nova(db, escola, turma, nome):
    aluno = Aluno(escola_id=escola.id, nome=nome)
    db.add(aluno)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=aluno.id, turma_id=turma.id,
                     ano_letivo=2026))
    db.commit()
    return aluno


def test_cadeia_de_fusoes_nao_dobra_a_mesma_leitura(cliente, db, escola_completa):
    """A sonda do revisor: Z e Y leram o mesmo livro em março. D absorve Z, X
    absorve Y, e depois D absorve X."""
    esc, turma = escola_completa["escola"], escola_completa["turma"]
    d, z, x = escola_completa["alunos"]
    y = _nova(db, esc, turma, "Ana B Souza Ficticia")
    did, zid, xid, yid = d.id, z.id, x.id, y.id
    _importar(cliente, esc.id, z, MARCO)
    _importar(cliente, esc.id, y, MARCO)
    _fundir(cliente, esc.id, did, zid)
    _fundir(cliente, esc.id, xid, yid)
    corpo = _fundir(cliente, esc.id, did, xid)
    eventos = _eventos(db, did)
    print("CADEIA: eventos no D =", len(eventos), "| corpo eventos_descartados=",
          corpo.get("eventos_descartados"), "movidos=", corpo.get("eventos_movidos"))
    assert len(eventos) == 1, f"a mesma leitura ficou {len(eventos)} vezes na linha do tempo"
    assert corpo["eventos_descartados"] == 1 and corpo["eventos_movidos"] == 0
    # Fica a cópia que já estava na ficha que fica (a de Z); a de Y vai para o log.
    assert eventos[0].chave_natural == chave_evento("elefante", "leitura", zid, TITULO,
                                                    T_MARCO)
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "aluno.fundido",
        LogAuditoria.entidade_id == did).order_by(LogAuditoria.id.desc())).scalars().first()
    detalhe, = log.detalhes["eventos_descartados_detalhe"]
    assert detalhe["chave_natural"] == chave_evento("elefante", "leitura", yid, TITULO,
                                                    T_MARCO)
    # A reimportação da mesma conta, agora na ficha que ficou, também não dobra.
    _importar(cliente, esc.id, d, MARCO)
    assert len(_eventos(db, did)) == 1


def test_controle_em_estrela(cliente, db, escola_completa):
    """D absorve Z e depois X, cada uma com a leitura nativa: já funcionava."""
    esc = escola_completa["escola"]
    d, z, x = escola_completa["alunos"]
    did = d.id
    _importar(cliente, esc.id, z, MARCO)
    _importar(cliente, esc.id, x, MARCO)
    _fundir(cliente, esc.id, did, z.id)
    _fundir(cliente, esc.id, did, x.id)
    _importar(cliente, esc.id, d, MARCO)
    assert len(_eventos(db, did)) == 1


def test_fichas_absorvidas_segue_a_cadeia_so_das_fichas_pedidas(db, escola_completa):
    """O fecho do log ``aluno.fundido`` a partir de fichas dadas: segue a cadeia
    (D ← X ← Y), não traz o que as outras fichas absorveram e não entra por um id
    que hoje é de uma ficha viva."""
    from app.services.eventos import fichas_absorvidas

    escola_id = escola_completa["escola"].id

    def fusao(manter_id, remover_id):
        db.add(LogAuditoria(escola_id=escola_id, acao="aluno.fundido", entidade="aluno",
                            entidade_id=manter_id,
                            detalhes={"mantido": {"id": manter_id},
                                      "removido": {"id": remover_id}}))

    viva = escola_completa["alunos"][1].id       # id em uso: reaproveitamento
    fusao(901, 902)
    fusao(901, 903)
    fusao(903, 904)
    fusao(904, 905)
    fusao(907, 908)
    fusao(901, viva)
    fusao(viva, 909)
    db.commit()
    assert fichas_absorvidas(db, [901, 907, 910]) == {
        901: {902, 903, 904, 905}, 907: {908}, 910: set()}
