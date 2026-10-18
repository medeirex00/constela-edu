"""ICA completo (etapa E3): microdados AGREGADOS do INEP (TS_MUNICIPIO/TS_ESTADO).

* parser ``inep_aeeb_agregados`` — colunas pelo nome, Latin-1 com ``;``, níveis
  presentes (2024+) e ausentes (2023), só a rede municipal do município e as redes
  municipal e pública da UF, recusa de arquivo de ALUNO;
* leitor de zip por faixa (arquivo local e HTTP Range SUBSTITUÍDO), ZIP64, CRC32
  conferido, TS_ALUNO nunca lido;
* linha de comando ``preparar`` → pacote recortado; o servidor refaz a validação
  e recusa pacote adulterado, cifrado ou com tabela vazia; município sem a rede
  municipal: o pacote vai só com o TS_ESTADO (nenhuma tabela útil = recusa);
* precedência: o decimal dos microdados vira DETALHE da capa da planilha, em
  qualquer ordem — valor E fonte; com as mesmas casas, o detalhe é o da planilha;
  o que só os microdados trazem (média de LP, níveis, UF nas redes municipais) é
  capa;
* desfazer pelo id, com conflito; API.

TUDO SINTÉTICO no layout real: nenhum número, data, nome ou linha do INEP aqui (o
repositório é público e os arquivos oficiais têm licença CC BY-ND — D13). Os
números são INVENTADOS (não são os oficiais com o inteiro trocado): só guardam as
propriedades que os testes conferem — 5 casas no TS_MUNICIPIO e 2 no TS_ESTADO,
níveis que somam 100, decimais que arredondam para as capas das planilhas
sintéticas de ``test_indicadores_ica`` (30 no município, 34 na UF pública, com
33,50 = meio exato que arredonda para cima), longe dos números oficiais. Nenhum
teste sai para a internet: o "servidor" do INEP é uma função que responde com os
bytes de um zip montado em memória.
"""
import functools
import hashlib
import io
import itertools
import json
import re
import struct
import zipfile
from datetime import datetime

import httpx
import pytest
from sqlalchemy import func, select

from app.models import ImportacaoIndicador, IndicadorReferencia, LogAuditoria, Rede
from app.services import avaliacoes as svc
from app.services.avaliacoes import ImportacaoRecusada
from app.services.indicadores import aeeb, consulta, pacote, pipeline, preparar, zip_parcial
from app.services.indicadores.zip_parcial import RespostaFaixa
from tests.test_indicadores_ica import (MUN, NOME_MUN, OUTRO, _cliente, _estado, _upload,
                                        _valores, arq_mun_2024, arq_mun_2025, arq_ufs_2025)

NIVEIS = [f"PC_ALUNO_NIVEL_{k}_LP" for k in range(9)]
COLS_MUN = ["NU_ANO_AVALIACAO", "CO_UF", "SG_UF", "CO_MUNICIPIO", "NO_MUNICIPIO", "TP_SERIE",
            "ID_TIPO_REDE", "PC_ALUNO_ALFABETIZADO", "VL_MEDIA_LP", *NIVEIS]
COLS_MUN_2023 = COLS_MUN[:9]
COLS_EST = ["NU_ANO_AVALIACAO", "CO_UF", "SG_UF", "TP_SERIE", "ID_TIPO_REDE",
            "PC_ALUNO_ALFABETIZADO", "VL_MEDIA_LP", *NIVEIS]
COLS_EST_2023 = COLS_EST[:7]
URL = "https://download.inep.gov.br/dados_abertos/microdados_sintetico_2025.zip"
DATA_ENTRADA = (2026, 3, 10, 10, 0, 0)        # data interna SINTÉTICA das entradas
LAST_MODIFIED = "Tue, 10 Mar 2026 13:00:00 GMT"

# Níveis INVENTADOS (somam 100): no município com 5 casas, na UF com 2, como no
# layout real. Nenhum vem dos arquivos do INEP.
_NIV_MUN_25 = ["7.34000", "9.72000", "13.22000", "16.06000", "20.76000", "15.76000",
               "11.20000", "5.05000", "0.89000"]
_NIV_MUN_24 = ["9.04000", "10.42000", "14.87000", "16.93000", "19.46000", "13.62000",
               "9.45000", "4.22000", "1.99000"]
_NIV_UF_25 = ["7.04", "8.76", "12.62", "18.00", "19.91", "16.58", "10.92", "4.45", "1.72"]


def _linha(colunas, **valores) -> dict:
    return {c: valores.get(c, "") for c in colunas}


def _mun(ano, codigo=MUN, nome=NOME_MUN, rede="3", pc="30.20", media="726.48170",
         niveis=None, serie="2", colunas=COLS_MUN) -> dict:
    v = {"NU_ANO_AVALIACAO": ano, "CO_UF": codigo[:2], "SG_UF": "SP", "CO_MUNICIPIO": codigo,
         "NO_MUNICIPIO": nome, "TP_SERIE": serie, "ID_TIPO_REDE": rede,
         "PC_ALUNO_ALFABETIZADO": pc, "VL_MEDIA_LP": media}
    if "PC_ALUNO_NIVEL_0_LP" in colunas:
        v.update(zip(NIVEIS, niveis or _NIV_MUN_25))
    return _linha(colunas, **v)


def _uf(ano, uf="35", rede="3", pc="31.57", media="728.9135", niveis=None,
        colunas=COLS_EST) -> dict:
    v = {"NU_ANO_AVALIACAO": ano, "CO_UF": uf, "SG_UF": "SP" if uf == "35" else "AC",
         "TP_SERIE": "2", "ID_TIPO_REDE": rede, "PC_ALUNO_ALFABETIZADO": pc,
         "VL_MEDIA_LP": media}
    if "PC_ALUNO_NIVEL_0_LP" in colunas:
        v.update(zip(NIVEIS, niveis or _NIV_UF_25))
    return _linha(colunas, **v)


def _csv(colunas, linhas, *, codificacao="latin-1") -> bytes:
    texto = ";".join(colunas) + "\n"
    texto += "".join(";".join(str(ln[c]) for c in colunas) + "\n" for ln in linhas)
    return texto.encode(codificacao)


def ts_municipio(ano=2025) -> bytes:
    if ano == 2023:
        return _csv(COLS_MUN_2023, [
            _mun(2023, pc="26.18", media="719.8642", colunas=COLS_MUN_2023),
            _mun(2023, OUTRO, "Vizinho Sintético", pc="89.35", media="791.4", colunas=COLS_MUN_2023),
        ])
    niveis = _NIV_MUN_25 if ano == 2025 else _NIV_MUN_24
    # 30,20 → capa 30 e 21,84 → capa 22 das planilhas sintéticas (test_indicadores_ica)
    pc, media = ("30.20", "726.48170") if ano == 2025 else ("21.84", "721.27460")
    return _csv(COLS_MUN, [
        _mun(ano, OUTRO, "Vizinho Sintético", pc="91.40", media="793.60410"),
        _mun(ano, pc=pc, media=media, niveis=niveis),
        _mun(ano, rede="5", pc=pc, media=media, niveis=niveis),    # pública: ignorada
    ])


def ts_estado(ano=2025) -> bytes:
    if ano == 2023:
        return _csv(COLS_EST_2023, [
            _uf(2023, rede="3", pc="19.73", media="712.6604", colunas=COLS_EST_2023),
            _uf(2023, rede="5", pc="18.3", media="716.952", colunas=COLS_EST_2023),
        ])
    return _csv(COLS_EST, [
        _uf(ano, uf="12", rede="3", pc="16.00"),
        _uf(ano, rede="3"),                                         # SP redes municipais
        _uf(ano, rede="2", pc="38.00", media="794.0"),               # estadual: ignorada
        # pública: 33,50 é o meio exato que arredonda (para cima) para a capa 34
        _uf(ano, rede="5", pc="33.50", media="722.5817"),
        _uf(ano, rede="0", pc="36.00", media="795.0"),               # total: ignorada
    ])


def ts_aluno() -> bytes:
    """Tabela de alunos SINTÉTICA (só para provar que nunca é lida)."""
    cab = "NU_ANO_AVALIACAO;CO_UF;CO_MUNICIPIO;ID_ESCOLA;ID_ALUNO;VL_PROFICIENCIA_LP\n"
    return (cab + "".join(f"2025;35;{MUN};{i % 50};{i};{700 + i % 90}.5\n"
                          for i in range(20_000))).encode("latin-1")


def zip_microdados(ano=2025, *, com_aluno=True, metodo=zipfile.ZIP_DEFLATED,
                   sem_estado=False, extra: dict | None = None) -> bytes:
    """O zip SINTÉTICO no desenho do INEP: TS_ALUNO (grande, 1º), TS_MUNICIPIO,
    TS_ESTADO e um INPUT de dicionário."""
    entradas = {}
    if com_aluno:
        entradas["DADOS/TS_ALUNO.csv"] = ts_aluno()
    entradas["DADOS/TS_MUNICIPIO.csv"] = ts_municipio(ano)
    if not sem_estado:
        entradas["DADOS/TS_ESTADO.csv"] = ts_estado(ano)
    entradas[f"INPUTS/INPUT_R_TS_MUNICIPIO_{ano}.R"] = b"# dicionario sintetico\n"
    entradas.update(extra or {})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for nome, dados in entradas.items():
            info = zipfile.ZipInfo(nome, date_time=DATA_ENTRADA)
            info.compress_type = metodo
            z.writestr(info, dados)
    return buf.getvalue()


def _zip_com_ts_municipio(csv_municipio: bytes, ano=2025, **kw) -> bytes:
    """O mesmo zip SINTÉTICO de ``ano`` com OUTRO TS_MUNICIPIO (o resto igual)."""
    return zip_microdados(ano, extra={"DADOS/TS_MUNICIPIO.csv": csv_municipio}, **kw)


def zip64_microdados(monkeypatch) -> bytes:
    """O mesmo zip em ZIP64: com o limite do zipfile rebaixado, as entradas ganham o
    extra ZIP64 e o fim ganha o registro + localizador ZIP64; o EOCD comum é
    marcado com 0xFFFF/0xFFFFFFFF (como os gravadores fazem nos zips grandes)."""
    monkeypatch.setattr(zipfile, "ZIP64_LIMIT", 1024)
    dados = zip_microdados()
    monkeypatch.undo()
    pos = dados.rfind(b"PK\x05\x06")
    marcado = (dados[:pos + 8] + b"\xff\xff\xff\xff" + b"\xff\xff\xff\xff\xff\xff\xff\xff"
               + dados[pos + 20:])
    assert b"PK\x06\x06" in marcado and b"PK\x06\x07" in marcado
    return marcado


class ServidorFalso:
    """O "servidor do INEP" SUBSTITUÍDO: responde Range com os bytes do zip em
    memória e registra cada faixa pedida (nenhum acesso à internet)."""

    def __init__(self, dados: bytes, *, status=206, etags=('"v1"',)):
        self.dados = dados
        self.status = status
        self.etags = list(etags)
        self.pedidos: list[str] = []

    def __call__(self, url: str, faixa: str, maximo: int) -> RespostaFaixa:
        self.pedidos.append(faixa)
        etag = self.etags[min(len(self.pedidos) - 1, len(self.etags) - 1)]
        if self.status != 206:
            return RespostaFaixa(self.status, {"etag": etag}, b"")
        ini, fim = _intervalo(faixa, len(self.dados))
        return RespostaFaixa(206, {"content-range": f"bytes {ini}-{fim}/{len(self.dados)}",
                                   "etag": etag, "last-modified": LAST_MODIFIED},
                             self.dados[ini:fim + 1])

    def intervalos(self) -> list[tuple[int, int]]:
        return [_intervalo(f, len(self.dados)) for f in self.pedidos]


def _intervalo(faixa: str, total: int) -> tuple[int, int]:
    casou = re.fullmatch(r"bytes=(\d*)-(\d*)", faixa)
    if casou.group(1) == "":
        return max(0, total - int(casou.group(2))), total - 1
    return int(casou.group(1)), min(int(casou.group(2)), total - 1)


def _faixa_da_entrada(dados: bytes, nome: str) -> tuple[int, int]:
    """[início, fim) da entrada no zip: cabeçalho local + bytes comprimidos."""
    info = zipfile.ZipFile(io.BytesIO(dados)).getinfo(nome)
    inicio = info.header_offset
    n_nome, n_extra = struct.unpack_from("<HH", dados, inicio + 26)
    return inicio, inicio + 30 + n_nome + n_extra + info.compress_size


def _preparar(dados: bytes, codigo=MUN, **kw) -> preparar.Preparo:
    return preparar.preparar(codigo_ibge=codigo, url=URL, buscar=ServidorFalso(dados),
                             agora=datetime(2026, 10, 17, 12, 0), **kw)


def _por_chave(linhas) -> dict:
    return {(ln.abrangencia, ln.rede_ensino, ln.indicador, ln.nivel): ln for ln in linhas}


# --- Parser (puro) -----------------------------------------------------------------

def test_ts_municipio_2025_so_a_rede_municipal_do_municipio_com_niveis():
    leitura = aeeb.ler_tabela_aeeb(ts_municipio(2025), "DADOS/TS_MUNICIPIO.csv", codigo_ibge=MUN)
    assert (leitura.parser, leitura.tabela, leitura.edicao_arquivo) == (
        aeeb.PARSER, "TS_MUNICIPIO", 2025)
    assert leitura.territorios == {MUN: NOME_MUN}            # Latin-1 decodificado
    assert {(ln.abrangencia, ln.codigo_territorio, ln.rede_ensino) for ln in leitura.linhas} == {
        ("municipio", MUN, "municipal")}                     # nem o vizinho nem a pública
    por = _por_chave(leitura.linhas)
    alf = por[("municipio", "municipal", "percentual_alfabetizado", "")]
    media = por[("municipio", "municipal", "media_lp", "")]
    assert (alf.valor, alf.casas_decimais, alf.unidade) == (30.2, 2, "percentual")
    assert (media.valor, media.casas_decimais, media.unidade) == (726.48, 2, "escala_alfabetizacao")
    assert [por[("municipio", "municipal", "pct_nivel", str(k))].valor for k in range(9)] == [
        7.34, 9.72, 13.22, 16.06, 20.76, 15.76, 11.2, 5.05, 0.89]
    assert all(ln.etapa == "2_ano" and ln.componente == "lp" and ln.casas_decimais == 2
               for ln in leitura.linhas)
    assert len(leitura.linhas) == 11 and len(leitura.linhas_usadas) == 1
    assert leitura.linhas_lidas == 3


def test_ts_municipio_2023_sem_niveis_avisa_e_le_o_resto():
    leitura = aeeb.ler_tabela_aeeb(ts_municipio(2023), "TS_MUNICIPIO.csv", codigo_ibge=MUN)
    assert {ln.indicador for ln in leitura.linhas} == {"percentual_alfabetizado", "media_lp"}
    por = _por_chave(leitura.linhas)
    assert por[("municipio", "municipal", "media_lp", "")].valor == 719.86
    assert any("não traz a distribuição por nível" in a for a in leitura.avisos)


def test_ts_estado_uf_nas_redes_municipal_e_publica_sem_brasil():
    leitura = aeeb.ler_tabela_aeeb(ts_estado(2025), "TS_ESTADO.csv", codigo_ibge=MUN)
    assert leitura.tabela == "TS_ESTADO"
    assert {(ln.abrangencia, ln.codigo_territorio, ln.rede_ensino) for ln in leitura.linhas} == {
        ("uf", "35", "municipal"), ("uf", "35", "publica")}  # nem estadual, total, outra UF, BR
    por = _por_chave(leitura.linhas)
    assert por[("uf", "municipal", "percentual_alfabetizado", "")].valor == 31.57
    assert por[("uf", "publica", "percentual_alfabetizado", "")].valor == 33.5
    assert por[("uf", "municipal", "pct_nivel", "0")].valor == 7.04
    assert leitura.territorios == {}       # a sigla não sobrescreve o nome da UF


def test_colunas_pelo_nome_nao_pela_posicao_e_utf8_tambem():
    normal = aeeb.ler_tabela_aeeb(ts_municipio(), "TS_MUNICIPIO.csv", codigo_ibge=MUN)
    invertidas = list(reversed(COLS_MUN))
    linhas = [_mun(2025, OUTRO, "Vizinho Sintético", pc="91.40"), _mun(2025)]
    outro = aeeb.ler_tabela_aeeb(_csv(invertidas, linhas, codificacao="utf-8"),
                                 "TS_MUNICIPIO.csv", codigo_ibge=MUN)
    assert sorted(normal.linhas, key=lambda ln: ln.chave) == sorted(outro.linhas,
                                                                    key=lambda ln: ln.chave)
    assert outro.territorios == {MUN: NOME_MUN}


@pytest.mark.parametrize("nome, conteudo, trecho", [
    ("DADOS/TS_ALUNO.csv", None, "dado POR ALUNO"),
    ("TS_MUNICIPIO.csv", "aluno_disfarcado", "coluna de aluno/escola"),
    ("TS_MUNICIPIO.csv", "escola", "ID_ESCOLA"),
])
def test_recusa_arquivo_de_aluno_pelo_nome_ou_pelas_colunas(nome, conteudo, trecho):
    if conteudo is None:
        dados = ts_aluno()
    elif conteudo == "aluno_disfarcado":
        dados = ts_aluno()                   # o TS_ALUNO renomeado para TS_MUNICIPIO
    else:
        dados = _csv(["NU_ANO_AVALIACAO", "CO_UF", "CO_MUNICIPIO", "ID_ESCOLA", "TP_SERIE",
                      "ID_TIPO_REDE", "PC_ALUNO_ALFABETIZADO", "VL_MEDIA_LP"],
                     [{"NU_ANO_AVALIACAO": 2025, "CO_UF": 35, "CO_MUNICIPIO": MUN,
                       "ID_ESCOLA": 1, "TP_SERIE": 2, "ID_TIPO_REDE": 3,
                       "PC_ALUNO_ALFABETIZADO": "34.00", "VL_MEDIA_LP": "720.0"}])
    with pytest.raises(ImportacaoRecusada, match=re.escape(trecho)):
        aeeb.ler_tabela_aeeb(dados, nome, codigo_ibge=MUN)


def test_recusas_de_layout():
    sem_media = _csv([c for c in COLS_MUN if c != "VL_MEDIA_LP"],
                     [{c: v for c, v in _mun(2025).items() if c != "VL_MEDIA_LP"}])
    with pytest.raises(ImportacaoRecusada, match="VL_MEDIA_LP"):
        aeeb.ler_tabela_aeeb(sem_media, "TS_MUNICIPIO.csv", codigo_ibge=MUN)
    meio = [c for c in COLS_MUN if c != "PC_ALUNO_NIVEL_4_LP"]
    with pytest.raises(ImportacaoRecusada, match="só parte dos níveis"):
        aeeb.ler_tabela_aeeb(_csv(meio, [{c: _mun(2025)[c] for c in meio}]), "TS_MUNICIPIO.csv",
                             codigo_ibge=MUN)
    with pytest.raises(ImportacaoRecusada, match="mistura anos"):
        aeeb.ler_tabela_aeeb(_csv(COLS_MUN, [_mun(2025), _mun(2024, OUTRO)]),
                             "TS_MUNICIPIO.csv", codigo_ibge=MUN)
    with pytest.raises(ImportacaoRecusada, match="fora da faixa"):
        aeeb.ler_tabela_aeeb(_csv(COLS_MUN, [_mun(2025, pc="120.00")]), "TS_MUNICIPIO.csv",
                             codigo_ibge=MUN)
    with pytest.raises(ImportacaoRecusada, match="aparece 2 vezes"):
        aeeb.ler_tabela_aeeb(_csv(COLS_MUN, [_mun(2025), _mun(2025)]), "TS_MUNICIPIO.csv",
                             codigo_ibge=MUN)
    cortado = _csv(COLS_MUN, [_mun(2025)]) + b"2025;35;SP\n"
    with pytest.raises(ImportacaoRecusada, match="colunas"):
        aeeb.ler_tabela_aeeb(cortado, "TS_MUNICIPIO.csv", codigo_ibge=MUN)
    with pytest.raises(ImportacaoRecusada, match="não parece"):
        aeeb.ler_tabela_aeeb(b"a;b;c\n1;2;3\n", "TS_MUNICIPIO.csv", codigo_ibge=MUN)


def test_decimal_sem_zero_final_e_ausencia_nao_e_zero():
    linha = _mun(2025, pc="27.9", media="NA")
    linha["PC_ALUNO_NIVEL_3_LP"] = ""
    leitura = aeeb.ler_tabela_aeeb(_csv(COLS_MUN, [linha]), "TS_MUNICIPIO.csv", codigo_ibge=MUN)
    por = _por_chave(leitura.linhas)
    alf = por[("municipio", "municipal", "percentual_alfabetizado", "")]
    assert (alf.valor, alf.casas_decimais) == (27.9, 2)     # 27,90: a precisão é a da fonte
    media = por[("municipio", "municipal", "media_lp", "")]
    nivel3 = por[("municipio", "municipal", "pct_nivel", "3")]
    assert (media.valor, media.motivo_ausencia) == (None, "nao_divulgado")
    assert (nivel3.valor, nivel3.motivo_ausencia) == (None, "nao_divulgado")
    assert all(ln.valor != 0 for ln in leitura.linhas)


def test_municipio_ausente_ou_so_noutra_rede_nao_grava_e_avisa():
    leitura = aeeb.ler_tabela_aeeb(ts_municipio(), "TS_MUNICIPIO.csv", codigo_ibge="3511111")
    assert leitura.linhas == [] and any("não está no TS_MUNICIPIO" in a for a in leitura.avisos)
    so_publica = _csv(COLS_MUN, [_mun(2025, rede="5")])
    leitura = aeeb.ler_tabela_aeeb(so_publica, "TS_MUNICIPIO.csv", codigo_ibge=MUN)
    assert leitura.linhas == [] and any("rede MUNICIPAL" in a for a in leitura.avisos)


def test_outra_serie_e_niveis_que_nao_somam_100_avisam():
    torto = _mun(2025, niveis=["22.48"] * 9)
    outra = _mun(2025, OUTRO, serie="5")
    leitura = aeeb.ler_tabela_aeeb(_csv(COLS_MUN, [torto, outra]), "TS_MUNICIPIO.csv",
                                   codigo_ibge=MUN)
    assert any("somam 202.32%" in a for a in leitura.avisos)
    assert any("outra série" in a for a in leitura.avisos)


# --- Zip por faixa: local, HTTP Range substituído, ZIP64, CRC -------------------

def test_zip_local_le_so_a_entrada_pedida_com_crc_e_recusa_a_de_aluno(tmp_path):
    caminho = tmp_path / "microdados.zip"
    caminho.write_bytes(zip_microdados())
    fonte = zip_parcial.FonteArquivoLocal(caminho)
    entradas = {e.base: e for e in zip_parcial.listar_entradas(fonte)}
    assert set(entradas) == {"TS_ALUNO.csv", "TS_MUNICIPIO.csv", "TS_ESTADO.csv",
                             "INPUT_R_TS_MUNICIPIO_2025.R"}
    assert entradas["TS_MUNICIPIO.csv"].data_interna == datetime(*DATA_ENTRADA)
    assert zip_parcial.ler_entrada(fonte, entradas["TS_MUNICIPIO.csv"]) == ts_municipio()
    with pytest.raises(ImportacaoRecusada, match="POR ALUNO"):
        zip_parcial.ler_entrada(fonte, entradas["TS_ALUNO.csv"])
    ini_aluno, fim_aluno = _faixa_da_entrada(caminho.read_bytes(), "DADOS/TS_ALUNO.csv")
    assert fonte.faixas and all(f <= ini_aluno or i >= fim_aluno for i, f in fonte.faixas)


def test_zip_sem_compressao_e_metodo_nao_suportado(tmp_path):
    caminho = tmp_path / "m.zip"
    caminho.write_bytes(zip_microdados(metodo=zipfile.ZIP_STORED))
    fonte = zip_parcial.FonteArquivoLocal(caminho)
    e = next(x for x in zip_parcial.listar_entradas(fonte) if x.base == "TS_ESTADO.csv")
    assert zip_parcial.ler_entrada(fonte, e) == ts_estado()
    estranho = zip_parcial.Entrada(**{**e.__dict__, "metodo": 14})
    with pytest.raises(ImportacaoRecusada, match="método de compressão"):
        zip_parcial.ler_entrada(fonte, estranho)


def test_crc_errado_e_recusado():
    dados = bytearray(zip_microdados())
    info = zipfile.ZipFile(io.BytesIO(bytes(dados))).getinfo("DADOS/TS_MUNICIPIO.csv")
    # troca o CRC32 declarado no diretório central da entrada TS_MUNICIPIO
    pos = 0
    while True:
        pos = dados.find(b"PK\x01\x02", pos)
        nome_len = int.from_bytes(dados[pos + 28:pos + 30], "little")
        if dados[pos + 46:pos + 46 + nome_len] == b"DADOS/TS_MUNICIPIO.csv":
            break
        pos += 4
    dados[pos + 16:pos + 20] = ((info.CRC ^ 0xFFFF) & 0xFFFFFFFF).to_bytes(4, "little")
    with pytest.raises(ImportacaoRecusada, match="CRC32 .* não confere"):
        _preparar(bytes(dados))


def test_zip64_le_pelo_registro_de_fim_zip64(monkeypatch):
    dados = zip64_microdados(monkeypatch)
    servidor = ServidorFalso(dados)
    fonte = zip_parcial.FonteHTTPRange(URL, servidor)
    entradas = {e.base: e for e in zip_parcial.listar_entradas(fonte)}
    e = entradas["TS_MUNICIPIO.csv"]
    assert zip_parcial.ler_entrada(fonte, e) == ts_municipio()
    preparo = _preparar(dados)
    assert {x["tabela"] for x in preparo.manifesto["entradas"]} == {"TS_MUNICIPIO", "TS_ESTADO"}


def test_http_range_substituido_nunca_pede_o_ts_aluno_nem_o_zip_inteiro():
    dados = zip_microdados()
    servidor = ServidorFalso(dados)
    preparo = preparar.preparar(codigo_ibge=MUN, url=URL, buscar=servidor)
    ini_aluno, fim_aluno = _faixa_da_entrada(dados, "DADOS/TS_ALUNO.csv")
    for ini, fim in servidor.intervalos():
        assert fim < ini_aluno or ini >= fim_aluno, (ini, fim)   # nem um byte do TS_ALUNO
    assert preparo.bytes_lidos < len(dados) / 4
    assert servidor.pedidos[0].startswith("bytes=-")              # 1º: o fim do zip
    assert preparo.manifesto["origem"]["last_modified"] == LAST_MODIFIED
    assert preparo.manifesto["origem"]["etag"] == '"v1"'
    assert preparo.manifesto["origem"]["entradas_de_aluno_nao_lidas"] == ["DADOS/TS_ALUNO.csv"]


def test_http_servidor_que_ignora_range_ou_muda_o_arquivo_e_recusado():
    with pytest.raises(ImportacaoRecusada, match="não aceitou a leitura por faixa"):
        preparar.preparar(codigo_ibge=MUN, url=URL, buscar=ServidorFalso(zip_microdados(),
                                                                          status=200))
    mudou = ServidorFalso(zip_microdados(), etags=('"v1"', '"v2"'))
    with pytest.raises(ImportacaoRecusada, match="mudou durante a leitura"):
        preparar.preparar(codigo_ibge=MUN, url=URL, buscar=mudou)


def test_busca_https_real_com_transporte_falso_manda_range_e_nao_le_200(monkeypatch):
    """O cliente HTTP de verdade (httpx) com um transporte FALSO — nada sai da
    máquina: confere o cabeçalho Range, o 206, o redirecionamento revalidado e a
    recusa do 200 sem ler o corpo."""
    dados = zip_microdados()
    destinos = []
    monkeypatch.setattr(svc, "_exigir_destino_publico", lambda url: destinos.append(url))
    vistos = []

    def responder(request: httpx.Request) -> httpx.Response:
        vistos.append(request.headers.get("range"))
        if request.url.path.endswith("antigo.zip"):
            return httpx.Response(302, headers={"location": URL})
        ini, fim = _intervalo(request.headers["range"], len(dados))
        return httpx.Response(206, content=dados[ini:fim + 1], headers={
            "content-range": f"bytes {ini}-{fim}/{len(dados)}", "last-modified": LAST_MODIFIED})

    transporte = httpx.MockTransport(responder)
    buscar = functools.partial(zip_parcial.buscar_faixa_https, transporte=transporte)
    preparo = preparar.preparar(codigo_ibge=MUN, url=URL.replace("sintetico_2025", "antigo"),
                                buscar=buscar)
    assert preparo.manifesto["edicao"] == 2025
    assert all(v and v.startswith("bytes=") for v in vistos)
    assert URL in destinos and destinos[0].endswith("antigo.zip")   # cada salto revalidado

    inteiro = httpx.MockTransport(lambda r: httpx.Response(200, content=dados))
    r = zip_parcial.buscar_faixa_https(URL, "bytes=0-9", 10, transporte=inteiro)
    assert (r.status, r.corpo) == (200, b"")                         # corpo NÃO lido
    with pytest.raises(ValueError, match="só https"):
        monkeypatch.undo()
        zip_parcial.buscar_faixa_https("http://download.inep.gov.br/x.zip", "bytes=0-9", 10,
                                       transporte=inteiro)


# --- preparar: pacote recortado ------------------------------------------------------

def test_preparar_zip_local_e_url_geram_o_mesmo_recorte_com_manifesto(tmp_path):
    caminho = tmp_path / "microdados_sintetico_2025.zip"
    caminho.write_bytes(zip_microdados())
    local = preparar.preparar(codigo_ibge=MUN, zip_local=caminho, url=URL,
                              last_modified=LAST_MODIFIED)
    remoto = _preparar(caminho.read_bytes())
    for p in (local, remoto):
        m = p.manifesto
        assert (m["tipo"], m["parser"], m["parser_versao"], m["codigo_territorio_alvo"],
                m["edicao"]) == ("pacote_indicadores", "inep_aeeb_agregados", "1", MUN, 2025)
        assert [e["tabela"] for e in m["entradas"]] == ["TS_MUNICIPIO", "TS_ESTADO"]
        mun = m["entradas"][0]
        assert mun["nome"] == "DADOS/TS_MUNICIPIO.csv" and mun["linhas_recorte"] == 1
        assert mun["linhas_original"] == 3 and mun["data_interna"] == "2026-03-10T10:00:00"
        assert len(mun["sha256"]) == 64 and re.fullmatch(r"[0-9a-f]{8}", mun["crc32"])
        assert m["entradas"][1]["linhas_recorte"] == 2               # SP municipal + pública
        assert len(p.pacote) < 4096
    assert local.manifesto["origem"]["zip_sha256"] and remoto.manifesto["origem"]["zip_sha256"] is None
    with zipfile.ZipFile(io.BytesIO(local.pacote)) as z, zipfile.ZipFile(io.BytesIO(remoto.pacote)) as w:
        assert sorted(z.namelist()) == ["TS_ESTADO.csv", "TS_MUNICIPIO.csv", "manifesto.json"]
        for nome in ("TS_ESTADO.csv", "TS_MUNICIPIO.csv"):
            assert z.read(nome) == w.read(nome)
        recorte = z.read("TS_MUNICIPIO.csv")
        assert b"\r" not in recorte and OUTRO.encode() not in recorte   # só a rede, LF
        assert recorte.decode("utf-8").count("\n") == 2                # cabeçalho + 1 linha


def test_preparar_linha_de_comando_grava_o_pacote_e_recusa_com_codigo_2(tmp_path, capsys):
    caminho = tmp_path / "m.zip"
    caminho.write_bytes(zip_microdados())
    saida = tmp_path / "saida"
    assert preparar.main(["--ibge", MUN, "--zip", str(caminho), "--saida", str(saida)]) == 0
    gerado = saida / f"pacote_ica_aeeb_2025_{MUN}.zip"
    assert gerado.exists() and pacote.eh_pacote(gerado.read_bytes())
    texto = capsys.readouterr().out
    assert "CRC32" in texto and "conferido" in texto and "percentual_alfabetizado" in texto
    sem_tabelas = tmp_path / "outro.zip"
    with zipfile.ZipFile(sem_tabelas, "w") as z:
        z.writestr("DADOS/TS_ALUNO.csv", ts_aluno()[:1000])
    assert preparar.main(["--ibge", MUN, "--zip", str(sem_tabelas), "--saida", str(saida)]) == 2
    assert "não tem as tabelas agregadas" in capsys.readouterr().err
    assert preparar.main(["--ibge", "123", "--zip", str(caminho)]) == 2


SEM_LINHA = "3599997"      # município SINTÉTICO sem linha da rede municipal


def _ts_sem_a_rede_municipal(caso: str) -> bytes:
    """TS_MUNICIPIO em que ``SEM_LINHA`` não aparece (``ausente``) ou só aparece nas
    redes estadual e pública (``so_outra_rede``)."""
    linhas = [_mun(2025, OUTRO, "Vizinho Sintético", pc="91.40", media="793.60410")]
    if caso == "so_outra_rede":
        linhas += [_mun(2025, SEM_LINHA, "Sem Rede Municipal", rede=r) for r in ("2", "5")]
    return _csv(COLS_MUN, linhas)


@pytest.mark.parametrize("caso, trecho", [
    ("ausente", f"O município {SEM_LINHA} não está no TS_MUNICIPIO de 2025"),
    ("so_outra_rede", f"O município {SEM_LINHA} está no TS_MUNICIPIO, mas não na rede MUNICIPAL"),
])
def test_municipio_sem_a_rede_municipal_vai_so_com_o_ts_estado(tmp_path, capsys, caso, trecho):
    """Sem linha da rede municipal, o TS_MUNICIPIO fica FORA do pacote (um recorte só
    com o cabeçalho seria recusado pelo servidor e levaria junto as linhas de SP)."""
    caminho = tmp_path / "m.zip"
    caminho.write_bytes(_zip_com_ts_municipio(_ts_sem_a_rede_municipal(caso)))
    saida = tmp_path / "saida"
    assert preparar.main(["--ibge", SEM_LINHA, "--zip", str(caminho), "--saida", str(saida)]) == 0
    gerado = (saida / f"pacote_ica_aeeb_2025_{SEM_LINHA}.zip").read_bytes()
    with zipfile.ZipFile(io.BytesIO(gerado)) as z:
        assert sorted(z.namelist()) == ["TS_ESTADO.csv", "manifesto.json"]
        m = json.loads(z.read("manifesto.json"))
    assert [(e["tabela"], e["linhas_recorte"]) for e in m["entradas"]] == [("TS_ESTADO", 2)]
    assert f"TS_MUNICIPIO: {trecho}" in " ".join(m["avisos_preparo"])
    assert ("TS_MUNICIPIO: nenhuma linha a importar — a tabela fica fora do pacote."
            in m["avisos_preparo"])
    assert "fica fora do pacote" in capsys.readouterr().out


def test_sem_nenhuma_linha_da_rede_o_preparar_recusa_e_nao_grava(tmp_path, capsys):
    caminho = tmp_path / "m.zip"
    caminho.write_bytes(_zip_com_ts_municipio(_ts_sem_a_rede_municipal("ausente"),
                                              sem_estado=True))
    with pytest.raises(ImportacaoRecusada, match=(
            rf"Nada a importar para o município {SEM_LINHA} neste zip: .*não está no "
            r"TS_MUNICIPIO de 2025.* O zip não tem TS_ESTADO\.csv\. Nenhum pacote foi gerado\.")):
        preparar.preparar(codigo_ibge=SEM_LINHA, zip_local=caminho)
    saida = tmp_path / "saida"
    assert preparar.main(["--ibge", SEM_LINHA, "--zip", str(caminho), "--saida", str(saida)]) == 2
    assert "Nada a importar" in capsys.readouterr().err
    assert not saida.exists()                       # nenhum pacote, nem a pasta


def test_tabela_que_fica_fora_do_pacote_ainda_conta_para_uma_edicao_so():
    """TS_MUNICIPIO de 2024 (sem o município) com TS_ESTADO de 2025: a tabela vazia
    sai do pacote, mas o zip continua misturando anos — recusa."""
    dados = _zip_com_ts_municipio(_csv(COLS_MUN, [_mun(2024, OUTRO, "Vizinho Sintético")]))
    with pytest.raises(ImportacaoRecusada, match=r"anos diferentes \(2024, 2025\)"):
        _preparar(dados, codigo=SEM_LINHA)


# --- Pipeline: pacote → prévia → aplicação; precedência; adulteração -----------------

@pytest.fixture()
def rede(db):
    r = Rede(nome="Rede Sintética", uf="SP", codigo_ibge=MUN, status="ativa")
    db.add(r)
    db.commit()
    return r


def _aplicar(db, rede, conteudo, nome="arquivo.xlsx"):
    """O nome só importa para a planilha (.xlsx); o pacote é detectado pelo conteúdo."""
    p = pipeline.previa(db, rede, conteudo, nome, usuario_id=None)
    db.commit()
    a = pipeline.aplicar(db, rede, p["id"], conteudo, nome, usuario_id=None)
    db.commit()
    return a


def _pac(ano=2025) -> bytes:
    return _preparar(zip_microdados(ano)).pacote


def test_previa_do_pacote_registra_a_origem_do_manifesto_e_nao_grava(db, rede):
    conteudo = _pac()
    p = pipeline.previa(db, rede, conteudo, "pacote.zip", usuario_id=None,
                        url_origem="https://outro.exemplo/x", last_modified_origem="digitado")
    db.commit()
    assert db.scalar(select(func.count(IndicadorReferencia.id))) == 0
    imp = db.get(ImportacaoIndicador, p["id"])
    assert (imp.parser, imp.modo, imp.edicao_arquivo) == ("inep_aeeb_agregados", "pacote_cli", 2025)
    assert imp.url_origem == URL and imp.last_modified_origem == LAST_MODIFIED
    assert imp.arquivo_nome == "microdados_sintetico_2025.zip"
    assert imp.arquivo_data == datetime(*DATA_ENTRADA)              # data interna da entrada
    assert imp.coletado_em == datetime(2026, 10, 17, 12, 0)
    assert len(imp.pacote_sha256) == 64 and imp.pacote_sha256 != imp.arquivo_sha256
    assert imp.resumo["pacote"]["entradas"][0]["crc32"]
    assert p["contadores"]["novas"] == 33             # município 11 + SP municipal 11 + pública 11
    assert {m["rede_ensino"] for m in p["mudancas"] if m["abrangencia"] == "uf"} == {
        "municipal", "publica"}
    assert any(m["territorio"] == "UF 35 (redes municipais)" for m in p["mudancas"])


def _pacote_mexido(conteudo: bytes, *, csv=None, manifesto=None, extra=None) -> bytes:
    entrada = zipfile.ZipFile(io.BytesIO(conteudo))
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as novo:
        for nome in entrada.namelist():
            dados = entrada.read(nome)
            if nome == "manifesto.json" and manifesto:
                m = json.loads(dados)
                manifesto(m)
                dados = json.dumps(m).encode()
            if nome == "TS_MUNICIPIO.csv" and csv:
                dados = csv(dados)
            novo.writestr(nome, dados)
        for nome, dados in (extra or {}).items():
            novo.writestr(nome, dados)
    return saida.getvalue()


def _recorte_com_vizinho(dados: bytes) -> bytes:
    """Acrescenta ao recorte uma linha de outro município (e acerta o manifesto)."""
    return dados + ";".join(str(v) for v in _mun(2025, OUTRO, "Vizinho").values()).encode() + b"\n"


@pytest.mark.parametrize("mexer, trecho", [
    (dict(csv=lambda d: d.replace(b"30.20", b"40.20")), "sha256 diferente"),
    (dict(manifesto=lambda m: m.update(parser="inep_ideb_escolas")), "inep_ideb_escolas"),
    (dict(manifesto=lambda m: m.update(parser_versao="0")), "versão"),
    (dict(manifesto=lambda m: m.update(codigo_territorio_alvo="3511111")), "município 3511111"),
    (dict(manifesto=lambda m: m.update(formato=99)), "formato de pacote"),
    (dict(extra={"leia-me.txt": b"oi"}), "não declara"),
    (dict(manifesto=lambda m: m["entradas"][0].update(nome="DADOS/TS_ALUNO.csv")), "POR ALUNO"),
])
def test_pacote_adulterado_e_recusado(db, rede, mexer, trecho):
    with pytest.raises(ImportacaoRecusada, match=re.escape(trecho)):
        pipeline.previa(db, rede, _pacote_mexido(_pac(), **mexer), "p.zip", usuario_id=None)


def test_pacote_com_linha_de_fora_mesmo_com_o_hash_acertado_e_recusado(db, rede):
    original = _pac()
    recorte = _recorte_com_vizinho(zipfile.ZipFile(io.BytesIO(original)).read("TS_MUNICIPIO.csv"))

    def acertar(m):
        m["entradas"][0]["csv_sha256"] = hashlib.sha256(recorte).hexdigest()
    mexido = _pacote_mexido(original, csv=lambda _: recorte, manifesto=acertar)
    with pytest.raises(ImportacaoRecusada, match="não é um recorte do preparar"):
        pipeline.previa(db, rede, mexido, "p.zip", usuario_id=None)


def test_pacote_com_tabela_vazia_e_recusado_com_a_causa(db, rede):
    """Um recorte só com o cabeçalho (o preparar de antes gerava) diz a causa — não
    "o arquivo não tem linhas de dados; confira se é a tabela agregada"."""
    original = _pac()
    so_cabecalho = zipfile.ZipFile(io.BytesIO(original)).read("TS_MUNICIPIO.csv").split(b"\n")[0] + b"\n"

    def acertar(m):
        m["entradas"][0].update(csv_sha256=hashlib.sha256(so_cabecalho).hexdigest(),
                                linhas_recorte=0)
    mexido = _pacote_mexido(original, csv=lambda _: so_cabecalho, manifesto=acertar)
    with pytest.raises(ImportacaoRecusada, match="não tem nenhuma linha da rede"):
        pipeline.previa(db, rede, mexido, "p.zip", usuario_id=None)


def test_pacote_com_entrada_cifrada_e_recusa_limpa_nao_erro_500(db, rede):
    dados = bytearray(_pac())
    pos = dados.find(b"PK\x01\x02")
    while dados[pos + 46:pos + 46 + len(b"TS_MUNICIPIO.csv")] != b"TS_MUNICIPIO.csv":
        pos = dados.find(b"PK\x01\x02", pos + 4)
    flags = int.from_bytes(dados[pos + 8:pos + 10], "little") | 0x1     # bit "cifrado"
    dados[pos + 8:pos + 10] = flags.to_bytes(2, "little")
    with pytest.raises(ImportacaoRecusada, match="corrompido, cifrado"):
        pipeline.previa(db, rede, bytes(dados), "p.zip", usuario_id=None)


@pytest.mark.parametrize("caso", ["ausente", "so_outra_rede"])
def test_pacote_sem_o_municipio_chega_a_previa_so_com_sp(db, caso):
    """Do preparar até a prévia: sem linha da rede municipal, entram as linhas de SP
    (redes municipais e pública) e a prévia diz, pelo preparo, por que o município
    ficou de fora."""
    rede_sem = Rede(nome="Rede Sintética Sem Linha", uf="SP", codigo_ibge=SEM_LINHA,
                    status="ativa")
    db.add(rede_sem)
    db.commit()
    conteudo = _preparar(_zip_com_ts_municipio(_ts_sem_a_rede_municipal(caso)),
                         codigo=SEM_LINHA).pacote
    p = pipeline.previa(db, rede_sem, conteudo, "p.zip", usuario_id=None)
    assert p["contadores"]["novas"] == 22                 # SP municipal 11 + pública 11
    assert {(m["abrangencia"], m["rede_ensino"]) for m in p["mudancas"]} == {
        ("uf", "municipal"), ("uf", "publica")}
    assert any(a.startswith("No preparo: TS_MUNICIPIO: O município") for a in p["avisos"])
    assert "No preparo: TS_MUNICIPIO: nenhuma linha a importar — a tabela fica fora do pacote." \
        in p["avisos"]


def test_aplicar_exige_o_mesmo_pacote(db, rede):
    conteudo = _pac()
    p = pipeline.previa(db, rede, conteudo, "p.zip", usuario_id=None)
    db.commit()
    with pytest.raises(ImportacaoRecusada, match="não é o mesmo da prévia"):
        pipeline.aplicar(db, rede, p["id"], conteudo + b"\0", "p.zip", usuario_id=None)
    db.rollback()
    outro = preparar.preparar(codigo_ibge=MUN, url=URL, buscar=ServidorFalso(zip_microdados()),
                              agora=datetime(2026, 10, 18)).pacote      # outro gerado_em
    with pytest.raises(ImportacaoRecusada, match="não é o mesmo da prévia"):
        pipeline.aplicar(db, rede, p["id"], outro, "p.zip", usuario_id=None)


@pytest.mark.parametrize("nome, conteudo, trecho", [
    ("TS_MUNICIPIO.csv", ts_municipio, "gere o pacote"),
    ("TS_ALUNO.csv", ts_aluno, "dado POR ALUNO"),
    ("microdados_AEEB_2025.zip", zip_microdados, "TS_ALUNO"),
], ids=["ts-municipio-cru", "ts-aluno", "zip-inteiro"])
def test_arquivo_cru_dos_microdados_e_zip_inteiro_sao_recusados(db, rede, nome, conteudo, trecho):
    with pytest.raises(ImportacaoRecusada, match=re.escape(trecho)):
        pipeline.previa(db, rede, conteudo(), nome, usuario_id=None)
    assert db.scalar(select(func.count(ImportacaoIndicador.id))) == 0


def _conferir_precedencia(db):
    v = _valores(db)
    # capa = planilha (inteiro); detalhe = 2 casas dos microdados, com a data deles
    assert v[("municipio", "percentual_alfabetizado", 2025)] == (30, 30.2)
    linha = db.execute(select(IndicadorReferencia).where(
        IndicadorReferencia.indicador == "percentual_alfabetizado",
        IndicadorReferencia.abrangencia == "municipio",
        IndicadorReferencia.edicao == 2025)).scalar_one()
    detalhe = db.get(ImportacaoIndicador, linha.detalhe_importacao_id)
    capa = db.get(ImportacaoIndicador, linha.importacao_id)
    assert detalhe.parser == "inep_aeeb_agregados" and capa.parser == "inep_ica_municipios"
    assert linha.casas_decimais_detalhe == 2
    # UF pública: 33,50 arredonda (meio para cima) para a capa 34 da planilha de UFs
    uf_pub = db.execute(select(IndicadorReferencia).where(
        IndicadorReferencia.abrangencia == "uf", IndicadorReferencia.rede_ensino == "publica",
        IndicadorReferencia.indicador == "percentual_alfabetizado",
        IndicadorReferencia.edicao == 2025)).scalar_one()
    assert (uf_pub.valor, uf_pub.valor_detalhado) == (34, 33.5)
    # o que só os microdados trazem é capa
    assert v[("municipio", "media_lp", 2025)] == (726.48, None)
    uf_mun = db.execute(select(IndicadorReferencia).where(
        IndicadorReferencia.abrangencia == "uf", IndicadorReferencia.rede_ensino == "municipal",
        IndicadorReferencia.indicador == "percentual_alfabetizado")).scalar_one()
    assert (uf_mun.valor, uf_mun.casas_decimais) == (31.57, 2)
    return _estado_com_fonte(db)


def _estado_com_fonte(db) -> list[tuple]:
    """Cada linha com o valor E a fonte da capa e do detalhe — a fonte pelo ARQUIVO
    (parser e edição), porque os ids mudam de uma rodada para outra."""
    db.expire_all()
    arquivo = {i.id: (i.parser, i.edicao_arquivo)
               for i in db.execute(select(ImportacaoIndicador)).scalars()}
    return sorted(((r.edicao, r.indicador, r.abrangencia, r.codigo_territorio, r.rede_ensino,
                    r.nivel, r.valor, r.valor_detalhado, r.casas_decimais,
                    r.casas_decimais_detalhe, r.motivo_ausencia,
                    arquivo.get(r.importacao_id), arquivo.get(r.detalhe_importacao_id))
                   for r in db.execute(select(IndicadorReferencia)).scalars()), key=repr)


def _zerar(db):
    db.query(IndicadorReferencia).delete()
    db.query(ImportacaoIndicador).delete()
    db.commit()


def test_precedencia_detalhe_dos_microdados_x_capa_da_planilha_em_qualquer_ordem(db, rede):
    arquivos = [arq_mun_2025(), arq_ufs_2025(), _pac()]
    for conteudo in arquivos:
        _aplicar(db, rede, conteudo)
    direta = _conferir_precedencia(db)
    _zerar(db)
    for conteudo in reversed(arquivos):        # microdados ANTES das planilhas
        _aplicar(db, rede, conteudo)
    assert _conferir_precedencia(db) == direta                # valores E fontes


def test_detalhe_com_as_mesmas_casas_fica_com_a_planilha_em_qualquer_ordem(db, rede):
    """Planilha de 2024 com 21,84 (2 casas) e microdados de 2024 com 21,87 (2 casas,
    data interna MAIS NOVA), sob a capa 22 da planilha de 2025. O detalhe é o da
    planilha — a mesma prioridade da capa — em todas as 6 ordens, valor e fonte.
    (Sem a prioridade no detalhe, os microdados importados depois da planilha de 2024
    eram descartados — não eram mais precisos que ela na capa — e, em outra ordem,
    venciam pela data: o resultado dependia da ordem.)"""
    micro_2024 = _preparar(_zip_com_ts_municipio(
        _csv(COLS_MUN, [_mun(2024, pc="21.87", media="721.27460", niveis=_NIV_MUN_24)]),
        ano=2024)).pacote
    arquivos = {"planilha_2024": arq_mun_2024(), "planilha_2025": arq_mun_2025(),
                "microdados_2024": micro_2024}
    estados = set()
    for ordem in itertools.permutations(arquivos):
        _zerar(db)
        for nome in ordem:
            _aplicar(db, rede, arquivos[nome])
        estado = _estado_com_fonte(db)
        linha = next(ln for ln in estado if ln[:3] == (2024, "percentual_alfabetizado", "municipio"))
        assert linha[6:8] == (22, 21.84), ordem
        assert linha[11:] == (("inep_ica_municipios", 2025), ("inep_ica_municipios", 2024)), ordem
        estados.add(repr(estado))
    assert len(estados) == 1


def test_microdados_sozinhos_sao_capa_ate_a_planilha_chegar(db, rede):
    _aplicar(db, rede, _pac())
    assert _valores(db)[("municipio", "percentual_alfabetizado", 2025)] == (30.2, None)
    b = _aplicar(db, rede, arq_mun_2025())
    assert _valores(db)[("municipio", "percentual_alfabetizado", 2025)] == (30, 30.2)
    assert b["contadores"]["alteradas"] >= 1


def test_decimal_dos_microdados_que_nao_arredonda_e_descartado_com_aviso(db, rede):
    _aplicar(db, rede, arq_mun_2025())
    torto = _csv(COLS_MUN, [_mun(2025, pc="27.30")])          # não arredonda para 30
    p = pipeline.previa(db, rede, _preparar(_zip_com_ts_municipio(torto)).pacote, "p.zip",
                        usuario_id=None)
    assert any("divergência entre arquivos" in a and "27.3" in a for a in p["avisos"])


def test_avisos_do_preparo_aparecem_na_previa_sem_repetir_os_do_servidor(db, rede):
    """O que só o arquivo INTEIRO mostra (linha de outra série) chega pela prévia como
    "No preparo: …"; o que o servidor reproduz no recorte (sem níveis em 2023)
    aparece uma vez só."""
    com_outra_serie = _csv(COLS_MUN_2023, [
        _mun(2023, pc="26.18", media="719.8642", colunas=COLS_MUN_2023),
        _mun(2023, OUTRO, serie="5", colunas=COLS_MUN_2023)])
    p = pipeline.previa(db, rede, _preparar(_zip_com_ts_municipio(com_outra_serie, ano=2023)).pacote,
                        "p.zip", usuario_id=None)
    assert any(a.startswith("No preparo: TS_MUNICIPIO: 1 linha(s) de outra série") for a in p["avisos"])
    sem_niveis = [a for a in p["avisos"] if "não traz a distribuição por nível" in a]
    assert len(sem_niveis) == 2 and not any(a.startswith("No preparo") for a in sem_niveis)


def test_pacote_reimportado_e_idempotente(db, rede):
    conteudo = _pac()
    _aplicar(db, rede, conteudo)
    antes = _estado(db)
    de_novo = _aplicar(db, rede, _pac())                      # outro pacote, mesmos números
    assert de_novo["contadores"]["iguais"] == 33 and de_novo["contadores"]["novas"] == 0
    assert de_novo["contadores"]["alteradas"] == 0 and de_novo["contadores"]["fonte_atualizada"] == 0
    assert _estado(db) == antes


# --- Desfazer pelo id -------------------------------------------------------------

def test_desfazer_pelo_id_sem_conflito_volta_ao_estado_sem_ela(db, rede):
    a = _aplicar(db, rede, _pac(2024))                         # edição 2024
    b = _aplicar(db, rede, _pac(2025))                         # 2025: outros números
    so_b = [ln for ln in _estado(db) if ln[0] == 2025]
    pipeline.desfazer(db, rede, a["id"], usuario_id=None)
    db.commit()
    assert _estado(db) == so_b
    assert db.get(ImportacaoIndicador, a["id"]).status == "desfeita"
    assert db.get(ImportacaoIndicador, b["id"]).status == "aplicada"


def test_desfazer_pelo_id_com_conflito_recusa_e_diz_qual_desfazer_antes(db, rede):
    a = _aplicar(db, rede, arq_mun_2025())
    estado_a = _estado(db)
    b = _aplicar(db, rede, _pac())                  # pôs o detalhe na capa de "a"
    lista = {i["id"]: i for i in pipeline.listar(db, rede)}
    assert lista[a["id"]]["pode_desfazer"] is False and lista[a["id"]]["bloqueada_por"] == b["id"]
    assert lista[b["id"]]["pode_desfazer"] is True
    with pytest.raises(ImportacaoRecusada, match=rf"desfaça antes a #{b['id']}"):
        pipeline.desfazer(db, rede, a["id"], usuario_id=None)
    db.rollback()
    pipeline.desfazer(db, rede, b["id"], usuario_id=None)
    db.commit()
    assert _estado(db) == estado_a                  # exatamente o de antes de "b"
    pipeline.desfazer(db, rede, a["id"], usuario_id=None)
    db.commit()
    assert db.scalar(select(func.count(IndicadorReferencia.id))) == 0


def test_posterior_que_so_viu_como_igual_tambem_bloqueia(db, rede):
    """A posterior que reimportou o mesmo arquivo viu os números como "iguais" — e
    decidiu a precedência com eles: desfazer a anterior por baixo dela não seria
    exato. Recusa; desfeita a posterior (não muda nada), a anterior sai."""
    a = _aplicar(db, rede, _pac())
    b = _aplicar(db, rede, _pac())
    assert b["contadores"]["iguais"] == 33
    with pytest.raises(ImportacaoRecusada, match=rf"#{b['id']}"):
        pipeline.desfazer(db, rede, a["id"], usuario_id=None)
    db.rollback()
    pipeline.desfazer(db, rede, b["id"], usuario_id=None)
    pipeline.desfazer(db, rede, a["id"], usuario_id=None)
    db.commit()
    assert db.scalar(select(func.count(IndicadorReferencia.id))) == 0


# --- Leitura da rede (consulta) e API ------------------------------------------------

def test_consulta_traz_media_niveis_uf_municipal_e_fonte_dos_microdados(db, rede):
    for conteudo in (arq_mun_2025(), arq_mun_2024(), arq_ufs_2025(), _pac(2024), _pac(2025)):
        _aplicar(db, rede, conteudo)
    d = consulta.ica_da_rede(db, rede)
    mun, uf, br = d["territorios"]                     # os três de sempre
    assert (uf["rede_ensino"], br["rede_ensino"]) == ("publica", "publica")
    r2025 = next(r for r in mun["resultados"] if r["edicao"] == 2025)
    assert r2025["valor"] == 30 and r2025["detalhe"]["valor"] == 30.2
    assert r2025["detalhe"]["fonte"]["parser"] == "inep_aeeb_agregados"
    assert r2025["detalhe"]["fonte"]["arquivo_data"] == datetime(*DATA_ENTRADA).isoformat()
    assert [(m["edicao"], m["valor"]) for m in mun["media_lp"]] == [(2024, 721.27), (2025, 726.48)]
    dist = {x["edicao"]: x for x in mun["distribuicao_niveis"]}
    assert [n["valor"] for n in dist[2025]["niveis"]][0] == 7.34
    assert [n["nivel"] for n in dist[2024]["niveis"]] == [str(k) for k in range(9)]
    assert dist[2025]["soma"] == 100.0
    assert br["media_lp"] == [] and br["distribuicao_niveis"] == []  # o Brasil não vem dos TS
    ufm = d["uf_municipal"]
    assert (ufm["abrangencia"], ufm["rede_ensino"], ufm["codigo_territorio"]) == (
        "uf", "municipal", "35")
    assert [(r["edicao"], r["valor"]) for r in ufm["resultados"]] == [(2024, 31.57), (2025, 31.57)]
    assert d["corte_alfabetizado"] == 743
    assert {f["parser"] for f in d["fontes"]} >= {"inep_ica_municipios", "inep_aeeb_agregados"}


def test_api_pacote_previa_aplicar_ler_e_desfazer_com_conflito(db, escola_completa,
                                                               cliente_global, rede):
    planilha = arq_mun_2025()
    p = _upload(cliente_global, rede.id, "previa", planilha)
    a = _upload(cliente_global, rede.id, "aplicar", planilha, previa_id=str(p.json()["id"]))
    assert a.status_code == 200, a.text
    conteudo = _pac()
    previa = _upload(cliente_global, rede.id, "previa", conteudo, nome=f"pacote_ica_aeeb_2025_{MUN}.zip")
    assert previa.status_code == 200, previa.text
    assert previa.json()["modo"] == "pacote_cli" and previa.json()["parser"] == "inep_aeeb_agregados"
    ok = _upload(cliente_global, rede.id, "aplicar", conteudo, nome="p.zip",
                 previa_id=str(previa.json()["id"]))
    assert ok.status_code == 200, ok.text
    # a auditoria guarda o sha256 do que foi CONFERIDO (o do pacote), além do da
    # entrada original do zip do INEP
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "indicador.importado",
        LogAuditoria.entidade_id == ok.json()["id"])).scalar_one()
    assert log.detalhes["modo"] == "pacote_cli"
    assert log.detalhes["pacote_sha256"] == hashlib.sha256(conteudo).hexdigest()
    assert log.detalhes["sha256"] == ok.json()["arquivo_sha256"] != log.detalhes["pacote_sha256"]
    secretaria = _cliente(db, "sec@aeeb.gov", cargo="coordenador", rede_id=rede.id)
    d = secretaria.get(f"/api/v1/redes/{rede.id}/indicadores/ica").json()
    assert d["uf_municipal"]["resultados"][0]["valor"] == 31.57
    assert d["territorios"][0]["media_lp"][0]["valor"] == 726.48
    # importar/desfazer continua só do admin global
    assert _upload(secretaria, rede.id, "previa", conteudo).status_code == 403
    lista = cliente_global.get(f"/api/v1/redes/{rede.id}/indicadores/importacoes").json()
    bloqueada = next(i for i in lista if i["id"] == a.json()["id"])
    assert bloqueada["bloqueada_por"] == ok.json()["id"]
    r = cliente_global.post(f"/api/v1/redes/{rede.id}/indicadores/importacoes/"
                            f"{a.json()['id']}/desfazer")
    assert r.status_code == 400 and f"desfaça antes a #{ok.json()['id']}" in r.json()["detail"]
    adulterado = _pacote_mexido(conteudo, csv=lambda d: d.replace(b"30.20", b"40.20"))
    r = _upload(cliente_global, rede.id, "previa", adulterado, nome="p.zip")
    assert r.status_code == 400 and "sha256 diferente" in r.json()["detail"]


# --- O mesmo fluxo num PostgreSQL de verdade ---------------------------------------

from tests.test_migracoes_postgres import engine_postgres  # noqa: E402,F401


@pytest.mark.postgres
def test_pacote_no_postgres_aplica_e_desfaz_pelo_id(engine_postgres):
    from sqlalchemy.orm import sessionmaker

    from app.core.migracoes import aplicar_migracoes

    aplicar_migracoes(engine_postgres)
    db = sessionmaker(bind=engine_postgres)()
    try:
        rede_pg = Rede(nome="Rede Sintética PG", uf="SP", codigo_ibge=MUN, status="ativa")
        db.add(rede_pg)
        db.commit()
        a = _aplicar(db, rede_pg, _pac(2024))
        _aplicar(db, rede_pg, arq_mun_2025())
        b = _aplicar(db, rede_pg, _pac(2025))
        assert _valores(db)[("municipio", "percentual_alfabetizado", 2025)] == (30, 30.2)
        with pytest.raises(ImportacaoRecusada):
            pipeline.desfazer(db, rede_pg, a["id"], usuario_id=None)   # a planilha viu 2024
        db.rollback()
        pipeline.desfazer(db, rede_pg, b["id"], usuario_id=None)
        db.commit()
        assert _valores(db)[("municipio", "percentual_alfabetizado", 2025)] == (30, None)
    finally:
        db.close()
