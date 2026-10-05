"""Relatório por período: a janela é inclusiva, cada número diz de QUAL data
ele vem, e o que não dá para calcular é declarado em vez de inventado.

O teste que sustenta o módulo é ``test_releitura_...``: um livro com ``Leitura``
histórica ANTERIOR ao período e um evento de releitura DENTRO dele. O relatório
tem de mostrar os DOIS fatos sem somá-los — ``livros_novos`` (eixo
``Leitura.data``, o mesmo da premiação oficial) fica zero em setembro, e
``livros_com_atividade`` + ``livros_relidos`` (eixo ``EventoAluno.ocorrido_em``)
mostram a releitura. Uma implementação com um eixo só reprova aqui: com apenas
``Leitura.data`` a releitura desaparece; com apenas o evento, o relatório
discorda do pódio sobre o mesmo mês.

E ``test_tempo_por_evento_e_declarado_nao_suportado`` guarda a decisão medida:
``EventoAluno.tempo_segundos`` vem do ``totalTimeSpent`` por LIVRO, cuja soma e
cuja diferença estão ambas refutadas pela base real — então o tempo do período
vem de ``Leitura.tempo_leitura_min``, nunca do evento.
"""
from datetime import date, datetime

import pytest

from app.models import (EventoAluno, Importacao, Leitura, Livro,
                        SnapshotElefante, SnapshotMatific)
from app.services import relatorios_periodo as rp
from app.services.eventos import chave_evento

HOJE = date(2026, 10, 5)
ANO = 2026


def _livro(db, escola_id, titulo="A Galinha do Vizinho", nivel="AA"):
    livro = Livro(escola_id=escola_id, titulo=titulo, nivel_codigo=nivel)
    db.add(livro)
    db.flush()
    return livro


def _leitura(db, escola_id, aluno_id, livro, quando, tempo=5):
    leitura = Leitura(escola_id=escola_id, aluno_id=aluno_id, livro_id=livro.id,
                      data=quando, tempo_leitura_min=tempo,
                      nivel_codigo=livro.nivel_codigo)
    db.add(leitura)
    db.flush()
    return leitura


def _evento(db, escola_id, aluno_id, livro, quando, minutos=5, extra=""):
    evento = EventoAluno(
        escola_id=escola_id, aluno_id=aluno_id, plataforma="elefante",
        tipo_evento="leitura", ocorrido_em=quando, conteudo_titulo=livro.titulo,
        livro_id=livro.id, tempo_segundos=minutos * 60,
        nivel_codigo=livro.nivel_codigo,
        chave_natural=chave_evento("elefante", "leitura", aluno_id,
                                   livro.titulo, quando, extra))
    db.add(evento)
    db.flush()
    return evento


def _importacao(db, escola_id, plataforma):
    """`snapshots_*.importacao_id` é NOT NULL: todo retrato nasce de uma
    importação. Os testes criam uma, em vez de afrouxar o modelo."""
    imp = Importacao(escola_id=escola_id, usuario_id=None, plataforma=plataforma,
                     tipo="seed", arquivo_original=None, qtd_alunos=0,
                     qtd_erros=0, tempo_ms=0, status="concluida")
    db.add(imp)
    db.flush()
    return imp


def _snap_matific(db, escola_id, aluno_id, quando, atividades, estrelas):
    snap = SnapshotMatific(escola_id=escola_id, aluno_id=aluno_id,
                           importacao_id=_importacao(db, escola_id, "matific").id,
                           data_referencia=quando,
                           atividades=atividades, estrelas=estrelas,
                           pontuacao_media=0.0)
    db.add(snap)
    db.flush()
    return snap


def _snap_elefante(db, escola_id, aluno_id, quando, tentativas, acertos):
    snap = SnapshotElefante(escola_id=escola_id, aluno_id=aluno_id,
                            importacao_id=_importacao(db, escola_id, "elefante").id,
                            data_referencia=quando,
                            livros_unicos=0, tempo_leitura_min=0,
                            questoes_tentativas=tentativas,
                            questoes_acertos=acertos, livros_por_nivel={})
    db.add(snap)
    db.flush()
    return snap


def _gerar(db, escola_id, **kw):
    kw.setdefault("preset", "mes")
    kw.setdefault("plataformas", ("elefante", "matific"))
    kw.setdefault("hoje", HOJE)
    return rp.gerar(db, escola_id, **kw)


# ---------------------------------------------------------------- 1 a 5: presets
@pytest.mark.parametrize("preset,ini,fim", [
    ("mes", datetime(2026, 10, 1), datetime(2026, 10, 31, 23, 59, 59, 999999)),
    ("mes_anterior", datetime(2026, 9, 1), datetime(2026, 9, 30, 23, 59, 59, 999999)),
    ("bimestre_3", datetime(2026, 7, 24), datetime(2026, 10, 4, 23, 59, 59, 999999)),
    ("ano_letivo", datetime(2026, 1, 1), datetime(2026, 12, 31, 23, 59, 59, 999999)),
])
def test_presets_oficiais_resolvem_a_janela(preset, ini, fim):
    j = rp.resolver_janela(preset, ANO, hoje=HOJE)
    assert (j.inicio, j.fim) == (ini, fim)


def test_personalizado_usa_as_datas_informadas():
    j = rp.resolver_janela("personalizado", ANO, inicio=date(2026, 8, 1),
                           fim=date(2026, 8, 15), hoje=HOJE)
    assert j.inicio == datetime(2026, 8, 1, 0, 0, 0)
    assert j.fim == datetime(2026, 8, 15, 23, 59, 59, 999999)
    assert j.rotulo == "01/08/2026 a 15/08/2026"


# ------------------------------------------------------- 6 a 8: datas de borda
def test_mesmo_dia_inicial_e_final_cobre_o_dia_inteiro():
    j = rp.resolver_janela("personalizado", ANO, inicio=date(2026, 9, 10),
                           fim=date(2026, 9, 10), hoje=HOJE)
    assert j.inicio == datetime(2026, 9, 10, 0, 0, 0)
    assert j.fim == datetime(2026, 9, 10, 23, 59, 59, 999999)
    assert j.contem(datetime(2026, 9, 10, 0, 0, 0))
    assert j.contem(datetime(2026, 9, 10, 23, 59, 59))
    assert not j.contem(datetime(2026, 9, 11, 0, 0, 0))


def test_data_inicial_maior_que_final_e_recusada():
    with pytest.raises(rp.RelatorioInvalido) as erro:
        rp.resolver_janela("personalizado", ANO, inicio=date(2026, 9, 25),
                           fim=date(2026, 9, 10), hoje=HOJE)
    assert "posterior" in str(erro.value)


def test_personalizado_sem_data_e_recusado():
    with pytest.raises(rp.RelatorioInvalido):
        rp.resolver_janela("personalizado", ANO, inicio=date(2026, 9, 1), hoje=HOJE)
    with pytest.raises(rp.RelatorioInvalido):
        rp.resolver_janela("personalizado", ANO, hoje=HOJE)


def test_preset_inexistente_e_recusado():
    with pytest.raises(rp.RelatorioInvalido) as erro:
        rp.resolver_janela("trimestre_maluco", ANO, hoje=HOJE)
    assert "não existe" in str(erro.value)


# ------------------------------------------------- 9 a 11: seleção de plataforma
def test_somente_elefante(db, escola_completa):
    escola = escola_completa["escola"]
    r = _gerar(db, escola.id, plataformas=("elefante",))
    assert "elefante" in r and "matific" not in r
    assert r["plataformas_rotulo"] == "Elefante Letrado"


def test_somente_matific(db, escola_completa):
    escola = escola_completa["escola"]
    r = _gerar(db, escola.id, plataformas=("matific",))
    assert "matific" in r and "elefante" not in r
    assert r["plataformas_rotulo"] == "Matific"


def test_as_duas_plataformas(db, escola_completa):
    escola = escola_completa["escola"]
    r = _gerar(db, escola.id, plataformas=("elefante", "matific"))
    assert "elefante" in r and "matific" in r
    assert r["plataformas_rotulo"] == "Elefante Letrado + Matific"


def test_nenhuma_plataforma_e_recusado(db, escola_completa):
    with pytest.raises(rp.RelatorioInvalido):
        _gerar(db, escola_completa["escola"].id, plataformas=())


def test_plataforma_inexistente_e_recusada(db, escola_completa):
    with pytest.raises(rp.RelatorioInvalido):
        _gerar(db, escola_completa["escola"].id, plataformas=("khan",))


# ------------------------------------------------------- 12 a 14: os três escopos
def test_escopo_escola_cobre_toda_a_populacao_ativa(db, escola_completa):
    escola = escola_completa["escola"]
    r = _gerar(db, escola.id, escopo="escola")
    assert r["alunos"]["considerados"] == len(escola_completa["alunos"])
    assert r["escopo"]["tipo"] == "escola"
    assert len(r["por_aluno"]) == len(escola_completa["alunos"])
    assert "por_turma" in r


def test_escopo_turma(db, escola_completa):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    r = _gerar(db, escola.id, escopo="turma", turma_id=turma.id)
    assert r["escopo"]["turma_id"] == turma.id
    assert r["alunos"]["considerados"] == len(escola_completa["alunos"])
    assert {t["turma_id"] for t in r["por_turma"]} == {turma.id}


def test_escopo_aluno(db, escola_completa):
    escola = escola_completa["escola"]
    alvo = escola_completa["alunos"][0]
    r = _gerar(db, escola.id, escopo="aluno", aluno_id=alvo.id)
    assert r["alunos"]["considerados"] == 1
    assert [a["aluno_id"] for a in r["por_aluno"]] == [alvo.id]


def test_escopo_turma_sem_turma_id_e_recusado(db, escola_completa):
    with pytest.raises(rp.RelatorioInvalido):
        _gerar(db, escola_completa["escola"].id, escopo="turma")


def test_escopo_aluno_sem_aluno_id_e_recusado(db, escola_completa):
    with pytest.raises(rp.RelatorioInvalido):
        _gerar(db, escola_completa["escola"].id, escopo="aluno")


def test_escopo_inexistente_e_recusado(db, escola_completa):
    with pytest.raises(rp.RelatorioInvalido):
        _gerar(db, escola_completa["escola"].id, escopo="rede")


# ------------------------------- 15: o aluno de OUTRA escola não entra na coorte
def test_aluno_de_outra_escola_nao_entra_no_relatorio(db, escola_completa):
    """A trava de permissão é da rota; o motor também não deixa vazar: a coorte
    é filtrada por escola_id, então pedir um aluno alheio devolve vazio."""
    from app.models import Escola
    outra = Escola(nome="OUTRA ESCOLA", ano_letivo_ativo=ANO)
    db.add(outra)
    db.flush()
    alvo = escola_completa["alunos"][0]
    r = _gerar(db, outra.id, escopo="aluno", aluno_id=alvo.id)
    assert r["alunos"]["considerados"] == 0
    assert r["por_aluno"] == []


def test_escola_inexistente_e_recusada(db):
    with pytest.raises(rp.RelatorioInvalido):
        _gerar(db, 987654)


# --------------------------------------- 16 a 18: sem atividade é EXPLÍCITO
def test_escola_sem_atividade_no_periodo_mostra_zero_explicito(db, escola_completa):
    escola = escola_completa["escola"]
    r = _gerar(db, escola.id, preset="mes")
    assert r["elefante"]["livros_novos"] == 0
    assert r["elefante"]["livros_com_atividade"] == 0
    assert r["elefante"]["eventos_leitura"] == 0
    assert r["elefante"]["livros_relidos"] == 0
    assert r["elefante"]["alunos_com_atividade"] == 0
    assert r["elefante"]["sem_atividade"] == len(escola_completa["alunos"])
    assert r["matific"]["atividades"] == 0
    assert r["matific"]["alunos_sem_retrato"] == len(escola_completa["alunos"])
    assert r["alunos"]["com_atividade"] == 0


def test_turma_sem_atividade_aparece_na_distribuicao(db, escola_completa):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    r = _gerar(db, escola.id, escopo="turma", turma_id=turma.id)
    linha = next(t for t in r["por_turma"] if t["turma_id"] == turma.id)
    assert linha["alunos"] == len(escola_completa["alunos"])
    assert linha["com_atividade"] == 0
    assert linha["elefante"] == {"livros_novos": 0, "tempo_min": 0,
                                 "livros_com_atividade": 0, "livros_relidos": 0,
                                 "eventos_leitura": 0}


def test_aluno_sem_atividade_e_listado_e_marcado(db, escola_completa):
    escola = escola_completa["escola"]
    alvo = escola_completa["alunos"][0]
    r = _gerar(db, escola.id, escopo="aluno", aluno_id=alvo.id)
    linha = r["por_aluno"][0]
    assert linha["sem_atividade"] is True
    assert linha["elefante"] is None and linha["matific"] is None


# ============================================================================
# O TESTE CRÍTICO DO ELEFANTE
# ============================================================================
def test_releitura_aparece_no_eixo_do_evento_sem_contaminar_o_da_premiacao(
        db, escola_completa):
    """Livro importado em JULHO, relido em SETEMBRO.

    ``Leitura.data`` fica em julho para sempre (a §35 nunca a atualiza). O
    relatório de setembro tem de dizer as duas coisas, separadas:
      - ``livros_novos`` = 0 → é o MESMO número que a premiação oficial daria,
        e é verdade: nenhum livro NOVO em setembro;
      - ``livros_com_atividade`` = 1 e ``livros_relidos`` = 1 → houve leitura,
        e o relatório não some com ela.
    """
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    livro = _livro(db, escola.id)
    # histórico: a linha de Leitura nasceu em julho e nunca mudou
    _leitura(db, escola.id, aluno.id, livro, datetime(2026, 7, 10, 9, 0), tempo=4)
    _evento(db, escola.id, aluno.id, livro, datetime(2026, 7, 10, 9, 0), minutos=4)
    # releitura: só o evento registra setembro
    _evento(db, escola.id, aluno.id, livro, datetime(2026, 9, 18, 14, 30), minutos=7)

    setembro = _gerar(db, escola.id, preset="mes_anterior",
                      plataformas=("elefante",))["elefante"]
    assert setembro["livros_novos"] == 0, (
        "nenhum livro NOVO em setembro — e é isso que a premiação diz")
    assert setembro["tempo_min"] == 0, "o tempo acompanha o livro novo"
    assert setembro["livros_com_atividade"] == 1, (
        "a releitura de setembro TEM de aparecer — o evento a registra")
    assert setembro["livros_relidos"] == 1, (
        "e tem de aparecer rotulada como releitura, não como livro novo")
    assert setembro["eventos_leitura"] == 1
    assert setembro["alunos_com_atividade"] == 1
    assert setembro["alunos_com_livro_novo"] == 0

    julho = _gerar(db, escola.id, preset="personalizado",
                   inicio=date(2026, 7, 1), fim=date(2026, 7, 31),
                   plataformas=("elefante",))["elefante"]
    assert julho["livros_novos"] == 1 and julho["tempo_min"] == 4
    assert julho["livros_com_atividade"] == 1
    assert julho["livros_relidos"] == 0, "em julho o livro era novo, não relido"

    # a janela que cobre os dois meses: UM livro novo, UM com atividade, DOIS
    # eventos — e nada é somado duas vezes.
    ambos = _gerar(db, escola.id, preset="personalizado",
                   inicio=date(2026, 7, 1), fim=date(2026, 9, 30),
                   plataformas=("elefante",))["elefante"]
    assert ambos["livros_novos"] == 1
    assert ambos["livros_com_atividade"] == 1, "é o MESMO livro, não dois"
    assert ambos["eventos_leitura"] == 2
    assert ambos["livros_relidos"] == 0, "a Leitura está DENTRO desta janela"
    assert ambos["tempo_min"] == 4


def test_tempo_por_evento_e_declarado_nao_suportado(db, escola_completa):
    """A decisão medida: tempo do período NÃO sai de ``tempo_segundos``.

    Se um dia alguém "otimizar" o módulo somando o evento, este teste reprova —
    e o motivo fica no relatório, não só no commit.
    """
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    livro = _livro(db, escola.id)
    _leitura(db, escola.id, aluno.id, livro, datetime(2026, 9, 2, 9, 0), tempo=4)
    _evento(db, escola.id, aluno.id, livro, datetime(2026, 9, 2, 9, 0), minutos=4)
    _evento(db, escola.id, aluno.id, livro, datetime(2026, 9, 20, 9, 0), minutos=7)
    r = _gerar(db, escola.id, preset="mes_anterior", plataformas=("elefante",))
    assert r["elefante"]["tempo_min_por_evento"] is None
    assert r["elefante"]["tempo_min"] == 4, (
        "o tempo é o da Leitura (4), nunca a soma dos eventos (4+7) nem o "
        "último acumulado (7)")
    assert r["elefante"]["suporte"]["tempo_min_por_evento"]["classificacao"] \
        == "NÃO SUPORTADO"
    nao = [n for n in r["nao_suportado"] if n["metrica"] == "tempo_min_por_evento"]
    assert nao and "totalTimeSpent" in nao[0]["por_que"]


def test_cada_numero_declara_de_qual_data_ele_vem(db, escola_completa):
    r = _gerar(db, escola_completa["escola"].id, plataformas=("elefante",))
    suporte = r["elefante"]["suporte"]
    assert suporte["livros_novos"]["campo"].startswith("Leitura.data")
    assert suporte["livros_novos"]["classificacao"] == "SUPORTADO"
    assert "Mais Livros" in suporte["livros_novos"]["por_que"]
    assert suporte["tempo_min"]["campo"].startswith("Leitura.tempo_leitura_min")
    assert suporte["tempo_min"]["classificacao"] == "SUPORTADO COM RESSALVA"
    assert suporte["livros_com_atividade"]["campo"].startswith(
        "EventoAluno.ocorrido_em")


def test_livro_fora_da_janela_nao_conta(db, escola_completa):
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    livro = _livro(db, escola.id)
    _leitura(db, escola.id, aluno.id, livro, datetime(2026, 8, 20, 10, 0), tempo=9)
    _evento(db, escola.id, aluno.id, livro, datetime(2026, 8, 20, 10, 0), minutos=9)
    r = _gerar(db, escola.id, preset="mes_anterior", plataformas=("elefante",))
    assert r["elefante"]["livros_novos"] == 0 and r["elefante"]["tempo_min"] == 0
    assert r["elefante"]["livros_com_atividade"] == 0
    assert r["elefante"]["livros_relidos"] == 0, (
        "sem evento NA janela não há releitura, embora a Leitura esteja fora")


def test_borda_inclusiva_do_primeiro_e_do_ultimo_dia(db, escola_completa):
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    a, b = _livro(db, escola.id, "Primeiro dia"), _livro(db, escola.id, "Ultimo dia")
    _leitura(db, escola.id, aluno.id, a, datetime(2026, 9, 1, 0, 0, 0), tempo=1)
    _leitura(db, escola.id, aluno.id, b, datetime(2026, 9, 30, 23, 59, 59), tempo=2)
    _evento(db, escola.id, aluno.id, a, datetime(2026, 9, 1, 0, 0, 0), minutos=1)
    _evento(db, escola.id, aluno.id, b, datetime(2026, 9, 30, 23, 59, 59), minutos=2)
    r = _gerar(db, escola.id, preset="mes_anterior", plataformas=("elefante",))
    assert r["elefante"]["livros_novos"] == 2, "o intervalo é INCLUSIVO nas bordas"
    assert r["elefante"]["livros_com_atividade"] == 2, "nas duas datas, nos dois eixos"
    assert r["elefante"]["tempo_min"] == 3


def test_evento_de_outra_plataforma_nao_conta_como_leitura(db, escola_completa):
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    livro = _livro(db, escola.id)
    ev = _evento(db, escola.id, aluno.id, livro, datetime(2026, 9, 9, 10, 0))
    ev.plataforma = "matific"
    db.flush()
    r = _gerar(db, escola.id, preset="mes_anterior", plataformas=("elefante",))
    assert r["elefante"]["eventos_leitura"] == 0


def test_livro_com_evento_na_janela_mas_sem_leitura_nao_vira_releitura(
        db, escola_completa):
    """O join com ``Leitura`` é interno de propósito.

    A linha que o importador rejeitou (nível fora do vocabulário) deixa evento e
    não deixa ``Leitura``. Chamar isso de releitura seria afirmar um histórico
    que o sistema nunca registrou.
    """
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    livro = _livro(db, escola.id)
    _evento(db, escola.id, aluno.id, livro, datetime(2026, 9, 10, 10, 0), minutos=6)
    r = _gerar(db, escola.id, preset="mes_anterior", plataformas=("elefante",))
    assert r["elefante"]["livros_com_atividade"] == 1
    assert r["elefante"]["livros_relidos"] == 0
    assert r["elefante"]["livros_novos"] == 0 and r["elefante"]["tempo_min"] == 0


def test_tempo_nulo_na_leitura_entra_como_piso_nao_quebra(db, escola_completa):
    """``tempo_leitura_min`` é NULLABLE — a soma trata nulo como 0 e diz isso."""
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    a, b = _livro(db, escola.id, "Com tempo"), _livro(db, escola.id, "Sem tempo")
    _leitura(db, escola.id, aluno.id, a, datetime(2026, 9, 4, 10, 0), tempo=6)
    _leitura(db, escola.id, aluno.id, b, datetime(2026, 9, 5, 10, 0), tempo=None)
    r = _gerar(db, escola.id, preset="mes_anterior", plataformas=("elefante",))
    assert r["elefante"]["livros_novos"] == 2
    assert r["elefante"]["tempo_min"] == 6
    assert "PISO" in r["elefante"]["suporte"]["tempo_min"]["ressalva"]


# ---------------------------------------------------------- Matific: o ganho
def test_matific_conta_o_ganho_entre_retratos(db, escola_completa):
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    _snap_matific(db, escola.id, aluno.id, datetime(2026, 8, 31, 12, 0), 100, 300)
    _snap_matific(db, escola.id, aluno.id, datetime(2026, 9, 28, 12, 0), 140, 420)
    r = _gerar(db, escola.id, preset="mes_anterior", plataformas=("matific",))
    assert r["matific"]["atividades"] == 40
    assert r["matific"]["estrelas"] == 120
    assert r["matific"]["alunos_com_atividade"] == 1


def test_matific_sem_retrato_na_janela_nao_vira_zero(db, escola_completa):
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    _snap_matific(db, escola.id, aluno.id, datetime(2026, 8, 31, 12, 0), 100, 300)
    r = _gerar(db, escola.id, preset="mes_anterior", plataformas=("matific",))
    assert r["matific"]["alunos_sem_retrato"] == len(escola_completa["alunos"])
    assert r["matific"]["alunos_com_atividade"] == 0


def test_matific_questoes_e_declarado_nao_suportado(db, escola_completa):
    r = _gerar(db, escola_completa["escola"].id, plataformas=("matific",))
    assert r["matific"]["questoes"] is None
    assert r["matific"]["suporte"]["questoes"]["classificacao"] == "NÃO SUPORTADO"
    nao = [n for n in r["nao_suportado"]
           if n["plataforma"] == "matific" and n["metrica"] == "questoes"]
    assert nao and "não existe contador de questões" in nao[0]["por_que"]


def test_merito_no_periodo_e_declarado_nao_suportado(db, escola_completa):
    r = _gerar(db, escola_completa["escola"].id)
    nao = [n for n in r["nao_suportado"] if n["metrica"] == "pontos_de_dificuldade"]
    assert nao and "premiacoes" in nao[0]["por_que"]


def test_questoes_do_elefante_vem_da_diferenca_de_retratos(db, escola_completa):
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    _snap_elefante(db, escola.id, aluno.id, datetime(2026, 8, 31, 12, 0), 50, 40)
    _snap_elefante(db, escola.id, aluno.id, datetime(2026, 9, 29, 12, 0), 80, 62)
    r = _gerar(db, escola.id, preset="mes_anterior", plataformas=("elefante",))
    assert r["elefante"]["questoes_tentativas"] == 30
    assert r["elefante"]["questoes_acertos"] == 22
    assert r["elefante"]["suporte"]["questoes"]["classificacao"] == \
        "SUPORTADO COM RESSALVA"


def test_ter_retrato_na_janela_nao_e_ter_atividade(db, escola_completa):
    """Toda sincronização grava retrato de TODO MUNDO.

    Se "tem retrato" contasse como "tem atividade", `alunos_com_atividade`
    empataria com a escola inteira e a tela diria que ninguém está parado — o
    oposto do que o relatório existe para mostrar.
    """
    escola = escola_completa["escola"]
    parado, ativo = escola_completa["alunos"][0], escola_completa["alunos"][1]
    # os DOIS têm retrato na janela; só um evoluiu
    _snap_elefante(db, escola.id, parado.id, datetime(2026, 8, 31, 12, 0), 10, 8)
    _snap_elefante(db, escola.id, parado.id, datetime(2026, 9, 29, 12, 0), 10, 8)
    _snap_elefante(db, escola.id, ativo.id, datetime(2026, 8, 31, 12, 0), 10, 8)
    _snap_elefante(db, escola.id, ativo.id, datetime(2026, 9, 29, 12, 0), 25, 20)
    r = _gerar(db, escola.id, preset="mes_anterior", plataformas=("elefante",))
    assert r["elefante"]["questoes_tentativas"] == 15
    assert r["elefante"]["alunos_com_atividade"] == 1, (
        "só quem teve questão DE VERDADE conta como ativo")
    assert r["alunos"]["com_atividade"] == 1
    por_aluno = {x["aluno_id"]: x["elefante"] for x in r["por_aluno"]}
    assert por_aluno[parado.id] is None
    assert por_aluno[ativo.id]["questoes_tentativas"] == 15


def test_numero_vindo_de_retrato_publica_a_janela_efetiva(db, escola_completa):
    """O ganho entre COLETAS pode cobrir mais que o período pedido.

    A coleta base é de 15/08, mas o relatório é de setembro: o número inclui,
    por construção, 15/08 a 31/08. Em vez de esconder isso, o relatório diz
    quais pontas entraram na conta — a mesma auditoria que /premiacoes expõe.
    """
    escola = escola_completa["escola"]
    aluno = escola_completa["alunos"][0]
    _snap_elefante(db, escola.id, aluno.id, datetime(2026, 8, 15, 12, 0), 10, 8)
    _snap_elefante(db, escola.id, aluno.id, datetime(2026, 9, 29, 12, 0), 40, 30)
    _snap_matific(db, escola.id, aluno.id, datetime(2026, 8, 15, 12, 0), 5, 2)
    _snap_matific(db, escola.id, aluno.id, datetime(2026, 9, 29, 12, 0), 25, 11)
    r = _gerar(db, escola.id, preset="mes_anterior")
    jq = r["elefante"]["janela_efetiva_questoes"]
    assert jq["data_base_mais_antiga"].startswith("2026-08-15")
    assert jq["data_atual_mais_recente"].startswith("2026-09-29")
    assert "mais largo que o período pedido" in jq["observacao"]
    jm = r["matific"]["janela_efetiva"]
    assert jm["data_base_mais_antiga"].startswith("2026-08-15")
    assert jm["data_atual_mais_recente"].startswith("2026-09-29")


def test_sem_retrato_na_janela_a_janela_efetiva_e_nula(db, escola_completa):
    r = _gerar(db, escola_completa["escola"].id, preset="mes_anterior")
    assert r["elefante"]["janela_efetiva_questoes"] is None
    assert r["matific"]["janela_efetiva"] is None


# --------------------------------------------- agregação e ausência de N+1
def test_agrega_vários_alunos_e_distribui_por_turma(db, escola_completa):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    a, b = escola_completa["alunos"][0], escola_completa["alunos"][1]
    l1, l2 = _livro(db, escola.id, "Um"), _livro(db, escola.id, "Dois")
    _leitura(db, escola.id, a.id, l1, datetime(2026, 9, 5, 10, 0), tempo=10)
    _leitura(db, escola.id, a.id, l2, datetime(2026, 9, 6, 10, 0), tempo=5)
    _leitura(db, escola.id, b.id, l1, datetime(2026, 9, 7, 10, 0), tempo=8)
    _evento(db, escola.id, a.id, l1, datetime(2026, 9, 5, 10, 0), minutos=10)
    _evento(db, escola.id, a.id, l2, datetime(2026, 9, 6, 10, 0), minutos=5)
    _evento(db, escola.id, b.id, l1, datetime(2026, 9, 7, 10, 0), minutos=8)
    r = _gerar(db, escola.id, preset="mes_anterior", plataformas=("elefante",))
    assert r["elefante"]["livros_novos"] == 3, "2 do aluno A + 1 do aluno B"
    assert r["elefante"]["livros_com_atividade"] == 3
    assert r["elefante"]["eventos_leitura"] == 3
    assert r["elefante"]["tempo_min"] == 23
    assert r["elefante"]["alunos_com_atividade"] == 2
    assert r["elefante"]["alunos_com_livro_novo"] == 2
    linha = next(t for t in r["por_turma"] if t["turma_id"] == turma.id)
    assert linha["com_atividade"] == 2
    assert linha["elefante"]["tempo_min"] == 23
    assert linha["elefante"]["livros_novos"] == 3


def test_relatorio_identifica_periodo_plataformas_e_escopo(db, escola_completa):
    escola = escola_completa["escola"]
    r = _gerar(db, escola.id, preset="personalizado", inicio=date(2026, 10, 1),
               fim=date(2026, 10, 5))
    assert r["periodo"]["rotulo"] == "01/10/2026 a 05/10/2026"
    assert r["periodo"]["inclusivo"] is True
    assert r["escola"]["id"] == escola.id and r["escola"]["ano_letivo"] == ANO
    assert r["plataformas"] == ["elefante", "matific"]


def test_uma_consulta_agregada_por_plataforma_sem_n_mais_1(db, escola_completa):
    """Guarda contra N+1: o nº de SELECTs não cresce com o nº de alunos."""
    from sqlalchemy import event as sa_event
    escola = escola_completa["escola"]
    livro = _livro(db, escola.id)
    for al in escola_completa["alunos"]:
        _leitura(db, escola.id, al.id, livro, datetime(2026, 9, 11, 10, 0), tempo=3)
        _evento(db, escola.id, al.id, livro, datetime(2026, 9, 11, 10, 0),
                minutos=3, extra=str(al.id))
    contagem = {"n": 0}

    def contar(conn, cursor, stmt, *a, **k):
        if stmt.lstrip().upper().startswith("SELECT"):
            contagem["n"] += 1

    sa_event.listen(db.get_bind(), "before_cursor_execute", contar)
    try:
        r = _gerar(db, escola.id, preset="mes_anterior", plataformas=("elefante",))
    finally:
        sa_event.remove(db.get_bind(), "before_cursor_execute", contar)
    assert r["elefante"]["alunos_com_atividade"] == len(escola_completa["alunos"])
    assert contagem["n"] <= 10, (
        f"{contagem['n']} SELECTs para {len(escola_completa['alunos'])} alunos — "
        "o custo não pode crescer por aluno")
