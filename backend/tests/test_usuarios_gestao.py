"""Gestão segura de usuários: guardas, soft delete e exclusão permanente."""
from sqlalchemy import select

from app.core.security import hash_senha
from app.models import Importacao, LogAuditoria, Usuario


def _url(escola_id: int, sufixo: str = "") -> str:
    return f"/api/v1/escolas/{escola_id}/usuarios{sufixo}"


def _criar_usuario(cliente, escola_id: int, nome: str, email: str,
                   cargo: str = "professor") -> dict:
    resposta = cliente.post(_url(escola_id), json={
        "nome": nome, "email": email, "senha": "senha123", "cargo": cargo})
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def _login(cliente, email: str, senha: str = "senha123") -> dict:
    resposta = cliente.post("/api/v1/auth/login",
                            data={"username": email, "password": senha})
    assert resposta.status_code == 200, resposta.text
    return {"Authorization": f"Bearer {resposta.json()['access_token']}"}


def _global(db, escola_id: int) -> Usuario:
    usuario = Usuario(escola_id=escola_id, nome="Global", email="global@rede.com.br",
                      senha_hash=hash_senha("senha123"), cargo="admin",
                      is_global=True)
    db.add(usuario)
    db.commit()
    return usuario


# --- Guardas -----------------------------------------------------------------

def test_nao_exclui_a_propria_conta(cliente, escola_completa):
    escola = escola_completa["escola"]
    admin = escola_completa["admin"]
    resposta = cliente.delete(_url(escola.id, f"/{admin.id}"))
    assert resposta.status_code == 400
    assert "própria conta" in resposta.json()["detail"]


def test_ultimo_admin_nao_pode_ser_excluido_nem_rebaixado(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    admin = escola_completa["admin"]
    chaves = _login(cliente, _global(db, escola.id).email)

    exclusao = cliente.delete(_url(escola.id, f"/{admin.id}"), headers=chaves)
    assert exclusao.status_code == 400
    assert "único administrador" in exclusao.json()["detail"]

    rebaixamento = cliente.patch(_url(escola.id, f"/{admin.id}"),
                                 json={"cargo": "professor"}, headers=chaves)
    assert rebaixamento.status_code == 400
    assert "único administrador" in rebaixamento.json()["detail"]

    # com um segundo admin ativo, a exclusão é liberada
    _criar_usuario(cliente, escola.id, "Novo Admin", "admin2@escola.com.br", "admin")
    liberada = cliente.delete(_url(escola.id, f"/{admin.id}"), headers=chaves)
    assert liberada.status_code == 200
    assert "preservado" in liberada.json()["mensagem"]


# --- Exclusão lógica ----------------------------------------------------------

def test_soft_delete_preserva_historico_e_bloqueia_acesso(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    professor = _criar_usuario(cliente, escola.id, "Paula Prof",
                               "paula@escola.com.br")

    resposta = cliente.delete(_url(escola.id, f"/{professor['id']}"))
    assert resposta.status_code == 200

    # registro continua no banco, marcado como excluído
    alvo = db.get(Usuario, professor["id"])
    db.refresh(alvo)
    assert alvo.status == "excluido"

    # login bloqueado
    login = cliente.post("/api/v1/auth/login",
                         data={"username": "paula@escola.com.br",
                               "password": "senha123"})
    assert login.status_code == 403

    # some da lista padrão; aparece com incluir_excluidos
    padrao = cliente.get(_url(escola.id)).json()
    assert all(u["id"] != professor["id"] for u in padrao)
    completa = cliente.get(_url(escola.id) + "?incluir_excluidos=true").json()
    assert any(u["id"] == professor["id"] for u in completa)

    # auditoria com o tipo da ação, autor e afetado
    log = db.execute(
        select(LogAuditoria).where(LogAuditoria.acao == "usuario.excluido")
        .order_by(LogAuditoria.id.desc())
    ).scalars().first()
    assert log is not None
    assert log.usuario_id == escola_completa["admin"].id
    assert log.entidade_id == professor["id"]
    assert log.detalhes["tipo"] == "exclusao_logica"


def test_excluido_so_pode_ser_restaurado(cliente, escola_completa):
    escola = escola_completa["escola"]
    usuario = _criar_usuario(cliente, escola.id, "Carlos Prof",
                             "carlos@escola.com.br")
    cliente.delete(_url(escola.id, f"/{usuario['id']}"))

    editar = cliente.patch(_url(escola.id, f"/{usuario['id']}"),
                           json={"nome": "Outro Nome"})
    assert editar.status_code == 400
    assert "restaure" in editar.json()["detail"].casefold()

    restaurar = cliente.patch(_url(escola.id, f"/{usuario['id']}"),
                              json={"status": "ativo"})
    assert restaurar.status_code == 200
    assert restaurar.json()["status"] == "ativo"


def test_desativacao_gera_log_especifico(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    usuario = _criar_usuario(cliente, escola.id, "Vera Prof", "vera@escola.com.br")
    cliente.patch(_url(escola.id, f"/{usuario['id']}"), json={"status": "inativo"})
    log = db.execute(
        select(LogAuditoria).where(LogAuditoria.acao == "usuario.desativado")
    ).scalars().first()
    assert log is not None and log.entidade_id == usuario["id"]


# --- Exclusão permanente --------------------------------------------------------

def test_exclusao_permanente_exige_admin_global(cliente, escola_completa):
    escola = escola_completa["escola"]
    usuario = _criar_usuario(cliente, escola.id, "Tiago Prof", "tiago@escola.com.br")
    resposta = cliente.delete(
        _url(escola.id, f"/{usuario['id']}/permanente?confirmacao=tiago@escola.com.br"))
    assert resposta.status_code == 403
    assert "globais" in resposta.json()["detail"]


def test_exclusao_permanente_com_confirmacao_extra(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    admin = escola_completa["admin"]
    usuario = _criar_usuario(cliente, escola.id, "Lia Prof", "lia@escola.com.br")
    chaves = _login(cliente, _global(db, escola.id).email)

    # importação feita pelo usuário — a história não pode se perder
    importacao = Importacao(escola_id=escola.id, usuario_id=usuario["id"],
                            plataforma="matific", tipo="pdf", status="concluida")
    db.add(importacao)
    db.commit()

    sem_confirmacao = cliente.delete(
        _url(escola.id, f"/{usuario['id']}/permanente"), headers=chaves)
    assert sem_confirmacao.status_code == 400
    assert "e-mail" in sem_confirmacao.json()["detail"]

    errada = cliente.delete(
        _url(escola.id, f"/{usuario['id']}/permanente?confirmacao=outra@x.com"),
        headers=chaves)
    assert errada.status_code == 400

    certa = cliente.delete(
        _url(escola.id, f"/{usuario['id']}/permanente?confirmacao=lia@escola.com.br"),
        headers=chaves)
    assert certa.status_code == 200, certa.text
    assert "permanentemente" in certa.json()["mensagem"]

    # usuário sumiu do banco; importação ficou, sem autoria
    assert db.get(Usuario, usuario["id"]) is None
    db.refresh(importacao)
    assert importacao.usuario_id is None

    log = db.execute(
        select(LogAuditoria).where(LogAuditoria.acao == "usuario.excluido_permanente")
    ).scalars().first()
    assert log is not None
    assert log.detalhes == {"tipo": "exclusao_permanente", "email": "lia@escola.com.br",
                            "nome": "Lia Prof", "cargo": "professor"}
    assert log.usuario_id != admin.id     # autor foi o global, não o admin local
