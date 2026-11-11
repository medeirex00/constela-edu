"""Duas redes com o MESMO código IBGE (auditoria S_G_INDICADORES-1). Tudo SINTÉTICO:
município 3599999 (não existe), INEPs 3599010x e números inventados das fábricas do Ideb.

* O cadastro (POST e PATCH /redes) recusa com 409 o código IBGE que já é de outra rede,
  e recusa o código que não tem 7 dígitos.
* Duas redes que JÁ têm o mesmo código (cadastradas antes da trava) não se misturam nas
  importações feitas daqui em diante: a rede B não lista, não aplica nem desfaz a
  importação da rede A, e o Ideb oficial de uma escola não some (com o motivo falso
  "cadastrada depois da importação") quando o admin importa o mesmo pacote pela outra rede.
"""
from sqlalchemy import func, select

from app.models import Escola, ImportacaoIndicador, Rede, ResultadoAvaliacao
from app.services.indicadores import consulta_ideb
from tests.test_indicadores_ideb import ALFA, BETA, MUN, _aplicar, _preparar, planilha

URL = "/api/v1/redes"


def test_cadastro_recusa_o_codigo_ibge_de_outra_rede(db, cliente_global):
    ra = cliente_global.post(URL, json={"nome": "Rede Inventada Norte", "uf": "SP",
                                        "codigo_ibge": MUN})
    assert ra.status_code == 201, ra.text
    assert ra.json()["codigo_ibge"] == MUN

    rb = cliente_global.post(URL, json={"nome": "Rede Inventada Sul", "uf": "SP",
                                        "codigo_ibge": MUN})
    assert rb.status_code == 409, rb.text
    assert "Rede Inventada Norte" in rb.json()["detail"] and MUN in rb.json()["detail"]
    assert db.execute(select(func.count()).select_from(Rede)).scalar_one() == 1

    # Sem código, a 2ª rede entra; o PATCH com o código da outra também é recusado.
    rb = cliente_global.post(URL, json={"nome": "Rede Inventada Sul", "uf": "SP"})
    assert rb.status_code == 201, rb.text
    patch = cliente_global.patch(f"{URL}/{rb.json()['id']}", json={"codigo_ibge": MUN})
    assert patch.status_code == 409, patch.text
    assert "Rede Inventada Norte" in patch.json()["detail"]
    db.expire_all()
    assert db.get(Rede, rb.json()["id"]).codigo_ibge is None

    # Regravar o próprio código não é conflito; "" limpa e libera o código.
    assert cliente_global.patch(f"{URL}/{ra.json()['id']}",
                                json={"codigo_ibge": MUN}).status_code == 200
    limpa = cliente_global.patch(f"{URL}/{ra.json()['id']}", json={"codigo_ibge": ""})
    assert limpa.status_code == 200 and limpa.json()["codigo_ibge"] is None
    assert cliente_global.patch(f"{URL}/{rb.json()['id']}",
                                json={"codigo_ibge": MUN}).status_code == 200


def test_cadastro_recusa_codigo_ibge_sem_7_digitos(db, cliente_global):
    for errado in ("35999", "359999X", "ABCDEFG"):
        r = cliente_global.post(URL, json={"nome": f"Rede Inventada {errado}",
                                           "codigo_ibge": errado})
        assert r.status_code == 422, (errado, r.text)
        assert "7 dígitos" in r.text
    criada = cliente_global.post(URL, json={"nome": "Rede Inventada Leste"}).json()
    r = cliente_global.patch(f"{URL}/{criada['id']}", json={"codigo_ibge": "35999"})
    assert r.status_code == 422 and "7 dígitos" in r.text
    db.expire_all()
    assert db.get(Rede, criada["id"]).codigo_ibge is None


def _ideb_2019(db, rede, nome):
    db.expire_all()
    d = consulta_ideb.ideb_da_rede(db, rede)
    linha = next(x for x in d["escolas"] if x["nome"] == nome)
    e19 = next(x for x in linha["serie"] if x["edicao"] == 2019)
    return (e19["ideb"] or {}).get("valor"), e19["motivo"]


def test_redes_antigas_com_o_mesmo_ibge_nao_misturam_as_importacoes(db, cliente_global,
                                                                     tmp_path):
    # Duas redes cadastradas ANTES da trava, com o mesmo código (direto no banco).
    rede_a = Rede(nome="Rede Inventada Antiga A", uf="SP", codigo_ibge=MUN, status="ativa")
    rede_b = Rede(nome="Rede Inventada Antiga B", uf="SP", codigo_ibge=MUN, status="ativa")
    db.add_all([rede_a, rede_b])
    db.flush()
    db.add_all([Escola(nome="EMEF Sintética Alfa", ano_letivo_ativo=2026, rede_id=rede_a.id,
                       codigo_inep="35990101"),
                Escola(nome="EMEF Sintética Beta", ano_letivo_ativo=2026, rede_id=rede_b.id,
                       codigo_inep="35990102")])
    db.commit()
    alfa_id = db.execute(select(Escola.id).where(Escola.codigo_inep == "35990101")).scalar_one()

    pacote = _preparar(tmp_path, planilha([ALFA, BETA])).pacote
    _, imp_a = _aplicar(db, rede_a, pacote)
    assert _ideb_2019(db, rede_a, "EMEF Sintética Alfa") == (1.5, None)
    # O mesmo pacote pela rede B: o Ideb da escola da rede A continua na tela da A.
    _, imp_b = _aplicar(db, rede_b, pacote)
    assert _ideb_2019(db, rede_a, "EMEF Sintética Alfa") == (1.5, None)
    assert _ideb_2019(db, rede_b, "EMEF Sintética Beta") == (1.5, None)
    # Reimportar pela A não esconde de novo o da B.
    _aplicar(db, rede_a, pacote, nome="pacote2.zip")
    assert _ideb_2019(db, rede_b, "EMEF Sintética Beta") == (1.5, None)
    assert _ideb_2019(db, rede_a, "EMEF Sintética Alfa") == (1.5, None)

    # A lista da rede B só tem a importação feita pela B.
    lista_b = cliente_global.get(f"{URL}/{rede_b.id}/indicadores/ideb/importacoes").json()
    assert [i["id"] for i in lista_b] == [imp_b["id"]]

    # Pela rede B, a importação da rede A "não existe": nada é apagado.
    def oficiais_da_alfa():
        db.expire_all()
        return db.execute(select(func.count()).select_from(ResultadoAvaliacao).where(
            ResultadoAvaliacao.escola_id == alfa_id,
            ResultadoAvaliacao.importacao_id.isnot(None))).scalar_one()

    antes = oficiais_da_alfa()
    assert antes > 0
    r = cliente_global.post(
        f"{URL}/{rede_b.id}/indicadores/ideb/importacoes/{imp_a['id']}/desfazer")
    assert r.status_code == 404, r.text
    assert oficiais_da_alfa() == antes
    assert db.get(ImportacaoIndicador, imp_a["id"]).status == "aplicada"


def test_redes_antigas_com_o_mesmo_ibge_nao_escondem_o_iee_uma_da_outra(db, cliente_global):
    """O mesmo no SARESP/IEE por escola (``consulta_saresp``): o IEE importado pela rede B
    não esconde o da escola da rede A, e a B não lista a importação da A."""
    from app.services.indicadores import consulta_saresp, pipeline_seduc
    from tests.test_indicadores_saresp import CODMUN, _iee
    from tests.test_indicadores_saresp import MUN as MUN_SARESP

    redes = [Rede(nome=f"Rede Inventada Antiga {x}", uf="SP", codigo_ibge=MUN_SARESP,
                  codigo_municipio_estadual=CODMUN, status="ativa") for x in "AB"]
    db.add_all(redes)
    db.flush()
    rede_a, rede_b = redes
    db.add_all([Escola(nome="EMEF Sintética Alfa", ano_letivo_ativo=2026, rede_id=rede_a.id,
                       codigo_inep="35990001"),
                Escola(nome="EMEF Sintética Beta", ano_letivo_ativo=2026, rede_id=rede_b.id,
                       codigo_inep="35990002")])
    db.commit()

    def importar(rede):
        nome = "Indice de Excelencia Educacional 2025-2026_0.csv"
        p = pipeline_seduc.previa(db, rede, _iee(), nome, usuario_id=None)
        db.commit()
        a = pipeline_seduc.aplicar(db, rede, p["id"], _iee(), nome, usuario_id=None)
        db.commit()
        return a

    def ed_2025(rede, nome):
        db.expire_all()
        d = consulta_saresp.saresp_da_rede(db, rede)
        linha = next(x for x in d["escolas"]["linhas"] if x["nome"] == nome)
        ed = next(e for e in linha["por_edicao"] if e["edicao"] == 2025)
        return ed["tem_resultado"], ed["motivo"]

    imp_a = importar(rede_a)
    assert ed_2025(rede_a, "EMEF Sintética Alfa") == (True, None)
    imp_b = importar(rede_b)
    assert ed_2025(rede_a, "EMEF Sintética Alfa") == (True, None)
    assert ed_2025(rede_b, "EMEF Sintética Beta") == (True, None)
    lista_b = cliente_global.get(f"{URL}/{rede_b.id}/indicadores/saresp/importacoes").json()
    assert [i["id"] for i in lista_b] == [imp_b["id"]]
    r = cliente_global.post(
        f"{URL}/{rede_b.id}/indicadores/saresp/importacoes/{imp_a['id']}/desfazer")
    assert r.status_code == 404, r.text
