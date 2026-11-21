"""REV2-ANALISE-3 (revisão do G_GRUPO-2): o texto da média escondida pela proteção por
blocos do calendário vale para o que de fato a escondeu.

O bloco que esconde pode ser um bimestre, a FOLGA entre bimestres (janeiro, antes do 1º) ou o
RESTO da conta que nenhum bimestre mede (a primeira coleta de quem chega no meio do ano).
Antes, o texto dizia sempre "num dos bimestres dele, menos de 5 alunos têm esse número" —
quem conferia os bimestres na tela não achava o bimestre citado (todos mostravam o número ou
não tinham ninguém ativo).

Dados INVENTADOS. Nenhuma rede externa.
"""
from datetime import datetime

import pytest

from app.services.analise import plataformas as svc
from tests.test_analise_base import nova_escola, nova_rede, retrato_matific, turma_com_alunos
from tests.test_aud2_analise_janelas import HOJE, _blocos_da_rede, _login

PARTES = ("um bimestre", "os dias fora dos bimestres", "o que só o período inteiro conta")


@pytest.fixture(autouse=True)
def _hoje(monkeypatch):
    monkeypatch.setattr("app.routers.analise.hoje_br", lambda: HOJE)


def _mundo_da_folga(db):
    """A ALVO só usa o Matific em janeiro (antes do 1º bimestre); as outras 5, nos bimestres."""
    rede = nova_rede(db, nome="Rede Fictícia do Texto da Folga", codigo="3599975", codmun="9975")
    escola = nova_escola(db, rede, "EMEF Fictícia do Texto da Folga", "35997501")
    alunos = turma_com_alunos(db, escola, "4º Ano", 6)
    alvo, outros = alunos[5], alunos[:5]
    for a in outros:
        retrato_matific(db, escola, a, datetime(2026, 1, 20, 3, 20), atividades=0, estrelas=0)
        retrato_matific(db, escola, a, datetime(2026, 3, 2, 3, 20), atividades=10, estrelas=30)
        retrato_matific(db, escola, a, datetime(2026, 6, 1, 3, 20), atividades=20, estrelas=60)
        retrato_matific(db, escola, a, datetime(2026, 10, 1, 3, 20), atividades=20, estrelas=60)
    for quando in (datetime(2026, 1, 20, 3, 20), datetime(2026, 3, 2, 3, 20),
                   datetime(2026, 6, 1, 3, 20), datetime(2026, 10, 1, 3, 20)):
        retrato_matific(db, escola, alvo, quando, atividades=5, estrelas=12)
    db.commit()
    return rede


def _mundo_da_chegada(db):
    """A ALVO entra no Matific em setembro com o contador do ano já em 7 atividades."""
    rede = nova_rede(db, nome="Rede Fictícia do Texto da Chegada", codigo="3599974",
                     codmun="9974")
    escola = nova_escola(db, rede, "EMEF Fictícia do Texto da Chegada", "35997401")
    alunos = turma_com_alunos(db, escola, "5º Ano", 6)
    alvo, outros = alunos[5], alunos[:5]
    for a in outros:
        retrato_matific(db, escola, a, datetime(2026, 3, 2, 3, 20), atividades=0, estrelas=0)
        retrato_matific(db, escola, a, datetime(2026, 6, 1, 3, 20), atividades=10, estrelas=30)
        retrato_matific(db, escola, a, datetime(2026, 9, 1, 3, 20), atividades=20, estrelas=60)
        retrato_matific(db, escola, a, datetime(2026, 10, 1, 3, 20), atividades=30, estrelas=90)
    retrato_matific(db, escola, alvo, datetime(2026, 9, 1, 3, 20), atividades=7, estrelas=19)
    retrato_matific(db, escola, alvo, datetime(2026, 10, 1, 3, 20), atividades=7, estrelas=19)
    db.commit()
    return rede


@pytest.mark.parametrize("mundo", [_mundo_da_folga, _mundo_da_chegada])
def test_o_texto_nao_cita_um_bimestre_que_mostra_o_numero(db, escola_completa, mundo):
    rede = mundo(db)
    sec = _login(db, f"sec.texto.{mundo.__name__}@ficticio.local", cargo="coordenador",
                 rede_id=rede.id)
    # Nenhum bimestre esconde as estrelas COM crianças dentro: cada um as mostra ou não tem
    # ninguém com atividade.
    for n in (1, 2, 3, 4):
        m = _blocos_da_rede(sec, rede.id, periodo=f"bimestre_{n}")["celula"]["matific"]
        assert "estrelas_por_aluno" not in m["metricas_protegidas"], (n, m)
    ano = _blocos_da_rede(sec, rede.id, periodo="ano_letivo")
    for nivel in ("celula", "escola", "rede"):
        m = ano[nivel]["matific"]
        assert "estrelas_por_aluno" in m["metricas_protegidas"], (nivel, m)
        texto = m["texto_metricas_protegidas"]
        assert "num dos bimestres" not in texto, (nivel, texto)
        for parte in PARTES:
            assert parte in texto, (nivel, parte, texto)


def test_os_textos_de_mais_de_um_motivo_tambem_dizem_a_parte_do_periodo():
    for texto in (svc.TEXTO_METRICAS_PROTEGIDAS_BLOCOS, svc.TEXTO_METRICAS_PROTEGIDAS_AMBOS,
                  svc.TEXTO_METRICAS_PROTEGIDAS_VARIOS):
        corpo = texto.format(k=5)
        assert "num dos bimestres" not in corpo and "dos bimestres do período" not in corpo, corpo
        for parte in PARTES:
            assert parte in corpo, (parte, corpo)
