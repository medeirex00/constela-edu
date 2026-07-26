"""Casar as escolas de uma rede com o CÓDIGO INEP oficial, a partir do arquivo do
INEP (ex.: IDEB por escola). O gestor cadastra as escolas com nomes CURTOS
("ADOLFINA", "CARLOS RODRIGUES"); o arquivo traz o nome OFICIAL longo
("ADOLFINA LEONOR SOARES DOS SANTOS PROFA CIEFI"). Casamos por TOKENS do nome,
escopado pelo MUNICÍPIO da escola (a cidade que ela já tem no cadastro), e
devolvemos PROPOSTAS para o gestor conferir — nunca aplica sozinho.

Reusa o leitor robusto do importador de avaliações (XLSX/CSV/ZIP, streaming)."""
from __future__ import annotations

import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Escola
from app.services.avaliacoes import _cel, _iterar_grade, _num, normalizar_inep

# Palavras que NÃO distinguem uma escola de outra (tipo de unidade, títulos,
# conectivos). Removidas antes de casar, para "EMEF Prof Auracy Mansano" bater
# com "AURACY MANSANO".
_RUIDO = {
    "emef", "emei", "emeief", "emeief", "emefebs", "eeefm", "eeef", "eef", "ee",
    "em", "ei", "cei", "ciefi", "cieji", "centro", "integrado", "integ",
    "educacao", "educacional", "ed", "educ", "fundamental", "fund", "infantil",
    "inf", "ensino", "escola", "municipal", "estadual", "est", "publica",
    "prof", "profa", "professor", "professora", "dr", "dra", "sr", "sra",
    "de", "da", "do", "dos", "das", "e", "no", "na",
}


def _sem_acento(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _norm(texto: str) -> str:
    """Caixa alta, sem acento, só letras/números e espaço."""
    limpo = _sem_acento(texto or "").upper()
    return " ".join("".join(c if c.isalnum() else " " for c in limpo).split())


def _tokens(nome: str) -> frozenset[str]:
    """Tokens significativos do nome (sem ruído, sem tokens de 1 letra)."""
    return frozenset(
        t for t in _norm(nome).split()
        if len(t) > 1 and t.lower() not in _RUIDO
    )


def _ler_oficiais(conteudo: bytes, nome: str, *, linha_dados: int, col_inep: int,
                  col_nome: int, col_municipio: int, col_valor: int | None):
    """Lê o arquivo oficial → lista de (tokens, municipio_norm, municipio_bruto,
    inep, nome_oficial, valor). Guarda o município BRUTO para exibir na proposta
    (o gestor precisa ver a cidade para rejeitar homônima de outro município).
    Ignora linhas sem INEP."""
    oficiais = []
    for i, linha in enumerate(_iterar_grade(conteudo, nome)):
        if i < linha_dados:
            continue
        inep = normalizar_inep(_cel(linha, col_inep))
        if not inep:
            continue
        nome_of = str(_cel(linha, col_nome) or "").strip()
        muni_bruto = str(_cel(linha, col_municipio) or "").strip()
        valor = _num(_cel(linha, col_valor)) if col_valor is not None else None
        oficiais.append((_tokens(nome_of), _norm(muni_bruto), muni_bruto, inep,
                         nome_of, valor))
    return oficiais


def casar_inep(db: Session, rede_id: int, conteudo: bytes, nome: str, *,
               linha_dados: int = 8, col_inep: int = 3, col_nome: int = 4,
               col_municipio: int = 2, col_valor: int | None = 115) -> list[dict]:
    """Para cada escola da REDE, propõe o INEP oficial casando por tokens do nome
    dentro do MESMO município. Devolve propostas (não grava):
      escola_id, escola_nome, cidade, ja_tem (inep atual), inep (proposto),
      nome_oficial, valor (ex.: IDEB), confianca (alta|revisar|nenhum)."""
    escolas = db.execute(
        select(Escola).where(Escola.rede_id == rede_id).order_by(Escola.nome)
    ).scalars().all()
    oficiais = _ler_oficiais(conteudo, nome, linha_dados=linha_dados,
                             col_inep=col_inep, col_nome=col_nome,
                             col_municipio=col_municipio, col_valor=col_valor)

    propostas: list[dict] = []
    for e in escolas:
        alvo = _tokens(e.nome)
        muni_e = _norm(e.cidade or "")
        base = {"escola_id": e.id, "escola_nome": e.nome, "cidade": e.cidade,
                "ja_tem": e.codigo_inep}
        vazio = {**base, "inep": None, "nome_oficial": None,
                 "municipio_oficial": None, "valor": None, "confianca": "nenhum"}
        if not alvo:
            propostas.append(vazio)
            continue
        # 1) candidatos no MESMO município cujo nome CONTÉM todos os tokens da escola
        no_muni = [o for o in oficiais if muni_e and o[1] == muni_e and alvo <= o[0]]
        candidatos, escopo = (no_muni, "alta") if no_muni else (
            [o for o in oficiais if alvo <= o[0]], "revisar")  # 2) sem município
        if not candidatos:
            propostas.append(vazio)
            continue
        # melhor = o nome oficial MAIS PRÓXIMO (menos tokens sobrando)
        candidatos.sort(key=lambda o: len(o[0] - alvo))
        melhor = candidatos[0]
        # "alta" só com evidência de UNICIDADE no município: um único candidato, ou
        # um único nome oficial IDÊNTICO (tokens iguais). 2+ nomes que contêm todos
        # os tokens da escola ⇒ "revisar" — nunca escolher a errada em silêncio.
        exatos = [o for o in candidatos if o[0] == alvo]
        unico = escopo == "alta" and (len(candidatos) == 1 or len(exatos) == 1)
        propostas.append({**base, "inep": melhor[3], "nome_oficial": melhor[4],
                          "municipio_oficial": melhor[2], "valor": melhor[5],
                          "confianca": "alta" if unico else "revisar"})
    return propostas
