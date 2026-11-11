"""A "semana atual" da Persistência (Insights/Dashboard/Assistente) é a semana de
BRASÍLIA, não a do relógio UTC.

`insights.indices_da_escola` recortava a semana pela segunda 00:00 da semana ISO
em UTC e a comparava com `Leitura.data`, que é horário de PAREDE de Brasília
(`sync/fuso.py`). No domingo depois das 21h (BRT) o UTC já é segunda: a "semana
atual" começava amanhã, as leituras da semana sumiam e a persistência de todos
caía a 0 — duas horas antes, com os mesmos dados, era 100. Achado PERIODOS-11.

O relógio é fixado trocando o `datetime` dos módulos (como na sonda do
auditor). Dados fictícios.
"""
import datetime as _dt

from app.models import Leitura, Livro
from app.services import evolucao as svc_evolucao
from app.services import insights


def _relogio(agora_iso: str):
    alvo = _dt.datetime.fromisoformat(agora_iso)

    class _Relogio(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is not None:
                return alvo.astimezone(tz)
            return alvo.astimezone(_dt.timezone.utc).replace(tzinfo=None)
    return _Relogio


def _persistencia(db, escola_id, monkeypatch, agora_iso):
    relogio = _relogio(agora_iso)
    monkeypatch.setattr(insights, "datetime", relogio)
    monkeypatch.setattr(svc_evolucao, "datetime", relogio)
    return {i["aluno_id"]: i["persistencia"]
            for i in insights.indices_da_escola(db, escola_id)}


def _leituras(db, escola, leituras):
    for i, (aluno, quando) in enumerate(leituras):
        livro = Livro(escola_id=escola.id, titulo=f"Livro Fictício {i}", nivel_codigo="D")
        db.add(livro)
        db.flush()
        db.add(Leitura(escola_id=escola.id, aluno_id=aluno.id, livro_id=livro.id,
                       data=quando, tempo_leitura_min=15))
    db.commit()


def test_persistencia_nao_zera_no_domingo_a_noite(db, escola_completa, monkeypatch):
    escola = escola_completa["escola"]
    ana, joao = escola_completa["alunos"][0], escola_completa["alunos"][1]
    # Semana de Brasília: segunda 28/09 a domingo 04/10/2026.
    _leituras(db, escola, [
        (ana, _dt.datetime(2026, 10, 4, 10, 0)),    # domingo de manhã (esta semana)
        (ana, _dt.datetime(2026, 9, 15, 10, 0)),    # semanas antes (o ritmo dela)
        (joao, _dt.datetime(2026, 9, 16, 10, 0)),   # só semanas antes
    ])
    as_20h = _persistencia(db, escola.id, monkeypatch, "2026-10-04T20:00:00-03:00")
    as_22h = _persistencia(db, escola.id, monkeypatch, "2026-10-04T22:00:00-03:00")
    as_23h59 = _persistencia(db, escola.id, monkeypatch, "2026-10-04T23:59:00-03:00")
    assert as_20h[ana.id] > 0
    assert as_22h[ana.id] == as_20h[ana.id], (
        f"domingo 20h BRT: {as_20h[ana.id]} × domingo 22h BRT: {as_22h[ana.id]}")
    assert as_23h59[ana.id] == as_20h[ana.id]
    assert as_20h[joao.id] == as_22h[joao.id] == 0.0


def test_a_semana_vira_a_meia_noite_de_brasilia(db, escola_completa, monkeypatch):
    """A leitura de domingo deixa de ser "desta semana" à meia-noite de Brasília
    (segunda 00h BRT = 03h UTC), não às 21h de domingo."""
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    _leituras(db, escola, [
        (ana, _dt.datetime(2026, 10, 4, 10, 0)),
        (ana, _dt.datetime(2026, 9, 15, 10, 0)),
    ])
    domingo = _persistencia(db, escola.id, monkeypatch, "2026-10-04T21:30:00-03:00")
    segunda = _persistencia(db, escola.id, monkeypatch, "2026-10-05T00:30:00-03:00")
    assert domingo[ana.id] > 0, "domingo 21h30 (BRT) ainda é a semana da leitura"
    assert segunda[ana.id] == 0.0, "segunda 00h30 (BRT) já é outra semana"
