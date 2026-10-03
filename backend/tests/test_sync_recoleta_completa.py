"""O incremental é otimização, não verdade: recoleta completa periódica.

O BUG QUE ISTO TRAVA (medido na escola 1 em 03/10/2026, não suposto). O cursor
é ``{studentId: totalBooksRead}`` e esse total vem do relatório de TURMA do
Elefante. Duas crianças tinham, no relatório de turma, exatamente os MESMOS
livros, tempo, tentativas e acertos do último retrato gravado — e, no endpoint
por aluno, livros lidos em 01–09/09 e 21/09 que nunca entraram no Constela.
Nenhum dos quatro campos do relatório mudou, então nenhum sinal derivado dele
detectaria a novidade: o aluno fica congelado para sempre.

Não existe sinal melhor naquele relatório — isso foi medido, não inferido. A
correção aceita isso e garante uma recoleta completa a cada
``DIAS_ENTRE_COLETAS_COMPLETAS`` dias: toda perda passa a ter teto de tempo em
vez de ser permanente, seja ela por agregado defasado, por linha descartada no
import, ou por falha que o cursor não soube desfazer.

O que estes testes travam:
  * sem cursor, nada muda (a coleta já é completa);
  * cursor sem marca, ou com marca velha/ilegível, pede recoleta;
  * marca recente mantém o incremental (a otimização continua valendo);
  * a marca só avança quando a execução GRAVOU dados — recoleta que falhou no
    meio não reinicia o relógio;
  * e o caso real: com o relatório de turma idêntico, a recoleta encontra o
    livro que o cursor esconde.
"""
import asyncio
from datetime import timedelta

from app.models import Configuracao
from app.sync import service, vault
from app.sync.interfaces import Contexto, Credenciais

PLAT = "elefante"


def _marca(db, escola_id, quando, plataforma=PLAT):
    db.add(Configuracao(escola_id=escola_id, namespace=service._NS_INCREMENTAL,
                        chave=plataforma + service._SUFIXO_COMPLETA,
                        valor={"em": quando.isoformat() if hasattr(quando, "isoformat")
                               else quando}))
    db.commit()


# ---------------------------------------------------------------------------
# A regra de quando recoletar
# ---------------------------------------------------------------------------
def test_sem_cursor_a_coleta_ja_e_completa(db, escola_completa):
    """Primeira sync da escola: não há cursor para ignorar, então a recoleta
    não é "devida" — ela já acontece por natureza."""
    eid = escola_completa["escola"].id
    devida, motivo = service._coleta_completa_devida(db, eid, PLAT)
    assert devida is False
    assert motivo == "sem cursor"


def test_cursor_sem_marca_pede_recoleta(db, escola_completa):
    """Escola que já tem cursor e nunca passou por recoleta: a primeira coisa a
    fazer é reconciliar — é exatamente o estado de toda escola hoje."""
    eid = escola_completa["escola"].id
    service._salvar_contadores(db, eid, PLAT, {"111": 10})
    db.commit()
    devida, motivo = service._coleta_completa_devida(db, eid, PLAT)
    assert devida is True
    assert "nunca houve recoleta completa" in motivo


def test_marca_recente_mantem_o_incremental(db, escola_completa):
    eid = escola_completa["escola"].id
    service._salvar_contadores(db, eid, PLAT, {"111": 10})
    _marca(db, eid, service._agora() - timedelta(days=2))
    devida, motivo = service._coleta_completa_devida(db, eid, PLAT)
    assert devida is False
    assert "há 2 dia(s)" in motivo


def test_marca_antiga_pede_recoleta(db, escola_completa):
    eid = escola_completa["escola"].id
    service._salvar_contadores(db, eid, PLAT, {"111": 10})
    _marca(db, eid, service._agora()
           - timedelta(days=service.DIAS_ENTRE_COLETAS_COMPLETAS))
    devida, motivo = service._coleta_completa_devida(db, eid, PLAT)
    assert devida is True
    assert "última recoleta completa há" in motivo


def test_marca_ilegivel_pede_recoleta(db, escola_completa):
    """Fail-safe: marca corrompida recoleta. O caro é perder dado, não gastar
    uma coleta a mais."""
    eid = escola_completa["escola"].id
    service._salvar_contadores(db, eid, PLAT, {"111": 10})
    _marca(db, eid, "nao-e-uma-data")
    devida, motivo = service._coleta_completa_devida(db, eid, PLAT)
    assert devida is True
    assert "ilegível" in motivo


def test_marca_com_fuso_e_normalizada(db, escola_completa):
    """A marca normal nasce de ``_agora()``, que neste módulo é UTC NAIVE. Uma
    marca COM fuso (editada à mão, ou escrita por outra convenção) não pode
    explodir a subtração — tem de ser trazida para o mesmo referencial."""
    from datetime import timezone as _tz
    eid = escola_completa["escola"].id
    service._salvar_contadores(db, eid, PLAT, {"111": 10})
    _marca(db, eid, (service._agora() - timedelta(days=1)).replace(tzinfo=_tz.utc))
    devida, _motivo = service._coleta_completa_devida(db, eid, PLAT)
    assert devida is False


def test_marcar_grava_e_sobrescreve(db, escola_completa):
    eid = escola_completa["escola"].id
    service._marcar_coleta_completa(db, eid, PLAT)
    db.commit()
    primeira = service._linha_coleta_completa(db, eid, PLAT).valor["em"]
    depois = service._agora() + timedelta(days=1)
    service._marcar_coleta_completa(db, eid, PLAT, agora=depois)
    db.commit()
    linhas = db.query(Configuracao).filter(
        Configuracao.escola_id == eid,
        Configuracao.namespace == service._NS_INCREMENTAL,
        Configuracao.chave == PLAT + service._SUFIXO_COMPLETA).all()
    assert len(linhas) == 1                      # sobrescreve, não acumula
    assert linhas[0].valor["em"] != primeira


def test_o_cursor_de_livros_e_a_marca_nao_se_atropelam(db, escola_completa):
    """A marca mora no MESMO namespace do cursor, numa chave irmã. Gravar uma
    não pode apagar a outra."""
    eid = escola_completa["escola"].id
    service._salvar_contadores(db, eid, PLAT, {"111": 10})
    service._marcar_coleta_completa(db, eid, PLAT)
    db.commit()
    assert service._carregar_contadores(db, eid, PLAT) == {"111": 10}
    assert service._linha_coleta_completa(db, eid, PLAT) is not None
    # e o Matific tem a marca dele, independente
    assert service._linha_coleta_completa(db, eid, "matific") is None


# ---------------------------------------------------------------------------
# O executor: ignora o cursor, e só marca depois de gravar
# ---------------------------------------------------------------------------
class _ConectorEspiao:
    """Registra o que o serviço passou como cursor e devolve o que lhe disserem."""

    plataforma = PLAT
    versao = "test"

    def __init__(self, arquivos=()):
        self.arquivos = list(arquivos)
        self.cursor_recebido = None

    async def sincronizar(self, cred, contexto):
        self.cursor_recebido = dict(contexto.contadores_anteriores or {})
        return self.arquivos


def _preparar(db, escola_completa, monkeypatch, arquivos=()):
    escola = escola_completa["escola"]
    vault.salvar_credencial(db, escola.id, PLAT,
                            Credenciais(usuario="u@x", senha="s3nh4"))
    espiao = _ConectorEspiao(arquivos)
    monkeypatch.setattr(service.connectors, "obter", lambda _p: espiao)
    ex = service.enfileirar(db, escola.id, PLAT, origem="teste")
    db.commit()
    return escola, espiao, ex


def test_executar_ignora_o_cursor_quando_a_recoleta_e_devida(db, escola_completa,
                                                             monkeypatch):
    """O teste central: havendo cursor e nenhuma marca, o serviço entrega
    ``contadores_anteriores`` VAZIO — é isso que faz o conector buscar os livros
    do aluno que o total parado estava escondendo."""
    escola, espiao, ex = _preparar(db, escola_completa, monkeypatch)
    service._salvar_contadores(db, escola.id, PLAT, {"8157715": 27})
    db.commit()

    service.executar(db, ex)
    assert espiao.cursor_recebido == {}          # cursor IGNORADO


def test_executar_passa_o_cursor_quando_a_marca_e_recente(db, escola_completa,
                                                          monkeypatch):
    """A otimização não é jogada fora: fora da janela de reconciliação o cursor
    continua valendo."""
    escola, espiao, ex = _preparar(db, escola_completa, monkeypatch)
    service._salvar_contadores(db, escola.id, PLAT, {"8157715": 27})
    _marca(db, escola.id, service._agora() - timedelta(days=1))

    service.executar(db, ex)
    assert espiao.cursor_recebido == {"8157715": 27}


def test_recoleta_sem_dados_nao_reinicia_o_relogio(db, escola_completa, monkeypatch):
    """Uma recoleta que não gravou nada NÃO pode marcar "reconciliado" — senão a
    janela pularia e a perda voltaria a ser permanente por mais uma semana."""
    escola, espiao, ex = _preparar(db, escola_completa, monkeypatch, arquivos=[])
    service._salvar_contadores(db, escola.id, PLAT, {"8157715": 27})
    db.commit()

    res = service.executar(db, ex)
    assert res.status == "sem_dados"
    assert espiao.cursor_recebido == {}
    assert service._linha_coleta_completa(db, escola.id, PLAT) is None
    # e continua devida — a próxima execução tenta de novo
    devida, _m = service._coleta_completa_devida(db, escola.id, PLAT)
    assert devida is True


def test_nao_ha_loop_a_recoleta_bem_sucedida_fecha_a_janela(db, escola_completa,
                                                            monkeypatch):
    """Sem isto a correção viraria recoleta completa em TODA execução."""
    escola = escola_completa["escola"]
    service._salvar_contadores(db, escola.id, PLAT, {"8157715": 27})
    assert service._coleta_completa_devida(db, escola.id, PLAT)[0] is True

    # simula o que `executar` faz ao final de uma execução COM dados
    service._marcar_coleta_completa(db, escola.id, PLAT)
    db.commit()
    devida, motivo = service._coleta_completa_devida(db, escola.id, PLAT)
    assert devida is False
    assert "há 0 dia(s)" in motivo


# ---------------------------------------------------------------------------
# O caso real: relatório de turma IDÊNTICO, livro novo escondido
# ---------------------------------------------------------------------------
class _NavTotalParado:
    """Relatório de turma com o total PARADO (o caso medido) e um endpoint por
    aluno que tem um livro novo. Registra quais ids foram pedidos."""

    def __init__(self):
        self.buscou_ids = None

    async def ir_para(self, url): pass
    async def preencher(self, s, v): pass
    async def clicar(self, s): pass
    async def esperar(self, s, timeout_s=20): return True
    async def visivel(self, s): return "password" in s.lower()
    async def texto(self, s): return ""
    async def url_atual(self):
        return "https://admin.elefanteletrado.com.br/reports/menu"
    async def fechar(self): pass

    async def coletar_respostas(self, url, timeout_s=25):
        return [{"url": "https://prod-ecs-apiadmin.elefanteletrado.com.br/"
                        "course/get-courses-students",
                 "json": [{"id": 511434, "name": "5B", "student": [
                     {"id": 2751737, "name": "CESAR BENITO DINIZ ALVES"}]}]}]

    async def avaliar(self, expressao):
        if "fetch(" in expressao and "overall-course-report" in expressao:
            # TODOS os campos iguais ao que já está gravado: nenhum sinal muda.
            return {"ok": True, "status": 200, "tipo": "object", "n": 0, "body": {
                "courseId": 511434,
                "courseSchoolDescriptors": {"courseName": "5B"},
                "students": [{"studentId": 2751737,
                              "studentName": "CESAR BENITO DINIZ ALVES",
                              "totalBooksRead": 184, "totalReadTime": 21600,
                              "responses": 289, "approvedResponses": 172}]}}
        if "fetch(" in expressao and "overall-student-books-read" in expressao:
            import re
            self.buscou_ids = [n for n in re.findall(r"\b(\d{3,})\b", expressao)
                               if n == "2751737"]
            return [{"studentId": 2751737, "n": 1, "books": [
                {"bookTitle": "Histórias do Mundo-O pavão e o corvo",
                 "levelName": "E", "lastReadWhen": "2026-09-21T10:40:46",
                 "totalTimeSpent": 120}]}]
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


def _coletar(cursor):
    from app.sync.connectors import elefante
    nav = _NavTotalParado()

    async def fab(**_kw):
        return nav
    ctx = Contexto(escola_id=1, execucao_id=None, log=lambda e, n, m: None,
                   contadores_anteriores=dict(cursor))
    arquivos = asyncio.run(elefante.ConectorElefante(fab).sincronizar(
        Credenciais(usuario="u", senha="p"), ctx))
    return nav, ctx, arquivos


def test_o_cursor_esconde_o_livro_quando_o_total_nao_muda(monkeypatch):
    """Reprodução do bug: total 184 == cursor 184 → o aluno é pulado e o livro
    de 21/09 não é nem pedido. Este é o comportamento ANTIGO, e é por isso que
    a perda era permanente."""
    from app.sync.connectors import elefante
    monkeypatch.setattr(elefante, "_SETTLE_S", 0)
    nav, _ctx, arquivos = _coletar({"2751737": 184})
    assert nav.buscou_ids is None                       # nem foi pedido
    assert not [a for a in arquivos if a.formato_hint == "leituras"]


def test_a_recoleta_completa_encontra_o_livro_escondido(monkeypatch):
    """A correção: com o cursor ignorado (``contadores_anteriores`` vazio), o
    MESMO relatório de turma parado deixa de esconder o livro."""
    from app.sync.connectors import elefante
    monkeypatch.setattr(elefante, "_SETTLE_S", 0)
    nav, ctx, arquivos = _coletar({})
    assert nav.buscou_ids == ["2751737"]
    leituras = [a for a in arquivos if a.formato_hint == "leituras"]
    assert leituras, "a recoleta tem de produzir o arquivo de leituras"
    import json
    payload = json.loads(leituras[0].conteudo.decode("utf-8"))
    titulos = [x["bookTitle"] for x in payload["leituras"]]
    assert "Histórias do Mundo-O pavão e o corvo" in titulos
    # e o cursor novo é registrado para a próxima execução
    assert ctx.contadores_novos == {"2751737": 184}


def test_a_recoleta_e_idempotente_no_conector(monkeypatch):
    """Rodar duas vezes devolve o mesmo payload — a dedup real é das UNIQUE de
    Leitura/EventoAluno, mas a coleta não pode variar sozinha."""
    from app.sync.connectors import elefante
    monkeypatch.setattr(elefante, "_SETTLE_S", 0)
    _n1, _c1, a1 = _coletar({})
    _n2, _c2, a2 = _coletar({})
    p1 = [a.conteudo for a in a1 if a.formato_hint == "leituras"]
    p2 = [a.conteudo for a in a2 if a.formato_hint == "leituras"]
    assert p1 == p2
