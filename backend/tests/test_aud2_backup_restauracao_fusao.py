"""G_LGPD-2 — restaurar o backup não traz de volta a criança excluída de vez pela
DUPLICATA que tinha sido fundida nela.

``backup._excluidos_depois_do_backup`` montava as fichas que não voltam a partir de
``aluno.excluido_permanente`` seguindo só a linhagem das RESTAURAÇÕES. A FUSÃO também
liga duas fichas da mesma criança (``aluno.fundido``: ``removido.id`` → ``mantido.id``),
e essa ligação ficava de fora: o arquivo de antes da fusão traz as duas fichas, a
oficial excluída ficava de fora e a duplicata absorvida voltava inteira — nome,
matrícula, retratos e a conta da plataforma —, com a resposta dizendo que a criança
"não foi restaurada". Agora a fusão entra na mesma linhagem, em cadeia e nos dois
sentidos, e o aviso conta CRIANÇAS (as duas fichas da mesma criança contam uma).

Os ids de uma escola-tampão (``_segurar_o_maior_id``) impedem o SQLite de reaproveitar
os ids que a fusão, a exclusão e a restauração apagam (o PostgreSQL nunca reaproveita:
``test_aud2_backup_restauracao_fusao_pg.py``).

Dados 100% fictícios (escolas e crianças inventadas); sem rede.
"""
import json

from sqlalchemy import select

from app.models import (
    Aluno,
    Escola,
    IdentidadeExterna,
    Importacao,
    LogAuditoria,
    Matricula,
    SnapshotMatific,
)
from app.services import backup as svc_backup

API = "/api/v1"
UUID = "uuid-ficticio-aud2-duplicata"
NOME_OFICIAL = "Ana Beatriz Souza Lima"
AVISO_1 = ("1 criança(s) excluída(s) permanentemente (nesta ou em outra escola) depois "
           "deste backup não foram restauradas (direito de eliminação, LGPD art. 18).")


def _segurar_o_maior_id(db) -> None:
    """Ficha de outra escola com o maior id: no SQLite a fusão, a exclusão e a
    restauração deixam de reaproveitar os ids que apagam."""
    tampao = Escola(nome="ESCOLA FICTICIA AUD2 TAMPAO FUSAO", ano_letivo_ativo=2026)
    db.add(tampao)
    db.flush()
    db.add(Aluno(escola_id=tampao.id, nome="Crianca Ficticia Tampao Fusao"))
    db.commit()


def _cena(db, escola_completa) -> tuple[int, int, int, str]:
    """A duplicata da coleta (com retrato e a conta da plataforma) e a ficha oficial da
    mesma criança, na mesma turma. Devolve (escola, duplicata, oficial, nome da
    duplicata)."""
    eid = escola_completa["escola"].id
    turma = escola_completa["turma"]
    duplicata = escola_completa["alunos"][0]
    oficial = Aluno(escola_id=eid, nome=NOME_OFICIAL, da_lista_piloto=True)
    db.add(oficial)
    db.flush()
    db.add(Matricula(escola_id=eid, aluno_id=oficial.id, turma_id=turma.id, ano_letivo=2026))
    imp = Importacao(escola_id=eid, plataforma="matific", tipo="seed")
    db.add(imp)
    db.flush()
    db.add(SnapshotMatific(escola_id=eid, aluno_id=duplicata.id, importacao_id=imp.id,
                           atividades=12, estrelas=12, pontuacao_media=70))
    db.add(IdentidadeExterna(escola_id=eid, aluno_id=duplicata.id, plataforma="matific",
                             id_externo=UUID))
    db.commit()
    _segurar_o_maior_id(db)
    return eid, duplicata.id, oficial.id, duplicata.nome


def _arquivo(db, eid) -> bytes:
    db.expire_all()
    return json.dumps(svc_backup.exportar(db, eid), default=str).encode("utf-8")


def _fundir(cliente, eid, manter_id, remover_id):
    r = cliente.post(f"{API}/escolas/{eid}/alunos/fundir",
                     json={"manter_id": manter_id, "remover_id": remover_id,
                           "confirmacao": "FUNDIR"})
    assert r.status_code == 200, r.text


def _excluir(cliente_global, eid, aluno_id):
    r = cliente_global.post(f"{API}/escolas/{eid}/alunos/excluir-permanente",
                            json={"aluno_ids": [aluno_id], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text


def _restaurar(cliente_global, eid, arquivo: bytes) -> dict:
    r = cliente_global.post(f"{API}/escolas/{eid}/restaurar",
                            files={"arquivo": ("b.json", arquivo, "application/json")})
    assert r.status_code == 200, r.text
    return r.json()


def _da_crianca(db, eid, nome_duplicata) -> dict:
    """Tudo o que a criança excluída deixou na escola: fichas, retratos e a conta."""
    db.expire_all()
    fichas = db.execute(select(Aluno.id, Aluno.nome).where(
        Aluno.escola_id == eid, Aluno.nome.in_([nome_duplicata, NOME_OFICIAL]))).all()
    ids = [i for i, _ in fichas] or [-1]
    retratos = db.execute(select(SnapshotMatific.aluno_id).where(
        SnapshotMatific.aluno_id.in_(ids))).scalars().all()
    contas = db.execute(select(IdentidadeExterna.aluno_id).where(
        IdentidadeExterna.escola_id == eid, IdentidadeExterna.id_externo == UUID)).all()
    return {"fichas": fichas, "retratos": retratos, "contas": contas}


def _id_atual(db, eid, nome) -> int:
    db.expire_all()
    return db.execute(select(Aluno.id).where(Aluno.escola_id == eid,
                                             Aluno.nome == nome)).scalar_one()


def test_fusao_depois_do_backup_a_duplicata_nao_volta(db, escola_completa, cliente,
                                                      cliente_global):
    eid, dup_id, ofi_id, nome_dup = _cena(db, escola_completa)
    outros = {a.nome for a in escola_completa["alunos"][1:]}
    arquivo = _arquivo(db, eid)                      # backup de rotina: as duas fichas
    _fundir(cliente, eid, ofi_id, dup_id)            # a gestão funde a duplicata
    _excluir(cliente_global, eid, ofi_id)            # a família pede esquecimento
    corpo = _restaurar(cliente_global, eid, arquivo)
    assert _da_crianca(db, eid, nome_dup) == {"fichas": [], "retratos": [], "contas": []}, (
        "a restauração trouxe de volta a criança excluída de vez pela duplicata fundida")
    assert corpo["avisos"] == [AVISO_1]              # uma criança, não duas fichas
    db.expire_all()
    assert outros <= set(db.execute(select(Aluno.nome).where(
        Aluno.escola_id == eid)).scalars())


def test_fusao_antes_do_backup_a_crianca_nao_volta(db, escola_completa, cliente,
                                                   cliente_global):
    eid, dup_id, ofi_id, nome_dup = _cena(db, escola_completa)
    _fundir(cliente, eid, ofi_id, dup_id)
    arquivo = _arquivo(db, eid)                      # só a ficha oficial no arquivo
    _excluir(cliente_global, eid, ofi_id)
    corpo = _restaurar(cliente_global, eid, arquivo)
    assert _da_crianca(db, eid, nome_dup) == {"fichas": [], "retratos": [], "contas": []}
    assert corpo["avisos"] == [AVISO_1]


def test_excluir_a_duplicata_que_voltou_tambem_segura_a_oficial(db, escola_completa, cliente,
                                                                cliente_global):
    """O outro sentido da fusão: o arquivo de antes dela, restaurado, trouxe de volta as
    duas fichas; a gestão exclui de vez a duplicata. A ficha oficial é a mesma
    criança: com o mesmo arquivo, nenhuma das duas volta."""
    eid, dup_id, ofi_id, nome_dup = _cena(db, escola_completa)
    arquivo = _arquivo(db, eid)
    _fundir(cliente, eid, ofi_id, dup_id)
    _restaurar(cliente_global, eid, arquivo)         # as duas fichas voltam (ids novos)
    _excluir(cliente_global, eid, _id_atual(db, eid, nome_dup))
    corpo = _restaurar(cliente_global, eid, arquivo)
    assert _da_crianca(db, eid, nome_dup) == {"fichas": [], "retratos": [], "contas": []}
    assert corpo["avisos"] == [AVISO_1]


def test_entre_escolas_a_copia_da_duplicata_nao_volta(db, escola_completa, cliente,
                                                      cliente_global):
    """O arquivo de A (antes da fusão) restaurado em B leva as duas fichas para B. A
    funde e exclui de vez a oficial; o backup de B, gerado antes disso, não traz de
    volta nenhuma das duas cópias."""
    eid, dup_id, ofi_id, nome_dup = _cena(db, escola_completa)
    destino = Escola(nome="ESCOLA FICTICIA AUD2 DESTINO FUSAO", ano_letivo_ativo=2026)
    db.add(destino)
    db.commit()
    destino_id = destino.id
    _restaurar(cliente_global, destino_id, _arquivo(db, eid))
    arquivo_b = _arquivo(db, destino_id)
    assert len(_da_crianca(db, destino_id, nome_dup)["fichas"]) == 2
    _fundir(cliente, eid, ofi_id, dup_id)
    _excluir(cliente_global, eid, ofi_id)
    corpo = _restaurar(cliente_global, destino_id, arquivo_b)
    assert _da_crianca(db, destino_id, nome_dup)["fichas"] == [], (
        "a cópia da duplicata fundida voltou na outra escola")
    assert corpo["avisos"] == [AVISO_1]


def test_id_absorvido_que_hoje_e_de_outra_crianca_nao_entra():
    """Id absorvido por fusão que hoje é de uma ficha VIVA é reaproveitamento (SQLite de
    desenvolvimento): é outra criança, e a ligação da fusão não a alcança — a mesma
    regra de ``exclusao_aluno.fichas_absorvidas``."""
    ligacoes = svc_backup._ligar_fusoes({}, [(10, 20), (10, 30)], vivas={30})
    assert ligacoes == {10: {20}, 20: {10}}


def test_fusao_registrada_sem_ids_legiveis_nao_liga_nada(db):
    db.add_all([
        LogAuditoria(acao="aluno.fundido", entidade="aluno", entidade_id=5,
                     detalhes={"mantido": "[removido]", "removido": {"id": "x"}}),
        LogAuditoria(acao="aluno.fundido", entidade="aluno", entidade_id=None,
                     detalhes=["nada"]),
        LogAuditoria(acao="aluno.fundido", entidade="aluno", entidade_id=7,
                     detalhes={"mantido": {"id": 7}, "removido": {"id": 8}}),
    ])
    db.commit()
    assert svc_backup._fusoes(db) == [(7, 8)]
