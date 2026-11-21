"""Trocar o título de um livro FORA do catálogo oficial que já tem leituras (G_AJUSTE-5).

Fora do catálogo do Elefante, a coleta reconhece o livro da escola pelo TÍTULO que
vem da plataforma (``importacoes._AcervoEscola.resolver``: sem id oficial, só o
título normalizado — sem acento, sem caixa, espaços únicos). O PATCH /livros
aceitava trocar esse título; a coleta seguinte não achava o livro renomeado, criava
outro e gravava DE NOVO todas as leituras já registradas (a regra de releitura
compara o livro), com +1 livro, minutos e pontos para cada criança — enquanto o
aviso devolvido prometia que o histórico continuava como estava.

Agora a troca é recusada com 409 e a explicação. Continuam livres: corrigir
acentos, maiúsculas e espaços (não mudam o reconhecimento), renomear um livro sem
leituras e renomear um livro do catálogo oficial (a coleta o acha pelo id).

Dados fictícios (o livro do catálogo é lido do próprio arquivo do catálogo).
"""
from datetime import datetime

from sqlalchemy import select

from app.models import Leitura, Livro, LogAuditoria
from app.services import dificuldade_livro

API = "/api/v1"
QUANDO = datetime(2026, 6, 1, 10, 0, 0)
TITULO_PLATAFORMA = "Diario de Bordo Ficticio"          # fora do catálogo oficial


def _livro(db, escola_id: int, titulo: str, nivel: str, elefante_id=None) -> Livro:
    livro = Livro(escola_id=escola_id, titulo=titulo, nivel_codigo=nivel, nivel_fonte=nivel,
                  origem_nivel="legado", elefante_id=elefante_id)
    db.add(livro)
    db.flush()
    return livro


def _leitura(db, escola_id: int, aluno_id: int, livro: Livro) -> None:
    db.add(Leitura(escola_id=escola_id, aluno_id=aluno_id, livro_id=livro.id, data=QUANDO,
                   tempo_leitura_min=7, nivel_codigo=livro.nivel_codigo))
    db.commit()


def _coleta(cliente, escola_id: int, aluno, titulo: str, nivel: str) -> None:
    """A coleta do Elefante (o mesmo núcleo da sincronização) trazendo a leitura."""
    r = cliente.post(f"{API}/escolas/{escola_id}/importacoes/confirmar", json={
        "plataforma": "elefante", "formato": "leituras", "tipo": "texto",
        "linhas": [{"nome": aluno.nome, "aluno_id": aluno.id,
                    "dados": {"livro": titulo, "nivel": nivel, "data": QUANDO.isoformat(),
                              "tempo_livro_min": 7}}]})
    assert r.status_code == 200, r.text


def _leituras(db, aluno_id: int) -> list[int]:
    db.expire_all()
    return db.execute(select(Leitura.livro_id).where(Leitura.aluno_id == aluno_id)
                      .order_by(Leitura.id)).scalars().all()


def test_renomear_livro_fora_do_catalogo_com_leituras_e_recusado(cliente, cliente_global, db,
                                                                 escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    livro = _livro(db, escola.id, TITULO_PLATAFORMA, "C")
    _leitura(db, escola.id, ana.id, livro)
    url = f"{API}/escolas/{escola.id}/livros/{livro.id}"

    for corpo in ({"titulo": "Diário de Bordo Fictício (2ª edição)"},
                  {"titulo": "Outro Diário", "nivel_codigo": "D",
                   "motivo": "nível conferido na plataforma"}):
        r = cliente_global.patch(url, json=corpo)
        assert r.status_code == 409, r.text
        detalhe = r.json()["detail"]
        assert "fora do catálogo oficial" in detalhe
        assert "1 leitura" in detalhe and "coleta" in detalhe

    db.expire_all()
    assert (db.get(Livro, livro.id).titulo, db.get(Livro, livro.id).nivel_codigo) == (
        TITULO_PLATAFORMA, "C")
    assert db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "livro.atualizado")).first() is None

    # A coleta seguinte continua reconhecendo o livro: releitura, nada duplicado.
    _coleta(cliente, escola.id, ana, TITULO_PLATAFORMA, "C")
    assert _leituras(db, ana.id) == [livro.id]
    assert db.execute(select(Livro.id).where(Livro.escola_id == escola.id)).scalars().all() == [
        livro.id]


def test_corrigir_acento_e_maiuscula_continua_livre(cliente, cliente_global, db,
                                                    escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    livro = _livro(db, escola.id, TITULO_PLATAFORMA, "C")
    _leitura(db, escola.id, ana.id, livro)

    r = cliente_global.patch(f"{API}/escolas/{escola.id}/livros/{livro.id}",
                             json={"titulo": "Diário  de bordo fictício"})
    assert r.status_code == 200, r.text
    _coleta(cliente, escola.id, ana, TITULO_PLATAFORMA, "C")
    assert _leituras(db, ana.id) == [livro.id]


def test_renomear_livro_sem_leituras_continua_livre(cliente_global, db, escola_completa):
    escola = escola_completa["escola"]
    livro = _livro(db, escola.id, TITULO_PLATAFORMA, "C")
    db.commit()
    r = cliente_global.patch(f"{API}/escolas/{escola.id}/livros/{livro.id}",
                             json={"titulo": "Diário de Bordo Fictício (2ª edição)"})
    assert r.status_code == 200, r.text


def test_renomear_livro_do_catalogo_continua_livre(cliente, cliente_global, db,
                                                   escola_completa):
    """No catálogo oficial a coleta acha o livro pelo id: o título da escola não
    importa para o reconhecimento."""
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    meta = next(itens[0] for itens in dificuldade_livro.catalogo().por_titulo.values()
                if len(itens) == 1)
    livro = _livro(db, escola.id, meta.titulo, meta.nivel, elefante_id=meta.id)
    _leitura(db, escola.id, ana.id, livro)

    r = cliente_global.patch(f"{API}/escolas/{escola.id}/livros/{livro.id}",
                             json={"titulo": f"{meta.titulo} (edição da escola)"})
    assert r.status_code == 200, r.text
    _coleta(cliente, escola.id, ana, meta.titulo, meta.nivel)
    assert _leituras(db, ana.id) == [livro.id]
