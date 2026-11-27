import secrets
from collections import Counter

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.security import criar_token
from app.main import app
from app.models import Escola, IndicadorReferencia, ModuloRede, Rede, ResultadoAvaliacao, Usuario
from app.services import demo_caragua as demo
from scripts.demo_caragua import provisionar, revogar


def _contagens(db):
    return {
        modelo: db.scalar(select(func.count()).select_from(modelo))
        for modelo in (Rede, Usuario, ModuloRede, Escola, ResultadoAvaliacao, IndicadorReferencia)
    }


@pytest.fixture()
def cenario(db):
    senha = secrets.token_urlsafe(24)
    antes = _contagens(db)
    assert provisionar(db, lambda: senha)
    db.commit()
    esperado = {
        modelo: total + (modelo in (Rede, Usuario, ModuloRede))
        for modelo, total in antes.items()
    }
    assert _contagens(db) == esperado
    conta = db.scalar(select(Usuario).where(Usuario.username == demo.USERNAME))
    return conta, senha


def _url(rede_id: int) -> str:
    return f"/api/v1/redes/{rede_id}/demonstracao-caragua"


def _cliente(conta: Usuario) -> TestClient:
    token = criar_token(conta.id, conta.token_version)
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def test_login_real_e_contrato_sintetico_sem_escrever(db, cenario):
    conta, senha = cenario
    cliente = TestClient(app)
    resposta = cliente.post("/api/v1/auth/login", data={
        "username": "@IFSP2026SEC", "password": senha,
    })
    assert resposta.status_code == 200
    cliente.headers["Authorization"] = f"Bearer {resposta.json()['access_token']}"
    antes = _contagens(db)

    assert cliente.get("/api/v1/redes").json() == [{
        "id": conta.rede_id, "nome": demo.NOME_REDE, "uf": None,
        "codigo_ibge": None, "codigo_municipio_estadual": None,
    }]
    resposta = cliente.get(_url(conta.rede_id))
    assert resposta.status_code == 200
    assert resposta.headers["Cache-Control"] == "private, no-store"
    dados = resposta.json()
    assert set(dados) == {"escolas", "regioes", "avaliacoes"}
    escolas = {escola["id"]: escola for escola in dados["escolas"]}
    assert len(escolas) == len(dados["escolas"])
    assert Counter(e["regiao"] for e in escolas.values()) == {
        "norte": 3, "centro": 3, "sul": 3, "serra": 1,
    }
    assert {r["id"] for r in dados["regioes"]} == {e["regiao"] for e in escolas.values()}
    for escola in escolas.values():
        assert "Fictícia" in escola["nome"]
        assert -23.76 < escola["latitude"] < -23.48
        assert -45.72 < escola["longitude"] < -45.25
        assert 0 <= escola["com_dados"] <= escola["matriculados"]
        assert (escola["nota"] is None) == (escola["com_dados"] == 0)

    chaves = {(a["escola_id"], a["avaliacao"], a["edicao"], a["serie"], a["disciplina"])
              for a in dados["avaliacoes"]}
    assert len(chaves) == len(dados["avaliacoes"]) == 6 * len(escolas)
    for escola_id in escolas:
        assert {(a["avaliacao"], a["edicao"]) for a in dados["avaliacoes"]
                if a["escola_id"] == escola_id} == {("SARESP", 2024), ("SARESP", 2025), ("SAEB", 2023)}
    assert _contagens(db) == antes


def test_nega_anonimo_ou_outra_rede(db, cenario):
    conta, _ = cenario
    outra = Rede(nome="Rede Fictícia de Controle")
    db.add(outra)
    db.flush()
    secretaria_outra = Usuario(
        nome="Secretaria Fictícia de Controle", email="controle@constela.invalid",
        cargo="coordenador", rede_id=outra.id, senha_hash="sem-login",
    )
    db.add(secretaria_outra)
    db.commit()

    assert TestClient(app).get(_url(conta.rede_id)).status_code == 401
    assert _cliente(conta).get(_url(outra.id)).status_code == 403
    assert _cliente(secretaria_outra).get(_url(conta.rede_id)).status_code == 403


@pytest.mark.parametrize("restricao", [
    "global", "escola", "username", "sem_marcador", "marcador_inativo",
    "rede_inativa", "rede_descaracterizada", "escola_na_rede",
])
def test_nega_se_faltar_qualquer_condicao(db, cenario, restricao):
    conta, _ = cenario
    rede_id = conta.rede_id
    if restricao == "global":
        conta.is_global = True
    elif restricao in {"escola", "escola_na_rede"}:
        escola = Escola(nome="Escola Fictícia de Controle",
                        rede_id=rede_id if restricao == "escola_na_rede" else None)
        db.add(escola)
        db.flush()
        if restricao == "escola":
            conta.escola_id = escola.id
    elif restricao == "username":
        conta.username = "secretaria-ficticia-de-controle"
    elif restricao in {"sem_marcador", "marcador_inativo"}:
        marcador = db.scalar(select(ModuloRede).where(demo.marcador_da_rede(rede_id)))
        if restricao == "sem_marcador":
            db.delete(marcador)
        else:
            marcador.ativo = False
    else:
        rede = db.get(Rede, rede_id)
        if restricao == "rede_inativa":
            rede.status = "inativa"
        else:
            rede.codigo_ibge = "3599901"
    db.commit()

    assert _cliente(conta).get(_url(rede_id)).status_code == 403


def test_rede_demo_so_leitura_e_conta_imovel(db, cenario):
    conta, _ = cenario
    outra = Rede(nome="Rede Fictícia de Controle")
    global_ = Usuario(nome="Admin Fictício", email="admin-demo-teste@constela.invalid",
                      cargo="admin", is_global=True, senha_hash="sem-login")
    db.add_all([outra, global_])
    db.commit()

    caminho = f"/api/v1/redes/{conta.rede_id}"
    cliente = _cliente(conta)
    admin = _cliente(global_)
    assert cliente.put(f"{caminho}/publico", json={"ativo": True}).status_code == 403
    assert cliente.put(f"{caminho}/metas", json={"metrica": "adocao", "alvo": 80}).status_code == 403
    assert cliente.delete(f"{caminho}/metas/adocao").status_code == 403
    assert admin.patch(caminho, json={"codigo_ibge": "3599901"}).status_code == 403
    assert admin.put(f"{caminho}/escolas", json={"escola_ids": []}).status_code == 403
    assert admin.put(f"{caminho}/usuarios", json={"usuario_ids": []}).status_code == 403
    assert admin.put(f"/api/v1/redes/{outra.id}/usuarios",
                     json={"usuario_ids": [conta.id]}).status_code == 403


def test_provisionamento_idempotente_e_revogacao_escopada(db, cenario):
    conta, _ = cenario
    outro = Usuario(nome="Usuário Fictício de Controle", email="outro@constela.invalid",
                    senha_hash="sem-login", cargo="coordenador")
    db.add(outro)
    db.commit()
    cliente = _cliente(conta)
    antes = _contagens(db)
    assert not provisionar(db, lambda: pytest.fail("não deve solicitar uma nova senha"))
    db.commit()

    assert revogar(db)
    db.commit()
    assert cliente.get(_url(conta.rede_id)).status_code == 401
    assert conta.status == "inativo"
    assert outro.status == "ativo"
    assert not revogar(db)
    db.commit()
    with pytest.raises(ValueError, match="revogado"):
        provisionar(db, lambda: pytest.fail("não deve recriar uma conta revogada"))
    db.rollback()
    assert _contagens(db) == antes


@pytest.mark.parametrize("tipo", ["rede", "conta", "marcador"])
def test_provisionamento_recusa_colisoes_sem_escrever(db, tipo):
    if tipo == "rede":
        db.add(Rede(nome=demo.NOME_REDE))
    elif tipo == "conta":
        db.add(Usuario(nome="Conta Fictícia de Controle", email="outra@constela.invalid",
                       username="IFSP2026SEC", senha_hash="sem-login", cargo="professor"))
    else:
        rede = Rede(nome="Rede Fictícia de Controle")
        db.add(rede)
        db.flush()
        db.add(ModuloRede(rede_id=rede.id, modulo=demo.MODULO, ativo=False))
    db.commit()
    antes = _contagens(db)

    with pytest.raises(ValueError, match="colisão"):
        provisionar(db, lambda: pytest.fail("não deve solicitar senha em colisão"))
    db.rollback()
    assert _contagens(db) == antes
