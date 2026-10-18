"""Linha de comando ``preparar``: recorta, NESTA máquina, as tabelas agregadas dos
microdados da avaliação da alfabetização do INEP e gera o PACOTE pequeno que sobe
pela tela de importação do ICA (plano, 4.4).

Uso (a partir de ``backend/``). O zip do INEP e o pacote ficam FORA do
repositório: ele é público e o recorte é de arquivo oficial (CC BY-ND — D13); o
.gitignore também barra ``pacote_*.zip`` (o do ICA e o do Ideb), ``microdados_*.zip``
e ``divulgacao_*`` (o zip do Ideb e a planilha extraída dele), e o comando AVISA
quando a pasta de saída fica dentro do repositório::

    # zip já baixado (local)
    python -m app.services.indicadores.preparar --ibge 3510500 \\
        --zip ~/constela-dados-oficiais/microdados_AEEB_2025.zip \\
        --saida ~/constela-dados-oficiais/pacotes \\
        [--url URL_DE_ORIGEM] [--last-modified "..."]

    # direto da URL do INEP, por HTTP Range (só as entradas agregadas)
    python -m app.services.indicadores.preparar --ibge 3510500 \\
        --url https://download.inep.gov.br/dados_abertos/microdados_AEEB_2025.zip \\
        --saida ~/constela-dados-oficiais/pacotes

    [--saida PASTA]   (padrão: a pasta atual — prefira uma pasta fora do repositório)

O que ela faz:

1. lê só o diretório do zip e as entradas ``TS_MUNICIPIO.csv`` e ``TS_ESTADO.csv``
   (pela URL, cada pedaço é uma requisição com Range — o zip inteiro nunca é
   baixado; o ``TS_ALUNO``, dado de aluno, nunca é lido);
2. confere o CRC32 e o tamanho de cada entrada (diferente = recusa);
3. passa cada tabela pelo parser ``inep_aeeb_agregados`` (o MESMO do servidor);
4. grava ``pacote_ica_aeeb_<ano>_<ibge>.zip``: o recorte canônico (só as linhas do
   município e da UF dele) + o manifesto com a URL, o Last-Modified, a ETag, o
   sha256 e o CRC32 das entradas originais e a versão do parser. Tabela sem
   nenhuma linha da rede (ex.: o município não tem linha da rede MUNICIPAL no
   TS_MUNICIPIO) fica FORA do pacote, com aviso; se nenhuma tiver, recusa (nenhum
   pacote é gravado).

Depois, suba o pacote em Avaliações externas → ICA → "Escolher arquivo e ver
prévia" (admin global). O servidor refaz a validação; pacote alterado é recusado.

IDEB POR ESCOLA (E6a) — o MESMO comando, com o zip do Ideb dos anos iniciais
(``divulgacao_anos_iniciais_escolas_AAAA.zip``, detectado pelo CONTEÚDO do zip)::

    python -m app.services.indicadores.preparar --ibge 3510500 \\
        --zip ~/constela-dados-oficiais/ideb/divulgacao_anos_iniciais_escolas_2025.zip \\
        --saida ~/constela-dados-oficiais/pacotes [--url URL_DE_ORIGEM] [--last-modified "..."]

* SÓ CAMINHO LOCAL: o xlsx dele tem ~50 MB comprimidos dentro de um zip de ~100 MB
  e não há como ler só as linhas da rede por HTTP Range (seria baixar a entrada
  inteira). Baixe o zip (com a sua autorização) e passe ``--zip``; ``--url`` e
  ``--last-modified`` só registram a origem no manifesto;
* o ZIP como foi baixado, não a planilha extraída dele (.xlsx/.ods, que também são
  zips): é no zip que vêm o md5 que o INEP publica e o sha256 que identifica a origem.
  A planilha solta é reconhecida e recusada com essa explicação;
* lê o xlsx em STREAMING (openpyxl ``read_only``; poucos minutos e algumas dezenas de
  MB de memória), confere o md5 que o próprio INEP põe no zip e grava
  ``pacote_ideb_escolas_<edição>_<ibge>.zip``: o topo da planilha + SÓ as linhas da
  rede municipal do município + o rodapé, com o manifesto (sha256 do zip e do xlsx,
  versão do parser, todas as edições e metas encontradas);
* suba o pacote na importação do Ideb (``/redes/{id}/indicadores/ideb/previa``,
  admin global). A produção nunca abre o arquivo do INEP.

IDEB DO MUNICÍPIO, DA UF E DO BRASIL (E6b) — o MESMO comando e a MESMA rota de
importação, com o zip de municípios (``divulgacao_anos_iniciais_municipios_AAAA.zip``),
o de UF/regiões (``divulgacao_regioes_ufs_ideb_AAAA.zip``) ou o de Brasil
(``divulgacao_brasil_ideb_AAAA.zip``), detectados pelo CONTEÚDO (a linha técnica sem
``ID_ESCOLA``; a aba dos anos iniciais pelo topo): grava
``pacote_ideb_<municipio|uf|brasil>_<edição>_<ibge>.zip`` com o topo da planilha + as
linhas do território (todas as redes) + o rodapé.

PLANILHA DO SAEB (E7) — Brasil, estados e municípios (médias e níveis do 5º ano; 2º ano
amostral e a taxa de alfabetização de 2021 só de UF e Brasil)::

    python -m app.services.indicadores.preparar --ibge 3510500 \\
        --planilha ~/constela-dados-oficiais/inep-saeb/saeb_2025_..._censitario.xlsx \\
        --saida ~/constela-dados-oficiais/pacotes [--edicao AAAA]

* SÓ ARQUIVO LOCAL e em STREAMING (a de 2025 tem ~150 MB de XML); a aba "Dicionário" é
  ignorada pelo conteúdo; ``--edicao`` só quando a planilha não traz ``ANO_SAEB`` nem o
  ano no nome;
* grava ``pacote_saeb_<edição>_<resultados|tx_alfabetizado>_<ibge>.zip`` (um CSV por aba,
  só com as linhas do território) e sobe em ``/redes/{id}/indicadores/saeb/previa``.

ORIGEM (todas as fontes): ``--url``/``--last-modified`` ou, melhor, o MANIFESTO.json
do download (``--manifesto``; sem a opção, o da pasta do arquivo, quando ele registra o
arquivo): a URL, o Last-Modified e a data do download vêm dele, e o sha256 registrado
tem de ser o do arquivo (senão, recusa).

Não usa banco nem a rede além da URL pedida (só https para host público).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from app.services.avaliacoes import ImportacaoRecusada
from app.services.indicadores import (aeeb, ica, ideb, ideb_territorio, pacote, pacote_ideb,
                                      pacote_saeb, saeb_planilha)
from app.services.indicadores.zip_parcial import (BuscarFaixa, Entrada, FonteArquivoLocal,
                                                  FonteHTTPRange, entrada_de_aluno,
                                                  ler_entrada, listar_entradas)


@dataclass
class Preparo:
    """O pacote gerado e o que foi lido para gerá-lo."""

    pacote: bytes
    manifesto: dict
    nome: str
    leituras: list[aeeb.LeituraAEEB] = field(default_factory=list)
    bytes_lidos: int = 0
    faixas: list[tuple[int, int]] = field(default_factory=list)


def _sha256_arquivo(caminho: Path) -> str:
    h = hashlib.sha256()
    with caminho.open("rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def planilha_extraida(nomes: list[str]) -> str | None:
    """``"xlsx"``/``"ods"`` quando o "zip" é, na verdade, uma PLANILHA solta (o .xlsx
    e o .ods também são zips: ``[Content_Types].xml``, ou ``mimetype`` +
    ``META-INF/manifest.xml``, na raiz); None se não for."""
    conjunto = set(nomes)
    if "[Content_Types].xml" in conjunto:
        return "xlsx"
    if "mimetype" in conjunto and "META-INF/manifest.xml" in conjunto:
        return "ods"
    return None


def _recusa_planilha_extraida(tipo: str) -> ImportacaoRecusada:
    return ImportacaoRecusada(
        f"Este arquivo é uma planilha .{tipo} (já extraída do zip), não o zip do INEP. "
        "Para o Ideb por escola, passe em --zip o zip do INEP como foi baixado "
        "(divulgacao_anos_iniciais_escolas_AAAA.zip), sem descompactar: é nele que vêm o "
        "md5 que o INEP publica (conferido) e o sha256 que identifica a origem no "
        "manifesto. Nenhum pacote foi gerado.")


def escolher_entradas(entradas: list[Entrada]) -> list[Entrada]:
    """Só ``TS_MUNICIPIO.csv`` e ``TS_ESTADO.csv`` (pelo nome do arquivo, em qualquer
    pasta do zip). Entrada de aluno nunca entra. Ambíguo (duas de uma tabela) ou sem
    nenhuma das duas = recusa (com a causa, quando é o zip do Ideb ou uma planilha
    extraída dele)."""
    escolhidas: dict[str, Entrada] = {}
    for e in entradas:
        if entrada_de_aluno(e.nome):
            continue
        base = e.base.upper()
        for tabela in aeeb.TABELAS:
            if base == f"{tabela}.CSV":
                if tabela in escolhidas:
                    raise ImportacaoRecusada(
                        f"O zip tem mais de uma entrada {tabela}.csv ({escolhidas[tabela].nome} "
                        f"e {e.nome}); não dá para saber qual vale.")
                escolhidas[tabela] = e
    if not escolhidas:
        tipo = planilha_extraida([e.nome for e in entradas])
        if tipo:
            raise _recusa_planilha_extraida(tipo)
        if any(e.base.lower().endswith(".xlsx") for e in entradas):
            raise ImportacaoRecusada(
                "Este parece o zip do Ideb por escola (tem uma planilha .xlsx dentro): ele só "
                "é lido LOCAL — baixe o zip e rode o preparar com --zip (o xlsx tem dezenas de "
                "MB comprimidos; não há como ler só a rede por HTTP Range).")
        raise ImportacaoRecusada(
            "O zip não tem as tabelas agregadas TS_MUNICIPIO.csv nem TS_ESTADO.csv — não é o "
            "zip dos microdados da avaliação da alfabetização do INEP?")
    return [escolhidas[t] for t in aeeb.TABELAS if t in escolhidas]


def preparar(*, codigo_ibge: str, zip_local: str | Path | None = None, url: str | None = None,
             last_modified: str | None = None, buscar: BuscarFaixa | None = None,
             agora: datetime | None = None) -> Preparo:
    """Gera o pacote a partir do zip LOCAL (``zip_local``; ``url``/``last_modified``
    só registram a origem) ou da ``url`` por HTTP Range (``buscar`` injetável)."""
    codigo = ica.normalizar_codigo_ibge(codigo_ibge)
    if codigo is None:
        raise ImportacaoRecusada("Código IBGE do município inválido (são 7 dígitos; "
                                 "Caraguatatuba = 3510500).")
    if zip_local is None and not url:
        raise ImportacaoRecusada("Informe o zip local (--zip) ou a URL do INEP (--url).")
    if zip_local is not None:
        caminho = Path(zip_local)
        fonte = FonteArquivoLocal(caminho)
        origem = {"modo": "zip_local", "arquivo_nome": caminho.name, "url": url or None,
                  "last_modified": last_modified or None, "etag": None,
                  "zip_bytes": fonte.tamanho, "zip_sha256": _sha256_arquivo(caminho)}
    else:
        fonte = FonteHTTPRange(url, buscar)
        origem = {"modo": "http_range", "arquivo_nome": url.rstrip("/").rsplit("/", 1)[-1],
                  "url": url, "last_modified": fonte.last_modified, "etag": fonte.etag,
                  "zip_bytes": fonte.tamanho, "zip_sha256": None}
    todas = listar_entradas(fonte)
    escolhidas = escolher_entradas(todas)
    lidas = []
    avisos: list[str] = []
    vazias: list[aeeb.LeituraAEEB] = []
    for entrada in escolhidas:
        conteudo = ler_entrada(fonte, entrada)            # CRC32 e tamanho conferidos
        leitura = aeeb.ler_tabela_aeeb(conteudo, entrada.nome, codigo_ibge=codigo)
        avisos.extend(f"{leitura.tabela}: {a}" for a in leitura.avisos)
        # Tabela sem nenhuma linha da rede (ex.: o município não tem linha da rede
        # MUNICIPAL no TS_MUNICIPIO): fica FORA do pacote, como a que falta no zip —
        # um recorte só com o cabeçalho seria recusado pelo servidor e levaria junto
        # as linhas válidas da outra tabela.
        if leitura.linhas_usadas:
            lidas.append((entrada, conteudo, leitura))
        else:
            vazias.append(leitura)
    # A tabela que fica fora do pacote também conta para "um zip, uma edição".
    edicoes = {lt.edicao_arquivo for _, _, lt in lidas} | {lt.edicao_arquivo for lt in vazias}
    if len(edicoes) > 1:
        raise ImportacaoRecusada(
            f"As tabelas são de anos diferentes ({', '.join(map(str, sorted(edicoes)))}): um "
            "pacote é de uma edição só.")
    presentes = {lt.tabela for _, _, lt in lidas} | {lt.tabela for lt in vazias}
    faltam = [t for t in aeeb.TABELAS if t not in presentes]
    falta_no_zip = (f"O zip não tem {', '.join(faltam)}.csv: o pacote vai sem essa tabela."
                    if faltam else None)
    if not lidas:
        motivos = [a for lt in vazias for a in lt.avisos
                   if "não está no" in a or "rede MUNICIPAL" in a]
        raise ImportacaoRecusada(" ".join([
            f"Nada a importar para o município {codigo} neste zip: nenhuma tabela agregada "
            "tem linha da rede dele.", *motivos,
            *([falta_no_zip.split(":")[0] + "."] if falta_no_zip else []),
            "Nenhum pacote foi gerado."]))
    for leitura in vazias:
        avisos.append(f"{leitura.tabela}: nenhuma linha a importar — a tabela fica fora do "
                      "pacote.")
    if falta_no_zip:
        avisos.append(falta_no_zip)
    origem["bytes_lidos"] = fonte.bytes_lidos
    origem["entradas_no_zip"] = len(todas)
    origem["entradas_de_aluno_nao_lidas"] = [e.nome for e in todas if entrada_de_aluno(e.nome)]
    dados, manifesto = pacote.montar_pacote(lidas, codigo_ibge=codigo, origem=origem,
                                            gerado_em=agora, avisos=avisos)
    edicao = manifesto["edicao"]
    return Preparo(pacote=dados, manifesto=manifesto,
                   nome=f"pacote_ica_aeeb_{edicao}_{codigo}.zip",
                   leituras=[lt for _, _, lt in lidas], bytes_lidos=fonte.bytes_lidos,
                   faixas=list(getattr(fonte, "faixas", [])))


# --- Ideb por escola (E6a): só zip LOCAL ------------------------------------------

@dataclass
class PreparoIdeb:
    """O pacote do Ideb por escola e o que foi lido para gerá-lo."""

    pacote: bytes
    manifesto: dict
    nome: str
    leitura: object              # ideb.LeituraIdeb | ideb_territorio.LeituraTerritorio
    segundos: float = 0.0


_RE_MD5 = re.compile(r"^\s*([0-9a-fA-F]{32})\s+\*?(.+?)\s*$")


def zip_do_ideb(caminho: str | Path) -> bool:
    """O zip LOCAL é o do Ideb (uma planilha .xlsx dentro e nenhuma tabela dos
    microdados)? Só olha o diretório do zip; quem confere o layout é o parser."""
    try:
        with zipfile.ZipFile(caminho) as z:
            nomes = [n for n in z.namelist() if not n.startswith("__MACOSX")]
    except (OSError, zipfile.BadZipFile):
        return False
    bases = [n.rsplit("/", 1)[-1].upper() for n in nomes]
    if any(b == f"{t}.CSV" for b in bases for t in aeeb.TABELAS):
        return False
    return any(b.endswith(".XLSX") for b in bases)


def _escolher_xlsx(z: zipfile.ZipFile) -> zipfile.ZipInfo:
    planilhas = [i for i in z.infolist() if i.filename.lower().endswith(".xlsx")
                 and not i.filename.startswith("__MACOSX") and not i.is_dir()]
    if not planilhas and (tipo := planilha_extraida(z.namelist())):
        raise _recusa_planilha_extraida(tipo)
    if len(planilhas) != 1:
        raise ImportacaoRecusada(
            "O zip não tem nenhuma planilha .xlsx." if not planilhas else
            f"O zip tem {len(planilhas)} planilhas .xlsx "
            f"({', '.join(i.filename for i in planilhas)}); não dá para saber qual vale.")
    return planilhas[0]


def _md5_publicado(z: zipfile.ZipFile, nome: str) -> str | None:
    """O md5 que o INEP publica DENTRO do zip (``md5_*.txt``: "<md5> *<arquivo>")."""
    base = nome.rsplit("/", 1)[-1]
    for info in z.infolist():
        if not info.filename.lower().endswith(".txt") or info.file_size > 64 * 1024:
            continue
        for linha in ica.ler_do_zip(z, info, 64 * 1024).decode("latin-1").splitlines():
            casou = _RE_MD5.match(linha)
            if casou and casou.group(2).rsplit("/", 1)[-1] == base:
                return casou.group(1).lower()
    return None


def _hashes_da_entrada(z: zipfile.ZipFile, info: zipfile.ZipInfo) -> tuple[str, str]:
    """``(sha256, md5)`` da entrada, lida em blocos (o zipfile confere o CRC32 no fim)."""
    sha, md5 = hashlib.sha256(), hashlib.md5()  # noqa: S324 — md5 só para conferir o do INEP
    with z.open(info) as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            sha.update(bloco)
            md5.update(bloco)
    return sha.hexdigest(), md5.hexdigest()


def _ideb_por_escola(wb) -> bool:
    """Alguma aba tem ``ID_ESCOLA`` na linha técnica (o Ideb por escola)? Senão, é o
    do município, da UF ou do Brasil (``ideb_territorio``) — pelo CONTEÚDO."""
    for aba in wb.worksheets:
        for linha in aba.iter_rows(max_row=20, values_only=True):
            if "ID_ESCOLA" in {ideb.texto_celula(c).upper() for c in linha}:
                return True
    return False


def preparar_ideb(*, codigo_ibge: str, zip_local: str | Path, url: str | None = None,
                  last_modified: str | None = None, baixado_em: str | None = None,
                  agora: datetime | None = None,
                  progresso: Callable[[int], None] | None = None) -> PreparoIdeb:
    """Gera o pacote do Ideb a partir do zip LOCAL do INEP — por escola (E6a) ou do
    município, da UF ou do Brasil (E6b), detectado pelo CONTEÚDO da planilha (``url``,
    ``last_modified`` e ``baixado_em`` só registram a origem). LEVANTA
    ``ImportacaoRecusada``."""
    inicio = time.perf_counter()
    codigo = ica.normalizar_codigo_ibge(codigo_ibge)
    if codigo is None:
        raise ImportacaoRecusada("Código IBGE do município inválido (são 7 dígitos; "
                                 "Caraguatatuba = 3510500).")
    caminho = Path(zip_local)
    if not caminho.is_file():
        raise ImportacaoRecusada(f"O zip {caminho} não existe (o Ideb só é lido de um zip "
                                 "LOCAL).")
    try:
        z = zipfile.ZipFile(caminho)
    except zipfile.BadZipFile as exc:
        raise ImportacaoRecusada(f"{caminho.name} não é um zip válido.") from exc
    with z:
        info = _escolher_xlsx(z)
        publicado = _md5_publicado(z, info.filename)
        try:
            sha_entrada, md5_entrada = _hashes_da_entrada(z, info)
        except (zipfile.BadZipFile, OSError, EOFError) as exc:
            raise ImportacaoRecusada(f"A planilha {info.filename} está corrompida dentro do "
                                     f"zip (CRC32 ou dados): {exc}") from exc
        if publicado and publicado != md5_entrada:
            raise ImportacaoRecusada(
                f"A planilha {info.filename} não confere com o md5 publicado no próprio zip "
                f"({publicado} × {md5_entrada}): arquivo corrompido ou alterado.")
        from openpyxl import load_workbook
        with z.open(info) as f:
            try:
                wb = load_workbook(f, read_only=True, data_only=True)
            except Exception as exc:  # noqa: BLE001 — qualquer falha de leitura = recusa clara
                raise ImportacaoRecusada(f"Não consegui abrir {info.filename} como planilha "
                                         "XLSX.") from exc
            try:
                por_escola = _ideb_por_escola(wb)
                if por_escola:
                    aba, linhas = ideb.linhas_da_planilha(wb)
                    leitura = ideb.ler_grade(linhas, codigo_ibge=codigo, nome=info.filename,
                                             progresso=progresso)
                else:
                    aba, linhas = ideb_territorio.linhas_da_planilha(wb)
                    leitura = ideb_territorio.ler_grade(linhas, codigo_ibge=codigo,
                                                        nome=info.filename, progresso=progresso)
            finally:
                wb.close()
    if not leitura.recorte:
        if por_escola:
            raise ImportacaoRecusada(
                f"Nada a importar: nenhuma escola da rede MUNICIPAL do município {codigo} em "
                f"{info.filename} ({leitura.linhas_lidas} escolas lidas). Nenhum pacote foi "
                "gerado.")
        raise ImportacaoRecusada(
            f"Nada a importar: nenhuma linha do território {leitura.alvo} em {info.filename} "
            f"({leitura.linhas_lidas} linhas lidas). Nenhum pacote foi gerado.")
    origem = {"modo": "zip_local", "arquivo_nome": caminho.name, "url": url or None,
              "last_modified": last_modified or None, "baixado_em": baixado_em or None,
              "zip_bytes": caminho.stat().st_size, "zip_sha256": _sha256_arquivo(caminho)}
    entrada = {"nome": info.filename, "bytes": info.file_size,
               "bytes_comprimidos": info.compress_size, "crc32": f"{info.CRC:08x}",
               "data_interna": datetime(*info.date_time).isoformat(), "sha256": sha_entrada,
               "md5": md5_entrada,
               "md5_publicado": "confere" if publicado else "ausente no zip", "aba": aba}
    avisos = list(leitura.avisos)
    if not publicado:
        avisos.append(f"O zip não traz o md5 de {info.filename} (md5_*.txt): integridade "
                      "conferida só pelo CRC32.")
    if por_escola:
        dados, manifesto = pacote_ideb.montar_pacote(leitura, codigo_ibge=codigo, origem=origem,
                                                     entrada=entrada, gerado_em=agora,
                                                     avisos=avisos)
        nome = f"pacote_ideb_escolas_{leitura.edicao_arquivo}_{codigo}.zip"
    else:
        dados, manifesto = pacote_ideb.montar_pacote_territorio(
            leitura, codigo_ibge=codigo, origem=origem, entrada=entrada, gerado_em=agora,
            avisos=avisos)
        nome = f"pacote_ideb_{leitura.abrangencia}_{leitura.edicao_arquivo}_{codigo}.zip"
    return PreparoIdeb(pacote=dados, manifesto=manifesto, nome=nome, leitura=leitura,
                       segundos=time.perf_counter() - inicio)


# --- Planilha do Saeb (E7): só arquivo LOCAL ---------------------------------------

@dataclass
class PreparoSaeb:
    """O pacote da planilha do Saeb e o que foi lido para gerá-lo."""

    pacote: bytes
    manifesto: dict
    nome: str
    leitura: saeb_planilha.LeituraSaeb
    segundos: float = 0.0


def planilha_do_saeb(caminho: str | Path) -> bool:
    """O arquivo LOCAL é uma planilha .xlsx com o cabeçalho técnico do Saeb (pelo
    CONTEÚDO das abas, não pelo nome)?"""
    try:
        with zipfile.ZipFile(caminho) as z:
            if planilha_extraida(z.namelist()) != "xlsx":
                return False
        from openpyxl import load_workbook
        wb = load_workbook(caminho, read_only=True, data_only=True)
    except Exception:  # noqa: BLE001 — não é zip/xlsx legível: não é a planilha do Saeb
        return False
    try:
        return saeb_planilha.parece_planilha_saeb(wb)
    finally:
        wb.close()


def preparar_saeb(*, codigo_ibge: str, planilha: str | Path, url: str | None = None,
                  last_modified: str | None = None, baixado_em: str | None = None,
                  edicao: int | None = None, agora: datetime | None = None,
                  progresso: Callable[[str, int], None] | None = None) -> PreparoSaeb:
    """Gera o pacote da planilha do Saeb a partir do .xlsx LOCAL do INEP (``url``,
    ``last_modified`` e ``baixado_em`` só registram a origem; ``edicao`` só quando a
    planilha não traz ANO_SAEB nem o ano no nome). LEVANTA ``ImportacaoRecusada``."""
    inicio = time.perf_counter()
    codigo = ica.normalizar_codigo_ibge(codigo_ibge)
    if codigo is None:
        raise ImportacaoRecusada("Código IBGE do município inválido (são 7 dígitos; "
                                 "Caraguatatuba = 3510500).")
    caminho = Path(planilha)
    if not caminho.is_file():
        raise ImportacaoRecusada(f"A planilha {caminho} não existe (a do Saeb só é lida LOCAL).")
    try:
        with zipfile.ZipFile(caminho) as z:
            e_xlsx = planilha_extraida(z.namelist()) == "xlsx"
    except zipfile.BadZipFile:
        e_xlsx = False
    if not e_xlsx:
        raise ImportacaoRecusada(f"{caminho.name} não é uma planilha .xlsx.")
    from openpyxl import load_workbook
    try:
        wb = load_workbook(caminho, read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 — qualquer falha de leitura = recusa clara
        raise ImportacaoRecusada(f"Não consegui abrir {caminho.name} como planilha XLSX.") from exc
    try:
        abas, ignoradas = saeb_planilha.abas_da_planilha(wb, codigo_ibge=codigo,
                                                         progresso=progresso)
    finally:
        wb.close()
    leitura = saeb_planilha.consolidar(abas, nome=caminho.name, edicao_informada=edicao,
                                       abas_ignoradas=ignoradas)
    data = ica.data_interna(caminho)
    sha = _sha256_arquivo(caminho)
    tamanho = caminho.stat().st_size
    origem = {"modo": "planilha_local", "arquivo_nome": caminho.name, "url": url or None,
              "last_modified": last_modified or None, "baixado_em": baixado_em or None,
              "bytes": tamanho, "sha256": sha}
    entrada = {"nome": caminho.name, "bytes": tamanho, "sha256": sha,
               "data_interna": data.isoformat() if data else None}
    avisos = list(leitura.avisos)
    if data is None:
        avisos.append(ica.AVISO_SEM_DATA)
    dados, manifesto = pacote_saeb.montar_pacote(leitura, codigo_ibge=codigo, origem=origem,
                                                 entrada=entrada, edicao_informada=edicao,
                                                 gerado_em=agora, avisos=avisos)
    tem_tx = any(c.indicador == saeb_planilha.IND_TX_ALFABETIZADO
                 for a in leitura.abas for c in a.colunas)
    rotulo = "tx_alfabetizado" if tem_tx else "resultados"
    return PreparoSaeb(pacote=dados, manifesto=manifesto,
                       nome=f"pacote_saeb_{leitura.edicao_arquivo}_{rotulo}_{codigo}.zip",
                       leitura=leitura, segundos=time.perf_counter() - inicio)


# --- Origem pelo MANIFESTO.json do download ------------------------------------------

def origem_do_manifesto(arquivo: str | Path, manifesto: str | Path) -> dict | None:
    """URL, Last-Modified e data do download do ``arquivo`` registrados no
    MANIFESTO.json da pasta de download (lista de ``{"arquivo", "url",
    "last_modified", "baixado_em", "sha256", "ok"}``) — None se o MANIFESTO não
    registra o arquivo. O sha256 do registro tem de ser o do arquivo (outro arquivo com
    o mesmo nome = recusa). LEVANTA ``ImportacaoRecusada``."""
    caminho = Path(arquivo)
    try:
        registros = json.loads(Path(manifesto).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ImportacaoRecusada(f"Não consegui ler o MANIFESTO {manifesto}.") from exc
    if isinstance(registros, dict):
        registros = [registros]
    if not isinstance(registros, list):
        raise ImportacaoRecusada(f"O MANIFESTO {manifesto} não é uma lista de arquivos.")
    achados = [r for r in registros if isinstance(r, dict) and r.get("arquivo") == caminho.name]
    if not achados:
        return None
    if len(achados) > 1:
        raise ImportacaoRecusada(
            f"O MANIFESTO {Path(manifesto).name} registra {caminho.name} mais de uma vez.")
    registro = achados[0]
    if registro.get("ok") is False:
        raise ImportacaoRecusada(f"O MANIFESTO registra o download de {caminho.name} como falho.")
    sha = registro.get("sha256")
    if isinstance(sha, str) and sha.lower() != _sha256_arquivo(caminho):
        raise ImportacaoRecusada(
            f"O sha256 de {caminho.name} não é o registrado no MANIFESTO (o arquivo não é o "
            "baixado). Nenhum pacote foi gerado.")
    return {k: registro.get(k) if isinstance(registro.get(k), str) else None
            for k in ("url", "last_modified", "baixado_em")}


def pico_de_memoria_mb() -> float | None:
    """Pico de memória do processo (MB), quando o sistema informa (Windows/Unix)."""
    try:
        import resource
        pico = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return pico / 1024 / (1024 if sys.platform == "darwin" else 1)
    except ImportError:
        pass
    try:
        import ctypes
        from ctypes import wintypes

        class _Contadores(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

        contadores = _Contadores()
        contadores.cb = ctypes.sizeof(contadores)
        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        consultar = kernel32.K32GetProcessMemoryInfo
        consultar.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Contadores), wintypes.DWORD]
        consultar.restype = wintypes.BOOL
        if consultar(kernel32.GetCurrentProcess(), ctypes.byref(contadores), contadores.cb):
            return contadores.PeakWorkingSetSize / 1024 / 1024
    except (AttributeError, OSError, ValueError):
        pass
    return None


def _resumo_ideb(preparo: PreparoIdeb, destino: Path) -> list[str]:
    m, leitura = preparo.manifesto, preparo.leitura
    if m["parser"] != ideb.PARSER:
        return _resumo_ideb_territorio(preparo, destino)
    o, e = m["origem"], m["entrada"]
    linhas = [f"Pacote: {destino} ({len(preparo.pacote)} bytes, sha256 "
              f"{hashlib.sha256(preparo.pacote).hexdigest()})",
              f"Ideb por escola · município {m['codigo_territorio_alvo']} "
              f"({leitura.municipio_nome or 'nome não informado'}) · parser {m['parser']} "
              f"v{m['parser_versao']}",
              f"Edições: {', '.join(map(str, m['edicoes']))} · metas: "
              f"{', '.join(map(str, m['anos_meta'])) or 'nenhuma'}",
              f"Origem: {o.get('url') or o.get('arquivo_nome')} ({o.get('zip_bytes')} bytes, sha256 "
              f"{o.get('zip_sha256')}) · Last-Modified: {o.get('last_modified') or 'não informado'}",
              f"  {e['nome']}: {e['bytes']} bytes, CRC32 {e['crc32']} conferido, md5 "
              f"{e['md5']} ({e['md5_publicado']}), aba “{e['aba']}”, data interna "
              f"{e['data_interna']}",
              f"  {e['linhas_original']} escola(s) lidas; {e['linhas_recorte']} da rede municipal "
              f"no recorte; {e['escolas_outras_redes']} do município em outra rede (ignoradas)"]
    for ano, (ideb_n, saeb_n) in ideb.cobertura_do_recorte(leitura).items():
        linhas.append(f"    {ano}: Ideb em {ideb_n} e Saeb em {saeb_n} de "
                      f"{len(leitura.escolas)} escola(s) do recorte")
    pico = pico_de_memoria_mb()
    linhas.append(f"Tempo: {preparo.segundos:.1f} s"
                  + (f" · pico de memória do processo: {pico:.0f} MB" if pico else ""))
    for aviso in m.get("avisos_preparo") or []:
        linhas.append(f"  Aviso: {aviso}")
    return linhas


def _resumo_ideb_territorio(preparo: PreparoIdeb, destino: Path) -> list[str]:
    m, leitura = preparo.manifesto, preparo.leitura
    o, e = m["origem"], m["entrada"]
    linhas = [f"Pacote: {destino} ({len(preparo.pacote)} bytes, sha256 "
              f"{hashlib.sha256(preparo.pacote).hexdigest()})",
              f"Ideb · {leitura.abrangencia} {leitura.alvo} "
              f"({leitura.nome_territorio or 'nome não informado'}) · parser {m['parser']} "
              f"v{m['parser_versao']}",
              f"Edições: {', '.join(map(str, m['edicoes']))} · metas: "
              f"{', '.join(map(str, m['anos_meta'])) or 'nenhuma'}",
              f"Origem: {o.get('url') or o.get('arquivo_nome')} ({o.get('zip_bytes')} bytes, sha256 "
              f"{o.get('zip_sha256')}) · Last-Modified: {o.get('last_modified') or 'não informado'}",
              f"  {e['nome']}: {e['bytes']} bytes, CRC32 {e['crc32']} conferido, md5 "
              f"{e['md5']} ({e['md5_publicado']}), aba “{e['aba']}”, data interna "
              f"{e['data_interna']}",
              f"  {e['linhas_original']} linha(s) lidas; {e['linhas_recorte']} do território no "
              f"recorte: {', '.join(e.get('redes_no_recorte') or [])}"]
    pico = pico_de_memoria_mb()
    linhas.append(f"Tempo: {preparo.segundos:.1f} s"
                  + (f" · pico de memória do processo: {pico:.0f} MB" if pico else ""))
    for aviso in m.get("avisos_preparo") or []:
        linhas.append(f"  Aviso: {aviso}")
    return linhas


def _resumo_saeb(preparo: PreparoSaeb, destino: Path) -> list[str]:
    m = preparo.manifesto
    o, e = m["origem"], m["entrada"]
    de_onde = {"coluna": "pela coluna ANO_SAEB", "nome": "pelo nome do arquivo",
               "informada": "informada"}.get(m["origem_edicao"], m["origem_edicao"])
    linhas = [f"Pacote: {destino} ({len(preparo.pacote)} bytes, sha256 "
              f"{hashlib.sha256(preparo.pacote).hexdigest()})",
              f"Planilha do Saeb · edição {m['edicao']} ({de_onde}) · município "
              f"{m['codigo_territorio_alvo']} · parser {m['parser']} v{m['parser_versao']}",
              f"Origem: {o.get('url') or o.get('arquivo_nome')} ({o.get('bytes')} bytes, sha256 "
              f"{o.get('sha256')}) · Last-Modified: {o.get('last_modified') or 'não informado'} "
              f"· data interna {e.get('data_interna') or 'ausente'}",
              f"  abas ignoradas: {', '.join(e.get('abas_ignoradas') or []) or 'nenhuma'} · níveis "
              f"em {e.get('escala_niveis') or '—'}"]
    for a in m["abas"]:
        linhas.append(f"  aba “{a['aba']}” ({a['tipo']} {a['territorio']}): {a['linhas_original']} "
                      f"linha(s) lidas; {a['linhas_recorte']} do território no recorte")
    pico = pico_de_memoria_mb()
    linhas.append(f"Tempo: {preparo.segundos:.1f} s"
                  + (f" · pico de memória do processo: {pico:.0f} MB" if pico else ""))
    for aviso in m.get("avisos_preparo") or []:
        linhas.append(f"  Aviso: {aviso}")
    return linhas


def _numero(v: float | None) -> str:
    return "sem resultado" if v is None else f"{v:.2f}".replace(".", ",")


def _resumo(preparo: Preparo, destino: Path) -> list[str]:
    m = preparo.manifesto
    linhas = [f"Pacote: {destino} ({len(preparo.pacote)} bytes, sha256 "
              f"{hashlib.sha256(preparo.pacote).hexdigest()})",
              f"Edição {m['edicao']} · município {m['codigo_territorio_alvo']} · parser "
              f"{m['parser']} v{m['parser_versao']}",
              f"Origem: {m['origem'].get('url') or m['origem'].get('arquivo_nome')} · "
              f"Last-Modified: {m['origem'].get('last_modified') or 'não informado'} · "
              f"{preparo.bytes_lidos} bytes lidos de {m['origem'].get('zip_bytes')}"]
    for e in m["entradas"]:
        linhas.append(f"  {e['nome']}: CRC32 {e['crc32']} conferido, {e['bytes']} bytes, "
                      f"data interna {e['data_interna'] or '—'}, {e['linhas_recorte']} de "
                      f"{e['linhas_original']} linha(s) no recorte")
    for leitura in preparo.leituras:
        for ln in leitura.linhas:
            nivel = f" nível {ln.nivel}" if ln.nivel else ""
            linhas.append(f"    {ln.abrangencia} {ln.codigo_territorio} ({ln.rede_ensino}) "
                          f"{ln.indicador}{nivel} {ln.edicao}: {_numero(ln.valor)}")
    for aviso in m.get("avisos_preparo") or []:
        linhas.append(f"  Aviso: {aviso}")
    return linhas


def _raiz_do_repositorio() -> Path | None:
    """A raiz do checkout deste código (backend/app/services/indicadores/preparar.py →
    5 níveis acima): é ELE o repositório público em que o pacote não pode cair."""
    pais = Path(__file__).resolve().parents
    return pais[4] if len(pais) > 4 else None


def dentro_do_repositorio(pasta: Path, raiz: Path | None = None) -> bool:
    """A pasta fica dentro do checkout do Constela (a raiz com ``.git``, pasta ou
    arquivo de worktree)? Outro repositório git qualquer acima dela não conta."""
    raiz = raiz or _raiz_do_repositorio()
    if raiz is None:
        return False
    try:
        if not (raiz / ".git").exists():
            return False
        pasta.resolve().relative_to(raiz.resolve())
    except (ValueError, OSError):
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.services.indicadores.preparar",
        description="Gera, NESTA máquina, o pacote recortado de um arquivo grande do INEP: "
                    "(1) as tabelas agregadas TS_MUNICIPIO e TS_ESTADO dos microdados da "
                    "avaliação da alfabetização, para a importação do ICA; (2) o Ideb dos anos "
                    "iniciais — por escola, por município, de UF/regiões ou de Brasil "
                    "(divulgacao_*_AAAA.zip) —, para a importação do Ideb/Saeb; ou (3) a "
                    "planilha do Saeb por Brasil, estados e municípios (--planilha), para a "
                    "importação do Saeb — detectados pelo CONTEÚDO do arquivo.")
    parser.add_argument("--ibge", required=True, help="código IBGE do município (7 dígitos)")
    parser.add_argument("--zip", dest="zip_local",
                        help="zip já baixado: o dos microdados OU um zip do Ideb (por escola, "
                             "município, UF/regiões ou Brasil; o do Ideb SÓ é aceito assim, "
                             "local)")
    parser.add_argument("--url",
                        help="sem --zip: URL do zip dos MICRODADOS no INEP, lida por HTTP Range "
                             "(só as tabelas agregadas). O zip do Ideb NÃO é lido por URL: o "
                             "xlsx dele tem dezenas de MB comprimidos e exigiria baixar a "
                             "entrada inteira — baixe o zip e use --zip. Com --zip, a URL só "
                             "registra a origem no manifesto")
    parser.add_argument("--last-modified",
                        help="Last-Modified do arquivo (só com --zip ou --planilha)")
    parser.add_argument("--planilha",
                        help="planilha .xlsx do Saeb (Brasil, estados e municípios), já baixada "
                             "— lida LOCAL, em streaming (a de 2025 tem ~150 MB de XML)")
    parser.add_argument("--manifesto",
                        help="MANIFESTO.json do download (URL, Last-Modified, data e sha256 de "
                             "cada arquivo baixado); sem ele, o da pasta do arquivo, se existir")
    parser.add_argument("--edicao", type=int,
                        help="edição do Saeb, só quando a planilha não traz ANO_SAEB nem o ano "
                             "no nome")
    parser.add_argument("--saida", default=".",
                        help="pasta onde gravar o pacote (padrão: a atual; prefira uma pasta "
                             "fora do repositório — dentro dele, o comando avisa)")
    args = parser.parse_args(argv)
    for fluxo in (sys.stdout, sys.stderr):    # console Windows (cp1252) não quebra com "≠"
        try:
            fluxo.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    resumir: Callable[[Path], list[str]]
    try:
        local = args.planilha or args.zip_local
        url, last_modified, baixado_em = args.url, args.last_modified, None
        manifesto, explicito = args.manifesto, args.manifesto is not None
        if local and manifesto is None and (Path(local).parent / "MANIFESTO.json").is_file():
            manifesto = str(Path(local).parent / "MANIFESTO.json")
        registro = origem_do_manifesto(local, manifesto) if local and manifesto else None
        if registro is None and explicito:
            raise ImportacaoRecusada(f"O MANIFESTO {manifesto} não registra "
                                     f"{Path(local or '').name}.")
        if registro is not None:
            for informado, do_manifesto, rotulo in ((url, registro["url"], "--url"),
                                                    (last_modified, registro["last_modified"],
                                                     "--last-modified")):
                if informado and do_manifesto and informado != do_manifesto:
                    raise ImportacaoRecusada(f"{rotulo} informado diverge do MANIFESTO "
                                             f"({informado} × {do_manifesto}).")
            url = url or registro["url"]
            last_modified = last_modified or registro["last_modified"]
            baixado_em = registro["baixado_em"]
            print(f"Origem registrada no MANIFESTO {manifesto} (sha256 conferido).",
                  file=sys.stderr)
        e_saeb = bool(args.planilha) or bool(args.zip_local and not zip_do_ideb(args.zip_local)
                                             and planilha_do_saeb(args.zip_local))
        if e_saeb:
            print(f"Planilha do Saeb: lendo {local} em streaming (alguns minutos)...",
                  file=sys.stderr)
            preparo = preparar_saeb(
                codigo_ibge=args.ibge, planilha=local, url=url, last_modified=last_modified,
                baixado_em=baixado_em, edicao=args.edicao,
                progresso=lambda aba, n: print(f"  {aba}: {n} linhas lidas", file=sys.stderr,
                                               flush=True))
            resumir = lambda destino: _resumo_saeb(preparo, destino)  # noqa: E731
        elif args.zip_local and zip_do_ideb(args.zip_local):
            print(f"Ideb: lendo {args.zip_local} em streaming (alguns minutos)...",
                  file=sys.stderr)
            preparo = preparar_ideb(
                codigo_ibge=args.ibge, zip_local=args.zip_local, url=url,
                last_modified=last_modified, baixado_em=baixado_em,
                progresso=lambda n: print(f"  {n} linhas lidas", file=sys.stderr, flush=True))
            resumir = lambda destino: _resumo_ideb(preparo, destino)  # noqa: E731
        else:
            preparo = preparar(codigo_ibge=args.ibge, zip_local=args.zip_local, url=url,
                               last_modified=last_modified)
            resumir = lambda destino: _resumo(preparo, destino)  # noqa: E731
    except (ImportacaoRecusada, ValueError, OSError) as exc:
        print(f"Recusado: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 — erro de rede/TLS: mensagem, sem traceback
        print(f"Falhou: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    pasta = Path(args.saida)
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / preparo.nome
    destino.write_bytes(preparo.pacote)
    for linha in resumir(destino):
        print(linha)
    if dentro_do_repositorio(pasta):
        print(f"Aviso: o pacote foi gravado DENTRO do repositório ({destino}). Ele é recorte "
              "de arquivo oficial do INEP (CC BY-ND) e não pode ir para o repositório público "
              "(D13): o .gitignore barra pacote_*.zip, mas mova-o para uma pasta fora do "
              "repositório (ou use --saida).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
