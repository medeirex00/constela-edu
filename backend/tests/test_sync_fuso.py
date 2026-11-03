"""Fuso da coleta: regra de negócio em America/Sao_Paulo, armazenamento em UTC.

Achado da auditoria de 20/10/2026: a agenda "03:00" (horário que a escola
escolhe na tela) rodava às 03:00 UTC = MEIA-NOITE em Brasília, porque o cálculo
da próxima execução aplicava o horário direto sobre o relógio UTC. E toda data de
negócio tirada de um instante UTC vira o dia às 21h (BRT).
"""
import asyncio
import json
from datetime import date, datetime

from sqlalchemy import select

from app.models.sincronizacao import SincronizacaoConfig
from app.sync import fuso, service
from app.sync.interfaces import ArquivoObtido, Contexto, Credenciais


def _cfg(cadencia="diaria", hora="03:00", dia_semana=None):
    return SincronizacaoConfig(escola_id=1, plataforma="matific", ativo=True,
                               cadencia=cadencia, hora_local=hora, dia_semana=dia_semana)


# --------------------------------------------------------------------------
# Agenda
# --------------------------------------------------------------------------
def test_agenda_das_tres_e_tres_da_manha_em_brasilia_nao_meia_noite():
    """20/10 12:00 UTC (09:00 BRT) → próxima = 21/10 03:00 BRT = 06:00 UTC."""
    prox = service.calcular_proxima(_cfg(), datetime(2026, 10, 20, 12, 0))
    assert prox == datetime(2026, 10, 21, 6, 0)
    assert fuso.para_local(prox).hour == 3          # 03:00 no relógio da escola


def test_agenda_antes_do_horario_local_roda_no_mesmo_dia_local():
    """05:00 UTC = 02:00 BRT de 20/10: ainda dá tempo das 03:00 BRT de HOJE (06:00
    UTC). O cálculo antigo (sobre UTC) já pulava para o dia seguinte."""
    assert service.calcular_proxima(_cfg(), datetime(2026, 10, 20, 5, 0)) == \
        datetime(2026, 10, 20, 6, 0)


def test_agenda_logo_depois_do_horario_vai_para_amanha():
    assert service.calcular_proxima(_cfg(), datetime(2026, 10, 20, 6, 30)) == \
        datetime(2026, 10, 21, 6, 0)


def test_agenda_semanal_usa_o_dia_da_semana_de_brasilia():
    """19/10 01:00 UTC já é segunda no UTC, mas em Brasília ainda é DOMINGO 22h:
    a agenda "segunda 03:00" é daqui a 5 h (19/10 06:00 UTC), não "agora às 03:00
    UTC" (meia-noite de domingo para segunda em Brasília)."""
    prox = service.calcular_proxima(_cfg("semanal", dia_semana=0), datetime(2026, 10, 19, 1, 0))
    assert prox == datetime(2026, 10, 19, 6, 0)
    local = fuso.para_local(prox)
    assert local.weekday() == 0 and local.hour == 3


def test_agenda_noturna_local_atravessa_a_meia_noite_utc():
    """Agenda "23:30" (BRT) = 02:30 UTC do dia SEGUINTE — o banco guarda em UTC."""
    prox = service.calcular_proxima(_cfg(hora="23:30"), datetime(2026, 10, 20, 12, 0))
    assert prox == datetime(2026, 10, 21, 2, 30)
    assert fuso.para_local(prox).date() == date(2026, 10, 20)


def test_hora_invalida_na_agenda_e_recusada_com_422(cliente, escola_completa):
    """O padrão HH:MM aceitava "25:99" e o cálculo da próxima estourava (500)."""
    e = escola_completa["escola"].id
    r = cliente.put(f"/api/v1/escolas/{e}/sync/config/matific",
                    json={"ativo": True, "cadencia": "diaria", "hora_local": "25:99"})
    assert r.status_code == 422


def test_salvar_agenda_grava_a_proxima_em_utc(cliente, escola_completa, db):
    e = escola_completa["escola"].id
    r = cliente.put(f"/api/v1/escolas/{e}/sync/config/matific",
                    json={"ativo": True, "cadencia": "diaria", "hora_local": "03:00"})
    assert r.status_code == 200, r.text
    cfg = db.execute(select(SincronizacaoConfig).where(
        SincronizacaoConfig.escola_id == e)).scalars().one()
    assert cfg.proxima_execucao.hour == 6 and cfg.proxima_execucao.minute == 0


# --------------------------------------------------------------------------
# "Hoje" e o dia de uma leitura
# --------------------------------------------------------------------------
def test_hoje_local_das_21h_a_meia_noite_ainda_e_o_mesmo_dia():
    assert fuso.hoje_local(datetime(2026, 10, 21, 1, 30)) == date(2026, 10, 20)
    assert fuso.hoje_local(datetime(2026, 10, 21, 3, 0)) == date(2026, 10, 21)


def test_corpo_do_elefante_usa_o_hoje_de_brasilia(monkeypatch):
    """endPeriodCustom ia com a data UTC: às 22h30 (BRT) de 20/10 pedia até 21/10."""
    from app.sync.connectors.elefante import ConectorElefante

    monkeypatch.setattr(fuso, "hoje_local", lambda agora=None: date(2026, 10, 20))
    assert ConectorElefante._corpo_relatorio()["endPeriodCustom"] == "2026-10-20"


def test_instante_com_fuso_vira_horario_de_brasilia():
    assert fuso.instante_para_horario_local("2026-09-30T01:30:00Z") == \
        ("2026-09-29T22:30:00", True)
    assert fuso.instante_para_horario_local("2026-09-30T22:00:00-03:00") == \
        ("2026-09-30T22:00:00", True)
    # Sem fuso já é o horário local (pedido com timezoneOffset=180): intacto.
    assert fuso.instante_para_horario_local("2026-09-30T22:00:00") == \
        ("2026-09-30T22:00:00", False)
    # Formato brasileiro / vazio: intacto (o importador sabe ler).
    assert fuso.instante_para_horario_local("30/09/2026 22:00") == ("30/09/2026 22:00", False)
    assert fuso.instante_para_horario_local(None) == ("", False)


class _NavLeituras:
    """Elefante com UMA turma e UM aluno cujo livro foi lido às 22h30 de 29/09 em
    Brasília — a API (hipoteticamente) informando em UTC: 01:30Z de 30/09."""

    def __init__(self, quando):
        self.quando = quando

    async def ir_para(self, url): pass
    async def preencher(self, s, v): pass
    async def clicar(self, s): pass
    async def esperar(self, s, timeout_s=20): return True
    async def visivel(self, s): return "password" in s.lower()
    async def texto(self, s): return ""
    async def url_atual(self): return "https://admin.elefanteletrado.com.br/reports/menu"
    async def fechar(self): pass

    async def coletar_respostas(self, url, timeout_s=25):
        # Suposição (captura de jul/2026, não confirmada pelo Elefante): cada turma
        # traz a escola (schoolId). Sem ela, e sem active-schools, a coleta é
        # recusada (escola_nao_identificada).
        return [{"url": "https://prod-ecs-apiadmin.elefanteletrado.com.br/course/get-courses-students",
                 "json": [{"id": 511434, "name": "3 ANO A", "schoolId": 23952,
                           "student": [{"id": 101, "name": "Aluna Teste A"}]}]}]

    async def avaliar(self, expressao):
        if "fetch(" in expressao and "overall-course-report" in expressao:
            return {"ok": True, "status": 200, "body": {
                "courseId": 511434, "courseSchoolDescriptors": {"courseName": "3 ANO A"},
                "students": [{"studentId": 101, "studentName": "Aluna Teste A",
                              "totalBooksRead": 1}]}}
        if "fetch(" in expressao and "overall-student-books-read" in expressao:
            return [{"studentId": 101, "books": [
                {"bookTitle": "Livro Teste", "levelName": "F", "lastReadWhen": self.quando}]}]
        return {"n_selects": 0, "course_links": [], "student_links": [], "tem_exportar": False}

    async def coletar_apos_acao(self, acao, timeout_s=20):
        try:
            await acao()
        except Exception:  # noqa: BLE001
            pass
        return []

    async def baixar_acao(self, acao, timeout_s=60): return (b"", "x")
    async def baixar(self, s, timeout_s=60): return (b"", "x")


def _leituras_coletadas(monkeypatch, quando, logs=None):
    from app.sync.connectors import elefante
    monkeypatch.setattr(elefante, "_SETTLE_S", 0)

    async def fab(**_kw):
        return _NavLeituras(quando)

    def log(etapa, nivel, msg):
        if logs is not None:
            logs.append((nivel, msg))
    ctx = Contexto(escola_id=1, execucao_id=None, log=log)
    arquivos = asyncio.run(elefante.ConectorElefante(fab).sincronizar(
        Credenciais(usuario="u", senha="p"), ctx))
    granular = [a for a in arquivos if (a.metadados or {}).get("tipo") == "leituras"]
    assert len(granular) == 1
    return json.loads(granular[0].conteudo)["leituras"]


def test_leitura_das_22h30_em_brasilia_fica_no_dia_certo(monkeypatch):
    """Data com fuso explícito: o conector entrega o horário de Brasília (a
    convenção de Leitura.data) — 29/09, não 30/09."""
    logs: list = []
    leituras = _leituras_coletadas(monkeypatch, "2026-09-30T01:30:00Z", logs)
    assert leituras[0]["lastReadWhen"] == "2026-09-29T22:30:00"
    # A operação fica sabendo que vieram datas com fuso (o histórico antigo pode
    # ter sido gravado com o relógio UTC).
    assert any(n == "warn" and "fuso explícito" in m for n, m in logs)


def test_leitura_sem_fuso_passa_intacta(monkeypatch):
    leituras = _leituras_coletadas(monkeypatch, "2026-09-29T22:30:00")
    assert leituras[0]["lastReadWhen"] == "2026-09-29T22:30:00"


def test_ponta_a_ponta_a_leitura_noturna_entra_no_dia_de_brasilia(db, escola_completa,
                                                                   monkeypatch):
    """Do JSON normalizado pelo conector até Leitura.data: 29/09 22:30."""
    from app.models import Leitura
    from app.sync import orchestrator

    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    monkeypatch.setattr(orchestrator.imp, "_guardar_temporario", lambda *a, **k: None)
    quando, _ = fuso.instante_para_horario_local("2026-09-30T01:30:00Z")
    payload = {"courseSchoolDescriptors": {"courseName": "3 ANO A"},
               "leituras": [{"nome": ana.nome, "bookTitle": "Livro Noturno",
                             "levelName": "F", "lastReadWhen": quando}]}
    arq = ArquivoObtido(conteudo=json.dumps(payload).encode("utf-8"),
                        nome_arquivo="elefante_leituras_1.json", plataforma="elefante",
                        content_type=orchestrator.CT_ELEFANTE_API, formato_hint="leituras")
    orchestrator.aplicar_arquivo(db, escola, arq, usuario_id=None, recalcular=False,
                                 contexto=Contexto(escola_id=escola.id, execucao_id=None,
                                                   log=lambda *a: None))
    leitura = db.execute(select(Leitura).where(Leitura.aluno_id == ana.id)).scalars().one()
    assert leitura.data == datetime(2026, 9, 29, 22, 30)
