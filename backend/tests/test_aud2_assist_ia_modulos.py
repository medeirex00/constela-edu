"""Assistente Pedagógico x módulos contratados (G_MODULOS-3).

Numa rede que contratou só Leitura (ou só Matemática), o contexto que o
assistente monta — e que, com provedor externo, sai pseudonimizado para fora da
infraestrutura — não pode levar notas, pódio nem ganhos do produto que a rede
não assinou; e o modo local não pode responder "os melhores no Matific".
Dados 100% fictícios; nenhuma rede externa (o provedor externo é um espião).
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.models import (
    Importacao,
    ModuloRede,
    Rede,
    SnapshotElefante,
    SnapshotMatific,
)
from app.services import assistente, modulos as svc_modulos, scoring
from app.services.ia.provedores import LocalProvedor

API = "/api/v1"


def _agora():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _rede_com(db, escola, modulo_ativo: str) -> None:
    rede = Rede(nome=f"Rede Inventada Só {modulo_ativo}", status="ativa")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    for modulo in svc_modulos.TODOS:
        db.add(ModuloRede(rede_id=rede.id, modulo=modulo, ativo=(modulo == modulo_ativo)))


def _retratos(db, escola, ana, joao, sofia) -> None:
    """Ana e João leem (Elefante); Ana e Sofia têm Matific — com uma base antiga
    e um retrato recente, para haver ganho nos 30 dias nas duas plataformas."""
    imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    agora = _agora()
    for aluno, livros in ((ana, 4), (joao, 6)):
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                                livros_unicos=1, tempo_leitura_min=10,
                                questoes_tentativas=2, questoes_acertos=1,
                                data_referencia=agora - timedelta(days=50)))
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                                livros_unicos=livros, tempo_leitura_min=50,
                                questoes_tentativas=10, questoes_acertos=8,
                                data_referencia=agora - timedelta(days=2)))
    for aluno, atividades in ((ana, 30), (sofia, 12)):
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                               atividades=1, estrelas=5, pontuacao_media=2.0,
                               data_referencia=agora - timedelta(days=50)))
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                               atividades=atividades, estrelas=600, pontuacao_media=3.5,
                               data_referencia=agora - timedelta(days=1)))


@pytest.fixture()
def so_leitura(db, escola_completa):
    escola = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]
    _rede_com(db, escola, "leitura")
    _retratos(db, escola, ana, joao, sofia)
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    return escola


@pytest.fixture()
def so_matematica(db, escola_completa):
    escola = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]
    _rede_com(db, escola, "matematica")
    _retratos(db, escola, ana, joao, sofia)
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    return escola


@pytest.fixture()
def avulsa(db, escola_completa):
    """Escola sem rede: os dois módulos valem (o contexto de sempre)."""
    escola = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]
    _retratos(db, escola, ana, joao, sofia)
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    return escola


def _secao(contexto: str, nome: str) -> str:
    marcador = f"### {nome}\n"
    if marcador not in contexto:
        return ""
    return contexto.split(marcador, 1)[1].split("\n### ", 1)[0]


def _local(contexto: str, pergunta: str) -> str:
    return LocalProvedor().responder(assistente.INSTRUCOES + contexto,
                                     [{"papel": "usuario", "conteudo": pergunta}])


class _ProvedorEspiao:
    nome = "anthropic"

    def __init__(self):
        self.sistema = None

    def responder(self, sistema, mensagens):
        self.sistema = sistema
        return "ok"


# --- Rede só com Leitura --------------------------------------------------------

def test_contexto_sem_matematica_nao_leva_matific_nem_atividades(db, so_leitura):
    contexto = assistente.montar_contexto(db, so_leitura.id)
    assert "### RANKING_MATIFIC" not in contexto
    assert "Matific" not in contexto
    assert "atividades" not in contexto
    # A Leitura contratada segue inteira.
    assert "### RANKING_ELEFANTE" in contexto
    assert "Elefante" in _secao(contexto, "ALUNOS")
    assert "livros" in _secao(contexto, "EVOLUCAO")
    # E o contexto diz, sem dado de criança, que Matemática está fora do plano.
    assert "Matemática" in _secao(contexto, "FORA_DO_PLANO")


def test_provedor_externo_nao_recebe_matematica_fora_do_plano(db, so_leitura, cliente,
                                                               monkeypatch):
    espiao = _ProvedorEspiao()
    monkeypatch.setattr(assistente, "_provedor_da_escola", lambda _db, _eid: espiao)
    r = cliente.post(f"{API}/escolas/{so_leitura.id}/assistente",
                     json={"pergunta": "Quem são os melhores em matemática?"})
    assert r.status_code == 200, r.text
    enviado = espiao.sistema
    assert "RANKING_MATIFIC" not in enviado
    assert "Matific" not in enviado
    assert "atividades" not in enviado


def test_modo_local_diz_que_matematica_nao_faz_parte_do_plano(db, so_leitura):
    contexto = assistente.montar_contexto(db, so_leitura.id)
    for pergunta in ("Quem são os melhores em matemática?",
                     "top 3 do matific",
                     "como está a matemática da escola?"):
        resposta = _local(contexto, pergunta)
        assert "não faz parte do plano" in resposta, (pergunta, resposta)
        assert "melhores alunos no Matific" not in resposta
        assert "nota 100" not in resposta   # nenhuma nota de Matemática de criança


def test_modo_local_responde_leitura_com_linha_sem_matific(db, so_leitura):
    """A linha do aluno sem "Matific x" ainda é lida pelo pódio da Leitura."""
    contexto = assistente.montar_contexto(db, so_leitura.id)
    resposta = _local(contexto, "quais os 2 melhores alunos no elefante?")
    assert "melhores alunos no Elefante Letrado" in resposta, resposta
    assert "João Pedro Barbosa" in resposta and "Ana Beatriz Souza" in resposta


# --- Rede só com Matemática (o simétrico) ---------------------------------------

def test_contexto_sem_leitura_nao_leva_elefante_nem_livros(db, so_matematica):
    contexto = assistente.montar_contexto(db, so_matematica.id)
    assert "### RANKING_ELEFANTE" not in contexto
    assert "Elefante" not in contexto
    assert "livros" not in contexto
    assert "### RANKING_MATIFIC" in contexto
    assert "Matific" in _secao(contexto, "ALUNOS")
    assert "atividades" in _secao(contexto, "EVOLUCAO")
    assert "Leitura" in _secao(contexto, "FORA_DO_PLANO")


def test_modo_local_diz_que_leitura_nao_faz_parte_do_plano(db, so_matematica):
    contexto = assistente.montar_contexto(db, so_matematica.id)
    resposta = _local(contexto, "quem são os 3 melhores no elefante letrado?")
    assert "não faz parte do plano" in resposta, resposta
    assert "melhores alunos no Elefante" not in resposta
    matific = _local(contexto, "top 2 do matific")
    assert "melhores alunos no Matific" in matific, matific


# --- Escola avulsa (os dois módulos): nada muda ----------------------------------

def test_escola_avulsa_mantem_as_duas_plataformas(db, avulsa):
    contexto = assistente.montar_contexto(db, avulsa.id)
    assert "### RANKING_MATIFIC" in contexto and "### RANKING_ELEFANTE" in contexto
    alunos = _secao(contexto, "ALUNOS")
    assert "Matific" in alunos and "Elefante" in alunos
    evolucao = _secao(contexto, "EVOLUCAO")
    assert "atividades" in evolucao and "livros" in evolucao
    assert "### FORA_DO_PLANO" not in contexto


# --- Alerta da Leitura numa rede só com Matemática (REV2-ASSIST-2) ---------------
#
# "Caiu de X% para Y% de acertos nas questões" é dado do Elefante (Leitura). Com o
# contrato mudado (ou a escola movida) e retratos antigos do Elefante, a seção
# ALERTAS levava esse alerta — ao provedor externo e ao modo local — enquanto
# FORA_DO_PLANO, no mesmo contexto, dizia que a Leitura não faz parte do plano.

def _com_queda_de_acertos(db, escola_completa, modulo_ativo: str | None):
    """Ana tem dois retratos do Elefante com acertos de 9/10 para 8/20 (a queda
    dispara o alerta); os três têm Matific normal (nenhum outro alerta)."""
    escola = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]
    if modulo_ativo:
        _rede_com(db, escola, modulo_ativo)
    imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    agora = _agora()
    for dias, livros, tentativas, acertos in ((10, 3, 10, 9), (1, 5, 20, 8)):
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=ana.id, importacao_id=imp.id,
                                livros_unicos=livros, tempo_leitura_min=30,
                                questoes_tentativas=tentativas, questoes_acertos=acertos,
                                data_referencia=agora - timedelta(days=dias)))
    for aluno in (ana, joao, sofia):
        for dias, atividades in ((50, 1), (1, 20)):
            db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                                   atividades=atividades, estrelas=5 * atividades,
                                   pontuacao_media=3.0,
                                   data_referencia=agora - timedelta(days=dias)))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    return escola


def test_rede_so_matematica_nao_leva_queda_de_acertos_da_leitura(db, escola_completa):
    escola = _com_queda_de_acertos(db, escola_completa, "matematica")
    contexto = assistente.montar_contexto(db, escola.id)
    assert "Leitura" in _secao(contexto, "FORA_DO_PLANO")
    assert "acertos" not in contexto, _secao(contexto, "ALERTAS")
    # O total do RESUMO conta só os alertas que foram ao contexto.
    assert "- Alertas ativos: 0" in _secao(contexto, "RESUMO")
    assert "Nenhum alerta no momento" in _secao(contexto, "ALERTAS")


def test_provedor_externo_nao_recebe_queda_de_acertos_fora_do_plano(
        db, escola_completa, cliente, monkeypatch):
    escola = _com_queda_de_acertos(db, escola_completa, "matematica")
    espiao = _ProvedorEspiao()
    monkeypatch.setattr(assistente, "_provedor_da_escola", lambda _db, _eid: espiao)
    r = cliente.post(f"{API}/escolas/{escola.id}/assistente",
                     json={"pergunta": "Quais alunos precisam de atenção?"})
    assert r.status_code == 200, r.text
    linhas = [ln for ln in espiao.sistema.splitlines() if "acertos" in ln]
    assert not linhas, linhas


def test_modo_local_nao_responde_queda_de_acertos_fora_do_plano(db, escola_completa):
    escola = _com_queda_de_acertos(db, escola_completa, "matematica")
    contexto = assistente.montar_contexto(db, escola.id)
    resposta = _local(contexto, "quais alunos precisam de atenção?")
    assert "acertos nas questões" not in resposta, resposta


@pytest.mark.parametrize("modulo_ativo", ["leitura", None])
def test_com_leitura_no_plano_a_queda_de_acertos_continua_no_contexto(
        db, escola_completa, modulo_ativo):
    """Rede só Leitura e escola avulsa: o alerta é da Leitura contratada e segue."""
    escola = _com_queda_de_acertos(db, escola_completa, modulo_ativo)
    contexto = assistente.montar_contexto(db, escola.id)
    alertas = _secao(contexto, "ALERTAS")
    assert "Ana Beatriz Souza caiu de 90,0% para 40,0% de acertos nas questões" in alertas, \
        alertas
    assert "- Alertas ativos: 1" in _secao(contexto, "RESUMO")
