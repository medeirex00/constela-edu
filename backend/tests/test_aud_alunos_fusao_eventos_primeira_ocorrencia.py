"""A deduplicação de eventos não pode apagar a PRIMEIRA leitura de uma ficha.

O DEFEITO (REV-ALUNOS-1, sobre o conserto do ALUNOS-3). A fusão e a limpeza do
passivo descartam a cópia repetida por conteúdo (a mesma linha do relatório em
duas fichas). Mas a restauração histórica (``leituras_restauracao``, regra 9)
só aceita como evidência a PRIMEIRA ocorrência do livro na ficha de origem, e
sabe qual é a primeira pela chave do evento — que traz a ficha. Quando a cópia
descartada era a primeira daquela ficha e a ficha tinha uma ocorrência
POSTERIOR do mesmo livro, a posterior passava a parecer a primeira e a
restauração aceitava reescrever a data da leitura para a data errada.

O CONSERTO. A cópia que é a primeira ocorrência do livro para a ficha de onde
veio, quando essa ficha tem outra ocorrência do mesmo livro depois, não é
descartada: sai a outra cópia, se puder; se as duas forem primeiras, ficam as
duas (a evidência vale mais do que um registro repetido na linha do tempo).

Dados fictícios.
"""
from datetime import datetime

import pytest
from sqlalchemy import select

from app.models import EventoAluno, LogAuditoria
from app.services import leituras_restauracao as lr
from app.services.eventos import chave_evento, deduplicar_eventos_por_conteudo
from tests.test_aud_alunos_fusao_eventos import (
    AGOSTO,
    MARCO,
    TITULO,
    _eventos,
    _fundir,
    _importar,
)

SETEMBRO = "2026-09-02T14:30:00"
T_MARCO = datetime(2026, 3, 10, 10, 0)
T_AGOSTO = datetime(2026, 8, 6, 0, 1)


def _pedir(db, escola_id, aluno_id, origem_id, evento, motivo="restaurar a data da origem"):
    return lr.planejar(db, escola_id, [lr.ItemRestauracao(
        aluno_id=aluno_id, aluno_origem_id=origem_id, livro_id=evento.livro_id,
        data_original=evento.ocorrido_em, tempo_original=15,
        evidencia_evento_id=evento.id, evidencia_chave_natural=evento.chave_natural,
        motivo=motivo)])


def _de(eventos, quando, origem):
    """O evento da ficha ``origem`` naquele instante (pela chave)."""
    return next((e for e in eventos if e.ocorrido_em == quando and e.chave_natural ==
                 chave_evento("elefante", "leitura", origem, TITULO, quando)), None)


def test_fusao_nao_apaga_a_primeira_leitura_de_uma_ficha_absorvida(cliente, db,
                                                                   escola_completa):
    """A sonda do revisor: Z leu em março; Y leu em março e em agosto. D absorve Z
    e depois Y. A primeira leitura de Y (março) não pode sumir — senão agosto
    passa por "primeira ocorrência de Y" e a restauração aceita a data errada."""
    esc = escola_completa["escola"]
    d, z, y = escola_completa["alunos"]
    did, zid, yid = d.id, z.id, y.id
    _importar(cliente, esc.id, z, MARCO)
    _importar(cliente, esc.id, y, MARCO, AGOSTO)
    _fundir(cliente, esc.id, did, zid)
    corpo = _fundir(cliente, esc.id, did, yid)
    eventos = _eventos(db, did)
    print("EVENTOS NO D:", [(e.id, e.ocorrido_em.isoformat()) for e in eventos],
          "| descartados:", corpo.get("eventos_descartados"))
    posterior = _de(eventos, T_AGOSTO, yid)
    with pytest.raises(lr.RestauracaoInvalida) as recusa:
        print("PLANO ACEITO:", _pedir(db, esc.id, did, yid, posterior))
    print("RECUSADO:", recusa.value.mensagem[:160])
    assert "não é a primeira ocorrência" in recusa.value.mensagem
    assert _de(eventos, T_MARCO, yid) is not None, "a primeira leitura de Y sumiu"


def test_fusao_nao_apaga_a_primeira_leitura_nativa_que_tem_releitura(cliente, db,
                                                                     escola_completa):
    """A mesma regra vale para a cópia NATIVA da ficha que fica: ela vira origem
    quando essa ficha é absorvida depois. D leu em março e em agosto; Z leu em
    março. D absorve Z, e W absorve D. Agosto não é a primeira leitura de D."""
    esc = escola_completa["escola"]
    d, z, w = escola_completa["alunos"]
    did, zid, wid = d.id, z.id, w.id
    _importar(cliente, esc.id, d, MARCO, AGOSTO)
    _importar(cliente, esc.id, z, MARCO)
    corpo = _fundir(cliente, esc.id, did, zid)
    assert corpo["eventos_descartados"] == 1          # a mesma leitura não fica dobrada
    assert len(_eventos(db, did)) == 2
    _fundir(cliente, esc.id, wid, did)
    eventos = _eventos(db, wid)
    print("EVENTOS NO W:", [(e.id, e.ocorrido_em.isoformat()) for e in eventos])
    with pytest.raises(lr.RestauracaoInvalida) as recusa:
        print("PLANO ACEITO:", _pedir(db, esc.id, wid, did, _de(eventos, T_AGOSTO, did)))
    assert "não é a primeira ocorrência" in recusa.value.mensagem
    assert _de(eventos, T_MARCO, did) is not None, "a primeira leitura de D sumiu"


def test_quando_as_duas_copias_sao_primeiras_as_duas_ficam(cliente, db, escola_completa):
    """Z leu em março e em setembro; Y em março e em agosto. Apagar qualquer uma
    das cópias de março tiraria a primeira leitura de uma das fichas: ficam as
    duas, e a restauração recusa a releitura das duas."""
    esc = escola_completa["escola"]
    d, z, y = escola_completa["alunos"]
    did, zid, yid = d.id, z.id, y.id
    _importar(cliente, esc.id, z, MARCO, SETEMBRO)
    _importar(cliente, esc.id, y, MARCO, AGOSTO)
    _fundir(cliente, esc.id, did, zid)
    _fundir(cliente, esc.id, did, yid)
    eventos = _eventos(db, did)
    assert len(eventos) == 4
    for origem, quando in ((zid, datetime(2026, 9, 2, 14, 30)), (yid, T_AGOSTO)):
        with pytest.raises(lr.RestauracaoInvalida):
            _pedir(db, esc.id, did, origem, _de(eventos, quando, origem))


def test_fusao_ainda_descarta_a_copia_que_nao_e_evidencia(cliente, db, escola_completa):
    """D leu em março e em agosto; Z só em março. A primeira de D fica; a de Z, que
    não tem releitura, é a repetida — e vai para o log da fusão."""
    esc = escola_completa["escola"]
    d, z, _ = escola_completa["alunos"]
    did, zid = d.id, z.id
    _importar(cliente, esc.id, d, MARCO, AGOSTO)
    _importar(cliente, esc.id, z, MARCO)
    corpo = _fundir(cliente, esc.id, did, zid)
    eventos = _eventos(db, did)
    assert corpo["eventos_descartados"] == 1 and corpo["eventos_movidos"] == 0
    assert [e.chave_natural for e in eventos] == [
        chave_evento("elefante", "leitura", did, TITULO, T_MARCO),
        chave_evento("elefante", "leitura", did, TITULO, T_AGOSTO)]
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "aluno.fundido")).scalars().one()
    detalhe, = log.detalhes["eventos_descartados_detalhe"]
    assert detalhe["chave_natural"] == chave_evento("elefante", "leitura", zid, TITULO,
                                                    T_MARCO)


# ---------------------------------------------------------------------------
# A limpeza do passivo segue a mesma regra
# ---------------------------------------------------------------------------
def _evento(db, escola_id, aluno_id, origem, quando, livro_id):
    ev = EventoAluno(escola_id=escola_id, aluno_id=aluno_id, plataforma="elefante",
                     tipo_evento="leitura", ocorrido_em=quando, conteudo_titulo=TITULO,
                     tempo_segundos=900, livro_id=livro_id,
                     chave_natural=chave_evento("elefante", "leitura", origem, TITULO, quando))
    db.add(ev)
    db.flush()
    return ev


def _fusao_antiga(db, escola_id, manter_id, remover_id):
    db.add(LogAuditoria(escola_id=escola_id, acao="aluno.fundido", entidade="aluno",
                        entidade_id=manter_id,
                        detalhes={"mantido": {"id": manter_id}, "removido": {"id": remover_id}}))


def test_limpeza_do_passivo_nao_apaga_a_primeira_leitura_de_uma_ficha(cliente, db,
                                                                      escola_completa):
    """Passivo de uma fusão antiga: D absorveu Z e Y; as duas trouxeram março, e Y
    também agosto. A cópia de março que sai é a de Z (sem releitura), mesmo
    tendo id menor; a de Y é a primeira leitura de Y."""
    esc = escola_completa["escola"]
    d, _, _ = escola_completa["alunos"]
    did = d.id
    _importar(cliente, esc.id, d, SETEMBRO)            # cria o livro e a leitura de D
    livro_id = _eventos(db, did)[0].livro_id
    db.execute(EventoAluno.__table__.delete().where(EventoAluno.aluno_id == did))
    z, y = 9101, 9102                                   # fichas que já não existem
    da_z = _evento(db, esc.id, did, z, T_MARCO, livro_id)
    da_y = _evento(db, esc.id, did, y, T_MARCO, livro_id)
    _evento(db, esc.id, did, y, T_AGOSTO, livro_id)
    _fusao_antiga(db, esc.id, did, z)
    _fusao_antiga(db, esc.id, did, y)
    db.commit()
    da_z_id, da_y_id = da_z.id, da_y.id

    resultado = deduplicar_eventos_por_conteudo(db, escola_id=esc.id, aplicar=True)
    db.commit()
    assert resultado == {"alunos": 1, "eventos_duplicados": 1}
    eventos = _eventos(db, did)
    assert da_z_id not in {e.id for e in eventos}
    assert da_y_id in {e.id for e in eventos}
    with pytest.raises(lr.RestauracaoInvalida) as recusa:
        _pedir(db, esc.id, did, y, _de(eventos, T_AGOSTO, y))
    assert "não é a primeira ocorrência" in recusa.value.mensagem
