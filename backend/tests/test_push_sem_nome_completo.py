"""Push sem o NOME COMPLETO da criança (auditoria de 20/10/2026).

Ao resolver uma pendência de identidade com dados, a escola recebia no celular:
"<nome completo> teve os dados da plataforma atualizados." — na tela bloqueada,
passando pelo Expo e pelo FCM/APNs. Agora vai só o primeiro nome, com o mesmo
sentido.
"""
from sqlalchemy import select

from app.models import Matricula, RevisaoIdentidade, Turma
from app.models import Aluno
from app.routers import importacoes as imp
from app.schemas.importacao import ImportacaoConfirm, LinhaConfirmacao
from app.services import push

NOME_COMPLETO = "ALUNA TESTE EXEMPLO SOUZA"


def test_corpo_leva_so_o_primeiro_nome():
    corpo = push.corpo_dados_atualizados(NOME_COMPLETO)
    assert corpo.startswith("Aluna teve os dados da plataforma atualizados.")
    for sobrenome in ("TESTE", "EXEMPLO", "SOUZA"):
        assert sobrenome.casefold() not in corpo.casefold()


def test_corpo_sem_nome_continua_fazendo_sentido():
    assert push.corpo_dados_atualizados("").startswith("Um aluno teve os dados")
    assert push.corpo_dados_atualizados(None).startswith("Um aluno teve os dados")
    assert push.primeiro_nome("  maria   eduarda  ") == "Maria"


def test_resolver_pendencia_envia_push_sem_o_nome_completo(db, cliente, escola_completa,
                                                          monkeypatch):
    """Caminho real: a pendência resolvida com dados dispara o push."""
    esc, admin = escola_completa["escola"], escola_completa["admin"]
    turma = Turma(escola_id=esc.id, nome="5ºA", ano_escolar="5º Ano", ano_letivo=2026)
    db.add(turma)
    db.flush()
    aluna = Aluno(escola_id=esc.id, nome=NOME_COMPLETO, status="ativo")
    db.add(aluna)
    db.flush()
    db.add(Matricula(escola_id=esc.id, aluno_id=aluna.id, turma_id=turma.id,
                     ano_letivo=2026))
    db.commit()

    # Nome parcial (sem o último sobrenome) → pendência de revisão, com os dados.
    linha = LinhaConfirmacao(
        nome="ALUNA TESTE EXEMPLO", criar_em_turma_nome="5ºA",
        dados={"turma_relatorio": "5ºA", "livros_unicos": 7, "tempo_leitura_min": 40,
               "questoes_tentativas": 5, "questoes_acertos": 4,
               "elefante_student_id": "990011"})
    imp.confirmar(dados=ImportacaoConfirm(plataforma="elefante", formato="resumo",
                                          tipo="texto", linhas=[linha], recalcular=False),
                  escola_id=esc.id, usuario=admin, db=db)
    rev = db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == esc.id,
        RevisaoIdentidade.status == "pendente")).scalars().one()

    enviados = []
    alvos = []   # o aviso é de UMA criança: vai com o aluno_id (recorte por quem a vê)
    monkeypatch.setattr(push, "notificar_escola",
                        lambda db_, escola_id, titulo, corpo, dados=None, aluno_id=None:
                        enviados.append((titulo, corpo)) or alvos.append(aluno_id) or 0)
    r = cliente.post(f"/api/v1/escolas/{esc.id}/importacoes/revisoes/{rev.id}/resolver",
                     json={"aluno_id": aluna.id})
    assert r.status_code == 200, r.text

    assert enviados, "a resolução com dados tem de avisar a escola"
    for titulo, corpo in enviados:
        texto = f"{titulo} {corpo}".casefold()
        assert NOME_COMPLETO.casefold() not in texto
        assert "souza" not in texto and "exemplo" not in texto
    assert any(corpo.startswith("Aluna teve os dados") for _, corpo in enviados)
    assert alvos == [aluna.id] * len(enviados)
