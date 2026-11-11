"""Certificado da PLATAFORMA (a arte do Elefante/Matific) com todas as vagas de
navegador ocupadas: o pedido responde 503 ("tente de novo"), e a arte NÃO é trocada
pelo certificado Geral de MÉRITO.

Com o teto de navegadores (DESEMPENHO-4), "sem vaga no prazo" levanta
``NavegadorOcupado``. Na arte, essa exceção caía no mesmo ``except`` de "sem Chromium"
e a emissão virava o Geral, que passa pela guarda de mérito: a criança sem Nota recebia
409/422 com um motivo que não vale para a arte (e, no lote, ficava de fora como
recusada — recusado não é substituído), e a com Nota recebia um certificado de mérito
no lugar da arte pedida. Achado REV-REL-1. O Chromium aqui é FALSO (nenhum navegador
é aberto); dados INVENTADOS.
"""
import sys
from contextlib import contextmanager

import pytest
from sqlalchemy import select

from app.models import LogAuditoria
from app.services import relatorios as svc
from tests.test_aud_rel_pdf_teto_navegadores import _Contador, _playwright_falso
from tests.test_certificados_lote import _aluno, _lote

API = "/api/v1"
PDF_DO_CHROMIUM_FALSO = b"%PDF-1.4 falso"


@pytest.fixture()
def chromium_falso(monkeypatch):
    """Playwright falso (conta os navegadores abertos), espera curta pela vaga e um
    espião no Geral, para saber se a emissão caiu nele."""
    contador = _Contador()
    monkeypatch.setitem(sys.modules, "playwright.sync_api",
                        _playwright_falso(contador, demora=0))
    monkeypatch.setattr(svc, "ESPERA_POR_NAVEGADOR_S", 0.2)
    gerais: list[str] = []
    gerar_certificado = svc.gerar_certificado

    def _geral_espiado(**campos):
        gerais.append(campos["aluno_nome"])
        return gerar_certificado(**campos)

    monkeypatch.setattr(svc, "gerar_certificado", _geral_espiado)
    return {"contador": contador, "gerais": gerais}


@contextmanager
def _vagas_tomadas():
    """Todas as vagas do teto ocupadas (como por outros PDFs em geração)."""
    tomadas = 0
    try:
        while svc._VAGAS_DE_NAVEGADOR.acquire(blocking=False):
            tomadas += 1
        assert tomadas == svc.NAVEGADORES_SIMULTANEOS
        yield
    finally:
        for _ in range(tomadas):
            svc._VAGAS_DE_NAVEGADOR.release()


def _individual(cliente, escola_id, aluno_id, modelo=None):
    params = {"modelo": modelo, "bimestre": 3} if modelo else {}
    return cliente.get(f"{API}/escolas/{escola_id}/certificados/{aluno_id}",
                       params=params)


def _emitidos(db) -> list[int]:
    db.rollback()
    return sorted(db.execute(select(LogAuditoria.entidade_id).where(
        LogAuditoria.acao == "certificado.emitido")).scalars())


def _resumo(r) -> str:
    return f"{r.status_code} {r.headers.get('content-type')} {r.text[:300]!r}"


@pytest.mark.parametrize("com_nota", [False, True], ids=["sem-nota", "com-nota"])
@pytest.mark.parametrize("modelo", ["elefante", "matific"])
def test_arte_sem_vaga_responde_503_e_nao_vira_o_geral(cliente, db, escola_completa,
                                                       chromium_falso, modelo, com_nota):
    escola = escola_completa["escola"]
    aluno = _aluno(db, escola, "CRIANCA FICTICIA DA ARTE", nota=com_nota)
    with _vagas_tomadas():
        r = _individual(cliente, escola.id, aluno.id, modelo)
    assert r.status_code == 503, _resumo(r)
    assert "Tente de novo" in r.json()["detail"], _resumo(r)
    assert chromium_falso["gerais"] == [], "a arte caiu no certificado Geral (mérito)"
    assert chromium_falso["contador"].total == 0
    assert _emitidos(db) == []                     # nada foi entregue, nada auditado


def test_lote_da_arte_sem_vaga_responde_503_sem_recusar_ninguem(cliente, db,
                                                                 escola_completa,
                                                                 chromium_falso):
    """No lote, a falta de vaga é do PEDIDO, não da criança: o lote inteiro volta com
    503, sem item recusado por mérito e sem ninguém trocado pelo Geral."""
    escola = escola_completa["escola"]
    ids = [_aluno(db, escola, "LOTE FICTICIO SEM NOTA", nota=False).id,
           _aluno(db, escola, "LOTE FICTICIO COM NOTA").id]
    with _vagas_tomadas():
        r = _lote(cliente, escola.id, ids, "elefante")
    assert r.status_code == 503, _resumo(r)
    corpo = r.json()
    assert "Tente de novo" in corpo["detail"], _resumo(r)
    assert "itens" not in corpo, _resumo(r)
    assert chromium_falso["gerais"] == [], "a arte caiu no certificado Geral (mérito)"
    assert chromium_falso["contador"].total == 0
    assert _emitidos(db) == []


@pytest.mark.parametrize("com_nota", [False, True], ids=["sem-nota", "com-nota"])
def test_com_vaga_livre_a_arte_continua_saindo(cliente, db, escola_completa,
                                              chromium_falso, com_nota):
    escola = escola_completa["escola"]
    aluno = _aluno(db, escola, "CRIANCA FICTICIA COM VAGA", nota=com_nota)
    r = _individual(cliente, escola.id, aluno.id, "elefante")
    assert r.status_code == 200, _resumo(r)
    assert r.content == PDF_DO_CHROMIUM_FALSO        # a arte, pelo Chromium
    assert chromium_falso["gerais"] == []
    assert chromium_falso["contador"].total == 1
    assert _emitidos(db) == [aluno.id]


def test_geral_sem_vaga_continua_saindo_pela_reserva(cliente, db, escola_completa,
                                                     chromium_falso):
    """O Geral tem reserva com os mesmos dados (fpdf): sem vaga, ele sai por ela — o
    503 é só da arte, que não tem reserva equivalente."""
    escola = escola_completa["escola"]
    aluno = _aluno(db, escola, "CRIANCA FICTICIA DO GERAL")
    with _vagas_tomadas():
        r = _individual(cliente, escola.id, aluno.id)
    assert r.status_code == 200, _resumo(r)
    assert r.content[:5] == b"%PDF-" and r.content != PDF_DO_CHROMIUM_FALSO
    assert chromium_falso["gerais"] == [aluno.nome]
    assert chromium_falso["contador"].total == 0
    assert _emitidos(db) == [aluno.id]
