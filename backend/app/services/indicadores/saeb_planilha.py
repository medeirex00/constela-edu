"""Parser ``inep_saeb_planilha``: as planilhas de resultados do SAEB por Brasil,
estados e municípios (2019, 2021, 2025 e a de 2021 com a taxa de alfabetização) —
etapa E7 dos indicadores oficiais.

Função PURA (linhas das abas → leitura canônica + avisos, sem banco nem rede), nos DOIS
caminhos com o MESMO código: nesta máquina, pela linha de comando ``preparar``, sobre a
planilha inteira (a de 2025 tem ~24 MB e ~150 MB de XML; lida em STREAMING, openpyxl
``read_only``); no servidor, sobre o PACOTE recortado (``pacote_saeb``: o cabeçalho
técnico de cada aba + só as linhas do território, em CSV). A produção nunca abre a
planilha do INEP.

LAYOUT REAL (conferido nas planilhas de 2019, 2021 e 2025):

* abas reconhecidas PELO CONTEÚDO, nunca pela posição nem pelo nome: a linha de
  cabeçalho técnico (``DEPENDENCIA_ADM``, ``LOCALIZACAO`` e ao menos uma medida
  ``MEDIA_*``/``NIVEL_*``/``TX_ALFABETIZADO``) diz que a aba é de dados, e a
  identificação diz de quê — ``CO_MUNICIPIO`` (municípios), ``CO_UF`` (estados) ou
  ``ID`` (Brasil). A de 2025 começa por uma aba "Dicionário" (variável × descrição):
  sem esse cabeçalho, é IGNORADA (listada no aviso), esteja onde estiver;
* caixa variável nos nomes (``MEDIA_5_LP`` × ``nivel_0_LP5``): comparados normalizados;
* 2021 traz, logo abaixo do cabeçalho técnico, uma linha de RÓTULOS legíveis ("Edição do
  Saeb", "Código do Município"...): não é dado (o código não é código) e é pulada;
* edição: a coluna ``ANO_SAEB`` (2021 e 2025) ou, sem ela (2019), o ano no NOME do
  arquivo — ou a informada por quem prepara (``--edicao``); divergência = recusa;
* ``DEPENDENCIA_ADM`` por extenso: "Municipal", "Estadual", "Total - Federal, Estadual
  e Municipal" (= rede PÚBLICA), "Total - Federal, Estadual, Municipal e Privada" (=
  TOTAL); "Federal", "Privada" e "Total - Estadual e Municipal" ficam de fora (aviso);
* ``LOCALIZACAO`` Total/Urbana/Rural — gravadas SEPARADAS (``localizacao``); a CAPA é a
  Total. ``CAPITAL`` (Total/Capital/Interior, em Brasil e estados): só a Total;
* médias (``MEDIA_5_LP``/``MT``; ``MEDIA_2_LP``/``MT`` no 2º ano) e a distribuição por
  nível (``nivel_k_LP5``/``MT5``: LP 0–9, MT 0–10; ``nivel_k_LP2``/``MT2``: 0–8 — a
  régua de ``escalas.NIVEIS_SAEB``), em PERCENTUAL (soma ≈ 100) — uma planilha em
  FRAÇÃO (soma ≈ 1) é convertida para percentual (×100, com aviso); misturadas, recusa;
* ``TX_ALFABETIZADO`` (só a planilha de 2021 "c_tx_alfabetizado", Brasil e estados): a
  taxa de alfabetização do Saeb do 2º ano — CONTEXTO AMOSTRAL, gravada como
  ``tx_alfabetizado`` (nunca como o ICA, ``percentual_alfabetizado``). Um "0" sem
  nenhuma média na linha não é taxa medida: vira ausência;
* célula vazia, "-" ou "ND" = AUSÊNCIA ``nao_divulgado`` (nunca zero); o 9º ano e o
  ensino médio não são lidos.

RECORTE (pelo CÓDIGO): o MUNICÍPIO da rede (``CO_MUNICIPIO`` = IBGE) só na dependência
MUNICIPAL (as demais ficam registradas no aviso); a UF da rede (os 2 primeiros dígitos
do IBGE) e o Brasil nas redes municipal, estadual, pública e total. O 2º ANO (amostral)
só de UF e Brasil: numa aba de municípios ele não é lido; nada do 2º ano é gravado por
município ou por escola.

ONDE VAI: ``indicadores_referencia``, avaliação ``saeb``: ``proficiencia`` (média),
``pct_nivel`` (``nivel`` = k) e ``tx_alfabetizado``; etapa ``5_ano``/``2_ano``,
componente ``lp``/``mt``; desenho ``censitario`` no 5º ano das redes públicas (a TOTAL
inclui a privada, amostral: sem marca) e ``amostral`` no 2º ano. O Saeb 2023 (RAR/XLSB)
continua ADIADO (plano, E7).
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Callable, Iterable, Iterator, Sequence

from app.services.avaliacoes import ImportacaoRecusada
from app.services.indicadores import escalas, ideb, ideb_territorio, seduc
from app.services.indicadores.ica import CODIGO_BRASIL, LinhaCanonica

PARSER = "inep_saeb_planilha"
VERSAO_PARSER = "1"
AVALIACAO = "saeb"
IND_PROFICIENCIA = "proficiencia"
IND_PCT_NIVEL = "pct_nivel"
IND_TX_ALFABETIZADO = "tx_alfabetizado"      # Saeb 2º ano, amostral — NÃO é o ICA
MOTIVO = "nao_divulgado"

ABA_MUNICIPIO, ABA_UF, ABA_BRASIL = "municipio", "uf", "brasil"
TIPOS = (ABA_BRASIL, ABA_UF, ABA_MUNICIPIO)
REDES = {"MUNICIPAL": "municipal", "ESTADUAL": "estadual",
         "TOTAL - FEDERAL, ESTADUAL E MUNICIPAL": "publica",
         "TOTAL - FEDERAL, ESTADUAL, MUNICIPAL E PRIVADA": "total"}
REDES_IGNORADAS = ("FEDERAL", "PRIVADA", "TOTAL - ESTADUAL E MUNICIPAL")
LOCALIZACOES = {"TOTAL": "total", "URBANA": "urbana", "RURAL": "rural"}
CAPITAIS = ("TOTAL", "CAPITAL", "INTERIOR")
COMPONENTES = {"LP": "lp", "MT": "mt"}
ETAPAS = {"5": "5_ano", "2": "2_ano"}
UNIDADE_MEDIA = {"5_ano": escalas.ESCALA_SAEB, "2_ano": escalas.ESCALA_ALFABETIZACAO}
FAIXA_MEDIA = {"5_ano": 500.0, "2_ano": 1000.0}

_IDENTIFICACAO = ("ANO_SAEB", "ID", "CO_UF", "NO_UF", "CO_MUNICIPIO", "NO_MUNICIPIO",
                  "DEPENDENCIA_ADM", "LOCALIZACAO", "CAPITAL")
_RE_MEDIA = re.compile(r"^MEDIA_(2|5)_(LP|MT)$")
_RE_NIVEL = re.compile(r"^NIVEL_(\d{1,2})_(LP|MT)(2|5)$")
_TX = "TX_ALFABETIZADO"
_RE_MEDIDA = re.compile(r"^(?:MEDIA_|NIVEL_\d)")
_LINHAS_CABECALHO = 5
_TOLERANCIA_PERCENTUAL = 1.5          # soma dos níveis (arredondados a 2 casas) ≈ 100
_TOLERANCIA_FRACAO = 0.015

ARQUIVO = ('a planilha oficial do INEP de resultados do Saeb por Brasil, estados e '
           'municípios (saeb_AAAA_brasil_estados_municipios*.xlsx)')


def _recusa(texto: str) -> ImportacaoRecusada:
    return ImportacaoRecusada(f"{texto} Confira se é {ARQUIVO}. Nada foi gravado.")


def _rotulo_etapa(etapa: str) -> str:
    """"5_ano" → "5º ano"."""
    return etapa.replace("_ano", "º ano")


def _cel(linha: Sequence, j: int | None):
    return linha[j] if j is not None and 0 <= j < len(linha) else None


# --- Estruturas ---------------------------------------------------------------

@dataclass(frozen=True)
class ColunaSaeb:
    nome: str            # como no arquivo
    indice: int
    indicador: str       # proficiencia | pct_nivel | tx_alfabetizado
    etapa: str           # 5_ano | 2_ano
    componente: str      # lp | mt
    nivel: str = ""


@dataclass(frozen=True)
class LinhaSaeb:
    """Uma linha do território, já lida (texto → número ou marcador)."""

    dependencia: str            # normalizada (sem acento, maiúscula)
    rotulo_dependencia: str     # como no arquivo
    rede: str | None            # municipal | estadual | publica | total | None (ignorada)
    localizacao: str
    capital: str                # TOTAL | CAPITAL | INTERIOR | "" (sem a coluna)
    nome: str                   # do território, como no arquivo
    celulas: dict               # nome da coluna → ideb.Celula


@dataclass
class LeituraAba:
    """Uma aba de dados (o recorte do território)."""

    tipo: str                     # brasil | uf | municipio
    aba: str
    alvo: str
    cabecalho: list[str]
    colunas: list[ColunaSaeb]
    recorte: list[list[str]] = field(default_factory=list)
    linhas: list[LinhaSaeb] = field(default_factory=list)
    linhas_lidas: int = 0
    rotulos: int = 0
    anos: set = field(default_factory=set)
    ignoradas: list[str] = field(default_factory=list)
    segundo_ano_ignorado: list[str] = field(default_factory=list)


@dataclass
class LeituraSaeb:
    """O que o parser entendeu do arquivo (nada gravado)."""

    parser: str
    edicao_arquivo: int
    origem_edicao: str                     # coluna | nome | informada
    abas: list[LeituraAba]
    abas_ignoradas: list[str] = field(default_factory=list)
    escala_niveis: str | None = None       # percentual | fracao | None (sem níveis)
    escala_tx: str | None = None
    casas: dict = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)

    @property
    def linhas_lidas(self) -> int:
        return sum(a.linhas_lidas for a in self.abas)


# --- Cabeçalho ------------------------------------------------------------------

def normalizar(nome) -> str:
    return seduc.normalizar_coluna(ideb_territorio.texto_limpo(nome))


def tipo_do_cabecalho(nomes: list[str]) -> str | None:
    """O tipo da aba pela linha de cabeçalho técnico (já normalizada), ou None quando
    não é cabeçalho de dados (a aba "Dicionário", por exemplo)."""
    conjunto = set(nomes)
    if not {"DEPENDENCIA_ADM", "LOCALIZACAO"} <= conjunto:
        return None
    if not any(_RE_MEDIDA.match(n) or n == _TX for n in conjunto):
        return None
    if "CO_MUNICIPIO" in conjunto:
        return ABA_MUNICIPIO
    if "CO_UF" in conjunto:
        return ABA_UF
    if "ID" in conjunto:
        return ABA_BRASIL
    raise _recusa("Uma aba tem as medidas do Saeb, mas não a identificação (CO_MUNICIPIO, "
                  "CO_UF ou ID).")


def _mapear(cabecalho: list[str], tipo: str) -> tuple[dict[str, int], list[ColunaSaeb],
                                                      list[str], list[str]]:
    nomes = [normalizar(c) for c in cabecalho]
    repetidas = sorted({n for n, k in Counter(n for n in nomes if n).items() if k > 1})
    if repetidas:
        raise _recusa(f"A coluna {', '.join(repetidas)} aparece mais de uma vez no cabeçalho.")
    ids = {n: j for j, n in enumerate(nomes) if n in _IDENTIFICACAO}
    colunas: list[ColunaSaeb] = []
    ignoradas: list[str] = []
    segundo_ano: list[str] = []
    for j, n in enumerate(nomes):
        if not n or n in ids:
            continue
        original = (cabecalho[j] or "").strip()
        media, nivel = _RE_MEDIA.match(n), _RE_NIVEL.match(n)
        if media:
            col = ColunaSaeb(original, j, IND_PROFICIENCIA, ETAPAS[media.group(1)],
                             COMPONENTES[media.group(2)])
        elif nivel:
            etapa, comp = ETAPAS[nivel.group(3)], COMPONENTES[nivel.group(2)]
            k = int(nivel.group(1))
            if k not in escalas.NIVEIS_SAEB[(etapa, comp)]:
                raise _recusa(f"A coluna {original} é de um nível fora da régua do Saeb "
                              f"({_rotulo_etapa(etapa)} {comp.upper()}: níveis "
                              f"{min(escalas.NIVEIS_SAEB[(etapa, comp)])} a "
                              f"{max(escalas.NIVEIS_SAEB[(etapa, comp)])}).")
            col = ColunaSaeb(original, j, IND_PCT_NIVEL, etapa, comp, str(k))
        elif n == _TX:
            col = ColunaSaeb(original, j, IND_TX_ALFABETIZADO, "2_ano", "lp")
        else:
            ignoradas.append(original)
            continue
        if col.etapa == "2_ano" and tipo == ABA_MUNICIPIO:
            segundo_ano.append(original)          # amostral: nunca por município
            continue
        colunas.append(col)
    exigidas = {ABA_MUNICIPIO: "CO_MUNICIPIO", ABA_UF: "CO_UF", ABA_BRASIL: "ID"}[tipo]
    if exigidas not in ids:
        raise _recusa(f"A aba não tem a coluna {exigidas}.")
    _conferir_niveis(colunas)
    return ids, colunas, ignoradas, segundo_ano


def _conferir_niveis(colunas: list[ColunaSaeb]) -> None:
    """Os níveis de um componente vêm completos (0 a n) ou não vêm."""
    por: dict[tuple[str, str], set[int]] = {}
    for c in colunas:
        if c.indicador == IND_PCT_NIVEL:
            por.setdefault((c.etapa, c.componente), set()).add(int(c.nivel))
    for (etapa, comp), niveis in por.items():
        esperados = set(escalas.NIVEIS_SAEB[(etapa, comp)])
        if niveis != esperados:
            faltam = sorted(esperados - niveis)
            raise _recusa(f"Os níveis do {_rotulo_etapa(etapa)} em {comp.upper()} estão "
                          f"incompletos (faltam {faltam}).")


def _achar_cabecalho(it: Iterator) -> tuple[list[str], str] | None:
    for i, bruta in enumerate(it):
        if i >= _LINHAS_CABECALHO:
            return None
        linha = [ideb_territorio.texto_limpo(c) for c in (bruta or ())]
        tipo = tipo_do_cabecalho([normalizar(c) for c in linha])
        if tipo:
            while linha and not linha[-1]:
                linha.pop()
            return linha, tipo
    return None


# --- Leitura de uma aba ----------------------------------------------------------

def _alvo(tipo: str, codigo_ibge: str) -> str:
    if tipo == ABA_MUNICIPIO:
        return codigo_ibge
    return codigo_ibge[:2] if tipo == ABA_UF else CODIGO_BRASIL


def _codigo_da_linha(tipo: str, bruta: Sequence, ids: dict[str, int]) -> str | None:
    """O código do território da linha (None = não é linha de dados: rótulo, rodapé)."""
    if tipo == ABA_MUNICIPIO:
        codigo = ideb._codigo(_cel(bruta, ids["CO_MUNICIPIO"]))
        return codigo if codigo is not None and len(codigo) == 7 else None
    if tipo == ABA_UF:
        codigo = ideb._codigo(_cel(bruta, ids["CO_UF"]))
        return codigo if codigo is not None and len(codigo) == 2 else None
    valor = ideb_territorio.texto_limpo(_cel(bruta, ids["ID"]))
    return CODIGO_BRASIL if ideb_territorio.chave_nome(valor) == "brasil" else None


def ler_aba(linhas: Iterable[Sequence], *, codigo_ibge: str, aba: str = "",
            progresso: Callable[[int], None] | None = None) -> LeituraAba | None:
    """Lê uma aba (valores do openpyxl ou o CSV do pacote) e recorta o território.
    None quando a aba não é de dados (sem o cabeçalho técnico nas primeiras linhas)."""
    it = iter(linhas)
    achado = _achar_cabecalho(it)
    if achado is None:
        return None
    cabecalho, tipo = achado
    ids, colunas, ignoradas, segundo_ano = _mapear(cabecalho, tipo)
    leitura = LeituraAba(tipo=tipo, aba=aba, alvo=_alvo(tipo, codigo_ibge),
                         cabecalho=cabecalho, colunas=colunas, ignoradas=ignoradas,
                         segundo_ano_ignorado=segundo_ano)
    nome_col = {ABA_MUNICIPIO: "NO_MUNICIPIO", ABA_UF: "NO_UF"}.get(tipo)
    for bruta in it:
        if not bruta or all(c is None or c == "" for c in bruta):
            continue
        codigo = _codigo_da_linha(tipo, bruta, ids)
        if codigo is None:
            leitura.rotulos += 1            # a linha de rótulos legíveis (2021) ou rodapé
            continue
        leitura.linhas_lidas += 1
        if progresso and leitura.linhas_lidas % 10_000 == 0:
            progresso(leitura.linhas_lidas)
        if "ANO_SAEB" in ids:
            ano = ideb._codigo(_cel(bruta, ids["ANO_SAEB"]))
            if ano is None or len(ano) != 4:
                raise _recusa(f"“{ideb_territorio.texto_limpo(_cel(bruta, ids['ANO_SAEB']))}” "
                              "em ANO_SAEB não é um ano.")
            leitura.anos.add(int(ano))
        if codigo != leitura.alvo:
            continue
        linha = [ideb_territorio.texto_limpo(c) for c in bruta]
        while linha and not linha[-1]:
            linha.pop()
        leitura.recorte.append(linha)
        leitura.linhas.append(_linha(linha, ids, colunas, tipo, nome_col))
    return leitura


def _linha(linha: list[str], ids: dict[str, int], colunas: list[ColunaSaeb], tipo: str,
           nome_col: str | None) -> LinhaSaeb:
    dependencia = seduc.normalizar_texto(_cel(linha, ids["DEPENDENCIA_ADM"]) or "")
    if dependencia not in REDES and dependencia not in REDES_IGNORADAS:
        raise _recusa(f"Dependência administrativa “{_cel(linha, ids['DEPENDENCIA_ADM'])}” "
                      "desconhecida (esperado Municipal, Estadual, Federal, Privada ou um dos "
                      "Totais do INEP).")
    localizacao = seduc.normalizar_texto(_cel(linha, ids["LOCALIZACAO"]) or "")
    if localizacao not in LOCALIZACOES:
        raise _recusa(f"Localização “{_cel(linha, ids['LOCALIZACAO'])}” desconhecida (esperado "
                      "Total, Urbana ou Rural).")
    capital = ""
    if "CAPITAL" in ids:
        capital = seduc.normalizar_texto(_cel(linha, ids["CAPITAL"]) or "")
        if capital not in CAPITAIS:
            raise _recusa(f"“{_cel(linha, ids['CAPITAL'])}” em CAPITAL desconhecido (esperado "
                          "Total, Capital ou Interior).")
    celulas = {}
    for col in colunas:
        bruto = _cel(linha, col.indice) or ""
        celula = ideb_territorio.ler_celula(bruto)
        if celula is None:
            raise _recusa(f"“{bruto}” em {col.nome} não é número nem marcador de ausência.")
        celulas[col.nome] = celula
    nome = (_cel(linha, ids[nome_col]) or "") if nome_col and nome_col in ids else ""
    return LinhaSaeb(dependencia=dependencia,
                     rotulo_dependencia=(_cel(linha, ids["DEPENDENCIA_ADM"]) or "").strip(),
                     rede=REDES.get(dependencia),
                     localizacao=LOCALIZACOES[localizacao], capital=capital,
                     nome=nome if tipo != ABA_BRASIL else "Brasil", celulas=celulas)


# --- Arquivo inteiro: edição, escala e validação -----------------------------------

def gravada(aba: LeituraAba, ln: LinhaSaeb) -> bool:
    """A linha entra no banco? Município: só a dependência MUNICIPAL; UF/Brasil: as
    quatro redes, e só a CAPITAL Total."""
    if ln.rede is None or (ln.capital and ln.capital != "TOTAL"):
        return False
    return ln.rede == "municipal" if aba.tipo == ABA_MUNICIPIO else True


def _edicao(abas: list[LeituraAba], nome: str, informada: int | None) -> tuple[int, str]:
    da_coluna = set().union(*(a.anos for a in abas)) if abas else set()
    if len(da_coluna) > 1:
        raise _recusa(f"A planilha mistura edições em ANO_SAEB ({', '.join(map(str, sorted(da_coluna)))}).")
    no_nome = {int(a) for a in re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", nome or "")}
    candidatos = []
    if da_coluna:
        candidatos.append(("coluna", next(iter(da_coluna))))
    if len(no_nome) == 1:
        candidatos.append(("nome", next(iter(no_nome))))
    if informada is not None:
        candidatos.append(("informada", int(informada)))
    if not candidatos:
        raise _recusa("Não achei a edição do Saeb: a planilha não tem ANO_SAEB e o nome do "
                      "arquivo não traz um ano só. Informe a edição (--edicao).")
    anos = {a for _, a in candidatos}
    if len(anos) > 1:
        raise _recusa("A edição diverge: " + ", ".join(f"{o} {a}" for o, a in candidatos) + ".")
    origem, ano = candidatos[0]
    if not 1990 <= ano <= 2100:
        raise _recusa(f"Edição {ano} fora do esperado.")
    return ano, origem


def _escala(grupos: list[list[float]], rotulo: str) -> str | None:
    """``percentual`` (soma ≈ 100) ou ``fracao`` (soma ≈ 1) — pelos grupos COMPLETOS
    (todas as faixas com número). Mistura ou soma fora das duas: recusa."""
    tipos = set()
    for valores in grupos:
        soma = sum(valores)
        if abs(soma - 100) <= _TOLERANCIA_PERCENTUAL:
            tipos.add("percentual")
        elif abs(soma - 1) <= _TOLERANCIA_FRACAO:
            tipos.add("fracao")
        else:
            raise _recusa(f"A soma dos {rotulo} de uma linha é {round(soma, 4)}: nem 100% "
                          "(percentual) nem 1 (fração) — as colunas não conferem.")
    if len(tipos) > 1:
        raise _recusa(f"A planilha mistura {rotulo} em percentual e em fração.")
    return next(iter(tipos)) if tipos else None


def _percentual(celula: ideb.Celula, escala: str | None) -> tuple[float | None, int]:
    if celula.valor is None or escala != "fracao":
        return celula.valor, celula.casas
    return float(Decimal(repr(celula.valor)) * 100), max(celula.casas - 2, 0)


def consolidar(abas: list[LeituraAba], *, nome: str, edicao_informada: int | None = None,
               abas_ignoradas: list[str] | None = None) -> LeituraSaeb:
    """Junta as abas: a edição (coluna, nome ou informada), a escala dos níveis e da
    taxa (percentual × fração), as faixas e os avisos. LEVANTA ``ImportacaoRecusada``."""
    if not abas:
        raise _recusa("Nenhuma aba de dados (com DEPENDENCIA_ADM, LOCALIZACAO e as médias ou "
                      "os níveis do Saeb) na planilha.")
    tipos = Counter(a.tipo for a in abas)
    if any(n > 1 for n in tipos.values()):
        raise _recusa("A planilha tem mais de uma aba do mesmo nível (" + ", ".join(
            f"{t}: {', '.join(a.aba for a in abas if a.tipo == t)}" for t, n in tipos.items()
            if n > 1) + "); não dá para saber qual vale.")
    edicao, origem = _edicao(abas, nome, edicao_informada)
    grupos_nivel: list[list[float]] = []
    valores_tx: list[float] = []
    for aba in abas:
        for ln in aba.linhas:
            if not gravada(aba, ln):
                continue
            por: dict[tuple[str, str], list] = {}
            for col in aba.colunas:
                celula = ln.celulas[col.nome]
                if col.indicador == IND_PCT_NIVEL:
                    por.setdefault((col.etapa, col.componente), []).append(celula.valor)
                elif col.indicador == IND_TX_ALFABETIZADO and celula.valor is not None:
                    valores_tx.append(celula.valor)
            grupos_nivel.extend(v for v in por.values() if v and all(x is not None for x in v))
    escala = _escala(grupos_nivel, "níveis")
    if escala is None and any(c.indicador == IND_PCT_NIVEL for a in abas for c in a.colunas):
        valores = [ln.celulas[c.nome].valor for a in abas for ln in a.linhas
                   for c in a.colunas if c.indicador == IND_PCT_NIVEL and gravada(a, ln)
                   and ln.celulas[c.nome].valor is not None]
        escala = ("fracao" if valores and max(valores) <= 1.0 else "percentual") if valores else None
    escala_tx = None
    if valores_tx:
        escala_tx = ("fracao" if max(valores_tx) <= 1.0
                     and any(not float(v).is_integer() for v in valores_tx) else "percentual")
    leitura = LeituraSaeb(parser=PARSER, edicao_arquivo=edicao, origem_edicao=origem,
                          abas=abas, abas_ignoradas=list(abas_ignoradas or []),
                          escala_niveis=escala, escala_tx=escala_tx)
    _validar(leitura)
    leitura.avisos = _avisos(leitura)
    return leitura


def _familia(col: ColunaSaeb) -> str:
    return f"{col.indicador}_{col.etapa}"


def _validar(leitura: LeituraSaeb) -> None:
    casas: dict[str, int] = {}
    for aba in leitura.abas:
        vistas: set[tuple] = set()
        for ln in aba.linhas:
            if not gravada(aba, ln):
                continue
            chave = (ln.rede, ln.localizacao)
            if chave in vistas:
                raise _recusa(f"A rede {ln.rede} ({ln.localizacao}) aparece em mais de uma linha "
                              f"do território {aba.alvo} na aba {aba.aba or aba.tipo}.")
            vistas.add(chave)
            for col in aba.colunas:
                valor, c = _valor(leitura, col, ln.celulas[col.nome])
                if valor is None:
                    continue
                maximo = (FAIXA_MEDIA[col.etapa] if col.indicador == IND_PROFICIENCIA
                          else 100.0)
                if not 0 <= valor <= maximo:
                    raise _recusa(f"{col.nome} = {valor:g} fora da faixa (0 a {maximo:g}) no "
                                  f"território {aba.alvo} ({ln.dependencia}, {ln.localizacao}).")
                casas[_familia(col)] = max(casas.get(_familia(col), 0), min(c, 4))
    leitura.casas = casas


def _valor(leitura: LeituraSaeb, col: ColunaSaeb, celula: ideb.Celula) -> tuple[float | None, int]:
    if col.indicador == IND_PCT_NIVEL:
        return _percentual(celula, leitura.escala_niveis)
    if col.indicador == IND_TX_ALFABETIZADO:
        return _percentual(celula, leitura.escala_tx)
    return celula.valor, celula.casas


def _tx_sem_medida(aba: LeituraAba, ln: LinhaSaeb) -> bool:
    """O "0" da taxa numa linha sem nenhuma média do 2º ano não é taxa medida."""
    tx = next((ln.celulas[c.nome] for c in aba.colunas if c.indicador == IND_TX_ALFABETIZADO),
              None)
    if tx is None or tx.valor != 0:
        return False
    medias = [ln.celulas[c.nome] for c in aba.colunas
              if c.indicador == IND_PROFICIENCIA and c.etapa == "2_ano"]
    return bool(medias) and all(m.valor is None for m in medias)


def _avisos(leitura: LeituraSaeb) -> list[str]:
    origem = {"coluna": "pela coluna ANO_SAEB", "nome": "pelo nome do arquivo",
              "informada": "informada no preparo"}[leitura.origem_edicao]
    avisos = [f"Edição {leitura.edicao_arquivo} ({origem}). Abas lidas: "
              + ", ".join(f"{a.aba or a.tipo} ({a.tipo})" for a in leitura.abas) + "."]
    if leitura.abas_ignoradas:
        avisos.append("Abas sem o cabeçalho técnico de dados, ignoradas: "
                      + ", ".join(leitura.abas_ignoradas) + ".")
    for aba in leitura.abas:
        if not aba.linhas:
            avisos.append(f"Aba {aba.aba or aba.tipo}: nenhuma linha do território {aba.alvo}.")
            continue
        fora = Counter(ln.rotulo_dependencia for ln in aba.linhas
                       if not gravada(aba, ln) and (not ln.capital or ln.capital == "TOTAL"))
        if fora:
            quem = ("dependências do município não gravadas (a do município é a MUNICIPAL)"
                    if aba.tipo == ABA_MUNICIPIO else "dependências não gravadas")
            avisos.append(f"Aba {aba.aba or aba.tipo}: {quem}: "
                          + ", ".join(f"{d} ({n}×)" for d, n in sorted(fora.items())) + ".")
        if aba.tipo == ABA_MUNICIPIO and not any(gravada(aba, ln) for ln in aba.linhas):
            avisos.append(f"O município {aba.alvo} não tem linha da dependência MUNICIPAL na "
                          "planilha: nada é gravado para ele (outra rede NUNCA vira a "
                          "municipal).")
        if aba.segundo_ano_ignorado:
            avisos.append(f"Aba {aba.aba or aba.tipo}: as colunas do 2º ano (amostral) não são "
                          "lidas por município: " + ", ".join(aba.segundo_ano_ignorado[:6])
                          + ("…" if len(aba.segundo_ano_ignorado) > 6 else "") + ".")
        if aba.ignoradas:
            avisos.append(f"Aba {aba.aba or aba.tipo}: {len(aba.ignoradas)} coluna(s) de outras "
                          "etapas não lidas (9º ano, ensino médio...).")
        if aba.rotulos:
            avisos.append(f"Aba {aba.aba or aba.tipo}: {aba.rotulos} linha(s) sem código "
                          "(rótulos legíveis ou rodapé) puladas.")
    if leitura.escala_niveis == "fracao":
        avisos.append("Distribuição por nível em FRAÇÃO (soma 1): convertida para percentual "
                      "(× 100).")
    if leitura.escala_tx == "fracao":
        avisos.append("Taxa de alfabetização em FRAÇÃO: convertida para percentual (× 100).")
    if any(c.etapa == "2_ano" for a in leitura.abas for c in a.colunas):
        avisos.append("2º ano: contexto AMOSTRAL do Saeb, só de UF e Brasil — nunca número da "
                      "rede nem da escola.")
    if any(c.indicador == IND_TX_ALFABETIZADO for a in leitura.abas for c in a.colunas):
        avisos.append("A taxa de alfabetização desta planilha é a do Saeb do 2º ano (amostral): "
                      "NÃO é o Indicador Criança Alfabetizada (ICA) e não se compara com ele.")
    zeros = sum(1 for a in leitura.abas for ln in a.linhas if gravada(a, ln)
                and _tx_sem_medida(a, ln))
    if zeros:
        avisos.append(f"{zeros} taxa(s) de alfabetização “0” sem nenhuma média do 2º ano na "
                      "linha: viram ausência (não é taxa medida).")
    ausentes = sum(1 for a in leitura.abas for ln in a.linhas if gravada(a, ln)
                   for c in a.colunas if ln.celulas[c.nome].valor is None)
    if ausentes:
        avisos.append(f"{ausentes} número(s) sem valor nas linhas gravadas: ausência “não "
                      "divulgado” (nunca zero).")
    return avisos


# --- Planilha (linha de comando) -------------------------------------------------

def abas_da_planilha(wb, *, codigo_ibge: str,
                     progresso: Callable[[str, int], None] | None = None
                     ) -> tuple[list[LeituraAba], list[str]]:
    """Lê as abas de dados (pelo CONTEÚDO do cabeçalho) e devolve também os nomes das
    ignoradas (ex.: "Dicionário")."""
    abas, ignoradas = [], []
    for aba in wb.worksheets:
        lida = ler_aba(aba.iter_rows(values_only=True), codigo_ibge=codigo_ibge,
                       aba=aba.title,
                       progresso=(lambda n, t=aba.title: progresso(t, n)) if progresso else None)
        if lida is None:
            ignoradas.append(aba.title)
        else:
            abas.append(lida)
    return abas, ignoradas


def parece_planilha_saeb(wb) -> bool:
    """Alguma aba tem o cabeçalho técnico de dados do Saeb nas primeiras linhas?"""
    for aba in wb.worksheets:
        for linha in aba.iter_rows(max_row=_LINHAS_CABECALHO, values_only=True):
            try:
                if tipo_do_cabecalho([normalizar(c) for c in linha]):
                    return True
            except ImportacaoRecusada:
                return True
    return False


# --- Para indicadores_referencia (servidor) --------------------------------------

def recortar(lido: LeituraSaeb) -> tuple[seduc.LeituraSeduc, dict]:
    """As linhas de ``indicadores_referencia`` (avaliação ``saeb``) do território, no
    formato do fluxo de famílias (``pipeline_seduc``)."""
    leitura = seduc.LeituraSeduc(parser=lido.parser, edicao_arquivo=lido.edicao_arquivo,
                                 encoding="utf-8", linhas_lidas=lido.linhas_lidas,
                                 avisos=list(lido.avisos),
                                 colunas_ignoradas=sorted({c for a in lido.abas
                                                           for c in a.ignoradas}))
    for aba in lido.abas:
        nomes = {ln.nome for ln in aba.linhas if ln.nome}
        if aba.linhas:
            leitura.territorios[aba.alvo] = next(iter(nomes)) if len(nomes) == 1 else aba.alvo
        for ln in aba.linhas:
            if not gravada(aba, ln):
                continue
            sem_tx = _tx_sem_medida(aba, ln)
            for col in aba.colunas:
                valor, _ = _valor(lido, col, ln.celulas[col.nome])
                if col.indicador == IND_TX_ALFABETIZADO and sem_tx:
                    valor = None
                leitura.referencia.append(_numero(lido, aba, ln, col, valor))
    extra = {"edicoes": [lido.edicao_arquivo], "origem_edicao": lido.origem_edicao,
             "abas": [{"aba": a.aba, "tipo": a.tipo, "territorio": a.alvo,
                       "linhas_recorte": len(a.recorte),
                       "linhas_gravadas": sum(1 for ln in a.linhas if gravada(a, ln))}
                      for a in lido.abas],
             "abas_ignoradas": list(lido.abas_ignoradas),
             "escala_niveis": lido.escala_niveis, "escala_tx": lido.escala_tx}
    return leitura, extra


def _numero(lido: LeituraSaeb, aba: LeituraAba, ln: LinhaSaeb, col: ColunaSaeb,
            valor: float | None) -> seduc.NumeroReferencia:
    if col.indicador == IND_PROFICIENCIA:
        unidade = UNIDADE_MEDIA[col.etapa]
    else:
        unidade = "percentual"
    if col.etapa == "2_ano":
        desenho = "amostral"
    else:
        desenho = None if ln.rede == "total" else "censitario"
    base = dict(indicador=col.indicador, edicao=lido.edicao_arquivo, abrangencia=aba.tipo,
                codigo_territorio=aba.alvo, rede_ensino=ln.rede, unidade=unidade,
                etapa=col.etapa, componente=col.componente, nivel=col.nivel,
                localizacao=ln.localizacao, desenho=desenho)
    if valor is None:
        linha = LinhaCanonica(valor=None, motivo_ausencia=MOTIVO, **base)
    else:
        linha = LinhaCanonica(valor=valor, casas_decimais=lido.casas.get(_familia(col)),
                              **base)
    return seduc.NumeroReferencia(AVALIACAO, linha)
