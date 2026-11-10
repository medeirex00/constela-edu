"""Leituras dos indicadores oficiais que se REPETEM numa requisição, feitas uma vez só.

Em produção a API fica a ~195 ms do banco por consulta. Montar a análise de uma escola (ou o
catálogo da rede) lê o ICA, o SARESP, o IEE, o Ideb e o Saeb, e cada família buscava de novo o
mesmo registro do catálogo (``AvaliacaoExterna`` pela chave), as importações APLICADAS do
município (uma consulta por parser) e as escolas da rede. Dentro de
``leituras_da_requisicao(db)`` essas leituras saem do banco uma vez e são servidas da
memória; fora dele (as rotas que GRAVAM, os importadores, os testes que não pedem), cada
função consulta o banco como sempre — nada fica velho depois de uma gravação.

Também uma vez só, dentro do bloco (``ativa``), as duas tabelas de números oficiais que cada
família relia com o seu próprio filtro:

* ``referencias``: as linhas de ``indicadores_referencia`` do município, da UF dele e do
  Brasil (o ICA, o SARESP, o Ideb da escola e o Ideb, o Saeb e o contexto da rede liam cada um
  a sua: seis consultas) mais as das escolas da rede, pelo INEP;
* ``resultados_sem_turma``: os ``resultados_avaliacao`` sem turma das escolas da rede no
  SARESP, no Ideb e no Saeb (três consultas).

O resultado é o mesmo das consultas diretas: as linhas são lidas num superconjunto e
filtradas em Python pelos MESMOS critérios de cada consulta (quem chama tem os dois caminhos
lado a lado), em ordem de id, e quem chama ordena como antes.
"""
from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models import (AvaliacaoExterna, Escola, ImportacaoIndicador, IndicadorReferencia,
                        ResultadoAvaliacao)
from app.services.avaliacoes import normalizar_inep

_CHAVE = "indicadores_leituras_da_requisicao"


@contextmanager
def leituras_da_requisicao(db: Session):
    """Liga a leitura única durante o bloco (só para requisições de LEITURA)."""
    if _CHAVE in db.info:                      # já ligada por quem chamou
        yield
        return
    db.info[_CHAVE] = {}
    try:
        yield
    finally:
        db.info.pop(_CHAVE, None)


def _memoria(db: Session) -> dict | None:
    return db.info.get(_CHAVE)


def ativa(db: Session) -> bool:
    """A leitura única está ligada nesta sessão (dentro de ``leituras_da_requisicao``)?"""
    return _memoria(db) is not None


def avaliacao(db: Session, chave: str) -> AvaliacaoExterna | None:
    """O registro do catálogo pela chave."""
    memoria = _memoria(db)
    if memoria is None:
        return db.execute(select(AvaliacaoExterna).where(
            AvaliacaoExterna.chave == chave)).scalar_one_or_none()
    if "catalogo" not in memoria:
        memoria["catalogo"] = {a.chave: a for a in db.execute(select(AvaliacaoExterna)).scalars()}
    return memoria["catalogo"].get(chave)


def aplicadas_do_territorio(db: Session, codigo: str, parsers: tuple[str, ...]
                            ) -> list[ImportacaoIndicador]:
    """As importações APLICADAS com ``codigo_territorio_alvo == codigo`` destes parsers (em
    qualquer ordem: quem chama ordena)."""
    memoria = _memoria(db)
    if memoria is None:
        return list(db.execute(select(ImportacaoIndicador).where(
            ImportacaoIndicador.status == "aplicada",
            ImportacaoIndicador.parser.in_(parsers),
            ImportacaoIndicador.codigo_territorio_alvo == codigo)).scalars())
    por_codigo = memoria.setdefault("aplicadas", {})
    if codigo not in por_codigo:
        por_codigo[codigo] = list(db.execute(select(ImportacaoIndicador).where(
            ImportacaoIndicador.status == "aplicada",
            ImportacaoIndicador.codigo_territorio_alvo == codigo)).scalars())
    return [i for i in por_codigo[codigo] if i.parser in parsers]


def importacoes_por_id(db: Session, ids: set[int], codigo: str | None = None
                       ) -> dict[int, ImportacaoIndicador]:
    """As importações destes ids; as já lidas nesta requisição não voltam ao banco. Com a
    memória ligada e o ``codigo`` do município, as APLICADAS dele são lidas antes (a mesma
    leitura de ``aplicadas_do_territorio``, que o SARESP e o Ideb fazem depois): as fontes do
    município saem dela, e só as outras vão ao banco."""
    if not ids:
        return {}
    memoria = _memoria(db)
    if memoria is not None and codigo is not None:
        aplicadas_do_territorio(db, codigo, ())
    lidas: dict[int, ImportacaoIndicador] = {}
    if memoria is not None:
        for imps in memoria.get("aplicadas", {}).values():
            lidas.update({i.id: i for i in imps if i.id in ids})
    faltam = set(ids) - set(lidas)
    if faltam:
        lidas.update({i.id: i for i in db.execute(select(ImportacaoIndicador).where(
            ImportacaoIndicador.id.in_(faltam))).scalars()})
    return lidas


def escolas_da_rede(db: Session, rede_id: int) -> list[Escola]:
    """As escolas da rede (em qualquer ordem: quem chama ordena)."""
    memoria = _memoria(db)
    if memoria is None:
        return list(db.execute(select(Escola).where(Escola.rede_id == rede_id)).scalars())
    por_rede = memoria.setdefault("escolas", {})
    if rede_id not in por_rede:
        por_rede[rede_id] = list(db.execute(select(Escola).where(
            Escola.rede_id == rede_id)).scalars())
    return list(por_rede[rede_id])


def ineps_da_rede(db: Session, rede_id: int) -> frozenset[str]:
    """Os códigos INEP (normalizados) das escolas da rede — o filtro de escola do SARESP e do
    Ideb (``normalizar_inep``; a escola sem código não entra)."""
    return frozenset(i for i in (normalizar_inep(e.codigo_inep)
                                 for e in escolas_da_rede(db, rede_id)) if i)


def referencias(db: Session, codigo: str, ineps: frozenset[str] | None = None
                ) -> list[IndicadorReferencia]:
    """SÓ com a memória ligada: as linhas de ``indicadores_referencia`` com
    ``codigo_territorio`` no município ``codigo``, na UF dele (``codigo[:2]``) ou no Brasil
    (``ica.CODIGO_BRASIL``) — as de território (abrangência diferente de ``escola``) sempre
    e, com ``ineps``, também as de ESCOLA com ``codigo_inep`` nele —, em ordem de id. Quem
    chama aplica o próprio filtro (o mesmo da consulta direta). Território e escolas saem
    numa consulta só na primeira chamada que pede os dois (o ICA, que abre a análise, já
    passa os INEPs da rede); o que faltar depois é lido à parte."""
    from app.services.indicadores.ica import CODIGO_BRASIL

    memoria = _memoria(db)
    if memoria is None:
        raise RuntimeError("referencias() só vale dentro de leituras_da_requisicao")
    territorio = memoria.setdefault("ref_territorio", {})
    de_escola = memoria.setdefault("ref_escolas", {})
    falta_territorio = codigo not in territorio
    falta_escolas = ineps is not None and (codigo, ineps) not in de_escola
    if falta_territorio or falta_escolas:
        partes = []
        if falta_territorio:
            partes.append(IndicadorReferencia.abrangencia != "escola")
        if falta_escolas:
            partes.append(and_(IndicadorReferencia.abrangencia == "escola",
                               IndicadorReferencia.codigo_inep.in_(sorted(ineps))))
        linhas = list(db.execute(select(IndicadorReferencia).where(
            IndicadorReferencia.codigo_territorio.in_(
                sorted({codigo, codigo[:2], CODIGO_BRASIL})),
            or_(*partes)).order_by(IndicadorReferencia.id)).scalars())
        if falta_territorio:
            territorio[codigo] = [ln for ln in linhas if ln.abrangencia != "escola"]
        if falta_escolas:
            de_escola[(codigo, ineps)] = [ln for ln in linhas if ln.abrangencia == "escola"]
    saida = list(territorio[codigo])
    if ineps is not None:
        saida += de_escola[(codigo, ineps)]
    return sorted(saida, key=lambda ln: ln.id)


# As avaliações cujos resultados POR ESCOLA a análise lê (SARESP, Ideb e Saeb): uma leitura só.
AVALIACOES_POR_ESCOLA = ("saresp", "ideb", "saeb")


def resultados_sem_turma(db: Session, escola_ids: set[int], avaliacao_id: int
                         ) -> list[ResultadoAvaliacao]:
    """SÓ com a memória ligada: os ``resultados_avaliacao`` da avaliação ``avaliacao_id`` (uma
    de ``AVALIACOES_POR_ESCOLA``) com ``escola_id`` em ``escola_ids`` e SEM turma (nula ou
    vazia), em ordem de id. Na primeira chamada para estas escolas, as três avaliações são
    lidas juntas. Quem chama aplica o resto do próprio filtro."""
    memoria = _memoria(db)
    if memoria is None:
        raise RuntimeError("resultados_sem_turma() só vale dentro de leituras_da_requisicao")
    por_escolas = memoria.setdefault("resultados", {})
    chave = frozenset(escola_ids)
    if chave not in por_escolas:
        ids_av = sorted(a.id for a in (avaliacao(db, c) for c in AVALIACOES_POR_ESCOLA)
                        if a is not None)
        grupo: dict[int, list[ResultadoAvaliacao]] = {i: [] for i in ids_av}
        if ids_av and chave:
            for r in db.execute(select(ResultadoAvaliacao).where(
                    ResultadoAvaliacao.avaliacao_id.in_(ids_av),
                    ResultadoAvaliacao.escola_id.in_(sorted(chave)),
                    or_(ResultadoAvaliacao.turma.is_(None), ResultadoAvaliacao.turma == ""),
                    ).order_by(ResultadoAvaliacao.id)).scalars():
                grupo[r.avaliacao_id].append(r)
        por_escolas[chave] = grupo
    grupo = por_escolas[chave]
    if avaliacao_id not in grupo:
        raise ValueError("avaliação fora de AVALIACOES_POR_ESCOLA")
    return list(grupo[avaliacao_id])
