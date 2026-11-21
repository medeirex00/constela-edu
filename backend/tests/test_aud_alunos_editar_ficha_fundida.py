"""“Editar dados” (PATCH /alunos/{id}) × fusão que apaga a ficha no meio.

As ações em massa já tomavam a trava da escola antes de ler e davam 409 quando a
ficha sumia; a edição individual ficou de fora. Ela lia a ficha sem a trava e não
tratava ``StaleDataError``: se outro gestor fundia a ficha entre a leitura e o
commit, o UPDATE batia em 0 linhas e a resposta era 500 "Erro interno".

Agora a edição toma a mesma trava ANTES de ler (no PostgreSQL ela espera a fusão
terminar e então não acha mais a ficha: 404) e, se a ficha sumir mesmo assim entre
a leitura e a gravação (no SQLite a trava não existe), responde 409 dizendo o que
houve, sem gravar nada.

Achado ALUNOS-5 da auditoria. Dados fictícios.
"""
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models import Aluno, Usuario
from app.routers import academico
from app.schemas.comum import FusaoAlunos
from tests.test_transferir_ficha_fundida_no_meio import _cena, _fusao_na_hora_da_trava


def _fundir(sessao, c, escola_id):
    outra = Session(bind=sessao.get_bind())
    try:
        academico.fundir_alunos(
            dados=FusaoAlunos(manter_id=c["oficial"], remover_id=c["stub"],
                              confirmacao="FUNDIR"),
            escola_id=escola_id, usuario=outra.get(Usuario, c["admin"]), db=outra)
    finally:
        outra.close()


def _editar(cliente, c, aluno_id, corpo):
    # Sem relançar a exceção do servidor: o que se mede é o que o gestor recebe.
    http = TestClient(app, raise_server_exceptions=False)
    http.headers.update(cliente.headers)
    return http.patch(f"/api/v1/escolas/{c['escola']}/alunos/{aluno_id}", json=corpo)


def test_fusao_entre_a_leitura_e_a_gravacao_da_409_e_nada_muda(db, cliente,
                                                               escola_completa,
                                                               monkeypatch):
    c = _cena(db, escola_completa)
    real = academico._aluno_da_escola
    feito: list[str] = []

    def lido_e_fundido(sessao, escola_id, aluno_id):
        aluno = real(sessao, escola_id, aluno_id)
        if not feito:
            feito.append("fusao")
            _fundir(sessao, c, escola_id)
        return aluno

    monkeypatch.setattr(academico, "_aluno_da_escola", lido_e_fundido)
    r = _editar(cliente, c, c["stub"], {"numero_chamada": 12})

    assert feito == ["fusao"]
    assert r.status_code == 409, f"{r.status_code} {r.text[:300]}"
    detalhe = r.json()["detail"]
    assert "fundida" in detalhe and "Nada foi alterado" in detalhe, detalhe
    db.expire_all()
    assert db.get(Aluno, c["stub"]) is None                      # a fusão valeu
    assert db.get(Aluno, c["oficial"]).numero_chamada is None    # e nada foi gravado


def test_a_edicao_pede_a_trava_da_escola_antes_de_ler(db, cliente, escola_completa,
                                                      monkeypatch):
    """A fusão que pegou a trava primeiro (como no PostgreSQL): a edição lê depois
    dela e vê que a ficha não existe mais — 404, sem 500."""
    c = _cena(db, escola_completa)
    momentos = _fusao_na_hora_da_trava(monkeypatch, c)
    r = _editar(cliente, c, c["stub"], {"numero_chamada": 12})
    assert momentos == ["fusao"], "a edição não pediu a trava da escola"
    assert r.status_code == 404, f"{r.status_code} {r.text[:300]}"
    db.expire_all()
    assert db.get(Aluno, c["stub"]) is None


def test_sem_fusao_a_edicao_segue_como_antes(db, cliente, escola_completa):
    c = _cena(db, escola_completa)
    r = _editar(cliente, c, c["stub"], {"numero_chamada": 12, "nome": "  Zefa Q. Lima "})
    assert r.status_code == 200, r.text
    assert r.json()["nome"] == "Zefa Q. Lima"
    db.expire_all()
    assert db.get(Aluno, c["stub"]).numero_chamada == 12
