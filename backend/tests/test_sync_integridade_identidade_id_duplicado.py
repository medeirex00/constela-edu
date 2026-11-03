"""ID EXTERNO DUPLICADO no mesmo relatório (frente B, 22/10/2026).

O importador guarda só a ÚLTIMA linha de cada aluno: duas linhas com o mesmo
uuid/studentId e nomes diferentes punham os números de uma criança na ficha da
outra, sem aviso (e92 09d/09e). O que estes testes travam, com dados FICTÍCIOS:

  * nenhuma das linhas aplica número em ficha nenhuma — revisão
    ``id_externo_duplicado``, UMA pendência por nome; o vínculo que já existia
    fica intacto e a dona dele aparece como candidata;
  * no Matific o nome cheio vem do próprio uuid, então duas contas coladas no
    mesmo uuid chegam com o MESMO nome e números diferentes: também é conflito, e
    ao resolver vale só o vínculo — nenhum número é escolhido no escuro;
  * a disputa aberta no resumo do Elefante segura também o histórico de leituras
    que vem no arquivo seguinte (o conector já o traz com um nome só);
  * a mesma linha repetida idêntica e o mesmo id em vários livros NÃO são conflito.
"""
from app.services import identidade_aluno as ida
from app.services.importacao import LinhaImportacao
from tests.sync_integridade_comum import (aplicar, dono, elefante_leituras, elefante_resumo,
                                          fichas, leituras, matific, pendentes, sem_disco,
                                          snap_elefante, snap_matific, vincular)

K = "3 ANO A TARDE ANUAL (300396804)"      # a sala "3º Ano A" do escola_completa


def test_matific_mesmo_uuid_com_nomes_diferentes_nao_aplica_em_ninguem(
        db, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    escola = escola_completa["escola"]
    a, b, _c = escola_completa["alunos"]
    antes = fichas(db, escola.id)

    aplicar(db, escola, matific(K, [
        {"nome": a.nome, "nome_abrev": "ANA B", "uuid": "u-dup", "estrelas": 40, "atividades": 10},
        {"nome": b.nome, "nome_abrev": "JOAO B", "uuid": "u-dup", "estrelas": 30, "atividades": 8}]))

    assert fichas(db, escola.id) == antes
    assert snap_matific(db, a.id) is None and snap_matific(db, b.id) is None
    assert dono(db, escola.id, "matific", "u-dup") is None
    revs = pendentes(db, escola.id, "id_externo_duplicado")
    assert sorted(r.nome_recebido for r in revs) == sorted([a.nome, b.nome])  # uma por nome


def test_mesmo_uuid_ja_vinculado_nao_recebe_os_numeros_da_outra_linha(
        db, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    escola = escola_completa["escola"]
    a, b, _c = escola_completa["alunos"]
    vincular(db, escola.id, a.id, "matific", "u-a")
    db.commit()

    aplicar(db, escola, matific(K, [
        {"nome": a.nome, "nome_abrev": "ANA B", "uuid": "u-a", "estrelas": 40, "atividades": 10},
        {"nome": b.nome, "nome_abrev": "JOAO B", "uuid": "u-a", "estrelas": 30, "atividades": 8}]))

    assert snap_matific(db, a.id) is None and snap_matific(db, b.id) is None
    revs = pendentes(db, escola.id, "id_externo_duplicado")
    assert len(revs) == 2
    assert all([c["aluno_id"] for c in r.candidatos] == [a.id] for r in revs)
    assert dono(db, escola.id, "matific", "u-a") == a.id    # vínculo intacto


def test_mesmo_uuid_mesmo_nome_numeros_diferentes_resolver_nao_escolhe_numeros(
        db, cliente, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    escola = escola_completa["escola"]
    b = escola_completa["alunos"][1]
    aplicar(db, escola, matific(K, [
        {"nome": b.nome, "nome_abrev": "ANA B", "uuid": "u-dup", "estrelas": 40, "atividades": 10},
        {"nome": b.nome, "nome_abrev": "JOAO B", "uuid": "u-dup", "estrelas": 30, "atividades": 8}]))
    assert snap_matific(db, b.id) is None
    [rev] = pendentes(db, escola.id, "id_externo_duplicado")
    assert len(rev.linhas) == 2

    r = cliente.post(f"/api/v1/escolas/{escola.id}/importacoes/revisoes/{rev.id}/resolver",
                     json={"aluno_id": b.id})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert snap_matific(db, b.id) is None                  # nenhum número escolhido
    assert dono(db, escola.id, "matific", "u-dup") == b.id
    assert any("números diferentes" in a for a in r.json()["avisos"])


def test_linha_repetida_identica_nao_e_conflito(db, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    escola = escola_completa["escola"]
    a = escola_completa["alunos"][0]
    linha = {"nome": a.nome, "nome_abrev": "ANA B", "uuid": "u-a", "estrelas": 40,
             "atividades": 10}
    aplicar(db, escola, matific(K, [linha, dict(linha)]))
    s = snap_matific(db, a.id)
    assert s is not None and (s.estrelas, s.atividades) == (40, 10)
    assert pendentes(db, escola.id) == []


def test_elefante_mesmo_student_id_no_resumo_segura_tambem_as_leituras(
        db, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    escola = escola_completa["escola"]
    a, b, _c = escola_completa["alunos"]
    sala = "3 ANO A TARDE ANUAL"

    aplicar(db, escola, elefante_resumo(sala, [
        {"studentId": 9100777, "studentName": a.nome, "totalBooksRead": 1},
        {"studentId": 9100777, "studentName": b.nome, "totalBooksRead": 7}]))
    aplicar(db, escola, elefante_leituras(sala, [
        {"nome": b.nome, "studentId": 9100777, "bookTitle": "Livro Ficticio Um",
         "lastReadWhen": "2026-09-02T10:00:00"}]))

    for x in (a, b):
        assert snap_elefante(db, x.id) is None
        assert leituras(db, x.id) == 0
    assert dono(db, escola.id, "elefante", "9100777") is None
    revs = pendentes(db, escola.id, "id_externo_duplicado")
    assert sorted((r.formato, r.nome_recebido) for r in revs) == sorted(
        [("resumo", a.nome), ("resumo", b.nome), ("leituras", b.nome)])


def test_elefante_mesmo_id_mesmo_nome_em_varios_livros_e_normal(
        db, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    escola = escola_completa["escola"]
    a = escola_completa["alunos"][0]
    aplicar(db, escola, elefante_leituras("3 ANO A TARDE ANUAL", [
        {"nome": a.nome, "studentId": 9100001, "bookTitle": "Livro Ficticio Um",
         "lastReadWhen": "2026-09-02T10:00:00"},
        {"nome": a.nome, "studentId": 9100001, "bookTitle": "Livro Ficticio Dois",
         "lastReadWhen": "2026-09-03T10:00:00"}]))
    assert leituras(db, a.id) == 2
    assert pendentes(db, escola.id) == []


def test_marcar_ids_em_conflito_regra():
    ctx = ida.Contexto(escola_id=1, ano=2026)
    linhas = [
        LinhaImportacao(numero=1, nome="ANA FICTICIA 3B", dados={"matific_uuid": "u-1", "estrelas": 1}),
        LinhaImportacao(numero=2, nome="ANA FICTICIA", dados={"matific_uuid": "u-1", "estrelas": 1}),
        LinhaImportacao(numero=3, nome="BIA FICTICIA", dados={"matific_uuid": "u-2", "estrelas": 1}),
        LinhaImportacao(numero=4, nome="CAIO FICTICIO", dados={"matific_uuid": "u-2", "estrelas": 1}),
        LinhaImportacao(numero=5, nome="DUDA FICTICIA", dados={"matific_uuid": "", "estrelas": 1}),
        LinhaImportacao(numero=6, nome="EVA FICTICIA", dados={"matific_uuid": "", "estrelas": 2}),
    ]
    # sufixo de turma não faz outra criança; id vazio não é id
    assert ida.marcar_ids_em_conflito(ctx, linhas, "matific") == {("matific", "u-2")}


def test_triagem_nunca_diz_segura_para_id_duplicado(db, escola_completa, monkeypatch):
    """A conta já vinculada NÃO desempata uma pendência de id duplicado: pode ser
    justamente a da outra criança."""
    from app.services import triagem_revisoes
    sem_disco(monkeypatch)
    escola = escola_completa["escola"]
    a, b, _c = escola_completa["alunos"]
    vincular(db, escola.id, a.id, "matific", "u-a")
    db.commit()
    aplicar(db, escola, matific(K, [
        {"nome": a.nome, "nome_abrev": "ANA B", "uuid": "u-a", "estrelas": 40, "atividades": 10},
        {"nome": b.nome, "nome_abrev": "JOAO B", "uuid": "u-a", "estrelas": 30, "atividades": 8}]))
    revs = pendentes(db, escola.id, "id_externo_duplicado")
    triagens = triagem_revisoes.triar_revisoes(ida.carregar_contexto(db, escola.id), revs)
    assert {t.classificacao for t in triagens.values()} == {triagem_revisoes.DECISAO_HUMANA}
