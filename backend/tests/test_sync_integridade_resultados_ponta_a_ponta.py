"""Ponta a ponta de RESULTADO: retrato gravado pela sincronização → nota →
``/ranking`` geral, por dimensão e por período → premiações (frente C).

Fecha a lacuna V-04 do teste de aceitação e92 (``test_e92_13``): ele conferia
livros e questões, mas deixava passar o TEMPO de leitura zerado e as DATAS das
leituras erradas (mutações ``totalReadTime = 0`` e ``lastReadWhen = 2020-01-01``
não acusavam nada), e não consultava o ranking POR PERÍODO nem as premiações.

Caminho REAL: ``service.enfileirar`` → ``service.executar`` → conector real
(``ConectorElefante`` / ``ConectorMatific``) com navegador FALSO → orquestrador →
importador → ``scoring.recalcular_escola`` → rotas. Dados 100% fictícios, nenhuma
conexão de rede (o plugin ``sem_rede_e1`` bloqueia), nenhuma credencial real.

As identidades externas já vêm VINCULADAS (o id da plataforma vence o nome): a
correspondência de estudantes é da frente B e não é o que este teste mede. Os
contadores da execução (status, qtd_*) são da frente A e também ficam de fora —
aqui só o RESULTADO: o que foi gravado aparece, com os números e as datas certas.

O último teste é o caminho de ERRO (falha depois de gravar): ele depende do
recálculo no caminho de erro, que é da frente A. No ramo da frente C ele estava
``xfail(strict=True)``; na integração (fix/sync-integridade) passou a passar e o
marcador saiu — agora é um teste comum.
"""
from __future__ import annotations

import json
import re
from datetime import date

from sqlalchemy import select

from app.models import Aluno, IdentidadeExterna, Matricula, Nota, Turma
from app.models.plataformas import Leitura, SnapshotElefante, SnapshotMatific
from app.models.sincronizacao import SincronizacaoExecucao
from app.routers import importacoes as imp
from app.services import frescor_ranking
from app.sync import connectors, orchestrator, service, vault
from app.sync.connectors import elefante as con_elefante
from app.sync.connectors import matific as con_matific
from app.sync.interfaces import Credenciais

API = "/api/v1"
SCHOOL_UUID = "c93c93c9-0000-0000-0000-000000000001"
COMP_UUID = "c93c93c9-0000-0000-0000-0000000000cc"
K1, K2 = "3 ANO A (300396804)", "4 ANO B (300397061)"
CID1, CID2 = 511434, 600001


# ---------------------------------------------------------------------------
# Plataformas FALSAS (respondem como as APIs internas; nada sai da máquina)
# ---------------------------------------------------------------------------
class _NavElefante:
    """``turmas`` = {course_id: {"nome", "alunos": [{sid, nome, livros, total,
    tempo_s, resp, ok}]}}; cada livro = {bookTitle, levelName, lastReadWhen,
    totalTimeSpent}."""

    def __init__(self, turmas):
        self.turmas = turmas

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
        base = "https://prod-ecs-apiadmin.elefanteletrado.com.br"
        cursos = [{"id": cid, "name": t["nome"],
                   "student": [{"id": a["sid"], "name": a["nome"]} for a in t["alunos"]]}
                  for cid, t in self.turmas.items()]
        return [{"url": f"{base}/school/active-schools", "json": [{"id": 23000}],
                 "req_auth": "Bearer FICTICIO"},
                {"url": f"{base}/course/get-courses-students", "json": cursos}]

    async def avaliar(self, expressao):
        if "fetch(" in expressao and "overall-course-report" in expressao:
            cid = int(re.search(r'"courseId":\s*(\d+)', expressao).group(1))
            t = self.turmas[cid]
            return {"ok": True, "status": 200, "tipo": "object", "n": 0, "body": {
                "courseId": cid,
                "courseSchoolDescriptors": {"courseName": t["nome"],
                                            "schoolName": "ESCOLA FICTICIA"},
                "students": [{"studentId": a["sid"], "studentName": a["nome"],
                              "totalBooksRead": a["total"], "totalReadTime": a["tempo_s"],
                              "responses": a["resp"], "approvedResponses": a["ok"]}
                             for a in t["alunos"]]}}
        if "fetch(" in expressao and "overall-student-books-read" in expressao:
            ids = json.loads(re.search(r"const ids = (\[[^\]]*\])", expressao).group(1))
            saida = []
            for sid in ids:
                for t in self.turmas.values():
                    achou = next((a for a in t["alunos"] if a["sid"] == sid), None)
                    if achou is not None:
                        saida.append({"studentId": sid, "n": len(achou["livros"]),
                                      "books": achou["livros"]})
                        break
            return saida
        if "fetch(" in expressao:
            return {"ok": True, "status": 200, "tipo": "list", "n": 0, "body": []}
        return {"n_selects": 0, "course_links": [], "student_links": [],
                "tem_exportar": False}


class _PlacarMatific:
    """``linhas`` = [(uuid, nome_completo, klassName, estrelas, atividades)]."""

    def __init__(self):
        self.linhas = []

    def school_student(self):
        data = [{"account_id": (n.split()[0] + " " + n.split()[-1][0]).upper(),
                 "score": str(e), "grade_code": k.split()[0],
                 "activities_completed": str(a), "klassName": k, "uuid": u}
                for u, n, k, e, a in self.linhas]
        return {"ok": True, "status": 200, "body": [{"school_id": SCHOOL_UUID, "data": data}]}


class _NavMatific:
    def __init__(self, placar):
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
        if "student-leaderboard" in expr:
            return {"ok": True, "status": 200, "body": {"leaderboard": [
                {"student_id": u, "student_name": n} for u, n, *_ in self.placar.linhas]}}
        if "accounts/current" in expr:
            return {"ok": True, "status": 200, "body": {"school_id": SCHOOL_UUID}}
        if "competition-v2" in expr:
            return {"ok": True, "status": 200, "body": [{"id": COMP_UUID, "is_live": True}]}
        if "school_student" in expr:
            return self.placar.school_student()
        return {"ok": False, "status": 0, "body": None}


def _fabrica(nav):
    async def fab(**_kw):
        return nav
    return fab


def _instalar(monkeypatch, nav_elefante, placar):
    monkeypatch.setattr(con_elefante, "_SETTLE_S", 0)
    registro = {"elefante": con_elefante.ConectorElefante(_fabrica(nav_elefante)),
                "matific": con_matific.ConectorMatific(_fabrica(_NavMatific(placar)))}
    original = connectors.obter
    monkeypatch.setattr(connectors, "obter", lambda p: registro.get(p) or original(p))
    monkeypatch.setattr(orchestrator.imp, "_guardar_temporario", lambda *a, **k: None)


def _rodar(db, eid, plataforma):
    ex = service.enfileirar(db, eid, plataforma, origem="manual")
    db.commit()
    exid = ex.id
    try:
        service.executar(db, ex)
    except Exception:  # noqa: BLE001 — o resultado é o que o teste confere
        db.rollback()
    db.expire_all()
    return db.get(SincronizacaoExecucao, exid)


# ---------------------------------------------------------------------------
# Cenário: 6 crianças em 2 turmas; a força cresce com i em TODO indicador
# ---------------------------------------------------------------------------
def _livro(titulo, nivel, quando, tempo_s):
    # 13:00 sem fuso: o mesmo dia em UTC e em Brasília (o teste não depende de
    # qual dos dois o conector assume).
    return {"bookTitle": titulo, "levelName": nivel, "lastReadWhen": quando,
            "totalTimeSpent": tempo_s}


def _montar(db, escola_completa):
    escola = escola_completa["escola"]
    eid = escola.id
    t2 = Turma(escola_id=eid, nome="4º Ano B", ano_escolar="4º Ano", ano_letivo=2026)
    db.add(t2)
    db.flush()
    alunos = list(escola_completa["alunos"])
    for nome in ("Crianca Ficticia Um Silva", "Crianca Ficticia Dois Souza",
                 "Crianca Ficticia Tres Lima"):
        a = Aluno(escola_id=eid, nome=nome)
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=eid, aluno_id=a.id, turma_id=t2.id, ano_letivo=2026))
        alunos.append(a)
    esperado = []
    for i, al in enumerate(alunos, start=1):
        livros = [_livro(f"Livro Ficticio {i}-{j}", "E" if j % 2 else "D",
                         f"2026-09-{10 + j:02d}T13:00:00", 300 * (j + 1)) for j in range(i)]
        e = {"aluno_id": al.id, "nome": al.nome, "i": i, "sid": 9300000 + i,
             "uuid": f"u-c93-{i}", "klass": K1 if i <= 3 else K2,
             "cid": CID1 if i <= 3 else CID2, "livros": livros,
             "atividades": 10 * i, "estrelas": 30 * i + i * i,
             "resp": 5 * i, "ok": 3 * i}
        esperado.append(e)
        db.add(IdentidadeExterna(escola_id=eid, aluno_id=al.id, plataforma="elefante",
                                 id_externo=str(e["sid"])))
        db.add(IdentidadeExterna(escola_id=eid, aluno_id=al.id, plataforma="matific",
                                 id_externo=e["uuid"]))
    for plataforma in ("elefante", "matific"):
        vault.salvar_credencial(db, eid, plataforma,
                                Credenciais(usuario="robo-ficticio", senha="valor-ficticio-local"))
    db.commit()
    return eid, esperado


def _origem(esperado):
    turmas = {CID1: {"nome": "3 ANO A TARDE ANUAL", "alunos": []},
              CID2: {"nome": "4 ANO B TARDE ANUAL", "alunos": []}}
    for e in esperado:
        turmas[e["cid"]]["alunos"].append({
            "sid": e["sid"], "nome": e["nome"], "livros": e["livros"],
            "total": len(e["livros"]),
            "tempo_s": sum(b["totalTimeSpent"] for b in e["livros"]),
            "resp": e["resp"], "ok": e["ok"]})
    placar = _PlacarMatific()
    placar.linhas = [(e["uuid"], e["nome"], e["klass"], e["estrelas"], e["atividades"])
                     for e in esperado]
    return turmas, placar


def _min_livro(b):
    return round(b["totalTimeSpent"] / 60)


def _snap(db, modelo, aluno_id):
    return db.execute(select(modelo).where(modelo.aluno_id == aluno_id)
                      .order_by(modelo.data_referencia.desc(), modelo.id.desc())).scalars().first()


def _get(cliente, url):
    r = cliente.get(url)
    assert r.status_code == 200, (url, r.text[:300])
    return r.json()


def _premios(cliente, eid, inicio, fim):
    dados = _get(cliente, f"{API}/escolas/{eid}/premiacoes?periodo=personalizado"
                          f"&inicio={inicio}&fim={fim}&limite=50")
    return {c["chave"]: c for c in dados["categorias"]}, dados


def _sincronizar_tudo(db, eid):
    for plataforma in ("elefante", "matific"):
        _rodar(db, eid, plataforma)


# ---------------------------------------------------------------------------
# 1. Sincronização bem-sucedida: tudo o que foi gravado aparece, com datas
# ---------------------------------------------------------------------------
def test_retrato_gravado_chega_a_nota_aos_rankings_e_as_premiacoes(db, cliente, escola_completa,
                                                                   monkeypatch):
    eid, esperado = _montar(db, escola_completa)
    turmas, placar = _origem(esperado)
    _instalar(monkeypatch, _NavElefante(turmas), placar)
    _sincronizar_tudo(db, eid)
    db.expire_all()

    ordem = [e["aluno_id"] for e in sorted(esperado, key=lambda x: -x["i"])]
    for e in esperado:
        tempo_total = sum(_min_livro(b) for b in e["livros"])
        # (c) PERSISTIDO — inclusive o TEMPO e as DATAS (a lacuna V-04)
        s = _snap(db, SnapshotElefante, e["aluno_id"])
        assert (s.livros_unicos, s.questoes_tentativas, s.questoes_acertos) == (
            len(e["livros"]), e["resp"], e["ok"]), e["i"]
        assert s.tempo_leitura_min == round(sum(b["totalTimeSpent"] for b in e["livros"]) / 60)
        leituras = db.execute(select(Leitura).where(Leitura.aluno_id == e["aluno_id"])).scalars().all()
        assert sorted(lt.data.date() for lt in leituras) == sorted(
            date.fromisoformat(b["lastReadWhen"][:10]) for b in e["livros"]), e["i"]
        assert sum(lt.tempo_leitura_min or 0 for lt in leituras) == tempo_total, e["i"]
        m = _snap(db, SnapshotMatific, e["aluno_id"])
        assert (m.atividades, m.estrelas) == (e["atividades"], e["estrelas"])
        # (n) NOTA recalculada
        nota = db.execute(select(Nota).where(Nota.aluno_id == e["aluno_id"])).scalar_one()
        assert nota.aferido_leitura and nota.aferido_matematica, e["i"]
        assert nota.detalhes["dimensoes"]["leitura"]["dados"]["livros_unicos"] == len(e["livros"])

    # (e) /ranking POR DIMENSÃO e LEGADO
    dia_coleta = frescor_ranking.dia_do_retrato(
        _snap(db, SnapshotElefante, esperado[0]["aluno_id"]).data_referencia)
    for dim in ("leitura", "matematica"):
        itens = _get(cliente, f"{API}/escolas/{eid}/ranking?dimensao={dim}")
        assert [i["aluno_id"] for i in itens] == ordem, dim
        por = {i["aluno_id"]: i for i in itens}
        for e in esperado:
            dados = por[e["aluno_id"]]["dados"]
            if dim == "leitura":
                assert dados["livros_unicos"] == len(e["livros"])
            else:
                assert (dados["atividades"], dados["estrelas"]) == (e["atividades"], e["estrelas"])
    legado = _get(cliente, f"{API}/escolas/{eid}/ranking")
    assert [i["aluno_id"] for i in legado] == ordem
    assert all(i["aferido_leitura"] and i["aferido_matematica"] for i in legado)

    # (e) /ranking POR PERÍODO — Leitura pelas DATAS das leituras, com o TEMPO
    setembro = _get(cliente, f"{API}/escolas/{eid}/ranking/leitura?periodo=personalizado"
                             f"&inicio=2026-09-01&fim=2026-09-30")
    assert [i["aluno_id"] for i in setembro] == ordem
    por = {i["aluno_id"]: i for i in setembro}
    for e in esperado:
        assert por[e["aluno_id"]]["livros"] == len(e["livros"])
        assert por[e["aluno_id"]]["tempo_leitura_min"] == sum(_min_livro(b) for b in e["livros"])
    agosto = _get(cliente, f"{API}/escolas/{eid}/ranking/leitura?periodo=personalizado"
                           f"&inicio=2026-08-01&fim=2026-08-31")
    assert agosto == [], "leitura datada em setembro não pode cair em agosto"
    so_dia_11 = _get(cliente, f"{API}/escolas/{eid}/ranking/leitura?periodo=personalizado"
                              f"&inicio=2026-09-11&fim=2026-09-11")
    assert {i["aluno_id"] for i in so_dia_11} == {e["aluno_id"] for e in esperado if e["i"] >= 2}
    mat = _get(cliente, f"{API}/escolas/{eid}/ranking/matematica?periodo=tudo")
    assert [i["aluno_id"] for i in mat] == ordem
    for item in mat:
        e = next(x for x in esperado if x["aluno_id"] == item["aluno_id"])
        assert (item["atividades"], item["estrelas"]) == (e["atividades"], e["estrelas"])
        assert item["snapshot_em"] == dia_coleta.isoformat()

    # (e) PREMIAÇÕES do período
    cats, dados = _premios(cliente, eid, "2026-09-01", "2026-09-30")
    for chave, valor in (("mais_livros", lambda e: len(e["livros"])),
                         ("mais_tempo", lambda e: sum(_min_livro(b) for b in e["livros"]))):
        podio = cats[chave]["podio"]
        assert [p["aluno_id"] for p in podio] == ordem, chave
        for p in podio:
            e = next(x for x in esperado if x["aluno_id"] == p["aluno_id"])
            assert p["valor"] == valor(e), (chave, e["i"])
    assert [p["aluno_id"] for p in cats["melhor_leitor"]["podio"]] == ordem
    # O bloco de frescor da resposta diz de quando é o dado.
    assert dados["frescor"]["dimensoes"]["leitura"]["dado_mais_recente_em"] == dia_coleta.isoformat()


# ---------------------------------------------------------------------------
# 2. Nova sincronização: a mudança chega a todas as saídas sem ação manual
# ---------------------------------------------------------------------------
def test_nova_coleta_atualiza_ranking_periodo_e_premiacao(db, cliente, escola_completa,
                                                          monkeypatch):
    eid, esperado = _montar(db, escola_completa)
    turmas, placar = _origem(esperado)
    _instalar(monkeypatch, _NavElefante(turmas), placar)
    _sincronizar_tudo(db, eid)

    # A criança mais fraca (i=1) lê 9 livros em OUTUBRO e dispara no Matific.
    fraca = esperado[0]
    novos = [_livro(f"Livro Ficticio Outubro {j}", "E", f"2026-10-{1 + j:02d}T13:00:00", 900)
             for j in range(9)]
    aluno_origem = next(a for a in turmas[CID1]["alunos"] if a["sid"] == fraca["sid"])
    aluno_origem["livros"] = fraca["livros"] + novos
    aluno_origem["total"] = len(aluno_origem["livros"])
    aluno_origem["tempo_s"] = sum(b["totalTimeSpent"] for b in aluno_origem["livros"])
    placar.linhas = [(u, n, k, (5000 if u == fraca["uuid"] else e), (900 if u == fraca["uuid"] else a))
                     for u, n, k, e, a in placar.linhas]
    _sincronizar_tudo(db, eid)
    db.expire_all()

    leitura = _get(cliente, f"{API}/escolas/{eid}/ranking?dimensao=leitura")
    assert leitura[0]["aluno_id"] == fraca["aluno_id"]
    assert leitura[0]["dados"]["livros_unicos"] == 1 + 9
    assert _get(cliente, f"{API}/escolas/{eid}/ranking?dimensao=matematica")[0]["aluno_id"] \
        == fraca["aluno_id"]
    # Setembro NÃO muda (os livros novos são de outubro)…
    setembro = {i["aluno_id"]: i for i in _get(
        cliente, f"{API}/escolas/{eid}/ranking/leitura?periodo=personalizado"
                 f"&inicio=2026-09-01&fim=2026-09-30")}
    assert setembro[fraca["aluno_id"]]["livros"] == 1
    # …e outubro tem só a criança que leu em outubro, com o tempo de outubro.
    outubro = _get(cliente, f"{API}/escolas/{eid}/ranking/leitura?periodo=personalizado"
                            f"&inicio=2026-10-01&fim=2026-10-31")
    assert [(i["aluno_id"], i["livros"], i["tempo_leitura_min"]) for i in outubro] == [
        (fraca["aluno_id"], 9, 9 * 15)]
    cats, _ = _premios(cliente, eid, "2026-10-01", "2026-10-31")
    assert [(p["aluno_id"], p["valor"]) for p in cats["mais_livros"]["podio"]] == [
        (fraca["aluno_id"], 9)]
    assert [(p["aluno_id"], p["valor"]) for p in cats["mais_tempo"]["podio"]] == [
        (fraca["aluno_id"], 135)]


# ---------------------------------------------------------------------------
# 3. Falha DEPOIS de gravar: o que ficou gravado tem de aparecer (frente A)
# ---------------------------------------------------------------------------
def test_falha_depois_de_gravar_o_ranking_reflete_o_que_ficou_gravado(db, cliente, escola_completa,
                                                                      monkeypatch):
    eid, esperado = _montar(db, escola_completa)
    turmas, placar = _origem(esperado)
    _instalar(monkeypatch, _NavElefante(turmas), placar)
    _sincronizar_tudo(db, eid)

    primeira, ultima = esperado[0], esperado[-1]
    placar.linhas = [(u, n, k, e * 10, a * 10) for u, n, k, e, a in placar.linhas]
    original = imp._importar_matific

    def quebra(db_, escola_id, importacao, aluno, *a, **k):
        r = original(db_, escola_id, importacao, aluno, *a, **k)
        if aluno.id == ultima["aluno_id"]:
            raise RuntimeError("falha simulada depois de gravar")
        return r
    monkeypatch.setattr(imp, "_importar_matific", quebra)
    _rodar(db, eid, "matific")
    db.expire_all()

    gravado = _snap(db, SnapshotMatific, primeira["aluno_id"])
    rk = {i["aluno_id"]: i for i in _get(cliente, f"{API}/escolas/{eid}/ranking?dimensao=matematica")}
    assert (rk[primeira["aluno_id"]]["dados"]["atividades"],
            rk[primeira["aluno_id"]]["dados"]["estrelas"]) == (gravado.atividades, gravado.estrelas), \
        "o retrato gravado não chegou ao /ranking (falta o recálculo no caminho de erro)"
