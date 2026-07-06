"""Gestão de turmas: criar, editar, arquivar e excluir (com trava)."""
from sqlalchemy import create_engine, inspect, text

from app.core.database import migrar_colunas_novas


def _url(escola_id: int) -> str:
    return f"/api/v1/escolas/{escola_id}/turmas"


def test_criar_turma_completa(cliente, escola_completa):
    escola = escola_completa["escola"]
    resposta = cliente.post(_url(escola.id), json={
        "nome": "4º Ano A", "ano_escolar": "4º Ano", "ano_letivo": 2026,
        "turno": "manha", "capacidade_maxima": 30,
        "observacoes": "Sala 12, prédio novo.",
    })
    assert resposta.status_code == 201, resposta.text
    corpo = resposta.json()
    assert corpo["nome"] == "4º Ano A"
    assert corpo["turno"] == "manha"
    assert corpo["capacidade_maxima"] == 30
    assert corpo["status"] == "ativa"
    assert corpo["total_alunos"] == 0

    # aparece imediatamente na listagem padrão (filtros, importações, rankings)
    lista = cliente.get(_url(escola.id)).json()
    assert any(t["nome"] == "4º Ano A" for t in lista)


def test_nome_duplicado_no_mesmo_ano_e_recusado(cliente, escola_completa):
    escola = escola_completa["escola"]
    base = {"nome": "5º Ano B", "ano_escolar": "5º Ano", "ano_letivo": 2026}
    assert cliente.post(_url(escola.id), json=base).status_code == 201
    repetida = cliente.post(_url(escola.id), json={**base, "nome": "5º ano b"})
    assert repetida.status_code == 409
    assert "Já existe" in repetida.json()["detail"]
    # mesmo nome em OUTRO ano letivo é permitido (histórico multi-anos)
    outro_ano = cliente.post(_url(escola.id), json={**base, "ano_letivo": 2027})
    assert outro_ano.status_code == 201


def test_turno_invalido_e_recusado(cliente, escola_completa):
    escola = escola_completa["escola"]
    resposta = cliente.post(_url(escola.id), json={
        "nome": "6º Ano A", "ano_escolar": "6º Ano", "ano_letivo": 2026,
        "turno": "madrugada",
    })
    assert resposta.status_code == 422


def test_professor_de_outra_escola_e_recusado(cliente, db, escola_completa):
    from app.models import Escola, Professor

    outra = Escola(nome="OUTRA ESCOLA", ano_letivo_ativo=2026)
    db.add(outra)
    db.flush()
    intruso = Professor(escola_id=outra.id, nome="Prof. de Fora")
    db.add(intruso)
    db.commit()

    escola = escola_completa["escola"]
    resposta = cliente.post(_url(escola.id), json={
        "nome": "7º Ano A", "ano_escolar": "7º Ano", "ano_letivo": 2026,
        "professor_id": intruso.id,
    })
    assert resposta.status_code == 400


def test_editar_e_vincular_professor(cliente, escola_completa):
    escola = escola_completa["escola"]
    professor = cliente.post(
        f"/api/v1/escolas/{escola.id}/professores",
        json={"nome": "Regina Souza"}).json()
    turma = cliente.post(_url(escola.id), json={
        "nome": "8º Ano A", "ano_escolar": "8º Ano", "ano_letivo": 2026}).json()

    resposta = cliente.put(f"{_url(escola.id)}/{turma['id']}", json={
        "turno": "tarde", "professor_id": professor["id"],
        "capacidade_maxima": 25,
    })
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["turno"] == "tarde"
    assert corpo["professor_nome"] == "Regina Souza"
    assert corpo["capacidade_maxima"] == 25


def test_arquivar_esconde_da_lista_padrao(cliente, escola_completa):
    escola = escola_completa["escola"]
    turma = cliente.post(_url(escola.id), json={
        "nome": "9º Ano A", "ano_escolar": "9º Ano", "ano_letivo": 2026}).json()

    arquivada = cliente.put(f"{_url(escola.id)}/{turma['id']}",
                            json={"status": "arquivada"})
    assert arquivada.status_code == 200
    assert arquivada.json()["status"] == "arquivada"

    padrao = cliente.get(_url(escola.id)).json()
    assert all(t["id"] != turma["id"] for t in padrao)
    todas = cliente.get(f"{_url(escola.id)}?todas=true").json()
    assert any(t["id"] == turma["id"] for t in todas)

    # reativar traz de volta
    cliente.put(f"{_url(escola.id)}/{turma['id']}", json={"status": "ativa"})
    padrao = cliente.get(_url(escola.id)).json()
    assert any(t["id"] == turma["id"] for t in padrao)


def test_excluir_bloqueado_com_alunos_vinculados(cliente, db, escola_completa):
    from app.models import Matricula

    escola = escola_completa["escola"]
    turma = escola_completa["turma"]          # tem 3 alunos matriculados

    resposta = cliente.delete(f"{_url(escola.id)}/{turma.id}")
    assert resposta.status_code == 409
    detalhe = resposta.json()["detail"]
    assert "3 aluno(s) vinculado(s)" in detalhe
    assert "Mova ou remova os alunos" in detalhe

    # contagem aparece na listagem da tela de gestão
    lista = cliente.get(_url(escola.id)).json()
    assert next(t for t in lista if t["id"] == turma.id)["total_alunos"] == 3

    # sem alunos, a exclusão é liberada
    db.query(Matricula).filter(Matricula.turma_id == turma.id).delete()
    db.commit()
    liberada = cliente.delete(f"{_url(escola.id)}/{turma.id}")
    assert liberada.status_code == 200
    assert "excluída" in liberada.json()["mensagem"]
    assert all(t["id"] != turma.id
               for t in cliente.get(f"{_url(escola.id)}?todas=true").json())


def test_turma_nova_recebe_alunos(cliente, escola_completa):
    escola = escola_completa["escola"]
    turma = cliente.post(_url(escola.id), json={
        "nome": "1º Ano C", "ano_escolar": "1º Ano", "ano_letivo": 2026,
        "turno": "integral"}).json()
    aluno = cliente.post(f"/api/v1/escolas/{escola.id}/alunos", json={
        "nome": "Aluno Novo da Silva", "turma_id": turma["id"]})
    assert aluno.status_code == 201, aluno.text
    lista = cliente.get(_url(escola.id)).json()
    assert next(t for t in lista if t["id"] == turma["id"])["total_alunos"] == 1


def test_migracao_adiciona_colunas_em_banco_antigo():
    """Banco de instalação anterior (sem as colunas novas) é atualizado."""
    motor = create_engine("sqlite://")
    with motor.begin() as conexao:
        conexao.execute(text(
            "CREATE TABLE turmas (id INTEGER PRIMARY KEY, escola_id INTEGER, "
            "nome VARCHAR(100), ano_escolar VARCHAR(30), ano_letivo INTEGER, "
            "professor_id INTEGER, created_at TIMESTAMP)"))
        conexao.execute(text(
            "INSERT INTO turmas (escola_id, nome, ano_escolar, ano_letivo) "
            "VALUES (1, '4º Ano B', '4º Ano', 2026)"))

    migrar_colunas_novas(motor)
    migrar_colunas_novas(motor)  # idempotente

    colunas = {c["name"] for c in inspect(motor).get_columns("turmas")}
    assert {"turno", "capacidade_maxima", "observacoes", "status"} <= colunas
    with motor.connect() as conexao:
        status = conexao.execute(text("SELECT status FROM turmas")).scalar_one()
    assert status == "ativa"    # linhas antigas nascem ativas
