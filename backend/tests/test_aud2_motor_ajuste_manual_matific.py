"""G_AJUSTE-1 (parte 2, defesa na série): o ajuste manual do Matific não vira
"ganho" nem "regressão" do período quando a coleta seguinte o desmente.

O contador do Matific é cumulativo e a coleta seguinte traz de novo o número da
plataforma. O retrato gravado pelo botão Editar (``Importacao.tipo == "manual"``,
``data_referencia`` = o instante do ajuste) virava um degrau artificial: corrigir
para BAIXO fazia a coleta seguinte parecer ganho; corrigir para CIMA zerava o
ganho real. A regra agora: um retrato manual só vale enquanto nenhuma COLETA do
mesmo ano letivo vier depois dele; depois disso ele não é base nem estado atual.

Cenário (datas fixas em 2026, meio-dia UTC = 9h de Brasília, longe das bordas):
  * coleta A  = 08/06 — Ana 100 atividades / 400 estrelas; os outros 50 / 200;
  * AJUSTE MANUAL de Ana = 10/06 (gravado como a rota grava);
  * coleta B  = 11/06 — Ana 105 / 420 (fez 5 e 20); os outros 70 / 280 (20 e 80);
  * período premiado = 11/06 (começa depois do ajuste e antes da coleta B).

Dados fictícios; nada de rede.
"""
from datetime import date, datetime, timezone
from types import SimpleNamespace

from sqlalchemy import select

from app.models import Aluno, Importacao, Matricula, SnapshotMatific
from app.services import evolucao, gamificacao, matific_destaque
from app.services import relatorios_periodo as rp
from app.services import visao_geral as vg

API = "/api/v1"
DIA = "2026-06-11"
COLETA_A = datetime(2026, 6, 8, 12, 0)
AJUSTE = datetime(2026, 6, 10, 12, 0)
COLETA_B = datetime(2026, 6, 11, 12, 0)


def _mais_alunos(db, escola_completa, n=4):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    novos = []
    for i in range(n):
        a = Aluno(escola_id=escola.id, nome=f"Aluno Ficticio {i}")
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=turma.id,
                         ano_letivo=2026))
        novos.append(a)
    db.commit()
    return escola_completa["alunos"] + novos


def _coleta(db, escola_id, quando, valores: dict[int, tuple[int, int]]):
    imp = Importacao(escola_id=escola_id, usuario_id=None, plataforma="matific",
                     tipo="api", qtd_alunos=len(valores))
    db.add(imp)
    db.flush()
    for aid, (ativ, est) in valores.items():
        db.add(SnapshotMatific(escola_id=escola_id, aluno_id=aid, importacao_id=imp.id,
                               data_referencia=quando, atividades=ativ, estrelas=est,
                               pontuacao_media=4.0))
    db.commit()


def _ajuste_manual(db, escola_id, aluno_id, quando, atividades, estrelas):
    """O que ``routers.plataformas.editar_matific`` grava: uma Importacao
    ``tipo="manual"`` e um retrato novo no instante do ajuste."""
    imp = Importacao(escola_id=escola_id, usuario_id=None, plataforma="matific",
                     tipo="manual", qtd_alunos=1)
    db.add(imp)
    db.flush()
    db.add(SnapshotMatific(escola_id=escola_id, aluno_id=aluno_id, importacao_id=imp.id,
                           data_referencia=quando, atividades=atividades,
                           estrelas=estrelas, pontuacao_media=4.0))
    db.commit()
    return imp.id


def _cenario(db, escola_completa, manual: tuple[int, int] | None):
    escola = escola_completa["escola"]
    alunos = _mais_alunos(db, escola_completa)
    ana, outros = alunos[0], alunos[1:]
    _coleta(db, escola.id, COLETA_A, {ana.id: (100, 400), **{a.id: (50, 200) for a in outros}})
    if manual is not None:
        _ajuste_manual(db, escola.id, ana.id, AJUSTE, *manual)
    _coleta(db, escola.id, COLETA_B, {ana.id: (105, 420), **{a.id: (70, 280) for a in outros}})
    return escola, ana, outros


def _podio_mat(cliente, escola_id):
    r = cliente.get(f"{API}/escolas/{escola_id}/premiacoes",
                    params={"periodo": "personalizado", "inicio": DIA, "fim": DIA,
                            "limite": 50})
    assert r.status_code == 200, r.text
    return next(c for c in r.json()["categorias"] if c["chave"] == "melhor_matematica")["podio"]


def _ranking_mat(cliente, escola_id):
    r = cliente.get(f"{API}/escolas/{escola_id}/ranking/matematica",
                    params={"periodo": "personalizado", "inicio": DIA, "fim": DIA})
    assert r.status_code == 200, r.text
    return r.json()


# --- a regra pura ---------------------------------------------------------------------

def _s(i, quando, importacao_id):
    return SimpleNamespace(id=i, data_referencia=quando, importacao_id=importacao_id,
                           atividades=0, estrelas=0)


def test_regra_pura_descarta_so_o_manual_desmentido_pela_coleta_do_mesmo_ano():
    a, m, b = _s(1, COLETA_A, 10), _s(2, AJUSTE, 99), _s(3, COLETA_B, 11)
    assert matific_destaque.sem_ajustes_superados([a, m, b], {99}) == [a, b]
    # Sem coleta depois: o ajuste é o estado vigente e continua valendo.
    assert matific_destaque.sem_ajustes_superados([a, m], {99}) == [a, m]
    # Coleta de OUTRO ano letivo não desmente o contador deste ano.
    jan = _s(4, datetime(2027, 1, 5, 12, 0), 12)
    assert matific_destaque.sem_ajustes_superados([a, m, jan], {99}) == [a, m, jan]
    # Ajuste seguido de outro ajuste: só a coleta desmente.
    m2 = _s(5, datetime(2026, 6, 10, 18, 0), 98)
    assert matific_destaque.sem_ajustes_superados([a, m, m2], {98, 99}) == [a, m, m2]
    # Sem ajuste manual na escola: a série volta intacta.
    assert matific_destaque.sem_ajustes_superados([a, m, b], set()) == [a, m, b]


def test_serie_da_escola_nao_carrega_o_ajuste_ja_desmentido(db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    _coleta(db, escola.id, COLETA_A, {ana.id: (100, 400)})
    _ajuste_manual(db, escola.id, ana.id, AJUSTE, 50, 200)
    # Antes da coleta seguinte o ajuste É o estado atual.
    serie = evolucao._series_por_aluno(db, escola.id, SnapshotMatific)[ana.id]
    assert [s.atividades for s in serie] == [100, 50]
    _coleta(db, escola.id, COLETA_B, {ana.id: (105, 420)})
    serie = evolucao._series_por_aluno(db, escola.id, SnapshotMatific)[ana.id]
    assert [s.atividades for s in serie] == [100, 105]


# --- premiações e Ranking de Matemática --------------------------------------------------

def test_controle_sem_ajuste(cliente, db, escola_completa):
    escola, ana, _ = _cenario(db, escola_completa, None)
    linha = next(p for p in _podio_mat(cliente, escola.id) if p["aluno_id"] == ana.id)
    assert (linha["atividades"], linha["estrelas"]) == (5, 20)


def test_correcao_para_baixo_nao_cria_ganho_falso(cliente, db, escola_completa):
    escola, ana, _ = _cenario(db, escola_completa, (50, 200))
    podio = _podio_mat(cliente, escola.id)
    linha = next(p for p in podio if p["aluno_id"] == ana.id)
    assert (linha["atividades"], linha["estrelas"]) == (5, 20), \
        "Premiação atribuiu ao período a diferença entre o ajuste manual e a coleta"
    assert linha["posicao"] == len(podio)
    item = next(i for i in _ranking_mat(cliente, escola.id) if i["aluno_id"] == ana.id)
    assert (item["atividades"], item["estrelas"]) == (5, 20), \
        "Ranking de Matemática atribuiu ao período o que o ajuste manual tirou"


def test_correcao_para_cima_nao_apaga_ganho_real(cliente, db, escola_completa):
    escola, ana, _ = _cenario(db, escola_completa, (300, 1500))
    linha = next((p for p in _podio_mat(cliente, escola.id) if p["aluno_id"] == ana.id),
                 None)
    assert linha is not None, "Ana fez 5 atividades no período e sumiu do pódio"
    assert (linha["atividades"], linha["estrelas"]) == (5, 20)
    item = next((i for i in _ranking_mat(cliente, escola.id) if i["aluno_id"] == ana.id),
                None)
    assert item is not None and (item["atividades"], item["estrelas"]) == (5, 20)


# --- os outros leitores da série ----------------------------------------------------------

def test_ranking_de_evolucao_mede_o_ganho_da_coleta(db, escola_completa):
    escola, ana, _ = _cenario(db, escola_completa, (50, 200))
    ini, fim = datetime(2026, 6, 11), datetime(2026, 6, 11, 23, 59, 59, 999999)
    itens = evolucao.ranking_evolucao(db, escola.id, ini, fim, base_no_periodo=True)
    item = next(i for i in itens if i.aluno_id == ana.id)
    assert (item.ganhos["atividades"], item.ganhos["estrelas"]) == (5, 20)


def test_relatorio_por_periodo_mede_o_ganho_da_coleta(db, escola_completa):
    escola, ana, outros = _cenario(db, escola_completa, (50, 200))
    dados = rp.gerar(db, escola.id, preset="personalizado", plataformas=("matific",),
                     inicio=date(2026, 6, 11), fim=date(2026, 6, 11),
                     hoje=date(2026, 11, 11))
    assert dados["matific"]["atividades"] == 5 + 20 * len(outros)
    assert dados["matific"]["estrelas"] == 20 + 80 * len(outros)


def test_visao_geral_mede_o_ganho_da_coleta(db, escola_completa):
    escola, ana, _ = _cenario(db, escola_completa, (300, 1500))
    coorte = rp._coorte(db, escola.id, 2026)
    dados = vg._series_matific(db, escola.id, coorte, 2026)
    ini, fim = datetime(2026, 6, 11), datetime(2026, 6, 11, 23, 59, 59, 999999)
    ganho = vg._ganho(dados.series[ana.id], dados.chaves[ana.id], ini, fim, 2026)
    assert (ganho.atividades, ganho.estrelas) == (5, 20)
    assert not ganho.regressao_detectada


def test_resumo_de_evolucao_do_aluno_nao_parte_do_ajuste(db, escola_completa, monkeypatch):
    escola, ana, _ = _cenario(db, escola_completa, (50, 200))

    class _Relogio(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 6, 11, 15, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(evolucao, "datetime", _Relogio)
    # 1 dia: o início (10/06 15h) cai entre o ajuste (10/06 12h) e a coleta B.
    resumo = evolucao.resumo_evolucao(db, escola.id, ana.id, 1)
    atividades = next(i for i in resumo["indicadores"] if i["indicador"] == "atividades")
    assert (atividades["inicial"], atividades["atual"], atividades["variacao"]) == \
        (100.0, 105.0, 5.0)


def test_sequencia_de_semanas_nao_conta_o_ajuste_desmentido(db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    # Semanas ISO 23 (coleta), 24 (ajuste para cima) e 25 (coleta: +5 de verdade).
    _coleta(db, escola.id, datetime(2026, 6, 2, 12, 0), {ana.id: (100, 400)})
    _ajuste_manual(db, escola.id, ana.id, datetime(2026, 6, 10, 12, 0), 300, 1500)
    _coleta(db, escola.id, datetime(2026, 6, 17, 12, 0), {ana.id: (105, 420)})
    detalhe = gamificacao.gamificacao_do_aluno(db, escola.id, ana.id)
    # Com o degrau, a semana 24 "ganhou" e a 25 "regrediu": a sequência terminava
    # na semana do ajuste. Sem ele, a semana mais recente com ganho é a 25.
    assert detalhe["sequencia_semanas"] == 1


def test_ajuste_sem_coleta_depois_continua_valendo(cliente, db, escola_completa):
    """O ajuste é o estado vigente enquanto a plataforma não trouxer número novo."""
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    _coleta(db, escola.id, COLETA_A, {ana.id: (100, 400)})
    imp = _ajuste_manual(db, escola.id, ana.id, AJUSTE, 120, 480)
    serie = evolucao._series_por_aluno(db, escola.id, SnapshotMatific)[ana.id]
    assert serie[-1].importacao_id == imp
    ids = set(db.execute(select(SnapshotMatific.id)
                         .where(SnapshotMatific.aluno_id == ana.id)).scalars())
    assert {s.id for s in serie} == ids
