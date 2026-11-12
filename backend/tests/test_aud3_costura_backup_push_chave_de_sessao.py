"""A impressão da chave de sessão dos aparelhos de push fica fora do backup da escola
(S_G_ROTACAO-1, costura da fase D).

A troca da SECRET_KEY tira os aparelhos de push da escola: cada escola guarda em
``configuracoes`` (namespace ``push``, chave ``chave_de_sessao``) a impressão HMAC da
chave com que os aparelhos foram registrados (``push.conferir_chave_de_sessao``).

O DEFEITO. O namespace ``push`` não estava em ``backup.SEGREDOS_DE_CONFIGURACAO``:

* a impressão (valor derivado da SECRET_KEY) saía no arquivo de backup que o admin baixa
  e que circula fora do banco;
* restaurar um backup gerado ANTES de uma troca de chave repunha a impressão antiga: o
  próximo push (ou registro de aparelho, ou boot) a achava diferente da atual e apagava
  sem necessidade todos os aparelhos da escola, registrados depois da troca com
  sessões válidas.

Agora a linha não sai no arquivo e a restauração deixa a atual como está (como os
outros segredos). Chaves geradas na hora; tokens de push fictícios.
"""
import json
import secrets

from sqlalchemy import select

from app.core.config import settings
from app.core.security import impressao_da_chave_de_sessao
from app.models import Configuracao, DispositivoMovel
from app.services import backup, push

TOKEN_ANTES = "ExponentPushToken[ficticio-registrado-antes-da-troca]"
TOKEN_DEPOIS = "ExponentPushToken[ficticio-registrado-depois-da-troca]"


def _chave(rotulo: str) -> str:
    return f"teste-{rotulo}-" + secrets.token_urlsafe(32)


def _marca(db, eid: int):
    db.expire_all()
    linha = db.execute(select(Configuracao).where(
        Configuracao.escola_id == eid,
        Configuracao.namespace == push.NAMESPACE_CHAVE_DE_SESSAO,
        Configuracao.chave == push.CHAVE_IMPRESSAO)).scalar_one_or_none()
    return linha.valor if linha is not None else None


def _aparelho(db, ec, token: str) -> None:
    db.add(DispositivoMovel(escola_id=ec["escola"].id, usuario_id=ec["admin"].id,
                            token_push=token, plataforma="android"))
    db.commit()


def _tokens(db) -> set[str]:
    db.expire_all()
    return set(db.execute(select(DispositivoMovel.token_push)).scalars())


def test_o_namespace_do_push_e_segredo_do_backup():
    assert push.NAMESPACE_CHAVE_DE_SESSAO in backup.SEGREDOS_DE_CONFIGURACAO
    assert push.NAMESPACE_CHAVE_DE_SESSAO in backup.PRESERVADAS_NA_RESTAURACAO


def test_exportacao_nao_leva_a_impressao_da_chave_de_sessao(db, escola_completa, cliente):
    ec = escola_completa
    eid = ec["escola"].id
    _aparelho(db, ec, TOKEN_ANTES)
    push.conferir_chave_de_sessao(db, eid)
    db.commit()
    impressao = _marca(db, eid)
    assert impressao == impressao_da_chave_de_sessao()

    arquivo = backup.exportar(db, eid)
    assert impressao not in json.dumps(arquivo, default=str)
    assert not [c for c in arquivo["tabelas"]["configuracoes"]
                if c["namespace"] == push.NAMESPACE_CHAVE_DE_SESSAO]
    r = cliente.get(f"/api/v1/escolas/{eid}/backup")
    assert r.status_code == 200, r.text
    assert impressao not in r.text


def test_restaurar_backup_de_antes_da_troca_nao_apaga_os_aparelhos_de_depois(
        db, escola_completa, monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    monkeypatch.setattr(settings, "SECRET_KEY", _chave("sk0"))
    _aparelho(db, ec, TOKEN_ANTES)
    push.conferir_chave_de_sessao(db, eid)
    db.commit()
    impressao_antiga = _marca(db, eid)
    # O arquivo como o código ANTERIOR o gerava (com a linha do push).
    with monkeypatch.context() as m:
        m.setattr(backup, "SEGREDOS_DE_CONFIGURACAO", {}, raising=False)
        arquivo = json.loads(json.dumps(backup.exportar(db, eid), default=str))
    assert impressao_antiga in json.dumps(arquivo)

    # Troca da SECRET_KEY: os aparelhos antigos saem e o app volta a se registrar.
    monkeypatch.setattr(settings, "SECRET_KEY", _chave("sk1"))
    removidos, _ = push.conferir_chave_de_sessao(db, eid)
    db.commit()
    assert removidos == 1
    _aparelho(db, ec, TOKEN_DEPOIS)
    impressao_nova = _marca(db, eid)
    assert impressao_nova != impressao_antiga

    backup.restaurar(db, eid, arquivo)
    db.commit()

    assert _marca(db, eid) == impressao_nova        # antes: voltava a impressão antiga
    removidos, _ = push.conferir_chave_de_sessao(db, eid)   # o próximo push
    db.commit()
    assert removidos == 0
    assert TOKEN_DEPOIS in _tokens(db)
