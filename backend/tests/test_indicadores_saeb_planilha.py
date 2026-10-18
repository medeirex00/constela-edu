"""Planilha do SAEB por Brasil, estados e municípios (etapa E7): o parser
``inep_saeb_planilha``, a linha de comando ``preparar`` → PACOTE recortado →
prévia/aplicação/desfazer da família do Saeb e a regressão das consultas.

FIXTURES SINTÉTICAS no layout REAL das planilhas do INEP: a aba "Dicionário" (primeira
ou não), as abas de dados reconhecidas pelo CONTEÚDO (nomes que não dizem nada), a linha
de rótulos legíveis abaixo do cabeçalho técnico (2021), a planilha sem ``ANO_SAEB``
(2019, edição pelo nome do arquivo), estados sem ``CAPITAL``, a caixa variável dos nomes
(``MEDIA_5_LP`` × ``nivel_0_LP5``), Total × Urbana/Rural, Capital/Interior, as
dependências por extenso, os níveis em percentual e em fração, "-", "ND" e célula vazia,
o 2º ano (amostral) e a taxa de alfabetização de 2021. NADA aqui é dado do INEP: o
município, os nomes, as datas e TODOS os números são INVENTADOS (D13) — e ficam longe
da faixa dos oficiais.
"""
import csv
import hashlib
import io
import json
import re
import zipfile
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
from sqlalchemy import func, select

from app.core.security import hash_senha
from app.main import app
from app.models import ImportacaoIndicador, IndicadorReferencia, Rede, ResultadoAvaliacao, Usuario
from app.services import avaliacoes as svc
from app.services.avaliacoes import ImportacaoRecusada
from app.services.indicadores import escalas, pacote, pacote_saeb, pipeline_saeb, preparar
from app.services.indicadores import saeb_planilha as sp

MUN = "3599999"                # IBGE SINTÉTICO (não existe)
OUTRO_MUN = "3599998"
NOME_MUN = "Cidade Sintética"
AGORA = datetime(2031, 5, 14, 9, 30)          # data INVENTADA
DATA_PLANILHA = datetime(2031, 6, 2, 8, 15)   # data INVENTADA (docProps/core.xml)
DATA_NOVA = datetime(2031, 9, 1, 10, 0)       # data INVENTADA (a planilha "mais nova")

# Distribuições SINTÉTICAS por nível (1 casa; soma 100), deslocadas pela semente da linha.
_DIST_LP5 = [18.2, 21.5, 17.3, 13.9, 10.4, 7.6, 5.1, 3.4, 1.8, 0.8]
_DIST_MT5 = [12.1, 16.4, 18.7, 16.2, 13.5, 9.8, 6.3, 3.9, 2.0, 0.8, 0.3]
_DIST_2 = [9.3, 12.6, 15.8, 17.1, 15.4, 12.2, 9.1, 5.6, 2.9]

DEPENDENCIAS = ("Municipal", "Estadual", "Total - Federal, Estadual e Municipal",
                "Total - Federal, Estadual, Municipal e Privada", "Federal", "Privada",
                "Total - Estadual e Municipal")
_ROTULOS_2021 = {"ANO_SAEB": "Edição do Saeb", "ID": "Identificador", "CO_UF": "Código do estado",
                 "NO_UF": "Estado", "CO_MUNICIPIO": "Código do Município",
                 "NO_MUNICIPIO": "Município", "DEPENDENCIA_ADM": "Dependência Administrativa",
                 "LOCALIZACAO": "Localização", "CAPITAL": "Área "}


def _dist(base: list[float], semente: int, fracao: bool = False) -> list[float]:
    """A distribuição deslocada (0,3 por semente do 1º para o 2º nível; soma intacta)."""
    v = list(base)
    v[0], v[1] = round(v[0] - 0.3 * semente, 1), round(v[1] + 0.3 * semente, 1)
    return [x / 100 for x in v] if fracao else v


def _medidas(segundo_ano: bool, tx: bool, quinto: bool = True, caixa: str = "real") -> list[str]:
    def nivel(k, comp):
        nome = f"nivel_{k}_{comp}"
        return nome.upper() if caixa == "maiuscula" else nome

    cols = []
    if segundo_ano:
        cols += ["MEDIA_2_LP", "MEDIA_2_MT"]
    if quinto:
        cols += ["MEDIA_5_LP", "MEDIA_5_MT", "MEDIA_9_LP"]
    if tx:
        cols.insert(0, "TX_ALFABETIZADO")
    if segundo_ano:
        cols += [nivel(k, "LP2") for k in range(9)] + [nivel(k, "MT2") for k in range(9)]
    if quinto:
        cols += ([nivel(k, "LP5") for k in range(10)] + [nivel(k, "MT5") for k in range(11)]
                 + [nivel(k, "LP9") for k in range(9)])
    return cols


def _valores(semente: int, colunas: list[str], *, fracao=False, trocas=None) -> dict:
    """Os números de uma linha (INVENTADOS e longe da faixa dos oficiais): médias do 5º
    ano 10x–13x; do 2º ano 61x–64x; taxa 1x; os níveis pelas distribuições acima."""
    v = {"MEDIA_5_LP": round(101.3 + semente * 1.7, 1), "MEDIA_5_MT": round(108.6 + semente * 1.9, 1),
         "MEDIA_9_LP": 150.5, "MEDIA_2_LP": round(612.4 + semente * 2.3, 1),
         "MEDIA_2_MT": round(621.7 + semente * 2.1, 1),
         "TX_ALFABETIZADO": round(11.2 + semente * 0.7, 1)}
    for comp, base in (("LP5", _DIST_LP5), ("MT5", _DIST_MT5), ("LP2", _DIST_2), ("MT2", _DIST_2),
                       ("LP9", _DIST_2)):
        for k, x in enumerate(_dist(base, semente, fracao)):
            v[f"NIVEL_{k}_{comp}"] = x
    saida = {c: v[c.upper()] for c in colunas}
    saida.update(trocas or {})
    return saida


def _linhas_do_territorio(tipo: str, codigo, nome, *, capital=True, semente0=0):
    """(dependência, localização, capital, semente) de um território: todas as
    dependências, Total/Urbana/Rural e (Brasil/UF) Total/Capital."""
    saida = []
    s = semente0
    for dep in DEPENDENCIAS:
        for loc in ("Total", "Urbana", "Rural"):
            for cap in (("Total", "Capital") if capital and tipo != "municipio" else ("",)):
                saida.append((dep, loc, cap, s % 7))
                s += 1
    return saida


def aba_saeb(ws, tipo: str, territorios, *, ano=2025, segundo_ano=False, tx=False,
             quinto=True, capital=True, rotulos=False, fracao=False, caixa="real",
             trocas=None, sem_ano=False):
    """Uma aba de dados no layout real. ``territorios``: lista de (código, nome)."""
    ids = {"brasil": ["ANO_SAEB", "ID", "DEPENDENCIA_ADM", "LOCALIZACAO", "CAPITAL"],
           "uf": ["ANO_SAEB", "CO_UF", "NO_UF", "DEPENDENCIA_ADM", "LOCALIZACAO", "CAPITAL"],
           "municipio": ["ANO_SAEB", "CO_UF", "NO_UF", "CO_MUNICIPIO", "NO_MUNICIPIO",
                         "DEPENDENCIA_ADM", "LOCALIZACAO"]}[tipo]
    if sem_ano:
        ids = [c for c in ids if c != "ANO_SAEB"]
    if not capital:
        ids = [c for c in ids if c != "CAPITAL"]
    colunas = _medidas(segundo_ano, tx, quinto, caixa)
    ws.append(ids + colunas)
    if rotulos:
        ws.append([_ROTULOS_2021[c] for c in ids] + [f"Rótulo de {c}" for c in colunas])
    for codigo, nome in territorios:
        for dep, loc, cap, semente in _linhas_do_territorio(tipo, codigo, nome, capital=capital):
            ident = {"ANO_SAEB": ano, "ID": "Brasil",
                     "CO_UF": int(str(codigo)[:2]) if tipo != "brasil" else None,
                     "NO_UF": "São Paulo" if str(codigo).startswith("35") else "Outra UF",
                     "CO_MUNICIPIO": int(codigo) if tipo == "municipio" else None,
                     "NO_MUNICIPIO": nome, "DEPENDENCIA_ADM": dep, "LOCALIZACAO": loc,
                     "CAPITAL": cap}
            if tipo == "uf":
                ident["NO_UF"] = nome
            vals = _valores(semente, colunas, fracao=fracao,
                            trocas=(trocas or {}).get((str(codigo), dep, loc, cap)))
            if dep == "Estadual" and tipo == "municipio":
                vals = dict.fromkeys(colunas)                 # sem escola estadual: vazio
            ws.append([ident[c] for c in ids] + [vals[c] for c in colunas])


def _dicionario(ws):
    ws.append(["Dicionário - Planilhas sintéticas"])
    ws.append(["Variável", "Descrição"])
    for nome in ("ANO_SAEB", "DEPENDENCIA_ADM", "LOCALIZACAO", "MEDIA_5_LP", "nivel_0_LP5"):
        ws.append([nome, f"Descrição sintética de {nome}"])


def _com_data_interna(conteudo: bytes, quando: datetime) -> bytes:
    """Fixa o dcterms:modified/created (o openpyxl grava a hora do relógio) e as datas
    das entradas do zip: o mesmo conteúdo dá os MESMOS bytes (o sha256 é conferido)."""
    carimbo = quando.strftime("%Y-%m-%dT%H:%M:%SZ").encode()
    entrada, saida = zipfile.ZipFile(io.BytesIO(conteudo)), io.BytesIO()
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as novo:
        for item in entrada.infolist():
            dados = entrada.read(item.filename)
            if item.filename == "docProps/core.xml":
                dados = re.sub(rb"(<dcterms:(?:modified|created)[^>]*>)[^<]*"
                               rb"(</dcterms:(?:modified|created)>)",
                               rb"\g<1>" + carimbo + rb"\g<2>", dados)
            item.date_time = (2031, 1, 1, 0, 0, 0)
            novo.writestr(item, dados)
    return saida.getvalue()


MUNICIPIOS = [(MUN, NOME_MUN), (OUTRO_MUN, NOME_MUN)]          # o homônimo, OUTRO código
UFS = [("35", "São Paulo"), ("33", "Outra UF Sintética")]


def planilha(*, ano=2025, dicionario="primeira", segundo_ano=False, tx=False, quinto=True,
             municipios=True, rotulos=False, sem_ano=False, capital_uf=True, fracao=False,
             caixa="real", trocas=None, quando=DATA_PLANILHA) -> bytes:
    """A planilha SINTÉTICA no layout real: abas com nomes que não dizem o nível."""
    wb = Workbook()
    abas = [("Planilha X", "brasil"), ("Planilha Y", "uf")]
    if municipios:
        abas.append(("Planilha Z", "municipio"))
    if dicionario == "primeira":
        abas.insert(0, ("Dicionário", None))
    elif dicionario == "meio":
        abas.insert(2, ("Municípios", None))       # o NOME engana: é um dicionário
    for k, (nome, tipo) in enumerate(abas):
        ws = wb.active if k == 0 else wb.create_sheet()
        ws.title = nome
        if tipo is None:
            _dicionario(ws)
            continue
        territorios = {"brasil": [("BR", "Brasil")], "uf": UFS, "municipio": MUNICIPIOS}[tipo]
        aba_saeb(ws, tipo, territorios, ano=ano, segundo_ano=segundo_ano and tipo != "municipio",
                 tx=tx and tipo != "municipio", quinto=quinto,
                 capital=capital_uf or tipo == "brasil", rotulos=rotulos, fracao=fracao,
                 caixa=caixa, trocas=trocas, sem_ano=sem_ano)
    buf = io.BytesIO()
    wb.save(buf)
    return _com_data_interna(buf.getvalue(), quando)


def _ler(conteudo: bytes, nome="saeb_2025_brasil_estados_municipios.xlsx",
         edicao=None) -> sp.LeituraSaeb:
    wb = load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    try:
        abas, ignoradas = sp.abas_da_planilha(wb, codigo_ibge=MUN)
    finally:
        wb.close()
    return sp.consolidar(abas, nome=nome, edicao_informada=edicao, abas_ignoradas=ignoradas)


def _refs(leitura) -> dict:
    lido, _ = sp.recortar(leitura)
    return {(n.linha.abrangencia, n.linha.rede_ensino, n.linha.localizacao, n.linha.etapa,
             n.linha.indicador, n.linha.componente, n.linha.nivel): n.linha
            for n in lido.referencia}


def _nivel(refs, abrangencia, rede, loc, etapa, comp, k):
    return refs[(abrangencia, rede, loc, etapa, sp.IND_PCT_NIVEL, comp, str(k))]


# =============================================================================
# Parser
# =============================================================================

def test_abas_pelo_conteudo_dicionario_ignorado_onde_estiver():
    for posicao in ("primeira", "meio"):
        leitura = _ler(planilha(dicionario=posicao))
        assert [(a.aba, a.tipo) for a in leitura.abas] == [
            ("Planilha X", "brasil"), ("Planilha Y", "uf"), ("Planilha Z", "municipio")]
        assert leitura.abas_ignoradas == (["Dicionário"] if posicao == "primeira"
                                          else ["Municípios"])
        assert any("ignoradas" in a and leitura.abas_ignoradas[0] in a for a in leitura.avisos)
    assert (leitura.edicao_arquivo, leitura.origem_edicao) == (2025, "coluna")
    assert leitura.escala_niveis == "percentual"


def test_municipio_so_a_rede_municipal_total_separado_de_urbana_e_rural():
    leitura = _ler(planilha())
    mun = next(a for a in leitura.abas if a.tipo == "municipio")
    assert mun.alvo == MUN and mun.linhas_lidas == 2 * 21 and len(mun.recorte) == 21
    refs = _refs(leitura)
    redes_mun = {(r, loc) for (ab, r, loc, *_) in refs if ab == "municipio"}
    assert redes_mun == {("municipal", "total"), ("municipal", "urbana"), ("municipal", "rural")}
    capa = refs[("municipio", "municipal", "total", "5_ano", "proficiencia", "lp", "")]
    urbana = refs[("municipio", "municipal", "urbana", "5_ano", "proficiencia", "lp", "")]
    assert (capa.valor, capa.unidade, capa.desenho) == (101.3, escalas.ESCALA_SAEB, "censitario")
    assert urbana.valor == round(101.3 + 1 * 1.7, 1)
    assert capa.codigo_territorio == MUN and capa.edicao == 2025
    assert _nivel(refs, "municipio", "municipal", "total", "5_ano", "lp", 0).valor == 18.2
    assert _nivel(refs, "municipio", "municipal", "total", "5_ano", "mt", 10).valor == 0.3
    assert _nivel(refs, "municipio", "municipal", "total", "5_ano", "lp", 0).unidade == "percentual"
    # nada do 9º ano nem do 2º ano por município
    assert not any(et == "2_ano" for (ab, _, _, et, *_) in refs if ab == "municipio")
    assert len([k for k in refs if k[0] == "municipio"]) == 3 * (2 + 10 + 11)
    avisos = " ".join(leitura.avisos)
    assert "dependências do município não gravadas" in avisos and "Estadual (3×)" in avisos


def test_uf_e_brasil_nas_quatro_redes_so_a_area_total():
    leitura = _ler(planilha())
    refs = _refs(leitura)
    redes = {(ab, r) for (ab, r, *_) in refs if ab != "municipio"}
    assert redes == {(ab, r) for ab in ("uf", "brasil")
                     for r in ("municipal", "estadual", "publica", "total")}
    uf = next(a for a in leitura.abas if a.tipo == "uf")
    assert uf.alvo == "35" and uf.linhas_lidas == 2 * 42 and len(uf.recorte) == 42
    lido, _ = sp.recortar(leitura)
    assert lido.territorios == {"BR": "Brasil", "35": "São Paulo", MUN: NOME_MUN}
    total = refs[("brasil", "total", "total", "5_ano", "proficiencia", "mt", "")]
    assert total.desenho is None                       # inclui a privada (amostral)
    assert refs[("uf", "publica", "rural", "5_ano", "proficiencia", "mt", "")].desenho == "censitario"


def test_segundo_ano_e_taxa_so_de_uf_e_brasil_amostral_e_nunca_o_ica():
    leitura = _ler(planilha(ano=2021, segundo_ano=True, tx=True),
                   nome="saeb_2021_brasil_estados_municipios.xlsx")
    refs = _refs(leitura)
    media2 = refs[("uf", "municipal", "total", "2_ano", "proficiencia", "lp", "")]
    assert (media2.unidade, media2.desenho) == (escalas.ESCALA_ALFABETIZACAO, "amostral")
    tx = refs[("brasil", "municipal", "total", "2_ano", sp.IND_TX_ALFABETIZADO, "lp", "")]
    assert (tx.unidade, tx.desenho, tx.valor) == ("percentual", "amostral", 11.2)
    assert sp.IND_TX_ALFABETIZADO != "percentual_alfabetizado"
    assert not any(ab == "municipio" and et == "2_ano" for (ab, _, _, et, *_) in refs)
    assert _nivel(refs, "uf", "estadual", "urbana", "2_ano", "mt", 8).desenho == "amostral"
    avisos = " ".join(leitura.avisos)
    assert "AMOSTRAL" in avisos and "NÃO é o Indicador Criança Alfabetizada" in avisos


def test_segundo_ano_numa_aba_de_municipios_nao_e_lido():
    wb = Workbook()
    ws = wb.active
    aba_saeb(ws, "municipio", [(MUN, NOME_MUN)], segundo_ano=True)
    buf = io.BytesIO()
    wb.save(buf)
    leitura = _ler(buf.getvalue())
    assert leitura.abas[0].segundo_ano_ignorado[:2] == ["MEDIA_2_LP", "MEDIA_2_MT"]
    assert not any(et == "2_ano" for (_, _, _, et, *_) in _refs(leitura))
    assert any("2º ano (amostral) não são lidas por município" in a for a in leitura.avisos)


def test_fracao_vira_percentual_e_mistura_ou_soma_errada_recusam():
    leitura = _ler(planilha(fracao=True))
    assert leitura.escala_niveis == "fracao"
    refs = _refs(leitura)
    n0 = _nivel(refs, "municipio", "municipal", "total", "5_ano", "lp", 0)
    assert (n0.valor, n0.casas_decimais) == (18.2, 1)
    assert any("FRAÇÃO" in a for a in leitura.avisos)
    misturada = planilha(trocas={(MUN, "Municipal", "Urbana", ""): {
        f"nivel_{k}_LP5": x / 100 for k, x in enumerate(_DIST_LP5)}})
    with pytest.raises(ImportacaoRecusada, match="mistura"):
        _ler(misturada)
    errada = planilha(trocas={(MUN, "Municipal", "Total", ""): {"nivel_3_LP5": 41.9}})
    with pytest.raises(ImportacaoRecusada, match="nem 100%"):
        _ler(errada)


def test_marcadores_e_vazio_sao_ausencia_nunca_zero():
    trocas = {(MUN, "Municipal", "Total", ""): {"MEDIA_5_MT": "ND", "nivel_9_LP5": "-"},
              ("35", "Municipal", "Total", "Total"): {"MEDIA_5_LP": None}}
    refs = _refs(_ler(planilha(trocas=trocas)))
    mt = refs[("municipio", "municipal", "total", "5_ano", "proficiencia", "mt", "")]
    assert (mt.valor, mt.motivo_ausencia) == (None, "nao_divulgado")
    n9 = _nivel(refs, "municipio", "municipal", "total", "5_ano", "lp", 9)
    assert (n9.valor, n9.motivo_ausencia) == (None, "nao_divulgado")
    lp_uf = refs[("uf", "municipal", "total", "5_ano", "proficiencia", "lp", "")]
    assert (lp_uf.valor, lp_uf.motivo_ausencia) == (None, "nao_divulgado")


def test_taxa_zero_sem_media_do_segundo_ano_e_ausencia():
    trocas = {("35", "Estadual", "Rural", "Total"): {"TX_ALFABETIZADO": 0, "MEDIA_2_LP": None,
                                                     "MEDIA_2_MT": None}}
    leitura = _ler(planilha(ano=2021, segundo_ano=True, tx=True, quinto=False, municipios=False,
                            trocas=trocas), nome="saeb_2021_c_tx_alfabetizado.xlsx")
    tx = _refs(leitura)[("uf", "estadual", "rural", "2_ano", sp.IND_TX_ALFABETIZADO, "lp", "")]
    assert (tx.valor, tx.motivo_ausencia) == (None, "nao_divulgado")
    assert any("“0” sem nenhuma média" in a for a in leitura.avisos)


def test_rotulos_legiveis_caixa_dos_nomes_e_estados_sem_capital():
    leitura = _ler(planilha(rotulos=True, caixa="maiuscula", capital_uf=False))
    assert all(a.rotulos == 1 for a in leitura.abas)
    uf = next(a for a in leitura.abas if a.tipo == "uf")
    assert len(uf.recorte) == 21 and all(ln.capital == "" for ln in uf.linhas)
    refs = _refs(leitura)
    assert _nivel(refs, "uf", "municipal", "total", "5_ano", "mt", 3).valor == 16.2


def test_edicao_pela_coluna_pelo_nome_ou_informada():
    sem_ano = planilha(sem_ano=True)
    leitura = _ler(sem_ano, nome="Resultados_Saeb_2019_Brasil_Estados_Municipios.xlsx")
    assert (leitura.edicao_arquivo, leitura.origem_edicao) == (2019, "nome")
    with pytest.raises(ImportacaoRecusada, match="Informe a edição"):
        _ler(sem_ano, nome="planilha_sintetica.xlsx")
    informada = _ler(sem_ano, nome="planilha_sintetica.xlsx", edicao=2021)
    assert (informada.edicao_arquivo, informada.origem_edicao) == (2021, "informada")
    with pytest.raises(ImportacaoRecusada, match="diverge"):
        _ler(planilha(ano=2025), nome="saeb_2021_brasil_estados_municipios.xlsx")


def test_layout_estranho_recusa():
    wb = Workbook()
    ws = wb.active
    ws.append(["ANO_SAEB", "DEPENDENCIA_ADM", "LOCALIZACAO", "MEDIA_5_LP"])     # sem o território
    buf = io.BytesIO()
    wb.save(buf)
    with pytest.raises(ImportacaoRecusada, match="identificação"):
        _ler(buf.getvalue())
    sem_dados = Workbook()
    _dicionario(sem_dados.active)
    buf = io.BytesIO()
    sem_dados.save(buf)
    with pytest.raises(ImportacaoRecusada, match="Nenhuma aba de dados"):
        _ler(buf.getvalue())
    desconhecida = planilha(trocas={(MUN, "Municipal", "Total", ""): {"MEDIA_5_LP": "abc"}})
    with pytest.raises(ImportacaoRecusada, match="não é número nem marcador"):
        _ler(desconhecida)
    fora = planilha(trocas={(MUN, "Municipal", "Total", ""): {"MEDIA_5_LP": 512.5}})
    with pytest.raises(ImportacaoRecusada, match="fora da faixa"):
        _ler(fora)


def test_regua_dos_niveis_do_saeb():
    assert escalas.NIVEIS_SAEB[("5_ano", "lp")] == tuple(range(10))
    assert escalas.NIVEIS_SAEB[("5_ano", "mt")] == tuple(range(11))
    assert escalas.faixa_nivel_saeb("5_ano", "lp", 0) == (None, 125.0)
    assert escalas.faixa_nivel_saeb("5_ano", "lp", 9) == (325.0, None)
    assert escalas.faixa_nivel_saeb("5_ano", "mt", 10) == (350.0, None)
    assert escalas.faixa_nivel_saeb("2_ano", "lp", 3) == (None, None)


# =============================================================================
# preparar → pacote → servidor
# =============================================================================

def _preparar(tmp_path, conteudo=None, nome="saeb_2025_brasil_estados_municipios.xlsx",
              **kw) -> preparar.PreparoSaeb:
    caminho = tmp_path / nome
    caminho.write_bytes(conteudo or planilha())
    return preparar.preparar_saeb(codigo_ibge=MUN, planilha=caminho, agora=AGORA,
                                  url="https://exemplo.invalido/saeb_sintetico.xlsx",
                                  last_modified="Mon, 03 Mar 2031 10:00:00 GMT",
                                  baixado_em="2031-03-04T10:00:00+00:00", **kw)


def _arquivos(dados: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(dados)) as z:
        return {n: z.read(n) for n in z.namelist()}


def test_preparar_gera_o_pacote_com_um_csv_por_aba_e_a_proveniencia(tmp_path):
    preparo = _preparar(tmp_path)
    m = preparo.manifesto
    assert preparo.nome == f"pacote_saeb_2025_resultados_{MUN}.zip"
    assert (m["parser"], m["parser_versao"], m["edicao"], m["origem_edicao"]) == (
        sp.PARSER, sp.VERSAO_PARSER, 2025, "coluna")
    xlsx = (tmp_path / "saeb_2025_brasil_estados_municipios.xlsx").read_bytes()
    assert m["origem"]["sha256"] == hashlib.sha256(xlsx).hexdigest()
    assert m["origem"]["last_modified"] == "Mon, 03 Mar 2031 10:00:00 GMT"
    assert m["entrada"]["data_interna"] == "2031-06-02T08:15:00"
    assert m["entrada"]["abas_ignoradas"] == ["Dicionário"]
    assert [(a["tipo"], a["territorio"], a["linhas_recorte"]) for a in m["abas"]] == [
        ("brasil", "BR", 42), ("uf", "35", 42), ("municipio", MUN, 21)]
    arquivos = _arquivos(preparo.pacote)
    assert sorted(arquivos) == sorted([pacote.NOME_MANIFESTO, *pacote_saeb.NOME_CSV.values()])
    texto = arquivos["saeb_municipio_recorte.csv"].decode("utf-8")
    assert b"\r" not in arquivos["saeb_municipio_recorte.csv"] and OUTRO_MUN not in texto
    assert "Outra UF" not in arquivos["saeb_uf_recorte.csv"].decode("utf-8")
    assert len(preparo.pacote) < 40_000
    tx = _preparar(tmp_path, planilha(ano=2021, segundo_ano=True, tx=True, quinto=False,
                                      municipios=False),
                   nome="saeb_2021_brasil_estados_municipios_c_tx_alfabetizado.xlsx")
    assert tx.nome == f"pacote_saeb_2021_tx_alfabetizado_{MUN}.zip"


def test_pacote_lido_no_servidor_e_o_mesmo_recorte(tmp_path):
    preparo = _preparar(tmp_path, planilha(sem_ano=True),
                        nome="Resultados_Saeb_2019_Brasil_Estados_Municipios.xlsx")
    lido = pacote_saeb.ler_pacote(preparo.pacote, "p.zip", codigo_ibge=MUN)
    assert lido.leitura.edicao_arquivo == 2019 and lido.leitura.origem_edicao == "nome"
    assert _refs(lido.leitura) == _refs(preparo.leitura)
    assert lido.meta["arquivo_data"] == DATA_PLANILHA
    assert lido.meta["coletado_em"] == datetime(2031, 3, 4, 10, 0)
    assert lido.meta["arquivo_nome"] == "Resultados_Saeb_2019_Brasil_Estados_Municipios.xlsx"


def _mexido(dados: bytes, *, csv_fn=None, manifesto_fn=None, recalcular=False) -> bytes:
    arquivos = _arquivos(dados)
    m = json.loads(arquivos[pacote.NOME_MANIFESTO])
    alvo = "saeb_municipio_recorte.csv"
    if csv_fn:
        arquivos[alvo] = csv_fn(arquivos[alvo])
        if recalcular:
            aba = next(a for a in m["abas"] if a["csv"] == alvo)
            aba["csv_sha256"] = hashlib.sha256(arquivos[alvo]).hexdigest()
    if manifesto_fn:
        manifesto_fn(m)
    arquivos[pacote.NOME_MANIFESTO] = json.dumps(m).encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for nome, conteudo in arquivos.items():
            z.writestr(nome, conteudo)
    return buf.getvalue()


def _linha_do_homonimo(recorte: bytes) -> bytes:
    linhas = list(csv.reader(io.StringIO(recorte.decode("utf-8"), newline=""), delimiter=";"))
    nova = list(linhas[1])
    nova[3] = OUTRO_MUN
    linhas.append(nova)
    buf = io.StringIO()
    csv.writer(buf, delimiter=";", lineterminator="\n").writerows(linhas)
    return buf.getvalue().encode("utf-8")


@pytest.mark.parametrize("mexer, trecho", [
    (dict(csv_fn=lambda b: b.replace(b"101.3", b"109.3")), "sha256 diferente"),
    (dict(csv_fn=_linha_do_homonimo, recalcular=True), "de fora do território"),
    (dict(manifesto_fn=lambda m: m.update(edicao=2023)), "não é a do manifesto"),
    (dict(manifesto_fn=lambda m: m.update(parser_versao="0")), "versão '0' do parser"),
    (dict(manifesto_fn=lambda m: m["abas"].pop()), "não declara"),
    (dict(manifesto_fn=lambda m: m.update(codigo_territorio_alvo=OUTRO_MUN)),
     f"recortado para o município {OUTRO_MUN}"),
])
def test_pacote_adulterado_e_recusado(tmp_path, mexer, trecho):
    preparo = _preparar(tmp_path)
    with pytest.raises(ImportacaoRecusada, match=trecho):
        pacote_saeb.ler_pacote(_mexido(preparo.pacote, **mexer), "p.zip", codigo_ibge=MUN)


def test_linha_de_comando_detecta_a_planilha_pelo_conteudo(tmp_path, capsys):
    caminho = tmp_path / "saeb_2025_brasil_estados_municipios.xlsx"
    caminho.write_bytes(planilha())
    assert preparar.planilha_do_saeb(caminho) and not preparar.zip_do_ideb(caminho)
    for opcao in ("--planilha", "--zip"):
        saida = tmp_path / f"saida{opcao}"
        assert preparar.main(["--ibge", MUN, opcao, str(caminho), "--saida", str(saida)]) == 0
        gerado = saida / f"pacote_saeb_2025_resultados_{MUN}.zip"
        assert pacote_saeb.ler_pacote(gerado.read_bytes(), gerado.name, codigo_ibge=MUN)
    assert "Planilha do Saeb" in capsys.readouterr().out


# =============================================================================
# Pipeline: prévia → aplicação → reaplicação → desfazer
# =============================================================================

@pytest.fixture()
def rede(db):
    r = Rede(nome="Rede Sintética do Saeb", uf="SP", codigo_ibge=MUN, status="ativa")
    db.add(r)
    db.commit()
    return r


def _estado(db) -> list:
    db.expire_all()
    return sorted((r.avaliacao_id, r.edicao, r.indicador, r.abrangencia, r.codigo_territorio,
                   r.rede_ensino, r.localizacao, r.etapa, r.componente, r.nivel, r.valor,
                   r.casas_decimais, r.motivo_ausencia, r.unidade, r.desenho, r.importacao_id,
                   r.created_at, r.updated_at)
                  for r in db.execute(select(IndicadorReferencia)).scalars())


def _aplicar(db, rede, conteudo, nome="pacote.zip"):
    p = pipeline_saeb.previa(db, rede, conteudo, nome, usuario_id=None)
    db.commit()
    a = pipeline_saeb.aplicar(db, rede, p["id"], conteudo, nome, usuario_id=None)
    db.commit()
    return p, a


def test_previa_nao_grava_aplicar_reaplicar_e_desfazer_exato(db, rede, tmp_path):
    dados = _preparar(tmp_path).pacote
    antes = _estado(db)
    p = pipeline_saeb.previa(db, rede, dados, "pacote.zip", usuario_id=None)
    db.commit()
    assert _estado(db) == antes
    imp = db.get(ImportacaoIndicador, p["id"])
    assert (imp.parser, imp.parser_versao, imp.modo, imp.edicao_arquivo) == (
        sp.PARSER, sp.VERSAO_PARSER, "pacote_cli", 2025)
    assert imp.arquivo_data == DATA_PLANILHA and imp.coletado_em == datetime(2031, 3, 4, 10, 0)
    assert imp.arquivo_nome == "saeb_2025_brasil_estados_municipios.xlsx"
    assert imp.last_modified_origem == "Mon, 03 Mar 2031 10:00:00 GMT"
    assert "Saeb" in imp.fonte_nome and "CC BY-ND" in imp.licenca
    novas = p["contadores"]["novas"]
    assert novas == (2 * 4 * 3 + 3) * (2 + 10 + 11)        # UF e Brasil: 4 redes × 3 loc
    assert p["abas_ignoradas"] == ["Dicionário"] and p["escala_niveis"] == "percentual"
    assert any(m["nivel"] == "10" and m["localizacao"] == "rural" for m in p["mudancas"])
    a = pipeline_saeb.aplicar(db, rede, p["id"], dados, "outro.zip", usuario_id=None)
    db.commit()
    assert a["status"] == "aplicada" and db.scalar(select(func.count(ResultadoAvaliacao.id))) == 0
    depois = _estado(db)
    assert len(depois) == novas
    _, b = _aplicar(db, rede, dados)
    assert b["contadores"]["novas"] == 0 and b["contadores"]["iguais"] == novas
    assert _estado(db) == depois
    lista = pipeline_saeb.listar(db, rede)
    assert lista[1]["bloqueada_por"] == lista[0]["id"]
    for item in lista:
        if item["status"] == "aplicada":
            pipeline_saeb.desfazer(db, rede, item["id"], usuario_id=None)
            db.commit()
    assert _estado(db) == antes


def test_mesma_edicao_vale_a_planilha_mais_nova_em_qualquer_ordem(db, rede, tmp_path):
    """A de 2021 com a taxa repete as médias do 2º ano de UF e Brasil da de 2021: na
    MESMA edição vale a data interna mais nova; número igual não mexe em nada."""
    trocas = {("BR", "Municipal", "Total", "Total"): {"MEDIA_2_LP": 633.8}}
    principal = _preparar(tmp_path, planilha(ano=2021, segundo_ano=True), nome="a.xlsx").pacote
    com_tx = _preparar(tmp_path, planilha(ano=2021, segundo_ano=True, tx=True, quinto=False,
                                          municipios=False, trocas=trocas, quando=DATA_NOVA),
                       nome="b.xlsx").pacote

    def media2():
        db.expire_all()
        return db.execute(select(IndicadorReferencia).where(
            IndicadorReferencia.indicador == "proficiencia", IndicadorReferencia.etapa == "2_ano",
            IndicadorReferencia.componente == "lp", IndicadorReferencia.abrangencia == "brasil",
            IndicadorReferencia.rede_ensino == "municipal",
            IndicadorReferencia.localizacao == "total")).scalar_one()

    _, a1 = _aplicar(db, rede, principal)
    _, a2 = _aplicar(db, rede, com_tx)
    assert (media2().valor, media2().importacao_id) == (633.8, a2["id"])
    for imp_id in (a2["id"], a1["id"]):
        pipeline_saeb.desfazer(db, rede, imp_id, usuario_id=None)
        db.commit()
    _aplicar(db, rede, com_tx)
    p, _ = _aplicar(db, rede, principal)
    assert p["contadores"]["mantidas"] >= 1 and media2().valor == 633.8
    assert any(x.startswith("Arquivo de data anterior") for x in p["avisos"])


def test_nada_polui_opcoes_nem_correlacao(db, rede, tmp_path):
    _aplicar(db, rede, _preparar(tmp_path).pacote)
    assert svc.opcoes_rede(db, rede.id) == []
    corr = svc.correlacao_rede(db, rede.id, avaliacao_chave="saeb", indicador="proficiencia",
                               edicao=2025, etapa="5_ano", componente="portugues")
    assert corr["pontos"] == [] and corr["evolucao"] == []


def test_o_que_nao_e_o_pacote_e_recusado_com_a_causa(db, rede, tmp_path):
    with pytest.raises(ImportacaoRecusada, match="planilha do INEP crua"):
        pipeline_saeb.previa(db, rede, planilha(), "saeb.xlsx", usuario_id=None)
    db.rollback()
    with pytest.raises(ImportacaoRecusada, match="Não reconheci"):
        pipeline_saeb.previa(db, rede, b"ANO_SAEB;ID\n", "x.csv", usuario_id=None)
    db.rollback()
    from app.services.indicadores import pipeline_ideb
    pacote_do_saeb = _preparar(tmp_path).pacote
    with pytest.raises(ImportacaoRecusada, match="pacote da planilha do Saeb") as recusa:
        pipeline_ideb.previa(db, rede, pacote_do_saeb, "p.zip", usuario_id=None)
    db.rollback()
    # A recusa vai para a tela como veio: em português, dizendo qual opção escolher,
    # e sem o identificador interno de nenhum parser.
    assert "escolha “Saeb (pacote)”" in str(recusa.value)
    assert "inep_" not in str(recusa.value) and "parser" not in str(recusa.value)
    for parser, trecho in (("inep_ideb_escolas", "Ideb por escola"),
                           ("inep_ideb_municipios", "Ideb do município"),
                           ("inep_ideb_uf_brasil", "Ideb da UF ou do Brasil"),
                           ("inep_aeeb_agregados", "microdados do ICA")):
        outro = _mexido(pacote_do_saeb, manifesto_fn=lambda m, p=parser: m.update(parser=p))
        with pytest.raises(ImportacaoRecusada, match=trecho) as recusa:
            pipeline_saeb.previa(db, rede, outro, "p.zip", usuario_id=None)
        db.rollback()
        assert "aqui entra o pacote da planilha do Saeb" in str(recusa.value)
        assert "inep_" not in str(recusa.value) and "parser" not in str(recusa.value)
    assert db.scalar(select(func.count(ImportacaoIndicador.id))) == 0


def test_textos_de_proveniencia_cabem_nas_colunas():
    assert len(pipeline_saeb.FONTE_NOME) <= 120 and len(pipeline_saeb.CITACAO) <= 500
    assert len(pipeline_saeb.fonte_curta(2025)) <= 120


def test_gitignore_barra_as_planilhas_do_saeb_os_zips_do_ideb_e_os_pacotes():
    """D13: nem a planilha nem o recorte vão para o repositório público."""
    import fnmatch
    from pathlib import Path

    raiz = Path(preparar.__file__).resolve().parents[4]
    gitignore = raiz / ".gitignore"
    if not gitignore.is_file():
        pytest.skip("sem o .gitignore do repositório (código fora do checkout)")
    padroes = [ln.strip() for ln in gitignore.read_text(encoding="utf-8").splitlines()
               if ln.strip() and not ln.lstrip().startswith("#")]
    for nome in (f"pacote_saeb_2025_resultados_{MUN}.zip", f"pacote_ideb_municipio_2025_{MUN}.zip",
                 f"pacote_ideb_uf_2025_{MUN}.zip", f"pacote_ideb_brasil_2025_{MUN}.zip",
                 "saeb_2025_brasil_estados_municipios_censitario.xlsx",
                 "saeb_2021_brasil_estados_municipios_c_tx_alfabetizado.xlsx",
                 "Resultados_Saeb_2019_Brasil_Estados_Municipios.xlsx",
                 "divulgacao_brasil_ideb_2025.zip", "divulgacao_regioes_ufs_ideb_2025.zip"):
        assert any(fnmatch.fnmatchcase(nome, p) for p in padroes), nome


# =============================================================================
# API
# =============================================================================

def _cliente(db, email: str, **campos) -> TestClient:
    db.add(Usuario(nome=email, email=email, senha_hash=hash_senha("s3nh4saeb7"), **campos))
    db.commit()
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", data={"username": email, "password": "s3nh4saeb7"})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def test_api_permissoes_fluxo_e_recusas(db, escola_completa, cliente_global, rede, tmp_path):
    dados = _preparar(tmp_path).pacote
    url = f"/api/v1/redes/{rede.id}/indicadores/saeb"
    secretaria = _cliente(db, "sec@saeb.gov", cargo="coordenador", rede_id=rede.id)
    assert secretaria.post(f"{url}/previa", files={"arquivo": ("p.zip", dados)}).status_code == 403
    assert secretaria.get(f"{url}/importacoes").status_code == 403
    p = cliente_global.post(f"{url}/previa", files={"arquivo": ("p.zip", dados)})
    assert p.status_code == 200, p.text
    ok = cliente_global.post(f"{url}/aplicar", files={"arquivo": ("p.zip", dados)},
                             data={"previa_id": str(p.json()["id"])})
    assert ok.status_code == 200 and ok.json()["status"] == "aplicada"
    assert secretaria.post(f"{url}/importacoes/{ok.json()['id']}/desfazer").status_code == 403
    cru = cliente_global.post(f"{url}/previa", files={"arquivo": ("s.xlsx", planilha())})
    assert cru.status_code == 400 and "preparar" in cru.json()["detail"]
    grande = cliente_global.post(f"{url}/previa",
                                 files={"arquivo": ("g.zip", b"PK" + b"0" * (6 * 1024 * 1024))})
    assert grande.status_code == 413
    desf = cliente_global.post(f"{url}/importacoes/{ok.json()['id']}/desfazer")
    assert desf.status_code == 200 and desf.json()["status"] == "desfeita"
    db.expire_all()
    assert db.scalar(select(func.count(IndicadorReferencia.id))) == 0


# --- O mesmo fluxo num PostgreSQL de verdade ------------------------------------

from tests.test_migracoes_postgres import engine_postgres  # noqa: E402,F401 — fixture do PG de teste


@pytest.mark.postgres
def test_pipeline_saeb_no_postgres_aplica_reaplica_e_desfaz_exato(engine_postgres, tmp_path):
    from sqlalchemy.orm import sessionmaker

    from app.core.migracoes import aplicar_migracoes

    aplicar_migracoes(engine_postgres)
    db = sessionmaker(bind=engine_postgres)()
    try:
        r = Rede(nome="Rede Sintética PG", uf="SP", codigo_ibge=MUN, status="ativa")
        db.add(r)
        db.commit()
        antes = _estado(db)
        dados = _preparar(tmp_path, planilha(trocas={(MUN, "Municipal", "Total", ""): {
            "MEDIA_5_MT": "ND"}})).pacote
        _aplicar(db, r, dados)
        depois = _estado(db)
        assert db.scalar(select(func.count(IndicadorReferencia.id)).where(
            IndicadorReferencia.valor.is_(None))) == 1
        _, b = _aplicar(db, r, dados)
        assert b["contadores"]["novas"] == 0 and _estado(db) == depois
        for item in pipeline_saeb.listar(db, r):
            if item["status"] == "aplicada":
                pipeline_saeb.desfazer(db, r, item["id"], usuario_id=None)
                db.commit()
        assert _estado(db) == antes
    finally:
        db.close()
