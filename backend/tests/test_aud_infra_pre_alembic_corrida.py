"""Dois migradores num banco anterior ao Alembic: o 2º espera a vez e NÃO recarimba a base.

``aplicar_migracoes`` decidia "banco pré-Alembic" (tabela ``usuarios`` sem
``alembic_version``) ANTES de tomar a vez (advisory lock 4714). Dois processos subindo juntos
num banco desses (dois workers em modo dev, ou pre-deploy + entrypoint) decidiam os dois
"carimbar". O 1º carimbava a 0001 e subia até as heads; o 2º esperava a vez e, com a decisão
velha, carimbava a 0001 POR CIMA das heads e rodava a 0002 de novo: DuplicateTable e o boot
do 2º processo caía (BANCO-6). Agora a decisão é tomada DEPOIS de tomar a vez, na mesma
conexão: o 2º vê o banco já versionado e só confere que está em dia.

Cenário determinístico: este teste faz o papel do 1º migrador (segura a vez e migra na própria
conexão) enquanto ``aplicar_migracoes`` — o 2º — espera na fila da trava (``pg_locks``).
"""
from __future__ import annotations

import threading
import time

import pytest
from alembic import command
from sqlalchemy import create_engine, text

from app.core.migracoes import _REVISAO_BASE, _config_da_aplicacao, aplicar_migracoes
from tests._infra_comum import heads_do_codigo, levar_a, pg_url  # noqa: F401 — fixture


def _esperando_a_vez(motor) -> int:
    with motor.connect() as c:
        return c.execute(text(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND classid = 4714 "
            "AND objid = 0 AND NOT granted")).scalar()


@pytest.mark.postgres
def test_segundo_migrador_num_banco_pre_alembic_espera_e_nao_recarimba(pg_url):
    levar_a(pg_url, _REVISAO_BASE)
    motor = create_engine(pg_url)
    try:
        with motor.begin() as c:                     # schema da 0001, sem alembic_version
            c.execute(text("DROP TABLE alembic_version"))

        primeiro = motor.connect()
        primeiro.exec_driver_sql("SELECT pg_advisory_xact_lock(4714, 0)")   # a vez é dele
        resultado: dict = {}

        def segundo():
            outro = create_engine(pg_url)
            try:
                resultado["estado"] = aplicar_migracoes(outro)
            except Exception as erro:  # noqa: BLE001 — o teste mostra o erro
                resultado["erro"] = erro
            finally:
                outro.dispose()

        fio = threading.Thread(target=segundo, daemon=True)
        fio.start()
        try:
            prazo = time.monotonic() + 60
            while _esperando_a_vez(motor) == 0:
                assert fio.is_alive(), f"o 2º migrador não esperou a vez: {resultado}"
                assert time.monotonic() < prazo, "o 2º migrador não chegou à fila da trava"
                time.sleep(0.05)
            # o 1º faz o serviço inteiro: carimba a base e sobe até as heads
            cfg = _config_da_aplicacao()
            cfg.attributes["connection"] = primeiro
            command.stamp(cfg, _REVISAO_BASE)
            command.upgrade(cfg, "heads")
            primeiro.commit()                         # solta a vez
        finally:
            primeiro.close()
        fio.join(300)
        assert not fio.is_alive(), "o 2º migrador não terminou"
        assert "erro" not in resultado, f"o 2º migrador caiu: {resultado.get('erro')!r}"
        assert resultado["estado"].situacao == "em_dia"
        with motor.connect() as c:
            versao = sorted(c.execute(text("SELECT version_num FROM alembic_version")).scalars())
        assert versao == heads_do_codigo()
    finally:
        motor.dispose()
