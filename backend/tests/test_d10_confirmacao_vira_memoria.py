"""A confirmação do D10 pelo Admin Global FORA da fila vale para a coleta seguinte
da própria escola — 2ª revisão de integração do e97 (identidade-sync, provas 1 e 3
invertidas).

O passo 0d de ``identidade_aluno.decidir`` só associa uma conta efetiva em outra
escola quando há memória humana (``RevisaoIdentidade`` resolvida →
``ctx.resolvidas``). O ``/resolver`` grava essa memória; a reativação de uma ficha
excluída (``/alunos/acoes``) e a volta de uma conta aposentada
(``/identidades/{p}/reativar`` ou ``/efetiva``) só gravavam a auditoria e o aviso.
Na coleta seguinte desta escola a conta voltava para a revisão
``identidade_de_outra_escola`` daqui, a ficha reativada não recebia dado e a
gestão levava 403 no ``/resolver``.

Agora, com a ficha ATIVA, o Admin Global deixa a mesma memória que o ``/resolver``
(``identidade_efetiva._gravar_memoria_da_decisao``). Ficha arquivada ou
transferida NÃO ganha memória: com ela, a ficha inativa passaria a receber dado.

Dados 100% fictícios (nomes de escola e de criança inventados); sem rede.
"""
import pytest
from sqlalchemy import select

from app.models import Aluno, IdentidadeExterna, RevisaoIdentidade
from app.models.nota import LogAuditoria
from app.models.plataformas import SnapshotMatific

API = "/api/v1"
U = "u-ficticia-d10-memoria"
V = "u-ficticia-d10-memoria-outra"
K = "3 ANO A (300396804)"
NOME_B = "Crianca Ficticia B Da Memoria"


def _nova_escola(db):
    from tests.test_sync_escola_cruzada import _nova_escola as nova

    return nova(db, nome="ESCOLA FICTICIA B DA MEMORIA", com_alunos=(NOME_B,))


def _importar(cliente, eid, nome, estrelas, data=None):
    """Importação sem ficha escolhida — a mesma porta da sincronização. ``data`` é
    a data do relatório (com ela, a pendência do mesmo retrato fecha sozinha)."""
    linha = {"nome": nome, "dados": {"matific_uuid": U, "estrelas": estrelas,
                                     "atividades": 10, "pontuacao_media": 80,
                                     "turma_relatorio": K}}
    corpo = {"plataforma": "matific", "formato": "resumo", "tipo": "pdf",
             "recalcular": False, "linhas": [linha]}
    if data is not None:
        corpo["data_referencia"] = data
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/confirmar", json=corpo)
    assert r.status_code == 200, r.text
    return r.json()


def _estrelas(db, aluno_id):
    db.expire_all()
    return [s.estrelas for s in db.execute(select(SnapshotMatific).where(
        SnapshotMatific.aluno_id == aluno_id)).scalars()]


def _revisoes(db, eid, status):
    db.expire_all()
    return db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == eid, RevisaoIdentidade.status == status)
        .order_by(RevisaoIdentidade.id)).scalars().all()


def _auditoria(db, acao):
    db.expire_all()
    return [a for a in db.execute(select(LogAuditoria).order_by(LogAuditoria.id)).scalars()
            if a.acao == acao]


def _cena_ficha_excluida(db, escola_completa, cliente):
    """A ficha X da escola A tem a conta U; a gestão de A exclui X; a escola B
    vincula U à ficha Y dela (legítimo). Devolve (e1, x, e2)."""
    e1 = escola_completa["escola"].id
    x = escola_completa["alunos"][0]
    db.add(IdentidadeExterna(escola_id=e1, aluno_id=x.id, plataforma="matific",
                             id_externo=U))
    db.commit()
    assert cliente.post(f"{API}/escolas/{e1}/alunos/acoes",
                        json={"aluno_ids": [x.id], "acao": "excluir"}).status_code == 200
    escola_b, _t, (y,) = _nova_escola(db)
    db.add(IdentidadeExterna(escola_id=escola_b.id, aluno_id=y.id, plataforma="matific",
                             id_externo=U))
    db.commit()
    return e1, x, escola_b.id


def _cena_conta_aposentada(db, escola_completa, idx=1):
    """A ficha X de A tem U aposentada e V efetiva; U é efetiva na escola B."""
    e1 = escola_completa["escola"].id
    x = escola_completa["alunos"][idx]
    db.add(IdentidadeExterna(escola_id=e1, aluno_id=x.id, plataforma="matific",
                             id_externo=U, status="aposentada"))
    db.add(IdentidadeExterna(escola_id=e1, aluno_id=x.id, plataforma="matific",
                             id_externo=V))
    escola_b, _t, (y,) = _nova_escola(db)
    db.add(IdentidadeExterna(escola_id=escola_b.id, aluno_id=y.id, plataforma="matific",
                             id_externo=U))
    db.commit()
    return e1, x, escola_b.id


def _confere_memoria(db, e1, aluno_id, resolvida_na):
    [mem] = _revisoes(db, e1, "resolvida")
    assert mem.chave_identidade == f"matific|id:{U}"
    assert mem.motivo == "identidade_de_outra_escola"
    assert mem.aluno_escolhido_id == aluno_id
    assert mem.resolvida_por_id is not None
    assert mem.resolucao["acao"] == "associar"
    assert mem.resolucao["automatica"] is False
    assert mem.resolucao["resolvida_na"] == resolvida_na
    return mem


# ===========================================================================
# Ficha excluída reativada pelo Admin Global (/alunos/acoes)
# ===========================================================================
def test_reativacao_da_ficha_pelo_admin_global_vale_para_a_coleta_desta_escola(
        db, escola_completa, cliente, cliente_global):
    """Prova 1 invertida: a coleta seguinte de A aplica em X e não sobra pendência."""
    e1, x, e2 = _cena_ficha_excluida(db, escola_completa, cliente)
    r = cliente_global.post(f"{API}/escolas/{e1}/alunos/acoes",
                            json={"aluno_ids": [x.id], "acao": "reativar"})
    assert r.status_code == 200, r.text
    assert len(r.json()["avisos"]) == 1
    mem = _confere_memoria(db, e1, x.id, "reativar")
    [aud] = _auditoria(db, "aluno.reativacao_outra_escola_confirmada")
    assert aud.detalhes["memoria_da_decisao"] == mem.id
    assert x.nome not in str(aud.detalhes)

    corpo = _importar(cliente, e1, x.nome, 55)
    assert corpo["ids_de_outra_escola"] == []
    assert _estrelas(db, x.id) == [55]
    assert _revisoes(db, e1, "pendente") == []
    # A outra escola não é alterada (e a conta segue efetiva lá).
    db.expire_all()
    assert db.execute(select(IdentidadeExterna.escola_id).where(
        IdentidadeExterna.escola_id == e2,
        IdentidadeExterna.id_externo == U)).scalar_one() == e2


def test_pendencia_aberta_antes_da_reativacao_fecha_na_coleta_seguinte(
        db, escola_completa, cliente, cliente_global):
    """A coleta de A trouxe U antes (pendência identidade_de_outra_escola). O Admin
    Global reativa X: a coleta seguinte associa e encerra a pendência."""
    e1, x, _e2 = _cena_ficha_excluida(db, escola_completa, cliente)
    assert _importar(cliente, e1, x.nome, 20,
                     data="2026-09-10T12:00:00")["ids_de_outra_escola"] == [U]
    assert len(_revisoes(db, e1, "pendente")) == 1
    assert cliente_global.post(f"{API}/escolas/{e1}/alunos/acoes",
                               json={"aluno_ids": [x.id], "acao": "reativar"}
                               ).status_code == 200
    corpo = _importar(cliente, e1, x.nome, 66, data="2026-09-11T12:00:00")
    assert corpo["ids_de_outra_escola"] == []
    assert 66 in _estrelas(db, x.id)
    assert _revisoes(db, e1, "pendente") == []


@pytest.mark.parametrize("acao,status", [("arquivar", "arquivado"),
                                         ("marcar_transferido", "transferido")])
def test_ficha_que_sai_de_excluido_para_inativa_nao_ganha_memoria(
        db, escola_completa, cliente, cliente_global, acao, status):
    """Arquivar ou marcar como transferido não grava memória: a ficha inativa não
    recebe dado, e a coleta seguinte continua mandando a conta para a revisão."""
    e1, x, _e2 = _cena_ficha_excluida(db, escola_completa, cliente)
    r = cliente_global.post(f"{API}/escolas/{e1}/alunos/acoes",
                            json={"aluno_ids": [x.id], "acao": acao})
    assert r.status_code == 200, r.text
    assert len(r.json()["avisos"]) == 1
    db.expire_all()
    assert db.get(Aluno, x.id).status == status
    assert _revisoes(db, e1, "resolvida") == []
    [aud] = _auditoria(db, "aluno.reativacao_outra_escola_confirmada")
    assert aud.detalhes["memoria_da_decisao"] is None
    corpo = _importar(cliente, e1, x.nome, 33)
    assert corpo["ids_de_outra_escola"] == [U]
    assert _estrelas(db, x.id) == []


# ===========================================================================
# Conta aposentada que volta a valer pelo Admin Global
# ===========================================================================
def test_conta_aposentada_escolhida_como_efetiva_vale_na_coleta_daqui(
        db, escola_completa, cliente, cliente_global):
    """Prova 3 invertida (/identidades/matific/efetiva)."""
    e1, x, _e2 = _cena_conta_aposentada(db, escola_completa)
    r = cliente_global.post(f"{API}/escolas/{e1}/importacoes/identidades/matific/efetiva",
                            json={"aluno_id": x.id, "id_externo_efetivo": U,
                                  "aposentar": [V], "motivo": "a conta certa e a U"})
    assert r.status_code == 200, r.text
    assert len(r.json()["avisos"]) == 1
    mem = _confere_memoria(db, e1, x.id, "definir_efetiva")
    [aud] = _auditoria(db, "identidade.reativacao_outra_escola_confirmada")
    assert aud.detalhes["memoria_da_decisao"] == mem.id
    corpo = _importar(cliente, e1, x.nome, 44)
    assert corpo["ids_de_outra_escola"] == []
    assert _estrelas(db, x.id) == [44]


def test_conta_aposentada_reativada_vale_na_coleta_daqui(
        db, escola_completa, cliente, cliente_global):
    """Mesma lacuna pelo /identidades/matific/reativar (V aposentada antes)."""
    e1, x, _e2 = _cena_conta_aposentada(db, escola_completa)
    ident_v = db.execute(select(IdentidadeExterna).where(
        IdentidadeExterna.escola_id == e1, IdentidadeExterna.id_externo == V)).scalar_one()
    ident_v.status = "aposentada"
    db.commit()
    r = cliente_global.post(f"{API}/escolas/{e1}/importacoes/identidades/matific/reativar",
                            json={"aluno_id": x.id, "id_externo": U,
                                  "motivo": "a conta certa e a U"})
    assert r.status_code == 200, r.text
    assert len(r.json()["avisos"]) == 1
    _confere_memoria(db, e1, x.id, "reativar")
    corpo = _importar(cliente, e1, x.nome, 47)
    assert corpo["ids_de_outra_escola"] == []
    assert _estrelas(db, x.id) == [47]


def test_conta_aposentada_de_ficha_inativa_nao_ganha_memoria(
        db, escola_completa, cliente, cliente_global):
    """Ficha ARQUIVADA: a conta volta a valer (decisão do Admin Global, com aviso),
    mas sem memória — a ficha inativa não recebe dado."""
    e1, x, _e2 = _cena_conta_aposentada(db, escola_completa)
    assert cliente.post(f"{API}/escolas/{e1}/alunos/acoes",
                        json={"aluno_ids": [x.id], "acao": "arquivar"}).status_code == 200
    r = cliente_global.post(f"{API}/escolas/{e1}/importacoes/identidades/matific/efetiva",
                            json={"aluno_id": x.id, "id_externo_efetivo": U,
                                  "aposentar": [V], "motivo": "a conta certa e a U"})
    assert r.status_code == 200, r.text
    assert len(r.json()["avisos"]) == 1
    assert _revisoes(db, e1, "resolvida") == []
    [aud] = _auditoria(db, "identidade.reativacao_outra_escola_confirmada")
    assert aud.detalhes["memoria_da_decisao"] is None
    assert _importar(cliente, e1, x.nome, 12)["ids_de_outra_escola"] == [U]
    assert _estrelas(db, x.id) == []
