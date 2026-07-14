"""Consulta AO VIVO do Placar do Matific (premiação por período).

Cobre: (1) o mapeamento período → filtro da API (presets nativos vs. datas),
(2) a montagem do ranking (ordem/média/link com o aluno), (3) o método do
conector com navegador FAKE — login na 1ª vez e REUSO de sessão na 2ª (sem novo
login), (4) o round-trip completo pelo serviço com a sessão cifrada em banco.
"""
from datetime import date, datetime

import pytest

from app.sync import aovivo, connectors, vault
from app.sync.connectors import matific
from app.sync.interfaces import Contexto, Credenciais, ErroConector

SCHOOL = "e3e918e8-0000-0000-0000-000000000001"


# --- 1. Período → filtro (sem suposição: preset nativo onde há, datas no resto)

def test_mapa_filtro_presets_nativos_e_datas():
    hoje = date(2026, 7, 14)
    # Presets NATIVOS do site.
    assert aovivo.mapa_filtro("semana", None, None, 2026, hoje)[0] == "duration=week"
    assert aovivo.mapa_filtro("ano_letivo", None, None, 2026, hoje)[0] == "duration=this-year"
    # Hoje / mês / bimestre → start_date/end_date (mesmo mecanismo do personalizado),
    # nunca com data FUTURA (fim limitado a hoje).
    assert aovivo.mapa_filtro("hoje", None, None, 2026, hoje)[0] == \
        "start_date=2026-07-14&end_date=2026-07-14"
    assert aovivo.mapa_filtro("mes", None, None, 2026, hoje)[0] == \
        "start_date=2026-07-01&end_date=2026-07-14"
    assert aovivo.mapa_filtro("bimestre", None, None, 2026, hoje)[0] == \
        "start_date=2026-07-01&end_date=2026-07-14"


def test_mapa_filtro_personalizado_e_erros():
    hoje = date(2026, 7, 14)
    filtro, _rot, di, df = aovivo.mapa_filtro(
        "personalizado", "2026-05-01", "2026-05-31", 2026, hoje)
    assert filtro == "start_date=2026-05-01&end_date=2026-05-31"
    assert di == date(2026, 5, 1) and df == date(2026, 5, 31)
    # Uma data só → erro claro.
    with pytest.raises(ErroConector):
        aovivo.mapa_filtro("personalizado", "2026-05-01", None, 2026, hoje)
    # Fim antes do início → erro.
    with pytest.raises(ErroConector):
        aovivo.mapa_filtro("personalizado", "2026-05-31", "2026-05-01", 2026, hoje)
    # Data malformada → ErroConector (não ValueError, que viraria 500).
    with pytest.raises(ErroConector) as exc:
        aovivo.mapa_filtro("personalizado", "01/05/2026", "2026-05-31", 2026, hoje)
    assert exc.value.codigo == "periodo_invalido"


# --- 2. Montagem do ranking -------------------------------------------------

def test_montar_ranking_ordena_e_calcula_media():
    alunos = [
        {"nome": "Ana Beatriz Souza", "turma": "3º Ano A", "serie": "3",
         "estrelas": 100, "atividades": 20},
        {"nome": "João Pedro Barbosa", "turma": "3º Ano A", "serie": "3",
         "estrelas": 50, "atividades": 10},
        {"nome": "Sem Atividade", "turma": "3º Ano A", "serie": "3",
         "estrelas": 0, "atividades": 0},
    ]
    mapa = {aovivo._norm("Ana Beatriz Souza"): 7}
    itens = aovivo._montar_ranking(alunos, mapa)
    assert [i["nome"] for i in itens] == ["Ana Beatriz Souza", "João Pedro Barbosa", "Sem Atividade"]
    assert [i["posicao"] for i in itens] == [1, 2, 3]
    assert itens[0]["pontuacao_media"] == 5.0        # 100/20
    assert itens[2]["pontuacao_media"] == 0.0        # sem divisão por zero
    assert itens[0]["aluno_id"] == 7                  # casou com o cadastro
    assert itens[1]["aluno_id"] is None              # sem correspondência


# --- Navegador FAKE ---------------------------------------------------------

def _payloads(nomes_por_uuid: dict[str, str]):
    data = []
    estrelas = {"u-ana": ("100", "20"), "u-joao": ("50", "10"), "u-sofia": ("0", "0")}
    for uuid, nome in nomes_por_uuid.items():
        s, a = estrelas[uuid]
        data.append({"account_id": nome.split()[0].upper(), "score": s,
                     "activities_completed": a, "grade_code": "3",
                     "klassName": "3º Ano A", "uuid": uuid})
    ss = {"ok": True, "status": 200,
          "body": [{"school_id": SCHOOL, "data": data}]}
    sl = {"ok": True, "status": 200, "body": {"leaderboard": [
        {"student_id": u, "student_name": n} for u, n in nomes_por_uuid.items()]}}
    return ss, sl


class NavFake:
    """Navegador FAKE para a consulta ao vivo. Conta os logins (preencher) para
    provar que o REUSO de sessão pula o formulário."""

    def __init__(self, ss, sl, *, logado_de_saida=True):
        self._ss, self._sl = ss, sl
        self.logins = 0
        self._logado = logado_de_saida

    async def ir_para(self, url): pass
    async def preencher(self, s, v):
        if "user" in s.lower():  # 1 login = preenche usuário + senha; conta só o usuário
            self.logins += 1
    async def clicar(self, s): pass
    async def esperar(self, s, timeout_s=20): return True
    async def visivel(self, s): return "password" in s.lower()
    async def texto(self, s): return ""
    async def url_atual(self):
        return ("https://www.matific.com/bra/pt-br/teachers/admin/school-leaderboard/"
                if self._logado else "https://www.matific.com/bra/pt-br/login-page/")
    async def fechar(self): pass
    async def estado_sessao(self): return {"cookies": [{"name": "sessionid", "value": "x"}], "origins": []}

    async def coletar_respostas(self, url, timeout_s=25):
        return []

    async def avaliar(self, expr):
        if "student-leaderboard" in expr:
            return self._sl
        if "accounts/current" in expr:
            return {"ok": True, "status": 200, "body": {"school_id": SCHOOL}}
        if "competition-v2" in expr:
            return {"ok": True, "status": 200,
                    "body": [{"id": "8773b0bf-0000-0000-0000-0000000000aa", "is_live": True}]}
        if "school_student" in expr:
            return self._ss
        return {"ok": False, "status": 0, "body": None}

    async def coletar_apos_acao(self, acao, timeout_s=20):
        return []
    async def baixar(self, s, timeout_s=60): return (b"", "x")


# --- 3. Conector: login na 1ª, REUSO na 2ª ----------------------------------

def _run(coro):
    import asyncio
    return asyncio.run(coro)


def test_conector_faz_login_sem_sessao_e_reusa_com_sessao():
    ss, sl = _payloads({"u-ana": "Ana Beatriz Souza"})
    nav = NavFake(ss, sl)

    async def fab(**_kw):
        return nav

    con = matific.ConectorMatific(fab)
    ctx = Contexto(escola_id=1, execucao_id=None, log=lambda *a: None)
    cred = Credenciais(usuario="u", senha="p")

    # 1ª consulta sem sessão → faz login.
    alunos, estado = _run(con.coletar_placar_ao_vivo(
        cred, ctx, filtro="duration=week", storage_state=None))
    assert nav.logins == 1
    assert estado and estado.get("cookies")
    assert alunos and alunos[0]["nome"] == "Ana Beatriz Souza"

    # 2ª consulta COM a sessão salva (e ainda logado) → NÃO loga de novo.
    alunos2, _ = _run(con.coletar_placar_ao_vivo(
        cred, ctx, filtro="duration=week", storage_state=estado))
    assert nav.logins == 1          # nenhum login novo
    assert alunos2[0]["nome"] == "Ana Beatriz Souza"


def test_conector_refaz_login_se_sessao_expirou():
    ss, sl = _payloads({"u-ana": "Ana Beatriz Souza"})
    nav = NavFake(ss, sl, logado_de_saida=False)  # sessão reidratada NÃO está logada

    async def fab(**_kw):
        return nav

    con = matific.ConectorMatific(fab)
    ctx = Contexto(escola_id=1, execucao_id=None, log=lambda *a: None)
    alunos, _ = _run(con.coletar_placar_ao_vivo(
        Credenciais(usuario="u", senha="p"), ctx,
        filtro="duration=week", storage_state={"cookies": []}))
    assert nav.logins == 1          # sessão inválida → refez o login
    assert alunos[0]["nome"] == "Ana Beatriz Souza"


# --- 4. Serviço: round-trip com a sessão cifrada em banco -------------------

def test_placar_matific_round_trip_com_sessao_persistida(db, escola_completa, monkeypatch):
    escola = escola_completa["escola"]
    nomes = {"u-ana": "Ana Beatriz Souza", "u-joao": "João Pedro Barbosa",
             "u-sofia": "Sofia Almeida Duarte"}
    ss, sl = _payloads(nomes)
    nav = NavFake(ss, sl)

    async def fab(**_kw):
        return nav

    con = matific.ConectorMatific(fab)
    monkeypatch.setattr(connectors, "obter", lambda plat: con if plat == "matific" else None)

    vault.salvar_credencial(db, escola.id, "matific",
                            Credenciais(usuario="u", senha="p"))
    db.commit()

    agora = datetime(2026, 7, 14, 12, 0, 0)
    r1 = aovivo.placar_matific(db, escola.id, periodo="mes", inicio=None, fim=None,
                               agora=agora)
    assert r1["total"] == 3
    assert [i["nome"] for i in r1["itens"]] == \
        ["Ana Beatriz Souza", "João Pedro Barbosa", "Sofia Almeida Duarte"]
    assert r1["itens"][0]["pontuacao_media"] == 5.0
    # casou os 3 nomes com os cadastros da escola (link para a ficha).
    assert r1["com_link"] == 3 and all(i["aluno_id"] for i in r1["itens"])
    assert nav.logins == 1

    # 2ª consulta reusa a sessão CIFRADA persistida → sem novo login.
    r2 = aovivo.placar_matific(db, escola.id, periodo="semana", inicio=None, fim=None,
                               agora=agora)
    assert r2["periodo"] == "Esta semana"
    assert nav.logins == 1


def test_placar_matific_sem_credencial_erro_claro(db, escola_completa):
    escola = escola_completa["escola"]
    with pytest.raises(ErroConector) as exc:
        aovivo.placar_matific(db, escola.id, periodo="mes", inicio=None, fim=None)
    assert exc.value.codigo == "sem_credencial"


def test_placar_matific_usa_data_do_brasil_perto_da_meia_noite(db, escola_completa,
                                                               monkeypatch):
    """Regressão: 'Hoje' à noite (BRT) NÃO pode pedir o dia seguinte (UTC) ao
    Matific. 01:00 UTC = 22:00 do dia anterior no Brasil (UTC-3)."""
    escola = escola_completa["escola"]
    ss, sl = _payloads({"u-ana": "Ana Beatriz Souza"})
    nav = NavFake(ss, sl)

    async def fab(**_kw):
        return nav

    con = matific.ConectorMatific(fab)
    monkeypatch.setattr(connectors, "obter",
                        lambda plat: con if plat == "matific" else None)
    vault.salvar_credencial(db, escola.id, "matific",
                            Credenciais(usuario="u", senha="p"))
    db.commit()

    agora_utc = datetime(2026, 7, 15, 1, 0, 0)  # 22:00 de 14/07 no Brasil
    r = aovivo.placar_matific(db, escola.id, periodo="hoje", inicio=None, fim=None,
                              agora=agora_utc)
    assert r["filtro"] == "start_date=2026-07-14&end_date=2026-07-14"
