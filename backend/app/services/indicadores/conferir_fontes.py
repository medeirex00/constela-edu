"""Linha de comando ``conferir_fontes``: a conferência MANUAL das fontes oficiais dos
indicadores (etapa E10 — decisão D12 do dono, 17/10: a verificação de arquivos novos
começa pela conferência manual, por comando local; nada agendado, nada em produção).

Uso (a partir de ``backend/``, NESTA máquina)::

    python -m app.services.indicadores.conferir_fontes \\
        [--dados ~/constela-dados-oficiais]      # lê <pasta>/*/MANIFESTO.json (repetível)
        [--manifesto ARQ]                        # um MANIFESTO.json avulso (repetível)
        [--banco sqlite:///caminho/da/copia.db]  # só LÊ importacoes_indicador
        [--json]                                 # saída em JSON (para guardar ou comparar)
        [--ca-bundle ARQ.pem]                    # certificados EXTRAS (PEM), somados ao certifi
        [--timeout 20] [--intervalo 1]

Os caminhos aceitam ``~`` (o PowerShell não o expande: o comando expande).

O QUE FAZ — para cada fonte oficial conhecida, consulta SÓ METADADOS:

* os arquivos do INEP (planilhas do ICA, zips dos microdados da avaliação da
  alfabetização, zips do Ideb, planilhas do Saeb — o catálogo ``FONTES``) e qualquer
  outra URL que apareça numa importação registrada ou num MANIFESTO: um ``HEAD``
  (Last-Modified, ETag, Content-Length). Se o servidor não aceitar HEAD (405/501), um
  ``GET`` de 1 byte (``Range: bytes=0-0``) cujo corpo NÃO é lido;
* os conjuntos de dados abertos da SEDUC-SP (IEE, SARESP por município e por
  instância): ``package_show`` da API CKAN, para DESCOBRIR recursos novos (o ano novo,
  o sufixo trocado), e o ``HEAD`` de cada recurso que interessa;

e compara com o que já se tem — a última importação APLICADA registrada em
``importacoes_indicador`` (URL, Last-Modified, ETag, tamanho, sha256, edição; com
``--banco``) e o MANIFESTO local dos downloads (``--dados``/``--manifesto``).

ESTADOS de cada item:

* ``sem_novidade`` — os metadados batem com a referência mais nova (Last-Modified; na
  falta dele, ETag ou tamanho);
* ``nova_versao`` — o arquivo mudou no servidor (outro Last-Modified, ETag ou tamanho),
  ou a edição já registrada ganhou um endereço novo no CKAN (sufixo trocado), ou não há
  metadado comparável (conferir à mão, pela prévia);
* ``novo_arquivo`` — existe no servidor e não há registro dele (ex.: o ano novo no
  CKAN; uma URL do catálogo ainda não importada nem baixada);
* ``inacessivel`` — timeout, recusa de conexão, 401/403/429/5xx, redirecionamento para
  uma página de LOGIN ou uma página HTML no lugar do arquivo (como no defeso eleitoral
  de 2026). "Inacessível" NUNCA vira "removido";
* ``nao_encontrado`` — 404 ou 410 ("conferir a página oficial": o vigia não adivinha o
  próximo sufixo, _4 ou v3);
* ``erro_tls`` — o certificado não foi validado. A verificação NUNCA é desligada: se a
  cadeia do servidor vier incompleta, passe a intermediária em ``--ca-bundle`` — ela é
  SOMADA às autoridades confiáveis de sempre (as do certifi, ou as de ``SSL_CERT_FILE``
  / ``SSL_CERT_DIR``), então os outros hosts continuam validando.

O QUE NUNCA FAZ: baixar dado (nenhum corpo de arquivo é lido; o do CKAN é só o JSON
dos metadados, com teto), aplicar ou importar qualquer coisa, gravar no banco (com
``--banco`` ele só lê; o SQLite abre em modo SOMENTE LEITURA e um caminho inexistente é
recusado sem criar arquivo), rodar sozinho (não há agendamento) ou desligar o TLS. Os
destinos passam pela mesma guarda anti-SSRF do robô de coleta (só https para host
público, revalidada a cada redirecionamento). A URL do banco nunca sai com a senha.

LIMITE CONHECIDO: nas fontes de ARQUIVO a referência é casada SÓ pela URL normalizada.
Uma importação feita pela tela sem a URL de origem (campo opcional) não casa com a fonte
do catálogo: ela aparece como ``novo_arquivo`` — confira pela prévia (o sha256).

SAÍDA: o relatório legível (ou ``--json``) e o código de saída 0 quando tudo está
``sem_novidade``; 1 quando algum item pede atenção (novidade, falha de acesso ou um
arquivo baixado — MANIFESTO — que ainda não foi importado); 2 para erro de uso
(argumento inválido, MANIFESTO ilegível, banco que não abre, ``--ca-bundle`` inválido).

Depois: arquivo novo ou nova versão → baixar (com autorização), gerar o pacote com o
``preparar`` quando for o caso e passar pela PRÉVIA da importação (admin global) — a
prévia diz o que muda; nada é aplicado sem ela.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import quote, unquote, urlparse

import httpx

# --- Estados ----------------------------------------------------------------------

SEM_NOVIDADE = "sem_novidade"
NOVA_VERSAO = "nova_versao"
NOVO_ARQUIVO = "novo_arquivo"
INACESSIVEL = "inacessivel"
NAO_ENCONTRADO = "nao_encontrado"
ERRO_TLS = "erro_tls"
ESTADOS = (NOVA_VERSAO, NOVO_ARQUIVO, INACESSIVEL, NAO_ENCONTRADO, ERRO_TLS, SEM_NOVIDADE)
ROTULO_ESTADO = {
    NOVA_VERSAO: "NOVA VERSÃO", NOVO_ARQUIVO: "NOVO ARQUIVO", INACESSIVEL: "INACESSÍVEL",
    NAO_ENCONTRADO: "NÃO ENCONTRADO (conferir a página oficial)", ERRO_TLS: "ERRO DE TLS",
    SEM_NOVIDADE: "SEM NOVIDADE",
}

# --- Catálogo das fontes conhecidas (as URLs que o branch usa) ----------------------

CKAN_SEDUC = "https://dados.educacao.sp.gov.br/api/3/action/package_show"
_INEP = "https://download.inep.gov.br"


@dataclass(frozen=True)
class FonteConhecida:
    """Uma fonte oficial que o Constela importa. ``tipo``: ``arquivo`` (uma URL, pelo
    HEAD) ou ``ckan`` (um conjunto de dados: ``package_show`` + HEAD dos recursos).
    ``parsers``: quem lê o arquivo no Constela. Só o CKAN os usa (as edições já
    importadas do conjunto); nas fontes de ``arquivo`` a referência é casada SÓ pela URL
    normalizada — a importação feita sem a URL de origem não casa (limite no topo)."""
    chave: str
    rotulo: str
    orgao: str
    tipo: str
    url: str
    parsers: tuple[str, ...]
    ckan_id: str | None = None


FONTES: tuple[FonteConhecida, ...] = (
    # Indicador Criança Alfabetizada — planilhas "resultados e metas" (E2).
    FonteConhecida("ica_municipios_2025", "ICA — resultados e metas dos municípios (2025)",
                   "INEP", "arquivo",
                   f"{_INEP}/avaliacao_da_alfabetizacao/resultados/"
                   "resultados_e_metas_municipios_2025_3.xlsx", ("inep_ica_municipios",)),
    FonteConhecida("ica_municipios_2024", "ICA — resultados e metas dos municípios (2024)",
                   "INEP", "arquivo",
                   f"{_INEP}/alfabetiza_brasil/resultados_e_metas_municipios_2024.xlsx",
                   ("inep_ica_municipios",)),
    FonteConhecida("ica_municipios_2023", "ICA — resultados e metas dos municípios (2023)",
                   "INEP", "arquivo",
                   f"{_INEP}/avaliacao_da_alfabetizacao/resultados_e_metas_municipios.xlsx",
                   ("inep_ica_municipios",)),
    FonteConhecida("ica_ufs_2025", "ICA — resultados e metas das UFs e do Brasil (2025)",
                   "INEP", "arquivo",
                   f"{_INEP}/avaliacao_da_alfabetizacao/resultados/"
                   "resultados_e_metas_ufs_2025_v2.xlsx", ("inep_ica_ufs",)),
    FonteConhecida("ica_ufs_2024", "ICA — resultados e metas das UFs e do Brasil (2024)",
                   "INEP", "arquivo",
                   f"{_INEP}/alfabetiza_brasil/resultados_e_metas_ufs_2024_2.xlsx",
                   ("inep_ica_ufs",)),
    FonteConhecida("ica_ufs_2023", "ICA — resultados e metas das UFs e do Brasil (2023)",
                   "INEP", "arquivo",
                   f"{_INEP}/avaliacao_da_alfabetizacao/resultados_e_metas_ufs.xlsx",
                   ("inep_ica_ufs",)),
    # Microdados da avaliação da alfabetização — tabelas agregadas (E3).
    FonteConhecida("aeeb_2025", "Microdados da avaliação da alfabetização (2025)", "INEP",
                   "arquivo", f"{_INEP}/dados_abertos/microdados_AEEB_2025.zip",
                   ("inep_aeeb_agregados",)),
    FonteConhecida("aeeb_2024", "Microdados da avaliação da alfabetização (2024)", "INEP",
                   "arquivo",
                   f"{_INEP}/dados_abertos/microdados_avaliacao_da_alfabetizacao_2024.zip",
                   ("inep_aeeb_agregados",)),
    FonteConhecida("aeeb_2023", "Microdados da avaliação da alfabetização (2023)", "INEP",
                   "arquivo",
                   f"{_INEP}/dados_abertos/microdados_avaliacao_da_alfabetizacao_2023.zip",
                   ("inep_aeeb_agregados",)),
    # Ideb — zips da divulgação (E6a e E6b).
    FonteConhecida("ideb_escolas_2025", "Ideb por escola — anos iniciais (divulgação 2025)",
                   "INEP", "arquivo",
                   f"{_INEP}/ideb/resultados/divulgacao_anos_iniciais_escolas_2025.zip",
                   ("inep_ideb_escolas",)),
    FonteConhecida("ideb_municipios_2025",
                   "Ideb por município — anos iniciais (divulgação 2025)", "INEP", "arquivo",
                   f"{_INEP}/ideb/resultados/divulgacao_anos_iniciais_municipios_2025.zip",
                   ("inep_ideb_municipios",)),
    FonteConhecida("ideb_ufs_2025", "Ideb de regiões e UFs (divulgação 2025)", "INEP",
                   "arquivo", f"{_INEP}/ideb/resultados/divulgacao_regioes_ufs_ideb_2025.zip",
                   ("inep_ideb_uf_brasil",)),
    FonteConhecida("ideb_brasil_2025", "Ideb do Brasil (divulgação 2025)", "INEP", "arquivo",
                   f"{_INEP}/ideb/resultados/divulgacao_brasil_ideb_2025.zip",
                   ("inep_ideb_uf_brasil",)),
    # Saeb — planilhas de Brasil, estados e municípios (E7).
    FonteConhecida("saeb_2025", "Saeb — Brasil, estados e municípios (2025)", "INEP",
                   "arquivo",
                   f"{_INEP}/saeb/resultados/saeb_2025_brasil_estados_municipios_censitario.xlsx",
                   ("inep_saeb_planilha",)),
    FonteConhecida("saeb_2021", "Saeb — Brasil, estados e municípios (2021)", "INEP",
                   "arquivo", f"{_INEP}/saeb/resultados/saeb_2021_brasil_estados_municipios.xlsx",
                   ("inep_saeb_planilha",)),
    FonteConhecida("saeb_2021_alfabetizacao",
                   "Saeb 2021 — com a taxa de alfabetização (UF e Brasil)", "INEP", "arquivo",
                   f"{_INEP}/saeb/resultados/"
                   "saeb_2021_brasil_estados_municipios_c_tx_alfabetizado.xlsx",
                   ("inep_saeb_planilha",)),
    FonteConhecida("saeb_2019", "Saeb — Brasil, estados e municípios (2019)", "INEP",
                   "arquivo",
                   f"{_INEP}/educacao_basica/saeb/2019/resultados/"
                   "Resultados_Saeb_2019_Brasil_Estados_Municipios.xlsx",
                   ("inep_saeb_planilha",)),
    # SEDUC-SP — conjuntos de dados abertos (CKAN), E4.
    FonteConhecida("seduc_iee", "Índice de Excelência Educacional (IEE) — conjunto do CKAN",
                   "SEDUC-SP", "ckan", CKAN_SEDUC, ("seduc_iee",),
                   ckan_id="55e73f71-4bca-44c7-bdad-11a820daf998"),
    FonteConhecida("seduc_saresp_municipio",
                   "Proficiência do SARESP por município — conjunto do CKAN",
                   "SEDUC-SP", "ckan", CKAN_SEDUC, ("seduc_saresp_municipio",),
                   ckan_id=("proficiência-do-sistema-de-avaliação-de-rendimento-escolar-do-"
                            "estado-de-são-paulo-saresp-4")),
    FonteConhecida("seduc_saresp_instancia",
                   "Proficiência do SARESP por instância (Estado) — conjunto do CKAN",
                   "SEDUC-SP",
                   "ckan", CKAN_SEDUC, ("seduc_saresp_instancia",),
                   ckan_id=("proficiência-do-sistema-de-avaliação-de-rendimento-escolar-do-"
                            "estado-de-são-paulo-saresp-6")),
)

# --- Referências (o que já se tem) ---------------------------------------------------


@dataclass
class Referencia:
    """O que se sabe de um arquivo já importado ou baixado."""
    origem: str                      # "importação #12" | "MANIFESTO <caminho>"
    tipo: str                        # importacao | manifesto
    url: str | None = None
    last_modified: str | None = None
    etag: str | None = None
    bytes: int | None = None
    sha256: str | None = None
    edicao: int | None = None
    parser: str | None = None
    arquivo: str | None = None


def normalizar_url(url: str | None) -> str | None:
    """Chave de comparação: sem espaços, %-codificação desfeita, esquema e host em
    minúsculas, sem barra final (o CKAN e o MANIFESTO codificam o acento diferente)."""
    if not url or not isinstance(url, str) or not url.strip():
        return None
    partes = urlparse(url.strip())
    caminho = unquote(partes.path).rstrip("/")
    consulta = f"?{unquote(partes.query)}" if partes.query else ""
    return f"{partes.scheme.lower()}://{(partes.netloc or '').lower()}{caminho}{consulta}"


_RE_ANO = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


def ano_do_nome(texto: str | None) -> int | None:
    """O PRIMEIRO ano (20xx) do nome: "IEE 2025-2026_0.csv" → 2025 (a edição do SARESP);
    "SARESP por Municipio de 2024_0.csv" → 2024. Sem ano, None."""
    m = _RE_ANO.search(unquote(texto or ""))
    return int(m.group(1)) if m else None


def _inteiro(valor) -> int | None:
    try:
        return int(str(valor).strip()) if valor not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _texto(valor) -> str | None:
    return valor.strip() if isinstance(valor, str) and valor.strip() else None


def referencias_do_manifesto(caminho: str | Path) -> list[Referencia]:
    """Registros de um MANIFESTO.json de download: ``{"url", "arquivo", "last_modified",
    "bytes", "sha256"}`` (arquivo baixado inteiro) ou ``{"url_zip", "zip_last_modified",
    "zip_bytes", ...}`` (entrada lida de dentro do zip por HTTP Range — o tamanho e a data
    que valem são os do ZIP; o sha256 é o da entrada, não do zip). Registro marcado como
    falho (``"ok": false``) fica de fora. LEVANTA ``ValueError`` se o arquivo não é um
    MANIFESTO legível."""
    caminho = Path(caminho)
    origem = (f"MANIFESTO {caminho.parent.name}/{caminho.name}" if caminho.parent.name
              else f"MANIFESTO {caminho}")
    try:
        registros = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"não consegui ler o MANIFESTO {caminho}: {exc}") from exc
    if isinstance(registros, dict):
        registros = [registros]
    if not isinstance(registros, list):
        raise ValueError(f"o MANIFESTO {caminho} não é uma lista de arquivos")
    saida = []
    for r in registros:
        if not isinstance(r, dict) or r.get("ok") is False:
            continue
        if _texto(r.get("url")):
            ref = Referencia(origem=origem, tipo="manifesto",
                             url=_texto(r.get("url")), last_modified=_texto(r.get("last_modified")),
                             etag=_texto(r.get("etag")), bytes=_inteiro(r.get("bytes")),
                             sha256=_texto(r.get("sha256")), arquivo=_texto(r.get("arquivo")))
        elif _texto(r.get("url_zip")):
            ref = Referencia(origem=origem, tipo="manifesto",
                             url=_texto(r.get("url_zip")),
                             last_modified=_texto(r.get("zip_last_modified")),
                             etag=_texto(r.get("zip_etag")), bytes=_inteiro(r.get("zip_bytes")),
                             arquivo=_texto(r.get("arquivo")))
        else:
            continue
        ref.edicao = ano_do_nome(ref.arquivo) or ano_do_nome(ref.url)
        saida.append(ref)
    return saida


def manifestos_da_pasta(pasta: str | Path) -> list[Path]:
    """``<pasta>/MANIFESTO.json`` e ``<pasta>/*/MANIFESTO.json`` (a organização de
    ``constela-dados-oficiais``: uma subpasta por fonte)."""
    pasta = Path(pasta).expanduser()
    if not pasta.is_dir():
        raise ValueError(f"a pasta {pasta} não existe")
    raiz = [pasta / "MANIFESTO.json"] if (pasta / "MANIFESTO.json").is_file() else []
    return raiz + sorted(pasta.glob("*/MANIFESTO.json"))


def url_sem_senha(url_banco: str) -> str:
    """A URL do banco para mensagens: a senha vira ``***`` (nunca vai para o terminal nem
    para um log); a que nem se deixa ler vira ``<url inválida>``."""
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import SQLAlchemyError

    try:
        return make_url(url_banco).render_as_string(hide_password=True)
    except (SQLAlchemyError, ValueError, TypeError):
        return "<url inválida>"


def _engine_so_leitura(url_banco: str):
    """O engine de ``--banco``. SQLite: o arquivo precisa EXISTIR (``~`` expandido) e abre
    em modo SOMENTE LEITURA — um caminho digitado errado é recusado sem criar arquivo
    vazio. Outros bancos: o engine comum (o comando só faz SELECT e rollback)."""
    import sqlite3

    from sqlalchemy import create_engine
    from sqlalchemy.engine import make_url
    from sqlalchemy.pool import NullPool

    url = make_url(url_banco)
    if url.get_backend_name() != "sqlite":
        return create_engine(url)
    banco = url.database or ""
    if not banco or banco == ":memory:" or banco.startswith("file:"):
        raise ValueError(f"o --banco SQLite precisa ser o caminho de um arquivo: "
                         f"{url_sem_senha(url_banco)}")
    caminho = Path(banco).expanduser()
    if not caminho.is_file():
        raise ValueError(f"o banco SQLite {caminho} não existe (nada foi criado)")
    uri = f"{caminho.resolve().as_uri()}?mode=ro"
    return create_engine("sqlite://", creator=lambda: sqlite3.connect(uri, uri=True),
                         poolclass=NullPool)


def referencias_do_banco(url_banco: str) -> list[Referencia]:
    """As importações APLICADAS de ``importacoes_indicador`` (só LÊ: um SELECT, nenhuma
    escrita, nenhum commit). No pacote da linha de comando, a URL, o Last-Modified e a
    ETag são os do ZIP de origem (manifesto do pacote); o TAMANHO e o sha256 do ZIP só
    valem como os do arquivo REMOTO no pacote lido por HTTP Range (``origem.modo ==
    "http_range"``: o total do Content-Range do servidor). No ``zip_local`` eles são os do
    zip LOCAL — no AEEB, um zip reduzido (sem o TS_ALUNO) — e ficam de fora: compará-los
    com o Content-Length acusaria uma "nova versão" falsa. No upload direto, o tamanho e
    o sha256 são os do próprio arquivo. LEVANTA ``ValueError`` se o banco não abre (a
    mensagem nunca traz a senha)."""
    from sqlalchemy import select
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.orm import Session

    from app.models import ImportacaoIndicador

    try:
        engine = _engine_so_leitura(url_banco)
    except (SQLAlchemyError, ImportError) as exc:
        raise ValueError(f"não consegui abrir o banco {url_sem_senha(url_banco)}: "
                         f"{type(exc).__name__}") from exc
    try:
        with Session(engine) as sessao:
            imps = sessao.execute(select(ImportacaoIndicador).where(
                ImportacaoIndicador.status == "aplicada")).scalars().all()
            saida = []
            for imp in imps:
                origem_pacote = ((imp.resumo or {}).get("pacote") or {}).get("origem") or {}
                pacote = imp.modo == "pacote_cli"
                zip_remoto = pacote and origem_pacote.get("modo") == "http_range"
                if zip_remoto:
                    tamanho = _inteiro(origem_pacote.get("zip_bytes"))
                    sha256 = _texto(origem_pacote.get("zip_sha256"))
                elif pacote:
                    tamanho = sha256 = None      # zip_local / planilha_local: tamanho LOCAL
                else:
                    tamanho, sha256 = _inteiro(imp.arquivo_bytes), _texto(imp.arquivo_sha256)
                saida.append(Referencia(
                    origem=f"importação #{imp.id}", tipo="importacao",
                    url=_texto(imp.url_origem),
                    last_modified=_texto(imp.last_modified_origem),
                    etag=_texto(origem_pacote.get("etag")) if pacote else None,
                    bytes=tamanho, sha256=sha256,
                    edicao=imp.edicao_arquivo, parser=imp.parser, arquivo=imp.arquivo_nome))
            sessao.rollback()
            return saida
    except SQLAlchemyError as exc:
        raise ValueError(f"não consegui ler importacoes_indicador em "
                         f"{url_sem_senha(url_banco)}: {type(exc).__name__}") from exc
    finally:
        engine.dispose()


# --- HTTP: só metadados ---------------------------------------------------------------

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/124.0 Safari/537.36 (Constela - conferencia de metadados)")
_MAX_REDIRECTS = 5
_MAX_JSON_CKAN = 2 * 1024 * 1024        # o package_show tem poucos KB
_EXTENSOES_ARQUIVO = (".xlsx", ".xls", ".zip", ".csv", ".ods", ".rar", ".xlsb")
_RE_LOGIN = re.compile(r"(login|logon|signin|sign-in|/entrar|/auth|oauth|/sso|/cas/|"
                       r"autentica|defeso)", re.IGNORECASE)


@dataclass
class Consulta:
    """Resultado de uma consulta de metadados (sem corpo de arquivo)."""
    estado: str | None               # None = respondeu 2xx com metadados
    detalhe: str = ""
    status_http: int | None = None
    url_final: str | None = None
    last_modified: str | None = None
    etag: str | None = None
    content_length: int | None = None
    content_type: str | None = None
    redirecionado: bool = False
    corpo: bytes | None = None       # só no CKAN (JSON)


def _cadeia(exc: BaseException) -> Iterable[BaseException]:
    vistos = set()
    while exc is not None and id(exc) not in vistos:
        vistos.add(id(exc))
        yield exc
        exc = exc.__cause__ or exc.__context__


def _e_tls(exc: BaseException) -> bool:
    import ssl

    for e in _cadeia(exc):
        if isinstance(e, ssl.SSLError):
            return True
        texto = str(e)
        if any(t in texto for t in ("CERTIFICATE_VERIFY_FAILED", "SSL:", "[SSL", "TLSV1",
                                    "certificate verify failed")):
            return True
    return False


def _parece_arquivo(url: str) -> bool:
    return unquote(urlparse(url).path).lower().endswith(_EXTENSOES_ARQUIVO)


def _validar_padrao(url: str) -> None:
    """A guarda anti-SSRF do robô de coleta (só https para host público)."""
    from app.services.avaliacoes import _exigir_destino_publico

    _exigir_destino_publico(url)


def consultar(cliente: httpx.Client, url: str, *, validar: Callable[[str], None],
              json_ckan: bool = False) -> Consulta:
    """HEAD (ou, no CKAN, GET do JSON) seguindo os redirecionamentos À MÃO, cada destino
    revalidado. Nunca levanta por erro de rede: devolve o estado."""
    alvo = url
    redirecionado = False
    metodo = "GET" if json_ckan else "HEAD"
    tentou_get = json_ckan
    try:
        for _ in range(_MAX_REDIRECTS + 1):
            try:
                validar(alvo)
            except ValueError as exc:
                return Consulta(INACESSIVEL, f"destino recusado pela guarda: {exc}",
                                url_final=alvo, redirecionado=redirecionado)
            cabecalhos = {"User-Agent": _UA, "Accept": "application/json" if json_ckan else "*/*"}
            if metodo == "GET" and not json_ckan:
                cabecalhos.update({"Range": "bytes=0-0", "Accept-Encoding": "identity"})
            with cliente.stream(metodo, alvo, headers=cabecalhos) as r:
                if r.is_redirect:
                    destino = r.headers.get("location")
                    if not destino:
                        return Consulta(INACESSIVEL, "redirecionamento sem destino",
                                        status_http=r.status_code, url_final=alvo)
                    novo = str(r.url.join(destino))
                    if _RE_LOGIN.search(urlparse(novo).path + "?" + urlparse(novo).query):
                        return Consulta(INACESSIVEL,
                                        f"redirecionado para uma página de login ({novo}) — "
                                        "como no defeso eleitoral; não é remoção",
                                        status_http=r.status_code, url_final=novo,
                                        redirecionado=True)
                    alvo, redirecionado = novo, True
                    continue
                if r.status_code in (405, 501) and metodo == "HEAD" and not tentou_get:
                    metodo, tentou_get = "GET", True       # HEAD recusado: 1 byte, sem ler
                    continue
                cab = {k.lower(): v for k, v in r.headers.items()}
                base = dict(status_http=r.status_code, url_final=alvo,
                            last_modified=cab.get("last-modified"), etag=cab.get("etag"),
                            content_type=cab.get("content-type"), redirecionado=redirecionado)
                if r.status_code in (404, 410):
                    return Consulta(NAO_ENCONTRADO, f"HTTP {r.status_code}", **base)
                if not 200 <= r.status_code < 300:
                    return Consulta(INACESSIVEL, f"HTTP {r.status_code}", **base)
                tamanho = _inteiro(cab.get("content-length"))
                if r.status_code == 206:            # GET de 1 byte: o total vem no Content-Range
                    m = re.search(r"/(\d+)\s*$", cab.get("content-range", ""))
                    tamanho = int(m.group(1)) if m else None
                tipo = (cab.get("content-type") or "").lower()
                if not json_ckan and "text/html" in tipo and _parece_arquivo(url):
                    return Consulta(INACESSIVEL,
                                    "o endereço devolveu uma página HTML, não o arquivo "
                                    "(provável login ou aviso, como no defeso eleitoral)",
                                    content_length=tamanho, **base)
                corpo = None
                if json_ckan:
                    buf = bytearray()
                    for pedaco in r.iter_bytes():
                        buf += pedaco
                        if len(buf) > _MAX_JSON_CKAN:
                            return Consulta(INACESSIVEL, "resposta do CKAN grande demais "
                                            "(não parece o package_show)", **base)
                    corpo = bytes(buf)
                return Consulta(None, "", content_length=tamanho, corpo=corpo, **base)
        return Consulta(INACESSIVEL, "redirecionamentos demais", url_final=alvo,
                        redirecionado=True)
    except httpx.TimeoutException:
        return Consulta(INACESSIVEL, "tempo esgotado", url_final=alvo)
    except httpx.HTTPError as exc:
        if _e_tls(exc):
            return Consulta(ERRO_TLS, f"certificado não validado ({_curto(exc)}); a "
                            "verificação continua ligada — se a cadeia do servidor vier "
                            "incompleta, passe a intermediária em --ca-bundle (somada às "
                            "autoridades do certifi)", url_final=alvo)
        return Consulta(INACESSIVEL, f"falha de conexão ({_curto(exc)})", url_final=alvo)
    except OSError as exc:                      # ssl.SSLError também é OSError
        if _e_tls(exc):
            return Consulta(ERRO_TLS, f"certificado não validado ({_curto(exc)})",
                            url_final=alvo)
        return Consulta(INACESSIVEL, f"falha de conexão ({_curto(exc)})", url_final=alvo)


def _curto(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:200]


# --- Comparação --------------------------------------------------------------------------


@dataclass
class Item:
    """Uma linha do relatório."""
    chave: str
    rotulo: str
    orgao: str | None
    url: str
    estado: str
    detalhe: str
    edicao: int | None = None
    conjunto: str | None = None
    remoto: dict = field(default_factory=dict)
    referencia: dict | None = None
    referencias: int = 0
    baixado_sem_importacao: bool = False


def _data(texto: str | None) -> datetime | None:
    if not texto:
        return None
    try:
        d = parsedate_to_datetime(texto)
    except (TypeError, ValueError, IndexError):
        try:
            d = datetime.fromisoformat(texto.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


_RE_DOCUMENTACAO = re.compile(r"dicion[aá]rio|leia[\s_-]?me|readme", re.IGNORECASE)


def _e_documentacao(nome: str | None) -> bool:
    """Arquivo de documentação (dicionário de dados, leia-me): nenhum parser o importa."""
    return bool(_RE_DOCUMENTACAO.search(unquote(nome or "")))


def _mais_nova(refs: list[Referencia]) -> Referencia:
    """A referência de Last-Modified mais novo (sem data: a primeira importação, depois o
    primeiro MANIFESTO)."""
    datadas = [(d, r) for r in refs if (d := _data(r.last_modified)) is not None]
    if datadas:
        return max(datadas, key=lambda par: (par[0], par[1].tipo == "importacao"))[1]
    return sorted(refs, key=lambda r: r.tipo != "importacao")[0]


def _remoto(c: Consulta) -> dict:
    return {"status_http": c.status_http, "last_modified": c.last_modified, "etag": c.etag,
            "content_length": c.content_length, "url_final": c.url_final,
            "redirecionado": c.redirecionado}


def _ref_dict(r: Referencia) -> dict:
    d = asdict(r)
    return {k: v for k, v in d.items() if v is not None}


def comparar(c: Consulta, refs: list[Referencia], *, banco_consultado: bool = True
             ) -> tuple[str, str, Referencia | None, bool]:
    """(estado, detalhe, referência usada, baixado_sem_importacao) de um arquivo que
    respondeu 2xx. ``baixado_sem_importacao`` (o MANIFESTO tem uma versão que nenhuma
    importação aplicada registra) só quando as importações foram consultadas."""
    if not refs:
        return NOVO_ARQUIVO, "existe no servidor e não há registro dele (nem importação, nem " \
                             "MANIFESTO)", None, False
    ref = _mais_nova(refs)
    importacoes = [r for r in refs if r.tipo == "importacao"]
    # O dicionário de dados (e o leia-me) é baixado para LER o formato, nunca importado:
    # não vira "baixado e não importado" (o arquivo continua conferido no servidor).
    pendente = (banco_consultado and ref.tipo == "manifesto"
                and not _e_documentacao(ref.arquivo or ref.url) and (
                    not importacoes or all(_data(r.last_modified) != _data(ref.last_modified)
                                           for r in importacoes)))
    d_remoto, d_ref = _data(c.last_modified), _data(ref.last_modified)
    if d_remoto is not None and d_ref is not None:
        if d_remoto == d_ref:
            # Mesmo Last-Modified: "nova versão" pelo tamanho só se NENHUMA referência com
            # essa data tem o tamanho do servidor (o MANIFESTO registra o Content-Length;
            # a importação pode não ter tamanho remoto).
            com_tamanho = [r for r in refs
                           if _data(r.last_modified) == d_ref and r.bytes is not None]
            if (c.content_length is not None and com_tamanho
                    and all(r.bytes != c.content_length for r in com_tamanho)):
                r_t = ref if ref.bytes is not None else com_tamanho[0]
                return (NOVA_VERSAO, f"mesmo Last-Modified, tamanho diferente: {r_t.bytes} → "
                        f"{c.content_length} bytes ({r_t.origem})", ref, pendente)
            return SEM_NOVIDADE, f"Last-Modified igual ao de {ref.origem}", ref, pendente
        sentido = "mais novo" if d_remoto > d_ref else "ANTERIOR ao registrado"
        return (NOVA_VERSAO, f"Last-Modified mudou ({sentido}): {ref.last_modified} "
                f"({ref.origem}) → {c.last_modified} no servidor", ref, pendente)
    if c.etag and ref.etag:
        if c.etag == ref.etag:
            return SEM_NOVIDADE, f"ETag igual à de {ref.origem}", ref, pendente
        return NOVA_VERSAO, f"ETag mudou: {ref.etag} → {c.etag} ({ref.origem})", ref, pendente
    if c.content_length is not None and ref.bytes is not None:
        if c.content_length == ref.bytes:
            return (SEM_NOVIDADE, f"sem Last-Modified para comparar; mesmo tamanho de "
                    f"{ref.origem}", ref, pendente)
        return (NOVA_VERSAO, f"tamanho mudou: {ref.bytes} → {c.content_length} bytes "
                f"({ref.origem})", ref, pendente)
    return (NOVA_VERSAO, f"sem metadados comparáveis com {ref.origem} (o servidor ou o "
            "registro não têm Last-Modified, ETag nem tamanho): confira pela prévia (sha256)",
            ref, pendente)


def _rotulo_da_url(url: str) -> str:
    return unquote(urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]) or url


def _orgao_da_url(url: str) -> str | None:
    host = (urlparse(url).hostname or "").lower()
    if host.endswith("inep.gov.br"):
        return "INEP"
    if host.endswith("educacao.sp.gov.br"):
        return "SEDUC-SP"
    return None


def _item_arquivo(cliente, url: str, rotulo: str, orgao: str | None, refs: list[Referencia],
                  validar, *, edicao: int | None = None, conjunto: str | None = None,
                  banco_consultado: bool = True) -> Item:
    c = consultar(cliente, url, validar=validar)
    ref_usada, pendente = None, False
    if c.estado is None:
        estado, detalhe, ref_usada, pendente = comparar(c, refs,
                                                        banco_consultado=banco_consultado)
    else:
        estado, detalhe = c.estado, c.detalhe
        if refs:
            ref_usada = _mais_nova(refs)
    if pendente:
        detalhe += " — atenção: o arquivo baixado (MANIFESTO) ainda não foi importado"
    if c.redirecionado and c.estado is None:
        detalhe += f" (redirecionado para {c.url_final})"
    return Item(chave=normalizar_url(url) or url, rotulo=rotulo, orgao=orgao, url=url,
                estado=estado, detalhe=detalhe,
                edicao=edicao if edicao is not None else (
                    ref_usada.edicao if ref_usada and ref_usada.edicao else ano_do_nome(url)),
                conjunto=conjunto, remoto=_remoto(c),
                referencia=_ref_dict(ref_usada) if ref_usada else None,
                referencias=len(refs), baixado_sem_importacao=pendente)


def _recursos_ckan(corpo: bytes) -> tuple[list[dict] | None, str | None]:
    """(recursos, erro). ``erro`` = "nao_encontrado" | texto de inacessível."""
    try:
        dados = json.loads(corpo.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None, "o CKAN não devolveu JSON (provável página de login ou aviso)"
    if not isinstance(dados, dict):
        return None, "resposta inesperada do CKAN"
    if dados.get("success") is False:
        erro = dados.get("error") or {}
        tipo = str(erro.get("__type", "")) if isinstance(erro, dict) else ""
        if "not found" in tipo.lower():
            return None, NAO_ENCONTRADO
        return None, f"o CKAN recusou: {tipo or erro}"
    resultado = dados.get("result")
    if isinstance(resultado, list) and resultado and isinstance(resultado[0], dict):
        resultado = resultado[0]               # DKAN devolve uma lista com o pacote
    if not isinstance(resultado, dict):
        return None, "resposta do CKAN sem o pacote"
    recursos = [r for r in resultado.get("resources") or [] if isinstance(r, dict)
                and _texto(r.get("url"))]
    return recursos, None


def conferir(*, fontes: Iterable[FonteConhecida] = FONTES, referencias: list[Referencia],
             cliente: httpx.Client, validar: Callable[[str], None] = _validar_padrao,
             intervalo: float = 0.0, dormir: Callable[[float], None] = time.sleep,
             banco_consultado: bool | None = None) -> list[Item]:
    """Confere cada fonte e devolve os itens do relatório (ordem: catálogo, conjuntos do
    CKAN e as URLs que só as referências conhecem). Nunca grava nada.
    ``banco_consultado``: as importações registradas foram lidas (``--banco``)? Sem
    elas não se avisa "baixado e não importado" (não se sabe). Padrão: há referência de
    importação na lista."""
    if banco_consultado is None:
        banco_consultado = any(r.tipo == "importacao" for r in referencias)
    por_url: dict[str, list[Referencia]] = {}
    for r in referencias:
        chave = normalizar_url(r.url)
        if chave:
            por_url.setdefault(chave, []).append(r)
    vistos: set[str] = set()
    itens: list[Item] = []
    primeira = [True]

    def pausa():
        if not primeira[0] and intervalo > 0:
            dormir(intervalo)
        primeira[0] = False

    fontes = list(fontes)
    for f in (f for f in fontes if f.tipo == "arquivo"):
        chave = normalizar_url(f.url)
        if chave in vistos:
            continue
        vistos.add(chave)
        pausa()
        itens.append(_item_arquivo(cliente, f.url, f.rotulo, f.orgao, por_url.get(chave, []),
                                   validar, banco_consultado=banco_consultado))
    for f in (f for f in fontes if f.tipo == "ckan"):
        pausa()
        itens.extend(_conferir_ckan(cliente, f, referencias, por_url, vistos, validar, pausa,
                                    banco_consultado))
    for chave, refs in por_url.items():           # URLs que só as referências conhecem
        if chave in vistos:
            continue
        vistos.add(chave)
        url = refs[0].url
        pausa()
        itens.append(_item_arquivo(cliente, url, refs[0].arquivo or _rotulo_da_url(url),
                                   _orgao_da_url(url), refs, validar,
                                   banco_consultado=banco_consultado))
    return itens


def _conferir_ckan(cliente, f: FonteConhecida, referencias, por_url, vistos, validar,
                   pausa, banco_consultado: bool = True) -> list[Item]:
    url_api = f"{f.url}?id={quote(f.ckan_id or '', safe='-')}"
    c = consultar(cliente, url_api, validar=validar, json_ckan=True)
    base = dict(chave=f"ckan:{f.chave}", rotulo=f.rotulo, orgao=f.orgao, url=url_api,
                conjunto=f.chave, remoto=_remoto(c))
    if c.estado is not None:
        return [Item(estado=c.estado, detalhe=f"package_show: {c.detalhe}", **base)]
    recursos, erro = _recursos_ckan(c.corpo or b"")
    if erro == NAO_ENCONTRADO:
        return [Item(estado=NAO_ENCONTRADO, detalhe="o conjunto não existe mais no CKAN com "
                     "este id — conferir a página oficial", **base)]
    if erro:
        return [Item(estado=INACESSIVEL, detalhe=erro, **base)]
    # Edições já conhecidas deste conjunto: as das importações dos parsers dele e as dos
    # recursos que casam com uma referência pela URL.
    conhecidas = {r.edicao for r in referencias
                  if r.tipo == "importacao" and r.parser in f.parsers and r.edicao}
    casados, sem_ref = [], []
    for rec in recursos:
        chave = normalizar_url(rec["url"])
        nome = _texto(rec.get("name")) or _rotulo_da_url(rec["url"])
        ano = ano_do_nome(nome) or ano_do_nome(rec["url"])
        if chave in por_url:
            casados.append((rec, chave, nome, ano))
            conhecidas.update(r.edicao for r in por_url[chave] if r.edicao)
            if ano:
                conhecidas.add(ano)
        else:
            sem_ref.append((rec, chave, nome, ano))
    itens: list[Item] = []
    for rec, chave, nome, ano in casados:
        if chave in vistos:
            continue
        vistos.add(chave)
        pausa()
        itens.append(_item_arquivo(cliente, rec["url"], nome, f.orgao, por_url[chave], validar,
                                   edicao=ano, conjunto=f.chave,
                                   banco_consultado=banco_consultado))
    anteriores = []
    maior = max(conhecidas) if conhecidas else None
    for rec, chave, nome, ano in sem_ref:
        if chave in vistos:
            continue
        if ano is not None and maior is not None and ano < maior and ano not in conhecidas:
            anteriores.append(nome)
            continue
        vistos.add(chave)
        if ano is not None and ano in conhecidas:
            estado = NOVA_VERSAO
            detalhe = (f"endereço novo para a edição {ano}, já registrada com outro arquivo (a "
                       "SEDUC troca o sufixo): confira e reimporte pela prévia")
        elif ano is not None and maior is not None:
            estado, detalhe = NOVO_ARQUIVO, f"edição {ano} — mais nova que as registradas " \
                                            f"(até {maior})"
        else:
            estado, detalhe = NOVO_ARQUIVO, "recurso do conjunto sem registro (nem importação, " \
                                            "nem MANIFESTO)"
        pausa()
        cons = consultar(cliente, rec["url"], validar=validar)
        if cons.estado is not None:
            detalhe += f"; o HEAD do arquivo falhou: {cons.estado} ({cons.detalhe})"
        elif cons.last_modified:
            detalhe += f"; Last-Modified no servidor: {cons.last_modified}"
        itens.append(Item(chave=chave or rec["url"], rotulo=nome, orgao=f.orgao, url=rec["url"],
                          estado=estado, detalhe=detalhe, edicao=ano, conjunto=f.chave,
                          remoto=_remoto(cons)))
    descobertos = [i for i in itens if i.referencias == 0]
    resumo_ckan = (f"package_show: {len(recursos)} recurso(s), {len(casados)} com registro"
                   + (f", {len(descobertos)} sem registro (itens próprios)" if descobertos else "")
                   + (f", {len(anteriores)} de edições anteriores não importadas (ignorados)"
                      if anteriores else ""))
    # O item do CONJUNTO diz que o package_show respondeu e não trouxe recurso novo; quando
    # traz, quem aparece são os itens dos recursos descobertos (sem contar duas vezes).
    if descobertos:
        return itens
    return [Item(estado=SEM_NOVIDADE, detalhe=resumo_ckan, **base), *itens]


# --- Relatório ------------------------------------------------------------------------------


def resumo(itens: list[Item]) -> dict:
    contagem = Counter(i.estado for i in itens)
    return {e: contagem.get(e, 0) for e in ESTADOS}


def baixados_sem_importacao(itens: list[Item]) -> int:
    """Itens cujo arquivo baixado (MANIFESTO) ainda não foi importado — pedem atenção
    mesmo quando o servidor está ``sem_novidade``."""
    return sum(1 for i in itens if i.baixado_sem_importacao)


def pede_atencao(itens: list[Item]) -> bool:
    return any(i.estado != SEM_NOVIDADE or i.baixado_sem_importacao for i in itens)


def relatorio_texto(itens: list[Item], *, n_importacoes: int, n_manifesto: int,
                    gerado_em: str) -> str:
    linhas = [
        f"Conferência das fontes oficiais ({gerado_em}) — só metadados (HEAD e package_show "
        "do CKAN): nada foi baixado, importado nem aplicado.",
        f"Referências: {n_importacoes} importação(ões) aplicada(s) registrada(s) e "
        f"{n_manifesto} registro(s) de MANIFESTO.",
        "",
    ]
    for estado in ESTADOS:
        do_estado = [i for i in itens if i.estado == estado]
        if not do_estado:
            continue
        linhas.append(f"{ROTULO_ESTADO[estado]} ({len(do_estado)})")
        for i in do_estado:
            orgao = f"{i.orgao} · " if i.orgao else ""
            edicao = f" [{i.edicao}]" if i.edicao else ""
            if estado == SEM_NOVIDADE:
                linhas.append(f"  - {orgao}{i.rotulo}{edicao} — {i.detalhe}")
                continue
            linhas.append(f"  - {orgao}{i.rotulo}{edicao}")
            linhas.append(f"    {i.url}")
            linhas.append(f"    {i.detalhe}")
        linhas.append("")
    r = resumo(itens)
    linhas.append("Resumo: " + " · ".join(f"{e} {r[e]}" for e in ESTADOS))
    if n_pendentes := baixados_sem_importacao(itens):
        linhas.append(f"Atenção: {n_pendentes} arquivo(s) baixado(s) (MANIFESTO) ainda não "
                      "importado(s) — veja os itens marcados acima.")
    linhas.append("Nada foi aplicado. Arquivo novo ou nova versão: baixe (com autorização), "
                  "gere o pacote com o preparar quando for o caso e use a PRÉVIA da importação.")
    return "\n".join(linhas)


def relatorio_json(itens: list[Item], *, n_importacoes: int, n_manifesto: int,
                   gerado_em: str) -> str:
    return json.dumps({
        "gerado_em": gerado_em, "so_metadados": True, "nada_aplicado": True,
        "referencias": {"importacoes_aplicadas": n_importacoes, "manifesto": n_manifesto},
        "resumo": resumo(itens), "baixados_sem_importacao": baixados_sem_importacao(itens),
        "pede_atencao": pede_atencao(itens), "itens": [asdict(i) for i in itens],
    }, ensure_ascii=False, indent=2)


def contexto_tls(ca_bundle: str | Path | None = None) -> ssl.SSLContext:
    """O contexto TLS do comando — a verificação SEMPRE ligada (``CERT_REQUIRED`` e o nome
    do host conferido). As autoridades de sempre (as mesmas do httpx: ``SSL_CERT_FILE``,
    ``SSL_CERT_DIR`` ou o certifi) e, com ``--ca-bundle``, os certificados do arquivo
    SOMADOS a elas (a intermediária que o servidor não manda não tira a validação dos
    outros hosts). LEVANTA ``ssl.SSLError``/``OSError`` se o PEM não se deixa ler."""
    import certifi

    if os.environ.get("SSL_CERT_FILE"):
        ctx = ssl.create_default_context(cafile=os.environ["SSL_CERT_FILE"])
    elif os.environ.get("SSL_CERT_DIR"):
        ctx = ssl.create_default_context(capath=os.environ["SSL_CERT_DIR"])
    else:
        ctx = ssl.create_default_context(cafile=certifi.where())
    if ca_bundle:
        ctx.load_verify_locations(cafile=str(ca_bundle))
    return ctx


def main(argv: list[str] | None = None, *, transporte: httpx.BaseTransport | None = None,
         validar: Callable[[str], None] | None = None,
         agora: Callable[[], datetime] | None = None) -> int:
    """``transporte``, ``validar`` e ``agora`` são só para os testes (HTTP substituído)."""
    parser = argparse.ArgumentParser(
        prog="python -m app.services.indicadores.conferir_fontes",
        description="Confere, SÓ PELOS METADADOS (HEAD e package_show do CKAN), se as fontes "
                    "oficiais dos indicadores (INEP e SEDUC-SP) têm arquivo novo ou versão "
                    "nova, comparando com as importações registradas e o MANIFESTO local. "
                    "Nunca baixa dados, nunca aplica nada, nunca roda sozinho.")
    parser.add_argument("--dados", action="append", default=[],
                        help="pasta dos downloads oficiais: lê <pasta>/MANIFESTO.json e "
                             "<pasta>/*/MANIFESTO.json (repetível)")
    parser.add_argument("--manifesto", action="append", default=[],
                        help="um MANIFESTO.json avulso (repetível)")
    parser.add_argument("--banco",
                        help="URL SQLAlchemy de um banco para LER importacoes_indicador (ex.: "
                             "sqlite:///copia.db); nada é gravado. Sem ela, só o MANIFESTO")
    parser.add_argument("--json", action="store_true", help="saída em JSON")
    parser.add_argument("--ca-bundle",
                        help="arquivo PEM com certificados EXTRAS (ex.: a intermediária que o "
                             "servidor não manda), somados às autoridades do certifi; a "
                             "verificação TLS nunca é desligada")
    parser.add_argument("--timeout", type=float, default=20.0,
                        help="tempo máximo de cada consulta, em segundos (padrão 20)")
    parser.add_argument("--intervalo", type=float, default=1.0,
                        help="pausa entre as consultas, em segundos (padrão 1)")
    args = parser.parse_args(argv)
    for fluxo in (sys.stdout, sys.stderr):        # console Windows (cp1252) não quebra
        try:
            fluxo.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    if args.timeout <= 0 or args.intervalo < 0:
        print("Recusado: --timeout precisa ser > 0 e --intervalo, >= 0.", file=sys.stderr)
        return 2
    referencias: list[Referencia] = []
    try:
        caminhos = [Path(m).expanduser() for m in args.manifesto]
        for pasta in args.dados:
            caminhos += manifestos_da_pasta(pasta)
        for caminho in caminhos:
            referencias += referencias_do_manifesto(caminho)
        n_manifesto = len(referencias)
        if args.banco:
            referencias += referencias_do_banco(args.banco)
        ca_bundle = Path(args.ca_bundle).expanduser() if args.ca_bundle else None
        if ca_bundle is not None and not ca_bundle.is_file():
            raise ValueError(f"o --ca-bundle {ca_bundle} não existe")
        try:
            # SEMPRE verifica o certificado: o bundle só ACRESCENTA autoridades.
            tls = contexto_tls(ca_bundle)
        except (ssl.SSLError, OSError) as exc:      # PEM inválido: erro de uso, sem traceback
            qual = (f"o --ca-bundle {ca_bundle}" if ca_bundle is not None
                    else "a cadeia de certificados de SSL_CERT_FILE/SSL_CERT_DIR")
            raise ValueError(f"{qual} não se deixa ler como PEM de certificados "
                             f"({type(exc).__name__})") from exc
    except ValueError as exc:
        print(f"Recusado: {exc}", file=sys.stderr)
        return 2
    n_importacoes = len(referencias) - n_manifesto
    opcoes = {"timeout": args.timeout, "follow_redirects": False, "verify": tls}
    if transporte is not None:
        opcoes["transport"] = transporte
    with httpx.Client(**opcoes) as cliente:
        itens = conferir(referencias=referencias, cliente=cliente,
                         validar=validar or _validar_padrao, intervalo=args.intervalo,
                         banco_consultado=bool(args.banco))
    gerado_em = (agora or (lambda: datetime.now(timezone.utc)))().isoformat(timespec="seconds")
    saida = (relatorio_json if args.json else relatorio_texto)(
        itens, n_importacoes=n_importacoes, n_manifesto=n_manifesto, gerado_em=gerado_em)
    print(saida)
    return 1 if pede_atencao(itens) else 0


if __name__ == "__main__":
    sys.exit(main())
