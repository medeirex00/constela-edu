"""VAZAMENTO ENTRE DIMENSÕES — prova nos DOIS sentidos, com números.

A garantia central da Arquitetura 2 (`docs/spec-arquitetura-2.md` §0, §6):

    usar (ou não usar) a plataforma de uma dimensão NÃO pode mover a nota da
    outra dimensão — nem por um centésimo.

O canal real que existia: ``scoring._referencias`` decidia "régua robusta
(P90 + saturação) × escala simples (máximo)" por ``max(len(matific),
len(elefante))`` — UM número para as DUAS dimensões. Numa escola com muitos
alunos no Matific e poucos no Elefante, a coorte de MATEMÁTICA ligava a régua
robusta dos indicadores de LEITURA. Importar o Matific mudava a nota de Leitura
de quem nunca abriu o Matific.

Este arquivo é a CATRACA dos dois sentidos. Para cada um dos 6 cenários pedidos
ele mede o delta máximo (ao centésimo) sofrido pelas notas da dimensão-vítima
enquanto a coorte da dimensão-agressora cresce de 0 a 11 alunos (atravessando
``MIN_ALUNOS_ROBUSTO`` = 8), em duas configurações:

  * COM a correção (o código de produção)  → o delta tem de ser 0,00 em todos;
  * SEM a correção (``referencias_legado_com_vazamento``, réplica congelada do
    código ANTIGO) → o delta volta a ser > 0, senão os cenários não estariam
    exercitando canal nenhum e a catraca seria decorativa.

Os números medidos são impressos para que a diferença "com × sem" possa ser
auditada, não apenas afirmada.
"""
import pytest

from app.core.security import hash_senha
from app.models import (
    Aluno,
    Configuracao,
    Escola,
    Importacao,
    Matricula,
    NivelDificuldade,
    Nota,
    ReferenciaNormalizacao,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
    Usuario,
)
from app.services import scoring
from tests.regua_legada import referencias_legado_com_vazamento

# ---------------------------------------------------------------------------
# Montagem
# ---------------------------------------------------------------------------

def _escola(db):
    esc = Escola(nome="EM VAZAMENTO", ano_letivo_ativo=2026, status="ativa")
    db.add(esc)
    db.flush()
    for ns, val in scoring.PESOS_PADRAO.items():
        db.add(Configuracao(escola_id=esc.id, namespace=ns, chave="valores",
                            valor=val))
    # Estas escolas EXERCITAM a régua CONFIGURÁVEL da escola (o monkeypatch de
    # `scoring._referencias`). No perfil PADRÃO/institucional o recálculo ignora
    # `_referencias` (usa A3+auto direto), e o canal antigo — que estes testes
    # precisam observar (com e sem a correção) — nunca chegaria a rodar. Marcar a
    # escola como PERSONALIZADA restaura EXATAMENTE o caminho de cálculo antigo,
    # que passa por `_referencias` e, portanto, pela réplica legada com vazamento.
    db.add(Configuracao(escola_id=esc.id, namespace=scoring.PERFIL_SCORING_NS,
                        chave="modo", valor="personalizado"))
    db.add(NivelDificuldade(escola_id=esc.id, nome="N2", codigo="n2",
                            codigos=["D"], pontos_padrao=4.0, ordem=1))
    db.add(ReferenciaNormalizacao(escola_id=esc.id, modo="auto"))
    turma = Turma(escola_id=esc.id, nome="4ºA", ano_escolar="4º Ano",
                  ano_letivo=2026, status="ativa")
    db.add(turma)
    # E-mail único por escola: um mesmo teste monta duas escolas (o A/B recalcula
    # a mesma base com as duas réguas, e a varredura monta a sua).
    db.add(Usuario(escola_id=esc.id, nome="G", email=f"g{esc.id}@vaz.local",
                   senha_hash=hash_senha("s3nh4vaz4mento"), cargo="coordenador"))
    db.flush()
    imp = Importacao(escola_id=esc.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    return esc, turma, imp


def _ele(n):
    return {"livros_unicos": n, "tempo_leitura_min": n * 11,
            "questoes_tentativas": n * 5, "questoes_acertos": n * 3,
            "livros_por_nivel": {"D": n}}


def _mat(n):
    return {"atividades": n * 7, "pontuacao_media": min(5.0, n * 0.3),
            "estrelas": n * 13}


def _aluno(db, esc, turma, imp, nome, *, ele=None, mat=None):
    a = Aluno(escola_id=esc.id, nome=nome, status="ativo")
    db.add(a)
    db.flush()
    db.add(Matricula(escola_id=esc.id, aluno_id=a.id, turma_id=turma.id,
                     ano_letivo=2026))
    if ele is not None:
        db.add(SnapshotElefante(escola_id=esc.id, aluno_id=a.id,
                                importacao_id=imp.id, **_ele(ele)))
    if mat is not None:
        db.add(SnapshotMatific(escola_id=esc.id, aluno_id=a.id,
                               importacao_id=imp.id, **_mat(mat)))
    return a


def _notas(db, esc_id):
    return {n.aluno_id: n for n in db.query(Nota).filter(Nota.escola_id == esc_id)}


# ---------------------------------------------------------------------------
# Os 6 cenários pedidos. Cada um devolve (escola, turma, importação, alvos).
# Os alvos são os alunos cuja nota é observada nos DOIS sentidos.
# ---------------------------------------------------------------------------

def _cen_so_elefante(db):
    esc, turma, imp = _escola(db)
    alvos = [_aluno(db, esc, turma, imp, f"L{i}", ele=2 + i * 4) for i in range(6)]
    return esc, turma, imp, alvos


def _cen_so_matific(db):
    esc, turma, imp = _escola(db)
    alvos = [_aluno(db, esc, turma, imp, f"M{i}", mat=2 + i * 3) for i in range(6)]
    return esc, turma, imp, alvos


def _cen_ambos(db):
    esc, turma, imp = _escola(db)
    alvos = [_aluno(db, esc, turma, imp, f"A{i}", ele=2 + i * 4, mat=3 + i * 2)
             for i in range(6)]
    return esc, turma, imp, alvos


def _cen_muito_desbalanceado(db):
    """11 alunos só de Matific × 3 só de Elefante: a coorte de MATEMÁTICA já
    passa do gate de 8 e a de LEITURA está bem abaixo. É a forma exata do bug
    original — o `max(...)` ligava a régua robusta da leitura com 3 leitores."""
    esc, turma, imp = _escola(db)
    leitores = [_aluno(db, esc, turma, imp, f"L{i}", ele=3 + i * 9) for i in range(3)]
    matematicos = [_aluno(db, esc, turma, imp, f"M{i}", mat=1 + i * 2)
                   for i in range(11)]
    return esc, turma, imp, leitores + matematicos


def _cen_aluno_em_uma_plataforma_so(db):
    esc, turma, imp = _escola(db)
    base = [_aluno(db, esc, turma, imp, f"B{i}", ele=4 + i * 3, mat=4 + i * 3)
            for i in range(5)]
    so_le = _aluno(db, esc, turma, imp, "So Le", ele=25)
    so_conta = _aluno(db, esc, turma, imp, "So Conta", mat=25)
    return esc, turma, imp, [*base, so_le, so_conta]


def _cen_aluno_sem_snapshot_nenhum(db):
    esc, turma, imp = _escola(db)
    base = [_aluno(db, esc, turma, imp, f"B{i}", ele=4 + i * 3, mat=4 + i * 3)
            for i in range(5)]
    orfao = _aluno(db, esc, turma, imp, "Sem Nada")
    return esc, turma, imp, [*base, orfao]


CENARIOS = {
    "escola só com Elefante": _cen_so_elefante,
    "escola só com Matific": _cen_so_matific,
    "escola com ambos": _cen_ambos,
    "quantidades MUITO diferentes": _cen_muito_desbalanceado,
    "aluno em só uma plataforma": _cen_aluno_em_uma_plataforma_so,
    "aluno sem snapshot nenhum": _cen_aluno_sem_snapshot_nenhum,
}

# dimensão-vítima → (coluna da nota, coluna da posição, coluna de aferido,
#                    plataforma PERTURBADA para tentar contaminá-la).
SENTIDOS = {
    # sentido 1 — "Matific → não altera Leitura" (o teste que já existia)
    "leitura": ("nota_elefante", "posicao_leitura", "aferido_leitura", "mat"),
    # sentido 2 — "Leitura → não altera Matemática" (a prova INVERSA)
    "matematica": ("nota_matific", "posicao_matematica", "aferido_matematica", "ele"),
}
PLATAFORMA = {"mat": "Matific", "ele": "Elefante"}

# Rodadas da varredura: 0..11 alunos da plataforma agressora — atravessa
# `MIN_ALUNOS_ROBUSTO` (8) nos dois sentidos.
RODADAS = 12

# Placar das medições SEM a correção, só para o relatório final do arquivo.
_MEDIDO_SEM_CORRECAO: dict[tuple[str, str], tuple[float, int]] = {}


def _medir(db, cenario, dimensao, monkeypatch=None):
    """Delta máximo sofrido pela ``dimensao`` enquanto a coorte da OUTRA
    plataforma cresce de 0 a ``RODADAS-1`` alunos.

    Devolve ``(delta_nota, delta_posicao, aferido_flipou, alvos_com_sinal)``."""
    coluna, coluna_pos, coluna_aferido, agressora = SENTIDOS[dimensao]
    esc, turma, imp, alvos = CENARIOS[cenario](db)
    db.commit()
    if monkeypatch is not None:
        monkeypatch.setattr(scoring, "_referencias",
                            referencias_legado_com_vazamento)

    base_nota = base_pos = base_afer = None
    pior_nota, pior_pos, flipou = 0.0, 0, False
    for rodada in range(RODADAS):
        if rodada:
            # Aluno NOVO, com dado só da plataforma agressora — não encosta em
            # nenhum snapshot da dimensão observada nem nos alvos.
            _aluno(db, esc, turma, imp, f"X{agressora}{rodada}",
                   **{agressora: rodada + 1})
            db.commit()
        scoring.recalcular_escola(db, esc.id)
        notas = _notas(db, esc.id)
        atual = {a.id: getattr(notas[a.id], coluna) for a in alvos}
        posic = {a.id: getattr(notas[a.id], coluna_pos) for a in alvos}
        afer = {a.id: bool(getattr(notas[a.id], coluna_aferido)) for a in alvos}
        if base_nota is None:
            base_nota, base_pos, base_afer = atual, posic, afer
            continue
        pior_nota = max(pior_nota,
                        max(abs(atual[k] - base_nota[k]) for k in base_nota))
        pior_pos = max(pior_pos,
                       max(abs((posic[k] or 0) - (base_pos[k] or 0))
                           for k in base_pos))
        flipou = flipou or afer != base_afer
    return (round(pior_nota, 2), pior_pos, flipou,
            sum(1 for v in base_nota.values() if v > 0))


# ---------------------------------------------------------------------------
# 1) COM a correção: delta 0,00 nos dois sentidos, nos 6 cenários
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cenario", list(CENARIOS))
@pytest.mark.parametrize("dimensao", list(SENTIDOS))
def test_perturbar_a_outra_plataforma_nao_move_a_nota_da_dimensao(
        db, cenario, dimensao):
    """Os 6 cenários × os 2 sentidos. Delta exigido: 0,00 na nota, 0 na posição
    e nenhum ``aferido`` invertido — ausência não pode virar presença (nem
    valor) por causa da outra plataforma."""
    delta, delta_pos, flipou, com_sinal = _medir(db, cenario, dimensao)
    agressora = PLATAFORMA[SENTIDOS[dimensao][3]]
    print(f"  [COM correção] vítima={dimensao:<11} agressora={agressora:<9}"
          f"| {cenario:<30} | d_nota={delta:.2f} d_posicao={delta_pos} "
          f"| alvos com nota>0: {com_sinal}")
    assert delta == 0.0, (
        f"VAZAMENTO: crescer a coorte de {agressora} moveu a nota de {dimensao} "
        f"em até {delta:.2f} pontos no cenário '{cenario}'")
    assert delta_pos == 0, (
        f"VAZAMENTO: a POSIÇÃO em {dimensao} mudou (até {delta_pos} lugares) por "
        f"causa da coorte de {agressora} no cenário '{cenario}'")
    assert not flipou, (
        f"VAZAMENTO: o estado AFERIDO em {dimensao} mudou por causa da coorte de "
        f"{agressora} no cenário '{cenario}' — ausência virou presença")


# ---------------------------------------------------------------------------
# 2) COM × SEM a correção, sobre a MESMA base: quanto o canal valia
# ---------------------------------------------------------------------------
# A varredura acima mede "crescer a coorte agressora muda a vítima?". Ela é a
# catraca certa para o código CORRIGIDO, mas subestima o canal antigo: no
# cenário desbalanceado a régua velha já nasce contaminada (11 alunos de
# Matific desde a rodada 0), então nada MUDA ao longo da varredura — o erro está
# no nível, não na variação. A medida honesta do que a correção vale é o A/B
# direto: a MESMA escola, recalculada com as duas versões de `_referencias`.

def _medir_ab(db, cenario, dimensao, monkeypatch):
    """Diferença entre a nota calculada COM e SEM a correção, mesma base.

    Devolve ``(delta_nota, delta_pct, delta_posicao, n_alvos)``."""
    coluna, coluna_pos, _aferido, _agr = SENTIDOS[dimensao]
    esc, turma, imp, alvos = CENARIOS[cenario](db)
    db.commit()

    scoring.recalcular_escola(db, esc.id)
    notas = _notas(db, esc.id)
    com = {a.id: getattr(notas[a.id], coluna) for a in alvos}
    com_pos = {a.id: getattr(notas[a.id], coluna_pos) for a in alvos}

    monkeypatch.setattr(scoring, "_referencias", referencias_legado_com_vazamento)
    scoring.recalcular_escola(db, esc.id)
    notas = _notas(db, esc.id)
    sem = {a.id: getattr(notas[a.id], coluna) for a in alvos}
    sem_pos = {a.id: getattr(notas[a.id], coluna_pos) for a in alvos}

    delta = max(abs(sem[k] - com[k]) for k in com)
    pior = max(com, key=lambda k: abs(sem[k] - com[k]))
    pct = (abs(sem[pior] - com[pior]) / com[pior] * 100) if com[pior] else 0.0
    delta_pos = max(abs((sem_pos[k] or 0) - (com_pos[k] or 0)) for k in com_pos)
    return round(delta, 2), round(pct, 1), delta_pos, len(alvos)


@pytest.mark.parametrize("cenario", list(CENARIOS))
@pytest.mark.parametrize("dimensao", list(SENTIDOS))
def test_medida_do_vazamento_quando_a_correcao_e_revertida(
        db, cenario, dimensao, monkeypatch):
    """Quanto a correção vale, cenário a cenário, nos dois sentidos.

    Duas medidas, porque o canal antigo se manifesta de duas formas:
      * ``d_nota`` (A/B) — a MESMA base recalculada com as duas réguas. Pega o
        erro de NÍVEL (o cenário desbalanceado já nasce contaminado);
      * ``varredura`` — crescer a coorte agressora de 0 a 11 sob a régua ANTIGA.
        Pega o erro de VARIAÇÃO (a nota da vítima muda ao importar a outra
        plataforma), que é a forma como o usuário sente o bug.

    Não exige delta > 0: há cenários em que as duas réguas coincidem por
    construção (as duas coortes do mesmo tamanho, ou as duas do mesmo lado do
    gate). A exigência de que o canal REAPAREÇA fica nos testes seguintes, que
    são autossuficientes."""
    delta, pct, delta_pos, n = _medir_ab(db, cenario, dimensao, monkeypatch)
    varredura = _medir(db, cenario, dimensao, monkeypatch=monkeypatch)[0]
    _MEDIDO_SEM_CORRECAO[(dimensao, cenario)] = (delta, pct, delta_pos, varredura)
    agressora = PLATAFORMA[SENTIDOS[dimensao][3]]
    print(f"  [SEM correcao] vitima={dimensao:<11} agressora={agressora:<9}"
          f"| {cenario:<30} | AB={delta:>6.2f} ({pct:>5.1f}%) "
          f"varredura={varredura:>6.2f} d_posicao={delta_pos} | alvos={n}")


@pytest.mark.parametrize("cenario,dimensao,minimo", [
    # Escola só de Elefante + coorte de Matific crescendo: a varredura ANTIGA
    # atravessa o gate de 8 e a nota de LEITURA se mexe (o bug original).
    ("escola só com Elefante", "leitura", 0.01),
    # Sentido INVERSO, mesma forma.
    ("escola só com Matific", "matematica", 0.01),
])
def test_a_catraca_e_real_a_varredura_antiga_vaza(db, monkeypatch, cenario,
                                                  dimensao, minimo):
    """AUTOSSUFICIENTE (varredura): com a régua antiga, fazer a coorte da OUTRA
    plataforma crescer de 0 a 11 alunos move a nota da dimensão observada. Se
    isto passar a medir 0,00, os cenários deixaram de atravessar
    ``MIN_ALUNOS_ROBUSTO`` e as catracas acima viraram decorativas."""
    delta, delta_pos, _flipou, _n = _medir(db, cenario, dimensao,
                                           monkeypatch=monkeypatch)
    print(f"\n  >>> SEM a correcao, varredura de {cenario} sobre {dimensao}: "
          f"d_nota={delta:.2f} d_posicao={delta_pos}")
    assert delta >= minimo, (
        "a réplica do código antigo não vazou na varredura: os cenários "
        "deixaram de atravessar MIN_ALUNOS_ROBUSTO e a catraca virou decorativa")


def test_a_catraca_e_real_o_nivel_da_regua_antiga_difere(db, monkeypatch):
    """AUTOSSUFICIENTE (A/B): no cenário desbalanceado — 11 alunos de Matific ×
    3 de Elefante — a régua antiga já nasce contaminada, então o erro aparece no
    NÍVEL da nota de Leitura, não na variação. É o caso medido pelo dono
    (9,68 → 17,21, +78%)."""
    delta, pct, delta_pos, _ = _medir_ab(db, "quantidades MUITO diferentes",
                                         "leitura", monkeypatch)
    print(f"\n  >>> COM x SEM no cenario desbalanceado (leitura): "
          f"d_nota={delta:.2f} ({pct:.1f}%) d_posicao={delta_pos}")
    assert delta > 0, (
        "a régua antiga produziu exatamente a mesma nota de leitura: o cenário "
        "desbalanceado deixou de ser desbalanceado e a catraca virou decorativa")
