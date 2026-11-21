"""Elefante: o endpoint de livros muda de FORMATO (a data ou o título da leitura
vem com outro nome, ou num valor que não se lê) — e o cursor incremental.

Contrato:
  * a data/o título que SOME de todos os livros de uma turma é "formato do
    relatório mudou" (falha da unidade com o alerta crítico 'parser_incompativel'),
    não "linha com defeito" de passagem: a coleta não conta como "em dia";
  * o cursor de quem teve os livros perdidos assim NÃO avança — quando o formato
    volta (ou a coleta é ajustada), a coleta seguinte traz o livro novo;
  * o nulo EXPLÍCITO continua sendo "sem dado": linha descartada contada, como
    sempre (``test_sync_em_dia_forma_c``, ``test_sync_revisao_regressao``);
  * o alerta "Coleta parcial" só manda sincronizar de novo quando isso completa a
    coleta: a leitura descartada não volta com outra coleta (o cursor do aluno já
    avançou, por decisão) — ela é pedida de novo na recoleta completa da semana.

Dados 100% fictícios; conectores reais com navegador falso; nada sai da máquina.
"""
from sqlalchemy import func, select

from app.models.plataformas import Leitura
from app.models.sincronizacao import SincronizacaoAlerta
from app.sync import service
from app.sync.connectors import elefante as con_elefante
from tests._sync_nucleo_fakes import (
    NavElefante, aluno_el, alertas_abertos, credencial, instalar, livro, rodar)

CID = 511434


def _livro_data_renomeada(titulo, nivel="D", data="2026-09-10T10:00:00", tempo=300):
    """O mesmo livro, mas a API passou a chamar a data de ``readWhen``."""
    return {"bookTitle": titulo, "levelName": nivel, "readWhen": data, "totalTimeSpent": tempo}


def _leituras(db, aluno_id):
    return db.scalar(select(func.count()).select_from(Leitura).where(Leitura.aluno_id == aluno_id))


def _alertas(db, eid):
    return {al.tipo: (al.severidade, al.mensagem) for al in db.execute(
        select(SincronizacaoAlerta).where(SincronizacaoAlerta.escola_id == eid,
                                          SincronizacaoAlerta.resolvido.is_(False))).scalars()}


def _turma(ec, livros_a, livros_b, livros_c):
    a, b, c = ec["alunos"]
    return {CID: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
        aluno_el(9100001, a.nome, livros_a),
        aluno_el(9100002, b.nome, livros_b),
        aluno_el(9100003, c.nome, livros_c)]}}


def test_data_renomeada_nao_avanca_o_cursor_nem_perde_o_livro(db, escola_completa, monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    a = ec["alunos"][0]
    credencial(db, eid, "elefante")
    l1 = livro("Livro Ficticio Um", data="2026-09-02T10:00:00")
    turmas = _turma(ec, [l1],
                    [livro("Livro Ficticio Dois", "E", "2026-09-05T10:00:00")],
                    [livro("Livro Ficticio Tres", "D", "2026-09-06T10:00:00")])
    nav = NavElefante(turmas)
    instalar(monkeypatch, nav_elefante=nav)
    ex1, _ = rodar(db, eid, "elefante")
    assert ex1.status == "concluida", (ex1.status, ex1.motivo)
    assert _leituras(db, a.id) == 1

    # 2ª coleta: A leu um livro NOVO e o endpoint de livros passou a mandar a data
    # com outro nome em TODAS as linhas.
    novo = livro("Livro Ficticio Novo", data="2026-09-10T10:00:00")
    turmas[CID]["alunos"][0] = aluno_el(9100001, a.nome, [l1, novo])
    for al in turmas[CID]["alunos"]:
        al["livros"] = [_livro_data_renomeada(x["bookTitle"], x["levelName"], x["lastReadWhen"])
                        for x in al["livros"]]
    ex2, _ = rodar(db, eid, "elefante")
    cursor = service._carregar_contadores(db, eid, "elefante")
    assert _leituras(db, a.id) == 1
    assert cursor.get("9100001") != 2, (
        f"o cursor de A avançou sem a leitura nova gravada: {cursor}")

    # 3ª coleta: o formato voltou (ou a coleta foi ajustada): o livro novo entra.
    for al in turmas[CID]["alunos"]:
        al["livros"] = [livro(x["bookTitle"], x["levelName"], x["readWhen"])
                        for x in al["livros"]]
    nav.lotes.clear()
    ex3, _ = rodar(db, eid, "elefante")
    assert _leituras(db, a.id) == 2, (
        f"o livro novo de A foi perdido (coleta 2: {ex2.status}/{ex2.motivo}, "
        f"cursor={cursor}; coleta 3: {ex3.status}/{ex3.motivo}, lotes={nav.lotes})")


def test_data_renomeada_e_formato_que_mudou_e_nao_conta_em_dia(db, escola_completa,
                                                               monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    credencial(db, eid, "elefante")
    instalar(monkeypatch, nav_elefante=NavElefante(_turma(
        ec, [_livro_data_renomeada("Livro Ficticio Um")],
        [_livro_data_renomeada("Livro Ficticio Dois")],
        [_livro_data_renomeada("Livro Ficticio Tres")])))
    ex, _ = rodar(db, eid, "elefante")
    alertas = _alertas(db, eid)
    assert alertas.get("parser_incompativel", (None,))[0] == "critico", (
        f"a data sumiu de todas as leituras e não abriu o alerta de formato: "
        f"{ex.status}/{ex.motivo} {alertas}")
    assert service.ultimo_em_dia_em(db, eid, "elefante") is None, (
        f"a coleta que perdeu TODAS as leituras contou como 'em dia' ({ex.status}/{ex.motivo})")
    assert db.scalar(select(func.count()).select_from(Leitura)) == 0
    # O alerta da coleta parcial não manda repetir o que não volta com outra coleta.
    _sev, msg = alertas["coleta_parcial"]
    assert "Sincronize de novo" not in msg, msg


def test_data_ilegivel_em_todas_as_linhas_tambem_e_formato(db, escola_completa, monkeypatch):
    """A chave continua lá, mas o valor deixou de ser uma data (objeto)."""
    ec = escola_completa
    eid = ec["escola"].id
    credencial(db, eid, "elefante")

    def _objeto(titulo):
        b = livro(titulo)
        b["lastReadWhen"] = {"valor": b["lastReadWhen"]}
        return b
    instalar(monkeypatch, nav_elefante=NavElefante(_turma(
        ec, [_objeto("Livro Ficticio Um")], [_objeto("Livro Ficticio Dois")],
        [_objeto("Livro Ficticio Tres")])))
    rodar(db, eid, "elefante")
    assert "parser_incompativel" in alertas_abertos(db, eid, "elefante")
    assert service.ultimo_em_dia_em(db, eid, "elefante") is None


def test_titulo_renomeado_em_todas_as_linhas_tambem_e_formato(db, escola_completa,
                                                              monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    credencial(db, eid, "elefante")

    def _sem_titulo(titulo):
        b = livro(titulo)
        b["title"] = b.pop("bookTitle")
        return b
    instalar(monkeypatch, nav_elefante=NavElefante(_turma(
        ec, [_sem_titulo("Livro Ficticio Um")], [_sem_titulo("Livro Ficticio Dois")],
        [_sem_titulo("Livro Ficticio Tres")])))
    rodar(db, eid, "elefante")
    assert "parser_incompativel" in alertas_abertos(db, eid, "elefante")
    assert service.ultimo_em_dia_em(db, eid, "elefante") is None
    assert service._carregar_contadores(db, eid, "elefante") == {}


def test_data_nula_explicita_continua_linha_descartada_em_dia(db, escola_completa,
                                                               monkeypatch):
    """Controle: nulo explícito é "sem dado" — mesmo em todas as linhas da turma —
    e segue a regra de sempre (linha descartada, em dia, sem alerta de formato)."""
    ec = escola_completa
    eid = ec["escola"].id
    credencial(db, eid, "elefante")
    instalar(monkeypatch, nav_elefante=NavElefante(_turma(
        ec, [livro("Livro Ficticio Um", data=None)], [livro("Livro Ficticio Dois", data=None)],
        [livro("Livro Ficticio Tres", data=None)])))
    ex, _ = rodar(db, eid, "elefante")
    assert (ex.status, ex.motivo) == ("parcial", "linhas_descartadas")
    assert "parser_incompativel" not in alertas_abertos(db, eid, "elefante")
    assert service.ultimo_em_dia_em(db, eid, "elefante") == ex.finalizada_em


def test_formato_misto_nao_e_formato_que_mudou(db, escola_completa, monkeypatch):
    """Controle: só PARTE dos livros sem a data é linha com defeito, não formato."""
    ec = escola_completa
    eid = ec["escola"].id
    credencial(db, eid, "elefante")
    instalar(monkeypatch, nav_elefante=NavElefante(_turma(
        ec, [livro("Livro Ficticio Um"), _livro_data_renomeada("Livro Ficticio Dois")],
        [livro("Livro Ficticio Tres")], [livro("Livro Ficticio Quatro")])))
    ex, _ = rodar(db, eid, "elefante")
    assert (ex.status, ex.motivo) == ("parcial", "linhas_descartadas")
    assert "parser_incompativel" not in alertas_abertos(db, eid, "elefante")


def test_leitura_descartada_nao_manda_sincronizar_de_novo(db, escola_completa, monkeypatch):
    """O cursor de quem teve um livro sem data AVANÇA (decisão: o defeito permanente
    não faz toda coleta pedir os livros de novo) — então "Sincronize de novo para
    completar" era falso: a próxima coleta sai 'nada mudou' e não pede o livro."""
    ec = escola_completa
    eid = ec["escola"].id
    credencial(db, eid, "elefante")
    nav = NavElefante(_turma(
        ec, [livro("Livro Ficticio Um"), livro("Livro Ficticio Sem Data", data=None)],
        [livro("Livro Ficticio Dois")], [livro("Livro Ficticio Tres")]))
    instalar(monkeypatch, nav_elefante=nav)
    ex, _ = rodar(db, eid, "elefante")
    assert (ex.status, ex.motivo) == ("parcial", "linhas_descartadas")
    _sev, msg = _alertas(db, eid)["coleta_parcial"]
    assert "leitura sem data: 1" in msg
    assert "Sincronize de novo" not in msg, msg
    assert "recoleta completa" in msg, msg
    # O que a mensagem diz é o que acontece: depois da 1ª recoleta completa (a 2ª
    # coleta, sem marca anterior), a coleta seguinte não pede o livro.
    rodar(db, eid, "elefante")
    nav.lotes.clear()
    ex3, _ = rodar(db, eid, "elefante")
    assert nav.lotes == [] and (ex3.status, ex3.motivo) == ("sem_atualizacao", "nada_mudou")


def test_campos_sumidos_do_livro():
    """A regra do conector: chave ausente ou valor ilegível = campo que sumiu;
    nulo/vazio explícito = sem dado."""
    f = con_elefante._campos_sumidos_do_livro
    assert f(livro("T")) == []
    assert f(livro("T", data=None)) == []
    assert f({**livro("T"), "lastReadWhen": ""}) == []
    assert f({**livro("T"), "lastReadWhen": "10/09/2026"}) == []
    assert f({**livro("T"), "lastReadWhen": "2026-09-10T10:00:00Z"}) == []
    assert f({"bookTitle": "T", "readWhen": "2026-09-10"}) == ["data"]
    assert f({**livro("T"), "lastReadWhen": "ontem"}) == ["data"]
    assert f({**livro("T"), "lastReadWhen": {"v": 1}}) == ["data"]
    assert f({"title": "T", "lastReadWhen": "2026-09-10"}) == ["título"]
    assert f({**livro("T"), "bookTitle": None}) == []
    assert f({**livro("T"), "bookTitle": {"pt": "T"}}) == ["título"]
