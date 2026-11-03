"""Auxiliares dos testes de integridade do NÚCLEO da sincronização (Etapa 2).

Adaptados dos ensaios e92 (diagnóstico de 22/10/2026). Dados 100% FICTÍCIOS, sem
rede e sem login: conectores REAIS (ConectorElefante / ConectorMatific) com
navegador FALSO que responde como as APIs internas das plataformas; serviço REAL
(enfileirar → executar → orquestrador → confirmar → scoring). Banco: o ``db`` do
conftest (SQLite em memória) ou o PostgreSQL local descartável
(``test_sync_integridade_nucleo_pg.py``).
"""
from __future__ import annotations

import asyncio
import json
import re

from sqlalchemy import func, select, text

from app.models import Aluno, IdentidadeExterna, Matricula, Nota, Turma
from app.models.plataformas import Importacao, Leitura, SnapshotElefante, SnapshotMatific
from app.models.sincronizacao import (SincronizacaoAlerta, SincronizacaoExecucao,
                                      SincronizacaoLog)
from app.sync import connectors, orchestrator, service, vault
from app.sync.connectors import elefante as con_elefante
from app.sync.connectors import matific as con_matific
from app.sync.interfaces import Credenciais

API = "/api/v1"
SCHOOL_UUID = "e92e92e9-0000-0000-0000-000000000001"
COMP_UUID = "e92e92e9-0000-0000-0000-0000000000cc"


# ---------------------------------------------------------------------------
# ELEFANTE — origem simulada: {course_id: {"nome": rótulo, "alunos": [aluno...]}}
# ---------------------------------------------------------------------------
def livro(titulo, nivel="D", data="2026-09-02T10:00:00", tempo=300, book_id=None):
    b = {"bookTitle": titulo, "levelName": nivel, "lastReadWhen": data,
         "totalTimeSpent": tempo}
    if book_id is not None:
        b["bookId"] = book_id
    return b


def aluno_el(sid, nome, livros=(), *, total=None, tempo=600, resp=4, ok=2):
    livros = list(livros)
    return {"sid": sid, "nome": nome, "livros": livros,
            "total": len(livros) if total is None else total,
            "tempo": tempo, "resp": resp, "ok": ok}


class NavElefante:
    """Navegador fake que responde como a API interna do Elefante.

    Falhas controladas:
      erro_turma      {course_id: status_http}  → overall-course-report devolve esse status
      excecao_turma   {course_id}               → avaliar() levanta no course-report
      excecao_lote    {course_id}               → avaliar() levanta no lote de livros
      status_aluno    {student_id: status}      → lote devolve {studentId, status} (HTTP por aluno)
      atraso_s        segundos de espera em cada course-report (timeout)
      sem_turmas      roster vazio (lista vazia da plataforma)
    """

    def __init__(self, turmas, *, erro_turma=None, excecao_turma=(), excecao_lote=(),
                 status_aluno=None, atraso_s=0.0, sem_turmas=False,
                 school_ids=(23000,), status_roster=200, omitir_aluno=()):
        self.turmas = turmas
        self.erro_turma = dict(erro_turma or {})
        self.excecao_turma = set(excecao_turma)
        self.excecao_lote = set(excecao_lote)
        self.status_aluno = dict(status_aluno or {})
        self.atraso_s = atraso_s
        self.sem_turmas = sem_turmas
        self.school_ids = school_ids
        self.status_roster = status_roster      # HTTP da lista de turmas (API direta)
        self.omitir_aluno = set(omitir_aluno)   # aluno que o lote não devolve
        self.course_reports = []      # course_ids pedidos
        self.lotes = []               # listas de ids pedidas no lote

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

    def _cursos(self):
        if self.sem_turmas:
            return []
        return [{"id": cid, "name": t["nome"],
                 "student": [{"id": a["sid"], "name": a["nome"]}
                             for a in t["alunos"] if a["sid"] is not None]}
                for cid, t in self.turmas.items()]

    async def coletar_respostas(self, url, timeout_s=25):
        base = "https://prod-ecs-apiadmin.elefanteletrado.com.br"
        caps = [{"url": f"{base}/school/active-schools",
                 "json": [{"id": s} for s in self.school_ids], "req_auth": "Bearer FICTICIO"}]
        cursos = self._cursos()
        if cursos:
            caps.append({"url": f"{base}/course/get-courses-students", "json": cursos})
        return caps

    async def avaliar(self, expressao):
        if "fetch(" in expressao and "overall-course-report" in expressao:
            cid = int(re.search(r'"courseId":\s*(\d+)', expressao).group(1))
            self.course_reports.append(cid)
            if self.atraso_s:
                await asyncio.sleep(self.atraso_s)
            if cid in self.excecao_turma:
                raise RuntimeError("course-report falhou (simulado)")
            if cid in self.erro_turma:
                return {"ok": False, "status": self.erro_turma[cid], "tipo": "null",
                        "n": 0, "body": None}
            t = self.turmas[cid]
            alunos = []
            for a in t["alunos"]:
                linha = {"studentName": a["nome"], "totalBooksRead": a["total"],
                         "totalReadTime": a["tempo"], "responses": a["resp"],
                         "approvedResponses": a["ok"]}
                if a["sid"] is not None:
                    linha["studentId"] = a["sid"]
                alunos.append(linha)
            return {"ok": True, "status": 200, "tipo": "object", "n": 0, "body": {
                "courseId": cid,
                "courseSchoolDescriptors": {"courseName": t["nome"],
                                            "schoolName": t.get("escola", "ESCOLA FICTICIA")},
                "students": alunos}}
        if "fetch(" in expressao and "overall-student-books-read" in expressao:
            ids = json.loads(re.search(r"const ids = (\[[^\]]*\])", expressao).group(1))
            self.lotes.append(ids)
            cid_do_lote = next((cid for cid, t in self.turmas.items()
                                if any(a["sid"] in ids for a in t["alunos"])), None)
            if cid_do_lote in self.excecao_lote:
                raise RuntimeError("lote de livros falhou (simulado)")
            out = []
            for sid in ids:
                if sid in self.status_aluno:
                    out.append({"studentId": sid, "status": self.status_aluno[sid]})
                    continue
                if sid in self.omitir_aluno:
                    continue
                for t in self.turmas.values():
                    achou = next((a for a in t["alunos"] if a["sid"] == sid), None)
                    if achou is not None:
                        out.append({"studentId": sid, "n": len(achou["livros"]),
                                    "books": achou["livros"]})
                        break
            return out
        if "fetch(" in expressao:     # get-courses-students direto / sondas
            if self.status_roster != 200 and "get-courses-students" in expressao:
                return {"ok": False, "status": self.status_roster, "tipo": "null", "n": 0,
                        "body": None}
            return {"ok": True, "status": 200, "tipo": "list", "n": 0, "body": []}
        return {"n_selects": 0, "course_links": [], "student_links": [],
                "tem_exportar": False}


# ---------------------------------------------------------------------------
# MATIFIC — Placar da Escola simulado
# ---------------------------------------------------------------------------
class PlacarFake:
    """``linhas`` = [(uuid, nome_completo, klassName, estrelas, atividades)].

    Falhas controladas: ``status_ss`` (HTTP do school_student), ``excecao_ss``
    (exceção levantada no avaliar do school_student), ``atraso_s``."""

    def __init__(self):
        self.linhas = []
        self.status_ss = 200
        self.status_lb = 200
        self.renomear = {}          # campo do school_student → nome novo (API mudou)
        self.excecao_ss = None
        self.atraso_s = 0.0
        self.com_competicao = True
        self.filtros = []

    @staticmethod
    def _abrev(nome):
        partes = (nome or "X Y").split()
        return (partes[0] + " " + partes[-1][0]).upper()

    def school_student(self, expr):
        m = re.search(r"school_student/\?([^\"]+?)&school_id", expr)
        self.filtros.append(m.group(1) if m else "?")
        if self.excecao_ss is not None:
            raise self.excecao_ss
        if self.status_ss != 200:
            return {"ok": False, "status": self.status_ss, "body": {"detail": "erro simulado"}}
        data = [{"account_id": self._abrev(n), "score": str(e), "grade_code": k.split()[0],
                 "activities_completed": str(a), "klassName": k, "uuid": u or ""}
                for u, n, k, e, a in self.linhas]
        for item in data:
            for velho, novo in self.renomear.items():
                item[novo] = item.pop(velho)
        # linha-fantasma que o Matific devolve no fim do relatório
        data.append({"account_id": "", "score": "0", "grade_code": "0",
                     "activities_completed": "0", "klassName": "", "uuid": ""})
        return {"ok": True, "status": 200, "body": [{"school_id": SCHOOL_UUID, "data": data}]}

    def leaderboard(self):
        if self.status_lb != 200:
            return {"ok": False, "status": self.status_lb, "body": None}
        return {"ok": True, "status": 200, "body": {"leaderboard": [
            {"student_id": u, "student_name": n} for u, n, *_ in self.linhas if u]}}


class NavMatific:
    def __init__(self, placar: PlacarFake):
        self.placar = placar

    async def ir_para(self, url): pass
    async def preencher(self, s, v): pass
    async def clicar(self, s): pass
    async def esperar(self, s, timeout_s=20): return True
    async def visivel(self, s): return "password" in s.lower()
    async def url_atual(self):
        return "https://www.matific.com/bra/pt-br/teachers/admin/school-leaderboard/"
    async def fechar(self): pass
    async def coletar_respostas(self, url, timeout_s=25): return []
    async def estado_sessao(self): return {}

    async def avaliar(self, expr):
        p = self.placar
        if "student-leaderboard" in expr:
            return p.leaderboard()
        if "accounts/current" in expr:
            return {"ok": True, "status": 200, "body": {"school_id": SCHOOL_UUID}}
        if "competition-v2" in expr:
            corpo = [{"id": COMP_UUID, "is_live": True}] if p.com_competicao else []
            return {"ok": True, "status": 200, "body": corpo}
        if "school_student" in expr:
            if p.atraso_s:
                await asyncio.sleep(p.atraso_s)
            return p.school_student(expr)
        return {"ok": False, "status": 0, "body": None}


def _fabrica(nav):
    async def fab(**_kw):
        return nav
    return fab


def instalar(monkeypatch, *, nav_elefante=None, placar=None):
    """Registra conectores reais com navegador fake; não grava arquivo em disco."""
    monkeypatch.setattr(con_elefante, "_SETTLE_S", 0)
    registro = {}
    if nav_elefante is not None:
        registro["elefante"] = con_elefante.ConectorElefante(_fabrica(nav_elefante))
    if placar is not None:
        registro["matific"] = con_matific.ConectorMatific(_fabrica(NavMatific(placar)))
    original = connectors.obter
    monkeypatch.setattr(connectors, "obter", lambda p: registro.get(p) or original(p))
    monkeypatch.setattr(orchestrator.imp, "_guardar_temporario", lambda *a, **k: None)
    return registro


def credencial(db, eid, plataforma):
    vault.salvar_credencial(db, eid, plataforma,
                            Credenciais(usuario="robo-ficticio", senha="valor-ficticio-local"))
    db.commit()


def rodar(db, eid, plataforma, parametros=None, origem="manual"):
    """enfileirar → executar. Devolve (execucao recarregada, nome da exceção ou None)."""
    ex = service.enfileirar(db, eid, plataforma, origem=origem, parametros=parametros)
    db.commit()
    exid = ex.id
    erro = None
    try:
        service.executar(db, ex)
    except Exception as exc:  # noqa: BLE001 — o teste decide o que isso significa
        erro = type(exc).__name__
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
    db.expire_all()
    return db.get(SincronizacaoExecucao, exid), erro


def logs(db, exid):
    return [(e, n, m) for e, n, m in db.execute(
        select(SincronizacaoLog.etapa, SincronizacaoLog.nivel, SincronizacaoLog.mensagem)
        .where(SincronizacaoLog.execucao_id == exid).order_by(SincronizacaoLog.id)).all()]


def alertas_abertos(db, eid, plataforma=None):
    q = select(SincronizacaoAlerta.tipo).where(SincronizacaoAlerta.escola_id == eid,
                                               SincronizacaoAlerta.resolvido.is_(False))
    if plataforma:
        q = q.where(SincronizacaoAlerta.plataforma == plataforma)
    return sorted(t for (t,) in db.execute(q).all())


def execucoes(db, eid, plataforma=None):
    q = select(SincronizacaoExecucao).where(SincronizacaoExecucao.escola_id == eid)
    if plataforma:
        q = q.where(SincronizacaoExecucao.plataforma == plataforma)
    return list(db.execute(q.order_by(SincronizacaoExecucao.id)).scalars())


def snap_atual(db, modelo, aluno_id):
    return db.execute(select(modelo).where(modelo.aluno_id == aluno_id)
                      .order_by(modelo.data_referencia.desc(), modelo.id.desc())).scalars().first()


def contar(db, modelo, *cond):
    return db.scalar(select(func.count()).select_from(modelo).where(*cond)) or 0


def contagens(db, eid):
    return {
        "alunos": contar(db, Aluno, Aluno.escola_id == eid),
        "matriculas": contar(db, Matricula, Matricula.escola_id == eid),
        "turmas": contar(db, Turma, Turma.escola_id == eid),
        "identidades": contar(db, IdentidadeExterna, IdentidadeExterna.escola_id == eid),
        "leituras": contar(db, Leitura, Leitura.escola_id == eid),
        "eventos": db.execute(text("SELECT COUNT(*) FROM eventos_aluno WHERE escola_id=:e"),
                              {"e": eid}).scalar_one(),
        "livros": db.execute(text("SELECT COUNT(*) FROM livros")).scalar_one(),
        "snap_el": contar(db, SnapshotElefante, SnapshotElefante.escola_id == eid),
        "snap_mt": contar(db, SnapshotMatific, SnapshotMatific.escola_id == eid),
        "notas": contar(db, Nota, Nota.escola_id == eid),
        "importacoes": contar(db, Importacao, Importacao.escola_id == eid),
        "revisoes": db.execute(text("SELECT COUNT(*) FROM revisoes_identidade WHERE escola_id=:e"),
                               {"e": eid}).scalar_one(),
    }


def ident(db, eid, plataforma, id_externo):
    """aluno_id vinculado a (plataforma, id_externo) — None se não houver."""
    return db.execute(select(IdentidadeExterna.aluno_id).where(
        IdentidadeExterna.escola_id == eid, IdentidadeExterna.plataforma == plataforma,
        IdentidadeExterna.id_externo == str(id_externo))).scalars().first()


def nota(db, aluno_id):
    return db.execute(select(Nota).where(Nota.aluno_id == aluno_id)).scalars().first()


def ranking(cliente, eid, dimensao=None):
    url = f"{API}/escolas/{eid}/ranking" + (f"?dimensao={dimensao}" if dimensao else "")
    r = cliente.get(url)
    assert r.status_code == 200, r.text[:200]
    return {i["aluno_id"]: i for i in r.json()}


def novo_aluno(db, eid, turma, nome, status="ativo"):
    a = Aluno(escola_id=eid, nome=nome, status=status)
    db.add(a)
    db.flush()
    db.add(Matricula(escola_id=eid, aluno_id=a.id, turma_id=turma.id, ano_letivo=2026))
    db.flush()
    return a


def vincular(db, eid, aluno_id, plataforma, id_externo):
    db.add(IdentidadeExterna(escola_id=eid, aluno_id=aluno_id, plataforma=plataforma,
                             id_externo=str(id_externo)))
    db.flush()
