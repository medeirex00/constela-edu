"""Ajuste manual (Matific/Elefante) e catálogo de livros: valores que não cabem na
coluna viram 422, não 500 (G_AJUSTE-7).

``MatificEdicao`` (atividades, estrelas), ``ElefanteEdicao`` (tempo, questões) e
``LivroCreate``/``LivroUpdate`` (páginas, autor, categoria) aceitavam valores que
não cabem nas colunas (INTEGER, VARCHAR(200)/(100)). O SQLite aceita tudo; o
PostgreSQL recusa no commit (DataError) e a tela recebia "Erro interno" sem dizer
o campo. Agora o pedido é recusado com 422 antes do banco e nada é gravado. A
paridade schema × coluna fica conferida aqui; os testes de API rodam também num PG
real (``..._pg.py``). Dados fictícios.
"""
import pytest
from sqlalchemy import select

from app.models import Livro, SnapshotElefante, SnapshotMatific
from app.schemas import ElefanteEdicao, LivroCreate, LivroUpdate, MatificEdicao

API = "/api/v1"
INTEIRO_MAX = 2_147_483_647          # teto da coluna INTEGER do PostgreSQL
ACIMA = 3_000_000_000
MOTIVO = "correção do relatório"


def _limite(schema, campo: str, atributo: str):
    valores = [getattr(m, atributo, None) for m in schema.model_fields[campo].metadata]
    return next((v for v in valores if v is not None), None)


@pytest.mark.parametrize("schema,campo", [
    (MatificEdicao, "atividades"), (MatificEdicao, "estrelas"),
    (ElefanteEdicao, "tempo_leitura_min"), (ElefanteEdicao, "questoes_tentativas"),
    (ElefanteEdicao, "questoes_acertos"),
    (LivroCreate, "paginas"), (LivroUpdate, "paginas"),
])
def test_inteiros_do_schema_cabem_na_coluna_integer(schema, campo):
    teto = _limite(schema, campo, "le")
    assert teto is not None, f"{schema.__name__}.{campo} sem teto (le)"
    assert teto <= INTEIRO_MAX


@pytest.mark.parametrize("schema,campo,coluna", [
    (LivroCreate, "autor", Livro.autor), (LivroUpdate, "autor", Livro.autor),
    (LivroCreate, "categoria", Livro.categoria), (LivroUpdate, "categoria", Livro.categoria),
])
def test_textos_do_livro_cabem_na_coluna(schema, campo, coluna):
    limite = _limite(schema, campo, "max_length")
    assert limite is not None, f"{schema.__name__}.{campo} sem max_length"
    assert limite <= coluna.property.columns[0].type.length


@pytest.fixture()
def ids(db, escola_completa):
    escola = escola_completa["escola"]
    livro = Livro(escola_id=escola.id, titulo="Livro Fictício do Limite", nivel_codigo="C",
                  origem_nivel="legado")
    db.add(livro)
    db.commit()
    return {"base": f"{API}/escolas/{escola.id}", "aluno": escola_completa["alunos"][0].id,
            "livro": livro.id}


@pytest.mark.parametrize("corpo", [
    {"atividades": ACIMA, "estrelas": 1},
    {"atividades": 1, "estrelas": ACIMA},
], ids=["atividades", "estrelas"])
def test_matific_acima_da_coluna_e_422(cliente, db, ids, corpo):
    r = cliente.put(f"{ids['base']}/matific/{ids['aluno']}", json={**corpo, "motivo": MOTIVO})
    assert r.status_code == 422, r.text
    db.expire_all()
    assert db.execute(select(SnapshotMatific)).first() is None


@pytest.mark.parametrize("campo", ["tempo_leitura_min", "questoes_tentativas",
                                   "questoes_acertos"])
def test_elefante_acima_da_coluna_e_422(cliente, db, ids, campo):
    corpo = {"tempo_leitura_min": 1, "questoes_tentativas": 0, "questoes_acertos": 0,
             "motivo": MOTIVO}
    corpo[campo] = ACIMA
    if campo == "questoes_acertos":
        corpo["questoes_tentativas"] = ACIMA
    r = cliente.put(f"{ids['base']}/elefante/{ids['aluno']}", json=corpo)
    assert r.status_code == 422, r.text
    db.expire_all()
    assert db.execute(select(SnapshotElefante)).first() is None


def test_matific_e_elefante_no_teto_da_coluna_sao_aceitos(cliente, ids):
    r = cliente.put(f"{ids['base']}/matific/{ids['aluno']}",
                    json={"atividades": INTEIRO_MAX // 5, "estrelas": INTEIRO_MAX // 5 * 5,
                          "motivo": MOTIVO})
    assert r.status_code == 200, r.text
    r = cliente.put(f"{ids['base']}/elefante/{ids['aluno']}",
                    json={"tempo_leitura_min": INTEIRO_MAX, "questoes_tentativas": INTEIRO_MAX,
                          "questoes_acertos": INTEIRO_MAX, "motivo": MOTIVO})
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("campo,valor", [
    ("autor", "A" * 201), ("categoria", "C" * 101), ("paginas", 100_001), ("paginas", ACIMA),
], ids=["autor", "categoria", "paginas", "paginas_coluna"])
def test_livro_acima_do_limite_e_422_no_cadastro_e_na_correcao(cliente_global, db, ids,
                                                                campo, valor):
    novo = cliente_global.post(f"{ids['base']}/livros",
                               json={"titulo": "Outro Livro Fictício", "nivel_codigo": "C",
                                     campo: valor})
    assert novo.status_code == 422, novo.text
    correcao = cliente_global.patch(f"{ids['base']}/livros/{ids['livro']}", json={campo: valor})
    assert correcao.status_code == 422, correcao.text
    db.expire_all()
    livros = db.execute(select(Livro)).scalars().all()
    assert [(l.titulo, l.autor, l.categoria, l.paginas) for l in livros] == [
        ("Livro Fictício do Limite", None, None, None)]


def test_livro_no_limite_e_aceito(cliente_global, ids):
    no_limite = {"autor": "A" * 200, "categoria": "C" * 100, "paginas": 100_000}
    novo = cliente_global.post(f"{ids['base']}/livros",
                               json={"titulo": "Outro Livro Fictício", "nivel_codigo": "C",
                                     **no_limite})
    assert novo.status_code == 201, novo.text
    correcao = cliente_global.patch(f"{ids['base']}/livros/{ids['livro']}", json=no_limite)
    assert correcao.status_code == 200, correcao.text
