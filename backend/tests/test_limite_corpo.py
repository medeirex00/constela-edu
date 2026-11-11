"""Teto do corpo da requisição ANTES da autenticação (app/core/limite_corpo.py).

O FastAPI lê o corpo antes das dependências de login; no starlette 0.47 o
formulário urlencoded nem respeita max_fields/max_part_size (GHSA-82w8). O teto
recusa com 413 sem ler (Content-Length) ou ao passar do limite (chunked) — para
quem não está logado, inclusive.
"""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.limite_corpo import LimiteDeCorpoMiddleware
from app.main import app

API = "/api/v1"


@pytest.fixture()
def tetos_pequenos(monkeypatch):
    monkeypatch.setattr(settings, "LIMITE_CORPO_FORMULARIO_BYTES", 1024)
    monkeypatch.setattr(settings, "LIMITE_CORPO_MULTIPART_BYTES", 4096)
    monkeypatch.setattr(settings, "LIMITE_CORPO_OUTROS_BYTES", 2048)


def test_padroes_cobrem_os_maiores_uploads_legitimos():
    """Avaliações e INEP aceitam 150 MB (teto grande, só nessas rotas); as outras rotas de
    upload (backup 25 MB, indicadores 20 MB, importações 10 MB, logo 3 MB) cabem no teto
    comum."""
    from app.routers import admin, avaliacoes, importacoes, indicadores, rede
    assert settings.LIMITE_CORPO_MULTIPART_BYTES > avaliacoes._MAX_BYTES
    assert settings.LIMITE_CORPO_MULTIPART_BYTES > rede._MAX_BYTES_INEP
    for teto_da_rota in (admin.TAMANHO_MAXIMO_BACKUP, admin._LOGO_MAX_BYTES, importacoes.TAMANHO_MAXIMO,
                         indicadores._MAX_BYTES, indicadores._MAX_BYTES_SEDUC, indicadores._MAX_BYTES_IDEB):
        assert settings.LIMITE_CORPO_OUTROS_BYTES > teto_da_rota
    assert settings.LIMITE_CORPO_FORMULARIO_BYTES == 64 * 1024
    assert settings.LIMITE_CORPO_OUTROS_BYTES == 32 * 1024 * 1024


def test_login_com_formulario_gigante_e_recusado_sem_ler(db, tetos_pequenos):
    cliente = TestClient(app)
    resposta = cliente.post(f"{API}/auth/login",
                            data={"username": "x@y.local", "password": "a" * 5000})
    assert resposta.status_code == 413
    assert resposta.json() == {"detail": "Requisição grande demais."}
    # As camadas de fora continuam valendo na recusa: cabeçalhos de segurança e id.
    assert resposta.headers["x-content-type-options"] == "nosniff"
    assert resposta.headers.get("x-request-id")


def test_login_de_tamanho_normal_segue_o_fluxo(db, tetos_pequenos):
    cliente = TestClient(app)
    resposta = cliente.post(f"{API}/auth/login",
                            data={"username": "ninguem@y.local", "password": "errada"})
    assert resposta.status_code == 401


def test_formulario_chunked_e_cortado_ao_passar_do_teto(db, tetos_pequenos):
    """Sem Content-Length, os bytes são contados ao chegar."""
    def pedacos():
        yield b"username=x%40y.local&password="
        for _ in range(20):
            yield b"a" * 200

    cliente = TestClient(app)
    resposta = cliente.post(f"{API}/auth/login", content=pedacos(),
                            headers={"content-type": "application/x-www-form-urlencoded"})
    assert resposta.status_code == 413


def test_upload_de_anonimo_e_recusado_antes_da_autenticacao(db, escola_completa,
                                                            tetos_pequenos):
    """Sem token: o 413 vem antes do 401 — o corpo nem é lido."""
    cliente = TestClient(app)
    escola_id = escola_completa["escola"].id
    grande = cliente.post(f"{API}/escolas/{escola_id}/aparencia/logo?tipo=brasao",
                          files={"arquivo": ("logo.png", b"\x89PNG" + b"0" * 8000, "image/png")})
    assert grande.status_code == 413
    pequeno = cliente.post(f"{API}/escolas/{escola_id}/aparencia/logo?tipo=brasao",
                           files={"arquivo": ("logo.png", b"\x89PNG", "image/png")})
    assert pequeno.status_code == 401


def test_multipart_disfarcado_numa_rota_json_fica_no_teto_comum(db, tetos_pequenos):
    """O teto não vem do tipo declarado: 3000 bytes ditos multipart numa rota JSON sem
    login caem no teto comum (2048 no teste), não no de upload (4096)."""
    cliente = TestClient(app)
    for tipo in ("multipart/form-data; boundary=x", "application/json"):
        resposta = cliente.post(f"{API}/auth/redefinir-senha", content=b"a" * 3000,
                                headers={"content-type": tipo})
        assert resposta.status_code == 413, tipo


def test_login_multipart_fica_no_teto_comum(db, tetos_pequenos):
    cliente = TestClient(app)
    resposta = cliente.post(f"{API}/auth/login", files={"username": (None, "x@y.local"),
                                                        "password": (None, "a" * 3000)})
    assert resposta.status_code == 413


def test_teto_grande_so_na_rota_de_upload_e_com_token_valido(db, escola_completa, cliente,
                                                              tetos_pequenos):
    """3000 bytes: acima do teto comum (2048), abaixo do de upload (4096)."""
    arquivo = {"arquivo": ("a.xlsx", b"0" * 3000, "application/octet-stream")}
    anonimo = TestClient(app)
    assert anonimo.post(f"{API}/avaliacoes/analisar", files=arquivo).status_code == 413
    forjado = TestClient(app, headers={"Authorization": "Bearer nao.e.um.token"})
    assert forjado.post(f"{API}/avaliacoes/analisar", files=arquivo).status_code == 413
    # Token válido (admin de escola): passa pelo teto; quem barra é a rota (Admin Global).
    assert cliente.post(f"{API}/avaliacoes/analisar", files=arquivo).status_code == 403
    # Rota comum com token válido continua no teto comum.
    escola_id = escola_completa["escola"].id
    logo = {"arquivo": ("logo.png", b"\x89PNG" + b"0" * 3000, "image/png")}
    assert cliente.post(f"{API}/escolas/{escola_id}/aparencia/logo?tipo=brasao",
                        files=logo).status_code == 413


def _token_de_aluno(cliente, db, escola_completa) -> str:
    """Token REAL de aluno do Quest (mesma chave e algoritmo dos da equipe), a
    partir de um cartão emitido para a turma fictícia da fixture."""
    from sqlalchemy import select

    from app.quest.models import QuestCredencialAluno
    from app.quest.services import credenciais as svc_cred

    e, t = escola_completa["escola"], escola_completa["turma"]
    r = cliente.post(f"{API}/escolas/{e.id}/quest/turmas/{t.id}/cartoes")
    assert r.status_code == 200, r.text
    db.expire_all()
    cred = db.execute(select(QuestCredencialAluno)).scalars().first()
    return svc_cred.criar_token_aluno(cred)


def test_token_de_aluno_do_quest_nao_leva_o_teto_grande(db, escola_completa, cliente,
                                                         tetos_pequenos):
    """O token do aluno (30 dias, só com o código do cartão) passa na assinatura,
    mas não é de pessoa da equipe: fica no teto comum em toda rota de upload grande."""
    from starlette.datastructures import Headers

    from app.core.limite_corpo import _token_valido

    aluno = _token_de_aluno(cliente, db, escola_completa)
    assert _token_valido(Headers({"authorization": f"Bearer {aluno}"})) is False
    assert _token_valido(Headers({"authorization": cliente.headers["Authorization"]})) is True
    arquivo = {"arquivo": ("a.xlsx", b"0" * 3000, "application/octet-stream")}
    com_aluno = TestClient(app, headers={"Authorization": f"Bearer {aluno}"})
    for rota in ("avaliacoes/analisar", "avaliacoes/importar", "avaliacoes/importar-preset",
                 "redes/1/casar-inep"):
        assert com_aluno.post(f"{API}/{rota}", files=arquivo).status_code == 413, rota


def test_multipart_de_33mb_com_token_de_aluno_e_413(db, escola_completa, cliente):
    """Tetos REAIS (sem fixture): ~33 MB passa dos 32 MB comuns e fica abaixo dos
    160 MB de upload. Antes o corpo do aluno era aceito pelo teto e só a rota
    recusava (401) — depois de ler e gravar o corpo inteiro."""
    aluno = _token_de_aluno(cliente, db, escola_completa)
    corpo = b"x" * (33 * 1024 * 1024)
    r = TestClient(app).post(f"{API}/avaliacoes/importar",
                             files={"arquivo": ("a.csv", corpo, "text/csv")},
                             headers={"Authorization": f"Bearer {aluno}"})
    assert r.status_code == 413
    assert r.json() == {"detail": "Requisição grande demais."}


def test_422_nao_devolve_o_corpo_enviado(db):
    """O 422 padrão ecoava o corpo inteiro no campo 'input'."""
    cliente = TestClient(app)
    marca = "CORPO-QUE-NAO-PODE-VOLTAR-" * 40
    resposta = cliente.post(f"{API}/auth/redefinir-senha", content=marca.encode(),
                            headers={"content-type": "text/plain"})
    assert resposta.status_code == 422
    assert "CORPO-QUE-NAO-PODE-VOLTAR" not in resposta.text
    assert resposta.json()["detail"]                       # o erro continua explicado
    # O valor curto de um campo que é segredo (o token do link) também não volta; o de
    # um campo comum volta (test_aud_infra_eco_422.py, REG_SEGURANCA-4).
    curto = cliente.post(f"{API}/auth/redefinir-senha", json={"token": 1})
    erro = curto.json()["detail"][0]
    assert curto.status_code == 422 and erro["loc"] == ["body", "token"]
    assert "input" not in erro


def test_json_acima_do_teto(cliente, tetos_pequenos):
    resposta = cliente.post(f"{API}/auth/login", content=json.dumps({"x": "a" * 4000}),
                            headers={"content-type": "application/json"})
    assert resposta.status_code == 413


# --- O middleware isolado (ASGI cru): casos que o cliente HTTP não deixa montar ---

class _Configuracao:
    API_V1_PREFIX = "/api/v1"
    LIMITE_CORPO_FORMULARIO_BYTES = 10
    LIMITE_CORPO_MULTIPART_BYTES = 20
    LIMITE_CORPO_OUTROS_BYTES = 30


def _rodar(cabecalhos, pedacos, caminho="/api/v1/x"):
    lidos, enviados = [], []

    async def app_interno(scope, receive, send):
        while True:
            evento = await receive()
            lidos.append(evento.get("body", b""))
            if not evento.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    fila = [{"type": "http.request", "body": p, "more_body": i < len(pedacos) - 1}
            for i, p in enumerate(pedacos)]

    async def receive():
        return fila.pop(0)

    async def send(evento):
        enviados.append(evento)

    scope = {"type": "http", "path": caminho,
             "headers": [(k.encode(), v.encode()) for k, v in cabecalhos]}
    middleware = LimiteDeCorpoMiddleware(app_interno, _Configuracao())
    erro = None
    try:
        asyncio.run(middleware(scope, receive, send))
    except Exception as exc:  # noqa: BLE001 — o teste inspeciona
        erro = exc
    _rodar.sobrou = len(fila)
    return lidos, enviados, erro


@pytest.mark.parametrize("tipo, teto", [
    ("application/x-www-form-urlencoded; charset=utf-8", 10),
    ("Application/X-WWW-Form-Urlencoded", 10),
    ("multipart/form-data; boundary=x", 30),          # fora da rota de upload grande
    ("application/json", 30),
    ("", 30),
])
def test_teto_por_tipo_de_conteudo(tipo, teto):
    no_limite = _rodar([("content-type", tipo), ("content-length", str(teto))], [b"a" * teto])
    assert no_limite[1][0]["status"] == 200
    acima = _rodar([("content-type", tipo), ("content-length", str(teto + 1))], [b"a" * (teto + 1)])
    assert acima[0] == [], "o app não recebe nada"
    assert acima[1][0]["status"] == 413


def test_excesso_moderado_e_drenado_e_o_grande_fecha_a_conexao():
    """Até 2 × o teto: o corpo é lido e descartado (o navegador recebe o 413, sem RST).
    Acima: responde sem ler e fecha."""
    cabecalhos = [("content-type", "application/json")]
    lidos, enviados, _ = _rodar(cabecalhos + [("content-length", "50")], [b"a" * 25, b"a" * 25])
    assert lidos == [] and _rodar.sobrou == 0
    assert enviados[0]["status"] == 413
    assert (b"connection", b"close") not in enviados[0]["headers"]
    lidos, enviados, _ = _rodar(cabecalhos + [("content-length", "61")], [b"a" * 30, b"a" * 31])
    assert lidos == [] and _rodar.sobrou == 2
    assert (b"connection", b"close") in enviados[0]["headers"]


def test_rota_de_upload_grande_exige_token_valido_e_caminho_exato():
    """No middleware isolado (sem token válido possível aqui), toda variação de caminho e
    de token cai no teto comum (30): 31 bytes recusados."""
    cabecalhos = [("content-type", "multipart/form-data; boundary=x"), ("content-length", "31")]
    for caminho in ("/api/v1/avaliacoes/analisar", "/api/v1/redes/7/casar-inep",
                    "/api/v1/avaliacoes/analisar/../../auth/login", "/api/v1/avaliacoes/analisarx"):
        for token in ([], [("authorization", "Bearer token-invalido")], [("authorization", "Basic abc")]):
            _, enviados, _ = _rodar(cabecalhos + token, [b"a" * 31], caminho)
            assert enviados[0]["status"] == 413, (caminho, token)


@pytest.mark.parametrize("valor", ["-1", "abc", "1e3"])
def test_content_length_invalido_e_400(valor):
    lidos, enviados, erro = _rodar([("content-length", valor)], [b""])
    assert erro is None and lidos == []
    assert enviados[0]["status"] == 400


def test_chunked_levanta_413_ao_passar_do_teto():
    from fastapi import HTTPException
    lidos, enviados, erro = _rodar([("content-type", "application/json")], [b"a" * 20, b"a" * 20])
    assert isinstance(erro, HTTPException) and erro.status_code == 413
    assert enviados == []


def test_websocket_e_lifespan_passam_direto():
    chamado = []

    async def app_interno(scope, receive, send):
        chamado.append(scope["type"])

    middleware = LimiteDeCorpoMiddleware(app_interno, _Configuracao())
    for tipo in ("websocket", "lifespan"):
        asyncio.run(middleware({"type": tipo}, None, None))
    assert chamado == ["websocket", "lifespan"]
