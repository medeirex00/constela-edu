"""Conta duplicada: uma identidade EFETIVA, a outra APOSENTADA (mas preservada).

Quando a criança tem duas contas na mesma plataforma e a escola não consegue
apagar a duplicada lá, o Constela precisa dizer qual vale — sem apagar nada e
sem fingir que mexeu na plataforma externa.

A regra que estes testes protegem: a aposentada continua no banco, provando de
quem era o id externo, mas sai do casamento, do retrato e da pontuação, e não
volta sozinha. Só uma decisão explícita a reativa.
"""
import pytest
from sqlalchemy import func, select

from app.models import (Aluno, IdentidadeExterna, LogAuditoria, Matricula,
                        RevisaoIdentidade, SnapshotMatific, Turma)
from app.routers import importacoes as imp
from app.schemas.importacao import ImportacaoConfirm, LinhaConfirmacao
from app.services import identidade_aluno as ida
from app.services import identidade_efetiva as efe
from app.services import triagem_revisoes as tri

ANO = 2026


# --- montagem ---------------------------------------------------------------

def _turma(db, escola, nome="3ºA", codigo="300300001"):
    t = Turma(escola_id=escola.id, nome=nome, ano_escolar="3º Ano", ano_letivo=ANO,
              codigo_externo=codigo, turno="tarde")
    db.add(t)
    db.flush()
    return t


def _aluno(db, escola, turma, nome):
    a = Aluno(escola_id=escola.id, nome=nome, da_lista_piloto=True)
    db.add(a)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=turma.id,
                     ano_letivo=ANO))
    db.flush()
    return a


def _vincular(db, escola, aluno, id_externo, plataforma="matific"):
    i = IdentidadeExterna(escola_id=escola.id, aluno_id=aluno.id,
                          plataforma=plataforma, id_externo=id_externo)
    db.add(i)
    db.flush()
    return i


def _linha(nome, turma, uuid, atividades, estrelas):
    return LinhaConfirmacao(
        nome=nome,
        dados={"turma_relatorio": turma, "matific_uuid": uuid,
               "atividades": atividades, "estrelas": estrelas,
               "pontuacao_media": round(estrelas / max(atividades, 1), 2)},
        aluno_id=None, criar_em_turma_nome=turma)


def _importar(db, escola, admin, linhas, *, recalcular=False):
    conf = ImportacaoConfirm(plataforma="matific", formato="resumo", tipo="texto",
                             linhas=linhas, recalcular=recalcular)
    return imp.confirmar(dados=conf, escola_id=escola.id, usuario=admin, db=db)


def _snaps(db, aluno_id):
    return db.execute(select(SnapshotMatific).where(SnapshotMatific.aluno_id == aluno_id)
                      .order_by(SnapshotMatific.id)).scalars().all()


def _estados(db, escola, aluno):
    return {i.id_externo: i.status for i in efe.identidades_do_aluno(
        db, escola.id, aluno.id, "matific")}


@pytest.fixture()
def cena(db, escola_completa):
    """A ficha com DUAS contas Matific — o estado real da Allyce/Melissa."""
    esc, admin = escola_completa["escola"], escola_completa["admin"]
    t = _turma(db, esc)
    aluna = _aluno(db, esc, t, "ALLYCE CRISTINA BARBOSA DE ALMEIDA")
    colega = _aluno(db, esc, t, "BEATRIZ SOUZA LIMA")
    _vincular(db, esc, aluna, "conta-principal")
    _vincular(db, esc, aluna, "conta-duplicada")
    _vincular(db, esc, colega, "conta-colega")
    db.commit()
    return {"escola": esc, "admin": admin, "turma": t.nome,
            "aluna": aluna, "colega": colega}


def _decidir(db, cena, efetiva="conta-principal", aposentar=("conta-duplicada",),
             motivo="a escola confirmou que esta é a conta em uso"):
    r = efe.definir_efetiva(db, cena["escola"].id, aluno_id=cena["aluna"].id,
                            plataforma="matific", id_externo_efetivo=efetiva,
                            aposentar=list(aposentar), motivo=motivo,
                            usuario_id=cena["admin"].id)
    db.commit()
    return r


# --- 1. o conceito ----------------------------------------------------------

def test_define_a_efetiva_e_aposenta_a_outra_sem_apagar_nada(db, cena):
    antes = db.scalar(select(func.count()).select_from(IdentidadeExterna))
    r = _decidir(db, cena)

    assert r.efetiva == "conta-principal" and r.aposentadas == ("conta-duplicada",)
    assert _estados(db, cena["escola"], cena["aluna"]) == {
        "conta-principal": "efetiva", "conta-duplicada": "aposentada"}
    # NADA foi apagado: as duas linhas continuam lá
    assert db.scalar(select(func.count()).select_from(IdentidadeExterna)) == antes


def test_a_aposentada_guarda_quem_decidiu_quando_e_por_que(db, cena):
    _decidir(db, cena, motivo="conta antiga, sem uso desde maio")
    apos = next(i for i in efe.identidades_do_aluno(
        db, cena["escola"].id, cena["aluna"].id, "matific")
        if i.id_externo == "conta-duplicada")
    assert apos.aposentada_em is not None
    assert apos.aposentada_por_id == cena["admin"].id
    assert apos.motivo_aposentadoria == "conta antiga, sem uso desde maio"


def test_a_operacao_e_reversivel(db, cena):
    """Reversível de duas formas: trocando qual é a efetiva, e reativando a
    aposentada quando ela volta a ser a única."""
    esc, aluna, admin = cena["escola"], cena["aluna"], cena["admin"]
    _decidir(db, cena)
    assert _estados(db, esc, aluna)["conta-duplicada"] == "aposentada"

    # (a) trocar a escolha desfaz a decisão anterior por inteiro
    _decidir(db, cena, efetiva="conta-duplicada", aposentar=("conta-principal",),
             motivo="a escola corrigiu")
    assert _estados(db, esc, aluna) == {"conta-principal": "aposentada",
                                        "conta-duplicada": "efetiva"}

    # (b) sobrando uma só, a aposentada volta a valer pelo caminho explícito
    db.delete(next(i for i in efe.identidades_do_aluno(db, esc.id, aluna.id, "matific")
                   if i.id_externo == "conta-duplicada"))
    db.flush()
    efe.reativar(db, esc.id, aluno_id=aluna.id, plataforma="matific",
                 id_externo="conta-principal", motivo="a duplicada saiu do sistema",
                 usuario_id=admin.id)
    db.commit()
    assert _estados(db, esc, aluna) == {"conta-principal": "efetiva"}
    assert db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "identidade.reativada")).scalars().first() is not None


def test_reativar_exige_que_a_outra_seja_aposentada_antes(db, cena):
    _decidir(db, cena)
    with pytest.raises(efe.ErroIdentidade) as e:
        efe.reativar(db, cena["escola"].id, aluno_id=cena["aluna"].id,
                     plataforma="matific", id_externo="conta-duplicada",
                     motivo="quero as duas", usuario_id=cena["admin"].id)
    assert e.value.codigo == "duas_efetivas"

    # invertendo a decisão, a reativação passa e o estado fica coerente
    _decidir(db, cena, efetiva="conta-duplicada", aposentar=("conta-principal",),
             motivo="a escola corrigiu a escolha")
    assert _estados(db, cena["escola"], cena["aluna"]) == {
        "conta-principal": "aposentada", "conta-duplicada": "efetiva"}


# --- 2. validações que impedem estrago --------------------------------------

def test_nunca_deixa_duas_efetivas(db, cena):
    with pytest.raises(efe.ErroIdentidade) as e:
        efe.definir_efetiva(db, cena["escola"].id, aluno_id=cena["aluna"].id,
                            plataforma="matific", id_externo_efetivo="conta-principal",
                            aposentar=[], motivo="só quero marcar a principal",
                            usuario_id=cena["admin"].id)
    assert e.value.codigo == "duas_efetivas"
    assert "conta-duplicada" in str(e.value)


def test_nao_aposenta_conta_de_outro_aluno(db, cena):
    with pytest.raises(efe.ErroIdentidade) as e:
        efe.definir_efetiva(db, cena["escola"].id, aluno_id=cena["aluna"].id,
                            plataforma="matific", id_externo_efetivo="conta-principal",
                            aposentar=["conta-duplicada", "conta-colega"],
                            motivo="limpeza", usuario_id=cena["admin"].id)
    assert e.value.codigo == "identidade_de_outro_aluno"
    assert str(cena["colega"].id) in str(e.value)
    db.rollback()
    # a colega ficou intacta
    assert [i.status for i in efe.identidades_do_aluno(
        db, cena["escola"].id, cena["colega"].id, "matific")] == ["efetiva"]


def test_identidade_inexistente_e_erro(db, cena):
    with pytest.raises(efe.ErroIdentidade) as e:
        efe.definir_efetiva(db, cena["escola"].id, aluno_id=cena["aluna"].id,
                            plataforma="matific", id_externo_efetivo="nao-existe",
                            aposentar=["conta-duplicada"], motivo="x y z",
                            usuario_id=cena["admin"].id)
    assert e.value.codigo == "identidade_inexistente"


def test_plataforma_errada_e_erro(db, cena):
    with pytest.raises(efe.ErroIdentidade) as e:
        efe.definir_efetiva(db, cena["escola"].id, aluno_id=cena["aluna"].id,
                            plataforma="elefante", id_externo_efetivo="conta-principal",
                            aposentar=["conta-duplicada"], motivo="x y z",
                            usuario_id=cena["admin"].id)
    assert e.value.codigo == "identidade_inexistente"


def test_aluno_de_outra_escola_e_erro(db, cena, escola_completa):
    with pytest.raises(efe.ErroIdentidade) as e:
        efe.definir_efetiva(db, cena["escola"].id + 999, aluno_id=cena["aluna"].id,
                            plataforma="matific", id_externo_efetivo="conta-principal",
                            aposentar=["conta-duplicada"], motivo="x y z",
                            usuario_id=cena["admin"].id)
    assert e.value.codigo == "aluno_de_outra_escola"


def test_motivo_e_obrigatorio(db, cena):
    with pytest.raises(efe.ErroIdentidade) as e:
        efe.definir_efetiva(db, cena["escola"].id, aluno_id=cena["aluna"].id,
                            plataforma="matific", id_externo_efetivo="conta-principal",
                            aposentar=["conta-duplicada"], motivo="   ",
                            usuario_id=cena["admin"].id)
    assert e.value.codigo == "motivo_obrigatorio"


def test_nao_aposenta_a_propria_efetiva(db, cena):
    with pytest.raises(efe.ErroIdentidade) as e:
        efe.definir_efetiva(db, cena["escola"].id, aluno_id=cena["aluna"].id,
                            plataforma="matific", id_externo_efetivo="conta-principal",
                            aposentar=["conta-principal"], motivo="x y z",
                            usuario_id=cena["admin"].id)
    assert e.value.codigo == "efetiva_e_aposentada"


# --- 3. auditoria -----------------------------------------------------------

def test_a_decisao_fica_auditada_com_estado_antes_e_depois(db, cena):
    _decidir(db, cena, motivo="conta de teste criada por engano")
    [log] = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "identidade.efetiva_definida")).scalars().all()
    d = log.detalhes
    assert log.usuario_id == cena["admin"].id and log.entidade_id == cena["aluna"].id
    assert d["plataforma"] == "matific"
    assert d["identidade_efetiva"] == "conta-principal"
    assert d["identidades_aposentadas"] == ["conta-duplicada"]
    assert d["estado_anterior"] == {"conta-principal": "efetiva",
                                    "conta-duplicada": "efetiva"}
    assert d["estado_posterior"] == {"conta-principal": "efetiva",
                                     "conta-duplicada": "aposentada"}
    assert d["motivo"] == "conta de teste criada por engano"
    # A distinção que não pode se perder: isto NÃO desativou nada na plataforma.
    assert d["escopo"] == "decisao_interna_constela"
    assert "continua existindo na plataforma" in d["observacao"]


# --- 4. importação ----------------------------------------------------------

def test_so_a_efetiva_alimenta_o_retrato(db, cena):
    _decidir(db, cena)
    r = _importar(db, cena["escola"], cena["admin"], [
        _linha("ALLYCE CRISTINA BARBOSA DE ALMEIDA", cena["turma"], "conta-principal", 139, 523),
        _linha("ALLYCE CRISTINA BARBOSA DE ALMEIDA", cena["turma"], "conta-duplicada", 3, 9)])

    [s] = _snaps(db, cena["aluna"].id)
    assert (s.atividades, s.estrelas) == (139, 523)      # a EFETIVA venceu
    assert r.qtd_alunos == 1
    assert any("APOSENTADA" in a for a in r.avisos)


def test_a_aposentada_sozinha_nao_grava_nada_nem_reabre_a_fila(db, cena):
    """Sincronização após sincronização, a conta aposentada continua chegando —
    e não pode virar dado nem pendência nova a cada rodada."""
    _decidir(db, cena)
    for _ in range(3):
        r = _importar(db, cena["escola"], cena["admin"], [
            _linha("ALLYCE CRISTINA BARBOSA DE ALMEIDA", cena["turma"],
                   "conta-duplicada", 3, 9)])
        assert r.qtd_alunos == 0
    assert _snaps(db, cena["aluna"].id) == []
    assert db.scalar(select(func.count()).select_from(RevisaoIdentidade)) == 0


def test_a_ordem_das_linhas_nao_muda_o_resultado(db, cena):
    """Era exatamente isto que o `linhas_aluno[-1]` quebrava."""
    _decidir(db, cena)
    _importar(db, cena["escola"], cena["admin"], [
        _linha("ALLYCE CRISTINA BARBOSA DE ALMEIDA", cena["turma"], "conta-duplicada", 3, 9),
        _linha("ALLYCE CRISTINA BARBOSA DE ALMEIDA", cena["turma"], "conta-principal", 139, 523)])
    [s] = _snaps(db, cena["aluna"].id)
    assert (s.atividades, s.estrelas) == (139, 523)


def test_a_colega_de_uma_conta_so_segue_normal(db, cena):
    _decidir(db, cena)
    _importar(db, cena["escola"], cena["admin"],
              [_linha("BEATRIZ SOUZA LIMA", cena["turma"], "conta-colega", 11, 44)])
    [s] = _snaps(db, cena["colega"].id)
    assert (s.atividades, s.estrelas) == (11, 44)


def test_terceira_conta_nova_nao_e_aceita_sozinha(db, cena):
    """Aposentar uma não abre a porta para a próxima entrar sem decisão."""
    _decidir(db, cena)
    _importar(db, cena["escola"], cena["admin"], [
        _linha("ALLYCE CRISTINA BARBOSA DE ALMEIDA", cena["turma"], "conta-nova", 50, 200)])
    pend = db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.status == "pendente")).scalars().all()
    assert [p.motivo for p in pend] == ["outra_identidade_na_plataforma"]
    assert _snaps(db, cena["aluna"].id) == []


# --- 5. collision guard -----------------------------------------------------

def test_com_a_duplicada_aposentada_a_efetiva_deixa_de_ser_colisao(db, cena):
    ctx = ida.carregar_contexto(db, cena["escola"].id, ANO)
    linha = ida.linha_de_dados("ALLYCE", {"matific_uuid": "conta-principal"},
                               plataforma="matific", turma_nome=cena["turma"])
    assert ida.decidir(ctx, linha).acao == ida.REVISAR      # antes: colisão

    _decidir(db, cena)
    ctx = ida.carregar_contexto(db, cena["escola"].id, ANO)
    d = ida.decidir(ctx, linha)
    assert d.acao == ida.ASSOCIAR and d.aluno_id == cena["aluna"].id


def test_a_aposentada_e_ignorada_e_nunca_reassociada(db, cena):
    _decidir(db, cena)
    ctx = ida.carregar_contexto(db, cena["escola"].id, ANO)
    linha = ida.linha_de_dados("ALLYCE", {"matific_uuid": "conta-duplicada"},
                               plataforma="matific", turma_nome=cena["turma"])
    d = ida.decidir(ctx, linha)
    assert d.acao == ida.IGNORAR and d.motivo == "identidade_aposentada"
    assert d.aluno_id == cena["aluna"].id     # sabe de quem era, mas não associa


def test_duas_efetivas_continuam_bloqueadas(db, cena):
    """Sem decisão, nada muda: o guard de colisão segue valendo."""
    ctx = ida.carregar_contexto(db, cena["escola"].id, ANO)
    for uuid in ("conta-principal", "conta-duplicada"):
        linha = ida.linha_de_dados("ALLYCE", {"matific_uuid": uuid},
                                   plataforma="matific", turma_nome=cena["turma"])
        d = ida.decidir(ctx, linha)
        assert d.acao == ida.REVISAR
        assert d.motivo == "outra_identidade_na_plataforma"


def test_identidade_de_outro_aluno_continua_bloqueada(db, cena):
    _decidir(db, cena)
    ctx = ida.carregar_contexto(db, cena["escola"].id, ANO)
    linha = ida.linha_de_dados("ALLYCE CRISTINA BARBOSA DE ALMEIDA",
                               {"matific_uuid": "conta-colega"},
                               plataforma="matific", turma_nome=cena["turma"])
    d = ida.decidir(ctx, linha)
    assert d.acao == ida.ASSOCIAR and d.aluno_id == cena["colega"].id


# --- 6. fila de revisão -----------------------------------------------------

def test_a_pendencia_da_aposentada_e_encerrada_pela_decisao(db, cena):
    esc = cena["escola"]
    _importar(db, esc, cena["admin"], [
        _linha("ALLYCE CRISTINA BARBOSA DE ALMEIDA", cena["turma"], "conta-principal", 139, 523),
        _linha("ALLYCE CRISTINA BARBOSA DE ALMEIDA", cena["turma"], "conta-duplicada", 3, 9)])
    pend = {p.id_externo: p for p in db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.status == "pendente")).scalars()}
    assert set(pend) == {"conta-principal", "conta-duplicada"}

    r = _decidir(db, cena)
    assert r.revisoes_encerradas == (pend["conta-duplicada"].id,)
    db.expire_all()
    # a da aposentada foi DESCARTADA (não resolvida: resolver associaria os dados)
    assert db.get(RevisaoIdentidade, pend["conta-duplicada"].id).status == "descartada"
    # a da efetiva segue aberta e agora é encerrável
    assert db.get(RevisaoIdentidade, pend["conta-principal"].id).status == "pendente"
    v = tri.triar_escola(db, esc.id)[pend["conta-principal"].id]
    assert v.classificacao == tri.SEGURA and v.aluno_id == cena["aluna"].id


def test_triagem_reconhece_a_pendencia_de_conta_aposentada(db, cena):
    esc = cena["escola"]
    _importar(db, esc, cena["admin"], [
        _linha("ALLYCE CRISTINA BARBOSA DE ALMEIDA", cena["turma"], "conta-duplicada", 3, 9)])
    [pend] = db.execute(select(RevisaoIdentidade)).scalars().all()
    # decide SEM encerrar a pendência (simula uma que reabriu depois)
    efe.definir_efetiva(db, esc.id, aluno_id=cena["aluna"].id, plataforma="matific",
                        id_externo_efetivo="conta-principal",
                        aposentar=["conta-duplicada"], motivo="decisão da escola",
                        usuario_id=cena["admin"].id)
    pend.status = "pendente"
    pend.resolvida_em = None
    db.commit()

    v = tri.triar_escola(db, esc.id)[pend.id]
    assert v.classificacao == tri.DECISAO_HUMANA
    assert v.motivo == tri.IDENTIDADE_APOSENTADA
    assert any("aposentada" in c for c in v.conflitos)


def test_resolver_uma_pendencia_de_conta_aposentada_e_recusado(db, cena, cliente,
                                                               escola_completa):
    esc = cena["escola"]
    _importar(db, esc, cena["admin"], [
        _linha("ALLYCE CRISTINA BARBOSA DE ALMEIDA", cena["turma"], "conta-duplicada", 3, 9)])
    [pend] = db.execute(select(RevisaoIdentidade)).scalars().all()
    efe.definir_efetiva(db, esc.id, aluno_id=cena["aluna"].id, plataforma="matific",
                        id_externo_efetivo="conta-principal",
                        aposentar=["conta-duplicada"], motivo="decisão da escola",
                        usuario_id=cena["admin"].id)
    pend.status = "pendente"
    pend.resolvida_em = None
    db.commit()

    r = cliente.post(f"/api/v1/escolas/{esc.id}/importacoes/revisoes/{pend.id}/resolver",
                     json={"aluno_id": cena["aluna"].id})
    assert r.status_code == 409, r.text
    assert "aposentada" in r.json()["detail"]


# --- 7. scoring e histórico -------------------------------------------------

def test_nada_do_historico_e_apagado_pela_decisao(db, cena):
    esc = cena["escola"]
    _importar(db, esc, cena["admin"], [
        _linha("ALLYCE CRISTINA BARBOSA DE ALMEIDA", cena["turma"], "conta-principal", 139, 523)])
    snaps_antes = [(s.id, s.atividades, s.estrelas) for s in _snaps(db, cena["aluna"].id)]
    ident_antes = db.scalar(select(func.count()).select_from(IdentidadeExterna))

    _decidir(db, cena)
    db.expire_all()

    assert [(s.id, s.atividades, s.estrelas) for s in _snaps(db, cena["aluna"].id)] == snaps_antes
    assert db.scalar(select(func.count()).select_from(IdentidadeExterna)) == ident_antes


def test_a_decisao_sozinha_nao_mexe_na_nota(db, cena):
    """Definir a identidade efetiva é decisão de identidade, não de pontuação:
    quem muda nota é a importação seguinte, pelo caminho normal."""
    from app.models import Nota
    esc = cena["escola"]
    _importar(db, esc, cena["admin"], [
        _linha("ALLYCE CRISTINA BARBOSA DE ALMEIDA", cena["turma"], "conta-principal", 139, 523)],
        recalcular=True)
    db.expire_all()
    antes = {n.aluno_id: (n.nota_matific, n.nota_geral, n.posicao_matematica)
             for n in db.execute(select(Nota).where(Nota.ano_letivo == ANO)).scalars()}

    _decidir(db, cena)
    db.expire_all()
    depois = {n.aluno_id: (n.nota_matific, n.nota_geral, n.posicao_matematica)
              for n in db.execute(select(Nota).where(Nota.ano_letivo == ANO)).scalars()}
    assert antes == depois


# --- 8. a rota --------------------------------------------------------------

def test_rota_define_a_efetiva_e_lista_o_estado(db, cena, cliente):
    esc, aluna = cena["escola"], cena["aluna"]
    base = f"/api/v1/escolas/{esc.id}/importacoes/identidades/matific"

    r = cliente.post(f"{base}/efetiva", json={
        "aluno_id": aluna.id, "id_externo_efetivo": "conta-principal",
        "aposentar": ["conta-duplicada"], "motivo": "a escola confirmou o uso"})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["identidade_efetiva"] == "conta-principal"
    assert corpo["identidades_aposentadas"] == ["conta-duplicada"]
    assert "continua existindo na plataforma externa" in corpo["observacao"]

    lista = cliente.get(f"{base}/aluno/{aluna.id}")
    assert lista.status_code == 200
    por_conta = {x["id_externo"]: x for x in lista.json()}
    assert por_conta["conta-principal"]["status"] == "efetiva"
    assert por_conta["conta-duplicada"]["status"] == "aposentada"
    assert por_conta["conta-duplicada"]["motivo_aposentadoria"] == "a escola confirmou o uso"
    assert por_conta["conta-duplicada"]["aposentada_por"] == "Admin"


def test_rota_recusa_deixar_duas_efetivas(db, cena, cliente):
    esc, aluna = cena["escola"], cena["aluna"]
    r = cliente.post(
        f"/api/v1/escolas/{esc.id}/importacoes/identidades/matific/efetiva",
        json={"aluno_id": aluna.id, "id_externo_efetivo": "conta-principal",
              "aposentar": [], "motivo": "só marcar a principal"})
    assert r.status_code == 400
    assert "duas contas efetivas" in r.json()["detail"]
    db.expire_all()
    assert _estados(db, esc, aluna) == {"conta-principal": "efetiva",
                                        "conta-duplicada": "efetiva"}
