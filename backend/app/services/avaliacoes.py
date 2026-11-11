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
import ipaddress
import logging
import socket
import zipfile
from datetime import datetime, timedelta, timezone
from itertools import islice
from typing import Callable, Iterator
from urllib.parse import urlparse

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AvaliacaoExterna, Escola, FonteAvaliacao, ResultadoAvaliacao
from app.services import planilhas
from app.services.codificacao import decodificar_texto

logger = logging.getLogger(__name__)

# Teto rígido de linhas processadas na importação — barra decompression-bomb de
# XLSX (arquivo pequeno comprimido que declara milhões de linhas). Muito acima de
# qualquer arquivo real por escola (o país tem ~200 mil escolas).
_MAX_LINHAS_IMPORT = 1_000_000

# EXIBIÇÃO por chave: vale em TODA saída da API que mostra o nome, o órgão (e a
# descrição) da avaliação, MESMO com a linha antiga do banco dizendo outra coisa —
# `obter_avaliacao` não reescreve linha existente, e aqui não há migração.
# Decisão D1 do dono: a série `crianca_alfabetizada` é uma ESTIMATIVA calculada
# pelo Constela a partir do SARESP do 2º ano (Suficiente + Avançado), por escola —
# NÃO é o Indicador Criança Alfabetizada do INEP (que é da rede). A chave fica. O
# ÓRGÃO segue a mesma regra (o número é do Constela, não do INEP/CAEd) — isso
# reabre a decisão de 2026-08-04, que manteve "INEP / CAEd": PENDE o dono confirmar.
# `nome_curto` é o do eixo do gráfico (o nome inteiro não cabe na altura dele).
# Reverter = tirar a entrada daqui: a API volta ao que está no banco, e o CATALOGO
# e o rótulo do preset (routers/avaliacoes.py) caem no texto anterior à D1, sem
# quebrar o import. MAS a instalação criada com a entrada já gravou o rótulo novo
# na linha do catálogo (e o mantém: lá, voltar exige corrigir a linha), e a `dica`
# do preset é texto à parte.
_EXIBICAO: dict[str, dict[str, str]] = {
    "crianca_alfabetizada": {
        "nome": "Estimativa Constela de alfabetização (SARESP 2º ano) — não é o indicador oficial",
        "nome_curto": "Estimativa Constela (SARESP 2º ano)",
        "orgao": "Constela (estimativa a partir do SARESP)",
        "descricao": "Cálculo do Constela, por escola, a partir do SARESP do 2º ano "
                     "(Suficiente + Avançado). NÃO é o Indicador Criança Alfabetizada do "
                     "INEP: o oficial é da rede (município) e entrará como série separada.",
    },
}


def nome_exibicao(chave: str, nome: str | None) -> str | None:
    """Nome que a API MOSTRA para a avaliação (o do banco, salvo em `_EXIBICAO`)."""
    return _EXIBICAO.get(chave, {}).get("nome", nome)


def nome_curto_exibicao(chave: str, nome: str | None) -> str | None:
    """Nome para espaço curto (eixo do gráfico): o `nome_curto`, senão o de exibição."""
    return _EXIBICAO.get(chave, {}).get("nome_curto", nome_exibicao(chave, nome))


def orgao_exibicao(chave: str, orgao: str | None) -> str | None:
    """Órgão que a API MOSTRA (o do banco, salvo em `_EXIBICAO`)."""
    return _EXIBICAO.get(chave, {}).get("orgao", orgao)


def descricao_exibicao(chave: str, descricao: str | None) -> str | None:
    """Descrição que a API MOSTRA (a do banco, salvo em `_EXIBICAO`)."""
    return _EXIBICAO.get(chave, {}).get("descricao", descricao)


# Catálogo inicial (extensível: adicionar aqui + um mapeamento na tela). O IDEB
# entra como INDICADOR (derivado), separado das avaliações de desempenho.
CATALOGO = {
    "saeb": {"nome": "SAEB", "tipo": "avaliacao", "orgao": "INEP",
             "descricao": "Sistema de Avaliação da Educação Básica (proficiência em escala SAEB)."},
    "ideb": {"nome": "IDEB", "tipo": "indicador", "orgao": "INEP",
             "descricao": "Índice derivado: desempenho (SAEB) × fluxo (aprovação). Não é medição direta."},
    # A descrição antiga dizia "rede estadual": o SARESP cobre também as redes
    # municipais que aderem. A linha já gravada é corrigida pela migração 0035.
    "saresp": {"nome": "SARESP", "tipo": "avaliacao", "orgao": "SEDUC-SP",
               "descricao": "Sistema de Avaliação de Rendimento Escolar do Estado de São "
                            "Paulo (SEDUC-SP): rede estadual e redes municipais que aderem "
                            "(proficiência em escala SARESP)."},
    # Instalação nova já nasce com o rótulo da D1 (a antiga é coberta por `_EXIBICAO`);
    # sem a entrada lá, cai no texto anterior à D1 (o 2º argumento).
    "crianca_alfabetizada": {
        "nome": nome_exibicao("crianca_alfabetizada", "Criança Alfabetizada"),
        "tipo": "avaliacao",
        "orgao": orgao_exibicao("crianca_alfabetizada", "INEP / CAEd"),
        "descricao": descricao_exibicao("crianca_alfabetizada",
                                        "Avaliação de alfabetização (2º ano do EF)."),
    },
    # CAEd como FONTE/tipo próprio (decisão do dono 2026-08-04): as avaliações do CAEd
    # entram como avaliações SEPARADAS, sem alterar a série `crianca_alfabetizada`
    # (chave e dados seguem; só o RÓTULO e o órgão exibidos mudaram, pela D1).
    # Ainda SEM preset de import de 1 clique — o mapeamento de colunas será travado
    # com o ARQUIVO OFICIAL de cada avaliação (não inventar formato); a tela já
    # permite importar por mapeamento manual quando o arquivo existir.
    "caed_fluencia": {"nome": "CAEd — Fluência Leitora", "tipo": "avaliacao", "orgao": "CAEd",
                      "descricao": "Fluência leitora aplicada pelo CAEd. Mapeamento de "
                                   "importação a configurar com o arquivo oficial."},
    "caed_diagnostica": {"nome": "CAEd — Avaliação Diagnóstica", "tipo": "avaliacao", "orgao": "CAEd",
                         "descricao": "Avaliação diagnóstica do CAEd. Mapeamento de "
                                      "importação a configurar com o arquivo oficial."},
    # O ICA OFICIAL (etapa E2 dos indicadores): número da REDE, não da escola. Os
    # resultados ficam em `indicadores_referencia` (município, UF e Brasil), com
    # importação própria (services/indicadores) — nunca em `resultados_avaliacao`.
    "ica": {"nome": "Indicador Criança Alfabetizada (ICA)", "tipo": "indicador", "orgao": "INEP",
            "descricao": "Indicador oficial do Compromisso Nacional Criança Alfabetizada: "
                         "percentual de alunos do 2º ano da REDE municipal com 743 pontos ou "
                         "mais na escala Saeb de Língua Portuguesa. É da rede (município); "
                         "não existe por escola."},
    # O IEE da SEDUC (etapa E4): nota, meta e cumprimento da meta POR ESCOLA da rede
    # municipal, a partir do SARESP do 2º e do 5º ano. Fica em
    # `indicadores_referencia` (abrangência escola), com importação própria — a
    # proficiência oficial do SARESP que vem no mesmo arquivo vai para
    # `resultados_avaliacao` (chave `saresp`).
    "iee": {"nome": "Índice de Excelência Educacional (IEE)", "tipo": "indicador",
            "orgao": "SEDUC-SP",
            "descricao": "Índice da SEDUC-SP por escola municipal, calculado a partir do "
                         "SARESP do 2º e do 5º ano: nota, meta da escola e cumprimento da "
                         "meta. Não é proficiência."},
}

# Chaves com fluxo PRÓPRIO, com prévia e desfazer, em `services/indicadores`: não
# entram na importação por escola (upload manual, robô) nem no seletor dela. O ICA
# só existe por território (município/UF/Brasil); o IEE vem do arquivo oficial da
# SEDUC, junto com a proficiência e a participação do SARESP.
SO_REFERENCIA = frozenset({"ica", "iee"})

# SAEB e SARESP gravam a SÉRIE avaliada como etapa (0035): "5_ano" (e "2_ano" no
# SARESP). "anos_iniciais" fica para o IDEB — numa série do SAEB/SARESP ele criaria
# uma série paralela à normalizada (e, no SARESP, misturaria o 2º com o 5º ano).
_ETAPA_POR_SERIE = frozenset({"saeb", "saresp"})
_MSG_ETAPA_POR_SERIE = ("Para o SAEB e o SARESP, a etapa é a SÉRIE avaliada: use “5_ano” (ou "
                        "“2_ano” no SARESP), não “anos_iniciais” — esse rótulo fica para o "
                        "IDEB. Nada foi gravado.")


def _eh_anos_iniciais(etapa) -> bool:
    """'anos_iniciais', 'Anos Iniciais', 'anos-iniciais' → True (o rótulo do IDEB)."""
    return "_".join(str(etapa or "").replace("-", " ").casefold().split()) == "anos_iniciais"


def exigir_etapa_por_serie(avaliacao_chave: str, etapa) -> None:
    """LEVANTA ``ImportacaoRecusada`` se a etapa de um SAEB/SARESP for "anos_iniciais".
    Vale para a importação manual, o 1 clique, o robô e o cadastro da receita dele."""
    if avaliacao_chave in _ETAPA_POR_SERIE and _eh_anos_iniciais(etapa):
        raise ImportacaoRecusada(_MSG_ETAPA_POR_SERIE)


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


# Teto do arquivo INTERNO descomprimido de um ZIP — barra zip-bomb (os arquivos
# oficiais por escola têm poucos MB; 150MB é folga larga).
_MAX_ZIP_INTERNO = 150 * 1024 * 1024

# Planilha inflada (bomba de descompressão) — a defesa única é
# ``planilhas.exigir_xlsx_contido``, conferida ANTES do openpyxl, com teto próprio:
# o .xlsx do Ideb por escola é GRANDE (~50 MB comprimidos, 126 colunas, ~65 mil
# escolas). Numa planilha fictícia no mesmo formato, o XML descomprimido dá ~8x o
# comprimido — ~400 MB para o arquivo real —; 1 GB dá folga e ainda barra o abuso. A
# razão de compressão (``planilhas.XLSX_MAX_RAZAO``) vale sempre. A aba é lida em
# streaming (``read_only``); o que o openpyxl carrega INTEIRO é a tabela de textos
# (sharedStrings) — nomes de escola e de município, alguns MB no arquivo real —, que
# tem teto próprio: dentro do 1 GB, uma tabela de centenas de MB derrubaria o worker.
_MB = 1024 * 1024
_XLSX_MAX_DESCOMPRIMIDO = 1024 * _MB
_XLSX_MAX_TEXTOS = 64 * _MB
_MAX_TIPOS_DE_CONTEUDO = _MB     # [Content_Types].xml: poucos KB numa planilha real
# A leitura das linhas não passa do limite do Excel (a dimensão declarada e o número
# da linha no XML são do próprio arquivo) nem de ``planilhas.MAX_COLUNAS_LIDAS``
# colunas (o arquivo do INEP tem 126).
_MAX_LINHAS_EXCEL = 1_048_576


def exigir_xlsx_contido(conteudo: bytes, max_total: int | None = None) -> None:
    """Recusa (``ImportacaoRecusada``, 400 nas rotas) o .xlsx inflado ANTES de o
    openpyxl abri-lo: ``planilhas.exigir_xlsx_contido`` (partes, compactação, razão e
    o descomprimido real) com o teto ``max_total`` (padrão: o das avaliações), e a
    tabela de textos (sharedStrings) até ``_XLSX_MAX_TEXTOS``. O que não é zip legível
    passa: o openpyxl recusa como sempre."""
    if max_total is None:
        max_total = _XLSX_MAX_DESCOMPRIMIDO
    try:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as pacote:
            declarado = sum(info.file_size for info in pacote.infolist())
    except Exception:  # noqa: BLE001 — não é zip legível: o leitor da planilha recusa
        return
    if declarado > max_total:
        raise ImportacaoRecusada(
            f"A planilha passa de {max_total // _MB} MB depois de descompactada e foi "
            "recusada. Confira se é o arquivo oficial, como baixado, e envie de novo. "
            "Nada foi gravado.")
    try:
        planilhas.exigir_xlsx_contido(conteudo, max_total=max_total)
    except planilhas.PlanilhaRecusada as exc:
        raise ImportacaoRecusada(f"{exc} Nada foi gravado.") from exc
    _exigir_textos_contidos(conteudo)


def _exigir_textos_contidos(conteudo: bytes) -> None:
    """A tabela de textos que o openpyxl vai carregar inteira — achada como ele a acha
    (``ExcelReader.read_strings``: o Override de [Content_Types].xml com o tipo de
    sharedStrings) — não passa de ``_XLSX_MAX_TEXTOS``. O tamanho declarado basta: a
    leitura do zip para nele (e confere o CRC). Roda DEPOIS da guarda única, que já
    recusou a compactação sem teto por leitura."""
    from openpyxl.packaging.manifest import Manifest
    from openpyxl.xml.constants import ARC_CONTENT_TYPES, SHARED_STRINGS
    from openpyxl.xml.functions import fromstring

    try:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as pacote:
            with pacote.open(ARC_CONTENT_TYPES) as entrada:
                tipos = entrada.read(_MAX_TIPOS_DE_CONTEUDO + 1)
            if len(tipos) > _MAX_TIPOS_DE_CONTEUDO:
                raise ImportacaoRecusada(
                    "A planilha tem a estrutura interna fora do normal e foi recusada. "
                    "Abra o arquivo no Excel, salve de novo e envie outra vez. Nada foi "
                    "gravado.")
            parte = Manifest.from_tree(fromstring(tipos)).find(SHARED_STRINGS)
            if parte is None:
                return
            tamanho = pacote.getinfo(parte.PartName[1:]).file_size
    except ImportacaoRecusada:
        raise
    except Exception:  # noqa: BLE001 — pacote incompleto/ilegível: o openpyxl recusa
        return
    if tamanho > _XLSX_MAX_TEXTOS:
        raise ImportacaoRecusada(
            f"A tabela de textos da planilha passa de {_XLSX_MAX_TEXTOS // _MB} MB e foi "
            "recusada — muito maior que a de um arquivo oficial. Confira se é o arquivo "
            "certo, como baixado, e envie de novo. Nada foi gravado.")


def _linhas_xlsx(conteudo: bytes) -> Iterator[list]:
    """As linhas da 1ª aba com teto do que é PERCORRIDO: no máximo
    ``_MAX_LINHAS_EXCEL`` linhas e ``planilhas.MAX_COLUNAS_LIDAS`` colunas, passados
    ao openpyxl — a dimensão declarada (A1:XFD1048576 em 2 KB) e o número da linha no
    XML não alargam a leitura. Com dimensão declarada, cada linha tem a largura dela
    (até o teto), como antes; sem, vai até a última célula preenchida. A linha toda
    vazia é pulada sem custo em Python (``count`` roda em C)."""
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    try:
        aba = wb.active
        declaradas = aba.max_column
        max_col = min(declaradas or planilhas.MAX_COLUNAS_LIDAS, planilhas.MAX_COLUNAS_LIDAS)
        max_row = min(aba.max_row or _MAX_LINHAS_EXCEL, _MAX_LINHAS_EXCEL)
        for row in aba.iter_rows(values_only=True, max_row=max_row, max_col=max_col):
            fim = len(row)
            if row.count(None) == fim:
                continue
            if not declaradas:
                while row[fim - 1] is None:
                    fim -= 1
            yield list(row[:fim])
    finally:
        wb.close()


def _iterar_grade(conteudo: bytes, nome: str) -> Iterator[list]:
    """GERA as linhas não-vazias do arquivo (1ª aba do XLSX, ou CSV) em STREAMING
    — não materializa a grade inteira (senão um XLSX comprimido explodiria em
    memória). Arquivos oficiais do INEP vêm em ZIP: extrai o 1º XLSX/CSV de dentro.
    Arquivo ilegível → não gera nada. LEVANTA ``ImportacaoRecusada`` (antes da 1ª
    linha, nada gravado) só para o .xlsx inflado (``exigir_xlsx_contido``)."""
    nome_l = (nome or "").lower()
    if nome_l.endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(conteudo)) as zf:
                interno = next(
                    (n for n in zf.namelist()
                     if n.lower().endswith((".xlsx", ".xlsm", ".csv"))
                     and not n.startswith("__MACOSX")),
                    None)
                if interno is None or zf.getinfo(interno).file_size > _MAX_ZIP_INTERNO:
                    return
                dados = zf.read(interno)
        except Exception:  # noqa: BLE001 — zip corrompido: não gera nada
            return
        yield from _iterar_grade(dados, interno)  # recursa com o arquivo de dentro
        return
    eh_xlsx = nome_l.endswith((".xlsx", ".xlsm"))
    if eh_xlsx:
        exigir_xlsx_contido(conteudo)   # fora do try: a recusa chega a quem chamou
    try:
        if eh_xlsx:
            for linha in _linhas_xlsx(conteudo):
                if _nao_vazia(linha):
                    yield linha
        else:
            # O CSV do Excel em português vem em Windows-1252 (e o "Texto Unicode" em
            # UTF-16): o componente lido da coluna é chave gravada.
            texto = decodificar_texto(conteudo)
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


class ImportacaoRecusada(ValueError):
    """Importação recusada ANTES de gravar qualquer linha (layout que não confere,
    cadastro ambíguo). A mensagem vai como está para a tela (HTTP 400)."""


# --- Layout oficial do INEP (Ideb/Saeb por escola) --------------------------

# A planilha oficial tem pré-âmbulo e cabeçalho em várias linhas; a ÚLTIMA delas é
# a linha TÉCNICA, com os nomes das variáveis (SG_UF, ID_ESCOLA, VL_OBSERVADO_2023...).
# Ela é procurada só no topo do arquivo (em 2023 é a 8ª linha não-vazia).
_LINHAS_TOPO_INEP = 20


def localizar_colunas_inep(conteudo: bytes, nome: str, exigidas: list[str], *,
                           marcadores_etapa: tuple[str, ...],
                           arquivo_esperado: str) -> tuple[int, dict[str, int]]:
    """Acha a linha técnica (a que contém a célula ``ID_ESCOLA``) nas primeiras
    linhas não-vazias e localiza cada variável ``exigidas`` PELO NOME. Devolve
    ``(linha_dados, {variável: índice})`` — os dados começam na linha não-vazia
    seguinte à técnica, no mesmo índice que ``importar_resultados`` usa.

    A ETAPA também é conferida: os arquivos de Anos Iniciais, Anos Finais e Ensino
    Médio usam os MESMOS nomes de variável (VL_OBSERVADO_2023 em todos); só o topo
    diz a etapa ("Ensino Fundamental Regular - Anos Iniciais", "1º ao 5º ano").
    Alguma célula ACIMA da linha técnica tem de conter um dos ``marcadores_etapa``
    (sem diferenciar maiúsculas) — senão o arquivo de outra etapa gravaria por cima
    da série desta (a chave é escola+etapa+componente+turma).

    LEVANTA ``ImportacaoRecusada`` se a linha técnica não existir, se o topo não
    trouxer a etapa, se faltar uma variável ou se ela aparecer repetida. NUNCA cai
    de volta para posição fixa: a edição seguinte insere colunas novas em cada
    bloco, e ler pela posição de 2023 gravaria outra variável como se fosse a
    edição escolhida. ``arquivo_esperado`` completa a mensagem ("confira se é ...")."""
    topo: list[str] = []   # células das linhas acima da técnica (pré-âmbulo + cabeçalho)
    for i, linha in enumerate(islice(_iterar_grade(conteudo, nome), _LINHAS_TOPO_INEP)):
        nomes = ["" if c is None else str(c).strip().upper() for c in linha]
        if "ID_ESCOLA" not in nomes:
            topo.extend(str(c).casefold() for c in linha if c is not None)
            continue
        if not any(m.casefold() in celula for celula in topo for m in marcadores_etapa):
            marcas = " nem ".join(f'"{m}"' for m in marcadores_etapa)
            raise ImportacaoRecusada(
                f"O cabeçalho do arquivo não indica a etapa esperada (não traz {marcas}); "
                f"confira se é {arquivo_esperado}. Nada foi gravado.")
        indices: dict[str, int] = {}
        faltam, repetidas = [], []
        for variavel in exigidas:
            posicoes = [j for j, n in enumerate(nomes) if n == variavel.upper()]
            if not posicoes:
                faltam.append(variavel)
            elif len(posicoes) > 1:
                repetidas.append(variavel)
            else:
                indices[variavel] = posicoes[0]
        if faltam:
            raise ImportacaoRecusada(
                f"O arquivo não tem a coluna {', '.join(faltam)}; confira se é "
                f"{arquivo_esperado}. Nada foi gravado.")
        if repetidas:
            raise ImportacaoRecusada(
                f"A coluna {', '.join(repetidas)} aparece mais de uma vez no arquivo; "
                f"confira se é {arquivo_esperado}. Nada foi gravado.")
        return i + 1, indices
    raise ImportacaoRecusada(
        "Não encontrei a linha técnica do INEP (a que tem a coluna ID_ESCOLA) no "
        f"começo do arquivo; confira se é {arquivo_esperado}. Nada foi gravado.")


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

    LEVANTA ``ImportacaoRecusada`` (antes de gravar qualquer coisa) se duas escolas
    do escopo tiverem o MESMO código INEP normalizado: casar com uma delas seria
    escolher em silêncio de quem é o resultado — e se a etapa de um SAEB/SARESP for
    "anos_iniciais" (desde a 0035 a etapa deles é a série: "5_ano"/"2_ano"), seja a
    etapa fixa, seja a lida da COLUNA (``col_etapa``) em qualquer linha com INEP e
    valor: o arquivo inteiro é recusado antes de gravar a 1ª linha.

    Linha que veio de uma importação OFICIAL com prévia (``importacao_id``) NÃO é
    sobrescrita pela importação manual: fica como está e é contada em
    ``mantidos_oficiais`` (trocá-la é pela importação oficial — prévia e desfazer).
    """
    if col_etapa is None:
        exigir_etapa_por_serie(avaliacao_chave, etapa_fixa)
    elif avaliacao_chave in _ETAPA_POR_SERIE:
        # A etapa vem célula a célula: confere o arquivo TODO antes de gravar (o laço
        # de baixo grava enquanto lê, e o robô não desfaz o que já entrou na sessão).
        recusadas = sum(
            1 for linha in islice(_iterar_grade(conteudo, nome), linha_dados,
                                  linha_dados + _MAX_LINHAS_IMPORT)
            if normalizar_inep(_cel(linha, col_inep)) is not None
            and _num(_cel(linha, col_valor)) is not None
            and _eh_anos_iniciais(_dimensao(linha, col_etapa, None)))
        if recusadas:
            raise ImportacaoRecusada(
                f"{recusadas} linha(s) do arquivo trazem “anos_iniciais” na coluna da "
                f"etapa. {_MSG_ETAPA_POR_SERIE}")
    # Índice CÓDIGO INEP -> (escola_id, rede_id), só das escolas do escopo.
    q = select(Escola.id, Escola.rede_id, Escola.codigo_inep, Escola.nome).where(
        Escola.codigo_inep.isnot(None))
    if escopo_escolas is not None:
        q = q.where(Escola.id.in_(escopo_escolas))
    por_inep = {}
    nomes_por_inep: dict[str, list[str]] = {}
    for eid, rid, inep, nome_escola in db.execute(q.order_by(Escola.nome, Escola.id)):
        chave = normalizar_inep(inep)
        if chave:
            por_inep[chave] = (eid, rid)
            nomes_por_inep.setdefault(chave, []).append(nome_escola)
    duplicados = {k: v for k, v in nomes_por_inep.items() if len(v) > 1}
    if duplicados:
        lista = "; ".join(f"{k} ({', '.join(v)})" for k, v in sorted(duplicados.items()))
        raise ImportacaoRecusada(
            "Importação recusada: o mesmo código INEP está cadastrado em mais de uma "
            f"escola — {lista}. Corrija o cadastro (cada escola com o seu INEP) e "
            "importe de novo. Nada foi gravado.")

    avaliacao = obter_avaliacao(db, avaliacao_chave)

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
    mantidos_oficiais = 0
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
            inep_nao_casados.add(inep)   # TODOS (a tela decide quanto mostrar)
            continue
        escola_id, rede_id = alvo
        etapa = _dimensao(linha, col_etapa, etapa_fixa)
        componente = _dimensao(linha, col_componente, componente_fixo)
        turma = _dimensao(linha, col_turma, None)
        casados += 1

        chave = (escola_id, etapa, componente, turma)
        atual = existentes.get(chave)
        if atual is not None and atual.importacao_id is not None:
            mantidos_oficiais += 1        # número oficial (com prévia): não se mexe aqui
            continue
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
        "nao_casados": nao_casados,          # linhas (com INEP e valor) sem escola
        "ignorados": ignorados,
        # linhas casadas que JÁ têm o número oficial (importação com prévia): mantidas
        "mantidos_oficiais": mantidos_oficiais,
        # A lista COMPLETA dos códigos (distintos) sem escola no escopo — antes era
        # uma amostra de 20 e o gestor não tinha como conferir o resto.
        "inep_nao_casados": sorted(inep_nao_casados),
    }


def resumo_para_auditoria(resumo: dict) -> dict:
    """O resumo SEM a lista completa de códigos não casados (o arquivo nacional do
    INEP tem ~65 mil escolas — a trilha de auditoria guarda a contagem, e uma
    amostra, não o arquivo inteiro). A resposta da API segue com a lista toda."""
    saida = {k: v for k, v in resumo.items() if k != "inep_nao_casados"}
    if "inep_nao_casados" in resumo:
        saida["inep_nao_casados_amostra"] = resumo["inep_nao_casados"][:20]
    return saida


# --- Correlação / evolução (cruzar avaliação × engajamento) -------------------

def _escolas_da_rede_ids(db: Session, rede_id: int) -> list[int]:
    return list(db.execute(select(Escola.id).where(Escola.rede_id == rede_id)).scalars())


def opcoes_rede(db: Session, rede_id: int) -> list[dict]:
    """As séries de avaliação que EXISTEM para as escolas da rede — por
    (avaliação, indicador, etapa, componente) e as edições presentes. A tela usa
    para montar os seletores sem oferecer combinação vazia.

    Só linhas de ESCOLA com VALOR (desde a 0035): a ausência registrada (valor
    nulo + motivo) não cria série nem edição. Nunca lê `indicadores_referencia`:
    metas, níveis e números de município/UF/Brasil não entram aqui."""
    ids = _escolas_da_rede_ids(db, rede_id)
    if not ids:
        return []
    linhas = db.execute(
        select(AvaliacaoExterna.chave, AvaliacaoExterna.nome, AvaliacaoExterna.tipo,
               ResultadoAvaliacao.indicador, ResultadoAvaliacao.etapa,
               ResultadoAvaliacao.componente, ResultadoAvaliacao.edicao)
        .join(ResultadoAvaliacao, ResultadoAvaliacao.avaliacao_id == AvaliacaoExterna.id)
        .where(ResultadoAvaliacao.escola_id.in_(ids),
               ResultadoAvaliacao.valor.isnot(None))
        .distinct()
    ).all()
    series: dict[tuple, dict] = {}
    for chave, nome, tipo, indicador, etapa, componente, edicao in linhas:
        k = (chave, indicador, etapa, componente)
        s = series.setdefault(k, {
            "avaliacao": chave, "nome": nome_exibicao(chave, nome), "tipo": tipo,
            "indicador": indicador,
            "etapa": etapa, "componente": componente, "edicoes": set()})
        s["edicoes"].add(edicao)
    saida = []
    for s in series.values():
        s = {**s, "edicoes": sorted(s["edicoes"], reverse=True)}
        saida.append(s)
    saida.sort(key=lambda s: (s["nome"], s["indicador"] or "", s["etapa"] or "",
                              s["componente"] or ""))
    return saida


def _pearson(pares: list[tuple[float, float]]) -> float | None:
    """Correlação de Pearson de uma lista de (x, y). None se n<3 ou variância nula
    (sem correlação definível — a tela mostra 'dados insuficientes')."""
    n = len(pares)
    if n < 3:
        return None
    mx = sum(x for x, _ in pares) / n
    my = sum(y for _, y in pares) / n
    sxy = sum((x - mx) * (y - my) for x, y in pares)
    sxx = sum((x - mx) ** 2 for x, _ in pares)
    syy = sum((y - my) ** 2 for _, y in pares)
    if sxx <= 0 or syy <= 0:
        return None
    return round(sxy / (sxx ** 0.5 * syy ** 0.5), 3)


def correlacao_rede(db: Session, rede_id: int, *, avaliacao_chave: str, indicador: str,
                    edicao: int, etapa: str | None = None, componente: str | None = None,
                    metrica: str = "pontuacao_geral") -> dict:
    """Cruza, por ESCOLA da rede, o valor da avaliação (edição escolhida) com o
    ENGAJAMENTO nas plataformas. Devolve os pontos do gráfico de dispersão, a
    correlação de Pearson e a EVOLUÇÃO histórica (média da rede por edição).
    NUNCA afirma causalidade — a tela deixa isso explícito.

    O eixo X padrão é ``pontuacao_geral`` (índice per capita 0–1000, comparável
    entre escolas). Com ``media_geral`` — normalizada contra o P90 de cada escola
    — a dispersão cruzava o SAEB com um número que mede a homogeneidade interna
    da escola, e o Pearson resultante não significava o que a tela dizia."""
    from app.services import rede as svc_rede  # engajamento por escola (reuso)

    if metrica not in ("pontuacao_geral", "media_geral", "adocao"):
        metrica = "pontuacao_geral"
    av = obter_avaliacao(db, avaliacao_chave)
    engaj = {c["escola_id"]: c for c in svc_rede._kpis_da_rede(db, rede_id)}
    ids = _escolas_da_rede_ids(db, rede_id)

    def _filtro(q):
        # ESCOPO da rede (isolamento): só resultados das escolas DESTA rede — senão
        # a evolução somaria escolas de outras redes que importaram a mesma série.
        # Só com VALOR (0035): a ausência (valor nulo + motivo) não é ponto nem conta
        # escola na evolução — ausência ≠ zero, e também não é "uma escola a mais".
        q = q.where(ResultadoAvaliacao.avaliacao_id == av.id,
                    ResultadoAvaliacao.indicador == indicador,
                    ResultadoAvaliacao.escola_id.in_(ids),
                    ResultadoAvaliacao.valor.isnot(None))
        q = q.where(ResultadoAvaliacao.etapa == etapa) if etapa else q.where(
            ResultadoAvaliacao.etapa.is_(None))
        q = q.where(ResultadoAvaliacao.componente == componente) if componente else q.where(
            ResultadoAvaliacao.componente.is_(None))
        return q

    # Valor por ESCOLA (média sobre eventuais turmas) na edição escolhida — 1 ponto
    # por escola, determinístico mesmo se a fonte trouxer resultado por turma.
    valores = {
        eid: v for eid, v in db.execute(
            _filtro(select(ResultadoAvaliacao.escola_id,
                           func.avg(ResultadoAvaliacao.valor)))
            .where(ResultadoAvaliacao.edicao == edicao)
            .group_by(ResultadoAvaliacao.escola_id))
    }
    pontos = []
    for eid, valor in valores.items():
        c = engaj.get(eid)
        if c is None or c.get("alunos_com_dados", 0) <= 0:
            continue  # sem engajamento com dados: não entra na correlação
        x = float(c[metrica])
        pontos.append({"escola_id": eid, "nome": c["nome"], "x": round(x, 1),
                       "y": round(float(valor), 2)})
    pearson = _pearson([(p["x"], p["y"]) for p in pontos])

    # Evolução: média por (escola, edição) e DEPOIS média entre as escolas por
    # edição (ponderação por escola, não por linha) + contagem de escolas DISTINTAS.
    #
    # ESTE NÚMERO É DO CONSTELA, NÃO É OFICIAL: é a média SIMPLES das escolas da
    # rede que têm resultado — não pondera por matrícula/participantes, e nenhum
    # órgão publica "a média das escolas" como número da rede (o oficial da rede,
    # quando existe, vem em ``indicadores_referencia``). E a série pode misturar
    # linhas vindas da importação OFICIAL com prévia (``importacao_id``) e linhas
    # da importação manual/robô legado (sem prévia). Por isso a saída rotula a
    # origem do cálculo e separa por fonte (``evolucao_por_fonte``); ``evolucao``
    # segue igual (todas as linhas com valor) para quem já a consome.
    def _evolucao(filtro_extra=None) -> list[dict]:
        base = _filtro(select(ResultadoAvaliacao.edicao.label("ed"),
                              ResultadoAvaliacao.escola_id.label("eid"),
                              func.avg(ResultadoAvaliacao.valor).label("v")))
        if filtro_extra is not None:
            base = base.where(filtro_extra)
        sub = (base.group_by(ResultadoAvaliacao.edicao, ResultadoAvaliacao.escola_id)
               .subquery())
        ev = db.execute(
            select(sub.c.ed, func.avg(sub.c.v), func.count(sub.c.eid))
            .group_by(sub.c.ed).order_by(sub.c.ed)
        ).all()
        return [{"edicao": e, "media_valor": round(float(m), 2), "escolas": int(n)}
                for e, m, n in ev]

    evolucao = _evolucao()
    evolucao_por_fonte = {
        "importacao_oficial": _evolucao(ResultadoAvaliacao.importacao_id.isnot(None)),
        "sem_previa": _evolucao(ResultadoAvaliacao.importacao_id.is_(None)),
    }

    return {
        "avaliacao": av.chave, "nome": nome_exibicao(av.chave, av.nome), "tipo": av.tipo,
        "nome_curto": nome_curto_exibicao(av.chave, av.nome),   # eixo do gráfico
        "indicador": indicador, "etapa": etapa, "componente": componente,
        "edicao": edicao, "metrica": metrica,
        "pontos": pontos, "n": len(pontos), "pearson": pearson,
        "evolucao": evolucao,
        "evolucao_por_fonte": evolucao_por_fonte,
        "evolucao_origem": "calculado_constela",
        "evolucao_rotulo": ("Média simples das escolas da rede com resultado, calculada "
                            "pelo Constela — não é número oficial da rede."),
        # A própria SÉRIE é uma estimativa do Constela (decisão D1: a
        # "crianca_alfabetizada" por escola não é o indicador do INEP).
        "serie_estimativa_constela": av.chave in _EXIBICAO,
    }


# --- Coleta AUTOMÁTICA (o "robô": baixa o arquivo oficial e importa) ----------

Baixador = Callable[[str], bytes]
_UA_NAVEGADOR = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                 "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
# Teto do arquivo baixado. O IDEB oficial por escola é GRANDE: o ZIP de "anos
# iniciais" 2023 tem ~97 MB (XLSX de ~50 MB dentro, 126 colunas, ~65 mil escolas).
# 150 MB dá folga sobre o real e ainda barra abuso.
_MAX_DOWNLOAD = 150 * 1024 * 1024


def _agora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


_MAX_REDIRECTS = 5


def _exigir_destino_publico(url: str) -> None:
    """Anti-SSRF: só https e host que resolve para IP PÚBLICO (rejeita privado/
    loopback/link-local/reservado/multicast — inclui 169.254.169.254 de metadata).
    Aplicado ANTES de cada conexão, inclusive a cada redirect (revalida o salto)."""
    partes = urlparse(url)
    if partes.scheme != "https":
        raise ValueError(f"esquema não permitido (só https): {partes.scheme or 'vazio'}")
    host = partes.hostname
    if not host:
        raise ValueError("URL sem host")
    try:
        infos = socket.getaddrinfo(host, partes.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValueError(f"host não resolvido: {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise ValueError(f"host aponta para rede não-pública ({ip}): {host}")


def baixar_url(url: str, *, timeout: float = 30.0) -> bytes:
    """Baixa o arquivo oficial (User-Agent de navegador — os portais oficiais
    bloqueiam clientes 'crus'). Guarda anti-SSRF: só https para host público, e os
    redirects são seguidos MANUALMENTE revalidando cada destino (o alvo final não
    fica a cargo do upstream). LEVANTA em erro; o chamador registra o status."""
    cabecalhos = {"User-Agent": _UA_NAVEGADOR, "Accept": "*/*"}
    with httpx.Client(timeout=timeout, follow_redirects=False, headers=cabecalhos) as cli:
        for _ in range(_MAX_REDIRECTS + 1):
            _exigir_destino_publico(url)
            with cli.stream("GET", url) as r:
                if r.is_redirect:
                    destino = r.headers.get("location")
                    if not destino:
                        raise ValueError("redirect sem destino")
                    url = str(r.url.join(destino))  # resolve relativo → absoluto
                    continue
                r.raise_for_status()
                buf = bytearray()
                for chunk in r.iter_bytes():
                    buf += chunk
                    if len(buf) > _MAX_DOWNLOAD:
                        raise ValueError("arquivo excede o teto de download")
                return bytes(buf)
    raise ValueError("excesso de redirects")


def _nome_do_url(url: str) -> str:
    return url.rstrip("/").split("/")[-1] or "arquivo"


def coletar_fonte(db: Session, fonte: FonteAvaliacao,
                  baixador: Baixador | None = None) -> dict:
    """Baixa o arquivo da fonte e importa (MESMA máquina do upload manual), casando
    por INEP globalmente. NUNCA levanta: erro de download/parse vira ultimo_status=
    'erro' (o painel mostra — não quebra em silêncio). ``baixador`` é injetável
    (default = ``baixar_url``, resolvido em tempo de chamada p/ ser testável)."""
    baixador = baixador or baixar_url
    # Serializa com outra coleta simultânea da MESMA fonte (scheduler × "coletar
    # agora"): a 2ª relê os resultados já gravados e ATUALIZA em vez de duplicar.
    from app.core.database import bloquear_fonte_para_coleta
    bloquear_fonte_para_coleta(db, fonte.id)
    av = db.get(AvaliacaoExterna, fonte.avaliacao_id)
    m = fonte.mapeamento or {}
    try:
        conteudo = baixador(fonte.url)
        resumo = importar_resultados(
            db, conteudo, _nome_do_url(fonte.url),
            avaliacao_chave=av.chave, edicao=fonte.edicao,
            indicador=fonte.indicador, unidade=fonte.unidade,
            linha_dados=int(m.get("linha_dados", 0)),
            col_inep=int(m.get("col_inep", 0)), col_valor=int(m.get("col_valor", 0)),
            col_etapa=m.get("col_etapa"), col_componente=m.get("col_componente"),
            col_turma=m.get("col_turma"),
            etapa_fixa=m.get("etapa_fixa"), componente_fixo=m.get("componente_fixo"),
            escopo_escolas=None)  # global: casa qualquer escola da base por código INEP
        # Persistido (e relido a cada listagem): contagem + amostra, como antes.
        resumo = resumo_para_auditoria(resumo)
        fonte.ultimo_status, fonte.ultimo_erro, fonte.ultimo_resumo = "ok", None, resumo
    except Exception as exc:  # noqa: BLE001 — nunca quebra: registra o erro
        fonte.ultimo_status = "erro"
        fonte.ultimo_erro = f"{type(exc).__name__}: {exc}"[:300]
        fonte.ultimo_resumo = {"erro": fonte.ultimo_erro}
    fonte.ultima_coleta = _agora()
    fonte.proxima_coleta = (_agora() + timedelta(days=30)) if fonte.cadencia == "mensal" else None
    return {"status": fonte.ultimo_status, **(fonte.ultimo_resumo or {})}


_VERDADEIRO = frozenset({"1", "true", "sim", "yes", "on"})
_FALSO = frozenset({"", "0", "false", "nao", "não", "no", "off"})
_valores_nao_reconhecidos: set[str] = set()


def robo_habilitado() -> bool:
    """O robô AUTOMÁTICO de avaliações externas pode rodar? DESLIGADO por padrão.

    Por que existe: o robô (``fontes_avaliacao`` + ``coletar_pendentes``) grava
    números SEM prévia e roda embutido no agendador do sync — ligar o agendador
    (``SYNC_SCHEDULER_ENABLED``) ligaria o robô junto, sem ninguém decidir. Os
    indicadores oficiais entram hoje pela importação COM prévia e desfazer
    (``services/indicadores``). Para o robô voltar a rodar, é preciso pedir
    explicitamente: ``AVALIACOES_ROBO_HABILITADO=true`` no ambiente.

    Fonte ÚNICA: ``settings.AVALIACOES_ROBO_HABILITADO`` (ambiente ou ``.env``,
    lido uma vez no boot). Antes, havia também a leitura direta de ``os.environ``
    "até o campo existir" — o campo passou a existir e esse caminho morreu em
    silêncio. É TEXTO e a interpretação é esta: valor fora da lista de "ligado"
    deixa o robô DESLIGADO (fail-closed) e avisa no log uma vez, em vez de
    derrubar o boot como o campo bool fazia com "sim"."""
    valor = str(settings.AVALIACOES_ROBO_HABILITADO or "").strip().lower()
    if valor in _VERDADEIRO:
        return True
    if valor not in _FALSO and valor not in _valores_nao_reconhecidos:
        _valores_nao_reconhecidos.add(valor)
        logger.warning("AVALIACOES_ROBO_HABILITADO com valor não reconhecido: o robô "
                       "de avaliações fica DESLIGADO (use true/false).")
    return False


def coletar_pendentes(db: Session, baixador: Baixador | None = None,
                      limite: int | None = None) -> int:
    """Coleta as fontes ATIVAS com proxima_coleta vencida — chamado pelo scheduler.
    Devolve quantas foram coletadas. ``limite`` é o TETO por rodada (a coleta roda
    embutida na thread do sync; sem teto, muitas fontes — ou uma lenta — poderiam
    estagnar a fila). O que sobrar vai na próxima rodada; a mais antiga vai primeiro.

    Com o robô DESLIGADO (``robo_habilitado``, o padrão) não coleta nada e devolve
    0 — a agenda das fontes fica como está, para quando for religado."""
    if not robo_habilitado():
        return 0
    limite = settings.AVALIACOES_COLETA_POR_RODADA if limite is None else limite
    pendentes = db.execute(
        select(FonteAvaliacao).where(
            FonteAvaliacao.ativo.is_(True),
            FonteAvaliacao.proxima_coleta.isnot(None),
            FonteAvaliacao.proxima_coleta <= _agora(),
        ).order_by(FonteAvaliacao.proxima_coleta).limit(limite)
    ).scalars().all()
    for fonte in pendentes:
        coletar_fonte(db, fonte, baixador)
    if pendentes:
        db.commit()
    return len(pendentes)
