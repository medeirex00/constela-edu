"""Questões do período × coleta em que as questões NÃO vieram (S9, revisão independente).

Quando a API do Elefante deixa de mandar ``responses``/``approvedResponses``, quem leu
um livro novo ganha, na sincronização, um retrato com as questões da coleta ANTERIOR e
a data de agora (os livros entram; nada é zerado). As Questões do período são a
diferença entre retratos: usado como borda, esse retrato dava "0 no período" e a
cobertura saía "completa" — o relatório afirmava ter medido o que não mediu.

Agora a importação dessa sincronização é marcada (``IMPORTACAO_SEM_QUESTOES``) e os
retratos dela não são borda das questões (relatório e análise): a conta do aluno vai
até a coleta anterior, ou fica sem número, e a cobertura diz por quê
(``alunos_questoes_nao_vieram``). Nenhum número gravado muda.

Instantes em UTC, como a sync grava (00:10 em Brasília = 03:10 UTC). Dados FICTÍCIOS.
"""
from __future__ import annotations

from datetime import date, datetime

from app.models import Importacao, SnapshotElefante
from app.models.plataformas import IMPORTACAO_SEM_QUESTOES
from app.services import relatorios_periodo as rp
from app.services.analise import plataformas as svc_analise
from tests.test_analise_base import nova_escola, nova_rede, turma_com_alunos

HOJE_OUT = date(2026, 10, 6)


def _retrato(db, escola_id, aluno_id, quando, tentativas, acertos, *, sem_questoes=False):
    imp = Importacao(escola_id=escola_id, usuario_id=None, plataforma="elefante",
                     tipo="pdf", arquivo_original=None, qtd_alunos=0, qtd_erros=0,
                     tempo_ms=0, created_at=quando,
                     status=IMPORTACAO_SEM_QUESTOES if sem_questoes else "concluida")
    db.add(imp)
    db.flush()
    db.add(SnapshotElefante(escola_id=escola_id, aluno_id=aluno_id, importacao_id=imp.id,
                            data_referencia=quando, livros_unicos=3, tempo_leitura_min=40,
                            questoes_tentativas=tentativas, questoes_acertos=acertos,
                            livros_por_nivel={}))
    db.flush()


def _noite(dia: int, mes: int = 9) -> datetime:
    """A coleta da agenda: 00:10 em Brasília (03:10 UTC)."""
    return datetime(2026, mes, dia, 3, 10)


def _setembro(db, eid, **kw):
    return rp.gerar(db, eid, preset="mes_anterior", plataformas=("elefante",),
                    hoje=HOJE_OUT, **kw)["elefante"]


def test_coleta_sem_questoes_na_borda_do_fim_nao_da_cobertura_completa(db, escola_completa):
    """A: coletas válidas em 01/09 e 20/09; a de 01/10 (que mediria o fim) veio sem as
    questões e repete as de 20/09. B: só a de 01/09 é válida. Antes: 30 questões e
    cobertura "completa" — e B entrava com 0."""
    eid = escola_completa["escola"].id
    a, b, _c = (x.id for x in escola_completa["alunos"])
    _retrato(db, eid, a, _noite(1), 100, 80)
    _retrato(db, eid, a, _noite(20), 130, 101)
    _retrato(db, eid, a, _noite(1, 10), 130, 101, sem_questoes=True)
    _retrato(db, eid, b, _noite(1), 50, 40)
    _retrato(db, eid, b, _noite(1, 10), 50, 40, sem_questoes=True)
    db.commit()

    ele = _setembro(db, eid)

    cob = ele["cobertura_questoes"]
    assert cob["status"] == "parcial" and cob["completa"] is False
    assert cob["alunos_questoes_nao_vieram"] == 2
    # A conta vai até a coleta anterior (20/09). Quem diz isso é "as questões não
    # vieram", não "a última coleta é de 20/09": A teve coleta depois (cada aluno numa
    # causa só — test_relatorios_periodo_s9_uma_causa).
    assert (ele["questoes_tentativas"], ele["questoes_acertos"]) == (30, 21)
    assert cob["fim_coberto"] is False and cob["alunos_sem_fim"] == 0
    assert cob["coleta_fim"].startswith("2026-09-20T03:10")
    # B não é "uma coleta só" nem "sem coleta": o motivo é o das questões que não vieram
    # (o "sem coleta" é só o 3º aluno da escola, que não tem nenhuma).
    assert cob["alunos_sem_intervalo"] == 0 and ele["alunos_sem_retrato"] == 1
    assert cob["alunos_medidos"] == 1


def test_so_coletas_sem_questoes_no_periodo_nao_viram_zero(db, escola_completa):
    """O cenário da revisão: todos da turma leram livro novo e as questões não vieram.
    Antes: 0/0 com cobertura "completa". Agora não há número ("—")."""
    eid = escola_completa["escola"].id
    a, b, _c = (x.id for x in escola_completa["alunos"])
    for aluno, t, ac in ((a, 30, 25), (b, 10, 8)):
        _retrato(db, eid, aluno, _noite(1), t, ac)
        _retrato(db, eid, aluno, _noite(1, 10), t, ac, sem_questoes=True)
    db.commit()

    ele = _setembro(db, eid)

    assert ele["questoes_tentativas"] is None and ele["questoes_acertos"] is None
    cob = ele["cobertura_questoes"]
    assert cob["status"] == "sem_intervalo" and cob["completa"] is False
    assert cob["alunos_questoes_nao_vieram"] == 2
    assert cob["alunos_sem_intervalo"] == 0 and cob["turmas_sem_coleta"] == []


def test_coleta_sem_questoes_no_meio_do_periodo_nao_muda_nada(db, escola_completa):
    """Com as duas bordas medidas por coletas válidas, a coleta sem questões no meio do
    período não muda a conta: cobertura completa e nenhum aluno afetado."""
    eid = escola_completa["escola"].id
    a = escola_completa["alunos"][0].id
    _retrato(db, eid, a, _noite(1), 100, 80)
    _retrato(db, eid, a, _noite(15), 100, 80, sem_questoes=True)
    _retrato(db, eid, a, _noite(1, 10), 150, 120)
    db.commit()

    ele = _setembro(db, eid)

    cob = ele["cobertura_questoes"]
    assert (ele["questoes_tentativas"], ele["questoes_acertos"]) == (50, 40)
    assert cob["status"] == "completa" and cob["alunos_questoes_nao_vieram"] == 0


def test_pdf_diz_que_as_questoes_nao_vieram(db, escola_completa):
    """O PDF segue a tela: o motivo da cobertura parcial e, sem número, por que não há
    número (não "uma coleta só por estudante")."""
    from app.services import relatorios_periodo_pdf as pdf
    from tests.test_relatorios_periodo_pdf import _texto
    eid = escola_completa["escola"].id
    a, b, _c = (x.id for x in escola_completa["alunos"])
    _retrato(db, eid, a, _noite(1), 100, 80)
    _retrato(db, eid, a, _noite(20), 130, 101)
    _retrato(db, eid, a, _noite(1, 10), 130, 101, sem_questoes=True)
    _retrato(db, eid, b, _noite(1), 50, 40)
    _retrato(db, eid, b, _noite(1, 10), 50, 40, sem_questoes=True)
    db.commit()
    dados = rp.gerar(db, eid, preset="mes_anterior", plataformas=("elefante",), hoje=HOJE_OUT)

    html = pdf.montar_html(dados)
    assert "COBERTURA PARCIAL" in html
    assert "2 estudante(s) com coleta no período em que a plataforma não mandou as questões" \
        in html
    assert "2 sem questões na coleta" in _texto(pdf._reserva(dados, "#1B2A4A"))


def test_pdf_sem_numero_porque_as_questoes_nao_vieram(db, escola_completa):
    from app.services import relatorios_periodo_pdf as pdf
    eid = escola_completa["escola"].id
    a = escola_completa["alunos"][0].id
    _retrato(db, eid, a, _noite(1), 30, 25)
    _retrato(db, eid, a, _noite(1, 10), 30, 25, sem_questoes=True)
    db.commit()
    dados = rp.gerar(db, eid, preset="mes_anterior", plataformas=("elefante",), hoje=HOJE_OUT)

    resumo = {r: (v, f) for r, v, f in pdf.linhas_resumo(dados)}
    assert resumo["Questões tentadas"] == (pdf.SEM_DADO, "as questões não vieram da plataforma")
    html = pdf.montar_html(dados)
    assert "A plataforma não mandou as questões nas coletas do período" in html
    assert "Há uma única coleta por estudante no período" not in html


def test_a_analise_le_as_mesmas_coletas_das_questoes_que_o_relatorio(db):
    """A análise (``_coletas_das_questoes``) tira o retrato sem questões antes de tudo,
    como o relatório: o número das duas é o mesmo, e não o "0" da coleta sem questões."""
    rede = nova_rede(db, nome="Rede Fictícia Sem Questões", codigo="3599951", codmun="9951")
    e = nova_escola(db, rede, "EMEF Fictícia Sem Questões", "35999511")
    alunos = turma_com_alunos(db, e, "3º Ano", 5)
    for a in alunos:
        _retrato(db, e.id, a.id, _noite(1), 100, 80)
        _retrato(db, e.id, a.id, _noite(20), 130, 104)
        _retrato(db, e.id, a.id, _noite(1, 10), 130, 104, sem_questoes=True)
    db.commit()
    ini, fim = date(2026, 9, 1), date(2026, 9, 30)
    janela = rp.resolver_janela("personalizado", 2026, inicio=ini, fim=fim, hoje=HOJE_OUT)

    lidas = svc_analise._coletas_das_questoes(db, e.id, janela)

    assert {tuple(r.data_referencia for r in v) for v in lidas.values()} == {
        (_noite(1), _noite(20))}
    rel = rp.gerar(db, e.id, preset="personalizado", inicio=ini, fim=fim,
                   plataformas=["elefante"], hoje=HOJE_OUT)["elefante"]
    assert (rel["questoes_tentativas"], rel["questoes_acertos"]) == (150, 120)
    dados = svc_analise.plataformas_da_rede(db, rede, preset="personalizado", inicio=ini,
                                            fim=fim, hoje=HOJE_OUT)
    el = next(x for x in dados["escolas"] if x["escola_id"] == e.id)["elefante"]
    assert el["taxa_acerto_pct"] == 80.0
    assert el["janela_questoes"]["fim"].startswith("2026-09-20T00:10")
