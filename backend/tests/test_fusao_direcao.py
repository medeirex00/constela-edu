"""Direção da fusão manual: a prévia sugere a ficha principal pela MESMA regra da
fusão em lote (``_melhor_perfil``) e avisa quando a escolha deixa um nome
abreviado na ficha que fica — sem bloquear a fusão. Dados fictícios."""
import pytest

from app.models import Aluno
from app.services import alunos_dedup
from app.services.importacao import nome_abreviado
from tests.sync_integridade_comum import aluno


def _previa(cliente, eid, manter_id, remover_id):
    r = cliente.get(f"/api/v1/escolas/{eid}/alunos/fundir/previa",
                    params={"manter_id": manter_id, "remover_id": remover_id})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("nome, esperado", [
    ("ZEFA Q", True), ("Zefa Q.", True), ("M. EDUARDA", True), ("Kauê", True),
    ("Ana de", True), ("JOAO B SILVA", True),
    ("Zefa Quaresma Lima", False), ("Maria e Silva", False), ("Ana Souza 2", False),
    ("Zefa Quaresma Lima 3A", False), ("", False),
])
def test_nome_abreviado(nome, esperado):
    assert nome_abreviado(nome) is esperado


def test_sugere_a_ficha_da_lista_piloto_mesmo_abrindo_pelo_stub(cliente, db, escola_completa):
    esc, t = escola_completa["escola"], escola_completa["turma"]
    oficial = aluno(db, esc.id, t, "Zefa Quaresma Lima", da_lista_piloto=True)
    stub = aluno(db, esc.id, t, "Zefa Quaresma")
    db.commit()
    # A tela abre pelo stub (é o aluno aberto): a direção pedida é a errada.
    p = _previa(cliente, esc.id, stub.id, oficial.id)
    assert p["sugestao"] == {"manter_id": oficial.id, "remover_id": stub.id,
                             "motivo": "lista_piloto"}
    assert p["nome"]["mantem_abreviado"] is True
    # Na direção sugerida, nada a avisar.
    assert _previa(cliente, esc.id, oficial.id, stub.id)["nome"]["mantem_abreviado"] is False


def test_sem_lista_piloto_vence_o_nome_mais_completo(cliente, db, escola_completa):
    esc, t = escola_completa["escola"], escola_completa["turma"]
    completo = aluno(db, esc.id, t, "Zefa Quaresma Lima")
    stub = aluno(db, esc.id, t, "ZEFA Q")
    db.commit()
    p = _previa(cliente, esc.id, stub.id, completo.id)
    assert p["sugestao"]["manter_id"] == completo.id
    assert p["sugestao"]["motivo"] == "nome_mais_completo"
    assert p["nome"]["mantem_abreviado"] is True


def test_nome_oficial_mais_curto_da_lista_piloto_nao_e_aviso(cliente, db, escola_completa):
    """A Lista Piloto é o cadastro oficial, mesmo quando a plataforma traz o nome
    mais comprido: manter a ficha dela não é "manter nome abreviado"."""
    esc, t = escola_completa["escola"], escola_completa["turma"]
    oficial = aluno(db, esc.id, t, "Zefa Lima", da_lista_piloto=True)
    plataforma = aluno(db, esc.id, t, "Zefa Quaresma Lima")
    db.commit()
    p = _previa(cliente, esc.id, oficial.id, plataforma.id)
    assert p["sugestao"]["manter_id"] == oficial.id
    assert p["nome"]["mantem_abreviado"] is False


@pytest.mark.parametrize("oficial_nome, outro_nome", [
    ("Zefa J Quaresma Lima", "Zefa Joana Quaresma Lima"),
    ("Ana D Avila Souza", "ANA D"),          # D'Ávila que chegou sem o apóstrofo
])
def test_nome_oficial_com_inicial_nao_e_aviso_contra_a_propria_sugestao(
        cliente, db, escola_completa, oficial_nome, outro_nome):
    """A prévia sugere manter a ficha da Lista Piloto; o aviso "nome abreviado,
    clique em trocar" não pode mandar o contrário e apagar o nome oficial."""
    esc, t = escola_completa["escola"], escola_completa["turma"]
    oficial = aluno(db, esc.id, t, oficial_nome, da_lista_piloto=True)
    outro = aluno(db, esc.id, t, outro_nome)
    db.commit()
    p = _previa(cliente, esc.id, oficial.id, outro.id)
    assert p["sugestao"]["manter_id"] == oficial.id
    assert p["nome"]["mantem_abreviado"] is False
    # Aberta pelo outro lado (a direção contrária à sugestão), o aviso continua
    # quando o nome que ficaria é o abreviado.
    if nome_abreviado(outro_nome):
        assert _previa(cliente, esc.id, outro.id, oficial.id)["nome"]["mantem_abreviado"] is True


def test_mesma_regra_do_lote(cliente, db, escola_completa):
    """O par que o lote oferece tem o mesmo principal que a fusão manual sugere."""
    esc, t = escola_completa["escola"], escola_completa["turma"]
    oficial = aluno(db, esc.id, t, "Zefa Quaresma Lima", da_lista_piloto=True)
    stub = aluno(db, esc.id, t, "ZEFA Q")
    db.commit()
    [par] = [c for c in alunos_dedup.plano_deduplicacao(db, esc.id) if c["loser_id"] == stub.id]
    assert _previa(cliente, esc.id, stub.id, oficial.id)["sugestao"]["manter_id"] == par["manter_id"]


def test_a_api_continua_aceitando_manter_o_stub(cliente, db, escola_completa):
    """Sugestão não é trava: o gestor pode saber de algo que o dado não conta."""
    esc, t = escola_completa["escola"], escola_completa["turma"]
    oficial = aluno(db, esc.id, t, "Zefa Quaresma Lima", da_lista_piloto=True)
    stub = aluno(db, esc.id, t, "ZEFA Q")
    db.commit()
    stub_id, oficial_id = stub.id, oficial.id
    r = cliente.post(f"/api/v1/escolas/{esc.id}/alunos/fundir",
                     json={"manter_id": stub_id, "remover_id": oficial_id,
                           "confirmacao": "FUNDIR"})
    assert r.status_code == 200, r.text
    db.expire_all()
    ficou = db.get(Aluno, stub_id)
    assert ficou.nome == "ZEFA Q" and ficou.da_lista_piloto is True
