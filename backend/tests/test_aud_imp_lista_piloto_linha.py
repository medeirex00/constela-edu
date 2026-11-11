"""Lista Piloto: número com dígito sobrescrito ("2¹", "②", "2026²") e linha que não
pode ser lida.

Antes: o nº de chamada, o ano letivo e o nº da classe eram conferidos com
``isdigit()`` — verdadeiro para "2¹" — e o ``int()`` levantava ValueError. Na linha do
aluno, o ``except Exception: continue`` engolia o erro: a criança sumia da análise
sem aviso nem log (e, no Confirmar, a ficha dela era marcada "fora da lista
piloto"). No topo da aba ("Lista Piloto: 2026²"), o erro não tinha ``try`` e a prévia
inteira dava 500.

Agora os três usam ``isdecimal()`` (o número com rodapé fica sem o número, como
"2a"), e a linha que ainda não puder ser lida sai com aviso (aba e posição, sem nome),
vai para o log e deixa a turma fora da marcação "fora da lista piloto". Tudo fictício.
"""
import io
import logging

import pytest
from openpyxl import Workbook

from app.services import lista_piloto


def _planilha(numero_dois="2¹", ano="2026", sed="123456") -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "3º ANO A"
    ws.append(["Lista Piloto", ano])
    ws.append(["Escola", "EMEF Ficticia"])
    ws.append(["Turno", "Manhã"])
    ws.append(["Professor", "Prof Ficticio"])
    ws.append(["N.º da Classe (SED)", sed])
    ws.append(["Nº", "Nome", "RA"])
    ws.append([1, "Aluno Ficticio Um", "000000001"])
    ws.append([numero_dois, "Aluno Ficticio Dois", "000000002"])     # rodapé: transferido
    ws.append([3, "Aluno Ficticio Tres", "000000003"])
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def _alunos(analise) -> dict:
    return {al.nome: al for t in analise.turmas for al in t.alunos}


@pytest.mark.parametrize("numero", ["2¹", "②", "²"])
def test_numero_com_digito_sobrescrito_nao_some_com_a_crianca(numero):
    a = lista_piloto.analisar_matriculas(_planilha(numero), "lista_piloto_2026.xlsx")
    alunos = _alunos(a)
    assert set(alunos) == {"Aluno Ficticio Um", "Aluno Ficticio Dois", "Aluno Ficticio Tres"}
    assert alunos["Aluno Ficticio Dois"].numero_chamada is None   # como "2a": sem número
    assert alunos["Aluno Ficticio Um"].numero_chamada == 1


def test_ano_letivo_com_digito_sobrescrito_nao_derruba_a_analise():
    a = lista_piloto.analisar_matriculas(_planilha("2", ano="2026²"), "lista.xlsx")
    assert len(_alunos(a)) == 3
    assert a.ano_letivo is None          # nem o nome do arquivo traz o ano


def test_rota_da_previa_com_ano_sobrescrito_responde(cliente, escola_completa):
    escola_id = escola_completa["escola"].id
    r = cliente.post(f"/api/v1/escolas/{escola_id}/importacoes/matriculas/analisar",
                     files={"arquivo": ("lista.xlsx", _planilha("2", ano="2026²"),
                                        "application/vnd.openxmlformats-officedocument."
                                        "spreadsheetml.sheet")})
    assert r.status_code == 200, r.text


def test_numero_da_classe_com_digito_sobrescrito_nao_vira_codigo():
    a = lista_piloto.analisar_matriculas(_planilha("2", sed="123456¹"), "lista.xlsx")
    assert [t.sed for t in a.turmas] == [""]
    a = lista_piloto.analisar_matriculas(_planilha("2", sed="123456"), "lista.xlsx")
    assert [t.sed for t in a.turmas] == ["123456"]


def test_linha_que_nao_pode_ser_lida_vira_aviso_e_log(monkeypatch, caplog):
    """Qualquer outra falha ao ler UMA linha: ela fica de fora COM aviso (aba e
    posição, sem o nome) e log, e a turma não marca ninguém "fora da lista"."""
    original = lista_piloto._extrair_aluno

    def extrair(linha, colunas):
        if "Aluno Ficticio Dois" in linha:
            raise RuntimeError("falha simulada")
        return original(linha, colunas)

    monkeypatch.setattr(lista_piloto, "_extrair_aluno", extrair)
    caplog.set_level(logging.WARNING, logger="app.services.lista_piloto")
    a = lista_piloto.analisar_matriculas(_planilha("2"), "lista.xlsx")
    assert set(_alunos(a)) == {"Aluno Ficticio Um", "Aluno Ficticio Tres"}
    assert a.avisos == [
        "Aba “3º ANO A”, 2ª linha preenchida abaixo dos títulos: a linha não pôde ser "
        "lida e fica fora da importação. Confira a planilha e envie de novo; até lá, "
        "ninguém desta turma é marcado “fora da lista piloto”."]
    assert [t.linhas_puladas for t in a.turmas] == [1]
    mensagens = [r.getMessage() for r in caplog.records]
    assert any("3º ANO A" in m and "RuntimeError" in m for m in mensagens), mensagens
    assert not any("Ficticio" in m for m in mensagens), mensagens


# --- O mesmo ``isdigit()`` + ``int()`` nos outros leitores da importação ----------
# Número de chamada nos dados da linha (``identidade_aluno._chamada``), ``bookId`` do
# Elefante (``importacao._id_livro_elefante``) e ``elefante_id`` da linha no
# /confirmar (``importacoes._id_oficial``): "2¹" levantava ValueError (500) em vez de
# ser "sem número", como qualquer outro texto que não é número.

@pytest.mark.parametrize("bruto", ["2¹", "②", "12²"])
def test_numero_sobrescrito_nos_dados_da_linha_e_sem_numero(bruto):
    from app.routers import importacoes
    from app.services import identidade_aluno, importacao

    assert identidade_aluno._chamada({"numero_chamada": bruto}) is None
    assert importacao._id_livro_elefante(bruto) is None
    assert importacoes._id_oficial(bruto) is None


def test_numero_comum_nos_dados_da_linha_continua():
    from app.routers import importacoes
    from app.services import identidade_aluno, importacao

    assert identidade_aluno._chamada({"numero_chamada": " 12 "}) == 12
    assert importacao._id_livro_elefante("345") == 345
    assert importacoes._id_oficial("345") == 345
