"""Consumo do link de redefinição × revogação simultânea (4ª revisão de
integração, contas-turmas-push). Dados 100% fictícios.

O consumo (``POST /auth/redefinir-senha``) conferia token, situação da conta e
autor com SELECTs comuns e só gravava depois, por chave primária. A revogação
que commitava nesse intervalo (desativar, trocar a senha pelo admin, promover a
Secretaria) respondia 200 e não valia, e dois consumos do mesmo link respondiam
200 e 200. Agora o consumo trava a conta, marca o token com UPDATE condicional
(``usado_em IS NULL``, exige 1 linha) e só então confere situação e autor.

Aqui (SQLite, e reaproveitados no PostgreSQL em ``..._corrida_pg``) o intervalo
é reproduzido de forma determinística: logo depois de o consumo ler o token
(``_token_valido``), um pedido REAL à API, por outra sessão, revoga ou consome o
mesmo link. Falhavam no 99c197d (consumo 200 ou gravação sem condição): a senha
do admin no meio, o 2º consumo no meio e a ordem dos comandos. Desativar,
promover e mudar o cargo no meio já davam 400 nesse ponto (a conta era lida
depois): ficam como controle de que a releitura continua valendo depois da
trava. A TRAVA em si (``FOR NO KEY UPDATE``, que o SQLite não emite) é provada no PG
com duas threads, em ``..._corrida_pg``; aqui se prova a ORDEM dos comandos.
"""
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from app.core.security import hash_senha, verificar_senha
from app.main import app
from app.models import Rede, TokenResetSenha, Usuario
from app.routers import auth as auth_router

SENHA_ANTIGA = "Senha-Antiga-7319"
SENHA_DO_LINK = "Cometa-Azul-4821"
SENHA_OUTRA = "Estrela-Rosa-5530"
SENHA_COORD = "Coord-Ficticia-6604"


def _login(usuario, senha):
    return TestClient(app).post("/api/v1/auth/login",
                                data={"username": usuario, "password": senha})


def _consumir(token, nova):
    return TestClient(app).post("/api/v1/auth/redefinir-senha",
                                json={"token": token, "nova_senha": nova})


def _conta(db, escola_id, email, cargo="professor", senha=SENHA_ANTIGA):
    u = Usuario(escola_id=escola_id, nome="Paula Ficticia Corrida", email=email,
                senha_hash=hash_senha(senha), cargo=cargo)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _depois_de_ler_o_token(monkeypatch, acao):
    """Roda ``acao()`` uma vez, logo depois de o consumo ler o token e antes de
    travar a conta — o intervalo em que a versão antiga só tinha feito SELECTs."""
    original = auth_router._token_valido
    estado = {"feito": False, "resultado": None}

    def envolvida(sessao, token_bruto):
        registro = original(sessao, token_bruto)
        if registro is not None and not estado["feito"]:
            estado["feito"] = True
            estado["resultado"] = acao()
        return registro

    monkeypatch.setattr(auth_router, "_token_valido", envolvida)
    return estado


def _token_do(db, usuario_id):
    db.expire_all()
    return db.execute(select(TokenResetSenha)
                      .where(TokenResetSenha.usuario_id == usuario_id)).scalar_one()


def test_senha_definida_pelo_admin_no_meio_vence_o_link(cliente, db, escola_completa,
                                                        monkeypatch):
    """O admin define a senha direto para cortar um link entregue por engano. Antes
    a senha do link a sobrescrevia (os dois pedidos com 200)."""
    e = escola_completa["escola"]
    p = _conta(db, e.id, "paula.corrida1@teste.local")
    base = f"/api/v1/escolas/{e.id}/usuarios/{p.id}"
    token = cliente.post(f"{base}/redefinir-senha").json()["token"]
    estado = _depois_de_ler_o_token(
        monkeypatch, lambda: cliente.patch(base, json={"senha": SENHA_OUTRA}).status_code)
    r = _consumir(token, SENHA_DO_LINK)
    assert estado["resultado"] == 200
    assert r.status_code == 400, r.text
    monkeypatch.undo()
    assert _login(p.email, SENHA_OUTRA).status_code == 200      # a do admin vale
    assert _login(p.email, SENHA_DO_LINK).status_code == 401


def test_desativar_no_meio_derruba_o_consumo(cliente, db, escola_completa, monkeypatch):
    e = escola_completa["escola"]
    p = _conta(db, e.id, "paula.corrida2@teste.local")
    base = f"/api/v1/escolas/{e.id}/usuarios/{p.id}"
    token = cliente.post(f"{base}/redefinir-senha").json()["token"]
    estado = _depois_de_ler_o_token(
        monkeypatch, lambda: cliente.patch(base, json={"status": "inativo"}).status_code)
    r = _consumir(token, SENHA_DO_LINK)
    assert estado["resultado"] == 200
    assert r.status_code == 400, r.text
    monkeypatch.undo()
    db.expire_all()
    u = db.get(Usuario, p.id)
    assert u.status == "inativo"
    assert not verificar_senha(SENHA_DO_LINK, u.senha_hash)
    # Reativada a conta, o link continua morto e a senha antiga é a que vale.
    assert cliente.patch(base, json={"status": "ativo"}).status_code == 200
    assert _consumir(token, SENHA_DO_LINK).status_code == 400
    assert _login(p.email, SENHA_DO_LINK).status_code == 401
    assert _login(p.email, SENHA_ANTIGA).status_code == 200


def test_link_de_uso_unico_consumido_no_meio_recusa_o_segundo(cliente, db, escola_completa,
                                                              monkeypatch):
    e = escola_completa["escola"]
    p = _conta(db, e.id, "paula.corrida3@teste.local")
    base = f"/api/v1/escolas/{e.id}/usuarios/{p.id}"
    token = cliente.post(f"{base}/redefinir-senha").json()["token"]
    estado = _depois_de_ler_o_token(
        monkeypatch, lambda: _consumir(token, SENHA_OUTRA).status_code)
    r = _consumir(token, SENHA_DO_LINK)
    assert estado["resultado"] == 200          # o 1º consumo vale
    assert r.status_code == 400, r.text        # o 2º, não
    monkeypatch.undo()
    assert _login(p.email, SENHA_OUTRA).status_code == 200
    assert _login(p.email, SENHA_DO_LINK).status_code == 401


def test_promocao_a_secretaria_no_meio_derruba_o_link_da_escola(
        cliente, cliente_global, db, escola_completa, monkeypatch):
    e = escola_completa["escola"]
    rede = Rede(nome="Rede Corrida Ficticia", status="ativa")
    db.add(rede)
    db.flush()
    e.rede_id = rede.id
    db.commit()
    p = _conta(db, e.id, "carla.corrida@teste.local", cargo="coordenador")
    token = cliente.post(
        f"/api/v1/escolas/{e.id}/usuarios/{p.id}/redefinir-senha").json()["token"]
    estado = _depois_de_ler_o_token(
        monkeypatch, lambda: cliente_global.put(
            f"/api/v1/redes/{rede.id}/usuarios", json={"usuario_ids": [p.id]}).status_code)
    r = _consumir(token, SENHA_DO_LINK)
    assert estado["resultado"] == 200
    assert r.status_code == 400, r.text
    monkeypatch.undo()
    assert _login(p.email, SENHA_DO_LINK).status_code == 401


def test_cargo_mudado_no_meio_e_conferido_depois_da_trava_sem_queimar_o_link(
        cliente, db, escola_completa, monkeypatch):
    """Promover a conta a coordenadora NÃO marca os links pendentes DELA (só os que
    ela gerou): quem barra é o autor reconferido depois da trava — a coordenadora
    que gerou o link já não poderia gerá-lo. A recusa vem depois da marcação do
    token e desfaz a marcação (a sessão fecha sem commit)."""
    e = escola_completa["escola"]
    coord = _conta(db, e.id, "coord.corrida@teste.local", cargo="coordenador",
                   senha=SENHA_COORD)
    p = _conta(db, e.id, "paula.corrida4@teste.local")
    c = TestClient(app)
    login = c.post("/api/v1/auth/login",
                   data={"username": coord.email, "password": SENHA_COORD})
    assert login.status_code == 200, login.text
    c.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    r = c.post(f"/api/v1/escolas/{e.id}/usuarios/{p.id}/redefinir-senha")
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    base = f"/api/v1/escolas/{e.id}/usuarios/{p.id}"
    estado = _depois_de_ler_o_token(
        monkeypatch, lambda: cliente.patch(base, json={"cargo": "coordenador"}).status_code)
    r = _consumir(token, SENHA_DO_LINK)
    assert estado["resultado"] == 200
    assert r.status_code == 400, r.text
    assert _token_do(db, p.id).usado_em is None          # a marcação foi desfeita
    assert _login(p.email, SENHA_DO_LINK).status_code == 401


def test_senha_fraca_do_dono_nao_queima_o_link(cliente, db, escola_completa):
    """A regra que depende do dono (senha = e-mail) roda depois da marcação: o 422
    desfaz a marcação e o mesmo link continua valendo."""
    e = escola_completa["escola"]
    p = _conta(db, e.id, "paula.corrida5@teste.local")
    token = cliente.post(
        f"/api/v1/escolas/{e.id}/usuarios/{p.id}/redefinir-senha").json()["token"]
    r = _consumir(token, "paula.corrida5")
    assert r.status_code == 422, r.text
    assert _token_do(db, p.id).usado_em is None
    assert _consumir(token, SENHA_DO_LINK).status_code == 200
    assert _token_do(db, p.id).usado_em is not None
    assert _consumir(token, SENHA_OUTRA).status_code == 400


def test_consumo_trava_a_conta_antes_de_marcar_o_token_condicionalmente(
        cliente, db, escola_completa):
    """A ORDEM que serializa com as revogações (usuário → token) e a marcação
    condicional. No PostgreSQL a leitura da conta sai com FOR NO KEY UPDATE; no SQLite o
    dialeto não emite a cláusula (um escritor por vez), então lá se prova a ordem."""
    e = escola_completa["escola"]
    p = _conta(db, e.id, "paula.corrida6@teste.local")
    token = cliente.post(
        f"/api/v1/escolas/{e.id}/usuarios/{p.id}/redefinir-senha").json()["token"]
    engine = db.get_bind()
    comandos: list[str] = []

    def _anotar(_conn, _cursor, sql, _params, _ctx, _many):
        comandos.append(" ".join(sql.split()))

    event.listen(engine, "before_cursor_execute", _anotar)
    try:
        r = _consumir(token, SENHA_DO_LINK)
    finally:
        event.remove(engine, "before_cursor_execute", _anotar)
    assert r.status_code == 200, r.text

    def _indice(pred, depois_de=-1):
        return next(i for i, s in enumerate(comandos) if i > depois_de and pred(s))

    i_token = _indice(lambda s: s.startswith("SELECT") and "FROM tokens_reset_senha" in s)
    i_conta = _indice(lambda s: s.startswith("SELECT") and "FROM usuarios" in s, i_token)
    i_marca = _indice(lambda s: s.startswith("UPDATE tokens_reset_senha"), i_token)
    assert i_token < i_conta < i_marca, comandos
    assert "usado_em IS NULL" in comandos[i_marca]
    # Nenhuma gravação do token por chave primária sem a condição (a versão antiga).
    assert all("usado_em IS NULL" in s for s in comandos
               if s.startswith("UPDATE tokens_reset_senha")), comandos
    if engine.dialect.name == "postgresql":
        assert "FOR NO KEY UPDATE" in comandos[i_conta], comandos[i_conta]
