"""Diagnóstico da Integração Elefante (auto-inventário): o conector sonda os
endpoints com a sessão autenticada e o serviço persiste + compara (diff)."""
import asyncio

import pytest

from app.sync import diagnostico_elefante as diag
from app.sync.connectors import elefante
from app.sync.connectors.elefante import ConectorElefante
from app.sync.interfaces import Contexto, Credenciais, ErroConector

APIHOST = "https://prod-ecs-apiadmin.elefanteletrado.com.br"


# --- sinais de paginação (puro) ---------------------------------------------

def test_sinais_paginacao():
    assert ConectorElefante._sinais_paginacao([1, 2, 3]) == {
        "formato": "lista_simples", "itens": 3, "chaves_paginacao": []}
    p = ConectorElefante._sinais_paginacao(
        {"total": 120, "page": 1, "content": [1, 2]})
    assert p["formato"] == "objeto" and "total" in p["chaves_paginacao"]
    assert p["lista_em"] == "content" and p["itens"] == 2


# --- diff do inventário (puro) ----------------------------------------------

def test_comparar_primeira_vez():
    atual = {"endpoints": [{"nome": "a", "estrutura": "{x:num}"}]}
    d = diag._comparar(None, atual)
    assert d["primeira_vez"] and d["novos_endpoints"] == ["a"]


def test_comparar_detecta_mudancas():
    anterior = {"endpoints": [
        {"nome": "a", "estrutura": "{x:num}"},
        {"nome": "b", "estrutura": "{y:str}"}],
        "periodos_no_trafego": ["PERIODS.LIFETIME"]}
    atual = {"endpoints": [
        {"nome": "a", "estrutura": "{x:num, z:str}"},   # mudou
        {"nome": "c", "estrutura": "{w:num}"}],          # novo (b sumiu)
        "periodos_no_trafego": ["PERIODS.LIFETIME", "PERIODS.WEEK"]}
    d = diag._comparar(anterior, atual)
    assert d["novos_endpoints"] == ["c"]
    assert d["endpoints_sumidos"] == ["b"]
    assert d["estrutura_mudou"] == ["a"]
    assert any("mudou" in a for a in d["avisos"])
    assert any("PERIODS.WEEK" in a for a in d["avisos"])   # período novo detectado


# --- auto-inventário e2e (conector com navegador FAKE) ----------------------

class NavFake:
    def __init__(self, caps, respostas):
        self._caps, self._resp = caps, respostas

    async def ir_para(self, url): pass
    async def preencher(self, s, v): pass
    async def clicar(self, s): pass
    async def esperar(self, s, timeout_s=20): return True
    async def visivel(self, s): return "password" in s.lower() or "senha" in s.lower()
    async def texto(self, s): return ""
    async def url_atual(self): return "https://admin.elefanteletrado.com.br/reports/menu"
    async def fechar(self): pass
    async def coletar_respostas(self, url, timeout_s=25): return self._caps
    async def coletar_apos_acao(self, acao, timeout_s=20):
        try: await acao()
        except Exception: pass  # noqa: BLE001
        return []

    async def avaliar(self, expr):
        for frag, resp in self._resp.items():
            if frag in expr:
                return resp
        return {"ok": False, "status": 404, "body": None}


def _caps():
    return [
        {"url": f"{APIHOST}/school/active-schools", "json": [{"id": "123"}],
         "req_auth": "Bearer TESTE"},
        {"url": f"{APIHOST}/course/get-courses-students?schoolId=123"
                "&period=PERIODS.LIFETIME&products=1",
         "json": [{"id": "500", "student": [{"id": "9001"}]}],
         "req_auth": "Bearer TESTE"},
    ]


def _respostas():
    # o que cada endpoint devolve quando o conector chama _js_fetch
    aq = {"ok": True, "status": 200, "body": {
        "total": 42, "answeredQuestions": [
            {"questionId": 1, "correct": True, "answeredAt": "2026-03-10",
             "bookLevel": "C"}]}}
    return {
        "get-courses-students": {"ok": True, "status": 200,
                                 "body": [{"id": 500, "student": [{"id": 9001}]}]},
        "overall-course-report": {"ok": True, "status": 200,
                                  "body": {"students": [{"name": "x", "minutes": 10}]}},
        "overall-student-books-read": {"ok": True, "status": 200,
                                       "body": [{"bookId": 1, "lastReadWhen": "2026-03-01"}]},
        "overall-answered-questions": aq,
        "overall-student-report": {"ok": True, "status": 200, "body": {"history": []}},
    }


def test_diagnosticar_endpoints_captura_estrutura():
    nav = NavFake(_caps(), _respostas())

    async def fab(**_kw):
        return nav

    con = ConectorElefante(fab)
    ctx = Contexto(escola_id=1, execucao_id=None, log=lambda *a: None)
    inv = asyncio.run(con.diagnosticar_endpoints(Credenciais(usuario="u", senha="p"), ctx))

    assert inv["ok"] and inv["turmas"] == 1 and inv["auth"] == "jwt"
    assert inv["aceita_datas_personalizadas"] is True
    assert "PERIODS.LIFETIME" in inv["periodos_no_trafego"]
    por_nome = {e["nome"]: e for e in inv["endpoints"]}
    aq = por_nome["overall-answered-questions"]
    assert aq["status"] == 200
    # Estrutura capturada (só tipos/chaves) — inclui os campos por questão.
    assert "answeredQuestions" in aq["estrutura"] and "questionId" in aq["estrutura"]
    # Paginação detectada.
    assert "total" in aq["paginacao"]["chaves_paginacao"]
    assert aq["paginacao"]["lista_em"] == "answeredQuestions"
    # Parâmetros aceitos (do corpo do POST).
    assert "studentId" in aq["parametros"] and "period" in aq["parametros"]


def test_executar_sem_credencial(db, escola_completa):
    escola = escola_completa["escola"]
    with pytest.raises(ErroConector) as exc:
        diag.executar(db, escola.id)
    assert exc.value.codigo == "sem_credencial"
