"""Escola em que SÓ a Educação Infantil usa a plataforma não entra nas
comparações entre escolas com zero.

O per capita da rede passou a contar só quem concorre (1º–5º ano), então essa
escola tem ``livros_por_matricula = 0`` e fica fora da coorte do índice. Mas o
filtro de entrada do ranking e do painel continuava sendo ``alunos_com_dados >
0``, que conta as Fases: ela aparecia ranqueada em último com "0,0 livros/aluno",
levava o ``gap_indice`` a 1000, o ``escola_menor_indice`` a 0 e entrava no
índice da rede com o peso dos alunos dela. A ausência de quem concorre virava um
zero de desempenho.

A cobertura (``total_alunos``, ``alunos_com_dados``) continua sobre todos os
matriculados — a criança da Fase segue contada como quem usa a plataforma.

E as colunas da aba Leitura falam da MESMA população: ``tempo_premiaveis_min``
(horas lidas só de quem concorre) vai no cartão ao lado de
``livros_premiaveis`` e ``alunos_premiaveis``.
"""
from app.models import Rede
from app.services import rede as svc
from tests.test_rede_percapita_fases import _escola


def _rede_com_escola_so_fase(db):
    rede = Rede(nome="Rede Teste So Fase Ranking", status="ativa")
    db.add(rede)
    db.flush()
    _escola(db, rede, "ESCOLA COM FUNDAMENTAL", fundamental=[(5, 10)], fase=[])
    _escola(db, rede, "ESCOLA SO EMEI USA", fundamental=[], fase=[(30, 20), (20, 10)])
    db.commit()
    return rede


def test_ranking_da_rede_nao_lista_a_escola_so_com_a_fase(db):
    rede = _rede_com_escola_so_fase(db)
    for metrica in ("indice_geral", "livros_aluno", "estrelas_aluno", "engajamento"):
        nomes = [c["nome"] for c in svc.ranking_escolas(db, rede.id, metrica=metrica)]
        assert nomes == ["ESCOLA COM FUNDAMENTAL"], (metrica, nomes)


def test_painel_da_rede_nao_mede_equidade_nem_indice_com_a_ausencia(db):
    rede = _rede_com_escola_so_fase(db)
    painel = svc.dashboard_rede(db, rede.id)
    equidade, totais = painel["equidade"], painel["totais"]
    # Uma só escola comparada: não há distância entre escolas a medir.
    assert equidade["gap_indice"] == 0.0
    assert equidade["escola_menor_indice"] == 1000.0
    assert equidade["escolas_abaixo_do_indice_medio"] == 0
    # O índice da rede é o da escola comparada (antes: (1000·1 + 0·2) ÷ 3).
    assert totais["pontuacao_geral"] == 1000.0
    assert totais["melhor_escola"]["nome"] == "ESCOLA COM FUNDAMENTAL"
    # A cobertura não muda: as duas escolas seguem no painel, as Fases contadas.
    assert {c["nome"] for c in painel["escolas"]} == {"ESCOLA COM FUNDAMENTAL",
                                                      "ESCOLA SO EMEI USA"}
    assert totais["alunos_com_dados"] == 3


def test_melhores_escolas_globais_sem_a_escola_so_com_a_fase(db):
    _rede_com_escola_so_fase(db)
    nomes = [e["nome"] for e in svc.dashboard_global(db)["top_escolas"]]
    assert nomes == ["ESCOLA COM FUNDAMENTAL"]


def test_horas_lidas_de_quem_concorre_vao_no_cartao(db):
    rede = Rede(nome="Rede Teste Horas Premiaveis", status="ativa")
    db.add(rede)
    db.flush()
    # 2 do Fundamental com 10 livros (100 min cada) + 1 da Fase com 50 (500 min).
    _escola(db, rede, "ESCOLA COM EMEI", fundamental=[(10, 40), (10, 40)], fase=[(50, 200)])
    db.commit()
    cartao = svc.ranking_escolas(db, rede.id, metrica="livros_aluno")[0]
    assert cartao["tempo_premiaveis_min"] == 200
    assert cartao["tempo_leitura_min"] == 700         # cobertura: com a Fase
    assert (cartao["alunos_premiaveis"], cartao["livros_premiaveis"]) == (2, 20)
