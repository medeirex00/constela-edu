"""Avaliações externas: catálogo, análise de planilha, e importação de resultados
casando escola por CÓDIGO INEP (idempotente, escopada, só o que a fonte fornece).
"""
import io

from sqlalchemy import func, select

from app.core.security import hash_senha
from app.models import (AvaliacaoExterna, Escola, Rede, ResultadoAvaliacao, Usuario)
from app.services import avaliacoes as svc


def _csv(linhas: list[list[str]]) -> bytes:
    return "\n".join(";".join(c for c in linha) for linha in linhas).encode("utf-8")


# Planilha "IDEB por escola" no estilo INEP: 1 linha de pré-âmbulo + cabeçalho + dados.
_PLANILHA = _csv([
    ["Resultados do IDEB 2023 - Anos Iniciais (documento oficial)"],
    ["CO_ESCOLA", "NO_ESCOLA", "IDEB_2023"],
    ["35012345", "EM Alfa", "6,1"],
    ["00035067890", "EM Beta", "5,3"],   # com zeros à esquerda / >8 díg → normaliza
    ["99999999", "EM de Outra Rede", "4,0"],
    ["", "linha vazia de valor", ""],    # ignorada (sem inep/valor)
])


def _escola_inep(db, rede_id, nome, inep):
    e = Escola(nome=nome, ano_letivo_ativo=2026, status="ativa", rede_id=rede_id,
               codigo_inep=inep)
    db.add(e)
    db.flush()
    return e


# --- Serviço: normalização + análise ----------------------------------------

def test_normalizar_inep():
    assert svc.normalizar_inep("35012345") == "35012345"
    assert svc.normalizar_inep("35012345.0") == "35012345"   # int-como-float do openpyxl
    assert svc.normalizar_inep("00035067890") == "35067890"  # 8 dígitos finais
    assert svc.normalizar_inep("123") == "00000123"          # zero-pad
    assert svc.normalizar_inep("  ") is None
    assert svc.normalizar_inep(None) is None


def test_analisar_planilha_devolve_grade_crua():
    a = svc.analisar_planilha(_PLANILHA, "ideb.csv")
    # 6 linhas: pré-âmbulo + cabeçalho + 3 dados + a linha com texto (só linhas
    # TOTALMENTE vazias somem). O inep/valor vazio dela é tratado na importação.
    assert a["linhas_lidas"] == 6
    assert a["primeiras_linhas"][0][0].startswith("Resultados do IDEB")
    assert a["primeiras_linhas"][1] == ["CO_ESCOLA", "NO_ESCOLA", "IDEB_2023"]


def test_analisar_xlsx():
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active
    ws.append(["CO_ESCOLA", "IDEB"]); ws.append([35012345, 6.1])
    buf = io.BytesIO(); wb.save(buf)
    a = svc.analisar_planilha(buf.getvalue(), "ideb.xlsx")
    assert a["primeiras_linhas"][0] == ["CO_ESCOLA", "IDEB"]
    assert a["primeiras_linhas"][1][0] == "35012345"   # int vira string sem ".0"


# --- Serviço: importação -----------------------------------------------------

def test_importa_casando_por_inep_e_ignora_nao_casado(db, escola_completa):
    rede = Rede(nome="Rede Aval", status="ativa"); db.add(rede); db.flush()
    _escola_inep(db, rede.id, "EM Alfa", "35012345")
    _escola_inep(db, rede.id, "EM Beta", "35067890")
    db.commit()

    res = svc.importar_resultados(
        db, _PLANILHA, "ideb.csv", avaliacao_chave="ideb", edicao=2023,
        indicador="ideb", unidade="indice", linha_dados=2, col_inep=0, col_valor=2,
        etapa_fixa="anos_iniciais", escopo_escolas=None)
    db.commit()

    assert res["casados"] == 2 and res["inseridos"] == 2
    assert res["nao_casados"] == 1          # 99999999 não existe
    assert res["ignorados"] == 1            # linha vazia
    linhas = db.execute(select(ResultadoAvaliacao)).scalars().all()
    assert {round(r.valor, 1) for r in linhas} == {6.1, 5.3}
    assert all(r.etapa == "anos_iniciais" and r.componente is None for r in linhas)
    assert all(r.indicador == "ideb" and r.unidade == "indice" for r in linhas)
    # IDEB entrou no catálogo como INDICADOR.
    av = db.execute(select(AvaliacaoExterna).where(AvaliacaoExterna.chave == "ideb")).scalar_one()
    assert av.tipo == "indicador"


def test_reimportar_atualiza_nao_duplica(db, escola_completa):
    rede = Rede(nome="Rede Idem", status="ativa"); db.add(rede); db.flush()
    _escola_inep(db, rede.id, "EM Alfa", "35012345")
    _escola_inep(db, rede.id, "EM Beta", "35067890")
    db.commit()
    comum = dict(avaliacao_chave="ideb", edicao=2023, indicador="ideb", unidade="indice",
                 linha_dados=2, col_inep=0, col_valor=2, etapa_fixa="anos_iniciais",
                 escopo_escolas=None)
    svc.importar_resultados(db, _PLANILHA, "ideb.csv", **comum); db.commit()
    # Segunda importação com valor alterado da 1ª escola.
    planilha2 = _csv([["preambulo"], ["CO", "NO", "IDEB"],
                      ["35012345", "EM Alfa", "6,8"], ["35067890", "EM Beta", "5,3"]])
    res = svc.importar_resultados(db, planilha2, "ideb.csv", **comum); db.commit()
    assert res["inseridos"] == 0 and res["atualizados"] == 2
    total = db.scalar(select(func.count(ResultadoAvaliacao.id)))
    assert total == 2                       # não duplicou
    alfa = db.execute(select(ResultadoAvaliacao).where(
        ResultadoAvaliacao.codigo_inep == "35012345")).scalar_one()
    assert round(alfa.valor, 1) == 6.8      # atualizou


def test_escopo_de_rede_nao_casa_escola_de_outra_rede(db):
    ra = Rede(nome="Rede A", status="ativa"); rb = Rede(nome="Rede B", status="ativa")
    db.add_all([ra, rb]); db.flush()
    _escola_inep(db, ra.id, "EM A", "35012345")
    _escola_inep(db, rb.id, "EM B", "35067890")
    db.commit()
    escopo_a = set(db.execute(select(Escola.id).where(Escola.rede_id == ra.id)).scalars())

    res = svc.importar_resultados(
        db, _PLANILHA, "ideb.csv", avaliacao_chave="ideb", edicao=2023, indicador="ideb",
        unidade="indice", linha_dados=2, col_inep=0, col_valor=2, etapa_fixa="ai",
        escopo_escolas=escopo_a)
    db.commit()
    assert res["casados"] == 1              # só a EM A (rede A); a EM B ficou fora do escopo
    assert res["nao_casados"] == 2


# --- Endpoints ---------------------------------------------------------------

def test_catalogo_endpoint(db, escola_completa, cliente):
    dados = cliente.get("/api/v1/avaliacoes").json()
    chaves = {a["chave"] for a in dados}
    assert {"saeb", "ideb", "saresp", "crianca_alfabetizada"} <= chaves
    ideb = next(a for a in dados if a["chave"] == "ideb")
    assert ideb["tipo"] == "indicador"


def test_importar_endpoint_escopa_pela_escola_do_admin(db, escola_completa, cliente):
    # O admin de teste é da escola (não global): só casa a PRÓPRIA escola.
    escola = escola_completa["escola"]
    escola.codigo_inep = "35012345"
    # SEGUNDA escola (de outra escola/rede) COM um INEP que ESTÁ na planilha: se o
    # escopo falhasse (fosse global), ela também casaria. Prova o filtro de escopo.
    db.add(Escola(nome="EM Fora do Escopo", ano_letivo_ativo=2026, status="ativa",
                  codigo_inep="35067890"))
    db.commit()

    r = cliente.post(
        "/api/v1/avaliacoes/importar",
        data={"avaliacao": "ideb", "edicao": 2023, "indicador": "ideb", "unidade": "indice",
              "linha_dados": 2, "col_inep": 0, "col_valor": 2, "etapa_fixa": "anos_iniciais"},
        files={"arquivo": ("ideb.csv", _PLANILHA, "text/csv")})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["casados"] == 1 and corpo["inseridos"] == 1  # só a do admin, não a 35067890
    db.expire_all()
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 1


def test_dimensao_mapeada_vazia_vira_null_nao_string_none(db, escola_completa):
    # Regressão (achado da revisão): coluna de dimensão MAPEADA mas com célula
    # ausente (linha curta) deve gravar NULL — nunca a string literal "None".
    rede = Rede(nome="Rede Dim", status="ativa"); db.add(rede); db.flush()
    _escola_inep(db, rede.id, "EM Alfa", "35012345")
    db.commit()
    planilha = _csv([["preambulo"], ["CO", "VALOR", "COMPONENTE"],
                     ["35012345", "234,5"]])   # linha curta: sem a coluna 2 (componente)
    res = svc.importar_resultados(
        db, planilha, "saeb.csv", avaliacao_chave="saeb", edicao=2023,
        indicador="proficiencia", unidade="escala_saeb", linha_dados=2,
        col_inep=0, col_valor=1, col_componente=2, escopo_escolas=None)
    db.commit()
    assert res["casados"] == 1
    r = db.execute(select(ResultadoAvaliacao)).scalars().one()
    assert r.componente is None   # e NÃO "None"


def test_importar_endpoint_avaliacao_desconhecida_400(db, escola_completa, cliente):
    r = cliente.post(
        "/api/v1/avaliacoes/importar",
        data={"avaliacao": "enem", "edicao": 2023, "indicador": "x", "unidade": "y",
              "linha_dados": 1, "col_inep": 0, "col_valor": 1},
        files={"arquivo": ("x.csv", _PLANILHA, "text/csv")})
    assert r.status_code == 400
