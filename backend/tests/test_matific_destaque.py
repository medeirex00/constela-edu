"""MELHOR MATEMÁTICA por período — decisão do dono (2026-09-15).

Trava mecanicamente:
  * SÓ O PERÍODO decide: snapshot de dez/2025 não vale em set/2026; snapshot só
    antes do período não entra; snapshots diários sem atividade não entram;
  * FILTRO DE ANO LETIVO: snapshots fora do ano letivo não são estado nem base;
  * RÉGUA DA ESCOLA INTEIRA: a mesma criança tem o mesmo valor com turma, com
    as turmas de um professor e no agrupamento por turno;
  * FÓRMULA: estrelas ÷ (atividades + 0,2 × mediana de atividades da coorte),
    com os valores e a ordem dos casos de referência;
  * período vazio = sem vencedor; coorte vazia = sem erro.
"""
import math
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.core.security import hash_senha
from app.models import Aluno, Escola, Importacao, Matricula, SnapshotMatific, Turma, Usuario
from app.services import matific_destaque as md
from app.services import periodos, premiacoes, provisionamento

AGO_INI, AGO_FIM = datetime(2026, 8, 1), datetime(2026, 8, 31, 23, 59, 59, 999999)
SET_INI, SET_FIM = datetime(2026, 9, 1), datetime(2026, 9, 30, 23, 59, 59, 999999)
BASE_JUL = datetime(2026, 7, 31, 12, 0)

# Casos de referência do dono: (atividades, estrelas por atividade) no período.
CASOS = [(10, 5.0), (30, 5.0), (60, 4.8), (100, 4.6), (150, 4.5), (200, 4.0)]


def s(data, atividades, estrelas):
    """Snapshot mínimo para as funções puras."""
    return SimpleNamespace(data_referencia=data, atividades=atividades, estrelas=estrelas)


# ---------------------------------------------------------------------------
# Cenário de banco
# ---------------------------------------------------------------------------
def _escola(db, nome="EMEF Destaque"):
    esc = Escola(nome=nome, ano_letivo_ativo=2026, status="ativa")
    db.add(esc)
    db.flush()
    db.add(Usuario(escola_id=esc.id, nome="A", email=f"a{esc.id}@destaque.local",
                   senha_hash=hash_senha("x"), cargo="admin"))
    provisionamento.semear_config_inicial(db, esc.id)
    imp = Importacao(escola_id=esc.id, plataforma="matific", tipo="seed")
    db.add(imp)
    db.flush()
    return esc, imp


def _turma(db, esc, nome, turno, serie="3º Ano"):
    t = Turma(escola_id=esc.id, nome=nome, ano_escolar=serie, ano_letivo=2026,
              turno=turno, status="ativa")
    db.add(t)
    db.flush()
    return t


def _aluno(db, esc, turma, nome):
    a = Aluno(escola_id=esc.id, nome=nome, status="ativo")
    db.add(a)
    db.flush()
    db.add(Matricula(escola_id=esc.id, aluno_id=a.id, turma_id=turma.id, ano_letivo=2026))
    return a


def _snap(db, esc, imp, aluno, quando, atividades, estrelas, media=3.0):
    db.add(SnapshotMatific(escola_id=esc.id, aluno_id=aluno.id, importacao_id=imp.id,
                           data_referencia=quando, atividades=atividades,
                           estrelas=estrelas, pontuacao_media=media))


def _jogou_em_agosto(db, esc, imp, aluno, atividades, estrelas):
    """Base zerada no fim de julho + estado em 20/08: ganho = (atividades, estrelas)."""
    _snap(db, esc, imp, aluno, BASE_JUL, 0, 0)
    _snap(db, esc, imp, aluno, datetime(2026, 8, 20), atividades, estrelas)


def _mm(dados):
    return next(c for c in dados["categorias"] if c["chave"] == "melhor_matematica")["podio"]


def _grupo(dados, turno):
    grupo = next(g for g in dados["turnos"] if g["turno"] == turno)
    return next(c for c in grupo["categorias"] if c["chave"] == "melhor_matematica")["podio"]


# ---------------------------------------------------------------------------
# Funções puras
# ---------------------------------------------------------------------------
def test_janela_do_ano_letivo_e_a_mesma_do_preset():
    ini, fim, _ = periodos.resolver("ano_letivo", date(2026, 5, 10), 2026)
    assert md.janela_ano_letivo(2026) == (ini, fim)


def test_exemplo_do_dono_dezembro_2025_nao_vale_em_setembro_2026():
    serie = [s(datetime(2025, 12, 20), 400, 1800)]
    assert md.ganho_no_periodo(serie, SET_INI, SET_FIM, 2026) is None
    # Nem como "todo o histórico" de 2026: não há snapshot no ano letivo.
    assert md.ganho_no_periodo(serie, None, None, 2026) is None
    # E como BASE também não: com dez/2025 como base, o ganho de setembro seria 0.
    serie += [s(datetime(2026, 9, 10), 20, 90), s(datetime(2026, 9, 25), 50, 220)]
    ganho = md.ganho_no_periodo(serie, SET_INI, SET_FIM, 2026)
    assert (ganho.atividades, ganho.estrelas) == (30, 130)
    assert ganho.data_base == datetime(2026, 9, 10)
    assert ganho.data_atual == datetime(2026, 9, 25)


def test_snapshot_so_antes_do_periodo_nao_entra():
    assert md.ganho_no_periodo([s(datetime(2026, 7, 10), 50, 200)],
                               AGO_INI, AGO_FIM, 2026) is None


def test_base_e_o_ultimo_snapshot_do_ano_antes_do_inicio():
    serie = [s(datetime(2026, 6, 1), 60, 250), s(BASE_JUL, 100, 400),
             s(datetime(2026, 8, 15), 130, 520), s(datetime(2026, 9, 3), 200, 900)]
    ganho = md.ganho_no_periodo(serie, AGO_INI, AGO_FIM, 2026)
    assert (ganho.atividades, ganho.estrelas) == (30, 120)   # setembro não entra
    assert (ganho.data_base, ganho.data_atual) == (BASE_JUL, datetime(2026, 8, 15))


def test_snapshots_diarios_cumulativos_sem_atividade_no_periodo_nao_pontuam():
    dias = [datetime(2026, 7, 25) + timedelta(days=i) for i in range(38)]
    serie = [s(d, 120, 500) for d in dias]                    # contador parado
    ganho = md.ganho_no_periodo(serie, AGO_INI, AGO_FIM, 2026)
    assert (ganho.atividades, ganho.estrelas) == (0, 0)
    assert md.indice(ganho.atividades, ganho.estrelas, k=50) is None
    # Sem base anterior: só snapshots DENTRO da janela, todos iguais → também zero.
    dentro = [s(d, 120, 500) for d in dias if d >= AGO_INI]
    assert md.ganho_no_periodo(dentro, AGO_INI, AGO_FIM, 2026).atividades == 0


def test_estrelas_limitadas_a_cinco_por_atividade():
    serie = [s(datetime(2026, 8, 1), 10, 0), s(datetime(2026, 8, 20), 12, 50)]
    ganho = md.ganho_no_periodo(serie, AGO_INI, AGO_FIM, 2026)
    assert (ganho.atividades, ganho.estrelas) == (2, 10)


def test_filtro_de_ano_letivo():
    serie = [s(datetime(2025, 12, 10), 300, 1000), s(datetime(2026, 1, 10), 5, 20),
             s(datetime(2026, 1, 30), 25, 100)]
    # Período que atravessa a virada: vale só a parte de 2026 — e, como a janela
    # EFETIVA começa em 01/01, a base é ZERO.
    # MUDOU (MAT-01): este teste esperava 20/80 com base em 10/01 (o 1º snapshot
    # do ano virando base de si mesmo). O contador do Matific é DO ANO e parte de
    # zero em 01/01: aquele 1º snapshot JÁ É ganho do período, e descontá-lo
    # jogava fora tudo o que a criança fez antes da primeira coleta — fazendo a
    # MESMA janela de 2026 valer 20 por "ano letivo" e 25 por "todo o histórico".
    ganho = md.ganho_no_periodo(serie, datetime(2025, 12, 1), datetime(2026, 1, 31), 2026)
    assert (ganho.atividades, ganho.estrelas) == (25, 100)
    assert ganho.data_base is None and ganho.data_atual == datetime(2026, 1, 30)
    assert md.janela_efetiva(datetime(2025, 12, 1), datetime(2026, 1, 31), 2026) == (
        datetime(2026, 1, 1), datetime(2026, 1, 31))
    # Período inteiro fora do ano letivo: nada a medir.
    assert md.janela_efetiva(datetime(2025, 3, 1), datetime(2025, 3, 31), 2026) is None
    assert md.ganho_no_periodo(serie, datetime(2025, 3, 1), datetime(2025, 3, 31), 2026) is None
    # "Todo o histórico": situação do último snapshot DO ANO LETIVO, a partir do zero.
    tudo = md.ganho_no_periodo(serie, None, None, 2026)
    assert (tudo.atividades, tudo.estrelas, tudo.data_base) == (25, 100, None)
    assert tudo.data_atual == datetime(2026, 1, 30)
    anterior = md.ganho_no_periodo(serie, None, None, 2025)
    assert (anterior.atividades, anterior.estrelas) == (300, 1000)


def test_janela_que_comeca_no_ano_letivo_parte_do_zero():
    """MAT-01 — o contador do Matific é DO ANO: janela que começa em 01/01 não
    tem acumulado anterior a descontar, e "ano letivo" tem de bater com "tudo"."""
    ini_ano, fim_ano = md.janela_ano_letivo(2026)
    jan_ini, jan_fim = datetime(2026, 1, 1), datetime(2026, 1, 31, 23, 59, 59, 999999)
    # Import do relatório "Intervalo de datas" de JANEIRO: a base virtual cai em
    # 31/12 do ano anterior (descartada pelo filtro de ano) + o estado do mês.
    serie = [s(datetime(2025, 12, 31, 23, 59, 59), 0, 0),
             s(datetime(2026, 1, 31, 23, 59, 59), 40, 180)]
    jan = md.ganho_no_periodo(serie, jan_ini, jan_fim, 2026)
    assert (jan.atividades, jan.estrelas, jan.data_base) == (40, 180, None)
    ano = md.ganho_no_periodo(serie, ini_ano, fim_ano, 2026)
    tudo = md.ganho_no_periodo(serie, None, None, 2026)
    assert (ano.atividades, ano.estrelas) == (tudo.atividades, tudo.estrelas) == (40, 180)
    # Um único snapshot no ano (sync ligada em setembro, contador "this-year")
    # não vira base de si mesmo: o ano inteiro é o ganho.
    unico = [s(datetime(2026, 9, 10), 300, 1350)]
    assert md.ganho_no_periodo(unico, ini_ano, fim_ano, 2026).atividades == 300
    # E os meses seguintes continuam somando ao ano, sem duplicar nem sumir.
    com_fev = serie + [s(datetime(2026, 2, 28, 23, 59, 59), 50, 225)]
    fev = md.ganho_no_periodo(com_fev, datetime(2026, 2, 1),
                              datetime(2026, 2, 28, 23, 59, 59, 999999), 2026)
    assert (fev.atividades, fev.data_base) == (10, datetime(2026, 1, 31, 23, 59, 59))
    assert md.ganho_no_periodo(com_fev, ini_ano, fim_ano, 2026).atividades == 50


def test_janela_no_meio_do_ano_continua_medindo_so_o_observado():
    """Contraprova de MAT-01: fora do início do ano a regra justa vale inteira —
    o acumulado anterior à janela nunca vira mérito dela."""
    serie = [s(datetime(2026, 8, 5), 100, 400), s(datetime(2026, 8, 25), 130, 520)]
    ganho = md.ganho_no_periodo(serie, AGO_INI, AGO_FIM, 2026)
    assert (ganho.atividades, ganho.estrelas) == (30, 120)
    assert ganho.data_base == datetime(2026, 8, 5)
    # Um único snapshot na janela, sem base anterior, não prova atividade nenhuma.
    so_um = [s(datetime(2026, 8, 25), 130, 520)]
    assert md.ganho_no_periodo(so_um, AGO_INI, AGO_FIM, 2026).atividades == 0


def test_queda_do_contador_e_registrada_em_vez_de_virar_zero_mudo():
    """MAT-04 — o piso em 0 continua (uma correção para baixo não pode virar
    ganho do valor cheio: seria inventar número), mas a queda deixa de ser
    silenciosa: `regressao_detectada` diz que o contador do Matific regrediu
    entre `data_base` e `data_atual`."""
    serie = [s(datetime(2026, 1, 20), 400, 1800), s(datetime(2026, 2, 5), 3, 14),
             s(datetime(2026, 2, 25), 15, 70)]
    fev = md.ganho_no_periodo(serie, datetime(2026, 2, 1),
                              datetime(2026, 2, 28, 23, 59, 59, 999999), 2026)
    assert (fev.atividades, fev.estrelas) == (0, 0)
    assert fev.regressao_detectada is True
    assert (fev.data_base, fev.data_atual) == (datetime(2026, 1, 20), datetime(2026, 2, 25))
    # Sem queda não há marca; e o caminho sem base (ano/tudo) nunca marca.
    normal = md.ganho_no_periodo([s(BASE_JUL, 100, 400), s(datetime(2026, 8, 20), 130, 520)],
                                 AGO_INI, AGO_FIM, 2026)
    assert normal.regressao_detectada is False
    assert md.ganho_no_periodo(serie, None, None, 2026).regressao_detectada is False


def test_o_equilibrio_da_formula_depende_da_mediana_do_periodo():
    """MAT-07 — as duas propriedades citadas na documentação NÃO são absolutas:
    dependem de `k`, a mediana da coorte DAQUELE período. Este teste trava a
    fronteira para ninguém ressuscitar a redação absoluta (a fórmula não muda)."""
    k80 = md.mediana_atividades([a for a, _ in CASOS])
    assert k80 == 80                                   # a mediana dos casos do dono
    assert md.indice(10, 50, k80) < md.indice(150, 675, k80)
    assert md.indice(200, 800, k80) < md.indice(60, 288, k80)
    # Período curto / coorte pouco ativa: mediana baixa → a média por atividade pesa.
    k_curto = md.mediana_atividades([2, 3, 4, 5, 10, 150])
    assert k_curto == 4.5
    assert md.indice(10, 50, k_curto) > md.indice(150, 675, k_curto)
    # Coorte de volume alto: mediana alta → o volume pesa.
    k_alto = md.mediana_atividades([200, 60, 150, 180, 250])
    assert k_alto == 180
    assert md.indice(200, 800, k_alto) > md.indice(60, 288, k_alto)


def test_valores_e_ordem_dos_casos_de_referencia_com_k_conhecido():
    atividades = [a for a, _ in CASOS]
    k = md.mediana_atividades(atividades)
    assert k == 80                                            # (60 + 100) / 2
    esperado = {                                              # estrelas ÷ (ativ. + 16)
        (10, 5.0): 1.9231, (30, 5.0): 3.2609, (60, 4.8): 3.7895,
        (100, 4.6): 3.9655, (150, 4.5): 4.0663, (200, 4.0): 3.7037,
    }
    valores = {caso: md.indice(caso[0], caso[0] * caso[1], k) for caso in CASOS}
    for caso, valor in valores.items():
        assert valor == pytest.approx(esperado[caso], abs=1e-4), caso
    ordem = sorted(CASOS, key=lambda caso: -valores[caso])
    assert ordem == [(150, 4.5), (100, 4.6), (60, 4.8), (200, 4.0), (30, 5.0), (10, 5.0)]


def test_protecoes_da_formula():
    assert md.mediana_atividades([]) is None
    assert md.mediana_atividades([0, 0, None]) is None
    assert md.indice(0, 0, 10) is None                        # sem atividade
    assert md.indice(10, 50, None) is None                    # sem régua
    assert md.indice(10, 50, 0) == 5.0                        # k = 0 não divide por zero
    assert md.indice(1, 10**9, 1) == 5.0                      # teto da escala
    assert md.indice(float("nan"), 5, 10) is None
    assert md.indice(5, float("inf"), 10) is None
    regua, indices = md.indices_da_coorte({})
    assert (regua.k_mediana_atividades, regua.zeros_extras, regua.alunos_com_atividade) == (None, None, 0)
    assert indices == {}
    for valor in (md.indice(a, a * e, 80) for a, e in CASOS):
        assert math.isfinite(valor) and 0 <= valor <= 5


def test_podio_ordena_pelo_valor_bruto_e_exibe_arredondado():
    alunos = {1: {"nome": "Zé", "turma": "A"}, 2: {"nome": "Ana", "turma": "A"}}
    podio = premiacoes._podio({1: 3.964, 2: 3.961}, alunos)
    # Arredondados os dois dariam 3,96 e o nome decidiria (Ana); o bruto decide.
    assert [p["aluno_id"] for p in podio] == [1, 2]
    assert [p["valor"] for p in podio] == [3.96, 3.96]


# ---------------------------------------------------------------------------
# Serviço de premiações
# ---------------------------------------------------------------------------
def test_premiacao_de_setembro_2026_ignora_acumulado_de_dezembro_2025(db):
    esc, imp = _escola(db)
    turma = _turma(db, esc, "3º A", "manha")
    antigo = _aluno(db, esc, turma, "Acumulado Antigo")
    _snap(db, esc, imp, antigo, datetime(2025, 12, 20), 400, 1800)
    jogou = _aluno(db, esc, turma, "Jogou Em Setembro")
    _snap(db, esc, imp, jogou, datetime(2026, 8, 31, 12), 0, 0)
    _snap(db, esc, imp, jogou, datetime(2026, 9, 12), 12, 48)
    db.commit()

    dados = premiacoes.premiacoes(db, esc.id, SET_INI, SET_FIM)
    podio = _mm(dados)
    assert [p["nome"] for p in podio] == ["Jogou Em Setembro"]
    # Datas efetivamente usadas viajam na resposta.
    assert podio[0]["data_base"] == "2026-08-31T12:00:00"
    assert podio[0]["data_atual"] == "2026-09-12T00:00:00"
    assert (podio[0]["atividades"], podio[0]["estrelas"]) == (12, 48)
    regua = dados["regua_matematica"]
    assert regua["alunos_com_atividade"] == 1 and regua["k_mediana_atividades"] == 12
    assert regua["modo"] == "periodo"
    assert regua["inicio_efetivo"] == SET_INI.isoformat()
    assert regua["fim_efetivo"] == SET_FIM.isoformat()
    # "Todo o histórico" também não usa o acumulado do ano anterior.
    tudo = premiacoes.premiacoes(db, esc.id, None, None)
    assert [p["nome"] for p in _mm(tudo)] == ["Jogou Em Setembro"]
    assert tudo["regua_matematica"]["modo"] == "situacao_atual"
    assert tudo["regua_matematica"]["inicio_efetivo"] is None


def test_quem_jogou_no_periodo_vence_acumulado_grande(db):
    esc, imp = _escola(db)
    turma = _turma(db, esc, "3º A", "manha")
    veterano = _aluno(db, esc, turma, "Veterano Parado")
    _snap(db, esc, imp, veterano, BASE_JUL, 900, 4200)
    for dia in range(1, 32):                                   # diários sem atividade
        _snap(db, esc, imp, veterano, datetime(2026, 8, dia, 6), 900, 4200)
    gigante = _aluno(db, esc, turma, "Gigante So Antes")
    _snap(db, esc, imp, gigante, datetime(2026, 7, 10), 5000, 25000)
    novato = _aluno(db, esc, turma, "Novato Ativo")
    _jogou_em_agosto(db, esc, imp, novato, 40, 180)
    db.commit()

    dados = premiacoes.premiacoes(db, esc.id, AGO_INI, AGO_FIM)
    assert [p["nome"] for p in _mm(dados)] == ["Novato Ativo"]
    assert dados["regua_matematica"]["alunos_com_atividade"] == 1


def test_mesma_nota_com_turma_professor_e_turno(db):
    """A régua é a da ESCOLA: k = mediana de TODA a coorte, em qualquer recorte."""
    esc, imp = _escola(db)
    manha = _turma(db, esc, "3º A", "manha", serie="3º Ano")
    tarde = _turma(db, esc, "4º A", "tarde", serie="4º Ano")
    da_manha = {}
    for nome, ativ, estrelas in [("M1", 10, 50), ("M2", 20, 90), ("M3", 30, 120)]:
        aluno = _aluno(db, esc, manha, nome)
        _jogou_em_agosto(db, esc, imp, aluno, ativ, estrelas)
        da_manha[nome] = (ativ, estrelas)
    for nome, ativ, estrelas in [("T1", 100, 400), ("T2", 150, 600), ("T3", 200, 700),
                                 ("T4", 250, 1000), ("T5", 300, 1200)]:
        _jogou_em_agosto(db, esc, imp, _aluno(db, esc, tarde, nome), ativ, estrelas)
    db.commit()

    k_escola = 125.0                                   # mediana de 8 alunos: (100 + 150) / 2
    esperado = {nome: round(md.indice(a, e, k_escola), 2) for nome, (a, e) in da_manha.items()}
    # Com a régua SÓ da manhã (k = 20) os valores seriam outros — o teste distingue.
    assert esperado != {nome: round(md.indice(a, e, 20.0), 2)
                        for nome, (a, e) in da_manha.items()}

    por_turma = premiacoes.premiacoes(db, esc.id, AGO_INI, AGO_FIM, turma_id=manha.id)
    professor = premiacoes.premiacoes(db, esc.id, AGO_INI, AGO_FIM, turma_ids=[manha.id])
    por_turno = premiacoes.premiacoes(db, esc.id, AGO_INI, AGO_FIM, por_turno=True)
    for podio in (_mm(por_turma), _mm(professor), _grupo(por_turno, "manha")):
        assert {p["nome"]: p["valor"] for p in podio} == esperado
    for dados in (por_turma, professor, por_turno):
        assert dados["regua_matematica"]["k_mediana_atividades"] == k_escola
        assert dados["regua_matematica"]["alunos_com_atividade"] == 8
    # Na escola inteira, a mesma criança aparece com o MESMO valor.
    escola = premiacoes.premiacoes(db, esc.id, AGO_INI, AGO_FIM)
    geral = {p["nome"]: p["valor"] for p in _mm(escola)}
    assert all(geral[n] == v for n, v in esperado.items() if n in geral)


def test_casos_de_referencia_no_servico(db):
    esc, imp = _escola(db)
    turma = _turma(db, esc, "5º A", "manha", serie="5º Ano")
    nomes = {}
    for ativ, media in CASOS:
        nome = f"Caso {ativ:03d}"
        _jogou_em_agosto(db, esc, imp, _aluno(db, esc, turma, nome), ativ, round(ativ * media))
        nomes[(ativ, media)] = nome
    db.commit()

    dados = premiacoes.premiacoes(db, esc.id, AGO_INI, AGO_FIM)
    regua = dados["regua_matematica"]
    assert (regua["k_mediana_atividades"], regua["zeros_extras"]) == (80, 16)
    assert regua["alunos_com_atividade"] == 6 and regua["coorte"] == "escola"
    podio = _mm(dados)
    assert [p["nome"] for p in podio] == [nomes[c] for c in
                                          [(150, 4.5), (100, 4.6), (60, 4.8), (200, 4.0), (30, 5.0)]]
    assert [p["valor"] for p in podio] == [4.07, 3.97, 3.79, 3.7, 3.26]
    assert [p["posicao"] for p in podio] == [1, 2, 3, 4, 5]


def test_periodo_vazio_sem_vencedor(db):
    esc, imp = _escola(db)
    turma = _turma(db, esc, "3º A", "manha")
    _jogou_em_agosto(db, esc, imp, _aluno(db, esc, turma, "So Agosto"), 30, 120)
    db.commit()

    dados = premiacoes.premiacoes(db, esc.id, SET_INI, SET_FIM)
    assert _mm(dados) == []
    regua = dados["regua_matematica"]
    assert regua["k_mediana_atividades"] is None and regua["zeros_extras"] is None
    assert regua["alunos_com_atividade"] == 0
    # Período fora do ano letivo: sem janela e sem vencedor.
    fora = premiacoes.premiacoes(db, esc.id, datetime(2025, 8, 1), datetime(2025, 8, 31))
    assert _mm(fora) == [] and fora["regua_matematica"]["modo"] == "fora_do_ano_letivo"
    # Datas trocadas (início depois do fim): sem janela, sem vencedor e rótulo honesto.
    trocado = premiacoes.premiacoes(db, esc.id, AGO_FIM, AGO_INI)
    assert _mm(trocado) == [] and trocado["regua_matematica"]["modo"] == "periodo_invalido"
    assert trocado["regua_matematica"]["inicio_efetivo"] is None


def test_coorte_vazia_sem_erro(db):
    esc, _ = _escola(db, "EMEF Vazia")
    db.commit()
    dados = premiacoes.premiacoes(db, esc.id, AGO_INI, AGO_FIM, por_turno=True)
    assert all(c["podio"] == [] for c in dados["categorias"])
    assert dados["turnos"] == []
    assert dados["regua_matematica"]["alunos_com_atividade"] == 0
    assert dados["regua_matematica"]["k_mediana_atividades"] is None
    # Recorte de professor sem turmas também não quebra.
    vazio = premiacoes.premiacoes(db, esc.id, AGO_INI, AGO_FIM, turma_ids=[])
    assert all(c["podio"] == [] for c in vazio["categorias"])
