"""As rotas de upload de Importações não param o worker: o banco e a CPU rodam fora
do event loop.

``/importacoes/analisar``, ``/matriculas/analisar`` e ``/matriculas/confirmar`` eram
``async def`` e, depois do ``await arquivo.read()``, usavam a Session SÍNCRONA (e o
casamento de nomes, e a espera da trava da escola) na própria thread do loop. Numa
rota ``async`` o FastAPI não usa o threadpool: enquanto um coordenador confirmava a
Lista Piloto, o worker inteiro deixava de atender — inclusive ``/api/health/live``. Em
produção (~0,2 s por ida ao banco, 2 workers) eram minutos com metade da API parada.

O "espião" envolve a função pesada de cada rota; quando ela começa, um GET trivial é
mandado ao MESMO loop (como chegaria ao worker do uvicorn) e medimos a espera dele. A
versão com a trava da escola segura no PostgreSQL está em
``test_aud_imp_rotas_fora_do_loop_pg.py``. Dados fictícios.
"""
import asyncio
import inspect
import io
import threading
import time
from datetime import date

import httpx
import openpyxl
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.core.database import get_db
from app.core.security import hash_senha
from app.main import app
from app.models import Aluno, Matricula, Turma, Usuario

API = "/api/v1"
CT_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

#: Rotas ``async def`` com a sessão do banco que ficam em OUTROS arquivos (outras
#: frentes da auditoria: admin.py e sync/router.py). Não crescem: rota nova com banco
#: é ``def``.
_ASYNC_COM_BANCO_FORA_DAS_IMPORTACOES = {
    "app.routers.admin.restaurar_backup",
    "app.routers.admin.enviar_logo_aparencia",
    "app.sync.router.salvar_credenciais",
    "app.sync.router.testar_credenciais",
}


def _usa_get_db(dependant) -> bool:
    return any(d.call is get_db or _usa_get_db(d) for d in dependant.dependencies)


def _rotas_async_com_banco() -> set[str]:
    return {f"{r.endpoint.__module__}.{r.endpoint.__name__}"
            for r in app.routes
            if isinstance(r, APIRoute) and inspect.iscoroutinefunction(r.endpoint)
            and _usa_get_db(r.dependant)}


def test_nenhuma_rota_de_importacoes_e_async():
    from app.routers import importacoes

    assincronas = sorted(r.endpoint.__name__ for r in importacoes.router.routes
                         if inspect.iscoroutinefunction(r.endpoint))
    assert assincronas == [], (
        f"rotas async em routers/importacoes.py: {assincronas} — o FastAPI as roda na "
        "thread do event loop; com a Session síncrona, o worker para")


def test_rota_async_nova_nao_usa_a_sessao_do_banco():
    novas = _rotas_async_com_banco() - _ASYNC_COM_BANCO_FORA_DAS_IMPORTACOES
    assert not novas, sorted(novas)


# --- Medição no loop ----------------------------------------------------------

def _povoar(db, escola_id: int, n_alunos: int) -> None:
    turmas = []
    for i in range(10):
        t = Turma(escola_id=escola_id, nome=f"{1 + i % 5}º Ano {'FG'[i // 5]}",
                  ano_escolar=f"{1 + i % 5}º Ano", ano_letivo=2026)
        db.add(t)
        turmas.append(t)
    db.flush()
    for i in range(n_alunos):
        a = Aluno(escola_id=escola_id, nome=f"Crianca Ficticia {i:04d} Sobrenome Teste")
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=escola_id, aluno_id=a.id,
                         turma_id=turmas[i % 10].id, ano_letivo=2026))
    db.commit()


def _login(db, escola_id: int, email: str) -> str:
    db.add(Usuario(escola_id=escola_id, nome="Coordenação Fictícia", email=email,
                   senha_hash=hash_senha("s3nh4"), cargo="coordenador"))
    db.commit()
    r = TestClient(app).post(f"{API}/auth/login",
                             data={"username": email, "password": "s3nh4"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _relatorio_matific(n_linhas: int) -> bytes:
    linhas = ["Relatório Matific — Turma 3º Ano A",
              "Nome do aluno\tAtividades finalizadas\tPontuação média\tEstrelas"]
    linhas += [f"Menina Inventada Numero {i:05d} Da Silva\t{i % 50}\t70\t{i % 90}"
               for i in range(n_linhas)]
    return ("\n".join(linhas) + "\n").encode("utf-8")


def lista_piloto(n_turmas: int, por_turma: int) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for t in range(n_turmas):
        nome = f"{1 + t % 5}º Ano {'HIJKLMNOPQ'[t // 5]}"
        ws = wb.create_sheet(nome)
        ws.append([None, None, None, "PREFEITURA MUNICIPAL FICTICIA"])
        ws.append(["Escola:", None, "EMEF FICTICIA", None, None, None, None,
                   "Lista Piloto:", 2026])
        ws.append([])
        ws.append(["Professor:", None, f"PROFESSORA FICTICIA {t}", None, "Ano:", nome,
                   "Turno:       TARDE", None, "N.º da Classe (SED):", 300390000 + t])
        ws.append([])
        ws.append(["N.º", "RM", "RA", "Nome", "Data de Nasc."])
        for k in range(por_turma):
            ws.append([k + 1, 1000 * t + k, f"{900000000 + 1000 * t + k}-0",
                       f"ALUNO FICTICIO T{t:02d} N{k:02d} DE TESTE", date(2018, 1, 1)])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def medir(enviar_upload, modulo, nome_funcao, *, ao_comecar=None) -> dict:
    """Roda o upload; quando ``modulo.nome_funcao`` começa, manda GET /api/health/live
    ao MESMO loop e mede a espera dele desde o envio. Conta também as consultas SQL
    feitas na thread do loop (a principal)."""
    loop = asyncio.get_running_loop()
    out: dict = {"threads": [], "consultas_no_loop": 0}
    principal = threading.main_thread()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://teste", timeout=120) as c:
        async def saude(t_envio):
            r = await c.get("/api/health/live")
            out["saude"] = (r.status_code, round(time.monotonic() - t_envio, 2))

        futuros = []
        original = getattr(modulo, nome_funcao)

        def espiao(*a, **k):
            out["threads"].append(threading.current_thread().name)
            if not futuros:
                futuros.append(asyncio.run_coroutine_threadsafe(saude(time.monotonic()), loop))
                if ao_comecar is not None:
                    ao_comecar()
            return original(*a, **k)

        def contar(*_a, **_k):
            if threading.current_thread() is principal:
                out["consultas_no_loop"] += 1

        from sqlalchemy.engine import Engine
        event.listen(Engine, "before_cursor_execute", contar)
        setattr(modulo, nome_funcao, espiao)
        try:
            t0 = time.monotonic()
            r = await enviar_upload(c)
            out["upload"] = (r.status_code, round(time.monotonic() - t0, 2))
            assert futuros, f"{nome_funcao} não rodou: {r.status_code} {r.text[:200]}"
            await asyncio.wrap_future(futuros[0])
        finally:
            setattr(modulo, nome_funcao, original)
            event.remove(Engine, "before_cursor_execute", contar)
    return out


def conferir(res: dict, rota: str) -> None:
    assert res["upload"][0] == 200, res
    assert res["threads"][:1] != ["MainThread"], (
        f"{rota}: o trabalho rodou na thread do event loop ({res['threads'][:1]}); "
        f"a sonda de vida esperou {res['saude'][1]} s e {res['consultas_no_loop']} "
        "consulta(s) SQL rodaram no loop")
    assert res["consultas_no_loop"] == 0, res
    assert res["saude"][1] < 1.0, res


def test_previa_do_relatorio_roda_fora_do_event_loop(db, escola_completa):
    escola_id = escola_completa["escola"].id
    _povoar(db, escola_id, 200)
    token = _login(db, escola_id, "coord.loop1@teste.local")
    conteudo = _relatorio_matific(30)
    from app.services import importacao as svc

    async def enviar(c):
        return await c.post(f"{API}/escolas/{escola_id}/importacoes/analisar",
                            headers={"Authorization": f"Bearer {token}"},
                            files={"arquivo": ("relatorio.txt", conteudo, "text/plain")})

    conferir(asyncio.run(medir(enviar, svc, "casar_nomes")), "importacoes/analisar")


def test_previa_da_lista_piloto_roda_fora_do_event_loop(db, escola_completa):
    escola_id = escola_completa["escola"].id
    token = _login(db, escola_id, "coord.loop2@teste.local")
    conteudo = lista_piloto(4, 10)
    from app.routers import importacoes as rota

    async def enviar(c):
        return await c.post(f"{API}/escolas/{escola_id}/importacoes/matriculas/analisar",
                            headers={"Authorization": f"Bearer {token}"},
                            files={"arquivo": ("Lista Piloto 2026.xlsx", conteudo, CT_XLSX)})

    conferir(asyncio.run(medir(enviar, rota, "_simular_lista_piloto")),
             "importacoes/matriculas/analisar")


def test_confirmar_lista_piloto_roda_fora_do_event_loop(db, escola_completa):
    escola_id = escola_completa["escola"].id
    token = _login(db, escola_id, "coord.loop3@teste.local")
    conteudo = lista_piloto(4, 10)
    from app.routers import importacoes as rota

    async def enviar(c):
        return await c.post(f"{API}/escolas/{escola_id}/importacoes/matriculas/confirmar",
                            headers={"Authorization": f"Bearer {token}"},
                            files={"arquivo": ("Lista Piloto 2026.xlsx", conteudo, CT_XLSX)})

    res = asyncio.run(medir(enviar, rota, "bloquear_escola_para_importacao"))
    conferir(res, "importacoes/matriculas/confirmar")
    db.expire_all()
    assert db.query(Aluno).filter(Aluno.nome.like("ALUNO FICTICIO T%")).count() == 40
