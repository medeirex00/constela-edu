"""PACOTE RECORTADO do Ideb — por escola (E6a) e do município, da UF e do Brasil (E6b).

Quem gera é a linha de comando ``preparar`` (nesta máquina, a partir do zip LOCAL do
INEP: o xlsx por escola tem ~50 MB comprimidos e não há como ler só as linhas da rede
por HTTP Range; o de municípios, ~12 MB). Quem recebe é a prévia/aplicação/desfazer do
fluxo de famílias (``pipeline_seduc`` com a família do Ideb, em ``pipeline_ideb``); o
servidor refaz a validação com o MESMO parser (``ideb.ler_grade`` por escola,
``ideb_territorio.ler_grade`` no território) e nunca abre o arquivo do INEP.

O pacote é um .zip de poucos KB com:

* ``manifesto.json`` — tipo e formato, parser e versão, o município-alvo, a edição
  mais nova e TODAS as edições encontradas (e os anos das metas), a ORIGEM (nome,
  bytes e sha256 do zip do INEP; URL, Last-Modified e data do download quando
  informados — o ``preparar`` os lê do MANIFESTO.json do download) e a ENTRADA lida
  (nome no zip, bytes, CRC32, data interna, sha256 e md5 — conferido com o
  ``md5_*.txt`` que o próprio INEP põe no zip —, a aba, as linhas do arquivo e do
  recorte e o sha256 do CSV); no território, também a abrangência (município, UF ou
  Brasil);
* o CSV do RECORTE (``ideb_escolas_recorte.csv``; no território,
  ``ideb_municipio_recorte.csv`` ou ``ideb_uf_brasil_recorte.csv``): UTF-8, ``;``, fim
  de linha LF, as linhas do TOPO da planilha (cabeçalho legível + linha técnica, como
  no arquivo), SÓ as linhas do recorte (por escola: as da rede municipal do
  município; no território: as do município, da UF ou do Brasil, todas as redes — o
  servidor registra as que não grava) e o rodapé (fonte, legenda e notas). Os valores
  vão como o INEP os escreveu (o número como texto, "-", "ND*", a vírgula): nada
  recalculado.

``ler_pacote``/``ler_pacote_territorio`` RECUSAM (nada gravado) se: não for deste
formato/parser/versão; for de outro município; tiver arquivo a mais ou a menos; o CSV
estiver corrompido ou não conferir com o sha256 do manifesto (pacote alterado depois
de gerado); o CSV não passar no parser (layout, etapa, marcadores, faixas); trouxer
linha de fora do recorte (não é um recorte do preparar); ou as edições, as metas, a
abrangência e as contagens não forem as do manifesto. Sem assinatura digital: o
manifesto confere a INTEGRIDADE, não a autoria (importar é ato do admin global).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.services.avaliacoes import ImportacaoRecusada
from app.services.indicadores import ica, ideb, ideb_territorio, pacote

FORMATO = 1
NOME_CSV = "ideb_escolas_recorte.csv"
NOME_CSV_TERRITORIO = {ideb_territorio.PARSER_MUNICIPIOS: "ideb_municipio_recorte.csv",
                       ideb_territorio.PARSER_UF_BRASIL: "ideb_uf_brasil_recorte.csv"}
MAX_PACOTE = 2 * 1024 * 1024        # o de uma rede (todas as edições) tem poucos KB
_MAX_CSV = 2 * 1024 * 1024
_MAX_MANIFESTO = 256 * 1024
_RE_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _recusa(texto: str) -> ImportacaoRecusada:
    return ImportacaoRecusada(f"Pacote do Ideb recusado: {texto} Nada foi gravado.")


def _sha256(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


# --- Montagem (linha de comando) ------------------------------------------------

def _csv(linhas) -> bytes:
    """O recorte em CSV (UTF-8 e LF: os bytes são os mesmos em qualquer sistema — é
    deles o sha256 do manifesto)."""
    buf = io.StringIO()
    escritor = csv.writer(buf, delimiter=";", lineterminator="\n")
    for linha in linhas:
        escritor.writerow(linha)
    return buf.getvalue().encode("utf-8")


def csv_do_recorte(leitura) -> bytes:
    """Topo + linha técnica + linhas do recorte + rodapé, em texto (o mesmo texto que
    o parser lê) — por escola (``ideb.LeituraIdeb``) ou do território
    (``ideb_territorio.LeituraTerritorio``)."""
    return _csv((*leitura.topo, leitura.tecnica, *leitura.recorte, *leitura.notas_linhas))


def _gerado_em(gerado_em: datetime | None) -> str:
    gerado_em = gerado_em or datetime.now(timezone.utc)
    gerado_em = (gerado_em.replace(tzinfo=timezone.utc) if gerado_em.tzinfo is None
                 else gerado_em.astimezone(timezone.utc))
    return gerado_em.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _zip(manifesto: dict, nome_csv: str, recorte: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for nome, dados in ((pacote.NOME_MANIFESTO,
                             json.dumps(manifesto, ensure_ascii=False, indent=2).encode("utf-8")),
                            (nome_csv, recorte)):
            info = zipfile.ZipInfo(nome, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, dados)
    return buf.getvalue()


def montar_pacote(leitura: ideb.LeituraIdeb, *, codigo_ibge: str, origem: dict,
                  entrada: dict, gerado_em: datetime | None = None,
                  avisos: list[str] | None = None) -> tuple[bytes, dict]:
    """``(bytes do .zip, manifesto)`` do Ideb POR ESCOLA. ``origem`` = o zip do INEP;
    ``entrada`` = o xlsx lido dentro dele (nome, bytes, CRC32, data interna, sha256,
    md5, aba)."""
    if not leitura.recorte:
        raise ImportacaoRecusada(
            f"Nenhuma escola da rede municipal do município {codigo_ibge} no arquivo: nenhum "
            "pacote foi gerado.")
    recorte = csv_do_recorte(leitura)
    manifesto = {
        "tipo": pacote.TIPO, "formato": FORMATO, "parser": ideb.PARSER,
        "parser_versao": ideb.VERSAO_PARSER, "gerado_em": _gerado_em(gerado_em),
        "gerado_por": "python -m app.services.indicadores.preparar",
        "codigo_territorio_alvo": codigo_ibge, "codigo_uf": codigo_ibge[:2],
        "edicao": leitura.edicao_arquivo, "edicoes": list(leitura.edicoes),
        "anos_meta": list(leitura.anos_meta), "origem": origem,
        "entrada": {**entrada, "linhas_original": leitura.linhas_lidas,
                    "linhas_recorte": len(leitura.recorte),
                    "escolas_outras_redes": sum(leitura.outras_redes.values()),
                    "csv": NOME_CSV, "csv_sha256": _sha256(recorte)},
        "avisos_preparo": list(avisos or []), "licenca": pacote.AVISO_LICENCA,
    }
    return _zip(manifesto, NOME_CSV, recorte), manifesto


def montar_pacote_territorio(leitura: ideb_territorio.LeituraTerritorio, *, codigo_ibge: str,
                             origem: dict, entrada: dict, gerado_em: datetime | None = None,
                             avisos: list[str] | None = None) -> tuple[bytes, dict]:
    """``(bytes do .zip, manifesto)`` do Ideb do MUNICÍPIO, da UF ou do BRASIL: o topo +
    as linhas do território (todas as redes) + o rodapé."""
    if not leitura.recorte:
        raise ImportacaoRecusada(
            f"Nenhuma linha do território {leitura.alvo} no arquivo: nenhum pacote foi gerado.")
    nome_csv = NOME_CSV_TERRITORIO[leitura.parser]
    recorte = csv_do_recorte(leitura)
    manifesto = {
        "tipo": pacote.TIPO, "formato": FORMATO, "parser": leitura.parser,
        "parser_versao": ideb_territorio.VERSAO_PARSER, "gerado_em": _gerado_em(gerado_em),
        "gerado_por": "python -m app.services.indicadores.preparar",
        "codigo_territorio_alvo": codigo_ibge, "codigo_uf": codigo_ibge[:2],
        "abrangencia": leitura.abrangencia, "territorio": leitura.alvo,
        "edicao": leitura.edicao_arquivo, "edicoes": list(leitura.edicoes),
        "anos_meta": list(leitura.anos_meta), "origem": origem,
        "entrada": {**entrada, "linhas_original": leitura.linhas_lidas,
                    "linhas_recorte": len(leitura.recorte),
                    "redes_no_recorte": [ln.rotulo_rede for ln in leitura.linhas],
                    "csv": nome_csv, "csv_sha256": _sha256(recorte)},
        "avisos_preparo": list(avisos or []), "licenca": pacote.AVISO_LICENCA,
    }
    return _zip(manifesto, nome_csv, recorte), manifesto


# --- Leitura (servidor) -----------------------------------------------------------

def parser_do_pacote(conteudo: bytes) -> str | None:
    """O ``parser`` do manifesto, se o arquivo for um pacote de indicadores (zip com
    ``manifesto.json``); None se não for pacote ou o manifesto não se ler."""
    if not pacote.eh_pacote(conteudo):
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
            info = z.getinfo(pacote.NOME_MANIFESTO)
            if info.file_size > _MAX_MANIFESTO:
                return None
            manifesto = json.loads(ica.ler_do_zip(z, info, _MAX_MANIFESTO).decode("utf-8"))
    except (KeyError, zipfile.BadZipFile, UnicodeDecodeError, ValueError, RuntimeError,
            NotImplementedError, EOFError):
        return None
    parser = manifesto.get("parser") if isinstance(manifesto, dict) else None
    return parser if isinstance(parser, str) else None


@dataclass
class PacoteIdebLido:
    """O que o servidor entendeu do pacote: a leitura (pelo MESMO parser) e os campos
    de proveniência da importação."""

    leitura: object                  # ideb.LeituraIdeb | ideb_territorio.LeituraTerritorio
    manifesto: dict
    meta: dict = field(default_factory=dict)
    avisos_preparo: list[str] = field(default_factory=list)


def _ler(z: zipfile.ZipFile, nome: str, maximo: int) -> bytes:
    try:
        info = z.getinfo(nome)
    except KeyError as exc:
        raise _recusa(f"falta o arquivo {nome}.") from exc
    if info.file_size > maximo:
        raise _recusa(f"o {nome} é grande demais para um recorte.")
    try:
        # Descomprime no máximo ``maximo``: o tamanho declarado no zip não limita a
        # memória (``ica.ler_do_zip``). O zipfile confere o CRC32.
        return ica.ler_do_zip(z, info, maximo)
    except (zipfile.BadZipFile, EOFError, RuntimeError, NotImplementedError, ValueError,
            OSError) as exc:
        raise _recusa(f"o {nome} está corrompido, cifrado ou num formato de compressão que o "
                      "preparar não gera.") from exc


def _inteiros(valor, nome: str) -> list[int]:
    if (not isinstance(valor, list) or not all(isinstance(a, int) and not isinstance(a, bool)
                                               for a in valor)):
        raise _recusa(f"o campo “{nome}” do manifesto é inválido.")
    return valor


def _data(valor) -> datetime | None:
    if not isinstance(valor, str) or not valor.strip():
        return None
    try:
        quando = datetime.fromisoformat(valor.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise _recusa("uma data do manifesto é inválida.") from exc
    return quando.astimezone(timezone.utc).replace(tzinfo=None) if quando.tzinfo else quando


def _texto(valor, maximo: int) -> str | None:
    if not isinstance(valor, str):
        return None
    return valor.strip()[:maximo] or None


def _abrir(conteudo: bytes, *, codigo_ibge: str, parsers: dict[str, tuple[str, str]],
           esperado: str) -> tuple[dict, bytes]:
    """Abre o zip e confere o manifesto e o CSV declarado (``parsers``: parser →
    (versão, nome do CSV)). Devolve ``(manifesto, bytes do CSV)``."""
    if len(conteudo) > MAX_PACOTE:
        raise _recusa("o arquivo é grande demais para um pacote recortado (o real tem poucos "
                      "KB).")
    try:
        z = zipfile.ZipFile(io.BytesIO(conteudo))
    except zipfile.BadZipFile as exc:
        raise _recusa("o arquivo não é um .zip válido.") from exc
    with z:
        try:
            manifesto = json.loads(_ler(z, pacote.NOME_MANIFESTO, _MAX_MANIFESTO).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _recusa("o manifesto.json não é um JSON válido.") from exc
        if not isinstance(manifesto, dict) or manifesto.get("tipo") != pacote.TIPO:
            raise _recusa("o arquivo não é um pacote de indicadores do Constela.")
        if manifesto.get("formato") != FORMATO:
            raise _recusa(f"formato de pacote {manifesto.get('formato')!r} desconhecido (este "
                          f"servidor lê o formato {FORMATO}). Gere o pacote de novo.")
        parser = manifesto.get("parser")
        if parser not in parsers:
            raise _recusa(f"o pacote é do parser {parser!r}; aqui entra o {esperado}.")
        versao, nome_csv = parsers[parser]
        if manifesto.get("parser_versao") != versao:
            raise _recusa(f"o pacote foi gerado pela versão {manifesto.get('parser_versao')!r} "
                          f"do parser; o servidor está na {versao}. Gere o pacote de novo com "
                          "o código atual.")
        alvo = manifesto.get("codigo_territorio_alvo")
        if alvo != codigo_ibge:
            raise _recusa(f"ele foi recortado para o município {alvo}, e esta rede é do "
                          f"município {codigo_ibge}. Gere o pacote com --ibge {codigo_ibge}.")
        _inteiros(manifesto.get("edicoes"), "edicoes")
        _inteiros(manifesto.get("anos_meta"), "anos_meta")
        entrada = manifesto.get("entrada")
        if not isinstance(entrada, dict) or entrada.get("csv") != nome_csv:
            raise _recusa("a entrada do manifesto é inválida.")
        for campo in ("sha256", "csv_sha256"):
            if not isinstance(entrada.get(campo), str) or not _RE_SHA256.match(entrada[campo]):
                raise _recusa(f"o {campo} da entrada é inválido.")
        sobrando = sorted(set(z.namelist()) - {pacote.NOME_MANIFESTO, nome_csv})
        if sobrando:
            raise _recusa(f"o pacote traz arquivo(s) que o manifesto não declara "
                          f"({', '.join(sobrando)}).")
        recorte = _ler(z, nome_csv, _MAX_CSV)
    if _sha256(recorte) != entrada["csv_sha256"]:
        raise _recusa(f"o {nome_csv} não confere com o manifesto (sha256 diferente): o pacote "
                      "foi alterado depois de gerado. Gere-o de novo com o preparar.")
    return manifesto, recorte


def _linhas_do_csv(recorte: bytes, nome_csv: str):
    try:
        texto = recorte.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _recusa(f"o {nome_csv} não é UTF-8.") from exc
    return csv.reader(io.StringIO(texto, newline=""), delimiter=";")


def _meta(manifesto: dict, conteudo: bytes, nome: str) -> dict:
    """A proveniência da importação, a partir do manifesto."""
    origem = manifesto.get("origem") if isinstance(manifesto.get("origem"), dict) else {}
    entrada = manifesto["entrada"]
    arquivo_nome = (_texto(origem.get("arquivo_nome"), 255)
                    or _texto((origem.get("url") or "").rstrip("/").rsplit("/", 1)[-1], 255)
                    or nome or "pacote_ideb.zip")
    zip_sha = origem.get("zip_sha256")
    zip_sha = zip_sha if isinstance(zip_sha, str) and _RE_SHA256.match(zip_sha) else None
    bytes_zip = origem.get("zip_bytes")
    return {
        "modo": "pacote_cli", "url_origem": _texto(origem.get("url"), 500),
        "last_modified_origem": _texto(origem.get("last_modified"), 64),
        "arquivo_nome": arquivo_nome,
        # O sha256 que identifica o arquivo do INEP é o do ZIP baixado (o preparar só
        # lê zip local, então ele sempre existe); sem ele, o da entrada (o xlsx).
        "arquivo_sha256": zip_sha or entrada["sha256"],
        "arquivo_bytes": bytes_zip if isinstance(bytes_zip, int) else 0,
        "arquivo_data": _data(entrada.get("data_interna")),
        "versao_rotulo": arquivo_nome.rsplit(".", 1)[0][:60] or None,
        # Quando o download foi registrado (MANIFESTO.json do download), vale ele; senão,
        # a hora em que o pacote foi gerado.
        "coletado_em": _data(origem.get("baixado_em")) or _data(manifesto.get("gerado_em")),
        "pacote_sha256": _sha256(conteudo),
    }


def _avisos_preparo(manifesto: dict, proprios: list[str]) -> list[str]:
    ja = set(proprios)
    return [a for a in manifesto.get("avisos_preparo") or [] if isinstance(a, str) and a not in ja]


def ler_pacote(conteudo: bytes, nome: str, *, codigo_ibge: str) -> PacoteIdebLido:
    """Abre, confere e lê o pacote do Ideb POR ESCOLA (ver o docstring do módulo).
    LEVANTA ``ImportacaoRecusada`` em qualquer divergência."""
    codigo_ibge = ica.normalizar_codigo_ibge(codigo_ibge)
    if codigo_ibge is None:
        raise ImportacaoRecusada("Código IBGE do município inválido (são 7 dígitos).")
    manifesto, recorte = _abrir(conteudo, codigo_ibge=codigo_ibge,
                                parsers={ideb.PARSER: (ideb.VERSAO_PARSER, NOME_CSV)},
                                esperado=f"{ideb.PARSER} (Ideb por escola)")
    entrada = manifesto["entrada"]
    linhas = _linhas_do_csv(recorte, NOME_CSV)
    nome_entrada = entrada.get("nome") if isinstance(entrada.get("nome"), str) else nome
    try:
        # O csv.reader é preguiçoso: o erro de CSV (campo acima do limite do módulo,
        # NUL...) só aparece DENTRO do parser — e não é ImportacaoRecusada.
        leitura = ideb.ler_grade(linhas, codigo_ibge=codigo_ibge, nome=nome_entrada or "")
    except csv.Error as exc:
        raise _recusa(f"o {NOME_CSV} está malformado (não é um CSV como o que o preparar "
                      "gera).") from exc
    if not leitura.recorte:
        raise _recusa("o recorte não tem nenhuma escola da rede municipal do município.")
    if leitura.linhas_lidas != len(leitura.recorte):
        raise _recusa(f"o {NOME_CSV} traz {leitura.linhas_lidas - len(leitura.recorte)} "
                      "linha(s) de escola de fora da rede municipal do município (não é um "
                      "recorte do preparar).")
    if (leitura.edicoes != manifesto["edicoes"] or leitura.anos_meta != manifesto["anos_meta"]
            or leitura.edicao_arquivo != manifesto.get("edicao")
            or entrada.get("linhas_recorte") != len(leitura.recorte)):
        raise _recusa("as edições, as metas ou as linhas do recorte não são as do manifesto.")
    return PacoteIdebLido(leitura=leitura, manifesto=manifesto,
                          meta=_meta(manifesto, conteudo, nome),
                          avisos_preparo=_avisos_preparo(manifesto, leitura.avisos))


def ler_pacote_territorio(conteudo: bytes, nome: str, *, codigo_ibge: str) -> PacoteIdebLido:
    """Abre, confere e lê o pacote do Ideb do MUNICÍPIO, da UF ou do BRASIL. LEVANTA
    ``ImportacaoRecusada`` em qualquer divergência."""
    codigo_ibge = ica.normalizar_codigo_ibge(codigo_ibge)
    if codigo_ibge is None:
        raise ImportacaoRecusada("Código IBGE do município inválido (são 7 dígitos).")
    parsers = {p: (ideb_territorio.VERSAO_PARSER, NOME_CSV_TERRITORIO[p])
               for p in ideb_territorio.PARSERS}
    manifesto, recorte = _abrir(
        conteudo, codigo_ibge=codigo_ibge, parsers=parsers,
        esperado=f"{' ou '.join(ideb_territorio.PARSERS)} (Ideb do município, da UF ou do "
                 "Brasil)")
    entrada = manifesto["entrada"]
    nome_csv = entrada["csv"]
    linhas = _linhas_do_csv(recorte, nome_csv)
    nome_entrada = entrada.get("nome") if isinstance(entrada.get("nome"), str) else nome
    try:
        leitura = ideb_territorio.ler_grade(linhas, codigo_ibge=codigo_ibge,
                                            nome=nome_entrada or "")
    except csv.Error as exc:
        raise _recusa(f"o {nome_csv} está malformado (não é um CSV como o que o preparar "
                      "gera).") from exc
    if leitura.parser != manifesto["parser"]:
        raise _recusa(f"o {nome_csv} é do layout {leitura.parser}, não do "
                      f"{manifesto['parser']} que o manifesto declara.")
    if not leitura.recorte:
        raise _recusa(f"o recorte não tem nenhuma linha do território {leitura.alvo}.")
    if leitura.linhas_lidas != len(leitura.recorte):
        raise _recusa(f"o {nome_csv} traz {leitura.linhas_lidas - len(leitura.recorte)} "
                      f"linha(s) de fora do território {leitura.alvo} (não é um recorte do "
                      "preparar).")
    if (leitura.edicoes != manifesto["edicoes"] or leitura.anos_meta != manifesto["anos_meta"]
            or leitura.edicao_arquivo != manifesto.get("edicao")
            or leitura.abrangencia != manifesto.get("abrangencia")
            or leitura.alvo != manifesto.get("territorio")
            or entrada.get("linhas_recorte") != len(leitura.recorte)):
        raise _recusa("as edições, as metas, o território ou as linhas do recorte não são as "
                      "do manifesto.")
    return PacoteIdebLido(leitura=leitura, manifesto=manifesto,
                          meta=_meta(manifesto, conteudo, nome),
                          avisos_preparo=_avisos_preparo(manifesto, leitura.avisos))


def resumo_do_manifesto(manifesto: dict) -> dict:
    """O que fica do manifesto na importação (proveniência do zip e da entrada)."""
    origem = manifesto.get("origem") if isinstance(manifesto.get("origem"), dict) else {}
    entrada = manifesto.get("entrada") if isinstance(manifesto.get("entrada"), dict) else {}
    return {
        "formato": manifesto.get("formato"), "gerado_em": manifesto.get("gerado_em"),
        "parser_versao": manifesto.get("parser_versao"),
        **({"abrangencia": manifesto["abrangencia"], "territorio": manifesto.get("territorio")}
           if "abrangencia" in manifesto else {}),
        "origem": {k: origem.get(k) for k in ("modo", "url", "arquivo_nome", "last_modified",
                                               "baixado_em", "zip_bytes", "zip_sha256")},
        "entrada": {k: entrada.get(k) for k in ("nome", "bytes", "bytes_comprimidos", "crc32",
                                                 "data_interna", "sha256", "md5",
                                                 "md5_publicado", "aba", "linhas_original",
                                                 "linhas_recorte", "escolas_outras_redes",
                                                 "redes_no_recorte")
                    if k in entrada or k not in ("redes_no_recorte",)},
    }
