"""Certificados EM LOTE (identidade visual v2, decisão D7): o MESMO certificado da
rota individual ``GET /escolas/{id}/certificados/{aluno_id}``, para até 50 alunos.

* ``POST /certificados/lote/previa`` — roda as guardas de cada aluno, sem gerar PDF e
  sem auditoria, e diz quem está apto e o motivo de cada recusa;
* ``POST /certificados/lote`` — UM PDF com uma página por aluno APTO, na ordem pedida,
  e a auditoria ``certificado.emitido`` de cada um, como a rota individual.

As guardas NÃO são cópia: são as funções da rota individual
(``relatorios.exigir_modulo_do_modelo``, ``preparar_certificado``, ``exigir_merito`` e
``conteudo_certificado``), na mesma ordem — módulo do modelo (403, para o pedido
inteiro), aluno da escola e do professor (404), situação ativa, turma de 1º a 5º ano e
Lista Piloto (409) e, só no Geral, mérito (409/422). O fallback também é o dela, aluno a
aluno: se a arte da plataforma falhar, cai no Geral com as guardas de mérito.

RECUSADO NÃO É SUBSTITUÍDO. Quem pede "os 5 primeiros" e tem um recusado recebe 4
certificados, não o 6º colocado: trocar a criança mudaria quem foi premiado.

A recusa "aluno não encontrado/não permitido" (404) volta com ``nome`` e ``turma``
nulos: o id de um aluno de outra escola, ou de outra turma para o professor, não pode
devolver o nome dele.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import escola_autorizada, negar_secretaria
from app.models import Aluno, Escola, Matricula, Turma, Usuario
from app.routers import relatorios as emissao
from app.schemas.certificados_lote import LoteIn, PreviaLoteIn, PreviaLoteOut
from app.services import certificados_lote as svc_lote

router = APIRouter(prefix="/escolas/{escola_id}", tags=["Relatórios"])

logger = logging.getLogger("constela.certificados_lote")

NENHUM_APTO = "Nenhum aluno apto para o certificado."


def _apto(preparo: emissao.PreparoCertificado) -> dict:
    return {"aluno_id": preparo.aluno.id, "nome": preparo.aluno.nome,
            "turma": preparo.turma_nome, "apto": True, "motivo": None}


def _recusado(db: Session, escola: Escola, aluno_id: int, exc: HTTPException) -> dict:
    """O item de um aluno recusado, com o motivo da rota individual (o mesmo texto do
    409/422 dela). Nome e turma só quando o aluno é desta escola E visível a quem pede
    — o 404 é exatamente o caso em que não é."""
    item = {"aluno_id": aluno_id, "nome": None, "turma": None, "apto": False,
            "motivo": str(exc.detail)}
    if exc.status_code == status.HTTP_404_NOT_FOUND:
        return item
    aluno = db.get(Aluno, aluno_id)
    if aluno is None or aluno.escola_id != escola.id:   # defensivo: não acontece
        return item
    turma = db.execute(
        select(Turma.nome)
        .join(Matricula, Matricula.turma_id == Turma.id)
        .where(Matricula.aluno_id == aluno_id,
               Matricula.ano_letivo == escola.ano_letivo_ativo)).first()
    item["nome"] = aluno.nome
    item["turma"] = turma[0] if turma is not None else None
    return item


@router.post("/certificados/lote/previa", response_model=PreviaLoteOut)
def previa_certificados_lote(
    pedido: PreviaLoteIn,
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(negar_secretaria),
):
    """Quem do lote recebe o certificado e por que os outros não — as MESMAS guardas
    da emissão, sem gerar PDF e sem gravar nada. Ordem dos itens = ordem pedida.

    Nas artes das plataformas (participação) a guarda de mérito não vale, como na rota
    individual; no Geral (``modelo`` nulo) vale."""
    escola = db.get(Escola, escola_id)
    emissao.exigir_modulo_do_modelo(db, escola, pedido.modelo)
    itens = []
    for aluno_id in pedido.aluno_ids:
        try:
            preparo = emissao.preparar_certificado(db, escola, usuario, aluno_id)
            if pedido.modelo is None:
                emissao.exigir_merito(db, preparo)
        except HTTPException as exc:
            itens.append(_recusado(db, escola, aluno_id, exc))
            continue
        itens.append(_apto(preparo))
    return {"modelo": pedido.modelo, "itens": itens}


@router.post(
    "/certificados/lote",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}},
                     "description": "Um PDF com uma página por aluno apto"},
               422: {"description": "Nenhum aluno apto (com os itens da prévia)"}})
def certificados_lote(
    pedido: LoteIn,
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(negar_secretaria),
):
    """UM PDF com o certificado de cada aluno APTO, na ordem pedida, e a auditoria
    ``certificado.emitido`` de cada um. Nenhum apto → 422 com os itens da prévia.

    A geração é síncrona (um Chromium por certificado, ~1,5 s cada medido em
    31/10/2026): o teto de 50 alunos é o que mantém a resposta num tempo aceitável."""
    escola = db.get(Escola, escola_id)
    emissao.exigir_modulo_do_modelo(db, escola, pedido.modelo)
    itens, emitidos, documentos = [], [], []
    for aluno_id in pedido.aluno_ids:
        try:
            preparo = emissao.preparar_certificado(db, escola, usuario, aluno_id)
            conteudo = emissao.conteudo_certificado(db, preparo, pedido.modelo,
                                                    pedido.bimestre)
        except HTTPException as exc:
            itens.append(_recusado(db, escola, aluno_id, exc))
            continue
        itens.append(_apto(preparo))
        emitidos.append(aluno_id)
        documentos.append(conteudo)
    if not documentos:
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            content={"detail": NENHUM_APTO, "itens": itens})
    pdf = svc_lote.juntar_pdfs(documentos)
    for aluno_id in emitidos:
        emissao.registrar_emissao(db, escola_id, usuario, aluno_id, pedido.modelo,
                                  detalhes_extra={"lote": True})
    db.commit()
    if len(emitidos) < len(pedido.aluno_ids):
        logger.info("lote de certificados: %d de %d emitidos",
                    len(emitidos), len(pedido.aluno_ids))
    nome = f"certificados_{pedido.modelo or 'geral'}_{len(emitidos)}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )
