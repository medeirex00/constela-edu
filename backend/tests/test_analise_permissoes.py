"""Permissões da análise educacional — a matriz dos 7 perfis nas 5 rotas (o padrão de
``test_indicadores_permissoes``).

* ``/redes/{id}/analise/*`` (indicadores, um indicador, plataformas, relação):
  ``exigir_rede`` — a Secretaria da PRÓPRIA rede e o admin global. Secretaria de outra
  rede, coordenador, professor e admin de escola: 403;
* ``/escolas/{id}/analise``: a MESMA regra de ``GET /escolas/{id}/indicadores`` — o
  global, a Secretaria da rede da escola e o coordenador/admin da PRÓPRIA escola; o
  professor (nem a da escola dele), o coordenador de outra escola e a Secretaria de outra
  rede: 403;
* as rotas da rede não aceitam ``escola_id`` de OUTRA rede nem de escola sem rede (404,
  sem o nome da outra escola);
* nenhuma rota da análise escreve (só GET, e o banco fica igual depois de todas as rotas
  com todos os perfis) nem existe no painel público;
* a supressão na rota da escola segue quem lê: o coordenador da escola não perde o
  agregado dela por causa de outra escola da rede (nem fica sabendo que ela existe); a
  Secretaria continua com a decisão da rede.

Dados INVENTADOS (decisão D13).
"""
import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.security import hash_senha
from app.main import app
from app.models import Usuario
from tests.test_analise_base import (HOJE, NOMES, mundo_plataformas, nova_escola, nova_rede,
                                     retrato_matific, turma_com_alunos)

SENHA = "s3nh4analise"
PERFIS = ("global", "secretaria", "secretaria_outra", "coordenador", "coordenador_outra",
          "professor", "admin_escola")
DA_REDE = {"global", "secretaria"}


@pytest.fixture()
def mundo(db, monkeypatch):
    monkeypatch.setattr("app.routers.analise.hoje_br", lambda: HOJE)
    base = mundo_plataformas(db)
    rede, alfa, beta = base["rede"], base["escolas"]["alfa"], base["escolas"]["beta"]
    vizinha = nova_rede(db, nome="Rede Fictícia Vizinha", codigo="3599908", codmun="9998")
    da_vizinha = nova_escola(db, vizinha, "EMEF Fictícia da Vizinha", "35990801")
    sem_rede = nova_escola(db, None, "Escola Fictícia Sem Rede", "35990901")
    usuarios = {
        "global": {"cargo": "admin", "is_global": True},
        "secretaria": {"cargo": "coordenador", "rede_id": rede.id},
        "secretaria_outra": {"cargo": "coordenador", "rede_id": vizinha.id},
        "coordenador": {"cargo": "coordenador", "escola_id": alfa.id},
        "coordenador_outra": {"cargo": "coordenador", "escola_id": beta.id},
        "professor": {"cargo": "professor", "escola_id": alfa.id},
        "admin_escola": {"cargo": "admin", "escola_id": alfa.id},
    }
    hash_ = hash_senha(SENHA)
    for perfil, campos in usuarios.items():
        db.add(Usuario(nome=perfil, email=f"{perfil}@analise.local", senha_hash=hash_, **campos))
    db.commit()
    clientes = {}
    for perfil in usuarios:
        c = TestClient(app)
        r = c.post("/api/v1/auth/login",
                   data={"username": f"{perfil}@analise.local", "password": SENHA})
        assert r.status_code == 200, r.text
        c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        clientes[perfil] = c
    return {**base, "vizinha": vizinha, "da_vizinha": da_vizinha, "sem_rede": sem_rede,
            "c": clientes}


def _matriz(mundo, chamada, permitidos: set[str], *, ok=(200,)) -> dict:
    """``chamada(cliente)`` em cada perfil: os permitidos recebem ``ok``; os demais, 403."""
    codigos = {}
    for perfil in PERFIS:
        r = chamada(mundo["c"][perfil])
        codigos[perfil] = r.status_code
        if perfil in permitidos:
            assert r.status_code in ok, (perfil, r.status_code, r.text)
        else:
            assert r.status_code == 403, (perfil, r.status_code, r.text)
    return codigos


def _rotas_da_rede(rede_id: int) -> list[tuple[str, dict]]:
    base = f"/api/v1/redes/{rede_id}/analise"
    return [(f"{base}/indicadores", {}),
            (f"{base}/indicadores/saresp", {"visao": "escolas", "edicao": 2025}),
            (f"{base}/plataformas", {}),
            (f"{base}/relacao", {"indicador": "saresp"})]


@pytest.mark.parametrize("indice", range(4))
def test_rotas_da_rede_secretaria_da_rede_e_admin_global(mundo, indice):
    url, params = _rotas_da_rede(mundo["rede"].id)[indice]
    _matriz(mundo, lambda c: c.get(url, params=params), DA_REDE)
    # A rede vizinha: só o global e a Secretaria dela.
    url_v, params_v = _rotas_da_rede(mundo["vizinha"].id)[indice]
    _matriz(mundo, lambda c: c.get(url_v, params=params_v), {"global", "secretaria_outra"})
    # Rede que não existe: 404 (antes do 403, como em exigir_rede).
    url_x, params_x = _rotas_da_rede(999999)[indice]
    assert mundo["c"]["global"].get(url_x, params=params_x).status_code == 404


def _url_escola(escola_id: int) -> str:
    return f"/api/v1/escolas/{escola_id}/analise"


def test_rota_da_escola_matriz_de_perfis(mundo):
    alfa, beta = mundo["escolas"]["alfa"], mundo["escolas"]["beta"]
    _matriz(mundo, lambda c: c.get(_url_escola(alfa.id)),
            {"global", "secretaria", "coordenador", "admin_escola"})
    _matriz(mundo, lambda c: c.get(_url_escola(beta.id)),
            {"global", "secretaria", "coordenador_outra"})
    _matriz(mundo, lambda c: c.get(_url_escola(mundo["da_vizinha"].id)),
            {"global", "secretaria_outra"})
    assert mundo["c"]["global"].get(_url_escola(999999)).status_code == 404
    assert mundo["c"]["coordenador"].get(_url_escola(999999)).status_code == 404


def test_professor_nao_le_nem_a_propria_escola(mundo):
    r = mundo["c"]["professor"].get(_url_escola(mundo["escolas"]["alfa"].id))
    assert r.status_code == 403 and "coordenação" in r.json()["detail"]


def test_coordenador_ve_so_a_propria_escola_e_a_rede_como_referencia(mundo):
    dados = mundo["c"]["coordenador"].get(_url_escola(mundo["escolas"]["alfa"].id)).json()
    assert dados["escola"]["nome"] == NOMES["alfa"]
    texto = json.dumps(dados, ensure_ascii=False)
    for outra in ("beta", "delta", "gama", "ebano"):
        assert NOMES[outra] not in texto, outra
    for chave in ("35990102", "35990104", "35990105"):
        assert chave not in texto
    papeis = {s["papel"] for item in dados["indicadores"] for s in item["series"]}
    assert papeis <= {"principal", "referencia"}
    assert all(s["abrangencia"] in ("escola", "rede") for item in dados["indicadores"]
               for s in item["series"])


@pytest.mark.parametrize("perfil", ["global", "secretaria"])
def test_rotas_da_rede_recusam_escola_de_outra_rede_ou_sem_rede(mundo, perfil):
    """SEG-4 (a): ``escola_id`` de uma escola da rede vizinha ou de uma escola sem rede
    numa rota da rede: 404, e a resposta não traz o nome da outra escola."""
    base = f"/api/v1/redes/{mundo['rede'].id}/analise"
    for escola in (mundo["da_vizinha"], mundo["sem_rede"]):
        for url, params in ((f"{base}/plataformas", {"escola_id": escola.id}),
                            (f"{base}/indicadores/saresp", {"escola_id": escola.id}),
                            (f"{base}/indicadores/ideb", {"escola_id": escola.id})):
            r = mundo["c"][perfil].get(url, params=params)
            assert r.status_code == 404, (url, r.text)
            assert escola.nome not in r.text and "Vizinha" not in r.text


def _contagens(db) -> dict[str, int]:
    return {t.name: db.execute(select(func.count()).select_from(t)).scalar()
            for t in Base.metadata.sorted_tables}


def test_nenhuma_rota_da_analise_grava_nada_no_banco(db, mundo):
    """SEG-4 (b): todas as rotas da análise, com todos os perfis — nenhum flush com
    objeto novo, alterado ou apagado, e as contagens de todas as tabelas iguais."""
    r, alfa, beta = mundo["rede"].id, mundo["escolas"]["alfa"].id, mundo["escolas"]["beta"].id
    base = f"/api/v1/redes/{r}/analise"
    urls = [(f"{base}/indicadores", {}), (f"{base}/indicadores/saresp", {}),
            (f"{base}/indicadores/saresp", {"visao": "escolas", "edicao": 2025}),
            (f"{base}/indicadores/ideb", {"escola_id": beta}),
            (f"{base}/indicadores/iee", {"visao": "escolas", "edicao": 2025}),
            (f"{base}/indicadores/saeb", {}), (f"{base}/indicadores/ica", {}),
            (f"{base}/plataformas", {}), (f"{base}/plataformas", {"serie": 5}),
            (f"{base}/relacao", {"indicador": "saresp"}),
            (f"{base}/relacao", {"indicador": "ideb", "metrica": "estrelas_por_aluno"}),
            (f"/api/v1/escolas/{alfa}/analise", {}), (f"/api/v1/escolas/{beta}/analise", {}),
            (f"/api/v1/escolas/{mundo['sem_rede'].id}/analise", {})]
    escritas = []

    def _antes_do_flush(sessao, _ctx, _inst):
        if sessao.new or sessao.dirty or sessao.deleted:
            escritas.append((len(sessao.new), len(sessao.dirty), len(sessao.deleted)))

    antes = _contagens(db)
    event.listen(Session, "before_flush", _antes_do_flush)
    try:
        for perfil in PERFIS:
            for url, params in urls:
                mundo["c"][perfil].get(url, params=params)
    finally:
        event.remove(Session, "before_flush", _antes_do_flush)
    db.expire_all()
    assert escritas == []
    assert _contagens(db) == antes


def test_coordenador_nao_perde_a_propria_escola_por_causa_de_outra(db, mundo):
    """SEG-3: com uma escola de 3 crianças na rede, a Beta (8, a menor visível) é
    suprimida em complemento na decisão da REDE. O coordenador da Beta, que não lê a rede,
    recebe a Beta inteira — e nada que denuncie a escola pequena; a Secretaria, que lê a
    rede, continua com a Beta suprimida também na rota da escola (senão recomporia a
    pequena com o total da rede)."""
    rede, beta = mundo["rede"], mundo["escolas"]["beta"]
    pequena = nova_escola(db, rede, "EMEF Fictícia Pequena", "35990198")
    for a in turma_com_alunos(db, pequena, "4º Ano", 3):
        retrato_matific(db, pequena, a, datetime(2026, 9, 30, 3, 20), atividades=9, estrelas=9)
    db.commit()
    url = f"/api/v1/escolas/{beta.id}/analise"
    coord = mundo["c"]["coordenador_outra"].get(url)
    assert coord.status_code == 200, coord.text
    p = coord.json()["plataformas"]
    assert p["suprimido"] is False and p["alunos"] == 8
    assert p["matific"]["atividades_por_aluno"] == 5.0
    assert "Pequena" not in coord.text
    assert not any(s["suprimido"] for s in p["series"])
    sec = mundo["c"]["secretaria"].get(url).json()["plataformas"]
    assert sec["suprimido"] is True and sec["alunos"] is None and sec["matific"] is None
    rede_sec = mundo["c"]["secretaria"].get(
        f"/api/v1/redes/{rede.id}/analise/plataformas").json()
    na_rede = next(e for e in rede_sec["escolas"] if e["escola_id"] == beta.id)
    assert na_rede["suprimido"] is True and sec["series"] == na_rede["series"]


def test_nenhuma_rota_da_analise_escreve_nem_e_publica(mundo):
    rotas = [r for r in app.routes if "/analise" in getattr(r, "path", "")]
    # 5 da análise integrada + diagnóstico e evolução das plataformas (revisão de 01/11).
    assert len(rotas) == 7
    assert all(r.methods <= {"GET", "HEAD"} for r in rotas)
    assert not [r for r in rotas if "/publico" in r.path]
    anonimo = TestClient(app)
    assert anonimo.get(_url_escola(mundo["escolas"]["alfa"].id)).status_code == 401
    assert anonimo.get(f"/api/v1/redes/{mundo['rede'].id}/analise/indicadores").status_code == 401
    # Um POST na rota da análise não existe (405), nem para o global.
    r = mundo["c"]["global"].post(f"/api/v1/redes/{mundo['rede'].id}/analise/indicadores")
    assert r.status_code == 405
