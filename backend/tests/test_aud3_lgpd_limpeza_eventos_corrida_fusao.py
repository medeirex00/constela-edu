"""A limpeza do passivo de eventos (``scripts/deduplicar_eventos_por_conteudo``) não
apaga a única cópia de uma leitura quando uma fusão acontece no meio dela (REG_DADOS-1).

O DEFEITO. ``eventos.deduplicar_eventos_por_conteudo(aplicar=True)`` lia os eventos,
montava o plano ficha a ficha e só no fim apagava por id, sem a trava da escola (a da
fusão, da importação e da coleta) e sem conferir se o plano ainda valia. Uma fusão
confirmada entre a leitura e o DELETE movia a cópia que o plano mandava apagar para a
ficha que fica (e apagava as outras cópias): o DELETE do plano velho levava a ÚNICA
cópia que restou — a leitura sumia da linha do tempo, do espelho e dos "Registros de
leitura" do Relatório por Período.

A CORREÇÃO. Escola por escola, com a trava da escola ANTES de ler (no PostgreSQL a
fusão espera; ver o ``_pg``) e o script commitando cada escola; e o DELETE só apaga o
que ainda está como no plano (o evento na ficha planejada e a cópia que fica, ainda lá)
— no SQLite, onde a trava não faz nada, é essa condição que protege. O log
``aluno.eventos_duplicados_removidos`` registra só o que saiu de fato.

Dados fictícios.
"""
from datetime import datetime

from sqlalchemy import event, select

from app.models import Aluno, Escola, EventoAluno, LogAuditoria
from app.services import eventos as svc_eventos
from app.services.eventos import chave_evento, deduplicar_eventos_por_conteudo

API = "/api/v1"
TITULO = "Livro Inventado da Corrida"
T = datetime(2026, 3, 10, 10, 0)
Z = 990001                                    # ficha absorvida há tempos (apagada)


def _evento(escola_id, aluno_id, origem_id):
    return EventoAluno(escola_id=escola_id, aluno_id=aluno_id, plataforma="elefante",
                       tipo_evento="leitura", ocorrido_em=T,
                       chave_natural=chave_evento("elefante", "leitura", origem_id, TITULO, T),
                       conteudo_titulo=TITULO, dados={})


def _cenario(db, escola_completa):
    """M e R ativas; R tem o passivo de uma fusão ANTIGA (absorveu Z): a mesma linha
    duas vezes (r1 nativa de R, r2 com a chave de Z). M tem a mesma linha nativa."""
    esc = escola_completa["escola"]
    m, r = escola_completa["alunos"][0], escola_completa["alunos"][1]
    db.add(LogAuditoria(escola_id=esc.id, acao="aluno.fundido", entidade="aluno",
                        entidade_id=r.id,
                        detalhes={"mantido": {"id": r.id}, "removido": {"id": Z}}))
    m1, r1, r2 = _evento(esc.id, m.id, m.id), _evento(esc.id, r.id, r.id), \
        _evento(esc.id, r.id, Z)
    db.add_all([m1, r1, r2])
    db.commit()
    return esc.id, m.id, r.id, r1.id, r2.id


def _fundir(cliente, escola_id, manter_id, remover_id):
    r = cliente.post(f"{API}/escolas/{escola_id}/alunos/fundir", json={
        "manter_id": manter_id, "remover_id": remover_id, "confirmacao": "FUNDIR"})
    assert r.status_code == 200, r.text
    return r.json()


def _copias(db, aluno_id):
    db.expire_all()
    return list(db.execute(select(EventoAluno.id).where(
        EventoAluno.aluno_id == aluno_id, EventoAluno.conteudo_titulo == TITULO)).scalars())


def _removidos(db):
    return db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "aluno.eventos_duplicados_removidos")).scalars().all()


def test_controle_limpeza_sozinha_tira_a_copia_nativa_de_r(db, escola_completa):
    escola_id, _m, r_id, r1, r2 = _cenario(db, escola_completa)
    assert deduplicar_eventos_por_conteudo(db, escola_id=escola_id, aplicar=True) == {
        "alunos": 1, "eventos_duplicados": 1}
    db.commit()
    assert _copias(db, r_id) == [r2]
    [log] = _removidos(db)
    assert [e["evento_id"] for e in log.detalhes["eventos"]] == [r1]


def test_fusao_no_meio_da_limpeza_nao_apaga_a_unica_copia(cliente, db, escola_completa,
                                                         monkeypatch):
    escola_id, m_id, r_id, r1, _r2 = _cenario(db, escola_completa)
    delete_real = svc_eventos.delete
    feito = {}

    def _delete_com_fusao_no_meio(*args, **kwargs):
        # O plano já foi lido; a gestão funde M ← R agora (outra requisição, commit).
        if not feito:
            feito["fusao"] = _fundir(cliente, escola_id, m_id, r_id)
            feito["m_depois_da_fusao"] = _copias(db, m_id)
        return delete_real(*args, **kwargs)

    monkeypatch.setattr(svc_eventos, "delete", _delete_com_fusao_no_meio)
    resultado = deduplicar_eventos_por_conteudo(db, escola_id=escola_id, aplicar=True)
    db.commit()
    assert feito["m_depois_da_fusao"] == [r1]          # a fusão deixou só a r1, em M
    assert _copias(db, m_id) == [r1], "a leitura sumiu da linha do tempo de M"
    # Nada saiu, e o log não diz que saiu (nem em nome da ficha R, que não existe mais).
    assert resultado == {"alunos": 0, "eventos_duplicados": 0}
    assert _removidos(db) == []


def test_copia_que_ficaria_sumiu_no_meio_a_outra_nao_sai(db, escola_completa, monkeypatch):
    """O plano manda apagar r1 porque r2 fica. Se r2 sumiu entre a leitura e o DELETE
    (outra operação), r1 é a única cópia: não sai."""
    escola_id, _m, r_id, r1, r2 = _cenario(db, escola_completa)
    delete_real = svc_eventos.delete
    feito = {}

    def _delete_depois_de_sumir_a_que_fica(*args, **kwargs):
        if not feito:
            feito["sumiu"] = True
            db.execute(delete_real(EventoAluno).where(EventoAluno.id == r2))
        return delete_real(*args, **kwargs)

    monkeypatch.setattr(svc_eventos, "delete", _delete_depois_de_sumir_a_que_fica)
    resultado = deduplicar_eventos_por_conteudo(db, escola_id=escola_id, aplicar=True)
    db.commit()
    assert _copias(db, r_id) == [r1]
    assert resultado == {"alunos": 0, "eventos_duplicados": 0}
    assert _removidos(db) == []


def _segunda_escola(db):
    esc = Escola(nome="ESCOLA TESTE DOIS", ano_letivo_ativo=2026)
    db.add(esc)
    db.flush()
    a = Aluno(escola_id=esc.id, nome="Criança Inventada Dois")
    db.add(a)
    db.flush()
    db.add(LogAuditoria(escola_id=esc.id, acao="aluno.fundido", entidade="aluno",
                        entidade_id=a.id,
                        detalhes={"mantido": {"id": a.id}, "removido": {"id": Z + 1}}))
    db.add_all([_evento(esc.id, a.id, a.id), _evento(esc.id, a.id, Z + 1)])
    db.commit()
    return esc.id


def test_aplicar_trava_cada_escola_antes_de_ler_e_o_script_commita_por_escola(
        db, escola_completa, monkeypatch, capsys):
    from scripts import deduplicar_eventos_por_conteudo as script

    escola_um = _cenario(db, escola_completa)[0]
    escola_dois = _segunda_escola(db)
    ordem: list[tuple] = []

    def _trava(sessao, escola_id):
        ordem.append(("trava", escola_id))

    def _consulta(conn, cursor, sql, params, context, executemany):
        texto = " ".join(sql.split()).upper()
        if texto.startswith("SELECT") and "FROM EVENTOS_ALUNO" in texto:
            ordem.append(("le_eventos",))

    class _Sessao:
        def __init__(self, sessao):
            self._s = sessao

        def __getattr__(self, nome):
            return getattr(self._s, nome)

        def commit(self):
            ordem.append(("commit",))
            self._s.commit()

        def close(self):
            pass

    monkeypatch.setattr(svc_eventos, "bloquear_escola_para_importacao", _trava)
    monkeypatch.setattr(script, "SessionLocal", lambda: _Sessao(db))
    motor = db.get_bind()
    event.listen(motor, "before_cursor_execute", _consulta)
    try:
        assert script.main(["--aplicar"]) == 0
    finally:
        event.remove(motor, "before_cursor_execute", _consulta)

    # Cada escola: a trava antes de ler os eventos dela, e o commit dela antes da
    # próxima (a trava do PostgreSQL só cai no commit).
    assert [m for m in ordem if m[0] == "trava"] == [("trava", escola_um),
                                                    ("trava", escola_dois)]
    trava_um = ordem.index(("trava", escola_um))
    assert ("le_eventos",) not in ordem[:trava_um]
    commit_um = ordem.index(("commit",), ordem.index(("le_eventos",), trava_um))
    trava_dois = ordem.index(("trava", escola_dois), commit_um)
    ordem.index(("commit",), ordem.index(("le_eventos",), trava_dois))
    assert "2 evento(s) repetido(s) apagado(s) em 2 ficha(s)" in capsys.readouterr().out


def test_simulacao_nao_trava_nem_apaga(db, escola_completa, monkeypatch):
    escola_id, _m, r_id, r1, r2 = _cenario(db, escola_completa)
    travas = []
    monkeypatch.setattr(svc_eventos, "bloquear_escola_para_importacao",
                        lambda sessao, escola: travas.append(escola))
    assert deduplicar_eventos_por_conteudo(db, aplicar=False) == {
        "alunos": 1, "eventos_duplicados": 1}
    db.rollback()
    assert travas == [] and sorted(_copias(db, r_id)) == sorted([r1, r2])
