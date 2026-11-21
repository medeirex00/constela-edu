"""A2 (forma ampliada): nome ABREVIADO não cria ficha em fonte nenhuma.

Antes a trava só existia no Placar do Matific com ``nome_abrev``; o Elefante
"ZEFA Q", o Placar sem ``nome_abrev``, a planilha e o PDF criavam a ficha
abreviada com a política "permitir" — o mesmo caminho que encheu a rede de
"LORENA D" ao lado das oficiais. Agora viram a revisão ``nome_incompleto``.

Só a CRIAÇÃO é barrada: associar por abreviação à ficha certa continua igual
(``test_sync_nao_repete_stub``). Dados fictícios.
"""
import pytest

from app.models import Aluno
from app.services import identidade_aluno as ida
from app.services.importacao import LinhaImportacao, casar_nomes
from tests.sync_integridade_comum import (aluno, aplicar, com_nome, dono, elefante_resumo, fichas,
                                          matific, pendentes, sem_disco)

K = "3 ANO A TARDE ANUAL (300396804)"


def _esc(ec):
    return ec["escola"], ec["turma"], ec["admin"]


def test_elefante_abreviado_sem_candidato_vai_para_a_revisao(db, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    esc, _, _ = _esc(escola_completa)
    antes = fichas(db, esc.id)
    aplicar(db, esc, elefante_resumo(K, [{"studentId": 9001, "studentName": "ZEFA Q",
                                          "totalBooksRead": 3}]))
    assert fichas(db, esc.id) == antes, "nasceu ficha com nome abreviado"
    assert com_nome(db, esc.id, "ZEFA Q") == []
    [rev] = pendentes(db, esc.id)
    assert rev.motivo == "nome_incompleto" and rev.id_externo == "9001"
    assert rev.linhas and rev.linhas[0]["livros_unicos"] == 3, "o dado ficou guardado na fila"


def test_placar_sem_nome_abrev_tambem_nao_cria(db, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    esc, _, _ = _esc(escola_completa)
    antes = fichas(db, esc.id)
    aplicar(db, esc, matific(K, [{"nome": "ZEFA Q", "uuid": "u-sem-abrev",
                                  "estrelas": 4, "atividades": 2}]))
    assert fichas(db, esc.id) == antes
    assert [r.motivo for r in pendentes(db, esc.id)] == ["nome_incompleto"]


def test_sufixo_de_turma_nao_disfarca_a_abreviacao(db, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    esc, _, _ = _esc(escola_completa)
    antes = fichas(db, esc.id)
    aplicar(db, esc, elefante_resumo(K, [{"studentId": 9002, "studentName": "ZEFA Q 3A",
                                          "totalBooksRead": 1}]))
    assert fichas(db, esc.id) == antes
    assert [r.motivo for r in pendentes(db, esc.id)] == ["nome_incompleto"]


@pytest.mark.parametrize("recebido", ["KAUE 4B", "ZEFA Q 4B", "KAUE 4ºB"])
def test_sufixo_de_outra_sala_tambem_nao_disfarca(db, escola_completa, monkeypatch, recebido):
    """O sufixo de OUTRA sala fica no nome (não é a turma da linha), mas não é
    palavra de nome: "KAUE 4B" na 3ºA continua sendo um nome de uma palavra só."""
    sem_disco(monkeypatch)
    esc, _, _ = _esc(escola_completa)
    antes = fichas(db, esc.id)
    aplicar(db, esc, elefante_resumo(K, [{"studentId": 9004, "studentName": recebido,
                                          "totalBooksRead": 1}]))
    assert fichas(db, esc.id) == antes, "nasceu ficha com nome abreviado"
    assert [r.motivo for r in pendentes(db, esc.id)] == ["nome_incompleto"]


@pytest.mark.parametrize("tipo", ["xlsx", "pdf", "texto"])
@pytest.mark.parametrize("destino", ["turma_escolhida", "turma_pelo_nome"])
def test_upload_manual_planilha_ou_pdf_nao_cria(cliente, db, escola_completa, tipo, destino):
    """O upload passa pela mesma porta: nem a turma pré-escolhida pela tela
    (a prévia já marca "criar" sozinha) faz nascer a ficha abreviada."""
    esc, t, _ = _esc(escola_completa)
    antes = fichas(db, esc.id)
    linha = {"nome": "ZEFA Q", "dados": {"livros_unicos": 2}}
    if destino == "turma_escolhida":
        linha["criar_em_turma_id"] = t.id
    else:
        linha["criar_em_turma_nome"] = K
    r = cliente.post(f"/api/v1/escolas/{esc.id}/importacoes/confirmar",
                     json={"plataforma": "elefante", "formato": "resumo", "tipo": tipo,
                           "linhas": [linha]})
    assert r.status_code == 200, r.text
    assert fichas(db, esc.id) == antes
    assert [p.motivo for p in pendentes(db, esc.id)] == ["nome_incompleto"]


def test_uma_palavra_so_em_planilha_tambem_nao_cria(cliente, db, escola_completa):
    esc, t, _ = _esc(escola_completa)
    antes = fichas(db, esc.id)
    r = cliente.post(f"/api/v1/escolas/{esc.id}/importacoes/confirmar",
                     json={"plataforma": "matific", "formato": "resumo", "tipo": "xlsx",
                           "linhas": [{"nome": "Kauê", "criar_em_turma_id": t.id,
                                       "dados": {"atividades": 3, "estrelas": 9}}]})
    assert r.status_code == 200, r.text
    assert fichas(db, esc.id) == antes


def test_previa_mostra_a_mesma_revisao(db, escola_completa):
    """Prévia = confirmação: a tela já diz que a linha vai para a revisão."""
    esc, _, _ = _esc(escola_completa)
    linhas = [LinhaImportacao(numero=1, nome="ZEFA Q",
                              dados={"livros_unicos": 2, "turma_relatorio": K})]
    casar_nomes(db, esc.id, linhas, plataforma="elefante")
    assert linhas[0].correspondencia["status"] == "revisar"
    assert linhas[0].correspondencia["motivo"] == "nome_incompleto"


def test_associar_por_abreviacao_continua_igual(db, escola_completa, monkeypatch):
    """A trava é só da CRIAÇÃO: com a ficha oficial na sala, "ZEFA Q" é dela."""
    sem_disco(monkeypatch)
    esc, t, _ = _esc(escola_completa)
    oficial = aluno(db, esc.id, t, "Zefa Quaresma Lima", da_lista_piloto=True)
    db.commit()
    antes = fichas(db, esc.id)
    aplicar(db, esc, elefante_resumo(K, [{"studentId": 9003, "studentName": "ZEFA Q",
                                          "totalBooksRead": 4}]))
    assert fichas(db, esc.id) == antes
    assert dono(db, esc.id, "elefante", "9003") == oficial.id
    assert pendentes(db, esc.id) == []


def test_nome_completo_sem_candidato_ainda_cria(db, escola_completa, monkeypatch):
    """A política 'permitir' não mudou para o nome que identifica a criança."""
    sem_disco(monkeypatch)
    esc, _, _ = _esc(escola_completa)
    antes = fichas(db, esc.id)
    aplicar(db, esc, elefante_resumo(K, [{"studentId": 9004, "studentName": "Zefa Quaresma Lima",
                                          "totalBooksRead": 2}]))
    assert fichas(db, esc.id) == antes + 1


def test_quem_decide_na_fila_ainda_pode_criar(cliente, db, escola_completa, monkeypatch):
    """A fila é o lugar da decisão humana: "Criar novo aluno" continua possível."""
    sem_disco(monkeypatch)
    esc, t, _ = _esc(escola_completa)
    aplicar(db, esc, elefante_resumo(K, [{"studentId": 9005, "studentName": "ZEFA Q",
                                          "totalBooksRead": 2}]))
    [rev] = pendentes(db, esc.id)
    antes = fichas(db, esc.id)
    r = cliente.post(f"/api/v1/escolas/{esc.id}/importacoes/revisoes/{rev.id}/resolver",
                     json={"criar_em_turma_id": t.id})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert fichas(db, esc.id) == antes + 1


def test_decidir_direto(db, escola_completa):
    """A regra mora na porta única: CRIAR vira REVISAR nome_incompleto."""
    esc, _, _ = _esc(escola_completa)
    ctx = ida.carregar_contexto(db, esc.id)
    dec = ida.decidir(ctx, ida.LinhaIdentidade(nome="M. EDUARDA", plataforma="elefante",
                                               id_externo="77", turma_nome=K))
    assert (dec.acao, dec.motivo, dec.candidatos) == (ida.REVISAR, "nome_incompleto", ())
    dec = ida.decidir(ctx, ida.LinhaIdentidade(nome="Maria Eduarda Fictoni", plataforma="elefante",
                                               id_externo="78", turma_nome=K))
    assert dec.acao == ida.CRIAR
    assert db.query(Aluno).count() >= 1
