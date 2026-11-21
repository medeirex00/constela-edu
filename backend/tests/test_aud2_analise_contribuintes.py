"""G_GRUPO-4 (auditoria, fase C): a análise educacional não mostra livros, minutos nem
atividades por aluno quando só 1 a k − 1 crianças SOMAM neles.

Essas médias dependiam só de k alunos MEDIDOS. Com 6 medidas e 1 só lendo (ou fazendo
atividade), "média × medidos" era o total daquela criança: 0,5 livro por aluno × 6 = os 3
livros dela; 1,17 atividade por aluno × 6 = as 7 atividades. A METODOLOGIA registrava isso
como "lacuna de desenho conhecida"; o cartão da Secretaria (``grupo_pequeno``) e a vitrine já
contavam quem SOMA em cada campo (os contribuintes). Agora a análise também: livros por quem
leu livro novo, minutos por quem tem tempo, atividades por quem fez atividade — de 1 a k − 1
contribuintes, a média some (e sobe em complemento para a escola e a rede, como as outras);
sem nenhum, ela é o zero sabido.

Dados INVENTADOS. Nenhuma rede externa.
"""
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import EventoAluno, Usuario
from tests.test_analise_base import (ler, livros, nova_escola, nova_rede, retrato_elefante,
                                     retrato_matific, turma_com_alunos)

HOJE = date(2026, 10, 5)
API = "/api/v1"
TERCEIRO = {"periodo": "bimestre_3"}                       # 24/07 a 04/10/2026


@pytest.fixture(autouse=True)
def _hoje(monkeypatch):
    monkeypatch.setattr("app.routers.analise.hoje_br", lambda: HOJE)


def _secretaria(db, rede_id) -> TestClient:
    db.add(Usuario(nome="Secretaria Fictícia", email=f"sec.{rede_id}@ficticio.local",
                   senha_hash=hash_senha("s3nh4"), cargo="coordenador", rede_id=rede_id))
    db.commit()
    c = TestClient(app)
    r = c.post(f"{API}/auth/login",
               data={"username": f"sec.{rede_id}@ficticio.local", "password": "s3nh4"})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _turma(db, escola, serie, n, *, leitoras=0, livros_cada=3, ativas=0, atividades=7,
           releituras=0):
    """``n`` crianças com conta nas duas plataformas; ``leitoras`` leem ``livros_cada`` livros
    novos no 3º bimestre; ``releituras`` outras só releem (evento, sem livro novo); ``ativas``
    fazem ``atividades`` no Matific no 3º bimestre."""
    alunos = turma_com_alunos(db, escola, f"{serie}º Ano", n)
    for i, a in enumerate(alunos):
        retrato_elefante(db, escola, a, datetime(2026, 7, 20, 3, 10))
        retrato_elefante(db, escola, a, datetime(2026, 10, 1, 3, 10))
        retrato_matific(db, escola, a, datetime(2026, 7, 20, 3, 20), atividades=0, estrelas=0)
        feitas = atividades if i < ativas else 0
        retrato_matific(db, escola, a, datetime(2026, 10, 1, 3, 20), atividades=feitas,
                        estrelas=2 * feitas)
        if i < leitoras:
            ler(db, escola, a, livros(db, escola, livros_cada, "K"), datetime(2026, 9, 10, 14, 0),
                minutos=15)
        elif i < leitoras + releituras:
            db.add(EventoAluno(escola_id=escola.id, aluno_id=a.id, plataforma="elefante",
                               tipo_evento="leitura", ocorrido_em=datetime(2026, 9, 12, 10, 0),
                               chave_natural=f"releitura-{escola.id}-{a.id}"))
    db.flush()
    return alunos


def _celula(corpo, escola, serie):
    e = next(x for x in corpo["escolas"] if x["escola_id"] == escola.id)
    return e, next(c for c in e["series"] if c["serie"] == serie)


def test_uma_crianca_lendo_entre_seis_medidas_nao_vira_a_media(db, escola_completa):
    rede = nova_rede(db, nome="Rede Fictícia dos Contribuintes", codigo="3599981", codmun="9981")
    escola = nova_escola(db, rede, "EMEF Fictícia dos Contribuintes", "35998101")
    _turma(db, escola, 3, 6, leitoras=1, ativas=1)
    db.commit()
    sec = _secretaria(db, rede.id)
    r = sec.get(f"{API}/redes/{rede.id}/analise/plataformas", params=TERCEIRO)
    assert r.status_code == 200, r.text
    corpo = r.json()
    esc, cel = _celula(corpo, escola, 3)
    for nome, bloco in (("celula", cel), ("escola", esc), ("rede", corpo["rede"])):
        ele, mat = bloco["elefante"], bloco["matific"]
        assert ele["alunos_medidos"] == 6 and ele["alunos_com_leitura"] == 1, (nome, ele)
        # A contagem e a participação continuam (não são número de criança)...
        assert ele["participacao_pct"] == 16.7 and mat["participacao_pct"] == 16.7, nome
        # ...mas "média × medidos" não devolve mais os 3 livros, os 45 minutos e as 7
        # atividades da única criança.
        assert ele["livros_por_aluno"] is None and ele["minutos_por_aluno"] is None, (nome, ele)
        assert mat["atividades_por_aluno"] is None, (nome, mat)
    # A mesma escola pela rota da escola (a Secretaria lê com a proteção da rede).
    r = sec.get(f"{API}/escolas/{escola.id}/analise", params=TERCEIRO)
    plat = r.json()["plataformas"]
    assert plat["elefante"]["livros_por_aluno"] is None
    assert plat["matific"]["atividades_por_aluno"] is None


def test_releituras_nao_escondem_a_unica_leitora_de_livro_novo(db, escola_completa):
    """5 crianças só releem (contam como "com leitura") e 1 lê 3 livros novos: os livros por
    aluno são os dela. O que conta é quem SOMA livros (o campo > 0), como no cartão."""
    rede = nova_rede(db, nome="Rede Fictícia das Releituras", codigo="3599982", codmun="9982")
    escola = nova_escola(db, rede, "EMEF Fictícia das Releituras", "35998201")
    _turma(db, escola, 4, 6, leitoras=1, releituras=5)
    db.commit()
    sec = _secretaria(db, rede.id)
    corpo = sec.get(f"{API}/redes/{rede.id}/analise/plataformas", params=TERCEIRO).json()
    _esc, cel = _celula(corpo, escola, 4)
    assert cel["elefante"]["alunos_com_leitura"] == 6
    assert cel["elefante"]["livros_por_aluno"] is None
    assert cel["elefante"]["minutos_por_aluno"] is None


def test_complemento_sobe_para_a_escola_e_a_rede(db, escola_completa):
    """3º ano com 1 leitora e 1 ativa de 6; 4º com 6 leitoras e 6 ativas: a célula do 3º
    esconde, e o total da escola (e o da rede) também — senão "escola − 4º" a refaria. Com
    k ou mais contribuintes, ou nenhum (o zero sabido), a média aparece."""
    rede = nova_rede(db, nome="Rede Fictícia do Complemento", codigo="3599983", codmun="9983")
    escola = nova_escola(db, rede, "EMEF Fictícia do Complemento", "35998301")
    _turma(db, escola, 3, 6, leitoras=1, ativas=1)
    _turma(db, escola, 4, 6, leitoras=6, ativas=6)
    _turma(db, escola, 5, 6)                       # ninguém leu nem fez atividade
    db.commit()
    sec = _secretaria(db, rede.id)
    corpo = sec.get(f"{API}/redes/{rede.id}/analise/plataformas", params=TERCEIRO).json()
    esc, c3 = _celula(corpo, escola, 3)
    _esc, c4 = _celula(corpo, escola, 4)
    _esc, c5 = _celula(corpo, escola, 5)
    assert c3["elefante"]["livros_por_aluno"] is None
    assert c3["matific"]["atividades_por_aluno"] is None
    assert c4["elefante"]["livros_por_aluno"] == 3.0
    assert c4["elefante"]["minutos_por_aluno"] == 45.0
    assert c4["matific"]["atividades_por_aluno"] == 7.0
    assert c5["elefante"]["livros_por_aluno"] == 0.0           # nenhuma: o zero sabido
    assert c5["matific"]["atividades_por_aluno"] == 0.0
    for nome, total in (("escola", esc), ("rede", corpo["rede"])):
        assert total["elefante"]["livros_por_aluno"] is None, nome
        assert "livros_por_aluno" in total["elefante"]["metricas_protegidas"], nome
        assert total["matific"]["atividades_por_aluno"] is None, nome
        assert "atividades_por_aluno" in total["matific"]["metricas_protegidas"], nome
