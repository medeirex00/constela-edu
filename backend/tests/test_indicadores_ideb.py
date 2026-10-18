"""Ideb e Saeb POR ESCOLA (etapa E6a): o parser ``inep_ideb_escolas`` do xlsx do INEP,
a linha de comando ``preparar`` → PACOTE recortado → prévia/aplicação/desfazer do
fluxo de escolas, e a regressão das consultas (opções e correlação).

FIXTURES SINTÉTICAS no layout REAL do arquivo do INEP: pré-âmbulo e cabeçalho em
várias linhas, a linha técnica, o dígito de nota de rodapé grudado no ano dos
rótulos, "-", "ND", "ND**", número em texto com vírgula e com "*", colunas fora de
ordem, edição ausente, rodapé no fim da aba. NADA aqui é dado do INEP: o município,
os INEPs, os nomes, as datas e TODOS os números são INVENTADOS (decisão D13 do plano:
repositório público, licença CC BY-ND) — e ficam longe da faixa dos oficiais.
"""
import csv
import fnmatch
import hashlib
import io
import json
import random
import struct
import tracemalloc
import zipfile
import zlib
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import OperationalError

from app.core.security import hash_senha
from app.main import app
from app.models import (Escola, ImportacaoIndicador, IndicadorReferencia, LogAuditoria, Rede,
                        ResultadoAvaliacao, Usuario)
from app.services import avaliacoes as svc
from app.services.avaliacoes import ImportacaoRecusada
from app.services.indicadores import (consulta_ideb, ica, ideb, pacote, pacote_ideb, pacote_saeb,
                                      pipeline_ideb, preparar)

MUN = "3599999"                # IBGE SINTÉTICO (não existe)
OUTRO_MUN = "3599998"          # outro município SINTÉTICO
NOME_MUN = "Cidade Sintética"
TITULO = "Ensino Fundamental Regular - Anos Iniciais"
AGORA = datetime(2031, 5, 14, 9, 30)          # data INVENTADA
DATA_ZIP = (2031, 6, 2, 8, 15, 0)             # data INVENTADA

_APROV = ("SI_4", "SI", "1", "2", "3", "4")
_SERIE = {"SI_4": "1º ao 5º ano", "SI": "1º", "1": "2º", "2": "3º", "3": "4º", "4": "5º"}
_IDS = (("SG_UF", "Sigla da UF"), ("CO_MUNICIPIO", "Código do Município"),
        ("NO_MUNICIPIO", "Nome do Município"), ("ID_ESCOLA", "Código da Escola"),
        ("NO_ESCOLA", "Nome da Escola"), ("REDE", "Rede"))


def _rot(ano: int) -> str:
    """O ano como nos rótulos do INEP: 2021 leva o dígito da nota de rodapé ("20211")."""
    return f"{ano}1" if ano == 2021 else str(ano)


def _colunas(edicoes, metas) -> list[tuple]:
    """(nome técnico, grupo, componente, série) na ORDEM do arquivo real."""
    cols = []
    for ano in edicoes:
        for suf in _APROV:
            cols.append((f"VL_APROVACAO_{ano}_{suf}", f"Taxa de Aprovação - {_rot(ano)}", None,
                         _SERIE[suf]))
        cols.append((f"VL_INDICADOR_REND_{ano}", f"Taxa de Aprovação - {_rot(ano)}", None,
                     "Indicador de Rendimento (P)"))
    for ano in edicoes:
        cols += [(f"VL_NOTA_MATEMATICA_{ano}", f"Nota SAEB - {_rot(ano)}", "Matemática", None),
                 (f"VL_NOTA_PORTUGUES_{ano}", f"Nota SAEB - {_rot(ano)}", "Língua Portuguesa", None),
                 (f"VL_NOTA_MEDIA_{ano}", f"Nota SAEB - {_rot(ano)}", "Nota Média Padronizada (N)",
                  None)]
    for ano in edicoes:
        cols.append((f"VL_OBSERVADO_{ano}", f"IDEB\n{_rot(ano)}\n(N x P)", None, None))
    for ano in metas:
        cols.append((f"VL_PROJECAO_{ano}", "Metas do 1º ciclo do Ideb2,3 (2007-2021)", None, ano))
    return cols


# --- As escolas do arquivo SINTÉTICO (todos os números INVENTADOS) ---------------

# (edição, aprovação 1º–5º, 1º, 2º, 3º, 4º, 5º, P, MT, LP, N, Ideb)
_ALFA = [(2019, 51.4, 54.2, 48.3, 45.1, 39.7, 42.6, 0.612347, 131.47, 124.83, 2.381946, 1.5),
         (2021, 53.2, 54.9, 50.1, 47.3, 42.8, 45.4, 0.637219, 133.29, 127.61, 2.452318, 1.6),
         (2023, 55.7, 55.1, 52.9, 49.4, 44.2, 48.8, 0.659821, 135.18, 129.94, 2.513467, 1.7)]
_BETA = [(2019, 34.6, 37.2, 33.9, 31.8, 35.3, 32.7, 0.608426, "123,47*", "118,29*", 2.164903, 1.5),
         (2021, 36.1, 38.3, 35.2, 33.4, 36.9, 34.8, 0.593518, "ND", "ND", "-", "-"),
         (2023, *(["-"] * 11))]
_GAMA = [(2019, 41.2, 43.4, 40.8, 39.9, 42.1, 40.3, 0.584215, "ND**", "ND**", "-", "-"),
         (2021, 42.7, 44.6, 41.3, 40.6, 43.8, 43.2, 0.597342, 121.36, 116.72, 2.217539, 1.5),
         (2023, 43.9, 45.1, 42.4, 41.7, 44.5, 45.9, 0.602631, 122.59, 117.84, 2.246183, 1.6)]
_METAS = {"ALFA": {2019: 2.3, 2021: 2.4}, "BETA": {2019: "-", 2021: 2.2},
          "GAMA": {2019: 1.8, 2021: 2.2}}
_CAMPOS = ("VL_APROVACAO_{a}_SI_4", "VL_APROVACAO_{a}_SI", "VL_APROVACAO_{a}_1",
           "VL_APROVACAO_{a}_2", "VL_APROVACAO_{a}_3", "VL_APROVACAO_{a}_4",
           "VL_INDICADOR_REND_{a}", "VL_NOTA_MATEMATICA_{a}", "VL_NOTA_PORTUGUES_{a}",
           "VL_NOTA_MEDIA_{a}", "VL_OBSERVADO_{a}")


def _valores(tabela, metas) -> dict:
    v = {}
    for ano, *nums in tabela:
        for campo, n in zip(_CAMPOS, nums):
            v[campo.format(a=ano)] = n
    for ano, n in metas.items():
        v[f"VL_PROJECAO_{ano}"] = n
    return v


def _escola(inep, nome, valores, *, mun=MUN, nome_mun=NOME_MUN, rede="Municipal") -> dict:
    return {"uf": "SP", "mun": mun, "nome_mun": nome_mun, "inep": inep, "nome": nome,
            "rede": rede, "valores": valores}


ALFA = _escola("35990101", "EMEF SINTETICA ALFA", _valores(_ALFA, _METAS["ALFA"]))
BETA = _escola("35990102", "EMEF SINTETICA BETA", _valores(_BETA, _METAS["BETA"]))
GAMA = _escola("35990103", "EMEF SINTETICA GAMA (fora do cadastro)",
               _valores(_GAMA, _METAS["GAMA"]))
ESTADUAL = _escola("35990104", "EE SINTETICA DO MUNICIPIO", _valores(_ALFA, _METAS["ALFA"]),
                   rede="Estadual")
# O homônimo da ALFA em OUTRO município, com outro INEP: nunca entra.
HOMONIMO = _escola("35980101", "EMEF SINTETICA ALFA", _valores(_GAMA, _METAS["GAMA"]),
                   mun=OUTRO_MUN, nome_mun="Outra Cidade Ficticia")
# Escola do CADASTRO cuja linha, no arquivo, é de OUTRO município: não entra.
DELTA = _escola("35990105", "EMEF SINTETICA DELTA", _valores(_ALFA, _METAS["ALFA"]),
                mun=OUTRO_MUN, nome_mun="Outra Cidade Ficticia")
ESCOLAS = [ALFA, BETA, GAMA, ESTADUAL, HOMONIMO, DELTA]


def planilha(escolas=None, *, edicoes=(2019, 2021, 2023), metas=(2019, 2021),
             embaralhar=False, titulo=TITULO, sem=(), rotulos=None, tecnica=None,
             rodape=True) -> bytes:
    """O xlsx SINTÉTICO no layout real. ``embaralhar`` põe as colunas de valor fora de
    ordem (cada uma com o seu rótulo); ``rotulos`` troca rótulos ({nome: (grupo,
    componente, série)}); ``tecnica`` troca nomes da linha técnica ({nome: novo})."""
    escolas = ESCOLAS if escolas is None else escolas
    cols = [c for c in _colunas(edicoes, metas) if c[0] not in sem]
    if embaralhar:
        random.Random(3).shuffle(cols)
    cols = [(n, *(rotulos or {}).get(n, (g, c, s))) for n, g, c, s in cols]
    grupos = [g for _, g, _, _ in cols]
    if not embaralhar:                    # célula mesclada: só a 1ª do grupo tem o rótulo
        grupos = [g if k == 0 or g != grupos[k - 1] else None for k, g in enumerate(grupos)]
    wb = Workbook()
    ws = wb.active
    ws.title = "IDEB_Escolas (Anos_Iniciais)"
    ws.append([None, None, "Cabeçalho institucional sintético"])
    ws.append([None])
    ws.append([titulo])
    ws.append([f"Indicadores sintéticos de {', '.join(_rot(a) for a in edicoes)} e Metas do 1º "
               "ciclo do Ideb2,3 (2007-2021), por escola e rede."])
    ws.append([None])
    ws.append([r for _, r in _IDS] + grupos)
    ws.append([None] * len(_IDS) + [c for _, _, c, _ in cols])
    ws.append([None] * len(_IDS) + [s for _, _, _, s in cols])
    ws.append([(tecnica or {}).get(n, n) for n in [n for n, _ in _IDS] + [c[0] for c in cols]])
    for e in escolas:
        ws.append([e["uf"], int(e["mun"]), e["nome_mun"], int(e["inep"]), e["nome"], e["rede"]]
                  + [e["valores"].get(n, "-") for n, _, _, _ in cols])
    if rodape:
        ws.append([None])
        ws.append(["Fonte: arquivo sintético de teste"])
        ws.append(["Notas: ND - marcador sintético de não divulgação;"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _linhas(conteudo: bytes) -> list:
    wb = load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    try:
        return list(ideb.linhas_da_planilha(wb)[1])
    finally:
        wb.close()


def _ler(conteudo: bytes = None, **kw) -> ideb.LeituraIdeb:
    return ideb.ler_grade(_linhas(conteudo or planilha()), codigo_ibge=MUN, **kw)


def _cel(leitura, inep, nome):
    return next(e for e in leitura.escolas if e.inep == inep).celulas[nome]


# =============================================================================
# Parser
# =============================================================================

def test_layout_real_cabecalho_em_varias_linhas_rodape_e_recorte_da_rede():
    leitura = _ler(nome="divulgacao_anos_iniciais_escolas_2023.xlsx")
    assert leitura.edicoes == [2019, 2021, 2023] and leitura.anos_meta == [2019, 2021]
    assert leitura.edicao_arquivo == 2023
    # Só a rede MUNICIPAL do município: a estadual, o homônimo e a DELTA (outro
    # município) ficam de fora — pelo código, nunca pelo nome.
    assert [e.inep for e in leitura.escolas] == ["35990101", "35990102", "35990103"]
    assert leitura.linhas_lidas == 6 and dict(leitura.outras_redes) == {"estadual": 1}
    assert leitura.municipio_nome == NOME_MUN
    assert leitura.notas == ["Fonte: arquivo sintético de teste",
                             "Notas: ND - marcador sintético de não divulgação;"]
    assert _cel(leitura, "35990101", "VL_OBSERVADO_2021").valor == 1.6
    assert _cel(leitura, "35990101", "VL_NOTA_PORTUGUES_2023").valor == 129.94
    # texto com vírgula e "*" (nota do INEP): número, com aviso
    beta_mt = _cel(leitura, "35990102", "VL_NOTA_MATEMATICA_2019")
    assert (beta_mt.valor, beta_mt.casas, beta_mt.asterisco) == (123.47, 2, True)
    assert "INEP 35990102 VL_NOTA_MATEMATICA_2019" in leitura.asteriscos
    # "-", "ND" e "ND**" viram ausência, contados pelo marcador original
    assert _cel(leitura, "35990102", "VL_NOTA_MATEMATICA_2021").marcador == "ND"
    assert _cel(leitura, "35990103", "VL_NOTA_PORTUGUES_2019").marcador == "ND**"
    assert leitura.marcadores["ND"] == 2 and leitura.marcadores["ND**"] == 2
    assert leitura.marcadores["-"] == 16
    # precisão publicada por coluna (N e P com 6 casas; Ideb com 1)
    assert leitura.casas["VL_NOTA_MEDIA_2019"] == 6 and leitura.casas["VL_OBSERVADO_2019"] == 1
    avisos = " ".join(leitura.avisos)
    assert "não definiu meta do Ideb para 2023" in avisos and "pandemia" in avisos
    assert "1 escola(s) do município em outra rede (estadual)" in avisos


def test_colunas_fora_de_ordem_dao_os_mesmos_numeros():
    real, fora = _ler(), _ler(planilha(embaralhar=True))
    assert [c.nome for c in real.colunas] != [c.nome for c in fora.colunas]
    assert {e.inep: e.celulas for e in real.escolas} == {e.inep: e.celulas for e in fora.escolas}
    assert real.edicoes == fora.edicoes and real.anos_meta == fora.anos_meta


def test_aprovacao_por_serie_pelo_sufixo_conferido_com_o_rotulo():
    leitura = _ler()
    etapas = {c.nome: c.etapa for c in leitura.colunas if c.familia == "aprovacao" and c.ano == 2019}
    assert etapas == {"VL_APROVACAO_2019_SI_4": "anos_iniciais", "VL_APROVACAO_2019_SI": "1_ano",
                      "VL_APROVACAO_2019_1": "2_ano", "VL_APROVACAO_2019_2": "3_ano",
                      "VL_APROVACAO_2019_3": "4_ano", "VL_APROVACAO_2019_4": "5_ano"}
    trocado = planilha(rotulos={"VL_APROVACAO_2019_SI": ("Taxa de Aprovação - 2019", None, "3º")})
    with pytest.raises(ImportacaoRecusada, match="sufixo da variável é de 1 ano"):
        _ler(trocado)


def test_digito_de_rodape_nos_rotulos_e_ano_do_rotulo_que_diverge():
    assert ideb.anos_do_rotulo("IDEB\n20211\n(N x P)") == {2021}
    assert ideb.anos_do_rotulo("Metas do 1º ciclo do Ideb2,3 (2007-2021)") == {2007, 2021}
    assert ideb.anos_do_rotulo("1º ao 5º ano") == set()
    assert ideb.etapa_do_rotulo("5º2") == "5_ano" and ideb.etapa_do_rotulo("1º ao 5º ano") == "anos_iniciais"
    errado = planilha(rotulos={"VL_OBSERVADO_2019": ("IDEB\n2017\n(N x P)", None, None)})
    with pytest.raises(ImportacaoRecusada, match="fala de 2017, não de 2019"):
        _ler(errado)


def test_edicao_ausente_nao_vira_ausencia_e_bloco_incompleto_recusa():
    sem_2021 = _ler(planilha(edicoes=(2019, 2023)))
    assert sem_2021.edicoes == [2019, 2023]
    assert not any("2021" in n for e in sem_2021.escolas for n in e.celulas
                   if not n.startswith("VL_PROJECAO"))
    incompleto = planilha(sem=("VL_NOTA_PORTUGUES_2021",))
    with pytest.raises(ImportacaoRecusada, match="2021 está incompleta.*VL_NOTA_PORTUGUES_2021"):
        _ler(incompleto)
    # N/P/aprovação de uma edição faltando: lê o resto (não são o núcleo do Ideb)
    sem_n = _ler(planilha(sem=("VL_NOTA_MEDIA_2023",)))
    assert "VL_NOTA_MEDIA_2023" not in sem_n.escolas[0].celulas


# A edição 2025 (INVENTADA, como as outras): o arquivo de 2025 traz um bloco a mais em
# cada grupo, e todas as colunas depois dele mudam de posição.
_ALFA_2025 = [(2025, 54.3, 53.6, 51.8, 48.2, 43.1, 47.5, 0.664318, 133.71, 128.26, 2.497125, 1.9)]


def test_arquivo_de_2025_edicao_pelo_nome_e_sem_metas_depois_de_2021():
    """O parser da E6a lê o arquivo de 2025 SEM mudança: a edição 2025 é achada PELO
    NOME da coluna (as posições mudaram), as metas continuam só até 2021 e nada de 2023 e
    2025 vira meta."""
    alfa = {**ALFA, "valores": {**ALFA["valores"], **_valores(_ALFA_2025, {})}}
    conteudo = planilha([alfa, BETA, ESTADUAL], edicoes=(2019, 2021, 2023, 2025),
                        metas=(2019, 2021))
    leitura = _ler(conteudo, nome="divulgacao_anos_iniciais_escolas_2025.xlsx")
    assert leitura.edicoes == [2019, 2021, 2023, 2025] and leitura.anos_meta == [2019, 2021]
    assert leitura.edicao_arquivo == 2025
    assert _cel(leitura, "35990101", "VL_OBSERVADO_2025").valor == 1.9
    assert _cel(leitura, "35990101", "VL_NOTA_PORTUGUES_2025").valor == 128.26
    assert _cel(leitura, "35990101", "VL_OBSERVADO_2023").valor == 1.7       # a 2023 intacta
    assert _cel(leitura, "35990102", "VL_OBSERVADO_2025").marcador == "-"     # ausência
    assert any("2023, 2025" in a and "não definiu" in a for a in leitura.avisos)
    cadastro = {"35990101": {"id": 1, "rede_id": 7, "nome": "EMEF Sintética Alfa"}}
    rec, extra = ideb.recortar(leitura, cadastro, codigo_ibge=MUN)
    assert extra["edicoes"] == [2019, 2021, 2023, 2025]
    assert sorted({n.linha.edicao for n in rec.referencia
                   if n.linha.indicador == ideb.IND_META}) == [2019, 2021]
    assert {ln.edicao for ln in rec.escolares} == {2019, 2021, 2023, 2025}


@pytest.mark.parametrize("valor, trecho", [
    ("abc", "não é número nem marcador"), (11.2, "fora da faixa do Ideb"),
])
def test_valor_que_nao_e_numero_nem_marcador_ou_fora_da_faixa_recusa(valor, trecho):
    alfa = {**ALFA, "valores": {**ALFA["valores"], "VL_OBSERVADO_2019": valor}}
    with pytest.raises(ImportacaoRecusada, match=trecho):
        _ler(planilha([alfa, BETA]))
    p_errado = {**ALFA, "valores": {**ALFA["valores"], "VL_INDICADOR_REND_2019": 1.3}}
    with pytest.raises(ImportacaoRecusada, match="fora da faixa do P"):
        _ler(planilha([p_errado]))


def test_inep_repetido_coluna_repetida_e_falta_de_coluna_recusam():
    with pytest.raises(ImportacaoRecusada, match="35990101 aparece em mais de uma linha"):
        _ler(planilha([ALFA, ALFA]))
    with pytest.raises(ImportacaoRecusada, match="VL_OBSERVADO_2019 aparece mais de uma vez"):
        _ler(planilha(tecnica={"VL_OBSERVADO_2021": "VL_OBSERVADO_2019"}))
    with pytest.raises(ImportacaoRecusada, match="não tem a coluna REDE"):
        _ler(planilha(tecnica={"REDE": "TIPO"}))


def test_linha_tecnica_so_com_a_identificacao_recusa_com_a_causa(tmp_path, capsys):
    """Sem nenhuma coluna de valor: recusa clara (antes caía num ``min`` de lista vazia
    — ValueError, que a rota da prévia devolvia como 500)."""
    with pytest.raises(ImportacaoRecusada, match="nenhuma edição do Ideb"):
        _ler(planilha(edicoes=(), metas=()))
    caminho = tmp_path / "d.zip"
    caminho.write_bytes(zip_ideb(planilha(edicoes=(), metas=())))
    assert preparar.main(["--ibge", MUN, "--zip", str(caminho), "--saida",
                          str(tmp_path / "s")]) == 2
    erro = capsys.readouterr().err
    assert "nenhuma edição do Ideb" in erro and "min()" not in erro
    assert not (tmp_path / "s").exists()


def test_linha_da_rede_sem_codigo_de_escola_valido_recusa_e_nao_vira_rodape():
    conteudo = planilha([{**ALFA, "inep": "35990107"}, BETA])
    wb = load_workbook(io.BytesIO(conteudo))
    for linha in wb.active.iter_rows():
        if linha[3].value == 35990107:
            linha[3].value = "35.990.107"
    buf = io.BytesIO()
    wb.save(buf)
    with pytest.raises(ImportacaoRecusada, match="não tem código de escola válido"):
        _ler(buf.getvalue())


def test_etapa_do_topo_e_ideb_de_municipio_ou_uf_sao_recusados():
    with pytest.raises(ImportacaoRecusada, match="outra etapa"):
        _ler(planilha(titulo="Ensino Fundamental Regular - Anos Finais"))
    with pytest.raises(ImportacaoRecusada, match="não indica a etapa"):
        _ler(planilha(titulo="Planilha sintética", edicoes=(2019,), metas=(),
                      rotulos={f"VL_APROVACAO_2019_{s}": ("Taxa", None, None) for s in _APROV}))
    with pytest.raises(ImportacaoRecusada, match="Ideb por MUNICÍPIO"):
        _ler(planilha(tecnica={"ID_ESCOLA": "CO_ESCOLA_X"}))


def test_sem_escola_da_rede_avisa_e_nada_a_importar():
    leitura = _ler(planilha([HOMONIMO, DELTA]))
    assert leitura.recorte == [] and "Nenhuma escola da rede MUNICIPAL" in " ".join(leitura.avisos)


def test_recortar_casa_pelo_inep_e_lista_fora_do_cadastro_e_sem_linha():
    cadastro = {"35990101": {"id": 1, "rede_id": 7, "nome": "EMEF Sintética Alfa"},
                "35990102": {"id": 2, "rede_id": 7, "nome": "EMEF Sintética Beta"},
                "35990105": {"id": 5, "rede_id": 7, "nome": "EMEF Sintética Delta"}}
    leitura, extra = ideb.recortar(_ler(), cadastro, codigo_ibge=MUN)
    assert [d["codigo_inep"] for d in leitura.escolas_casadas] == ["35990101", "35990102"]
    assert [d["codigo_inep"] for d in leitura.fora_do_cadastro] == ["35990103"]
    assert [d["codigo_inep"] for d in extra["sem_linha_no_arquivo"]] == ["35990105"]
    # 2 escolas × 3 edições × (Ideb + Saeb MT + Saeb LP)
    assert len(leitura.escolares) == 18
    # 2 escolas × (3 edições × (N + P + 6 aprovações) + 2 metas)
    assert len(leitura.referencia) == 52
    ideb_alfa = {ln.edicao: ln for ln in leitura.escolares
                 if ln.escola_id == 1 and ln.indicador == "ideb"}
    assert ideb_alfa[2023].etapa == "anos_iniciais" and ideb_alfa[2023].componente is None
    assert ideb_alfa[2023].unidade == "indice" and ideb_alfa[2023].valor == 1.7
    saeb = {(ln.edicao, ln.componente): ln for ln in leitura.escolares
            if ln.escola_id == 2 and ln.avaliacao == "saeb"}
    assert saeb[(2021, "matematica")].valor is None
    assert saeb[(2021, "matematica")].motivo_ausencia == "nao_divulgado"
    assert saeb[(2019, "portugues")].etapa == "5_ano" and saeb[(2019, "portugues")].valor == 118.29
    refs = {(n.linha.indicador, n.linha.edicao, n.linha.etapa): n.linha for n in leitura.referencia
            if n.linha.codigo_inep == "35990101"}
    assert refs[("rendimento_p", 2023, "anos_iniciais")].unidade == "proporcao"
    assert refs[("nota_n", 2019, "anos_iniciais")].casas_decimais == 6
    assert refs[("aprovacao", 2021, "3_ano")].valor == 47.3
    assert refs[("meta", 2021, "anos_iniciais")].valor == 2.4
    assert refs[("meta", 2021, "anos_iniciais")].desenho is None
    assert {n.avaliacao for n in leitura.referencia} == {"ideb"}
    assert extra["cobertura"]["2023"] == {"ideb": 1, "saeb": 1}


# =============================================================================
# preparar → pacote
# =============================================================================

def zip_ideb(xlsx: bytes, *, md5: str | None = "certo", nome="divulgacao_anos_iniciais_escolas_2023",
             outra_planilha=False, data=DATA_ZIP) -> bytes:
    """O zip SINTÉTICO como o do INEP: pasta, .ods, .xlsx e o md5_*.txt (``data`` = a
    data interna das entradas)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        def gravar(caminho, dados):
            info = zipfile.ZipInfo(caminho, date_time=data)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, dados)
        gravar(f"{nome}/", b"")
        gravar(f"{nome}/{nome}.ods", b"ods sintetico (nao lido)")
        gravar(f"{nome}/{nome}.xlsx", xlsx)
        if outra_planilha:
            gravar(f"{nome}/copia.xlsx", xlsx)
        if md5:
            soma = hashlib.md5(xlsx).hexdigest() if md5 == "certo" else md5
            gravar(f"{nome}/md5_{nome}.txt", f"{soma} *{nome}.xlsx\r\n".encode())
    return buf.getvalue()


def _preparar(tmp_path, xlsx=None, nome="ideb.zip", **kw) -> preparar.PreparoIdeb:
    caminho = tmp_path / nome
    caminho.write_bytes(zip_ideb(xlsx or planilha(), **kw))
    return preparar.preparar_ideb(codigo_ibge=MUN, zip_local=caminho, agora=AGORA,
                                  url="https://exemplo.invalido/ideb_sintetico.zip")


def _arquivos(dados: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(dados)) as z:
        return {n: z.read(n) for n in z.namelist()}


def test_preparar_gera_o_pacote_so_com_a_rede_e_o_manifesto(tmp_path):
    preparo = _preparar(tmp_path)
    m = preparo.manifesto
    assert preparo.nome == f"pacote_ideb_escolas_2023_{MUN}.zip"
    assert m["parser"] == ideb.PARSER and m["parser_versao"] == ideb.VERSAO_PARSER
    assert m["tipo"] == pacote.TIPO and m["codigo_territorio_alvo"] == MUN
    assert m["edicao"] == 2023 and m["edicoes"] == [2019, 2021, 2023]
    assert m["anos_meta"] == [2019, 2021] and m["gerado_em"] == "2031-05-14T09:30:00Z"
    zip_original = (tmp_path / "ideb.zip").read_bytes()
    assert m["origem"]["zip_sha256"] == hashlib.sha256(zip_original).hexdigest()
    assert m["origem"]["zip_bytes"] == len(zip_original) and m["origem"]["modo"] == "zip_local"
    xlsx = planilha()
    e = m["entrada"]
    assert e["sha256"] == hashlib.sha256(xlsx).hexdigest() and e["md5_publicado"] == "confere"
    assert e["nome"].endswith(".xlsx") and e["aba"] == "IDEB_Escolas (Anos_Iniciais)"
    assert e["data_interna"] == "2031-06-02T08:15:00"
    assert (e["linhas_original"], e["linhas_recorte"], e["escolas_outras_redes"]) == (6, 3, 1)
    arquivos = _arquivos(preparo.pacote)
    assert sorted(arquivos) == [pacote_ideb.NOME_CSV, pacote.NOME_MANIFESTO]
    recorte = arquivos[pacote_ideb.NOME_CSV]
    assert b"\r" not in recorte and hashlib.sha256(recorte).hexdigest() == e["csv_sha256"]
    texto = recorte.decode("utf-8")
    assert "35990101" in texto and "35990103" in texto            # a rede (casa ou não)
    for fora in ("35990104", "35980101", "35990105"):              # estadual, homônimo, outro mun.
        assert fora not in texto
    assert "ID_ESCOLA" in texto and TITULO in texto and "Fonte: arquivo sintético" in texto
    assert "123,47*" in texto and "ND**" in texto                  # como o INEP escreveu
    assert len(preparo.pacote) < 20_000


def test_preparar_confere_o_md5_do_inep_e_recusa_zip_ambiguo_ou_sem_a_rede(tmp_path):
    with pytest.raises(ImportacaoRecusada, match="não confere com o md5 publicado"):
        _preparar(tmp_path, md5="0" * 32)
    sem_md5 = _preparar(tmp_path, nome="sem.zip", md5=None)
    assert sem_md5.manifesto["entrada"]["md5_publicado"] == "ausente no zip"
    assert any("integridade conferida só pelo CRC32" in a
               for a in sem_md5.manifesto["avisos_preparo"])
    with pytest.raises(ImportacaoRecusada, match="2 planilhas .xlsx"):
        _preparar(tmp_path, nome="duas.zip", outra_planilha=True)
    with pytest.raises(ImportacaoRecusada, match="Nenhum pacote foi gerado"):
        _preparar(tmp_path, xlsx=planilha([HOMONIMO, DELTA]), nome="vazio.zip")


def test_linha_de_comando_detecta_o_zip_do_ideb_e_grava_o_pacote(tmp_path, capsys):
    caminho = tmp_path / "divulgacao_anos_iniciais_escolas_2023.zip"
    caminho.write_bytes(zip_ideb(planilha()))
    assert preparar.zip_do_ideb(caminho)
    saida = tmp_path / "saida"
    assert preparar.main(["--ibge", MUN, "--zip", str(caminho), "--saida", str(saida)]) == 0
    gerado = saida / f"pacote_ideb_escolas_2023_{MUN}.zip"
    assert pacote_ideb.parser_do_pacote(gerado.read_bytes()) == ideb.PARSER
    texto = capsys.readouterr().out
    assert "Edições: 2019, 2021, 2023" in texto and "md5" in texto and "Tempo:" in texto
    assert "2023: Ideb em 2 e Saeb em 2 de 3 escola(s)" in texto
    vazio = tmp_path / "vazio.zip"
    vazio.write_bytes(zip_ideb(planilha([HOMONIMO])))
    assert preparar.main(["--ibge", MUN, "--zip", str(vazio), "--saida", str(tmp_path / "v")]) == 2
    assert "Nada a importar" in capsys.readouterr().err and not (tmp_path / "v").exists()


def test_zip_do_ideb_por_url_e_recusado_so_local(capsys):
    from app.services.indicadores.zip_parcial import Entrada

    entradas = [Entrada("d/divulgacao_anos_iniciais_escolas_2025.xlsx", 8, 0, 0, 1, 1, 0, None),
                Entrada("d/divulgacao_anos_iniciais_escolas_2025.ods", 8, 0, 0, 1, 1, 0, None)]
    with pytest.raises(ImportacaoRecusada, match="só é lido LOCAL"):
        preparar.escolher_entradas(entradas)
    with pytest.raises(SystemExit):
        preparar.main(["--help"])
    assert "Ideb NÃO é lido por URL" in " ".join(capsys.readouterr().out.split())


def test_planilha_extraida_do_zip_e_recusada_com_a_explicacao(tmp_path, capsys):
    """O .xlsx (e o .ods) também são zips: passados soltos, não caem na mensagem dos
    microdados do ICA — o preparar pede o zip do INEP como foi baixado."""
    xlsx = tmp_path / "divulgacao_anos_iniciais_escolas_2023.xlsx"
    xlsx.write_bytes(planilha())
    ods = tmp_path / "divulgacao_anos_iniciais_escolas_2023.ods"
    with zipfile.ZipFile(ods, "w") as z:          # só a estrutura de um OpenDocument
        z.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet")
        z.writestr("META-INF/manifest.xml", "<manifest/>")
        z.writestr("content.xml", "<conteudo-sintetico/>")
    for arquivo, tipo in ((xlsx, "xlsx"), (ods, "ods")):
        assert not preparar.zip_do_ideb(arquivo)
        saida = tmp_path / f"saida_{tipo}"
        assert preparar.main(["--ibge", MUN, "--zip", str(arquivo), "--saida",
                              str(saida)]) == 2
        erro = " ".join(capsys.readouterr().err.split())
        assert f"planilha .{tipo}" in erro and "como foi baixado" in erro
        assert "divulgacao_anos_iniciais_escolas_AAAA.zip" in erro
        assert "TS_MUNICIPIO" not in erro and not saida.exists()
    with pytest.raises(ImportacaoRecusada, match=r"planilha \.xlsx"):
        preparar.preparar_ideb(codigo_ibge=MUN, zip_local=xlsx)


def test_linha_de_comando_avisa_quando_a_saida_fica_dentro_do_repositorio(tmp_path, capsys,
                                                                       monkeypatch):
    caminho = tmp_path / "d.zip"
    caminho.write_bytes(zip_ideb(planilha()))
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    monkeypatch.setattr(preparar, "_raiz_do_repositorio", lambda: repo)
    assert preparar.main(["--ibge", MUN, "--zip", str(caminho), "--saida",
                          str(repo / "backend")]) == 0
    assert "DENTRO do repositório" in capsys.readouterr().err
    assert (repo / "backend" / f"pacote_ideb_escolas_2023_{MUN}.zip").is_file()
    assert preparar.main(["--ibge", MUN, "--zip", str(caminho), "--saida",
                          str(tmp_path / "fora")]) == 0
    assert "DENTRO do repositório" not in capsys.readouterr().err
    # outra pasta com .git ACIMA (ex.: a home) não conta; só o checkout do Constela
    assert not preparar.dentro_do_repositorio(tmp_path / "fora", raiz=tmp_path / "sem_git")
    assert preparar.dentro_do_repositorio(repo / "backend" / "x", raiz=repo)


def test_gitignore_barra_os_pacotes_do_preparar_e_os_arquivos_do_inep():
    """D13: nem o recorte nem o arquivo do INEP vão para o repositório público."""
    raiz = Path(preparar.__file__).resolve().parents[4]
    gitignore = raiz / ".gitignore"
    if not gitignore.is_file():
        pytest.skip("sem o .gitignore do repositório (código fora do checkout)")
    padroes = [ln.strip() for ln in gitignore.read_text(encoding="utf-8").splitlines()
               if ln.strip() and not ln.lstrip().startswith("#")]
    for nome in (f"pacote_ideb_escolas_2023_{MUN}.zip", f"pacote_ica_aeeb_2025_{MUN}.zip",
                 "microdados_AEEB_2025.zip", "divulgacao_anos_iniciais_escolas_2023.zip",
                 "divulgacao_anos_iniciais_escolas_2023.xlsx",
                 "divulgacao_anos_iniciais_escolas_2023.ods",
                 "divulgacao_anos_iniciais_municipios_2023.zip"):
        assert any(fnmatch.fnmatchcase(nome, p) for p in padroes), nome


def test_pacote_lido_no_servidor_e_o_mesmo_recorte(tmp_path):
    preparo = _preparar(tmp_path)
    lido = pacote_ideb.ler_pacote(preparo.pacote, preparo.nome, codigo_ibge=MUN)
    assert [e.inep for e in lido.leitura.escolas] == [e.inep for e in preparo.leitura.escolas]
    assert ({e.inep: e.celulas for e in lido.leitura.escolas}
            == {e.inep: e.celulas for e in preparo.leitura.escolas})
    assert lido.leitura.casas == preparo.leitura.casas
    assert lido.meta["arquivo_nome"] == "ideb.zip" and lido.meta["modo"] == "pacote_cli"
    assert lido.meta["url_origem"] == "https://exemplo.invalido/ideb_sintetico.zip"
    assert lido.meta["pacote_sha256"] == hashlib.sha256(preparo.pacote).hexdigest()
    # o aviso que só o preparo vê (escola de outra rede no município) volta do manifesto
    assert any("outra rede" in a for a in lido.avisos_preparo)


def _mexido(dados: bytes, *, csv_fn=None, manifesto_fn=None, extra=None,
            recalcular=False) -> bytes:
    arquivos = _arquivos(dados)
    m = json.loads(arquivos[pacote.NOME_MANIFESTO])
    if csv_fn:
        arquivos[pacote_ideb.NOME_CSV] = csv_fn(arquivos[pacote_ideb.NOME_CSV])
        if recalcular:
            m["entrada"]["csv_sha256"] = hashlib.sha256(arquivos[pacote_ideb.NOME_CSV]).hexdigest()
    if manifesto_fn:
        manifesto_fn(m)
    arquivos[pacote.NOME_MANIFESTO] = json.dumps(m).encode()
    arquivos.update(extra or {})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for nome, conteudo in arquivos.items():
            z.writestr(nome, conteudo)
    return buf.getvalue()


def _linha_estadual(recorte: bytes) -> bytes:
    """Acrescenta ao recorte a linha da escola ESTADUAL do município (fora da rede)."""
    linhas = list(csv.reader(io.StringIO(recorte.decode("utf-8"), newline=""), delimiter=";"))
    i = next(k for k, ln in enumerate(linhas) if len(ln) > 3 and ln[3] == "35990101")
    nova = list(linhas[i])
    nova[3], nova[5] = "35990104", "Estadual"
    linhas.insert(i + 1, nova)
    buf = io.StringIO()
    csv.writer(buf, delimiter=";", lineterminator="\n").writerows(linhas)
    return buf.getvalue().encode("utf-8")


def _so_identificacao(recorte: bytes) -> bytes:
    """O recorte só com as 6 colunas de identificação (nenhuma de valor)."""
    linhas = csv.reader(io.StringIO(recorte.decode("utf-8"), newline=""), delimiter=";")
    buf = io.StringIO()
    csv.writer(buf, delimiter=";", lineterminator="\n").writerows(ln[:6] for ln in linhas)
    return buf.getvalue().encode("utf-8")


def _campo_gigante(recorte: bytes) -> bytes:
    """Um campo acima do limite do módulo csv (131072 caracteres): ``csv.Error``."""
    return recorte + b"x" * 140_000 + b"\n"


# O manifesto confere a INTEGRIDADE, não a autoria: com o csv_sha256 recalculado, o
# pacote adulterado chega ao parser — e tem de ser RECUSADO (400), nunca virar 500.
@pytest.mark.parametrize("mexer, trecho", [
    (dict(csv_fn=_so_identificacao, recalcular=True), "nenhuma edição do Ideb"),
    (dict(csv_fn=_campo_gigante, recalcular=True), "está malformado"),
    (dict(csv_fn=lambda b: b.replace(b"131.47", b"139.47")), "sha256 diferente"),
    (dict(csv_fn=_linha_estadual, recalcular=True), "de fora da rede municipal"),
    (dict(csv_fn=lambda b: b.replace(b"131.47", b"139.47"), recalcular=True,
          manifesto_fn=lambda m: m.update(edicoes=[2019, 2023])), "não são as do manifesto"),
    (dict(manifesto_fn=lambda m: m.update(parser_versao="0")), "versão '0' do parser"),
    (dict(manifesto_fn=lambda m: m.update(codigo_territorio_alvo=OUTRO_MUN)),
     f"recortado para o município {OUTRO_MUN}"),
    (dict(extra={"outro.csv": b"x"}), "não declara"),
])
def test_pacote_adulterado_e_recusado(tmp_path, mexer, trecho):
    preparo = _preparar(tmp_path)
    with pytest.raises(ImportacaoRecusada, match=trecho):
        pacote_ideb.ler_pacote(_mexido(preparo.pacote, **mexer), "p.zip", codigo_ibge=MUN)


def _zip_que_mente(nome: str, inflado: int = 48 * 1024 * 1024, declarado: int = 100) -> bytes:
    """Um zip de UMA entrada que DECLARA ``declarado`` bytes (no diretório central e no
    cabeçalho local) mas cujo deflate infla ``inflado`` bytes de zeros: a zip bomb que
    passa pela conferência de ``file_size``. Montado à mão (o zipfile não escreve isso)."""
    comp = zlib.compressobj(9, zlib.DEFLATED, -15)
    bloco = b"\0" * (1024 * 1024)
    dados = b"".join(comp.compress(bloco) for _ in range(inflado // len(bloco))) + comp.flush()
    nome_b = nome.encode()
    local = struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0, 8, 0, 0, 0, len(dados), declarado,
                        len(nome_b), 0) + nome_b
    central = struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 20, 20, 0, 8, 0, 0, 0, len(dados),
                          declarado, len(nome_b), 0, 0, 0, 0, 0, 0) + nome_b
    fim = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, 1, 1, len(central),
                      len(local) + len(dados), 0)
    return local + dados + central + fim


@pytest.mark.parametrize("nome, ler", [
    (pacote.NOME_MANIFESTO, lambda c: pacote_ideb.ler_pacote(c, "p.zip", codigo_ibge=MUN)),
    (pacote.NOME_MANIFESTO, lambda c: pacote_saeb.ler_pacote(c, "p.zip", codigo_ibge=MUN)),
    (pacote.NOME_MANIFESTO, lambda c: pacote.ler_pacote(c, "p.zip", codigo_ibge=MUN)),
    ("docProps/core.xml", lambda c: ica.data_interna(c)),
], ids=["ideb", "saeb", "aeeb", "core_xml"])
def test_zip_que_mente_o_tamanho_nao_infla_na_memoria(nome, ler):
    """O tamanho DECLARADO no zip não limita a memória (``z.read`` infla o fluxo todo
    antes de cortar): a leitura descomprime no máximo o teto e recusa (CRC) sem inflar
    os 48 MB — antes, o pico passava do tamanho inflado."""
    conteudo = _zip_que_mente(nome)
    tracemalloc.start()
    try:
        if nome == pacote.NOME_MANIFESTO:
            assert pacote_ideb.parser_do_pacote(conteudo) is None
            with pytest.raises(ImportacaoRecusada):
                ler(conteudo)
        else:
            assert ler(conteudo) is None                     # sem data, nunca 500
        _, pico = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert pico < 16 * 1024 * 1024, pico


# =============================================================================
# Pipeline: prévia → aplicação → reaplicação → desfazer
# =============================================================================

@pytest.fixture()
def rede(db):
    r = Rede(nome="Rede Sintética do Ideb", uf="SP", codigo_ibge=MUN, status="ativa")
    vizinha = Rede(nome="Rede Vizinha Fictícia", uf="SP", codigo_ibge=OUTRO_MUN, status="ativa")
    db.add_all([r, vizinha])
    db.flush()
    db.add_all([
        Escola(nome="EMEF Sintética Alfa", ano_letivo_ativo=2026, rede_id=r.id,
               codigo_inep="35990101"),
        Escola(nome="EMEF Sintética Beta", ano_letivo_ativo=2026, rede_id=r.id,
               codigo_inep="35990102"),
        Escola(nome="EMEF Sintética Delta", ano_letivo_ativo=2026, rede_id=r.id,
               codigo_inep="35990105"),
        Escola(nome="EMEF Sintética Zeta", ano_letivo_ativo=2026, rede_id=r.id,
               codigo_inep="35990106"),
        Escola(nome="EMEF SINTETICA GAMA", ano_letivo_ativo=2026, rede_id=r.id),   # sem INEP
        # o homônimo da ALFA, com o INEP dele, noutra rede: não entra nesta
        Escola(nome="EMEF SINTETICA ALFA", ano_letivo_ativo=2026, rede_id=vizinha.id,
               codigo_inep="35980101"),
    ])
    db.commit()
    return r


@pytest.fixture()
def pacote_2023(tmp_path) -> bytes:
    return _preparar(tmp_path).pacote


def _escola_id(db, inep) -> int:
    return db.execute(select(Escola.id).where(Escola.codigo_inep == inep)).scalar_one()


def _estado(db) -> tuple:
    db.expire_all()
    res = sorted((r.id, r.avaliacao_id, r.edicao, r.indicador, r.escola_id, r.etapa,
                  r.componente, r.turma, r.valor, r.motivo_ausencia, r.unidade, r.fonte,
                  r.importacao_id, r.codigo_inep, r.rede_id)
                 for r in db.execute(select(ResultadoAvaliacao)).scalars())
    ref = sorted((r.avaliacao_id, r.edicao, r.indicador, r.abrangencia, r.codigo_territorio,
                  r.codigo_inep, r.rede_ensino, r.etapa, r.componente, r.valor,
                  r.casas_decimais, r.motivo_ausencia, r.unidade, r.importacao_id,
                  r.created_at, r.updated_at)
                 for r in db.execute(select(IndicadorReferencia)).scalars())
    return res, ref


def _aplicar(db, rede, conteudo, nome="pacote.zip", **kw):
    p = pipeline_ideb.previa(db, rede, conteudo, nome, usuario_id=None)
    db.commit()
    a = pipeline_ideb.aplicar(db, rede, p["id"], conteudo, nome, usuario_id=None, **kw)
    db.commit()
    return p, a


def _manuais_2023(db, rede, *, ideb_alfa=1.7, mt_alfa=135.18, lp_alfa=129.94):
    """Os números de 2023 gravados pelo botão de 1 clique (SEM importacao_id), como na
    produção — iguais ao arquivo por padrão. INVENTADOS."""
    ideb_av, saeb_av = svc.obter_avaliacao(db, "ideb"), svc.obter_avaliacao(db, "saeb")
    alfa = _escola_id(db, "35990101")
    fonte = "IDEB 2023 — arquivo_sintetico.zip"
    db.add_all([
        ResultadoAvaliacao(avaliacao_id=ideb_av.id, edicao=2023, rede_id=rede.id, escola_id=alfa,
                           codigo_inep="35990101", etapa="anos_iniciais", componente=None,
                           indicador="ideb", valor=ideb_alfa, unidade="indice", fonte=fonte),
        ResultadoAvaliacao(avaliacao_id=saeb_av.id, edicao=2023, rede_id=rede.id, escola_id=alfa,
                           codigo_inep="35990101", etapa="5_ano", componente="matematica",
                           indicador="proficiencia", valor=mt_alfa, unidade="escala_saeb",
                           fonte=fonte.replace("IDEB", "SAEB")),
        ResultadoAvaliacao(avaliacao_id=saeb_av.id, edicao=2023, rede_id=rede.id, escola_id=alfa,
                           codigo_inep="35990101", etapa="5_ano", componente="portugues",
                           indicador="proficiencia", valor=lp_alfa, unidade="escala_saeb",
                           fonte=fonte.replace("IDEB", "SAEB")),
    ])
    db.commit()


def test_previa_nao_grava_aplicar_reaplicar_e_desfazer_exato(db, rede, pacote_2023):
    antes = _estado(db)
    p = pipeline_ideb.previa(db, rede, pacote_2023, "pacote.zip", usuario_id=None)
    db.commit()
    assert _estado(db) == antes                                     # prévia não grava
    imp = db.get(ImportacaoIndicador, p["id"])
    assert imp.status == "previa" and imp.parser == ideb.PARSER and imp.modo == "pacote_cli"
    assert imp.pacote_sha256 == hashlib.sha256(pacote_2023).hexdigest()
    assert imp.arquivo_nome == "ideb.zip" and imp.edicao_arquivo == 2023
    assert imp.arquivo_data == datetime(2031, 6, 2, 8, 15)
    assert imp.url_origem == "https://exemplo.invalido/ideb_sintetico.zip"
    assert "Inep" in imp.citacao and "CC BY-ND" in imp.licenca
    c = p["contadores"]
    assert (c["novas"], c["ausentes"], c["escolas_casadas"], c["fora_do_cadastro"]) == (70, 16, 2, 1)
    assert p["edicoes"] == [2019, 2021, 2023] and p["anos_meta"] == [2019, 2021]
    assert [d["codigo_inep"] for d in p["sem_linha_no_arquivo"]] == ["35990105", "35990106"]
    assert p["pacote"]["entrada"]["md5_publicado"] == "confere"
    assert any(a.startswith("No preparo:") and "outra rede" in a for a in p["avisos"])
    a = pipeline_ideb.aplicar(db, rede, p["id"], pacote_2023, "outro_nome.zip", usuario_id=None)
    db.commit()
    assert a["status"] == "aplicada"
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 18
    assert db.scalar(select(func.count(IndicadorReferencia.id))) == 52
    alfa = _escola_id(db, "35990101")
    linha = db.execute(select(ResultadoAvaliacao).where(
        ResultadoAvaliacao.escola_id == alfa, ResultadoAvaliacao.edicao == 2019,
        ResultadoAvaliacao.componente == "matematica")).scalar_one()
    assert (linha.valor, linha.etapa, linha.unidade) == (131.47, "5_ano", "escala_saeb")
    assert linha.fonte == "Ideb/Saeb oficial (INEP, divulgação 2023) — ideb.zip"
    assert linha.importacao_id == a["id"]
    depois = _estado(db)
    _, de_novo = _aplicar(db, rede, pacote_2023)
    assert de_novo["contadores"]["iguais"] == 70 and de_novo["contadores"]["novas"] == 0
    assert _estado(db) == depois                                    # idempotente
    lista = pipeline_ideb.listar(db, rede)
    assert [i["status"] for i in lista][:2] == ["aplicada", "aplicada"]
    assert lista[1]["pode_desfazer"] is False and lista[1]["bloqueada_por"] == lista[0]["id"]
    pipeline_ideb.desfazer(db, rede, lista[0]["id"], usuario_id=None)
    db.commit()
    assert _estado(db) == depois                    # a reaplicação não tinha mudado nada
    pipeline_ideb.desfazer(db, rede, a["id"], usuario_id=None)
    db.commit()
    assert _estado(db) == antes                                     # exato


def test_plano_de_desfazer_fica_fora_do_resumo_e_das_consultas(db, rede, pacote_2023):
    """O plano de desfazer (uma entrada por número: MB no Ideb de uma rede inteira) fica
    na coluna ``desfazer`` (deferred), não no ``resumo``: o GET do Ideb não o lê nem o
    decodifica, e o desfazer busca as linhas num SELECT por tabela — não um por número."""
    antes = _estado(db)
    _, a = _aplicar(db, rede, pacote_2023)
    imp = db.get(ImportacaoIndicador, a["id"])
    assert "desfazer" not in imp.resumo
    assert len(imp.desfazer["criadas"]) == 70 and len(imp.desfazer["chaves"]) == 70
    assert {"5_ano", "anos_iniciais"} <= set(imp.resumo["etapas_vistas"])
    comandos: list[str] = []

    def _ouvir(conn, cursor, statement, params, context, executemany):
        comandos.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", _ouvir)
    try:
        db.expire_all()
        consulta_ideb.ideb_da_rede(db, db.get(Rede, rede.id))
        assert comandos and not [c for c in comandos if "importacoes_indicador.desfazer" in c]
        comandos.clear()
        db.expire_all()
        pipeline_ideb.desfazer(db, rede, a["id"], usuario_id=None)
        selects = [c for c in comandos if c.lstrip().upper().startswith("SELECT")]
        assert len(selects) <= 10, len(selects)      # antes: um SELECT por número (70+)
    finally:
        event.remove(engine, "before_cursor_execute", _ouvir)
    db.commit()
    assert _estado(db) == antes                                     # exato


def test_lista_le_os_planos_de_desfazer_num_select_so(db, rede, pacote_2023):
    """A coluna ``desfazer`` é deferred: a lista confere o conflito de cada aplicada
    contra as posteriores (de qualquer rede) e precisa dos planos delas — num SELECT só,
    não um por importação (antes da coluna eles vinham no ``resumo``, na mesma consulta)."""
    ids = [_aplicar(db, rede, pacote_2023)[1]["id"] for _ in range(4)]   # 1 nova + 3 iguais
    comandos: list[str] = []

    def _ouvir(conn, cursor, statement, params, context, executemany):
        comandos.append(statement)

    engine = db.get_bind()
    db.expire_all()
    event.listen(engine, "before_cursor_execute", _ouvir)
    try:
        lista = pipeline_ideb.listar(db, rede)
    finally:
        event.remove(engine, "before_cursor_execute", _ouvir)
    assert {i["id"] for i in lista if i["status"] == "aplicada"} >= set(ids)
    planos = [c for c in comandos if "importacoes_indicador.desfazer" in c]
    assert len(planos) == 1, len(planos)                  # antes: 4 (um por importação)


def test_importacao_com_o_plano_no_formato_antigo_ainda_desfaz_exato(db, rede, pacote_2023):
    """Plano no formato antigo (``resumo['desfazer']``) com a coluna ``desfazer`` NULA — o
    estado do banco local anterior à coluna DEPOIS do reparo da 0034 (a coluna criada; a
    coluna AUSENTE está no teste seguinte): a lista e o desfazer leem o plano do resumo —
    antes, a importação virava 'desfeita' com 0 desfeitas e os números ficavam."""
    antes = _estado(db)
    _, a = _aplicar(db, rede, pacote_2023)
    imp = db.get(ImportacaoIndicador, a["id"])
    imp.resumo = {**imp.resumo, "desfazer": imp.desfazer}
    imp.desfazer = None
    db.commit()
    db.expire_all()
    assert [i["pode_desfazer"] for i in pipeline_ideb.listar(db, rede)] == [True]
    saida = pipeline_ideb.desfazer(db, rede, a["id"], usuario_id=None)
    db.commit()
    assert saida["status"] == "desfeita" and saida["contadores"]["desfeitas"] == 70
    assert _estado(db) == antes                                     # exato


def test_banco_sem_a_coluna_desfazer_volta_a_desfazer_com_o_reparo_da_0034(db, rede, pacote_2023):
    """Banco local que aplicou a 0034 antes da coluna ``desfazer`` existir: a coluna
    AUSENTE (o plano em ``resumo['desfazer']``). O app não lista nem desfaz (o modelo
    mapeia a coluna) — por isso a 0034 documenta o reparo, e a recusa do downgrade da
    0035 o repete: criar a coluna. Criada (nula), a lista e o desfazer voltam, exatos."""
    antes = _estado(db)
    _, a = _aplicar(db, rede, pacote_2023)
    imp = db.get(ImportacaoIndicador, a["id"])
    imp.resumo = {**imp.resumo, "desfazer": imp.desfazer}
    db.commit()
    db.execute(text("ALTER TABLE importacoes_indicador DROP COLUMN desfazer"))
    db.commit()
    db.expire_all()
    with pytest.raises(OperationalError, match="importacoes_indicador.desfazer"):
        pipeline_ideb.listar(db, rede)
    db.rollback()
    db.execute(text("ALTER TABLE importacoes_indicador ADD COLUMN desfazer JSON"))  # o reparo
    db.commit()
    db.expire_all()
    assert [i["pode_desfazer"] for i in pipeline_ideb.listar(db, rede)] == [True]
    saida = pipeline_ideb.desfazer(db, rede, a["id"], usuario_id=None)
    db.commit()
    assert saida["status"] == "desfeita" and saida["contadores"]["desfeitas"] == 70
    assert _estado(db) == antes                                     # exato


def test_aplicada_sem_plano_de_desfazer_recusa_em_vez_de_virar_desfeita(db, rede, pacote_2023):
    """Sem plano (nem na coluna, nem no ``resumo``): recusa, sem tocar em nada, e a
    lista não oferece o desfazer."""
    _, a = _aplicar(db, rede, pacote_2023)
    imp = db.get(ImportacaoIndicador, a["id"])
    imp.desfazer = None
    db.commit()
    depois = _estado(db)
    assert [i["pode_desfazer"] for i in pipeline_ideb.listar(db, rede)] == [False]
    with pytest.raises(ImportacaoRecusada, match="plano de desfazer"):
        pipeline_ideb.desfazer(db, rede, a["id"], usuario_id=None)
    db.rollback()
    assert db.get(ImportacaoIndicador, a["id"]).status == "aplicada"
    assert _estado(db) == depois


def test_numeros_de_2023_ja_gravados_e_iguais_ficam_identicos(db, rede, pacote_2023):
    """O critério da E6: reimportar 2023 sobre o que o 1 clique gravou não cria linha
    nova COM VALOR em 2023 — só as ausências do arquivo — e não toca nas antigas."""
    _manuais_2023(db, rede)
    antigas = {r.id: (r.valor, r.fonte, r.importacao_id, r.unidade, r.etapa, r.componente)
               for r in db.execute(select(ResultadoAvaliacao)).scalars()}
    p, a = _aplicar(db, rede, pacote_2023)
    assert p["substituicoes"] == [] and a["contadores"]["iguais_sem_proveniencia"] == 3
    db.expire_all()
    for r in db.execute(select(ResultadoAvaliacao)).scalars():
        if r.id in antigas:
            assert antigas[r.id] == (r.valor, r.fonte, r.importacao_id, r.unidade, r.etapa,
                                     r.componente)
    novas_2023 = db.execute(select(ResultadoAvaliacao).where(
        ResultadoAvaliacao.edicao == 2023,
        ResultadoAvaliacao.id.notin_(list(antigas)))).scalars().all()
    assert novas_2023 and all(r.valor is None and r.motivo_ausencia == "nao_divulgado"
                              for r in novas_2023)               # só a BETA ("-")
    assert {r.codigo_inep for r in novas_2023} == {"35990102"}
    pipeline_ideb.desfazer(db, rede, a["id"], usuario_id=None)
    db.commit()
    assert {r.id for r in db.execute(select(ResultadoAvaliacao)).scalars()} == set(antigas)


def test_numero_sem_proveniencia_diferente_exige_resposta_explicita(db, rede, pacote_2023):
    _manuais_2023(db, rede, mt_alfa=134.81)
    p = pipeline_ideb.previa(db, rede, pacote_2023, "pacote.zip", usuario_id=None)
    db.commit()
    assert [(s["componente"], s["antes"]["valor"], s["depois"]["valor"])
            for s in p["substituicoes"]] == [("matematica", 134.81, 135.18)]
    with pytest.raises(ImportacaoRecusada, match="explicitamente"):
        pipeline_ideb.aplicar(db, rede, p["id"], pacote_2023, "pacote.zip", usuario_id=None)
    db.rollback()
    a = pipeline_ideb.aplicar(db, rede, p["id"], pacote_2023, "pacote.zip", usuario_id=None,
                              substituir_calculadas=False)
    db.commit()
    assert a["contadores"]["substituicoes_mantidas"] == 1
    mt = db.execute(select(ResultadoAvaliacao).where(
        ResultadoAvaliacao.edicao == 2023, ResultadoAvaliacao.componente == "matematica",
        ResultadoAvaliacao.codigo_inep == "35990101")).scalar_one()
    assert mt.valor == 134.81 and mt.importacao_id is None


def test_aplicar_exige_o_mesmo_pacote_e_uma_vez_so(db, rede, tmp_path, pacote_2023):
    p = pipeline_ideb.previa(db, rede, pacote_2023, "pacote.zip", usuario_id=None)
    db.commit()
    outro = _preparar(tmp_path, nome="outro.zip").pacote
    with pytest.raises(ImportacaoRecusada, match="não é o mesmo da prévia"):
        pipeline_ideb.aplicar(db, rede, p["id"], outro, "pacote.zip", usuario_id=None)
    db.rollback()
    pipeline_ideb.aplicar(db, rede, p["id"], pacote_2023, "pacote.zip", usuario_id=None)
    db.commit()
    with pytest.raises(ImportacaoRecusada, match="já foi aplicada"):
        pipeline_ideb.aplicar(db, rede, p["id"], pacote_2023, "pacote.zip", usuario_id=None)


def test_arquivo_de_edicao_mais_antiga_nao_sobrescreve_a_mais_nova(db, rede, tmp_path,
                                                                  pacote_2023):
    _, novo = _aplicar(db, rede, pacote_2023)
    alfa = {**ALFA, "valores": {**ALFA["valores"], "VL_OBSERVADO_2019": 1.4}}
    antigo = _preparar(tmp_path, xlsx=planilha([alfa, BETA], edicoes=(2019, 2021)),
                       nome="divulgacao_anos_iniciais_escolas_2021.zip").pacote
    p, a = _aplicar(db, rede, antigo)
    assert p["edicao_arquivo"] == 2021 and a["contadores"]["mantidas"] >= 1
    db.expire_all()
    ideb_2019 = db.execute(select(ResultadoAvaliacao).where(
        ResultadoAvaliacao.edicao == 2019, ResultadoAvaliacao.indicador == "ideb",
        ResultadoAvaliacao.codigo_inep == "35990101")).scalar_one()
    assert ideb_2019.valor == 1.5 and ideb_2019.importacao_id == novo["id"]


DATA_RETIFICADA = (2031, 9, 1, 10, 0, 0)      # data INVENTADA (a "versão retificada")


def _ideb_alfa_2019(db) -> ResultadoAvaliacao:
    db.expire_all()
    return db.execute(select(ResultadoAvaliacao).where(
        ResultadoAvaliacao.edicao == 2019, ResultadoAvaliacao.indicador == "ideb",
        ResultadoAvaliacao.codigo_inep == "35990101")).scalar_one()


def test_retificacao_da_mesma_edicao_nao_e_desfeita_pelo_pacote_anterior(db, rede, tmp_path):
    """Plano 4.3/4.5: vale o arquivo mais recente. O INEP retifica com o MESMO nome de
    zip; na mesma edição desempata a data interna da planilha (como no ICA): o pacote
    da versão anterior fica ``mantida``, com aviso — em qualquer ordem."""
    nome = "divulgacao_anos_iniciais_escolas_2023.zip"
    alfa_v2 = {**ALFA, "valores": {**ALFA["valores"], "VL_OBSERVADO_2019": 1.9}}
    retificado = _preparar(tmp_path, xlsx=planilha([alfa_v2, BETA]), nome=nome,
                           data=DATA_RETIFICADA).pacote
    anterior = _preparar(tmp_path, xlsx=planilha([ALFA, BETA]), nome=nome).pacote
    _, a2 = _aplicar(db, rede, retificado)
    p1, a1 = _aplicar(db, rede, anterior)
    c = p1["contadores"]
    assert (c["novas"], c["alteradas"], c["iguais"]) == (0, 0, 0)
    assert c["mantidas"] == c["recortadas"] > 0
    ideb_19 = next(m for m in p1["mudancas"] if m["indicador"] == "ideb" and m["edicao"] == 2019
                   and m["codigo_inep"] == "35990101")
    assert (ideb_19["tipo"], ideb_19["antes"], ideb_19["depois"]) == ("mantida", 1.9, 1.5)
    aviso = next(a for a in p1["avisos"] if a.startswith("Arquivo de data anterior"))
    assert "edição (2023)" in aviso and f"#{a2['id']}" in aviso and "01/09/2031" in aviso
    assert "02/06/2031" in aviso and "retificada" in aviso
    linha = _ideb_alfa_2019(db)
    assert (linha.valor, linha.importacao_id) == (1.9, a2["id"])      # retificação intacta
    # Pacote SEM data interna (manifesto sem ela): fica atrás do datado, também mantida.
    sem_data = _mexido(anterior, manifesto_fn=lambda m: m["entrada"].pop("data_interna"))
    p0 = pipeline_ideb.previa(db, rede, sem_data, "p.zip", usuario_id=None)
    db.rollback()
    assert p0["contadores"]["mantidas"] == p0["contadores"]["recortadas"]
    assert any("não tem data interna" in a for a in p0["avisos"])
    # A ordem inversa dá o MESMO valor final (a retificação vence).
    for imp_id in (a1["id"], a2["id"]):
        pipeline_ideb.desfazer(db, rede, imp_id, usuario_id=None)
        db.commit()
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 0
    _aplicar(db, rede, anterior)
    p2, b2 = _aplicar(db, rede, retificado)
    assert p2["contadores"]["alteradas"] >= 1 and p2["contadores"]["mantidas"] == 0
    assert not any(a.startswith("Arquivo de data anterior") for a in p2["avisos"])
    linha = _ideb_alfa_2019(db)
    assert (linha.valor, linha.importacao_id) == (1.9, b2["id"])


def test_desempate_por_data_so_na_familia_do_ideb():
    """O SARESP (upload sem data interna) segue só pela edição."""
    from types import SimpleNamespace as NS

    from app.services.indicadores import pipeline_seduc as ps

    novo = NS(edicao_arquivo=2023, arquivo_data=datetime(2031, 9, 1))
    velho = NS(edicao_arquivo=2023, arquivo_data=datetime(2031, 6, 2))
    sem = NS(edicao_arquivo=2023, arquivo_data=None)
    antes, depois, campos = {"valor": 1.9}, {"valor": 1.5}, ("valor",)
    assert ps._tipo(novo, velho, antes, depois, campos, por_data=True) == "mantida"
    assert ps._tipo(novo, sem, antes, depois, campos, por_data=True) == "mantida"
    assert ps._tipo(velho, novo, antes, depois, campos, por_data=True) == "alterada"
    assert ps._tipo(sem, novo, antes, depois, campos, por_data=True) == "alterada"
    assert ps._tipo(sem, sem, antes, depois, campos, por_data=True) == "alterada"
    assert ps._tipo(velho, velho, antes, depois, campos, por_data=True) == "alterada"
    assert ps._tipo(novo, velho, antes, antes, campos, por_data=True) == "mantida"
    assert ps._tipo(novo, velho, antes, depois, campos) == "alterada"     # sem desempate
    assert pipeline_ideb.FAMILIA.desempate_por_data and not ps.SEDUC.desempate_por_data


def test_nada_polui_opcoes_nem_correlacao(db, rede, pacote_2023):
    _aplicar(db, rede, pacote_2023)
    ops = svc.opcoes_rede(db, rede.id)
    series = {(o["avaliacao"], o["indicador"], o["etapa"], o["componente"]): o["edicoes"]
              for o in ops}
    assert set(series) == {("ideb", "ideb", "anos_iniciais", None),
                           ("saeb", "proficiencia", "5_ano", "matematica"),
                           ("saeb", "proficiencia", "5_ano", "portugues")}
    assert all(sorted(e) == [2019, 2021, 2023] for e in series.values())
    # só ausências numa edição: nem opção nem ponto
    db.execute(ResultadoAvaliacao.__table__.delete().where(
        ResultadoAvaliacao.codigo_inep == "35990101"))
    db.commit()
    ops = svc.opcoes_rede(db, rede.id)
    assert all(2023 not in o["edicoes"] for o in ops)
    corr = svc.correlacao_rede(db, rede.id, avaliacao_chave="ideb", indicador="ideb",
                               edicao=2023, etapa="anos_iniciais", componente=None)
    assert corr["pontos"] == []                                    # ausência ≠ zero
    assert [e["edicao"] for e in corr["evolucao"]] == [2019]       # só onde há número


def test_pacote_de_outra_rede_ou_rede_sem_ibge_e_recusado(db, rede, pacote_2023):
    vizinha = db.execute(select(Rede).where(Rede.codigo_ibge == OUTRO_MUN)).scalar_one()
    with pytest.raises(ImportacaoRecusada, match=f"recortado para o município {MUN}"):
        pipeline_ideb.previa(db, vizinha, pacote_2023, "pacote.zip", usuario_id=None)
    db.rollback()
    rede.codigo_ibge = None
    db.commit()
    with pytest.raises(ImportacaoRecusada, match="não tem o código IBGE"):
        pipeline_ideb.previa(db, rede, pacote_2023, "pacote.zip", usuario_id=None)


@pytest.mark.parametrize("conteudo, nome, trecho", [
    (planilha(), "divulgacao_anos_iniciais_escolas_2023.xlsx", "uma planilha"),
    (zip_ideb(planilha()), "divulgacao_anos_iniciais_escolas_2023.zip", "o zip do INEP inteiro"),
    (b"SG_UF;CO_MUNICIPIO\nSP;3599999\n", "x.csv", "Não reconheci"),
])
def test_o_que_nao_e_o_pacote_e_recusado_com_a_causa(db, rede, conteudo, nome, trecho):
    with pytest.raises(ImportacaoRecusada, match=trecho):
        pipeline_ideb.previa(db, rede, conteudo, nome, usuario_id=None)
    db.rollback()
    assert db.scalar(select(func.count(ImportacaoIndicador.id))) == 0


def test_pacote_do_ica_no_ideb_e_o_do_ideb_no_ica_sao_recusados(db, rede, pacote_2023):
    falso_ica = _mexido(pacote_2023, manifesto_fn=lambda m: m.update(parser="inep_aeeb_agregados"))
    with pytest.raises(ImportacaoRecusada, match="pacote dos microdados do ICA") as recusa:
        pipeline_ideb.previa(db, rede, falso_ica, "p.zip", usuario_id=None)
    db.rollback()
    # Em português e sem identificador interno: a tela mostra a recusa como veio.
    assert "aqui entra o pacote do Ideb (por escola, do município, da UF ou do Brasil)" in str(
        recusa.value)
    assert "inep_" not in str(recusa.value) and "parser" not in str(recusa.value)
    from app.services.indicadores import pipeline as pipeline_ica
    with pytest.raises(ImportacaoRecusada, match="inep_ideb_escolas"):
        pipeline_ica.previa(db, rede, pacote_2023, "p.zip", usuario_id=None)


def test_textos_de_proveniencia_cabem_nas_colunas():
    assert len(pipeline_ideb.FONTE_NOME) <= 120 and len(pipeline_ideb.CITACAO) <= 500
    assert len(pipeline_ideb.fonte_curta(2025) + " — " + "x" * 60) <= 200


# =============================================================================
# API: permissões, fluxo e auditoria
# =============================================================================

def _cliente(db, email: str, **campos) -> TestClient:
    db.add(Usuario(nome=email, email=email, senha_hash=hash_senha("s3nh4ideb1"), **campos))
    db.commit()
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", data={"username": email, "password": "s3nh4ideb1"})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _post(cliente, rede_id, rota, conteudo, nome="pacote.zip", **form):
    return cliente.post(f"/api/v1/redes/{rede_id}/indicadores/ideb/{rota}",
                        files={"arquivo": (nome, conteudo)}, data=form)


def test_api_permissoes_fluxo_e_auditoria(db, escola_completa, cliente_global, rede,
                                          pacote_2023):
    secretaria = _cliente(db, "sec@ideb.gov", cargo="coordenador", rede_id=rede.id)
    coordenador = _cliente(db, "coord@ideb.escola", cargo="coordenador",
                           escola_id=escola_completa["escola"].id)
    for quem in (secretaria, coordenador):
        assert _post(quem, rede.id, "previa", pacote_2023).status_code == 403
        assert quem.get(f"/api/v1/redes/{rede.id}/indicadores/ideb/importacoes").status_code == 403
    p = _post(cliente_global, rede.id, "previa", pacote_2023)
    assert p.status_code == 200, p.text
    assert p.json()["fora_do_cadastro"][0]["codigo_inep"] == "35990103"
    assert p.json()["pacote_sha256"] == hashlib.sha256(pacote_2023).hexdigest()
    ok = _post(cliente_global, rede.id, "aplicar", pacote_2023, previa_id=str(p.json()["id"]))
    assert ok.status_code == 200 and ok.json()["status"] == "aplicada"
    for quem in (secretaria, coordenador):
        assert quem.post(f"/api/v1/redes/{rede.id}/indicadores/ideb/importacoes/"
                         f"{ok.json()['id']}/desfazer").status_code == 403
    lista = cliente_global.get(f"/api/v1/redes/{rede.id}/indicadores/ideb/importacoes").json()
    assert lista[0]["id"] == ok.json()["id"] and lista[0]["pode_desfazer"] is True
    # cada fluxo lista só as suas importações
    saresp = cliente_global.get(f"/api/v1/redes/{rede.id}/indicadores/saresp/importacoes").json()
    assert ok.json()["id"] not in {i["id"] for i in saresp}
    desf = cliente_global.post(f"/api/v1/redes/{rede.id}/indicadores/ideb/importacoes/"
                               f"{ok.json()['id']}/desfazer")
    assert desf.status_code == 200 and desf.json()["status"] == "desfeita"
    db.expire_all()
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 0
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "indicador.importado")).scalar_one()
    assert log.detalhes["pacote_sha256"] == hashlib.sha256(pacote_2023).hexdigest()
    assert {"indicador.importado", "indicador.desfeito"} <= {
        a for (a,) in db.execute(select(LogAuditoria.acao))}


def test_api_recusas_limpas(db, escola_completa, cliente_global, rede, pacote_2023):
    cru = _post(cliente_global, rede.id, "previa", planilha(), "ideb.xlsx")
    assert cru.status_code == 400 and "preparar" in cru.json()["detail"]
    grande = _post(cliente_global, rede.id, "previa", b"PK" + b"0" * (6 * 1024 * 1024))
    assert grande.status_code == 413
    no_ica = cliente_global.post(f"/api/v1/redes/{rede.id}/indicadores/ica/previa",
                                 files={"arquivo": ("p.zip", pacote_2023)})
    assert no_ica.status_code == 400
    no_saresp = cliente_global.post(f"/api/v1/redes/{rede.id}/indicadores/saresp/previa",
                                    files={"arquivo": ("p.zip", pacote_2023)})
    assert no_saresp.status_code == 400
    # adulterado com o csv_sha256 recalculado: recusa 400 com a causa, não 500
    for mexer, trecho in ((_so_identificacao, "nenhuma edição do Ideb"),
                          (_campo_gigante, "está malformado")):
        r = _post(cliente_global, rede.id, "previa",
                  _mexido(pacote_2023, csv_fn=mexer, recalcular=True))
        assert r.status_code == 400 and trecho in r.json()["detail"], r.text
    assert db.scalar(select(func.count(ImportacaoIndicador.id))) == 0


# --- O mesmo fluxo num PostgreSQL de verdade ------------------------------------

from tests.test_migracoes_postgres import engine_postgres  # noqa: E402,F401 — fixture do PG de teste


@pytest.mark.postgres
def test_pipeline_ideb_no_postgres_aplica_reaplica_e_desfaz_exato(engine_postgres, tmp_path):
    from sqlalchemy.orm import sessionmaker

    from app.core.migracoes import aplicar_migracoes

    aplicar_migracoes(engine_postgres)
    db = sessionmaker(bind=engine_postgres)()
    try:
        r = Rede(nome="Rede Sintética PG", uf="SP", codigo_ibge=MUN, status="ativa")
        db.add(r)
        db.flush()
        db.add_all([Escola(nome="EMEF Sintética Alfa", ano_letivo_ativo=2026, rede_id=r.id,
                           codigo_inep="35990101"),
                    Escola(nome="EMEF Sintética Beta", ano_letivo_ativo=2026, rede_id=r.id,
                           codigo_inep="35990102")])
        db.commit()
        _manuais_2023(db, r)
        antes = _estado(db)
        dados = _preparar(tmp_path).pacote
        _, a = _aplicar(db, r, dados)
        assert a["contadores"]["iguais_sem_proveniencia"] == 3
        assert db.scalar(select(func.count(ResultadoAvaliacao.id)).where(
            ResultadoAvaliacao.valor.is_(None))) == 6                 # ausências no PG
        depois = _estado(db)
        _, b = _aplicar(db, r, dados)
        assert b["contadores"]["novas"] == 0 and _estado(db) == depois
        for item in pipeline_ideb.listar(db, r):                    # desfaz tudo, do fim
            if item["status"] == "aplicada":
                pipeline_ideb.desfazer(db, r, item["id"], usuario_id=None)
                db.commit()
        assert _estado(db) == antes
    finally:
        db.close()
