"""Revisão adversarial e93 (lente: semântica dos estados) do fix/sync-integridade.

Reproduções do revisor (``scratchpad/e93/rev-semantica``), trazidas para a suíte
com o comportamento DECIDIDO na correção. Dados 100% fictícios; conectores reais
com navegador falso; sem rede.
"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select, text

from app.core.config import settings
from app.models import Turma
from app.models.plataformas import SnapshotMatific
from app.models.sincronizacao import SincronizacaoAlerta, SincronizacaoConfig, SincronizacaoExecucao
from app.services import politica_sync
from app.sync import service, vault
from tests._sync_nucleo_fakes import (
    API, NavElefante, PlacarFake, aluno_el, alertas_abertos, credencial, instalar, livro,
    logs, novo_aluno, rodar)

K = "3 ANO A (300396804)"
CID_A, CID_B = 511434, 600001


def _placar_3(ec):
    a, b, c = ec["alunos"]
    p = PlacarFake()
    p.linhas = [("u-a", a.nome, K, 40, 10), ("u-b", b.nome, K, 30, 8),
                ("u-c", c.nome, K, 20, 5)]
    return p


def _n_snaps(db, eid):
    return db.scalar(select(func.count()).select_from(SnapshotMatific)
                     .where(SnapshotMatific.escola_id == eid))


def _agora():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _alerta(db, eid, tipo):
    return db.execute(select(SincronizacaoAlerta).where(
        SincronizacaoAlerta.escola_id == eid, SincronizacaoAlerta.tipo == tipo,
        SincronizacaoAlerta.resolvido.is_(False))).scalars().first()


def _agenda_diaria(db, eid, plataforma, desde_dias):
    cfg = SincronizacaoConfig(escola_id=eid, plataforma=plataforma, ativo=True,
                              cadencia="diaria", hora_local="03:00")
    db.add(cfg)
    db.commit()
    cfg.updated_at = _agora() - timedelta(days=desde_dias)
    db.commit()
    return cfg


# ---------------------------------------------------------------------------
# Achado 2 — Matific por período EM ANDAMENTO repetido sem mudança.
# ---------------------------------------------------------------------------
def test_periodo_em_andamento_repetido_sem_mudanca_e_nada_mudou(db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "matific")
    instalar(monkeypatch, placar=_placar_3(escola_completa))
    hoje = date.today()
    params = {"matific_start_date": (hoje - timedelta(days=5)).isoformat(),
              "matific_end_date": (hoje + timedelta(days=5)).isoformat()}
    ex1, e1 = rodar(db, eid, "matific", parametros=params)
    assert e1 is None and ex1.status == "concluida", (ex1.status, ex1.motivo, ex1.erro_resumo)
    n1 = _n_snaps(db, eid)
    ex2, _ = rodar(db, eid, "matific", parametros=params)
    assert (ex2.status, ex2.motivo, ex2.qtd_alunos) == ("sem_atualizacao", "nada_mudou", 0)
    assert _n_snaps(db, eid) == n1          # o retrato do dia é atualizado no lugar


def test_periodo_ate_hoje_inclusiva_repetido_sem_mudanca(db, escola_completa, monkeypatch):
    monkeypatch.setattr(settings, "MATIFIC_END_DATE", "inclusiva")
    eid = escola_completa["escola"].id
    credencial(db, eid, "matific")
    instalar(monkeypatch, placar=_placar_3(escola_completa))
    hoje = date.today()
    params = {"matific_start_date": (hoje - timedelta(days=6)).isoformat(),
              "matific_end_date": hoje.isoformat()}
    ex1, _ = rodar(db, eid, "matific", parametros=params)
    assert ex1.status == "concluida", (ex1.status, ex1.erro_resumo)
    ex2, _ = rodar(db, eid, "matific", parametros=params)
    assert (ex2.status, ex2.motivo, ex2.qtd_alunos) == ("sem_atualizacao", "nada_mudou", 0)


def test_periodo_em_andamento_com_ganho_novo_continua_concluida(db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "matific")
    placar = _placar_3(escola_completa)
    instalar(monkeypatch, placar=placar)
    hoje = date.today()
    params = {"matific_start_date": (hoje - timedelta(days=5)).isoformat(),
              "matific_end_date": (hoje + timedelta(days=5)).isoformat()}
    rodar(db, eid, "matific", parametros=params)
    u, n, k, e, at = placar.linhas[0]
    placar.linhas[0] = (u, n, k, e + 7, at + 2)
    ex2, _ = rodar(db, eid, "matific", parametros=params)
    assert (ex2.status, ex2.qtd_alunos) == ("concluida", 1)


# ---------------------------------------------------------------------------
# Achado 1 (ALTA) — lista de turmas do Elefante 2xx fora do formato.
# ---------------------------------------------------------------------------
class _NavRosterForaDoFormato(NavElefante):
    def __init__(self, corpo, **kw):
        super().__init__({}, sem_turmas=True, **kw)
        self._corpo = corpo

    async def avaliar(self, expressao):
        if "fetch(" in expressao and "get-courses-students" in expressao:
            return {"ok": True, "status": 200, "tipo": type(self._corpo).__name__,
                    "n": 0, "body": self._corpo}
        return await super().avaliar(expressao)


class _NavEscolaRecusada(NavElefante):
    def __init__(self):
        super().__init__({}, sem_turmas=True)

    async def avaliar(self, expressao):
        if "fetch(" in expressao and "get-courses-students" in expressao:
            if "schoolId" in expressao:
                return {"ok": False, "status": 403, "tipo": "null", "n": 0, "body": None}
            return {"ok": True, "status": 200, "tipo": "list", "n": 0, "body": []}
        return await super().avaliar(expressao)


def _roster(db, ec, monkeypatch, nav):
    eid = ec["escola"].id
    credencial(db, eid, "elefante")
    linha = vault.obter_linha(db, eid, "elefante")
    vault.marcar_status(db, linha, "nao_validada")
    db.commit()
    instalar(monkeypatch, nav_elefante=nav)
    ex, _ = rodar(db, eid, "elefante")
    cred = vault.obter_linha(db, eid, "elefante").status
    verif = service.ultima_verificacao_em(db, eid, "elefante")
    return ex, cred, verif, alertas_abertos(db, eid, "elefante")


def test_roster_2xx_objeto_fora_do_formato_e_erro(db, escola_completa, monkeypatch):
    ex, cred, verif, abertos = _roster(db, escola_completa, monkeypatch, _NavRosterForaDoFormato(
        {"courses": [{"id": 1, "name": "3 ANO A", "student": []}]}))
    assert (ex.status, ex.motivo) == ("erro", "parser_incompativel")
    assert cred != "valida" and verif is None
    assert "parser_incompativel" in abertos and "plataforma_sem_dados" not in abertos


def test_roster_2xx_corpo_nao_json_e_erro(db, escola_completa, monkeypatch):
    ex, cred, verif, _ = _roster(db, escola_completa, monkeypatch, _NavRosterForaDoFormato(None))
    assert (ex.status, ex.motivo) == ("erro", "parser_incompativel")
    assert cred != "valida" and verif is None


def test_roster_200_vazio_sem_escola_e_403_na_escola_e_sem_acesso(db, escola_completa,
                                                                 monkeypatch):
    ex, cred, verif, abertos = _roster(db, escola_completa, monkeypatch, _NavEscolaRecusada())
    assert (ex.status, ex.motivo) == ("erro", "sem_acesso_ao_dado")
    assert cred != "valida" and verif is None and "sem_acesso_ao_dado" in abertos


def test_roster_2xx_lista_vazia_continua_sem_dados(db, escola_completa, monkeypatch):
    ex, cred, verif, _ = _roster(db, escola_completa, monkeypatch,
                                 NavElefante({}, sem_turmas=True))
    assert ex.status == "sem_dados" and cred == "valida" and verif is not None


# ---------------------------------------------------------------------------
# Achado 8 — 'concluida' com linhas que ficaram em revisão NESTA execução.
# ---------------------------------------------------------------------------
def test_concluida_com_linhas_em_revisao_mantem_correspondencia_pendente(
        db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    politica_sync.definir(db, eid, "bloquear")
    db.commit()
    a = escola_completa["alunos"][0]
    credencial(db, eid, "elefante")
    estranho = aluno_el(9300001, "Crianca Ficticia Sem Ficha Um",
                        [livro("Livro Ficticio Dois", "E", "2026-09-03T10:00:00")])
    conhecido = aluno_el(9100001, a.nome, [livro("Livro Ficticio Um")])
    turmas = {CID_A: {"nome": "3 ANO A TARDE ANUAL", "alunos": [conhecido, estranho]}}
    instalar(monkeypatch, nav_elefante=NavElefante(turmas))
    ex1, _ = rodar(db, eid, "elefante")
    assert ex1.status == "concluida" and ex1.qtd_em_revisao > 0
    assert "correspondencia_pendente" in alertas_abertos(db, eid, "elefante")
    rodar(db, eid, "elefante")
    assert "correspondencia_pendente" in alertas_abertos(db, eid, "elefante")
    conhecido["livros"].append(livro("Livro Ficticio Novo", "E", "2026-10-02T10:00:00"))
    conhecido["total"] = len(conhecido["livros"])
    ex3, _ = rodar(db, eid, "elefante")
    assert ex3.status == "concluida" and ex3.qtd_em_revisao > 0
    assert "correspondencia_pendente" in alertas_abertos(db, eid, "elefante")


# ---------------------------------------------------------------------------
# Achado 5 — queda retida do Matific não é "correspondência pendente".
# ---------------------------------------------------------------------------
def test_queda_retida_tem_motivo_proprio_e_nao_manda_para_revisao(db, escola_completa,
                                                                 monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "matific")
    placar = _placar_3(escola_completa)
    instalar(monkeypatch, placar=placar)
    ex1, _ = rodar(db, eid, "matific")
    assert ex1.status == "concluida"
    u, n, k, e, at = placar.linhas[0]
    placar.linhas[0] = (u, n, k, e - 10, at - 2)        # queda de um aluno, resto igual
    ex2, _ = rodar(db, eid, "matific")
    abertos = alertas_abertos(db, eid, "matific")
    assert (ex2.status, ex2.motivo) == ("sem_atualizacao", "queda_retida")
    assert ex2.qtd_em_revisao == 0
    assert "queda_matific" in abertos and "correspondencia_pendente" not in abertos
    # Coleta completa e sem falha: conta como verificação.
    assert service.ultima_verificacao_em(db, eid, "matific") == ex2.finalizada_em


# ---------------------------------------------------------------------------
# Achados 3 e 6 — coleta POR PERÍODO não é o acumulado.
# ---------------------------------------------------------------------------
def test_periodo_sem_atividade_nao_culpa_a_conta(db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "matific")
    placar = _placar_3(escola_completa)
    instalar(monkeypatch, placar=placar)
    ex1, _ = rodar(db, eid, "matific")
    assert ex1.status == "concluida"
    placar.linhas = []
    ex2, _ = rodar(db, eid, "matific", parametros={"matific_start_date": "2026-07-01",
                                                   "matific_end_date": "2026-07-15"})
    assert ex2.status == "sem_dados"
    assert "plataforma_sem_dados" not in alertas_abertos(db, eid, "matific")


def test_acumulado_vazio_depois_de_cheio_ainda_avisa(db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "matific")
    placar = _placar_3(escola_completa)
    instalar(monkeypatch, placar=placar)
    rodar(db, eid, "matific")
    placar.linhas = []
    ex2, _ = rodar(db, eid, "matific")
    assert ex2.status == "sem_dados"
    assert "plataforma_sem_dados" in alertas_abertos(db, eid, "matific")


def test_periodo_passado_nao_poe_a_integracao_em_dia(db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "matific")
    placar = _placar_3(escola_completa)
    instalar(monkeypatch, placar=placar)
    ex1, _ = rodar(db, eid, "matific")
    assert ex1.status == "concluida"
    velho = _agora() - timedelta(days=10)
    db.get(SincronizacaoExecucao, ex1.id).finalizada_em = velho
    db.commit()
    cfg = _agenda_diaria(db, eid, "matific", 10)
    assert service.atualizar_alerta_desatualizada(db, cfg) is True
    db.commit()
    placar.linhas = [(u, n, k, 7, 3) for u, n, k, e, at in placar.linhas]
    ex2, _ = rodar(db, eid, "matific", parametros={"matific_start_date": "2026-08-01",
                                                   "matific_end_date": "2026-08-31"})
    assert ex2.status == "concluida"
    assert "desatualizada" in alertas_abertos(db, eid, "matific")
    ultimo = service.ultimo_sucesso_em(db, eid, "matific")
    assert ultimo is not None and ultimo <= velho + timedelta(seconds=1)


# ---------------------------------------------------------------------------
# Achado 7 — período no futuro.
# ---------------------------------------------------------------------------
def test_periodo_futuro_recusado_na_rota(cliente, db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "matific")
    instalar(monkeypatch, placar=_placar_3(escola_completa))
    monkeypatch.setattr(service, "disparar_em_thread", lambda i: None)
    hoje = date.today()
    ini, fim = (hoje + timedelta(days=10)).isoformat(), (hoje + timedelta(days=20)).isoformat()
    r = cliente.post(f"{API}/escolas/{eid}/sync/agora?plataforma=matific"
                     f"&inicio={ini}&fim={fim}")
    assert r.status_code == 400, r.text[:200]
    assert "depois de hoje" in r.json()["detail"]


def test_importacao_que_recusa_o_periodo_vira_periodo_invalido(db, escola_completa,
                                                               monkeypatch):
    """Execução já na fila com período inválido (criada antes da trava da rota,
    ou por outro caminho): o 400 da importação vira 'periodo_invalido' não
    recuperável, não "Falha inesperada"."""
    eid = escola_completa["escola"].id
    credencial(db, eid, "matific")
    instalar(monkeypatch, placar=_placar_3(escola_completa))
    hoje = date.today()
    ex, _ = rodar(db, eid, "matific", parametros={
        "matific_start_date": (hoje + timedelta(days=10)).isoformat(),
        "matific_end_date": (hoje + timedelta(days=20)).isoformat()})
    assert (ex.status, ex.motivo) == ("erro", "periodo_invalido")
    assert "periodo_invalido" in alertas_abertos(db, eid, "matific")


# ---------------------------------------------------------------------------
# Achado 14 (e R3 da lente regressão) — student-leaderboard é acessório.
# ---------------------------------------------------------------------------
def test_leaderboard_fora_do_formato_com_contas_vinculadas_e_parcial(db, escola_completa,
                                                                    monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "matific")
    placar = _placar_3(escola_completa)
    instalar(monkeypatch, placar=placar)
    ex1, _ = rodar(db, eid, "matific")
    assert ex1.status == "concluida"
    placar.leaderboard = lambda: {"ok": True, "status": 200, "body": {"results": [
        {"student_id": u, "student_name": n} for u, n, *_ in placar.linhas]}}
    placar.linhas = [(u, n, k, e + 5, a + 1) for u, n, k, e, a in placar.linhas]
    ex2, _ = rodar(db, eid, "matific")
    abertos = alertas_abertos(db, eid, "matific")
    assert (ex2.status, ex2.motivo, ex2.qtd_alunos) == ("parcial", "coleta_parcial", 3)
    assert "parser_incompativel" in abertos and "coleta_parcial" in abertos


def test_leaderboard_404_na_primeira_coleta_e_a_coleta_seguinte_resolve_as_pendencias(
        db, escola_completa, monkeypatch):
    """1ª coleta sem os nomes completos: ninguém vinculado → as contas vão para a
    revisão 'nome_incompleto' (nenhuma ficha abreviada) e a execução é 'erro'
    (nenhum dado, endpoint falhou). A coleta seguinte, com os nomes, associa
    pelas regras de sempre e encerra as pendências sozinha."""
    from tests.sync_integridade_comum import pendentes
    eid = escola_completa["escola"].id
    credencial(db, eid, "matific")
    placar = _placar_3(escola_completa)
    placar.status_lb = 404
    instalar(monkeypatch, placar=placar)
    ex1, _ = rodar(db, eid, "matific")
    assert (ex1.status, ex1.motivo) == ("erro", "falha_download")
    assert len(pendentes(db, eid, "nome_incompleto")) == 3
    placar.status_lb = 200
    ex2, _ = rodar(db, eid, "matific")
    assert (ex2.status, ex2.qtd_alunos) == ("concluida", 3)
    assert pendentes(db, eid) == []


def test_leaderboard_fora_do_formato_na_primeira_coleta_e_erro(db, escola_completa,
                                                               monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "matific")
    placar = _placar_3(escola_completa)
    placar.leaderboard = lambda: {"ok": True, "status": 200, "body": {"results": []}}
    instalar(monkeypatch, placar=placar)
    ex1, _ = rodar(db, eid, "matific")
    assert (ex1.status, ex1.motivo) == ("erro", "parser_incompativel")
    assert "parser_incompativel" in alertas_abertos(db, eid, "matific")


# ---------------------------------------------------------------------------
# Achado 11 — conta vinculada que some do Placar.
# ---------------------------------------------------------------------------
def test_conta_vinculada_ausente_no_placar_abre_aviso(db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "matific")
    placar = _placar_3(escola_completa)
    instalar(monkeypatch, placar=placar)
    ex1, _ = rodar(db, eid, "matific")
    assert ex1.status == "concluida"
    completas = list(placar.linhas)
    placar.linhas = [(u, n, k, e + 5, a + 1) for u, n, k, e, a in completas[:2]]
    ex2, _ = rodar(db, eid, "matific")
    al = _alerta(db, eid, "contas_ausentes")
    assert ex2.status == "concluida"
    assert al is not None and al.severidade == "warn" and al.mensagem.startswith("1 conta")
    assert any("ausentes" in m for _e, _n, m in logs(db, ex2.id))
    # Voltou a vir: o aviso fecha.
    placar.linhas = [(u, n, k, e + 9, a + 2) for u, n, k, e, a in completas]
    rodar(db, eid, "matific")
    assert "contas_ausentes" not in alertas_abertos(db, eid, "matific")


# ---------------------------------------------------------------------------
# Achado 10 — linha com defeito sem nenhuma mudança.
# ---------------------------------------------------------------------------
def test_sem_atualizacao_com_linhas_descartadas_abre_aviso(db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "matific")
    placar = _placar_3(escola_completa)
    instalar(monkeypatch, placar=placar)
    ex1, _ = rodar(db, eid, "matific")
    assert ex1.status == "concluida"
    original = placar.school_student

    def _com_linha_sem_turma(expr):
        res = original(expr)
        res["body"][0]["data"].insert(0, {
            "account_id": "CRIANCA F", "score": "9", "grade_code": "3",
            "activities_completed": "3", "klassName": "", "uuid": "u-z"})
        return res
    placar.school_student = _com_linha_sem_turma
    ex2, _ = rodar(db, eid, "matific")
    assert (ex2.status, ex2.motivo) == ("sem_atualizacao", "linhas_descartadas")
    assert "coleta_parcial" in alertas_abertos(db, eid, "matific")


# ---------------------------------------------------------------------------
# Achado 4 — pendência ou defeito que não se resolve sozinho NÃO abre o
# 'desatualizada' crítico com a coleta funcionando (decisão registrada).
# ---------------------------------------------------------------------------
def test_defeito_permanente_nao_mantem_desatualizada_com_dado_chegando(
        db, escola_completa, monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    a, b, c = ec["alunos"]
    credencial(db, eid, "elefante")
    _agenda_diaria(db, eid, "elefante", 5)
    sem_data = {"bookTitle": "Livro Ficticio Sem Data", "levelName": "D",
                "lastReadWhen": None, "totalTimeSpent": 120}
    al_a = aluno_el(9100001, a.nome, [livro("Livro Ficticio Um"), sem_data])
    turmas = {CID_A: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
        al_a,
        aluno_el(9100002, b.nome, [livro("Livro Ficticio Dois", "E", "2026-09-05T10:00:00")]),
        aluno_el(9100003, c.nome, [livro("Livro Ficticio Tres", "D", "2026-09-06T10:00:00")])]}}
    instalar(monkeypatch, nav_elefante=NavElefante(turmas))
    resultados = []
    for dia in range(3):
        al_a["livros"].append(livro(f"Livro Ficticio Dia {dia}", "E",
                                    f"2026-10-0{dia + 1}T10:00:00"))
        al_a["total"] = len(al_a["livros"])
        ex, _ = rodar(db, eid, "elefante")
        resultados.append((ex.status, ex.motivo, ex.qtd_alunos))
    assert all(r[2] >= 1 for r in resultados), resultados
    assert _alerta(db, eid, "desatualizada") is None, resultados
    assert "coleta_parcial" in alertas_abertos(db, eid, "elefante")   # o defeito segue visível


def test_uma_pendencia_nao_abre_desatualizada_no_fim_de_semana(db, escola_completa,
                                                               monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    a, b, c = ec["alunos"]
    politica_sync.definir(db, eid, "bloquear")
    db.commit()
    credencial(db, eid, "elefante")
    turmas = {CID_A: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
        aluno_el(9100001, a.nome, [livro("Livro Ficticio Um")]),
        aluno_el(9100002, b.nome, [livro("Livro Ficticio Dois", "E", "2026-09-05T10:00:00")]),
        aluno_el(9100003, c.nome, [livro("Livro Ficticio Tres", "D", "2026-09-06T10:00:00")]),
        aluno_el(9300001, "Crianca Ficticia Fora Da Lista",
                 [livro("Livro Ficticio Quatro", "E", "2026-09-03T10:00:00")])]}}
    instalar(monkeypatch, nav_elefante=NavElefante(turmas))
    ex1, _ = rodar(db, eid, "elefante")
    assert ex1.status == "concluida"
    tres = _agora() - timedelta(days=3)
    db.get(SincronizacaoExecucao, ex1.id).finalizada_em = tres
    db.commit()
    _agenda_diaria(db, eid, "elefante", 3)
    ex2, _ = rodar(db, eid, "elefante")
    assert (ex2.status, ex2.motivo) == ("sem_atualizacao", "correspondencia_pendente")
    assert _alerta(db, eid, "desatualizada") is None
    assert "correspondencia_pendente" in alertas_abertos(db, eid, "elefante")


def test_parcial_por_unidade_que_falhou_continua_sem_fechar_desatualizada(
        db, escola_completa, monkeypatch):
    """O que NÃO mudou na decisão: turma/lote/aluno que falhou deixa parte da
    escola sem dado novo — a 'parcial' por falha de unidade não põe em dia."""
    ec = escola_completa
    eid = ec["escola"].id
    a = ec["alunos"][0]
    t2 = Turma(escola_id=eid, nome="4º Ano B", ano_escolar="4º Ano", ano_letivo=2026)
    db.add(t2)
    db.commit()
    d = novo_aluno(db, eid, t2, "Crianca Ficticia Quarto Ano")
    db.commit()
    credencial(db, eid, "elefante")
    _agenda_diaria(db, eid, "elefante", 5)
    turmas = {CID_A: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
        aluno_el(9100001, a.nome, [livro("Livro Ficticio Um")])]},
        CID_B: {"nome": "4 ANO B TARDE ANUAL", "alunos": [
            aluno_el(9200001, d.nome, [livro("Livro Ficticio Quatro")])]}}
    instalar(monkeypatch, nav_elefante=NavElefante(turmas, erro_turma={CID_B: 500}))
    ex, _ = rodar(db, eid, "elefante")
    assert (ex.status, ex.motivo) == ("parcial", "coleta_parcial")
    assert _alerta(db, eid, "desatualizada") is not None


# ---------------------------------------------------------------------------
# Achado 13 — importação manual repetida.
# ---------------------------------------------------------------------------
def test_importacao_manual_repetida_nao_diz_atualizados(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    a, b, c = escola_completa["alunos"]
    corpo = {"plataforma": "matific", "formato": "resumo", "tipo": "xlsx", "linhas": [
        {"nome": al.nome, "aluno_id": al.id,
         "dados": {"atividades": 10 + i, "estrelas": 30 + i, "pontuacao_media": 3.0}}
        for i, al in enumerate((a, b, c))]}
    r1 = cliente.post(f"{API}/escolas/{eid}/importacoes/confirmar", json=corpo)
    assert r1.status_code == 200, r1.text[:300]
    assert "3 alunos atualizados" in r1.json()["mensagem"]
    r2 = cliente.post(f"{API}/escolas/{eid}/importacoes/confirmar", json=corpo)
    j2 = r2.json()
    assert j2["alunos_aplicados_ids"] == []
    assert "0 alunos atualizados" in j2["mensagem"]
    assert "3 aluno(s) conferido(s)" in j2["mensagem"]


# ---------------------------------------------------------------------------
# Achado 12 — parte recusada e resto sem mudança: o motivo é o código.
# ---------------------------------------------------------------------------
def test_parte_recusada_resto_igual_tem_o_codigo_como_motivo(db, escola_completa, monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    a = ec["alunos"][0]
    t2 = Turma(escola_id=eid, nome="4º Ano B", ano_escolar="4º Ano", ano_letivo=2026)
    db.add(t2)
    db.commit()
    d = novo_aluno(db, eid, t2, "Crianca Ficticia Quarto Ano")
    db.commit()
    credencial(db, eid, "elefante")
    turmas = {CID_A: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
        aluno_el(9100001, a.nome, [livro("Livro Ficticio Um")])]},
        CID_B: {"nome": "4 ANO B TARDE ANUAL", "alunos": [
            aluno_el(9200001, d.nome, [livro("Livro Ficticio Quatro", "E",
                                             "2026-09-07T10:00:00")])]}}
    nav = NavElefante(turmas)
    instalar(monkeypatch, nav_elefante=nav)
    ex1, _ = rodar(db, eid, "elefante")
    assert ex1.status == "concluida"
    nav.erro_turma = {CID_B: 403}
    ex2, _ = rodar(db, eid, "elefante")
    assert (ex2.status, ex2.motivo) == ("erro", "sem_acesso_ao_dado")


# ---------------------------------------------------------------------------
# Achado 9 — coleta completa só com pendência fecha falhas antigas.
# ---------------------------------------------------------------------------
def test_coleta_completa_com_pendencia_fecha_falha_antiga(cliente_global, db, escola_completa,
                                                          monkeypatch):
    eid = escola_completa["escola"].id
    politica_sync.definir(db, eid, "bloquear")
    db.commit()
    a = escola_completa["alunos"][0]
    credencial(db, eid, "elefante")
    turmas = {CID_A: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
        aluno_el(9100001, a.nome, [livro("Livro Ficticio Um")]),
        aluno_el(9300001, "Crianca Ficticia Sem Ficha Um",
                 [livro("Livro Ficticio Dois", "E", "2026-09-03T10:00:00")])]}}
    nav = NavElefante(turmas)
    instalar(monkeypatch, nav_elefante=nav)
    ex1, _ = rodar(db, eid, "elefante")
    assert ex1.status == "concluida"
    nav.erro_turma = {CID_A: 403}
    ex2, _ = rodar(db, eid, "elefante")
    assert ex2.status == "erro" and "sem_acesso_ao_dado" in alertas_abertos(db, eid, "elefante")
    nav.erro_turma = {}
    ex3, _ = rodar(db, eid, "elefante")
    painel = cliente_global.get(f"{API}/sync/dashboard").json()
    assert (ex3.status, ex3.motivo) == ("sem_atualizacao", "correspondencia_pendente")
    abertos = alertas_abertos(db, eid, "elefante")
    assert "sem_acesso_ao_dado" not in abertos and "correspondencia_pendente" in abertos
    assert painel.get("escolas_com_erro") == 0


# ---------------------------------------------------------------------------
# Controle (não confirmado pelo revisor): repetição sem mudança no Elefante,
# inclusive a recoleta completa forçada, é sempre 'nada_mudou'.
# ---------------------------------------------------------------------------
def test_repeticoes_sem_mudanca_elefante_inclusive_completa(db, escola_completa, monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    a, b, c = ec["alunos"]
    credencial(db, eid, "elefante")
    turmas = {CID_A: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
        aluno_el(9100001, a.nome, [livro("Livro Ficticio Um"),
                                   livro("Livro Ficticio Um B", "E", "2026-09-03T10:00:00")],
                 tempo=1500),
        aluno_el(9100002, b.nome, [livro("Livro Ficticio Dois", "E", "2026-09-05T10:00:00")]),
        aluno_el(9100003, c.nome, [livro("Livro Ficticio Tres", "D", "2026-09-06T10:00:00")])]}}
    instalar(monkeypatch, nav_elefante=NavElefante(turmas))
    res = []
    for _ in range(4):
        ex, _e = rodar(db, eid, "elefante")
        res.append((ex.status, ex.motivo))
    monkeypatch.setattr(service, "_coleta_completa_devida",
                        lambda *a, **k: (True, "forçada no teste"))
    for _ in range(2):
        ex, _e = rodar(db, eid, "elefante")
        res.append((ex.status, ex.motivo))
    assert all(r == ("sem_atualizacao", "nada_mudou") for r in res[1:]), res
    assert db.execute(text("SELECT COUNT(*) FROM revisoes_identidade WHERE escola_id=:e"),
                      {"e": eid}).scalar_one() == 0
