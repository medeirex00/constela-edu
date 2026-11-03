"""D17 — arquivar turma com matrícula ativa é recusado (409).

Arquivar só tira a turma dos filtros, não encerra as matrículas: com aluno
ativo dentro, a criança seguia nos rankings/premiações/certificado ligada a uma
turma invisível e a sincronização mandava a ficha para revisão. A regra conta a
matrícula NESTA turma, do ano letivo ativo (ou posterior), de aluno "ativo".
Dados 100% fictícios (fixture ``escola_completa``)."""
from sqlalchemy import select

from app.models import Aluno, LogAuditoria, Matricula, Turma


def _url(escola_id: int) -> str:
    return f"/api/v1/escolas/{escola_id}/turmas"


def _arquivar(cliente, escola_id: int, turma_id: int, **extra):
    return cliente.put(f"{_url(escola_id)}/{turma_id}",
                       json={"status": "arquivada", **extra})


def _acao(cliente, escola_id: int, acao: str, aluno_ids: list[int], turma_id=None):
    corpo = {"acao": acao, "aluno_ids": aluno_ids}
    if turma_id is not None:
        corpo["turma_id"] = turma_id
    r = cliente.post(f"/api/v1/escolas/{escola_id}/alunos/acoes", json=corpo)
    assert r.status_code == 200, r.text
    return r


def _turma(db, escola_id: int, nome: str, ano_letivo: int, ano_escolar="3º Ano") -> Turma:
    t = Turma(escola_id=escola_id, nome=nome, ano_escolar=ano_escolar,
              ano_letivo=ano_letivo)
    db.add(t)
    db.flush()
    return t


def test_arquivar_turma_com_alunos_ativos_e_recusado(cliente, db, escola_completa):
    escola, turma = escola_completa["escola"], escola_completa["turma"]  # 3 ativos

    r = _arquivar(cliente, escola.id, turma.id)

    assert r.status_code == 409, r.text
    detalhe = r.json()["detail"]
    assert "não pode ser arquivada" in detalhe
    assert "3 aluno(s) ativo(s)" in detalhe
    assert "2026" in detalhe                         # o ano letivo ativo
    assert "Transferir de turma" in detalhe          # o que fazer
    db.expire_all()
    assert db.get(Turma, turma.id).status == "ativa"
    # nada foi gravado: nem a turma, nem a auditoria de atualização
    assert db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "turma.atualizada")).scalars().all() == []


def test_admin_global_tambem_nao_arquiva_com_alunos_ativos(cliente_global, db,
                                                          escola_completa):
    """A regra é de integridade, não de permissão: vale para todos os perfis."""
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    r = _arquivar(cliente_global, escola.id, turma.id)
    assert r.status_code == 409, r.text
    assert "3 aluno(s) ativo(s)" in r.json()["detail"]


def test_arquivar_liberado_depois_de_transferir_os_alunos(cliente, db, escola_completa):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    ids = [a.id for a in escola_completa["alunos"]]
    destino = cliente.post(_url(escola.id), json={
        "nome": "3º Ano B", "ano_escolar": "3º Ano", "ano_letivo": 2026}).json()

    _acao(cliente, escola.id, "transferir", ids, turma_id=destino["id"])

    r = _arquivar(cliente, escola.id, turma.id)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "arquivada"
    # o destino, agora com os 3, é que não pode ser arquivado
    r2 = _arquivar(cliente, escola.id, destino["id"])
    assert r2.status_code == 409
    assert "3 aluno(s) ativo(s)" in r2.json()["detail"]


def test_so_alunos_ativos_contam(cliente, db, escola_completa):
    """Transferido (saiu da escola) e arquivado não prendem a turma."""
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    a1, a2, a3 = (a.id for a in escola_completa["alunos"])

    _acao(cliente, escola.id, "marcar_transferido", [a1])
    _acao(cliente, escola.id, "arquivar", [a2])
    r = _arquivar(cliente, escola.id, turma.id)
    assert r.status_code == 409
    assert "1 aluno(s) ativo(s)" in r.json()["detail"]   # só o a3

    _acao(cliente, escola.id, "excluir", [a3])             # exclusão lógica
    r = _arquivar(cliente, escola.id, turma.id)
    assert r.status_code == 200, r.text
    # as matrículas continuam no banco: arquivar não apaga nada
    db.expire_all()
    assert db.query(Matricula).filter(Matricula.turma_id == turma.id).count() == 3


def test_turma_do_ano_anterior_arquiva_mesmo_com_os_alunos_ativos_hoje(
        cliente, db, escola_completa):
    """Virada de ano: as crianças seguem ativas (no 2026), a turma de 2025 só
    guarda histórico — arquivá-la continua livre."""
    escola = escola_completa["escola"]
    antiga = _turma(db, escola.id, "2º Ano A", 2025, ano_escolar="2º Ano")
    for a in escola_completa["alunos"]:
        db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=antiga.id,
                         ano_letivo=2025))
    db.commit()

    r = _arquivar(cliente, escola.id, antiga.id)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "arquivada"


def test_matricula_do_ano_ativo_numa_turma_de_outro_ano_conta(cliente, db,
                                                             escola_completa):
    """Matrícula de 2026 numa turma de 2025: a criança está nela de verdade
    (aparece em /alunos com essa turma). Dado LEGADO, gravado direto no banco:
    "Transferir de turma" aceitava esse destino até a trava do destino
    (``academico._exigir_destino_do_ano_ativo``), que hoje responde 409."""
    escola = escola_completa["escola"]
    antiga = _turma(db, escola.id, "2º Ano A", 2025, ano_escolar="2º Ano")
    db.execute(select(Matricula).where(
        Matricula.aluno_id == escola_completa["alunos"][0].id,
        Matricula.ano_letivo == 2026)).scalar_one().turma_id = antiga.id
    db.commit()

    r = _arquivar(cliente, escola.id, antiga.id)
    assert r.status_code == 409, r.text
    assert "1 aluno(s) ativo(s)" in r.json()["detail"]


def test_matricula_de_ano_posterior_tambem_conta(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    futura = _turma(db, escola.id, "4º Ano A", 2027, ano_escolar="4º Ano")
    db.add(Matricula(escola_id=escola.id, aluno_id=escola_completa["alunos"][0].id,
                     turma_id=futura.id, ano_letivo=2027))
    db.commit()

    r = _arquivar(cliente, escola.id, futura.id)
    assert r.status_code == 409, r.text
    assert "1 aluno(s) ativo(s)" in r.json()["detail"]


def test_turma_ja_arquivada_mantem_o_significado(cliente, db, escola_completa):
    """Turma arquivada ANTES da regra (com alunos ativos dentro) não muda:
    continua arquivada, editável e reativável; só um NOVO arquivamento é
    barrado."""
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    db.get(Turma, turma.id).status = "arquivada"
    db.commit()

    # editar reenviando o mesmo status não é "arquivar": passa
    r = cliente.put(f"{_url(escola.id)}/{turma.id}",
                    json={"status": "arquivada", "observacoes": "Sala antiga."})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "arquivada"
    assert r.json()["observacoes"] == "Sala antiga."
    # os alunos seguem ativos e matriculados (nada foi encerrado)
    db.expire_all()
    assert all(db.get(Aluno, a.id).status == "ativo" for a in escola_completa["alunos"])

    # reativar nunca é barrado
    r = cliente.put(f"{_url(escola.id)}/{turma.id}", json={"status": "ativa"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ativa"

    # arquivar de novo, com os 3 ativos, já cai na regra
    assert _arquivar(cliente, escola.id, turma.id).status_code == 409


def test_turma_vazia_arquiva_como_antes(cliente, escola_completa):
    escola = escola_completa["escola"]
    vazia = cliente.post(_url(escola.id), json={
        "nome": "5º Ano C", "ano_escolar": "5º Ano", "ano_letivo": 2026}).json()
    r = _arquivar(cliente, escola.id, vazia["id"])
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "arquivada"
