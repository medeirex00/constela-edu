"""G_SCRIPTS-9 — ``recalcular_institucional``: o resumo do ``--dry-run`` não diz que
processou nada, e ``--rede`` com ``--escola`` não é ignorado em silêncio.

* No DRY-RUN o resumo dizia "escolas processadas: N", embora nada tivesse sido feito.
* ``if args.escola ... elif args.rede``: com os dois, o ``--rede`` caía fora sem aviso e
  uma escola de outra rede (ou sem rede) era recalculada. Agora os dois filtros valem
  juntos: só a escola pedida, se ela for da rede pedida.

Escolas, rede e crianças FICTÍCIAS.
"""
import sys

from sqlalchemy import select

from app.models import Aluno, Escola, Matricula, Nota, Rede, Turma
from scripts import recalcular_institucional as script


class _SessaoSemFechar:
    def __init__(self, sessao):
        self._sessao = sessao

    def __getattr__(self, nome):
        return getattr(self._sessao, nome)

    def close(self):
        pass


def _escola(db, nome, rede_id=None):
    esc = Escola(nome=nome, ano_letivo_ativo=2026, rede_id=rede_id)
    db.add(esc)
    db.flush()
    turma = Turma(escola_id=esc.id, nome="3º Ano A", ano_escolar="3º Ano", ano_letivo=2026)
    db.add(turma)
    db.flush()
    aluno = Aluno(escola_id=esc.id, nome=f"Crianca Inventada {nome}")
    db.add(aluno)
    db.flush()
    db.add(Matricula(escola_id=esc.id, aluno_id=aluno.id, turma_id=turma.id, ano_letivo=2026))
    db.add(Nota(escola_id=esc.id, aluno_id=aluno.id, ano_letivo=2026, nota_elefante=10.0,
                detalhes={}))
    db.commit()
    return esc.id


def _rodar(monkeypatch, db, capsys, *argumentos):
    monkeypatch.setattr(script, "SessionLocal", lambda: _SessaoSemFechar(db))
    monkeypatch.setattr(sys, "argv", ["recalcular_institucional", *argumentos])
    codigo = script.main()
    return codigo, capsys.readouterr().out


def _carimbada(db, escola_id):
    nota = db.execute(select(Nota).where(Nota.escola_id == escola_id)).scalar_one()
    db.refresh(nota)
    return "regua_institucional" in (nota.detalhes or {})


def test_dry_run_diz_quantas_seriam_recalculadas_e_nao_processadas(db, monkeypatch, capsys):
    eid = _escola(db, "Escola Inventada Ensaio")
    codigo, saida = _rodar(monkeypatch, db, capsys, "--escola", str(eid), "--dry-run")
    assert codigo == 0
    assert "escolas que seriam recalculadas: 1" in saida
    assert "escolas processadas" not in saida
    assert not _carimbada(db, eid)

    codigo, saida = _rodar(monkeypatch, db, capsys, "--escola", str(eid))
    assert codigo == 0 and "escolas processadas: 1" in saida
    assert _carimbada(db, eid)


def test_rede_e_escola_juntas_valem_as_duas(db, monkeypatch, capsys):
    rede = Rede(nome="Rede Inventada Recorte", status="ativa")
    db.add(rede)
    db.flush()
    da_rede = _escola(db, "Escola Inventada Da Rede", rede.id)
    avulsa = _escola(db, "Escola Inventada Avulsa")

    # A escola avulsa não é da rede pedida: nada a recalcular (antes, era recalculada).
    codigo, saida = _rodar(monkeypatch, db, capsys, "--rede", str(rede.id), "--escola",
                           str(avulsa))
    assert codigo == 0 and "Escolas a recalcular: 0" in saida
    assert not _carimbada(db, avulsa)

    codigo, saida = _rodar(monkeypatch, db, capsys, "--rede", str(rede.id), "--escola",
                           str(da_rede))
    assert codigo == 0 and "Escolas a recalcular: 1" in saida
    assert _carimbada(db, da_rede)
