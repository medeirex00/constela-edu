"""Período personalizado com as datas trocadas é recusado em TODAS as telas (PERIODOS-6).

O Relatório por Período já recusava ``inicio > fim`` (422, "inverta as duas"), mas o
serviço comum de períodos (``periodos.resolver``) aceitava o intervalo invertido e devolvia
início depois do fim: as consultas ``data >= início AND data <= fim`` davam vazio e o
Ranking de Leitura, as Premiações, o Histórico do aluno e o Ranking de Evolução respondiam
"nenhuma leitura no período" (200). Agora a validação mora em ``periodos.resolver``
(``PeriodoInvalido``) e o app responde 422 com a MESMA frase do relatório. Tudo fictício.
"""
from datetime import date, datetime

import pytest

from app.models import Leitura, Livro
from app.services import periodos

TROCADO = "periodo=personalizado&inicio=2026-10-31&fim=2026-10-01"
FRASE = "A data inicial (31/10/2026) é posterior à final (01/10/2026) — inverta as duas."
HOJE = date(2026, 11, 11)


def test_resolver_recusa_o_personalizado_invertido_com_a_frase_do_relatorio():
    with pytest.raises(periodos.PeriodoInvalido) as erro:
        periodos.resolver("personalizado", HOJE, 2026, date(2026, 10, 31), date(2026, 10, 1))
    assert str(erro.value) == FRASE
    # Não é ValueError: as rotas trocam ValueError por "Data inválida (use AAAA-MM-DD)",
    # que é outro problema (formato), e engoliriam a frase.
    assert not isinstance(erro.value, ValueError)


def test_resolver_continua_aceitando_o_mesmo_dia_um_limite_so_e_os_presets():
    um_dia = periodos.resolver("personalizado", HOJE, 2026, date(2026, 10, 5), date(2026, 10, 5))
    assert um_dia == (datetime(2026, 10, 5), datetime(2026, 10, 5, 23, 59, 59, 999999),
                      "05/10/2026")
    assert periodos.resolver("personalizado", HOJE, 2026, date(2026, 10, 5), None)[1] is None
    assert periodos.resolver("personalizado", HOJE, 2026, None, date(2026, 10, 5))[0] is None
    # Fora do personalizado as datas soltas não contam (como antes): nada a recusar.
    assert periodos.resolver("mes", HOJE, 2026, date(2026, 10, 31),
                             date(2026, 10, 1))[2] == "Este mês"


@pytest.fixture()
def com_leitura(db, escola_completa):
    escola, aluno = escola_completa["escola"], escola_completa["alunos"][0]
    livro = Livro(escola_id=escola.id, titulo="Livro Fictício do Teste", nivel_codigo="D")
    db.add(livro)
    db.flush()
    db.add(Leitura(escola_id=escola.id, aluno_id=aluno.id, livro_id=livro.id,
                   data=datetime(2026, 10, 10, 9, 30), tempo_leitura_min=20))
    db.commit()
    return escola.id, aluno.id


ROTAS = [
    "/ranking/leitura?{q}",
    "/ranking/matematica?{q}",
    "/premiacoes?{q}",
    "/ranking-evolucao?{q}",
    "/alunos/{aluno}/leituras?{q}",
    "/alunos/{aluno}/evolucao-leitura?{q}",
    "/alunos/{aluno}/linha-do-tempo?{q}",
    "/configuracoes/pontuacao/exemplo/matific?atividades=5&estrelas=10&{q}",
]


@pytest.mark.parametrize("rota", ROTAS)
def test_rotas_com_periodo_recusam_as_datas_trocadas_como_o_relatorio(cliente, com_leitura,
                                                                      rota):
    escola_id, aluno_id = com_leitura
    base = f"/api/v1/escolas/{escola_id}"
    relatorio = cliente.get(f"{base}/relatorios/periodo?{TROCADO}&plataformas=elefante")
    assert (relatorio.status_code, relatorio.json()["detail"]) == (422, FRASE)

    r = cliente.get(base + rota.format(q=TROCADO, aluno=aluno_id))
    assert r.status_code == 422, (rota, r.status_code, r.text[:200])
    assert r.json() == {"detail": FRASE}


def test_controle_o_mesmo_intervalo_na_ordem_certa_traz_a_leitura(cliente, com_leitura):
    escola_id, aluno_id = com_leitura
    base = f"/api/v1/escolas/{escola_id}"
    certo = "periodo=personalizado&inicio=2026-10-01&fim=2026-10-31"
    ranking = cliente.get(f"{base}/ranking/leitura?{certo}")
    assert ranking.status_code == 200 and len(ranking.json()) == 1
    historico = cliente.get(f"{base}/alunos/{aluno_id}/leituras?{certo}")
    assert historico.status_code == 200, historico.text[:200]
    # Data em formato errado continua sendo o 400 de formato (outra frase).
    errado = cliente.get(f"{base}/ranking/leitura?periodo=personalizado&inicio=31-10-2026")
    assert errado.status_code == 400 and "AAAA-MM-DD" in errado.json()["detail"]
