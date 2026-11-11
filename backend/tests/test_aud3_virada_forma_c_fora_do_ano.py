"""Forma C na janela da virada: coleta de fora do ano letivo que não conferiu nenhuma
conta da escola NÃO é "em dia" (REV3-VIRADA-2, sobre S_G_VIRADA-1).

O DEFEITO. Fevereiro de 2027, escola ainda em 2026. Desde o S_G_VIRADA-1, a criança sem
ficha que a coleta de fora do ano letivo traz fica de fora (não cria ficha nem vai para a
Revisão). Com a credencial de OUTRA escola (ou na 1ª coleta, sem nenhum vínculo), TODAS
as linhas eram assim: nenhuma conta da escola conferida, nenhuma pendência de revisão — e a
coleta saía 'sem_atualizacao/nada_mudou', que conta como em dia. Isso quebrava a forma C
(decisão aceita pelo dono: nenhuma conta da escola conferida não prova que o dado desta
escola está em dia): o alerta 'desatualizada' deixava de abrir, o diagnóstico de "acesso de
outra escola" sumia, e o alerta da coleta fora do ano dizia "Quem já tem ficha recebe os
números normalmente" — sem ninguém ter recebido nada. Inclusive com a política
'bloquear'.

A CORREÇÃO. Linha deixada de fora pela coleta fora do ano + nenhuma conta da escola
conferida = 'sem_atualizacao' com motivo próprio ('fora_do_ano_sem_conferencia'), que não
conta como em dia (nem como verificação): o 'desatualizada' abre depois da cadência. O
alerta da coleta fora do ano só afirma que quem tem ficha recebeu os números quando alguma
conta da escola foi conferida; sem isso, diz que nenhuma foi e aponta o acesso cadastrado.

Dados 100% fictícios; conectores reais com navegador falso (sem rede). O relógio é preso
em 10/02/2027 (escola em 2026): os testes valem em qualquer data em que a suíte rode.
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models import Aluno, RevisaoIdentidade
from app.models.sincronizacao import SincronizacaoAlerta
from app.services import politica_sync
from app.sync import service
from tests import _relogio
from tests._sync_nucleo_fakes import (NavElefante, PlacarFake, alertas_abertos, credencial,
                                      instalar, rodar, vincular)
from tests.test_sync_em_dia_forma_c import (_agenda_diaria, _da_escola, _de_outra_escola,
                                            _escola_sem_alunos, _recuar)

# 10/02/2027, meio-dia em Brasília: o ano civil de 2026 já acabou.
FEVEREIRO_2027 = datetime(2027, 2, 10, 15, 0, tzinfo=timezone.utc)
ALERTA = "coleta_fora_do_ano_letivo"
MOTIVO = "fora_do_ano_sem_conferencia"
RECEBE = "Quem já tem ficha recebe os números normalmente"


def _mensagem(db, eid, plataforma, tipo=ALERTA):
    alerta = db.execute(select(SincronizacaoAlerta).where(
        SincronizacaoAlerta.escola_id == eid, SincronizacaoAlerta.plataforma == plataforma,
        SincronizacaoAlerta.tipo == tipo,
        SincronizacaoAlerta.resolvido.is_(False))).scalars().first()
    return alerta.mensagem if alerta is not None else None


def _fichas_e_revisoes(db, eid):
    db.expire_all()
    fichas = db.execute(select(Aluno.nome).where(Aluno.escola_id == eid)).scalars().all()
    revisoes = db.execute(select(RevisaoIdentidade.id).where(
        RevisaoIdentidade.escola_id == eid)).scalars().all()
    return sorted(fichas), revisoes


@pytest.mark.parametrize("politica", ["bloquear", "permitir"])
def test_primeira_coleta_fora_do_ano_sem_conta_da_escola_nao_e_em_dia(db, escola_completa,
                                                                     monkeypatch, politica):
    """Escola em 2026 sem nenhuma ficha; em fevereiro de 2027 a credencial mostra crianças
    de outra escola. Nada da escola foi conferido: não é em dia, nem verificação."""
    _relogio.prender(monkeypatch, FEVEREIRO_2027)
    eid = _escola_sem_alunos(db)
    politica_sync.definir(db, eid, politica)
    db.commit()
    credencial(db, eid, "elefante")
    instalar(monkeypatch, nav_elefante=NavElefante(_de_outra_escola()))

    ex, erro = rodar(db, eid, "elefante")

    assert erro is None, erro
    # Comportamento primeiro (no 95f4ee99 saía 'nada_mudou' e contava como em dia).
    assert service.ultimo_em_dia_em(db, eid, "elefante") is None, (ex.status, ex.motivo)
    assert service.ultima_verificacao_em(db, eid, "elefante") is None
    assert service.ultimo_sucesso_em(db, eid, "elefante") is None
    assert (ex.status, ex.motivo) == ("sem_atualizacao", MOTIVO)
    assert ex.motivo in service.MOTIVOS_SEM_EM_DIA
    # Ninguém da outra escola entrou: nem ficha, nem Revisão.
    assert _fichas_e_revisoes(db, eid) == ([], [])
    abertos = alertas_abertos(db, eid, "elefante")
    assert ALERTA in abertos and "correspondencia_pendente" not in abertos, abertos
    mensagem = _mensagem(db, eid, "elefante")
    assert RECEBE not in mensagem, mensagem                 # ninguém recebeu nada
    assert "nenhuma conta já ligada a um aluno desta escola" in mensagem.lower(), mensagem
    assert "não conta como coleta em dia" in mensagem, mensagem
    assert "ainda não tem conta vinculada nesta plataforma" in mensagem, mensagem
    # A ação chega inteira (o alerta guarda só 500 caracteres).
    assert mensagem.endswith("“Ano letivo ativo” para 2027 em Configurações."), mensagem
    assert "Crianca Ficticia Outra" not in mensagem         # sem nome de criança


def test_vinculados_e_credencial_de_outra_escola_fora_do_ano_abre_desatualizada(
        db, escola_completa, monkeypatch):
    """A escola tem as três contas vinculadas e a credencial passa a ver outra escola,
    em fevereiro de 2027 (escola em 2026). Antes do S_G_VIRADA-1 era 'tudo_em_revisao';
    depois dele, 'nada_mudou' (em dia). Agora: não é em dia, o 'desatualizada' abre
    contra a última coleta boa e o alerta aponta o acesso cadastrado."""
    _relogio.prender(monkeypatch, FEVEREIRO_2027)
    ec = escola_completa
    eid = ec["escola"].id
    politica_sync.definir(db, eid, "bloquear")
    for al, sid in zip(ec["alunos"], (9100001, 9100002, 9100003)):
        vincular(db, eid, al.id, "elefante", sid)
    db.commit()
    credencial(db, eid, "elefante")
    nav = NavElefante(_da_escola(ec))
    instalar(monkeypatch, nav_elefante=nav)
    ex1, _ = rodar(db, eid, "elefante")
    assert ex1.status == "concluida" and ex1.qtd_alunos == 3, (ex1.status, ex1.motivo)
    _recuar(db, eid, "elefante", 3)
    cfg = _agenda_diaria(db, eid, "elefante", 10)
    referencia = service.ultimo_em_dia_em(db, eid, "elefante")
    assert referencia is not None

    nav.turmas = _de_outra_escola()                       # credencial de outra escola
    ex2, erro = rodar(db, eid, "elefante")

    assert erro is None, erro
    assert service.ultimo_em_dia_em(db, eid, "elefante") == referencia   # não andou
    db.refresh(cfg)
    assert service.esta_desatualizada(db, cfg)
    assert (ex2.status, ex2.motivo) == ("sem_atualizacao", MOTIVO)
    abertos = alertas_abertos(db, eid, "elefante")
    assert {ALERTA, "desatualizada"} <= set(abertos), abertos
    mensagem = _mensagem(db, eid, "elefante")
    assert RECEBE not in mensagem, mensagem
    assert "A escola tem 3 conta(s) vinculada(s) nesta plataforma" in mensagem, mensagem
    assert "acesso cadastrado é o desta escola" in mensagem, mensagem
    assert mensagem.endswith("“Ano letivo ativo” para 2027 em Configurações."), mensagem


def test_coleta_por_periodo_fora_do_ano_sem_conta_da_escola_nao_acusa_o_acesso(
        db, escola_completa, monkeypatch):
    """Coleta POR PERÍODO do Matific (nunca conta como em dia): sem conta da escola nela
    não há sinal de acesso de outra escola (o Placar do período pode trazer só quem
    jogou). O motivo segue o da coleta por período ('nada_mudou') e o alerta da coleta
    fora do ano não manda conferir o acesso — nem diz que alguém recebeu números."""
    _relogio.prender(monkeypatch, FEVEREIRO_2027)
    eid = escola_completa["escola"].id
    credencial(db, eid, "matific")
    placar = PlacarFake()
    placar.linhas = [("u-nova", "CRIANCA NOVA FICTICIA", "1 ANO A (300396901)", 3, 1)]
    instalar(monkeypatch, placar=placar)

    ex, erro = rodar(db, eid, "matific", parametros={"matific_start_date": "2027-02-01",
                                                     "matific_end_date": "2027-02-07"})

    assert erro is None, erro
    assert (ex.status, ex.motivo) == ("sem_atualizacao", "nada_mudou")
    mensagem = _mensagem(db, eid, "matific")
    assert mensagem is not None
    assert RECEBE not in mensagem, mensagem
    assert "acesso cadastrado" not in mensagem, mensagem
    assert "nenhuma conta já ligada a um aluno desta escola" in mensagem.lower(), mensagem
    assert mensagem.endswith("“Ano letivo ativo” para 2027 em Configurações."), mensagem


def test_coleta_fora_do_ano_que_conferiu_a_escola_segue_em_dia(db, escola_completa,
                                                               monkeypatch):
    """Controle: com as contas da escola conferidas, a coleta fora do ano segue em dia e o
    alerta diz que quem tem ficha recebeu os números (o que de fato aconteceu)."""
    _relogio.prender(monkeypatch, FEVEREIRO_2027)
    ec = escola_completa
    eid = ec["escola"].id
    for al, sid in zip(ec["alunos"], (9100001, 9100002, 9100003)):
        vincular(db, eid, al.id, "elefante", sid)
    db.commit()
    credencial(db, eid, "elefante")
    turmas = _da_escola(ec)
    turmas.update(_de_outra_escola())                     # e duas crianças sem ficha
    instalar(monkeypatch, nav_elefante=NavElefante(turmas))

    ex, erro = rodar(db, eid, "elefante")

    assert erro is None, erro
    assert ex.status == "concluida" and ex.qtd_alunos == 3, (ex.status, ex.motivo)
    assert service.ultimo_em_dia_em(db, eid, "elefante") is not None
    mensagem = _mensagem(db, eid, "elefante")
    assert RECEBE in mensagem, mensagem
    assert "acesso cadastrado" not in mensagem, mensagem


@pytest.mark.parametrize("ano_da_escola", [2026, 2028], ids=["terminou", "nao_comecou"])
@pytest.mark.parametrize("conferiu", [True, False], ids=["conferiu", "sem_conferencia"])
@pytest.mark.parametrize("por_periodo", [False, True], ids=["acumulado", "periodo"])
@pytest.mark.parametrize("contas", [(99999, 0), (0, 99999), (0, 0)],
                         ids=["vinculadas", "inativas", "nenhuma"])
def test_o_texto_do_alerta_cabe_nos_500_caracteres(db, escola_completa, monkeypatch,
                                                   ano_da_escola, conferiu, por_periodo,
                                                   contas):
    """O alerta guarda só 500 caracteres (``abrir_alerta``): nenhuma variação do texto
    da coleta fora do ano pode perder a ação do fim (o primeiro rascunho do texto sem
    conta conferida passava disso e cortava o "vire o ano letivo")."""
    _relogio.prender(monkeypatch, FEVEREIRO_2027)
    escola = escola_completa["escola"]
    escola.ano_letivo_ativo = ano_da_escola
    db.commit()
    vinculadas, inativas = contas
    monkeypatch.setattr(service, "_contas_vinculadas",
                        lambda _db, _eid, _plat, *, ativos=True:
                        vinculadas if ativos else inativas)
    ap = service._Apuracao()
    ap.descartes = {service._MOTIVO_FORA_DO_ANO: 99999}
    if conferiu:
        ap.conferidos_sem_mudanca = 3
    texto = service._mensagem_fora_do_ano_letivo(db, escola.id, ap, plataforma="matific",
                                                 por_periodo=por_periodo)
    assert len(texto) <= 500, (len(texto), texto)
    # Termina na ação inteira: virar o ano ou conferir o ano letivo ativo.
    assert texto.endswith(("Configurações.", "ficou de fora.", "coletar de novo.",
                           "o altera).")), texto
    assert (RECEBE in texto) is conferiu, texto
