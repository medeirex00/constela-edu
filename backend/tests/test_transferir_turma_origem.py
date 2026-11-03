"""“Transferir de turma” a partir do painel de uma turma (``turma_origem_id``).

3ª revisão de integração (contas-turmas-push, provas 1 e 3): o painel de uma
turma de OUTRO ano letivo (ex.: 2025, com a escola em 2026) lista os alunos pela
matrícula de 2025, mas “Transferir de turma” fazia UPDATE só na matrícula do ANO
ATIVO — a da turma atual da criança, em outra sala. As crianças trocavam de
turma atual em silêncio, quem só tinha a matrícula de 2025 ganhava uma de 2026,
a turma antiga continuava com as matrículas (e sem poder ser excluída) e a
auditoria não guardava a origem. E a tela de Turmas indicava esse caminho para
esvaziar a turma antes de excluí-la.

Agora o painel manda ``turma_origem_id``:
  * origem de outro ano letivo → 409 orientando a arquivar; nada muda;
  * origem do ano ativo → move SÓ a matrícula do ano ativo que está nela, sem
    criar matrícula nova; aluno que não está nela → 409 para o pedido inteiro;
  * a auditoria ``aluno.transferido`` guarda a origem.
Sem ``turma_origem_id`` (o perfil do aluno) o comportamento é o de sempre.

E o 409 do DELETE de uma turma de ano ANTERIOR com alunos passa a orientar
“arquive-a” (e não “Mova ou remova”). Dados 100% fictícios (``escola_completa``)."""
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.security import hash_senha
from app.main import app
from app.models import Aluno, LogAuditoria, Matricula, Usuario
from app.routers import academico

API = "/api/v1"


def _turma(cliente, eid, nome, ano_escolar, ano_letivo):
    r = cliente.post(f"{API}/escolas/{eid}/turmas", json={
        "nome": nome, "ano_escolar": ano_escolar, "ano_letivo": ano_letivo})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _matriculas(db, *, turma_id, ano=None, aluno_id=None) -> int:
    db.expire_all()
    q = select(func.count()).select_from(Matricula).where(Matricula.turma_id == turma_id)
    if ano is not None:
        q = q.where(Matricula.ano_letivo == ano)
    if aluno_id is not None:
        q = q.where(Matricula.aluno_id == aluno_id)
    return db.execute(q).scalar_one()


def _auditorias(db, acao="aluno.transferido") -> list[LogAuditoria]:
    db.expire_all()
    return list(db.execute(select(LogAuditoria).where(LogAuditoria.acao == acao))
                .scalars())


def _transferir(cliente, eid, ids, destino, origem=None):
    corpo = {"acao": "transferir", "aluno_ids": ids, "turma_id": destino}
    if origem is not None:
        corpo["turma_origem_id"] = origem
    return cliente.post(f"{API}/escolas/{eid}/alunos/acoes", json=corpo)


def _com_turma_de_2025(cliente, db, escola_completa):
    """As 3 crianças de “3º Ano A” (2026) com o histórico de 2025 em “2º Ano A”."""
    eid = escola_completa["escola"].id
    ids = sorted(a.id for a in escola_completa["alunos"])
    antiga = _turma(cliente, eid, "2º Ano A", "2º Ano", 2025)
    for aid in ids:
        db.add(Matricula(escola_id=eid, aluno_id=aid, turma_id=antiga, ano_letivo=2025))
    db.commit()
    return eid, ids, antiga


def _coordenacao(db, eid) -> TestClient:
    db.add(Usuario(escola_id=eid, nome="Coord Ficticia", email="coord@teste.local",
                   senha_hash=hash_senha("s3nh4"), cargo="coordenador"))
    db.commit()
    c = TestClient(app)
    r = c.post(f"{API}/auth/login",
               data={"username": "coord@teste.local", "password": "s3nh4"})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


# --- origem de OUTRO ano letivo: 409, nada muda --------------------------------

def test_origem_de_outro_ano_letivo_e_recusada_e_nada_muda(cliente, db, escola_completa):
    """Prova 1 (contas-turmas-push) invertida."""
    turma_2026 = escola_completa["turma"].id
    eid, ids, antiga = _com_turma_de_2025(cliente, db, escola_completa)
    destino = _turma(cliente, eid, "3º Ano B", "3º Ano", 2026)
    # O painel da turma de 2025 lista os 3 (pela matrícula de 2025).
    r = cliente.get(f"{API}/escolas/{eid}/turmas/{antiga}/alunos")
    assert sorted(a["id"] for a in r.json()) == ids

    r = _transferir(cliente, eid, ids, destino, origem=antiga)

    assert r.status_code == 409, r.text
    detalhe = r.json()["detail"]
    assert "“2º Ano A” é do ano letivo 2025" in detalhe
    assert "move a matrícula do ano letivo ativo (2026)" in detalhe
    assert "Nada foi transferido" in detalhe
    assert "arquive-a" in detalhe and "histórico fica preservado" in detalhe
    # A turma ATUAL das crianças não mudou; a de 2025 continua com o histórico.
    assert _matriculas(db, turma_id=turma_2026, ano=2026) == 3
    assert _matriculas(db, turma_id=destino) == 0
    assert _matriculas(db, turma_id=antiga, ano=2025) == 3
    assert _auditorias(db) == []


def test_coordenacao_na_turma_de_2025_nao_cria_matricula_de_2026(db, escola_completa):
    """Prova 3 (contas-turmas-push) invertida: transferir os 4 da turma de 2025
    para a turma REAL deles em 2026 não cria matrícula de 2026 para o 4º (que só
    tinha a de 2025). A saída indicada — arquivar a turma de 2025 — funciona."""
    eid = escola_completa["escola"].id
    turma_2026 = escola_completa["turma"].id
    ids = sorted(a.id for a in escola_completa["alunos"])
    c = _coordenacao(db, eid)
    antiga = _turma(c, eid, "2º Ano A", "2º Ano", 2025)
    quarto = Aluno(escola_id=eid, nome="Lucas Teste Ficticio")
    db.add(quarto)
    db.flush()
    for aid in ids + [quarto.id]:
        db.add(Matricula(escola_id=eid, aluno_id=aid, turma_id=antiga, ano_letivo=2025))
    db.commit()
    qid = quarto.id

    r = _transferir(c, eid, sorted(ids + [qid]), turma_2026, origem=antiga)

    assert r.status_code == 409, r.text
    assert _matriculas(db, turma_id=turma_2026, ano=2026, aluno_id=qid) == 0
    assert _matriculas(db, turma_id=antiga) == 4
    # O DELETE (não global) orienta arquivar — e arquivar a turma de 2025 passa.
    r = c.delete(f"{API}/escolas/{eid}/turmas/{antiga}")
    assert r.status_code == 409, r.text
    assert "arquive-a" in r.json()["detail"]
    assert "Mova ou remova" not in r.json()["detail"]
    r = c.put(f"{API}/escolas/{eid}/turmas/{antiga}", json={"status": "arquivada"})
    assert r.status_code == 200, r.text


# --- origem do ano ativo: move só a matrícula que está nela ----------------------

def test_origem_do_ano_ativo_move_so_a_matricula_dela_e_audita_a_origem(
        cliente, db, escola_completa):
    """Controle da prova 1: na turma do ano ativo a transferência esvazia a turma
    (que pode ser excluída) e a auditoria guarda de onde as crianças saíram."""
    eid, origem = escola_completa["escola"].id, escola_completa["turma"].id
    ids = sorted(a.id for a in escola_completa["alunos"])
    destino = _turma(cliente, eid, "3º Ano B", "3º Ano", 2026)

    r = _transferir(cliente, eid, ids, destino, origem=origem)

    assert r.status_code == 200, r.text
    assert r.json()["mensagem"] == "3 aluno(s) transferido(s) de 3º Ano A para 3º Ano B."
    assert _matriculas(db, turma_id=origem) == 0
    assert _matriculas(db, turma_id=destino, ano=2026) == 3
    [log] = _auditorias(db)
    assert log.detalhes["turma_origem_id"] == origem
    assert log.detalhes["turma_origem"] == "3º Ano A"
    assert log.detalhes["turma_id"] == destino
    assert sorted(log.detalhes["alunos"]) == ids
    r = cliente.delete(f"{API}/escolas/{eid}/turmas/{origem}")
    assert r.status_code == 200, r.text


def test_origem_do_ano_ativo_nao_mexe_na_matricula_de_outro_ano(cliente, db,
                                                               escola_completa):
    """Na turma do ano ativo, o histórico de 2025 das mesmas crianças fica onde
    está: só a matrícula do ano ativo que está NA origem se move."""
    turma_2026 = escola_completa["turma"].id
    eid, ids, antiga = _com_turma_de_2025(cliente, db, escola_completa)
    destino = _turma(cliente, eid, "3º Ano B", "3º Ano", 2026)

    r = _transferir(cliente, eid, ids, destino, origem=turma_2026)

    assert r.status_code == 200, r.text
    assert _matriculas(db, turma_id=antiga, ano=2025) == 3
    assert _matriculas(db, turma_id=destino, ano=2026) == 3
    assert _matriculas(db, turma_id=turma_2026) == 0


def test_aluno_fora_da_origem_recusa_o_pedido_inteiro_sem_criar_matricula(
        cliente, db, escola_completa):
    """Lista desatualizada: um aluno selecionado já não está na origem (ou nunca
    teve matrícula no ano ativo). 409 para o pedido inteiro — ninguém se move e
    nenhuma matrícula nasce no destino."""
    eid, origem = escola_completa["escola"].id, escola_completa["turma"].id
    ids = sorted(a.id for a in escola_completa["alunos"])
    sem_matricula = Aluno(escola_id=eid, nome="Bia Ficticia Sem Turma")
    db.add(sem_matricula)
    db.commit()
    sid = sem_matricula.id
    destino = _turma(cliente, eid, "3º Ano B", "3º Ano", 2026)

    r = _transferir(cliente, eid, ids + [sid], destino, origem=origem)

    assert r.status_code == 409, r.text
    detalhe = r.json()["detail"]
    assert "1 aluno(s) selecionado(s) não está(ão) na turma “3º Ano A”" in detalhe
    assert "recarregue a turma" in detalhe
    assert _matriculas(db, turma_id=origem, ano=2026) == 3
    assert _matriculas(db, turma_id=destino) == 0
    assert _auditorias(db) == []


def test_origem_arquivada_do_ano_ativo_e_a_saida_do_d17(cliente, db, escola_completa):
    """A turma ARQUIVADA do ano ativo é uma origem válida: tirar dela quem está lá
    é a saída que o D17 indica antes de reativar (só o DESTINO precisa estar
    ativo)."""
    eid, turma = escola_completa["escola"].id, escola_completa["turma"].id
    ids = sorted(a.id for a in escola_completa["alunos"])
    assert cliente.post(f"{API}/escolas/{eid}/alunos/acoes", json={
        "acao": "arquivar", "aluno_ids": ids}).status_code == 200
    r = cliente.put(f"{API}/escolas/{eid}/turmas/{turma}", json={"status": "arquivada"})
    assert r.status_code == 200, r.text
    destino = _turma(cliente, eid, "3º Ano B", "3º Ano", 2026)

    r = _transferir(cliente, eid, ids, destino, origem=turma)

    assert r.status_code == 200, r.text
    r = cliente.post(f"{API}/escolas/{eid}/alunos/acoes", json={
        "acao": "reativar", "aluno_ids": ids})
    assert r.status_code == 200, r.text
    assert _matriculas(db, turma_id=destino, ano=2026) == 3


def test_origem_de_outra_escola_e_404(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    ids = [a.id for a in escola_completa["alunos"]]
    destino = _turma(cliente, eid, "3º Ano B", "3º Ano", 2026)
    r = _transferir(cliente, eid, ids, destino, origem=999_999)
    assert r.status_code == 404, r.text
    assert _auditorias(db) == []


def test_transferir_toma_a_trava_antes_de_ler_origem_e_destino(cliente, db,
                                                              escola_completa,
                                                              monkeypatch):
    """A trava da escola (a do arquivamento) vem ANTES de ler as duas turmas (no
    SQLite ela é no-op: aqui se prova a ordem)."""
    eid, origem = escola_completa["escola"].id, escola_completa["turma"].id
    ids = [a.id for a in escola_completa["alunos"]]
    destino = _turma(cliente, eid, "3º Ano B", "3º Ano", 2026)
    eventos: list[object] = []
    trava_real = academico.bloquear_escola_para_importacao
    turma_real = academico._turma_da_escola

    def _trava(sessao, escola_id):
        eventos.append("trava")
        return trava_real(sessao, escola_id)

    def _le(sessao, escola_id, turma_id):
        eventos.append(turma_id)
        return turma_real(sessao, escola_id, turma_id)

    monkeypatch.setattr(academico, "bloquear_escola_para_importacao", _trava)
    monkeypatch.setattr(academico, "_turma_da_escola", _le)

    assert _transferir(cliente, eid, ids, destino, origem=origem).status_code == 200
    assert eventos[:3] == ["trava", origem, destino]


# --- sem turma_origem_id: o comportamento de sempre (perfil do aluno) ----------

def test_sem_origem_continua_movendo_a_matricula_do_ano_ativo(cliente, db,
                                                             escola_completa):
    """Outras telas (perfil do aluno) não mandam a origem: move a matrícula do ano
    ativo onde ela estiver e cria uma no destino para quem não tem."""
    eid, turma_2026 = escola_completa["escola"].id, escola_completa["turma"].id
    ids = sorted(a.id for a in escola_completa["alunos"])
    sem_matricula = Aluno(escola_id=eid, nome="Bia Ficticia Sem Turma")
    db.add(sem_matricula)
    db.commit()
    sid = sem_matricula.id
    destino = _turma(cliente, eid, "3º Ano B", "3º Ano", 2026)

    r = _transferir(cliente, eid, ids + [sid], destino)

    assert r.status_code == 200, r.text
    assert r.json()["mensagem"] == "4 aluno(s) transferido(s) para 3º Ano B."
    assert _matriculas(db, turma_id=turma_2026) == 0
    assert _matriculas(db, turma_id=destino, ano=2026) == 4
    [log] = _auditorias(db)
    assert "turma_origem_id" not in log.detalhes


# --- DELETE de turma de ano anterior orienta arquivar --------------------------

def test_delete_de_turma_de_ano_anterior_orienta_arquivar(cliente, db, escola_completa):
    eid, ids, antiga = _com_turma_de_2025(cliente, db, escola_completa)
    r = cliente.delete(f"{API}/escolas/{eid}/turmas/{antiga}")
    assert r.status_code == 409, r.text
    detalhe = r.json()["detail"]
    assert "“2º Ano A” é do ano letivo 2025" in detalhe
    assert "3 aluno(s) vinculado(s)" in detalhe
    assert "não saem por “Transferir de turma”" in detalhe
    assert "arquive-a" in detalhe
    assert "Mova ou remova" not in detalhe
    assert "exclusivo do Admin Global" in detalhe          # admin da escola
    r = cliente.put(f"{API}/escolas/{eid}/turmas/{antiga}", json={"status": "arquivada"})
    assert r.status_code == 200, r.text


def test_delete_de_turma_do_ano_ativo_continua_orientando_mover(cliente, db,
                                                               escola_completa):
    eid, turma = escola_completa["escola"].id, escola_completa["turma"].id
    r = cliente.delete(f"{API}/escolas/{eid}/turmas/{turma}")
    assert r.status_code == 409, r.text
    assert "Mova ou remova os alunos" in r.json()["detail"]
