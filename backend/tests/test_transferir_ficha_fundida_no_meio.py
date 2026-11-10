"""Transferir de turma × fusão que apaga uma das fichas selecionadas.

Revisão de integração (10/11): a transferência lia os alunos selecionados
(``_alunos_selecionados``) ANTES de tomar a trava da escola (4711); a fusão toma a
mesma trava e apaga a ficha absorvida. Se a fusão entrava nesse intervalo, a
transferência seguia com a lista lida antes: a matrícula da ficha absorvida já não
existia, e o "aluno sem matrícula no ano ganha uma na turma de destino" inseria
matrícula de aluno apagado — FK, 500, e nada dizia ao gestor o que aconteceu.

Agora a transferência toma a trava ANTES de ler os alunos e, se alguma ficha
selecionada não existe mais nesta escola, responde 409 com o motivo e não transfere
ninguém (como a lista desatualizada da turma de origem).

O SQLite não tem a trava (no-op): a fusão é posta no ponto exato em que a
transferência pede a trava. No PostgreSQL, a corrida de verdade fica em
``test_transferir_ficha_fundida_no_meio_pg``. Dados FICTÍCIOS.
"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import app
from app.models import Aluno, Matricula, Usuario
from app.routers import academico
from app.schemas.comum import FusaoAlunos
from tests.sync_integridade_comum import aluno, turma


def _cena(db, escola_completa):
    esc, t = escola_completa["escola"], escola_completa["turma"]
    oficial = aluno(db, esc.id, t, "Zefa Quaresma Lima", da_lista_piloto=True)
    stub = aluno(db, esc.id, t, "Zefa Quaresma")
    destino = turma(db, esc.id, "3º Ano B", "3º Ano")
    db.commit()
    return {"escola": esc.id, "origem": t.id, "destino": destino.id, "oficial": oficial.id,
            "stub": stub.id, "admin": escola_completa["admin"].id}


def _fusao_na_hora_da_trava(monkeypatch, c):
    """Outro gestor funde o stub na oficial (pela rota real, em outra sessão) no
    instante em que a transferência pede a trava da escola."""
    real = academico.bloquear_escola_para_importacao
    momentos: list[str] = []

    def trava(sessao, escola_id):
        if not momentos:
            momentos.append("fusao")
            outra = Session(bind=sessao.get_bind())
            try:
                academico.fundir_alunos(
                    dados=FusaoAlunos(manter_id=c["oficial"], remover_id=c["stub"],
                                      confirmacao="FUNDIR"),
                    escola_id=escola_id, usuario=outra.get(Usuario, c["admin"]), db=outra)
            finally:
                outra.close()
        return real(sessao, escola_id)

    monkeypatch.setattr(academico, "bloquear_escola_para_importacao", trava)
    return momentos


def test_fusao_no_meio_da_transferencia_da_409_e_nada_muda(db, cliente, escola_completa,
                                                           monkeypatch):
    c = _cena(db, escola_completa)
    momentos = _fusao_na_hora_da_trava(monkeypatch, c)
    # Sem relançar a exceção do servidor: o que se mede é o que o gestor recebe.
    http = TestClient(app, raise_server_exceptions=False)
    http.headers.update(cliente.headers)

    r = http.post(f"/api/v1/escolas/{c['escola']}/alunos/acoes",
                  json={"acao": "transferir", "aluno_ids": [c["oficial"], c["stub"]],
                        "turma_id": c["destino"]})

    assert momentos == ["fusao"]
    assert r.status_code == 409, f"{r.status_code}: {r.text}"
    detalhe = r.json()["detail"]
    assert "fundida" in detalhe and "Nada foi transferido" in detalhe
    db.expire_all()
    assert db.get(Aluno, c["stub"]) is None                       # a fusão valeu
    assert db.execute(select(Matricula.aluno_id, Matricula.turma_id).where(
        Matricula.aluno_id.in_([c["oficial"], c["stub"]]))).all() == [
        (c["oficial"], c["origem"])]                               # ninguém transferido


def test_sem_fusao_a_transferencia_segue_como_antes(db, cliente, escola_completa):
    """Controle: as duas fichas existem — as duas vão para o destino."""
    c = _cena(db, escola_completa)
    r = cliente.post(f"/api/v1/escolas/{c['escola']}/alunos/acoes",
                     json={"acao": "transferir", "aluno_ids": [c["oficial"], c["stub"]],
                           "turma_id": c["destino"]})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert sorted(db.execute(select(Matricula.aluno_id, Matricula.turma_id).where(
        Matricula.aluno_id.in_([c["oficial"], c["stub"]]))).all()) == [
        (c["oficial"], c["destino"]), (c["stub"], c["destino"])]
