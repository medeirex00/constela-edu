"""Exclusão permanente (LGPD): o RA da criança sai também do log do vínculo da Lista
Piloto (REV2-LGPD-3, na linha do DEC-14).

O DEFEITO. A importação da Lista Piloto grava ``"ra": linha.ra`` em TODO
``aluno.identidade_vinculada`` que troca o nome da ficha, qualquer que seja o motivo
do casamento ("abreviacao", "ra"...). A redação do esquecimento deixava esse RA em
claro, como se fosse sempre o "motivo de uma decisão" — mas o log não guarda a via do
casamento, então não há como mostrar que o RA foi o motivo.

O CONSERTO. Nas entradas da própria criança (e das fichas que ela absorveu), o RA
vira "[removido]", como o nascimento e o RA da fusão; o motivo e a origem do vínculo
continuam. Entradas de criança que continua na escola ficam intactas.

Base: a variante do revisor (``test_v4_ra_do_vinculo_por_nome_fica_no_log``). Dados
fictícios.
"""
import json

import pytest
from sqlalchemy import select

from app.models import LogAuditoria
from app.services.audit import registrar

API = "/api/v1"
RA_DELA = "000123456789-0"
RA_DE_QUEM_FICA = "000987654321-0"


def _vinculo(db, escola_id, aluno, ra, motivo):
    """A entrada que ``routers/importacoes.py`` grava ao trocar o nome da ficha."""
    registrar(db, "aluno.identidade_vinculada", escola_id=escola_id, usuario_id=None,
              entidade="aluno", entidade_id=aluno.id,
              detalhes={"nome_antigo": "ANA B SOUZA", "nome_novo": aluno.nome,
                        "origem_linha": aluno.nome, "ra": ra, "motivo": motivo,
                        "origem": "importacao_matriculas"})


def _excluir(cliente_global, escola_id, aluno_id):
    r = cliente_global.post(f"{API}/escolas/{escola_id}/alunos/excluir-permanente",
                            json={"aluno_ids": [aluno_id], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text


def _vinculos(db, aluno_id):
    db.expire_all()
    return [lg.detalhes for lg in db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "aluno.identidade_vinculada",
        LogAuditoria.entidade_id == aluno_id)).scalars()]


@pytest.mark.parametrize("motivo", ["abreviacao", "ra"])
def test_ra_do_vinculo_sai_do_log_qualquer_que_seja_o_motivo(
        db, escola_completa, cliente_global, motivo):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    _vinculo(db, escola.id, ana, RA_DELA, motivo)
    db.commit()
    ana_id = ana.id
    _excluir(cliente_global, escola.id, ana_id)

    db.expire_all()
    restos = [(lg.acao, lg.detalhes) for lg in db.execute(select(LogAuditoria)).scalars()
              if RA_DELA in json.dumps(lg.detalhes or {}, default=str)]
    print("\nRA da criança esquecida no log:", restos)
    assert restos == [], "o RA da criança esquecida ficou no log"
    # O registro do vínculo e o porquê técnico continuam; o número, não.
    [vinculo] = _vinculos(db, ana_id)
    assert vinculo["ra"] == "[removido]"
    assert vinculo["motivo"] == motivo and vinculo["origem"] == "importacao_matriculas"


def test_vinculo_sem_ra_continua_sem_ra(db, escola_completa, cliente_global):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    _vinculo(db, escola.id, ana, None, "abreviacao")
    db.commit()
    ana_id = ana.id
    _excluir(cliente_global, escola.id, ana_id)
    [vinculo] = _vinculos(db, ana_id)
    assert vinculo["ra"] is None and vinculo["motivo"] == "abreviacao"


def test_ra_do_vinculo_de_quem_continua_fica_intacto(db, escola_completa, cliente_global):
    escola = escola_completa["escola"]
    fica, sai = escola_completa["alunos"][0], escola_completa["alunos"][2]
    _vinculo(db, escola.id, fica, RA_DE_QUEM_FICA, "abreviacao")
    db.commit()
    fica_id = fica.id
    _excluir(cliente_global, escola.id, sai.id)
    [vinculo] = _vinculos(db, fica_id)
    assert vinculo["ra"] == RA_DE_QUEM_FICA
