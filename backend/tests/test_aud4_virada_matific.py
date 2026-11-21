"""Regressões da virada do contador do Matific e da população histórica."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models import Importacao, Matricula, SnapshotElefante, SnapshotMatific, Turma
from tests._relogio import prender
from tests._sync_nucleo_fakes import PlacarFake, alertas_abertos, credencial, instalar, rodar, vincular


@pytest.fixture(autouse=True)
def _relogio(monkeypatch):
    prender(monkeypatch, datetime(2027, 3, 10, 15, tzinfo=timezone.utc))


def _escola_2027(db, escola_completa, cliente_global):
    escola = escola_completa["escola"]
    resposta = cliente_global.patch(f"/api/v1/escolas/{escola.id}", json={"ano_letivo_ativo": 2027})
    assert resposta.status_code == 200, resposta.text
    turma = Turma(escola_id=escola.id, nome="4º Ano A", ano_escolar="4º Ano", ano_letivo=2027)
    db.add(turma)
    db.flush()
    for aluno in escola_completa["alunos"]:
        db.add(Matricula(escola_id=escola.id, aluno_id=aluno.id, turma_id=turma.id, ano_letivo=2027))
    db.commit()


def _retrato(db, escola_id, aluno_id, ano, *, mes=12, dia=10, atividades=80,
             estrelas=300, livros=None):
    plataforma = "matific" if livros is None else "elefante"
    importacao = Importacao(escola_id=escola_id, plataforma=plataforma, tipo="seed")
    db.add(importacao)
    db.flush()
    dados = dict(escola_id=escola_id, aluno_id=aluno_id, importacao_id=importacao.id,
                 data_referencia=datetime(ano, mes, dia, 15))
    if livros is None:
        db.add(SnapshotMatific(**dados, atividades=atividades, estrelas=estrelas,
                               pontuacao_media=3.75))
    else:
        db.add(SnapshotElefante(**dados, livros_unicos=livros, tempo_leitura_min=60))
    db.commit()


def _retratos_matific(db, aluno_id):
    db.expire_all()
    return list(db.scalars(select(SnapshotMatific)
                          .where(SnapshotMatific.aluno_id == aluno_id)
                          .order_by(SnapshotMatific.data_referencia, SnapshotMatific.id)))


@pytest.mark.parametrize("formato", ["periodo", "acumulado", "coleta_por_periodo"])
def test_virada_nao_herda_o_contador_do_ano_anterior(
        db, escola_completa, cliente_global, monkeypatch, formato):
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    _retrato(db, escola.id, aluno.id, 2026)
    _escola_2027(db, escola_completa, cliente_global)
    vincular(db, escola.id, aluno.id, "matific", "u-inventado")
    db.commit()
    credencial(db, escola.id, "matific")
    placar = PlacarFake()
    instalar(monkeypatch, placar=placar)
    linha = {"nome": aluno.nome, "aluno_id": aluno.id,
             "dados": {"atividades": 6, "pontuacao_media": 3.33}}
    periodo = {
        "periodo_inicio": "2027-02-01T00:00:00",
        "periodo_fim": "2027-03-01T00:00:00",
    }
    if formato == "coleta_por_periodo":
        placar.linhas = [("u-inventado", aluno.nome, "4 ANO A (300396900)", 20, 6)]
        execucao, erro = rodar(db, escola.id, "matific", parametros={
            "matific_start_date": "2027-02-01", "matific_end_date": "2027-02-28"})
        assert erro is None and execucao.status == "concluida"
    else:
        if formato == "periodo":
            linha["dados"]["estrelas"] = 20
        else:
            periodo = {"data_referencia": "2027-02-15T15:00:00Z"}
        resposta = cliente_global.post(f"/api/v1/escolas/{escola.id}/importacoes/confirmar", json={
            "plataforma": "matific", "formato": "resumo", "tipo": "xlsx", "linhas": [linha],
            **periodo,
        })
        assert resposta.status_code == 200, resposta.text
    novo = _retratos_matific(db, aluno.id)[-1]
    assert (novo.data_referencia.year, novo.atividades, novo.estrelas) == (
        2027, 6, 0 if formato == "acumulado" else 20)

    placar.linhas = [("u-inventado", aluno.nome, "4 ANO A (300396900)", 40, 10)]
    execucao, erro = rodar(db, escola.id, "matific")
    assert erro is None and execucao.status == "concluida"
    assert "queda_matific" not in alertas_abertos(db, escola.id, "matific")
    atual = _retratos_matific(db, aluno.id)[-1]
    assert (atual.atividades, atual.estrelas) == (10, 40)


def test_importacao_de_janeiro_preserva_dezembro_e_recusa_intervalo_entre_anos(
        db, escola_completa, cliente_global):
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    _retrato(db, escola.id, aluno.id, 2026)
    _escola_2027(db, escola_completa, cliente_global)
    url = f"/api/v1/escolas/{escola.id}/importacoes/confirmar"
    pedido = {
        "plataforma": "matific", "formato": "resumo", "tipo": "xlsx",
        "periodo_inicio": "2026-12-20T00:00:00", "periodo_fim": "2027-02-01T00:00:00",
        "linhas": [{"nome": aluno.nome, "aluno_id": aluno.id,
                    "dados": {"atividades": 4, "estrelas": 10}}],
    }
    resposta = cliente_global.post(url, json=pedido)
    assert resposta.status_code == 422, resposta.text
    assert len(_retratos_matific(db, aluno.id)) == 1

    pedido["periodo_inicio"] = "2027-01-01T00:00:00"
    for _ in range(2):
        resposta = cliente_global.post(url, json=pedido)
        assert resposta.status_code == 200, resposta.text
    retratos = _retratos_matific(db, aluno.id)
    assert [(s.data_referencia.year, s.atividades, s.estrelas) for s in retratos] == [
        (2026, 80, 300), (2027, 4, 10),
    ]


def test_acumulado_do_matific_grava_o_mesmo_ano_utc_que_usa_para_herdar(
        db, escola_completa, cliente_global):
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    _retrato(db, escola.id, aluno.id, 2026)
    _escola_2027(db, escola_completa, cliente_global)
    resposta = cliente_global.post(f"/api/v1/escolas/{escola.id}/importacoes/confirmar", json={
        "plataforma": "matific", "formato": "resumo", "tipo": "xlsx",
        "data_referencia": "2026-12-31T23:30:00-03:00",
        "linhas": [{"nome": aluno.nome, "aluno_id": aluno.id, "dados": {"atividades": 2}}],
    })
    assert resposta.status_code == 200, resposta.text
    novo = _retratos_matific(db, aluno.id)[-1]
    assert novo.data_referencia == datetime(2027, 1, 1, 2, 30)
    assert (novo.atividades, novo.estrelas) == (2, 0)


def test_resumo_historico_e_estado_atual_respeitam_anos_distintos(
        db, escola_completa, cliente_global):
    escola = escola_completa["escola"]
    turma_antiga = escola_completa["turma"]
    aluno = escola_completa["alunos"][0]
    url = f"/api/v1/escolas/{escola.id}"
    _retrato(db, escola.id, aluno.id, 2026)
    _retrato(db, escola.id, aluno.id, 2026, livros=11)
    _escola_2027(db, escola_completa, cliente_global)
    _retrato(db, escola.id, aluno.id, 2027, mes=2, livros=33)

    lista = cliente_global.get(f"{url}/turmas/{turma_antiga.id}/alunos")
    resumo = cliente_global.get(f"{url}/turmas/{turma_antiga.id}/resumo")
    assert lista.status_code == resumo.status_code == 200
    assert resumo.json()["total_alunos"] == len(lista.json()) == 3
    indicadores = resumo.json()["indicadores"]
    assert (indicadores["atividades"], indicadores["livros_unicos"]) == (80, 11)

    modulo = cliente_global.get(f"{url}/matific")
    assert modulo.status_code == 200, modulo.text
    assert all(i["data_referencia"] is None for i in modulo.json())

    ajuste = cliente_global.put(f"{url}/matific/{aluno.id}", json={
        "atividades": 3, "estrelas": 12, "motivo": "Ajuste da coleta de teste",
    })
    assert ajuste.status_code == 200, ajuste.text
    assert ajuste.json()["pontuacao_media"] == 0


def test_evolucao_separa_contadores_anuais_e_limita_estrelas(
        db, escola_completa, cliente_global):
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    _retrato(db, escola.id, aluno.id, 2026)
    _retrato(db, escola.id, aluno.id, 2027, mes=2, atividades=3, estrelas=100)
    resposta = cliente_global.get(
        f"/api/v1/escolas/{escola.id}/alunos/{aluno.id}/evolucao?dias=90")
    assert resposta.status_code == 200, resposta.text
    dados = resposta.json()
    por_indicador = {i["indicador"]: i for i in dados["resumo"]["indicadores"]}
    assert (por_indicador["atividades"]["inicial"], por_indicador["atividades"]["variacao"]) == (0, 3)
    assert (por_indicador["estrelas"]["inicial"], por_indicador["estrelas"]["variacao"]) == (0, 15)
    assert dados["linha_do_tempo"]["matific"][-1]["estrelas"] == 15
