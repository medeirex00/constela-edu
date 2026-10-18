"""Conferência MANUAL das fontes oficiais (etapa E10, decisão D12): o comando
``python -m app.services.indicadores.conferir_fontes``.

O que se garante:

* só METADADOS: HEAD nos arquivos (GET de 1 byte, sem ler o corpo, quando o HEAD é
  recusado) e o JSON do ``package_show`` no CKAN — nenhum arquivo é baixado;
* cada estado: ``sem_novidade``, ``nova_versao``, ``novo_arquivo``, ``inacessivel``
  (inclui o redirecionamento para LOGIN e a página HTML no lugar do arquivo — o defeso
  eleitoral), ``nao_encontrado`` (404/410) e ``erro_tls`` (sem desligar a verificação);
* a comparação com a última importação APLICADA (``importacoes_indicador``, só lida) e
  com o MANIFESTO local;
* no CKAN, o recurso de edição nova (``novo_arquivo``), o sufixo trocado de uma edição já
  registrada (``nova_versao``) e as edições antigas não importadas (ignoradas);
* a saída legível e ``--json``, e o código de saída.

O HTTP é SUBSTITUÍDO (``httpx.MockTransport``) e a guarda de destino também: nenhum teste
sai para a internet. As datas, tamanhos e ETags são INVENTADOS (2031–2032).
"""
import json
import ssl
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import AvaliacaoExterna, ImportacaoIndicador
from app.services.indicadores import aeeb, conferir_fontes as cf, ica, ideb, saeb_planilha, seduc

LM_A = "Mon, 02 Jun 2031 08:15:00 GMT"          # datas INVENTADAS
LM_B = "Tue, 14 Oct 2031 10:00:00 GMT"
LM_C = "Wed, 03 Mar 2032 12:30:00 GMT"
URL_X = "https://download.inep.gov.br/sintetico/arquivo_x.xlsx"
URL_Z = "https://download.inep.gov.br/sintetico/pacote_z.zip"
SO_X = (cf.FonteConhecida("x", "Arquivo X sintético", "INEP", "arquivo", URL_X, ("p_x",)),)


def _sem_guarda(destinos=None):
    def validar(url):
        if destinos is not None:
            destinos.append(url)
    return validar


class Servidor:
    """Respostas por (método, URL); registra cada requisição (para provar que nada foi
    baixado). ``padrao``: resposta das URLs não cadastradas."""

    def __init__(self, rotas=None, padrao=None):
        self.rotas = rotas or {}
        self.padrao = padrao or (lambda req: httpx.Response(404))
        self.pedidos: list[httpx.Request] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.pedidos.append(req)
        chave = (req.method, str(req.url))
        resp = self.rotas.get(chave) or self.rotas.get(("*", str(req.url)))
        if resp is None:
            return self.padrao(req)
        return resp(req) if callable(resp) else resp


def _cliente(servidor) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(servidor), follow_redirects=False)


def _head(lm=None, tamanho=None, etag=None, tipo="application/octet-stream", status=200):
    cab = {"content-type": tipo}
    if lm:
        cab["last-modified"] = lm
    if tamanho is not None:
        cab["content-length"] = str(tamanho)
    if etag:
        cab["etag"] = etag
    return httpx.Response(status, headers=cab)


def _ref(url=URL_X, lm=LM_A, tipo="manifesto", **kw):
    return cf.Referencia(origem=f"{tipo} sintético", tipo=tipo, url=url, last_modified=lm, **kw)


def _um(servidor, refs, fontes=SO_X, destinos=None) -> cf.Item:
    with _cliente(servidor) as c:
        (item,) = cf.conferir(fontes=fontes, referencias=refs, cliente=c,
                              validar=_sem_guarda(destinos))
    return item


# =============================================================================
# Estados de um arquivo (HEAD)
# =============================================================================

def test_sem_novidade_quando_o_last_modified_bate_com_a_importacao():
    s = Servidor({("HEAD", URL_X): _head(LM_A, 1200)})
    item = _um(s, [_ref(tipo="importacao", bytes=1200, edicao=2031)])
    assert item.estado == cf.SEM_NOVIDADE and "importacao sintético" in item.detalhe
    assert item.remoto["last_modified"] == LM_A and item.edicao == 2031
    assert [p.method for p in s.pedidos] == ["HEAD"]


def test_nova_versao_quando_o_last_modified_muda():
    s = Servidor({("HEAD", URL_X): _head(LM_B)})
    item = _um(s, [_ref(lm=LM_A, tipo="importacao")])
    assert item.estado == cf.NOVA_VERSAO
    assert LM_A in item.detalhe and LM_B in item.detalhe and "mais novo" in item.detalhe


def test_compara_com_a_referencia_mais_nova_e_avisa_o_baixado_nao_importado():
    """O MANIFESTO tem um download mais novo que a última importação: contra ele, sem
    novidade no servidor — mas o relatório avisa que falta importar."""
    s = Servidor({("HEAD", URL_X): _head(LM_B)})
    item = _um(s, [_ref(lm=LM_A, tipo="importacao"), _ref(lm=LM_B, tipo="manifesto")])
    assert item.estado == cf.SEM_NOVIDADE and item.baixado_sem_importacao is True
    assert "ainda não foi importado" in item.detalhe


def test_sem_o_banco_nao_avisa_baixado_nao_importado():
    """Só com o MANIFESTO (sem --banco) não se sabe o que foi importado: sem o aviso."""
    s = Servidor({("HEAD", URL_X): _head(LM_A)})
    with _cliente(s) as c:
        (item,) = cf.conferir(fontes=SO_X, referencias=[_ref(lm=LM_A)], cliente=c,
                              validar=_sem_guarda(), banco_consultado=False)
    assert item.estado == cf.SEM_NOVIDADE and item.baixado_sem_importacao is False
    assert "importado" not in item.detalhe


def test_mesmo_last_modified_e_tamanho_diferente_e_nova_versao():
    s = Servidor({("HEAD", URL_X): _head(LM_A, 999)})
    assert _um(s, [_ref(bytes=1000)]).estado == cf.NOVA_VERSAO


def test_sem_last_modified_compara_etag_e_depois_o_tamanho():
    s = Servidor({("HEAD", URL_X): _head(etag='"e1"', tamanho=10)})
    assert _um(s, [_ref(lm=None, etag='"e1"')]).estado == cf.SEM_NOVIDADE
    assert _um(s, [_ref(lm=None, etag='"e0"')]).estado == cf.NOVA_VERSAO
    s2 = Servidor({("HEAD", URL_X): _head(tamanho=10)})
    assert _um(s2, [_ref(lm=None, bytes=10)]).estado == cf.SEM_NOVIDADE
    assert _um(s2, [_ref(lm=None, bytes=11)]).estado == cf.NOVA_VERSAO
    # Nada comparável: não afirma "sem novidade" — pede a conferência pela prévia.
    sem_nada = _um(Servidor({("HEAD", URL_X): _head()}), [_ref(lm=None)])
    assert sem_nada.estado == cf.NOVA_VERSAO and "prévia" in sem_nada.detalhe


def test_novo_arquivo_quando_nao_ha_registro_nenhum():
    item = _um(Servidor({("HEAD", URL_X): _head(LM_A)}), [])
    assert item.estado == cf.NOVO_ARQUIVO and item.referencia is None


@pytest.mark.parametrize("destino", ["https://download.inep.gov.br/login?volta=x",
                                     "https://sso.exemplo.gov.br/auth/realms/x",
                                     "https://www.gov.br/inep/pt-br/defeso-eleitoral"])
def test_redirecionamento_para_login_e_inacessivel_nunca_removido(destino):
    s = Servidor({("HEAD", URL_X): httpx.Response(302, headers={"location": destino})})
    item = _um(s, [_ref()])
    assert item.estado == cf.INACESSIVEL and "login" in item.detalhe
    assert len(s.pedidos) == 1                 # não segue para a página de login


def test_pagina_html_no_lugar_do_arquivo_e_inacessivel():
    s = Servidor({("HEAD", URL_X): _head(LM_A, tipo="text/html; charset=utf-8")})
    item = _um(s, [_ref()])
    assert item.estado == cf.INACESSIVEL and "HTML" in item.detalhe


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_recusa_ou_erro_do_servidor_e_inacessivel(status):
    assert _um(Servidor({("HEAD", URL_X): httpx.Response(status)}), [_ref()]).estado == \
        cf.INACESSIVEL


@pytest.mark.parametrize("status", [404, 410])
def test_404_e_410_sao_nao_encontrado(status):
    item = _um(Servidor({("HEAD", URL_X): httpx.Response(status)}), [_ref()])
    assert item.estado == cf.NAO_ENCONTRADO and str(status) in item.detalhe


def test_timeout_e_falha_de_conexao_sao_inacessivel():
    def timeout(req):
        raise httpx.ReadTimeout("lento", request=req)

    def recusada(req):
        raise httpx.ConnectError("Connection reset by peer", request=req)

    assert _um(Servidor({("HEAD", URL_X): timeout}), [_ref()]).estado == cf.INACESSIVEL
    item = _um(Servidor({("HEAD", URL_X): recusada}), [_ref()])
    assert item.estado == cf.INACESSIVEL and "reset" in item.detalhe


def test_certificado_nao_validado_e_erro_tls():
    def tls(req):
        raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
                                 "unable to get local issuer certificate", request=req)

    item = _um(Servidor({("HEAD", URL_X): tls}), [_ref()])
    assert item.estado == cf.ERRO_TLS and "--ca-bundle" in item.detalhe


def test_destino_recusado_pela_guarda_e_inacessivel():
    def guarda(url):
        raise ValueError("host aponta para rede não-pública (10.0.0.1)")

    with _cliente(Servidor({("HEAD", URL_X): _head(LM_A)})) as c:
        (item,) = cf.conferir(fontes=SO_X, referencias=[_ref()], cliente=c, validar=guarda)
    assert item.estado == cf.INACESSIVEL and "guarda" in item.detalhe


def test_redirecionamento_comum_e_seguido_com_a_guarda_em_cada_salto():
    novo = "https://download.inep.gov.br/sintetico/movido/arquivo_x.xlsx"
    s = Servidor({("HEAD", URL_X): httpx.Response(301, headers={"location": novo}),
                  ("HEAD", novo): _head(LM_A)})
    destinos = []
    item = _um(s, [_ref()], destinos=destinos)
    assert destinos == [URL_X, novo]
    assert item.estado == cf.SEM_NOVIDADE and "redirecionado" in item.detalhe


def test_head_recusado_vira_get_de_um_byte_sem_ler_o_corpo():
    def get_parcial(req):
        assert req.headers["range"] == "bytes=0-0"
        return httpx.Response(206, headers={"last-modified": LM_A, "content-range": "bytes 0-0/4321"},
                              content=b"P")

    s = Servidor({("HEAD", URL_X): httpx.Response(405), ("GET", URL_X): get_parcial})
    item = _um(s, [_ref(bytes=4321)])
    assert item.estado == cf.SEM_NOVIDADE and item.remoto["content_length"] == 4321
    assert [p.method for p in s.pedidos] == ["HEAD", "GET"]


# =============================================================================
# CKAN da SEDUC: descobrir recursos novos
# =============================================================================

_CKAN = cf.FonteConhecida("conj", "Conjunto sintético", "SEDUC-SP", "ckan", cf.CKAN_SEDUC,
                          ("p_conj",), ckan_id="conjunto-sintetico")
_API = f"{cf.CKAN_SEDUC}?id=conjunto-sintetico"
_BASE = "https://dados.educacao.sp.gov.br/sites/default/files/"


def _rec(nome):
    return {"name": nome, "url": _BASE + nome.replace(" ", "%20")}


def _pacote(*nomes):
    return httpx.Response(200, json={"success": True,
                                     "result": {"resources": [_rec(n) for n in nomes]}})


def test_ckan_novo_ano_sufixo_trocado_e_edicoes_antigas():
    s = Servidor({
        ("GET", _API): _pacote("Arquivo Sintetico de 2029.csv", "Arquivo Sintetico de 2031_0.csv",
                               "Arquivo Sintetico de 2031_1.csv", "Arquivo Sintetico de 2032_0.csv",
                               "Dicionario sintetico.csv"),
        ("*", _BASE + "Arquivo%20Sintetico%20de%202031_0.csv"): _head(LM_A),
        ("*", _BASE + "Arquivo%20Sintetico%20de%202031_1.csv"): _head(LM_B),
        ("*", _BASE + "Arquivo%20Sintetico%20de%202032_0.csv"): _head(LM_C),
        ("*", _BASE + "Dicionario%20sintetico.csv"): _head(LM_A),
    })
    # O MANIFESTO codifica o acento/espaço de outro jeito: casa pela URL normalizada.
    refs = [_ref(url=_BASE + "Arquivo Sintetico de 2031_0.csv", lm=LM_A, edicao=2031),
            cf.Referencia(origem="importação #7", tipo="importacao", parser="p_conj",
                          edicao=2030)]
    with _cliente(s) as c:
        itens = cf.conferir(fontes=(_CKAN,), referencias=refs, cliente=c, validar=_sem_guarda())
    por_nome = {i.rotulo: i for i in itens}
    assert por_nome["Arquivo Sintetico de 2031_0.csv"].estado == cf.SEM_NOVIDADE
    sufixo = por_nome["Arquivo Sintetico de 2031_1.csv"]
    assert sufixo.estado == cf.NOVA_VERSAO and "sufixo" in sufixo.detalhe
    novo = por_nome["Arquivo Sintetico de 2032_0.csv"]
    assert novo.estado == cf.NOVO_ARQUIVO and "2032" in novo.detalhe and LM_C in novo.detalhe
    assert por_nome["Dicionario sintetico.csv"].estado == cf.NOVO_ARQUIVO
    # 2029: edição antiga não importada — ignorada, sem HEAD.
    assert "Arquivo Sintetico de 2029.csv" not in por_nome
    assert not [p for p in s.pedidos if "2029" in str(p.url)]
    # Os descobertos aparecem como itens próprios; o conjunto não é contado de novo.
    assert "ckan:conj" not in {i.chave for i in itens}
    metodos = {(p.method, str(p.url)) for p in s.pedidos}
    assert ("GET", _API) in metodos and all(m == "HEAD" for m, u in metodos if u != _API)


def test_ckan_sem_recurso_novo_tem_o_item_do_conjunto_sem_novidade():
    s = Servidor({("GET", _API): _pacote("Arquivo Sintetico de 2031_0.csv",
                                         "Arquivo Sintetico de 2029.csv"),
                  ("*", _BASE + "Arquivo%20Sintetico%20de%202031_0.csv"): _head(LM_A)})
    refs = [_ref(url=_BASE + "Arquivo%20Sintetico%20de%202031_0.csv", lm=LM_A)]
    with _cliente(s) as c:
        itens = cf.conferir(fontes=(_CKAN,), referencias=refs, cliente=c, validar=_sem_guarda())
    conjunto = next(i for i in itens if i.chave == "ckan:conj")
    assert conjunto.estado == cf.SEM_NOVIDADE and "2 recurso(s)" in conjunto.detalhe
    assert "anteriores" in conjunto.detalhe
    assert {i.estado for i in itens} == {cf.SEM_NOVIDADE}


@pytest.mark.parametrize("resposta, estado", [
    (httpx.Response(200, json={"success": False, "error": {"__type": "Not Found Error"}}),
     cf.NAO_ENCONTRADO),
    (httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html>login</html>"),
     cf.INACESSIVEL),
    (httpx.Response(302, headers={"location": "https://dados.educacao.sp.gov.br/user/login"}),
     cf.INACESSIVEL),
    (httpx.Response(404), cf.NAO_ENCONTRADO),
    (httpx.Response(503), cf.INACESSIVEL),
])
def test_ckan_que_falha(resposta, estado):
    with _cliente(Servidor({("GET", _API): resposta})) as c:
        (item,) = cf.conferir(fontes=(_CKAN,), referencias=[], cliente=c,
                              validar=_sem_guarda())
    assert item.estado == estado and item.chave == "ckan:conj"


def test_urls_que_so_as_referencias_conhecem_tambem_sao_conferidas():
    s = Servidor({("HEAD", URL_X): _head(LM_A), ("HEAD", URL_Z): httpx.Response(404)})
    with _cliente(s) as c:
        itens = cf.conferir(fontes=SO_X, referencias=[_ref(), _ref(url=URL_Z, arquivo="z.zip")],
                            cliente=c, validar=_sem_guarda())
    assert [(i.url, i.estado) for i in itens] == [(URL_X, cf.SEM_NOVIDADE),
                                                 (URL_Z, cf.NAO_ENCONTRADO)]
    assert itens[1].orgao == "INEP" and itens[1].rotulo == "z.zip"


def test_intervalo_entre_as_consultas():
    pausas = []
    s = Servidor({("HEAD", URL_X): _head(LM_A), ("HEAD", URL_Z): _head(LM_A)})
    with _cliente(s) as c:
        cf.conferir(fontes=SO_X, referencias=[_ref(url=URL_Z)], cliente=c,
                    validar=_sem_guarda(), intervalo=0.5, dormir=pausas.append)
    assert pausas == [0.5]


# =============================================================================
# Referências: MANIFESTO e importacoes_indicador (só leitura)
# =============================================================================

def test_manifesto_nos_dois_formatos(tmp_path):
    m = tmp_path / "MANIFESTO.json"
    m.write_text(json.dumps([
        {"url": URL_X, "arquivo": "arquivo_x_2031.xlsx", "last_modified": LM_A, "bytes": 120,
         "sha256": "ab" * 32},
        {"url_zip": URL_Z, "entrada": "DADOS/T.csv", "arquivo": "pacote_z_2032__T.csv",
         "zip_last_modified": LM_B, "zip_bytes": "999", "sha256": "cd" * 32},
        {"url": "https://download.inep.gov.br/falho.xlsx", "ok": False},
        "lixo",
    ]), encoding="utf-8")
    a, b = cf.referencias_do_manifesto(m)
    assert (a.url, a.last_modified, a.bytes, a.sha256, a.edicao) == (URL_X, LM_A, 120, "ab" * 32,
                                                                    2031)
    # Entrada de zip: o tamanho e a data que valem são os do ZIP; o sha256 é da entrada.
    assert (b.url, b.last_modified, b.bytes, b.sha256, b.edicao) == (URL_Z, LM_B, 999, None, 2032)
    assert a.origem == f"MANIFESTO {tmp_path.name}/MANIFESTO.json"
    sub = tmp_path / "fonte_a"
    sub.mkdir()
    (sub / "MANIFESTO.json").write_text("[]", encoding="utf-8")
    assert cf.manifestos_da_pasta(tmp_path) == [m, sub / "MANIFESTO.json"]
    ruim = tmp_path / "ruim.json"
    ruim.write_text("{nao é json", encoding="utf-8")
    with pytest.raises(ValueError):
        cf.referencias_do_manifesto(ruim)


def _banco_sintetico(tmp_path, *importacoes: dict, nome="copia.db") -> tuple[Path, str]:
    """Um SQLite descartável com ``importacoes_indicador`` (dados INVENTADOS)."""
    caminho = tmp_path / nome
    url = f"sqlite:///{caminho.as_posix()}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    comum = dict(parser_versao="1", fonte_nome="Fonte sintética", arquivo_bytes=50,
                 codigo_territorio_alvo="3599999", edicao_arquivo=2031)
    with Session(engine) as s:
        av = AvaliacaoExterna(chave="ica", nome="ICA")
        s.add(av)
        s.flush()
        s.add_all([ImportacaoIndicador(avaliacao_id=av.id, **{**comum, **imp})
                   for imp in importacoes])
        s.commit()
    engine.dispose()
    return caminho, url


def _pacote_zip(url, lm, modo, zip_bytes, **extra) -> dict:
    """Uma importação ``pacote_cli`` do AEEB com a origem do manifesto do pacote."""
    return dict(parser="inep_aeeb_agregados", arquivo_nome="pacote.zip", arquivo_sha256="11" * 32,
                url_origem=url, last_modified_origem=lm, modo="pacote_cli", status="aplicada",
                resumo={"pacote": {"origem": {"modo": modo, "etag": extra.get("etag"),
                                              "zip_bytes": zip_bytes,
                                              "zip_sha256": extra.get("zip_sha256")}}})


def test_referencias_do_banco_le_so_as_aplicadas(tmp_path):
    caminho = tmp_path / "copia.db"
    url = f"sqlite:///{caminho.as_posix()}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    comum = dict(parser_versao="1", fonte_nome="Fonte sintética", arquivo_bytes=50,
                 codigo_territorio_alvo="3599999", edicao_arquivo=2031)
    with Session(engine) as s:
        av = AvaliacaoExterna(chave="ica", nome="ICA")
        s.add(av)
        s.flush()
        s.add_all([
            ImportacaoIndicador(avaliacao_id=av.id, parser="inep_aeeb_agregados",
                                arquivo_nome="pacote.zip", arquivo_sha256="11" * 32,
                                url_origem=URL_Z, last_modified_origem=LM_A, modo="pacote_cli",
                                status="aplicada",
                                resumo={"pacote": {"origem": {"modo": "http_range",
                                                              "etag": '"z1"', "zip_bytes": 777,
                                                              "zip_sha256": "22" * 32}}},
                                **comum),
            ImportacaoIndicador(avaliacao_id=av.id, parser="inep_ica_municipios",
                                arquivo_nome="x.xlsx", arquivo_sha256="33" * 32, url_origem=URL_X,
                                last_modified_origem=LM_B, modo="upload", status="aplicada",
                                **comum),
            ImportacaoIndicador(avaliacao_id=av.id, parser="inep_ica_municipios",
                                arquivo_nome="x.xlsx", arquivo_sha256="44" * 32, url_origem=URL_X,
                                last_modified_origem=LM_C, modo="upload", status="previa",
                                **comum),
            ImportacaoIndicador(avaliacao_id=av.id, parser="inep_ica_municipios",
                                arquivo_nome="x.xlsx", arquivo_sha256="55" * 32, url_origem=URL_X,
                                last_modified_origem=LM_C, modo="upload", status="desfeita",
                                **comum),
        ])
        s.commit()
    antes = caminho.stat().st_mtime_ns, caminho.read_bytes()
    upload, pacote = sorted(cf.referencias_do_banco(url), key=lambda r: r.url)
    assert (pacote.url, pacote.last_modified, pacote.etag, pacote.bytes, pacote.sha256,
            pacote.parser, pacote.edicao) == (URL_Z, LM_A, '"z1"', 777, "22" * 32,
                                              "inep_aeeb_agregados", 2031)
    assert (upload.url, upload.last_modified, upload.bytes, upload.sha256) == (
        URL_X, LM_B, 50, "33" * 32)
    assert pacote.origem.startswith("importação #") and pacote.tipo == "importacao"
    assert caminho.read_bytes() == antes[1]          # nada gravado no banco
    engine.dispose()
    # Caminho SQLite inexistente (erro de digitação): recusado SEM criar arquivo vazio.
    with pytest.raises(ValueError, match="não existe"):
        cf.referencias_do_banco(f"sqlite:///{(tmp_path / 'vazio.db').as_posix()}")
    assert not (tmp_path / "vazio.db").exists()


def test_pacote_zip_local_nao_usa_o_tamanho_do_zip_local_como_o_do_servidor(tmp_path):
    """No ``zip_local`` (o AEEB vem de um zip REDUZIDO, sem o TS_ALUNO) o zip_bytes é o
    do arquivo LOCAL: não vale como o tamanho remoto. Só o ``http_range`` registra o do
    servidor (o total do Content-Range)."""
    _, url = _banco_sintetico(
        tmp_path,
        _pacote_zip(URL_Z, LM_A, "zip_local", 3210, zip_sha256="aa" * 32),
        _pacote_zip(URL_X, LM_A, "http_range", 98765, etag='"x1"'),
        dict(parser="seduc_iee", arquivo_nome="saeb.xlsx", arquivo_sha256="bb" * 32,
             url_origem="https://download.inep.gov.br/sintetico/p.xlsx", last_modified_origem=LM_A,
             modo="pacote_cli", status="aplicada",
             resumo={"pacote": {"origem": {"modo": "planilha_local", "zip_bytes": None}}}))
    por_url = {r.url: r for r in cf.referencias_do_banco(url)}
    assert (por_url[URL_Z].bytes, por_url[URL_Z].sha256) == (None, None)
    assert (por_url[URL_X].bytes, por_url[URL_X].etag) == (98765, '"x1"')
    assert por_url["https://download.inep.gov.br/sintetico/p.xlsx"].bytes is None


def test_cli_banco_com_pacote_zip_local_e_mesmo_last_modified_e_sem_novidade(tmp_path, capsys):
    """O caso real do alarme falso: pacote ``zip_local`` com zip_bytes (local) diferente
    do Content-Length e o MESMO Last-Modified — sem novidade, com e sem o MANIFESTO."""
    _, url = _banco_sintetico(tmp_path, _pacote_zip(URL_Z, LM_A, "zip_local", 3210))
    so_z = (cf.FonteConhecida("z", "Pacote Z sintético", "INEP", "arquivo", URL_Z, ("p",)),)
    s = Servidor({("HEAD", URL_Z): _head(LM_A, 4_444_444)})
    with _cliente(s) as c:
        (item,) = cf.conferir(fontes=so_z, referencias=cf.referencias_do_banco(url), cliente=c,
                              validar=_sem_guarda(), banco_consultado=True)
    assert item.estado == cf.SEM_NOVIDADE, item.detalhe
    # Pela linha de comando, com o MANIFESTO (que registra o tamanho do servidor): código 0.
    m = tmp_path / "MANIFESTO.json"
    m.write_text(json.dumps([{"url_zip": URL_Z, "zip_last_modified": LM_A,
                              "zip_bytes": 4_444_444, "arquivo": "pacote_z_2031__T.csv"}]),
                 encoding="utf-8")
    rotas = {("HEAD", f.url): httpx.Response(404) for f in cf.FONTES if f.tipo == "arquivo"}
    codigo = cf.main(["--manifesto", str(m), "--banco", url, "--json", "--intervalo", "0"],
                     transporte=httpx.MockTransport(Servidor({**rotas, ("HEAD", URL_Z):
                                                               _head(LM_A, 4_444_444)})),
                     validar=_sem_guarda())
    dados = json.loads(capsys.readouterr().out)
    (z,) = [i for i in dados["itens"] if i["url"] == URL_Z]
    assert z["estado"] == cf.SEM_NOVIDADE and z["baixado_sem_importacao"] is False
    assert dados["resumo"]["nova_versao"] == 0
    assert codigo == 1                    # só pelos 404 das outras URLs do catálogo aqui


def test_mesmo_last_modified_vale_o_tamanho_de_qualquer_referencia_da_mesma_data():
    """A importação tem um tamanho que não é o do servidor; o MANIFESTO da mesma data tem
    o do servidor: sem novidade. Se nenhuma referência da data tem o tamanho, nova versão."""
    s = Servidor({("HEAD", URL_X): _head(LM_A, 5000)})
    refs = [_ref(tipo="importacao", bytes=1234), _ref(tipo="manifesto", bytes=5000)]
    assert _um(s, refs).estado == cf.SEM_NOVIDADE
    refs_ruins = [_ref(tipo="importacao", bytes=1234), _ref(tipo="manifesto", bytes=4999)]
    item = _um(s, refs_ruins)
    assert item.estado == cf.NOVA_VERSAO and "1234 → 5000" in item.detalhe


def test_url_do_banco_nunca_sai_com_a_senha(tmp_path, capsys):
    assert cf.url_sem_senha("postgresql+psycopg://leitor:segredo@127.0.0.1:5999/x") == \
        "postgresql+psycopg://leitor:***@127.0.0.1:5999/x"
    assert cf.url_sem_senha("isto não é url") == "<url inválida>"
    # Banco que não abre (conexão recusada no loopback, porta fechada): a mensagem do
    # comando não traz a senha.
    codigo = cf.main(["--banco",
                      "postgresql+psycopg://leitor:segredo@127.0.0.1:1/x?connect_timeout=3"])
    err = capsys.readouterr().err
    assert codigo == 2 and "Recusado" in err
    assert "segredo" not in err and "leitor:***@" in err
    # SQLite inexistente, com usuário e senha na URL: recusado, sem a senha, nada criado.
    codigo = cf.main(["--banco", f"sqlite://u:segredo@/{(tmp_path / 'nao_existe.db').as_posix()}"])
    err = capsys.readouterr().err
    assert codigo == 2 and "segredo" not in err
    assert not (tmp_path / "nao_existe.db").exists()


# =============================================================================
# Linha de comando
# =============================================================================

def _manifesto_de_tudo(tmp_path, lm=LM_A) -> Path:
    """Um MANIFESTO sintético com TODAS as URLs de arquivo do catálogo e um recurso por
    conjunto do CKAN (datas INVENTADAS)."""
    registros = [{"url": f.url, "arquivo": f.url.rsplit("/", 1)[-1], "last_modified": lm}
                 for f in cf.FONTES if f.tipo == "arquivo"]
    registros += [{"url": _BASE + f"{f.chave}_2031_0.csv", "arquivo": f"{f.chave}_2031_0.csv",
                   "last_modified": lm} for f in cf.FONTES if f.tipo == "ckan"]
    caminho = tmp_path / "MANIFESTO.json"
    caminho.write_text(json.dumps(registros), encoding="utf-8")
    return caminho


def _servidor_de_tudo(lm_arquivos=LM_A) -> Servidor:
    rotas = {("HEAD", f.url): _head(lm_arquivos) for f in cf.FONTES if f.tipo == "arquivo"}
    for f in cf.FONTES:
        if f.tipo == "ckan":
            api = f"{f.url}?id={cf.quote(f.ckan_id, safe='-')}"
            rotas[("GET", api)] = httpx.Response(200, json={"success": True, "result": {
                "resources": [{"name": f"{f.chave}_2031_0.csv",
                               "url": _BASE + f"{f.chave}_2031_0.csv"}]}})
            rotas[("HEAD", _BASE + f"{f.chave}_2031_0.csv")] = _head(LM_A)
    return Servidor(rotas)


def test_cli_tudo_sem_novidade_sai_com_0(tmp_path, capsys):
    s = _servidor_de_tudo()
    codigo = cf.main(["--manifesto", str(_manifesto_de_tudo(tmp_path)), "--intervalo", "0"],
                     transporte=httpx.MockTransport(s), validar=_sem_guarda())
    texto = capsys.readouterr().out
    assert codigo == 0, texto
    assert "SEM NOVIDADE" in texto and "nada foi baixado" in texto
    assert "Resumo: nova_versao 0 · novo_arquivo 0" in texto
    # Só metadados: HEAD nos arquivos e GET só no JSON do CKAN.
    assert all(p.method == "HEAD" or "/api/3/action/package_show" in str(p.url)
               for p in s.pedidos)


def test_cli_json_com_novidade_sai_com_1(tmp_path, capsys):
    s = _servidor_de_tudo(lm_arquivos=LM_B)            # o servidor tem outra data
    codigo = cf.main(["--dados", str(tmp_path), "--json", "--intervalo", "0"],
                     transporte=httpx.MockTransport(s), validar=_sem_guarda(),
                     agora=lambda: __import__("datetime").datetime(2032, 1, 5, 9, 0))
    dados = json.loads(capsys.readouterr().out)
    assert codigo == 1
    assert dados["so_metadados"] is True and dados["nada_aplicado"] is True
    # A pasta não tem MANIFESTO: todo arquivo do catálogo e o recurso de cada conjunto do
    # CKAN são "novo_arquivo" (não há registro de nenhum).
    assert dados["resumo"]["novo_arquivo"] == len(cf.FONTES)
    assert dados["gerado_em"] == "2032-01-05T09:00:00"


def test_cli_json_compara_com_o_manifesto_da_pasta(tmp_path, capsys):
    sub = tmp_path / "inep"
    sub.mkdir()
    _manifesto_de_tudo(sub)
    s = _servidor_de_tudo(lm_arquivos=LM_B)
    codigo = cf.main(["--dados", str(tmp_path), "--json", "--intervalo", "0"],
                     transporte=httpx.MockTransport(s), validar=_sem_guarda())
    dados = json.loads(capsys.readouterr().out)
    assert codigo == 1
    n_arquivos = sum(1 for f in cf.FONTES if f.tipo == "arquivo")
    assert dados["resumo"]["nova_versao"] == n_arquivos
    item = next(i for i in dados["itens"] if i["estado"] == "nova_versao")
    assert item["referencia"]["last_modified"] == LM_A and item["remoto"]["last_modified"] == LM_B


def test_cli_erros_de_uso_saem_com_2(tmp_path, capsys):
    assert cf.main(["--manifesto", str(tmp_path / "nao_existe.json")]) == 2
    assert cf.main(["--dados", str(tmp_path / "nao_existe")]) == 2
    assert cf.main(["--ca-bundle", str(tmp_path / "nao_existe.pem")]) == 2
    assert cf.main(["--timeout", "0"]) == 2
    assert "Recusado" in capsys.readouterr().err


def _ca_sintetica(caminho: Path) -> Path:
    """Um certificado de AC INVENTADO (autoassinado, gerado na hora) em PEM."""
    from datetime import datetime as dt, timedelta, timezone as tz

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    chave = ec.generate_private_key(ec.SECP256R1())
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "AC Intermediaria Sintetica")])
    agora = dt.now(tz.utc)
    cert = (x509.CertificateBuilder().subject_name(nome).issuer_name(nome)
            .public_key(chave.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(agora - timedelta(days=1)).not_valid_after(agora + timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(chave, hashes.SHA256()))
    caminho.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return caminho


def test_a_verificacao_tls_nunca_e_desligada_e_o_bundle_soma(tmp_path, monkeypatch, capsys):
    """Sem e com --ca-bundle o contexto verifica (CERT_REQUIRED + nome do host); o bundle
    SOMA a cadeia às autoridades de sempre (o certifi continua lá) — não as substitui."""
    vistos = []
    original = httpx.Client

    def cliente(**kw):
        vistos.append(kw.get("verify"))
        return original(**{k: v for k, v in kw.items() if k != "verify"})

    monkeypatch.setattr(cf.httpx, "Client", cliente)
    pem = _ca_sintetica(tmp_path / "intermediaria.pem")
    t = httpx.MockTransport(_servidor_de_tudo())
    cf.main(["--intervalo", "0"], transporte=t, validar=_sem_guarda())
    cf.main(["--intervalo", "0", "--ca-bundle", str(pem)], transporte=t, validar=_sem_guarda())
    capsys.readouterr()
    sem, com = vistos
    for ctx in (sem, com):
        assert isinstance(ctx, ssl.SSLContext)
        assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname is True
    base = cf.contexto_tls(None).cert_store_stats()["x509_ca"]
    assert base > 1                                         # as autoridades de sempre
    assert sem.cert_store_stats()["x509_ca"] == base
    assert com.cert_store_stats()["x509_ca"] == base + 1    # SOMOU a intermediária
    fonte = Path(cf.__file__).read_text(encoding="utf-8")
    assert "verify=False" not in fonte and "verify\": False" not in fonte
    assert "CERT_NONE" not in fonte and "check_hostname = False" not in fonte


def test_ca_bundle_invalido_e_erro_de_uso_sem_traceback(tmp_path, capsys):
    ruim = tmp_path / "ruim.pem"
    ruim.write_text("-----BEGIN CERTIFICATE-----\nnao é certificado\n", encoding="utf-8")
    assert cf.main(["--ca-bundle", str(ruim)]) == 2
    err = capsys.readouterr().err
    assert "Recusado" in err and "PEM" in err and "Traceback" not in err


def test_baixado_e_nao_importado_pede_atencao_no_codigo_de_saida(tmp_path, capsys):
    """Servidor sem novidade, mas o MANIFESTO tem uma versão que nenhuma importação
    aplicada registra: código 1 e a contagem no texto e no JSON."""
    _, url = _banco_sintetico(tmp_path, _pacote_zip(URL_Z, LM_A, "http_range", 10))
    m = tmp_path / "MANIFESTO.json"
    m.write_text(json.dumps([{"url_zip": URL_Z, "zip_last_modified": LM_B, "zip_bytes": 10,
                              "arquivo": "pacote_z_2031__T.csv"}]), encoding="utf-8")
    so_z = (cf.FonteConhecida("z", "Pacote Z sintético", "INEP", "arquivo", URL_Z, ("p",)),)
    s = Servidor({("HEAD", URL_Z): _head(LM_B, 10)})
    refs = cf.referencias_do_manifesto(m) + cf.referencias_do_banco(url)
    with _cliente(s) as c:
        itens = cf.conferir(fontes=so_z, referencias=refs, cliente=c, validar=_sem_guarda(),
                            banco_consultado=True)
    assert [i.estado for i in itens] == [cf.SEM_NOVIDADE] and itens[0].baixado_sem_importacao
    assert cf.pede_atencao(itens) and cf.baixados_sem_importacao(itens) == 1
    texto = cf.relatorio_texto(itens, n_importacoes=1, n_manifesto=1, gerado_em="2032-01-05")
    assert "1 arquivo(s) baixado(s) (MANIFESTO) ainda não importado(s)" in texto
    dados = json.loads(cf.relatorio_json(itens, n_importacoes=1, n_manifesto=1,
                                         gerado_em="2032-01-05"))
    assert dados["baixados_sem_importacao"] == 1 and dados["pede_atencao"] is True
    # Tudo sem novidade e nada pendente: não pede atenção.
    limpo = [cf.Item(chave="k", rotulo="r", orgao=None, url=URL_Z, estado=cf.SEM_NOVIDADE,
                     detalhe="")]
    assert not cf.pede_atencao(limpo)
    # O dicionário de dados baixado nunca é importado (nenhum parser o lê): sem o aviso.
    url_dic = _BASE + "Dicionario%20de%20dados%20sintetico_2.csv"
    so_dic = (cf.FonteConhecida("d", "Dicionário sintético", "SEDUC-SP", "arquivo", url_dic, ("p",)),)
    ref_dic = cf.Referencia(origem="MANIFESTO sintético", tipo="manifesto", url=url_dic,
                            last_modified=LM_A, arquivo="Dicionario de dados sintetico_2.csv")
    with _cliente(Servidor({("HEAD", url_dic): _head(LM_A)})) as c:
        itens = cf.conferir(fontes=so_dic, referencias=[ref_dic], cliente=c,
                            validar=_sem_guarda(), banco_consultado=True)
    assert [i.estado for i in itens] == [cf.SEM_NOVIDADE]
    assert not itens[0].baixado_sem_importacao and not cf.pede_atencao(itens)


def test_caminhos_com_til_sao_expandidos(tmp_path, monkeypatch, capsys):
    """``~`` vale em --dados, --manifesto, --ca-bundle e no caminho do SQLite do --banco
    (o PowerShell não o expande)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    sub = tmp_path / "dados" / "inep"
    sub.mkdir(parents=True)
    _manifesto_de_tudo(sub)
    _manifesto_de_tudo(tmp_path)
    _ca_sintetica(tmp_path / "intermediaria.pem")
    _banco_sintetico(tmp_path, _pacote_zip(URL_Z, LM_A, "http_range", 10), nome="copia.db")
    s = _servidor_de_tudo()
    codigo = cf.main(["--dados", "~/dados", "--manifesto", "~/MANIFESTO.json",
                      "--ca-bundle", "~/intermediaria.pem", "--banco", "sqlite:///~/copia.db",
                      "--json", "--intervalo", "0"],
                     transporte=httpx.MockTransport(s), validar=_sem_guarda())
    saida = capsys.readouterr()
    assert codigo in (0, 1), saida.err
    dados = json.loads(saida.out)
    # Cada MANIFESTO sintético tem um registro por fonte do catálogo (arquivo ou CKAN).
    assert dados["referencias"] == {"importacoes_aplicadas": 1, "manifesto": 2 * len(cf.FONTES)}


# =============================================================================
# O catálogo
# =============================================================================

def test_catalogo_usa_os_parsers_do_constela_e_so_hosts_oficiais_em_https():
    parsers = {ica.PARSER_MUNICIPIOS, ica.PARSER_UFS, aeeb.PARSER, ideb.PARSER,
               ideb.PARSER_MUNICIPIOS, ideb.PARSER_UF_BRASIL, saeb_planilha.PARSER, *seduc.PARSERS}
    assert {p for f in cf.FONTES for p in f.parsers} == parsers
    for f in cf.FONTES:
        assert f.url.startswith("https://"), f.chave
        assert cf._orgao_da_url(f.url) == f.orgao, f.chave
        assert (f.tipo == "ckan") == (f.ckan_id is not None), f.chave
    assert len({f.chave for f in cf.FONTES}) == len(cf.FONTES)
    assert len({cf.normalizar_url(f.url) for f in cf.FONTES if f.tipo == "arquivo"}) == \
        sum(1 for f in cf.FONTES if f.tipo == "arquivo")


def test_normalizar_url_e_ano_do_nome():
    assert cf.normalizar_url(_BASE + "Profici%C3%AAncia%20de%202031_0.csv") == \
        cf.normalizar_url(_BASE + "Proficiência de 2031_0.csv")
    assert cf.normalizar_url("HTTPS://Download.INEP.gov.br/a/b.zip/") == \
        "https://download.inep.gov.br/a/b.zip"
    assert cf.ano_do_nome("Indice de Excelencia Educacional 2031-2032_0.csv") == 2031
    assert cf.ano_do_nome("Dicionario de dados - IEE_2.csv") is None
    assert cf.ano_do_nome(None) is None
