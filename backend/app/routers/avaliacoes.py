"""Avaliações externas — catálogo e importação de resultados oficiais.

MVP: importação de ARQUIVO oficial (XLSX/CSV) — nenhuma das fontes (SAEB/IDEB/
SARESP/Criança Alfabetizada) tem API self-serve. Fluxo: `analisar` mostra a grade
crua (o gestor escolhe a linha de dados e mapeia as colunas), `importar` grava
casando escola por CÓDIGO INEP. Só admin/coordenador; o alcance segue o perfil
(global = todas; rede = escolas da rede; escola = a própria).
"""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import exigir_papeis, get_usuario_atual
from app.models import AvaliacaoExterna, Escola, Usuario
from app.services import avaliacoes as svc
from app.services.audit import registrar

router = APIRouter(prefix="/avaliacoes", tags=["Avaliações externas"])

_MAX_BYTES = 25 * 1024 * 1024  # planilhas oficiais cabem folgado; barra abuso


def _escopo_escolas(db: Session, usuario: Usuario) -> set[int] | None:
    """Escolas que este usuário pode gravar resultado: None = todas (global);
    conjunto = escolas da rede (Secretaria) ou a própria escola; vazio = nada."""
    if usuario.is_global:
        return None
    if usuario.rede_id is not None:
        return set(db.execute(
            select(Escola.id).where(Escola.rede_id == usuario.rede_id)).scalars())
    if usuario.escola_id is not None:
        return {usuario.escola_id}
    return set()


@router.get("")
def catalogo(usuario: Usuario = Depends(get_usuario_atual), db: Session = Depends(get_db)):
    """Catálogo de avaliações/indicadores (materializa o catálogo inicial)."""
    for chave in svc.CATALOGO:
        svc.obter_avaliacao(db, chave)
    db.commit()
    return [
        {"chave": a.chave, "nome": a.nome, "tipo": a.tipo, "orgao": a.orgao,
         "descricao": a.descricao}
        for a in db.execute(
            select(AvaliacaoExterna).order_by(AvaliacaoExterna.tipo, AvaliacaoExterna.nome)
        ).scalars()
    ]


# Endpoints SÍNCRONOS de propósito: o parse (openpyxl) e a gravação são CPU/DB
# bound; como `def` (não `async def`), o FastAPI os roda numa thread do pool, sem
# travar o event loop durante um arquivo grande. Por isso lemos o arquivo pelo
# objeto síncrono (arquivo.file.read()).

@router.post("/analisar")
def analisar(
    arquivo: UploadFile = File(...),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
):
    """Prévia: grade crua das primeiras linhas — a tela usa para escolher a linha
    de dados e mapear as colunas (por índice). Robusto a pré-âmbulo/edição."""
    conteudo = arquivo.file.read(_MAX_BYTES + 1)  # limitado: o teto limita a RAM
    if len(conteudo) > _MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            "Arquivo muito grande. Extraia/reduza a planilha antes de subir.")
    return svc.analisar_planilha(conteudo, arquivo.filename or "")


@router.post("/importar")
def importar(
    arquivo: UploadFile = File(...),
    avaliacao: str = Form(...),
    edicao: int = Form(...),
    indicador: str = Form(...),
    unidade: str = Form(...),
    linha_dados: int = Form(...),
    col_inep: int = Form(...),
    col_valor: int = Form(...),
    col_etapa: int | None = Form(None),
    col_componente: int | None = Form(None),
    col_turma: int | None = Form(None),
    etapa_fixa: str | None = Form(None),
    componente_fixo: str | None = Form(None),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
    db: Session = Depends(get_db),
):
    """Importa os resultados casando escola por CÓDIGO INEP (dentro do alcance do
    perfil). Idempotente por (avaliação, edição, indicador, escola, etapa,
    componente, turma). Só grava os níveis que o arquivo fornece."""
    if avaliacao not in svc.CATALOGO:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Avaliação desconhecida: {avaliacao}.")
    if linha_dados < 0 or col_inep < 0 or col_valor < 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Mapeamento inválido.")
    conteudo = arquivo.file.read(_MAX_BYTES + 1)  # limitado: o teto limita a RAM
    if len(conteudo) > _MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Arquivo muito grande.")

    resultado = svc.importar_resultados(
        db, conteudo, arquivo.filename or "",
        avaliacao_chave=avaliacao, edicao=edicao, indicador=indicador, unidade=unidade,
        linha_dados=linha_dados, col_inep=col_inep, col_valor=col_valor,
        col_etapa=col_etapa, col_componente=col_componente, col_turma=col_turma,
        etapa_fixa=etapa_fixa, componente_fixo=componente_fixo,
        escopo_escolas=_escopo_escolas(db, usuario))
    registrar(db, "avaliacao.importada", usuario_id=usuario.id,
              entidade="avaliacao_externa", detalhes=resultado)
    db.commit()
    return resultado
