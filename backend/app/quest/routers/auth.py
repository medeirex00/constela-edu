"""Entrada do aluno no Quest: código falável (SEM senha) ou QR do cartão.

Fluxo em duas etapas: a criança digita o código, vê o próprio nome/avatar
("É você?") e confirma — errar o código nunca a joga na conta de outra
pessoa sem perceber. O código é a credencial (decisão de produto, como no
Elefante Letrado); a defesa contra abuso é o limitador por (código, IP).
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rate_limit import LimitadorTentativas, ip_do_cliente
from app.quest import schemas
from app.quest.models import QuestCredencialAluno
from app.quest.services import credenciais as svc
from app.quest.services import perfis as svc_perfis
from app.services.audit import registrar

router = APIRouter(prefix="/quest/auth", tags=["Quest — Autenticação"])

# Chaveado por (código, IP): o erro de digitação de uma criança nunca pune a
# turma inteira atrás do NAT da escola (um único IP público para 30 tablets).
limitador_codigo = LimitadorTentativas(max_tentativas=8, janela_s=300)
# Teto largo por IP só contra enumeração em massa — dimensionado para o
# pior caso legítimo: uma sala inteira errando o código algumas vezes.
limitador_ip = LimitadorTentativas(max_tentativas=300, janela_s=300)
# Por CÓDIGO (sem IP): freia adivinhação de UM código específico mesmo com o
# atacante trocando de IP. Seguro: acertar o código já dá acesso (é a
# credencial), então travá-lo não é pior que o modelo de produto atual.
limitador_codigo_conta = LimitadorTentativas(max_tentativas=20, janela_s=900)

ERRO_CODIGO = "Não encontrei esse código. Confira o cartão e tente de novo!"
ERRO_INATIVO = ("Seu cartão está descansando! Peça um cartão novo "
                "na sua escola.")
ERRO_MUITAS = "Ufa, quantas tentativas! Descanse um pouquinho e tente de novo."


def _montar_perfil(credencial: QuestCredencialAluno, perfil,
                   aluno) -> schemas.PerfilOut:
    saida = schemas.PerfilOut.model_validate(perfil)
    saida.nome_exibicao = (perfil.nome_exibicao or "").strip()
    saida.nome = svc_perfis.nome_para_falas(perfil, aluno.nome)
    saida.codigo_login = credencial.codigo_login
    if credencial.ultimo_acesso is not None:
        delta = datetime.now(timezone.utc) - credencial.ultimo_acesso.replace(
            tzinfo=credencial.ultimo_acesso.tzinfo or timezone.utc)
        saida.dias_sem_jogar = max(0, delta.days)
    return saida


def _checar_credencial(credencial: QuestCredencialAluno | None,
                       falha_conta) -> QuestCredencialAluno:
    """404/401 para código inexistente; mensagem PRÓPRIA (e sem contar no
    limitador) para aluno inativo — a criança que decorou o código não pode
    achar que errou ela: transferência/arquivamento não é culpa dela."""
    if credencial is None or credencial.aluno is None:
        falha_conta()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, ERRO_CODIGO)
    if credencial.aluno.status != "ativo":
        raise HTTPException(status.HTTP_403_FORBIDDEN, ERRO_INATIVO)
    return credencial


def _sessao(db: Session, credencial: QuestCredencialAluno, request: Request,
            via: str) -> schemas.SessaoOut:
    aluno = credencial.aluno
    perfil = svc_perfis.obter_ou_criar_perfil(db, aluno)
    primeira_vez = credencial.ultimo_acesso is None
    saida_perfil = _montar_perfil(credencial, perfil, aluno)
    credencial.ultimo_acesso = datetime.now(timezone.utc)
    registrar(db, "quest.login", escola_id=credencial.escola_id,
              entidade="aluno", entidade_id=aluno.id,
              detalhes={"via": via, "ip": ip_do_cliente(request)})
    db.commit()
    return schemas.SessaoOut(
        access_token=svc.criar_token_aluno(credencial),
        primeira_vez=primeira_vez,
        perfil=saida_perfil,
    )


def _limites(request: Request, chave_conta: str) -> tuple[str, str]:
    ip = ip_do_cliente(request)
    chave = f"{chave_conta}|{ip}"
    if (limitador_ip.bloqueado(ip) or limitador_codigo.bloqueado(chave)
            or limitador_codigo_conta.bloqueado(chave_conta)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, ERRO_MUITAS)
    return ip, chave


@router.post("/quem", response_model=schemas.QuemOut)
def quem(dados: schemas.QuemIn, request: Request, db: Session = Depends(get_db)):
    """Etapa 1 — "É você?": devolve nome/avatar do dono do código."""
    codigo = svc.normalizar_codigo(dados.codigo)
    ip, chave = _limites(request, codigo)

    def falhou():
        limitador_codigo.registrar_falha(chave)
        limitador_codigo_conta.registrar_falha(codigo)
        limitador_ip.registrar_falha(ip)

    credencial = _checar_credencial(svc.buscar_por_codigo(db, codigo), falhou)
    perfil = svc_perfis.obter_ou_criar_perfil(db, credencial.aluno)
    db.commit()
    return schemas.QuemOut(
        nome=svc_perfis.nome_para_falas(perfil, credencial.aluno.nome),
        apelido=perfil.apelido,
        avatar=perfil.avatar or {},
    )


@router.post("/entrar", response_model=schemas.SessaoOut)
def entrar(dados: schemas.EntrarIn, request: Request,
           db: Session = Depends(get_db)):
    """Etapa 2 — cria a sessão do aluno (o código é a credencial)."""
    codigo = svc.normalizar_codigo(dados.codigo)
    ip, chave = _limites(request, codigo)

    def falhou():
        limitador_codigo.registrar_falha(chave)
        limitador_codigo_conta.registrar_falha(codigo)
        limitador_ip.registrar_falha(ip)
        registrar(db, "quest.login_falhou",
                  detalhes={"codigo": codigo, "ip": ip})
        db.commit()

    credencial = _checar_credencial(svc.buscar_por_codigo(db, codigo), falhou)
    limitador_codigo.limpar(chave)
    limitador_codigo_conta.limpar(codigo)
    return _sessao(db, credencial, request, via="codigo")


@router.post("/entrar-qr", response_model=schemas.SessaoOut)
def entrar_qr(dados: schemas.EntrarQrIn, request: Request,
              db: Session = Depends(get_db)):
    ip, chave = _limites(request, dados.qr_token[:16])

    def falhou():
        limitador_codigo.registrar_falha(chave)
        limitador_codigo_conta.registrar_falha(dados.qr_token[:16])
        limitador_ip.registrar_falha(ip)

    credencial = svc.buscar_por_qr(db, dados.qr_token)
    if credencial is None or credencial.aluno is None:
        falhou()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "Esse QR não funcionou. Peça um cartão novo!")
    if credencial.aluno.status != "ativo":
        raise HTTPException(status.HTTP_403_FORBIDDEN, ERRO_INATIVO)
    return _sessao(db, credencial, request, via="qr")
