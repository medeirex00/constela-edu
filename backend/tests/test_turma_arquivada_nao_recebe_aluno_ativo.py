"""D17 (T24) pelo outro lado — turma arquivada não RECEBE aluno ativo.

A trava do D17 (``test_turma_arquivar_com_alunos_ativos``) só valia no momento
de arquivar. A 2ª revisão de integração (contas-acesso, prova 2) mostrou o mesmo
estado — aluno ativo matriculado no ano letivo ativo em turma arquivada —
voltando por três caminhos, todos com 200/201 e sem aviso:

  (a) "Transferir de turma" PARA uma turma arquivada;
  (b) reativar alunos cuja matrícula do ano está numa turma arquivada;
  (c) cadastrar aluno novo numa turma arquivada.

Agora os três respondem 409 com o motivo do D17 e nada é gravado; transferir e
cadastrar em turma ativa seguem 200/201, e reativar depois de transferir para
uma turma ativa passa.

A 3ª revisão de integração achou mais portas para o mesmo estado, agora
também 409 com o MESMO texto (``services.turma_arquivada``):

  (d) "Corrigir turmas duplicadas" com a canônica ARQUIVADA (contas-turmas-push,
      prova 2);
  (e) o /resolver da fila de Revisões de identidade com ``criar_em_turma_id`` de
      turma arquivada (identidade-backup, provas 1c e 2A).

Dados 100% fictícios (fixture ``escola_completa``)."""
from sqlalchemy import func, select

from app.models import Aluno, LogAuditoria, Matricula, RevisaoIdentidade, Turma
from app.routers import academico
from app.services import turma_arquivada

API = "/api/v1"


def _ativos_na_turma(db, turma_id, ano=2026) -> int:
    """A invariante do D17: alunos ATIVOS matriculados na turma no ano ativo+."""
    db.expire_all()
    return db.execute(
        select(func.count(func.distinct(Matricula.aluno_id))).select_from(Matricula)
        .join(Aluno, Aluno.id == Matricula.aluno_id)
        .where(Matricula.turma_id == turma_id, Matricula.ano_letivo >= ano,
               Aluno.status == "ativo")).scalar_one()


def _auditoria(db, acao: str) -> int:
    return db.execute(select(func.count()).select_from(LogAuditoria)
                      .where(LogAuditoria.acao == acao)).scalar_one()


def _nova_turma(cliente, eid, nome, *, arquivada: bool) -> int:
    t = cliente.post(f"{API}/escolas/{eid}/turmas", json={
        "nome": nome, "ano_escolar": "3º Ano", "ano_letivo": 2026})
    assert t.status_code == 201, t.text
    tid = t.json()["id"]
    if arquivada:
        r = cliente.put(f"{API}/escolas/{eid}/turmas/{tid}", json={"status": "arquivada"})
        assert r.status_code == 200, r.text            # vazia: arquiva
    return tid


def _acoes(cliente, eid, **corpo):
    return cliente.post(f"{API}/escolas/{eid}/alunos/acoes", json=corpo)


def _assert_mensagem_d17(detalhe: str) -> None:
    assert turma_arquivada.NAO_RECEBE in detalhe
    assert "está arquivada" in detalhe or "turma arquivada" in detalhe


# --- (a) transferir -----------------------------------------------------------

def test_a_transferir_para_turma_arquivada_e_recusado(cliente, db, escola_completa):
    eid, origem = escola_completa["escola"].id, escola_completa["turma"].id
    ids = [a.id for a in escola_completa["alunos"]]
    destino = _nova_turma(cliente, eid, "3º Ano Z", arquivada=True)

    r = _acoes(cliente, eid, acao="transferir", aluno_ids=ids, turma_id=destino)

    assert r.status_code == 409, r.text
    detalhe = r.json()["detail"]
    _assert_mensagem_d17(detalhe)
    assert "“3º Ano Z” está arquivada" in detalhe
    assert "Escolha uma turma ativa" in detalhe
    assert _ativos_na_turma(db, destino) == 0          # prova 2a invertida
    assert _ativos_na_turma(db, origem) == 3           # nada saiu da origem
    assert _auditoria(db, "aluno.transferido") == 0


def test_a_controle_transferir_para_turma_ativa_continua(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    ids = [a.id for a in escola_completa["alunos"]]
    destino = _nova_turma(cliente, eid, "3º Ano B", arquivada=False)
    r = _acoes(cliente, eid, acao="transferir", aluno_ids=ids, turma_id=destino)
    assert r.status_code == 200, r.text
    assert _ativos_na_turma(db, destino) == 3


# --- (b) reativar -------------------------------------------------------------

def _arquivar_alunos_e_turma(cliente, db, escola_completa):
    eid, turma = escola_completa["escola"].id, escola_completa["turma"]
    ids = [a.id for a in escola_completa["alunos"]]
    assert _acoes(cliente, eid, acao="arquivar", aluno_ids=ids).status_code == 200
    r = cliente.put(f"{API}/escolas/{eid}/turmas/{turma.id}", json={"status": "arquivada"})
    assert r.status_code == 200, r.text            # 0 ativos: o D17 libera
    return eid, turma.id, ids


def test_b_reativar_alunos_de_turma_arquivada_e_recusado(cliente, db, escola_completa):
    eid, tid, ids = _arquivar_alunos_e_turma(cliente, db, escola_completa)

    r = _acoes(cliente, eid, acao="reativar", aluno_ids=ids)

    assert r.status_code == 409, r.text
    detalhe = r.json()["detail"]
    _assert_mensagem_d17(detalhe)
    assert "3 aluno(s) selecionado(s) não pode(m) ser reativado(s)" in detalhe
    assert "ano letivo 2026" in detalhe and "“3º Ano A”" in detalhe
    assert "Transferir de turma" in detalhe            # a saída indicada
    db.expire_all()
    assert db.get(Turma, tid).status == "arquivada"
    assert {db.get(Aluno, i).status for i in ids} == {"arquivado"}
    assert _ativos_na_turma(db, tid) == 0              # prova 2b invertida
    assert _auditoria(db, "aluno.reativar") == 0


def test_b_pedido_misto_e_recusado_inteiro(cliente, db, escola_completa):
    """Um aluno numa turma ativa e outro numa arquivada: o pedido todo é 409 —
    nada muda pela metade."""
    eid, tid, ids = _arquivar_alunos_e_turma(cliente, db, escola_completa)
    ativa = _nova_turma(cliente, eid, "3º Ano B", arquivada=False)
    assert _acoes(cliente, eid, acao="transferir", aluno_ids=[ids[0]],
                  turma_id=ativa).status_code == 200

    r = _acoes(cliente, eid, acao="reativar", aluno_ids=ids)

    assert r.status_code == 409, r.text
    assert "2 aluno(s) selecionado(s)" in r.json()["detail"]
    db.expire_all()
    assert {db.get(Aluno, i).status for i in ids} == {"arquivado"}


def test_b_reativar_depois_de_transferir_para_turma_ativa_passa(cliente, db,
                                                              escola_completa):
    """A saída que a mensagem indica funciona: transferir (mesmo arquivados) e
    reativar."""
    eid, tid, ids = _arquivar_alunos_e_turma(cliente, db, escola_completa)
    ativa = _nova_turma(cliente, eid, "3º Ano B", arquivada=False)
    assert _acoes(cliente, eid, acao="transferir", aluno_ids=ids,
                  turma_id=ativa).status_code == 200

    r = _acoes(cliente, eid, acao="reativar", aluno_ids=ids)

    assert r.status_code == 200, r.text
    assert _ativos_na_turma(db, ativa) == 3
    assert _ativos_na_turma(db, tid) == 0


def test_b_controle_reativar_em_turma_ativa_continua(cliente, db, escola_completa):
    eid, turma = escola_completa["escola"].id, escola_completa["turma"]
    ids = [a.id for a in escola_completa["alunos"]]
    assert _acoes(cliente, eid, acao="arquivar", aluno_ids=ids).status_code == 200
    r = _acoes(cliente, eid, acao="reativar", aluno_ids=ids)
    assert r.status_code == 200, r.text
    assert _ativos_na_turma(db, turma.id) == 3


def test_b_matricula_de_ano_anterior_em_turma_arquivada_nao_prende(cliente, db,
                                                                  escola_completa):
    """Só a matrícula do ano letivo ATIVO conta: a turma de 2025 arquivada é
    histórico e não impede reativar quem hoje está numa turma ativa."""
    eid, turma = escola_completa["escola"].id, escola_completa["turma"]
    ids = [a.id for a in escola_completa["alunos"]]
    antiga = Turma(escola_id=eid, nome="2º Ano A", ano_escolar="2º Ano", ano_letivo=2025,
                   status="arquivada")
    db.add(antiga)
    db.flush()
    for i in ids:
        db.add(Matricula(escola_id=eid, aluno_id=i, turma_id=antiga.id, ano_letivo=2025))
    db.commit()
    assert _acoes(cliente, eid, acao="arquivar", aluno_ids=ids).status_code == 200
    r = _acoes(cliente, eid, acao="reativar", aluno_ids=ids)
    assert r.status_code == 200, r.text
    assert _ativos_na_turma(db, turma.id) == 3


# --- (c) cadastrar ------------------------------------------------------------

def test_c_cadastrar_aluno_em_turma_arquivada_e_recusado(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    destino = _nova_turma(cliente, eid, "3º Ano Y", arquivada=True)
    antes = db.execute(select(func.count()).select_from(Aluno)).scalar_one()

    r = cliente.post(f"{API}/escolas/{eid}/alunos",
                     json={"nome": "Crianca Ficticia Nova", "turma_id": destino})

    assert r.status_code == 409, r.text
    _assert_mensagem_d17(r.json()["detail"])
    assert "“3º Ano Y” está arquivada" in r.json()["detail"]
    assert _ativos_na_turma(db, destino) == 0          # prova 2c invertida
    assert db.execute(select(func.count()).select_from(Aluno)).scalar_one() == antes
    assert _auditoria(db, "aluno.criado") == 0
    assert _auditoria(db, "aluno.criacao_recusada") == 0


def test_c_controle_cadastrar_em_turma_ativa_continua(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    destino = _nova_turma(cliente, eid, "3º Ano B", arquivada=False)
    r = cliente.post(f"{API}/escolas/{eid}/alunos",
                     json={"nome": "Crianca Ficticia Nova", "turma_id": destino})
    assert r.status_code == 201, r.text
    assert _ativos_na_turma(db, destino) == 1


# --- concorrência com o arquivamento -----------------------------------------

def test_transferir_e_reativar_tomam_a_trava_do_arquivamento_antes_de_ler(
        cliente, db, escola_completa, monkeypatch):
    """No PG, arquivar toma a trava da escola antes de contar os ativos. Para a
    turma não ser arquivada entre a leitura do status e a gravação, transferir e
    reativar tomam a MESMA trava antes de ler (no SQLite ela é no-op: aqui se
    prova a ordem)."""
    eventos: list[str] = []
    trava_real = academico.bloquear_escola_para_importacao
    turma_real = academico._turma_da_escola

    def _trava(sessao, escola_id):
        eventos.append("trava")
        return trava_real(sessao, escola_id)

    def _turma(sessao, escola_id, turma_id):
        eventos.append("le_turma")
        return turma_real(sessao, escola_id, turma_id)

    monkeypatch.setattr(academico, "bloquear_escola_para_importacao", _trava)
    # A recusa do "Reativar" mora em services.turma_arquivada (as portas de
    # academico e importacoes usam o mesmo texto) e toma a trava por lá.
    monkeypatch.setattr(turma_arquivada, "bloquear_escola_para_importacao", _trava)
    monkeypatch.setattr(academico, "_turma_da_escola", _turma)
    eid = escola_completa["escola"].id
    ids = [a.id for a in escola_completa["alunos"]]
    destino = _nova_turma(cliente, eid, "3º Ano B", arquivada=False)

    eventos.clear()
    assert _acoes(cliente, eid, acao="transferir", aluno_ids=ids,
                  turma_id=destino).status_code == 200
    assert eventos[:2] == ["trava", "le_turma"]

    assert _acoes(cliente, eid, acao="arquivar", aluno_ids=ids).status_code == 200
    eventos.clear()
    assert _acoes(cliente, eid, acao="reativar", aluno_ids=ids).status_code == 200
    assert eventos == ["trava"]


# --- (d) corrigir turmas duplicadas -------------------------------------------

def _consolidar(cliente, eid, canonica, duplicadas):
    return cliente.post(f"{API}/escolas/{eid}/turmas/duplicadas/corrigir",
                        json=[{"canonica_id": canonica, "duplicada_ids": duplicadas}])


def test_d_consolidar_em_canonica_arquivada_e_recusado(cliente, db, escola_completa):
    """Prova 2 (contas-turmas-push) invertida: a canônica arquivada não recebe os
    alunos ativos das duplicadas — 409 e nada se move nem se apaga."""
    eid, com_alunos = escola_completa["escola"].id, escola_completa["turma"].id
    canonica = _nova_turma(cliente, eid, "3ºA", arquivada=True)

    r = _consolidar(cliente, eid, canonica, [com_alunos])

    assert r.status_code == 409, r.text
    detalhe = r.json()["detail"]
    _assert_mensagem_d17(detalhe)
    assert "“3ºA” está arquivada" in detalhe
    db.expire_all()
    assert db.get(Turma, com_alunos) is not None       # a duplicada continua
    assert _ativos_na_turma(db, com_alunos) == 3       # com os 3 ativos
    assert _ativos_na_turma(db, canonica) == 0         # a arquivada continua vazia
    assert db.get(Turma, canonica).status == "arquivada"
    assert _auditoria(db, "turmas.consolidadas") == 0


def test_d_pedido_com_um_grupo_recusado_nao_consolida_nenhum(cliente, db,
                                                            escola_completa):
    """Dois grupos, o 2º com canônica arquivada: 409 ANTES de mover qualquer
    matrícula — o 1º grupo (válido) também não é consolidado."""
    eid, com_alunos = escola_completa["escola"].id, escola_completa["turma"].id
    ativa = _nova_turma(cliente, eid, "3º Ano A (manhã)", arquivada=False)
    vazia = _nova_turma(cliente, eid, "4º Ano B", arquivada=False)
    arquivada = _nova_turma(cliente, eid, "4ºB", arquivada=True)

    r = cliente.post(f"{API}/escolas/{eid}/turmas/duplicadas/corrigir", json=[
        {"canonica_id": ativa, "duplicada_ids": [com_alunos]},
        {"canonica_id": arquivada, "duplicada_ids": [vazia]}])

    assert r.status_code == 409, r.text
    db.expire_all()
    assert db.get(Turma, com_alunos) is not None
    assert db.get(Turma, vazia) is not None
    assert _ativos_na_turma(db, com_alunos) == 3
    assert _ativos_na_turma(db, ativa) == 0
    assert _auditoria(db, "turmas.consolidadas") == 0


def test_d_controle_consolidar_em_canonica_ativa_continua(cliente, db, escola_completa):
    eid, com_alunos = escola_completa["escola"].id, escola_completa["turma"].id
    canonica = _nova_turma(cliente, eid, "3ºA", arquivada=False)

    r = _consolidar(cliente, eid, canonica, [com_alunos])

    assert r.status_code == 200, r.text
    assert r.json()["alunos_movidos"] == 3
    db.expire_all()
    assert db.get(Turma, com_alunos) is None
    assert _ativos_na_turma(db, canonica) == 3
    assert _auditoria(db, "turmas.consolidadas") == 1


def test_d_canonica_de_outra_escola_continua_400(cliente, db, escola_completa):
    """A recusa do D17 só olha a canônica DA escola: a inválida segue com o 400
    de sempre (``turmas_dedup.consolidar``)."""
    eid, com_alunos = escola_completa["escola"].id, escola_completa["turma"].id
    r = _consolidar(cliente, eid, 999_999, [com_alunos])
    assert r.status_code == 400, r.text
    assert "canônica inválida" in r.json()["detail"]


def test_d_consolidar_toma_a_trava_antes_de_ler_a_canonica(cliente, db, escola_completa,
                                                          monkeypatch):
    """A canônica não é arquivada entre a leitura do status e a consolidação: a
    rota toma a trava da escola (a mesma do arquivamento) ANTES de ler as turmas
    (no SQLite ela é no-op: aqui se prova a ordem)."""
    eid, com_alunos = escola_completa["escola"].id, escola_completa["turma"].id
    canonica = _nova_turma(cliente, eid, "3ºA", arquivada=False)
    eventos: list[str] = []
    trava_real = academico.bloquear_escola_para_importacao
    exigir_real = turma_arquivada.exigir_turma_ativa

    def _trava(sessao, escola_id):
        eventos.append("trava")
        return trava_real(sessao, escola_id)

    def _exigir(turma):
        eventos.append("le_canonica")
        return exigir_real(turma)

    monkeypatch.setattr(academico, "bloquear_escola_para_importacao", _trava)
    monkeypatch.setattr(turma_arquivada, "exigir_turma_ativa", _exigir)

    assert _consolidar(cliente, eid, canonica, [com_alunos]).status_code == 200
    assert eventos[:2] == ["trava", "le_canonica"]


# --- (e) fila de Revisões de identidade: /resolver com criar_em_turma_id -----

def _pendencia(db, eid, nome="Crianca Ficticia Da Fila", conta="u-d17-ficticia"):
    rev = RevisaoIdentidade(
        escola_id=eid, chave=f"matific|id:{conta}|resumo||",
        chave_identidade=f"matific|id:{conta}", plataforma="matific", formato="resumo",
        id_externo=conta, nome_recebido=nome, motivo="sem_candidato", candidatos=[],
        linhas=[], contexto={}, origem="sincronizacao", status="pendente")
    db.add(rev)
    db.commit()
    return rev.id


def _resolver(cliente, eid, rid, **corpo):
    return cliente.post(f"{API}/escolas/{eid}/importacoes/revisoes/{rid}/resolver",
                        json=corpo)


def test_e_resolver_criar_em_turma_arquivada_e_recusado(cliente, db, escola_completa):
    """Prova 1c (identidade-backup) invertida: 409, a pendência continua pendente,
    nenhuma ficha, matrícula ou auditoria ``aluno.criado`` nova."""
    eid = escola_completa["escola"].id
    tid = _nova_turma(cliente, eid, "3º Ano Z", arquivada=True)
    rid = _pendencia(db, eid)
    fichas_antes = db.execute(select(func.count()).select_from(Aluno)).scalar_one()
    matriculas_antes = db.execute(select(func.count()).select_from(Matricula)).scalar_one()

    r = _resolver(cliente, eid, rid, criar_em_turma_id=tid)

    assert r.status_code == 409, r.text
    detalhe = r.json()["detail"]
    _assert_mensagem_d17(detalhe)
    assert "“3º Ano Z” está arquivada" in detalhe
    db.expire_all()
    assert db.get(RevisaoIdentidade, rid).status == "pendente"
    assert db.execute(select(func.count()).select_from(Aluno)).scalar_one() == fichas_antes
    assert (db.execute(select(func.count()).select_from(Matricula)).scalar_one()
            == matriculas_antes)
    assert _ativos_na_turma(db, tid) == 0
    assert _auditoria(db, "aluno.criado") == 0
    assert _auditoria(db, "identidade.revisao_resolvida") == 0


def test_e_fila_nao_desfaz_a_rede_de_seguranca_da_turma_arquivada(cliente, db,
                                                                 escola_completa):
    """Prova 2A (identidade-backup) invertida: o /confirmar manda para a fila
    (motivo ``turma_arquivada``) a linha cuja turma escolhida está arquivada; o
    /resolver dessa pendência na MESMA turma é 409 — não cria a ficha que a rede
    de segurança recusou. Escolher uma turma ativa resolve."""
    from app.routers.importacoes import _confirmar_sem_commit
    from app.schemas.importacao import ImportacaoConfirm, LinhaConfirmacao
    from tests.sync_integridade_comum import fichas, pendentes, turma

    escola = escola_completa["escola"]
    arquivada = turma(db, escola.id, "5º Ano Z", "5º Ano", status="arquivada")
    db.commit()
    arquivada_id = arquivada.id
    antes = fichas(db, escola.id)
    corpo = ImportacaoConfirm(plataforma="matific", formato="resumo", tipo="texto",
                              recalcular=False, linhas=[LinhaConfirmacao(
                                  nome="GABI FICTICIA DA FILA", criar_em_turma_id=arquivada_id,
                                  dados={"estrelas": 3, "atividades": 1})])
    _confirmar_sem_commit(dados=corpo, escola_id=escola.id,
                          usuario=escola_completa["admin"], db=db)
    db.commit()
    [rev] = pendentes(db, escola.id)
    assert rev.motivo == "turma_arquivada"
    rid = rev.id

    r = _resolver(cliente, escola.id, rid, criar_em_turma_id=arquivada_id)

    assert r.status_code == 409, r.text
    _assert_mensagem_d17(r.json()["detail"])
    db.expire_all()
    assert fichas(db, escola.id) == antes
    assert db.get(RevisaoIdentidade, rid).status == "pendente"
    assert _ativos_na_turma(db, arquivada_id) == 0

    # A saída: a mesma pendência numa turma ATIVA cria a ficha ali.
    ativa = _nova_turma(cliente, escola.id, "5º Ano A", arquivada=False)
    r = _resolver(cliente, escola.id, rid, criar_em_turma_id=ativa)
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(RevisaoIdentidade, rid).status == "resolvida"
    assert _ativos_na_turma(db, ativa) == 1


def test_e_controle_resolver_criar_em_turma_ativa_continua(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    tid = _nova_turma(cliente, eid, "3º Ano B", arquivada=False)
    rid = _pendencia(db, eid)

    r = _resolver(cliente, eid, rid, criar_em_turma_id=tid)

    assert r.status_code == 200, r.text
    novo = r.json()["aluno_id"]
    db.expire_all()
    assert db.get(Aluno, novo).status == "ativo"
    assert db.get(RevisaoIdentidade, rid).status == "resolvida"
    assert _ativos_na_turma(db, tid) == 1
    assert _auditoria(db, "aluno.criado") == 1


def test_e_resolver_criar_em_turma_ativa_de_outro_ano_letivo_e_recusado(cliente, db,
                                                                       escola_completa):
    """A lacuna geral que este teste FIXAVA (turma ATIVA de outro ano letivo aceita
    no /resolver, gravando a matrícula de 2026 numa turma de 2025) foi fechada nas
    portas juntas: cadastrar, transferir e consolidar já davam 409, e o /resolver
    era a última. Agora também é 409 (``turma_arquivada.exigir_destino_do_ano_ativo``),
    a pendência continua pendente e nenhuma ficha, matrícula ou auditoria nasce."""
    eid = escola_completa["escola"].id
    r = cliente.post(f"{API}/escolas/{eid}/turmas", json={
        "nome": "3º Ano Antigo", "ano_escolar": "3º Ano", "ano_letivo": 2025})
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    rid = _pendencia(db, eid, nome="Outra Crianca Ficticia", conta="u-d17-b")
    fichas_antes = db.execute(select(func.count()).select_from(Aluno)).scalar_one()
    matriculas_antes = db.execute(select(func.count()).select_from(Matricula)).scalar_one()

    r = _resolver(cliente, eid, rid, criar_em_turma_id=tid)

    assert r.status_code == 409, r.text
    detalhe = r.json()["detail"]
    assert "“3º Ano Antigo” é do ano letivo 2025" in detalhe
    assert "ano letivo ativo (2026)" in detalhe and "Nada foi gravado" in detalhe
    db.expire_all()
    assert db.get(RevisaoIdentidade, rid).status == "pendente"
    assert db.execute(select(func.count()).select_from(Aluno)).scalar_one() == fichas_antes
    assert (db.execute(select(func.count()).select_from(Matricula)).scalar_one()
            == matriculas_antes)
    assert db.execute(select(func.count()).select_from(Matricula)
                      .where(Matricula.turma_id == tid)).scalar_one() == 0
    assert db.get(Turma, tid).ano_letivo == 2025
    assert _auditoria(db, "aluno.criado") == 0
    assert _auditoria(db, "identidade.revisao_resolvida") == 0


# --- a trava original continua -----------------------------------------------

def test_controle_d17_recusa_arquivar_com_ativos(cliente, db, escola_completa):
    eid, turma = escola_completa["escola"].id, escola_completa["turma"]
    r = cliente.put(f"{API}/escolas/{eid}/turmas/{turma.id}", json={"status": "arquivada"})
    assert r.status_code == 409, r.text
