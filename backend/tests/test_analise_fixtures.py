"""Exemplos de resposta da análise educacional para os testes do WEB
(``apps/web/src/test/fixtures/analise/*.json``) — gerados AQUI, com os mundos INVENTADOS
de ``test_analise_base`` e ``test_analise_relacao`` (decisão D13: nenhum número oficial
real), pelas MESMAS rotas que a tela chama.

* Sempre: cada exemplo gravado tem a MESMA forma (as mesmas chaves, em todos os níveis)
  da resposta de agora — se a API mudar, este teste acusa o exemplo defasado.
* Para regravar: ``GERAR_FIXTURES_ANALISE=1 python -m pytest tests/test_analise_fixtures.py``
  (as respostas são determinísticas: datas, ids e "hoje" fixos).
"""
import json
import os
from pathlib import Path

import pytest

from tests.test_analise_base import HOJE, mundo_plataformas
from tests.test_analise_relacao import mundo_correlato

PASTA = (Path(__file__).resolve().parents[2] / "apps" / "web" / "src" / "test" / "fixtures"
         / "analise")
GERAR = os.environ.get("GERAR_FIXTURES_ANALISE") == "1"


@pytest.fixture()
def respostas(db, cliente_global, monkeypatch) -> dict[str, tuple[str, dict, int]]:
    monkeypatch.setattr("app.routers.analise.hoje_br", lambda: HOJE)
    m = mundo_plataformas(db)
    correlato = mundo_correlato(db)
    rede, alfa, gama = m["rede"].id, m["escolas"]["alfa"].id, m["escolas"]["gama"].id
    base = f"/api/v1/redes/{rede}/analise"
    pedidos = {
        "indicadores": (f"{base}/indicadores", {},
                        "Catálogo da rede: indicadores, destaques, estimativas, escolas e alertas"),
        "indicador_ica": (f"{base}/indicadores/ica", {},
                          "ICA da rede: 2023 sem resultado (participação baixa), 2024 empate com "
                          "a meta (inconclusivo), SP e Brasil como contexto"),
        "indicador_saresp_serie": (f"{base}/indicadores/saresp",
                                   {"etapa": "5_ano", "componente": "lp"},
                                   "SARESP 5º ano LP: rede municipal, Estado (mesma rede) e rede "
                                   "estadual (contexto)"),
        "indicador_saresp_escola": (f"{base}/indicadores/saresp",
                                    {"etapa": "2_ano", "componente": "mt", "escola_id": alfa},
                                    "SARESP de uma escola (sem número: motivo) com a rede de "
                                    "referência e as quebras de escala do 2º ano"),
        "indicador_saresp_escolas": (f"{base}/indicadores/saresp",
                                     {"visao": "escolas", "edicao": 2025},
                                     "Visão por escolas (ordem de nome, instável com TPS = 0, "
                                     "ausências com motivo)"),
        "indicador_ideb": (f"{base}/indicadores/ideb", {},
                           "Ideb da rede: metas só até 2021, 2023 sem meta"),
        "indicador_ideb_escolas": (f"{base}/indicadores/ideb", {"visao": "escolas", "edicao": 2023},
                                   "Ideb 2023 por escola: o número gravado antes, sem o registro "
                                   "do arquivo oficial, aparece marcado (proveniencia = "
                                   "sem_registro); ausências com motivo"),
        "indicador_iee_escolas": (f"{base}/indicadores/iee", {"visao": "escolas", "edicao": 2025},
                                  "IEE por escola com a meta e o ICM oficial"),
        "erro_ica_por_escola": (f"{base}/indicadores/ica", {"escola_id": alfa},
                                "400: o ICA não existe por escola"),
        "plataformas": (f"{base}/plataformas", {},
                        "Elefante e Matific por escola × série (célula pequena suprimida com "
                        "motivo único e a vizinha junto, blocos só das séries visíveis, escola "
                        "sem coleta com métrica nula)"),
        "plataformas_serie_3": (f"{base}/plataformas", {"serie": 3}, "Plataformas só do 3º ano"),
        "relacao_nao_calculavel": (f"{base}/relacao",
                                   {"indicador": "saresp", "componente": "mt",
                                    "metrica": "estrelas_por_aluno"},
                                   "Relação recusada (SARESP 2025 × plataformas 2026), com os "
                                   "pares lado a lado e o motivo próprio de cada escola"),
        "relacao_ica": (f"{base}/relacao", {"indicador": "ica"},
                        "Relação recusada: o ICA é da rede"),
        "relacao_calculavel": (f"/api/v1/redes/{correlato['rede'].id}/analise/relacao",
                               {"indicador": "saresp", "etapa": "5_ano", "componente": "lp",
                                "edicao": 2026, "metrica": "livros_por_aluno"},
                               "Relação calculável (cenário SINTÉTICO do mesmo ano: SARESP 2026 "
                               "inventado × Elefante 2026)"),
        "escola": (f"/api/v1/escolas/{alfa}/analise", {},
                   "Análise de uma escola: indicadores dela, rede de referência, plataformas"),
        "escola_sem_inep": (f"/api/v1/escolas/{gama}/analise", {},
                            "Análise de uma escola sem código INEP"),
    }
    saida = {}
    for nome, (url, params, descricao) in pedidos.items():
        r = cliente_global.get(url, params=params)
        assert r.status_code == (400 if nome.startswith("erro_") else 200), (nome, r.text)
        saida[nome] = (url, params, descricao, r.json())
    return saida


def _forma(obj):
    """A forma de um JSON: as chaves de cada objeto (recursivo); de uma lista, a forma do
    primeiro item; de um mapa de fontes ("12": {...}), a de um valor."""
    if isinstance(obj, dict):
        if obj and all(k.isdigit() for k in obj):
            return {"<id>": _forma(next(iter(obj.values())))}
        return {k: _forma(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_forma(obj[0])] if obj else []
    return None


def _juntar(a, b):
    """Duas formas são compatíveis se as chaves batem onde as duas têm conteúdo (lista
    vazia ou valor nulo de um lado não acusa)."""
    if isinstance(a, dict) and isinstance(b, dict):
        assert set(a) == set(b), (sorted(set(a) ^ set(b)))
        for k in a:
            _juntar(a[k], b[k])
    elif isinstance(a, list) and isinstance(b, list) and a and b:
        _juntar(a[0], b[0])


def test_exemplos_para_o_web_estao_em_dia(respostas):
    if GERAR:
        PASTA.mkdir(parents=True, exist_ok=True)
        indice = []
        for nome, (url, params, descricao, corpo) in respostas.items():
            (PASTA / f"{nome}.json").write_text(
                json.dumps(corpo, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
                newline="\n")
            indice.append({"arquivo": f"{nome}.json", "rota": f"GET {url}", "params": params,
                           "descricao": descricao})
        (PASTA / "indice.json").write_text(
            json.dumps({"dados": "INVENTADOS (decisão D13) — gerados por "
                                 "backend/tests/test_analise_fixtures.py",
                        "exemplos": indice}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n")
    if not PASTA.exists():
        pytest.skip("cópia sem apps/web: os exemplos do web não estão aqui")
    for nome, (_, _, _, corpo) in respostas.items():
        arquivo = PASTA / f"{nome}.json"
        assert arquivo.exists(), (f"falta o exemplo {arquivo.name}: regrave com "
                                  "GERAR_FIXTURES_ANALISE=1")
        gravado = json.loads(arquivo.read_text(encoding="utf-8"))
        _juntar(_forma(gravado), _forma(corpo))


def test_exemplos_sem_dado_pessoal(respostas):
    for nome, (_, _, _, corpo) in respostas.items():
        texto = json.dumps(corpo, ensure_ascii=False)
        assert "aluno_id" not in texto and "Criança Fictícia" not in texto, nome
