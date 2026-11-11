"""O recálculo da escola grava as notas numa ida ao banco, não uma por grupo de crianças.

Toda importação e toda sincronização terminam em ``scoring.recalcular_escola``. Ele
reaproveitava cada ``Nota`` e trocava os atributos um a um; na gravação, o SQLAlchemy
manda um UPDATE para cada sequência de linhas com o MESMO conjunto de colunas
alteradas — e como cada criança muda coisas diferentes (uma só o carimbo, outra a
posição, outra a nota), saíam dezenas de UPDATE: ~98 para 300 crianças, a ~0,2 s cada
em produção, com a trava da escola presa. Agora as linhas que já existem vão num
UPDATE em lote por chave primária (um só comando), e o resultado gravado é o mesmo.

Dados 100% fictícios.
"""
import re
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import sessionmaker

from app.models import (Aluno, Importacao, Matricula, Nota, SnapshotElefante,
                        SnapshotMatific)
from app.services import scoring

N_CRIANCAS = 60


def _retrato(db, escola_id: int) -> dict:
    """Tudo o que o motor grava na Nota."""
    return {
        n.aluno_id: (n.nota_matific, n.nota_elefante, n.nota_matific_institucional,
                     n.nota_elefante_institucional, n.nota_geral, n.posicao,
                     n.aferido_leitura, n.aferido_matematica, n.posicao_leitura,
                     n.posicao_matematica, n.detalhes, n.calculada_em)
        for n in db.execute(select(Nota).where(Nota.escola_id == escola_id)).scalars()
    }


@pytest.fixture()
def escola_grande(db, escola_completa):
    """60 crianças fictícias na turma da escola-base, com as duas plataformas."""
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    quando = datetime(2026, 9, 1, 12, 0)
    alunos = []
    for k in range(N_CRIANCAS):
        aluno = Aluno(escola_id=escola.id, nome=f"Crianca Ficticia Lote {k:02d}")
        db.add(aluno)
        db.flush()
        db.add(Matricula(escola_id=escola.id, aluno_id=aluno.id, turma_id=turma.id,
                         ano_letivo=2026))
        db.add(SnapshotElefante(
            escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
            data_referencia=quando, livros_unicos=k % 9 + 1,
            livros_por_nivel={"D": k % 9 + 1}, tempo_leitura_min=10 + k % 7,
            questoes_tentativas=10, questoes_acertos=k % 10))
        db.add(SnapshotMatific(
            escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
            data_referencia=quando, atividades=k % 11 + 1, estrelas=2 * (k % 11 + 1),
            pontuacao_media=2.0))
        alunos.append(aluno)
    db.commit()
    return {"escola": escola, "alunos": alunos, "importacao": imp, "quando": quando}


def _dia_seguinte(db, cenario) -> None:
    """Uma coleta em que só ALGUMAS crianças mudam, e cada uma de um jeito: é o dia
    comum de sincronização (umas leram, outras fizeram atividade, a maioria nada)."""
    escola, imp = cenario["escola"], cenario["importacao"]
    depois = cenario["quando"] + timedelta(days=1)
    for k, aluno in enumerate(cenario["alunos"]):
        if k % 4 == 1:
            db.add(SnapshotElefante(
                escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                data_referencia=depois, livros_unicos=k % 9 + 3,
                livros_por_nivel={"D": k % 9 + 3}, tempo_leitura_min=20 + k % 7,
                questoes_tentativas=12, questoes_acertos=k % 10 + 1))
        if k % 6 == 2:
            db.add(SnapshotMatific(
                escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                data_referencia=depois, atividades=k % 11 + 4,
                estrelas=2 * (k % 11 + 4), pontuacao_media=2.5))
    db.commit()


class Updates:
    def __init__(self, engine):
        self.engine, self.comandos = engine, []

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._antes)
        return self

    def __exit__(self, *exc):
        event.remove(self.engine, "before_cursor_execute", self._antes)

    def _antes(self, _conn, _cursor, comando, *_a):
        self.comandos.append(" ".join(comando.split()))

    @property
    def de_notas(self) -> int:
        return sum(1 for c in self.comandos if re.match(r"UPDATE notas\b", c, re.I))


def test_recalculo_grava_as_notas_existentes_num_update_so(db, escola_grande):
    escola_id = escola_grande["escola"].id
    scoring.recalcular_escola(db, escola_id)
    antes = _retrato(db, escola_id)
    _dia_seguinte(db, escola_grande)

    with Updates(db.get_bind()) as idas:
        assert scoring.recalcular_escola(db, escola_id) == N_CRIANCAS + 3
    # As linhas que já existem (todas) vão num UPDATE em lote por chave primária.
    assert idas.de_notas <= 1, f"{idas.de_notas} UPDATE de notas para {N_CRIANCAS + 3} crianças"

    db.expire_all()
    depois = _retrato(db, escola_id)
    assert set(depois) == set(antes)
    mudou = [k for k, a in enumerate(escola_grande["alunos"]) if k % 4 == 1]
    assert all(depois[escola_grande["alunos"][k].id][1] != antes[escola_grande["alunos"][k].id][1]
               for k in mudou), "quem leu mais tem a nota de leitura nova"


def test_quem_saiu_perde_a_posicao_no_mesmo_lote(db, escola_grande):
    """A criança transferida não concorre mais: a posição dela some (um UPDATE à parte,
    só das linhas que ainda tinham posição)."""
    escola_id = escola_grande["escola"].id
    scoring.recalcular_escola(db, escola_id)
    saiu = escola_grande["alunos"][7]
    saiu.status = "transferido"
    db.commit()
    with Updates(db.get_bind()) as idas:
        scoring.recalcular_escola(db, escola_id)
    assert idas.de_notas <= 2
    db.expire_all()
    nota = db.execute(select(Nota).where(Nota.aluno_id == saiu.id)).scalar_one()
    assert (nota.posicao, nota.posicao_leitura, nota.posicao_matematica) == (None, None, None)
    # E num recálculo seguinte ela não volta a ser regravada à toa.
    with Updates(db.get_bind()) as idas:
        scoring.recalcular_escola(db, escola_id)
    assert idas.de_notas <= 1


def test_recalculo_sem_commit_deixa_a_sessao_com_as_notas_novas(db, escola_grande):
    """``commit=False`` (o /resolver da revisão): quem continua na mesma transação lê as
    notas novas nos objetos que já tinha carregado, sem reler do banco."""
    escola_id = escola_grande["escola"].id
    scoring.recalcular_escola(db, escola_id)
    _dia_seguinte(db, escola_grande)

    fabrica = sessionmaker(bind=db.get_bind(), autoflush=False, autocommit=False)
    sessao = fabrica()       # como a SessionLocal de produção (sem autoflush)
    try:
        carregadas = {n.aluno_id: n for n in sessao.execute(
            select(Nota).where(Nota.escola_id == escola_id)).scalars()}
        scoring.recalcular_escola(sessao, escola_id, commit=False)
        em_memoria = {a: (n.nota_elefante, n.posicao, n.posicao_leitura, n.detalhes)
                      for a, n in carregadas.items()}
        sessao.commit()
        sessao.expire_all()
        do_banco = {n.aluno_id: (n.nota_elefante, n.posicao, n.posicao_leitura, n.detalhes)
                    for n in sessao.execute(
                        select(Nota).where(Nota.escola_id == escola_id)).scalars()}
    finally:
        sessao.close()
    assert em_memoria == do_banco


def test_resultado_do_lote_e_o_mesmo_do_calculo_linha_a_linha(db, escola_grande):
    """O lote não muda o que é gravado: o retrato bate com o de uma escola recalculada
    do zero (todas as linhas nascendo pelo INSERT)."""
    escola_id = escola_grande["escola"].id
    scoring.recalcular_escola(db, escola_id)
    _dia_seguinte(db, escola_grande)
    instante = datetime(2026, 9, 3, 9, 0)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(scoring, "agora", lambda: instante)
        scoring.recalcular_escola(db, escola_id)      # UPDATE em lote
        db.expire_all()
        pelo_lote = _retrato(db, escola_id)
        db.execute(Nota.__table__.delete().where(Nota.escola_id == escola_id))
        db.commit()
        scoring.recalcular_escola(db, escola_id)      # tudo pelo INSERT
        db.expire_all()
        do_zero = _retrato(db, escola_id)
    assert pelo_lote == do_zero
