"""Relatório por Período — o período PEDIDO é a referência; a cobertura das
COLETAS é declarada, nunca confundida com ele.

CASO REAL (escola 17, set/2026). Pedido: 01/09 → 30/09. A primeira coleta do
Elefante daquela escola foi em 22/09 16:53 UTC (13:53 em Brasília) e a última
de setembro em 30/09 10:58 UTC (07:58). As questões do Elefante só existem como
contador ACUMULADO (vitalício: a sync pede LIFETIME) no retrato, e nenhuma
tabela guarda questão datada — então 01/09 → 21/09 NÃO é reconstruível.

O relatório antigo publicava o ganho 22/09 → 30/09 sob o rótulo do mês e dizia
que o intervalo "pode ser mais largo que o período pedido" — era mais
ESTREITO. Um aluno com uma única coleta no mês aparecia com 0/0. A janela (dias
de Brasília) era comparada com o instante da coleta em UTC. E a coleta noturna
da agenda (00:05–00:50 em Brasília, medindo o dia ANTERIOR) fazia setembro sair
com um dia trocado: 31/08 dentro, 30/09 fora.

Os instantes de coleta aqui estão em UTC, como a sync grava
(``importacoes.confirmar``: ``datetime.now(timezone.utc)``). 00:10 em Brasília
= 03:10 UTC. Dados sintéticos.
"""
from __future__ import annotations

from datetime import date, datetime

import pytest

from app.models import Importacao, SnapshotElefante
from app.services import matific_destaque
from app.services import relatorios_periodo as rp
from tests.test_relatorios_periodo import _snap_matific

HOJE_OUT = date(2026, 10, 6)
ROTA = "/api/v1/escolas/{eid}/relatorios/periodo"


def _snap_elefante(db, escola_id, aluno_id, quando, tentativas, acertos):
    """Retrato como a sync grava: a importação nasce no MESMO instante da coleta
    (o ``created_at`` padrão seria "agora", e a regra de valores reescritos no
    mesmo dia faria o teste depender do relógio)."""
    imp = Importacao(escola_id=escola_id, usuario_id=None, plataforma="elefante",
                     tipo="seed", arquivo_original=None, qtd_alunos=0, qtd_erros=0,
                     tempo_ms=0, status="concluida", created_at=quando)
    db.add(imp)
    db.flush()
    snap = SnapshotElefante(escola_id=escola_id, aluno_id=aluno_id, importacao_id=imp.id,
                            data_referencia=quando, livros_unicos=0, tempo_leitura_min=0,
                            questoes_tentativas=tentativas, questoes_acertos=acertos,
                            livros_por_nivel={})
    db.add(snap)
    db.flush()
    return snap


def _gerar(db, escola_id, **kw):
    kw.setdefault("preset", "mes_anterior")
    kw.setdefault("plataformas", ("elefante",))
    kw.setdefault("hoje", HOJE_OUT)
    return rp.gerar(db, escola_id, **kw)


def _ids(escola_completa):
    return (escola_completa["escola"].id,
            [a.id for a in escola_completa["alunos"]])


def _noite(dia: int, mes: int = 9, hora_utc: int = 3, minuto: int = 10) -> datetime:
    """A coleta da agenda: 00:10 em Brasília (03:10 UTC) do dia dado — mede o
    dia ANTERIOR."""
    return datetime(2026, mes, dia, hora_utc, minuto)


# ------------------------------------------------------- reprodução do caso real
def test_reproducao_setembro_pedido_com_coletas_so_desde_22_09(db, escola_completa):
    """O número só cobre 22/09 13:53 → 30/09 07:58 (Brasília). Ele não pode
    sair como "setembro": a cobertura é declarada PARCIAL, com o período pedido
    e o disponível lado a lado — e com o PORQUÊ de cada lado."""
    eid, (a, *_) = _ids(escola_completa)
    _snap_elefante(db, eid, a, datetime(2026, 9, 22, 16, 53, 12), 100, 80)
    _snap_elefante(db, eid, a, datetime(2026, 9, 30, 10, 58, 22), 130, 101)

    ele = _gerar(db, eid)["elefante"]

    cob = ele["cobertura_questoes"]
    assert (cob["periodo_inicio"], cob["periodo_fim"]) == ("2026-09-01", "2026-09-30")
    assert cob["coleta_inicio"].startswith("2026-09-22T16:53")
    assert cob["coleta_fim"].startswith("2026-09-30T10:58")
    assert cob["status"] == "parcial" and cob["completa"] is False
    assert cob["inicio_coberto"] is False          # 01/09 → 22/09 não está na conta
    assert cob["fim_coberto"] is False             # 30/09 depois das 07:58 também não
    assert (cob["alunos_sem_inicio"], cob["alunos_sem_fim"]) == (1, 1)
    # o valor é o que a cobertura DISPONÍVEL permite — e só ele
    assert (ele["questoes_tentativas"], ele["questoes_acertos"]) == (30, 21)
    # a primeira coleta já trazia 100 tentativas acumuladas (de todas as épocas):
    # o histórico EXISTE na plataforma, só não tem data no contador
    assert cob["acumulado_na_primeira_coleta"] == 100
    # a observação antiga dizia só "mais largo"; aqui o intervalo é mais estreito
    assert "mais estreito" in ele["janela_efetiva_questoes"]["observacao"]


# ------------------------------------------------------------ 1. setembro completo
def test_setembro_completo_com_a_agenda_noturna(db, escola_completa):
    """A coleta das 00:10 de 01/09 mede o fim de 31/08 (= o início de setembro)
    e a de 01/10 mede o fim de 30/09. Setembro = 470 − 130 = 340 — não o
    300 de antes (31/08..29/09)."""
    eid, (a, *_) = _ids(escola_completa)
    _snap_elefante(db, eid, a, _noite(31, 8), 100, 80)
    _snap_elefante(db, eid, a, _noite(1), 130, 100)
    _snap_elefante(db, eid, a, _noite(30), 400, 300)
    _snap_elefante(db, eid, a, _noite(1, 10), 470, 350)
    ele = _gerar(db, eid)["elefante"]
    cob = ele["cobertura_questoes"]
    assert (ele["questoes_tentativas"], ele["questoes_acertos"]) == (340, 250)
    assert cob["status"] == "completa" and cob["completa"] is True
    assert cob["inicio_coberto"] and cob["fim_coberto"]
    assert cob["inclui_antes_do_inicio"] is False
    assert cob["coleta_inicio"].startswith("2026-09-01T03:10")
    assert cob["coleta_fim"].startswith("2026-10-01T03:10")


def test_base_muito_anterior_ao_inicio_e_ampliada_nao_completa(db, escola_completa):
    """Sem coleta perto de 01/09, a base de 15/08 INCLUI duas semanas de agosto:
    o número não é "do período" — status ampliada, com a antecedência."""
    eid, (a, *_) = _ids(escola_completa)
    _snap_elefante(db, eid, a, datetime(2026, 8, 15, 12, 0), 50, 40)
    _snap_elefante(db, eid, a, _noite(1, 10), 90, 70)
    ele = _gerar(db, eid)["elefante"]
    cob = ele["cobertura_questoes"]
    assert cob["status"] == "ampliada" and cob["completa"] is False
    assert cob["inclui_antes_do_inicio"] is True and cob["alunos_ampliados"] == 1
    assert cob["antecedencia_max_horas"] == 16 * 24 + 15      # 15/08 09:00 → 01/09 00:00 (BRT)
    assert (ele["questoes_tentativas"], ele["questoes_acertos"]) == (40, 30)


# ------------------------------------------------------------------ 2. uma semana
def test_uma_semana_22_a_30_de_setembro(db, escola_completa):
    eid, (a, *_) = _ids(escola_completa)
    _snap_elefante(db, eid, a, _noite(22), 100, 80)     # mede o início de 22/09
    _snap_elefante(db, eid, a, _noite(1, 10), 130, 101)  # mede o fim de 30/09
    ele = _gerar(db, eid, preset="personalizado",
                 inicio=date(2026, 9, 22), fim=date(2026, 9, 30))["elefante"]
    cob = ele["cobertura_questoes"]
    assert (cob["periodo_inicio"], cob["periodo_fim"]) == ("2026-09-22", "2026-09-30")
    assert cob["status"] == "completa"
    assert (ele["questoes_tentativas"], ele["questoes_acertos"]) == (30, 21)


# ------------------------------------------------------- 3. período personalizado
def test_periodo_personalizado_5_a_18_de_setembro(db, escola_completa):
    eid, (a, *_) = _ids(escola_completa)
    _snap_elefante(db, eid, a, _noite(4), 5, 2)         # antes da tolerância: ignorado
    _snap_elefante(db, eid, a, _noite(5), 10, 5)        # mede o início de 05/09
    _snap_elefante(db, eid, a, _noite(10), 20, 12)
    _snap_elefante(db, eid, a, _noite(19), 35, 20)      # mede o fim de 18/09
    _snap_elefante(db, eid, a, datetime(2026, 9, 19, 15, 0), 99, 90)   # depois: fora
    ele = _gerar(db, eid, preset="personalizado",
                 inicio=date(2026, 9, 5), fim=date(2026, 9, 18))["elefante"]
    assert ele["cobertura_questoes"]["status"] == "completa"
    assert (ele["questoes_tentativas"], ele["questoes_acertos"]) == (25, 15)


# --------------------------------------------------------------- 4. mês atual
def test_mes_atual_vai_ate_a_coleta_de_hoje(db, escola_completa):
    """Mês em andamento: o fim efetivo é HOJE e vale a coleta mais recente."""
    eid, (a, *_) = _ids(escola_completa)
    _snap_elefante(db, eid, a, _noite(1, 10), 100, 80)
    _snap_elefante(db, eid, a, _noite(6, 10), 112, 90)
    ele = _gerar(db, eid, preset="mes")["elefante"]
    cob = ele["cobertura_questoes"]
    assert (cob["periodo_inicio"], cob["periodo_fim"]) == ("2026-10-01", "2026-10-31")
    assert cob["periodo_fim_efetivo"] == "2026-10-06" and cob["em_andamento"] is True
    assert cob["status"] == "completa"
    assert (ele["questoes_tentativas"], ele["questoes_acertos"]) == (12, 10)


def test_mes_atual_sem_coleta_de_hoje_e_parcial_no_fim(db, escola_completa):
    eid, (a, *_) = _ids(escola_completa)
    _snap_elefante(db, eid, a, _noite(1, 10), 100, 80)
    _snap_elefante(db, eid, a, _noite(3, 10), 105, 84)      # a agenda parou
    cob = _gerar(db, eid, preset="mes")["elefante"]["cobertura_questoes"]
    assert cob["fim_coberto"] is False and cob["status"] == "parcial"


def test_hoje_com_so_a_coleta_da_meia_noite_nao_tem_numero(db, escola_completa):
    """A coleta das 00:10 de hoje mede ONTEM. "Hoje" não pode sair com a
    atividade de ontem: não há diferença a medir ainda."""
    eid, (a, *_) = _ids(escola_completa)
    _snap_elefante(db, eid, a, _noite(5, 10), 100, 80)
    _snap_elefante(db, eid, a, _noite(6, 10), 160, 120)
    ele = _gerar(db, eid, preset="hoje")["elefante"]
    assert ele["questoes_tentativas"] is None
    assert ele["cobertura_questoes"]["status"] == "sem_intervalo"


def test_ontem_e_exatamente_o_dia_de_ontem(db, escola_completa):
    eid, (a, *_) = _ids(escola_completa)
    _snap_elefante(db, eid, a, _noite(5, 10), 100, 80)      # mede o início de 05/10
    _snap_elefante(db, eid, a, _noite(6, 10), 160, 120)     # mede o fim de 05/10
    ele = _gerar(db, eid, preset="ontem")["elefante"]
    assert (ele["questoes_tentativas"], ele["questoes_acertos"]) == (60, 40)
    assert ele["cobertura_questoes"]["status"] == "completa"


# ---------------------------------------------------------- 5. mês anterior
@pytest.mark.parametrize("hoje", [date(2026, 10, 1), date(2026, 10, 15), date(2026, 10, 31)])
def test_mes_anterior_de_qualquer_dia_de_outubro_e_setembro_inteiro(hoje):
    j = rp.resolver_janela("mes_anterior", 2026, hoje=hoje)
    assert (j.inicio, j.fim) == (datetime(2026, 9, 1),
                                 datetime(2026, 9, 30, 23, 59, 59, 999999))


# ------------------------------------------------ 6. sem cobertura suficiente
def test_uma_unica_coleta_no_mes_nao_vira_zero(db, escola_completa):
    """Uma coleta só, sem base: não há intervalo medido. 0/0 diria "não
    respondeu nada" — o certo é "não dá para medir"."""
    eid, (a, *_) = _ids(escola_completa)
    _snap_elefante(db, eid, a, datetime(2026, 9, 21, 14, 14), 500, 400)
    ele = _gerar(db, eid)["elefante"]
    assert ele["questoes_tentativas"] is None and ele["questoes_acertos"] is None
    cob = ele["cobertura_questoes"]
    assert cob["status"] == "sem_intervalo" and cob["alunos_sem_intervalo"] == 1


def test_coleta_unica_de_um_aluno_fica_fora_da_soma_dos_outros(db, escola_completa):
    eid, (a, b, *_) = _ids(escola_completa)
    _snap_elefante(db, eid, a, _noite(1), 10, 5)
    _snap_elefante(db, eid, a, _noite(1, 10), 20, 10)
    _snap_elefante(db, eid, b, datetime(2026, 9, 15, 12, 0), 500, 400)   # só esta
    ele = _gerar(db, eid)["elefante"]
    cob = ele["cobertura_questoes"]
    assert (ele["questoes_tentativas"], ele["questoes_acertos"]) == (10, 5)
    assert cob["status"] == "parcial"
    assert (cob["alunos_cobertura_completa"], cob["alunos_sem_intervalo"]) == (1, 1)


def test_conta_nova_zerada_na_primeira_coleta_parte_do_zero(db, escola_completa):
    """Contador acumulado em ZERO numa conta nova (sem livro e sem tempo): ele
    também era zero no início. A conta parte do zero — o início está PROVADO."""
    eid, (a, b, *_) = _ids(escola_completa)
    _snap_elefante(db, eid, a, datetime(2026, 9, 22, 16, 53), 0, 0)     # começou no mês
    _snap_elefante(db, eid, a, _noite(1, 10), 18, 12)
    _snap_elefante(db, eid, b, _noite(1, 10), 0, 0)                     # única, zero
    ele = _gerar(db, eid)["elefante"]
    cob = ele["cobertura_questoes"]
    assert (ele["questoes_tentativas"], ele["questoes_acertos"]) == (18, 12)
    assert cob["status"] == "completa" and cob["alunos_cobertura_completa"] == 2
    assert cob["alunos_sem_intervalo"] == 0


def test_zero_de_questoes_com_livros_contados_nao_prova_nada(db, escola_completa):
    """Os importadores gravam 0 nas questões quando o relatório não traz a
    coluna. Com livros já contados, esse 0 é "desconhecido": o início NÃO está
    coberto (o número é o mesmo; a declaração não pode ser "completa")."""
    eid, (a, *_) = _ids(escola_completa)
    s = _snap_elefante(db, eid, a, datetime(2026, 9, 22, 16, 53), 0, 0)
    s.livros_unicos = 40
    _snap_elefante(db, eid, a, _noite(1, 10), 18, 12)
    db.flush()
    ele = _gerar(db, eid)["elefante"]
    assert ele["questoes_tentativas"] == 18
    cob = ele["cobertura_questoes"]
    assert cob["status"] == "parcial" and cob["inicio_coberto"] is False


def test_mistura_de_alunos_e_contada_por_causa(db, escola_completa):
    eid, (a, b, c) = _ids(escola_completa)
    _snap_elefante(db, eid, a, _noite(1), 10, 5)                         # completa
    _snap_elefante(db, eid, a, _noite(1, 10), 20, 10)
    _snap_elefante(db, eid, b, datetime(2026, 9, 22, 16, 53), 100, 80)   # sem início
    _snap_elefante(db, eid, b, _noite(1, 10), 103, 82)
    _snap_elefante(db, eid, c, _noite(1), 50, 40)                        # sem fim
    _snap_elefante(db, eid, c, _noite(17), 60, 45)
    ele = _gerar(db, eid)["elefante"]
    cob = ele["cobertura_questoes"]
    assert cob["status"] == "parcial"
    assert cob["inicio_coberto"] is False and cob["fim_coberto"] is False
    assert (cob["alunos_cobertura_completa"], cob["alunos_sem_inicio"],
            cob["alunos_sem_fim"], cob["alunos_cobertura_parcial"]) == (1, 1, 1, 2)
    assert cob["coleta_inicio"].startswith("2026-09-01T03:10")
    assert cob["coleta_inicio_mais_tardio"].startswith("2026-09-22T16:53")
    assert cob["coleta_fim_mais_cedo"].startswith("2026-09-17T03:10")
    assert (ele["questoes_tentativas"], ele["questoes_acertos"]) == (23, 12)


# ------------------------------------------------------------------ 7. limites
def test_limite_coleta_exatamente_em_01_09_00h_e_a_medida_do_inicio(db, escola_completa):
    """01/09 00:00 em Brasília = 01/09 03:00 UTC: é a medida exata do começo e
    vence a coleta mais antiga de agosto como base."""
    eid, (a, *_) = _ids(escola_completa)
    _snap_elefante(db, eid, a, datetime(2026, 8, 15, 12, 0), 1, 1)
    _snap_elefante(db, eid, a, datetime(2026, 9, 1, 3, 0), 40, 30)      # 01/09 00:00 BRT
    _snap_elefante(db, eid, a, _noite(1, 10), 70, 50)
    ele = _gerar(db, eid)["elefante"]
    cob = ele["cobertura_questoes"]
    assert cob["status"] == "completa" and cob["inclui_antes_do_inicio"] is False
    assert cob["coleta_inicio"].startswith("2026-09-01T03:00")
    assert (ele["questoes_tentativas"], ele["questoes_acertos"]) == (30, 20)


def test_limite_coleta_pouco_antes_do_inicio_tambem_o_mede(db, escola_completa):
    """31/08 23:59:59 em Brasília está a 1 s do início: é a medida dele."""
    eid, (a, *_) = _ids(escola_completa)
    _snap_elefante(db, eid, a, datetime(2026, 9, 1, 2, 59, 59), 40, 30)
    _snap_elefante(db, eid, a, _noite(1, 10), 70, 50)
    cob = _gerar(db, eid)["elefante"]["cobertura_questoes"]
    assert cob["status"] == "completa" and cob["inclui_antes_do_inicio"] is False


def test_limite_coleta_duas_horas_antes_do_inicio_amplia(db, escola_completa):
    """31/08 22:00 em Brasília: fora da tolerância — o número inclui 2 h de
    agosto, e isso é dito."""
    eid, (a, *_) = _ids(escola_completa)
    _snap_elefante(db, eid, a, datetime(2026, 9, 1, 1, 0), 40, 30)
    _snap_elefante(db, eid, a, _noite(1, 10), 70, 50)
    cob = _gerar(db, eid)["elefante"]["cobertura_questoes"]
    assert cob["status"] == "ampliada" and cob["antecedencia_max_horas"] == 2


def test_limite_ultimo_instante_de_30_09_mede_o_fim(db, escola_completa):
    eid, (a, *_) = _ids(escola_completa)
    _snap_elefante(db, eid, a, _noite(1), 10, 5)
    _snap_elefante(db, eid, a, datetime(2026, 10, 1, 2, 59, 59, 999999), 40, 30)  # 30/09 23:59:59.999999 BRT
    ele = _gerar(db, eid)["elefante"]
    assert ele["questoes_tentativas"] == 30
    assert ele["cobertura_questoes"]["fim_coberto"] is True


def test_limite_01_10_00h_e_a_medida_exata_do_fim(db, escola_completa):
    """01/10 00:00 em Brasília é o ESTADO ao fim de 30/09: mede o fim."""
    eid, (a, *_) = _ids(escola_completa)
    _snap_elefante(db, eid, a, _noite(1), 10, 5)
    _snap_elefante(db, eid, a, datetime(2026, 9, 29, 12, 0), 20, 10)
    _snap_elefante(db, eid, a, datetime(2026, 10, 1, 3, 0), 99, 90)     # 01/10 00:00 BRT
    ele = _gerar(db, eid)["elefante"]
    assert ele["questoes_tentativas"] == 89
    assert ele["cobertura_questoes"]["status"] == "completa"


def test_limite_coleta_bem_depois_do_fim_nao_entra(db, escola_completa):
    """01/10 12:00 em Brasília já é outubro: não mede o fim de setembro. A
    conta vai até a última coleta de setembro — e o fim fica descoberto."""
    eid, (a, *_) = _ids(escola_completa)
    _snap_elefante(db, eid, a, _noite(1), 10, 5)
    _snap_elefante(db, eid, a, datetime(2026, 9, 29, 12, 0), 20, 10)
    _snap_elefante(db, eid, a, datetime(2026, 10, 1, 15, 0), 99, 90)    # 01/10 12:00 BRT
    ele = _gerar(db, eid)["elefante"]
    assert ele["questoes_tentativas"] == 10
    cob = ele["cobertura_questoes"]
    assert cob["fim_coberto"] is False and cob["coleta_fim"].startswith("2026-09-29T12:00")


# -------------------------------------------------------------------- 8. fuso
def test_fuso_coletas_das_22h_de_brasilia_ficam_no_dia_certo(db, escola_completa):
    """30/09 22:00 BRT = 01/10 01:00 UTC — é setembro. 31/08 22:00 BRT = 01/09
    01:00 UTC — é agosto (base anterior ao início). Antes a comparação era com
    o UTC cru e setembro dava 10/5."""
    eid, (a, *_) = _ids(escola_completa)
    _snap_elefante(db, eid, a, datetime(2026, 9, 1, 1, 0), 10, 5)       # 31/08 22:00 BRT
    _snap_elefante(db, eid, a, datetime(2026, 9, 15, 12, 0), 20, 10)
    _snap_elefante(db, eid, a, datetime(2026, 10, 1, 1, 0), 50, 33)     # 30/09 22:00 BRT
    ele = _gerar(db, eid)["elefante"]
    cob = ele["cobertura_questoes"]
    assert (ele["questoes_tentativas"], ele["questoes_acertos"]) == (40, 28)
    assert (cob["periodo_inicio"], cob["periodo_fim"]) == ("2026-09-01", "2026-09-30")
    assert cob["coleta_inicio"].startswith("2026-09-01T01:00")   # pontas em UTC
    assert cob["coleta_fim"].startswith("2026-10-01T01:00")
    # 22:00 está a 2 h de cada borda: fora da tolerância nas duas
    assert cob["inclui_antes_do_inicio"] is True and cob["fim_coberto"] is False


def test_fuso_coleta_de_29_09_as_22h_nao_mede_o_fim(db, escola_completa):
    """30/09 01:00 UTC é 29/09 22:00 em Brasília: o dia 30 inteiro falta."""
    eid, (a, *_) = _ids(escola_completa)
    _snap_elefante(db, eid, a, _noite(1), 10, 8)
    _snap_elefante(db, eid, a, datetime(2026, 9, 30, 1, 0), 40, 30)
    cob = _gerar(db, eid)["elefante"]["cobertura_questoes"]
    assert cob["fim_coberto"] is False and cob["status"] == "parcial"


# ------------------------------------------ a data da coleta é a referência
def test_revisao_reaplicada_no_mesmo_dia_vale_pela_data_da_coleta(db, escola_completa):
    """A coleta das 00:10 de 06/10 foi para a fila de identidade; o gestor
    resolveu às 14:52 (Brasília) do MESMO dia UTC, e a reaplicação criou uma
    linha NOVA com a data congelada e os valores DAQUELA coleta. Ela continua
    medindo o fim de 05/10 — não o meio da tarde de 06/10."""
    eid, (a, *_) = _ids(escola_completa)
    _snap_elefante(db, eid, a, _noite(5, 10), 100, 80)
    resolucao = Importacao(escola_id=eid, usuario_id=None, plataforma="elefante",
                           tipo="texto", arquivo_original=None, qtd_alunos=1,
                           qtd_erros=0, tempo_ms=0, status="concluida",
                           created_at=datetime(2026, 10, 6, 17, 52))
    db.add(resolucao)
    db.flush()
    db.add(SnapshotElefante(escola_id=eid, aluno_id=a, importacao_id=resolucao.id,
                            data_referencia=_noite(6, 10), livros_unicos=0,
                            tempo_leitura_min=0, questoes_tentativas=160,
                            questoes_acertos=120, livros_por_nivel={}))
    db.flush()
    ontem = _gerar(db, eid, preset="ontem")["elefante"]
    assert (ontem["questoes_tentativas"], ontem["questoes_acertos"]) == (60, 40)
    assert ontem["cobertura_questoes"]["status"] == "completa"
    hoje = _gerar(db, eid, preset="hoje")["elefante"]
    assert hoje["questoes_tentativas"] is None
    assert hoje["cobertura_questoes"]["status"] == "sem_intervalo"


def test_relatorio_retroativo_mantem_a_data_do_retrato(db, escola_completa):
    """Relatório de 01/09 importado só em 05/09 (data informada pelo relatório):
    a data do retrato é a verdadeira — ele continua sendo a medida do início."""
    eid, (a, *_) = _ids(escola_completa)
    tardia = Importacao(escola_id=eid, usuario_id=None, plataforma="elefante",
                        tipo="seed", arquivo_original=None, qtd_alunos=0,
                        qtd_erros=0, tempo_ms=0, status="concluida",
                        created_at=datetime(2026, 9, 5, 15, 0))
    db.add(tardia)
    db.flush()
    db.add(SnapshotElefante(escola_id=eid, aluno_id=a, importacao_id=tardia.id,
                            data_referencia=_noite(1), livros_unicos=0,
                            tempo_leitura_min=0, questoes_tentativas=130,
                            questoes_acertos=100, livros_por_nivel={}))
    _snap_elefante(db, eid, a, _noite(1, 10), 470, 350)
    db.flush()
    ele = _gerar(db, eid)["elefante"]
    assert ele["cobertura_questoes"]["status"] == "completa"
    assert (ele["questoes_tentativas"], ele["questoes_acertos"]) == (340, 250)


# ------------------------------------------------ uma execução, duas linhas
def test_uma_coleta_gravada_em_duas_linhas_nao_e_intervalo(db, escola_completa):
    """A sync grava o resumo e, segundos depois, as leituras: duas linhas da
    MESMA coleta. Isso não é um intervalo medido — é uma coleta só."""
    eid, (a, *_) = _ids(escola_completa)
    _snap_elefante(db, eid, a, datetime(2026, 9, 22, 16, 53, 12), 100, 80)
    _snap_elefante(db, eid, a, datetime(2026, 9, 22, 16, 53, 40), 100, 80)
    ele = _gerar(db, eid)["elefante"]
    assert ele["questoes_tentativas"] is None
    assert ele["cobertura_questoes"]["status"] == "sem_intervalo"


def test_na_mesma_execucao_vale_a_linha_do_resumo(db, escola_completa):
    """Duas linhas na mesma execução: a primeira é o resumo (traz as questões
    da plataforma); a segunda, de leituras, COPIA as do retrato mais recente —
    numa revisão reaplicada com data congelada, de outro dia (aqui, 999)."""
    eid, (a, *_) = _ids(escola_completa)
    _snap_elefante(db, eid, a, _noite(1, minuto=5), 10, 5)       # resumo
    _snap_elefante(db, eid, a, _noite(1, minuto=7), 999, 999)    # leituras: cópia
    _snap_elefante(db, eid, a, _noite(1, 10), 40, 30)
    ele = _gerar(db, eid)["elefante"]
    assert (ele["questoes_tentativas"], ele["questoes_acertos"]) == (30, 25)


# ------------------------------------------------- contador que diminui
def test_contador_que_diminui_fica_fora_e_e_declarado(db, escola_completa):
    """Acumulado não diminui. Se diminuiu, a série mistura contas: zerar um
    campo e somar o outro inventaria número."""
    eid, (a, b, *_) = _ids(escola_completa)
    _snap_elefante(db, eid, a, _noite(1), 10, 5)
    _snap_elefante(db, eid, a, _noite(1, 10), 20, 10)
    _snap_elefante(db, eid, b, _noite(1), 500, 100)          # outra conta na ficha
    _snap_elefante(db, eid, b, _noite(1, 10), 50, 300)
    ele = _gerar(db, eid)["elefante"]
    assert (ele["questoes_tentativas"], ele["questoes_acertos"]) == (10, 5)
    cob = ele["cobertura_questoes"]
    assert cob["alunos_contador_regrediu"] == 1 and cob["status"] == "parcial"


# --------------------------------------------- lacuna dentro do período
def test_aluno_coletado_antes_e_depois_mas_nao_no_periodo_e_lacuna(db, escola_completa):
    eid, (a, b, *_) = _ids(escola_completa)
    _snap_elefante(db, eid, a, _noite(1), 10, 5)
    _snap_elefante(db, eid, a, _noite(1, 10), 20, 10)
    _snap_elefante(db, eid, b, datetime(2026, 8, 15, 12, 0), 10, 5)
    _snap_elefante(db, eid, b, datetime(2026, 10, 5, 12, 0), 90, 60)
    ele = _gerar(db, eid)["elefante"]
    cob = ele["cobertura_questoes"]
    assert cob["alunos_sem_coleta_no_periodo"] == 1 and cob["status"] == "parcial"
    assert ele["alunos_sem_retrato"] == 2       # b e o terceiro aluno (sem dado nenhum)


# ------------------------------------------------- "só a coleta do início"
def test_dia_1_so_com_a_coleta_que_mede_o_inicio(db, escola_completa):
    eid, (a, *_) = _ids(escola_completa)
    _snap_elefante(db, eid, a, _noite(30), 90, 70)
    _snap_elefante(db, eid, a, _noite(1, 10), 100, 80)        # mede o início de outubro
    ele = _gerar(db, eid, preset="mes", hoje=date(2026, 10, 1))["elefante"]
    cob = ele["cobertura_questoes"]
    assert ele["questoes_tentativas"] is None
    assert cob["status"] == "sem_intervalo"
    assert cob["alunos_sem_intervalo_so_inicio"] == cob["alunos_sem_intervalo"] == 1


# ------------------------------------------- Matific: só a declaração de cobertura
def test_matific_declara_cobertura_parcial_sem_mudar_o_numero(db, escola_completa):
    """O NÚMERO do Matific é o da função oficial (a mesma das premiações) e não
    muda; o que muda é o relatório não apresentá-lo como mês completo."""
    eid, (a, *_) = _ids(escola_completa)
    s1 = _snap_matific(db, eid, a, datetime(2026, 9, 23, 12, 30), 100, 300)
    s2 = _snap_matific(db, eid, a, datetime(2026, 9, 30, 10, 56), 112, 340)
    mat = _gerar(db, eid, plataformas=("matific",))["matific"]
    janela = rp.resolver_janela("mes_anterior", 2026, hoje=HOJE_OUT)
    oficial = matific_destaque.ganho_no_periodo([s1, s2], janela.inicio, janela.fim, 2026)
    assert (mat["atividades"], mat["estrelas"]) == (oficial.atividades, oficial.estrelas)
    cob = mat["cobertura"]
    assert cob["regra"] == "oficial_matific"
    assert cob["status"] == "parcial" and cob["inicio_coberto"] is False
    assert cob["coleta_inicio"].startswith("2026-09-23T12:30")


def test_matific_nunca_se_declara_completo(db, escola_completa):
    """As bordas da regra oficial não são verificadas no relatório: com base
    anterior ao período, o status é ``regra_oficial`` — nunca "completa"."""
    eid, (a, *_) = _ids(escola_completa)
    _snap_matific(db, eid, a, _noite(31, 8), 100, 300)
    _snap_matific(db, eid, a, _noite(30), 112, 340)
    cob = _gerar(db, eid, plataformas=("matific",))["matific"]["cobertura"]
    assert cob["status"] == "regra_oficial" and cob["completa"] is False


def test_matific_coleta_unica_e_o_zero_oficial(db, escola_completa):
    eid, (a, *_) = _ids(escola_completa)
    _snap_matific(db, eid, a, datetime(2026, 9, 15, 12, 0), 100, 300)
    mat = _gerar(db, eid, plataformas=("matific",))["matific"]
    assert mat["atividades"] == 0                      # a regra oficial, intacta
    cob = mat["cobertura"]
    assert cob["status"] == "sem_intervalo" and cob["alunos_sem_intervalo"] == 1


def test_matific_ano_letivo_parte_de_01_01(db, escola_completa):
    """Janela que começa antes do ano letivo: o contador do Matific é do ano —
    o que veio antes de 01/01 não entra, e isso é dito."""
    eid, (a, *_) = _ids(escola_completa)
    _snap_matific(db, eid, a, datetime(2026, 1, 20, 12, 0), 10, 30)
    _snap_matific(db, eid, a, datetime(2026, 1, 25, 12, 0), 15, 40)
    cob = _gerar(db, eid, plataformas=("matific",), preset="personalizado",
                 inicio=date(2025, 12, 1), fim=date(2026, 1, 31))["matific"]["cobertura"]
    assert cob["inicio_coberto"] is False and cob["status"] == "parcial"


# --------------------------------------------------------------- pela rota HTTP
def test_rota_devolve_a_cobertura(cliente, db, escola_completa):
    eid, (a, *_) = _ids(escola_completa)
    _snap_elefante(db, eid, a, datetime(2026, 9, 22, 16, 53, 12), 100, 80)
    _snap_elefante(db, eid, a, datetime(2026, 9, 30, 10, 58, 22), 130, 101)
    db.commit()
    r = cliente.get(ROTA.format(eid=eid), params={
        "periodo": "personalizado", "inicio": "2026-09-01", "fim": "2026-09-30",
        "plataformas": "elefante"})
    assert r.status_code == 200, r.text
    cob = r.json()["elefante"]["cobertura_questoes"]
    assert cob["status"] == "parcial"
    assert (cob["periodo_inicio"], cob["periodo_fim"]) == ("2026-09-01", "2026-09-30")


# ------------------------------------------------- PDF: a mesma regra da tela
def test_pdf_diz_periodo_pedido_e_cobertura_parcial(db, escola_completa):
    """Vitrine (HTML) e reserva (fpdf) declaram que o número NÃO é o mês."""
    from app.services import relatorios_periodo_pdf as pdf
    from tests.test_relatorios_periodo_pdf import _texto
    eid, (a, *_) = _ids(escola_completa)
    _snap_elefante(db, eid, a, datetime(2026, 9, 22, 16, 53, 12), 100, 80)
    _snap_elefante(db, eid, a, datetime(2026, 9, 30, 10, 58, 22), 130, 101)
    dados = _gerar(db, eid)

    html = pdf.montar_html(dados)
    assert "COBERTURA PARCIAL — o valor NÃO representa o período completo" in html
    assert "Período solicitado: 01/09/2026 a 30/09/2026" in html
    assert "Intervalo medido pelas coletas do Constela: 22/09/2026 13:53 a 30/09/2026 07:58" in html
    assert "não é recuperável" not in html
    assert "a primeira coleta já trazia 100 questões acumuladas" in html
    assert "Questões Respondidas" in html
    assert "pode ser mais largo que o período pedido" not in html

    resumo = {r: (v, f) for r, v, f in pdf.linhas_resumo(dados)}
    assert resumo["Questões tentadas"] == ("30", "COBERTURA PARCIAL - ver nota")

    texto = _texto(pdf._reserva(dados, "#1B2A4A"))
    assert "COBERTURA PARCIAL" in texto
    assert "valor NÃO é o período completo" in texto
    assert "NÃO está na conta" in texto


def test_pdf_sem_intervalo_nao_imprime_zero(db, escola_completa):
    from app.services import relatorios_periodo_pdf as pdf
    eid, (a, *_) = _ids(escola_completa)
    _snap_elefante(db, eid, a, datetime(2026, 9, 21, 14, 14), 500, 400)
    dados = _gerar(db, eid)
    resumo = {r: (v, f) for r, v, f in pdf.linhas_resumo(dados)}
    assert resumo["Questões tentadas"][0] == pdf.SEM_DADO
    assert "sem número para 01/09/2026 a 30/09/2026" in pdf.montar_html(dados)


def test_pdf_matific_parcial_e_zero_oficial(db, escola_completa):
    from app.services import relatorios_periodo_pdf as pdf
    eid, (a, b, *_) = _ids(escola_completa)
    _snap_matific(db, eid, a, datetime(2026, 9, 23, 12, 30), 100, 300)
    _snap_matific(db, eid, a, datetime(2026, 9, 30, 10, 56), 112, 340)
    _snap_matific(db, eid, b, datetime(2026, 9, 15, 12, 0), 50, 100)     # coleta única
    dados = _gerar(db, eid, plataformas=("matific",))
    html = pdf.montar_html(dados)
    assert "Matific: COBERTURA PARCIAL — o valor NÃO representa o período completo" in html
    assert "entram com 0 pela regra oficial" in html
    resumo = {r: (v, f) for r, v, f in pdf.linhas_resumo(dados)}
    assert resumo["Atividades (Matific)"] == ("12", "COBERTURA PARCIAL - ver nota")


def test_pdf_recorte_vazio_nao_inventa_motivo(db, escola_completa):
    from app.services import relatorios_periodo_pdf as pdf
    eid, _ = _ids(escola_completa)
    dados = _gerar(db, eid, escopo="turma", turma_id=999999)
    resumo = {r: (v, f) for r, v, f in pdf.linhas_resumo(dados)}
    assert resumo["Questões tentadas"] == (pdf.SEM_DADO, "nenhum estudante no recorte")


def test_pdf_matific_coleta_unica_nao_imprime_o_zero_oficial(db, escola_completa):
    """O 0 da regra oficial (uma coleta só) continua no payload — mas o papel
    não o imprime como medição."""
    from app.services import relatorios_periodo_pdf as pdf
    eid, (a, *_) = _ids(escola_completa)
    _snap_matific(db, eid, a, datetime(2026, 9, 15, 12, 0), 50, 100)
    dados = _gerar(db, eid, plataformas=("matific",))
    assert dados["matific"]["atividades"] == 0
    resumo = {r: (v, f) for r, v, f in pdf.linhas_resumo(dados)}
    assert resumo["Atividades (Matific)"][0] == pdf.SEM_DADO
    assert resumo["Estrelas (Matific)"][0] == pdf.SEM_DADO
    assert "NÃO quer dizer que não houve atividade" in pdf.montar_html(dados)



def test_matific_base_na_noite_anterior_nao_e_sem_inicio(db, escola_completa):
    """01/09 02:30 UTC é 31/08 23:30 em Brasília: para a regra oficial (UTC
    cru) ela está "dentro"; mas ela mede o início — não se declara "sem
    coleta no início"."""
    eid, (a, *_) = _ids(escola_completa)
    _snap_matific(db, eid, a, datetime(2026, 9, 1, 2, 30), 100, 300)
    _snap_matific(db, eid, a, _noite(30), 112, 340)
    cob = _gerar(db, eid, plataformas=("matific",))["matific"]["cobertura"]
    assert cob["inicio_coberto"] is True and cob["status"] == "regra_oficial"


def test_matific_conta_os_medidos_para_dizer_a_quem_vale(db, escola_completa):
    eid, (a, b, *_) = _ids(escola_completa)
    _snap_matific(db, eid, a, _noite(31, 8), 100, 300)              # regra oficial
    _snap_matific(db, eid, a, _noite(30), 112, 340)
    _snap_matific(db, eid, b, datetime(2026, 9, 22, 16, 0), 50, 100)  # sem início
    _snap_matific(db, eid, b, _noite(30), 55, 110)
    cob = _gerar(db, eid, plataformas=("matific",))["matific"]["cobertura"]
    assert cob["alunos_medidos"] == 2 and cob["alunos_sem_inicio"] == 1
    from app.services import relatorios_periodo_pdf as pdf
    html = pdf.montar_html(_gerar(db, eid, plataformas=("matific",)))
    assert "sem coleta no início do período para 1 estudante(s)" in html.lower()


def test_pdf_reserva_leva_a_contagem_e_o_andamento(db, escola_completa):
    from app.services import relatorios_periodo_pdf as pdf
    from tests.test_relatorios_periodo_pdf import _texto
    eid, (a, b, *_) = _ids(escola_completa)
    _snap_elefante(db, eid, a, _noite(1, 10), 10, 5)                # completo
    _snap_elefante(db, eid, a, _noite(6, 10), 20, 10)
    _snap_elefante(db, eid, b, datetime(2026, 10, 2, 16, 0), 50, 40)  # sem início
    _snap_elefante(db, eid, b, _noite(6, 10), 55, 44)
    texto = _texto(pdf._reserva(_gerar(db, eid, preset="mes"), "#1B2A4A"))
    assert "(1 est.)" in texto
    assert "em andamento" in texto
