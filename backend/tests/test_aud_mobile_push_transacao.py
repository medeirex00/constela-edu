"""Push: a chamada ao Expo não segura a transação do banco da requisição
(auditoria técnica, API_SEGURANCA-6).

``push.notificar_escola`` lia os aparelhos e as contas (o SELECT abre a transação
por autobegin; com ``aluno_id``, também as consultas de ``_ve_a_crianca``) e chamava
``httpx.post`` ao Expo — até 15 s por lote — com essa transação ainda aberta. A
sessão é a da requisição (``importacoes._pos_commit_importacao``), depois do commit
da operação principal: no PostgreSQL a conexão ficava "idle in transaction" durante
a chamada externa, presa ao pool.

Regra travada aqui: a lista de destinos é lida, a transação de leitura é encerrada
ANTES da rede, e os tokens mortos que o Expo devolver são apagados numa transação
curta, depois. ``httpx.post`` é trocado por um falso (sem rede). Dados fictícios.
"""
import httpx

from app.core.security import hash_senha
from app.models import Aluno, DispositivoMovel, Matricula, Usuario
from app.services import push


def _coordenadora_com_aparelho(db, eid, token):
    u = Usuario(escola_id=eid, nome="Coord Ficticia", email="coord.trans@teste.local",
                senha_hash=hash_senha("Senha-Coord-Trans-x"), cargo="coordenador")
    db.add(u)
    db.flush()
    db.add(DispositivoMovel(escola_id=eid, usuario_id=u.id, plataforma="android",
                            token_push=token))
    db.commit()
    return u


def _falso_expo(db, visto, mortos=()):
    def post(url, json=None, timeout=None):
        visto.append({"em_transacao": db.in_transaction(), "timeout": timeout})
        data = [{"status": "error", "details": {"error": "DeviceNotRegistered"}}
                if m["to"] in mortos else {"status": "ok"} for m in json]
        return httpx.Response(200, json={"data": data},
                              request=httpx.Request("POST", url))
    return post


def test_aviso_da_escola_nao_chama_o_expo_com_transacao_aberta(db, escola_completa,
                                                                monkeypatch):
    eid = escola_completa["escola"].id
    _coordenadora_com_aparelho(db, eid, "ExponentPushToken[ficticio-trans-0001]")
    visto: list[dict] = []
    monkeypatch.setattr(httpx, "post", _falso_expo(db, visto))

    assert push.notificar_escola(db, eid, "Novos dados", "3 alunos atualizados") == 1
    assert visto == [{"em_transacao": False, "timeout": 15.0}], visto


def test_aviso_de_uma_crianca_tambem_libera_a_transacao(db, escola_completa,
                                                        monkeypatch):
    """Com ``aluno_id`` há mais leituras antes da rede (``_ve_a_crianca``): a
    transação que elas abrem também fecha antes da chamada ao Expo."""
    eid = escola_completa["escola"].id
    _coordenadora_com_aparelho(db, eid, "ExponentPushToken[ficticio-trans-0002]")
    aluna = escola_completa["alunos"][0]
    visto: list[dict] = []
    monkeypatch.setattr(httpx, "post", _falso_expo(db, visto))

    alvos = push.notificar_escola(db, eid, "Novos dados",
                                  push.corpo_dados_atualizados(aluna.nome),
                                  aluno_id=aluna.id)
    assert alvos == 1
    assert [v["em_transacao"] for v in visto] == [False]


def test_token_morto_continua_apagado_depois_da_chamada(db, escola_completa,
                                                        monkeypatch):
    """A limpeza dos ``DeviceNotRegistered`` segue valendo, numa transação curta
    depois da rede — e a sessão do chamador continua utilizável."""
    eid = escola_completa["escola"].id
    u = _coordenadora_com_aparelho(db, eid, "ExponentPushToken[ficticio-trans-vivo]")
    db.add(DispositivoMovel(escola_id=eid, usuario_id=u.id, plataforma="ios",
                            token_push="ExponentPushToken[ficticio-trans-morto]"))
    db.commit()
    visto: list[dict] = []
    monkeypatch.setattr(httpx, "post", _falso_expo(
        db, visto, mortos={"ExponentPushToken[ficticio-trans-morto]"}))

    assert push.notificar_escola(db, eid, "t", "c") == 2
    assert [v["em_transacao"] for v in visto] == [False]
    db.expire_all()
    restantes = sorted(d.token_push for d in db.query(DispositivoMovel).all())
    assert restantes == ["ExponentPushToken[ficticio-trans-vivo]"]
    # A sessão segue boa para quem chamou (ex.: o ``db.refresh`` do /resolver).
    assert db.get(Aluno, escola_completa["alunos"][0].id) is not None
    assert db.query(Matricula).count() == 3
