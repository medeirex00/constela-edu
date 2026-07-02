"""Testes da Fase 6 — insights, alertas, camada de IA e assistente."""
from datetime import datetime, timedelta, timezone

import pytest

from app.models import Importacao, SnapshotElefante, SnapshotMatific
from app.services import assistente, insights, scoring
from app.services.ia.provedores import LocalProvedor, obter_provedor


def _snapshot(db, escola_id, aluno_id, dias_atras=1, **valores):
    importacao = Importacao(escola_id=escola_id, plataforma="matific", tipo="seed")
    db.add(importacao)
    db.flush()
    momento = datetime.now(timezone.utc) - timedelta(days=dias_atras)
    if "atividades" in valores or "estrelas" in valores:
        db.add(SnapshotMatific(escola_id=escola_id, aluno_id=aluno_id,
                               importacao_id=importacao.id, data_referencia=momento,
                               **valores))
    else:
        db.add(SnapshotElefante(escola_id=escola_id, aluno_id=aluno_id,
                                importacao_id=importacao.id, data_referencia=momento,
                                **valores))


# --- Insights e alertas ---------------------------------------------------------

def test_indices_engajamento_evolucao_persistencia(db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    _snapshot(db, escola.id, ana.id, dias_atras=2,
              atividades=30, estrelas=100, pontuacao_media=80)
    db.commit()

    indices = insights.indices_da_escola(db, escola.id)
    de_ana = next(i for i in indices if i["aluno_id"] == ana.id)
    assert de_ana["engajamento"] > 0
    assert de_ana["evolucao"] > 0
    assert de_ana["persistencia"] > 0
    # Quem não tem dados fica com índices zerados
    sem_dados = next(i for i in indices if i["aluno_id"] != ana.id)
    assert sem_dados["engajamento"] == 0.0


def test_alerta_sem_dados_e_sem_atividade(db, escola_completa):
    escola = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]
    # Ana ativa; João parado há 60 dias; Sofia sem nada
    _snapshot(db, escola.id, ana.id, dias_atras=2,
              atividades=10, estrelas=20, pontuacao_media=70)
    _snapshot(db, escola.id, joao.id, dias_atras=60,
              atividades=5, estrelas=10, pontuacao_media=60)
    db.commit()

    alertas = insights.alertas_da_escola(db, escola.id)
    tipos = {(a["tipo"], a["aluno_id"]) for a in alertas}
    assert ("sem_dados", sofia.id) in tipos
    assert ("sem_atividade", joao.id) in tipos
    assert not any(a["aluno_id"] == ana.id and a["tipo"] == "sem_atividade"
                   for a in alertas)


def test_alerta_queda_de_acertos(db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    _snapshot(db, escola.id, ana.id, dias_atras=20,
              livros_unicos=2, questoes_tentativas=20, questoes_acertos=18)  # 90%
    _snapshot(db, escola.id, ana.id, dias_atras=2,
              livros_unicos=3, questoes_tentativas=40, questoes_acertos=24)  # 60%
    db.commit()

    alertas = insights.alertas_da_escola(db, escola.id)
    assert any(a["tipo"] == "queda_acertos" and a["aluno_id"] == ana.id
               for a in alertas)


# --- Camada de IA (PRD §154) ------------------------------------------------------

def test_fabrica_escolhe_provedor_pela_configuracao(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "AI_PROVIDER", "local")
    assert obter_provedor().nome == "local"

    monkeypatch.setattr(settings, "AI_PROVIDER", "anthropic")
    monkeypatch.setattr(settings, "AI_API_KEY", "sk-teste")
    assert obter_provedor().nome == "anthropic"

    monkeypatch.setattr(settings, "AI_PROVIDER", "openai")
    assert obter_provedor().nome == "openai"


def test_provedor_anthropic_exige_chave(monkeypatch):
    from app.core.config import settings
    from app.services.ia import ErroProvedorIA
    monkeypatch.setattr(settings, "AI_PROVIDER", "anthropic")
    monkeypatch.setattr(settings, "AI_API_KEY", "")
    with pytest.raises(ErroProvedorIA):
        obter_provedor()


def test_provedor_local_responde_do_contexto():
    sistema = assistente.INSTRUCOES + (
        "### RESUMO\n- Escola: TESTE\n\n"
        "### RANKING\n- 1º: Ana Beatriz Souza (3º Ano A) — geral 92.0\n\n"
        "### ALERTAS\n- [alta] João está sem novos dados há 45 dias.\n\n"
        "### ALUNOS\n- Ana Beatriz Souza: turma 3º Ano A, 1º lugar, nota geral 92.0\n"
    )
    provedor = LocalProvedor()

    ranking = provedor.responder(sistema, [{"papel": "usuario",
                                            "conteudo": "Quem está no topo do ranking?"}])
    assert "Ana Beatriz Souza" in ranking

    alertas = provedor.responder(sistema, [{"papel": "usuario",
                                            "conteudo": "Quais alunos precisam de atenção?"}])
    assert "João" in alertas

    aluna = provedor.responder(sistema, [{"papel": "usuario",
                                          "conteudo": "Como está a Ana Beatriz Souza?"}])
    assert "1º lugar" in aluna


# --- Assistente completo -----------------------------------------------------------

def test_assistente_registra_conversa_e_responde(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    _snapshot(db, escola.id, ana.id, dias_atras=1,
              atividades=50, estrelas=150, pontuacao_media=85)
    db.commit()
    scoring.recalcular_escola(db, escola.id)

    resposta = cliente.post(
        f"/api/v1/escolas/{escola.id}/assistente",
        json={"pergunta": "Quem está em primeiro no ranking?"},
    )
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert "Ana Beatriz Souza" in corpo["resposta"]
    assert corpo["provedor"] == "local"

    # Conversa e mensagens registradas (PRD §169)
    conversas = cliente.get(f"/api/v1/escolas/{escola.id}/assistente/conversas").json()
    assert len(conversas) == 1
    detalhe = cliente.get(
        f"/api/v1/escolas/{escola.id}/assistente/conversas/{corpo['conversa_id']}"
    ).json()
    assert [m["papel"] for m in detalhe["mensagens"]] == ["usuario", "assistente"]

    # Continuação na mesma conversa
    seguinte = cliente.post(
        f"/api/v1/escolas/{escola.id}/assistente",
        json={"pergunta": "E os alertas?", "conversa_id": corpo["conversa_id"]},
    )
    assert seguinte.status_code == 200
    assert seguinte.json()["conversa_id"] == corpo["conversa_id"]


def test_assistente_nao_ve_outra_escola(cliente, db, escola_completa):
    """Isolamento multi-escolas vale para a IA (PRD §169)."""
    from app.models import Escola
    outra = Escola(nome="OUTRA ESCOLA", ano_letivo_ativo=2026)
    db.add(outra)
    db.commit()

    resposta = cliente.post(
        f"/api/v1/escolas/{outra.id}/assistente",
        json={"pergunta": "Qual o ranking?"},
    )
    # admin da escola de teste é global (não), aqui cargo=admin sem is_global:
    assert resposta.status_code == 403


def test_conversa_de_outro_usuario_nao_aparece(cliente, db, escola_completa):
    from app.core.security import hash_senha
    from app.models import ConversaIA, Usuario
    escola = escola_completa["escola"]
    outro = Usuario(escola_id=escola.id, nome="Outro", email="outro@escola.com.br",
                    senha_hash=hash_senha("s3nh4"), cargo="professor")
    db.add(outro)
    db.flush()
    db.add(ConversaIA(escola_id=escola.id, usuario_id=outro.id, titulo="Privada"))
    db.commit()

    conversas = cliente.get(f"/api/v1/escolas/{escola.id}/assistente/conversas").json()
    assert all(c["titulo"] != "Privada" for c in conversas)


def test_insights_pela_api(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    resposta = cliente.get(f"/api/v1/escolas/{escola.id}/insights")
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert "indices" in corpo and "alertas" in corpo
    # Sem snapshots, os três alunos aparecem como sem_dados
    assert sum(1 for a in corpo["alertas"] if a["tipo"] == "sem_dados") == 3
