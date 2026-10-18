"""Permissões definitivas dos indicadores oficiais e a leitura da ESCOLA (etapa E9).

Decisões do dono (17/10):

* D4 — SÓ o administrador global importa e desfaz QUALQUER avaliação ou indicador
  oficial: as rotas antigas (``/avaliacoes/analisar``, ``/importar``, ``/importar-preset``,
  ``DELETE /avaliacoes/resultados`` e o robô ``/avaliacoes/fontes``) e as novas
  (``/redes/{id}/indicadores/{ica,saresp,ideb,saeb}/...``: prévia, aplicação, lista das
  importações e desfazer);
* D5 — a Secretaria lê a rede inteira; o coordenador lê SÓ a própria escola (com as
  referências da rede, de SP e do Brasil; o ICA só como indicador da rede); o professor
  não lê nada; nada no painel público.

A matriz roda os seis perfis: admin global, Secretaria da rede, Secretaria de outra
rede, coordenador da escola, coordenador de outra escola e professor (mais o admin DA
escola, que gere a escola como o coordenador).

FIXTURES SINTÉTICAS: as fábricas INVENTADAS dos testes da E2, E4 e E6a (o município, os
INEPs, os nomes, as datas e todos os números são fictícios — decisão D13).
"""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.security import hash_senha
from app.main import app
from app.models import (Escola, FonteAvaliacao, ImportacaoIndicador, Rede, ResultadoAvaliacao,
                        Usuario)
from app.services import avaliacoes as svc
from app.services.indicadores import consulta_escola, pipeline_seduc
from tests.test_indicadores_ica import _aplicar as _aplicar_ica
from tests.test_indicadores_ica import arq_mun_2025
from tests.test_indicadores_ideb import _aplicar as _aplicar_ideb
from tests.test_indicadores_ideb import _preparar
from tests.test_indicadores_saresp import CODMUN, MUN, _iee, _municipio

OUTRO_MUN = "3599998"
SENHA = "s3nh4matriz"
NOME_IEE = "Indice de Excelencia Educacional 2025-2026_0.csv"
NOME_MUN = "Proficiência do SARESP por Municipio de 2025_0.csv"
LM = "Mon, 12 Jan 2026 09:00:00 GMT"                 # data INVENTADA

PERFIS = ("global", "secretaria", "secretaria_outra", "coordenador", "coordenador_outra",
          "professor", "admin_escola")
SO_GLOBAL = {"global"}


@pytest.fixture()
def mundo(db):
    """Rede sintética (ALFA e BETA, as do IEE; IDEB-ALFA, a do Ideb) + rede vizinha, e um
    usuário de cada perfil."""
    rede = Rede(nome="Rede Sintética", uf="SP", codigo_ibge=MUN,
                codigo_municipio_estadual=CODMUN, status="ativa")
    vizinha = Rede(nome="Rede Vizinha Fictícia", uf="SP", codigo_ibge=OUTRO_MUN, status="ativa")
    db.add_all([rede, vizinha])
    db.flush()
    alfa = Escola(nome="EMEF Sintética Alfa", ano_letivo_ativo=2026, rede_id=rede.id,
                  codigo_inep="35990001")
    beta = Escola(nome="EMEF Sintética Beta", ano_letivo_ativo=2026, rede_id=rede.id,
                  codigo_inep="35990002")
    ideb_alfa = Escola(nome="EMEF Sintética Ideb Alfa", ano_letivo_ativo=2026, rede_id=rede.id,
                       codigo_inep="35990101")
    ideb_beta = Escola(nome="EMEF Sintética Ideb Beta", ano_letivo_ativo=2026, rede_id=rede.id,
                       codigo_inep="35990102")
    da_vizinha = Escola(nome="EMEF Vizinha Fictícia", ano_letivo_ativo=2026,
                        rede_id=vizinha.id, codigo_inep="35880001")
    sem_rede = Escola(nome="Escola Sintética Sem Rede", ano_letivo_ativo=2026,
                      codigo_inep="35770001")
    db.add_all([alfa, beta, ideb_alfa, ideb_beta, da_vizinha, sem_rede])
    db.flush()
    usuarios = {
        "global": {"cargo": "admin", "is_global": True},
        "secretaria": {"cargo": "coordenador", "rede_id": rede.id},
        "secretaria_outra": {"cargo": "coordenador", "rede_id": vizinha.id},
        "coordenador": {"cargo": "coordenador", "escola_id": alfa.id},
        "coordenador_outra": {"cargo": "coordenador", "escola_id": beta.id},
        "professor": {"cargo": "professor", "escola_id": alfa.id},
        "admin_escola": {"cargo": "admin", "escola_id": alfa.id},
    }
    hash_ = hash_senha(SENHA)
    for perfil, campos in usuarios.items():
        db.add(Usuario(nome=perfil, email=f"{perfil}@matriz.local", senha_hash=hash_, **campos))
    db.commit()
    clientes = {}
    for perfil in usuarios:
        c = TestClient(app)
        r = c.post("/api/v1/auth/login",
                   data={"username": f"{perfil}@matriz.local", "password": SENHA})
        assert r.status_code == 200, r.text
        c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        clientes[perfil] = c
    return {"rede": rede, "vizinha": vizinha, "alfa": alfa, "beta": beta,
            "ideb_alfa": ideb_alfa, "ideb_beta": ideb_beta, "da_vizinha": da_vizinha,
            "sem_rede": sem_rede, "c": clientes}


def _matriz(mundo, chamada, permitidos: set[str], *, ok=(200, 201)) -> dict:
    """Roda ``chamada(cliente)`` em cada perfil: os permitidos NÃO recebem 401/403 (e, se
    ``ok`` for dado, recebem um desses códigos); os demais recebem 403."""
    codigos = {}
    for perfil in PERFIS:
        r = chamada(mundo["c"][perfil])
        codigos[perfil] = r.status_code
        if perfil in permitidos:
            assert r.status_code not in (401, 403), (perfil, r.status_code, r.text)
            if ok is not None:
                assert r.status_code in ok, (perfil, r.status_code, r.text)
        else:
            assert r.status_code == 403, (perfil, r.status_code, r.text)
    return codigos


# =============================================================================
# D4 — importar e desfazer: só o admin global (rotas antigas)
# =============================================================================

_CSV = b"INEP;V\n35990001;6,1\n35990002;5,7"
_FORM_IMPORTAR = {"avaliacao": "ideb", "edicao": "2023", "indicador": "ideb",
                  "unidade": "indice", "linha_dados": "1", "col_inep": "0", "col_valor": "1",
                  "etapa_fixa": "anos_iniciais"}


def test_rotas_antigas_de_importacao_e_desfazer_so_do_admin_global(db, mundo):
    _matriz(mundo, lambda c: c.post("/api/v1/avaliacoes/analisar",
                                    files={"arquivo": ("x.csv", _CSV)}), SO_GLOBAL)
    # Ninguém além do global grava: a contagem só sobe com a importação dele.
    _matriz(mundo, lambda c: c.post("/api/v1/avaliacoes/importar", data=_FORM_IMPORTAR,
                                    files={"arquivo": ("x.csv", _CSV)}), SO_GLOBAL)
    db.expire_all()
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 2
    saresp = b"INEP;COMP;PROF\n35990001;portugues;183,3"
    _matriz(mundo, lambda c: c.post("/api/v1/avaliacoes/importar-preset",
                                    data={"preset": "saresp_ai", "edicao": "2024"},
                                    files={"arquivo": ("saresp.csv", saresp)}), SO_GLOBAL)
    db.expire_all()
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 3
    # Desfazer (DELETE da série): a Secretaria e o coordenador não apagam nem a da escola
    # deles; o global apaga a série inteira (as duas escolas).
    url = ("/api/v1/avaliacoes/resultados?avaliacao=ideb&edicao=2023&indicador=ideb"
           "&etapa=anos_iniciais")
    for perfil in PERFIS:
        if perfil != "global":
            assert mundo["c"][perfil].delete(url).status_code == 403, perfil
    db.expire_all()
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 3
    r = mundo["c"]["global"].delete(url)
    assert r.status_code == 200 and r.json()["removidos"] == 2


def test_o_global_importa_em_todas_as_escolas_da_base_casando_pelo_inep(db, mundo):
    """Sem o recorte por perfil: o arquivo nacional casa as escolas de QUALQUER rede."""
    csv = b"INEP;V\n35990001;6,1\n35880001;5,2\n35770001;4,9\n35000000;3,3"
    r = mundo["c"]["global"].post("/api/v1/avaliacoes/importar", data=_FORM_IMPORTAR,
                                  files={"arquivo": ("x.csv", csv)})
    assert r.status_code == 200, r.text
    assert r.json()["casados"] == 3 and r.json()["inep_nao_casados"] == ["35000000"]
    db.expire_all()
    escolas = set(db.execute(select(ResultadoAvaliacao.escola_id)).scalars())
    assert escolas == {mundo["alfa"].id, mundo["da_vizinha"].id, mundo["sem_rede"].id}


def test_robo_de_coleta_so_do_admin_global(db, mundo, monkeypatch):
    corpo = {"avaliacao": "ideb", "nome": "IDEB sintético", "url": "https://exemplo.gov.br/x.csv",
             "edicao": 2023, "indicador": "ideb", "unidade": "indice", "cadencia": "manual",
             "mapeamento": {"linha_dados": 1, "col_inep": 0, "col_valor": 1,
                            "etapa_fixa": "anos_iniciais"}}
    _matriz(mundo, lambda c: c.get("/api/v1/avaliacoes/fontes"), SO_GLOBAL)
    for perfil in PERFIS:
        if perfil != "global":
            assert mundo["c"][perfil].post("/api/v1/avaliacoes/fontes",
                                           json=corpo).status_code == 403, perfil
    db.expire_all()
    assert db.scalar(select(func.count(FonteAvaliacao.id))) == 0
    r = mundo["c"]["global"].post("/api/v1/avaliacoes/fontes", json=corpo)
    assert r.status_code == 201, r.text
    fid = r.json()["id"]
    # Coletar baixa o arquivo: o download é substituído (nenhum teste sai para a internet).
    monkeypatch.setattr(svc, "baixar_url", lambda url, **kw: _CSV)
    _matriz(mundo, lambda c: c.post(f"/api/v1/avaliacoes/fontes/{fid}/coletar"), SO_GLOBAL)
    _matriz(mundo, lambda c: c.put(f"/api/v1/avaliacoes/fontes/{fid}?ativo=false"), SO_GLOBAL)
    for perfil in PERFIS:
        if perfil != "global":
            assert mundo["c"][perfil].delete(f"/api/v1/avaliacoes/fontes/{fid}").status_code == 403
    assert mundo["c"]["global"].delete(f"/api/v1/avaliacoes/fontes/{fid}").status_code == 200


def test_leitura_do_catalogo_e_dos_presets_segue_aberta_a_quem_esta_logado(mundo):
    _matriz(mundo, lambda c: c.get("/api/v1/avaliacoes"), set(PERFIS))
    _matriz(mundo, lambda c: c.get("/api/v1/avaliacoes/presets-import"), set(PERFIS))


# =============================================================================
# D4 — importar, listar e desfazer os indicadores novos: só o admin global
# =============================================================================

_FAMILIAS = ("ica", "saresp", "ideb", "saeb")


def _rota(familia: str, rede_id: int, resto: str) -> str:
    # O ICA (a primeira família) lista e desfaz em /indicadores/importacoes, sem o nome.
    meio = "" if familia == "ica" and resto.startswith("importacoes") else f"{familia}/"
    return f"/api/v1/redes/{rede_id}/indicadores/{meio}{resto}"


@pytest.mark.parametrize("familia", _FAMILIAS)
def test_indicadores_novos_importar_listar_desfazer_so_do_admin_global(db, mundo, familia):
    rede_id = mundo["rede"].id
    lixo = {"arquivo": ("arquivo.csv", b"nada a ver")}
    # Prévia: o global passa da permissão (o arquivo é recusado: 400); os outros, 403.
    _matriz(mundo, lambda c: c.post(_rota(familia, rede_id, "previa"), files=lixo),
            SO_GLOBAL, ok=(400,))
    _matriz(mundo, lambda c: c.post(_rota(familia, rede_id, "aplicar"), files=lixo,
                                    data={"previa_id": "999999"}), SO_GLOBAL, ok=(400, 404))
    _matriz(mundo, lambda c: c.get(_rota(familia, rede_id, "importacoes")), SO_GLOBAL)
    _matriz(mundo, lambda c: c.post(_rota(familia, rede_id, "importacoes/999999/desfazer")),
            SO_GLOBAL, ok=(400, 404))
    db.expire_all()
    assert db.scalar(select(func.count(ImportacaoIndicador.id))) == 0


def test_desfazer_uma_importacao_aplicada_so_o_admin_global(db, mundo):
    """Com uma importação REAL aplicada (IEE sintético): ninguém além do global a desfaz,
    e ela continua aplicada até ele desfazer."""
    rede = mundo["rede"]
    p = pipeline_seduc.previa(db, rede, _iee(), NOME_IEE, usuario_id=None)
    db.commit()
    a = pipeline_seduc.aplicar(db, rede, p["id"], _iee(), NOME_IEE, usuario_id=None)
    db.commit()
    url = f"/api/v1/redes/{rede.id}/indicadores/saresp/importacoes/{a['id']}/desfazer"
    for perfil in PERFIS:
        if perfil != "global":
            assert mundo["c"][perfil].post(url).status_code == 403, perfil
    db.expire_all()
    assert db.get(ImportacaoIndicador, a["id"]).status == "aplicada"
    r = mundo["c"]["global"].post(url)
    assert r.status_code == 200 and r.json()["status"] == "desfeita"


# =============================================================================
# D5 — leitura da REDE: Secretaria da rede e admin global
# =============================================================================

@pytest.mark.parametrize("familia", ("ica", "saresp", "ideb"))
def test_leitura_da_rede_secretaria_da_rede_e_admin_global(mundo, familia):
    url = f"/api/v1/redes/{mundo['rede'].id}/indicadores/{familia}"
    _matriz(mundo, lambda c: c.get(url), {"global", "secretaria"})


# =============================================================================
# D5 — leitura da ESCOLA: coordenador (ou admin) da escola, Secretaria da rede, global
# =============================================================================

def _url_escola(escola_id: int) -> str:
    return f"/api/v1/escolas/{escola_id}/indicadores"


def test_leitura_da_escola_matriz_de_perfis(mundo):
    alfa = mundo["alfa"]
    _matriz(mundo, lambda c: c.get(_url_escola(alfa.id)),
            {"global", "secretaria", "coordenador", "admin_escola"}, ok=(200,))
    # A escola da OUTRA rede: só o global e a Secretaria dela.
    viz = mundo["da_vizinha"]
    _matriz(mundo, lambda c: c.get(_url_escola(viz.id)), {"global", "secretaria_outra"},
            ok=(200,))
    # A BETA: o coordenador dela (``coordenador_outra``) lê; o da ALFA, não.
    beta = mundo["beta"]
    _matriz(mundo, lambda c: c.get(_url_escola(beta.id)),
            {"global", "secretaria", "coordenador_outra"}, ok=(200,))
    assert mundo["c"]["global"].get(_url_escola(999999)).status_code == 404
    assert mundo["c"]["coordenador"].get(_url_escola(999999)).status_code == 404


def test_professor_nao_le_nem_a_propria_escola(mundo):
    r = mundo["c"]["professor"].get(_url_escola(mundo["alfa"].id))
    assert r.status_code == 403 and "coordenação" in r.json()["detail"]


def _texto(dados) -> str:
    return json.dumps(dados, ensure_ascii=False)


def test_escola_le_o_saresp_oficial_dela_com_as_referencias_e_sem_outra_escola(db, mundo):
    rede = mundo["rede"]
    for conteudo, nome in ((_iee(), NOME_IEE), (_municipio(), NOME_MUN)):
        p = pipeline_seduc.previa(db, rede, conteudo, nome, usuario_id=None,
                                  url_origem="https://dados.educacao.sp.gov.br/exemplo.csv",
                                  last_modified_origem=LM)
        db.commit()
        pipeline_seduc.aplicar(db, rede, p["id"], conteudo, nome, usuario_id=None)
        db.commit()
    r = mundo["c"]["coordenador"].get(_url_escola(mundo["alfa"].id))
    assert r.status_code == 200, r.text
    dados = r.json()
    assert dados["escola"] == {"id": mundo["alfa"].id, "nome": "EMEF Sintética Alfa",
                               "codigo_inep": "35990001", "status": "ativa", "pendencia": None}
    assert dados["rede"]["nome"] == "Rede Sintética" and dados["rede"]["codigo_ibge"] == MUN
    saresp = dados["saresp"]
    (ed,) = saresp["por_edicao"]
    assert ed["edicao"] == 2025 and ed["tem_resultado"] is True
    prof = ed["proficiencia"]
    assert prof["2_ano"]["lp"]["valor"] == 148.3 and prof["5_ano"]["mt"]["valor"] == 196.8
    # Cada número com a fonte (o arquivo do IEE) — e a fonte está na lista de fontes.
    fonte = prof["5_ano"]["mt"]["fonte"]
    assert fonte["arquivo_nome"] == NOME_IEE and fonte["data_arquivo"] == "2026-01-12"
    assert fonte["importacao_id"] in {f["importacao_id"] for f in saresp["fontes"]}
    assert ed["participacao"]["2_ano"]["valor"] == 72.4 and ed["tps"]["valor"] == 1
    assert ed["iee"]["valor"] == 5.12 and ed["meta"]["valor"] == 5.46
    assert ed["fonte_da_edicao"]["arquivo_nome"] == NOME_IEE
    # As referências: a rede municipal (com número) e o Estado (sem arquivo: sem dado).
    terr = {t["chave"]: t for t in saresp["territorios"]}
    assert terr["rede_municipal"]["tem_dados"] is True
    assert terr["estado_redes_municipais"]["tem_dados"] is False
    serie_lp5 = next(s for s in terr["rede_municipal"]["series"]
                     if (s["etapa"], s["componente"]) == ("5_ano", "lp"))
    assert [(n["edicao"], n["valor"]) for n in serie_lp5["numeros"]] == [(2025, 193.6)]
    # Sem ranking e sem outra escola: nem a tabela, nem a cobertura nominal, nem o aviso.
    assert "cobertura" not in saresp and "escolas" not in saresp
    assert "sem_ranking" not in saresp["avisos"]
    texto = _texto(dados)
    for outra in ("Beta", "BETA", "35990002", "GAMA", "35990003", "Ideb Alfa"):
        assert outra not in texto, outra
    assert dados["tem_dados_escola"] is True and saresp["tem_dados_escola"] is True


def test_a_secretaria_le_a_escola_da_rede_com_os_mesmos_numeros_da_tela_da_rede(db, mundo):
    rede = mundo["rede"]
    p = pipeline_seduc.previa(db, rede, _iee(), NOME_IEE, usuario_id=None)
    db.commit()
    pipeline_seduc.aplicar(db, rede, p["id"], _iee(), NOME_IEE, usuario_id=None)
    db.commit()
    escola = mundo["c"]["secretaria"].get(_url_escola(mundo["beta"].id)).json()
    da_rede = mundo["c"]["secretaria"].get(f"/api/v1/redes/{rede.id}/indicadores/saresp").json()
    linha = next(ln for ln in da_rede["escolas"]["linhas"] if ln["escola_id"] == mundo["beta"].id)
    (ed,) = escola["saresp"]["por_edicao"]
    (ed_rede,) = linha["por_edicao"]
    assert {k: v for k, v in ed.items() if k != "fonte_da_edicao"} == ed_rede
    # A BETA não tem o 2º ano no arquivo: o motivo aparece, nunca 0.
    assert ed["proficiencia"]["2_ano"]["lp"]["valor"] is None
    assert ed["proficiencia"]["2_ano"]["lp"]["motivo_ausencia"]


def test_escola_le_o_ideb_dela_e_a_rede_municipal_sem_outra_escola(db, mundo, tmp_path):
    rede = mundo["rede"]
    _aplicar_ideb(db, rede, _preparar(tmp_path).pacote)
    admin = mundo["c"]["global"]
    dados = admin.get(_url_escola(mundo["ideb_alfa"].id)).json()
    ideb = dados["ideb"]
    assert ideb["edicoes"] == [2019, 2021, 2023]
    ed = {e["edicao"]: e for e in ideb["serie"]}
    assert ed[2019]["ideb"]["valor"] is not None and ed[2019]["ideb"]["proveniencia"] == "oficial"
    fontes = {f["importacao_id"] for f in ideb["fontes"]}
    assert ed[2019]["ideb"]["fonte_id"] in fontes
    assert ed[2023]["fonte_da_edicao_id"] in fontes
    assert set(ideb["rede_municipal"]) >= {"ideb", "saeb", "avisos", "tem_dados"}
    assert ideb["participacao"]["disponivel"] is False
    assert "cobertura" not in ideb and "escolas" not in ideb and "pendentes" not in ideb
    assert "sem_ranking" not in ideb["avisos"]
    texto = _texto(dados)
    assert "35990102" not in texto and "Ideb Beta" not in texto and "SINTETICA BETA" not in texto
    # A escola que não tem linha no arquivo vê a edição com o motivo, sem número.
    alfa = admin.get(_url_escola(mundo["alfa"].id)).json()["ideb"]
    assert alfa["edicoes"] == [2019, 2021, 2023]
    assert all(e["ideb"] is None and e["motivo"] for e in alfa["serie"])
    assert alfa["tem_dados_escola"] is False


def test_o_ica_aparece_so_como_indicador_da_rede(db, mundo):
    _aplicar_ica(db, mundo["rede"], arq_mun_2025())
    dados = mundo["c"]["coordenador"].get(_url_escola(mundo["alfa"].id)).json()
    ica = dados["ica"]
    assert ica["papel"] == consulta_escola.PAPEL_REFERENCIA_REDE
    assert "não publica o ICA por escola" in ica["aviso"]
    mun = next(t for t in ica["territorios"] if t["abrangencia"] == "municipio")
    assert mun["rede_ensino"] == "municipal" and mun["tem_dados"] is True
    assert [r["edicao"] for r in mun["resultados"]] == [2023, 2024, 2025]
    assert ica["fontes"] and ica["fontes"][0]["arquivo_nome"]
    # O ICA não conta como número DA ESCOLA.
    assert dados["tem_dados_escola"] is False and dados["tem_dados"] is True
    assert "ica_da_rede" in dados["avisos"]


def test_escola_sem_rede_diz_a_pendencia_e_nao_inventa_referencia(mundo):
    global_ = mundo["c"]["global"]
    dados = global_.get(_url_escola(mundo["sem_rede"].id)).json()
    assert dados["rede"] is None and "sem_rede" in dados["pendencias"]
    assert dados["saresp"] is None and dados["ideb"] is None and dados["ica"] is None
    assert dados["tem_dados"] is False and "sem_rede" in dados["avisos"]


def test_escola_sem_inep_tem_a_pendencia_de_cadastro(db, mundo):
    mundo["alfa"].codigo_inep = None
    db.commit()
    dados = mundo["c"]["coordenador"].get(_url_escola(mundo["alfa"].id)).json()
    assert dados["escola"]["pendencia"] == "codigo_inep" and "codigo_inep" in dados["pendencias"]


def test_nada_no_painel_publico():
    """Nenhuma rota pública (sem login) expõe os indicadores oficiais."""
    rotas = [r.path for r in app.routes if hasattr(r, "path")]
    assert not [p for p in rotas if "indicadores" in p and "/publico" in p]
    assert TestClient(app).get(_url_escola(1)).status_code == 401
