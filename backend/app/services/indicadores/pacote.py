"""PACOTE RECORTADO dos microdados agregados do INEP (TS_MUNICIPIO e TS_ESTADO).

Quem gera é a linha de comando ``preparar`` (nesta máquina, a partir do zip local
ou da URL lida por HTTP Range). Quem recebe é a MESMA prévia/aplicação da E2: o
pacote sobe pela tela como a planilha, e o servidor refaz a validação.

O pacote é um .zip de poucos KB com:

* ``manifesto.json`` — tipo e formato, parser e versão, o município-alvo, a edição,
  a ORIGEM (URL do zip do INEP, Last-Modified e ETag do servidor, tamanho do zip,
  sha256 do zip quando ele foi lido local, bytes buscados pela rede) e, por ENTRADA
  original: nome no zip, CRC32 conferido, bytes, data interna, sha256 da entrada, o
  CSV recortado com o sha256 dele e as contagens de linhas;
* ``TS_MUNICIPIO.csv`` e ``TS_ESTADO.csv`` — o RECORTE CANÔNICO: UTF-8, ``;``, fim
  de linha LF, as colunas conhecidas com o nome oficial e SÓ as linhas que o parser
  usa (o município na rede municipal; a UF nas redes municipal e pública), com os
  valores COMO o INEP os escreveu (nada recalculado).

No servidor, ``ler_pacote`` RECUSA o pacote (nada é gravado) se: não for deste
formato/parser/versão; for recortado para outro município; tiver arquivo a mais
ou a menos; alguma entrada estiver corrompida ou cifrada; o sha256 de algum CSV
não bater com o do manifesto (pacote alterado depois de gerado); alguma tabela vier
sem nenhuma linha (o ``preparar`` deixa fora do pacote a tabela em que o município
não tem linha da rede); o CSV não passar no MESMO parser da linha de comando (faixas,
códigos, série, rede, ano, recusa de aluno); ou trouxer linha que o parser não usa
(não é um recorte do ``preparar``). Sem assinatura digital — o manifesto confere a
INTEGRIDADE (alteração acidental ou manual do CSV), não a autoria: importar é ato
do admin global, que gera o pacote nesta máquina.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.services.avaliacoes import ImportacaoRecusada
from app.services.indicadores import aeeb, ica
from app.services.indicadores.zip_parcial import Entrada

TIPO = "pacote_indicadores"
FORMATO = 1
NOME_MANIFESTO = "manifesto.json"
MAX_PACOTE = 2 * 1024 * 1024          # o real tem ~3 KB
_MAX_MANIFESTO = 256 * 1024
_MAX_CSV = 512 * 1024
_RE_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RE_CRC = re.compile(r"^[0-9a-f]{8}$")

# Ordem canônica das colunas no recorte (só as que o original tiver).
_NIVEIS = [f"PC_ALUNO_NIVEL_{k}_LP" for k in aeeb.NIVEIS]
COLUNAS = {
    aeeb.TABELA_MUNICIPIO: ["NU_ANO_AVALIACAO", "CO_UF", "SG_UF", "CO_MUNICIPIO",
                            "NO_MUNICIPIO", "TP_SERIE", "ID_TIPO_REDE",
                            "PC_ALUNO_ALFABETIZADO", "VL_MEDIA_LP", *_NIVEIS],
    aeeb.TABELA_ESTADO: ["NU_ANO_AVALIACAO", "CO_UF", "SG_UF", "TP_SERIE", "ID_TIPO_REDE",
                         "PC_ALUNO_ALFABETIZADO", "VL_MEDIA_LP", *_NIVEIS],
}
AVISO_LICENCA = ("Recorte de dado público do Inep para uso interno do Constela (citar a "
                 "fonte). Não redistribuir: o portal gov.br aplica a licença CC BY-ND 3.0.")


def _recusa(texto: str) -> ImportacaoRecusada:
    return ImportacaoRecusada(f"Pacote recusado: {texto} Nada foi gravado.")


def _sha256(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


def _iso(quando: datetime | None) -> str | None:
    return quando.isoformat() if quando else None


# --- Montagem (linha de comando) ---------------------------------------------------

def csv_canonico(leitura: aeeb.LeituraAEEB) -> bytes:
    """O recorte de UMA tabela: as colunas conhecidas, só as linhas usadas, os
    valores como o INEP escreveu. UTF-8 e LF (os bytes são os mesmos em qualquer
    sistema — é deles o sha256 do manifesto)."""
    presentes = [c for c in COLUNAS[leitura.tabela] if c in leitura.cabecalho]
    indice = {c: leitura.cabecalho.index(c) for c in presentes}
    buf = io.StringIO()
    escritor = csv.writer(buf, delimiter=";", lineterminator="\n")
    escritor.writerow(presentes)
    for linha in leitura.linhas_usadas:
        escritor.writerow([linha[indice[c]].strip() for c in presentes])
    return buf.getvalue().encode("utf-8")


def montar_pacote(lidas: list[tuple[Entrada, bytes, aeeb.LeituraAEEB]], *, codigo_ibge: str,
                  origem: dict, gerado_em: datetime | None = None,
                  avisos: list[str] | None = None) -> tuple[bytes, dict]:
    """``(bytes do .zip, manifesto)``. ``lidas`` = (entrada do zip original, bytes
    descomprimidos — CRC já conferido —, leitura do parser) de cada tabela."""
    if not lidas:
        raise ImportacaoRecusada("Nenhuma tabela agregada para empacotar.")
    edicoes = {leitura.edicao_arquivo for _, _, leitura in lidas}
    if len(edicoes) != 1:
        raise ImportacaoRecusada(
            f"As tabelas são de anos diferentes ({', '.join(map(str, sorted(edicoes)))}): um "
            "pacote é de uma edição só.")
    tabelas = [leitura.tabela for _, _, leitura in lidas]
    if len(set(tabelas)) != len(tabelas):
        raise ImportacaoRecusada("O zip tem a mesma tabela agregada mais de uma vez.")
    # Recorte só com o cabeçalho o servidor recusa (e levaria junto a outra tabela):
    # o ``preparar`` deixa fora do pacote a tabela sem linha da rede.
    vazias = [leitura.tabela for _, _, leitura in lidas if not leitura.linhas_usadas]
    if vazias:
        raise ImportacaoRecusada(
            f"{', '.join(vazias)} sem nenhuma linha da rede: essa tabela não entra no pacote.")
    gerado_em = gerado_em or datetime.now(timezone.utc)
    gerado_em = (gerado_em.replace(tzinfo=timezone.utc) if gerado_em.tzinfo is None   # sem fuso = UTC
                 else gerado_em.astimezone(timezone.utc))
    arquivos: dict[str, bytes] = {}
    entradas = []
    for entrada, original, leitura in sorted(lidas, key=lambda t: aeeb.TABELAS.index(t[2].tabela)):
        nome_csv = f"{leitura.tabela}.csv"
        recorte = csv_canonico(leitura)
        arquivos[nome_csv] = recorte
        entradas.append({
            "tabela": leitura.tabela, "nome": entrada.nome, "crc32": entrada.crc32_hex,
            "bytes": entrada.bytes, "bytes_comprimidos": entrada.bytes_comprimidos,
            "data_interna": _iso(entrada.data_interna), "sha256": _sha256(original),
            "linhas_original": leitura.linhas_lidas,
            "csv": nome_csv, "csv_sha256": _sha256(recorte),
            "linhas_recorte": len(leitura.linhas_usadas),
        })
    manifesto = {
        "tipo": TIPO, "formato": FORMATO, "parser": aeeb.PARSER,
        "parser_versao": aeeb.VERSAO_PARSER,
        "gerado_em": gerado_em.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "gerado_por": "python -m app.services.indicadores.preparar",
        "codigo_territorio_alvo": codigo_ibge, "codigo_uf": codigo_ibge[:2],
        "edicao": next(iter(edicoes)), "origem": origem, "entradas": entradas,
        "avisos_preparo": list(avisos or []), "licenca": AVISO_LICENCA,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        def gravar(nome: str, dados: bytes) -> None:
            info = zipfile.ZipInfo(nome, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, dados)
        gravar(NOME_MANIFESTO, json.dumps(manifesto, ensure_ascii=False, indent=2).encode("utf-8"))
        for nome, dados in arquivos.items():
            gravar(nome, dados)
    return buf.getvalue(), manifesto


# --- Leitura (servidor) ------------------------------------------------------------

def eh_pacote(conteudo: bytes) -> bool:
    """Um .zip com ``manifesto.json`` na raiz (e que não é uma planilha XLSX)."""
    if not conteudo.startswith(b"PK"):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
            nomes = set(z.namelist())
    except zipfile.BadZipFile:
        return False
    return NOME_MANIFESTO in nomes and "[Content_Types].xml" not in nomes


def zip_com_entrada_de_aluno(conteudo: bytes) -> str | None:
    """O nome da entrada de aluno, se o upload for um zip dos microdados INTEIRO
    (com o TS_ALUNO dentro) — só o diretório é olhado, a entrada não é lida."""
    if not conteudo.startswith(b"PK"):
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
            return next((n for n in z.namelist() if aeeb.nome_de_aluno(n)), None)
    except zipfile.BadZipFile:
        return None


@dataclass
class PacoteLido:
    """O que o servidor entendeu do pacote: a leitura (pelo MESMO parser) e os
    campos de proveniência da importação."""

    leitura: ica.LeituraICA
    manifesto: dict
    meta: dict = field(default_factory=dict)


def _texto(valor, nome: str, maximo: int, obrigatorio: bool = True) -> str | None:
    if valor is None and not obrigatorio:
        return None
    if not isinstance(valor, str) or not valor.strip() or len(valor) > maximo:
        raise _recusa(f"o campo “{nome}” do manifesto é inválido.")
    return valor.strip()


def _data(valor, nome: str) -> datetime | None:
    if valor in (None, ""):
        return None
    try:
        quando = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError as exc:
        raise _recusa(f"a data “{nome}” do manifesto é inválida.") from exc
    if quando.tzinfo is not None:
        quando = quando.astimezone(timezone.utc).replace(tzinfo=None)
    return quando


def _ler_do_pacote(z: zipfile.ZipFile, info: zipfile.ZipInfo, maximo: int) -> bytes:
    # Entrada cifrada (RuntimeError) ou com método de compressão que o zipfile não
    # lê (NotImplementedError) também é recusa limpa (400), não erro 500 — o
    # ``preparar`` só grava entradas DEFLATE sem senha. Descomprime no máximo
    # ``maximo`` (o tamanho declarado no zip não limita a memória: ``ica.ler_do_zip``).
    try:
        return ica.ler_do_zip(z, info, maximo)    # o zipfile confere o CRC32
    except (zipfile.BadZipFile, zlib.error, EOFError, RuntimeError, NotImplementedError,
            ValueError) as exc:
        raise _recusa(f"o arquivo {info.filename} do pacote está corrompido, cifrado ou "
                      "num formato de compressão que o preparar não gera.") from exc


def _manifesto(z: zipfile.ZipFile) -> dict:
    try:
        info = z.getinfo(NOME_MANIFESTO)
    except KeyError as exc:
        raise _recusa("falta o manifesto.json.") from exc
    if info.file_size > _MAX_MANIFESTO:
        raise _recusa("o manifesto é grande demais.")
    try:
        manifesto = json.loads(_ler_do_pacote(z, info, _MAX_MANIFESTO).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _recusa("o manifesto.json não é um JSON válido.") from exc
    if not isinstance(manifesto, dict) or manifesto.get("tipo") != TIPO:
        raise _recusa("o arquivo não é um pacote de indicadores do Constela.")
    if manifesto.get("formato") != FORMATO:
        raise _recusa(f"formato de pacote {manifesto.get('formato')!r} desconhecido (este "
                      f"servidor lê o formato {FORMATO}). Gere o pacote de novo.")
    if manifesto.get("parser") != aeeb.PARSER:
        raise _recusa(f"o pacote é do parser {manifesto.get('parser')!r}; esta importação lê "
                      f"{aeeb.PARSER} (microdados agregados do INEP).")
    if manifesto.get("parser_versao") != aeeb.VERSAO_PARSER:
        raise _recusa(f"o pacote foi gerado pela versão {manifesto.get('parser_versao')!r} do "
                      f"parser; o servidor está na {aeeb.VERSAO_PARSER}. Gere o pacote de novo "
                      "com o código atual.")
    return manifesto


def ler_pacote(conteudo: bytes, nome: str, *, codigo_ibge: str) -> PacoteLido:
    """Abre, confere e lê o pacote (ver o docstring do módulo). LEVANTA
    ``ImportacaoRecusada`` em qualquer divergência."""
    codigo_ibge = ica.normalizar_codigo_ibge(codigo_ibge)
    if codigo_ibge is None:
        raise ImportacaoRecusada("Código IBGE do município inválido (são 7 dígitos).")
    if len(conteudo) > MAX_PACOTE:
        raise _recusa("o arquivo é grande demais para um pacote recortado (o real tem poucos KB).")
    try:
        z = zipfile.ZipFile(io.BytesIO(conteudo))
    except zipfile.BadZipFile as exc:
        raise _recusa("o arquivo não é um .zip válido.") from exc
    with z:
        manifesto = _manifesto(z)
        alvo = _texto(manifesto.get("codigo_territorio_alvo"), "codigo_territorio_alvo", 7)
        if alvo != codigo_ibge:
            raise _recusa(f"ele foi recortado para o município {alvo}, e esta rede é do "
                          f"município {codigo_ibge}. Gere o pacote com --ibge {codigo_ibge}.")
        edicao = manifesto.get("edicao")
        if not isinstance(edicao, int) or not 2000 <= edicao <= 2100:
            raise _recusa("a edição do manifesto é inválida.")
        entradas = manifesto.get("entradas")
        if not isinstance(entradas, list) or not 1 <= len(entradas) <= len(aeeb.TABELAS):
            raise _recusa("a lista de entradas do manifesto é inválida.")
        esperados = {NOME_MANIFESTO}
        leituras: list[aeeb.LeituraAEEB] = []
        datas: list[datetime] = []
        for e in entradas:
            if not isinstance(e, dict):
                raise _recusa("uma entrada do manifesto é inválida.")
            tabela = e.get("tabela")
            nome_original = _texto(e.get("nome"), "nome", 255)
            if tabela not in aeeb.TABELAS or e.get("csv") != f"{tabela}.csv":
                raise _recusa(f"a entrada “{nome_original}” não é TS_MUNICIPIO nem TS_ESTADO.")
            aeeb.recusar_se_for_de_aluno(nome_original)
            for campo, padrao in (("sha256", _RE_SHA256), ("csv_sha256", _RE_SHA256),
                                  ("crc32", _RE_CRC)):
                if not isinstance(e.get(campo), str) or not padrao.match(e[campo]):
                    raise _recusa(f"o {campo} da entrada “{nome_original}” é inválido.")
            nome_csv = e["csv"]
            if nome_csv in esperados:
                raise _recusa(f"a tabela {tabela} aparece duas vezes no manifesto.")
            esperados.add(nome_csv)
            try:
                info = z.getinfo(nome_csv)
            except KeyError as exc:
                raise _recusa(f"falta o arquivo {nome_csv} que o manifesto declara.") from exc
            if info.file_size > _MAX_CSV:
                raise _recusa(f"o {nome_csv} é grande demais para um recorte.")
            recorte = _ler_do_pacote(z, info, _MAX_CSV)
            if _sha256(recorte) != e["csv_sha256"]:
                raise _recusa(f"o {nome_csv} não confere com o manifesto (sha256 diferente): o "
                              "pacote foi alterado depois de gerado. Gere-o de novo com o "
                              "preparar.")
            if e.get("linhas_recorte") == 0:
                raise _recusa(f"o {nome_csv} não tem nenhuma linha da rede (o município não "
                              "tem resultado nessa tabela). Gere o pacote de novo com o "
                              "preparar atual, que deixa essa tabela fora do pacote.")
            leitura = aeeb.ler_tabela_aeeb(recorte, nome_csv, codigo_ibge=codigo_ibge)
            if leitura.tabela != tabela:
                raise _recusa(f"o {nome_csv} tem as colunas de {leitura.tabela}.")
            if leitura.edicao_arquivo != edicao:
                raise _recusa(f"o {nome_csv} é de {leitura.edicao_arquivo}, e o manifesto diz "
                              f"{edicao}.")
            if (leitura.linhas_lidas != len(leitura.linhas_usadas)
                    or leitura.linhas_lidas != e.get("linhas_recorte")):
                raise _recusa(f"o {nome_csv} traz linhas que não são da rede nem da UF dela "
                              "(não é um recorte do preparar).")
            quando = _data(e.get("data_interna"), "data_interna")
            if quando:
                datas.append(quando)
            leituras.append(leitura)
        sobrando = sorted(set(z.namelist()) - esperados)
        if sobrando:
            raise _recusa(f"o pacote traz arquivo(s) que o manifesto não declara "
                          f"({', '.join(sobrando)}).")
    origem = manifesto.get("origem") if isinstance(manifesto.get("origem"), dict) else {}
    url = origem.get("url") if isinstance(origem.get("url"), str) else None
    arquivo_nome = origem.get("arquivo_nome") if isinstance(origem.get("arquivo_nome"), str) else None
    arquivo_nome = (arquivo_nome or (url or "").rstrip("/").rsplit("/", 1)[-1]
                    or nome or "pacote.zip")[:255]
    principal = next((e for e in entradas if e["tabela"] == aeeb.TABELA_MUNICIPIO), entradas[0])
    # Avisos do preparo que o servidor não reproduz sozinho (ex.: linhas de outra
    # série no arquivo inteiro); os que ele reproduz aparecem uma vez só.
    proprios = [a for lt in leituras for a in lt.avisos]
    do_preparo = [a for a in manifesto.get("avisos_preparo") or []
                  if isinstance(a, str) and a.split(": ", 1)[-1] not in proprios]
    leitura = ica.LeituraICA(
        parser=aeeb.PARSER, edicao_arquivo=edicao,
        arquivo_data=max(datas) if datas else None,
        aba=" + ".join(lt.tabela for lt in leituras),
        linhas=[ln for lt in leituras for ln in lt.linhas],
        avisos=[*(f"No preparo: {a}" for a in do_preparo), *proprios],
        territorios={k: v for lt in leituras for k, v in lt.territorios.items()},
        linhas_lidas=sum(lt.linhas_lidas for lt in leituras))
    if leitura.arquivo_data is None:
        leitura.avisos.append(
            "O pacote não traz a data interna das entradas do zip: a importação fica sem "
            "“microdados de <data>”.")
    versao = arquivo_nome.rsplit(".", 1)[0][:60] or None
    meta = {
        "modo": "pacote_cli", "url_origem": url,
        "last_modified_origem": origem.get("last_modified") if isinstance(
            origem.get("last_modified"), str) else None,
        "arquivo_nome": arquivo_nome, "arquivo_sha256": principal["sha256"],
        "arquivo_bytes": principal.get("bytes") if isinstance(principal.get("bytes"), int) else 0,
        "versao_rotulo": versao, "coletado_em": _data(manifesto.get("gerado_em"), "gerado_em"),
        "pacote_sha256": _sha256(conteudo),
    }
    return PacoteLido(leitura=leitura, manifesto=manifesto, meta=meta)
