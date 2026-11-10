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


@pytest.mark.parametrize("chave", ["totalBooksRead"])
def test_campo_essencial_sumido_sem_conector_no_log(db, escola_completa, monkeypatch, chave):
    """O campo essencial sumiu de todas as linhas (nada aplicado): a linha do log da
    execução, que a tela mostra em "Detalhes técnicos", dizia "(o conector precisa ser
    revisto)"."""
    eid, ex = _segunda_coleta(db, escola_completa, monkeypatch, chaves=(chave,))

    linhas = [m for _e, _n, m in logs(db, ex.id)]
    assert any(f"nada aplicado ({AJUSTE})" in m for m in linhas), linhas
    _sem_jargao(*linhas, *_alertas(db, eid).values())
