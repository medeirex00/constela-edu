"""Arquivar, reativar, excluir e marcar como transferido × fusão que apaga uma das
fichas selecionadas.

Revisão final (D3 só corrigiu "transferir"): as outras ações em massa liam os
alunos sem a trava da escola e depois gravavam o status de cada um. Se outro gestor
fundia o stub na ficha oficial (rota real, outra sessão) entre a leitura e o commit,
o UPDATE do status batia em 1 linha onde esperava 2 — ``StaleDataError`` e 500
"Erro interno", sem dizer ao gestor o que houve.

Agora todas tomam a trava ANTES de ler (a fusão toma a mesma: no PostgreSQL ela não
entra mais nesse intervalo) e dão 409 com a ficha que sumiu ("Nada foi arquivado…"),
sem mudar ninguém; e se a ficha sumir mesmo assim entre a leitura e a gravação (no
SQLite a trava não existe), a resposta é o mesmo 409. Dados FICTÍCIOS.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models import Aluno, Usuario
from app.routers import academico
from app.schemas.comum import FusaoAlunos
from tests.test_transferir_ficha_fundida_no_meio import _cena, _fusao_na_hora_da_trava

ACOES = {"arquivar": "Nada foi arquivado", "excluir": "Nada foi excluído",
         "marcar_transferido": "Nada foi marcado como transferido",
         "reativar": "Nada foi reativado"}
# A fusão só junta fichas ATIVAS ("Só é possível fundir alunos ativos"): "Reativar"
# parte de fichas fora de "ativo" e não cruza com ela. Fica no controle e na trava.
COM_FUSAO = ["arquivar", "excluir", "marcar_transferido"]


def _preparar(db, escola_completa, acao):
    c = _cena(db, escola_completa)
    if acao == "reativar":           # reativar parte de fichas fora de "ativo"
        for aid in (c["oficial"], c["stub"]):
            db.get(Aluno, aid).status = "arquivado"
        db.commit()
    c["status_antes"] = db.get(Aluno, c["oficial"]).status
    return c


def _fundir(sessao, c, escola_id):
    outra = Session(bind=sessao.get_bind())
    try:
        academico.fundir_alunos(
            dados=FusaoAlunos(manter_id=c["oficial"], remover_id=c["stub"],
                              confirmacao="FUNDIR"),
            escola_id=escola_id, usuario=outra.get(Usuario, c["admin"]), db=outra)
    finally:
        outra.close()


def _pedir(cliente, c, acao):
    # Sem relançar a exceção do servidor: o que se mede é o que o gestor recebe.
    http = TestClient(app, raise_server_exceptions=False)
    http.headers.update(cliente.headers)
    return http.post(f"/api/v1/escolas/{c['escola']}/alunos/acoes",
                     json={"acao": acao, "aluno_ids": [c["oficial"], c["stub"]]})


def _conferir_409(db, r, c, acao):
    assert r.status_code == 409, f"{acao}: {r.status_code} {r.text[:300]}"
    detalhe = r.json()["detail"]
    assert "fundida" in detalhe and ACOES[acao] in detalhe, detalhe
    db.expire_all()
    assert db.get(Aluno, c["stub"]) is None                     # a fusão valeu
    assert db.get(Aluno, c["oficial"]).status == c["status_antes"]   # ninguém mudou


@pytest.mark.parametrize("acao", COM_FUSAO)
def test_fusao_entre_a_leitura_e_a_gravacao_da_409(db, cliente, escola_completa,
                                                    monkeypatch, acao):
    """A sonda da revisão: a fusão entra logo DEPOIS da leitura dos alunos (o caso
    sem a trava). Antes: 500 (StaleDataError) em arquivar, excluir e marcar como
    transferido."""
    c = _preparar(db, escola_completa, acao)
    real = academico._alunos_selecionados

    def lidos_e_fundidos(sessao, escola_id, aluno_ids):
        alunos = real(sessao, escola_id, aluno_ids)
        _fundir(sessao, c, escola_id)
        return alunos

    monkeypatch.setattr(academico, "_alunos_selecionados", lidos_e_fundidos)
    _conferir_409(db, _pedir(cliente, c, acao), c, acao)


@pytest.mark.parametrize("acao", COM_FUSAO)
def test_fusao_na_hora_da_trava_da_409(db, cliente, escola_completa, monkeypatch, acao):
    """A fusão que pegou a trava primeiro (como no PostgreSQL): a ação lê depois dela
    e vê que a ficha não existe mais. Antes a ação não pedia a trava."""
    c = _preparar(db, escola_completa, acao)
    momentos = _fusao_na_hora_da_trava(monkeypatch, c)
    r = _pedir(cliente, c, acao)
    assert momentos == ["fusao"], "a ação não pediu a trava da escola"
    _conferir_409(db, r, c, acao)


@pytest.mark.parametrize("acao", list(ACOES))
def test_sem_fusao_a_acao_segue_como_antes(db, cliente, escola_completa, acao):
    """Controle: as duas fichas existem — as duas mudam de status."""
    c = _preparar(db, escola_completa, acao)
    r = cliente.post(f"/api/v1/escolas/{c['escola']}/alunos/acoes",
                     json={"acao": acao, "aluno_ids": [c["oficial"], c["stub"]]})
    assert r.status_code == 200, r.text
    assert r.json()["afetados"] == 2
    db.expire_all()
    esperado = {"arquivar": "arquivado", "excluir": "excluido",
                "marcar_transferido": "transferido", "reativar": "ativo"}[acao]
    assert {db.get(Aluno, a).status for a in (c["oficial"], c["stub"])} == {esperado}


def test_reativar_com_ficha_que_nao_existe_mais_da_409(db, cliente, escola_completa):
    """"Reativar" não cruza com a fusão (que só junta fichas ativas), mas a lista
    aberta pode trazer uma ficha que sumiu por outro caminho: o mesmo 409, e a outra
    ficha selecionada continua arquivada."""
    c = _preparar(db, escola_completa, "reativar")
    db.delete(db.get(Aluno, c["stub"]))
    db.commit()
    r = _pedir(cliente, c, "reativar")
    _conferir_409(db, r, c, "reativar")
