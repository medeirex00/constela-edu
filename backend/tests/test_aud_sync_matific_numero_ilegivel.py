"""Matific: número ILEGÍVEL no Placar (a chave veio, o valor não é número) não
vira 0.

O mesmo parser (``ConectorMatific._parse_school_student``) serve a coleta do
acumulado, a coleta por período e o placar ao vivo da premiação. Antes, só a
CHAVE ausente entrava em ``ausentes``; o valor ilegível ('N/A', objeto, null)
virava 0 em ``_para_int`` e as guardas da importação ("ausente/ilegível NÃO vira
0") e do placar ao vivo recebiam um zero legítimo: retrato 0/0 gravado com a
coleta 'concluida', ganhos do período zerados e pódio com 0.

Decisão documentada: ``score``/``activities_completed`` são texto numérico na API
(docs/MATIFIC_API.md, não anuláveis); ``null`` também é ilegível — vai nulo,
nunca 0. Dados fictícios; conector real com navegador falso.
"""
import pytest
from sqlalchemy import func, select

from app.models.plataformas import SnapshotMatific
from app.models.sincronizacao import SincronizacaoAlerta
from app.sync import aovivo
from app.sync.connectors.matific import ConectorMatific
from app.sync.interfaces import ErroConector
from tests._sync_nucleo_fakes import (
    PlacarFake, alertas_abertos, credencial, instalar, rodar, snap_atual)

K = "3 ANO A (300396804)"
P_SET = {"matific_start_date": "2026-09-01", "matific_end_date": "2026-09-30"}


def _formato_novo(placar, embrulho):
    """O Placar passa a mandar os números de outro jeito (a chave continua lá)."""
    original = placar.school_student

    def _novo(expr):
        res = original(expr)
        for item in res["body"][0]["data"]:
            if item.get("uuid"):
                item["score"] = embrulho(item["score"])
                item["activities_completed"] = embrulho(item["activities_completed"])
        return res
    placar.school_student = _novo


def _severidades(db, eid):
    return {al.tipo: al.severidade for al in db.execute(select(SincronizacaoAlerta).where(
        SincronizacaoAlerta.escola_id == eid, SincronizacaoAlerta.resolvido.is_(False))).scalars()}


def _retratos(db, eid):
    return db.scalar(select(func.count()).select_from(SnapshotMatific).where(
        SnapshotMatific.escola_id == eid))


def test_numero_ilegivel_nao_grava_retrato_zero_no_acumulado(db, escola_completa, monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    a, b, c = ec["alunos"]
    credencial(db, eid, "matific")
    placar = PlacarFake()
    placar.linhas = [("u-a", a.nome, K, 40, 10), ("u-b", b.nome, K, 30, 8)]
    instalar(monkeypatch, placar=placar)
    ex1, _ = rodar(db, eid, "matific")
    assert ex1.status == "concluida"

    # Formato novo: os números vêm como objeto. Entra também uma criança que ainda
    # não tinha conta vinculada (1º encontro, sem retrato no ano).
    placar.linhas.append(("u-c", c.nome, K, 25, 6))
    _formato_novo(placar, lambda v: {"valor": v})
    ex2, _ = rodar(db, eid, "matific")
    sev = _severidades(db, eid)
    snap_c = snap_atual(db, SnapshotMatific, c.id)
    assert snap_c is None or (snap_c.estrelas, snap_c.atividades) != (0, 0), (
        f"número ilegível do Placar virou ZERO no retrato da criança C ({ex2.status})")
    assert sev.get("parser_incompativel") == "critico", (
        f"formato novo dos números não abriu o alerta de formato: {sev}")
    assert ex2.status != "concluida"
    # As contas já vinculadas não ficam "retidas por queda" com o diagnóstico errado.
    assert "queda_matific" not in sev, sev
    sa = snap_atual(db, SnapshotMatific, a.id)
    assert (sa.estrelas, sa.atividades) == (40, 10)


def test_numero_ilegivel_nao_zera_os_ganhos_do_periodo(db, escola_completa, monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    a, b, _c = ec["alunos"]
    credencial(db, eid, "matific")
    placar = PlacarFake()
    placar.linhas = [("u-a", a.nome, K, 12, 4), ("u-b", b.nome, K, 9, 3)]
    _formato_novo(placar, lambda v: "N/A")
    instalar(monkeypatch, placar=placar)
    antes = _retratos(db, eid)
    rodar(db, eid, "matific", parametros=P_SET)
    assert _retratos(db, eid) == antes, "a coleta do período gravou retrato com 0"
    assert "parser_incompativel" in alertas_abertos(db, eid, "matific")


@pytest.mark.parametrize("ilegivel", [{"valor": 3914}, "N/A", None, True, "nan", [1], ""])
def test_parser_marca_o_valor_ilegivel_como_ausente(ilegivel):
    res = {"body": [{"data": [{"account_id": "ANA B", "klassName": "3 ANO A", "uuid": "u-1",
                               "score": ilegivel, "activities_completed": "12"}]}]}
    [linha] = ConectorMatific._parse_school_student(res, {})
    assert linha.get("ausentes") == ["estrelas"], linha
    assert linha["atividades"] == 12


@pytest.mark.parametrize("legivel,esperado", [("0", 0), (0, 0), ("3914", 3914), (3914, 3914),
                                              ("3914.0", 3914), (" 12 ", 12), (7.0, 7)])
def test_parser_le_o_numero_valido(legivel, esperado):
    res = {"body": [{"data": [{"account_id": "ANA B", "klassName": "3 ANO A", "uuid": "u-1",
                               "score": legivel, "activities_completed": legivel}]}]}
    [linha] = ConectorMatific._parse_school_student(res, {})
    assert "ausentes" not in linha, linha
    assert (linha["estrelas"], linha["atividades"]) == (esperado, esperado)


def test_placar_ao_vivo_recusa_o_numero_ilegivel():
    """O placar ao vivo (premiação por período) recebe a mesma marca e recusa,
    em vez de montar o pódio com 0."""
    res = {"body": [{"data": [
        {"account_id": "ANA B", "klassName": "3 ANO A", "uuid": "u-1",
         "score": {"valor": 3914}, "activities_completed": "N/A"},
        {"account_id": "BIA C", "klassName": "3 ANO A", "uuid": "u-2",
         "score": "50", "activities_completed": "10"}]}]}
    alunos = ConectorMatific._parse_school_student(res, {})
    with pytest.raises(ErroConector) as exc:
        aovivo._recusar_linhas_sem_numeros(alunos)
    assert exc.value.codigo == "parser_incompativel"
