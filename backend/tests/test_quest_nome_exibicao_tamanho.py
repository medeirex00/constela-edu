"""Quest — o nome da cerimônia cabe na coluna DEPOIS da normalização.

``validar_nome_exibicao`` conferia 2..20 caracteres ANTES do ``str.title()``, e o
title() do Python pode EXPANDIR o texto: a ligadura U+FB03 vira "Ffi" (3) e o
U+0130 (I com ponto) vira "i" + U+0307 (2). Os dois passam no ``isalpha()`` e o
front aceita qualquer letra. Vinte caracteres de entrada viravam 41 gravados em
``quest_perfis.nome_exibicao`` (String(40)): no PostgreSQL, 500 no commit
(StringDataRightTruncation) em vez de 422.

Agora o tamanho é conferido no valor que vai ao banco (title() + NFC): o excesso é
422 e nada é gravado. Regressão do achado 2 do módulo quest na revisão e97 (provas
test_prova_1/2, invertidas aqui). A mesma bateria roda no PostgreSQL em
``test_quest_nome_exibicao_tamanho_pg.py``. Dados fictícios.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.quest.models import QuestCredencialAluno, QuestPerfil
from app.quest.services import perfis

# 20 caracteres, todos isalpha(): o title() leva a 41.
NOME_QUE_EXPANDE = "ﬃ" + "İ" * 19
NOME = "/api/v1/quest/perfil/nome"


def _coluna() -> int:
    return QuestPerfil.__table__.c.nome_exibicao.type.length


def _sessao_da_crianca(cliente, db, escola_completa):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    aluno = escola_completa["alunos"][0]
    r = cliente.post(f"/api/v1/escolas/{escola.id}/quest/turmas/{turma.id}/cartoes")
    assert r.status_code == 200, r.text
    db.expire_all()
    cred = db.execute(select(QuestCredencialAluno)
                      .where(QuestCredencialAluno.aluno_id == aluno.id)).scalar_one()
    # Sem relançar a exceção do servidor: um 500 aparece como status, não como erro.
    crianca = TestClient(app, raise_server_exceptions=False)
    r = crianca.post("/api/v1/quest/auth/entrar", json={"codigo": cred.codigo_login})
    assert r.status_code == 200, r.text
    crianca.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return crianca, aluno.id


def _gravado(db, aluno_id):
    db.expire_all()
    return db.execute(select(QuestPerfil.nome_exibicao)
                      .where(QuestPerfil.aluno_id == aluno_id)).scalar_one()


# --- o validador --------------------------------------------------------------

def test_a_entrada_de_20_que_expande_passava_do_limite_e_da_coluna():
    """Pré-condição da regressão: a entrada é válida pelas regras ANTIGAS (20
    letras) e o title() a leva além do limite e da coluna."""
    assert len(NOME_QUE_EXPANDE) == 20 and NOME_QUE_EXPANDE.isalpha()
    assert len(NOME_QUE_EXPANDE.title()) == 41 > _coluna() == 40


def test_validador_recusa_o_nome_que_cresce_alem_de_20():
    with pytest.raises(ValueError, match="entre 2 e 20"):
        perfis.validar_nome_exibicao(NOME_QUE_EXPANDE)


@pytest.mark.parametrize("entrada", [
    " ".join(["ﬃ"] * 7),  # 13 -> 27 (cada palavra vira "Ffi")
    "ß" * 20,            # ß: 20 -> 21 ("Ssßßß...")
    "Ana " + "İ" * 16,   # 20 -> 36
])
def test_validador_confere_o_tamanho_do_que_vai_ao_banco(entrada):
    assert len(entrada) <= 20
    with pytest.raises(ValueError):
        perfis.validar_nome_exibicao(entrada)


@pytest.mark.parametrize("entrada, esperado", [
    ("ana clara", "Ana Clara"),
    ("  maria   eduarda ", "Maria Eduarda"),
    ("joão", "João"),
    ("a" * 20, "A" + "a" * 19),                 # no limite: 20 continua valendo
    ("İİ", "İi̇"),          # cresce, mas cabe: 3 <= 20
])
def test_validador_aceita_nome_que_cabe(entrada, esperado):
    saida = perfis.validar_nome_exibicao(entrada)
    assert saida == esperado
    assert 2 <= len(saida) <= 20 <= _coluna()


def test_validador_mantem_as_regras_de_antes():
    for ruim in ("a", "a" * 21, "Ana1", "Ana!", "\U0001F600\U0001F600"):
        with pytest.raises(ValueError):
            perfis.validar_nome_exibicao(ruim)


# --- a rota (a mesma bateria roda no PostgreSQL) -------------------------------

def test_rota_nome_que_expande_da_422_e_nao_grava(cliente, db, escola_completa):
    crianca, aluno_id = _sessao_da_crianca(cliente, db, escola_completa)
    ok = crianca.patch(NOME, json={"nome": "ana clara"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["nome_exibicao"] == "Ana Clara"

    r = crianca.patch(NOME, json={"nome": NOME_QUE_EXPANDE})
    assert r.status_code == 422, r.text          # antes: 200 no SQLite, 500 no PG
    assert "entre 2 e 20" in r.json()["detail"]
    assert _gravado(db, aluno_id) == "Ana Clara"


def test_rota_nome_de_20_letras_comuns_continua_200(cliente, db, escola_completa):
    crianca, aluno_id = _sessao_da_crianca(cliente, db, escola_completa)
    r = crianca.patch(NOME, json={"nome": "Ana" * 6 + "Bi"})
    assert r.status_code == 200, r.text
    assert _gravado(db, aluno_id) == "Anaanaanaanaanaanabi"
