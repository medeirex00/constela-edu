"""Escola externa: decisões do dono implementadas (A2 da sincronização).

  D8  (risco A2, LGPD) sem vínculo da escola externa, a coleta em que TODAS as
      contas identificadas já são a identidade efetiva de alunos de OUTRA escola
      do Constela é recusada ANTES de aplicar qualquer linha: 'erro'
      ``contas_de_outra_escola``, nada gravado (nem ficha, nem retrato, nem a
      revisão com o nome da criança de lá, nem o vínculo) e auditoria. A coleta
      mista continua aplicando só as contas desta escola.
  D9  (risco A3) sem vínculo, o nome da escola na plataforma divergente do
      cadastrado (comparação normalizada, com tolerância) impede só o
      APRENDIZADO automático do vínculo: a coleta segue. Com o vínculo gravado
      pelo Admin Global, o nome divergente é só aviso.
  D10 (risco V) confirmar no ``/resolver`` uma conta que já é a identidade
      efetiva de um aluno de OUTRA escola exige o Admin Global (403 para a gestão
      da escola) e registra auditoria própria, com aviso do efeito na outra.

Conectores reais com navegador falso; dados 100% fictícios; sem rede. Regras em
``app/sync/escola_externa.py`` e docs/SINCRONIZACAO.md ("Escola externa").
"""
import pytest
from sqlalchemy import select

from app.models import Aluno, IdentidadeExterna
from app.models.academico import RevisaoIdentidade
from app.models.nota import LogAuditoria
from app.models.plataformas import SnapshotElefante, SnapshotMatific
from app.sync import escola_externa
from tests._sync_nucleo_fakes import (
    API, SCHOOL_UUID, alertas_abertos, contagens, credencial, logs, rodar, snap_atual,
    vincular)
from tests.test_sync_escola_cruzada import (
    CID_A, CID_B, ESC_A, ESC_B, NOME_B, NavEl, NavMt, _alerta, _da_escola, _nova_escola,
    _placar, _turmas, instalar_navs)


def _auditoria(db, acao):
    return db.execute(select(LogAuditoria).where(LogAuditoria.acao == acao)).scalars().all()


def _revisoes(db, eid):
    return db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == eid)).scalars().all()


# ===========================================================================
# D8 — coleta só de contas de outra escola: recusada antes de aplicar
# ===========================================================================
def _elefante_da_escola_1_sem_vinculo(db, escola_completa, monkeypatch):
    """Escola 1 sincronizou (contas 7001 e 7002 efetivas nela) e está no estado de
    antes da implantação (sem vínculo). Devolve (e1, nav)."""
    e1 = escola_completa["escola"].id
    credencial(db, e1, "elefante")
    turmas = _turmas(escola_completa)
    del turmas[CID_B]
    nav = NavEl(turmas, escola_da_turma={CID_A: ESC_A})
    instalar_navs(monkeypatch, elefante=nav)
    ex0, _ = rodar(db, e1, "elefante")
    assert ex0.status == "concluida", (ex0.status, ex0.motivo)
    escola_externa.remover(db, e1, "elefante")
    db.commit()
    return e1, nav


def test_d8_elefante_credencial_de_outra_escola_sem_vinculo_nao_grava_nada(
        db, escola_completa, monkeypatch):
    """A escola 2 cadastrou, por engano, a conta da escola 1: TODAS as contas da
    coleta já são de alunos da escola 1. Antes: os nomes e números das crianças
    da escola 1 entravam na fila de Revisões da escola 2 (sonda A2 do e95)."""
    e1, _nav = _elefante_da_escola_1_sem_vinculo(db, escola_completa, monkeypatch)
    nomes_e1 = {a.nome for a in escola_completa["alunos"]}
    escola2, _t, _a = _nova_escola(db, com_alunos=["Criança Ficticia Da Segunda Escola"])
    e2 = escola2.id
    credencial(db, e2, "elefante")
    antes1, antes2 = contagens(db, e1), contagens(db, e2)
    ex2, erro = rodar(db, e2, "elefante")
    assert erro is None
    assert (ex2.status, ex2.motivo) == ("erro", "contas_de_outra_escola"), ex2.erro_resumo
    assert ex2.qtd_alunos == 0 and ex2.qtd_em_revisao == 0
    # Nada gravado na escola 2: nem ficha, nem retrato, nem revisão com nome.
    assert _da_escola(contagens(db, e2)) == _da_escola(antes2)
    assert not any(r.nome_recebido in nomes_e1 for r in _revisoes(db, e2))
    assert escola_externa.obter(db, e2, "elefante") is None          # não aprende
    # Status/motivo honesto e alerta crítico próprio; sem nova tentativa.
    assert "Todas as 2 conta(s)" in ex2.erro_resumo
    alerta = _alerta(db, e2, "contas_de_outra_escola")
    assert alerta is not None and alerta.severidade == "critico"
    assert "identidade_de_outra_escola" not in alertas_abertos(db, e2, "elefante")
    # Auditoria: contagem e, só ali, a outra escola (a mensagem não a revela).
    aud = _auditoria(db, "sync.contas_de_outra_escola_recusada")
    assert len(aud) == 1 and aud[0].escola_id == e2
    assert aud[0].detalhes["contas"] == 2 and aud[0].detalhes["outras_escolas"] == [e1]
    assert all(a.escola_id != e2 for a in _auditoria(db, "sync.escola_externa_aprendida"))
    # A escola 1 não foi tocada e continua sincronizando (aprende o vínculo).
    assert _da_escola(contagens(db, e1)) == _da_escola(antes1)
    ex1, _ = rodar(db, e1, "elefante")
    assert ex1.status in ("concluida", "sem_atualizacao"), (ex1.status, ex1.motivo)
    assert escola_externa.obter(db, e1, "elefante")["id"] == str(ESC_A)


def test_d8_matific_credencial_de_outra_escola_sem_vinculo_nao_grava_nada(
        db, escola_completa, monkeypatch):
    e1 = escola_completa["escola"].id
    credencial(db, e1, "matific")
    instalar_navs(monkeypatch, matific=NavMt(_placar(escola_completa)))
    assert rodar(db, e1, "matific")[0].status == "concluida"          # u-a, u-b, u-c
    escola_externa.remover(db, e1, "matific")
    db.commit()
    escola2, _t, _a = _nova_escola(db, com_alunos=[a.nome for a in escola_completa["alunos"]])
    e2 = escola2.id
    credencial(db, e2, "matific")
    antes2 = contagens(db, e2)
    ex2, erro = rodar(db, e2, "matific")
    assert erro is None
    assert (ex2.status, ex2.motivo) == ("erro", "contas_de_outra_escola"), ex2.erro_resumo
    assert _da_escola(contagens(db, e2)) == _da_escola(antes2)       # nem revisão, nem retrato
    assert escola_externa.obter(db, e2, "matific") is None
    assert len(_auditoria(db, "sync.contas_de_outra_escola_recusada")) == 1
    ex1, _ = rodar(db, e1, "matific")
    assert ex1.status in ("concluida", "sem_atualizacao"), (ex1.status, ex1.motivo)
    assert escola_externa.obter(db, e1, "matific")["id"] == SCHOOL_UUID


def test_d8_coleta_mista_com_conta_desta_escola_aplica_so_as_da_escola(
        db, escola_completa, monkeypatch):
    """Controle: UMA conta já desta escola basta para a coleta seguir. A conta da
    escola é aplicada; as de outra escola vão para a revisão própria, sem tocar
    na outra escola."""
    eid = escola_completa["escola"].id
    a, b, c = escola_completa["alunos"]
    outra, _t, donas = _nova_escola(db, nome="ESCOLA PRIMEIRA FICTICIA", com_alunos=[
        "Crianca Ficticia Primeira Um", "Crianca Ficticia Primeira Tres"])
    vincular(db, outra.id, donas[0].id, "matific", "u-a")
    vincular(db, outra.id, donas[1].id, "matific", "u-c")
    vincular(db, eid, b.id, "matific", "u-b")                         # a conta daqui
    db.commit()
    antes_outra = contagens(db, outra.id)
    credencial(db, eid, "matific")
    instalar_navs(monkeypatch, matific=NavMt(_placar(escola_completa)))
    ex, erro = rodar(db, eid, "matific")
    assert erro is None
    assert ex.status == "concluida", (ex.status, ex.motivo, ex.erro_resumo)
    assert ex.qtd_alunos == 1 and ex.qtd_em_revisao == 2
    assert snap_atual(db, SnapshotMatific, b.id) is not None
    assert snap_atual(db, SnapshotMatific, a.id) is None
    assert snap_atual(db, SnapshotMatific, c.id) is None
    assert sorted((r.motivo, r.id_externo) for r in _revisoes(db, eid)) == [
        ("identidade_de_outra_escola", "u-a"), ("identidade_de_outra_escola", "u-c")]
    assert _da_escola(contagens(db, outra.id)) == _da_escola(antes_outra)
    assert _auditoria(db, "sync.contas_de_outra_escola_recusada") == []


def test_d8_coleta_mista_com_conta_desconhecida_segue(db, escola_completa, monkeypatch):
    """Controle: uma conta ainda desconhecida no Constela (escola nova, criança
    nova) também basta — a escola que recebeu uma criança transferida de outra
    escola do Constela não fica parada na 1ª coleta."""
    eid = escola_completa["escola"].id
    a, b, _c = escola_completa["alunos"]
    outra, _t, (dona,) = _nova_escola(db, nome="ESCOLA PRIMEIRA FICTICIA",
                                      com_alunos=["Aluna Da Primeira Escola Ficticia"])
    vincular(db, outra.id, dona.id, "elefante", "7001")
    db.commit()
    credencial(db, eid, "elefante")
    turmas = _turmas(escola_completa)
    del turmas[CID_B]
    instalar_navs(monkeypatch, elefante=NavEl(turmas, escola_da_turma={CID_A: ESC_A}))
    ex, _ = rodar(db, eid, "elefante")
    assert ex.status == "concluida", (ex.status, ex.motivo, ex.erro_resumo)   # só a 7002
    assert snap_atual(db, SnapshotElefante, b.id) is not None
    assert snap_atual(db, SnapshotElefante, a.id) is None
    assert {r.motivo for r in _revisoes(db, eid)} == {"identidade_de_outra_escola"}


# Saída da criança pela API (o fluxo real): ação → status gravado na ficha.
_SAIDA_PELA_API = {"transferido_pela_api": ("marcar_transferido", "transferido"),
                   "arquivado_pela_api": ("arquivar", "arquivado")}


@pytest.mark.parametrize("nao_efetiva", ["aposentada", "ficha_excluida",
                                         "transferido_pela_api", "arquivado_pela_api",
                                         "fora_lista_piloto"])
def test_d8_identidade_nao_efetiva_aqui_nao_livra_da_recusa(db, escola_completa, monkeypatch,
                                                            nao_efetiva):
    """Revisão e97b (bloqueio): a escola 1 sincronizou u-a, u-b e u-c (efetivas
    nela) e está sem vínculo. A escola 2 tem UMA identidade de u-a que não é de
    uma criança que está na escola: aposentada (a conta duplicada que a escola
    descartou) ou presa a uma ficha excluída. Antes, essa linha bastava para a
    coleta da escola 2 com a credencial da 1 seguir como 'mista' e gravar 2 ou 3
    revisões com os nomes e números das crianças da escola 1. Agora: todas as
    contas são efetivas em outra escola (regra única) → recusada, nada gravado.

    Revisão de integração do e97 (prova dados-sync 1 e 3, invertidas): o mesmo
    com a ficha INATIVA nesta escola — a criança que saiu da 2 para a 1, pelo
    fluxo real ("Marcar como transferido" ou "Arquivar" em /alunos/acoes, que
    não aposentam a conta) ou fora da Lista Piloto. Antes, a conta dela contava
    como "efetiva aqui" e a coleta gravava na fila da escola 2 as revisões
    ``identidade_de_outra_escola`` com os nomes das crianças da escola 1."""
    e1 = escola_completa["escola"].id
    credencial(db, e1, "matific")
    instalar_navs(monkeypatch, matific=NavMt(_placar(escola_completa)))
    assert rodar(db, e1, "matific")[0].status == "concluida"          # u-a, u-b, u-c
    escola_externa.remover(db, e1, "matific")
    db.commit()
    escola2, _t, (antiga, _outra) = _nova_escola(db, com_alunos=[
        "Crianca Ficticia Que Saiu", "Crianca Ficticia Da Segunda"])
    e2 = escola2.id
    velha = IdentidadeExterna(escola_id=e2, aluno_id=antiga.id, plataforma="matific",
                              id_externo="u-a")
    if nao_efetiva == "aposentada":
        velha.status = "aposentada"
    elif nao_efetiva == "ficha_excluida":
        db.get(Aluno, antiga.id).status = "excluido"
    elif nao_efetiva == "fora_lista_piloto":
        db.get(Aluno, antiga.id).status = "fora_lista_piloto"
    db.add(velha)
    db.commit()
    if nao_efetiva in _SAIDA_PELA_API:
        acao, status_ficha = _SAIDA_PELA_API[nao_efetiva]
        r = _cliente_de(f"admin{e2}@teste.local").post(
            f"{API}/escolas/{e2}/alunos/acoes", json={"aluno_ids": [antiga.id], "acao": acao})
        assert r.status_code == 200, r.text
        db.expire_all()
        assert db.get(Aluno, antiga.id).status == status_ficha
        # A saída NÃO aposenta a conta: continua efetiva, presa à ficha inativa.
        assert db.execute(select(IdentidadeExterna.status).where(
            IdentidadeExterna.escola_id == e2,
            IdentidadeExterna.id_externo == "u-a")).scalar_one() == "efetiva"
    credencial(db, e2, "matific")
    antes1, antes2 = contagens(db, e1), contagens(db, e2)
    ex2, erro = rodar(db, e2, "matific")
    assert erro is None
    assert (ex2.status, ex2.motivo) == ("erro", "contas_de_outra_escola"), (
        ex2.status, ex2.motivo, ex2.erro_resumo)
    assert ex2.qtd_alunos == 0 and ex2.qtd_em_revisao == 0
    assert "Todas as 3 conta(s)" in ex2.erro_resumo
    # Nada gravado na escola 2: nem revisão com nome, nem retrato, nem identidade
    # nova (só a antiga, não efetiva, continua lá), nem o vínculo.
    assert _da_escola(contagens(db, e2)) == _da_escola(antes2)
    assert _revisoes(db, e2) == []
    assert db.execute(select(IdentidadeExterna.id_externo).where(
        IdentidadeExterna.escola_id == e2)).scalars().all() == ["u-a"]
    assert escola_externa.obter(db, e2, "matific") is None
    aud = _auditoria(db, "sync.contas_de_outra_escola_recusada")
    assert len(aud) == 1 and aud[0].escola_id == e2
    assert aud[0].detalhes["contas"] == 3 and aud[0].detalhes["outras_escolas"] == [e1]
    # A escola 1 não foi tocada.
    assert _da_escola(contagens(db, e1)) == _da_escola(antes1)


def test_d8_ficha_inativa_aqui_com_conta_de_crianca_ativa_daqui_segue_mista(
        db, escola_completa, monkeypatch):
    """Controle do filtro de ficha inativa (prova dados-sync 5c): a escola 2 tem a
    criança que saiu (ficha transferida, conta u-a) e uma criança ATIVA com a
    conta u-b. A conta da criança ativa basta: a coleta segue como mista."""
    e1 = escola_completa["escola"].id
    credencial(db, e1, "matific")
    instalar_navs(monkeypatch, matific=NavMt(_placar(escola_completa)))
    assert rodar(db, e1, "matific")[0].status == "concluida"          # u-a, u-b, u-c
    escola_externa.remover(db, e1, "matific")
    db.commit()
    escola2, _t, (saiu, fica) = _nova_escola(db, com_alunos=[
        "Crianca Ficticia Que Saiu", "Crianca Ficticia Da Segunda"])
    e2 = escola2.id
    vincular(db, e2, saiu.id, "matific", "u-a")
    vincular(db, e2, fica.id, "matific", "u-b")
    db.get(Aluno, saiu.id).status = "transferido"
    db.commit()
    credencial(db, e2, "matific")
    ex2, erro = rodar(db, e2, "matific")
    assert erro is None
    assert (ex2.status, ex2.motivo) != ("erro", "contas_de_outra_escola"), (
        ex2.status, ex2.motivo, ex2.erro_resumo)
    assert _auditoria(db, "sync.contas_de_outra_escola_recusada") == []


@pytest.mark.parametrize("status_inativo", ["transferido", "arquivado", "fora_lista_piloto"])
def test_d8_regra_de_efetiva_aqui_e_a_mesma_de_outra_escola(db, escola_completa,
                                                           status_inativo):
    """A identidade aposentada ou de ficha excluída não conta de nenhum dos lados.
    A de ficha INATIVA (transferida, arquivada, fora da Lista Piloto) é a única
    diferença entre os dois lados, e é de propósito: não conta como "desta
    escola" (``efetivas_na_escola``, o lado do D8: a criança saiu daqui), mas
    continua contando vista da OUTRA escola (``efetivas_em_outra_escola``, a
    regra única do D10 e da revisão ``identidade_de_outra_escola``)."""
    from app.services.identidade_aluno import efetivas_em_outra_escola, efetivas_na_escola

    eid = escola_completa["escola"].id
    a, b, c = escola_completa["alunos"]
    outra, _t, (d, saiu) = _nova_escola(db, com_alunos=[
        "Crianca Ficticia Da Segunda", "Crianca Ficticia Que Saiu Da Segunda"])
    vincular(db, eid, a.id, "matific", "u-a")
    vincular(db, eid, b.id, "matific", "u-b")
    vincular(db, eid, c.id, "matific", "u-c")
    vincular(db, outra.id, d.id, "matific", "u-c")
    vincular(db, outra.id, saiu.id, "matific", "u-t")
    db.commit()
    db.execute(IdentidadeExterna.__table__.update().where(
        IdentidadeExterna.escola_id == eid, IdentidadeExterna.id_externo == "u-a")
        .values(status="aposentada"))
    db.get(Aluno, b.id).status = "excluido"
    db.get(Aluno, saiu.id).status = status_inativo
    db.commit()
    ids = {"u-a", "u-b", "u-c", "u-t", "u-nova"}
    assert efetivas_na_escola(db, eid, "matific", ids) == {"u-c"}
    assert efetivas_na_escola(db, eid, "elefante", ids) == set()
    # Lado "desta escola": a ficha inativa da outra escola não conta lá.
    assert efetivas_na_escola(db, outra.id, "matific", ids) == {"u-c"}
    assert efetivas_em_outra_escola(db, outra.id, "matific", ids) == {"u-c": eid}
    # Lado "de outra escola": vista daqui, a mesma ficha inativa continua contando.
    assert efetivas_em_outra_escola(db, eid, "matific", ids) == {"u-c": outra.id,
                                                                 "u-t": outra.id}


def test_d8_com_vinculo_gravado_nao_recusa(db, escola_completa, monkeypatch):
    """Com o vínculo gravado (o Admin Global conferiu a escola externa), a regra
    não se aplica: as contas de outra escola vão para a revisão própria (criança
    que mudou de escola, escola desmembrada) — é a saída do caso legítimo."""
    eid = escola_completa["escola"].id
    outra, _t, donas = _nova_escola(db, nome="ESCOLA PRIMEIRA FICTICIA", com_alunos=[
        "Crianca Ficticia Primeira Um", "Crianca Ficticia Primeira Dois",
        "Crianca Ficticia Primeira Tres"])
    for dona, u in zip(donas, ("u-a", "u-b", "u-c")):
        vincular(db, outra.id, dona.id, "matific", u)
    escola_externa.salvar(db, eid, "matific", SCHOOL_UUID, origem="explicito")
    db.commit()
    credencial(db, eid, "matific")
    instalar_navs(monkeypatch, matific=NavMt(_placar(escola_completa)))
    ex, _ = rodar(db, eid, "matific")
    assert (ex.status, ex.motivo) == ("sem_atualizacao", "tudo_em_revisao")
    assert ex.qtd_em_revisao == 3
    assert "identidade_de_outra_escola" in alertas_abertos(db, eid, "matific")
    assert _auditoria(db, "sync.contas_de_outra_escola_recusada") == []


def test_d8_nenhuma_identidade_criada_e_codigo_cabe_nas_colunas(db, escola_completa,
                                                                 monkeypatch):
    """O código novo cabe em ``sincronizacao_alertas.tipo`` (String(30)) e em
    ``execucoes.motivo`` (String(40)); e a recusa não deixa identidade nenhuma
    na escola 2 (a conta continua só na escola 1)."""
    from app.sync import service

    tipo, sev = service.alerta_do_codigo("contas_de_outra_escola")
    assert (tipo, sev) == ("contas_de_outra_escola", "critico")
    assert len(tipo) <= 30
    assert service.CATEGORIA_POR_TIPO["contas_de_outra_escola"] == "autenticacao"
    e1, _nav = _elefante_da_escola_1_sem_vinculo(db, escola_completa, monkeypatch)
    escola2, _t, _a = _nova_escola(db)
    credencial(db, escola2.id, "elefante")
    rodar(db, escola2.id, "elefante")
    assert db.execute(select(IdentidadeExterna).where(
        IdentidadeExterna.escola_id == escola2.id)).first() is None
    assert len(db.execute(select(IdentidadeExterna).where(
        IdentidadeExterna.escola_id == e1)).all()) == 2


# ===========================================================================
# D9 — nome divergente bloqueia só o APRENDIZADO automático do vínculo
# ===========================================================================
def test_d9_criterio_de_nome_normalizado_com_tolerancia():
    """Critério documentado (docs/SINCRONIZACAO.md): sem acento/caixa/pontuação,
    sem tipo, preposição, título e iniciais; palavras do nome mais curto no outro
    (todas, ou 2/3 e no mínimo duas), com UMA letra de tolerância em palavras de
    5+ letras."""
    casa = escola_externa.nomes_compativeis
    # Nomes de escola inventados (sem escola real), com as mesmas variações.
    assert casa("EMEI/EMEF BALTHAZAR LIMOEIRO DO ROSÁRIO", "emef baltazar limoeiro do rosario")
    assert casa("EMEF Prof. Teodoro Passarela", "Escola Municipal Professor Teodoro Pasarela")
    assert casa("E.M.E.F. VER. HONÓRIO QUIRINO", "Escola Municipal Vereador Honorio Quirino")
    assert casa("EMEF Mª Belarmina Ficticia Souto", "EMEF Maria Belarmina Ficticia Souto")
    assert casa("EMEF TEODORO PASSARELA - VILA FICTÍCIA", "EMEF Teodoro Passarela")
    assert not casa("EMEF MARIA DAS DORES", "EMEF MARIA JOSE")       # só "Maria"
    assert not casa("EMEF TEODORO PASSARELA", "EMEF TEODORO ALVORADA")
    assert not casa("EMEF OUTRA UNIDADE FICTICIA", "ESCOLA SEGUNDA FICTICIA")
    assert not casa("EMEF ILA MORO", "EMEF ILE MORU")       # palavra curta: só igual
    assert casa("", "ESCOLA TESTE") and casa("ESCOLA MUNICIPAL", "ESCOLA TESTE")
    assert escola_externa.nomes_divergentes(
        ["", "EMEF ESCOLA TESTE", "EMEF OUTRA FICTICIA", "EMEF OUTRA FICTICIA"],
        "ESCOLA TESTE") == ["EMEF OUTRA FICTICIA"]


def _cenario_a3(db, escola_completa, monkeypatch, *, politica_da_errada):
    """A escola 1 ("ESCOLA TESTE") cadastrou a credencial da escola externa ESC_B
    ("EMEF OUTRA UNIDADE FICTICIA"), cuja escola dona no Constela ainda não tem
    histórico (a identidade não pega). Devolve (e1, ex1, dona, ex_dona)."""
    from app.services import politica_sync

    e1 = escola_completa["escola"].id
    politica_sync.definir(db, e1, politica_da_errada)
    db.commit()
    credencial(db, e1, "elefante")
    turmas = {CID_B: _turmas(escola_completa)[CID_B]}
    instalar_navs(monkeypatch, elefante=NavEl(turmas, ativas=((ESC_B, NOME_B),),
                                              escola_da_turma={CID_B: ESC_B}))
    ex1, erro = rodar(db, e1, "elefante")
    assert erro is None
    dona, _t, _a = _nova_escola(db, nome=NOME_B)
    credencial(db, dona.id, "elefante")
    ex_dona, erro = rodar(db, dona.id, "elefante")
    assert erro is None
    return e1, ex1, dona, ex_dona


def test_d9_nome_divergente_coleta_sem_aprender_e_a_dona_aprende(
        relogio_no_ano_letivo, db, escola_completa, monkeypatch):
    """Sonda A3 do e95. Antes: a escola 1 aprendia ESC_B e a dona, sem histórico,
    parava em 'erro/escola_externa_em_outra_escola'. Agora a 1 coleta sem gravar
    o vínculo (log + auditoria) e a dona aprende o dela e coleta."""
    e1, ex1, dona, ex_dona = _cenario_a3(db, escola_completa, monkeypatch,
                                         politica_da_errada="bloquear")
    # A coleta da escola 1 NÃO foi bloqueada pelo nome: só não aprendeu.
    assert ex1.status != "erro", (ex1.status, ex1.motivo, ex1.erro_resumo)
    assert escola_externa.obter(db, e1, "elefante") is None
    assert any("NÃO vinculada nesta coleta" in m and "não confere" in m
               for _e, _n, m in logs(db, ex1.id))
    aud = _auditoria(db, "sync.escola_externa_nao_aprendida")
    assert len(aud) == 1 and aud[0].escola_id == e1
    assert aud[0].detalhes["motivo"] == "nome_divergente"
    assert aud[0].detalhes["id_externo"] == str(ESC_B)
    # A dona não fica bloqueada: aprende e coleta.
    assert (ex_dona.status, ex_dona.motivo) != ("erro", "escola_externa_em_outra_escola")
    assert ex_dona.status == "concluida", (ex_dona.status, ex_dona.motivo, ex_dona.erro_resumo)
    assert escola_externa.obter(db, dona.id, "elefante")["id"] == str(ESC_B)


def test_d9_com_permitir_na_escola_errada_a_dona_cai_no_d8_e_nao_no_vinculo(
        relogio_no_ano_letivo, db, escola_completa, monkeypatch):
    """Interação documentada: com 'permitir' na escola errada, as crianças da dona
    viram fichas lá. A dona não para mais em 'escola_externa_em_outra_escola'
    (D9), mas a coleta dela é recusada pelo D8 (todas as contas já são de outra
    escola) até o Admin Global corrigir; nada é gravado na dona."""
    e1, _ex1, dona, ex_dona = _cenario_a3(db, escola_completa, monkeypatch,
                                          politica_da_errada="permitir")
    assert escola_externa.obter(db, e1, "elefante") is None
    assert (ex_dona.status, ex_dona.motivo) == ("erro", "contas_de_outra_escola")
    assert contagens(db, dona.id)["revisoes"] == 0


def test_d9_nome_compativel_continua_aprendendo(db, escola_completa, monkeypatch):
    """Controle: nome que confere pelo critério (variação de grafia e tipo)
    continua aprendendo o vínculo na 1ª coleta, sem aviso de nome."""
    eid = escola_completa["escola"].id
    credencial(db, eid, "elefante")
    turmas = _turmas(escola_completa)
    del turmas[CID_B]
    turmas[CID_A]["escola"] = "E.M.E.F. Escola Teste"
    instalar_navs(monkeypatch, elefante=NavEl(turmas, ativas=((ESC_A, "EMEF ESCOLA TESTE"),),
                                              escola_da_turma={CID_A: ESC_A}))
    ex, _ = rodar(db, eid, "elefante")
    assert ex.status == "concluida", (ex.status, ex.motivo, ex.erro_resumo)
    assert escola_externa.obter(db, eid, "elefante")["origem"] == "aprendido"
    assert not any("nome da escola" in m for _e, _n, m in logs(db, ex.id))
    assert _auditoria(db, "sync.escola_externa_nao_aprendida") == []


def test_d9_vinculo_explicito_com_nome_divergente_coleta_so_com_aviso(db, escola_completa,
                                                                      monkeypatch):
    """O vínculo gravado pelo Admin Global vale: o nome divergente não bloqueia a
    coleta nem troca o vínculo, só avisa."""
    eid = escola_completa["escola"].id
    credencial(db, eid, "elefante")
    turmas = _turmas(escola_completa)
    del turmas[CID_B]
    turmas[CID_A]["escola"] = "EMEF NOME TOTALMENTE DIFERENTE"
    instalar_navs(monkeypatch, elefante=NavEl(
        turmas, ativas=((ESC_A, "EMEF NOME TOTALMENTE DIFERENTE"),),
        escola_da_turma={CID_A: ESC_A}))
    escola_externa.salvar(db, eid, "elefante", str(ESC_A), origem="explicito")
    db.commit()
    ex, _ = rodar(db, eid, "elefante")
    assert ex.status == "concluida", (ex.status, ex.motivo, ex.erro_resumo)
    vinc = escola_externa.obter(db, eid, "elefante")
    assert (vinc["id"], vinc["origem"]) == (str(ESC_A), "explicito")
    assert any("Só um aviso" in m for _e, _n, m in logs(db, ex.id))
    assert _auditoria(db, "sync.escola_externa_nao_aprendida") == []


def test_d9_testar_conexao_avisa_que_nao_vai_aprender(db, escola_completa, cliente,
                                                      monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "elefante")
    turmas = _turmas(escola_completa)
    del turmas[CID_B]
    instalar_navs(monkeypatch, elefante=NavEl(
        turmas, ativas=((ESC_A, "EMEF NOME TOTALMENTE DIFERENTE"),),
        escola_da_turma={CID_A: ESC_A}))
    j = cliente.post(f"{API}/escolas/{eid}/sync/credenciais/elefante/testar").json()
    assert j["ok"] is True
    assert "NÃO grava sozinha o vínculo" in j["aviso_escola"]
    assert escola_externa.obter(db, eid, "elefante") is None          # testar não grava


def test_d9_testar_conexao_recusa_nao_diz_que_coleta(db, escola_completa, cliente,
                                                     monkeypatch):
    """Revisão e97b (defeito menor): sem vínculo, a escola externa já vinculada a
    OUTRA escola do Constela e com o nome divergente. A coleta vai ser recusada;
    o aviso não pode dizer também que "a sincronização coleta". O nome fica só
    como conferência."""
    eid = escola_completa["escola"].id
    outra, _t, _a = _nova_escola(db, nome="ESCOLA PRIMEIRA FICTICIA")
    escola_externa.salvar(db, outra.id, "elefante", str(ESC_A), origem="explicito")
    db.commit()
    credencial(db, eid, "elefante")
    turmas = _turmas(escola_completa)
    del turmas[CID_B]
    instalar_navs(monkeypatch, elefante=NavEl(
        turmas, ativas=((ESC_A, "EMEF NOME TOTALMENTE DIFERENTE"),),
        escola_da_turma={CID_A: ESC_A}))
    j = cliente.post(f"{API}/escolas/{eid}/sync/credenciais/elefante/testar").json()
    assert j["ok"] is True and j["escola_confere"] is False
    aviso = j["aviso_escola"]
    assert "vai ser recusada" in aviso
    assert "coleta" not in aviso and "NÃO grava sozinha" not in aviso
    assert "só para conferência" in aviso


# ===========================================================================
# D10 — confirmar conta efetiva em outra escola: só o Admin Global, com aviso
# ===========================================================================
def _cliente_de(email):
    from fastapi.testclient import TestClient

    from app.main import app

    c = TestClient(app)
    tok = c.post(f"{API}/auth/login", data={"username": email, "password": "s3nh4"}).json()
    c.headers["Authorization"] = f"Bearer {tok['access_token']}"
    return c


def _cenario_v(db, escola_completa, monkeypatch):
    """Sonda V do e95. A escola 1 recebe a conta u-a (Ana) pelo vínculo
    automático; a escola 2 (outra escola da plataforma) tem uma ficha com o mesmo
    nome e a lista dela também traz u-a, mais uma conta só dela (coleta mista: o
    D8 não recusa). Devolve (e1, a, e2, a2, nav1, p1, revisão de u-a na 2)."""
    from tests.test_sync_escola_cruzada import K, OUTRA_UUID
    from tests.test_sync_escola_cruzada_revisao import PlacarEco

    e1 = escola_completa["escola"].id
    a = escola_completa["alunos"][0]
    credencial(db, e1, "matific")
    p1 = PlacarEco()
    p1.linhas = list(_placar(escola_completa).linhas)
    nav1 = NavMt(p1)
    instalar_navs(monkeypatch, matific=nav1)
    assert rodar(db, e1, "matific")[0].status == "concluida"
    escola2, _t, (a2, _z) = _nova_escola(db, com_alunos=[a.nome, "Crianca Ficticia Da Segunda"])
    e2 = escola2.id
    credencial(db, e2, "matific")
    p2 = PlacarEco()
    p2.linhas = [("u-a", a.nome, K, 41, 11), ("u-z", "Crianca Ficticia Da Segunda", K, 5, 1)]
    instalar_navs(monkeypatch, matific=NavMt(p2, school_id=OUTRA_UUID))
    ex2, _ = rodar(db, e2, "matific")
    assert ex2.motivo != "contas_de_outra_escola", (ex2.status, ex2.motivo)
    rev = [r for r in _revisoes(db, e2) if r.id_externo == "u-a" and r.status == "pendente"]
    assert len(rev) == 1 and rev[0].motivo == "identidade_de_outra_escola"
    return e1, a, e2, a2, nav1, p1, rev[0]


def test_d10_gestao_da_escola_nao_confirma_conta_efetiva_em_outra_escola(
        db, escola_completa, monkeypatch):
    """Antes: o admin da escola 2 confirmava (200, sem aviso) e a Ana parava de
    atualizar na escola 1, com alerta crítico lá. Agora: 403, a pendência fica,
    nada é vinculado na 2 e a escola 1 segue recebendo o dado."""
    e1, a, e2, a2, nav1, p1, rev = _cenario_v(db, escola_completa, monkeypatch)
    r = _cliente_de(f"admin{e2}@teste.local").post(
        f"{API}/escolas/{e2}/importacoes/revisoes/{rev.id}/resolver", json={"aluno_id": a2.id})
    assert r.status_code == 403, r.text
    assert "Admin Global" in r.json()["detail"]
    db.expire_all()
    assert db.get(RevisaoIdentidade, rev.id).status == "pendente"
    assert db.execute(select(IdentidadeExterna).where(
        IdentidadeExterna.escola_id == e2, IdentidadeExterna.id_externo == "u-a")).first() is None
    assert _auditoria(db, "identidade.revisao_outra_escola_confirmada") == []
    # A escola 1 sincroniza de novo: a Ana ganhou estrelas e continua atualizando.
    p1.linhas = [(u, n, k, e + 5, at + 2) for u, n, k, e, at in p1.linhas]
    instalar_navs(monkeypatch, matific=nav1)
    ex1, _ = rodar(db, e1, "matific")
    assert ex1.status == "concluida", (ex1.status, ex1.motivo)
    assert snap_atual(db, SnapshotMatific, a.id).estrelas == 45
    assert "identidade_de_outra_escola" not in alertas_abertos(db, e1, "matific")


def test_d10_admin_global_confirma_com_aviso_e_auditoria(db, escola_completa, cliente_global,
                                                         monkeypatch):
    """O Admin Global pode confirmar (criança que mudou de escola): 200, com o aviso
    do efeito na outra escola e a auditoria própria. O aviso é verdadeiro: na
    coleta seguinte da escola 1 a conta vai para a revisão de lá."""
    e1, a, e2, a2, nav1, p1, rev = _cenario_v(db, escola_completa, monkeypatch)
    r = cliente_global.post(f"{API}/escolas/{e2}/importacoes/revisoes/{rev.id}/resolver",
                            json={"aluno_id": a2.id})
    assert r.status_code == 200, r.text
    avisos = r.json()["avisos"]
    assert any("continua vinculada a um aluno de outra escola" in m for m in avisos), avisos
    db.expire_all()
    assert db.get(RevisaoIdentidade, rev.id).status == "resolvida"
    assert db.execute(select(IdentidadeExterna.aluno_id).where(
        IdentidadeExterna.escola_id == e2,
        IdentidadeExterna.id_externo == "u-a")).scalar() == a2.id
    aud = _auditoria(db, "identidade.revisao_outra_escola_confirmada")
    assert len(aud) == 1 and aud[0].escola_id == e2
    assert aud[0].detalhes["outra_escola_id"] == e1
    assert aud[0].detalhes["id_externo"] == "u-a" and aud[0].usuario_id is not None
    # A escola 1 não foi alterada pela confirmação…
    assert db.execute(select(IdentidadeExterna.aluno_id).where(
        IdentidadeExterna.escola_id == e1,
        IdentidadeExterna.id_externo == "u-a")).scalar() == a.id
    # …e o efeito anunciado no aviso acontece na coleta seguinte dela.
    instalar_navs(monkeypatch, matific=nav1)
    rodar(db, e1, "matific")
    assert ("identidade_de_outra_escola", "u-a") in [
        (x.motivo, x.id_externo) for x in _revisoes(db, e1) if x.status == "pendente"]


def test_d10_conta_sem_vinculo_em_outra_escola_segue_com_a_gestao(
        relogio_no_ano_letivo, db, escola_completa, cliente, monkeypatch):
    """Controle: pendência de uma conta que NÃO é efetiva em outra escola continua
    sendo resolvida pela gestão da escola (sem aviso de outra escola)."""
    from app.services import politica_sync

    eid = escola_completa["escola"].id
    a = escola_completa["alunos"][0]
    politica_sync.definir(db, eid, "bloquear")
    db.commit()
    credencial(db, eid, "matific")
    p = _placar(escola_completa)
    p.linhas = [("u-nova", "Crianca Ficticia Sem Ficha", p.linhas[0][2], 3, 1)]
    instalar_navs(monkeypatch, matific=NavMt(p))
    rodar(db, eid, "matific")
    rev = [r for r in _revisoes(db, eid) if r.id_externo == "u-nova"]
    assert rev and rev[0].motivo != "identidade_de_outra_escola"
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/revisoes/{rev[0].id}/resolver",
                     json={"aluno_id": a.id})
    assert r.status_code == 200, r.text
    assert not any("outra escola" in m for m in r.json()["avisos"])
    assert _auditoria(db, "identidade.revisao_outra_escola_confirmada") == []


# ===========================================================================
# D11 (item E) — só orientação: a mensagem diz onde se decide
# ===========================================================================
def test_d11_motivo_orienta_que_a_importacao_manual_nao_encerra_a_pendencia(
        db, escola_completa, cliente, monkeypatch):
    """Sem fluxo novo: o texto do motivo (lista de Revisões e prévia) diz que a
    confirmação é feita em Revisão de identidade, pelo Admin Global, e que
    escolher a ficha na importação manual não encerra a pendência — e isso é
    verdade (a pendência continua depois do /confirmar manual)."""
    from tests.test_sync_escola_cruzada import K
    from tests.test_sync_identidade_outra_escola import _escola_dona_de

    eid = escola_completa["escola"].id
    a = escola_completa["alunos"][0]
    _escola_dona_de(db, "matific", "u-a")
    credencial(db, eid, "matific")
    instalar_navs(monkeypatch, matific=NavMt(_placar(escola_completa)))
    rodar(db, eid, "matific")                         # mista: u-b e u-c seguem
    lista = cliente.get(f"{API}/escolas/{eid}/importacoes/revisoes").json()
    rev = [r for r in lista if r["id_externo"] == "u-a"]
    assert len(rev) == 1 and rev[0]["motivo"] == "identidade_de_outra_escola"
    texto = rev[0]["motivo_texto"]
    assert "Revisão de identidade, pelo Admin Global" in texto
    assert "importação manual não encerra esta pendência" in texto
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/confirmar", json={
        "plataforma": "matific", "formato": "resumo", "tipo": "pdf",
        "linhas": [{"nome": a.nome, "aluno_id": a.id,
                    "dados": {"matific_uuid": "u-a", "estrelas": 40, "atividades": 10,
                              "pontuacao_media": 80, "turma_relatorio": K}}]})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(RevisaoIdentidade, rev[0]["id"]).status == "pendente"
