"""O cache do telão (painel público, sem login) não guarda uma montagem que começou
antes de uma invalidação (S_G_CARGA-2).

``painel_publico`` montava os dados e os gravava no cache sem conferir se houve
invalidação DURANTE a montagem. O arquivamento (e a exclusão, e as importações) chama
``invalidar_cache_painel`` depois do commit; se uma montagem tinha começado antes, ela
lia a criança ainda ativa e gravava esse resultado DEPOIS da invalidação, valendo por
``TTL_PAINEL_S`` (60 s) — no MESMO processo, mesmo com um worker só. ``_ids_visiveis``
(quem pode ter o perfil público aberto) tinha o mesmo padrão.

Agora cada invalidação avança a geração do cache da escola (e a global, quando é de
todas); a montagem anota a geração ANTES de ler o banco e só grava no cache se ela não
mudou. A resposta da própria montagem em andamento segue como está (já estava a
caminho); a seguinte monta de novo. Só a DURAÇÃO da montagem é simulada; o cache, a
invalidação e as rotas são o código real. Dados fictícios.
"""
import threading
from datetime import datetime

from fastapi.testclient import TestClient

from app.main import app
from app.models import Configuracao
from app.models.plataformas import Importacao, SnapshotElefante, SnapshotMatific
from app.routers import publico
from app.services import scoring

TOKEN = "tokenInventadoTelaoCorrida01"
URL = f"/api/v1/publico/{TOKEN}/painel"
COLETA = datetime(2026, 9, 10, 10, 0)


def _preparar(db, escola_completa):
    escola = escola_completa["escola"]
    imp = Importacao(escola_id=escola.id, plataforma="matific", tipo="seed", qtd_alunos=3)
    db.add(imp)
    db.flush()
    for k, a in enumerate(escola_completa["alunos"]):
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=a.id, importacao_id=imp.id,
                               data_referencia=COLETA, atividades=10 + 5 * k,
                               estrelas=20 + 7 * k, pontuacao_media=3.0))
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=a.id, importacao_id=imp.id,
                                data_referencia=COLETA, livros_unicos=2 + k,
                                tempo_leitura_min=30, questoes_tentativas=10,
                                questoes_acertos=6, livros_por_nivel={"D": 2 + k}))
    db.add(Configuracao(escola_id=escola.id, namespace="painel_publico", chave="valores",
                        valor={"ativo": True, "token": TOKEN, "anonimizar": True}))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    return escola


def _ids_no_ranking(resp) -> list[int]:
    assert resp.status_code == 200, resp.text
    return [item["aluno_id"] for item in resp.json()["ranking"]]


def _montagem_segura(monkeypatch, alvo: str):
    """Troca ``publico.<alvo>`` por uma versão que lê o banco e, na PRIMEIRA chamada,
    espera o sinal antes de devolver — o resto das idas ao banco em produção."""
    original = getattr(publico, alvo)
    leu, pode_seguir = threading.Event(), threading.Event()
    segurar = {"ativo": True}

    def _lenta(*a, **k):
        dados = original(*a, **k)
        if segurar["ativo"]:
            segurar["ativo"] = False
            leu.set()
            assert pode_seguir.wait(30)
        return dados

    monkeypatch.setattr(publico, alvo, _lenta)
    return leu, pode_seguir


def test_arquivar_durante_a_montagem_nao_deixa_a_crianca_no_cache_do_telao(
        db, escola_completa, cliente, monkeypatch):
    escola = _preparar(db, escola_completa)
    alvo = escola_completa["alunos"][0]
    publico_cli = TestClient(app)
    assert alvo.id in _ids_no_ranking(publico_cli.get(URL))   # antes: está no telão
    publico._cache_painel.clear()                              # o TTL venceu

    leu, pode_seguir = _montagem_segura(monkeypatch, "_dados_publicos")
    em_andamento: dict = {}
    t = threading.Thread(target=lambda: em_andamento.setdefault("r", publico_cli.get(URL)))
    t.start()
    try:
        assert leu.wait(30), "a montagem não chegou a ler o banco"
        # A coordenação arquiva a criança: commit + recálculo + invalidar_cache_painel.
        r = cliente.post(f"/api/v1/escolas/{escola.id}/alunos/acoes",
                         json={"acao": "arquivar", "aluno_ids": [alvo.id]})
        assert r.status_code == 200, r.text
    finally:
        pode_seguir.set()
        t.join(30)
    assert em_andamento["r"].status_code == 200

    depois = [alvo.id in _ids_no_ranking(publico_cli.get(URL)) for _ in range(2)]
    assert depois == [False, False], (
        "o telão sem login seguiu listando a criança ARQUIVADA depois de o arquivamento "
        "responder 200, no mesmo processo: a montagem em andamento gravou o cache "
        "depois da invalidação")


def test_invalidar_todas_as_escolas_durante_a_montagem_tambem_vale(
        db, escola_completa, monkeypatch):
    """``invalidar_cache_painel()`` sem escola (troca geral) também descarta a montagem
    que estava em andamento — e a seguinte volta a usar o cache normalmente."""
    escola = _preparar(db, escola_completa)
    publico_cli = TestClient(app)
    leu, pode_seguir = _montagem_segura(monkeypatch, "_dados_publicos")
    t = threading.Thread(target=lambda: publico_cli.get(URL))
    t.start()
    try:
        assert leu.wait(30)
        publico.invalidar_cache_painel()
    finally:
        pode_seguir.set()
        t.join(30)
    assert escola.id not in publico._cache_painel, "a montagem velha foi para o cache"
    assert publico_cli.get(URL).status_code == 200
    assert escola.id in publico._cache_painel, "a montagem sem corrida voltou a ser guardada"


def test_ids_visiveis_nao_guarda_conjunto_montado_antes_da_invalidacao(
        db, escola_completa, monkeypatch):
    """Quem pode ter o perfil público aberto (``_ids_visiveis``): o mesmo cuidado."""
    escola = _preparar(db, escola_completa)
    alvo = escola_completa["alunos"][0]
    leu, pode_seguir = _montagem_segura(monkeypatch, "_turmas_premiaveis")
    publico_cli = TestClient(app)
    t = threading.Thread(
        target=lambda: publico_cli.get(f"/api/v1/publico/{TOKEN}/alunos/{alvo.id}"))
    t.start()
    try:
        assert leu.wait(30)
        publico.invalidar_cache_painel(escola.id)
    finally:
        pode_seguir.set()
        t.join(30)
    assert escola.id not in publico._cache_visiveis, (
        "o conjunto montado antes da invalidação foi para o cache")
