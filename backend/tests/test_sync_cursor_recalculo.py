"""Sincronização automática — P3A: o cursor incremental só avança depois que os
livros do aluno CHEGARAM (falha = retenta na próxima); P3B: recálculo ÚNICO ao
final (não depende de o último arquivo ter dados); P3C: linha sem vínculo
desfaz o cursor daquele aluno (a sync retenta em vez de perder os livros)."""
import asyncio

from app.services import importacao as svc
from app.sync import service, vault
from app.sync.interfaces import ArquivoObtido, Contexto, Credenciais


# --------------------------------------------------------------------------
# P3A — cursor incremental do conector
# --------------------------------------------------------------------------
class _NavElefante:
    """Turma com 2 alunos; `lote` = resposta do books-read (lista) ou Exception."""

    def __init__(self, alunos, lote):
        self.alunos, self.lote = alunos, lote

    async def ir_para(self, url): pass
    async def preencher(self, s, v): pass
    async def clicar(self, s): pass
    async def esperar(self, s, timeout_s=20): return True
    async def visivel(self, s): return "password" in s.lower()
    async def texto(self, s): return ""
    async def url_atual(self): return "https://admin.elefanteletrado.com.br/reports/menu"
    async def fechar(self): pass

    async def coletar_respostas(self, url, timeout_s=25):
        return [{"url": "https://prod-ecs-apiadmin.elefanteletrado.com.br/course/get-courses-students",
                 "json": [{"id": 511434, "name": "5B",
                           "student": [{"id": sid, "name": nome} for sid, nome, _ in self.alunos]}]}]

    async def avaliar(self, expressao):
        if "fetch(" in expressao and "overall-course-report" in expressao:
            return {"ok": True, "status": 200, "tipo": "object", "n": 0, "body": {
                "courseId": 511434, "courseSchoolDescriptors": {"courseName": "5B"},
                "students": [{"studentId": sid, "studentName": nome, "totalBooksRead": total}
                             for sid, nome, total in self.alunos]}}
        if "fetch(" in expressao and "overall-student-books-read" in expressao:
            if isinstance(self.lote, Exception):
                raise self.lote
            return self.lote
        return {"n_selects": 0, "course_links": [], "student_links": [], "tem_exportar": False}

    async def coletar_apos_acao(self, acao, timeout_s=20):
        try:
            await acao()
        except Exception:  # noqa: BLE001
            pass
        return []
    async def baixar_acao(self, acao, timeout_s=60): return (b"", "x")
    async def baixar(self, s, timeout_s=60): return (b"", "x")


def _rodar_conector(monkeypatch, nav, anteriores):
    from app.sync.connectors import elefante
    monkeypatch.setattr(elefante, "_SETTLE_S", 0)

    async def fab(**_kw):
        return nav
    ctx = Contexto(escola_id=1, execucao_id=None, log=lambda e, n, m: None,
                   contadores_anteriores=anteriores)
    asyncio.run(elefante.ConectorElefante(fab).sincronizar(Credenciais(usuario="u", senha="p"), ctx))
    return ctx


def test_cursor_nao_avanca_quando_a_busca_de_livros_falha(monkeypatch):
    """Falha no lote: quem NÃO mudou mantém o cursor (livros já coletados antes);
    quem mudou fica SEM cursor novo → a próxima sync busca de novo. Antes o cursor
    avançava ANTES do fetch e os livros ficavam perdidos para sempre."""
    nav = _NavElefante([(4427356, "Aluno X", 86), (9999, "Aluno Novo", 3)],
                       lote=RuntimeError("timeout"))
    ctx = _rodar_conector(monkeypatch, nav, {"4427356": 86})
    assert ctx.contadores_novos == {"4427356": 86}      # 9999 NÃO avançou
    assert ctx.nome_por_sid == {"4427356": "Aluno X", "9999": "Aluno Novo"}


def test_cursor_avanca_so_para_quem_teve_os_livros_entregues(monkeypatch):
    """Lote parcial (a API devolveu só um dos dois alunos que mudaram): o cursor
    avança só para o entregue; o outro é retentado na próxima sync."""
    nav = _NavElefante([(4427356, "Aluno X", 90), (9999, "Aluno Novo", 3)],
                       lote=[{"studentId": 9999, "n": 1, "books": [
                           {"bookTitle": "Novo", "levelName": "F",
                            "lastReadWhen": "2026-06-26T08:00:00"}]}])
    ctx = _rodar_conector(monkeypatch, nav, {"4427356": 86})
    assert ctx.contadores_novos == {"9999": 3}
    assert "4427356" not in ctx.contadores_novos




# --------------------------------------------------------------------------
# P3B/P3C — serviço: recálculo único ao final + cursor de linhas ignoradas
# --------------------------------------------------------------------------
def _executar_sync_fake(db, escola, monkeypatch, resultados, contadores, nomes):
    vault.salvar_credencial(db, escola.id, "elefante", Credenciais(usuario="u", senha="p"))
    ex = service.enfileirar(db, escola.id, "elefante", origem="teste")
    db.commit()

    class ConectorFake:
        plataforma = "elefante"
        versao = "test"

        async def sincronizar(self, cred, contexto):
            contexto.contadores_novos.update(contadores)
            contexto.nome_por_sid.update(nomes)
            return [ArquivoObtido(conteudo=b"{}", nome_arquivo=f"t{i}.json", plataforma="elefante")
                    for i in range(len(resultados))]

    flags, recalcs = [], []

    def fake_aplicar(db_, escola_, arquivo, *, usuario_id, recalcular, contexto):
        flags.append(recalcular)
        return dict(resultados[len(flags) - 1])

    monkeypatch.setattr(service.connectors, "obter", lambda _p: ConectorFake())
    monkeypatch.setattr(service.orchestrator, "aplicar_arquivo", fake_aplicar)
    monkeypatch.setattr(service, "_recalcular_ao_final",
                        lambda db_, eid, plat, n: recalcs.append((eid, plat, n)))
    res = service.executar(db, ex)
    return res, flags, recalcs


def test_sync_recalcula_uma_vez_ao_final_mesmo_com_ultimo_arquivo_sem_dados(
        db, escola_completa, monkeypatch):
    """Antes: `recalcular = (i == len(arquivos)-1)` → se o ÚLTIMO arquivo vinha
    "sem_dados", a escola ficava sem recálculo. Agora nenhum arquivo recalcula e
    o serviço fecha UMA vez, se gravou alguém."""
    escola = escola_completa["escola"]
    res, flags, recalcs = _executar_sync_fake(
        db, escola, monkeypatch,
        resultados=[{"qtd_alunos": 2, "qtd_erros": 0, "qtd_turmas": 0, "importacao_id": 1,
                     "avisos": [], "ignorados": [], "sem_dados": False},
                    {"qtd_alunos": 0, "qtd_erros": 0, "qtd_turmas": 0, "importacao_id": None,
                     "avisos": ["Relatório sem linhas."], "sem_dados": True}],
        contadores={"1": 5, "2": 7}, nomes={"1": "Ana Beatriz Souza", "2": "João Pedro Barbosa"})
    assert res.status == "concluida"
    assert flags == [False, False]
    assert recalcs == [(escola.id, "elefante", 2)]
    assert service._carregar_contadores(db, escola.id, "elefante") == {"1": 5, "2": 7}


def test_sync_sem_dados_gravados_nao_recalcula(db, escola_completa, monkeypatch):
    escola = escola_completa["escola"]
    res, flags, recalcs = _executar_sync_fake(
        db, escola, monkeypatch,
        resultados=[{"qtd_alunos": 0, "qtd_erros": 0, "qtd_turmas": 0, "importacao_id": None,
                     "avisos": ["Relatório sem linhas."], "sem_dados": True}],
        contadores={"1": 5}, nomes={"1": "Ana Beatriz Souza"})
    assert res.status == "concluida" and flags == [False] and recalcs == []


def test_sync_desfaz_cursor_de_linha_ignorada(db, escola_completa, monkeypatch):
    """Linha que o confirmar NÃO vinculou (correspondência insegura/ambígua) não
    avança o cursor → a próxima sync busca os livros de novo (nada se perde)."""
    escola = escola_completa["escola"]
    service._salvar_contadores(db, escola.id, "elefante", {"1": 2, "2": 3})
    db.commit()
    _executar_sync_fake(
        db, escola, monkeypatch,
        resultados=[{"qtd_alunos": 1, "qtd_erros": 0, "qtd_turmas": 0, "importacao_id": 1,
                     "avisos": ["x"], "ignorados": [svc.normalizar_nome("JOÃO PEDRO BARBOSA")],
                     "sem_dados": False}],
        contadores={"1": 5, "2": 7}, nomes={"1": "Ana Beatriz Souza", "2": "João Pedro Barbosa"})
    # Ana avançou (2→5); João voltou ao cursor anterior (3, não 7).
    assert service._carregar_contadores(db, escola.id, "elefante") == {"1": 5, "2": 3}
