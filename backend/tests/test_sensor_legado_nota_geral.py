"""SENSOR 4 do plano de retirada do legado `nota_geral` — telemetria de contrato.

O inventário de `test_legado_nota_geral.py` prova que o código DESTE repositório
não depende mais do legado. Ele não enxerga o app já instalado nos celulares nem
um navegador preso num bundle antigo: para esses, a única prova é o servidor
CONTAR quantas respostas ainda saem com `nota_geral`/`Nota.posicao`, e para
quem. É o contador `legado_nota_geral_servido_total{rota, cliente}`
(`app.core.observabilidade.registrar_legado_nota_geral`).

O que se prova aqui:
  * o contador sobe nas rotas que servem o contrato legado e NÃO sobe na rota
    por dimensão (cliente já migrado);
  * os rótulos têm cardinalidade limitada: a rota é o TEMPLATE (sem ids, sem o
    token do telão) e o cliente sai de um conjunto fechado — um User-Agent
    arbitrário cai em "outro";
  * é puramente aditivo: nenhuma resposta muda e uma falha da telemetria nunca
    derruba a requisição.
"""
import re

import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from app.core import observabilidade as obs
from app.main import app
from app.models import Importacao, SnapshotElefante, SnapshotMatific
from app.services import scoring

METRICA = "legado_nota_geral_servido_total"
ESCOLA = "/api/v1/escolas/{escola_id}"
ROTA_RANKING = f"{ESCOLA}/ranking"
ROTA_DASHBOARD = f"{ESCOLA}/dashboard"
ROTA_PERFIL = f"{ESCOLA}/alunos/{{aluno_id}}/perfil"
ROTA_TURMA = f"{ESCOLA}/turmas/{{turma_id}}/alunos"
ROTA_COMPARAR = f"{ESCOLA}/comparar"
ROTA_SYNC = f"{ESCOLA}/sincronizacao"
ROTA_TELAO = "/api/v1/publico/{token}/painel"
ROTA_PERFIL_PUBLICO = "/api/v1/publico/{token}/alunos/{aluno_id}"

_CLIENTE_VALIDO = re.compile(
    r"^(web|mobile-android|mobile-ios|outro|(web|mobile)/(\d{1,3}(\.\d{1,3}){0,2}|outra))$")


def _amostras() -> list[tuple[dict, float]]:
    return [(amostra.labels, amostra.value)
            for familia in REGISTRY.collect()
            for amostra in familia.samples if amostra.name == METRICA]


def _total(rota: str, cliente: str | None = None) -> float:
    """Soma do contador numa rota (e cliente, se dado). O registro é global ao
    processo, então todo teste mede DIFERENÇAS, nunca valores absolutos."""
    return sum(valor for rotulos, valor in _amostras()
               if rotulos["rota"] == rota
               and (cliente is None or rotulos["cliente"] == cliente))


def _total_geral() -> float:
    return sum(valor for _rotulos, valor in _amostras())


@pytest.fixture()
def com_notas(db, escola_completa):
    """Ana e João com Matific, Ana com Elefante — rankings legado e por
    dimensão não vazios."""
    escola = escola_completa["escola"]
    ana, joao, _sofia = escola_completa["alunos"]
    imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=ana.id, importacao_id=imp.id,
                           atividades=40, estrelas=90, pontuacao_media=80))
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=joao.id, importacao_id=imp.id,
                           atividades=10, estrelas=20, pontuacao_media=50))
    db.add(SnapshotElefante(escola_id=escola.id, aluno_id=ana.id, importacao_id=imp.id,
                            livros_unicos=8, tempo_leitura_min=120,
                            questoes_tentativas=20, questoes_acertos=15,
                            livros_por_nivel={"D": 8}))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    return escola_completa


# --- O contador sobe no legado e NÃO na rota por dimensão ---------------------

def test_ranking_legado_conta_e_ranking_por_dimensao_nao(cliente, com_notas):
    escola_id = com_notas["escola"].id

    antes = _total(ROTA_RANKING)
    for dimensao in ("leitura", "matematica"):
        r = cliente.get(f"/api/v1/escolas/{escola_id}/ranking?dimensao={dimensao}")
        assert r.status_code == 200, r.text
        assert r.json(), "cenário sem sinal: ranking por dimensão vazio"
    assert _total(ROTA_RANKING) == antes, (
        "a rota POR DIMENSÃO não serve o contrato legado — não pode contar")

    antes_outro = _total(ROTA_RANKING, "outro")
    r = cliente.get(f"/api/v1/escolas/{escola_id}/ranking")
    assert r.status_code == 200, r.text
    assert "nota_geral" in r.json()[0]
    # O TestClient se apresenta como "testclient": fora do conjunto → "outro".
    assert _total(ROTA_RANKING, "outro") == antes_outro + 1
    assert _total(ROTA_RANKING) == antes + 1


def test_dashboard_conta_o_top10_legado(cliente, com_notas):
    escola_id = com_notas["escola"].id
    antes = _total(ROTA_DASHBOARD)
    r = cliente.get(f"/api/v1/escolas/{escola_id}/dashboard")
    assert r.status_code == 200, r.text
    assert _total(ROTA_DASHBOARD) == antes + 1


def test_perfil_do_aluno_conta_so_o_que_e_servido(cliente, com_notas):
    escola_id = com_notas["escola"].id
    ana = com_notas["alunos"][0]
    antes = _total(ROTA_PERFIL)
    r = cliente.get(f"/api/v1/escolas/{escola_id}/alunos/{ana.id}/perfil")
    assert r.status_code == 200, r.text
    assert _total(ROTA_PERFIL) == antes + 1
    # 404: nenhum payload legado saiu — não conta.
    r = cliente.get(f"/api/v1/escolas/{escola_id}/alunos/999999/perfil")
    assert r.status_code == 404
    assert _total(ROTA_PERFIL) == antes + 1


def test_lista_da_turma_separa_quem_ainda_ordena_pelo_legado(cliente, com_notas):
    """Toda resposta da lista leva `nota_geral`/`posicao` por aluno; quem pede
    `?ordenar=desempenho` além disso ORDENA pelo legado — rótulo próprio."""
    escola_id = com_notas["escola"].id
    turma_id = com_notas["turma"].id
    variante = f"{ROTA_TURMA}?ordenar=desempenho"
    antes_simples, antes_variante = _total(ROTA_TURMA), _total(variante)

    r = cliente.get(f"/api/v1/escolas/{escola_id}/turmas/{turma_id}/alunos")
    assert r.status_code == 200, r.text
    assert _total(ROTA_TURMA) == antes_simples + 1
    assert _total(variante) == antes_variante

    r = cliente.get(
        f"/api/v1/escolas/{escola_id}/turmas/{turma_id}/alunos?ordenar=desempenho")
    assert r.status_code == 200, r.text
    assert _total(variante) == antes_variante + 1
    assert _total(ROTA_TURMA) == antes_simples + 1


def test_comparador_so_conta_com_lado_aluno(cliente, com_notas):
    escola_id = com_notas["escola"].id
    ana, joao, _ = com_notas["alunos"]
    turma_id = com_notas["turma"].id
    antes = _total(ROTA_COMPARAR)

    r = cliente.get(f"/api/v1/escolas/{escola_id}/comparar?tipo_a=turma&id_a={turma_id}"
                    f"&tipo_b=turma&id_b={turma_id}")
    assert r.status_code == 200, r.text
    assert _total(ROTA_COMPARAR) == antes, (
        "turma×turma não leva `nota_geral` (lá `notas.geral` é média das "
        "dimensões com dado) — não pode contar")

    r = cliente.get(f"/api/v1/escolas/{escola_id}/comparar?tipo_a=aluno&id_a={ana.id}"
                    f"&tipo_b=aluno&id_b={joao.id}")
    assert r.status_code == 200, r.text
    assert _total(ROTA_COMPARAR) == antes + 1


def test_pacote_do_app_conta_com_o_tipo_de_cliente(cliente, com_notas):
    """O pacote de sincronização é o consumidor que não atualizamos à força:
    o rótulo `cliente` separa o app Android/iOS do resto."""
    escola_id = com_notas["escola"].id
    antes_android = _total(ROTA_SYNC, "mobile-android")
    antes_ios = _total(ROTA_SYNC, "mobile-ios")

    r = cliente.get(f"/api/v1/escolas/{escola_id}/sincronizacao",
                    headers={"User-Agent": "okhttp/4.9.2"})
    assert r.status_code == 200, r.text
    assert "ranking" in r.json()
    r = cliente.get(f"/api/v1/escolas/{escola_id}/sincronizacao",
                    headers={"User-Agent": "Constela%20Edu/7 CFNetwork/1494.0.7 "
                                           "Darwin/23.4.0"})
    assert r.status_code == 200, r.text

    assert _total(ROTA_SYNC, "mobile-android") == antes_android + 1
    assert _total(ROTA_SYNC, "mobile-ios") == antes_ios + 1


def _ativar_painel(cliente, escola_id: int, slides: list[str]) -> str:
    r = cliente.put(f"/api/v1/escolas/{escola_id}/painel-publico",
                    json={"ativo": True, "slides": slides,
                          "intervalo_s": 8, "max_posicoes": 5})
    assert r.status_code == 200, r.text
    return r.json()["url"].rsplit("/", 1)[-1]


def test_telao_e_perfil_publico_contam_sem_expor_o_token(cliente, com_notas):
    escola_id = com_notas["escola"].id
    ana = com_notas["alunos"][0]
    token = _ativar_painel(cliente, escola_id, ["ranking", "destaques"])
    anonimo = TestClient(app)   # sem Authorization: é o telão
    navegador = {"User-Agent": "Mozilla/5.0 (SmartTV)"}

    antes_telao = _total(ROTA_TELAO, "web")
    antes_perfil = _total(ROTA_PERFIL_PUBLICO, "web")
    r = anonimo.get(f"/api/v1/publico/{token}/painel", headers=navegador)
    assert r.status_code == 200, r.text
    assert r.json()["ranking"]
    r = anonimo.get(f"/api/v1/publico/{token}/alunos/{ana.id}", headers=navegador)
    assert r.status_code == 200, r.text
    assert _total(ROTA_TELAO, "web") == antes_telao + 1
    assert _total(ROTA_PERFIL_PUBLICO, "web") == antes_perfil + 1

    # O token do link público NUNCA vira rótulo (quem lê /metrics abriria o
    # painel com nomes de crianças).
    assert all(token not in rotulos["rota"] for rotulos, _ in _amostras())

    # Sem o slide `ranking`, o telão não recebe o legado — e não conta.
    token = _ativar_painel(cliente, escola_id, ["destaques"])
    antes_telao = _total(ROTA_TELAO)
    r = anonimo.get(f"/api/v1/publico/{token}/painel", headers=navegador)
    assert r.status_code == 200, r.text
    assert r.json()["ranking"] == []
    assert _total(ROTA_TELAO) == antes_telao


# --- Rótulos de cardinalidade limitada ------------------------------------------

def test_user_agent_arbitrario_cai_em_outro(cliente, com_notas):
    escola_id = com_notas["escola"].id
    lixo = "Robo-Qualquer/9.9 (+http://exemplo.invalid) " + "x" * 300
    antes = _total(ROTA_RANKING, "outro")
    r = cliente.get(f"/api/v1/escolas/{escola_id}/ranking",
                    headers={"User-Agent": lixo})
    assert r.status_code == 200, r.text
    assert _total(ROTA_RANKING, "outro") == antes + 1
    assert all(lixo not in rotulos["cliente"] for rotulos, _ in _amostras())


def test_todos_os_rotulos_sao_de_conjunto_fechado(cliente, com_notas):
    """Depois de exercitar as rotas: toda `rota` é um template de rota do app
    (com, no máximo, uma variante fixa do código) e todo `cliente` é do conjunto
    fechado — nenhum id, token ou texto livre de cabeçalho virou série."""
    escola_id = com_notas["escola"].id
    ana = com_notas["alunos"][0]
    cliente.get(f"/api/v1/escolas/{escola_id}/ranking",
                headers={"User-Agent": "Mozilla/5.0 Chrome/140"})
    cliente.get(f"/api/v1/escolas/{escola_id}/alunos/{ana.id}/perfil",
                headers={"X-Constela-Cliente": "mobile/1.4.0"})

    templates = {getattr(r, "path", None) for r in app.routes}
    amostras = _amostras()
    assert amostras, "o contador nem foi registrado"
    for rotulos, _valor in amostras:
        base, _, variante = rotulos["rota"].partition("?")
        assert base in templates, rotulos
        assert not variante or variante in obs.VARIANTES_ROTA, rotulos
        assert _CLIENTE_VALIDO.match(rotulos["cliente"]), rotulos
    assert _total(ROTA_RANKING, "web") >= 1
    assert _total(ROTA_PERFIL, "mobile/1.4.0") >= 1


@pytest.mark.parametrize("cabecalhos, esperado", [
    ({b"user-agent": b"okhttp/4.12.0"}, "mobile-android"),
    ({b"user-agent": b"Expo/2.32 CFNetwork/1568.100.1 Darwin/24.0.0"}, "mobile-ios"),
    ({b"user-agent": b"Mozilla/5.0 (Windows NT 10.0) Chrome/140"}, "web"),
    ({b"user-agent": b"curl/8.4.0"}, "outro"),
    ({}, "outro"),
    # Cabeçalho declarado bem formado: tipo/versão.
    ({b"x-constela-cliente": b"mobile/1.4.0", b"user-agent": b"okhttp/4.12.0"},
     "mobile/1.4.0"),
    ({b"x-constela-cliente": b"WEB/2.0"}, "web/2.0"),
    # Mal formado: ignorado, vale o User-Agent.
    ({b"x-constela-cliente": b"mobile/1.4.0-beta; DROP", b"user-agent": b"okhttp/4"},
     "mobile-android"),
    ({b"x-constela-cliente": b"desktop/1.0"}, "outro"),
    ({b"x-constela-cliente": b"mobile/" + b"9" * 50}, "outro"),
])
def test_cliente_da_requisicao_reduz_a_um_conjunto_fechado(
        monkeypatch, cabecalhos, esperado):
    monkeypatch.setattr(obs, "_versoes_admitidas", set())
    escopo = {"headers": list(cabecalhos.items())}
    assert obs.cliente_da_requisicao(escopo) == esperado


def test_versoes_declaradas_tem_teto(monkeypatch):
    """A versão vem do cliente: sem teto, `mobile/1.0.1`, `mobile/1.0.2`, …
    seriam uma série cada. Passou do teto, vira `mobile/outra`."""
    monkeypatch.setattr(obs, "_versoes_admitidas", set())
    monkeypatch.setattr(obs, "MAX_VERSOES_DECLARADAS", 2)

    def declarar(versao: str) -> str:
        return obs.cliente_da_requisicao(
            {"headers": [(b"x-constela-cliente", f"mobile/{versao}".encode())]})

    assert declarar("1.0.0") == "mobile/1.0.0"
    assert declarar("1.1.0") == "mobile/1.1.0"
    assert declarar("1.2.0") == "mobile/outra"
    assert declarar("1.0.0") == "mobile/1.0.0"   # já admitida continua


# --- Puramente aditivo ------------------------------------------------------------

def test_fora_de_uma_requisicao_http_nao_conta():
    """Função da rota chamada direto em Python (teste, script): sem HTTP, sem
    métrica — e sem erro."""
    antes = _total_geral()
    obs.registrar_legado_nota_geral()
    assert _total_geral() == antes


def test_telemetria_nunca_derruba_nem_muda_a_resposta(cliente, com_notas, monkeypatch):
    escola_id = com_notas["escola"].id
    url = f"/api/v1/escolas/{escola_id}/ranking"
    normal = cliente.get(url)
    assert normal.status_code == 200, normal.text

    class _Quebrado:
        def labels(self, *_a, **_k):
            raise RuntimeError("prometheus fora do ar")

    monkeypatch.setattr(obs, "_M_LEGADO", _Quebrado())
    com_falha = cliente.get(url)
    assert com_falha.status_code == 200, com_falha.text
    assert com_falha.json() == normal.json()


# --- Limitação de infra registrada ------------------------------------------------

def test_o_sensor_4_AINDA_nao_soma_os_workers():
    """ACHADO REGISTRADO, não corrigido (infra; revisão de 2026-10-12): o
    contador vive na memória de cada worker do uvicorn, e o /metrics serializa
    só o processo que atendeu a coleta. Com 2 workers, cada coleta mostra
    metade da verdade, e tudo zera a cada deploy — o Sensor 4 ainda não sustenta
    o critério do Gatilho 1 ("== 0 por 2 ciclos letivos, série preservada").

    Corrigir é mudança de infraestrutura/produção, fora desta entrega: o passo a
    passo está no comentário do Sensor 4 em `app/core/observabilidade.py`.
    Este teste existe para o fato ficar VISÍVEL e cai quando alguém somar os
    workers — a queda dele é o lembrete de atualizar aquele comentário e o
    `docs/plano-retirada-nota-geral.md`. Ainda faltará guardar a série num
    Prometheus com retenção longa, que nenhum teste daqui enxerga."""
    import inspect
    from pathlib import Path

    entrypoint = (Path(__file__).resolve().parents[1] / "entrypoint.sh").read_text(
        encoding="utf-8")
    assert '--workers "${WEB_CONCURRENCY:-2}"' in entrypoint
    assert "PROMETHEUS_MULTIPROC_DIR" not in entrypoint
    assert "MultiProcessCollector" not in inspect.getsource(obs.render_metricas)
