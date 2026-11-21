"""G_MODULOS-1 — a gamificação respeita o contrato de módulos da rede.

Rede só com Leitura e um retrato do Matific gravado (o contrato mudou no meio do
ano, ou a escola veio de uma rede com os dois módulos). O módulo não contratado
"não existe nem na interface, nem na API, nem nas médias/rankings"
(``services/modulos.py``): ele não dá XP, não desbloqueia conquista, não aparece
no mural (web, app e telão sem login), na biblioteca nem no perfil público.

Dados 100% fictícios; nenhuma rede externa.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import (
    Importacao,
    ModuloRede,
    Rede,
    SnapshotElefante,
    SnapshotMatific,
)
from app.services import gamificacao, modulos as svc_modulos, scoring

API = "/api/v1"
MATEMATICA = ("Primeiro Desafio", "Matemático", "Chuva de Estrelas", "Constelação")


def _agora():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _cenario(db, escola_completa, ativos):
    """Ana e João leem IGUAL (4 livros); só a Ana tem retrato do Matific do ano
    (30 atividades, 600 estrelas). ``ativos`` = módulos contratados (None = sem rede)."""
    escola = escola_completa["escola"]
    ana, joao, _sofia = escola_completa["alunos"]
    if ativos is not None:
        rede = Rede(nome="Rede Inventada Gamificacao", status="ativa")
        db.add(rede)
        db.flush()
        escola.rede_id = rede.id
        for modulo in svc_modulos.TODOS:
            db.add(ModuloRede(rede_id=rede.id, modulo=modulo, ativo=(modulo in ativos)))
    imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    agora = _agora()
    for aluno in (ana, joao):
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                                livros_unicos=4, tempo_leitura_min=50,
                                questoes_tentativas=10, questoes_acertos=8,
                                data_referencia=agora - timedelta(days=2)))
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=ana.id, importacao_id=imp.id,
                           atividades=30, estrelas=600, pontuacao_media=3.5,
                           data_referencia=agora - timedelta(days=1)))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    return escola, ana, joao


@pytest.fixture()
def so_leitura(db, escola_completa):
    return _cenario(db, escola_completa, {"leitura"})


def _de_matematica(textos):
    return [t for t in textos if any(m in t for m in MATEMATICA)]


def test_ranking_xp_nao_soma_o_matific_fora_do_plano(so_leitura, cliente):
    escola, ana, joao = so_leitura
    itens = cliente.get(f"{API}/escolas/{escola.id}/gamificacao/ranking-xp").json()
    xp = {i["aluno_id"]: i for i in itens}
    assert xp[ana.id]["xp"] == xp[joao.id]["xp"], (xp[ana.id], xp[joao.id])
    assert xp[ana.id]["conquistas"] == xp[joao.id]["conquistas"]


def test_aluno_sem_conquista_nem_xp_de_matematica(so_leitura, cliente):
    escola, ana, joao = so_leitura
    ga = cliente.get(f"{API}/escolas/{escola.id}/gamificacao/alunos/{ana.id}").json()
    gj = cliente.get(f"{API}/escolas/{escola.id}/gamificacao/alunos/{joao.id}").json()
    assert [c["nome"] for c in ga["conquistas"] if c["plataforma"] == "matific"] == []
    assert not _de_matematica([c["nome"] for c in ga["conquistas"]])
    assert ga["xp"] == gj["xp"]


def test_biblioteca_sem_conquista_nem_indicador_de_matematica(so_leitura, cliente):
    escola, *_ = so_leitura
    b = cliente.get(f"{API}/escolas/{escola.id}/gamificacao/biblioteca").json()
    assert [c["nome"] for c in b["conquistas"] if c["plataforma"] == "matific"] == []
    assert "atividades" not in b["indicadores"] and "estrelas" not in b["indicadores"]
    assert "livros_unicos" in b["indicadores"]
    assert b["estatisticas"]["total"] == len(b["conquistas"]) > 0


def test_mural_web_nao_celebra_conquista_de_matematica(so_leitura, cliente):
    escola, *_ = so_leitura
    eventos = cliente.get(f"{API}/escolas/{escola.id}/gamificacao/mural").json()["eventos"]
    textos = [e["texto"] for e in eventos]
    assert textos, "o cenário precisa celebrar a leitura para o teste significar algo"
    assert not _de_matematica(textos), textos


def test_mural_do_app_nao_celebra_conquista_de_matematica(so_leitura, cliente):
    escola, *_ = so_leitura
    pacote = cliente.get(f"{API}/escolas/{escola.id}/sincronizacao").json()
    assert not _de_matematica([e["texto"] for e in pacote["mural"]])


def test_telao_e_perfil_publico_sem_conquista_nem_xp_de_matematica(so_leitura, cliente):
    escola, ana, joao = so_leitura
    r = cliente.put(f"{API}/escolas/{escola.id}/painel-publico",
                    json={"ativo": True, "anonimizar": True})
    assert r.status_code == 200, r.text
    token = r.json()["url"].rsplit("/p/", 1)[1]
    anon = TestClient(app)
    painel = anon.get(f"{API}/publico/{token}/painel").json()
    assert not _de_matematica([m["texto"] for m in painel["mural"]])
    pa = anon.get(f"{API}/publico/{token}/alunos/{ana.id}").json()
    pj = anon.get(f"{API}/publico/{token}/alunos/{joao.id}").json()
    assert pa["xp"] == pj["xp"]
    assert not _de_matematica([c["nome"] for c in pa["conquistas"]])


def test_sequencia_de_semanas_nao_conta_o_matific(db, escola_completa):
    """Leitura parada há semanas, Matific (fora do plano) desta semana: a sequência
    de semanas com ganho não pode nascer do produto que a rede não contratou."""
    escola = escola_completa["escola"]
    joao = escola_completa["alunos"][1]
    rede = Rede(nome="Rede Inventada Sequencia", status="ativa")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    db.add(ModuloRede(rede_id=rede.id, modulo="matematica", ativo=False))
    imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=joao.id, importacao_id=imp.id,
                           atividades=9, estrelas=20, pontuacao_media=3.0,
                           data_referencia=_agora() - timedelta(days=1)))
    db.commit()
    g = gamificacao.gamificacao_do_aluno(db, escola.id, joao.id)
    assert g["sequencia_semanas"] == 0 and g["xp"] == 0


def test_rede_que_nunca_teve_matific_nao_lista_conquistas_dele(db, escola_completa, cliente):
    """Mesmo sem nenhum retrato do Matific, as 6 conquistas dele não aparecem
    com progresso 0 no perfil da criança."""
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    rede = Rede(nome="Rede Inventada Sem Matific", status="ativa")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    db.add(ModuloRede(rede_id=rede.id, modulo="matematica", ativo=False))
    db.commit()
    g = cliente.get(f"{API}/escolas/{escola.id}/gamificacao/alunos/{ana.id}").json()
    assert {c["plataforma"] for c in g["conquistas"]} == {"elefante"}


def test_rede_so_matematica_esconde_as_conquistas_de_leitura(db, escola_completa, cliente):
    escola, ana, joao = _cenario(db, escola_completa, {"matematica"})
    g = cliente.get(f"{API}/escolas/{escola.id}/gamificacao/alunos/{joao.id}").json()
    assert g["conquistas"] and {c["plataforma"] for c in g["conquistas"]} == {"matific"}
    assert g["xp"] == 0          # João só tem Leitura, que a rede não contratou
    b = cliente.get(f"{API}/escolas/{escola.id}/gamificacao/biblioteca").json()
    assert "livros_unicos" not in b["indicadores"]


def test_controle_escola_sem_rede_mantem_as_conquistas_de_matematica(
        db, escola_completa, cliente):
    escola, ana, joao = _cenario(db, escola_completa, None)
    ga = cliente.get(f"{API}/escolas/{escola.id}/gamificacao/alunos/{ana.id}").json()
    gj = cliente.get(f"{API}/escolas/{escola.id}/gamificacao/alunos/{joao.id}").json()
    assert _de_matematica([c["nome"] for c in ga["conquistas"] if c["atingida"]])
    assert ga["xp"] > gj["xp"]


# --- Configurações → Conquistas -------------------------------------------------

def test_definicoes_avisam_o_que_esta_fora_do_plano_sem_perder_nada(so_leitura, cliente):
    escola, *_ = so_leitura
    r = cliente.get(f"{API}/escolas/{escola.id}/gamificacao/conquistas/definicoes")
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["plataformas_fora_do_plano"] == ["matific"]
    # A lista volta INTEIRA: o PUT grava o que a tela devolve, e as conquistas do
    # módulo desligado ficam guardadas para quando a rede o religar.
    assert any(c["indicador"] == "atividades" for c in corpo["conquistas"])
    salvar = cliente.put(f"{API}/escolas/{escola.id}/gamificacao/conquistas/definicoes",
                         json={"conquistas": corpo["conquistas"]})
    assert salvar.status_code == 200, salvar.text
    assert len(salvar.json()["conquistas"]) == len(corpo["conquistas"])


def test_nao_cria_conquista_de_modulo_fora_do_plano(so_leitura, cliente):
    escola, *_ = so_leitura
    corpo = cliente.get(f"{API}/escolas/{escola.id}/gamificacao/conquistas/definicoes").json()
    nova = {"codigo": "", "nome": "Conquista Inventada", "indicador": "atividades",
            "limite": 5, "xp": 50, "raridade": "comum"}
    r = cliente.put(f"{API}/escolas/{escola.id}/gamificacao/conquistas/definicoes",
                    json={"conquistas": [*corpo["conquistas"], nova]})
    assert r.status_code == 400, r.text
    assert "Matemática" in r.json()["detail"] and "plano" in r.json()["detail"]
    # Trocar o critério de uma conquista de Leitura para o Matific também não vale.
    trocada = [{**c, "indicador": "estrelas", "plataforma": ""}
               if c["codigo"] == "primeira_leitura" else c for c in corpo["conquistas"]]
    r = cliente.put(f"{API}/escolas/{escola.id}/gamificacao/conquistas/definicoes",
                    json={"conquistas": trocada})
    assert r.status_code == 400, r.text


def test_escola_sem_rede_cria_conquista_de_matematica(escola_completa, cliente):
    escola = escola_completa["escola"]
    corpo = cliente.get(f"{API}/escolas/{escola.id}/gamificacao/conquistas/definicoes").json()
    assert corpo["plataformas_fora_do_plano"] == []
    nova = {"codigo": "", "nome": "Conquista Inventada", "indicador": "atividades",
            "limite": 5, "xp": 50, "raridade": "comum"}
    r = cliente.put(f"{API}/escolas/{escola.id}/gamificacao/conquistas/definicoes",
                    json={"conquistas": [*corpo["conquistas"], nova]})
    assert r.status_code == 200, r.text
