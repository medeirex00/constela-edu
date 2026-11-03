"""Análise educacional — os indicadores OFICIAIS na forma única
(``GET /redes/{id}/analise/indicadores`` e ``.../indicadores/{chave}``).

O que estes testes sustentam:

* a disponibilidade POR INDICADOR (com o motivo quando não há);
* os filtros etapa / componente / escola / de–até / visão;
* AUSÊNCIA ≠ ZERO: o ponto sem número traz ``valor`` nulo e o MOTIVO da consulta oficial;
* META E DIFERENÇA iguais às das consultas oficiais — o "inconclusivo" do ICA no empate e
  as metas do Ideb só até 2021;
* a ESTIMATIVA CONSTELA nunca numa série oficial (fica em ``estimativas``); o Ideb e o
  Saeb gravados antes, sem o registro do arquivo oficial, aparecem nas séries MARCADOS
  (``proveniencia = "sem_registro"``), nunca como estimativa, nos destaques ou na relação;
* os avisos são os das consultas oficiais (o período real do Ideb, o aviso dos níveis do
  SARESP) e os textos da tela não citam arquivo nem caminho;
* a visão por escolas em ordem de NOME (nunca ranking), com as médias instáveis (TPS = 0)
  marcadas.

Dados INVENTADOS (``test_analise_base``; decisão D13).
"""
import json

import pytest

from app.models import ImportacaoIndicador, Usuario
from app.core.security import hash_senha
from app.services.analise import indicadores as svc
from app.services.indicadores import consulta, consulta_ideb, consulta_saresp
from tests.test_analise_base import INEPS, NOMES, mundo_indicadores, nova_escola, nova_rede

URL = "/api/v1/redes/{rede}/analise/indicadores"


@pytest.fixture()
def mundo(db, cliente_global):
    m = mundo_indicadores(db)
    return {**m, "c": cliente_global}


def _get(mundo, caminho="", **params):
    r = mundo["c"].get(URL.format(rede=mundo["rede"].id) + caminho, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _serie(dados, id_):
    return next(s for s in dados["series"] if s["id"] == id_)


def _pontos(serie):
    return {p["edicao"]: p for p in serie["pontos"]}


# --- Catálogo: disponibilidade por indicador -----------------------------------------------

def test_catalogo_diz_a_disponibilidade_de_cada_indicador(mundo):
    dados = _get(mundo)
    itens = {i["chave"]: i for i in dados["indicadores"]}
    assert list(itens) == ["ica", "saresp", "iee", "ideb", "saeb"]
    assert all(i["disponivel"] and i["oficial"] for i in itens.values())
    assert itens["ica"]["por_escola"] is False and itens["ica"]["abrangencias"] == ["rede"]
    assert itens["ica"]["edicoes"] == [2024, 2025]          # 2023: só a ausência
    assert itens["saresp"]["etapas"] == ["5_ano", "2_ano"]
    assert itens["saresp"]["componentes"] == ["lp", "mt"] and itens["saresp"]["tem_meta"] is False
    assert itens["iee"]["abrangencias"] == ["escola"] and itens["iee"]["tem_meta"] is True
    assert itens["ideb"]["edicoes"] == [2019, 2021, 2023]
    assert itens["saeb"]["edicoes"] == [2019, 2021, 2023]
    assert itens["saeb"]["unidade"] == "pontos" and itens["ideb"]["unidade"] == "índice"
    assert dados["rede"]["codigo_ibge"] == mundo["rede"].codigo_ibge
    # Escolas em ordem de NOME (sem acento): Ébano antes de "Fictícia ...".
    assert [e["nome"] for e in dados["escolas"]] == [
        NOMES["ebano"], NOMES["alfa"], NOMES["beta"], NOMES["delta"], NOMES["gama"]]
    gama = next(e for e in dados["escolas"] if e["nome"] == NOMES["gama"])
    assert gama["pendencia"] == "sem_codigo_inep"


def test_indicador_sem_importacao_ou_sem_codigo_diz_o_motivo(db, cliente_global):
    sem_codigo = nova_rede(db, nome="Rede Fictícia Sem IBGE", codigo=None)
    nova_escola(db, sem_codigo, "EMEF Fictícia Solitária", "35990201")
    vazia = nova_rede(db, nome="Rede Fictícia Vazia", codigo="3599903")
    db.commit()
    a = cliente_global.get(URL.format(rede=sem_codigo.id)).json()
    itens = {i["chave"]: i for i in a["indicadores"]}
    assert not any(i["disponivel"] for i in itens.values())
    assert itens["ica"]["motivo_indisponivel"] == "sem_codigo_ibge"
    assert itens["ica"]["texto_indisponivel"]
    assert any(al["tipo"] == "cadastro" and "IBGE" in al["texto"] for al in a["alertas"])
    b = cliente_global.get(URL.format(rede=vazia.id)).json()
    assert {i["motivo_indisponivel"] for i in b["indicadores"]} == {"sem_importacao"}
    assert {al["tipo"] for al in b["alertas"]} >= {"ausente"}
    assert b["destaques"] == []


def test_so_estimativa_nao_torna_o_indicador_disponivel(db, cliente_global):
    rede = nova_rede(db, nome="Rede Fictícia Estimada", codigo="3599904")
    e = nova_escola(db, rede, "EMEF Fictícia Estimada", "35990301")
    from tests.test_analise_base import resultado
    resultado(db, "saresp", e, edicao=2025, indicador="proficiencia", etapa="5_ano",
              componente="portugues", valor=222.2, imp=None)
    db.commit()
    dados = cliente_global.get(URL.format(rede=rede.id)).json()
    saresp = next(i for i in dados["indicadores"] if i["chave"] == "saresp")
    assert saresp["disponivel"] is False and saresp["motivo_indisponivel"] == "so_estimativa"
    (est,) = dados["estimativas"]
    assert est["chave"] == "saresp" and est["oficial"] is False and est["edicoes"] == [2025]
    assert "não são o indicador oficial" in est["nome"]
    assert est["tipo"] == "estimativa_constela" and "Estimativa Constela" in est["nome"]


def test_so_numero_sem_registro_nao_e_chamado_de_estimativa(db, cliente_global):
    rede = nova_rede(db, nome="Rede Fictícia Só 1 Clique", codigo="3599905")
    e = nova_escola(db, rede, "EMEF Fictícia do Clique", "35990401")
    from tests.test_analise_base import resultado
    resultado(db, "ideb", e, edicao=2023, indicador="ideb", etapa="anos_iniciais",
              componente=None, valor=6.6, imp=None, unidade="indice")
    db.commit()
    dados = cliente_global.get(URL.format(rede=rede.id)).json()
    ideb = next(i for i in dados["indicadores"] if i["chave"] == "ideb")
    assert ideb["disponivel"] is False and ideb["motivo_indisponivel"] == "so_sem_registro"
    assert "estimativa" not in ideb["texto_indisponivel"].lower()
    assert dados["estimativas"] == []
    (sr,) = dados["sem_registro_oficial"]
    assert sr["chave"] == "ideb" and sr["edicoes"] == [2023] and sr["tipo"] == "sem_registro"


def test_destaques_e_estimativas_separadas(mundo):
    dados = _get(mundo)
    d = {x["indicador"]: x for x in dados["destaques"]}
    assert set(d) == {"ica", "saresp", "ideb", "saeb"}          # o IEE não tem número da rede
    assert d["ica"]["rotulo"] == "ICA da rede (2º ano)"
    assert (d["ica"]["edicao"], d["ica"]["valor"], d["ica"]["meta"]) == (2025, 58.0, 60.0)
    assert d["ica"]["diferenca_meta"] == -2.0 and d["ica"]["situacao_meta"] == "nao_atingiu"
    assert [p["edicao"] for p in d["ica"]["serie"]] == [2023, 2024, 2025]
    assert d["ica"]["serie"][0]["valor"] is None
    assert d["ica"]["serie"][0]["motivo_ausencia"] == "participacao_baixa"
    assert (d["saresp"]["etapa"], d["saresp"]["componente"], d["saresp"]["valor"]) == (
        "5_ano", "lp", 201.4)
    assert d["ideb"]["edicao"] == 2023 and d["ideb"]["meta"] is None
    assert d["ideb"]["motivo_sem_meta"] == consulta_ideb.SEM_META_DEPOIS_DO_CICLO
    assert d["saeb"]["edicao"] == 2021 and d["saeb"]["valor"] == 210.0
    # A Estimativa Constela à parte (a do SARESP e a do 2º ano), nunca misturada com o
    # Ideb do 1 clique — que vem em `sem_registro_oficial`, com o próprio nome.
    chaves = {e["chave"]: e for e in dados["estimativas"]}
    assert set(chaves) == {"crianca_alfabetizada", "saresp"}
    assert chaves["crianca_alfabetizada"]["nome"].endswith("— não é o indicador oficial")
    assert {e["tipo"] for e in dados["estimativas"]} == {"estimativa_constela"}
    assert all(e["oficial"] is False for e in dados["estimativas"])
    (sr,) = dados["sem_registro_oficial"]
    assert (sr["chave"], sr["tipo"], sr["edicoes"]) == ("ideb", "sem_registro", [2023])
    assert sr["escolas_por_edicao"] == {"2023": 1} and sr["difere_do_oficial"] == 0
    assert "estimativa" not in (sr["nome"] + sr["texto"]).lower()
    assert str(d["ica"]["fonte_id"]) in dados["fontes"]
    # A metodologia legível vem junto, sem caminho de arquivo nem nome de campo.
    assert dados["metodologia_resumo"] and not any(
        "docs/" in t or ".md" in t or "_" in t for t in dados["metodologia_resumo"])


def test_alertas_de_cadastro_insuficiente_desatualizado_e_metodologia(mundo):
    alertas = _get(mundo)["alertas"]
    tipos = {a["tipo"] for a in alertas}
    assert {"cadastro", "insuficiente", "desatualizado", "metodologia"} <= tipos
    gama = mundo["escolas"]["gama"].id
    assert any(a["tipo"] == "cadastro" and a["escolas"] == [gama] for a in alertas)
    saresp = next(a for a in alertas if a["tipo"] == "insuficiente" and a["indicador"] == "saresp")
    assert set(saresp["escolas"]) == {mundo["escolas"]["delta"].id, gama}
    assert "sem resultado não é zero" in saresp["texto"]
    met = next(a for a in alertas if a["tipo"] == "metodologia")
    assert "2026" in met["texto"] and "2025" in met["texto"]
    # O "desatualizado" tem texto próprio: nem o nome do arquivo do INEP aparece.
    for a in alertas:
        assert ".zip" not in a["texto"] and ".xlsx" not in a["texto"] and "_" not in a["texto"]
    des = next(a for a in alertas if a["tipo"] == "desatualizado")
    assert "2025" in des["texto"] and "ainda não foi importado" in des["texto"]


def test_alerta_conta_o_numero_sem_registro_a_parte_de_sem_resultado(mundo):
    """Ideb 2023: a Delta tem só o número do 1 clique (7,7). O alerta não a conta como "sem
    resultado": diz quantas escolas têm número sem o registro do arquivo oficial."""
    alertas = _get(mundo)["alertas"]
    esc = mundo["escolas"]
    ins = next(a for a in alertas if a["tipo"] == "insuficiente" and a["indicador"] == "ideb")
    assert esc["delta"].id not in ins["escolas"]
    assert set(ins["escolas"]) == {esc["ebano"].id, esc["gama"].id}
    sr = next(a for a in alertas if a["tipo"] == "sem_registro" and a["indicador"] == "ideb")
    assert sr["escolas"] == [esc["delta"].id]
    assert "1 de 5" in sr["texto"] and "sem o registro do arquivo oficial" in sr["texto"]
    assert "estimativa" not in sr["texto"].lower()


# --- Um indicador: séries normalizadas -----------------------------------------------------

def test_ica_serie_com_meta_inconclusivo_no_empate_e_ausencia_com_motivo(db, mundo):
    dados = _get(mundo, "/ica")
    assert dados["filtros"]["etapa"] == "2_ano" and dados["filtros"]["componente"] == "lp"
    mun = _serie(dados, "rede_municipal")
    assert mun["papel"] == "principal" and mun["comparavel"] is True
    p = _pontos(mun)
    # 2023: o INEP não divulgou (participação baixa) — valor nulo, nunca 0.
    assert p[2023]["valor"] is None and p[2023]["motivo_ausencia"] == "participacao_baixa"
    assert "70%" in p[2023]["texto_ausencia"] and p[2023]["diferenca_meta"] is None
    # 2024: 55 × meta 55 na precisão divulgada → INCONCLUSIVO (não "atingiu").
    assert (p[2024]["valor"], p[2024]["meta"], p[2024]["diferenca_meta"]) == (55.0, 55.0, 0.0)
    assert p[2024]["situacao_meta"] == "inconclusivo"
    # 2025: 58 × 60 → −2 p.p.; o detalhe (58,37) vem junto, com a fonte.
    assert p[2025]["diferenca_meta"] == -2.0 and p[2025]["situacao_meta"] == "nao_atingiu"
    assert p[2025]["valor_detalhado"] == 58.37 and p[2025]["casas_detalhe"] == 2
    assert [m["edicao"] for m in mun["metas"]] == [2024, 2025, 2026]
    # As MESMAS comparações da consulta oficial.
    oficial = consulta.ica_da_rede(db, mundo["rede"])
    comps = {c["edicao"]: c for c in oficial["territorios"][0]["comparacoes"]}
    assert {e: (comps[e]["diferenca_pp"], comps[e]["situacao"]) for e in comps} == {
        2024: (0.0, "inconclusivo"), 2025: (-2.0, "nao_atingiu")}
    # SP e Brasil na rede PÚBLICA: contexto, não comparável.
    for id_ in ("uf_rede_publica", "brasil_rede_publica"):
        s = _serie(dados, id_)
        assert s["papel"] == "contexto" and s["comparavel"] is False
        assert "rede PÚBLICA" in s["motivo_nao_comparavel"]
    assert str(p[2025]["fonte_id"]) in dados["fontes"]
    assert dados["fontes"][str(p[2025]["fonte_id"])]["arquivo_nome"] == "arquivo_ficticio.csv"


def test_ica_por_escola_e_recusado(mundo):
    alfa = mundo["escolas"]["alfa"].id
    for params in ({"escola_id": alfa}, {"visao": "escolas", "edicao": 2025}):
        r = mundo["c"].get(URL.format(rede=mundo["rede"].id) + "/ica", params=params)
        assert r.status_code == 400
        assert "o ica não existe por escola" in r.json()["detail"].lower()


def test_ideb_metas_so_ate_2021_e_empate_atinge(mundo):
    dados = _get(mundo, "/ideb")
    p = _pontos(_serie(dados, "rede_municipal"))
    assert (p[2019]["valor"], p[2019]["meta"], p[2019]["situacao_meta"]) == (5.8, 5.8, "atingiu")
    assert p[2021]["diferenca_meta"] == -0.6 and p[2021]["situacao_meta"] == "nao_atingiu"
    assert p[2023]["meta"] is None and p[2023]["situacao_meta"] is None
    assert p[2023]["motivo_sem_meta"] == consulta_ideb.SEM_META_DEPOIS_DO_CICLO
    assert "depois de 2021" in p[2023]["texto_sem_meta"]
    br = _serie(dados, "brasil_redes_municipais")
    assert br["papel"] == "referencia" and br["comparavel"] is True
    assert dados["filtros"]["componente"] is None


def test_filtros_etapa_componente_e_intervalo(mundo):
    dados = _get(mundo, "/saresp", etapa="2_ano", componente="mt")
    assert dados["filtros"] == {"etapa": "2_ano", "componente": "mt", "escola_id": None,
                                "de": None, "ate": None, "visao": "serie", "edicao": None}
    assert [p["valor"] for p in _serie(dados, "rede_municipal")["pontos"]] == [160.9]
    assert [q["entre"] for q in dados["quebras"]] == [[2022, 2023], [2025, 2026]]
    assert any("NÃO é comparável ao ICA" in a for a in dados["avisos"])
    # de–até recorta as edições (o Ideb 2019–2023 vira só 2021).
    ideb = _get(mundo, "/ideb", de=2020, ate=2022)
    assert [p["edicao"] for p in _serie(ideb, "rede_municipal")["pontos"]] == [2021]
    # Filtro que não existe: 400 com o motivo; indicador que não existe: 404.
    c, rede = mundo["c"], mundo["rede"].id
    assert c.get(URL.format(rede=rede) + "/saresp", params={"etapa": "9_ano"}).status_code == 400
    assert c.get(URL.format(rede=rede) + "/ideb", params={"componente": "lp"}).status_code == 400
    invertido = {"de": 2025, "ate": 2020}
    assert c.get(URL.format(rede=rede) + "/saresp", params=invertido).status_code == 400
    assert c.get(URL.format(rede=rede) + "/nada").status_code == 404
    assert c.get(URL.format(rede=rede) + "/saresp", params={"visao": "escolas"}).status_code == 400


def test_filtro_por_escola_traz_a_escola_e_a_rede_como_referencia(mundo):
    alfa = mundo["escolas"]["alfa"]
    dados = _get(mundo, "/saresp", escola_id=alfa.id, etapa="2_ano", componente="mt")
    principal = _serie(dados, f"escola_{alfa.id}")
    assert principal["papel"] == "principal" and principal["abrangencia"] == "escola"
    (p,) = principal["pontos"]
    # Alfa não tem o MT do 2º ano no arquivo: ausência com o motivo da fonte.
    assert p["valor"] is None and p["motivo_ausencia"] == "nao_divulgado"
    assert _serie(dados, "rede_municipal")["papel"] == "referencia"
    assert {e["id"]: e["tem_dado"] for e in dados["opcoes"]["escolas"]}[alfa.id] is False
    r = mundo["c"].get(URL.format(rede=mundo["rede"].id) + "/saresp",
                       params={"escola_id": 999999})
    assert r.status_code == 404


def test_ausencia_nao_e_zero_em_todas_as_escolas(mundo):
    esc = mundo["escolas"]
    dados = _get(mundo, "/saresp", visao="escolas", edicao=2025)
    linhas = {e["escola_id"]: e for e in dados["escolas"]}
    assert linhas[esc["delta"].id]["valor"] is None
    assert linhas[esc["delta"].id]["motivo_ausencia"] == consulta_saresp.MOTIVO_FORA_DO_ARQUIVO
    assert linhas[esc["gama"].id]["motivo_ausencia"] == consulta_saresp.MOTIVO_SEM_INEP
    assert linhas[esc["gama"].id]["texto_ausencia"] == "a escola está sem código INEP no cadastro"
    assert not any(e["valor"] == 0 for e in dados["escolas"])
    ideb = _get(mundo, "/ideb", visao="escolas", edicao=2021)
    beta = next(e for e in ideb["escolas"] if e["escola_id"] == esc["beta"].id)
    assert beta["valor"] is None and beta["motivo_ausencia"] == "nao_divulgado"
    ebano = next(e for e in ideb["escolas"] if e["escola_id"] == esc["ebano"].id)
    assert ebano["valor"] is None and ebano["motivo_ausencia"] == consulta_ideb.MOTIVO_SEM_RESULTADO


def test_estimativa_constela_nunca_entra_na_serie_oficial(mundo):
    delta = mundo["escolas"]["delta"]
    # SARESP: Delta só tem a Estimativa Constela (233,3) — o ponto oficial é nulo, com o
    # motivo da consulta oficial (a escola não está no arquivo importado).
    saresp = _get(mundo, "/saresp", escola_id=delta.id)
    (p,) = _serie(saresp, f"escola_{delta.id}")["pontos"]
    assert p["valor"] is None and p["motivo_ausencia"] == "fora_do_arquivo"
    oficiais = [_get(mundo, "/saresp")["series"], saresp["series"],
                _get(mundo, "/saresp", visao="escolas", edicao=2025)["escolas"],
                _get(mundo)["destaques"], _get(mundo, "/ideb")["series"]]
    texto = json.dumps(oficiais)
    assert "233.3" not in texto


def test_numero_sem_registro_aparece_marcado_como_na_consulta_oficial(mundo):
    """RD2: o Ideb 2023 da Delta (7,7) foi gravado antes pelo 1 clique, sem
    ``importacao_id``. A consulta oficial o mostra marcado "sem_registro"; a análise também
    — na série da escola e na visão por escolas —, sem fonte, e nunca num destaque."""
    delta = mundo["escolas"]["delta"]
    ideb = _get(mundo, "/ideb", escola_id=delta.id)
    p23 = _pontos(_serie(ideb, f"escola_{delta.id}"))[2023]
    assert p23["valor"] == 7.7 and p23["motivo_ausencia"] is None
    assert p23["proveniencia"] == "sem_registro" and p23["fonte_id"] is None
    assert p23["texto_proveniencia"] == svc.TEXTO_SEM_REGISTRO
    assert p23["difere_do_oficial"] is False
    assert any("sem registro oficial" in a for a in ideb["avisos"])
    linhas = {e["escola_id"]: e for e in
              _get(mundo, "/ideb", visao="escolas", edicao=2023)["escolas"]}
    assert linhas[delta.id]["valor"] == 7.7 and linhas[delta.id]["proveniencia"] == "sem_registro"
    alfa = linhas[mundo["escolas"]["alfa"].id]
    assert alfa["proveniencia"] == "oficial" and alfa["texto_proveniencia"] is None
    # Nunca num destaque (o destaque é só o número oficial da rede).
    assert "7.7" not in json.dumps(_get(mundo)["destaques"])


def test_numero_sem_registro_que_difere_do_arquivo_oficial(db, mundo):
    """A importação oficial recusou (resposta "não") trocar o número da Delta pelo do
    arquivo: a consulta diz ``difere_do_oficial`` e a análise diz o mesmo, por extenso."""
    from app.services import avaliacoes as svc_avaliacoes
    delta = mundo["escolas"]["delta"]
    av = svc_avaliacoes.obter_avaliacao(db, "ideb")
    imp = db.get(ImportacaoIndicador, mundo["imps"]["ideb_escolas"].id)
    imp.resumo = {**imp.resumo, "substituir_calculadas": False,
                  "substituicoes_previa": [[av.id, 2023, "ideb", delta.id, "anos_iniciais",
                                            None, 7.7, None]]}
    db.commit()
    dados = _get(mundo, "/ideb", visao="escolas", edicao=2023)
    linha = next(e for e in dados["escolas"] if e["escola_id"] == delta.id)
    assert linha["difere_do_oficial"] is True
    assert linha["texto_proveniencia"] == f"{svc.TEXTO_SEM_REGISTRO}; {svc.TEXTO_DIFERE}"
    cat = _get(mundo)
    assert cat["sem_registro_oficial"][0]["difere_do_oficial"] == 1
    sr = next(a for a in cat["alertas"] if a["tipo"] == "sem_registro")
    assert "1 difere do arquivo oficial" in sr["texto"]


def test_avisos_sao_os_da_consulta_oficial(db, mundo):
    """M9: o período da comparabilidade do Ideb é o das edições reais (2019–2023, não
    "2005–2023") e o aviso dos níveis do SARESP é o da consulta (muda quando um corte for
    confirmado)."""
    ideb = _get(mundo, "/ideb")
    oficial = consulta_ideb.ideb_da_rede(db, mundo["rede"])["avisos"]
    assert oficial["comparabilidade"] in ideb["avisos"]
    assert any("(2019–2023)" in a for a in ideb["avisos"])
    assert not any("2005–2023" in a for a in ideb["avisos"])
    saresp = _get(mundo, "/saresp")
    niveis = consulta_saresp.saresp_da_rede(db, mundo["rede"])["niveis"]["aviso"]
    assert niveis in saresp["avisos"]
    assert niveis in next(i for i in _get(mundo)["indicadores"]
                          if i["chave"] == "saresp")["avisos"]


def test_aviso_do_saeb_no_contexto_de_uma_escola(mundo):
    """No contexto de UMA escola, o aviso diz que a nota é a média da escola e que a da
    rede vem da planilha (localização Total)."""
    alfa = mundo["escolas"]["alfa"]
    da_escola = _get(mundo, "/saeb", componente="lp", escola_id=alfa.id)["avisos"]
    assert any("A nota do Saeb da escola é a média dela" in a for a in da_escola)
    da_rede = _get(mundo, "/saeb", componente="lp")["avisos"]
    assert not any("média dela" in a for a in da_rede)


def test_iee_com_tps_zero_e_marcado_para_a_relacao(mundo):
    """M8: o IEE oficial da Beta foi calculado com médias de TPS = 0. O número oficial não
    é marcado instável, mas o ponto diz ``tps_zero`` (a relação o exclui)."""
    dados = _get(mundo, "/iee", visao="escolas", edicao=2025)
    linhas = {e["escola_id"]: e for e in dados["escolas"]}
    beta = linhas[mundo["escolas"]["beta"].id]
    assert beta["valor"] == 4.8 and beta["instavel"] is False and beta["tps_zero"] is True
    assert linhas[mundo["escolas"]["alfa"].id]["tps_zero"] is False
    assert any("ICM (Índice de Cumprimento de Meta)" in a for a in dados["avisos"])


def test_visao_por_escolas_em_ordem_de_nome_com_instaveis(mundo):
    esc = mundo["escolas"]
    dados = _get(mundo, "/saresp", visao="escolas", edicao=2025, etapa="5_ano", componente="lp")
    assert [e["nome"] for e in dados["escolas"]] == [
        NOMES["ebano"], NOMES["alfa"], NOMES["beta"], NOMES["delta"], NOMES["gama"]]
    # A ordem NÃO é por valor: 205,5 / 210,3 / 190,7 / — / —.
    assert [e["valor"] for e in dados["escolas"]] == [205.5, 210.3, 190.7, None, None]
    beta = next(e for e in dados["escolas"] if e["escola_id"] == esc["beta"].id)
    assert beta["instavel"] is True                      # TPS = 0
    assert all(e["instavel"] is False for e in dados["escolas"] if e["escola_id"] != esc["beta"].id)
    assert any("não é ranking" in a for a in dados["avisos"])
    assert all(str(e["fonte_id"]) in dados["fontes"] for e in dados["escolas"] if e["fonte_id"])
    assert dados["series"] == []


def test_iee_meta_pelo_icm_oficial_e_diferenca_na_precisao_publicada(mundo):
    esc = mundo["escolas"]
    dados = _get(mundo, "/iee", visao="escolas", edicao=2025)
    linhas = {e["escola_id"]: e for e in dados["escolas"]}
    alfa, beta, ebano = linhas[esc["alfa"].id], linhas[esc["beta"].id], linhas[esc["ebano"].id]
    assert (alfa["valor"], alfa["meta"], alfa["diferenca_meta"]) == (5.12, 5.46, -0.34)
    assert alfa["situacao_meta"] == "nao_atingiu" and alfa["icm"] == 0.0
    assert beta["situacao_meta"] == "atingiu" and beta["diferenca_meta"] == 0.3
    assert ebano["diferenca_meta"] == 0.0 and ebano["situacao_meta"] == "atingiu"
    # Sem escola, não há série do IEE (ele não existe para a rede): vazio, com o aviso.
    serie = _get(mundo, "/iee")
    assert serie["series"] == []
    assert any("escolha uma escola" in a for a in serie["avisos"])


def test_saeb_rede_pela_planilha_e_escola_pelo_arquivo_do_ideb(mundo):
    alfa = mundo["escolas"]["alfa"]
    dados = _get(mundo, "/saeb", componente="mt", escola_id=alfa.id)
    esc = _pontos(_serie(dados, f"escola_{alfa.id}"))
    assert esc[2023]["valor"] == 230.07 and esc[2023]["casas"] == 2
    assert esc[2019]["valor"] is None and esc[2019]["motivo_ausencia"]
    rede = _pontos(_serie(dados, "rede_municipal"))
    assert (rede[2019]["valor"], rede[2021]["valor"]) == (225.5, 219.75)
    assert dados["filtros"]["etapa"] == "5_ano"


def test_mesmos_numeros_da_consulta_oficial(db, mundo):
    """A normalização não muda número nenhum: o SARESP por escola é o de
    ``consulta_saresp`` (valor e casas), ponto a ponto."""
    oficial = consulta_saresp.saresp_da_rede(db, mundo["rede"])
    dados = _get(mundo, "/saresp", visao="escolas", edicao=2025, etapa="5_ano", componente="mt")
    for e in dados["escolas"]:
        linha = next(ln for ln in oficial["escolas"]["linhas"] if ln["escola_id"] == e["escola_id"])
        n = linha["por_edicao"][0]["proficiencia"]["5_ano"]["mt"]
        assert e["valor"] == (n["valor"] if n else None)
        if n and n["valor"] is not None:
            assert e["casas"] == n["casas_decimais"]


def test_secretaria_le_o_catalogo_da_propria_rede(db, mundo):
    db.add(Usuario(nome="sec", email="sec@analise.local", senha_hash=hash_senha("s3nh4"),
                   cargo="coordenador", rede_id=mundo["rede"].id))
    db.commit()
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    tok = c.post("/api/v1/auth/login", data={"username": "sec@analise.local",
                                             "password": "s3nh4"}).json()["access_token"]
    c.headers["Authorization"] = f"Bearer {tok}"
    r = c.get(URL.format(rede=mundo["rede"].id))
    assert r.status_code == 200 and r.json()["rede"]["id"] == mundo["rede"].id
    assert INEPS["alfa"] in r.text
