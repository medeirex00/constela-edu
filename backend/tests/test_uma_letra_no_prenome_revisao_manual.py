"""Uma letra diferente no 2º PRENOME fica na revisão MANUAL — por nenhum caminho
automático ela se resolve sozinha (decisão 3 do dono, aprovada em 2026-10-12).

O caso relatado na escola 1: a plataforma manda o 2º prenome com UMA letra a
menos, a ficha oficial tem o nome certo, e é o único candidato da sala. É
provável que seja a mesma criança — mas a mesma regra ligaria MARIA ALINE à ficha
da MARIA ALICE (irmãs e gêmeas se distinguem pelo PRENOME), e o cadastro não tem
lista de prenomes confiável para separar os dois casos. A regra vigente
(``identidade_aluno._grafia_segura``) manda esse caso para a revisão; o dono
decidiu MANTER assim. Um clique do gestor no /resolver resolve, e a conta passa a
ligar sozinha nas próximas sincronizações.

O que o matcher decide já está coberto noutros arquivos (ver o mapa, ao fim).
Aqui ficam os caminhos AUTOMÁTICOS que poderiam fechar o caso sem gente:

  1. a SINCRONIZAÇÃO real (orquestrador) — inclusive com a ficha oficial ao lado
     do stub abreviado do Matific, onde o desempate "oficial × duplicata" poderia
     escolher a oficial sozinho;
  2. o ENCERRAMENTO AUTOMÁTICO de revisões respondidas
     (``importacoes._encerrar_revisoes_respondidas``) — nem a mesma linha de novo,
     nem os livros da mesma conta, nem a sincronização da OUTRA plataforma da
     ficha, nem a listagem da fila (que calcula a triagem) fecham a pendência;
  3. FUSÃO — com DUAS fichas (a oficial e a de uma letra a menos), nenhuma
     sincronização funde nada, e a detecção de duplicatas só as sugere na faixa
     "revisar" (nunca pré-marcada).

Nomes FICTÍCIOS: reproduzem o PADRÃO do caso (uma letra a menos no 2º prenome,
1º nome e sobrenomes idênticos) sem usar o nome da criança.
"""
from sqlalchemy import func, select

from app.models import Aluno, IdentidadeExterna, Leitura, SnapshotMatific
from app.services import alunos_dedup
from app.services import identidade_aluno as ida
from app.services import matching
from tests.test_revisao_encerramento_automatico import (  # noqa: F401 — fixtures reutilizadas
    ACAO_AUTO,
    ACAO_HUMANA,
    SALA,
    _aluno,
    _confirmar,
    _conta,
    _logs,
    _matific,
    _n_alunos,
    _n_snapshots,
    _pendentes,
    _revisoes,
    _sincronizar_elefante,
    _sincronizar_leituras,
    sala,
)

FICHA = "CAIO FERNANDO LACERDA BORGES"       # a ficha oficial (Lista Piloto)
RECEBIDO = "CAIO FERNADO LACERDA BORGES"     # o 2º prenome com UMA letra a menos
SID = 4410777                                # studentId do Elefante (fictício)
CONTA_MATIFIC = "u-caio-oficial"             # a conta Matific que a ficha já tem
VINCULO_AUTO = "aluno.vinculado_auto"
FUSAO = "aluno.fundido"


def _contas_elefante(db, escola):
    return db.execute(select(IdentidadeExterna.aluno_id).where(
        IdentidadeExterna.escola_id == escola.id,
        IdentidadeExterna.plataforma == "elefante",
        IdentidadeExterna.id_externo == str(SID))).scalars().all()


def _n_leituras(db, aluno_id):
    return db.execute(select(func.count()).select_from(Leitura)
                      .where(Leitura.aluno_id == aluno_id)).scalar_one()


def _n_snapshots_matific(db, aluno_id):
    return db.execute(select(func.count()).select_from(SnapshotMatific)
                      .where(SnapshotMatific.aluno_id == aluno_id)).scalar_one()


def test_o_par_e_o_que_a_regra_antiga_ligaria():
    """Pré-condição dos testes abaixo: o critério de nome do motor (o mesmo da
    Lista Piloto) AINDA aceitaria este par — 1º nome e último sobrenome
    idênticos, diferença num nome do meio. Quem segura é a trava do prenome; se
    o par deixasse de ser "parecido", os testes daqui não provariam nada."""
    assert matching.plausivel(RECEBIDO, FICHA) == "fraco"
    assert matching.vincula_por_nome_unico(RECEBIDO, FICHA)


# --- 1. a sincronização real deixa o caso na revisão ---------------------------------

def test_sincronizacao_do_elefante_deixa_o_caso_na_revisao_sem_tocar_a_ficha(
        db, sala, monkeypatch):
    esc = sala["escola"]
    oficial = _aluno(db, esc, sala["b"], FICHA)
    _conta(db, esc, oficial, "matific", CONTA_MATIFIC)
    _aluno(db, esc, sala["b"], "PRISCILA NUNES TAVARES")     # colega sem relação
    db.commit()
    antes = _n_alunos(db, esc)

    _sincronizar_elefante(db, esc, monkeypatch, [(SID, RECEBIDO)])

    [rev] = _pendentes(db, esc)
    assert (rev.plataforma, rev.id_externo, rev.motivo) == (
        "elefante", str(SID), "correspondencia_insegura")
    assert [c["aluno_id"] for c in rev.candidatos] == [oficial.id]   # só sugestão
    assert rev.aluno_escolhido_id is None
    # Nada foi aplicado à ficha e nenhuma ficha nova apareceu.
    assert _contas_elefante(db, esc) == []
    assert _n_snapshots(db, oficial.id) == 0
    assert _n_alunos(db, esc) == antes
    assert _logs(db, VINCULO_AUTO) == [] and _logs(db, ACAO_AUTO) == []


def test_oficial_e_stub_abreviado_nao_desempatam_o_caso(db, sala, monkeypatch):
    """O padrão da escola 1 com o stub ao lado: a ficha OFICIAL e a abreviada que
    a sincronização do Matific criou ("CAIO F", com a conta Matific dela). O
    desempate "oficial × duplicata" escolheria a oficial — o stub é sombra dela
    e a linha casaria com ela sozinha pelo critério do motor. A trava do prenome
    vale também ali: revisão com as duas fichas, ninguém preterido."""
    esc = sala["escola"]
    oficial = _aluno(db, esc, sala["b"], FICHA)
    stub = _aluno(db, esc, sala["b"], "CAIO F", lp=False)
    _conta(db, esc, stub, "matific", "u-stub-caio")
    db.commit()
    assert matching.plausivel(stub.nome, oficial.nome) == "forte"   # é sombra dela

    ctx = ida.carregar_contexto(db, esc.id)
    d = ida.decidir(ctx, ida.linha_de_dados(
        RECEBIDO, {"elefante_student_id": str(SID)}, plataforma="elefante",
        turma_nome=SALA))
    assert (d.acao, d.motivo) == (ida.REVISAR, "candidatos_multiplos")
    assert set(d.candidatos) == {oficial.id, stub.id}
    assert d.preteridos == ()

    antes = _n_alunos(db, esc)
    _sincronizar_elefante(db, esc, monkeypatch, [(SID, RECEBIDO)])
    [rev] = _pendentes(db, esc)
    assert rev.motivo == "candidatos_multiplos"
    assert {c["aluno_id"] for c in rev.candidatos} == {oficial.id, stub.id}
    assert _contas_elefante(db, esc) == []
    assert _n_snapshots(db, oficial.id) == 0 and _n_snapshots(db, stub.id) == 0
    assert _n_alunos(db, esc) == antes
    db.expire_all()
    assert db.get(Aluno, stub.id).status == "ativo"           # nada fundido
    assert _logs(db, VINCULO_AUTO) == [] and _logs(db, FUSAO) == []


# --- 2. o encerramento automático não fecha a pendência ------------------------------

def test_pendencia_do_caso_sobrevive_as_sincronizacoes_seguintes(
        db, sala, monkeypatch, cliente):
    """O encerramento automático só fecha a pendência quando uma linha da MESMA
    conta é ASSOCIADA. Nada do dia a dia da escola faz isso aqui: a mesma linha
    volta (revisão de novo), os livros da mesma conta chegam (revisão também), a
    ficha recebe o Matific pela conta dela (é OUTRA conta, outra pendência) e a
    fila é listada com a triagem (só leitura)."""
    esc, admin = sala["escola"], sala["admin"]
    oficial = _aluno(db, esc, sala["b"], FICHA)
    _conta(db, esc, oficial, "matific", CONTA_MATIFIC)
    db.commit()

    _sincronizar_elefante(db, esc, monkeypatch, [(SID, RECEBIDO)])
    _sincronizar_leituras(db, esc, monkeypatch, [
        (SID, RECEBIDO, "O barco", "2025-09-01T10:00:00")])
    resumo, leituras = sorted(_pendentes(db, esc), key=lambda r: r.formato != "resumo")
    assert (resumo.formato, leituras.formato) == ("resumo", "leituras")
    assert resumo.chave_identidade == leituras.chave_identidade

    for _ in range(2):                                 # as coletas dos dias seguintes
        _sincronizar_elefante(db, esc, monkeypatch, [(SID, RECEBIDO)])
        _sincronizar_leituras(db, esc, monkeypatch, [
            (SID, RECEBIDO, "O barco", "2025-09-01T10:00:00")])
    # A sincronização do Matific da MESMA ficha, pela conta dela.
    _confirmar(db, esc, admin, "matific", [_matific("CAIO F", CONTA_MATIFIC)])
    assert _n_snapshots_matific(db, oficial.id) == 1          # a do Matific aplicou

    # A fila com a triagem calculada (o que a tela de revisão chama).
    resp = cliente.get(f"/api/v1/escolas/{esc.id}/importacoes/revisoes")
    assert resp.status_code == 200, resp.text
    assert {r["id"] for r in resp.json()} == {resumo.id, leituras.id}

    revs = _revisoes(db, esc)
    assert [r.id for r in revs] == sorted([resumo.id, leituras.id])   # nada novo
    for r in revs:
        assert r.status == "pendente"
        assert r.ocorrencias == 3                      # a MESMA pendência, atualizada
        assert (r.aluno_escolhido_id, r.resolvida_em, r.resolvida_por_id,
                r.resolucao) == (None, None, None, None)
    assert _logs(db, ACAO_AUTO) == [] and _logs(db, ACAO_HUMANA) == []
    assert resumo.chave_identidade not in ida.carregar_contexto(db, esc.id).resolvidas
    # Os dados do Elefante continuam só na pendência.
    assert _contas_elefante(db, esc) == []
    assert _n_snapshots(db, oficial.id) == 0 and _n_leituras(db, oficial.id) == 0


# --- 3. duas fichas: nenhuma fusão automática ----------------------------------------

def test_duas_fichas_do_caso_nunca_sao_fundidas_por_sincronizacao(db, sala, monkeypatch):
    """A outra forma do mesmo caso: DUAS fichas na sala — a oficial e a de uma
    letra a menos, que uma sincronização antiga criou com a conta do Elefante.
    As sincronizações seguem cada uma pela sua conta e não juntam nada; a
    detecção de duplicatas só SUGERE o par, na faixa "revisar" (nunca
    pré-marcada nem de lote), e a fusão continua sendo do gestor."""
    esc, admin = sala["escola"], sala["admin"]
    oficial = _aluno(db, esc, sala["b"], FICHA)
    _conta(db, esc, oficial, "matific", CONTA_MATIFIC)
    copia = _aluno(db, esc, sala["b"], RECEBIDO, lp=False)
    _conta(db, esc, copia, "elefante", str(SID))
    db.commit()
    antes = _n_alunos(db, esc)

    for _ in range(2):
        _sincronizar_elefante(db, esc, monkeypatch, [(SID, RECEBIDO)])
        _confirmar(db, esc, admin, "matific", [_matific("CAIO F", CONTA_MATIFIC)])

    db.expire_all()
    assert _n_alunos(db, esc) == antes
    assert db.get(Aluno, oficial.id).status == "ativo"
    assert db.get(Aluno, copia.id).status == "ativo"
    assert _logs(db, FUSAO) == []
    # Cada conta continua na ficha dela; nada migra sozinho para a oficial.
    assert _contas_elefante(db, esc) == [copia.id]
    assert _n_snapshots(db, oficial.id) == 0
    assert _pendentes(db, esc) == []

    par = [p for p in alunos_dedup.plano_deduplicacao(db, esc.id)
           if {p["loser_id"], p["manter_id"]} == {oficial.id, copia.id}]
    assert len(par) == 1
    assert (par[0]["loser_id"], par[0]["manter_id"]) == (copia.id, oficial.id)
    assert (par[0]["confianca"], par[0]["motivo"]) == ("revisar", "variante")


# --- mapa: onde o matcher já está coberto ---------------------------------------------

def test_mapa_da_decisao_nos_outros_arquivos():
    """Os testes que provam a DECISÃO do matcher para este padrão (para quem
    revisa a cobertura — e para que nenhum suma sem este arquivo perceber)."""
    import tests.test_alunos_dedup as dedup
    import tests.test_identidade_automatica as auto
    import tests.test_identidade_casos_obrigatorios as obrig
    import tests.test_identidade_revisao as revisao
    import tests.test_revisao_encerramento_automatico as enc
    mapa = {
        obrig: ("test_caso_matias_uma_letra_no_segundo_prenome_fica_para_gente",),
        revisao: ("test_uma_letra_no_segundo_prenome_continua_em_revisao",),
        auto: ("test_uma_letra_no_prenome_vai_para_revisao_sem_depender_do_cadastro",
               "test_iii_uma_letra_no_prenome_e_outro_nome_vai_para_revisao"),
        enc: ("test_decisao_revisar_mantem_a_pendencia",),
        dedup: ("test_detecta_variante_em_turmas_fantasma_da_mesma_sala",),
    }
    for modulo, nomes in mapa.items():
        for nome in nomes:
            assert hasattr(modulo, nome), f"{modulo.__name__}.{nome}"
