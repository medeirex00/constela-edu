"""Testes da Fase 4 — gamificação, relatórios, administração e utilidades."""
import json

import pytest

from app.models import Importacao, Leitura, Livro, SnapshotElefante, SnapshotMatific, Usuario
from app.services import backup as svc_backup
from app.services import gamificacao as svc_gami
from app.services import scoring


def _dados_basicos(db, escola_completa):
    """Snapshots para Ana (fortes) e João (fracos)."""
    escola = escola_completa["escola"]
    ana, joao, _ = escola_completa["alunos"]
    importacao = Importacao(escola_id=escola.id, plataforma="matific", tipo="seed")
    db.add(importacao)
    db.flush()
    db.add_all([
        SnapshotMatific(escola_id=escola.id, aluno_id=ana.id, importacao_id=importacao.id,
                        atividades=60, estrelas=250, pontuacao_media=88),
        SnapshotElefante(escola_id=escola.id, aluno_id=ana.id, importacao_id=importacao.id,
                         livros_unicos=6, tempo_leitura_min=320,
                         questoes_tentativas=30, questoes_acertos=27,
                         livros_por_nivel={"AA": 4, "D": 2}),
        SnapshotMatific(escola_id=escola.id, aluno_id=joao.id, importacao_id=importacao.id,
                        atividades=5, estrelas=12, pontuacao_media=60),
    ])
    db.commit()
    return importacao


# --- Gamificação ----------------------------------------------------------------

def test_xp_e_nivel_derivados_dos_snapshots(db, escola_completa):
    _dados_basicos(db, escola_completa)
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]

    resultado = svc_gami.gamificacao_do_aluno(db, escola.id, ana.id)
    # XP padrão: 60*2 + 250*1 + 6*10 + 27*3 + 320*0.2 = 120+250+60+81+64 = 575
    assert resultado["xp"] == 575
    assert resultado["nivel"] == 6  # base 100 XP por nível
    assert resultado["xp_para_proximo"] == 25


def test_conquistas_com_progresso_e_data(db, escola_completa):
    _dados_basicos(db, escola_completa)
    escola = escola_completa["escola"]
    ana, joao, _ = escola_completa["alunos"]

    de_ana = svc_gami.gamificacao_do_aluno(db, escola.id, ana.id)
    conquistas = {c["codigo"]: c for c in de_ana["conquistas"]}
    assert conquistas["leitor_bronze"]["atingida"] is True
    assert conquistas["leitor_bronze"]["data"] is not None
    assert conquistas["leitor_ouro"]["atingida"] is False
    assert conquistas["leitor_ouro"]["progresso"] == 6
    # 90% de acertos com 30 tentativas ≥ mínimo → craque
    assert conquistas["craque_questoes"]["atingida"] is True
    assert conquistas["maratonista"]["atingida"] is True

    de_joao = svc_gami.gamificacao_do_aluno(db, escola.id, joao.id)
    conquistas_joao = {c["codigo"]: c for c in de_joao["conquistas"]}
    assert conquistas_joao["primeira_leitura"]["atingida"] is False


def test_ranking_xp_ordena_e_posiciona(db, escola_completa):
    _dados_basicos(db, escola_completa)
    escola = escola_completa["escola"]
    itens = svc_gami.ranking_xp(db, escola.id)
    assert itens[0]["nome"] == "Ana Beatriz Souza"
    assert itens[0]["posicao"] == 1
    assert itens[0]["xp"] > itens[1]["xp"]


def test_mural_traz_destaques_e_eventos(cliente, db, escola_completa):
    _dados_basicos(db, escola_completa)
    escola = escola_completa["escola"]
    resposta = cliente.get(f"/api/v1/escolas/{escola.id}/gamificacao/mural")
    assert resposta.status_code == 200
    corpo = resposta.json()
    # Ana cresceu no período (snapshot recente) → destaque do mês
    assert corpo["destaques"]["mes"]["nome"] == "Ana Beatriz Souza"
    assert any(evento["tipo"] == "conquista" for evento in corpo["eventos"])


# --- Relatórios -----------------------------------------------------------------

def test_exportar_csv_xlsx_pdf(cliente, db, escola_completa):
    _dados_basicos(db, escola_completa)
    escola = escola_completa["escola"]
    scoring.recalcular_escola(db, escola.id)

    csv_resposta = cliente.get(
        f"/api/v1/escolas/{escola.id}/relatorios/ranking", params={"formato": "csv"})
    assert csv_resposta.status_code == 200
    texto = csv_resposta.content.decode("utf-8-sig")
    assert "Ana Beatriz Souza" in texto
    assert texto.splitlines()[0].startswith("Posição;Aluno;Turma")

    xlsx_resposta = cliente.get(
        f"/api/v1/escolas/{escola.id}/relatorios/alunos", params={"formato": "xlsx"})
    assert xlsx_resposta.status_code == 200
    assert xlsx_resposta.content[:4] == b"PK\x03\x04"  # zip do xlsx

    pdf_resposta = cliente.get(
        f"/api/v1/escolas/{escola.id}/relatorios/ranking", params={"formato": "pdf"})
    assert pdf_resposta.status_code == 200
    assert pdf_resposta.content[:5] == b"%PDF-"


def test_certificado_pdf(cliente, db, escola_completa):
    _dados_basicos(db, escola_completa)
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    scoring.recalcular_escola(db, escola.id)

    resposta = cliente.get(f"/api/v1/escolas/{escola.id}/certificados/{ana.id}")
    assert resposta.status_code == 200
    assert resposta.content[:5] == b"%PDF-"


# --- Usuários -------------------------------------------------------------------

def test_crud_usuarios_com_protecoes(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    criado = cliente.post(
        f"/api/v1/escolas/{escola.id}/usuarios",
        json={"nome": "Coordenadora", "email": "coord@escola.com.br",
              "senha": "segredo1", "cargo": "coordenador"},
    )
    assert criado.status_code == 201, criado.text
    usuario_id = criado.json()["id"]

    duplicado = cliente.post(
        f"/api/v1/escolas/{escola.id}/usuarios",
        json={"nome": "Outra", "email": "coord@escola.com.br", "senha": "segredo2"},
    )
    assert duplicado.status_code == 409

    desativado = cliente.patch(
        f"/api/v1/escolas/{escola.id}/usuarios/{usuario_id}",
        json={"status": "inativo"},
    )
    assert desativado.status_code == 200
    assert desativado.json()["id"] == usuario_id

    # Autopreservação: admin não desativa a própria conta
    admin = escola_completa["admin"]
    proprio = cliente.patch(
        f"/api/v1/escolas/{escola.id}/usuarios/{admin.id}",
        json={"status": "inativo"},
    )
    assert proprio.status_code == 400


def test_usuario_comum_nao_gerencia_usuarios(cliente, db, escola_completa):
    from app.core.security import hash_senha
    escola = escola_completa["escola"]
    db.add(Usuario(escola_id=escola.id, nome="Prof", email="prof@teste.local",
                   senha_hash=hash_senha("s3nh4"), cargo="professor"))
    db.commit()
    from fastapi.testclient import TestClient
    from app.main import app
    outro = TestClient(app)
    login = outro.post("/api/v1/auth/login",
                       data={"username": "prof@teste.local", "password": "s3nh4"})
    outro.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    resposta = outro.get(f"/api/v1/escolas/{escola.id}/usuarios")
    assert resposta.status_code == 403


# --- Backup e restauração ---------------------------------------------------------

def test_backup_e_restauracao_roundtrip(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    importacao = _dados_basicos(db, escola_completa)
    livro = Livro(escola_id=escola.id, titulo="Livro do Backup", nivel_codigo="AA")
    db.add(livro)
    db.flush()
    db.add(Leitura(escola_id=escola.id, aluno_id=ana.id, livro_id=livro.id))
    db.commit()
    scoring.recalcular_escola(db, escola.id)

    baixado = cliente.get(f"/api/v1/escolas/{escola.id}/backup")
    assert baixado.status_code == 200
    dados = json.loads(baixado.content)
    assert dados["versao"] == 1
    assert len(dados["tabelas"]["alunos"]) == 3
    assert len(dados["tabelas"]["leituras"]) == 1

    # Restaura por cima (substituição completa, IDs remapeados)
    resposta = cliente.post(
        f"/api/v1/escolas/{escola.id}/restaurar",
        files={"arquivo": ("backup.json", baixado.content, "application/json")},
    )
    assert resposta.status_code == 200, resposta.text

    from app.models import Aluno
    alunos = db.query(Aluno).filter_by(escola_id=escola.id).all()
    assert len(alunos) == 3
    assert {a.nome for a in alunos} == {
        "Ana Beatriz Souza", "João Pedro Barbosa", "Sofia Almeida Duarte"}
    # Leituras vieram junto, apontando para os NOVOS ids
    leituras = db.query(Leitura).filter_by(escola_id=escola.id).all()
    assert len(leituras) == 1
    assert db.query(Livro).filter_by(id=leituras[0].livro_id).one().titulo == "Livro do Backup"


def test_restaurar_arquivo_invalido_nao_apaga_nada(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    resposta = cliente.post(
        f"/api/v1/escolas/{escola.id}/restaurar",
        files={"arquivo": ("backup.json", b"{nao json", "application/json")},
    )
    assert resposta.status_code == 400
    from app.models import Aluno
    assert db.query(Aluno).filter_by(escola_id=escola.id).count() == 3


# --- Pesquisa, notificações e simulador -------------------------------------------

def test_pesquisa_global(cliente, escola_completa):
    escola = escola_completa["escola"]
    resposta = cliente.get(f"/api/v1/escolas/{escola.id}/pesquisa", params={"q": "ana"})
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert any("Ana" in item["nome"] for item in corpo["alunos"])


def test_notificacoes_derivadas_da_auditoria(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    cliente.post(
        f"/api/v1/escolas/{escola.id}/importacoes/confirmar",
        json={"plataforma": "matific", "formato": "resumo", "tipo": "texto",
              "linhas": [{"nome": ana.nome,
                          "dados": {"atividades": 3, "pontuacao_media": 50, "estrelas": 5},
                          "aluno_id": ana.id}]},
    )
    resposta = cliente.get(f"/api/v1/escolas/{escola.id}/notificacoes")
    assert resposta.status_code == 200
    assert any("importação" in n["texto"].casefold() for n in resposta.json())


def test_simulador_usa_regras_atuais_sem_gravar(cliente, db, escola_completa):
    _dados_basicos(db, escola_completa)
    escola = escola_completa["escola"]
    scoring.recalcular_escola(db, escola.id)
    from app.models import Nota
    notas_antes = db.query(Nota).count()
    snaps_antes = db.query(SnapshotMatific).count()

    resposta = cliente.post(
        f"/api/v1/escolas/{escola.id}/simulador",
        json={"ano_escolar": "3º Ano", "atividades": 60, "pontuacao_media": 88,
              "estrelas": 250, "livros_por_nivel": {"AA": 4, "D": 2},
              "tempo_leitura_min": 320, "questoes_tentativas": 30,
              "questoes_acertos": 27},
    )
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    # Simulando exatamente os dados da Ana (a melhor da escola), nota = 100
    assert corpo["geral"]["nota"] == pytest.approx(100.0)
    # E nada foi gravado
    assert db.query(Nota).count() == notas_antes
    assert db.query(SnapshotMatific).count() == snaps_antes
