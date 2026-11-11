"""A coleta não muda a SÉRIE de ninguém (S_G_VIRADA-1, correção principal).

O DEFEITO. A coleta do Matific movia a matrícula do ano letivo ativo para qualquer
turma ativa do mesmo ano que casasse com o rótulo do Placar por série + letra — de
OUTRA série inclusive (``_turma_existente_por_tokens`` exige a mesma etapa, não a
mesma série). Na virada isso corrompia o ano inteiro, com ou sem a virada feita:

* fevereiro, a escola ainda no ano que terminou e o Matific já com as turmas do ano
  novo: o 3º A ia todo para o 4º A do ano que terminou, misturado com a outra coorte;
* o ano já virado e o Matific ainda com as turmas do ano anterior: a coleta devolvia
  as crianças rematriculadas no 4º A ao 3º A do ano novo.

A data da coleta não é o gatilho (dentro do ano a coleta movia igual): decide o
rótulo da turma no Matific.

A CORREÇÃO. Mudança de série é virada, não troca de sala: a coleta nunca move entre
turmas de séries diferentes — vira aviso com o que fazer, e a matrícula fica onde
está. A troca de sala na MESMA série segue como antes
(``test_matific_turma_sync``, ``test_sync_politica_bloquear_matricula``).

Dados 100% fictícios; conectores reais com navegador falso (sem rede).
"""
from datetime import datetime, timezone

from sqlalchemy import select

from app.models import Matricula, Turma
from app.routers.importacoes import _sincronizar_turma_matific
from app.schemas.importacao import LinhaConfirmacao
from tests import _relogio
from tests._sync_nucleo_fakes import (PlacarFake, alertas_abertos, credencial, instalar, logs,
                                      rodar, vincular)

# 10/02/2027, meio-dia em Brasília: o relógio fica preso num instante do ano letivo da
# escola virada (o teste vale em qualquer data em que a suíte rode).
FEVEREIRO_2027 = datetime(2027, 2, 10, 15, 0, tzinfo=timezone.utc)
K4A = "4 ANO A (300396900)"
K3A = "3 ANO A (300396800)"


def _turma(db, eid, nome, serie, ano):
    t = Turma(escola_id=eid, nome=nome, ano_escolar=serie, ano_letivo=ano)
    db.add(t)
    db.flush()
    return t


def _turma_da_matricula(db, aluno_id, ano):
    db.expire_all()
    linha = db.execute(select(Turma.nome).join(
        Matricula, Matricula.turma_id == Turma.id).where(
        Matricula.aluno_id == aluno_id, Matricula.ano_letivo == ano)).first()
    return linha[0] if linha else None


def _matriculas(db, alunos, ano):
    return {a.nome: _turma_da_matricula(db, a.id, ano) for a in alunos}


def _linha(aluno, uuid, turma):
    return LinhaConfirmacao(nome=aluno.nome, aluno_id=aluno.id, via="identidade",
                            dados={"matific_uuid": uuid, "turma_relatorio": turma,
                                   "estrelas": 10, "atividades": 2})


def test_coleta_nao_move_a_crianca_para_turma_de_outra_serie(db, escola_completa):
    """Dentro do ano: o Matific diz "4 ANO A" para a criança do 3º Ano A e a "4º Ano A"
    existe — série e letra do Placar casam com ela, mas mudar de série é a virada do
    ano letivo, não troca de sala."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    ano = escola.ano_letivo_ativo
    _turma(db, escola.id, "4º Ano A", "4º Ano", ano)
    vincular(db, escola.id, ana.id, "matific", "u-ana")
    db.commit()
    avisos: list[str] = []
    movidos_ids: list[int] = []
    n = _sincronizar_turma_matific(db, escola.id, ano,
                                   {ana.id: (ana, [_linha(ana, "u-ana", K4A)])},
                                   avisos, movidos_ids=movidos_ids)
    assert (n, movidos_ids) == (0, [])
    assert _turma_da_matricula(db, ana.id, ano) == "3º Ano A"
    assert len(avisos) == 1, avisos
    assert "outra série" in avisos[0] and "4º Ano A" in avisos[0] and "não movi" in avisos[0]


def test_escola_ja_virada_e_matific_ainda_com_a_turma_do_ano_anterior(
        db, escola_completa, monkeypatch):
    """Ordem certa da virada: a escola foi para 2027 e as crianças do 3º A foram
    rematriculadas no 4º Ano A de 2027. O Matific ainda mostra "3 ANO A" (a turma de
    2026) e a "3º Ano A" de 2027 existe: a coleta — dentro do ano letivo ativo — não
    as devolve à série anterior."""
    _relogio.prender(monkeypatch, FEVEREIRO_2027)
    escola = escola_completa["escola"]
    eid = escola.id
    alunos = escola_completa["alunos"]
    contas = ("u-ana", "u-joao", "u-sofia")
    escola.ano_letivo_ativo = 2027
    t4a = _turma(db, eid, "4º Ano A", "4º Ano", 2027)
    _turma(db, eid, "3º Ano A", "3º Ano", 2027)
    for al, u in zip(alunos, contas):
        db.add(Matricula(escola_id=eid, aluno_id=al.id, turma_id=t4a.id, ano_letivo=2027))
        vincular(db, eid, al.id, "matific", u)
    db.commit()
    credencial(db, eid, "matific")
    antes = _matriculas(db, alunos, 2027)
    assert set(antes.values()) == {"4º Ano A"}

    placar = PlacarFake()
    placar.linhas = [(u, al.nome, K3A, 6 + i, 2 + i)
                     for i, (al, u) in enumerate(zip(alunos, contas))]
    instalar(monkeypatch, placar=placar)
    ex, erro = rodar(db, eid, "matific")

    assert erro is None, erro
    assert _matriculas(db, alunos, 2027) == antes
    assert _matriculas(db, alunos, 2026) == {a.nome: "3º Ano A" for a in alunos}
    mensagens = [m for _e, _n, m in logs(db, ex.id)]
    assert not any("movido de" in m for m in mensagens), mensagens
    assert ex.status == "concluida", (ex.status, ex.motivo)
    assert "correspondencia_pendente" not in alertas_abertos(db, eid, "matific")
