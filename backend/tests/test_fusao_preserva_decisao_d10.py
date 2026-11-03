"""Fundir duplicatas NÃO desfaz a confirmação do D10 — 2ª revisão de integração do
e97 (identidade-sync, prova 2 invertida).

A memória da decisão humana é ``RevisaoIdentidade.aluno_escolhido_id``
(``carregar_contexto`` → ``ctx.resolvidas``; o passo 0d de ``decidir`` só associa
uma conta efetiva em outra escola com ``_confirmado_por_humano``). ``fundir_par``
movia a identidade externa do ``remover`` para o ``manter`` mas não a memória: o
delete do ``remover`` zerava a coluna (FK SET NULL), e a coleta seguinte mandava a
conta de volta para a revisão ``identidade_de_outra_escola`` — com 403 para a
gestão no ``/resolver``. Agora a memória segue a criança (fusão de 1 par e em
lote, que usam o mesmo núcleo).

Caso realista: o Admin Global confirma a conta de uma criança que veio de outra
escola numa ficha criada pela revisão (sem RA); depois a Lista Piloto traz a ficha
oficial e a gestão funde a duplicata nela.

Dados 100% fictícios (nomes de escola e de criança inventados); sem rede.
"""
from sqlalchemy import select

from app.models import Aluno, IdentidadeExterna, Matricula, RevisaoIdentidade
from app.models.nota import LogAuditoria
from app.models.plataformas import SnapshotMatific

API = "/api/v1"
U = "u-ficticia-fusao-d10"
K = "3 ANO A (300396804)"


def _nova_escola(db):
    from tests.test_sync_escola_cruzada import _nova_escola as nova

    return nova(db, nome="ESCOLA FICTICIA B DA FUSAO", com_alunos=("Crianca Ficticia B Fusao",))


def _importar(cliente, eid, nome, estrelas):
    linha = {"nome": nome, "dados": {"matific_uuid": U, "estrelas": estrelas,
                                     "atividades": 10, "pontuacao_media": 80,
                                     "turma_relatorio": K}}
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/confirmar", json={
        "plataforma": "matific", "formato": "resumo", "tipo": "pdf",
        "recalcular": False, "linhas": [linha]})
    assert r.status_code == 200, r.text
    return r.json()


def _estrelas(db, aluno_id):
    db.expire_all()
    return [s.estrelas for s in db.execute(select(SnapshotMatific).where(
        SnapshotMatific.aluno_id == aluno_id)).scalars()]


def _pendentes(db, eid):
    db.expire_all()
    return db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == eid,
        RevisaoIdentidade.status == "pendente")).scalars().all()


def _cena(db, escola_completa, cliente, cliente_global, nome_oficial):
    """B tem a conta U efetiva; a coleta de A traz U (revisão aqui); o Admin Global
    resolve para a ficha R; entra a ficha oficial M (Lista Piloto, RA) na mesma
    turma. Devolve (e1, r_id, m_id, rev_id, nome_r)."""
    e1 = escola_completa["escola"].id
    turma = escola_completa["turma"]
    r_ficha = escola_completa["alunos"][0]
    nome_r = r_ficha.nome
    escola_b, _t, (y,) = _nova_escola(db)
    db.add(IdentidadeExterna(escola_id=escola_b.id, aluno_id=y.id,
                             plataforma="matific", id_externo=U))
    db.commit()
    assert _importar(cliente, e1, nome_r, 30)["ids_de_outra_escola"] == [U]
    [rev] = _pendentes(db, e1)
    r = cliente_global.post(f"{API}/escolas/{e1}/importacoes/revisoes/{rev.id}/resolver",
                            json={"aluno_id": r_ficha.id})
    assert r.status_code == 200, r.text
    m = Aluno(escola_id=e1, nome=nome_oficial, da_lista_piloto=True,
              ficha={"ra": "000.111.222-3"})
    db.add(m)
    db.flush()
    db.add(Matricula(escola_id=e1, aluno_id=m.id, turma_id=turma.id, ano_letivo=2026))
    db.commit()
    return e1, r_ficha.id, m.id, rev.id, nome_r


def _confere_coleta_seguinte(db, cliente, e1, m_id, rev_id, nome):
    db.expire_all()
    assert db.get(RevisaoIdentidade, rev_id).aluno_escolhido_id == m_id
    corpo = _importar(cliente, e1, nome, 50)
    assert corpo["ids_de_outra_escola"] == []
    assert 50 in _estrelas(db, m_id)
    assert _pendentes(db, e1) == []


def test_fusao_de_um_par_preserva_a_confirmacao_do_d10(db, escola_completa, cliente,
                                                       cliente_global):
    e1, r_id, m_id, rev_id, nome_r = _cena(db, escola_completa, cliente, cliente_global,
                                           nome_oficial="Ana Beatriz Souza")
    r = cliente.post(f"{API}/escolas/{e1}/alunos/fundir",
                     json={"manter_id": m_id, "remover_id": r_id, "confirmacao": "FUNDIR"})
    assert r.status_code == 200, r.text
    _confere_coleta_seguinte(db, cliente, e1, m_id, rev_id, nome_r)
    db.expire_all()
    [aud] = [a for a in db.execute(select(LogAuditoria)).scalars()
             if a.acao == "aluno.fundido"]
    assert aud.detalhes["decisoes_de_identidade_movidas"] == 1


def test_fusao_em_lote_preserva_a_confirmacao_do_d10(db, escola_completa, cliente,
                                                     cliente_global):
    """Fundir duplicatas em lote usa o mesmo núcleo: a ficha da revisão (nome mais
    curto) cai na ficha oficial da Lista Piloto, e a memória vai junto."""
    e1, r_id, m_id, rev_id, nome_r = _cena(db, escola_completa, cliente, cliente_global,
                                           nome_oficial="Ana Beatriz Souza Lima")
    cands = cliente.get(f"{API}/escolas/{e1}/alunos/duplicados").json()["candidatos"]
    assert any((c["loser_id"], c["manter_id"]) == (r_id, m_id) for c in cands), cands
    r = cliente.post(f"{API}/escolas/{e1}/alunos/duplicados/corrigir",
                     json={"loser_ids": [r_id], "confirmacao": "FUNDIR"})
    assert r.status_code == 200, r.text
    assert r.json()["fundidos"] == 1, r.json()
    _confere_coleta_seguinte(db, cliente, e1, m_id, rev_id, nome_r)
