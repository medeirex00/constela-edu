"""G_GRUPO-2 (auditoria, fase C): a DIFERENÇA ENTRE DOIS PERÍODOS da análise educacional
não refaz o número de UMA criança que um dos períodos esconde.

A proteção por métrica (estrelas por aluno e desempenho do Matific só com ``k`` crianças com
atividade; nível médio do Elefante só com ``k`` crianças com livro de nível) era decidida
período a período, e o período personalizado era livre: duas janelas com o mesmo início
mostravam a métrica e a diferença entre elas era o que UMA criança fez no trecho final — o
número que a janela curta escondia de propósito.

O que estes testes sustentam:

* a SECRETARIA só pede períodos que são blocos inteiros do calendário (o ano letivo ou um
  bimestre): o personalizado, o dia, a semana, o mês e o semestre voltam 422 nas rotas da
  rede e na da escola (o Admin Global e a coordenação da escola, que já veem cada criança,
  continuam com todos os períodos);
* a métrica de um período que junta vários blocos (o ano letivo) só aparece se nenhum
  bloco dele (os bimestres e a folga antes do 1º) a esconde com crianças dentro, nem o
  resto da conta do ano que nenhum bimestre mede (o acumulado da primeira coleta do
  Matific): "ano letivo − bimestres" não isola mais nenhuma criança.

Dados INVENTADOS. Nenhuma rede externa.
"""
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import Usuario
from tests.test_analise_base import (ler, livros, nova_escola, nova_rede, retrato_elefante,
                                     retrato_matific, turma_com_alunos)

HOJE = date(2026, 10, 5)
API = "/api/v1"
PRESETS_DE_BLOCO = ("ano_letivo", "bimestre", "bimestre_anterior", "bimestre_1", "bimestre_2",
                    "bimestre_3", "bimestre_4")
RECUSADOS = ({"periodo": "personalizado", "inicio": "2026-03-01", "fim": "2026-08-15"},
             {"periodo": "mes"}, {"periodo": "mes_anterior"}, {"periodo": "semana"},
             {"periodo": "semana_anterior"}, {"periodo": "hoje"}, {"periodo": "ontem"},
             {"periodo": "7dias"}, {"periodo": "30dias"}, {"periodo": "semestre"},
             {"periodo": "tudo"})


@pytest.fixture(autouse=True)
def _hoje(monkeypatch):
    monkeypatch.setattr("app.routers.analise.hoje_br", lambda: HOJE)


def _login(db, email, **campos) -> TestClient:
    db.add(Usuario(nome="Conta Fictícia", email=email, senha_hash=hash_senha("s3nh4"), **campos))
    db.commit()
    c = TestClient(app)
    r = c.post(f"{API}/auth/login", data={"username": email, "password": "s3nh4"})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _mundo_terceiro_bimestre(db):
    """6 crianças numa turma: as 5 "outras" usam as plataformas no 1º semestre; a ALVO só
    aparece no 3º bimestre (24/07–04/10): 7 atividades e 19 estrelas no Matific (desempenho
    2,71) e 3 livros de nível Z no Elefante."""
    rede = nova_rede(db, nome="Rede Fictícia das Janelas", codigo="3599977", codmun="9977")
    escola = nova_escola(db, rede, "EMEF Fictícia das Janelas", "35997701")
    alunos = turma_com_alunos(db, escola, "3º Ano", 6)
    alvo, outros = alunos[5], alunos[:5]
    for a in outros:
        retrato_matific(db, escola, a, datetime(2026, 3, 2, 3, 20), atividades=10, estrelas=30)
        retrato_matific(db, escola, a, datetime(2026, 6, 1, 3, 20), atividades=20, estrelas=60)
        retrato_matific(db, escola, a, datetime(2026, 9, 1, 3, 20), atividades=20, estrelas=60)
        retrato_matific(db, escola, a, datetime(2026, 10, 1, 3, 20), atividades=20, estrelas=60)
    retrato_matific(db, escola, alvo, datetime(2026, 3, 2, 3, 20), atividades=0, estrelas=0)
    retrato_matific(db, escola, alvo, datetime(2026, 6, 1, 3, 20), atividades=0, estrelas=0)
    retrato_matific(db, escola, alvo, datetime(2026, 9, 1, 3, 20), atividades=7, estrelas=19)
    retrato_matific(db, escola, alvo, datetime(2026, 10, 1, 3, 20), atividades=7, estrelas=19)
    for a in alunos:
        retrato_elefante(db, escola, a, datetime(2026, 3, 2, 3, 10))
        retrato_elefante(db, escola, a, datetime(2026, 10, 1, 3, 10))
    k_livros = livros(db, escola, 2, "K")
    for a in outros:
        ler(db, escola, a, k_livros, datetime(2026, 5, 10, 14, 0))
    ler(db, escola, alvo, livros(db, escola, 3, "Z"), datetime(2026, 9, 10, 14, 0))
    db.commit()
    return rede, escola


def _blocos_da_rede(c, rede_id, **params):
    r = c.get(f"{API}/redes/{rede_id}/analise/plataformas", params=params)
    assert r.status_code == 200, r.text
    corpo = r.json()
    (escola,) = corpo["escolas"]
    assert not escola["suprimido"]
    (celula,) = escola["series"]
    return {"celula": celula, "escola": escola, "rede": corpo["rede"]}


def test_secretaria_so_pede_ano_letivo_ou_bimestre_inteiro(db, escola_completa):
    rede, escola = _mundo_terceiro_bimestre(db)
    sec = _login(db, "sec.janelas@ficticio.local", cargo="coordenador", rede_id=rede.id)
    urls = (f"{API}/redes/{rede.id}/analise/plataformas",
            f"{API}/redes/{rede.id}/analise/diagnostico",
            f"{API}/escolas/{escola.id}/analise")
    for url in urls:
        for params in RECUSADOS:
            r = sec.get(url, params=params)
            assert r.status_code == 422, (url, params, r.status_code, r.text[:200])
            assert "bimestre" in r.json()["detail"], r.text
        for preset in PRESETS_DE_BLOCO:
            r = sec.get(url, params={"periodo": preset})
            assert r.status_code == 200, (url, preset, r.status_code, r.text[:200])
    r = sec.get(f"{API}/redes/{rede.id}/analise/relacao",
                params={"indicador": "saresp", "periodo": "personalizado",
                        "inicio": "2026-03-01", "fim": "2026-08-15"})
    assert r.status_code == 422, r.text
    # A ficha da Secretaria (só as avaliações) continua no ano letivo.
    r = sec.get(f"{API}/escolas/{escola.id}/analise",
                params={"periodo": "ano_letivo", "so_avaliacoes": "true"})
    assert r.status_code == 200, r.text


def test_a_diferenca_das_janelas_sobrepostas_nao_e_mais_pedida_pela_secretaria(
        db, escola_completa):
    """A sonda da auditoria (W1 = [01/03, 15/08] e W2 = [01/03, 04/10]) não roda mais."""
    rede, _ = _mundo_terceiro_bimestre(db)
    sec = _login(db, "sec.sonda@ficticio.local", cargo="coordenador", rede_id=rede.id)
    for inicio, fim in (("2026-03-01", "2026-08-15"), ("2026-03-01", "2026-10-04"),
                        ("2026-08-16", "2026-10-04")):
        r = sec.get(f"{API}/redes/{rede.id}/analise/plataformas",
                    params={"periodo": "personalizado", "inicio": inicio, "fim": fim})
        assert r.status_code == 422, r.text


def test_ano_letivo_menos_bimestres_nao_refaz_a_crianca_do_terceiro_bimestre(
        db, escola_completa):
    rede, escola = _mundo_terceiro_bimestre(db)
    sec = _login(db, "sec.ano@ficticio.local", cargo="coordenador", rede_id=rede.id)
    ano = _blocos_da_rede(sec, rede.id, periodo="ano_letivo")
    bim = {n: _blocos_da_rede(sec, rede.id, periodo=f"bimestre_{n}") for n in (1, 2, 3, 4)}
    # O 3º bimestre esconde a criança (1 de 6 com atividade, 1 com livro de nível).
    m3, e3 = bim[3]["celula"]["matific"], bim[3]["celula"]["elefante"]
    assert m3["estrelas_por_aluno"] is None and m3["desempenho_medio"] is None
    assert e3["nivel_medio_posicao"] is None
    for nivel in ("celula", "escola", "rede"):
        m, e = ano[nivel]["matific"], ano[nivel]["elefante"]
        # O ano letivo também esconde, e diz que é proteção (não falta de dado).
        assert m["estrelas_por_aluno"] is None and m["desempenho_medio"] is None, (nivel, m)
        assert {"estrelas_por_aluno", "desempenho_medio"} <= set(m["metricas_protegidas"]), m
        assert e["nivel_medio"] is None and e["nivel_medio_posicao"] is None, (nivel, e)
        assert {"nivel_medio", "nivel_medio_posicao"} <= set(e["metricas_protegidas"]), e
        assert m["texto_metricas_protegidas"] and "bimestre" in m["texto_metricas_protegidas"]
        # A participação (contagem, não número de criança) continua.
        assert m["participacao_pct"] == 100.0 and e["participacao_pct"] is not None
    # A mesma escola pela rota da escola (a Secretaria lê com a proteção da rede).
    r = sec.get(f"{API}/escolas/{escola.id}/analise", params={"periodo": "ano_letivo"})
    assert r.status_code == 200, r.text
    plat = r.json()["plataformas"]
    assert plat["matific"]["estrelas_por_aluno"] is None
    assert plat["series"][0]["matific"]["estrelas_por_aluno"] is None
    assert plat["elefante"]["nivel_medio_posicao"] is None
    assert plat["matific"] == ano["escola"]["matific"]
    assert plat["series"] == ano["escola"]["series"]


def test_folga_antes_do_primeiro_bimestre_e_um_bloco(db, escola_completa):
    """A ALVO só usa o Matific em janeiro (antes do 1º bimestre, que começa em 02/02): o ano
    letivo menos os quatro bimestres seria ela sozinha."""
    rede = nova_rede(db, nome="Rede Fictícia da Folga", codigo="3599978", codmun="9978")
    escola = nova_escola(db, rede, "EMEF Fictícia da Folga", "35997801")
    alunos = turma_com_alunos(db, escola, "4º Ano", 6)
    alvo, outros = alunos[5], alunos[:5]
    for a in outros:
        retrato_matific(db, escola, a, datetime(2026, 1, 20, 3, 20), atividades=0, estrelas=0)
        retrato_matific(db, escola, a, datetime(2026, 3, 2, 3, 20), atividades=10, estrelas=30)
        retrato_matific(db, escola, a, datetime(2026, 6, 1, 3, 20), atividades=20, estrelas=60)
        retrato_matific(db, escola, a, datetime(2026, 10, 1, 3, 20), atividades=20, estrelas=60)
    for quando in (datetime(2026, 1, 20, 3, 20), datetime(2026, 3, 2, 3, 20),
                   datetime(2026, 6, 1, 3, 20), datetime(2026, 10, 1, 3, 20)):
        retrato_matific(db, escola, alvo, quando, atividades=5, estrelas=12)
    db.commit()
    sec = _login(db, "sec.folga@ficticio.local", cargo="coordenador", rede_id=rede.id)
    bim = {n: _blocos_da_rede(sec, rede.id, periodo=f"bimestre_{n}")["celula"]["matific"]
           for n in (1, 2)}
    assert bim[1]["estrelas_por_aluno"] == 25.0 and bim[2]["estrelas_por_aluno"] == 25.0
    ano = _blocos_da_rede(sec, rede.id, periodo="ano_letivo")
    for nivel in ("celula", "escola", "rede"):
        m = ano[nivel]["matific"]
        assert m["estrelas_por_aluno"] is None and m["desempenho_medio"] is None, (nivel, m)


def test_primeira_coleta_no_meio_do_ano_nao_escapa_pela_diferenca(db, escola_completa):
    """A ALVO entra no Matific em setembro com o contador do ano já em 7 atividades e 19
    estrelas, e não faz mais nada: o 3º bimestre parte da primeira coleta dela (ganho 0) e o
    ano letivo parte do zero. Com outras 5 crianças ativas no 3º bimestre, o bimestre mostra
    as estrelas; sem a proteção, "ano letivo − bimestres" seria a primeira coleta dela."""
    rede = nova_rede(db, nome="Rede Fictícia da Chegada", codigo="3599979", codmun="9979")
    escola = nova_escola(db, rede, "EMEF Fictícia da Chegada", "35997901")
    alunos = turma_com_alunos(db, escola, "5º Ano", 6)
    alvo, outros = alunos[5], alunos[:5]
    for a in outros:
        retrato_matific(db, escola, a, datetime(2026, 3, 2, 3, 20), atividades=0, estrelas=0)
        retrato_matific(db, escola, a, datetime(2026, 6, 1, 3, 20), atividades=10, estrelas=30)
        retrato_matific(db, escola, a, datetime(2026, 9, 1, 3, 20), atividades=20, estrelas=60)
        retrato_matific(db, escola, a, datetime(2026, 10, 1, 3, 20), atividades=30, estrelas=90)
    retrato_matific(db, escola, alvo, datetime(2026, 9, 1, 3, 20), atividades=7, estrelas=19)
    retrato_matific(db, escola, alvo, datetime(2026, 10, 1, 3, 20), atividades=7, estrelas=19)
    db.commit()
    sec = _login(db, "sec.chegada@ficticio.local", cargo="coordenador", rede_id=rede.id)
    b3 = _blocos_da_rede(sec, rede.id, periodo="bimestre_3")["celula"]["matific"]
    assert b3["estrelas_por_aluno"] is not None             # 5 ativas no bimestre
    ano = _blocos_da_rede(sec, rede.id, periodo="ano_letivo")
    for nivel in ("celula", "escola", "rede"):
        m = ano[nivel]["matific"]
        assert m["estrelas_por_aluno"] is None and m["desempenho_medio"] is None, (nivel, m)


def test_admin_global_e_coordenacao_continuam_com_todos_os_periodos(db, escola_completa):
    rede, escola = _mundo_terceiro_bimestre(db)
    glob = _login(db, "global.janelas@ficticio.local", cargo="admin", is_global=True)
    coord = _login(db, "coord.janelas@ficticio.local", cargo="coordenador", escola_id=escola.id)
    personalizado = {"periodo": "personalizado", "inicio": "2026-03-01", "fim": "2026-08-15"}
    for url in (f"{API}/redes/{rede.id}/analise/plataformas",
                f"{API}/escolas/{escola.id}/analise"):
        assert glob.get(url, params=personalizado).status_code == 200, url
        assert glob.get(url, params={"periodo": "mes"}).status_code == 200, url
    r = coord.get(f"{API}/escolas/{escola.id}/analise", params=personalizado)
    assert r.status_code == 200, r.text
    # A coordenação (que vê cada criança da própria escola) não recebe a proteção da rede.
    r = coord.get(f"{API}/escolas/{escola.id}/analise", params={"periodo": "ano_letivo"})
    assert r.json()["plataformas"]["matific"]["estrelas_por_aluno"] is not None
