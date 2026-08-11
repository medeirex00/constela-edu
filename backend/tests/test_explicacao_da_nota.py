"""A EXPLICAÇÃO da nota tem de descrever a conta que foi feita.

Contexto: numa rede que só contratou um módulo, ``pesos.geral`` é redistribuído
(só Leitura ⇒ ``{elefante: 1,0}``). Se a explicação gravada em
``detalhes.geral.pesos`` continuasse dizendo 50/50, a tela "Como esta nota foi
calculada" (PRD §45, que professor e coordenador enxergam) exibiria uma equação
que NÃO fecha com a própria nota — "Matific 100 × 50% + Elefante 70 × 50% = 70".

O que estes testes travam: para todo contrato possível, a soma das parcelas
descritas em ``detalhes.geral.pesos`` reproduz exatamente ``nota_geral``.
Eles não olham o VALOR da nota (isso é o motor, e não mudou) — olham a coerência
entre o número e a explicação dele.
"""
import pytest

from app.models import (
    Aluno,
    Escola,
    Importacao,
    Matricula,
    Nota,
    Rede,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
)
from app.services import modulos as svc
from app.services import scoring


@pytest.fixture()
def rede_com_notas(db):
    """Rede + escola + 6 alunos com dados das DUAS plataformas."""
    rede = Rede(nome="Rede Explicacao", status="ativa")
    db.add(rede)
    db.flush()
    esc = Escola(nome="EM Explicacao", ano_letivo_ativo=2026, rede_id=rede.id,
                 status="ativa")
    db.add(esc)
    db.flush()
    turma = Turma(escola_id=esc.id, nome="1ºA", ano_escolar="1º Ano",
                  ano_letivo=2026, status="ativa")
    db.add(turma)
    db.flush()
    imp = Importacao(escola_id=esc.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    for i in range(6):
        a = Aluno(escola_id=esc.id, nome=f"Crianca {i}", status="ativo")
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=esc.id, aluno_id=a.id, turma_id=turma.id,
                         ano_letivo=2026))
        db.add(SnapshotElefante(escola_id=esc.id, aluno_id=a.id, importacao_id=imp.id,
                                livros_unicos=5 + i, tempo_leitura_min=60 + i * 10,
                                questoes_tentativas=20, questoes_acertos=16))
        db.add(SnapshotMatific(escola_id=esc.id, aluno_id=a.id, importacao_id=imp.id,
                               atividades=20 + i, estrelas=100 + i * 10,
                               pontuacao_media=4.0))
    db.commit()
    scoring.recalcular_escola(db, esc.id)
    return rede, esc


def _explicacoes(db, escola_id):
    """``[(pesos_exibidos, nota_geral, nota_elefante, nota_matific), ...]``."""
    return [
        (n.detalhes["geral"]["pesos"], n.nota_geral, n.nota_elefante, n.nota_matific)
        for n in db.query(Nota).filter(Nota.escola_id == escola_id)
    ]


def _conferir_fecha(db, escola_id):
    """A conta exibida reproduz a nota gravada, para TODO aluno."""
    linhas = _explicacoes(db, escola_id)
    assert linhas, "o cenário precisa ter notas"
    for pesos, geral, ele, mat in linhas:
        assert sum(pesos.values()) == pytest.approx(100.0, abs=0.01), (
            f"os percentuais exibidos precisam somar 100%: {pesos}")
        conta = sum((mat if chave == "matific" else ele) * (pct / 100)
                    for chave, pct in pesos.items())
        assert conta == pytest.approx(geral, abs=0.05), (
            f"a explicação {pesos} dá {conta:.2f}, mas a nota gravada é {geral}")
    return linhas


def test_ambos_contratados_explica_as_duas_plataformas(rede_com_notas, db):
    _, esc = rede_com_notas
    linhas = _conferir_fecha(db, esc.id)
    for pesos, *_ in linhas:
        assert set(pesos) == {"matific", "elefante"}
        assert pesos == {"matific": 50.0, "elefante": 50.0}   # comportamento original


def test_somente_leitura_explica_so_o_elefante_e_fecha(rede_com_notas, db):
    rede, esc = rede_com_notas
    svc.definir(db, rede.id, "matematica", False)
    db.commit()
    scoring.recalcular_escola(db, esc.id)

    linhas = _conferir_fecha(db, esc.id)
    for pesos, geral, ele, _mat in linhas:
        assert set(pesos) == {"elefante"}, "Matific não pode aparecer na conta"
        assert pesos["elefante"] == pytest.approx(100.0)
        assert geral == pytest.approx(ele, abs=0.01)


def test_somente_matematica_explica_so_o_matific_e_fecha(rede_com_notas, db):
    rede, esc = rede_com_notas
    svc.definir(db, rede.id, "leitura", False)
    db.commit()
    scoring.recalcular_escola(db, esc.id)

    linhas = _conferir_fecha(db, esc.id)
    for pesos, geral, _ele, mat in linhas:
        assert set(pesos) == {"matific"}, "Elefante não pode aparecer na conta"
        assert pesos["matific"] == pytest.approx(100.0)
        assert geral == pytest.approx(mat, abs=0.01)


def test_religar_os_dois_volta_ao_comportamento_original(rede_com_notas, db):
    rede, esc = rede_com_notas
    antes = _explicacoes(db, esc.id)

    svc.definir(db, rede.id, "matematica", False)
    db.commit()
    scoring.recalcular_escola(db, esc.id)
    assert _explicacoes(db, esc.id) != antes          # de fato mudou

    svc.definir(db, rede.id, "matematica", True)
    db.commit()
    scoring.recalcular_escola(db, esc.id)
    assert _explicacoes(db, esc.id) == antes          # e voltou, bit a bit
    _conferir_fecha(db, esc.id)


def test_simulador_explica_com_os_mesmos_pesos_do_recalculo(rede_com_notas, db):
    """O simulador (Métricas → Simulador) monta a MESMA estrutura `geral.pesos`
    por um caminho próprio. Se ele ficasse de fora, a conta voltaria a não fechar
    justamente na tela que existe para explicar a nota."""
    from fastapi.testclient import TestClient

    from app.core.security import hash_senha
    from app.main import app
    from app.models import Usuario

    rede, esc = rede_com_notas
    db.add(Usuario(escola_id=esc.id, nome="Coord", email="coord@expl.local",
                   senha_hash=hash_senha("s3nh4"), cargo="coordenador"))
    db.commit()
    cliente = TestClient(app)
    r = cliente.post("/api/v1/auth/login",
                     data={"username": "coord@expl.local", "password": "s3nh4"})
    cliente.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    corpo = {"ano_escolar": "1º Ano", "atividades": 20, "estrelas": 100,
             "pontuacao_media": 4.0, "livros_unicos": 5, "tempo_leitura_min": 60,
             "questoes_tentativas": 20, "questoes_acertos": 16, "livros_por_nivel": {}}

    def simular():
        resp = cliente.post(f"/api/v1/escolas/{esc.id}/simulador", json=corpo)
        assert resp.status_code == 200, resp.text
        return resp.json()["geral"]

    assert set(simular()["pesos"]) == {"matific", "elefante"}

    svc.definir(db, rede.id, "matematica", False)
    db.commit()
    geral = simular()
    assert set(geral["pesos"]) == {"elefante"}
    assert geral["pesos"]["elefante"] == pytest.approx(100.0)


def test_o_valor_da_nota_nao_mudou_com_a_correcao(rede_com_notas, db):
    """Blindagem: corrigimos a EXPLICAÇÃO, não a fórmula. Com os dois módulos —
    o estado de toda rede hoje — a nota continua sendo a média 50/50."""
    _, esc = rede_com_notas
    for _pesos, geral, ele, mat in _explicacoes(db, esc.id):
        assert geral == pytest.approx(round(mat * 0.5 + ele * 0.5, 2), abs=0.01)
