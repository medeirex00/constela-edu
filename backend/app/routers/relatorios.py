"""Exportação de relatórios e certificados (PRD §86–§103).

Cada exportação também deixa uma cópia em /exports e um registro no log.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import escola_autorizada, get_usuario_atual
from app.models import Aluno, Escola, Matricula, Nota, Turma, Usuario
from app.services import relatorios as svc
from app.services.audit import registrar

router = APIRouter(prefix="/escolas/{escola_id}", tags=["Relatórios"])

FORMATOS = {
    "csv": ("text/csv; charset=utf-8", "csv"),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    "pdf": ("application/pdf", "pdf"),
}


@router.get("/relatorios/{tipo}")
def exportar_relatorio(
    tipo: str,
    formato: str = Query(pattern="^(csv|xlsx|pdf)$"),
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    if tipo not in svc.FONTES:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            f"Relatórios disponíveis: {', '.join(sorted(svc.FONTES))}.")
    escola = db.get(Escola, escola_id)
    titulo, fonte = svc.FONTES[tipo]
    cabecalho, linhas = fonte(db, escola_id)
    cor = svc.cor_primaria(db, escola_id)

    if formato == "csv":
        conteudo = svc.gerar_csv(cabecalho, linhas)
    elif formato == "xlsx":
        conteudo = svc.gerar_xlsx(titulo, escola.nome, cor, cabecalho, linhas)
    else:
        conteudo = svc.gerar_pdf(titulo, escola.nome, cor, cabecalho, linhas)

    media_type, extensao = FORMATOS[formato]
    momento = datetime.now(timezone.utc)
    nome_arquivo = f"{tipo}_{momento:%Y%m%d_%H%M%S}.{extensao}"

    # Cópia local em /exports (PRD: relatórios gerados ficam disponíveis)
    destino = settings.EXPORTS_DIR
    destino.mkdir(parents=True, exist_ok=True)
    (destino / nome_arquivo).write_bytes(conteudo)

    registrar(db, "relatorio.exportado", escola_id=escola_id, usuario_id=usuario.id,
              detalhes={"tipo": tipo, "formato": formato, "linhas": len(linhas)})
    db.commit()

    return Response(
        content=conteudo,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'},
    )


@router.get("/certificados/{aluno_id}")
def certificado(
    aluno_id: int,
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Certificado individual em PDF (PRD §99)."""
    escola = db.get(Escola, escola_id)
    aluno = db.get(Aluno, aluno_id)
    if aluno is None or aluno.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aluno não encontrado.")

    matricula = db.execute(
        select(Matricula, Turma)
        .join(Turma, Matricula.turma_id == Turma.id)
        .where(Matricula.aluno_id == aluno_id,
               Matricula.ano_letivo == escola.ano_letivo_ativo)
    ).first()
    nota = db.execute(
        select(Nota).where(Nota.aluno_id == aluno_id,
                           Nota.ano_letivo == escola.ano_letivo_ativo)
    ).scalar_one_or_none()

    conteudo = svc.gerar_certificado(
        escola_nome=escola.nome,
        cor=svc.cor_primaria(db, escola_id),
        aluno_nome=aluno.nome,
        turma=matricula[1].nome if matricula else "",
        posicao=nota.posicao if nota else None,
        nota_geral=nota.nota_geral if nota else 0.0,
        ano_letivo=escola.ano_letivo_ativo,
    )
    registrar(db, "certificado.emitido", escola_id=escola_id, usuario_id=usuario.id,
              entidade="aluno", entidade_id=aluno_id)
    db.commit()
    return Response(
        content=conteudo,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="certificado_{aluno_id}.pdf"'},
    )
