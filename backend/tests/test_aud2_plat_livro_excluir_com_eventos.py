"""Excluir do catálogo um livro sem leitura que ainda tem eventos (G_AJUSTE-8).

``EventoAluno.livro_id`` aponta para ``livros.id`` sem ON DELETE. O saneamento dos
homônimos remove a Leitura legado e MANTÉM, de propósito, o evento no livro legado
(o evento é a prova documental que a restauração histórica usa). A exclusão só
conferia Leitura: o DELETE estourava a chave estrangeira e a tela mostrava "Erro
interno". Agora é 409 com a explicação, e nada é apagado.

Dados fictícios (os títulos homônimos são do próprio catálogo oficial).
"""
from datetime import datetime

from sqlalchemy import select

from app.models import EventoAluno, Leitura, Livro, LogAuditoria
from app.services import livros_homonimos_saneamento as san
from app.services.eventos import chave_evento

API = "/api/v1"
INSTANTE = datetime(2026, 3, 30, 20, 50, 43)


def _livro(db, escola_id: int, titulo: str, nivel: str, origem: str = "legado",
           elefante_id=None) -> Livro:
    livro = Livro(escola_id=escola_id, titulo=titulo, nivel_codigo=nivel, nivel_fonte=nivel,
                  origem_nivel=origem, elefante_id=elefante_id)
    db.add(livro)
    db.flush()
    return livro


def _evento(db, escola_id: int, aluno_id: int, livro: Livro) -> None:
    db.add(EventoAluno(
        escola_id=escola_id, aluno_id=aluno_id, plataforma="elefante",
        tipo_evento="leitura", ocorrido_em=INSTANTE, conteudo_titulo=livro.titulo,
        livro_id=livro.id, tempo_segundos=300, nivel_codigo=livro.nivel_codigo,
        chave_natural=chave_evento("elefante", "leitura", aluno_id, livro.titulo, INSTANTE)))
    db.flush()


def _excluido_no_log(db, livro_id: int) -> bool:
    return db.execute(select(LogAuditoria.id).where(
        LogAuditoria.acao == "livro.excluido",
        LogAuditoria.entidade_id == livro_id)).first() is not None


def test_livro_sem_leitura_com_evento_responde_409_e_nao_apaga(cliente_global, db,
                                                               escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    livro = _livro(db, escola.id, "Caderno de Viagem Fictício", "D")
    _evento(db, escola.id, ana.id, livro)
    db.commit()

    r = cliente_global.delete(f"{API}/escolas/{escola.id}/livros/{livro.id}")
    assert r.status_code == 409, r.text
    assert "linha do tempo" in r.json()["detail"]
    db.expire_all()
    assert db.get(Livro, livro.id) is not None
    assert not _excluido_no_log(db, livro.id)


def test_livro_sem_leitura_e_sem_evento_continua_excluivel(cliente_global, db,
                                                           escola_completa):
    escola = escola_completa["escola"]
    livro_id = _livro(db, escola.id, "Caderno de Viagem Fictício", "D").id
    db.commit()
    r = cliente_global.delete(f"{API}/escolas/{escola.id}/livros/{livro_id}")
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(Livro, livro_id) is None
    assert _excluido_no_log(db, livro_id)


def test_livro_legado_depois_do_saneamento_responde_409(cliente_global, db, escola_completa):
    """O estado que o saneamento dos homônimos deixa por desenho: o livro legado
    perde a Leitura e mantém o evento."""
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    legado = _livro(db, escola.id, "Cadê?", "BB", "legado", 4799)
    fonte = _livro(db, escola.id, "Cadê?", "B", "fonte", 2356)
    for livro, com_evento in ((legado, True), (fonte, False)):
        db.add(Leitura(escola_id=escola.id, aluno_id=ana.id, livro_id=livro.id, data=INSTANTE,
                       tempo_leitura_min=5, nivel_codigo=livro.nivel_codigo))
        if com_evento:
            _evento(db, escola.id, ana.id, livro)
    db.commit()
    san.executar(db, [escola.id], None, "duplicata homonima provada no teste")
    db.commit()
    db.expire_all()
    assert db.execute(select(Leitura.id).where(Leitura.livro_id == legado.id)).first() is None

    r = cliente_global.delete(f"{API}/escolas/{escola.id}/livros/{legado.id}")
    assert r.status_code == 409, r.text
    db.expire_all()
    assert db.get(Livro, legado.id) is not None
