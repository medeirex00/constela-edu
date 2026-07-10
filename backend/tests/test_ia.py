"""Testes da Fase 6 — insights, alertas, camada de IA e assistente."""
import re
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


# --- Modo local inteligente: "os N melhores do X" -----------------------------------

_CTX_TOP = assistente.INSTRUCOES + (
    "### RESUMO\n- Escola: TESTE\n\n"
    "### EVOLUCAO\n- 1º: Fulano Errado (1º Ano A) — evolução 90.0\n\n"
    "### ALUNOS\n"
    "- Ana Beatriz Souza: turma 3º Ano A, 1º lugar, geral 92.0, Matific 70.0, Elefante 95.0\n"
    "- João Pedro Barbosa: turma 3º Ano A, 2º lugar, geral 80.0, Matific 88.0, Elefante 60.0\n"
    "- Sofia Almeida Duarte: turma 3º Ano B, 3º lugar, geral 75.0, Matific 80.0, Elefante 71.0\n"
    "- Carlos Lima Neto: turma 3º Ano B, 4º lugar, geral 60.0, Matific 40.0, Elefante 78.0\n"
)


def test_local_melhores_do_matific_ordena_pela_nota_certa():
    resposta = LocalProvedor().responder(_CTX_TOP, [{
        "papel": "usuario",
        "conteudo": "quem sao os 3 melhores alunos do matific na escola?"}])
    # Ordenado pela NOTA MATIFIC (João 88 > Sofia 80 > Ana 70), exatamente 3.
    assert resposta.index("João Pedro Barbosa") < resposta.index("Sofia Almeida Duarte")
    assert resposta.index("Sofia Almeida Duarte") < resposta.index("Ana Beatriz Souza")
    assert "Carlos Lima Neto" not in resposta
    assert "Fulano Errado" not in resposta          # não despeja a seção de evolução
    assert "evolução" not in resposta


def test_local_nao_sequestra_evolucao_nem_alertas():
    """Regressão: "melhor evolução"/"top que mais evoluíram" vão para a seção
    de EVOLUCAO — não para o pódio de nota geral."""
    for pergunta in ("qual aluno teve a melhor evolucao este mes?",
                     "top 3 alunos que mais evoluiram",
                     "quais os melhores alunos em evolucao?"):
        resposta = LocalProvedor().responder(_CTX_TOP, [{
            "papel": "usuario", "conteudo": pergunta}])
        assert "Fulano Errado" in resposta, pergunta   # seção EVOLUCAO
        assert "nota geral" not in resposta.lower() or "evolução" in resposta


def test_local_melhor_aluno_geral_e_top_elefante():
    um = LocalProvedor().responder(_CTX_TOP, [{
        "papel": "usuario", "conteudo": "qual o melhor aluno da escola?"}])
    assert "Ana Beatriz Souza" in um and "João Pedro Barbosa" not in um

    ele = LocalProvedor().responder(_CTX_TOP, [{
        "papel": "usuario", "conteudo": "top 2 do elefante letrado"}])
    assert "Ana Beatriz Souza" in ele and "Carlos Lima Neto" in ele
    assert "João Pedro Barbosa" not in ele

    # "quem mais melhorou" continua indo para a seção de EVOLUCAO.
    evo = LocalProvedor().responder(_CTX_TOP, [{
        "papel": "usuario", "conteudo": "quem mais evoluiu este mês?"}])
    assert "Fulano Errado" in evo


def test_contexto_tem_rankings_por_plataforma(db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    _snapshot(db, escola.id, ana.id, atividades=50, estrelas=150, pontuacao_media=85)
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    contexto = assistente.montar_contexto(db, escola.id)
    assert "### RANKING_MATIFIC" in contexto
    assert "### RANKING_ELEFANTE" in contexto
    assert "Matific" in contexto.split("### ALUNOS")[1]


# --- Configuração do assistente pela interface --------------------------------------

def test_config_assistente_salva_cifrado_e_nunca_devolve_chave(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    base = f"/api/v1/escolas/{escola_id}/assistente"

    padrao = cliente.get(f"{base}/config").json()
    assert padrao == {"provedor": "local", "modelo": "", "chave_definida": False}

    # Provedor externo sem chave: recusa com orientação.
    sem_chave = cliente.put(f"{base}/config", json={"provedor": "anthropic"})
    assert sem_chave.status_code == 400

    r = cliente.put(f"{base}/config", json={
        "provedor": "anthropic", "api_key": "sk-ant-teste-123", "modelo": ""})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["provedor"] == "anthropic" and corpo["chave_definida"] is True
    assert "sk-ant" not in r.text                    # a chave nunca volta

    # No banco, só a versão CIFRADA.
    from app.models import Configuracao
    from sqlalchemy import select
    row = db.execute(select(Configuracao).where(
        Configuracao.escola_id == escola_id,
        Configuracao.namespace == "assistente")).scalar_one()
    assert "sk-ant-teste-123" not in str(row.valor)
    from app.core.security import decifrar_segredo
    assert decifrar_segredo(row.valor["api_key_cifrada"]) == "sk-ant-teste-123"

    # Salvar de novo SEM informar chave mantém a atual.
    r2 = cliente.put(f"{base}/config", json={"provedor": "anthropic",
                                             "modelo": "claude-opus-4-8"})
    assert r2.json()["chave_definida"] is True
    assert cliente.get(f"{base}/status").json()["provedor"] == "anthropic"


def test_trocar_provedor_descarta_chave_do_anterior(cliente, db, escola_completa):
    """A chave de um fornecedor NUNCA é reaproveitada em outro: trocar de
    provedor sem informar chave nova é recusado."""
    escola_id = escola_completa["escola"].id
    base = f"/api/v1/escolas/{escola_id}/assistente/config"
    assert cliente.put(base, json={"provedor": "anthropic",
                                   "api_key": "sk-ant-abc"}).status_code == 200
    # Trocar para OpenAI mantendo a chave antiga: recusado (e a antiga cai).
    r = cliente.put(base, json={"provedor": "openai"})
    assert r.status_code == 400
    # Chave só de espaços também não vale.
    assert cliente.put(base, json={"provedor": "openai",
                                   "api_key": "   "}).status_code == 400
    # Com a chave do novo provedor, funciona.
    r2 = cliente.put(base, json={"provedor": "openai", "api_key": "sk-openai-x"})
    assert r2.status_code == 200 and r2.json()["chave_definida"] is True


def test_config_assistente_exige_admin(cliente, db, escola_completa):
    from app.core.security import hash_senha
    from app.models import Usuario
    escola = escola_completa["escola"]
    db.add(Usuario(escola_id=escola.id, nome="Prof", email="prof@t.local",
                   senha_hash=hash_senha("s3nh4abc"), cargo="professor"))
    db.commit()
    from fastapi.testclient import TestClient
    from app.main import app
    c2 = TestClient(app)
    token = c2.post("/api/v1/auth/login",
                    data={"username": "prof@t.local", "password": "s3nh4abc"}).json()
    c2.headers["Authorization"] = f"Bearer {token['access_token']}"
    assert c2.get(f"/api/v1/escolas/{escola.id}/assistente/config").status_code == 403


def test_provedor_externo_falhando_cai_no_local(cliente, db, escola_completa, monkeypatch):
    """Com chave inválida/sem rede, o assistente NUNCA sai do ar: responde local."""
    from app.services.ia import provedores
    from app.services.ia.base import ErroProvedorIA as Erro

    escola_id = escola_completa["escola"].id
    cliente.put(f"/api/v1/escolas/{escola_id}/assistente/config",
                json={"provedor": "anthropic", "api_key": "chave-invalida"})

    def explode(self, sistema, mensagens):
        raise Erro("chave recusada")
    monkeypatch.setattr(provedores.AnthropicProvedor, "responder", explode)

    r = cliente.post(f"/api/v1/escolas/{escola_id}/assistente",
                     json={"pergunta": "como está a escola?"})
    assert r.status_code == 200, r.text
    assert "local" in r.json()["provedor"]


def test_a3_provedor_externo_nao_recebe_nome_real_e_reidentifica(
        db, escola_completa, monkeypatch):
    """A3/LGPD: com provedor externo, NENHUM nome real de aluno sai da
    infraestrutura — contexto e pergunta vão pseudonimizados ("Aluno NNN") e a
    resposta é reidentificada no backend antes de chegar ao professor."""
    escola = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]
    # Ana com dados (fica no topo do ranking); João e Sofia sem dados (viram
    # nomes em alertas "sem_dados"). Assim os 3 nomes aparecem no contexto.
    _snapshot(db, escola.id, ana.id, dias_atras=1,
              atividades=50, estrelas=150, pontuacao_media=85)
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    nomes = [ana.nome, joao.nome, sofia.nome]

    from app.services.ia.base import ProvedorIA
    capturado = {}

    class FakeExterno(ProvedorIA):
        nome = "openai"

        def responder(self, sistema, mensagens):
            capturado["sistema"] = sistema
            capturado["mensagens"] = mensagens
            # Ecoa um token do contexto — para provar a reidentificação.
            token = re.search(r"Aluno \d+", sistema).group(0)
            return f"O destaque do ranking é {token}."

    monkeypatch.setattr(assistente, "_provedor_da_escola",
                        lambda db, escola_id: FakeExterno())

    resultado = assistente.perguntar(db, escola.id, escola_completa["admin"].id,
                                     f"como está {ana.nome}?")

    # 1) Nada de nome real no que SAIU para o provedor (contexto + conversa).
    enviado = capturado["sistema"] + " ".join(
        m["conteudo"] for m in capturado["mensagens"])
    for nome in nomes:
        assert nome not in enviado, f"vazou nome real: {nome}"
    # 2) A pergunta com nome completo foi tokenizada (o nome digitado não vazou).
    ultima = capturado["mensagens"][-1]["conteudo"]
    assert ana.nome not in ultima
    assert re.search(r"Aluno \d+", ultima)
    # 3) A resposta entregue ao usuário foi reidentificada para um nome real.
    assert any(nome in resultado["resposta"] for nome in nomes)
    assert resultado["provedor"] == "openai"
    # 4) O texto reidentificado é o que fica gravado (para o professor reler).
    from sqlalchemy import select

    from app.models import MensagemIA
    gravadas = db.execute(
        select(MensagemIA).where(MensagemIA.conversa_id == resultado["conversa_id"])
    ).scalars().all()
    assert any(any(nome in m.conteudo for nome in nomes) for m in gravadas)


def test_b1_aluno_arquivado_nao_entra_no_contexto_nem_vaza_para_ia(
        db, escola_completa, monkeypatch):
    """B1: aluno arquivado (com Nota órfã, pois arquivar não a apaga) NÃO aparece
    no contexto do assistente e, com provedor externo, seu nome NUNCA sai."""
    escola = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]
    for aluno in (ana, joao, sofia):
        _snapshot(db, escola.id, aluno.id, dias_atras=1,
                  atividades=30, estrelas=80, pontuacao_media=75)
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    # Arquiva a Ana SEM recalcular: a Nota órfã dela permanece no banco.
    ana.status = "arquivado"
    db.commit()

    contexto = assistente.montar_contexto(db, escola.id)
    assert ana.nome not in contexto            # arquivada some do contexto da IA
    assert joao.nome in contexto               # ativos permanecem

    from app.services.ia.base import ProvedorIA
    capturado = {}

    class FakeExterno(ProvedorIA):
        nome = "openai"

        def responder(self, sistema, mensagens):
            capturado["sistema"] = sistema
            return "ok"

    monkeypatch.setattr(assistente, "_provedor_da_escola",
                        lambda db, escola_id: FakeExterno())
    assistente.perguntar(db, escola.id, escola_completa["admin"].id,
                         "como está o ranking?")
    # Nada de nome real no que saiu (arquivada nem aparece; ativos vão tokenizados).
    for nome in (ana.nome, joao.nome, sofia.nome):
        assert nome not in capturado["sistema"], f"vazou {nome}"
    assert re.search(r"Aluno \d+", capturado["sistema"])   # ativos pseudonimizados


def test_medio1_pseudonimizacao_ignora_caixa(db, escola_completa, monkeypatch):
    """Médio-1 (LGPD): o nome digitado em caixa diferente (minúsculas) também é
    tokenizado antes de ir ao provedor externo — não vaza."""
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    _snapshot(db, escola.id, ana.id, dias_atras=1,
              atividades=30, estrelas=80, pontuacao_media=75)
    db.commit()
    scoring.recalcular_escola(db, escola.id)

    from app.services.ia.base import ProvedorIA
    capturado = {}

    class FakeExterno(ProvedorIA):
        nome = "openai"

        def responder(self, sistema, mensagens):
            capturado["mensagens"] = mensagens
            return "ok"

    monkeypatch.setattr(assistente, "_provedor_da_escola",
                        lambda db, escola_id: FakeExterno())
    # Pergunta com o nome do aluno em MINÚSCULAS (caixa diferente do banco).
    assistente.perguntar(db, escola.id, escola_completa["admin"].id,
                         f"como está {ana.nome.lower()}?")
    ultima = capturado["mensagens"][-1]["conteudo"]
    assert ana.nome.lower() not in ultima          # nome em minúsculas não vazou
    assert re.search(r"Aluno \d+", ultima)          # foi trocado por token


# --- Correção de dados: conta do dono vira global -----------------------------------

def test_promover_admin_global_idempotente(db, escola_completa):
    from app.core.database import _promover_admin_global
    from app.core.security import hash_senha
    from app.models import Usuario

    escola = escola_completa["escola"]
    dono = Usuario(escola_id=escola.id, nome="Dono",
                   email="EduMedeiros1405@gmail.com",   # caixa diferente de propósito
                   senha_hash=hash_senha("s3nh4abc"), cargo="admin")
    db.add(dono)
    db.commit()
    assert dono.is_global is False

    motor = db.get_bind()
    _promover_admin_global(motor)
    db.expire_all()
    assert db.get(Usuario, dono.id).is_global is True
    _promover_admin_global(motor)                      # 2ª vez: sem efeito colateral
    db.expire_all()
    assert db.get(Usuario, dono.id).is_global is True


# --- Retenção LGPD das conversas do assistente --------------------------------

def test_retencao_purga_conversas_com_mais_de_90_dias(db, escola_completa):
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import func, select

    from app.models import ConversaIA, MensagemIA
    escola, admin = escola_completa["escola"], escola_completa["admin"]
    ref = datetime.now(timezone.utc)
    velha = ConversaIA(escola_id=escola.id, usuario_id=admin.id, titulo="Velha",
                       created_at=ref - timedelta(days=91))
    nova = ConversaIA(escola_id=escola.id, usuario_id=admin.id, titulo="Nova",
                      created_at=ref - timedelta(days=10))
    db.add_all([velha, nova])
    db.flush()
    db.add_all([
        MensagemIA(conversa_id=velha.id, papel="usuario", conteudo="oi"),
        MensagemIA(conversa_id=nova.id, papel="usuario", conteudo="oi"),
    ])
    db.commit()
    velha_id, nova_id = velha.id, nova.id

    assert assistente.purgar_conversas_ia_expiradas(db) == 1
    vivas = set(db.execute(select(ConversaIA.id)).scalars())
    assert velha_id not in vivas and nova_id in vivas
    # Cascata (0003): a mensagem da conversa velha também sumiu; sobra a da nova.
    assert db.execute(select(func.count()).select_from(MensagemIA)).scalar() == 1
    # Idempotente: rodar de novo não apaga mais nada.
    assert assistente.purgar_conversas_ia_expiradas(db) == 0


def test_retencao_respeita_dias_configurado(db, escola_completa):
    from datetime import datetime, timedelta, timezone

    from app.models import ConversaIA
    escola, admin = escola_completa["escola"], escola_completa["admin"]
    db.add(ConversaIA(escola_id=escola.id, usuario_id=admin.id, titulo="X",
                      created_at=datetime.now(timezone.utc) - timedelta(days=40)))
    db.commit()
    assert assistente.purgar_conversas_ia_expiradas(db, dias=90) == 0   # < 90 dias
    assert assistente.purgar_conversas_ia_expiradas(db, dias=30) == 1   # > 30 dias
