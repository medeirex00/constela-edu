"""Retenção e minimização do log de auditoria — só o MECANISMO (achado 4, 20/10/2026).

Não há regra jurídica de prazo definida: tudo nasce DESLIGADO (prazo 0, minimização
desligada = comportamento atual). O que estes testes travam:

* com os padrões, nada muda: o expurgo não conta nem apaga, o log grava como antes;
* a minimização, quando ligada, tira só o nome ATUAL do aluno identificado pelo id
  (o id basta) e mantém o nome que é EVIDÊNCIA (o da planilha, o anterior);
* o expurgo é por categoria disjunta, o ``--dry-run`` só conta, as provas do
  esquecimento nunca entram, e o registro de acesso tem piso de 183 dias;
* o log do Quest já nasce sem o nome escolhido pela criança.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.models import LogAuditoria, Notificacao, SincronizacaoExecucao, SincronizacaoLog
from app.services import audit
from app.services.audit import (CATEGORIAS, config_retencao, expurgar_retencao,
                                minimizar_detalhes, registrar)

AGORA = datetime(2026, 10, 20, 12, 0)


def _velho(dias: int) -> datetime:
    return AGORA - timedelta(days=dias)


def _log(db, acao, dias_atras, **kw):
    db.add(LogAuditoria(acao=acao, created_at=_velho(dias_atras), detalhes={}, **kw))


# --- padrões = comportamento atual ------------------------------------------------

def test_tudo_desligado_por_padrao():
    assert config_retencao.AUDITORIA_MINIMIZAR_NOMES is False
    assert all(dias == 0 for dias in audit.prazos_configurados().values())
    assert set(audit.prazos_configurados()) == set(CATEGORIAS)


def test_com_os_padroes_o_expurgo_nao_conta_nem_apaga(db):
    for dias in (10, 400, 4000):
        _log(db, "aluno.criado", dias)
        _log(db, "login", dias)
    db.commit()
    resultado = expurgar_retencao(db, simular=False, agora=AGORA)
    assert all(r["dias"] == 0 and r["linhas"] == 0 for r in resultado.values())
    assert len(db.execute(select(LogAuditoria)).scalars().all()) == 6


def test_registrar_por_padrao_grava_como_antes(db, escola_completa):
    ana = escola_completa["alunos"][0]
    registrar(db, "aluno.criado", escola_id=ana.escola_id, entidade="aluno",
              entidade_id=ana.id, detalhes={"nome": ana.nome})
    db.commit()
    log = db.execute(select(LogAuditoria).where(LogAuditoria.acao == "aluno.criado")
                     ).scalars().one()
    assert log.detalhes == {"nome": ana.nome}


# --- minimização ------------------------------------------------------------------

def test_minimizar_tira_o_nome_atual_e_mantem_a_evidencia(db, escola_completa):
    ana = escola_completa["alunos"][0]          # "Ana Beatriz Souza"
    detalhes = {"aluno": "ANA BEATRIZ SOUZA", "origem": "ANA B. SOUZA",
                "turma": "3º Ano A", "confianca": "alta",
                "mantido": {"id": ana.id, "nome": "  ana   beatriz souza "}}
    saida = minimizar_detalhes(db, "aluno", ana.id, detalhes)
    assert saida == {"origem": "ANA B. SOUZA", "turma": "3º Ano A", "confianca": "alta",
                     "mantido": {"id": ana.id}}
    assert detalhes["aluno"] == "ANA BEATRIZ SOUZA"     # não muta a entrada


def test_minimizar_nao_toca_sem_aluno_identificado(db, escola_completa):
    ana = escola_completa["alunos"][0]
    assert minimizar_detalhes(db, "aluno", None, {"nome": ana.nome}) == {"nome": ana.nome}
    assert minimizar_detalhes(db, "turma", 1, {"nome": "3º Ano A"}) == {"nome": "3º Ano A"}
    assert minimizar_detalhes(db, "aluno", 999999, {"nome": "X Y"}) == {"nome": "X Y"}


def test_minimizacao_ligada_vale_para_todo_registrar(db, escola_completa, monkeypatch):
    monkeypatch.setattr(config_retencao, "AUDITORIA_MINIMIZAR_NOMES", True)
    ana = escola_completa["alunos"][0]
    registrar(db, "aluno.criado", escola_id=ana.escola_id, entidade="aluno",
              entidade_id=ana.id, detalhes={"nome": ana.nome, "campos": ["nome"]})
    registrar(db, "aluno.atualizado", escola_id=ana.escola_id, entidade="aluno",
              entidade_id=ana.id, detalhes={"nome": ana.nome}, minimizar=False)
    db.commit()
    por_acao = {l.acao: l.detalhes for l in db.execute(select(LogAuditoria)).scalars()}
    assert por_acao["aluno.criado"] == {"campos": ["nome"]}
    assert por_acao["aluno.atualizado"] == {"nome": ana.nome}    # forçado na chamada


def test_log_do_quest_nasce_sem_o_nome_escolhido(cliente, db, escola_completa):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    cliente.post(f"/api/v1/escolas/{escola.id}/quest/turmas/{turma.id}/cartoes")
    from app.quest.models import QuestCredencialAluno
    db.expire_all()
    codigo = db.execute(select(QuestCredencialAluno.codigo_login).where(
        QuestCredencialAluno.aluno_id == escola_completa["alunos"][0].id)).scalar_one()
    token = TestClient(app).post("/api/v1/quest/auth/entrar",
                                 json={"codigo": codigo}).json()["access_token"]
    r = TestClient(app).patch("/api/v1/quest/perfil/nome", json={"nome": "Bibi"},
                              headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "quest.nome_escolhido")).scalars().one()
    assert "Bibi" not in str(log.detalhes)
    assert log.entidade == "aluno" and log.entidade_id == escola_completa["alunos"][0].id


# --- expurgo --------------------------------------------------------------------

@pytest.fixture
def historico(db, escola_completa):
    eid = escola_completa["escola"].id
    for dias in (30, 400):
        _log(db, "login", dias)
        _log(db, "login.falhou", dias)
        _log(db, "quest.login", dias)
        _log(db, "quest.avatar", dias)
        _log(db, "aluno.criado", dias, escola_id=eid)
        _log(db, "identidade.revisao_resolvida", dias, escola_id=eid)
        _log(db, "pesos.alterados", dias, escola_id=eid)
        _log(db, "aluno.excluido_permanente", dias, escola_id=eid)   # prova: fica
    execucao = SincronizacaoExecucao(escola_id=eid, plataforma="elefante", origem="manual")
    db.add(execucao)
    db.flush()
    for dias in (30, 400):
        db.add(SincronizacaoLog(execucao_id=execucao.id, escola_id=eid, etapa="download",
                                mensagem="baixado", created_at=_velho(dias)))
        db.add(Notificacao(escopo="escola", escola_id=eid, tipo="t", titulo="Aviso teste",
                           created_at=_velho(dias)))
    db.commit()


def test_dry_run_so_conta(db, historico):
    prazos = {c: 365 for c in CATEGORIAS}
    antes = len(db.execute(select(LogAuditoria)).scalars().all())
    resultado = expurgar_retencao(db, simular=True, prazos=prazos, agora=AGORA)
    assert {c: r["linhas"] for c, r in resultado.items()} == {
        "auditoria_acesso": 3, "auditoria_quest": 1, "auditoria_alunos": 2,
        "auditoria_demais": 1, "sincronizacao_logs": 1, "notificacoes": 1}
    db.commit()
    assert len(db.execute(select(LogAuditoria)).scalars().all()) == antes


def test_expurgo_por_categoria_e_disjunto_e_preserva_as_provas(db, historico):
    resultado = expurgar_retencao(db, simular=False, prazos={"auditoria_quest": 365},
                                  agora=AGORA)
    db.commit()
    assert resultado["auditoria_quest"]["linhas"] == 1
    acoes = [l.acao for l in db.execute(select(LogAuditoria)).scalars()]
    assert acoes.count("quest.avatar") == 1                  # só o de 400 dias saiu
    assert acoes.count("quest.login") == 2                   # acesso: outra categoria
    assert "retencao.expurgo" in acoes                       # o expurgo fica registrado

    expurgar_retencao(db, simular=False, prazos={c: 1 for c in CATEGORIAS},
                      agora=AGORA, aceitar_abaixo_do_piso=True)
    db.commit()
    restantes = {l.acao for l in db.execute(select(LogAuditoria)).scalars()}
    assert restantes == {"aluno.excluido_permanente", "retencao.expurgo"}
    assert db.execute(select(SincronizacaoLog)).scalars().all() == []
    assert db.execute(select(Notificacao)).scalars().all() == []


def test_registro_de_acesso_tem_piso_de_seis_meses(db, historico):
    with pytest.raises(ValueError, match="183"):
        expurgar_retencao(db, simular=True, prazos={"auditoria_acesso": 90}, agora=AGORA)
    ok = expurgar_retencao(db, simular=True, prazos={"auditoria_acesso": 183}, agora=AGORA)
    assert ok["auditoria_acesso"]["linhas"] == 3


def test_categoria_desconhecida_e_recusada(db):
    with pytest.raises(ValueError, match="desconhecida"):
        expurgar_retencao(db, simular=True, prazos={"tudo": 1})


def test_prazo_pelo_ambiente(db, historico, monkeypatch):
    monkeypatch.setattr(config_retencao, "RETENCAO_NOTIFICACOES_DIAS", 365)
    resultado = expurgar_retencao(db, simular=True, agora=AGORA)
    assert resultado["notificacoes"]["linhas"] == 1
    assert resultado["auditoria_quest"]["dias"] == 0


# --- o script ---------------------------------------------------------------------

def test_script_dry_run_padrao_nao_faz_nada(db, historico, monkeypatch, capsys):
    from scripts import expurgar_retencao as script

    monkeypatch.setattr(script, "SessionLocal", sessionmaker(bind=db.get_bind()))
    antes = len(db.execute(select(LogAuditoria)).scalars().all())
    assert script.main(["--dry-run"]) == 0
    saida = capsys.readouterr().out
    assert "Nenhuma categoria com prazo definido" in saida
    assert len(db.execute(select(LogAuditoria)).scalars().all()) == antes


def test_script_conta_com_prazo_e_recusa_abaixo_do_piso(db, historico, monkeypatch, capsys):
    from scripts import expurgar_retencao as script

    monkeypatch.setattr(script, "SessionLocal", sessionmaker(bind=db.get_bind()))
    assert script.main(["--dry-run", "--dias", "auditoria_alunos=365"]) == 0
    assert "auditoria_alunos: prazo 365 dias" in capsys.readouterr().out
    assert script.main(["--dias", "auditoria_acesso=30"]) == 2
    assert "Recusado" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        script.main(["--dias", "auditoria_alunos=muito"])
