"""Avaliações externas: catálogo, leitura de planilha e importação de resultados.

MVP = IMPORTAÇÃO DE ARQUIVO OFICIAL (não há API oficial em nenhuma das fontes). O
importador é robusto de propósito: lê o arquivo, devolve a grade crua para a tela
deixar o gestor escolher a LINHA do cabeçalho/dados e MAPEAR as colunas por índice
(planilhas do INEP/SEDUC têm pré-âmbulo e nomes de coluna que mudam entre edições).
O casamento com a escola é pelo CÓDIGO INEP — nunca pelo nome. Só grava os níveis
que o arquivo fornece; o resto fica nulo (nunca inventa).
"""
from __future__ import annotations

import csv
import io
from itertools import islice
from typing import Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AvaliacaoExterna, Escola, ResultadoAvaliacao

# Teto rígido de linhas processadas na importação — barra decompression-bomb de
# XLSX (arquivo pequeno comprimido que declara milhões de linhas). Muito acima de
# qualquer arquivo real por escola (o país tem ~200 mil escolas).
_MAX_LINHAS_IMPORT = 1_000_000

# Catálogo inicial (extensível: adicionar aqui + um mapeamento na tela). O IDEB
# entra como INDICADOR (derivado), separado das avaliações de desempenho.
CATALOGO = {
    "saeb": {"nome": "SAEB", "tipo": "avaliacao", "orgao": "INEP",
             "descricao": "Sistema de Avaliação da Educação Básica (proficiência em escala SAEB)."},
    "ideb": {"nome": "IDEB", "tipo": "indicador", "orgao": "INEP",
             "descricao": "Índice derivado: desempenho (SAEB) × fluxo (aprovação). Não é medição direta."},
    "saresp": {"nome": "SARESP", "tipo": "avaliacao", "orgao": "SEDUC-SP",
               "descricao": "Avaliação de rendimento da rede estadual de São Paulo."},
    "crianca_alfabetizada": {"nome": "Criança Alfabetizada", "tipo": "avaliacao", "orgao": "INEP / CAEd",
                             "descricao": "Avaliação de alfabetização (2º ano do EF)."},
}


def obter_avaliacao(db: Session, chave: str) -> AvaliacaoExterna:
    """Linha do catálogo para a chave (cria sob demanda a partir de CATALOGO).
    Assim funciona igual em create_all (testes), dev e produção, sem seed."""
    av = db.execute(
        select(AvaliacaoExterna).where(AvaliacaoExterna.chave == chave)
    ).scalar_one_or_none()
    if av is not None:
        return av
    meta = CATALOGO.get(chave, {"nome": chave, "tipo": "avaliacao", "orgao": None, "descricao": None})
    av = AvaliacaoExterna(chave=chave, nome=meta["nome"], tipo=meta["tipo"],
                          orgao=meta.get("orgao"), descricao=meta.get("descricao"))
    db.add(av)
    db.flush()
    return av


# --- Leitura de planilha (XLSX/CSV) -----------------------------------------

def _nao_vazia(linha: list) -> bool:
    return any(c is not None and str(c).strip() for c in linha)


def _iterar_grade(conteudo: bytes, nome: str) -> Iterator[list]:
    """GERA as linhas não-vazias do arquivo (1ª aba do XLSX, ou CSV) em STREAMING
    — não materializa a grade inteira (senão um XLSX comprimido explodiria em
    memória). Nunca levanta por conteúdo: arquivo ilegível → não gera nada."""
    nome_l = (nome or "").lower()
    try:
        if nome_l.endswith((".xlsx", ".xlsm")):
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
            try:
                for row in wb.active.iter_rows(values_only=True):
                    linha = list(row)
                    if _nao_vazia(linha):
                        yield linha
            finally:
                wb.close()
        else:
            texto = conteudo.decode("utf-8-sig", errors="replace")
            delim = ";" if texto[:8192].count(";") >= texto[:8192].count(",") else ","
            for r in csv.reader(io.StringIO(texto), delimiter=delim):
                if _nao_vazia(r):
                    yield list(r)
    except Exception:  # noqa: BLE001 — arquivo corrompido/inesperado: para de gerar
        return


def analisar_planilha(conteudo: bytes, nome: str, amostra: int = 20) -> dict:
    """Grade CRUA das primeiras linhas — a tela usa para o gestor escolher a linha
    dos dados e mapear as colunas (por índice). Robusto a pré-âmbulo/edição. Lê só
    ``amostra`` linhas (não a grade inteira) — barato mesmo com arquivo enorme."""
    grade = list(islice(_iterar_grade(conteudo, nome), amostra))
    n_colunas = max((len(r) for r in grade), default=0)
    def _cel(v):
        return "" if v is None else str(v).strip()
    return {
        "linhas_lidas": len(grade),   # amostra (pode haver mais linhas no arquivo)
        "n_colunas": n_colunas,
        "primeiras_linhas": [[_cel(c) for c in r] for r in grade],
    }


# --- Normalização ------------------------------------------------------------

def normalizar_inep(valor) -> str | None:
    """Código INEP em 8 dígitos, ou None. Tolera int-como-float do openpyxl
    ('35012345.0') e separadores; NUNCA levanta."""
    if valor is None:
        return None
    s = str(valor).strip()
    if s.endswith(".0"):
        s = s[:-2]
    s = "".join(ch for ch in s if ch.isdigit())
    if not s:
        return None
    return s.zfill(8)[-8:]


def _num(valor):
    """Número a partir de célula (vírgula decimal, %, marcadores de vazio)."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    s = str(valor).strip().replace("%", "").replace(",", ".")
    if s.lower() in ("", "-", "--", "nd", "*", "...", "—", "s/i", "na"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _cel(linha: list, indice) -> object:
    if indice is None or indice < 0 or indice >= len(linha):
        return None
    return linha[indice]


def _dimensao(linha: list, col: int | None, fixo: str | None) -> str | None:
    """Valor de uma dimensão (etapa/componente/turma): da coluna mapeada, ou o
    valor fixo, ou None. Célula VAZIA/ausente vira NULL — nunca a string 'None'
    (senão inventaria um nível que a fonte não deu e quebraria a idempotência)."""
    if col is not None:
        v = _cel(linha, col)
        if v is None:
            return None
        return str(v).strip() or None
    if fixo:
        return str(fixo).strip() or None
    return None


# --- Importação --------------------------------------------------------------

def importar_resultados(
    db: Session, conteudo: bytes, nome: str, *,
    avaliacao_chave: str, edicao: int, indicador: str, unidade: str,
    linha_dados: int, col_inep: int, col_valor: int,
    col_etapa: int | None = None, col_componente: int | None = None,
    col_turma: int | None = None, etapa_fixa: str | None = None,
    componente_fixo: str | None = None,
    escopo_escolas: set[int] | None = None,
) -> dict:
    """Grava os resultados do arquivo, casando escola por CÓDIGO INEP.

    ``linha_dados`` = índice (0-based, sobre as linhas NÃO-vazias) da primeira
    linha de DADOS (após cabeçalho/pré-âmbulo). Colunas por índice.
    ``escopo_escolas`` = ids elegíveis (rede) ou None (global). Idempotente:
    re-importar a mesma (avaliação, edição, indicador) ATUALIZA em vez de duplicar
    (chave: escola+etapa+componente+turma). A idempotência assume imports NÃO
    concorrentes da mesma (avaliação, edição, indicador) — é uma ação de gestão,
    sob demanda; não há corrida esperada.
    """
    avaliacao = obter_avaliacao(db, avaliacao_chave)

    # Índice CÓDIGO INEP -> (escola_id, rede_id), só das escolas do escopo.
    q = select(Escola.id, Escola.rede_id, Escola.codigo_inep).where(
        Escola.codigo_inep.isnot(None))
    if escopo_escolas is not None:
        q = q.where(Escola.id.in_(escopo_escolas))
    por_inep = {}
    for eid, rid, inep in db.execute(q):
        chave = normalizar_inep(inep)
        if chave:
            por_inep[chave] = (eid, rid)

    # Resultados JÁ existentes desta (avaliação, edição, indicador) no escopo, para
    # atualizar em vez de duplicar. Chave: (escola_id, etapa, componente, turma).
    ex_q = select(ResultadoAvaliacao).where(
        ResultadoAvaliacao.avaliacao_id == avaliacao.id,
        ResultadoAvaliacao.edicao == edicao,
        ResultadoAvaliacao.indicador == indicador)
    if escopo_escolas is not None:
        ex_q = ex_q.where(ResultadoAvaliacao.escola_id.in_(escopo_escolas))
    existentes = {
        (r.escola_id, r.etapa, r.componente, r.turma): r
        for r in db.execute(ex_q).scalars()
    }

    fonte = f"{avaliacao.nome} {edicao} — {nome}"[:200]
    inseridos = atualizados = casados = nao_casados = ignorados = processadas = 0
    inep_nao_casados: set[str] = set()
    truncado = False

    # Streaming: pula o pré-âmbulo (linha_dados) e processa até o teto anti-OOM.
    for linha in islice(_iterar_grade(conteudo, nome), linha_dados, None):
        if processadas >= _MAX_LINHAS_IMPORT:
            truncado = True
            break
        processadas += 1
        inep = normalizar_inep(_cel(linha, col_inep))
        valor = _num(_cel(linha, col_valor))
        if inep is None or valor is None:
            ignorados += 1
            continue
        alvo = por_inep.get(inep)
        if alvo is None:
            nao_casados += 1
            if len(inep_nao_casados) < 50:
                inep_nao_casados.add(inep)
            continue
        escola_id, rede_id = alvo
        etapa = _dimensao(linha, col_etapa, etapa_fixa)
        componente = _dimensao(linha, col_componente, componente_fixo)
        turma = _dimensao(linha, col_turma, None)
        casados += 1

        chave = (escola_id, etapa, componente, turma)
        atual = existentes.get(chave)
        if atual is not None:
            atual.valor, atual.unidade, atual.fonte = valor, unidade, fonte
            atual.rede_id, atual.codigo_inep = rede_id, inep
            atualizados += 1
        else:
            novo = ResultadoAvaliacao(
                avaliacao_id=avaliacao.id, edicao=edicao, rede_id=rede_id,
                escola_id=escola_id, codigo_inep=inep, etapa=etapa,
                componente=componente, turma=turma, indicador=indicador,
                valor=valor, unidade=unidade, fonte=fonte)
            db.add(novo)
            existentes[chave] = novo
            inseridos += 1

    return {
        "avaliacao": avaliacao.chave,
        "edicao": edicao,
        "indicador": indicador,
        "linhas_dados": processadas,
        "truncado": truncado,
        "casados": casados,
        "inseridos": inseridos,
        "atualizados": atualizados,
        "nao_casados": nao_casados,
        "ignorados": ignorados,
        "inep_nao_casados_amostra": sorted(inep_nao_casados)[:20],
    }
