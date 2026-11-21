"""A5 (resíduo): duas contas SEM VÍNCULO, no mesmo relatório, para a mesma ficha.

Antes, a primeira linha do arquivo levava a ficha e gravava o retrato (3 ou 139
atividades, conforme a ordem); só a segunda ia para a revisão. Agora as duas vão
para a revisão e a ficha não recebe número nenhum até alguém decidir qual conta
é a da criança — o mesmo invariante de ``test_colisao_identidades`` para contas
já vinculadas. Dados fictícios.
"""
import pytest

from app.models import Aluno
from app.services import identidade_aluno as ida
from app.services import triagem_revisoes as tri
from app.services.importacao import LinhaImportacao, casar_nomes
from tests.sync_integridade_comum import (aluno, aplicar, dono, elefante_resumo, fichas,
                                          matific, pendentes, sem_disco, snap_matific, vincular)

K = "3 ANO A TARDE ANUAL (300396804)"
POUCO = {"nome": "Zefa Quaresma Lima", "nome_abrev": "ZEFA Q", "uuid": "conta-pouco-usada",
         "estrelas": 9, "atividades": 3}
REAL = {"nome": "Zefa Quaresma Lima", "nome_abrev": "ZEFA Q", "uuid": "conta-real",
        "estrelas": 523, "atividades": 139}


def _esc(ec):
    return ec["escola"], ec["turma"], ec["admin"]


@pytest.mark.parametrize("ordem", [[POUCO, REAL], [REAL, POUCO]], ids=["pouco_primeiro",
                                                                      "real_primeiro"])
def test_nenhuma_conta_leva_a_ficha_qualquer_que_seja_a_ordem(db, escola_completa,
                                                              monkeypatch, ordem):
    sem_disco(monkeypatch)
    esc, t, _ = _esc(escola_completa)
    f = aluno(db, esc.id, t, "Zefa Quaresma Lima", da_lista_piloto=True)
    db.commit()
    aplicar(db, esc, matific(K, ordem))
    assert snap_matific(db, f.id) is None, "a ordem do arquivo decidiu o retrato"
    assert dono(db, esc.id, "matific", "conta-pouco-usada") is None
    assert dono(db, esc.id, "matific", "conta-real") is None
    revs = pendentes(db, esc.id)
    assert sorted(r.id_externo for r in revs) == ["conta-pouco-usada", "conta-real"]
    assert {r.motivo for r in revs} == {"outra_identidade_na_plataforma"}
    assert all([c["aluno_id"] for c in r.candidatos] == [f.id] for r in revs)
    # Cada pendência guarda os números da SUA conta.
    por_conta = {r.id_externo: r.linhas[0]["atividades"] for r in revs}
    assert por_conta == {"conta-pouco-usada": 3, "conta-real": 139}


def test_triagem_nao_chama_nenhuma_das_duas_de_segura(db, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    esc, t, _ = _esc(escola_completa)
    aluno(db, esc.id, t, "Zefa Quaresma Lima", da_lista_piloto=True)
    db.commit()
    aplicar(db, esc, matific(K, [POUCO, REAL]))
    revs = pendentes(db, esc.id)
    triagens = tri.triar_revisoes(ida.carregar_contexto(db, esc.id), revs)
    assert {t.classificacao for t in triagens.values()} == {tri.DECISAO_HUMANA}


def test_conta_ja_vinculada_continua_entrando(db, escola_completa, monkeypatch):
    """A trava é do PRIMEIRO vínculo: a conta que já é da ficha segue aplicando, e
    só a conta nova vai para a revisão (como sempre foi)."""
    sem_disco(monkeypatch)
    esc, t, _ = _esc(escola_completa)
    f = aluno(db, esc.id, t, "Zefa Quaresma Lima", da_lista_piloto=True)
    vincular(db, esc.id, f.id, "matific", "conta-real")
    db.commit()
    aplicar(db, esc, matific(K, [POUCO, REAL]))
    assert snap_matific(db, f.id).atividades == 139
    assert [r.id_externo for r in pendentes(db, esc.id)] == ["conta-pouco-usada"]


def test_uma_conta_so_vincula_normalmente(db, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    esc, t, _ = _esc(escola_completa)
    f = aluno(db, esc.id, t, "Zefa Quaresma Lima", da_lista_piloto=True)
    db.commit()
    aplicar(db, esc, matific(K, [REAL]))
    assert dono(db, esc.id, "matific", "conta-real") == f.id
    assert pendentes(db, esc.id) == []


def test_mesma_conta_em_varias_linhas_de_leitura_nao_e_disputa(db, escola_completa, monkeypatch):
    """O histórico de leituras repete a conta (uma linha por livro): é UMA conta."""
    from tests.sync_integridade_comum import elefante_leituras, leituras
    sem_disco(monkeypatch)
    esc, t, _ = _esc(escola_completa)
    f = aluno(db, esc.id, t, "Zefa Quaresma Lima", da_lista_piloto=True)
    db.commit()
    aplicar(db, esc, elefante_leituras(K, [
        {"nome": "Zefa Quaresma Lima", "studentId": 501, "bookTitle": "Livro Ficticio A",
         "lastReadWhen": "2026-08-01T10:00:00"},
        {"nome": "Zefa Quaresma Lima", "studentId": 501, "bookTitle": "Livro Ficticio B",
         "lastReadWhen": "2026-08-02T10:00:00"}]))
    assert dono(db, esc.id, "elefante", "501") == f.id
    assert leituras(db, f.id) == 2


def test_duas_contas_sem_ficha_nao_criam_a_ficha_da_primeira(db, escola_completa, monkeypatch):
    """Sem ficha nenhuma: antes a 1ª linha criava a ficha com os números dela e a
    2ª caía na revisão daquela ficha. Agora nada nasce — as duas vão para a fila."""
    sem_disco(monkeypatch)
    esc, _, _ = _esc(escola_completa)
    antes = fichas(db, esc.id)
    aplicar(db, esc, elefante_resumo(K, [
        {"studentId": 601, "studentName": "Iara Fictoni Modesto", "totalBooksRead": 2},
        {"studentId": 602, "studentName": "Iara Fictoni Modesto", "totalBooksRead": 40}]))
    assert fichas(db, esc.id) == antes
    revs = pendentes(db, esc.id)
    assert sorted(r.id_externo for r in revs) == ["601", "602"]
    assert {r.motivo for r in revs} == {"contas_repetidas_no_relatorio"}


def test_previa_mostra_o_mesmo_que_a_confirmacao(db, escola_completa):
    esc, t, _ = _esc(escola_completa)
    aluno(db, esc.id, t, "Zefa Quaresma Lima", da_lista_piloto=True)
    db.commit()
    linhas = [LinhaImportacao(numero=i, nome=d["nome"],
                              dados={"turma_relatorio": K, "matific_uuid": d["uuid"],
                                     "atividades": d["atividades"], "estrelas": d["estrelas"]})
              for i, d in enumerate([POUCO, REAL], start=1)]
    casar_nomes(db, esc.id, linhas, plataforma="matific")
    assert [l.correspondencia["status"] for l in linhas] == ["revisar", "revisar"]
    assert {l.correspondencia["motivo"] for l in linhas} == {"outra_identidade_na_plataforma"}


def test_escolha_explicita_de_um_humano_continua_valendo(cliente, db, escola_completa):
    """Quem fixa a ficha numa linha decide por ela; a outra conta, sem ficha
    fixada, vai para a revisão em vez de levar a mesma ficha."""
    esc, t, _ = _esc(escola_completa)
    f = aluno(db, esc.id, t, "Zefa Quaresma Lima", da_lista_piloto=True)
    db.commit()
    fid = f.id
    linhas = [{"nome": d["nome"], "aluno_id": fid if d is REAL else None,
               "dados": {"turma_relatorio": K, "matific_uuid": d["uuid"],
                         "atividades": d["atividades"], "estrelas": d["estrelas"]}}
              for d in (POUCO, REAL)]
    r = cliente.post(f"/api/v1/escolas/{esc.id}/importacoes/confirmar",
                     json={"plataforma": "matific", "formato": "resumo", "tipo": "texto",
                           "linhas": linhas})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert dono(db, esc.id, "matific", "conta-real") == fid
    assert dono(db, esc.id, "matific", "conta-pouco-usada") is None
    assert snap_matific(db, fid).atividades == 139
    assert [p.id_externo for p in pendentes(db, esc.id)] == ["conta-pouco-usada"]
    assert db.get(Aluno, fid) is not None
