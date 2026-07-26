"""Casar as escolas de uma rede com o código INEP oficial por NOME, escopado pelo
MUNICÍPIO — a partir do arquivo do INEP (layout do IDEB por escola). Devolve
propostas para conferência; grava via o PATCH de escola."""
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_senha
from app.main import app
from app.models import Escola, Rede, Usuario
from app.services import casamento_inep as svc


def _linha(vals: dict) -> list:
    row = [""] * (max(vals) + 1)
    for i, v in vals.items():
        row[i] = str(v)
    return row


def _oficial(escolas, preamble=8) -> bytes:
    """Arquivo oficial no layout do IDEB: col2=município, col3=INEP, col4=nome,
    col115=valor; dados começam na linha `preamble` (após pré-âmbulo/cabeçalhos)."""
    linhas = [[f"cabecalho {i}"] for i in range(preamble)]
    for muni, inep, nome, valor in escolas:
        linhas.append(_linha({2: muni, 3: inep, 4: nome, 115: valor}))
    return "\n".join(";".join(c for c in ln) for ln in linhas).encode("utf-8")


def _escola(db, rede_id, nome, cidade):
    e = Escola(nome=nome, ano_letivo_ativo=2026, status="ativa",
               rede_id=rede_id, cidade=cidade)
    db.add(e); db.flush()
    return e


OFICIAL = _oficial([
    ("Caraguatatuba", "35402862", "ADOLFINA LEONOR SOARES DOS SANTOS PROFA CIEFI", "6.8"),
    ("Caraguatatuba", "35215077", "CARLOS DE ALMEIDA RODRIGUES DR EMEF", "7.0"),
    ("Caraguatatuba", "35225903", "MARIA APARECIDA UJIO PROFA EMEF", "7.2"),
    ("Caraguatatuba", "35495037", "MARIA APARECIDA DE CARVALHO PROFA EMEF", "6.1"),
    ("Sao Paulo", "35000001", "CARLOS DE ALMEIDA RODRIGUES DR EMEF", "5.0"),  # homônima
])


def test_casa_por_nome_dentro_do_municipio(db):
    rede = Rede(nome="Caraguá", status="ativa"); db.add(rede); db.flush()
    _escola(db, rede.id, "ADOLFINA", "Caraguatatuba")            # nome curto do gestor
    _escola(db, rede.id, "CARLOS RODRIGUES", "Caraguatatuba")
    db.commit()
    props = {p["escola_nome"]: p for p in svc.casar_inep(db, rede.id, OFICIAL, "ideb.csv")}
    assert props["ADOLFINA"]["inep"] == "35402862"
    assert props["ADOLFINA"]["confianca"] == "alta" and props["ADOLFINA"]["valor"] == 6.8
    # casa a CARLOS RODRIGUES de Caraguatatuba, NUNCA a homônima de São Paulo
    assert props["CARLOS RODRIGUES"]["inep"] == "35215077"


def test_ambiguo_vira_revisar(db):
    rede = Rede(nome="R", status="ativa"); db.add(rede); db.flush()
    _escola(db, rede.id, "MARIA APARECIDA", "Caraguatatuba")     # casa Ujio E Carvalho
    db.commit()
    p = svc.casar_inep(db, rede.id, OFICIAL, "ideb.csv")[0]
    assert p["confianca"] == "revisar"                           # não escolhe sozinho


def test_superconjunto_multiplo_vira_revisar(db):
    # Achado da revisão (alto): nome curto subconjunto de VÁRIOS oficiais do mesmo
    # município (com sobras DIFERENTES) não pode dar "alta" — escolheria a errada.
    oficial = _oficial([
        ("Caraguatatuba", "35111111", "SANTOS DUMONT PROF EMEF", "6.0"),   # {SANTOS,DUMONT}
        ("Caraguatatuba", "35222222", "JOAO BATISTA SANTOS EMEF", "5.0"),  # {JOAO,BATISTA,SANTOS}
    ])
    rede = Rede(nome="R", status="ativa"); db.add(rede); db.flush()
    _escola(db, rede.id, "SANTOS", "Caraguatatuba")     # {SANTOS} ⊆ os dois
    db.commit()
    p = svc.casar_inep(db, rede.id, oficial, "ideb.csv")[0]
    assert p["confianca"] == "revisar"                  # não escolhe uma das duas


def test_nome_identico_unico_e_alta(db):
    # Nome oficial IDÊNTICO (tokens iguais) e único ⇒ "alta", mesmo com outro
    # superconjunto por perto.
    oficial = _oficial([
        ("Caraguatatuba", "35111111", "EMEF PROF AURACY MANSANO", "5.5"),      # == {AURACY,MANSANO}
        ("Caraguatatuba", "35222222", "AURACY MANSANO JUNIOR EMEF", "6.0"),    # superconjunto
    ])
    rede = Rede(nome="R", status="ativa"); db.add(rede); db.flush()
    _escola(db, rede.id, "AURACY MANSANO", "Caraguatatuba")
    db.commit()
    p = svc.casar_inep(db, rede.id, oficial, "ideb.csv")[0]
    assert p["confianca"] == "alta" and p["inep"] == "35111111"


def test_proposta_expoe_municipio_oficial(db):
    # Achado da revisão: a proposta precisa trazer o município OFICIAL (para o
    # gestor rejeitar homônima de outra cidade no fallback global).
    rede = Rede(nome="R", status="ativa"); db.add(rede); db.flush()
    _escola(db, rede.id, "ADOLFINA", "Caraguatatuba")
    db.commit()
    p = svc.casar_inep(db, rede.id, OFICIAL, "ideb.csv")[0]
    assert p["municipio_oficial"] == "Caraguatatuba"


def test_sem_correspondencia(db):
    rede = Rede(nome="R", status="ativa"); db.add(rede); db.flush()
    _escola(db, rede.id, "ESCOLA FANTASMA", "Caraguatatuba")
    db.commit()
    p = svc.casar_inep(db, rede.id, OFICIAL, "ideb.csv")[0]
    assert p["inep"] is None and p["confianca"] == "nenhum"


def test_so_escolas_da_rede(db):
    ra = Rede(nome="A", status="ativa"); rb = Rede(nome="B", status="ativa")
    db.add_all([ra, rb]); db.flush()
    _escola(db, ra.id, "ADOLFINA", "Caraguatatuba")
    _escola(db, rb.id, "CARLOS RODRIGUES", "Caraguatatuba")
    db.commit()
    props = svc.casar_inep(db, ra.id, OFICIAL, "ideb.csv")
    assert {p["escola_nome"] for p in props} == {"ADOLFINA"}     # não vaza a rede B


# --- Endpoint ----------------------------------------------------------------

def _cliente_global(db):
    db.add(Usuario(nome="Root", email="root@seduc.gov",
                   senha_hash=hash_senha("r00tgl0b4l"), cargo="admin", is_global=True))
    db.commit()
    c = TestClient(app)
    r = c.post("/api/v1/auth/login",
               data={"username": "root@seduc.gov", "password": "r00tgl0b4l"})
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def test_endpoint_casar_e_salvar_inep(db):
    rede = Rede(nome="Caraguá", status="ativa"); db.add(rede); db.flush()
    e = _escola(db, rede.id, "ADOLFINA", "Caraguatatuba")
    db.commit()
    c = _cliente_global(db)
    r = c.post(f"/api/v1/redes/{rede.id}/casar-inep",
               files={"arquivo": ("ideb.csv", OFICIAL, "text/csv")})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["casadas"] == 1 and corpo["total"] == 1
    prop = corpo["propostas"][0]
    assert prop["inep"] == "35402862"
    # grava o INEP proposto via o PATCH de escola (normaliza p/ 8 dígitos)
    s = c.patch(f"/api/v1/redes/escolas/{e.id}", json={"codigo_inep": prop["inep"]})
    assert s.status_code == 200 and s.json()["codigo_inep"] == "35402862"
    db.expire_all()
    assert db.get(Escola, e.id).codigo_inep == "35402862"


def test_patch_limpa_inep_com_vazio(db):
    rede = Rede(nome="R", status="ativa"); db.add(rede); db.flush()
    e = _escola(db, rede.id, "X", "Caraguatatuba"); e.codigo_inep = "35402862"
    db.commit()
    c = _cliente_global(db)
    s = c.patch(f"/api/v1/redes/escolas/{e.id}", json={"codigo_inep": ""})
    assert s.status_code == 200 and s.json()["codigo_inep"] is None


def test_endpoint_exige_admin_global(db, escola_completa, cliente):
    rede = Rede(nome="R", status="ativa"); db.add(rede); db.flush(); db.commit()
    r = cliente.post(f"/api/v1/redes/{rede.id}/casar-inep",
                     files={"arquivo": ("x.csv", OFICIAL, "text/csv")})
    assert r.status_code == 403
