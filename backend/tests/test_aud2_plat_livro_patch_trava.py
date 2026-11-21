"""PATCH /livros serializa a edição e o recálculo com a importação da escola.

O congelamento de níveis do script (``vincular_livros_catalogo --congelar-niveis``) e
a coleta seguram a trava de importação da escola (4711) enquanto gravam leituras com o
nível do livro. A correção de nível do Admin Global precisa entrar na MESMA fila: sem
ela, o PATCH corrigia o livro no meio da gravação do script e respondia sobre leituras
que o script congelava no nível velho ao comitar (a cena real, com duas sessões, está
em ``test_aud2_plat_congelar_patch_espera_pg.py``).

No SQLite a trava não emite SQL, então aqui ela é observada por um espião: o PATCH a
pede antes de ler o livro e mantém a transação até o recálculo. O recálculo usa
a ordem 4711 → 4713 e deixa o commit a cargo de quem aplica a edição. Dados fictícios.
"""
from sqlalchemy.orm import Session

from app.core import database as core_db
from app.models import Leitura, Livro
from app.routers import plataformas
from app.services import scoring

API = "/api/v1"


def _vigia(monkeypatch) -> dict:
    estado = {"travas": [], "trava_ativa": False, "recalculos": [],
              "leu_livro_com_trava": None}
    trava_real = core_db.bloquear_escola_para_importacao

    def _travar(sessao, eid):
        estado["travas"].append(eid)
        estado["trava_ativa"] = True
        return trava_real(sessao, eid)

    monkeypatch.setattr(plataformas, "bloquear_escola_para_importacao", _travar)

    get_real = Session.get

    def _get(self, entidade, ident, *a, **k):
        if entidade is Livro and estado["leu_livro_com_trava"] is None:
            estado["leu_livro_com_trava"] = estado["trava_ativa"]
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
        estado["recalculos"].append((estado["trava_ativa"], k.get("commit", True)))
        return recalcular_real(sessao, eid, *a, **k)

    monkeypatch.setattr(scoring, "recalcular_escola", _recalcular)
    return estado


def _livro_com_leituras(db, escola_completa) -> tuple[int, int]:
    escola = escola_completa["escola"]
    livro = Livro(escola_id=escola.id, titulo="Livro Fictício da Trava", nivel_codigo="K")
    db.add(livro)
    db.flush()
    ana, joao = escola_completa["alunos"][:2]
    db.add_all([Leitura(escola_id=escola.id, aluno_id=ana.id, livro_id=livro.id,
                        nivel_codigo="K"),
                Leitura(escola_id=escola.id, aluno_id=joao.id, livro_id=livro.id)])
    db.commit()
    return escola.id, livro.id


def test_correcao_de_nivel_pede_a_trava_da_escola_antes_de_ler_o_livro(
        cliente_global, db, escola_completa, monkeypatch):
    escola_id, livro_id = _livro_com_leituras(db, escola_completa)
    estado = _vigia(monkeypatch)

    r = cliente_global.patch(f"{API}/escolas/{escola_id}/livros/{livro_id}",
                             json={"nivel_codigo": "M", "motivo": "nível conferido"})
    assert r.status_code == 200, r.text
    assert estado["travas"] == [escola_id], "o PATCH não entrou na fila da escola"
    assert estado["leu_livro_com_trava"] is True, "o livro foi lido antes da trava"


def test_aplicar_ao_historico_recalcula_na_mesma_transacao(
        cliente_global, db, escola_completa, monkeypatch):
    """Os dois caminhos que recalculam: só retroagir, e corrigir + retroagir."""
    escola_id, livro_id = _livro_com_leituras(db, escola_completa)
    estado = _vigia(monkeypatch)
    url = f"{API}/escolas/{escola_id}/livros/{livro_id}"

    so_retroagir = cliente_global.patch(url, json={"aplicar_ao_historico": True,
                                                   "motivo": "retroagir o nível atual"})
    assert so_retroagir.status_code == 200, so_retroagir.text
    corrigir_e_retroagir = cliente_global.patch(
        url, json={"nivel_codigo": "M", "aplicar_ao_historico": True,
                   "motivo": "nível errado desde a importação"})
    assert corrigir_e_retroagir.status_code == 200, corrigir_e_retroagir.text

    # Só retroagir usa uma trava. Corrigir e retroagir usa uma por transação.
    assert estado["travas"] == [escola_id, escola_id, escola_id]
    assert estado["recalculos"] == [(True, False), (True, False)]
