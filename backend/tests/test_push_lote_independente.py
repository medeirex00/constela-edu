"""Push: cada lote de 100 é independente — um lote com erro não cala os demais.

``push._enviar_lotes`` mandava os lotes em sequência e chamava
``raise_for_status()`` em cada um, sem try por lote. Uma resposta de erro no lote
k (timeout, 5xx do Expo, 400 do pedido inteiro) fazia a exceção sair do laço: os
lotes k+1.. NUNCA eram enviados e os ``DeviceNotRegistered`` que os lotes
anteriores já tinham reportado NÃO eram apagados (``notificar_escola`` engole a
exceção) — ao contrário do que a docstring promete (revisão de integração 5,
exportacoes-notificacoes, prova 504).

Regra travada aqui: o lote com erro vira um aviso no log (com o número do lote)
e o envio segue; os tokens mortos reportados pelos lotes que responderam são
removidos. Sem rede: ``httpx.post`` é trocado por um falso. Dados fictícios.
"""
import logging

import httpx

from app.core.security import hash_senha
from app.models import DispositivoMovel, Usuario
from app.services import push


class _Resp:
    def __init__(self, status, corpo):
        self.status_code = status
        self._corpo = corpo
        self._req = httpx.Request("POST", push.EXPO_PUSH_URL)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "erro", request=self._req,
                response=httpx.Response(self.status_code, request=self._req))

    def json(self):
        return self._corpo


def _aparelhos(db, eid, n):
    u = Usuario(escola_id=eid, nome="Coord Ficticia", email="coord.push@teste.local",
                senha_hash=hash_senha("Senha-Coord-Push-x"), cargo="coordenador")
    db.add(u)
    db.flush()
    for i in range(n):
        db.add(DispositivoMovel(escola_id=eid, usuario_id=u.id, plataforma="android",
                                token_push=f"ExponentPushToken[ficticio-{i:04d}]"))
    db.commit()


def _ok(lote):
    return _Resp(200, {"data": [{"status": "ok"} for _ in lote]})


def test_lote_recusado_nao_impede_o_lote_seguinte(db, escola_completa, monkeypatch,
                                                  caplog):
    eid = escola_completa["escola"].id
    _aparelhos(db, eid, 150)                    # 2 lotes: 100 + 50
    lotes_enviados: list[int] = []

    def falso_post(url, json, timeout):
        lotes_enviados.append(len(json))
        if len(lotes_enviados) == 1:            # 1º lote: o Expo recusa o pedido
            return _Resp(400, {"errors": [{"code": "PUSH_TOO_MANY_EXPERIENCE_IDS"}]})
        return _ok(json)

    monkeypatch.setattr(httpx, "post", falso_post)
    with caplog.at_level(logging.WARNING, logger=push.logger.name):
        alvo = push.notificar_escola(db, eid, "Novos dados no Constela Edu", "corpo")
    assert alvo == 150
    assert lotes_enviados == [100, 50], "o 2º lote (50 aparelhos) nunca saiu"
    avisos = [r for r in caplog.records
              if r.levelno == logging.WARNING and r.name == push.logger.name]
    assert len(avisos) == 1
    assert "lote 1 de 2" in avisos[0].getMessage()
    assert db.query(DispositivoMovel).count() == 150   # nada apagado por engano


def test_nao_registrado_do_lote_anterior_e_limpo_mesmo_com_timeout_depois(
        db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    _aparelhos(db, eid, 150)
    chamadas = {"n": 0}

    def falso_post(url, json, timeout):
        chamadas["n"] += 1
        if chamadas["n"] == 1:                  # 1º lote ok, com um token morto
            data = [{"status": "ok"} for _ in json]
            data[0] = {"status": "error", "details": {"error": "DeviceNotRegistered"}}
            return _Resp(200, {"data": data})
        raise httpx.ReadTimeout("expo lento")   # 2º lote: timeout

    monkeypatch.setattr(httpx, "post", falso_post)
    push.notificar_escola(db, eid, "t", "c")
    db.expire_all()
    restante = db.query(DispositivoMovel).filter(
        DispositivoMovel.token_push == "ExponentPushToken[ficticio-0000]").count()
    assert restante == 0, "o DeviceNotRegistered do 1º lote foi descartado com a exceção"
    assert db.query(DispositivoMovel).count() == 149


def test_enviar_lotes_acumula_nao_registrados_dos_lotes_que_responderam(monkeypatch):
    """Unidade: lote do meio com erro; os mortos do 1º e do 3º voltam."""
    lotes = push.montar_lotes([f"ExponentPushToken[t-{i:03d}]" for i in range(250)],
                              "t", "c")
    assert [len(lote) for lote in lotes] == [100, 100, 50]
    chamadas = {"n": 0}

    def falso_post(url, json, timeout):
        chamadas["n"] += 1
        if chamadas["n"] == 2:
            return _Resp(502, {})
        data = [{"status": "ok"} for _ in json]
        data[-1] = {"status": "error", "details": {"error": "DeviceNotRegistered"}}
        return _Resp(200, {"data": data})

    monkeypatch.setattr(httpx, "post", falso_post)
    assert push._enviar_lotes(lotes) == ["ExponentPushToken[t-099]",
                                         "ExponentPushToken[t-249]"]
    assert chamadas["n"] == 3


def test_resposta_ilegivel_de_um_lote_nao_cala_os_demais(monkeypatch):
    lotes = push.montar_lotes([f"ExponentPushToken[t-{i:03d}]" for i in range(150)],
                              "t", "c")
    enviados: list[int] = []

    class _SemJson(_Resp):
        def json(self):
            raise ValueError("corpo não é JSON")

    def falso_post(url, json, timeout):
        enviados.append(len(json))
        return _SemJson(200, None) if len(enviados) == 1 else _ok(json)

    monkeypatch.setattr(httpx, "post", falso_post)
    assert push._enviar_lotes(lotes) == []
    assert enviados == [100, 50]
