"""Teto de tempo FIXO, dependente de CPU, não volta aos testes do job test-backend.

O job roda com ``--cov=app`` num runner compartilhado, 2–3x mais lento que uma máquina
comum: um ``assert time.perf_counter() - comeco < 1.0`` que passa aqui com folga reprova
lá ao acaso (revisão de 28/10). Teto de CUSTO DE CPU segue o padrão de
``test_planilha_inflada.py``: ``TETO_S`` = 2 s numa máquina comum, 12 s com ``CI``
definido, ``TESTE_TETO_TEMPO_S`` por cima — e cada teste usa uma fração dele.

Fica de fora o teto que mede um PRAZO do próprio teste (o coletor desiste em 1 s em vez
de esperar o pool por 6 s; a coleta aborta no teto de 1 s em vez de esperar o atraso de
2,5 s): escalar esse teto apagaria a diferença entre o prazo e a regressão. Esses estão
em ``PRAZOS``, cada um com o porquê. Os marcados ``postgres`` ficam de fora (job próprio,
sem cobertura).

A varredura é pela árvore de sintaxe: um ``assert`` que compara um TEMPO MEDIDO com um
TETO FIXO.

- Tempo medido: a chamada de um relógio — ``perf_counter``, ``monotonic``, ``time``,
  ``process_time``, ``thread_time`` (e as variantes ``_ns``), ``timeit.default_timer``,
  ``timeit.timeit``/``timeit.repeat`` —, também importado com outro nome (``from time
  import perf_counter as pc``, ``from time import time``); a chamada de uma função do
  próprio módulo que DEVOLVE um tempo medido (``_tempo()`` que devolve
  ``perf_counter() - comeco``), com fecho transitivo (a auxiliar da auxiliar também
  conta: o fecho custa um laço a mais e não deixa a regra ser contornada por mais um
  nível de indireção); e toda variável derivada de um desses.
- Teto fixo: um número literal, ou um nome ligado UMA vez, a um número literal (ou a
  uma conta só de literais e de outros nomes assim): constante do módulo, como
  ``_TETO_DO_MENOR_S = 5.0``, ou da própria função. Um nome ligado mais de uma vez
  (``TETO = 2`` e, sob ``if CI``, ``TETO = 12``) ou a uma expressão com chamada
  (``TETO_S = float(os.environ.get(...) or ...)``) já escala, e não conta.
- Toda função do módulo é varrida, as auxiliares também: o teto pode estar dentro de
  um ``_melhores_tempos`` e não no teste que o chama.

Revisão integrada de 30/10: a primeira versão só via teto LITERAL e relógio chamado
DIRETO na própria função, e pulava a função que não chamava relógio — passava ``assert
t_menor < _TETO_DO_MENOR_S`` (constante de módulo, dentro de uma auxiliar, com o tempo
vindo de ``_tempo()``) e os relógios por alias, ``time_ns`` e ``default_timer``. Limites
que continuam (fora do alcance de uma varredura por módulo): o tempo que entra por
PARÂMETRO e a auxiliar importada de OUTRO módulo.
"""
import ast
from functools import lru_cache
from pathlib import Path

PASTA = Path(__file__).resolve().parent
# Relógios do módulo ``time``: na chamada ``x.nome()`` e no nome importado.
_RELOGIOS = {"perf_counter", "perf_counter_ns", "monotonic", "monotonic_ns", "process_time",
             "process_time_ns", "thread_time", "thread_time_ns", "time", "time_ns"}
# ``timeit.default_timer`` é o ``perf_counter``; ``timeit.timeit`` e ``timeit.repeat``
# devolvem a duração medida.
_RELOGIOS_DO_TIMEIT = {"default_timer"}
_MEDIDAS_DO_TIMEIT = {"timeit", "repeat"}
# Um módulo sem nenhum destes trechos não chama relógio (nem por alias: o alias exige
# ``from time import`` ou ``from timeit import``) e nem é analisado.
_TRECHOS_DE_RELOGIO = ("perf_counter", "monotonic", "process_time", "thread_time", "time(",
                       "time_ns", "default_timer", "timeit", "from time import")
_ESCOPOS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)

# (arquivo, teste) -> por que o teto é um PRAZO do próprio teste, e não custo de CPU.
PRAZOS = {
    ("test_sync_metricas_revisao.py",
     "test_pool_esgotado_o_coletor_responde_dentro_do_prazo_total"):
        "PRAZO_COLETOR_S=1 contra o pool_timeout de 6 s: o teto de 3 s separa o prazo da "
        "espera inteira; o de 0,5 s do 2º scrape separa 'responde na hora' de 'espera o "
        "prazo de 1 s de novo'",
    ("test_sync_metricas_revisao.py",
     "test_rota_metrics_responde_dentro_do_prazo_com_pool_esgotado"):
        "o mesmo prazo de 1 s pela rota /metrics, contra os 6 s do pool",
    ("test_sync_integridade_nucleo_falhas.py",
     "test_teto_total_aborta_perto_do_teto_e_termina_erro_timeout"):
        "SYNC_TETO_EXECUCAO_S=1 contra o atraso de 2,5 s do conector falso: o teto de 2 s "
        "separa o aborto no teto da espera inteira",
    ("test_aud_misc_assistente_prazo_total.py",
     "test_resposta_gotejando_estoura_o_prazo_total"):
        "PRAZO_TOTAL_S=1 contra a resposta que goteja por ~4 s: o teto de 2,5 s "
        "(PRAZO_TOTAL_TESTE_S + FOLGA_S) separa a desistência no prazo total do "
        "gotejamento inteiro",
    ("test_aud_misc_assistente_prazo_total.py",
     "test_anthropic_ocupada_nao_espera_alem_do_prazo_total"):
        "o mesmo prazo total de 1 s contra o 529 com Retry-After de 3 s: o teto de 2,5 s "
        "separa responder na hora de esperar a pausa do SDK",
    ("test_aud_rel_pdf_teto_navegadores.py",
     "test_sem_vaga_no_prazo_cai_na_reserva_sem_abrir_navegador"):
        "ESPERA_POR_NAVEGADOR_S=0,2 contra a espera padrão de 30 s com as vagas todas "
        "ocupadas: o teto de 5 s separa desistir no prazo e sair pela reserva (fpdf) de "
        "esperar a vaga",
}


class _Relogios:
    """O que, num módulo, lê um relógio quando chamado.

    ``nomes``: chamada por nome — o relógio importado (com o nome que recebeu) e a
    função do módulo que devolve um tempo medido (também como ``self.f()``/``cls.f()``).
    Um ``time()`` solto só conta com ``from time import time``: com ``from datetime
    import time`` ele monta uma hora do dia. ``modulos_timeit``: os nomes do módulo
    ``timeit`` (``import timeit as t`` → ``t.timeit()``)."""

    def __init__(self) -> None:
        self.nomes = (_RELOGIOS - {"time"}) | _RELOGIOS_DO_TIMEIT
        self.modulos_timeit: set = set()


def _relogios_importados(nos) -> _Relogios:
    r = _Relogios()
    for no in nos:
        if isinstance(no, ast.ImportFrom) and no.module in ("time", "timeit"):
            validos = (_RELOGIOS if no.module == "time"
                       else _RELOGIOS_DO_TIMEIT | _MEDIDAS_DO_TIMEIT)
            r.nomes.update(a.asname or a.name for a in no.names if a.name in validos)
        elif isinstance(no, ast.Import):
            r.modulos_timeit.update(a.asname or a.name for a in no.names
                                    if a.name == "timeit")
    return r


def _e_relogio(no, r: _Relogios) -> bool:
    if not isinstance(no, ast.Call):
        return False
    f = no.func
    if isinstance(f, ast.Name):
        return f.id in r.nomes
    if not isinstance(f, ast.Attribute):
        return False
    base = f.value.id if isinstance(f.value, ast.Name) else None
    return (f.attr in _RELOGIOS | _RELOGIOS_DO_TIMEIT
            or (base in r.modulos_timeit and f.attr in _MEDIDAS_DO_TIMEIT)
            or (base in ("self", "cls") and f.attr in r.nomes))


def _temporal(no, nomes, r: _Relogios) -> bool:
    return any(_e_relogio(n, r) or (isinstance(n, ast.Name) and n.id in nomes)
               for n in ast.walk(no))


def _proprios(no):
    """Os nós do escopo de ``no`` (função ou módulo), sem descer nas funções, lambdas e
    classes definidas dentro dele."""
    pilha = list(ast.iter_child_nodes(no))
    while pilha:
        filho = pilha.pop()
        yield filho
        if not isinstance(filho, _ESCOPOS):
            pilha.extend(ast.iter_child_nodes(filho))


def _nomes_temporais(funcao, r: _Relogios) -> set:
    """Variáveis que guardam um tempo medido (ou algo derivado dele), até o ponto fixo."""
    nomes: set = set()
    while True:
        novos = set(nomes)
        for no in ast.walk(funcao):
            if isinstance(no, (ast.Assign, ast.AnnAssign, ast.AugAssign)) and no.value is not None:
                alvos = no.targets if isinstance(no, ast.Assign) else [no.target]
                if _temporal(no.value, nomes, r):
                    for alvo in alvos:
                        novos.update(n.id for n in ast.walk(alvo) if isinstance(n, ast.Name))
        if novos == nomes:
            return nomes
        nomes = novos


def _devolve_tempo(funcao, r: _Relogios) -> bool:
    nomes = _nomes_temporais(funcao, r)
    return any(isinstance(no, ast.Return) and no.value is not None
               and _temporal(no.value, nomes, r) for no in _proprios(funcao))


def _auxiliares_de_relogio(nos, r: _Relogios) -> None:
    """As funções do módulo (de qualquer nível, métodos inclusive) que DEVOLVEM um tempo
    medido passam a contar como relógio para quem as chama — até o ponto fixo."""
    funcoes = [(no, [n for n in ast.walk(no) if isinstance(n, ast.Call)])
               for no in nos if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef))]
    while True:
        novas = {f.name for f, chamadas in funcoes if f.name not in r.nomes
                 and any(_e_relogio(c, r) for c in chamadas) and _devolve_tempo(f, r)}
        if not novas:
            return
        r.nomes |= novas


def _numero_fixo(no, constantes=frozenset()) -> bool:
    if isinstance(no, ast.Constant):
        return isinstance(no.value, (int, float)) and not isinstance(no.value, bool)
    if isinstance(no, ast.Name):
        return no.id in constantes
    if isinstance(no, ast.UnaryOp):
        return _numero_fixo(no.operand, constantes)
    if isinstance(no, ast.BinOp):
        return _numero_fixo(no.left, constantes) and _numero_fixo(no.right, constantes)
    return False


def _ligacoes(nos) -> dict:
    """nome -> o valor de cada ligação dele entre ``nos`` (``None``: ligado sem um valor
    simples — parâmetro, ``for``, ``with``, ``+=``, desempacotamento)."""
    nos = list(nos)
    valores: dict = {}
    simples = set()
    for no in nos:
        if isinstance(no, (ast.Assign, ast.AnnAssign)) and no.value is not None:
            for alvo in (no.targets if isinstance(no, ast.Assign) else [no.target]):
                if isinstance(alvo, ast.Name):
                    valores.setdefault(alvo.id, []).append(no.value)
                    simples.add(id(alvo))
    for no in nos:
        if isinstance(no, ast.Name) and isinstance(no.ctx, ast.Store) and id(no) not in simples:
            valores.setdefault(no.id, []).append(None)
        elif isinstance(no, ast.arg):
            valores.setdefault(no.arg, []).append(None)
    return valores


def _constantes(valores: dict, herdadas=frozenset()) -> set:
    """Os nomes ligados UMA vez, a um número fixo (literais e outros nomes assim)."""
    constantes: set = set()
    while True:
        novas = {nome for nome, vs in valores.items() if nome not in constantes
                 and len(vs) == 1 and vs[0] is not None
                 and _numero_fixo(vs[0], constantes | herdadas)}
        if not novas:
            return constantes
        constantes |= novas


def _tetos_fixos(funcao, r: _Relogios, do_modulo=frozenset()) -> list:
    nomes = _nomes_temporais(funcao, r)
    locais = _ligacoes(ast.walk(funcao))
    herdadas = frozenset(do_modulo) - set(locais)       # o nome local esconde o do módulo
    fixos = herdadas | _constantes(locais, herdadas)
    linhas = []
    for no in ast.walk(funcao):
        if not isinstance(no, ast.Assert):
            continue
        for cmp_ in (n for n in ast.walk(no.test) if isinstance(n, ast.Compare)):
            termos = [cmp_.left, *cmp_.comparators]
            for i, op in enumerate(cmp_.ops):
                a, b = termos[i], termos[i + 1]
                if ((isinstance(op, (ast.Lt, ast.LtE)) and _temporal(a, nomes, r)
                     and _numero_fixo(b, fixos))
                        or (isinstance(op, (ast.Gt, ast.GtE)) and _temporal(b, nomes, r)
                            and _numero_fixo(a, fixos))):
                    linhas.append(no.lineno)
    return sorted(set(linhas))


def _e_postgres(no) -> bool:
    return any(isinstance(n, ast.Attribute) and n.attr == "postgres"
               and isinstance(n.value, ast.Attribute) and n.value.attr == "mark"
               for n in ast.walk(no))


def _funcoes(arvore):
    for no in arvore.body:
        if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield no
        elif isinstance(no, ast.ClassDef) and not any(_e_postgres(d) for d in no.decorator_list):
            yield from (m for m in no.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)))


def varrer(fonte: str) -> dict:
    """{nome da função: [linhas com teto fixo]} de um módulo, sem os marcados postgres."""
    if not any(trecho in fonte for trecho in _TRECHOS_DE_RELOGIO):
        return {}                                   # nenhum relógio: nem precisa da árvore
    arvore = ast.parse(fonte)
    modulo_pg = any(isinstance(no, ast.Assign) and _e_postgres(no.value)
                    and any(isinstance(a, ast.Name) and a.id == "pytestmark" for a in no.targets)
                    for no in arvore.body)
    if modulo_pg:
        return {}
    nos = [no for no in ast.walk(arvore)
           if isinstance(no, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef))]
    r = _relogios_importados(nos)
    _auxiliares_de_relogio(nos, r)
    do_modulo = _constantes(_ligacoes(_proprios(arvore)))
    achados = {}
    for funcao in _funcoes(arvore):
        if (any(_e_postgres(d) for d in funcao.decorator_list)
                or not any(_e_relogio(n, r) for n in ast.walk(funcao))):
            continue
        linhas = _tetos_fixos(funcao, r, do_modulo)
        if linhas:
            achados[funcao.name] = linhas
    return achados


@lru_cache(maxsize=1)
def _achados_da_suite() -> dict:
    achados = {}
    for arquivo in sorted(PASTA.glob("test_*.py")):
        for funcao, linhas in varrer(arquivo.read_text(encoding="utf-8")).items():
            achados[(arquivo.name, funcao)] = linhas
    return achados


def test_nenhum_teto_fixo_de_cpu_fora_dos_prazos():
    fora = {k: v for k, v in _achados_da_suite().items() if k not in PRAZOS}
    assert not fora, (
        "teto de tempo fixo dependente de CPU (use TETO_S, como em test_planilha_inflada.py, "
        "ou, se o teto mede um prazo do próprio teste, registre em PRAZOS com o porquê): "
        + "; ".join(f"{a}:{linhas} ({f})" for (a, f), linhas in sorted(fora.items())))


def test_lista_de_prazos_nao_tem_sobra():
    achados = _achados_da_suite()
    sobra = [k for k in PRAZOS if k not in achados]
    assert not sobra, f"PRAZOS cita teste que não tem mais teto fixo (tire da lista): {sobra}"


def test_a_varredura_reconhece_as_formas_de_teto():
    fonte = '''
import os
import time
import pytest

TETO_S = float(os.environ.get("TESTE_TETO_TEMPO_S") or (12 if os.environ.get("CI") else 2))

def test_direto():
    t0 = time.perf_counter()
    assert time.perf_counter() - t0 < 1.0

def test_por_variavel():
    t0 = time.monotonic()
    fim = time.monotonic()
    dt = fim - t0
    assert dt < 3, dt

def test_em_conjuncao_e_encadeado():
    inicio = time.time()
    decorrido = time.time() - inicio
    assert erro is None and decorrido < 2.0
    assert 1.0 <= decorrido < 15

def test_invertido():
    t0 = time.perf_counter()
    assert 0.5 > time.perf_counter() - t0

def test_escalado():
    t0 = time.perf_counter()
    assert time.perf_counter() - t0 < TETO_S
    assert time.perf_counter() - t0 < TETO_S / 2
    assert time.perf_counter() - t0 < max(TETO_S / 2, 5 * t0)

def test_contagem_nao_e_tempo():
    n = len([1, 2])
    assert n < 3

@pytest.mark.postgres
def test_postgres():
    t0 = time.monotonic()
    assert time.monotonic() - t0 < 1

@pytest.mark.postgres
class TestPostgres:
    def test_na_classe(self):
        t0 = time.monotonic()
        assert time.monotonic() - t0 < 1
'''
    achados = varrer(fonte)
    assert set(achados) == {"test_direto", "test_por_variavel", "test_em_conjuncao_e_encadeado",
                            "test_invertido"}
    assert len(achados["test_em_conjuncao_e_encadeado"]) == 2
    assert varrer("import pytest\npytestmark = [pytest.mark.postgres]\n" + fonte) == {}


def test_a_varredura_pega_constante_auxiliar_alias_e_os_outros_relogios():
    """Os furos da primeira versão (revisão de 30/10), cada um num caso sintético: a
    constante do módulo (também composta), a constante local, a auxiliar que devolve o
    tempo (em dois níveis e como método), o relógio com alias, ``time_ns``,
    ``default_timer`` e ``timeit.timeit``."""
    fonte = '''
import os
import time
import timeit
from time import perf_counter as pc

_TETO_DO_MENOR_S = 5.0
_TETO_COMPOSTO_S = 2 * _TETO_DO_MENOR_S + 1

def _tempo(f):
    comeco = time.perf_counter()
    f()
    return time.perf_counter() - comeco

def _melhor(f):
    return min(_tempo(f), _tempo(f))

def _melhores_tempos(f):
    t_menor = float("inf")
    for _ in range(2):
        t_menor = min(t_menor, _tempo(f))
        assert t_menor < _TETO_DO_MENOR_S, t_menor
    return t_menor

def test_constante_composta_do_modulo():
    assert _melhor(print) <= _TETO_COMPOSTO_S

def test_constante_local():
    teto = 0.5
    assert _tempo(print) < teto

def test_alias():
    t0 = pc()
    assert pc() - t0 < 1.0

def test_time_ns():
    t0 = time.time_ns()
    assert time.time_ns() - t0 < 10**9

def test_default_timer():
    t0 = timeit.default_timer()
    assert timeit.default_timer() - t0 < 1.0

def test_timeit():
    assert timeit.timeit("1 + 1", number=10) < 0.1

class TestMetodo:
    def _medir(self):
        t0 = time.monotonic()
        return time.monotonic() - t0

    def test_por_metodo(self):
        assert self._medir() < 2
'''
    achados = varrer(fonte)
    assert achados == {
        "_melhores_tempos": [22],
        "test_constante_composta_do_modulo": [26],
        "test_constante_local": [30],
        "test_alias": [34],
        "test_time_ns": [38],
        "test_default_timer": [42],
        "test_timeit": [45],
        "test_por_metodo": [53],
    }, achados


def test_a_varredura_reconhece_os_imports_de_relogio():
    """``from time import time``, ``from timeit import default_timer as ...``: o nome
    importado é relógio. ``time()`` de ``from datetime import time`` monta uma hora do dia
    e não é; ``time_ns`` sozinho no arquivo (sem ``time(`` no texto) também é varrido."""
    so_time_ns = '''
import time

def test_ns():
    t0 = time.time_ns()
    assert time.time_ns() - t0 < 5_000_000
'''
    assert varrer(so_time_ns) == {"test_ns": [6]}
    importados = '''
from time import time
from timeit import default_timer as cronometro

def test_time_importado():
    inicio = time()
    assert time() - inicio < 2

def test_cronometro():
    t0 = cronometro()
    assert cronometro() - t0 < 2
'''
    assert varrer(importados) == {"test_time_importado": [7], "test_cronometro": [11]}
    hora_do_dia = '''
from datetime import time

def test_hora():
    assert time(8, 30) < time(9, 0)
    assert time(8).hour < 9
'''
    assert varrer(hora_do_dia) == {}


def test_a_varredura_nao_pega_o_que_escala_nem_o_que_nao_e_tempo():
    """O teto que escala (``TETO_S`` do ambiente, uma constante derivada dele, um nome
    religado sob ``if CI``), a auxiliar que chama relógio mas devolve outra coisa, a
    constante usada fora de uma medida, o nome local que esconde a constante e a razão
    entre dois tempos (sem teto) não são pegos."""
    fonte = '''
import os
import time

TETO_S = float(os.environ.get("TESTE_TETO_TEMPO_S") or (12 if os.environ.get("CI") else 2))
_TETO_DO_MENOR_S = 2.5 * TETO_S
_TAMANHO = 50_000
TETO_POR_AMBIENTE = 2
if os.environ.get("CI"):
    TETO_POR_AMBIENTE = 12

def _tempo(f):
    comeco = time.perf_counter()
    f()
    return time.perf_counter() - comeco

def _contagem(f):
    time.perf_counter()
    return len(str(f))

def test_escalado_pela_constante_derivada():
    assert _tempo(print) < _TETO_DO_MENOR_S
    assert _tempo(print) < TETO_S / 2

def test_teto_por_ambiente():
    assert _tempo(print) < TETO_POR_AMBIENTE

def test_auxiliar_que_nao_devolve_tempo():
    assert _contagem(print) < 3
    assert len("x" * _TAMANHO) <= _TAMANHO

def test_nome_local_esconde_a_constante():
    _TAMANHO = TETO_S * 2
    assert _tempo(print) < _TAMANHO

def test_razao_nao_e_teto():
    t_menor, t_maior = _tempo(print), _tempo(print)
    if t_maior <= max(8.0 * t_menor, 0.25):
        return
    assert t_maior > 0
'''
    assert varrer(fonte) == {}
