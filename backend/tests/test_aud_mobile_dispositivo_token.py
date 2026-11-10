"""Registro de aparelho para push: só token do Expo, com limite por conta, e o lixo
antigo não sai para o Expo (auditoria técnica, API_SEGURANCA-5).

``POST /escolas/{id}/dispositivos`` aceitava QUALQUER texto de 10 a 200 caracteres
como token do Expo e sem limite por conta: uma conta da escola (até um professor)
gravava milhares de "tokens" por script, e cada importação ou revisão passava a
fazer N/100 chamadas ao Expo dentro da requisição. O lixo nunca saía do banco: só
o token que o Expo marca ``DeviceNotRegistered`` era apagado.

Regras travadas aqui:
  * o token tem o formato que o app recebe de ``getExpoPushTokenAsync``
    (``ExponentPushToken[...]`` ou ``ExpoPushToken[...]``); outro texto → 422;
  * cada conta tem no máximo ``MAX_APARELHOS_POR_CONTA`` aparelhos; o registro de
    um aparelho novo além disso apaga o que está há mais tempo sem se registrar
    (o app se registra a cada abertura), e isso fica na auditoria;
  * aparelho gravado antes desta regra com token fora do formato não vai ao Expo
    e é apagado no próximo aviso.

Envio ao Expo trocado por um falso (sem rede). Dados 100% fictícios.
"""
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from app.models import DispositivoMovel, LogAuditoria
from app.routers import mobile
from app.services import push


def _tokens(db) -> list[str]:
    db.expire_all()
    return sorted(d.token_push for d in db.query(DispositivoMovel).all())


def test_texto_que_nao_e_token_do_expo_e_recusado(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    aceitos = 0
    for i in range(250):
        r = cliente.post(f"/api/v1/escolas/{eid}/dispositivos",
                         json={"token_push": f"lixo-qualquer-{i:05d}",
                               "plataforma": "android"})
        aceitos += r.status_code == 200
    for lixo in ("ExponentPushToken[]", "ExponentPushToken[a b]",
                 "ExponentPushToken[abc]extra", "xExpoPushToken[abc]",
                 "ExponentPushToken[ab[c]"):
        r = cliente.post(f"/api/v1/escolas/{eid}/dispositivos",
                         json={"token_push": lixo, "plataforma": "ios"})
        aceitos += r.status_code == 200
    assert aceitos == 0, f"API aceitou {aceitos} textos que não são token do Expo"
    assert _tokens(db) == []


def test_os_dois_formatos_do_expo_continuam_aceitos(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    for token in ("ExponentPushToken[xXyZ0123456789abcdEFGH]",
                  "ExpoPushToken[a1b2c3d4-e5f6_7890]"):
        r = cliente.post(f"/api/v1/escolas/{eid}/dispositivos",
                         json={"token_push": token, "plataforma": "android"})
        assert r.status_code == 200, r.text
    assert len(_tokens(db)) == 2


def test_conta_tem_teto_de_aparelhos_e_sai_o_mais_antigo(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    admin = escola_completa["admin"]
    teto = mobile.MAX_APARELHOS_POR_CONTA
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    # Aparelhos já registrados, do mais antigo (0) ao mais recente; o 0 voltou a se
    # registrar há pouco (abriu o app): conta como recente e não pode sair.
    for i in range(teto):
        db.add(DispositivoMovel(escola_id=eid, usuario_id=admin.id, plataforma="android",
                                token_push=f"ExponentPushToken[antigo-{i}]",
                                created_at=base + timedelta(days=i),
                                updated_at=base + timedelta(days=i)))
    db.commit()
    r = cliente.post(f"/api/v1/escolas/{eid}/dispositivos",
                     json={"token_push": "ExponentPushToken[antigo-0]",
                           "plataforma": "android"})
    assert r.status_code == 200, r.text
    assert len(_tokens(db)) == teto                 # re-registro não cria linha

    r = cliente.post(f"/api/v1/escolas/{eid}/dispositivos",
                     json={"token_push": "ExponentPushToken[novo-0001]",
                           "plataforma": "ios"})
    assert r.status_code == 200, r.text
    restantes = _tokens(db)
    assert len(restantes) == teto, restantes
    assert "ExponentPushToken[novo-0001]" in restantes
    assert "ExponentPushToken[antigo-0]" in restantes      # registrou-se há pouco
    assert "ExponentPushToken[antigo-1]" not in restantes  # o mais antigo sem uso
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "dispositivo.excedente_removido")).scalars().one()
    assert log.detalhes == {"removidos": 1, "limite": teto}

    # Script com muitos tokens válidos: a conta nunca passa do teto.
    for i in range(40):
        cliente.post(f"/api/v1/escolas/{eid}/dispositivos",
                     json={"token_push": f"ExponentPushToken[script-{i:03d}]",
                           "plataforma": "android"})
    assert len(_tokens(db)) == teto


def test_teto_e_por_conta(cliente, db, escola_completa):
    """O aparelho de OUTRA conta não conta no teto de quem registra."""
    from app.core.security import hash_senha
    from app.models import Usuario
    eid = escola_completa["escola"].id
    outra = Usuario(escola_id=eid, nome="Prof Ficticia", email="prof.teto@teste.local",
                    senha_hash=hash_senha("Senha-Prof-Teto-1"), cargo="professor")
    db.add(outra)
    db.flush()
    for i in range(mobile.MAX_APARELHOS_POR_CONTA):
        db.add(DispositivoMovel(escola_id=eid, usuario_id=outra.id, plataforma="ios",
                                token_push=f"ExponentPushToken[outra-{i}]"))
    db.commit()
    r = cliente.post(f"/api/v1/escolas/{eid}/dispositivos",
                     json={"token_push": "ExponentPushToken[admin-0001]",
                           "plataforma": "android"})
    assert r.status_code == 200, r.text
    assert len(_tokens(db)) == mobile.MAX_APARELHOS_POR_CONTA + 1


def test_lixo_gravado_antes_nao_vai_ao_expo_e_e_apagado(db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    admin = escola_completa["admin"]
    for i in range(250):
        db.add(DispositivoMovel(escola_id=eid, usuario_id=admin.id, plataforma="android",
                                token_push=f"lixo-qualquer-{i:05d}"))
    db.add(DispositivoMovel(escola_id=eid, usuario_id=admin.id, plataforma="ios",
                            token_push="ExponentPushToken[legitimo-0001]"))
    db.commit()
    chamadas: list[list[str]] = []

    def post(url, json=None, timeout=None):
        chamadas.append([m["to"] for m in json])
        return httpx.Response(200, json={"data": [{"status": "ok"} for _ in json]},
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", post)

    assert push.notificar_escola(db, eid, "t", "c") == 1
    assert chamadas == [["ExponentPushToken[legitimo-0001]"]], (
        f"{len(chamadas)} chamadas ao Expo com {sum(map(len, chamadas))} destinos")
    assert _tokens(db) == ["ExponentPushToken[legitimo-0001]"]


def test_so_lixo_gravado_nao_chama_o_expo(db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    db.add(DispositivoMovel(escola_id=eid, usuario_id=escola_completa["admin"].id,
                            plataforma="android", token_push="lixo-sem-formato"))
    db.commit()
    chamadas = []
    monkeypatch.setattr(httpx, "post", lambda *a, **k: chamadas.append(1))
    assert push.notificar_escola(db, eid, "t", "c") == 0
    assert chamadas == []
    assert _tokens(db) == []
