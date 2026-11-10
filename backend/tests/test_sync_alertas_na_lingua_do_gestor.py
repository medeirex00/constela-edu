"""Os alertas e o log da sincronização que a tela de Integrações mostra, na língua de
quem os lê (revisão pp3).

O Suporte novo manda o gestor ler o alerta "Formato do relatório mudou" no cartão de
Integrações. As mensagens desse alerta, do "Coleta parcial" ao lado e do log da
execução diziam "o conector precisa ser revisto" — vocabulário de quem programa. Agora
dizem o mesmo que o Relatório por Período: "a equipe do Constela precisa ajustar a
coleta dessa plataforma".

E cada status diz a verdade: na 'sem_atualizacao' (nenhum aluno com dado novo) o
alerta dizia "os livros foram atualizados" — o Suporte ("Sem atualização: tempo ou
questões não vieram") diz, certo, que nenhum aluno foi atualizado.

Coletas montadas com o navegador falso do Elefante. Dados FICTÍCIOS, sem rede.
"""
from __future__ import annotations

import pathlib

import pytest
from sqlalchemy import select

from app.models.sincronizacao import SincronizacaoAlerta
from tests._sync_nucleo_fakes import (
    NavElefante,
    PlacarFake,
    aluno_el,
    credencial,
    instalar,
    logs,
    rodar,
)
from tests.test_sync_campos_nao_essenciais import (
    CID,
    NAO_ESSENCIAIS,
    _coleta_de_dois_dias_atras,
    _origem,
    _sem,
)

TERMOS_INTERNOS = ("conector",)
AJUSTE = "a equipe do Constela precisa ajustar a coleta dessa plataforma"
SUPORTE = (pathlib.Path(__file__).resolve().parents[2] / "apps" / "web" / "src" / "pages"
           / "suporteConteudo.ts")


def _alertas(db, eid) -> dict[str, str]:
    return dict(db.execute(select(SincronizacaoAlerta.tipo, SincronizacaoAlerta.mensagem).where(
        SincronizacaoAlerta.escola_id == eid, SincronizacaoAlerta.resolvido.is_(False))).all())


def _sem_jargao(*textos: str) -> None:
    for texto in textos:
        for termo in TERMOS_INTERNOS:
            assert termo not in texto.lower(), (termo, texto)


def _segunda_coleta(db, escola_completa, monkeypatch, *, livros_de=None, chaves=NAO_ESSENCIAIS):
    ec = escola_completa
    eid = ec["escola"].id
    a, b, _c = ec["alunos"]
    credencial(db, eid, "elefante")
    nav = NavElefante(_origem(a, b))
    instalar(monkeypatch, nav_elefante=nav)
    rodar(db, eid, "elefante")
    _coleta_de_dois_dias_atras(db)
    _sem(nav, chaves, livros_de=livros_de)
    ex, _ = rodar(db, eid, "elefante")
    return eid, ex


def test_parcial_com_campo_sumido_sem_conector_no_alerta_nem_no_log(
        db, escola_completa, monkeypatch):
    eid, ex = _segunda_coleta(db, escola_completa, monkeypatch, livros_de={9300001: 7})

    assert ex.status == "parcial"
    alertas = _alertas(db, eid)
    formato, parcial = alertas["parser_incompativel"], alertas["coleta_parcial"]
    assert "os livros foram atualizados, mas esses números ficaram com o valor da coleta " \
           "anterior" in formato, formato
    assert f"Sincronizar de novo não resolve: {AJUSTE}." in formato, formato
    assert f"não voltam com outra coleta: {AJUSTE} (alerta “Formato do relatório mudou”)" \
           in parcial, parcial
    _sem_jargao(formato, parcial, *(m for _e, _n, m in logs(db, ex.id)))


def test_sem_atualizacao_com_campo_sumido_nao_diz_que_os_livros_foram_atualizados(
        db, escola_completa, monkeypatch):
    """Ninguém teve dado novo: nada foi gravado. O alerta dizia "os livros foram
    atualizados"."""
    eid, ex = _segunda_coleta(db, escola_completa, monkeypatch,
                              chaves=("responses", "approvedResponses"))

    assert ex.status == "sem_atualizacao"
    formato = _alertas(db, eid)["parser_incompativel"]
    assert "os livros foram atualizados" not in formato, formato
    assert ("A resposta da plataforma veio sem questões aprovadas, questões respondidas em "
            "todas as linhas: nenhum aluno foi atualizado, e esses números ficaram com o "
            "valor da coleta anterior") in formato, formato
    assert f"Sincronizar de novo não resolve: {AJUSTE}." in formato, formato
    _sem_jargao(formato, *(m for _e, _n, m in logs(db, ex.id)))
    if SUPORTE.exists():
        # A entrada do Suporte que manda ler este alerta diz o mesmo.
        suporte = SUPORTE.read_text(encoding="utf-8")
        assert "Sem atualização: tempo ou questões não vieram" in suporte
        assert "nenhum aluno foi atualizado" in suporte
        assert "quem resolve é a equipe do Constela, ajustando a coleta dessa plataforma" \
            in suporte


@pytest.mark.parametrize("livros_de,status", [({9300001: 7}, "parcial"),
                                               (None, "sem_atualizacao")])
@pytest.mark.parametrize("chaves,questoes_nao_medem", [
    (("totalReadTime",), False),
    (("responses",), True),
    (("approvedResponses", "totalReadTime"), True),
])
def test_questoes_do_periodo_so_nao_medem_quando_as_questoes_sumiram(
        db, escola_completa, monkeypatch, livros_de, status, chaves, questoes_nao_medem):
    """Revisão do acabamento (sonda R3): com só o tempo de leitura sumido as questões
    vieram — a importação é 'concluida' e o retrato dela MEDE as questões (é borda do
    Relatório por Período). O alerta dizia sempre "e as Questões do período não medem os
    dias desta coleta"; agora só quando uma das questões sumiu."""
    from app.models import Importacao
    from app.models.plataformas import IMPORTACAO_SEM_QUESTOES

    eid, ex = _segunda_coleta(db, escola_completa, monkeypatch, livros_de=livros_de,
                              chaves=chaves)

    assert ex.status == status, ex.status
    statuses = set(db.execute(select(Importacao.status).where(
        Importacao.escola_id == eid, Importacao.plataforma == "elefante")).scalars())
    assert (IMPORTACAO_SEM_QUESTOES in statuses) is questoes_nao_medem, statuses
    formato = _alertas(db, eid)["parser_incompativel"]
    assert "em todas as linhas: " in formato, formato
    assert ("e as Questões do período não medem os dias desta coleta." in formato) \
        is questoes_nao_medem, formato
    assert f"Sincronizar de novo não resolve: {AJUSTE}." in formato, formato


def test_tudo_com_defeito_sem_conector_no_alerta(db, escola_completa, monkeypatch):
    """Nenhuma linha aproveitável ('erro'): o alerta dizia "Verifique o conector."."""
    ec = escola_completa
    eid = ec["escola"].id
    credencial(db, eid, "elefante")
    nav = NavElefante({CID: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
        aluno_el(9300101, "", []), aluno_el(9300102, "", [])]}})
    instalar(monkeypatch, nav_elefante=nav)

    ex, _ = rodar(db, eid, "elefante")

    assert ex.status == "erro"
    formato = _alertas(db, eid)["parser_incompativel"]
    assert formato.startswith("Nenhuma linha aproveitável"), formato
    assert f"Avise o suporte: {AJUSTE}." in formato, formato
    _sem_jargao(formato, *(m for _e, _n, m in logs(db, ex.id)))
    # Revisão do acabamento (sonda R3): o motivo do descarte saía como código interno,
    # "(sem_nome: 2)".
    assert "2 linha(s) com defeito (sem o nome do aluno: 2)" in formato, formato
    assert "_" not in formato, formato


def test_motivos_de_descarte_sem_codigo_interno():
    """Todo motivo de linha com defeito que conectores, parser e importação anotam sai
    com rótulo nos alertas; um código novo, sem rótulo, sai ao menos sem o "_"."""
    from app.sync import service

    motivos = ("sem_nome", "sem_nome_ou_turma", "sem_nome_ou_titulo", "sem_data",
               "livro_sem_titulo", "id_em_varias_turmas", "campos_ausentes", "codigo_novo")
    ap = service._Apuracao(linhas=len(motivos), descartes=dict.fromkeys(motivos, 1))
    resumo = ap.resumo_descartes()
    assert "_" not in resumo, resumo
    assert set(motivos[:-1]) <= set(service._ROTULO_DESCARTE), resumo
    assert "codigo novo: 1" in resumo, resumo


class _PlacarFormatoNovo(PlacarFake):
    """O Placar respondeu 200, mas sem a lista 'data' (a API mudou de formato)."""

    def school_student(self, expr):
        self.filtros.append("?")
        return {"ok": True, "status": 200, "body": [{"school_id": "x", "rows": []}]}


def test_formato_mudou_no_matific_sem_conector_no_alerta(db, escola_completa, monkeypatch):
    """Revisão do acabamento (sonda R3): o alerta "Formato do relatório mudou" do Matific
    vem da mensagem do próprio conector, crua no alerta, no log e no erro_resumo — e
    dizia "(sem a lista 'data') — a API pode ter mudado. Verifique o conector."."""
    eid = escola_completa["escola"].id
    credencial(db, eid, "matific")
    placar = _PlacarFormatoNovo()
    placar.linhas = [("u-a", escola_completa["alunos"][0].nome, "3 ANO A", 40, 10)]
    instalar(monkeypatch, placar=placar)

    ex, erro = rodar(db, eid, "matific")

    assert erro is None and (ex.status, ex.motivo) == ("erro", "parser_incompativel")
    formato = _alertas(db, eid)["parser_incompativel"]
    assert formato.startswith("O Placar do Matific respondeu num formato que o Constela "
                              "não reconhece"), formato
    assert f"Avise o suporte: {AJUSTE}." in formato, formato
    assert "'data'" not in formato and "API" not in formato, formato
    _sem_jargao(formato, ex.erro_resumo, *(m for _e, _n, m in logs(db, ex.id)))


def test_lista_de_turmas_do_elefante_fora_do_formato_sem_conector_no_alerta(
        db, escola_completa, monkeypatch):
    """O mesmo na lista de turmas do Elefante (2xx fora do formato): dizia "— a API pode
    ter mudado. Verifique o conector."."""
    from tests.test_sync_revisao_semantica import _NavRosterForaDoFormato

    eid = escola_completa["escola"].id
    credencial(db, eid, "elefante")
    instalar(monkeypatch, nav_elefante=_NavRosterForaDoFormato(
        {"courses": [{"id": 1, "name": "3 ANO A", "student": []}]}))

    ex, _ = rodar(db, eid, "elefante")

    assert (ex.status, ex.motivo) == ("erro", "parser_incompativel")
    formato = _alertas(db, eid)["parser_incompativel"]
    assert formato.startswith("A lista de turmas do Elefante respondeu num formato que o "
                              "Constela não reconhece"), formato
    assert f"Avise o suporte: {AJUSTE}." in formato, formato
    _sem_jargao(formato, ex.erro_resumo, *(m for _e, _n, m in logs(db, ex.id)))


@pytest.mark.parametrize("chave", ["totalBooksRead"])
def test_campo_essencial_sumido_sem_conector_no_log(db, escola_completa, monkeypatch, chave):
    """O campo essencial sumiu de todas as linhas (nada aplicado): a linha do log da
    execução, que a tela mostra em "Detalhes técnicos", dizia "(o conector precisa ser
    revisto)"."""
    eid, ex = _segunda_coleta(db, escola_completa, monkeypatch, chaves=(chave,))

    linhas = [m for _e, _n, m in logs(db, ex.id)]
    assert any(f"nada aplicado ({AJUSTE})" in m for m in linhas), linhas
    _sem_jargao(*linhas, *_alertas(db, eid).values())
