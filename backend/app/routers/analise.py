"""Análise educacional integrada — SÓ LEITURA (nenhuma rota aqui grava nada).

* ``GET /redes/{id}/analise/indicadores`` — o catálogo dos indicadores oficiais da rede
  (disponibilidade, edições, metas, avisos), os destaques, as estimativas à parte, as
  escolas e os alertas;
* ``GET /redes/{id}/analise/indicadores/{chave}`` — as séries de um indicador (rede,
  referências e contexto; ou uma escola) ou a visão por escolas de uma edição, em ordem
  de NOME (nunca ranking);
* ``GET /redes/{id}/analise/plataformas`` — Elefante e Matific por escola × série no
  período, sem nenhum dado de aluno e com supressão de células pequenas;
* ``GET /redes/{id}/analise/relacao`` — a relação entre um indicador oficial por escola e
  uma métrica das plataformas, só quando os critérios da metodologia valem (e sempre os
  pares "lado a lado");
* ``GET /redes/{id}/analise/diagnostico`` — o diagnóstico pedagógico EXPLORATÓRIO de cada
  escola (avaliações oficiais × plataformas no período, com sinais rastreáveis, leituras
  por componente e nível de acompanhamento), em ordem de NOME;
* ``GET /redes/{id}/analise/plataformas/evolucao`` — Elefante e Matific da rede e de cada
  escola em cada bimestre do ano letivo que já começou;
* ``GET /escolas/{id}/analise`` — a análise de UMA escola.

PERMISSÕES: as rotas da rede usam ``exigir_rede`` (a Secretaria da PRÓPRIA rede e o
admin global — a regra das telas de indicadores); a da escola usa a MESMA dependência de
``GET /escolas/{id}/indicadores`` (``escola_com_indicadores_legiveis``: o global, a
Secretaria da rede da escola e o coordenador/admin da própria escola; o professor, 403).

A supressão de células pequenas na rota da escola segue QUEM lê: a Secretaria e o
global (que também leem a rede) recebem a decisão da rede inteira; o coordenador e o admin
da própria escola (que não leem a rede), a decisão tomada só dentro da escola.

Os critérios e as fórmulas estão em ``docs/analise/METODOLOGIA.md``.
"""
from dataclasses import dataclass
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db, leitura_sem_transacao
from app.core.deps import exigir_rede, get_usuario_atual
from app.core.tempo import hoje_br
from app.models import Escola, Rede, Usuario
from app.routers.indicadores import escola_com_indicadores_legiveis
from app.services.analise import AnaliseInvalida
from app.services.analise import diagnostico as svc_diagnostico
from app.services.analise import escola as svc_escola
from app.services.analise import evolucao as svc_evolucao
from app.services.analise import indicadores as svc_indicadores
from app.services.analise import plataformas as svc_plataformas
from app.services.analise import relacao as svc_relacao
from app.services.indicadores.leituras_da_requisicao import leituras_da_requisicao

router = APIRouter(prefix="/redes", tags=["Análise educacional"])
router_escola = APIRouter(prefix="/escolas", tags=["Análise educacional"])


def _executar(funcao, *args, **kwargs):
    try:
        return funcao(*args, **kwargs)
    except AnaliseInvalida as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@dataclass(frozen=True)
class _RedeConferida:
    """A rede das rotas que MEDEM as plataformas, já conferida por ``exigir_rede`` (existe e
    a conta pode lê-la). As medições (``plataformas_da_rede`` e ``evolucao``) usam só o ``id``
    dela: reler a linha da rede seria uma ida ao banco (~195 ms em produção) sem uso. Qualquer
    outro atributo dá erro — de propósito, para nenhuma medição passar a ler um campo vazio."""
    id: int


@router.get("/{rede_id}/analise/indicadores")
@leitura_sem_transacao
def catalogo(rede_id: int = Depends(exigir_rede), db: Session = Depends(get_db)):
    """O que existe de indicador oficial para a rede, desde quando e com que ressalva."""
    with leituras_da_requisicao(db):
        return _executar(svc_indicadores.catalogo, db, db.get(Rede, rede_id))


@router.get("/{rede_id}/analise/indicadores/{chave}")
@leitura_sem_transacao
def indicador(
    chave: str,
    etapa: str | None = None,
    componente: str | None = None,
    escola_id: int | None = None,
    de: int | None = None,
    ate: int | None = None,
    visao: str = "serie",
    edicao: int | None = None,
    rede_id: int = Depends(exigir_rede),
    db: Session = Depends(get_db),
):
    """As séries de UM indicador (``visao=serie``) ou as escolas da rede numa edição
    (``visao=escolas``, em ordem de nome). O ICA por escola é recusado (400): ele só
    existe para a rede."""
    with leituras_da_requisicao(db):
        return _executar(svc_indicadores.detalhe, db, db.get(Rede, rede_id), chave, etapa=etapa,
                         componente=componente, escola_id=escola_id, de=de, ate=ate, visao=visao,
                         edicao=edicao)


@router.get("/{rede_id}/analise/plataformas")
@leitura_sem_transacao
def plataformas(
    periodo: str = "ano_letivo",
    inicio: date | None = None,
    fim: date | None = None,
    serie: int | None = None,
    escola_id: int | None = None,
    rede_id: int = Depends(exigir_rede),
    db: Session = Depends(get_db),
):
    """Elefante e Matific por escola × série no período (padrão: o ano letivo)."""
    return _executar(svc_plataformas.plataformas_da_rede, db, _RedeConferida(rede_id),
                     preset=periodo, inicio=inicio, fim=fim, serie=serie,
                     escola_id=escola_id, hoje=hoje_br())


@router.get("/{rede_id}/analise/plataformas/evolucao")
@leitura_sem_transacao
def evolucao_plataformas(
    serie: int | None = None,
    escola_id: int | None = None,
    so_escola: bool = False,
    rede_id: int = Depends(exigir_rede),
    db: Session = Depends(get_db),
):
    """Elefante e Matific em cada bimestre do ano letivo que já começou (a rede e as
    escolas, em ordem de nome) — cada bimestre é o período da rota de plataformas. Com
    ``so_escola`` (a ficha da escola, pede ``escola_id``): só a escola é medida e o bloco da
    rede sai nulo."""
    return _executar(svc_evolucao.evolucao, db, _RedeConferida(rede_id), serie=serie,
                     escola_id=escola_id, so_escola=so_escola, hoje=hoje_br())


@router.get("/{rede_id}/analise/diagnostico")
@leitura_sem_transacao
def diagnostico_pedagogico(
    periodo: str = "ano_letivo",
    inicio: date | None = None,
    fim: date | None = None,
    rede_id: int = Depends(exigir_rede),
    db: Session = Depends(get_db),
):
    """O diagnóstico pedagógico EXPLORATÓRIO de cada escola da rede (em ordem de nome):
    avaliações oficiais × plataformas no período (padrão: o ano letivo). Hipótese para
    orientar o acompanhamento — nunca causa e efeito."""
    return _executar(svc_diagnostico.diagnostico, db, db.get(Rede, rede_id), preset=periodo,
                     inicio=inicio, fim=fim, hoje=hoje_br())


@router.get("/{rede_id}/analise/relacao")
@leitura_sem_transacao
def relacao(
    indicador: str,
    etapa: str | None = None,
    componente: str | None = None,
    edicao: int | None = None,
    metrica: str | None = None,
    periodo: str = "ano_letivo",
    inicio: date | None = None,
    fim: date | None = None,
    serie: int | None = None,
    rede_id: int = Depends(exigir_rede),
    db: Session = Depends(get_db),
):
    """A relação indicador oficial × plataforma por escola: o coeficiente só quando os
    critérios valem; os pares lado a lado sempre."""
    return _executar(svc_relacao.relacao, db, db.get(Rede, rede_id), indicador=indicador,
                     etapa=etapa, componente=componente, edicao=edicao, metrica=metrica,
                     periodo=periodo, inicio=inicio, fim=fim, serie=serie, hoje=hoje_br())


@router_escola.get("/{escola_id}/analise")
@leitura_sem_transacao
def analise_da_escola(
    periodo: str = "ano_letivo",
    inicio: date | None = None,
    fim: date | None = None,
    so_avaliacoes: bool = False,
    escola: Escola = Depends(escola_com_indicadores_legiveis),
    usuario: Usuario = Depends(get_usuario_atual),
    db: Session = Depends(get_db),
):
    """A análise de UMA escola: os indicadores oficiais dela (com a rede municipal como
    referência), as plataformas por série e o que não dá para comparar. Com
    ``so_avaliacoes`` (a ficha e a comparação da Secretaria): sem as plataformas."""
    # Quem lê a REDE (global, Secretaria) recebe a supressão da rede; quem só lê a escola,
    # a decidida dentro dela (nada da resposta depende das outras escolas).
    escopo_rede = bool(usuario.is_global or usuario.rede_id is not None)
    return _executar(svc_escola.analise_da_escola, db, escola, preset=periodo, inicio=inicio,
                     fim=fim, hoje=hoje_br(), escopo_rede=escopo_rede,
                     com_plataformas=not so_avaliacoes)
