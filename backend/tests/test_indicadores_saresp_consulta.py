"""Leitura do SARESP oficial da rede (etapa E5): ``GET /redes/{id}/indicadores/saresp``.

O que a API garante (plano, 4.6, 4.8, 4.9, 5.1):

* permissões: a Secretaria da PRÓPRIA rede e o admin global leem; Secretaria de
  outra rede, coordenador e professor de escola recebem 403;
* a rede municipal por série × componente, 2022–2025, e o Estado na MESMA rede
  (redes municipais); a rede estadual vem à parte, rotulada como outra rede;
* cada número com a fonte: arquivo, edição, data do arquivo (Last-Modified
  informado — o CSV não tem data interna) e data da importação;
* por escola, a proficiência OFICIAL do IEE com participação, TPS, IEE, meta e
  cumprimento, em ordem de nome; a média SEM proveniência oficial (a calculada pelo
  Constela que a D2 não substituiu) vem SEPARADA, como estimativa;
* cobertura: sem resultado ≠ 0 (com o motivo), escola sem INEP = pendência de
  cadastro, escola do arquivo fora do cadastro (pelo código);
* código INEP cadastrado ou trocado DEPOIS da importação: nenhum número misturado
  (nem de outra linha do arquivo), motivo "reimporte" e a lista "fora do cadastro"
  conferida com o cadastro de hoje; D2 "não" = motivo próprio, nunca "não divulgado";
* níveis "a confirmar" (nenhum corte inventado) e a quebra do 2º ano 2022→2023.

FIXTURES SINTÉTICAS no layout real dos CSVs da SEDUC (as fábricas do teste da E4).
Nenhum número, código, nome ou data aqui é da SEDUC — o repositório é público
(decisão D13): os valores são INVENTADOS e longe dos oficiais; o município, os CIEs e
os INEPs são fictícios.
"""
import codecs

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_senha
from app.main import app
from app.models import Escola, Rede, ResultadoAvaliacao, Usuario
from app.services.indicadores import consulta_saresp, escalas, pipeline_seduc
from tests.test_indicadores_saresp import (_COMP, _ESCOLAS_IEE, _PERIODOS, CODMUN, MUN,
                                           _calculadas, _iee, _municipio)

# --- Fixtures (todas INVENTADAS) ----------------------------------------------

# Data do arquivo (Last-Modified) e endereço FICTÍCIOS.
LM_A = "Mon, 12 Jan 2026 09:00:00 GMT"
LM_B = "Mon, 01 Dec 2025 09:00:00 GMT"
URL = "https://dados.educacao.sp.gov.br/exemplo-sintetico.csv"

# Rede municipal (DEPADM 2) do município sintético: {ano: (2º LP, 2º MT, 5º LP, 5º MT)}.
# Valores longe da escala real das médias (de propósito). "" = MEDPROF vazio.
_REDE = {2022: ("121,3", "118,9", "241,6", "252,7"),
         2023: ("133,8", "124,4", "238,3", "256,1"),
         2024: ("129,6", "", "246,9", "258,8"),
         2025: ("137,1", "131,2", "249,4", "263,3")}
# Estado, redes municipais (DEPADM 2) e rede estadual (DEPADM 1, só 2025, 2 números).
_ESTADO_MUN = {2022: ("126,6", "122,3", "236,4", "248,1"),
               2023: ("131,7", "125,8", "239,7", "251,6"),
               2024: ("135,4", "128,6", "243,2", "255,9"),
               2025: ("139,2", "133,9", "247,8", "259,4")}
_ESTADO_EST_2025 = (("2º Ano EF", "1", "128,8"), ("5º Ano EF", "2", "268,2"))
_CHAVES = (("2º Ano EF", "1"), ("2º Ano EF", "2"), ("5º Ano EF", "1"), ("5º Ano EF", "2"))


def _arq_municipio(ano: int) -> bytes:
    linhas = [("2", CODMUN, "CIDADE SINTETICA", serie, "9", comp, med)
              for (serie, comp), med in zip(_CHAVES, _REDE[ano])]
    return _municipio(linhas=linhas)


def _arq_instancia(ano: int) -> bytes:
    cab = "DEPADM;DEPBOL;NOMEDEPBOL;CODRMET;REGIAOMETROPOLITANA;SERIE_ANO;COD_PER;PERIODO;CO_COMP;DS_COMP;MEDPROF"
    linhas = [("2", serie, comp, med) for (serie, comp), med in zip(_CHAVES, _ESTADO_MUN[ano])]
    if ano == 2025:
        linhas += [("1", serie, comp, med) for serie, comp, med in _ESTADO_EST_2025]
    corpo = []
    for dep, serie, comp, med in linhas:
        nome_rede = "Rede Estadual" if dep == "1" else "Rede Municipal"
        corpo.append(";".join([dep, dep, nome_rede, "9", "ESTADO", serie, "9", _PERIODOS["9"],
                               comp, _COMP[comp], med]))
    return codecs.BOM_UTF8 + ("\r\n".join([cab, *corpo]) + "\r\n").encode("utf-8")


def _escolas_2024():
    """O IEE da edição anterior: a BETA sem nenhuma proficiência divulgada (só
    participação e IEE) e a ALFA sem o 5º ano de LP — nada além de células vazias."""
    saida = []
    for linha in _ESCOLAS_IEE:
        linha = list(linha)
        if linha[4] == "35990002":
            linha[6:10] = ["", "", "", ""]
        if linha[4] == "35990001":
            linha[8] = ""
        saida.append(tuple(linha))
    return saida


NOME_IEE_25 = "Indice de Excelencia Educacional 2025-2026_0.csv"
NOME_IEE_24 = "Indice de Excelencia Educacional 2024-2025.csv"


@pytest.fixture()
def rede(db):
    r = Rede(nome="Rede Sintética", uf="SP", codigo_ibge=MUN, codigo_municipio_estadual=CODMUN,
             status="ativa")
    outra = Rede(nome="Rede Vizinha Fictícia", uf="SP", codigo_ibge="3599998", status="ativa")
    db.add_all([r, outra])
    db.flush()
    # Fora da ordem alfabética de propósito: a API ordena por NOME.
    db.add_all([
        Escola(nome="ESCOLA SINTETICA GAMA", ano_letivo_ativo=2026, rede_id=r.id),  # sem INEP
        Escola(nome="EMEF Sintética Delta", ano_letivo_ativo=2026, rede_id=r.id,
               codigo_inep="35990004"),                      # tem INEP, fora do arquivo
        Escola(nome="EMEF Sintética Beta", ano_letivo_ativo=2026, rede_id=r.id,
               codigo_inep="35990002"),
        Escola(nome="EMEF Sintética Alfa", ano_letivo_ativo=2026, rede_id=r.id,
               codigo_inep="35990001"),
        Escola(nome="EMEF Sintética Épsilon (desativada)", ano_letivo_ativo=2026,
               rede_id=r.id, status="inativa"),               # inativa sem número: fora
        # O homônimo da ALFA, numa OUTRA rede: nunca aparece nesta.
        Escola(nome="ESCOLA SINTETICA ALFA", ano_letivo_ativo=2026, rede_id=outra.id,
               codigo_inep="35880001"),
    ])
    db.commit()
    return r


def _importar(db, rede, conteudo, nome, *, lm=LM_A, **kw):
    p = pipeline_seduc.previa(db, rede, conteudo, nome, usuario_id=None, url_origem=URL,
                              last_modified_origem=lm)
    db.commit()
    a = pipeline_seduc.aplicar(db, rede, p["id"], conteudo, nome, usuario_id=None, **kw)
    db.commit()
    return a


def _importar_tudo(db, rede, *, iee=True, territorio=True, substituir=None):
    if territorio:
        for ano in sorted(_REDE):
            _importar(db, rede, _arq_municipio(ano),
                      f"Proficiência do SARESP por Municipio de {ano}_0.csv")
            _importar(db, rede, _arq_instancia(ano),
                      f"Proficiência do SARESP por instância de {ano}_0.csv", lm=LM_B)
    if iee:
        _importar(db, rede, _iee(_escolas_2024(), ano=2024), NOME_IEE_24, lm=LM_B)
        _importar(db, rede, _iee(), NOME_IEE_25, substituir_calculadas=substituir)


def _cliente(db, email: str, **campos) -> TestClient:
    db.add(Usuario(nome=email, email=email, senha_hash=hash_senha("s3nh4consulta"), **campos))
    db.commit()
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", data={"username": email, "password": "s3nh4consulta"})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _url(rede_id) -> str:
    return f"/api/v1/redes/{rede_id}/indicadores/saresp"


def _serie(territorio: dict, etapa: str, componente: str) -> list[tuple]:
    s = next(x for x in territorio["series"] if (x["etapa"], x["componente"]) == (etapa, componente))
    return [(n["edicao"], n["valor"], n["motivo_ausencia"]) for n in s["numeros"]]


def _escola(dados: dict, nome: str) -> dict:
    return next(linha for linha in dados["escolas"]["linhas"] if linha["nome"] == nome)


def _edicao(linha: dict, edicao: int) -> dict:
    return next(e for e in linha["por_edicao"] if e["edicao"] == edicao)


# =============================================================================
# Permissões
# =============================================================================

def test_permissoes_secretaria_da_rede_e_admin_leem_os_demais_403(db, escola_completa,
                                                                  cliente_global, rede):
    escola = escola_completa["escola"]
    outra = db.execute(select(Rede).where(Rede.nome == "Rede Vizinha Fictícia")).scalar_one()
    secretaria = _cliente(db, "sec@consulta.gov", cargo="coordenador", rede_id=rede.id)
    secretaria_outra = _cliente(db, "sec@vizinha.gov", cargo="coordenador", rede_id=outra.id)
    coordenador = _cliente(db, "coord@consulta.escola", cargo="coordenador", escola_id=escola.id)
    professor = _cliente(db, "prof@consulta.escola", cargo="professor", escola_id=escola.id)

    assert cliente_global.get(_url(rede.id)).status_code == 200
    assert secretaria.get(_url(rede.id)).status_code == 200
    for quem in (secretaria_outra, coordenador, professor):
        assert quem.get(_url(rede.id)).status_code == 403
    assert cliente_global.get(_url(999999)).status_code == 404
    # A Secretaria lê, mas não importa (só o admin global, até a D4).
    r = secretaria.post(f"{_url(rede.id)}/previa", files={"arquivo": (NOME_IEE_25, _iee())})
    assert r.status_code == 403


# =============================================================================
# Rede municipal × Estado (mesma rede) × rede estadual (outra rede)
# =============================================================================

def test_rede_municipal_por_serie_e_componente_com_o_estado_na_mesma_rede(db, escola_completa,
                                                                          cliente_global, rede):
    _importar_tudo(db, rede, iee=False)
    d = cliente_global.get(_url(rede.id)).json()

    assert d["tem_dados"] and d["pendencias"] == [] and d["edicoes_rede"] == [2022, 2023, 2024, 2025]
    assert d["municipio"] == "Cidade Sintetica" and d["codigo_ibge"] == MUN
    chaves = [t["chave"] for t in d["territorios"]]
    assert chaves == ["rede_municipal", "estado_redes_municipais", "rede_estadual_no_municipio",
                      "estado_rede_estadual"]                         # ordem FIXA, não por valor
    mun, est_mun, mun_est, est_est = d["territorios"]
    assert (mun["abrangencia"], mun["rede_ensino"], mun["mesma_rede"]) == ("municipio", "municipal", True)
    assert mun["rotulo"] == "Cidade Sintetica — rede municipal"
    assert (est_mun["abrangencia"], est_mun["rede_ensino"], est_mun["mesma_rede"]) == ("uf", "municipal", True)
    assert est_mun["rotulo"] == "Estado de São Paulo — redes municipais"
    # A rede estadual é OUTRA rede: vem à parte e rotulada.
    assert (mun_est["mesma_rede"], est_est["mesma_rede"]) == (False, False)
    assert "rede estadual" in mun_est["rotulo"] and "rede estadual" in est_est["rotulo"]

    assert _serie(mun, "2_ano", "lp") == [(2022, 121.3, None), (2023, 133.8, None),
                                          (2024, 129.6, None), (2025, 137.1, None)]
    assert _serie(mun, "5_ano", "mt") == [(2022, 252.7, None), (2023, 256.1, None),
                                          (2024, 258.8, None), (2025, 263.3, None)]
    # MEDPROF vazio = sem resultado, com o motivo — nunca 0.
    assert (2024, None, "nao_divulgado") in _serie(mun, "2_ano", "mt")
    assert _serie(est_mun, "5_ano", "lp")[-1] == (2025, 247.8, None)
    # A rede estadual no município não tem 2º nem 5º ano no arquivo: vazio, não 0.
    assert mun_est["tem_dados"] is False and all(s["numeros"] == [] for s in mun_est["series"])
    assert _serie(est_est, "2_ano", "lp") == [(2025, 128.8, None)]
    assert _serie(est_est, "2_ano", "mt") == []

    # Proveniência: fonte, edição e data do arquivo em CADA número.
    for t in (mun, est_mun):
        for s in t["series"]:
            for n in s["numeros"]:
                f = n["fonte"]
                assert f["edicao_arquivo"] == n["edicao"]
                assert f["arquivo_nome"].endswith(f"de {n['edicao']}_0.csv")
                assert f["importado_em"] and f["fonte_nome"].startswith("SEDUC-SP")
                assert f["url_origem"] == URL and f["licenca"]
                assert f["data_arquivo_origem"] == "last_modified"
                assert f["data_arquivo"] == ("2026-01-12" if t is mun else "2025-12-01")
                assert n["unidade"] == "escala_saresp"
                assert n["casas_decimais"] == (None if n["valor"] is None else 1)
    assert {f["parser"] for f in d["fontes"]} == {"seduc_saresp_municipio", "seduc_saresp_instancia"}


def test_niveis_a_confirmar_e_quebra_do_2o_ano_entre_2022_e_2023(db, escola_completa,
                                                                cliente_global, rede):
    _importar_tudo(db, rede, iee=False)
    d = cliente_global.get(_url(rede.id)).json()
    quebras = {(q["etapa"], q["de"], q["para"]) for q in d["quebras_de_escala"]}
    assert ("2_ano", 2022, 2023) in quebras
    assert not any(q["etapa"] == "5_ano" for q in d["quebras_de_escala"])
    niveis = d["niveis"]
    assert niveis["edicoes_a_confirmar"] == [2022, 2023, 2024, 2025]
    assert all(c["situacao"] == "a_confirmar" and c["basico"] is c["adequado"] is c["avancado"] is None
               for c in niveis["cortes"])
    assert [r["rotulo"] for r in niveis["rotulos"]] == ["Abaixo do Básico", "Básico", "Adequado",
                                                         "Avançado"]
    # Nenhuma média recebe nível nem distância até o Adequado sem corte confirmado.
    for t in d["territorios"]:
        for s in t["series"]:
            for n in s["numeros"]:
                assert n["nivel"]["situacao"] == "a_confirmar"
                assert n["nivel"]["nivel"] is None and n["nivel"]["distancia_adequado"] is None
    assert "comparável ao ICA" in d["avisos"]["segundo_ano_x_ica"]


# =============================================================================
# Por escola: oficial (IEE), estimativa separada, cobertura
# =============================================================================

def test_escolas_por_nome_com_proficiencia_oficial_participacao_tps_iee_e_meta(
        db, escola_completa, cliente_global, rede):
    _importar_tudo(db, rede, territorio=False)
    d = cliente_global.get(_url(rede.id)).json()

    assert d["escolas"]["edicoes"] == [2025, 2024]
    nomes = [linha["nome"] for linha in d["escolas"]["linhas"]]
    assert nomes == ["EMEF Sintética Alfa", "EMEF Sintética Beta", "EMEF Sintética Delta",
                     "ESCOLA SINTETICA GAMA"]          # por NOME; inativa sem número e a de outra rede fora
    alfa = _escola(d, "EMEF Sintética Alfa")
    a25 = _edicao(alfa, 2025)
    assert a25["proficiencia"]["2_ano"]["lp"]["valor"] == 148.3
    assert a25["proficiencia"]["5_ano"]["mt"]["valor"] == 196.8
    assert a25["proficiencia"]["5_ano"]["mt"]["casas_decimais"] == 1
    assert a25["proficiencia"]["5_ano"]["mt"]["nivel"]["situacao"] == "a_confirmar"
    assert (a25["participacao"]["2_ano"]["valor"], a25["participacao"]["5_ano"]["valor"]) == (72.4, 68.9)
    assert (a25["tps"]["valor"], a25["iee"]["valor"], a25["meta"]["valor"], a25["icm"]["valor"]) == (
        1, 5.12, 5.46, 0)
    assert a25["iee"]["casas_decimais"] == 2
    f = a25["proficiencia"]["2_ano"]["lp"]["fonte"]
    assert (f["arquivo_nome"], f["edicao_arquivo"], f["data_arquivo"]) == (NOME_IEE_25, 2025,
                                                                         "2026-01-12")
    assert a25["iee"]["fonte"]["parser"] == "seduc_iee"
    # 2024: a célula vazia do arquivo é ausência (não 0) e a edição é a certa.
    a24 = _edicao(alfa, 2024)
    assert a24["proficiencia"]["5_ano"]["lp"]["valor"] is None
    assert a24["proficiencia"]["5_ano"]["lp"]["motivo_ausencia"] == "nao_divulgado"
    assert a24["proficiencia"]["2_ano"]["lp"]["fonte"]["arquivo_nome"] == NOME_IEE_24
    # BETA: o 2º ano sem proficiência no arquivo é "não divulgado", nunca 0.
    beta = _edicao(_escola(d, "EMEF Sintética Beta"), 2025)
    assert beta["proficiencia"]["2_ano"]["lp"]["valor"] is None
    assert beta["proficiencia"]["2_ano"]["lp"]["motivo_ausencia"] == "nao_divulgado"
    assert beta["participacao"]["2_ano"]["valor"] is None
    # Sem INEP: pendência de cadastro, sem número nenhum.
    gama = _escola(d, "ESCOLA SINTETICA GAMA")
    assert gama["pendencia"] == "codigo_inep" and gama["codigo_inep"] is None
    assert not any(e["no_arquivo"] for e in gama["por_edicao"])
    assert d["estimativas"] == []


def test_estimativa_do_constela_vem_separada_e_nunca_misturada_com_a_oficial(
        db, escola_completa, cliente_global, rede):
    _calculadas(db, rede)                        # médias do 5º ano 2025 sem proveniência oficial
    _importar_tudo(db, rede, territorio=False, substituir=False)      # D2: "não" (mantém)
    d = cliente_global.get(_url(rede.id)).json()

    est = d["estimativas"]
    assert len(est) == 4
    assert {(e["nome"], e["edicao"], e["etapa"], e["componente"], e["valor"]) for e in est} == {
        ("EMEF Sintética Alfa", 2025, "5_ano", "lp", 184.6),
        ("EMEF Sintética Alfa", 2025, "5_ano", "mt", 198.3),
        ("EMEF Sintética Beta", 2025, "5_ano", "lp", 200.1),
        ("EMEF Sintética Beta", 2025, "5_ano", "mt", 190.0)}
    assert all(e["fonte_texto"] == "SARESP 2025 — calculo_sintetico.csv" for e in est)
    # Na tabela OFICIAL, o 5º ano de 2025 dessas escolas fica SEM número (a estimativa
    # não entra lá) e a célula diz POR QUÊ: o oficial está no arquivo, mas não foi
    # gravado — a estimativa foi mantida (D2). Nunca "não divulgado". O 2º ano oficial
    # aparece normalmente.
    alfa = _edicao(_escola(d, "EMEF Sintética Alfa"), 2025)
    for comp in ("lp", "mt"):
        cel = alfa["proficiencia"]["5_ano"][comp]
        assert cel["valor"] is None and cel["motivo_ausencia"] == "estimativa_mantida_d2"
        assert cel["fonte"]["arquivo_nome"] == NOME_IEE_25
        assert cel["nivel"]["nivel"] is None
    assert alfa["proficiencia"]["2_ano"]["lp"]["valor"] == 148.3
    assert alfa["tem_resultado"] is True and alfa["motivo"] is None
    oficiais = {n["valor"] for linha in d["escolas"]["linhas"] for e in linha["por_edicao"]
                for et in e["proficiencia"].values() for n in et.values() if n}
    assert not oficiais & {184.6, 198.3, 200.1, 190.0}
    beta_linha = _escola(d, "EMEF Sintética Beta")
    assert beta_linha["tem_estimativa"] is True
    # A estimativa é só de 2025: a frase "há estimativa" vale POR EDIÇÃO.
    assert _edicao(beta_linha, 2025)["tem_estimativa"] is True
    assert _edicao(beta_linha, 2024)["tem_estimativa"] is False
    # BETA 2025: 2º ano não divulgado + 5º ano com a estimativa mantida → o motivo da
    # escola é o da D2 (o arquivo TEM o 5º ano dela), na tabela e na cobertura.
    assert _edicao(beta_linha, 2025)["motivo"] == "estimativa_mantida_d2"
    cob = next(c for c in d["cobertura"] if c["edicao"] == 2025)
    beta = next(s for s in cob["sem_resultado"] if s["nome"] == "EMEF Sintética Beta")
    assert beta["tem_estimativa"] is True and beta["motivo"] == "estimativa_mantida_d2"
    cob24 = next(c for c in d["cobertura"] if c["edicao"] == 2024)
    beta24 = next(s for s in cob24["sem_resultado"] if s["nome"] == "EMEF Sintética Beta")
    assert beta24["tem_estimativa"] is False and beta24["motivo"] == "nao_divulgado"

    # D2 "sim" numa importação nova: a oficial substitui a estimativa, que some da lista.
    _importar(db, rede, _iee(), NOME_IEE_25, substituir_calculadas=True)
    d = cliente_global.get(_url(rede.id)).json()
    assert d["estimativas"] == []
    alfa = _edicao(_escola(d, "EMEF Sintética Alfa"), 2025)
    assert alfa["proficiencia"]["5_ano"]["lp"]["valor"] == 187.2


def test_cobertura_sem_resultado_com_motivo_sem_inep_e_fora_do_cadastro(db, escola_completa,
                                                                        cliente_global, rede):
    _importar_tudo(db, rede, territorio=False)
    d = cliente_global.get(_url(rede.id)).json()
    cob = {c["edicao"]: c for c in d["cobertura"]}
    assert sorted(cob) == [2024, 2025]

    c25 = cob[2025]
    assert (c25["total_escolas"], c25["com_resultado"]) == (4, 2)
    assert [(s["nome"], s["motivo"]) for s in c25["sem_resultado"]] == [
        ("EMEF Sintética Delta", "fora_do_arquivo")]
    assert [s["nome"] for s in c25["sem_inep"]] == ["ESCOLA SINTETICA GAMA"]
    # A escola do arquivo sem escola no cadastro, pelo CÓDIGO (nunca casada pelo nome).
    assert [(f["codigo_inep"], f["cie"]) for f in c25["fora_do_cadastro"]] == [("35990003", "990003")]
    assert c25["fonte"]["arquivo_nome"] == NOME_IEE_25
    # 2024: a BETA está no arquivo, mas sem proficiência divulgada — motivo da fonte.
    c24 = cob[2024]
    assert c24["com_resultado"] == 1
    assert [(s["nome"], s["motivo"]) for s in c24["sem_resultado"]] == [
        ("EMEF Sintética Beta", "nao_divulgado"), ("EMEF Sintética Delta", "fora_do_arquivo")]


# --- O cadastro mudou DEPOIS da importação --------------------------------------

def _escola_do_banco(db, nome: str) -> Escola:
    return db.execute(select(Escola).where(Escola.nome == nome)).scalar_one()


def _inep(cliente, escola: Escola, codigo: str) -> None:
    """Grava o código INEP como o admin global faz (Gestão de redes)."""
    r = cliente.patch(f"/api/v1/redes/escolas/{escola.id}", json={"codigo_inep": codigo})
    assert r.status_code == 200, r.text


def test_inep_cadastrado_depois_da_importacao_pede_reimportar_e_sai_do_fora_do_cadastro(
        db, escola_completa, cliente_global, rede):
    _importar_tudo(db, rede, territorio=False)
    # O passo que a cobertura pede: cadastrar o código da escola do arquivo (35990003).
    _inep(cliente_global, _escola_do_banco(db, "ESCOLA SINTETICA GAMA"), "35990003")
    d = cliente_global.get(_url(rede.id)).json()
    for edicao in (2025, 2024):
        ed = _edicao(_escola(d, "ESCOLA SINTETICA GAMA"), edicao)
        # Não é "fora do arquivo" (o código ESTÁ no arquivo): falta reimportar.
        assert (ed["no_arquivo"], ed["motivo"]) == (False, "cadastrado_depois_da_importacao")
        c = next(x for x in d["cobertura"] if x["edicao"] == edicao)
        assert ("ESCOLA SINTETICA GAMA", "cadastrado_depois_da_importacao") in [
            (s["nome"], s["motivo"]) for s in c["sem_resultado"]]
        assert c["sem_inep"] == []
        # O código agora é de uma escola do cadastro: sai de "fora do cadastro".
        assert "35990003" not in [f["codigo_inep"] for f in c["fora_do_cadastro"]]

    # Reimportar a edição resolve: a GAMA casa pelo código e ganha os números do arquivo.
    _importar(db, rede, _iee(), NOME_IEE_25)
    d = cliente_global.get(_url(rede.id)).json()
    g25 = _edicao(_escola(d, "ESCOLA SINTETICA GAMA"), 2025)
    assert g25["proficiencia"]["2_ano"]["lp"]["valor"] == 133.1 and g25["iee"]["valor"] == 4.5
    assert g25["motivo"] is None and g25["tem_resultado"] is True
    c25 = next(x for x in d["cobertura"] if x["edicao"] == 2025)
    assert c25["com_resultado"] == 3 and c25["fora_do_cadastro"] == []
    # A outra edição continua pedindo a SUA reimportação.
    assert _edicao(_escola(d, "ESCOLA SINTETICA GAMA"), 2024)["motivo"] == (
        "cadastrado_depois_da_importacao")


def test_inep_trocado_depois_da_importacao_nao_mistura_numeros_de_duas_escolas(
        db, escola_completa, cliente_global, rede):
    _importar_tudo(db, rede, territorio=False)
    alfa = _escola_do_banco(db, "EMEF Sintética Alfa")
    beta = _escola_do_banco(db, "EMEF Sintética Beta")
    for escola, codigo in ((alfa, ""), (beta, "35990001"), (alfa, "35990002")):   # troca
        _inep(cliente_global, escola, codigo)
    d = cliente_global.get(_url(rede.id)).json()
    for nome in ("EMEF Sintética Alfa", "EMEF Sintética Beta"):
        for edicao in (2025, 2024):
            ed = _edicao(_escola(d, nome), edicao)
            # NENHUM número: nem a proficiência gravada pela escola (linha do código
            # antigo) nem participação/IEE pelo código novo (outra linha do arquivo).
            assert all(ed["proficiencia"][et][c] is None
                       for et in ("2_ano", "5_ano") for c in ("lp", "mt"))
            assert ed["participacao"] == {"2_ano": None, "5_ano": None}
            assert all(ed[k] is None for k in ("tps", "iee", "meta", "icm"))
            assert (ed["no_arquivo"], ed["motivo"]) == (False, "codigo_inep_alterado")
    c25 = next(x for x in d["cobertura"] if x["edicao"] == 2025)
    assert c25["com_resultado"] == 0
    assert {(s["nome"], s["motivo"]) for s in c25["sem_resultado"]} == {
        ("EMEF Sintética Alfa", "codigo_inep_alterado"),
        ("EMEF Sintética Beta", "codigo_inep_alterado"),
        ("EMEF Sintética Delta", "fora_do_arquivo")}
    assert [f["codigo_inep"] for f in c25["fora_do_cadastro"]] == ["35990003"]

    # Reimportar 2025: cada escola com a linha do SEU código, sem mistura.
    _importar(db, rede, _iee(), NOME_IEE_25)
    d = cliente_global.get(_url(rede.id)).json()
    a25 = _edicao(_escola(d, "EMEF Sintética Alfa"), 2025)      # agora 35990002
    assert a25["proficiencia"]["5_ano"]["lp"]["valor"] == 201.7 and a25["iee"]["valor"] == 6.04
    assert a25["proficiencia"]["2_ano"]["lp"]["motivo_ausencia"] == "nao_divulgado"
    assert a25["participacao"]["5_ano"]["valor"] == 73.2
    b25 = _edicao(_escola(d, "EMEF Sintética Beta"), 2025)       # agora 35990001
    assert b25["proficiencia"]["2_ano"]["lp"]["valor"] == 148.3 and b25["iee"]["valor"] == 5.12
    assert b25["participacao"]["2_ano"]["valor"] == 72.4
    # 2024 não foi reimportado: continua sem número e pedindo a reimportação.
    assert _edicao(_escola(d, "EMEF Sintética Alfa"), 2024)["motivo"] == "codigo_inep_alterado"


def test_inep_corrigido_para_codigo_fora_do_arquivo_descarta_os_numeros_antigos(
        db, escola_completa, cliente_global, rede):
    _importar_tudo(db, rede, territorio=False)
    _inep(cliente_global, _escola_do_banco(db, "EMEF Sintética Alfa"), "35990009")
    d = cliente_global.get(_url(rede.id)).json()
    a25 = _edicao(_escola(d, "EMEF Sintética Alfa"), 2025)
    # Os números gravados eram da linha 35990001: com o código novo, a escola não está
    # no arquivo — sem número, "fora do arquivo" (reimportar não traria nada).
    assert (a25["no_arquivo"], a25["motivo"]) == (False, "fora_do_arquivo")
    assert a25["proficiencia"]["2_ano"]["lp"] is None and a25["iee"] is None
    c25 = next(x for x in d["cobertura"] if x["edicao"] == 2025)
    # O código antigo continua no arquivo, agora sem escola no cadastro.
    assert [(f["codigo_inep"], f["cie"]) for f in c25["fora_do_cadastro"]] == [
        ("35990001", "990001"), ("35990003", "990003")]


def test_estimativas_em_ordem_alfabetica_sem_acento_e_sem_caixa(db, rede):
    """A mesma ordem da tabela por escola — não a do ponto de código ('Á' > 'Z' e
    minúscula depois de maiúscula). Nomes e números INVENTADOS."""
    from app.services import avaliacoes as svc

    av = svc.obter_avaliacao(db, "saresp")
    for i, nome in enumerate(("EMEF Zélia Fictícia", "emef bruno fictício",
                              "EMEF Álvaro Fictício")):
        e = Escola(nome=nome, ano_letivo_ativo=2026, rede_id=rede.id,
                   codigo_inep=f"3599007{i}")
        db.add(e)
        db.flush()
        db.add(ResultadoAvaliacao(avaliacao_id=av.id, edicao=2025, rede_id=rede.id,
                                  escola_id=e.id, codigo_inep=e.codigo_inep, etapa="5_ano",
                                  componente="portugues", indicador="proficiencia",
                                  valor=float(400 + i), unidade="escala_saresp",
                                  fonte="estimativa sintética"))
    db.commit()
    d = consulta_saresp.saresp_da_rede(db, rede)
    nomes = [e["nome"] for e in d["estimativas"]]
    assert nomes == ["EMEF Álvaro Fictício", "emef bruno fictício", "EMEF Zélia Fictícia"]
    assert nomes == [linha["nome"] for linha in d["escolas"]["linhas"] if linha["tem_estimativa"]]


def test_aviso_dos_niveis_acompanha_os_cortes_confirmados(monkeypatch):
    """Sem corte confirmado, o aviso diz que nenhum foi conferido; com um confirmado
    (valores INVENTADOS, fora de qualquer média dos arquivos da SEDUC), o aviso e a
    tabela mudam — sem a tela precisar mudar."""
    sem = consulta_saresp._niveis({2024})
    assert "ainda não foram conferidos" in sem["aviso"]
    monkeypatch.setitem(escalas.CORTES_SARESP, (2024, "5_ano", "lp"), escalas.CortesSaresp(
        edicao=2024, etapa="5_ano", componente="lp", basico=139, adequado=262, avancado=304,
        situacao=escalas.SITUACAO_CONFIRMADO, fonte="Fonte sintética de teste"))
    com = consulta_saresp._niveis({2024})
    corte = next(c for c in com["cortes"]
                 if (c["edicao"], c["etapa"], c["componente"]) == (2024, "5_ano", "lp"))
    assert (corte["situacao"], corte["basico"], corte["adequado"], corte["avancado"],
            corte["fonte"]) == ("confirmado", 139, 262, 304, "Fonte sintética de teste")
    assert "ainda não foram conferidos" not in com["aviso"]
    assert "só onde a tabela mostra o corte" in com["aviso"]
    assert com["edicoes_a_confirmar"] == [2022, 2023, 2024, 2025]   # 2024 ainda tem 3 a confirmar
    for chave in list(escalas.CORTES_SARESP):
        e, et, c = chave
        monkeypatch.setitem(escalas.CORTES_SARESP, chave, escalas.CortesSaresp(
            edicao=e, etapa=et, componente=c, basico=139, adequado=262, avancado=304,
            situacao=escalas.SITUACAO_CONFIRMADO, fonte="Fonte sintética de teste"))
    todos = consulta_saresp._niveis({2024})
    assert todos["edicoes_a_confirmar"] == [] and "a confirmar" not in todos["aviso"]


def test_sem_importacao_vem_vazio_e_nunca_zero(db, escola_completa, cliente_global, rede):
    d = cliente_global.get(_url(rede.id)).json()
    assert d["tem_dados"] is False and d["fontes"] == [] and d["edicoes_rede"] == []
    assert all(not t["tem_dados"] and all(s["numeros"] == [] for s in t["series"])
               for t in d["territorios"])
    assert d["escolas"]["edicoes"] == [] and d["cobertura"] == [] and d["estimativas"] == []
    assert [linha["nome"] for linha in d["escolas"]["linhas"]][0] == "EMEF Sintética Alfa"
    assert d["niveis"]["edicoes_a_confirmar"] == [2022, 2023, 2024, 2025]


def test_rede_sem_codigos_pede_o_cadastro_e_ainda_mostra_a_estimativa(db, escola_completa,
                                                                      cliente_global, rede):
    _calculadas(db, rede)
    rede.codigo_ibge = None
    rede.codigo_municipio_estadual = None
    db.commit()
    d = cliente_global.get(_url(rede.id)).json()
    assert d["pendencias"] == ["codigo_ibge", "codigo_municipio_estadual"]
    assert d["territorios"] == [] and d["tem_dados"] is False
    assert len(d["estimativas"]) == 4            # a estimativa não some: só fica separada


def test_textos_da_data_do_arquivo_sem_last_modified_nao_inventam_data(db, rede):
    p = pipeline_seduc.previa(db, rede, _arq_municipio(2025),
                              "Proficiência do SARESP por Municipio de 2025_0.csv", usuario_id=None)
    db.commit()
    pipeline_seduc.aplicar(db, rede, p["id"], _arq_municipio(2025),
                           "Proficiência do SARESP por Municipio de 2025_0.csv", usuario_id=None)
    db.commit()
    d = consulta_saresp.saresp_da_rede(db, rede)
    f = d["fontes"][0]
    assert f["data_arquivo"] is None and f["data_arquivo_origem"] is None
    assert db.scalar(select(ResultadoAvaliacao.id)) is None     # território não vai p/ escola


# --- O mesmo, num PostgreSQL de verdade -----------------------------------------

from tests.test_migracoes_postgres import engine_postgres  # noqa: E402,F401 — fixture do PG de teste


@pytest.mark.postgres
def test_consulta_saresp_no_postgres(engine_postgres):
    from sqlalchemy.orm import sessionmaker

    from app.core.migracoes import aplicar_migracoes

    aplicar_migracoes(engine_postgres)
    db = sessionmaker(bind=engine_postgres)()
    try:
        r = Rede(nome="Rede Sintética PG", uf="SP", codigo_ibge=MUN,
                 codigo_municipio_estadual=CODMUN, status="ativa")
        db.add(r)
        db.flush()
        db.add_all([Escola(nome="ESCOLA SINTETICA GAMA", ano_letivo_ativo=2026, rede_id=r.id),
                    Escola(nome="EMEF Sintética Beta", ano_letivo_ativo=2026, rede_id=r.id,
                           codigo_inep="35990002"),
                    Escola(nome="EMEF Sintética Alfa", ano_letivo_ativo=2026, rede_id=r.id,
                           codigo_inep="35990001")])
        db.commit()
        _calculadas(db, r)
        _importar_tudo(db, r, substituir=False)
        d = consulta_saresp.saresp_da_rede(db, r)
        assert [linha["nome"] for linha in d["escolas"]["linhas"]] == [
            "EMEF Sintética Alfa", "EMEF Sintética Beta", "ESCOLA SINTETICA GAMA"]
        assert _serie(d["territorios"][0], "2_ano", "lp")[0] == (2022, 121.3, None)
        assert len(d["estimativas"]) == 4
        assert _edicao(_escola(d, "EMEF Sintética Alfa"), 2025)["proficiencia"]["2_ano"]["lp"][
            "valor"] == 148.3
    finally:
        db.close()
