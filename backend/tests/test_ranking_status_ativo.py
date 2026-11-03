"""Aluno NÃO ATIVO (transferido, fora da Lista Piloto, arquivado) nunca aparece
num ranking — mesmo com ``notas.posicao`` ainda carimbada no ano ativo.

Achado de produção (20/10/2026, leitura só de consulta, agregada): 7 alunos não
ativos (6 ``transferido`` + 1 ``fora_lista_piloto``) ainda têm ``notas.posicao``
preenchida no ano ativo. É esperado — o recálculo só regrava as linhas do
conjunto pontuado e não apaga a Nota de quem saiu (o dado gravado não é
alterado aqui) —, e por isso TODO leitor de ranking tem de filtrar o status NA
LEITURA. Este arquivo trava isso em cada superfície de ranking, pódio,
premiação, exportação e telão, num cenário em que o não ativo tem a Nota
congelada em 1º e o maior volume de dados de todos.
"""
import csv
import io
from datetime import datetime, timedelta

import pytest

from app.models import (
    Aluno,
    Importacao,
    Leitura,
    Livro,
    Matricula,
    Nota,
    SnapshotElefante,
    SnapshotMatific,
)
from app.services import scoring

API = "/api/v1"
STATUS_FORA = ("transferido", "fora_lista_piloto", "arquivado")


def _dados(db, escola, imp, aluno, livros, escala):
    agora = datetime.now().replace(microsecond=0)
    for dias, fator in ((20, 1), (2, 2)):
        quando = agora - timedelta(days=dias)
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                               data_referencia=quando, atividades=5 * escala * fator,
                               estrelas=12 * escala * fator, pontuacao_media=2.4))
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                                data_referencia=quando, livros_unicos=escala * fator,
                                tempo_leitura_min=15 * escala * fator,
                                livros_por_nivel={"D": escala * fator}))
    for i in range(min(escala, len(livros))):
        db.add(Leitura(escola_id=escola.id, aluno_id=aluno.id, livro_id=livros[i].id,
                       data=agora - timedelta(days=5, hours=i), tempo_leitura_min=20,
                       nivel_codigo="D"))


@pytest.fixture()
def cenario(db, escola_completa):
    escola = escola_completa["escola"]
    turma = escola_completa["turma"]
    turma.turno = "manha"
    imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    livros = [Livro(escola_id=escola.id, titulo=f"Livro Teste {i}", nivel_codigo="D")
              for i in range(12)]
    db.add_all(livros)
    db.flush()
    ativos = escola_completa["alunos"]
    for i, aluno in enumerate(ativos, start=1):
        _dados(db, escola, imp, aluno, livros, escala=i)
    fora = []
    for status in STATUS_FORA:
        a = Aluno(escola_id=escola.id, nome=f"Aluno Teste {status}", status="ativo")
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=turma.id,
                         ano_letivo=2026))
        _dados(db, escola, imp, a, livros, escala=10)
        fora.append((a, status))
    db.commit()
    # Recalcula com TODOS ativos (as Notas deles ganham posição de verdade)…
    scoring.recalcular_escola(db, escola.id)
    # …e só então eles saem: a Nota fica no banco, carimbada em 1º, como em
    # produção. O recálculo seguinte não a apaga.
    for aluno, status in fora:
        aluno.status = status
        nota = db.query(Nota).filter_by(aluno_id=aluno.id).one()
        nota.posicao = nota.posicao_leitura = nota.posicao_matematica = 1
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    for aluno, _status in fora:
        nota = db.query(Nota).filter_by(aluno_id=aluno.id).one()
        assert nota.posicao is not None, "o cenário precisa da Nota congelada"
    return {"escola": escola, "ativos": {a.id for a in ativos},
            "fora": {a.id for a, _ in fora}}


def _sem_fora(itens, cenario, chave="aluno_id"):
    ids = {i[chave] for i in itens}
    assert not ids & cenario["fora"], "aluno não ativo apareceu num ranking"
    return ids


@pytest.mark.parametrize("params", [
    {}, {"dimensao": "leitura"}, {"dimensao": "matematica"}, {"turno": "manha"},
    {"ano_escolar": "3º Ano"},
])
def test_ranking_da_escola(cliente, cenario, params):
    r = cliente.get(f"{API}/escolas/{cenario['escola'].id}/ranking", params=params)
    assert r.status_code == 200, r.text
    ids = _sem_fora(r.json(), cenario)
    assert ids == cenario["ativos"]
    assert sorted(i["posicao"] for i in r.json()) == [1, 2, 3]
    if params.get("dimensao"):
        assert {i["n_aferidos"] for i in r.json()} == {3}


@pytest.mark.parametrize("rota,params", [
    ("ranking/leitura", {}), ("ranking/leitura", {"periodo": "mes"}),
    ("ranking/matematica", {}), ("ranking/matematica", {"periodo": "mes"}),
    ("ranking-evolucao", {}), ("ranking-evolucao", {"dimensao": "leitura"}),
])
def test_rankings_por_periodo_e_evolucao(cliente, cenario, rota, params):
    r = cliente.get(f"{API}/escolas/{cenario['escola'].id}/{rota}", params=params)
    assert r.status_code == 200, r.text
    _sem_fora(r.json(), cenario)


def test_competicao_por_turno_premiacoes_e_top10(cliente, cenario):
    escola_id = cenario["escola"].id
    for grupo in cliente.get(f"{API}/escolas/{escola_id}/ranking/leitura/turnos").json():
        _sem_fora(grupo["alunos"], cenario)
        assert grupo["total"] == 3
    premios = cliente.get(f"{API}/escolas/{escola_id}/premiacoes",
                          params={"periodo": "ano_letivo", "limite": 50, "turnos": True}).json()
    for categoria in premios["categorias"]:
        _sem_fora(categoria["podio"], cenario)
    for turno in premios.get("turnos", []):
        for categoria in turno["categorias"]:
            _sem_fora(categoria["podio"], cenario)
    _sem_fora(cliente.get(f"{API}/escolas/{escola_id}/dashboard").json()["top10"], cenario)


def test_ranking_de_turmas_nao_conta_o_nao_ativo(cliente, cenario):
    r = cliente.get(f"{API}/escolas/{cenario['escola'].id}/ranking/turmas",
                    params={"dimensao": "leitura"})
    assert r.status_code == 200, r.text
    (turma,) = r.json()["itens"]
    assert turma["n_aferidos"] == 3 and turma["total_alunos"] == 3


def test_exportacao_do_ranking_e_cartaz_da_materia(cliente, cenario):
    escola_id = cenario["escola"].id
    r = cliente.get(f"{API}/escolas/{escola_id}/relatorios/ranking", params={"formato": "csv"})
    assert r.status_code == 200, r.text
    texto = r.content.decode("utf-8-sig")
    linhas = list(csv.reader(io.StringIO(texto), delimiter=";" if ";" in texto else ","))
    nomes = {linha[1] for linha in linhas[1:] if len(linha) > 1}
    assert not any(n.startswith("Aluno Teste") for n in nomes), nomes
    assert len(nomes) == 3
    for dimensao in ("leitura", "matematica"):
        r = cliente.get(f"{API}/escolas/{escola_id}/ranking/cartaz",
                        params={"dimensao": dimensao})
        assert r.status_code == 200, r.text


def test_painel_publico_e_pacote_do_app(cliente, cenario):
    escola_id = cenario["escola"].id
    r = cliente.put(f"{API}/escolas/{escola_id}/painel-publico",
                    json={"ativo": True, "slides": ["ranking", "evolucao"],
                          "intervalo_s": 8, "max_posicoes": 50})
    assert r.status_code == 200, r.text
    token = r.json()["url"].rsplit("/", 1)[-1]
    painel = cliente.get(f"{API}/publico/{token}/painel").json()
    _sem_fora(painel["ranking"], cenario)
    _sem_fora(painel.get("evolucao", []), cenario)
    pacote = cliente.get(f"{API}/escolas/{escola_id}/sincronizacao")
    assert pacote.status_code == 200, pacote.text
    _sem_fora(pacote.json()["ranking"], cenario)
    _sem_fora(pacote.json()["evolucao"], cenario)
    _sem_fora(pacote.json()["dashboard"]["top10"], cenario)


def test_frescor_nao_conta_o_nao_ativo(cliente, cenario):
    leitura = cliente.get(f"{API}/escolas/{cenario['escola'].id}/ranking/frescor"
                          ).json()["dimensoes"]["leitura"]
    assert leitura["alunos_com_dado"] == 3
