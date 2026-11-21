"""G_SCRIPTS-1 — ``recalcular_institucional --pendentes`` converge: depois de uma rodada,
a seleção e o contador do painel da rede ficam vazios.

O "pendente" (``rede._q_pendentes``, que alimenta ``escolas_com_notas_pendentes`` e o
``recalculo_pendente`` do painel da rede, e ``escolas_com_versao_desatualizada`` do
script) contava a Nota de aluno matriculado em QUALQUER turma. O recálculo
(``scoring.recalcular_escola``) só regrava a população que concorre: a turma da
Educação Infantil (Fase) ou sem série reconhecível sai antes da conta, e a Nota já
gravada de quem saiu fica no banco. A Nota antiga (sem carimbo, ou com o de outra
versão da régua) dessa criança nunca era regravada e nunca saía da seleção: toda
rodada recalculava a escola inteira de novo, e o "0 escolas" do roteiro de deploy
nunca chegava.

Agora os dois lados olham a mesma população: aluno ativo matriculado no ano ativo numa
turma PREMIÁVEL. Escola e crianças FICTÍCIAS.
"""
import sys

from sqlalchemy import select

from app.models import Aluno, Escola, Matricula, Nota, Turma
from app.services import dificuldade_livro as dl
from app.services import rede
from scripts import recalcular_institucional as script


class _SessaoSemFechar:
    """O ``main()`` do script fecha a sessão no ``finally``; o teste ainda a usa."""

    def __init__(self, sessao):
        self._sessao = sessao

    def __getattr__(self, nome):
        return getattr(self._sessao, nome)

    def close(self):
        pass


def _escola_com_fase(db, *, carimbo_da_fase=None):
    """Uma criança no 3º ano e uma na 1ª Fase, as duas com Nota ANTIGA do ano ativo
    (sem carimbo institucional; a da Fase, opcionalmente, com o carimbo pedido)."""
    esc = Escola(nome="Escola Inventada Converge", ano_letivo_ativo=2026)
    db.add(esc)
    db.flush()
    ano = Turma(escola_id=esc.id, nome="3º Ano A", ano_escolar="3º Ano", ano_letivo=2026)
    fase = Turma(escola_id=esc.id, nome="1ª Fase A", ano_escolar="1ª Fase", ano_letivo=2026)
    db.add_all([ano, fase])
    db.flush()
    um = Aluno(escola_id=esc.id, nome="Crianca Inventada Um")
    dois = Aluno(escola_id=esc.id, nome="Crianca Inventada Dois")
    db.add_all([um, dois])
    db.flush()
    db.add_all([Matricula(escola_id=esc.id, aluno_id=um.id, turma_id=ano.id, ano_letivo=2026),
                Matricula(escola_id=esc.id, aluno_id=dois.id, turma_id=fase.id,
                          ano_letivo=2026)])
    detalhes_fase = ({"regua_institucional": {"versao_dificuldade": carimbo_da_fase,
                                              "perfil_local": "institucional"}}
                     if carimbo_da_fase else {})
    db.add_all([Nota(escola_id=esc.id, aluno_id=um.id, ano_letivo=2026, nota_elefante=10.0,
                     detalhes={}),
                Nota(escola_id=esc.id, aluno_id=dois.id, ano_letivo=2026, nota_elefante=10.0,
                     detalhes=detalhes_fase)])
    db.commit()
    return esc.id


def _rodar(monkeypatch, db, *argumentos):
    monkeypatch.setattr(script, "SessionLocal", lambda: _SessaoSemFechar(db))
    monkeypatch.setattr(sys, "argv", ["recalcular_institucional", *argumentos])
    return script.main()


def test_uma_rodada_de_pendentes_zera_a_selecao_e_o_painel(db, monkeypatch, capsys):
    eid = _escola_com_fase(db)
    assert script.escolas_pendentes(db) == [eid]

    assert _rodar(monkeypatch, db, "--pendentes") == 0
    assert "alunos recalculados: 1" in capsys.readouterr().out
    # Antes: ({eid: 1}, [eid]) para sempre — a Nota da Fase nunca ganha carimbo.
    assert rede._pendentes_recalculo(db, [eid]) == {}
    assert rede.escolas_com_notas_pendentes(db) == []
    assert script.escolas_pendentes(db) == []

    assert _rodar(monkeypatch, db, "--pendentes", "--dry-run") == 0
    assert "Escolas a recalcular: 0" in capsys.readouterr().out
    # A Nota antiga da Fase continua no banco, intocada (elegibilidade, não cadastro).
    notas = {n.aluno_id: n.detalhes for n in db.execute(select(Nota)).scalars()}
    assert sorted(len(d) for d in notas.values())[0] == 0


def test_nota_da_fase_com_versao_antiga_nao_fica_pendente_para_sempre(db):
    eid = _escola_com_fase(db, carimbo_da_fase=dl.VERSAO_V1)
    assert script.escolas_com_versao_desatualizada(db) == []
    assert rede._pendentes_recalculo(db, [eid]) == {eid: 1}      # só a do 3º ano


def test_o_painel_conta_so_a_nota_de_quem_concorre(db):
    """O ``recalculo_pendente`` do painel da rede: a Nota antiga da Fase não conta (o
    motor não a regrava); a do 3º ano, sim."""
    eid = _escola_com_fase(db)
    assert rede._pendentes_recalculo(db, [eid]) == {eid: 1}
