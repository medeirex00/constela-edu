"""PACOTE RECORTADO da planilha do SAEB (Brasil, estados e municípios) — etapa E7.

Quem gera é a linha de comando ``preparar`` (nesta máquina: a planilha de 2025 tem
~24 MB e ~150 MB de XML descomprimido, e a produção não a abre). Quem recebe é a
prévia/aplicação/desfazer do fluxo de famílias (``pipeline_saeb``); o servidor refaz a
validação com o MESMO parser (``saeb_planilha.ler_aba`` + ``consolidar``).

O pacote é um .zip de poucos KB com:

* ``manifesto.json`` — tipo e formato, parser e versão, o município-alvo, a edição (e
  de onde ela veio: a coluna ANO_SAEB, o nome do arquivo ou a informada), a ORIGEM
  (nome, bytes e sha256 da planilha do INEP; URL, Last-Modified e data do download —
  o ``preparar`` os lê do MANIFESTO.json do download), a ENTRADA (a data interna da
  planilha, ``docProps/core.xml``; as abas ignoradas, como o "Dicionário"; a escala dos
  níveis) e, por ABA de dados, o tipo (Brasil, UF ou município), o território, o CSV,
  o sha256 dele e as linhas do arquivo e do recorte;
* um CSV por aba (``saeb_brasil_recorte.csv``, ``saeb_uf_recorte.csv``,
  ``saeb_municipio_recorte.csv``): UTF-8, ``;``, LF — o cabeçalho técnico da aba + SÓ
  as linhas do território (todas as dependências, localizações e áreas: o servidor
  registra as que não grava). Os valores vão como na planilha (sem o ruído binário do
  float): nada recalculado.

``ler_pacote`` RECUSA (nada gravado) se: não for deste formato/parser/versão; for de
outro município; tiver arquivo a mais ou a menos; um CSV não conferir com o sha256 do
manifesto; um CSV não passar no parser; trouxer linha de fora do território; ou a
edição, as abas e as contagens não forem as do manifesto. Sem assinatura digital: o
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
from app.services.indicadores import ica, pacote, saeb_planilha

FORMATO = 1
NOME_CSV = {saeb_planilha.ABA_BRASIL: "saeb_brasil_recorte.csv",
            saeb_planilha.ABA_UF: "saeb_uf_recorte.csv",
            saeb_planilha.ABA_MUNICIPIO: "saeb_municipio_recorte.csv"}
MAX_PACOTE = 2 * 1024 * 1024
_MAX_CSV = 1024 * 1024
_MAX_MANIFESTO = 256 * 1024
_RE_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _recusa(texto: str) -> ImportacaoRecusada:
    return ImportacaoRecusada(f"Pacote do Saeb recusado: {texto} Nada foi gravado.")


def _sha256(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


# --- Montagem (linha de comando) ------------------------------------------------

def csv_da_aba(aba: saeb_planilha.LeituraAba) -> bytes:
    """O cabeçalho técnico + as linhas do território, em texto (UTF-8 e LF)."""
    buf = io.StringIO()
    escritor = csv.writer(buf, delimiter=";", lineterminator="\n")
    for linha in (aba.cabecalho, *aba.recorte):
        escritor.writerow(linha)
    return buf.getvalue().encode("utf-8")


def montar_pacote(leitura: saeb_planilha.LeituraSaeb, *, codigo_ibge: str, origem: dict,
                  entrada: dict, edicao_informada: int | None = None,
                  gerado_em: datetime | None = None,
                  avisos: list[str] | None = None) -> tuple[bytes, dict]:
    """``(bytes do .zip, manifesto)``. Aba sem nenhuma linha do território fica FORA do
    pacote (com aviso); sem nenhuma, recusa."""
    com_linhas = [a for a in leitura.abas if a.recorte]
    if not com_linhas:
        raise ImportacaoRecusada(
            f"Nenhuma linha do município {codigo_ibge}, da UF dele ou do Brasil na planilha: "
            "nenhum pacote foi gerado.")
    gerado_em = gerado_em or datetime.now(timezone.utc)
    gerado_em = (gerado_em.replace(tzinfo=timezone.utc) if gerado_em.tzinfo is None
                 else gerado_em.astimezone(timezone.utc))
    arquivos = {a.tipo: csv_da_aba(a) for a in com_linhas}
    manifesto = {
        "tipo": pacote.TIPO, "formato": FORMATO, "parser": saeb_planilha.PARSER,
        "parser_versao": saeb_planilha.VERSAO_PARSER,
        "gerado_em": gerado_em.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "gerado_por": "python -m app.services.indicadores.preparar",
        "codigo_territorio_alvo": codigo_ibge, "codigo_uf": codigo_ibge[:2],
        "edicao": leitura.edicao_arquivo, "edicao_informada": edicao_informada,
        "origem_edicao": leitura.origem_edicao, "origem": origem,
        "entrada": {**entrada, "abas_ignoradas": list(leitura.abas_ignoradas),
                    "abas_sem_o_territorio": [a.aba for a in leitura.abas if not a.recorte],
                    "escala_niveis": leitura.escala_niveis, "escala_tx": leitura.escala_tx},
        "abas": [{"tipo": a.tipo, "aba": a.aba, "territorio": a.alvo, "csv": NOME_CSV[a.tipo],
                  "csv_sha256": _sha256(arquivos[a.tipo]), "linhas_original": a.linhas_lidas,
                  "linhas_recorte": len(a.recorte)} for a in com_linhas],
        "avisos_preparo": list(avisos or []), "licenca": pacote.AVISO_LICENCA,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        conteudos = [(pacote.NOME_MANIFESTO,
                      json.dumps(manifesto, ensure_ascii=False, indent=2).encode("utf-8")),
                     *((NOME_CSV[t], dados) for t, dados in arquivos.items())]
        for nome, dados in conteudos:
            info = zipfile.ZipInfo(nome, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, dados)
    return buf.getvalue(), manifesto


# --- Leitura (servidor) -----------------------------------------------------------

@dataclass
class PacoteSaebLido:
    leitura: saeb_planilha.LeituraSaeb
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


def _abas_do_manifesto(manifesto: dict) -> list[dict]:
    abas = manifesto.get("abas")
    if not isinstance(abas, list) or not abas:
        raise _recusa("o manifesto não declara as abas do recorte.")
    vistos = set()
    for a in abas:
        if (not isinstance(a, dict) or a.get("tipo") not in NOME_CSV
                or a.get("csv") != NOME_CSV[a["tipo"]] or a["tipo"] in vistos
                or not isinstance(a.get("csv_sha256"), str)
                or not _RE_SHA256.match(a["csv_sha256"])
                or not isinstance(a.get("linhas_recorte"), int)):
            raise _recusa("uma aba do manifesto é inválida.")
        vistos.add(a["tipo"])
    return abas


def ler_pacote(conteudo: bytes, nome: str, *, codigo_ibge: str) -> PacoteSaebLido:
    """Abre, confere e lê o pacote (ver o docstring do módulo). LEVANTA
    ``ImportacaoRecusada`` em qualquer divergência."""
    codigo_ibge = ica.normalizar_codigo_ibge(codigo_ibge)
    if codigo_ibge is None:
        raise ImportacaoRecusada("Código IBGE do município inválido (são 7 dígitos).")
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
        if manifesto.get("parser") != saeb_planilha.PARSER:
            raise _recusa(f"o pacote é do parser {manifesto.get('parser')!r}; aqui entra o "
                          f"{saeb_planilha.PARSER} (planilha do Saeb).")
        if manifesto.get("parser_versao") != saeb_planilha.VERSAO_PARSER:
            raise _recusa(f"o pacote foi gerado pela versão {manifesto.get('parser_versao')!r} "
                          f"do parser; o servidor está na {saeb_planilha.VERSAO_PARSER}. Gere o "
                          "pacote de novo com o código atual.")
        alvo = manifesto.get("codigo_territorio_alvo")
        if alvo != codigo_ibge:
            raise _recusa(f"ele foi recortado para o município {alvo}, e esta rede é do "
                          f"município {codigo_ibge}. Gere o pacote com --ibge {codigo_ibge}.")
        origem = manifesto.get("origem") if isinstance(manifesto.get("origem"), dict) else {}
        entrada = manifesto.get("entrada") if isinstance(manifesto.get("entrada"), dict) else {}
        if not isinstance(origem.get("sha256"), str) or not _RE_SHA256.match(origem["sha256"]):
            raise _recusa("o sha256 da planilha de origem é inválido.")
        abas_m = _abas_do_manifesto(manifesto)
        declarados = {pacote.NOME_MANIFESTO, *(a["csv"] for a in abas_m)}
        sobrando = sorted(set(z.namelist()) - declarados)
        if sobrando:
            raise _recusa(f"o pacote traz arquivo(s) que o manifesto não declara "
                          f"({', '.join(sobrando)}).")
        csvs = {a["tipo"]: _ler(z, a["csv"], _MAX_CSV) for a in abas_m}
    abas = []
    for a in abas_m:
        dados = csvs[a["tipo"]]
        if _sha256(dados) != a["csv_sha256"]:
            raise _recusa(f"o {a['csv']} não confere com o manifesto (sha256 diferente): o "
                          "pacote foi alterado depois de gerado. Gere-o de novo com o preparar.")
        try:
            texto = dados.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise _recusa(f"o {a['csv']} não é UTF-8.") from exc
        try:
            lida = saeb_planilha.ler_aba(csv.reader(io.StringIO(texto, newline=""),
                                                    delimiter=";"),
                                         codigo_ibge=codigo_ibge,
                                         aba=_texto(a.get("aba"), 60) or a["tipo"])
        except csv.Error as exc:
            raise _recusa(f"o {a['csv']} está malformado (não é um CSV como o que o preparar "
                          "gera).") from exc
        if lida is None or lida.tipo != a["tipo"]:
            raise _recusa(f"o {a['csv']} não tem o cabeçalho técnico de uma aba "
                          f"“{a['tipo']}” da planilha do Saeb.")
        if lida.linhas_lidas != len(lida.recorte):
            raise _recusa(f"o {a['csv']} traz {lida.linhas_lidas - len(lida.recorte)} linha(s) "
                          f"de fora do território {lida.alvo} (não é um recorte do preparar).")
        if not lida.recorte or len(lida.recorte) != a["linhas_recorte"]:
            raise _recusa(f"as linhas do {a['csv']} não são as do manifesto.")
        abas.append(lida)
    edicao_informada = manifesto.get("edicao_informada")
    if edicao_informada is not None and (not isinstance(edicao_informada, int)
                                         or isinstance(edicao_informada, bool)):
        raise _recusa("a edição informada do manifesto é inválida.")
    ignoradas = [x for x in entrada.get("abas_ignoradas") or [] if isinstance(x, str)]
    arquivo_nome = (_texto(origem.get("arquivo_nome"), 255)
                    or _texto((origem.get("url") or "").rstrip("/").rsplit("/", 1)[-1], 255)
                    or nome or "planilha_saeb.xlsx")
    leitura = saeb_planilha.consolidar(abas, nome=arquivo_nome, edicao_informada=edicao_informada,
                                       abas_ignoradas=ignoradas)
    if leitura.edicao_arquivo != manifesto.get("edicao"):
        raise _recusa(f"a edição lida ({leitura.edicao_arquivo}) não é a do manifesto "
                      f"({manifesto.get('edicao')}).")
    bytes_origem = origem.get("bytes")
    meta = {
        "modo": "pacote_cli", "url_origem": _texto(origem.get("url"), 500),
        "last_modified_origem": _texto(origem.get("last_modified"), 64),
        "arquivo_nome": arquivo_nome, "arquivo_sha256": origem["sha256"],
        "arquivo_bytes": bytes_origem if isinstance(bytes_origem, int) else 0,
        "arquivo_data": _data(entrada.get("data_interna")),
        "versao_rotulo": arquivo_nome.rsplit(".", 1)[0][:60] or None,
        "coletado_em": _data(origem.get("baixado_em")) or _data(manifesto.get("gerado_em")),
        "pacote_sha256": _sha256(conteudo),
    }
    proprios = set(leitura.avisos)
    avisos_preparo = [x for x in manifesto.get("avisos_preparo") or []
                      if isinstance(x, str) and x not in proprios]
    return PacoteSaebLido(leitura=leitura, manifesto=manifesto, meta=meta,
                          avisos_preparo=avisos_preparo)


def resumo_do_manifesto(manifesto: dict) -> dict:
    """O que fica do manifesto na importação (proveniência da planilha e das abas)."""
    origem = manifesto.get("origem") if isinstance(manifesto.get("origem"), dict) else {}
    entrada = manifesto.get("entrada") if isinstance(manifesto.get("entrada"), dict) else {}
    return {
        "formato": manifesto.get("formato"), "gerado_em": manifesto.get("gerado_em"),
        "parser_versao": manifesto.get("parser_versao"),
        "origem_edicao": manifesto.get("origem_edicao"),
        "origem": {k: origem.get(k) for k in ("modo", "url", "arquivo_nome", "last_modified",
                                               "baixado_em", "bytes", "sha256")},
        "entrada": {k: entrada.get(k) for k in ("data_interna", "abas_ignoradas",
                                                 "abas_sem_o_territorio", "escala_niveis",
                                                 "escala_tx")},
        "abas": [{k: a.get(k) for k in ("tipo", "aba", "territorio", "linhas_original",
                                         "linhas_recorte", "csv_sha256")}
                 for a in manifesto.get("abas") or [] if isinstance(a, dict)],
    }
