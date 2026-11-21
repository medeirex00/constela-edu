"""Coleta FORA do ano letivo ativo: não mexe em matrícula nem cria ficha
(S_G_VIRADA-1, reforço).

O DEFEITO. Fevereiro de 2027: a escola ainda em 2026 (o Admin Global vira o ano
depois) e a coordenação clica em "Sincronizar agora" (o agendador está desligado).
O Matific já mostra as turmas de 2027. Com a série protegida
(``test_aud3_virada_coleta_serie``), ainda sobravam dois caminhos que escreviam o
ano de 2027 dentro de 2026:

* a troca de sala na MESMA série — quem repetiu o 3º ano e está no "3 ANO B" de 2027
  ia do 3º A para o 3º B DE 2026;
* a criação de ficha pela coleta (política 'permitir', a padrão): a criança nova de
  2027 nascia matriculada no 1º Ano A de 2026 e entrava no ranking, nas premiações e
  nos certificados do ano que terminou. No Elefante, o mesmo.

A CORREÇÃO. A coleta cujo dia (horário de Brasília) cai fora do ano letivo ativo da
escola grava os números de quem já tem ficha (o retrato é do ano da coleta: o ano que
terminou não o conta), mas não move matrícula nem cria ficha. A criança sem ficha fica
de fora — nem na Revisão de identidade, onde "Criar novo aluno" a criaria no ano que
terminou —, e a coleta depois da virada a traz. A execução abre o alerta
"coleta_fora_do_ano_letivo", que pede a virada do ano, sem nome de criança.

Dados 100% fictícios; conectores reais com navegador falso (sem rede). O relógio é
preso em 10/02/2027: os testes valem em qualquer data em que a suíte rode.
"""
from datetime import datetime, timezone

from sqlalchemy import select

from app.models import Aluno, Matricula, RevisaoIdentidade, Turma
from app.models.plataformas import SnapshotElefante, SnapshotMatific
from app.models.sincronizacao import SincronizacaoAlerta
from tests import _relogio
from tests._sync_nucleo_fakes import (NavElefante, PlacarFake, aluno_el, alertas_abertos,
                                      credencial, instalar, livro, logs, rodar, snap_atual,
                                      vincular)

# 10/02/2027, meio-dia em Brasília: o ano civil de 2026 já acabou.
FEVEREIRO_2027 = datetime(2027, 2, 10, 15, 0, tzinfo=timezone.utc)
K4A = "4 ANO A (300396900)"
K3B = "3 ANO B (300396902)"
K1A = "1 ANO A (300396901)"
ALERTA = "coleta_fora_do_ano_letivo"
LIA = "LIA NOVA FICTICIA"


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


def _ficha(db, eid, nome):
    db.expire_all()
    return db.execute(select(Aluno).where(Aluno.escola_id == eid,
                                          Aluno.nome == nome)).scalars().first()


def _matriculas_da_ficha(db, aluno_id):
    db.expire_all()
    return sorted(tuple(linha) for linha in db.execute(
        select(Turma.nome, Matricula.ano_letivo).join(
            Matricula, Matricula.turma_id == Turma.id).where(
            Matricula.aluno_id == aluno_id)).all())


def _alerta_aberto(db, eid, plataforma):
    return db.execute(select(SincronizacaoAlerta).where(
        SincronizacaoAlerta.escola_id == eid, SincronizacaoAlerta.plataforma == plataforma,
        SincronizacaoAlerta.tipo == ALERTA,
        SincronizacaoAlerta.resolvido.is_(False))).scalars().first()


def _revisoes(db, eid):
    return db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == eid)).scalars().all()


def test_coleta_do_matific_na_janela_da_virada_nao_reescreve_o_ano_que_terminou(
        db, escola_completa, monkeypatch):
    _relogio.prender(monkeypatch, FEVEREIRO_2027)
    escola = escola_completa["escola"]
    eid = escola.id
    ana, joao, sofia = alunos = escola_completa["alunos"]       # 3º Ano A de 2026
    assert escola.ano_letivo_ativo == 2026
    # 2026 tinha também o 4º A (outra coorte), o 3º B e o 1º A.
    for nome, serie in (("4º Ano A", "4º Ano"), ("3º Ano B", "3º Ano"), ("1º Ano A", "1º Ano")):
        _turma(db, eid, nome, serie, 2026)
    for al, u in zip(alunos, ("u-ana", "u-joao", "u-sofia")):
        vincular(db, eid, al.id, "matific", u)
    db.commit()
    credencial(db, eid, "matific")
    antes = _matriculas(db, alunos, 2026)

    # O Matific já mostra 2027: Ana e João no "4 ANO A"; Sofia repetiu e está no
    # "3 ANO B" (mesma série — numa coleta de 2026 seria troca de sala); e chegou a
    # Lia, criança nova, no "1 ANO A".
    placar = PlacarFake()
    placar.linhas = [("u-ana", ana.nome, K4A, 6, 2), ("u-joao", joao.nome, K4A, 3, 1),
                     ("u-sofia", sofia.nome, K3B, 4, 1), ("u-lia", LIA, K1A, 3, 1)]
    instalar(monkeypatch, placar=placar)
    ex, erro = rodar(db, eid, "matific")

    assert erro is None, erro
    # O ano que terminou fica como estava: ninguém mudou de turma em 2026…
    assert _matriculas(db, alunos, 2026) == antes
    # …e a criança de 2027 não nasceu numa turma de 2026 (nem foi para a Revisão,
    # onde "Criar novo aluno" a criaria em 2026 do mesmo jeito).
    assert _ficha(db, eid, LIA) is None
    assert _revisoes(db, eid) == []
    # Os números de quem já tem ficha entram (o retrato é de 2027: o ranking de 2026
    # não o conta).
    snap = snap_atual(db, SnapshotMatific, ana.id)
    assert snap is not None and (snap.estrelas, snap.atividades) == (6, 2)
    assert (ex.status, ex.qtd_em_revisao) == ("concluida", 0), (ex.status, ex.motivo)
    # A escola fica sabendo o que fazer — sem pendência de correspondência falsa.
    abertos = alertas_abertos(db, eid, "matific")
    assert ALERTA in abertos and "correspondencia_pendente" not in abertos, abertos
    mensagem = _alerta_aberto(db, eid, "matific").mensagem
    assert "2026" in mensagem and "vire o ano letivo" in mensagem.lower(), mensagem
    assert "ainda não têm ficha ficaram de fora" in mensagem, mensagem
    assert "nenhuma matrícula foi mudada" in mensagem, mensagem
    assert LIA.split()[0] not in mensagem.upper()          # sem nome de criança no alerta
    mensagens = [m for _e, _n, m in logs(db, ex.id)]
    assert any("vire o ano letivo" in m.lower() for m in mensagens), mensagens
    assert not any("movido de" in m for m in mensagens), mensagens

    # Depois da virada (o Admin Global vira para 2027 e as crianças são rematriculadas),
    # a coleta seguinte traz a Lia para a turma de 2027 e o alerta fecha.
    escola.ano_letivo_ativo = 2027
    t4a = _turma(db, eid, "4º Ano A", "4º Ano", 2027)
    t3b = _turma(db, eid, "3º Ano B", "3º Ano", 2027)
    _turma(db, eid, "1º Ano A", "1º Ano", 2027)
    for al, turma in ((ana, t4a), (joao, t4a), (sofia, t3b)):
        db.add(Matricula(escola_id=eid, aluno_id=al.id, turma_id=turma.id, ano_letivo=2027))
    db.commit()
    ex2, erro2 = rodar(db, eid, "matific")

    assert erro2 is None, erro2
    lia = _ficha(db, eid, LIA)
    assert lia is not None, [m for _e, _n, m in logs(db, ex2.id)]
    assert _matriculas_da_ficha(db, lia.id) == [("1º Ano A", 2027)]
    assert _matriculas(db, alunos, 2026) == antes
    assert _matriculas(db, alunos, 2027) == {ana.nome: "4º Ano A", joao.nome: "4º Ano A",
                                             sofia.nome: "3º Ano B"}
    assert ALERTA not in alertas_abertos(db, eid, "matific")


def test_coleta_do_elefante_fora_do_ano_letivo_nao_cria_ficha(db, escola_completa, monkeypatch):
    """O mesmo caminho de criação de ficha no Elefante: a criança nova de 2027 não
    nasce numa turma de 2026; quem já tem ficha recebe os livros. Os livros dela
    voltam a ser pedidos (o cursor dela não avança): a coleta depois da virada os traz."""
    _relogio.prender(monkeypatch, FEVEREIRO_2027)
    escola = escola_completa["escola"]
    eid = escola.id
    ana = escola_completa["alunos"][0]
    _turma(db, eid, "1º Ano A", "1º Ano", 2026)
    vincular(db, eid, ana.id, "elefante", 9300001)
    db.commit()
    credencial(db, eid, "elefante")
    turmas = {
        611001: {"nome": "4 ANO A TARDE ANUAL", "alunos": [
            aluno_el(9300001, ana.nome, [livro("Livro Ficticio Um", "D", "2027-02-03T10:00:00")])]},
        611002: {"nome": "1 ANO A TARDE ANUAL", "alunos": [
            aluno_el(9300009, LIA, [livro("Livro Ficticio Dois", "D", "2027-02-04T10:00:00")])]},
    }
    instalar(monkeypatch, nav_elefante=NavElefante(turmas))
    ex, erro = rodar(db, eid, "elefante")

    assert erro is None, erro
    assert _ficha(db, eid, LIA) is None and _revisoes(db, eid) == []
    assert _turma_da_matricula(db, ana.id, 2026) == "3º Ano A"
    assert snap_atual(db, SnapshotElefante, ana.id) is not None
    abertos = alertas_abertos(db, eid, "elefante")
    assert ALERTA in abertos and "correspondencia_pendente" not in abertos, abertos
    assert (ex.status, ex.qtd_em_revisao) == ("concluida", 0), (ex.status, ex.motivo)

    # Virado o ano, a mesma coleta cria a ficha dela em 2027, com o livro.
    escola.ano_letivo_ativo = 2027
    _turma(db, eid, "1º Ano A", "1º Ano", 2027)
    db.commit()
    ex2, erro2 = rodar(db, eid, "elefante")
    assert erro2 is None, erro2
    lia = _ficha(db, eid, LIA)
    assert lia is not None, [m for _e, _n, m in logs(db, ex2.id)]
    assert _matriculas_da_ficha(db, lia.id) == [("1º Ano A", 2027)]
    assert snap_atual(db, SnapshotElefante, lia.id) is not None
    assert ALERTA not in alertas_abertos(db, eid, "elefante")


def test_coleta_dentro_do_ano_letivo_segue_criando_a_ficha(db, escola_completa, monkeypatch):
    """Controle: com a escola no ano da coleta, a política 'permitir' segue criando a
    ficha da criança nova, sem alerta de virada."""
    _relogio.prender(monkeypatch, FEVEREIRO_2027)
    escola = escola_completa["escola"]
    eid = escola.id
    escola.ano_letivo_ativo = 2027
    _turma(db, eid, "1º Ano A", "1º Ano", 2027)
    db.commit()
    credencial(db, eid, "matific")
    placar = PlacarFake()
    placar.linhas = [("u-lia", LIA, K1A, 3, 1)]
    instalar(monkeypatch, placar=placar)
    ex, erro = rodar(db, eid, "matific")

    assert erro is None, erro
    lia = _ficha(db, eid, LIA)
    assert lia is not None and _matriculas_da_ficha(db, lia.id) == [("1º Ano A", 2027)]
    assert ALERTA not in alertas_abertos(db, eid, "matific")
