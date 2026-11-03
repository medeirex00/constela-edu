"""D10 (risco V) pelos OUTROS caminhos — rodada 3 do e97.

A trava do D10 (commit 7cdda10): confirmar uma conta da plataforma que já é a
identidade EFETIVA de um aluno de OUTRA escola do Constela é só do Admin Global,
com aviso e auditoria. Ela valia só no ``POST /revisoes/{id}/resolver``; a revisão
adversarial do e97b mostrou dois desvios, agora fechados com a MESMA regra única
(``identidade_aluno.efetivas_em_outra_escola``):

  * importação manual com a ficha escolhida (``/importacoes/confirmar``, sonda S3):
    para a gestão da escola a linha vai para a revisão ``identidade_de_outra_escola``
    (nada vinculado nem aplicado); o Admin Global vincula, com aviso e a auditoria
    ``identidade.importacao_outra_escola_confirmada``;
  * a volta de uma conta APOSENTADA (``/identidades/{plataforma}/reativar`` e a
    escolha dela em ``/identidades/{plataforma}/efetiva``): 403 para a gestão; o
    Admin Global segue, com ``avisos`` e a auditoria
    ``identidade.reativacao_outra_escola_confirmada``.

Conectores reais com navegador falso; dados 100% fictícios (nomes de escola e de
criança inventados); sem rede.
"""
from sqlalchemy import select

from app.models import IdentidadeExterna
from app.models.academico import RevisaoIdentidade
from app.models.nota import LogAuditoria
from app.models.plataformas import SnapshotMatific
from app.sync import escola_externa
from tests._sync_nucleo_fakes import API, credencial, rodar
from tests.test_sync_escola_cruzada import NavMt, _nova_escola, _placar, instalar_navs

AVISO = "continua vinculada a um aluno de outra escola"
AUD_IMPORTACAO = "identidade.importacao_outra_escola_confirmada"
AUD_REATIVACAO = "identidade.reativacao_outra_escola_confirmada"
SEGUNDA = "Crianca Ficticia Da Segunda Escola"


def _cliente_de(email):
    from tests.test_sync_escola_externa_decisoes import _cliente_de as cliente

    return cliente(email)


def _auditoria(db, acao):
    db.expire_all()
    return db.execute(select(LogAuditoria).where(LogAuditoria.acao == acao)).scalars().all()


def _identidade(db, eid, id_externo):
    db.expire_all()
    return db.execute(select(IdentidadeExterna).where(
        IdentidadeExterna.escola_id == eid, IdentidadeExterna.plataforma == "matific",
        IdentidadeExterna.id_externo == id_externo)).scalars().first()


def _escola1_com_u_a(db, escola_completa, monkeypatch):
    """A escola 1 sincronizou o Matific (u-a, u-b e u-c efetivas nela) e está sem o
    vínculo da escola externa (o estado de antes da implantação)."""
    e1 = escola_completa["escola"].id
    credencial(db, e1, "matific")
    instalar_navs(monkeypatch, matific=NavMt(_placar(escola_completa)))
    assert rodar(db, e1, "matific")[0].status == "concluida"
    escola_externa.remover(db, e1, "matific")
    db.commit()
    assert _identidade(db, e1, "u-a").aluno_id == escola_completa["alunos"][0].id
    return e1


def _confirmar_manual(cliente, eid, aluno, uuid, **extra):
    from tests.test_sync_escola_cruzada import K

    return cliente.post(f"{API}/escolas/{eid}/importacoes/confirmar", json={
        "plataforma": "matific", "formato": "resumo", "tipo": "pdf", **extra,
        "linhas": [{"nome": aluno.nome, "aluno_id": aluno.id,
                    "dados": {"matific_uuid": uuid, "estrelas": 40, "atividades": 10,
                              "pontuacao_media": 80, "turma_relatorio": K}}]})


# ===========================================================================
# Importação manual com a ficha escolhida (sonda S3 do e97b, invertida)
# ===========================================================================
def test_s3_gestao_da_escola_nao_vincula_conta_efetiva_em_outra_pela_importacao(
        db, escola_completa, monkeypatch):
    """Antes (sonda S3): a gestão da escola 2, que recebe 403 no /resolver, vinculava
    a mesma conta pela importação manual com a ficha escolhida — e a criança da
    escola 1 caía em revisão lá na coleta seguinte. Agora a linha vai para a
    revisão 'identidade_de_outra_escola' daqui, com a ficha escolhida como
    sugestão; nada é vinculado nem aplicado, e a escola 1 não muda."""
    e1 = _escola1_com_u_a(db, escola_completa, monkeypatch)
    ana = escola_completa["alunos"][0]
    escola2, _t, (a2,) = _nova_escola(db, com_alunos=[SEGUNDA])
    e2 = escola2.id

    r = _confirmar_manual(_cliente_de(f"admin{e2}@teste.local"), e2, a2, "u-a")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert _identidade(db, e2, "u-a") is None              # a sonda S3: nada vinculado
    assert corpo["qtd_revisoes"] == 1 and corpo["ids_de_outra_escola"] == ["u-a"]
    assert corpo["alunos_aplicados_ids"] == [] and not any(AVISO in m for m in corpo["avisos"])
    [rev] = db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == e2)).scalars().all()
    assert (rev.status, rev.motivo, rev.id_externo) == (
        "pendente", "identidade_de_outra_escola", "u-a")
    assert [c["aluno_id"] for c in rev.candidatos] == [a2.id]
    assert db.execute(select(SnapshotMatific).where(
        SnapshotMatific.aluno_id == a2.id)).first() is None
    assert _auditoria(db, AUD_IMPORTACAO) == []
    assert _identidade(db, e1, "u-a").aluno_id == ana.id    # a escola 1 não muda

    # E a decisão continua sendo do Admin Global no /resolver (D10): 403 aqui.
    r2 = _cliente_de(f"admin{e2}@teste.local").post(
        f"{API}/escolas/{e2}/importacoes/revisoes/{rev.id}/resolver", json={"aluno_id": a2.id})
    assert r2.status_code == 403, r2.text


def test_s3_admin_global_vincula_pela_importacao_com_aviso_e_auditoria(
        db, escola_completa, cliente_global, monkeypatch):
    e1 = _escola1_com_u_a(db, escola_completa, monkeypatch)
    ana = escola_completa["alunos"][0]
    escola2, _t, (a2,) = _nova_escola(db, com_alunos=[SEGUNDA])
    e2 = escola2.id

    r = _confirmar_manual(cliente_global, e2, a2, "u-a")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert _identidade(db, e2, "u-a").aluno_id == a2.id
    assert corpo["alunos_aplicados_ids"] == [a2.id]
    assert sum(AVISO in m for m in corpo["avisos"]) == 1, corpo["avisos"]
    [aud] = _auditoria(db, AUD_IMPORTACAO)
    assert (aud.escola_id, aud.entidade_id) == (e2, a2.id) and aud.usuario_id is not None
    assert aud.detalhes["outra_escola_id"] == e1 and aud.detalhes["id_externo"] == "u-a"
    assert aud.detalhes["importacao_id"] == corpo["importacao_id"]
    assert SEGUNDA not in str(aud.detalhes)                  # trilha sem nome
    assert _identidade(db, e1, "u-a").aluno_id == ana.id    # a outra escola não muda


def test_importacao_manual_de_conta_sem_vinculo_em_outra_escola_segue_com_a_gestao(
        db, escola_completa, monkeypatch):
    """Controle: conta que NÃO é efetiva em outra escola continua sendo vinculada
    pela gestão da escola, sem aviso nem auditoria do D10."""
    _escola1_com_u_a(db, escola_completa, monkeypatch)
    escola2, _t, (a2,) = _nova_escola(db, com_alunos=[SEGUNDA])
    e2 = escola2.id
    r = _confirmar_manual(_cliente_de(f"admin{e2}@teste.local"), e2, a2, "u-so-da-segunda")
    assert r.status_code == 200, r.text
    assert _identidade(db, e2, "u-so-da-segunda").aluno_id == a2.id
    assert not any(AVISO in m for m in r.json()["avisos"])
    assert _auditoria(db, AUD_IMPORTACAO) == []


def test_conta_ja_vinculada_aqui_a_mesma_ficha_nao_e_barrada(db, escola_completa,
                                                             monkeypatch):
    """A conta que JÁ vale aqui para a ficha escolhida (decisão anterior do Admin
    Global) não volta para a revisão a cada importação manual: nada novo é
    vinculado, então não há nada a decidir de novo."""
    _escola1_com_u_a(db, escola_completa, monkeypatch)
    escola2, _t, (a2,) = _nova_escola(db, com_alunos=[SEGUNDA])
    e2 = escola2.id
    db.add(IdentidadeExterna(escola_id=e2, aluno_id=a2.id, plataforma="matific",
                             id_externo="u-a"))
    db.commit()
    r = _confirmar_manual(_cliente_de(f"admin{e2}@teste.local"), e2, a2, "u-a")
    assert r.status_code == 200, r.text
    assert r.json()["alunos_aplicados_ids"] == [a2.id]
    assert _auditoria(db, AUD_IMPORTACAO) == []


# ===========================================================================
# Volta de uma conta APOSENTADA: /reativar e /efetiva
# ===========================================================================
def _escola2_com_u_a_aposentada(db, escola_completa, monkeypatch, *, outra_efetiva=False):
    """Escola 2: a ficha da criança tem a conta u-a APOSENTADA (e, se pedido, uma
    conta u-z efetiva). Na escola 1, u-a é a identidade efetiva da Ana."""
    e1 = _escola1_com_u_a(db, escola_completa, monkeypatch)
    escola2, _t, (a2,) = _nova_escola(db, com_alunos=[SEGUNDA])
    e2 = escola2.id
    db.add(IdentidadeExterna(escola_id=e2, aluno_id=a2.id, plataforma="matific",
                             id_externo="u-a", status="aposentada",
                             motivo_aposentadoria="conta duplicada ficticia"))
    if outra_efetiva:
        db.add(IdentidadeExterna(escola_id=e2, aluno_id=a2.id, plataforma="matific",
                                 id_externo="u-z"))
    db.commit()
    return e1, e2, a2


def _reativar(cliente, e2, a2, id_externo="u-a"):
    return cliente.post(f"{API}/escolas/{e2}/importacoes/identidades/matific/reativar",
                        json={"aluno_id": a2.id, "id_externo": id_externo,
                              "motivo": "a criança voltou a usar esta conta"})


def test_reativar_conta_efetiva_em_outra_escola_e_so_do_admin_global(db, escola_completa,
                                                                     monkeypatch):
    e1, e2, a2 = _escola2_com_u_a_aposentada(db, escola_completa, monkeypatch)
    r = _reativar(_cliente_de(f"admin{e2}@teste.local"), e2, a2)
    assert r.status_code == 403, r.text
    assert "Admin Global" in r.json()["detail"]
    assert _identidade(db, e2, "u-a").status == "aposentada"     # nada mudou
    assert _auditoria(db, "identidade.reativada") == []
    assert _auditoria(db, AUD_REATIVACAO) == []
    assert _identidade(db, e1, "u-a").aluno_id == escola_completa["alunos"][0].id


def test_admin_global_reativa_com_aviso_e_auditoria(db, escola_completa, cliente_global,
                                                    monkeypatch):
    e1, e2, a2 = _escola2_com_u_a_aposentada(db, escola_completa, monkeypatch)
    r = _reativar(cliente_global, e2, a2)
    assert r.status_code == 200, r.text
    assert any(AVISO in m for m in r.json()["avisos"]), r.json()
    assert _identidade(db, e2, "u-a").status == "efetiva"
    [aud] = _auditoria(db, AUD_REATIVACAO)
    assert (aud.escola_id, aud.entidade_id, aud.detalhes["acao"]) == (e2, a2.id, "reativar")
    assert aud.detalhes["outra_escola_id"] == e1 and aud.usuario_id is not None
    assert len(_auditoria(db, "identidade.reativada")) == 1
    assert _identidade(db, e1, "u-a").aluno_id == escola_completa["alunos"][0].id


def test_reativar_conta_sem_vinculo_em_outra_escola_segue_com_a_gestao(db, escola_completa,
                                                                       monkeypatch):
    _e1, e2, a2 = _escola2_com_u_a_aposentada(db, escola_completa, monkeypatch)
    db.add(IdentidadeExterna(escola_id=e2, aluno_id=a2.id, plataforma="matific",
                             id_externo="u-velha-da-segunda", status="aposentada"))
    db.commit()
    r = _reativar(_cliente_de(f"admin{e2}@teste.local"), e2, a2, "u-velha-da-segunda")
    assert r.status_code == 200, r.text
    assert r.json()["avisos"] == []
    assert _auditoria(db, AUD_REATIVACAO) == []


def _efetiva(cliente, e2, a2):
    return cliente.post(f"{API}/escolas/{e2}/importacoes/identidades/matific/efetiva",
                        json={"aluno_id": a2.id, "id_externo_efetivo": "u-a",
                              "aposentar": ["u-z"], "motivo": "conta certa da criança"})


def test_escolher_aposentada_efetiva_em_outra_escola_e_so_do_admin_global(
        db, escola_completa, cliente_global, monkeypatch):
    """O mesmo desvio pela tela "Usar só esta conta" chamada com a aposentada."""
    e1, e2, a2 = _escola2_com_u_a_aposentada(db, escola_completa, monkeypatch,
                                             outra_efetiva=True)
    r = _efetiva(_cliente_de(f"admin{e2}@teste.local"), e2, a2)
    assert r.status_code == 403, r.text
    assert _identidade(db, e2, "u-a").status == "aposentada"
    assert _identidade(db, e2, "u-z").status == "efetiva"
    assert _auditoria(db, "identidade.efetiva_definida") == []

    r = _efetiva(cliente_global, e2, a2)
    assert r.status_code == 200, r.text
    assert any(AVISO in m for m in r.json()["avisos"])
    assert (_identidade(db, e2, "u-a").status, _identidade(db, e2, "u-z").status) == (
        "efetiva", "aposentada")
    [aud] = _auditoria(db, AUD_REATIVACAO)
    assert (aud.detalhes["acao"], aud.detalhes["outra_escola_id"]) == ("definir_efetiva", e1)


def test_usar_so_a_conta_que_ja_vale_nao_passa_pela_trava(db, escola_completa,
                                                         monkeypatch):
    """Controle da tela: escolher a conta que JÁ é a efetiva (o botão só aparece
    nela) não faz nada voltar a valer — segue com a gestão, sem aviso."""
    _e1, e2, a2 = _escola2_com_u_a_aposentada(db, escola_completa, monkeypatch,
                                              outra_efetiva=True)
    r = _cliente_de(f"admin{e2}@teste.local").post(
        f"{API}/escolas/{e2}/importacoes/identidades/matific/efetiva",
        json={"aluno_id": a2.id, "id_externo_efetivo": "u-z", "aposentar": ["u-a"],
              "motivo": "conta certa da criança"})
    assert r.status_code == 200, r.text
    assert r.json()["avisos"] == []
    assert _auditoria(db, AUD_REATIVACAO) == []
