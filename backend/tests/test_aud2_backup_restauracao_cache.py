"""G_LGPD-8 — restaurar o backup invalida o cache do telão e o do ao vivo do Matific.

``restaurar_backup`` chamava ``scoring.recalcular_escola`` direto, sem
``publico.invalidar_cache_painel`` (que a exclusão, a importação e as ações da gestão
chamam) nem ``aovivo.invalidar_cache``. Por até 60 s (``TTL_PAINEL_S``) o telão público
seguia mostrando o ranking de ANTES — com ids que já não existem (o perfil público
dava 404) e a criança que o arquivo não traz (com o nome, se o painel não anonimiza) —,
e o ao vivo do Matific seguia ligando as linhas a fichas apagadas.

Dados 100% fictícios (fixture escola_completa); sem rede.
"""
import json
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import Aluno, Importacao, Matricula, SnapshotMatific
from app.services import backup as svc_backup
from app.services import scoring
from app.sync import aovivo

API = "/api/v1"


def test_restauracao_atualiza_o_telao_na_hora(db, escola_completa, cliente, cliente_global):
    escola = escola_completa["escola"]
    eid = escola.id
    turma = escola_completa["turma"]
    a, b, _c = escola_completa["alunos"]
    imp = Importacao(escola_id=eid, plataforma="matific", tipo="seed")
    db.add(imp)
    db.flush()
    for aluno, estrelas in ((a, 30), (b, 20)):
        db.add(SnapshotMatific(escola_id=eid, aluno_id=aluno.id, importacao_id=imp.id,
                               atividades=estrelas, estrelas=estrelas, pontuacao_media=70))
    db.commit()
    arquivo = json.dumps(svc_backup.exportar(db, eid), default=str).encode("utf-8")

    # Depois do backup entra uma criança nova que lidera o ranking.
    nova = Aluno(escola_id=eid, nome="Crianca Ficticia Aud2 Depois Do Backup")
    db.add(nova)
    db.flush()
    db.add(Matricula(escola_id=eid, aluno_id=nova.id, turma_id=turma.id, ano_letivo=2026))
    db.add(SnapshotMatific(escola_id=eid, aluno_id=nova.id, importacao_id=imp.id,
                           atividades=99, estrelas=99, pontuacao_media=99))
    db.commit()
    nova_id = nova.id
    scoring.recalcular_escola(db, eid)
    r = cliente.put(f"{API}/escolas/{eid}/painel-publico",
                    json={"ativo": True, "slides": ["ranking"], "intervalo_s": 8,
                          "max_posicoes": 10})
    assert r.status_code == 200, r.text
    token = r.json()["url"].rsplit("/", 1)[-1]
    anonimo = TestClient(app)
    antes = [i["aluno_id"] for i in anonimo.get(f"{API}/publico/{token}/painel").json()["ranking"]]
    assert nova_id in antes, antes

    r = cliente_global.post(f"{API}/escolas/{eid}/restaurar",
                            files={"arquivo": ("b.json", arquivo, "application/json")})
    assert r.status_code == 200, r.text
    db.expire_all()
    vivas = set(db.execute(select(Aluno.id).where(Aluno.escola_id == eid)).scalars())
    depois = [i["aluno_id"]
              for i in anonimo.get(f"{API}/publico/{token}/painel").json()["ranking"]]
    assert depois and set(depois) <= vivas, (
        f"o telão segue mostrando fichas que a restauração apagou: {set(depois) - vivas}")
    assert nova_id not in depois
    for aluno_id in depois:                          # o perfil público das fichas novas abre
        assert anonimo.get(f"{API}/publico/{token}/alunos/{aluno_id}").status_code == 200


def test_restauracao_descarta_o_ao_vivo_do_matific_da_escola(db, escola_completa,
                                                             cliente_global):
    eid = escola_completa["escola"].id
    arquivo = json.dumps(svc_backup.exportar(db, eid), default=str).encode("utf-8")
    agora = datetime.now()
    aovivo._cache_put(eid, "aud2-filtro", agora, {"itens": [{"aluno_id": 1}]})
    aovivo._cache_put(eid + 1000, "aud2-filtro", agora, {"itens": []})   # outra escola
    try:
        r = cliente_global.post(f"{API}/escolas/{eid}/restaurar",
                                files={"arquivo": ("b.json", arquivo, "application/json")})
        assert r.status_code == 200, r.text
        assert aovivo._cache_get(eid, "aud2-filtro", agora) is None, (
            "o ao vivo do Matific segue ligando as linhas às fichas de antes")
        assert aovivo._cache_get(eid + 1000, "aud2-filtro", agora) is not None
    finally:
        aovivo.invalidar_cache(eid)
        aovivo.invalidar_cache(eid + 1000)
