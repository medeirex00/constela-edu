"""Quem participa das premiações — regra ÚNICA, no backend.

Decisão de produto: as premiações (ranking, certificados, pódios) são do Ensino
Fundamental I — **1º ao 5º ano**. As turmas de Educação Infantil (1ª e 2ª Fase)
que a Lista Piloto traz junto NÃO concorrem.

Isto é regra de ELEGIBILIDADE, não de cadastro. A criança continua matriculada,
ativa, com turma, histórico e ficha intactos; ela só não entra na disputa nem
recebe documento de premiação. Nada aqui apaga, arquiva ou altera matrícula.

Por que um helper NOVO em vez de ``1 <= serie_numero(x) <= 5``: porque
``serie_numero`` **não distingue fase de ano** — ``serie_numero("1ª Fase")``
devolve ``1``, exatamente como ``"1º Ano"``. Um teste de faixa sozinho admitiria
a EMEI inteira. O veto por ETAPA tem de vir antes, e vem aqui.

Cuidado a jusante: o rótulo em ``Turma.ano_escolar`` é texto livre e já chegou ao
banco mentindo em pelo menos um caminho (o importador derivava "1º Ano" de uma
turma chamada "1 FASE A"). Esta regra lê o rótulo; se o rótulo for falso, ela não
tem como saber. Por isso a correção do importador acompanha esta entrega.
"""
from __future__ import annotations

import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Turma

#: As séries que concorrem. Fundamental I.
ANOS_PREMIAVEIS = (1, 2, 3, 4, 5)

#: Palavras que marcam uma ETAPA que não concorre. Casadas por palavra inteira
#: sobre o rótulo sem acento e em maiúsculas — "FASE" pega "1ª Fase", "2 FASE B"
#: e "Fase II"; não pega nada que apenas contenha as letras.
_ETAPAS_FORA = (
    "FASE", "ETAPA", "EMEI", "INFANTIL", "MATERNAL", "BERCARIO", "BERCARISTA",
    "CRECHE", "JARDIM", "PRE", "PREI", "PREII", "EJA", "MINIGRUPO",
)
_RE_ETAPA_FORA = re.compile(r"\b(?:%s)\b" % "|".join(_ETAPAS_FORA))

#: Um rótulo que diz "ANO" com todas as letras está AFIRMANDO Fundamental, e
#: essa afirmação vence a palavra de etapa. Sem esta regra, uma turma chamada
#: "4º Ano - Fase 2" perderia o certificado por causa de uma palavra que ali não
#: significa Educação Infantil — errar para o lado de tirar a premiação de uma
#: criança do Fundamental é pior do que errar para o outro, e o outro lado tem
#: conferência humana (a escola vê a lista antes de emitir).
_RE_ANO_EXPLICITO = re.compile(
    r"\b(?:\d\s*[º°O]?\s*ANO|ANO\s*\d|"
    r"PRIMEIRO|SEGUNDO|TERCEIRO|QUARTO|QUINTO)\b")


def _plano(rotulo: str | None) -> str:
    """Sem acento, maiúsculas, espaços normalizados."""
    texto = unicodedata.normalize("NFKD", str(rotulo or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).strip().upper()


def e_etapa_fora_da_premiacao(ano_escolar: str | None) -> bool:
    """O rótulo nomeia uma etapa que não concorre (Fase/EMEI/EJA/…)?

    ``"1ª Fase"`` → ``True``; ``"4º Ano"`` → ``False``; ``"4º Ano - Fase 2"`` →
    ``False``, porque o "ANO" explícito manda (ver :data:`_RE_ANO_EXPLICITO`)."""
    plano = _plano(ano_escolar)
    if _RE_ANO_EXPLICITO.search(plano):
        return False
    return bool(_RE_ETAPA_FORA.search(plano))


def ano_premiavel(ano_escolar: str | None) -> int | None:
    """A série que concorre (1–5), ou ``None`` se a turma não participa.

    >>> ano_premiavel("3º Ano"), ano_premiavel("4ºB"), ano_premiavel("2° Ano")
    (3, 4, 2)
    >>> ano_premiavel("1ª Fase"), ano_premiavel("6º Ano"), ano_premiavel("")
    (None, None, None)
    """
    # Import TARDIO: `dificuldade_livro` importa `scoring`, que importa este
    # módulo. No topo isso fecha um ciclo e o app nem sobe. O próprio `scoring`
    # já usa esta mesma saída para falar com `dificuldade_livro`.
    from app.services.dificuldade_livro import serie_numero

    if e_etapa_fora_da_premiacao(ano_escolar):
        return None
    numero = serie_numero(ano_escolar)
    return numero if numero in ANOS_PREMIAVEIS else None


def participa_de_premiacao(ano_escolar: str | None) -> bool:
    """A turma concorre a ranking/premiação/certificado de premiação?"""
    return ano_premiavel(ano_escolar) is not None


def turmas_premiaveis(db: Session, escola_id: int,
                      ano_letivo: int | None = None) -> list[int]:
    """Os ``turma_id`` da escola que concorrem.

    Devolve uma lista de ids para usar em ``.in_(...)``, em vez de tentar
    expressar a regra em SQL: o rótulo é texto livre e a decisão depende de
    normalização (acento, "4ºB", "2° Ano", por extenso) que já existe em Python.
    Uma consulta barata por chamada, e a regra continua num lugar só.
    """
    consulta = select(Turma.id, Turma.ano_escolar).where(Turma.escola_id == escola_id)
    if ano_letivo is not None:
        consulta = consulta.where(Turma.ano_letivo == ano_letivo)
    return [tid for tid, rotulo in db.execute(consulta).all()
            if participa_de_premiacao(rotulo)]


def turmas_premiaveis_da_rede(db: Session, escola_ids: list[int] | None = None,
                              ano_letivo: int | None = None) -> list[int]:
    """Mesma regra, para os consumidores que varrem várias escolas de uma vez
    (ranking da rede, painel da Secretaria). Sem isto o número da escola no
    painel da rede deixaria de bater com o da própria escola."""
    consulta = select(Turma.id, Turma.ano_escolar)
    if escola_ids is not None:
        consulta = consulta.where(Turma.escola_id.in_(escola_ids))
    if ano_letivo is not None:
        consulta = consulta.where(Turma.ano_letivo == ano_letivo)
    return [tid for tid, rotulo in db.execute(consulta).all()
            if participa_de_premiacao(rotulo)]
