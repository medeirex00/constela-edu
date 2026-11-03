"""Elefante: o ``studentId`` usa a MESMA regra em todo o conector.

Resíduo do e97 (marco 2, §3). A identidade (``elefante_student_id``) e os
``ids_recebidos`` já usavam ``importacao.student_id_elefante`` (sem espaços, sem o
sufixo ".0", nunca só zeros), mas o cursor incremental, a busca de livros por aluno,
o ``primeiro_sid`` da sonda e a separação do aluno em várias turmas ainda usavam
``str(studentId)`` (+ ``isdigit()``). Com " 123 " ou 123.0 a conta "123" era gravada
pelo resumo, mas a criança ficava sem cursor e sem livros datados, a sonda não rodava
e a mesma conta em duas turmas não era reconhecida como repetida.

Dados 100% fictícios; navegador falso; sem rede.
"""
import asyncio
import json
import re

from app.services.importacao import student_id_elefante
from app.sync.connectors import elefante
from app.sync.interfaces import ArquivoObtido, Contexto, Credenciais

T1, T2 = 511434, 600001
UM, DOIS = 9100001, 9100002


class _NavElefante:
    """Uma turma; ``alunos`` = [(studentId CRU, nome, totalBooksRead)]. O lote de livros
    responde, para cada id pedido, com o id pedido (como a API) e um livro."""

    def __init__(self, alunos):
        self.alunos = alunos
        self.lotes: list[list] = []

    async def ir_para(self, url): pass
    async def preencher(self, s, v): pass
    async def clicar(self, s): pass
    async def esperar(self, s, timeout_s=20): return True
    async def visivel(self, s): return "password" in s.lower()
    async def texto(self, s): return ""
    async def url_atual(self): return "https://admin.elefanteletrado.com.br/reports/menu"
    async def fechar(self): pass
    async def coletar_apos_acao(self, acao, timeout_s=20): return []
    async def baixar_acao(self, acao, timeout_s=60): return (b"", "x")
    async def baixar(self, s, timeout_s=60): return (b"", "x")
    async def estado_sessao(self): return {}

    async def coletar_respostas(self, url, timeout_s=25):
        return [{"url": "https://prod-ecs-apiadmin.elefanteletrado.com.br/course/get-courses-students",
                 "json": [{"id": T1, "name": "5B", "schoolId": 23952,
                           "student": [{"id": sid, "name": nome} for sid, nome, _ in self.alunos]}]}]

    async def avaliar(self, expressao):
        if "fetch(" in expressao and "overall-course-report" in expressao:
            return {"ok": True, "status": 200, "tipo": "object", "n": 0, "body": {
                "courseId": T1, "courseSchoolDescriptors": {"courseName": "5B"},
                "students": [{"studentId": sid, "studentName": nome, "totalBooksRead": total}
                             for sid, nome, total in self.alunos]}}
        if "fetch(" in expressao and "overall-student-books-read" in expressao:
            ids = json.loads(re.search(r"const ids = (\[[^\]]*\])", expressao).group(1))
            self.lotes.append(ids)
            return [{"studentId": sid, "n": 1, "books": [
                {"bookTitle": f"Livro Ficticio {sid}", "levelName": "F",
                 "lastReadWhen": "2026-10-20T08:00:00"}]} for sid in ids]
        return {"n_selects": 0, "course_links": [], "student_links": [], "tem_exportar": False}


def _rodar(monkeypatch, nav, anteriores):
    monkeypatch.setattr(elefante, "_SETTLE_S", 0)
    sondas: list[str] = []

    async def _sonda(self, nav_, log, base, headers, creds, sid):
        sondas.append(sid)

    monkeypatch.setattr(elefante.ConectorElefante, "_sondar_por_aluno", _sonda)

    async def fab(**_kw):
        return nav
    ctx = Contexto(escola_id=1, execucao_id=None, log=lambda e, n, m: None,
                   contadores_anteriores=anteriores)
    arquivos = asyncio.run(elefante.ConectorElefante(fab).sincronizar(
        Credenciais(usuario="u", senha="p"), ctx))
    return ctx, arquivos, sondas


def test_regra_unica_do_student_id():
    assert student_id_elefante(" 9100002 ") == student_id_elefante(9100002.0) \
        == student_id_elefante("9100002.0") == student_id_elefante(9100002) == "9100002"
    assert student_id_elefante("000") == "" and student_id_elefante(None) == ""


def test_cursor_e_busca_de_livros_usam_a_regra_unica(monkeypatch):
    """" 9100002 " mudou (sem cursor) e 9100001.0 não mudou (cursor 5). Antes os dois
    caíam no ``isdigit()``: nenhum cursor, nenhum livro buscado, nenhum nome."""
    nav = _NavElefante([(" 9100002 ", "Aluno Ficticio Dois", 3),
                        (9100001.0, "Aluno Ficticio Um", 5)])
    ctx, arquivos, sondas = _rodar(monkeypatch, nav, {str(UM): 5})

    assert nav.lotes == [[DOIS]]                     # só quem mudou, com o id certo
    assert ctx.contadores_novos == {str(DOIS): 3, str(UM): 5}
    assert ctx.nome_por_sid == {str(DOIS): "Aluno Ficticio Dois", str(UM): "Aluno Ficticio Um"}
    leituras = [json.loads(a.conteudo) for a in arquivos if a.formato_hint == "leituras"]
    assert [x["studentId"] for p in leituras for x in p["leituras"]] == [str(DOIS)]
    assert sondas == [str(DOIS)]                    # primeiro_sid normalizado


def test_cursor_com_o_mesmo_total_nao_busca_de_novo(monkeypatch):
    """A chave do cursor gravada ("9100002") casa com o id cru " 9100002 " da coleta
    seguinte: o aluno que não mudou não é buscado de novo."""
    nav = _NavElefante([(" 9100002 ", "Aluno Ficticio Dois", 3)])
    ctx, _arquivos, _sondas = _rodar(monkeypatch, nav, {str(DOIS): 3})
    assert nav.lotes == []
    assert ctx.contadores_novos == {str(DOIS): 3}


def _arquivo_turma(cid, alunos):
    payload = {"courseId": cid, "courseSchoolDescriptors": {"courseName": f"T{cid}"},
               "students": alunos}
    return ArquivoObtido(conteudo=json.dumps(payload).encode("utf-8"),
                         nome_arquivo=f"elefante_turma_{cid}.json", plataforma="elefante",
                         formato_hint="resumo", metadados={"origem": "api", "course_id": cid})


def _alunos_por_turma(arquivos):
    return {a.metadados["course_id"]: [x["studentId"] for x in json.loads(a.conteudo)["students"]]
            for a in arquivos}


def test_mesma_conta_com_formatos_diferentes_em_duas_turmas_e_repetida():
    """" 9100003 " na T1 e 9100003.0 na T2, com os MESMOS números: é a mesma conta —
    fica só na primeira turma (antes eram dois ids e a T2 aplicava por cima)."""
    aluno = {"studentName": "Aluno Ficticio Tres", "totalBooksRead": 4}
    arquivos = [_arquivo_turma(T1, [{**aluno, "studentId": " 9100003 "}]),
                _arquivo_turma(T2, [{**aluno, "studentId": 9100003.0},
                                    {"studentName": "Outro Ficticio", "studentId": 9100004,
                                     "totalBooksRead": 1}])]
    ctx = Contexto(escola_id=1, execucao_id=None, log=lambda e, n, m: None)
    saida = elefante._separar_ids_em_varias_turmas(arquivos, ctx, lambda e, n, m: None)
    assert _alunos_por_turma(saida) == {T1: [" 9100003 "], T2: [9100004]}


def test_mesma_conta_com_numeros_diferentes_sai_das_duas_e_perde_o_cursor():
    """Números diferentes: não dá para saber quais são dela — sai das duas turmas e o
    cursor dela (chave normalizada "9100003") não avança."""
    arquivos = [_arquivo_turma(T1, [{"studentName": "Aluno Ficticio Tres",
                                     "studentId": " 9100003 ", "totalBooksRead": 4}]),
                _arquivo_turma(T2, [{"studentName": "Aluno Ficticio Tres",
                                     "studentId": "9100003.0", "totalBooksRead": 7},
                                    {"studentName": "Outro Ficticio", "studentId": 9100004,
                                     "totalBooksRead": 1}])]
    ctx = Contexto(escola_id=1, execucao_id=None, log=lambda e, n, m: None,
                   contadores_novos={"9100003": 7, "9100004": 1})
    saida = elefante._separar_ids_em_varias_turmas(arquivos, ctx, lambda e, n, m: None)
    assert _alunos_por_turma(saida) == {T2: [9100004]}
    assert ctx.contadores_novos == {"9100004": 1}
    assert ctx.coleta["descartes"] == {"id_em_varias_turmas": 2}
