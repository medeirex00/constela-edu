"""REV2-MOTOR-1 (DEC-19 / RANKINGS-4) — o ARQUIVO e o CARTAZ do Ranking Geral
listam as mesmas crianças, na mesma posição, que a TELA.

A tela do Ranking Geral (``GET /ranking`` e a aba do app) deixou de listar a
criança sem NENHUM dado (``rankings._ranking(so_com_dado=True)``). A exportação
(CSV, XLSX e PDF em ``/relatorios/ranking``) e o cartaz (``/ranking/cartaz`` sem
dimensão) saem de ``services.relatorios._consulta_ranking_geral``, que ainda não
tem esse corte: a criança sem dado volta no arquivo com posição e Nota Geral
0,0 e, para o professor (o arquivo é renumerado 1..N "como na tela"), empurra a
posição de quem vem depois — a mesma criança fica com uma posição na tela e
outra no arquivo.

A correção é de ``backend/app/services/relatorios.py`` (frente rede): o mesmo
corte de ``_ranking(so_com_dado=True)`` em ``_consulta_ranking_geral``. Até lá
os testes abaixo ficam ``xfail(strict=True)``: quando o corte entrar, eles
passam e o ``strict`` derruba a suíte — é o aviso para tirar a marca.

Cenário do teste DEC-19 (``test_aud2_motor_ranking_geral_sem_dado``): Ana tem
Matific, João não tem dado nenhum e Sofia tem retrato zerado (zero legítimo,
continua). Dados 100% fictícios.
"""
import csv
import io

import pytest
from openpyxl import load_workbook

from app.services import relatorios as svc
from tests.test_aud2_motor_ranking_geral_sem_dado import _cenario
from tests.test_permissoes import cenario_professor  # noqa: F401 — fixture

API = "/api/v1"

PENDENTE_REDE = pytest.mark.xfail(
    strict=True,
    reason="REV2-MOTOR-1: falta o corte so_com_dado em "
           "services/relatorios._consulta_ranking_geral (frente rede)")


def _tela(cliente, escola):
    r = cliente.get(f"{API}/escolas/{escola.id}/ranking")
    assert r.status_code == 200, r.text
    return [(int(i["posicao"]), i["nome"]) for i in r.json()]


def _csv(cliente, escola):
    r = cliente.get(f"{API}/escolas/{escola.id}/relatorios/ranking",
                    params={"formato": "csv"})
    assert r.status_code == 200, r.text
    linhas = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
    return [(int(linha[0]), linha[1]) for linha in linhas[1:]]


def _xlsx(cliente, escola):
    r = cliente.get(f"{API}/escolas/{escola.id}/relatorios/ranking",
                    params={"formato": "xlsx"})
    assert r.status_code == 200, r.text
    ws = load_workbook(io.BytesIO(r.content)).active
    # Linha 1 = título; 2 = cabeçalho; dados a partir da 3.
    return [(int(pos), nome) for pos, nome, *_ in ws.iter_rows(min_row=3, values_only=True)]


@pytest.fixture()
def cartazes(monkeypatch):
    """Guarda as linhas que cada cartaz (PDF do Ranking Geral) imprimiria."""
    capturados = []

    def _falso(escola_nome, cor, ano_letivo, cabecalho, linhas, *args, **kwargs):
        capturados.append([(int(linha[0]), linha[1]) for linha in linhas])
        return b"%PDF-1.4 cartaz de teste"

    monkeypatch.setattr(svc, "gerar_cartaz_ranking", _falso)
    return capturados


@PENDENTE_REDE
def test_arquivo_da_gestao_lista_quem_a_tela_lista(db, escola_completa, cliente):
    escola, ana, joao, sofia = _cenario(db, escola_completa)
    tela = _tela(cliente, escola)
    assert tela == [(1, ana.nome), (3, sofia.nome)], tela
    assert _csv(cliente, escola) == tela
    assert _xlsx(cliente, escola) == tela


@PENDENTE_REDE
def test_cartaz_da_gestao_lista_quem_a_tela_lista(db, escola_completa, cliente, cartazes):
    escola, ana, joao, sofia = _cenario(db, escola_completa)
    tela = _tela(cliente, escola)
    r = cliente.get(f"{API}/escolas/{escola.id}/ranking/cartaz")
    assert r.status_code == 200, r.text
    r = cliente.get(f"{API}/escolas/{escola.id}/relatorios/ranking",
                    params={"formato": "pdf"})
    assert r.status_code == 200, r.text
    # O cartaz de /ranking/cartaz e o PDF do relatório: a lista da tela.
    assert cartazes == [tela, tela], cartazes


@PENDENTE_REDE
def test_arquivo_e_cartaz_do_professor_tem_a_posicao_da_tela(
        cenario_professor, escola_completa, db, cartazes):  # noqa: F811
    c = cenario_professor
    escola, ana, joao, sofia = _cenario(db, escola_completa)
    tela = _tela(c["professor"], escola)
    assert tela == [(1, ana.nome), (2, sofia.nome)], tela
    assert _csv(c["professor"], escola) == tela
    assert _xlsx(c["professor"], escola) == tela
    r = c["professor"].get(f"{API}/escolas/{escola.id}/relatorios/ranking",
                           params={"formato": "pdf"})
    assert r.status_code == 200, r.text
    assert cartazes == [tela], cartazes


def test_controle_o_zero_legitimo_continua_no_arquivo(db, escola_completa, cliente):
    """Controle (passa hoje e depois do corte): o retrato ZERADO da Sofia é um
    zero legítimo — ela segue no arquivo, com a Nota Geral dela."""
    escola, ana, joao, sofia = _cenario(db, escola_completa)
    nomes = [nome for _pos, nome in _csv(cliente, escola)]
    assert ana.nome in nomes and sofia.nome in nomes
