"""G_MODULOS-6 — rede só com a Leitura: meta e totais de um módulo FORA DO PLANO.

A Secretaria cadastrou "Atividades Matific na rede: 1000" quando a rede tinha os dois
módulos; depois o Admin Global desligou a Matemática. O Painel e o Panorama da Rede seguiam
mostrando a meta, com o progresso calculado com o dado do Matific; por API direta a meta de
Matemática ainda podia ser criada (200), e os totais do ``/dashboard`` traziam atividades,
estrelas e alunos com dado do Matific numa rede que não o contratou.

O conserto: a meta de módulo fora do plano é recusada (400) e some do progresso — a linha
NÃO é apagada (o módulo pode voltar, e a meta volta com ele) — e os totais da plataforma
fora do plano saem nulos no painel da rede.

Redes, escolas e crianças FICTÍCIAS.
"""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import Importacao, MetaRede, SnapshotElefante, SnapshotMatific, Usuario
from app.services import rede as svc
from tests.test_analise_base import nova_escola, nova_rede, turma_com_alunos

API = "/api/v1"
QUANDO = datetime(2026, 9, 30, 12, 0)
_SENHA = "s3nh4-inventada"
TOTAIS_DO_MATIFIC = ("media_matific", "atividades", "estrelas", "ativos_matific")


def _imp(db, escola, plataforma):
    imp = Importacao(escola_id=escola.id, plataforma=plataforma, tipo="seed",
                     status="concluida")
    db.add(imp)
    db.flush()
    return imp


def _login(email):
    cliente = TestClient(app)
    r = cliente.post(f"{API}/auth/login", data={"username": email, "password": _SENHA})
    assert r.status_code == 200, r.text
    cliente.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return cliente


@pytest.fixture()
def rede_dois_modulos(db):
    """Uma escola com 5 crianças do 3º ano, todas com dado do Elefante e do Matific, e uma
    conta da Secretaria da rede."""
    rede = nova_rede(db, nome="Rede Inventada das Metas", codigo="3599971")
    escola = nova_escola(db, rede, "EMEF Inventada Ômega", None)
    for crianca in turma_com_alunos(db, escola, "3º Ano", 5):
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=crianca.id,
                                importacao_id=_imp(db, escola, "elefante").id,
                                data_referencia=QUANDO, livros_unicos=4, tempo_leitura_min=40,
                                questoes_tentativas=0, questoes_acertos=0,
                                livros_por_nivel={}))
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=crianca.id,
                               importacao_id=_imp(db, escola, "matific").id,
                               data_referencia=QUANDO, atividades=7, estrelas=21,
                               pontuacao_media=0.0))
    db.add(Usuario(escola_id=None, nome="SEC INVENTADA", email="sec.metas@inventada.local",
                   senha_hash=hash_senha(_SENHA), cargo="coordenador", rede_id=rede.id))
    db.commit()
    return rede


def test_meta_de_modulo_desligado_some_do_progresso_e_volta_com_o_modulo(
        cliente_global, db, rede_dois_modulos):
    rid = rede_dois_modulos.id
    for metrica, alvo in (("atividades", 1000), ("media_elefante", 50)):
        r = cliente_global.put(f"{API}/redes/{rid}/metas", json={"metrica": metrica, "alvo": alvo})
        assert r.status_code == 200, r.text
    assert cliente_global.put(f"{API}/redes/{rid}/modulos",
                              json={"matematica": False}).status_code == 200

    for cliente in (cliente_global, _login("sec.metas@inventada.local")):
        metas = cliente.get(f"{API}/redes/{rid}/metas").json()
        assert [m["metrica"] for m in metas] == ["media_elefante"], metas
    # A linha não foi apagada: o módulo pode ser recontratado.
    assert db.query(MetaRede).filter_by(rede_id=rid, metrica="atividades").count() == 1

    assert cliente_global.put(f"{API}/redes/{rid}/modulos",
                              json={"matematica": True}).status_code == 200
    metas = cliente_global.get(f"{API}/redes/{rid}/metas").json()
    volta = next(m for m in metas if m["metrica"] == "atividades")
    assert volta["alvo"] == 1000.0 and volta["atual"] == 35.0


@pytest.mark.parametrize("metrica", ["media_matific", "atividades"])
def test_meta_de_modulo_fora_do_plano_e_recusada(cliente_global, db, rede_dois_modulos, metrica):
    rid = rede_dois_modulos.id
    assert cliente_global.put(f"{API}/redes/{rid}/modulos",
                              json={"matematica": False}).status_code == 200
    for cliente in (cliente_global, _login("sec.metas@inventada.local")):
        r = cliente.put(f"{API}/redes/{rid}/metas", json={"metrica": metrica, "alvo": 70})
        assert r.status_code == 400, r.text
        assert "Matemática" in r.json()["detail"]
    assert db.query(MetaRede).filter_by(rede_id=rid).count() == 0
    # A do módulo contratado continua aceita.
    r = cliente_global.put(f"{API}/redes/{rid}/metas", json={"metrica": "livros", "alvo": 70})
    assert r.status_code == 200, r.text


def test_servico_recusa_meta_de_leitura_numa_rede_so_de_matematica(db, rede_dois_modulos):
    from app.models import ModuloRede
    db.add(ModuloRede(rede_id=rede_dois_modulos.id, modulo="leitura", ativo=False))
    db.commit()
    for metrica in ("media_elefante", "livros"):
        with pytest.raises(svc.MetaForaDoPlano):
            svc.definir_meta(db, rede_dois_modulos.id, metrica, 10)
    # As métricas sem plataforma (índice, adoção, média geral) valem em qualquer plano.
    svc.definir_meta(db, rede_dois_modulos.id, "pontuacao_geral", 10)


def test_totais_do_painel_nao_trazem_a_plataforma_fora_do_plano(
        cliente_global, db, rede_dois_modulos):
    rid = rede_dois_modulos.id
    antes = cliente_global.get(f"{API}/redes/{rid}/dashboard").json()["totais"]
    assert (antes["atividades"], antes["estrelas"], antes["ativos_matific"]) == (35, 105, 5)
    assert cliente_global.put(f"{API}/redes/{rid}/modulos",
                              json={"matematica": False}).status_code == 200
    for cliente in (cliente_global, _login("sec.metas@inventada.local")):
        totais = cliente.get(f"{API}/redes/{rid}/dashboard").json()["totais"]
        assert {k: totais[k] for k in TOTAIS_DO_MATIFIC} == dict.fromkeys(TOTAIS_DO_MATIFIC)
        # A Leitura, contratada, continua com os números dela.
        assert (totais["livros"], totais["ativos_elefante"]) == (20, 5)
