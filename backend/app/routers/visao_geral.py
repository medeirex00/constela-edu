"""Visão Geral da escola (identidade visual v2): indicadores do período e atividade
semanal. SÓ LEITURA, sem migração, sem auditoria por visualização e sem lista de
alunos — a regra de cada número está em ``services/visao_geral``.

Permissões, como as rotas vizinhas do Relatório por Período:
* ``escola_autorizada`` — usuário de escola só vê a própria escola;
* ``negar_secretaria`` — a Secretaria acompanha a REDE pelo boletim consolidado, não
  opera a tela da escola (declarada na rota e também no registro do router);
* professor: o recorte das turmas dele (``permissoes.turmas_permitidas``) vale para a
  coorte inteira — denominador, ativos e somas;
* módulo fora do plano da rede: o bloco dele sai ``contratado=false`` e sem números.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import escola_autorizada, negar_secretaria
from app.core.tempo import hoje_br
from app.models import Escola, Usuario
from app.schemas.visao_geral import AtividadeSemanalOut, VisaoGeralOut
from app.services import modulos as svc_modulos
from app.services import permissoes
from app.services import visao_geral as svc

router = APIRouter(prefix="/escolas/{escola_id}", tags=["Visão geral"])


@router.get("/visao-geral", response_model=VisaoGeralOut)
def visao_geral(
    periodo: str = Query(default="bimestre", max_length=32,
                         description="bimestre | bimestre_1..4 | mes | semana | "
                                     "ano_letivo (e os demais presets com início e "
                                     "fim de `periodos`)"),
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(negar_secretaria),
):
    """Alunos ativos (por plataforma e a união), livros novos, tempo de leitura e
    atividades do Matific no período — e os mesmos números na MESMA quantidade de
    dias desde o início do período anterior (``comparacao``), quando há um anterior
    equivalente e as duas janelas estão medidas. Sem coleta, ``null`` (nunca 0)."""
    escola = db.get(Escola, escola_id)
    try:
        return svc.visao_geral(
            db, escola, preset=periodo,
            modulos=svc_modulos.modulos_da_escola(db, escola),
            turma_ids=permissoes.turmas_permitidas(db, escola_id, usuario),
            hoje=hoje_br())
    except svc.PedidoInvalido as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.get("/atividade-semanal", response_model=AtividadeSemanalOut)
def atividade_semanal(
    semanas: int = Query(default=8, ge=svc.SEMANAS_MIN, le=svc.SEMANAS_MAX),
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(negar_secretaria),
):
    """Percentual da coorte com atividade em cada semana (segunda a domingo), por
    plataforma, da mais antiga à corrente (parcial). Semana sem coleta = ``null``
    (lacuna no gráfico), nunca 0; ``denominador`` declara a base do percentual."""
    escola = db.get(Escola, escola_id)
    try:
        return svc.atividade_semanal(
            db, escola, semanas=semanas,
            modulos=svc_modulos.modulos_da_escola(db, escola),
            turma_ids=permissoes.turmas_permitidas(db, escola_id, usuario),
            hoje=hoje_br())
    except svc.PedidoInvalido as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
