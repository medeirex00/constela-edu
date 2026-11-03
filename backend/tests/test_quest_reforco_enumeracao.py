"""Quest — reforço contra a enumeração do código de login infantil (revisão e97).

Achado verificado (dimensão "exposição"): o código PALAVRA+NNN (~1,3×10^5) é a
credencial e o único freio à varredura era o teto de falhas POR IP. Aqui ficam as
regressões do reforço estrutural (o formato e o portão QUEST_ALUNO_HABILITADO são
decisão do dono e não mudam):

- IPv6 conta pela rede /64 nas chaves de limite por IP;
- o 403 de aluno inativo conta como falha por IP (deixa de ser oráculo grátis),
  uma vez por (código, IP) na janela — o NAT da escola não trava por causa de
  crianças inativas insistindo no próprio cartão;
- teto GLOBAL de falhas (todos os IPs somados) no /quem e no /entrar, com log de
  alerta; o QR fica fora dele.

Todos os nomes, códigos e IPs são fictícios (alunos "Sint<n> Teste"; faixas de
documentação 2001:db8::/32, 198.51.100.0/24 e 203.0.113.0/24; rede privada 10/8).
"""
import logging
import random
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from app.core.rate_limit import rede_para_limite
from app.main import app
from app.models import Aluno, Matricula
from app.quest.config import ConfigQuest
from app.quest.models import QuestCredencialAluno, QuestLimiteAcesso
from app.quest.routers import auth as quest_auth
from app.quest.services import credenciais as svc_cred
from app.quest.services import limites

QUEM = "/api/v1/quest/auth/quem"
ENTRAR = "/api/v1/quest/auth/entrar"
ENTRAR_QR = "/api/v1/quest/auth/entrar-qr"


def _reiniciar_processo():
    """O que um restart (ou outro worker) enxerga: memória vazia, só o banco."""
    for lim in quest_auth._DIMENSOES.values():
        lim._eventos.clear()


def _post(url, codigo, ip="203.0.113.10"):
    return TestClient(app).post(url, json={"codigo": codigo},
                                headers={"X-Forwarded-For": ip})


def _credenciais(cliente, db, escola_completa) -> list[QuestCredencialAluno]:
    """Gera os cartões da turma fictícia (pela rota do professor) e devolve as
    credenciais na ordem dos alunos da fixture."""
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    r = cliente.post(f"/api/v1/escolas/{escola.id}/quest/turmas/{turma.id}/cartoes")
    assert r.status_code == 200, r.text
    db.expire_all()
    return [db.execute(select(QuestCredencialAluno)
                       .where(QuestCredencialAluno.aluno_id == aluno.id)).scalar_one()
            for aluno in escola_completa["alunos"]]


def _inativar(db, aluno_id, status="transferido"):
    db.get(Aluno, aluno_id).status = status
    db.commit()


def _falhas_no_banco(db, dimensao, valor) -> int:
    db.expire_all()
    return db.execute(select(QuestLimiteAcesso.falhas).where(
        QuestLimiteAcesso.chave == limites.chave(dimensao, valor))).scalar() or 0


# ---------------------------------------------------------------------------
# (b) IPv6 agrupado por /64 nas chaves de limite por IP
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("entrada,esperado", [
    ("2001:db8:1:2:aaaa::1", "2001:db8:1:2::/64"),
    ("2001:DB8:1:2:ffff:1:2:3", "2001:db8:1:2::/64"),    # maiúsculas, mesmo /64
    ("[2001:db8:1:2::9]:443", "2001:db8:1:2::/64"),      # com colchetes e porta
    ("fe80::1%eth0", "fe80::/64"),                       # zona descartada
    ("2001:db8:1:3::1", "2001:db8:1:3::/64"),            # outro /64
    ("::ffff:203.0.113.5", "203.0.113.5"),               # IPv4 mapeado = o IPv4
    ("203.0.113.5", "203.0.113.5"),                      # IPv4 inalterado
    ("203.0.113.5:8080", "203.0.113.5"),                 # IPv4 sem a porta
    (" 203.0.113.5 ", "203.0.113.5"),
    ("desconhecido", "desconhecido"),                    # não-IP passa intacto
    ("testclient", "testclient"),
    ("", ""),
])
def test_rede_para_limite(entrada, esperado):
    assert rede_para_limite(entrada) == esperado


def test_rede_para_limite_respeita_o_prefixo():
    assert rede_para_limite("2001:db8:1:2::1", 48) == "2001:db8:1::/48"
    assert rede_para_limite("2001:db8:1:2::1", 128) == "2001:db8:1:2::1/128"
    assert rede_para_limite("203.0.113.5", 48) == "203.0.113.5"


def test_prefixo_ipv6_tem_padrao_seguro_e_faixa_validada():
    assert ConfigQuest(_env_file=None).QUEST_LIMITE_PREFIXO_IPV6 == 64
    for invalido in (8, 31, 129):
        with pytest.raises(ValidationError):
            ConfigQuest(_env_file=None, QUEST_LIMITE_PREFIXO_IPV6=invalido)


def test_ipv6_do_mesmo_64_divide_o_teto_de_falhas_por_ip(db):
    """A varredura que troca de ENDEREÇO a cada palpite dentro do próprio /64
    gasta um orçamento só (antes: cada endereço era um IP novo)."""
    for i in range(quest_auth.limitador_ip_falha.max_tentativas):
        r = _post(ENTRAR, f"NAOEXISTE{i:03d}", ip=f"2001:db8:aa:1::{i + 1:x}")
        assert r.status_code == 401
    assert _post(ENTRAR, "NAOEXISTE999",
                 ip="2001:db8:aa:1:ffff:ffff:ffff:fffe").status_code == 429
    # Persistente: num processo "novo" o /64 continua barrado.
    _reiniciar_processo()
    assert _post(QUEM, "NAOEXISTE998", ip="2001:db8:aa:1::abcd").status_code == 429
    # Outro /64 (outro assinante) segue com o orçamento dele.
    assert _post(ENTRAR, "NAOEXISTE999", ip="2001:db8:aa:2::1").status_code == 401


def test_ipv6_do_mesmo_64_divide_o_teto_por_codigo_e_ip(db):
    teto = quest_auth.limitador_codigo.max_tentativas
    for i in range(teto):
        assert _post(ENTRAR, "NAOEXISTE123",
                     ip=f"2001:db8:bb:1::{i + 1:x}").status_code == 401
    assert _post(ENTRAR, "NAOEXISTE123", ip="2001:db8:bb:1::ffff").status_code == 429


def test_ipv4_continua_por_endereco(db):
    """Sem mudança para IPv4: o vizinho de /24 não divide o orçamento."""
    for i in range(quest_auth.limitador_ip_falha.max_tentativas):
        assert _post(ENTRAR, f"NAOEXISTE{i:03d}", ip="198.51.100.7").status_code == 401
    assert _post(ENTRAR, "NAOEXISTE999", ip="198.51.100.7").status_code == 429
    assert _post(ENTRAR, "NAOEXISTE999", ip="198.51.100.8").status_code == 401


# ---------------------------------------------------------------------------
# (c) o 403 de aluno inativo conta como falha por IP
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url", [QUEM, ENTRAR])
def test_inativo_conta_no_teto_de_falhas_por_ip(cliente, db, escola_completa, url):
    """Inverso da prova verif_exposicao (2d): antes, 30 respostas 403 seguidas
    não gastavam nada e a 50ª falha ainda dava 401. Agora o 403 é uma falha."""
    creds = _credenciais(cliente, db, escola_completa)
    _inativar(db, escola_completa["alunos"][0].id)
    ip = "198.51.100.77"
    for i in range(quest_auth.limitador_ip_falha.max_tentativas - 1):
        assert _post(url, f"ZZZ{100 + i}", ip=ip).status_code == 401
    inativo = _post(url, creds[0].codigo_login, ip=ip)
    assert inativo.status_code == 403
    assert inativo.json()["detail"] == quest_auth.ERRO_INATIVO   # mensagem própria
    # O 403 completou o teto: até o código VÁLIDO de uma colega é barrado agora.
    assert _post(url, creds[1].codigo_login, ip=ip).status_code == 429
    _reiniciar_processo()                                   # vale no banco também
    assert _post(url, "ZZZ999", ip=ip).status_code == 429
    assert _falhas_no_banco(db, "ip_falha", ip) == quest_auth.limitador_ip_falha.max_tentativas


def test_crianca_inativa_insistindo_nao_trava_a_escola(cliente, db, escola_completa):
    """NAT da escola: a criança transferida que toca 20 vezes no próprio cartão
    esbarra no teto do (código, IP), mas só o PRIMEIRO toque conta no orçamento de
    falhas do IP e no global — os colegas no mesmo IP seguem entrando."""
    creds = _credenciais(cliente, db, escola_completa)
    _inativar(db, escola_completa["alunos"][0].id, status="arquivado")
    ip = "203.0.113.50"
    teto_codigo_ip = quest_auth.limitador_codigo.max_tentativas
    respostas = [_post(ENTRAR, creds[0].codigo_login, ip=ip) for _ in range(20)]
    assert [r.status_code for r in respostas] == (
        [403] * teto_codigo_ip + [429] * (20 - teto_codigo_ip))
    assert respostas[-1].json()["detail"] == quest_auth.ERRO_MUITAS
    codigo_ip = f"{svc_cred.normalizar_codigo(creds[0].codigo_login)}|{ip}"
    assert _falhas_no_banco(db, "codigo_ip", codigo_ip) == teto_codigo_ip
    assert _falhas_no_banco(db, "ip_falha", ip) == 1
    assert _falhas_globais(db) == 1
    # O teto do CÓDIGO sozinho não foi tocado (o cartão não entra mesmo).
    assert _falhas_no_banco(db, "codigo", creds[0].codigo_login) == 0
    assert _post(ENTRAR, creds[1].codigo_login, ip=ip).status_code == 200
    assert _post(QUEM, creds[2].codigo_login, ip=ip).status_code == 200


def _inativar_varios(db, credenciais, status="transferido"):
    for c in credenciais:
        db.get(Aluno, c.aluno_id).status = status
    db.commit()


def _post_qr(qr_token, ip):
    return TestClient(app).post(ENTRAR_QR, json={"qr_token": qr_token},
                                headers={"X-Forwarded-For": ip})


def test_sete_criancas_inativas_insistindo_nao_travam_a_sala(db, escola_completa):
    """Resíduo da revisão e97: atrás do MESMO NAT, 7 crianças inativas tocando 8
    vezes cada (56 respostas 403, acima do teto 50 do IP) travavam a sala inteira,
    inclusive o QR da colega ativa. Agora cada cartão inativo conta UMA vez no teto
    do IP e no global; o limite por (código, IP) continua valendo."""
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    creds = _rede_sintetica(db, escola, turma, 5)      # 3 da fixture + 5 = 8 cartões
    assert len(creds) == 8
    inativas, ativa = creds[:7], creds[7]
    _inativar_varios(db, inativas)
    ip = "203.0.113.70"
    toques = 8
    respostas = [_post(QUEM if n % 2 else ENTRAR, c.codigo_login, ip=ip).status_code
                 for c in inativas for n in range(toques)]
    assert respostas == [403] * (len(inativas) * toques)
    assert _falhas_no_banco(db, "ip_falha", ip) == len(inativas)
    assert _falhas_globais(db) == len(inativas)
    # A colega ativa entra pelo código (as duas etapas) e pelo QR...
    assert _post(QUEM, ativa.codigo_login, ip=ip).status_code == 200
    assert _post(ENTRAR, ativa.codigo_login, ip=ip).status_code == 200
    assert _post_qr(ativa.qr_token, ip).status_code == 200
    # ...também num processo "novo" (só o banco).
    _reiniciar_processo()
    assert _post(ENTRAR, ativa.codigo_login, ip=ip).status_code == 200
    # O limite por (código, IP) continua: o 9º toque de um cartão inativo é 429.
    nono = _post(ENTRAR, inativas[0].codigo_login, ip=ip)
    assert nono.status_code == 429
    assert nono.json()["detail"] == quest_auth.ERRO_MUITAS


def test_varrer_60_codigos_inativos_diferentes_esgota_o_teto_do_ip(db, escola_completa):
    """O outro lado da calibragem: quem varre códigos inativos DIFERENTES do mesmo
    IP continua pagando 1 por código, como no código inexistente — no 50º o IP
    trava e até a colega ativa (código e QR) espera a janela."""
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    creds = _rede_sintetica(db, escola, turma, 58)     # 3 da fixture + 58 = 61
    assert len(creds) == 61
    inativas, ativa = creds[:60], creds[60]
    _inativar_varios(db, inativas)
    ip = "198.51.100.90"
    teto = quest_auth.limitador_ip_falha.max_tentativas
    respostas = [_post(QUEM, c.codigo_login, ip=ip).status_code for c in inativas]
    assert respostas == [403] * teto + [429] * (len(inativas) - teto)
    assert _falhas_no_banco(db, "ip_falha", ip) == teto
    assert _post(ENTRAR, ativa.codigo_login, ip=ip).status_code == 429
    assert _post_qr(ativa.qr_token, ip).status_code == 429
    _reiniciar_processo()                                   # vale no banco também
    assert _post(QUEM, ativa.codigo_login, ip=ip).status_code == 429
    # Outro IP segue com o orçamento dele.
    assert _post(ENTRAR, ativa.codigo_login, ip="198.51.100.91").status_code == 200


@pytest.mark.postgres
def test_inativo_simultaneo_do_mesmo_cartao_conta_uma_vez_no_ip():
    """Corrida real (PostgreSQL): 8 toques SIMULTÂNEOS do mesmo cartão inativo no
    mesmo IP, cada um numa transação — só UMA vê o 1 do (código, IP) e conta no
    teto do IP e no global."""
    import os
    import threading
    from types import SimpleNamespace

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
    ip, conta, n = "203.0.113.99", "GATOFICTICIO123", 8
    pedido = SimpleNamespace(headers={}, client=SimpleNamespace(host=ip))
    largada = threading.Barrier(n)
    erros = []

    def toque():
        try:
            tentativa = quest_auth._Tentativa(pedido, conta)
            largada.wait()
            with Sessao() as s:
                tentativa.contar_inativo(s)
        except Exception as exc:  # noqa: BLE001 — o teste reporta qualquer falha
            erros.append(exc)

    threads = [threading.Thread(target=toque) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    try:
        assert not erros, erros
        with Sessao() as s:
            def falhas(dimensao, valor):
                return s.execute(select(QuestLimiteAcesso.falhas).where(
                    QuestLimiteAcesso.chave == limites.chave(dimensao, valor))).scalar()
            assert falhas("codigo_ip", f"{conta}|{ip}") == n   # todo toque conta aqui
            assert falhas("ip_falha", ip) == 1
            assert falhas("global_falha", quest_auth._GLOBAL) == 1
        assert len(quest_auth.limitador_ip_falha._eventos[ip]) == 1   # memória igual
    finally:
        tabela.drop(engine, checkfirst=True)
        engine.dispose()


# ---------------------------------------------------------------------------
# (a) teto GLOBAL de falhas, somando todos os IPs
# ---------------------------------------------------------------------------

def _rede_sintetica(db, escola, turma, n) -> list[QuestCredencialAluno]:
    """n alunos fictícios ativos na turma, cada um com credencial do Quest."""
    for i in range(n):
        aluno = Aluno(escola_id=escola.id, nome=f"Sint{i} Teste")
        db.add(aluno)
        db.flush()
        db.add(Matricula(escola_id=escola.id, aluno_id=aluno.id, turma_id=turma.id,
                         ano_letivo=2026))
    db.flush()
    creds = svc_cred.garantir_credenciais_turma(db, escola.id, turma)
    db.commit()
    return [c["credencial"] for c in creds]


def _alertas(caplog):
    return [r for r in caplog.records
            if getattr(r, "evento", None) == "quest.limite_global_atingido"]


def _falhas_globais(db) -> int:
    return _falhas_no_banco(db, "global_falha", quest_auth._GLOBAL)


def test_teto_global_tem_padrao_seguro_e_faixa_validada():
    cfg = ConfigQuest(_env_file=None)
    assert cfg.QUEST_LIMITE_GLOBAL_FALHAS == 400
    assert cfg.QUEST_LIMITE_GLOBAL_JANELA_S == 300
    for campo, invalido in (("QUEST_LIMITE_GLOBAL_FALHAS", 0),
                            ("QUEST_LIMITE_GLOBAL_JANELA_S", 30),
                            ("QUEST_LIMITE_GLOBAL_JANELA_S", 7200)):
        with pytest.raises(ValidationError):
            ConfigQuest(_env_file=None, **{campo: invalido})


def test_varredura_cega_distribuida_recebe_429_global_antes_de_500_falhas(
        db, escola_completa, caplog):
    """Inverso da prova verif_exposicao/test_prova_2 (2b): o atacante não sabe
    nada, chuta PALAVRA+NNN ao acaso sobre uma rede com muitas credenciais e troca
    de IP a cada 45 falhas (abaixo do teto por IP). Antes: 2.000 palpites e
    nenhum 429. Agora o teto global corta a varredura na falha nº
    QUEST_LIMITE_GLOBAL_FALHAS (padrão 400, abaixo de 500)."""
    caplog.set_level(logging.WARNING, logger="constela.quest")
    teto = quest_auth.limitador_global_falha.max_tentativas
    assert teto < 500
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    creds = _rede_sintetica(db, escola, turma, 300)
    sorteio = random.Random(20261024)
    anon = TestClient(app)
    falhas = falhas_ip = ip_n = 0
    primeiro_429 = None
    for n in range(2000):
        if falhas_ip >= 45:
            ip_n, falhas_ip = ip_n + 1, 0
        palpite = (f"{sorteio.choice(svc_cred._PALAVRAS_CODIGO)}"
                   f"{sorteio.randrange(100, 1000)}")
        r = anon.post(QUEM, json={"codigo": palpite},
                      headers={"X-Forwarded-For": f"10.0.{ip_n}.7"})
        if r.status_code == 429:
            primeiro_429 = n
            break
        assert r.status_code in (200, 401)
        if r.status_code == 401:
            falhas += 1
            falhas_ip += 1
    assert primeiro_429 is not None, "a varredura distribuída não pode correr solta"
    assert falhas == teto
    assert ip_n + 1 >= teto // 45      # vários IPs, nenhum chegou ao teto por IP

    # É o teto GLOBAL: um IP nunca visto, com código VÁLIDO, recebe a mesma
    # resposta de um código inexistente (sem oráculo), no /quem e no /entrar,
    # e também num processo "novo" (o bloqueio está no banco).
    valido = creds[0].codigo_login
    novo = {"X-Forwarded-For": "198.51.100.200"}
    r_valido = anon.post(QUEM, json={"codigo": valido}, headers=novo)
    r_inexistente = anon.post(QUEM, json={"codigo": "ZZZ999"}, headers=novo)
    assert r_valido.status_code == r_inexistente.status_code == 429
    assert r_valido.json() == r_inexistente.json()
    assert r_valido.json()["detail"] == quest_auth.ERRO_MUITAS
    assert anon.post(ENTRAR, json={"codigo": valido}, headers=novo).status_code == 429
    _reiniciar_processo()
    assert anon.post(ENTRAR, json={"codigo": valido}, headers=novo).status_code == 429
    assert _falhas_globais(db) == teto          # os 429 não realimentam o contador

    # O QR do cartão segue entrando: é a porta das crianças durante o bloqueio.
    qr = anon.post(ENTRAR_QR, json={"qr_token": creds[0].qr_token}, headers=novo)
    assert qr.status_code == 200, qr.text

    # UM alerta estruturado, sem IP nem código.
    alertas = _alertas(caplog)
    assert len(alertas) == 1
    assert alertas[0].levelno == logging.WARNING
    assert alertas[0].teto == teto and alertas[0].falhas_na_janela == teto
    assert alertas[0].janela_s == quest_auth.limitador_global_falha.janela_s
    conteudo = repr({k: v for k, v in vars(alertas[0]).items()
                     if k not in ("pathname", "filename", "module")})
    assert valido not in conteudo and "10.0." not in conteudo


def test_teto_global_soma_os_ips_conta_inativo_e_ignora_login_certo(
        cliente, db, escola_completa, monkeypatch):
    monkeypatch.setattr(quest_auth.limitador_global_falha, "max_tentativas", 4)
    creds = _credenciais(cliente, db, escola_completa)
    _inativar(db, escola_completa["alunos"][2].id)
    # Login certo não conta no global (5 entradas, de IPs distintos).
    for i in range(5):
        assert _post(ENTRAR, creds[0].codigo_login,
                     ip=f"203.0.113.{i + 1}").status_code == 200
    assert _falhas_globais(db) == 0
    # 3 códigos inexistentes de 3 IPs + 1 inativo de um 4º IP = 4 falhas globais,
    # cada IP com 1 só (longe do teto por IP).
    assert _post(QUEM, "ZZZ101", ip="198.51.100.1").status_code == 401
    assert _post(ENTRAR, "ZZZ102", ip="198.51.100.2").status_code == 401
    assert _post(QUEM, "ZZZ103", ip="198.51.100.3").status_code == 401
    assert _post(ENTRAR, creds[2].codigo_login, ip="198.51.100.4").status_code == 403
    assert _falhas_globais(db) == 4
    for url in (QUEM, ENTRAR):
        assert _post(url, creds[1].codigo_login, ip="198.51.100.5").status_code == 429
    qr = TestClient(app).post(ENTRAR_QR, json={"qr_token": creds[1].qr_token},
                              headers={"X-Forwarded-For": "198.51.100.5"})
    assert qr.status_code == 200, qr.text


def test_falha_de_qr_nao_conta_no_teto_global(db):
    for i in range(5):
        r = TestClient(app).post(ENTRAR_QR, json={"qr_token": f"{'x' * 24}{i}"},
                                 headers={"X-Forwarded-For": f"198.51.100.{60 + i}"})
        assert r.status_code == 401
    assert _falhas_globais(db) == 0


def test_bloqueio_global_e_temporario(cliente, db, escola_completa, monkeypatch):
    monkeypatch.setattr(quest_auth.limitador_global_falha, "max_tentativas", 3)
    creds = _credenciais(cliente, db, escola_completa)
    for i in range(3):
        assert _post(QUEM, f"ZZZ{110 + i}", ip=f"198.51.100.{10 + i}").status_code == 401
    for i in range(10):
        assert _post(ENTRAR, creds[0].codigo_login,
                     ip=f"198.51.100.{30 + i}").status_code == 429
    assert _falhas_globais(db) == 3

    depois = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
        seconds=quest_auth.limitador_global_falha.janela_s + 1)
    monkeypatch.setattr(limites, "_agora", lambda: depois)
    _reiniciar_processo()          # a camada em memória também já teria esvaziado
    assert _post(ENTRAR, creds[0].codigo_login, ip="198.51.100.50").status_code == 200
    # Janela nova: a contagem global recomeça do 1.
    assert _post(QUEM, "ZZZ199", ip="198.51.100.51").status_code == 401
    assert _falhas_globais(db) == 1
