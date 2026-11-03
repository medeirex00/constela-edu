"""O "mesmo dia" que torna a reimportação idempotente é o dia de BRASÍLIA.

``importacoes._mesmo_dia`` comparava a data UTC crua (residual do e93 §3.1, A2
§3.12): das 21h à meia-noite (BRT) o UTC já é o dia seguinte, então a coleta das
22h e a da manhã seguinte colapsavam num retrato só — o valor da noite sumia do
histórico — e a das 20h e a das 22h do mesmo dia viravam dois. Dados fictícios.
"""
from datetime import datetime, timedelta, timezone

from app.models import SnapshotElefante, SnapshotMatific
from app.routers import importacoes as imp

BRT = timezone(timedelta(hours=-3))


def test_mesmo_dia_compara_a_data_de_brasilia():
    # 20h e 22h de 22/10 em Brasília (23:00 e 01:00 UTC: datas UTC diferentes)
    assert imp._mesmo_dia(datetime(2026, 10, 22, 23, 0), datetime(2026, 10, 23, 1, 0))
    # 22h de 22/10 e 09h de 23/10 em Brasília (as duas em 23/10 UTC)
    assert not imp._mesmo_dia(datetime(2026, 10, 23, 1, 0), datetime(2026, 10, 23, 12, 0))
    # com fuso: convertido (não só "tirado"); naive = UTC
    assert imp._mesmo_dia(datetime(2026, 10, 22, 22, 0, tzinfo=BRT), datetime(2026, 10, 23, 1, 0))
    assert imp._mesmo_dia(datetime(2026, 10, 23, 1, 0, tzinfo=timezone.utc),
                          datetime(2026, 10, 22, 12, 0, tzinfo=BRT))
    assert not imp._mesmo_dia(None, datetime(2026, 10, 23))


def _confirmar(cliente, escola_id, ana, quando, plataforma, dados):
    r = cliente.post(
        f"/api/v1/escolas/{escola_id}/importacoes/confirmar",
        json={"plataforma": plataforma, "formato": "resumo", "tipo": "texto",
              "data_referencia": quando,
              "linhas": [{"nome": ana.nome, "aluno_id": ana.id, "dados": dados}]})
    assert r.status_code == 200, r.text


def _serie(db, modelo, aluno_id):
    db.expire_all()
    return [(s.data_referencia.replace(tzinfo=None), s)
            for s in db.query(modelo).filter_by(aluno_id=aluno_id)
            .order_by(modelo.data_referencia, modelo.id).all()]


def test_coleta_da_noite_e_da_manha_seguinte_sao_dois_retratos(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    mt = {"atividades": 10, "estrelas": 40, "pontuacao_media": 80.0}
    _confirmar(cliente, escola_id, ana, "2026-10-23T01:00:00Z", "matific", mt)   # 22h BRT 22/10
    _confirmar(cliente, escola_id, ana, "2026-10-23T12:00:00Z", "matific",       # 09h BRT 23/10
               {**mt, "estrelas": 55})
    serie = _serie(db, SnapshotMatific, ana.id)
    assert [(d, s.estrelas) for d, s in serie] == [
        (datetime(2026, 10, 23, 1, 0), 40),      # o retrato da noite fica no histórico
        (datetime(2026, 10, 23, 12, 0), 55)]

    el = {"livros_unicos": 3, "tempo_leitura_min": 30}
    _confirmar(cliente, escola_id, ana, "2026-10-23T01:00:00Z", "elefante", el)
    _confirmar(cliente, escola_id, ana, "2026-10-23T12:00:00Z", "elefante",
               {**el, "livros_unicos": 4})
    assert [s.livros_unicos for _d, s in _serie(db, SnapshotElefante, ana.id)] == [3, 4]


def test_coletas_das_20h_e_das_22h_do_mesmo_dia_sao_um_retrato(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    mt = {"atividades": 10, "estrelas": 40, "pontuacao_media": 80.0}
    _confirmar(cliente, escola_id, ana, "2026-10-22T23:00:00Z", "matific", mt)   # 20h BRT 22/10
    _confirmar(cliente, escola_id, ana, "2026-10-23T01:00:00Z", "matific",       # 22h BRT 22/10
               {**mt, "estrelas": 47})
    serie = _serie(db, SnapshotMatific, ana.id)
    assert len(serie) == 1                                   # um ponto no dia de Brasília
    data, snap = serie[0]
    assert snap.estrelas == 47 and data == datetime(2026, 10, 23, 1, 0)   # a data acompanha

    el = {"livros_unicos": 3, "tempo_leitura_min": 30}
    _confirmar(cliente, escola_id, ana, "2026-10-22T23:00:00Z", "elefante", el)
    _confirmar(cliente, escola_id, ana, "2026-10-23T01:00:00Z", "elefante",
               {**el, "livros_unicos": 5})
    assert [s.livros_unicos for _d, s in _serie(db, SnapshotElefante, ana.id)] == [5]


# --- Resíduo do e97 (marco 2, §3): ORDEM de instantes com fuso -------------------
# ``_avancar_data`` e ``_retrato_superado`` comparavam instantes com ``_sem_fuso``, que
# só TIRA o fuso: "14h -03:00" (17h UTC) virava "14h" e perdia para "16h" UTC. Agora
# os dois instantes são convertidos (naive = UTC; com fuso → UTC) antes de comparar;
# o critério de DIA continua o de Brasília (``_mesmo_dia``).

def test_instante_utc_converte_em_vez_de_cortar():
    assert imp._instante_utc(datetime(2026, 10, 23, 14, 0, tzinfo=BRT)) == \
        datetime(2026, 10, 23, 17, 0)
    assert imp._instante_utc(datetime(2026, 10, 23, 17, 0, tzinfo=timezone.utc)) == \
        datetime(2026, 10, 23, 17, 0)
    assert imp._instante_utc(datetime(2026, 10, 23, 16, 0)) == datetime(2026, 10, 23, 16, 0)


def test_avancar_data_com_fuso_de_brasilia_avanca_pelo_instante():
    from types import SimpleNamespace

    # gravado às 16h UTC (13h BRT); o valor novo é das 14h BRT (17h UTC): AVANÇA
    snap = SimpleNamespace(data_referencia=datetime(2026, 10, 23, 16, 0))
    novo = datetime(2026, 10, 23, 14, 0, tzinfo=BRT)
    imp._avancar_data(snap, novo)
    assert snap.data_referencia is novo                  # antes: 14h < 16h, ficava

    # o valor novo é das 12h BRT (15h UTC), anterior às 16h UTC: não recua
    snap = SimpleNamespace(data_referencia=datetime(2026, 10, 23, 16, 0))
    imp._avancar_data(snap, datetime(2026, 10, 23, 12, 0, tzinfo=BRT))
    assert snap.data_referencia == datetime(2026, 10, 23, 16, 0)

    # gravado com fuso (14h BRT = 17h UTC) e o novo naive das 16h UTC: NUNCA recua
    # (antes, 14h < 16h e a data voltava uma hora)
    gravada = datetime(2026, 10, 23, 14, 0, tzinfo=BRT)
    snap = SimpleNamespace(data_referencia=gravada)
    imp._avancar_data(snap, datetime(2026, 10, 23, 16, 0))
    assert snap.data_referencia is gravada


def _pendencia_de_retrato(data_congelada: str):
    from types import SimpleNamespace

    return SimpleNamespace(formato="resumo", plataforma="matific",
                           contexto={"data_referencia": data_congelada})


def test_retrato_superado_compara_o_instante_da_data_congelada_com_fuso(cliente, db,
                                                                       escola_completa):
    """Retrato gravado às 02h UTC de 24/10 (23h de 23/10 em Brasília). A pendência
    guardou o retrato das 01h de 24/10 -03:00 (04h UTC; dia 24 em Brasília): é o MAIS
    NOVO e de OUTRO dia — o /resolver deve aplicá-lo. Cortando o fuso ele virava
    "01h UTC" (22h de 23/10 em Brasília) e era descartado como do mesmo dia."""
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    _confirmar(cliente, escola_id, ana, "2026-10-24T02:00:00Z", "matific",
               {"atividades": 10, "estrelas": 40, "pontuacao_media": 80.0})
    db.expire_all()

    rev = _pendencia_de_retrato("2026-10-24T01:00:00-03:00")
    assert imp._retrato_superado(db, escola_id, ana.id, rev) is None

    # o mesmo instante sem fuso (UTC) dá o mesmo juízo
    assert imp._retrato_superado(db, escola_id, ana.id,
                                 _pendencia_de_retrato("2026-10-24T04:00:00")) is None
    # 23h30 de 23/10 em Brasília (02h30 UTC de 24/10): mesmo dia do gravado
    assert imp._retrato_superado(db, escola_id, ana.id, _pendencia_de_retrato(
        "2026-10-23T23:30:00-03:00"))["motivo"] == "mesmo_dia_do_snapshot_atual"
    # 21h de 22/10 em Brasília (00h UTC de 23/10): o gravado é mais recente
    assert imp._retrato_superado(db, escola_id, ana.id, _pendencia_de_retrato(
        "2026-10-22T21:00:00-03:00"))["motivo"] == "snapshot_mais_recente"


def test_retrato_superado_ordem_entre_dias_pelo_instante(cliente, db, escola_completa):
    """Gravado às 03h30 UTC de 24/10 (00h30 de 24/10 em Brasília); congelado às 02h de
    24/10 -03:00 (05h UTC): mesmo dia em Brasília. Cortando o fuso, "02h UTC" era 23h
    de 23/10 e o motivo saía 'snapshot_mais_recente' (dia e ordem errados)."""
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    _confirmar(cliente, escola_id, ana, "2026-10-24T03:30:00Z", "matific",
               {"atividades": 10, "estrelas": 40, "pontuacao_media": 80.0})
    db.expire_all()
    assert imp._retrato_superado(db, escola_id, ana.id, _pendencia_de_retrato(
        "2026-10-24T02:00:00-03:00"))["motivo"] == "mesmo_dia_do_snapshot_atual"
