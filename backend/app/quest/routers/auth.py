"""Entrada do aluno no Quest: código falável + PIN de figuras, ou QR.

Fluxo em duas etapas (docs/quest/04): a criança digita o código, vê o
próprio nome/avatar ("É você?") e só então toca as 4 figuras — errar o
código nunca a joga numa tela de senha de outra pessoa.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rate_limit import LimitadorTentativas, ip_do_cliente
from app.quest import schemas
from app.quest.services import credenciais as svc
from app.quest.services import perfis as svc_perfis
from app.services.audit import registrar

router = APIRouter(prefix="/quest/auth", tags=["Quest — Autenticação"])

# O PIN tem espaço pequeno (12×11×10×9 ≈ 11,9 mil ordens): o limitador é a
# defesa real. 6 tentativas por 10 min por (código, IP) trava adivinhação
# sem punir a criança que confunde a ordem das figuras.
limitador_pin = LimitadorTentativas(max_tentativas=6, janela_s=600)
# Descoberta de códigos válidos ("quem é SOL-1234?"): 30 consultas/5min por IP.
limitador_quem = LimitadorTentativas(max_tentativas=30, janela_s=300)

ERRO_CODIGO = "Não encontrei esse código. Confira o cartão e tente de novo!"
ERRO_PIN = "As figuras não bateram. Olhe seu cartão e tente de novo!"


def _primeiro_nome(nome: str) -> str:
    return (nome or "").strip().split(" ")[0].title()


def _montar_perfil(perfil, aluno) -> schemas.PerfilOut:
    saida = schemas.PerfilOut.model_validate(perfil)
    saida.primeiro_nome = _primeiro_nome(aluno.nome)
    return saida


def _sessao(db: Session, credencial, request: Request, via: str) -> schemas.SessaoOut:
    aluno = credencial.aluno
    perfil = svc_perfis.obter_ou_criar_perfil(db, aluno)
    credencial.ultimo_acesso = datetime.now(timezone.utc)
    registrar(db, "quest.login", escola_id=credencial.escola_id,
              entidade="aluno", entidade_id=aluno.id,
              detalhes={"via": via, "ip": ip_do_cliente(request)})
    db.commit()
    return schemas.SessaoOut(
        access_token=svc.criar_token_aluno(credencial),
        perfil=_montar_perfil(perfil, aluno),
    )


@router.get("/figuras", response_model=list[schemas.FiguraOut])
def figuras():
    """Catálogo das figuras do PIN (público: a tela de entrada precisa dele)."""
    return svc.FIGURAS_PIN


@router.post("/quem", response_model=schemas.QuemOut)
def quem(dados: schemas.QuemIn, request: Request, db: Session = Depends(get_db)):
    ip = ip_do_cliente(request)
    if limitador_quem.bloqueado(ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "Calma, astronauta! Espere um pouquinho e tente de novo.")
    credencial = svc.buscar_por_codigo(db, dados.codigo)
    if credencial is None or credencial.aluno is None \
            or credencial.aluno.status != "ativo":
        limitador_quem.registrar_falha(ip)
        raise HTTPException(status.HTTP_404_NOT_FOUND, ERRO_CODIGO)
    perfil = svc_perfis.obter_ou_criar_perfil(db, credencial.aluno)
    db.commit()
    return schemas.QuemOut(
        primeiro_nome=_primeiro_nome(credencial.aluno.nome),
        apelido=perfil.apelido,
        avatar=perfil.avatar or {},
    )


@router.post("/entrar", response_model=schemas.SessaoOut)
def entrar(dados: schemas.EntrarIn, request: Request, db: Session = Depends(get_db)):
    ip = ip_do_cliente(request)
    codigo = svc.normalizar_codigo(dados.codigo)
    chave = f"{codigo}|{ip}"

    if limitador_pin.bloqueado(chave):
        espera = limitador_pin.segundos_restantes(chave)
        registrar(db, "quest.login_bloqueado", detalhes={"codigo": codigo, "ip": ip})
        db.commit()
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Muitas tentativas! Descanse {max(1, espera // 60)} minutinho(s) "
            "e tente de novo.")

    credencial = svc.buscar_por_codigo(db, codigo)
    if credencial is None or credencial.aluno is None \
            or credencial.aluno.status != "ativo":
        limitador_pin.registrar_falha(chave)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, ERRO_CODIGO)

    if not svc.pin_confere(credencial, dados.pin):
        limitador_pin.registrar_falha(chave)
        registrar(db, "quest.login_falhou", escola_id=credencial.escola_id,
                  entidade="aluno", entidade_id=credencial.aluno_id,
                  detalhes={"ip": ip, "motivo": "pin_incorreto"})
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, ERRO_PIN)

    limitador_pin.limpar(chave)
    return _sessao(db, credencial, request, via="codigo_pin")


@router.post("/entrar-qr", response_model=schemas.SessaoOut)
def entrar_qr(dados: schemas.EntrarQrIn, request: Request,
              db: Session = Depends(get_db)):
    ip = ip_do_cliente(request)
    if limitador_quem.bloqueado(ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "Calma, astronauta! Espere um pouquinho e tente de novo.")
    credencial = svc.buscar_por_qr(db, dados.qr_token)
    if credencial is None or credencial.aluno is None \
            or credencial.aluno.status != "ativo":
        limitador_quem.registrar_falha(ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "Esse QR não funcionou. Peça um cartão novo!")
    return _sessao(db, credencial, request, via="qr")
