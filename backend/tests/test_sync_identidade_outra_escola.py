"""Conta da plataforma (uuid do Matific, studentId do Elefante) já EFETIVA em
OUTRA escola do Constela (Etapa 3, frente escola): a linha não aplica nada nesta
escola, vai para a revisão ``identidade_de_outra_escola`` com alerta crítico, e a
outra escola não é tocada. Conectores reais com navegador falso; dados fictícios;
sem rede. Regras em docs/SINCRONIZACAO.md ("Escola externa")."""
from sqlalchemy import select

from app.models import IdentidadeExterna
from app.models.academico import RevisaoIdentidade
from app.models.plataformas import SnapshotElefante, SnapshotMatific
from app.services import identidade_aluno as ida
from app.services import triagem_revisoes
from tests._sync_nucleo_fakes import API, alertas_abertos, contagens, credencial, rodar, vincular
from tests.test_sync_escola_cruzada import (
    CID_A, CID_B, ESC_A, K, NavEl, NavMt, _alerta, _da_escola, _nova_escola, _placar, _turmas,
    instalar_navs)


# ===========================================================================
# IDENTIDADE: id externo já EFETIVO em outra escola do Constela
# ===========================================================================
def _escola_dona_de(db, plataforma, id_externo, nome="Aluna Da Primeira Escola Ficticia"):
    escola, _t, alunos = _nova_escola(db, nome="ESCOLA PRIMEIRA FICTICIA", com_alunos=[nome])
    vincular(db, escola.id, alunos[0].id, plataforma, id_externo)
    db.commit()
    return escola, alunos[0]


def test_uuid_efetivo_em_outra_escola_vai_para_revisao_e_nao_aplica(db, escola_completa,
                                                                    cliente, cliente_global,
                                                                    monkeypatch):
    eid = escola_completa["escola"].id
    a, _b, _c = escola_completa["alunos"]
    outra, dona = _escola_dona_de(db, "matific", "u-a")
    antes_outra = contagens(db, outra.id)
    credencial(db, eid, "matific")
    instalar_navs(monkeypatch, matific=NavMt(_placar(escola_completa)))
    ex, _ = rodar(db, eid, "matific")
    assert ex.status == "concluida", (ex.status, ex.motivo, ex.erro_resumo)   # u-b, u-c
    assert ex.qtd_alunos == 2 and ex.qtd_em_revisao == 1
    rev = db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == eid, RevisaoIdentidade.status == "pendente")).scalars().one()
    assert (rev.motivo, rev.id_externo) == ("identidade_de_outra_escola", "u-a")
    assert [c["aluno_id"] for c in rev.candidatos] == [a.id]       # sugestão pelo nome
    assert db.execute(select(IdentidadeExterna).where(
        IdentidadeExterna.escola_id == eid, IdentidadeExterna.id_externo == "u-a")).first() is None
    assert db.execute(select(SnapshotMatific).where(SnapshotMatific.aluno_id == a.id)).first() is None
    assert _da_escola(contagens(db, outra.id)) == _da_escola(antes_outra)                 # a outra escola intacta
    assert db.get(IdentidadeExterna, db.execute(select(IdentidadeExterna.id).where(
        IdentidadeExterna.escola_id == outra.id)).scalar_one()).aluno_id == dona.id
    alerta = _alerta(db, eid, "identidade_de_outra_escola")
    assert alerta is not None and alerta.severidade == "critico"
    # A triagem nunca dá isso por "seguro".
    tri = triagem_revisoes.triar_revisoes(ida.carregar_contexto(db, eid), [rev])[rev.id]
    assert tri.classificacao == triagem_revisoes.DECISAO_HUMANA
    # A conta é efetiva em OUTRA escola: a gestão desta escola não confirma
    # (decisão D10); o Admin Global confirma (uma vez) que a conta é da Ana daqui.
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/revisoes/{rev.id}/resolver",
                     json={"aluno_id": a.id})
    assert r.status_code == 403, r.text
    r = cliente_global.post(f"{API}/escolas/{eid}/importacoes/revisoes/{rev.id}/resolver",
                            json={"aluno_id": a.id})
    assert r.status_code == 200, r.text
    ex2, _ = rodar(db, eid, "matific")
    assert ex2.status in ("concluida", "sem_atualizacao"), (ex2.status, ex2.motivo)
    assert ex2.qtd_em_revisao == 0
    assert _alerta(db, eid, "identidade_de_outra_escola") is None   # fechou
    assert _da_escola(contagens(db, outra.id)) == _da_escola(antes_outra)


def test_student_id_efetivo_em_outra_escola_vai_para_revisao(db, escola_completa,
                                                             monkeypatch):
    eid = escola_completa["escola"].id
    a, b, _c = escola_completa["alunos"]
    outra, _dona = _escola_dona_de(db, "elefante", "7001")
    antes_outra = contagens(db, outra.id)
    credencial(db, eid, "elefante")
    turmas = _turmas(escola_completa)
    del turmas[CID_B]
    instalar_navs(monkeypatch, elefante=NavEl(turmas, escola_da_turma={CID_A: ESC_A}))
    ex, _ = rodar(db, eid, "elefante")
    assert ex.status == "concluida", (ex.status, ex.motivo, ex.erro_resumo)   # só a 7002
    motivos = {r.motivo for r in db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == eid, RevisaoIdentidade.status == "pendente")).scalars()}
    assert motivos == {"identidade_de_outra_escola"}
    assert db.execute(select(SnapshotElefante).where(SnapshotElefante.aluno_id == a.id)).first() is None
    assert db.execute(select(SnapshotElefante).where(SnapshotElefante.aluno_id == b.id)).first()
    assert _da_escola(contagens(db, outra.id)) == _da_escola(antes_outra)
    assert "identidade_de_outra_escola" in alertas_abertos(db, eid, "elefante")


def test_previa_mostra_a_identidade_de_outra_escola_como_revisao(db, escola_completa):
    """Prévia = confirmação: a importação MANUAL marca a mesma linha."""
    from app.services import importacao as svc

    eid = escola_completa["escola"].id
    _escola_dona_de(db, "matific", "u-a")
    a = escola_completa["alunos"][0]
    linhas = [svc.LinhaImportacao(numero=1, nome=a.nome,
                               dados={"matific_uuid": "u-a", "estrelas": 5, "atividades": 2,
                                      "turma_relatorio": K})]
    svc.casar_nomes(db, eid, linhas, plataforma="matific")
    assert linhas[0].correspondencia["status"] == "revisar"
    assert linhas[0].correspondencia["motivo"] == "identidade_de_outra_escola"


def test_motivo_novo_cabe_na_coluna_e_tem_texto():
    """O tipo do alerta é String(30); o motivo da revisão tem texto para a tela."""
    assert len("identidade_de_outra_escola") <= 30
    assert "identidade_de_outra_escola" in ida.MOTIVOS
