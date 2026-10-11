"""GET /escolas/{id}/configuracoes/pontuacao/regra — a regra da nota como o MOTOR
a aplica nesta escola, para a explicação do Suporte e do "Como funciona?".

Trava:
  * os pesos devolvidos SÃO os de ``scoring.pesos_efetivos`` — no perfil
    institucional os fixos da rede (mesmo com configuração local diferente), no
    personalizado os da escola — e a versão da régua de dificuldade é a da
    ``regra_da_escola``;
  * a normalização declarada é a do motor (percentil e amostra mínima vêm das
    constantes de ``scoring``; modo manual só vale no perfil personalizado);
  * o módulo não contratado aparece como ``contratada: false`` (sem esconder);
  * acesso: qualquer usuário da escola lê (professor inclusive), sem login 401,
    outra escola 403; é só GET (a governança da fórmula cobre a rota).
"""
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_senha
from app.main import app
from app.models import Configuracao, Escola, ModuloRede, Rede, ReferenciaNormalizacao, Usuario
from app.services import dificuldade_livro, scoring

API = "/api/v1"


def _url(escola_id: int) -> str:
    return f"{API}/escolas/{escola_id}/configuracoes/pontuacao/regra"


def _login(email: str) -> TestClient:
    c = TestClient(app)
    r = c.post(f"{API}/auth/login", data={"username": email, "password": "s3nh4"})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _usuario(db, escola_id: int, email: str, cargo: str) -> TestClient:
    db.add(Usuario(escola_id=escola_id, nome=email.split("@")[0], email=email,
                   senha_hash=hash_senha("s3nh4"), cargo=cargo))
    db.commit()
    return _login(email)


def _pesos_locais(db, escola_id: int, namespace: str, valores: dict) -> None:
    row = db.execute(select(Configuracao).where(
        Configuracao.escola_id == escola_id, Configuracao.namespace == namespace,
        Configuracao.chave == "valores")).scalar_one_or_none()
    if row is None:
        db.add(Configuracao(escola_id=escola_id, namespace=namespace, chave="valores",
                            valor=valores))
    else:
        row.valor = valores
    db.commit()


def _referencia(db, escola_id: int, modo: str) -> None:
    ref = db.execute(select(ReferenciaNormalizacao).where(
        ReferenciaNormalizacao.escola_id == escola_id)).scalar_one_or_none()
    if ref is None:
        db.add(ReferenciaNormalizacao(escola_id=escola_id, modo=modo))
    else:
        ref.modo = modo
    db.commit()


def test_institucional_devolve_os_pesos_da_rede_mesmo_com_config_local(cliente, db,
                                                                       escola_completa):
    escola_id = escola_completa["escola"].id
    # Config local DIFERENTE: no perfil institucional o motor a ignora.
    _pesos_locais(db, escola_id, "pesos.elefante",
                  {"livros": 70.0, "dificuldade": 10.0, "questoes": 10.0, "tempo": 10.0})
    r = cliente.get(_url(escola_id))
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["perfil"] == "institucional"
    leitura, matematica = corpo["dimensoes"]
    assert leitura["pesos"] == scoring.PESOS_PADRAO["pesos.elefante"]
    assert leitura["subpesos_questoes"] == scoring.PESOS_PADRAO["pesos.questoes"]
    assert matematica["pesos"] == scoring.PESOS_PADRAO["pesos.matific"]
    for dim, ns in ((leitura, "pesos.elefante"), (matematica, "pesos.matific")):
        assert dim["pesos"] == scoring.pesos_efetivos(db, escola_id, ns)[1]
    assert corpo["versoes"] == {
        "composicao": scoring.COMPOSICAO_ATUAL,
        "dificuldade": dificuldade_livro.VERSAO_VIGENTE,
        "dificuldade_da_rede": dificuldade_livro.VERSAO_VIGENTE,
    }
    assert corpo["normalizacao"] == {
        "modo": "auto",
        "percentil_referencia": round(scoring.PERCENTIL_REFERENCIA * 100),
        "minimo_alunos_percentil": scoring.MIN_ALUNOS_ROBUSTO,
        "indicadores_volume": sorted(scoring.INDICADORES_VOLUME),
    }


def test_institucional_ignora_o_modo_manual_local(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    _referencia(db, escola_id, "manual")
    assert cliente.get(_url(escola_id)).json()["normalizacao"]["modo"] == "auto"


def test_personalizado_devolve_os_pesos_e_a_regua_da_escola(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    db.add(Configuracao(escola_id=escola_id, namespace=scoring.PERFIL_SCORING_NS,
                        chave="modo", valor="personalizado"))
    db.commit()
    locais = {"livros": 70.0, "dificuldade": 10.0, "questoes": 10.0, "tempo": 10.0}
    _pesos_locais(db, escola_id, "pesos.elefante", locais)
    _referencia(db, escola_id, "manual")
    corpo = cliente.get(_url(escola_id)).json()
    assert corpo["perfil"] == "personalizado"
    assert corpo["dimensoes"][0]["pesos"] == locais
    assert corpo["dimensoes"][0]["pesos"] == scoring.pesos_efetivos(
        db, escola_id, "pesos.elefante")[1]
    assert corpo["versoes"]["dificuldade"] == dificuldade_livro.VERSAO_LEGADA
    assert corpo["versoes"]["dificuldade_da_rede"] == dificuldade_livro.VERSAO_VIGENTE
    assert corpo["normalizacao"]["modo"] == "manual"


def test_modulo_nao_contratado_aparece_sem_esconder(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    rede = Rede(nome="Rede So Leitura")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    db.add(ModuloRede(rede_id=rede.id, modulo="leitura", ativo=True))
    db.add(ModuloRede(rede_id=rede.id, modulo="matematica", ativo=False))
    db.commit()
    leitura, matematica = cliente.get(_url(escola.id)).json()["dimensoes"]
    assert (leitura["contratada"], matematica["contratada"]) == (True, False)


def test_qualquer_usuario_da_escola_le_e_ninguem_de_fora(db, escola_completa):
    escola_id = escola_completa["escola"].id
    for email, cargo in (("prof@regra.local", "professor"), ("coord@regra.local", "coordenador")):
        assert _usuario(db, escola_id, email, cargo).get(_url(escola_id)).status_code == 200
    assert TestClient(app).get(_url(escola_id)).status_code == 401
    outra = Escola(nome="ESCOLA DE FORA", ano_letivo_ativo=2026)
    db.add(outra)
    db.commit()
    assert _usuario(db, outra.id, "fora@regra.local", "coordenador").get(
        _url(escola_id)).status_code == 403


def test_nenhuma_escrita_na_rota(cliente, escola_completa):
    url = _url(escola_completa["escola"].id)
    for metodo in (cliente.put, cliente.post, cliente.delete):
        assert metodo(url).status_code == 405
