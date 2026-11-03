"""Quest — regenerar a turma (folha perdida) revoga também o cartão de quem estava na
folha impressa e depois TROCOU de turma.

O regenerar da turma (POST /turmas/{id}/cartoes?regenerar=true) só alcançava quem
estava matriculado nela NAQUELA HORA (ativos no PDF, inativos pelo 3737a13). A troca
de turma reescreve a matrícula sem histórico (Lista Piloto: ``mat.turma_id =
turma.id``; troca manual): a criança que estava na folha da turma A e foi para a B
seguia com o cartão da folha — e, com a ficha ativa, quem achasse a folha entrava na
hora pelo código ou pelo QR, e a sessão aberta antes seguia respondendo.

Agora a auditoria de cada folha (``quest.cartoes_gerados``) guarda os ``aluno_ids``
do PDF, e o regenerar (ou ``rotacionar_codigo``) da turma revoga também o cartão de
quem foi impresso numa folha dela desde a última revogação e não está mais
matriculado nela — sem PDF para ele (o cartão novo sai na turma de agora) —, com
``revogados_fora_da_turma`` (e os ids) na auditoria. Sem revogação pedida nada muda.

Regressão do achado 2 da dimensão mobile-quest (integração 6 do e97; prova
test_prova_602, invertida). Dados fictícios (fixture escola_completa).
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import PROJECT_ROOT
from app.main import app
from app.models import Aluno, LogAuditoria, Matricula, Turma
from app.quest.models import QuestCredencialAluno
from tests.test_permissoes import cenario_professor  # noqa: F401  (fixture)

ENTRAR = "/api/v1/quest/auth/entrar"
ENTRAR_QR = "/api/v1/quest/auth/entrar-qr"
PERFIL = "/api/v1/quest/perfil"


def _cred(db, aluno_id) -> QuestCredencialAluno | None:
    db.expire_all()
    return db.execute(select(QuestCredencialAluno)
                      .where(QuestCredencialAluno.aluno_id == aluno_id)).scalar_one_or_none()


def _cartao(cred: QuestCredencialAluno) -> tuple:
    return cred.codigo_login, cred.qr_token, cred.token_version


def _folha(cliente, escola_id, turma_id, consulta=""):
    r = cliente.post(f"/api/v1/escolas/{escola_id}/quest/turmas/{turma_id}/cartoes{consulta}")
    assert r.status_code == 200, r.text
    return r


def _turma_b(db, escola, ano):
    turma = Turma(escola_id=escola.id, nome="5º Ano B", ano_escolar="5º Ano", ano_letivo=ano)
    db.add(turma)
    db.flush()
    return turma


def _trocar_de_turma(db, aluno_id, de, para):
    """O que a Lista Piloto e a troca manual fazem: reescrevem a matrícula."""
    db.expire_all()
    mat = db.execute(select(Matricula).where(Matricula.aluno_id == aluno_id,
                                             Matricula.turma_id == de.id)).scalar_one()
    mat.turma_id = para.id
    db.commit()


def _ultimo_log(db) -> LogAuditoria:
    db.expire_all()
    return db.execute(select(LogAuditoria)
                      .where(LogAuditoria.acao == "quest.cartoes_gerados")
                      .order_by(LogAuditoria.id.desc())).scalars().first()


def _entram(cartao, jwt) -> tuple:
    codigo, qr, _ = cartao
    return (TestClient(app).post(ENTRAR, json={"codigo": codigo}).status_code,
            TestClient(app).post(ENTRAR_QR, json={"qr_token": qr}).status_code,
            TestClient(app).get(PERFIL, headers={"Authorization": f"Bearer {jwt}"}).status_code)


def _sessao(codigo) -> str:
    r = TestClient(app).post(ENTRAR, json={"codigo": codigo})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest.mark.parametrize("consulta", ["?regenerar=true", "?rotacionar_codigo=true"])
def test_folha_perdida_da_turma_a_cai_para_quem_trocou_de_turma(
        cliente, db, escola_completa, consulta):
    escola, turma_a = escola_completa["escola"], escola_completa["turma"]
    a0, x, a2 = (a.id for a in escola_completa["alunos"])
    # 1) Folha da turma A impressa (cartões dos 3); a auditoria guarda quem estava nela.
    _folha(cliente, escola.id, turma_a.id)
    assert _ultimo_log(db).detalhes["aluno_ids"] == [a0, x, a2]
    antigo = _cartao(_cred(db, x))
    jwt = _sessao(antigo[0])

    # 2) X troca de turma no mesmo ano (a ficha segue ativa).
    turma_b = _turma_b(db, escola, turma_a.ano_letivo)
    _trocar_de_turma(db, x, turma_a, turma_b)

    # 3) A folha da turma A se perde: regenerar a turma A.
    _folha(cliente, escola.id, turma_a.id, consulta)

    novo = _cred(db, x)
    assert novo.codigo_login != antigo[0] and novo.qr_token != antigo[1]
    assert novo.token_version == antigo[2] + 1
    assert _entram(antigo, jwt) == (401, 401, 401)       # era (200, 200, 200)
    log = _ultimo_log(db)
    assert log.detalhes["revogados_fora_da_turma"] == 1
    assert log.detalhes["revogados_fora_da_turma_ids"] == [x]
    assert log.detalhes["revogados_inativos"] == 0
    assert log.detalhes["aluno_ids"] == [a0, a2]          # X não entra no PDF de A
    assert log.detalhes["alunos"] == 2
    # A criança segue ativa: o cartão NOVO entra, e a folha da turma B já o traz.
    assert TestClient(app).post(ENTRAR, json={"codigo": novo.codigo_login}).status_code == 200
    _folha(cliente, escola.id, turma_b.id)
    assert _cartao(_cred(db, x)) == _cartao(novo)        # reimpressão de B: o código novo


def test_controle_quem_ficou_na_turma_a_perde_o_cartao(cliente, db, escola_completa):
    escola, turma_a = escola_completa["escola"], escola_completa["turma"]
    y = escola_completa["alunos"][0].id
    _folha(cliente, escola.id, turma_a.id)
    antigo = _cartao(_cred(db, y))
    jwt = _sessao(antigo[0])
    _folha(cliente, escola.id, turma_a.id, "?regenerar=true")
    assert _entram(antigo, jwt) == (401, 401, 401)
    assert _ultimo_log(db).detalhes["revogados_fora_da_turma"] == 0


def test_quem_nunca_esteve_na_folha_da_turma_a_nao_e_tocado(cliente, db, escola_completa):
    escola, turma_a = escola_completa["escola"], escola_completa["turma"]
    turma_b = _turma_b(db, escola, turma_a.ano_letivo)
    z = Aluno(escola_id=escola.id, nome="Aluno Da Turma B Ficticio")
    db.add(z)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=z.id, turma_id=turma_b.id,
                     ano_letivo=turma_a.ano_letivo))
    db.commit()
    _folha(cliente, escola.id, turma_b.id)                # Z só esteve na folha de B
    _folha(cliente, escola.id, turma_a.id)
    antes = _cartao(_cred(db, z.id))
    jwt = _sessao(antes[0])

    _folha(cliente, escola.id, turma_a.id, "?regenerar=true")

    assert _cartao(_cred(db, z.id)) == antes
    assert _entram(antes, jwt) == (200, 200, 200)
    assert _ultimo_log(db).detalhes["revogados_fora_da_turma"] == 0


def test_reimpressao_sem_revogacao_nao_toca_quem_saiu(cliente, db, escola_completa):
    escola, turma_a = escola_completa["escola"], escola_completa["turma"]
    x = escola_completa["alunos"][1].id
    _folha(cliente, escola.id, turma_a.id)
    antes = _cartao(_cred(db, x))
    _trocar_de_turma(db, x, turma_a, _turma_b(db, escola, turma_a.ano_letivo))

    _folha(cliente, escola.id, turma_a.id)                # reimpressão: nada é revogado

    assert _cartao(_cred(db, x)) == antes
    detalhes = _ultimo_log(db).detalhes
    assert detalhes["revogados_fora_da_turma"] == 0 and detalhes["revogados_fora_da_turma_ids"] == []


def test_so_as_folhas_desde_a_ultima_revogacao_contam(cliente, db, escola_completa):
    """A folha da última revogação entra (saiu com os cartões novos); as de antes já
    caíram nela. Quem saiu ANTES da última revogação foi revogado ali e ganhou cartão
    na turma nova: o regenerar seguinte da turma A não derruba esse cartão."""
    escola, turma_a = escola_completa["escola"], escola_completa["turma"]
    a0, x, a2 = (a.id for a in escola_completa["alunos"])
    turma_b = _turma_b(db, escola, turma_a.ano_letivo)
    _folha(cliente, escola.id, turma_a.id)                # folha 1: a0, x, a2
    _trocar_de_turma(db, a2, turma_a, turma_b)            # a2 sai antes da 1ª revogação
    _folha(cliente, escola.id, turma_a.id, "?regenerar=true")   # folha 2: a0, x
    assert _ultimo_log(db).detalhes["revogados_fora_da_turma_ids"] == [a2]
    _folha(cliente, escola.id, turma_b.id)                # a2 recebe o cartão em B
    cartao_de_b = _cartao(_cred(db, a2))
    x_na_folha_2 = _cartao(_cred(db, x))
    jwt_x = _sessao(x_na_folha_2[0])
    _trocar_de_turma(db, x, turma_a, turma_b)             # x sai depois da 1ª revogação

    _folha(cliente, escola.id, turma_a.id, "?regenerar=true")

    assert _ultimo_log(db).detalhes["revogados_fora_da_turma_ids"] == [x]
    assert _entram(x_na_folha_2, jwt_x) == (401, 401, 401)
    assert _cartao(_cred(db, a2)) == cartao_de_b          # o cartão de B segue valendo


def test_folha_registrada_antes_dos_aluno_ids_nao_quebra_o_regenerar(
        cliente, db, escola_completa):
    """A auditoria antiga não traz ``aluno_ids``: dela não há como saber quem estava
    impresso, e o regenerar segue como antes para quem está na turma."""
    escola, turma_a = escola_completa["escola"], escola_completa["turma"]
    db.add(LogAuditoria(escola_id=escola.id, acao="quest.cartoes_gerados",
                        entidade="turma", entidade_id=turma_a.id,
                        detalhes={"alunos": 3, "regenerou": False, "rotacionou_codigo": False}))
    db.commit()
    _folha(cliente, escola.id, turma_a.id, "?regenerar=true")
    detalhes = _ultimo_log(db).detalhes
    assert detalhes["revogados_fora_da_turma"] == 0 and detalhes["alunos"] == 3


def test_professor_da_turma_a_regenera_e_o_cartao_de_quem_saiu_cai(
        cenario_professor, db, escola_completa):  # noqa: F811
    """O professor restrito regenera a turma dele; o cartão impresso na folha dele
    cai mesmo que a criança agora esteja na turma de outro professor (não há PDF
    nem código novo dela para ele)."""
    c = cenario_professor
    escola, turma_a, turma_b = c["escola"], c["turma_a"], c["turma_b"]
    x = escola_completa["alunos"][1].id
    _folha(c["professor"], escola.id, turma_a.id)
    antigo = _cartao(_cred(db, x))
    jwt = _sessao(antigo[0])
    _trocar_de_turma(db, x, turma_a, turma_b)

    r = _folha(c["professor"], escola.id, turma_a.id, "?regenerar=true")

    assert r.headers["content-type"] == "application/pdf"
    assert _entram(antigo, jwt) == (401, 401, 401)
    assert _ultimo_log(db).detalhes["revogados_fora_da_turma_ids"] == [x]


def test_bible_21_e_apendice_b_dizem_que_o_regenerar_alcanca_quem_saiu_da_turma():
    """A documentação de suporte diz o que o regenerar da turma faz (PT e EN)."""
    def _plano(rel):
        texto = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
        return " ".join(texto.replace("**", "").replace("`", "").split())

    secao = _plano("docs/bible/21-suporte-operacao.md")
    assert "Folha da turma perdida com criança que já trocou de turma" in secao
    assert "Lost class sheet with a child who has since changed class" in secao
    assert secao.count("revogados_fora_da_turma") == 2
    assert _plano("docs/bible/apendice-B-api-dados.md").count("revogados_fora_da_turma") == 2
