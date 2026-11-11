"""Vitrine pública da rede (sem login) não publica o per capita de escola com menos de
K_MINIMO (5) crianças que concorrem (revisão independente dados-lgpd, d4caac4).

Antes, ``_top_escolas`` filtrava só ``alunos_com_dados > 0`` e valor > 0: a escola com
UMA criança de 1º a 5º ano aparecia com o total de livros (ou de estrelas) dela, num
endereço sem login, enquanto a análise autenticada suprime a mesma escola (k = 5,
docs/analise/METODOLOGIA.md 3.5). Agora a escola entra na vitrine só com 5 ou mais
crianças que concorrem; o cálculo não muda.

Integração 80a27da (lente segurança-correção): o k contava o DENOMINADOR. Com 5 crianças
que concorrem e só 1 com dado, o per capita publicado × 5 era o total dessa criança. Agora
o k vale também, por matéria, para quem CONTRIBUI (livros_unicos > 0 no Elefante,
estrelas > 0 no Matific); o per capita e os rankings não mudam.

Dados 100% fictícios."""
from datetime import datetime

from fastapi.testclient import TestClient

from app.main import app
from app.models import Importacao, SnapshotElefante, SnapshotMatific
from app.services.analise import K_MINIMO
from tests.test_analise_base import nova_escola, nova_rede, turma_com_alunos

TOKEN = "vitrineRegressaoK5x"


def _snaps(db, escola, alunos, livros, estrelas):
    imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed",
                     status="concluida", qtd_alunos=0, qtd_erros=0, tempo_ms=0)
    db.add(imp)
    db.flush()
    for aluno in alunos:
        db.add(SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id,
                                importacao_id=imp.id,
                                data_referencia=datetime(2026, 9, 30, 3, 0),
                                livros_unicos=livros, tempo_leitura_min=10 * livros,
                                questoes_tentativas=0, questoes_acertos=0,
                                livros_por_nivel={}))
        # Datado como o do Elefante, no ano letivo da escola (o de ``nova_escola``).
        # Sem data, o retrato era de "agora" e, a partir de 2027, o contador do ANO
        # do Matific o deixava de fora (TESTES-1).
        db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id,
                               importacao_id=imp.id,
                               data_referencia=datetime(escola.ano_letivo_ativo, 9, 30, 3, 0),
                               atividades=10, estrelas=estrelas))


def test_vitrine_omite_escola_com_menos_de_k_criancas_que_concorrem(db):
    assert K_MINIMO == 5
    rede = nova_rede(db)
    rede.token_publico = TOKEN
    mini = nova_escola(db, rede, "EMEF Ficticia Mini", "35990311")
    quatro = nova_escola(db, rede, "EMEF Ficticia Quatro", "35990312")
    cinco = nova_escola(db, rede, "EMEF Ficticia Cinco", "35990313")
    _snaps(db, mini, turma_com_alunos(db, mini, "3º Ano", 1), 37, 143)
    _snaps(db, quatro, turma_com_alunos(db, quatro, "3º Ano", 4), 9, 50)
    _snaps(db, cinco, turma_com_alunos(db, cinco, "3º Ano", 5), 2, 20)
    db.commit()

    r = TestClient(app).get(f"/api/v1/publico/rede/{TOKEN}")       # SEM login
    assert r.status_code == 200, r.text
    corpo = r.json()
    for chave, valor in (("top_leitura", 2.0), ("top_matematica", 20.0)):
        assert corpo[chave] == [{"nome": "EMEF Ficticia Cinco", "valor": valor}], chave


def _vitrine(token):
    r = TestClient(app).get(f"/api/v1/publico/rede/{token}")       # SEM login
    assert r.status_code == 200, r.text
    corpo = r.json()
    return ({e["nome"]: e["valor"] for e in corpo["top_leitura"]},
            {e["nome"]: e["valor"] for e in corpo["top_matematica"]})


def test_vitrine_omite_escola_com_uma_so_crianca_com_dado_entre_cinco(db):
    rede = nova_rede(db)
    rede.token_publico = "vitrineContribUma01"
    escola = nova_escola(db, rede, "EMEF Ficticia Contrib Uma", "35990321")
    criancas = turma_com_alunos(db, escola, "3º Ano", 5)
    _snaps(db, escola, criancas[:1], 37, 143)
    _snaps(db, escola, criancas[1:], 0, 0)          # retrato com zero não contribui
    db.commit()
    assert _vitrine("vitrineContribUma01") == ({}, {})


def test_vitrine_com_cinco_que_contribuem_publica_o_mesmo_per_capita(db):
    rede = nova_rede(db)
    rede.token_publico = "vitrineContribCinco"
    escola = nova_escola(db, rede, "EMEF Ficticia Contrib Cinco", "35990322")
    criancas = turma_com_alunos(db, escola, "3º Ano", 6)    # a 6ª concorre sem dado
    for i, crianca in enumerate(criancas[:5]):
        _snaps(db, escola, [crianca], 2 + i, 20)             # 20 livros, 100 estrelas
    db.commit()
    assert _vitrine("vitrineContribCinco") == (
        {"EMEF Ficticia Contrib Cinco": round(20 / 6, 1)},
        {"EMEF Ficticia Contrib Cinco": round(100 / 6, 1)})


def test_vitrine_aplica_o_k_de_quem_contribui_por_materia(db):
    rede = nova_rede(db)
    rede.token_publico = "vitrineContribMater"
    escola = nova_escola(db, rede, "EMEF Ficticia Contrib Materia", "35990323")
    criancas = turma_com_alunos(db, escola, "3º Ano", 5)
    _snaps(db, escola, criancas[:1], 3, 143)        # só ela tem estrelas
    _snaps(db, escola, criancas[1:], 3, 0)
    db.commit()
    assert _vitrine("vitrineContribMater") == ({"EMEF Ficticia Contrib Materia": 3.0}, {})
