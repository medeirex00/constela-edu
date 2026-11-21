"""Alcance REAL da Secretaria (conta com rede vinculada, não global) no servidor.

A Secretaria costuma ter cargo "coordenador" — e quando é PROMOVIDA a partir de uma
conta de escola guarda o ``escola_id`` e o cargo de origem (``secadm_x`` = admin da
escola X). Por isso toda regra que só olha o CARGO a trata como gestora da escola.
Estes testes fixam o que ela consegue de fato:

1. Avaliações externas (decisão D4 do dono, 17/10): SÓ o admin global analisa,
   importa, desfaz ou configura o robô coletor. Secretaria, coordenador e admin de
   escola recebem 403 e nada é gravado; a Secretaria continua LENDO os resultados
   da rede dela.
2. Telas de ESCOLA abertas pelo endereço (/alunos, /matific, /elefante, /relatorios,
   /usuarios, /premiacoes, /comparador...): os endpoints que elas consomem NUNCA
   devolvem nome de criança à Secretaria — voltam vazios (``turmas_permitidas`` =
   []), 404 (ficha/evolução por aluno) ou 403 (usuários, relatórios, comparador de
   aluno). A guarda de rota do front só tira a Secretaria dessas telas vazias.
3. Escrita em ESCOLA: ``PATCH /escolas/{id}`` não passava por ``escola_autorizada``;
   a Secretaria promovida de um admin alterava a escola de origem (até inativá-la).
"""
import pytest

from app.models import Escola, ResultadoAvaliacao
from tests._mundo_sintetico import A25, A26, B26, OUTRA, mundo  # noqa: F401  (fixture)

NOMES_DE_ALUNO = (A25, A26, B26, OUTRA)
SECRETARIAS = ("sec_r1", "secadm_x")


def _url(mundo, resto, escola="x"):
    return f"/api/v1/escolas/{mundo.ids[escola]}{resto}"


def _csv(linhas):
    return "\n".join(";".join(c for c in ln) for ln in linhas).encode("utf-8")


_PLANILHA = _csv([["CO_ESCOLA", "NO_ESCOLA", "IDEB_2023"], ["35012345", "ESCOLA X", "6,1"]])
_DADOS_IMPORT = {"avaliacao": "ideb", "edicao": 2023, "indicador": "ideb", "unidade": "indice",
                 "linha_dados": 1, "col_inep": 0, "col_valor": 2, "etapa_fixa": "anos_iniciais"}


def _arquivo():
    return {"arquivo": ("ideb.csv", _PLANILHA, "text/csv")}


# --- 1) D4: avaliações externas só pelo admin global ---------------------------

@pytest.mark.parametrize("ator", ["sec_r1", "secadm_x", "coord_x", "admin_x"])
def test_d4_so_o_admin_global_importa_desfaz_e_configura_o_robo(mundo, ator):
    escola = mundo.db.get(Escola, mundo.ids["x"])
    escola.codigo_inep = "35012345"
    mundo.db.commit()
    cli = mundo.cli(ator)

    assert cli.post("/api/v1/avaliacoes/analisar", files=_arquivo()).status_code == 403
    assert cli.post("/api/v1/avaliacoes/importar", data=_DADOS_IMPORT,
                    files=_arquivo()).status_code == 403
    assert cli.post("/api/v1/avaliacoes/importar-preset",
                    data={"preset": "crianca_alfab", "edicao": 2025},
                    files=_arquivo()).status_code == 403
    assert cli.delete("/api/v1/avaliacoes/resultados",
                      params={"avaliacao": "ideb", "edicao": 2023,
                              "indicador": "ideb"}).status_code == 403
    # Robô coletor (fontes): já era só do global — continua.
    assert cli.get("/api/v1/avaliacoes/fontes").status_code == 403
    assert cli.post("/api/v1/avaliacoes/fontes", json={
        "avaliacao": "ideb", "nome": "x", "url": "https://exemplo.gov.br/a.csv",
        "edicao": 2023, "indicador": "ideb", "unidade": "indice",
        "mapeamento": {}}).status_code == 403
    mundo.db.expire_all()
    assert mundo.db.query(ResultadoAvaliacao).count() == 0     # nada foi gravado


def test_d4_admin_global_importa_e_desfaz_e_a_secretaria_le(mundo):
    escola = mundo.db.get(Escola, mundo.ids["x"])
    escola.codigo_inep = "35012345"
    mundo.db.commit()
    glob = mundo.cli("global")

    assert glob.post("/api/v1/avaliacoes/analisar", files=_arquivo()).status_code == 200
    r = glob.post("/api/v1/avaliacoes/importar", data=_DADOS_IMPORT, files=_arquivo())
    assert r.status_code == 200, r.text
    assert r.json()["casados"] == 1

    # A Secretaria da rede da escola LÊ a série importada (a tela de avaliações).
    for ator in SECRETARIAS:
        opcoes = mundo.cli(ator).get(f"/api/v1/redes/{mundo.ids['r1']}/avaliacoes/opcoes")
        assert opcoes.status_code == 200, (ator, opcoes.text)
        assert any(o["avaliacao"] == "ideb" for o in opcoes.json()), (ator, opcoes.json())

    r = glob.delete("/api/v1/avaliacoes/resultados",
                    params={"avaliacao": "ideb", "edicao": 2023, "indicador": "ideb",
                            "etapa": "anos_iniciais"})
    assert r.status_code == 200 and r.json()["removidos"] == 1


# --- 2) Telas de escola pelo endereço: nenhum nome de criança -------------------

# Endpoint consumido por cada tela (front) → status que a Secretaria recebe.
# 200 = volta VAZIO (turmas_permitidas = []); 404 = ficha/evolução por aluno (não
# revela a existência); 403 = área operacional/PII barrada de propósito.
_TELAS = [
    ("/alunos", "/alunos", 200),
    ("/alunos", "/turmas", 200),
    ("/alunos/:id", "/alunos/{aluno}/perfil", 404),
    ("/alunos/:id/evolucao", "/alunos/{aluno}/evolucao", 404),
    ("/alunos/:id/evolucao", "/alunos/{aluno}/evolucao-leitura", 404),
    ("/matific", "/matific", 200),
    ("/elefante", "/elefante", 200),
    ("/premiacoes", "/premiacoes", 200),
    ("/premiacoes", "/ranking-evolucao", 200),
    ("/insights", "/insights", 200),
    ("/ranking", "/ranking", 200),
    ("/ranking", "/ranking/leitura", 200),
    ("/ranking", "/ranking/matematica", 200),
    ("/conquistas", "/gamificacao/ranking-xp", 200),
    ("/conquistas", "/gamificacao/mural", 403),
    ("busca global", "/pesquisa?q=ALUNO", 200),
    ("/comparador", "/alunos?por_pagina=100", 200),
    ("/comparador", "/comparar?tipo_a=aluno&id_a={aluno}&tipo_b=aluno&id_b={aluno}", 403),
    ("/relatorios", "/relatorios/ranking?formato=csv", 403),
    ("/relatorios", "/relatorios/alunos?formato=csv", 403),
    ("/relatorios", "/ranking/cartaz", 403),
    ("/relatorios/periodo", "/relatorios/periodo", 403),
    ("/usuarios", "/usuarios", 403),
    # O painel da escola saía 200 com tudo zerado (recortado pelas turmas que ela
    # não tem): 403 explicado, como no pacote do app (PEND-31).
    ("Dashboard da escola", "/dashboard", 403),
]


@pytest.mark.parametrize("ator", SECRETARIAS)
def test_secretaria_nao_recebe_nome_de_crianca_nas_telas_de_escola(mundo, ator):
    cli = mundo.cli(ator)
    aluno = mundo.ids[A26]
    for tela, rota, esperado in _TELAS:
        r = cli.get(_url(mundo, rota.format(aluno=aluno)))
        assert r.status_code == esperado, (ator, tela, rota, r.status_code, r.text[:200])
        for nome in NOMES_DE_ALUNO:
            assert nome not in r.text, (ator, tela, rota, nome)


def test_o_coordenador_da_escola_ve_os_nomes_nas_mesmas_rotas(mundo):
    """Controle: o cenário TEM dado nominal — o vazio da Secretaria é o filtro dela,
    não falta de dado. O coordenador da escola X (sem rede) vê os alunos."""
    coord = mundo.cli("coord_x")
    alunos = coord.get(_url(mundo, "/alunos")).json()
    assert {a["nome"] for a in alunos["itens"]} >= {A26, B26}
    ranking = coord.get(_url(mundo, "/ranking")).text
    assert A26 in ranking and B26 in ranking


def test_secretaria_nao_le_escola_de_outra_rede(mundo):
    # A escola Y fica fora da rede R1: nem a leitura vazia passa.
    for ator in SECRETARIAS:
        assert mundo.cli(ator).get(_url(mundo, "/alunos", escola="y")).status_code == 403


# --- 3) PATCH /escolas/{id}: a Secretaria não altera a escola ------------------

@pytest.mark.parametrize("ator", SECRETARIAS)
def test_secretaria_nao_altera_a_escola_nem_a_de_origem(mundo, ator):
    # `secadm_x` é admin de origem DA escola X: o PATCH só olhava cargo + escola_id
    # e deixava ela renomear ou INATIVAR a escola (que some de todas as listas).
    r = mundo.cli(ator).patch(_url(mundo, ""), json={"nome": "RENOMEADA", "status": "inativa"})
    assert r.status_code == 403, r.text
    mundo.db.expire_all()
    escola = mundo.db.get(Escola, mundo.ids["x"])
    assert escola.nome == "ESCOLA_X_SINTETICA" and escola.status == "ativa"


def test_admin_da_escola_e_global_seguem_alterando_a_escola(mundo):
    assert mundo.cli("admin_x").patch(_url(mundo, ""), json={"cidade": "Cidade A"}).status_code == 200
    assert mundo.cli("global").patch(_url(mundo, ""), json={"cidade": "Cidade B"}).status_code == 200
    mundo.db.expire_all()
    assert mundo.db.get(Escola, mundo.ids["x"]).cidade == "Cidade B"
