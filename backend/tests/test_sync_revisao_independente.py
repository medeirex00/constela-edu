"""Regressões dos defeitos da sincronização apontados pela revisão independente do
ramo de prontidão (d4caac4). Dados 100% FICTÍCIOS; conectores REAIS com navegador
falso; nenhuma rede. ``test_sync_revisao_independente_pg.py`` roda os mesmos
cenários num PostgreSQL local descartável.

1. D2(6): falha SÓ do ``student-leaderboard`` (endpoint acessório dos nomes) com as
   contas vinculadas conferidas é 'parcial/coleta_parcial' também quando nenhum
   número mudou — antes virava 'erro/sem_acesso_ao_dado' crítico, sem avaliar a
   queda retida. Essa 'parcial' SEM aluno aplicado não é a "última coleta com
   dado" do alerta 'plataforma_sem_dados' (como referência, com 0 aluno, calava o
   alerta do Placar que esvazia depois dela); a 'parcial' COM aluno continua sendo.
   Pela mesma regra (P18), ela não avança o "último sucesso", o frescor do /status
   nem o selo do ranking, nem conta no painel global (escolas sincronizadas, última
   sincronização): só a 'concluida' e a 'parcial' com aluno aplicado contam.
2. Processo morto DEPOIS de o /confirmar gravar um arquivo: a órfã fica com a marca
   de recálculo pendente e a coleta seguinte ('nada mudou') recalcula. Morta ANTES
   de gravar qualquer arquivo (na coleta), não ganha a marca (o aviso "os dados
   foram gravados" seria falso). 2b (integração 80a27da): a coleta sem aluno aplicado
   que recalcula pela marca não manda aos aparelhos "0 alunos atualizados".
3. Elefante: total de livros não inteiro ('2.0') ou ilegível não derruba a coleta
   inteira em 'erro_inesperado'.
4. Matific por período com data inexistente (31/02): a rota recusa; uma execução já
   na fila termina 'erro/periodo_invalido' sem gravar os números do período como
   acumulado.
5. Selo de frescor do ranking: a coleta POR PERÍODO não é a "última sincronização
   com dado aplicado" (a mesma regra de ``sync.service.ultimo_sucesso_em``).
"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import settings
from app.models import Escola, Nota
from app.models.plataformas import Leitura, SnapshotMatific
from app.models.sincronizacao import (
    SincronizacaoAlerta,
    SincronizacaoExecucao,
    SincronizacaoLog,
)
from app.services import frescor_ranking
from app.sync import orchestrator, service
from tests._sync_nucleo_fakes import (
    API, NavElefante, PlacarFake, aluno_el, alertas_abertos, contar, credencial,
    execucoes, instalar, livro, rodar, snap_atual)
from tests._ano_letivo import no_ano_de_hoje

K = "3 ANO A (300396804)"
CID_A = 511434


class _ProcessoMorreu(BaseException):
    """A morte do processo (deploy, falta de memória): não é ``Exception`` — nenhum
    ``except`` do serviço a captura e a execução fica 'executando'."""


def _matific_em_dia(db, ec, monkeypatch):
    """1ª coleta do Matific concluída: as três contas ficam vinculadas."""
    eid = ec["escola"].id
    a, b, c = ec["alunos"]
    credencial(db, eid, "matific")
    placar = PlacarFake()
    placar.linhas = [("u-a", a.nome, K, 40, 10), ("u-b", b.nome, K, 30, 8),
                     ("u-c", c.nome, K, 20, 5)]
    instalar(monkeypatch, placar=placar)
    ex, _ = rodar(db, eid, "matific")
    assert ex.status == "concluida"
    return eid, (a, b, c), placar


# ---------------------------------------------------------------------------
# 1. D2(6) — falha só do endpoint acessório dos nomes
# ---------------------------------------------------------------------------
def test_leaderboard_falhando_sem_numero_mudado_e_parcial_nao_erro(db, escola_completa,
                                                                  monkeypatch):
    eid, (a, _b, _c), placar = _matific_em_dia(db, escola_completa, monkeypatch)
    placar.status_lb = 403
    ex, erro = rodar(db, eid, "matific")
    assert erro is None
    assert (ex.status, ex.motivo, ex.qtd_alunos, ex.qtd_falhas) == (
        "parcial", "coleta_parcial", 0, 1)
    abertos = alertas_abertos(db, eid, "matific")
    assert "coleta_parcial" in abertos
    assert "sem_acesso_ao_dado" not in abertos       # o relatório de dados respondeu 2xx
    assert snap_atual(db, SnapshotMatific, a.id).atividades == 10   # nada mudou
    # Conta como VERIFICAÇÃO, não como "em dia" (contrato e93 §1.4, item 1).
    assert service.ultima_verificacao_em(db, eid, "matific") == ex.finalizada_em
    assert service.ultimo_em_dia_em(db, eid, "matific") < ex.finalizada_em


@no_ano_de_hoje
def test_leaderboard_falhando_com_total_retido_abre_o_alerta_de_queda(db, escola_completa,
                                                                     monkeypatch):
    """Total do ano MENOR que o gravado (retido) + falha só do endpoint dos nomes: a
    execução é 'parcial' e a avaliação da queda roda (antes, no 'erro', não rodava)."""
    eid, (a, b, c), placar = _matific_em_dia(db, escola_completa, monkeypatch)
    placar.status_lb = 403
    placar.linhas = [("u-a", a.nome, K, 35, 9), ("u-b", b.nome, K, 30, 8),
                     ("u-c", c.nome, K, 20, 5)]
    ex, erro = rodar(db, eid, "matific")
    assert erro is None
    assert (ex.status, ex.motivo) == ("parcial", "coleta_parcial")
    assert snap_atual(db, SnapshotMatific, a.id).atividades == 10   # retido
    abertos = alertas_abertos(db, eid, "matific")
    assert "queda_matific" in abertos and "sem_acesso_ao_dado" not in abertos


def _mensagem_aberta(db, eid, tipo):
    return db.execute(select(SincronizacaoAlerta.mensagem).where(
        SincronizacaoAlerta.escola_id == eid, SincronizacaoAlerta.plataforma == "matific",
        SincronizacaoAlerta.tipo == tipo, SincronizacaoAlerta.resolvido.is_(False))).scalar_one()


def test_parcial_sem_aluno_nao_cala_o_alerta_do_placar_vazio(db, escola_completa,
                                                            monkeypatch):
    """1ª coleta concluída (3 alunos); depois só o endpoint dos nomes falha e nada muda
    ('parcial', 0 aluno); depois o endpoint volta e o Placar vem vazio ('sem_dados').
    A referência do 'plataforma_sem_dados' é a 'concluida' — antes era a 'parcial' de
    0 aluno e o alerta não abria."""
    eid, _alunos, placar = _matific_em_dia(db, escola_completa, monkeypatch)
    ex1 = execucoes(db, eid, "matific")[0]
    placar.status_lb = 403
    ex2, _ = rodar(db, eid, "matific")
    assert (ex2.status, ex2.motivo, ex2.qtd_alunos) == ("parcial", "coleta_parcial", 0)
    placar.status_lb = 200
    placar.linhas = []
    ex3, erro = rodar(db, eid, "matific")
    assert erro is None and ex3.status == "sem_dados"
    assert service._ultima_com_dado(db, ex3).id == ex1.id
    assert "plataforma_sem_dados" in alertas_abertos(db, eid, "matific")
    assert "trouxe 3" in _mensagem_aberta(db, eid, "plataforma_sem_dados")


def test_parcial_com_aluno_aplicado_continua_referencia_do_placar_vazio(db, escola_completa,
                                                                       monkeypatch):
    """Controle do filtro: a 'parcial' em que o endpoint dos nomes falhou mas um aluno
    teve dado novo aplicado continua sendo a "última coleta com dado"."""
    eid, (a, b, c), placar = _matific_em_dia(db, escola_completa, monkeypatch)
    placar.status_lb = 403
    placar.linhas = [("u-a", a.nome, K, 45, 12), ("u-b", b.nome, K, 30, 8),
                     ("u-c", c.nome, K, 20, 5)]
    ex2, _ = rodar(db, eid, "matific")
    assert (ex2.status, ex2.motivo, ex2.qtd_alunos) == ("parcial", "coleta_parcial", 1)
    placar.status_lb = 200
    placar.linhas = []
    ex3, erro = rodar(db, eid, "matific")
    assert erro is None and ex3.status == "sem_dados"
    assert service._ultima_com_dado(db, ex3).id == ex2.id
    assert "trouxe 1" in _mensagem_aberta(db, eid, "plataforma_sem_dados")


def _concluida_recuada_e_parcial(db, ec, monkeypatch, linhas_da_2a=None):
    """1ª coleta concluída (3 alunos), com o fim recuado 3 h (as duas não caem no
    mesmo instante e a idade do frescor fica mensurável); 2ª: só o endpoint dos
    nomes falha (403). Sem ``linhas_da_2a`` nenhum número muda: 'parcial' com 0
    aluno aplicado (D2(6))."""
    eid, alunos, placar = _matific_em_dia(db, ec, monkeypatch)
    ex1 = execucoes(db, eid, "matific")[0]
    ex1.finalizada_em = ex1.finalizada_em - timedelta(hours=3)
    db.commit()
    placar.status_lb = 403
    if linhas_da_2a is not None:
        placar.linhas = linhas_da_2a(alunos)
    ex2, erro = rodar(db, eid, "matific")
    assert erro is None
    ex1 = db.get(SincronizacaoExecucao, ex1.id)
    assert ex2.finalizada_em > ex1.finalizada_em
    return eid, ex1, ex2


def _naive_utc(valor):
    """``datetime`` (ou o texto ISO do JSON) como UTC naive, para comparar."""
    if isinstance(valor, str):
        valor = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    if valor is not None and valor.tzinfo is not None:
        valor = valor.astimezone(timezone.utc).replace(tzinfo=None)
    return valor


def test_parcial_sem_aluno_nao_avanca_o_ultimo_sucesso(db, escola_completa, monkeypatch):
    """P18: a 'parcial' com 0 aluno aplicado não é "a última sincronização que APLICOU
    dado" (``ultimo_sucesso_em`` e o marco agrupado do /status) — antes era. Ela
    continua contando como VERIFICAÇÃO (contrato e93 §1.4, item 1)."""
    eid, ex1, ex2 = _concluida_recuada_e_parcial(db, escola_completa, monkeypatch)
    assert (ex2.status, ex2.motivo, ex2.qtd_alunos) == ("parcial", "coleta_parcial", 0)
    assert service.ultimo_sucesso_em(db, eid, "matific") == ex1.finalizada_em
    marco = service.marcos_por_plataforma(db, eid)["matific"]
    assert _naive_utc(marco.ultimo_sucesso_em) == _naive_utc(ex1.finalizada_em)
    assert service.ultima_verificacao_em(db, eid, "matific") == ex2.finalizada_em


def test_selo_de_frescor_nao_conta_parcial_sem_aluno(db, escola_completa, monkeypatch):
    """P18 no selo do ranking: a "última sincronização ok" é a 'concluida', não a
    'parcial' de 0 aluno."""
    eid, ex1, _ex2 = _concluida_recuada_e_parcial(db, escola_completa, monkeypatch)
    mapa = frescor_ranking._ultimas_sincronizacoes_ok(db, [eid])
    assert _naive_utc(mapa[(eid, "matific")]) == _naive_utc(ex1.finalizada_em)
    selo = frescor_ranking.frescor_da_escola(db, escola_completa["escola"], date.today())
    assert _naive_utc(selo["dimensoes"]["matematica"]["ultima_sincronizacao_ok_em"]) == (
        _naive_utc(ex1.finalizada_em))


def test_status_nao_mostra_parcial_sem_aluno_como_ultimo_sucesso(db, cliente, escola_completa,
                                                                 monkeypatch):
    """P18 na rota da tela (GET /sync/status): o "último sucesso" e a idade do frescor
    são os da 'concluida' (3 h); a última tentativa continua sendo a 'parcial'."""
    eid, ex1, _ex2 = _concluida_recuada_e_parcial(db, escola_completa, monkeypatch)
    st = cliente.get(f"{API}/escolas/{eid}/sync/status")
    assert st.status_code == 200, st.text
    mt = next(p for p in st.json()["plataformas"] if p["plataforma"] == "matific")
    assert _naive_utc(mt["ultimo_sucesso_em"]) == _naive_utc(ex1.finalizada_em)
    assert mt["idade_horas"] == 3
    assert (mt["ultima_tentativa"]["status"], mt["ultima_tentativa"]["qtd_alunos"]) == (
        "parcial", 0)


def test_parcial_com_aluno_aplicado_continua_avancando_o_ultimo_sucesso_e_o_selo(
        db, cliente, escola_completa, monkeypatch):
    """Controle: a 'parcial' em que o endpoint dos nomes falhou mas um aluno teve dado
    novo aplicado continua sendo o último sucesso, no serviço, no selo e no /status."""
    eid, _ex1, ex2 = _concluida_recuada_e_parcial(
        db, escola_completa, monkeypatch,
        linhas_da_2a=lambda al: [("u-a", al[0].nome, K, 45, 12), ("u-b", al[1].nome, K, 30, 8),
                                 ("u-c", al[2].nome, K, 20, 5)])
    assert (ex2.status, ex2.motivo, ex2.qtd_alunos) == ("parcial", "coleta_parcial", 1)
    assert service.ultimo_sucesso_em(db, eid, "matific") == ex2.finalizada_em
    mapa = frescor_ranking._ultimas_sincronizacoes_ok(db, [eid])
    assert _naive_utc(mapa[(eid, "matific")]) == _naive_utc(ex2.finalizada_em)
    mt = next(p for p in cliente.get(f"{API}/escolas/{eid}/sync/status").json()["plataformas"]
              if p["plataforma"] == "matific")
    assert _naive_utc(mt["ultimo_sucesso_em"]) == _naive_utc(ex2.finalizada_em)
    assert mt["idade_horas"] == 0


def test_painel_global_nao_conta_parcial_sem_aluno_como_sincronizada(db, cliente_global,
                                                                     escola_completa):
    """P18 no painel global (GET /sync/dashboard): "escolas sincronizadas" e "última
    sincronização" contam só execução que aplicou dado. A escola cuja única coleta é a
    'parcial' de 0 aluno não é sincronizada, e essa coleta não é a última."""
    agora = service._agora()
    so_parcial_vazia = Escola(nome="ESCOLA FICTICIA PARCIAL VAZIA", ano_letivo_ativo=2026)
    com_parcial_cheia = Escola(nome="ESCOLA FICTICIA PARCIAL CHEIA", ano_letivo_ativo=2026)
    db.add_all([so_parcial_vazia, com_parcial_cheia])
    db.flush()

    def _ex(eid, status, horas, qtd):
        db.add(SincronizacaoExecucao(
            escola_id=eid, plataforma="matific", origem="manual", status=status,
            motivo="coleta_parcial" if status == "parcial" else None, qtd_alunos=qtd,
            iniciada_em=agora - timedelta(hours=horas),
            finalizada_em=agora - timedelta(hours=horas)))

    _ex(escola_completa["escola"].id, "concluida", 10, 3)
    _ex(com_parcial_cheia.id, "parcial", 5, 1)
    _ex(so_parcial_vazia.id, "parcial", 1, 0)
    db.commit()
    r = cliente_global.get(f"{API}/sync/dashboard")
    assert r.status_code == 200, r.text
    painel = r.json()
    assert painel["escolas_sincronizadas"] == 2
    assert _naive_utc(painel["ultima_sincronizacao"]) == _naive_utc(agora - timedelta(hours=5))


# ---------------------------------------------------------------------------
# 2. Processo morto no meio da execução
# ---------------------------------------------------------------------------
def _posicao_matematica(db, aluno_id):
    db.expire_all()
    return db.execute(select(Nota.posicao_matematica).where(
        Nota.aluno_id == aluno_id)).scalar_one()


def _executar_e_morrer(db, eid):
    ex = service.enfileirar(db, eid, "matific", origem="manual")
    db.commit()
    exid = ex.id
    try:
        service.executar(db, ex)
    except _ProcessoMorreu:
        pass
    return exid


def _reiniciar_servico(db, exid):
    """O reinício: a limpeza de órfãs do boot fecha a execução presa em 'executando'
    (a mesma ``_finalizar_travada`` do reaper periódico e do ``enfileirar``)."""
    db.rollback()
    db.expire_all()
    morta = db.get(SincronizacaoExecucao, exid)
    assert morta.status == "executando"
    # O tempo passa sem nenhum sinal de vida: o início E o log dela ficam para trás
    # (o critério de órfã é o último registro, não a idade).
    atraso = timedelta(seconds=settings.SYNC_SEM_SINAL_S + 60)
    morta.iniciada_em = morta.iniciada_em - atraso
    for linha in db.execute(select(SincronizacaoLog).where(
            SincronizacaoLog.execucao_id == exid)).scalars():
        linha.created_at = linha.created_at - atraso
    db.commit()
    assert service.finalizar_orfas_no_boot(db) >= 1
    db.expire_all()
    return db.get(SincronizacaoExecucao, exid)


@no_ano_de_hoje
def test_morte_depois_de_gravar_um_arquivo_marca_recalculo_e_a_coleta_seguinte_recalcula(
        db, escola_completa, monkeypatch):
    eid, (a, b, c), placar = _matific_em_dia(db, escola_completa, monkeypatch)
    assert _posicao_matematica(db, c.id) == 3
    # A criança C sobe muito; o processo morre logo depois de o /confirmar commitar o
    # arquivo, antes do recálculo do fim (que é quem gravava a marca).
    placar.linhas = [("u-a", a.nome, K, 40, 10), ("u-b", b.nome, K, 30, 8),
                     ("u-c", c.nome, K, 400, 90)]
    original = orchestrator.aplicar_arquivo

    def _aplica_e_morre(*args, **kw):
        original(*args, **kw)
        raise _ProcessoMorreu()

    monkeypatch.setattr(orchestrator, "aplicar_arquivo", _aplica_e_morre)
    exid = _executar_e_morrer(db, eid)
    monkeypatch.setattr(orchestrator, "aplicar_arquivo", original)
    morta = _reiniciar_servico(db, exid)
    assert snap_atual(db, SnapshotMatific, c.id).estrelas == 400     # o dado ficou
    assert (morta.status, morta.recalculo_pendente) == ("erro", True)
    assert service.recalculo_pendente_aberto(db, eid, "matific")
    assert _posicao_matematica(db, c.id) == 3                        # notas atrás

    # Coleta seguinte com os MESMOS números: 'nada mudou', mas recalcula pela marca.
    ex3, _ = rodar(db, eid, "matific")
    assert (ex3.status, ex3.motivo) == ("sem_atualizacao", "nada_mudou")
    assert _posicao_matematica(db, c.id) == 1
    assert not service.recalculo_pendente_aberto(db, eid)


def test_morte_durante_a_coleta_nao_marca_recalculo(db, escola_completa, monkeypatch):
    """Controle: morreu ANTES de gravar qualquer arquivo (o caso comum: a coleta é a
    fase longa) — nada foi gravado, então não há recálculo pendente a anunciar."""
    eid, _alunos, _placar = _matific_em_dia(db, escola_completa, monkeypatch)

    def _morre_na_coleta(*_a, **_k):
        raise _ProcessoMorreu()

    monkeypatch.setattr(service, "_coletar", _morre_na_coleta)
    exid = _executar_e_morrer(db, eid)
    morta = _reiniciar_servico(db, exid)
    assert (morta.status, morta.recalculo_pendente) == ("erro", False)
    assert not service.recalculo_pendente_aberto(db, eid)


# ---------------------------------------------------------------------------
# 2b. Push do recálculo pela marca, sem aluno aplicado (integração 80a27da)
# ---------------------------------------------------------------------------
# A coleta que não aplicou nenhum aluno mas recalcula pela marca de recálculo
# pendente (órfã que gravou um arquivo, recálculo anterior que falhou) mandava a
# TODOS os aparelhos "0 alunos atualizados na Matific... As notas já foram
# recalculadas". O recálculo continua (e com ele o cache do painel e a pendência
# fechada); só o texto do push diz o que aconteceu.
def _espiao_push(monkeypatch):
    from app.services import push

    enviados = []
    monkeypatch.setattr(push, "notificar_escola",
                        lambda _db, escola_id, titulo, corpo, dados=None, **kw:
                        enviados.append((corpo, kw.get("aluno_id"))) or 0)
    return enviados


def _orfa_que_gravou(db, ec, monkeypatch):
    """Processo morto logo depois de gravar um arquivo: a órfã fica com a marca."""
    eid, (a, b, c), placar = _matific_em_dia(db, ec, monkeypatch)
    placar.linhas = [("u-a", a.nome, K, 40, 10), ("u-b", b.nome, K, 30, 8),
                     ("u-c", c.nome, K, 400, 90)]
    original = orchestrator.aplicar_arquivo

    def _aplica_e_morre(*args, **kw):
        original(*args, **kw)
        raise _ProcessoMorreu()

    monkeypatch.setattr(orchestrator, "aplicar_arquivo", _aplica_e_morre)
    exid = _executar_e_morrer(db, eid)
    monkeypatch.setattr(orchestrator, "aplicar_arquivo", original)
    assert _reiniciar_servico(db, exid).recalculo_pendente is True
    return eid, placar


def _sem_zero_alunos(enviados):
    assert len(enviados) == 1, enviados
    corpo, aluno_id = enviados[0]
    assert not corpo.startswith("0 alunos"), corpo
    assert "Notas recalculadas" in corpo and "Matific" in corpo
    assert aluno_id is None


def test_coleta_nada_mudou_que_recalcula_pela_marca_nao_anuncia_zero_alunos(
        db, escola_completa, monkeypatch):
    eid, _placar = _orfa_que_gravou(db, escola_completa, monkeypatch)
    enviados = _espiao_push(monkeypatch)
    ex, erro = rodar(db, eid, "matific")
    assert erro is None
    assert (ex.status, ex.motivo, ex.qtd_alunos) == ("sem_atualizacao", "nada_mudou", 0)
    _sem_zero_alunos(enviados)
    assert not service.recalculo_pendente_aberto(db, eid)


def test_coleta_parcial_sem_aluno_que_recalcula_pela_marca_nao_anuncia_zero_alunos(
        db, escola_completa, monkeypatch):
    eid, placar = _orfa_que_gravou(db, escola_completa, monkeypatch)
    enviados = _espiao_push(monkeypatch)
    placar.status_lb = 403              # só o student-leaderboard falha
    ex, erro = rodar(db, eid, "matific")
    assert erro is None
    assert (ex.status, ex.motivo, ex.qtd_alunos) == ("parcial", "coleta_parcial", 0)
    _sem_zero_alunos(enviados)


def test_recalculo_que_falhou_e_a_coleta_seguinte_sem_aluno_nao_anuncia_zero_alunos(
        db, escola_completa, monkeypatch):
    eid, (a, b, c), placar = _matific_em_dia(db, escola_completa, monkeypatch)
    placar.linhas = [("u-a", a.nome, K, 40, 10), ("u-b", b.nome, K, 30, 8),
                     ("u-c", c.nome, K, 400, 90)]
    original = service._recalcular_ao_final
    chamadas = {"n": 0}

    def _falha_uma_vez(*args, **kw):
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            raise RuntimeError("recálculo falhou (simulado)")
        return original(*args, **kw)

    monkeypatch.setattr(service, "_recalcular_ao_final", _falha_uma_vez)
    ex1, erro1 = rodar(db, eid, "matific")
    assert erro1 is None and ex1.qtd_alunos >= 1 and ex1.recalculo_pendente is True
    enviados = _espiao_push(monkeypatch)
    ex2, erro2 = rodar(db, eid, "matific")
    assert erro2 is None
    assert (ex2.status, ex2.qtd_alunos) == ("sem_atualizacao", 0)
    _sem_zero_alunos(enviados)


def test_coleta_com_aluno_aplicado_continua_dizendo_quantos(db, escola_completa,
                                                          monkeypatch):
    """Controle: com aluno aplicado o push continua com a contagem."""
    eid, (a, b, c), placar = _matific_em_dia(db, escola_completa, monkeypatch)
    placar.linhas = [("u-a", a.nome, K, 40, 10), ("u-b", b.nome, K, 30, 8),
                     ("u-c", c.nome, K, 400, 90)]
    enviados = _espiao_push(monkeypatch)
    ex, erro = rodar(db, eid, "matific")
    assert erro is None and (ex.status, ex.qtd_alunos) == ("concluida", 1)
    assert [corpo for corpo, _ in enviados] == [
        "1 alunos atualizados na Matific pela sincronização automática. "
        "As notas já foram recalculadas."]


# ---------------------------------------------------------------------------
# 3. Elefante — total de livros que não é inteiro
# ---------------------------------------------------------------------------
def test_elefante_total_nao_inteiro_ou_ilegivel_nao_derruba_a_coleta(db, escola_completa,
                                                                    monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    a, b, c = ec["alunos"]
    credencial(db, eid, "elefante")
    turmas = {CID_A: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
        aluno_el(9100001, a.nome, [livro("Livro Ficticio Um")]),
        aluno_el(9100002, b.nome, [livro("Livro Ficticio Dois", "E", "2026-09-05T10:00:00"),
                                   livro("Livro Ficticio Tres", "E", "2026-09-06T10:00:00")],
                 total="2.0"),
        aluno_el(9100003, c.nome, [livro("Livro Ficticio Quatro", "D", "2026-09-07T10:00:00")],
                 total="ilegivel")]}}
    instalar(monkeypatch, nav_elefante=NavElefante(turmas))
    ex, erro = rodar(db, eid, "elefante")
    assert erro is None
    assert ex.status in ("concluida", "parcial"), (ex.status, ex.motivo, ex.erro_resumo)
    cursor = service._carregar_contadores(db, eid, "elefante")
    assert cursor.get("9100001") == 1
    assert cursor.get("9100002") == 2          # '2.0' é 2: a mesma leitura do analisador
    assert "9100003" not in cursor             # ilegível: o cursor dele não avança
    assert contar(db, Leitura, Leitura.aluno_id == c.id) == 1   # os livros dele vieram


# ---------------------------------------------------------------------------
# 4. Matific por período com data que não existe
# ---------------------------------------------------------------------------
def test_rota_recusa_periodo_com_data_inexistente(db, cliente, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "matific")
    monkeypatch.setattr(service, "disparar_em_thread", lambda _id: None)
    r = cliente.post(f"{API}/escolas/{eid}/sync/agora?plataforma=matific"
                     "&inicio=2026-02-01&fim=2026-02-31")
    assert r.status_code == 400, r.text
    assert "inexistente" in r.json()["detail"]
    assert execucoes(db, eid, "matific") == []


def test_execucao_com_data_inexistente_termina_periodo_invalido_sem_tocar_o_acumulado(
        db, escola_completa, monkeypatch):
    """Execução já na fila (ou criada por outro caminho) com uma data impossível: sem
    a data, o arquivo sairia SEM período e o pipeline gravaria os números do período
    por cima do acumulado — sem a trava de queda."""
    eid, (a, b, c), placar = _matific_em_dia(db, escola_completa, monkeypatch)
    placar.linhas = [("u-a", a.nome, K, 6, 2), ("u-b", b.nome, K, 3, 1),
                     ("u-c", c.nome, K, 2, 1)]                    # números "do período"
    ex, erro = rodar(db, eid, "matific", parametros={
        "matific_start_date": "2026-02-01", "matific_end_date": "2026-02-31"})
    assert erro is None
    assert (ex.status, ex.motivo) == ("erro", "periodo_invalido")
    s = snap_atual(db, SnapshotMatific, a.id)
    assert (s.atividades, s.estrelas) == (10, 40)
    assert len(placar.filtros) == 1            # o Matific nem foi consultado de novo


# ---------------------------------------------------------------------------
# 5. Selo de frescor do ranking
# ---------------------------------------------------------------------------
def test_selo_de_frescor_nao_conta_coleta_por_periodo_como_ultima_sincronizacao(
        db, escola_completa, monkeypatch):
    eid, (a, b, c), placar = _matific_em_dia(db, escola_completa, monkeypatch)
    ex1 = execucoes(db, eid, "matific")[0]
    placar.linhas = [("u-a", a.nome, K, 7, 3), ("u-b", b.nome, K, 3, 1),
                     ("u-c", c.nome, K, 2, 1)]
    ex2, _ = rodar(db, eid, "matific", parametros={
        "matific_start_date": "2026-08-03", "matific_end_date": "2026-08-14"})
    assert ex2.status in ("concluida", "parcial"), (ex2.status, ex2.motivo)
    assert ex2.finalizada_em > ex1.finalizada_em
    assert service.ultimo_sucesso_em(db, eid, "matific") == ex1.finalizada_em
    selo = frescor_ranking.frescor_da_escola(db, escola_completa["escola"], date.today())
    assert selo["dimensoes"]["matematica"]["ultima_sincronizacao_ok_em"] == (
        ex1.finalizada_em.isoformat())
