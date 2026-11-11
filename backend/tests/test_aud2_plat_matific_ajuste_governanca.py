"""Ajuste manual do Matific: a mesma governança do Elefante (G_AJUSTE-1, parte 1).

O ajuste manual grava um retrato novo do Matific com a data de AGORA. O contador
do Matific é cumulativo e a coleta seguinte traz de novo o valor da plataforma:
um número digitado por cima do dado coletado vira um degrau falso na série
(ganho inventado ou ganho real apagado nas Premiações e no Ranking de
Matemática). O Elefante já fecha essa porta; o Matific não fechava:

  * com a integração do Matific ATIVA (credencial válida ou agenda ligada), ou
    com EVIDÊNCIA de que o Matific da escola já chegou da plataforma (coleta,
    relatório importado, conexão registrada no log), o ajuste manual é do Admin
    Global — admin e coordenador da escola recebem 403 com a explicação;
  * o motivo é obrigatório (é o que explica a mudança no histórico);
  * aluno que não está ativo (transferido, arquivado…) não recebe ajuste.

Numa escola que nunca recebeu o Matific da plataforma, o ajuste manual continua
com a escola: ali ele é a única fonte do dado.

Dados fictícios.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_senha
from app.main import app
from app.models import (Aluno, EventoAluno, Importacao, LogAuditoria, PlataformaCredencial,
                        SincronizacaoConfig, SincronizacaoExecucao, SnapshotMatific, Usuario)
from app.services.audit import registrar

API = "/api/v1"
CORPO = {"atividades": 12, "estrelas": 40, "motivo": "correção do relatório"}


def _url(escola_id: int, aluno_id: int) -> str:
    return f"{API}/escolas/{escola_id}/matific/{aluno_id}"


def _coordenador(db, escola) -> TestClient:
    db.add(Usuario(escola_id=escola.id, nome="Coordenação Fictícia",
                   email="coord@aud2-plat.local", senha_hash=hash_senha("s3nh4"),
                   cargo="coordenador"))
    db.commit()
    cliente = TestClient(app)
    resposta = cliente.post(f"{API}/auth/login",
                            data={"username": "coord@aud2-plat.local", "password": "s3nh4"})
    assert resposta.status_code == 200, resposta.text
    cliente.headers["Authorization"] = f"Bearer {resposta.json()['access_token']}"
    return cliente


def _coleta(db, escola_id: int, aluno_id: int, atividades: int, estrelas: int) -> None:
    """Retrato como a sincronização grava: uma Importacao NÃO manual."""
    imp = Importacao(escola_id=escola_id, plataforma="matific", tipo="api", qtd_alunos=1)
    db.add(imp)
    db.flush()
    db.add(SnapshotMatific(
        escola_id=escola_id, aluno_id=aluno_id, importacao_id=imp.id,
        data_referencia=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1),
        atividades=atividades, estrelas=estrelas, pontuacao_media=4.0))
    db.commit()


def _retratos(db, aluno_id: int) -> list[SnapshotMatific]:
    db.expire_all()
    return db.execute(select(SnapshotMatific).where(SnapshotMatific.aluno_id == aluno_id)
                      .order_by(SnapshotMatific.id)).scalars().all()


# --- Integração ativa ---------------------------------------------------------------------

def test_integracao_do_matific_ativa_fecha_o_ajuste_da_escola(cliente, cliente_global, db,
                                                              escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    coordenador = _coordenador(db, escola)

    # Sem integração e sem dado da plataforma: o ajuste é da escola.
    assert coordenador.put(_url(escola.id, ana.id), json=CORPO).status_code == 200

    db.add(PlataformaCredencial(escola_id=escola.id, plataforma="matific",
                                segredo_cifrado="cifrado-de-teste", status="valida"))
    db.commit()
    antes = len(_retratos(db, ana.id))
    for perfil in (coordenador, cliente):
        bloqueado = perfil.put(_url(escola.id, ana.id),
                               json={**CORPO, "atividades": 999, "estrelas": 4995})
        assert bloqueado.status_code == 403, bloqueado.text
        assert "integração" in bloqueado.json()["detail"]
        assert "Matific" in bloqueado.json()["detail"]
    assert len(_retratos(db, ana.id)) == antes            # nada gravado

    # O Admin Global continua fazendo a manutenção.
    assert cliente_global.put(_url(escola.id, ana.id), json=CORPO).status_code == 200


def test_agenda_do_matific_ligada_conta_e_integracao_do_elefante_nao(db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    coordenador = _coordenador(db, escola)

    # A integração de OUTRA plataforma não governa o Matific.
    db.add(PlataformaCredencial(escola_id=escola.id, plataforma="elefante",
                                segredo_cifrado="cifrado-de-teste", status="valida"))
    db.commit()
    assert coordenador.put(_url(escola.id, ana.id), json=CORPO).status_code == 200

    agenda = SincronizacaoConfig(escola_id=escola.id, plataforma="matific", ativo=True,
                                 cadencia="diaria")
    db.add(agenda)
    db.commit()
    assert coordenador.put(_url(escola.id, ana.id), json=CORPO).status_code == 403


# --- Evidência histórica (a trava que a escola não desliga) ---------------------------------

def test_coleta_do_matific_ja_recebida_fecha_o_ajuste_sem_credencial(cliente, cliente_global,
                                                                     db, escola_completa):
    """O cenário da auditoria: coleta recebida, coordenador corrige por cima."""
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    coordenador = _coordenador(db, escola)
    _coleta(db, escola.id, ana.id, 100, 400)

    for perfil in (coordenador, cliente):
        bloqueado = perfil.put(_url(escola.id, ana.id),
                               json={**CORPO, "atividades": 50, "estrelas": 200})
        assert bloqueado.status_code == 403, bloqueado.text
        detalhe = bloqueado.json()["detail"]
        assert "Matific" in detalhe and "Admin Global" in detalhe
    assert [r.atividades for r in _retratos(db, ana.id)] == [100]

    assert cliente_global.put(_url(escola.id, ana.id), json=CORPO).status_code == 200


def test_relatorio_do_matific_importado_fecha_o_ajuste(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    assert cliente.put(_url(escola.id, ana.id), json=CORPO).status_code == 200

    importado = cliente.post(
        f"{API}/escolas/{escola.id}/importacoes/confirmar",
        json={"plataforma": "matific", "formato": "resumo", "tipo": "texto",
              "linhas": [{"nome": ana.nome, "aluno_id": ana.id,
                          "dados": {"atividades": 10, "pontuacao_media": 4.0,
                                    "estrelas": 20}}]})
    assert importado.status_code == 200, importado.text

    depois = cliente.put(_url(escola.id, ana.id), json=CORPO)
    assert depois.status_code == 403, depois.text


def test_ajuste_manual_da_escola_nao_vira_evidencia_contra_ela(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    for _ in range(3):
        assert cliente.put(_url(escola.id, ana.id), json=CORPO).status_code == 200
    manuais = db.execute(select(Importacao).where(Importacao.plataforma == "matific",
                                                  Importacao.tipo == "manual")).scalars().all()
    assert len(manuais) == 3


def test_dado_do_elefante_nao_fecha_o_ajuste_do_matific(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    db.add(Importacao(escola_id=escola.id, plataforma="elefante", tipo="texto"))
    registrar(db, "sync.credencial_salva", escola_id=escola.id,
              detalhes={"plataforma": "elefante"})
    db.commit()
    assert cliente.put(_url(escola.id, ana.id), json=CORPO).status_code == 200


@pytest.mark.parametrize("marca", ["auditoria_credencial", "auditoria_importacao",
                                   "importacao", "evento", "sincronizacao"])
def test_cada_marca_historica_do_matific_fecha_o_ajuste(cliente, db, escola_completa, marca):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    assert cliente.put(_url(escola.id, ana.id), json=CORPO).status_code == 200

    if marca == "auditoria_credencial":
        registrar(db, "sync.credencial_salva", escola_id=escola.id,
                  detalhes={"plataforma": "matific"})
    elif marca == "auditoria_importacao":
        registrar(db, "importacao.concluida", escola_id=escola.id,
                  detalhes={"plataforma": "matific", "tipo": "pdf", "alunos": 1})
    elif marca == "importacao":
        db.add(Importacao(escola_id=escola.id, plataforma="matific", tipo="pdf"))
    elif marca == "evento":
        db.add(EventoAluno(escola_id=escola.id, aluno_id=ana.id, plataforma="matific",
                           tipo_evento="atividade", ocorrido_em=datetime(2026, 5, 2, 10),
                           chave_natural=f"marca-{marca}"))
    else:
        db.add(SincronizacaoExecucao(escola_id=escola.id, plataforma="matific",
                                     origem="scheduler", status="concluida"))
    db.commit()

    bloqueado = cliente.put(_url(escola.id, ana.id), json=CORPO)
    assert bloqueado.status_code == 403, (marca, bloqueado.text)


# --- Motivo e aluno ativo -----------------------------------------------------------------

def test_motivo_do_ajuste_do_matific_e_obrigatorio(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    sem_motivo = {k: v for k, v in CORPO.items() if k != "motivo"}
    assert cliente.put(_url(escola.id, ana.id), json=sem_motivo).status_code == 422
    for motivo in (None, "", "ok", "     "):
        resposta = cliente.put(_url(escola.id, ana.id), json={**CORPO, "motivo": motivo})
        assert resposta.status_code == 422, (motivo, resposta.text)
    assert _retratos(db, ana.id) == []

    ok = cliente.put(_url(escola.id, ana.id), json={**CORPO, "motivo": "  correção do relatório "})
    assert ok.status_code == 200, ok.text
    log = db.execute(select(LogAuditoria).where(LogAuditoria.acao == "matific.editado")
                     ).scalars().first()
    assert log.detalhes["motivo"] == "correção do relatório"


@pytest.mark.parametrize("situacao", ["transferido", "arquivado", "fora_lista_piloto"])
def test_aluno_que_nao_esta_ativo_nao_recebe_ajuste(cliente, cliente_global, db,
                                                    escola_completa, situacao):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    aluno = db.get(Aluno, ana.id)
    aluno.status = situacao
    db.commit()
    for perfil in (cliente, cliente_global):
        resposta = perfil.put(_url(escola.id, ana.id), json=CORPO)
        assert resposta.status_code == 409, resposta.text
        assert "ativo" in resposta.json()["detail"]
    assert _retratos(db, ana.id) == []
