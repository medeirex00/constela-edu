"""Regressão G_INDICADORES-1: o número OFICIAL de uma escola não some da tela quando um
arquivo MAIS NOVO (ou uma retificação) não traz a escola.

O pipeline aplica a precedência número a número e não apaga o número de uma escola que
o arquivo novo não traz: o número gravado pela importação anterior continua no banco,
com a fonte dela. A consulta conferia a escola só contra o arquivo mais novo da edição
e escondia esse número com o motivo falso "fora do arquivo" (a cobertura também perdia
a escola). Agora a escola é conferida contra a importação aplicada que TEM a linha
dela: só fica "fora do arquivo" quando nenhuma importação da edição a trouxe.

Tudo SINTÉTICO (as fábricas dos testes da E6a e da E4/E5: município, INEPs, nomes e
números inventados).
"""
from sqlalchemy import select

from app.models import Escola, ResultadoAvaliacao
from app.services.indicadores import consulta_ideb, consulta_saresp, preparar
from tests.test_indicadores_ideb import (_ALFA_2025, AGORA, ALFA, BETA, GAMA, MUN, _aplicar,
                                         _valores, planilha, zip_ideb)
from tests.test_indicadores_ideb_consulta import rede  # noqa: F401 — fixture
from tests.test_indicadores_saresp import _ESCOLAS_IEE, _iee
from tests.test_indicadores_saresp_consulta import LM_A, NOME_IEE_25
from tests.test_indicadores_saresp_consulta import _edicao as _edicao_saresp
from tests.test_indicadores_saresp_consulta import _escola as _escola_saresp
from tests.test_indicadores_saresp_consulta import _importar as _importar_seduc
from tests.test_indicadores_saresp_consulta import rede as rede_saresp  # noqa: F401 — fixture

BETA_INEP = "35990102"


def _pacote(tmp_path, xlsx, nome_zip, nome_inep):
    caminho = tmp_path / nome_zip
    caminho.write_bytes(zip_ideb(xlsx, nome=nome_inep))
    return preparar.preparar_ideb(codigo_ibge=MUN, zip_local=caminho, agora=AGORA,
                                  url="https://exemplo.invalido/ideb_sintetico.zip").pacote


def _pacote_2023(tmp_path, escolas=(ALFA, BETA)):
    return _pacote(tmp_path, planilha(list(escolas)), "a23.zip",
                   "divulgacao_anos_iniciais_escolas_2023")


def _pacote_2025_sem_a_beta(tmp_path):
    alfa25 = {**ALFA, "valores": {**ALFA["valores"], **_valores(_ALFA_2025, {})}}
    return _pacote(tmp_path, planilha([alfa25], edicoes=(2019, 2021, 2023, 2025),
                                      metas=(2019, 2021)),
                   "a25.zip", "divulgacao_anos_iniciais_escolas_2025")


def _linha(d, nome):
    return next(x for x in d["escolas"] if x["nome"] == nome)


def _ed(linha, edicao):
    return next(x for x in linha["serie"] if x["edicao"] == edicao)


def _cob(d, edicao):
    return next(c for c in d["cobertura"] if c["edicao"] == edicao)


def _conferir_beta_2019_com_a_fonte_de_2023(db, rede, a23):
    db.expire_all()
    beta_id = db.execute(select(Escola.id).where(Escola.codigo_inep == BETA_INEP)).scalar_one()
    no_banco = db.execute(select(ResultadoAvaliacao).where(
        ResultadoAvaliacao.escola_id == beta_id, ResultadoAvaliacao.edicao == 2019,
        ResultadoAvaliacao.indicador == "ideb")).scalar_one()
    assert (no_banco.valor, no_banco.importacao_id) == (1.5, a23["id"])

    d = consulta_ideb.ideb_da_rede(db, rede)
    b19 = _ed(_linha(d, "EMEF Sintética Beta"), 2019)
    assert b19["ideb"] is not None and b19["ideb"]["valor"] == 1.5, b19["motivo"]
    assert b19["ideb"]["fonte_id"] == a23["id"]
    assert b19["motivo"] is None and b19["tem_ideb"] is True
    # N, P e aprovação da linha dela no arquivo de 2023 (a meta de 2019 é "-": ausência).
    assert b19["nota_n"]["valor"] == 2.164903 and b19["nota_n"]["fonte_id"] == a23["id"]
    assert b19["rendimento_p"]["valor"] == 0.608426
    assert b19["aprovacao"]["anos_iniciais"]["valor"] == 34.6
    assert b19["meta"] is not None and b19["meta"]["valor"] is None
    cob19 = _cob(d, 2019)
    assert cob19["com_ideb"] == 2                                    # ALFA e BETA
    assert "EMEF Sintética Beta" not in {x["nome"] for x in cob19["sem_linha_no_arquivo"]}
    # 2025 só está no arquivo novo, que não tem a BETA: aí, sim, "fora do arquivo".
    b25 = _ed(_linha(d, "EMEF Sintética Beta"), 2025)
    assert b25["ideb"] is None and b25["motivo"] == "fora_do_arquivo"
    assert "EMEF Sintética Beta" in {x["nome"] for x in _cob(d, 2025)["sem_linha_no_arquivo"]}
    assert _ed(_linha(d, "EMEF Sintética Alfa"), 2025)["ideb"]["valor"] == 1.9
    return d


def test_ideb_2023_depois_2025_sem_a_escola_mantem_o_numero_oficial_de_2023(db, rede, tmp_path):
    _, a23 = _aplicar(db, rede, _pacote_2023(tmp_path))
    _aplicar(db, rede, _pacote_2025_sem_a_beta(tmp_path))
    _conferir_beta_2019_com_a_fonte_de_2023(db, rede, a23)


def test_ideb_2025_depois_2023_na_ordem_inversa_mostra_o_mesmo(db, rede, tmp_path):
    _aplicar(db, rede, _pacote_2025_sem_a_beta(tmp_path))
    _, a23 = _aplicar(db, rede, _pacote_2023(tmp_path))
    _conferir_beta_2019_com_a_fonte_de_2023(db, rede, a23)


def test_ideb_codigo_trocado_depois_pede_reimportar_pelo_arquivo_que_tem_a_linha(
        db, rede, tmp_path):
    """O código novo da BETA (o da GAMA, que só o arquivo de 2023 traz) está no arquivo
    que tem a linha: nenhum número misturado e o motivo pede a reimportação — não "fora
    do arquivo" só porque o arquivo mais novo não traz a linha."""
    _aplicar(db, rede, _pacote_2023(tmp_path, (ALFA, BETA, GAMA)))
    _aplicar(db, rede, _pacote_2025_sem_a_beta(tmp_path))
    beta = db.execute(select(Escola).where(Escola.codigo_inep == BETA_INEP)).scalar_one()
    beta.codigo_inep = "35990103"
    db.commit()
    db.expire_all()
    d = consulta_ideb.ideb_da_rede(db, rede)
    b19 = _ed(_linha(d, "EMEF Sintética Beta"), 2019)
    assert all(b19[c] is None for c in ("ideb", "saeb_lp", "saeb_mt", "nota_n",
                                        "rendimento_p", "meta"))
    assert b19["motivo"] == "codigo_inep_alterado"


def test_saresp_retificacao_sem_a_escola_mantem_o_numero_da_1a_versao(db, rede_saresp):
    v1 = _importar_seduc(db, rede_saresp, _iee(), NOME_IEE_25, lm=LM_A)
    # "Retificação" da MESMA edição: a ALFA com um número corrigido, a BETA ausente.
    so_alfa = []
    for linha in _ESCOLAS_IEE:
        if linha[4] == "35990001":
            linha = list(linha)
            linha[6] = "148,9"
            so_alfa.append(tuple(linha))
        elif linha[4] != "35990002":
            so_alfa.append(linha)
    _importar_seduc(db, rede_saresp, _iee(so_alfa),
                    "Indice de Excelencia Educacional 2025-2026_1.csv",
                    lm="Tue, 20 Jan 2026 09:00:00 GMT")
    db.expire_all()
    beta_id = db.execute(select(Escola.id).where(Escola.codigo_inep == "35990002")).scalar_one()
    no_banco = db.execute(select(ResultadoAvaliacao).where(
        ResultadoAvaliacao.escola_id == beta_id, ResultadoAvaliacao.edicao == 2025,
        ResultadoAvaliacao.etapa == "5_ano", ResultadoAvaliacao.componente == "portugues")
        ).scalar_one()
    assert (no_banco.valor, no_banco.importacao_id) == (201.7, v1["id"])

    d = consulta_saresp.saresp_da_rede(db, rede_saresp)
    b25 = _edicao_saresp(_escola_saresp(d, "EMEF Sintética Beta"), 2025)
    lp = b25["proficiencia"]["5_ano"]["lp"]
    assert lp is not None and lp["valor"] == 201.7, b25["motivo"]
    assert lp["fonte"]["importacao_id"] == v1["id"]
    assert b25["motivo"] is None and b25["tem_resultado"] is True
    assert b25["iee"] is not None and b25["iee"]["valor"] is not None
    cob = next(c for c in d["cobertura"] if c["edicao"] == 2025)
    assert "EMEF Sintética Beta" not in {x["nome"] for x in cob["sem_resultado"]}
    # A ALFA segue a retificação.
    a25 = _edicao_saresp(_escola_saresp(d, "EMEF Sintética Alfa"), 2025)
    assert a25["proficiencia"]["2_ano"]["lp"]["valor"] == 148.9
