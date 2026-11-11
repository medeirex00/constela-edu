"""UPLOADS-1 / BANCO-1 / DESEMPENHO-1 (parte da administração): a restauração de
backup e o envio do logo eram rotas ``async def`` que usavam a sessão SÍNCRONA do
banco (e o Pillow) no corpo. Numa rota ``async``, o FastAPI roda o corpo na
própria thread do event loop: cada ida ao banco parava o worker inteiro — nem a
sonda de vida (``/api/health/live``) respondia enquanto o Admin Global restaurava
um backup.

O espião entra na função pesada de cada rota e, quando ela começa, pede
``/api/health/live`` ao MESMO loop e espera a resposta. Se a função roda no
loop, a sonda não consegue ser atendida (o loop está parado no espião) e o
pedido fica sem resposta até o prazo. Dados fictícios."""
import asyncio
import concurrent.futures
import inspect
import io
import threading

import httpx
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.core.database import get_db
from app.main import app
from app.models import Aluno, Matricula

API = "/api/v1"
_PRAZO_DA_SONDA_S = 5.0


def _usa_get_db(dependant) -> bool:
    return any(d.call is get_db or _usa_get_db(d) for d in dependant.dependencies)


def test_nenhuma_rota_da_administracao_e_async_com_sessao_do_banco():
    """Catraca: rota da administração com a sessão síncrona do banco é ``def``
    (o FastAPI a roda numa thread do pool, fora do event loop)."""
    rotas = [r for r in app.routes if isinstance(r, APIRoute)
             and r.endpoint.__module__ == "app.routers.admin"]
    assert rotas, "nenhuma rota de app.routers.admin encontrada"
    async_com_banco = sorted(
        f"{sorted(r.methods)[0]} {r.path} ({r.endpoint.__name__})" for r in rotas
        if inspect.iscoroutinefunction(r.endpoint) and _usa_get_db(r.dependant))
    assert not async_com_banco, (
        "rotas async def usando a sessão síncrona do banco no event loop: "
        + ", ".join(async_com_banco))


async def _medir_no_loop(enviar, modulo, nome_funcao, engine) -> dict:
    loop = asyncio.get_running_loop()
    thread_do_loop = threading.get_ident()
    out: dict = {"no_loop": None, "saude": None, "consultas_no_loop": 0}

    def contar(*_a, **_k):
        if threading.get_ident() == thread_do_loop:
            out["consultas_no_loop"] += 1

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://teste", timeout=60) as cli:
        async def saude():
            return (await cli.get("/api/health/live")).status_code

        original = getattr(modulo, nome_funcao)
        pendente: list[concurrent.futures.Future] = []

        def espiao(*a, **k):
            if not pendente:
                out["no_loop"] = threading.get_ident() == thread_do_loop
                pendente.append(asyncio.run_coroutine_threadsafe(saude(), loop))
                try:
                    out["saude"] = pendente[0].result(timeout=_PRAZO_DA_SONDA_S)
                except concurrent.futures.TimeoutError:
                    out["saude"] = "sem resposta"
            return original(*a, **k)

        setattr(modulo, nome_funcao, espiao)
        event.listen(engine, "before_cursor_execute", contar)
        try:
            resposta = await enviar(cli)
        finally:
            event.remove(engine, "before_cursor_execute", contar)
            setattr(modulo, nome_funcao, original)
        assert pendente, f"{nome_funcao} não rodou"
        await asyncio.wrap_future(pendente[0])   # a sonda atrasada termina aqui
    out["status"] = resposta.status_code
    out["corpo"] = resposta.text[:300]
    return out


def _conferir(res: dict, rota: str) -> None:
    assert res["status"] == 200, res
    assert res["no_loop"] is False, (
        f"{rota}: o trabalho síncrono rodou na thread do event loop; "
        f"/api/health/live: {res['saude']}")
    assert res["saude"] == 200, (
        f"{rota}: /api/health/live não respondeu durante o trabalho ({res['saude']})")
    assert res["consultas_no_loop"] == 0, (
        f"{rota}: {res['consultas_no_loop']} consultas ao banco na thread do event loop")


def test_restaurar_backup_roda_fora_do_event_loop(db, escola_completa, cliente_global):
    from app.services import backup as svc_backup

    escola = escola_completa["escola"]
    turma = escola_completa["turma"]
    for i in range(20):
        aluno = Aluno(escola_id=escola.id, nome=f"Crianca Ficticia {i:02d} Teste")
        db.add(aluno)
        db.flush()
        db.add(Matricula(escola_id=escola.id, aluno_id=aluno.id,
                         turma_id=turma.id, ano_letivo=2026))
    db.commit()
    backup = cliente_global.get(f"{API}/escolas/{escola.id}/backup")
    assert backup.status_code == 200, backup.text
    cabecalho = {"Authorization": cliente_global.headers["Authorization"]}

    async def enviar(cli):
        return await cli.post(f"{API}/escolas/{escola.id}/restaurar", headers=cabecalho,
                              files={"arquivo": ("backup.json", backup.content,
                                                 "application/json")})

    res = asyncio.run(_medir_no_loop(enviar, svc_backup, "restaurar", db.get_bind()))
    _conferir(res, "POST /restaurar")


def test_logo_da_aparencia_processado_fora_do_event_loop(db, escola_completa, cliente):
    import PIL.Image as modulo_imagem

    escola_id = escola_completa["escola"].id
    buf = io.BytesIO()
    modulo_imagem.new("RGB", (640, 480), (30, 60, 90)).save(buf, format="PNG")
    png = buf.getvalue()
    cabecalho = {"Authorization": cliente.headers["Authorization"]}

    async def enviar(cli):
        return await cli.post(f"{API}/escolas/{escola_id}/aparencia/logo?tipo=brasao",
                              headers=cabecalho,
                              files={"arquivo": ("brasao.png", png, "image/png")})

    res = asyncio.run(_medir_no_loop(enviar, modulo_imagem, "open", db.get_bind()))
    _conferir(res, "POST /aparencia/logo")
    # O logo continua chegando aos PDFs, reduzido.
    aparencia = TestClient(app).get(f"{API}/escolas/{escola_id}/aparencia",
                                    headers=cabecalho).json()
    assert aparencia["brasao_data_uri"].startswith("data:image/png;base64,")


def test_restaurar_continua_recusando_arquivo_acima_do_teto(
        db, escola_completa, cliente_global, monkeypatch):
    """A leitura síncrona tem teto (``arquivo.file.read(teto + 1)``): o arquivo
    grande não vai inteiro para a memória e o 413 continua."""
    import tempfile

    from app.routers import admin

    tamanhos = []
    ler = tempfile.SpooledTemporaryFile.read

    def espiao(self, *args):
        tamanhos.append(args[0] if args else -1)
        return ler(self, *args)

    monkeypatch.setattr(tempfile.SpooledTemporaryFile, "read", espiao)
    monkeypatch.setattr(admin, "TAMANHO_MAXIMO_BACKUP", 64)
    escola_id = escola_completa["escola"].id
    r = cliente_global.post(f"{API}/escolas/{escola_id}/restaurar",
                            files={"arquivo": ("backup.json", b"{" + b" " * 200 + b"}",
                                               "application/json")})
    assert r.status_code == 413, r.text
    assert tamanhos == [65]
