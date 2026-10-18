"""Avaliações externas: catálogo, análise de planilha, e importação de resultados
casando escola por CÓDIGO INEP (idempotente, escopada, só o que a fonte fornece).
"""
import io

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.security import hash_senha
from app.main import app
from app.models import (Aluno, AvaliacaoExterna, Escola, Importacao, Matricula,
                        Nota, Rede, ResultadoAvaliacao, SnapshotElefante,
                        SnapshotMatific, Turma, Usuario)
from app.services import avaliacoes as svc
from app.services import scoring


def _csv(linhas: list[list[str]]) -> bytes:
    return "\n".join(";".join(c for c in linha) for linha in linhas).encode("utf-8")


# Rótulo da D1 (fixado aqui por extenso: mudar o texto exige mudar o teste).
_ROTULO_ESTIMATIVA = ("Estimativa Constela de alfabetização (SARESP 2º ano) — "
                      "não é o indicador oficial")
_ORGAO_ESTIMATIVA = "Constela (estimativa a partir do SARESP)"


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


def test_catalogo_inclui_caed_como_fonte_propria(db, escola_completa, cliente):
    """Item 2: CAEd é uma FONTE/tipo própria (orgao='CAEd') com avaliações separadas,
    sem alterar a série `crianca_alfabetizada` (mesma chave; o rótulo e o órgão
    exibidos mudaram pela D1 — ver test_rotulo_estimativa_*)."""
    dados = cliente.get("/api/v1/avaliacoes").json()
    por_chave = {a["chave"]: a for a in dados}
    assert por_chave["caed_fluencia"]["orgao"] == "CAEd"
    assert por_chave["caed_diagnostica"]["orgao"] == "CAEd"
    assert por_chave["caed_fluencia"]["tipo"] == "avaliacao"
    # A série do Constela continua na mesma chave — e não aparece sob o INEP/CAEd
    # (a tela agrupa o seletor pelo órgão).
    assert por_chave["crianca_alfabetizada"]["orgao"] == _ORGAO_ESTIMATIVA
    assert por_chave["crianca_alfabetizada"]["nome"] == _ROTULO_ESTIMATIVA


def test_importar_endpoint_so_do_admin_global_que_casa_toda_a_base(db, escola_completa, cliente,
                                                                    cliente_global):
    # Decisão D4 (E9): SÓ o admin global importa. Antes, o admin da escola importava
    # (escopado à própria escola); agora recebe 403 e nada é gravado.
    escola = escola_completa["escola"]
    escola.codigo_inep = "35012345"
    # SEGUNDA escola (de outra escola/rede) COM um INEP que ESTÁ na planilha: o global
    # casa as escolas de toda a base pelo código INEP.
    db.add(Escola(nome="EM de Outra Rede", ano_letivo_ativo=2026, status="ativa",
                  codigo_inep="35067890"))
    db.commit()
    dados = {"avaliacao": "ideb", "edicao": 2023, "indicador": "ideb", "unidade": "indice",
             "linha_dados": 2, "col_inep": 0, "col_valor": 2, "etapa_fixa": "anos_iniciais"}

    r = cliente.post("/api/v1/avaliacoes/importar", data=dados,
                     files={"arquivo": ("ideb.csv", _PLANILHA, "text/csv")})
    assert r.status_code == 403
    assert cliente.post("/api/v1/avaliacoes/analisar",
                        files={"arquivo": ("ideb.csv", _PLANILHA, "text/csv")}).status_code == 403
    db.expire_all()
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 0

    r = cliente_global.post("/api/v1/avaliacoes/importar", data=dados,
                            files={"arquivo": ("ideb.csv", _PLANILHA, "text/csv")})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["casados"] == 2 and corpo["inseridos"] == 2   # as duas escolas da base
    db.expire_all()
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 2


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


def test_importar_endpoint_avaliacao_desconhecida_400(db, escola_completa, cliente_global):
    r = cliente_global.post(
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
    imp = Importacao(escola_id=e.id, plataforma="seed", tipo="seed")
    db.add(imp); db.flush()
    for i in range(3):
        a = Aluno(escola_id=e.id, nome=f"Aluno {nome} {i}"); db.add(a); db.flush()
        db.add(Matricula(escola_id=e.id, aluno_id=a.id, turma_id=turma.id, ano_letivo=2026))
        # Snapshot = "tem dado da plataforma": sem ele o aluno não entra na média
        # de desempenho da escola (services/rede.py) e a correlação fica sem ponto.
        db.add(SnapshotElefante(escola_id=e.id, aluno_id=a.id, importacao_id=imp.id,
                                livros_unicos=5, tempo_leitura_min=60))
        db.add(SnapshotMatific(escola_id=e.id, aluno_id=a.id, importacao_id=imp.id,
                               atividades=20, estrelas=100))
        # A rede lê as colunas *_institucional (perfil fixo do Constela); ao semear
        # a Nota direto (sem recalcular_escola) precisamos preenchê-las com o mesmo
        # valor, senão nascem 0.0 e a média/engajamento da rede dá zero.
        db.add(Nota(detalhes=scoring.carimbo_institucional(), escola_id=e.id, aluno_id=a.id, ano_letivo=2026, nota_geral=media,
                    nota_elefante=media, nota_matific=media,
                    nota_elefante_institucional=media, nota_matific_institucional=media,
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
    assert corr["nome"] == corr["nome_curto"] == "IDEB"   # sem nome curto próprio


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


# --- Layout REAL do IDEB (validado no arquivo oficial de 2023) ---------------
# O arquivo do INEP tem pré-âmbulo + cabeçalhos, o INEP não é a 1ª coluna
# (ID_ESCOLA = col 3), o valor fica numa coluna distante (VL_OBSERVADO_2023),
# faltantes são "-" e o decimal é PONTO. Este teste fixa essa realidade.

def _ideb_real_xlsx() -> bytes:
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active
    ws.title = "IDEB_Escolas (Anos_Iniciais)"
    ws.append(["Ministério da Educação"])                     # pré-âmbulo
    ws.append(["Ensino Fundamental — Anos Iniciais"])         # pré-âmbulo
    cab = [None] * 9
    cab[0], cab[3], cab[4], cab[8] = "SG_UF", "ID_ESCOLA", "NO_ESCOLA", "VL_OBSERVADO_2023"
    ws.append(cab)                                            # cabeçalho técnico (idx 2)
    def linha(uf, inep, nome, ideb):
        r = [None] * 9
        r[0], r[3], r[4], r[8] = uf, inep, nome, ideb
        return r
    ws.append(linha("RO", "11024682", "EEEFM EURIDICE", "6.7"))   # ponto decimal
    ws.append(linha("RO", "11024828", "EMEIEF BOA VISTA", "4.0"))
    ws.append(linha("RO", "99999999", "EM DE OUTRA REDE", "5.5"))  # não está no banco
    ws.append(linha("RO", "11025310", "EMEIEF SEM IDEB", "-"))     # faltante → ignora
    import io as _io
    buf = _io.BytesIO(); wb.save(buf)
    return buf.getvalue()


def test_importa_layout_real_do_ideb_em_zip(db):
    import zipfile
    _escola_inep(db, None, "EEEFM EURIDICE", "11024682")
    _escola_inep(db, None, "EMEIEF BOA VISTA", "11024828")
    _escola_inep(db, None, "EMEIEF SEM IDEB", "11025310")
    db.commit()
    # ZIP como o oficial: um .ods (que o extrator DEVE ignorar) + o .xlsx.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("divulgacao_anos_iniciais_escolas_2023/x.ods", b"nao-e-planilha-lida")
        zf.writestr("divulgacao_anos_iniciais_escolas_2023/x.xlsx", _ideb_real_xlsx())
    conteudo = buf.getvalue()

    res = svc.importar_resultados(
        db, conteudo, "divulgacao_anos_iniciais_escolas_2023.zip",
        avaliacao_chave="ideb", edicao=2023, indicador="ideb", unidade="indice",
        linha_dados=3, col_inep=3, col_valor=8, etapa_fixa="anos_iniciais",
        escopo_escolas=None)
    db.commit()

    assert res["casados"] == 2 and res["inseridos"] == 2   # as duas com IDEB numérico
    assert res["nao_casados"] == 1                         # 99999999 fora do banco
    assert res["ignorados"] == 1                           # "-" sem valor
    linhas = {r.codigo_inep: round(r.valor, 2)
              for r in db.execute(select(ResultadoAvaliacao)).scalars()}
    assert linhas == {"11024682": 6.7, "11024828": 4.0}    # ponto decimal parseado
    assert "11025310" not in linhas                        # o "-" não virou registro


def _raw_layout(escolas, preamble=8) -> bytes:
    """Arquivo no layout do INEP de 2023 (Anos Iniciais): col3=INEP, col103=Mat,
    col104=Port, col115=IDEB; a ÚLTIMA linha do pré-âmbulo é a linha TÉCNICA (os
    presets acham as colunas por ela, pelo nome) e os dados vêm logo depois; a 1ª
    linha diz a etapa, como no oficial. ``escolas``=[(inep,ideb,mat,port)]."""
    linhas = [["Ensino Fundamental Regular - Anos Iniciais"]]
    linhas += [[f"cab {i}"] for i in range(1, preamble - 1)]
    tecnica = [""] * 116
    tecnica[3], tecnica[103], tecnica[104], tecnica[115] = (
        "ID_ESCOLA", "VL_NOTA_MATEMATICA_2023", "VL_NOTA_PORTUGUES_2023", "VL_OBSERVADO_2023")
    linhas.append(tecnica)
    for inep, ideb, mat, port in escolas:
        row = [""] * 116
        row[3], row[103], row[104], row[115] = inep, mat, port, ideb
        linhas.append(row)
    return "\n".join(";".join(c for c in ln) for ln in linhas).encode("utf-8")


def test_importar_preset_ideb_1_clique(db, escola_completa, cliente_global):
    escola = escola_completa["escola"]; escola.codigo_inep = "35012345"; db.commit()
    arq = _raw_layout([("35012345", "6.5", "220.0", "210.0")])
    r = cliente_global.post("/api/v1/avaliacoes/importar-preset",
                     data={"preset": "ideb_ai", "edicao": 2023},
                     files={"arquivo": ("ideb.csv", arq, "text/csv")})
    assert r.status_code == 200, r.text
    assert r.json()["series"][0]["casados"] == 1
    reg = db.execute(select(ResultadoAvaliacao)).scalars().one()
    assert reg.indicador == "ideb" and round(reg.valor, 1) == 6.5 and reg.etapa == "anos_iniciais"


def test_importar_preset_saeb_duas_series_1_clique(db, escola_completa, cliente_global):
    escola = escola_completa["escola"]; escola.codigo_inep = "35012345"; db.commit()
    arq = _raw_layout([("35012345", "6.5", "220.5", "210.2")])
    r = cliente_global.post("/api/v1/avaliacoes/importar-preset",
                     data={"preset": "saeb_ai", "edicao": 2023},
                     files={"arquivo": ("saeb.csv", arq, "text/csv")})
    assert r.status_code == 200, r.text
    series = {s["componente"]: s for s in r.json()["series"]}
    assert series["matematica"]["casados"] == 1 and series["portugues"]["casados"] == 1
    regs = {reg.componente: reg.valor for reg in db.execute(select(ResultadoAvaliacao)).scalars()}
    assert round(regs["matematica"], 1) == 220.5 and round(regs["portugues"], 1) == 210.2   # SAEB Mat/Port


def test_importar_preset_desconhecido_400(db, escola_completa, cliente_global):
    r = cliente_global.post("/api/v1/avaliacoes/importar-preset",
                     data={"preset": "xyz", "edicao": 2023},
                     files={"arquivo": ("x.csv", b"a;b", "text/csv")})
    assert r.status_code == 400


def test_importar_preset_saresp_componente_em_coluna(db, escola_completa, cliente_global):
    # SARESP: o preset lê o COMPONENTE de uma COLUNA (não fixo) — arquivo enxuto
    # INEP;COMPONENTE;PROFICIENCIA que o Constela prepara dos microdados.
    escola = escola_completa["escola"]; escola.codigo_inep = "35012345"; db.commit()
    arq = _csv([["CO_ESCOLA", "COMPONENTE", "PROFICIENCIA"],
                ["35012345", "portugues", "210.5"],
                ["35012345", "matematica", "225.0"]])
    r = cliente_global.post("/api/v1/avaliacoes/importar-preset",
                     data={"preset": "saresp_ai", "edicao": 2025},
                     files={"arquivo": ("saresp.csv", arq, "text/csv")})
    assert r.status_code == 200, r.text
    regs = {reg.componente: reg.valor
            for reg in db.execute(select(ResultadoAvaliacao)).scalars()}
    assert round(regs["portugues"], 1) == 210.5 and round(regs["matematica"], 1) == 225.0


def test_importar_preset_crianca_alfabetizada(db, escola_completa, cliente_global):
    # Estimativa do Constela (D1): taxa (%) por escola, derivada do 2º ano da SARESP.
    escola = escola_completa["escola"]; escola.codigo_inep = "35012345"; db.commit()
    arq = _csv([["CO_ESCOLA", "TAXA_ALFABETIZADOS_PCT"], ["35012345", "96.8"]])
    r = cliente_global.post("/api/v1/avaliacoes/importar-preset",
                     data={"preset": "crianca_alfab", "edicao": 2025},
                     files={"arquivo": ("alfab.csv", arq, "text/csv")})
    assert r.status_code == 200, r.text
    assert r.json()["rotulo"] == _ROTULO_ESTIMATIVA   # não se passa pelo indicador oficial
    reg = db.execute(select(ResultadoAvaliacao)).scalars().one()
    assert reg.indicador == "taxa_alfabetizacao" and round(reg.valor, 1) == 96.8
    assert reg.etapa == "2_ano" and reg.unidade == "percentual"


def test_excluir_resultados_desfaz_importacao_errada(db, escola_completa, cliente_global):
    # Cenário do dono: importou o mesmo arquivo como 2025 SEM QUERER (além de 2023).
    # Remover a edição 2025 não pode tocar na 2023.
    escola = escola_completa["escola"]; escola.codigo_inep = "35012345"; db.commit()
    dados = dict(avaliacao_chave="ideb", indicador="ideb", unidade="indice",
                 linha_dados=2, col_inep=0, col_valor=2, etapa_fixa="anos_iniciais",
                 escopo_escolas=None)
    svc.importar_resultados(db, _PLANILHA, "ideb.csv", edicao=2023, **dados)
    svc.importar_resultados(db, _PLANILHA, "ideb.csv", edicao=2025, **dados)  # engano
    db.commit()
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 2   # 1 em 2023, 1 em 2025

    r = cliente_global.delete(
        "/api/v1/avaliacoes/resultados?avaliacao=ideb&edicao=2025&indicador=ideb&etapa=anos_iniciais")
    assert r.status_code == 200, r.text
    assert r.json()["removidos"] == 1
    db.expire_all()
    restantes = db.execute(select(ResultadoAvaliacao)).scalars().all()
    assert len(restantes) == 1 and restantes[0].edicao == 2023   # a boa continua


def test_excluir_resultados_nao_apaga_serie_irma(db, escola_completa, cliente_global):
    # Achado da revisão (alto): remover UMA série não pode apagar as irmãs da MESMA
    # edição (outra etapa/componente importados à parte, e corretos).
    escola = escola_completa["escola"]; escola.codigo_inep = "35012345"; db.commit()
    base = dict(avaliacao_chave="ideb", edicao=2023, indicador="ideb", unidade="indice",
                linha_dados=2, col_inep=0, col_valor=2, escopo_escolas=None)
    svc.importar_resultados(db, _PLANILHA, "ai.csv", etapa_fixa="anos_iniciais", **base)
    svc.importar_resultados(db, _PLANILHA, "af.csv", etapa_fixa="anos_finais", **base)
    db.commit()
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 2

    r = cliente_global.delete(
        "/api/v1/avaliacoes/resultados?avaliacao=ideb&edicao=2023&indicador=ideb&etapa=anos_iniciais")
    assert r.status_code == 200 and r.json()["removidos"] == 1   # só anos_iniciais
    db.expire_all()
    restante = db.execute(select(ResultadoAvaliacao)).scalars().one()
    assert restante.etapa == "anos_finais"                       # a irmã sobreviveu


def test_excluir_resultados_so_do_admin_global(db, cliente_global):
    # Decisão D4 (E9): SÓ o admin global desfaz. Antes, a Secretaria (coordenador de
    # rede) removia os resultados das escolas da rede dela; agora recebe 403 e nada some.
    ra = Rede(nome="A", status="ativa"); rb = Rede(nome="B", status="ativa")
    db.add_all([ra, rb]); db.flush()
    _escola_inep(db, ra.id, "EM A", "35012345")
    _escola_inep(db, rb.id, "EM B", "35067890")
    db.commit()
    _importar_ideb(db, [("35012345", "6,0"), ("35067890", "4,0")])  # casa as duas (global)
    db.commit()
    secretaria = _login_rede(db, ra.id)   # Secretaria (coordenador) da rede A
    url = "/api/v1/avaliacoes/resultados?avaliacao=ideb&edicao=2023&indicador=ideb"

    assert secretaria.delete(url).status_code == 403
    db.expire_all()
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 2   # nada foi apagado
    r = cliente_global.delete(url)
    assert r.status_code == 200 and r.json()["removidos"] == 2      # as duas redes


def test_excluir_resultados_avaliacao_desconhecida_400(db, escola_completa, cliente_global):
    r = cliente_global.delete("/api/v1/avaliacoes/resultados?avaliacao=enem&edicao=2023&indicador=x")
    assert r.status_code == 400


def test_tetos_de_tamanho_cobrem_o_ideb_real():
    # Regressão (achado com o arquivo real): o ZIP oficial do IDEB tem ~97 MB.
    # Os tetos de upload e de download NÃO podem cair abaixo dele de novo.
    from app.routers import avaliacoes as rot
    real_ideb = 97 * 1024 * 1024
    assert rot._MAX_BYTES >= real_ideb        # upload manual (plano B)
    assert svc._MAX_DOWNLOAD >= real_ideb     # robô baixando sozinho


def test_resultado_avaliacao_chave_natural_e_unica(db):
    """M6 (auditoria): a chave natural do fato (avaliação, edição, indicador,
    escola, etapa, componente, turma) é ÚNICA — duas coletas concorrentes da
    mesma fonte não podem duplicar a linha, mesmo com dimensões NULAS."""
    esc = Escola(nome="Escola INEP", ano_letivo_ativo=2026)
    av = AvaliacaoExterna(chave="saeb", nome="SAEB")
    db.add_all([esc, av])
    db.flush()

    def _res():
        return ResultadoAvaliacao(
            avaliacao_id=av.id, edicao=2023, escola_id=esc.id,
            codigo_inep="12345678", etapa=None, componente=None, turma=None,
            indicador="proficiencia", valor=250.0, unidade="escala_saeb")

    db.add(_res())
    db.commit()
    # Segunda linha idêntica (NULOS incluídos) → barrada pelo índice único.
    db.add(_res())
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    # Continua permitindo uma dimensão DIFERENTE (etapa preenchida).
    db.add(ResultadoAvaliacao(
        avaliacao_id=av.id, edicao=2023, escola_id=esc.id, codigo_inep="12345678",
        etapa="5º ano", componente=None, turma=None,
        indicador="proficiencia", valor=260.0, unidade="escala_saeb"))
    db.commit()
    assert db.execute(select(func.count()).select_from(ResultadoAvaliacao)).scalar_one() == 2


# --- Presets do INEP: colunas pelo NOME da variável (nunca pela posição) -----
# Arquivo SINTÉTICO que imita o oficial (nenhum dado real no repositório): o
# cabeçalho ocupa várias linhas e só a última — a linha TÉCNICA — tem os nomes das
# variáveis. Cada edição nova acrescenta colunas em TODOS os blocos, então as
# posições de 2023 apontam para outra variável no arquivo de 2025.

_ANOS_2023 = list(range(2005, 2024, 2))   # 2005, 2007, ..., 2023
_ANOS_2025 = list(range(2005, 2026, 2))   # ... + 2025 (layout provável de 2025)


def _variaveis_inep(anos: list[int]) -> list[str]:
    """Linha técnica no padrão do arquivo do INEP (Anos Iniciais, por escola):
    identificação; aprovação + rendimento por edição; notas (Mat, Port, média) por
    edição; Ideb observado por edição; projeções. Com 2005–2023 reproduz as
    posições do arquivo de 2023 (ID_ESCOLA=3, Mat/Port 2023=103/104, Ideb=115)."""
    nomes = ["SG_UF", "CO_MUNICIPIO", "NO_MUNICIPIO", "ID_ESCOLA", "NO_ESCOLA", "REDE"]
    for a in anos:
        nomes += [f"VL_APROVACAO_{a}_SI_4", f"VL_APROVACAO_{a}_SI",
                  *(f"VL_APROVACAO_{a}_{s}" for s in range(1, 5)), f"VL_INDICADOR_REND_{a}"]
    for a in anos:
        nomes += [f"VL_NOTA_MATEMATICA_{a}", f"VL_NOTA_PORTUGUES_{a}", f"VL_NOTA_MEDIA_{a}"]
    nomes += [f"VL_OBSERVADO_{a}" for a in anos]
    nomes += [f"VL_PROJECAO_{a}" for a in anos if 2007 <= a <= 2021]
    return nomes


def _zip_inep(anos: list[int], escolas, *, sem: tuple[str, ...] = (),
              extra: tuple[str, ...] = (),
              etapa: tuple[str, str] = ("Anos Iniciais", "1º ao 5º ano")) -> bytes:
    """ZIP como o oficial (um .ods ignorado + o .xlsx). ``escolas`` = [(inep,
    {variável: valor})]. As outras células numéricas recebem o PRÓPRIO índice da
    coluna como ISCA: ler pela posição errada grava a isca, nunca o valor certo.
    ``sem`` tira variáveis da linha técnica e ``extra`` as acrescenta no fim
    (arquivo incompleto/errado). ``etapa`` = (segmento do pré-âmbulo, subgrupo das
    séries) — o arquivo de Anos Finais usa os MESMOS nomes de variável."""
    import zipfile
    from openpyxl import Workbook
    nomes = [n for n in _variaveis_inep(anos) if n not in sem] + list(extra)
    wb = Workbook(); ws = wb.active
    ws.title = "IDEB_Escolas (Anos_Iniciais)"
    ws.append([None, None, "Ministério da Educação"])                       # pré-âmbulo
    ws.append([None, None, "Instituto Nacional de Estudos e Pesquisas Educacionais"])
    ws.append([])                                                           # em branco
    ws.append([f"Ensino Fundamental Regular - {etapa[0]}"])
    ws.append([f"Indicadores nos anos de {anos[0]} a {anos[-1]} (sintético)"])
    ws.append([])
    ws.append(["Sigla da UF", "Código do Município", "Nome do Município",
               "Código da Escola", "Nome da Escola", "Rede", "Taxa de Aprovação"])
    ws.append([None] * 7 + ["Matemática", "Língua Portuguesa", "Nota Média"])  # grupos
    ws.append([None] * 6 + [etapa[1], "1º", "2º", "3º", "4º"])               # subgrupos
    ws.append(nomes)                                                        # TÉCNICA
    for inep, valores in escolas:
        linha = []
        for j, n in enumerate(nomes):
            if n in valores:
                linha.append(valores[n])
            elif n == "ID_ESCOLA":
                linha.append(int(inep))          # o oficial traz o código como número
            elif n in ("SG_UF", "NO_MUNICIPIO", "NO_ESCOLA", "REDE"):
                linha.append({"SG_UF": "SP", "REDE": "Municipal"}.get(n, f"Texto {inep}"))
            else:
                linha.append(float(j))           # isca
        ws.append(linha)
    ws.append(["1 Nota de rodapé do INEP (sem código de escola)."])         # rodapé
    xbuf = io.BytesIO(); wb.save(xbuf)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("divulgacao_anos_iniciais_escolas/x.ods", b"nao-e-planilha-lida")
        zf.writestr("divulgacao_anos_iniciais_escolas/x.xlsx", xbuf.getvalue())
    return buf.getvalue()


def _preset(cliente, preset, edicao, arq, nome="divulgacao_anos_iniciais_escolas.zip"):
    return cliente.post("/api/v1/avaliacoes/importar-preset",
                        data={"preset": preset, "edicao": edicao},
                        files={"arquivo": (nome, arq, "application/zip")})


def _valores(db):
    db.expire_all()
    return {(r.indicador, r.componente, r.edicao): round(r.valor, 2)
            for r in db.execute(select(ResultadoAvaliacao)).scalars()}


def test_layout_2023_pelo_nome_da_as_mesmas_colunas_de_hoje():
    # As posições fixas que os presets usavam (linha 8, col 3/115/103/104) saem
    # agora da linha técnica — no layout de 2023, exatamente as mesmas.
    linha, cols = svc.localizar_colunas_inep(
        _zip_inep(_ANOS_2023, []), "ideb.zip",
        ["ID_ESCOLA", "VL_OBSERVADO_2023", "VL_NOTA_MATEMATICA_2023", "VL_NOTA_PORTUGUES_2023"],
        marcadores_etapa=("Anos Iniciais",), arquivo_esperado="o arquivo de teste")
    assert linha == 8
    assert cols == {"ID_ESCOLA": 3, "VL_OBSERVADO_2023": 115,
                    "VL_NOTA_MATEMATICA_2023": 103, "VL_NOTA_PORTUGUES_2023": 104}


def test_layout_2025_desloca_as_colunas():
    # Sanidade do arquivo sintético de 2025: as posições de 2023 apontam para
    # OUTRAS variáveis — é o erro que a leitura por posição cometeria.
    nomes = _variaveis_inep(_ANOS_2025)
    assert nomes.index("ID_ESCOLA") == 3
    assert nomes[115] == "VL_NOTA_MEDIA_2025" and nomes[103] == "VL_NOTA_MEDIA_2017"
    assert nomes.index("VL_OBSERVADO_2025") == 126


def test_preset_ideb_e_saeb_layout_2023_importam_igual_a_hoje(db, escola_completa, cliente_global):
    escola = escola_completa["escola"]; escola.codigo_inep = "35012345"; db.commit()
    arq = _zip_inep(_ANOS_2023, [
        ("35012345", {"VL_OBSERVADO_2023": "6.1", "VL_NOTA_MATEMATICA_2023": "225.3",
                      "VL_NOTA_PORTUGUES_2023": "212.7"}),
        ("99999999", {"VL_OBSERVADO_2023": "5.0", "VL_NOTA_MATEMATICA_2023": "200.0",
                      "VL_NOTA_PORTUGUES_2023": "200.0"}),   # escola fora da base
    ])
    ideb = _preset(cliente_global, "ideb_ai", 2023, arq)
    assert ideb.status_code == 200, ideb.text
    saeb = _preset(cliente_global, "saeb_ai", 2023, arq)
    assert saeb.status_code == 200, saeb.text
    assert _valores(db) == {("ideb", None, 2023): 6.1,
                            ("proficiencia", "matematica", 2023): 225.3,
                            ("proficiencia", "portugues", 2023): 212.7}
    assert ideb.json()["series"][0]["casados"] == 1
    # A resposta diz de qual variável cada série saiu.
    assert ideb.json()["series"][0]["coluna"] == "VL_OBSERVADO_2023"
    assert [s["coluna"] for s in saeb.json()["series"]] == [
        "VL_NOTA_MATEMATICA_2023", "VL_NOTA_PORTUGUES_2023"]


def test_preset_layout_2025_le_a_coluna_certa(db, escola_completa, cliente_global):
    escola = escola_completa["escola"]; escola.codigo_inep = "35012345"; db.commit()
    arq = _zip_inep(_ANOS_2025, [("35012345", {
        "VL_OBSERVADO_2025": "6.3", "VL_OBSERVADO_2023": "5.9",
        "VL_NOTA_MATEMATICA_2025": "231.4", "VL_NOTA_PORTUGUES_2025": "219.8"})])
    for preset in ("ideb_ai", "saeb_ai"):
        r = _preset(cliente_global, preset, 2025, arq)
        assert r.status_code == 200, r.text
    # O IDEB 2023 do MESMO arquivo também sai da coluna certa (VL_OBSERVADO_2023).
    r = _preset(cliente_global, "ideb_ai", 2023, arq)
    assert r.status_code == 200, r.text
    # Nenhuma isca (índice de coluna) foi gravada: só os valores das variáveis.
    assert _valores(db) == {("ideb", None, 2025): 6.3, ("ideb", None, 2023): 5.9,
                            ("proficiencia", "matematica", 2025): 231.4,
                            ("proficiencia", "portugues", 2025): 219.8}
    assert r.json()["series"][0]["coluna"] == "VL_OBSERVADO_2023"


def test_preset_coluna_ausente_recusa_400_sem_gravar(db, escola_completa, cliente_global):
    escola = escola_completa["escola"]; escola.codigo_inep = "35012345"; db.commit()
    arq = _zip_inep(_ANOS_2023, [("35012345", {"VL_NOTA_MATEMATICA_2023": "225.3"})],
                    sem=("VL_NOTA_PORTUGUES_2023",))
    r = _preset(cliente_global, "saeb_ai", 2023, arq)
    assert r.status_code == 400
    assert "VL_NOTA_PORTUGUES_2023" in r.json()["detail"]
    # Nem a Matemática (que existe) foi gravada: a conferência vem ANTES de tudo.
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 0

    # Arquivo sem a linha técnica (o CSV "posicional" de antes) também é recusado.
    sem_tecnica = _csv([[f"cab {i}"] for i in range(8)] + [["", "", "", "35012345"]])
    r = cliente_global.post("/api/v1/avaliacoes/importar-preset",
                     data={"preset": "ideb_ai", "edicao": 2023},
                     files={"arquivo": ("ideb.csv", sem_tecnica, "text/csv")})
    assert r.status_code == 400 and "ID_ESCOLA" in r.json()["detail"]
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 0


def test_preset_edicao_sem_coluna_no_arquivo_recusa_400(db, escola_completa, cliente_global):
    # Arquivo de 2023 + edição 2025 escolhida: antes gravava o Ideb de 2023 COMO
    # 2025; agora não existe VL_OBSERVADO_2025 e a importação é recusada.
    escola = escola_completa["escola"]; escola.codigo_inep = "35012345"; db.commit()
    arq = _zip_inep(_ANOS_2023, [("35012345", {"VL_OBSERVADO_2023": "6.1"})])
    r = _preset(cliente_global, "ideb_ai", 2025, arq)
    assert r.status_code == 400
    assert r.json()["detail"] == (
        "O arquivo não tem a coluna VL_OBSERVADO_2025; confira se é o arquivo oficial "
        "do INEP de Anos Iniciais (Ideb por escola) da edição 2025. Nada foi gravado.")
    r = _preset(cliente_global, "saeb_ai", 2025, arq)
    assert r.status_code == 400
    assert "VL_NOTA_MATEMATICA_2025, VL_NOTA_PORTUGUES_2025" in r.json()["detail"]
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 0


def test_preset_arquivo_de_anos_finais_recusa_400_sem_sobrescrever(db, escola_completa,
                                                                   cliente_global):
    # O arquivo de Anos Finais usa os MESMOS nomes de variável; só o topo diz a
    # etapa. Sem a conferência, ele gravaria como 'anos_iniciais' POR CIMA do valor
    # certo (mesma chave escola+etapa+componente+turma) — e contaria "atualizados".
    escola = escola_completa["escola"]; escola.codigo_inep = "35012345"; db.commit()
    iniciais = _zip_inep(_ANOS_2023, [("35012345", {
        "VL_OBSERVADO_2023": "6.1", "VL_NOTA_MATEMATICA_2023": "225.3",
        "VL_NOTA_PORTUGUES_2023": "212.7"})])
    for preset in ("ideb_ai", "saeb_ai"):
        assert _preset(cliente_global, preset, 2023, iniciais).status_code == 200
    antes = _valores(db)

    finais = _zip_inep(_ANOS_2023, [("35012345", {
        "VL_OBSERVADO_2023": "4.8", "VL_NOTA_MATEMATICA_2023": "255.0",
        "VL_NOTA_PORTUGUES_2023": "250.0"})], etapa=("Anos Finais", "6º ao 9º ano"))
    for preset in ("ideb_ai", "saeb_ai"):
        r = _preset(cliente_global, preset, 2023, finais, nome="divulgacao_anos_finais_escolas_2023.zip")
        assert r.status_code == 400, r.text
        assert r.json()["detail"] == (
            'O cabeçalho do arquivo não indica a etapa esperada (não traz "Anos Iniciais" '
            'nem "1º ao 5º ano"); confira se é o arquivo oficial do INEP de Anos Iniciais '
            "(Ideb por escola) da edição 2023. Nada foi gravado.")
    assert _valores(db) == antes == {("ideb", None, 2023): 6.1,
                                     ("proficiencia", "matematica", 2023): 225.3,
                                     ("proficiencia", "portugues", 2023): 212.7}


def test_preset_variavel_repetida_na_linha_tecnica_recusa_400(db, escola_completa, cliente_global):
    # Duas colunas com o mesmo nome: escolher uma seria adivinhar qual é o dado.
    escola = escola_completa["escola"]; escola.codigo_inep = "35012345"; db.commit()
    arq = _zip_inep(_ANOS_2023, [("35012345", {"VL_OBSERVADO_2023": "6.1"})],
                    extra=("VL_OBSERVADO_2023",))
    r = _preset(cliente_global, "ideb_ai", 2023, arq)
    assert r.status_code == 400
    assert "VL_OBSERVADO_2023 aparece mais de uma vez" in r.json()["detail"]
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 0


# --- INEP duplicado no cadastro: recusa, sem gravar -------------------------

def test_inep_duplicado_no_escopo_recusa_sem_gravar(db, cliente_global):
    rede = Rede(nome="Rede Dup", status="ativa"); db.add(rede); db.flush()
    _escola_inep(db, rede.id, "EM Alfa", "35012345")
    _escola_inep(db, rede.id, "EM Alfa Anexo", "035012345")   # normaliza p/ o MESMO código
    _escola_inep(db, rede.id, "EM Beta", "35067890")
    db.commit()
    escopo = set(db.execute(select(Escola.id).where(Escola.rede_id == rede.id)).scalars())

    with pytest.raises(svc.ImportacaoRecusada) as exc:
        svc.importar_resultados(
            db, _PLANILHA, "ideb.csv", avaliacao_chave="ideb", edicao=2023,
            indicador="ideb", unidade="indice", linha_dados=2, col_inep=0, col_valor=2,
            escopo_escolas=escopo)
    msg = str(exc.value)
    assert "35012345 (EM Alfa, EM Alfa Anexo)" in msg and "Nada foi gravado" in msg
    # Conferido ANTES do rollback, na mesma transação: `obter_avaliacao` só faz
    # flush, e o rollback apagaria a linha do catálogo — a contagem depois dele
    # nunca falharia.
    assert db.scalar(select(func.count(AvaliacaoExterna.id))) == 0   # nem o catálogo
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 0
    db.rollback()

    # Pelos endpoints (só o admin global importa desde a E9, em toda a base): 400 com a
    # mesma mensagem, nada gravado.
    cliente = cliente_global
    r = cliente.post(
        "/api/v1/avaliacoes/importar",
        data={"avaliacao": "ideb", "edicao": 2023, "indicador": "ideb", "unidade": "indice",
              "linha_dados": 2, "col_inep": 0, "col_valor": 2},
        files={"arquivo": ("ideb.csv", _PLANILHA, "text/csv")})
    assert r.status_code == 400 and "35012345 (EM Alfa, EM Alfa Anexo)" in r.json()["detail"]
    r = _preset(cliente, "ideb_ai", 2023,
                _zip_inep(_ANOS_2023, [("35012345", {"VL_OBSERVADO_2023": "6.1"})]))
    assert r.status_code == 400 and "35012345" in r.json()["detail"]
    db.expire_all()
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 0


def test_inep_repetido_fora_do_escopo_nao_bloqueia(db):
    # O mesmo código numa escola de OUTRA rede não entra no escopo da rede A:
    # a importação dela segue normal (não há ambiguidade dentro do escopo). Desde a
    # 0035 o banco recusa o MESMO texto em duas escolas (uq_escolas_codigo_inep);
    # um cadastro antigo com zero à esquerda ainda normaliza para o mesmo código.
    ra = Rede(nome="Rede A", status="ativa"); rb = Rede(nome="Rede B", status="ativa")
    db.add_all([ra, rb]); db.flush()
    _escola_inep(db, ra.id, "EM A", "35012345")
    _escola_inep(db, rb.id, "EM B", "035012345")
    db.commit()
    escopo_a = set(db.execute(select(Escola.id).where(Escola.rede_id == ra.id)).scalars())
    res = svc.importar_resultados(
        db, _PLANILHA, "ideb.csv", avaliacao_chave="ideb", edicao=2023, indicador="ideb",
        unidade="indice", linha_dados=2, col_inep=0, col_valor=2, escopo_escolas=escopo_a)
    assert res["casados"] == 1


def test_coleta_automatica_com_inep_duplicado_vira_erro_sem_gravar(db):
    from app.models import FonteAvaliacao
    _escola_inep(db, None, "EM Alfa", "35012345")
    # (o mesmo texto o banco já recusa desde a 0035; o zero à esquerda normaliza igual)
    _escola_inep(db, None, "EM Alfa (cópia)", "035012345")
    db.commit()
    av = svc.obter_avaliacao(db, "ideb")
    fonte = FonteAvaliacao(
        avaliacao_id=av.id, nome="IDEB AI 2023", url="https://download.inep.gov.br/x.csv",
        edicao=2023, indicador="ideb", unidade="indice", cadencia="manual",
        mapeamento={"linha_dados": 2, "col_inep": 0, "col_valor": 2})
    db.add(fonte); db.commit()

    resumo = svc.coletar_fonte(db, fonte, baixador=lambda url: _PLANILHA)   # NÃO levanta
    db.commit()
    assert resumo["status"] == "erro" and "35012345" in fonte.ultimo_erro
    assert db.scalar(select(func.count(ResultadoAvaliacao.id))) == 0


# --- Resumo: TODOS os códigos não casados -----------------------------------

def test_resumo_lista_todos_os_codigos_nao_casados(db, escola_completa, cliente_global):
    from app.models import LogAuditoria
    escola = escola_completa["escola"]; escola.codigo_inep = "35012345"; db.commit()
    fora = [f"{41000000 + i}" for i in range(60)]           # > 50 (teto antigo) e > 20
    linhas = [["preambulo"], ["CO", "IDEB"], ["35012345", "6,0"]]
    linhas += [[c, "5,0"] for c in fora] + [[fora[0], "5,1"]]   # 1 código repetido
    r = cliente_global.post(
        "/api/v1/avaliacoes/importar",
        data={"avaliacao": "ideb", "edicao": 2023, "indicador": "ideb", "unidade": "indice",
              "linha_dados": 2, "col_inep": 0, "col_valor": 1},
        files={"arquivo": ("ideb.csv", _csv(linhas), "text/csv")})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["casados"] == 1
    assert corpo["nao_casados"] == 61                 # a contagem segue por LINHA
    assert corpo["inep_nao_casados"] == sorted(fora)  # e a lista traz TODOS os códigos
    # A trilha de auditoria guarda contagem + amostra, não a lista inteira.
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "avaliacao.importada")).scalar_one()
    assert log.detalhes["nao_casados"] == 61
    assert "inep_nao_casados" not in log.detalhes
    assert len(log.detalhes["inep_nao_casados_amostra"]) == 20

    # O 1 clique devolve, por série, a contagem e a lista completa.
    arq = _zip_inep(_ANOS_2023, [(c, {"VL_OBSERVADO_2023": "5.0"}) for c in ["35012345", *fora]])
    r = _preset(cliente_global, "ideb_ai", 2023, arq)
    assert r.status_code == 200, r.text
    serie = r.json()["series"][0]
    assert serie["nao_casados"] == 60 and serie["inep_nao_casados"] == sorted(fora)
    # ... e a trilha de auditoria do 1 clique também guarda só contagem + amostra.
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "avaliacao.importada_preset")).scalar_one()
    (serie_log,) = log.detalhes["series"]
    assert serie_log["nao_casados"] == 60 and "inep_nao_casados" not in serie_log
    assert serie_log["inep_nao_casados_amostra"] == sorted(fora)[:20]


def test_coleta_automatica_guarda_so_contagem_e_amostra(db):
    # `ultimo_resumo` é persistido e volta em cada GET /avaliacoes/fontes: o arquivo
    # nacional (dezenas de milhares de códigos de outras redes) não vai inteiro.
    from app.models import FonteAvaliacao
    _escola_inep(db, None, "EM Alfa", "35012345")
    db.commit()
    fora = [f"{41000000 + i}" for i in range(30)]
    arq = _csv([["preambulo"], ["CO", "IDEB"], ["35012345", "6,0"]]
               + [[c, "5,0"] for c in fora])
    av = svc.obter_avaliacao(db, "ideb")
    fonte = FonteAvaliacao(
        avaliacao_id=av.id, nome="IDEB AI 2023", url="https://download.inep.gov.br/x.csv",
        edicao=2023, indicador="ideb", unidade="indice", cadencia="manual",
        mapeamento={"linha_dados": 2, "col_inep": 0, "col_valor": 1})
    db.add(fonte); db.commit()

    resumo = svc.coletar_fonte(db, fonte, baixador=lambda url: arq)
    db.commit()
    assert resumo["status"] == "ok" and resumo["casados"] == 1 and resumo["nao_casados"] == 30
    db.expire_all()
    for guardado in (fonte.ultimo_resumo, resumo):
        assert "inep_nao_casados" not in guardado
        assert guardado["inep_nao_casados_amostra"] == sorted(fora)[:20]


# --- Rótulo da D1: estimativa do Constela, não o indicador oficial ----------

def test_rotulo_estimativa_mesmo_com_nome_antigo_no_banco(db, escola_completa, cliente,
                                                         cliente_global):
    # Banco ANTIGO (produção): a linha do catálogo ainda diz "Criança Alfabetizada".
    antigo = AvaliacaoExterna(chave="crianca_alfabetizada", nome="Criança Alfabetizada",
                              tipo="avaliacao", orgao="INEP / CAEd",
                              descricao="Avaliação de alfabetização (2º ano do EF).")
    db.add(antigo); db.commit()
    rede = Rede(nome="Rede Rot", status="ativa"); db.add(rede); db.flush()
    e = _escola_engajada(db, rede.id, "EM R", "35012345", 70.0)
    db.add(ResultadoAvaliacao(avaliacao_id=antigo.id, edicao=2025, rede_id=rede.id,
                              escola_id=e.id, codigo_inep="35012345", etapa="2_ano",
                              indicador="taxa_alfabetizacao", valor=96.8,
                              unidade="percentual"))
    db.commit()

    cat = {a["chave"]: a for a in cliente.get("/api/v1/avaliacoes").json()}
    assert cat["crianca_alfabetizada"]["nome"] == _ROTULO_ESTIMATIVA
    assert cat["crianca_alfabetizada"]["orgao"] == _ORGAO_ESTIMATIVA   # não "INEP / CAEd"
    assert "SARESP do 2º ano" in cat["crianca_alfabetizada"]["descricao"]
    assert "NÃO é o Indicador Criança Alfabetizada do INEP" in cat["crianca_alfabetizada"]["descricao"]
    ops = svc.opcoes_rede(db, rede.id)
    assert [s["nome"] for s in ops] == [_ROTULO_ESTIMATIVA]
    corr = svc.correlacao_rede(db, rede.id, avaliacao_chave="crianca_alfabetizada",
                               indicador="taxa_alfabetizacao", edicao=2025, etapa="2_ano")
    assert corr["nome"] == _ROTULO_ESTIMATIVA
    assert corr["nome_curto"] == "Estimativa Constela (SARESP 2º ano)"   # eixo do gráfico
    presets = {p["chave"]: p for p in cliente.get("/api/v1/avaliacoes/presets-import").json()}
    assert presets["crianca_alfab"]["rotulo"] == _ROTULO_ESTIMATIVA
    assert "não o Indicador Criança Alfabetizada do INEP" in presets["crianca_alfab"]["dica"]
    r = cliente_global.post("/api/v1/avaliacoes/fontes", json={
        "avaliacao": "crianca_alfabetizada", "nome": "Estimativa 2025",
        "url": "https://exemplo.gov.br/x.csv", "edicao": 2025,
        "indicador": "taxa_alfabetizacao", "unidade": "percentual",
        "mapeamento": {"linha_dados": 1, "col_inep": 0, "col_valor": 1}})
    assert r.status_code == 201, r.text
    assert r.json()["avaliacao_nome"] == _ROTULO_ESTIMATIVA
    fontes = cliente_global.get("/api/v1/avaliacoes/fontes").json()
    assert [f["avaliacao_nome"] for f in fontes] == [_ROTULO_ESTIMATIVA]

    # Reversível: o DADO do banco não mudou (só a exibição) — nada de migração.
    db.expire_all()
    linha = db.get(AvaliacaoExterna, antigo.id)
    assert linha.nome == "Criança Alfabetizada" and linha.orgao == "INEP / CAEd"
    assert linha.descricao == "Avaliação de alfabetização (2º ano do EF)."


def test_instalacao_nova_ja_nasce_com_o_rotulo_da_estimativa(db):
    av = svc.obter_avaliacao(db, "crianca_alfabetizada")
    assert av.nome == _ROTULO_ESTIMATIVA and len(av.nome) <= 120   # cabe na coluna
    assert av.orgao == _ORGAO_ESTIMATIVA and len(av.orgao) <= 80
    assert "SARESP do 2º ano" in av.descricao and len(av.descricao) <= 500
