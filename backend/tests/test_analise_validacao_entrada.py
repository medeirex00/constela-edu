"""Análise educacional — ano fora da faixa nas datas do período e na edição: 422 ANTES de
medir (regressão da prova 3 da revisão e97 do módulo ``analise``).

Antes: ``GET /redes/{id}/analise/relacao?edicao=0`` (ou 10000) caía com ``ValueError``
em ``relacao._sobrepoe`` (``datetime(0, 1, 1)``) e ``periodo=personalizado&inicio=0001-01-01``
caía com ``OverflowError`` na borda do período menos a tolerância de 1 h — os dois viravam
500, e só depois de a rota medir a rede inteira. Agora a entrada é validada no começo
(anos de ``ANO_MINIMO`` a ``ANO_MAXIMO``) e a resposta é 422, sem medir nenhuma escola.

Dados INVENTADOS (decisão D13).
"""
from datetime import date, datetime

import pytest

from app.services.analise import ANO_MAXIMO, ANO_MINIMO, AnaliseInvalida
from app.services.analise import escola as svc_escola
from app.services.analise import plataformas as svc_plat
from app.services.analise import relacao as svc_rel
from tests.test_analise_base import (HOJE, nova_escola, nova_rede, retrato_elefante,
                                     turma_com_alunos)

URL_REDE = "/api/v1/redes/{rede}/analise"
URL_ESCOLA = "/api/v1/escolas/{escola}/analise"


@pytest.fixture(autouse=True)
def _hoje(monkeypatch):
    monkeypatch.setattr("app.routers.analise.hoje_br", lambda: HOJE)


def _mundo(db):
    rede = nova_rede(db, nome="Rede Fictícia Entrada", codigo="3599971", codmun="9971")
    e = nova_escola(db, rede, "EMEF Fictícia Entrada", "35997101")
    for a in turma_com_alunos(db, e, "5º Ano", 5):
        retrato_elefante(db, e, a, datetime(2026, 3, 2, 15, 0), tentativas=10, acertos=5)
        retrato_elefante(db, e, a, datetime(2026, 10, 1, 15, 0), tentativas=20, acertos=12)
    db.commit()
    return rede, e


@pytest.fixture()
def sem_medir(monkeypatch):
    """Falha se a rota chegar a medir alguma escola (a validação vem antes)."""
    def proibido(*_a, **_k):
        raise AssertionError("mediu a rede antes de validar a entrada")
    monkeypatch.setattr(svc_plat, "_coortes", proibido)
    monkeypatch.setattr(svc_plat, "_coortes_e_coletas", proibido)   # a da rota (com as coletas)
    monkeypatch.setattr(svc_plat, "_medir_escola", proibido)
    monkeypatch.setattr(svc_plat, "celulas_da_rede", proibido)


@pytest.mark.parametrize("edicao", [0, 10000, ANO_MINIMO - 1, ANO_MAXIMO + 1])
def test_relacao_com_edicao_fora_da_faixa_e_422_sem_medir(db, cliente_global, sem_medir,
                                                          edicao):
    rede, _ = _mundo(db)
    r = cliente_global.get(URL_REDE.format(rede=rede.id) + "/relacao",
                           params={"indicador": "saresp", "edicao": edicao})
    assert r.status_code == 422, (edicao, r.status_code, r.text)
    assert "edição" in r.json()["detail"] and str(ANO_MINIMO) in r.json()["detail"]


@pytest.mark.parametrize("params", [
    {"periodo": "personalizado", "inicio": "0001-01-01", "fim": "2026-10-05"},
    {"periodo": "personalizado", "inicio": "2026-01-01", "fim": "9999-12-31"},
    {"periodo": "personalizado", "inicio": "1999-12-31", "fim": "2026-10-05"},
])
def test_plataformas_com_data_fora_da_faixa_e_422_sem_medir(db, cliente_global, sem_medir,
                                                           params):
    rede, e = _mundo(db)
    for url in (URL_REDE.format(rede=rede.id) + "/plataformas",
                URL_REDE.format(rede=rede.id) + "/relacao",
                URL_ESCOLA.format(escola=e.id)):
        extra = {"indicador": "saresp"} if url.endswith("/relacao") else {}
        r = cliente_global.get(url, params={**params, **extra})
        assert r.status_code == 422, (url, r.status_code, r.text)
        assert "fora da faixa aceita" in r.json()["detail"]


def test_servicos_recusam_com_analise_invalida_422(db):
    """As funções do serviço (não só as rotas) recusam com ``AnaliseInvalida(422)`` — e não
    com ``ValueError``/``OverflowError``."""
    rede, e = _mundo(db)
    chamadas = [
        lambda: svc_rel.relacao(db, rede, indicador="saresp", edicao=0, hoje=HOJE),
        lambda: svc_plat.plataformas_da_rede(db, rede, preset="personalizado",
                                             inicio=date(1, 1, 1), fim=date(2026, 10, 5),
                                             hoje=HOJE),
        lambda: svc_plat.celulas_da_rede(db, rede, preset="personalizado",
                                         inicio=date(1, 1, 1), fim=date(2026, 10, 5),
                                         hoje=HOJE),
        lambda: svc_escola.analise_da_escola(db, e, preset="personalizado",
                                             inicio=date(1, 1, 1), fim=date(2026, 10, 5),
                                             hoje=HOJE),
    ]
    for chamar in chamadas:
        with pytest.raises(AnaliseInvalida) as exc:
            chamar()
        assert exc.value.status == 422


def test_controle_anos_na_faixa_continuam_respondendo(db, cliente_global):
    rede, e = _mundo(db)
    base = URL_REDE.format(rede=rede.id)
    assert cliente_global.get(base + "/relacao",
                              params={"indicador": "saresp", "edicao": 2025}).status_code == 200
    periodo = {"periodo": "personalizado", "inicio": f"{ANO_MINIMO}-01-01",
               "fim": "2026-10-05"}
    r = cliente_global.get(base + "/plataformas", params=periodo)
    assert r.status_code == 200, r.text
    (escola,) = r.json()["escolas"]
    # Sem coleta antes do início, a conta começa na primeira coleta do período: 10/5 → 20/12.
    assert escola["elefante"]["taxa_acerto_pct"] == 70.0
    assert cliente_global.get(URL_ESCOLA.format(escola=e.id), params=periodo).status_code == 200
