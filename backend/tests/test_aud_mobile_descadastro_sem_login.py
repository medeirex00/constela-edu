"""'Sair' do app descadastra o aparelho do push mesmo sem a sessão (auditoria
técnica, MOBILE-3 — parte do servidor).

O único jeito de o app tirar o aparelho do push era ``POST /escolas/{id}/
dispositivos/remover``, que exige o login. No "Sair da conta" sem rede (ou com a API
fora) a chamada falhava, o app apagava o JWT logo depois e nenhuma nova tentativa
conseguia se autenticar; na sessão expirada (401) nem dava para tentar. O aparelho
seguia cadastrado para uma conta ATIVA e continuava recebendo, na tela bloqueada,
"<primeiro nome da criança> teve os dados da plataforma atualizados".

Agora há ``POST /escolas/{id}/dispositivos/descadastrar``, que só pede o
``token_push`` — o segredo do próprio aparelho, que só o app dele conhece — e
funciona sem login (e com sessão expirada), para o app chamar na hora e repetir
depois, quando a rede voltar. A resposta é a mesma exista o token ou não (não diz
quais aparelhos estão cadastrados) e há limite de tentativas por IP.

Envio ao Expo trocado por uma captura (sem rede). Dados 100% fictícios.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_senha
from app.main import app
from app.models import (
    Aluno, DispositivoMovel, LogAuditoria, Matricula, Professor, Turma, Usuario,
)
from app.routers import mobile
from app.services import push

API = "/api/v1"
TOKEN_PROF = "ExponentPushToken[ficticio-sair-0001]"
TOKEN_OUTRO = "ExponentPushToken[ficticio-sair-0002]"


@pytest.fixture(autouse=True)
def _limitador_limpo():
    mobile.limitador_descadastro._eventos.clear()
    yield
    mobile.limitador_descadastro._eventos.clear()


@pytest.fixture()
def cenario(db, escola_completa):
    """Professora com uma turma e uma aluna, e o aparelho dela cadastrado pelo app."""
    esc = escola_completa["escola"]
    prof = Professor(escola_id=esc.id, nome="Professora Ficticia",
                     email="prof.sair@teste.local")
    db.add(prof)
    db.flush()
    turma = Turma(escola_id=esc.id, nome="5º Ano B", ano_escolar="5º Ano",
                  ano_letivo=2026, professor_id=prof.id)
    db.add(turma)
    db.flush()
    aluna = Aluno(escola_id=esc.id, nome="ANA FICTICIA DA SILVA", status="ativo")
    db.add(aluna)
    db.flush()
    db.add(Matricula(escola_id=esc.id, aluno_id=aluna.id, turma_id=turma.id,
                     ano_letivo=2026))
    db.add(Usuario(escola_id=esc.id, nome=prof.nome, email=prof.email,
                   senha_hash=hash_senha("Senha-Prof-Sair-1"), cargo="professor"))
    db.commit()
    sessao = TestClient(app)
    r = sessao.post(f"{API}/auth/login",
                    data={"username": prof.email, "password": "Senha-Prof-Sair-1"})
    assert r.status_code == 200, r.text
    sessao.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    r = sessao.post(f"{API}/escolas/{esc.id}/dispositivos",
                    json={"token_push": TOKEN_PROF, "plataforma": "android"})
    assert r.status_code == 200, r.text
    return {"escola": esc, "aluna": aluna}


def _destinos_do_aviso_da_aluna(db, cenario, monkeypatch) -> list[str]:
    enviados: list[str] = []
    monkeypatch.setattr(push, "_enviar_lotes",
                        lambda lotes: [enviados.extend(m["to"] for m in lote)
                                       for lote in lotes] and [])
    aluna = cenario["aluna"]
    push.notificar_escola(db, cenario["escola"].id, "Novos dados",
                          push.corpo_dados_atualizados(aluna.nome), aluno_id=aluna.id)
    return enviados


def test_sair_sem_sessao_descadastra_e_o_push_para(db, cenario, monkeypatch):
    # Controle: cadastrado, o aparelho recebe o aviso com o primeiro nome.
    assert _destinos_do_aviso_da_aluna(db, cenario, monkeypatch) == [TOKEN_PROF]

    # "Sair da conta" depois que o JWT já foi apagado (ou expirou): sem login.
    anonimo = TestClient(app)
    r = anonimo.post(f"{API}/escolas/{cenario['escola'].id}/dispositivos/descadastrar",
                     json={"token_push": TOKEN_PROF})
    assert r.status_code == 200, r.text
    assert _destinos_do_aviso_da_aluna(db, cenario, monkeypatch) == []
    db.expire_all()
    assert db.query(DispositivoMovel).count() == 0
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "dispositivo.descadastrado")).scalars().one()
    assert log.detalhes["sem_login"] is True


def test_sessao_expirada_nao_impede_o_descadastro(db, cenario):
    """O app que levou 401 ainda manda o JWT velho: o descadastro não depende dele."""
    vencido = TestClient(app)
    vencido.headers["Authorization"] = "Bearer token.expirado.ficticio"
    r = vencido.post(f"{API}/escolas/{cenario['escola'].id}/dispositivos/descadastrar",
                     json={"token_push": TOKEN_PROF})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.query(DispositivoMovel).count() == 0


def test_vale_para_o_aparelho_mesmo_com_outra_escola_na_rota(db, cenario,
                                                             escola_completa):
    """A escola da rota é a que o app tinha aberta; o aparelho pode ter sido
    cadastrado noutra (o admin troca de escola no app sem novo cadastro). O token é
    único: sai de onde estiver, como no ``/remover``."""
    r = TestClient(app).post(f"{API}/escolas/999999/dispositivos/descadastrar",
                             json={"token_push": TOKEN_PROF})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.query(DispositivoMovel).count() == 0


def test_token_desconhecido_tem_a_mesma_resposta_e_nao_apaga_outro(db, cenario):
    url = f"{API}/escolas/{cenario['escola'].id}/dispositivos/descadastrar"
    anonimo = TestClient(app)
    conhecido_antes = anonimo.post(url, json={"token_push": TOKEN_OUTRO})
    assert conhecido_antes.status_code == 200
    db.expire_all()
    assert [d.token_push for d in db.query(DispositivoMovel).all()] == [TOKEN_PROF]
    repetido = anonimo.post(url, json={"token_push": TOKEN_PROF})
    de_novo = anonimo.post(url, json={"token_push": TOKEN_PROF})   # reenvio da fila
    assert repetido.status_code == de_novo.status_code == 200
    assert conhecido_antes.json() == repetido.json() == de_novo.json()


def test_limite_de_tentativas_por_ip(db, cenario):
    url = f"{API}/escolas/{cenario['escola'].id}/dispositivos/descadastrar"
    anonimo = TestClient(app)
    teto = mobile.limitador_descadastro.max_tentativas
    for i in range(teto):
        r = anonimo.post(url, json={"token_push": f"ExponentPushToken[chute-{i:04d}]"})
        assert r.status_code == 200, (i, r.text)
    r = anonimo.post(url, json={"token_push": TOKEN_PROF})
    assert r.status_code == 429, r.text
    assert int(r.headers["Retry-After"]) > 0
    db.expire_all()
    assert db.query(DispositivoMovel).count() == 1      # bloqueado não apaga nada


def test_remover_com_login_continua_como_antes(db, cliente, escola_completa):
    """Controle: o ``/remover`` autenticado segue valendo."""
    eid = escola_completa["escola"].id
    cliente.post(f"{API}/escolas/{eid}/dispositivos",
                 json={"token_push": TOKEN_OUTRO, "plataforma": "ios"})
    r = cliente.post(f"{API}/escolas/{eid}/dispositivos/remover",
                     json={"token_push": TOKEN_OUTRO})
    assert r.status_code == 200
    db.expire_all()
    assert db.query(DispositivoMovel).filter_by(token_push=TOKEN_OUTRO).count() == 0
