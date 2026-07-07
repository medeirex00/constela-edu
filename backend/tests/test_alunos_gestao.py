"""Gestão de alunos por turma: editar, arquivar/reativar, transferir, excluir
(lógico e em massa) e EXCLUSÃO PERMANENTE (remove o aluno e todos os vínculos).
"""
from sqlalchemy import func, select

from app.models import (
    Aluno,
    Leitura,
    LogAuditoria,
    Matricula,
    Nota,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
)


def _base(escola_id: int) -> str:
    return f"/api/v1/escolas/{escola_id}"


def _popular_dados(cliente, escola_id: int, aluno) -> None:
    """Importa Matific + Elefante para o aluno — cria snapshots, leitura e nota."""
    cliente.post(f"{_base(escola_id)}/importacoes/confirmar", json={
        "plataforma": "matific", "formato": "resumo", "tipo": "texto",
        "linhas": [{"nome": aluno.nome,
                    "dados": {"atividades": 40, "pontuacao_media": 3.5, "estrelas": 100},
                    "aluno_id": aluno.id}]})
    cliente.post(f"{_base(escola_id)}/importacoes/confirmar", json={
        "plataforma": "elefante", "formato": "leituras", "tipo": "texto",
        "linhas": [{"nome": aluno.nome,
                    "dados": {"livro": "O Gato e a Lua", "nivel": "AA"},
                    "aluno_id": aluno.id}]})


# --- Editar -----------------------------------------------------------------

def test_editar_aluno(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    r = cliente.patch(f"{_base(escola_id)}/alunos/{ana.id}",
                      json={"nome": "Ana Beatriz S. Corrigida", "numero_chamada": 7})
    assert r.status_code == 200, r.text
    assert r.json()["nome"] == "Ana Beatriz S. Corrigida"
    db.refresh(ana)
    assert ana.numero_chamada == 7


# --- Arquivar / reativar (soft) + contagem da turma -------------------------

def test_arquivar_remove_da_contagem_e_reativar_restaura(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    turma = escola_completa["turma"]
    ana = escola_completa["alunos"][0]

    def total_turma() -> int:
        turmas = cliente.get(f"{_base(escola_id)}/turmas").json()
        return next(t["total_alunos"] for t in turmas if t["id"] == turma.id)

    assert total_turma() == 3
    r = cliente.post(f"{_base(escola_id)}/alunos/acoes",
                     json={"aluno_ids": [ana.id], "acao": "arquivar"})
    assert r.status_code == 200, r.text
    db.refresh(ana)
    assert ana.status == "arquivado"
    assert total_turma() == 2  # sumiu da contagem sem recarregar

    # Some da listagem padrão, mas aparece com incluir_inativos
    ativos = cliente.get(f"{_base(escola_id)}/turmas/{turma.id}/alunos").json()
    assert ana.id not in [a["id"] for a in ativos]
    todos = cliente.get(f"{_base(escola_id)}/turmas/{turma.id}/alunos?incluir_inativos=true").json()
    assert ana.id in [a["id"] for a in todos]

    cliente.post(f"{_base(escola_id)}/alunos/acoes",
                 json={"aluno_ids": [ana.id], "acao": "reativar"})
    db.refresh(ana)
    assert ana.status == "ativo"
    assert total_turma() == 3


def test_excluir_logico_em_massa(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    ids = [a.id for a in escola_completa["alunos"][:2]]
    r = cliente.post(f"{_base(escola_id)}/alunos/acoes",
                     json={"aluno_ids": ids, "acao": "excluir"})
    assert r.status_code == 200, r.text
    assert r.json()["afetados"] == 2
    for aluno in escola_completa["alunos"][:2]:
        db.refresh(aluno)
        assert aluno.status == "excluido"


# --- Transferir de turma ----------------------------------------------------

def test_transferir_de_turma_em_massa(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    origem = escola_completa["turma"]
    destino = Turma(escola_id=escola_id, nome="4º Ano B", ano_escolar="4º Ano", ano_letivo=2026)
    db.add(destino)
    db.commit()
    ids = [a.id for a in escola_completa["alunos"][:2]]

    r = cliente.post(f"{_base(escola_id)}/alunos/acoes",
                     json={"aluno_ids": ids, "acao": "transferir", "turma_id": destino.id})
    assert r.status_code == 200, r.text
    db.expire_all()
    for aid in ids:
        matricula = db.execute(
            select(Matricula).where(Matricula.aluno_id == aid, Matricula.ano_letivo == 2026)
        ).scalar_one()
        assert matricula.turma_id == destino.id
    # contagens: origem perde 2, destino ganha 2
    turmas = {t["id"]: t["total_alunos"] for t in cliente.get(f"{_base(escola_id)}/turmas").json()}
    assert turmas[origem.id] == 1
    assert turmas[destino.id] == 2


def test_transferir_exige_turma_destino(cliente, escola_completa):
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    r = cliente.post(f"{_base(escola_id)}/alunos/acoes",
                     json={"aluno_ids": [ana.id], "acao": "transferir"})
    assert r.status_code == 400


# --- Exclusão PERMANENTE (cascata) ------------------------------------------

def test_exclusao_permanente_remove_todos_os_vinculos(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    ana, joao = escola_completa["alunos"][0], escola_completa["alunos"][1]
    ana_id, ana_nome = ana.id, ana.nome
    _popular_dados(cliente, escola_id, ana)
    _popular_dados(cliente, escola_id, joao)

    # Pré-condição: Ana tem vínculos em todas as tabelas.
    def conta(modelo, aluno_id):
        return db.execute(select(func.count()).select_from(modelo)
                          .where(modelo.aluno_id == aluno_id)).scalar_one()
    assert conta(Matricula, ana.id) == 1
    assert conta(SnapshotMatific, ana.id) >= 1
    assert conta(SnapshotElefante, ana.id) >= 1
    assert conta(Leitura, ana.id) >= 1
    assert conta(Nota, ana.id) == 1

    r = cliente.post(f"{_base(escola_id)}/alunos/excluir-permanente",
                     json={"aluno_ids": [ana.id], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text
    assert r.json()["afetados"] == 1

    db.expire_all()  # descarta o cache da sessão de teste (a API usou outra)
    # Ana e TODOS os vínculos sumiram; nenhum órfão.
    assert db.get(Aluno, ana_id) is None
    for modelo in (Matricula, SnapshotMatific, SnapshotElefante, Leitura, Nota):
        assert conta(modelo, ana_id) == 0, modelo.__name__

    # João permanece intacto.
    assert db.get(Aluno, joao.id) is not None
    assert conta(SnapshotMatific, joao.id) >= 1

    # Auditoria preservada (§17).
    log = db.execute(select(LogAuditoria)
                     .where(LogAuditoria.acao == "aluno.excluido_permanente")
                     .order_by(LogAuditoria.id.desc())).scalars().first()
    assert log is not None
    assert log.detalhes.get("nome") == ana_nome


def test_exclusao_permanente_exige_confirmacao(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    r = cliente.post(f"{_base(escola_id)}/alunos/excluir-permanente",
                     json={"aluno_ids": [ana.id], "confirmacao": "sim"})
    assert r.status_code == 400
    assert db.get(Aluno, ana.id) is not None  # nada foi apagado


# --- Listagem: busca e ordenação --------------------------------------------

def test_listar_alunos_da_turma_busca_e_ordena(cliente, escola_completa):
    escola_id = escola_completa["escola"].id
    turma = escola_completa["turma"]

    tudo = cliente.get(f"{_base(escola_id)}/turmas/{turma.id}/alunos?ordenar=nome").json()
    nomes = [a["nome"] for a in tudo]
    assert nomes == sorted(nomes)  # ordem alfabética
    assert all("created_at" in a for a in tudo)

    busca = cliente.get(f"{_base(escola_id)}/turmas/{turma.id}/alunos?busca=jo%C3%A3o").json()
    assert len(busca) == 1
    assert "João" in busca[0]["nome"]
