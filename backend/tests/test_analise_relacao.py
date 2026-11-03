"""Análise educacional — a RELAÇÃO entre um indicador oficial por escola e uma métrica das
plataformas (``GET /redes/{id}/analise/relacao``).

Cada critério de ``docs/analise/METODOLOGIA.md`` tem a sua recusa testada (ICA por
escola, só estimativa, só número sem registro, série incompatível, componente
incompatível, período sem sobreposição, n < 8, célula pequena, sem variância) e cada
exclusão por escola tem o seu motivo próprio, também quando um motivo geral bloqueia a
relação (média instável, IEE com TPS = 0, número sem registro, coleta parcial, questões de
outro ano letivo) — e há UM caso calculável, com dados
sintéticos do MESMO ano letivo (SARESP 2026 inventado × Elefante 2026), em que o Spearman
com empates é conferido À MÃO (postos escritos no teste). Os pares "lado a lado" vêm
sempre, com o ano de cada lado.

Dados INVENTADOS (decisão D13): na rede de verdade não existe SARESP 2026 — este é só o
cenário de teste do cálculo.
"""
from datetime import datetime
from math import atanh, sqrt, tanh

import pytest
from sqlalchemy import update

from app.models import IndicadorReferencia, ResultadoAvaliacao, SnapshotElefante
from app.services.analise import relacao as svc
from tests.test_analise_base import (HOJE, importacao, ler, livros, mundo_plataformas,
                                     nova_escola, nova_rede, resultado, retrato_elefante,
                                     saresp_oficial, turma_com_alunos)

URL = "/api/v1/redes/{rede}/analise/relacao"
MUN_CORRELATO = "3599907"
# Livros novos por aluno (Elefante, 5º ano, 2026) e SARESP 2026 do 5º ano em LP, por
# escola — com EMPATES dos dois lados (2 e 2; 6 e 6; 190 e 190).
X_LIVROS = [1, 2, 2, 3, 4, 5, 6, 6, 7]
Y_SARESP = [180.0, 185.0, 190.0, 190.0, 200.0, 195.0, 210.0, 205.0, 215.0]


@pytest.fixture(autouse=True)
def _hoje(monkeypatch):
    monkeypatch.setattr("app.routers.analise.hoje_br", lambda: HOJE)


def mundo_correlato(db, *, alunos: dict[int, int] | None = None, y=Y_SARESP) -> dict:
    """9 escolas do 5º ano (6 crianças cada), com o SARESP 2026 oficial (inventado) e os
    livros novos de 2026 no Elefante."""
    rede = nova_rede(db, nome="Rede Fictícia Correlata", codigo=MUN_CORRELATO, codmun="9997")
    imp = importacao(db, "iee", "seduc_iee", 2026, alvo=MUN_CORRELATO)
    escolas = []
    for i, (x, yv) in enumerate(zip(X_LIVROS, y), start=1):
        e = nova_escola(db, rede, f"EMEF Correlata {i:02d}", f"3599{7000 + i}")
        lv = livros(db, e, 7, "K")
        for a in turma_com_alunos(db, e, "5º Ano", (alunos or {}).get(i, 6)):
            ler(db, e, a, lv[:x], datetime(2026, 6, 1, 10, 0))
            retrato_elefante(db, e, a, datetime(2026, 9, 30, 3, 0))
        saresp_oficial(db, imp, e, 2026, lp5=yv, mt5=yv + 10, iee=4.0 + i / 10, meta=5.0,
                       icm=0, codigo=MUN_CORRELATO)
        escolas.append(e)
    db.commit()
    return {"rede": rede, "escolas": escolas, "imp": imp}


def _rel(cliente, rede, **params):
    r = cliente.get(URL.format(rede=rede.id), params=params)
    assert r.status_code == 200, r.text
    return r.json()


_SARESP_LP = {"indicador": "saresp", "etapa": "5_ano", "componente": "lp", "edicao": 2026,
              "metrica": "livros_por_aluno"}


# --- O caso calculável --------------------------------------------------------------

def test_spearman_com_empates_conferido_a_mao(db, cliente_global):
    m = mundo_correlato(db)
    dados = _rel(cliente_global, m["rede"], **_SARESP_LP)
    assert dados["calculavel"] is True and dados["motivos"] == [] and dados["n"] == 9
    pares = dados["pares"]
    assert [p["nome"] for p in pares] == [f"EMEF Correlata {i:02d}" for i in range(1, 10)]
    assert [p["valor_plataforma"] for p in pares] == [float(x) for x in X_LIVROS]
    assert [p["valor_oficial"] for p in pares] == Y_SARESP
    assert all(p["incluido"] and p["edicao"] == 2026 and p["janela"] == "2026" for p in pares)
    # Postos À MÃO (empate = posto médio):
    #   x = 1, 2, 2, 3, 4, 5, 6, 6, 7          → 1, 2,5, 2,5, 4, 5, 6, 7,5, 7,5, 9
    #   y = 180, 185, 190, 190, 200, 195, 210, 205, 215 → 1, 2, 3,5, 3,5, 6, 5, 8, 7, 9
    rx = [1, 2.5, 2.5, 4, 5, 6, 7.5, 7.5, 9]
    ry = [1, 2, 3.5, 3.5, 6, 5, 8, 7, 9]
    assert svc.postos([float(x) for x in X_LIVROS]) == rx and svc.postos(Y_SARESP) == ry
    # Médias 5 e 5: Σdx·dy = 57,25; Σdx² = 59; Σdy² = 59,5.
    rho = 57.25 / sqrt(59 * 59.5)
    assert dados["coeficiente"] == round(rho, 3) == 0.966
    # IC 95%: Fisher z com EP = 1,06/√(n−3).
    z, ep = atanh(round(rho, 3)), 1.06 / sqrt(9 - 3)
    assert dados["ic95"]["inferior"] == round(tanh(z - 1.96 * ep), 3)
    assert dados["ic95"]["superior"] == round(tanh(z + 1.96 * ep), 3)
    assert dados["ic95"]["inferior"] > 0                 # o intervalo não inclui o zero
    assert "não é causalidade" in " ".join(dados["avisos"])
    # O aviso vai UMA vez (em avisos), não repetido na interpretação.
    assert "causalidade" not in dados["interpretacao"]
    assert "Spearman" in dados["metodologia"] and dados["criterios"]["n_minimo"] == 8
    # A metodologia é legível na tela: sem caminho de arquivo; o rótulo, sem "retrato".
    assert "docs/" not in dados["metodologia"] and ".md" not in dados["metodologia"]
    assert not any("retrato" in m["rotulo"] for m in dados["metricas_disponiveis"])
    assert dados["criterios"]["k_minimo_alunos"] == 5 and dados["criterios"]["so_oficial"] is True


def test_ideb_ou_iee_usa_a_escola_inteira_e_avisa_que_junta_os_componentes(db, cliente_global):
    m = mundo_correlato(db)
    dados = _rel(cliente_global, m["rede"], indicador="iee", edicao=2026,
                 metrica="livros_por_aluno")
    assert dados["calculavel"] is True and dados["n"] == 9
    assert dados["filtros"]["etapa"] == "anos_iniciais" and dados["filtros"]["componente"] is None
    assert any("junta Língua Portuguesa e Matemática" in a for a in dados["avisos"])
    # O IEE cresce com a escola e os livros também (com empates): associação positiva.
    assert dados["coeficiente"] > 0.9


# --- Cada recusa ----------------------------------------------------------------------

def test_sem_sobreposicao_de_ano_mostra_os_pares_lado_a_lado(db, cliente_global):
    mundo = mundo_plataformas(db)
    dados = _rel(cliente_global, mundo["rede"], indicador="saresp", componente="mt",
                 metrica="estrelas_por_aluno")
    assert dados["calculavel"] is False
    assert dados["motivos"] == ["periodo_sem_sobreposicao"]
    assert "2025" in dados["textos"][0] and "2026" in dados["textos"][0]
    # O rótulo do período já traz o ano: ele não se repete entre parênteses.
    assert dados["textos"][0].count("2026") == 1
    assert dados["filtros"]["edicao"] == 2025 and dados["n"] == 0
    beta = next(p for p in dados["pares"] if p["escola_id"] == mundo["escolas"]["beta"].id)
    # Lado a lado, com o ano de cada lado: SARESP 2025 × Matific 2026.
    assert (beta["valor_oficial"], beta["edicao"]) == (199.0, 2025)
    assert (beta["valor_plataforma"], beta["janela"]) == (12.0, "2026")
    assert beta["incluido"] is False
    # Na mesma rede correlata, um período de 2025 contra o SARESP 2026 também é recusado.
    m = mundo_correlato(db)
    outro = _rel(cliente_global, m["rede"], **_SARESP_LP, periodo="personalizado",
                 inicio="2025-03-01", fim="2025-11-30")
    assert outro["motivos"] == ["periodo_sem_sobreposicao"] and outro["coeficiente"] is None


def test_cada_par_diz_o_motivo_proprio_mesmo_com_bloqueio_geral(db, cliente_global):
    """R6: com a relação bloqueada (período sem sobreposição), o lado a lado não repete o
    texto geral em cada escola: cada uma diz o PRÓPRIO motivo — o que responde "quais
    escolas teriam dados suficientes para uma comparação válida"."""
    mundo = mundo_plataformas(db)
    esc = mundo["escolas"]
    dados = _rel(cliente_global, mundo["rede"], indicador="saresp", componente="mt",
                 metrica="estrelas_por_aluno")
    geral = dados["textos"][0]
    pares = {p["escola_id"]: p for p in dados["pares"]}
    assert all(p["incluido"] is False and p["motivo_exclusao"] != geral for p in pares.values())
    assert "média instável" in pares[esc["beta"].id]["motivo_escola"]          # TPS = 0
    assert "célula suprimida" in pares[esc["alfa"].id]["motivo_escola"]        # 5º ano
    assert pares[esc["delta"].id]["motivo_escola"].startswith("sem resultado oficial")
    assert pares[esc["gama"].id]["motivo_escola"].startswith("sem resultado oficial")
    assert "não tem alunos desta série" in pares[esc["ebano"].id]["motivo_escola"]
    # Escola sem motivo próprio fica de fora só pelo geral (o texto dele não se repete).
    m = mundo_correlato(db)
    outro = _rel(cliente_global, m["rede"], **_SARESP_LP, periodo="personalizado",
                 inicio="2025-03-01", fim="2025-11-30")
    assert outro["motivos"] == ["periodo_sem_sobreposicao"]
    assert {p["motivo_escola"] for p in outro["pares"]} != {outro["textos"][0]}
    for p in outro["pares"]:
        assert p["incluido"] is False and p["motivo_exclusao"] != outro["textos"][0]
        if p["motivo_escola"] is None:
            assert p["motivo_exclusao"] == svc.FORA_PELO_MOTIVO_GERAL


def test_numero_sem_registro_fica_fora_com_motivo_proprio(db, cliente_global):
    """RD2: o Ideb 2023 da Delta foi gravado antes, sem o registro do arquivo oficial. Na
    relação, o par fica sem ``valor_oficial`` e com o motivo "sem registro oficial"."""
    mundo = mundo_plataformas(db)
    dados = _rel(cliente_global, mundo["rede"], indicador="ideb", edicao=2023,
                 metrica="livros_por_aluno")
    delta = next(p for p in dados["pares"] if p["escola_id"] == mundo["escolas"]["delta"].id)
    assert delta["valor_oficial"] is None and delta["incluido"] is False
    assert delta["motivo_escola"].startswith("sem registro oficial")
    assert "estimativa" not in delta["motivo_escola"].lower()
    alfa = next(p for p in dados["pares"] if p["escola_id"] == mundo["escolas"]["alfa"].id)
    assert alfa["valor_oficial"] == 6.3


def test_iee_com_tps_zero_fica_fora_da_relacao(db, cliente_global):
    """M8: o IEE da escola 05 foi calculado com médias de TPS = 0 — fora do par, com o
    motivo, como a média instável do SARESP (antes entrava no Spearman)."""
    m = mundo_correlato(db)
    alvo = m["escolas"][4]
    db.execute(update(IndicadorReferencia).where(
        IndicadorReferencia.codigo_inep == alvo.codigo_inep,
        IndicadorReferencia.indicador == "tps").values(valor=0.0))
    db.commit()
    dados = _rel(cliente_global, m["rede"], indicador="iee", edicao=2026,
                 metrica="livros_por_aluno")
    par = next(p for p in dados["pares"] if p["escola_id"] == alvo.id)
    assert par["incluido"] is False and "TPS = 0" in par["motivo_escola"]
    assert dados["calculavel"] is True and dados["n"] == 8


def test_coleta_parcial_fica_fora_da_relacao(db, cliente_global):
    """M5: a escola 03 parou de coletar em 01/08 (antes do fim do período, com mais de 7
    dias): os números dela valem só até lá — fora do par, com o motivo."""
    m = mundo_correlato(db)
    alvo = m["escolas"][2]
    db.execute(update(SnapshotElefante).where(SnapshotElefante.escola_id == alvo.id)
               .values(data_referencia=datetime(2026, 8, 1, 3, 0)))
    db.commit()
    dados = _rel(cliente_global, m["rede"], **_SARESP_LP)
    par = next(p for p in dados["pares"] if p["escola_id"] == alvo.id)
    assert par["incluido"] is False and par["motivo_escola"].startswith("coleta parcial")
    assert "01/08/2026" in par["motivo_escola"]
    assert dados["calculavel"] is True and dados["n"] == 8


def test_acerto_com_coleta_de_outro_ano_letivo_fica_fora(db, cliente_global):
    """M10: na métrica de acerto, a janela das questões da escola 01 começa numa coleta de
    20/12/2025 — o ganho mistura questões de outro ano letivo. A escola 02 (coletas só de
    2026) não tem esse motivo."""
    m = mundo_correlato(db)
    e1, e2 = m["escolas"][0], m["escolas"][1]
    from app.models import Matricula
    for escola, base in ((e1, datetime(2025, 12, 20, 3, 0)), (e2, datetime(2026, 3, 1, 3, 0))):
        alunos = [mt.aluno for mt in db.query(Matricula).filter(Matricula.escola_id == escola.id)]
        for a in alunos:
            retrato_elefante(db, escola, a, base)
            retrato_elefante(db, escola, a, datetime(2026, 10, 1, 3, 0), tentativas=10,
                             acertos=5)
    db.commit()
    dados = _rel(cliente_global, m["rede"], **{**_SARESP_LP, "metrica": "taxa_acerto"})
    pares = {p["escola_id"]: p for p in dados["pares"]}
    assert pares[e1.id]["valor_plataforma"] == 50.0
    assert pares[e1.id]["motivo_escola"] == (
        "as questões contam desde uma coleta de outro ano letivo")
    assert pares[e2.id]["motivo_escola"] is None and pares[e2.id]["incluido"] is True


def test_n_menor_que_8_escolas(db, cliente_global):
    m = mundo_correlato(db)
    for escola in m["escolas"][:2]:
        db.execute(update(ResultadoAvaliacao).where(
            ResultadoAvaliacao.escola_id == escola.id,
            ResultadoAvaliacao.etapa == "5_ano", ResultadoAvaliacao.componente == "portugues"
        ).values(valor=None, motivo_ausencia="nao_divulgado"))
    db.commit()
    dados = _rel(cliente_global, m["rede"], **_SARESP_LP)
    assert dados["calculavel"] is False and dados["motivos"] == ["n_insuficiente"]
    assert "7 escola(s)" in dados["textos"][0] and dados["coeficiente"] is None
    fora = [p for p in dados["pares"] if not p["incluido"]]
    assert len(fora) == 2 and all("sem resultado oficial" in p["motivo_exclusao"] for p in fora)
    assert all(p["valor_oficial"] is None for p in fora)        # ausência, nunca 0


def test_celula_com_menos_de_k_alunos_fica_fora(db, cliente_global):
    """A escola 01 tem 4 crianças (< 5): suprimida — e a menor visível some junto
    (supressão complementar), o que derruba o n para 7."""
    m = mundo_correlato(db, alunos={1: 4})
    dados = _rel(cliente_global, m["rede"], **_SARESP_LP)
    assert dados["motivos"] == ["n_insuficiente"]
    fora = [p for p in dados["pares"] if not p["incluido"]]
    assert [p["nome"] for p in fora] == ["EMEF Correlata 01", "EMEF Correlata 02"]
    assert all(p["valor_plataforma"] is None and "célula suprimida" in p["motivo_exclusao"]
               for p in fora)


def test_ica_nao_existe_por_escola(db, cliente_global):
    m = mundo_correlato(db)
    dados = _rel(cliente_global, m["rede"], indicador="ica")
    assert dados["calculavel"] is False and dados["motivos"] == ["indicador_so_da_rede"]
    assert "não publica o ICA por escola" in dados["textos"][0] and dados["pares"] == []


def test_serie_incompativel(db, cliente_global):
    m = mundo_correlato(db)
    dados = _rel(cliente_global, m["rede"], **_SARESP_LP, serie=3)
    assert dados["calculavel"] is False and dados["motivos"] == ["serie_incompativel"]
    assert len(dados["pares"]) == 9 and not any(p["incluido"] for p in dados["pares"])
    # O IEE (anos iniciais) só se relaciona com a escola inteira: série nenhuma.
    iee = _rel(cliente_global, m["rede"], indicador="iee", edicao=2026, serie=5)
    assert iee["motivos"] == ["serie_incompativel"]


def test_so_estimativa_e_so_sem_registro(db, cliente_global):
    m = mundo_correlato(db)
    # A "Estimativa Constela" nunca entra em associação.
    est = _rel(cliente_global, m["rede"], indicador="crianca_alfabetizada")
    assert est["motivos"] == ["so_estimativa"] and est["indicador"]["oficial"] is False
    assert "não é o indicador oficial" in est["indicador"]["nome"]
    # Saeb 2026 só com números gravados antes, sem o registro do arquivo (1 clique) —
    # nenhum oficial; e eles NÃO são chamados de estimativa.
    for e in m["escolas"]:
        resultado(db, "saeb", e, edicao=2026, indicador="proficiencia", etapa="5_ano",
                  componente="portugues", valor=200.0 + e.id % 7, imp=None,
                  unidade="escala_saeb")
    db.commit()
    saeb = _rel(cliente_global, m["rede"], indicador="saeb", edicao=2026,
                metrica="livros_por_aluno")
    assert saeb["calculavel"] is False and saeb["motivos"] == ["so_sem_registro"]
    assert "estimativa" not in saeb["textos"][0].lower()
    assert all(p["valor_oficial"] is None for p in saeb["pares"])
    assert all(p["motivo_escola"].startswith("sem registro oficial") for p in saeb["pares"])


def test_componente_incompativel_e_sem_variancia(db, cliente_global):
    m = mundo_correlato(db, y=[200.0] * 9)
    comp = _rel(cliente_global, m["rede"], **{**_SARESP_LP, "metrica": "atividades_por_aluno"})
    assert comp["motivos"] == ["componente_incompativel"]
    var = _rel(cliente_global, m["rede"], **_SARESP_LP)
    assert var["motivos"] == ["sem_variancia"] and var["n"] == 0 and var["coeficiente"] is None


def test_metrica_e_indicador_inexistentes(db, cliente_global):
    m = mundo_correlato(db)
    r = cliente_global.get(URL.format(rede=m["rede"].id), params={"indicador": "saresp",
                                                                  "metrica": "nada"})
    assert r.status_code == 400
    r = cliente_global.get(URL.format(rede=m["rede"].id), params={"indicador": "nada"})
    assert r.status_code == 404


def test_intervalo_com_rho_extremo_nao_quebra():
    ic = svc.intervalo_95(1.0, 8)
    assert ic["inferior"] <= 1 and ic["superior"] == 1.0
    assert svc.spearman([1, 1, 1], [1, 2, 3]) is None
