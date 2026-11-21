"""Auditoria (frente importação): a ETAPA da turma vale na PRÉVIA — prévia = confirmação.

IMPORTACAO-3 / REVERIFICACAO-1 (b): a regra "ficha nova não nasce em turma de outra
etapa" existia só na gravação (``_resolver_aluno``). A prévia (``identidade_aluno.
decidir``) achava a "1ºA" de ano_escolar "1ª Fase" para o relatório "1 ANO A …",
dizia "Novo aluno" e a confirmação abria a revisão ``turma_de_outra_etapa`` — o
coordenador lia "1 de 1 aluno(s) serão importados" e nada nascia. Agora a porta única
decide a etapa: a prévia já diz o motivo, a turma da sala que é de outra etapa não é
destino (com uma da etapa certa na mesma sala, vale ela) e a pendência não sugere a
turma recusada. Dados fictícios.
"""
from sqlalchemy import select

from tests.test_aud_imp_etapa_turma import (
    _analise, _confirmar, _motivos, _placar, _turma, _turmas_do_aluno)

API = "/api/v1"


def _uma_crianca(turma, nome="Crianca Ficticia Primeiro Ano"):
    return _placar(turma, [{"nome": nome, "uuid": "uuid-fict-etapa", "estrelas": 5,
                            "atividades": 1}])


def _corpo_criar_na_turma_do_relatorio(analise, turma_relatorio):
    return [{"nome": linha["nome"], "dados": linha["dados"], "aluno_id": None,
             "criar_em_turma_id": None, "criar_em_turma_nome": turma_relatorio}
            for linha in analise["linhas"]]


def test_previa_ja_diz_turma_de_outra_etapa_e_a_confirmacao_concorda(
        cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    _turma(db, eid, "1ºA", "1ª Fase")
    analise = _analise(cliente, eid, _uma_crianca("1 ANO A TARDE ANUAL"))
    corr = analise["linhas"][0]["correspondencia"]
    assert (corr["status"], corr["motivo"]) == ("revisar", "turma_de_outra_etapa"), corr
    res = _confirmar(cliente, eid, analise,
                     _corpo_criar_na_turma_do_relatorio(analise, "1 ANO A TARDE ANUAL"))
    assert (res["qtd_alunos"], res["qtd_revisoes"]) == (0, 1), res
    assert _turmas_do_aluno(db, eid, "Crianca Ficticia Primeiro Ano") == []
    assert _motivos(db, eid) == ["turma_de_outra_etapa"]


def test_sala_com_turmas_das_duas_etapas_usa_a_da_etapa_do_relatorio(
        cliente, db, escola_completa):
    """A escola tem a "1ºA" da Fase e a "1º Ano A" do Fundamental — as duas na sala
    1|A. A criança do "1 ANO A" nasce na do Fundamental; a do "Fase 1A", na da Fase.
    Antes a do 1º Ano caía na "1ºA" (nome idêntico ao normalizado) e ia para a revisão."""
    eid = escola_completa["escola"].id
    _turma(db, eid, "1ºA", "1ª Fase")
    _turma(db, eid, "1º Ano A", "1º Ano")
    for relatorio, nome, esperada in (("1 ANO A", "Crianca Ficticia Do Ano", "1º Ano A"),
                                      ("Fase 1A", "Crianca Ficticia Da Fase", "1ºA")):
        analise = _analise(cliente, eid, _placar(relatorio, [
            {"nome": nome, "uuid": f"uuid-fict-{esperada}", "estrelas": 5, "atividades": 1}]))
        corr = analise["linhas"][0]["correspondencia"]
        assert corr["status"] == "nao_encontrado", (relatorio, corr)
        _confirmar(cliente, eid, analise,
                   _corpo_criar_na_turma_do_relatorio(analise, relatorio))
        assert _turmas_do_aluno(db, eid, nome) == [esperada], (relatorio, _motivos(db, eid))
    assert _motivos(db, eid) == []


def test_turma_escolhida_de_outra_etapa_ja_e_revisao_na_previa_da_confirmacao(
        cliente, db, escola_completa):
    """A turma da Fase escolhida para a criança do 1º Ano: a decisão da porta única
    (não só a rede de segurança da gravação) diz turma_de_outra_etapa."""
    from app.services import identidade_aluno as ida

    eid = escola_completa["escola"].id
    fase = _turma(db, eid, "1ºA", "1ª Fase")
    ctx = ida.carregar_contexto(db, eid)
    linha = ida.linha_de_dados("Crianca Ficticia Primeiro Ano", {"matific_uuid": "u-1"},
                               plataforma="matific", turma_nome="1ºA", turma_id=fase,
                               turma_relatorio="1 ANO A TARDE ANUAL")
    dec = ida.decidir(ctx, linha)
    assert (dec.acao, dec.motivo) == (ida.REVISAR, "turma_de_outra_etapa"), dec


def test_pendencia_de_outra_etapa_nao_sugere_a_turma_recusada(cliente, db, escola_completa):
    """A pendência turma_de_outra_etapa não traz como turma sugerida para a ficha nova
    justamente a turma de outra etapa que o sistema recusou."""
    from app.models import RevisaoIdentidade

    eid = escola_completa["escola"].id
    _turma(db, eid, "1ºA", "1ª Fase")
    analise = _analise(cliente, eid, _uma_crianca("1 ANO A TARDE ANUAL"))
    _confirmar(cliente, eid, analise,
               _corpo_criar_na_turma_do_relatorio(analise, "1 ANO A TARDE ANUAL"))
    db.expire_all()
    rev = db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == eid)).scalar_one()
    assert rev.motivo == "turma_de_outra_etapa"
    assert rev.turma_id is None, "a pendência sugere a turma da Fase para a criança do 1º Ano"
