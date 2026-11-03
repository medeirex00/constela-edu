"""A matrícula do ano letivo ativo não entra em turma de OUTRO ano letivo.

Revisão do grupo pequeno (rodada 4): uma matrícula de 2026 numa turma de 2025
continuava contando na escola, porque o cartão da rede e o lado escola do
comparador contam pela matrícula do ano ativo, e sumia das turmas do ano, porque
o resumo da escola lista só as turmas do ano ativo. Cartão menos resumo
entregava à Secretaria os livros, o tempo e a nota dessa criança. O estado era
alcançável pela API: "Transferir de turma" (POST /alunos/acoes) conferia o ano
da turma de ORIGEM, mas não o do DESTINO.

Agora as portas de ``routers.academico`` que põem matrícula numa turma recusam
a turma de outro ano com 409, sem gravar nada:
  * "Transferir de turma", com e sem ``turma_origem_id``;
  * o cadastro manual (POST /alunos);
  * "Corrigir turmas duplicadas" com canônica de ano diferente do das duplicadas;
  * mudar o ano letivo de uma turma que tem matrícula de outro ano.
Os controles provam que o caminho do ano ativo segue igual. Dados 100% fictícios
(fixture ``escola_completa``).

Fechamento (01/11): a última porta era o /resolver da fila de Revisões de
identidade com ``criar_em_turma_id`` (``routers.importacoes``), que criava a ficha
nova com a matrícula de 2026 numa turma ATIVA de 2025. Agora usa a MESMA trava do
destino, que mudou para ``services.turma_arquivada.exigir_destino_do_ano_ativo``
(os dois routers não se importam). E mudar o ano letivo de uma turma toma a trava
da escola antes de contar as matrículas."""
import pytest
from sqlalchemy import func, select

from app.models import Aluno, LogAuditoria, Matricula, Turma

API = "/api/v1"


def _turma(db, escola_id: int, nome: str, ano_letivo: int, ano_escolar="3º Ano") -> int:
    turma = Turma(escola_id=escola_id, nome=nome, ano_escolar=ano_escolar,
                  ano_letivo=ano_letivo)
    db.add(turma)
    db.commit()
    return turma.id


def _matriculas(db) -> list[tuple[int, int, int]]:
    """(aluno, turma, ano) de todas as matrículas: a prova de que nada mudou."""
    db.expire_all()
    return sorted(tuple(linha) for linha in db.execute(
        select(Matricula.aluno_id, Matricula.turma_id, Matricula.ano_letivo)).all())


def _auditorias(db, acao: str) -> int:
    db.expire_all()
    return db.execute(select(func.count()).select_from(LogAuditoria)
                      .where(LogAuditoria.acao == acao)).scalar_one()


def _transferir(cliente, eid, ids, destino, origem=None):
    corpo = {"acao": "transferir", "aluno_ids": ids, "turma_id": destino}
    if origem is not None:
        corpo["turma_origem_id"] = origem
    return cliente.post(f"{API}/escolas/{eid}/alunos/acoes", json=corpo)


# --- "Transferir de turma" ---------------------------------------------------

@pytest.mark.parametrize("com_origem", [False, True])
@pytest.mark.parametrize("ano_destino", [2025, 2027])
def test_transferir_para_turma_de_outro_ano_e_409_e_nada_muda(
        cliente, db, escola_completa, ano_destino, com_origem):
    """A prova do revisor invertida: a criança X não vai para a turma de 2025 (nem
    para uma de 2027), seja pelo perfil do aluno (sem origem), seja pelo painel da
    turma de 2026 (com origem)."""
    eid, turma_2026 = escola_completa["escola"].id, escola_completa["turma"].id
    x = escola_completa["alunos"][0].id
    destino = _turma(db, eid, f"3º Ano A ({ano_destino})", ano_destino)
    antes = _matriculas(db)

    r = _transferir(cliente, eid, [x], destino, origem=turma_2026 if com_origem else None)

    assert r.status_code == 409, r.text
    detalhe = r.json()["detail"]
    assert f"“3º Ano A ({ano_destino})” é do ano letivo {ano_destino}" in detalhe
    assert "ano letivo ativo (2026)" in detalhe
    assert "Nada foi gravado" in detalhe
    assert _matriculas(db) == antes
    assert _auditorias(db, "aluno.transferido") == 0


def test_transferir_aluno_sem_matricula_para_turma_de_outro_ano_nao_cria_matricula(
        cliente, db, escola_completa):
    """Sem origem, quem não tem matrícula no ano ativo ganharia uma NO DESTINO —
    numa turma de 2025. 409 e nenhuma matrícula nasce."""
    eid = escola_completa["escola"].id
    sem_turma = Aluno(escola_id=eid, nome="Bia Ficticia Sem Turma")
    db.add(sem_turma)
    db.commit()
    sid = sem_turma.id
    antiga = _turma(db, eid, "3º Ano A (2025)", 2025)
    antes = _matriculas(db)

    r = _transferir(cliente, eid, [sid], antiga)

    assert r.status_code == 409, r.text
    assert _matriculas(db) == antes
    assert not any(aluno == sid for aluno, _t, _a in _matriculas(db))


def test_admin_global_tambem_recebe_409(cliente_global, db, escola_completa):
    """A trava é de integridade do dado, não de permissão: vale para todos."""
    eid = escola_completa["escola"].id
    antiga = _turma(db, eid, "3º Ano A (2025)", 2025)
    antes = _matriculas(db)

    r = _transferir(cliente_global, eid, [escola_completa["alunos"][0].id], antiga)

    assert r.status_code == 409, r.text
    assert _matriculas(db) == antes


def test_controle_transferir_para_turma_do_ano_ativo_continua(cliente, db,
                                                             escola_completa):
    eid = escola_completa["escola"].id
    x = escola_completa["alunos"][0].id
    destino = _turma(db, eid, "3º Ano B", 2026)

    r = _transferir(cliente, eid, [x], destino)

    assert r.status_code == 200, r.text
    assert (x, destino, 2026) in _matriculas(db)
    assert _auditorias(db, "aluno.transferido") == 1


# --- Cadastro manual ---------------------------------------------------------

def _total_alunos(db) -> int:
    db.expire_all()
    return db.execute(select(func.count()).select_from(Aluno)).scalar_one()


def test_cadastrar_aluno_em_turma_de_outro_ano_e_409_e_nada_grava(cliente, db,
                                                                escola_completa):
    eid = escola_completa["escola"].id
    antiga = _turma(db, eid, "3º Ano A (2025)", 2025)
    alunos_antes, antes = _total_alunos(db), _matriculas(db)

    r = cliente.post(f"{API}/escolas/{eid}/alunos",
                     json={"nome": "Crianca Nova Ficticia", "turma_id": antiga})

    assert r.status_code == 409, r.text
    assert "Nada foi gravado" in r.json()["detail"]
    assert _total_alunos(db) == alunos_antes
    assert _matriculas(db) == antes
    assert _auditorias(db, "aluno.criado") == 0
    assert _auditorias(db, "aluno.criacao_recusada") == 0


def test_controle_cadastrar_na_turma_do_ano_ativo_continua(cliente, db, escola_completa):
    eid, turma_2026 = escola_completa["escola"].id, escola_completa["turma"].id

    r = cliente.post(f"{API}/escolas/{eid}/alunos",
                     json={"nome": "Crianca Nova Ficticia", "turma_id": turma_2026})

    assert r.status_code == 201, r.text
    assert (r.json()["id"], turma_2026, 2026) in _matriculas(db)


# --- "Corrigir turmas duplicadas" ----------------------------------------------

def _consolidar(cliente, eid, canonica, duplicadas):
    return cliente.post(f"{API}/escolas/{eid}/turmas/duplicadas/corrigir",
                        json=[{"canonica_id": canonica, "duplicada_ids": duplicadas}])


def test_consolidar_com_canonica_de_outro_ano_e_409_e_nada_muda(cliente, db,
                                                              escola_completa):
    """Com a canônica de 2025, as 3 matrículas de 2026 da turma de 2026 iriam para
    uma turma de 2025. 409 para o pedido inteiro: nada se move nem se apaga."""
    eid, turma_2026 = escola_completa["escola"].id, escola_completa["turma"].id
    antiga = _turma(db, eid, "3ºA", 2025)
    antes = _matriculas(db)

    r = _consolidar(cliente, eid, antiga, [turma_2026])

    assert r.status_code == 409, r.text
    detalhe = r.json()["detail"]
    assert "“3º Ano A” é do ano letivo 2026" in detalhe
    assert "“3ºA” é de 2025" in detalhe
    assert "Nada foi consolidado" in detalhe
    assert _matriculas(db) == antes
    assert db.get(Turma, turma_2026) is not None and db.get(Turma, antiga) is not None
    assert _auditorias(db, "turmas.consolidadas") == 0


def test_controle_consolidar_duplicadas_do_mesmo_ano_anterior_continua(
        cliente, db, escola_completa):
    """As duplicadas de 2025 entre si (a tela propõe grupos por ano letivo): o
    histórico vai para a canônica de 2025, como antes."""
    eid = escola_completa["escola"].id
    ids = sorted(a.id for a in escola_completa["alunos"])
    canonica = _turma(db, eid, "2ºA", 2025, ano_escolar="2º Ano")
    duplicada = _turma(db, eid, "2 ANO A (123)", 2025, ano_escolar="2º Ano")
    for aid in ids:
        db.add(Matricula(escola_id=eid, aluno_id=aid, turma_id=duplicada, ano_letivo=2025))
    db.commit()

    r = _consolidar(cliente, eid, canonica, [duplicada])

    assert r.status_code == 200, r.text
    assert r.json()["alunos_movidos"] == 3
    assert all((aid, canonica, 2025) in _matriculas(db) for aid in ids)


# --- Mudar o ano letivo de uma turma --------------------------------------------

def test_mudar_o_ano_de_turma_com_matricula_de_outro_ano_e_409(cliente, db,
                                                              escola_completa):
    """Levar a turma de 2026 (com as 3 crianças) para 2025 deixaria as matrículas
    de 2026 numa turma de 2025 — o mesmo estado, pela tela de Turmas."""
    eid, turma_2026 = escola_completa["escola"].id, escola_completa["turma"].id
    antes = _matriculas(db)

    r = cliente.put(f"{API}/escolas/{eid}/turmas/{turma_2026}", json={"ano_letivo": 2025})

    assert r.status_code == 409, r.text
    detalhe = r.json()["detail"]
    assert "3 matrícula(s) de ano letivo diferente de 2025" in detalhe
    assert "Nada foi alterado" in detalhe
    db.expire_all()
    assert db.get(Turma, turma_2026).ano_letivo == 2026
    assert _matriculas(db) == antes
    assert _auditorias(db, "turma.atualizada") == 0


def test_controle_corrigir_o_ano_de_turma_vazia_ou_reenviar_o_mesmo_ano(
        cliente, db, escola_completa):
    """Turma vazia criada com o ano errado: corrigir segue livre. E a tela, que
    reenvia o ano junto com os outros campos, continua editando a turma cheia."""
    eid, turma_2026 = escola_completa["escola"].id, escola_completa["turma"].id
    errada = _turma(db, eid, "3º Ano B", 2025)

    r = cliente.put(f"{API}/escolas/{eid}/turmas/{errada}", json={"ano_letivo": 2026})
    assert r.status_code == 200, r.text
    assert r.json()["ano_letivo"] == 2026

    r = cliente.put(f"{API}/escolas/{eid}/turmas/{turma_2026}",
                    json={"ano_letivo": 2026, "turno": "manha"})
    assert r.status_code == 200, r.text


def test_turma_de_outro_ano_com_so_matriculas_do_ano_novo_pode_ser_corrigida(
        cliente, db, escola_completa):
    """Dado legado (matrícula de 2026 numa turma de 2025, de antes da trava): a
    saída de corrigir o ano da turma para 2026 fica aberta, porque desfaz o
    estado em vez de criá-lo."""
    eid = escola_completa["escola"].id
    x = escola_completa["alunos"][0].id
    antiga = _turma(db, eid, "3º Ano B", 2025)
    db.execute(select(Matricula).where(Matricula.aluno_id == x)).scalar_one().turma_id = antiga
    db.commit()

    r = cliente.put(f"{API}/escolas/{eid}/turmas/{antiga}", json={"ano_letivo": 2026})

    assert r.status_code == 200, r.text
    assert (x, antiga, 2026) in _matriculas(db)


# --- Fila de Revisões de identidade: /resolver com criar_em_turma_id -------------

def _pendencia(db, eid: int, conta: str) -> int:
    from app.models import RevisaoIdentidade

    rev = RevisaoIdentidade(
        escola_id=eid, chave=f"matific|id:{conta}|resumo||",
        chave_identidade=f"matific|id:{conta}", plataforma="matific", formato="resumo",
        id_externo=conta, nome_recebido="Crianca Ficticia Da Fila", motivo="sem_candidato",
        candidatos=[], linhas=[], contexto={}, origem="sincronizacao", status="pendente")
    db.add(rev)
    db.commit()
    return rev.id


def _resolver(cliente, eid: int, rid: int, turma_id: int):
    return cliente.post(f"{API}/escolas/{eid}/importacoes/revisoes/{rid}/resolver",
                        json={"criar_em_turma_id": turma_id})


@pytest.mark.parametrize("ano_destino", [2025, 2027])
def test_resolver_criar_em_turma_de_outro_ano_e_409_e_nada_grava(cliente, db,
                                                                escola_completa,
                                                                ano_destino):
    """A última porta: a ficha nova nasceria com a matrícula de 2026 numa turma ATIVA
    de outro ano. 409 com o texto da trava do destino; a pendência continua
    pendente, e nenhuma ficha, matrícula, conta ou auditoria nasce."""
    from app.models import IdentidadeExterna, RevisaoIdentidade

    eid = escola_completa["escola"].id
    destino = _turma(db, eid, f"3º Ano A ({ano_destino})", ano_destino)
    rid = _pendencia(db, eid, f"u-outro-ano-{ano_destino}")
    alunos_antes, antes = _total_alunos(db), _matriculas(db)

    r = _resolver(cliente, eid, rid, destino)

    assert r.status_code == 409, r.text
    detalhe = r.json()["detail"]
    assert f"“3º Ano A ({ano_destino})” é do ano letivo {ano_destino}" in detalhe
    assert "ano letivo ativo (2026)" in detalhe and "Nada foi gravado" in detalhe
    assert _total_alunos(db) == alunos_antes
    assert _matriculas(db) == antes
    assert db.get(RevisaoIdentidade, rid).status == "pendente"
    assert db.execute(select(func.count()).select_from(IdentidadeExterna).where(
        IdentidadeExterna.id_externo == f"u-outro-ano-{ano_destino}")).scalar_one() == 0
    assert _auditorias(db, "aluno.criado") == 0
    assert _auditorias(db, "identidade.revisao_resolvida") == 0


def test_controle_resolver_criar_na_turma_do_ano_ativo_continua(cliente, db,
                                                               escola_completa):
    eid, turma_2026 = escola_completa["escola"].id, escola_completa["turma"].id
    rid = _pendencia(db, eid, "u-ano-ativo")

    r = _resolver(cliente, eid, rid, turma_2026)

    assert r.status_code == 200, r.text
    assert (r.json()["aluno_id"], turma_2026, 2026) in _matriculas(db)
    assert _auditorias(db, "aluno.criado") == 1


def test_a_trava_do_destino_e_uma_so_nos_dois_routers():
    """``routers.academico`` (cadastrar, transferir) e ``routers.importacoes``
    (/resolver) usam a MESMA função, que mora em ``services``: um router não importa
    o outro, e o texto do 409 não diverge."""
    from app.routers import academico
    from app.services import turma_arquivada

    assert academico._exigir_destino_do_ano_ativo is turma_arquivada.exigir_destino_do_ano_ativo


# --- Mudar o ano letivo: a trava da escola antes de contar ------------------------

def test_mudar_o_ano_toma_a_trava_da_escola_antes_de_contar_as_matriculas(
        cliente, db, escola_completa, monkeypatch):
    """No PG, cadastrar, transferir e o /resolver tomam a trava da escola antes de ler
    o ano da turma. Mudar o ano letivo de uma turma toma a MESMA trava antes de
    contar as matrículas de outro ano: senão uma matrícula do ano que a turma está
    deixando (a de 2026, numa turma que passa a 2025) entrava entre a contagem e a
    troca do ano (no SQLite a trava é no-op: aqui se prova a ordem). Sem mudar o
    ano, nada muda: a trava não é tomada."""
    from app.routers import academico

    eventos: list[str] = []
    trava_real = academico.bloquear_escola_para_importacao
    contagem_real = academico._exigir_turma_sem_matricula_de_outro_ano

    def _trava(sessao, escola_id):
        eventos.append("trava")
        return trava_real(sessao, escola_id)

    def _contagem(sessao, turma, novo_ano):
        eventos.append("conta")
        return contagem_real(sessao, turma, novo_ano)

    monkeypatch.setattr(academico, "bloquear_escola_para_importacao", _trava)
    monkeypatch.setattr(academico, "_exigir_turma_sem_matricula_de_outro_ano", _contagem)
    eid = escola_completa["escola"].id
    errada = _turma(db, eid, "3º Ano B", 2025)

    r = cliente.put(f"{API}/escolas/{eid}/turmas/{errada}", json={"ano_letivo": 2026})
    assert r.status_code == 200, r.text
    assert eventos == ["trava", "conta"]

    eventos.clear()
    r = cliente.put(f"{API}/escolas/{eid}/turmas/{errada}",
                    json={"ano_letivo": 2026, "turno": "manha"})
    assert r.status_code == 200, r.text
    assert eventos == []


# --- "Reativar" com a matrícula LEGADA do ano numa turma de outro ano ----------
# Resíduo da revisão da rodada 8: as portas que GRAVAM recusam o estado, mas a ficha
# arquivada que já estava assim (dado legado) voltava a "ativo" com 200 e passava a
# contar na escola pela matrícula, fora das turmas do ano.

def _reativar(cliente, eid, ids):
    return cliente.post(f"{API}/escolas/{eid}/alunos/acoes",
                        json={"acao": "reativar", "aluno_ids": ids})


def _plantar_legado(db, eid, aluno_id, turma_id, status="arquivado") -> None:
    """O estado legado é plantado direto no banco (nenhuma porta o grava mais): a
    matrícula de 2026 da ficha aponta para ``turma_id``."""
    matricula = db.execute(select(Matricula).where(
        Matricula.aluno_id == aluno_id, Matricula.ano_letivo == 2026)).scalar_one()
    matricula.turma_id = turma_id
    db.get(Aluno, aluno_id).status = status
    db.commit()


@pytest.mark.parametrize("ano_turma", [2025, 2027])
def test_reativar_ficha_com_matricula_legada_em_turma_de_outro_ano_e_409(
        cliente, db, escola_completa, ano_turma):
    eid = escola_completa["escola"].id
    aluno_id = escola_completa["alunos"][0].id
    _plantar_legado(db, eid, aluno_id, _turma(db, eid, "3º Ano Z", ano_turma))
    antes = _matriculas(db)

    r = _reativar(cliente, eid, [aluno_id])

    assert r.status_code == 409, r.text
    detalhe = r.json()["detail"]
    assert f"turma de outro ano letivo (“3º Ano Z” ({ano_turma}))" in detalhe
    assert "Nada foi alterado" in detalhe and "turma de 2026" in detalhe
    db.expire_all()
    assert db.get(Aluno, aluno_id).status == "arquivado"
    assert _matriculas(db) == antes
    assert _auditorias(db, "aluno.reativar") == 0


def test_reativar_com_turma_de_outro_ano_arquivada_nao_manda_reativar_a_turma(
        cliente, db, escola_completa):
    """A turma antiga também arquivada (o caso mais provável): reativá-la não resolveria —
    a orientação é a do outro ano, não "reative a turma"."""
    eid = escola_completa["escola"].id
    aluno_id = escola_completa["alunos"][0].id
    t2025 = _turma(db, eid, "3º Ano Z", 2025)
    db.get(Turma, t2025).status = "arquivada"
    _plantar_legado(db, eid, aluno_id, t2025)

    r = _reativar(cliente, eid, [aluno_id])

    assert r.status_code == 409, r.text
    detalhe = r.json()["detail"]
    assert "turma de outro ano letivo" in detalhe
    assert "reative a turma" not in detalhe


def test_controle_reativar_com_matricula_na_turma_do_ano_continua(
        cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    aluno_id = escola_completa["alunos"][0].id
    db.get(Aluno, aluno_id).status = "arquivado"
    db.commit()

    r = _reativar(cliente, eid, [aluno_id])

    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(Aluno, aluno_id).status == "ativo"


def test_controle_veterano_com_historico_de_outro_ano_e_reativado(
        cliente, db, escola_completa):
    """Matrícula de 2025 numa turma de 2025 (histórico) + a de 2026 na turma do ano: o
    histórico não bloqueia — só a matrícula do ANO ATIVO conta."""
    eid = escola_completa["escola"].id
    aluno_id = escola_completa["alunos"][0].id
    t2025 = _turma(db, eid, "2º Ano A", 2025, ano_escolar="2º Ano")
    db.add(Matricula(escola_id=eid, aluno_id=aluno_id, turma_id=t2025, ano_letivo=2025))
    db.get(Aluno, aluno_id).status = "arquivado"
    db.commit()

    r = _reativar(cliente, eid, [aluno_id])

    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(Aluno, aluno_id).status == "ativo"


def test_controle_pedido_misto_com_ficha_ja_ativa_em_estado_legado_continua(
        cliente, db, escola_completa):
    """A ficha JÁ ativa não é contada (nada muda nela); a arquivada normal é reativada."""
    eid = escola_completa["escola"].id
    legado_id, normal_id = (a.id for a in escola_completa["alunos"][:2])
    _plantar_legado(db, eid, legado_id, _turma(db, eid, "3º Ano Z", 2025), status="ativo")
    db.get(Aluno, normal_id).status = "arquivado"
    db.commit()

    r = _reativar(cliente, eid, [legado_id, normal_id])

    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(Aluno, normal_id).status == "ativo"
