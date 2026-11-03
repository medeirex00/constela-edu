"""Revisão adversarial e93 (lente: regressão) do fix/sync-integridade @2582092.

Reproduções do revisor (``scratchpad/e93/rev-regressao``), trazidas sem mudar
as asserções: passavam no 34f1a23 e no c5e78d3 e falhavam no 2582092 (R1c, R1d,
R2, R3, R3c, R4, R4b, R5). Dados 100% fictícios, conectores reais com navegador
falso, plugin sem rede. Cada teste IMPRIME o que mediu (``-s``) e afirma o
comportamento DESEJADO (o do c5e78d3 quando ele era o certo).
"""
from datetime import timedelta

from sqlalchemy import select

from app.models.plataformas import SnapshotMatific
from app.models.sincronizacao import SincronizacaoConfig
from app.sync import service
from tests._sync_nucleo_fakes import (
    NavElefante, PlacarFake, aluno_el, alertas_abertos, credencial, instalar, livro,
    logs, rodar, snap_atual, vincular)

CID = 511434
K = "3 ANO A (300396804)"


def _livro_sem_data(titulo="Livro Ficticio Sem Data"):
    # Livro com título mas sem data utilizável (o caso real "data não
    # parseável" da memória elefante-data-da-ultima-leitura-e-cursor).
    return {"bookTitle": titulo, "levelName": "D", "lastReadWhen": None,
            "totalTimeSpent": 60}


def _origem(ec, *, defeito=True):
    a, b, c = ec["alunos"]
    livros_a = [livro("Livro Ficticio Um")] + ([_livro_sem_data()] if defeito else [])
    return {CID: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
        aluno_el(9100001, a.nome, livros_a),
        aluno_el(9100002, b.nome, [livro("Livro Ficticio Dois", "E", "2026-09-05T10:00:00")]),
        aluno_el(9100003, c.nome, [livro("Livro Ficticio Tres", "D", "2026-09-06T10:00:00")])]}}


def _rodadas(db, eid, nav, n):
    saida = []
    for _ in range(n):
        antes = len(nav.lotes)
        ex, erro = rodar(db, eid, "elefante")
        pedidos = sum(len(x) for x in nav.lotes[antes:])
        completa = any("Recoleta COMPLETA" in m for _e, _n, m in logs(db, ex.id))
        saida.append({"status": ex.status, "motivo": getattr(ex, "motivo", None),
                      "completa": completa, "alunos_buscados": pedidos, "erro": erro})
    return saida


# ---------------------------------------------------------------------------
# R1 — UMA linha com defeito permanente faz TODA coleta seguinte virar
#      recoleta completa (o cursor nunca mais vale) e 'parcial' para sempre.
# ---------------------------------------------------------------------------
def test_r1_defeito_permanente_nao_prende_em_recoleta_completa(db, escola_completa,
                                                               monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "elefante")
    nav = NavElefante(_origem(escola_completa))
    instalar(monkeypatch, nav_elefante=nav)
    r = _rodadas(db, eid, nav, 4)
    print("\nR1 rodadas:", r)
    # Depois da 1ª recoleta completa (rodada 2), a semanal só volta em 7 dias:
    # as rodadas 3 e 4 têm de ser incrementais (cursor valendo, ninguém buscado).
    assert [x["completa"] for x in r[2:]] == [False, False], r
    assert [x["alunos_buscados"] for x in r[2:]] == [0, 0], r


def test_r1b_controle_sem_defeito_volta_ao_incremental(db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "elefante")
    nav = NavElefante(_origem(escola_completa, defeito=False))
    instalar(monkeypatch, nav_elefante=nav)
    r = _rodadas(db, eid, nav, 4)
    print("\nR1b rodadas:", r)
    assert [x["completa"] for x in r[2:]] == [False, False], r


# ---------------------------------------------------------------------------
# R2 — com a agenda diária ativa, a mesma linha com defeito deixa a escola
#      "desatualizada" (alerta crítico + /status) apesar de o dado entrar todo dia.
# ---------------------------------------------------------------------------
def test_r2_defeito_permanente_nao_deixa_escola_desatualizada(db, escola_completa,
                                                              monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "elefante")
    cfg = SincronizacaoConfig(escola_id=eid, plataforma="elefante", ativo=True,
                              cadencia="diaria")
    db.add(cfg)
    db.commit()
    # Agenda ligada há 3 dias (a referência quando nunca houve coleta "em dia").
    cfg.updated_at = service._agora() - timedelta(days=3)
    db.commit()
    nav = NavElefante(_origem(escola_completa))
    instalar(monkeypatch, nav_elefante=nav)
    r = _rodadas(db, eid, nav, 2)
    abertos = alertas_abertos(db, eid, "elefante")
    db.refresh(cfg)
    desat = service.esta_desatualizada(db, cfg)
    print("\nR2 rodadas:", r, "alertas:", abertos, "desatualizada:", desat,
          "ultimo_sucesso:", service.ultimo_sucesso_em(db, eid, "elefante"))
    assert service.ultimo_sucesso_em(db, eid, "elefante") is not None
    assert not desat and "desatualizada" not in abertos, (r, abertos)


# ---------------------------------------------------------------------------
# R3 — o endpoint ACESSÓRIO de nomes (student-leaderboard) respondendo erro
#      derruba a coleta inteira — inclusive de quem já está vinculado por uuid.
# ---------------------------------------------------------------------------
def _matific(db, ec, monkeypatch, status_lb):
    eid = ec["escola"].id
    a, b, c = ec["alunos"]
    credencial(db, eid, "matific")
    for al, u in ((a, "u-a"), (b, "u-b"), (c, "u-c")):
        vincular(db, eid, al.id, "matific", u)
    db.commit()
    placar = PlacarFake()
    placar.linhas = [("u-a", a.nome, K, 40, 10), ("u-b", b.nome, K, 30, 8),
                     ("u-c", c.nome, K, 20, 5)]
    placar.status_lb = status_lb
    instalar(monkeypatch, placar=placar)
    return eid, (a, b, c)


def test_r3_nomes_404_nao_derruba_coleta_de_quem_tem_uuid(db, escola_completa, monkeypatch):
    eid, (a, b, c) = _matific(db, escola_completa, monkeypatch, 404)
    ex, erro = rodar(db, eid, "matific")
    snaps = {al.id: getattr(snap_atual(db, SnapshotMatific, al.id), "estrelas", None)
             for al in (a, b, c)}
    print("\nR3 status:", ex.status, getattr(ex, "motivo", None), "erro:", erro,
          "resumo:", (ex.erro_resumo or "")[:120], "estrelas:", snaps,
          "alertas:", alertas_abertos(db, eid, "matific"))
    assert ex.status in ("concluida", "parcial"), ex.status
    assert set(snaps.values()) == {40, 30, 20}


def test_r3b_controle_nomes_200(db, escola_completa, monkeypatch):
    eid, (a, b, c) = _matific(db, escola_completa, monkeypatch, 200)
    ex, erro = rodar(db, eid, "matific")
    print("\nR3b status:", ex.status, "erro:", erro)
    assert ex.status == "concluida"


def test_r3c_placar_ao_vivo_com_nomes_404(db, escola_completa, monkeypatch):
    """Mesmo cenário pelo placar AO VIVO (o núcleo _coletar_do_placar é
    compartilhado): o ranking do dia deixa de sair?"""
    from app.sync.connectors import matific as con_matific
    from tests._sync_nucleo_fakes import NavMatific
    import asyncio
    eid, _ = _matific(db, escola_completa, monkeypatch, 404)
    placar = PlacarFake()
    placar.linhas = [("u-a", "Ana Beatriz Souza", K, 40, 10)]
    placar.status_lb = 404
    conector = con_matific.ConectorMatific(None)
    msgs = []
    try:
        alunos = asyncio.run(conector._coletar_do_placar(
            NavMatific(placar), "duration=this-year",
            lambda *a: msgs.append(a)))
        resultado = ("ok", len(alunos))
    except Exception as exc:  # noqa: BLE001
        resultado = ("levantou", type(exc).__name__, getattr(exc, "codigo", None))
    print("\nR3c:", resultado)
    assert resultado[0] == "ok", resultado


# ---------------------------------------------------------------------------
# R1c — o caso REAL: a escola tem atividade todo dia (uma criança lê um livro
#       novo entre uma coleta e outra) e UMA leitura antiga sem data.
# ---------------------------------------------------------------------------
def test_r1c_defeito_permanente_com_atividade_diaria(db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "elefante")
    origem = _origem(escola_completa)
    nav = NavElefante(origem)
    instalar(monkeypatch, nav_elefante=nav)
    b = origem[CID]["alunos"][1]
    r = []
    for dia in range(5):
        if dia:
            b["livros"].append(livro(f"Livro Ficticio Novo {dia}", "E",
                                     f"2026-10-{10 + dia:02d}T10:00:00"))
            b["total"] = len(b["livros"])
        r += _rodadas(db, eid, nav, 1)
    print("\nR1c rodadas:", r)
    # Rodada 2 = a recoleta completa semanal; da 3 em diante o cursor tem de
    # valer (só a criança que leu é buscada).
    assert [x["completa"] for x in r[2:]] == [False, False, False], r
    assert [x["alunos_buscados"] for x in r[2:]] == [1, 1, 1], r


# ---------------------------------------------------------------------------
# R4 — escola com UMA pendência de identidade legítima (decisão humana) e
#      coleta funcionando: três dias sem leitura nova (feriado/férias) e a
#      integração vira "desatualizada" — antes, não.
# ---------------------------------------------------------------------------
def test_r4_pendencia_de_identidade_em_ferias_nao_deixa_desatualizada(
        db, escola_completa, monkeypatch):
    from app.services import politica_sync
    from tests._sync_nucleo_fakes import execucoes
    eid = escola_completa["escola"].id
    credencial(db, eid, "elefante")
    politica_sync.definir(db, eid, "bloquear")
    cfg = SincronizacaoConfig(escola_id=eid, plataforma="elefante", ativo=True,
                              cadencia="diaria")
    db.add(cfg)
    db.commit()
    origem = _origem(escola_completa, defeito=False)
    origem[CID]["alunos"].append(aluno_el(9100009, "Crianca Ficticia Sem Ficha",
                                          [livro("Livro Ficticio Nove")]))
    nav = NavElefante(origem)
    instalar(monkeypatch, nav_elefante=nav)
    r = _rodadas(db, eid, nav, 1)
    # Três dias se passam (nenhuma criança lê): recua a execução e a agenda.
    for ex in execucoes(db, eid, "elefante"):
        ex.finalizada_em = ex.finalizada_em - timedelta(days=3)
        ex.iniciada_em = ex.iniciada_em - timedelta(days=3)
        ex.created_at = ex.created_at - timedelta(days=3)
    cfg.updated_at = service._agora() - timedelta(days=10)
    db.commit()
    r += _rodadas(db, eid, nav, 1)
    db.refresh(cfg)
    desat = service.esta_desatualizada(db, cfg)
    abertos = alertas_abertos(db, eid, "elefante")
    print("\nR4 rodadas:", r, "desatualizada:", desat, "alertas:", abertos)
    assert not desat and "desatualizada" not in abertos, (r, abertos)


# ---------------------------------------------------------------------------
# R5 — UMA criança sem ficha (bloquear) com 5 livros: quantas "em revisão" a
#      execução diz? (a tela mostra o número com destaque)
# ---------------------------------------------------------------------------
def test_r5_em_revisao_conta_criancas_nao_livros(db, escola_completa, monkeypatch):
    from app.services import politica_sync
    from sqlalchemy import text
    eid = escola_completa["escola"].id
    credencial(db, eid, "elefante")
    politica_sync.definir(db, eid, "bloquear")
    db.commit()
    origem = _origem(escola_completa, defeito=False)
    origem[CID]["alunos"].append(aluno_el(
        9100009, "Crianca Ficticia Sem Ficha",
        [livro(f"Livro Ficticio R5 {i}", "D", f"2026-09-1{i}T10:00:00") for i in range(5)]))
    nav = NavElefante(origem)
    instalar(monkeypatch, nav_elefante=nav)
    ex, _ = rodar(db, eid, "elefante")
    pend = db.execute(text("SELECT COUNT(*) FROM revisoes_identidade WHERE escola_id=:e "
                           "AND status='pendente'"), {"e": eid}).scalar_one()
    print("\nR5:", ex.status, "qtd_em_revisao:", getattr(ex, "qtd_em_revisao", None),
          "qtd_erros:", ex.qtd_erros, "pendencias:", pend)
    assert getattr(ex, "qtd_em_revisao", None) in (None, 1, pend), ex.qtd_em_revisao


def test_r4b_status_da_escola_com_defeito_permanente(db, cliente, escola_completa, monkeypatch):
    """O /status que a tela lê no cenário R2 (agenda diária, uma leitura sem data,
    dado entrando): o que o card mostra?"""
    eid = escola_completa["escola"].id
    credencial(db, eid, "elefante")
    cfg = SincronizacaoConfig(escola_id=eid, plataforma="elefante", ativo=True,
                              cadencia="diaria")
    db.add(cfg)
    db.commit()
    cfg.updated_at = service._agora() - timedelta(days=3)
    db.commit()
    origem = _origem(escola_completa)
    nav = NavElefante(origem)
    instalar(monkeypatch, nav_elefante=nav)
    b = origem[CID]["alunos"][1]
    for dia in range(3):
        if dia:
            b["livros"].append(livro(f"Livro Ficticio B {dia}", "E", f"2026-10-1{dia}T10:00:00"))
            b["total"] = len(b["livros"])
        _rodadas(db, eid, nav, 1)
    st = cliente.get(f"/api/v1/escolas/{eid}/sync/status").json()
    p = next(x for x in st["plataformas"] if x["plataforma"] == "elefante")
    chaves = ("ultimo_status", "ultimo_motivo", "desatualizada", "frescor",
              "ultimo_sucesso_em", "ultima_verificacao_em")
    print("\nR4b /status:", {k: p.get(k) for k in chaves})
    assert p["desatualizada"] is False, {k: p.get(k) for k in chaves}


def test_r1d_um_aluno_com_erro_persistente_no_endpoint_de_livros(db, escola_completa,
                                                                 monkeypatch):
    """Variante: o pedido de livros de UMA criança volta HTTP 500 sempre."""
    eid = escola_completa["escola"].id
    credencial(db, eid, "elefante")
    origem = _origem(escola_completa, defeito=False)
    nav = NavElefante(origem, status_aluno={9100003: 500})
    instalar(monkeypatch, nav_elefante=nav)
    b = origem[CID]["alunos"][1]
    r = []
    for dia in range(4):
        if dia:
            b["livros"].append(livro(f"Livro Ficticio D {dia}", "E", f"2026-10-1{dia}T10:00:00"))
            b["total"] = len(b["livros"])
        r += _rodadas(db, eid, nav, 1)
    print("\nR1d rodadas:", r)
    assert [x["completa"] for x in r[2:]] == [False, False], r


# ---------------------------------------------------------------------------
# R7 — cobertura que o ajuste de test_api_com_campo_ausente_preserva_snapshot_valido
#      deixou sem teste: campo NÃO essencial ausente (tempo/questões) na sync.
# ---------------------------------------------------------------------------
def test_r7_campo_nao_essencial_ausente_aplica_livros_e_herda_tempo(db, escola_completa,
                                                                   monkeypatch):
    from app.models.plataformas import SnapshotElefante
    eid = escola_completa["escola"].id
    a = escola_completa["alunos"][0]
    credencial(db, eid, "elefante")
    origem = {CID: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
        aluno_el(9100001, a.nome, [livro("Livro Ficticio Um")], total=5, tempo=12000,
                 resp=30, ok=25)]}}
    nav = NavElefante(origem)
    instalar(monkeypatch, nav_elefante=nav)
    rodar(db, eid, "elefante")
    original = nav.avaliar

    async def sem_tempo(expressao):
        res = await original(expressao)
        if isinstance(res, dict) and isinstance(res.get("body"), dict) \
                and "students" in res["body"]:
            for s in res["body"]["students"]:
                s.pop("totalReadTime", None)
                s.pop("responses", None)
                s.pop("approvedResponses", None)
                s["totalBooksRead"] = 7
        return res
    nav.avaliar = sem_tempo
    ex, _ = rodar(db, eid, "elefante")
    s = snap_atual(db, SnapshotElefante, a.id)
    print("\nR7:", ex.status, getattr(ex, "motivo", None),
          (s.livros_unicos, s.tempo_leitura_min, s.questoes_tentativas),
          alertas_abertos(db, eid, "elefante"))
    assert (s.livros_unicos, s.tempo_leitura_min, s.questoes_tentativas) == (7, 200, 30)
    assert ex.status == "concluida"
