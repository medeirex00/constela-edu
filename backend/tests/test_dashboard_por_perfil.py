"""Dashboard POR PERFIL: cada papel enxerga o escopo certo e nada além.

  * Professor   → a PRÓPRIA TURMA (ranking/Top10 renumerados 1..N para ele).
  * Coordenador → a ESCOLA INTEIRA (posição global, todos os alunos).
  * Secretaria  → o agregado da REDE + Ranking Geral agregado POR ESCOLA, mas
                  NUNCA PII individual de criança (ranking nominal vazio; ficha/
                  evolução por aluno → 403).
  * Admin Global→ a consolidação de TODAS as redes, com drill-down (rede →
                  escola) e retorno à visão consolidada.

Cobre os dois casos corrigidos: o Ranking Geral da Secretaria (agregado, sem
PII — antes vinha vazio) e a visão multirrede do Admin Global (antes era só a
mesma tela da rede). Os testes exercitam os endpoints REAIS que cada Dashboard
consome — a fonte da verdade é o servidor, não o que o frontend esconde.
"""
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import (
    Aluno,
    Escola,
    Importacao,
    Matricula,
    Nota,
    Professor,
    Rede,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
    Usuario,
)


def _login(email: str, senha: str) -> TestClient:
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", data={"username": email, "password": senha})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _turma_com_alunos(db, escola_id, nome, alunos, professor_id=None):
    """Turma + alunos (nome, nota_geral, posição GLOBAL) + matrículas do ano."""
    turma = Turma(escola_id=escola_id, nome=nome, ano_escolar="1º Ano",
                  ano_letivo=2026, status="ativa", professor_id=professor_id)
    db.add(turma)
    db.flush()
    imp = Importacao(escola_id=escola_id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    ids = []
    for nome_aluno, nota_geral, posicao in alunos:
        a = Aluno(escola_id=escola_id, nome=nome_aluno, status="ativo")
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=escola_id, aluno_id=a.id, turma_id=turma.id,
                         ano_letivo=2026))
        # Snapshots das duas plataformas: sem eles o aluno não tem "dado" e fica
        # fora da média de desempenho da escola (que agora mede só quem usa).
        db.add(SnapshotElefante(escola_id=escola_id, aluno_id=a.id, importacao_id=imp.id,
                                livros_unicos=5, tempo_leitura_min=60))
        db.add(SnapshotMatific(escola_id=escola_id, aluno_id=a.id, importacao_id=imp.id,
                               atividades=20, estrelas=100))
        db.add(Nota(escola_id=escola_id, aluno_id=a.id, ano_letivo=2026,
                    nota_geral=nota_geral, nota_elefante=nota_geral,
                    nota_matific=nota_geral, posicao=posicao))
        ids.append(a.id)
    return turma, ids


def _cenario(db):
    """Uma REDE, uma ESCOLA, duas TURMAS (A com professor, B sem) e três alunos.

    Posição GLOBAL: Ana(90)=1 · Carla(76)=2 · Bruno(70)=4 (o gap na 3 seria um
    aluno arquivado — posições reais não são contíguas). A turma A do professor
    tem Ana e Bruno → na visão DELE renumeram para 1 e 2, o que DISCRIMINA da
    posição global [1, 4] (um teste com [1,2,3] contíguo não pegaria renumeração
    indevida). Carla vale 76 (≠ média 80 de Ana+Bruno) para que a média restrita
    do professor (80) DIFIRA da média da escola inteira (78,67) — senão o assert
    de média passaria mesmo sem restrição. Cria as três contas de escola/rede (o
    Admin Global é criado por teste, quando preciso)."""
    rede = Rede(nome="Rede Municipal de Caraguatatuba", uf="SP", status="ativa")
    db.add(rede)
    db.flush()
    esc = Escola(nome="EM JORGE PASSOS", ano_letivo_ativo=2026, rede_id=rede.id,
                 status="ativa")
    db.add(esc)
    db.flush()

    prof = Professor(escola_id=esc.id, nome="Maria Prof", email="prof@esc.local")
    db.add(prof)
    db.flush()
    turma_a, alunos_a = _turma_com_alunos(
        db, esc.id, "1º Ano A",
        [("Ana Souza", 90.0, 1), ("Bruno Lima", 70.0, 4)], professor_id=prof.id)
    turma_b, alunos_b = _turma_com_alunos(
        db, esc.id, "1º Ano B", [("Carla Dias", 76.0, 2)])

    db.add(Usuario(escola_id=esc.id, nome="Maria Prof", email="prof@esc.local",
                   senha_hash=hash_senha("s3nh4professor"), cargo="professor"))
    db.add(Usuario(escola_id=esc.id, nome="Coord Escola", email="coord@esc.local",
                   senha_hash=hash_senha("s3nh4coordena"), cargo="coordenador"))
    db.add(Usuario(nome="Secretaria", email="sec@rede.gov",
                   senha_hash=hash_senha("s3nh4secretar"), cargo="coordenador",
                   rede_id=rede.id))
    db.commit()
    return {"rede": rede.id, "escola": esc.id,
            "turma_a": turma_a.id, "turma_b": turma_b.id,
            "alunos_a": alunos_a, "alunos_b": alunos_b}


# --- Professor → Dashboard da TURMA -----------------------------------------

def test_professor_ve_apenas_a_propria_turma_renumerada(db):
    c = _cenario(db)
    prof = _login("prof@esc.local", "s3nh4professor")

    # Ranking Geral na perspectiva do professor: só a turma dele, RENUMERADO 1..N
    # (posição global de Bruno é 4 → renumerar para 2 discrimina de [1, 4]).
    ranking = prof.get(f"/api/v1/escolas/{c['escola']}/ranking").json()
    assert [r["nome"] for r in ranking] == ["Ana Souza", "Bruno Lima"]  # sem Carla
    assert [r["posicao"] for r in ranking] == [1, 2]                    # renumerado

    # Dashboard da TURMA: só os 2 alunos da turma dele, uma turma. A média restrita
    # (90+70)/2 = 80 DIFERE da média da escola inteira (78,67) → sensível ao escopo.
    dash = prof.get(f"/api/v1/escolas/{c['escola']}/dashboard").json()
    assert dash["total_alunos"] == 2 and dash["total_turmas"] == 1
    assert dash["media_geral"] == 80.0
    assert [t["nome"] for t in dash["top10"]] == ["Ana Souza", "Bruno Lima"]

    # O passo-a-passo da nota é liberado para o aluno DELE...
    meu = prof.get(f"/api/v1/escolas/{c['escola']}/alunos/{c['alunos_a'][0]}/perfil")
    assert meu.status_code == 200, meu.text
    # ...mas um aluno de OUTRA turma é invisível (404, não revela a existência).
    outro = prof.get(f"/api/v1/escolas/{c['escola']}/alunos/{c['alunos_b'][0]}/perfil")
    assert outro.status_code == 404


# --- Coordenador → Dashboard da ESCOLA --------------------------------------

def test_coordenador_ve_a_escola_inteira(db):
    c = _cenario(db)
    coord = _login("coord@esc.local", "s3nh4coordena")

    # Ranking Geral da escola inteira, na posição GLOBAL preservada (NÃO renumera):
    # posições [1, 2, 4] (o 3 é o gap do arquivado) discriminam de um [1,2,3] que
    # uma renumeração indevida produziria.
    ranking = coord.get(f"/api/v1/escolas/{c['escola']}/ranking").json()
    assert [r["nome"] for r in ranking] == ["Ana Souza", "Carla Dias", "Bruno Lima"]
    assert [r["posicao"] for r in ranking] == [1, 2, 4]

    # Dashboard da ESCOLA: os 3 alunos, as 2 turmas.
    dash = coord.get(f"/api/v1/escolas/{c['escola']}/dashboard").json()
    assert dash["total_alunos"] == 3 and dash["total_turmas"] == 2

    # O gestor da PRÓPRIA escola (sem rede) enxerga o dado individual da criança.
    r = coord.get(f"/api/v1/escolas/{c['escola']}/alunos/{c['alunos_a'][0]}/evolucao")
    assert r.status_code == 200, r.text


# --- Secretaria → Dashboard da REDE + Ranking agregado, SEM PII --------------

def test_secretaria_ve_rede_e_ranking_agregado_sem_pii(db):
    c = _cenario(db)
    sec = _login("sec@rede.gov", "s3nh4secretar")

    # 1) Dashboard da REDE: agregado por escola, sem nome de criança.
    resp = sec.get(f"/api/v1/redes/{c['rede']}/dashboard")
    assert resp.status_code == 200, resp.text
    dash = resp.json()
    assert dash["totais"]["escolas"] == 1 and dash["totais"]["alunos"] == 3
    for nome in ("Ana", "Bruno", "Carla"):
        assert nome not in resp.text                       # sem PII individual

    # 2) Ranking Geral da REDE (agregado POR ESCOLA) — o caso corrigido: NÃO vem
    #    mais vazio. Traz a escola pelo nome, não a criança.
    rk = sec.get(f"/api/v1/redes/{c['rede']}/ranking?metrica=geral")
    assert rk.status_code == 200, rk.text
    escolas = rk.json()
    assert [e["nome"] for e in escolas] == ["EM JORGE PASSOS"]
    for nome in ("Ana", "Bruno", "Carla"):
        assert nome not in rk.text

    # 3) BLOQUEIO DE PII: o ranking NOMINAL de crianças por escola fica VAZIO para
    #    a Secretaria (turmas_permitidas = []), sem 403 — some, não vaza.
    nominal = sec.get(f"/api/v1/escolas/{c['escola']}/ranking")
    assert nominal.status_code == 200 and nominal.json() == []

    # 4) BLOQUEIO DE PII: a ficha/evolução individual da criança → 403.
    r = sec.get(f"/api/v1/escolas/{c['escola']}/alunos/{c['alunos_a'][0]}/evolucao")
    assert r.status_code == 403

    # 5) A Secretaria NÃO acessa a visão global (é uma camada acima dela).
    assert sec.get("/api/v1/redes/panorama-global").status_code == 403


# --- Admin Global → múltiplas redes + drill-down + volta consolidada ---------

def test_admin_global_multirrede_drill_down_e_volta(db):
    c = _cenario(db)                       # rede Caraguatatuba + escola + 3 alunos

    # Segunda rede, para haver o que CONSOLIDAR.
    rede2 = Rede(nome="Rede Municipal de Ubatuba", uf="SP", status="ativa")
    db.add(rede2)
    db.flush()
    esc2 = Escola(nome="EM UBATUBA CENTRO", ano_letivo_ativo=2026,
                  rede_id=rede2.id, status="ativa")
    db.add(esc2)
    db.flush()
    _turma_com_alunos(db, esc2.id, "1º Ano U", [("Duda Rocha", 60.0, 1)])
    db.add(Usuario(nome="Root", email="root@x.gov",
                   senha_hash=hash_senha("s3nh4rootglob"), cargo="admin",
                   is_global=True))
    db.commit()

    admin = _login("root@x.gov", "s3nh4rootglob")

    # (a) Visão CONSOLIDADA: todas as redes (2), todas as escolas (2), alunos (4).
    glob = admin.get("/api/v1/redes/panorama-global")
    assert glob.status_code == 200, glob.text
    jg = glob.json()
    assert jg["totais"]["redes"] == 2 and jg["totais"]["escolas"] == 2
    assert jg["totais"]["alunos"] == 4
    assert {r["nome"] for r in jg["redes"]} == {
        "Rede Municipal de Caraguatatuba", "Rede Municipal de Ubatuba"}
    # Cada escola do top carrega o nome da SUA rede (não vazio, não trocado).
    por_escola = {e["nome"]: e["rede_nome"] for e in jg["top_escolas"]}
    assert por_escola == {
        "EM JORGE PASSOS": "Rede Municipal de Caraguatatuba",
        "EM UBATUBA CENTRO": "Rede Municipal de Ubatuba"}
    for nome in ("Ana", "Bruno", "Carla", "Duda"):
        assert nome not in glob.text                          # consolidado sem PII

    # (b) SELECIONA uma rede (drill-down) → o painel daquela rede específica.
    dash_rede = admin.get(f"/api/v1/redes/{c['rede']}/dashboard").json()
    assert dash_rede["totais"]["escolas"] == 1 and dash_rede["totais"]["alunos"] == 3

    # (c) SELECIONA uma escola dentro da rede → o Dashboard da escola (o global
    #     acessa qualquer escola, de qualquer rede).
    dash_esc = admin.get(f"/api/v1/escolas/{c['escola']}/dashboard").json()
    assert dash_esc["total_alunos"] == 3 and dash_esc["total_turmas"] == 2
    # e a escola da OUTRA rede também (nada de isolamento para o admin global).
    assert admin.get(f"/api/v1/escolas/{esc2.id}/dashboard").json()["total_alunos"] == 1

    # (d) A visão consolidada é STATELESS: reconsultar o global entrega sempre os
    #     mesmos 2 redes/2 escolas/4 alunos (a jornada de UI "voltar para todas as
    #     redes" — estado do componente — é coberta em web/PanoramaGlobal.test.tsx).
    de_volta = admin.get("/api/v1/redes/panorama-global").json()
    assert de_volta["totais"]["redes"] == 2 and de_volta["totais"]["alunos"] == 4
