"""D10/D11 — a importação manual da gestão não encerra NENHUMA pendência da conta
que hoje é efetiva em outra escola, qualquer que seja o motivo (risco residual
declarado no marco 3 do e97, grupo identidade-backup).

``importacoes._retida_pelo_d10`` só retinha a pendência de motivo
``identidade_de_outra_escola``. Cenário que passava por baixo dela (dados 100%
fictícios; sem rede):

  1. a conta u-a vale na escola 1 (Ana) e a Ana é marcada como transferida; a
     coleta seguinte da escola 1 manda u-a para a revisão
     ``identidade_de_ficha_inativa`` (passo 1 de ``decidir``) — aberta ANTES de a
     conta virar efetiva em outra escola;
  2. o Admin Global confirma u-a na escola 2 (a criança que mudou de escola): a
     conta passa a valer nas duas;
  3. a gestão da escola 1 leva 403 no /resolver dessa pendência (o D10 do
     /resolver olha a conta, não o motivo), mas sobe o relatório à mão com a
     ficha da Ana fixada: passo 0 de ``decidir`` (``dono == aluno`` → ASSOCIAR
     via ``identidade``) e ``_encerrar_revisoes_respondidas`` fechava a pendência
     como DECISÃO HUMANA da gestão. Essa decisão virava memória
     (``carregar_contexto``) e o passo 0d (``_confirmado_por_humano``) da coleta
     seguinte associava u-a à Ana sozinho: o D10 contornado, sem o Admin Global.

Agora a pendência fica (com o mesmo aviso de antes), o dado declarado continua
aplicado à ficha que já é a dona da conta aqui, e seguem a regra geral o Admin
Global, a sincronização (linha sem ficha fixada) e a gestão quando a conta deixa
de ser de outra escola.
"""
import pytest
from sqlalchemy import select

from app.models.academico import RevisaoIdentidade
from app.models.plataformas import SnapshotMatific
from app.routers import importacoes
from app.services import identidade_aluno as ida
from tests._sync_nucleo_fakes import API, rodar, snap_atual
from tests.test_d10_importacao_manual_nao_encerra import (
    AVISO_RETIDA, _auditoria_da_revisao, _confirmar_manual,
    _conta_deixa_de_ser_de_outra_escola, _pendentes)
from tests.test_sync_escola_cruzada import K, instalar_navs
from tests.test_sync_escola_externa_decisoes import _cenario_v

MOTIVO = "identidade_de_ficha_inativa"


def _marcar_transferida(db, aluno):
    db.expire_all()
    aluno = db.merge(aluno)
    aluno.status = "transferido"
    db.commit()


def _estado_ficha_inativa_pos_admin_global(db, escola_completa, cliente_global,
                                           monkeypatch):
    """Devolve (e1, a, e2, a2, nav1, p1, pendência ``identidade_de_ficha_inativa``
    de u-a na escola 1), com u-a já efetiva também na escola 2."""
    e1, a, e2, a2, nav1, p1, rev2 = _cenario_v(db, escola_completa, monkeypatch)
    rev2_id = rev2.id
    # 1. A Ana sai da escola 1 (transferida) e a coleta seguinte de lá manda u-a
    #    para a revisão de ficha inativa — u-a ainda não vale na escola 2.
    _marcar_transferida(db, a)
    p1.linhas = [(u, n, k, e + 5, at + 2) for u, n, k, e, at in p1.linhas]
    instalar_navs(monkeypatch, matific=nav1)
    rodar(db, e1, "matific")
    [pend] = _pendentes(db, e1, "u-a")
    assert pend.motivo == MOTIVO
    assert ida.efetivas_em_outra_escola(db, e1, "matific", ["u-a"]) == {}
    # 2. O Admin Global confirma u-a na escola 2: a conta passa a valer nas duas.
    r = cliente_global.post(f"{API}/escolas/{e2}/importacoes/revisoes/{rev2_id}/resolver",
                            json={"aluno_id": a2.id})
    assert r.status_code == 200, r.text
    assert ida.efetivas_em_outra_escola(db, e1, "matific", ["u-a"]) == {"u-a": e2}
    db.expire_all()
    return e1, a, e2, a2, nav1, p1, db.get(RevisaoIdentidade, pend.id)


def _decisao_da_coleta(db, e1, nome):
    """O que a porta única decide para a linha de u-a SEM ficha fixada (a coleta)."""
    ctx = ida.carregar_contexto(db, e1)
    ida.marcar_ids_de_outra_escola(
        db, ctx, [type("L", (), {"dados": {"matific_uuid": "u-a"}, "nome": nome})()],
        "matific")
    return ida.decidir(ctx, ida.linha_de_dados(
        nome, {"matific_uuid": "u-a", "turma_relatorio": K},
        plataforma="matific", turma_nome=K))


@pytest.mark.parametrize("abreviado", [False, True], ids=["nome_identico", "nome_abreviado"])
def test_gestao_nao_encerra_pendencia_de_ficha_inativa_da_conta_de_outra_escola(
        db, escola_completa, cliente, cliente_global, monkeypatch, abreviado):
    e1, a, e2, a2, nav1, p1, pend = _estado_ficha_inativa_pos_admin_global(
        db, escola_completa, cliente_global, monkeypatch)
    # Controle (só leitura do /resolver): o D10 dele vale para QUALQUER motivo —
    # a pendência de ficha inativa desta conta também é 403 para a gestão.
    r = cliente.post(f"{API}/escolas/{e1}/importacoes/revisoes/{pend.id}/resolver",
                     json={"aluno_id": a.id})
    assert r.status_code == 403, r.text
    assert "Admin Global" in r.json()["detail"]
    # Pela importação manual, com a ficha da Ana fixada, a mesma gestão:
    nome = "Aninha Souza" if abreviado else a.nome
    r = _confirmar_manual(cliente, e1, a, pend, nome, 77)
    assert r.status_code == 200, r.text
    db.expire_all()
    rev = db.get(RevisaoIdentidade, pend.id)
    assert (rev.status, rev.motivo) == ("pendente", MOTIVO)          # antes: "resolvida"
    assert rev.resolvida_por_id is None and rev.resolucao is None    # antes: a gestão
    assert rev.aluno_escolhido_id is None
    assert _auditoria_da_revisao(db, pend.id) == []
    # O dado declarado continua aplicado à ficha que já é a dona da conta aqui.
    assert snap_atual(db, SnapshotMatific, a.id).estrelas == 77
    # O aviso de sempre: a pendência continua e só o Admin Global a encerra.
    assert any(AVISO_RETIDA in m and "OUTRA escola" in m for m in r.json()["avisos"])
    # Nenhuma memória humana: a coleta (sem ficha fixada) ainda revisa u-a.
    dec = _decisao_da_coleta(db, e1, nome)
    assert (dec.acao, dec.motivo) == (ida.REVISAR, "identidade_de_outra_escola")


def test_gestao_com_nome_abreviado_a_coleta_seguinte_nao_associa_sozinha(
        db, escola_completa, cliente, cliente_global, monkeypatch):
    """O furo inteiro: antes, a memória gravada pela importação manual fazia a
    coleta seguinte da escola 1 aplicar à Ana o número de u-a (passo 0d)."""
    e1, a, e2, a2, nav1, p1, pend = _estado_ficha_inativa_pos_admin_global(
        db, escola_completa, cliente_global, monkeypatch)
    r = _confirmar_manual(cliente, e1, a, pend, "Aninha Souza", 77)
    assert r.status_code == 200, r.text
    p1.linhas = [(u, n, k, e + 50, at + 5) for u, n, k, e, at in p1.linhas]
    instalar_navs(monkeypatch, matific=nav1)
    rodar(db, e1, "matific")
    pendentes = _pendentes(db, e1, "u-a")
    # A mesma pendência (mesma chave) continua aberta, agora pela conta de outra
    # escola — e só o Admin Global a encerra.
    assert [p.id for p in pendentes] == [pend.id]
    assert [p.motivo for p in pendentes] == ["identidade_de_outra_escola"]
    assert snap_atual(db, SnapshotMatific, a.id).estrelas == 77     # antes: 95
    db.expire_all()
    assert db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == e1, RevisaoIdentidade.id_externo == "u-a",
        RevisaoIdentidade.status == "resolvida")).first() is None


def test_admin_global_na_importacao_manual_encerra_a_pendencia_de_ficha_inativa(
        db, escola_completa, cliente_global, monkeypatch):
    """O D10 é do Admin Global: a importação manual dele segue a regra geral."""
    e1, a, e2, a2, nav1, p1, pend = _estado_ficha_inativa_pos_admin_global(
        db, escola_completa, cliente_global, monkeypatch)
    r = _confirmar_manual(cliente_global, e1, a, pend, a.nome, 77)
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(RevisaoIdentidade, pend.id).status == "resolvida"
    assert snap_atual(db, SnapshotMatific, a.id).estrelas == 77
    assert not any(AVISO_RETIDA in m for m in r.json()["avisos"])


def test_gestao_encerra_a_pendencia_de_ficha_inativa_quando_a_conta_ja_nao_e_de_outra_escola(
        db, escola_completa, cliente, cliente_global, monkeypatch):
    """A trava olha o estado de AGORA (regra única): excluída a ficha da escola 2,
    u-a deixa de ser de outra escola e a gestão volta à regra geral."""
    e1, a, e2, a2, nav1, p1, pend = _estado_ficha_inativa_pos_admin_global(
        db, escola_completa, cliente_global, monkeypatch)
    _conta_deixa_de_ser_de_outra_escola(db, a2)
    r = _confirmar_manual(cliente, e1, a, pend, a.nome, 77)
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(RevisaoIdentidade, pend.id).status == "resolvida"
    assert not any(AVISO_RETIDA in m for m in r.json()["avisos"])


@pytest.mark.parametrize("motivo", [
    "identidade_de_outra_escola", "identidade_de_ficha_inativa", "ficha_inativa",
    "outra_identidade_na_plataforma", "nome_incompleto", "turma_arquivada"])
def test_retencao_vale_para_qualquer_motivo_so_com_ficha_fixada_e_fora_do_admin_global(
        db, escola_completa, cliente_global, monkeypatch, motivo):
    """A regra, motivo a motivo: retém só a pendência da linha com a ficha FIXADA,
    de quem não é o Admin Global, de conta HOJE efetiva em outra escola. A
    sincronização (sem ficha fixada) e o Admin Global seguem a regra geral."""
    e1, a, e2, a2, nav1, p1, pend = _estado_ficha_inativa_pos_admin_global(
        db, escola_completa, cliente_global, monkeypatch)
    rev = RevisaoIdentidade(escola_id=e1, plataforma="matific", id_externo="u-a",
                            motivo=motivo, status="pendente")
    ctx = ida.carregar_contexto(db, e1)
    dados = {"matific_uuid": "u-a", "turma_relatorio": K}
    fixada = ida.linha_de_dados(a.nome, dados, plataforma="matific", turma_nome=K,
                                aluno_id=a.id)
    coleta = ida.linha_de_dados(a.nome, dados, plataforma="matific", turma_nome=K)
    assert importacoes._retida_pelo_d10(db, e1, ctx, fixada, rev, {}) is True
    assert importacoes._retida_pelo_d10(db, e1, ctx, coleta, rev, {}) is False
    ctx.confirma_conta_de_outra_escola = True                        # Admin Global
    assert importacoes._retida_pelo_d10(db, e1, ctx, fixada, rev, {}) is False
    # Conta que não é de outra escola: nada retido.
    ctx.confirma_conta_de_outra_escola = False
    daqui = RevisaoIdentidade(escola_id=e1, plataforma="matific", id_externo="u-b",
                              motivo=motivo, status="pendente")
    assert importacoes._retida_pelo_d10(db, e1, ctx, fixada, daqui, {}) is False
