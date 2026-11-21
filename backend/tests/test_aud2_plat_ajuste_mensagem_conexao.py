"""A recusa do ajuste manual diz a marca que a fechou (REV2-PLAT-2, sobre G_AJUSTE-1).

A trava do ajuste manual (Elefante e Matific) fecha com qualquer marca histórica da
plataforma — e isso continua. Mas a mensagem dizia sempre "Esta escola já recebeu
dados ... vindos da plataforma ... o que já foi recebido continua valendo", também
quando a marca era só a CONFIGURAÇÃO da integração:

  * ``sync.credencial_salva`` é gravado no "Salvar e validar" ANTES do teste de login
    (``sync/router._gravar_credencial``): vale também para a senha recusada;
  * ``sync.credencial_removida`` diz só que houve uma credencial;
  * uma ``SincronizacaoExecucao`` existe também quando a coleta falhou (login recusado).

Nesses casos nenhum dado precisa ter chegado. A mensagem agora diz o que é verdade
(o Matific/Elefante da escola já foi configurado na integração automática); a de
"dado recebido" fica para as marcas que provam dado (relatório importado, coleta
aplicada, evento, leitura). Dados fictícios.
"""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_senha
from app.main import app
from app.models import (EventoAluno, Importacao, Leitura, Livro, PlataformaCredencial,
                        SincronizacaoExecucao, SnapshotMatific, Usuario)
from app.services.audit import registrar

API = "/api/v1"
CORPO_MATIFIC = {"atividades": 12, "estrelas": 40, "motivo": "correção do relatório"}
CORPO_ELEFANTE = {"tempo_leitura_min": 30, "questoes_tentativas": 4, "questoes_acertos": 2,
                  "motivo": "correção do relatório", "livros_por_nivel": {"D": 1}}
DADO_RECEBIDO = "já recebeu dados"
NOME = {"matific": "Matific", "elefante": "Elefante Letrado"}


def _put(cliente: TestClient, plataforma: str, escola_id: int, aluno_id: int):
    corpo = CORPO_MATIFIC if plataforma == "matific" else CORPO_ELEFANTE
    return cliente.put(f"{API}/escolas/{escola_id}/{plataforma}/{aluno_id}", json=corpo)


def _coordenador(db, escola) -> TestClient:
    db.add(Usuario(escola_id=escola.id, nome="Coordenação Fictícia da Mensagem",
                   email="coord-mensagem@aud2-plat.local", senha_hash=hash_senha("s3nh4"),
                   cargo="coordenador"))
    db.commit()
    cliente = TestClient(app)
    resposta = cliente.post(f"{API}/auth/login", data={
        "username": "coord-mensagem@aud2-plat.local", "password": "s3nh4"})
    assert resposta.status_code == 200, resposta.text
    cliente.headers["Authorization"] = f"Bearer {resposta.json()['access_token']}"
    return cliente


def _nada_chegou_da_plataforma(db, plataforma: str) -> None:
    """A cena da revisão: nenhuma importação, evento, retrato ou leitura da plataforma."""
    assert db.execute(select(Importacao.id).where(
        Importacao.plataforma == plataforma, Importacao.tipo != "manual")).first() is None
    assert db.execute(select(EventoAluno.id).where(
        EventoAluno.plataforma == plataforma)).first() is None
    if plataforma == "matific":
        assert db.execute(
            select(SnapshotMatific.id).join(Importacao,
                                            Importacao.id == SnapshotMatific.importacao_id)
            .where(Importacao.tipo != "manual")).first() is None
    else:
        assert db.execute(select(Leitura.id)).first() is None


def _marca_de_configuracao(db, escola_id: int, plataforma: str, marca: str) -> None:
    if marca == "credencial_recusada":
        # O que o "Salvar e validar" grava ANTES do login, e o login recusado.
        db.add(PlataformaCredencial(escola_id=escola_id, plataforma=plataforma,
                                    segredo_cifrado="cifrado-de-teste", status="invalida",
                                    ultimo_erro="Usuário ou senha recusados."))
        registrar(db, "sync.credencial_salva", escola_id=escola_id, entidade="plataforma",
                  detalhes={"plataforma": plataforma})
    elif marca == "credencial_removida":
        registrar(db, "sync.credencial_removida", escola_id=escola_id,
                  entidade="plataforma", detalhes={"plataforma": plataforma})
    else:
        # A coleta que rodou e falhou no login: a execução fica, dado nenhum.
        db.add(SincronizacaoExecucao(escola_id=escola_id, plataforma=plataforma,
                                     origem="manual", status="erro"))
    db.commit()


@pytest.mark.parametrize("plataforma", ["matific", "elefante"])
@pytest.mark.parametrize("marca", ["credencial_recusada", "credencial_removida",
                                   "coleta_que_falhou"])
def test_integracao_so_configurada_fecha_o_ajuste_sem_dizer_que_dado_chegou(
        cliente, db, escola_completa, plataforma, marca):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    coordenador = _coordenador(db, escola)
    assert _put(coordenador, plataforma, escola.id, ana.id).status_code == 200

    _marca_de_configuracao(db, escola.id, plataforma, marca)
    _nada_chegou_da_plataforma(db, plataforma)

    for perfil in (coordenador, cliente):
        bloqueado = _put(perfil, plataforma, escola.id, ana.id)
        # A trava continua fechada (a regra não muda)...
        assert bloqueado.status_code == 403, (marca, bloqueado.text)
        detalhe = bloqueado.json()["detail"]
        # ...e a explicação diz o que é verdade: a integração foi configurada.
        assert DADO_RECEBIDO not in detalhe, detalhe
        assert "já foi recebido" not in detalhe, detalhe
        assert NOME[plataforma] in detalhe and "Admin Global" in detalhe
        assert "configurad" in detalhe and "Integrações" in detalhe, detalhe
        assert "NÃO reabre o ajuste" in detalhe


@pytest.mark.parametrize("plataforma", ["matific", "elefante"])
@pytest.mark.parametrize("marca", ["auditoria_importacao", "importacao", "evento"])
def test_dado_que_chegou_da_plataforma_continua_explicado_como_recebido(
        cliente, db, escola_completa, plataforma, marca):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    assert _put(cliente, plataforma, escola.id, ana.id).status_code == 200

    if marca == "auditoria_importacao":
        registrar(db, "importacao.concluida", escola_id=escola.id,
                  detalhes={"plataforma": plataforma, "tipo": "pdf", "alunos": 1})
    elif marca == "importacao":
        db.add(Importacao(escola_id=escola.id, plataforma=plataforma, tipo="pdf"))
    else:
        db.add(EventoAluno(escola_id=escola.id, aluno_id=ana.id, plataforma=plataforma,
                           tipo_evento="atividade" if plataforma == "matific" else "leitura",
                           ocorrido_em=datetime(2026, 5, 2, 10),
                           chave_natural=f"mensagem-{plataforma}-{marca}"))
    db.commit()

    bloqueado = _put(cliente, plataforma, escola.id, ana.id)
    assert bloqueado.status_code == 403, (marca, bloqueado.text)
    detalhe = bloqueado.json()["detail"]
    assert f"{DADO_RECEBIDO} do {NOME[plataforma]}" in detalhe, detalhe


def test_leitura_do_elefante_continua_explicada_como_dado_recebido(cliente, db,
                                                                  escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    livro = Livro(escola_id=escola.id, titulo="Livro Fictício da Mensagem", nivel_codigo="D")
    db.add(livro)
    db.flush()
    db.add(Leitura(escola_id=escola.id, aluno_id=ana.id, livro_id=livro.id))
    db.commit()

    bloqueado = _put(cliente, "elefante", escola.id, ana.id)
    assert bloqueado.status_code == 403, bloqueado.text
    assert f"{DADO_RECEBIDO} do Elefante Letrado" in bloqueado.json()["detail"]
