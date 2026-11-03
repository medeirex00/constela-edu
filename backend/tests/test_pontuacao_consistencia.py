"""Consistência da pontuação — três furos comprovados, travados aqui.

1. ``Nota.calculada_em`` acompanha o RECÁLCULO.
   O motor reaproveita a linha de ``Nota`` que já existe e o campo só tinha
   ``default=agora``: ficava congelado no instante da PRIMEIRA gravação, e a tela
   dizia "calculada em" uma data em que aquele número nem existia. Agora toda
   linha tocada por ``scoring.recalcular_escola`` recebe o instante do recálculo.
   O conteúdo da Nota continua DETERMINÍSTICO: recalcular duas vezes com o mesmo
   dado dá a mesma nota, a mesma posição e os mesmos ``detalhes`` — o instante
   vive só em ``calculada_em``, nunca dentro de ``detalhes``.

2. O denominador do ranking por dimensão (``rankings._contar_aferidos``) conta a
   MESMA população da lista (``rankings._ranking``).
   A lista corta as turmas que não concorrem (Educação Infantil, "1 FASE A" —
   ``services.elegibilidade``); o contador não cortava. Uma escola com EMEI
   exibia "1º de 4 aferidos" numa lista de 2 nomes.

3. A configuração da fórmula recusa valor absurdo na VALIDAÇÃO (422).
   ``PUT /pesos/{ns}`` aceitava peso NEGATIVO desde que a soma desse 100
   (``{"livros": -10, "tempo": 45, ...}``) e ``PUT /referencias`` aceitava valor
   manual negativo ou infinito, que zerava o indicador de todos os alunos sem
   aviso. ZERO continua valendo na referência manual: é o "use o automático
   nesta chave" que a tela envia e o motor entende. Só o Admin Global grava, mas
   engano de digitação também é engano.
"""
import math
from datetime import date, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.models import (
    Aluno,
    Configuracao,
    Importacao,
    Matricula,
    Nota,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
)
from app.routers import rankings
from app.schemas.comum import PesosUpdate, ReferenciasUpdate
from app.services import scoring

API = "/api/v1"


# --------------------------------------------------------------------------
# 1. calculada_em avança a cada recálculo; o resto fica idêntico
# --------------------------------------------------------------------------
def _semear_snapshots(db, escola_completa) -> None:
    """3 alunos com perfis diferentes nas duas plataformas — para `detalhes` ter
    conteúdo de verdade (indicadores, referências, pesos), não só zeros."""
    escola = escola_completa["escola"]
    imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    # (livros por nível, tempo, tentativas, acertos, atividades, estrelas)
    perfis = [({"D": 10}, 30, 40, 30, 50, 120),
              ({"AA": 2}, 500, 4, 1, 10, 20),
              ({"E": 5}, 100, 20, 10, 30, 60)]
    for aluno, (por_nivel, tempo, tent, acert, ativ, estrelas) in zip(
            escola_completa["alunos"], perfis):
        db.add(SnapshotElefante(
            escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
            livros_unicos=sum(por_nivel.values()), livros_por_nivel=dict(por_nivel),
            tempo_leitura_min=tempo, questoes_tentativas=tent, questoes_acertos=acert))
        db.add(SnapshotMatific(
            escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
            atividades=ativ, estrelas=estrelas,
            pontuacao_media=round(estrelas / ativ, 2)))
    db.commit()


def _sem_fuso(instante: datetime) -> datetime:
    """O SQLite devolve o datetime sem fuso; compara-se sempre no mesmo formato."""
    return instante.replace(tzinfo=None) if instante.tzinfo else instante


def _retrato(db, escola_id: int) -> dict:
    """Tudo o que o motor grava na Nota, MENOS `calculada_em`."""
    db.expire_all()
    return {
        n.aluno_id: {
            "nota_matific": n.nota_matific,
            "nota_elefante": n.nota_elefante,
            "nota_matific_institucional": n.nota_matific_institucional,
            "nota_elefante_institucional": n.nota_elefante_institucional,
            "nota_geral": n.nota_geral,
            "posicao": n.posicao,
            "aferido_leitura": n.aferido_leitura,
            "aferido_matematica": n.aferido_matematica,
            "posicao_leitura": n.posicao_leitura,
            "posicao_matematica": n.posicao_matematica,
            "detalhes": n.detalhes,
        }
        for n in db.execute(select(Nota).where(Nota.escola_id == escola_id)).scalars()
    }


def _instantes(db, escola_id: int) -> dict[int, datetime]:
    db.expire_all()
    return {n.aluno_id: _sem_fuso(n.calculada_em)
            for n in db.execute(select(Nota).where(Nota.escola_id == escola_id)).scalars()}


def test_calculada_em_avanca_a_cada_recalculo_e_o_resto_e_idempotente(
        db, escola_completa, monkeypatch):
    """Relógio CONTROLADO: o 1º recálculo grava T1 (INSERT), o 2º grava T2 na
    MESMA linha (UPDATE). Nota, posição e detalhes não mudam entre os dois."""
    escola_id = escola_completa["escola"].id
    _semear_snapshots(db, escola_completa)

    t1 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    t2 = t1 + timedelta(hours=3)

    # `raising=False`: o teste mede o CONTRATO (o instante gravado é o do
    # recálculo), não a existência do símbolo — sem a correção ele falha na
    # comparação de instantes, que é o defeito de verdade.
    monkeypatch.setattr(scoring, "agora", lambda: t1, raising=False)
    assert scoring.recalcular_escola(db, escola_id) == 3
    retrato_1 = _retrato(db, escola_id)
    assert len(retrato_1) == 3
    assert set(_instantes(db, escola_id).values()) == {_sem_fuso(t1)}
    ids_1 = {n.aluno_id: n.id for n in db.execute(
        select(Nota).where(Nota.escola_id == escola_id)).scalars()}

    monkeypatch.setattr(scoring, "agora", lambda: t2, raising=False)
    assert scoring.recalcular_escola(db, escola_id) == 3
    # A MESMA linha foi reaproveitada (é o caminho do UPDATE que esquecia o campo).
    assert {n.aluno_id: n.id for n in db.execute(
        select(Nota).where(Nota.escola_id == escola_id)).scalars()} == ids_1
    assert set(_instantes(db, escola_id).values()) == {_sem_fuso(t2)}, (
        "calculada_em tem de dizer QUANDO este número foi calculado")

    # Idempotência: o instante NÃO entra no conteúdo da Nota.
    assert _retrato(db, escola_id) == retrato_1
    for linha in retrato_1.values():
        assert "calculada_em" not in linha["detalhes"]
    assert any(linha["nota_elefante"] > 0 for linha in retrato_1.values())


def test_calculada_em_tambem_avanca_no_recalculo_sem_commit(
        db, escola_completa, monkeypatch):
    """``commit=False`` (o caminho do ``/resolver`` de revisão) grava o mesmo
    instante — quem confirma muda, o que é gravado não."""
    escola_id = escola_completa["escola"].id
    _semear_snapshots(db, escola_completa)
    t1 = datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc)
    t2 = t1 + timedelta(days=1)

    monkeypatch.setattr(scoring, "agora", lambda: t1, raising=False)
    scoring.recalcular_escola(db, escola_id)
    monkeypatch.setattr(scoring, "agora", lambda: t2, raising=False)
    scoring.recalcular_escola(db, escola_id, commit=False)
    db.commit()
    assert set(_instantes(db, escola_id).values()) == {_sem_fuso(t2)}


# --------------------------------------------------------------------------
# 2. denominador do ranking por dimensão = tamanho da lista
# --------------------------------------------------------------------------
def _turma(db, escola, nome, ano_escolar):
    t = Turma(escola_id=escola.id, nome=nome, ano_escolar=ano_escolar,
              ano_letivo=escola.ano_letivo_ativo)
    db.add(t)
    db.flush()
    return t


def _aluno_aferido(db, escola, turma, nome, posicao):
    """Aluno ativo com Nota AFERIDA nas duas dimensões (mesmo molde de
    ``test_elegibilidade_premiacao._aluno``)."""
    a = Aluno(escola_id=escola.id, nome=nome, status="ativo", da_lista_piloto=True)
    a.data_nascimento = date(2018, 3, 3)
    db.add(a)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=turma.id,
                     ano_letivo=turma.ano_letivo))
    db.add(Nota(escola_id=escola.id, aluno_id=a.id, ano_letivo=turma.ano_letivo,
                nota_geral=50.0, nota_elefante=50.0, nota_matific=50.0,
                aferido_leitura=True, aferido_matematica=True, posicao=posicao,
                posicao_leitura=posicao, posicao_matematica=posicao))
    db.commit()
    return a


def _escola_com_fase(db, escola_completa):
    """2 aferidos no 4º Ano (concorrem) + 2 aferidos na "1 FASE A" (Educação
    Infantil — NÃO concorrem). A Nota da Fase existe no banco (linha antiga que
    o recálculo não apaga): é ela que o contador contava a mais."""
    escola = escola_completa["escola"]
    fund = _turma(db, escola, "4º Ano K", "4º Ano")
    emei = _turma(db, escola, "1 FASE A", "1ª Fase")
    do_fund = [_aluno_aferido(db, escola, fund, "FUNDAMENTAL UM", 1),
               _aluno_aferido(db, escola, fund, "FUNDAMENTAL DOIS", 2)]
    da_fase = [_aluno_aferido(db, escola, emei, "EMEI UM", 3),
               _aluno_aferido(db, escola, emei, "EMEI DOIS", 4)]
    return escola, do_fund, da_fase


@pytest.mark.parametrize("dimensao", ["leitura", "matematica"])
def test_contar_aferidos_usa_a_mesma_elegibilidade_do_ranking(
        db, escola_completa, dimensao):
    escola, do_fund, da_fase = _escola_com_fase(db, escola_completa)
    ano = escola.ano_letivo_ativo

    lista = rankings._ranking(db, escola.id, ano, dimensao=dimensao)
    ids = {item.aluno_id for item in lista}
    assert ids == {a.id for a in do_fund}, "a Fase não concorre"
    assert not ids & {a.id for a in da_fase}

    total = rankings._contar_aferidos(db, escola.id, ano, dimensao)
    assert total == len(lista) == 2, (
        f"denominador {total} contra {len(lista)} nomes na lista")


@pytest.mark.parametrize("dimensao", ["leitura", "matematica"])
def test_n_aferidos_da_rota_bate_com_a_lista(cliente, db, escola_completa, dimensao):
    """Pela API, na visão da GESTÃO (sem recorte) — o único caminho em que o
    denominador vem de `_contar_aferidos` e não do tamanho da própria lista."""
    escola, do_fund, _ = _escola_com_fase(db, escola_completa)

    r = cliente.get(f"{API}/escolas/{escola.id}/ranking?dimensao={dimensao}")
    assert r.status_code == 200, r.text
    itens = r.json()
    assert {i["aluno_id"] for i in itens} == {a.id for a in do_fund}
    assert {i["n_aferidos"] for i in itens} == {len(itens)} == {2}


# --------------------------------------------------------------------------
# 3. pesos e referências manuais finitos e >= 0 (422 na validação)
# --------------------------------------------------------------------------
def _base(escola_id: int) -> str:
    return f"{API}/escolas/{escola_id}/configuracoes"


@pytest.mark.parametrize("namespace,valores", [
    # Soma 100 — passava pela única regra que existia.
    ("elefante", {"livros": -10.0, "dificuldade": 45.0, "questoes": 35.0, "tempo": 30.0}),
    ("matific", {"atividades": 120.0, "media": -20.0, "estrelas": 0.0}),
    ("geral", {"matific": -50.0, "elefante": 150.0}),
])
def test_peso_negativo_e_recusado(cliente_global, db, escola_completa,
                                  namespace, valores):
    base = _base(escola_completa["escola"].id)
    antes = cliente_global.get(f"{base}/pesos/{namespace}").json()

    r = cliente_global.put(f"{base}/pesos/{namespace}", json={"valores": valores})
    assert r.status_code == 422, r.text
    assert "não pode ser negativo" in r.text
    # Nada foi gravado.
    assert cliente_global.get(f"{base}/pesos/{namespace}").json() == antes


@pytest.mark.parametrize("namespace,valores", [
    ("elefante", {"livros": 35.0, "dificuldade": 30.0, "questoes": 30.0, "tempo": 5.0}),
    # Peso ZERO continua válido: é como a escola desliga um indicador.
    ("matific", {"atividades": 60.0, "media": 40.0, "estrelas": 0.0}),
    ("geral", {"matific": 0.0, "elefante": 100.0}),
])
def test_peso_valido_continua_aceito(cliente_global, db, escola_completa,
                                     namespace, valores):
    base = _base(escola_completa["escola"].id)
    r = cliente_global.put(f"{base}/pesos/{namespace}", json={"valores": valores})
    assert r.status_code == 200, r.text
    assert cliente_global.get(f"{base}/pesos/{namespace}").json()["valores"] == valores


@pytest.mark.parametrize("valor", [-5.0, -0.01])
def test_referencia_manual_negativa_e_recusada(cliente_global, db,
                                                   escola_completa, valor):
    base = _base(escola_completa["escola"].id)
    antes = cliente_global.get(f"{base}/referencias").json()

    r = cliente_global.put(f"{base}/referencias", json={
        "modo": "manual", "valores_manuais": {"max_livros": 20.0, "max_tempo": valor}})
    assert r.status_code == 422, r.text
    assert "não pode ser negativo" in r.text
    # Nada foi gravado (nem o modo).
    assert cliente_global.get(f"{base}/referencias").json() == antes


def test_referencia_manual_positiva_continua_aceita(cliente_global, db, escola_completa):
    base = _base(escola_completa["escola"].id)
    r = cliente_global.put(f"{base}/referencias", json={
        "modo": "manual", "valores_manuais": {"max_livros": 20.0, "max_tempo": 0.5}})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["modo"] == "manual"
    assert corpo["valores_manuais"] == {"max_livros": 20.0, "max_tempo": 0.5}

    # Voltar ao automático sem valores manuais segue valendo.
    r = cliente_global.put(f"{base}/referencias", json={"modo": "auto", "valores_manuais": {}})
    assert r.status_code == 200, r.text


def test_referencia_manual_zero_segue_o_automatico(cliente_global, db, escola_completa):
    """O que a tela envia para a plataforma sem dado: 0 = "use o automático".
    (O modo manual só vale no perfil personalizado; no institucional a régua da
    rede é sempre automática.)"""
    escola_id = escola_completa["escola"].id
    db.add(Configuracao(escola_id=escola_id, namespace=scoring.PERFIL_SCORING_NS,
                        chave="modo", valor="personalizado"))
    db.commit()
    base = _base(escola_id)
    auto = cliente_global.get(f"{base}/referencias").json()["valores_em_uso"]
    r = cliente_global.put(f"{base}/referencias", json={
        "modo": "manual", "valores_manuais": {"max_livros": 20.0, "max_tempo": 0.0}})
    assert r.status_code == 200, r.text
    em_uso = cliente_global.get(f"{base}/referencias").json()["valores_em_uso"]
    assert em_uso["max_livros"] == 20.0
    assert em_uso["max_tempo"] == auto["max_tempo"]


@pytest.mark.parametrize("valor", [math.inf, -math.inf, math.nan])
def test_valor_nao_finito_e_recusado_no_schema(valor):
    """NaN/infinito não chegam pela tela (JSON padrão não os tem), mas o contrato
    os recusa — no schema, sem depender da rota."""
    with pytest.raises(ValidationError):
        ReferenciasUpdate(modo="manual", valores_manuais={"max_livros": valor})
    with pytest.raises(ValidationError):
        PesosUpdate(valores={"matific": valor, "elefante": 100.0})
