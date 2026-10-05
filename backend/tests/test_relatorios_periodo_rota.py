"""A ROTA do relatório por período: quem pode pedir, o que volta, o que é
recusado — e a PARIDADE com a premiação oficial.

O teste mais importante daqui é ``test_paridade_com_a_premiacao_oficial``: para
a MESMA janela, ``livros_novos`` e ``tempo_min`` têm de dar exatamente o que os
pódios "Mais Livros" e "Mais Tempo" dão. É o que impede o relatório de virar uma
segunda régua discordando da cerimônia sobre o mesmo mês.
"""
from datetime import date, datetime

from sqlalchemy import select

from app.models import (Aluno, EventoAluno, Leitura, Livro, LogAuditoria,
                        Matricula, Professor, Rede, Turma, Usuario)
from app.core.security import hash_senha
from app.services import periodos, premiacoes as svc_premiacoes
from app.services import relatorios_periodo as rp
from app.services.eventos import chave_evento

ROTA = "/api/v1/escolas/{eid}/relatorios/periodo"
HOJE = date(2026, 10, 5)


def _semear(db, escola_id, aluno_id, titulo, quando, tempo, nivel="D"):
    """Uma leitura COMPLETA: a linha que pontua + o evento do espelho, como o
    importador real grava as duas."""
    livro = Livro(escola_id=escola_id, titulo=titulo, nivel_codigo=nivel)
    db.add(livro)
    db.flush()
    db.add(Leitura(escola_id=escola_id, aluno_id=aluno_id, livro_id=livro.id,
                   data=quando, tempo_leitura_min=tempo, nivel_codigo=nivel))
    db.add(EventoAluno(
        escola_id=escola_id, aluno_id=aluno_id, plataforma="elefante",
        tipo_evento="leitura", ocorrido_em=quando, conteudo_titulo=titulo,
        livro_id=livro.id, tempo_segundos=tempo * 60, nivel_codigo=nivel,
        chave_natural=chave_evento("elefante", "leitura", aluno_id, titulo,
                                   quando, "")))
    db.flush()
    return livro


# ============================================================================
# PARIDADE COM A PREMIAÇÃO OFICIAL
# ============================================================================
def test_paridade_com_a_premiacao_oficial(db, escola_completa):
    """Mesma janela, mesmos números. Se divergir, um dos dois está errado."""
    escola = escola_completa["escola"]
    a, b = escola_completa["alunos"][0], escola_completa["alunos"][1]
    _semear(db, escola.id, a.id, "Setembro um", datetime(2026, 9, 3, 10, 0), 12)
    _semear(db, escola.id, a.id, "Setembro dois", datetime(2026, 9, 14, 10, 0), 7)
    _semear(db, escola.id, b.id, "Setembro tres", datetime(2026, 9, 21, 10, 0), 9)
    # fora da janela: nenhum dos dois pode contar
    _semear(db, escola.id, a.id, "Agosto", datetime(2026, 8, 30, 10, 0), 40)
    db.commit()

    ini, fim, _ = periodos.resolver("mes_anterior", HOJE, escola.ano_letivo_ativo)
    oficial = svc_premiacoes.premiacoes(db, escola.id, ini, fim, limite=500)
    pod = {c["chave"]: c["podio"] for c in oficial["categorias"]}
    livros_oficiais = sum(int(i["valor"]) for i in pod["mais_livros"])
    tempo_oficial = sum(int(i["valor"]) for i in pod["mais_tempo"])

    r = rp.gerar(db, escola.id, preset="mes_anterior",
                 plataformas=("elefante",), hoje=HOJE)
    assert r["elefante"]["livros_novos"] == livros_oficiais == 3
    assert r["elefante"]["tempo_min"] == tempo_oficial == 28

    # e por aluno, não só no total
    por_aluno = {x["aluno_id"]: x["elefante"] for x in r["por_aluno"]}
    for item in pod["mais_livros"]:
        assert por_aluno[item["aluno_id"]]["livros_novos"] == int(item["valor"])
    for item in pod["mais_tempo"]:
        assert por_aluno[item["aluno_id"]]["tempo_min"] == int(item["valor"])


def test_o_relatorio_nao_altera_nota_nem_posicao(db, escola_completa):
    """Consulta é consulta: a tabela de notas não se move."""
    from app.models import Nota
    escola = escola_completa["escola"]
    a = escola_completa["alunos"][0]
    _semear(db, escola.id, a.id, "Um", datetime(2026, 9, 3, 10, 0), 12)
    db.commit()
    antes = sorted((n.aluno_id, n.nota_geral, n.posicao) for n in db.execute(
        select(Nota).where(Nota.escola_id == escola.id)).scalars())
    rp.gerar(db, escola.id, preset="mes_anterior", plataformas=("elefante",),
             hoje=HOJE)
    depois = sorted((n.aluno_id, n.nota_geral, n.posicao) for n in db.execute(
        select(Nota).where(Nota.escola_id == escola.id)).scalars())
    assert antes == depois


# ============================================================================
# A ROTA
# ============================================================================
def test_rota_devolve_o_relatorio_para_o_admin(db, escola_completa, cliente):
    escola = escola_completa["escola"]
    a = escola_completa["alunos"][0]
    _semear(db, escola.id, a.id, "Lido", datetime(2026, 9, 9, 10, 0), 6)
    db.commit()
    resp = cliente.get(ROTA.format(eid=escola.id),
                       params={"periodo": "mes_anterior", "plataformas": "elefante"})
    assert resp.status_code == 200, resp.text
    corpo = resp.json()
    assert corpo["periodo"]["preset"] == "mes_anterior"
    assert corpo["periodo"]["inclusivo"] is True
    assert corpo["plataformas"] == ["elefante"]
    assert corpo["elefante"]["livros_novos"] == 1
    assert corpo["elefante"]["tempo_min"] == 6
    assert corpo["elefante"]["tempo_min_por_evento"] is None
    assert "matific" not in corpo
    assert any(n["metrica"] == "tempo_min_por_evento" for n in corpo["nao_suportado"])


def test_rota_personalizado_exige_as_duas_datas(db, escola_completa, cliente):
    eid = escola_completa["escola"].id
    resp = cliente.get(ROTA.format(eid=eid), params={"periodo": "personalizado"})
    assert resp.status_code == 422
    assert "data inicial" in resp.json()["detail"].lower()


def test_rota_personalizado_com_datas(db, escola_completa, cliente):
    escola = escola_completa["escola"]
    a = escola_completa["alunos"][0]
    _semear(db, escola.id, a.id, "Dentro", datetime(2026, 9, 12, 10, 0), 5)
    _semear(db, escola.id, a.id, "Fora", datetime(2026, 9, 26, 10, 0), 5)
    db.commit()
    resp = cliente.get(ROTA.format(eid=escola.id),
                       params={"periodo": "personalizado", "inicio": "2026-09-10",
                               "fim": "2026-09-25", "plataformas": "elefante"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["elefante"]["livros_novos"] == 1
    assert resp.json()["periodo"]["rotulo"] == "10/09/2026 a 25/09/2026"


def test_rota_recusa_periodo_inexistente(db, escola_completa, cliente):
    """`periodos.resolver` NÃO levanta em preset desconhecido: devolve 'todo o
    histórico'. Num relatório isso seria entregar um escopo MAIOR que o pedido,
    então a validação é explícita."""
    eid = escola_completa["escola"].id
    resp = cliente.get(ROTA.format(eid=eid), params={"periodo": "trimestre_7"})
    assert resp.status_code == 422
    assert "não existe" in resp.json()["detail"]


def test_rota_recusa_data_invalida(db, escola_completa, cliente):
    eid = escola_completa["escola"].id
    resp = cliente.get(ROTA.format(eid=eid),
                       params={"periodo": "personalizado", "inicio": "12/09/2026",
                               "fim": "2026-09-25"})
    assert resp.status_code == 422


def test_rota_recusa_data_inicial_depois_da_final(db, escola_completa, cliente):
    eid = escola_completa["escola"].id
    resp = cliente.get(ROTA.format(eid=eid),
                       params={"periodo": "personalizado", "inicio": "2026-09-25",
                               "fim": "2026-09-10"})
    assert resp.status_code == 422
    assert "posterior" in resp.json()["detail"]


def test_rota_recusa_plataforma_inexistente(db, escola_completa, cliente):
    eid = escola_completa["escola"].id
    resp = cliente.get(ROTA.format(eid=eid), params={"plataformas": "khan"})
    assert resp.status_code == 422


def test_rota_escopo_turma_exige_turma(db, escola_completa, cliente):
    eid = escola_completa["escola"].id
    resp = cliente.get(ROTA.format(eid=eid), params={"escopo": "turma"})
    assert resp.status_code == 422


def test_rota_escopo_aluno(db, escola_completa, cliente):
    escola = escola_completa["escola"]
    a, b = escola_completa["alunos"][0], escola_completa["alunos"][1]
    _semear(db, escola.id, a.id, "Do A", datetime(2026, 9, 9, 10, 0), 6)
    _semear(db, escola.id, b.id, "Do B", datetime(2026, 9, 9, 11, 0), 4)
    db.commit()
    resp = cliente.get(ROTA.format(eid=escola.id),
                       params={"periodo": "mes_anterior", "escopo": "aluno",
                               "aluno_id": a.id, "plataformas": "elefante"})
    assert resp.status_code == 200, resp.text
    corpo = resp.json()
    assert corpo["alunos"]["considerados"] == 1
    assert corpo["elefante"]["livros_novos"] == 1
    assert [x["aluno_id"] for x in corpo["por_aluno"]] == [a.id]


def test_rota_nao_vaza_escola_alheia(db, escola_completa, cliente):
    from app.models import Escola
    outra = Escola(nome="OUTRA ESCOLA", ano_letivo_ativo=2026)
    db.add(outra)
    db.commit()
    resp = cliente.get(ROTA.format(eid=outra.id))
    assert resp.status_code in (403, 404)


def test_rota_nega_secretaria(db, escola_completa):
    """A guarda de PII viaja COM o endpoint — o relatório lista nome de criança."""
    from fastapi.testclient import TestClient

    from app.main import app
    escola = escola_completa["escola"]
    rede = Rede(nome="REDE TESTE")
    db.add(rede)
    db.flush()
    # A escola entra na MESMA rede: assim `escola_autorizada` passa e quem nega
    # é a guarda de PII do endpoint, que é o que este teste prova.
    escola.rede_id = rede.id
    db.add(Usuario(escola_id=escola.id, rede_id=rede.id, nome="Secretaria",
                   email="sec@teste.local", senha_hash=hash_senha("s3nh4"),
                   cargo="coordenador"))
    db.commit()
    c = TestClient(app)
    tok = c.post("/api/v1/auth/login",
                 data={"username": "sec@teste.local", "password": "s3nh4"})
    assert tok.status_code == 200, tok.text
    c.headers["Authorization"] = f"Bearer {tok.json()['access_token']}"
    resp = c.get(ROTA.format(eid=escola.id))
    assert resp.status_code == 403
    assert "Secretaria" in resp.json()["detail"]


def test_rota_professor_so_ve_as_turmas_dele(db, escola_completa):
    """Escopo "escola" NÃO fura o recorte do professor."""
    from fastapi.testclient import TestClient

    from app.main import app
    escola = escola_completa["escola"]
    minha = escola_completa["turma"]
    outra = Turma(escola_id=escola.id, nome="4º Ano B", ano_escolar="4º Ano",
                  ano_letivo=2026)
    db.add(outra)
    db.flush()
    prof = Professor(escola_id=escola.id, nome="Prof", email="prof@teste.local")
    db.add(prof)
    db.flush()
    minha.professor_id = prof.id
    db.add(Usuario(escola_id=escola.id, nome="Prof", email="prof@teste.local",
                   senha_hash=hash_senha("s3nh4"), cargo="professor"))
    alheio = Aluno(escola_id=escola.id, nome="Crianca da outra turma")
    db.add(alheio)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=alheio.id, turma_id=outra.id,
                     ano_letivo=2026))
    _semear(db, escola.id, alheio.id, "Alheio", datetime(2026, 9, 9, 10, 0), 30)
    _semear(db, escola.id, escola_completa["alunos"][0].id, "Meu",
            datetime(2026, 9, 9, 11, 0), 5)
    db.commit()

    c = TestClient(app)
    tok = c.post("/api/v1/auth/login",
                 data={"username": "prof@teste.local", "password": "s3nh4"})
    assert tok.status_code == 200, tok.text
    c.headers["Authorization"] = f"Bearer {tok.json()['access_token']}"
    resp = c.get(ROTA.format(eid=escola.id),
                 params={"periodo": "mes_anterior", "plataformas": "elefante"})
    assert resp.status_code == 200, resp.text
    corpo = resp.json()
    assert corpo["escopo"]["restrito_a_turmas"] == [minha.id]
    assert alheio.id not in [x["aluno_id"] for x in corpo["por_aluno"]]
    assert corpo["elefante"]["tempo_min"] == 5, "o 30 da outra turma não entra"

    negado = c.get(ROTA.format(eid=escola.id),
                   params={"escopo": "turma", "turma_id": outra.id})
    assert negado.status_code in (403, 404)


def test_rota_registra_a_consulta_na_auditoria(db, escola_completa, cliente):
    """O relatório não é persistido; o log guarda o PEDIDO, não o conteúdo."""
    escola = escola_completa["escola"]
    antes = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "relatorio.periodo_consultado")).scalars().all()
    resp = cliente.get(ROTA.format(eid=escola.id),
                       params={"periodo": "bimestre_3", "plataformas": "elefante"})
    assert resp.status_code == 200, resp.text
    depois = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "relatorio.periodo_consultado")).scalars().all()
    assert len(depois) == len(antes) + 1
    log = depois[-1]
    assert log.escola_id == escola.id
    assert log.detalhes["periodo"] == "bimestre_3"
    assert log.detalhes["plataformas"] == ["elefante"]
    assert "nome" not in str(log.detalhes).lower()
