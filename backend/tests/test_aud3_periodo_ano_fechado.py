"""S_G_VIRADA-2 — período de um ano letivo ENCERRADO, consultado depois da virada.

A cerimônia de 2026 ficou para fevereiro de 2027: o Admin Global já virou o ano da escola
e a Lista Piloto de 2027 já entrou. Premiações, Ranking de Leitura (e o de Matemática, o
espelho dele) e o Relatório por Período (tela e PDF) de 01/10/2026 a 15/12/2026 tiravam
as crianças das matrículas do ano ATIVO (2027): a formanda do 5º ano que liderou sumia e
as demais apareciam na turma de 2027, sem aviso — e a régua da Matemática, na mesma
resposta, já dizia "fora do ano letivo".

DECISÃO TÉCNICA (fase D): período inteiro num ano letivo ANTERIOR ao ativo → as crianças
matriculadas NAQUELE ano, com a turma e a série dele (``periodos.populacao_do_periodo``);
período que atravessa anos → a regra de sempre (o ano ativo), DECLARADA na resposta.
O recorte de turma (o filtro da tela e as turmas do professor) continua escolhendo as
crianças pelas turmas de agora — as únicas que os seletores e as permissões conhecem.

Mundo 100% fictício e datas fixas: o resultado não depende do relógio.
"""
from datetime import datetime

import pdfplumber
import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import (Aluno, Importacao, Leitura, Livro, Matricula, Professor,
                        SnapshotMatific, Turma, Usuario)
from app.services import periodos, premiacoes
from app.services import relatorios_periodo_pdf as pdf

ANO_FECHADO, ANO_NOVO = 2026, 2027
PERIODO = {"periodo": "personalizado", "inicio": "2026-10-01", "fim": "2026-12-15"}
ATRAVESSA = {"periodo": "personalizado", "inicio": "2026-11-01", "fim": "2027-01-31"}
DO_ANO_NOVO = {"periodo": "personalizado", "inicio": "2027-01-01", "fim": "2027-01-31"}

ANA = "ANA CLARA FICTICIA SOUZA"
BETO = "BETO FICTICIO LIMA"
DORA = "DORA FICTICIA MELO"      # a formanda: 5º ano em 2026, sem matrícula em 2027


@pytest.fixture()
def virada(db, escola_completa):
    """A escola ainda em 2026, com o ano inteiro de dados; ``virar()`` passa para 2027.

    2026: ANA e BETO no 4º Ano A (manhã), DORA no 5º Ano A (tarde). 2027: ANA e BETO no
    5º Ano A (manhã); DORA se formou e saiu (só tem a matrícula de 2026). Leitura em
    novembro de 2026: DORA 4 livros, ANA 2, BETO 1; BETO lê mais 2 em janeiro de 2027.
    Matific de 2026 (base em setembro, coleta em 30/11): DORA à frente, depois ANA e BETO.
    """
    escola = escola_completa["escola"]
    assert escola.ano_letivo_ativo == ANO_FECHADO

    def turma(nome, serie, ano, turno):
        t = Turma(escola_id=escola.id, nome=nome, ano_escolar=serie, ano_letivo=ano,
                  turno=turno, status="ativa")
        db.add(t)
        db.flush()
        return t

    t4 = turma("4º Ano A", "4º Ano", ANO_FECHADO, "manha")
    t5 = turma("5º Ano A", "5º Ano", ANO_FECHADO, "tarde")
    t5_novo = turma("5º Ano A", "5º Ano", ANO_NOVO, "manha")
    alunos = {}
    for nome, t in ((ANA, t4), (BETO, t4), (DORA, t5)):
        a = Aluno(escola_id=escola.id, nome=nome, status="ativo")
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=t.id,
                         ano_letivo=ANO_FECHADO))
        alunos[nome] = a
    for nome in (ANA, BETO):
        db.add(Matricula(escola_id=escola.id, aluno_id=alunos[nome].id,
                         turma_id=t5_novo.id, ano_letivo=ANO_NOVO))
    livros = []
    for i in range(6):
        livro = Livro(escola_id=escola.id, titulo=f"LIVRO FICTICIO {i}", nivel_codigo="D")
        db.add(livro)
        db.flush()
        livros.append(livro)

    def ler(nome, livro, quando):
        db.add(Leitura(escola_id=escola.id, aluno_id=alunos[nome].id, livro_id=livro.id,
                       data=quando, tempo_leitura_min=30, nivel_codigo="D"))

    for nome, n in ((DORA, 4), (ANA, 2), (BETO, 1)):
        for i in range(n):
            ler(nome, livros[i], datetime(2026, 11, 10 + i, 12, 0))
    ler(BETO, livros[4], datetime(2027, 1, 20, 12, 0))
    ler(BETO, livros[5], datetime(2027, 1, 21, 12, 0))

    imp = Importacao(escola_id=escola.id, plataforma="matific", tipo="seed")
    db.add(imp)
    db.flush()
    for nome, atividades, estrelas, media in ((DORA, 20, 90, 4.5), (ANA, 10, 40, 4.0),
                                              (BETO, 8, 24, 3.0)):
        for quando, ativ, estr, med in ((datetime(2026, 9, 20, 12, 0), 0, 0, 0.0),
                                        (datetime(2026, 11, 30, 12, 0), atividades,
                                         estrelas, media)):
            db.add(SnapshotMatific(escola_id=escola.id, aluno_id=alunos[nome].id,
                                   importacao_id=imp.id, data_referencia=quando,
                                   atividades=ativ, estrelas=estr, pontuacao_media=med))
    db.commit()

    def virar():
        escola.ano_letivo_ativo = ANO_NOVO
        db.commit()

    return {"escola": escola, "t4": t4, "t5": t5, "t5_novo": t5_novo, "alunos": alunos,
            "virar": virar}


def _get(cliente, virada, rota, params):
    resp = cliente.get(f"/api/v1/escolas/{virada['escola'].id}/{rota}", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _podio(resp, chave, categorias=None):
    cats = categorias if categorias is not None else resp["categorias"]
    cat = next(c for c in cats if c["chave"] == chave)
    return [(i["nome"], i["turma"]) for i in cat["podio"]]


def _leitores(lista):
    return [(i["nome"], i["turma"], i["livros"]) for i in lista]


DO_ANO_FECHADO = {"ano_letivo": ANO_FECHADO, "origem": "ano_do_periodo",
                  "ano_letivo_ativo": ANO_NOVO}


# ============================================================================
# A regra, sozinha
# ============================================================================
@pytest.mark.parametrize(("inicio", "fim", "ativo", "esperado"), [
    # período inteiro num ano ANTERIOR ao ativo: as crianças daquele ano
    (datetime(2026, 10, 1), datetime(2026, 12, 15, 23, 59), 2027, (2026, "ano_do_periodo")),
    (datetime(2025, 3, 1), datetime(2025, 3, 31), 2027, (2025, "ano_do_periodo")),
    # no ano ativo, ou "Todo o histórico": a regra de sempre, sem aviso
    (datetime(2026, 10, 1), datetime(2026, 12, 15), 2026, (2026, "ano_ativo")),
    (None, None, 2027, (2027, "ano_ativo")),
    (datetime(2027, 3, 1), None, 2027, (2027, "ano_ativo")),
    # depois do ano ativo (janeiro, a escola ainda não virou): as crianças de agora
    (datetime(2027, 1, 1), datetime(2027, 1, 31), 2026, (2026, "ano_ativo")),
    # atravessa anos (ou não tem uma das pontas): a regra de sempre, DECLARADA
    (datetime(2026, 11, 1), datetime(2027, 1, 31), 2027, (2027, "atravessa_anos")),
    (datetime(2026, 12, 1), datetime(2027, 1, 31), 2026, (2026, "atravessa_anos")),
    (None, datetime(2026, 12, 15), 2027, (2027, "atravessa_anos")),
    (datetime(2026, 3, 1), None, 2027, (2027, "atravessa_anos")),
])
def test_populacao_do_periodo(inicio, fim, ativo, esperado):
    pop = periodos.populacao_do_periodo(inicio, fim, ativo)
    assert (pop.ano_letivo, pop.origem) == esperado
    assert pop.como_dict() == {"ano_letivo": esperado[0], "origem": esperado[1],
                               "ano_letivo_ativo": ativo}


# ============================================================================
# Premiações
# ============================================================================
def test_premiacoes_do_ano_fechado_saem_com_as_criancas_e_as_turmas_daquele_ano(
        cliente_global, virada):
    params = {**PERIODO, "limite": 50, "turnos": "true"}
    antes = _get(cliente_global, virada, "premiacoes", params)
    virada["virar"]()
    depois = _get(cliente_global, virada, "premiacoes", params)

    # A formanda que liderou continua em 1º, e cada criança com a turma de 2026.
    assert _podio(depois, "mais_livros") == [
        (DORA, "5º Ano A"), (ANA, "4º Ano A"), (BETO, "4º Ano A")]
    assert [n for n, _t in _podio(depois, "melhor_matematica")] == [DORA, ANA, BETO]
    # O pódio de um ano fechado não muda porque o ano da escola virou.
    assert depois["categorias"] == antes["categorias"]
    assert depois["turnos"] == antes["turnos"]
    tarde = next(g for g in depois["turnos"] if g["turno"] == "tarde")
    assert _podio(depois, "mais_livros", tarde["categorias"]) == [(DORA, "5º Ano A")]
    # A Matemática mede o contador DAQUELE ano, com a mesma coorte.
    assert depois["regua_matematica"] == antes["regua_matematica"]
    assert depois["regua_matematica"]["ano_letivo"] == ANO_FECHADO
    assert depois["regua_matematica"]["modo"] == "periodo"
    # E a resposta diz de que ano são as crianças.
    assert depois["populacao"] == DO_ANO_FECHADO
    assert antes["populacao"] == {"ano_letivo": ANO_FECHADO, "origem": "ano_ativo",
                                  "ano_letivo_ativo": ANO_FECHADO}


def _frescor_da_matematica(resp):
    return ((resp.get("frescor") or {}).get("dimensoes") or {}).get("matematica")


def test_selo_de_frescor_das_premiacoes_do_ano_fechado_nao_desmente_o_podio(
        cliente_global, virada):
    """REV3-PERIODO-1: o selo "de quando é o dado", logo acima dos pódios, era calculado
    com as crianças e o contador do Matific do ano ATIVO. Depois da virada dizia
    "Matemática (Matific): sem dados ainda." ao lado de uma Melhor Matemática com DORA,
    ANA e BETO (e, com a 1ª coleta de 2027, diria "dados de fev/2027" para um pódio de
    out–dez/2026). O selo de um ano fechado ou é o daquele ano, ou não aparece."""
    params = {**PERIODO, "limite": 50}
    antes = _get(cliente_global, virada, "premiacoes", params)
    # No ano ativo o selo continua lá, com a coleta de 30/11/2026.
    assert _frescor_da_matematica(antes)["dado_mais_recente_em"] == "2026-11-30"

    virada["virar"]()
    depois = _get(cliente_global, virada, "premiacoes", params)
    assert [n for n, _t in _podio(depois, "melhor_matematica")] == [DORA, ANA, BETO]
    mat = _frescor_da_matematica(depois)
    assert mat is None or (mat["estado"], mat["dado_mais_recente_em"]) == (
        _frescor_da_matematica(antes)["estado"], "2026-11-30"), (
        f"selo do ano fechado com a população do ano ativo: {mat}")

    # Período do ano ativo ou que atravessa anos: as crianças de agora, o selo de agora.
    for params_ativo in (ATRAVESSA, DO_ANO_NOVO):
        assert _get(cliente_global, virada, "premiacoes", params_ativo)["frescor"] is not None


def test_regua_do_exemplo_da_pontuacao_e_a_do_ano_fechado(db, virada):
    """O "Quer ver um exemplo?" da Pontuação usa a MESMA régua das premiações."""
    virada["virar"]()
    regua = premiacoes.regua_matematica(db, virada["escola"].id, datetime(2026, 10, 1),
                                        datetime(2026, 12, 15, 23, 59, 59))
    assert (regua["ano_letivo"], regua["modo"], regua["alunos_com_atividade"]) == (
        ANO_FECHADO, "periodo", 3)


# ============================================================================
# Ranking de Leitura e de Matemática por período
# ============================================================================
def test_ranking_de_leitura_do_ano_fechado(cliente_global, virada):
    antes = _get(cliente_global, virada, "ranking/leitura", PERIODO)
    virada["virar"]()
    depois = _get(cliente_global, virada, "ranking/leitura", PERIODO)

    assert _leitores(depois) == [(DORA, "5º Ano A", 4), (ANA, "4º Ano A", 2),
                                 (BETO, "4º Ano A", 1)]
    assert [(i["nome"], i["pontos"], i["posicao"]) for i in depois] == [
        (i["nome"], i["pontos"], i["posicao"]) for i in antes]
    assert {(i["ano_letivo"], i["populacao"]) for i in depois} == {
        (ANO_FECHADO, "ano_do_periodo")}
    assert {(i["ano_letivo"], i["populacao"]) for i in antes} == {(ANO_FECHADO, "ano_ativo")}
    # A SÉRIE é a daquele ano: o 5º ano de 2026 é o da formanda.
    quinto = _get(cliente_global, virada, "ranking/leitura", {**PERIODO, "ano_escolar": "5º Ano"})
    assert _leitores(quinto) == [(DORA, "5º Ano A", 4)]
    quarto = _get(cliente_global, virada, "ranking/leitura", {**PERIODO, "ano_escolar": "4º Ano"})
    assert [n for n, _t, _l in _leitores(quarto)] == [ANA, BETO]


def test_ranking_de_matematica_do_ano_fechado(cliente_global, virada):
    antes = _get(cliente_global, virada, "ranking/matematica", PERIODO)
    virada["virar"]()
    depois = _get(cliente_global, virada, "ranking/matematica", PERIODO)

    assert [(i["nome"], i["turma"], i["estrelas"]) for i in depois] == [
        (DORA, "5º Ano A", 90), (ANA, "4º Ano A", 40), (BETO, "4º Ano A", 24)]
    assert [(i["nome"], i["estrelas"], i["atividades"]) for i in depois] == [
        (i["nome"], i["estrelas"], i["atividades"]) for i in antes]
    assert {(i["ano_letivo"], i["populacao"]) for i in depois} == {
        (ANO_FECHADO, "ano_do_periodo")}


# ============================================================================
# Relatório por Período (tela e PDF)
# ============================================================================
PARAMS_RELATORIO = {**PERIODO, "plataformas": ["elefante", "matific"]}


def _por_aluno(dados):
    return {a["nome"]: (a["turma"], (a["elefante"] or {}).get("livros_novos", 0),
                        (a["matific"] or {}).get("atividades"))
            for a in dados["por_aluno"]}


def test_relatorio_do_ano_fechado_mede_as_criancas_daquele_ano(cliente_global, virada):
    antes = _get(cliente_global, virada, "relatorios/periodo", PARAMS_RELATORIO)
    virada["virar"]()
    depois = _get(cliente_global, virada, "relatorios/periodo", PARAMS_RELATORIO)

    alunos = _por_aluno(depois)
    assert alunos[DORA] == ("5º Ano A", 4, 20)
    assert alunos[ANA] == ("4º Ano A", 2, 10)
    assert alunos[BETO] == ("4º Ano A", 1, 8)
    assert alunos == _por_aluno(antes)
    # 3 da turma-base de 2026 (sem dado) + ANA, BETO e DORA.
    assert depois["alunos"] == antes["alunos"]
    assert depois["alunos"]["considerados"] == 6
    assert depois["elefante"]["livros_novos"] == 7
    assert depois["matific"]["atividades"] == 38
    assert sorted(t["turma"] for t in depois["por_turma"]) == [
        "3º Ano A", "4º Ano A", "5º Ano A"]
    assert depois["populacao"] == DO_ANO_FECHADO
    assert depois["escola"]["ano_letivo"] == ANO_NOVO


def _texto_da_vitrine(html: str) -> str:
    import html as html_mod
    import re
    sem_estilo = re.sub(r"<style.*?</style>", " ", html, flags=re.S)
    return re.sub(r"\s+", " ", html_mod.unescape(re.sub(r"<[^>]+>", " ", sem_estilo)))


def test_pdf_do_ano_fechado_diz_de_que_ano_sao_as_criancas(cliente_global, virada,
                                                           monkeypatch):
    virada["virar"]()
    dados = _get(cliente_global, virada, "relatorios/periodo", PARAMS_RELATORIO)
    vitrine = _texto_da_vitrine(pdf.montar_html(dados))
    assert "Ano letivo 2026" in vitrine
    assert "Crianças e turmas" in vitrine and "matriculadas em 2026" in vitrine

    # A reserva (a que roda sem Chromium, na integração contínua) diz o mesmo.
    def sem_chromium(*_a, **_k):
        raise RuntimeError("sem Chromium (forçado pelo teste)")
    monkeypatch.setattr(pdf, "_relatorio_html_pdf", sem_chromium)
    resp = cliente_global.get(
        f"/api/v1/escolas/{virada['escola'].id}/relatorios/periodo.pdf",
        params=PARAMS_RELATORIO)
    assert resp.status_code == 200, resp.text
    import io
    with pdfplumber.open(io.BytesIO(resp.content)) as doc:
        texto = "\n".join((p.extract_text() or "") for p in doc.pages)
    assert "Crianças e turmas" in texto and "as de 2026" in texto
    assert DORA in texto


# ============================================================================
# Período que atravessa os anos: a regra de sempre, declarada
# ============================================================================
def test_periodo_que_atravessa_os_anos_usa_o_ano_ativo_e_declara(cliente_global, virada):
    virada["virar"]()
    premio = _get(cliente_global, virada, "premiacoes", {**ATRAVESSA, "limite": 50})
    assert premio["populacao"] == {"ano_letivo": ANO_NOVO, "origem": "atravessa_anos",
                                   "ano_letivo_ativo": ANO_NOVO}
    assert _podio(premio, "mais_livros") == [(BETO, "5º Ano A"), (ANA, "5º Ano A")]

    leitura = _get(cliente_global, virada, "ranking/leitura", ATRAVESSA)
    assert _leitores(leitura) == [(BETO, "5º Ano A", 3), (ANA, "5º Ano A", 2)]
    assert {(i["ano_letivo"], i["populacao"]) for i in leitura} == {
        (ANO_NOVO, "atravessa_anos")}

    relatorio = _get(cliente_global, virada, "relatorios/periodo",
                     {**ATRAVESSA, "plataformas": ["elefante"]})
    assert relatorio["populacao"]["origem"] == "atravessa_anos"
    assert DORA not in _por_aluno(relatorio)

    # Dentro do ano novo, nada muda: as crianças de agora, sem aviso.
    novo = _get(cliente_global, virada, "ranking/leitura", DO_ANO_NOVO)
    assert _leitores(novo) == [(BETO, "5º Ano A", 2)]
    assert novo[0]["populacao"] == "ano_ativo" and novo[0]["ano_letivo"] == ANO_NOVO


# ============================================================================
# O recorte de turma (o filtro e as turmas do professor) no ano fechado
# ============================================================================
@pytest.fixture()
def cliente_professor(db, virada):
    """A professora do 5º Ano A de 2027 (a turma de ANA e BETO agora)."""
    escola = virada["escola"]
    prof = Professor(escola_id=escola.id, nome="PROFESSORA FICTICIA",
                     email="prof.ficticia@teste.local")
    db.add(prof)
    db.flush()
    virada["t5_novo"].professor_id = prof.id
    db.add(Usuario(escola_id=escola.id, nome="PROFESSORA FICTICIA",
                   email="prof.ficticia@teste.local", senha_hash=hash_senha("s3nh4"),
                   cargo="professor"))
    db.commit()
    cliente = TestClient(app)
    tok = cliente.post("/api/v1/auth/login",
                       data={"username": "prof.ficticia@teste.local", "password": "s3nh4"})
    assert tok.status_code == 200, tok.text
    cliente.headers["Authorization"] = f"Bearer {tok.json()['access_token']}"
    return cliente


def test_recorte_de_turma_no_ano_fechado_escolhe_as_criancas_de_agora(
        cliente_global, cliente_professor, virada):
    """Os seletores e as permissões só conhecem as turmas de agora: o recorte continua
    escolhendo QUEM aparece por elas (as crianças do 5º Ano A de 2027), e cada uma sai
    com a turma que tinha no ano do período — a formanda não é da turma de agora."""
    virada["virar"]()
    turma_nova = {"turma_id": virada["t5_novo"].id}
    esperado = [(ANA, "4º Ano A", 2), (BETO, "4º Ano A", 1)]

    assert _leitores(_get(cliente_global, virada, "ranking/leitura",
                          {**PERIODO, **turma_nova})) == esperado
    assert _leitores(_get(cliente_professor, virada, "ranking/leitura", PERIODO)) == esperado

    for cliente, extra in ((cliente_global, turma_nova), (cliente_professor, {})):
        premio = _get(cliente, virada, "premiacoes", {**PERIODO, **extra, "limite": 50})
        assert _podio(premio, "mais_livros") == [(ANA, "4º Ano A"), (BETO, "4º Ano A")]
        assert premio["populacao"] == DO_ANO_FECHADO
        # A régua da Matemática continua sendo a da escola inteira daquele ano.
        assert premio["regua_matematica"]["alunos_com_atividade"] == 3

    rel_turma = _get(cliente_global, virada, "relatorios/periodo",
                     {**PARAMS_RELATORIO, "escopo": "turma", **turma_nova})
    assert set(_por_aluno(rel_turma)) == {ANA, BETO}
    assert "A turma escolhida é a de agora" in _texto_da_vitrine(pdf.montar_html(rel_turma))
    rel_prof = _get(cliente_professor, virada, "relatorios/periodo", PARAMS_RELATORIO)
    assert set(_por_aluno(rel_prof)) == {ANA, BETO}
    assert "As turmas de quem gerou são as de agora" in _texto_da_vitrine(
        pdf.montar_html(rel_prof))
    rel_aluno = _get(cliente_professor, virada, "relatorios/periodo",
                     {**PARAMS_RELATORIO, "escopo": "aluno", **turma_nova,
                      "aluno_id": virada["alunos"][ANA].id})
    assert _por_aluno(rel_aluno) == {ANA: ("4º Ano A", 2, 10)}
