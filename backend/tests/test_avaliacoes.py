"""Avaliações externas: catálogo, análise de planilha, e importação de resultados
casando escola por CÓDIGO INEP (idempotente, escopada, só o que a fonte fornece).
"""
import io

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.security import hash_senha
from app.main import app
from app.models import (Aluno, AvaliacaoExterna, Escola, Matricula, Nota, Rede,
                        ResultadoAvaliacao, Turma, Usuario)
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


def test_importa_de_dentro_de_zip(db):
    # Os arquivos oficiais do INEP (IDEB/SAEB) vêm em ZIP — o importador extrai o
    # XLSX/CSV de dentro sozinho (o gestor não descompacta à mão).
    import zipfile
    rede = Rede(nome="Rede Zip", status="ativa"); db.add(rede); db.flush()
    _escola_inep(db, rede.id, "EM A", "35012345")
    db.commit()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("divulgacao_anos_iniciais_escolas_2023/planilha.csv", _PLANILHA.decode("utf-8"))
    conteudo = buf.getvalue()

    a = svc.analisar_planilha(conteudo, "ideb.zip")
    assert a["primeiras_linhas"][1] == ["CO_ESCOLA", "NO_ESCOLA", "IDEB_2023"]
    res = svc.importar_resultados(
        db, conteudo, "ideb.zip", avaliacao_chave="ideb", edicao=2023, indicador="ideb",
        unidade="indice", linha_dados=2, col_inep=0, col_valor=2, etapa_fixa="anos_iniciais",
        escopo_escolas=None)
    db.commit()
    assert res["casados"] == 1                          # casou EM A pelo INEP, de dentro do ZIP


def test_importar_endpoint_avaliacao_desconhecida_400(db, escola_completa, cliente):
    r = cliente.post(
        "/api/v1/avaliacoes/importar",
        data={"avaliacao": "enem", "edicao": 2023, "indicador": "x", "unidade": "y",
              "linha_dados": 1, "col_inep": 0, "col_valor": 1},
        files={"arquivo": ("x.csv", _PLANILHA, "text/csv")})
    assert r.status_code == 400


# --- Correlação / evolução ---------------------------------------------------

def _escola_engajada(db, rede_id, nome, inep, media):
    """Escola com engajamento (notas) para o _kpis_da_rede computar média_geral."""
    e = Escola(nome=nome, ano_letivo_ativo=2026, status="ativa", rede_id=rede_id,
               codigo_inep=inep)
    db.add(e); db.flush()
    turma = Turma(escola_id=e.id, nome="1A", ano_escolar="1º Ano", ano_letivo=2026,
                  status="ativa")
    db.add(turma); db.flush()
    for i in range(3):
        a = Aluno(escola_id=e.id, nome=f"Aluno {nome} {i}"); db.add(a); db.flush()
        db.add(Matricula(escola_id=e.id, aluno_id=a.id, turma_id=turma.id, ano_letivo=2026))
        db.add(Nota(escola_id=e.id, aluno_id=a.id, ano_letivo=2026, nota_geral=media,
                    posicao=i + 1))
    return e


def _importar_ideb(db, pares_inep_valor, edicao=2023):
    linhas = [["preambulo IDEB"], ["CO", "IDEB"]]
    linhas += [[inep, valor] for inep, valor in pares_inep_valor]
    svc.importar_resultados(db, _csv(linhas), "ideb.csv", avaliacao_chave="ideb",
                            edicao=edicao, indicador="ideb", unidade="indice",
                            linha_dados=2, col_inep=0, col_valor=1, escopo_escolas=None)


def test_pearson():
    assert svc._pearson([(1, 2), (2, 4), (3, 6)]) == 1.0        # perfeita positiva
    assert svc._pearson([(1, 6), (2, 4), (3, 2)]) == -1.0       # perfeita negativa
    assert svc._pearson([(1, 1), (2, 1)]) is None               # n<3
    assert svc._pearson([(1, 5), (2, 5), (3, 5)]) is None       # variância nula


def test_correlacao_cruza_avaliacao_com_engajamento(db):
    rede = Rede(nome="Rede Corr", status="ativa"); db.add(rede); db.flush()
    _escola_engajada(db, rede.id, "EM Alta", "35012345", 80.0)
    _escola_engajada(db, rede.id, "EM Media", "35067890", 60.0)
    _escola_engajada(db, rede.id, "EM Baixa", "35011111", 40.0)
    db.commit()
    _importar_ideb(db, [("35012345", "6,5"), ("35067890", "5,5"), ("35011111", "4,0")])
    db.commit()

    corr = svc.correlacao_rede(db, rede.id, avaliacao_chave="ideb", indicador="ideb",
                               edicao=2023, metrica="media_geral")
    assert corr["n"] == 3
    pts = {p["nome"]: p for p in corr["pontos"]}
    assert round(pts["EM Alta"]["y"], 1) == 6.5 and round(pts["EM Baixa"]["y"], 1) == 4.0
    assert pts["EM Alta"]["x"] > pts["EM Baixa"]["x"]      # engajamento acompanha
    assert corr["pearson"] is not None and corr["pearson"] > 0.9   # correlação forte +
    # Evolução: média da rede na edição 2023 = (6.5+5.5+4.0)/3 ≈ 5.33.
    assert corr["evolucao"][0]["edicao"] == 2023
    assert corr["evolucao"][0]["escolas"] == 3


def test_opcoes_rede_lista_series_existentes(db):
    rede = Rede(nome="Rede Op", status="ativa"); db.add(rede); db.flush()
    _escola_engajada(db, rede.id, "EM X", "35012345", 70.0)
    db.commit()
    _importar_ideb(db, [("35012345", "6,0")], edicao=2021)
    _importar_ideb(db, [("35012345", "6,2")], edicao=2023)
    db.commit()
    ops = svc.opcoes_rede(db, rede.id)
    assert len(ops) == 1
    s = ops[0]
    assert s["avaliacao"] == "ideb" and s["indicador"] == "ideb" and s["tipo"] == "indicador"
    assert s["edicoes"] == [2023, 2021]     # ambas as edições, mais recente primeiro


def test_correlacao_isola_a_rede_na_evolucao(db):
    # Regressão (achado da revisão): duas redes importam o MESMO IDEB nacional; a
    # evolução da rede A não pode misturar a escola da rede B.
    ra = Rede(nome="Rede A", status="ativa"); rb = Rede(nome="Rede B", status="ativa")
    db.add_all([ra, rb]); db.flush()
    _escola_engajada(db, ra.id, "EM A", "35012345", 70.0)
    _escola_engajada(db, rb.id, "EM B", "35067890", 70.0)
    db.commit()
    _importar_ideb(db, [("35012345", "6,0"), ("35067890", "4,0")])   # casa as duas (global)
    db.commit()

    corr = svc.correlacao_rede(db, ra.id, avaliacao_chave="ideb", indicador="ideb", edicao=2023)
    assert corr["n"] == 1
    assert corr["evolucao"][0]["escolas"] == 1        # só a escola da rede A
    assert corr["evolucao"][0]["media_valor"] == 6.0  # e NÃO (6+4)/2 = 5.0


def test_correlacao_agrega_por_escola_com_turmas(db):
    # Regressão (achado da revisão): resultado por TURMA (SARESP) vira 1 ponto por
    # ESCOLA (média das turmas), e a evolução conta escolas distintas, não linhas.
    rede = Rede(nome="Rede T", status="ativa"); db.add(rede); db.flush()
    e = _escola_engajada(db, rede.id, "EM T", "35012345", 70.0)
    db.commit()
    av = svc.obter_avaliacao(db, "saresp")
    for turma, valor in (("A", 6.0), ("B", 8.0)):
        db.add(ResultadoAvaliacao(avaliacao_id=av.id, edicao=2024, rede_id=rede.id,
                                  escola_id=e.id, codigo_inep="35012345",
                                  indicador="proficiencia", turma=turma, valor=valor,
                                  unidade="pontos"))
    db.commit()

    corr = svc.correlacao_rede(db, rede.id, avaliacao_chave="saresp",
                               indicador="proficiencia", edicao=2024)
    assert corr["n"] == 1                              # UM ponto (a escola), não dois
    assert round(corr["pontos"][0]["y"], 1) == 7.0     # média das turmas (6+8)/2
    assert corr["evolucao"][0]["escolas"] == 1         # UMA escola distinta
    assert corr["evolucao"][0]["media_valor"] == 7.0


def _login_rede(db, rede_id):
    db.add(Usuario(nome="Sec", email="sec@corr.gov", senha_hash=hash_senha("s3nh4correl1"),
                   cargo="coordenador", rede_id=rede_id))
    db.commit()
    c = TestClient(app)
    r = c.post("/api/v1/auth/login", data={"username": "sec@corr.gov", "password": "s3nh4correl1"})
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def test_endpoints_correlacao_e_opcoes(db):
    rede = Rede(nome="Rede End", status="ativa"); db.add(rede); db.flush()
    _escola_engajada(db, rede.id, "EM A", "35012345", 75.0)
    _escola_engajada(db, rede.id, "EM B", "35067890", 45.0)
    db.commit()
    _importar_ideb(db, [("35012345", "6,4"), ("35067890", "4,2")])
    db.commit()
    cliente = _login_rede(db, rede.id)

    ops = cliente.get(f"/api/v1/redes/{rede.id}/avaliacoes/opcoes").json()
    assert any(s["avaliacao"] == "ideb" for s in ops)
    corr = cliente.get(
        f"/api/v1/redes/{rede.id}/avaliacoes/correlacao"
        f"?avaliacao=ideb&indicador=ideb&edicao=2023&metrica=media_geral")
    assert corr.status_code == 200, corr.text
    assert corr.json()["n"] == 2
