"""S_G_AJUSTE-1 (parte do Relatório por Período): o ajuste manual do Elefante não é coleta.

O Admin Global corrige o retrato do Elefante de uma criança numa escola integrada (o
"fale com o suporte" da governança). A rota grava um retrato NOVO, ligado a uma
``Importacao`` do tipo ``"manual"``. O contador de questões do Elefante é vitalício e a
coleta seguinte traz de novo o número da plataforma: se o ajuste servisse de borda, o
degrau entre o número digitado e o coletado virava "Questões do período" (corrigir para
baixo) ou apagava o ganho real da criança (corrigir para cima, "contador regrediu").

A regra é a do Matific (``matific_destaque.sem_ajustes_superados``): o retrato manual
vale como base e como estado atual só enquanto nenhuma coleta vier depois dele; sem
coleta depois, ele é o estado vigente e continua valendo.

Datas fixas no ano da ``escola_completa`` (2026): o período é fechado com o relógio de
hoje ou adiantado. Dados fictícios.
"""
from datetime import datetime

import pytest
from sqlalchemy import select

from app.models import Importacao, PlataformaCredencial, SnapshotElefante

API = "/api/v1"

COLETA_A = datetime(2026, 9, 1, 15, 0)     # 12h de Brasília
AJUSTE = datetime(2026, 9, 5, 15, 0)       # antes do período
COLETA_B = datetime(2026, 9, 12, 15, 0)    # dentro do período
PERIODO = {"periodo": "personalizado", "inicio": "2026-09-06", "fim": "2026-09-14",
           "plataformas": ["elefante"]}


def _coleta(db, escola_id, quando, valores):
    """Coleta da sincronização: ``Importacao`` que não é manual. ``valores``:
    {aluno_id: (tentativas, acertos)}."""
    imp = Importacao(escola_id=escola_id, usuario_id=None, plataforma="elefante",
                     tipo="api", qtd_alunos=len(valores))
    db.add(imp)
    db.flush()
    for aid, (tent, acer) in valores.items():
        db.add(SnapshotElefante(escola_id=escola_id, aluno_id=aid, importacao_id=imp.id,
                                data_referencia=quando, livros_unicos=10,
                                tempo_leitura_min=100, questoes_tentativas=tent,
                                questoes_acertos=acer, livros_por_nivel={"AA": 10}))
    db.commit()


def _ajuste_do_suporte(db, cliente_global, escola_id, aluno_id, tentativas, acertos,
                       quando):
    """O ajuste pela rota real (Admin Global numa escola integrada); só a data do
    retrato é trazida para ``quando``."""
    r = cliente_global.put(
        f"{API}/escolas/{escola_id}/elefante/{aluno_id}",
        json={"livros_unicos": 10, "tempo_leitura_min": 100,
              "questoes_tentativas": tentativas, "questoes_acertos": acertos,
              "livros_por_nivel": {"AA": 10},
              "motivo": "suporte: o relatório da plataforma contou errado"})
    assert r.status_code == 200, r.text
    snap = db.execute(
        select(SnapshotElefante).join(Importacao,
                                      Importacao.id == SnapshotElefante.importacao_id)
        .where(SnapshotElefante.aluno_id == aluno_id, Importacao.tipo == "manual")
        .order_by(SnapshotElefante.id.desc()).limit(1)).scalar_one()
    snap.data_referencia = quando
    db.commit()


def _cenario(db, cliente_global, escola_completa, ajuste: tuple[int, int] | None):
    escola = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]
    db.add(PlataformaCredencial(escola_id=escola.id, plataforma="elefante",
                                segredo_cifrado="cifrado-de-teste", status="valida"))
    db.commit()
    _coleta(db, escola.id, COLETA_A, {ana.id: (100, 80), joao.id: (100, 80),
                                      sofia.id: (100, 80)})
    if ajuste is not None:
        _ajuste_do_suporte(db, cliente_global, escola.id, ana.id, *ajuste, AJUSTE)
    # A coleta seguinte traz de novo o número da plataforma: Ana +5 (4 certas); João e
    # Sofia +10 (8 certas) cada.
    _coleta(db, escola.id, COLETA_B, {ana.id: (105, 84), joao.id: (110, 88),
                                      sofia.id: (110, 88)})
    return escola, ana


def _questoes(cliente, escola_id, aluno_id):
    r = cliente.get(f"{API}/escolas/{escola_id}/relatorios/periodo", params=PERIODO)
    assert r.status_code == 200, r.text
    corpo = r.json()
    ele = corpo["elefante"]
    linha = next(a for a in corpo["por_aluno"] if a["aluno_id"] == aluno_id)
    return ((ele["questoes_tentativas"], ele["questoes_acertos"]),
            (linha["elefante"] or {}).get("questoes_tentativas"),
            ele["cobertura_questoes"])


def test_controle_sem_ajuste(cliente, cliente_global, db, escola_completa):
    escola, ana = _cenario(db, cliente_global, escola_completa, None)
    total, da_ana, _ = _questoes(cliente, escola.id, ana.id)
    assert total == (25, 20)
    assert da_ana == 5


@pytest.mark.parametrize("ajuste", [(50, 40), (150, 120)],
                         ids=["corrigido_para_baixo", "corrigido_para_cima"])
def test_ajuste_desmentido_pela_coleta_seguinte_nao_e_borda(cliente, cliente_global, db,
                                                            escola_completa, ajuste):
    escola, ana = _cenario(db, cliente_global, escola_completa, ajuste)
    total, da_ana, cobertura = _questoes(cliente, escola.id, ana.id)
    print(f"\najuste {ajuste}: escola {total}; Ana {da_ana}; "
          f"regrediu={cobertura.get('alunos_contador_regrediu')}")
    # Para baixo, o degrau 50 → 105 virava 55 questões "do período"; para cima,
    # 150 → 105 tirava Ana da conta ("contador regrediu").
    assert total == (25, 20), (
        "o número digitado pelo suporte serviu de borda das Questões do período")
    assert da_ana == 5
    assert not cobertura.get("alunos_contador_regrediu")


def test_ajuste_sem_coleta_depois_continua_valendo(cliente, cliente_global, db,
                                                   escola_completa):
    """Sem coleta depois do ajuste, ele é o estado vigente: mede o fim do período."""
    escola = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]
    _coleta(db, escola.id, COLETA_A, {ana.id: (100, 80), joao.id: (100, 80),
                                      sofia.id: (100, 80)})
    # O suporte completa as questões que a plataforma deixou de contar: 100 → 110.
    _ajuste_do_suporte(db, cliente_global, escola.id, ana.id, 110, 88, AJUSTE)
    r = cliente.get(f"{API}/escolas/{escola.id}/relatorios/periodo",
                    params={**PERIODO, "inicio": "2026-09-03", "fim": "2026-09-08"})
    assert r.status_code == 200, r.text
    corpo = r.json()
    linha = next(a for a in corpo["por_aluno"] if a["aluno_id"] == ana.id)
    assert (corpo["elefante"]["questoes_tentativas"],
            corpo["elefante"]["questoes_acertos"]) == (10, 8)
    assert linha["elefante"]["questoes_tentativas"] == 10
