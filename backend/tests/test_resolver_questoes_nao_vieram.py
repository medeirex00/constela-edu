"""A fila de identidade × coleta em que as questões NÃO vieram (S9).

A sincronização em que a API do Elefante não manda ``responses``/``approvedResponses``
grava os retratos numa importação marcada (``IMPORTACAO_SEM_QUESTOES``): eles não são
borda das Questões do período. Desde a revisão de identidade, mais linhas dessa coleta
vão para a fila em vez de entrar direto: o nome abreviado (A2, ``nome_incompleto``) e
as duas contas sem vínculo que disputam a mesma ficha (A5).

O ``/resolver`` reaplica a linha guardada pelo mesmo pipeline. Sem herdar a marca da
importação de origem, o retrato nascia numa importação "concluida": com as questões da
coleta anterior e a data da coleta (A5), o relatório dizia "0 no período, completa"; com
0 questões na ficha nova (A2), a coleta normal seguinte contava o contador VITALÍCIO
inteiro como questões do período, também "completa". Dados FICTÍCIOS.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlalchemy import select

from app.models import Importacao, SnapshotElefante
from app.models.plataformas import IMPORTACAO_SEM_QUESTOES
from app.services import relatorios_periodo as rp
from app.sync import fuso, orchestrator
from app.sync.interfaces import ArquivoObtido
from tests.sync_integridade_comum import (aluno, aplicar, dono, elefante_resumo, pendentes,
                                          sem_disco)

K = "3 ANO A TARDE ANUAL (300396804)"


def _sem_questoes(turma: str, alunos: list[dict]) -> ArquivoObtido:
    """overall-course-report SEM ``responses``/``approvedResponses`` (S9)."""
    payload = {"courseId": 700001,
               "courseSchoolDescriptors": {"courseName": turma,
                                           "schoolName": "ESCOLA FICTICIA"},
               "students": [{"totalReadTime": 600, **a} for a in alunos]}
    return ArquivoObtido(conteudo=json.dumps(payload).encode("utf-8"),
                         nome_arquivo="elefante_ficticio.json", plataforma="elefante",
                         content_type=orchestrator.CT_ELEFANTE_API, formato_hint="resumo")


def _cinco_dias_atras() -> datetime:
    return datetime.combine(fuso.hoje_local() - timedelta(days=5),
                            datetime.min.time()).replace(hour=3, minute=10)


def _retratos(db, aluno_id):
    return db.execute(select(SnapshotElefante, Importacao.status)
                      .join(Importacao, Importacao.id == SnapshotElefante.importacao_id)
                      .where(SnapshotElefante.aluno_id == aluno_id)
                      .order_by(SnapshotElefante.data_referencia, SnapshotElefante.id)).all()


def _questoes_do_intervalo(db, escola_id, inicio):
    hoje = fuso.hoje_local()
    return rp.gerar(db, escola_id, preset="personalizado", plataformas=("elefante",),
                    inicio=inicio.date(), fim=hoje, hoje=hoje)["elefante"]


def _resolver(cliente, escola_id, rev_id, **corpo):
    r = cliente.post(f"/api/v1/escolas/{escola_id}/importacoes/revisoes/{rev_id}/resolver",
                     json=corpo)
    assert r.status_code == 200, r.text
    return r.json()


def test_contas_em_disputa_numa_coleta_sem_questoes_resolvidas_depois(
        cliente, db, escola_completa, monkeypatch):
    """A5: as duas contas vão para a fila; o gestor liga uma à ficha. O retrato que o
    /resolver grava tem livros novos e as questões HERDADAS da coleta anterior: tem de
    nascer marcado, como o da própria coleta, e o relatório não pode dizer "completa"."""
    sem_disco(monkeypatch)
    esc, t = escola_completa["escola"], escola_completa["turma"]
    ficha = aluno(db, esc.id, t, "Iara Fictoni Modesto", da_lista_piloto=True)
    antes = _cinco_dias_atras()
    manual = Importacao(escola_id=esc.id, usuario_id=None, plataforma="elefante",
                        tipo="pdf", qtd_alunos=1, qtd_erros=0, tempo_ms=0,
                        created_at=antes, status="concluida")
    db.add(manual)
    db.flush()
    db.add(SnapshotElefante(escola_id=esc.id, aluno_id=ficha.id, importacao_id=manual.id,
                            data_referencia=antes, livros_unicos=3, tempo_leitura_min=40,
                            questoes_tentativas=100, questoes_acertos=80, livros_por_nivel={}))
    db.commit()

    res = aplicar(db, esc, _sem_questoes(K, [
        {"studentId": 601, "studentName": "Iara Fictoni Modesto", "totalBooksRead": 5},
        {"studentId": 602, "studentName": "Iara Fictoni Modesto", "totalBooksRead": 5}]))
    assert db.get(Importacao, res["importacao_id"]).status == IMPORTACAO_SEM_QUESTOES
    revs = pendentes(db, esc.id)
    assert sorted(r.id_externo for r in revs) == ["601", "602"]    # nenhuma entrou direto

    rev = next(r for r in revs if r.id_externo == "601")
    _resolver(cliente, esc.id, rev.id, aluno_id=ficha.id)
    db.expire_all()

    ultimo, status = _retratos(db, ficha.id)[-1]
    assert (ultimo.livros_unicos, ultimo.questoes_tentativas) == (5, 100)   # herdadas
    assert status == IMPORTACAO_SEM_QUESTOES

    ele = _questoes_do_intervalo(db, esc.id, antes)
    cob = ele["cobertura_questoes"]
    assert ele["questoes_tentativas"] is None
    assert cob["status"] != "completa"
    assert cob["alunos_questoes_nao_vieram"] == 1


def test_nome_abreviado_numa_coleta_sem_questoes_criado_pela_fila(
        cliente, db, escola_completa, monkeypatch):
    """A2: a conta "IARA F" chega na coleta sem questões e vai para a fila; o gestor cria
    a ficha. O retrato dela (0 questões) nasce marcado; a coleta normal de dias depois traz
    o contador vitalício (500), que não pode virar "500 questões no período"."""
    sem_disco(monkeypatch)
    esc, t = escola_completa["escola"], escola_completa["turma"]
    antes = _cinco_dias_atras()
    aplicar(db, esc, _sem_questoes(K, [
        {"studentId": 701, "studentName": "IARA F", "totalBooksRead": 5}]))
    [rev] = pendentes(db, esc.id, "nome_incompleto")
    _resolver(cliente, esc.id, rev.id, criar_em_turma_id=t.id)
    db.expire_all()
    ficha = dono(db, esc.id, "elefante", "701")
    assert ficha is not None
    [(retrato, status)] = _retratos(db, ficha)
    assert status == IMPORTACAO_SEM_QUESTOES
    retrato.data_referencia = antes        # a coleta sem questões foi há cinco dias
    db.commit()

    aplicar(db, esc, elefante_resumo(K, [
        {"studentId": 701, "studentName": "IARA F", "totalBooksRead": 6,
         "responses": 500, "approvedResponses": 400}]))
    assert [s for _, s in _retratos(db, ficha)] == [IMPORTACAO_SEM_QUESTOES, "concluida"]

    ele = _questoes_do_intervalo(db, esc.id, antes)
    assert ele["questoes_tentativas"] != 500
    assert ele["questoes_tentativas"] is None
    assert ele["cobertura_questoes"]["alunos_questoes_nao_vieram"] == 1


def test_pendencia_de_coleta_normal_resolvida_continua_concluida(
        cliente, db, escola_completa, monkeypatch):
    """O controle: a linha que veio COM as questões não ganha a marca no /resolver."""
    sem_disco(monkeypatch)
    esc, t = escola_completa["escola"], escola_completa["turma"]
    aplicar(db, esc, elefante_resumo(K, [
        {"studentId": 702, "studentName": "ZEFA Q", "totalBooksRead": 2,
         "responses": 30, "approvedResponses": 20}]))
    [rev] = pendentes(db, esc.id, "nome_incompleto")
    _resolver(cliente, esc.id, rev.id, criar_em_turma_id=t.id)
    db.expire_all()
    [(retrato, status)] = _retratos(db, dono(db, esc.id, "elefante", "702"))
    assert (retrato.questoes_tentativas, status) == (30, "concluida")
