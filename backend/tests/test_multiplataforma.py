"""Testes da camada multiplataforma — dispositivos push e sincronização."""
import pytest

from app.models import DispositivoMovel
from app.services import push, scoring

TOKEN = "ExponentPushToken[abcdef1234567890]"


# --- Dispositivos ---------------------------------------------------------------

def test_registrar_dispositivo_e_upsert_por_token(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    primeiro = cliente.post(
        f"/api/v1/escolas/{escola_id}/dispositivos",
        json={"token_push": TOKEN, "plataforma": "android"},
    )
    assert primeiro.status_code == 200, primeiro.text
    assert db.query(DispositivoMovel).count() == 1

    # Registrar de novo com o mesmo token não duplica — atualiza
    segundo = cliente.post(
        f"/api/v1/escolas/{escola_id}/dispositivos",
        json={"token_push": TOKEN, "plataforma": "ios"},
    )
    assert segundo.status_code == 200
    assert db.query(DispositivoMovel).count() == 1
    assert db.query(DispositivoMovel).one().plataforma == "ios"


def test_remover_dispositivo_no_logout(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    cliente.post(f"/api/v1/escolas/{escola_id}/dispositivos",
                 json={"token_push": TOKEN, "plataforma": "android"})
    resposta = cliente.post(f"/api/v1/escolas/{escola_id}/dispositivos/remover",
                            json={"token_push": TOKEN})
    assert resposta.status_code == 200
    assert db.query(DispositivoMovel).count() == 0


# --- Push (Expo) -----------------------------------------------------------------

def test_montar_lotes_respeita_limite_do_expo():
    tokens = [f"token-{i}" for i in range(250)]
    lotes = push.montar_lotes(tokens, "Título", "Corpo", {"tela": "ranking"})
    assert [len(lote) for lote in lotes] == [100, 100, 50]
    assert lotes[0][0]["to"] == "token-0"
    assert lotes[0][0]["data"] == {"tela": "ranking"}


def test_notificar_escola_remove_tokens_mortos(db, escola_completa, monkeypatch):
    escola_id = escola_completa["escola"].id
    admin = escola_completa["admin"]
    db.add(DispositivoMovel(escola_id=escola_id, usuario_id=admin.id,
                            token_push="vivo", plataforma="android"))
    db.add(DispositivoMovel(escola_id=escola_id, usuario_id=admin.id,
                            token_push="morto", plataforma="android"))
    db.commit()

    monkeypatch.setattr(push, "_enviar_lotes", lambda lotes: ["morto"])
    alvo = push.notificar_escola(db, escola_id, "t", "c")
    assert alvo == 2
    tokens = [d.token_push for d in db.query(DispositivoMovel).all()]
    assert tokens == ["vivo"]


def test_falha_de_rede_no_push_nao_derruba_a_operacao(db, escola_completa, monkeypatch):
    escola_id = escola_completa["escola"].id
    admin = escola_completa["admin"]
    db.add(DispositivoMovel(escola_id=escola_id, usuario_id=admin.id,
                            token_push="qualquer", plataforma="ios"))
    db.commit()

    def explode(lotes):
        raise RuntimeError("rede fora")

    monkeypatch.setattr(push, "_enviar_lotes", explode)
    # Não pode levantar exceção
    assert push.notificar_escola(db, escola_id, "t", "c") == 1


def test_sem_dispositivos_nao_ha_chamada_de_rede(db, escola_completa, monkeypatch):
    chamado = []
    monkeypatch.setattr(push, "_enviar_lotes", lambda lotes: chamado.append(1) or [])
    assert push.notificar_escola(db, escola_completa["escola"].id, "t", "c") == 0
    assert chamado == []


def test_importacao_dispara_push(cliente, db, escola_completa, monkeypatch):
    """A confirmação de importação notifica os aparelhos da escola."""
    envios = []
    monkeypatch.setattr(push, "_enviar_lotes",
                        lambda lotes: envios.append(lotes) or [])
    escola_id = escola_completa["escola"].id
    admin = escola_completa["admin"]
    ana = escola_completa["alunos"][0]
    db.add(DispositivoMovel(escola_id=escola_id, usuario_id=admin.id,
                            token_push=TOKEN, plataforma="android"))
    db.commit()

    resposta = cliente.post(
        f"/api/v1/escolas/{escola_id}/importacoes/confirmar",
        json={"plataforma": "matific", "formato": "resumo", "tipo": "texto",
              "linhas": [{"nome": ana.nome,
                          "dados": {"atividades": 10, "pontuacao_media": 70, "estrelas": 30},
                          "aluno_id": ana.id}]},
    )
    assert resposta.status_code == 200, resposta.text
    assert len(envios) == 1
    assert "Matific" in envios[0][0][0]["body"]


# --- Sincronização ----------------------------------------------------------------

def test_sincronizacao_devolve_pacote_completo(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    from app.models import Importacao, SnapshotMatific
    importacao = Importacao(escola_id=escola.id, plataforma="matific", tipo="seed")
    db.add(importacao)
    db.flush()
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=ana.id,
                           importacao_id=importacao.id,
                           atividades=20, estrelas=50, pontuacao_media=75))
    db.commit()
    scoring.recalcular_escola(db, escola.id)

    resposta = cliente.get(f"/api/v1/escolas/{escola.id}/sincronizacao")
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    for chave in ("gerado_em", "dashboard", "ranking", "evolucao", "alertas", "mural"):
        assert chave in corpo, f"faltou {chave}"
    assert corpo["dashboard"]["escola"]["nome"] == "ESCOLA TESTE"
    assert len(corpo["ranking"]) == 3
    assert corpo["ranking"][0]["nome"] == ana.nome
    # Alunos sem snapshot geram alertas de sem_dados no mesmo pacote
    assert any(alerta["tipo"] == "sem_dados" for alerta in corpo["alertas"])


def test_sincronizacao_nao_recarrega_series_por_consumidor(cliente, db, escola_completa):
    """Item 2 (perf): /sincronizacao carrega as séries de snapshot UMA vez e as
    injeta em alertas + mural + evolução — antes, cada consumidor relia as
    tabelas snapshots_matific/elefante (~3x cada por request). Conta os SELECTs
    de série e confirma o pacote intacto."""
    from sqlalchemy import event

    from app.models import Importacao, SnapshotElefante, SnapshotMatific

    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    importacao = Importacao(escola_id=escola.id, plataforma="matific", tipo="seed")
    db.add(importacao)
    db.flush()
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=ana.id, importacao_id=importacao.id,
                           atividades=20, estrelas=50, pontuacao_media=75))
    db.add(SnapshotElefante(escola_id=escola.id, aluno_id=ana.id, importacao_id=importacao.id,
                            livros_unicos=5, tempo_leitura_min=100,
                            questoes_tentativas=10, questoes_acertos=8))
    db.commit()
    scoring.recalcular_escola(db, escola.id)

    engine = db.get_bind()
    contagem = {"matific": 0, "elefante": 0}

    def _contar(_c, _cur, stmt, _p, _ctx, _m):
        alvo = stmt.lower()
        if "from snapshots_matific" in alvo:
            contagem["matific"] += 1
        if "from snapshots_elefante" in alvo:
            contagem["elefante"] += 1

    event.listen(engine, "before_cursor_execute", _contar)
    try:
        resposta = cliente.get(f"/api/v1/escolas/{escola.id}/sincronizacao")
    finally:
        event.remove(engine, "before_cursor_execute", _contar)

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["ranking"][0]["nome"] == ana.nome   # resultado intacto
    # As séries são carregadas 1x (series_e_dificuldade) e injetadas; o dashboard
    # ainda soma os KPIs por tabela. Margem folgada <= 3 (antes do fix eram ~6+).
    assert contagem["matific"] <= 3, contagem
    assert contagem["elefante"] <= 3, contagem


def test_sincronizacao_respeita_isolamento_de_escola(cliente, db, escola_completa):
    from app.models import Escola
    outra = Escola(nome="OUTRA", ano_letivo_ativo=2026)
    db.add(outra)
    db.commit()
    resposta = cliente.get(f"/api/v1/escolas/{outra.id}/sincronizacao")
    assert resposta.status_code == 403
