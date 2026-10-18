"""Parser ``inep_aeeb_agregados``: as tabelas AGREGADAS dos microdados da
avaliação da alfabetização do INEP (``TS_MUNICIPIO`` e ``TS_ESTADO``).

São CSVs com ``;``, em Latin-1, uma linha por território × rede de ensino × série,
com as colunas (localizadas PELO NOME, nunca pela posição):

* ``NU_ANO_AVALIACAO``, ``CO_UF``, ``CO_MUNICIPIO`` (só no TS_MUNICIPIO),
  ``TP_SERIE``, ``ID_TIPO_REDE``;
* ``PC_ALUNO_ALFABETIZADO`` — o percentual do ICA com 2 casas (a planilha de
  resultados traz o mesmo número, em 2025 só em inteiros);
* ``VL_MEDIA_LP`` — a média de Língua Portuguesa na escala equalizada ao Saeb;
* ``PC_ALUNO_NIVEL_0_LP`` … ``PC_ALUNO_NIVEL_8_LP`` — a distribuição por nível
  (desde 2024; o arquivo de 2023 não tem essas colunas).

CÓDIGOS (dicionário oficial: os ``INPUT_R/SAS/SPSS_TS_*`` que vêm no mesmo zip,
iguais em 2023, 2024 e 2025): ``TP_SERIE`` 2 = 2º ano do Ensino Fundamental;
``ID_TIPO_REDE`` 0 = Total (inclui a privada), 1 = Federal, 2 = Estadual,
3 = Municipal, 4 = Privada, 5 = Pública (Estadual e Municipal), 6 = Pública
(Federal, Estadual e Municipal).

O QUE ENTRA (comparação sempre com a MESMA rede — plano, 4.8):

* município da rede (``redes.codigo_ibge``): só a linha MUNICIPAL (3) — o ICA do
  município é o da rede municipal;
* UF do município (os 2 primeiros dígitos do IBGE): a linha PÚBLICA (5), que é a
  rede do ICA da UF na planilha de resultados (vira o DETALHE com 2 casas dela), e
  a MUNICIPAL (3) — "SP só redes municipais", a comparação justa com o município;
* Brasil: os TS não trazem linha do Brasil (conferido em 2023–2025). O Brasil
  continua vindo só da planilha de UFs.

Nada de rede estadual, privada ou total; nada de outros municípios.

PRECISÃO: o percentual e os níveis são publicados com 2 casas (às vezes sem o
zero final: "27.9" é 27,90 — exemplo sintético) e a média com 4 a 5 casas, que
o Constela mostra com 2 (como a divulgação das médias). Por isso
``casas_decimais`` é fixo em 2 — não depende das outras linhas do arquivo, e o
pacote recortado (só as linhas da rede) reproduz exatamente a leitura do arquivo
inteiro.

DADO DE ALUNO NUNCA: o parser RECUSA o ``TS_ALUNO`` (pelo nome) e qualquer
arquivo com coluna de aluno, escola ou proficiência individual — antes de ler
uma linha de dados.

Função PURA: bytes → ``LeituraICA`` (linhas canônicas + avisos). Sem banco.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

from app.services.avaliacoes import ImportacaoRecusada
from app.services.indicadores import ica

PARSER = "inep_aeeb_agregados"
VERSAO_PARSER = "1"

TABELA_MUNICIPIO = "TS_MUNICIPIO"
TABELA_ESTADO = "TS_ESTADO"
TABELAS = (TABELA_MUNICIPIO, TABELA_ESTADO)

# Dicionário oficial (INPUT_* do zip do INEP).
SERIE_2_ANO = "2"
REDE_MUNICIPAL = "3"
REDE_PUBLICA = "5"
REDES = {REDE_MUNICIPAL: "municipal", REDE_PUBLICA: "publica"}

IND_MEDIA_LP = "media_lp"
IND_PCT_NIVEL = "pct_nivel"
UNIDADE_MEDIA = "escala_alfabetizacao"   # escala do 2º ano equalizada ao Saeb (corte 743)
NIVEIS = tuple(range(9))                  # níveis de LP 0 a 8
CASAS = 2
CORTE_ALFABETIZADO = 743                  # pontos na escala do Saeb (definição do ICA)

_FIXAS = ("NU_ANO_AVALIACAO", "CO_UF", "TP_SERIE", "ID_TIPO_REDE",
          "PC_ALUNO_ALFABETIZADO", "VL_MEDIA_LP")
_COL_NIVEL = "PC_ALUNO_NIVEL_{}_LP"
# Teto de linhas: o TS_MUNICIPIO real tem ~12,5 mil (5,5 mil municípios × redes).
# O TS_ALUNO tem milhões — um arquivo assim nem chega a ser lido até o fim.
_MAX_LINHAS = 200_000
_MAX_BYTES = 30 * 1024 * 1024
# A média de LP é da escala do Saeb do 2º ano (centenas de pontos, corte 743).
_MEDIA_MIN, _MEDIA_MAX = 0, 1000
_TOLERANCIA_SOMA_NIVEIS = 0.5

# Coluna de DADO DE ALUNO (ou de escola/turma, ou de proficiência individual): se
# aparecer, o arquivo não é uma tabela agregada — recusa, sem ler os dados.
_RE_COLUNA_DE_ALUNO = re.compile(
    r"(^|_)(ALUNO|ESCOLA|TURMA|PROFICIENCIA|PESO|PRESENCA|RESPOSTA|CADERNO|BLOCO)(_|$)")
_ARQUIVO = ("a tabela agregada TS_MUNICIPIO.csv ou TS_ESTADO.csv dos microdados da "
            "avaliação da alfabetização do INEP")
MSG_ALUNO = ("é dado POR ALUNO (microdado individual) — o Constela não lê, não grava "
             "e não guarda dado de aluno. Use só as tabelas agregadas TS_MUNICIPIO e "
             "TS_ESTADO. Nada foi gravado.")


@dataclass
class LeituraAEEB(ica.LeituraICA):
    """A leitura de UMA tabela (TS_MUNICIPIO ou TS_ESTADO), com as linhas do
    arquivo que foram usadas — é delas que o ``preparar`` monta o recorte."""

    tabela: str = ""
    cabecalho: list[str] = field(default_factory=list)
    linhas_usadas: list[list[str]] = field(default_factory=list)


def nome_de_aluno(nome: str) -> bool:
    """O NOME já diz que é a tabela de alunos (``TS_ALUNO``, ``…ALUNO….csv``)."""
    base = re.split(r"[\\/]", nome or "")[-1].upper()
    return "ALUNO" in base


def recusar_se_for_de_aluno(nome: str, cabecalho: list[str] | None = None) -> None:
    """LEVANTA ``ImportacaoRecusada`` se o arquivo é de aluno (nome ou colunas)."""
    if nome_de_aluno(nome):
        raise ImportacaoRecusada(f"O arquivo “{nome}” {MSG_ALUNO}")
    de_aluno = sorted(c for c in (cabecalho or [])
                      if _RE_COLUNA_DE_ALUNO.search(c) and not c.startswith("PC_ALUNO_"))
    if de_aluno:
        raise ImportacaoRecusada(
            f"O arquivo “{nome or 'sem nome'}” tem coluna de aluno/escola "
            f"({', '.join(de_aluno[:5])}): {MSG_ALUNO}")


def decodificar(conteudo: bytes) -> str:
    """UTF-8 (com ou sem BOM) quando decodifica; senão Latin-1, a do INEP. O pacote
    recortado é gravado em UTF-8; o original vem em Latin-1."""
    try:
        return conteudo.decode("utf-8-sig")
    except UnicodeDecodeError:
        return conteudo.decode("latin-1")


def _cabecalho(texto: str) -> list[str]:
    primeira = texto.split("\n", 1)[0].rstrip("\r")
    return [c.strip().strip('"').upper() for c in primeira.split(";")]


def cabecalho(conteudo: bytes) -> list[str]:
    """As colunas da 1ª linha (para recusar arquivo de aluno antes de ler os dados)."""
    return _cabecalho(decodificar(conteudo[:4096]))


def tabela_do_cabecalho(cabecalho: list[str]) -> str | None:
    """``TS_MUNICIPIO`` | ``TS_ESTADO`` pela ASSINATURA das colunas, ou None."""
    if not all(c in cabecalho for c in ("NU_ANO_AVALIACAO", "ID_TIPO_REDE", "CO_UF")):
        return None
    return TABELA_MUNICIPIO if "CO_MUNICIPIO" in cabecalho else TABELA_ESTADO


def parece_tabela_aeeb(conteudo: bytes) -> bool:
    """Atalho para o despacho da importação: a 1ª linha tem a assinatura de um TS."""
    texto = decodificar(conteudo[:4096])
    return tabela_do_cabecalho(_cabecalho(texto)) is not None


def _mapear(cabecalho: list[str], tabela: str) -> dict:
    vistos: dict[str, int] = {}
    repetidas = []
    for j, c in enumerate(cabecalho):
        if c in vistos:
            repetidas.append(c)
        vistos[c] = j
    if repetidas:
        raise ImportacaoRecusada(
            f"A coluna {', '.join(sorted(set(repetidas)))} aparece mais de uma vez no "
            f"arquivo; confira se é {_ARQUIVO}. Nada foi gravado.")
    exigidas = (*_FIXAS, "CO_MUNICIPIO") if tabela == TABELA_MUNICIPIO else _FIXAS
    faltam = [c for c in exigidas if c not in vistos]
    if faltam:
        raise ImportacaoRecusada(
            f"O arquivo não tem a coluna {', '.join(faltam)}; confira se é {_ARQUIVO}. "
            "Nada foi gravado.")
    niveis = {k: vistos.get(_COL_NIVEL.format(k)) for k in NIVEIS}
    presentes = [k for k, j in niveis.items() if j is not None]
    if presentes and len(presentes) != len(NIVEIS):
        faltando = [_COL_NIVEL.format(k) for k in NIVEIS if niveis[k] is None]
        raise ImportacaoRecusada(
            f"O arquivo traz só parte dos níveis de LP (falta {', '.join(faltando)}); "
            f"confira se é {_ARQUIVO}. Nada foi gravado.")
    return {"col": vistos, "niveis": niveis if presentes else None}


def _linhas_csv(texto: str):
    leitor = csv.reader(io.StringIO(texto), delimiter=";")
    next(leitor, None)                       # cabeçalho
    for n, linha in enumerate(leitor, start=2):
        if n - 1 > _MAX_LINHAS:
            raise ImportacaoRecusada(
                f"O arquivo tem mais de {_MAX_LINHAS} linhas — muito maior que a tabela "
                "agregada do INEP (é a de alunos?). Nada foi gravado.")
        if not any(c.strip() for c in linha):
            continue
        yield n, linha


def _valor(texto: str, rotulo: str, coluna: str, minimo: float, maximo: float,
           avisos: list[str]) -> float | None:
    texto = (texto or "").strip()
    if texto.upper() == "NA":                # o "vazio" dos INPUT_R do INEP
        return None
    numero, operador, ok = ica.ler_numero(texto)
    if not ok or operador is not None:
        avisos.append(f"{rotulo}: valor não numérico “{texto}” em {coluna} — tratado "
                      "como ausente (não como zero).")
        return None
    if numero is None:
        return None
    if not minimo <= numero <= maximo:
        raise ImportacaoRecusada(
            f"{rotulo}: {coluna} = {numero} fora da faixa ({minimo} a {maximo}). O arquivo "
            "não confere com o layout oficial; nada foi gravado.")
    return ica.arredondar(numero, CASAS)


def _linhas_do_territorio(linha: list[str], mapa: dict, *, edicao: int, abrangencia: str,
                          codigo: str, rede_ensino: str, rotulo: str,
                          avisos: list[str]) -> list[ica.LinhaCanonica]:
    col = mapa["col"]

    def cel(nome_ou_indice) -> str:
        j = col[nome_ou_indice] if isinstance(nome_ou_indice, str) else nome_ou_indice
        return linha[j] if j is not None and j < len(linha) else ""

    base = {"edicao": edicao, "abrangencia": abrangencia, "codigo_territorio": codigo,
            "rede_ensino": rede_ensino}

    def numero(indicador: str, unidade: str, valor: float | None, nivel: str = ""):
        if valor is None:
            return ica.LinhaCanonica(indicador=indicador, unidade=unidade, valor=None,
                                     motivo_ausencia="nao_divulgado", nivel=nivel, **base)
        return ica.LinhaCanonica(indicador=indicador, unidade=unidade, valor=valor,
                                 casas_decimais=CASAS, nivel=nivel, **base)

    saida = [
        numero(ica.IND_RESULTADO, "percentual",
               _valor(cel("PC_ALUNO_ALFABETIZADO"), rotulo, "PC_ALUNO_ALFABETIZADO",
                      0, 100, avisos)),
        numero(IND_MEDIA_LP, UNIDADE_MEDIA,
               _valor(cel("VL_MEDIA_LP"), rotulo, "VL_MEDIA_LP", _MEDIA_MIN, _MEDIA_MAX,
                      avisos)),
    ]
    if mapa["niveis"] is not None:
        valores = []
        for k in NIVEIS:
            coluna = _COL_NIVEL.format(k)
            v = _valor(cel(mapa["niveis"][k]), rotulo, coluna, 0, 100, avisos)
            valores.append(v)
            saida.append(numero(IND_PCT_NIVEL, "percentual", v, nivel=str(k)))
        if all(v is not None for v in valores):
            soma = round(sum(valores), 2)
            if abs(soma - 100) > _TOLERANCIA_SOMA_NIVEIS:
                avisos.append(f"{rotulo}: os níveis 0 a 8 somam {soma}% (esperado ≈ 100%) "
                              "— confira o arquivo.")
    return saida


def _rotulo(abrangencia: str, codigo: str, rede_ensino: str, nome: str | None) -> str:
    rede = "rede municipal" if rede_ensino == "municipal" else "rede pública"
    if abrangencia == "municipio":
        return f"{nome or codigo} ({rede})"
    return f"UF {codigo} ({'redes municipais' if rede_ensino == 'municipal' else rede})"


def ler_tabela_aeeb(conteudo: bytes, nome: str, *, codigo_ibge: str) -> LeituraAEEB:
    """Lê UMA tabela agregada (TS_MUNICIPIO ou TS_ESTADO, detectada pelas colunas) e
    recorta SÓ o que a rede usa (ver o docstring do módulo). LEVANTA
    ``ImportacaoRecusada`` se o arquivo não confere ou se é de aluno."""
    codigo_ibge = ica.normalizar_codigo_ibge(codigo_ibge)
    if codigo_ibge is None:
        raise ImportacaoRecusada("Código IBGE do município inválido (são 7 dígitos).")
    recusar_se_for_de_aluno(nome)
    if len(conteudo) > _MAX_BYTES:
        raise ImportacaoRecusada(
            f"O arquivo “{nome}” tem {len(conteudo) // (1024 * 1024)} MB — muito maior que a "
            "tabela agregada do INEP (é a de alunos?). Nada foi gravado.")
    texto = decodificar(conteudo)
    cabecalho = _cabecalho(texto)
    recusar_se_for_de_aluno(nome, cabecalho)
    tabela = tabela_do_cabecalho(cabecalho)
    if tabela is None:
        raise ImportacaoRecusada(
            f"O arquivo “{nome or 'sem nome'}” não parece {_ARQUIVO}: faltam as colunas "
            "NU_ANO_AVALIACAO, CO_UF e ID_TIPO_REDE na 1ª linha. Nada foi gravado.")
    mapa = _mapear(cabecalho, tabela)
    col = mapa["col"]
    codigo_uf = codigo_ibge[:2]
    anos: set[int] = set()
    outras_series = 0
    lidas = 0
    alvos: dict[tuple[str, str], list[list[str]]] = {}
    municipio_noutra_rede = False
    for n, linha in _linhas_csv(texto):
        if len(linha) != len(cabecalho):
            raise ImportacaoRecusada(
                f"A linha {n} do arquivo tem {len(linha)} colunas, e o cabeçalho tem "
                f"{len(cabecalho)} (arquivo cortado ou de outro formato). Nada foi gravado.")
        lidas += 1
        ano = ica._ano(linha[col["NU_ANO_AVALIACAO"]].strip())
        if ano is None:
            raise ImportacaoRecusada(
                f"A linha {n} não tem um ano válido em NU_ANO_AVALIACAO "
                f"(“{linha[col['NU_ANO_AVALIACAO']]}”). Nada foi gravado.")
        anos.add(ano)
        if linha[col["TP_SERIE"]].strip() != SERIE_2_ANO:
            outras_series += 1
            continue
        rede = linha[col["ID_TIPO_REDE"]].strip()
        if tabela == TABELA_MUNICIPIO:
            if linha[col["CO_MUNICIPIO"]].strip() != codigo_ibge:
                continue
            if rede != REDE_MUNICIPAL:
                municipio_noutra_rede = True
                continue
            alvos.setdefault(("municipio", rede), []).append(linha)
        else:
            if linha[col["CO_UF"]].strip() != codigo_uf or rede not in REDES:
                continue
            alvos.setdefault(("uf", rede), []).append(linha)
    if not anos:
        raise ImportacaoRecusada(
            f"O arquivo não tem linhas de dados; confira se é {_ARQUIVO}. Nada foi gravado.")
    if len(anos) > 1:
        raise ImportacaoRecusada(
            f"O arquivo mistura anos de avaliação ({', '.join(map(str, sorted(anos)))}) em "
            f"NU_ANO_AVALIACAO; confira se é {_ARQUIVO}. Nada foi gravado.")
    edicao = next(iter(anos))
    leitura = LeituraAEEB(parser=PARSER, edicao_arquivo=edicao, arquivo_data=None,
                          aba=tabela, tabela=tabela, cabecalho=cabecalho,
                          linhas_lidas=lidas)
    if outras_series:
        leitura.avisos.append(f"{outras_series} linha(s) de outra série (TP_SERIE ≠ 2) "
                              "ignorada(s): o ICA é do 2º ano.")
    if mapa["niveis"] is None:
        leitura.avisos.append(f"O arquivo de {edicao} não traz a distribuição por nível "
                              "(PC_ALUNO_NIVEL_0..8_LP): sem níveis desta edição.")
    for (abrangencia, rede), linhas in sorted(alvos.items()):
        rede_ensino = REDES[rede]
        if len(linhas) > 1:
            raise ImportacaoRecusada(
                f"{_rotulo(abrangencia, codigo_ibge if abrangencia == 'municipio' else codigo_uf, rede_ensino, None)} "
                f"aparece {len(linhas)} vezes no arquivo; não dá para saber qual linha vale. "
                "Nada foi gravado.")
        linha = linhas[0]
        codigo = codigo_ibge if abrangencia == "municipio" else codigo_uf
        nome_mun = None
        if abrangencia == "municipio" and "NO_MUNICIPIO" in col:
            nome_mun = linha[col["NO_MUNICIPIO"]].strip() or None
            leitura.territorios[codigo] = nome_mun or codigo
        leitura.linhas.extend(_linhas_do_territorio(
            linha, mapa, edicao=edicao, abrangencia=abrangencia, codigo=codigo,
            rede_ensino=rede_ensino, rotulo=_rotulo(abrangencia, codigo, rede_ensino, nome_mun),
            avisos=leitura.avisos))
        leitura.linhas_usadas.append(linha)
    if tabela == TABELA_MUNICIPIO and ("municipio", REDE_MUNICIPAL) not in alvos:
        if municipio_noutra_rede:
            leitura.avisos.append(
                f"O município {codigo_ibge} está no {tabela}, mas não na rede MUNICIPAL — "
                "nada a importar dele (o ICA do município é o da rede municipal).")
        else:
            leitura.avisos.append(
                f"O município {codigo_ibge} não está no {tabela} de {edicao} (sem resultado "
                "nos microdados). Nada a importar dele deste arquivo.")
    if tabela == TABELA_ESTADO:
        for rede, rede_ensino in REDES.items():
            if ("uf", rede) not in alvos:
                leitura.avisos.append(
                    f"{_rotulo('uf', codigo_uf, rede_ensino, None)} não está no {tabela} "
                    f"de {edicao} — nada a importar para essa linha.")
    return leitura
