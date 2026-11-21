"""Perfis de relatório PDF — leitura POSICIONAL dos formatos reais.

As estratégias genéricas de `importacao.py` trabalham com texto corrido e
resolvem relatórios colados ou PDFs simples. Os PDFs REAIS do Elefante
Letrado e do Matific, porém, têm layout complexo: nomes quebrados em até
4 linhas, durações fatiadas ("42h" / "09min" / "01s"), cabeçalhos que se
repetem a cada página e títulos de livro que contêm palavras como "Nível".

Nada disso é recuperável com heurísticas de texto. Este módulo lê as
COORDENADAS de cada palavra (pdfplumber) e reconstrói as tabelas:

    palavras com posição (x0, topo)
        │
        ├─ detecção do PERFIL pelo texto compactado (sem espaços/acentos)
        │     "relatoriodeperformancedaturma"     → Elefante · turma
        │     "relatoriodeperformancedoestudante" → Elefante · estudante
        │     "matific" / "atividadesfinalizadas" → Matific
        │
        ├─ cabeçalho: agrupa rótulos por x0 e casa por SEMELHANÇA
        │   (a posição do cabeçalho vira o mapa de colunas da página)
        ├─ registros: linha que preenche várias colunas INICIA um registro;
        │   fragmentos (sobrenomes, "34min", turma quebrada) são costurados
        │   ao registro vizinho pela coluna em que caem
        └─ conversões tolerantes: duração → minutos, número pt-BR, datas

Se nenhum perfil reconhecer o arquivo (formato futuro, plataforma nova),
o fluxo cai automaticamente nas 4 estratégias genéricas — o usuário nunca
fica sem resposta.
"""
from __future__ import annotations

import bisect
import contextvars
import functools
import io
import logging
import re
import threading
import time
import zlib
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from typing import NamedTuple

from app.services import scoring
from app.services.importacao import (
    Analise,
    LinhaImportacao,
    _casar_coluna,
    _eh_coluna_nome,
    _fechar_linha,
    _numero_plausivel,
    _similaridade,
    normalizar_nome,
    valor_plausivel,
)

# Vocabulário OFICIAL de níveis do Elefante (escada A3 AA…Z + tiers Z+ e A+) —
# o MESMO do importador (``routers/importacoes.py``) e do CRUD do catálogo
# (``routers/plataformas.py``). O parser do PDF não pode recusar um nível que o
# resto do sistema aceita: o nível sumiria da linha e a leitura se perderia.
NIVEIS_OFICIAIS: frozenset[str] = frozenset(scoring.NIVEIS_ORDENADOS) | {"Z+", "A+"}

# --------------------------------------------------------------------------
# PDF inflado (bomba de descompressão) — recusa PRÉVIA, antes do pdfplumber
# --------------------------------------------------------------------------
# (A garantia de verdade é o orçamento da análise, mais abaixo: o teto DENTRO do
# pdfminer e do pypdf. Este medidor é um segundo leitor do PDF; ele dá a recusa
# antes de abrir o arquivo, mas onde discordar do pdfminer o orçamento segura.)
#
# O upload só confere o tamanho COMPRIMIDO (10 MB). Dentro do PDF, cada fluxo
# ("stream") pode vir compactado: 10 KB de espaços compactados viram 10 MB, e o
# pdfminer (motor do pdfplumber) descompacta tudo na memória, sem teto — 10 MB
# enviados chegam a ~10 GB e derrubam o processo da API de todas as redes. Aqui,
# ANTES de o pdfplumber abrir o arquivo, cada fluxo é descompactado aos poucos
# e com teto (``zlib.decompressobj().decompress(dado, max_length)``), somando o
# que ele de fato vira; o arquivo é recusado assim que a soma passa do teto. Só
# depois disso o pdfplumber abre o arquivo, e as páginas são contadas (a árvore
# de páginas do próprio pdfminer) antes de qualquer página ser lida.
#
# A medida é um TETO do que o pdfminer vai descompactar: os filtros em cadeia
# ([/ASCII85Decode /FlateDecode] etc.) são seguidos, o que o leitor não consegue
# interpretar com segurança é recusado em vez de ignorado, e o PDF protegido por
# senha vazia é medido depois de decifrado (com o mesmo decifrador do pdfminer).

#: Soma máxima do que os fluxos do PDF viram depois de descompactados (conteúdo
#: das páginas, fontes, tabelas de objetos). Relatório real fica em poucos MB.
PDF_MAX_DESCOMPRIMIDO = 50 * 1024 * 1024
#: Imagens têm conta própria: o pdfminer NÃO as descompacta para ler o texto, e
#: capturas de tela em PNG (FlateDecode) chegam a dezenas de MB num PDF real de
#: 5 MB. Cada imagem só entra aqui se não inflar além do tamanho que ela mesma
#: declara (largura × altura); acima disso, conta como conteúdo comum.
PDF_MAX_IMAGENS = 200 * 1024 * 1024
#: Páginas. Os relatórios reais têm poucas dezenas.
PDF_MAX_PAGINAS = 300
_BLOCO_INFLAR = 16 * 1024
#: Um dicionário de fluxo real tem algumas centenas de bytes.
_MAX_DICIONARIO = 64 * 1024
#: Fluxos e objetos: um relatório real tem centenas; um PDF grande, milhares.
_MAX_FLUXOS = 50_000
_MAX_OBJETOS = 200_000
_MB = 1024 * 1024


class PdfRecusado(ValueError):
    """O PDF foi recusado ANTES de o pdfplumber abri-lo. ``status_http`` é o código
    que a rota devolve: 413 para tamanho (descompactado ou páginas), 422 para a
    estrutura que o leitor não mede com segurança. Subclasse de ``ValueError``:
    quem já trata ``ValueError`` como "arquivo ilegível" continua tratando."""

    def __init__(self, mensagem: str, status_http: int = 413):
        super().__init__(mensagem)
        self.status_http = status_http


def _msg_teto(teto: int) -> str:
    return (f"O PDF passa de {teto // _MB} MB depois de descompactado e foi recusado. "
            "Os relatórios do Matific e do Elefante ficam muito abaixo disso: confira se "
            "é o arquivo certo e envie de novo.")


def _msg_imagens(teto: int) -> str:
    return (f"As imagens do PDF passam de {teto // _MB} MB depois de descompactadas e o "
            "arquivo foi recusado. Confira se é o relatório exportado da plataforma e "
            "envie de novo.")


def _msg_paginas(teto: int) -> str:
    return (f"O PDF tem mais de {teto} páginas e foi recusado. Os relatórios do Matific "
            "e do Elefante têm poucas dezenas: confira se é o arquivo certo e envie de novo.")


_MSG_ESTRUTURA = ("O PDF tem uma estrutura interna que os relatórios das plataformas não "
                  "usam e foi recusado. Baixe o relatório de novo na plataforma e envie "
                  "outra vez.")
_MSG_SENHA = ("O PDF está protegido por senha e não pode ser lido. Baixe o relatório de "
              "novo na plataforma, sem proteção, e envie outra vez.")

# Filtros, com os mesmos nomes (e abreviações) que o pdfminer aceita.
_FLATE = frozenset({"FlateDecode", "Fl"})
_LZW = frozenset({"LZWDecode", "LZW"})
_A85 = frozenset({"ASCII85Decode", "A85"})
_AHX = frozenset({"ASCIIHexDecode", "AHx"})
_RL = frozenset({"RunLengthDecode", "RL"})
_CCITT = frozenset({"CCITTFaxDecode", "CCF"})
#: O pdfminer devolve o dado como veio (imagem): não infla, e a cadeia segue.
_IDENTIDADE = frozenset({"DCTDecode", "DCT", "JBIG2Decode", "JPXDecode"})
#: Num dicionário que o leitor não entende, estes nomes recusam o arquivo: a
#: cadeia não poderia ser medida (com o Flate sozinho, a medida segue possível).
_INFLAM_SEM_FLATE = _LZW | _A85 | _AHX | _RL | _CCITT

# Espaço: o ``\s`` do pdfminer (que inclui o \x0b, tabulação vertical) mais o \x00 do
# padrão PDF. O medidor separa as palavras em TODO lugar em que o pdfminer separa
# (com o \x00, em alguns a mais — o que só faz medir de mais). Antes faltava o \x0b:
# "/Filter\x0b/FlateDecode" ou ">>\x0bstream" passavam sem medida e o pdfminer
# descompactava tudo.
_ESPACOS = b" \t\r\n\x0b\x0c\x00"
_ESP = rb" \t\r\n\x0b\x0c\x00"   # o mesmo conjunto, para as classes das expressões
# Fim de palavra-chave, como o pdfminer: espaço ou um destes — inclusive o "#"
# ("stream#x" é a palavra "stream" para o pdfminer).
_RE_INICIO_FLUXO = re.compile(rb"(?<![A-Za-z])stream(?=[" + _ESP + rb"()<>\[\]{}/%#]|\Z)")
_RE_CABECALHO = re.compile(
    rb"(?<![0-9])(\d{1,10})[" + _ESP + rb"]+(\d{1,5})[" + _ESP + rb"]+obj(?![A-Za-z0-9])")
_RE_INTEIRO = re.compile(rb"[+-]?\d+")
# Escape "#" num nome, como o pdfminer: até 2 dígitos hexadecimais viram um byte, e um
# "#" sem dígito depois some ("/F#lateDecode" é /FlateDecode para o pdfminer).
_RE_HEX_NOME = re.compile(rb"#([0-9A-Fa-f]{0,2})")
_RE_NOME = re.compile(rb"/([^" + _ESP + rb"/%\[\]()<>{}]+)")
_RE_CIFRADO = re.compile(rb"/Encrypt(?![A-Za-z0-9])")
_RE_NOME_COM_ESCAPE = re.compile(
    rb"/([^" + _ESP + rb"/%\[\]()<>{}]*#[^" + _ESP + rb"/%\[\]()<>{}]*)")
# Um token PDF por vez (sem laço byte a byte): espaço/comentário (pulados),
# << >> [ ], texto hexadecimal, /nome, início de texto literal, palavra (que termina
# no "#", como no pdfminer; o "#" solto é uma palavra de um caractere).
_RE_TOKEN = re.compile(
    rb"[" + _ESP + rb"]+|%[^\r\n]*"
    rb"|(<<|>>|\[|\])"
    rb"|(<[^<>]*>)"
    rb"|/([^" + _ESP + rb"/%\[\]()<>{}]*)"
    rb"|(\()"
    rb"|([^" + _ESP + rb"/%\[\]()<>{}#]+|#)")
_RE_PARENTESE = re.compile(rb"[()\\]")
# Só espaços e comentários. Possessiva (``++``, ``*+``): a forma anterior,
# ``(?:[espaço]+|%[^\r\n]*)*``, aninhava quantificadores, e quando o trecho NÃO era
# só espaço o ``re`` tentava todos os jeitos de repartir a sequência — 2^N para N
# espaços: ~40 espaços e um "x" entre ">>" e "stream" congelavam o medidor. Mesmo
# resultado: cada espaço ou comentário é engolido inteiro (um comentário vai até a
# quebra de linha, que é espaço), e nunca é preciso devolver um pedaço dele.
_RE_SO_ESPACOS = re.compile(rb"(?:[" + _ESP + rb"]++|%[^\r\n]*+)*+")
#: Bytes interpretados como objeto (dicionários, números) no arquivo inteiro.
_MAX_TOKENIZADO = 8 * 1024 * 1024
#: "stream" depois de ">>" sem dicionário legível: num PDF real, nenhum.
_MAX_DICIONARIOS_ILEGIVEIS = 1_000
_MAX_PROFUNDIDADE = 100


class _Nome(NamedTuple):
    valor: str


class _Ref(NamedTuple):
    num: int
    ger: int


class _Ilegivel(Exception):
    """O trecho não é um objeto PDF que este leitor entenda."""


_TEXTO = object()  # cadeia de caracteres: o conteúdo não interessa à medida


def _nome(bruto: bytes) -> str:
    return _RE_HEX_NOME.sub(lambda m: bytes((int(m.group(1), 16),)) if m.group(1) else b"",
                            bruto).decode("latin-1")


def _cifrado(conteudo: bytes) -> bool:
    """O arquivo declara cifra (/Encrypt)? Também com o nome escrito com escapes
    ("/Encr#79pt"), que o pdfminer lê como /Encrypt."""
    if _RE_CIFRADO.search(conteudo):
        return True
    return any(_nome(m.group(1)) == "Encrypt" for m in _RE_NOME_COM_ESCAPE.finditer(conteudo))


def _fim_texto(dado: bytes, pos: int, fim: int) -> int:
    """Posição logo depois do ")" que fecha o texto literal aberto antes de ``pos``."""
    nivel = 1
    while nivel:
        m = _RE_PARENTESE.search(dado, pos, fim)
        if m is None:
            raise _Ilegivel
        pos = m.end()
        c = m.group()
        if c == b"\\":
            pos += 1
        elif c == b"(":
            nivel += 1
        else:
            nivel -= 1
    return pos


def _gerar_tokens(dado: bytes, pos: int, fim: int):
    """(tipo, valor, posição depois do token) de ``dado[pos:fim]``, sob demanda."""
    while pos < fim:
        m = _RE_TOKEN.match(dado, pos, fim)
        if m is None:
            raise _Ilegivel   # ")", "{", "}" ou ">" solto: não é um dicionário de fluxo
        grupo = m.lastindex
        pos = m.end()
        if grupo is None:
            continue
        if grupo == 1:
            yield m.group(1).decode(), None, pos
        elif grupo == 2:
            yield "texto", None, pos
        elif grupo == 3:
            yield "nome", _nome(m.group(3)), pos
        elif grupo == 4:
            pos = _fim_texto(dado, pos, fim)
            yield "texto", None, pos
        else:
            yield "palavra", m.group(5), pos


class _Leitor:
    """Lê UM objeto PDF a partir de uma posição, consumindo só os tokens dele."""

    def __init__(self, dado: bytes, pos: int, fim: int):
        self._tokens = _gerar_tokens(dado, pos, fim)
        self._fila: list = []
        self.pos = pos            # depois do último token CONSUMIDO
        self.lido = pos           # depois do último token gerado (inclui a espiada)

    def _espiar(self, k: int = 0):
        while len(self._fila) <= k:
            try:
                token = next(self._tokens)
            except StopIteration:
                return None
            self._fila.append(token)
            self.lido = token[2]
        return self._fila[k]

    def _tomar(self):
        if self._espiar() is None:
            raise _Ilegivel
        token = self._fila.pop(0)
        self.pos = token[2]
        return token

    def objeto(self, profundidade: int = 0):
        """Dicionário → dict (nome → valor), matriz → list, nome → ``_Nome``,
        inteiro → int, "N G R" → ``_Ref``; o resto é opaco."""
        if profundidade > _MAX_PROFUNDIDADE:
            raise _Ilegivel
        tipo, valor, _fim = self._tomar()
        if tipo == "<<":
            dic: dict = {}
            while True:
                token = self._espiar()
                if token is None:
                    raise _Ilegivel
                if token[0] == ">>":
                    self._tomar()
                    return dic
                if token[0] != "nome":
                    raise _Ilegivel
                self._tomar()
                item = self.objeto(profundidade + 1)
                if item == ("palavra", b"null"):
                    dic.pop(token[1], None)   # como no pdfminer: null some do dicionário
                else:
                    dic[token[1]] = item      # chave repetida: a última vale (pdfminer)
        if tipo == "[":
            lista: list = []
            while True:
                token = self._espiar()
                if token is None:
                    raise _Ilegivel
                if token[0] == "]":
                    self._tomar()
                    return lista
                lista.append(self.objeto(profundidade + 1))
        if tipo == "nome":
            return _Nome(valor)
        if tipo == "texto":
            return _TEXTO
        if tipo == "palavra" and _RE_INTEIRO.fullmatch(valor):
            ger, r = self._espiar(0), self._espiar(1)
            if (ger is not None and r is not None and ger[0] == "palavra"
                    and _RE_INTEIRO.fullmatch(ger[1]) and r[:2] == ("palavra", b"R")):
                self._tomar()
                self._tomar()
                return _Ref(int(valor), int(ger[1]))
            return int(valor)
        if tipo == "palavra":
            return ("palavra", valor)
        raise _Ilegivel


class _Estouro(Exception):
    """Um orçamento passou do teto (``orcamento.tipo`` diz qual)."""

    def __init__(self, orcamento: "_Orcamento"):
        super().__init__(orcamento.tipo)
        self.orcamento = orcamento


class _Orcamento:
    """O que ainda pode sair (bytes descompactados) e, na raiz, o que ainda pode
    ser lido (bytes de entrada processados — evita que fluxos sobrepostos
    multipliquem o trabalho). ``tipo``: "geral", "imagens" ou "geometria" (o
    tamanho que uma imagem declara); o filho herda o tipo do pai."""

    def __init__(self, teto: int, teto_entrada: int = 0, pai: "_Orcamento | None" = None,
                 tipo: str | None = None):
        self.teto = teto
        self.restante = teto
        self.tipo = tipo or (pai.tipo if pai is not None else "geral")
        self.raiz = pai.raiz if pai is not None else self
        self.entrada_restante = teto_entrada
        # Só na raiz: a conta das imagens e os contêineres de objetos (que nunca
        # ganham a conta das imagens — ver ``_conteineres_de_objetos``).
        self.imagens: _Orcamento | None = None
        self.conteineres: set[int] | None = None

    def gastar(self, n: int) -> None:
        self.restante -= n
        if self.restante < 0:
            raise _Estouro(self)

    def ler(self, n: int) -> None:
        self.raiz.entrada_restante -= n
        if self.raiz.entrada_restante < 0:
            raise PdfRecusado(_MSG_ESTRUTURA, 422)

    def filho(self, teto: int | None = None, tipo: str | None = None) -> "_Orcamento":
        return _Orcamento(self.restante if teto is None else teto, pai=self, tipo=tipo)


class _Cabecalhos:
    """Índice dos "N G obj" do arquivo — para achar o objeto de cada fluxo e
    resolver referências indiretas (/Length 12 0 R) sem o pdfminer. Cada objeto é
    lido UMA vez (memória) e o total lido tem teto."""

    def __init__(self, conteudo: bytes):
        self.conteudo = conteudo
        self.fins: list[int] = []
        self.ids: list[tuple[int, int]] = []
        self.por_id: dict[tuple[int, int], list[int]] = {}
        self._objetos: dict[int, tuple[int, object] | None] = {}
        self._tokenizado = 0
        for m in _RE_CABECALHO.finditer(conteudo):
            if len(self.fins) >= _MAX_OBJETOS:
                raise _Ilegivel
            chave = (int(m.group(1)), int(m.group(2)))
            self.fins.append(m.end())
            self.ids.append(chave)
            self.por_id.setdefault(chave, []).append(m.end())

    def antes_de(self, pos: int, quantos: int = 3):
        """Os ``quantos`` cabeçalhos mais próximos que terminam antes de ``pos``."""
        k = bisect.bisect_right(self.fins, pos)
        for j in range(k - 1, max(-1, k - 1 - quantos), -1):
            if pos - self.fins[j] > _MAX_DICIONARIO:
                return
            yield self.fins[j], self.ids[j]

    def objeto_em(self, inicio: int):
        """(posição depois do objeto, valor) do objeto que começa em ``inicio``, ou
        None se ilegível. Lido uma vez; o total lido no arquivo tem teto."""
        if inicio in self._objetos:
            return self._objetos[inicio]
        leitor = _Leitor(self.conteudo, inicio, min(len(self.conteudo), inicio + _MAX_DICIONARIO))
        try:
            valor = leitor.objeto()
            achado = (leitor.pos, valor)
        except _Ilegivel:
            achado = None
        self._tokenizado += max(leitor.lido, leitor.pos) - inicio + 1
        if self._tokenizado > _MAX_TOKENIZADO:
            raise _Ilegivel
        self._objetos[inicio] = achado
        return achado

    def resolver(self, valor):
        """Os valores que uma referência pode ter (cada definição do objeto no
        arquivo; atualização incremental pode repetir). Não-referência: ela mesma.
        Referência que não está no corpo do arquivo (num fluxo de objetos): []."""
        if not isinstance(valor, _Ref):
            return [valor]
        valores = []
        for inicio in self.por_id.get((valor.num, valor.ger), []):
            achado = self.objeto_em(inicio)
            if achado is not None:
                valores.append(achado[1])
        return valores

    def resolver_unico(self, valor):
        """O valor de uma referência — ou ``_Ilegivel`` se não está no corpo do
        arquivo ou se as definições discordam (o leitor não sabe qual vale)."""
        valores = self.resolver(valor)
        if not valores or any(v != valores[0] for v in valores[1:]):
            raise _Ilegivel
        return valores[0]


@dataclass
class _Fluxo:
    inicio: int                         # 1º byte do dado (depois do fim de linha)
    dic: dict | None                    # None = dicionário que o leitor não entende
    ident: tuple[int, int] | None       # (número, geração) do objeto
    regiao: bytes                       # o trecho antes de "stream" (para os nomes)


def _dicionario_antes(conteudo: bytes, p: int) -> bool:
    """O que antecede "stream" (fora espaços e comentários) termina em ">>"? Se
    não termina, o pdfminer não tem dicionário para o fluxo — sem filtro, nada
    infla — e a palavra é só texto."""
    fim = p
    for _ in range(8):
        janela = max(0, fim - 4096)
        trecho = conteudo[janela:fim].rstrip(_ESPACOS)
        if trecho.endswith(b">>"):
            return True
        inicio_linha = max(trecho.rfind(b"\n"), trecho.rfind(b"\r")) + 1
        pct = trecho.find(b"%", inicio_linha)
        if pct < 0:
            return False
        fim = janela + pct
    return False


def _fluxos(conteudo: bytes, cab: _Cabecalhos) -> list[_Fluxo]:
    """Cada palavra-chave "stream" do arquivo com dicionário antes, e o dicionário."""
    fluxos: list[_Fluxo] = []
    proxima = {b"\n": -1, b"\r": -1}   # próxima quebra de linha já achada (busca amortizada)
    total = len(conteudo)
    vistos = ilegiveis = 0
    for m in _RE_INICIO_FLUXO.finditer(conteudo):
        vistos += 1
        if vistos > _MAX_FLUXOS:
            raise _Ilegivel
        p = m.start()
        if not _dicionario_antes(conteudo, p):
            continue
        # O dado começa depois do fim de linha que segue "stream" (o pdfminer lê a
        # linha inteira da palavra-chave e começa na próxima).
        quebra = total
        for marca in proxima:
            if proxima[marca] != total and proxima[marca] < m.end():
                achado = conteudo.find(marca, m.end())
                proxima[marca] = total if achado < 0 else achado
            quebra = min(quebra, proxima[marca])
        inicio = quebra + 1
        if conteudo[quebra:quebra + 2] == b"\r\n":
            inicio = quebra + 2
        dic = ident = None
        regiao = conteudo[max(0, p - 4096):p]
        for fim_cab, chave in cab.antes_de(p):
            achado = cab.objeto_em(fim_cab)
            if (achado is not None and isinstance(achado[1], dict) and p - achado[0] <= 4096
                    and _RE_SO_ESPACOS.fullmatch(conteudo, achado[0], p)):
                dic, ident = achado[1], chave
                break
            regiao = conteudo[fim_cab:p]
        if dic is None:
            ilegiveis += 1
            if ilegiveis > _MAX_DICIONARIOS_ILEGIVEIS:
                raise _Ilegivel
        fluxos.append(_Fluxo(inicio=min(inicio, total), dic=dic, ident=ident,
                             regiao=b"" if dic is not None else regiao))
    return fluxos


def _inflar_bloco(d, entrada, orc: _Orcamento, partes: list | None) -> None:
    while entrada and not d.eof:
        # No máximo 1 MB por chamada: o zlib monta a saída em blocos e junta no fim
        # (pico de ~2x a saída de UMA chamada), e o que não é guardado sai logo.
        saida = d.decompress(entrada, min(orc.restante + 1, _MB))
        orc.gastar(len(saida))
        if partes is not None and saida:
            partes.append(saida)
        entrada = d.unconsumed_tail


def _refazer(reserva, bloco, orc: _Orcamento, partes: list | None, passo: int):
    """Refaz ``bloco`` a partir do estado ``reserva`` em pedaços de ``passo`` bytes
    até achar o erro; devolve o estado onde parou. Primeiro em pedaços de 64 bytes,
    depois byte a byte só no pedaço do erro."""
    d = reserva
    for i in range(0, len(bloco), passo):
        pedaco = bloco[i:i + passo]
        copia = d.copy() if passo > 1 else None
        restante_antes = orc.restante
        n_partes = len(partes) if partes is not None else 0
        try:
            _inflar_bloco(d, pedaco, orc, partes)
        except zlib.error:
            if copia is not None:
                orc.restante = restante_antes
                if partes is not None:
                    del partes[n_partes:]
                return _refazer(copia, pedaco, orc, partes, 1)
            return d
        if d.eof:
            return d
    return d


def _inflar(dado, orc: _Orcamento, guardar: bool) -> bytes | None:
    """FlateDecode com teto: descompacta aos poucos e conta o que sai. Dado
    corrompido no meio: o que saiu até ali conta (o pdfminer chega a alocar isso
    e ainda tenta de novo byte a byte), por isso o bloco do erro é refeito em
    pedaços a partir de uma cópia do estado."""
    d = zlib.decompressobj()
    partes: list | None = [] if guardar else None
    vista = memoryview(dado)
    pos, total = 0, len(vista)
    while pos < total and not d.eof:
        bloco = vista[pos:pos + _BLOCO_INFLAR]
        reserva = d.copy()
        restante_antes = orc.restante
        n_partes = len(partes) if partes is not None else 0
        try:
            _inflar_bloco(d, bloco, orc, partes)
        except zlib.error:
            # Desfaz o que este bloco já contou e refaz a partir da cópia do estado.
            orc.restante = restante_antes
            if partes is not None:
                del partes[n_partes:]
            d = _refazer(reserva, bloco, orc, partes, 64)
            pos += len(bloco)
            break
        pos += len(bloco)
    orc.ler(pos - (len(d.unused_data) if d.eof else 0))
    return b"".join(partes) if partes is not None else None


def _lzw(dado, orc: _Orcamento, guardar: bool) -> bytes | None:
    from pdfminer.lzw import LZWDecoder

    orc.ler(len(dado))
    partes: list = []
    try:
        for parte in LZWDecoder(io.BytesIO(bytes(dado))).run():
            orc.gastar(len(parte))
            if guardar:
                partes.append(parte)
    except (PdfRecusado, _Estouro):
        raise
    except Exception:  # noqa: BLE001 — dado corrompido: o pdfminer também para aí
        pass
    return b"".join(partes) if guardar else None


def _rl(dado, orc: _Orcamento, guardar: bool) -> bytes | None:
    partes: list = []
    i, total = 0, len(dado)
    while i < total:
        c = dado[i]
        if c == 128:
            i += 1
            break
        if c < 128:
            trecho = bytes(dado[i + 1:i + 2 + c])
            i += 2 + c
            n = len(trecho)
        else:
            if i + 1 >= total:
                i = total
                break
            n = 257 - c
            trecho = bytes(dado[i + 1:i + 2]) * n if guardar else b""
            i += 2
        orc.gastar(n)
        if guardar:
            partes.append(trecho)
    orc.ler(i)
    return b"".join(partes) if guardar else None


def _a85(dado, orc: _Orcamento) -> bytes | None:
    from pdfminer.ascii85 import ascii85decode

    dado = bytes(dado)
    # 5 caracteres viram 4 bytes; "z" vira 4 bytes sozinho — o teto antes de decodificar.
    if (len(dado) * 4) // 5 + 4 * dado.count(b"z") + 4 > orc.restante:
        raise _Estouro(orc)
    orc.ler(len(dado))
    try:
        saida = ascii85decode(dado)
    except Exception:  # noqa: BLE001 — inválido: o pdfminer recusa o fluxo inteiro
        return None
    orc.gastar(len(saida))
    return saida


def _ahx(dado, orc: _Orcamento) -> bytes | None:
    from pdfminer.ascii85 import asciihexdecode

    dado = bytes(dado)
    orc.ler(len(dado))
    try:
        saida = asciihexdecode(dado)   # sai no máximo metade do que entra
    except Exception:  # noqa: BLE001 — inválido: o pdfminer recusa o fluxo inteiro
        return None
    orc.gastar(len(saida))
    return saida


def _ccitt(dado, parametro, cab: _Cabecalhos, orc: _Orcamento) -> None:
    """Fax (CCITT): o pdfminer decodifica linha a linha até o dado acabar, e uma
    linha em branco custa 1 bit. Teto = largura × (linhas declaradas, ou 8 por
    byte de entrada). Sem largura legível, recusa."""
    parametro = cab.resolver_unico(parametro) if parametro is not None else {}
    if not isinstance(parametro, dict):
        parametro = {}
    colunas = cab.resolver_unico(parametro.get("Columns", 1728))
    linhas = cab.resolver_unico(parametro.get("Rows", 0))
    if not isinstance(colunas, int) or not isinstance(linhas, int) or colunas < 0:
        raise _Ilegivel
    teto_linhas = 8 * len(dado) + 1
    if linhas <= 0 or linhas > teto_linhas:
        linhas = teto_linhas
    orc.gastar(((colunas + 7) // 8) * linhas)


def _filtros(dic: dict, cab: _Cabecalhos) -> tuple[list[str | None], list]:
    """(nomes dos filtros na ordem, parâmetros de cada um) — como o pdfminer lê:
    /F antes de /Filter; /DP, /DecodeParms ou /FDecodeParms. Nome ilegível vira
    None (o pdfminer recusa o fluxo ali: nada infla depois)."""
    bruto = dic["F"] if "F" in dic else dic.get("Filter")
    bruto = cab.resolver_unico(bruto) if bruto is not None else None
    if not bruto:
        return [], []
    lista = bruto if isinstance(bruto, list) else [bruto]
    nomes: list[str | None] = []
    for item in lista:
        item = cab.resolver_unico(item)
        nomes.append(item.valor if isinstance(item, _Nome) else None)
    params = None
    for chave in ("DP", "DecodeParms", "FDecodeParms"):
        if chave in dic:
            params = cab.resolver_unico(dic[chave])
            break
    if isinstance(params, list):
        params = (params + [None] * len(nomes))[:len(nomes)]
    else:
        params = [params] * len(nomes)
    return nomes, params


def _cadeia(entrada, nomes: list, params: list, cab: _Cabecalhos, orc: _Orcamento) -> None:
    dado = entrada
    for k, (nome, parametro) in enumerate(zip(nomes, params)):
        guardar = k < len(nomes) - 1     # a saída só é guardada se outro filtro vem depois
        if nome in _FLATE:
            dado = _inflar(dado, orc, guardar)
        elif nome in _LZW:
            dado = _lzw(dado, orc, guardar)
        elif nome in _RL:
            dado = _rl(dado, orc, guardar)
        elif nome in _A85:
            dado = _a85(dado, orc)
        elif nome in _AHX:
            dado = _ahx(dado, orc)
        elif nome in _CCITT:
            _ccitt(dado, parametro, cab, orc)
            if guardar:            # fax no meio da cadeia: nenhum relatório faz isso
                raise _Ilegivel
            return
        elif nome in _IDENTIDADE:
            continue
        else:
            return                 # /Crypt ou desconhecido: o pdfminer recusa o fluxo
        if dado is None:
            return


def _medir_candidatos(candidatos: list, nomes: list, params: list,
                      cab: _Cabecalhos, orc: _Orcamento) -> None:
    """Mede cada leitura possível do dado bruto e cobra a MAIOR (o teto)."""
    maior = 0
    for entrada in candidatos:
        filho = orc.filho()
        _cadeia(entrada, nomes, params, cab, filho)
        maior = max(maior, filho.teto - filho.restante)
    orc.gastar(maior)


def _bytes_da_imagem(dic: dict, cab: _Cabecalhos) -> int | None:
    """Teto do que uma imagem pode virar descompactada, pelo que ela DECLARA:
    largura × altura × 4 componentes × bits por componente (+1 byte por linha do
    preditor PNG, +64 KB de folga). None se o fluxo não é uma imagem bem declarada
    (/Subtype /Image, /Width e /Height inteiros, sem outro /Type) — aí conta como
    conteúdo comum."""
    if dic.get("Subtype") != _Nome("Image") or dic.get("Type", _Nome("XObject")) != _Nome("XObject"):
        return None
    try:
        largura = cab.resolver_unico(dic.get("Width"))
        altura = cab.resolver_unico(dic.get("Height"))
        bits = cab.resolver_unico(dic.get("BitsPerComponent", 8))
    except _Ilegivel:
        return None
    if not all(isinstance(v, int) and v > 0 for v in (largura, altura, bits)):
        return None
    return (largura * 4 * min(bits, 16) + 7) // 8 * altura + altura + 64 * 1024


def _brutos(conteudo: bytes, fluxo: _Fluxo, cab: _Cabecalhos, *, exigir_tamanho: bool):
    """As leituras possíveis do dado bruto, como o pdfminer faz: os /Length bytes
    a partir do início (leitura normal) e até o próximo "endstream" (leitura de
    recuperação, quando a tabela de objetos está quebrada)."""
    ate_marca = conteudo.find(b"endstream", fluxo.inicio)
    if ate_marca < 0:
        ate_marca = len(conteudo)
    fins = {ate_marca}
    tamanho = fluxo.dic.get("Length", 0)
    valores = [v for v in cab.resolver(tamanho) if isinstance(v, int) and v >= 0]
    if valores:
        fins.add(min(len(conteudo), fluxo.inicio + max(valores)))
    elif exigir_tamanho:
        raise _Ilegivel   # tamanho num fluxo de objetos: o leitor não o enxerga
    return [conteudo[fluxo.inicio:fim] for fim in sorted(fins)]


def _medir_fluxo(conteudo: bytes, fluxo: _Fluxo, cab: _Cabecalhos, orc: _Orcamento,
                 decifrar=None) -> None:
    if fluxo.dic is None:
        nomes_na_regiao = {_nome(m.group(1)) for m in _RE_NOME.finditer(fluxo.regiao)}
        if decifrar is not None or nomes_na_regiao & _INFLAM_SEM_FLATE:
            raise _Ilegivel
        # Dicionário estranho: se o dado for zlib, mede como Flate (o pdfminer pode
        # aceitar o que este leitor não entende).
        _inflar(memoryview(conteudo)[fluxo.inicio:], orc, guardar=False)
        return
    nomes, params = _filtros(fluxo.dic, cab)
    if not nomes:
        return
    if decifrar is None:
        if nomes[0] in _FLATE:
            # O zlib termina sozinho: do início até o fim do arquivo é um teto das
            # duas leituras (a dos /Length bytes e a até "endstream").
            candidatos = [memoryview(conteudo)[fluxo.inicio:]]
        else:
            exige = nomes[0] in (_LZW | _RL | _A85 | _CCITT)
            candidatos = _brutos(conteudo, fluxo, cab, exigir_tamanho=exige)
    else:
        candidatos = []
        for bruto in _brutos(conteudo, fluxo, cab, exigir_tamanho=True):
            for tentativa in (bruto, bruto[:16 + max(0, len(bruto) - 16) // 16 * 16]):
                try:
                    candidatos.append(decifrar(bruto=tentativa))
                    break
                except Exception:  # noqa: BLE001 — o pdfminer também não decifra
                    continue
    geometria = _bytes_da_imagem(fluxo.dic, cab)
    if (geometria is not None and orc.imagens is not None and orc.conteineres is not None
            and fluxo.ident is not None and fluxo.ident[0] not in orc.conteineres):
        # Imagem: o pdfminer não a descompacta para ler o texto. Conta à parte, mas
        # só se couber no tamanho que ela declara; inflando mais, não é a imagem que
        # diz ser — conta no orçamento geral, como qualquer conteúdo.
        medida = orc.filho(teto=min(geometria, orc.imagens.restante + 1), tipo="geometria")
        try:
            _medir_candidatos(candidatos, nomes, params, cab, medida)
        except _Estouro as exc:
            if exc.orcamento.tipo != "geometria":
                raise
            if geometria > orc.imagens.restante:
                raise _Estouro(orc.imagens) from exc   # coube na geometria, não na conta
        else:
            orc.imagens.gastar(medida.teto - medida.restante)
            return
    _medir_candidatos(candidatos, nomes, params, cab, orc)


#: Tabela de objetos (xref) descompactada que o leitor aceita interpretar: uma real
#: tem 5 a 10 bytes por objeto.
_MAX_TABELA_XREF = 8 * 1024 * 1024


def _conteineres_de_objetos(conteudo: bytes, fluxos: list[_Fluxo],
                            cab: _Cabecalhos) -> set[int] | None:
    """Números dos objetos usados como FLUXO DE OBJETOS (entradas tipo 2 das
    tabelas xref em fluxo). O pdfminer descompacta esses contêineres ao abrir o
    documento, olhe o /Subtype que olhar — então nenhum deles ganha a conta das
    imagens. None se alguma tabela não pôde ser lida (aí nenhuma imagem ganha)."""
    from pdfminer.utils import apply_png_predictor

    conteineres: set[int] = set()
    for fluxo in fluxos:
        if fluxo.dic is None or fluxo.dic.get("Type") != _Nome("XRef"):
            continue
        try:
            nomes, params = _filtros(fluxo.dic, cab)
            if nomes and nomes[-1] not in _FLATE or len(nomes) > 1:
                return None
            if nomes:
                dado = _inflar(memoryview(conteudo)[fluxo.inicio:],
                               _Orcamento(_MAX_TABELA_XREF, 4 * len(conteudo) + _MB), True)
            else:
                dado = _brutos(conteudo, fluxo, cab, exigir_tamanho=True)[0]
            parametro = cab.resolver_unico(params[0]) if params and params[0] is not None else {}
            parametro = parametro if isinstance(parametro, dict) else {}
            preditor = cab.resolver_unico(parametro.get("Predictor", 1))
            if preditor >= 10:
                dado = apply_png_predictor(
                    preditor, cab.resolver_unico(parametro.get("Colors", 1)),
                    cab.resolver_unico(parametro.get("Columns", 1)),
                    cab.resolver_unico(parametro.get("BitsPerComponent", 8)), dado)
            elif preditor != 1:
                return None
            larguras = [cab.resolver_unico(w) for w in cab.resolver_unico(fluxo.dic.get("W"))]
            if len(larguras) != 3 or not all(isinstance(w, int) and 0 <= w <= 8 for w in larguras):
                return None
            passo = sum(larguras)
            if passo == 0:
                continue
            for k in range(0, len(dado) - passo + 1, passo):
                linha = dado[k:k + passo]
                tipo = int.from_bytes(linha[:larguras[0]], "big") if larguras[0] else 1
                if tipo == 2:
                    conteineres.add(int.from_bytes(
                        linha[larguras[0]:larguras[0] + larguras[1]], "big"))
        except (_Ilegivel, _Estouro, PdfRecusado, TypeError, ValueError):
            return None
    return conteineres


def _abrir_documento(conteudo: bytes):
    from pdfminer.pdfdocument import PDFDocument
    from pdfminer.pdfparser import PDFParser

    if _ORCAMENTO.get() is not None:      # dentro de ``analisar_pdf``: o orçamento dela
        return PDFDocument(PDFParser(io.BytesIO(conteudo)))
    with _orcamento_da_analise():         # chamado sozinho: um orçamento só para abrir
        return PDFDocument(PDFParser(io.BytesIO(conteudo)))


def exigir_pdf_contido(conteudo: bytes, max_descomprimido: int | None = None) -> None:
    """Recusa (``PdfRecusado``) o PDF que infla além do teto, ANTES do pdfplumber
    abri-lo. Nada aqui descompacta sem teto.

    Ordem: (1) cada fluxo, como está no arquivo, é descompactado aos poucos e
    contado contra o teto; (2) PDF protegido por senha vazia: os fluxos são
    decifrados com o decifrador do próprio pdfminer e medidos de novo. As páginas
    são conferidas depois, por ``exigir_paginas``, no documento já aberto pelo
    pdfplumber e antes de qualquer página ser lida."""
    if max_descomprimido is None:
        max_descomprimido = PDF_MAX_DESCOMPRIMIDO
    max_imagens = PDF_MAX_IMAGENS
    orc = _Orcamento(max_descomprimido,
                     2 * len(conteudo) + max_descomprimido + max_imagens + _MB)
    orc.imagens = _Orcamento(max_imagens, tipo="imagens")
    try:
        cab = _Cabecalhos(conteudo)
        fluxos = _fluxos(conteudo, cab)
        orc.conteineres = _conteineres_de_objetos(conteudo, fluxos, cab)
        for fluxo in fluxos:
            _medir_fluxo(conteudo, fluxo, cab, orc)
        if _cifrado(conteudo):
            # Só aqui o documento é aberto (para o decifrador): a tabela de objetos
            # e os fluxos não cifrados já foram medidos acima.
            try:
                doc = _abrir_documento(conteudo)
            except Exception as exc:  # noqa: BLE001 — senha exigida, cifra desconhecida
                raise PdfRecusado(_MSG_SENHA, 422) from exc
            decifrador = getattr(doc, "decipher", None)
            if decifrador is not None:
                for fluxo in fluxos:
                    if fluxo.dic is not None and fluxo.dic.get("Type") == _Nome("XRef"):
                        continue   # a tabela de objetos nunca é cifrada (já medida)
                    if fluxo.ident is None:
                        raise _Ilegivel
                    num, ger = fluxo.ident

                    def decifrar(bruto, num=num, ger=ger):
                        return decifrador(num, ger, bruto)
                    _medir_fluxo(conteudo, fluxo, cab, orc, decifrar=decifrar)
    except _Ilegivel as exc:
        raise PdfRecusado(_MSG_ESTRUTURA, 422) from exc
    except _Estouro as exc:
        if exc.orcamento.tipo == "imagens":
            raise PdfRecusado(_msg_imagens(max_imagens)) from exc
        raise PdfRecusado(_msg_teto(max_descomprimido)) from exc


def exigir_paginas(doc, max_paginas: int | None = None) -> None:
    """Recusa o PDF com mais de ``max_paginas`` páginas, contando pela árvore de
    páginas do pdfminer (a MESMA que o pdfplumber percorre) e parando na primeira
    página além do teto — nenhuma página tem o conteúdo lido aqui. ``doc`` é o
    documento pdfminer já aberto (``pdfplumber.PDF.doc``): abrir de novo dobraria
    o custo da leitura num arquivo hostil."""
    from pdfminer.pdfpage import PDFPage

    if max_paginas is None:
        max_paginas = PDF_MAX_PAGINAS
    paginas = []
    for n, pagina in enumerate(PDFPage.create_pages(doc), start=1):
        if n > max_paginas:
            raise PdfRecusado(_msg_paginas(max_paginas))
        paginas.append(pagina)
    _exigir_imagens_so_como_imagem(paginas)


def _exigir_imagens_so_como_imagem(paginas) -> None:
    """As imagens têm conta própria na medida porque o pdfminer não as descompacta
    para ler o texto — MAS ele descompacta, sem olhar o /Subtype, o conteúdo das
    páginas, os arquivos de fonte, os mapas de caracteres e os desenhos das fontes
    Type3. Uma "imagem" nesses lugares é um disfarce: recusa antes de qualquer
    página ser lida. (Formulários entram na busca; imagens chamadas como imagem,
    não: o pdfminer as deixa compactadas.)"""
    from pdfminer.pdftypes import PDFStream, resolve1
    from pdfminer.psparser import PSLiteral

    def nome(valor) -> str:
        valor = resolve1(valor)
        return valor.name if isinstance(valor, PSLiteral) else ""

    def conferir(valor) -> None:
        valor = resolve1(valor)
        if isinstance(valor, PDFStream) and nome(valor.get("Subtype")) == "Image":
            raise PdfRecusado(_MSG_ESTRUTURA, 422)

    def como_dict(valor) -> dict:
        valor = resolve1(valor)
        if isinstance(valor, PDFStream):
            return valor.attrs
        return valor if isinstance(valor, dict) else {}

    vistos: set[int] = set()

    def recursos(valor, profundidade: int) -> None:
        dic = como_dict(valor)
        if not dic or profundidade > 8 or id(dic) in vistos:
            return
        vistos.add(id(dic))
        for fonte in como_dict(dic.get("Font")).values():
            fonte = como_dict(fonte)
            conferir(fonte.get("ToUnicode"))
            conferir(fonte.get("Encoding"))
            descendentes = resolve1(fonte.get("DescendantFonts"))
            for f in [fonte, *(descendentes if isinstance(descendentes, list) else [])]:
                descritor = como_dict(como_dict(f).get("FontDescriptor"))
                for chave in ("FontFile", "FontFile2", "FontFile3"):
                    conferir(descritor.get(chave))
            for desenho in como_dict(fonte.get("CharProcs")).values():
                conferir(desenho)
            recursos(fonte.get("Resources"), profundidade + 1)
        for objeto in como_dict(dic.get("XObject")).values():
            objeto = resolve1(objeto)
            if isinstance(objeto, PDFStream) and nome(objeto.get("Subtype")) == "Form":
                recursos(objeto.get("Resources"), profundidade + 1)

    try:
        for pagina in paginas:
            for conteudo in pagina.contents:
                conferir(conteudo)
            recursos(pagina.resources, 0)
    except PdfRecusado:
        raise
    except Exception:  # noqa: BLE001 — estrutura quebrada: o pdfplumber dirá o mesmo
        return


# --------------------------------------------------------------------------
# Orçamento da análise — o teto DENTRO dos leitores (a garantia de verdade)
# --------------------------------------------------------------------------
# O medidor acima recusa cedo, antes de abrir o arquivo, mas é um SEGUNDO leitor do
# PDF: onde ele discordar do pdfminer (um byte de espaço, um "#"), o fluxo escapa da
# medida. A garantia, então, fica dentro dos próprios leitores: durante
# ``analisar_pdf``, TODA descompactação do pdfminer (motor do pdfplumber) e do pypdf
# (o leitor genérico, rede de segurança) gasta de um orçamento ÚNICO da análise, e
# passar dele recusa o arquivo com a mesma mensagem do medidor (413).
#
# O mesmo orçamento conta o que o pdfplumber MONTA sem descompactar nada a mais:
# caracteres (~2 KB de memória cada), operações de desenho, figuras e imagens, e as
# entradas dos mapas de caracteres. Um conteúdo compartilhado por várias páginas, um
# formulário desenhado mil vezes ou um intervalo "<00000000> <FFFFFFFF>" num mapa
# multiplicam o trabalho sem inflar um byte.
#
# As funções dos leitores são trocadas UMA vez (no primeiro uso, ``_instalar_tetos``)
# e só limitam quando há orçamento no contexto — um ``ContextVar``: cada requisição e
# cada thread enxergam só o seu. Sem orçamento, chamam a original, intacta: fora de
# ``analisar_pdf`` o pdfminer e o pypdf se comportam exatamente como antes.

#: Caracteres que a análise pode montar, somadas as páginas (um conteúdo desenhado
#: em várias páginas conta em cada uma). Calibração em 01/11 com 86 PDFs reais do
#: disco: o maior aceito tem ~80 mil (42 páginas). Relatório de plataforma: poucos
#: milhares. O pdfminer gasta ~0,1 ms por caractere: 150 mil ≈ 15 s no pior caso.
PDF_MAX_CARACTERES = 150_000
#: ... e numa página só: a memória do pdfplumber (~2 KB por caractere) é por página,
#: liberada quando ela fecha. A página real mais densa medida tem ~6,5 mil.
PDF_MAX_CARACTERES_PAGINA = 30_000
#: Operações de desenho (cada trecho de caminho), figuras e imagens — somadas e numa
#: página só (cada retângulo custa ~4 KB e ~0,5 ms ao pdfplumber). Reais (86 PDFs em
#: 01/11): o maior PDF aceito (225 páginas) tem ~110 mil no total — margem de só
#: ~1,36x até o teto — e o mais denso, ~14,6 mil numa página (~2x). Pela conta só dos
#: desenhos, o pior caso permitido chegaria a ~75 s de CPU: quem o corta é o prazo
#: (``PDF_MAX_SEGUNDOS``).
PDF_MAX_DESENHOS = 150_000
PDF_MAX_DESENHOS_PAGINA = 30_000
#: Leitor genérico (pypdf, quando nenhum perfil casa): teto PRÓPRIO do descompactado,
#: bem abaixo do geral — ele só lê conteúdo das páginas, fontes e formulários (nos
#: PDFs reais, no máximo ~4,5 MB, o de 225 páginas; o geral inclui o resto do arquivo).
PDF_MAX_DESCOMPRIMIDO_GENERICO = 10 * 1024 * 1024
#: O texto que o leitor genérico extrai conta no MESMO teto de caracteres (só o
#: texto, sem os espaços e quebras de linha). O modo layout do pypdf acrescenta
#: espaços para alinhar as colunas (nos PDFs reais, até ~4 vezes o texto, mas no
#: máximo ~146 mil caracteres no total e ~12 mil numa página): com eles, o teto é
#: este múltiplo do de caracteres — por página e no total.
_FATOR_ESPACOS_GENERICO = 4
#: Entradas criadas pelos mapas de caracteres das fontes (um mapa real tem centenas,
#: uma fonte asiática completa, dezenas de milhares).
PDF_MAX_ENTRADAS_MAPA = 500_000
#: Prazo da análise INTEIRA (medidor, pdfplumber, leitor genérico e a análise do
#: texto). Os tetos acima limitam o que se monta, não o tempo: dentro de todos eles um
#: PDF ainda segurava o processo por dezenas de segundos. Nos 86 PDFs reais (01/11) a
#: parte com orçamento leva no máximo ~9 a 12 s (o de 225 páginas; o de 42 páginas,
#: ~9 s), e a análise inteira até ~15 s: 30 s deixam margem de ~2 a 2,5x da análise
#: inteira. Conferido a cada ``_PASSOS_PRAZO`` contas (caracteres, desenhos, bytes,
#: entradas de mapa), a cada página e entre as etapas. O tempo conta desde antes do
#: medidor.
PDF_MAX_SEGUNDOS = 30
_PASSOS_PRAZO = 256
#: Relógio do prazo (os testes o trocam).
_agora = time.monotonic
#: Modo layout do leitor genérico: o pypdf monta a página INTEIRA antes de qualquer
#: conta, escrevendo cada linha numa grade do tamanho da letra média e enchendo cada
#: lacuna de espaços (até 10 mil por lacuna, e o texto de uma linha é emendado com
#: custo quadrático). Uma linha de milhares de letras, uma lacuna enorme ou uma fonte
#: de fração de ponto custavam centenas de MB e dezenas de segundos numa página só.
#: Com o que o pdfplumber já mediu da página (``_so_texto_simples``), o genérico a lê
#: só no modo simples (sem alinhar as colunas) quando uma linha visual passa de
#: ``PDF_LAYOUT_MAX_LINHA`` letras ou colunas estimadas, ou quando a página tem mais de
#: ``PDF_LAYOUT_MAX_LETRAS_MIUDAS`` letras com menos de ``PDF_LAYOUT_LETRA_MIUDA`` pt de
#: largura (fonte de ~2 pt para baixo). PDFs reais (86, em 01/11): a maior linha tem
#: 331 letras e ~224 colunas estimadas, e nenhuma página passa de 29 letras miúdas.
PDF_LAYOUT_MAX_LINHA = 500
PDF_LAYOUT_LETRA_MIUDA = 1.0
PDF_LAYOUT_MAX_LETRAS_MIUDAS = 100


def _milhar(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def _msg_caracteres(teto: int, onde: str = "") -> str:
    return (f"O PDF tem texto demais para um relatório de plataforma (mais de "
            f"{_milhar(teto)} caracteres{onde}) e foi recusado. Os relatórios do Matific e "
            "do Elefante ficam muito abaixo disso: confira se é o arquivo certo e envie de novo.")


def _msg_desenhos(teto: int, onde: str = "") -> str:
    return (f"O PDF tem desenhos demais para um relatório de plataforma (mais de "
            f"{_milhar(teto)} traços e figuras{onde}) e foi recusado. Os relatórios do "
            "Matific e do Elefante ficam muito abaixo disso: confira se é o arquivo certo "
            "e envie de novo.")


# Texto com os espaços do modo layout: o teto efetivo é outro (``_FATOR_ESPACOS_
# GENERICO`` vezes o de caracteres) e citar o número confundiria.
_MSG_TEXTO_DEMAIS = ("O PDF tem texto demais para um relatório de plataforma e foi recusado. "
                     "Os relatórios do Matific e do Elefante ficam muito abaixo disso: "
                     "confira se é o arquivo certo e envie de novo.")


def _msg_prazo(segundos: int) -> str:
    return (f"O PDF é pesado demais para ser lido (a leitura passou de {segundos} "
            "segundos) e foi recusado. Os relatórios do Matific e do Elefante são lidos em "
            "poucos segundos: confira se é o arquivo certo e envie de novo.")


class _OrcamentoAnalise:
    """O que UMA análise ainda pode gastar. A primeira recusa fica guardada: se algum
    leitor engolir a exceção (o pdfplumber embrulha tudo em ``PdfminerException``, o
    leitor genérico tenta de novo), ``analisar_pdf`` recusa mesmo assim — e, esgotado,
    o orçamento recusa de novo a cada chamada, sem trabalho."""

    def __init__(self) -> None:
        self.teto_bytes = PDF_MAX_DESCOMPRIMIDO
        self.bytes = self.teto_bytes
        self.tetos = (PDF_MAX_CARACTERES, PDF_MAX_CARACTERES_PAGINA,
                      PDF_MAX_DESENHOS, PDF_MAX_DESENHOS_PAGINA)
        self.caracteres, _, self.desenhos, _ = self.tetos
        self.entradas_mapa = PDF_MAX_ENTRADAS_MAPA
        self.texto_generico = self.caracteres * _FATOR_ESPACOS_GENERICO
        self.recusa: PdfRecusado | None = None
        self.segundos = PDF_MAX_SEGUNDOS
        self.prazo = _agora() + self.segundos
        self.passos_ate_o_relogio = _PASSOS_PRAZO
        # Por página do pdfplumber, na ordem: ler no genérico só no modo simples?
        # (None: o pdfplumber não chegou a medir.)
        self.paginas_sem_layout: list[bool] | None = None
        self.nova_pagina()

    def nova_pagina(self) -> None:
        """Zera as contas POR PÁGINA (chamado antes de cada página ser lida)."""
        self.conferir_prazo()
        self.caracteres_pagina = self.tetos[1]
        self.desenhos_pagina = self.tetos[3]

    def conferir_prazo(self) -> None:
        if _agora() > self.prazo:
            self.recusar(_msg_prazo(self.segundos))

    def _passo(self) -> None:
        """Uma conta a mais: o relógio é olhado a cada ``_PASSOS_PRAZO`` delas."""
        self.passos_ate_o_relogio -= 1
        if self.passos_ate_o_relogio <= 0:
            self.passos_ate_o_relogio = _PASSOS_PRAZO
            self.conferir_prazo()

    def sem_layout(self, pagina) -> bool:
        """O leitor genérico deve ler esta página (``pypdf.PageObject``) só no modo
        simples? Sim quando o pdfplumber a mediu arriscada (``_so_texto_simples``) e
        também quando não a mediu — falhou, ou contou outro número de páginas: sem a
        medida, o modo simples é o seguro."""
        medidas = self.paginas_sem_layout
        try:
            indice = pagina.page_number
            total = len(pagina.pdf.pages)
        except Exception:  # noqa: BLE001 — sem saber qual página é: modo simples
            return True
        if medidas is None or indice is None or total != len(medidas) \
                or not 0 <= indice < total:
            return True
        return medidas[indice]

    def novo_leitor(self, teto_bytes: int | None = None) -> None:
        """O leitor genérico relê o arquivo do zero, com o pdfplumber já solto: os tetos
        valem para CADA leitura, nunca para as duas somadas (senão um relatório de 30 MB
        seria recusado como "mais de 50 MB"). ``teto_bytes``: o teto do descompactado
        desta leitura (o genérico tem um menor); os caracteres recomeçam do teto."""
        self.conferir()
        if teto_bytes is not None:
            self.teto_bytes = teto_bytes
        self.bytes = self.teto_bytes
        self.caracteres = self.tetos[0]
        self.texto_generico = self.tetos[0] * _FATOR_ESPACOS_GENERICO
        self.nova_pagina()

    def contar_texto_generico(self, texto: str) -> None:
        """Conta o texto de UMA página extraída pelo leitor genérico (pypdf): o texto
        sem espaços no teto de caracteres (por página e no total), e com os espaços do
        modo layout num teto ``_FATOR_ESPACOS_GENERICO`` vezes maior."""
        sem_espacos = len(texto) - sum(texto.count(c) for c in " \n\r\t")
        self.caracteres -= sem_espacos
        self.caracteres_pagina -= sem_espacos
        self.texto_generico -= len(texto)
        teto_total, teto_pagina = self.tetos[0], self.tetos[1]
        if self.caracteres_pagina < 0:
            self.recusar(_msg_caracteres(teto_pagina, " numa página"))
        if self.caracteres < 0:
            self.recusar(_msg_caracteres(teto_total))
        if len(texto) > teto_pagina * _FATOR_ESPACOS_GENERICO or self.texto_generico < 0 \
                or self.recusa is not None:
            self.recusar(_MSG_TEXTO_DEMAIS)
        self.conferir_prazo()

    def recusar(self, mensagem: str, status_http: int = 413):
        if self.recusa is None:
            self.recusa = PdfRecusado(mensagem, status_http)
        raise PdfRecusado(str(self.recusa), self.recusa.status_http)

    def livre(self) -> int:
        """Teto de saída da próxima chamada: um byte além do que resta (sair esse
        byte já é estourar)."""
        return max(self.bytes, 0) + 1

    def gastar(self, n: int) -> None:
        self.bytes -= n
        if self.bytes < 0 or self.recusa is not None:
            self.recusar(_msg_teto(self.teto_bytes))
        self._passo()

    def exigir(self, n: int) -> None:
        """Recusa já se ``n`` bytes não cabem (teto conhecido ANTES de decodificar)."""
        if n > max(self.bytes, 0):
            self.estourar()

    def estourar(self) -> None:
        self.bytes = -1
        self.recusar(_msg_teto(self.teto_bytes))

    def conferir(self) -> None:
        """Recusa se alguma recusa já aconteceu (mesmo que um leitor a tenha engolido)
        ou se o prazo da análise acabou."""
        if self.recusa is not None:
            raise PdfRecusado(str(self.recusa), self.recusa.status_http)
        self.conferir_prazo()

    def contar_caractere(self) -> None:
        self.caracteres -= 1
        self.caracteres_pagina -= 1
        if self.caracteres_pagina < 0:
            self.recusar(_msg_caracteres(self.tetos[1], " numa página"))
        if self.caracteres < 0 or self.recusa is not None:
            self.recusar(_msg_caracteres(self.tetos[0]))
        self._passo()

    def contar_desenho(self) -> None:
        self.desenhos -= 1
        self.desenhos_pagina -= 1
        if self.desenhos_pagina < 0:
            self.recusar(_msg_desenhos(self.tetos[3], " numa página"))
        if self.desenhos < 0 or self.recusa is not None:
            self.recusar(_msg_desenhos(self.tetos[2]))
        self._passo()

    def contar_entrada_mapa(self) -> None:
        self.entradas_mapa -= 1
        if self.entradas_mapa < 0 or self.recusa is not None:
            self.recusar(_MSG_ESTRUTURA, 422)
        self._passo()


_ORCAMENTO: contextvars.ContextVar[_OrcamentoAnalise | None] = contextvars.ContextVar(
    "perfis_pdf_orcamento", default=None)


@contextmanager
def _orcamento_da_analise():
    """Instala o orçamento da análise no contexto atual (só nele) e o devolve."""
    _instalar_tetos()
    orcamento = _OrcamentoAnalise()
    ficha = _ORCAMENTO.set(orcamento)
    try:
        yield orcamento
    finally:
        _ORCAMENTO.reset(ficha)


def _com_teto(original, limitada):
    """Sem orçamento no contexto: ``original``, intacta. Com orçamento:
    ``limitada(orcamento, original, *args)``."""
    @functools.wraps(original)
    def trocada(*args, **kwargs):
        orcamento = _ORCAMENTO.get()
        if orcamento is None:
            return original(*args, **kwargs)
        return limitada(orcamento, original, *args, **kwargs)

    trocada.teto_perfis_pdf = True
    return trocada


def _dar_ao_zlib(d, dado, orcamento: _OrcamentoAnalise) -> bytes:
    """Uma chamada ao descompressor com teto. Saindo menos que o teto, o zlib consumiu
    toda a entrada; saindo o teto, o orçamento estourou."""
    saida = d.decompress(dado, orcamento.livre())
    orcamento.gastar(len(saida))
    return saida


def _inflar_com_teto(orcamento, _original, dado, wbits=zlib.MAX_WBITS, bufsize=None):
    """``zlib.decompress`` com teto. Mesmo resultado — inclusive o erro do fluxo
    truncado, que leva o pdfminer à leitura de recuperação."""
    d = zlib.decompressobj(wbits)
    saida = _dar_ao_zlib(d, dado, orcamento)
    if not d.eof:
        raise zlib.error("Error -5 while decompressing data: incomplete or truncated stream")
    return saida


class _DescompressorComTeto:
    """Um ``zlib.decompressobj`` que gasta do orçamento a cada saída (o pdfminer de
    hoje só o usa na leitura de recuperação, também trocada; fica por garantia)."""

    def __init__(self, real, orcamento: _OrcamentoAnalise):
        self._real = real
        self._orcamento = orcamento

    def decompress(self, dado, max_length: int = 0) -> bytes:
        teto = self._orcamento.livre()
        saida = self._real.decompress(dado, min(max_length, teto) if max_length else teto)
        self._orcamento.gastar(len(saida))
        return saida

    def flush(self, *args) -> bytes:
        # O flush consumiria SEM teto a entrada que sobrou: ela passa antes pelo teto.
        saida = self.decompress(self._real.unconsumed_tail) if self._real.unconsumed_tail else b""
        resto = self._real.flush(*args)
        self._orcamento.gastar(len(resto))
        return saida + resto

    def copy(self) -> "_DescompressorComTeto":
        return _DescompressorComTeto(self._real.copy(), self._orcamento)

    def __getattr__(self, nome):
        return getattr(self._real, nome)


class _ZlibDoPdfminer:
    """O ``zlib`` que o ``pdfminer.pdftypes`` enxerga: ``decompress`` e
    ``decompressobj`` com teto quando há orçamento; o resto é o zlib de verdade."""

    def __init__(self, real):
        self._real = real
        self.decompress = _com_teto(real.decompress, _inflar_com_teto)

    def decompressobj(self, *args, **kwargs):
        d = self._real.decompressobj(*args, **kwargs)
        orcamento = _ORCAMENTO.get()
        return d if orcamento is None else _DescompressorComTeto(d, orcamento)

    def __getattr__(self, nome):
        return getattr(self._real, nome)


def _inflar_corrompido(orcamento, _original, dado) -> bytes:
    """``decompress_corrupted`` do pdfminer (fluxo corrompido: alimenta o zlib byte a
    byte e fica com o que saiu até o erro) com teto e sem o custo quadrático do
    original, que junta a saída com ``+=`` a cada byte de entrada. Mesmo resultado:
    alimenta em blocos e só refaz byte a byte, de uma cópia do estado, o bloco do erro."""
    d = zlib.decompressobj()
    partes: list[bytes] = []
    total = len(dado)
    for inicio in range(0, total, _BLOCO_INFLAR):
        bloco = dado[inicio:inicio + _BLOCO_INFLAR]
        reserva = d.copy()
        try:
            partes.append(_dar_ao_zlib(d, bloco, orcamento))
            continue
        except zlib.error:
            d = reserva
        for i in range(len(bloco)):
            try:
                partes.append(_dar_ao_zlib(d, bloco[i:i + 1], orcamento))
            except zlib.error:
                if inicio + i < total - 3:
                    raise
                return b"".join(partes)   # erro só na soma de verificação: como o original
    return b"".join(partes)


def _lzw_com_teto(orcamento, _original, dado) -> bytes:
    """``lzwdecode`` com teto: o mesmo decodificador, contando cada pedaço que sai (a
    tabela do LZW cresce junto com a saída, e fica limitada com ela)."""
    from pdfminer.lzw import LZWDecoder

    partes: list[bytes] = []
    for parte in LZWDecoder(io.BytesIO(dado)).run():
        orcamento.gastar(len(parte))
        partes.append(parte)
    return b"".join(partes)


def _a85_com_teto(orcamento, original, dado) -> bytes:
    # 5 caracteres viram 4 bytes; "z" vira 4 bytes sozinho: o teto ANTES de decodificar.
    orcamento.exigir((len(dado) * 4) // 5 + 4 * dado.count(b"z") + 4)
    saida = original(dado)
    orcamento.gastar(len(saida))
    return saida


def _ahx_com_teto(orcamento, original, dado) -> bytes:
    saida = original(dado)    # sai no máximo metade do que entra
    orcamento.gastar(len(saida))
    return saida


def _rl_com_teto(orcamento, _original, dado) -> bytes:
    """``rldecode`` com teto, e sem a lista de um inteiro por byte do original (~8x a
    saída em memória). Mesmo resultado, inclusive o erro nos dados truncados."""
    saida = bytearray()
    i, total = 0, len(dado)
    while i < total:
        n = dado[i]
        i += 1
        if n == 128:
            break
        if n < 128:
            trecho = bytes(dado[i:i + n + 1])
            if len(trecho) < n + 1:
                raise RuntimeError("generator raised StopIteration")   # como o original
            i += n + 1
        else:
            if i >= total:
                raise StopIteration                                     # como o original
            trecho = bytes(dado[i:i + 1]) * (257 - n)
            i += 1
        orcamento.gastar(len(trecho))
        saida += trecho
    return bytes(saida)


def _ccitt_recusado(orcamento, _original, *_args, **_kwargs):
    """Fax (CCITT): o pdfminer só o decodifica para ler texto quando ele vem disfarçado
    de conteúdo, fonte ou mapa (imagens ficam compactadas), e a decodificação custa
    uma volta de Python por PIXEL e uma lista do tamanho da largura declarada a cada
    linha. Nenhum relatório faz isso: recusa."""
    orcamento.recusar(_MSG_ESTRUTURA, 422)


def _caractere_com_teto(orcamento, original, *args, **kwargs):
    orcamento.contar_caractere()
    return original(*args, **kwargs)


def _desenho_com_teto(orcamento, original, *args, **kwargs):
    orcamento.contar_desenho()
    return original(*args, **kwargs)


def _operacao_com_teto(original):
    """Uma operação de caminho do interpretador (m, l, c, v, y, h, re) que conta um
    desenho. O pdfminer descobre quantos operandos tirar da pilha pelo
    ``__code__.co_argcount`` da função: o envoltório tem a MESMA aridade — um
    ``*args`` (co_argcount 0) faria a operação nunca rodar e bagunçaria a pilha."""
    def contar() -> None:
        orcamento = _ORCAMENTO.get()
        if orcamento is not None:
            orcamento.contar_desenho()

    aridade = original.__code__.co_argcount
    if aridade == 1:
        def trocada(self):
            contar()
            return original(self)
    elif aridade == 3:
        def trocada(self, a, b):
            contar()
            return original(self, a, b)
    elif aridade == 5:
        def trocada(self, a, b, c, d):
            contar()
            return original(self, a, b, c, d)
    elif aridade == 7:
        def trocada(self, a, b, c, d, e, f):
            contar()
            return original(self, a, b, c, d, e, f)
    else:
        # Outra versão do pdfminer mudou a operação: fica sem conta (os testes avisam),
        # nunca quebrada.
        return original
    functools.update_wrapper(trocada, original)
    trocada.teto_perfis_pdf = True
    return trocada


def _entrada_mapa_com_teto(orcamento, original, *args, **kwargs):
    orcamento.contar_entrada_mapa()
    return original(*args, **kwargs)


def _pypdf_com_teto(orcamento, original, fluxo):
    """``decode_stream_data`` do pypdf (o leitor genérico): os tetos do próprio pypdf
    caem para o que resta do orçamento e o que sai é gasto. Estouro dos tetos dele
    (``LimitReachedError``) vira a mesma recusa."""
    import pypdf
    from pypdf.errors import LimitReachedError

    orcamento.gastar(0)            # esgotado: recusa sem decodificar de novo
    teto = orcamento.livre()
    try:
        with pypdf.apply_configuration(**{nome: teto for nome in _TETOS_PYPDF}):
            saida = original(fluxo)
    except LimitReachedError:
        orcamento.estourar()       # o teto do pypdf era o que restava do orçamento
        raise
    orcamento.gastar(len(saida))
    return saida


def _texto_pypdf_com_teto(orcamento, original, pagina, *args, **kwargs):
    """``PageObject.extract_text`` do pypdf (o leitor genérico extrai o texto página a
    página): cada chamada é uma leitura da página — as contas por página recomeçam — e
    o texto que sai é contado (``contar_texto_generico``). Já recusado (inclusive numa
    recusa que o leitor engoliu) ou sem prazo, recusa de novo sem extrair. O modo
    layout vira o simples na página que o pdfplumber mediu arriscada, ou não mediu
    (``_OrcamentoAnalise.sem_layout``)."""
    orcamento.conferir()
    orcamento.nova_pagina()
    if kwargs.get("extraction_mode") == "layout" and orcamento.sem_layout(pagina):
        kwargs["extraction_mode"] = "plain"
    texto = original(pagina, *args, **kwargs)
    orcamento.contar_texto_generico(texto or "")
    return texto


#: Tetos de saída do pypdf (por fluxo, ``pypdf.Configuration``) que caem para o que
#: resta do orçamento.
_TETOS_PYPDF = ("zlib_maximum_output_length", "lzw_maximum_output_length",
                "run_length_maximum_output_length", "brotli_maximum_output_length",
                "jbig2_maximum_output_length", "array_based_stream_maximum_output_length")

_TETOS_INSTALADOS = False
_TRAVA_TETOS = threading.Lock()


def _trocar(alvo, nome: str, limitada) -> None:
    original = getattr(alvo, nome)
    if not getattr(original, "teto_perfis_pdf", False):
        setattr(alvo, nome, _com_teto(original, limitada))


def _instalar_tetos() -> None:
    """Troca, uma vez, as funções do pdfminer e do pypdf que descompactam ou montam
    objetos pelas versões que gastam do orçamento da análise (e que, sem orçamento
    no contexto, chamam a original). Todo o caminho de descompactação do pdfminer
    passa por ``PDFStream.decode``, que procura estes nomes no módulo a cada chamada."""
    global _TETOS_INSTALADOS
    if _TETOS_INSTALADOS:
        return
    with _TRAVA_TETOS:
        if _TETOS_INSTALADOS:
            return
        import pypdf.filters
        from pdfminer import cmapdb, converter, pdfinterp, pdftypes

        if not isinstance(pdftypes.zlib, _ZlibDoPdfminer):
            pdftypes.zlib = _ZlibDoPdfminer(pdftypes.zlib)
        _trocar(pdftypes, "decompress_corrupted", _inflar_corrompido)
        _trocar(pdftypes, "lzwdecode", _lzw_com_teto)
        _trocar(pdftypes, "ascii85decode", _a85_com_teto)
        _trocar(pdftypes, "asciihexdecode", _ahx_com_teto)
        _trocar(pdftypes, "rldecode", _rl_com_teto)
        _trocar(pdftypes, "ccittfaxdecode", _ccitt_recusado)
        # O que o pdfplumber monta: cada caractere, cada trecho de caminho (antes de a
        # página ser desenhada: o caminho cresce na memória a cada operação), cada
        # figura (um formulário desenhado) e cada imagem.
        _trocar(converter.PDFLayoutAnalyzer, "render_char", _caractere_com_teto)
        for operacao in ("do_m", "do_l", "do_c", "do_v", "do_y", "do_h", "do_re"):
            original = getattr(pdfinterp.PDFPageInterpreter, operacao)
            if not getattr(original, "teto_perfis_pdf", False):
                setattr(pdfinterp.PDFPageInterpreter, operacao, _operacao_com_teto(original))
        _trocar(converter.PDFLayoutAnalyzer, "begin_figure", _desenho_com_teto)
        _trocar(converter.PDFLayoutAnalyzer, "render_image", _desenho_com_teto)
        # Mapas de caracteres: um intervalo "<00000000> <FFFFFFFF>" cria 4 bilhões de
        # entradas, uma a uma.
        _trocar(cmapdb.FileCMap, "add_code2cid", _entrada_mapa_com_teto)
        _trocar(cmapdb.FileUnicodeMap, "add_cid2unichr", _entrada_mapa_com_teto)
        _trocar(pypdf.filters, "decode_stream_data", _pypdf_com_teto)
        _trocar(pypdf.PageObject, "extract_text", _texto_pypdf_com_teto)
        _TETOS_INSTALADOS = True


# --------------------------------------------------------------------------
# Extração de palavras com posição
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Palavra:
    texto: str
    x0: float
    x1: float
    topo: float


@dataclass
class Pagina:
    numero: int
    palavras: list[Palavra]


def _so_texto_simples(palavras: list[Palavra]) -> bool:
    """A página deve ser lida pelo leitor genérico só no modo simples (ver
    ``PDF_LAYOUT_MAX_LINHA``)? O modo layout do pypdf põe cada linha numa grade de
    colunas do tamanho da letra média da página: o comprimento de uma linha nessa grade
    é estimado pela extensão dela (do começo do texto da página até o fim da linha)
    dividida pela largura média de uma letra — uma lacuna enorme alonga a linha, e uma
    fonte de fração de ponto encolhe a letra média. Letras miúdas, se poucas, não pesam
    na média, mas cada lacuna depois delas ainda vira milhares de espaços: muitas
    delas também levam ao modo simples."""
    letras = sum(len(p.texto) for p in palavras)
    if not letras:
        return False
    miudas = sum(len(p.texto) for p in palavras
                 if p.x1 - p.x0 < PDF_LAYOUT_LETRA_MIUDA * len(p.texto))
    if miudas > PDF_LAYOUT_MAX_LETRAS_MIUDAS:
        return True
    letra = sum(max(p.x1 - p.x0, 0.0) for p in palavras) / letras
    if letra <= 0:
        return True
    inicio = min(p.x0 for p in palavras)
    for linha in _linhas_visuais(palavras):
        caracteres = sum(len(p.texto) + 1 for p in linha.palavras) - 1
        colunas = (max(p.x1 for p in linha.palavras) - inicio) / letra
        if max(caracteres, colunas) > PDF_LAYOUT_MAX_LINHA:
            return True
    return False


def _repassar_recusa(exc: BaseException) -> None:
    """O pdfplumber embrulha as exceções do pdfminer em ``PdfminerException``: a
    recusa do orçamento que vier embrulhada sai como ela mesma."""
    for causa in (*exc.args[:1], exc.__cause__, exc.__context__):
        if isinstance(causa, PdfRecusado):
            raise PdfRecusado(str(causa), causa.status_http) from exc


def extrair_paginas(conteudo: bytes) -> list[Pagina]:
    """Palavras de cada página com coordenadas (pdfplumber).

    Quem chama confere o descompactado ANTES (``exigir_pdf_contido``, em
    ``analisar_pdf``) e, durante a leitura, o orçamento da análise limita o que o
    pdfminer descompacta e monta (caracteres, desenhos). Aqui, com o documento aberto
    e antes de ler qualquer página, confere o número de páginas (``exigir_paginas``);
    e cada página é liberada logo depois de lida — o pdfplumber guarda ~2 KB por
    caractere até a página ser fechada, e antes elas só eram fechadas no fim."""
    import pdfplumber
    from pdfplumber.utils.exceptions import PdfminerException

    # PDFs do Elefante têm fontes sem FontBBox — o aviso não interessa aqui
    logging.getLogger("pdfminer").setLevel(logging.ERROR)

    paginas: list[Pagina] = []
    try:
        pdf = pdfplumber.open(io.BytesIO(conteudo))
    except PdfminerException as exc:
        _repassar_recusa(exc)
        raise
    try:
        exigir_paginas(pdf.doc)
        orcamento = _ORCAMENTO.get()
        if orcamento is not None:
            orcamento.paginas_sem_layout = []
        for numero, pagina in enumerate(pdf.pages, start=1):
            if orcamento is not None:
                orcamento.nova_pagina()
            try:
                palavras = [
                    Palavra(p["text"], float(p["x0"]), float(p["x1"]), float(p["top"]))
                    for p in pagina.extract_words(x_tolerance=2.5)
                ]
            finally:
                pagina.close()
            if orcamento is not None:
                # A medida que o leitor genérico usa, se nenhum perfil casar.
                orcamento.paginas_sem_layout.append(_so_texto_simples(palavras))
            paginas.append(Pagina(numero=numero, palavras=palavras))
    except PdfminerException as exc:
        _repassar_recusa(exc)
        raise
    finally:
        # Não ``pdf.close()``: ele percorre a árvore de páginas INTEIRA de novo, sem o
        # teto — o mesmo PDF que acabou de ser recusado por páginas demais seria lido
        # até a última. Cada página aberta já foi fechada acima; aqui só se solta o
        # resto (o arquivo é um BytesIO nosso, nada a fechar no disco).
        pdf.flush_cache()
    return paginas


def compactar(texto: str) -> str:
    """Normaliza e remove TODO espaço — imune ao espaçamento intra-letra
    que esses PDFs produzem ("Re la tó rio" → "relatorio")."""
    return normalizar_nome(texto).replace(" ", "")


# --------------------------------------------------------------------------
# Conversões tolerantes
# --------------------------------------------------------------------------

_RE_RELOGIO = re.compile(r"^(\d+):([0-5]?\d)(?::([0-5]?\d))?$")
_RE_DATA = re.compile(r"^([0-3]?\d)/([01]?\d)/(\d{4})$")


def duracao_em_minutos(bruto: str) -> int:
    """Aceita "19:40:02", "0:06:04", "42 h 09 min 01 s", "00 s" → minutos."""
    plano = normalizar_nome(bruto)
    relogio = _RE_RELOGIO.match(plano.replace(" ", ""))
    if relogio:
        horas, minutos, segundos = (int(g or 0) for g in relogio.groups())
        return round(horas * 60 + minutos + segundos / 60)
    horas = re.search(r"(\d+)\s*h(?![a-z0-9])", plano)
    minutos_m = re.search(r"(\d+)\s*min", plano)
    segundos_m = re.search(r"(\d+)\s*s(?![a-z0-9])", plano)
    if not (horas or minutos_m or segundos_m):
        raise ValueError(f"duração ilegível: {bruto!r}")
    total = ((int(horas.group(1)) * 60 if horas else 0)
             + (int(minutos_m.group(1)) if minutos_m else 0)
             + (int(segundos_m.group(1)) / 60 if segundos_m else 0))
    return round(total)


def _data_iso(bruto: str) -> str:
    par = _RE_DATA.match(bruto.strip())
    if not par:
        raise ValueError(f"data ilegível: {bruto!r}")
    dia, mes, ano = par.groups()
    return f"{ano}-{int(mes):02d}-{int(dia):02d}"


def _data_hora_iso(par: tuple[str, str | None]) -> str:
    """Combina "DD/MM/AAAA" com um horário "HH:MM:SS" opcional → ISO datetime.
    Sem horário, devolve só a data (o import grava à meia-noite). O relatório
    individual do Elefante traz data e hora empilhadas na coluna "Data/Hora"."""
    data_str, hora_str = par
    dia_iso = _data_iso(data_str)  # "AAAA-MM-DD"
    if hora_str:
        rel = _RE_RELOGIO.match(hora_str.strip())
        if rel:
            h, m, s = (int(g or 0) for g in rel.groups())
            return f"{dia_iso}T{h:02d}:{m:02d}:{s:02d}"
    return dia_iso


# --------------------------------------------------------------------------
# Linhas visuais e colunas
# --------------------------------------------------------------------------

TOLERANCIA_LINHA = 4.0   # unidades ("min", "s") ficam ~3,3pt abaixo do número
TOLERANCIA_COLUNA = 3.0  # rótulos empilhados do cabeçalho compartilham o x0


@dataclass
class LinhaVisual:
    topo: float
    palavras: list[Palavra] = field(default_factory=list)

    @property
    def texto(self) -> str:
        return " ".join(p.texto for p in sorted(self.palavras, key=lambda p: p.x0))


def _linhas_visuais(palavras: list[Palavra]) -> list[LinhaVisual]:
    linhas: list[LinhaVisual] = []
    for palavra in sorted(palavras, key=lambda p: (p.topo, p.x0)):
        if linhas and palavra.topo - linhas[-1].topo <= TOLERANCIA_LINHA:
            linhas[-1].palavras.append(palavra)
        else:
            linhas.append(LinhaVisual(topo=palavra.topo, palavras=[palavra]))
    return linhas


@dataclass
class Coluna:
    campo: str
    x0: float
    x_min: float = float("-inf")
    x_max: float = float("inf")


def _delimitar(colunas: list[Coluna]) -> list[Coluna]:
    """Fronteira entre colunas = âncora da coluna seguinte (dados alinhados
    à esquerda: tudo que começa antes da próxima âncora pertence à atual)."""
    ordenadas = sorted(colunas, key=lambda c: c.x0)
    for anterior, atual in zip(ordenadas, ordenadas[1:]):
        anterior.x_max = atual.x0 - 2.0
        atual.x_min = atual.x0 - 2.0
    return ordenadas


def _coluna_de(colunas: list[Coluna], palavra: Palavra) -> Coluna | None:
    for coluna in colunas:
        if coluna.x_min <= palavra.x0 < coluna.x_max:
            return coluna
    return None


# --------------------------------------------------------------------------
# Cabeçalhos: detecção por vocabulário e mapa de colunas por x0
# --------------------------------------------------------------------------

def _vocabulario(colunas_def: dict[str, list[str]], com_nome: bool) -> set[str]:
    """Todos os tokens que podem aparecer num cabeçalho deste perfil."""
    tokens: set[str] = set()
    sinonimos = [s for lista in colunas_def.values() for s in lista]
    if com_nome:
        sinonimos += ["nome do estudante", "nome do aluno", "aluno", "estudante"]
    for sinonimo in sinonimos:
        tokens.update(compactar(t) for t in sinonimo.split())
    return tokens


def _forca_cabecalho(linha: LinhaVisual, vocabulario: set[str]) -> str | None:
    """'forte' = linha claramente de cabeçalho; 'fraca' = só conectivos
    ("de", "do") — vale apenas colada a uma linha forte."""
    tokens = [compactar(p.texto) for p in linha.palavras]
    tokens = [t for t in tokens if t]
    if not tokens or any(any(c.isdigit() for c in t) for t in tokens):
        return None
    no_vocab = sum(1 for t in tokens if t in vocabulario)
    if no_vocab == len(tokens) and all(len(t) < 4 for t in tokens):
        return "fraca"
    if no_vocab / len(tokens) >= 0.6 and any(
            t in vocabulario and len(t) >= 4 for t in tokens):
        return "forte"
    return None


def _mapear_bloco(linhas_bloco: list[LinhaVisual],
                  colunas_def: dict[str, list[str]],
                  com_nome: bool) -> list[Coluna]:
    """Agrupa as palavras do bloco por x0; cada grupo vira um rótulo
    ("Leituras" + "Concluídas" empilhados = "Leituras Concluídas")."""
    palavras = [p for linha in linhas_bloco for p in linha.palavras]
    grupos: list[list[Palavra]] = []
    for palavra in sorted(palavras, key=lambda p: p.x0):
        if grupos and palavra.x0 - grupos[-1][0].x0 <= TOLERANCIA_COLUNA:
            grupos[-1].append(palavra)
        else:
            grupos.append([palavra])

    colunas: list[Coluna] = []
    mapeados: set[str] = set()
    for grupo in grupos:
        rotulo = " ".join(p.texto for p in sorted(grupo, key=lambda p: (p.topo, p.x0)))
        x0 = grupo[0].x0
        if com_nome and "nome" not in mapeados and _eh_coluna_nome(rotulo):
            colunas.append(Coluna(campo="nome", x0=x0))
            mapeados.add("nome")
            continue
        campo = _casar_coluna(rotulo, colunas_def, ignorar=mapeados)
        if campo:
            colunas.append(Coluna(campo=campo, x0=x0))
            mapeados.add(campo)
    return colunas


# --------------------------------------------------------------------------
# Tabela posicional: registros iniciados e costurados por coluna
# --------------------------------------------------------------------------

@dataclass
class Registro:
    topo: float
    campos: dict[str, list[Palavra]] = field(default_factory=dict)

    def texto(self, campo: str) -> str:
        palavras = sorted(self.campos.get(campo, []), key=lambda p: (p.topo, p.x0))
        return " ".join(p.texto for p in palavras).strip()


def _tabela_posicional(
    paginas: list[Pagina],
    colunas_def: dict[str, list[str]],
    *,
    com_nome: bool,
    aceitar_cabecalho,
    inicia_registro,
    ignorar_linha=None,
    anexo_por_proximidade: bool = False,
) -> list[Registro]:
    """Motor comum dos perfis: encontra cabeçalhos, delimita colunas e
    costura registros de várias linhas. O mapa de colunas persiste entre
    páginas — relatórios que só imprimem o cabeçalho uma vez também funcionam.
    """
    vocab = _vocabulario(colunas_def, com_nome)
    colunas: list[Coluna] | None = None
    registros: list[Registro] = []
    inicio_pagina = 0                      # `topo` é relativo à página: um
    orfas: list[LinhaVisual] = []          # fragmento só casa com registros
                                           # da MESMA página

    def _so_coluna_nome(linha: LinhaVisual) -> bool:
        """Fragmento que cai INTEIRO na coluna 'nome' e não tem dígitos — é um
        pedaço de nome quebrado (sobrenome numa 3ª linha), não turma/dado."""
        if colunas is None or not linha.palavras:
            return False
        for palavra in linha.palavras:
            coluna = _coluna_de(colunas, palavra)
            if coluna is None or coluna.campo != "nome" or any(c.isdigit() for c in palavra.texto):
                return False
        return True

    def _fechar_orfas() -> None:
        """Anexa cada fragmento ao registro mais próximo verticalmente.

        O nome do aluno pode quebrar em 3 linhas visuais (o registro nasce na
        do meio): as pontas ficam a ~1 altura de linha (~16pt), acima do limiar
        de 12pt usado para a turma fatiada. Fragmentos que caem só na coluna
        'nome' ganham um limiar maior — sem alcançar a próxima linha de dados
        (~23pt adiante), então não invadem o registro vizinho."""
        da_pagina = registros[inicio_pagina:]
        for linha in orfas:
            vizinho = min(da_pagina, key=lambda r: abs(r.topo - linha.topo),
                          default=None)
            limite = 18.0 if _so_coluna_nome(linha) else 12.0
            if vizinho is not None and abs(vizinho.topo - linha.topo) <= limite:
                _depositar(vizinho, linha)
        orfas.clear()

    def _depositar(registro: Registro, linha: LinhaVisual) -> None:
        for palavra in linha.palavras:
            coluna = _coluna_de(colunas, palavra)
            if coluna is not None:
                registro.campos.setdefault(coluna.campo, []).append(palavra)

    for pagina in paginas:
        inicio_pagina = len(registros)
        linhas = _linhas_visuais(pagina.palavras)
        forcas = [_forca_cabecalho(linha, vocab) for linha in linhas]
        registro_atual: Registro | None = None

        indice = 0
        while indice < len(linhas):
            # Bloco de cabeçalho: sequência com ao menos uma linha "forte"
            if forcas[indice] is not None:
                fim = indice
                while fim < len(linhas) and forcas[fim] is not None:
                    fim += 1
                bloco = linhas[indice:fim]
                if any(forcas[i] == "forte" for i in range(indice, fim)):
                    mapeadas = _mapear_bloco(bloco, colunas_def, com_nome)
                    if aceitar_cabecalho({c.campo for c in mapeadas}):
                        if anexo_por_proximidade:
                            _fechar_orfas()
                        colunas = _delimitar(mapeadas)
                        registro_atual = None
                        indice = fim
                        continue
                # Não era cabeçalho válido: trata as linhas como dados comuns
                indice_dados = indice
                indice = fim
                alcance = range(indice_dados, fim)
            else:
                alcance = range(indice, indice + 1)
                indice += 1

            for i in alcance:
                linha = linhas[i]
                if colunas is None:
                    continue  # dados antes do primeiro cabeçalho: resumo/capa
                if ignorar_linha is not None and ignorar_linha(linha):
                    continue
                presentes: dict[str, list[Palavra]] = {}
                for palavra in linha.palavras:
                    coluna = _coluna_de(colunas, palavra)
                    if coluna is not None:
                        presentes.setdefault(coluna.campo, []).append(palavra)
                if inicia_registro(presentes):
                    registro_atual = Registro(topo=linha.topo, campos={
                        campo: list(ps) for campo, ps in presentes.items()
                    })
                    registros.append(registro_atual)
                elif anexo_por_proximidade:
                    orfas.append(linha)
                elif registro_atual is not None:
                    _depositar(registro_atual, linha)
        if anexo_por_proximidade:
            _fechar_orfas()
    return registros


def _atribuir(item: LinhaImportacao, campo: str, bruto: str, conversor) -> None:
    """Conversão tolerante: falha vira aviso, nunca derruba a linha (§51).

    Número impossível (infinito, ou acima de ``VALOR_MAXIMO`` — o RA ou o telefone
    caído na coluna) também é ilegível: a mesma régua da planilha e do /confirmar
    (``importacao.valor_plausivel``). Antes o "inf" estourava ``int()`` com
    OverflowError e derrubava a prévia inteira, e o gigante só era recusado (400)
    na confirmação."""
    if not bruto:
        return
    try:
        valor = conversor(bruto)
        if (isinstance(valor, (int, float)) and not isinstance(valor, bool)
                and not valor_plausivel(valor)):
            raise ValueError("fora da faixa")
        item.dados[campo] = valor
    except (ValueError, TypeError, OverflowError):
        item.avisos.append(f"“{campo}” ilegível ({bruto!r}) — campo ficará ausente.")


def _inteiro(bruto: str) -> int:
    return int(_numero_plausivel(bruto))


# --------------------------------------------------------------------------
# Perfil 1 — Elefante Letrado · relatório de performance da TURMA
# --------------------------------------------------------------------------

# Os campos de escuta (não pontuados) vêm ANTES dos de leitura para que
# "Livros Escutados" nunca seja capturado pelo sinônimo genérico "livros".
COLUNAS_PERFIL_TURMA = {
    "nivel": ["nivel"],
    "livros_escutados": ["livros escutados"],
    "tempo_escuta": ["tempo de escuta"],
    "livros_unicos": ["leituras concluidas", "livros lidos", "leituras"],
    "tempo_leitura_min": ["tempo de leitura"],
    "questoes_tentativas": ["questoes respondidas"],
    "questoes_acertos": ["questoes aprovadas"],
}

_CAMPOS_TURMA = {"livros_unicos", "tempo_leitura_min",
                 "questoes_tentativas", "questoes_acertos", "nivel"}


class PerfilElefanteTurma:
    plataforma = "elefante"
    formato = "resumo"
    estrategia = "perfil_elefante_turma"

    def detecta(self, compacto: str, nome_arquivo: str = "") -> bool:
        return ("performancedaturma" in compacto
                or "performancedaturma" in compactar(nome_arquivo)
                or ("habitodeleitura" in compacto and "nomedoestudante" in compacto))

    def analisar(self, paginas: list[Pagina], nome_arquivo: str = "") -> Analise:
        registros = _tabela_posicional(
            paginas, COLUNAS_PERFIL_TURMA, com_nome=True,
            aceitar_cabecalho=lambda campos: "nome" in campos
            and len(campos & _CAMPOS_TURMA) >= 3,
            inicia_registro=lambda presentes: "nome" in presentes
            and len(presentes) >= 4,
        )
        turma = _turma_da_capa(paginas)
        analise = Analise(plataforma=self.plataforma, formato=self.formato,
                          estrategia=self.estrategia, turma_detectada=turma,
                          mensagem_deteccao="Este arquivo pertence ao Elefante "
                          "Letrado — relatório de performance da turma"
                          + (f" ({turma})" if turma else "") + ".")
        for numero, registro in enumerate(registros, start=1):
            item = LinhaImportacao(numero=numero, nome=registro.texto("nome"),
                                   dados={})
            if turma:
                item.dados["turma_relatorio"] = turma
            _atribuir(item, "nivel", registro.texto("nivel"),
                      lambda b: _codigo_nivel(b))
            _atribuir(item, "livros_unicos", registro.texto("livros_unicos"), _inteiro)
            _atribuir(item, "tempo_leitura_min",
                      registro.texto("tempo_leitura_min"), duracao_em_minutos)
            _atribuir(item, "questoes_tentativas",
                      registro.texto("questoes_tentativas"), _inteiro)
            _atribuir(item, "questoes_acertos",
                      registro.texto("questoes_acertos"), _inteiro)
            analise.linhas.append(_fechar_linha(item))
        return analise


def _codigo_nivel(bruto: str) -> str:
    """Código de nível do Elefante lido do PDF, no vocabulário OFICIAL —
    AA…Z mais os tiers ``Z+`` e ``A+`` (o catálogo tem 24 livros neles). O ``+``
    pode vir como token separado na coluna ("Z +"), por isso o espaço interno é
    removido antes de validar. Fora do vocabulário → ValueError, que ``_atribuir``
    transforma em aviso (o campo fica ausente, a linha não cai)."""
    codigo = re.sub(r"\s+", "", bruto).upper()
    if codigo not in NIVEIS_OFICIAIS:
        raise ValueError(f"nível ilegível: {bruto!r}")
    return codigo


def _turma_da_capa(paginas: list[Pagina]) -> str:
    """Nome da turma na capa: linha logo após a do intervalo de datas."""
    if not paginas:
        return ""
    linhas = _linhas_visuais(paginas[0].palavras)
    for indice, linha in enumerate(linhas[:6]):
        if re.search(r"\d{2}/\d{2}/\d{4}", linha.texto) and indice + 1 < len(linhas):
            turma = linhas[indice + 1].texto.strip()
            if 0 < len(turma) <= 60:
                return turma
    return ""


# --------------------------------------------------------------------------
# Perfil 2 — Elefante Letrado · relatório individual do ESTUDANTE
# --------------------------------------------------------------------------

COLUNAS_PERFIL_ESTUDANTE = {
    "livro": ["titulo do livro", "titulo"],
    "nivel": ["nivel"],
    "genero": ["genero textual"],
    "tempo": ["tempo de leitura"],
    "data": ["data/hora", "data hora", "data"],
}

# Rótulos de seção do cabeçalho — nunca são nome do aluno nem turma.
_ROTULOS_SECAO = ("habitodeleitura", "leiturasconcluidas", "tempodeleitura",
                  "historicodelivroslidos", "compreensaoleitora",
                  "livrosescutados", "tempodeescuta")

# Prefixos de legenda/decoração que NUNCA são nome de aluno (imagens, logos...).
_PREFIXOS_LIXO = ("imagem", "figura", "foto", "logotipo", "logo", "marca",
                  "icone", "banner", "grafico", "captura", "screenshot")

# Nome do aluno no NOME DO ARQUIVO — fonte preferencial, pois o Elefante
# exporta "Relatório de performance do estudante - NOME DO ALUNO.pdf".
_RE_NOME_ARQUIVO = re.compile(
    r"(?:performance|desempenho)\s+d[oe]\s+(?:estudante|aluno)\s*[-–—:]\s*(.+)$",
    re.IGNORECASE,
)


def _parece_nome_pessoa(nome: str) -> bool:
    """≥2 palavras, essencialmente alfabético e sem cara de legenda/rótulo."""
    limpo = (nome or "").strip()
    if len(limpo) < 3 or len(limpo) > 80 or len(limpo.split()) < 2:
        return False
    plano = compactar(limpo)
    # Rejeita legenda de imagem/logo pelo PRIMEIRO TOKEN isolado ("Imagem de…",
    # "Figura 1…") — comparar a string inteira colada descartaria nomes reais
    # cujo início por acaso coincide com um prefixo ("Marcela", "Figueiredo").
    if compactar(limpo.split()[0]) in _PREFIXOS_LIXO:
        return False
    if any(r in plano for r in _ROTULOS_SECAO):
        return False
    alfabeticas = sum(1 for c in limpo if c.isalpha() or c in " '-.")
    return alfabeticas / max(1, len(limpo)) >= 0.85


def nome_do_arquivo(nome_arquivo: str) -> str | None:
    """Extrai o nome do aluno do NOME DO ARQUIVO (tudo após '... estudante -').

    Tolera acentos e variações no rótulo (só casa a partir de 'performance',
    que não tem acento). Devolve None se o arquivo não segue o padrão."""
    if not nome_arquivo:
        return None
    base = re.sub(r"\.(pdf|txt|csv|tsv)$", "", nome_arquivo.strip(), flags=re.IGNORECASE)
    casado = _RE_NOME_ARQUIVO.search(base)
    if not casado:
        return None
    nome = re.sub(r"\s+", " ", casado.group(1)).strip(" -–—_")
    # Remove o sufixo "(1)", "(2)"… que o navegador acrescenta ao baixar cópias
    # do mesmo relatório — senão o casamento exato de nome falharia.
    nome = re.sub(r"\s*\(\d+\)\s*$", "", nome).strip()
    return nome if _parece_nome_pessoa(nome) else None


class PerfilElefanteEstudante:
    plataforma = "elefante"
    formato = "leituras"
    estrategia = "perfil_elefante_estudante"

    def detecta(self, compacto: str, nome_arquivo: str = "") -> bool:
        # O nome do arquivo também identifica o relatório individual — cobre
        # PDFs cujo conteúdo veio ruim (escaneado/imagem).
        return ("performancedoestudante" in compacto
                or "historicodelivroslidos" in compacto
                or "performancedoestudante" in compactar(nome_arquivo)
                or "desempenhodoestudante" in compactar(nome_arquivo))

    def analisar(self, paginas: list[Pagina], nome_arquivo: str = "") -> Analise | None:
        cabecalho = self._cabecalho(paginas)
        # PRIORIDADE 1: nome do arquivo (fonte oficial e confiável do Elefante).
        # PRIORIDADE 2: conteúdo do PDF. PRIORIDADE 3: seleção manual.
        nome_arq = nome_do_arquivo(nome_arquivo)
        nome_conteudo = cabecalho.get("nome")
        if nome_arq:
            nome_aluno, origem = nome_arq, "arquivo"
        elif nome_conteudo:
            nome_aluno, origem = nome_conteudo, "conteudo"
        else:
            nome_aluno, origem = "", "nenhum"

        registros = _tabela_posicional(
            paginas, COLUNAS_PERFIL_ESTUDANTE, com_nome=False,
            aceitar_cabecalho=lambda campos: {"livro", "tempo", "data"} <= campos,
            inicia_registro=lambda presentes: any(
                _RE_RELOGIO.match(p.texto) for p in presentes.get("tempo", [])
            ) and any(
                _RE_DATA.match(p.texto) for p in presentes.get("data", [])),
        )

        # Sem nome confiável E sem histórico: deixa o genérico/manual decidir.
        if not nome_aluno and not registros:
            return None
        nome_linha = nome_aluno or "Aluno não identificado"

        resumo = self._resumo(paginas)
        turma = cabecalho.get("turma", "")
        por_metodo = {"arquivo": "pelo nome do arquivo",
                      "conteudo": "pelo conteúdo do PDF"}.get(origem)
        analise = Analise(
            plataforma=self.plataforma, formato=self.formato,
            estrategia=self.estrategia,
            turma_detectada=turma,
            escola_detectada=cabecalho.get("escola", ""),
            professor_detectado=cabecalho.get("professor", ""),
            origem_nome=origem,
            mensagem_deteccao="Este arquivo pertence ao Elefante Letrado — "
            + (f"relatório individual de {nome_aluno} (identificado {por_metodo})"
               if nome_aluno else "relatório individual (aluno não identificado "
               "automaticamente — selecione manualmente)")
            + (f", turma {turma}" if turma else "")
            + (f" · {resumo['leituras']} leituras concluídas na plataforma"
               if "leituras" in resumo else "") + ".")

        # O nome do arquivo tem prioridade, mas se DIVERGIR do nome no conteúdo
        # do PDF é sinal de arquivo renomeado/trocado — avisa para o usuário
        # conferir antes de importar (não muda a prioridade, só sinaliza).
        if origem == "arquivo" and nome_conteudo and _similaridade(
                normalizar_nome(nome_arq), normalizar_nome(nome_conteudo)) < 0.85:
            analise.erros_gerais.append(
                f"Atenção: o nome do arquivo (“{nome_arq}”) difere do nome no "
                f"conteúdo do PDF (“{nome_conteudo}”). Confirme se o relatório é "
                "do aluno certo antes de importar.")

        for numero, registro in enumerate(registros, start=1):
            item = LinhaImportacao(numero=numero, nome=nome_linha, dados={})
            if turma:
                item.dados["turma_relatorio"] = turma
            titulo = registro.texto("livro")
            if titulo:
                item.dados["livro"] = titulo
            _atribuir(item, "nivel", registro.texto("nivel"), _codigo_nivel)
            genero = registro.texto("genero")
            if genero:
                item.dados["genero"] = genero.strip(" ,")
            # A coluna Data/Hora traz a DATA na 1ª linha e o HORÁRIO na 2ª —
            # captura os dois para preservar o momento exato da leitura.
            tokens_data = [p.texto for p in registro.campos.get("data", [])]
            datas = [t for t in tokens_data if _RE_DATA.match(t)]
            horas = [t for t in tokens_data if _RE_RELOGIO.match(t)]
            if datas:
                _atribuir(item, "data", (datas[0], horas[0] if horas else None),
                          _data_hora_iso)
            _atribuir(item, "tempo_livro_min", registro.texto("tempo"),
                      duracao_em_minutos)
            analise.linhas.append(_fechar_linha(item))

        # Tempo total de leitura do resumo: complementa alunos que ainda não
        # têm snapshot vindo do relatório da turma (nunca o sobrescreve).
        if analise.linhas and "tempo_leitura_min" in resumo:
            analise.linhas[0].dados["tempo_leitura_min"] = resumo["tempo_leitura_min"]
        return analise

    def _cabecalho(self, paginas: list[Pagina]) -> dict:
        """Nome, turma, escola e professor do cabeçalho do relatório individual.

        Layout (posicional): abaixo do título vem o NOME; depois a linha
        "TURMA - ESCOLA"; e o bloco Professor|Escola|Turma em colunas
        (Turma alinhada à direita, x0 alto)."""
        info: dict = {}
        if not paginas:
            return info
        linhas = _linhas_visuais(paginas[0].palavras)
        apos_titulo = False
        for linha in linhas[:10]:
            texto = linha.texto.strip()
            compacto = compactar(texto)
            if "performancedoestudante" in compacto:
                apos_titulo = True
                continue
            if not apos_titulo or not texto:
                continue
            if re.search(r"\d{2}/\d{2}/\d{4}", texto):
                continue  # linha do intervalo de datas — ignorar
            # Rótulos de seção nunca são nome nem turma.
            if any(r in compacto for r in _ROTULOS_SECAO):
                continue
            # NOME do aluno vem PRIMEIRO no layout (topo mais alto) — capturado
            # antes da regra de turma para não confundir nomes com hífen
            # ("Ana - Maria") com "TURMA - ESCOLA". Legendas de imagem
            # ("Imagem de..."), logos e rótulos são recusados.
            if "nome" not in info and not re.search(r"\d", texto) \
                    and _parece_nome_pessoa(texto):
                info["nome"] = texto
                continue
            # Linha "TURMA - ESCOLA": SÓ depois do nome e SÓ se começar por
            # dígito (a série). rpartition separa a escola (último segmento),
            # preservando turmas cujo nome contenha " - ".
            if "nome" in info and "turma" not in info and " - " in texto \
                    and re.match(r"^\s*\d", texto):
                turma, _, escola = texto.rpartition(" - ")
                if turma.strip() and len(turma) <= 60:
                    info["turma"] = turma.strip()
                    if escola.strip():
                        info["escola"] = escola.strip()
                continue
        # Professor: coluna à esquerda do bloco "Professor | Escola | Turma".
        info["professor"] = self._professor(linhas)
        # Reforço da turma pela coluna "Turma" (x0 alto) se a linha falhou.
        if not info.get("turma"):
            info["turma"] = self._turma_por_coluna(linhas)
        return info

    def _professor(self, linhas: list[LinhaVisual]) -> str:
        for indice, linha in enumerate(linhas[:12]):
            if compactar(linha.texto).startswith("professor"):
                nomes = []
                for prox in linhas[indice + 1:indice + 4]:
                    trecho = " ".join(
                        p.texto for p in sorted(prox.palavras, key=lambda p: p.x0)
                        if p.x0 < 200)
                    if trecho.strip():
                        nomes.append(trecho.strip())
                return " ".join(nomes).strip(" ,")[:200]
        return ""

    def _turma_por_coluna(self, linhas: list[LinhaVisual]) -> str:
        for indice, linha in enumerate(linhas[:12]):
            rotulo = next((p for p in linha.palavras
                           if compactar(p.texto) == "turma"), None)
            if rotulo is None:
                continue
            for prox in linhas[indice + 1:indice + 3]:
                trecho = " ".join(
                    p.texto for p in sorted(prox.palavras, key=lambda p: p.x0)
                    if p.x0 >= rotulo.x0 - 8)
                if trecho.strip():
                    return trecho.strip()
        return ""

    def _resumo(self, paginas: list[Pagina]) -> dict:
        """Valores do bloco "Hábito de Leitura" (rótulo em cima, valor embaixo)."""
        resumo: dict = {}
        if not paginas:
            return resumo
        linhas = _linhas_visuais(paginas[0].palavras)
        for indice, linha in enumerate(linhas):
            for alvo, chave, conversor in (
                ("leiturasconcluidas", "leituras", _inteiro),
                ("tempodeleitura", "tempo_leitura_min", duracao_em_minutos),
            ):
                if chave in resumo:
                    continue
                x0 = _x0_do_rotulo(linha, alvo)
                if x0 is None:
                    continue
                for proxima in linhas[indice + 1:indice + 3]:
                    for palavra in proxima.palavras:
                        if abs(palavra.x0 - x0) <= 15.0:
                            try:
                                resumo[chave] = conversor(palavra.texto)
                            except (ValueError, TypeError):
                                pass
                            break
                    if chave in resumo:
                        break
        return resumo


def _x0_do_rotulo(linha: LinhaVisual, alvo_compacto: str) -> float | None:
    """x0 da sequência de palavras cujo texto compactado forma o rótulo."""
    palavras = sorted(linha.palavras, key=lambda p: p.x0)
    for inicio in range(len(palavras)):
        acumulado = ""
        for palavra in palavras[inicio:]:
            acumulado += compactar(palavra.texto)
            if acumulado == alvo_compacto:
                return palavras[inicio].x0
            if len(acumulado) >= len(alvo_compacto):
                break
    return None


# --------------------------------------------------------------------------
# Perfil 3 — Matific · classificação de estrelas dos estudantes
# --------------------------------------------------------------------------

COLUNAS_PERFIL_MATIFIC = {
    "serie": ["serie"],
    "turma_relatorio": ["turma"],
    "atividades": ["atividades finalizadas", "atividades"],
    "pontuacao_media": ["pontuacao media"],
    "estrelas": ["estrelas"],
}

_RE_RODAPE_MATIFIC = re.compile(r"https?://|www\.|matific\.com", re.IGNORECASE)

# "Intervalo de datas 2026-03-01-2026-04-01" (leaderboard mensal/semanal).
# Tolerante: "datas"/"dados", datas ISO ou brasileiras, separador -, – ou "a".
_RE_INTERVALO_MATIFIC = re.compile(
    r"intervalo\s*de\s*(?:dat[ao]s?|dados)\s*:?\s*"
    r"(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})"
    r"\s*(?:[-–—]|ate|até|a)\s*"
    r"(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})",
    re.IGNORECASE,
)

# O campo também aceita PRESETS em vez de datas explícitas. Os semanais são
# resolvidos pela data de impressão do rodapé; os demais viram TOTAL acumulado
# (com aviso — para rankings por período, o certo é "Personalizar intervalo").
_RE_INTERVALO_PRESET = re.compile(
    r"intervalo\s*de\s*(?:dat[ao]s?|dados)\s*:?\s*([^\d\s][^\n]{2,60}?)\s*$",
    re.IGNORECASE,
)
_RE_DATA_IMPRESSAO = re.compile(r"([0-3]?\d)/([01]?\d)/(\d{4}),")


def _data_impressao(paginas: list[Pagina]):
    """Data em que o PDF foi impresso (rodapé "08/07/2026, 01:13 Matific")."""
    from datetime import date as _date
    for pagina in paginas:
        for linha in _linhas_visuais(pagina.palavras):
            casado = _RE_DATA_IMPRESSAO.search(linha.texto)
            if casado:
                dia, mes, ano = (int(g) for g in casado.groups())
                try:
                    return _date(ano, mes, dia)
                except ValueError:
                    continue
    return None


def _intervalo_matific(paginas: list[Pagina]) -> tuple[str, str, str]:
    """("AAAA-MM-DD", "AAAA-MM-DD", observação) do "Intervalo de datas".

    * Datas explícitas → o intervalo impresso (degenerado é descartado: a
      confirmação responderia 400 sem saída — melhor cair no acumulado).
    * "Esta semana"/"Última semana" → resolvidos pela data de impressão do
      rodapé (semana de segunda a domingo).
    * "Ano acadêmico ..."/"Olimpíadas ..." → sem período: os valores são
      tratados como TOTAL acumulado, com observação orientando o usuário.
    """
    if not paginas:
        return "", "", ""
    for linha in _linhas_visuais(paginas[0].palavras)[:12]:
        casado = _RE_INTERVALO_MATIFIC.search(linha.texto)
        if casado:
            try:
                inicio, fim = (
                    bruto if re.fullmatch(r"\d{4}-\d{2}-\d{2}", bruto)
                    else _data_iso(bruto)
                    for bruto in casado.groups()
                )
                if inicio < fim:
                    return inicio, fim, ""
            except ValueError:
                pass
            # Datas presentes mas ilegíveis/degeneradas: NUNCA em silêncio —
            # sem período, a confirmação SUBSTITUI o acumulado.
            return "", "", ("O intervalo de datas do relatório não pôde ser "
                            "lido — os valores serão tratados como TOTAL "
                            "acumulado. Para rankings por semana/mês, exporte "
                            "com “Personalizar intervalo”.")
        preset = _RE_INTERVALO_PRESET.search(linha.texto.strip())
        if not preset:
            continue
        rotulo = preset.group(1).strip(" .:-–—")
        plano = compactar(rotulo)
        if plano in ("estasemana", "ultimasemana"):
            impressao = _data_impressao(paginas)
            if impressao is None:
                return "", "", (f"O intervalo de datas está como “{rotulo}”, mas "
                                "não encontrei a data de impressão no rodapé — os "
                                "valores serão tratados como total acumulado.")
            # A semana do Matific começa no DOMINGO (help.br.matific.com:
            # "Esta semana cobre do último domingo até hoje").
            domingo = impressao - timedelta(days=(impressao.weekday() + 1) % 7)
            if plano == "ultimasemana":
                inicio_d, fim_d = domingo - timedelta(days=7), domingo
            else:
                inicio_d, fim_d = domingo, impressao + timedelta(days=1)
            return (inicio_d.isoformat(), fim_d.isoformat(),
                    f"“{rotulo}” resolvido pela data de impressão do relatório.")
        if plano:
            return "", "", (f"O intervalo de datas está como “{rotulo}” — os "
                            "valores serão tratados como TOTAL acumulado. Para "
                            "rankings por semana/mês, exporte o relatório com "
                            "“Personalizar intervalo”.")
    return "", "", ""


def _data_br(iso: str) -> str:
    ano, mes, dia = iso.split("-")
    return f"{dia}/{mes}/{ano}"


class PerfilMatific:
    plataforma = "matific"
    formato = "resumo"
    estrategia = "perfil_matific"

    def detecta(self, compacto: str, nome_arquivo: str = "") -> bool:
        return ("matific" in compacto
                or "matific" in compactar(nome_arquivo)
                or ("atividadesfinalizadas" in compacto and "estrelas" in compacto))

    def analisar(self, paginas: list[Pagina], nome_arquivo: str = "") -> Analise:
        # O botão lateral "Opinião" é desenhado de lado ("oãinipO") e pousa
        # na MESMA linha visual de registros reais — remove-se por palavra.
        paginas = [
            Pagina(numero=pagina.numero, palavras=[
                p for p in pagina.palavras
                if compactar(p.texto)[::-1] != "opiniao"
            ])
            for pagina in paginas
        ]

        def ignorar(linha: LinhaVisual) -> bool:
            texto = linha.texto
            if _RE_RODAPE_MATIFIC.search(texto):
                return True
            # Rodapé "06/07/2026, 16:10 Matific"
            return re.search(r"\d{2}/\d{2}/\d{4},", texto) is not None

        def inicia(presentes: dict[str, list[Palavra]]) -> bool:
            # Conta colunas de métrica PREENCHIDAS — número OU traço ("-"/"—").
            # O aluno inativo pode vir "- - -": ainda é um aluno (nome + Série),
            # e a linha deve sobreviver com avisos, nunca sumir (§51).
            preenchidas = sum(
                1 for campo in ("atividades", "pontuacao_media", "estrelas")
                if any(re.fullmatch(r"[\d.,]+|[-–—]", p.texto)
                       for p in presentes.get(campo, [])))
            if "nome" in presentes:
                return preenchidas >= 2
            # Nome comprido quebra INTEIRO nas linhas vizinhas ("CHRISTOPHER"
            # acima, "D" abaixo) e a linha do registro fica só com números:
            # série + as 3 métricas bastam — o nome chega pela costura de
            # órfãs. Sem isto o aluno sumia do relatório.
            return preenchidas >= 3 and "serie" in presentes

        registros = _tabela_posicional(
            paginas, COLUNAS_PERFIL_MATIFIC, com_nome=True,
            aceitar_cabecalho=lambda campos: "nome" in campos
            and {"atividades", "estrelas"} <= campos and len(campos) >= 4,
            inicia_registro=inicia,
            ignorar_linha=ignorar,
            anexo_por_proximidade=True,  # a turma vem fatiada acima E abaixo
        )
        # O "Intervalo de datas" da capa define A QUE PERÍODO os números
        # pertencem: a confirmação soma ao acumulado e data o snapshot no fim
        # do intervalo — rankings e premiações do mês certo, mesmo importando
        # o relatório semanas depois.
        inicio, fim, observacao = _intervalo_matific(paginas)
        analise = Analise(plataforma=self.plataforma, formato=self.formato,
                          estrategia=self.estrategia,
                          periodo_inicio=inicio, periodo_fim=fim,
                          mensagem_deteccao="Este arquivo pertence ao Matific — "
                          "classificação de estrelas dos estudantes"
                          + (f", com dados do período de {_data_br(inicio)} a "
                             f"{_data_br(fim)}" if inicio else "")
                          + "." + (f" {observacao}" if observacao else ""))
        for numero, registro in enumerate(registros, start=1):
            item = LinhaImportacao(numero=numero, nome=registro.texto("nome"),
                                   dados={})
            _atribuir(item, "atividades", registro.texto("atividades"), _inteiro)
            _atribuir(item, "pontuacao_media",
                      registro.texto("pontuacao_media"), _numero_plausivel)
            _atribuir(item, "estrelas", registro.texto("estrelas"), _inteiro)
            serie = registro.texto("serie")
            if serie:
                item.dados["serie"] = serie
            turma = re.sub(r"\s*\(\d+\)\s*$", "", registro.texto("turma_relatorio"))
            if turma:
                item.dados["turma_relatorio"] = turma
            analise.linhas.append(_fechar_linha(item))
        return analise


# --------------------------------------------------------------------------
# Orquestração: perfis primeiro, estratégias genéricas como rede de segurança
# --------------------------------------------------------------------------

PERFIS = (PerfilElefanteEstudante(), PerfilElefanteTurma(), PerfilMatific())


def analisar_pdf(conteudo: bytes, plataforma: str | None = None,
                 nome_arquivo: str = "") -> Analise:
    """Analisa um PDF: detecta o perfil real e reconstrói a tabela por
    posição; sem perfil compatível, cai nas estratégias genéricas de texto.

    `nome_arquivo` é a fonte PREFERENCIAL do nome do aluno no relatório
    individual do Elefante ("... estudante - NOME.pdf").

    PDF inflado (bomba de descompressão) é recusado ANTES de qualquer leitor
    abri-lo; com páginas demais, logo depois de aberto e antes de qualquer página
    ser lida (``PdfRecusado``, fora do "melhor esforço" abaixo: a recusa chega a
    quem chamou, nunca cai no leitor genérico). A garantia, porém, é o orçamento
    da análise: tudo o que o pdfplumber e o leitor genérico descompactam ou montam
    aqui dentro gasta dele, e estourá-lo recusa o arquivo — mesmo que o medidor
    prévio não tenha enxergado o fluxo, e mesmo que um leitor engula a exceção. O
    orçamento tem também um prazo (``PDF_MAX_SEGUNDOS``) para a análise inteira.
    """
    from app.services import importacao as generico

    with _orcamento_da_analise() as orcamento:
        exigir_pdf_contido(conteudo)
        try:
            paginas = extrair_paginas(conteudo)
        except PdfRecusado:
            raise   # recusa: nunca "melhor esforço" no leitor genérico
        except Exception:  # noqa: BLE001 — pdfplumber é melhor esforço
            paginas = []
        orcamento.conferir()   # a recusa que o pdfplumber engoliu também vale

        compacto = ""
        if paginas:
            compacto = compactar(" ".join(
                p.texto for pagina in paginas for p in pagina.palavras))
        for perfil in PERFIS:
            if plataforma and perfil.plataforma != plataforma:
                continue
            if not perfil.detecta(compacto, nome_arquivo):
                continue
            try:
                analise = perfil.analisar(paginas, nome_arquivo)
            except Exception:  # noqa: BLE001 — layout inesperado: usa o genérico
                analise = None
            if analise is not None and analise.linhas:
                return analise

        # Leitor genérico: teto próprio do descompactado (nunca acima do geral) e o
        # texto contado página a página (``_texto_pypdf_com_teto``).
        orcamento.novo_leitor(min(PDF_MAX_DESCOMPRIMIDO_GENERICO, PDF_MAX_DESCOMPRIMIDO))
        texto = generico.extrair_texto_pdf(conteudo)
        # O prazo vale também para a análise do texto, que não tem contas por dentro:
        # sem tempo, ela nem começa; e a que passar do prazo também é recusada (a regra
        # é a mesma para qualquer etapa em que o tempo for gasto).
        orcamento.conferir()
        analise = generico.analisar_texto(texto, plataforma)
        orcamento.conferir()
    return analise
