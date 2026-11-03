"""D19 — excluir turma JUNTO com os alunos (exclusão física) é do Admin Global.

``com_alunos=true`` com aluno matriculado apaga em definitivo a ficha e todos
os dados de quem só está na turma (e desvincula quem está em outra). Para o
admin e o coordenador da escola: 403 com o caminho que eles têm, ANTES de
qualquer DELETE. Para o Admin Global: tudo num único commit, com auditoria das
contagens (sem nome) e o resumo do que saiu na resposta. Dados 100% fictícios.
"""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import settings
from app.core.security import hash_senha
from app.main import app
from app.models import (
    Aluno,
    EventoAluno,
    Importacao,
    Leitura,
    Livro,
    LogAuditoria,
    Matricula,
    Nota,
    SnapshotMatific,
    Turma,
    Usuario,
)


@pytest.fixture(autouse=True)
def pastas(tmp_path, monkeypatch):
    """A exclusão física apaga, no commit, as cópias em /exports e os originais
    de relatório individual: aponta as pastas para o tmp do teste."""
    uploads, exports = tmp_path / "uploads", tmp_path / "exports"
    (uploads / "elefante").mkdir(parents=True)
    exports.mkdir()
    monkeypatch.setattr(settings, "UPLOADS_DIR", uploads)
    monkeypatch.setattr(settings, "EXPORTS_DIR", exports)
    return {"uploads": uploads, "exports": exports}


def _url(escola_id: int) -> str:
    return f"/api/v1/escolas/{escola_id}/turmas"


def _contar(db, modelo, *condicoes) -> int:
    return db.execute(select(func.count()).select_from(modelo).where(*condicoes)).scalar_one()


def _acoes(db, *acoes: str) -> list[LogAuditoria]:
    return list(db.execute(select(LogAuditoria).where(
        LogAuditoria.acao.in_(acoes))).scalars())


def _cliente_coordenador(db, escola_id: int) -> TestClient:
    db.add(Usuario(escola_id=escola_id, nome="Coordenadora Ficticia",
                   email="coord.ficticia@teste.local", senha_hash=hash_senha("s3nh4"),
                   cargo="coordenador"))
    db.commit()
    cliente = TestClient(app)
    r = cliente.post("/api/v1/auth/login",
                     data={"username": "coord.ficticia@teste.local", "password": "s3nh4"})
    assert r.status_code == 200, r.text
    cliente.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return cliente


def _semear_dados(db, escola_completa) -> dict:
    """2 leituras, 1 nota, 1 retrato Matific e 1 evento por aluno da turma."""
    escola, admin = escola_completa["escola"], escola_completa["admin"]
    livros = [Livro(escola_id=escola.id, titulo=f"Livro Ficticio {i}", nivel_codigo="D")
              for i in range(2)]
    imp = Importacao(escola_id=escola.id, usuario_id=admin.id, plataforma="matific",
                     tipo="texto")
    db.add_all([*livros, imp])
    db.flush()
    for n, aluno in enumerate(escola_completa["alunos"]):
        for livro in livros:
            db.add(Leitura(escola_id=escola.id, aluno_id=aluno.id, livro_id=livro.id))
        db.add(Nota(escola_id=escola.id, aluno_id=aluno.id, ano_letivo=2026))
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id,
                               importacao_id=imp.id, estrelas=5))
        db.add(EventoAluno(escola_id=escola.id, aluno_id=aluno.id, plataforma="elefante",
                           tipo_evento="leitura", ocorrido_em=datetime(2026, 10, 1, 10),
                           chave_natural=f"evento-ficticio-{n}"))
    db.commit()
    return {"leituras": 6, "notas": 3, "snapshots_matific": 3, "eventos": 3}


def _intacto(db, escola_completa, leituras: int = 0) -> None:
    turma_id = escola_completa["turma"].id
    ids = [a.id for a in escola_completa["alunos"]]
    db.expire_all()
    assert _contar(db, Turma, Turma.id == turma_id) == 1
    assert _contar(db, Aluno, Aluno.id.in_(ids)) == 3
    assert _contar(db, Matricula, Matricula.turma_id == turma_id) == 3
    assert _contar(db, Leitura, Leitura.aluno_id.in_(ids)) == leituras
    assert _acoes(db, "turma.excluida", "turma.exclusao_com_alunos",
                  "aluno.excluido_permanente", "turma.alunos_desvinculados") == []


# --- quem não é Admin Global: 403 antes de qualquer DELETE --------------------

def test_admin_da_escola_nao_exclui_turma_com_alunos(cliente, db, escola_completa):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    _semear_dados(db, escola_completa)

    r = cliente.delete(f"{_url(escola.id)}/{turma.id}?com_alunos=true")

    assert r.status_code == 403, r.text
    detalhe = r.json()["detail"]
    assert "exclusivo do Admin Global" in detalhe
    assert "“3º Ano A” tem 3 aluno(s) matriculado(s)" in detalhe
    assert "transfira os alunos" in detalhe            # o caminho que ele tem
    _intacto(db, escola_completa, leituras=6)


def test_coordenador_nao_exclui_turma_com_alunos(db, escola_completa):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    coord = _cliente_coordenador(db, escola.id)

    r = coord.delete(f"{_url(escola.id)}/{turma.id}?com_alunos=true")

    assert r.status_code == 403, r.text
    assert "exclusivo do Admin Global" in r.json()["detail"]
    _intacto(db, escola_completa)


def test_exclusao_em_massa_com_alunos_recusada_inteira(cliente, db, escola_completa):
    """Na massa, a recusa vale para o pedido todo: nem a turma vazia sai (o
    'excluir só as turmas' continua disponível para ela)."""
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    vazia = cliente.post(_url(escola.id), json={
        "nome": "3º Ano B", "ano_escolar": "3º Ano", "ano_letivo": 2026}).json()

    r = cliente.post(f"{_url(escola.id)}/excluir",
                     json={"turma_ids": [turma.id, vazia["id"]], "com_alunos": True})

    assert r.status_code == 403, r.text
    assert "As 2 turmas selecionadas têm 3 aluno(s)" in r.json()["detail"]
    db.expire_all()
    assert db.get(Turma, vazia["id"]) is not None
    _intacto(db, escola_completa)

    # o caminho sem apagar alunos segue igual: só a vazia sai, a outra fica
    r = cliente.post(f"{_url(escola.id)}/excluir",
                     json={"turma_ids": [turma.id, vazia["id"]], "com_alunos": False})
    assert r.status_code == 200, r.text
    assert r.json()["excluidas"] == 1 and r.json()["bloqueadas"] == 1
    assert "exclusivo do Admin Global" in r.json()["mensagem"]
    assert "use ‘excluir com os alunos’" not in r.json()["mensagem"]


def test_desvincular_quem_esta_em_outra_turma_tambem_exige_admin_global(
        cliente, db, escola_completa):
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    antiga = Turma(escola_id=escola.id, nome="2º Ano A", ano_escolar="2º Ano",
                   ano_letivo=2025)
    db.add(antiga)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=aluno.id, turma_id=antiga.id,
                     ano_letivo=2025))
    db.commit()

    r = cliente.delete(f"{_url(escola.id)}/{antiga.id}?com_alunos=true")

    assert r.status_code == 403, r.text
    db.expire_all()
    assert _contar(db, Matricula, Matricula.turma_id == antiga.id) == 1


def test_com_alunos_numa_turma_vazia_e_a_exclusao_simples(cliente, db, escola_completa):
    """Sem matrícula nenhuma não há aluno a apagar: o pedido não é recusado."""
    escola = escola_completa["escola"]
    vazia = cliente.post(_url(escola.id), json={
        "nome": "5º Ano D", "ano_escolar": "5º Ano", "ano_letivo": 2026}).json()

    r = cliente.delete(f"{_url(escola.id)}/{vazia['id']}?com_alunos=true")

    assert r.status_code == 200, r.text
    assert r.json()["excluidas"] == 1
    assert r.json()["alunos_excluidos"] == 0
    assert r.json()["dados_removidos"] == {}


def test_409_sem_com_alunos_nao_oferece_o_caminho_destrutivo(cliente, escola_completa):
    escola, turma = escola_completa["escola"], escola_completa["turma"]

    r = cliente.delete(f"{_url(escola.id)}/{turma.id}")

    assert r.status_code == 409
    detalhe = r.json()["detail"]
    assert "3 aluno(s) vinculado(s)" in detalhe
    assert "ou exclua a turma junto com os alunos" not in detalhe
    assert "exclusivo do Admin Global" in detalhe


def test_409_para_o_admin_global_mantem_o_caminho_destrutivo(cliente_global, escola_completa):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    r = cliente_global.delete(f"{_url(escola.id)}/{turma.id}")
    assert r.status_code == 409
    assert "ou exclua a turma junto com os alunos" in r.json()["detail"]


# --- Admin Global: transação única, auditoria com contagens ------------------

def test_admin_global_exclui_com_contagens_na_resposta_e_na_auditoria(
        cliente_global, db, escola_completa):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    turma_id = turma.id
    nomes = [a.nome for a in escola_completa["alunos"]]
    ids = [a.id for a in escola_completa["alunos"]]
    esperado = _semear_dados(db, escola_completa)
    global_id = db.execute(select(Usuario.id).where(Usuario.is_global.is_(True))).scalar_one()

    r = cliente_global.delete(f"{_url(escola.id)}/{turma_id}?com_alunos=true")

    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["excluidas"] == 1 and corpo["alunos_excluidos"] == 3
    dados = corpo["dados_removidos"]
    for chave, valor in esperado.items():
        assert dados[chave] == valor, (chave, dados)
    assert dados["matriculas"] == 3
    assert dados["snapshots_elefante"] == 0 and dados["perfis_quest"] == 0
    # nada é apagado em silêncio: a mensagem diz o que saiu
    assert "3 aluno(s) e todos os dados" in corpo["mensagem"]
    assert "6 leitura(s)" in corpo["mensagem"] and "3 nota(s)" in corpo["mensagem"]

    db.expire_all()
    assert _contar(db, Turma, Turma.id == turma_id) == 0
    assert _contar(db, Aluno, Aluno.id.in_(ids)) == 0
    assert _contar(db, Leitura, Leitura.aluno_id.in_(ids)) == 0
    assert _contar(db, Nota, Nota.aluno_id.in_(ids)) == 0
    assert _contar(db, SnapshotMatific, SnapshotMatific.aluno_id.in_(ids)) == 0
    assert _contar(db, EventoAluno, EventoAluno.aluno_id.in_(ids)) == 0

    (resumo,) = _acoes(db, "turma.exclusao_com_alunos")
    assert resumo.usuario_id == global_id
    assert resumo.escola_id == escola.id
    assert resumo.entidade == "turma" and resumo.entidade_id == turma_id
    assert resumo.detalhes["turmas"] == [turma_id]
    assert resumo.detalhes["alunos_excluidos"] == 3
    for chave, valor in esperado.items():
        assert resumo.detalhes["dados_removidos"][chave] == valor
    # LGPD: o resumo só leva ids e contagens
    assert not any(nome.split()[0] in str(resumo.detalhes) for nome in nomes)
    assert len(_acoes(db, "aluno.excluido_permanente")) == 3
    assert len(_acoes(db, "turma.excluida")) == 1


def test_admin_global_desvincula_e_audita_as_matriculas(cliente_global, db, escola_completa):
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    antiga = Turma(escola_id=escola.id, nome="2º Ano A", ano_escolar="2º Ano",
                   ano_letivo=2025)
    db.add(antiga)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=aluno.id, turma_id=antiga.id,
                     ano_letivo=2025))
    db.commit()

    r = cliente_global.delete(f"{_url(escola.id)}/{antiga.id}?com_alunos=true")

    assert r.status_code == 200, r.text
    assert r.json()["alunos_excluidos"] == 0 and r.json()["alunos_desvinculados"] == 1
    assert r.json()["dados_removidos"] == {"matriculas_desvinculadas": 1}
    (resumo,) = _acoes(db, "turma.exclusao_com_alunos")
    assert resumo.detalhes["alunos_desvinculados"] == 1
    assert resumo.detalhes["dados_removidos"] == {"matriculas_desvinculadas": 1}
    db.expire_all()
    assert db.get(Aluno, aluno.id) is not None


def test_falha_no_meio_da_exclusao_desfaz_tudo(cliente_global, db, escola_completa,
                                               monkeypatch, pastas):
    """Transação única: uma falha DEPOIS dos DELETEs (leituras, notas,
    matrículas e alunos já emitidos) desfaz tudo — banco e arquivos."""
    from app.services import exclusao_aluno

    escola_id, turma_id = escola_completa["escola"].id, escola_completa["turma"].id
    _semear_dados(db, escola_completa)
    copia = pastas["exports"] / "ranking_ficticio.pdf"
    copia.write_bytes(b"%PDF copia ficticia")

    def _quebra(*_a, **_k):
        raise RuntimeError("falha simulada no meio da exclusão")

    monkeypatch.setattr(exclusao_aluno, "conversas_ia_que_citam", _quebra)

    r = cliente_global.delete(f"{_url(escola_id)}/{turma_id}?com_alunos=true")
    assert r.status_code == 500        # o middleware converte a exceção em 500

    _intacto(db, escola_completa, leituras=6)
    assert _contar(db, Nota, Nota.escola_id == escola_id) == 3
    assert copia.exists()          # os arquivos só saem no commit, que não houve


def test_resumo_da_exclusao_fica_fora_do_expurgo_automatico():
    """O resumo é a prova (sem nome) do que a exclusão física levou: entra no
    mesmo grupo preservado do ``aluno.excluido_permanente``."""
    from app.services.audit import ACOES_PRESERVADAS

    assert "turma.exclusao_com_alunos" in ACOES_PRESERVADAS
    assert "aluno.excluido_permanente" in ACOES_PRESERVADAS
