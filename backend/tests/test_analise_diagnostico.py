"""Análise educacional — o DIAGNÓSTICO PEDAGÓGICO exploratório
(``GET /redes/{id}/analise/diagnostico``).

O que estes testes sustentam:

* permissões: ``exigir_rede`` — a Secretaria da PRÓPRIA rede e o admin global; Secretaria
  de outra rede, coordenação, professor e admin de escola, 403; rede inexistente, 404;
* nenhum ``aluno_id``, nome de criança ou turma na resposta (varredura do JSON);
* escolas em ordem alfabética (sem acento e sem caixa) — nunca ranking;
* TOLERÂNCIAS na fronteira: diferença IGUAL à tolerância já é acima/abaixo; menor, na média
  (SARESP 5 pontos, Ideb 0,2, participação 5 p.p., intensidade 15% da rede);
* média instável (TPS = 0) e o IEE calculado com ela não geram sinal de posição nem de
  tendência; a tendência não atravessa a quebra de escala do 2º ano;
* a Estimativa Constela e o número sem registro do arquivo oficial nunca entram em
  ``oficiais`` (viram sinal de dados);
* a comparabilidade por ano (exploratória × mesmo ano — só pelos sinais COM direção, com um
  ano letivo só e o período dentro dele), as categorias por componente e os níveis de
  acompanhamento — num mundo desenhado para cobrir cada caso;
* k = 5: escola suprimida fica sem número de plataforma e sem posição (sinal de dados);
* os números de plataforma são os da rota de plataformas (nada recalculado);
* banco igual antes e depois (só leitura); rota só GET e fora do painel público.

Dados INVENTADOS (decisão D13): o município, os INEPs, as escolas, as crianças e todos os
valores são fictícios.
"""
import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.security import hash_senha
from app.main import app
from app.models import Aluno, Turma, Usuario
from app.services.analise import diagnostico as svc
from app.services.analise import indicadores as ind_svc
from tests.test_analise_base import (HOJE, NOMES, PREFIXO_CRIANCA, importacao, ler, livros,
                                     mundo_plataformas, nova_escola, nova_rede, ref, resultado,
                                     retrato_elefante, retrato_matific, saresp_oficial,
                                     turma_com_alunos)

URL = "/api/v1/redes/{rede}/analise/diagnostico"
URL_EVOLUCAO = "/api/v1/redes/{rede}/analise/plataformas/evolucao"
MUN_DIAG = "3599961"            # IBGE INVENTADO
NOMES_DIAG = {"a": "EMEF Diag Acácia", "b": "EMEF Diag Bétula", "c": "EMEF Diag Cedro",
              "d": "EMEF Diag Dália", "e": "EMEF Diag Ébano", "f": "EMEF Diag Figueira",
              "g": "EMEF Diag Gameleira", "h": "EMEF Diag Hortênsia"}


@pytest.fixture(autouse=True)
def _hoje(monkeypatch):
    monkeypatch.setattr("app.routers.analise.hoje_br", lambda: HOJE)


def _get(cliente, rede, **params):
    r = cliente.get(URL.format(rede=rede.id), params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _escola(dados, escola):
    return next(e for e in dados["escolas"] if e["id"] == escola.id)


def _linha(escola_json, rotulo):
    return next((o for o in escola_json["oficiais"] if o["rotulo"] == rotulo), None)


def _codigos(escola_json, **filtro):
    return [s["codigo"] for s in escola_json["sinais"]
            if all(s[k] == v for k, v in filtro.items())]


# --- O mundo do diagnóstico ----------------------------------------------------------------

def mundo_diagnostico(db) -> dict:
    """8 escolas desenhadas para cobrir cada leitura (SARESP do 5º ano, rede municipal
    200,0 em LP e 210,0 em MT na edição 2025; plataformas de 2026, 6 crianças por escola):

    * Acácia — LP 205,0 (+5,0: acima, NA fronteira; subiu de 200,0) e uso alto → convergente
      favorável; MT 220,0 e Matific alto → convergente favorável;
    * Bétula — LP 190,0 (abaixo; caiu de 195,0) e uso baixo → convergente de atenção
      (prioritário); MT 200,0 e Matific baixo → convergente de atenção;
    * Cedro — LP 190,0 (abaixo) e uso alto → divergente (uso alto) → acompanhar;
    * Dália — LP 210,0 (acima; 214,0 → 210,0 é estável) e uso baixo → divergente (uso baixo)
      → oportunidade; MT 212,0 (na média) → inconclusiva;
    * Ébano — LP 204,9 (+4,9: na média) e uso na média → inconclusiva → sem sinal;
    * Figueira — sem INEP e sem crianças → dados insuficientes;
    * Gameleira — SARESP com TPS = 0 (instável), sem plataforma → sem sinal;
    * Hortênsia — só a Estimativa Constela do SARESP e um Ideb sem registro → dados
      insuficientes.

    Rede das plataformas = a soma das 5 primeiras: participação 66,7% e 1,67 livro por
    aluno (Elefante); 66,7% e 10,67 atividades por aluno (Matific)."""
    rede = nova_rede(db, nome="Rede Fictícia do Diagnóstico", codigo=MUN_DIAG, codmun="9961")
    ineps = {k: f"359961{i:02d}" for i, k in enumerate("abcdegh", start=1)}
    e = {k: nova_escola(db, rede, NOMES_DIAG[k], ineps.get(k)) for k in NOMES_DIAG}
    imp_mun = importacao(db, "saresp", "seduc_saresp_municipio", 2025, alvo=MUN_DIAG,
                         resumo={"territorios": {MUN_DIAG: "MUNICIPIO DIAG"}})
    for comp, valor in (("lp", 200.0), ("mt", 210.0)):
        ref(db, "saresp", imp_mun, edicao=2025, indicador="proficiencia", etapa="5_ano",
            componente=comp, valor=valor, casas=1, codigo=MUN_DIAG, unidade="escala_saresp")
    iee24 = importacao(db, "iee", "seduc_iee", 2024, alvo=MUN_DIAG, nome="iee_diag_2024.csv")
    iee25 = importacao(db, "iee", "seduc_iee", 2025, alvo=MUN_DIAG, nome="iee_diag_2025.csv")
    s24 = {"a": 200.0, "b": 195.0, "d": 214.0, "e": 204.0}
    s25 = {"a": (205.0, 220.0), "b": (190.0, 200.0), "c": (190.0, 220.0),
           "d": (210.0, 212.0), "e": (204.9, 210.0)}
    for k, lp in s24.items():
        saresp_oficial(db, iee24, e[k], 2024, lp5=lp, iee=5.0, meta=4.8, icm=1, codigo=MUN_DIAG)
    for k, (lp, mt) in s25.items():
        saresp_oficial(db, iee25, e[k], 2025, lp5=lp, mt5=mt, lp2=148.0 if k == "a" else None,
                       iee=5.1, meta=4.9, icm=1, codigo=MUN_DIAG)
    saresp_oficial(db, iee25, e["g"], 2025, lp5=150.0, mt5=150.0, tps=0, codigo=MUN_DIAG)
    # Hortênsia: a Estimativa Constela (sem importação) e um Ideb do 1 clique (sem registro).
    resultado(db, "saresp", e["h"], edicao=2025, indicador="proficiencia", etapa="5_ano",
              componente="portugues", valor=233.3, imp=None)
    importacao(db, "ideb", "inep_ideb_escolas", 2023, alvo=MUN_DIAG,
               resumo={"edicoes": [2023], "anos_meta": [],
                       "escolas_casadas": [{"escola_id": e["h"].id, "codigo_inep": ineps["h"]}]})
    resultado(db, "ideb", e["h"], edicao=2023, indicador="ideb", etapa="anos_iniciais",
              componente=None, valor=7.7, imp=None, unidade="indice")
    # Plataformas de 2026: (crianças que leram, livros de cada uma) e (com atividade, quantas).
    elefante = {"a": [3] * 6, "b": [1, 1], "c": [3] * 6, "d": [1, 1], "e": [3, 3, 2, 2]}
    matific = {"a": [20] * 6, "b": [5, 5], "c": [20] * 6, "d": [5, 5], "e": [15] * 4}
    for k in "abcde":
        escola = e[k]
        lv = livros(db, escola, 3, "K")
        for i, a in enumerate(turma_com_alunos(db, escola, "5º Ano", 6)):
            retrato_elefante(db, escola, a, datetime(2026, 9, 30, 3, 10))
            if i < len(elefante[k]):
                ler(db, escola, a, lv[:elefante[k][i]], datetime(2026, 6, 1, 10, 0))
            atv = matific[k][i] if i < len(matific[k]) else 0
            retrato_matific(db, escola, a, datetime(2026, 9, 30, 3, 20), atividades=atv,
                            estrelas=2 * atv)
    db.commit()
    return {"rede": rede, "escolas": e, "ineps": ineps}


# --- Permissões ------------------------------------------------------------------------------

SENHA = "s3nh4diagnostico"
PERFIS = ("global", "secretaria", "secretaria_outra", "coordenador", "professor",
          "admin_escola")


@pytest.fixture()
def perfis(db):
    base = mundo_plataformas(db)
    rede, alfa = base["rede"], base["escolas"]["alfa"]
    vizinha = nova_rede(db, nome="Rede Fictícia Vizinha", codigo="3599908", codmun="9998")
    nova_escola(db, vizinha, "EMEF Fictícia da Vizinha", "35990801")
    usuarios = {
        "global": {"cargo": "admin", "is_global": True},
        "secretaria": {"cargo": "coordenador", "rede_id": rede.id},
        "secretaria_outra": {"cargo": "coordenador", "rede_id": vizinha.id},
        "coordenador": {"cargo": "coordenador", "escola_id": alfa.id},
        "professor": {"cargo": "professor", "escola_id": alfa.id},
        "admin_escola": {"cargo": "admin", "escola_id": alfa.id},
    }
    hash_ = hash_senha(SENHA)
    for perfil, campos in usuarios.items():
        db.add(Usuario(nome=perfil, email=f"{perfil}@diag.local", senha_hash=hash_, **campos))
    db.commit()
    clientes = {}
    for perfil in usuarios:
        c = TestClient(app)
        r = c.post("/api/v1/auth/login", data={"username": f"{perfil}@diag.local",
                                                "password": SENHA})
        assert r.status_code == 200, r.text
        c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        clientes[perfil] = c
    return {**base, "vizinha": vizinha, "c": clientes}


def _matriz(perfis, url, permitidos, params=None):
    for perfil in PERFIS:
        r = perfis["c"][perfil].get(url, params=params or {})
        esperado = 200 if perfil in permitidos else 403
        assert r.status_code == esperado, (perfil, r.status_code, r.text)


@pytest.mark.parametrize("modelo", [URL, URL_EVOLUCAO])
def test_permissoes_secretaria_da_rede_e_global(perfis, modelo):
    _matriz(perfis, modelo.format(rede=perfis["rede"].id), {"global", "secretaria"})
    # A rede vizinha: só o global e a Secretaria DELA.
    _matriz(perfis, modelo.format(rede=perfis["vizinha"].id), {"global", "secretaria_outra"})
    assert perfis["c"]["global"].get(modelo.format(rede=999999)).status_code == 404
    assert TestClient(app).get(modelo.format(rede=perfis["rede"].id)).status_code == 401


def test_permissoes_da_evolucao_so_da_escola(perfis):
    """A evolução da ficha (``so_escola``) não abre nada: as permissões são as da evolução
    da rede, e a escola de outra rede continua 404."""
    alfa = perfis["escolas"]["alfa"].id
    url = URL_EVOLUCAO.format(rede=perfis["rede"].id)
    _matriz(perfis, url, {"global", "secretaria"}, params={"escola_id": alfa, "so_escola": True})
    assert TestClient(app).get(url, params={"escola_id": alfa,
                                            "so_escola": True}).status_code == 401
    r = perfis["c"]["secretaria_outra"].get(
        URL_EVOLUCAO.format(rede=perfis["vizinha"].id), params={"escola_id": alfa,
                                                                "so_escola": True})
    assert r.status_code == 404


def test_rotas_novas_so_get_e_fora_do_painel_publico(perfis):
    novas = [r for r in app.routes if getattr(r, "path", "").endswith(
        ("/analise/diagnostico", "/analise/plataformas/evolucao"))]
    assert len(novas) == 2
    assert all(r.methods <= {"GET", "HEAD"} and "/publico" not in r.path for r in novas)
    rede = perfis["rede"].id
    for modelo in (URL, URL_EVOLUCAO):
        assert perfis["c"]["global"].post(modelo.format(rede=rede)).status_code == 405


def _contagens(db) -> dict[str, int]:
    return {t.name: db.execute(select(func.count()).select_from(t)).scalar()
            for t in Base.metadata.sorted_tables}


def test_banco_igual_antes_e_depois(db, perfis):
    """Só leitura: nenhum flush com objeto novo, alterado ou apagado, e as contagens de
    todas as tabelas iguais — com todos os perfis, nas duas rotas novas."""
    rede = perfis["rede"].id
    pedidos = [(URL.format(rede=rede), {}),
               (URL.format(rede=rede), {"periodo": "bimestre_3"}),
               (URL_EVOLUCAO.format(rede=rede), {}),
               (URL_EVOLUCAO.format(rede=rede), {"serie": 3})]
    escritas = []

    def _antes_do_flush(sessao, _ctx, _inst):
        if sessao.new or sessao.dirty or sessao.deleted:
            escritas.append((len(sessao.new), len(sessao.dirty), len(sessao.deleted)))

    antes = _contagens(db)
    event.listen(Session, "before_flush", _antes_do_flush)
    try:
        for perfil in PERFIS:
            for url, params in pedidos:
                perfis["c"][perfil].get(url, params=params)
    finally:
        event.remove(Session, "before_flush", _antes_do_flush)
    db.expire_all()
    assert escritas == []
    assert _contagens(db) == antes


# --- Sem dado pessoal, ordem, forma ------------------------------------------------------------

def test_nenhum_dado_pessoal_de_crianca(db, cliente_global):
    m = mundo_plataformas(db)
    texto = cliente_global.get(URL.format(rede=m["rede"].id)).text
    ids_rede = {e.id for e in m["escolas"].values()}
    da_rede = [a.nome for a in db.query(Aluno).all() if a.escola_id in ids_rede]
    assert len(da_rede) == 29 and all(n.startswith(PREFIXO_CRIANCA) for n in da_rede)
    nomes = [a.nome for a in db.query(Aluno).all()]          # todas as crianças da base
    assert "aluno_id" not in texto and PREFIXO_CRIANCA not in texto
    for nome in nomes:
        assert nome not in texto
    assert '"turma"' not in texto and "turma_id" not in texto
    # Nem o NOME de turma ("3º Ano A") — a série aparece só como etapa ("5º ano").
    turmas = [t.nome for t in db.query(Turma).all()]
    assert turmas and not [t for t in turmas if t in texto]


def test_escolas_em_ordem_alfabetica_e_forma_do_contrato(db, cliente_global):
    m = mundo_plataformas(db)
    dados = _get(cliente_global, m["rede"])
    assert [e["nome"] for e in dados["escolas"]] == [
        NOMES["ebano"], NOMES["alfa"], NOMES["beta"], NOMES["delta"], NOMES["gama"]]
    assert set(dados) >= {"rede", "janela", "gerado_em", "criterios", "referencias_rede",
                          "escolas", "resumo", "limitacoes", "metodologia", "fontes"}
    assert dados["rede"] == {"id": m["rede"].id, "nome": m["rede"].nome}
    assert dados["janela"]["rotulo"] == "Ano letivo 2026" and dados["k_minimo"] == 5
    crit = dados["criterios"]
    assert crit["n_minimo_escolas_comparacao"] == 3 and crit["regras"]
    assert crit["tolerancias"] == {"participacao_pp": 5.0, "intensidade_pct_da_rede": 15.0,
                                   "ideb": 0.2, "iee": 0.2, "saresp": 5.0, "saeb": 5.0}
    for e in dados["escolas"]:
        assert set(e) >= {"id", "nome", "codigo_inep", "pendencias", "oficiais", "plataformas",
                          "sinais", "leituras", "acompanhamento"}
        for o in e["oficiais"]:
            assert set(o) >= {"indicador", "rotulo", "etapa", "componente", "edicao", "valor",
                              "casas", "meta", "situacao_meta", "instavel", "fonte_id",
                              "valor_rede", "diferenca_rede", "posicao_rede",
                              "motivo_sem_comparacao", "anterior", "tendencia"}
            # Sem posição, SEMPRE o motivo (ausência ≠ zero).
            assert (o["posicao_rede"] is None) == (o["motivo_sem_comparacao"] is not None)
        for s in e["sinais"]:
            assert set(s) >= {"codigo", "eixo", "componente", "natureza", "direcao", "texto",
                              "referencia"}
            assert s["eixo"] in ("avaliacao", "plataforma", "dados")
            assert s["componente"] in ("lp", "mt", "geral")
            assert s["natureza"] in ("oficial", "calculado", "plataforma", "dados")
            assert s["direcao"] in ("atencao", "favoravel", "informativo")
            # Falta de dado nunca vira atenção.
            assert s["eixo"] != "dados" or s["direcao"] == "informativo"
        for c in ("lp", "mt"):
            lt = e["leituras"][c]
            assert lt["avaliacao"] in ("favoravel", "atencao", "misto", "sem_dado")
            assert lt["plataforma"] in ("favoravel", "atencao", "misto", "sem_dado")
            assert lt["categoria"] in svc.CATEGORIAS
            assert (lt["categoria"] == "inconclusiva") == (lt["motivo"] is not None)
        assert e["acompanhamento"]["nivel"] in svc.NIVEIS and e["acompanhamento"]["motivos"]
    # Cada fonte citada num número oficial está em `fontes`.
    ids = {o[k] for e in dados["escolas"] for o in e["oficiais"]
           for k in ("fonte_id", "fonte_rede_id") if o[k] is not None}
    assert ids and {str(i) for i in ids} <= set(dados["fontes"])


def test_ordem_alfabetica_sem_acento_no_mundo_do_diagnostico(db, cliente_global):
    m = mundo_diagnostico(db)
    dados = _get(cliente_global, m["rede"])
    # "Ébano" entre "Dália" e "Figueira" (sem acento), não no fim (ponto de código).
    assert [e["nome"] for e in dados["escolas"]] == [NOMES_DIAG[k] for k in "abcdefgh"]


# --- Avaliações oficiais: tolerâncias, instável, quebra, estimativa ----------------------------

def test_posicao_contra_a_rede_com_tolerancia_na_fronteira(db, cliente_global):
    m = mundo_diagnostico(db)
    dados = _get(cliente_global, m["rede"])
    esc = {k: _escola(dados, m["escolas"][k]) for k in "abcde"}
    lp = {k: _linha(esc[k], "SARESP · 5º ano · LP") for k in "abcde"}
    # +5,0 = a tolerância: já é "acima"; +4,9: na média; −10,0: abaixo.
    assert (lp["a"]["diferenca_rede"], lp["a"]["posicao_rede"]) == (5.0, "acima")
    assert (lp["e"]["diferenca_rede"], lp["e"]["posicao_rede"]) == (4.9, "na_media")
    assert (lp["b"]["diferenca_rede"], lp["b"]["posicao_rede"]) == (-10.0, "abaixo")
    assert lp["a"]["valor_rede"] == 200.0 and lp["a"]["casas_diferenca"] == 1
    assert "acima_da_rede" in _codigos(esc["a"], componente="lp", natureza="calculado")
    assert "na_media_da_rede" in _codigos(esc["e"], componente="lp", direcao="informativo")
    # Tendência: +5,0 subiu; −5,0 caiu; −4,0 e +0,9 estáveis.
    assert (lp["a"]["anterior"]["edicao"], lp["a"]["tendencia"]) == (2024, "subiu")
    assert lp["b"]["tendencia"] == "caiu" and lp["d"]["tendencia"] == "estavel"
    assert lp["e"]["tendencia"] == "estavel" and lp["c"]["anterior"] is None
    assert lp["c"]["motivo_sem_tendencia"].startswith("primeira edição")
    # Nas referências da rede, o número usado na comparação.
    (rede_lp,) = [r for r in dados["referencias_rede"]
                  if (r["indicador"], r["etapa"], r["componente"]) == ("saresp", "5_ano", "lp")]
    assert (rede_lp["edicao"], rede_lp["valor"], rede_lp["referencia"]) == (
        2025, 200.0, "SARESP 2025 · 5º ano · LP")


def test_ideb_na_fronteira_de_0_2_e_meta_do_iee(db, cliente_global):
    m = mundo_plataformas(db)
    dados = _get(cliente_global, m["rede"])
    alfa, beta = _escola(dados, m["escolas"]["alfa"]), _escola(dados, m["escolas"]["beta"])
    ideb = _linha(alfa, "Ideb")
    # 6,3 × 6,1 = 0,2 (a tolerância): acima — e 5,5 → 6,3 subiu.
    assert (ideb["edicao"], ideb["diferenca_rede"], ideb["posicao_rede"]) == (2023, 0.2, "acima")
    assert ideb["tendencia"] == "subiu" and ideb["meta"] is None
    assert _linha(beta, "Ideb")["posicao_rede"] == "abaixo"
    # IEE: sem rede (só meta e tendência); meta pelo ICM oficial.
    iee = _linha(alfa, "IEE")
    assert iee["valor_rede"] is None and "por escola" in iee["motivo_sem_comparacao"]
    meta = next(s for s in alfa["sinais"] if s["codigo"] == "meta_nao_atingida")
    assert (meta["natureza"], meta["direcao"], meta["referencia"]) == (
        "oficial", "atencao", "IEE 2025")
    # Meta oficial não atingida → acompanhar, com a referência no motivo.
    assert alfa["acompanhamento"]["nivel"] == "acompanhar"
    assert any("IEE 2025" in t for t in alfa["acompanhamento"]["motivos"])
    # Saeb da escola em 2023 sem a rede em 2023: sem posição, com o motivo.
    saeb = _linha(alfa, "Saeb · 5º ano · LP")
    assert saeb["posicao_rede"] is None and "2023" in saeb["motivo_sem_comparacao"]


def test_media_instavel_nao_gera_sinal_de_posicao_nem_de_tendencia(db, cliente_global):
    m = mundo_plataformas(db)
    beta = _escola(_get(cliente_global, m["rede"]), m["escolas"]["beta"])
    lp = _linha(beta, "SARESP · 5º ano · LP")
    assert lp["instavel"] is True and lp["valor"] == 190.7
    assert lp["posicao_rede"] is None and lp["valor_rede"] is None
    assert "instável" in lp["motivo_sem_comparacao"] and lp["tendencia"] is None
    saresp = [s for s in beta["sinais"] if s["indicador"] == "saresp"]
    assert {s["codigo"] for s in saresp} == {"media_instavel"}
    assert all(s["eixo"] == "dados" and s["direcao"] == "informativo" for s in saresp)
    # O IEE com TPS = 0: a meta oficial continua (é o ICM), mas sem sinal de tendência.
    iee = [s["codigo"] for s in beta["sinais"] if s["indicador"] == "iee"]
    assert "meta_atingida" in iee and "media_instavel" in iee
    assert not {"subiu", "caiu", "estavel"} & set(iee)
    assert _linha(beta, "IEE")["tps_zero"] is True


def _serie_teste(chave, etapa, comp, pontos, papel="principal", abrangencia="escola"):
    return ind_svc.serie(f"t_{chave}", rotulo="t", papel=papel, abrangencia=abrangencia,
                         rede_ensino="municipal", mesma_rede=True, comparavel=True,
                         pontos=pontos, etapa=etapa, componente=comp)


def test_tendencia_nao_atravessa_quebra_nem_media_instavel():
    p = ind_svc.ponto
    # SARESP do 2º ano: a quebra de escala 2025 → 2026 (a da consulta oficial).
    quebras = ind_svc.INDICADORES["saresp"].quebras("2_ano")
    escola = _serie_teste("saresp", "2_ano", "lp", [p(2025, chave="saresp", valor=150.0, casas=1),
                                                    p(2026, chave="saresp", valor=170.0, casas=1)])
    linha = svc._linha_oficial("saresp", "2_ano", "lp", escola, None, quebras)
    assert linha["edicao"] == 2026 and linha["anterior"] is None and linha["tendencia"] is None
    assert "2026" in linha["motivo_sem_tendencia"]
    # IEE com TPS = 0 na anterior: sem tendência, com o motivo próprio.
    iee = _serie_teste("iee", "anos_iniciais", None, [
        p(2024, chave="iee", valor=4.0, casas=2, tps_zero=True),
        p(2025, chave="iee", valor=5.0, casas=2, tps_zero=False)])
    linha = svc._linha_oficial("iee", "anos_iniciais", None, iee, None, [])
    assert linha["anterior"]["instavel"] is True and linha["tendencia"] is None
    # O motivo diz que a instável é a ANTERIOR (o IEE 2025 mostrado não é o de TPS = 0).
    assert "TPS = 0" in linha["motivo_sem_tendencia"]
    assert "edição anterior (2024)" in linha["motivo_sem_tendencia"]
    assert not [s for s in svc._sinais_da_linha(linha) if s["codigo"] in ("subiu", "caiu")]
    # IEE estável × subiu: a tolerância é 0,2.
    for antes, esperado in ((4.81, "estavel"), (4.80, "subiu")):
        serie = _serie_teste("iee", "anos_iniciais", None, [
            p(2024, chave="iee", valor=antes, casas=2), p(2025, chave="iee", valor=5.0, casas=2)])
        assert svc._linha_oficial("iee", "anos_iniciais", None, serie, None, [])[
            "tendencia"] == esperado


def test_so_a_edicao_anterior_instavel_nao_tira_a_posicao_nem_a_contradiz():
    """SARESP 5º ano LP: 2024 com TPS = 0 e 2025 estável, 8 pontos acima da rede. A posição
    contra a rede vale (a média de 2025 é estável); só a tendência some — e o motivo cita a
    edição ANTERIOR, sem dizer "não se compara com a rede" ao lado de "acima da rede" (na
    célula da aba Avaliações externas e no CSV)."""
    p = ind_svc.ponto
    escola = _serie_teste("saresp", "5_ano", "lp", [
        p(2024, chave="saresp", valor=150.0, casas=1, instavel=True),
        p(2025, chave="saresp", valor=208.0, casas=1)])
    rede = _serie_teste("saresp", "5_ano", "lp", [p(2025, chave="saresp", valor=200.0, casas=1)],
                        papel="referencia", abrangencia="municipio")
    linha = svc._linha_oficial("saresp", "5_ano", "lp", escola, rede, [])
    assert (linha["instavel"], linha["anterior"]["instavel"]) == (False, True)
    assert (linha["posicao_rede"], linha["diferenca_rede"]) == ("acima", 8.0)
    assert linha["motivo_sem_comparacao"] is None and linha["tendencia"] is None
    motivo = linha["motivo_sem_tendencia"]
    assert "não se compara com a rede" not in motivo
    assert "edição anterior (2024)" in motivo and "TPS = 0" in motivo
    # Sinais: a posição (favorável), sem tendência e sem "média instável" (a de 2025 é estável).
    assert {s["codigo"] for s in svc._sinais_da_linha(linha)} == {"acima_da_rede"}
    # A edição ATUAL instável continua com o motivo de sempre — o mesmo da posição (a tela
    # não o repete).
    atual = _serie_teste("saresp", "5_ano", "lp", [
        p(2024, chave="saresp", valor=200.0, casas=1),
        p(2025, chave="saresp", valor=150.0, casas=1, instavel=True)])
    linha = svc._linha_oficial("saresp", "5_ano", "lp", atual, rede, [])
    assert linha["posicao_rede"] is None and linha["tendencia"] is None
    assert linha["motivo_sem_tendencia"] == linha["motivo_sem_comparacao"] == svc.TEXTO_INSTAVEL


def test_estimativa_e_numero_sem_registro_ficam_fora_de_oficiais(db, cliente_global):
    m = mundo_plataformas(db)
    delta = _escola(_get(cliente_global, m["rede"]), m["escolas"]["delta"])
    assert delta["oficiais"] == []
    sinais = {s["codigo"]: s for s in delta["sinais"]}
    assert sinais["so_estimativa"]["referencia"] == "SARESP 2025 · Estimativa Constela"
    assert sinais["numero_sem_registro"]["referencia"] == "Ideb 2023"
    # O número sem registro não é chamado de estimativa; nenhum dos dois vira atenção.
    assert "estimativa" not in sinais["numero_sem_registro"]["texto"].lower()
    assert all(sinais[c]["eixo"] == "dados" and sinais[c]["direcao"] == "informativo"
               for c in ("so_estimativa", "numero_sem_registro"))
    texto = json.dumps(delta["oficiais"])
    assert "233.3" not in texto and "7.7" not in texto
    assert delta["acompanhamento"]["nivel"] == "dados_insuficientes"
    gama = _escola(_get(cliente_global, m["rede"]), m["escolas"]["gama"])
    assert gama["pendencias"] == ["sem_codigo_inep"]
    assert {"sem_codigo_inep", "sem_resultado_oficial"} <= set(_codigos(gama, eixo="dados"))


# --- Plataformas, categorias, níveis, comparabilidade ------------------------------------------

def test_categorias_e_niveis_no_mundo_do_diagnostico(db, cliente_global):
    m = mundo_diagnostico(db)
    dados = _get(cliente_global, m["rede"])
    esc = {k: _escola(dados, m["escolas"][k]) for k in NOMES_DIAG}
    lp = {k: esc[k]["leituras"]["lp"]["categoria"] for k in esc}
    mt = {k: esc[k]["leituras"]["mt"]["categoria"] for k in esc}
    assert lp == {"a": "convergente_favoravel", "b": "convergente_atencao",
                  "c": "divergente_uso_alto", "d": "divergente_uso_baixo", "e": "inconclusiva",
                  "f": "inconclusiva", "g": "inconclusiva", "h": "inconclusiva"}
    assert mt == {"a": "convergente_favoravel", "b": "convergente_atencao",
                  "c": "convergente_favoravel", "d": "inconclusiva", "e": "inconclusiva",
                  "f": "inconclusiva", "g": "inconclusiva", "h": "inconclusiva"}
    niveis = {k: esc[k]["acompanhamento"]["nivel"] for k in esc}
    assert niveis == {"a": "sem_sinal", "b": "prioritario", "c": "acompanhar",
                      "d": "oportunidade", "e": "sem_sinal", "f": "dados_insuficientes",
                      "g": "sem_sinal", "h": "dados_insuficientes"}
    # O motivo do prioritário traz as referências dos sinais (avaliação e plataforma).
    (motivo_b, *_resto) = esc["b"]["acompanhamento"]["motivos"]
    assert "SARESP 2025 · 5º ano · LP" in motivo_b and "Elefante · 01/01/2026" in motivo_b
    # Ébano: tudo na média — inconclusiva por FALTA DE SINAL, não por falta de dado.
    e_lp = esc["e"]["leituras"]["lp"]
    assert (e_lp["avaliacao"], e_lp["base"], e_lp["plataforma"]) == (
        "sem_dado", "componente", "sem_dado")
    assert "na média" in e_lp["motivo"] and "sem resultado" not in e_lp["motivo"]
    # Gameleira: SARESP instável → sem sinal do componente nem geral.
    g_lp = esc["g"]["leituras"]["lp"]
    assert g_lp["base"] is None and g_lp["avaliacao"] == "sem_dado"
    # "Sem sinal" sem nenhum sinal com direção (Gameleira: só a média instável) não passa por
    # tranquilidade: o motivo diz que não há comparação válida. A Acácia (convergente
    # favorável) e o Ébano (meta do IEE cumprida, o resto na média) ficam com o motivo geral.
    assert "sem comparação válida" in esc["g"]["acompanhamento"]["motivos"][0]
    for k in "ae":
        assert "sem comparação válida" not in esc[k]["acompanhamento"]["motivos"][0], k
    # Os textos das leituras põem as fontes lado a lado — nada de "mas", nem de causa; e o
    # lado da avaliação não diz "em relação à rede" (o sinal pode ser meta ou tendência).
    for e in esc.values():
        for c in ("lp", "mt"):
            texto = e["leituras"][c]["texto"].lower()
            assert " mas " not in texto and "por causa" not in texto and "devido" not in texto
            assert "graças" not in texto and "efeito" not in texto and "explica" not in texto
    assert "lados opostos" in esc["c"]["leituras"]["lp"]["texto"]
    assert "mesmo lado" in esc["b"]["leituras"]["lp"]["texto"]
    assert dados["resumo"]["por_nivel"] == {"prioritario": 1, "acompanhar": 1,
                                            "oportunidade": 1, "dados_insuficientes": 2,
                                            "sem_sinal": 3}
    assert dados["resumo"]["por_categoria"]["lp"] == {
        "convergente_favoravel": 1, "convergente_atencao": 1, "divergente_uso_alto": 1,
        "divergente_uso_baixo": 1, "inconclusiva": 4}
    assert dados["resumo"]["por_categoria"]["mt"]["convergente_favoravel"] == 2
    assert (dados["resumo"]["escolas_total"], dados["resumo"]["escolas_com_oficial"],
            dados["resumo"]["escolas_com_plataforma"]) == (8, 6, 5)
    assert dados["resumo"]["anos"] == {"avaliacao_mais_recente": 2025, "plataforma": 2026}


def test_posicao_das_plataformas_contra_a_rede(db, cliente_global):
    m = mundo_diagnostico(db)
    dados = _get(cliente_global, m["rede"])
    refs = dados["referencias_plataformas"]
    assert (refs["elefante"]["participacao_pct"], refs["elefante"]["livros_por_aluno"]) == (
        66.7, 1.67)
    assert refs["elefante"]["escolas_com_participacao"] == 5
    assert (refs["matific"]["participacao_pct"], refs["matific"]["atividades_por_aluno"]) == (
        66.7, 10.67)
    a = _escola(dados, m["escolas"]["a"])["plataformas"]["elefante"]
    b = _escola(dados, m["escolas"]["b"])["plataformas"]["elefante"]
    e = _escola(dados, m["escolas"]["e"])["plataformas"]
    assert (a["participacao_pct"], a["posicao_participacao"]) == (100.0, "acima")
    assert b["posicao_participacao"] == "abaixo"
    assert e["elefante"]["posicao_participacao"] == "na_media"
    # A intensidade (livros e atividades por aluno) das escolas com 2 e com 4 crianças somando
    # é protegida (G_GRUPO-4: "média × medidos" seria a soma delas) — e sobram 2 escolas com o
    # número, menos que as 3 que a comparação exige. (A régua da intensidade tem o teste de
    # fronteira abaixo.)
    for p in ("elefante", "matific"):
        assert refs[p]["escolas_com_intensidade"] == 2, p
    assert a["posicao_intensidade"] is None and "só 2 escola(s)" in a["motivo_sem_comparacao"]
    assert b["posicao_intensidade"] is None and b["motivo_sem_comparacao"] == (
        svc.TEXTO_METRICA_PROTEGIDA)
    assert "livros_por_aluno" in b["metricas_protegidas"]
    assert e["elefante"]["posicao_intensidade"] is None
    assert e["matific"]["diferenca_intensidade_pct"] is None
    assert "atividades_por_aluno" in e["matific"]["metricas_protegidas"]
    # Os números de cada escola são os da rota de plataformas (nada recalculado).
    plat = cliente_global.get(f"/api/v1/redes/{m['rede'].id}/analise/plataformas").json()
    por_id = {e["id"]: e for e in dados["escolas"]}
    for escola in plat["escolas"]:
        diag = por_id[escola["escola_id"]]
        for p, metricas in (("elefante", ("participacao_pct", "livros_por_aluno",
                                          "minutos_por_aluno", "taxa_acerto_pct")),
                            ("matific", ("participacao_pct", "atividades_por_aluno",
                                         "desempenho_medio"))):
            for chave in metricas:
                assert diag["plataformas"][p][chave] == escola[p][chave], (escola["nome"], chave)


def test_tolerancias_das_plataformas_na_fronteira():
    comparar = svc._comparar_plataforma
    # Participação: 5,0 p.p. já é acima; 4,9 é na média.
    assert comparar(65.0, 60.0, 3, None, intensidade=False)[:2] == ("acima", 5.0)
    assert comparar(64.9, 60.0, 3, None, intensidade=False)[0] == "na_media"
    assert comparar(55.0, 60.0, 3, None, intensidade=False)[0] == "abaixo"
    # Intensidade: 15% do valor da rede já é acima; 14% é na média.
    assert comparar(1.15, 1.0, 3, None, intensidade=True)[:2] == ("acima", 15.0)
    assert comparar(1.14, 1.0, 3, None, intensidade=True)[0] == "na_media"
    assert comparar(0.85, 1.0, 3, None, intensidade=True)[0] == "abaixo"
    # Menos de 3 escolas com a métrica: sem posição, com o motivo.
    pos, dif, motivo = comparar(80.0, 60.0, 2, None, intensidade=False)
    assert pos is None and dif is None and "pelo menos 3" in motivo
    assert svc.posicao(0.2, 0.2) == "acima" and svc.posicao(-0.19, 0.2) == "na_media"
    assert svc.posicao(-0.0, 0.0) == "na_media"


def test_poucas_escolas_com_plataforma_nao_tem_posicao(db, cliente_global):
    m = mundo_plataformas(db)
    alfa = _escola(_get(cliente_global, m["rede"]), m["escolas"]["alfa"])
    ele = alfa["plataformas"]["elefante"]
    assert ele["participacao_pct"] == 71.4 and ele["posicao_participacao"] is None
    assert "pelo menos 3" in ele["motivo_sem_comparacao"]
    assert not _codigos(alfa, eixo="plataforma")
    assert alfa["leituras"]["lp"]["plataforma"] == "sem_dado"


def test_comparabilidade_por_ano_e_quebra_do_2o_ano(db, cliente_global):
    m = mundo_diagnostico(db)
    dados = _get(cliente_global, m["rede"])
    a = _escola(dados, m["escolas"]["a"])["leituras"]["lp"]
    assert a["anos"] == {"avaliacao": 2025, "plataforma": 2026}
    assert a["comparabilidade"] == "exploratoria" and "outra edição" in a["texto_comparabilidade"]
    # SARESP 2026 (inventado) para a Acácia e a rede: avaliação e plataformas no mesmo ano.
    acacia = m["escolas"]["a"]
    imp = importacao(db, "iee", "seduc_iee", 2026, alvo=MUN_DIAG, nome="iee_diag_2026.csv")
    saresp_oficial(db, imp, acacia, 2026, lp5=207.0, mt5=221.0, lp2=150.0, iee=5.2, meta=5.0,
                   icm=1, codigo=MUN_DIAG)
    imp_mun = importacao(db, "saresp", "seduc_saresp_municipio", 2026, alvo=MUN_DIAG,
                         resumo={"territorios": {MUN_DIAG: "MUNICIPIO DIAG"}})
    ref(db, "saresp", imp_mun, edicao=2026, indicador="proficiencia", etapa="5_ano",
        componente="lp", valor=200.0, casas=1, codigo=MUN_DIAG, unidade="escala_saresp")
    db.commit()
    dados = _get(cliente_global, m["rede"])
    esc = _escola(dados, acacia)
    lp = esc["leituras"]["lp"]
    assert lp["anos"] == {"avaliacao": 2026, "plataforma": 2026}
    assert lp["comparabilidade"] == "mesmo_ano" and "nunca causa" in lp["texto_comparabilidade"]
    assert _escola(dados, m["escolas"]["b"])["leituras"]["lp"]["comparabilidade"] == "exploratoria"
    # MT da Acácia: só "estável" (220,0 → 221,0; a rede não tem MT em 2026) — nenhum sinal com
    # direção decide a leitura: o ano 2026 aparece, mas a leitura não é "mesmo ano".
    mt = esc["leituras"]["mt"]
    assert (mt["avaliacao"], mt["anos"]) == ("sem_dado", {"avaliacao": 2026, "plataforma": 2026})
    assert mt["comparabilidade"] is None
    assert "nenhuma edição decide" in mt["texto_comparabilidade"]
    # O período que sai do ano letivo (dez/2025–set/2026): exploratória, com o período.
    cruzado = _escola(_get(cliente_global, m["rede"], periodo="personalizado",
                           inicio="2025-12-01", fim="2026-09-30"), acacia)["leituras"]["lp"]
    assert cruzado["comparabilidade"] == "exploratoria"
    assert "01/12/2025–30/09/2026, que não cabe no ano de 2026" in cruzado[
        "texto_comparabilidade"]
    # 5º ano: 205,0 → 207,0 é estável. 2º ano: 2025 → 2026 atravessa a quebra de escala.
    assert _linha(esc, "SARESP · 5º ano · LP")["tendencia"] == "estavel"
    lp2 = _linha(esc, "SARESP · 2º ano · LP")
    assert lp2["edicao"] == 2026 and lp2["anterior"] is None and lp2["tendencia"] is None
    assert "2026" in lp2["motivo_sem_tendencia"]


def test_celula_protegida_por_k_fica_sem_dado(db, cliente_global):
    """Uma escola de 3 crianças é suprimida — e a Beta (8, a menor visível) junto, em
    complemento (a decisão da rota de plataformas). As duas ficam sem número de plataforma,
    sem posição e com o sinal de dados; o número da pequena não aparece."""
    m = mundo_plataformas(db)
    pequena = nova_escola(db, m["rede"], "EMEF Fictícia Pequena", "35990198")
    for a in turma_com_alunos(db, pequena, "4º Ano", 3):
        retrato_matific(db, pequena, a, datetime(2026, 9, 30, 3, 20), atividades=9373,
                        estrelas=9791)
    db.commit()
    r = cliente_global.get(URL.format(rede=m["rede"].id))
    dados = r.json()
    for escola in (pequena, m["escolas"]["beta"]):
        e = _escola(dados, escola)
        p = e["plataformas"]
        assert p["suprimido"] is True and p["cobertura"] is None
        for plataforma in ("elefante", "matific"):
            bloco = p[plataforma]
            assert bloco["suprimido"] is True and bloco["participacao_pct"] is None
            assert bloco["posicao_participacao"] is None and bloco["motivo_sem_comparacao"]
        assert set(_codigos(e, eixo="dados", componente="mt")) >= {"celula_protegida"}
        assert not _codigos(e, eixo="plataforma")
    assert "9373" not in r.text and "9791" not in r.text
    assert dados["k_minimo"] == 5


def test_media_protegida_em_complemento_diz_que_esta_protegida():
    """Escola visível, coleta em dia, mas a participação e os livros do Elefante escondidos
    em complemento (``metricas_protegidas`` do serviço): sem posição, com o motivo da
    PROTEÇÃO (não "a escola não tem este número") e o sinal de dados da célula protegida —
    e o que segue visível (o acerto) é o do serviço."""
    janela = {"inicio": "2026-01-01", "fim": "2026-12-31", "ano_letivo": 2026}
    elefante = {"participacao_pct": None, "livros_por_aluno": None, "minutos_por_aluno": None,
                "taxa_acerto_pct": 80.0, "coleta_parcial": False, "coberto_ate": None,
                "motivo_sem_dado": None, "texto_sem_dado": None,
                "metricas_protegidas": ["participacao_pct", "livros_por_aluno",
                                        "minutos_por_aluno"]}
    matific = {"participacao_pct": 70.0, "atividades_por_aluno": 9.0, "desempenho_medio": 2.0,
               "coleta_parcial": False, "coberto_ate": None, "motivo_sem_dado": None,
               "texto_sem_dado": None, "metricas_protegidas": []}
    e_plat = {"suprimido": False, "cobertura": {"elefante": "ok", "matific": "ok"},
              "ultima_coleta": {"elefante": None, "matific": None},
              "elefante": elefante, "matific": matific}
    plat = {"modulos": {"elefante": True, "matific": True}, "k_minimo": 5}
    refs = {"elefante": {"participacao_pct": 60.0, "livros_por_aluno": 1.0,
                         "escolas_com_participacao": 4, "escolas_com_intensidade": 4},
            "matific": {"participacao_pct": 60.0, "atividades_por_aluno": 9.0,
                        "escolas_com_participacao": 4, "escolas_com_intensidade": 4}}
    bloco, sinais, medida = svc._plataformas_da_escola(e_plat, plat, refs, janela)
    ele = bloco["elefante"]
    assert ele["posicao_participacao"] is None and ele["posicao_intensidade"] is None
    assert "proteger as crianças" in ele["motivo_sem_comparacao"]
    assert "não tem este número" not in ele["motivo_sem_comparacao"]
    assert ele["suprimido"] is True and ele["taxa_acerto_pct"] == 80.0
    codigos = {(s["codigo"], s["componente"]) for s in sinais}
    assert ("celula_protegida", "lp") in codigos
    assert not [s for s in sinais if s["eixo"] == "plataforma" and s["componente"] == "lp"]
    # O Matific segue comparável: +10 p.p. (acima) e a mesma intensidade (na média).
    mat = bloco["matific"]
    assert (mat["posicao_participacao"], mat["posicao_intensidade"]) == ("acima", "na_media")
    assert medida is True


def test_modulo_nao_contratado_vira_sinal_de_dados(db, cliente_global):
    from app.services import modulos
    m = mundo_diagnostico(db)
    modulos.definir(db, m["rede"].id, "matematica", False)
    db.commit()
    dados = _get(cliente_global, m["rede"])
    a = _escola(dados, m["escolas"]["a"])
    assert a["plataformas"]["matific"] is None
    assert dados["referencias_plataformas"]["matific"] is None
    assert "modulo_nao_contratado" in _codigos(a, eixo="dados", componente="mt")
    assert a["leituras"]["mt"]["categoria"] == "inconclusiva"
    assert "não contratou" in a["leituras"]["mt"]["motivo"]


def test_periodo_invalido(db, cliente_global):
    m = mundo_plataformas(db)
    url = URL.format(rede=m["rede"].id)
    assert cliente_global.get(url, params={"periodo": "nada"}).status_code == 400
    assert cliente_global.get(url, params={"periodo": "personalizado"}).status_code == 400
    r = cliente_global.get(url, params={"periodo": "personalizado", "inicio": "0001-01-01",
                                        "fim": "2026-10-05"})
    assert r.status_code == 422 and "fora da faixa" in r.json()["detail"]
    # Período personalizado válido: a janela pedida volta na resposta.
    dados = _get(cliente_global, m["rede"], periodo="personalizado", inicio="2026-03-01",
                 fim="2026-09-30")
    assert (dados["janela"]["inicio"], dados["janela"]["fim"]) == ("2026-03-01", "2026-09-30")


# --- Regras puras ---------------------------------------------------------------------------

def _s(eixo, componente, direcao, codigo="x", ano=2025):
    return svc._sinal(codigo, eixo, componente, "calculado", direcao, "t", f"ref {codigo}",
                      ano=ano)


# A janela da rota de plataformas: ano letivo 2026, todas as escolas nele.
JANELA_2026 = {"preset": "ano_letivo", "rotulo": "Ano letivo 2026", "inicio": "2026-01-01",
               "fim": "2026-12-31", "ano_letivo": 2026, "anos_letivos": [2026]}


def test_comparabilidade_so_pelos_sinais_com_direcao_e_um_ano_letivo():
    """Jan/2027, escolas ainda em 2026 e o SARESP 2026 importado: LP na média do SARESP 2026
    (informativo) e abaixo da rede no Saeb 2025 (atenção), com o Elefante abaixo. Quem decide
    a leitura é a atenção de 2025 (outra coorte): exploratória, nunca "mesmo ano"."""
    plat = _s("plataforma", "lp", "atencao", "participacao_abaixo_da_rede", ano=2026)
    saresp = _s("avaliacao", "lp", "informativo", "na_media_da_rede", ano=2026)
    saeb = _s("avaliacao", "lp", "atencao", "abaixo_da_rede", ano=2025)
    lt = svc.leitura("lp", [saresp, saeb, plat], {"elefante": {}}, JANELA_2026)
    assert lt["categoria"] == "convergente_atencao"
    assert lt["anos"] == {"avaliacao": 2025, "plataforma": 2026}
    assert lt["comparabilidade"] == "exploratoria"
    assert lt["texto_comparabilidade"].startswith("Avaliação de 2025; plataformas de 2026.")
    assert lt["referencias"] == ["ref abaixo_da_rede", "ref participacao_abaixo_da_rede"]
    # Sinais com direção de 2025 e de 2026: os dois anos citados — exploratória.
    acima = _s("avaliacao", "lp", "favoravel", "acima_da_rede", ano=2026)
    lt = svc.leitura("lp", [acima, saeb, plat], {"elefante": {}}, JANELA_2026)
    assert lt["comparabilidade"] == "exploratoria"
    assert "Avaliação de 2025 e 2026;" in lt["texto_comparabilidade"]
    # Todos de 2026, um ano letivo só e o período dentro dele: mesmo ano.
    so_2026 = [_s("avaliacao", "lp", "atencao", "abaixo_da_rede", ano=2026), saresp, plat]
    lt = svc.leitura("lp", so_2026, {"elefante": {}}, JANELA_2026)
    assert (lt["comparabilidade"], lt["texto_comparabilidade"]) == ("mesmo_ano",
                                                                    svc.TEXTO_MESMO_ANO)
    # Escolas em 2026 e 2027, ou o período saindo do ano: exploratória, dizendo por quê (a
    # relação recusaria o par por ``periodo_sem_sobreposicao``).
    lt = svc.leitura("lp", so_2026, {"elefante": {}},
                     {**JANELA_2026, "anos_letivos": [2026, 2027]})
    assert lt["comparabilidade"] == "exploratoria"
    assert "2026 e 2027 (escolas em anos letivos diferentes)" in lt["texto_comparabilidade"]
    lt = svc.leitura("lp", so_2026, {"elefante": {}},
                     {**JANELA_2026, "inicio": "2026-12-06", "fim": "2027-01-04"})
    assert lt["comparabilidade"] == "exploratoria"
    assert "06/12/2026–04/01/2027, que não cabe no ano de 2026" in lt["texto_comparabilidade"]
    # Sem sinal com direção: o ano aparece (só para exibir), mas nunca "mesmo ano"...
    lt = svc.leitura("lp", [saresp, plat], {"elefante": {}}, JANELA_2026)
    assert lt["anos"] == {"avaliacao": 2026, "plataforma": 2026}
    assert lt["comparabilidade"] is None
    assert "nenhuma edição decide" in lt["texto_comparabilidade"]
    # ... e, de outro ano, exploratória (anos diferentes, como no contrato).
    estavel = _s("avaliacao", "lp", "informativo", "estavel", ano=2025)
    lt = svc.leitura("lp", [estavel, plat], {"elefante": {}}, JANELA_2026)
    assert (lt["anos"]["avaliacao"], lt["comparabilidade"]) == (2025, "exploratoria")


def test_estado_categoria_e_nivel():
    assert svc.estado([]) == "sem_dado"
    assert svc.estado([_s("avaliacao", "lp", "informativo")]) == "sem_dado"
    assert svc.estado([_s("avaliacao", "lp", "favoravel")]) == "favoravel"
    assert svc.estado([_s("avaliacao", "lp", "favoravel"),
                       _s("avaliacao", "lp", "atencao")]) == "misto"
    assert svc.categoria("atencao", "favoravel") == "divergente_uso_alto"
    assert svc.categoria("favoravel", "atencao") == "divergente_uso_baixo"
    assert svc.categoria("misto", "atencao") == "inconclusiva"
    # Sem sinal do componente, a leitura usa os gerais (IEE/Ideb) e diz que usou.
    sinais = [_s("avaliacao", "geral", "atencao", "abaixo_da_rede"),
              _s("plataforma", "lp", "atencao", "participacao_abaixo_da_rede", ano=2026)]
    lt = svc.leitura("lp", sinais, {"elefante": {}}, JANELA_2026)
    assert (lt["base"], lt["avaliacao"], lt["categoria"]) == ("geral", "atencao",
                                                             "convergente_atencao")
    assert lt["comparabilidade"] == "exploratoria"
    vazio = svc.leitura("mt", sinais, {"matific": {}}, JANELA_2026)
    nivel = svc.acompanhamento({"lp": lt, "mt": vazio}, sinais, True, True)
    assert nivel["nivel"] == "prioritario" and "ref abaixo_da_rede" in nivel["motivos"][0]
    assert svc.acompanhamento({"lp": vazio, "mt": vazio}, [], False, False)[
        "nivel"] == "dados_insuficientes"
    assert svc.acompanhamento({"lp": vazio, "mt": vazio}, [], True, False)["nivel"] == "sem_sinal"
