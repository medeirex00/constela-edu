"""Leitura em lote das plataformas: os retratos são ordenados UMA vez, para qualquer número
de períodos (DESEMPENHO-6).

Antes, cada período pedido (os 4 bimestres da evolução, os blocos do ano letivo da proteção
por blocos) numerava, com duas ``row_number``, TODOS os retratos da rede — nas questões do
Elefante e no Matific: 17 funções de janela para a evolução por bimestre, ~6 s no PG local
com a rede fictícia de 28 escolas. Agora os retratos de cada fonte são ordenados uma vez
(cada linha com a data da anterior e a da seguinte) e cada período só filtra.

O que estes testes sustentam:

* a consulta das leituras tem o MESMO número de funções de janela para 1 e para 4 períodos;
* as linhas escolhidas são exatamente as da regra ("a última antes do início, a primeira e a
  última dentro"; nas questões, também as das bordas na tolerância e a primeira depois), por
  uma referência em Python, em dados com empates de horário, execuções de minutos, piso do
  ano letivo depois do início e períodos sem início ou sem fim.

Dados INVENTADOS (``test_analise_base``).
"""
import random
from datetime import date, datetime, timedelta

from sqlalchemy import event

from app.models import Importacao, SnapshotElefante, SnapshotMatific
from app.models.plataformas import IMPORTACAO_SEM_QUESTOES
from app.services import relatorios_periodo as rp
from app.services.analise import evolucao as svc_evolucao
from app.services.analise import plataformas as svc
from tests.test_analise_base import (mundo_plataformas, nova_escola, nova_rede,
                                     turma_com_alunos)

HOJE_FIM_DO_ANO = date(2026, 12, 20)


def _sql_das_leituras(db, funcao) -> str:
    """O SQL da consulta das leituras em lote (a única com o CTE ``primeiras``)."""
    vistos: list[str] = []

    def _anota(_c, _cur, sql, *_a):
        if "primeiras" in sql:
            vistos.append(sql)

    motor = db.get_bind()
    event.listen(motor, "before_cursor_execute", _anota)
    try:
        funcao()
    finally:
        event.remove(motor, "before_cursor_execute", _anota)
    assert len(vistos) == 1, len(vistos)
    return vistos[0].lower()


def test_funcoes_de_janela_nao_crescem_com_o_numero_de_periodos(db):
    base = mundo_plataformas(db)
    rede = base["rede"]
    um = _sql_das_leituras(db, lambda: svc.plataformas_da_rede(
        db, rede, preset="bimestre_3", hoje=HOJE_FIM_DO_ANO))
    quatro = _sql_das_leituras(db, lambda: svc_evolucao.evolucao(db, rede,
                                                                 hoje=HOJE_FIM_DO_ANO))
    assert quatro.count("union all") > um.count("union all")     # 4 períodos na consulta
    assert quatro.count(" over (") == um.count(" over (")


# --- As linhas escolhidas: referência em Python --------------------------------------------

def _ref_matific(linhas, grupos):
    """A regra do Matific, grupo a grupo: só a escola do grupo, retratos >= piso e <= fim;
    por criança e faixa (antes do início / dentro), em ordem de (data, id), a ÚLTIMA antes e
    a PRIMEIRA e a ÚLTIMA dentro."""
    saida = set()
    for g, (inicio, fim, piso, ids) in grupos.items():
        por: dict[tuple, list] = {}
        for r in linhas:
            if r.escola_id not in ids or (piso is not None and r.data_referencia < piso) or (
                    fim is not None and r.data_referencia > fim):
                continue
            faixa = 0 if inicio is not None and r.data_referencia < inicio else 1
            por.setdefault((r.escola_id, r.aluno_id, faixa), []).append(r)
        for (eid, aid, faixa), rs in por.items():
            rs.sort(key=lambda r: (r.data_referencia, r.id))
            escolhidas = [rs[-1]] if faixa == 0 else [rs[0], rs[-1]]
            saida |= {(g, eid, aid, r.id) for r in escolhidas}
    return saida


def _ref_questoes(linhas, grupos, sem_questoes):
    """A regra das questões, grupo a grupo: fora as coletas em que as questões não vieram;
    só a PRIMEIRA linha de cada execução (a anterior a mais de 15 min); por faixa das bordas
    (em UTC, na tolerância de ``rp._mede_a_borda``) a última antes, todas nas bordas, a
    primeira e a última do miolo e a primeira depois."""
    validas = [r for r in linhas if r.importacao_id not in sem_questoes]
    series: dict[tuple, list] = {}
    for r in validas:
        series.setdefault((r.escola_id, r.aluno_id), []).append(r)
    primeiras = []
    for rs in series.values():
        rs.sort(key=lambda r: (r.data_referencia, r.id))
        for i, r in enumerate(rs):
            if i == 0 or r.data_referencia - rs[i - 1].data_referencia > rp._MESMA_COLETA:
                primeiras.append(r)
    antes, depois = rp.TOLERANCIA_BORDA, rp.tolerancia_depois_da_borda()
    saida = set()
    for g, (janela, ids) in grupos.items():
        def faixa(d):
            if janela.inicio is not None:
                ini = svc._utc(janela.inicio)
                if d < ini - antes:
                    return 0
                if d <= ini + depois:
                    return 1
            if janela.fim is not None:
                fim = svc._utc(janela.fim + timedelta(microseconds=1))
                if d < fim - antes:
                    return 2
                if d <= fim + depois:
                    return 3
                return 4
            return 2
        por: dict[tuple, list] = {}
        for r in primeiras:
            if r.escola_id in ids:
                por.setdefault((r.escola_id, r.aluno_id, faixa(r.data_referencia)), []).append(r)
        for (eid, aid, f), rs in por.items():
            rs.sort(key=lambda r: (r.data_referencia, r.id))
            escolhidas = {0: [rs[-1]], 1: rs, 2: [rs[0], rs[-1]], 3: rs, 4: [rs[0]]}[f]
            saida |= {(g, eid, aid, r.id) for r in escolhidas}
    return saida


def _ids(lidos) -> set:
    return {(g, eid, aid, r.id) for (g, eid), por_aluno in lidos.items()
            for aid, rs in por_aluno.items() for r in rs}


def _mundo_aleatorio(db, semente):
    """2 escolas, 9 crianças; retratos diários e semanais espalhados por 2025–2026, com
    empates de horário, execuções de poucos minutos e coletas em que as questões não vieram."""
    rnd = random.Random(semente)
    rede = nova_rede(db, nome=f"Rede Fictícia Lote {semente}", codigo=f"35999{semente:02d}")
    escolas = [nova_escola(db, rede, f"EMEF Fictícia Lote {semente}-{n}", None)
               for n in (1, 2)]
    sem_questoes = set()
    for e in escolas:
        imp_ok = Importacao(escola_id=e.id, plataforma="elefante", tipo="seed", qtd_alunos=0,
                            status="concluida")
        imp_sem = Importacao(escola_id=e.id, plataforma="elefante", tipo="seed", qtd_alunos=0,
                             status=IMPORTACAO_SEM_QUESTOES)
        imp_mat = Importacao(escola_id=e.id, plataforma="matific", tipo="seed", qtd_alunos=0,
                             status="concluida")
        db.add_all([imp_ok, imp_sem, imp_mat])
        db.flush()
        sem_questoes.add(imp_sem.id)
        for aluno in turma_com_alunos(db, e, "3º Ano", 4 + (e is escolas[1])):
            quando = datetime(2025, 11, 1, 3, 0) + timedelta(hours=rnd.randrange(0, 72))
            while quando < datetime(2027, 1, 20):
                for modelo in (SnapshotElefante, SnapshotMatific):
                    if rnd.random() < 0.15:
                        continue
                    repeticoes = 1 + (rnd.random() < 0.2) + (rnd.random() < 0.1)
                    instante = quando
                    for _ in range(repeticoes):           # a mesma execução (minutos)
                        if modelo is SnapshotElefante:
                            imp = imp_sem if rnd.random() < 0.1 else imp_ok
                            db.add(SnapshotElefante(
                                escola_id=e.id, aluno_id=aluno.id, importacao_id=imp.id,
                                data_referencia=instante, livros_unicos=0, tempo_leitura_min=0,
                                questoes_tentativas=rnd.randrange(50),
                                questoes_acertos=rnd.randrange(30), livros_por_nivel={}))
                        else:
                            db.add(SnapshotMatific(
                                escola_id=e.id, aluno_id=aluno.id, importacao_id=imp_mat.id,
                                data_referencia=instante, atividades=rnd.randrange(80),
                                estrelas=rnd.randrange(200), pontuacao_media=0.0))
                        if rnd.random() < 0.5:            # empate exato de horário
                            instante = instante + timedelta(minutes=rnd.choice((0, 3, 9)))
                quando += timedelta(days=rnd.choice((1, 1, 2, 7)),
                                    minutes=rnd.choice((0, 0, 20, -30)))
    db.commit()
    return escolas, sem_questoes


def _janelas():
    hoje = date(2026, 11, 11)
    return [rp.resolver_janela(f"bimestre_{n}", 2026, hoje=hoje) for n in (1, 2, 3, 4)] + [
        rp.resolver_janela("ano_letivo", 2026, hoje=hoje),
        rp.resolver_janela("tudo", 2026, hoje=hoje),
        rp.resolver_janela("personalizado", 2026, inicio=date(2026, 3, 9),
                           fim=date(2026, 3, 9), hoje=hoje),
        rp.resolver_janela("personalizado", 2026, inicio=date(2025, 12, 20),
                           fim=date(2026, 2, 3), hoje=hoje)]


def test_linhas_escolhidas_sao_as_da_regra(db):
    for semente in (3, 11):
        escolas, sem_questoes = _mundo_aleatorio(db, semente)
        ids = [e.id for e in escolas]
        janelas = _janelas()
        grupos_q = {g: (j, ids if g % 3 else ids[:1]) for g, j in enumerate(janelas)}
        esperadas = _ref_questoes(db.query(SnapshotElefante).filter(
            SnapshotElefante.escola_id.in_(ids)).all(), grupos_q, sem_questoes)
        lidas = _ids(svc._questoes_em_lote(db, grupos_q))
        assert lidas == esperadas, (semente, len(lidas ^ esperadas))
        assert len(esperadas) > 100

        piso_2026 = datetime(2026, 1, 1)
        grupos_m = {}
        for g, j in enumerate(janelas):
            piso = [None, piso_2026, datetime(2026, 3, 1)][g % 3]     # piso depois do início
            grupos_m[g] = (j.inicio, j.fim, piso, ids if g % 2 else ids[1:])
        esperadas_m = _ref_matific(db.query(SnapshotMatific).filter(
            SnapshotMatific.escola_id.in_(ids)).all(), grupos_m)
        lidas_m = _ids(svc._retratos_em_lote(db, SnapshotMatific, ("atividades", "estrelas"),
                                             grupos_m))
        assert lidas_m == esperadas_m, (semente, len(lidas_m ^ esperadas_m))
        assert len(esperadas_m) > 50
