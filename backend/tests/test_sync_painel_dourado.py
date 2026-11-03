"""DOURADO do GET /sync/dashboard (painel global, só admin global): a resposta é a
MESMA, campo a campo — inclusive o bloco ``prerequisitos_agendador`` com os textos
de cada verificação —, antes e depois do corte das idas ao banco (e97x, 28/10).

No 7440226 o painel fazia uma ida por agenda vencida (o contrato da rede de cada
uma) e uma por agenda ativa (a credencial de cada uma), além de ler as colunas da
tabela de execuções duas vezes: 25/56/194 instruções para 0/5/28 escolas com agenda
vencida (~5,5/11,5/38 s a ~195 ms por ida). O orçamento está em
``test_sync_painel_orcamento.py``; este teste prende o CONTRATO.

Cada estado de ``sync_painel_cenarios`` (sem integração nenhuma; 28 escolas, de
redes com tudo contratado, de rede SEM Matemática e avulsas, com 0, 5 e 28 agendas
vencidas; agendador ligado e forçado) tem as DUAS leituras seguidas iguais ao JSON
gravado em ``sync_painel_dourado.json`` — gravado com o código de antes (6251075).
O tempo é congelado e os ids são os de um banco novo, então o arquivo é estável.

Mudança INTENCIONAL na resposta: regravar com ``REGRAVAR_DOURADO_PAINEL=1`` e
conferir o diff do JSON na revisão.
"""
import json
import os
from pathlib import Path

import pytest

from app.core.config import settings
from tests import sync_painel_cenarios as cenarios

ARQUIVO = Path(__file__).resolve().parent / "sync_painel_dourado.json"
REGRAVAR = os.environ.get("REGRAVAR_DOURADO_PAINEL") == "1"


def _vazio(db, base, monkeypatch):
    return None


def _vencidas(n, **ambiente):
    def montar(db, base, monkeypatch):
        for nome, valor in ambiente.items():
            monkeypatch.setattr(settings, nome, valor)
        cenarios.mundo(db, base, vencidas=n)
    return montar


ESTADOS = {
    "sem_integracao": _vazio,
    "vencidas_0": _vencidas(0),
    "vencidas_5": _vencidas(5),
    "vencidas_28": _vencidas(28),
    "vencidas_5_agendador_ligado": _vencidas(5, SYNC_SCHEDULER_ENABLED=True),
    "vencidas_5_forcado": _vencidas(5, SYNC_SCHEDULER_ENABLED=True,
                                    SYNC_SCHEDULER_FORCAR="true"),
}


def _gravado() -> dict:
    return json.loads(ARQUIVO.read_text(encoding="utf-8")) if ARQUIVO.exists() else {}


@pytest.mark.parametrize("nome", list(ESTADOS))
def test_painel_devolve_o_json_gravado(nome, db, escola_completa, cliente_global, monkeypatch):
    cenarios.congelar(monkeypatch)
    ESTADOS[nome](db, escola_completa, monkeypatch)
    respostas = []
    for _ in range(2):
        r = cliente_global.get("/api/v1/sync/dashboard")
        assert r.status_code == 200, r.text
        respostas.append(r.json())
    if REGRAVAR:
        dados = _gravado()
        dados[nome] = respostas
        ARQUIVO.write_text(json.dumps(dados, ensure_ascii=False, indent=1, sort_keys=True)
                           + "\n", encoding="utf-8", newline="\n")
        pytest.skip("regravado")
    assert nome in _gravado(), f"estado {nome} sem resposta gravada: regravar"
    assert respostas == _gravado()[nome]


def test_estados_cobrem_o_que_o_painel_distingue():
    """O arquivo gravado não é trivial: os estados exercitam de fato os ramos
    (a rede sem Matemática não conta o Matific vencido; credencial ilegível;
    presas; recálculo; agenda que nasce ao ligar; horário do backup)."""
    dados = _gravado()
    assert set(dados) == set(ESTADOS)
    painel = {nome: leituras[0] for nome, leituras in dados.items()}
    # 28 escolas, 1/3 na rede só de Leitura (as de índice 1, 4, 7, …): das 5
    # primeiras vencidas, 2 só vencem no Matific, fora do plano.
    assert [painel[n]["escolas_desatualizadas"] for n in
            ("sem_integracao", "vencidas_0", "vencidas_5", "vencidas_28")] == [0, 0, 3, 19]
    assert painel["vencidas_5"]["escolas_com_erro"] == 1
    assert painel["vencidas_5"]["em_andamento"] == 1 and painel["vencidas_5"]["fila"] == 2
    verif = {nome: {v["id"]: v for v in p["prerequisitos_agendador"]["verificacoes"]}
             for nome, p in painel.items()}
    for nome in ("vencidas_0", "vencidas_5", "vencidas_28"):
        v = verif[nome]
        assert not v["credenciais_legiveis"]["ok"]
        assert "escola 5/elefante" in v["credenciais_legiveis"]["motivo"]
        assert not v["execucoes_presas"]["ok"] and "#" in v["execucoes_presas"]["motivo"]
        assert not v["recalculo_sem_pendencia"]["ok"]
        assert not v["horario_fora_do_backup"]["ok"]
        assert not v["fuso_da_agenda"]["ok"]
        assert not v["alcance_ao_ligar"]["ok"]
    assert verif["sem_integracao"]["credenciais_legiveis"]["ok"]
    assert painel["vencidas_5_forcado"]["prerequisitos_agendador"]["forcar"] is True
    assert painel["vencidas_5_agendador_ligado"]["prerequisitos_agendador"]["habilitado"] is True
