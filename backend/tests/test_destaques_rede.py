"""ESCOLAS EM DESTAQUE no Panorama da Rede (``GET /redes/{id}/destaques``).

São as MESMAS escolas da vitrine pública (``GET /publico/rede/{token}``), pelo
mesmo critério e pela mesma função (``rede._top_escolas``), agora com o
``escola_id`` para a tela levar à ficha de cada escola. Travado aqui:

* a lista e a ordem são as da vitrine quando nada está escondido;
* escola inativa fica fora;
* o k mínimo (5) de quem concorre (1º ao 5º ano) e de quem soma no per capita;
* só as matérias contratadas (a outra sai ``null``);
* para a Secretaria, a escola cuja matéria está escondida no cartão dela (grupo
  pequeno) sai da lista e entra em ``fora_por_protecao``; o Admin Global recebe
  a lista inteira;
* 403 para a coordenação da escola, a professora e a Secretaria de outra rede;
* nenhum nome de criança na resposta.

Dados 100% fictícios."""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_senha
from app.main import app
from app.models import (Aluno, Importacao, ModuloRede, SnapshotElefante, SnapshotMatific,
                        Usuario)
from app.services import grupo_pequeno
from app.services.analise import K_MINIMO
from tests.test_analise_base import MUN_VIZINHO, nova_escola, nova_rede, turma_com_alunos

API = "/api/v1"
_SENHA = "s3nh4destaques"
QUANDO = datetime(2026, 9, 30, 3, 0)          # coleta dentro do ano letivo de 2026
MATERIAS = {"leitura": "top_leitura", "matematica": "top_matematica"}


def _login(email: str) -> TestClient:
    c = TestClient(app)
    r = c.post(f"{API}/auth/login", data={"username": email, "password": _SENHA})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _escola(db, rede, nome, criancas, *, status="ativa"):
    """Escola com uma turma do 3º ano (concorre). ``criancas`` = lista de
    (livros, estrelas, tempo) de cada criança, com retrato das duas plataformas
    (o tempo de leitura é o que decide o grupo pequeno no cenário próprio)."""
    escola = nova_escola(db, rede, nome, None)
    escola.status = status
    alunos = turma_com_alunos(db, escola, "3º Ano", len(criancas))
    imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    for aluno, (livros, estrelas, tempo) in zip(alunos, criancas):
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                                data_referencia=QUANDO, livros_unicos=livros,
                                tempo_leitura_min=tempo, questoes_tentativas=0,
                                questoes_acertos=0, livros_por_nivel={}))
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
                               data_referencia=QUANDO, atividades=10 if estrelas else 0,
                               estrelas=estrelas))
    db.flush()
    return escola


def _iguais(n, livros, estrelas):
    """``n`` crianças com os mesmos números (o per capita é o de cada uma)."""
    return [(livros, estrelas, 10 * livros)] * n


def _contas(db, rede, escola, *, extras=False):
    """Secretaria da rede (cargo coordenador + rede, como em produção) e Admin
    Global; com ``extras``, também a coordenação e a professora da escola e a
    Secretaria de OUTRA rede."""
    contas = [Usuario(escola_id=None, nome="SEC", email="sec@destaques.local",
                      senha_hash=hash_senha(_SENHA), cargo="coordenador", rede_id=rede.id),
              Usuario(escola_id=escola.id, nome="GLOBAL", email="global@destaques.local",
                      senha_hash=hash_senha(_SENHA), cargo="admin", is_global=True)]
    if extras:
        outra = nova_rede(db, nome="Rede Fictícia Vizinha", codigo=MUN_VIZINHO, codmun="9992")
        contas += [
            Usuario(escola_id=escola.id, nome="COORD", email="coord@destaques.local",
                    senha_hash=hash_senha(_SENHA), cargo="coordenador"),
            Usuario(escola_id=escola.id, nome="PROF", email="prof@destaques.local",
                    senha_hash=hash_senha(_SENHA), cargo="professor"),
            Usuario(escola_id=None, nome="SEC OUTRA", email="outra@destaques.local",
                    senha_hash=hash_senha(_SENHA), cargo="coordenador", rede_id=outra.id),
        ]
    db.add_all(contas)
    db.commit()
    return {u.email.split("@")[0]: _login(u.email) for u in contas}


def _destaques(cliente, rede):
    r = cliente.get(f"{API}/redes/{rede.id}/destaques")
    assert r.status_code == 200, r.text
    return r.json()


def _vitrine(token):
    r = TestClient(app).get(f"{API}/publico/rede/{token}")        # SEM login
    assert r.status_code == 200, r.text
    return r.json()


def _nomes_e_valores(lista):
    return [(e["nome"], e["valor"]) for e in lista]


# ---------------------------------------------------------------------------
# Rede principal: 6 escolas ativas que entram, e as que o critério deixa fora
# ---------------------------------------------------------------------------

@pytest.fixture()
def rede_principal(db):
    rede = nova_rede(db)
    rede.token_publico = "destaquesVitrine01"
    escolas = {
        "aurora": _escola(db, rede, "EMEF Fictícia Aurora", _iguais(6, 9, 30)),
        # Bosque e Cais empatam na leitura (7,0): o desempate é o nome.
        "cais": _escola(db, rede, "EMEF Fictícia Cais", _iguais(6, 7, 10)),
        "bosque": _escola(db, rede, "EMEF Fictícia Bosque", _iguais(6, 7, 50)),
        "duna": _escola(db, rede, "EMEF Fictícia Duna", _iguais(6, 5, 40)),
        "enseada": _escola(db, rede, "EMEF Fictícia Enseada", _iguais(6, 4, 20)),
        # 6ª na leitura (fica fora do limite de 5) e 1ª na matemática.
        "farol": _escola(db, rede, "EMEF Fictícia Farol", _iguais(6, 3, 60)),
        # As maiores da rede, mas o critério as deixa fora:
        "inativa": _escola(db, rede, "EMEF Fictícia Inativa", _iguais(6, 50, 500),
                           status="inativa"),
        "quatro": _escola(db, rede, "EMEF Fictícia Quatro", _iguais(4, 40, 400)),
        "poucos": _escola(db, rede, "EMEF Fictícia Poucos Somam",
                          _iguais(4, 40, 400) + _iguais(2, 0, 0)),
        "zerada": _escola(db, rede, "EMEF Fictícia Zerada", _iguais(6, 0, 0)),
    }
    db.commit()
    return {"db": db, "rede": rede, "escolas": escolas,
            **_contas(db, rede, escolas["aurora"])}


ESPERADO_PRINCIPAL = {
    "leitura": [("EMEF Fictícia Aurora", 9.0), ("EMEF Fictícia Bosque", 7.0),
                ("EMEF Fictícia Cais", 7.0), ("EMEF Fictícia Duna", 5.0),
                ("EMEF Fictícia Enseada", 4.0)],
    "matematica": [("EMEF Fictícia Farol", 60.0), ("EMEF Fictícia Bosque", 50.0),
                   ("EMEF Fictícia Duna", 40.0), ("EMEF Fictícia Aurora", 30.0),
                   ("EMEF Fictícia Enseada", 20.0)],
}


@pytest.mark.parametrize("perfil", ["sec", "global"])
def test_destaques_sao_os_da_vitrine_publica_com_escola_id(rede_principal, perfil):
    corpo = _destaques(rede_principal[perfil], rede_principal["rede"])
    vitrine = _vitrine("destaquesVitrine01")
    assert corpo["modulos"] == ["leitura", "matematica"] == vitrine["modulos"]
    assert corpo["limite"] == 5 and corpo["k_minimo"] == K_MINIMO == 5
    ids = {e.nome: e.id for e in rede_principal["escolas"].values()}
    for materia, chave_vitrine in MATERIAS.items():
        bloco = corpo[materia]
        # A MESMA lista, na MESMA ordem e com os mesmos valores da vitrine.
        assert _nomes_e_valores(bloco["escolas"]) == ESPERADO_PRINCIPAL[materia]
        assert _nomes_e_valores(bloco["escolas"]) == _nomes_e_valores(vitrine[chave_vitrine])
        # ...com o escola_id de cada uma (a vitrine sem login continua sem ele).
        assert [e["escola_id"] for e in bloco["escolas"]] == [
            ids[nome] for nome, _ in ESPERADO_PRINCIPAL[materia]]
        assert all(set(e) == {"nome", "valor"} for e in vitrine[chave_vitrine])
        assert bloco["fora_por_protecao"] == 0


@pytest.mark.parametrize("perfil", ["sec", "global"])
def test_destaques_deixam_a_escola_inativa_de_fora(rede_principal, perfil):
    rede, inativa = rede_principal["rede"], rede_principal["escolas"]["inativa"]
    corpo = _destaques(rede_principal[perfil], rede)
    for materia in MATERIAS:
        assert inativa.id not in [e["escola_id"] for e in corpo[materia]["escolas"]]
        assert corpo[materia]["fora_por_protecao"] == 0    # inativa não é proteção
    # É o cadastro que a deixa fora: reativada, ela lidera as duas listas.
    db = rede_principal["db"]
    inativa.status = "ativa"
    db.commit()
    corpo = _destaques(rede_principal[perfil], rede)
    for materia in MATERIAS:
        assert corpo[materia]["escolas"][0]["escola_id"] == inativa.id
        assert len(corpo[materia]["escolas"]) == 5


@pytest.mark.parametrize("perfil", ["sec", "global"])
def test_destaques_respeitam_o_k_minimo_e_o_valor_acima_de_zero(rede_principal, perfil):
    corpo = _destaques(rede_principal[perfil], rede_principal["rede"])
    fora = {rede_principal["escolas"][e].id for e in ("quatro", "poucos", "zerada")}
    for materia in MATERIAS:
        assert not fora & {e["escola_id"] for e in corpo[materia]["escolas"]}
        # Ficar fora pelo k (ou por não ter valor) não é "fora por proteção".
        assert corpo[materia]["fora_por_protecao"] == 0


def test_destaques_entram_com_exatamente_k_criancas_que_somam(db):
    rede = nova_rede(db)
    cinco = _escola(db, rede, "EMEF Fictícia Cinco", _iguais(5, 2, 20))
    _escola(db, rede, "EMEF Fictícia Quatro", _iguais(4, 40, 400))
    # 6 que concorrem, só 4 somam (4 ≥ 3: não é grupo pequeno, mas é menos que k).
    _escola(db, rede, "EMEF Fictícia Poucos Somam", _iguais(4, 40, 400) + _iguais(2, 0, 0))
    db.commit()
    contas = _contas(db, rede, cinco)
    for perfil in ("sec", "global"):
        corpo = _destaques(contas[perfil], rede)
        assert corpo["leitura"] == {"escolas": [{"escola_id": cinco.id,
                                                 "nome": "EMEF Fictícia Cinco",
                                                 "valor": 2.0}],
                                    "fora_por_protecao": 0}, perfil
        assert corpo["matematica"] == {"escolas": [{"escola_id": cinco.id,
                                                    "nome": "EMEF Fictícia Cinco",
                                                    "valor": 20.0}],
                                       "fora_por_protecao": 0}, perfil


# ---------------------------------------------------------------------------
# Módulos contratados
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("desligado,ligado", [("matematica", "leitura"),
                                              ("leitura", "matematica")])
def test_destaques_so_da_materia_contratada(db, desligado, ligado):
    rede = nova_rede(db)
    rede.token_publico = "destaquesModulo01"
    escola = _escola(db, rede, "EMEF Fictícia Contratada", _iguais(6, 4, 40))
    db.add(ModuloRede(rede_id=rede.id, modulo=desligado, ativo=False))
    db.commit()
    contas = _contas(db, rede, escola)
    vitrine = _vitrine("destaquesModulo01")
    for perfil in ("sec", "global"):
        corpo = _destaques(contas[perfil], rede)
        assert corpo["modulos"] == [ligado]
        # A matéria fora do contrato não existe para a rede: null, não lista vazia.
        assert corpo[desligado] is None
        assert [e["escola_id"] for e in corpo[ligado]["escolas"]] == [escola.id]
        assert _nomes_e_valores(corpo[ligado]["escolas"]) == _nomes_e_valores(
            vitrine[MATERIAS[ligado]])
    assert vitrine[MATERIAS[desligado]] == []


@pytest.mark.parametrize("desligado", [None, "matematica"])
def test_materia_contratada_sem_escola_elegivel_vem_lista_vazia_nao_null(db, desligado):
    """Contratada, mas NENHUMA escola passa no critério (valor zero, menos de k
    crianças, inativa): a matéria vem ``{escolas: [], fora_por_protecao: 0}`` —
    a tela escreve "nenhuma escola com dados suficientes" —, nunca ``null``, que
    quer dizer "não contratada"."""
    rede = nova_rede(db)
    rede.token_publico = "destaquesVazio001"
    zerada = _escola(db, rede, "EMEF Fictícia Zerada", _iguais(6, 0, 0))
    _escola(db, rede, "EMEF Fictícia Quatro", _iguais(4, 40, 400))
    _escola(db, rede, "EMEF Fictícia Inativa", _iguais(6, 50, 500), status="inativa")
    if desligado:
        db.add(ModuloRede(rede_id=rede.id, modulo=desligado, ativo=False))
    db.commit()
    contas = _contas(db, rede, zerada)
    contratadas = [m for m in MATERIAS if m != desligado]
    vitrine = _vitrine("destaquesVazio001")
    for perfil in ("sec", "global"):
        corpo = _destaques(contas[perfil], rede)
        assert corpo["modulos"] == contratadas, perfil
        for materia in contratadas:
            # Lista vazia, sem ninguém "fora por proteção": quem ficou fora ficou pelo
            # critério da vitrine (que também não mostra ninguém).
            assert corpo[materia] == {"escolas": [], "fora_por_protecao": 0}, (perfil, materia)
            assert vitrine[MATERIAS[materia]] == []
        if desligado:
            assert corpo[desligado] is None, perfil


# ---------------------------------------------------------------------------
# Grupo pequeno: a Secretaria não recebe no destaque o que o cartão esconde
# ---------------------------------------------------------------------------

@pytest.fixture()
def rede_protegida(db):
    rede = nova_rede(db)
    rede.token_publico = "destaquesProtecao1"
    # 6 crianças leram, mas só 1 tem tempo de leitura: para a Secretaria a
    # leitura da escola é grupo pequeno (o total de tempo seria o dela). A
    # matemática segue visível.
    protegida = _escola(db, rede, "EMEF Fictícia Protegida",
                        [(9, 30, 47)] + [(9, 30, 0)] * 5)
    visiveis = [_escola(db, rede, f"EMEF Fictícia Visível {letra}", _iguais(6, livros, 10))
                for letra, livros in (("A", 8), ("B", 7), ("C", 6), ("D", 5), ("E", 4))]
    # Escondida também, mas fora das 5 primeiras: não conta como "fora".
    setima = _escola(db, rede, "EMEF Fictícia Protegida Sétima",
                     [(2, 5, 30)] + [(2, 5, 0)] * 5)
    db.commit()
    return {"db": db, "rede": rede, "protegida": protegida, "visiveis": visiveis,
            "setima": setima, **_contas(db, rede, protegida)}


def test_secretaria_nao_ve_no_destaque_a_escola_com_a_leitura_escondida(rede_protegida):
    rede, protegida = rede_protegida["rede"], rede_protegida["protegida"]
    # O cartão da Secretaria esconde a leitura dessa escola (o mesmo /dashboard).
    painel = rede_protegida["sec"].get(f"{API}/redes/{rede.id}/dashboard").json()
    cartao = next(c for c in painel["escolas"] if c["escola_id"] == protegida.id)
    assert cartao["oculto"]["leitura"]["motivo"] == grupo_pequeno.MOTIVO_GRUPO_PEQUENO
    assert cartao["livros_por_matricula"] is None
    assert cartao["oculto"]["matematica"] is None

    corpo = _destaques(rede_protegida["sec"], rede)
    vitrine = _vitrine("destaquesProtecao1")
    a, b, c, d, _ = rede_protegida["visiveis"]
    # Leitura: a lista da vitrine SEM a escola escondida (não é completada com a 6ª).
    assert [e["escola_id"] for e in corpo["leitura"]["escolas"]] == [a.id, b.id, c.id, d.id]
    assert corpo["leitura"]["fora_por_protecao"] == 1
    assert _nomes_e_valores(corpo["leitura"]["escolas"]) == [
        par for par in _nomes_e_valores(vitrine["top_leitura"])
        if par[0] != "EMEF Fictícia Protegida"]
    # Matemática visível: a escola continua no destaque.
    assert protegida.id in [e["escola_id"] for e in corpo["matematica"]["escolas"]]
    assert corpo["matematica"]["fora_por_protecao"] == 0
    assert _nomes_e_valores(corpo["matematica"]["escolas"]) == _nomes_e_valores(
        vitrine["top_matematica"])


def test_admin_global_recebe_o_destaque_sem_a_exclusao(rede_protegida):
    rede, protegida = rede_protegida["rede"], rede_protegida["protegida"]
    corpo = _destaques(rede_protegida["global"], rede)
    a, b, c, d, _ = rede_protegida["visiveis"]
    assert [e["escola_id"] for e in corpo["leitura"]["escolas"]] == [
        protegida.id, a.id, b.id, c.id, d.id]
    assert corpo["leitura"]["escolas"][0]["valor"] == 9.0
    assert corpo["leitura"]["fora_por_protecao"] == 0
    assert corpo["matematica"]["fora_por_protecao"] == 0
    assert _nomes_e_valores(corpo["leitura"]["escolas"]) == _nomes_e_valores(
        _vitrine("destaquesProtecao1")["top_leitura"])


# ---------------------------------------------------------------------------
# Acesso e privacidade
# ---------------------------------------------------------------------------

def test_destaques_403_para_coordenacao_professora_e_outra_rede(db):
    rede = nova_rede(db)
    escola = _escola(db, rede, "EMEF Fictícia Acesso", _iguais(6, 3, 30))
    db.commit()
    contas = _contas(db, rede, escola, extras=True)
    url = f"{API}/redes/{rede.id}/destaques"
    for perfil in ("coord", "prof", "outra"):
        assert contas[perfil].get(url).status_code == 403, perfil
    for perfil in ("sec", "global"):
        assert contas[perfil].get(url).status_code == 200, perfil


@pytest.mark.parametrize("perfil", ["sec", "global"])
def test_destaques_sem_nome_de_crianca(rede_principal, perfil):
    db, rede = rede_principal["db"], rede_principal["rede"]
    r = rede_principal[perfil].get(f"{API}/redes/{rede.id}/destaques")
    assert r.status_code == 200, r.text
    corpo = r.json()
    # O contrato inteiro: nada além de escola, nome da escola e valor.
    assert set(corpo) == {"modulos", "limite", "k_minimo", "leitura", "matematica"}
    for materia in MATERIAS:
        assert set(corpo[materia]) == {"escolas", "fora_por_protecao"}
        for linha in corpo[materia]["escolas"]:
            assert set(linha) == {"escola_id", "nome", "valor"}
    texto = r.text.casefold()
    nomes = db.execute(select(Aluno.nome)).scalars().all()
    assert nomes
    for nome in nomes:
        assert nome.casefold() not in texto
    assert "criança" not in texto
