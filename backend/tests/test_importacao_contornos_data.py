"""Contornos da data do relatório (revisão da rodada 2 do achado [10], 01/11/2026).

Os PoCs do revisor viraram testes:

* A — retrato LEGADO datado no futuro (o servidor aceitava qualquer data) fazia a
  coleta do dia virar "retrodatada": a sincronização da escola inteira era
  recusada (422 → ``ErroConector`` parser_incompativel, não recuperável) com a
  mensagem errada "confira a data informada". Agora o retrato acima de agora +
  folga não conta como o atual; e, se mesmo assim faltar base, a sync grava como
  antes, com aviso no log.
* B — piso da data (1º de janeiro do ano letivo anterior) e datas absurdas: 422,
  nunca 500.
* C — Matific com formato "leituras" escapava da recusa sem data.
* D — "lavagem" da origem: um upload COM data do mesmo dia complementava o retrato
  da sync no lugar e apagava a prova de que ele veio dela.
* E — relatório individual do Elefante com data passada criava um ponto NA DATA
  com os números do retrato mais novo.

Resíduos da revisão da rodada 3 (PoCs r1–r3):

* r1 — a regra D contava só a execução INICIADA no dia do retrato: a sync que
  cruza a meia-noite de Brasília escapava. Agora conta a janela da execução.
* r2 — um retrato legado de 0001-01-01 estourava em ``_mesmo_dia`` (OverflowError):
  a sincronização caía para a escola inteira e o upload manual dava 500.
* r3 — sem retrato válido posterior, o relatório individual com data passada
  datava em D o total de TODAS as leituras, inclusive as de depois de D.

Resíduos da revisão final (PoCs p1 e p2, 01/11):

* p1 — regressão do r1: a regra D subtraía a janela da execução do início do dia do
  retrato; com o retrato legado no dia 0001-01-01 de Brasília, a conta estourava
  (OverflowError) e o upload manual SEM data dava 500.
* p2 — já existia: uma pendência de revisão LEGADA com a data do ano 1 derrubava a
  sincronização da escola inteira (``_linha_substitui_o_congelado`` chamava
  ``para_br`` direto) e o /resolver dava 500 (``_retrato_superado``); um intervalo
  do Matific no ano 1 guardado na pendência também dava 500 no /resolver.
"""
import logging
from datetime import datetime, time, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.core.tempo import FUSO_BR, para_br
from app.models import (
    EventoAluno,
    IdentidadeExterna,
    Importacao,
    Leitura,
    RevisaoIdentidade,
    SincronizacaoExecucao,
    SnapshotElefante,
    SnapshotMatific,
)
from app.routers import importacoes as imp
from app.schemas import ImportacaoConfirm
from tests.sync_integridade_comum import aplicar, elefante_resumo, sem_disco
from tests.test_importacao_data_do_relatorio import _sync_matific
from tests.test_revisao_encerramento_automatico import (  # noqa: F401 — fixtures
    CHAVE_GIOVANA,
    NOME_ELEFANTE_GIOVANA,
    SALA,
    SID_GIOVANA,
    _pendencia,
    _sincronizar_elefante,
    oficial_e_stub,
    sala,
)

API = "/api/v1/escolas/{}/importacoes/confirmar"
OUTUBRO = "2026-10-25T12:00:00Z"
AGOSTO = "2026-08-15T02:59:59Z"      # fim do dia 14/08 em Brasília (o que a tela manda)


def _agora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _meia_noite_de_brasilia(momento: datetime) -> datetime:
    """O começo do dia (de Brasília) deste instante, em UTC naive."""
    return (datetime.combine(para_br(momento).date(), time(0, 0), tzinfo=FUSO_BR)
            .astimezone(timezone.utc).replace(tzinfo=None))


def _snaps(db, modelo, aluno_id: int) -> list:
    db.expire_all()
    return list(db.execute(
        select(modelo).where(modelo.aluno_id == aluno_id)
        .order_by(modelo.data_referencia, modelo.id)).scalars())


def _n_importacoes(db, escola_id: int) -> int:
    return db.scalar(select(func.count()).select_from(Importacao)
                     .where(Importacao.escola_id == escola_id))


def _post(cliente, escola_id: int, corpo: dict):
    return cliente.post(API.format(escola_id), json=corpo)


def _matific(aluno, dados: dict, data_referencia: str | None = None, *,
             tipo: str = "pdf", formato: str = "resumo", **extra) -> dict:
    corpo = {"plataforma": "matific", "formato": formato, "tipo": tipo,
             "linhas": [{"nome": aluno.nome, "aluno_id": aluno.id, "dados": dados}], **extra}
    if data_referencia is not None:
        corpo["data_referencia"] = data_referencia
    return corpo


def _retrato_legado_no_futuro(db, escola, admin, aluno, *, dias: float) -> SnapshotElefante:
    """Retrato do Elefante gravado por um upload manual ANTIGO com data no futuro."""
    legado = Importacao(escola_id=escola.id, usuario_id=admin.id, plataforma="elefante",
                        tipo="pdf", status="concluida")
    db.add(legado)
    db.flush()
    snap = SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id, importacao_id=legado.id,
                            data_referencia=_agora() + timedelta(days=dias),
                            livros_unicos=3, tempo_leitura_min=5, questoes_tentativas=1,
                            questoes_acertos=1, livros_por_nivel={"AA": 3})
    db.add(snap)
    db.commit()
    return snap


def _confirmacao_da_sync_elefante(alunos) -> ImportacaoConfirm:
    """O pedido que o orquestrador monta para o resumo do Elefante (que nunca traz
    os livros por nível)."""
    return imp.confirmacao_da_sincronizacao(ImportacaoConfirm(
        plataforma="elefante", formato="resumo", tipo="texto", recalcular=False,
        sincronizar_turma=True, permitir_criar_turma=False,
        linhas=[{"nome": a.nome, "aluno_id": a.id,
                 "dados": {"livros_unicos": 12, "tempo_leitura_min": 90,
                           "questoes_tentativas": 4, "questoes_acertos": 3}} for a in alunos]))


# --- A: retrato legado no futuro × sincronização ------------------------------

def test_sync_do_elefante_com_retrato_futuro_legado_aceita_a_escola(db, escola_completa,
                                                                    monkeypatch):
    """PoC 4b pelo caminho REAL da sincronização (orquestrador). Antes: 422 dentro do
    /confirmar → ``ErroConector`` parser_incompativel, e a escola inteira ficava sem
    a coleta (João, sem retrato nenhum, também). Agora os dois são gravados; o
    retrato futuro não serve de base (não herda dele) e fica como estava."""
    escola, admin = escola_completa["escola"], escola_completa["admin"]
    ana, joao = escola_completa["alunos"][:2]
    sem_disco(monkeypatch)
    futuro = _retrato_legado_no_futuro(db, escola, admin, ana, dias=30)
    data_futuro = futuro.data_referencia

    res = aplicar(db, escola, elefante_resumo("3º Ano A", [
        {"studentName": ana.nome, "totalBooksRead": 12},
        {"studentName": joao.nome, "totalBooksRead": 7}]))

    assert res["qtd_alunos"] == 2
    hoje, legado = _snaps(db, SnapshotElefante, ana.id)
    assert hoje.data_referencia.date() <= _agora().date()
    assert (hoje.livros_unicos, hoje.livros_por_nivel) == (12, {})   # nada herdado do futuro
    assert (legado.livros_unicos, legado.livros_por_nivel) == (3, {"AA": 3})
    assert legado.data_referencia == data_futuro
    assert [s.livros_unicos for s in _snaps(db, SnapshotElefante, joao.id)] == [7]


def test_sync_sem_base_nao_recusa_a_escola_e_avisa_no_log(db, escola_completa, monkeypatch,
                                                          caplog):
    """Mesmo ignorando o futuro, um retrato VÁLIDO (dentro da folga) do dia seguinte
    de Brasília deixa a coleta "retrodatada" — perto da meia-noite. Sem retrato
    anterior de onde completar os livros por nível, a sync grava como antes
    (herdando do retrato mais novo válido) e avisa no log, sem nome de aluno."""
    escola, admin = escola_completa["escola"], escola_completa["admin"]
    ana, joao = escola_completa["alunos"][:2]
    # Folga de 2 dias: o retrato de amanhã conta como válido (simula a meia-noite).
    monkeypatch.setattr(imp, "_FOLGA_DATA_FUTURA", timedelta(days=2))
    _retrato_legado_no_futuro(db, escola, admin, ana, dias=1)
    caplog.set_level(logging.WARNING, logger="constela.sync")

    imp.confirmar(dados=_confirmacao_da_sync_elefante((ana, joao)), escola_id=escola.id,
                  usuario=admin, db=db)

    hoje, amanha = _snaps(db, SnapshotElefante, ana.id)
    assert hoje.livros_unicos == 12
    assert hoje.livros_por_nivel == {"AA": 3}      # o comportamento de antes, na sync
    assert [s.livros_unicos for s in _snaps(db, SnapshotElefante, joao.id)] == [12]
    avisos = [r.getMessage() for r in caplog.records
              if r.name == "constela.sync" and r.levelno == logging.WARNING]
    assert len(avisos) == 1
    assert "1 aluno(s)" in avisos[0] and "livros_por_nivel" in avisos[0]
    assert ana.nome.split()[0] not in avisos[0] and joao.nome.split()[0] not in avisos[0]


def test_upload_sem_data_diante_de_retrato_mais_novo_nao_fala_em_data_informada(
        cliente, db, escola_completa, monkeypatch):
    """O mesmo caso no upload manual SEM data (só pela API): recusa, mas a mensagem
    pede a data — não manda "conferir a data informada", que não existe."""
    escola, admin = escola_completa["escola"], escola_completa["admin"]
    ana = escola_completa["alunos"][0]
    monkeypatch.setattr(imp, "_FOLGA_DATA_FUTURA", timedelta(days=2))
    _retrato_legado_no_futuro(db, escola, admin, ana, dias=1)
    n_imp = _n_importacoes(db, escola.id)

    r = _post(cliente, escola.id, {
        "plataforma": "elefante", "formato": "resumo", "tipo": "pdf",
        "linhas": [{"nome": ana.nome, "aluno_id": ana.id,
                    "dados": {"livros_unicos": 7, "tempo_leitura_min": 50,
                              "questoes_tentativas": 20, "questoes_acertos": 15}}]})

    assert r.status_code == 422, r.text
    detalhe = r.json()["detail"]
    assert detalhe.startswith("Informe a data do relatório")
    assert "data informada" not in detalhe and "livros por nível" in detalhe
    assert "Nada foi gravado" in detalhe and "Ana" not in detalhe
    assert len(_snaps(db, SnapshotElefante, ana.id)) == 1
    assert _n_importacoes(db, escola.id) == n_imp


def test_retrato_futuro_legado_nao_esconde_o_retrato_da_sync_da_recusa_sem_data(
        cliente, db, escola_completa, monkeypatch):
    """Upload manual: com o retrato futuro como "o atual", a recusa sem data olhava a
    importação DELE (manual) e deixava passar; o arquivo sem data então completava
    no lugar o retrato que a sync gravou hoje. Agora o atual é o da sync: 422."""
    escola, admin = escola_completa["escola"], escola_completa["admin"]
    ana = escola_completa["alunos"][0]
    _sync_matific(db, escola, monkeypatch, atividades=50, estrelas=300)
    # O upload antigo que gravou o retrato futuro (bem antes da sync de hoje).
    legado = Importacao(escola_id=escola.id, usuario_id=admin.id, plataforma="matific",
                        tipo="pdf", status="concluida",
                        created_at=_agora() - timedelta(days=60))
    db.add(legado)
    db.flush()
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=ana.id, importacao_id=legado.id,
                           data_referencia=_agora() + timedelta(days=30),
                           atividades=5, estrelas=5, pontuacao_media=1.0))
    db.commit()

    r = _post(cliente, escola.id, _matific(ana, {"atividades": 20, "estrelas": 100,
                                                 "pontuacao_media": 2.0}))

    assert r.status_code == 422, r.text
    assert "Informe a data do relatório" in r.json()["detail"]
    assert [(s.atividades, s.estrelas) for s in _snaps(db, SnapshotMatific, ana.id)] == [
        (50, 300), (5, 5)]


@pytest.mark.parametrize("caminho", ["sincronizacao", "upload"])
def test_retrato_legado_do_ano_1_nao_derruba_a_importacao(cliente, db, escola_completa,
                                                          monkeypatch, caminho):
    """PoC r2: retrato legado de 0001-01-01 00h (UTC) — em Brasília, ainda o ano 0, que
    o ``datetime`` não tem. ``_mesmo_dia`` estourava com OverflowError: a sync do
    Elefante caía para a escola INTEIRA (falha inesperada, não HTTPException) e o
    upload manual dava 500. Agora a data legada não é "o mesmo dia" de nada: a
    coleta de hoje vira um retrato novo e o legado fica como estava."""
    escola, admin = escola_completa["escola"], escola_completa["admin"]
    ana, joao = escola_completa["alunos"][:2]
    legado = Importacao(escola_id=escola.id, usuario_id=admin.id, plataforma="elefante",
                        tipo="pdf", status="concluida")
    db.add(legado)
    db.flush()
    db.add(SnapshotElefante(escola_id=escola.id, aluno_id=ana.id, importacao_id=legado.id,
                            data_referencia=datetime(1, 1, 1, 0, 0, 0),
                            livros_unicos=3, tempo_leitura_min=5, questoes_tentativas=1,
                            questoes_acertos=1, livros_por_nivel={"AA": 3}))
    db.commit()

    if caminho == "sincronizacao":
        sem_disco(monkeypatch)
        res = aplicar(db, escola, elefante_resumo("3º Ano A", [
            {"studentName": ana.nome, "totalBooksRead": 12},
            {"studentName": joao.nome, "totalBooksRead": 7}]))
        assert res["qtd_alunos"] == 2
        assert [s.livros_unicos for s in _snaps(db, SnapshotElefante, joao.id)] == [7]
    else:
        r = _post(cliente, escola.id, {
            "plataforma": "elefante", "formato": "resumo", "tipo": "pdf",
            "data_referencia": datetime.now(timezone.utc).isoformat(),
            "linhas": [{"nome": ana.nome, "aluno_id": ana.id,
                        "dados": {"livros_unicos": 12, "tempo_leitura_min": 90,
                                  "questoes_tentativas": 4, "questoes_acertos": 3}}]})
        assert r.status_code == 200, r.text

    antigo, hoje = _snaps(db, SnapshotElefante, ana.id)
    assert (antigo.data_referencia, antigo.livros_unicos) == (datetime(1, 1, 1), 3)
    assert hoje.livros_unicos == 12
    assert abs(hoje.data_referencia - _agora()) < timedelta(minutes=5)


# --- B: piso da data e datas absurdas -----------------------------------------

def test_data_muito_antiga_e_recusada_com_mensagem_clara(cliente, db, escola_completa):
    """PoC 5: 1990 recebia 200 e criava um ponto em 1990 (a base de qualquer janela
    sem retrato anterior). O caso realista é digitar 2006 em vez de 2026."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    for data in ("1990-01-01T00:00:00Z", "2006-10-25T12:00:00-03:00"):
        r = _post(cliente, escola.id, _matific(ana, {"atividades": 5, "estrelas": 5,
                                                     "pontuacao_media": 1.0}, data))
        assert r.status_code == 422, r.text
        detalhe = r.json()["detail"]
        assert detalhe.startswith("A data do relatório parece errada")
        assert "01/01/2025" in detalhe and "Confira o ano" in detalhe
        assert "Nada foi gravado" in detalhe
    assert _snaps(db, SnapshotMatific, ana.id) == []
    assert _n_importacoes(db, escola.id) == 0


@pytest.mark.parametrize("data", [
    "0001-01-01T00:00:00Z",
    "0001-01-01T00:00:00+14:00",      # quebrava já na conversão para UTC
    "0001-01-01T00:00:00",
    "9999-12-31T23:59:59-14:00",
    "9999-12-31T23:59:59Z",
])
def test_datas_absurdas_dao_422_e_nunca_500(cliente, db, escola_completa, data):
    """Com um retrato já gravado (o caminho que convertia a data em ``para_br`` e
    estourava). O TestClient relança erro do servidor: um 500 quebraria o teste."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    assert _post(cliente, escola.id, _matific(ana, {"atividades": 50, "estrelas": 300,
                                                    "pontuacao_media": 3.0},
                                              OUTUBRO)).status_code == 200

    r = _post(cliente, escola.id, _matific(ana, {"atividades": 5, "estrelas": 5,
                                                 "pontuacao_media": 1.0}, data))

    assert r.status_code == 422, r.text
    assert "Nada foi gravado" in r.json()["detail"]
    assert [(s.atividades, s.estrelas) for s in _snaps(db, SnapshotMatific, ana.id)] == [(50, 300)]


def test_piso_e_o_primeiro_de_janeiro_do_ano_letivo_anterior(cliente, db, escola_completa):
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    dados = {"atividades": 5, "estrelas": 5, "pontuacao_media": 1.0}
    assert _post(cliente, escola.id, _matific(
        ana, dados, "2024-12-31T12:00:00-03:00")).status_code == 422
    assert _post(cliente, escola.id, _matific(
        ana, dados, "2025-01-01T12:00:00-03:00")).status_code == 200

    escola.ano_letivo_ativo = 2025      # escola com o ano letivo anterior ativo
    db.commit()
    r = _post(cliente, escola.id, _matific(ana, {**dados, "atividades": 2},
                                           "2024-06-01T12:00:00-03:00"))
    assert r.status_code == 200, r.text
    assert [s.data_referencia.date().isoformat() for s in _snaps(db, SnapshotMatific, ana.id)] == [
        "2024-06-01", "2025-01-01"]


@pytest.mark.parametrize("inicio,fim", [
    ("0001-01-01T00:00:00", "0001-02-01T00:00:00"),   # o retrato-base na véspera estourava
    ("1990-03-01T00:00:00", "1990-04-01T00:00:00"),
])
def test_intervalo_de_datas_absurdo_do_matific_da_422(cliente, db, escola_completa, inicio, fim):
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    r = _post(cliente, escola.id, _matific(ana, {"atividades": 5, "estrelas": 5,
                                                 "pontuacao_media": 1.0},
                                           periodo_inicio=inicio, periodo_fim=fim))
    assert r.status_code == 422, r.text
    assert "intervalo de datas do relatório parece errado" in r.json()["detail"]
    assert _snaps(db, SnapshotMatific, ana.id) == []


# --- C: Matific com formato "leituras" ----------------------------------------

def test_matific_com_formato_leituras_e_recusado(cliente, db, escola_completa, monkeypatch):
    """PoC 1: o schema aceita Matific + leituras e o pedido ia para
    ``_importar_matific``, escapando da recusa sem data (que olha o formato
    "resumo"): o retrato da sync (50, 300) virava (20, 100) "como hoje"."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    _sync_matific(db, escola, monkeypatch, atividades=50, estrelas=300)
    (antes,) = _snaps(db, SnapshotMatific, ana.id)
    origem = antes.importacao_id
    n_imp = _n_importacoes(db, escola.id)

    for data in (None, datetime.now(timezone.utc).isoformat()):
        r = _post(cliente, escola.id, _matific(
            ana, {"atividades": 20, "estrelas": 100, "pontuacao_media": 2.0}, data,
            formato="leituras"))
        assert r.status_code == 422, r.text
        assert r.json()["detail"] == "O Matific não tem relatório individual de leituras."

    (depois,) = _snaps(db, SnapshotMatific, ana.id)
    assert (depois.atividades, depois.estrelas, depois.importacao_id) == (50, 300, origem)
    assert _n_importacoes(db, escola.id) == n_imp


# --- D: lavagem da origem pelo upload datado do mesmo dia ---------------------

def test_upload_datado_do_mesmo_dia_nao_lava_a_origem_da_sync(cliente, db, escola_completa,
                                                              monkeypatch):
    """PoC 2b: a sync grava (50, 300) hoje; um Excel COM a data de hoje (só
    atividades) complementa esse retrato no lugar e troca o ``importacao_id`` para o
    manual. Antes, o PDF SEM data seguinte passava e trocava as 300 estrelas da sync
    por 100, "como hoje". Agora: a sync rodou no dia do retrato atual — 422."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    _sync_matific(db, escola, monkeypatch, atividades=50, estrelas=300)
    (snap,) = _snaps(db, SnapshotMatific, ana.id)
    # A coleta foi há alguns minutos, no MESMO dia de Brasília (nunca antes da
    # meia-noite, para o teste não depender da hora em que roda).
    agora = _agora()
    iniciada = max(_meia_noite_de_brasilia(agora), agora - timedelta(minutes=10))
    finalizada = min(agora, iniciada + timedelta(minutes=2))
    meio = iniciada + (finalizada - iniciada) / 2
    execucao = db.execute(select(SincronizacaoExecucao)).scalars().one()
    importacao_sync = db.get(Importacao, snap.importacao_id)
    execucao.iniciada_em, execucao.finalizada_em = iniciada, finalizada
    execucao.importacao_id = importacao_sync.id
    importacao_sync.created_at = meio
    snap.data_referencia = meio
    db.commit()

    controle = _post(cliente, escola.id, _matific(ana, {"atividades": 20, "estrelas": 100,
                                                        "pontuacao_media": 2.0}))
    assert controle.status_code == 422, controle.text

    r1 = _post(cliente, escola.id, _matific(ana, {"atividades": 51, "pontuacao_media": 3.0},
                                            datetime.now(timezone.utc).isoformat(), tipo="xlsx"))
    assert r1.status_code == 200, r1.text
    (complementado,) = _snaps(db, SnapshotMatific, ana.id)
    assert (complementado.atividades, complementado.estrelas) == (51, 300)
    assert complementado.importacao_id != importacao_sync.id      # a origem "lavada"

    r2 = _post(cliente, escola.id, _matific(ana, {"atividades": 20, "estrelas": 100,
                                                  "pontuacao_media": 2.0}))

    assert r2.status_code == 422, r2.text
    assert "Informe a data do relatório" in r2.json()["detail"]
    assert [(s.atividades, s.estrelas) for s in _snaps(db, SnapshotMatific, ana.id)] == [(51, 300)]


def test_sync_de_dias_atras_nao_bloqueia_o_upload_sem_data_sobre_o_manual_de_hoje(
        cliente, db, escola_completa, monkeypatch):
    """A regra nova não pega quem não deve: a sync rodou há uma semana; hoje só houve
    upload manual. Entre uploads manuais do mesmo dia nada muda (complementa)."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    _sync_matific(db, escola, monkeypatch, atividades=50, estrelas=300)
    (snap,) = _snaps(db, SnapshotMatific, ana.id)
    semana = _agora() - timedelta(days=7)
    execucao = db.execute(select(SincronizacaoExecucao)).scalars().one()
    importacao_sync = db.get(Importacao, snap.importacao_id)
    execucao.iniciada_em, execucao.finalizada_em = semana, semana + timedelta(minutes=2)
    execucao.importacao_id = importacao_sync.id
    importacao_sync.created_at = semana + timedelta(minutes=1)
    snap.data_referencia = semana + timedelta(minutes=1)
    db.commit()

    assert _post(cliente, escola.id, _matific(
        ana, {"atividades": 60, "estrelas": 320, "pontuacao_media": 3.0},
        datetime.now(timezone.utc).isoformat())).status_code == 200
    r = _post(cliente, escola.id, _matific(ana, {"atividades": 61, "pontuacao_media": 3.1},
                                           tipo="xlsx"))

    assert r.status_code == 200, r.text
    assert [(s.atividades, s.estrelas) for s in _snaps(db, SnapshotMatific, ana.id)] == [
        (50, 300), (61, 320)]


def test_sync_que_cruza_a_meia_noite_tambem_conta_para_a_regra_d(cliente, db, escola_completa,
                                                                 monkeypatch):
    """PoC r1: a sync começou 2 min ANTES da meia-noite de Brasília e gravou o retrato
    2 min depois dela. A regra D contava só execução INICIADA no dia do retrato:
    esta era "de ontem", o Excel datado de hoje lavava a origem e o PDF sem data
    trocava (51, 300) por (20, 100). Agora conta a janela da execução (até o fim)."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    _sync_matific(db, escola, monkeypatch, atividades=50, estrelas=300)
    (snap,) = _snaps(db, SnapshotMatific, ana.id)
    meia_noite = _meia_noite_de_brasilia(_agora())
    execucao = db.execute(select(SincronizacaoExecucao)).scalars().one()
    importacao_sync = db.get(Importacao, snap.importacao_id)
    execucao.iniciada_em = meia_noite - timedelta(minutes=2)
    execucao.finalizada_em = meia_noite + timedelta(minutes=3)
    execucao.importacao_id = importacao_sync.id
    importacao_sync.created_at = meia_noite + timedelta(minutes=2)
    snap.data_referencia = meia_noite + timedelta(minutes=2)
    db.commit()

    controle = _post(cliente, escola.id, _matific(ana, {"atividades": 20, "estrelas": 100,
                                                        "pontuacao_media": 2.0}))
    assert controle.status_code == 422, controle.text     # a importação é da sync

    r1 = _post(cliente, escola.id, _matific(ana, {"atividades": 51, "pontuacao_media": 3.0},
                                            datetime.now(timezone.utc).isoformat(), tipo="xlsx"))
    assert r1.status_code == 200, r1.text
    (complementado,) = _snaps(db, SnapshotMatific, ana.id)
    assert (complementado.atividades, complementado.estrelas) == (51, 300)
    assert complementado.importacao_id != importacao_sync.id      # a origem "lavada"
    # O Excel foi enviado DEPOIS da janela da execução: a regra pela importação não
    # o pega, seja qual for a hora em que o teste roda (nos primeiros minutos do
    # dia, o horário real cairia dentro da janela e esconderia o contorno).
    db.get(Importacao, complementado.importacao_id).created_at = meia_noite + timedelta(minutes=30)
    db.commit()

    r2 = _post(cliente, escola.id, _matific(ana, {"atividades": 20, "estrelas": 100,
                                                  "pontuacao_media": 2.0}))

    assert r2.status_code == 422, r2.text
    assert "Informe a data do relatório" in r2.json()["detail"]
    assert [(s.atividades, s.estrelas) for s in _snaps(db, SnapshotMatific, ana.id)] == [(51, 300)]


# --- E: relatório individual do Elefante com data passada ---------------------

def test_elefante_leituras_com_data_passada_nao_cria_ponto_no_passado(cliente, db,
                                                                      escola_completa):
    """PoC 3: retrato de 25/10 com (12 livros, 90 min, 40/30 questões); o relatório
    individual datado de 15/08 criava o ponto de agosto com os números de outubro.
    Agora a data fica nas Leituras e nos eventos; o retrato derivado (o TOTAL de
    todas as leituras) atualiza o atual no lugar, sem recuar a data dele."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    assert _post(cliente, escola.id, {
        "plataforma": "elefante", "formato": "resumo", "tipo": "pdf", "data_referencia": OUTUBRO,
        "linhas": [{"nome": ana.nome, "aluno_id": ana.id,
                    "dados": {"livros_unicos": 12, "livros_por_nivel": {"AA": 12},
                              "tempo_leitura_min": 90, "questoes_tentativas": 40,
                              "questoes_acertos": 30}}]}).status_code == 200
    (outubro,) = _snaps(db, SnapshotElefante, ana.id)
    data_outubro = outubro.data_referencia

    r = _post(cliente, escola.id, {
        "plataforma": "elefante", "formato": "leituras", "tipo": "texto", "data_referencia": AGOSTO,
        "linhas": [
            {"nome": ana.nome, "aluno_id": ana.id,
             "dados": {"livro": "Livro Teste", "nivel": "AA", "data": "2026-08-10T10:00:00"}},
            {"nome": ana.nome, "aluno_id": ana.id,
             "dados": {"livro": "Outro Livro", "nivel": "BB"}}]})

    assert r.status_code == 200, r.text
    snaps = _snaps(db, SnapshotElefante, ana.id)
    assert not any(s.data_referencia.month == 8 for s in snaps)
    (atual,) = snaps
    assert atual.data_referencia == data_outubro                 # max(15/08, 25/10)
    assert (atual.livros_unicos, atual.tempo_leitura_min,
            atual.questoes_tentativas, atual.questoes_acertos) == (12, 90, 40, 30)
    assert atual.livros_por_nivel == {"AA": 1, "BB": 1}          # o das leituras, como sempre
    datas = sorted(d.isoformat() for d in db.execute(
        select(Leitura.data).where(Leitura.aluno_id == ana.id)).scalars())
    assert datas == ["2026-08-10T10:00:00", "2026-08-15T02:59:59"]
    eventos = list(db.execute(select(EventoAluno.ocorrido_em)
                              .where(EventoAluno.aluno_id == ana.id)).scalars())
    assert [e.isoformat() for e in eventos] == ["2026-08-10T10:00:00"]


def _leituras_com_data(aluno, data_referencia: str, *datas: str) -> dict:
    return {"plataforma": "elefante", "formato": "leituras", "tipo": "texto",
            "data_referencia": data_referencia,
            "linhas": [{"nome": aluno.nome, "aluno_id": aluno.id,
                        "dados": {"livro": f"Livro {i + 1}", "nivel": "AA", "data": data}}
                       for i, data in enumerate(datas)]}


def test_elefante_leituras_com_data_passada_sem_retrato_posterior_data_na_leitura_mais_nova(
        cliente, db, escola_completa):
    """PoC r3: sem retrato nenhum, o relatório individual de 15/08 com leituras de
    10/08 e de 20/10 criava o ponto de 15/08 com os 2 livros — a leitura de outubro
    contada em agosto. O retrato derivado é o TOTAL de todas as leituras: fica
    datado na mais nova delas. As datas de cada leitura não mudam."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]

    r = _post(cliente, escola.id, _leituras_com_data(
        ana, AGOSTO, "2026-08-10T10:00:00", "2026-10-20T10:00:00"))

    assert r.status_code == 200, r.text
    snaps = _snaps(db, SnapshotElefante, ana.id)
    assert not any(s.data_referencia.month == 8 for s in snaps)
    (atual,) = snaps
    assert (atual.data_referencia, atual.livros_unicos) == (datetime(2026, 10, 20, 10, 0), 2)
    datas = sorted(d.isoformat() for d in db.execute(
        select(Leitura.data).where(Leitura.aluno_id == ana.id)).scalars())
    assert datas == ["2026-08-10T10:00:00", "2026-10-20T10:00:00"]


def test_leitura_com_data_no_futuro_nao_leva_o_retrato_para_o_futuro(cliente, db,
                                                                      escola_completa,
                                                                      monkeypatch):
    """O limite da data do retrato derivado é agora: uma leitura datada no futuro
    (relógio errado na plataforma) não cria um retrato que esconderia as coletas
    seguintes até lá."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    agora = datetime(2026, 11, 1, 15, 0, 0)
    monkeypatch.setattr(imp, "_agora_utc", lambda: agora)

    r = _post(cliente, escola.id, _leituras_com_data(
        ana, AGOSTO, "2026-08-10T10:00:00", "2099-01-01T00:00:00"))

    assert r.status_code == 200, r.text
    (atual,) = _snaps(db, SnapshotElefante, ana.id)
    assert (atual.data_referencia, atual.livros_unicos) == (agora, 2)


def test_resolver_pendencia_antiga_nao_esbarra_no_piso_da_data(cliente, db, escola_completa):
    """O piso é para data DIGITADA. A pendência de revisão guarda a data da
    importação original (registro do servidor): resolvê-la depois que a escola
    avançou o ano letivo não pode virar "a data do relatório parece errada"."""
    from app.models import RevisaoIdentidade

    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    rev = RevisaoIdentidade(
        escola_id=escola.id, chave="matific|id:U-ANTIGA|resumo||",
        chave_identidade="matific|id:U-ANTIGA", plataforma="matific", formato="resumo",
        id_externo="U-ANTIGA", nome_recebido="ANA B", turma_informada="3º Ano A",
        motivo="nome_casa_em_outra_sala", candidatos=[],
        linhas=[{"matific_uuid": "U-ANTIGA", "atividades": 30, "estrelas": 120,
                 "pontuacao_media": 4.0}],
        contexto={"tipo": "texto", "periodo_inicio": "", "periodo_fim": "",
                  "data_referencia": "2024-06-10T12:00:00+00:00", "data_informada": True},
        origem="importacao", status="pendente")
    db.add(rev)
    db.commit()

    r = cliente.post(API.format(escola.id).replace("/confirmar", f"/revisoes/{rev.id}/resolver"),
                     json={"aluno_id": ana.id})

    assert r.status_code == 200, r.text
    (snap,) = _snaps(db, SnapshotMatific, ana.id)
    assert (snap.atividades, snap.estrelas) == (30, 120)
    assert snap.data_referencia.date().isoformat() == "2024-06-10"


# --- Resíduos da revisão final: datas legadas fora do calendário ------------------

def _retrato_legado_do_ano_1(db, escola, admin, aluno, plataforma: str, hora: int) -> None:
    """Retrato gravado por um upload manual ANTIGO (o servidor aceitava qualquer data)
    em 0001-01-01, na hora UTC pedida: até as 02h59 ainda é o "ano 0" em Brasília
    (fora do calendário); das 03h em diante, o dia 0001-01-01 de Brasília."""
    legado = Importacao(escola_id=escola.id, usuario_id=admin.id, plataforma=plataforma,
                        tipo="pdf", status="concluida")
    db.add(legado)
    db.flush()
    quando = datetime(1, 1, 1, hora, 0, 0)
    if plataforma == "matific":
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id, importacao_id=legado.id,
                               data_referencia=quando, atividades=5, estrelas=5,
                               pontuacao_media=1.0))
    else:
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id, importacao_id=legado.id,
                                data_referencia=quando, livros_unicos=3, tempo_leitura_min=5,
                                questoes_tentativas=1, questoes_acertos=1,
                                livros_por_nivel={"AA": 3}))
    db.commit()


def _resumo_sem_data(plataforma: str, aluno) -> dict:
    if plataforma == "matific":
        return _matific(aluno, {"atividades": 20, "estrelas": 100, "pontuacao_media": 2.0})
    return {"plataforma": "elefante", "formato": "resumo", "tipo": "pdf",
            "linhas": [{"nome": aluno.nome, "aluno_id": aluno.id,
                        "dados": {"livros_unicos": 12, "tempo_leitura_min": 90,
                                  "questoes_tentativas": 4, "questoes_acertos": 3}}]}


@pytest.mark.parametrize("hora", [0, 3, 12, 23])
@pytest.mark.parametrize("plataforma", ["elefante", "matific"])
def test_upload_sem_data_com_retrato_legado_do_ano_1_nao_da_500(cliente, db, escola_completa,
                                                                 plataforma, hora):
    """PoC p1: das 03h UTC em diante, o início do dia do retrato legado é 0001-01-01
    03h UTC, e a regra D tirava dele a janela da execução (12 h): OverflowError, 500
    no upload manual SEM data. Agora o filtro para no início do calendário; sem
    sincronização nenhuma, o arquivo vira o retrato de hoje e o legado fica como
    estava."""
    escola, admin = escola_completa["escola"], escola_completa["admin"]
    ana = escola_completa["alunos"][0]
    _retrato_legado_do_ano_1(db, escola, admin, ana, plataforma, hora)

    r = _post(cliente, escola.id, _resumo_sem_data(plataforma, ana))

    assert r.status_code == 200, r.text
    modelo = SnapshotMatific if plataforma == "matific" else SnapshotElefante
    antigo, hoje = _snaps(db, modelo, ana.id)
    assert antigo.data_referencia == datetime(1, 1, 1, hora)
    assert abs(hoje.data_referencia - _agora()) < timedelta(minutes=5)
    if plataforma == "matific":
        assert (hoje.atividades, hoje.estrelas) == (20, 100)
    else:
        assert hoje.livros_unicos == 12


@pytest.mark.parametrize("hora", [3, 12])
def test_retrato_do_ano_1_continua_anterior_a_sincronizacao_na_regra_d(cliente, db,
                                                                      escola_completa, hora):
    """O limite no início do calendário não tira o aluno da regra D: o retrato de
    0001-01-01 é ANTERIOR à sincronização de 3 dias atrás, e o upload sem data pede a
    data (como para qualquer retrato anterior à última sincronização), sem 500."""
    escola, admin = escola_completa["escola"], escola_completa["admin"]
    ana = escola_completa["alunos"][0]
    _retrato_legado_do_ano_1(db, escola, admin, ana, "matific", hora)
    inicio = _agora() - timedelta(days=3)
    db.add(SincronizacaoExecucao(escola_id=escola.id, plataforma="matific", origem="manual",
                                 status="concluida", iniciada_em=inicio,
                                 finalizada_em=inicio + timedelta(minutes=5)))
    db.commit()

    r = _post(cliente, escola.id, _resumo_sem_data("matific", ana))

    assert r.status_code == 422, r.text
    assert "Informe a data do relatório" in r.json()["detail"]
    assert [s.data_referencia for s in _snaps(db, SnapshotMatific, ana.id)] == [
        datetime(1, 1, 1, hora)]


@pytest.mark.parametrize("data,status_final", [
    ("0001-01-01T00:00:00+00:00", "pendente"),     # ano 0 em Brasília
    ("0001-01-01T00:00:00+03:00", "pendente"),     # idem, com fuso positivo
    ("2025-09-22T10:00:00+00:00", "resolvida"),    # controle: data normal encerra
])
def test_pendencia_legada_fora_do_calendario_nao_derruba_a_sincronizacao(
        db, oficial_e_stub, monkeypatch, data, status_final):  # noqa: F811
    """PoC p2: a linha da sync casa com a identidade de uma pendência LEGADA de
    resumo cuja data congelada é do ano 1. ``_linha_substitui_o_congelado`` chamava
    ``para_br`` direto: OverflowError, e a sincronização do Elefante caía para a
    escola INTEIRA. Agora a data absurda não é "tão nova quanto" nada: a pendência
    fica para o gestor, e a coleta segue (a ficha oficial recebe o retrato)."""
    c = oficial_e_stub
    rev = _pendencia(db, c["escola"], chave_ident=CHAVE_GIOVANA, formato="resumo",
                     id_externo=str(SID_GIOVANA), nome=NOME_ELEFANTE_GIOVANA,
                     candidatos=(c["oficial"], c["stub"]), data_referencia=data,
                     linhas=[{"turma_relatorio": SALA, "livros_unicos": 3,
                              "elefante_student_id": str(SID_GIOVANA)}])
    rid, oficial_id = rev.id, c["oficial"].id

    res = _sincronizar_elefante(db, c["escola"], monkeypatch,
                                [(SID_GIOVANA, NOME_ELEFANTE_GIOVANA)])

    assert res["qtd_alunos"] == 1
    db.expire_all()
    assert db.get(RevisaoIdentidade, rid).status == status_final
    assert [s.livros_unicos for s in _snaps(db, SnapshotElefante, oficial_id)] == [9]


def _pendencia_matific(db, escola, *, data: str, conta: str = "U-LEGADA",
                       periodo: tuple[str, str] = ("", "")) -> int:
    rev = RevisaoIdentidade(
        escola_id=escola.id, chave=f"matific|id:{conta}|resumo||",
        chave_identidade=f"matific|id:{conta}", plataforma="matific", formato="resumo",
        id_externo=conta, nome_recebido="ANA B", turma_informada="3º Ano A",
        motivo="nome_casa_em_outra_sala", candidatos=[],
        linhas=[{"matific_uuid": conta, "atividades": 30, "estrelas": 120,
                 "pontuacao_media": 4.0}],
        contexto={"tipo": "texto", "periodo_inicio": periodo[0], "periodo_fim": periodo[1],
                  "data_referencia": data, "data_informada": True},
        origem="importacao", status="pendente")
    db.add(rev)
    db.commit()
    return rev.id


def _resolver(cliente, escola_id: int, rid: int, aluno_id: int):
    return cliente.post(API.format(escola_id).replace("/confirmar", f"/revisoes/{rid}/resolver"),
                        json={"aluno_id": aluno_id})


@pytest.mark.parametrize("data", ["0001-01-01T00:00:00+03:00", "0001-01-01T02:00:00",
                                  "9999-12-31T23:00:00-03:00"])
@pytest.mark.parametrize("com_retrato", [True, False])
def test_resolver_pendencia_legada_fora_do_calendario_aplica_so_o_vinculo(
        cliente, db, escola_completa, monkeypatch, com_retrato, data):
    """O mesmo dado legado no /resolver. Com retrato gravado, ``_retrato_superado``
    estourava ao converter a data congelada com fuso (OverflowError, 500); sem
    retrato, o pipeline recusava a data (422) e a pendência nunca saía da fila. Agora
    vale só o vínculo, com aviso, e nenhum retrato nasce da data absurda."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    if com_retrato:
        _sync_matific(db, escola, monkeypatch, atividades=50, estrelas=300)
    rid = _pendencia_matific(db, escola, data=data)

    r = _resolver(cliente, escola.id, rid, ana.id)

    assert r.status_code == 200, r.text
    assert any("data fora do calendário" in a for a in r.json()["avisos"])
    db.expire_all()
    rev = db.get(RevisaoIdentidade, rid)
    assert rev.status == "resolvida"
    assert rev.resolucao["dados_superados"]["motivo"] == "data_referencia_fora_do_calendario"
    assert [(s.atividades, s.estrelas) for s in _snaps(db, SnapshotMatific, ana.id)] == (
        [(50, 300)] if com_retrato else [])
    assert db.execute(select(IdentidadeExterna.aluno_id).where(
        IdentidadeExterna.id_externo == "U-LEGADA")).scalar_one() == ana.id


@pytest.mark.parametrize("inicio,fim", [("0001-01-01T00:00:00", "2026-10-01T00:00:00"),
                                        ("2026-09-01T00:00:00", "0001-01-01T00:00:00")])
def test_resolver_pendencia_com_intervalo_do_matific_no_ano_1_da_422_e_nao_500(
        cliente, db, escola_completa, inicio, fim):
    """O /resolver não aplica o piso da data (a pendência é registro do servidor),
    mas o intervalo do Matific no ano 1 datava o retrato-base na véspera do início
    (ou o fim impresso, 1 s antes): OverflowError, 500. Agora só esse dia sem véspera
    é recusado, com 422; a pendência continua pendente e nada é gravado."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    rid = _pendencia_matific(db, escola, data="2026-10-01T00:00:00+00:00",
                             periodo=(inicio, fim))

    r = _resolver(cliente, escola.id, rid, ana.id)

    assert r.status_code == 422, r.text
    assert "01/01/0001 está fora do calendário" in r.json()["detail"]
    db.expire_all()
    assert db.get(RevisaoIdentidade, rid).status == "pendente"
    assert _snaps(db, SnapshotMatific, ana.id) == []
