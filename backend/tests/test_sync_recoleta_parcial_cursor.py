"""Furo da recoleta semanal: 'parcial' por unidade não reinicia o relógio de quem falhou.

A recoleta completa que termina 'parcial' reinicia o relógio semanal (para um
aluno cujo pedido falha sempre não tornar TODA coleta completa). Mas quem falhou
nela mantinha o cursor ANTIGO pelo merge de ``_salvar_contadores``: com o agregado
da turma parado (o caso medido em 03/10), a coleta incremental seguinte o pulava, e
os livros dele só voltavam na recoleta de 7 dias depois — o comentário do serviço
afirmava o contrário.

Agora, na recoleta completa com unidade que falhou, o cursor fica só com quem
chegou: quem falhou é buscado inteiro já na próxima coleta, que continua
incremental para os demais. Dados FICTÍCIOS, sem rede (conector real do Elefante
com navegador falso).
"""
from __future__ import annotations

from app.sync import service
from tests._sync_nucleo_fakes import NavElefante, aluno_el, credencial, instalar, livro, rodar

CID = 744001
SID_A, SID_B = 9440001, 9440002


def _cursor(db, eid):
    return service._carregar_contadores(db, eid, "elefante")


def test_aluno_que_falhou_na_recoleta_completa_volta_na_proxima_incremental(
        db, escola_completa, monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    a, b, _c = ec["alunos"]
    credencial(db, eid, "elefante")
    nav = NavElefante({CID: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
        aluno_el(SID_A, a.nome, [livro("Livro Ficticio A1")]),
        aluno_el(SID_B, b.nome, [livro("Livro Ficticio B1")])]}})
    instalar(monkeypatch, nav_elefante=nav)

    rodar(db, eid, "elefante")                       # 1ª coleta: cria o cursor
    assert set(_cursor(db, eid)) == {str(SID_A), str(SID_B)}

    # 2ª: recoleta completa (cursor sem marca) em que o pedido de livros de B falha;
    # A leu um livro novo (a coleta aplica dado e termina 'parcial', não 'erro').
    assert service._coleta_completa_devida(db, eid, "elefante")[0] is True
    dados_a = nav.turmas[CID]["alunos"][0]
    dados_a["livros"].append(livro("Livro Ficticio A2", data="2026-09-03T10:00:00"))
    dados_a["total"] = 2
    nav.status_aluno = {SID_B: 500}
    ex, _ = rodar(db, eid, "elefante")
    assert ex.status == "parcial"
    assert service._coleta_completa_devida(db, eid, "elefante")[0] is False  # relógio andou
    assert str(SID_B) not in _cursor(db, eid)        # quem falhou ficou sem cursor
    assert str(SID_A) in _cursor(db, eid)

    # 3ª: incremental, a plataforma volta, e o agregado da turma NÃO mudou para
    # ninguém. B é buscado (não espera 7 dias); A continua pulado pelo cursor.
    nav.status_aluno = {}
    nav.lotes.clear()
    ex, _ = rodar(db, eid, "elefante")
    pedidos = {sid for lote in nav.lotes for sid in lote}
    assert SID_B in pedidos
    assert SID_A not in pedidos
    assert ex.status in ("concluida", "sem_atualizacao")
    assert str(SID_B) in _cursor(db, eid)            # e o cursor dele volta


def test_recoleta_completa_sem_falha_continua_fazendo_merge(db, escola_completa):
    """Sem unidade com falha, nada muda: o merge preserva o resto do cursor."""
    eid = escola_completa["escola"].id
    service._salvar_contadores(db, eid, "elefante", {"1": 3, "2": 4})
    service._salvar_contadores(db, eid, "elefante", {"1": 5})
    assert _cursor(db, eid) == {"1": 5, "2": 4}
    service._salvar_contadores(db, eid, "elefante", {"1": 6}, substituir=True)
    assert _cursor(db, eid) == {"1": 6}
    service._salvar_contadores(db, eid, "elefante", {}, substituir=True)
    assert _cursor(db, eid) == {}
