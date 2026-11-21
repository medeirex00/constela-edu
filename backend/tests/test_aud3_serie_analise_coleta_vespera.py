"""S_G_ANALISE-1 — Análise Educacional: a coleta do Elefante feita na NOITE da véspera do
período (21h–23h59 de Brasília, já o dia seguinte em UTC) não conta como coleta do período.

A última coleta (``data_referencia``) é gravada em UTC sem fuso; o início do período é um
dia de Brasília. Comparar os dois sem converter fazia a coleta de 31/10 às 22h30 de
Brasília (01/11 01:30 UTC) passar por coleta de novembro: a escola saía "ok" com
participação 0,0% (um zero que é falta de dado) e esse zero entrava na soma da rede.

Mundo FICTÍCIO: rede, escolas e crianças inventadas.
"""
from datetime import date, datetime

from app.services.analise import evolucao as evo
from app.services.analise import plataformas as plat
from tests.test_analise_base import nova_escola, nova_rede, retrato_elefante, turma_com_alunos


def _duas_escolas(db, *, noite: datetime, tarde: datetime):
    """Duas escolas com 6 crianças do 3º ano; cada uma com UMA coleta do Elefante (UTC)."""
    rede = nova_rede(db, nome="Rede Fictícia da Véspera", codigo="3599962")
    e_noite = nova_escola(db, rede, "EMEF Fictícia Coleta da Noite", None)
    e_tarde = nova_escola(db, rede, "EMEF Fictícia Coleta da Tarde", None)
    for a in turma_com_alunos(db, e_noite, "3º Ano", 6):
        retrato_elefante(db, e_noite, a, noite)
    for a in turma_com_alunos(db, e_tarde, "3º Ano", 6):
        retrato_elefante(db, e_tarde, a, tarde)
    db.flush()
    return rede, e_noite, e_tarde


def test_coleta_da_vespera_depois_das_21h_nao_conta_como_coleta_do_mes(db):
    # 31/10 às 22h30 de Brasília = 01/11 01:30 UTC; 31/10 às 19h30 = 31/10 22:30 UTC.
    rede, noite, tarde = _duas_escolas(db, noite=datetime(2026, 11, 1, 1, 30),
                                       tarde=datetime(2026, 10, 31, 22, 30))
    r = plat.plataformas_da_rede(db, rede, preset="mes", hoje=date(2026, 11, 3))
    assert r["janela"]["inicio"] == "2026-11-01"
    por_id = {e["escola_id"]: e for e in r["escolas"]}
    assert por_id[noite.id]["ultima_coleta"]["elefante"].startswith("2026-10-31T22:30")
    for escola in (noite, tarde):
        item = por_id[escola.id]
        assert item["cobertura"]["elefante"] == plat.SEM_COLETA_NO_PERIODO, (
            escola.nome, item["cobertura"]["elefante"])
        bloco = item.get("elefante") or {}
        assert bloco.get("participacao_pct") is None
        assert bloco.get("livros_por_aluno") is None
    # Nenhuma das duas entra na soma da rede: não há zero de "falta de dado" lá.
    assert r["rede"]["escolas_com_dado"]["elefante"] == 0
    rede_ele = r["rede"].get("elefante") or {}
    assert rede_ele.get("participacao_pct") is None


def test_coleta_depois_da_meia_noite_de_brasilia_conta(db):
    """Controle: a coleta de 01/11 às 00h30 de Brasília (03:30 UTC) é do período."""
    rede, noite, _ = _duas_escolas(db, noite=datetime(2026, 11, 1, 3, 30),
                                   tarde=datetime(2026, 10, 31, 22, 30))
    r = plat.plataformas_da_rede(db, rede, preset="mes", hoje=date(2026, 11, 3))
    por_id = {e["escola_id"]: e for e in r["escolas"]}
    assert por_id[noite.id]["cobertura"]["elefante"] == plat.COBERTURA_OK


def test_ficha_da_escola_nao_conta_a_coleta_da_vespera(db):
    rede, noite, _ = _duas_escolas(db, noite=datetime(2026, 11, 1, 1, 30),
                                   tarde=datetime(2026, 10, 31, 22, 30))
    for escopo_rede in (True, False):        # a Secretaria e a coordenação da escola
        r = plat.plataformas_da_escola(db, noite, preset="mes", hoje=date(2026, 11, 3),
                                       escopo_rede=escopo_rede)
        assert r["cobertura"]["elefante"] == plat.SEM_COLETA_NO_PERIODO, escopo_rede
        assert (r.get("elefante") or {}).get("participacao_pct") is None


def test_evolucao_por_bimestre_na_borda_do_4o_bimestre(db):
    """O 4º bimestre de 2026 começa em 05/10. A coleta de 04/10 às 22h30 de Brasília
    (05/10 01:30 UTC) é do 3º bimestre, não do 4º."""
    rede, noite, tarde = _duas_escolas(db, noite=datetime(2026, 10, 5, 1, 30),
                                       tarde=datetime(2026, 10, 4, 22, 30))
    r = evo.evolucao(db, rede, hoje=date(2026, 10, 8))
    por_numero = {b["numero"]: b for b in r["bimestres"]}
    assert 4 in por_numero and 3 in por_numero
    quarto = {e["id"]: e for e in por_numero[4]["escolas"]}
    terceiro = {e["id"]: e for e in por_numero[3]["escolas"]}
    for escola in (noite, tarde):
        assert quarto[escola.id]["cobertura"]["elefante"] == plat.SEM_COLETA_NO_PERIODO, (
            escola.nome, quarto[escola.id]["cobertura"]["elefante"])
        assert terceiro[escola.id]["cobertura"]["elefante"] != plat.SEM_COLETA_NO_PERIODO
