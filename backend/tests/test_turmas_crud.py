"""Gestão de turmas: criar, editar, arquivar e excluir (com trava)."""


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


def test_excluir_turma_com_alunos_apaga_tudo(cliente, db, escola_completa):
    """com_alunos=true: exclui a turma E os alunos com todos os dados."""
    from app.models import Aluno, Matricula

    escola = escola_completa["escola"]
    turma = escola_completa["turma"]                     # 3 alunos matriculados
    aluno_ids = [a.id for a in escola_completa["alunos"]]

    resp = cliente.delete(f"{_url(escola.id)}/{turma.id}?com_alunos=true")
    assert resp.status_code == 200, resp.text
    corpo = resp.json()
    assert corpo["excluidas"] == 1
    assert corpo["alunos_excluidos"] == 3
    assert "3 aluno(s)" in corpo["mensagem"]

    # a turma some da listagem (mesmo com ?todas=true)
    assert all(t["id"] != turma.id
               for t in cliente.get(f"{_url(escola.id)}?todas=true").json())
    # exclusão FÍSICA: alunos e matrículas somem do banco
    assert db.query(Aluno).filter(Aluno.id.in_(aluno_ids)).count() == 0
    assert db.query(Matricula).filter(Matricula.turma_id == turma.id).count() == 0


def test_excluir_massa_com_alunos(cliente, db, escola_completa):
    """Exclusão em massa (POST /turmas/excluir) com com_alunos=true remove todas
    as turmas selecionadas e todos os alunos delas."""
    from app.models import Aluno, Turma

    escola = escola_completa["escola"]
    turma1 = escola_completa["turma"]                    # 3 alunos
    turma2 = cliente.post(_url(escola.id), json={
        "nome": "2º Ano B", "ano_escolar": "2º Ano", "ano_letivo": 2026}).json()
    assert cliente.post(f"/api/v1/escolas/{escola.id}/alunos",
                        json={"nome": "Novo Aluno Teste",
                              "turma_id": turma2["id"]}).status_code == 201

    resp = cliente.post(f"{_url(escola.id)}/excluir", json={
        "turma_ids": [turma1.id, turma2["id"]], "com_alunos": True})
    assert resp.status_code == 200, resp.text
    corpo = resp.json()
    assert corpo["excluidas"] == 2
    assert corpo["alunos_excluidos"] == 4                # 3 + 1
    assert corpo["bloqueadas"] == 0

    assert cliente.get(f"{_url(escola.id)}?todas=true").json() == []
    assert db.query(Turma).filter(Turma.escola_id == escola.id).count() == 0
    assert db.query(Aluno).filter(Aluno.escola_id == escola.id).count() == 0


def test_excluir_massa_sem_alunos_mantem_as_que_tem_alunos(cliente, escola_completa):
    """com_alunos=false: só as turmas VAZIAS são excluídas; as que têm alunos
    são mantidas e reportadas em `bloqueadas`."""
    escola = escola_completa["escola"]
    turma_com = escola_completa["turma"]                 # 3 alunos
    turma_vazia = cliente.post(_url(escola.id), json={
        "nome": "1º Ano D", "ano_escolar": "1º Ano", "ano_letivo": 2026}).json()

    resp = cliente.post(f"{_url(escola.id)}/excluir", json={
        "turma_ids": [turma_com.id, turma_vazia["id"]], "com_alunos": False})
    assert resp.status_code == 200, resp.text
    corpo = resp.json()
    assert corpo["excluidas"] == 1                       # só a vazia
    assert corpo["bloqueadas"] == 1                      # a que tem alunos
    assert corpo["alunos_excluidos"] == 0

    restantes = {t["id"] for t in cliente.get(f"{_url(escola.id)}?todas=true").json()}
    assert turma_com.id in restantes                     # preservada
    assert turma_vazia["id"] not in restantes            # excluída


def test_excluir_turma_com_alunos_preserva_aluno_ainda_em_outra_turma(
        cliente, db, escola_completa):
    """Excluir uma turma antiga 'com alunos e dados' NÃO apaga o aluno que ainda
    tem matrícula em outra turma (ex.: o ano ativo) — ele é só DESVINCULADO."""
    from app.models import Aluno, Matricula, Turma

    escola = escola_completa["escola"]
    turma_atual = escola_completa["turma"]           # 2026, 3 alunos ativos
    aluno = escola_completa["alunos"][0]

    antiga = Turma(escola_id=escola.id, nome="3º Ano A (2025)",
                   ano_escolar="3º Ano", ano_letivo=2025)
    db.add(antiga)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=aluno.id,
                     turma_id=antiga.id, ano_letivo=2025))
    db.commit()

    resp = cliente.delete(f"{_url(escola.id)}/{antiga.id}?com_alunos=true")
    assert resp.status_code == 200, resp.text
    corpo = resp.json()
    assert corpo["excluidas"] == 1
    assert corpo["alunos_excluidos"] == 0            # ninguém é apagado
    assert corpo["alunos_desvinculados"] == 1        # só desvinculado

    # o aluno continua existindo, com a matrícula ATUAL (2026) intacta
    assert db.get(Aluno, aluno.id) is not None
    assert db.query(Matricula).filter(
        Matricula.aluno_id == aluno.id,
        Matricula.turma_id == turma_atual.id).count() == 1
    # e sem o vínculo com a turma antiga
    assert db.query(Matricula).filter(
        Matricula.aluno_id == aluno.id,
        Matricula.turma_id == antiga.id).count() == 0


def test_total_matriculas_conta_cruas_e_bloqueia_arquivados(cliente, db, escola_completa):
    """total_matriculas reflete matrículas CRUAS (inclui alunos arquivados); a
    exclusão simples continua bloqueada mesmo com total_alunos (filtrado) = 0."""
    from app.models import Aluno

    escola = escola_completa["escola"]
    turma = escola_completa["turma"]                 # 3 alunos ativos
    for a in escola_completa["alunos"]:              # arquiva todos
        db.get(Aluno, a.id).status = "arquivado"
    db.commit()

    item = next(t for t in cliente.get(f"{_url(escola.id)}?todas=true").json()
                if t["id"] == turma.id)
    assert item["total_alunos"] == 0                 # nenhum ativo
    assert item["total_matriculas"] == 3             # matrículas cruas seguem

    # exclusão simples permanece BLOQUEADA (evita órfãos) — a UI usa
    # total_matriculas para NÃO chamar a turma de "vazia".
    assert cliente.delete(f"{_url(escola.id)}/{turma.id}").status_code == 409

    # com_alunos=true apaga os 3 (nenhum está em outra turma)
    ok = cliente.delete(f"{_url(escola.id)}/{turma.id}?com_alunos=true")
    assert ok.status_code == 200, ok.text
    assert ok.json()["alunos_excluidos"] == 3


def test_excluir_massa_isola_por_escola(cliente, db, escola_completa):
    """turma_ids de OUTRA escola são ignorados (escopo multi-tenant)."""
    from app.models import Escola, Turma

    outra = Escola(nome="ESCOLA VIZINHA", ano_letivo_ativo=2026)
    db.add(outra)
    db.flush()
    turma_alheia = Turma(escola_id=outra.id, nome="Turma Alheia",
                         ano_escolar="1º Ano", ano_letivo=2026)
    db.add(turma_alheia)
    db.commit()

    escola = escola_completa["escola"]
    resp = cliente.post(f"{_url(escola.id)}/excluir", json={
        "turma_ids": [turma_alheia.id], "com_alunos": True})
    assert resp.status_code == 200, resp.text
    assert resp.json()["excluidas"] == 0                 # nada da outra escola
    # a turma da outra escola continua existindo
    assert db.query(Turma).filter(Turma.id == turma_alheia.id).count() == 1


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
