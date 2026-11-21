"""O seed da demonstração e do E2E vale em qualquer ano (achado TESTES-2).

O DEFEITO. ``scripts/seed.py`` fixava ``ANO_LETIVO = 2026`` para a escola, as turmas e
as matrículas, e o ``seed_demo`` gravava os retratos do Matific e do Elefante e as
leituras com a data de HOJE. As Premiações (período padrão da tela: ano letivo) e o
ranking de Matemática medem pela janela civil do ano letivo da escola. Semeado a partir
de 01/01/2027 00:00 UTC, tudo caía fora da janela: Premiações sem pódio, ranking de
Matemática vazio, e o E2E do CI ("Premiações: categorias com pódio e certificados do
pódio") reprovava — o job semeia do zero a cada execução.

A CORREÇÃO, provada aqui: o ano letivo do seed é o ano de hoje em Brasília, e os
retratos e leituras da demonstração são datados DENTRO do ano letivo da escola (nas
últimas horas de 31/12 em Brasília o relógio UTC já virou o ano; o retrato fica no fim
do ano letivo, e não fora dele).

Como: o ``seed_e2e.main()`` do Playwright roda num processo novo com o relógio
ADIANTADO (``datetime``/``date``/``time.time`` trocados antes de qualquer import do
app; o relógio continua andando a partir do instante pedido), num SQLite descartável;
o mesmo processo faz login da coordenação do seed e pede as URLs das telas por
``TestClient``. Dados fictícios do próprio seed.
"""
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]

PROGRAMA = r'''
import datetime as _m
import json
import os
import sys
import time as _t

_RD, _RDate = _m.datetime, _m.date
_ALVO = _RD.fromisoformat(sys.argv[1])
_DESLOC = _ALVO - _RD.now(_m.timezone.utc)
_time_real = _t.time


def _agora_utc():
    return _RD.now(_m.timezone.utc) + _DESLOC


class _MetaDate(type):
    def __instancecheck__(cls, obj):
        return isinstance(obj, _RDate)

    def __subclasscheck__(cls, sub):
        return issubclass(sub, _RDate)


class _MetaDatetime(_MetaDate):
    def __instancecheck__(cls, obj):
        return isinstance(obj, _RD)

    def __subclasscheck__(cls, sub):
        return issubclass(sub, _RD)


class DataFalsa(_RDate, metaclass=_MetaDate):
    @classmethod
    def today(cls):
        d = _agora_utc().date()
        return _RDate(d.year, d.month, d.day)


class InstanteFalso(_RD, metaclass=_MetaDatetime):
    @classmethod
    def now(cls, tz=None):
        a = _agora_utc()
        return a.replace(tzinfo=None) if tz is None else a.astimezone(tz)

    @classmethod
    def utcnow(cls):
        return _agora_utc().replace(tzinfo=None)

    @classmethod
    def today(cls):
        return cls.now()


_m.date = DataFalsa
_m.datetime = InstanteFalso
_t.time = lambda: _time_real() + _DESLOC.total_seconds()

import contextlib
import io

sys.path.insert(0, os.getcwd())
with contextlib.redirect_stdout(io.StringIO()):
    from scripts import seed_e2e
    seed_e2e.main()
    from fastapi.testclient import TestClient
    from app.main import app

    c = TestClient(app)
    r = c.post("/api/v1/auth/login", data={"username": "coord@constela.local",
                                           "password": os.environ["COORD_PASSWORD"]})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = "Bearer " + r.json()["access_token"]
    escola = c.get("/api/v1/escolas").json()[0]
    premiacoes = c.get(f"/api/v1/escolas/{escola['id']}/premiacoes"
                       "?periodo=ano_letivo&turnos=true")
    ranking = c.get(f"/api/v1/escolas/{escola['id']}/ranking/matematica")


def _podios(o):
    n = 0
    if isinstance(o, dict):
        if isinstance(o.get("podio"), list) and o["podio"]:
            n += 1
        for v in o.values():
            n += _podios(v)
    elif isinstance(o, list):
        for v in o:
            n += _podios(v)
    return n


print("RESULTADO=" + json.dumps({
    "agora_utc": _agora_utc().isoformat(timespec="minutes"),
    "ano_letivo": escola.get("ano_letivo_ativo"),
    "premiacoes_status": premiacoes.status_code,
    "podios_com_alunos": _podios(premiacoes.json()),
    "ranking_matematica_linhas": len(ranking.json()) if ranking.status_code == 200 else -1,
}))
'''


def _medir(instante: str, pasta: Path) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k not in ("TEST_DATABASE_URL_PG", "SENTRY_DSN")
           and not k.startswith(("RAILWAY", "SUPABASE"))}
    env.update(ENV="dev", DATABASE_URL=f"sqlite:///{(pasta / 'e2e_relogio.db').as_posix()}",
               SECRET_KEY=secrets.token_urlsafe(48), DOCS_HABILITADOS="false",
               ADMIN_INITIAL_PASSWORD="AdminInventada@" + secrets.token_hex(4),
               COORD_PASSWORD="CoordInventada@" + secrets.token_hex(4),
               PROF_PASSWORD="ProfInventada@" + secrets.token_hex(4),
               AUTOMACAO_VERIFICAR_NO_BOOT="false", SYNC_SCHEDULER_ENABLED="false",
               PYTHONIOENCODING="utf-8", PYTHONWARNINGS="ignore")
    p = subprocess.run([sys.executable, "-c", PROGRAMA, instante], cwd=BACKEND, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=600)
    linhas = [x for x in p.stdout.splitlines() if x.startswith("RESULTADO=")]
    assert p.returncode == 0 and linhas, f"{p.returncode}\n{p.stdout[-2000:]}\n{p.stderr[-3000:]}"
    return json.loads(linhas[-1][len("RESULTADO="):])


@pytest.mark.parametrize("instante, ano_letivo", [
    ("2027-01-01T00:30:00+00:00", 2026),   # 31/12 21h30 em Brasília: o UTC já virou o ano
    ("2027-01-01T03:30:00+00:00", 2027),   # 01/01 00h30 em Brasília
    ("2027-02-15T12:00:00+00:00", 2027),
])
def test_seed_do_e2e_tem_podio_e_ranking_depois_da_virada(tmp_path, instante, ano_letivo):
    medida = _medir(instante, tmp_path)

    assert medida["premiacoes_status"] == 200, medida
    assert medida["ano_letivo"] == ano_letivo, medida
    assert medida["podios_com_alunos"] > 0, medida
    assert medida["ranking_matematica_linhas"] > 0, medida
