"""Lado do professor (consumido pelo Edu web): cartões de acesso da turma.

Permissões idênticas às demais rotas do Edu: papel validado no backend e
isolamento por escola via escola_autorizada.
"""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import escola_autorizada, exigir_papeis
from app.models import Escola, Turma, Usuario
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
    """Gera (ou regenera) credenciais da turma e devolve o PDF dos cartões.

    `regenerar=true` troca PIN + QR de TODOS os alunos da turma e derruba as
    sessões antigas — use para cartões perdidos/comprometidos.
    """
    turma = _turma_da_escola(db, escola_id, turma_id)
    dados = svc.garantir_credenciais_turma(db, escola_id, turma,
                                           regenerar=regenerar)

    figuras = {f["slug"]: f for f in svc.FIGURAS_PIN}
    cartoes = [{
        "nome": item["aluno"].nome,
        "apelido": item["perfil"].apelido,
        "codigo": item["credencial"].codigo_login,
        "pin": [figuras.get(slug, {"nome": slug})
                for slug in (item["credencial"].pin_figuras or [])],
        "qr_url": svc.url_qr(item["credencial"]),
    } for item in dados]

    escola = db.get(Escola, escola_id)
    pdf = cartoes_pdf.gerar_cartoes_pdf(
        escola_nome=escola.nome if escola else "Escola",
        cor=svc_relatorios.cor_primaria(db, escola_id),
        turma_nome=turma.nome,
        cartoes=cartoes,
    )

    registrar(db, "quest.cartoes_gerados", escola_id=escola_id,
              usuario_id=usuario.id, entidade="turma", entidade_id=turma.id,
              detalhes={"alunos": len(cartoes), "regenerou": regenerar})
    db.commit()

    # Cabeçalho HTTP só aceita ASCII: "3º Ano A" → "3-ano-a"
    import unicodedata

    slug = unicodedata.normalize("NFKD", turma.nome).encode("ascii", "ignore")
    slug = "-".join(slug.decode().lower().split()) or "turma"
    nome_arquivo = f"cartoes-quest-{slug}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'},
    )
