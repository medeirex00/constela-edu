"""Coleta AUTOMÁTICA de avaliações externas (o "robô"): a Secretaria não sobe
nada — o admin global cadastra a RECEITA (URL + mapeamento) e o software baixa o
arquivo oficial e importa sozinho, casando por INEP. O download é injetável, então
os testes NÃO tocam a rede; validam a máquina (import, idempotência, agenda, erro
que vira status sem quebrar) e os endpoints (só admin global)."""
import io
import zipfile
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.security import hash_senha
from app.main import app
from app.models import (AvaliacaoExterna, Escola, FonteAvaliacao, Rede,
                        ResultadoAvaliacao, Usuario)
from app.services import avaliacoes as svc


def _csv(linhas):
    return "\n".join(";".join(c for c in linha) for linha in linhas).encode("utf-8")


_PLANILHA = _csv([
    ["Resultados do IDEB 2023 - Anos Iniciais"],
    ["CO_ESCOLA", "NO_ESCOLA", "IDEB_2023"],
    ["35012345", "EM Alfa", "6,1"],
    ["35067890", "EM Beta", "5,3"],
])

_MAPEAMENTO = {"linha_dados": 2, "col_inep": 0, "col_valor": 2,
               "etapa_fixa": "anos_iniciais"}


def _escola(db, rede_id, nome, inep):
    e = Escola(nome=nome, ano_letivo_ativo=2026, status="ativa", rede_id=rede_id,
               codigo_inep=inep)
    db.add(e); db.flush()
    return e


def _fonte(db, *, cadencia="manual", proxima=None, ativo=True, mapeamento=None):
    av = svc.obter_avaliacao(db, "ideb")
    f = FonteAvaliacao(
        avaliacao_id=av.id, nome="IDEB AI 2023",
        url="https://download.inep.gov.br/ideb/x.csv", edicao=2023,
        indicador="ideb", unidade="indice", cadencia=cadencia, ativo=ativo,
        mapeamento=mapeamento or dict(_MAPEAMENTO), proxima_coleta=proxima)
    db.add(f); db.commit(); db.refresh(f)
    return f


# --- Serviço: coleta ---------------------------------------------------------

def test_coletar_fonte_baixa_e_importa(db):
    rede = Rede(nome="R", status="ativa"); db.add(rede); db.flush()
    _escola(db, rede.id, "EM Alfa", "35012345")
    _escola(db, rede.id, "EM Beta", "35067890")
    db.commit()
    f = _fonte(db, cadencia="mensal")

    resumo = svc.coletar_fonte(db, f, baixador=lambda url: _PLANILHA)
    db.commit()

    assert resumo["status"] == "ok"
    assert f.ultimo_status == "ok" and f.ultimo_erro is None
    assert f.ultima_coleta is not None
    assert f.proxima_coleta is not None            # mensal reagenda
    assert f.proxima_coleta > f.ultima_coleta
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 2


def test_coletar_fonte_erro_de_download_vira_status_sem_quebrar(db):
    f = _fonte(db)

    def _explode(url):
        raise ConnectionError("reset by peer")

    resumo = svc.coletar_fonte(db, f, baixador=_explode)   # NÃO levanta
    db.commit()

    assert resumo["status"] == "erro"
    assert f.ultimo_status == "erro"
    assert "ConnectionError" in f.ultimo_erro
    assert f.ultima_coleta is not None             # registrou a tentativa
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 0


def test_coletar_fonte_aceita_zip(db):
    rede = Rede(nome="R", status="ativa"); db.add(rede); db.flush()
    _escola(db, rede.id, "EM Alfa", "35012345")
    db.commit()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("divulgacao/planilha.csv", _PLANILHA.decode("utf-8"))
    conteudo = buf.getvalue()
    f = _fonte(db)

    svc.coletar_fonte(db, f, baixador=lambda url: conteudo)
    db.commit()
    assert f.ultimo_status == "ok"
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 1


def test_coletar_fonte_reimporta_idempotente(db):
    rede = Rede(nome="R", status="ativa"); db.add(rede); db.flush()
    _escola(db, rede.id, "EM Alfa", "35012345")
    _escola(db, rede.id, "EM Beta", "35067890")
    db.commit()
    f = _fonte(db)
    svc.coletar_fonte(db, f, baixador=lambda url: _PLANILHA); db.commit()
    svc.coletar_fonte(db, f, baixador=lambda url: _PLANILHA); db.commit()
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 2   # não duplicou


# --- Serviço: agenda (coletar_pendentes) -------------------------------------

def test_coletar_pendentes_pega_vencida_e_reagenda(db):
    rede = Rede(nome="R", status="ativa"); db.add(rede); db.flush()
    _escola(db, rede.id, "EM Alfa", "35012345")
    db.commit()
    vencida = svc._agora() - timedelta(days=1)
    f = _fonte(db, cadencia="mensal", proxima=vencida)

    n = svc.coletar_pendentes(db, baixador=lambda url: _PLANILHA)

    assert n == 1
    db.refresh(f)
    assert f.ultimo_status == "ok"
    assert f.proxima_coleta > svc._agora()         # reagendou ~+30d


def test_coletar_pendentes_ignora_manual_e_futura_e_inativa(db):
    rede = Rede(nome="R", status="ativa"); db.add(rede); db.flush()
    _escola(db, rede.id, "EM Alfa", "35012345")
    db.commit()
    _fonte(db, cadencia="manual", proxima=None)                       # sem agenda
    _fonte(db, cadencia="mensal", proxima=svc._agora() + timedelta(days=5))  # futura
    _fonte(db, cadencia="mensal", proxima=svc._agora() - timedelta(days=1),
           ativo=False)                                              # vencida mas OFF

    n = svc.coletar_pendentes(db, baixador=lambda url: _PLANILHA)
    assert n == 0
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 0


# --- Endpoints (só admin global) ---------------------------------------------

def _cliente_global(db):
    db.add(Usuario(nome="Root", email="root@seduc.gov",
                   senha_hash=hash_senha("r00tgl0b4l"), cargo="admin",
                   is_global=True))
    db.commit()
    c = TestClient(app)
    r = c.post("/api/v1/auth/login",
               data={"username": "root@seduc.gov", "password": "r00tgl0b4l"})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _corpo_fonte():
    return {"avaliacao": "ideb", "nome": "IDEB AI 2023",
            "url": "https://download.inep.gov.br/ideb/x.csv", "edicao": 2023,
            "indicador": "ideb", "unidade": "indice", "cadencia": "mensal",
            "mapeamento": _MAPEAMENTO}


def test_criar_listar_fonte(db):
    c = _cliente_global(db)
    r = c.post("/api/v1/avaliacoes/fontes", json=_corpo_fonte())
    assert r.status_code == 201, r.text
    criada = r.json()
    assert criada["cadencia"] == "mensal" and criada["ativo"] is True
    assert criada["proxima_coleta"] is not None      # mensal já agenda a 1ª
    lista = c.get("/api/v1/avaliacoes/fontes").json()
    assert len(lista) == 1 and lista[0]["avaliacao"] == "ideb"


def test_criar_fonte_avaliacao_desconhecida_400(db):
    c = _cliente_global(db)
    corpo = _corpo_fonte(); corpo["avaliacao"] = "enem"
    assert c.post("/api/v1/avaliacoes/fontes", json=corpo).status_code == 400


def test_criar_fonte_url_invalida_400(db):
    c = _cliente_global(db)
    corpo = _corpo_fonte(); corpo["url"] = "ftp://x/y"
    assert c.post("/api/v1/avaliacoes/fontes", json=corpo).status_code == 400


def test_fontes_exige_admin_global(db, escola_completa, cliente):
    # cliente = admin de ESCOLA (não global) → 403 nos endpoints do robô.
    assert cliente.get("/api/v1/avaliacoes/fontes").status_code == 403
    assert cliente.post("/api/v1/avaliacoes/fontes", json=_corpo_fonte()).status_code == 403


def test_coletar_agora_endpoint(db, monkeypatch):
    rede = Rede(nome="R", status="ativa"); db.add(rede); db.flush()
    _escola(db, rede.id, "EM Alfa", "35012345")
    _escola(db, rede.id, "EM Beta", "35067890")
    db.commit()
    monkeypatch.setattr(svc, "baixar_url", lambda url, **kw: _PLANILHA)  # sem rede
    c = _cliente_global(db)
    fid = c.post("/api/v1/avaliacoes/fontes", json=_corpo_fonte()).json()["id"]

    r = c.post(f"/api/v1/avaliacoes/fontes/{fid}/coletar")
    assert r.status_code == 200, r.text
    assert r.json()["ultimo_status"] == "ok"
    db.expire_all()
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 2


def test_coletar_agora_erro_reporta_status_200(db, monkeypatch):
    def _explode(url, **kw):
        raise ConnectionError("blocked")
    monkeypatch.setattr(svc, "baixar_url", _explode)
    c = _cliente_global(db)
    fid = c.post("/api/v1/avaliacoes/fontes", json=_corpo_fonte()).json()["id"]

    r = c.post(f"/api/v1/avaliacoes/fontes/{fid}/coletar")
    assert r.status_code == 200                       # a rota não quebra…
    assert r.json()["ultimo_status"] == "erro"        # …o status conta a falha
    assert "ConnectionError" in r.json()["ultimo_erro"]


def test_atualizar_pausa_e_desliga_agenda(db):
    c = _cliente_global(db)
    fid = c.post("/api/v1/avaliacoes/fontes", json=_corpo_fonte()).json()["id"]
    r = c.put(f"/api/v1/avaliacoes/fontes/{fid}?ativo=false")
    assert r.status_code == 200 and r.json()["ativo"] is False
    r = c.put(f"/api/v1/avaliacoes/fontes/{fid}?cadencia=manual")
    assert r.json()["cadencia"] == "manual" and r.json()["proxima_coleta"] is None


def test_excluir_fonte_nao_apaga_resultados(db, monkeypatch):
    rede = Rede(nome="R", status="ativa"); db.add(rede); db.flush()
    _escola(db, rede.id, "EM Alfa", "35012345")
    db.commit()
    monkeypatch.setattr(svc, "baixar_url", lambda url, **kw: _PLANILHA)
    c = _cliente_global(db)
    fid = c.post("/api/v1/avaliacoes/fontes", json=_corpo_fonte()).json()["id"]
    c.post(f"/api/v1/avaliacoes/fontes/{fid}/coletar")

    assert c.delete(f"/api/v1/avaliacoes/fontes/{fid}").status_code == 200
    assert db.scalar(select(func.count(FonteAvaliacao.id))) == 0
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 1   # resultados ficam


# --- Correções da revisão adversarial ---------------------------------------

def test_baixar_url_bloqueia_nao_https_e_rede_interna():
    # Anti-SSRF (achado da revisão): só https e host que resolve para IP público.
    import pytest
    # esquema http:// puro
    with pytest.raises(ValueError, match="https"):
        svc.baixar_url("http://download.inep.gov.br/x.csv")
    # loopback / link-local / privado (metadata de nuvem = 169.254.169.254)
    for alvo in ("https://127.0.0.1/x", "https://169.254.169.254/latest/meta-data/",
                 "https://10.0.0.5/x", "https://[::1]/x"):
        with pytest.raises(ValueError, match="não-pública|não permitido"):
            svc.baixar_url(alvo)
    # IP público literal passa na checagem de destino (não conecta de verdade aqui).
    svc._exigir_destino_publico("https://200.0.0.1/x")   # não levanta


def test_coletar_pendentes_respeita_teto_por_rodada(db):
    # Achado da revisão: coleta roda embutida na thread do sync — sem teto, muitas
    # fontes estagnariam a fila. O teto limita por rodada; o resto vai na próxima.
    rede = Rede(nome="R", status="ativa"); db.add(rede); db.flush()
    _escola(db, rede.id, "EM Alfa", "35012345")
    db.commit()
    vencida = svc._agora() - timedelta(days=1)
    for _ in range(4):
        _fonte(db, cadencia="mensal", proxima=vencida)

    n = svc.coletar_pendentes(db, baixador=lambda url: _PLANILHA, limite=2)
    assert n == 2                                        # só 2 nesta rodada
    restantes = db.execute(select(FonteAvaliacao).where(
        FonteAvaliacao.proxima_coleta <= svc._agora())).scalars().all()
    assert len(restantes) == 2                           # 2 ainda vencidas p/ a próxima


def test_reativar_fonte_mensal_reagenda_invariante(db):
    # Achado da revisão: reativar (só ?ativo=true) uma fonte mensal não podia
    # deixá-la com proxima_coleta=None (o scheduler a ignoraria em silêncio).
    c = _cliente_global(db)
    fid = c.post("/api/v1/avaliacoes/fontes", json=_corpo_fonte()).json()["id"]
    # pausar zera a agenda…
    assert c.put(f"/api/v1/avaliacoes/fontes/{fid}?ativo=false").json()["proxima_coleta"] is None
    # …e mesmo trocando cadência enquanto pausada (fica None)…
    assert c.put(f"/api/v1/avaliacoes/fontes/{fid}?cadencia=mensal").json()["proxima_coleta"] is None
    # …reativar restaura o invariante: mensal + ativa ⇒ tem proxima_coleta.
    reativada = c.put(f"/api/v1/avaliacoes/fontes/{fid}?ativo=true").json()
    assert reativada["ativo"] is True and reativada["proxima_coleta"] is not None
    # e o scheduler volta a enxergá-la.
    n = svc.coletar_pendentes(db, baixador=lambda url: _PLANILHA)
    assert n == 1
