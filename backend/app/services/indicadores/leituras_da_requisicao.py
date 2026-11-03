"""Leituras dos indicadores oficiais que se REPETEM numa requisição, feitas uma vez só.

Em produção a API fica a ~195 ms do banco por consulta. Montar a análise de uma escola (ou o
catálogo da rede) lê o ICA, o SARESP, o IEE, o Ideb e o Saeb, e cada família buscava de novo o
mesmo registro do catálogo (``AvaliacaoExterna`` pela chave), as importações APLICADAS do
município (uma consulta por parser) e as escolas da rede. Dentro de
``leituras_da_requisicao(db)`` essas três leituras saem do banco uma vez e são servidas da
memória; fora dele (as rotas que GRAVAM, os importadores, os testes que não pedem), cada
função consulta o banco como sempre — nada fica velho depois de uma gravação.

O resultado é o mesmo das consultas diretas: o catálogo e as importações são lidos inteiros e
filtrados em Python pelos mesmos critérios, e quem chama ordena como antes.
"""
from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AvaliacaoExterna, Escola, ImportacaoIndicador

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


def importacoes_por_id(db: Session, ids: set[int]) -> dict[int, ImportacaoIndicador]:
    """As importações destes ids; as já lidas nesta requisição não voltam ao banco."""
    if not ids:
        return {}
    memoria = _memoria(db)
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
