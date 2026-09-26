"""A fusão manual ganha a mesma rede que a fusão em lote já tinha.

``POST /alunos/fundir`` apaga uma ficha, mas não consultava conflito de
identidade nenhum — enquanto a fusão em LOTE recomputa os candidatos no servidor
e barra pares com prova de serem crianças diferentes. Pior: a tela mostra só
nome e turma, então quem digitava "FUNDIR" não via nascimento nem RA, que são
justamente os sinais do veto.

Não virou bloqueio. O repositório NÃO decide se esse veto é estrutural ou
heurística de sugestão — o docstring de ``_conflito_forte`` limita o escopo a
sugerir, mas ``_colapsavel`` o reaplica depois da confirmação humana. Diante da
ambiguidade, e porque fundir é ato humano (o gestor pode saber de algo que o
dado não conta), a proteção é uma SEGUNDA confirmação que nomeia a divergência
— o mesmo padrão que o repositório já usa para operações irreversíveis.

O juiz é ``matching.conflito_identidade``, a função que decide isso em toda
importação e sincronização: assim o RA passa pela normalização canônica e a
decisão sobre nº de chamada (renumeração de sala não é outra criança) é
herdada, não reinventada.
"""
from datetime import date

from sqlalchemy import select

from app.models import Aluno, Matricula, Turma
from app.services.alunos_dedup import _conflito_forte, plano_deduplicacao
from app.services.identidade_aluno import ra_forte

CONFIRMA_CONFLITO = "FUNDIR MESMO COM CONFLITO"


def _fundir(cliente, escola_id, manter, remover, **extra):
    return cliente.post(f"/api/v1/escolas/{escola_id}/alunos/fundir",
                        json={"manter_id": manter, "remover_id": remover,
                              "confirmacao": "FUNDIR", **extra})


def _existe(db, aluno_id) -> bool:
    """Consulta FRESCA: depois da fusão o objeto na sessão está morto, e
    ``db.get`` levantaria ObjectDeletedError em vez de devolver None."""
    db.expunge_all()
    return db.execute(select(Aluno.id).where(Aluno.id == aluno_id)).scalar_one_or_none() is not None


# ---------------------------------------------------------------------------
# 9–11. A PORTA DESTRUTIVA GANHA A MESMA REDE DA AUTOMÁTICA
# ---------------------------------------------------------------------------

def _dois_alunos(db, escola_id, *, nasc_a, nasc_b, ra_a=None, ra_b=None):
    turma = db.execute(select(Turma).where(Turma.escola_id == escola_id)).scalars().first()
    criados = []
    for i, (nasc, ra) in enumerate([(nasc_a, ra_a), (nasc_b, ra_b)]):
        a = Aluno(escola_id=escola_id, nome="RAFAEL BORGES CRUZ", status="ativo",
                  ficha={"ra": ra} if ra else {})
        a.data_nascimento = nasc
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=escola_id, aluno_id=a.id, turma_id=turma.id,
                         ano_letivo=turma.ano_letivo))
        criados.append(a)
    db.commit()
    return criados


def test_9_fusao_com_conflito_de_identidade_exige_confirmacao_especifica(
        cliente, db, escola_completa):
    """Não bloqueia — fundir é ato humano —, mas obriga a LER a divergência."""
    escola_id = escola_completa["escola"].id
    a, b = _dois_alunos(db, escola_id, nasc_a=date(2020, 7, 31), nasc_b=date(2021, 7, 31))
    aid, bid = a.id, b.id

    r = _fundir(cliente, escola_id, aid, bid)
    assert r.status_code == 409, r.text
    assert "2020-07-31" in r.text and "2021-07-31" in r.text
    assert CONFIRMA_CONFLITO in r.text
    assert _existe(db, bid), "nada pode ser apagado na recusa"

    r = _fundir(cliente, escola_id, aid, bid, confirmar_conflito=CONFIRMA_CONFLITO)
    assert r.status_code == 200, r.text
    assert not _existe(db, bid)


def test_9b_a_decisao_de_passar_por_cima_fica_auditada(cliente, db, escola_completa):
    from app.models import LogAuditoria
    escola_id = escola_completa["escola"].id
    a, b = _dois_alunos(db, escola_id, nasc_a=date(2020, 7, 31), nasc_b=date(2021, 7, 31))
    assert _fundir(cliente, escola_id, a.id, b.id,
                   confirmar_conflito=CONFIRMA_CONFLITO).status_code == 200

    db.expire_all()
    logs = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "aluno.fundido_com_conflito")).scalars().all()
    assert len(logs) == 1
    assert any("nascimento" in d for d in logs[0].detalhes["divergencias"])


def test_10_fusao_legitima_continua_passando_direto(cliente, db, escola_completa):
    """Sem prova de conflito, nada muda: um só 'FUNDIR' basta, como sempre."""
    escola_id = escola_completa["escola"].id
    a, b = _dois_alunos(db, escola_id, nasc_a=date(2020, 7, 31), nasc_b=date(2020, 7, 31))
    aid, bid = a.id, b.id
    r = _fundir(cliente, escola_id, aid, bid)
    assert r.status_code == 200, r.text
    assert not _existe(db, bid)


def test_10b_ra_so_com_pontuacao_diferente_nao_atrapalha_a_fusao(
        cliente, db, escola_completa):
    """Antes da correção este par era 'prova de crianças diferentes'."""
    escola_id = escola_completa["escola"].id
    a, b = _dois_alunos(db, escola_id, nasc_a=date(2020, 7, 31), nasc_b=date(2020, 7, 31),
                        ra_a="123.269.537-3", ra_b="1232695373")
    assert _fundir(cliente, escola_id, a.id, b.id).status_code == 200


def test_11_detector_e_rota_manual_concordam(cliente, db, escola_completa):
    """A mesma pergunta — 'há prova de serem crianças diferentes?' — tem de ter
    a mesma resposta nas duas portas."""
    escola_id = escola_completa["escola"].id
    a, b = _dois_alunos(db, escola_id, nasc_a=date(2020, 7, 31), nasc_b=date(2021, 7, 31))

    # detector: não sugere o par
    pares = plano_deduplicacao(db, escola_id)
    envolvidos = {i for c in pares for i in (c.get("manter_id"), c.get("remover_id"))}
    assert a.id not in envolvidos and b.id not in envolvidos

    # rota manual: recusa sem a confirmação específica
    assert _fundir(cliente, escola_id, a.id, b.id).status_code == 409


# ---------------------------------------------------------------------------
# 12. O CASO ALICE CONTINUA EXATAMENTE COMO ESTÁ
# ---------------------------------------------------------------------------

def test_12_alice_continua_com_duas_fichas_distintas(cliente, db, escola_completa):
    """Reprodução fiel das fichas 2285 e 2297 de produção. Nenhuma correção
    desta tarefa pode fundi-las, apagá-las ou alterar nascimento."""
    escola_id = escola_completa["escola"].id
    turma = db.execute(select(Turma).where(Turma.escola_id == escola_id)).scalars().first()
    fichas = []
    for nome, ra, nasc, status in [
            ("Alice Vitoria Fossenati de Jesus", "123269537", date(2021, 7, 31),
             "fora_lista_piloto"),
            ("ALICE VITORIA FOSSENATI DE JESUS", "123.269.537-3", date(2020, 7, 31),
             "ativo")]:
        a = Aluno(escola_id=escola_id, nome=nome, status=status, numero_chamada=2,
                  ficha={"ra": ra}, da_lista_piloto=True)
        a.data_nascimento = nasc
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=escola_id, aluno_id=a.id, turma_id=turma.id,
                         ano_letivo=turma.ano_letivo))
        fichas.append(a)
    db.commit()
    f2285, f2297 = fichas

    # (a) o RA continua provando conflito — 9 dígitos ≠ 10 dígitos
    assert ra_forte("123269537") != ra_forte("123.269.537-3")
    assert _conflito_forte(f2285, f2297) is True

    # (b) o detector não oferece o par
    pares = plano_deduplicacao(db, escola_id)
    envolvidos = {i for c in pares for i in (c.get("manter_id"), c.get("remover_id"))}
    assert f2285.id not in envolvidos and f2297.id not in envolvidos

    # (c) a porta manual recusa: primeiro pelo status, e — se estivesse ativa —
    #     pela confirmação específica do conflito
    assert _fundir(cliente, escola_id, f2297.id, f2285.id).status_code == 400
    f2285.status = "ativo"
    db.commit()
    assert _fundir(cliente, escola_id, f2297.id, f2285.id).status_code == 409

    # (d) nada foi apagado nem alterado
    db.expire_all()
    assert db.get(Aluno, f2285.id) is not None
    assert db.get(Aluno, f2297.id) is not None
    assert db.get(Aluno, f2285.id).data_nascimento == date(2021, 7, 31)
    assert db.get(Aluno, f2297.id).data_nascimento == date(2020, 7, 31)
    assert (db.get(Aluno, f2285.id).ficha or {}).get("ra") == "123269537"
    assert (db.get(Aluno, f2297.id).ficha or {}).get("ra") == "123.269.537-3"
