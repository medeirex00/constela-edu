"""PEND-14 (ingestão): a cópia NATIVA que a ingestão deixa de gravar fica no log, e a
regra 9 da restauração histórica a enxerga.

``eventos.ingerir_eventos`` não grava a cópia nativa de um evento quando o mesmo
conteúdo já está na ficha, vindo de uma ficha absorvida (a fusão moveu o evento com
a chave da absorvida). Era o único caminho em que a ocorrência anterior de um livro
para uma ficha sumia SEM deixar rastro: a fusão e a limpeza do passivo já registram
o que descartam (``leituras_restauracao._LOGS_DE_DESCARTE``). Se depois a ficha
ganha uma releitura e é absorvida, a releitura passava por "primeira" e a
restauração aceitava reescrever a data da leitura para a data errada.

Agora a ingestão registra ``aluno.eventos_nativos_nao_gravados`` na ficha (livro,
instante e a chave que a cópia nativa teria; sem nome) e a regra 9 lê esse log como
os outros descartes. Dados fictícios.
"""
from datetime import datetime

import pytest
from sqlalchemy import select

from app.models import LogAuditoria
from app.services import leituras_restauracao as lr
from app.services.eventos import chave_evento
from tests.test_aud_alunos_fusao_eventos import AGOSTO, MARCO, TITULO, _eventos, _fundir, _importar

T_MARCO = datetime(2026, 3, 10, 10, 0)
T_AGOSTO = datetime(2026, 8, 6, 0, 1)


def _pedir(db, escola_id, aluno_id, origem_id, evento):
    return lr.planejar(db, escola_id, [lr.ItemRestauracao(
        aluno_id=aluno_id, aluno_origem_id=origem_id, livro_id=evento.livro_id,
        data_original=evento.ocorrido_em, tempo_original=15,
        evidencia_evento_id=evento.id, evidencia_chave_natural=evento.chave_natural,
        motivo="restaurar a data da ficha de origem (ficticio)")])


def test_releitura_nao_passa_por_primeira_quando_a_ingestao_nao_gravou_a_nativa(
        cliente, db, escola_completa):
    """Y leu em março; D absorve Y. A coleta seguinte manda a mesma linha de março
    para D: a cópia nativa de D não é gravada (o conteúdo já está lá, com a chave de
    Y). D lê de novo em agosto e W absorve D. Agosto não é a primeira leitura de D:
    a restauração tem de recusar."""
    esc = escola_completa["escola"]
    d, y, w = escola_completa["alunos"]
    did, yid, wid = d.id, y.id, w.id
    _importar(cliente, esc.id, y, MARCO)
    _fundir(cliente, esc.id, did, yid)
    _importar(cliente, esc.id, d, MARCO)            # a nativa de março não é gravada
    assert len(_eventos(db, did)) == 1
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "aluno.eventos_nativos_nao_gravados")).scalars().all()
    assert len(log) == 1 and log[0].entidade_id == did and log[0].escola_id == esc.id
    [registro] = log[0].detalhes["eventos"]
    assert registro["chave_natural"] == chave_evento("elefante", "leitura", did, TITULO, T_MARCO)
    assert registro["ocorrido_em"] == T_MARCO.isoformat()
    assert d.nome not in str(log[0].detalhes)

    _importar(cliente, esc.id, d, AGOSTO)
    _fundir(cliente, esc.id, wid, did)
    eventos = _eventos(db, wid)
    agosto = next(e for e in eventos if e.ocorrido_em == T_AGOSTO and e.chave_natural ==
                  chave_evento("elefante", "leitura", did, TITULO, T_AGOSTO))
    with pytest.raises(lr.RestauracaoInvalida) as recusa:
        print("PLANO ACEITO:", _pedir(db, esc.id, wid, did, agosto))
    assert "não é a primeira ocorrência" in recusa.value.mensagem
    assert "10/03/2026" in recusa.value.mensagem


def test_reimportar_o_que_ja_esta_na_ficha_nao_registra_nada(cliente, db, escola_completa):
    """Controle: a reimportação da própria cópia nativa (mesma chave) não é descarte
    nenhum — nada no log."""
    esc = escola_completa["escola"]
    d = escola_completa["alunos"][0]
    _importar(cliente, esc.id, d, MARCO)
    _importar(cliente, esc.id, d, MARCO)
    assert len(_eventos(db, d.id)) == 1
    assert db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "aluno.eventos_nativos_nao_gravados")).first() is None


def test_o_log_novo_esta_entre_os_descartes_da_restauracao():
    assert lr._LOGS_DE_DESCARTE["aluno.eventos_nativos_nao_gravados"] == "eventos"
