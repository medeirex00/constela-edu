"""REV2-ANALISE-2 (revisão do G_GRUPO-4): na MESMA célula, a mesma causa — de 1 a k − 1
crianças com o número — tem o MESMO rótulo, "protegido", em todas as métricas.

Antes, as médias por contribuinte (atividades, livros e minutos por aluno) entravam em
``metricas_protegidas`` e as que somem pela regra do próprio subconjunto (estrelas por aluno
e desempenho do Matific com menos de k crianças com atividade; nível médio do Elefante com
menos de k com livro de nível; acerto nas questões com menos de k com questão) saíam
nulas SEM a marca — e a tela dizia "sem dado" ao lado de "protegido". Com NENHUMA criança no
subconjunto, continua sem a marca (é falta de dado, não proteção).

Dados INVENTADOS. Nenhuma rede externa.
"""
from datetime import datetime

import pytest

from app.services.analise import plataformas as svc
from tests.test_analise_base import (nova_escola, nova_rede, retrato_elefante, retrato_matific,
                                     turma_com_alunos)
from tests.test_aud2_analise_janelas import (API, HOJE, _blocos_da_rede, _login,
                                             _mundo_terceiro_bimestre)

MATIFIC_PELA_REGRA = {"atividades_por_aluno", "estrelas_por_aluno", "desempenho_medio"}
ELEFANTE_PELA_REGRA = {"livros_por_aluno", "nivel_medio", "nivel_medio_posicao"}


@pytest.fixture(autouse=True)
def _hoje(monkeypatch):
    monkeypatch.setattr("app.routers.analise.hoje_br", lambda: HOJE)


def test_terceiro_bimestre_com_uma_crianca_ativa_marca_tudo_como_protegido(db, escola_completa):
    """1 de 6 ativa no 3º bimestre (7 atividades, 19 estrelas, 3 livros de nível Z)."""
    rede, escola = _mundo_terceiro_bimestre(db)
    sec = _login(db, "sec.regra@ficticio.local", cargo="coordenador", rede_id=rede.id)
    b3 = _blocos_da_rede(sec, rede.id, periodo="bimestre_3")
    for nivel in ("celula", "escola", "rede"):
        m, e = b3[nivel]["matific"], b3[nivel]["elefante"]
        assert m["participacao_pct"] == 16.7, (nivel, m)
        for chave in MATIFIC_PELA_REGRA:
            assert m[chave] is None, (nivel, chave, m)
        assert MATIFIC_PELA_REGRA <= set(m["metricas_protegidas"]), (nivel, m)
        for chave in ELEFANTE_PELA_REGRA:
            assert e[chave] is None, (nivel, chave, e)
        assert ELEFANTE_PELA_REGRA <= set(e["metricas_protegidas"]), (nivel, e)
        # O texto diz que é proteção por poucas crianças com o número.
        assert m["texto_metricas_protegidas"] == svc.TEXTO_METRICAS_POUCOS_CONTRIBUINTES.format(
            k=5), (nivel, m)
        # Ninguém com questão: o acerto é falta de dado, sem a marca.
        assert e["taxa_acerto_pct"] is None and "taxa_acerto_pct" not in e["metricas_protegidas"]
    # A coordenação da escola (sem a proteção da rede) recebe o mesmo rótulo na célula.
    coord = _login(db, "coord.regra@ficticio.local", cargo="coordenador", escola_id=escola.id)
    r = coord.get(f"{API}/escolas/{escola.id}/analise", params={"periodo": "bimestre_3"})
    assert r.status_code == 200, r.text
    cel = r.json()["plataformas"]["series"][0]
    assert MATIFIC_PELA_REGRA <= set(cel["matific"]["metricas_protegidas"]), cel["matific"]
    assert ELEFANTE_PELA_REGRA <= set(cel["elefante"]["metricas_protegidas"]), cel["elefante"]


def _mundo_das_questoes(db, com_questao: int):
    """6 crianças com conta no Elefante; ``com_questao`` delas respondem questões entre as
    duas coletas do 3º bimestre."""
    rede = nova_rede(db, nome="Rede Fictícia das Questões", codigo="3599976", codmun="9976")
    escola = nova_escola(db, rede, "EMEF Fictícia das Questões", "35997601")
    alunos = turma_com_alunos(db, escola, "2º Ano", 6)
    for i, a in enumerate(alunos):
        retrato_elefante(db, escola, a, datetime(2026, 8, 3, 3, 10), tentativas=10, acertos=5)
        mais = 12 if i < com_questao else 0
        retrato_elefante(db, escola, a, datetime(2026, 9, 28, 3, 10), tentativas=10 + mais,
                         acertos=5 + mais // 2)
    db.commit()
    return rede


@pytest.mark.parametrize("com_questao, protegido", [(1, True), (4, True), (0, False)])
def test_acerto_com_poucas_criancas_com_questao_e_protegido(db, escola_completa, com_questao,
                                                            protegido):
    rede = _mundo_das_questoes(db, com_questao)
    sec = _login(db, f"sec.questoes{com_questao}@ficticio.local", cargo="coordenador",
                 rede_id=rede.id)
    b3 = _blocos_da_rede(sec, rede.id, periodo="bimestre_3")
    for nivel in ("celula", "escola", "rede"):
        e = b3[nivel]["elefante"]
        assert e["alunos_medidos"] == 6 and e["taxa_acerto_pct"] is None, (nivel, e)
        assert ("taxa_acerto_pct" in e["metricas_protegidas"]) is protegido, (nivel, e)


def test_cinco_criancas_com_questao_mostram_o_acerto(db, escola_completa):
    rede = _mundo_das_questoes(db, 5)
    sec = _login(db, "sec.questoes5@ficticio.local", cargo="coordenador", rede_id=rede.id)
    e = _blocos_da_rede(sec, rede.id, periodo="bimestre_3")["celula"]["elefante"]
    assert e["taxa_acerto_pct"] == 50.0 and e["metricas_protegidas"] == [], e


def test_metricas_sozinhas_marcam_pela_regra_do_subconjunto():
    """As funções de métrica (as mesmas da célula, da escola e da rede)."""
    mat = svc.metricas_matific(svc._Matific(coorte=6, medidos=6, com_atividade=2,
                                            atividades=9.0, estrelas=20.0), 5)
    assert MATIFIC_PELA_REGRA <= set(mat["metricas_protegidas"]), mat
    mat0 = svc.metricas_matific(svc._Matific(coorte=6, medidos=6), 5)
    assert mat0["metricas_protegidas"] == [], mat0
    ele = svc.metricas_elefante(svc._Elefante(coorte=6, medidos=6, alunos_com_nivel=3,
                                              soma_nivel=30.0, livros_com_nivel=3,
                                              alunos_com_questao=2, tentativas=8, acertos=4),
                                5)
    assert {"nivel_medio", "nivel_medio_posicao", "taxa_acerto_pct"} <= set(
        ele["metricas_protegidas"]), ele
    ele0 = svc.metricas_elefante(svc._Elefante(coorte=6, medidos=6), 5)
    assert ele0["metricas_protegidas"] == [], ele0
