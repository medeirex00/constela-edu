"""Lado do professor (consumido pelo Edu web): cartões de acesso.

Permissões idênticas às demais rotas do Edu: papel validado no backend e
isolamento por escola via escola_autorizada.
"""
import unicodedata

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import escola_autorizada, exigir_papeis
from app.models import Aluno, Escola, Turma, Usuario
from app.quest import schemas
from app.quest.models import QuestCredencialAluno, QuestPerfil
from app.quest.services import cartoes_pdf
from app.quest.services import credenciais as svc
from app.services import relatorios as svc_relatorios
from app.services.audit import registrar

router = APIRouter(prefix="/escolas/{escola_id}/quest",
                   tags=["Quest — Professor"])

PODE_GERAR = exigir_papeis("admin", "coordenador", "professor")


def _turma_da_escola(db: Session, escola_id: int, turma_id: int) -> Turma:
    turma = db.get(Turma, turma_id)
    if turma is None or turma.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Turma não encontrada.")
    return turma


def _slug_ascii(texto: str) -> str:
    # Cabeçalho HTTP só aceita ASCII: "3º Ano A" → "3-ano-a"
    limpo = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore")
    return "-".join(limpo.decode().lower().split()) or "turma"


def _resposta_pdf(pdf: bytes, nome_arquivo: str) -> Response:
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'},
    )


def _montar_cartoes(dados: list[dict]) -> list[dict]:
    return [{
        "nome": item["aluno"].nome,
        "apelido": item["perfil"].apelido,
        "codigo": item["credencial"].codigo_login,
        "qr_url": svc.url_qr(item["credencial"]),
    } for item in dados]


@router.get("/turmas/{turma_id}/acessos",
            response_model=list[schemas.AcessoAlunoOut])
def acessos_da_turma(turma_id: int,
                     escola_id: int = Depends(escola_autorizada),
                     usuario: Usuario = Depends(PODE_GERAR),
                     db: Session = Depends(get_db)):
    """Situação de acesso de cada aluno — alimenta a tela do Edu."""
    turma = _turma_da_escola(db, escola_id, turma_id)
    saida: list[schemas.AcessoAlunoOut] = []
    for aluno in svc.alunos_da_turma(db, escola_id, turma):
        credencial = db.execute(
            select(QuestCredencialAluno)
            .where(QuestCredencialAluno.aluno_id == aluno.id)
        ).scalar_one_or_none()
        perfil = db.execute(
            select(QuestPerfil).where(QuestPerfil.aluno_id == aluno.id)
        ).scalar_one_or_none()
        saida.append(schemas.AcessoAlunoOut(
            aluno_id=aluno.id,
            nome=aluno.nome,
            nome_exibicao=perfil.nome_exibicao if perfil else None,
            apelido=perfil.apelido if perfil else None,
            codigo_login=credencial.codigo_login if credencial else None,
            ultimo_acesso=credencial.ultimo_acesso if credencial else None,
            tem_credencial=credencial is not None,
        ))
    return saida


@router.post("/turmas/{turma_id}/cartoes")
def gerar_cartoes(turma_id: int,
                  regenerar: bool = False,
                  escola_id: int = Depends(escola_autorizada),
                  usuario: Usuario = Depends(PODE_GERAR),
                  db: Session = Depends(get_db)):
    """Gera (ou regenera) credenciais da turma e devolve o PDF dos cartões
    + a página "só do professor" (tabela nome → código e roteiro da 1ª aula).

    `regenerar=true` troca o QR de TODOS os alunos da turma e derruba as
    sessões antigas — use apenas se cartões caírem em mãos erradas.
    """
    turma = _turma_da_escola(db, escola_id, turma_id)
    dados = svc.garantir_credenciais_turma(db, escola_id, turma,
                                           regenerar=regenerar)
    escola = db.get(Escola, escola_id)
    pdf = cartoes_pdf.gerar_cartoes_pdf(
        escola_nome=escola.nome if escola else "Escola",
        cor=svc_relatorios.cor_primaria(db, escola_id),
        turma_nome=turma.nome,
        cartoes=_montar_cartoes(dados),
    )

    registrar(db, "quest.cartoes_gerados", escola_id=escola_id,
              usuario_id=usuario.id, entidade="turma", entidade_id=turma.id,
              detalhes={"alunos": len(dados), "regenerou": regenerar})
    db.commit()
    return _resposta_pdf(pdf, f"cartoes-quest-{_slug_ascii(turma.nome)}.pdf")


@router.post("/alunos/{aluno_id}/cartao")
def gerar_cartao_individual(aluno_id: int,
                            regenerar: bool = False,
                            escola_id: int = Depends(escola_autorizada),
                            usuario: Usuario = Depends(PODE_GERAR),
                            db: Session = Depends(get_db)):
    """Cartão de UM aluno — cartão perdido não derruba a turma inteira."""
    aluno = db.get(Aluno, aluno_id)
    if aluno is None or aluno.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aluno não encontrado.")
    if aluno.status != "ativo":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Aluno inativo não recebe cartão.")

    item = svc.garantir_credencial_aluno(db, escola_id, aluno,
                                         regenerar=regenerar)
    escola = db.get(Escola, escola_id)
    pdf = cartoes_pdf.gerar_cartoes_pdf(
        escola_nome=escola.nome if escola else "Escola",
        cor=svc_relatorios.cor_primaria(db, escola_id),
        turma_nome="",
        cartoes=_montar_cartoes([item]),
        com_pagina_professor=False,
    )

    registrar(db, "quest.cartao_individual", escola_id=escola_id,
              usuario_id=usuario.id, entidade="aluno", entidade_id=aluno.id,
              detalhes={"regenerou": regenerar})
    db.commit()
    return _resposta_pdf(pdf, f"cartao-quest-{_slug_ascii(aluno.nome)}.pdf")
