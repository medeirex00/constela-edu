"""Quest — limite de tentativas do login infantil PERSISTENTE (quest_limites_acesso).

Achado da auditoria de 20/10/2026: o /quest/auth/quem e o /entrar limitavam
tentativas só na memória do processo — zerava no restart (todo deploy devolvia o
orçamento a quem estava sendo barrado) e não valia entre workers/réplicas.

"Reiniciar" e "outro worker" são simulados zerando a camada em memória: o que
sobra para barrar é só o banco.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.quest.models import QuestCredencialAluno, QuestLimiteAcesso
from app.quest.routers import auth as quest_auth
from app.quest.services import limites

QUEM = "/api/v1/quest/auth/quem"
ENTRAR = "/api/v1/quest/auth/entrar"


def _reiniciar_processo():
    """O que um restart (ou outro worker) enxerga: memória vazia."""
    for lim in quest_auth._DIMENSOES.values():
        lim._eventos.clear()


def _post(url, codigo, ip="203.0.113.10"):
    return TestClient(app).post(url, json={"codigo": codigo},
                                headers={"X-Forwarded-For": ip})


def _codigo_valido(cliente, db, escola_completa, indice=0) -> str:
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    r = cliente.post(f"/api/v1/escolas/{escola.id}/quest/turmas/{turma.id}/cartoes")
    assert r.status_code == 200, r.text
    db.expire_all()
    return db.execute(select(QuestCredencialAluno.codigo_login).where(
        QuestCredencialAluno.aluno_id == escola_completa["alunos"][indice].id)).scalar_one()


def test_bloqueio_por_codigo_sobrevive_ao_restart(db):
    for _ in range(8):
        assert _post(ENTRAR, "NAOEXISTE123").status_code == 401
    _reiniciar_processo()
    # A 9ª tentativa do MESMO código, num processo "novo": continua barrada.
    assert _post(ENTRAR, "NAOEXISTE123").status_code == 429


def test_contagem_soma_entre_workers(db):
    """Dois processos dividindo as tentativas: 4 num, 4 noutro = teto de 8."""
    for _ in range(4):
        assert _post(QUEM, "NAOEXISTE123").status_code == 401
    _reiniciar_processo()                      # "outro worker"
    for _ in range(4):
        assert _post(QUEM, "NAOEXISTE123").status_code == 401
    _reiniciar_processo()
    assert _post(QUEM, "NAOEXISTE123").status_code == 429


def test_enumeracao_por_ip_barrada_mesmo_trocando_de_worker(db):
    for i in range(50):
        if i % 10 == 0:
            _reiniciar_processo()
        assert _post(ENTRAR, f"NAOEXISTE{i:03d}").status_code == 401
    _reiniciar_processo()
    assert _post(ENTRAR, "NAOEXISTE999").status_code == 429


def test_ip_bloqueado_recebe_a_mesma_resposta_com_codigo_valido(cliente, db,
                                                                escola_completa):
    """Sem enumeração: depois do bloqueio, código VÁLIDO e inexistente recebem a
    MESMA resposta — o bloqueio é checado antes de procurar o código."""
    valido = _codigo_valido(cliente, db, escola_completa)
    for i in range(50):
        _post(QUEM, f"NAOEXISTE{i:03d}")
    _reiniciar_processo()
    r_valido, r_inexistente = _post(QUEM, valido), _post(QUEM, "NAOEXISTE999")
    assert r_valido.status_code == r_inexistente.status_code == 429
    assert r_valido.json() == r_inexistente.json()
    # Outro IP (outra escola) segue entrando normalmente.
    assert _post(QUEM, valido, ip="198.51.100.20").status_code == 200


def test_bloqueio_e_temporario(db, monkeypatch):
    for _ in range(8):
        _post(ENTRAR, "NAOEXISTE123")
    _reiniciar_processo()
    assert _post(ENTRAR, "NAOEXISTE123").status_code == 429

    depois = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
        seconds=quest_auth.limitador_codigo.janela_s + 1)
    monkeypatch.setattr(limites, "_agora", lambda: depois)
    _reiniciar_processo()
    # Passada a janela do (código, IP), a chave volta a valer e a contagem dela
    # recomeça do 1 (a do código sozinho, de janela maior, segue somando).
    assert _post(ENTRAR, "NAOEXISTE123").status_code == 401
    db.expire_all()
    por_chave = {linha.chave: linha.falhas
                 for linha in db.execute(select(QuestLimiteAcesso)).scalars()}
    assert por_chave[limites.chave("codigo_ip", "NAOEXISTE123|203.0.113.10")] == 1
    assert por_chave[limites.chave("codigo", "NAOEXISTE123")] == 9


def test_nem_codigo_nem_ip_ficam_em_texto_no_banco(db):
    _post(ENTRAR, "SOL314", ip="203.0.113.77")
    chaves = db.execute(select(QuestLimiteAcesso.chave)).scalars().all()
    assert chaves, "a tentativa tem de ter sido contada no banco"
    for chave in chaves:
        assert "SOL314" not in chave and "203.0.113.77" not in chave
        dimensao, _, digest = chave.partition(":")
        assert dimensao in {"codigo_ip", "codigo", "ip", "ip_falha", "global_falha"}
        assert len(digest) == 32


def test_teto_e_o_mesmo_nas_duas_camadas(db, monkeypatch):
    """O teto da camada persistente vem do limitador em memória: mudar um muda
    o outro (as duas camadas nunca divergem)."""
    monkeypatch.setattr(quest_auth.limitador_codigo, "max_tentativas", 3)
    for _ in range(3):
        assert _post(ENTRAR, "NAOEXISTE123").status_code == 401
    _reiniciar_processo()
    assert _post(ENTRAR, "NAOEXISTE123").status_code == 429


def test_login_certo_zera_os_contadores_da_conta(cliente, db, escola_completa):
    valido = _codigo_valido(cliente, db, escola_completa)
    chave_conta = limites.chave("codigo", valido)
    limites.registrar_falha(db, chave_conta, max_tentativas=20, janela_s=900)
    db.commit()
    assert _post(ENTRAR, valido).status_code == 200
    db.expire_all()
    assert db.execute(select(QuestLimiteAcesso)
                      .where(QuestLimiteAcesso.chave == chave_conta)).first() is None


def test_faxina_apaga_so_contador_vencido_e_sem_bloqueio(db):
    agora = datetime.now(timezone.utc).replace(tzinfo=None)
    velho = agora - timedelta(days=2)
    db.add_all([
        QuestLimiteAcesso(chave="ip:vencido", falhas=3, janela_inicio=velho,
                          atualizado_em=velho),
        QuestLimiteAcesso(chave="ip:bloqueado", falhas=50, janela_inicio=velho,
                          atualizado_em=velho, bloqueado_ate=agora + timedelta(hours=1)),
        QuestLimiteAcesso(chave="ip:recente", falhas=1, janela_inicio=agora,
                          atualizado_em=agora),
    ])
    db.commit()
    assert limites.faxina(db, agora) == 1
    db.commit()
    assert set(db.execute(select(QuestLimiteAcesso.chave)).scalars()) == {
        "ip:bloqueado", "ip:recente"}


# --- Concorrência real (PostgreSQL): o incremento não perde contagem -----------

@pytest.mark.postgres
def test_incremento_concorrente_nao_perde_tentativa():
    import os
    import threading

    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import sessionmaker

    url = os.environ.get("TEST_DATABASE_URL_PG")
    if not url:
        pytest.skip("defina TEST_DATABASE_URL_PG para rodar contra PostgreSQL real")
    if "test" not in (make_url(url).database or "").lower():
        pytest.skip("o nome do banco precisa conter 'test'")
    engine = create_engine(url, pool_size=10)
    tabela = QuestLimiteAcesso.__table__
    tabela.drop(engine, checkfirst=True)
    tabela.create(engine)
    Sessao = sessionmaker(bind=engine)
    chave = "codigo:concorrente"
    erros = []

    def trabalhador():
        try:
            for _ in range(5):
                with Sessao() as s:
                    limites.registrar_falha(s, chave, max_tentativas=1000, janela_s=900)
                    s.commit()
        except Exception as exc:  # noqa: BLE001 — o teste reporta qualquer falha
            erros.append(exc)

    threads = [threading.Thread(target=trabalhador) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    try:
        assert not erros, erros
        with Sessao() as s:
            linhas = s.execute(select(QuestLimiteAcesso)
                               .where(QuestLimiteAcesso.chave == chave)).scalars().all()
        assert len(linhas) == 1               # a corrida do 1º INSERT não duplicou
        assert linhas[0].falhas == 40         # 8 × 5: nenhuma tentativa perdida
    finally:
        tabela.drop(engine, checkfirst=True)
        engine.dispose()


# --- Faxina sob a linha global (PostgreSQL): sem deadlock entre escolas ----------

@pytest.mark.postgres
def test_faxina_sob_a_linha_global_nao_da_deadlock_entre_escolas(monkeypatch):
    """Revisão de integração do e97 (config-cifra-quest, provas 1 e 4, invertidas).

    Toda falha do /quem e do /entrar trava a linha ``global_falha`` até o commit, e a
    faxina sorteada (1%) roda na MESMA transação, logo depois dela. Com um DELETE
    simples, a falha da escola A (T1) segurava a linha global e esperava, no DELETE,
    uma linha velha da escola B que a falha concorrente de B (T2) acabou de atualizar;
    T2, por sua vez, esperava a linha global: o PostgreSQL abortava uma das duas
    (DeadlockDetected → 500 no login da criança). Agora a faxina só apaga as linhas
    vencidas que ninguém segura (FOR UPDATE SKIP LOCKED): T1 não espera ninguém, as
    duas falhas contam, e a linha velha sem dono continua sendo apagada."""
    import os
    import threading
    import time
    import types

    from sqlalchemy import create_engine, text, update
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import sessionmaker
    from starlette.requests import Request

    url = os.environ.get("TEST_DATABASE_URL_PG")
    if not url:
        pytest.skip("defina TEST_DATABASE_URL_PG para rodar contra PostgreSQL real")
    if "test" not in (make_url(url).database or "").lower():
        pytest.skip("o nome do banco precisa conter 'test'")

    def requisicao(ip: str) -> Request:
        return Request({"type": "http", "method": "POST", "path": "/", "headers": [],
                        "client": (ip, 1234), "query_string": b""})

    assert quest_auth._FALHA_CODIGO[-1] == "global_falha"   # o cenário do 401 real
    por_ip = tuple(d for d in quest_auth._FALHA_CODIGO if d != "global_falha")
    engine = create_engine(url, pool_size=6)
    tabela = QuestLimiteAcesso.__table__
    tabela.drop(engine, checkfirst=True)
    tabela.create(engine)
    Sessao = sessionmaker(bind=engine)
    # IPs de documentação (RFC 5737); códigos inventados.
    escola_a = quest_auth._Tentativa(requisicao("198.51.100.20"), "PALPITEA111")
    escola_b = quest_auth._Tentativa(requisicao("203.0.113.10"), "PALPITEB222")
    chave_global = escola_a._chave("global_falha")
    chave_orfa = limites.chave("ip", "192.0.2.99")
    erros: list = []
    try:
        # Antes: a linha global existe; as linhas da escola B estão paradas desde
        # sexta; e há uma linha velha que ninguém vai tocar (a faxina deve apagá-la).
        agora = limites._agora()
        velho = agora - timedelta(days=2)
        with Sessao() as s:
            quest_auth._Tentativa(requisicao("192.0.2.5"), "OUTRO333").contar(
                s, *quest_auth._FALHA_CODIGO)
            escola_b.contar(s, *por_ip)
            s.add(QuestLimiteAcesso(chave=chave_orfa, falhas=1, janela_inicio=velho,
                                    atualizado_em=velho))
            s.commit()
            s.execute(update(QuestLimiteAcesso)
                      .where(QuestLimiteAcesso.chave.in_(
                          [escola_b._chave(d) for d in por_ip]))
                      .values(atualizado_em=velho, janela_inicio=velho)
                      .execution_options(synchronize_session=False))
            s.commit()
            global_antes = s.execute(select(QuestLimiteAcesso.falhas).where(
                QuestLimiteAcesso.chave == chave_global)).scalar_one()
        _reiniciar_processo()

        # A faxina é sorteada SÓ na chamada da linha global de T1 (a última).
        chamadas_t1 = {"n": 0}

        def sorteio():
            if threading.current_thread().name == "T1":
                chamadas_t1["n"] += 1
                return 0.0 if chamadas_t1["n"] == len(quest_auth._FALHA_CODIGO) else 1.0
            return 1.0

        monkeypatch.setattr(limites, "random", types.SimpleNamespace(random=sorteio))

        # T2 (escola B, 401): conta as dimensões por IP — trava as linhas VELHAS.
        s2 = Sessao()
        escola_b.contar(s2, *por_ip)

        def t1():
            s1 = Sessao()
            try:
                escola_a.contar(s1, *quest_auth._FALHA_CODIGO)
                s1.commit()
            except Exception as exc:  # noqa: BLE001 — o teste reporta qualquer falha
                erros.append(("T1", exc))
                s1.rollback()
            finally:
                s1.close()

        th = threading.Thread(target=t1, name="T1")
        th.start()
        # T1 termina sozinha (não espera linha de ninguém) ou fica presa num lock.
        estado, fim = "nenhum", time.monotonic() + 30
        while time.monotonic() < fim:
            if not th.is_alive():
                estado = "terminou"
                break
            with engine.connect() as c:
                esperando = c.execute(text(
                    "SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock' "
                    "AND datname = current_database()")).scalar()
            if esperando:
                estado = "esperou_lock"
                break
            time.sleep(0.05)
        try:
            escola_b.contar(s2, "global_falha")     # T2 chega à linha global
            s2.commit()
        except Exception as exc:  # noqa: BLE001
            erros.append(("T2", exc))
            s2.rollback()
        finally:
            s2.close()
        th.join(30)
        assert not th.is_alive()
        assert erros == [], [(q, str(e).splitlines()[0][:160]) for q, e in erros]
        assert estado == "terminou"                 # a faxina de T1 não esperou T2
        assert chamadas_t1["n"] == len(quest_auth._FALHA_CODIGO)
        with Sessao() as s:
            chaves = set(s.execute(select(QuestLimiteAcesso.chave)).scalars())
            global_depois = s.execute(select(QuestLimiteAcesso.falhas).where(
                QuestLimiteAcesso.chave == chave_global)).scalar_one()
        assert global_depois == global_antes + 2    # as duas falhas contaram
        assert chave_orfa not in chaves             # a velha sem dono foi apagada
        # As linhas de B que T2 segurava ficaram para a próxima faxina (e T2 as renovou).
        assert {escola_b._chave(d) for d in por_ip} <= chaves
    finally:
        tabela.drop(engine, checkfirst=True)
        engine.dispose()
