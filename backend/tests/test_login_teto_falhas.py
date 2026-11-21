"""Teto de FALHAS por IP e teto GLOBAL do /auth/login (auditoria de segurança de
31/10, achado 16), e a quem a Secretaria pede um link novo (achado 18).

Antes: o login do Edu só tinha os limites por (conta, IP) — 8 em 5 min — e por
conta — 20 em 15 min. Um único IP testava poucas senhas em TODAS as contas da rede
(pulverização) sem nunca ver um 429, e a soma de vários IPs também não tinha teto.
Agora há um teto de falhas por IP (50 em 5 min, IPv6 agrupado em /64) conferido
ANTES de procurar a conta, e um teto GLOBAL com alerta no log — os dois também no
banco (a tabela de limites do Quest, com dimensões próprias do Edu), valendo entre
workers e depois de um reinício.

Os hashes das contas de teste usam bcrypt com custo 4 só para o teste andar
rápido: a lógica dos limitadores não depende do custo do hash.
"""
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from passlib.hash import bcrypt as bcrypt_rapido
from pydantic import ValidationError
from sqlalchemy import event, select

from app.core import rate_limit
from app.core.config import BASE_DIR, Settings
from app.core.security import hash_token
from app.main import app
from app.models import LogAuditoria, Rede, TokenResetSenha, Usuario
from app.quest.models import QuestLimiteAcesso
from app.routers import auth as auth_router

URL = "/api/v1/auth/login"
SENHA = "Pulveriza#Certa2026"
ERRADA = "azul-cedro-duna-10"
IP = "198.51.100.77"


def _contas(db, escola, n: int) -> list[str]:
    """n professores fictícios com a mesma senha conhecida; devolve os e-mails."""
    h = bcrypt_rapido.using(rounds=4).hash(SENHA)
    emails = [f"pulv{i}@teste.local" for i in range(n)]
    for i, email in enumerate(emails):
        db.add(Usuario(escola_id=escola.id, nome=f"Prof Pulv {i}", email=email,
                       username=f"ProfPulv{i}", senha_hash=h, cargo="professor"))
    db.commit()
    return emails


def _login(cli: TestClient, usuario: str, senha: str, ip: str = IP):
    return cli.post(URL, data={"username": usuario, "password": senha},
                    headers={"X-Forwarded-For": ip})


def _reiniciar_processo() -> None:
    """Zera TODA a memória dos limitadores do login (= outro worker ou reinício)."""
    for lim in (rate_limit.limitador_login, rate_limit.limitador_conta,
                rate_limit.limitador_ip_falha_login,
                rate_limit.limitador_global_falha_login,
                rate_limit.alerta_global_login):
        lim._eventos.clear()


def _chaves_do_edu(db) -> list[QuestLimiteAcesso]:
    return db.execute(select(QuestLimiteAcesso).where(
        QuestLimiteAcesso.chave.like("edu_login_%"))).scalars().all()


def test_tetos_novos_tem_os_valores_pedidos_e_os_antigos_nao_mudam():
    assert (rate_limit.limitador_ip_falha_login.max_tentativas,
            rate_limit.limitador_ip_falha_login.janela_s) == (50, 300)
    assert (rate_limit.limitador_global_falha_login.max_tentativas,
            rate_limit.limitador_global_falha_login.janela_s) == (400, 300)
    # Os limites que já existiam ficam como estavam.
    assert (rate_limit.limitador_login.max_tentativas,
            rate_limit.limitador_login.janela_s) == (8, 300)
    assert (rate_limit.limitador_conta.max_tentativas,
            rate_limit.limitador_conta.janela_s) == (20, 900)


def test_um_ip_pulverizando_senhas_em_muitas_contas_recebe_429(db, escola_completa):
    """O cenário da auditoria, com o teto REAL (50): uma senha errada em cada uma
    de 50 contas diferentes, do mesmo IP. Antes eram 50 respostas 401 e a 51ª
    tentativa (senha certa de outra conta) entrava com 200."""
    emails = _contas(db, escola_completa["escola"], 52)
    cli = TestClient(app)
    codigos = [_login(cli, email, ERRADA).status_code for email in emails[:50]]
    assert codigos == [401] * 50     # cada conta ficou longe do próprio teto

    certo = _login(cli, emails[50], SENHA)
    assert certo.status_code == 429, certo.text
    assert certo.json()["detail"].startswith("Muitas tentativas. Aguarde ")
    # Mesma resposta para conta inexistente: sem oráculo de enumeração.
    inexistente = _login(cli, "ninguem.aqui@teste.local", ERRADA)
    assert inexistente.status_code == 429
    assert inexistente.json() == certo.json()

    # O teto é do IP: outro IP entra normalmente na mesma conta.
    assert _login(cli, emails[50], SENHA, ip="203.0.113.50").status_code == 200

    bloqueios = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "login.bloqueado")).scalars().all()
    assert {b.detalhes["motivo"] for b in bloqueios} == {"teto_ip"}
    assert all(b.detalhes["ip"] == "198.51.x.x" for b in bloqueios)  # mascarado


def test_teto_do_ip_e_conferido_antes_de_buscar_a_conta(db, escola_completa,
                                                       monkeypatch):
    monkeypatch.setattr(rate_limit.limitador_ip_falha_login, "max_tentativas", 3)
    emails = _contas(db, escola_completa["escola"], 4)
    cli = TestClient(app)
    for email in emails[:3]:
        assert _login(cli, email, ERRADA).status_code == 401

    consultas: list[str] = []

    def _anotar(conn, cursor, sql, params, context, executemany):
        consultas.append(sql.lower())

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", _anotar)
    try:
        r = _login(cli, emails[3], SENHA)
    finally:
        event.remove(engine, "before_cursor_execute", _anotar)
    assert r.status_code == 429
    assert not [s for s in consultas if "from usuarios" in s], consultas


def test_ipv6_conta_pela_rede_64(db, escola_completa, monkeypatch):
    """Trocar de endereço dentro do mesmo /64 não renova o orçamento do IP."""
    monkeypatch.setattr(rate_limit.limitador_ip_falha_login, "max_tentativas", 4)
    emails = _contas(db, escola_completa["escola"], 6)
    cli = TestClient(app)
    for i, email in enumerate(emails[:4], start=1):
        assert _login(cli, email, ERRADA, ip=f"2001:db8:abcd:12::{i}").status_code == 401
    assert _login(cli, emails[4], SENHA,
                  ip="2001:db8:abcd:12:ffff:ffff:ffff:fffe").status_code == 429
    # Outro /64 é outro cliente.
    assert _login(cli, emails[4], SENHA, ip="2001:db8:abcd:13::1").status_code == 200


def test_teto_do_ip_vale_entre_workers_e_depois_de_reiniciar(db, escola_completa,
                                                            monkeypatch):
    """A contagem fica no banco: falhas vistas por processos diferentes somam, e o
    bloqueio sobrevive à memória zerada. O IP não vai em texto para o banco, e o
    429 não realimenta o contador."""
    monkeypatch.setattr(rate_limit.limitador_ip_falha_login, "max_tentativas", 3)
    emails = _contas(db, escola_completa["escola"], 5)
    cli = TestClient(app)
    for email in emails[:3]:
        assert _login(cli, email, ERRADA).status_code == 401
        _reiniciar_processo()              # cada falha num "worker" diferente
    assert _login(cli, emails[3], SENHA).status_code == 429
    _reiniciar_processo()
    assert _login(cli, emails[4], SENHA).status_code == 429

    linhas = _chaves_do_edu(db)
    por_dimensao = {linha.chave.split(":", 1)[0]: linha for linha in linhas}
    assert set(por_dimensao) == {"edu_login_ip_falha", "edu_login_global_falha"}
    assert por_dimensao["edu_login_ip_falha"].falhas == 3      # os 429 não somam
    assert por_dimensao["edu_login_ip_falha"].bloqueado_ate is not None
    assert all(IP not in linha.chave and "198.51" not in linha.chave
               for linha in linhas)


def test_login_certo_nao_soma_nem_zera_o_teto_do_ip(db, escola_completa, monkeypatch):
    monkeypatch.setattr(rate_limit.limitador_ip_falha_login, "max_tentativas", 3)
    emails = _contas(db, escola_completa["escola"], 4)
    cli = TestClient(app)
    for _ in range(5):                                   # acertos não contam
        assert _login(cli, emails[0], SENHA).status_code == 200
    assert _login(cli, emails[1], ERRADA).status_code == 401
    assert _login(cli, emails[2], ERRADA).status_code == 401
    assert _login(cli, emails[0], SENHA).status_code == 200   # não "lava" o IP
    assert _login(cli, emails[3], ERRADA).status_code == 401  # 3ª falha do IP
    assert _login(cli, emails[0], SENHA).status_code == 429


def _alertas(caplog):
    return [r for r in caplog.records
            if getattr(r, "evento", None) == "login.limite_global_atingido"]


def test_teto_global_soma_os_ips_bloqueia_todos_e_alerta(db, escola_completa,
                                                        monkeypatch, caplog):
    """Falhas de muitos IPs, cada um longe do próprio teto, somam no teto global:
    ao chegar nele o login da API inteira responde 429 (mesma resposta para conta
    existente ou não, também depois de reiniciar) e sai UM alerta no log, sem IP
    nem conta."""
    caplog.set_level(logging.WARNING, logger="constela.auth")
    monkeypatch.setattr(rate_limit.limitador_global_falha_login, "max_tentativas", 6)
    emails = _contas(db, escola_completa["escola"], 8)
    cli = TestClient(app)
    for i, email in enumerate(emails[:6]):
        assert _login(cli, email, ERRADA, ip=f"10.0.{i}.7").status_code == 401

    novo = "198.51.100.200"
    certo = _login(cli, emails[6], SENHA, ip=novo)
    inexistente = _login(cli, "ninguem.aqui@teste.local", ERRADA, ip=novo)
    assert certo.status_code == inexistente.status_code == 429
    assert certo.json() == inexistente.json()
    assert certo.json()["detail"].startswith(
        "O acesso está temporariamente limitado por excesso de tentativas")
    _reiniciar_processo()
    assert _login(cli, emails[7], SENHA, ip="203.0.113.99").status_code == 429

    alertas = _alertas(caplog)
    assert len(alertas) == 1
    alerta = alertas[0]
    assert alerta.levelno == logging.WARNING
    assert alerta.teto == 6 and alerta.falhas_na_janela == 6
    assert alerta.janela_s == rate_limit.limitador_global_falha_login.janela_s
    conteudo = repr({k: v for k, v in vars(alerta).items()
                     if k not in ("pathname", "filename", "module")})
    assert "10.0." not in conteudo and "pulv" not in conteudo

    bloqueios = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "login.bloqueado")).scalars().all()
    assert {b.detalhes["motivo"] for b in bloqueios} == {"teto_global"}


def test_limite_por_conta_e_ip_recusa_com_mensagem_generica(db, escola_completa):
    """O limite por conta e IP age antes do teto público sem anunciar a conta."""
    emails = _contas(db, escola_completa["escola"], 1)
    cli = TestClient(app)
    respostas = [_login(cli, emails[0], ERRADA) for _ in range(8)]
    assert all(r.status_code == 401 for r in respostas)
    nona = _login(cli, emails[0], SENHA)
    assert nona.status_code == 401
    assert nona.json() == respostas[0].json()


# --- Achado 18: a quem pedir um link novo ---------------------------------------

@pytest.fixture()
def contas_link(db, escola_completa):
    escola = escola_completa["escola"]
    rede = Rede(nome="Rede Municipal", status="ativa")
    db.add(rede)
    db.flush()
    h = bcrypt_rapido.using(rounds=4).hash(SENHA)
    sec = Usuario(escola_id=escola.id, nome="Secretaria Demo", email="sec@link.local",
                  senha_hash=h, cargo="coordenador", rede_id=rede.id)
    prof = Usuario(escola_id=escola.id, nome="Prof Link", email="prof@link.local",
                   senha_hash=h, cargo="professor")
    dono = Usuario(escola_id=escola.id, nome="Dono", email="dono@link.local",
                   senha_hash=h, cargo="admin", is_global=True)
    db.add_all([sec, prof, dono])
    db.commit()
    return {"sec": sec, "prof": prof, "dono": dono, "rede": rede,
            "admin": escola_completa["admin"]}


def _link(db, alvo: Usuario, criador: Usuario, token: str, *, vencido: bool) -> None:
    agora = datetime.now(timezone.utc)
    db.add(TokenResetSenha(
        usuario_id=alvo.id, token_hash=hash_token(token), criado_por=criador.id,
        expira_em=agora + (timedelta(minutes=-5) if vencido else timedelta(minutes=30))))
    db.commit()


def _consumir(token: str):
    return TestClient(app).post("/api/v1/auth/redefinir-senha",
                                json={"token": token, "nova_senha": "Nova#Senha2026x"})


def test_link_vencido_da_secretaria_manda_pedir_ao_admin_global(db, contas_link):
    """O administrador da escola recebe 403 ao gerar link para a Secretaria (só o
    Admin Global gera): a mensagem não pode mandá-la pedir à escola."""
    _link(db, contas_link["sec"], contas_link["dono"], "token-secretaria-vencido",
          vencido=True)
    r = _consumir("token-secretaria-vencido")
    assert r.status_code == 400
    detalhe = r.json()["detail"]
    assert "Administrador Global da plataforma" in detalhe
    assert "administrador da escola" not in detalhe


def test_link_da_secretaria_que_perdeu_o_autor_manda_pedir_ao_admin_global(
        db, contas_link):
    """Link gerado pela escola quando a conta ainda não era da rede (o autor não
    pode mais): a recusa também aponta o Admin Global."""
    _link(db, contas_link["sec"], contas_link["admin"], "token-secretaria-autor",
          vencido=False)
    r = _consumir("token-secretaria-autor")
    assert r.status_code == 400
    assert "Administrador Global da plataforma" in r.json()["detail"]


def test_link_vencido_de_professor_e_token_desconhecido_seguem_com_a_escola(
        db, contas_link):
    _link(db, contas_link["prof"], contas_link["admin"], "token-professor-vencido",
          vencido=True)
    esperado = ("Link inválido ou expirado. Peça um novo ao administrador da "
                "escola.")
    assert _consumir("token-professor-vencido").json()["detail"] == esperado
    assert _consumir("token-que-nao-existe").json()["detail"] == esperado


def test_quem_gera_o_link_da_secretaria_e_so_o_admin_global(db, contas_link):
    """A régua que a tela Minha conta e a mensagem acima repetem: a escola e a
    própria Secretaria recebem 403; o Admin Global gera o link."""
    eid = contas_link["sec"].escola_id
    sec_id = contas_link["sec"].id

    def _cli(email: str, senha: str = SENHA) -> TestClient:
        c = TestClient(app)
        r = c.post(URL, data={"username": email, "password": senha})
        assert r.status_code == 200, r.text
        c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        return c

    rota = f"/api/v1/escolas/{eid}/usuarios/{sec_id}/redefinir-senha"
    assert _cli("admin@teste.local", "s3nh4").post(rota).status_code == 403
    assert _cli("sec@link.local").post(
        rota, json={"senha_atual": SENHA}).status_code == 403
    assert _cli("dono@link.local").post(rota).status_code == 200
    assert auth_router._so_o_admin_global_gera_link(contas_link["sec"]) is True
    assert auth_router._so_o_admin_global_gera_link(contas_link["prof"]) is False


# --- Tetos por IP e global configuráveis pelo ambiente (EDU_LOGIN_TETO_*) ---------
# Antes: os dois tetos novos eram constantes no código — subir o global em produção
# (se o uso real chegasse perto dele) exigia mudar o código e publicar. Agora vêm de
# EDU_LOGIN_TETO_{IP,GLOBAL}_{FALHAS,JANELA_S}, com os padrões de antes (50 e 400 em
# 5 min), como QUEST_LIMITE_GLOBAL_* no Quest. Os limites antigos seguem fixos.

_VARIAVEIS_DO_TETO = ("EDU_LOGIN_TETO_IP_FALHAS", "EDU_LOGIN_TETO_IP_JANELA_S",
                      "EDU_LOGIN_TETO_GLOBAL_FALHAS", "EDU_LOGIN_TETO_GLOBAL_JANELA_S")


def test_tetos_configuraveis_tem_os_padroes_de_antes_e_faixa_validada(monkeypatch):
    for nome in _VARIAVEIS_DO_TETO:
        monkeypatch.delenv(nome, raising=False)
    cfg = Settings(_env_file=None)
    assert (cfg.EDU_LOGIN_TETO_IP_FALHAS, cfg.EDU_LOGIN_TETO_IP_JANELA_S) == (50, 300)
    assert (cfg.EDU_LOGIN_TETO_GLOBAL_FALHAS,
            cfg.EDU_LOGIN_TETO_GLOBAL_JANELA_S) == (400, 300)
    # A variável de ambiente é lida (e vence o padrão).
    monkeypatch.setenv("EDU_LOGIN_TETO_GLOBAL_FALHAS", "1200")
    assert Settings(_env_file=None).EDU_LOGIN_TETO_GLOBAL_FALHAS == 1200
    # Teto zero barraria todo login; janela fora de 1 min..1 h não freia nada ou
    # deixa o login parado por horas: recusados já na leitura da configuração.
    for campo, invalido in (("EDU_LOGIN_TETO_IP_FALHAS", 0),
                            ("EDU_LOGIN_TETO_GLOBAL_FALHAS", 0),
                            ("EDU_LOGIN_TETO_IP_JANELA_S", 30),
                            ("EDU_LOGIN_TETO_GLOBAL_JANELA_S", 7200)):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **{campo: invalido})


def test_valores_do_ambiente_chegam_aos_limitadores_do_login():
    """Processo NOVO (como um worker subindo com as variáveis do Railway): teto e
    janela dos limitadores — que o router usa nas DUAS camadas, memória e banco — são
    os do ambiente; o alerta segue a janela global; os limites antigos não mudam."""
    env = {k: v for k, v in os.environ.items() if k not in _VARIAVEIS_DO_TETO}
    env.update(ENV="dev", PYTHONIOENCODING="utf-8",
               EDU_LOGIN_TETO_IP_FALHAS="7", EDU_LOGIN_TETO_IP_JANELA_S="120",
               EDU_LOGIN_TETO_GLOBAL_FALHAS="900", EDU_LOGIN_TETO_GLOBAL_JANELA_S="600")
    codigo = (
        "from app.core import rate_limit as r\n"
        "f = lambda x: '%d/%d' % (x.max_tentativas, x.janela_s)\n"
        "print('TETOS=' + ' '.join(f(x) for x in (\n"
        "    r.limitador_ip_falha_login, r.limitador_global_falha_login,\n"
        "    r.alerta_global_login, r.limitador_login, r.limitador_conta)))\n")
    p = subprocess.run([sys.executable, "-c", codigo], cwd=str(BASE_DIR), env=env,
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    linhas = [x for x in p.stdout.splitlines() if x.startswith("TETOS=")]
    assert p.returncode == 0 and linhas, f"{p.stdout[-2000:]}\n{p.stderr[-2000:]}"
    assert linhas[-1] == "TETOS=7/120 900/600 1/600 8/300 20/900"


def test_teto_e_janela_configurados_valem_tambem_no_banco(db, escola_completa,
                                                         monkeypatch):
    """O router passa ao banco o teto e a janela DO LIMITADOR (= os da configuração):
    com teto 2 e janela de 2 min, a 2ª falha bloqueia o IP no banco por 2 min — não
    pelos 5 min do padrão —, e a espera anunciada depois de reiniciar é essa."""
    monkeypatch.setattr(rate_limit.limitador_ip_falha_login, "max_tentativas", 2)
    monkeypatch.setattr(rate_limit.limitador_ip_falha_login, "janela_s", 120)
    emails = _contas(db, escola_completa["escola"], 3)
    cli = TestClient(app)
    antes = datetime.now(timezone.utc).replace(tzinfo=None)
    for email in emails[:2]:
        assert _login(cli, email, ERRADA).status_code == 401
    depois = datetime.now(timezone.utc).replace(tzinfo=None)

    linha = next(x for x in _chaves_do_edu(db) if x.chave.startswith("edu_login_ip_falha:"))
    assert linha.falhas == 2
    assert (antes + timedelta(seconds=120) <= linha.bloqueado_ate
            <= depois + timedelta(seconds=120))
    _reiniciar_processo()                          # bloqueado só no banco
    r = _login(cli, emails[2], SENHA)
    assert r.status_code == 429
    assert r.json()["detail"] == "Muitas tentativas. Aguarde 2 minuto(s) e tente novamente."


# --- Teto por IP tem de ficar abaixo do teto global --------------------------------
# Antes: cada variável era validada sozinha. EDU_LOGIN_TETO_IP_FALHAS=500 com
# EDU_LOGIN_TETO_GLOBAL_FALHAS=450 subia calado, e as falhas de UM IP só chegavam ao
# teto global antes do próprio: um único cliente travava o login de todos. Agora o
# boot avisa em dev e recusa em produção (a mensagem diz as variáveis, não os valores).

_PG_FICTICIO = "postgresql+psycopg://app@127.0.0.1:55432/teto_login_test"
_VARIAVEIS_DO_BOOT = ("ENV", "DATABASE_URL", "SECRET_KEY", "DATA_ENCRYPTION_KEY",
                      "DATA_ENCRYPTION_KEYS_ANTERIORES", "CHAVE_CIFRA_LEGADA_ANTERIOR",
                      "CORS_ORIGINS", "DOCS_HABILITADOS", "ADMIN_GLOBAL_EMAIL",
                      "METRICS_PUBLICO")


@pytest.fixture()
def ambiente_do_boot(monkeypatch):
    """Nenhuma variável do processo de teste vaza para o Settings() destes testes."""
    for nome in _VARIAVEIS_DO_TETO + _VARIAVEIS_DO_BOOT:
        monkeypatch.delenv(nome, raising=False)


def _producao(**extra) -> Settings:
    import secrets
    return Settings(_env_file=None, ENV="producao", DATABASE_URL=_PG_FICTICIO,
                    SECRET_KEY=f"sk-{secrets.token_urlsafe(40)}",
                    DATA_ENCRYPTION_KEY=f"dek-{secrets.token_urlsafe(40)}", **extra)


def _avisos_do_teto(registro) -> list[str]:
    return [str(w.message) for w in registro if "EDU_LOGIN_TETO" in str(w.message)]


@pytest.mark.parametrize("ip, global_", [(450, 450), (500, 450)])
def test_teto_do_ip_igual_ou_acima_do_global_avisa_em_dev(ambiente_do_boot, ip, global_):
    with pytest.warns(UserWarning, match="EDU_LOGIN_TETO_IP_FALHAS maior ou igual") as av:
        cfg = Settings(_env_file=None, ENV="dev", EDU_LOGIN_TETO_IP_FALHAS=ip,
                       EDU_LOGIN_TETO_GLOBAL_FALHAS=global_)
    # Cada valor sozinho é válido: em dev ficam como estão (só o aviso).
    assert (cfg.EDU_LOGIN_TETO_IP_FALHAS, cfg.EDU_LOGIN_TETO_GLOBAL_FALHAS) == (ip, global_)
    avisos = _avisos_do_teto(av)
    assert len(avisos) == 1
    assert str(ip) not in avisos[0] and str(global_) not in avisos[0]   # sem os valores
    assert "50 e 400" in avisos[0]                                      # os padrões


@pytest.mark.parametrize("ip, global_", [(450, 450), (500, 450)])
def test_teto_do_ip_igual_ou_acima_do_global_recusa_o_boot_de_producao(
        ambiente_do_boot, ip, global_):
    with pytest.raises(RuntimeError, match="EDU_LOGIN_TETO_IP_FALHAS maior ou igual") as e:
        _producao(EDU_LOGIN_TETO_IP_FALHAS=ip, EDU_LOGIN_TETO_GLOBAL_FALHAS=global_)
    assert str(ip) not in str(e.value) and str(global_) not in str(e.value)


def test_teto_do_ip_abaixo_do_global_sobe_sem_aviso(ambiente_do_boot, recwarn):
    assert _producao().em_producao                       # os padrões (50 < 400)
    assert _producao(EDU_LOGIN_TETO_IP_FALHAS=399,
                     EDU_LOGIN_TETO_GLOBAL_FALHAS=400).EDU_LOGIN_TETO_IP_FALHAS == 399
    Settings(_env_file=None, ENV="dev", EDU_LOGIN_TETO_IP_FALHAS=10,
             EDU_LOGIN_TETO_GLOBAL_FALHAS=1200)
    assert _avisos_do_teto(recwarn) == []
