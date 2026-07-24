"""Exportação de relatórios e certificados (PRD §86–§103).

Cada exportação também deixa uma cópia em /exports e um registro no log.
"""
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import escola_autorizada, get_usuario_atual
from app.models import Aluno, Escola, Matricula, Nota, Turma, Usuario
from app.services import permissoes
from app.services import relatorios as svc
from app.services.audit import registrar

router = APIRouter(prefix="/escolas/{escola_id}", tags=["Relatórios"])

logger = logging.getLogger("constela.relatorios")


def _expurgar_exports_antigos() -> None:
    """Remove cópias de relatórios além da retenção (LGPD/minimização — contêm
    nomes de alunos). Chamado a cada nova exportação — barato e evita acúmulo
    indefinido de PII em disco. EXPORTS_RETENCAO_DIAS=0 desliga."""
    dias = settings.EXPORTS_RETENCAO_DIAS
    if dias <= 0 or not settings.EXPORTS_DIR.exists():
        return
    limite = time.time() - dias * 86_400
    for arquivo in settings.EXPORTS_DIR.iterdir():
        # Preserva dotfiles de infraestrutura (ex.: .gitkeep) — só expurga as
        # cópias de relatórios de fato.
        if arquivo.name.startswith("."):
            continue
        try:
            if arquivo.is_file() and arquivo.stat().st_mtime < limite:
                arquivo.unlink(missing_ok=True)
        except OSError:
            pass


def _arquivar_copia(nome_arquivo: str, conteudo: bytes) -> None:
    """Cópia local em /exports — MELHOR ESFORÇO: se o disco não for gravável,
    o download segue normal (o arquivo vai na resposta); só a cópia é pulada.
    Expurga cópias antigas na mesma passada (retenção — não acumula PII)."""
    try:
        settings.EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
        _expurgar_exports_antigos()
        (settings.EXPORTS_DIR / nome_arquivo).write_bytes(conteudo)
    except OSError:
        logger.warning("Sem acesso de escrita em %s — relatório enviado, cópia "
                       "local não arquivada.", settings.EXPORTS_DIR)

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

    # Professor: só o relatório SUPERFICIAL (ranking) e apenas das turmas dele.
    permitidas = permissoes.turmas_permitidas(db, escola_id, usuario)
    if permitidas is not None:
        if tipo not in ("ranking", "alunos"):
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                "Seu perfil exporta apenas o ranking e a lista "
                                "de alunos das suas turmas.")
        nomes_turmas = {t.nome for t in db.execute(
            select(Turma).where(Turma.id.in_(permitidas))).scalars()}
        try:
            idx_turma = next(i for i, c in enumerate(cabecalho)
                             if c.strip().lower().startswith("turma"))
        except StopIteration:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                "Relatório indisponível para o seu perfil.")
        linhas = [l for l in linhas if str(l[idx_turma]) in nomes_turmas]
    cor = svc.cor_primaria(db, escola_id)

    if formato == "csv":
        conteudo = svc.gerar_csv(cabecalho, linhas)
    elif formato == "xlsx":
        conteudo = svc.gerar_xlsx(titulo, escola.nome, cor, cabecalho, linhas)
    elif tipo == "ranking" and permitidas is None:
        # PDF do Ranking Geral = o CARTAZ (pôster) de vitrine, com todos os
        # alunos. Só para gestão; professor restrito segue com o PDF simples
        # das suas turmas (cai no else).
        conteudo = svc.gerar_cartaz_ranking(
            escola.nome, cor, escola.ano_letivo_ativo, cabecalho, linhas,
            svc.estatisticas_cartaz(db, escola_id),
            logos=svc.logos_da_escola(db, escola_id))
    elif tipo == "alunos":
        conteudo = svc.gerar_lista_alunos_pdf(
            escola.nome, cor, escola.ano_letivo_ativo, cabecalho, linhas,
            logos=svc.logos_da_escola(db, escola_id))
    elif tipo == "livros":
        conteudo = svc.gerar_catalogo_livros_pdf(
            escola.nome, cor, escola.ano_letivo_ativo, cabecalho, linhas,
            logos=svc.logos_da_escola(db, escola_id))
    else:
        conteudo = svc.gerar_pdf(titulo, escola.nome, cor, cabecalho, linhas)

    media_type, extensao = FORMATOS[formato]
    momento = datetime.now(timezone.utc)
    nome_arquivo = f"{tipo}_{momento:%Y%m%d_%H%M%S}.{extensao}"

    _arquivar_copia(nome_arquivo, conteudo)

    registrar(db, "relatorio.exportado", escola_id=escola_id, usuario_id=usuario.id,
              detalhes={"tipo": tipo, "formato": formato, "linhas": len(linhas)})
    db.commit()

    return Response(
        content=conteudo,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'},
    )


@router.get("/ranking/cartaz")
def cartaz_ranking(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Cartaz (pôster) do Ranking Geral em PDF — TODOS os alunos, paginado.
    Documento de vitrine (gestão apenas): moldura Constela + logos da cidade,
    medalhas para o pódio e cartões de estatística."""
    permissoes.negar_restrito(db, escola_id, usuario)
    escola = db.get(Escola, escola_id)
    cabecalho, linhas = svc.linhas_ranking(db, escola_id)
    conteudo = svc.gerar_cartaz_ranking(
        escola_nome=escola.nome,
        cor=svc.cor_primaria(db, escola_id),
        ano_letivo=escola.ano_letivo_ativo,
        cabecalho=cabecalho,
        linhas=linhas,
        estatisticas=svc.estatisticas_cartaz(db, escola_id),
        logos=svc.logos_da_escola(db, escola_id),
    )
    momento = datetime.now(timezone.utc)
    nome_arquivo = f"ranking_cartaz_{momento:%Y%m%d_%H%M%S}.pdf"
    _arquivar_copia(nome_arquivo, conteudo)
    registrar(db, "relatorio.exportado", escola_id=escola_id, usuario_id=usuario.id,
              detalhes={"tipo": "ranking_cartaz", "formato": "pdf", "linhas": len(linhas)})
    db.commit()
    return Response(
        content=conteudo,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'},
    )


@router.get("/certificados/{aluno_id}")
def certificado(
    aluno_id: int,
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_usuario_atual),
):
    """Certificado individual em PDF (PRD §99). Professor: só dos seus alunos."""
    escola = db.get(Escola, escola_id)
    aluno = db.get(Aluno, aluno_id)
    if aluno is None or aluno.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aluno não encontrado.")
    permissoes.exigir_aluno_permitido(db, escola_id, escola.ano_letivo_ativo,
                                      usuario, aluno_id)

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
        logos=svc.logos_da_escola(db, escola_id),
    )
    registrar(db, "certificado.emitido", escola_id=escola_id, usuario_id=usuario.id,
              entidade="aluno", entidade_id=aluno_id)
    db.commit()
    return Response(
        content=conteudo,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="certificado_{aluno_id}.pdf"'},
    )
