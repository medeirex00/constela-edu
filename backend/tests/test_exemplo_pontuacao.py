"""'Quer ver um exemplo?' da tela de Pontuação — o exemplo É a conta real.

Trava, contra a fórmula que pontua de verdade:
  * Elefante: para os 752 livros do catálogo oficial × 1º–5º ano, o valor do
    exemplo é o de ``RegraGlobal().valor_livro`` (a chamada das premiações e
    dos rankings) e os fatores exibidos fecham a conta; com uma leitura no
    período, o exemplo arredondado é o valor do pódio "Melhor Leitor";
  * Matific: o ``k`` do exemplo é o ``regua_matematica`` das premiações e, com
    as atividades/estrelas de um aluno, o índice é o valor dele no pódio
    "Melhor Matemática" — inclusive com estrelas acima de 5 por atividade;
  * as funções extraídas (``premiacoes.regua_matematica``,
    ``matific_destaque.limitar_estrelas``) não mudam nenhum resultado;
  * autorização, 422 de nível/série/atividades, 404 de livro de outra escola e
    a decisão de privacidade (poucos alunos → sem ``k``).

Nomes de alunos fictícios; nenhum dado real.
"""
import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from sqlalchemy import select

from app.models import (Aluno, Configuracao, DificuldadeTurma, Escola, Importacao, Leitura,
                        Livro, Matricula, ModuloRede, NivelDificuldade, PontuacaoNivelTurma,
                        Rede, SnapshotMatific, Turma, Usuario)
from app.routers import configuracoes as rota_config
from app.routers.plataformas import NIVEIS_OFICIAIS
from app.services import dificuldade_livro as dl
from app.services import matific_destaque as md
from app.services import premiacoes, scoring

API = "/api/v1"
AGO_INI, AGO_FIM = datetime(2026, 8, 1), datetime(2026, 8, 31, 23, 59, 59, 999999)
BASE = datetime(2026, 7, 20)      # antes da janela: ponto de partida do ganho
DENTRO = datetime(2026, 8, 10)    # dentro da janela
Q_AGOSTO = "periodo=personalizado&inicio=2026-08-01&fim=2026-08-31"


def _url(escola_id: int, plataforma: str, query: str = "") -> str:
    base = f"{API}/escolas/{escola_id}/configuracoes/pontuacao/exemplo/{plataforma}"
    return f"{base}?{query}" if query else base


def _login(email: str, senha: str = "s3nh4") -> TestClient:
    c = TestClient(app)
    r = c.post(f"{API}/auth/login", data={"username": email, "password": senha})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _aluno(db, escola, turma, nome):
    a = Aluno(escola_id=escola.id, nome=nome, status="ativo")
    db.add(a)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=turma.id, ano_letivo=2026))
    return a


def _entrada(meta, serie):
    return {"origem": "catalogo", "livro_id": None, "elefante_id": meta.id,
            "titulo": meta.titulo, "nivel": meta.nivel, "serie": serie}


# ---------------------------------------------------------------------------
# 1) Elefante: o exemplo é a regra, livro a livro, para o catálogo inteiro
# ---------------------------------------------------------------------------

def test_catalogo_inteiro_x_series_exemplo_igual_a_valor_livro():
    """752 livros × 5 séries = 3.760 casos: o valor do exemplo é EXATAMENTE o de
    ``valor_livro`` (por id oficial e por título+nível), e base × tamanho × série
    com os fatores devolvidos fecha no valor (4 casas)."""
    regra = dl.RegraGlobal()
    livros = list(dl.catalogo().por_id.values())
    assert len(livros) == 752
    casos = 0
    for meta in livros:
        for serie in range(1, 6):
            ano = f"{serie}º Ano"
            ex = rota_config.montar_exemplo_elefante(
                regra, nivel=meta.nivel, titulo=meta.titulo, elefante_id=meta.id,
                serie=serie, entrada=_entrada(meta, serie))
            esperado = regra.valor_livro(meta.nivel, meta.titulo, ano, elefante_id=meta.id)
            assert ex["valor"] == esperado, (meta.id, serie)
            # Sem id (linha legada do acervo): título + nível chega ao mesmo valor
            # quando o par existe no catálogo.
            sem_id = rota_config.montar_exemplo_elefante(
                regra, nivel=meta.nivel, titulo=meta.titulo, elefante_id=None,
                serie=serie, entrada=_entrada(meta, serie))
            assert sem_id["valor"] == regra.valor_livro(meta.nivel, meta.titulo, ano)
            calc = ex["calculo"]
            assert round(calc["base_nivel"] * calc["fator_tamanho"] * calc["fator_serie"],
                         4) == ex["valor"]
            assert calc["fator_serie"] == dl.PARAMS_VIGENTES["fator_serie"][serie]
            assert ex["livro"]["palavras"] == meta.word_count
            assert ex["livro"]["palavras_status"] == dl.WC_CATALOGO
            assert ex["livro"]["resolvido_por"] == dl.RESOLVIDO_POR_ID
            assert ex["valor_exibido"] == round(esperado, 2)
            casos += 1
    assert casos == 3760


def test_amostra_do_catalogo_pela_api_igual_a_valor_livro(cliente, escola_completa):
    """A rota HTTP devolve o mesmo que a regra (amostra de 1 a cada 25 livros
    nas 5 séries, por ``elefante_id``)."""
    eid = escola_completa["escola"].id
    regra = dl.RegraGlobal()
    livros = sorted(dl.catalogo().por_id.values(), key=lambda b: b.id)[::25]
    for meta in livros:
        for serie in range(1, 6):
            r = cliente.get(_url(eid, "elefante", f"elefante_id={meta.id}&serie={serie}"))
            assert r.status_code == 200, r.text
            assert r.json()["valor"] == regra.valor_livro(
                meta.nivel, meta.titulo, f"{serie}º Ano", elefante_id=meta.id)


def test_decomposicao_de_um_livro_conhecido(cliente, escola_completa):
    """'O que é o que é?' (id 9, nível B, 70 palavras; mediana do B = 74) para o
    3º ano: 1,673639 × 0,982296 × 1,20 = 1,9728 — os números da sonda."""
    eid = escola_completa["escola"].id
    r = cliente.get(_url(eid, "elefante", "elefante_id=9&serie=3"))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["regra"] == dl.VERSAO_VIGENTE and d["personalizada"] is False
    assert d["catalogo"] == dl.versao_catalogo()
    assert d["livro"]["nivel"] == "B" and d["livro"]["palavras"] == 70
    assert d["livro"]["resolvido_por"] == "elefante_id"
    c = d["calculo"]
    assert c["mediana_palavras_nivel"] == 74.0 and c["posicao_nivel"] == 5.0
    # A posição interna começa em zero (AA = 0): para quem lê, B é o 6º nível.
    assert c["posicao_descricao"] == "6º nível da escada, que começa no AA"
    assert c["base_nivel"] == 1.673639 and c["fator_tamanho"] == 0.982296
    assert c["fator_serie"] == 1.2 and c["limite_tamanho"] is None
    assert d["valor"] == 1.9728 and d["valor_exibido"] == 1.97


def test_livro_no_teto_e_titulo_unico_em_outro_nivel(cliente, escola_completa):
    eid = escola_completa["escola"].id
    # 'O Castelo Encantado' (Z, 68.915 palavras): o fator para no teto 1,35.
    d = cliente.get(_url(eid, "elefante", "nivel=Z&titulo=O Castelo Encantado&serie=5")).json()
    assert d["calculo"]["limite_tamanho"] == "teto" and d["calculo"]["fator_tamanho"] == 1.35
    assert d["livro"]["resolvido_por"] == "titulo_nivel"
    assert any("máximo" in a for a in d["avisos"])
    # O título só existe no B, mas foi digitado como Z: a regra aceita o título
    # único e mistura as palavras dele com a mediana do Z — o exemplo DIZ isso.
    d = cliente.get(_url(eid, "elefante", "nivel=Z&titulo=O que é o que é?&serie=3")).json()
    assert d["livro"]["resolvido_por"] == "titulo_unico"
    assert d["livro"]["nivel_no_catalogo"] == "B" and d["livro"]["nivel"] == "Z"
    assert d["valor"] == dl.RegraGlobal().valor_livro("Z", "O que é o que é?", "3º Ano")
    assert d["calculo"]["limite_tamanho"] == "piso"
    assert any("nível B" in a for a in d["avisos"])


def test_so_o_nivel_vale_o_livro_tipico(cliente, escola_completa):
    eid = escola_completa["escola"].id
    d = cliente.get(_url(eid, "elefante", "nivel=d&serie=2")).json()
    assert d["livro"]["nivel"] == "D" and d["livro"]["palavras"] is None
    assert d["calculo"]["fator_tamanho"] == 1.0
    assert d["valor"] == dl.RegraGlobal().valor_tipico("D", "2º Ano")
    assert any("típico do nível" in a for a in d["avisos"])


def test_livro_do_acervo_sem_palavras_vale_o_tipico(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    livro = Livro(escola_id=escola.id, titulo="Livro Fora do Catálogo Exemplo",
                  nivel_codigo="D")
    db.add(livro)
    db.commit()
    r = cliente.get(_url(escola.id, "elefante", f"livro_id={livro.id}&serie=4"))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["entrada"]["origem"] == "acervo" and d["entrada"]["livro_id"] == livro.id
    assert d["livro"]["palavras"] is None
    assert d["livro"]["palavras_status"] == dl.WC_AUSENTE
    assert d["livro"]["resolvido_por"] is None
    assert d["calculo"]["fator_tamanho"] == 1.0
    assert d["valor"] == dl.RegraGlobal().valor_livro(
        "D", "Livro Fora do Catálogo Exemplo", "4º Ano")
    assert any("contagem de palavras" in a for a in d["avisos"])


def _personalizar(db, escola):
    db.add(Configuracao(escola_id=escola.id, namespace=scoring.PERFIL_SCORING_NS,
                        chave="modo", valor="personalizado"))
    db.commit()


def test_escola_personalizada_so_mostra_o_que_a_regra_legada_expoe(cliente, db,
                                                                  escola_completa):
    """Régua legada sem ajuste: o valor do 3º ano é o padrão da faixa (o fixture
    tem uma turma de 3º ano), sem divisão em fatores."""
    escola = escola_completa["escola"]
    _personalizar(db, escola)
    d = cliente.get(_url(escola.id, "elefante", "nivel=D&serie=3")).json()
    assert d["personalizada"] is True and d["regra"] == dl.VERSAO_LEGADA
    assert d["calculo"] is None
    turma = escola_completa["turma"]
    assert d["valor"] == dl.RegraEscolaLegada(db, escola.id).valor_livro(
        "D", None, turma.ano_escolar, turma.id)
    assert d["valor"] == 4.0 and d["valor_exibido"] == 4.0   # "Nível 2" (D, E) do fixture
    assert d["base_do_valor"] == "serie" and d["valor_padrao_escola"] == 4.0
    assert d["por_turma"] == [{"turma_id": turma.id, "turma": "3º Ano A", "valor": 4.0,
                               "valor_exibido": 4.0}]
    assert any("régua própria" in a for a in d["avisos"])
    assert not any("ajustou" in a for a in d["avisos"])


def _leitor(db, escola, turma, nome, livro):
    aluno = _aluno(db, escola, turma, nome)
    db.add(Leitura(escola_id=escola.id, aluno_id=aluno.id, livro_id=livro.id,
                   data=DENTRO, tempo_leitura_min=10))
    return aluno


def _podio_leitor(db, escola) -> dict:
    dados = premiacoes.premiacoes(db, escola.id, AGO_INI, AGO_FIM, limite=50)
    return {p["aluno_id"]: p["valor"] for p in next(
        c for c in dados["categorias"] if c["chave"] == "melhor_leitor")["podio"]}


def test_personalizada_com_ajuste_da_serie_bate_com_o_podio(cliente, db, escola_completa):
    """Ajuste por SÉRIE (DificuldadeTurma "3º Ano": D vale 9): o pódio "Melhor
    Leitor" paga 9 a um aluno do 3º ano — e o exemplo do 3º ano diz 9, não o
    padrão 4. Sem turma do 2º ano, o exemplo diz que mostra o padrão."""
    escola = escola_completa["escola"]
    _personalizar(db, escola)
    nivel2 = db.execute(select(NivelDificuldade).where(
        NivelDificuldade.escola_id == escola.id,
        NivelDificuldade.codigo == "nivel_2")).scalar_one()
    db.add(DificuldadeTurma(escola_id=escola.id, ano_escolar="3º Ano", nivel_id=nivel2.id,
                            pontos=9.0))
    livro = Livro(escola_id=escola.id, titulo="Livro Exemplo D", nivel_codigo="D")
    db.add(livro)
    db.flush()
    leitor = _leitor(db, escola, escola_completa["turma"], "Aluno Exemplo Serie", livro)
    db.commit()

    podio = _podio_leitor(db, escola)
    assert podio[leitor.id] == 9.0
    d = cliente.get(_url(escola.id, "elefante", f"livro_id={livro.id}&serie=3")).json()
    assert d["valor"] == 9.0 and d["valor_exibido"] == podio[leitor.id]
    assert d["base_do_valor"] == "serie" and d["valor_padrao_escola"] == 4.0
    assert any("ajustou o valor do nível D" in a and "4,00" in a for a in d["avisos"])
    # Só o nível dá o mesmo valor.
    assert cliente.get(_url(escola.id, "elefante", "nivel=D&serie=3")).json()["valor"] == 9.0

    # Nenhuma turma do 2º ano: só o padrão existe, e o exemplo diz isso.
    d2 = cliente.get(_url(escola.id, "elefante", f"livro_id={livro.id}&serie=2")).json()
    assert d2["base_do_valor"] == "padrao" and d2["valor"] == 4.0 and d2["por_turma"] == []
    assert any("não tem turma do 2º ano" in a for a in d2["avisos"])


def test_personalizada_com_ajuste_por_turma_mostra_cada_turma(cliente, db, escola_completa):
    """Turmas do MESMO ano com valores diferentes (ajuste livre por turma): o
    exemplo não escolhe um valor — mostra o de cada turma, cada um igual ao que
    o pódio paga ao aluno daquela turma."""
    escola = escola_completa["escola"]
    _personalizar(db, escola)
    turma_a = escola_completa["turma"]
    turma_b = Turma(escola_id=escola.id, nome="3º Ano B", ano_escolar="3º Ano", ano_letivo=2026)
    db.add(turma_b)
    db.flush()
    db.add(PontuacaoNivelTurma(escola_id=escola.id, turma_id=turma_b.id,
                               pontos_por_codigo={"D": 6.5}))
    livro = Livro(escola_id=escola.id, titulo="Livro Exemplo D", nivel_codigo="D")
    db.add(livro)
    db.flush()
    leitor_a = _leitor(db, escola, turma_a, "Aluno Exemplo A", livro)
    leitor_b = _leitor(db, escola, turma_b, "Aluno Exemplo B", livro)
    db.commit()

    podio = _podio_leitor(db, escola)
    d = cliente.get(_url(escola.id, "elefante", f"livro_id={livro.id}&serie=3")).json()
    assert d["base_do_valor"] == "turmas"
    assert d["valor"] is None and d["valor_exibido"] is None
    assert (d["valor_minimo"], d["valor_maximo"]) == (4.0, 6.5)
    por_turma = {item["turma"]: item["valor_exibido"] for item in d["por_turma"]}
    assert por_turma == {"3º Ano A": podio[leitor_a.id], "3º Ano B": podio[leitor_b.id]}
    assert por_turma == {"3º Ano A": 4.0, "3º Ano B": 6.5}
    assert any("conforme a turma do 3º ano" in a for a in d["avisos"])
    # Nenhum dado de aluno na resposta (turma não é aluno).
    texto = json.dumps(d, ensure_ascii=False)
    assert "Aluno Exemplo" not in texto and "aluno_id" not in texto


def test_descricao_da_posicao_na_escada():
    descrever = rota_config._descrever_posicao
    assert descrever(dl.posicao_nivel("AA")) == "1º nível da escada, que começa no AA"
    assert descrever(dl.posicao_nivel("B")) == "6º nível da escada, que começa no AA"
    assert descrever(dl.posicao_nivel("Z")) == "30º nível da escada, que começa no AA"
    assert descrever(dl.posicao_nivel("Z+")) == "31º nível da escada, que começa no AA"
    assert descrever(dl.posicao_nivel("A+")) == "entre A e B na escada"
    assert descrever(None) is None
    # Todo nível oficial ganha uma descrição.
    for nivel in NIVEIS_OFICIAIS:
        assert descrever(dl.posicao_nivel(nivel)), nivel


# ---------------------------------------------------------------------------
# 2) Elefante: o exemplo arredondado é o valor do pódio "Melhor Leitor"
# ---------------------------------------------------------------------------

def test_exemplo_bate_com_o_podio_melhor_leitor_e_o_ranking(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    turma3 = escola_completa["turma"]                      # 3º Ano
    turma1 = Turma(escola_id=escola.id, nome="1º Ano A", ano_escolar="1º Ano", ano_letivo=2026)
    db.add(turma1)
    db.flush()
    leitor3 = _aluno(db, escola, turma3, "Aluno Exemplo Tres")
    leitor1 = _aluno(db, escola, turma1, "Aluno Exemplo Um")
    meta = dl.catalogo().buscar_por_id(9)                 # B, 70 palavras
    livro = Livro(escola_id=escola.id, titulo=meta.titulo, nivel_codigo=meta.nivel,
                  elefante_id=meta.id)
    db.add(livro)
    db.flush()
    for aluno in (leitor3, leitor1):
        db.add(Leitura(escola_id=escola.id, aluno_id=aluno.id, livro_id=livro.id,
                       data=DENTRO, tempo_leitura_min=10))
    db.commit()

    ex3 = cliente.get(_url(escola.id, "elefante", f"livro_id={livro.id}&serie=3")).json()
    ex1 = cliente.get(_url(escola.id, "elefante", f"livro_id={livro.id}&serie=1")).json()
    assert ex3["valor"] == 1.9728

    dados = premiacoes.premiacoes(db, escola.id, AGO_INI, AGO_FIM)
    podio = {p["aluno_id"]: p["valor"] for p in next(
        c for c in dados["categorias"] if c["chave"] == "melhor_leitor")["podio"]}
    assert podio[leitor3.id] == round(ex3["valor"], 2) == ex3["valor_exibido"]
    assert podio[leitor1.id] == round(ex1["valor"], 2) == ex1["valor_exibido"]

    ranking = cliente.get(f"{API}/escolas/{escola.id}/ranking/leitura?{Q_AGOSTO}").json()
    pontos = {i["aluno_id"]: i["pontos"] for i in ranking}
    assert pontos[leitor3.id] == ex3["valor_exibido"]
    assert pontos[leitor1.id] == ex1["valor_exibido"]


# ---------------------------------------------------------------------------
# 3) Matific: k e índice do exemplo = régua e pódio da premiação
# ---------------------------------------------------------------------------

# (atividades, estrelas) do GANHO no período. O último tem estrelas acima de 5
# por atividade: a premiação considera 40, não 60.
GANHOS = [(40, 150), (10, 50), (100, 300), (25, 120), (60, 200), (8, 60)]


def _semear_matific(db, escola_completa, ganhos):
    escola = escola_completa["escola"]
    turma = escola_completa["turma"]
    imp = Importacao(escola_id=escola.id, plataforma="matific", tipo="seed")
    db.add(imp)
    db.flush()
    alunos = []
    for i, (ativ, est) in enumerate(ganhos):
        a = _aluno(db, escola, turma, f"Aluno Exemplo M{i}")
        for quando, (a_, e_) in ((BASE, (0, 0)), (DENTRO, (ativ, est))):
            db.add(SnapshotMatific(escola_id=escola.id, aluno_id=a.id, importacao_id=imp.id,
                                   data_referencia=quando, atividades=a_, estrelas=e_,
                                   pontuacao_media=0.0))
        alunos.append(a)
    db.commit()
    return alunos


def test_matific_k_e_indice_iguais_aos_da_premiacao(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    alunos = _semear_matific(db, escola_completa, GANHOS)
    dados = premiacoes.premiacoes(db, escola.id, AGO_INI, AGO_FIM, limite=50)
    regua_real = dados["regua_matematica"]
    assert regua_real["k_mediana_atividades"] == 32.5          # mediana de 8,10,25,40,60,100
    podio = {p["aluno_id"]: p for p in next(
        c for c in dados["categorias"] if c["chave"] == "melhor_matematica")["podio"]}

    for aluno, (ativ, est) in zip(alunos, GANHOS):
        r = cliente.get(_url(escola.id, "matific",
                             f"atividades={ativ}&estrelas={est}&{Q_AGOSTO}"))
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["referencia_disponivel"] is True and d["motivo"] is None
        assert d["regua"]["k_mediana_atividades"] == regua_real["k_mediana_atividades"]
        assert d["regua"]["zeros_extras"] == regua_real["zeros_extras"]
        assert d["regua"]["alunos_com_atividade"] == regua_real["alunos_com_atividade"] == 6
        assert d["regua"]["modo"] == "periodo"
        assert d["regua"]["inicio_efetivo"] == regua_real["inicio_efetivo"]
        assert d["regua"]["fim_efetivo"] == regua_real["fim_efetivo"]
        # Mesmas estrelas que a premiação considerou (teto 5 por atividade).
        assert d["estrelas_consideradas"] == podio[aluno.id]["estrelas"]
        calc = d["calculo"]
        assert calc["indice_exibido"] == podio[aluno.id]["valor"]
        assert calc["indice"] == md.indice(ativ, md.limitar_estrelas(ativ, est), 32.5)
        assert calc["zeros_extras"] == pytest.approx(6.5)
        assert calc["denominador"] == pytest.approx(ativ + 6.5)
        assert calc["indice"] == min(5.0, calc["indice_sem_teto"])
        assert calc["teto_aplicado"] is False
        assert d["periodo"]["chave"] == "personalizado"

    # Caso E > 5·A: 8 atividades com 60 estrelas → contam 40 (= ganho_no_periodo).
    d = cliente.get(_url(escola.id, "matific", f"atividades=8&estrelas=60&{Q_AGOSTO}")).json()
    assert d["estrelas_consideradas"] == 40.0
    assert any("no máximo 5" in a for a in d["avisos"])


@pytest.mark.parametrize("ganhos,atividades,estrelas", [
    # k = 41: 0,2 × 41 = 8,200000000000001 no float — o caso que dava "parou no
    # máximo" num índice de 2,48 (os números do exemplo da própria tela).
    ([(20, 70), (30, 100), (41, 150), (50, 160), (60, 200)], 20, 70),
    # k = 7: 0,2 × 7 = 1,4000000000000001.
    ([(5, 10), (7, 20), (7, 21), (9, 30), (10, 40)], 1, 3),
])
def test_matific_teto_nao_aparece_por_ruido_de_float(cliente, db, escola_completa, ganhos,
                                                     atividades, estrelas):
    escola = escola_completa["escola"]
    alunos = _semear_matific(db, escola_completa, ganhos)
    dados = premiacoes.premiacoes(db, escola.id, AGO_INI, AGO_FIM, limite=50)
    k = dados["regua_matematica"]["k_mediana_atividades"]
    podio = {p["aluno_id"]: p["valor"] for p in next(
        c for c in dados["categorias"] if c["chave"] == "melhor_matematica")["podio"]}
    d = cliente.get(_url(escola.id, "matific",
                         f"atividades={atividades}&estrelas={estrelas}&{Q_AGOSTO}")).json()
    calc = d["calculo"]
    assert d["regua"]["k_mediana_atividades"] == k
    assert calc["teto_aplicado"] is False
    assert calc["indice"] == md.indice(atividades, estrelas, k) == calc["indice_sem_teto"]
    if (atividades, estrelas) in ganhos:
        assert calc["indice_exibido"] == podio[alunos[ganhos.index((atividades, estrelas))].id]


def test_matific_etapas_fecham_com_o_indice_em_toda_a_faixa():
    """Varredura (k × atividades × estrelas, inclusive acima de 5 por atividade):
    o índice do exemplo é o de ``matific_destaque.indice`` com as estrelas
    limitadas, o "antes do teto" fecha EXATAMENTE com ele, e o teto nunca aparece
    (com estrelas limitadas e k > 0 o índice fica abaixo de 5)."""
    casos = 0
    for k2 in range(1, 401, 3):                      # k = 0,5 … 200 (passo 1,5)
        k = k2 / 2
        regua = {"alunos_com_atividade": 10, "k_mediana_atividades": k, "modo": "periodo"}
        for atividades in range(1, 121, 7):
            for estrelas in (0, atividades, 3 * atividades, 5 * atividades, 7 * atividades):
                ex = rota_config.montar_exemplo_matific(regua, atividades, estrelas)
                calc = ex["calculo"]
                consideradas = md.limitar_estrelas(atividades, estrelas)
                assert ex["estrelas_consideradas"] == consideradas
                assert calc["indice"] == md.indice(atividades, consideradas, k)
                assert calc["indice"] == min(5.0, calc["indice_sem_teto"])
                assert calc["teto_aplicado"] is False
                assert calc["zeros_extras"] == round(md.FRACAO_ZEROS_EXTRAS * k, 4)
                casos += 1
    assert casos > 10_000


def test_regua_matematica_extraida_e_a_mesma_das_premiacoes(db, escola_completa):
    escola = escola_completa["escola"]
    _semear_matific(db, escola_completa, GANHOS)
    for ini, fim in ((AGO_INI, AGO_FIM), (None, None), (datetime(2025, 1, 1), datetime(2025, 3, 1)),
                     (AGO_FIM, AGO_INI), (datetime(2026, 9, 1), datetime(2026, 9, 30))):
        assert premiacoes.regua_matematica(db, escola.id, ini, fim) == \
            premiacoes.premiacoes(db, escola.id, ini, fim)["regua_matematica"]


def test_limitar_estrelas_e_a_expressao_antiga_do_ganho():
    """A extração não muda nada: ``limitar_estrelas(a, max(0, d))`` é o
    ``min(max(0, d), 5·a)`` que ``ganho_no_periodo`` fazia em linha (a ≥ 0)."""
    for a in (0.0, 1.0, 2.0, 7.0, 10.0, 33.0):
        for d in (-50.0, -1.0, 0.0, 1.0, 4.5, 10.0, 35.0, 50.0, 1000.0):
            antigo = min(max(0.0, d), md.ESTRELAS_MAX_POR_ATIVIDADE * a)
            assert md.limitar_estrelas(a, max(0.0, d)) == antigo


def test_ganho_no_periodo_com_estrelas_acima_do_teto():
    class Snap:
        def __init__(self, quando, atividades, estrelas):
            self.data_referencia = quando
            self.atividades = atividades
            self.estrelas = estrelas

    serie = [Snap(BASE, 0, 0), Snap(DENTRO, 2, 50)]
    ganho = md.ganho_no_periodo(serie, AGO_INI, AGO_FIM, 2026)
    assert ganho.atividades == 2.0 and ganho.estrelas == 10.0
    assert md.indice(2, md.limitar_estrelas(2, 50), 30) == 1.25
    assert md.indice(2, 50, 30) == 5.0    # sem o teto o exemplo mentiria


def test_poucos_alunos_nao_mostra_k_nem_indice(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    _semear_matific(db, escola_completa, GANHOS[:3])
    r = cliente.get(_url(escola.id, "matific", f"atividades=20&estrelas=70&{Q_AGOSTO}"))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["referencia_disponivel"] is False and d["motivo"] == "poucos_alunos"
    assert d["regua"]["k_mediana_atividades"] is None
    assert d["regua"]["zeros_extras"] is None
    assert d["calculo"] is None
    assert d["regua"]["alunos_com_atividade"] == 3
    assert d["estrelas_consideradas"] == 70.0
    assert "Poucos alunos no período" in d["mensagem"]
    # Nenhum dado de aluno na resposta.
    texto = json.dumps(d, ensure_ascii=False)
    assert "Aluno Exemplo" not in texto and "aluno_id" not in texto and "nome" not in texto


def test_sem_atividade_e_fora_do_ano_letivo(cliente, escola_completa):
    eid = escola_completa["escola"].id
    d = cliente.get(_url(eid, "matific", f"atividades=5&estrelas=10&{Q_AGOSTO}")).json()
    assert d["motivo"] == "sem_atividade" and d["calculo"] is None
    d = cliente.get(_url(eid, "matific", "atividades=5&estrelas=10&periodo=personalizado"
                                          "&inicio=2025-03-01&fim=2025-03-31")).json()
    assert d["motivo"] == "fora_do_ano_letivo" and d["regua"]["k_mediana_atividades"] is None
    d = cliente.get(_url(eid, "matific", "atividades=5&estrelas=10&periodo=personalizado"
                                          "&inicio=2026-08-31&fim=2026-08-01")).json()
    assert d["motivo"] == "periodo_invalido"
    # Sem período: o padrão é o mesmo da rota de Premiações ("mes").
    d = cliente.get(_url(eid, "matific", "atividades=5&estrelas=10")).json()
    assert d["periodo"]["chave"] == "mes"


@pytest.mark.parametrize("query", [
    "atividades=0&estrelas=0", "atividades=-3&estrelas=5", "atividades=5&estrelas=-1",
    "atividades=100001&estrelas=5", "estrelas=5", "atividades=5",
    "atividades=abc&estrelas=5",
])
def test_matific_422_para_entradas_invalidas(cliente, escola_completa, query):
    r = cliente.get(_url(escola_completa["escola"].id, "matific", query))
    assert r.status_code == 422, r.text


def test_matific_422_fala_do_numero_que_passou_do_limite(cliente, escola_completa):
    eid = escola_completa["escola"].id
    r = cliente.get(_url(eid, "matific", "atividades=10&estrelas=600000"))
    assert r.status_code == 422
    assert r.json()["detail"] == "Use números de um aluno: até 500.000 estrelas no período."
    r = cliente.get(_url(eid, "matific", "atividades=100001&estrelas=5"))
    assert r.status_code == 422
    assert r.json()["detail"] == "Use números de um aluno: até 100.000 atividades no período."
    # No limite exato ainda responde (sem referência no período, mas 200).
    assert cliente.get(_url(eid, "matific", "atividades=100000&estrelas=500000")).status_code == 200


def test_matific_data_invalida_400_como_nas_premiacoes(cliente, escola_completa):
    r = cliente.get(_url(escola_completa["escola"].id, "matific",
                         "atividades=5&estrelas=5&periodo=personalizado&inicio=31-08-2026"))
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# 4) Validação e autorização
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("query", [
    "nivel=XX&serie=3",            # nível fora do vocabulário oficial
    "nivel=nivel_3&serie=3",       # faixa não é nível do livro
    "nivel=D&serie=6",             # fora do Fundamental I
    "nivel=D&serie=0",
    "nivel=D&serie=1ª Fase",       # Educação Infantil não concorre
    "nivel=D&serie=abc",
    "nivel=D",                     # série obrigatória
    "serie=3",                     # nenhum livro nem nível
    "titulo=Domingo&serie=3",      # título sem nível
    "nivel=D&elefante_id=9&serie=3",   # duas formas ao mesmo tempo
])
def test_elefante_422(cliente, escola_completa, query):
    r = cliente.get(_url(escola_completa["escola"].id, "elefante", query))
    assert r.status_code == 422, r.text


def test_serie_aceita_rotulo_de_turma(cliente, escola_completa):
    eid = escola_completa["escola"].id
    d = cliente.get(_url(eid, "elefante", "nivel=D&serie=3º Ano")).json()
    assert d["serie"] == 3 and d["calculo"]["fator_serie"] == 1.2


def test_vocabulario_de_niveis_aceito_e_o_oficial(cliente, escola_completa):
    eid = escola_completa["escola"].id
    for nivel in sorted(NIVEIS_OFICIAIS):
        r = cliente.get(_url(eid, "elefante", f"nivel={nivel.replace('+', '%2B')}&serie=5"))
        assert r.status_code == 200, (nivel, r.text)
        assert r.json()["valor"] == dl.RegraGlobal().valor_tipico(nivel, "5º Ano")
        assert r.json()["valor"] > 0


def test_livro_de_outra_escola_e_id_fora_do_catalogo_dao_404(cliente, db, escola_completa):
    outra = Escola(nome="ESCOLA VIZINHA", ano_letivo_ativo=2026)
    db.add(outra)
    db.flush()
    livro_alheio = Livro(escola_id=outra.id, titulo="Livro Alheio", nivel_codigo="C")
    db.add(livro_alheio)
    db.commit()
    eid = escola_completa["escola"].id
    r = cliente.get(_url(eid, "elefante", f"livro_id={livro_alheio.id}&serie=3"))
    assert r.status_code == 404
    assert "acervo desta escola" in r.json()["detail"]
    r = cliente.get(_url(eid, "elefante", "elefante_id=999999999&serie=3"))
    assert r.status_code == 404


def test_professor_nao_acessa(db, escola_completa):
    escola = escola_completa["escola"]
    db.add(Usuario(escola_id=escola.id, nome="Professor Exemplo", email="prof@exemplo.local",
                   senha_hash=hash_senha("s3nh4"), cargo="professor"))
    db.commit()
    prof = _login("prof@exemplo.local")
    assert prof.get(_url(escola.id, "elefante", "nivel=D&serie=3")).status_code == 403
    assert prof.get(_url(escola.id, "matific", "atividades=5&estrelas=5")).status_code == 403


def test_secretaria_le_na_rede_dela_e_nao_fora(db, escola_completa):
    escola = escola_completa["escola"]
    rede = Rede(nome="Rede Exemplo", status="ativa")
    outra_rede = Rede(nome="Outra Rede", status="ativa")
    db.add_all([rede, outra_rede])
    db.flush()
    escola.rede_id = rede.id
    fora = Escola(nome="ESCOLA OUTRA REDE", ano_letivo_ativo=2026, rede_id=outra_rede.id)
    db.add(fora)
    db.add(Usuario(escola_id=escola.id, nome="Secretaria", email="sec@exemplo.local",
                   senha_hash=hash_senha("s3nh4"), cargo="coordenador", rede_id=rede.id))
    db.commit()
    sec = _login("sec@exemplo.local")
    assert sec.get(_url(escola.id, "elefante", "nivel=D&serie=3")).status_code == 200
    assert sec.get(_url(escola.id, "matific", "atividades=5&estrelas=5")).status_code == 200
    assert sec.get(_url(fora.id, "elefante", "nivel=D&serie=3")).status_code == 403
    assert sec.get(_url(fora.id, "matific", "atividades=5&estrelas=5")).status_code == 403


def test_coordenador_da_escola_le(db, escola_completa):
    escola = escola_completa["escola"]
    db.add(Usuario(escola_id=escola.id, nome="Coordenacao", email="coord@exemplo.local",
                   senha_hash=hash_senha("s3nh4"), cargo="coordenador"))
    db.commit()
    coord = _login("coord@exemplo.local")
    assert coord.get(_url(escola.id, "elefante", "nivel=D&serie=3")).status_code == 200
    assert coord.get(_url(escola.id, "matific", "atividades=5&estrelas=5")).status_code == 200


def _rede_com(db, escola, **modulos):
    rede = Rede(nome="Rede Modulos")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    for modulo, ativo in modulos.items():
        db.add(ModuloRede(rede_id=rede.id, modulo=modulo, ativo=ativo))
    db.commit()


def test_modulo_desligado_barra_so_a_sua_aba(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    _rede_com(db, escola, leitura=False)
    assert cliente.get(_url(escola.id, "elefante", "nivel=D&serie=3")).status_code == 403
    assert cliente.get(_url(escola.id, "matific", "atividades=5&estrelas=5")).status_code == 200


def test_tela_do_exemplo_nao_refaz_a_formula():
    """Varredura estática: os componentes da Pontuação só EXIBEM o que a API
    devolve — nenhuma constante nem função da fórmula (A3, ajuste por tamanho,
    fator de série, zeros extras do Matific) mora no front."""
    import re
    from pathlib import Path

    web = Path(__file__).resolve().parents[2] / "apps" / "web" / "src" / "components"
    proibidos = re.compile(
        r"Math\.(exp|log)|\b0?\.103\b|\b0?\.35\b|\b1\.35\b|\b0?\.8\b|\b1\.4\b"
        r"|\*\s*0?\.2\b|\b0?\.2\s*\*")
    for nome in ("ExemploPontuacao.tsx", "ComoFuncionaPontuacao.tsx"):
        texto = (web / nome).read_text(encoding="utf-8")
        achados = [f"{nome}:{n}: {linha.strip()}"
                   for n, linha in enumerate(texto.splitlines(), 1) if proibidos.search(linha)]
        assert not achados, "\n".join(achados)


def test_sem_matematica_o_matific_e_barrado(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    _rede_com(db, escola, matematica=False)
    assert cliente.get(_url(escola.id, "matific", "atividades=5&estrelas=5")).status_code == 403
    assert cliente.get(_url(escola.id, "elefante", "nivel=D&serie=3")).status_code == 200
