"""Auditoria (frente importação): a prévia diz ONDE a ficha nova nasce.

IMPORTACAO-1 (parte do backend): a correspondência do /analisar só trazia status,
aluno, motivo, via e alternativas — não a turma que a porta única decidiu para o
aluno novo. A tela adivinhava a turma pelo nome (``acharTurmaPorNome``, que casava a
letra "a" dentro de "ano"/"fase"/"tarde") e mandava criar a criança do "1 ANO A" na
"1º Ano B" ou na "1ª Fase A". Agora a correspondência leva a decisão:

  * ``turma_id``/``turma_nome`` — a turma cadastrada que recebe a ficha nova;
  * ``turma_nova`` — sem turma da sala no cadastro: o nome da turma que a
    confirmação cria a partir da turma do relatório;
  * os três nulos — o relatório não informa turma (a tela pede a turma), ou a linha
    não cria ficha (vínculo ou revisão).

E o corpo que a tela monta com isso faz a criança nascer onde a prévia disse.
Dados fictícios.
"""
import pathlib
import re

import pytest

from tests.test_aud_imp_etapa_turma import (
    _analise, _confirmar, _placar, _turma, _turmas_do_aluno)

RAIZ = pathlib.Path(__file__).resolve().parents[2]
TIPOS_TS = RAIZ / "packages" / "core" / "src" / "tipos.ts"
CAMPOS_TURMA = ("turma_id", "turma_nome", "turma_nova")


def _uma(turma, nome, uuid):
    return _placar(turma, [{"nome": nome, "uuid": uuid, "estrelas": 5, "atividades": 1}])


def _turma_da(corr):
    return tuple(corr.get(c) for c in CAMPOS_TURMA)


def _corpo_da_tela(analise):
    """O corpo que a tela passa a montar com a turma da prévia: a turma cadastrada
    (``criar_em_turma_id``) ou, com ``turma_nova``, a turma do relatório pelo nome."""
    linhas = []
    for linha in analise["linhas"]:
        corr = linha["correspondencia"]
        relatorio = linha["dados"].get("turma_relatorio") or analise["turma_detectada"]
        linhas.append({"nome": linha["nome"], "dados": linha["dados"], "aluno_id": None,
                       "criar_em_turma_id": corr.get("turma_id"),
                       "criar_em_turma_nome": relatorio if corr.get("turma_nova") else None})
    return linhas


def test_sem_a_turma_da_sala_a_previa_diz_a_turma_que_sera_criada(cliente, db, escola_completa):
    """A escola tem "1º Ano B" e não tem a 1ºA: a criança do "1 ANO A" nasce numa
    "1ºA" nova — nunca na "1º Ano B"."""
    eid = escola_completa["escola"].id
    _turma(db, eid, "1º Ano B", "1º Ano")
    analise = _analise(cliente, eid, _uma("1 ANO A", "Crianca Ficticia Umbelina", "u-1a"))
    corr = analise["linhas"][0]["correspondencia"]
    assert corr["status"] == "nao_encontrado"
    assert _turma_da(corr) == (None, None, "1ºA"), corr
    _confirmar(cliente, eid, analise, _corpo_da_tela(analise))
    assert _turmas_do_aluno(db, eid, "Crianca Ficticia Umbelina") == ["1ºA"]


def test_com_a_turma_da_sala_a_previa_diz_a_turma_cadastrada(cliente, db, escola_completa):
    eid, turma = escola_completa["escola"].id, escola_completa["turma"]
    analise = _analise(cliente, eid, _uma("3 ANO A TARDE ANUAL", "Crianca Ficticia Nova",
                                          "u-3a"))
    corr = analise["linhas"][0]["correspondencia"]
    assert corr["status"] == "nao_encontrado"
    assert _turma_da(corr) == (turma.id, "3º Ano A", None), corr
    _confirmar(cliente, eid, analise, _corpo_da_tela(analise))
    assert _turmas_do_aluno(db, eid, "Crianca Ficticia Nova") == ["3º Ano A"]


def test_so_a_fase_na_escola_nao_e_a_turma_da_crianca_do_1_ano(cliente, db, escola_completa):
    """A "1ª Fase A" (Educação Infantil) não é a turma de quem vem no "1 ANO A": a
    prévia diz a 1ºA nova, e o corpo montado com ela cria lá."""
    eid = escola_completa["escola"].id
    _turma(db, eid, "1ª Fase A", "1ª Fase")
    analise = _analise(cliente, eid, _uma("1 ANO A", "Crianca Ficticia Primeiro Ano", "u-1"))
    corr = analise["linhas"][0]["correspondencia"]
    assert _turma_da(corr) == (None, None, "1ºA"), corr
    _confirmar(cliente, eid, analise, _corpo_da_tela(analise))
    assert _turmas_do_aluno(db, eid, "Crianca Ficticia Primeiro Ano") == ["1ºA"]


def test_sem_turma_no_relatorio_e_fora_da_criacao_os_campos_vem_nulos(
        cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    sem_turma = _analise(cliente, eid, _uma(None, "Crianca Ficticia Sem Turma", "u-s"))
    corr = sem_turma["linhas"][0]["correspondencia"]
    assert corr["status"] == "nao_encontrado"
    assert _turma_da(corr) == (None, None, None), corr
    vinculo = _analise(cliente, eid, _uma("3º Ano A", "Ana Beatriz Souza", "u-ana"))
    assert _turma_da(vinculo["linhas"][0]["correspondencia"]) == (None, None, None)


@pytest.mark.skipif(not TIPOS_TS.exists(), reason="sem o front no checkout")
def test_o_tipo_do_front_declara_a_turma_da_previa():
    corpo = re.search(r"export interface Correspondencia \{(.*?)\n\}",
                      TIPOS_TS.read_text(encoding="utf-8"), re.S)
    assert corpo
    campos = set(re.findall(r"^\s*(\w+)\??:", corpo.group(1), re.M))
    assert set(CAMPOS_TURMA) <= campos, campos
