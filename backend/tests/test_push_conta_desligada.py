"""Conta desligada não recebe mais o push da escola (2ª revisão de integração,
contas-acesso, prova 3).

Desativar ou excluir a conta derrubava a sessão e os links, mas não o aparelho
registrado para push: ``notificar_escola`` mandava para TODO aparelho da escola,
e o celular de quem perdeu o acesso seguia recebendo "Novos dados no Constela
Edu" e "<primeiro nome da criança> teve os dados da plataforma atualizados" na
tela bloqueada. O app não se descadastra sozinho no 401, e a conta revogada nem
conseguiria chamar ``/dispositivos/remover``.

Agora: ``notificar_escola`` só manda para aparelho de conta ATIVA (cobre também
as contas desligadas antes da correção, sem migração); desativar, excluir e
promover a Secretaria apagam os aparelhos da conta e contam
``dispositivos_removidos`` na auditoria. O envio ao Expo é trocado por uma
captura (sem rede). Dados 100% fictícios.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.security import hash_senha
from app.main import app
from app.models import DispositivoMovel, LogAuditoria, Rede, Usuario
from app.services import push

API = "/api/v1"
TOKEN_PROF = "ExponentPushToken[ficticio-prof-0001]"
TOKEN_ADMIN = "ExponentPushToken[ficticio-admin-0001]"


@pytest.fixture()
def capturados(monkeypatch):
    enviados: list[str] = []

    def _falso(lotes):
        for lote in lotes:
            enviados.extend(m["to"] for m in lote)
        return []

    monkeypatch.setattr(push, "_enviar_lotes", _falso)
    return enviados


def _login(email: str, senha: str) -> TestClient:
    c = TestClient(app)
    r = c.post(f"{API}/auth/login", data={"username": email, "password": senha})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _registrar(sessao: TestClient, eid: int, token: str) -> None:
    r = sessao.post(f"{API}/escolas/{eid}/dispositivos",
                    json={"token_push": token, "plataforma": "android"})
    assert r.status_code == 200, r.text


def _professora_com_aparelho(db, eid):
    prof = Usuario(escola_id=eid, nome="Professora Ficticia", email="prof.push@teste.local",
                   senha_hash=hash_senha("Senha-Prof-Push-9"), cargo="professor")
    db.add(prof)
    db.commit()
    sessao = _login("prof.push@teste.local", "Senha-Prof-Push-9")
    _registrar(sessao, eid, TOKEN_PROF)
    return prof.id, sessao


def _aparelhos(db, usuario_id) -> int:
    db.expire_all()
    return db.execute(select(func.count()).select_from(DispositivoMovel)
                      .where(DispositivoMovel.usuario_id == usuario_id)).scalar_one()


def _auditoria(db, acao, entidade_id) -> dict:
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == acao, LogAuditoria.entidade_id == entidade_id)
        .order_by(LogAuditoria.id.desc())).scalars().first()
    assert log is not None, acao
    return log.detalhes


@pytest.mark.parametrize("como,acao", [("desativar", "usuario.desativado"),
                                       ("excluir", "usuario.excluido")])
def test_conta_desligada_nao_recebe_mais_push_da_escola(db, escola_completa, cliente,
                                                       capturados, como, acao):
    """Prova 3 invertida — com um controle no MESMO envio: o aparelho do admin
    (conta ativa) continua recebendo, então o envio de fato aconteceu."""
    eid = escola_completa["escola"].id
    prof_id, sessao_prof = _professora_com_aparelho(db, eid)
    _registrar(cliente, eid, TOKEN_ADMIN)

    if como == "desativar":
        r = cliente.patch(f"{API}/escolas/{eid}/usuarios/{prof_id}", json={"status": "inativo"})
    else:
        r = cliente.delete(f"{API}/escolas/{eid}/usuarios/{prof_id}")
    assert r.status_code == 200, r.text
    assert sessao_prof.get(f"{API}/auth/me").status_code == 401

    # O aparelho dela saiu do banco, e a auditoria conta.
    assert _aparelhos(db, prof_id) == 0
    assert _auditoria(db, acao, prof_id)["dispositivos_removidos"] == 1

    # O aviso seguinte da escola não vai mais para ela (o do admin vai).
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/recalcular")
    assert r.status_code == 200, r.text
    assert TOKEN_ADMIN in capturados
    assert TOKEN_PROF not in capturados
    capturados.clear()
    push.notificar_escola(db, eid, titulo="Novos dados no Constela Edu",
                          corpo=push.corpo_dados_atualizados("Ana Beatriz Souza"))
    assert capturados == [TOKEN_ADMIN]


def test_aparelho_de_conta_desligada_antes_da_correcao_tambem_fica_de_fora(
        db, escola_completa, capturados):
    """Sem migração: o aparelho que ficou no banco de uma conta desativada (ou
    excluída) antes desta correção é filtrado no próprio envio."""
    eid = escola_completa["escola"].id
    admin = escola_completa["admin"]
    for status, token in (("inativo", "ExponentPushToken[legado-inativo]"),
                          ("excluido", "ExponentPushToken[legado-excluido]")):
        u = Usuario(escola_id=eid, nome=f"Conta {status}", email=f"{status}@teste.local",
                    senha_hash=hash_senha("Senha-Legado-9x"), cargo="professor",
                    status=status)
        db.add(u)
        db.flush()
        db.add(DispositivoMovel(escola_id=eid, usuario_id=u.id, token_push=token,
                                plataforma="android"))
    db.add(DispositivoMovel(escola_id=eid, usuario_id=admin.id, token_push=TOKEN_ADMIN,
                            plataforma="ios"))
    db.commit()

    alvo = push.notificar_escola(db, eid, titulo="t", corpo="c")

    assert alvo == 1
    assert capturados == [TOKEN_ADMIN]


def test_reativar_a_conta_nao_traz_o_aparelho_de_volta(db, escola_completa, cliente,
                                                     capturados):
    eid = escola_completa["escola"].id
    prof_id, _ = _professora_com_aparelho(db, eid)
    assert cliente.patch(f"{API}/escolas/{eid}/usuarios/{prof_id}",
                         json={"status": "inativo"}).status_code == 200
    r = cliente.patch(f"{API}/escolas/{eid}/usuarios/{prof_id}", json={"status": "ativo"})
    assert r.status_code == 200, r.text
    assert "dispositivos_removidos" not in _auditoria(db, "usuario.reativado", prof_id)

    push.notificar_escola(db, eid, titulo="t", corpo="c")
    assert TOKEN_PROF not in capturados

    # Só um novo registro pelo app (novo login) volta a receber.
    _registrar(_login("prof.push@teste.local", "Senha-Prof-Push-9"), eid, TOKEN_PROF)
    push.notificar_escola(db, eid, titulo="t", corpo="c")
    assert TOKEN_PROF in capturados


def test_controle_trocar_a_senha_de_conta_ativa_mantem_o_aparelho(db, escola_completa,
                                                                 cliente, capturados):
    """A troca de senha também revoga sessões, mas a conta segue ativa: o aparelho
    fica (o app registra de novo ao entrar com a senha nova, sem duplicar)."""
    eid = escola_completa["escola"].id
    prof_id, _ = _professora_com_aparelho(db, eid)
    r = cliente.patch(f"{API}/escolas/{eid}/usuarios/{prof_id}",
                      json={"senha": "Outra-Senha-Forte-77"})
    assert r.status_code == 200, r.text
    assert _aparelhos(db, prof_id) == 1
    assert "dispositivos_removidos" not in _auditoria(db, "usuario.senha_redefinida", prof_id)
    push.notificar_escola(db, eid, titulo="t", corpo="c")
    assert TOKEN_PROF in capturados


def test_promocao_a_secretaria_apaga_os_aparelhos_da_escola(db, escola_completa,
                                                            cliente_global, capturados):
    eid = escola_completa["escola"].id
    prof_id, _ = _professora_com_aparelho(db, eid)
    rede = Rede(nome="Rede Push Ficticia", status="ativa")
    db.add(rede)
    db.commit()

    r = cliente_global.put(f"{API}/redes/{rede.id}/usuarios", json={"usuario_ids": [prof_id]})

    assert r.status_code == 200, r.text
    assert _aparelhos(db, prof_id) == 0
    assert _auditoria(db, "usuario.promovido_a_secretaria",
                      prof_id)["dispositivos_removidos"] == 1
    push.notificar_escola(db, eid, titulo="t", corpo="c")
    assert TOKEN_PROF not in capturados


def test_controle_exclusao_permanente_continua_apagando_o_aparelho(
        db, escola_completa, cliente_global, capturados):
    eid = escola_completa["escola"].id
    prof_id, _ = _professora_com_aparelho(db, eid)
    r = cliente_global.delete(f"{API}/escolas/{eid}/usuarios/{prof_id}/permanente",
                              params={"confirmacao": "prof.push@teste.local"})
    assert r.status_code == 200, r.text
    push.notificar_escola(db, eid, titulo="t", corpo="c")
    assert TOKEN_PROF not in capturados
