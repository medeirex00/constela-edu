"""Catraca de TODA a API: rota ou dependência ``async def`` não recebe a sessão
SÍNCRONA do banco (``get_db``).

Numa rota ``async def`` o FastAPI roda o corpo na própria thread do event loop do
worker. Cada consulta da Session síncrona feita ali para o worker inteiro: todas as
escolas e perfis que caem nele, inclusive o ``/api/health/live`` (~0,2 s por ida ao
banco em produção). Uma rota ``def`` roda numa thread do pool e não tem esse problema.

Três frentes da auditoria tiraram o banco do loop, cada uma no seu arquivo (achados
UPLOADS-1 / BANCO-1 / DESEMPENHO-1):

- importações (``routers/importacoes.py``): as rotas de upload viraram ``def``;
- administração (``routers/admin.py``): restaurar backup e enviar o logo viraram ``def``;
- sincronização (``sync/router.py``): "Salvar e validar" e "Testar conexão" continuam
  ``async`` (o login na plataforma é um ``await`` longo), mas todo o trabalho de banco
  vai para ``run_in_threadpool``.

Cada frente travou só o próprio arquivo (``test_aud_imp_rotas_fora_do_loop.py``,
``test_aud_auth_admin_uploads_fora_do_loop.py``,
``test_aud_sync_credenciais_fora_do_loop.py``). Esta catraca vale para qualquer
arquivo: rota nova com banco é ``def``. As únicas exceções são as duas rotas de
credencial, cujo contrato (nenhum comando SQL na thread do loop) é medido de verdade
em ``test_aud_sync_credenciais_fora_do_loop.py``. A lista não guarda exceção vencida:
se uma delas virar ``def`` ou deixar de usar o banco, o teste pede para tirá-la daqui.
"""
import inspect

from fastapi.routing import APIRoute, APIWebSocketRoute

from app.core.database import get_db
from app.main import app

#: Rotas ``async def`` que recebem a sessão e mandam TODO o banco para o threadpool.
#: Cada entrada exige um teste que mede zero SQL na thread do event loop.
_EXCECOES = {
    # test_aud_sync_credenciais_fora_do_loop.py (65ee2e90, BANCO-1/DESEMPENHO-1)
    "app.sync.router.salvar_credenciais",
    "app.sync.router.testar_credenciais",
}


def _nome(chamavel) -> str:
    alvo = getattr(chamavel, "__func__", chamavel)
    nome = getattr(alvo, "__qualname__", None) or type(alvo).__qualname__
    return f"{getattr(alvo, '__module__', '?')}.{nome}"


def _e_async(chamavel) -> bool:
    """Funções ``async def`` (e geradores ``async``) rodam na thread do event loop;
    também conta o objeto chamável cujo ``__call__`` é ``async``."""
    for f in (chamavel, getattr(chamavel, "__call__", None)):
        if f is not None and (inspect.iscoroutinefunction(f)
                              or inspect.isasyncgenfunction(f)):
            return True
    return False


def _usa_get_db(dependant) -> bool:
    return any(d.call is get_db or _usa_get_db(d) for d in dependant.dependencies)


def _rotas():
    rotas = [r for r in app.routes if isinstance(r, (APIRoute, APIWebSocketRoute))]
    assert len(rotas) > 100, f"só {len(rotas)} rotas: o app não carregou os routers?"
    return rotas


def _rotas_async_com_banco() -> dict[str, str]:
    return {_nome(r.endpoint): f"{sorted(getattr(r, 'methods', None) or ['WS'])[0]} "
                               f"{r.path}"
            for r in _rotas()
            if _e_async(r.endpoint) and _usa_get_db(r.dependant)}


def test_nenhuma_rota_async_recebe_a_sessao_sincrona_do_banco():
    novas = {nome: rota for nome, rota in _rotas_async_com_banco().items()
             if nome not in _EXCECOES}
    assert not novas, (
        "rotas async def com a sessão síncrona do banco (o corpo roda no event loop e "
        "cada consulta para o worker): "
        + ", ".join(f"{rota} ({nome})" for nome, rota in sorted(novas.items()))
        + ". Torne a rota `def` ou mande todo o banco para run_in_threadpool e meça "
        "com um teste como test_aud_sync_credenciais_fora_do_loop.py.")


def test_nenhuma_dependencia_async_recebe_a_sessao_sincrona_do_banco():
    """Dependência ``async`` também roda no loop: se ela recebe a sessão, a rota
    ``def`` que a usa para o worker do mesmo jeito."""
    achadas: set[str] = set()

    def percorrer(dependant):
        for d in dependant.dependencies:
            if d.call is not None and _e_async(d.call) and _usa_get_db(d):
                achadas.add(_nome(d.call))
            percorrer(d)

    for r in _rotas():
        percorrer(r.dependant)
    assert not achadas, sorted(achadas)


def test_excecoes_continuam_valendo_e_mandam_o_banco_para_o_threadpool():
    atuais = _rotas_async_com_banco()
    vencidas = sorted(_EXCECOES - set(atuais))
    assert not vencidas, (
        f"exceções que já não são async com banco: {vencidas} — tire-as de _EXCECOES")
    endpoints = {_nome(r.endpoint): r.endpoint for r in _rotas()}
    for nome in sorted(_EXCECOES):
        assert "run_in_threadpool" in inspect.getsource(endpoints[nome]), (
            f"{nome} é async com a sessão do banco e não usa run_in_threadpool")
