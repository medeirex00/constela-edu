"""Ideb do MUNICÍPIO, da UF e do BRASIL (etapa E6b): os parsers ``inep_ideb_municipios``
e ``inep_ideb_uf_brasil``, a linha de comando ``preparar`` → PACOTE recortado →
prévia/aplicação/desfazer da família do Ideb, a precedência entre divulgações e a
regressão das consultas (opções e correlação).

FIXTURES SINTÉTICAS no layout REAL dos arquivos do INEP: pré-âmbulo e cabeçalho em
várias linhas com o dígito de rodapé grudado no ano, a linha técnica, três abas
(anos iniciais no MEIO, escolhida pelo topo), colunas de identificação SEM nome técnico
no arquivo de UF (só o rótulo legível), a UF pelo nome (com abreviação do INEP), a rede
com nota de rodapé ("Total (4)"), nome técnico REPETIDO no lugar do P da última edição,
"-", "ND", número com "**", edição ausente, rodapé com as notas. NADA aqui é dado do
INEP: o município, os nomes, as datas e TODOS os números são INVENTADOS (D13) — e
ficam longe da faixa dos oficiais.
"""
import csv
import hashlib
import io
import json
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
from app.services.indicadores import ideb_territorio as it
from app.services.indicadores import pacote, pacote_ideb, pipeline_ideb, pipeline_saeb, preparar
from tests.test_indicadores_saeb_planilha import planilha as planilha_saeb  # xlsx SINTÉTICO

MUN ="3599999"                # IBGE SINTÉTICO (não existe)
OUTRO_MUN = "3599998"
NOME_MUN = "Cidade Sintética"
AI = "Ensino Fundamental Regular - Anos Iniciais"
AGORA = datetime(2031, 5, 14, 9, 30)          # data INVENTADA
DATA_ZIP = (2031, 6, 2, 8, 15, 0)             # data INVENTADA
DATA_RETIFICADA = (2031, 9, 1, 10, 0, 0)      # data INVENTADA

_APROV = ("SI_4", "SI", "1", "2", "3", "4")
_SERIE = {"SI_4": "1º ao 5º ano", "SI": "1º", "1": "2º", "2": "3º", "3": "4º", "4": "5º"}
EDICOES = (2019, 2021, 2023, 2025)
METAS = (2019, 2021)


def _rot(ano: int) -> str:
    """O ano como nos rótulos do INEP: 2021 leva o dígito da nota de rodapé ("20212")."""
    return f"{ano}2" if ano == 2021 else str(ano)


def _colunas(edicoes, metas, *, p_repetido=False) -> list[tuple]:
    """(nome técnico, grupo, componente, série) na ORDEM do arquivo real. Com
    ``p_repetido``, o P da última edição sai com o nome do P da penúltima (como no
    arquivo de UF): o cabeçalho legível diz qual vale."""
    cols = []
    for ano in edicoes:
        grupo = f"Taxa de Aprovação - {_rot(ano)}"
        for suf in _APROV:
            cols.append((f"VL_APROVACAO_{ano}_{suf}", grupo, None, _SERIE[suf]))
        nome_p = (f"VL_INDICADOR_REND_{edicoes[-2]}" if p_repetido and ano == edicoes[-1]
                  else f"VL_INDICADOR_REND_{ano}")
        cols.append((nome_p, grupo, None, "Indicador de Rendimento (P)"))
    for ano in edicoes:
        grupo = f"Nota SAEB - {_rot(ano)}"
        cols += [(f"VL_NOTA_MATEMATICA_{ano}", grupo, "Matemática", None),
                 (f"VL_NOTA_PORTUGUES_{ano}", grupo, "Língua Portuguesa", None),
                 (f"VL_NOTA_MEDIA_{ano}", grupo, "Nota Média Padronizada (N)", None)]
    for ano in edicoes:
        cols.append((f"VL_OBSERVADO_{ano}", f"IDEB\n{_rot(ano)}\n(N x P)", None, None))
    for ano in metas:
        cols.append((f"VL_PROJECAO_{ano}", "Metas do 1º ciclo do Ideb3,4 (2007-2021)", None, ano))
    return cols


def valores(base: int, edicoes=EDICOES, metas=METAS, **trocas) -> dict:
    """Os números de uma linha (INVENTADOS e longe da faixa dos oficiais): Ideb 1,x; nota
    do Saeb 1xx,x; N 2,xxxxxx; P 0,4xxxxx; aprovação 3x–4x; metas 1,x."""
    v = {}
    for i, ano in enumerate(edicoes):
        for k, suf in enumerate(_APROV):
            v[f"VL_APROVACAO_{ano}_{suf}"] = round(31.2 + base * 2.1 + i * 1.3 + k * 0.4, 1)
        v[f"VL_INDICADOR_REND_{ano}"] = round(0.431257 + base * 0.0123 + i * 0.0071, 6)
        v[f"VL_NOTA_MATEMATICA_{ano}"] = round(112.4 + base * 3.1 + i * 1.7, 1)
        v[f"VL_NOTA_PORTUGUES_{ano}"] = round(104.7 + base * 2.9 + i * 1.3, 1)
        v[f"VL_NOTA_MEDIA_{ano}"] = round(2.013579 + base * 0.0417 + i * 0.0213, 6)
        v[f"VL_OBSERVADO_{ano}"] = round(1.1 + base * 0.1 + i * 0.1, 1)
    for j, ano in enumerate(metas):
        v[f"VL_PROJECAO_{ano}"] = round(1.0 + base * 0.1 + j * 0.2, 1)
    v.update(trocas)
    return v


_IDS = {"municipio": (("SG_UF", "Sigla da UF"), ("CO_MUNICIPIO", "Código do Município"),
                      ("NO_MUNICIPIO", "Nome do Município"), ("REDE", "Rede")),
        # no arquivo de UF as duas colunas NÃO têm nome técnico — só o rótulo legível
        "uf": (("", "Região/\nUnidade da Federação"), ("", "Rede")),
        "brasil": (("BRASIL", "Brasil"), ("rede", "Rede"))}


def _aba(ws, linhas, *, layout, titulo, edicoes, metas, p_repetido, tecnica, rodape):
    cols = _colunas(edicoes, metas, p_repetido=p_repetido)
    grupos = [g for _, g, _, _ in cols]
    grupos = [g if k == 0 or g != grupos[k - 1] else None for k, g in enumerate(grupos)]
    ids = _IDS[layout]
    ws.append([None, "Ministério sintético"])
    ws.append([None])
    ws.append([titulo])
    ws.append([f"Indicadores sintéticos de {', '.join(_rot(a) for a in edicoes)} e Metas do 1º "
               "ciclo do Ideb3,4 (2007-2021), organizados por rede."])
    ws.append([None])
    ws.append([r for _, r in ids] + grupos)
    ws.append([None] * len(ids) + [c for _, _, c, _ in cols])
    ws.append([None] * len(ids) + [s for _, _, _, s in cols])
    ws.append([(tecnica or {}).get(n, n) or None for n in [n for n, _ in ids] + [c[0] for c in cols]])
    for ln in linhas:
        if layout == "municipio":
            ident = [ln.get("uf", "SP"), int(ln["mun"]), ln.get("nome", NOME_MUN), ln["rede"]]
        else:
            ident = [ln["territorio"], ln["rede"]]
        ws.append(ident + [ln["valores"].get(n, "-") for n, _, _, _ in cols])
    if rodape:
        ws.append([None])
        ws.append(["Fonte: arquivo sintético de teste."])
        ws.append(["Notas: ND - marcador sintético de não divulgação;"])
        ws.append(["(3) Nota sintética três;"])
        ws.append(["(4) Nota sintética quatro: médias calculadas sem um tipo de escola;"])


def planilha(linhas, *, layout="municipio", edicoes=EDICOES, metas=METAS, p_repetido=False,
             tecnica=None, titulo=AI, outras_abas=None, rodape=True) -> bytes:
    """O xlsx SINTÉTICO no layout real. UF/Brasil: três abas, a dos anos iniciais no MEIO
    e com nome que não diz a etapa (a escolha é pelo topo)."""
    wb = Workbook()
    outras = (layout != "municipio") if outras_abas is None else outras_abas
    abas = ([("Aba A", "Ensino Fundamental Regular - Anos Finais"), ("Aba B", titulo),
             ("Aba C", "Ensino Médio Regular")] if outras else [("IDEB_AI_SINTETICO", titulo)])
    for k, (nome, tit) in enumerate(abas):
        ws = wb.active if k == 0 else wb.create_sheet()
        ws.title = nome
        _aba(ws, linhas, layout=layout, titulo=tit, edicoes=edicoes, metas=metas,
             p_repetido=p_repetido, tecnica=tecnica, rodape=rodape)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# As linhas dos arquivos SINTÉTICOS (todos os números INVENTADOS).
MUNICIPAL = {"mun": MUN, "rede": "Municipal",
             "valores": valores(1, VL_NOTA_MATEMATICA_2019="117,6**", VL_OBSERVADO_2023="ND",
                                VL_APROVACAO_2019_SI="-")}
PUBLICA = {"mun": MUN, "rede": "Pública", "valores": valores(2)}
# O homônimo (mesmo nome, OUTRO código) nunca entra.
HOMONIMO = {"mun": OUTRO_MUN, "rede": "Municipal", "valores": valores(3)}
UF_LINHAS = [
    {"territorio": "Sudeste", "rede": "Total", "valores": valores(4)},
    {"territorio": "São Paulo", "rede": "Total (4)", "valores": valores(2)},
    {"territorio": "São Paulo", "rede": "Pública (4)", "valores": valores(1)},
    {"territorio": "São Paulo", "rede": "Privada", "valores": valores(4)},
    {"territorio": "São Paulo", "rede": "Estadual", "valores": valores(3,
                                                                       VL_APROVACAO_2019_SI="-")},
    {"territorio": "R. G. do Sul", "rede": "Total (3)(4)", "valores": valores(0)},
    {"territorio": "Estado Fictício", "rede": "Total", "valores": valores(0)},
]
BRASIL_LINHAS = [{"territorio": "Brasil", "rede": r, "valores": valores(k)}
                 for k, r in enumerate(("Total", "Estadual", "Municipal", "Pública", "Privada (3)"))]


def _linhas(conteudo: bytes) -> list:
    wb = load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    try:
        return list(it.linhas_da_planilha(wb)[1])
    finally:
        wb.close()


def _ler(conteudo: bytes, **kw) -> it.LeituraTerritorio:
    return it.ler_grade(_linhas(conteudo), codigo_ibge=MUN, **kw)


def _refs(leitura) -> dict:
    lido, _ = it.recortar(leitura)
    return {(n.linha.rede_ensino, n.linha.indicador, n.linha.edicao, n.linha.etapa,
             n.linha.componente): n.linha for n in lido.referencia}


# =============================================================================
# Parser
# =============================================================================

def test_municipio_recorta_pelo_codigo_grava_a_municipal_e_registra_as_outras():
    leitura = _ler(planilha([HOMONIMO, MUNICIPAL, PUBLICA]),
                   nome="divulgacao_anos_iniciais_municipios_2025.xlsx")
    assert (leitura.parser, leitura.abrangencia, leitura.alvo) == (it.PARSER_MUNICIPIOS,
                                                                    "municipio", MUN)
    assert leitura.edicoes == list(EDICOES) and leitura.anos_meta == list(METAS)
    assert leitura.linhas_lidas == 3 and [ln.rede for ln in leitura.linhas] == ["municipal",
                                                                               "publica"]
    assert leitura.nome_territorio == NOME_MUN
    lido, extra = it.recortar(leitura)
    # só a MUNICIPAL vira número: 4 edições × (Ideb + 2 notas do Saeb + N + P + 6
    # aprovações) + 2 metas
    assert len(lido.referencia) == 4 * 11 + 2
    assert {n.linha.rede_ensino for n in lido.referencia} == {"municipal"}
    assert {n.linha.abrangencia for n in lido.referencia} == {"municipio"}
    assert {n.linha.codigo_territorio for n in lido.referencia} == {MUN}
    assert {n.avaliacao for n in lido.referencia} == {"ideb"}
    assert [r["rotulo"] for r in extra["redes_no_arquivo"] if not r["gravada"]] == ["Pública"]
    assert any("registradas e NÃO gravadas" in a and "Pública" in a for a in leitura.avisos)
    refs = _refs(leitura)
    mt = refs[("municipal", "nota_saeb", 2019, "5_ano", "mt")]
    assert (mt.valor, mt.unidade, mt.desenho) == (117.6, "escala_saeb", "censitario")
    assert leitura.asteriscos == ["Municipal VL_NOTA_MATEMATICA_2019"]
    ideb_23 = refs[("municipal", "ideb", 2023, "anos_iniciais", "")]
    assert (ideb_23.valor, ideb_23.motivo_ausencia) == (None, "nao_divulgado")
    assert refs[("municipal", "aprovacao", 2019, "1_ano", "")].valor is None
    assert refs[("municipal", "aprovacao", 2021, "3_ano", "")].valor == 35.8
    assert refs[("municipal", "rendimento_p", 2025, "anos_iniciais", "")].unidade == "proporcao"
    m21 = refs[("municipal", "meta", 2021, "anos_iniciais", "")]
    assert (m21.valor, m21.desenho, m21.casas_decimais) == (1.3, None, 1)
    # a precisão é a da FAMÍLIA no recorte: o Ideb inteiro de uma edição continua com 1 casa
    assert refs[("municipal", "ideb", 2019, "anos_iniciais", "")].casas_decimais == 1
    assert refs[("municipal", "nota_n", 2019, "anos_iniciais", "")].casas_decimais == 6
    assert dict(leitura.marcadores) == {"-": 1, "ND": 1}


def test_outra_rede_nunca_vira_a_municipal_nem_o_homonimo_entra():
    leitura = _ler(planilha([PUBLICA, HOMONIMO, {**PUBLICA, "rede": "Estadual"}]))
    lido, _ = it.recortar(leitura)
    assert lido.referencia == []                       # nem a Pública nem a Estadual
    assert any("não tem linha da rede MUNICIPAL" in a for a in leitura.avisos)
    sem_nada = _ler(planilha([HOMONIMO]))
    assert sem_nada.linhas == [] and any("Nenhuma linha do município" in a
                                         for a in sem_nada.avisos)


def test_edicao_ausente_nao_vira_ausencia_e_bloco_incompleto_recusa():
    leitura = _ler(planilha([{**MUNICIPAL, "valores": valores(1, edicoes=(2019, 2025))}],
                            edicoes=(2019, 2025)))
    assert leitura.edicoes == [2019, 2025]
    assert {e for (_, _, e, _, _) in _refs(leitura)} == {2019, 2025, 2021}    # 2021 = meta
    assert not any(e == 2021 and ind != "meta" for (_, ind, e, _, _) in _refs(leitura))
    sem_lp = planilha([MUNICIPAL], tecnica={"VL_NOTA_PORTUGUES_2023": "VL_OUTRA_COISA_2023"})
    with pytest.raises(ImportacaoRecusada, match="edição 2023 está incompleta") as erro:
        _ler(sem_lp)
    assert "Ideb por município" in str(erro.value) and "por escola" not in str(erro.value)


def test_uf_aba_pelo_topo_uf_pelo_nome_rede_com_nota_e_nome_tecnico_repetido():
    leitura = _ler(planilha(UF_LINHAS, layout="uf", p_repetido=True))
    assert (leitura.parser, leitura.abrangencia, leitura.alvo) == (it.PARSER_UF_BRASIL, "uf", "35")
    assert leitura.nome_territorio == "São Paulo"
    # regiões não casam; o nome fora da tabela fica listado; a abreviação do INEP casa
    assert leitura.linhas_lidas == 7 and leitura.nao_reconhecidos == ["Estado Fictício"]
    assert it.uf_do_nome("R. G. do Sul") == "43" and it.uf_do_nome("SAO PAULO") == "35"
    assert it.uf_do_nome("Sao Paulo do Norte") is None                 # nunca aproximado
    assert [(ln.rede, ln.notas) for ln in leitura.linhas] == [
        ("total", ("4",)), ("publica", ("4",)), ("privada", ()), ("estadual", ())]
    # o P da última edição veio com o nome do da penúltima: vale a ocorrência que confere
    assert leitura.colunas_repetidas and "VL_INDICADOR_REND_2023" in leitura.colunas_repetidas[0]
    assert "Taxa de Aprovação - 2025" in leitura.colunas_repetidas[0]
    refs = _refs(leitura)
    assert ("total", "rendimento_p", 2023, "anos_iniciais", "") in refs
    assert ("total", "rendimento_p", 2025, "anos_iniciais", "") not in refs     # não adivinha
    assert refs[("total", "rendimento_p", 2023, "anos_iniciais", "")].valor == round(
        0.431257 + 2 * 0.0123 + 2 * 0.0071, 6)
    assert {r for (r, *_) in refs} == {"total", "publica", "estadual"}         # sem a privada
    assert refs[("total", "ideb", 2025, "anos_iniciais", "")].desenho is None
    assert refs[("estadual", "ideb", 2025, "anos_iniciais", "")].desenho == "censitario"
    avisos = " ".join(leitura.avisos)
    assert "nota (4) do INEP: Nota sintética quatro" in avisos
    assert "não traz a rede MUNICIPAL da UF 35" in avisos and "Privada" in avisos
    assert "Estado Fictício" in avisos and "NÃO foi lida" in avisos


def test_nome_repetido_sem_cabecalho_que_decida_recusa():
    # duas ocorrências sob o MESMO grupo (as duas conferem): não dá para saber qual vale
    dupla = planilha(UF_LINHAS, layout="uf",
                     tecnica={"VL_NOTA_MATEMATICA_2023": "VL_NOTA_PORTUGUES_2023"})
    with pytest.raises(ImportacaoRecusada, match="não diz qual delas vale"):
        _ler(dupla)
    # nomes TROCADOS entre duas edições: o cabeçalho não confere com a técnica
    errada = planilha(UF_LINHAS, layout="uf", tecnica={"VL_NOTA_MEDIA_2023": "VL_NOTA_MEDIA_2021",
                                                       "VL_NOTA_MEDIA_2021": "VL_NOTA_MEDIA_2023"})
    with pytest.raises(ImportacaoRecusada, match="não confere com a linha técnica"):
        _ler(errada)


def test_brasil_por_rede_com_os_nomes_tecnicos_em_caixa_mista():
    leitura = _ler(planilha(BRASIL_LINHAS, layout="brasil"))
    assert (leitura.abrangencia, leitura.alvo, leitura.linhas_lidas) == ("brasil", "BR", 5)
    lido, extra = it.recortar(leitura)
    assert {n.linha.rede_ensino for n in lido.referencia} == {"total", "estadual", "municipal",
                                                              "publica"}
    assert {n.linha.codigo_territorio for n in lido.referencia} == {"BR"}
    assert lido.territorios == {"BR": "Brasil"}
    assert [r["rede"] for r in extra["redes_no_arquivo"] if not r["gravada"]] == ["privada"]


def _aviso_universo(leitura) -> str:
    return next(a for a in leitura.avisos if a.startswith("Universo do INEP"))


def test_universo_da_nota_do_saeb_vai_no_rotulo_nos_avisos_e_no_resumo():
    """O arquivo do Ideb não diz de que escolas é a nota do Saeb (que faz o N e o Ideb):
    só as urbanas no município, na UF e no Brasil municipal/estadual; todas (a base da
    "Total" da planilha) só no Brasil público e total. Vai no rótulo — a chave continua a
    do Ideb oficial do território (localização "total")."""
    urb, todas = it.UNIVERSO_URBANAS, it.UNIVERSO_TODAS
    assert it.universo_saeb("municipio", "municipal") == urb
    assert {it.universo_saeb("uf", r) for r in it.REDES_GRAVADAS} == {urb}
    assert [it.universo_saeb("brasil", r) for r in ("municipal", "estadual", "publica",
                                                    "total")] == [urb, urb, todas, todas]
    assert "Só escolas urbanas" in it.rotulo_universo("municipio", "municipal")
    assert "não é a média “Total”" in it.rotulo_universo("uf", "total")
    assert "urbanas e rurais" in it.rotulo_universo("brasil", "publica")
    assert it.INDICADORES_DO_UNIVERSO == ("ideb", "nota_saeb", "nota_n")

    mun = _ler(planilha([MUNICIPAL, PUBLICA]))
    _, extra = it.recortar(mun)
    assert extra["universo_saeb"] == {
        "indicadores": ["ideb", "nota_saeb", "nota_n"],
        "por_rede": {"municipal": {"universo": urb, "rotulo": it.ROTULO_UNIVERSO[urb]}}}
    assert [(r["rede"], r["universo_saeb"]) for r in extra["redes_no_arquivo"]] == [
        ("municipal", urb), ("publica", None)]                  # a Pública não é gravada
    aviso = _aviso_universo(mun)
    assert f"do município {MUN}" in aviso and "das escolas URBANAS —" in aviso
    assert "TODAS" not in aviso and "NÃO é a média “Total”" in aviso
    assert "nunca é emendada nem cruzada" in aviso

    uf = _ler(planilha(UF_LINHAS, layout="uf"))
    assert "das escolas URBANAS nas redes total, pública e estadual —" in _aviso_universo(uf)

    br = _ler(planilha(BRASIL_LINHAS, layout="brasil"))
    lido, extra_br = it.recortar(br)
    assert {r: u["universo"] for r, u in extra_br["universo_saeb"]["por_rede"].items()} == {
        "total": todas, "estadual": urb, "municipal": urb, "publica": todas}
    aviso_br = _aviso_universo(br)
    assert "de TODAS as escolas" in aviso_br and "nas redes total e pública" in aviso_br
    assert "das escolas URBANAS nas redes estadual e municipal" in aviso_br
    assert {n.linha.localizacao for n in lido.referencia} == {"total"}

    # sem rede gravada (só a Pública do município), nada a rotular
    assert not any(a.startswith("Universo do INEP") for a in _ler(planilha([PUBLICA])).avisos)


def test_etapa_errada_layout_por_escola_e_valor_estranho_recusam():
    with pytest.raises(ImportacaoRecusada, match="Nenhuma aba dos ANOS INICIAIS"):
        _ler(planilha([MUNICIPAL], titulo="Ensino Fundamental Regular - Anos Finais"))
    with pytest.raises(ImportacaoRecusada, match="POR ESCOLA"):
        it.ler_grade(_linhas(planilha([MUNICIPAL], tecnica={"NO_MUNICIPIO": "ID_ESCOLA"})),
                     codigo_ibge=MUN)
    fora = {**MUNICIPAL, "valores": valores(1, VL_OBSERVADO_2019=11.5)}
    with pytest.raises(ImportacaoRecusada, match="fora da faixa"):
        _ler(planilha([fora]))
    texto = {**MUNICIPAL, "valores": valores(1, VL_OBSERVADO_2019="sem número")}
    with pytest.raises(ImportacaoRecusada, match="não é número nem marcador"):
        _ler(planilha([texto]))
    with pytest.raises(ImportacaoRecusada, match="mais de uma linha"):
        _ler(planilha([MUNICIPAL, MUNICIPAL]))


def test_texto_limpo_tira_o_ruido_do_float_sem_perder_casas():
    assert it.texto_limpo(0.1 + 0.2) == "0.3"
    assert it.texto_limpo(123.45) == "123.45" and it.texto_limpo(7.0) == "7"
    assert it.texto_limpo(0.123456789) == "0.123456789"
    assert it.texto_limpo("  12,5  ") == "12,5" and it.texto_limpo(None) == ""


# =============================================================================
# preparar → pacote → servidor
# =============================================================================

def zip_ideb(xlsx: bytes, *, nome="divulgacao_anos_iniciais_municipios_2025",
             data=DATA_ZIP, md5=True) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        def gravar(caminho, dados):
            info = zipfile.ZipInfo(caminho, date_time=data)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, dados)
        gravar(f"{nome}/", b"")
        gravar(f"{nome}/{nome}.ods", b"ods sintetico (nao lido)")
        gravar(f"{nome}/{nome}.xlsx", xlsx)
        if md5:
            gravar(f"{nome}/md5_{nome}.txt",
                   f"{hashlib.md5(xlsx).hexdigest()} *{nome}.xlsx\r\n".encode())
    return buf.getvalue()


def _preparar(tmp_path, xlsx, nome="mun.zip", **kw) -> preparar.PreparoIdeb:
    caminho = tmp_path / nome
    caminho.write_bytes(zip_ideb(xlsx, **kw))
    return preparar.preparar_ideb(codigo_ibge=MUN, zip_local=caminho, agora=AGORA,
                                  url="https://exemplo.invalido/ideb_municipios.zip",
                                  last_modified="Mon, 03 Mar 2031 10:00:00 GMT",
                                  baixado_em="2031-03-04T10:00:00+00:00")


def _arquivos(dados: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(dados)) as z:
        return {n: z.read(n) for n in z.namelist()}


@pytest.fixture()
def pacote_mun(tmp_path) -> bytes:
    return _preparar(tmp_path, planilha([HOMONIMO, MUNICIPAL, PUBLICA])).pacote


@pytest.fixture()
def pacote_uf(tmp_path) -> bytes:
    return _preparar(tmp_path, planilha(UF_LINHAS, layout="uf", p_repetido=True),
                     nome="divulgacao_regioes_ufs_ideb_2025.zip",
                     ).pacote


@pytest.fixture()
def pacote_br(tmp_path) -> bytes:
    return _preparar(tmp_path, planilha(BRASIL_LINHAS, layout="brasil"),
                     nome="divulgacao_brasil_ideb_2025.zip").pacote


def test_preparar_gera_o_pacote_do_territorio_com_a_proveniencia(tmp_path):
    preparo = _preparar(tmp_path, planilha([HOMONIMO, MUNICIPAL, PUBLICA]))
    m = preparo.manifesto
    assert preparo.nome == f"pacote_ideb_municipio_2025_{MUN}.zip"
    assert (m["parser"], m["parser_versao"], m["abrangencia"], m["territorio"]) == (
        it.PARSER_MUNICIPIOS, it.VERSAO_PARSER, "municipio", MUN)
    assert m["edicoes"] == list(EDICOES) and m["anos_meta"] == list(METAS)
    assert m["origem"]["last_modified"] == "Mon, 03 Mar 2031 10:00:00 GMT"
    assert m["origem"]["baixado_em"] == "2031-03-04T10:00:00+00:00"
    assert m["origem"]["zip_sha256"] == hashlib.sha256((tmp_path / "mun.zip").read_bytes()).hexdigest()
    e = m["entrada"]
    assert e["md5_publicado"] == "confere" and e["data_interna"] == "2031-06-02T08:15:00"
    assert (e["linhas_original"], e["linhas_recorte"]) == (3, 2)
    assert e["redes_no_recorte"] == ["Municipal", "Pública"]
    arquivos = _arquivos(preparo.pacote)
    assert sorted(arquivos) == ["ideb_municipio_recorte.csv", pacote.NOME_MANIFESTO]
    recorte = arquivos["ideb_municipio_recorte.csv"]
    assert b"\r" not in recorte and hashlib.sha256(recorte).hexdigest() == e["csv_sha256"]
    texto = recorte.decode("utf-8")
    assert MUN in texto and OUTRO_MUN not in texto and "117,6**" in texto
    assert "Nota sintética quatro" in texto and "VL_OBSERVADO_2025" in texto
    assert len(preparo.pacote) < 20_000
    uf = _preparar(tmp_path, planilha(UF_LINHAS, layout="uf"), nome="uf.zip")
    assert uf.nome == f"pacote_ideb_uf_2025_{MUN}.zip"
    texto_uf = _arquivos(uf.pacote)["ideb_uf_brasil_recorte.csv"].decode("utf-8")
    assert "São Paulo" in texto_uf and "Sudeste" not in texto_uf and "Fictício" not in texto_uf
    assert any("Estado Fictício" in a for a in uf.manifesto["avisos_preparo"])


def test_pacote_lido_no_servidor_e_o_mesmo_recorte(tmp_path):
    preparo = _preparar(tmp_path, planilha(UF_LINHAS, layout="uf", p_repetido=True))
    lido = pacote_ideb.ler_pacote_territorio(preparo.pacote, "p.zip", codigo_ibge=MUN)
    assert [(ln.rede, ln.celulas) for ln in lido.leitura.linhas] == [
        (ln.rede, ln.celulas) for ln in preparo.leitura.linhas]
    assert lido.leitura.casas == preparo.leitura.casas
    assert lido.meta["arquivo_data"] == datetime(2031, 6, 2, 8, 15)
    assert lido.meta["coletado_em"] == datetime(2031, 3, 4, 10, 0)
    assert lido.meta["last_modified_origem"] == "Mon, 03 Mar 2031 10:00:00 GMT"
    assert any("Estado Fictício" in a for a in lido.avisos_preparo)   # só o preparo viu


def _mexido(dados: bytes, *, csv_fn=None, manifesto_fn=None, recalcular=False) -> bytes:
    arquivos = _arquivos(dados)
    m = json.loads(arquivos[pacote.NOME_MANIFESTO])
    nome_csv = m["entrada"]["csv"]
    if csv_fn:
        arquivos[nome_csv] = csv_fn(arquivos[nome_csv])
        if recalcular:
            m["entrada"]["csv_sha256"] = hashlib.sha256(arquivos[nome_csv]).hexdigest()
    if manifesto_fn:
        manifesto_fn(m)
    arquivos[pacote.NOME_MANIFESTO] = json.dumps(m).encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for nome, conteudo in arquivos.items():
            z.writestr(nome, conteudo)
    return buf.getvalue()


def _linha_de_outro_municipio(recorte: bytes) -> bytes:
    linhas = list(csv.reader(io.StringIO(recorte.decode("utf-8"), newline=""), delimiter=";"))
    i = next(k for k, ln in enumerate(linhas) if len(ln) > 3 and ln[1] == MUN)
    nova = list(linhas[i])
    nova[1] = OUTRO_MUN
    linhas.insert(i + 1, nova)
    buf = io.StringIO()
    csv.writer(buf, delimiter=";", lineterminator="\n").writerows(linhas)
    return buf.getvalue().encode("utf-8")


@pytest.mark.parametrize("mexer, trecho", [
    (dict(csv_fn=lambda b: b.replace(b"117,6**", b"119,6**")), "sha256 diferente"),
    (dict(csv_fn=_linha_de_outro_municipio, recalcular=True), "de fora do território"),
    (dict(manifesto_fn=lambda m: m.update(abrangencia="uf")), "não são as do manifesto"),
    (dict(manifesto_fn=lambda m: m.update(parser_versao="0")), "versão '0' do parser"),
    (dict(manifesto_fn=lambda m: m.update(parser="inep_ideb_escolas")),
     "aqui entra o inep_ideb_municipios"),
    (dict(manifesto_fn=lambda m: m.update(codigo_territorio_alvo=OUTRO_MUN)),
     f"recortado para o município {OUTRO_MUN}"),
])
def test_pacote_adulterado_e_recusado(pacote_mun, mexer, trecho):
    with pytest.raises(ImportacaoRecusada, match=trecho):
        pacote_ideb.ler_pacote_territorio(_mexido(pacote_mun, **mexer), "p.zip",
                                          codigo_ibge=MUN)


def test_linha_de_comando_le_a_origem_do_manifesto_do_download(tmp_path, capsys):
    pasta = tmp_path / "download"
    pasta.mkdir()
    caminho = pasta / "divulgacao_anos_iniciais_municipios_2025.zip"
    caminho.write_bytes(zip_ideb(planilha([MUNICIPAL])))
    registro = {"url": "https://exemplo.invalido/municipios.zip", "arquivo": caminho.name,
                "ok": True, "baixado_em": "2031-03-04T10:00:00+00:00",
                "last_modified": "Mon, 03 Mar 2031 10:00:00 GMT",
                "sha256": hashlib.sha256(caminho.read_bytes()).hexdigest()}
    (pasta / "MANIFESTO.json").write_text(json.dumps([registro]), encoding="utf-8")
    saida = tmp_path / "saida"
    assert preparar.main(["--ibge", MUN, "--zip", str(caminho), "--saida", str(saida)]) == 0
    m = json.loads(_arquivos((saida / f"pacote_ideb_municipio_2025_{MUN}.zip").read_bytes())[
        pacote.NOME_MANIFESTO])
    assert m["origem"]["url"] == registro["url"]
    assert m["origem"]["last_modified"] == registro["last_modified"]
    assert m["origem"]["baixado_em"] == registro["baixado_em"]
    assert "MANIFESTO" in capsys.readouterr().err
    # o sha256 do MANIFESTO tem de ser o do arquivo; o --url informado não pode divergir
    (pasta / "MANIFESTO.json").write_text(json.dumps([{**registro, "sha256": "0" * 64}]),
                                          encoding="utf-8")
    assert preparar.main(["--ibge", MUN, "--zip", str(caminho), "--saida", str(saida)]) == 2
    assert "não é o registrado no MANIFESTO" in capsys.readouterr().err
    (pasta / "MANIFESTO.json").write_text(json.dumps([registro]), encoding="utf-8")
    assert preparar.main(["--ibge", MUN, "--zip", str(caminho), "--url", "https://outra.invalida/x",
                          "--saida", str(saida)]) == 2
    assert "diverge do MANIFESTO" in capsys.readouterr().err
    outro = tmp_path / "outro.json"
    outro.write_text(json.dumps([]), encoding="utf-8")
    assert preparar.main(["--ibge", MUN, "--zip", str(caminho), "--manifesto", str(outro),
                          "--saida", str(saida)]) == 2
    assert "não registra" in capsys.readouterr().err


# =============================================================================
# Pipeline: prévia → aplicação → reaplicação → desfazer
# =============================================================================

@pytest.fixture()
def rede(db):
    r = Rede(nome="Rede Sintética do Ideb", uf="SP", codigo_ibge=MUN, status="ativa")
    vizinha = Rede(nome="Rede Vizinha Fictícia", uf="SP", codigo_ibge=OUTRO_MUN, status="ativa")
    db.add_all([r, vizinha])
    db.commit()
    return r


def _estado(db) -> list:
    db.expire_all()
    return sorted((r.avaliacao_id, r.edicao, r.indicador, r.abrangencia, r.codigo_territorio,
                   r.codigo_inep, r.rede_ensino, r.localizacao, r.etapa, r.componente, r.nivel,
                   r.valor, r.casas_decimais, r.motivo_ausencia, r.unidade, r.desenho,
                   r.importacao_id, r.created_at, r.updated_at)
                  for r in db.execute(select(IndicadorReferencia)).scalars())


def _aplicar(db, rede, conteudo, nome="pacote.zip"):
    p = pipeline_ideb.previa(db, rede, conteudo, nome, usuario_id=None)
    db.commit()
    a = pipeline_ideb.aplicar(db, rede, p["id"], conteudo, nome, usuario_id=None)
    db.commit()
    return p, a


def test_previa_nao_grava_aplicar_reaplicar_e_desfazer_exato(db, rede, pacote_mun, pacote_uf,
                                                           pacote_br):
    antes = _estado(db)
    p = pipeline_ideb.previa(db, rede, pacote_mun, "pacote.zip", usuario_id=None)
    db.commit()
    assert _estado(db) == antes
    imp = db.get(ImportacaoIndicador, p["id"])
    assert (imp.parser, imp.parser_versao, imp.modo, imp.status) == (
        it.PARSER_MUNICIPIOS, it.VERSAO_PARSER, "pacote_cli", "previa")
    assert imp.arquivo_nome == "mun.zip" and imp.edicao_arquivo == 2025
    assert imp.arquivo_data == datetime(2031, 6, 2, 8, 15)
    assert imp.last_modified_origem == "Mon, 03 Mar 2031 10:00:00 GMT"
    assert imp.coletado_em == datetime(2031, 3, 4, 10, 0)
    assert "por município" in imp.fonte_nome and "Inep" in imp.citacao
    assert p["contadores"]["novas"] == 46 and p["contadores"]["escolas_casadas"] == 0
    assert p["abrangencia"] == "municipio" and p["redes_no_arquivo"][1]["gravada"] is False
    assert p["pacote"]["abrangencia"] == "municipio"
    assert p["pacote"]["origem"]["baixado_em"] == "2031-03-04T10:00:00+00:00"
    a = pipeline_ideb.aplicar(db, rede, p["id"], pacote_mun, "outro_nome.zip", usuario_id=None)
    db.commit()
    assert a["status"] == "aplicada"
    _, b = _aplicar(db, rede, pacote_uf)
    _, c = _aplicar(db, rede, pacote_br)
    assert b["contadores"]["novas"] == 3 * 11 * 4 + 3 * 2 - 3        # sem o P de 2025
    assert c["contadores"]["novas"] == 4 * (4 * 11 + 2)
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 0     # nada por escola
    depois = _estado(db)
    territorios = {(t, r) for (_, _, _, _, t, _, r, *_) in depois}
    assert territorios == {(MUN, "municipal"), ("35", "total"), ("35", "publica"),
                           ("35", "estadual"), ("BR", "total"), ("BR", "estadual"),
                           ("BR", "municipal"), ("BR", "publica")}
    for pac in (pacote_mun, pacote_uf, pacote_br):
        _, de_novo = _aplicar(db, rede, pac)
        assert de_novo["contadores"]["novas"] == 0 and de_novo["contadores"]["alteradas"] == 0
    assert _estado(db) == depois                                          # idempotente
    lista = pipeline_ideb.listar(db, rede)
    assert {i["parser"] for i in lista} == {it.PARSER_MUNICIPIOS, it.PARSER_UF_BRASIL}
    for item in lista:                                                    # do fim para o início
        if item["status"] == "aplicada":
            pipeline_ideb.desfazer(db, rede, item["id"], usuario_id=None)
            db.commit()
    assert _estado(db) == antes                                           # exato


def test_divulgacao_mais_nova_vale_e_a_anterior_fica_mantida(db, rede, tmp_path):
    ed23 = (2019, 2021, 2023)
    antigo = _preparar(tmp_path, planilha(
        [{**MUNICIPAL, "valores": valores(1, edicoes=ed23, VL_OBSERVADO_2021=1.9)}],
        edicoes=ed23), nome="divulgacao_anos_iniciais_municipios_2023.zip").pacote
    novo = _preparar(tmp_path, planilha([MUNICIPAL]), nome="novo.zip").pacote

    def ideb_21():
        db.expire_all()
        return db.execute(select(IndicadorReferencia).where(
            IndicadorReferencia.indicador == "ideb", IndicadorReferencia.edicao == 2021,
            IndicadorReferencia.abrangencia == "municipio")).scalar_one()

    _, a1 = _aplicar(db, rede, antigo)
    p2, a2 = _aplicar(db, rede, novo)
    assert ideb_21().valor == 1.3 and ideb_21().importacao_id == a2["id"]
    mudanca = next(m for m in p2["mudancas"] if m["indicador"] == "ideb" and m["edicao"] == 2021)
    assert (mudanca["tipo"], mudanca["antes"], mudanca["depois"]) == ("alterada", 1.9, 1.3)
    # na ordem inversa, o arquivo de edição mais antiga NÃO desfaz o mais novo
    for imp_id in (a2["id"], a1["id"]):
        pipeline_ideb.desfazer(db, rede, imp_id, usuario_id=None)
        db.commit()
    _aplicar(db, rede, novo)
    p3, _ = _aplicar(db, rede, antigo)
    assert p3["contadores"]["mantidas"] >= 1 and ideb_21().valor == 1.3


def test_nada_polui_opcoes_nem_correlacao(db, rede, pacote_mun, pacote_br):
    _aplicar(db, rede, pacote_mun)
    _aplicar(db, rede, pacote_br)
    assert svc.opcoes_rede(db, rede.id) == []
    corr = svc.correlacao_rede(db, rede.id, avaliacao_chave="ideb", indicador="ideb",
                               edicao=2025, etapa="anos_iniciais", componente=None)
    assert corr["pontos"] == [] and corr["evolucao"] == []


def _saeb_do_brasil_municipal(db) -> dict:
    """{(indicador, localização, componente): valor} do Brasil municipal, 5º ano, 2025."""
    db.expire_all()
    return {(r.indicador, r.localizacao, r.componente): r.valor
            for r in db.execute(select(IndicadorReferencia).where(
                IndicadorReferencia.abrangencia == "brasil",
                IndicadorReferencia.rede_ensino == "municipal",
                IndicadorReferencia.etapa == "5_ano", IndicadorReferencia.edicao == 2025,
                IndicadorReferencia.indicador.in_(("proficiencia", "nota_saeb")))).scalars()}


def _estado_saeb(db) -> list:
    return [e for e in _estado(db) if e[2] in ("proficiencia", "pct_nivel", "tx_alfabetizado")]


def test_nota_do_saeb_do_ideb_nunca_vira_a_media_total_da_planilha(db, rede, tmp_path):
    """Total ≠ Urbana (fixtures SINTÉTICAS): a planilha do Saeb grava a média Total e a
    Urbana separadas; a nota do Saeb do Ideb do Brasil municipal é a das URBANAS. Ela fica
    na chave do Ideb (``nota_saeb``), com o rótulo do universo — nunca no lugar da média
    Total da planilha, e uma importação não mexe na outra (nem ao desfazer)."""
    caminho = tmp_path / "saeb_2025_brasil_estados_municipios.xlsx"
    caminho.write_bytes(planilha_saeb())
    saeb = preparar.preparar_saeb(codigo_ibge=MUN, planilha=caminho, agora=AGORA,
                                  url="https://exemplo.invalido/saeb_sintetico.xlsx",
                                  last_modified="Mon, 03 Mar 2031 10:00:00 GMT",
                                  baixado_em="2031-03-04T10:00:00+00:00").pacote
    p_saeb = pipeline_saeb.previa(db, rede, saeb, "saeb.zip", usuario_id=None)
    db.commit()
    pipeline_saeb.aplicar(db, rede, p_saeb["id"], saeb, "saeb.zip", usuario_id=None)
    db.commit()
    planilha_br = _saeb_do_brasil_municipal(db)
    total_lp, urbana_lp = (planilha_br[("proficiencia", loc, "lp")] for loc in ("total", "urbana"))
    urbana_mt = planilha_br[("proficiencia", "urbana", "mt")]
    assert total_lp != urbana_lp                                   # o caso que importa
    antes_saeb = _estado_saeb(db)

    # o Ideb do Brasil com a nota do Saeb da rede municipal = a média URBANA da planilha
    linhas = [{**ln, "valores": valores(k, VL_NOTA_PORTUGUES_2025=urbana_lp,
                                        VL_NOTA_MATEMATICA_2025=urbana_mt)}
              if ln["rede"] == "Municipal" else ln for k, ln in enumerate(BRASIL_LINHAS)]
    ideb_br = _preparar(tmp_path, planilha(linhas, layout="brasil"),
                        nome="divulgacao_brasil_ideb_2025.zip").pacote
    p, a = _aplicar(db, rede, ideb_br)
    assert p["universo_saeb"]["por_rede"]["municipal"]["universo"] == it.UNIVERSO_URBANAS
    assert p["universo_saeb"]["por_rede"]["total"]["universo"] == it.UNIVERSO_TODAS
    assert any(av.startswith("Universo do INEP no Ideb do Brasil") for av in p["avisos"])
    assert {m["indicador"] for m in p["mudancas"]}.isdisjoint({"proficiencia", "pct_nivel"})
    assert {m["indicador"] for m in p_saeb["mudancas"]}.isdisjoint({"nota_saeb", "ideb"})
    imp = db.get(ImportacaoIndicador, a["id"])
    assert imp.resumo["universo_saeb"] == p["universo_saeb"]           # fica no resumo

    depois = _saeb_do_brasil_municipal(db)
    assert depois[("nota_saeb", "total", "lp")] == urbana_lp          # chave do Ideb oficial
    assert depois[("nota_saeb", "total", "lp")] != depois[("proficiencia", "total", "lp")]
    assert depois[("proficiencia", "total", "lp")] == total_lp        # a Total intacta
    assert it.universo_saeb("brasil", "municipal") == it.UNIVERSO_URBANAS
    assert _estado_saeb(db) == antes_saeb
    pipeline_ideb.desfazer(db, rede, a["id"], usuario_id=None)
    db.commit()
    assert _estado_saeb(db) == antes_saeb
    assert ("nota_saeb", "total", "lp") not in _saeb_do_brasil_municipal(db)


def test_pacote_de_outra_rede_e_o_da_planilha_crua_sao_recusados(db, rede, pacote_mun):
    vizinha = db.execute(select(Rede).where(Rede.codigo_ibge == OUTRO_MUN)).scalar_one()
    with pytest.raises(ImportacaoRecusada, match=f"recortado para o município {MUN}"):
        pipeline_ideb.previa(db, vizinha, pacote_mun, "p.zip", usuario_id=None)
    db.rollback()
    with pytest.raises(ImportacaoRecusada, match="uma planilha"):
        pipeline_ideb.previa(db, rede, planilha([MUNICIPAL]), "x.xlsx", usuario_id=None)
    db.rollback()
    with pytest.raises(ImportacaoRecusada, match="o zip do INEP inteiro"):
        pipeline_ideb.previa(db, rede, zip_ideb(planilha([MUNICIPAL])), "x.zip", usuario_id=None)
    db.rollback()
    assert db.scalar(select(func.count(ImportacaoIndicador.id))) == 0


def test_textos_de_proveniencia_cabem_nas_colunas():
    for texto in pipeline_ideb.FONTE_NOME_TERRITORIO.values():
        assert len(texto) <= 120
    for texto in pipeline_ideb.CITACAO_TERRITORIO.values():
        assert len(texto) <= 500


# =============================================================================
# API: permissões e fluxo
# =============================================================================

def _cliente(db, email: str, **campos) -> TestClient:
    db.add(Usuario(nome=email, email=email, senha_hash=hash_senha("s3nh4terr1"), **campos))
    db.commit()
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", data={"username": email, "password": "s3nh4terr1"})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def test_api_mesmas_rotas_do_ideb_so_admin_global(db, escola_completa, cliente_global, rede,
                                                  pacote_uf):
    secretaria = _cliente(db, "sec@terr.gov", cargo="coordenador", rede_id=rede.id)
    url = f"/api/v1/redes/{rede.id}/indicadores/ideb"
    assert secretaria.post(f"{url}/previa", files={"arquivo": ("p.zip", pacote_uf)}).status_code == 403
    p = cliente_global.post(f"{url}/previa", files={"arquivo": ("p.zip", pacote_uf)})
    assert p.status_code == 200, p.text
    assert p.json()["parser"] == it.PARSER_UF_BRASIL and p.json()["abrangencia"] == "uf"
    ok = cliente_global.post(f"{url}/aplicar", files={"arquivo": ("p.zip", pacote_uf)},
                             data={"previa_id": str(p.json()["id"])})
    assert ok.status_code == 200 and ok.json()["status"] == "aplicada"
    lista = cliente_global.get(f"{url}/importacoes").json()
    assert lista[0]["id"] == ok.json()["id"] and lista[0]["pode_desfazer"] is True
    no_saeb = cliente_global.post(f"/api/v1/redes/{rede.id}/indicadores/saeb/previa",
                                  files={"arquivo": ("p.zip", pacote_uf)})
    assert no_saeb.status_code == 400 and "planilha do Saeb" in no_saeb.json()["detail"]
    desf = cliente_global.post(f"{url}/importacoes/{ok.json()['id']}/desfazer")
    assert desf.status_code == 200 and desf.json()["status"] == "desfeita"
    db.expire_all()
    assert db.scalar(select(func.count(IndicadorReferencia.id))) == 0


# --- O mesmo fluxo num PostgreSQL de verdade ------------------------------------

from tests.test_migracoes_postgres import engine_postgres  # noqa: E402,F401 — fixture do PG de teste


@pytest.mark.postgres
def test_pipeline_territorio_no_postgres_aplica_reaplica_e_desfaz_exato(engine_postgres,
                                                                        tmp_path):
    from sqlalchemy.orm import sessionmaker

    from app.core.migracoes import aplicar_migracoes

    aplicar_migracoes(engine_postgres)
    db = sessionmaker(bind=engine_postgres)()
    try:
        r = Rede(nome="Rede Sintética PG", uf="SP", codigo_ibge=MUN, status="ativa")
        db.add(r)
        db.commit()
        antes = _estado(db)
        pacotes = [_preparar(tmp_path, planilha([MUNICIPAL, PUBLICA])).pacote,
                   _preparar(tmp_path, planilha(UF_LINHAS, layout="uf", p_repetido=True),
                             nome="uf.zip").pacote]
        for dados in pacotes:
            _aplicar(db, r, dados)
        depois = _estado(db)
        assert db.scalar(select(func.count(IndicadorReferencia.id)).where(
            IndicadorReferencia.valor.is_(None))) > 0                # ausências no PG
        for dados in pacotes:
            _, b = _aplicar(db, r, dados)
            assert b["contadores"]["novas"] == 0
        assert _estado(db) == depois
        for item in pipeline_ideb.listar(db, r):
            if item["status"] == "aplicada":
                pipeline_ideb.desfazer(db, r, item["id"], usuario_id=None)
                db.commit()
        assert _estado(db) == antes
    finally:
        db.close()
