"""Restaurar um arquivo gerado ANTES de outra restauração não traz de volta a criança
excluída de vez depois dela (integração do ramo de prontidão, 80a27da; LGPD art. 18).

A restauração recria cada ficha com id NOVO. Antes, a exclusão feita depois de uma
restauração gravava no log (``aluno.excluido_permanente``) o id novo, e o arquivo
anterior a essa restauração levava o id ANTIGO: os dois nunca casavam no PostgreSQL e a
criança voltava, sem aviso. Agora cada restauração grava em ``backup.restaurado`` o mapa
{id novo: id do arquivo} das fichas (preservado do expurgo) e a restauração segue essa
linhagem (``backup._excluidos_depois_do_backup``).

PostgreSQL REAL, local e descartável (TEST_DATABASE_URL_PG; o nome do banco precisa
conter 'test'): no SQLite o id da tabela vazia recomeça e o defeito não aparece. Mesmo
padrão de ``test_backup_restauracao_respeita_esquecimento_pg.py``. Dados 100% fictícios
(fixture escola_completa)."""
import os

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.main import app
from app.models import Aluno

URL = os.environ.get("TEST_DATABASE_URL_PG", "")
pytestmark = [pytest.mark.postgres,
              pytest.mark.skipif(not URL, reason="defina TEST_DATABASE_URL_PG"),
              pytest.mark.skipif(bool(URL) and "test" not in (make_url(URL).database or ""),
                                 reason="o nome do banco PG de teste precisa conter 'test'")]
API = "/api/v1"
AVISO = ("excluída(s) permanentemente (nesta ou em outra escola) depois deste backup "
         "não foram restauradas")


@pytest.fixture()
def db():
    engine = create_engine(URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)
    sessao = TestSession()

    def _get_db():
        outra = TestSession()
        try:
            yield outra
        finally:
            outra.close()

    app.dependency_overrides[get_db] = _get_db
    yield sessao
    sessao.close()
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _baixar(cliente, escola_id):
    r = cliente.get(f"{API}/escolas/{escola_id}/backup")
    assert r.status_code == 200, r.text
    return r.content


def _restaurar(cliente_global, escola_id, conteudo):
    r = cliente_global.post(f"{API}/escolas/{escola_id}/restaurar",
                            files={"arquivo": ("backup.json", conteudo, "application/json")})
    assert r.status_code == 200, r.text
    return r.json()


def _id_atual(db, escola_id, nome):
    db.expire_all()
    return db.execute(select(Aluno.id).where(Aluno.escola_id == escola_id,
                                             Aluno.nome == nome)).scalar_one()


def _excluir(cliente_global, escola_id, aluno_id):
    r = cliente_global.post(f"{API}/escolas/{escola_id}/alunos/excluir-permanente",
                            json={"aluno_ids": [aluno_id], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text


def _nomes(db, escola_id):
    db.expire_all()
    return set(db.execute(select(Aluno.nome).where(Aluno.escola_id == escola_id)).scalars())


def _cena(cliente, cliente_global, db, escola_completa):
    """Arquivo ANTIGO; restauração intermediária (ids novos); arquivo DEPOIS dela;
    exclusão permanente da criança-alvo pelo id novo."""
    escola = escola_completa["escola"]
    alvo = escola_completa["alunos"][2].nome
    outros = {a.nome for a in escola_completa["alunos"][:2]}
    id_original = _id_atual(db, escola.id, alvo)
    antigo = _baixar(cliente, escola.id)
    _restaurar(cliente_global, escola.id, antigo)
    novo_id = _id_atual(db, escola.id, alvo)
    assert novo_id != id_original          # no PG a restauração troca os ids
    depois = _baixar(cliente, escola.id)
    _excluir(cliente_global, escola.id, novo_id)
    return escola, alvo, outros, antigo, depois


def test_arquivo_anterior_a_outra_restauracao_nao_ressuscita_a_excluida_e_avisa(
        cliente, cliente_global, db, escola_completa):
    escola, alvo, outros, antigo, _depois = _cena(cliente, cliente_global, db,
                                                  escola_completa)
    corpo = _restaurar(cliente_global, escola.id, antigo)
    nomes = _nomes(db, escola.id)
    assert alvo not in nomes and outros <= nomes
    assert [a for a in corpo["avisos"] if AVISO in a] == [
        f"1 criança(s) {AVISO} (direito de eliminação, LGPD art. 18)."]


def test_controle_arquivo_gerado_depois_da_restauracao_respeita_a_exclusao(
        cliente, cliente_global, db, escola_completa):
    escola, alvo, outros, _antigo, depois = _cena(cliente, cliente_global, db,
                                                  escola_completa)
    corpo = _restaurar(cliente_global, escola.id, depois)
    nomes = _nomes(db, escola.id)
    assert alvo not in nomes and outros <= nomes
    assert any(AVISO in a for a in corpo["avisos"])


def test_restauracao_intermediaria_de_arquivo_mais_antigo_tambem_liga_as_fichas(
        cliente, cliente_global, db, escola_completa):
    """A restauração do meio repôs um arquivo AINDA MAIS antigo (de antes de uma
    restauração anterior ao arquivo que agora volta): a linhagem passa pelas duas."""
    escola = escola_completa["escola"]
    alvo = escola_completa["alunos"][2].nome
    outros = {a.nome for a in escola_completa["alunos"][:2]}
    mais_antigo = _baixar(cliente, escola.id)
    _restaurar(cliente_global, escola.id, mais_antigo)       # ids trocam (1ª vez)
    arquivo = _baixar(cliente, escola.id)                     # o que vai voltar no fim
    _restaurar(cliente_global, escola.id, mais_antigo)       # ids trocam (2ª vez)
    _excluir(cliente_global, escola.id, _id_atual(db, escola.id, alvo))
    corpo = _restaurar(cliente_global, escola.id, arquivo)
    nomes = _nomes(db, escola.id)
    assert alvo not in nomes and outros <= nomes
    assert any(AVISO in a for a in corpo["avisos"])


def test_sem_exclusao_restaurar_de_novo_traz_todas_as_criancas(
        cliente, cliente_global, db, escola_completa):
    """Controle: a linhagem não segura criança nenhuma quando ninguém foi excluído."""
    escola = escola_completa["escola"]
    todos = {a.nome for a in escola_completa["alunos"]}
    antigo = _baixar(cliente, escola.id)
    _restaurar(cliente_global, escola.id, antigo)
    corpo = _restaurar(cliente_global, escola.id, antigo)
    assert _nomes(db, escola.id) == todos
    assert not any(AVISO in a for a in corpo["avisos"])
