"""O pacote do app (/sincronizacao) não entrega à Secretaria uma escola com tudo
zerado (auditoria técnica, MOBILE-1 — parte do servidor).

A Secretaria entra no app (login e /escolas funcionam para ela) e o Painel e o
Ranking leem ``GET /escolas/{id}/sincronizacao``. O pacote recorta tudo por
``permissoes.turmas_permitidas``, que para ela é a lista VAZIA de propósito (nunca
vê nome de criança) — e ``montar_dashboard(turma_ids=[])`` aplicava esse recorte
também aos números: alunos, turmas, média, livros, leitura e atividades saíam 0. O
app mostrava "0 Alunos · Média geral 0,0 · ... · Turmas 0" de uma escola com
centenas de crianças, como se fossem os números dela. Na web ela nunca vê esse
painel: vai para o Panorama da Rede.

Agora o pacote responde 403 à Secretaria, dizendo onde ela acompanha a rede, em vez
de números falsos. Uma visão da rede DENTRO do app seria decisão de produto (com a
regra de grupo pequeno); parar de mostrar zero falso não é. Gestão, admin global e
professor seguem com o pacote de sempre. Dados 100% fictícios.
"""
import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import (
    Aluno, Configuracao, Escola, Importacao, Matricula, NivelDificuldade, Professor,
    Rede, ReferenciaNormalizacao, SnapshotElefante, SnapshotMatific, Turma, Usuario,
)
from app.services import scoring

SENHA = "s3nh4-ficticia-sinc"
NUMEROS = ("total_alunos", "total_turmas", "media_geral", "total_livros",
           "tempo_leitura_min", "total_atividades")


def _login(email):
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", data={"username": email, "password": SENHA})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


@pytest.fixture()
def cenario(db):
    rede = Rede(nome="Rede Ficticia Sinc", status="ativa")
    db.add(rede)
    db.flush()
    esc = Escola(nome="EM FICTICIA SINC", ano_letivo_ativo=2026, status="ativa",
                 rede_id=rede.id)
    db.add(esc)
    db.flush()
    for ns, val in scoring.PESOS_PADRAO.items():
        db.add(Configuracao(escola_id=esc.id, namespace=ns, chave="valores", valor=val))
    db.add(NivelDificuldade(escola_id=esc.id, nome="N2", codigo="n2", codigos=["D"],
                            pontos_padrao=4.0, ordem=1))
    db.add(ReferenciaNormalizacao(escola_id=esc.id, modo="auto"))
    prof = Professor(escola_id=esc.id, nome="Prof Ficticia",
                     email="prof@sinc-ficticio.local")
    db.add(prof)
    db.flush()
    turma = Turma(escola_id=esc.id, nome="5º Ano A", ano_escolar="5º Ano",
                  ano_letivo=2026, status="ativa", professor_id=prof.id)
    db.add(turma)
    db.flush()
    imp = Importacao(escola_id=esc.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    for i, nome in enumerate(["Aluna Um Sinc", "Aluno Dois Sinc", "Aluna Tres Sinc",
                              "Aluno Quatro Sinc"]):
        a = Aluno(escola_id=esc.id, nome=nome, status="ativo")
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=esc.id, aluno_id=a.id, turma_id=turma.id,
                         ano_letivo=2026))
        if i < 3:
            db.add(SnapshotElefante(escola_id=esc.id, aluno_id=a.id, importacao_id=imp.id,
                                    livros_unicos=3 + i, tempo_leitura_min=30 + i,
                                    questoes_tentativas=10, questoes_acertos=6,
                                    livros_por_nivel={"D": 3 + i}))
        if i < 2:
            db.add(SnapshotMatific(escola_id=esc.id, aluno_id=a.id, importacao_id=imp.id,
                                   atividades=5 + i, pontuacao_media=3.0, estrelas=10 + i))
    contas = {
        "global": dict(escola_id=esc.id, nome="Global", cargo="admin", is_global=True,
                       email="global@sinc-ficticio.local"),
        "secretaria": dict(escola_id=None, nome="Secretaria", cargo="coordenador",
                           rede_id=rede.id, email="sec@sinc-ficticio.local"),
        "coordenador": dict(escola_id=esc.id, nome="Coord", cargo="coordenador",
                            email="coord@sinc-ficticio.local"),
        "professor": dict(escola_id=esc.id, nome="Prof", cargo="professor",
                          email="prof@sinc-ficticio.local"),
    }
    for dados in contas.values():
        db.add(Usuario(senha_hash=hash_senha(SENHA), **dados))
    db.commit()
    scoring.recalcular_escola(db, esc.id)
    return {"escola": esc,
            "clientes": {p: _login(d["email"]) for p, d in contas.items()}}


def test_secretaria_nao_recebe_a_escola_zerada(cenario):
    esc = cenario["escola"]
    coord = cenario["clientes"]["coordenador"].get(
        f"/api/v1/escolas/{esc.id}/sincronizacao")
    assert coord.status_code == 200, coord.text
    assert coord.json()["dashboard"]["total_alunos"] == 4   # controle: a escola tem 4

    r = cenario["clientes"]["secretaria"].get(f"/api/v1/escolas/{esc.id}/sincronizacao")
    numeros = ({k: r.json()["dashboard"][k] for k in NUMEROS}
               if r.status_code == 200 else None)
    assert r.status_code == 403, f"a Secretaria recebeu a escola com {numeros}"
    detalhe = r.json()["detail"]
    assert "Panorama da Rede" in detalhe
    assert "Secretaria" in detalhe


@pytest.mark.parametrize("perfil", ["global", "coordenador", "professor"])
def test_os_demais_perfis_seguem_com_o_pacote(cenario, perfil):
    esc = cenario["escola"]
    r = cenario["clientes"][perfil].get(f"/api/v1/escolas/{esc.id}/sincronizacao")
    assert r.status_code == 200, r.text
    pacote = r.json()
    for chave in ("gerado_em", "dashboard", "ranking", "evolucao", "alertas", "mural"):
        assert chave in pacote
    # Professor: a turma é dele, então vê as 4 crianças; gestão vê a escola inteira.
    assert pacote["dashboard"]["total_alunos"] == 4
    assert pacote["dashboard"]["total_turmas"] == 1
    # A aba Ranking Geral lista as 3 que têm dado: a quarta não tem dado nenhum e
    # não ganha posição nem 0,0 (DEC-19).
    assert len(pacote["ranking"]) == 3


def test_secretaria_segue_lendo_a_lista_de_escolas(cenario):
    """O resto do caminho do app continua: o login e o /escolas respondem a ela."""
    r = cenario["clientes"]["secretaria"].get("/api/v1/escolas")
    assert r.status_code == 200
    assert cenario["escola"].id in [e["id"] for e in r.json()]
