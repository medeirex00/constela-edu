"""Relatório por Período — ano fora da faixa nas datas: 422 ANTES de medir, no JSON e no
PDF (regressão do risco residual do marco 4 da revisão e97; inverte a prova
``test_a4_relatorio_por_periodo_da_escola_tambem_cai`` do verificador cético).

Antes: ``GET /escolas/{id}/relatorios/periodo?periodo=personalizado&inicio=0001-01-01``
respondia 500. ``resolver_janela`` aceitava a data, a rota lia a coorte e começava a medir,
e a conta da borda (início menos ``TOLERANCIA_BORDA``, de 1 h) estourava com
``OverflowError`` no ano 1; o fim em 31/12/9999 estoura do mesmo jeito (fim mais 1 µs). A
análise educacional já recusava isso com ``validar_anos`` (anos 2000–2100); o relatório da
escola, que mede com as mesmas funções, não. Agora ``resolver_janela`` passa as datas pela
MESMA faixa e levanta ``RelatorioInvalido``: 422 com a faixa na mensagem, sem ler a coorte
e sem registrar consulta na auditoria.

Dados INVENTADOS (decisão D13).
"""
from datetime import date, datetime

import pytest
from sqlalchemy import func, select

from app.models import LogAuditoria
from app.services import relatorios_periodo as rp
from app.services.analise import ANO_MAXIMO, ANO_MINIMO
from tests.test_analise_base import retrato_elefante

ROTA = "/api/v1/escolas/{eid}/relatorios/periodo"
ROTAS = (ROTA, ROTA + ".pdf")
HOJE = date(2026, 10, 5)

FORA_DA_FAIXA = [
    pytest.param({"inicio": "0001-01-01", "fim": "2026-10-05"}, "data inicial",
                 id="ano-1-no-inicio"),
    pytest.param({"inicio": "2026-01-01", "fim": "9999-12-31"}, "data final",
                 id="ano-9999-no-fim"),
    pytest.param({"inicio": f"{ANO_MINIMO - 1}-12-31", "fim": "2026-10-05"}, "data inicial",
                 id="vespera-da-faixa"),
    pytest.param({"inicio": "2026-01-01", "fim": f"{ANO_MAXIMO + 1}-01-01"}, "data final",
                 id="dia-seguinte-a-faixa"),
]


@pytest.fixture()
def com_retratos(db, escola_completa):
    """Retratos do Elefante em março e outubro: com eles a medição chega às questões —
    onde a borda do período menos 1 h estourava."""
    escola = escola_completa["escola"]
    for aluno in escola_completa["alunos"]:
        retrato_elefante(db, escola, aluno, datetime(2026, 3, 2, 15, 0),
                         tentativas=10, acertos=5)
        retrato_elefante(db, escola, aluno, datetime(2026, 10, 1, 15, 0),
                         tentativas=20, acertos=12)
    db.commit()
    return escola_completa


@pytest.fixture()
def sem_medir(monkeypatch):
    """Falha se o relatório chegar a ler a coorte ou a medir (a validação vem antes)."""
    def proibido(*_a, **_k):
        raise AssertionError("mediu antes de validar a entrada")
    for nome in ("_coorte", "_elefante", "_elefante_questoes", "_matific"):
        monkeypatch.setattr(rp, nome, proibido)


def _consultas_registradas(db) -> int:
    return db.execute(select(func.count()).select_from(LogAuditoria).where(
        LogAuditoria.acao.in_(("relatorio.periodo_consultado",
                               "relatorio.periodo_pdf")))).scalar_one()


@pytest.mark.parametrize("rota", ROTAS, ids=["json", "pdf"])
@pytest.mark.parametrize("datas,qual", FORA_DA_FAIXA)
def test_data_fora_da_faixa_e_422_sem_medir_nem_auditar(db, com_retratos, cliente, sem_medir,
                                                        rota, datas, qual):
    eid = com_retratos["escola"].id
    antes = _consultas_registradas(db)
    r = cliente.get(rota.format(eid=eid),
                    params={"periodo": "personalizado", **datas,
                            "plataformas": ["elefante", "matific"]})
    assert r.status_code == 422, (rota, datas, r.status_code, r.text[:300])
    detalhe = r.json()["detail"]
    assert "fora da faixa aceita" in detalhe and qual in detalhe
    assert str(ANO_MINIMO) in detalhe and str(ANO_MAXIMO) in detalhe
    assert _consultas_registradas(db) == antes, "pedido recusado não é consulta auditada"


def test_a_prova_do_verificador_agora_e_422(db, com_retratos, cliente):
    """A requisição EXATA da prova ``test_a4_relatorio_por_periodo_da_escola_tambem_cai``
    (que exigia 500), sem nenhum dublê: agora 422."""
    eid = com_retratos["escola"].id
    r = cliente.get(ROTA.format(eid=eid),
                    params={"periodo": "personalizado", "inicio": "0001-01-01",
                            "fim": "2026-10-05", "plataformas": "elefante"})
    assert r.status_code == 422, r.text[:300]
    assert "0001-01-01" in r.json()["detail"]


def test_data_fora_da_faixa_e_recusada_em_qualquer_preset(db, com_retratos, cliente,
                                                          sem_medir):
    """Mesma regra de ``validar_anos`` na análise: a data informada é conferida mesmo
    quando o preset não a usa (a tela só a envia em ``personalizado``)."""
    eid = com_retratos["escola"].id
    r = cliente.get(ROTA.format(eid=eid),
                    params={"periodo": "mes_anterior", "inicio": "0001-01-01",
                            "plataformas": "elefante"})
    assert r.status_code == 422, r.text[:300]
    assert "fora da faixa aceita" in r.json()["detail"]


@pytest.mark.parametrize("inicio,fim", [
    (date(1, 1, 1), date(2026, 10, 5)),
    (date(2026, 1, 1), date(9999, 12, 31)),
    (date(ANO_MINIMO - 1, 12, 31), date(2026, 10, 5)),
])
def test_servico_recusa_com_relatorio_invalido(db, com_retratos, inicio, fim):
    """O serviço (não só a rota) recusa com ``RelatorioInvalido`` — e não com
    ``OverflowError`` no meio da medição."""
    with pytest.raises(rp.RelatorioInvalido, match="fora da faixa aceita"):
        rp.resolver_janela("personalizado", 2026, inicio=inicio, fim=fim, hoje=HOJE)
    with pytest.raises(rp.RelatorioInvalido, match="fora da faixa aceita"):
        rp.gerar(db, com_retratos["escola"].id, preset="personalizado",
                 plataformas=("elefante", "matific"), inicio=inicio, fim=fim, hoje=HOJE)


def test_ordem_das_recusas_nao_muda(db, com_retratos):
    """Preset inexistente continua dizendo isso primeiro; dentro da faixa, as recusas
    de antes (faltou data, início depois do fim) seguem as mesmas."""
    with pytest.raises(rp.RelatorioInvalido, match="não existe"):
        rp.resolver_janela("trimestre_7", 2026, inicio=date(1, 1, 1), hoje=HOJE)
    with pytest.raises(rp.RelatorioInvalido, match="exige data inicial E data final"):
        rp.resolver_janela("personalizado", 2026, inicio=date(2026, 9, 1), hoje=HOJE)
    with pytest.raises(rp.RelatorioInvalido, match="posterior"):
        rp.resolver_janela("personalizado", 2026, inicio=date(2026, 9, 25),
                           fim=date(2026, 9, 10), hoje=HOJE)


def test_controle_bordas_da_faixa_continuam_respondendo(db, com_retratos, cliente,
                                                        monkeypatch):
    """As bordas EXATAS da faixa (01/01/2000 e 31/12/2100) medem normalmente, no JSON e
    no PDF — a recusa é só para fora dela."""
    from app.services import relatorios_periodo_pdf as pdf

    def sem_chromium(*_a, **_k):
        raise RuntimeError("sem Chromium (forçado pelo teste)")
    monkeypatch.setattr(pdf, "_relatorio_html_pdf", sem_chromium)
    eid = com_retratos["escola"].id
    params = {"periodo": "personalizado", "inicio": f"{ANO_MINIMO}-01-01",
              "fim": f"{ANO_MAXIMO}-12-31", "plataformas": ["elefante", "matific"]}
    r = cliente.get(ROTA.format(eid=eid), params=params)
    assert r.status_code == 200, r.text[:300]
    corpo = r.json()
    assert corpo["periodo"]["inicio"].startswith(f"{ANO_MINIMO}-01-01")
    assert corpo["periodo"]["fim"].startswith(f"{ANO_MAXIMO}-12-31")
    assert corpo["alunos"]["considerados"] == len(com_retratos["alunos"])
    # Sem coleta antes do início, a conta começa na primeira coleta: 10/5 → 20/12 por aluno.
    n = len(com_retratos["alunos"])
    assert corpo["elefante"]["questoes_tentativas"] == 10 * n
    assert corpo["elefante"]["questoes_acertos"] == 7 * n
    r = cliente.get(ROTA.format(eid=eid) + ".pdf", params=params)
    assert r.status_code == 200, r.text[:300]
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
