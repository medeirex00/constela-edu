"""Concorrência das importações (achado A1): duas confirmações sobrepostas da
MESMA escola não podem duplicar turmas nem alunos.

Cobre as três camadas da correção:
  * índice único ``uq_turma_escola_ano_nome`` (barreira de banco, cross-DB);
  * ``_inserir_turma`` re-resolvendo a turma existente em vez de estourar 500
    quando o índice barra o INSERT concorrente;
  * ``bloquear_escola_para_importacao`` chamada ANTES de ler o estado nos dois
    endpoints de confirmação (serialização por escola — efetiva no Postgres).

O banco de teste é SQLite de uma conexão só (StaticPool), então a corrida real
de duas transações é reproduzida de forma determinística: comita-se a 1ª e
tenta-se a 2ª, exatamente o que a trava impede em produção.
"""
import io
from datetime import date

import openpyxl
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models import Aluno, Turma
from app.routers import importacoes

CT_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
COLUNAS = ["N.º", "RM", "RA", "Nome", "Data de Nasc.", "Responsável",
           "Endereço", "Bairro", "Telefone", "RG", "CPF", "SUS",
           "SEXO", "RAÇA COR", "BOLSA FAMÍLIA"]


def _aba(ws, turma, turno, professor, sed, alunos):
    ws.append([None, None, None, "PREFEITURA MUNICIPAL DE CARAGUATATUBA"])
    ws.append(["Escola:", None, "EMEF PROFESSOR JORGE PASSOS", None, None,
               None, None, "Lista Piloto:", 2026])
    ws.append([])
    ws.append(["Professor:", None, professor, None, "Ano:", turma,
               f"Turno:       {turno}", None, "N.º da Classe (SED):", sed])
    ws.append([])
    ws.append(COLUNAS)
    for linha in alunos:
        ws.append(linha)


def _planilha() -> bytes:
    wb = openpyxl.Workbook()
    a = wb.active
    a.title = "1º Ano A"
    _aba(a, "1º Ano A", "TARDE", "PAULA", 300396614, [
        [1, 4446, "123.100.026-0", "AGATHA VITORIA MOURA DA SILVA",
         date(2019, 9, 18), "BRENDA", "RUA X, 178", "JARAGUAZINHO",
         "12-98109-4185", "66.4-1", "574.900.168-78", "700 1", "F", "PARDA", "SIM"],
        [2, 4447, "121.721.835-X", "ALICE DE ALMEIDA LEAL",
         date(2019, 5, 2), "MICHELLE", "RUA Y, 918", "JARAGUAZINHO",
         "99753-5290", "", "", "", "F", "BRANCA", "NÃO"],
    ])
    b = wb.create_sheet("1º Ano B")
    _aba(b, "1º ANO B", "TARDE", "MAIARA", 300396635, [
        [1, 4468, "121.521.972-6", "ADRYAN RIBEIRO VALERIANO",
         date(2018, 3, 10), "PRISCILA", "RUA Z, 453", "RIO DO OURO",
         "12 99608-2283", "65.8-X", "569.950.318-81", "700 0", "M", "BRANCA", "SIM"],
    ])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _upload():
    return {"arquivo": ("Lista Piloto 2026.xlsx", _planilha(), CT_XLSX)}


def _conta_turmas(db, escola_id) -> int:
    return db.execute(select(func.count()).select_from(Turma)
                      .where(Turma.escola_id == escola_id)).scalar_one()


def _conta_alunos(db, escola_id) -> int:
    return db.execute(select(func.count()).select_from(Aluno)
                      .where(Aluno.escola_id == escola_id)).scalar_one()


def test_indice_unico_barra_turma_duplicada(db, escola_completa):
    """A barreira de banco: duas turmas com (escola, ano, nome) idênticos não
    coexistem — é o que impedia a corrida de virar duplicata permanente."""
    escola_id = escola_completa["escola"].id
    db.add(Turma(escola_id=escola_id, nome="9º Ano Z", ano_escolar="9º Ano",
                 ano_letivo=2026))
    db.commit()
    db.add(Turma(escola_id=escola_id, nome="9º Ano Z", ano_escolar="9º Ano",
                 ano_letivo=2026))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_inserir_turma_reresolve_na_colisao(db, escola_completa):
    """_inserir_turma devolve a turma existente (sem 500) quando o índice barra
    o INSERT — a 2ª importação concorrente reaproveita em vez de duplicar."""
    escola_id = escola_completa["escola"].id
    turma1, criada1 = importacoes._inserir_turma(
        db, escola_id, 2026, "7º Ano Q", "7º Ano")
    db.commit()
    assert criada1 is True

    turma2, criada2 = importacoes._inserir_turma(
        db, escola_id, 2026, "7º Ano Q", "7º Ano")
    assert criada2 is False
    assert turma2.id == turma1.id
    total = db.execute(
        select(func.count()).select_from(Turma)
        .where(Turma.escola_id == escola_id, Turma.nome == "7º Ano Q")
    ).scalar_one()
    assert total == 1


def test_confirmar_trava_escola_antes_de_resolver(cliente, db, escola_completa,
                                                  monkeypatch):
    """/confirmar adquire a trava por escola — e cria a turma do relatório UMA
    vez só (sem a trava, dois envios a criariam duas vezes em produção)."""
    chamadas = []
    real = importacoes.bloquear_escola_para_importacao

    def _spy(sessao, eid):
        chamadas.append(eid)
        return real(sessao, eid)

    monkeypatch.setattr(importacoes, "bloquear_escola_para_importacao", _spy)

    escola_id = escola_completa["escola"].id
    corpo = {
        "plataforma": "elefante", "formato": "resumo", "tipo": "pdf",
        "linhas": [{"nome": "Aluno Único", "dados": {"livros_unicos": 2},
                    "criar_em_turma_nome": "8 ANO C MANHA ANUAL"}],
    }
    r = cliente.post(f"/api/v1/escolas/{escola_id}/importacoes/confirmar", json=corpo)
    assert r.status_code == 200, r.text
    assert chamadas == [escola_id]
    criadas = db.execute(
        select(func.count()).select_from(Turma)
        .where(Turma.escola_id == escola_id,
               func.lower(Turma.nome) == "8 ano c manha anual")).scalar_one()
    assert criadas == 1


def test_confirmar_reenvio_nao_duplica_alunos(cliente, db, escola_completa):
    """Reenvio sobreposto do MESMO /confirmar (double-click/retry de proxy)
    cria os alunos novos UMA vez só: o 2º reaproveita quem já está na turma em
    vez de duplicar — a trava serializa, o re-casamento contra o banco dedup."""
    escola_id = escola_completa["escola"].id
    corpo = {
        "plataforma": "elefante", "formato": "resumo", "tipo": "pdf",
        "linhas": [
            {"nome": "Novo Aluno Alfa", "dados": {"livros_unicos": 3},
             "criar_em_turma_nome": "6 ANO D MANHA ANUAL"},
            {"nome": "Novo Aluno Beta", "dados": {"livros_unicos": 1},
             "criar_em_turma_nome": "6 ANO D MANHA ANUAL"},
        ],
    }
    base = f"/api/v1/escolas/{escola_id}/importacoes/confirmar"
    assert cliente.post(base, json=corpo).status_code == 200
    turmas1, alunos1 = _conta_turmas(db, escola_id), _conta_alunos(db, escola_id)

    assert cliente.post(base, json=corpo).status_code == 200
    assert _conta_turmas(db, escola_id) == turmas1   # turma não duplica
    assert _conta_alunos(db, escola_id) == alunos1   # alunos não duplicam


def test_matriculas_confirmar_trava_e_reimport_idempotente(
        cliente, db, escola_completa, monkeypatch):
    """/matriculas/confirmar adquire a trava e é idempotente: confirmar o MESMO
    arquivo duas vezes não cria turma nem aluno duplicado."""
    chamadas = []
    real = importacoes.bloquear_escola_para_importacao
    monkeypatch.setattr(
        importacoes, "bloquear_escola_para_importacao",
        lambda sessao, eid: chamadas.append(eid) or real(sessao, eid))

    escola_id = escola_completa["escola"].id
    base = f"/api/v1/escolas/{escola_id}/importacoes/matriculas/confirmar"

    r1 = cliente.post(base, files=_upload())
    assert r1.status_code == 200, r1.text
    assert r1.json()["turmas_criadas"] == 2 and r1.json()["alunos_criados"] == 3
    turmas_apos_1, alunos_apos_1 = _conta_turmas(db, escola_id), _conta_alunos(db, escola_id)

    r2 = cliente.post(base, files=_upload())
    assert r2.status_code == 200, r2.text
    assert r2.json()["turmas_criadas"] == 0 and r2.json()["alunos_criados"] == 0

    assert _conta_turmas(db, escola_id) == turmas_apos_1
    assert _conta_alunos(db, escola_id) == alunos_apos_1
    assert chamadas == [escola_id, escola_id]
