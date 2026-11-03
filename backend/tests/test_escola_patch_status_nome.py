"""PATCH /escolas/{id}: status só pelo Admin Global e nome com tamanho mínimo
(achado e97/autorização 3, parte que é autorização).

Antes: o admin LOCAL desfazia pela API a inativação feita pelo global (e podia
inativar a própria escola), embora a tela de (des)ativar seja só do global; e o
nome aceitava vazio / só espaços (e um ``null`` estourava a coluna com 500).
O que "inativa" significa para o ACESSO segue decisão do dono (não muda aqui):
docs/operacao/STATUS-ESCOLA-REDE.md. Dados fictícios.
"""
import pytest

from app.models import Escola

API = "/api/v1"


def _status_no_banco(db, escola_id: int) -> str:
    db.expire_all()
    return db.get(Escola, escola_id).status


def test_admin_local_nao_inativa_a_propria_escola(db, escola_completa, cliente):
    escola = escola_completa["escola"]
    r = cliente.patch(f"{API}/escolas/{escola.id}", json={"status": "inativa"})
    assert r.status_code == 403, r.text
    assert "administrador global" in r.json()["detail"]
    assert _status_no_banco(db, escola.id) == "ativa"


def test_admin_local_nao_desfaz_a_inativacao_do_global(db, escola_completa, cliente,
                                                       cliente_global):
    escola = escola_completa["escola"]
    url = f"{API}/escolas/{escola.id}"
    assert cliente_global.patch(url, json={"status": "inativa"}).status_code == 200
    r = cliente.patch(url, json={"status": "ativa"})
    assert r.status_code == 403, r.text
    assert _status_no_banco(db, escola.id) == "inativa"
    # O global reativa: segue podendo.
    assert cliente_global.patch(url, json={"status": "ativa"}).status_code == 200
    assert _status_no_banco(db, escola.id) == "ativa"


def test_reenviar_o_status_atual_segue_aceito_e_a_edicao_local_continua(
        db, escola_completa, cliente):
    """Cliente que reenvia o objeto inteiro (status igual ao atual) não é barrado,
    e a edição local de cidade/UF (tela Configurações) continua do admin local."""
    escola = escola_completa["escola"]
    r = cliente.patch(f"{API}/escolas/{escola.id}",
                      json={"status": "ativa", "cidade": "Cidade Ficticia", "estado": "SP"})
    assert r.status_code == 200, r.text
    assert r.json()["cidade"] == "Cidade Ficticia"
    assert _status_no_banco(db, escola.id) == "ativa"


@pytest.mark.parametrize("nome", ["", "   ", "A", " B ", None, "x" * 201])
def test_nome_vazio_curto_nulo_ou_longo_e_recusado(db, escola_completa, cliente, nome):
    escola = escola_completa["escola"]
    r = cliente.patch(f"{API}/escolas/{escola.id}", json={"nome": nome})
    assert r.status_code == 422, r.text
    db.expire_all()
    assert db.get(Escola, escola.id).nome == "ESCOLA TESTE"


def test_nome_valido_e_gravado_sem_espacos_nas_pontas(db, escola_completa, cliente):
    escola = escola_completa["escola"]
    r = cliente.patch(f"{API}/escolas/{escola.id}", json={"nome": "  EM Nome Ficticio  "})
    assert r.status_code == 200, r.text
    assert r.json()["nome"] == "EM Nome Ficticio"
    db.expire_all()
    assert db.get(Escola, escola.id).nome == "EM Nome Ficticio"


def test_global_tambem_obedece_ao_tamanho_do_nome(db, escola_completa, cliente_global):
    escola = escola_completa["escola"]
    assert cliente_global.patch(f"{API}/escolas/{escola.id}",
                                json={"nome": "  "}).status_code == 422


@pytest.mark.parametrize("corpo", [{"status": None}, {"ano_letivo_ativo": None},
                                   {"status": None, "cidade": "Cidade Ficticia"}])
@pytest.mark.parametrize("quem", ["local", "global"])
def test_status_ou_ano_letivo_nulo_responde_422_sem_gravar(
        db, escola_completa, cliente, cliente_global, corpo, quem):
    """`null` explícito em coluna NOT NULL passava pelas travas e virava 500
    (IntegrityError) no commit; agora é 422 e nada muda."""
    escola = escola_completa["escola"]
    c = cliente if quem == "local" else cliente_global
    r = c.patch(f"{API}/escolas/{escola.id}", json=corpo)
    assert r.status_code == 422, r.text
    db.expire_all()
    gravada = db.get(Escola, escola.id)
    assert gravada.status == "ativa"
    assert gravada.ano_letivo_ativo == 2026
    assert gravada.cidade != "Cidade Ficticia"
