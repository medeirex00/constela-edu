"""Coleta do Matific pela API interna (Placar da Escola), sem PDF.

Dados ANONIMIZADOS espelhando a estrutura real capturada por DevTools:
  school_student  → data[] com account_id(abrev), score(=estrelas),
                    activities_completed, grade_code, klassName, uuid
  student-leaderboard → leaderboard[] com student_id(=uuid) + student_name(cheio)
O conector cruza por uuid (nome completo) e agrupa por turma; o analisador reusa
o pipeline do Excel do Matific (atividades/estrelas/pontuacao_media)."""
import asyncio
import json

from sqlalchemy import select

from app.services import importacao as svc
from app.sync.connectors import matific
from app.sync.interfaces import ArquivoObtido, Contexto, Credenciais


def _contexto(escola_id=1):
    return Contexto(escola_id=escola_id, execucao_id=None,
                    log=lambda etapa, nivel, msg: None)


# --- Payloads anonimizados (mesma FORMA da API real) ------------------------

_SCHOOL_STUDENT = {"ok": True, "status": 200, "body": [{
    "school_id": "e3e918e8-0000-0000-0000-000000000001",
    "total_points": 300, "school_score": 100.0, "students_count_in_school": 3,
    "data": [
        {"account_id": "ALUNO A", "score": "362", "grade_code": "3",
         "activities_completed": "100", "klassName": "3 ANO B (300396804)",
         "uuid": "aaaa1111-0000-0000-0000-000000000001"},
        {"account_id": "ALUNO B", "score": "80", "grade_code": "4",
         "activities_completed": "20", "klassName": "4 ANO A (300397061)",
         "uuid": "bbbb2222-0000-0000-0000-000000000002"},
        # sem atividade (0) — média deve ser 0, sem divisão por zero.
        {"account_id": "ALUNO C", "score": "0", "grade_code": "4",
         "activities_completed": "0", "klassName": "4 ANO A (300397061)",
         "uuid": "cccc3333-0000-0000-0000-000000000003"},
        # linha-fantasma do fim do relatório (sem nome/turma) — deve ser pulada.
        {"account_id": "", "score": "0", "grade_code": "0",
         "activities_completed": "0", "klassName": "", "uuid": ""},
    ]}]}

_STUDENT_LEADERBOARD = {"ok": True, "status": 200, "body": {"leaderboard": [
    {"student_id": "aaaa1111-0000-0000-0000-000000000001",
     "student_name": "Aluno A Sobrenome Completo", "class_name": "3 ANO B (300396804)"},
    {"student_id": "bbbb2222-0000-0000-0000-000000000002",
     "student_name": "Aluno B Sobrenome Completo", "class_name": "4 ANO A (300397061)"},
]}}


# --- Analisador --------------------------------------------------------------

def test_analisar_matific_api_mapeia_estrelas_atividades_media():
    payload = {"turma": "3 ANO B (300396804)", "alunos": [
        {"nome": "Aluno A Sobrenome Completo", "nome_abrev": "ALUNO A",
         "uuid": "x", "turma": "3 ANO B (300396804)", "estrelas": 362, "atividades": 100},
        {"nome": "", "estrelas": 5, "atividades": 1},   # sem nome → ignorado
    ]}
    analise = svc.analisar_matific_api(payload)
    assert analise.plataforma == "matific" and analise.formato == "resumo"
    assert analise.turma_detectada == "3 ANO B (300396804)"
    assert len(analise.linhas) == 1
    d = analise.linhas[0].dados
    assert analise.linhas[0].nome == "Aluno A Sobrenome Completo"
    assert d["estrelas"] == 362 and d["atividades"] == 100
    assert d["pontuacao_media"] == 3.62           # 362/100 (= "Pontuação média")
    assert d["turma_relatorio"] == "3 ANO B (300396804)"


def test_analisar_matific_api_media_zero_sem_atividade():
    analise = svc.analisar_matific_api(
        {"turma": "T", "alunos": [{"nome": "X", "estrelas": 0, "atividades": 0}]})
    assert analise.linhas[0].dados["pontuacao_media"] == 0.0


def test_analisar_matific_api_upload_multi_turma():
    """Upload da ESCOLA inteira (bookmarklet): sem ``turma`` no topo, cada aluno
    traz a sua turma em ``turma`` → vira turma_relatorio por linha."""
    payload = {"fonte": "matific-placar", "alunos": [
        {"nome": "Aluno A", "turma": "3 ANO B (300396804)", "estrelas": 100, "atividades": 40},
        {"nome": "Aluno B", "turma": "4 ANO A (300397061)", "estrelas": 80, "atividades": 20},
    ]}
    analise = svc.analisar_matific_api(payload)
    assert analise.turma_detectada == ""   # multi-turma → o front usa a turma por linha
    turmas = {l.dados["turma_relatorio"] for l in analise.linhas}
    assert turmas == {"3 ANO B (300396804)", "4 ANO A (300397061)"}
    assert analise.linhas[0].dados["pontuacao_media"] == 2.5   # 100/40


def test_analisar_matific_api_com_periodo():
    """start_date/end_date do Placar → analise.periodo_* preenchidos (import por
    período: premiação por semana/mês)."""
    analise = svc.analisar_matific_api({
        "alunos": [{"nome": "X", "turma": "T", "estrelas": 10, "atividades": 5}],
        "periodo_inicio": "2026-07-07", "periodo_fim": "2026-07-14"})
    assert analise.periodo_inicio == "2026-07-07"
    assert analise.periodo_fim == "2026-07-14"
    assert "2026-07-07" in analise.mensagem_deteccao


def test_orquestrador_matific_api_por_periodo(db, escola_completa, monkeypatch):
    """ArquivoObtido com período → dispatch para _importar_matific_periodo (o
    valor do intervalo vira snapshot do período, base do ranking por semana/mês)."""
    from datetime import datetime

    from app.models.plataformas import SnapshotMatific
    from app.sync import orchestrator

    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]  # "Ana Beatriz Souza"
    monkeypatch.setattr(orchestrator.imp, "_guardar_temporario", lambda *a, **k: None)

    payload = {"turma": "3 ANO B (300396804)",
               "periodo_inicio": "2026-07-07", "periodo_fim": "2026-07-14",
               "alunos": [{"nome": "Ana Beatriz Souza", "turma": "3 ANO B (300396804)",
                           "estrelas": 50, "atividades": 20}]}
    arq = ArquivoObtido(
        conteudo=json.dumps(payload).encode("utf-8"), nome_arquivo="matific.json",
        plataforma="matific", content_type=orchestrator.CT_MATIFIC_API,
        formato_hint="resumo",
        periodo_inicio=datetime(2026, 7, 7), periodo_fim=datetime(2026, 7, 14))
    res = orchestrator.aplicar_arquivo(
        db, escola, arq, usuario_id=None, recalcular=True, contexto=_contexto(escola.id))

    assert res["qtd_alunos"] == 1
    snaps = db.execute(select(SnapshotMatific).where(
        SnapshotMatific.aluno_id == ana.id)).scalars().all()
    # o ganho do período (50 estrelas sobre base zero) virou snapshot.
    assert any(s.estrelas == 50 for s in snaps)


def test_enfileirar_guarda_parametros_do_periodo(db, escola_completa):
    """Coleta integrada por período: a execução guarda as datas (a thread relê a
    linha pelo id) → o service injeta em cred.extra → o conector usa start_date/
    end_date. Persistência é a peça nova."""
    from app.sync import service
    escola = escola_completa["escola"]
    ex = service.enfileirar(
        db, escola.id, "matific", origem="manual",
        parametros={"matific_start_date": "2026-07-07", "matific_end_date": "2026-07-14"})
    db.commit()
    db.refresh(ex)
    assert ex.parametros == {"matific_start_date": "2026-07-07",
                             "matific_end_date": "2026-07-14"}
    # Sync normal (sem período) continua com parametros vazio.
    ex2 = service.enfileirar(db, escola.id, "elefante", origem="manual")
    db.commit()
    assert ex2.parametros == {}


def test_payload_matific_placar_detecta():
    from app.routers.importacoes import _payload_matific_placar
    bom = '{"fonte":"matific-placar","alunos":[{"nome":"X","turma":"T"}]}'
    assert _payload_matific_placar(bom) is not None
    # Não é o nosso JSON → None (segue como texto normal).
    assert _payload_matific_placar('{"foo":1}') is None
    assert _payload_matific_placar("texto qualquer colado") is None
    assert _payload_matific_placar('{"fonte":"matific-placar"}') is None  # sem alunos[]


def test_upload_json_matific_pela_api(cliente, escola_completa):
    """Upload do constela-matific.json → prévia com o aluno casado, sem PDF."""
    escola_id = escola_completa["escola"].id
    conteudo = json.dumps({"fonte": "matific-placar", "duration": "this-year", "alunos": [
        {"nome": "Ana Beatriz Souza", "nome_abrev": "Ana B",
         "turma": "3 ANO B (300396804)", "estrelas": 362, "atividades": 100}]})
    resposta = cliente.post(
        f"/api/v1/escolas/{escola_id}/importacoes/analisar",
        files={"arquivo": ("constela-matific.json", conteudo.encode("utf-8"), "application/json")},
    )
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["plataforma"] == "matific"
    assert corpo["total_alunos"] == 1
    linha = corpo["linhas"][0]
    assert linha["nome"] == "Ana Beatriz Souza"
    assert linha["dados"]["estrelas"] == 362 and linha["dados"]["pontuacao_media"] == 3.62
    # casou com a aluna real da turma (nome completo casa exato).
    assert linha["correspondencia"]["status"] == "exato"


# --- Conector: parse + join + agrupamento ------------------------------------

def test_parse_school_student_junta_nome_completo_e_pula_fantasma():
    nomes = matific.ConectorMatific._mapa_nomes(_STUDENT_LEADERBOARD)
    alunos = matific.ConectorMatific._parse_school_student(_SCHOOL_STUDENT, nomes)
    assert len(alunos) == 3          # a linha-fantasma foi descartada
    a = {x["uuid"]: x for x in alunos}
    # nome COMPLETO veio do student-leaderboard (join por uuid).
    assert a["aaaa1111-0000-0000-0000-000000000001"]["nome"] == "Aluno A Sobrenome Completo"
    assert a["aaaa1111-0000-0000-0000-000000000001"]["estrelas"] == 362
    # ALUNO C não está na competição → cai no nome abreviado do Placar.
    assert a["cccc3333-0000-0000-0000-000000000003"]["nome"] == "ALUNO C"


def test_ids_do_placar_extrai_school_e_competition():
    caps = [
        {"url": "https://www.matific.com/api/v2/reports/leaderboard/school_student/"
                "?duration=this-year&school_id=e3e918e8-0000-0000-0000-000000000001"},
        {"url": "https://www.matific.com/api/v2/competition-v2/"
                "8773b0bf-0000-0000-0000-0000000000aa/school/"
                "e3e918e8-0000-0000-0000-000000000001/student-leaderboard/"},
    ]
    school_id, comp_id = matific.ConectorMatific._ids_do_placar(caps)
    assert school_id == "e3e918e8-0000-0000-0000-000000000001"
    assert comp_id == "8773b0bf-0000-0000-0000-0000000000aa"


def test_orquestrador_importa_matific_api_json(db, escola_completa, monkeypatch):
    """Ponta a ponta: um ArquivoObtido JSON (Placar da Escola) passa pelo _parsear
    REAL (branch CT_MATIFIC_API) → casar_nomes → confirmar → SnapshotMatific com
    estrelas/atividades/média. Prova que a coleta por API entra no pipeline."""
    from app.models.plataformas import Importacao, SnapshotMatific
    from app.sync import orchestrator

    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]  # "Ana Beatriz Souza"
    monkeypatch.setattr(orchestrator.imp, "_guardar_temporario", lambda *a, **k: None)

    payload = {"turma": "3 ANO B (300396804)", "duration": "this-year", "alunos": [
        {"nome": "Ana Beatriz Souza", "nome_abrev": "Ana B",
         "uuid": "u1", "turma": "3 ANO B (300396804)", "estrelas": 362, "atividades": 100}]}
    arq = ArquivoObtido(
        conteudo=json.dumps(payload).encode("utf-8"),
        nome_arquivo="matific_3-ano-b.json", plataforma="matific",
        content_type=orchestrator.CT_MATIFIC_API, formato_hint="resumo")
    res = orchestrator.aplicar_arquivo(
        db, escola, arq, usuario_id=None, recalcular=True, contexto=_contexto(escola.id))

    assert res["qtd_alunos"] == 1 and res["sem_dados"] is False
    snap = db.execute(select(SnapshotMatific).where(
        SnapshotMatific.escola_id == escola.id,
        SnapshotMatific.aluno_id == ana.id)).scalars().first()
    assert snap is not None
    assert snap.estrelas == 362 and snap.atividades == 100
    assert snap.pontuacao_media == 3.62
    assert db.execute(select(Importacao).where(
        Importacao.escola_id == escola.id)).scalars().first() is not None


def test_sincronizar_agrupa_por_turma_com_api_interna(monkeypatch):
    """e2e do conector com um navegador FAKE: captura ids → chama as duas APIs →
    cruza nomes → emite UM arquivo por turma (2 turmas neste caso)."""

    class NavFake:
        async def ir_para(self, url): pass
        async def preencher(self, s, v): pass
        async def clicar(self, s): pass
        async def esperar(self, s, timeout_s=20): return True
        async def visivel(self, s): return "password" in s.lower()
        async def texto(self, s): return ""
        async def url_atual(self):
            return "https://www.matific.com/bra/pt-br/teachers/admin/school-leaderboard/"
        async def fechar(self): pass

        async def coletar_respostas(self, url, timeout_s=25):
            return [{"url": "https://www.matific.com/api/v2/reports/leaderboard/"
                            "school_student/?duration=this-year&"
                            "school_id=e3e918e8-0000-0000-0000-000000000001"},
                    {"url": "https://www.matific.com/api/v2/competition-v2/"
                            "8773b0bf-0000-0000-0000-0000000000aa/school/"
                            "e3e918e8-0000-0000-0000-000000000001/student-leaderboard/"}]

        async def avaliar(self, expr):
            if "student-leaderboard" in expr:      # checar ANTES de competition-v2
                return _STUDENT_LEADERBOARD
            if "accounts/current" in expr:          # fonte determinística do school_id
                return {"ok": True, "status": 200,
                        "body": {"school_id": "e3e918e8-0000-0000-0000-000000000001"}}
            if "competition-v2" in expr:            # a LISTA de competições
                return {"ok": True, "status": 200,
                        "body": [{"id": "8773b0bf-0000-0000-0000-0000000000aa", "is_live": True}]}
            if "school_student" in expr:
                return _SCHOOL_STUDENT
            return {"ok": False, "status": 0, "body": None}

        async def coletar_apos_acao(self, acao, timeout_s=20):
            try: await acao()
            except Exception: pass  # noqa: BLE001
            return []
        async def baixar(self, s, timeout_s=60): return (b"", "x")

    nav = NavFake()

    async def fab(**_kw):
        return nav
    con = matific.ConectorMatific(fab)
    ctx = Contexto(escola_id=1, execucao_id=None, log=lambda e, n, m: None)
    arquivos = asyncio.run(con.sincronizar(Credenciais(usuario="u", senha="p"), ctx))

    # 3 alunos válidos em 2 turmas → 2 arquivos.
    assert len(arquivos) == 2
    assert all(a.content_type == matific._CT_API for a in arquivos)
    turmas = set()
    for arq in arquivos:
        payload = json.loads(arq.conteudo.decode("utf-8"))
        turmas.add(payload["turma"])
        # sem datas configuradas → modo "ano todo" (sem período → import cumulativo).
        assert payload["periodo_inicio"] == "" and payload["periodo_fim"] == ""
        assert arq.periodo_inicio is None
    assert turmas == {"3 ANO B (300396804)", "4 ANO A (300397061)"}
