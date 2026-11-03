"""Quest — revogar o cartão também vale para quem está INATIVO naquela hora.

O regenerar da turma (POST /turmas/{id}/cartoes?regenerar=true) só passava pelos
alunos ATIVOS (``alunos_da_turma``): o cartão de quem estava arquivado, transferido ou
fora da Lista Piloto ficava com o mesmo código, o mesmo QR e o mesmo
``token_version``, e a auditoria não dizia quem ficou de fora. O individual com
``?regenerar=true`` respondia 422 antes de tocar na credencial. Quando a ficha voltava
a "ativo" (botão Reativar ou, sem decisão humana, a Lista Piloto seguinte), o cartão
"revogado" e o JWT de 30 dias emitido antes voltavam a entrar.

Agora, quando a revogação é PEDIDA (``regenerar`` ou ``rotacionar_codigo``):
  * o regenerar da turma revoga também o cartão dos inativos que têm credencial (fora
    do PDF) e a auditoria registra ``revogados_inativos``;
  * o individual de ficha inativa revoga sem emitir cartão: 204, sem PDF, auditado
    como ``quest.cartao_revogado_inativo``;
  * a reativação não reabre o código, o QR nem as sessões antigas.
Sem revogação pedida nada muda ("cartão descansando"): a reimpressão de inativo segue
422 e a criança que volta continua com o mesmo cartão.

Regressão do achado da dimensão rodadas-recentes-acesso (integração 5 do e97; provas
test_prova_1 e test_prova_101, invertidas). Dados fictícios (fixture escola_completa).
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.config import PROJECT_ROOT
from app.main import app
from app.models import Aluno, LogAuditoria
from app.quest.models import QuestCredencialAluno
from app.quest.routers import auth as quest_auth
from tests.test_permissoes import cenario_professor  # fixture

ENTRAR = "/api/v1/quest/auth/entrar"
ENTRAR_QR = "/api/v1/quest/auth/entrar-qr"
PERFIL = "/api/v1/quest/perfil"


def _cred(db, aluno_id) -> QuestCredencialAluno | None:
    db.expire_all()
    return db.execute(select(QuestCredencialAluno)
                      .where(QuestCredencialAluno.aluno_id == aluno_id)).scalar_one_or_none()


def _cartao(cred: QuestCredencialAluno) -> tuple:
    return cred.codigo_login, cred.qr_token, cred.token_version


def _status(db, aluno_id, valor):
    """O que a Lista Piloto grava (fora_lista_piloto) e o que ela faz ao reativar
    quem volta a constar (status = "ativo"), sem passar por ninguém."""
    db.expire_all()
    db.get(Aluno, aluno_id).status = valor
    db.commit()


def _base(escola_completa) -> str:
    return f"/api/v1/escolas/{escola_completa['escola'].id}/quest"


def _turma(cliente, escola_completa, consulta=""):
    r = cliente.post(f"{_base(escola_completa)}/turmas/"
                     f"{escola_completa['turma'].id}/cartoes{consulta}")
    assert r.status_code == 200, r.text
    return r


def _individual(cliente, escola_completa, aluno_id, consulta=""):
    return cliente.post(f"{_base(escola_completa)}/alunos/{aluno_id}/cartao{consulta}")


def _entrar(codigo):
    return TestClient(app).post(ENTRAR, json={"codigo": codigo})


def _qr(token):
    return TestClient(app).post(ENTRAR_QR, json={"qr_token": token})


def _perfil(jwt):
    return TestClient(app).get(PERFIL, headers={"Authorization": f"Bearer {jwt}"})


def _ultimo_log(db, acao) -> LogAuditoria:
    db.expire_all()
    return db.execute(select(LogAuditoria).where(LogAuditoria.acao == acao)
                      .order_by(LogAuditoria.id.desc())).scalars().first()


@pytest.fixture
def cartao_em_maos_erradas(cliente, db, escola_completa):
    """Cartões da turma impressos; o do 2º aluno (X) abre a sessão do intruso."""
    _turma(cliente, escola_completa)
    x = escola_completa["alunos"][1].id
    codigo, qr, ver = _cartao(_cred(db, x))
    r = _entrar(codigo)
    assert r.status_code == 200, r.text
    return {"x": x, "codigo": codigo, "qr": qr, "ver": ver, "jwt": r.json()["access_token"]}


def _o_cartao_antigo_nao_entra(c):
    assert _entrar(c["codigo"]).status_code == 401
    assert _qr(c["qr"]).status_code == 401
    assert _perfil(c["jwt"]).status_code == 401


# --- 1. Regenerar a TURMA revoga também o cartão de quem está inativo ----------------

def test_regenerar_turma_revoga_o_inativo_e_a_lista_piloto_nao_reabre(
        cliente, db, escola_completa, cartao_em_maos_erradas):
    c = cartao_em_maos_erradas
    _status(db, c["x"], "fora_lista_piloto")
    # Enquanto inativo, a criança ouve "cartão descansando" (barreira pelo status).
    r = _entrar(c["codigo"])
    assert r.status_code == 403 and r.json()["detail"] == quest_auth.ERRO_INATIVO

    _turma(cliente, escola_completa, "?regenerar=true")

    novo = _cred(db, c["x"])
    assert novo.codigo_login != c["codigo"] and novo.qr_token != c["qr"]
    assert novo.token_version == c["ver"] + 1
    for colega in (escola_completa["alunos"][0].id, escola_completa["alunos"][2].id):
        assert _cred(db, colega).token_version == 1              # os ativos, como antes
    log = _ultimo_log(db, "quest.cartoes_gerados")
    # O inativo continua matriculado na turma: não conta como quem saiu dela.
    assert log.detalhes == {"alunos": 2, "regenerou": True, "rotacionou_codigo": True,
                            "revogados_inativos": 1, "revogados_fora_da_turma": 0,
                            "revogados_fora_da_turma_ids": [],
                            "aluno_ids": [escola_completa["alunos"][0].id,
                                          escola_completa["alunos"][2].id]}
    # Ainda inativo: o código antigo já não existe (401); o novo dá "descansando".
    assert _entrar(c["codigo"]).status_code == 401
    assert _entrar(novo.codigo_login).status_code == 403

    _status(db, c["x"], "ativo")                    # a Lista Piloto seguinte reativa

    _o_cartao_antigo_nao_entra(c)
    r = _entrar(novo.codigo_login)
    assert r.status_code == 200, r.text
    assert _perfil(r.json()["access_token"]).status_code == 200


def test_arquivar_regenerar_e_reativar_pelo_botao_nao_reabre(
        cliente, db, escola_completa, cartao_em_maos_erradas):
    """O caminho da prova 1: arquivar e reativar pela tela de Alunos."""
    c = cartao_em_maos_erradas
    acoes = f"/api/v1/escolas/{escola_completa['escola'].id}/alunos/acoes"
    assert cliente.post(acoes, json={"aluno_ids": [c["x"]], "acao": "arquivar"}).status_code == 200

    _turma(cliente, escola_completa, "?regenerar=true")

    assert _cartao(_cred(db, c["x"])) != (c["codigo"], c["qr"], c["ver"])
    assert cliente.post(acoes, json={"aluno_ids": [c["x"]], "acao": "reativar"}).status_code == 200
    _o_cartao_antigo_nao_entra(c)


def test_rotacionar_codigo_da_turma_tambem_revoga_os_inativos(
        cliente, db, escola_completa, cartao_em_maos_erradas):
    c = cartao_em_maos_erradas
    _status(db, c["x"], "transferido")
    _turma(cliente, escola_completa, "?rotacionar_codigo=true")
    assert _cred(db, c["x"]).token_version == c["ver"] + 1
    assert _ultimo_log(db, "quest.cartoes_gerados").detalhes["revogados_inativos"] == 1
    _status(db, c["x"], "ativo")
    _o_cartao_antigo_nao_entra(c)


def test_varios_inativos_da_turma_ganham_codigos_distintos(cliente, db, escola_completa):
    _turma(cliente, escola_completa)
    ids = [a.id for a in escola_completa["alunos"]]
    antes = {i: _cartao(_cred(db, i)) for i in ids}
    for i in ids:
        _status(db, i, "arquivado")

    _turma(cliente, escola_completa, "?regenerar=true")

    depois = {i: _cred(db, i) for i in ids}
    assert all(depois[i].codigo_login != antes[i][0] for i in ids)
    assert len({d.codigo_login for d in depois.values()}) == 3
    assert all(d.token_version == 1 for d in depois.values())
    assert _ultimo_log(db, "quest.cartoes_gerados").detalhes == {
        "alunos": 0, "regenerou": True, "rotacionou_codigo": True, "revogados_inativos": 3,
        "revogados_fora_da_turma": 0, "revogados_fora_da_turma_ids": [], "aluno_ids": []}


def test_inativo_sem_credencial_nao_ganha_cartao_no_regenerar(cliente, db, escola_completa):
    x = escola_completa["alunos"][0].id
    _status(db, x, "arquivado")
    _turma(cliente, escola_completa, "?regenerar=true")
    assert _cred(db, x) is None
    assert _ultimo_log(db, "quest.cartoes_gerados").detalhes["revogados_inativos"] == 0


# --- 2. O individual de ficha inativa revoga sem emitir cartão -----------------------

@pytest.mark.parametrize("consulta", ["?regenerar=true", "?rotacionar_codigo=true"])
def test_individual_de_inativo_revoga_sem_pdf(cliente, db, escola_completa,
                                              cartao_em_maos_erradas, consulta):
    c = cartao_em_maos_erradas
    colega = escola_completa["alunos"][0].id
    colega_antes = _cartao(_cred(db, colega))
    _status(db, c["x"], "fora_lista_piloto")

    r = _individual(cliente, escola_completa, c["x"], consulta)

    assert r.status_code == 204, r.text
    assert r.content == b""                                     # nenhum cartão emitido
    novo = _cred(db, c["x"])
    assert novo.codigo_login != c["codigo"] and novo.qr_token != c["qr"]
    assert novo.token_version == c["ver"] + 1
    assert _cartao(_cred(db, colega)) == colega_antes           # a turma não cai
    log = _ultimo_log(db, "quest.cartao_revogado_inativo")
    assert log.entidade_id == c["x"]
    assert log.detalhes == {"regenerou": consulta == "?regenerar=true",
                            "rotacionou_codigo": True, "status_aluno": "fora_lista_piloto"}
    assert _ultimo_log(db, "quest.cartao_individual") is None   # não houve PDF

    _status(db, c["x"], "ativo")
    _o_cartao_antigo_nao_entra(c)
    # Reativada, a ficha volta a receber cartão (a reimpressão sai com o código novo).
    r = _individual(cliente, escola_completa, c["x"])
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert _cartao(_cred(db, c["x"])) == _cartao(novo)


def test_individual_de_inativo_sem_credencial_da_422_e_nao_cria(cliente, db,
                                                               escola_completa):
    x = escola_completa["alunos"][0].id
    _status(db, x, "arquivado")
    r = _individual(cliente, escola_completa, x, "?regenerar=true")
    assert r.status_code == 422 and r.json()["detail"] == "Aluno inativo não recebe cartão."
    assert _cred(db, x) is None
    assert db.scalar(select(func.count()).select_from(LogAuditoria)
                     .where(LogAuditoria.acao.like("quest.%"))) == 0


# --- 3. Sem revogação pedida nada muda ("cartão descansando") ------------------------

def test_reimpressao_nao_revoga_o_inativo_e_a_crianca_volta_com_o_mesmo_cartao(
        cliente, db, escola_completa, cartao_em_maos_erradas):
    c = cartao_em_maos_erradas
    _status(db, c["x"], "fora_lista_piloto")

    r = _individual(cliente, escola_completa, c["x"])
    assert r.status_code == 422 and r.json()["detail"] == "Aluno inativo não recebe cartão."
    _turma(cliente, escola_completa)                            # reimpressão da turma
    assert _cartao(_cred(db, c["x"])) == (c["codigo"], c["qr"], c["ver"])
    assert _ultimo_log(db, "quest.cartoes_gerados").detalhes["revogados_inativos"] == 0

    _status(db, c["x"], "ativo")
    assert _entrar(c["codigo"]).status_code == 200
    assert _qr(c["qr"]).status_code == 200
    assert _perfil(c["jwt"]).status_code == 200


# --- 4. Professor restrito: só o inativo da turma dele ------------------------------

def test_professor_revoga_o_inativo_da_turma_dele_e_nao_o_de_outra(cenario_professor, db):
    c = cenario_professor
    base = f"/api/v1/escolas/{c['escola'].id}/quest"
    dele, fora = c["aluno_da_turma"].id, c["aluno_fora"].id
    for aluno_id in (dele, fora):
        assert c["coordenador"].post(f"{base}/alunos/{aluno_id}/cartao").status_code == 200
    antes_fora = _cartao(_cred(db, fora))
    for aluno_id in (dele, fora):
        _status(db, aluno_id, "arquivado")

    r = c["professor"].post(f"{base}/alunos/{dele}/cartao?regenerar=true")
    assert r.status_code == 204, r.text
    assert _cred(db, dele).token_version == 1

    r = c["professor"].post(f"{base}/alunos/{fora}/cartao?regenerar=true")
    assert r.status_code == 404                                  # turma de outro professor
    assert _cartao(_cred(db, fora)) == antes_fora


# --- 5. A documentação de suporte diz o que o sistema faz ---------------------------

def _plano(rel: str) -> str:
    texto = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
    return " ".join(texto.replace("**", "").replace("`", "").split())


def test_bible_21_e_apendice_b_dizem_que_regenerar_revoga_o_inativo():
    """A árvore de decisão mandava "nunca tentar regenerar (o sistema recusa com
    422)" para ficha inativa — a orientação que deixava o cartão perdido valendo."""
    secao = _plano("docs/bible/21-suporte-operacao.md")
    assert "nunca tentar regenerar" not in secao and "never try to regenerate" not in secao
    assert "quest.cartao_revogado_inativo" in secao and "revogados_inativos" in secao
    assert secao.count("não reabre o código, o QR nem as sessões antigas") == 1
    assert secao.count("does not reopen the old code, QR or sessions") == 1
    apendice = _plano("docs/bible/apendice-B-api-dados.md")
    individual = [linha.split(" | 🟢")[0] for linha in apendice.split(" | POST | ")[1:]
                  if linha.startswith("/escolas/{escola_id}/quest/alunos/{aluno_id}/cartao")]
    assert len(individual) == 2                                   # PT e EN
    assert all("204" in linha for linha in individual), individual
    assert apendice.count("revogados_inativos") == 2
