"""P-UPLOADS-4 (pendência da fase B) — POST /redes/{id}/casar-inep com a planilha recusada.

O casamento do código INEP lê o arquivo oficial pelo ``avaliacoes._iterar_grade``, que
agora RECUSA o .xlsx inflado (ou com uma compactação que o Excel não gera) com
``ImportacaoRecusada`` antes de abri-lo. A rota não capturava a recusa: respondia 500 (um
erro interno, sem dizer o que fazer) em vez do 400 com o motivo, como as rotas de
avaliações e indicadores já fazem.

Rede e escola FICTÍCIAS.
"""
import io
import zipfile

from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import Escola, Rede, Usuario

API = "/api/v1"
CT_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx_com_bzip2() -> bytes:
    """Um .xlsx mínimo comprimido com bzip2 (o Excel só gera deflate/stored): a guarda das
    planilhas o recusa antes de ler, sem descomprimir nada."""
    partes = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8"?><Types xmlns='
                               '"http://schemas.openxmlformats.org/package/2006/content-types"/>',
        "xl/workbook.xml": "<workbook/>",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_BZIP2) as z:
        for nome, texto in partes.items():
            z.writestr(nome, texto)
    return buf.getvalue()


def _cliente_global(db) -> TestClient:
    db.add(Usuario(nome="Global Inventado", email="global.inep@inventado.local",
                   senha_hash=hash_senha("s3nh4-inventada"), cargo="admin", is_global=True))
    db.commit()
    # Sem relançar a exceção do servidor: o que se confere é a RESPOSTA (o 500 de antes).
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post(f"{API}/auth/login",
               data={"username": "global.inep@inventado.local", "password": "s3nh4-inventada"})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def test_planilha_recusada_no_casamento_inep_responde_400_com_o_motivo(db):
    rede = Rede(nome="Rede Inventada do INEP", status="ativa")
    db.add(rede)
    db.flush()
    db.add(Escola(nome="EMEF INVENTADA DO INEP", ano_letivo_ativo=2026, status="ativa",
                  rede_id=rede.id, cidade="Cidade Inventada"))
    db.commit()
    c = _cliente_global(db)
    r = c.post(f"{API}/redes/{rede.id}/casar-inep",
               files={"arquivo": ("ideb_escolas.xlsx", _xlsx_com_bzip2(), CT_XLSX)})
    assert r.status_code == 400, r.text
    assert "Nada foi gravado" in r.json()["detail"]
    # Nenhum código INEP foi gravado.
    db.expire_all()
    assert all(e.codigo_inep is None for e in db.query(Escola).filter_by(rede_id=rede.id))
