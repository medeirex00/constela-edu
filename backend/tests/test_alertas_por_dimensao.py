"""Alerta "abaixo da turma" POR DIMENSÃO (Arquitetura 2: ausência nunca vira
zero — nem no alerta).

Antes, a mediana era de `nota_geral` (legado) sobre a turma inteira: quem não
tinha dado de uma plataforma entrava como 0, puxava a referência para baixo e
ainda disparava "está com nota 0,0". Agora cada dimensão tem a sua mediana,
só entre os aferidos nela, e o aluno só é comparado onde foi aferido.
Dados sintéticos.
"""
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.models import Importacao, Nota, SnapshotElefante
from app.services import insights


def _cenario(db, escola_completa, notas_leitura, legado=None):
    """Snapshots do Elefante (para não cair em `sem_dados`) e a linha de
    `notas` de cada aluno: aferido só em Leitura, com a nota dada."""
    escola = escola_completa["escola"]
    imp = Importacao(escola_id=escola.id, plataforma="elefante", tipo="seed")
    db.add(imp)
    db.flush()
    agora = datetime.now(timezone.utc).replace(tzinfo=None)
    for i, (aluno, nota_l) in enumerate(zip(escola_completa["alunos"], notas_leitura)):
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id,
                                importacao_id=imp.id, livros_unicos=5,
                                data_referencia=agora))
        db.add(Nota(escola_id=escola.id, aluno_id=aluno.id,
                    ano_letivo=escola.ano_letivo_ativo,
                    nota_elefante=nota_l, aferido_leitura=True,
                    nota_matific=0.0, aferido_matematica=False,
                    nota_geral=(legado[i] if legado else nota_l)))
    db.commit()
    return escola


def _abaixo(db, escola):
    return [a for a in insights.alertas_da_escola(db, escola.id)
            if a["tipo"] == "abaixo_da_turma"]


def test_alerta_diz_a_materia_e_compara_so_entre_aferidos_dela(db, escola_completa):
    escola = _cenario(db, escola_completa, [80.0, 70.0, 10.0])
    alertas = _abaixo(db, escola)
    assert len(alertas) == 1
    alerta = alertas[0]
    assert alerta["aluno_id"] == escola_completa["alunos"][2].id
    assert alerta["dimensao"] == "leitura"
    assert "em Leitura" in alerta["texto"]
    assert "10.0" in alerta["texto"] and "(70.0)" in alerta["texto"]


def test_sem_dado_de_matematica_ninguem_e_acusado_em_matematica(db, escola_completa):
    # Ninguém aferido em Matemática (nota_matific = 0, aferido = False): antes,
    # com a nota geral, isso não aparecia; agora a dimensão nem tem mediana.
    escola = _cenario(db, escola_completa, [60.0, 60.0, 60.0])
    assert not [a for a in _abaixo(db, escola) if a.get("dimensao") == "matematica"]
    assert _abaixo(db, escola) == []


def test_o_alerta_nao_depende_do_legado(db, escola_completa):
    # A nota geral legada diz o contrário da nota de Leitura: o alerta segue a
    # dimensão (o aluno 3, fraco em Leitura), não a coluna legada.
    escola = _cenario(db, escola_completa, [80.0, 70.0, 10.0],
                      legado=[5.0, 90.0, 95.0])
    alertas = _abaixo(db, escola)
    assert [a["aluno_id"] for a in alertas] == [escola_completa["alunos"][2].id]


def test_certificado_geral_usa_a_guarda_por_dimensao(db, escola_completa):
    """A guarda de emissão do certificado geral lê as dimensões: sem nenhuma
    dimensão com nota > 0 não emite, mesmo com a nota geral legada > 0."""
    escola = _cenario(db, escola_completa, [0.0, 70.0, 10.0],
                      legado=[50.0, 70.0, 10.0])
    for aluno in escola_completa["alunos"]:
        aluno.da_lista_piloto = True   # a guarda da Lista Piloto vem antes
    db.commit()
    r = TestClient(app).post("/api/v1/auth/login",
                             data={"username": "admin@teste.local", "password": "s3nh4"})
    cli = TestClient(app)
    cli.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    sem = escola_completa["alunos"][0].id     # Leitura 0,0 e nada em Matemática
    r = cli.get(f"/api/v1/escolas/{escola.id}/certificados/{sem}")
    assert r.status_code == 422 and "nota calculada" in r.text, r.text
    com = escola_completa["alunos"][1].id     # Leitura 70,0
    r = cli.get(f"/api/v1/escolas/{escola.id}/certificados/{com}")
    assert r.status_code == 200, r.text
    assert r.content[:5] == b"%PDF-"
