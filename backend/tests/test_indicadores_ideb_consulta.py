"""Leitura do Ideb e do Saeb do 5º ano por escola (etapa E8a):
``GET /redes/{id}/indicadores/ideb``.

O que a API garante (plano, 2.2, 4.6, 4.7, 4.8, 5.1; "Correções da revisão" (2).4/(2).5):

* permissões: a Secretaria da PRÓPRIA rede e o admin global leem; a Secretaria de
  outra rede, o coordenador e o professor de escola recebem 403;
* por escola, em ordem de NOME (sem ranking), a série do Ideb, do Saeb (LP e MT), de
  N, de P, da aprovação e da meta, cada número com a fonte (``fonte_id`` → arquivo,
  edição, data do arquivo e da importação);
* meta × observado na precisão PUBLICADA (1 casa, mesmo com a coluna da meta toda
  inteira): "atingiu" (Ideb ≥ meta, o empate incluído) e "nao_atingiu"; depois de 2021,
  "o INEP não definiu meta" — nada comparado;
* ausência ≠ 0: "-"/"ND" = "não divulgado" com o motivo; escola sem linha no arquivo,
  sem INEP, com o INEP cadastrado ou trocado depois da importação — cada uma com o
  seu motivo, sem número de outra linha do arquivo;
* números gravados pelo botão de 1 clique (sem proveniência oficial) MARCADOS — e
  "difere do oficial" quando a importação recusou trocá-los;
* cobertura por edição: com Ideb/Saeb, sem resultado, sem linha no arquivo, sem INEP e
  os códigos do arquivo fora do cadastro;
* o que falta (a edição 2025, o território) vem pelo nome do arquivo, sem "aguardando"
  (o bloco da rede municipal tem o seu teste: ``test_indicadores_ideb_rede``); a
  participação por escola só com a D8.

FIXTURES SINTÉTICAS — as mesmas fábricas INVENTADAS do teste da E6a (layout real do
arquivo do INEP; o município, os INEPs, os nomes, as datas e TODOS os números são
fictícios e longe dos oficiais — decisão D13: repositório público, licença CC BY-ND).
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.security import hash_senha
from app.main import app
from app.models import AvaliacaoExterna, Escola, ImportacaoIndicador, Rede, ResultadoAvaliacao, Usuario
from app.services import avaliacoes as svc
from app.services.indicadores import consulta_ideb, pipeline_ideb
from tests.test_indicadores_ideb import (_ALFA, ALFA, BETA, ESTADUAL, GAMA, HOMONIMO, MUN,
                                         OUTRO_MUN, _aplicar, _escola, _manuais_2023, _preparar,
                                         _valores, planilha)

# A DELTA (no cadastro) com linha NO município — só nos testes de meta: Ideb igual à
# meta em 2019 (empate na precisão publicada), acima dela em 2021. Tudo INVENTADO.
_DELTA_NO_MUNICIPIO = [
    (2019, 47.2, 49.1, 45.6, 44.3, 46.8, 48.5, 0.583164, 126.41, 121.07, 2.351862, 2.2),
    (2021, 48.9, 50.4, 47.1, 46.2, 48.3, 50.7, 0.591427, 127.83, 122.56, 2.398417, 2.3),
    (2023, 49.6, 51.2, 48.4, 47.5, 49.1, 51.3, 0.596318, 128.62, 123.95, 2.427649, 2.3)]
DELTA_MUN = _escola("35990105", "EMEF SINTETICA DELTA",
                    _valores(_DELTA_NO_MUNICIPIO, {2019: 2.2, 2021: 2.0}))


@pytest.fixture()
def rede(db):
    r = Rede(nome="Rede Sintética do Ideb", uf="SP", codigo_ibge=MUN, status="ativa")
    vizinha = Rede(nome="Rede Vizinha Fictícia", uf="SP", codigo_ibge=OUTRO_MUN, status="ativa")
    db.add_all([r, vizinha])
    db.flush()
    # Fora da ordem alfabética de propósito: a API ordena por NOME (sem acento/caixa).
    db.add_all([
        Escola(nome="EMEF Sintética Zeta", ano_letivo_ativo=2026, rede_id=r.id,
               codigo_inep="35990106"),                    # tem INEP, sem linha no arquivo
        Escola(nome="EMEF SINTETICA GAMA", ano_letivo_ativo=2026, rede_id=r.id),   # sem INEP
        Escola(nome="EMEF Sintética Delta", ano_letivo_ativo=2026, rede_id=r.id,
               codigo_inep="35990105"),                    # a linha dela é de outro município
        Escola(nome="EMEF Sintética Beta", ano_letivo_ativo=2026, rede_id=r.id,
               codigo_inep="35990102"),
        Escola(nome="EMEF Sintética Alfa", ano_letivo_ativo=2026, rede_id=r.id,
               codigo_inep="35990101"),
        Escola(nome="EMEF Sintética Épsilon (desativada)", ano_letivo_ativo=2026,
               rede_id=r.id, status="inativa"),             # inativa sem número: fora
        # o homônimo da ALFA, com o INEP dele, noutra rede: nunca aparece nesta
        Escola(nome="EMEF SINTETICA ALFA", ano_letivo_ativo=2026, rede_id=vizinha.id,
               codigo_inep="35980101"),
    ])
    db.commit()
    return r


def _importar(db, rede, tmp_path, xlsx=None, **kw) -> dict:
    _, a = _aplicar(db, rede, _preparar(tmp_path, xlsx).pacote, **kw)
    return a


def _ler(db, rede) -> dict:
    db.expire_all()
    return consulta_ideb.ideb_da_rede(db, rede)


def _escola_da(dados: dict, nome: str) -> dict:
    return next(linha for linha in dados["escolas"] if linha["nome"] == nome)


def _ed(linha: dict, edicao: int) -> dict:
    return next(e for e in linha["serie"] if e["edicao"] == edicao)


def _cliente(db, email: str, **campos) -> TestClient:
    db.add(Usuario(nome=email, email=email, senha_hash=hash_senha("s3nh4leitura"), **campos))
    db.commit()
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", data={"username": email, "password": "s3nh4leitura"})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def _url(rede_id) -> str:
    return f"/api/v1/redes/{rede_id}/indicadores/ideb"


# =============================================================================
# Permissões
# =============================================================================

def test_permissoes_secretaria_da_rede_e_admin_leem_os_demais_403(db, escola_completa,
                                                                  cliente_global, rede):
    escola = escola_completa["escola"]
    vizinha = db.execute(select(Rede).where(Rede.nome == "Rede Vizinha Fictícia")).scalar_one()
    secretaria = _cliente(db, "sec@leitura-ideb.gov", cargo="coordenador", rede_id=rede.id)
    secretaria_outra = _cliente(db, "sec@vizinha-ideb.gov", cargo="coordenador",
                                rede_id=vizinha.id)
    coordenador = _cliente(db, "coord@leitura-ideb.escola", cargo="coordenador",
                           escola_id=escola.id)
    professor = _cliente(db, "prof@leitura-ideb.escola", cargo="professor", escola_id=escola.id)

    assert cliente_global.get(_url(rede.id)).status_code == 200
    assert secretaria.get(_url(rede.id)).status_code == 200
    for quem in (secretaria_outra, coordenador, professor):
        r = quem.get(_url(rede.id))
        assert r.status_code == 403, (quem, r.text)
    assert cliente_global.get(_url(999999)).status_code == 404
    # A Secretaria de outra rede lê a DELA, não esta.
    assert secretaria_outra.get(_url(vizinha.id)).status_code == 200


# =============================================================================
# Série por escola, ordem por nome, fonte em cada número
# =============================================================================

def test_serie_por_escola_em_ordem_de_nome_com_a_fonte_de_cada_numero(db, rede, tmp_path):
    a = _importar(db, rede, tmp_path)
    d = _ler(db, rede)

    assert d["tem_dados"] and d["pendencias"] == [] and d["codigo_ibge"] == MUN
    assert d["edicoes"] == [2019, 2021, 2023] and d["anos_meta"] == [2019, 2021]
    assert d["municipio"] == "Cidade Sintética"
    # Por NOME, sem acento e sem caixa; a inativa sem número e a de outra rede, fora.
    assert [linha["nome"] for linha in d["escolas"]] == [
        "EMEF Sintética Alfa", "EMEF Sintética Beta", "EMEF Sintética Delta",
        "EMEF SINTETICA GAMA", "EMEF Sintética Zeta"]

    alfa = _escola_da(d, "EMEF Sintética Alfa")
    e19 = _ed(alfa, 2019)
    assert (e19["ideb"]["valor"], e19["ideb"]["casas_decimais"]) == (1.5, 1)
    assert (e19["saeb_mt"]["valor"], e19["saeb_mt"]["casas_decimais"]) == (131.47, 2)
    assert (e19["saeb_lp"]["valor"], e19["saeb_lp"]["casas_decimais"]) == (124.83, 2)
    assert (e19["nota_n"]["valor"], e19["nota_n"]["casas_decimais"]) == (2.381946, 6)
    assert e19["rendimento_p"]["valor"] == 0.612347
    assert e19["aprovacao"]["anos_iniciais"]["valor"] == 51.4
    assert [e19["aprovacao"][s]["valor"] for s in ("1_ano", "2_ano", "3_ano", "4_ano", "5_ano")] \
        == [54.2, 48.3, 45.1, 39.7, 42.6]
    assert e19["meta"]["valor"] == 2.3 and e19["meta"]["casas_decimais"] == 1
    # Precisão publicada mesmo quando o float perdeu o zero final ("6,0"; "412,50").
    assert consulta_ideb._casas(6.0, "ideb") == 1 and consulta_ideb._casas(412.5, "saeb_lp") == 2

    # Cada número: proveniência oficial e a fonte (arquivo, edição, data do arquivo).
    fontes = {f["importacao_id"]: f for f in d["fontes"]}
    for linha in d["escolas"]:
        for ed in linha["serie"]:
            numeros = [ed[c] for c in ("ideb", "saeb_lp", "saeb_mt", "nota_n", "rendimento_p",
                                       "meta")] + list(ed["aprovacao"].values())
            for n in numeros:
                if n is None:
                    continue
                assert n["proveniencia"] == "oficial" and n["fonte_id"] == a["id"]
    f = fontes[a["id"]]
    assert (f["arquivo_nome"], f["edicao_arquivo"], f["arquivo_data"]) == (
        "ideb.zip", 2023, "2031-06-02T08:15:00")
    assert f["parser"] == "inep_ideb_escolas" and f["importado_em"] and "CC BY-ND" in f["licenca"]
    assert f["url_origem"] == "https://exemplo.invalido/ideb_sintetico.zip"
    assert "Fonte: arquivo sintético de teste" in f["notas"]
    assert d["campos"]["ideb"]["casas_publicadas"] == 1
    assert d["campos"]["saeb_lp"]["casas_publicadas"] == 2


def test_ausencias_com_motivo_e_variacao_nunca_contra_zero(db, rede, tmp_path):
    _importar(db, rede, tmp_path)
    d = _ler(db, rede)

    beta = _escola_da(d, "EMEF Sintética Beta")
    b23 = _ed(beta, 2023)
    # "-" no arquivo: Ideb NÃO DIVULGADO (valor nulo + motivo), nunca 0.
    assert b23["ideb"]["valor"] is None and b23["ideb"]["motivo_ausencia"] == "nao_divulgado"
    assert (b23["tem_ideb"], b23["motivo"], b23["no_arquivo"]) == (False, "nao_divulgado", True)
    assert b23["saeb_mt"]["valor"] is None and b23["tem_saeb"] is False
    b21 = _ed(beta, 2021)
    assert b21["saeb_lp"]["valor"] is None and b21["saeb_lp"]["motivo_ausencia"] == "nao_divulgado"
    # meta "-" (2019) = meta não divulgada; Ideb "-" (2021) com meta 2,2: nada comparado
    assert _ed(beta, 2019)["meta"]["valor"] is None
    assert b21["meta"]["valor"] == 2.2 and b21["comparacao_meta"] is None

    # Variação desde a edição ANTERIOR, só quando as duas têm número.
    alfa = _escola_da(d, "EMEF Sintética Alfa")
    assert _ed(alfa, 2019)["variacao_ideb"] is None
    assert _ed(alfa, 2021)["variacao_ideb"] == {"desde": 2019, "diferenca": 0.1, "casas_decimais": 1}
    assert _ed(alfa, 2023)["variacao_ideb"]["diferenca"] == 0.1
    assert b21["variacao_ideb"] is None and b23["variacao_ideb"] is None

    # Sem linha no arquivo (Delta: a linha dela é de outro município; Zeta: não está).
    for nome in ("EMEF Sintética Delta", "EMEF Sintética Zeta"):
        for ed in _escola_da(d, nome)["serie"]:
            assert ed["motivo"] == "fora_do_arquivo" and ed["no_arquivo"] is False
            assert ed["ideb"] is None and ed["meta"] is None and ed["nota_n"] is None
    # Sem INEP: pendência de cadastro, sem número nenhum.
    gama = _escola_da(d, "EMEF SINTETICA GAMA")
    assert gama["pendencia"] == "codigo_inep" and gama["codigo_inep"] is None
    assert {ed["motivo"] for ed in gama["serie"]} == {"sem_codigo_inep"}
    assert not any(ed["no_arquivo"] for ed in gama["serie"])


# =============================================================================
# Meta × observado na precisão publicada
# =============================================================================

def test_meta_x_observado_atingiu_e_nao_atingiu_na_precisao(db, rede, tmp_path):
    xlsx = planilha([ALFA, BETA, GAMA, ESTADUAL, HOMONIMO, DELTA_MUN],
                    edicoes=(2017, 2019, 2021, 2023), metas=(2019, 2021))
    _importar(db, rede, tmp_path, xlsx)
    d = _ler(db, rede)

    delta = _escola_da(d, "EMEF Sintética Delta")
    c19 = _ed(delta, 2019)["comparacao_meta"]
    # 2,2 × 2,2 na precisão publicada (1 casa): Ideb ≥ meta = ATINGIU (leitura do INEP).
    # Nada de "inconclusivo" como no ICA: o Ideb de 1 casa é o número oficial, sem valor
    # mais preciso que desfaça o empate.
    assert c19 == {"observado": 2.2, "meta": 2.2, "diferenca": 0.0, "casas_decimais": 1,
                   "situacao": "atingiu"}
    assert "igual ou acima da meta" in d["avisos"]["precisao"]
    assert "inconclusivo" not in d["avisos"]["precisao"]
    c21 = _ed(delta, 2021)["comparacao_meta"]
    assert (c21["situacao"], c21["diferenca"]) == ("atingiu", 0.3)
    c_alfa = _ed(_escola_da(d, "EMEF Sintética Alfa"), 2019)["comparacao_meta"]
    assert (c_alfa["situacao"], c_alfa["diferenca"]) == ("nao_atingiu", -0.8)
    # Depois do 1º ciclo (2023): o INEP não definiu meta — nada comparado. 2017 vem
    # antes das metas do arquivo.
    d23 = _ed(delta, 2023)
    assert d23["meta"] is None and d23["comparacao_meta"] is None
    assert d23["sem_meta"] == "depois_do_1o_ciclo"
    assert _ed(delta, 2017)["sem_meta"] == "antes_das_metas"
    assert _ed(delta, 2019)["sem_meta"] is None
    assert "2017–2023" in d["avisos"]["comparabilidade"]
    assert {c["situacao"] for linha in d["escolas"] for ed in linha["serie"]
            if (c := ed["comparacao_meta"])} <= {"atingiu", "nao_atingiu"}


def test_meta_e_aprovacao_inteiras_no_arquivo_ficam_na_precisao_publicada(db, rede, tmp_path):
    """Todas as metas da rede numa edição INTEIRAS no xlsx (a planilha devolve int): a
    coluna sai com 0 casas na importação, mas a leitura usa a precisão publicada (1 casa)
    — 1,5 × meta 2 é "não atingiu" (−0,5), não 2 × 2 (empate). O mesmo piso na
    aprovação (formato "0.0" do INEP). Números INVENTADOS."""
    tabela = [(2019, 51, *_ALFA[0][2:]), *_ALFA[1:]]          # aprovação 1º–5º de 2019 inteira
    alfa = _escola("35990101", "EMEF SINTETICA ALFA", _valores(tabela, {2019: 2, 2021: 2.4}))
    _importar(db, rede, tmp_path, planilha([alfa]))
    d = _ler(db, rede)

    a = _escola_da(d, "EMEF Sintética Alfa")
    e19 = _ed(a, 2019)
    assert (e19["meta"]["valor"], e19["meta"]["casas_decimais"]) == (2.0, 1)
    assert e19["comparacao_meta"] == {"observado": 1.5, "meta": 2.0, "diferenca": -0.5,
                                      "casas_decimais": 1, "situacao": "nao_atingiu"}
    assert (e19["aprovacao"]["anos_iniciais"]["valor"],
            e19["aprovacao"]["anos_iniciais"]["casas_decimais"]) == (51.0, 1)
    # A edição com a meta escrita com casa segue igual.
    e21 = _ed(a, 2021)
    assert e21["meta"]["casas_decimais"] == 1
    assert (e21["comparacao_meta"]["situacao"], e21["comparacao_meta"]["diferenca"]) == (
        "nao_atingiu", -0.8)
    # N e P: as casas do arquivo, sem piso (6 casas).
    assert e19["nota_n"]["casas_decimais"] == 6


# =============================================================================
# Números sem proveniência oficial (1 clique)
# =============================================================================

def test_numeros_do_1_clique_vem_marcados_antes_e_depois_da_importacao(db, rede, tmp_path):
    _manuais_2023(db, rede)
    # Ideb de OUTRA etapa e Saeb de outra série da mesma escola: não entram.
    ideb_av, saeb_av = svc.obter_avaliacao(db, "ideb"), svc.obter_avaliacao(db, "saeb")
    alfa_id = db.execute(select(Escola.id).where(Escola.codigo_inep == "35990101")).scalar_one()
    db.add_all([
        ResultadoAvaliacao(avaliacao_id=ideb_av.id, edicao=2023, rede_id=rede.id,
                           escola_id=alfa_id, codigo_inep="35990101", etapa="anos_finais",
                           indicador="ideb", valor=1.2, unidade="indice", fonte="manual"),
        ResultadoAvaliacao(avaliacao_id=saeb_av.id, edicao=2023, rede_id=rede.id,
                           escola_id=alfa_id, codigo_inep="35990101", etapa="9_ano",
                           componente="matematica", indicador="proficiencia", valor=139.2,
                           unidade="escala_saeb", fonte="manual"),
    ])
    db.commit()

    antes = _ler(db, rede)
    assert antes["edicoes"] == [2023] and antes["tem_dados"]
    # Uma edição só: "(2023)", não "(2023–2023)".
    assert "(2023) não é comparável" in antes["avisos"]["comparabilidade"]
    assert "2023–2023" not in antes["avisos"]["comparabilidade"]
    a23 = _ed(_escola_da(antes, "EMEF Sintética Alfa"), 2023)
    assert a23["ideb"]["valor"] == 1.7                     # a de anos_finais (1,2) não entra
    for campo, fonte in (("ideb", "IDEB 2023 — arquivo_sintetico.zip"),
                         ("saeb_mt", "SAEB 2023 — arquivo_sintetico.zip")):
        n = a23[campo]
        assert n["proveniencia"] == "sem_registro" and n["fonte_id"] is None
        assert n["fonte_texto"] == fonte and n["gravado_em"] and n["difere_do_oficial"] is False
    assert antes["sem_registro_oficial"] == {"total": 3, "por_edicao": {"2023": 3},
                                             "difere_do_oficial": 0}
    assert _escola_da(antes, "EMEF Sintética Alfa")["tem_sem_registro"] is True
    # Sem arquivo oficial importado: as outras escolas dizem isso (não "não divulgado").
    assert _ed(_escola_da(antes, "EMEF Sintética Beta"), 2023)["motivo"] == "sem_importacao"
    assert antes["cobertura"][0]["arquivo_importado"] is False
    assert antes["cobertura"][0]["fora_do_cadastro"] == []
    assert a23["sem_meta"] == "sem_arquivo_oficial" and antes["fontes"] == []

    a = _importar(db, rede, tmp_path)
    depois = _ler(db, rede)
    a23 = _ed(_escola_da(depois, "EMEF Sintética Alfa"), 2023)
    # Iguais ao arquivo: ficam COMO ESTÃO — e continuam marcados (sem registro oficial).
    assert a23["ideb"]["proveniencia"] == "sem_registro" and a23["ideb"]["valor"] == 1.7
    assert a23["saeb_lp"]["proveniencia"] == "sem_registro"
    # N, P e aprovação de 2023 e as outras edições: oficiais, da importação.
    assert a23["nota_n"]["fonte_id"] == a["id"]
    assert _ed(_escola_da(depois, "EMEF Sintética Alfa"), 2021)["ideb"]["fonte_id"] == a["id"]
    assert depois["sem_registro_oficial"]["total"] == 3


def test_numero_do_1_clique_diferente_e_mantido_vem_como_difere_do_oficial(db, rede, tmp_path):
    _manuais_2023(db, rede, mt_alfa=134.81)
    a = _importar(db, rede, tmp_path, substituir_calculadas=False)
    d = _ler(db, rede)
    mt = _ed(_escola_da(d, "EMEF Sintética Alfa"), 2023)["saeb_mt"]
    assert (mt["valor"], mt["proveniencia"], mt["difere_do_oficial"]) == (134.81, "sem_registro",
                                                                          True)
    assert mt["recusado_na_importacao"] == a["id"]
    assert d["sem_registro_oficial"]["difere_do_oficial"] == 1
    lp = _ed(_escola_da(d, "EMEF Sintética Alfa"), 2023)["saeb_lp"]
    assert lp["difere_do_oficial"] is False                 # igual ao arquivo: só marcado


# =============================================================================
# Cobertura e cadastro que mudou depois da importação
# =============================================================================

def test_cobertura_sem_linha_sem_inep_e_codigos_fora_do_cadastro(db, rede, tmp_path):
    a = _importar(db, rede, tmp_path)
    d = _ler(db, rede)
    assert [c["edicao"] for c in d["cobertura"]] == [2023, 2021, 2019]
    c = d["cobertura"][0]
    assert (c["total_escolas"], c["com_ideb"], c["com_saeb"]) == (5, 1, 1)
    assert [(s["nome"], s["motivo"]) for s in c["sem_resultado"]] == [
        ("EMEF Sintética Beta", "nao_divulgado")]
    assert [s["codigo_inep"] for s in c["sem_linha_no_arquivo"]] == ["35990105", "35990106"]
    assert [s["nome"] for s in c["sem_inep"]] == ["EMEF SINTETICA GAMA"]
    assert c["fora_do_cadastro"] == [{"codigo_inep": "35990103",
                                      "nome_no_arquivo": "EMEF SINTETICA GAMA (fora do cadastro)"}]
    assert c["arquivo_importado"] is True and c["fonte_id"] == a["id"]
    c19 = d["cobertura"][2]
    assert (c19["com_ideb"], c19["com_saeb"]) == (2, 2)     # a Beta tem Ideb e Saeb em 2019


def test_inep_cadastrado_depois_pede_reimportar_e_sai_do_fora_do_cadastro(db, rede, tmp_path):
    _importar(db, rede, tmp_path)
    zeta = db.execute(select(Escola).where(Escola.codigo_inep == "35990106")).scalar_one()
    zeta.codigo_inep = "35990103"            # o código da GAMA do arquivo, cadastrado DEPOIS
    db.commit()
    d = _ler(db, rede)
    z = _escola_da(d, "EMEF Sintética Zeta")
    assert {ed["motivo"] for ed in z["serie"]} == {"cadastrado_depois_da_importacao"}
    assert not any(ed["no_arquivo"] for ed in z["serie"])          # nada da linha da GAMA
    c = d["cobertura"][0]
    assert c["fora_do_cadastro"] == []
    assert ("EMEF Sintética Zeta", "cadastrado_depois_da_importacao") in {
        (s["nome"], s["motivo"]) for s in c["sem_resultado"]}


def test_inep_trocado_depois_nao_mistura_numeros_de_duas_linhas(db, rede, tmp_path):
    _importar(db, rede, tmp_path)
    alfa = db.execute(select(Escola).where(Escola.codigo_inep == "35990101")).scalar_one()
    alfa.codigo_inep = "35990103"            # trocado para o código de OUTRA linha do arquivo
    db.commit()
    d = _ler(db, rede)
    a = _escola_da(d, "EMEF Sintética Alfa")
    assert {ed["motivo"] for ed in a["serie"]} == {"codigo_inep_alterado"}
    # Nem o Ideb gravado pela escola (da linha 35990101) nem N/P/meta pelo código novo.
    assert all(ed[c] is None for ed in a["serie"]
               for c in ("ideb", "saeb_lp", "saeb_mt", "nota_n", "rendimento_p", "meta"))


# =============================================================================
# O que falta sem importação (nunca "aguardando"); participação só com a D8
# =============================================================================

def test_sem_o_territorio_e_sem_2025_o_que_falta_vem_pelo_nome_do_arquivo(db, rede, tmp_path):
    _importar(db, rede, tmp_path)
    d = _ler(db, rede)
    # A E8b tirou o "aguardando o arquivo oficial": os arquivos são públicos — o que falta
    # é a importação nesta base (e a planilha do Saeb 2023, adiada).
    assert "comparacoes" not in d and "aguardando" not in d["avisos"]
    pend = {p["chave"]: p for p in d["pendentes"]}
    assert pend["ideb_escolas_2025"] == {
        "chave": "ideb_escolas_2025", "edicao": 2025, "situacao": "sem_importacao",
        "arquivo": "divulgacao_anos_iniciais_escolas_2025.zip",
        "texto": pend["ideb_escolas_2025"]["texto"]}
    assert "não foi importado" in pend["ideb_escolas_2025"]["texto"]
    assert {pend[c]["situacao"] for c in ("ideb_municipio", "ideb_uf", "ideb_brasil")} == {
        "sem_importacao"}
    assert pend["saeb_planilha_2023"]["situacao"] == "adiado"
    assert all("aguardando" not in p["texto"] for p in d["pendentes"])
    assert d["rede_municipal"]["tem_dados"] is False
    assert d["participacao"]["disponivel"] is False and d["participacao"]["decisao"] == "D8"
    assert "participação baixa" in d["participacao"]["texto"]
    assert "série TODA" in d["avisos"]["comparabilidade"]
    assert "2019–2023" in d["avisos"]["comparabilidade"]
    assert "2021" in d["avisos"]["pandemia"]
    assert "média das escolas" in d["avisos"]["media_das_escolas"]


def test_com_a_edicao_2025_importada_ela_sai_dos_pendentes(db, rede, tmp_path):
    xlsx = planilha(edicoes=(2021, 2023, 2025), metas=(2021,))
    _importar(db, rede, tmp_path, xlsx)
    d = _ler(db, rede)
    assert d["edicoes"] == [2021, 2023, 2025]
    assert "ideb_escolas_2025" not in {p["chave"] for p in d["pendentes"]}
    assert _ed(_escola_da(d, "EMEF Sintética Alfa"), 2025)["sem_meta"] == "depois_do_1o_ciclo"
    assert "de 2023 em diante" in d["avisos"]["metas"]
    assert "(2021–2025)" in d["avisos"]["comparabilidade"]


def test_sem_nada_importado_vem_vazio_e_nao_cria_catalogo(db, escola_completa, cliente_global,
                                                          rede):
    n_av = db.scalar(select(func.count(AvaliacaoExterna.id)))
    d = cliente_global.get(_url(rede.id)).json()
    assert d["tem_dados"] is False and d["edicoes"] == [] and d["cobertura"] == []
    assert all(linha["serie"] == [] for linha in d["escolas"])
    assert d["fontes"] == [] and d["sem_registro_oficial"]["total"] == 0
    assert db.scalar(select(func.count(AvaliacaoExterna.id))) == n_av        # só LÊ
    assert db.scalar(select(func.count(ImportacaoIndicador.id))) == 0


def test_rede_sem_codigo_ibge_pede_o_cadastro_e_ainda_mostra_o_1_clique(db, rede):
    _manuais_2023(db, rede)
    rede.codigo_ibge = None
    db.commit()
    d = _ler(db, rede)
    assert d["pendencias"] == ["codigo_ibge"] and d["codigo_ibge"] is None
    a23 = _ed(_escola_da(d, "EMEF Sintética Alfa"), 2023)
    assert a23["ideb"]["proveniencia"] == "sem_registro" and a23["ideb"]["valor"] == 1.7


def test_desfazer_a_importacao_volta_a_leitura_anterior(db, rede, tmp_path):
    antes = _ler(db, rede)
    a = _importar(db, rede, tmp_path)
    pipeline_ideb.desfazer(db, rede, a["id"], usuario_id=None)
    db.commit()
    depois = _ler(db, rede)
    assert depois == antes


# =============================================================================
# PostgreSQL
# =============================================================================

from tests.test_migracoes_postgres import engine_postgres  # noqa: E402,F401 — fixture do PG de teste


@pytest.mark.postgres
def test_consulta_ideb_no_postgres(engine_postgres, tmp_path):
    from sqlalchemy.orm import sessionmaker

    from app.core.migracoes import aplicar_migracoes

    aplicar_migracoes(engine_postgres)
    db = sessionmaker(bind=engine_postgres)()
    try:
        r = Rede(nome="Rede Sintética PG", uf="SP", codigo_ibge=MUN, status="ativa")
        db.add(r)
        db.flush()
        db.add_all([Escola(nome="EMEF SINTETICA GAMA", ano_letivo_ativo=2026, rede_id=r.id),
                    Escola(nome="EMEF Sintética Beta", ano_letivo_ativo=2026, rede_id=r.id,
                           codigo_inep="35990102"),
                    Escola(nome="EMEF Sintética Alfa", ano_letivo_ativo=2026, rede_id=r.id,
                           codigo_inep="35990101")])
        db.commit()
        _manuais_2023(db, r)
        _, a = _aplicar(db, r, _preparar(tmp_path).pacote)
        d = consulta_ideb.ideb_da_rede(db, r)
        assert [linha["nome"] for linha in d["escolas"]] == [
            "EMEF Sintética Alfa", "EMEF Sintética Beta", "EMEF SINTETICA GAMA"]
        alfa = _escola_da(d, "EMEF Sintética Alfa")
        assert _ed(alfa, 2019)["comparacao_meta"]["situacao"] == "nao_atingiu"
        assert _ed(alfa, 2023)["ideb"]["proveniencia"] == "sem_registro"
        assert _ed(alfa, 2021)["ideb"]["fonte_id"] == a["id"]
        assert _ed(_escola_da(d, "EMEF Sintética Beta"), 2023)["motivo"] == "nao_divulgado"
        assert d["cobertura"][0]["fora_do_cadastro"][0]["codigo_inep"] == "35990103"
    finally:
        db.close()
