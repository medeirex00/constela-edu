"""D10/D11 — a importação manual da gestão NÃO encerra a pendência da conta de
outra escola, nem quando a conta já vale aqui na ficha escolhida (4ª revisão de
integração do e97, dimensão identidade-backup; regressão da prova 1, invertida).

Cenário (o do próprio aviso do D10): a conta u-a vale na escola 1 (Ana). O Admin
Global confirma u-a na escola 2 (criança que mudou de escola) e, como anunciado, a
coleta seguinte da escola 1 manda u-a para a revisão ``identidade_de_outra_escola``.
O /resolver dessa pendência é 403 para a gestão da escola 1. Antes, a importação
manual DATADA com a ficha da Ana fixada (a dona da conta aqui) caía no passo 0 de
``decidir`` (``dono == aluno`` → ASSOCIAR via ``identidade``, sem o D10) e
``_encerrar_revisoes_respondidas`` fechava a pendência pela gestão; com nome não
idêntico, como DECISÃO HUMANA, que virava memória: a coleta seguinte da escola 1
associava u-a sozinha, sem o Admin Global.

Agora (``importacoes._retida_pelo_d10``): o dado da linha continua aplicado (a
conta que já vale aqui não é barrada — ``test_conta_ja_vinculada_aqui_a_mesma_
ficha_nao_e_barrada``), mas a pendência fica, com aviso. Seguem a regra geral o
Admin Global e a sincronização, que encerra sozinha quando a conta deixa de ser
de outra escola. Dados 100% fictícios; sem rede.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.academico import RevisaoIdentidade
from app.models.nota import LogAuditoria
from app.models.plataformas import SnapshotMatific
from app.services import identidade_aluno as ida
from tests._sync_nucleo_fakes import API, rodar, snap_atual
from tests.test_sync_escola_cruzada import K, instalar_navs
from tests.test_sync_escola_externa_decisoes import _cenario_v

AVISO_RETIDA = "só o Admin Global encerra essa pendência"


def _pendentes(db, eid, uuid):
    db.expire_all()
    return [r for r in db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == eid)).scalars().all()
        if r.id_externo == uuid and r.status == "pendente"]


def _auditoria_da_revisao(db, rev_id):
    db.expire_all()
    return [log.acao for log in db.execute(select(LogAuditoria).where(LogAuditoria.acao.in_(
        ("identidade.revisao_resolvida", "revisao.encerrada_automaticamente")))).scalars()
        if (log.detalhes or {}).get("revisao_id") == rev_id]


def _estado_pos_admin_global(db, escola_completa, cliente_global, monkeypatch):
    e1, a, e2, a2, nav1, p1, rev2 = _cenario_v(db, escola_completa, monkeypatch)
    r = cliente_global.post(f"{API}/escolas/{e2}/importacoes/revisoes/{rev2.id}/resolver",
                            json={"aluno_id": a2.id})
    assert r.status_code == 200, r.text
    # O efeito anunciado: a coleta seguinte da escola 1 manda u-a para a revisão.
    instalar_navs(monkeypatch, matific=nav1)
    rodar(db, e1, "matific")
    [pend] = _pendentes(db, e1, "u-a")
    assert pend.motivo == "identidade_de_outra_escola"
    return e1, a, e2, a2, nav1, p1, pend


def _confirmar_manual(cliente, eid, aluno, pend, nome, estrelas, *, com_data=True):
    ctx = pend.contexto or {}
    corpo = {
        "plataforma": pend.plataforma, "formato": pend.formato or "resumo", "tipo": "pdf",
        "linhas": [{"nome": nome, "aluno_id": aluno.id,
                    "dados": {"matific_uuid": "u-a", "estrelas": estrelas, "atividades": 11,
                              "pontuacao_media": 80, "turma_relatorio": K}}]}
    if com_data:
        # A data do relatório informada (o caso normal de quem sobe um relatório
        # datado) = a da coleta que abriu a pendência: pela regra geral, a linha
        # substitui o congelado e a pendência encerraria.
        corpo["data_referencia"] = (ctx.get("data_referencia") or (
            datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat())
    for campo in ("periodo_inicio", "periodo_fim"):
        if ctx.get(campo):
            corpo[campo] = ctx[campo]
    return cliente.post(f"{API}/escolas/{eid}/importacoes/confirmar", json=corpo)


@pytest.mark.parametrize("com_data", [True, False], ids=["com_data", "sem_data"])
def test_gestao_aplica_o_dado_pela_importacao_manual_mas_a_pendencia_fica(
        db, escola_completa, cliente, cliente_global, monkeypatch, com_data):
    e1, a, e2, a2, nav1, p1, pend = _estado_pos_admin_global(
        db, escola_completa, cliente_global, monkeypatch)
    # Controle: pelo /resolver a gestão da escola 1 leva 403 (D10).
    r = cliente.post(f"{API}/escolas/{e1}/importacoes/revisoes/{pend.id}/resolver",
                     json={"aluno_id": a.id})
    assert r.status_code == 403, r.text
    antes = snap_atual(db, SnapshotMatific, a.id)
    estrelas_antes = antes.estrelas if antes is not None else None
    # Pela importação manual (nome idêntico ao da ficha), a mesma gestão:
    r = _confirmar_manual(cliente, e1, a, pend, a.nome, 77, com_data=com_data)
    if not com_data:
        # Sem a data do relatório, sobre um retrato que veio da sincronização, o
        # upload manual é recusado ANTES de gravar (achado [10], 31/10/2026: o
        # arquivo podia ser antigo e viraria "o dado de hoje"). A garantia do D10
        # continua: a pendência fica, sem resolução nem auditoria, e nada é aplicado.
        assert r.status_code == 422, r.text
        assert "Informe a data do relatório" in r.json()["detail"]
        db.expire_all()
        rev = db.get(RevisaoIdentidade, pend.id)
        assert rev.status == "pendente"
        assert rev.resolvida_por_id is None and rev.resolucao is None
        assert _auditoria_da_revisao(db, pend.id) == []
        depois = snap_atual(db, SnapshotMatific, a.id)
        assert (depois.estrelas if depois is not None else None) == estrelas_antes != 77
        return
    assert r.status_code == 200, r.text
    db.expire_all()
    rev = db.get(RevisaoIdentidade, pend.id)
    assert rev.status == "pendente"                      # antes: "resolvida"
    assert rev.resolvida_por_id is None and rev.resolucao is None
    assert _auditoria_da_revisao(db, pend.id) == []
    # O dado declarado continua aplicado (a conta que já vale aqui não é barrada).
    assert r.json()["alunos_aplicados_ids"] == [a.id]
    assert snap_atual(db, SnapshotMatific, a.id).estrelas == 77
    # ...e a gestão é avisada de que a pendência continua e de quem a decide.
    assert any(AVISO_RETIDA in m and "OUTRA escola" in m for m in r.json()["avisos"])


def test_gestao_com_nome_abreviado_nao_grava_memoria_e_a_coleta_seguinte_revisa(
        db, escola_completa, cliente, cliente_global, monkeypatch):
    e1, a, e2, a2, nav1, p1, pend = _estado_pos_admin_global(
        db, escola_completa, cliente_global, monkeypatch)
    # O relatório traz o apelido; a gestão escolhe a ficha da Ana (alternativa).
    r = _confirmar_manual(cliente, e1, a, pend, "Aninha Souza", 77)
    assert r.status_code == 200, r.text
    db.expire_all()
    rev = db.get(RevisaoIdentidade, pend.id)
    assert rev.status == "pendente"
    assert rev.resolvida_por_id is None                  # antes: o admin da escola 1
    assert snap_atual(db, SnapshotMatific, a.id).estrelas == 77
    # Nenhuma memória humana: a porta única ainda manda u-a para a revisão.
    ctx = ida.carregar_contexto(db, e1)
    ida.marcar_ids_de_outra_escola(
        db, ctx, [type("L", (), {"dados": {"matific_uuid": "u-a"}, "nome": a.nome})()],
        "matific")
    dec = ida.decidir(ctx, ida.linha_de_dados(
        a.nome, {"matific_uuid": "u-a", "turma_relatorio": K},
        plataforma="matific", turma_nome=K))
    assert ("matific", "u-a") in ctx.ids_de_outra_escola
    assert (dec.acao, dec.motivo) == (ida.REVISAR, "identidade_de_outra_escola")
    # A coleta seguinte da escola 1: u-a continua na revisão e a Ana não recebe o
    # número da conta contestada (antes: 90, sem pendência).
    p1.linhas = [(u, n, k, e + 50, at + 5) for u, n, k, e, at in p1.linhas]
    instalar_navs(monkeypatch, matific=nav1)
    rodar(db, e1, "matific")
    pendentes = _pendentes(db, e1, "u-a")
    assert [p.motivo for p in pendentes] == ["identidade_de_outra_escola"]
    assert snap_atual(db, SnapshotMatific, a.id).estrelas == 77


def test_admin_global_na_importacao_manual_segue_a_regra_geral(
        db, escola_completa, cliente_global, monkeypatch):
    """O D10 é do Admin Global: a importação manual dele encerra a pendência como
    antes (a mesma decisão que ele pode tomar no /resolver)."""
    e1, a, e2, a2, nav1, p1, pend = _estado_pos_admin_global(
        db, escola_completa, cliente_global, monkeypatch)
    r = _confirmar_manual(cliente_global, e1, a, pend, a.nome, 77)
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(RevisaoIdentidade, pend.id).status == "resolvida"
    assert snap_atual(db, SnapshotMatific, a.id).estrelas == 77
    assert not any(AVISO_RETIDA in m for m in r.json()["avisos"])


def _conta_deixa_de_ser_de_outra_escola(db, a2):
    """A ficha da escola 2 é excluída: ficha excluída não segura a conta
    (``ida.efetivas_em_outra_escola``), e u-a deixa de ser de outra escola."""
    db.expire_all()
    a2 = db.merge(a2)
    a2.status = "excluido"
    db.commit()


def test_sincronizacao_encerra_sozinha_quando_a_conta_deixa_de_ser_de_outra_escola(
        db, escola_completa, cliente_global, monkeypatch):
    e1, a, e2, a2, nav1, p1, pend = _estado_pos_admin_global(
        db, escola_completa, cliente_global, monkeypatch)
    _conta_deixa_de_ser_de_outra_escola(db, a2)
    p1.linhas = [(u, n, k, e + 50, at + 5) for u, n, k, e, at in p1.linhas]
    instalar_navs(monkeypatch, matific=nav1)
    ex, _ = rodar(db, e1, "matific")
    assert ex.status == "concluida", (ex.status, ex.motivo)
    db.expire_all()
    rev = db.get(RevisaoIdentidade, pend.id)
    assert rev.status == "resolvida"
    assert rev.resolucao.get("automatica") is True and rev.resolvida_por_id is None
    assert _pendentes(db, e1, "u-a") == []
    assert snap_atual(db, SnapshotMatific, a.id).estrelas == 90


def test_gestao_encerra_pela_importacao_quando_a_conta_ja_nao_e_de_outra_escola(
        db, escola_completa, cliente, cliente_global, monkeypatch):
    """A trava olha o estado de AGORA (regra única): sem a conta efetiva na outra
    escola, a importação manual da gestão volta à regra geral."""
    e1, a, e2, a2, nav1, p1, pend = _estado_pos_admin_global(
        db, escola_completa, cliente_global, monkeypatch)
    _conta_deixa_de_ser_de_outra_escola(db, a2)
    r = _confirmar_manual(cliente, e1, a, pend, a.nome, 77)
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(RevisaoIdentidade, pend.id).status == "resolvida"
    assert not any(AVISO_RETIDA in m for m in r.json()["avisos"])
