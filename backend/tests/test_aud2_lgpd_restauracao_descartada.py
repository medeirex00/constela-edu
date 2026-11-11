"""PEND-14 (REV-ALUNOS-1-A): a restauração histórica conta como "ocorrência anterior"
também o evento que a deduplicação DESCARTOU — e que ficou só no log.

A regra 9 de ``leituras_restauracao._conferir`` só aceita como evidência a PRIMEIRA
ocorrência do livro na ficha de origem, e procurava as anteriores só entre os
eventos vivos. A fusão (log ``aluno.fundido``, ``eventos_descartados_detalhe``) e a
limpeza do passivo (``aluno.eventos_duplicados_removidos``, ``eventos``) ainda tiram
a cópia NATIVA única de uma ficha (ela não tinha releitura naquela hora). Se depois
essa ficha ganha uma releitura e é absorvida, a releitura passava por "primeira" e a
restauração aceitava reescrever a data da leitura para a data errada.

Agora a regra 9 lê também os descartes da escola: mesmo livro, instante anterior e
chave que prova a mesma ficha de origem → recusa, dizendo que a anterior foi
descartada como cópia repetida. Dados fictícios.
"""
from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.models import EventoAluno, LogAuditoria
from app.services import leituras_restauracao as lr
from app.services.eventos import chave_evento, deduplicar_eventos_por_conteudo
from tests.test_aud_alunos_fusao_eventos import AGOSTO, MARCO, TITULO, _eventos, _fundir, _importar

T_MARCO = datetime(2026, 3, 10, 10, 0)
T_AGOSTO = datetime(2026, 8, 6, 0, 1)


def _pedir(db, escola_id, aluno_id, origem_id, evento):
    return lr.planejar(db, escola_id, [lr.ItemRestauracao(
        aluno_id=aluno_id, aluno_origem_id=origem_id, livro_id=evento.livro_id,
        data_original=evento.ocorrido_em, tempo_original=15,
        evidencia_evento_id=evento.id, evidencia_chave_natural=evento.chave_natural,
        motivo="restaurar a data da ficha de origem (ficticio)")])


def _de(eventos, quando, origem):
    return next(e for e in eventos if e.ocorrido_em == quando and e.chave_natural ==
                chave_evento("elefante", "leitura", origem, TITULO, quando))


def test_releitura_nao_passa_por_primeira_quando_a_primeira_saiu_na_fusao(
        cliente, db, escola_completa):
    """D e Y leram em março (a mesma linha do relatório). D absorve Y: sai a cópia
    nativa de D (sem releitura naquela hora). D lê de novo em agosto e W absorve D.
    Agosto não é a primeira leitura de D: a restauração tem de recusar."""
    esc = escola_completa["escola"]
    d, y, w = escola_completa["alunos"]
    did, yid, wid = d.id, y.id, w.id
    _importar(cliente, esc.id, d, MARCO)
    _importar(cliente, esc.id, y, MARCO)
    corpo = _fundir(cliente, esc.id, did, yid)
    assert corpo["eventos_descartados"] == 1
    _importar(cliente, esc.id, d, AGOSTO)
    _fundir(cliente, esc.id, wid, did)
    eventos = _eventos(db, wid)
    assert not [e for e in eventos if e.chave_natural == chave_evento(
        "elefante", "leitura", did, TITULO, T_MARCO)], "pré-condição: a de março de D saiu"

    with pytest.raises(lr.RestauracaoInvalida) as recusa:
        print("PLANO ACEITO:", _pedir(db, esc.id, wid, did, _de(eventos, T_AGOSTO, did)))
    texto = recusa.value.mensagem
    assert "não é a primeira ocorrência" in texto
    assert "10/03/2026" in texto and "descartad" in texto


def test_releitura_nao_passa_por_primeira_quando_a_limpeza_tirou_a_primeira(
        cliente, db, escola_completa):
    """O mesmo pela limpeza do passivo (``deduplicar_eventos_por_conteudo``): uma
    fusão antiga deixou as duas cópias de março em D; a limpeza tira a nativa, e a
    remoção fica só em ``aluno.eventos_duplicados_removidos``."""
    esc = escola_completa["escola"]
    d, y, w = escola_completa["alunos"]
    did, yid, wid = d.id, y.id, w.id
    _importar(cliente, esc.id, d, MARCO)
    _importar(cliente, esc.id, y, MARCO)
    _fundir(cliente, esc.id, did, yid)
    # O passivo de antes do conserto: a cópia nativa de D continuou ao lado da de Y,
    # e o log da fusão não falava dela.
    nativa = next(e for e in _eventos(db, did))
    db.add(EventoAluno(escola_id=esc.id, aluno_id=did, plataforma="elefante",
                       tipo_evento="leitura", conteudo_titulo=TITULO, livro_id=nativa.livro_id,
                       ocorrido_em=T_MARCO, tempo_segundos=15 * 60,
                       chave_natural=chave_evento("elefante", "leitura", did, TITULO, T_MARCO)))
    log = db.execute(select(LogAuditoria).where(LogAuditoria.acao == "aluno.fundido")).scalar_one()
    log.detalhes = {**log.detalhes, "eventos_descartados_detalhe": []}
    flag_modified(log, "detalhes")
    db.commit()
    assert deduplicar_eventos_por_conteudo(db, escola_id=esc.id, aplicar=True)[
        "eventos_duplicados"] == 1
    db.commit()
    _importar(cliente, esc.id, d, AGOSTO)
    _fundir(cliente, esc.id, wid, did)
    eventos = _eventos(db, wid)

    with pytest.raises(lr.RestauracaoInvalida) as recusa:
        print("PLANO ACEITO:", _pedir(db, esc.id, wid, did, _de(eventos, T_AGOSTO, did)))
    assert "não é a primeira ocorrência" in recusa.value.mensagem


def test_evidencia_que_e_mesmo_a_primeira_continua_aceita(cliente, db, escola_completa):
    """Controle: Y leu em agosto só. D (com março nativo) absorve Y — a leitura de D
    fica com março; a evidência de Y (agosto) é a primeira dela e o descarte de outra
    ficha no log não a barra."""
    esc = escola_completa["escola"]
    d, y, _ = escola_completa["alunos"]
    did, yid = d.id, y.id
    _importar(cliente, esc.id, d, MARCO)
    _importar(cliente, esc.id, y, AGOSTO)
    _fundir(cliente, esc.id, did, yid)
    eventos = _eventos(db, did)
    plano = _pedir(db, esc.id, did, yid, _de(eventos, T_AGOSTO, yid))
    assert plano[0]["data_restaurada"] == T_AGOSTO
