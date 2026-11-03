"""GRUPO PEQUENO: a Secretaria não recebe o número de UMA criança pela turma.

Achado de auditoria (dados pessoais): com uma turma de 20 matriculados e só 1
aluno com retrato do Elefante, ``/resumo-escola``, ``/ranking/turmas`` e
``/comparar`` (turma×turma) entregavam à Secretaria a nota e os contadores
(livros, tempo, questões) DAQUELA criança — a média de um aluno é a nota dele.

Agora, só para a Secretaria (``permissoes.e_secretaria``), a matéria de turma
com menos de ``K_MINIMO_TURMA`` alunos aferidos sai com média e indicadores
nulos e a marca explícita; e a supressão é complementar (o total da escola
menos as turmas visíveis não refaz a turma pequena). A gestão da escola e o
Admin Global continuam vendo tudo. Dados sintéticos.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import (Aluno, Importacao, Matricula, Nota, Rede, SnapshotElefante,
                        Turma, Usuario)
from app.services import grupo_pequeno, scoring

API = "/api/v1"


def _login(email: str, senha: str = "s3nh4") -> TestClient:
    c = TestClient(app)
    r = c.post(f"{API}/auth/login", data={"username": email, "password": senha})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _perfis(db, escola):
    """Secretaria da rede (cargo coordenador + rede, o pior caso), coordenador da
    própria escola e Admin Global."""
    rede = Rede(nome="REDE_SINT_GP", status="ativa")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    db.add_all([
        Usuario(escola_id=None, nome="SEC", email="sec@gp.local",
                senha_hash=hash_senha("s3nh4"), cargo="coordenador", rede_id=rede.id),
        Usuario(escola_id=escola.id, nome="COORD", email="coord@gp.local",
                senha_hash=hash_senha("s3nh4"), cargo="coordenador"),
        Usuario(escola_id=escola.id, nome="GLOBAL", email="global@gp.local",
                senha_hash=hash_senha("s3nh4"), cargo="admin", is_global=True),
    ])
    db.commit()
    return {"sec": _login("sec@gp.local"), "coord": _login("coord@gp.local"),
            "global": _login("global@gp.local")}


# ---------------------------------------------------------------------------
# Cenário 1 — o do auditor: 20 matriculados, 1 aferido (motor de verdade)
# ---------------------------------------------------------------------------

@pytest.fixture()
def turma_de_um(db, escola_completa):
    escola = escola_completa["escola"]
    t4 = Turma(escola_id=escola.id, nome="4o Ano A", ano_escolar="4º Ano", ano_letivo=2026)
    db.add(t4)
    db.flush()
    alunos = []
    for i in range(20):
        a = Aluno(escola_id=escola.id, nome=f"ALUNO_SINT_{i:02d}")
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=t4.id, ano_letivo=2026))
        alunos.append(a)
    imp = Importacao(escola_id=escola.id, plataforma="elefante", tipo="seed")
    db.add(imp)
    db.flush()
    agora = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(SnapshotElefante(escola_id=escola.id, aluno_id=alunos[7].id, importacao_id=imp.id,
                            data_referencia=agora - timedelta(days=1),
                            livros_unicos=19, tempo_leitura_min=47,
                            questoes_tentativas=13, questoes_acertos=11,
                            livros_por_nivel={"D": 19}))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    perfis = _perfis(db, escola)
    return {"escola": escola, "t4": t4, "outra": escola_completa["turma"], **perfis}


def _linha(resposta, turma_id):
    return next(t for t in resposta.json()["turmas"] if t["turma"]["id"] == turma_id)


def test_resumo_escola_secretaria_nao_recebe_os_numeros_da_crianca(turma_de_um):
    eid, tid = turma_de_um["escola"].id, turma_de_um["t4"].id
    r = turma_de_um["sec"].get(f"{API}/escolas/{eid}/resumo-escola")
    assert r.status_code == 200, r.text
    linha = _linha(r, tid)
    # A média de um aluno seria a nota dele: nula, com a marca explícita.
    assert linha["media_leitura"] is None and linha["media_elefante"] is None
    assert linha["media_geral"] is None
    ind = linha["indicadores"]
    for chave in ("livros_unicos", "tempo_leitura_min", "questoes_tentativas",
                  "questoes_acertos"):
        assert ind[chave] is None, chave
    assert linha["grupo_pequeno"] is True
    assert linha["oculto"]["leitura"]["motivo"] == grupo_pequeno.MOTIVO_GRUPO_PEQUENO
    assert "Menos de 3 alunos com dado" in linha["oculto"]["leitura"]["texto"]
    assert linha["oculto"]["matematica"] is None
    # A contagem (não o desempenho) continua: é ela que a tela explica.
    assert linha["n_leitura"] == 1 and linha["total_alunos"] == 20
    assert "ALUNO_SINT" not in r.text


@pytest.mark.parametrize("perfil", ["coord", "global"])
def test_resumo_escola_gestao_e_admin_global_veem_tudo_como_antes(turma_de_um, perfil):
    eid, tid = turma_de_um["escola"].id, turma_de_um["t4"].id
    r = turma_de_um[perfil].get(f"{API}/escolas/{eid}/resumo-escola")
    assert r.status_code == 200, r.text
    linha = _linha(r, tid)
    assert linha["n_leitura"] == 1 and linha["media_leitura"] is not None
    ind = linha["indicadores"]
    assert (ind["livros_unicos"], ind["tempo_leitura_min"],
            ind["questoes_tentativas"], ind["questoes_acertos"]) == (19, 47, 13, 11)
    # Nenhuma chave nova para quem vê tudo.
    assert "grupo_pequeno" not in linha and "oculto" not in linha
    assert "_aferidos" not in linha


def test_ranking_turmas_secretaria_tira_a_turma_pequena_da_ordem(turma_de_um):
    eid, tid = turma_de_um["escola"].id, turma_de_um["t4"].id
    r = turma_de_um["sec"].get(f"{API}/escolas/{eid}/ranking/turmas",
                               params={"dimensao": "leitura"})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert tid not in [i["turma_id"] for i in corpo["itens"]]
    [oculta] = [o for o in corpo["ocultas"] if o["turma_id"] == tid]
    assert oculta["media"] is None and oculta["posicao"] is None
    assert oculta["grupo_pequeno"] is True and oculta["n_aferidos"] == 1
    assert oculta["motivo"] == grupo_pequeno.MOTIVO_GRUPO_PEQUENO


@pytest.mark.parametrize("perfil", ["coord", "global"])
def test_ranking_turmas_gestao_ve_como_antes(turma_de_um, perfil):
    eid, tid = turma_de_um["escola"].id, turma_de_um["t4"].id
    r = turma_de_um[perfil].get(f"{API}/escolas/{eid}/ranking/turmas",
                                params={"dimensao": "leitura"})
    assert r.status_code == 200, r.text
    corpo = r.json()
    [item] = [i for i in corpo["itens"] if i["turma_id"] == tid]
    assert item["posicao"] == 1 and item["n_aferidos"] == 1 and item["media"] > 0
    assert "ocultas" not in corpo


def test_comparar_turma_x_turma_secretaria_sem_os_numeros_da_crianca(turma_de_um):
    eid, tid = turma_de_um["escola"].id, turma_de_um["t4"].id
    r = turma_de_um["sec"].get(f"{API}/escolas/{eid}/comparar",
                               params={"tipo_a": "turma", "id_a": tid,
                                       "tipo_b": "turma", "id_b": turma_de_um["outra"].id})
    assert r.status_code == 200, r.text
    lado = r.json()["a"]
    for chave in ("livros_unicos", "tempo_leitura_min", "questoes_tentativas",
                  "questoes_acertos"):
        assert lado["indicadores"][chave] is None, chave
    leitura = lado["dimensoes"]["leitura"]
    assert leitura["nota"] is None
    assert leitura["oculto"]["motivo"] == grupo_pequeno.MOTIVO_GRUPO_PEQUENO
    assert leitura["n_aferidos"] == 1
    assert lado["notas"]["elefante"] is None and lado["notas"]["geral"] is None
    assert lado["grupo_pequeno"] is True
    # O outro lado (turma sem ninguém aferido) não tem o que esconder.
    assert r.json()["b"]["grupo_pequeno"] is False


def test_comparar_turma_x_turma_gestao_ve_como_antes(turma_de_um):
    eid, tid = turma_de_um["escola"].id, turma_de_um["t4"].id
    r = turma_de_um["coord"].get(f"{API}/escolas/{eid}/comparar",
                                 params={"tipo_a": "turma", "id_a": tid,
                                         "tipo_b": "turma", "id_b": turma_de_um["outra"].id})
    assert r.status_code == 200, r.text
    lado = r.json()["a"]
    assert lado["indicadores"]["livros_unicos"] == 19
    assert lado["dimensoes"]["leitura"]["nota"] is not None
    assert "grupo_pequeno" not in lado


# ---------------------------------------------------------------------------
# Cenário 2 — supressão complementar e o limite exato
# ---------------------------------------------------------------------------

def _turma_com_notas(db, escola, imp, nome, notas, livros, ano_escolar="3º Ano"):
    turma = Turma(escola_id=escola.id, nome=nome, ano_escolar=ano_escolar,
                  ano_letivo=2026, status="ativa")
    db.add(turma)
    db.flush()
    for i, valor in enumerate(notas):
        a = Aluno(escola_id=escola.id, nome=f"ALUNO_SINT {nome} {i}", status="ativo")
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=turma.id,
                         ano_letivo=2026))
        db.add(Nota(escola_id=escola.id, aluno_id=a.id, ano_letivo=2026,
                    nota_elefante=valor, aferido_leitura=True))
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=a.id, importacao_id=imp.id,
                                data_referencia=datetime(2026, 10, 1), livros_unicos=livros,
                                livros_por_nivel={"D": livros}))
    return turma


@pytest.fixture()
def escola_mista(db, escola_completa):
    escola = escola_completa["escola"]
    imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    t = {
        # 1 aferido: grupo pequeno
        "pequena": _turma_com_notas(db, escola, imp, "Pequena", [90.0], livros=7),
        # 3 aferidos (o limite exato): menor turma visível da série → complementar
        "tres": _turma_com_notas(db, escola, imp, "Tres", [60.0, 70.0, 80.0], livros=2),
        # 5 aferidos: segue visível
        "cinco": _turma_com_notas(db, escola, imp, "Cinco", [50.0] * 5, livros=3),
        # outra série, 3 aferidos e nenhuma turma pequena: visível
        "quarto": _turma_com_notas(db, escola, imp, "Quarto", [40.0, 45.0, 50.0],
                                   livros=4, ano_escolar="4º Ano"),
    }
    db.commit()
    perfis = _perfis(db, escola)
    return {"escola": escola, **t, **perfis}


def test_complementar_esconde_a_menor_turma_visivel_da_serie(escola_mista):
    eid = escola_mista["escola"].id
    r = escola_mista["sec"].get(f"{API}/escolas/{eid}/resumo-escola")
    assert r.status_code == 200, r.text
    pequena = _linha(r, escola_mista["pequena"].id)
    tres = _linha(r, escola_mista["tres"].id)
    cinco = _linha(r, escola_mista["cinco"].id)
    quarto = _linha(r, escola_mista["quarto"].id)

    assert pequena["oculto"]["leitura"]["motivo"] == grupo_pequeno.MOTIVO_GRUPO_PEQUENO
    assert pequena["indicadores"]["livros_unicos"] is None
    # Sem isto, "total da escola − turmas visíveis" refaria a criança da Pequena.
    assert tres["oculto"]["leitura"]["motivo"] == grupo_pequeno.MOTIVO_COMPLEMENTAR
    assert tres["media_leitura"] is None and tres["indicadores"]["livros_unicos"] is None
    assert tres["grupo_pequeno"] is False  # não é pequena: está protegendo a outra
    # 3 aferidos é o limite exato: com dado e sem marca, as que não protegem ninguém.
    assert cinco["oculto"]["leitura"] is None and cinco["media_leitura"] == 50.0
    assert cinco["indicadores"]["livros_unicos"] == 15
    assert quarto["oculto"]["leitura"] is None and quarto["media_leitura"] == 45.0

    # O que o total menos as visíveis devolve é a soma de 4 crianças, nunca de 1.
    escondidas = [t for t in r.json()["turmas"] if t["oculto"]["leitura"]]
    assert sum(t["n_leitura"] for t in escondidas) >= grupo_pequeno.K_MINIMO_TURMA

    # O ranking de turmas segue a MESMA decisão (Pequena e Tres fora da ordem).
    rk = escola_mista["sec"].get(f"{API}/escolas/{eid}/ranking/turmas",
                                 params={"dimensao": "leitura"}).json()
    assert [(i["posicao"], i["nome"]) for i in rk["itens"]] == [(1, "Cinco"), (2, "Quarto")]
    assert {o["nome"]: o["motivo"] for o in rk["ocultas"]} == {
        "Pequena": grupo_pequeno.MOTIVO_GRUPO_PEQUENO,
        "Tres": grupo_pequeno.MOTIVO_COMPLEMENTAR}

    # ...e o comparador também (a turma complementar não vaza por outra rota).
    cmp_ = escola_mista["sec"].get(
        f"{API}/escolas/{eid}/comparar",
        params={"tipo_a": "turma", "id_a": escola_mista["tres"].id,
                "tipo_b": "turma", "id_b": escola_mista["cinco"].id}).json()
    assert cmp_["a"]["dimensoes"]["leitura"]["nota"] is None
    assert cmp_["a"]["dimensoes"]["leitura"]["oculto"]["motivo"] == \
        grupo_pequeno.MOTIVO_COMPLEMENTAR
    assert cmp_["b"]["dimensoes"]["leitura"]["nota"] == 50.0


def test_complementar_nao_muda_nada_para_a_gestao(escola_mista):
    eid = escola_mista["escola"].id
    r = escola_mista["coord"].get(f"{API}/escolas/{eid}/resumo-escola")
    assert _linha(r, escola_mista["pequena"].id)["media_leitura"] == 90.0
    assert _linha(r, escola_mista["tres"].id)["media_leitura"] == 70.0
    rk = escola_mista["coord"].get(f"{API}/escolas/{eid}/ranking/turmas",
                                   params={"dimensao": "leitura"}).json()
    assert [i["nome"] for i in rk["itens"]] == ["Pequena", "Tres", "Cinco", "Quarto"]


# ---------------------------------------------------------------------------
# A decisão pura
# ---------------------------------------------------------------------------

def _t(tid, serie, n_leitura, aferidos_leitura=None, n_mat=0):
    return {"turma": {"id": tid, "ano_escolar": serie},
            "n_leitura": n_leitura, "n_matematica": n_mat,
            "_aferidos": {"leitura": n_leitura if aferidos_leitura is None else aferidos_leitura,
                          "matematica": n_mat}}


def test_decidir_duas_pequenas_que_somam_o_limite_dispensam_complemento():
    turmas = [_t(1, "3º Ano", 1), _t(2, "3º Ano", 2), _t(3, "3º Ano", 10)]
    m = grupo_pequeno.decidir(turmas, premiaveis={1, 2, 3})
    assert m[1]["leitura"] == m[2]["leitura"] == grupo_pequeno.MOTIVO_GRUPO_PEQUENO
    assert m[3]["leitura"] is None
    assert all(v["matematica"] is None for v in m.values())


def test_decidir_indicadores_sem_nota_tambem_contam():
    # Escola importada e ainda não recalculada: ninguém na média, mas 1 criança
    # nos indicadores — os totais dela não podem sair.
    turmas = [_t(1, "3º Ano", 0, aferidos_leitura=1), _t(2, "3º Ano", 0, aferidos_leitura=8)]
    m = grupo_pequeno.decidir(turmas, premiaveis={1, 2})
    assert m[1]["leitura"] == grupo_pequeno.MOTIVO_GRUPO_PEQUENO
    assert m[2]["leitura"] == grupo_pequeno.MOTIVO_COMPLEMENTAR


def test_decidir_a_fase_nao_serve_de_complemento_da_media_de_quem_concorre():
    # A média da escola só soma quem concorre: esconder a Fase não protegeria
    # a turma pequena do 3º ano. O complemento vem de outra série que concorre.
    turmas = [_t(1, "3º Ano", 1), _t(2, "1ª Fase", 3), _t(3, "4º Ano", 9)]
    m = grupo_pequeno.decidir(turmas, premiaveis={1, 3})
    assert m[1]["leitura"] == grupo_pequeno.MOTIVO_GRUPO_PEQUENO
    assert m[3]["leitura"] == grupo_pequeno.MOTIVO_COMPLEMENTAR
    assert m[2]["leitura"] is None
