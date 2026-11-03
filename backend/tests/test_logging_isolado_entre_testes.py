"""O logging que um teste estraga não passa para o seguinte (conftest.pytest_runtest_protocol).

``command.upgrade`` com ``migracoes._config()`` (a Config COM o alembic.ini) faz o
env.py rodar ``fileConfig(alembic.ini, disable_existing_loggers=False)``: os handlers da
raiz saem e entra um ``StreamHandler(sys.stderr)`` com o formato do .ini. Antes, isso
ficava pelo resto da sessão (em 28/10 transformou uma exceção de fim de sessão em
"--- Logging error ---"). Os dois testes abaixo rodam NESTA ordem (a do arquivo): o 1º
prova que o problema existe dentro do teste; o 2º, que o seguinte recebe tudo de volta.
"""
import logging

import pytest
from alembic import command
from sqlalchemy import create_engine

from app.core.migracoes import _REVISAO_BASE, _config

FORMATO_DO_INI = "%(levelname)-5.5s [%(name)s] %(message)s"     # [formatter_generic]
NOMES = ("alembic", "alembic.runtime.migration", "sqlalchemy", "sqlalchemy.engine",
         "constela", "uvicorn")
_ANTES: dict = {}


def _do_alembic_ini(handler) -> bool:
    return getattr(handler.formatter, "_fmt", None) == FORMATO_DO_INI


def _retrato(captura_do_pytest: type) -> dict:
    """O logging fora dos handlers de captura do pytest (trocados a cada fase)."""
    raiz = logging.getLogger()
    return {
        "raiz": [h for h in raiz.handlers if not isinstance(h, captura_do_pytest)],
        "nivel_da_raiz": raiz.level,
        **{n: (list(logging.getLogger(n).handlers), logging.getLogger(n).level,
               logging.getLogger(n).propagate) for n in NOMES},
    }


def test_1_upgrade_pelo_alembic_ini_troca_o_logging_dentro_do_teste(tmp_path, caplog):
    captura = type(caplog.handler)
    _ANTES.update(_retrato(captura))
    assert not any(_do_alembic_ini(h) for h in _ANTES["raiz"])
    engine = create_engine(f"sqlite:///{(tmp_path / 'pelo-ini.db').as_posix()}")
    try:
        cfg = _config()
        assert cfg.config_file_name                      # é a Config COM o alembic.ini
        with engine.begin() as conexao:
            cfg.attributes["connection"] = conexao
            command.upgrade(cfg, _REVISAO_BASE)
    finally:
        engine.dispose()
    depois = _retrato(captura)
    # O problema existe: o fileConfig trocou o handler e o nível da raiz.
    assert any(_do_alembic_ini(h) for h in depois["raiz"])
    assert depois["raiz"] != _ANTES["raiz"] and depois["nivel_da_raiz"] == logging.WARNING


def test_2_o_teste_seguinte_recebe_o_logging_de_volta(caplog):
    raiz = logging.getLogger().handlers
    assert not any(_do_alembic_ini(h) for h in raiz), (
        "o StreamHandler do alembic.ini vazou do teste anterior para a raiz")
    if not _ANTES:
        pytest.skip("depende do teste anterior: rode o arquivo inteiro")
    assert _retrato(type(caplog.handler)) == _ANTES
    # E o caplog deste teste captura normalmente.
    logging.getLogger("constela").warning("registro de prova (fictício)")
    assert "registro de prova (fictício)" in caplog.text
