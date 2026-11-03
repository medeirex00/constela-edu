"""Boot com o schema errado não liga o agendador de sincronização.

O ``app.main`` promete que, com o schema sabidamente errado no boot (migração
pendente ou banco adiante do código), o processo sobe com o readiness em 503 e NADA
é escrito no banco. Os ajustes de dados e a liberação de órfãs já respeitavam isso;
o agendador não (auditoria de 20/10): com ``SYNC_SCHEDULER_ENABLED=true``, a thread
subia mesmo assim e, durante a janela do healthcheck, rodava a rodada inteira
(agenda diária, fila, sync completa) com código que não casa com o schema.

Roda em PROCESSO SEPARADO: a decisão é tomada no import do ``app.main``. No SQLite o
cenário "o import não migrou" é montado trocando ``aplicar_migracoes`` por um no-op
(em produção é o ``ENV=producao`` que pula a migração; ver o teste PostgreSQL). A
rodada do agendador vira no-op: o que se mede é se a thread subiu.

E esse processo não pode ficar PRONTO depois (2ª revisão de 20/10): se a migração for
aplicada por fora com ele de pé, o readiness passava a 200 e o Railway trocava o
tráfego para um processo sem agendador, sem os ajustes de dados e sem liberar órfãs —
com o ``/status`` das escolas dizendo "agendador ativo". Agora fica 503
``reinicio_pendente`` até um boot novo.
"""
from __future__ import annotations

import json

import pytest

from tests._infra_comum import (  # noqa: F401 — fixtures
    BOOT,
    REV_FUTURA,
    ambiente,
    assinatura,
    heads_do_codigo,
    levar_a,
    marcar_versao,
    pg_url,
    revisao_anterior_a_head,
    rodar,
    sqlite_url,
)

IMPORTAR_E_VER_AGENDADOR = BOOT + (
    "import json\n"
    "if os.environ.get('TESTE_IMPORT_SEM_MIGRAR'):\n"
    "    import app.core.migracoes as _m\n"
    "    _m.aplicar_migracoes = lambda engine: None\n"
    "import app.sync.scheduler as _s\n"
    "_s._uma_rodada = lambda: None\n"
    "import app.main as _main\n"
    "print('RESULTADO=' + json.dumps({'ativo': _s.ativo(),\n"
    "                                 'motivo': _main._motivo_boot}))\n"
    "_s.parar()\n"
)


#: Desde os pré-requisitos do agendador (P3, ``app/sync/prerequisitos.py``), ligado
#: pela variável ele só sobe com os críticos ok — e nesta base eles falham de
#: propósito (sem teto, sem status honesto). Aqui o que se mede é a trava do SCHEMA,
#: então o boot vai FORÇADO: o controle (banco em dia) continua provando que a thread
#: sobe, e os casos de schema errado provam também que forçar NÃO fura essa trava.
FORCADO = {"SYNC_SCHEDULER_FORCAR": "true"}


def _subir(url: str, producao: bool, **extra) -> dict:
    p = rodar(IMPORTAR_E_VER_AGENDADOR,
              ambiente(url, producao, SYNC_SCHEDULER_ENABLED="true", **FORCADO, **extra))
    linhas = [x for x in p.stdout.splitlines() if x.startswith("RESULTADO=")]
    assert p.returncode == 0 and linhas, (
        f"saída {p.returncode}\n{p.stdout[-3000:]}\n{p.stderr[-3000:]}")
    resultado = json.loads(linhas[-1][len("RESULTADO="):])
    resultado["_log"] = p.stdout + p.stderr
    return resultado


def test_banco_atras_no_boot_nao_liga_o_agendador(sqlite_url):
    levar_a(sqlite_url, revisao_anterior_a_head())
    antes = assinatura(sqlite_url)
    r = _subir(sqlite_url, producao=False, TESTE_IMPORT_SEM_MIGRAR="1")
    assert r["motivo"] == "migracao_pendente"
    assert r["ativo"] is False
    assert "agendador" in r["_log"].lower()          # o motivo fica registrado no log
    assert assinatura(sqlite_url) == antes


def test_banco_em_dia_liga_o_agendador_quando_habilitado(sqlite_url):
    """Controle: com o schema certo, o mesmo boot liga a thread (o teste acima não
    passa só porque o agendador nunca sobe neste ambiente)."""
    levar_a(sqlite_url, "heads")
    r = _subir(sqlite_url, producao=False, TESTE_IMPORT_SEM_MIGRAR="1")
    assert r["motivo"] == "em_dia"
    assert r["ativo"] is True


# O boot com o banco atrás; com o processo DE PÉ, a migração é aplicada por fora (outro
# engine, como o `scripts.migrate` da máquina do dono) e o readiness é sondado de novo.
BOOT_ATRAS_DEPOIS_MIGRAR_POR_FORA = BOOT + (
    "import json\n"
    "import app.core.migracoes as _m\n"
    "_migrar_de_verdade = _m.aplicar_migracoes\n"
    "_m.aplicar_migracoes = lambda engine: None\n"
    "import app.sync.scheduler as _s\n"
    "_s._uma_rodada = lambda: None\n"
    "from fastapi.testclient import TestClient\n"
    "from sqlalchemy import create_engine\n"
    "import app.main as _main\n"
    "c = TestClient(_main.app, raise_server_exceptions=False)\n"
    "antes = c.get('/api/health/ready')\n"
    "por_fora = create_engine(os.environ['DATABASE_URL'])\n"
    "_migrar_de_verdade(por_fora)\n"
    "por_fora.dispose()\n"
    "depois = [c.get('/api/health/ready') for _ in range(3)]\n"
    "print('RESULTADO=' + json.dumps({\n"
    "    'motivo': _main._motivo_boot, 'ativo': _s.ativo(),\n"
    "    'antes': [antes.status_code, antes.json()],\n"
    "    'depois': [[r.status_code, r.json()] for r in depois],\n"
    "    'live': c.get('/api/health/live').status_code}))\n"
    "_s.parar()\n"
)


def test_boot_com_banco_atras_nao_fica_pronto_mesmo_depois_de_migrar_por_fora(sqlite_url):
    levar_a(sqlite_url, revisao_anterior_a_head())
    p = rodar(BOOT_ATRAS_DEPOIS_MIGRAR_POR_FORA,
              ambiente(sqlite_url, False, SYNC_SCHEDULER_ENABLED="true", **FORCADO))
    linhas = [x for x in p.stdout.splitlines() if x.startswith("RESULTADO=")]
    assert p.returncode == 0 and linhas, (
        f"saída {p.returncode}\n{p.stdout[-3000:]}\n{p.stderr[-3000:]}")
    r = json.loads(linhas[-1][len("RESULTADO="):])
    log = p.stdout + p.stderr

    assert r["motivo"] == "migracao_pendente"
    assert r["antes"] == [503, {"status": "degradado", "banco": "ok",
                                "motivo": "migracao_pendente"}]
    # Controle: a migração por fora deixou o banco em dia...
    assert assinatura(sqlite_url)["versao"] == heads_do_codigo()
    # ...mas o processo segue sem agendador e, por isso, NÃO fica pronto.
    assert r["ativo"] is False
    for status, corpo in r["depois"]:
        assert status == 503
        assert corpo == {"status": "degradado", "banco": "ok", "motivo": "reinicio_pendente"}
    assert r["live"] == 200                    # vivo: o orquestrador não reinicia em laço
    # O motivo fica no log, uma vez só (a sonda repete; o log não).
    avisos = [x for x in log.splitlines() if "REINICIE" in x]
    assert len(avisos) == 1, log[-3000:]
    assert "migracao_pendente" in avisos[0] and "agendador" in avisos[0]


@pytest.mark.postgres
def test_producao_com_banco_atras_nao_liga_o_agendador_nem_escreve(pg_url):
    levar_a(pg_url, revisao_anterior_a_head())
    antes = assinatura(pg_url)
    r = _subir(pg_url, producao=True)
    assert r["motivo"] == "migracao_pendente" and r["ativo"] is False
    assert assinatura(pg_url) == antes


@pytest.mark.postgres
def test_producao_com_banco_adiante_nao_liga_o_agendador(pg_url):
    """Rollback de imagem sobre schema mais novo: o código velho não roda a fila."""
    levar_a(pg_url, "heads")
    marcar_versao(pg_url, REV_FUTURA)
    antes = assinatura(pg_url)
    r = _subir(pg_url, producao=True)
    assert r["motivo"] == "schema_adiante" and r["ativo"] is False
    assert assinatura(pg_url) == antes
