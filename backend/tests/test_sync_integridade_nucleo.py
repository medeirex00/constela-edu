"""Integridade do NÚCLEO da sincronização (Etapa 2, frente A): os 5 estados finais,
a contagem honesta, a coleta parcial visível, HTTP de erro do Matific, credencial,
alertas e o /status. Adaptado dos ensaios e92 (S2, S3, S9, S11; P01, P07, P21–P23).

Contrato dos estados (app/sync/service.py):
  concluida       nada falhou e ≥1 aluno teve dado novo/alterado;
  parcial         ≥1 aluno com dado aplicado e parte falhou (alerta 'coleta_parcial');
  sem_atualizacao coleta completa, com linhas, 0 aluno com dado novo
                  (motivo 'nada_mudou', 'correspondencia_pendente' ou, com tudo em
                  revisão e nenhuma conta da escola conferida, 'tudo_em_revisao');
  sem_dados       a plataforma respondeu 2xx com 0 turma/0 linha;
  erro            login, HTTP de erro, tempo, resposta incompatível, nada coletado.

Dados fictícios; conectores reais com navegador falso; nenhuma conexão externa.
"""
from sqlalchemy import func, select

from app.models import Turma
from app.models.plataformas import Leitura, SnapshotElefante, SnapshotMatific
from app.models.sincronizacao import SincronizacaoAlerta, SincronizacaoExecucao
from app.services import politica_sync
from app.sync import service, vault
from tests._sync_nucleo_fakes import (
    API, NavElefante, PlacarFake, aluno_el, alertas_abertos, contagens, credencial,
    instalar, livro, logs, novo_aluno, rodar, snap_atual)

K = "3 ANO A (300396804)"
CID_A, CID_B = 511434, 600001


def _origem_uma_turma(ec):
    a, b, c = ec["alunos"]
    return {CID_A: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
        aluno_el(9100001, a.nome, [livro("Livro Ficticio Um")]),
        aluno_el(9100002, b.nome, [livro("Livro Ficticio Dois", "E", "2026-09-05T10:00:00")]),
        aluno_el(9100003, c.nome, [livro("Livro Ficticio Tres", "D", "2026-09-06T10:00:00")])]}}


def _duas_turmas(db, ec):
    eid = ec["escola"].id
    a, b, c = ec["alunos"]
    t2 = Turma(escola_id=eid, nome="4º Ano B", ano_escolar="4º Ano", ano_letivo=2026)
    db.add(t2)
    db.commit()
    d = novo_aluno(db, eid, t2, "Crianca Ficticia Quarto Ano")
    db.commit()
    turmas = _origem_uma_turma(ec)
    turmas[CID_B] = {"nome": "4 ANO B TARDE ANUAL", "alunos": [
        aluno_el(9200001, d.nome, [livro("Livro Ficticio Quatro", "E", "2026-09-07T10:00:00")])]}
    return eid, (a, b, c, d), turmas


def _status_cred(db, eid, plataforma):
    return vault.obter_linha(db, eid, plataforma).status


def _alerta(db, eid, plataforma, tipo):
    return db.execute(select(SincronizacaoAlerta).where(
        SincronizacaoAlerta.escola_id == eid, SincronizacaoAlerta.plataforma == plataforma,
        SincronizacaoAlerta.tipo == tipo, SincronizacaoAlerta.resolvido.is_(False))
    ).scalars().first()


def _matific_base(db, ec, monkeypatch):
    eid = ec["escola"].id
    a, b, c = ec["alunos"]
    credencial(db, eid, "matific")
    placar = PlacarFake()
    placar.linhas = [("u-a", a.nome, K, 40, 10), ("u-b", b.nome, K, 30, 8),
                     ("u-c", c.nome, K, 20, 5)]
    instalar(monkeypatch, placar=placar)
    ex1, _ = rodar(db, eid, "matific")
    assert ex1.status == "concluida"
    return eid, (a, b, c), placar


# ===========================================================================
# 1. ZERO registros → 'sem_dados' (2xx sem nada); não é sucesso
# ===========================================================================
def test_elefante_roster_vazio_e_sem_dados_nao_renova_sucesso_mas_valida_credencial(
        db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "elefante")
    service.abrir_alerta(db, eid, "elefante", "falha_download", "falha anterior (simulada)")
    service.abrir_alerta(db, eid, "elefante", "desatualizada", "simulado", severidade="critico")
    db.commit()
    instalar(monkeypatch, nav_elefante=NavElefante({}, sem_turmas=True))
    ex, erro = rodar(db, eid, "elefante")
    assert erro is None and ex.status == "sem_dados" and ex.qtd_alunos == 0
    assert ex.qtd_linhas == 0 and ex.qtd_falhas == 0
    assert service.ultimo_sucesso_em(db, eid, "elefante") is None
    # A plataforma respondeu 2xx: verificado, e a credencial vale.
    assert service.ultima_verificacao_em(db, eid, "elefante") == ex.finalizada_em
    assert _status_cred(db, eid, "elefante") == "valida"
    # Uma coleta vazia não explica a falha anterior nem põe o dado em dia.
    assert {"falha_download", "desatualizada"} <= set(alertas_abertos(db, eid, "elefante"))


def test_matific_placar_vazio_e_sem_dados(db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "matific")
    instalar(monkeypatch, placar=PlacarFake())
    ex, erro = rodar(db, eid, "matific")
    assert erro is None and ex.status == "sem_dados"
    assert service.ultimo_sucesso_em(db, eid, "matific") is None
    assert "plataforma_sem_dados" not in alertas_abertos(db, eid, "matific")  # nunca teve


def test_plataforma_que_tinha_alunos_e_passa_a_zero_abre_plataforma_sem_dados(
        db, escola_completa, monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    credencial(db, eid, "elefante")
    nav = NavElefante(_origem_uma_turma(ec))
    instalar(monkeypatch, nav_elefante=nav)
    ex1, _ = rodar(db, eid, "elefante")
    assert ex1.status == "concluida" and ex1.qtd_alunos == 3
    nav.sem_turmas = True
    ex2, _ = rodar(db, eid, "elefante")
    assert ex2.status == "sem_dados"
    alerta = _alerta(db, eid, "elefante", "plataforma_sem_dados")
    assert alerta is not None and alerta.execucao_id == ex2.id and "3" in alerta.mensagem
    # Voltou a mandar linhas: o alerta fecha.
    nav.sem_turmas = False
    ex3, _ = rodar(db, eid, "elefante")
    assert ex3.status == "sem_atualizacao" and ex3.motivo == "nada_mudou"
    assert _alerta(db, eid, "elefante", "plataforma_sem_dados") is None


def test_matific_que_tinha_alunos_e_passa_a_zero_abre_alerta(db, escola_completa, monkeypatch):
    eid, _al, placar = _matific_base(db, escola_completa, monkeypatch)
    placar.linhas = []
    ex2, _ = rodar(db, eid, "matific")
    assert ex2.status == "sem_dados"
    assert "plataforma_sem_dados" in alertas_abertos(db, eid, "matific")


def test_lista_de_turmas_com_http_de_erro_e_erro_nao_sem_dados(db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "elefante")
    instalar(monkeypatch, nav_elefante=NavElefante({}, sem_turmas=True, status_roster=403))
    ex, _ = rodar(db, eid, "elefante")
    assert ex.status == "erro"
    assert "sem_acesso_ao_dado" in alertas_abertos(db, eid, "elefante")
    assert _status_cred(db, eid, "elefante") == "nao_validada"


# ===========================================================================
# 2. Novos + existentes, contagem DISTINTA (12→6 do Elefante)
# ===========================================================================
def test_elefante_qtd_alunos_e_turmas_distintos(db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    credencial(db, eid, "elefante")
    instalar(monkeypatch, nav_elefante=NavElefante(_origem_uma_turma(escola_completa)))
    ex, _ = rodar(db, eid, "elefante")
    distintos = db.scalar(select(func.count(func.distinct(SnapshotElefante.aluno_id)))
                          .where(SnapshotElefante.escola_id == eid))
    assert ex.status == "concluida" and ex.motivo is None
    assert ex.qtd_arquivos == 2                       # resumo + leituras da MESMA turma
    assert ex.qtd_alunos == distintos == 3            # antes: 6 (soma por arquivo)
    assert ex.qtd_alteracoes == 3
    assert ex.qtd_turmas == 1                         # antes: 2
    assert ex.qtd_erros == 0 and ex.qtd_falhas == 0 and ex.qtd_em_revisao == 0
    assert ex.qtd_linhas == 6                         # 3 linhas de resumo + 3 livros
    assert service.ultimo_sucesso_em(db, eid, "elefante") == ex.finalizada_em
    assert _status_cred(db, eid, "elefante") == "valida"


def test_matific_qtd_alunos_e_turmas(db, escola_completa, monkeypatch):
    eid, _al, _p = _matific_base(db, escola_completa, monkeypatch)
    ex = db.execute(select(SincronizacaoExecucao).where(
        SincronizacaoExecucao.escola_id == eid)).scalars().first()
    assert (ex.qtd_alunos, ex.qtd_turmas, ex.qtd_linhas, ex.qtd_erros) == (3, 1, 3, 0)


def test_novos_e_existentes_so_quem_mudou_conta(db, escola_completa, monkeypatch):
    """2ª coleta: 1 aluno mudou, os outros vieram iguais, 1 conta nova entrou →
    'concluida' com 2 alunos aplicados (o que mudou + o novo), nada duplicado."""
    ec = escola_completa
    eid = ec["escola"].id
    credencial(db, eid, "matific")
    a, b, c = ec["alunos"]
    placar = PlacarFake()
    placar.linhas = [("u-a", a.nome, K, 40, 10), ("u-b", b.nome, K, 30, 8)]
    instalar(monkeypatch, placar=placar)
    rodar(db, eid, "matific")
    antes = contagens(db, eid)
    placar.linhas = [("u-a", a.nome, K, 55, 12), ("u-b", b.nome, K, 30, 8),
                     ("u-c", c.nome, K, 5, 1)]
    ex2, _ = rodar(db, eid, "matific")
    depois = contagens(db, eid)
    assert ex2.status == "concluida" and ex2.qtd_alunos == 2 and ex2.qtd_linhas == 3
    assert depois["alunos"] == antes["alunos"] and depois["identidades"] == 3
    assert (snap_atual(db, SnapshotMatific, a.id).atividades,
            snap_atual(db, SnapshotMatific, b.id).atividades) == (12, 8)


def test_qtd_erros_conta_alunos_distintos_nao_aplicados(db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    politica_sync.definir(db, eid, "bloquear")
    db.commit()
    a = escola_completa["alunos"][0]
    credencial(db, eid, "elefante")
    turmas = {CID_A: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
        aluno_el(9100001, a.nome, [livro("Livro Ficticio Um")]),
        aluno_el(9300001, "Crianca Ficticia Sem Ficha Um",
                 [livro("Livro Ficticio Dois", "E", "2026-09-03T10:00:00")])]}}
    instalar(monkeypatch, nav_elefante=NavElefante(turmas))
    ex, _ = rodar(db, eid, "elefante")
    assert ex.status == "concluida" and ex.qtd_alunos == 1
    assert ex.qtd_erros == 1                          # antes: 2 (resumo + leituras)
    assert ex.qtd_em_revisao == 2                     # a linha do resumo e a do livro


# ===========================================================================
# 3. Tudo em revisão → 'sem_atualizacao' (tudo_em_revisao), não sucesso
#
# Ajuste da Etapa 3 (forma C da decisão 1): o motivo era
# 'correspondencia_pendente'. Nestas coletas NENHUMA conta da escola é conferida
# (todas as linhas vão para a revisão), então o motivo passa a ser o próprio
# 'tudo_em_revisao', que não conta como "em dia". O alerta continua o
# 'correspondencia_pendente'; o resto das asserções não mudou.
# ===========================================================================
def test_elefante_tudo_em_revisao_e_sem_atualizacao_com_alerta(db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    politica_sync.definir(db, eid, "bloquear")
    db.commit()
    credencial(db, eid, "elefante")
    turmas = {CID_A: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
        aluno_el(9300001, "Crianca Ficticia Sem Ficha Um", [livro("Livro Ficticio Um")]),
        aluno_el(9300002, "Crianca Ficticia Sem Ficha Dois",
                 [livro("Livro Ficticio Dois", "E", "2026-09-03T10:00:00")])]}}
    instalar(monkeypatch, nav_elefante=NavElefante(turmas))
    ex, _ = rodar(db, eid, "elefante")
    assert ex.status == "sem_atualizacao" and ex.motivo == "tudo_em_revisao"
    assert ex.qtd_alunos == 0 and ex.qtd_em_revisao == 4
    assert service.ultimo_sucesso_em(db, eid, "elefante") is None
    assert service.ultima_verificacao_em(db, eid, "elefante") is None   # não é "nada mudou"
    assert service.ultimo_em_dia_em(db, eid, "elefante") is None        # nem "em dia"
    assert "correspondencia_pendente" in alertas_abertos(db, eid, "elefante")


def test_matific_tudo_em_revisao_e_sem_atualizacao(db, escola_completa, monkeypatch):
    eid = escola_completa["escola"].id
    politica_sync.definir(db, eid, "bloquear")
    db.commit()
    credencial(db, eid, "matific")
    placar = PlacarFake()
    placar.linhas = [("u-x1", "Crianca Ficticia Um", "9 ANO Z (1)", 5, 2),
                     ("u-x2", "Crianca Ficticia Dois", "9 ANO Z (1)", 6, 3)]
    instalar(monkeypatch, placar=placar)
    ex, _ = rodar(db, eid, "matific")
    assert ex.status == "sem_atualizacao" and ex.motivo == "tudo_em_revisao"
    assert service.ultimo_sucesso_em(db, eid, "matific") is None
    assert service.ultimo_em_dia_em(db, eid, "matific") is None


# ===========================================================================
# 4. HTTP de erro do Matific (school_student e student-leaderboard)
# ===========================================================================
def _matific_http(db, ec, monkeypatch, *, ss=200, lb=200):
    eid, (a, _b, _c), placar = _matific_base(db, ec, monkeypatch)
    linha = vault.obter_linha(db, eid, "matific")
    vault.marcar_status(db, linha, "nao_validada")   # para ver se a sync carimba
    service.abrir_alerta(db, eid, "matific", "falha_download", "falha anterior (simulada)")
    db.commit()
    placar.status_ss, placar.status_lb = ss, lb
    placar.linhas = [(u, n, k, e + 100, at + 50) for u, n, k, e, at in placar.linhas]
    ex, erro = rodar(db, eid, "matific")
    return eid, a, ex, erro


def test_matific_school_student_401_e_erro_sem_acesso_ao_dado(db, escola_completa, monkeypatch):
    eid, a, ex, erro = _matific_http(db, escola_completa, monkeypatch, ss=401)
    assert erro is None and ex.status == "erro"
    assert "HTTP 401" in ex.erro_resumo
    assert "sem_acesso_ao_dado" in alertas_abertos(db, eid, "matific")
    assert _status_cred(db, eid, "matific") == "nao_validada"       # nunca 'valida' em erro
    assert "falha_download" in alertas_abertos(db, eid, "matific")  # não fecha a anterior
    s = snap_atual(db, SnapshotMatific, a.id)
    assert (s.atividades, s.estrelas) == (10, 40)                   # nada apagado/alterado


def test_matific_school_student_403_e_erro_sem_acesso_ao_dado(db, escola_completa, monkeypatch):
    eid, _a, ex, _ = _matific_http(db, escola_completa, monkeypatch, ss=403)
    assert ex.status == "erro"
    assert _alerta(db, eid, "matific", "sem_acesso_ao_dado").severidade == "critico"


def test_matific_school_student_500_e_erro_falha_download(db, escola_completa, monkeypatch):
    eid, _a, ex, _ = _matific_http(db, escola_completa, monkeypatch, ss=500)
    assert ex.status == "erro" and "HTTP 500" in ex.erro_resumo
    assert "falha_download" in alertas_abertos(db, eid, "matific")
    assert "sem_acesso_ao_dado" not in alertas_abertos(db, eid, "matific")
    assert _status_cred(db, eid, "matific") == "nao_validada"


def test_matific_leaderboard_403_nao_derruba_a_coleta_e_parcial(db, escola_completa,
                                                                monkeypatch):
    """O student-leaderboard só traz os NOMES completos: recusado, a coleta segue
    (quem já está vinculado casa pelo uuid; conta nova iria para a revisão
    'nome_incompleto') e a falha fica visível como unidade ('endpoint') —
    'parcial' com o alerta 'coleta_parcial'. Antes (revisão e93, regressão R3)
    derrubava a escola inteira em 'erro', diferente do 34f1a23 e do c5e78d3."""
    eid, a, ex, _ = _matific_http(db, escola_completa, monkeypatch, lb=403)
    assert (ex.status, ex.motivo, ex.qtd_falhas) == ("parcial", "coleta_parcial", 1)
    assert "coleta_parcial" in alertas_abertos(db, eid, "matific")
    assert snap_atual(db, SnapshotMatific, a.id).atividades == 60


def test_matific_corpo_fora_do_formato_e_parser_incompativel(db, escola_completa, monkeypatch):
    eid, _al, placar = _matific_base(db, escola_completa, monkeypatch)
    placar.school_student = lambda expr: {"ok": True, "status": 200, "body": {"resultado": []}}
    ex, _ = rodar(db, eid, "matific")
    assert ex.status == "erro"
    assert _alerta(db, eid, "matific", "parser_incompativel").severidade == "critico"


def test_matific_conta_vinculada_que_some_do_placar_e_avisada(db, escola_completa, monkeypatch):
    eid, (_a, b, c), placar = _matific_base(db, escola_completa, monkeypatch)
    assert contagens(db, eid)["identidades"] == 3       # a 1ª coleta vinculou as 3 contas
    placar.linhas = [placar.linhas[0]]
    ex, _ = rodar(db, eid, "matific")
    avisos = [m for _e, n, m in logs(db, ex.id) if n == "warn" and "ausentes" in m]
    assert avisos and avisos[0].startswith("2 conta(s)")
    assert (snap_atual(db, SnapshotMatific, b.id).atividades,
            snap_atual(db, SnapshotMatific, c.id).atividades) == (8, 5)   # não zerou


# ===========================================================================
# 5. Coleta parcial do Elefante: turma, lote e aluno com falha
# ===========================================================================
def test_elefante_turma_com_http_500_e_parcial_visivel(db, escola_completa, monkeypatch):
    eid, (a, b, c, d), turmas = _duas_turmas(db, escola_completa)
    credencial(db, eid, "elefante")
    instalar(monkeypatch, nav_elefante=NavElefante(turmas, erro_turma={CID_B: 500}))
    ex, erro = rodar(db, eid, "elefante")
    assert erro is None
    assert ex.status == "parcial" and ex.motivo == "coleta_parcial"
    assert ex.qtd_falhas == 1 and ex.qtd_alunos == 3 and ex.qtd_turmas == 1
    alerta = _alerta(db, eid, "elefante", "coleta_parcial")
    assert alerta is not None and "turma: 1" in alerta.mensagem
    for al in (a, b, c):
        assert snap_atual(db, SnapshotElefante, al.id) is not None
    assert snap_atual(db, SnapshotElefante, d.id) is None
    cursor = service._carregar_contadores(db, eid, "elefante")
    assert "9200001" not in cursor and {"9100001", "9100002", "9100003"} <= set(cursor)
    # Dado aplicado: renova o último sucesso e a credencial vale.
    assert service.ultimo_sucesso_em(db, eid, "elefante") == ex.finalizada_em
    assert _status_cred(db, eid, "elefante") == "valida"
    # A próxima coleta completa fecha o alerta.
    instalar(monkeypatch, nav_elefante=NavElefante(turmas))
    ex2, _ = rodar(db, eid, "elefante")
    assert ex2.status == "concluida"
    assert _alerta(db, eid, "elefante", "coleta_parcial") is None


def test_elefante_excecao_no_course_report_e_parcial(db, escola_completa, monkeypatch):
    eid, _al, turmas = _duas_turmas(db, escola_completa)
    credencial(db, eid, "elefante")
    instalar(monkeypatch, nav_elefante=NavElefante(turmas, excecao_turma={CID_B}))
    ex, erro = rodar(db, eid, "elefante")
    assert erro is None and ex.status == "parcial" and ex.qtd_falhas == 1


def test_elefante_todas_as_turmas_falham_e_erro(db, escola_completa, monkeypatch):
    eid, _al, turmas = _duas_turmas(db, escola_completa)
    credencial(db, eid, "elefante")
    instalar(monkeypatch, nav_elefante=NavElefante(turmas, erro_turma={CID_A: 403, CID_B: 401}))
    ex, _ = rodar(db, eid, "elefante")
    assert ex.status == "erro"
    assert "sem_acesso_ao_dado" in alertas_abertos(db, eid, "elefante")
    assert _status_cred(db, eid, "elefante") == "nao_validada"


def test_elefante_lote_de_livros_com_erro_e_parcial(db, escola_completa, monkeypatch):
    eid, (a, _b, _c, _d), turmas = _duas_turmas(db, escola_completa)
    credencial(db, eid, "elefante")
    instalar(monkeypatch, nav_elefante=NavElefante(turmas, excecao_lote={CID_A}))
    ex, _ = rodar(db, eid, "elefante")
    assert ex.status == "parcial" and ex.qtd_falhas == 1
    assert snap_atual(db, SnapshotElefante, a.id) is not None          # o resumo entrou
    assert contagens(db, eid)["leituras"] == 1                          # só a da turma B
    cursor = service._carregar_contadores(db, eid, "elefante")
    assert not ({"9100001", "9100002", "9100003"} & set(cursor))
    assert any("NÃO coletados" in m for _e, n, m in logs(db, ex.id) if n == "warn")


def test_elefante_aluno_com_http_500_e_aluno_omitido_no_lote_sao_falhas(
        db, escola_completa, monkeypatch):
    eid, _al, turmas = _duas_turmas(db, escola_completa)
    credencial(db, eid, "elefante")
    instalar(monkeypatch, nav_elefante=NavElefante(turmas, status_aluno={9100002: 500},
                                                   omitir_aluno={9100003}))
    ex, _ = rodar(db, eid, "elefante")
    cursor = service._carregar_contadores(db, eid, "elefante")
    assert ex.status == "parcial" and ex.qtd_falhas == 2
    assert "9100002" not in cursor and "9100003" not in cursor and "9100001" in cursor
    assert "aluno: 2" in _alerta(db, eid, "elefante", "coleta_parcial").mensagem


def test_parcial_nao_fecha_desatualizada(db, escola_completa, monkeypatch):
    from app.models.sincronizacao import SincronizacaoConfig
    eid, _al, turmas = _duas_turmas(db, escola_completa)
    credencial(db, eid, "elefante")
    cfg = SincronizacaoConfig(escola_id=eid, plataforma="elefante", ativo=True,
                              cadencia="diaria")
    db.add(cfg)
    db.commit()
    cfg.updated_at = service._agora().replace(year=2026, month=1, day=1)
    db.commit()
    instalar(monkeypatch, nav_elefante=NavElefante(turmas, erro_turma={CID_B: 500}))
    ex, _ = rodar(db, eid, "elefante")
    assert ex.status == "parcial"
    assert "desatualizada" in alertas_abertos(db, eid, "elefante")
    instalar(monkeypatch, nav_elefante=NavElefante(turmas))
    ex2, _ = rodar(db, eid, "elefante")
    assert ex2.status == "concluida"
    assert "desatualizada" not in alertas_abertos(db, eid, "elefante")


# ===========================================================================
# 6. Campo ausente/renomeado → 'parser_incompativel', sem retrato herdado
# ===========================================================================
def test_matific_campo_renomeado_nao_grava_retrato_herdado(db, escola_completa, monkeypatch):
    eid, (a, _b, _c), placar = _matific_base(db, escola_completa, monkeypatch)
    n_antes = db.scalar(select(func.count()).select_from(SnapshotMatific))
    placar.renomear = {"score": "pontos"}             # a API trocou o nome do campo
    ex, _ = rodar(db, eid, "matific")
    assert ex.status == "erro"
    assert _alerta(db, eid, "matific", "parser_incompativel").severidade == "critico"
    assert db.scalar(select(func.count()).select_from(SnapshotMatific)) == n_antes
    assert snap_atual(db, SnapshotMatific, a.id).estrelas == 40     # não virou 0


def test_elefante_campo_renomeado_nao_grava_retrato_com_data_nova(db, escola_completa, monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    a = ec["alunos"][0]
    credencial(db, eid, "elefante")
    turmas = {CID_A: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
        aluno_el(9100001, a.nome, [livro("Livro Ficticio Um")], total=5)]}}
    nav = NavElefante(turmas)
    instalar(monkeypatch, nav_elefante=nav)
    rodar(db, eid, "elefante")
    antes = snap_atual(db, SnapshotElefante, a.id)
    antes = (antes.livros_unicos, antes.tempo_leitura_min, antes.questoes_tentativas)
    original = nav.avaliar

    async def renomeado(expressao):
        res = await original(expressao)
        if isinstance(res, dict) and isinstance(res.get("body"), dict) \
                and "students" in res["body"]:
            for s in res["body"]["students"]:
                s["qtdNovoNome"] = s.pop("totalBooksRead")
        return res
    nav.avaliar = renomeado
    ex, _ = rodar(db, eid, "elefante")
    assert ex.status == "erro" and ex.qtd_alunos == 0
    assert "parser_incompativel" in alertas_abertos(db, eid, "elefante")
    # O resumo sem o campo não foi aplicado: nenhum retrato com livros zerados ou
    # herdados dele (o retrato das LEITURAS, que chegaram, repete os mesmos números).
    depois = snap_atual(db, SnapshotElefante, a.id)
    assert (depois.livros_unicos, depois.tempo_leitura_min,
            depois.questoes_tentativas) == antes
    assert db.scalar(select(func.count()).select_from(SnapshotElefante).where(
        SnapshotElefante.livros_unicos == 0)) == 0
    assert any("Campos ausentes" in m for _e, _n, m in logs(db, ex.id))


def test_elefante_campo_ausente_em_parte_das_linhas_e_parcial(db, escola_completa, monkeypatch):
    """Uma linha sem o campo essencial: a ficha dela não recebe retrato herdado
    com data nova; as outras entram; a execução é 'parcial' com alerta crítico."""
    ec = escola_completa
    eid = ec["escola"].id
    a, b, _c = ec["alunos"]
    credencial(db, eid, "elefante")
    turmas = {CID_A: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
        aluno_el(9100001, a.nome, [livro("Livro Ficticio Um")]),
        aluno_el(9100002, b.nome, [livro("Livro Ficticio Dois", "E", "2026-09-05T10:00:00")])]}}
    nav = NavElefante(turmas)
    original = nav.avaliar

    async def sem_campo_de_b(expressao):
        res = await original(expressao)
        if isinstance(res, dict) and isinstance(res.get("body"), dict) \
                and "students" in res["body"]:
            for s in res["body"]["students"]:
                if s["studentId"] == 9100002:
                    s.pop("totalBooksRead")
        return res
    nav.avaliar = sem_campo_de_b
    instalar(monkeypatch, nav_elefante=nav)
    ex, _ = rodar(db, eid, "elefante")
    assert ex.status == "parcial" and ex.motivo == "linhas_descartadas"
    assert "parser_incompativel" in alertas_abertos(db, eid, "elefante")
    resumo_b = db.execute(select(SnapshotElefante).where(
        SnapshotElefante.aluno_id == b.id, SnapshotElefante.importacao_id.isnot(None))
        .order_by(SnapshotElefante.id)).scalars().all()
    # B só tem o retrato derivado das LEITURAS (que chegaram), nenhum do resumo.
    assert len(resumo_b) == 1
    assert db.scalar(select(func.count()).select_from(Leitura).where(Leitura.aluno_id == b.id)) == 1


def test_livro_sem_data_e_linha_descartada_contada(db, escola_completa, monkeypatch):
    ec = escola_completa
    eid = ec["escola"].id
    a = ec["alunos"][0]
    credencial(db, eid, "elefante")
    turmas = {CID_A: {"nome": "3 ANO A TARDE ANUAL", "alunos": [
        aluno_el(9100001, a.nome, [livro("Livro Ficticio Um"),
                                   livro("Livro Ficticio Dois", data=None)])]}}
    instalar(monkeypatch, nav_elefante=NavElefante(turmas))
    ex, _ = rodar(db, eid, "elefante")
    assert ex.status == "parcial" and ex.motivo == "linhas_descartadas"
    assert "sem_data: 1" in _alerta(db, eid, "elefante", "coleta_parcial").mensagem
    assert ex.qtd_erros == 1


# ===========================================================================
# 7. /status e ExecucaoOut expõem o contrato
# ===========================================================================
def test_status_expoe_verificacao_ultimo_status_motivo_e_um_dia(
        db, cliente, escola_completa, monkeypatch):
    eid, _al, _placar = _matific_base(db, escola_completa, monkeypatch)
    ex2, _ = rodar(db, eid, "matific")              # mesma coleta: nada mudou
    assert ex2.status == "sem_atualizacao" and ex2.motivo == "nada_mudou"
    r = cliente.get(f"{API}/escolas/{eid}/sync/status")
    assert r.status_code == 200, r.text
    mt = next(p for p in r.json()["plataformas"] if p["plataforma"] == "matific")
    assert mt["ultimo_status"] == "sem_atualizacao" and mt["ultimo_motivo"] == "nada_mudou"
    assert mt["ultima_verificacao_em"] is not None
    assert mt["ultimo_sucesso_em"] is not None and mt["ultimo_sucesso_em"] < mt["ultima_verificacao_em"]
    assert mt["recalculo_pendente"] is False
    assert mt["periodo_um_dia_permitido"] is False      # MATIFIC_END_DATE desconhecida
    tent = mt["ultima_tentativa"]
    assert tent["status"] == "sem_atualizacao" and tent["qtd_linhas"] == 3
    assert tent["qtd_falhas"] == 0 and tent["qtd_em_revisao"] == 0 and tent["periodo"] is None
    h = cliente.get(f"{API}/escolas/{eid}/sync/historico").json()
    assert [e["status"] for e in h] == ["sem_atualizacao", "concluida"]


def test_execucao_antiga_sem_contabilidade_continua_legivel(db, cliente, escola_completa):
    """Execução anterior à 0039: contagens NULL ('não medido'), sem quebrar a API."""
    eid = escola_completa["escola"].id
    db.add(SincronizacaoExecucao(escola_id=eid, plataforma="matific", origem="manual",
                                 status="concluida", parametros={}))
    db.commit()
    h = cliente.get(f"{API}/escolas/{eid}/sync/historico").json()
    assert h[0]["qtd_linhas"] is None and h[0]["motivo"] is None
    assert h[0]["recalculo_pendente"] is False and h[0]["periodo"] is None


def test_decidir_status_regra_unica():
    ap = service._Apuracao()
    assert service.decidir_status(ap) == ("sem_dados", None)
    ap.linhas = 3
    assert service.decidir_status(ap) == ("sem_atualizacao", "nada_mudou")
    ap.em_revisao = 1
    # Etapa 3 (forma C): pendência sem nenhuma conta da escola conferida tem
    # motivo próprio; com ≥1 conferida sem mudança, é a correspondência pendente.
    assert service.decidir_status(ap) == ("sem_atualizacao", "tudo_em_revisao")
    ap.conferidos_sem_mudanca = 2
    assert service.decidir_status(ap) == ("sem_atualizacao", "correspondencia_pendente")
    ap.aplicados = {1}
    assert service.decidir_status(ap) == ("concluida", None)
    ap.falhas = [{"unidade": "turma", "codigo": "falha_download"}]
    assert service.decidir_status(ap) == ("parcial", "coleta_parcial")
    assert service.decidir_status(ap, falha_no_meio=True) == ("parcial", "falha_apos_gravacao")
    ap.aplicados = set()
    # Sem dado aplicado e com unidade que falhou: o motivo é o código dominante
    # (revisão e93, achado 12 — antes 'coleta_incompleta', que a tela não traduzia).
    assert service.decidir_status(ap) == ("erro", "falha_download")
    ap.falhas = [{"unidade": "turma", "codigo": "sem_acesso_ao_dado"}]
    assert service.decidir_status(ap) == ("erro", "sem_acesso_ao_dado")
    assert service.decidir_status(ap, falha_no_meio=True) == ("erro", None)
    ap.falhas, ap.em_revisao, ap.retidos_queda = [], 0, 1
    assert service.decidir_status(ap) == ("sem_atualizacao", "queda_retida")
