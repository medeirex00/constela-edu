"""S_G_AJUSTE-1: o ajuste manual do Elefante desmentido pela coleta seguinte não vira
"crescimento" no Ranking de Evolução de leitura, no resumo do aluno, no mural, no
/insights nem nas questões da Análise educacional.

Numa escola com a integração do Elefante, a escola que pede um ajuste recebe "fale com o
suporte" e o Admin Global grava o retrato manual (``Importacao.tipo == "manual"``, data =
instante do ajuste). O contador do Elefante é de VIDA INTEIRA e a coleta seguinte traz de
novo o número da plataforma: com o ajuste na série, corrigir para BAIXO fazia a coleta
seguinte parecer livros, minutos e questões do período (a criança subia ao topo do Ranking
de Evolução); corrigir para CIMA apagava o ganho real. A regra agora é a do Matific
(G_AJUSTE-1): o retrato manual vale como base e estado atual só até uma coleta vir depois
dele — no Elefante, de qualquer ano, porque o contador não zera.

Cenário (datas fixas em 2026, meio-dia UTC = 9h de Brasília, longe das bordas):
  * coleta A = 08/06 — todos com 10 livros, 100 min, 100 questões (80 certas);
  * AJUSTE de Ana = 10/06 (o suporte corrige o que a plataforma contou em dobro);
  * coleta B = 11/06 — Ana 11 livros, 110 min, 105 questões (84): leu 1, fez 5 (4);
    os outros 12, 120, 110 (88): leram 2, fizeram 10 (8);
  * período = 11/06 (começa depois do ajuste e antes da coleta B).

Questões do período do Relatório por Período (``relatorios_periodo``) são de outra frente.
Dados fictícios; nada de rede.
"""
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.models import Importacao, PlataformaCredencial, SnapshotElefante
from app.models.plataformas import IMPORTACAO_SEM_QUESTOES
from app.services import evolucao, gamificacao
from app.services import relatorios_periodo as rp
from app.services.analise import plataformas as ap

API = "/api/v1"
DIA = "2026-06-11"
COLETA_A = datetime(2026, 6, 8, 12, 0)
AJUSTE = datetime(2026, 6, 10, 12, 0)
COLETA_B = datetime(2026, 6, 11, 12, 0)
INICIO = datetime(2026, 6, 11)
FIM = datetime(2026, 6, 11, 23, 59, 59, 999999)

PARA_BAIXO = {"livros_unicos": 5, "tempo_leitura_min": 50, "questoes_tentativas": 50,
              "questoes_acertos": 40, "livros_por_nivel": {"AA": 5}}
PARA_CIMA = {"livros_unicos": 20, "tempo_leitura_min": 200, "questoes_tentativas": 200,
             "questoes_acertos": 160, "livros_por_nivel": {"AA": 20}}


def _retrato(db, escola_id, aluno_id, quando, livros, tempo, tentativas, acertos,
             importacao_id):
    db.add(SnapshotElefante(escola_id=escola_id, aluno_id=aluno_id,
                            importacao_id=importacao_id, data_referencia=quando,
                            livros_unicos=livros, tempo_leitura_min=tempo,
                            questoes_tentativas=tentativas, questoes_acertos=acertos,
                            livros_por_nivel={"AA": livros}))


def _coleta(db, escola_id, quando, valores, status="concluida"):
    """valores: {aluno_id: (livros, tempo, tentativas, acertos)} — o que a coleta grava."""
    imp = Importacao(escola_id=escola_id, usuario_id=None, plataforma="elefante",
                     tipo="api", qtd_alunos=len(valores), status=status)
    db.add(imp)
    db.flush()
    for aid, numeros in valores.items():
        _retrato(db, escola_id, aid, quando, *numeros, imp.id)
    db.commit()
    return imp.id


def _ajuste_manual(db, escola_id, aluno_id, quando, dados):
    """O que ``routers.plataformas.editar_elefante`` grava: uma Importacao ``tipo="manual"``
    e um retrato novo no instante do ajuste."""
    imp = Importacao(escola_id=escola_id, usuario_id=None, plataforma="elefante",
                     tipo="manual", qtd_alunos=1)
    db.add(imp)
    db.flush()
    _retrato(db, escola_id, aluno_id, quando, dados["livros_unicos"],
             dados["tempo_leitura_min"], dados["questoes_tentativas"],
             dados["questoes_acertos"], imp.id)
    db.commit()
    return imp.id


def _cenario(db, escola_completa, ajuste: dict | None):
    escola = escola_completa["escola"]
    ana, *outros = escola_completa["alunos"]
    _coleta(db, escola.id, COLETA_A, {a.id: (10, 100, 100, 80) for a in (ana, *outros)})
    if ajuste is not None:
        _ajuste_manual(db, escola.id, ana.id, AJUSTE, ajuste)
    _coleta(db, escola.id, COLETA_B, {ana.id: (11, 110, 105, 84),
                                      **{a.id: (12, 120, 110, 88) for a in outros}})
    return escola, ana, outros


def _ganhos_de(db, escola_id, aluno_id):
    itens = evolucao.ranking_evolucao(db, escola_id, INICIO, FIM, base_no_periodo=True)
    item = next(i for i in itens if i.aluno_id == aluno_id)
    return item, {k: item.ganhos[k] for k in ("livros", "tempo_leitura_min", "acertos")}


# --- a regra pura -----------------------------------------------------------------------

def _s(i, quando, importacao_id):
    return SimpleNamespace(id=i, data_referencia=quando, importacao_id=importacao_id)


def test_regra_pura_descarta_o_ajuste_desmentido_por_qualquer_coleta_depois():
    a, m, b = _s(1, COLETA_A, 10), _s(2, AJUSTE, 99), _s(3, COLETA_B, 11)
    assert evolucao.sem_ajustes_superados_vitalicio([a, m, b], {99}) == [a, b]
    # Sem coleta depois: o ajuste é o estado vigente e continua valendo.
    assert evolucao.sem_ajustes_superados_vitalicio([a, m], {99}) == [a, m]
    # O contador do Elefante é de vida inteira: a coleta do ano seguinte também desmente.
    jan = _s(4, datetime(2027, 2, 5, 12, 0), 12)
    assert evolucao.sem_ajustes_superados_vitalicio([a, m, jan], {99}) == [a, jan]
    # Ajuste seguido de ajuste (a escola sem integração digita os números): fica tudo.
    m2 = _s(5, datetime(2026, 6, 10, 18, 0), 98)
    assert evolucao.sem_ajustes_superados_vitalicio([m, m2], {98, 99}) == [m, m2]
    # Sem ajuste manual na escola: a série volta intacta (em ordem de data).
    assert evolucao.sem_ajustes_superados_vitalicio([b, a, m], set()) == [a, m, b]


def test_serie_da_escola_nao_carrega_o_ajuste_ja_desmentido(db, escola_completa):
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    _coleta(db, escola.id, COLETA_A, {ana.id: (10, 100, 100, 80)})
    imp = _ajuste_manual(db, escola.id, ana.id, AJUSTE, PARA_BAIXO)
    # Antes da coleta seguinte o ajuste É o estado atual.
    serie = evolucao._series_por_aluno(db, escola.id, SnapshotElefante)[ana.id]
    assert [s.questoes_tentativas for s in serie] == [100, 50]
    assert serie[-1].importacao_id == imp
    _coleta(db, escola.id, COLETA_B, {ana.id: (11, 110, 105, 84)})
    serie = evolucao._series_por_aluno(db, escola.id, SnapshotElefante)[ana.id]
    assert [s.questoes_tentativas for s in serie] == [100, 105]
    # A mesma série é a que o app e o assistente recebem pré-carregada.
    _, serie_e, _ = evolucao.series_e_dificuldade(db, escola.id)
    assert [s.questoes_tentativas for s in serie_e[ana.id]] == [100, 105]


# --- Ranking de Evolução (leitura) --------------------------------------------------------

def test_controle_sem_ajuste(db, escola_completa):
    escola, ana, _ = _cenario(db, escola_completa, None)
    _, ganhos = _ganhos_de(db, escola.id, ana.id)
    assert ganhos == {"livros": 1.0, "tempo_leitura_min": 10.0, "acertos": 4.0}


def test_correcao_para_baixo_nao_cria_crescimento_falso(db, escola_completa):
    escola, ana, outros = _cenario(db, escola_completa, PARA_BAIXO)
    item, ganhos = _ganhos_de(db, escola.id, ana.id)
    assert ganhos == {"livros": 1.0, "tempo_leitura_min": 10.0, "acertos": 4.0}, \
        "o degrau entre o número do suporte e a coleta seguinte virou crescimento"
    # Ana leu menos que os colegas no período: não sobe para o 1º lugar.
    assert item.posicao_dimensao["leitura"] == len(outros) + 1


def test_correcao_para_cima_nao_apaga_o_ganho_real(db, escola_completa):
    escola, ana, _ = _cenario(db, escola_completa, PARA_CIMA)
    _, ganhos = _ganhos_de(db, escola.id, ana.id)
    assert ganhos == {"livros": 1.0, "tempo_leitura_min": 10.0, "acertos": 4.0}, \
        "o ajuste para cima apagou o que a criança leu no período"


def test_ajuste_do_suporte_pela_rota_nao_vira_crescimento(cliente, cliente_global, db,
                                                          escola_completa):
    """O caminho real: escola integrada, o Admin Global ajusta pela rota (a escola recebe
    "fale com o suporte"); o ajuste aconteceu antes do período e a coleta seguinte, nele."""
    escola = escola_completa["escola"]
    ana, *outros = escola_completa["alunos"]
    db.add(PlataformaCredencial(escola_id=escola.id, plataforma="elefante",
                                segredo_cifrado="cifrado-de-teste", status="valida"))
    db.commit()
    _coleta(db, escola.id, COLETA_A, {a.id: (10, 100, 100, 80) for a in (ana, *outros)})
    r = cliente_global.put(f"{API}/escolas/{escola.id}/elefante/{ana.id}",
                           json={**PARA_BAIXO, "motivo": "suporte: relatório contou em dobro"})
    assert r.status_code == 200, r.text
    snap = db.execute(
        select(SnapshotElefante).join(Importacao, Importacao.id == SnapshotElefante.importacao_id)
        .where(SnapshotElefante.aluno_id == ana.id, Importacao.tipo == "manual")).scalar_one()
    snap.data_referencia = AJUSTE          # só a data: valores e origem são os da rota
    db.commit()
    _coleta(db, escola.id, COLETA_B, {ana.id: (11, 110, 105, 84),
                                      **{a.id: (12, 120, 110, 88) for a in outros}})
    r = cliente.get(f"{API}/escolas/{escola.id}/ranking-evolucao",
                    params={"dimensao": "leitura", "periodo": "personalizado",
                            "inicio": DIA, "fim": DIA})
    assert r.status_code == 200, r.text
    corpo = r.json()
    itens = corpo if isinstance(corpo, list) else corpo["itens"]
    linha = next(i for i in itens if i["aluno_id"] == ana.id)
    assert (linha["ganhos"]["livros"], linha["ganhos"]["acertos"]) == (1.0, 4.0), linha
    assert linha["posicao"] == len(outros) + 1, linha


# --- os outros leitores da série ------------------------------------------------------------

def test_resumo_de_evolucao_do_aluno_nao_parte_do_ajuste(db, escola_completa, monkeypatch):
    escola, ana, _ = _cenario(db, escola_completa, PARA_BAIXO)

    class _Relogio(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 6, 11, 15, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(evolucao, "datetime", _Relogio)
    # 1 dia: o início (10/06 15h) cai entre o ajuste (10/06 12h) e a coleta B.
    resumo = evolucao.resumo_evolucao(db, escola.id, ana.id, 1)
    por_campo = {i["indicador"]: i for i in resumo["indicadores"]}
    tentativas = por_campo["questoes_tentativas"]
    assert (tentativas["inicial"], tentativas["atual"], tentativas["variacao"]) == \
        (100.0, 105.0, 5.0)
    assert por_campo["livros_unicos"]["variacao"] == 1.0


def test_sequencia_de_semanas_nao_conta_o_ajuste_desmentido(db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    # Semanas ISO 23 (coleta), 24 (ajuste para cima) e 25 (coleta: +1 livro de verdade).
    _coleta(db, escola.id, datetime(2026, 6, 2, 12, 0), {ana.id: (10, 100, 100, 80)})
    _ajuste_manual(db, escola.id, ana.id, datetime(2026, 6, 10, 12, 0), PARA_CIMA)
    _coleta(db, escola.id, datetime(2026, 6, 17, 12, 0), {ana.id: (11, 110, 105, 84)})
    detalhe = gamificacao.gamificacao_do_aluno(db, escola.id, ana.id)
    # Com o degrau, a semana 24 "ganhou" e a 25 "regrediu": a sequência terminava na
    # semana do ajuste. Sem ele, a semana mais recente com ganho é a 25.
    assert detalhe["sequencia_semanas"] == 1


# --- Análise educacional (questões do Elefante) ---------------------------------------------

def _janela_do_dia():
    return rp.resolver_janela("personalizado", 2026, inicio=date(2026, 6, 11),
                              fim=date(2026, 6, 11), hoje=date(2026, 11, 11))


def _questoes_lidas(db, escola_id, aluno_id):
    lidas = ap._coletas_das_questoes(db, escola_id, _janela_do_dia())
    return [(r.data_referencia, r.questoes_tentativas) for r in lidas.get(aluno_id, [])]


@pytest.mark.parametrize("ajuste", [PARA_BAIXO, PARA_CIMA], ids=["para_baixo", "para_cima"])
def test_analise_nao_le_o_ajuste_desmentido_nas_questoes(db, escola_completa, ajuste):
    escola, ana, _ = _cenario(db, escola_completa, ajuste)
    assert _questoes_lidas(db, escola.id, ana.id) == [(COLETA_A, 100), (COLETA_B, 105)]
    # A leitura em lote (a da rede inteira) é a mesma.
    lote = ap._questoes_em_lote(db, {0: (_janela_do_dia(), [escola.id])})
    assert [r.questoes_tentativas for r in lote[(0, escola.id)][ana.id]] == [100, 105]


def test_analise_ajuste_sem_coleta_das_questoes_depois_continua_valendo(db,
                                                                         escola_completa):
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    _coleta(db, escola.id, COLETA_A, {ana.id: (10, 100, 100, 80)})
    _ajuste_manual(db, escola.id, ana.id, AJUSTE, PARA_BAIXO)
    assert _questoes_lidas(db, escola.id, ana.id) == [(AJUSTE, 50)]
    # A coleta em que as questões NÃO vieram (S9) não é coleta das questões: não desmente
    # as do ajuste (e continua fora da série, como antes).
    _coleta(db, escola.id, COLETA_B, {ana.id: (11, 110, 50, 40)},
            status=IMPORTACAO_SEM_QUESTOES)
    assert _questoes_lidas(db, escola.id, ana.id) == [(AJUSTE, 50)]
