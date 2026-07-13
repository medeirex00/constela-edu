"""Sincronização INCREMENTAL SEGURA: pula a coleta pesada do aluno cujo total de
livros NÃO mudou; aluno novo/atrasado sempre coleta tudo (sem perder leitura)."""
import asyncio

from app.sync import service
from app.sync.interfaces import Contexto


def test_contadores_roundtrip_com_merge(db, escola_completa):
    escola = escola_completa["escola"]
    # 1ª sync: vazio.
    assert service._carregar_contadores(db, escola.id, "elefante") == {}

    service._salvar_contadores(db, escola.id, "elefante", {"111": 10, "222": 5})
    db.commit()
    assert service._carregar_contadores(db, escola.id, "elefante") == {"111": 10, "222": 5}

    # MERGE: turma do 222 falhou (não veio); o 111 subiu. O 222 é PRESERVADO.
    service._salvar_contadores(db, escola.id, "elefante", {"111": 12})
    db.commit()
    assert service._carregar_contadores(db, escola.id, "elefante") == {"111": 12, "222": 5}


def test_conector_pula_aluno_inalterado(monkeypatch):
    """O conector só busca os livros de quem MUDOU; aluno novo (sem contagem
    anterior) é buscado. Preenche contadores_novos com TODOS."""
    from app.sync.connectors import elefante
    monkeypatch.setattr(elefante, "_SETTLE_S", 0)

    # 2 alunos: 4427356 (inalterado: já tinha 86) e 9999 (novo).
    class NavDoisAlunos:
        def __init__(self):
            self.buscou_ids = None

        async def ir_para(self, url): pass
        async def preencher(self, s, v): pass
        async def clicar(self, s): pass
        async def esperar(self, s, timeout_s=20): return True   # login/área logada OK
        async def visivel(self, s): return "password" in s.lower()
        async def texto(self, s): return ""
        async def url_atual(self):
            return "https://admin.elefanteletrado.com.br/reports/menu"
        async def fechar(self): pass

        async def coletar_respostas(self, url, timeout_s=25):
            return [{"url": "https://prod-ecs-apiadmin.elefanteletrado.com.br/course/get-courses-students",
                     "json": [{"id": 511434, "name": "5B", "student": [
                         {"id": 4427356, "name": "Aluno X"}, {"id": 9999, "name": "Aluno Novo"}]}]}]

        async def avaliar(self, expressao):
            if "fetch(" in expressao and "overall-course-report" in expressao:
                return {"ok": True, "status": 200, "tipo": "object", "n": 0, "body": {
                    "courseId": 511434,
                    "courseSchoolDescriptors": {"courseName": "5B"},
                    "students": [
                        {"studentId": 4427356, "studentName": "Aluno X", "totalBooksRead": 86},
                        {"studentId": 9999, "studentName": "Aluno Novo", "totalBooksRead": 3}]}}
            if "fetch(" in expressao and "overall-student-books-read" in expressao:
                # captura QUAIS ids foram pedidos (devem ser só os que mudaram).
                import re
                nums = re.findall(r"\b(\d{3,})\b", expressao)
                self.buscou_ids = [n for n in nums if n in ("4427356", "9999")]
                return [{"studentId": 9999, "n": 1, "books": [
                    {"bookTitle": "Novo", "levelName": "F", "lastReadWhen": "2026-06-26T08:00:00"}]}]
            return {"n_selects": 0, "course_links": [], "student_links": [],
                    "tem_exportar": False}

        async def coletar_apos_acao(self, acao, timeout_s=20):
            try:
                await acao()
            except Exception:  # noqa: BLE001
                pass
            return []
        async def baixar_acao(self, acao, timeout_s=60): return (b"", "x")
        async def baixar(self, s, timeout_s=60): return (b"", "x")

    nav = NavDoisAlunos()

    async def fab(**_kw):
        return nav
    from app.sync.interfaces import Credenciais
    ctx = Contexto(escola_id=1, execucao_id=None, log=lambda e, n, m: None,
                   contadores_anteriores={"4427356": 86})  # já tinha 86 → inalterado
    con = elefante.ConectorElefante(fab)
    asyncio.run(con.sincronizar(Credenciais(usuario="u", senha="p"), ctx))

    # Só o aluno NOVO (9999) teve os livros buscados; o inalterado foi pulado.
    assert nav.buscou_ids == ["9999"]
    # Mas a contagem de TODOS foi registrada (para a próxima sync).
    assert ctx.contadores_novos == {"4427356": 86, "9999": 3}
