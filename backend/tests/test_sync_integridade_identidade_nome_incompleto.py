"""NOME INCOMPLETO do Matific na sincronização (frente B, 22/10/2026 — S6).

O Placar do Matific (school_student) só traz o nome ABREVIADO ("ANNA E"); o nome
cheio vem do student-leaderboard, por uuid. Quando o uuid não está lá (ou a
competição veio vazia), a linha chega só com o abreviado — e era assim que a
sync criava a ficha "ANNA E" (escola 11, 02/10; escola 17, 25/09) ou casava pelo
nome abreviado. O que estes testes travam, com dados FICTÍCIOS:

  * o parser marca a linha (``nome_incompleto``) só quando o nome cheio não veio;
  * com a política "permitir" (padrão) ou "bloquear": nunca cria ficha nem
    associa pelo nome abreviado — revisão ``nome_incompleto``, com os candidatos
    que o motor achou para quem for decidir;
  * a ficha que JÁ tem o uuid continua recebendo, e a decisão de um gestor na
    revisão vale nas coletas seguintes (o uuid fica vinculado);
  * com o nome completo nada muda; a prévia mostra a mesma decisão.
"""
from app.services import politica_sync
from app.services.importacao import LinhaImportacao, analisar_matific_api, casar_nomes
from tests.sync_integridade_comum import (aplicar, com_nome, dono, fichas, matific,
                                          pendentes, sem_disco, snap_matific, vincular)

K = "3 ANO A TARDE ANUAL (300396804)"      # a sala "3º Ano A" do escola_completa


def _abreviada(uuid="u-ana", nome="ANA B", estrelas=40, atividades=10):
    return {"nome": nome, "nome_abrev": nome, "uuid": uuid,
            "estrelas": estrelas, "atividades": atividades}


def test_parser_marca_nome_incompleto_so_quando_o_nome_cheio_nao_veio():
    analise = analisar_matific_api({"turma": K, "alunos": [
        {"nome": "ANA B", "nome_abrev": "ANA B", "uuid": "u-1", "estrelas": 4, "atividades": 2},
        {"nome": "Ana Beatriz Souza", "nome_abrev": "ANA B", "uuid": "u-2",
         "estrelas": 4, "atividades": 2},
        {"nome": "Ana Beatriz Souza", "uuid": "u-3", "estrelas": 4, "atividades": 2}]})
    marcas = [l.dados.get("nome_incompleto") for l in analise.linhas]
    assert marcas == [True, None, None]


def test_nome_incompleto_nao_cria_nem_associa_com_politica_permitir(
        db, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]                 # "Ana Beatriz Souza"
    assert politica_sync.pode_criar_aluno(db, escola.id) is True
    antes = fichas(db, escola.id)

    aplicar(db, escola, matific(K, [_abreviada(),
                                    _abreviada(uuid="u-zefa", nome="ZEFA Q")]))

    assert fichas(db, escola.id) == antes               # nem "ANA B" nem "ZEFA Q"
    assert com_nome(db, escola.id, "ZEFA Q") == []
    assert snap_matific(db, ana.id) is None             # não associou pela abreviação
    assert dono(db, escola.id, "matific", "u-ana") is None
    revs = {r.nome_recebido: r for r in pendentes(db, escola.id, "nome_incompleto")}
    assert set(revs) == {"ANA B", "ZEFA Q"}
    # quem decide vê o candidato que o motor achou pela abreviação
    assert [c["aluno_id"] for c in revs["ANA B"].candidatos] == [ana.id]
    assert revs["ZEFA Q"].candidatos == []


def test_nome_incompleto_com_politica_bloquear_tambem_vai_para_revisao(
        db, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    escola = escola_completa["escola"]
    politica_sync.definir(db, escola.id, "bloquear")
    db.commit()
    antes = fichas(db, escola.id)

    aplicar(db, escola, matific(K, [_abreviada(uuid="u-zefa", nome="ZEFA Q")]))

    assert fichas(db, escola.id) == antes
    [rev] = pendentes(db, escola.id)
    assert rev.motivo == "nome_incompleto"              # o motivo verdadeiro, não a política


def test_ficha_com_o_uuid_vinculado_continua_recebendo_mesmo_com_nome_abreviado(
        db, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    vincular(db, escola.id, ana.id, "matific", "u-ana")
    db.commit()

    aplicar(db, escola, matific(K, [_abreviada(estrelas=77, atividades=21)]))

    s = snap_matific(db, ana.id)
    assert s is not None and (s.estrelas, s.atividades) == (77, 21)
    assert pendentes(db, escola.id) == []


def test_nome_cheio_continua_casando_pelo_nome(db, escola_completa, monkeypatch):
    """Controle: com o nome COMPLETO (veio do student-leaderboard) nada muda."""
    sem_disco(monkeypatch)
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    aplicar(db, escola, matific(K, [{"nome": ana.nome, "nome_abrev": "ANA B", "uuid": "u-ana",
                                     "estrelas": 40, "atividades": 10}]))
    assert snap_matific(db, ana.id) is not None
    assert dono(db, escola.id, "matific", "u-ana") == ana.id


def test_decisao_do_gestor_na_revisao_vale_nas_coletas_seguintes(
        db, cliente, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    aplicar(db, escola, matific(K, [_abreviada()]))
    [rev] = pendentes(db, escola.id, "nome_incompleto")

    r = cliente.post(f"/api/v1/escolas/{escola.id}/importacoes/revisoes/{rev.id}/resolver",
                     json={"aluno_id": ana.id})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert dono(db, escola.id, "matific", "u-ana") == ana.id

    aplicar(db, escola, matific(K, [_abreviada(estrelas=90, atividades=30)]))
    s = snap_matific(db, ana.id)
    assert s is not None and (s.estrelas, s.atividades) == (90, 30)
    assert pendentes(db, escola.id) == []


def test_previa_mostra_a_mesma_revisao_que_a_sync_fara(db, escola_completa):
    escola = escola_completa["escola"]
    linha = LinhaImportacao(numero=1, nome="ANA B", dados={
        "matific_uuid": "u-ana", "turma_relatorio": K, "nome_incompleto": True,
        "estrelas": 4, "atividades": 2})
    casar_nomes(db, escola.id, [linha], plataforma="matific")
    assert linha.correspondencia["status"] == "revisar"
    assert linha.correspondencia["motivo"] == "nome_incompleto"
