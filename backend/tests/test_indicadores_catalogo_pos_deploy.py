"""O catálogo logo depois do deploy: as linhas 'ica' e 'iee' AINDA NÃO existem.

O GET /avaliacoes não cria as linhas de ``SO_REFERENCIA`` (o ICA e o IEE): elas nascem
só na prévia da importação própria (``obter_avaliacao`` no pipeline do ICA e no da
SEDUC). Os testes da descida da 0034 provam isso chamando a função da rota; aqui a prova
é pela API (TestClient, com login), num banco migrado pelo MESMO caminho do deploy
(``aplicar_migracoes``, o que ``scripts.migrate`` roda), nos dois pontos de partida:

* ``vazio`` — instalação nova (o catálogo nasce vazio);
* ``seis_originais_na_0033`` — como a produção: o banco na 0033 já tem as seis linhas
  originais (criadas pelo GET do código antigo) e só então sobe até as heads.

O que fica provado:

1. nenhuma leitura depende das linhas existirem: GET /avaliacoes, os presets, as opções e
   a correlação da rede, a leitura da rede (ICA, SARESP, Ideb), as listas de importação
   das QUATRO famílias e a leitura da escola respondem 200 a quem lê e 403 a quem não lê
   (a matriz de sempre) — e nenhuma leitura cria 'ica' ou 'iee';
2. a prévia NEGADA (Secretaria e coordenador: 403) ou RECUSADA (400) não as cria;
3. a prévia do ICA cria 'ica' e a do SARESP/IEE cria 'iee', na hora;
4. depois disso o GET /avaliacoes devolve EXATAMENTE a mesma resposta (o seletor da
   importação manual não ganha o ICA nem o IEE) e as leituras seguem com o mesmo status.

Variante PostgreSQL com o marcador ``postgres`` (pula sem ``TEST_DATABASE_URL_PG``).
FIXTURES SINTÉTICAS (decisão D13): a rede, os INEPs, os usuários e os arquivos são os
INVENTADOS dos testes da E2 e da E4.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.core.database import get_db
from app.core.migracoes import aplicar_migracoes
from app.core.security import hash_senha
from app.main import app
from app.models import AvaliacaoExterna, Escola, Rede, Usuario
from app.services import avaliacoes as svc
from tests.test_indicadores_ica import arq_mun_2025
from tests.test_indicadores_saresp import CODMUN, MUN, _iee
from tests.test_migracoes_postgres import (REVISAO_0033, _inserir, _migrar,  # noqa: F401
                                           engine_postgres)

SENHA = "s3nh4posdeploy"                     # INVENTADA
NOME_ICA = "resultados_e_metas_municipios_2025_3.xlsx"
NOME_IEE = "Indice de Excelencia Educacional 2025-2026_0.csv"
PERFIS = ("global", "secretaria", "coordenador")
ORIGINAIS = set(svc.CATALOGO) - svc.SO_REFERENCIA
PONTOS_DE_PARTIDA = ("vazio", "seis_originais_na_0033")

# Quem lê o quê (global, Secretaria da rede, coordenador da escola ALFA) — a matriz das
# decisões D4/D5, que o catálogo sem 'ica'/'iee' não pode mudar.
ESPERADO = {
    "/avaliacoes": (200, 200, 200),
    "/avaliacoes/presets-import": (200, 200, 200),
    "/redes/{rede}/avaliacoes/opcoes": (200, 200, 403),
    # A correlação procura a avaliação pedida com ``obter_avaliacao`` (que cria a linha
    # na sessão), mas a rota não grava: pedir o ICA ou o IEE ali não pode criá-los.
    "/redes/{rede}/avaliacoes/correlacao?avaliacao=ica&indicador=taxa_inventada&edicao=2025":
        (200, 200, 403),
    "/redes/{rede}/avaliacoes/correlacao?avaliacao=iee&indicador=taxa_inventada&edicao=2025":
        (200, 200, 403),
    "/redes/{rede}/indicadores/ica": (200, 200, 403),
    "/redes/{rede}/indicadores/saresp": (200, 200, 403),
    "/redes/{rede}/indicadores/ideb": (200, 200, 403),
    "/redes/{rede}/indicadores/importacoes": (200, 403, 403),           # ICA
    "/redes/{rede}/indicadores/saresp/importacoes": (200, 403, 403),
    "/redes/{rede}/indicadores/ideb/importacoes": (200, 403, 403),
    "/redes/{rede}/indicadores/saeb/importacoes": (200, 403, 403),
    "/escolas/{alfa}/indicadores": (200, 200, 200),
}


def _subir(engine, ponto_de_partida: str) -> None:
    """Leva o banco às heads pelo caminho do deploy, a partir do ponto pedido."""
    if ponto_de_partida == "seis_originais_na_0033":
        _migrar(engine, REVISAO_0033)
        with engine.begin() as c:
            meta = MetaData()
            meta.reflect(bind=c)
            for chave in sorted(ORIGINAIS):
                m = svc.CATALOGO[chave]
                _inserir(c, meta, "avaliacoes_externas", chave=chave, nome=m["nome"],
                         tipo=m["tipo"], orgao=m["orgao"], descricao=m["descricao"])
    aplicar_migracoes(engine)


def _chaves(engine) -> set[str]:
    with engine.connect() as c:
        return set(c.execute(select(AvaliacaoExterna.chave)).scalars())


def _montar(engine) -> dict:
    """Rede sintética com duas escolas e um usuário de cada perfil; a API usa ESTE banco."""
    Sessao = sessionmaker(bind=engine)

    def _get_db():
        sessao = Sessao()
        try:
            yield sessao
        finally:
            sessao.close()

    app.dependency_overrides[get_db] = _get_db
    with Sessao() as db:
        rede = Rede(nome="Rede Sintética", uf="SP", codigo_ibge=MUN,
                    codigo_municipio_estadual=CODMUN, status="ativa")
        db.add(rede)
        db.flush()
        alfa = Escola(nome="EMEF Sintética Alfa", ano_letivo_ativo=2026, rede_id=rede.id,
                      codigo_inep="35990001")
        beta = Escola(nome="EMEF Sintética Beta", ano_letivo_ativo=2026, rede_id=rede.id,
                      codigo_inep="35990002")
        db.add_all([alfa, beta])
        db.flush()
        campos = {"global": {"cargo": "admin", "is_global": True},
                  "secretaria": {"cargo": "coordenador", "rede_id": rede.id},
                  "coordenador": {"cargo": "coordenador", "escola_id": alfa.id}}
        hash_ = hash_senha(SENHA)
        for perfil in PERFIS:
            db.add(Usuario(nome=perfil, email=f"{perfil}@pos-deploy.local", senha_hash=hash_,
                           **campos[perfil]))
        db.commit()
        ids = {"rede": rede.id, "alfa": alfa.id}
    clientes = {}
    for perfil in PERFIS:
        c = TestClient(app)
        r = c.post("/api/v1/auth/login",
                   data={"username": f"{perfil}@pos-deploy.local", "password": SENHA})
        assert r.status_code == 200, r.text
        c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        clientes[perfil] = c
    return {**ids, "c": clientes}


def _ler_tudo(mundo) -> dict[str, tuple[int, ...]]:
    """Status de cada leitura em cada perfil; confere com a matriz ESPERADO."""
    status = {}
    for rota, esperado in ESPERADO.items():
        url = "/api/v1" + rota.format(rede=mundo["rede"], alfa=mundo["alfa"])
        respostas = [mundo["c"][perfil].get(url) for perfil in PERFIS]
        status[rota] = tuple(r.status_code for r in respostas)
        assert status[rota] == esperado, (rota, [(r.status_code, r.text[:300])
                                                 for r in respostas])
    return status


def _previa(mundo, perfil: str, familia: str):
    nome, conteudo = (NOME_ICA, arq_mun_2025()) if familia == "ica" else (NOME_IEE, _iee())
    return mundo["c"][perfil].post(
        f"/api/v1/redes/{mundo['rede']}/indicadores/{familia}/previa",
        files={"arquivo": (nome, conteudo)})


def _cenario(engine, ponto_de_partida: str) -> None:
    """O banco já subiu às heads (``_subir``) a partir de ``ponto_de_partida``."""
    assert _chaves(engine) == (set() if ponto_de_partida == "vazio" else ORIGINAIS)
    try:
        mundo = _montar(engine)   # dentro do try: o override do get_db sempre sai
        # (1) Leituras com o catálogo SEM 'ica'/'iee': 200/403 como sempre, sem criá-las.
        # O GET /avaliacoes cria as originais que faltarem (como o código antigo), só elas.
        antes = _ler_tudo(mundo)
        assert _chaves(engine) == ORIGINAIS
        catalogo = mundo["c"]["global"].get("/api/v1/avaliacoes").json()
        assert {i["chave"] for i in catalogo} == ORIGINAIS
        ica = mundo["c"]["secretaria"].get(
            f"/api/v1/redes/{mundo['rede']}/indicadores/ica").json()
        assert ica["tem_dados"] is False and ica["fontes"] == []     # vazio, nunca 0
        escola = mundo["c"]["coordenador"].get(
            f"/api/v1/escolas/{mundo['alfa']}/indicadores").json()
        assert escola["tem_dados"] is False and escola["tem_dados_escola"] is False

        # (2) A prévia negada (403) ou recusada (400: arquivo que não é o oficial) não
        # cria nada — a rota desfaz a transação da recusa.
        for perfil in ("secretaria", "coordenador"):
            for familia in ("ica", "saresp"):
                assert _previa(mundo, perfil, familia).status_code == 403
        for familia in ("ica", "saresp"):
            r = mundo["c"]["global"].post(
                f"/api/v1/redes/{mundo['rede']}/indicadores/{familia}/previa",
                files={"arquivo": ("arquivo.csv", b"nada a ver")})
            assert r.status_code == 400, r.text
        assert _chaves(engine) == ORIGINAIS

        # (3) A prévia do admin global cria a linha na hora — e só a dela.
        r = _previa(mundo, "global", "ica")
        assert r.status_code == 200, r.text
        assert _chaves(engine) == ORIGINAIS | {"ica"}
        r = _previa(mundo, "global", "saresp")
        assert r.status_code == 200, r.text
        assert _chaves(engine) == ORIGINAIS | {"ica", "iee"}

        # (4) O seletor da importação manual não muda; as leituras seguem iguais.
        for perfil in PERFIS:
            assert mundo["c"][perfil].get("/api/v1/avaliacoes").json() == catalogo
        assert _ler_tudo(mundo) == antes
        assert _chaves(engine) == ORIGINAIS | {"ica", "iee"}
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.parametrize("ponto_de_partida", PONTOS_DE_PARTIDA)
def test_catalogo_sem_ica_iee_depois_do_deploy_no_sqlite(tmp_path, ponto_de_partida):
    url = f"sqlite:///{tmp_path / 'pos_deploy.db'}"
    migracao = create_engine(url)
    try:
        _subir(migracao, ponto_de_partida)
    finally:
        migracao.dispose()
    # A API usa um engine com a integridade referencial LIGADA, como o da aplicação.
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _rec):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    try:
        _cenario(engine, ponto_de_partida)
    finally:
        engine.dispose()


@pytest.mark.postgres
@pytest.mark.parametrize("ponto_de_partida", PONTOS_DE_PARTIDA)
def test_catalogo_sem_ica_iee_depois_do_deploy_no_postgres(engine_postgres, ponto_de_partida):
    _subir(engine_postgres, ponto_de_partida)
    _cenario(engine_postgres, ponto_de_partida)
