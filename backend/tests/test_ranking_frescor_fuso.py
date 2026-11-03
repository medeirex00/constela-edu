"""O DIA do retrato no selo de frescor é o dia de BRASÍLIA.

O banco grava ``data_referencia`` (e ``finalizada_em``) em UTC naive
(``sync/fuso.py``); o "hoje" do frescor é o de Brasília. Tirar ``.date()`` direto
do UTC fazia a coleta manual das 22h30 de 20/10 (01h30 UTC de 21/10) aparecer
como "dados de 21/10" no dia 20, com ``dias_desde_dado = -1``, e dava ao dado um
dia a mais antes de virar "desatualizado": o retrato das 23h30 de 12/10 ainda
saía "em dia" em 20/10, com oito dias de Brasília. O corte dos retratos antigos
(meia-noite naive comparada com UTC) tinha o mesmo desvio de 3 horas.

Os testes de ``test_ranking_frescor.py`` só usam 10h da manhã, quando UTC e
Brasília caem no mesmo dia — por isso não pegavam o caso.
"""
from datetime import date, datetime, time, timedelta

from app.models import Importacao, SnapshotElefante, SnapshotMatific
from app.models.sincronizacao import SincronizacaoExecucao
from app.services import frescor_ranking
from app.sync import fuso

API = "/api/v1"
HOJE = date(2026, 10, 20)


def _imp(db, escola_id):
    imp = Importacao(escola_id=escola_id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    return imp


def _retrato_e(db, escola_id, imp, aluno_id, quando_utc):
    db.add(SnapshotElefante(escola_id=escola_id, aluno_id=aluno_id, importacao_id=imp.id,
                            data_referencia=quando_utc, livros_unicos=3,
                            tempo_leitura_min=30, livros_por_nivel={"D": 3}))


def test_coleta_da_noite_e_do_dia_de_brasilia(db, escola_completa):
    """22h30 de 20/10 em Brasília = 01h30 UTC de 21/10. Consultado em 20/10, o
    dado é de HOJE (0 dias), nunca "de amanhã" (-1)."""
    escola = escola_completa["escola"]
    imp = _imp(db, escola.id)
    noite = datetime(2026, 10, 21, 1, 30)          # UTC naive, como o banco grava
    for aluno in escola_completa["alunos"]:
        _retrato_e(db, escola.id, imp, aluno.id, noite)
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id,
                               importacao_id=imp.id, data_referencia=noite,
                               atividades=10, estrelas=20, pontuacao_media=2.0))
    db.add(SincronizacaoExecucao(escola_id=escola.id, plataforma="elefante",
                                 origem="manual", status="concluida",
                                 finalizada_em=datetime(2026, 10, 21, 1, 40)))
    db.commit()

    corpo = frescor_ranking.frescor_da_escola(db, escola, HOJE)
    for dimensao in ("leitura", "matematica"):
        bloco = corpo["dimensoes"][dimensao]
        assert bloco["dado_mais_recente_em"] == "2026-10-20", (dimensao, bloco)
        assert bloco["dias_desde_dado"] == 0, (dimensao, bloco)
        assert bloco["estado"] == "em_dia"
    # A sincronização das 22h40 de Brasília também foi "hoje".
    assert corpo["dimensoes"]["leitura"]["dias_desde_sincronizacao_ok"] == 0


def test_limite_conta_em_dias_de_brasilia(db, escola_completa):
    """Limite 7: o retrato das 23h30 de 12/10 (Brasília) tem 8 dias em 20/10 e
    passou do limite; o das 00h30 de 13/10 tem 7 e ainda vale."""
    escola = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]
    imp = _imp(db, escola.id)
    _retrato_e(db, escola.id, imp, ana.id, datetime(2026, 10, 13, 2, 30))    # 12/10 23h30
    _retrato_e(db, escola.id, imp, joao.id, datetime(2026, 10, 13, 3, 30))   # 13/10 00h30
    _retrato_e(db, escola.id, imp, sofia.id, datetime(2026, 10, 19, 12, 0))  # 19/10 09h
    db.commit()

    leitura = frescor_ranking.frescor_da_escola(db, escola, HOJE)["dimensoes"]["leitura"]
    assert leitura["estado"] == "parcial"
    assert leitura["alunos_com_dado_antigo"] == 1          # só a Ana passou do limite
    assert leitura["dado_mais_antigo_em"] == "2026-10-12"
    assert leitura["dado_mais_recente_em"] == "2026-10-19"


def test_retrato_da_noite_de_oito_dias_e_desatualizado(db, escola_completa):
    escola = escola_completa["escola"]
    imp = _imp(db, escola.id)
    for aluno in escola_completa["alunos"]:
        _retrato_e(db, escola.id, imp, aluno.id, datetime(2026, 10, 13, 2, 30))
    db.commit()

    leitura = frescor_ranking.frescor_da_escola(db, escola, HOJE)["dimensoes"]["leitura"]
    assert leitura["dado_mais_recente_em"] == "2026-10-12"
    assert leitura["dias_desde_dado"] == 8
    assert leitura["estado"] == "desatualizado"
    assert leitura["alunos_com_dado_antigo"] == 3


def test_snapshot_em_do_ranking_de_matematica_usa_o_mesmo_dia_do_selo(
        cliente, db, escola_completa):
    """A linha do aluno e o selo não podem discordar sobre o dia: a coleta das
    22h30 de três dias atrás é de três dias atrás, não de dois."""
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    dia = fuso.hoje_local() - timedelta(days=3)
    noite_utc = fuso.local_para_utc_naive(datetime.combine(dia, time(22, 30)))
    imp = _imp(db, escola.id)
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=ana.id, importacao_id=imp.id,
                           data_referencia=noite_utc, atividades=10, estrelas=30,
                           pontuacao_media=2.0))
    db.commit()

    itens = cliente.get(f"{API}/escolas/{escola.id}/ranking/matematica").json()
    assert [(i["aluno_id"], i["snapshot_em"]) for i in itens] == [(ana.id, dia.isoformat())]
    selo = frescor_ranking.frescor_da_escola(db, escola, fuso.hoje_local())
    assert selo["dimensoes"]["matematica"]["dado_mais_recente_em"] == dia.isoformat()
