"""A etapa de deploy que invalida a senha derivada do nome também tira os aparelhos
(push) da conta (observação do AUTH-1, fase B).

``professores.invalidar_senhas_derivadas`` troca a senha pública (o nome/@ + "123")
por uma que ninguém conhece e sobe o ``token_version`` — as sessões caem —, mas o
aparelho registrado para push seguia cadastrado. A senha era pública: qualquer um que
soubesse o nome entrava e registrava o próprio celular, que seguia recebendo os avisos
da escola (com o primeiro nome da criança) depois da invalidação. As outras
substituições de senha (troca pelo admin e redefinição pelo link) já apagavam os
aparelhos. A auditoria da etapa segue com os mesmos campos ({"uso", "origem"}).

Contas e tokens fictícios."""
from sqlalchemy import func, select

from app.core.security import hash_senha
from app.models import DispositivoMovel, LogAuditoria, Usuario
from app.services import professores as svc


def _conta(db, escola, nome, username, senha, token):
    u = Usuario(escola_id=escola.id, nome=nome, email=f"{username.lower()}@legado.local",
                username=username, senha_hash=hash_senha(senha), cargo="professor")
    db.add(u)
    db.flush()
    db.add(DispositivoMovel(escola_id=escola.id, usuario_id=u.id, token_push=token,
                            plataforma="android"))
    db.flush()
    return u


def _aparelhos(db, usuario_id: int) -> int:
    return db.execute(select(func.count()).select_from(DispositivoMovel)
                      .where(DispositivoMovel.usuario_id == usuario_id)).scalar_one()


def test_invalidar_a_senha_derivada_tira_os_aparelhos_da_conta(db, escola_completa):
    escola = escola_completa["escola"]
    derivada = _conta(db, escola, "Telma Varoni", "TelmaVaroni", "telmavaroni123",
                      "ExponentPushToken[ficticio-derivada-0001]")
    escolhida = _conta(db, escola, "Iara Ficticia Propria", "IaraPropria",
                       "uma-senha-escolhida-77", "ExponentPushToken[ficticio-propria-0001]")
    db.commit()

    diagnostico = svc.invalidar_senhas_derivadas(db, escola.id)       # só lê
    db.commit()
    assert diagnostico["aplicado"] is False
    assert _aparelhos(db, derivada.id) == 1

    r = svc.invalidar_senhas_derivadas(db, escola.id, aplicar=True)
    db.commit()
    assert r["invalidadas"] == 1
    assert _aparelhos(db, derivada.id) == 0            # o aparelho saiu com as sessões
    assert _aparelhos(db, escolhida.id) == 1           # quem não foi tocado fica
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "usuario.senha_derivada_invalidada")).scalars().one()
    assert log.entidade_id == derivada.id
    assert set(log.detalhes) == {"uso", "origem"}


def test_senha_trocada_durante_a_execucao_nao_perde_o_aparelho(db, escola_completa):
    """Compare-and-set: quem trocou a senha no meio não é tocado — nem o aparelho."""
    escola = escola_completa["escola"]
    u = _conta(db, escola, "Telma Varoni", "TelmaVaroni", "telmavaroni123",
               "ExponentPushToken[ficticio-trocada-0001]")
    db.commit()
    classificacao = svc.classificar_senhas_derivadas(db, escola.id)
    u.senha_hash = hash_senha("trocou-no-meio-da-etapa-31")
    db.commit()

    r = svc.invalidar_senhas_derivadas(db, escola.id, aplicar=True,
                                       classificacao=classificacao)
    db.commit()
    assert r["invalidadas"] == 0 and len(r["trocadas_durante"]) == 1
    assert _aparelhos(db, u.id) == 1
