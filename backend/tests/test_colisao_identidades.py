"""Duas contas da MESMA plataforma na MESMA ficha nunca se sobrescrevem em silêncio.

O motor de identidade sempre travou isso nos caminhos por NOME (``_para_aluno``:
"o aluno encontrado já tem outra conta nesta plataforma"). O passo 1 — casar pela
IDENTIDADE externa — era o único sem a trava. Bastava um gestor resolver a
pendência da segunda conta para as duas ficarem vinculadas à mesma ficha; a
partir daí toda sincronização casava as duas por identidade, ambas viravam
ASSOCIAR para o mesmo aluno e o retrato de uma sobrescrevia o da outra sem
aviso, sem log e sem rastro — o importador guarda só a ÚLTIMA linha do aluno
(``linhas_aluno[-1]``) e a reimportação do mesmo dia ainda muta o snapshot no
lugar (``_mesmo_dia``).

A correção não decide nada: bloqueia. Qual conta é a criança — ou se as duas
são — é decisão humana, e ela some da fila no instante em que a máquina escolhe.
"""
import pytest
from sqlalchemy import func, select

from app.models import (Aluno, IdentidadeExterna, Importacao, LogAuditoria,
                        Matricula, RevisaoIdentidade, SnapshotMatific, Turma)
from app.routers import importacoes as imp
from app.schemas.importacao import ImportacaoConfirm, LinhaConfirmacao
from app.services import identidade_aluno as ida
from app.services import triagem_revisoes as tri

ANO = 2026


# --- montagem ---------------------------------------------------------------

def _turma(db, escola, nome="3ºA", ano_escolar="3º Ano", codigo="300300001"):
    t = Turma(escola_id=escola.id, nome=nome, ano_escolar=ano_escolar,
              ano_letivo=ANO, codigo_externo=codigo, turno="tarde")
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
    db.add(IdentidadeExterna(escola_id=escola.id, aluno_id=aluno.id,
                             plataforma=plataforma, id_externo=id_externo))
    db.flush()


def _linha(nome, turma, uuid, atividades, estrelas):
    return LinhaConfirmacao(
        nome=nome,
        dados={"turma_relatorio": turma, "matific_uuid": uuid,
               "atividades": atividades, "estrelas": estrelas,
               "pontuacao_media": round(estrelas / max(atividades, 1), 2)},
        aluno_id=None, criar_em_turma_nome=turma)


def _importar(db, escola, admin, linhas, *, recalcular=False, **kw):
    conf = ImportacaoConfirm(plataforma="matific", formato="resumo", tipo="texto",
                             linhas=linhas, recalcular=recalcular, **kw)
    return imp.confirmar(dados=conf, escola_id=escola.id, usuario=admin, db=db)


def _retrato_gravado(db, escola, aluno, atividades, estrelas, media):
    """Um retrato que já estava no banco antes da importação — como o que a
    ficha tinha quando só havia UMA conta."""
    i = Importacao(escola_id=escola.id, plataforma="matific", tipo="texto")
    db.add(i)
    db.flush()
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id, importacao_id=i.id,
                           atividades=atividades, estrelas=estrelas,
                           pontuacao_media=media))
    db.commit()


def _snaps(db, aluno_id):
    return db.execute(select(SnapshotMatific).where(SnapshotMatific.aluno_id == aluno_id)
                      .order_by(SnapshotMatific.id)).scalars().all()


def _pendentes(db, escola):
    return db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == escola.id,
        RevisaoIdentidade.status == "pendente")
        .order_by(RevisaoIdentidade.id)).scalars().all()


@pytest.fixture()
def cena(db, escola_completa):
    """Uma ficha com DUAS contas Matific já vinculadas — o estado real que um
    gestor cria ao resolver a pendência da segunda conta."""
    esc, admin = escola_completa["escola"], escola_completa["admin"]
    t = _turma(db, esc)
    allyce = _aluno(db, esc, t, "ALLYCE CRISTINA BARBOSA DE ALMEIDA")
    outra = _aluno(db, esc, t, "BEATRIZ SOUZA LIMA")
    _vincular(db, esc, allyce, "conta-A")
    _vincular(db, esc, allyce, "conta-B")
    _vincular(db, esc, outra, "conta-C")
    db.commit()
    return {"escola": esc, "admin": admin, "turma": t.nome,
            "allyce": allyce, "outra": outra}


# --- 1. identidade única continua funcionando -------------------------------

def test_1_uma_identidade_normal_importa_como_sempre(db, escola_completa):
    esc, admin = escola_completa["escola"], escola_completa["admin"]
    t = _turma(db, esc)
    a = _aluno(db, esc, t, "JOANA PEREIRA LIMA")
    _vincular(db, esc, a, "conta-unica")
    db.commit()

    _importar(db, esc, admin, [_linha("JOANA PEREIRA LIMA", "3ºA", "conta-unica", 30, 120)])

    [s] = _snaps(db, a.id)
    assert (s.atividades, s.estrelas) == (30, 120)
    assert _pendentes(db, esc) == []


def test_14_identidade_unica_continua_funcionando_depois_da_trava(db, cena):
    """A trava é por FICHA: a colega de uma conta só não é afetada."""
    _importar(db, cena["escola"], cena["admin"],
              [_linha("BEATRIZ SOUZA LIMA", cena["turma"], "conta-C", 11, 44)])

    [s] = _snaps(db, cena["outra"].id)
    assert (s.atividades, s.estrelas) == (11, 44)


# --- 2. duas identidades em fichas DIFERENTES -------------------------------

def test_2_duas_identidades_em_fichas_diferentes_nao_colidem(db, escola_completa):
    esc, admin = escola_completa["escola"], escola_completa["admin"]
    t = _turma(db, esc)
    a1 = _aluno(db, esc, t, "JOANA PEREIRA LIMA")
    a2 = _aluno(db, esc, t, "CARLOS EDUARDO DIAS")
    _vincular(db, esc, a1, "conta-1")
    _vincular(db, esc, a2, "conta-2")
    db.commit()

    _importar(db, esc, admin, [
        _linha("JOANA PEREIRA LIMA", "3ºA", "conta-1", 30, 120),
        _linha("CARLOS EDUARDO DIAS", "3ºA", "conta-2", 7, 21)])

    assert [(s.atividades, s.estrelas) for s in _snaps(db, a1.id)] == [(30, 120)]
    assert [(s.atividades, s.estrelas) for s in _snaps(db, a2.id)] == [(7, 21)]
    assert _pendentes(db, esc) == []


# --- 3. duas identidades na MESMA ficha -------------------------------------

def test_3_duas_contas_na_mesma_ficha_nao_gravam_snapshot(db, cena):
    """Nenhuma das duas entra: não dá para saber qual número é o da criança."""
    _importar(db, cena["escola"], cena["admin"], [
        _linha("ALLYCE CRISTINA BARBOSA DE ALMEIDA", cena["turma"], "conta-A", 139, 523),
        _linha("ALLYCE CRISTINA BARBOSA DE ALMEIDA", cena["turma"], "conta-B", 3, 9)])

    assert _snaps(db, cena["allyce"].id) == []
    pend = _pendentes(db, cena["escola"])
    assert len(pend) == 2
    assert {p.motivo for p in pend} == {"outra_identidade_na_plataforma"}
    assert {p.id_externo for p in pend} == {"conta-A", "conta-B"}


def test_3b_cada_conta_guarda_o_proprio_payload_na_fila(db, cena):
    """Preservar de forma auditável: o número de CADA conta fica na pendência
    dela, nunca misturado."""
    _importar(db, cena["escola"], cena["admin"], [
        _linha("ALLYCE CRISTINA BARBOSA DE ALMEIDA", cena["turma"], "conta-A", 139, 523),
        _linha("ALLYCE CRISTINA BARBOSA DE ALMEIDA", cena["turma"], "conta-B", 3, 9)])

    por_conta = {p.id_externo: p.linhas[0] for p in _pendentes(db, cena["escola"])}
    assert (por_conta["conta-A"]["atividades"], por_conta["conta-A"]["estrelas"]) == (139, 523)
    assert (por_conta["conta-B"]["atividades"], por_conta["conta-B"]["estrelas"]) == (3, 9)


# --- 4. mesmo dia: o snapshot que já existia NÃO é tocado -------------------

def test_4_reimportacao_no_mesmo_dia_nao_muta_o_snapshot_existente(db, cena):
    """Antes, ``_mesmo_dia`` mutava a foto do dia NO LUGAR — a segunda conta
    apagava a primeira sem deixar linha nova no histórico."""
    esc, admin, allyce = cena["escola"], cena["admin"], cena["allyce"]
    # a ficha já tem um retrato gravado (de quando só havia uma conta)
    _retrato_gravado(db, esc, allyce, 139, 523, 3.76)
    antes = [(s.id, s.atividades, s.estrelas) for s in _snaps(db, allyce.id)]

    _importar(db, esc, admin, [
        _linha("ALLYCE CRISTINA BARBOSA DE ALMEIDA", cena["turma"], "conta-B", 3, 9)])

    db.expire_all()
    assert [(s.id, s.atividades, s.estrelas) for s in _snaps(db, allyce.id)] == antes


# --- 5, 6 e 7. a ORDEM não decide nada --------------------------------------

def _resultado_na_ordem(db, cena, ordem):
    linhas = {
        "A": _linha("ALLYCE CRISTINA BARBOSA DE ALMEIDA", cena["turma"], "conta-A", 139, 523),
        "B": _linha("ALLYCE CRISTINA BARBOSA DE ALMEIDA", cena["turma"], "conta-B", 3, 9),
    }
    _importar(db, cena["escola"], cena["admin"], [linhas[x] for x in ordem])
    return ([(s.atividades, s.estrelas) for s in _snaps(db, cena["allyce"].id)],
            sorted(p.id_externo for p in _pendentes(db, cena["escola"])))


def test_5_ordem_A_depois_B(db, cena):
    snaps, pend = _resultado_na_ordem(db, cena, "AB")
    assert snaps == [] and pend == ["conta-A", "conta-B"]


def test_6_ordem_B_depois_A(db, cena):
    snaps, pend = _resultado_na_ordem(db, cena, "BA")
    assert snaps == [] and pend == ["conta-A", "conta-B"]


def test_7_a_ordem_nao_determina_quem_vence(db, escola_completa):
    """O invariante central: o resultado é IDÊNTICO nas duas ordens. Antes,
    ``linhas_aluno[-1]`` fazia a última linha do arquivo vencer."""
    esc, admin = escola_completa["escola"], escola_completa["admin"]
    t = _turma(db, esc)
    a = _aluno(db, esc, t, "ALLYCE CRISTINA BARBOSA DE ALMEIDA")
    _vincular(db, esc, a, "conta-A")
    _vincular(db, esc, a, "conta-B")
    db.commit()
    cena = {"escola": esc, "admin": admin, "turma": "3ºA", "allyce": a}

    ab = _resultado_na_ordem(db, cena, "AB")
    for p in _pendentes(db, esc):          # limpa a fila entre as duas rodadas
        db.delete(p)
    db.commit()
    ba = _resultado_na_ordem(db, cena, "BA")
    assert ab == ba


# --- 8. nada é sobrescrito em silêncio --------------------------------------

def test_8_a_escola_e_avisada_em_vez_de_perder_dado_calado(db, cena):
    r = _importar(db, cena["escola"], cena["admin"], [
        _linha("ALLYCE CRISTINA BARBOSA DE ALMEIDA", cena["turma"], "conta-A", 139, 523),
        _linha("ALLYCE CRISTINA BARBOSA DE ALMEIDA", cena["turma"], "conta-B", 3, 9)])

    texto = " ".join(r.avisos)
    assert "outra conta nesta plataforma" in texto
    assert "não é segura" in texto.lower() or "NÃO" in texto
    assert r.qtd_alunos == 0          # nenhuma linha virou dado


# --- 9. nunca somar ---------------------------------------------------------

def test_9_nunca_soma_as_duas_contas(db, cena):
    _importar(db, cena["escola"], cena["admin"], [
        _linha("ALLYCE CRISTINA BARBOSA DE ALMEIDA", cena["turma"], "conta-A", 139, 523),
        _linha("ALLYCE CRISTINA BARBOSA DE ALMEIDA", cena["turma"], "conta-B", 3, 9)])

    for s in _snaps(db, cena["allyce"].id):
        assert (s.atividades, s.estrelas) != (142, 532)
    assert _snaps(db, cena["allyce"].id) == []


# --- 10. auditoria ----------------------------------------------------------

def test_10_a_colisao_fica_auditada(db, cena):
    _importar(db, cena["escola"], cena["admin"], [
        _linha("ALLYCE CRISTINA BARBOSA DE ALMEIDA", cena["turma"], "conta-A", 139, 523),
        _linha("ALLYCE CRISTINA BARBOSA DE ALMEIDA", cena["turma"], "conta-B", 3, 9)])

    logs = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "aluno.revisao_necessaria")).scalars().all()
    assert len(logs) == 2
    motivos = {x.detalhes.get("motivo") for x in logs}
    assert motivos == {"outra_identidade_na_plataforma"}
    assert all(x.detalhes.get("decisao") == "REVIEW_REQUIRED" for x in logs)


# --- 11. scoring ------------------------------------------------------------

def test_11_scoring_nao_muda_arbitrariamente(db, cena):
    """Sem snapshot novo não há número novo: a nota fica exatamente como estava,
    em vez de passar a refletir uma conta escolhida por acaso."""
    esc, allyce = cena["escola"], cena["allyce"]
    _retrato_gravado(db, esc, allyce, 139, 523, 3.76)

    _importar(db, esc, cena["admin"], [
        _linha("ALLYCE CRISTINA BARBOSA DE ALMEIDA", cena["turma"], "conta-B", 3, 9)],
        recalcular=True)

    db.expire_all()
    atual = _snaps(db, allyce.id)[-1]
    assert (atual.atividades, atual.estrelas) == (139, 523)


# --- 12. convive com a guarda de retrato superado ---------------------------

def test_12_compativel_com_retrato_superado(db, cena):
    """``_retrato_superado`` compara DATAS e não é afetado pela trava: a
    pendência da colisão continua respondendo a ela normalmente."""
    esc, allyce = cena["escola"], cena["allyce"]
    _importar(db, esc, cena["admin"], [
        _linha("ALLYCE CRISTINA BARBOSA DE ALMEIDA", cena["turma"], "conta-A", 139, 523)])
    [rev] = _pendentes(db, esc)
    # sem snapshot gravado, não há retrato mais novo para superar nada
    assert imp._retrato_superado(db, esc.id, allyce.id, rev) is None


# --- 13. irmãs (resumo + leituras) ------------------------------------------

def test_13_a_trava_vale_por_plataforma_e_nao_atinge_as_irmas(db, cena):
    """Ter conta no Elefante NÃO é colisão: a trava é por plataforma."""
    esc, allyce = cena["escola"], cena["allyce"]
    _vincular(db, esc, allyce, "elefante-1", plataforma="elefante")
    db.commit()

    ctx = ida.carregar_contexto(db, esc.id, ANO)
    linha_ele = ida.linha_de_dados(
        "ALLYCE CRISTINA BARBOSA DE ALMEIDA",
        {"elefante_student_id": "elefante-1", "livros_unicos": 9},
        plataforma="elefante", turma_nome=cena["turma"])
    assert ida.decidir(ctx, linha_ele).acao == ida.ASSOCIAR

    linha_mat = ida.linha_de_dados(
        "ALLYCE CRISTINA BARBOSA DE ALMEIDA",
        {"matific_uuid": "conta-A", "atividades": 1}, plataforma="matific",
        turma_nome=cena["turma"])
    assert ida.decidir(ctx, linha_mat).acao == ida.REVISAR


# --- 15. a triagem reconhece o caso -----------------------------------------

def test_15_triagem_classifica_multi_identidade_mesmo_aluno(db, cena):
    _importar(db, cena["escola"], cena["admin"], [
        _linha("ALLYCE CRISTINA BARBOSA DE ALMEIDA", cena["turma"], "conta-A", 139, 523),
        _linha("ALLYCE CRISTINA BARBOSA DE ALMEIDA", cena["turma"], "conta-B", 3, 9)])

    saida = tri.triar_escola(db, cena["escola"].id)
    assert saida
    for v in saida.values():
        assert v.classificacao == tri.DECISAO_HUMANA
        assert v.motivo == tri.MULTI_IDENTIDADE
        assert v.aluno_id == cena["allyce"].id
        assert any("outra(s) conta(s)" in c for c in v.conflitos)


# --- a decisão HUMANA continua mandando -------------------------------------

def test_decisao_explicita_do_gestor_ainda_aplica_os_dados(db, cena):
    """A trava é contra a escolha AUTOMÁTICA. Quando um gestor escolhe a ficha
    (passo 0, que é o caminho do /resolver), os dados entram — auditados, e não
    em silêncio. Sem isso, a fila viraria um beco sem saída."""
    esc, allyce = cena["escola"], cena["allyce"]
    linha = _linha("ALLYCE CRISTINA BARBOSA DE ALMEIDA", cena["turma"], "conta-A", 139, 523)
    linha.aluno_id = allyce.id

    _importar(db, esc, cena["admin"], [linha])

    [s] = _snaps(db, allyce.id)
    assert (s.atividades, s.estrelas) == (139, 523)
    assert _pendentes(db, esc) == []


def test_ficha_com_tres_contas_tambem_trava(db, escola_completa):
    esc, admin = escola_completa["escola"], escola_completa["admin"]
    t = _turma(db, esc)
    a = _aluno(db, esc, t, "JOANA PEREIRA LIMA")
    for u in ("c1", "c2", "c3"):
        _vincular(db, esc, a, u)
    db.commit()

    _importar(db, esc, admin, [_linha("JOANA PEREIRA LIMA", "3ºA", "c2", 5, 10)])
    assert _snaps(db, a.id) == []
    assert [p.motivo for p in _pendentes(db, esc)] == ["outra_identidade_na_plataforma"]


def test_nenhuma_ficha_nova_e_criada_pela_colisao(db, cena):
    antes = db.scalar(select(func.count()).select_from(Aluno)
                      .where(Aluno.escola_id == cena["escola"].id))
    _importar(db, cena["escola"], cena["admin"], [
        _linha("ALLYCE CRISTINA BARBOSA DE ALMEIDA", cena["turma"], "conta-A", 139, 523),
        _linha("ALLYCE CRISTINA BARBOSA DE ALMEIDA", cena["turma"], "conta-B", 3, 9)])
    assert db.scalar(select(func.count()).select_from(Aluno)
                     .where(Aluno.escola_id == cena["escola"].id)) == antes


def test_nenhuma_identidade_e_transferida_pela_colisao(db, cena):
    antes = {(i.id_externo, i.aluno_id) for i in db.execute(
        select(IdentidadeExterna).where(
            IdentidadeExterna.escola_id == cena["escola"].id)).scalars()}
    _importar(db, cena["escola"], cena["admin"], [
        _linha("ALLYCE CRISTINA BARBOSA DE ALMEIDA", cena["turma"], "conta-A", 139, 523),
        _linha("ALLYCE CRISTINA BARBOSA DE ALMEIDA", cena["turma"], "conta-B", 3, 9)])
    db.expire_all()
    depois = {(i.id_externo, i.aluno_id) for i in db.execute(
        select(IdentidadeExterna).where(
            IdentidadeExterna.escola_id == cena["escola"].id)).scalars()}
    assert antes == depois
