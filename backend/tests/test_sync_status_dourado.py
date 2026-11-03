"""DOURADO do GET /escolas/{id}/sync/status: a resposta é a MESMA, campo a campo,
antes e depois do corte de idas ao banco (e97z, 27/10).

O /status passou a ler tudo em poucas consultas agrupadas e a só commitar quando
grava (ver ``test_sync_status_orcamento.py``). Este teste prende o CONTRATO: para
cada cenário de ``sync_status_cenarios`` (escola nova, ano letivo virado, em dia com
rede, dados velhos que abrem/atualizam alertas, execução ativa, fila parada que é
cancelada, credencial ilegível/recusada, módulo fora do plano, agendador ligado),
as DUAS leituras seguidas devolvem exatamente o JSON gravado em
``sync_status_dourado.json`` — gravado com o código de antes (6fed992), em que cada
número vinha de uma consulta própria. O tempo é congelado (``AGORA``) e os ids
são os de um banco novo, então o arquivo é estável.

Mudança INTENCIONAL na resposta: regravar com ``REGRAVAR_DOURADO_STATUS=1`` e
conferir o diff do JSON na revisão.
"""
import json
import os
from pathlib import Path

import pytest

from tests import sync_status_cenarios as cenarios

ARQUIVO = Path(__file__).resolve().parent / "sync_status_dourado.json"
REGRAVAR = os.environ.get("REGRAVAR_DOURADO_STATUS") == "1"


def _gravado() -> dict:
    return json.loads(ARQUIVO.read_text(encoding="utf-8")) if ARQUIVO.exists() else {}


def duas_leituras(cliente, escola_id: int) -> list[dict]:
    respostas = []
    for _ in range(2):
        r = cliente.get(f"/api/v1/escolas/{escola_id}/sync/status")
        assert r.status_code == 200, r.text
        respostas.append(r.json())
    return respostas


@pytest.mark.parametrize("nome", list(cenarios.CENARIOS))
def test_status_devolve_o_json_gravado(nome, db, escola_completa, cliente_global, monkeypatch):
    cenarios.congelar(monkeypatch)
    eid = cenarios.CENARIOS[nome](db, escola_completa, monkeypatch)
    respostas = duas_leituras(cliente_global, eid)
    if REGRAVAR:
        dados = _gravado()
        dados[nome] = respostas
        ARQUIVO.write_text(json.dumps(dados, ensure_ascii=False, indent=1, sort_keys=True)
                           + "\n", encoding="utf-8", newline="\n")
        pytest.skip("regravado")
    assert nome in _gravado(), f"cenário {nome} sem resposta gravada: regravar"
    assert respostas == _gravado()[nome]


def test_cenarios_cobrem_os_estados_que_o_status_distingue():
    """O arquivo gravado não é trivial: os cenários exercitam de fato os ramos."""
    dados = _gravado()
    assert set(dados) == set(cenarios.CENARIOS)
    plat = {nome: {p["plataforma"]: p for p in leituras[0]["plataformas"]}
            for nome, leituras in dados.items()}
    assert dados["escola_nova"][0]["lista_piloto_importada"] is False
    assert dados["configurada_em_dia"][0]["lista_piloto_importada"] is True
    virada = plat["virada_do_ano"]
    assert dados["virada_do_ano"][0]["lista_piloto_importada"] is True
    assert virada["matific"]["alunos_com_dados"] == virada["matific"]["alunos_sem_dados"] == 0
    assert virada["matific"]["dado_mais_recente_em"] is None
    assert plat["configurada_em_dia"]["elefante"]["alunos_com_zero_registros"] == 1
    assert dados["configurada_em_dia"][0]["pendencias_correspondencia_30d"] == 2
    assert plat["configurada_em_dia"]["elefante"]["escola_externa"]["id"] == "4321"
    # Coleta por período: última tentativa, mas não "último sucesso".
    mat = plat["configurada_em_dia"]["matific"]
    assert mat["ultima_tentativa"]["periodo"] is not None
    assert mat["ultimo_sucesso_em"] != mat["ultima_tentativa"]["finalizada_em"]
    velhos = plat["dados_velhos"]
    assert velhos["elefante"]["desatualizada"] and velhos["matific"]["desatualizada"]
    assert velhos["elefante"]["frescor"] == "atualizado"     # parcial: sucesso, não em dia
    assert velhos["elefante"]["recalculo_pendente"] and velhos["matific"]["recalculo_pendente"]
    assert velhos["matific"]["falha_categoria"] == "indisponibilidade_externa"
    assert plat["execucao_ativa"]["elefante"]["ultima_execucao"]["status"] == "executando"
    assert plat["execucao_ativa"]["matific"]["ultima_execucao"]["status"] == "fila"
    assert {p["ultima_execucao"]["status"] for p in plat["fila_parada"].values()} == {"cancelada"}
    assert plat["fila_parada"]["matific"]["falha_categoria"] == "processamento"
    ilegivel = plat["credencial_ilegivel"]
    assert ilegivel["elefante"]["credencial_status"] == "ilegivel"
    assert ilegivel["matific"]["falha_categoria"] == "autenticacao"
    assert plat["fora_do_plano"]["matific"]["desatualizada"] is False
    assert dados["agendador_ligado"][0]["agendador_ativo"] is True
    # Alertas: a 1ª leitura dos dados velhos abre o do Matific (2 → 3 abertos de
    # frescor/falha + recálculo), o fora do plano fecha o do Matific.
    assert dados["dados_velhos"][0]["alertas_abertos"] == dados["dados_velhos"][1]["alertas_abertos"]
    assert dados["fora_do_plano"][0]["alertas_abertos"] == 0
