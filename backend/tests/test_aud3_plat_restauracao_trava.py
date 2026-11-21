"""Restauração histórica de leituras na fila da escola (S_G_AJUSTE-4), no SQLite.

``POST /leituras/restaurar-historico`` não pedia a trava da escola (4711). A fusão
pede: ela descarta a leitura repetida da ficha absorvida e apaga a ficha. Sem a
trava, a restauração aplicada no meio de uma fusão caía com ``StaleDataError`` (500)
ou respondia "restaurada" e a fusão apagava a leitura registrando a data VELHA no
log (a cena com duas sessões está em ``test_aud3_plat_restauracao_fusao_pg.py``).

No SQLite a trava não emite SQL, então aqui ela é observada por um espião: a
restauração APLICADA a pede antes de ler a ficha e a solta (commit) antes do
recálculo — nunca pegar 4713 segurando 4711 (``bloquear_escola_para_recalculo``).
E a ficha que não existe mais (fundida em outra ou excluída) é dita assim, não
"não é desta escola". Dados fictícios.
"""
from datetime import datetime

from sqlalchemy.orm import Session

from app.core import database as core_db
from app.models import Aluno, EventoAluno, Leitura, Livro
from app.routers import plataformas
from app.services import scoring
from app.services.eventos import chave_evento

API = "/api/v1"
ORIGEM = 987654                      # ficha absorvida numa fusão anterior (só no hash)
DATA_VELHA = datetime(2026, 9, 20, 10, 0)
DATA_REAL = datetime(2026, 8, 6, 0, 1)
TITULO = "Livro Inventado da Restauracao"
MOTIVO = "fusao anterior manteve a data velha; o evento prova a original"


def _cena(db, escola_completa) -> dict:
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    livro = Livro(escola_id=escola.id, titulo=TITULO, nivel_codigo="AA")
    db.add(livro)
    db.flush()
    db.add(Leitura(escola_id=escola.id, aluno_id=aluno.id, livro_id=livro.id,
                   data=DATA_VELHA, tempo_leitura_min=1, nivel_codigo="AA"))
    evento = EventoAluno(
        escola_id=escola.id, aluno_id=aluno.id, plataforma="elefante",
        tipo_evento="leitura", ocorrido_em=DATA_REAL, conteudo_titulo=TITULO,
        livro_id=livro.id, tempo_segundos=120, nivel_codigo="AA",
        chave_natural=chave_evento("elefante", "leitura", ORIGEM, TITULO, DATA_REAL))
    db.add(evento)
    db.commit()
    return {"escola": escola.id, "aluno": aluno.id, "livro": livro.id,
            "evento": evento.id, "chave": evento.chave_natural}


def _corpo(c: dict, aluno_id: int | None = None) -> dict:
    return {"itens": [{"aluno_id": aluno_id or c["aluno"], "aluno_origem_id": ORIGEM,
                       "livro_id": c["livro"], "data_original": DATA_REAL.isoformat(),
                       "tempo_original": 2, "evidencia_evento_id": c["evento"],
                       "evidencia_chave_natural": c["chave"], "motivo": MOTIVO}],
            "dry_run": False, "confirmacao": "RESTAURAR HISTORICO"}


def _vigia(monkeypatch) -> dict:
    estado = {"travas": [], "trava_ativa": False, "violacoes": [], "recalculos": 0,
              "leu_ficha_com_trava": None}
    trava_real = core_db.bloquear_escola_para_importacao

    def _travar(sessao, eid):
        estado["travas"].append(eid)
        estado["trava_ativa"] = True
        return trava_real(sessao, eid)

    monkeypatch.setattr(plataformas, "bloquear_escola_para_importacao", _travar)

    get_real = Session.get

    def _get(self, entidade, ident, *a, **k):
        if entidade is Aluno and estado["leu_ficha_com_trava"] is None:
            estado["leu_ficha_com_trava"] = estado["trava_ativa"]
        return get_real(self, entidade, ident, *a, **k)

    commit_real, rollback_real = Session.commit, Session.rollback

    def _commit(self):
        r = commit_real(self)
        estado["trava_ativa"] = False          # a trava é da transação: cai no commit
        return r

    def _rollback(self):
        r = rollback_real(self)
        estado["trava_ativa"] = False
        return r

    monkeypatch.setattr(Session, "get", _get)
    monkeypatch.setattr(Session, "commit", _commit)
    monkeypatch.setattr(Session, "rollback", _rollback)

    recalcular_real = scoring.recalcular_escola

    def _recalcular(sessao, eid, *a, **k):
        estado["recalculos"] += 1
        if estado["trava_ativa"]:
            estado["violacoes"].append(eid)
        return recalcular_real(sessao, eid, *a, **k)

    monkeypatch.setattr(scoring, "recalcular_escola", _recalcular)
    return estado


def test_restauracao_aplicada_pede_a_trava_antes_de_ler_e_solta_antes_de_recalcular(
        cliente_global, db, escola_completa, monkeypatch):
    c = _cena(db, escola_completa)
    estado = _vigia(monkeypatch)
    r = cliente_global.post(f"{API}/escolas/{c['escola']}/leituras/restaurar-historico",
                            json=_corpo(c))
    assert r.status_code == 200, r.text
    assert r.json()["leituras_restauradas"] == 1
    assert estado["travas"] == [c["escola"]], "a restauração não entrou na fila da escola"
    assert estado["leu_ficha_com_trava"] is True, "a ficha foi lida antes da trava"
    assert estado["recalculos"] == 1, "o recálculo nem rodou"
    assert estado["violacoes"] == [], (
        "recálculo (4713) pedido ainda segurando a trava da escola (4711)")
    db.expire_all()
    assert db.query(Leitura).filter(Leitura.livro_id == c["livro"]).one().data == DATA_REAL


def test_ficha_que_nao_existe_mais_e_dita_assim(cliente_global, db, escola_completa):
    """Depois de uma fusão, a ficha absorvida não existe: a recusa diz isso (e que nada
    foi alterado), não que a ficha "não é desta escola"."""
    c = _cena(db, escola_completa)
    r = cliente_global.post(f"{API}/escolas/{c['escola']}/leituras/restaurar-historico",
                            json=_corpo(c, aluno_id=99999))
    assert r.status_code == 422, r.text
    detalhe = r.json()["detail"]
    assert "não é desta escola" not in detalhe, detalhe
    assert "não existe" in detalhe and "fundida" in detalhe, detalhe
