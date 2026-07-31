"""RBAC da Secretaria (usuário com rede vinculada, não-global).

A Secretaria acompanha os resultados da REDE, mas NÃO opera as escolas:
- não pode ALTERAR métricas (mas pode LER);
- não pode importar, sincronizar nem rodar o diagnóstico Elefante.
O coordenador de escola (sem rede) e o admin global seguem com escrita normal.
Fecha o furo de a Secretaria ter cargo "coordenador" e ser tratada como um.
"""
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import Escola, Rede, Usuario


def _login(email: str, senha: str) -> TestClient:
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", data={"username": email, "password": senha})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _cenario(db, escola_completa):
    escola = escola_completa["escola"]
    rede = Rede(nome="Rede Teste", status="ativa")
    outra_rede = Rede(nome="Outra Rede", status="ativa")
    db.add_all([rede, outra_rede])
    db.flush()
    escola.rede_id = rede.id                      # a escola-base entra na rede da Secretaria
    escola2 = Escola(nome="Escola 2 da Rede", status="ativa", rede_id=rede.id)
    fora = Escola(nome="Escola de Outra Rede", status="ativa", rede_id=outra_rede.id)
    db.add_all([escola2, fora])
    db.add(Usuario(escola_id=escola.id, nome="Coord Escola", email="coord@rbac.local",
                   senha_hash=hash_senha("s3nh4"), cargo="coordenador"))
    # Secretaria: cargo coordenador + rede vinculada (mantém escola_id — pior caso).
    db.add(Usuario(escola_id=escola.id, nome="Secretaria", email="sec@rbac.local",
                   senha_hash=hash_senha("s3nh4"), cargo="coordenador", rede_id=rede.id))
    db.commit()
    return {"escola": escola.id, "escola2": escola2.id, "fora": fora.id}


def test_secretaria_nao_altera_metricas_mas_le(db, escola_completa):
    eid = _cenario(db, escola_completa)["escola"]
    coord = _login("coord@rbac.local", "s3nh4")
    sec = _login("sec@rbac.local", "s3nh4")
    corpo = {"pesos": {"matific": 50, "elefante": 50}}

    # ESCRITA: coordenador de escola passa da autorização (não é 403);
    # Secretaria é barrada com 403.
    assert coord.put(f"/api/v1/escolas/{eid}/configuracoes/pesos/geral", json=corpo).status_code != 403
    assert sec.put(f"/api/v1/escolas/{eid}/configuracoes/pesos/geral", json=corpo).status_code == 403

    # LEITURA: a Secretaria PODE ver as métricas (não é 403).
    assert sec.get(f"/api/v1/escolas/{eid}/configuracoes/pesos/geral").status_code != 403


def test_secretaria_bloqueada_em_sync_diagnostico_importacao(db, escola_completa):
    eid = _cenario(db, escola_completa)["escola"]
    coord = _login("coord@rbac.local", "s3nh4")
    sec = _login("sec@rbac.local", "s3nh4")

    for metodo, rota in [
        ("post", f"/api/v1/escolas/{eid}/sync/agora"),
        ("post", f"/api/v1/escolas/{eid}/sync/elefante/diagnostico"),
        ("post", f"/api/v1/escolas/{eid}/importacoes/recalcular"),
    ]:
        assert getattr(sec, metodo)(rota, json={}).status_code == 403, rota
        # O coordenador de escola NÃO é barrado por papel/rede (403).
        assert getattr(coord, metodo)(rota, json={}).status_code != 403, rota


def test_secretaria_le_toda_a_rede_mas_nao_escreve(db, escola_completa):
    """A Secretaria enxerga e LÊ qualquer escola da rede dela (não só a 'dela'),
    mas não ESCREVE em nenhuma; e não alcança escola de outra rede."""
    cen = _cenario(db, escola_completa)
    sec = _login("sec@rbac.local", "s3nh4")
    coord = _login("coord@rbac.local", "s3nh4")

    # SELETOR: a Secretaria vê as DUAS escolas da rede; o coordenador vê só a dele.
    ids_sec = {e["id"] for e in sec.get("/api/v1/escolas").json()}
    assert {cen["escola"], cen["escola2"]} <= ids_sec
    assert cen["fora"] not in ids_sec
    assert {e["id"] for e in coord.get("/api/v1/escolas").json()} == {cen["escola"]}

    # LEITURA de OUTRA escola da rede (não a escola_id dela): liberada.
    assert sec.get(f"/api/v1/escolas/{cen['escola2']}/configuracoes/pesos/geral").status_code != 403
    # ESCRITA em qualquer escola da rede: bloqueada (ponto único em escola_autorizada).
    assert sec.post(f"/api/v1/escolas/{cen['escola2']}/alunos",
                    json={"nome": "Fulano"}).status_code == 403
    assert sec.delete(f"/api/v1/escolas/{cen['escola2']}/turmas/999").status_code == 403
    # Escola de OUTRA rede: nem ler.
    assert sec.get(f"/api/v1/escolas/{cen['fora']}/configuracoes/pesos/geral").status_code == 403


def test_secretaria_nao_ve_pii_individual_mas_ve_agregado(db, escola_completa):
    """LGPD: a Secretaria AGREGA a rede, mas não enxerga dado INDIVIDUAL de
    criança (nome/ficha/histórico/mural/certificado). Os agregados sem PII
    (resumo por turma) continuam abertos; o coordenador da escola não é afetado."""
    cen = _cenario(db, escola_completa)
    eid = cen["escola"]
    ana = escola_completa["alunos"][0]  # "Ana Beatriz Souza"
    sec = _login("sec@rbac.local", "s3nh4")
    coord = _login("coord@rbac.local", "s3nh4")

    # Lista de alunos: VAZIA para a Secretaria (nenhum nome de criança).
    lista = sec.get(f"/api/v1/escolas/{eid}/alunos")
    assert lista.status_code == 200
    assert lista.json()["itens"] == [] and lista.json()["total"] == 0
    assert "Beatriz" not in lista.text
    # ...mas o coordenador da própria escola continua vendo os alunos (sem over-block).
    assert coord.get(f"/api/v1/escolas/{eid}/alunos").json()["total"] >= 1

    # Endpoints por-aluno / nominais: 403 para a Secretaria.
    assert sec.get(f"/api/v1/escolas/{eid}/alunos/{ana.id}/linha-do-tempo").status_code == 403
    assert sec.get(f"/api/v1/escolas/{eid}/gamificacao/mural").status_code == 403
    # Prévia de fusão (lista NOMES) e histórico do Assistente (respostas
    # reidentificam PII): 403.
    assert sec.get(f"/api/v1/escolas/{eid}/alunos/duplicados").status_code == 403
    assert sec.get(f"/api/v1/escolas/{eid}/assistente/conversas").status_code == 403
    # Cartaz/certificados (router relatorios sob negar_secretaria): 403.
    assert sec.get(f"/api/v1/escolas/{eid}/ranking/cartaz").status_code == 403

    # Comparador: o lado 'aluno' é PII → 403; turma×turma é agregado → liberado.
    tid = escola_completa["turma"].id
    assert sec.get(f"/api/v1/escolas/{eid}/comparar",
                   params={"tipo_a": "aluno", "id_a": ana.id,
                           "tipo_b": "aluno", "id_b": ana.id}).status_code == 403
    assert sec.get(f"/api/v1/escolas/{eid}/comparar",
                   params={"tipo_a": "turma", "id_a": tid,
                           "tipo_b": "turma", "id_b": tid}).status_code != 403

    # Insights: acessível, mas SEM índices/alertas nominais de criança.
    ins = sec.get(f"/api/v1/escolas/{eid}/insights")
    assert ins.status_code == 200
    assert ins.json()["indices"] == [] and ins.json()["alertas"] == []
    assert "Beatriz" not in ins.text

    # AGREGADO legítimo continua aberto: comparação por turma (sem nome de criança).
    resumo = sec.get(f"/api/v1/escolas/{eid}/resumo-escola")
    assert resumo.status_code == 200 and "Beatriz" not in resumo.text
