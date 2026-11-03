"""Linhagem das fichas entre restaurações de escolas DIFERENTES (revisão de integração do
e97, crítico de completude; LGPD art. 18, eliminação).

A restauração recria cada ficha com id NOVO e grava em ``backup.restaurado`` o mapa
{id novo: id do arquivo}; a exclusão permanente vale em qualquer escola. Mas a linhagem
só seguia as restaurações da escola de DESTINO: o arquivo da escola A gerado ANTES de
uma restauração de A leva o id antigo, a exclusão de vez feita em A depois dela grava o
id novo, e só o log de A liga os dois. Restaurado na escola B, o arquivo trazia de volta,
sem aviso, a criança que A excluiu de vez. Agora a linhagem vale em qualquer escola
(``backup._ligacoes_entre_restauracoes``; no PostgreSQL o id do aluno é global e nunca
volta).

SQLite do CI principal; a variante PostgreSQL (ids nunca reaproveitados) está em
``test_backup_linhagem_entre_escolas_pg.py``. No SQLite a tabela vazia recomeça os ids
(a restauração de A devolveria às fichas os MESMOS ids e o defeito não apareceria):
uma ficha de uma terceira escola segura o maior id, como no PostgreSQL.

Mesmo arquivo, a decisão sobre a CÓPIA que o arquivo de uma escola deixa em outra: é a
mesma criança, e a exclusão de vez de uma das fichas vale para a outra na restauração
de um backup gerado ANTES dela. O backup gerado DEPOIS traz a ficha viva da outra
escola: o "depois" é medido no log inteiro (revisão adversarial do e97w-final).

Dados 100% fictícios (fixture escola_completa)."""
import json

from sqlalchemy import select

from app.models import Aluno, Escola
from app.services import backup

API = "/api/v1"
AVISO = "depois deste backup não foram restauradas (direito de eliminação, LGPD art. 18)"


def _baixar(cliente, escola_id):
    r = cliente.get(f"{API}/escolas/{escola_id}/backup")
    assert r.status_code == 200, r.text
    return r.content


def _restaurar(cliente_global, escola_id, conteudo):
    r = cliente_global.post(f"{API}/escolas/{escola_id}/restaurar",
                            files={"arquivo": ("backup.json", conteudo, "application/json")})
    assert r.status_code == 200, r.text
    return r.json()


def _excluir(cliente_global, escola_id, aluno_id):
    r = cliente_global.post(f"{API}/escolas/{escola_id}/alunos/excluir-permanente",
                            json={"aluno_ids": [aluno_id], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text


def _id_atual(db, escola_id, nome):
    db.expire_all()
    return db.execute(select(Aluno.id).where(Aluno.escola_id == escola_id,
                                             Aluno.nome == nome)).scalar_one()


def _nomes(db, escola_id):
    db.expire_all()
    return set(db.execute(select(Aluno.nome).where(Aluno.escola_id == escola_id)).scalars())


def _escola(db, nome):
    escola = Escola(nome=nome, ano_letivo_ativo=2026)
    db.add(escola)
    db.commit()
    return escola


def _segurar_o_maior_id(db):
    """Ficha de uma terceira escola com o maior id: no SQLite a restauração deixa de
    reaproveitar os ids que apagou (no PostgreSQL a sequência nunca volta)."""
    terceira = _escola(db, "ESCOLA FICTICIA TAMPAO DE IDS")
    db.add(Aluno(escola_id=terceira.id, nome="Crianca Ficticia Tampao"))
    db.commit()


def _cena(cliente, cliente_global, db, escola_completa):
    """Arquivo de A; restauração de A com ele (ids novos); exclusão de vez, em A, da
    criança-alvo pelo id NOVO."""
    _segurar_o_maior_id(db)
    escola = escola_completa["escola"]
    alvo = escola_completa["alunos"][2].nome
    outros = {a.nome for a in escola_completa["alunos"][:2]}
    id_original = _id_atual(db, escola.id, alvo)
    antigo = _baixar(cliente, escola.id)                 # arquivo de A (ids originais)
    _restaurar(cliente_global, escola.id, antigo)        # A restaurada: ids novos
    novo_id = _id_atual(db, escola.id, alvo)
    assert novo_id != id_original
    _excluir(cliente_global, escola.id, novo_id)
    return escola, alvo, outros, antigo


def test_controle_mesmo_arquivo_restaurado_em_A_nao_traz_a_excluida(
        cliente, cliente_global, db, escola_completa):
    escola, alvo, outros, antigo = _cena(cliente, cliente_global, db, escola_completa)
    corpo = _restaurar(cliente_global, escola.id, antigo)
    nomes = _nomes(db, escola.id)
    assert alvo not in nomes and outros <= nomes
    (aviso,) = [a for a in corpo["avisos"] if AVISO in a]
    assert aviso.startswith("1 criança(s) excluída(s) permanentemente ")


def test_arquivo_de_A_anterior_a_restauracao_de_A_restaurado_em_B(
        cliente, cliente_global, db, escola_completa):
    escola, alvo, outros, antigo = _cena(cliente, cliente_global, db, escola_completa)
    destino = _escola(db, "ESCOLA DESTINO FICTICIA LINHAGEM")
    corpo = _restaurar(cliente_global, destino.id, antigo)
    nomes = _nomes(db, destino.id)
    assert alvo not in nomes, "a criança excluída de vez em A voltou em B"
    assert outros <= nomes
    (aviso,) = [a for a in corpo["avisos"] if AVISO in a]
    assert aviso.startswith("1 criança(s) excluída(s) permanentemente ")
    assert _nomes(db, escola.id) == outros          # a origem não é tocada


# ---------------------------------------------------------------------------
# A cópia em outra escola (achado 2 do crítico de completude)
# ---------------------------------------------------------------------------
# O arquivo de A restaurado em B cria em B uma ficha da MESMA criança, e a linhagem
# gravada em B liga as duas. Decisão conservadora (LGPD art. 18: o pedido de eliminação
# vale para as cópias): excluída de vez uma delas, a outra não volta numa restauração
# seguinte, nos dois sentidos. A exclusão não apaga a ficha viva da outra escola; só a
# restauração deixa de repô-la. O aviso não pode dizer que a exclusão foi nesta escola.
AVISO_UMA = ("1 criança(s) excluída(s) permanentemente (nesta ou em outra escola) depois "
             "deste backup não foram restauradas (direito de eliminação, LGPD art. 18).")


def _copia_de_A_em_B(cliente, cliente_global, db, escola_completa, nome_destino):
    escola = escola_completa["escola"]
    alvo = escola_completa["alunos"][2].nome
    outros = {a.nome for a in escola_completa["alunos"][:2]}
    destino = _escola(db, nome_destino)
    _restaurar(cliente_global, destino.id, _baixar(cliente, escola.id))   # A -> B
    assert _nomes(db, destino.id) == outros | {alvo}
    return escola, destino, alvo, outros


def test_copia_em_B_da_crianca_excluida_de_vez_em_A_nao_volta_com_o_backup_de_B(
        cliente, cliente_global, db, escola_completa):
    escola, destino, alvo, outros = _copia_de_A_em_B(
        cliente, cliente_global, db, escola_completa, "ESCOLA DESTINO FICTICIA COPIA")
    backup_b = _baixar(cliente_global, destino.id)
    _excluir(cliente_global, escola.id, _id_atual(db, escola.id, alvo))
    assert alvo in _nomes(db, destino.id)           # a exclusão em A não apaga B
    corpo = _restaurar(cliente_global, destino.id, backup_b)
    assert _nomes(db, destino.id) == outros          # a cópia de B não volta
    assert [a for a in corpo["avisos"] if AVISO in a] == [AVISO_UMA]
    assert alvo not in json.dumps(corpo, ensure_ascii=False)


def test_ficha_de_A_nao_volta_com_o_backup_de_A_se_B_excluiu_de_vez_a_copia(
        cliente, cliente_global, db, escola_completa):
    escola, destino, alvo, outros = _copia_de_A_em_B(
        cliente, cliente_global, db, escola_completa, "ESCOLA DESTINO FICTICIA ORIGINAL")
    backup_a = _baixar(cliente, escola.id)
    _excluir(cliente_global, destino.id, _id_atual(db, destino.id, alvo))
    assert alvo in _nomes(db, escola.id)            # a exclusão em B não apaga A
    corpo = _restaurar(cliente_global, escola.id, backup_a)
    assert _nomes(db, escola.id) == outros           # a ficha de A não volta
    assert [a for a in corpo["avisos"] if AVISO in a] == [AVISO_UMA]
    assert alvo not in json.dumps(corpo, ensure_ascii=False)


def test_controle_copia_sem_exclusao_volta_com_o_backup_de_B(
        cliente, cliente_global, db, escola_completa):
    """Sem exclusão de vez em nenhuma das escolas, a cópia de B volta inteira."""
    _escola_a, destino, alvo, outros = _copia_de_A_em_B(
        cliente, cliente_global, db, escola_completa, "ESCOLA DESTINO FICTICIA CONTROLE")
    backup_b = _baixar(cliente_global, destino.id)
    corpo = _restaurar(cliente_global, destino.id, backup_b)
    assert _nomes(db, destino.id) == outros | {alvo}
    assert not [a for a in corpo["avisos"] if AVISO in a]


# ---------------------------------------------------------------------------
# O "depois" do backup é medido no log INTEIRO (revisão adversarial do e97w-final)
# ---------------------------------------------------------------------------
# A marca do arquivo (``log_ate``) era o último id do log da escola que baixa, mas as
# exclusões e a linhagem valem em qualquer escola. A exclusão de vez feita na outra
# escola ANTES do backup, com id maior que o último log da escola que baixa, contava
# como "depois": a restauração apagava a ficha viva com o aviso "depois deste backup",
# e um 2º download do mesmo estado (o ``backup.gerado`` do 1º sobe a marca) a devolvia.
# Agora a marca é o último id do log inteiro (``backup._ultimo_log``).


def test_backup_de_A_gerado_depois_que_B_excluiu_de_vez_a_copia_traz_a_ficha_de_A(
        cliente, cliente_global, db, escola_completa):
    escola, destino, alvo, outros = _copia_de_A_em_B(
        cliente, cliente_global, db, escola_completa, "ESCOLA DESTINO FICTICIA DEPOIS A")
    _excluir(cliente_global, destino.id, _id_atual(db, destino.id, alvo))   # em B, ANTES
    assert _nomes(db, escola.id) == outros | {alvo}       # a ficha de A segue viva
    backup_a = _baixar(cliente, escola.id)                 # o backup de A, DEPOIS
    assert alvo in backup_a.decode("utf-8")
    corpo = _restaurar(cliente_global, escola.id, backup_a)
    assert _nomes(db, escola.id) == outros | {alvo}, "a ficha viva de A sumiu"
    assert not [a for a in corpo["avisos"] if AVISO in a]


def test_dois_downloads_do_mesmo_estado_de_A_restauram_igual(
        cliente, cliente_global, db, escola_completa):
    """Depois que B excluiu de vez a cópia, A baixa o backup duas vezes seguidas, sem
    nada mudar entre elas: o resultado da restauração não pode depender de qual dos dois
    arquivos volta (antes, o 1º deixava a ficha de A de fora e o 2º a devolvia)."""
    escola, destino, alvo, outros = _copia_de_A_em_B(
        cliente, cliente_global, db, escola_completa, "ESCOLA DESTINO FICTICIA DOIS DOWNLOADS")
    _excluir(cliente_global, destino.id, _id_atual(db, destino.id, alvo))   # em B, ANTES
    id_em_a = _id_atual(db, escola.id, alvo)
    primeiro = json.loads(_baixar(cliente, escola.id))
    segundo = json.loads(_baixar(cliente, escola.id))
    assert primeiro["tabelas"]["alunos"] == segundo["tabelas"]["alunos"]   # mesmo estado
    assert [id_em_a in backup._excluidos_depois_do_backup(db, escola.id, d["log_ate"])
            for d in (primeiro, segundo)] == [False, False]
    for dados in (primeiro, segundo):
        corpo = _restaurar(cliente_global, escola.id, json.dumps(dados).encode("utf-8"))
        assert _nomes(db, escola.id) == outros | {alvo}
        assert not [a for a in corpo["avisos"] if AVISO in a]


def test_backup_de_B_gerado_depois_que_A_excluiu_de_vez_traz_a_copia_de_B(
        cliente, cliente_global, db, escola_completa):
    """O mesmo, no outro sentido (o defeito já existia no a905767 para a cópia de B)."""
    escola, destino, alvo, outros = _copia_de_A_em_B(
        cliente, cliente_global, db, escola_completa, "ESCOLA DESTINO FICTICIA DEPOIS B")
    _excluir(cliente_global, escola.id, _id_atual(db, escola.id, alvo))     # em A, ANTES
    assert alvo in _nomes(db, destino.id)                 # a cópia de B segue viva
    backup_b = _baixar(cliente_global, destino.id)         # o backup de B, DEPOIS
    assert alvo in backup_b.decode("utf-8")
    corpo = _restaurar(cliente_global, destino.id, backup_b)
    assert _nomes(db, destino.id) == outros | {alvo}, "a cópia viva de B sumiu"
    assert not [a for a in corpo["avisos"] if AVISO in a]
