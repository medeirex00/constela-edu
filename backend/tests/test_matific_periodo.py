"""Matific por período ("Intervalo de datas" no leaderboard).

O relatório mensal/semanal do Matific traz o que cada aluno fez DENTRO do
intervalo impresso na capa. A importação:
  * SOMA os valores ao acumulado anterior ao início do intervalo;
  * data o snapshot na véspera do fim (o limite impresso é exclusivo);
  * na primeira importação nasce uma base ZERADA na véspera do início —
    premiações e evolução do período enxergam exatamente o ganho do mês;
  * reimportar o mesmo período recalcula sobre a mesma base (não dobra);
  * importar um mês antigo (backfill) não rebaixa o estado atual.
"""
from datetime import datetime, time, timedelta

from sqlalchemy import select

from app.models import SnapshotMatific
from app.services.evolucao import _janela
from app.services.perfis_pdf import Pagina, Palavra, PerfilMatific

MARCO_INICIO = "2026-03-01"
MARCO_FIM = "2026-04-01"


def P(texto: str, x0: float, topo: float) -> Palavra:
    return Palavra(texto=texto, x0=x0, x1=x0 + 30.0, topo=topo)


def _paginas_leaderboard() -> list[Pagina]:
    """Réplica anonimizada do leaderboard escolar com intervalo de datas."""
    palavras = [
        P("Matific", 40, 20),
        P("Intervalo", 40, 40), P("de", 90, 40), P("datas", 105, 40),
        P("2026-03-01-2026-04-01", 140, 40),
        # cabeçalho com rótulos empilhados
        P("Atividades", 299.9, 100), P("Pontuação", 384.9, 100),
        P("Série", 51.7, 108), P("Aluno", 84.7, 108), P("Turma", 191.2, 108),
        P("Estrelas", 459.9, 108),
        P("Finalizadas", 299.9, 116), P("média", 384.9, 116),
        # registro (turma sanduíche)
        P("3", 191.2, 140), P("ANO", 199.5, 140), P("A", 224.2, 140),
        P("MANHA", 232.5, 140),
        P("3", 51.7, 148), P("ANA", 84.7, 148), P("B", 142.5, 148),
        P("50", 299.9, 148), P("4.10", 384.9, 148), P("200", 459.9, 148),
        P("ANUAL", 191.2, 156), P("(123)", 225.7, 156),
    ]
    return [Pagina(numero=1, palavras=palavras)]


def _confirmar(cliente, escola_id, aluno_id, dados, com_periodo=True):
    corpo = {
        "plataforma": "matific", "formato": "resumo", "tipo": "pdf",
        "linhas": [{"nome": "Ana B", "dados": dados, "aluno_id": aluno_id}],
    }
    if com_periodo:
        corpo["periodo_inicio"] = MARCO_INICIO
        corpo["periodo_fim"] = MARCO_FIM
    resposta = cliente.post(
        f"/api/v1/escolas/{escola_id}/importacoes/confirmar", json=corpo)
    assert resposta.status_code == 200, resposta.text
    return resposta.json()


def _snapshots(db, aluno_id):
    return db.execute(
        select(SnapshotMatific)
        .where(SnapshotMatific.aluno_id == aluno_id)
        .order_by(SnapshotMatific.data_referencia, SnapshotMatific.id)
    ).scalars().all()


# --- Parser -----------------------------------------------------------------

def test_parser_extrai_intervalo_de_datas():
    analise = PerfilMatific().analisar(_paginas_leaderboard())
    assert analise.periodo_inicio == MARCO_INICIO
    assert analise.periodo_fim == MARCO_FIM
    assert "01/03/2026 a 01/04/2026" in analise.mensagem_deteccao
    assert analise.linhas[0].dados["estrelas"] == 200


def test_parser_nao_perde_aluno_com_nome_todo_quebrado():
    """Nome comprido quebra INTEIRO nas linhas vizinhas ("CHRISTOPHER" acima,
    "D" abaixo) e a linha do registro fica só com números — no PDF real esse
    aluno sumia (83 de 84) e a soma de estrelas não batia com a capa."""
    paginas = _paginas_leaderboard()
    paginas[0].palavras += [
        # linha de cima: primeiro nome + metade da turma
        P("CHRISTOPHER", 84.7, 180), P("4", 191.2, 180), P("ANO", 199.5, 180),
        P("B", 224.2, 180), P("MANHA", 232.5, 180),
        # linha do registro: SÓ números (série + métricas)
        P("4", 51.7, 188), P("7", 299.9, 188), P("2.14", 384.9, 188),
        P("15", 459.9, 188),
        # linha de baixo: resto do nome + resto da turma
        P("D", 84.7, 196), P("ANUAL", 191.2, 196), P("(456)", 225.7, 196),
    ]
    analise = PerfilMatific().analisar(paginas)
    nomes = [l.nome for l in analise.linhas]
    assert "CHRISTOPHER D" in nomes
    chris = next(l for l in analise.linhas if l.nome == "CHRISTOPHER D")
    assert chris.dados["estrelas"] == 15
    assert chris.dados["turma_relatorio"] == "4 ANO B MANHA ANUAL"


def test_parser_sem_intervalo_segue_normal():
    paginas = _paginas_leaderboard()
    paginas[0].palavras = [p for p in paginas[0].palavras
                           if "2026-0" not in p.texto and p.texto != "Intervalo"]
    analise = PerfilMatific().analisar(paginas)
    assert analise.periodo_inicio == ""
    assert analise.periodo_fim == ""


def _com_intervalo(rotulo: str, com_rodape: bool = True) -> list[Pagina]:
    """Fixture com o campo "Intervalo de datas" preenchido por um PRESET."""
    paginas = _paginas_leaderboard()
    paginas[0].palavras = [
        p for p in paginas[0].palavras
        if p.texto not in ("Intervalo", "de", "datas", "2026-03-01-2026-04-01")
    ]
    extras = [Palavra("Intervalo", 40, 40, 40), ]
    # monta "Intervalo de datas <rotulo>" palavra a palavra
    extras = []
    x = 40.0
    for token in ["Intervalo", "de", "datas"] + rotulo.split():
        extras.append(P(token, x, 40))
        x += 55
    if com_rodape:
        extras += [P("08/07/2026,", 40, 700), P("01:13", 110, 700), P("Matific", 150, 700)]
    paginas[0].palavras += extras
    return paginas


def test_preset_ultima_semana_resolvido_pela_data_de_impressao():
    """"Última semana" vira um período real, ancorado na data de impressão do
    rodapé. A semana do Matific começa no DOMINGO (help.br.matific.com):
    impressão em 08/07/2026 (quarta) → última semana = 28/06 a 05/07."""
    analise = PerfilMatific().analisar(_com_intervalo("Última semana"))
    assert analise.periodo_inicio == "2026-06-28"
    assert analise.periodo_fim == "2026-07-05"
    assert "resolvido pela data de impressão" in analise.mensagem_deteccao


def test_preset_esta_semana_vai_do_domingo_ao_dia_da_impressao():
    analise = PerfilMatific().analisar(_com_intervalo("Esta semana"))
    assert analise.periodo_inicio == "2026-07-05"     # domingo desta semana
    assert analise.periodo_fim == "2026-07-09"        # impressão (08/07) + 1


def test_intervalo_ilegivel_avisa_que_vira_acumulado():
    """Datas presentes mas degeneradas (início == fim) nunca degradam em
    SILÊNCIO — sem período a confirmação SUBSTITUI o acumulado."""
    paginas = _paginas_leaderboard()
    for p in paginas[0].palavras:
        if p.texto == "2026-03-01-2026-04-01":
            paginas[0].palavras[paginas[0].palavras.index(p)] = (
                P("2026-03-01-2026-03-01", p.x0, p.topo))
            break
    analise = PerfilMatific().analisar(paginas)
    assert analise.periodo_inicio == ""
    assert "TOTAL acumulado" in analise.mensagem_deteccao


def test_preset_ano_academico_vira_acumulado_com_aviso():
    """"Ano acadêmico atual" (e "Olimpíadas...") não tem datas: os valores são
    tratados como TOTAL acumulado e a prévia orienta a usar o intervalo
    personalizado para rankings por período."""
    analise = PerfilMatific().analisar(_com_intervalo("Ano acadêmico atual"))
    assert analise.periodo_inicio == ""
    assert "TOTAL acumulado" in analise.mensagem_deteccao
    assert "Personalizar intervalo" in analise.mensagem_deteccao

    olimpiadas = PerfilMatific().analisar(_com_intervalo("Olimpíadas Matific 2026"))
    assert olimpiadas.periodo_inicio == ""
    assert "TOTAL acumulado" in olimpiadas.mensagem_deteccao


def test_criar_escola_recusa_nome_repetido(db):
    """POST /escolas duplicado criaria um segundo "inquilino" indistinguível
    no seletor — recusa com 409 (clique duplo no botão da rede nunca dobra)."""
    from fastapi.testclient import TestClient

    from app.core.security import hash_senha
    from app.main import app
    from app.models import Usuario

    db.add(Usuario(escola_id=None, nome="Root", email="root@teste.local",
                   senha_hash=hash_senha("s3nh4root"), cargo="admin",
                   is_global=True))
    db.commit()
    cliente = TestClient(app)
    resposta = cliente.post("/api/v1/auth/login",
                            data={"username": "root@teste.local",
                                  "password": "s3nh4root"})
    cliente.headers["Authorization"] = f"Bearer {resposta.json()['access_token']}"

    primeira = cliente.post("/api/v1/escolas", json={"nome": "DEBORA PILON"})
    assert primeira.status_code == 201
    repetida = cliente.post("/api/v1/escolas", json={"nome": "Debora Pilon"})
    assert repetida.status_code == 409


# --- Ranking de Matemática -----------------------------------------------------

def test_ranking_matematica_por_periodo(cliente, db, escola_completa):
    """Estrelas/atividades APENAS do período — o espelho do Ranking de
    Leitura para os melhores da matemática."""
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    joao = escola_completa["alunos"][1]

    def importar(aluno, inicio, fim, ativ, estrelas):
        corpo = {
            "plataforma": "matific", "formato": "resumo", "tipo": "pdf",
            "periodo_inicio": inicio, "periodo_fim": fim,
            "linhas": [{"nome": aluno.nome, "aluno_id": aluno.id,
                        "dados": {"atividades": ativ, "pontuacao_media": 4.0,
                                  "estrelas": estrelas}}],
        }
        r = cliente.post(f"/api/v1/escolas/{escola_id}/importacoes/confirmar", json=corpo)
        assert r.status_code == 200, r.text

    importar(ana, "2026-03-01", "2026-04-01", 50, 200)
    importar(ana, "2026-04-01", "2026-05-01", 30, 90)
    importar(joao, "2026-04-01", "2026-05-01", 40, 150)

    marco = cliente.get(f"/api/v1/escolas/{escola_id}/ranking/matematica"
                        "?periodo=personalizado&inicio=2026-03-01&fim=2026-03-31").json()
    assert [i["nome"] for i in marco] == [ana.nome]      # só a Ana jogou em março
    assert marco[0]["estrelas"] == 200

    abril = cliente.get(f"/api/v1/escolas/{escola_id}/ranking/matematica"
                        "?periodo=personalizado&inicio=2026-04-01&fim=2026-04-30").json()
    assert [i["nome"] for i in abril] == [joao.nome, ana.nome]  # João 150 > Ana 90
    assert (abril[0]["estrelas"], abril[1]["estrelas"]) == (150, 90)

    tudo = cliente.get(f"/api/v1/escolas/{escola_id}/ranking/matematica?periodo=tudo").json()
    assert tudo[0]["nome"] == ana.nome                   # 290 acumuladas
    assert tudo[0]["estrelas"] == 290
    assert tudo[0]["posicao"] == 1


# --- Importação por período ---------------------------------------------------

def test_primeira_importacao_cria_base_zero_e_data_no_fim_do_periodo(
        cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    _confirmar(cliente, escola_id, ana.id,
               {"atividades": 50, "pontuacao_media": 4.1, "estrelas": 200})

    snaps = _snapshots(db, ana.id)
    assert len(snaps) == 2
    base, marco = snaps
    assert (base.atividades, base.estrelas) == (0, 0)
    assert base.data_referencia == datetime(2026, 2, 28, 23, 59, 59)
    assert marco.data_referencia == datetime(2026, 3, 31, 23, 59, 59)
    assert (marco.atividades, marco.estrelas) == (50, 200)
    assert marco.pontuacao_media == 4.1

    # Premiações/evolução de MARÇO enxergam exatamente o ganho do relatório.
    atual, base_j = _janela(snaps, datetime(2026, 3, 1),
                            datetime(2026, 3, 31, 23, 59, 59),
                            base_no_periodo=True)
    assert atual.estrelas - base_j.estrelas == 200
    # E ABRIL não herda nada de março.
    atual_abr, base_abr = _janela(snaps, datetime(2026, 4, 1),
                                  datetime(2026, 4, 30), base_no_periodo=True)
    assert atual_abr.estrelas - base_abr.estrelas == 0


def test_mes_seguinte_soma_ao_acumulado_com_media_ponderada(
        cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    _confirmar(cliente, escola_id, ana.id,
               {"atividades": 50, "pontuacao_media": 4.0, "estrelas": 200})

    corpo = {
        "plataforma": "matific", "formato": "resumo", "tipo": "pdf",
        "periodo_inicio": "2026-04-01", "periodo_fim": "2026-05-01",
        "linhas": [{"nome": "Ana B", "aluno_id": ana.id,
                    "dados": {"atividades": 30, "pontuacao_media": 3.0,
                              "estrelas": 90}}],
    }
    resposta = cliente.post(
        f"/api/v1/escolas/{escola_id}/importacoes/confirmar", json=corpo)
    assert resposta.status_code == 200, resposta.text

    atual = _snapshots(db, ana.id)[-1]
    assert atual.data_referencia == datetime(2026, 4, 30, 23, 59, 59)
    assert atual.atividades == 80
    assert atual.estrelas == 290
    assert atual.pontuacao_media == round((4.0 * 50 + 3.0 * 30) / 80, 4)

    # Abril isolado = só o ganho de abril.
    atual_abr, base_abr = _janela(_snapshots(db, ana.id),
                                  datetime(2026, 4, 1),
                                  datetime(2026, 4, 30, 23, 59, 59),
                                  base_no_periodo=True)
    assert atual_abr.estrelas - base_abr.estrelas == 90


def test_reimportar_o_mesmo_periodo_nao_soma_duas_vezes(
        cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    dados = {"atividades": 50, "pontuacao_media": 4.1, "estrelas": 200}
    _confirmar(cliente, escola_id, ana.id, dados)
    resultado = _confirmar(cliente, escola_id, ana.id,
                           {**dados, "estrelas": 210})  # correção do relatório

    atual = _snapshots(db, ana.id)[-1]
    assert atual.estrelas == 210          # recalculado, não 200+210
    assert atual.atividades == 50
    assert any("recalculados" in a for a in resultado["avisos"])


def test_backfill_de_mes_antigo_nao_rebaixa_o_estado_atual(
        cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    # Estado atual pré-existente (import antigo, acumulado da plataforma).
    _confirmar(cliente, escola_id, ana.id,
               {"atividades": 300, "pontuacao_media": 4.5, "estrelas": 900},
               com_periodo=False)

    # Chega o relatório de MARÇO (período anterior ao estado atual).
    resultado = _confirmar(cliente, escola_id, ana.id,
                           {"atividades": 50, "pontuacao_media": 4.0,
                            "estrelas": 200})
    assert any("histórico" in a for a in resultado["avisos"])

    from app.services.scoring import _snapshots_atuais
    atual = _snapshots_atuais(db, escola_id, SnapshotMatific)[ana.id]
    assert atual.estrelas == 900          # o acumulado segue mandando
    # Mas o histórico de março existe para evolução/premiações do mês.
    marco = [s for s in _snapshots(db, ana.id)
             if s.data_referencia == datetime(2026, 3, 31, 23, 59, 59)]
    assert marco and marco[0].estrelas == 200


def test_acumulado_dentro_do_intervalo_nao_derruba_o_estado(
        cliente, db, escola_completa):
    """Migração do fluxo antigo: o acumulado all-time foi importado DENTRO do
    mês corrente; o leaderboard do mesmo mês chega depois. O total não pode
    despencar para os valores do mês (era 500→30 antes do piso). O período é o
    MÊS ATUAL derivado do relógio — antes eram datas fixas de jul/2026, o que
    fazia o teste falhar quando rodado fora daquele mês."""
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    _confirmar(cliente, escola_id, ana.id,
               {"atividades": 500, "pontuacao_media": 4.5, "estrelas": 900},
               com_periodo=False)                      # datado AGORA (mês corrente)

    # O período é o MÊS do acumulado — derivado da DATA que o import atribuiu ao
    # snapshot (não de um relógio à parte). Antes, datas fixas de jul/2026 +
    # a virada de fuso (23h em Brasília = dia seguinte em UTC) faziam o teste
    # falhar na última noite do mês.
    from app.services.scoring import _snapshots_atuais
    ref = _snapshots_atuais(db, escola_id, SnapshotMatific)[ana.id].data_referencia
    mes_inicio = ref.date().replace(day=1)
    prox_mes = (mes_inicio.replace(year=mes_inicio.year + 1, month=1)
                if mes_inicio.month == 12
                else mes_inicio.replace(month=mes_inicio.month + 1))
    corpo = {
        "plataforma": "matific", "formato": "resumo", "tipo": "pdf",
        "periodo_inicio": mes_inicio.isoformat(), "periodo_fim": prox_mes.isoformat(),
        "linhas": [{"nome": "Ana B", "aluno_id": ana.id,
                    "dados": {"atividades": 30, "pontuacao_media": 3.0,
                              "estrelas": 90}}],
    }
    resposta = cliente.post(
        f"/api/v1/escolas/{escola_id}/importacoes/confirmar", json=corpo)
    assert resposta.status_code == 200, resposta.text
    assert any("preservado" in a for a in resposta.json()["avisos"])

    atual = _snapshots_atuais(db, escola_id, SnapshotMatific)[ana.id]
    assert (atual.atividades, atual.estrelas) == (500, 900)  # nada despencou

    # E o delta do MÊS CORRENTE é exatamente o ganho do relatório (30/90),
    # porque o snapshot-base da véspera vale (novo − ganhos), não zero.
    snaps = _snapshots(db, ana.id)
    atual_j, base_j = _janela(snaps,
                              datetime.combine(mes_inicio, time.min),
                              datetime.combine(prox_mes, time.min) - timedelta(seconds=1),
                              base_no_periodo=True)
    assert atual_j.atividades - base_j.atividades == 30
    assert atual_j.estrelas - base_j.estrelas == 90


def test_periodo_em_andamento_nao_gera_data_futura_nem_engole_edicao_manual(
        cliente, db, escola_completa):
    """Importar o mês CORRENTE não pode datar o snapshot no futuro — uma
    edição manual feita depois ficaria permanentemente invisível."""
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    corpo = {
        "plataforma": "matific", "formato": "resumo", "tipo": "pdf",
        "periodo_inicio": "2026-07-01", "periodo_fim": "2026-08-01",
        "linhas": [{"nome": "Ana B", "aluno_id": ana.id,
                    "dados": {"atividades": 30, "pontuacao_media": 3.0,
                              "estrelas": 90}}],
    }
    resposta = cliente.post(
        f"/api/v1/escolas/{escola_id}/importacoes/confirmar", json=corpo)
    assert resposta.status_code == 200, resposta.text

    from datetime import timezone
    agora = datetime.now(timezone.utc).replace(tzinfo=None)
    atual = _snapshots(db, ana.id)[-1]
    assert atual.data_referencia <= agora            # nunca no futuro

    edicao = cliente.put(f"/api/v1/escolas/{escola_id}/matific/{ana.id}", json={
        "atividades": 77, "estrelas": 200, "pontuacao_media": 4.0,
        "motivo": "correção manual"})
    assert edicao.status_code == 200, edicao.text
    from app.services.scoring import _snapshots_atuais
    atual = _snapshots_atuais(db, escola_id, SnapshotMatific)[ana.id]
    assert atual.atividades == 77                    # a edição manual vale


def test_reimportar_mes_seguinte_incorpora_backfill(cliente, db, escola_completa):
    """Backfill fora de ordem: o mês antigo entra no histórico e o aviso manda
    reimportar os meses seguintes — reimportar MAIO após o backfill de ABRIL
    incorpora abril ao acumulado."""
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]

    def importar(inicio, fim, ativ, estrelas):
        corpo = {
            "plataforma": "matific", "formato": "resumo", "tipo": "pdf",
            "periodo_inicio": inicio, "periodo_fim": fim,
            "linhas": [{"nome": "Ana B", "aluno_id": ana.id,
                        "dados": {"atividades": ativ, "pontuacao_media": 3.0,
                                  "estrelas": estrelas}}],
        }
        resposta = cliente.post(
            f"/api/v1/escolas/{escola_id}/importacoes/confirmar", json=corpo)
        assert resposta.status_code == 200, resposta.text
        return resposta.json()

    importar("2026-05-01", "2026-06-01", 40, 120)          # maio primeiro
    fora_de_ordem = importar("2026-04-01", "2026-05-01", 30, 90)  # abril depois
    assert any("reimporte os meses seguintes" in a
               for a in fora_de_ordem["avisos"])

    importar("2026-05-01", "2026-06-01", 40, 120)          # reimporta maio
    from app.services.scoring import _snapshots_atuais
    atual = _snapshots_atuais(db, escola_id, SnapshotMatific)[ana.id]
    assert (atual.atividades, atual.estrelas) == (70, 210)  # abril incorporado


def test_evolucao_ordena_por_data_apos_backfill(cliente, db, escola_completa):
    """O backfill grava um mês antigo com id MAIOR: a série da evolução deve
    vir por data_referencia, senão o passado viraria o "estado atual"."""
    from app.services.evolucao import _series_por_aluno

    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    _confirmar(cliente, escola_id, ana.id,
               {"atividades": 300, "pontuacao_media": 4.5, "estrelas": 900},
               com_periodo=False)                     # acumulado datado AGORA
    _confirmar(cliente, escola_id, ana.id,
               {"atividades": 50, "pontuacao_media": 4.0, "estrelas": 200})
    serie = _series_por_aluno(db, escola_id, SnapshotMatific)[ana.id]
    datas = [s.data_referencia for s in serie]
    assert datas == sorted(datas)                     # cronológica
    # "atual" de uma janela até HOJE é o acumulado, não o mês backfillado.
    atual, _ = _janela(serie, datetime(2026, 6, 1), datetime(2026, 12, 31))
    assert atual.estrelas == 900


def test_sem_periodo_mantem_a_substituicao_antiga(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    _confirmar(cliente, escola_id, ana.id,
               {"atividades": 10, "pontuacao_media": 3.0, "estrelas": 30},
               com_periodo=False)
    _confirmar(cliente, escola_id, ana.id,
               {"atividades": 25, "pontuacao_media": 3.5, "estrelas": 80},
               com_periodo=False)
    atual = _snapshots(db, ana.id)[-1]
    assert (atual.atividades, atual.estrelas) == (25, 80)  # substitui, não soma
