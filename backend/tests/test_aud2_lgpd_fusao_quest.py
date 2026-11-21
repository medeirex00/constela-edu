"""G_LGPD-3: "Fundir duplicatas" não pode apagar o Constela Quest que a criança usa.

Imprimir os cartões da turma (``garantir_credenciais_turma``) dá cartão E perfil a
TODA ficha ativa, a duplicata e a oficial. A criança recebe o cartão com o nome que
reconhece (o da duplicata) e joga. A fusão sugere a ficha da Lista Piloto como
principal e, antes, mantinha sempre o perfil e o cartão da ficha que fica: o XP, o
progresso e as tentativas da criança iam embora pelo CASCADE e o cartão que ela usa
deixava de entrar, sem nenhum aviso na prévia.

Regra agora (``alunos_fusao.plano_quest``):
  * fica o perfil que tem uso (XP, tentativas, progresso, sequência, nome escolhido);
  * fica o cartão que a criança usou (o mais recente quando os dois foram usados);
  * as DUAS fichas com progresso: a fusão é recusada (nada é apagado);
  * a prévia (do par e do lote) e a resposta dizem o que acontece com o Quest.

Dados 100% fictícios; sem rede.
"""
from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.main import app
from app.models import Aluno, LogAuditoria, Matricula
from app.quest.models import (
    QuestCredencialAluno,
    QuestJornada,
    QuestMissao,
    QuestMundo,
    QuestPerfil,
    QuestProgresso,
    QuestTentativa,
)
from app.quest.services import credenciais as svc_cred

API = "/api/v1"


def _cena(db, escola_completa):
    """A ficha da coleta (``Ana Beatriz Souza``) e a oficial da Lista Piloto, na
    mesma turma, as duas com cartão e perfil (os cartões da turma impressos)."""
    eid = escola_completa["escola"].id
    turma = escola_completa["turma"]
    duplicata = escola_completa["alunos"][0]
    oficial = Aluno(escola_id=eid, nome="Ana Beatriz Souza Lima", da_lista_piloto=True)
    db.add(oficial)
    db.flush()
    db.add(Matricula(escola_id=eid, aluno_id=oficial.id, turma_id=turma.id,
                     ano_letivo=2026))
    db.commit()
    svc_cred.garantir_credenciais_turma(db, eid, turma)
    db.commit()
    mundo = QuestMundo(slug="mat-fusao", nome="Planeta Inventado")
    db.add(mundo)
    db.flush()
    jornada = QuestJornada(mundo_id=mundo.id, nome="Trilha Inventada", ano_escolar="3º Ano")
    db.add(jornada)
    db.flush()
    missao = QuestMissao(jornada_id=jornada.id, nome="Missão Inventada")
    db.add(missao)
    db.commit()
    return eid, duplicata.id, oficial.id, missao.id


def _perfil(db, aluno_id):
    return db.execute(select(QuestPerfil).where(QuestPerfil.aluno_id == aluno_id)).scalar_one()


def _cred(db, aluno_id):
    return db.execute(select(QuestCredencialAluno).where(
        QuestCredencialAluno.aluno_id == aluno_id)).scalar_one_or_none()


def _jogar(db, eid, aluno_id, missao_id, *, xp=520, tentativas=3):
    perfil = _perfil(db, aluno_id)
    perfil.xp_total, perfil.nivel, perfil.estrelas_total = xp, 4, 9
    perfil.ultimo_dia_ativo = date(2026, 5, 4)
    db.add(QuestProgresso(perfil_id=perfil.id, missao_id=missao_id, estrelas=3,
                          melhor_pct=100.0, tentativas=tentativas))
    for _ in range(tentativas):
        db.add(QuestTentativa(escola_id=eid, perfil_id=perfil.id, missao_id=missao_id,
                              iniciada_em=datetime.now(timezone.utc), xp_ganho=xp // tentativas,
                              estrelas=3))
    db.commit()
    return perfil.id


def _entrar(codigo):
    r = TestClient(app).post(f"{API}/quest/auth/entrar", json={"codigo": codigo})
    return r


def _tentativas(db, eid):
    return db.execute(select(func.count()).select_from(QuestTentativa).where(
        QuestTentativa.escola_id == eid)).scalar_one()


def test_fundir_duplicatas_mantem_o_progresso_e_o_cartao_que_a_crianca_usa(
        db, escola_completa, cliente):
    eid, dup_id, ofi_id, missao_id = _cena(db, escola_completa)
    codigo_dup = svc_cred.codigo_para_exibicao(_cred(db, dup_id))
    r = _entrar(codigo_dup)
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    perfil_dup_id = _jogar(db, eid, dup_id, missao_id)

    # A prévia do lote e a do par dizem o que acontece com o Quest.
    cands = cliente.get(f"{API}/escolas/{eid}/alunos/duplicados").json()["candidatos"]
    par = next(c for c in cands if c["loser_id"] == dup_id and c["manter_id"] == ofi_id)
    assert par["quest"]["conflito"] is False
    assert par["quest"]["perfil_fica"] == "remover"
    assert par["quest"]["cartao_fica"] == "remover"
    assert "Constela Quest" in par["quest"]["texto"]
    assert "Ana Beatriz Souza" in par["quest"]["texto"]
    previa = cliente.get(f"{API}/escolas/{eid}/alunos/fundir/previa",
                         params={"manter_id": ofi_id, "remover_id": dup_id}).json()
    assert previa["quest"]["perfil_fica"] == "remover"
    assert previa["quest"]["remover"]["xp"] == 520
    assert previa["quest"]["remover"]["tentativas"] == 3
    assert previa["quest"]["remover"]["cartao_usado"] is True
    assert previa["quest"]["manter"]["cartao_usado"] is False

    r = cliente.post(f"{API}/escolas/{eid}/alunos/duplicados/corrigir",
                     json={"loser_ids": [dup_id], "confirmacao": "FUNDIR"})
    assert r.status_code == 200 and r.json()["fundidos"] == 1, r.text
    detalhe = r.json()["detalhes"][0]
    assert detalhe["quest_perfil_de"] == dup_id
    assert detalhe["quest_cartao_de"] == dup_id
    assert detalhe["quest_tentativas_descartadas"] == 0

    db.expire_all()
    perfil_final = _perfil(db, ofi_id)
    assert perfil_final.id == perfil_dup_id
    assert perfil_final.xp_total == 520 and _tentativas(db, eid) == 3, (
        "a fusão APAGOU o progresso do Quest da criança (o perfil em uso era o da duplicata)")
    assert db.execute(select(func.count()).select_from(QuestProgresso)).scalar_one() == 1
    sessao = TestClient(app).get(f"{API}/quest/perfil",
                                 headers={"Authorization": f"Bearer {token}"})
    assert sessao.status_code == 200, "a sessão da criança caiu na fusão"
    assert _entrar(codigo_dup).status_code == 200, "o cartão que a criança usa deixou de entrar"
    # Um cartão por criança: o que ela nunca usou deixou de valer.
    assert db.execute(select(func.count()).select_from(QuestCredencialAluno)
                      .where(QuestCredencialAluno.aluno_id == ofi_id)).scalar_one() == 1
    log = db.execute(select(LogAuditoria).where(LogAuditoria.acao == "aluno.fundido")).scalar_one()
    assert log.detalhes["quest_perfil_de"] == dup_id
    assert log.detalhes["quest_cartao_de"] == dup_id


def test_fusao_manual_mantem_o_quest_da_ficha_absorvida_em_uso(db, escola_completa, cliente):
    eid, dup_id, ofi_id, missao_id = _cena(db, escola_completa)
    codigo_dup = svc_cred.codigo_para_exibicao(_cred(db, dup_id))
    assert _entrar(codigo_dup).status_code == 200
    _jogar(db, eid, dup_id, missao_id)

    r = cliente.post(f"{API}/escolas/{eid}/alunos/fundir", json={
        "manter_id": ofi_id, "remover_id": dup_id, "confirmacao": "FUNDIR"})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert _perfil(db, ofi_id).xp_total == 520 and _tentativas(db, eid) == 3, (
        "a fusão APAGOU o progresso do Quest da criança (o perfil em uso era o da duplicata)")
    assert _entrar(codigo_dup).status_code == 200
    assert r.json()["quest_perfil_de"] == dup_id


def test_as_duas_fichas_com_progresso_a_fusao_e_recusada_sem_apagar_nada(
        db, escola_completa, cliente):
    eid, dup_id, ofi_id, missao_id = _cena(db, escola_completa)
    _jogar(db, eid, dup_id, missao_id, xp=520, tentativas=3)
    _jogar(db, eid, ofi_id, missao_id, xp=90, tentativas=1)

    previa = cliente.get(f"{API}/escolas/{eid}/alunos/fundir/previa",
                         params={"manter_id": ofi_id, "remover_id": dup_id}).json()
    assert previa["quest"]["conflito"] is True
    assert "Constela Quest" in previa["quest"]["texto"]
    cands = cliente.get(f"{API}/escolas/{eid}/alunos/duplicados").json()["candidatos"]
    assert next(c for c in cands if c["loser_id"] == dup_id)["quest"]["conflito"] is True

    manual = cliente.post(f"{API}/escolas/{eid}/alunos/fundir", json={
        "manter_id": ofi_id, "remover_id": dup_id, "confirmacao": "FUNDIR"})
    assert manual.status_code == 409, manual.text
    assert "Constela Quest" in manual.json()["detail"]

    lote = cliente.post(f"{API}/escolas/{eid}/alunos/duplicados/corrigir",
                        json={"loser_ids": [dup_id], "confirmacao": "FUNDIR"})
    assert lote.status_code == 200, lote.text
    assert lote.json()["fundidos"] == 0
    falha = lote.json()["falhas"][0]
    assert falha["loser_id"] == dup_id and "Constela Quest" in falha["motivo"]

    db.expire_all()
    assert db.get(Aluno, dup_id) is not None and db.get(Aluno, ofi_id) is not None
    assert _perfil(db, dup_id).xp_total == 520 and _perfil(db, ofi_id).xp_total == 90
    assert _tentativas(db, eid) == 4
    assert db.execute(select(func.count()).select_from(LogAuditoria).where(
        LogAuditoria.acao == "aluno.fundido")).scalar_one() == 0


def test_so_o_cartao_foi_usado_fica_o_cartao_usado(db, escola_completa, cliente):
    """A criança entrou com o cartão da duplicata (e fez só a cerimônia): é esse
    cartão que segue valendo, e o perfil dela (com o nome escolhido) fica."""
    eid, dup_id, ofi_id, _missao = _cena(db, escola_completa)
    codigo_dup = svc_cred.codigo_para_exibicao(_cred(db, dup_id))
    cred_ofi_id = _cred(db, ofi_id).id
    assert _entrar(codigo_dup).status_code == 200
    perfil = _perfil(db, dup_id)
    perfil.nome_exibicao = "Bia"
    db.commit()

    r = cliente.post(f"{API}/escolas/{eid}/alunos/fundir", json={
        "manter_id": ofi_id, "remover_id": dup_id, "confirmacao": "FUNDIR"})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert _perfil(db, ofi_id).nome_exibicao == "Bia"
    assert db.get(QuestCredencialAluno, cred_ofi_id) is None
    assert _entrar(codigo_dup).status_code == 200


def test_os_dois_cartoes_usados_fica_o_mais_recente(db, escola_completa, cliente):
    eid, dup_id, ofi_id, _missao = _cena(db, escola_completa)
    agora = datetime.now(timezone.utc)
    cred_dup, cred_ofi = _cred(db, dup_id), _cred(db, ofi_id)
    cred_dup.ultimo_acesso = agora - timedelta(days=1)
    cred_ofi.ultimo_acesso = agora - timedelta(days=40)
    db.commit()
    cred_dup_id, cred_ofi_id = cred_dup.id, cred_ofi.id

    r = cliente.post(f"{API}/escolas/{eid}/alunos/fundir", json={
        "manter_id": ofi_id, "remover_id": dup_id, "confirmacao": "FUNDIR"})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(QuestCredencialAluno, cred_ofi_id) is None
    assert db.get(QuestCredencialAluno, cred_dup_id).aluno_id == ofi_id


def test_sem_uso_nenhum_fica_o_quest_da_ficha_principal(db, escola_completa, cliente):
    """Controle: cartões impressos e nunca usados — a regra de antes continua
    (fica o perfil e o cartão da ficha principal) e a prévia não alarma."""
    eid, dup_id, ofi_id, _missao = _cena(db, escola_completa)
    perfil_ofi_id, cred_ofi_id = _perfil(db, ofi_id).id, _cred(db, ofi_id).id
    previa = cliente.get(f"{API}/escolas/{eid}/alunos/fundir/previa",
                         params={"manter_id": ofi_id, "remover_id": dup_id}).json()
    assert previa["quest"]["conflito"] is False
    assert previa["quest"]["perfil_fica"] == "manter"
    assert previa["quest"]["cartao_fica"] == "manter"

    r = cliente.post(f"{API}/escolas/{eid}/alunos/fundir", json={
        "manter_id": ofi_id, "remover_id": dup_id, "confirmacao": "FUNDIR"})
    assert r.status_code == 200, r.text
    assert r.json()["quest_perfil_descartado"] == 1
    assert r.json()["quest_credencial_descartada"] == 1
    db.expire_all()
    assert _perfil(db, ofi_id).id == perfil_ofi_id
    assert _cred(db, ofi_id).id == cred_ofi_id


def test_sem_quest_a_previa_nao_fala_do_jogo(db, escola_completa, cliente):
    eid = escola_completa["escola"].id
    a, b = escola_completa["alunos"][0], escola_completa["alunos"][1]
    previa = cliente.get(f"{API}/escolas/{eid}/alunos/fundir/previa",
                         params={"manter_id": a.id, "remover_id": b.id}).json()
    assert previa["quest"]["tem_quest"] is False
    assert previa["quest"]["texto"] is None


def test_leque_com_progresso_em_duas_copias_recusa_so_a_segunda(db, escola_completa, cliente):
    """Três fichas da mesma criança (a oficial e duas cópias), duas com progresso:
    a primeira cópia leva o progresso para a oficial; a segunda é recusada (o
    lote segue) em vez de apagar o progresso que acabou de chegar."""
    eid, dup_id, ofi_id, missao_id = _cena(db, escola_completa)
    turma = escola_completa["turma"]
    # As duas cópias de plataforma com o nome completo da Lista Piloto: um LEQUE
    # (as duas apontam para a oficial), que o lote colapsa na oficial.
    db.get(Aluno, dup_id).nome = "Ana Beatriz Souza Lima"
    copia = Aluno(escola_id=eid, nome="Ana Beatriz Souza Lima")
    db.add(copia)
    db.flush()
    db.add(Matricula(escola_id=eid, aluno_id=copia.id, turma_id=turma.id, ano_letivo=2026))
    db.commit()
    copia_id = copia.id
    svc_cred.garantir_credenciais_turma(db, eid, turma)
    db.commit()
    _jogar(db, eid, dup_id, missao_id, xp=520, tentativas=3)
    _jogar(db, eid, copia_id, missao_id, xp=60, tentativas=1)

    from app.services import alunos_dedup
    pares = alunos_dedup._candidatos(db, eid)
    assert {(loser.id, survivor.id) for loser, survivor, *_ in pares} == {
        (dup_id, ofi_id), (copia_id, ofi_id)}
    r = cliente.post(f"{API}/escolas/{eid}/alunos/duplicados/corrigir",
                     json={"loser_ids": [dup_id, copia_id], "confirmacao": "FUNDIR"})
    assert r.status_code == 200, r.text
    assert r.json()["fundidos"] == 1
    db.expire_all()
    assert _tentativas(db, eid) == 4, "o lote apagou tentativas do Quest"
    assert len(r.json()["falhas"]) == 1
    assert "Constela Quest" in r.json()["falhas"][0]["motivo"]
