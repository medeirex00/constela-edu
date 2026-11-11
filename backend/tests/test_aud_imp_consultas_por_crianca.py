"""A importação não faz idas ao banco extras POR CRIANÇA.

Em produção cada ida ao banco custa ~0,2 s (a API e o banco ficam em regiões
diferentes): o que se repete por criança vira minutos com a trava da escola presa, na
Lista Piloto, no upload de relatório e na sincronização diária (que usa o mesmo
/confirmar).

* ``_vincular_identidade`` consultava ``identidades_externas`` em TODA linha, embora o
  contexto da importação (lido sob a trava da escola) já tenha todos os vínculos; e
  cada vínculo novo pagava SAVEPOINT + INSERT + RELEASE.
* ``_persistir_linhas`` (Lista Piloto) fazia ``flush()`` completo a cada ficha nova
  para obter o id: a matrícula e o log de auditoria da linha anterior saíam junto, um
  INSERT de cada por criança, sem agrupamento.

A sessão aqui é a de produção (``autoflush=False``, como ``SessionLocal``). O
recálculo de notas (``scoring.recalcular_escola``) é de outro módulo e fica de fora
das contas. Dados fictícios.
"""
import collections
import io
import re
from datetime import date

import openpyxl
import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import sessionmaker

from app.core.database import get_db
from app.main import app
from app.models import Aluno, IdentidadeExterna, Matricula
from app.services import identidade_aluno as ida

API = "/api/v1"
CT_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.fixture()
def sessao_de_producao(db):
    """As requisições usam uma sessão como a ``SessionLocal`` (sem autoflush)."""
    fabrica = sessionmaker(bind=db.get_bind(), autoflush=False, autocommit=False)

    def _get_db():
        sessao = fabrica()
        try:
            yield sessao
        finally:
            sessao.close()

    anterior = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = _get_db
    yield
    app.dependency_overrides[get_db] = anterior


class Consultas:
    """Conta os comandos SQL por modelo (tabela + verbo)."""

    def __init__(self, engine):
        self.engine, self.comandos = engine, []

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._antes)
        return self

    def __exit__(self, *exc):
        event.remove(self.engine, "before_cursor_execute", self._antes)

    def _antes(self, _conn, _cursor, comando, *_a):
        self.comandos.append(" ".join(comando.split()))

    def contar(self, padrao: str) -> int:
        return sum(1 for c in self.comandos if re.search(padrao, c, re.I))

    def _posicoes(self, padrao: str) -> list[int]:
        return [i for i, c in enumerate(self.comandos) if re.search(padrao, c, re.I)]

    def primeira(self, padrao: str) -> int:
        return min(self._posicoes(padrao))

    def ultima(self, padrao: str) -> int:
        return max(self._posicoes(padrao))

    def resumo(self) -> str:
        modelos = collections.Counter(re.sub(r"\b\d+\b", "N", c)[:90] for c in self.comandos)
        return f"{len(self.comandos)} comandos; " + "; ".join(
            f"{n}x {m}" for m, n in modelos.most_common(6))


def _lista_piloto(n_turmas: int, por_turma: int) -> bytes:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for t in range(n_turmas):
        nome = f"{1 + t % 5}º Ano {'HIJKLMNOPQ'[t // 5]}"
        ws = wb.create_sheet(nome)
        ws.append([None, None, None, "PREFEITURA MUNICIPAL FICTICIA"])
        ws.append(["Escola:", None, "EMEF FICTICIA", None, None, None, None,
                   "Lista Piloto:", 2026])
        ws.append([])
        ws.append(["Professor:", None, f"PROFESSORA FICTICIA {t}", None, "Ano:", nome,
                   "Turno:       TARDE", None, "N.º da Classe (SED):", 300390000 + t])
        ws.append([])
        ws.append(["N.º", "RM", "RA", "Nome", "Data de Nasc."])
        for k in range(por_turma):
            ws.append([k + 1, 1000 * t + k, f"{900000000 + 1000 * t + k}-0",
                       f"ALUNO FICTICIO T{t:02d} N{k:02d} DE TESTE", date(2018, 1, 1)])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_lista_piloto_agrupa_matriculas_e_auditoria_das_fichas_novas(
        db, cliente, escola_completa, sessao_de_producao):
    escola_id = escola_completa["escola"].id
    with Consultas(db.get_bind()) as c:
        r = cliente.post(f"{API}/escolas/{escola_id}/importacoes/matriculas/confirmar",
                         files={"arquivo": ("Lista.xlsx", _lista_piloto(2, 30), CT_XLSX)})
    assert r.status_code == 200, r.text[:300]
    assert r.json()["alunos_criados"] == 60
    # Uma ida por ficha nova (o id dela entra no índice do motor para as linhas
    # seguintes); as matrículas e os logs saem JUNTOS, num flush só depois das
    # fichas — não um de cada por criança, intercalados com elas. No PostgreSQL esse
    # flush vira poucos INSERT de várias linhas; o SQLite manda uma por linha (sem
    # RETURNING em lote), por isso aqui a prova é a ordem.
    assert c.contar(r"^INSERT INTO alunos\b") == 60, c.resumo()
    ultima_ficha = c.ultima(r"^INSERT INTO alunos\b")
    assert c.primeira(r"^INSERT INTO matriculas\b") > ultima_ficha, c.resumo()
    assert c.primeira(r"^INSERT INTO logs_auditoria\b") > ultima_ficha, c.resumo()
    if db.get_bind().dialect.name == "postgresql":
        assert c.contar(r"^INSERT INTO matriculas\b") <= 3, c.resumo()
        assert c.contar(r"^INSERT INTO logs_auditoria\b") <= 3, c.resumo()
    db.expire_all()
    assert db.query(Matricula).join(Aluno).filter(
        Aluno.nome.like("ALUNO FICTICIO T%")).count() == 60


def _alunos_na_turma(db, escola_completa, n: int) -> list[Aluno]:
    turma = escola_completa["turma"]
    alunos = []
    for i in range(n):
        a = Aluno(escola_id=turma.escola_id, nome=f"Crianca Ficticia {i:03d} da Silva")
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=turma.escola_id, aluno_id=a.id, turma_id=turma.id,
                         ano_letivo=2026))
        alunos.append(a)
    db.commit()
    return alunos


def _placar(alunos, dia: str, extra: int = 0) -> dict:
    """O corpo do /confirmar, montado ANTES de contar (ler ``a.nome`` depois de um
    commit faria o SELECT do próprio teste entrar na conta)."""
    return {
        "plataforma": "matific", "formato": "resumo", "tipo": "texto",
        "data_referencia": f"{dia}T12:00:00", "recalcular": False,
        "linhas": [{"nome": a.nome, "aluno_id": a.id,
                    "dados": {"matific_uuid": f"uuid-ficticio-{a.id}", "turma_relatorio":
                              "3º Ano A", "atividades": 3 + extra, "estrelas": 9 + extra}}
                   for a in alunos]}


def test_placar_nao_consulta_o_vinculo_linha_a_linha(db, cliente, escola_completa,
                                                     sessao_de_producao):
    escola_id = escola_completa["escola"].id
    alunos = _alunos_na_turma(db, escola_completa, 60)
    corpo1, corpo2 = _placar(alunos, "2026-08-14"), _placar(alunos, "2026-08-15", extra=1)
    contas = {(a.id, f"uuid-ficticio-{a.id}") for a in alunos}
    url = f"{API}/escolas/{escola_id}/importacoes/confirmar"
    with Consultas(db.get_bind()) as c1:
        r1 = cliente.post(url, json=corpo1)
    assert r1.status_code == 200, r1.text[:300]
    # 1ª importação: 60 contas novas, uma ida cada, sem SAVEPOINT/RELEASE por conta.
    assert c1.contar(r"^INSERT INTO identidades_externas\b") == 60, c1.resumo()
    assert c1.contar(r"^SAVEPOINT\b") <= 2, c1.resumo()
    assert c1.contar(r"^SELECT .* FROM identidades_externas\b") <= 4, c1.resumo()
    db.expire_all()
    assert {(i.aluno_id, i.id_externo) for i in db.execute(
        select(IdentidadeExterna)).scalars()} == contas

    with Consultas(db.get_bind()) as c2:
        r2 = cliente.post(url, json=corpo2)
    assert r2.status_code == 200, r2.text[:300]
    assert len(r2.json()["alunos_aplicados_ids"]) == 60
    # Dia seguinte, todos já vinculados: o contexto sabe — nada de SELECT por linha.
    assert c2.contar(r"^SELECT .* FROM identidades_externas\b") <= 4, c2.resumo()
    assert c2.contar(r"^INSERT INTO identidades_externas\b") == 0, c2.resumo()


def test_vinculo_feito_por_outra_transacao_nao_e_roubado(db, escola_completa):
    """A conta foi vinculada a OUTRA ficha depois de o contexto ser lido (outra
    operação, fora da trava): o vínculo novo não a toma — como antes, pela unique."""
    from app.routers.importacoes import _vincular_identidade

    escola_id = escola_completa["escola"].id
    ana, joao = escola_completa["alunos"][0], escola_completa["alunos"][1]
    ctx = ida.carregar_contexto(db, escola_id)
    db.add(IdentidadeExterna(escola_id=escola_id, aluno_id=joao.id, plataforma="matific",
                             id_externo="uuid-disputado"))
    db.commit()
    assert _vincular_identidade(db, escola_id, ana.id, "matific", "uuid-disputado",
                                ctx=ctx) is False
    db.commit()
    dono = db.execute(select(IdentidadeExterna.aluno_id).where(
        IdentidadeExterna.id_externo == "uuid-disputado")).scalar_one()
    assert dono == joao.id
    assert ctx.identidade.get(("matific", "uuid-disputado")) != ana.id


def test_conta_aposentada_nao_e_reativada_pelo_contexto(db, escola_completa):
    from app.routers.importacoes import _vincular_identidade

    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    db.add(IdentidadeExterna(escola_id=escola_id, aluno_id=ana.id, plataforma="matific",
                             id_externo="uuid-aposentado", status="aposentada"))
    db.commit()
    ctx = ida.carregar_contexto(db, escola_id)
    assert _vincular_identidade(db, escola_id, ana.id, "matific", "uuid-aposentado",
                                ctx=ctx) is False
    status = db.execute(select(IdentidadeExterna.status).where(
        IdentidadeExterna.id_externo == "uuid-aposentado")).scalar_one()
    assert status == "aposentada"


def test_vinculo_novo_devolve_true_e_entra_no_contexto(db, escola_completa):
    """O vínculo gravado pelo INSERT direto devolve True (quem chama decide por ele —
    o aviso D10 da conta de outra escola, por exemplo) e passa a valer no contexto."""
    from app.routers.importacoes import _vincular_identidade

    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    ctx = ida.carregar_contexto(db, escola_id)
    assert _vincular_identidade(db, escola_id, ana.id, "matific", "uuid-novo",
                                ctx=ctx) is True
    assert ctx.identidade[("matific", "uuid-novo")] == ana.id
    # De novo, pelo contexto: True sem gravar outra linha.
    assert _vincular_identidade(db, escola_id, ana.id, "matific", "uuid-novo",
                                ctx=ctx) is True
    db.commit()
    assert db.execute(select(IdentidadeExterna.aluno_id).where(
        IdentidadeExterna.id_externo == "uuid-novo")).scalars().all() == [ana.id]
