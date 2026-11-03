"""Push com o primeiro nome de UMA criança só vai a quem a enxerga pela API (revisão
independente dados-lgpd, d4caac4).

Antes, ``notificar_escola`` mandava o aviso "<Primeiro nome> teve os dados..." (resolução
de uma pendência de identidade com dados) para TODO aparelho ativo da escola — inclusive
o professor de outra turma, que recebe lista vazia e perfil 404 para a criança, e a conta
da Secretaria, que nunca vê dado individual. O nome aparecia na tela bloqueada deles.

Agora o aviso de uma criança leva ``aluno_id`` e só vai à gestão da escola e ao professor
de uma turma dela (a régua de ``permissoes.exigir_aluno_permitido``). O aviso da escola
inteira ("N alunos"), sem ``aluno_id``, continua indo a todo aparelho ativo.

Dados 100% fictícios (mesmo caminho real de tests/test_push_sem_nome_completo.py)."""
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_senha
from app.main import app
from app.models import (
    Aluno, DispositivoMovel, Matricula, Professor, Rede, RevisaoIdentidade, Turma, Usuario,
)
from app.routers import importacoes as imp
from app.schemas.importacao import ImportacaoConfirm, LinhaConfirmacao
from app.services import push

NOME = "ZULEICA PROVA FICTICIA SOUZA"
TOKENS = {"outro": "ExponentPushToken[escopo-outra-0001]",
          "dela": "ExponentPushToken[escopo-dela-0001]",
          "gestao": "ExponentPushToken[escopo-gestao-0001]",
          "secretaria": "ExponentPushToken[escopo-secretaria-0001]"}


def _login(email, senha):
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", data={"username": email, "password": senha})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _capturar(monkeypatch) -> list[dict]:
    enviados: list[dict] = []
    monkeypatch.setattr(push, "_enviar_lotes",
                        lambda lotes: [enviados.extend(lote) for lote in lotes] and [])
    return enviados


def test_push_de_uma_crianca_so_para_quem_a_ve(db, cliente, escola_completa, monkeypatch):
    esc, admin = escola_completa["escola"], escola_completa["admin"]
    outro = Professor(escola_id=esc.id, nome="Professor Outra",
                      email="prof.outra@escopo-push.local")
    dela = Professor(escola_id=esc.id, nome="Professor Dela",
                     email="prof.dela@escopo-push.local")
    db.add_all([outro, dela])
    db.flush()
    escola_completa["turma"].professor_id = outro.id
    for p in (outro, dela):
        db.add(Usuario(escola_id=esc.id, nome=p.nome, email=p.email,
                       senha_hash=hash_senha("s3nh4push"), cargo="professor"))
    rede = Rede(nome="REDE FICTICIA ESCOPO PUSH", status="ativa")
    db.add(rede)
    db.flush()
    esc.rede_id = rede.id
    secretaria = Usuario(escola_id=esc.id, rede_id=rede.id, nome="Secretaria Ficticia",
                         email="sec@escopo-push.local", senha_hash=hash_senha("s3nh4push"),
                         cargo="coordenador")
    db.add(secretaria)
    turma = Turma(escola_id=esc.id, nome="5ºA", ano_escolar="5º Ano", ano_letivo=2026,
                  professor_id=dela.id)
    db.add(turma)
    db.flush()
    aluna = Aluno(escola_id=esc.id, nome=NOME, status="ativo")
    db.add(aluna)
    db.flush()
    db.add(Matricula(escola_id=esc.id, aluno_id=aluna.id, turma_id=turma.id,
                     ano_letivo=2026))
    db.add(DispositivoMovel(escola_id=esc.id, usuario_id=secretaria.id,
                            token_push=TOKENS["secretaria"], plataforma="android"))
    db.commit()

    for chave, email in (("outro", outro.email), ("dela", dela.email)):
        r = _login(email, "s3nh4push").post(f"/api/v1/escolas/{esc.id}/dispositivos",
                                            json={"token_push": TOKENS[chave],
                                                  "plataforma": "android"})
        assert r.status_code == 200, r.text
    r = cliente.post(f"/api/v1/escolas/{esc.id}/dispositivos",
                     json={"token_push": TOKENS["gestao"], "plataforma": "ios"})
    assert r.status_code == 200, r.text

    # Nome parcial (sem o último sobrenome) → pendência de revisão, com os dados.
    linha = LinhaConfirmacao(
        nome="ZULEICA PROVA FICTICIA", criar_em_turma_nome="5ºA",
        dados={"turma_relatorio": "5ºA", "livros_unicos": 7, "tempo_leitura_min": 40,
               "questoes_tentativas": 5, "questoes_acertos": 4,
               "elefante_student_id": "990078"})
    imp.confirmar(dados=ImportacaoConfirm(plataforma="elefante", formato="resumo",
                                          tipo="texto", linhas=[linha], recalcular=False),
                  escola_id=esc.id, usuario=admin, db=db)
    rev = db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == esc.id,
        RevisaoIdentidade.status == "pendente")).scalars().one()

    enviados = _capturar(monkeypatch)
    r = cliente.post(f"/api/v1/escolas/{esc.id}/importacoes/revisoes/{rev.id}/resolver",
                     json={"aluno_id": aluna.id})
    assert r.status_code == 200, r.text

    destinos = {m["to"] for m in enviados}
    assert TOKENS["outro"] not in destinos          # outra turma: lista vazia, perfil 404
    assert TOKENS["secretaria"] not in destinos     # nunca vê dado individual
    assert destinos == {TOKENS["dela"], TOKENS["gestao"]}
    assert all(m["body"].startswith("Zuleica teve os dados") for m in enviados)


def test_push_da_escola_inteira_continua_para_todos(db, escola_completa, monkeypatch):
    esc = escola_completa["escola"]
    db.add(DispositivoMovel(escola_id=esc.id, usuario_id=escola_completa["admin"].id,
                            token_push="ExponentPushToken[escopo-todos-0001]",
                            plataforma="android"))
    db.commit()
    enviados = _capturar(monkeypatch)
    assert push.notificar_escola(db, esc.id, "t", "3 alunos atualizados") == 1
    assert [m["to"] for m in enviados] == ["ExponentPushToken[escopo-todos-0001]"]
