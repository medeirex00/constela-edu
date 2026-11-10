"""Análise educacional — Elefante e Matific por ESCOLA × SÉRIE (``GET
/redes/{id}/analise/plataformas``), sem nenhum dado pessoal.

O que estes testes sustentam:

* as métricas por escola × série saem das regras do Relatório por Período (livros novos
  por ``Leitura.data``, questões e Matific pela diferença entre retratos), com a série de
  ``ano_premiavel`` (a 1ª Fase fica fora do recorte) — e com SÓ os retratos que a regra lê
  o resultado é o mesmo das funções oficiais sobre o histórico inteiro;
* SUPRESSÃO: célula com menos de k = 5 alunos não mostra nem o número de alunos nem as
  métricas; a supressão é COMPLEMENTAR com faixa de proteção (as suprimidas somam pelo
  menos 2k), com um motivo SÓ (a resposta não diz qual célula é a pequena), na escola e
  entre as escolas;
* os blocos da escola e da rede somam SÓ o que está visível (nenhuma diferença "bloco −
  partes mostradas" isola uma escola ou célula pequena, em nenhum período), e escola
  suprimida não mostra nem a cobertura;
* nenhum total bruto que refaça uma taxa escondida (subconjunto com menos de k alunos);
* SUPRESSÃO COMPLEMENTAR POR MÉTRICA: a métrica escondida numa célula (subconjunto com
  menos de k) não se refaz pela diferença entre os totais (escola, rede, rede por série) e
  as células que a mostram — conferido por álgebra linear exata sobre as respostas;
* AUSÊNCIA ≠ ZERO: escola sem coleta fica com as métricas nulas e o motivo; coleta parada
  antes do fim do período vira ``coleta_parcial`` (fora da soma da rede); aluno sem conta
  na plataforma fica fora do denominador;
* NENHUM ``aluno_id`` nem nome de criança em resposta nenhuma (varredura do JSON).

Dados INVENTADOS (``test_analise_base``; decisão D13).
"""
import json
from datetime import date, datetime
from fractions import Fraction
from itertools import combinations

import pytest

from app.models import SnapshotMatific
from app.services import relatorios_periodo as rp
from app.services.analise import plataformas as svc
from tests.test_analise_base import (HOJE, PREFIXO_CRIANCA, ler, livros, mundo_plataformas,
                                     nova_escola, nova_rede, retrato_elefante, retrato_matific,
                                     turma_com_alunos)

URL = "/api/v1/redes/{rede}/analise/plataformas"
# Totais brutos que refariam uma taxa escondida: não saem em resposta nenhuma.
BRUTOS = ("questoes_tentativas", "questoes_acertos", "alunos_com_questao", "atividades",
          "estrelas", "alunos_com_atividade", "livros_novos", "tempo_min",
          "livros_com_atividade", "eventos_leitura", "alunos_sem_retrato_questoes")


@pytest.fixture()
def mundo(db, cliente_global, monkeypatch):
    monkeypatch.setattr("app.routers.analise.hoje_br", lambda: HOJE)
    return {**mundo_plataformas(db), "c": cliente_global}


def _get(mundo, rede=None, **params):
    r = mundo["c"].get(URL.format(rede=(rede or mundo["rede"]).id), params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _escola(dados, escola):
    return next(e for e in dados["escolas"] if e["escola_id"] == escola.id)


def _chaves(obj, saida=None):
    saida = set() if saida is None else saida
    if isinstance(obj, dict):
        for k, v in obj.items():
            saida.add(k)
            _chaves(v, saida)
    elif isinstance(obj, list):
        for v in obj:
            _chaves(v, saida)
    return saida


def test_metricas_por_escola_e_serie_com_a_regra_do_relatorio_por_periodo(mundo):
    dados = _get(mundo)
    assert dados["janela"] == {"preset": "ano_letivo", "rotulo": "Ano letivo 2026",
                               "inicio": "2026-01-01", "fim": "2026-12-31", "ano_letivo": 2026,
                               "anos_letivos": [2026]}
    assert dados["modulos"] == {"elefante": True, "matific": True} and dados["k_minimo"] == 5
    alfa = _escola(dados, mundo["escolas"]["alfa"])
    assert alfa["alunos"] == 17                         # 2º + 3º + 5º (a 1ª Fase fica fora)
    (s3,) = [s for s in alfa["series"] if s["serie"] == 3]
    assert s3["alunos"] == 7 and s3["suprimido"] is False
    e = s3["elefante"]
    # 7 crianças com conta (todas têm coleta); 5 leram 8 livros novos em 2026 (a leitura de
    # 2025 não entra).
    assert (e["alunos_medidos"], e["alunos_sem_conta"]) == (7, 0)
    assert (e["alunos_com_leitura"], e["participacao_pct"]) == (5, 71.4)
    assert e["livros_por_aluno"] == 1.14
    assert e["minutos_por_aluno"] == 11.4
    # Nível: K, K, K, K, K, M, M, L → posição média 14,625 → "L".
    assert (e["nivel_medio"], e["nivel_medio_posicao"]) == ("L", 14.63)
    # Questões pela diferença entre os retratos de março e setembro: 63 de 70.
    assert e["taxa_acerto_pct"] == 90.0
    assert e["janela_questoes"]["inicio"] == "2026-03-01T00:10:00-03:00"
    assert e["janela_questoes"]["fim"] == "2026-09-30T00:10:00-03:00"
    assert e["coleta_parcial"] is False and e["coberto_ate"].startswith("2026-09-30T00:10")
    m = s3["matific"]
    # 6 de 7 com retrato: 10 atividades e 30 estrelas cada (o ano começa do zero). Quem não
    # tem retrato fica FORA do denominador, também na participação (6 de 6).
    assert (m["alunos_medidos"], m["alunos_com_retrato"], m["alunos_sem_retrato"]) == (6, 6, 1)
    assert (m["atividades_por_aluno"], m["estrelas_por_aluno"], m["desempenho_medio"]) == (
        10.0, 30.0, 3.0)
    assert m["participacao_pct"] == 100.0
    assert dados["rede"]["alunos"] == 25 and dados["rede"]["alunos_fora_do_recorte"] == 4
    assert not set(BRUTOS) & _chaves(dados)


def test_a_conta_com_os_retratos_essenciais_e_a_das_funcoes_oficiais(db):
    """A regra das questões (``relatorios_periodo._elefante_questoes``) e a do Matific
    (``relatorios_periodo._matific``) sobre o histórico INTEIRO dão o mesmo número que a
    análise, que lê só as coletas que a regra pode usar — inclusive com retrato do ano
    anterior, depois do fim e período no meio do ano."""
    rede = nova_rede(db, nome="Rede Fictícia Equivalente", codigo="3599931")
    e = nova_escola(db, rede, "EMEF Fictícia Equivalente", "35993101")
    alunos = turma_com_alunos(db, e, "4º Ano", 7)
    datas = [datetime(2025, 12, 20, 3, 0), datetime(2026, 2, 1, 3, 0), datetime(2026, 4, 1, 3, 0),
             datetime(2026, 5, 15, 3, 0), datetime(2026, 6, 30, 3, 0), datetime(2026, 8, 1, 3, 0)]
    for i, a in enumerate(alunos[:6]):
        for j, quando in enumerate(datas[i % 3:]):
            retrato_elefante(db, e, a, quando, tentativas=10 * (j + i), acertos=6 * (j + i))
            retrato_matific(db, e, a, quando, atividades=3 * (j + i), estrelas=7 * (j + i))
    # A 7ª criança: série que MISTURA contas — as tentativas caem e os acertos sobem. A regra
    # oficial a tira das questões (``_regrediu``); a análise também.
    for j, quando in enumerate(datas):
        retrato_elefante(db, e, alunos[6], quando, tentativas=100 - 10 * j, acertos=5 * j)
        retrato_matific(db, e, alunos[6], quando, atividades=3 * j, estrelas=7 * j)
    db.commit()
    for preset, ini, fim in (("ano_letivo", None, None), ("tudo", None, None),
                             ("personalizado", date(2026, 3, 1), date(2026, 6, 30)),
                             ("personalizado", date(2025, 12, 1), date(2026, 5, 15))):
        janela = rp.resolver_janela(preset, 2026, inicio=ini, fim=fim, hoje=HOJE)
        coorte = rp._coorte(db, e.id, 2026)
        bloco, por_aluno = rp.BlocoElefante(), {}
        rp._elefante_questoes(db, e.id, coorte, janela, bloco, por_aluno, hoje=date(2026, 8, 3))
        mat_bloco, _ = rp._matific(db, e.id, coorte, janela, 2026)
        dados = svc.plataformas_da_rede(db, rede, preset=preset, inicio=ini, fim=fim,
                                        hoje=date(2026, 8, 3))
        (cel,) = _escola(dados, e)["series"]
        oficial = round(100 * bloco.questoes_acertos / bloco.questoes_tentativas, 1)
        assert cel["elefante"]["taxa_acerto_pct"] == oficial, preset
        regrediu = bloco.cobertura_questoes["alunos_contador_regrediu"]
        assert regrediu == (0 if preset == "tudo" else 1), preset    # sem base, não há queda
        assert cel["elefante"]["contador_regrediu"] is (regrediu > 0), preset
        medidos = len(coorte) - mat_bloco.alunos_sem_retrato
        assert cel["matific"]["alunos_medidos"] == medidos, preset
        assert cel["matific"]["atividades_por_aluno"] == round(mat_bloco.atividades / medidos, 2)
        # Só as coletas essenciais: sem coleta perto das bordas, no máximo 4 por criança
        # (a última antes, a 1ª e a última dentro, a 1ª depois), qualquer que seja o
        # histórico.
        lidos = svc._coletas_das_questoes(db, e.id, janela)
        assert max(len(v) for v in lidos.values()) <= 4
        lidos_m = svc._retratos_essenciais(db, SnapshotMatific, e.id, ("atividades", "estrelas"),
                                           janela.inicio, janela.fim)
        assert max(len(v) for v in lidos_m.values()) <= 3


def test_leituras_em_lote_sao_as_das_funcoes_oficiais_de_uma_escola(db):
    """A análise lê a coorte e o Elefante EM LOTE (todas as escolas e períodos numa consulta
    por fonte). Escola a escola, é a mesma coorte de ``relatorios_periodo._coorte`` e, aluno a
    aluno, os mesmos livros novos, tempo e eventos de ``relatorios_periodo._elefante`` — com
    aluno inativo, leitura e evento gravados na OUTRA escola, tempo nulo, evento que não é de
    leitura e vários períodos de uma vez."""
    from app.models import EventoAluno

    rede = nova_rede(db, nome="Rede Fictícia Lote", codigo="3599935")
    a = nova_escola(db, rede, "EMEF Fictícia Lote A", "35993501")
    b = nova_escola(db, rede, "EMEF Fictícia Lote B", "35993502")
    alunos_a = turma_com_alunos(db, a, "3º Ano", 6)
    alunos_b = turma_com_alunos(db, b, "4º Ano", 5)
    alunos_a[5].status = "inativo"                      # fora da coorte, com leitura
    lv_a, lv_b = livros(db, a, 4, "k"), livros(db, b, 4, "M")
    datas = [datetime(2026, 2, 10, 10), datetime(2026, 5, 4, 11), datetime(2026, 9, 1, 9),
             datetime(2026, 10, 1, 15)]
    for i, aluno in enumerate(alunos_a):
        ler(db, a, aluno, lv_a[: 1 + i % 4], datas[i % 4], minutos=None if i == 2 else 7 + i)
    for i, aluno in enumerate(alunos_b):
        ler(db, b, aluno, lv_b[: 1 + i % 3], datas[(i + 1) % 4], minutos=5)
    ler(db, b, alunos_a[0], lv_b[3:], datas[2])         # leitura do aluno de A gravada em B
    eventos = [(a, alunos_a[1], "leitura", datas[1]), (a, alunos_a[1], "leitura", datas[2]),
               (a, alunos_a[3], "atividade", datas[2]), (b, alunos_a[0], "leitura", datas[3]),
               (b, alunos_b[2], "leitura", datas[0]), (a, alunos_a[5], "leitura", datas[3])]
    for n, (escola, aluno, tipo, quando) in enumerate(eventos):
        db.add(EventoAluno(escola_id=escola.id, aluno_id=aluno.id, plataforma="elefante",
                           tipo_evento=tipo, ocorrido_em=quando, chave_natural=f"lote-{n}",
                           livro_id=(lv_a if escola is a else lv_b)[0].id))
    db.commit()
    periodos = [("ano_letivo", None, None), ("tudo", None, None),
                ("personalizado", date(2026, 3, 1), date(2026, 6, 30)),
                ("personalizado", date(2026, 9, 1), date(2026, 9, 30))]
    janelas = {g: rp.resolver_janela(p, 2026, inicio=i, fim=f, hoje=HOJE)
               for g, (p, i, f) in enumerate(periodos)}
    contagens, coortes = svc._coortes(db, [a, b])
    for escola in (a, b):
        oficial = rp._coorte(db, escola.id, escola.ano_letivo_ativo)
        assert coortes[escola.id] == {aid: {"turma_id": v["turma_id"],
                                            "ano_escolar": v["ano_escolar"]}
                                      for aid, v in oficial.items()}
        assert contagens[escola.id].total + contagens[escola.id].fora == len(oficial)
    assert alunos_a[5].id not in coortes[a.id]
    lote, _ = svc._elefante_em_lote(db, {g: (j, [a.id, b.id]) for g, j in janelas.items()},
                                    coortes)
    algum = False
    for g, janela in janelas.items():
        for escola in (a, b):
            _, oficial = rp._elefante(db, escola.id, rp._coorte(db, escola.id, 2026), janela)
            meu = lote.get((g, escola.id), {})
            assert set(meu) == set(oficial), (periodos[g], escola.nome)
            for aid, v in oficial.items():
                assert {c: meu[aid][c] for c in ("livros_novos", "tempo_min",
                                                 "eventos_leitura")} == {
                    c: v[c] for c in ("livros_novos", "tempo_min", "eventos_leitura")}
                algum = algum or bool(v["livros_novos"] or v["eventos_leitura"])
    assert algum                                         # o mundo tem número de verdade


def _rede_uma_escola(db, codigo: str, serie: list, n: int = 5):
    """Uma escola com ``n`` crianças do 3º ano e a MESMA série de coletas do Elefante
    (``(instante UTC, tentativas, acertos)``) para cada uma."""
    rede = nova_rede(db, nome=f"Rede Fictícia Bordas {codigo}", codigo=codigo,
                     codmun=codigo[-4:])
    e = nova_escola(db, rede, f"EMEF Fictícia Bordas {codigo}", f"{codigo}1")
    for a in turma_com_alunos(db, e, "3º Ano", n):
        for quando, t, ac in serie:
            retrato_elefante(db, e, a, quando, tentativas=t, acertos=ac)
    db.commit()
    return rede, e


def _taxa_oficial(db, e, ini, fim) -> float:
    rel = rp.gerar(db, e.id, preset="personalizado", inicio=ini, fim=fim,
                   plataformas=["elefante"], hoje=HOJE)
    return round(100 * rel["elefante"]["questoes_acertos"]
                 / rel["elefante"]["questoes_tentativas"], 1)


def test_questoes_medidas_em_brasilia_com_a_tolerancia_de_borda(db):
    """Prova 1b da revisão e97 INVERTIDA. Antes, a análise separava antes/dentro/depois
    comparando o instante UTC com a janela em dias de Brasília e guardava só o 1º e o
    último de cada faixa: com uma coleta às 22h e a da 0h10 nas duas bordas, media de
    31/08 22h a 30/09 22h (50,0%), e o Relatório por Período, de 01/09 00h10 a 01/10
    00h10 (73,1%). Agora a seleção usa o critério da regra (Brasília, coleta a até 1 h da
    borda) e o número é o mesmo."""
    serie = [(datetime(2026, 8, 15, 15, 0), 10, 5),
             (datetime(2026, 9, 1, 1, 0), 20, 10),      # 31/08 22h00 (Brasília)
             (datetime(2026, 9, 1, 3, 10), 22, 11),     # 01/09 00h10 — mede o início
             (datetime(2026, 9, 15, 15, 0), 30, 15),
             (datetime(2026, 10, 1, 1, 0), 40, 20),     # 30/09 22h00
             (datetime(2026, 10, 1, 3, 10), 48, 30)]    # 01/10 00h10 — mede o fim
    rede, e = _rede_uma_escola(db, "3599943", serie)
    ini, fim = date(2026, 9, 1), date(2026, 9, 30)
    assert _taxa_oficial(db, e, ini, fim) == 73.1          # 19 de 26 por criança
    dados = svc.plataformas_da_rede(db, rede, preset="personalizado", inicio=ini, fim=fim,
                                    hoje=HOJE)
    el = _escola(dados, e)["elefante"]
    assert el["taxa_acerto_pct"] == 73.1                   # antes: 50,0 (outro intervalo)
    assert el["janela_questoes"]["inicio"] == "2026-09-01T00:10:00-03:00"
    assert el["janela_questoes"]["fim"] == "2026-10-01T00:10:00-03:00"
    assert dados["rede"]["elefante"]["taxa_acerto_pct"] == 73.1
    # As coletas lidas: a última bem antes do início (31/08 22h; a de 15/08 fica de fora), a
    # da borda do início, a 1ª e a última do miolo (15/09 e 30/09 22h) e a da borda do fim.
    janela = rp.resolver_janela("personalizado", 2026, inicio=ini, fim=fim, hoje=HOJE)
    lidas = svc._coletas_das_questoes(db, e.id, janela)
    assert {tuple(r.data_referencia for r in v) for v in lidas.values()} == {
        tuple(q for q, _, _ in serie[1:])}


def test_questoes_contam_a_primeira_linha_de_cada_execucao(db):
    """A sync gravava o resumo e, segundos depois, a linha de leituras, que COPIA as
    questões do retrato mais recente (numa revisão reaplicada, de outro dia). A regra
    oficial conta a execução uma vez, pela primeira linha (``_MESMA_COLETA``). Antes, a
    análise pegava a ÚLTIMA linha antes do início e a última dentro por ``row_number`` —
    a cópia — e media 68,8% em vez dos 83,3% do Relatório por Período."""
    serie = [(datetime(2026, 8, 20, 15, 0, 0), 10, 5),
             (datetime(2026, 8, 20, 15, 0, 40), 8, 8),       # cópia, mesma execução
             (datetime(2026, 9, 28, 15, 0, 0), 40, 30),
             (datetime(2026, 9, 28, 15, 0, 30), 12, 6)]      # cópia, mesma execução
    rede, e = _rede_uma_escola(db, "3599944", serie)
    ini, fim = date(2026, 9, 1), date(2026, 9, 30)
    assert _taxa_oficial(db, e, ini, fim) == 83.3            # 25 de 30 por criança
    dados = svc.plataformas_da_rede(db, rede, preset="personalizado", inicio=ini, fim=fim,
                                    hoje=HOJE)
    assert _escola(dados, e)["elefante"]["taxa_acerto_pct"] == 83.3
    janela = rp.resolver_janela("personalizado", 2026, inicio=ini, fim=fim, hoje=HOJE)
    lidas = svc._coletas_das_questoes(db, e.id, janela)
    assert all([(r.questoes_tentativas, r.questoes_acertos) for r in v] == [(10, 5), (40, 30)]
               for v in lidas.values())


def _mundo_contador_regrediu(db, codigo: str, normais: int):
    """``normais`` crianças do 3º ano com +10 tentativas e +5 acertos (10/5 → 20/10) e uma
    com a série MISTURADA (fusão/colisão): tentativas caem 200 → 150, acertos sobem 20 →
    140 (cenário da prova 1 da revisão e97, dados inventados)."""
    rede = nova_rede(db, nome=f"Rede Fictícia Contador {codigo}", codigo=codigo,
                     codmun=codigo[-4:])
    e = nova_escola(db, rede, f"EMEF Fictícia Contador {codigo}", f"{codigo}1")
    alunos = turma_com_alunos(db, e, "3º Ano", normais + 1)
    marco, outubro = datetime(2026, 3, 2, 15, 0), datetime(2026, 10, 1, 15, 0)
    for a in alunos[:normais]:
        retrato_elefante(db, e, a, marco, tentativas=10, acertos=5)
        retrato_elefante(db, e, a, outubro, tentativas=20, acertos=10)
    retrato_elefante(db, e, alunos[normais], marco, tentativas=200, acertos=20)
    retrato_elefante(db, e, alunos[normais], outubro, tentativas=150, acertos=140)
    db.commit()
    return rede, e


def test_contador_que_regrediu_sai_das_questoes_como_no_relatorio_por_periodo(mundo, db):
    """Prova 1 da revisão e97 INVERTIDA. Antes: a análise somava a criança cujo contador
    diminuiu (tentativas zeradas campo a campo, acertos que subiram) e a taxa de acerto
    passava de 100% — 380% neste cenário (350% no da prova, com 4 + 1), na célula, na
    escola, na rede e na Visão da Escola, sem aviso. Agora a regra é a do Relatório por
    Período: a criança sai das questões (continua no denominador dos livros) e a resposta
    avisa, sem a contagem."""
    rede, e = _mundo_contador_regrediu(db, "3599941", normais=5)
    rel = rp.gerar(db, e.id, preset="ano_letivo", plataformas=["elefante"], hoje=HOJE)
    assert (rel["elefante"]["questoes_tentativas"], rel["elefante"]["questoes_acertos"]) == (
        50, 25)
    assert rel["elefante"]["cobertura_questoes"]["alunos_contador_regrediu"] == 1
    dados = _get(mundo, rede=rede)
    escola = _escola(dados, e)
    (cel,) = escola["series"]
    for bloco in (cel["elefante"], escola["elefante"], dados["rede"]["elefante"]):
        assert bloco["taxa_acerto_pct"] == 50.0                     # = o Relatório por Período
        assert bloco["contador_regrediu"] is True
        assert bloco["texto_contador_regrediu"] == svc.TEXTO_CONTADOR_REGREDIU
    assert cel["elefante"]["alunos_medidos"] == 6                  # segue com conta (livros)
    assert "alunos_contador_regrediu" not in json.dumps(dados)     # sem a contagem
    r = mundo["c"].get(f"/api/v1/escolas/{e.id}/analise")
    assert r.status_code == 200, r.text
    assert r.json()["plataformas"]["elefante"]["taxa_acerto_pct"] == 50.0
    assert r.json()["plataformas"]["elefante"]["contador_regrediu"] is True
    # O cenário literal da prova (4 normais + 1): sem a criança misturada sobram 4 com
    # questões (< k) — a taxa some, em vez de sair 350%.
    rede4, e4 = _mundo_contador_regrediu(db, "3599942", normais=4)
    esc4 = _escola(_get(mundo, rede=rede4), e4)
    assert esc4["elefante"]["taxa_acerto_pct"] is None
    assert esc4["series"][0]["elefante"]["taxa_acerto_pct"] is None
    assert esc4["elefante"]["contador_regrediu"] is True


def test_sem_contador_regredido_nao_ha_aviso(mundo):
    alfa = _escola(_get(mundo), mundo["escolas"]["alfa"])
    assert alfa["elefante"]["contador_regrediu"] is False
    assert alfa["elefante"]["texto_contador_regrediu"] is None
    beta = _escola(_get(mundo), mundo["escolas"]["beta"])            # sem coleta: sem dado
    assert beta["elefante"]["contador_regrediu"] is None


def test_celula_pequena_e_suprimida_com_complemento_e_motivo_unico(mundo):
    alfa = _escola(_get(mundo), mundo["escolas"]["alfa"])
    por_serie = {s["serie"]: s for s in alfa["series"]}
    assert set(por_serie) == {2, 3, 5}
    # 2º ano: 4 crianças (< 5) — nem o número de alunos aparece.
    assert por_serie[2] == {"serie": 2, "alunos": None, "suprimido": True,
                            "motivo_supressao": svc.SUPRIMIDO,
                            "texto_supressao": svc.TEXTO_SUPRESSAO,
                            "elefante": None, "matific": None}
    # 5º ano: 6 crianças, mas é a menor visível — some junto (4 + 6 ≥ 2k), senão 17 − 7 − 6
    # = 4 diria o 2º ano pela diferença do total. O motivo é o MESMO das duas.
    assert por_serie[5] == {**por_serie[2], "serie": 5}
    assert por_serie[3]["suprimido"] is False
    # Os números das células pequenas (77 atividades, 99 estrelas, nível Z) não aparecem,
    # nem no bloco da escola (que soma só a série visível).
    texto = json.dumps(alfa)
    assert "77" not in texto and "99" not in texto and '"Z"' not in texto
    assert alfa["blocos_parciais"] is True and alfa["texto_blocos"]
    assert alfa["elefante"]["alunos_medidos"] == por_serie[3]["elefante"]["alunos_medidos"] == 7
    assert alfa["matific"] == por_serie[3]["matific"]


def test_faixa_de_protecao_1_5_20_nao_fixa_a_celula_pequena(db):
    """Sonda A: 1º ano com 1 criança, 2º com 5 e 3º com 20. Antes, "menos_de_k" e
    "complementar" diziam qual célula era a pequena e a união (6) a fixava em 1. Agora o
    motivo é um só e a união suprimida chega a 2k: o 1º ano pode ter de 1 a 4 crianças."""
    rede = nova_rede(db, nome="Rede Fictícia Sonda A", codigo="3599932")
    e = nova_escola(db, rede, "EMEF Fictícia Sonda A", "35993201")
    outra = nova_escola(db, rede, "EMEF Fictícia Sonda B", "35993202")
    for serie, n in (("1º Ano", 1), ("2º Ano", 5), ("3º Ano", 20)):
        for a in turma_com_alunos(db, e, serie, n):
            retrato_elefante(db, e, a, datetime(2026, 9, 1, 3, 0))
    for a in turma_com_alunos(db, outra, "3º Ano", 30):
        retrato_elefante(db, outra, a, datetime(2026, 9, 1, 3, 0))
    db.commit()
    dados = svc.plataformas_da_rede(db, rede, hoje=HOJE)
    esc = _escola(dados, e)
    supr = [c for c in esc["series"] if c["suprimido"]]
    assert {c["motivo_supressao"] for c in supr} == {svc.SUPRIMIDO}
    assert len({c["texto_supressao"] for c in supr}) == 1
    visiveis = sum(c["alunos"] for c in esc["series"] if not c["suprimido"])
    uniao = esc["alunos"] - visiveis
    assert uniao >= 2 * dados["k_minimo"]
    # O intervalo de quem fica no 1º ano, para quem só vê a resposta: qualquer valor de 1
    # a k−1 continua possível (a união e o número de células não o fixam).
    possiveis = {x for x in range(1, uniao) if uniao - x >= len(supr) - 1}
    assert {1, 2, 3, 4} <= possiveis
    # Sem série visível, os blocos da escola não somam nada (nunca a soma das escondidas).
    assert esc["elefante"]["motivo_sem_dado"] == svc.SERIES_SUPRIMIDAS
    assert esc["elefante"]["alunos_medidos"] is None


def test_filtro_de_serie_nao_desfaz_a_supressao(mundo):
    """A supressão é decidida sobre a tabela INTEIRA: filtrar o 5º ano não mostra a célula
    que a visão completa escondeu em complemento — senão 17 − 7 (3º) − 6 (5º) revelaria o
    2º ano. E o total da rede no 5º ano some (ele menos a Beta daria a célula da Alfa)."""
    alfa, beta = mundo["escolas"]["alfa"], mundo["escolas"]["beta"]
    so5 = _get(mundo, serie=5)
    a = _escola(so5, alfa)
    assert a["suprimido"] is True and a["motivo_supressao"] == svc.SUPRIMIDO
    assert a["alunos"] is None and a["series"] == [] and a["matific"] is None
    b = _escola(so5, beta)
    assert b["suprimido"] is False and b["alunos"] == 8
    assert so5["rede"]["suprimido"] is True and so5["rede"]["alunos"] is None
    assert so5["rede"]["matific"] is None
    so2 = _get(mundo, serie=2)
    assert _escola(so2, alfa)["motivo_supressao"] == svc.SUPRIMIDO
    # O 3º ano (sem célula suprimida) mostra o total da rede.
    so3 = _get(mundo, serie=3)
    assert so3["rede"]["suprimido"] is False and so3["rede"]["alunos"] == 7
    # A relação usa as mesmas decisões: o 5º ano da Alfa fica fora, suprimido.
    rel = mundo["c"].get(f"/api/v1/redes/{mundo['rede'].id}/analise/relacao",
                         params={"indicador": "saresp", "componente": "mt",
                                 "metrica": "estrelas_por_aluno"}).json()
    par = next(p for p in rel["pares"] if p["escola_id"] == alfa.id)
    assert par["valor_plataforma"] is None


def _rede_xyz(db, nome, codigo, tamanhos: dict[str, tuple[int, bool, bool]]):
    """Escolas X, Y, Z do 5º ano: (crianças, tem Elefante, tem Matific). Cada criança com
    Elefante lê ``livros`` livros (X lê 3 por criança, para a soma denunciar)."""
    rede = nova_rede(db, nome=nome, codigo=codigo)
    escolas = {}
    for i, (letra, (n, com_ele, com_mat)) in enumerate(tamanhos.items()):
        e = escolas[letra] = nova_escola(db, rede, f"EMEF Fictícia {letra}", f"{codigo}{i:01d}")
        bk = livros(db, e, 4, "K")
        for a in turma_com_alunos(db, e, "5º Ano", n):
            if com_ele:
                ler(db, e, a, bk[:(3 if letra == "X" else 1)], datetime(2026, 5, 1, 12, 0))
                retrato_elefante(db, e, a, datetime(2026, 9, 29, 3, 0), tentativas=7, acertos=2)
            if com_mat:
                retrato_matific(db, e, a, datetime(2026, 9, 29, 3, 0),
                                atividades=(9 if letra == "X" else 1), estrelas=2)
    db.commit()
    return rede, escolas


def _confere_rede_igual_as_visiveis(dados):
    """Para cada plataforma, o bloco da rede é a soma das escolas VISÍVEIS (com a coleta
    em dia): nada sobra para isolar uma escola suprimida."""
    for p in ("elefante", "matific"):
        visiveis = [e for e in dados["escolas"] if not e["suprimido"]
                    and e["cobertura"][p] == svc.COBERTURA_OK and e[p]["alunos_medidos"]]
        soma = sum(e[p]["alunos_medidos"] for e in visiveis)
        bloco = dados["rede"][p]
        assert (bloco["alunos_medidos"] or 0) == soma, p
        assert dados["rede"]["escolas_com_dado"][p] == len(visiveis), p


@pytest.mark.parametrize("periodo", [{}, {"periodo": "personalizado", "inicio": "2026-06-01",
                                          "fim": "2026-09-30"}])
def test_cobertura_diferente_nao_reabre_escola_suprimida(db, periodo):
    """Sonda F (M2/SEG-1): X (3 crianças, com Elefante) suprimida; Y (8, SEM Elefante, com
    Matific) suprimida em complemento; Z (20) visível. Antes, "rede − Z" no Elefante dava
    os 3 alunos e os 9 livros de X. Agora o bloco da rede soma só as visíveis — em qualquer
    período —, e as suprimidas não mostram nem a cobertura."""
    rede, esc = _rede_xyz(db, "Rede Fictícia Sonda F", "3599933",
                          {"X": (3, True, True), "Y": (8, False, True), "Z": (20, True, True)})
    preset = periodo.get("periodo", "ano_letivo")
    datas = {k: date.fromisoformat(v) for k, v in periodo.items() if k in ("inicio", "fim")}
    dados = svc.plataformas_da_rede(db, rede, preset=preset, **datas, hoje=HOJE)
    por_nome = {e["nome"]: e for e in dados["escolas"]}
    x, y, z = (por_nome[f"EMEF Fictícia {c}"] for c in "XYZ")
    assert x["suprimido"] and y["suprimido"] and not z["suprimido"]
    assert x["motivo_supressao"] == y["motivo_supressao"] == svc.SUPRIMIDO
    for s in (x, y):
        assert s["cobertura"] is None and s["ultima_coleta"] is None and s["alunos"] is None
    _confere_rede_igual_as_visiveis(dados)
    assert dados["rede"]["elefante"]["alunos_medidos"] == z["elefante"]["alunos_medidos"] == 20
    assert dados["rede"]["elefante"]["livros_por_aluno"] == z["elefante"]["livros_por_aluno"]
    for chave in ("alunos_medidos", "participacao_pct", "atividades_por_aluno",
                  "estrelas_por_aluno", "desempenho_medio"):
        assert dados["rede"]["matific"][chave] == z["matific"][chave], chave
    assert dados["rede"]["texto_blocos"] and dados["rede"]["escopo_blocos"] == "escolas_visiveis"
    # As listas de cobertura da rede não dizem nada das suprimidas.
    ids_suprimidas = {esc["X"].id, esc["Y"].id}
    for lista in (dados["cobertura"]["escolas_sem_coleta"],
                  *dados["cobertura"]["escolas_sem_coleta_no_periodo"].values(),
                  *dados["cobertura"]["escolas_coleta_parcial"].values()):
        assert not ids_suprimidas & set(lista)
    # O total de alunos da rede menos as visíveis = a união suprimida, que é ≥ 2k.
    assert dados["rede"]["alunos"] - z["alunos"] >= 2 * dados["k_minimo"]


@pytest.mark.parametrize("periodo", ["ano_letivo", "tudo"])
def test_cobertura_da_rede_nao_mostra_datas_das_suprimidas(db, periodo):
    """A coleta e o primeiro evento do Elefante são lidos de TODAS as escolas medidas numa
    consulta só, e a escola suprimida (k = 5) sai depois, em Python: nem a data do primeiro
    evento dela, nem a última coleta dela aparecem na cobertura da rede. As suprimidas aqui
    têm o evento mais ANTIGO e a coleta mais RECENTE da rede — se vazassem, as datas da rede
    seriam as delas."""
    from app.models import EventoAluno

    rede, esc = _rede_xyz(db, "Rede Fictícia Datas Suprimidas", "3599934",
                          {"X": (3, True, True), "Y": (8, False, True), "Z": (20, True, True)})
    x, y, z = esc["X"], esc["Y"], esc["Z"]
    aluno = {e.id: db.query(svc.Aluno).filter_by(escola_id=e.id).first() for e in (x, y, z)}
    for n, (escola, quando) in enumerate([(z, datetime(2026, 3, 2, 12, 0)),
                                          (z, datetime(2026, 4, 6, 12, 0)),
                                          (x, datetime(2025, 2, 3, 12, 0)),
                                          (y, datetime(2025, 1, 6, 12, 0))]):
        db.add(EventoAluno(escola_id=escola.id, aluno_id=aluno[escola.id].id, plataforma="elefante",
                           tipo_evento="leitura", ocorrido_em=quando, chave_natural=f"datas-sup-{n}"))
    # A coleta mais recente da rede é a das suprimidas (Z parou em 29/09).
    retrato_elefante(db, x, aluno[x.id], datetime(2026, 10, 4, 3, 0), tentativas=9, acertos=3)
    retrato_matific(db, x, aluno[x.id], datetime(2026, 10, 4, 3, 0), atividades=11, estrelas=3)
    retrato_matific(db, y, aluno[y.id], datetime(2026, 10, 4, 3, 0), atividades=2, estrelas=3)
    db.commit()

    dados = svc.plataformas_da_rede(db, rede, preset=periodo, hoje=HOJE)
    por_id = {e["escola_id"]: e for e in dados["escolas"]}
    assert por_id[x.id]["suprimido"] and por_id[y.id]["suprimido"] and not por_id[z.id]["suprimido"]
    cob = dados["cobertura"]
    # O primeiro evento é o de Z (02/03/2026), nunca o de X (2025) nem o de Y.
    assert cob["primeiro_evento_elefante"] == datetime(2026, 3, 2, 12, 0).isoformat()
    # A última coleta e os dias desde ela são os de Z (29/09), nunca os de 04/10 das suprimidas.
    ultima_z = por_id[z.id]["ultima_coleta"]
    assert ultima_z["elefante"] is not None and ultima_z["elefante"].startswith("2026-09-")
    assert cob["ultima_coleta"] == ultima_z
    assert cob["dias_desde_ultima_coleta"] == (HOJE - date.fromisoformat(
        max(ultima_z.values())[:10])).days
    assert "2026-10-0" not in json.dumps(cob) and "2025-" not in json.dumps(cob)


def test_sonda_f_literal_3_6_9_nao_recompoe_x(db):
    """O cenário literal de M2 (X = 3, Y = 6, Z = 9): com a faixa de proteção as três somem
    juntas, e o bloco da rede não tem escola visível para somar (sem dado, nunca a soma
    das escondidas)."""
    rede, _ = _rede_xyz(db, "Rede Fictícia Sonda F2", "3599934",
                        {"X": (3, True, True), "Y": (6, False, True), "Z": (9, True, True)})
    dados = svc.plataformas_da_rede(db, rede, hoje=HOJE)
    assert all(e["suprimido"] for e in dados["escolas"])
    assert dados["rede"]["alunos"] == 18
    for p in ("elefante", "matific"):
        assert dados["rede"][p]["alunos_medidos"] is None
        assert dados["rede"][p]["motivo_sem_dado"] == svc.SEM_ESCOLA_VISIVEL
        assert dados["rede"]["escolas_com_dado"][p] == 0


def test_subconjunto_menor_que_k_nao_tem_total_que_refaca_a_taxa(db):
    """Sonda B (M4/SEG-2): célula VISÍVEL de 10 crianças, só 1 com questões no Elefante e
    só 2 com retrato do Matific. As taxas somem — e nenhum total bruto as refaz."""
    rede = nova_rede(db, nome="Rede Fictícia Sonda B", codigo="3599935")
    e = nova_escola(db, rede, "EMEF Fictícia Sonda B", "35993501")
    alunos = turma_com_alunos(db, e, "4º Ano", 10)
    for a in alunos:
        retrato_elefante(db, e, a, datetime(2026, 3, 1, 3, 0))
        retrato_elefante(db, e, a, datetime(2026, 9, 30, 3, 0))
    retrato_elefante(db, e, alunos[0], datetime(2026, 10, 1, 3, 0), tentativas=12, acertos=3)
    for a, (atv, est) in zip(alunos[:2], ((15, 40), (2, 3))):
        retrato_matific(db, e, a, datetime(2026, 9, 30, 3, 0), atividades=atv, estrelas=est)
    db.commit()
    dados = svc.plataformas_da_rede(db, rede, hoje=HOJE)
    (cel,) = _escola(dados, e)["series"]
    assert cel["suprimido"] is False and cel["alunos"] == 10
    el, mt = cel["elefante"], cel["matific"]
    assert el["alunos_medidos"] == 10 and el["taxa_acerto_pct"] is None
    assert mt["alunos_medidos"] == 2
    assert mt["atividades_por_aluno"] is None and mt["estrelas_por_aluno"] is None
    assert mt["desempenho_medio"] is None and mt["participacao_pct"] is None
    assert mt["motivo_sem_dado"] == svc.POUCOS_MEDIDOS and mt["texto_sem_dado"]
    assert not set(BRUTOS) & _chaves(dados)
    assert el["coleta_parcial"] is False and mt["coleta_parcial"] is False


def test_matific_com_poucos_ativos_esconde_estrelas_e_desempenho(db):
    """Com ≥ k alunos com retrato mas < k com atividade, "estrelas ÷ atividades" das duas
    médias refaria o desempenho escondido: as estrelas por aluno somem junto."""
    rede = nova_rede(db, nome="Rede Fictícia Poucos Ativos", codigo="3599936")
    e = nova_escola(db, rede, "EMEF Fictícia Poucos Ativos", "35993601")
    alunos = turma_com_alunos(db, e, "3º Ano", 8)
    for i, a in enumerate(alunos):
        retrato_matific(db, e, a, datetime(2026, 9, 30, 3, 0), atividades=6 if i < 2 else 0,
                        estrelas=20 if i < 2 else 0)
    db.commit()
    (cel,) = _escola(svc.plataformas_da_rede(db, rede, hoje=HOJE), e)["series"]
    mt = cel["matific"]
    assert mt["alunos_medidos"] == 8 and mt["atividades_por_aluno"] == 1.5
    assert mt["estrelas_por_aluno"] is None and mt["desempenho_medio"] is None


# --- Supressão complementar por métrica ---------------------------------------------------

def _posto(linhas: list[list[Fraction]]) -> int:
    """Posto de uma matriz de frações (eliminação de Gauss exata)."""
    m = [list(linha) for linha in linhas]
    posto = 0
    for col in range(len(m[0]) if m else 0):
        piv = next((i for i in range(posto, len(m)) if m[i][col] != 0), None)
        if piv is None:
            continue
        m[posto], m[piv] = m[piv], m[posto]
        for i in range(len(m)):
            if i != posto and m[i][col] != 0:
                f = m[i][col] / m[posto][col]
                m[i] = [a - f * b for a, b in zip(m[i], m[posto])]
        posto += 1
    return posto


def _celulas_com_dado(dados: dict, plataforma: str) -> dict:
    """{(escola_id, série): célula} — as células VISÍVEIS que os totais somam."""
    return {(e["escola_id"], c["serie"]): c for e in dados["escolas"] if not e["suprimido"]
            for c in e["series"]
            if not c["suprimido"] and c[plataforma] and c[plataforma]["alunos_medidos"]}


# Métricas DERIVADAS: no Matific, as atividades e as estrelas por aluno dividem as duas
# somas pelos mesmos alunos medidos, e o desempenho é estrelas ÷ atividades — duas das três
# médias mostradas num bloco refazem a terceira.
_TRIO_DERIVADO = {"matific": ("atividades_por_aluno", "estrelas_por_aluno", "desempenho_medio")}


def _revela(bloco: dict | None, plataforma: str, chave: str) -> bool:
    """Se o bloco FIXA o número por trás de ``chave``: mostrado, ou refeito pelas outras
    duas médias do trio derivado (atividades = estrelas ÷ desempenho; estrelas =
    atividades × desempenho; desempenho = estrelas ÷ atividades)."""
    if not bloco:
        return False
    if bloco.get(chave) is not None:
        return True
    trio = _TRIO_DERIVADO.get(plataforma, ())
    return chave in trio and all(bloco.get(c) is not None for c in trio if c != chave)


def _somas_expostas(completa: dict, por_serie: dict[int, dict], plataforma: str, chave: str,
                    escondidas: dict[tuple[int, int], int], k: int = 5) -> list:
    """Os conjuntos de células com ``chave`` ESCONDIDA (e crianças no subconjunto) cuja
    soma as respostas fixam com menos de ``k`` crianças: cada total que FIXA a métrica
    (mostrada ou refeita pelas outras duas do trio derivado — ``_revela``) é uma equação
    "soma das células"; as células que a fixam são conhecidas. Um conjunto é exposto
    quando o seu indicador está no espaço das equações."""
    celulas = _celulas_com_dado(completa, plataforma)
    ocultas = [a for a, c in celulas.items()
               if not _revela(c[plataforma], plataforma, chave) and escondidas.get(a, 0) > 0]
    pos = {a: j for j, a in enumerate(ocultas)}
    linhas: list[list[Fraction]] = []

    def equacao(atomos):
        linha = [Fraction(0)] * len(ocultas)
        for a in atomos:
            if a in pos:
                linha[pos[a]] = Fraction(1)
        if any(linha):
            linhas.append(linha)

    for e in completa["escolas"]:
        if not e["suprimido"] and _revela(e[plataforma], plataforma, chave):
            equacao([a for a in celulas if a[0] == e["escola_id"]])
    if _revela(completa["rede"][plataforma], plataforma, chave):
        equacao(list(celulas))
    for serie, dados in por_serie.items():
        if _revela(dados["rede"][plataforma], plataforma, chave):
            equacao([a for a in celulas if a[1] == serie])
    expostos = []
    base = _posto(linhas) if linhas else 0
    for r in range(1, len(ocultas) + 1):
        for conjunto in combinations(range(len(ocultas)), r):
            if sum(escondidas[ocultas[j]] for j in conjunto) >= k or not linhas:
                continue
            alvo = [Fraction(1 if j in conjunto else 0) for j in range(len(ocultas))]
            if _posto(linhas + [alvo]) == base:
                expostos.append([ocultas[j] for j in conjunto])
    return expostos


def _escola_matific(db, rede, nome: str, inep: str, series: dict[int, tuple]) -> tuple:
    """Uma escola com, por série, ``(crianças, ativas, atividades, estrelas)``: as ativas
    ganham ``atividades``/``estrelas`` no ano letivo, as outras têm coleta sem ganho.
    Devolve a escola e {(escola_id, série): ativas}."""
    e = nova_escola(db, rede, nome, inep)
    ativas = {}
    for serie, (n, ativos, atv, est) in series.items():
        for i, a in enumerate(turma_com_alunos(db, e, f"{serie}º Ano", n)):
            ativo = i < ativos
            retrato_matific(db, e, a, datetime(2026, 10, 1, 15, 0),
                            atividades=atv if ativo else 0, estrelas=est if ativo else 0)
        ativas[(e.id, serie)] = ativos
    return e, ativas


def _respostas(db, rede, series=(1, 2, 3, 4, 5)) -> tuple[dict, dict]:
    completa = svc.plataformas_da_rede(db, rede, hoje=HOJE)
    return completa, {s: svc.plataformas_da_rede(db, rede, serie=s, hoje=HOJE) for s in series}


def test_metrica_escondida_numa_serie_nao_se_refaz_pelo_total_da_escola(db, cliente_global,
                                                                        monkeypatch):
    """Prova 2 da revisão e97 INVERTIDA. 3º ano com 7 crianças e UMA ativa (10 atividades,
    50 estrelas); 4º ano com 6, todas com 10 e 30. A célula do 3º esconde estrelas e
    desempenho (menos de k ativas); antes, o bloco da escola (17,69 estrelas por aluno;
    desempenho 3,29) e o da rede os mostravam, e "escola − 4º ano" dava as 50 estrelas e o
    desempenho 5,0 da criança. Agora os totais escondem as duas métricas, com o porquê."""
    monkeypatch.setattr("app.routers.analise.hoje_br", lambda: HOJE)
    rede = nova_rede(db, nome="Rede Fictícia Complemento", codigo="3599945", codmun="9945")
    e, ativas = _escola_matific(db, rede, "EMEF Fictícia Complemento", "35994501",
                                {3: (7, 1, 10, 50), 4: (6, 6, 10, 30)})
    db.commit()
    completa, por_serie = _respostas(db, rede)
    esc = _escola(completa, e)
    cel = {c["serie"]: c["matific"] for c in esc["series"]}
    assert cel[3]["estrelas_por_aluno"] is None and cel[3]["desempenho_medio"] is None
    assert cel[4]["estrelas_por_aluno"] == 30.0
    for bloco in (esc["matific"], completa["rede"]["matific"]):
        assert bloco["estrelas_por_aluno"] is None and bloco["desempenho_medio"] is None
        assert bloco["metricas_protegidas"] == ["estrelas_por_aluno", "desempenho_medio"]
        assert bloco["texto_metricas_protegidas"] == svc.TEXTO_METRICAS_PROTEGIDAS.format(k=5)
        assert bloco["atividades_por_aluno"] == 5.38          # o resto do total continua
    assert cel[4]["metricas_protegidas"] == [] and cel[4]["texto_metricas_protegidas"] is None
    # Por série: o 4º ano (sem célula escondida) mostra o total; o 3º, não.
    assert por_serie[4]["rede"]["matific"]["estrelas_por_aluno"] == 30.0
    assert por_serie[3]["rede"]["matific"]["estrelas_por_aluno"] is None
    for chave in ("estrelas_por_aluno", "desempenho_medio"):
        assert _somas_expostas(completa, por_serie, "matific", chave, ativas) == []
    # A rota da escola (Visão da Escola), para quem lê a rede, é a mesma.
    r = cliente_global.get(f"/api/v1/escolas/{e.id}/analise")
    assert r.status_code == 200, r.text
    assert r.json()["plataformas"]["matific"] == esc["matific"]


def test_complemento_por_metrica_mostra_o_total_quando_as_escondidas_somam_k(db):
    """Controle: 3º ano com 2 ativas e 4º com 3 (escondidas nas duas células), 5º com 6.
    As escondidas somam 5 = k: o total da escola mostra a métrica (a diferença dá só a soma
    de 5 crianças, a mesma proteção da célula) e nenhuma célula se isola."""
    rede = nova_rede(db, nome="Rede Fictícia Complemento K", codigo="3599946", codmun="9946")
    e, ativas = _escola_matific(db, rede, "EMEF Fictícia Complemento K", "35994601",
                                {3: (7, 2, 10, 20), 4: (7, 3, 10, 40), 5: (6, 6, 10, 30)})
    db.commit()
    completa, por_serie = _respostas(db, rede)
    esc = _escola(completa, e)
    assert esc["matific"]["estrelas_por_aluno"] is not None
    assert esc["matific"]["metricas_protegidas"] == []
    assert completa["rede"]["matific"]["estrelas_por_aluno"] is not None
    assert por_serie[5]["rede"]["matific"]["estrelas_por_aluno"] == 30.0
    assert por_serie[3]["rede"]["matific"]["estrelas_por_aluno"] is None
    assert por_serie[4]["rede"]["matific"]["estrelas_por_aluno"] is None   # 3 ativas na série
    assert _somas_expostas(completa, por_serie, "matific", "estrelas_por_aluno", ativas) == []


@pytest.mark.parametrize("com_d", [False, True])
def test_complemento_por_metrica_entre_as_escolas_da_rede(db, com_d):
    """Escola × rede. A: 3º com 1 ativa (escondida) → o total de A esconde. C: 3º com 2 e
    4º com 3 ativas → o total de C MOSTRA (5 = k). Se a rede somasse as escondidas de todas
    as escolas (6 ≥ k) e mostrasse, "rede − total de C − células mostradas" isolaria a
    criança de A: a rede esconde. Com D (3º com 4 ativas, total escondido), as escondidas
    das escolas que esconderam somam 5 = k e a rede pode mostrar."""
    rede = nova_rede(db, nome=f"Rede Fictícia Complemento R{int(com_d)}",
                     codigo=f"359994{7 + int(com_d)}", codmun=f"994{7 + int(com_d)}")
    ativas = {}
    especificacao = {"A": {3: (7, 1, 10, 50), 4: (6, 6, 10, 30)},
                     "B": {4: (6, 6, 10, 20)},
                     "C": {3: (7, 2, 10, 20), 4: (7, 3, 10, 40), 5: (6, 6, 10, 30)}}
    if com_d:
        especificacao["D"] = {3: (7, 4, 10, 10), 4: (6, 6, 10, 30)}
    escolas = {}
    for i, (letra, series) in enumerate(especificacao.items()):
        escolas[letra], a = _escola_matific(db, rede, f"EMEF Fictícia Rede {letra}",
                                            f"{rede.codigo_ibge}{i}", series)
        ativas.update(a)
    db.commit()
    completa, por_serie = _respostas(db, rede)
    total = {letra: _escola(completa, e)["matific"] for letra, e in escolas.items()}
    assert total["A"]["estrelas_por_aluno"] is None
    assert total["C"]["estrelas_por_aluno"] is not None
    rede_m = completa["rede"]["matific"]
    if com_d:
        assert total["D"]["estrelas_por_aluno"] is None
        assert rede_m["estrelas_por_aluno"] is not None and rede_m["metricas_protegidas"] == []
    else:
        assert rede_m["estrelas_por_aluno"] is None
        assert "estrelas_por_aluno" in rede_m["metricas_protegidas"]
    for chave in ("estrelas_por_aluno", "desempenho_medio"):
        assert _somas_expostas(completa, por_serie, "matific", chave, ativas) == []


# --- O desempenho do Matific é derivado (estrelas ÷ atividades) -----------------------------

def _candidatos(mostrado: float, divisor: int, teto: int = 5000) -> set[int]:
    """Inteiros v com round(v / divisor, 2) == mostrado (o arredondamento da resposta)."""
    return {v for v in range(teto) if svc._arred(v / divisor, 2) == mostrado}


def _soma_admitida(bloco: dict, chave: str, teto: int = 5000) -> set[int] | None:
    """As somas (de atividades ou de estrelas, pela ``chave`` da média por aluno) que um
    bloco do Matific admite, pelo arredondamento das médias: pela própria média × alunos
    medidos, ou refeitas pela outra soma e o desempenho (atividades = estrelas ÷
    desempenho; estrelas = atividades × desempenho). None: nada na resposta a restringe."""
    n = bloco["alunos_medidos"]
    if bloco[chave] is not None:
        return _candidatos(bloco[chave], n, teto)
    outra = ("estrelas_por_aluno" if chave == "atividades_por_aluno"
             else "atividades_por_aluno")
    if bloco[outra] is None or bloco["desempenho_medio"] is None:
        return None
    outras = _candidatos(bloco[outra], n, teto)
    if chave == "atividades_por_aluno":
        return {a for a in range(1, teto) for s in outras
                if svc._arred(s / a, 2) == bloco["desempenho_medio"]}
    return {s for s in range(teto) for a in outras
            if a and svc._arred(s / a, 2) == bloco["desempenho_medio"]}


def _recompor(total: dict, chave: str, mostradas: list[dict]) -> set[int] | None:
    """"Total − células que mostram a média": as somas possíveis das células que a escondem
    (None = qualquer uma, a resposta não as restringe)."""
    saida = _soma_admitida(total, chave)
    if saida is None:
        return None
    for c in mostradas:
        parte = _candidatos(c[chave], c["alunos_medidos"])
        saida = {a - x for a in saida for x in parte}
    return saida


def _escola_mista(db, rede, nome: str, inep: str, series: dict[int, tuple]) -> tuple:
    """Como ``_escola_matific``, com ``(crianças, medidas, ativas, atividades, estrelas)``
    por série: só as ``medidas`` primeiras crianças têm coleta do Matific. Devolve a escola
    e {(escola_id, série): (medidas, ativas)}."""
    e = nova_escola(db, rede, nome, inep)
    celulas = {}
    for serie, (n, medidas, ativas, atv, est) in series.items():
        for i, a in enumerate(turma_com_alunos(db, e, f"{serie}º Ano", n)[:medidas]):
            ativa = i < ativas
            retrato_matific(db, e, a, datetime(2026, 10, 1, 15, 0),
                            atividades=atv if ativa else 0, estrelas=est if ativa else 0)
        celulas[(e.id, serie)] = (medidas, ativas)
    return e, celulas


def test_checador_refaz_as_atividades_pelo_desempenho_e_pelas_estrelas():
    """O checador conta a métrica DERIVADA: um total que esconde as atividades e mostra as
    estrelas por aluno e o desempenho as FIXA (estrelas ÷ desempenho) — a forma da resposta
    de 9971f88 na prova do revisor, que o checador antigo (chave a chave) não via. Sem o
    desempenho no total, nada se refaz."""
    def bloco(medidos, atv, est, des):
        return {"alunos_medidos": medidos, "atividades_por_aluno": atv,
                "estrelas_por_aluno": est, "desempenho_medio": des}

    def resposta(desempenho_do_total):
        total = bloco(15, None, 5.0, desempenho_do_total)
        series = [{"serie": 3, "suprimido": False, "matific": bloco(3, None, None, None)},
                  {"serie": 4, "suprimido": False, "matific": bloco(6, 3.33, None, None)},
                  {"serie": 5, "suprimido": False, "matific": bloco(6, 10.0, 30.0, 3.0)}]
        return {"escolas": [{"escola_id": 1, "suprimido": False, "matific": total,
                             "series": series}],
                "rede": {"matific": dict(total)}}

    medidos = {(1, 3): 3}
    assert _somas_expostas(resposta(2.5), {}, "matific", "atividades_por_aluno",
                           medidos) == [[(1, 3)]]
    assert _somas_expostas(resposta(None), {}, "matific", "atividades_por_aluno", medidos) == []
    # As estrelas da célula com atividades e desempenho mostrados também se refazem.
    assert _revela(bloco(6, 3.0, None, 2.0), "matific", "estrelas_por_aluno")
    assert not _revela(bloco(6, None, 5.0, None), "matific", "atividades_por_aluno")


def test_desempenho_do_total_nao_refaz_as_atividades_escondidas_em_complemento(db):
    """Prova do revisor (e97n, 9971f88 — test_prova_rv_complemento_cruzado, teste a)
    INVERTIDA. 3º ano com 7 crianças e só 3 com coleta (7, 11 e 13 atividades): a célula
    não mostra nada. 4º com 6 medidas e 2 ativas; 5º com 6 ativas. Os totais da escola e da
    rede escondiam as atividades em complemento, mas mostravam as estrelas por aluno e o
    desempenho: estrelas ÷ desempenho − 4º − 5º dava EXATAMENTE 31, as atividades das 3
    crianças. Agora o desempenho some junto com as atividades; as estrelas por aluno (soma
    de 5 crianças escondidas, = k) continuam."""
    rede = nova_rede(db, nome="Rede Fictícia Complemento Cruzado", codigo="3599961",
                     codmun="9961")
    e = nova_escola(db, rede, "EMEF Fictícia Complemento Cruzado", "35996101")
    quando = datetime(2026, 10, 1, 15, 0)
    t3 = turma_com_alunos(db, e, "3º Ano", 7)
    for a, atv in zip(t3[:3], (7, 11, 13)):
        retrato_matific(db, e, a, quando, atividades=atv, estrelas=2 * atv)
    for i, a in enumerate(turma_com_alunos(db, e, "4º Ano", 6)):
        retrato_matific(db, e, a, quando, atividades=10 if i < 2 else 0,
                        estrelas=20 if i < 2 else 0)
    for a in turma_com_alunos(db, e, "5º Ano", 6):
        retrato_matific(db, e, a, quando, atividades=10, estrelas=30)
    db.commit()
    completa, por_serie = _respostas(db, rede)
    esc = _escola(completa, e)
    cel = {c["serie"]: c["matific"] for c in esc["series"]}
    assert cel[3]["alunos_medidos"] == 3 and cel[3]["atividades_por_aluno"] is None
    assert cel[4]["atividades_por_aluno"] is not None and cel[4]["estrelas_por_aluno"] is None
    assert cel[5]["atividades_por_aluno"] is not None
    for rotulo, total in (("escola", esc["matific"]), ("rede", completa["rede"]["matific"])):
        assert total["atividades_por_aluno"] is None, rotulo
        assert total["desempenho_medio"] is None, rotulo
        assert {"participacao_pct", "atividades_por_aluno",
                "desempenho_medio"} <= set(total["metricas_protegidas"]), rotulo
        assert total["texto_metricas_protegidas"] == svc.TEXTO_METRICAS_PROTEGIDAS.format(k=5)
        assert total["estrelas_por_aluno"] is not None, rotulo
        assert _recompor(total, "atividades_por_aluno", [cel[4], cel[5]]) is None, rotulo
    medidas = {(e.id, 3): 3}
    ativas = {(e.id, 3): 3, (e.id, 4): 2}
    assert _somas_expostas(completa, por_serie, "matific", "atividades_por_aluno",
                           medidas) == []
    for chave in ("estrelas_por_aluno", "desempenho_medio"):
        assert _somas_expostas(completa, por_serie, "matific", chave, ativas) == []


def test_desempenho_do_total_nao_devolve_as_atividades_de_uma_crianca(db):
    """Teste b da mesma prova, INVERTIDO: 3º ano com UMA criança medida (17 atividades, 40
    estrelas), as outras 6 sem coleta; 4º com 4 ativas de 6; 5º com 6. Antes, a escola e a
    rede devolviam exatamente {17} — o dado individual. Agora nada restringe a soma."""
    rede = nova_rede(db, nome="Rede Fictícia Complemento Cruzado Um", codigo="3599963",
                     codmun="9963")
    e = nova_escola(db, rede, "EMEF Fictícia Complemento Cruzado Um", "35996301")
    quando = datetime(2026, 10, 1, 15, 0)
    t3 = turma_com_alunos(db, e, "3º Ano", 7)
    retrato_matific(db, e, t3[0], quando, atividades=17, estrelas=40)
    for i, a in enumerate(turma_com_alunos(db, e, "4º Ano", 6)):
        retrato_matific(db, e, a, quando, atividades=10 if i < 4 else 0,
                        estrelas=25 if i < 4 else 0)
    for a in turma_com_alunos(db, e, "5º Ano", 6):
        retrato_matific(db, e, a, quando, atividades=10, estrelas=30)
    db.commit()
    completa, por_serie = _respostas(db, rede)
    esc = _escola(completa, e)
    cel = {c["serie"]: c["matific"] for c in esc["series"]}
    assert cel[3]["alunos_medidos"] == 1 and cel[3]["atividades_por_aluno"] is None
    for rotulo, total in (("escola", esc["matific"]), ("rede", completa["rede"]["matific"])):
        assert total["atividades_por_aluno"] is None, rotulo
        assert total["desempenho_medio"] is None, rotulo
        assert total["estrelas_por_aluno"] is not None, rotulo
        assert _recompor(total, "atividades_por_aluno", [cel[4], cel[5]]) is None, rotulo
    assert _somas_expostas(completa, por_serie, "matific", "atividades_por_aluno",
                           {(e.id, 3): 1}) == []
    ativas = {(e.id, 3): 1, (e.id, 4): 4}
    for chave in ("estrelas_por_aluno", "desempenho_medio"):
        assert _somas_expostas(completa, por_serie, "matific", chave, ativas) == []


@pytest.mark.parametrize("com_z", [False, True])
def test_rede_soma_as_marcas_das_somas_com_o_desempenho_derivado(db, com_z):
    """Escola × rede com o desempenho derivado. X: 3º com 3 medidas de 7, 4º com 2 ativas
    de 6, 5º com 6 → o total de X esconde as atividades e o desempenho e MOSTRA as estrelas
    (5 escondidas = k). Y: 4º com 6 ativas. A rede soma as atividades escondidas só das
    escolas que as esconderam: sem Z (3 < k), esconde as atividades e o desempenho; com Z
    (3º com 2 medidas de 7, 4º com 3 ativas: o total de Z também esconde as atividades e
    mostra as estrelas), 3 + 2 = k e a rede mostra as três médias — o desempenho dela vem de
    duas somas que já protegem k crianças. Contando o desempenho como derivado, nenhuma soma
    de menos de k crianças escondidas se refaz."""
    sufixo = int(com_z)
    rede = nova_rede(db, nome=f"Rede Fictícia Cruzada R{sufixo}",
                     codigo=f"359996{4 + sufixo}", codmun=f"996{4 + sufixo}")
    especificacao = {"X": {3: (7, 3, 3, 10, 20), 4: (6, 6, 2, 10, 20), 5: (6, 6, 6, 10, 30)},
                     "Y": {4: (6, 6, 6, 10, 20)}}
    if com_z:
        especificacao["Z"] = {3: (7, 2, 2, 10, 40), 4: (6, 6, 3, 10, 30)}
    escolas, medidas, ativas = {}, {}, {}
    for i, (letra, series) in enumerate(especificacao.items()):
        escolas[letra], celulas = _escola_mista(db, rede, f"EMEF Fictícia Cruzada {letra}",
                                                f"{rede.codigo_ibge}{i}", series)
        for chave, (med, atv) in celulas.items():
            medidas[chave] = med if med < 5 else 0
            ativas[chave] = atv if atv < 5 else 0
    db.commit()
    completa, por_serie = _respostas(db, rede)
    total = {letra: _escola(completa, e)["matific"] for letra, e in escolas.items()}
    for letra in ("X", "Z") if com_z else ("X",):
        assert total[letra]["atividades_por_aluno"] is None, letra
        assert total[letra]["desempenho_medio"] is None, letra
        assert total[letra]["estrelas_por_aluno"] is not None, letra
    assert total["Y"]["desempenho_medio"] is not None
    rede_m = completa["rede"]["matific"]
    assert rede_m["estrelas_por_aluno"] is not None
    if com_z:
        assert rede_m["atividades_por_aluno"] is not None
        assert rede_m["desempenho_medio"] is not None and rede_m["metricas_protegidas"] == []
    else:
        assert rede_m["atividades_por_aluno"] is None and rede_m["desempenho_medio"] is None
        assert "desempenho_medio" in rede_m["metricas_protegidas"]
    assert _somas_expostas(completa, por_serie, "matific", "atividades_por_aluno",
                           medidas) == []
    for chave in ("estrelas_por_aluno", "desempenho_medio"):
        assert _somas_expostas(completa, por_serie, "matific", chave, ativas) == []


# --- O zero de uma série sem número não é sabido ---------------------------------------------

def test_estrelas_zero_de_serie_sem_numero_nao_se_refazem_pelo_total(db):
    """Prova do bloqueio e97n (test_prova_bl_estrelas_zero) INVERTIDA. 3º ano com 7
    crianças e só 3 com coleta, as 3 SEM atividade: a célula não mostra nada (nem a
    participação) e o grupo das estrelas dela é vazio — contava zero, "soma já sabida".
    Não era sabida: a escola e a rede mostravam as estrelas por aluno e "total − 4º − 5º"
    dava exatamente 0, as estrelas das 3 crianças. Agora as estrelas somem dos dois totais
    (os medidos das séries sem número somam 3 < k) e do total da rede no 3º ano."""
    rede = nova_rede(db, nome="Rede Fictícia Estrelas Zero", codigo="3599971", codmun="9971")
    e, _ = _escola_mista(db, rede, "EMEF Fictícia Estrelas Zero", "35997101",
                         {3: (7, 3, 0, 0, 0), 4: (6, 6, 6, 10, 30), 5: (6, 6, 6, 10, 20)})
    db.commit()
    completa, por_serie = _respostas(db, rede)
    esc = _escola(completa, e)
    cel = {c["serie"]: c["matific"] for c in esc["series"]}
    assert cel[3]["alunos_medidos"] == 3 and cel[3]["participacao_pct"] is None
    assert cel[4]["estrelas_por_aluno"] == 30.0 and cel[5]["estrelas_por_aluno"] == 20.0
    for rotulo, total in (("escola", esc["matific"]), ("rede", completa["rede"]["matific"])):
        assert total["alunos_medidos"] == 15, rotulo
        assert total["estrelas_por_aluno"] is None, rotulo
        assert "estrelas_por_aluno" in total["metricas_protegidas"], rotulo
        for chave in ("atividades_por_aluno", "estrelas_por_aluno"):
            assert _recompor(total, chave, [cel[4], cel[5]]) is None, (rotulo, chave)
    assert por_serie[3]["rede"]["matific"]["estrelas_por_aluno"] is None
    assert por_serie[4]["rede"]["matific"]["estrelas_por_aluno"] == 30.0
    # As 3 crianças sem número são as escondidas das duas somas.
    for chave in ("atividades_por_aluno", "estrelas_por_aluno", "desempenho_medio"):
        assert _somas_expostas(completa, por_serie, "matific", chave,
                               {(e.id, 3): 3}) == [], chave


def test_estrelas_zero_misturadas_com_k_ativas_escondidas_continuam(db):
    """Controle: o mesmo 3º ano (3 medidas, nenhuma ativa), com o 4º de 2 ativas e o 5º de
    3 ativas (escondidas nas células). As crianças ativas escondidas somam 5 = k: o total
    da escola mostra as estrelas — a diferença é a soma de 5 crianças ativas, com o zero do
    3º misturado, e não isola nada. As atividades e o desempenho somem (3 medidos sem
    número)."""
    rede = nova_rede(db, nome="Rede Fictícia Estrelas Misturadas", codigo="3599972",
                     codmun="9972")
    e, _ = _escola_mista(db, rede, "EMEF Fictícia Estrelas Misturadas", "35997201",
                         {3: (7, 3, 0, 0, 0), 4: (6, 6, 2, 10, 20), 5: (6, 6, 3, 10, 30)})
    db.commit()
    completa, por_serie = _respostas(db, rede)
    total = _escola(completa, e)["matific"]
    assert total["estrelas_por_aluno"] is not None
    assert total["atividades_por_aluno"] is None and total["desempenho_medio"] is None
    assert "estrelas_por_aluno" not in total["metricas_protegidas"]
    escondidas = {(e.id, 3): 3, (e.id, 4): 2, (e.id, 5): 3}
    for chave in ("estrelas_por_aluno", "desempenho_medio"):
        assert _somas_expostas(completa, por_serie, "matific", chave, escondidas) == [], chave
    assert _somas_expostas(completa, por_serie, "matific", "atividades_por_aluno",
                           {(e.id, 3): 3}) == []


@pytest.mark.parametrize("com_z", [False, True])
def test_estrelas_zero_entre_as_escolas_da_rede(db, com_z):
    """Escola × rede com o zero não sabido. X: 3º com 3 medidas de 7, nenhuma ativa; 4º com
    6 ativas → o total de X esconde as atividades, o desempenho e as estrelas. Sem Z, a rede
    escondia só as atividades e o desempenho e "rede − 4º de X" dava as estrelas das 3: 0.
    Agora a rede soma, das escolas que esconderam as estrelas, os medidos sem número (3 < k)
    e as esconde. Com Z (3º com 2 medidas de 7, nenhuma ativa), são 5 = k: a rede mostra as
    três médias, e as diferenças dão só o zero de 5 crianças (o padrão dos medidos — o
    mesmo que já mostra as atividades)."""
    sufixo = int(com_z)
    rede = nova_rede(db, nome=f"Rede Fictícia Zero R{sufixo}",
                     codigo=f"359997{3 + sufixo}", codmun=f"997{3 + sufixo}")
    especificacao = {"X": {3: (7, 3, 0, 0, 0), 4: (6, 6, 6, 10, 30)}}
    if com_z:
        especificacao["Z"] = {3: (7, 2, 0, 0, 0), 4: (6, 6, 6, 10, 20)}
    escolas, sem_numero = {}, {}
    for i, (letra, series) in enumerate(especificacao.items()):
        escolas[letra], celulas = _escola_mista(db, rede, f"EMEF Fictícia Zero {letra}",
                                                f"{rede.codigo_ibge}{i}", series)
        sem_numero.update({c: med for c, (med, _atv) in celulas.items() if med < 5})
    db.commit()
    completa, por_serie = _respostas(db, rede)
    for letra, e in escolas.items():
        total = _escola(completa, e)["matific"]
        for chave in ("atividades_por_aluno", "estrelas_por_aluno", "desempenho_medio"):
            assert total[chave] is None, (letra, chave)
    rede_m = completa["rede"]["matific"]
    for chave in ("atividades_por_aluno", "estrelas_por_aluno", "desempenho_medio"):
        assert (rede_m[chave] is not None) is com_z, chave
        assert _somas_expostas(completa, por_serie, "matific", chave, sem_numero) == [], chave


def test_serie_com_poucos_medidos_nao_se_refaz_pelo_total_da_escola(db):
    """O mesmo com o denominador: 3º ano com 7 crianças e só 2 com conta no Elefante (a
    célula não mostra métrica nenhuma — poucos medidos —, mas o total da escola a somava:
    "escola − 4º ano" dava os livros, os minutos e o nível das duas). Agora o total esconde
    as métricas que dependem delas."""
    rede = nova_rede(db, nome="Rede Fictícia Poucos Medidos", codigo="3599949", codmun="9949")
    e = nova_escola(db, rede, "EMEF Fictícia Poucos Medidos", "35994901")
    bk = livros(db, e, 3, "K")
    t3 = turma_com_alunos(db, e, "3º Ano", 7)
    t4 = turma_com_alunos(db, e, "4º Ano", 6)
    for a in t3[:2]:
        retrato_elefante(db, e, a, datetime(2026, 9, 30, 3, 10))
        ler(db, e, a, bk, datetime(2026, 5, 1, 12, 0), minutos=40)
    for a in t4:
        retrato_elefante(db, e, a, datetime(2026, 9, 30, 3, 10))
        ler(db, e, a, bk[:1], datetime(2026, 5, 1, 12, 0))
    db.commit()
    completa, por_serie = _respostas(db, rede)
    esc = _escola(completa, e)
    cel = {c["serie"]: c["elefante"] for c in esc["series"]}
    assert cel[3]["motivo_sem_dado"] == svc.POUCOS_MEDIDOS and cel[3]["alunos_medidos"] == 2
    assert cel[4]["livros_por_aluno"] == 1.0
    el = esc["elefante"]
    assert el["alunos_medidos"] == 8                          # a contagem continua
    for chave in ("alunos_com_leitura", "participacao_pct", "livros_por_aluno",
                  "minutos_por_aluno", "nivel_medio", "nivel_medio_posicao"):
        assert el[chave] is None, chave
        assert chave in el["metricas_protegidas"], chave
    medidos = {(e.id, 3): 2, (e.id, 4): 0}
    for chave in ("livros_por_aluno", "minutos_por_aluno", "participacao_pct"):
        assert _somas_expostas(completa, por_serie, "elefante", chave, medidos) == []


def test_aluno_sem_conta_no_elefante_fica_fora_do_denominador(db):
    """M6: 10 crianças, 3 ainda sem conta no Elefante (nenhuma coleta delas): os livros e a
    participação são dos 7 com conta — quem não tem conta não vira zero."""
    rede = nova_rede(db, nome="Rede Fictícia Sem Conta", codigo="3599937")
    e = nova_escola(db, rede, "EMEF Fictícia Sem Conta", "35993701")
    alunos = turma_com_alunos(db, e, "4º Ano", 10)
    bk = livros(db, e, 2, "K")
    for a in alunos[:7]:
        retrato_elefante(db, e, a, datetime(2026, 9, 30, 3, 0))
        ler(db, e, a, bk, datetime(2026, 5, 1, 12, 0))
    db.commit()
    (cel,) = _escola(svc.plataformas_da_rede(db, rede, hoje=HOJE), e)["series"]
    el = cel["elefante"]
    assert (el["alunos_medidos"], el["alunos_sem_conta"]) == (7, 3)
    assert el["livros_por_aluno"] == 2.0 and el["participacao_pct"] == 100.0


def test_coleta_parada_antes_do_fim_e_coleta_parcial(db):
    """Sonda E (M5): a última coleta do Elefante e do Matific é de 15/02 e o período vai de
    14/02 a hoje. Antes: cobertura "ok" e 0 livros por aluno — a escola comparada com as
    coletadas ontem. Agora: ``coleta_parcial`` com a data até onde vale, fora da rede."""
    rede = nova_rede(db, nome="Rede Fictícia Sonda E", codigo="3599938")
    parada = nova_escola(db, rede, "EMEF Fictícia Parada", "35993801")
    em_dia = nova_escola(db, rede, "EMEF Fictícia Em Dia", "35993802")
    bk = livros(db, parada, 3, "K")
    for a in turma_com_alunos(db, parada, "3º Ano", 10):
        ler(db, parada, a, bk[:1], datetime(2026, 2, 10, 12, 0))
        retrato_elefante(db, parada, a, datetime(2026, 2, 15, 3, 0))
        retrato_matific(db, parada, a, datetime(2026, 2, 15, 3, 0), atividades=2, estrelas=5)
    for a in turma_com_alunos(db, em_dia, "3º Ano", 10):
        retrato_elefante(db, em_dia, a, datetime(2026, 10, 3, 3, 0))
        retrato_matific(db, em_dia, a, datetime(2026, 10, 3, 3, 0), atividades=4, estrelas=9)
    db.commit()
    dados = svc.plataformas_da_rede(db, rede, preset="personalizado", inicio=date(2026, 2, 14),
                                    fim=HOJE, hoje=HOJE)
    p = _escola(dados, parada)
    assert p["cobertura"] == {"elefante": svc.COLETA_PARCIAL, "matific": svc.COLETA_PARCIAL}
    assert p["coberto_ate"]["elefante"].startswith("2026-02-15")
    assert p["dias_desde_ultima_coleta"] == {"elefante": 232, "matific": 232}
    el = p["elefante"]
    assert el["coleta_parcial"] is True and "15/02/2026" in el["texto_cobertura"]
    assert el["livros_por_aluno"] == 0.0          # o que foi medido (até 15/02), rotulado
    assert p["matific"]["coleta_parcial"] is True
    # Fora da soma da rede (que fica só com a escola em dia) e listada na cobertura.
    assert dados["rede"]["elefante"]["alunos_medidos"] == 10
    assert dados["rede"]["escolas_com_dado"] == {"elefante": 1, "matific": 1}
    assert dados["cobertura"]["escolas_coleta_parcial"] == {"elefante": [parada.id],
                                                            "matific": [parada.id]}
    assert _escola(dados, em_dia)["cobertura"]["elefante"] == svc.COBERTURA_OK
    # O ano letivo inteiro, com a coleta em dia na outra escola, também marca a parada.
    ano = svc.plataformas_da_rede(db, rede, hoje=HOJE)
    assert _escola(ano, parada)["cobertura"]["elefante"] == svc.COLETA_PARCIAL


def test_coleta_parcial_que_cobre_90_por_cento_entra_na_soma_da_rede_com_a_data(db):
    """Dados reais de 20/10/2026: 4 das 5 escolas com plataforma tinham a última coleta
    entre 01 e 04/10 (agendador desligado) — fora da soma, a rede do ano letivo ficava com
    UMA escola. A parcial que cobre ≥ 90% do período (até hoje) entra na soma, com a data
    até onde vale; a que cobre pouco continua fora; a relação segue estrita (relacao.py)."""
    rede = nova_rede(db, nome="Rede Fictícia Cobertura", codigo="3599937")
    quase = nova_escola(db, rede, "EMEF Fictícia Quase em Dia", "35993701")
    parada = nova_escola(db, rede, "EMEF Fictícia Parada Cedo", "35993702")
    em_dia = nova_escola(db, rede, "EMEF Fictícia Coletada", "35993703")
    for escola, quando in ((quase, datetime(2026, 9, 25, 3, 0)),
                           (parada, datetime(2026, 2, 15, 3, 0)),
                           (em_dia, datetime(2026, 10, 3, 3, 0))):
        for a in turma_com_alunos(db, escola, "3º Ano", 10):
            retrato_elefante(db, escola, a, quando)
            retrato_matific(db, escola, a, quando, atividades=2, estrelas=5)
    db.commit()
    # 14/02 → 05/10 = 233 dias; a coleta de 25/09 cobre 223 (95,7%), a de 15/02 quase nada.
    dados = svc.plataformas_da_rede(db, rede, preset="personalizado", inicio=date(2026, 2, 14),
                                    fim=HOJE, hoje=HOJE)
    assert _escola(dados, quase)["cobertura"]["elefante"] == svc.COLETA_PARCIAL
    assert _escola(dados, parada)["cobertura"]["elefante"] == svc.COLETA_PARCIAL
    rede_el = dados["rede"]["elefante"]
    assert rede_el["alunos_medidos"] == 20                     # em dia + quase; a parada não
    assert dados["rede"]["escolas_com_dado"]["elefante"] == 2
    assert rede_el["escolas_coleta_parcial_na_soma"] == 1
    assert rede_el["coberto_ate_parcial"].startswith("2026-09-25")
    assert "25/09/2026" in rede_el["texto_parcial_na_soma"]
    # As duas continuam listadas como coleta parcial na cobertura (alerta de atraso).
    assert sorted(dados["cobertura"]["escolas_coleta_parcial"]["elefante"]) == sorted(
        [quase.id, parada.id])


def test_escola_sem_coleta_tem_metrica_nula_nunca_zero(mundo):
    dados = _get(mundo)
    beta = _escola(dados, mundo["escolas"]["beta"])
    assert beta["cobertura"] == {"elefante": svc.SEM_COLETA, "matific": svc.COBERTURA_OK}
    e = beta["elefante"]
    assert e["livros_por_aluno"] is None and e["participacao_pct"] is None
    assert e["motivo_sem_dado"] == svc.SEM_COLETA and e["texto_sem_dado"]
    assert beta["matific"]["atividades_por_aluno"] == 5.0
    assert beta["matific"]["desempenho_medio"] == 2.4
    gama = _escola(dados, mundo["escolas"]["gama"])
    assert gama["alunos"] == 0 and gama["elefante"]["motivo_sem_dado"] == svc.SEM_ALUNOS
    sem_coleta = dados["cobertura"]["escolas_sem_coleta_no_periodo"]["elefante"]
    assert mundo["escolas"]["beta"].id in sem_coleta
    assert mundo["escolas"]["alfa"].id not in sem_coleta
    # A escola sem coleta fica FORA da conta da rede (não dilui a média com zeros) — e da
    # Alfa só entra a série visível (o 3º ano, 7 crianças).
    assert dados["rede"]["elefante"]["alunos_medidos"] == 7
    assert dados["rede"]["escolas_com_dado"] == {"elefante": 1, "matific": 2}


def test_periodo_sem_coleta_do_elefante_e_ausencia(mundo):
    """Período depois da última coleta do Elefante (30/09): as leituras de outubro ainda
    não chegaram — sem dado, não zero."""
    dados = _get(mundo, periodo="personalizado", inicio="2026-10-01", fim="2026-10-05")
    alfa = _escola(dados, mundo["escolas"]["alfa"])
    assert alfa["cobertura"]["elefante"] == svc.SEM_COLETA_NO_PERIODO
    assert alfa["elefante"]["livros_por_aluno"] is None
    assert alfa["matific"]["motivo_sem_dado"] == svc.SEM_COLETA_NO_PERIODO
    assert dados["janela"]["inicio"] == "2026-10-01"


def test_filtros_de_serie_e_escola(mundo):
    alfa, beta = mundo["escolas"]["alfa"], mundo["escolas"]["beta"]
    so3 = _get(mundo, serie=3)
    a = _escola(so3, alfa)
    assert a["alunos"] == 7 and [s["serie"] for s in a["series"]] == [3]
    assert _escola(so3, beta)["alunos"] == 0
    assert so3["filtros"]["serie"] == 3
    so_beta = _get(mundo, escola_id=beta.id)
    assert [e["escola_id"] for e in so_beta["escolas"]] == [beta.id]
    assert so_beta["rede"]["alunos"] == 25                 # a rede continua a rede inteira
    c, rede = mundo["c"], mundo["rede"].id
    assert c.get(URL.format(rede=rede), params={"serie": 6}).status_code == 400
    assert c.get(URL.format(rede=rede), params={"escola_id": 999999}).status_code == 404
    assert c.get(URL.format(rede=rede), params={"periodo": "nada"}).status_code == 400
    assert c.get(URL.format(rede=rede), params={"periodo": "personalizado"}).status_code == 400


def test_serie_que_a_escola_nao_tem_diz_a_serie_nao_1o_ao_5o(mundo):
    """Com Série = 3º ano, a BETA (8 crianças, só no 5º ano) não tem aluno nesta série: o
    motivo diz isso — não "nenhum aluno ativo do 1º ao 5º ano", que seria falso para ela. A
    GAMA (nenhum aluno no recorte) continua com o motivo de sempre."""
    so3 = _get(mundo, serie=3)
    beta = _escola(so3, mundo["escolas"]["beta"])
    assert beta["alunos"] == 0 and beta["suprimido"] is False and beta["series"] == []
    for p in ("elefante", "matific"):
        bloco = beta[p]
        assert bloco["motivo_sem_dado"] == svc.SEM_ALUNOS_NA_SERIE
        assert bloco["texto_sem_dado"] == "a escola não tem aluno ativo nesta série no ano letivo"
        assert "1º ao 5º" not in bloco["texto_sem_dado"]
        assert bloco["participacao_pct"] is None                    # sem dado, nunca 0
    # A cobertura da escola não muda com a série (a coleta é da escola inteira).
    assert beta["cobertura"] == {"elefante": svc.SEM_COLETA, "matific": svc.COBERTURA_OK}
    gama = _escola(so3, mundo["escolas"]["gama"])
    assert gama["alunos"] == 0 and gama["elefante"]["motivo_sem_dado"] == svc.SEM_ALUNOS
    assert "1º ao 5º ano" in gama["elefante"]["texto_sem_dado"]
    # Sem série, a BETA tem os seus alunos (5º ano) e nenhum dos dois motivos de "sem aluno".
    todas = _escola(_get(mundo), mundo["escolas"]["beta"])
    assert todas["alunos"] == 8
    assert todas["matific"]["motivo_sem_dado"] not in (svc.SEM_ALUNOS, svc.SEM_ALUNOS_NA_SERIE)


def test_escolas_em_ordem_de_nome_e_cobertura(mundo):
    dados = _get(mundo)
    nomes = [e["nome"] for e in dados["escolas"]]
    assert nomes[0] == "EMEF Ébano Fictícia" and nomes[1:] == sorted(nomes[1:])
    cob = dados["cobertura"]
    assert cob["ultima_coleta"]["elefante"].startswith("2026-09-30T00:10")    # 03:10 UTC
    assert cob["ultima_coleta"]["elefante"].endswith("-03:00")
    assert cob["dias_desde_ultima_coleta"] == 5
    assert _escola(dados, mundo["escolas"]["alfa"])["dias_desde_ultima_coleta"] == {
        "elefante": 5, "matific": 5}
    assert any("VITALÍCIO" in t for t in dados["limitacoes"])
    assert any("UTC" in t for t in dados["limitacoes"])


def test_textos_da_tela_sem_jargao_interno(mundo):
    """R11: os textos que a tela mostra não têm nome de campo, caminho de arquivo nem o
    termo interno "retrato"."""
    dados = _get(mundo)
    textos = list(dados["limitacoes"]) + [dados["rede"]["texto_blocos"]]
    textos += [v for v in svc.TEXTOS_COBERTURA.values()] + [svc.TEXTO_SUPRESSAO]
    textos += [svc.TEXTO_CONTADOR_REGREDIU, svc.TEXTO_METRICAS_PROTEGIDAS.format(k=5)]
    for t in textos:
        assert "janela_questoes" not in t and "docs/" not in t and ".md" not in t, t
        assert "retrato" not in t.lower(), t
        assert "metricas_protegidas" not in t and "contador_regrediu" not in t, t


def test_modulo_nao_contratado_some_da_resposta(db, mundo):
    from app.services import modulos
    modulos.definir(db, mundo["rede"].id, "matematica", False)
    db.commit()
    dados = _get(mundo)
    assert dados["modulos"] == {"elefante": True, "matific": False}
    assert dados["rede"]["matific"] is None
    assert all(e["matific"] is None for e in dados["escolas"])
    assert _escola(dados, mundo["escolas"]["alfa"])["cobertura"]["matific"] == svc.MODULO_DESLIGADO


def _todas_as_respostas(mundo) -> list[str]:
    c, rede = mundo["c"], mundo["rede"].id
    alfa = mundo["escolas"]["alfa"].id
    urls = [
        (f"/api/v1/redes/{rede}/analise/indicadores", {}),
        (f"/api/v1/redes/{rede}/analise/indicadores/saresp", {}),
        (f"/api/v1/redes/{rede}/analise/indicadores/saresp", {"visao": "escolas", "edicao": 2025}),
        (f"/api/v1/redes/{rede}/analise/indicadores/ideb", {"escola_id": alfa}),
        (f"/api/v1/redes/{rede}/analise/plataformas", {}),
        (f"/api/v1/redes/{rede}/analise/plataformas", {"serie": 3}),
        (f"/api/v1/redes/{rede}/analise/plataformas", {"escola_id": alfa}),
        (f"/api/v1/redes/{rede}/analise/relacao", {"indicador": "saresp"}),
        (f"/api/v1/redes/{rede}/analise/relacao", {"indicador": "ideb",
                                                   "metrica": "atividades_por_aluno"}),
        (f"/api/v1/escolas/{alfa}/analise", {}),
    ]
    saida = []
    for url, params in urls:
        r = c.get(url, params=params)
        assert r.status_code == 200, (url, r.text)
        saida.append(r.text)
    return saida


def test_nenhum_dado_pessoal_de_crianca_em_nenhuma_resposta(db, mundo):
    from app.models import Aluno
    ids_rede = {e.id for e in mundo["escolas"].values()}
    da_rede = [a.nome for a in db.query(Aluno).all() if a.escola_id in ids_rede]
    assert len(da_rede) == 29 and all(n.startswith(PREFIXO_CRIANCA) for n in da_rede)
    nomes = [a.nome for a in db.query(Aluno).all()]          # todas as crianças da base
    for texto in _todas_as_respostas(mundo):
        assert "aluno_id" not in texto
        assert PREFIXO_CRIANCA not in texto
        for nome in nomes:
            assert nome not in texto
        assert '"turma"' not in texto and "turma_id" not in texto


def test_livro_sem_nivel_conhecido_nao_entra_no_nivel_medio(db, mundo):
    alfa = mundo["escolas"]["alfa"]
    t3 = mundo["turmas"]["alfa_3"]
    ler(db, alfa, t3[6], livros(db, alfa, 1, "??"), datetime(2026, 6, 1, 10, 0))
    db.commit()
    s3 = next(s for s in _escola(_get(mundo), alfa)["series"] if s["serie"] == 3)
    # O livro conta como livro novo (9 ÷ 7), mas o nível fora do vocabulário não mexe na média.
    assert s3["elefante"]["livros_por_aluno"] == 1.29
    assert s3["elefante"]["nivel_medio_posicao"] == 14.63
