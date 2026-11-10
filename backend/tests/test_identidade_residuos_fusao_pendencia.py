"""Resíduos da auditoria de identidade (A10, A13, A15 e a notificação órfã).

  * A10 — o sufixo de turma digitado junto do nome ("… LIMA 3A") já não decidia
    de quem era a linha; agora também não fica gravado na ficha NOVA;
  * A13 — a pendência aberta por NOME (linha sem conta) fecha quando a mesma
    criança volta COM a conta e é associada — com a mesma guarda do resto e só
    se a pendência não apontava para outra ficha;
  * A15 — candidato já fundido sai da lista da pendência (entra quem ficou);
  * notificação de um aluno absorvido passa para a ficha que ficou.
Dados fictícios.
"""
import pytest
from sqlalchemy import select

from app.models import Notificacao, RevisaoIdentidade
from app.services import alunos_fusao
from app.services import identidade_aluno as ida
from tests.sync_integridade_comum import (aluno, aplicar, com_nome, dono, elefante_resumo,
                                          matific, pendentes, sem_disco)

K = "3 ANO A TARDE ANUAL (300396804)"


def _esc(ec):
    return ec["escola"], ec["turma"], ec["admin"]


# --- A10: a ficha nova nasce sem o sufixo de turma ---------------------------

@pytest.mark.parametrize("recebido, chave, gravado", [
    ("Zefa Quaresma Lima 3A", "3|A", "Zefa Quaresma Lima"),
    ("Zefa Quaresma Lima3A", "3|A", "Zefa Quaresma Lima"),
    ("Zefa Quaresma Lima 3ºA", "3|A", "Zefa Quaresma Lima"),
    ("Zefa  Quaresma  Lima 3A", "3|A", "Zefa Quaresma Lima"),
    ("Zéfa Quaresma Lima 3A", "3|A", "Zéfa Quaresma Lima"),   # grafia de quem digitou
    ("Zefa Quaresma Lima 2", "3|A", "Zefa Quaresma Lima 2"),  # número puro fica
    ("Zefa Quaresma Lima 4B", "3|A", "Zefa Quaresma Lima 4B"),  # outra sala: fica
    ("Zefa Quaresma Lima 3A", "", "Zefa Quaresma Lima 3A"),   # sala ilegível: fica
    ("3A", "3|A", "3A"),                                      # só o sufixo: não esvazia
])
def test_nome_sem_sufixo_preserva_a_grafia_e_segue_a_regra_do_casamento(recebido, chave, gravado):
    assert ida.nome_sem_sufixo_de_turma(recebido, chave) == gravado
    # É a MESMA regra do casamento: só a grafia é a recebida.
    assert ida.chave_nome(gravado) == ida.chave_nome(ida._nome_para_casar(recebido, chave))


def test_sync_cria_a_ficha_sem_o_sufixo(db, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    esc, _, _ = _esc(escola_completa)
    aplicar(db, esc, elefante_resumo(K, [{"studentId": 9102,
                                          "studentName": "Zefa Quaresma Lima 3A",
                                          "totalBooksRead": 3}]))
    assert com_nome(db, esc.id, "Zefa Quaresma Lima 3A") == []
    [criada] = com_nome(db, esc.id, "Zefa Quaresma Lima")
    assert dono(db, esc.id, "elefante", "9102") == criada.id
    # E a coleta seguinte casa com ela (nada de segunda ficha).
    aplicar(db, esc, elefante_resumo(K, [{"studentId": 9102,
                                          "studentName": "Zefa Quaresma Lima 3A",
                                          "totalBooksRead": 4}]))
    assert len(com_nome(db, esc.id, "Zefa Quaresma Lima")) == 1


def test_criar_pela_fila_tambem_tira_o_sufixo(cliente, db, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    esc, t, _ = _esc(escola_completa)
    from app.services import politica_sync
    politica_sync.definir(db, esc.id, "bloquear")
    db.commit()
    aplicar(db, esc, elefante_resumo(K, [{"studentId": 9103,
                                          "studentName": "Zefa Quaresma Lima 3A",
                                          "totalBooksRead": 3}]))
    [rev] = pendentes(db, esc.id)
    assert rev.nome_recebido == "Zefa Quaresma Lima 3A"     # a pendência guarda o recebido
    r = cliente.post(f"/api/v1/escolas/{esc.id}/importacoes/revisoes/{rev.id}/resolver",
                     json={"criar_em_turma_id": t.id})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert len(com_nome(db, esc.id, "Zefa Quaresma Lima")) == 1
    assert com_nome(db, esc.id, "Zefa Quaresma Lima 3A") == []


# --- A13: pendência aberta por nome fecha quando a linha vem com a conta ------

def _pendencia_por_nome(db, esc_id, nome, chave_sala, candidatos=()):
    chave_ident = f"elefante|nome:{ida.chave_nome(nome)}|sala:{chave_sala}"
    rev = RevisaoIdentidade(escola_id=esc_id, chave=ida.chave_pendencia(chave_ident, "resumo"),
                            chave_identidade=chave_ident, plataforma="elefante",
                            formato="resumo", nome_recebido=nome,
                            motivo="correspondencia_insegura", candidatos=list(candidatos),
                            linhas=[{"livros_unicos": 1}], contexto={},
                            origem="importacao", ocorrencias=1, status="pendente")
    db.add(rev)
    db.commit()
    return rev


def test_pendencia_por_nome_fecha_quando_a_conta_chega(db, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    esc, _, _ = _esc(escola_completa)
    ana = escola_completa["alunos"][0]
    rev = _pendencia_por_nome(db, esc.id, ana.nome, "3|A")
    aplicar(db, esc, elefante_resumo(K, [{"studentId": 9201, "studentName": ana.nome,
                                          "totalBooksRead": 3}]))
    assert dono(db, esc.id, "elefante", "9201") == ana.id
    db.refresh(rev)
    assert rev.status == "resolvida" and rev.aluno_escolhido_id == ana.id
    assert rev.resolucao["automatica"] is True     # não vira memória de decisão humana
    assert pendentes(db, esc.id) == []


def test_pendencia_por_nome_que_apontava_outra_ficha_continua(db, escola_completa, monkeypatch):
    """Guarda: se a pendência por nome tinha OUTRO candidato, a conta desta linha
    não responde a pergunta dela — fica para um humano."""
    sem_disco(monkeypatch)
    esc, t, _ = _esc(escola_completa)
    ana = escola_completa["alunos"][0]
    outra = aluno(db, esc.id, t, "Ana Beatriz Souza Fictoni")
    db.commit()
    rev = _pendencia_por_nome(db, esc.id, ana.nome, "3|A",
                              candidatos=[{"aluno_id": ana.id, "nome": ana.nome},
                                          {"aluno_id": outra.id, "nome": outra.nome}])
    aplicar(db, esc, elefante_resumo(K, [{"studentId": 9202, "studentName": ana.nome,
                                          "totalBooksRead": 3}]))
    assert dono(db, esc.id, "elefante", "9202") == ana.id
    db.refresh(rev)
    assert rev.status == "pendente"


def test_pendencia_por_nome_de_outra_sala_nao_e_tocada(db, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    esc, _, _ = _esc(escola_completa)
    ana = escola_completa["alunos"][0]
    rev = _pendencia_por_nome(db, esc.id, ana.nome, "5|B")
    aplicar(db, esc, elefante_resumo(K, [{"studentId": 9203, "studentName": ana.nome,
                                          "totalBooksRead": 3}]))
    db.refresh(rev)
    assert rev.status == "pendente"


# --- A15 e notificação órfã: a fusão atualiza quem aponta para o absorvido ----

def test_candidato_fundido_sai_da_pendencia_e_entra_quem_ficou(cliente, db, escola_completa,
                                                                monkeypatch):
    sem_disco(monkeypatch)
    esc, t, admin = _esc(escola_completa)
    oficial = aluno(db, esc.id, t, "Zefa Quaresma Lima", da_lista_piloto=True)
    stub = aluno(db, esc.id, t, "ZEFA Q")
    db.commit()
    aplicar(db, esc, matific(K, [{"nome": "ZEFA Q", "nome_abrev": "ZEFA Q", "uuid": "u2",
                                  "estrelas": 4, "atividades": 2}]))
    [rev] = pendentes(db, esc.id, "nome_incompleto")
    assert stub.id in [c["aluno_id"] for c in rev.candidatos]
    stub_id, oficial_id = stub.id, oficial.id
    alunos_fusao.fundir_par(db, esc.id, oficial, stub, admin.id)
    db.commit()
    db.expire_all()
    g = cliente.get(f"/api/v1/escolas/{esc.id}/importacoes/revisoes")
    cand = [c["aluno_id"] for c in g.json()[0]["candidatos"]]
    assert stub_id not in cand
    assert cand.count(oficial_id) == 1
    [entrada] = [c for c in g.json()[0]["candidatos"] if c["aluno_id"] == oficial_id]
    assert entrada["nome"] == "Zefa Quaresma Lima"
    r = cliente.post(f"/api/v1/escolas/{esc.id}/importacoes/revisoes/{rev.id}/resolver",
                     json={"aluno_id": oficial_id})
    assert r.status_code == 200, r.text


def test_pendencia_ja_resolvida_nao_e_reescrita(db, escola_completa):
    """O registro de uma decisão tomada não muda: só as PENDENTES são atualizadas."""
    esc, t, admin = _esc(escola_completa)
    oficial = aluno(db, esc.id, t, "Zefa Quaresma Lima", da_lista_piloto=True)
    stub = aluno(db, esc.id, t, "ZEFA Q")
    db.add(RevisaoIdentidade(escola_id=esc.id, chave="x", chave_identidade="x",
                             plataforma="matific", formato="resumo", nome_recebido="ZEFA Q",
                             motivo="nome_incompleto",
                             candidatos=[{"aluno_id": stub.id, "nome": "ZEFA Q"}],
                             linhas=[], contexto={}, origem="importacao",
                             status="descartada"))
    db.commit()
    stub_id = stub.id
    alunos_fusao.fundir_par(db, esc.id, oficial, stub, admin.id)
    db.commit()
    rev = db.execute(select(RevisaoIdentidade)).scalars().one()
    assert [c["aluno_id"] for c in rev.candidatos] == [stub_id]


def test_notificacao_do_absorvido_passa_para_quem_ficou(db, escola_completa):
    esc, t, admin = _esc(escola_completa)
    oficial = aluno(db, esc.id, t, "Zefa Quaresma Lima", da_lista_piloto=True)
    stub = aluno(db, esc.id, t, "ZEFA Q")
    db.add(Notificacao(escopo="escola", escola_id=esc.id, tipo="revisao_identidade",
                       titulo="Aviso ficticio", aluno_id=stub.id))
    db.commit()
    oficial_id = oficial.id
    r = alunos_fusao.fundir_par(db, esc.id, oficial, stub, admin.id)
    db.commit()
    assert r["notificacoes_movidas"] == 1
    n = db.execute(select(Notificacao)).scalars().one()
    assert n.aluno_id == oficial_id
