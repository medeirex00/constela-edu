"""P15: com a política "bloquear", a sincronização do Matific NÃO move a
matrícula — a Lista Piloto é a fonte da verdade.

DE ONDE VEM. Da regra já aceita da política "bloquear": a plataforma não matricula,
a matrícula vem da Lista Piloto (docstring de ``app.services.politica_sync`` e a
tela da política em Sincronizacao.tsx). P15 é a recomendação de 26/10, aplicada
por decorrer dessa regra; o dono pode objetar (reverter = 1 commit).

O DEFEITO. A sync automática do Matific movia a matrícula de uma criança da Lista
Piloto para a turma que o Placar mostrava; o reenvio seguinte da Lista Piloto a
devolvia ("a planilha é a fonte da verdade"), e a coleta seguinte a levava de novo:
a matrícula ia e voltava, e cada ida contava como "1 aluno atualizado" sem nenhum
número novo.

A REGRA. Com "bloquear" a plataforma não matricula: a sync vincula a conta e grava
os números da plataforma, mas a matrícula fica onde a Lista Piloto pôs. A
divergência vira aviso da importação — o mesmo canal do "não casa com nenhuma
turma cadastrada". Com "permitir" (e sem política) nada muda: a sync continua
movendo, como aprovado em 14/07.

Dados 100% fictícios; nenhuma rede.
"""
import io
from datetime import date

import openpyxl
from sqlalchemy import func, select

from app.models import IdentidadeExterna, LogAuditoria, Matricula, Turma
from app.models.plataformas import SnapshotMatific
from app.routers.importacoes import _confirmar_sem_commit, _sincronizar_turma_matific
from app.schemas.importacao import ImportacaoConfirm, LinhaConfirmacao
from app.services import politica_sync
from tests._sync_nucleo_fakes import PlacarFake, credencial, instalar, rodar, snap_atual
from tests.test_lista_piloto import CT_XLSX, _aba

KA = "3 ANO A (300396804)"
KB = "3 ANO B (300396805)"
URL_LISTA = "/api/v1/escolas/{}/importacoes/matriculas/confirmar"


def _turma_de(db, aluno_id):
    return db.execute(select(Matricula.turma_id).where(
        Matricula.aluno_id == aluno_id, Matricula.ano_letivo == 2026)).scalar_one()


def _turma_b(db, eid):
    turma = Turma(escola_id=eid, nome="3º Ano B", ano_escolar="3º Ano", ano_letivo=2026)
    db.add(turma)
    db.flush()
    return turma


def _movidas(db, eid):
    return db.scalar(select(func.count()).select_from(LogAuditoria).where(
        LogAuditoria.escola_id == eid,
        LogAuditoria.acao == "matricula.turma_sincronizada")) or 0


def _lista_3a(nomes) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "3º ANO A"
    linhas = [[i, 4000 + i, f"900.000.0{i:02d}", nome, date(2018, 2, 2), "RESP", "RUA X",
               "BAIRRO", "", "", "", "", "F", "PARDA", "NÃO"]
              for i, nome in enumerate(nomes, start=1)]
    _aba(ws, "3º Ano A", "TARDE", "PROFESSORA FICTICIA", 300000301, linhas)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _cena_placar(db, ec, monkeypatch, politica):
    """Três crianças da Lista Piloto na "3º Ano A", a "3º Ano B" cadastrada e o
    1º encontro do Matific já feito (a conta vinculada pelo nome, sem mover)."""
    eid = ec["escola"].id
    a, b, c = ec["alunos"]
    turma_b = _turma_b(db, eid)
    for al in (a, b, c):
        al.da_lista_piloto = True
    if politica is not None:
        politica_sync.definir(db, eid, politica)
    db.commit()
    credencial(db, eid, "matific")
    placar = PlacarFake()
    placar.linhas = [("u-a", a.nome, KA, 40, 10), ("u-b", b.nome, KA, 30, 8),
                     ("u-c", c.nome, KA, 20, 5)]
    instalar(monkeypatch, placar=placar)
    ex1, erro = rodar(db, eid, "matific")
    assert erro is None and ex1.status == "concluida", (ex1.status, ex1.motivo, erro)
    assert _turma_de(db, a.id) == ec["turma"].id
    return placar, turma_b


# ---------------------------------------------------------------------------
# "bloquear": a sync não move; vincula e grava os números
# ---------------------------------------------------------------------------
def test_bloquear_sync_do_matific_nao_move_a_matricula_da_lista_piloto(
        db, escola_completa, monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    a = ec["alunos"][0]
    placar, turma_b = _cena_placar(db, ec, monkeypatch, "bloquear")

    # O professor deixou a criança na turma B do Matific, e ela fez atividades.
    placar.linhas[0] = ("u-a", a.nome, KB, 44, 12)
    ex2, erro = rodar(db, eid, "matific")

    assert erro is None and ex2.status == "concluida", (ex2.status, ex2.motivo, erro)
    # A matrícula fica onde a Lista Piloto pôs…
    assert _turma_de(db, a.id) == ec["turma"].id != turma_b.id
    assert _movidas(db, eid) == 0
    # …e o dado da plataforma entra mesmo assim, na conta já vinculada.
    snap = snap_atual(db, SnapshotMatific, a.id)
    assert (snap.atividades, snap.estrelas) == (12, 44)
    assert db.execute(select(IdentidadeExterna.aluno_id).where(
        IdentidadeExterna.escola_id == eid, IdentidadeExterna.plataforma == "matific",
        IdentidadeExterna.id_externo == "u-a")).scalar_one() == a.id
    assert ex2.qtd_alunos == 1          # a criança com número novo, não a "mudança"


def test_bloquear_lista_piloto_e_matific_nao_alternam_a_matricula(
        db, cliente, escola_completa, monkeypatch):
    """Vai-e-volta da revisão independente (p3b): antes, cada coleta do Matific
    levava a criança à turma B ("concluida", 1 aluno atualizado sem número novo) e
    cada reenvio da Lista Piloto a devolvia à A: B, A, B, A."""
    ec = escola_completa
    eid = ec["escola"].id
    a, b, c = ec["alunos"]
    turma_b = _turma_b(db, eid)
    db.commit()
    lista = _lista_3a([a.nome, b.nome, c.nome])
    r = cliente.post(URL_LISTA.format(eid), files={"arquivo": ("L.xlsx", lista, CT_XLSX)})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert _turma_de(db, a.id) == ec["turma"].id
    politica_sync.definir(db, eid, "bloquear")
    db.commit()
    credencial(db, eid, "matific")
    placar = PlacarFake()
    placar.linhas = [("u-a", a.nome, KA, 40, 10), ("u-b", b.nome, KA, 30, 8),
                     ("u-c", c.nome, KA, 20, 5)]
    instalar(monkeypatch, placar=placar)
    assert rodar(db, eid, "matific")[0].status == "concluida"
    placar.linhas[0] = ("u-a", a.nome, KB, 40, 10)     # só a turma muda no Matific

    historico = []
    for _ in range(2):
        ex, erro = rodar(db, eid, "matific")
        historico.append(("matific", ex.status, ex.motivo, ex.qtd_alunos, erro,
                          "B" if _turma_de(db, a.id) == turma_b.id else "A"))
        r = cliente.post(URL_LISTA.format(eid), files={"arquivo": ("L.xlsx", lista, CT_XLSX)})
        assert r.status_code == 200, r.text
        db.expire_all()
        historico.append(("lista", "B" if _turma_de(db, a.id) == turma_b.id else "A"))

    assert [h[-1] for h in historico] == ["A", "A", "A", "A"], historico
    # Nenhum número novo e nenhuma mudança: a coleta é "nada mudou" (legítima, conta
    # como verificação), sem ninguém atualizado — antes era "concluida" com 1.
    assert [h[1:5] for h in historico if h[0] == "matific"] == [
        ("sem_atualizacao", "nada_mudou", 0, None)] * 2, historico
    assert _movidas(db, eid) == 0


def test_bloquear_a_divergencia_vira_aviso_e_nao_conta_como_dado_alterado(
        relogio_no_ano_letivo, db, escola_completa):
    """No núcleo do /confirmar (a mesma chamada da sync): a turma divergente do
    Matific vira AVISO, a matrícula não muda e a criança não entra nos
    "aplicados" (sem número novo, a coleta não recalcula ninguém por ela)."""
    ec = escola_completa
    eid = ec["escola"].id
    a = ec["alunos"][0]
    turma_b = _turma_b(db, eid)
    db.add(IdentidadeExterna(escola_id=eid, aluno_id=a.id, plataforma="matific",
                             id_externo="u-a"))
    politica_sync.definir(db, eid, "bloquear")
    db.commit()

    def _coleta(turma_relatorio):
        corpo = ImportacaoConfirm(
            plataforma="matific", formato="resumo", tipo="texto", recalcular=False,
            sincronizar_turma=True, permitir_criar_turma=False, permitir_criar_aluno=False,
            linhas=[LinhaConfirmacao(nome=a.nome, dados={
                "matific_uuid": "u-a", "turma_relatorio": turma_relatorio,
                "atividades": 10, "estrelas": 40})])
        res = _confirmar_sem_commit(dados=corpo, escola_id=eid, usuario=ec["admin"], db=db)
        db.commit()
        return res

    assert _coleta(KA).alunos_aplicados_ids == [a.id]   # 1º retrato: número novo
    res = _coleta(KB)                                    # mesmos números, outra turma

    assert _turma_de(db, a.id) == ec["turma"].id != turma_b.id
    assert res.alunos_aplicados_ids == []
    assert _movidas(db, eid) == 0
    avisos = [x for x in res.avisos if "Lista Piloto" in x]
    assert len(avisos) == 1, res.avisos
    assert turma_b.nome in avisos[0] and a.nome in avisos[0]
    assert not any("movido de" in x for x in res.avisos), res.avisos


def test_bloquear_turma_que_nao_casa_mantem_o_aviso_de_sempre(db, escola_completa):
    """Fora da regra nova, nada muda com "bloquear": turma do Matific que não casa
    com nenhuma cadastrada continua só com o aviso de revisão manual."""
    ec = escola_completa
    eid = ec["escola"].id
    a = ec["alunos"][0]
    db.add(IdentidadeExterna(escola_id=eid, aluno_id=a.id, plataforma="matific",
                             id_externo="u-a"))
    politica_sync.definir(db, eid, "bloquear")
    db.commit()
    linha = LinhaConfirmacao(nome=a.nome, aluno_id=a.id, via="identidade",
                             dados={"matific_uuid": "u-a", "turma_relatorio": "9 ANO Z NOTURNO",
                                    "atividades": 2, "estrelas": 10})
    avisos: list[str] = []
    assert _sincronizar_turma_matific(db, eid, 2026, {a.id: (a, [linha])}, avisos) == 0
    assert _turma_de(db, a.id) == ec["turma"].id
    assert len(avisos) == 1 and "não casa com nenhuma turma cadastrada" in avisos[0]


def test_bloquear_chamada_direta_tambem_nao_move(db, escola_completa):
    """A trava mora na própria rotina que move (não só no chamador): qualquer
    caminho que a chame numa escola "bloquear" fica sem mover."""
    ec = escola_completa
    eid = ec["escola"].id
    a = ec["alunos"][0]
    turma_b = _turma_b(db, eid)
    db.add(IdentidadeExterna(escola_id=eid, aluno_id=a.id, plataforma="matific",
                             id_externo="u-a"))
    politica_sync.definir(db, eid, "bloquear")
    db.commit()
    linha = LinhaConfirmacao(nome=a.nome, aluno_id=a.id, via="identidade",
                             dados={"matific_uuid": "u-a", "turma_relatorio": KB,
                                    "atividades": 2, "estrelas": 10})
    avisos: list[str] = []
    movidos_ids: list[int] = []
    n = _sincronizar_turma_matific(db, eid, 2026, {a.id: (a, [linha])}, avisos,
                                   movidos_ids=movidos_ids)
    assert (n, movidos_ids) == (0, [])
    assert _turma_de(db, a.id) == ec["turma"].id != turma_b.id
    assert len(avisos) == 1 and "Lista Piloto" in avisos[0]


# ---------------------------------------------------------------------------
# "permitir": comportamento aprovado em 14/07, idêntico
# ---------------------------------------------------------------------------
def test_permitir_a_sync_do_matific_continua_movendo(
        relogio_no_ano_letivo, db, escola_completa, monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    a = ec["alunos"][0]
    placar, turma_b = _cena_placar(db, ec, monkeypatch, "permitir")

    placar.linhas[0] = ("u-a", a.nome, KB, 40, 10)
    ex2, erro = rodar(db, eid, "matific")

    assert erro is None and ex2.status == "concluida", (ex2.status, ex2.motivo, erro)
    assert _turma_de(db, a.id) == turma_b.id
    assert _movidas(db, eid) == 1
    assert ex2.qtd_alunos == 1          # a matrícula movida conta como dado alterado


def test_sem_politica_a_sync_do_matific_continua_movendo(
        relogio_no_ano_letivo, db, escola_completa, monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    a = ec["alunos"][0]
    placar, turma_b = _cena_placar(db, ec, monkeypatch, None)

    placar.linhas[0] = ("u-a", a.nome, KB, 40, 10)
    ex2, erro = rodar(db, eid, "matific")

    assert erro is None and ex2.status == "concluida", (ex2.status, ex2.motivo, erro)
    assert _turma_de(db, a.id) == turma_b.id
    assert _movidas(db, eid) == 1
