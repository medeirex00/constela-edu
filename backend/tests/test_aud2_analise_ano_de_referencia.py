"""Análise da rede — o ANO LETIVO DE REFERÊNCIA é decidido pelas escolas EM USO (G_ANALISE-3).

A troca do ano letivo é manual e escola a escola (PATCH /escolas): uma escola fechada ou só
cadastrada (sem aluno nenhum) nunca avança. Antes, o ano da rede era a moda de TODAS as
escolas — e essas escolas paradas decidiam os bimestres da evolução, o rótulo da janela e a
lista ``anos_letivos`` (que bloqueia o "mesmo ano" da relação e do diagnóstico).

O que estes testes sustentam:

* o ano de referência é o mais comum entre as escolas EM USO (ativas e com aluno na coorte);
  sem nenhuma em uso, entre as que têm aluno; sem nenhuma com aluno, entre todas;
* ``anos_letivos`` lista os anos das escolas que têm aluno (as que são medidas): escola sem
  aluno não põe "anos letivos diferentes" na tela; escola com aluno noutro ano põe, porque
  ela é medida no ano dela;
* a ficha da escola (``so_escola``) usa o ano letivo da própria escola;
* a rede num ano só não paga consulta nenhuma a mais (a decisão só lê a coorte quando as
  escolas estão em anos diferentes).

Dados INVENTADOS (``test_analise_base``).
"""
from datetime import date, datetime

from app.services.analise import evolucao as svc_evolucao
from app.services.analise import indicadores as svc_ind
from app.services.analise import plataformas as svc_plat
from tests.test_analise_base import (ler, livros, nova_escola, nova_rede, retrato_elefante,
                                     retrato_matific, turma_com_alunos)

HOJE = date(2026, 10, 5)
HOJE_2027 = date(2027, 10, 5)


def _em_uso(db, rede, nome, ano):
    """Escola ativa, com 8 alunos no ano letivo ``ano`` e uso das plataformas nele."""
    e = nova_escola(db, rede, nome, None, ano=ano)
    alunos = turma_com_alunos(db, e, "3º Ano", 8, ano=ano)
    lv = livros(db, e, 16)
    for i, a in enumerate(alunos):
        retrato_elefante(db, e, a, datetime(ano, 9, 30, 3, 10))
        ler(db, e, a, [lv[2 * i]], datetime(ano, 3, 10, 10, 0))
        ler(db, e, a, [lv[2 * i + 1]], datetime(ano, 9, 10, 10, 0))
        retrato_matific(db, e, a, datetime(ano, 3, 1, 3, 10), atividades=0, estrelas=0)
        retrato_matific(db, e, a, datetime(ano, 9, 30, 3, 10), atividades=10, estrelas=30)
    return e


def _rede_com_escolas_fechadas(db):
    """2 escolas em uso em 2026; 3 escolas INATIVAS, sem aluno, paradas em 2025."""
    rede = nova_rede(db, nome="Rede Fictícia Escolas Fechadas", codigo="3599971")
    ativas = [_em_uso(db, rede, "EMEF Fictícia Em Uso 1", 2026),
              _em_uso(db, rede, "EMEF Fictícia Em Uso 2", 2026)]
    for i in range(3):
        e = nova_escola(db, rede, f"EMEF Fictícia Fechada {i + 1}", None, ano=2025)
        e.status = "inativa"
    db.flush()
    return rede, ativas


def _rede_piloto_2027(db):
    """Virada para 2027: as 2 escolas do piloto avançaram; 3 escolas só cadastradas (ativas
    no cadastro, sem aluno nenhum) ficaram em 2026."""
    rede = nova_rede(db, nome="Rede Fictícia Piloto", codigo="3599972")
    piloto = [_em_uso(db, rede, "EMEF Fictícia Piloto 1", 2027),
              _em_uso(db, rede, "EMEF Fictícia Piloto 2", 2027)]
    for i in range(3):
        nova_escola(db, rede, f"EMEF Fictícia Só Cadastro {i + 1}", None, ano=2026)
    db.flush()
    return rede, piloto


def test_escolas_fechadas_sem_aluno_nao_decidem_o_ano_da_rede(db):
    rede, _ = _rede_com_escolas_fechadas(db)
    evo = svc_evolucao.evolucao(db, rede, hoje=HOJE)
    assert evo["ano_letivo"] == 2026
    assert [b["inicio"] for b in evo["bimestres"]] == ["2026-02-02", "2026-04-23",
                                                       "2026-07-24", "2026-10-05"]
    janela = svc_plat.plataformas_da_rede(db, rede, hoje=HOJE)["janela"]
    assert (janela["ano_letivo"], janela["anos_letivos"]) == (2026, [2026])
    assert janela["rotulo"] == "Ano letivo 2026"
    assert janela["inicio"].startswith("2026")


def test_virada_escolas_so_cadastradas_nao_prendem_a_rede_no_ano_velho(db):
    rede, _ = _rede_piloto_2027(db)
    evo = svc_evolucao.evolucao(db, rede, hoje=HOJE_2027)
    assert evo["ano_letivo"] == 2027
    assert evo["bimestres"] and all(b["inicio"].startswith("2027") for b in evo["bimestres"])
    # O 1º bimestre de 2027 (as leituras de março) tem participação medida; nenhum
    # bimestre de 2026 aparece com 0,0%.
    primeiro = evo["bimestres"][0]["rede"]["elefante"]
    assert primeiro["participacao_pct"] == 100.0
    p = svc_plat.plataformas_da_rede(db, rede, hoje=HOJE_2027)
    assert (p["janela"]["ano_letivo"], p["janela"]["anos_letivos"]) == (2027, [2027])
    assert not any("anos letivos diferentes" in t for t in p["limitacoes"])


def test_relacao_e_diagnostico_recebem_um_ano_so(db):
    """``celulas_da_rede`` (a relação e o diagnóstico leem ``anos_letivos`` dela): as escolas
    sem aluno não tiram a rede do "mesmo ano"."""
    rede, _ = _rede_com_escolas_fechadas(db)
    cel = svc_plat.celulas_da_rede(db, rede, preset="ano_letivo", inicio=None, fim=None,
                                   hoje=HOJE)
    assert (cel["ano_letivo"], cel["anos_letivos"]) == (2026, [2026])
    from app.services.analise import relacao as svc_relacao
    assert svc_relacao._sobrepoe(cel["janela"], 2026, cel["anos_letivos"])


def test_escola_inativa_com_aluno_noutro_ano_continua_avisada(db):
    """Escola inativa que ainda tem aluno na coorte é medida no ano dela: não decide o ano da
    rede, mas o aviso de anos letivos diferentes continua (o dado dela é de outro ano)."""
    rede, _ = _rede_com_escolas_fechadas(db)
    velha = _em_uso(db, rede, "EMEF Fictícia Fechada Com Alunos", 2025)
    velha.status = "inativa"
    db.flush()
    p = svc_plat.plataformas_da_rede(db, rede, hoje=HOJE)
    assert (p["janela"]["ano_letivo"], p["janela"]["anos_letivos"]) == (2026, [2025, 2026])
    assert svc_evolucao.evolucao(db, rede, hoje=HOJE)["ano_letivo"] == 2026


def test_sem_nenhuma_escola_em_uso_vale_a_moda_de_todas(db):
    rede = nova_rede(db, nome="Rede Fictícia Vazia", codigo="3599973")
    for i, ano in enumerate((2026, 2026, 2027)):
        nova_escola(db, rede, f"EMEF Fictícia Vazia {i + 1}", None, ano=ano)
    db.flush()
    assert svc_evolucao.evolucao(db, rede, hoje=HOJE)["ano_letivo"] == 2026
    janela = svc_plat.plataformas_da_rede(db, rede, hoje=HOJE)["janela"]
    assert (janela["ano_letivo"], janela["anos_letivos"]) == (2026, [2026, 2027])


def test_ficha_da_escola_usa_o_ano_da_propria_escola(db):
    """A ficha (``so_escola``) de uma escola que já virou para 2027 numa rede ainda em 2026
    mostra os bimestres de 2027."""
    rede = nova_rede(db, nome="Rede Fictícia Ficha", codigo="3599974")
    for i in range(2):
        _em_uso(db, rede, f"EMEF Fictícia Ainda 2026 {i + 1}", 2026)
    adiantada = _em_uso(db, rede, "EMEF Fictícia Já 2027", 2027)
    db.flush()
    rede_evo = svc_evolucao.evolucao(db, rede, hoje=HOJE_2027)
    assert rede_evo["ano_letivo"] == 2026
    ficha = svc_evolucao.evolucao(db, rede, escola_id=adiantada.id, so_escola=True,
                                  hoje=HOJE_2027)
    assert ficha["ano_letivo"] == 2027
    assert ficha["bimestres"] and all(b["inicio"].startswith("2027")
                                      for b in ficha["bimestres"])
    (escola,) = ficha["bimestres"][0]["escolas"]
    assert escola["elefante"]["participacao_pct"] == 100.0


def test_alerta_do_catalogo_fala_do_ano_das_escolas_em_uso(db):
    rede, _ = _rede_com_escolas_fechadas(db)
    textos = [a["texto"] for a in svc_ind.catalogo(db, rede)["alertas"]
              if a["tipo"] == "metodologia"]
    assert any("ano letivo 2026" in t for t in textos), textos
    assert not any("ano letivo 2025" in t for t in textos), textos
