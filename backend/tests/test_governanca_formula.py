"""Governança da fórmula (item 2/10 do mandato): os PARÂMETROS MATEMÁTICOS do
motor são oficiais — só o Admin Global grava; a escola consulta.

"A escola usa o Constela; a escola não administra a matemática interna."

Regras travadas aqui:
  * PUT /pesos/{ns}, /referencias, /elefante-extra, /dificuldade e
    /pontuacao-turma → 403 para o admin e para o coordenador DA ESCOLA;
    200 para o Admin Global — o mesmo critério de /niveis e /perfil-scoring;
  * os GETs correspondentes continuam 200 para o coordenador (leitura);
  * PUT /perfil-scoring segue exclusivo do Admin Global;
  * no perfil INSTITUCIONAL (o padrão de toda escola) um PUT de pesos feito pelo
    Admin Global NÃO move nota_elefante/nota_matific gravadas — o motor usa
    PESOS_PADRAO (`scoring._insumos_institucionais`); só o perfil PERSONALIZADO
    lê a config local, e ligá-lo já é decisão do Admin Global.
"""
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_senha
from app.main import app
from app.models import (
    Importacao,
    NivelDificuldade,
    Nota,
    Rede,
    SnapshotElefante,
    SnapshotMatific,
    Usuario,
)
from app.services import scoring

API = "/api/v1"


def _login(email: str, senha: str = "s3nh4") -> TestClient:
    c = TestClient(app)
    r = c.post(f"{API}/auth/login", data={"username": email, "password": senha})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _coordenador(db, escola_id: int) -> TestClient:
    """Coordenador DA ESCOLA (sem rede — não é Secretaria)."""
    db.add(Usuario(escola_id=escola_id, nome="Coordenador", email="coord@governanca.local",
                   senha_hash=hash_senha("s3nh4"), cargo="coordenador"))
    db.commit()
    return _login("coord@governanca.local")


def _secretaria(db, escola) -> TestClient:
    """SECRETARIA: cargo coordenador + rede vinculada (mesmo padrão de
    tests/test_rbac_secretaria.py). A escola entra na rede dela."""
    rede = Rede(nome="Rede Governança", status="ativa")
    db.add(rede)
    db.flush()
    escola.rede_id = rede.id
    db.add(Usuario(escola_id=escola.id, nome="Secretaria", email="sec@governanca.local",
                   senha_hash=hash_senha("s3nh4"), cargo="coordenador", rede_id=rede.id))
    db.commit()
    return _login("sec@governanca.local")


def _base(escola_id: int) -> str:
    return f"{API}/escolas/{escola_id}/configuracoes"


def _rotas_put(db, escola_completa) -> list[tuple[str, object]]:
    """As 5 rotas de ESCRITA de parâmetro, cada uma com um corpo VÁLIDO — para
    o 403 ser de autorização, nunca de validação."""
    escola = escola_completa["escola"]
    turma = escola_completa["turma"]
    nivel = db.execute(select(NivelDificuldade).where(
        NivelDificuldade.escola_id == escola.id).order_by(NivelDificuldade.ordem)).scalars().first()
    base = _base(escola.id)
    return [
        (f"{base}/pesos/geral", {"valores": {"matific": 40.0, "elefante": 60.0}}),
        (f"{base}/referencias", {"modo": "auto", "valores_manuais": {}}),
        (f"{base}/elefante-extra", {"ativo": True, "pontos_por_livro": 1.5}),
        (f"{base}/dificuldade", [{"ano_escolar": "3º Ano", "nivel_id": nivel.id, "pontos": 2.0}]),
        (f"{base}/pontuacao-turma", {"turma_id": turma.id, "pontos": {"AA": 3.0}}),
    ]


ROTAS_GET = ["pesos/geral", "pesos/elefante", "pesos/matific", "referencias",
             "elefante-extra", "dificuldade", "pontuacao-turma", "perfil-scoring",
             "dificuldade-livro"]


# --------------------------------------------------------------------------
# Escrita: só o Admin Global
# --------------------------------------------------------------------------

def test_admin_da_escola_nao_grava_parametros(cliente, db, escola_completa):
    for url, corpo in _rotas_put(db, escola_completa):
        r = cliente.put(url, json=corpo)
        assert r.status_code == 403, f"{url} -> {r.status_code} {r.text}"


def test_coordenador_da_escola_nao_grava_parametros(cliente, db, escola_completa):
    coord = _coordenador(db, escola_completa["escola"].id)
    for url, corpo in _rotas_put(db, escola_completa):
        r = coord.put(url, json=corpo)
        assert r.status_code == 403, f"{url} -> {r.status_code} {r.text}"


def test_admin_global_grava_parametros(cliente_global, db, escola_completa):
    for url, corpo in _rotas_put(db, escola_completa):
        r = cliente_global.put(url, json=corpo)
        assert r.status_code == 200, f"{url} -> {r.status_code} {r.text}"


def test_coordenador_le_todos_os_parametros(cliente, db, escola_completa):
    """A escola CONSULTA: todos os GETs de configuração seguem 200 para o
    coordenador (e para o admin da escola)."""
    escola_id = escola_completa["escola"].id
    coord = _coordenador(db, escola_id)
    for rota in ROTAS_GET:
        for c in (coord, cliente):
            r = c.get(f"{_base(escola_id)}/{rota}")
            assert r.status_code == 200, f"{rota} -> {r.status_code} {r.text}"


def test_secretaria_le_todos_os_parametros_e_nao_grava(db, escola_completa):
    """A página 'Pontuação' também é aberta pela Secretaria: todos os GETs
    (inclusive /perfil-scoring e /dificuldade-livro) são 200; as 5 escritas de
    parâmetro são 403 — e nada é gravado."""
    escola = escola_completa["escola"]
    sec = _secretaria(db, escola)
    base = _base(escola.id)
    for rota in ROTAS_GET:
        r = sec.get(f"{base}/{rota}")
        assert r.status_code == 200, f"{rota} -> {r.status_code} {r.text}"
    pesos_antes = sec.get(f"{base}/pesos/geral").json()
    for url, corpo in _rotas_put(db, escola_completa):
        r = sec.put(url, json=corpo)
        assert r.status_code == 403, f"{url} -> {r.status_code} {r.text}"
    assert sec.get(f"{base}/pesos/geral").json() == pesos_antes


def test_perfil_scoring_segue_exclusivo_do_admin_global(cliente, cliente_global, db,
                                                        escola_completa):
    escola_id = escola_completa["escola"].id
    url = f"{_base(escola_id)}/perfil-scoring"
    coord = _coordenador(db, escola_id)
    assert cliente.put(url, json={"modo": "personalizado"}).status_code == 403
    assert coord.put(url, json={"modo": "personalizado"}).status_code == 403
    assert cliente.get(url).json()["modo"] == "institucional"
    r = cliente_global.put(url, json={"modo": "personalizado"})
    assert r.status_code == 200, r.text
    assert coord.get(url).json()["modo"] == "personalizado"


# --------------------------------------------------------------------------
# Perfil institucional: a config local NÃO entra na nota
# --------------------------------------------------------------------------

def _semear(db, escola_completa) -> int:
    """3 alunos com perfis bem diferentes nas duas plataformas, recalculados."""
    escola = escola_completa["escola"]
    imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    # (livros por nível, tempo, tentativas, acertos, atividades, estrelas)
    perfis = [({"D": 10}, 0, 40, 30, 50, 120),
              ({"AA": 2}, 500, 4, 1, 10, 20),
              ({"E": 5}, 100, 20, 10, 30, 60)]
    for aluno, (por_nivel, tempo, tent, acert, ativ, estrelas) in zip(
            escola_completa["alunos"], perfis):
        db.add(SnapshotElefante(
            escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
            livros_unicos=sum(por_nivel.values()), livros_por_nivel=dict(por_nivel),
            tempo_leitura_min=tempo, questoes_tentativas=tent, questoes_acertos=acert))
        db.add(SnapshotMatific(
            escola_id=escola.id, aluno_id=aluno.id, importacao_id=imp.id,
            atividades=ativ, estrelas=estrelas, pontuacao_media=round(estrelas / ativ, 2)))
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    return escola.id


def _notas(db, escola_id: int) -> dict:
    db.expire_all()
    return {
        n.aluno_id: {
            "local": (n.nota_elefante, n.nota_matific),
            "institucional": (n.nota_elefante_institucional, n.nota_matific_institucional),
        }
        for n in db.execute(select(Nota).where(Nota.escola_id == escola_id)).scalars()
    }


def test_perfil_institucional_ignora_pesos_gravados_pelo_admin_global(
        cliente, cliente_global, db, escola_completa):
    escola_id = _semear(db, escola_completa)
    base = _base(escola_id)
    assert cliente.get(f"{base}/perfil-scoring").json()["modo"] == "institucional"
    antes = _notas(db, escola_id)
    assert len(antes) == 3
    assert any(v["local"][0] > 0 for v in antes.values())
    assert any(v["local"][1] > 0 for v in antes.values())

    # O Admin Global grava pesos bem diferentes dos padrão (35/30/30/5 e 40/35/25).
    r = cliente_global.put(f"{base}/pesos/elefante", json={"valores": {
        "livros": 5.0, "dificuldade": 5.0, "questoes": 10.0, "tempo": 80.0}})
    assert r.status_code == 200, r.text
    r = cliente_global.put(f"{base}/pesos/matific", json={"valores": {
        "atividades": 80.0, "media": 10.0, "estrelas": 10.0}})
    assert r.status_code == 200, r.text
    # A config LOCAL foi gravada (o GET mostra)...
    assert cliente.get(f"{base}/pesos/elefante").json()["valores"]["tempo"] == 80.0
    # ...mas o motor, no perfil institucional, recalculou com PESOS_PADRAO: nada
    # se moveu — nem as notas locais, nem (obviamente) as institucionais.
    assert _notas(db, escola_id) == antes

    # Contraste: só quando o Admin Global liga o perfil PERSONALIZADO a config
    # local passa a valer — as notas LOCAIS mudam; a régua institucional nunca.
    r = cliente_global.put(f"{base}/perfil-scoring", json={"modo": "personalizado"})
    assert r.status_code == 200, r.text
    depois = _notas(db, escola_id)
    assert {k: v["local"] for k, v in depois.items()} != {k: v["local"] for k, v in antes.items()}
    assert ({k: v["institucional"] for k, v in depois.items()}
            == {k: v["institucional"] for k, v in antes.items()})
