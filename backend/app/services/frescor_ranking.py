"""FRESCOR do dado que sustenta um ranking — "de quando é este número?".

O motor (``scoring._carregar_contexto``) usa, para cada aluno, o retrato MAIS
RECENTE da plataforma, sem olhar a idade dele: uma coleta parada há três
semanas produz um ranking com a mesma cara de um ranking de ontem. Este módulo
NÃO muda nada no cálculo — ele DECLARA a idade do dado, para a tela poder dizer
"dados de 01/10, há 19 dias" em vez de deixar o número parecer atual.

Duas datas, com papéis diferentes:

* ``dado_mais_recente_em`` — a data de referência mais recente entre os retratos
  ATUAIS dos alunos que concorrem: os mesmos que o motor usa (ativos,
  matriculados no ano letivo, turma premiável — as Fases não concorrem — e, no
  Matific, só retrato do ano letivo, porque o contador é do ano). É ela que
  decide o estado: é o que o número da tela de fato reflete;
* ``ultima_sincronizacao_ok_em`` — a última sincronização que APLICOU dado
  (status ``concluida``, ou ``parcial`` com ao menos um aluno aplicado — o
  "último sucesso" do contrato da ETAPA 2, a mesma definição de
  ``sync.service.ultimo_sucesso_em``). É informativa e NÃO decide o estado: o
  dado pode ter chegado por importação manual, e uma sincronização que não
  trouxe retrato novo (``sem_atualizacao``/``sem_dados``/``parcial`` sem aluno)
  não torna o dado atual.

Estados — nunca "Funcionando":

* ``sem_dados``     — nenhum aluno que concorre tem retrato. Ausência, nunca zero;
* ``desatualizado`` — o retrato mais recente tem mais de
  :data:`LIMITE_DIAS_DADO_ATUAL` dias;
* ``parcial``       — o mais recente está em dia, mas há aluno cujo retrato atual
  passou do limite (a última coleta não o trouxe: a nota dele é antiga);
* ``em_dia``        — todos os retratos usados estão dentro do limite.

O DIA de um retrato é o dia de BRASÍLIA (:func:`dia_do_retrato`). O banco grava
``data_referencia`` e ``finalizada_em`` em UTC naive (``sync/fuso.py``), e o
"hoje" é o de Brasília: tirar ``.date()`` direto do UTC fazia a coleta das 22h30
de 20/10 virar "dados de 21/10" (``dias_desde_dado = -1``) e dava ao dado um dia
a mais antes de virar "desatualizado". O corte dos retratos antigos é a
meia-noite de Brasília convertida para UTC, pela mesma razão. O ``snapshot_em``
do ranking de Matemática por período usa esta mesma função, para o selo e a
linha do aluno não discordarem sobre o dia. O ``snapshot_em`` que o motor grava
no ranking por dimensão (``scoring._data_iso``) ainda tira o dia do UTC: falta
alinhá-lo a esta função (nenhuma tela o exibe hoje).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import and_, case, false, func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    Aluno,
    Escola,
    Matricula,
    SnapshotElefante,
    SnapshotMatific,
)
from app.models.sincronizacao import SincronizacaoExecucao
from app.services import elegibilidade, matific_destaque, modulos as svc_modulos
from app.sync import fuso

#: Um dado com MAIS do que estes dias é "desatualizado" na tela de ranking.
#: Devolvido em toda resposta (``limite_dias``) para a tela não ter um número
#: próprio que possa divergir deste.
#:
#: NÃO é o limite da tela Integrações: lá ``sync.service.limite_frescor`` mede a
#: idade da última SINCRONIZAÇÃO concluída pela cadência da agenda (2 dias na
#: diária e sem agenda, 10 na semanal). Do 3º ao 7º dia sem coleta diária, a
#: Integração já diz "desatualizado" e o ranking ainda não avisa. Unificar os
#: dois números é decisão do dono; até lá, o selo do ranking mostra a idade do
#: dado e nomeia o seu aviso pelo limite ("mais de N dias"), para as duas telas
#: não usarem a mesma palavra com réguas diferentes.
LIMITE_DIAS_DADO_ATUAL = 7

#: Dimensão → (plataforma, modelo do retrato). Mesma correspondência de
#: ``scoring.DIMENSOES``; repetida aqui com o modelo para não importar o motor.
_FONTES = {
    "leitura": ("elefante", SnapshotElefante),
    "matematica": ("matific", SnapshotMatific),
}

#: Do pior para o melhor: o estado geral da escola é o pior das dimensões.
_GRAVIDADE = ("sem_dados", "desatualizado", "parcial", "em_dia")


def _janela_matific(escolas: list[Escola]):
    """Condição: o retrato do Matific é do ano letivo ATIVO da escola dele (o
    contador é do ano — a mesma definição de aferido do motor,
    ``scoring.snapshots_matific_do_ano``). Um termo por ano letivo distinto."""
    por_ano: dict[int, list[int]] = {}
    for escola in escolas:
        por_ano.setdefault(escola.ano_letivo_ativo, []).append(escola.id)
    termos = []
    for ano, ids in por_ano.items():
        inicio, fim = matific_destaque.janela_ano_letivo(ano)
        termos.append(and_(SnapshotMatific.escola_id.in_(ids),
                           SnapshotMatific.data_referencia >= inicio,
                           SnapshotMatific.data_referencia <= fim))
    return or_(*termos) if termos else false()


def _datas_por_escola(db: Session, escolas: list[Escola], modelo,
                      premiaveis: list[int], turma_ids: list[int] | None,
                      corte: datetime) -> dict[int, tuple]:
    """``{escola_id: (mais_recente, mais_antigo, n_alunos, n_antigos)}`` sobre o
    retrato ATUAL (data_referencia, id) de cada aluno que concorre.

    UMA consulta para todas as escolas (window function por escola+aluno, a
    mesma régua de ``scoring.ids_snapshots_atuais``), nunca uma por escola."""
    ids = [e.id for e in escolas]
    concorre = (
        select(Matricula.id)
        .join(Aluno, Aluno.id == Matricula.aluno_id)
        .join(Escola, Escola.id == Matricula.escola_id)
        .where(Matricula.escola_id == modelo.escola_id,
               Matricula.aluno_id == modelo.aluno_id,
               Matricula.ano_letivo == Escola.ano_letivo_ativo,
               Matricula.turma_id.in_(premiaveis),
               Aluno.status == "ativo")
    )
    if turma_ids is not None:
        concorre = concorre.where(Matricula.turma_id.in_(turma_ids))
    filtro = [modelo.escola_id.in_(ids), concorre.exists()]
    if modelo is SnapshotMatific:
        filtro.append(_janela_matific(escolas))
    numerado = (
        select(
            modelo.escola_id.label("escola_id"),
            modelo.data_referencia.label("data"),
            func.row_number().over(
                partition_by=(modelo.escola_id, modelo.aluno_id),
                order_by=(modelo.data_referencia.desc(), modelo.id.desc()),
            ).label("pos"),
        )
        .where(*filtro)
        .subquery()
    )
    linhas = db.execute(
        select(numerado.c.escola_id, func.max(numerado.c.data),
               func.min(numerado.c.data), func.count(),
               func.sum(case((numerado.c.data < corte, 1), else_=0)))
        .where(numerado.c.pos == 1)
        .group_by(numerado.c.escola_id)
    ).all()
    return {eid: (maior, menor, int(n or 0), int(antigos or 0))
            for eid, maior, menor, n, antigos in linhas}


#: Estados finais de execução que podem ter APLICADO dado (contrato da ETAPA 2):
#: o "último sucesso". ``parcial`` aplicou dado e teve falha em parte — o dado
#: que entrou é real —, mas só conta com ≥1 aluno aplicado: a ``parcial`` de 0
#: aluno (D2(6), falhou só o endpoint dos nomes do Matific) não trouxe dado (P18).
#: ``sem_atualizacao``, ``sem_dados`` e ``erro`` não contam. O filtro aplicado é o
#: do serviço da sync (``_filtro_sucesso``).
STATUS_COM_DADO_APLICADO = ("concluida", "parcial")


def _ultimas_sincronizacoes_ok(db: Session, ids: list[int]) -> dict[tuple[int, str], datetime]:
    """``{(escola_id, plataforma): finalizada_em}`` da última sincronização que
    aplicou dado (:data:`STATUS_COM_DADO_APLICADO`; a ``parcial`` só com aluno
    aplicado) — falha, "sem dados", "sem atualização" e a ``parcial`` sem aluno não
    contam, nem a coleta POR PERÍODO do Matific, que não renova o acumulado dos
    rankings. É o MESMO filtro de ``sync.service.ultimo_sucesso_em``."""
    if not ids:
        return {}
    # Import local: o serviço da sync carrega muita coisa; aqui só o filtro.
    from app.sync.service import _filtro_sucesso
    return {(eid, plataforma): quando for eid, plataforma, quando in db.execute(
        select(SincronizacaoExecucao.escola_id, SincronizacaoExecucao.plataforma,
               func.max(SincronizacaoExecucao.finalizada_em))
        .where(SincronizacaoExecucao.escola_id.in_(ids), _filtro_sucesso())
        .group_by(SincronizacaoExecucao.escola_id, SincronizacaoExecucao.plataforma)
    ).all()}


def dia_do_retrato(momento: datetime | None) -> date | None:
    """Dia de BRASÍLIA de um instante gravado (naive = UTC, o padrão do banco).
    Das 21h à meia-noite o UTC já está no dia seguinte; o "hoje" das telas não."""
    return fuso.para_local(momento).date() if momento is not None else None


def _corte_dos_antigos(hoje: date, limite: int) -> datetime:
    """Instante UTC naive a partir do qual o retrato está dentro do limite: a
    meia-noite de Brasília de ``hoje - limite``. Antes dela, o dia de Brasília do
    retrato tem mais de ``limite`` dias — a mesma régua de :func:`_estado`."""
    return fuso.local_para_utc_naive(
        datetime.combine(hoje - timedelta(days=limite), time.min))


def _estado(alunos: int, dias: int | None, antigos: int, limite: int) -> str:
    if not alunos:
        return "sem_dados"
    if dias is not None and dias > limite:
        return "desatualizado"
    return "parcial" if antigos else "em_dia"


def _bloco(plataforma: str, contratada: bool, datas: tuple | None,
           sync_ok: datetime | None, hoje: date, limite: int) -> dict:
    """O frescor de UMA dimensão numa escola (forma estável para a tela)."""
    bloco = {"plataforma": plataforma, "contratada": contratada}
    if not contratada:
        # Módulo fora do plano: a dimensão não existe para a escola — nem como
        # "sem dados" (a mesma regra dos rankings e da lista de não aferidos).
        bloco.update(estado=None, dado_mais_recente_em=None, dado_mais_antigo_em=None,
                     dias_desde_dado=None, alunos_com_dado=0, alunos_com_dado_antigo=0,
                     ultima_sincronizacao_ok_em=None, dias_desde_sincronizacao_ok=None)
        return bloco
    maior, menor, alunos, antigos = datas or (None, None, 0, 0)
    dia_maior, dia_menor, dia_sync = (dia_do_retrato(maior), dia_do_retrato(menor),
                                      dia_do_retrato(sync_ok))
    dias = (hoje - dia_maior).days if dia_maior else None
    bloco.update(
        estado=_estado(alunos, dias, antigos, limite),
        dado_mais_recente_em=dia_maior.isoformat() if dia_maior else None,
        dado_mais_antigo_em=dia_menor.isoformat() if dia_menor else None,
        dias_desde_dado=dias,
        alunos_com_dado=alunos,
        alunos_com_dado_antigo=antigos,
        ultima_sincronizacao_ok_em=sync_ok.isoformat() if sync_ok else None,
        dias_desde_sincronizacao_ok=(hoje - dia_sync).days if dia_sync else None,
    )
    return bloco


def frescor_das_escolas(db: Session, escolas: list[Escola], hoje: date,
                        turma_ids: list[int] | None = None,
                        contratados: set[str] | None = None,
                        limite: int = LIMITE_DIAS_DADO_ATUAL) -> dict[int, dict]:
    """Frescor por escola, para N escolas num número FIXO de consultas (uma
    por plataforma, uma das sincronizações e uma das turmas premiáveis — mais a
    dos módulos de cada escola quando ``contratados`` não vem pronto).

    ``turma_ids`` restringe a população às turmas informadas (o recorte do
    professor — a mesma lista de ``permissoes.turmas_permitidas``); ``None`` =
    a escola inteira. ``contratados`` = módulos do plano; ``None`` = os de cada
    escola (``modulos.modulos_da_escola``)."""
    if not escolas:
        return {}
    ids = [e.id for e in escolas]
    corte = _corte_dos_antigos(hoje, limite)
    premiaveis = elegibilidade.turmas_premiaveis_da_rede(db, ids)
    # Cada escola filtrada pelo SEU ano letivo: a lista acima traz turmas de
    # todos os anos; quem garante o ano é o `Matricula.ano_letivo` da consulta.
    datas = {dim: _datas_por_escola(db, escolas, modelo, premiaveis, turma_ids, corte)
             for dim, (_plat, modelo) in _FONTES.items()}
    syncs = _ultimas_sincronizacoes_ok(db, ids)
    saida: dict[int, dict] = {}
    for escola in escolas:
        planos = (contratados if contratados is not None
                  else svc_modulos.modulos_da_escola(db, escola))
        dimensoes = {
            dim: _bloco(plataforma, dim in planos, datas[dim].get(escola.id),
                        syncs.get((escola.id, plataforma)), hoje, limite)
            for dim, (plataforma, _modelo) in _FONTES.items()
        }
        estados = [b["estado"] for b in dimensoes.values() if b["contratada"]]
        saida[escola.id] = {
            "limite_dias": limite,
            "hoje": hoje.isoformat(),
            "estado": min(estados, key=_GRAVIDADE.index) if estados else "sem_dados",
            "dimensoes": dimensoes,
        }
    return saida


def frescor_da_escola(db: Session, escola: Escola, hoje: date,
                      turma_ids: list[int] | None = None) -> dict:
    """Frescor de UMA escola — o bloco ``frescor`` das respostas de ranking."""
    return frescor_das_escolas(db, [escola], hoje, turma_ids=turma_ids)[escola.id]
