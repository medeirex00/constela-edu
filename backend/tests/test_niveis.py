"""Cadastro dos níveis de dificuldade (faixas) e provisionamento da escola.

Cobre o conserto do beco "Cadastre os níveis de dificuldade": criar/editar/
excluir níveis pela interface, o atalho de níveis padrão e o fato de uma escola
nova nascer provisionada (antes, escola criada pela tela ficava sem níveis).
"""
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_senha
from app.main import app
from app.models import Escola, NivelDificuldade, ReferenciaNormalizacao, Turma, Usuario
from app.services import provisionamento

API = "/api/v1"


def _niveis(cliente, escola_id=1):
    r = cliente.get(f"{API}/escolas/{escola_id}/configuracoes/dificuldade")
    assert r.status_code == 200, r.text
    return r.json()["niveis"]


def _cliente_global(db, escola_id=1) -> TestClient:
    """Cliente autenticado como ADMIN GLOBAL — os níveis são REFERÊNCIA/base da
    premiação e só ele pode criar/editar/excluir/semear."""
    db.add(Usuario(escola_id=escola_id, nome="Global", email="global@teste.local",
                   senha_hash=hash_senha("s3nh4"), cargo="admin", is_global=True))
    db.commit()
    c = TestClient(app)
    tok = c.post(f"{API}/auth/login",
                 data={"username": "global@teste.local", "password": "s3nh4"}).json()["access_token"]
    c.headers["Authorization"] = f"Bearer {tok}"
    return c


def test_criar_editar_e_excluir_nivel(cliente, db):
    gc = _cliente_global(db)                        # só admin global edita níveis
    # cria — códigos são normalizados (maiúsculo, sem espaço, sem repetido)
    r = gc.post(f"{API}/escolas/1/configuracoes/niveis",
                json={"nome": "Nível 9", "codigos": ["y", "z ", "Z"], "pontos_padrao": 20})
    assert r.status_code == 201, r.text
    novo = r.json()
    assert novo["codigos"] == ["Y", "Z"]
    assert novo["codigo"] == "nivel_9"
    nivel_id = novo["id"]

    assert "Nível 9" in [n["nome"] for n in _niveis(cliente)]   # leitura é de todos

    # edita nome e pontos
    r = gc.put(f"{API}/escolas/1/configuracoes/niveis/{nivel_id}",
               json={"pontos_padrao": 25, "nome": "Nível X"})
    assert r.status_code == 200, r.text
    assert r.json()["pontos_padrao"] == 25
    assert r.json()["nome"] == "Nível X"

    # exclui
    r = gc.delete(f"{API}/escolas/1/configuracoes/niveis/{nivel_id}")
    assert r.status_code == 200, r.text
    assert "Nível X" not in [n["nome"] for n in _niveis(cliente)]


def test_niveis_sao_somente_leitura_para_nao_global(cliente):
    """Admin de escola (não global) só VISUALIZA: qualquer escrita = 403."""
    assert cliente.get(f"{API}/escolas/1/configuracoes/dificuldade").status_code == 200
    assert cliente.post(f"{API}/escolas/1/configuracoes/niveis",
                        json={"nome": "X", "codigos": ["Q"], "pontos_padrao": 1}).status_code == 403
    assert cliente.post(f"{API}/escolas/1/configuracoes/niveis/padrao").status_code == 403
    existente = _niveis(cliente)[0]["id"]
    assert cliente.put(f"{API}/escolas/1/configuracoes/niveis/{existente}",
                       json={"pontos_padrao": 99}).status_code == 403
    assert cliente.delete(f"{API}/escolas/1/configuracoes/niveis/{existente}").status_code == 403


def test_niveis_padrao_desbloqueiam_a_pontuacao_por_turma(cliente, db):
    gc = _cliente_global(db)
    # esvazia os níveis desta escola -> beco: catálogo de pontuação vazio
    for n in db.execute(
        select(NivelDificuldade).where(NivelDificuldade.escola_id == 1)
    ).scalars().all():
        db.delete(n)
    db.commit()
    r = cliente.get(f"{API}/escolas/1/configuracoes/pontuacao-turma")
    assert r.status_code == 200
    assert r.json()["catalogo"] == []

    # 1 clique: níveis padrão do Elefante (admin global)
    r = gc.post(f"{API}/escolas/1/configuracoes/niveis/padrao")
    assert r.status_code == 200, r.text
    assert r.json()["criados"] == len(provisionamento.NIVEIS_PADRAO)

    # agora o catálogo tem códigos -> pontuação por turma liberada
    r = cliente.get(f"{API}/escolas/1/configuracoes/pontuacao-turma")
    codigos = [c["codigo"] for c in r.json()["catalogo"]]
    assert "AA" in codigos and "Z" in codigos


def test_niveis_padrao_nao_duplica_se_ja_existem(cliente, db):
    gc = _cliente_global(db)
    antes = len(_niveis(cliente))
    r = gc.post(f"{API}/escolas/1/configuracoes/niveis/padrao")
    assert r.status_code == 200
    assert r.json()["criados"] == 0
    assert len(_niveis(cliente)) == antes


def test_semear_config_inicial_provisiona_escola_nova(db):
    escola = Escola(nome="ESCOLA NOVA", ano_letivo_ativo=2026)
    db.add(escola)
    db.flush()
    provisionamento.semear_config_inicial(db, escola.id)
    db.commit()

    niveis = db.execute(
        select(NivelDificuldade).where(NivelDificuldade.escola_id == escola.id)
    ).scalars().all()
    assert len(niveis) == len(provisionamento.NIVEIS_PADRAO)
    ref = db.execute(
        select(ReferenciaNormalizacao).where(ReferenciaNormalizacao.escola_id == escola.id)
    ).scalar_one_or_none()
    assert ref is not None and ref.modo == "auto"


def test_pontuacao_turma_replica_para_outras_turmas(cliente, db, escola_completa):
    """Configurar uma turma e replicar a MESMA config para outras (aplicar_em):
    todas as turmas marcadas recebem o override; cada uma segue editável depois."""
    escola = escola_completa["escola"]
    t1 = escola_completa["turma"]                       # 3º Ano A (níveis já semeados)
    t2 = Turma(escola_id=escola.id, nome="3º Ano B", ano_escolar="3º Ano", ano_letivo=2026)
    t3 = Turma(escola_id=escola.id, nome="3º Ano C", ano_escolar="3º Ano", ano_letivo=2026)
    db.add_all([t2, t3])
    db.commit()

    r = cliente.put(f"{API}/escolas/{escola.id}/configuracoes/pontuacao-turma",
                    json={"turma_id": t1.id, "pontos": {"AA": 9.0}, "aplicar_em": [t2.id, t3.id]})
    assert r.status_code == 200, r.text
    assert set(r.json()["turmas"]) == {t1.id, t2.id, t3.id}

    porturma = {t["turma_id"]: t["pontos"]
                for t in cliente.get(f"{API}/escolas/{escola.id}/configuracoes/pontuacao-turma").json()["turmas"]}
    assert porturma[t1.id].get("AA") == 9.0
    assert porturma[t2.id].get("AA") == 9.0
    assert porturma[t3.id].get("AA") == 9.0
