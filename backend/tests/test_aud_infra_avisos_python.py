"""Avisos do Python (``warnings.warn``) saem pelo log JSON, não crus no stderr.

``configurar_logging`` põe o handler JSON no STDOUT porque o Railway marca como ERRO toda
linha do stderr — mas não ligava ``logging.captureWarnings``: o aviso de uma biblioteca
(ex.: o openpyxl, ao abrir uma Lista Piloto com lista suspensa do Excel, "Data Validation
extension is not supported and will be removed") saía no stderr em texto cru, em duas
linhas, sem ``request_id`` (auditoria, achado OBSERVABILIDADE-11). Dados fictícios.
"""
import io
import json
import logging
import os
import secrets
import subprocess
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

from app.core import observabilidade as obs

BACKEND = Path(__file__).resolve().parents[1]


def test_aviso_depois_do_configurar_logging_vira_linha_json(monkeypatch, capsys):
    raiz = logging.getLogger()
    handlers, nivel = list(raiz.handlers), raiz.level
    saida = io.StringIO()
    monkeypatch.setattr(sys, "stdout", saida)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("always")
            # O import do app.main na coleta já ligou a captura, e o pytest desfez a
            # troca do ``showwarning`` ao fim da coleta: o ``captureWarnings(True)`` de
            # novo seria nada. Volta ao estado de um processo novo.
            logging.captureWarnings(False)
            obs.configurar_logging(SimpleNamespace(LOG_LEVEL="INFO", LOG_JSON=True))
            warnings.warn("aviso fictício de uma biblioteca", UserWarning, stacklevel=1)
    finally:
        logging.captureWarnings(False)
        raiz.handlers[:] = handlers
        raiz.setLevel(nivel)
    linhas = [json.loads(x) for x in saida.getvalue().splitlines() if x.startswith("{")]
    avisos = [x for x in linhas if "aviso fictício de uma biblioteca" in x["message"]]
    assert len(avisos) == 1, saida.getvalue()
    assert avisos[0]["level"] == "warn" and avisos[0]["logger"] == "py.warnings"
    assert "aviso fictício" not in capsys.readouterr().err


_FILHO = r'''
import io, logging, zipfile
from types import SimpleNamespace
from app.core import observabilidade as obs
obs.configurar_logging(SimpleNamespace(LOG_LEVEL="INFO", LOG_JSON=True))
from openpyxl import Workbook, load_workbook
wb = Workbook(); ws = wb.active; ws.title = "3A"
ws.append(["Nº", "Nome", "RA"]); ws.append([1, "Aluno Ficticio Um", "000000001"])
bruto = io.BytesIO(); wb.save(bruto)
# Lista suspensa do Excel (extensão de validação de dados): o openpyxl avisa ao abrir.
EXT = (b'<extLst><ext uri="{CCE6A557-97BC-4b89-ADB6-D9C93CAAB3DF}" '
       b'xmlns:x14="http://schemas.microsoft.com/office/spreadsheetml/2009/9/main">'
       b'<x14:dataValidations count="0"/></ext></extLst>')
saida = io.BytesIO()
with zipfile.ZipFile(io.BytesIO(bruto.getvalue())) as zin, zipfile.ZipFile(saida, "w") as zout:
    for item in zin.infolist():
        dados = zin.read(item.filename)
        if item.filename == "xl/worksheets/sheet1.xml":
            dados = dados.replace(b"</worksheet>", EXT + b"</worksheet>")
        zout.writestr(item, dados)
load_workbook(io.BytesIO(saida.getvalue()), read_only=False)
logging.getLogger("constela").info("fim_do_teste")
'''


def test_aviso_do_openpyxl_num_processo_de_producao_sai_no_json():
    """Processo novo, como o da API: nada de stderr, o aviso vira uma linha JSON."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8", SECRET_KEY=secrets.token_urlsafe(48))
    env.pop("PYTHONWARNINGS", None)
    r = subprocess.run([sys.executable, "-c", _FILHO], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, cwd=BACKEND,
                       timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    assert not [x for x in r.stderr.splitlines() if x.strip()], r.stderr[-2000:]
    linhas = [json.loads(x) for x in r.stdout.splitlines() if x.startswith("{")]
    avisos = [x for x in linhas if x.get("logger") == "py.warnings"]
    assert len(avisos) == 1, r.stdout[-2000:]
    assert avisos[0]["level"] == "warn"
    assert "Data Validation extension is not supported" in avisos[0]["message"]
    assert linhas[-1]["message"] == "fim_do_teste"
