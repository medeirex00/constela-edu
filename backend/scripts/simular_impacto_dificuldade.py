"""Simulação ANTES/DEPOIS da dificuldade por livro (v1) sobre o catálogo de
referência — READ-ONLY, sem banco. Uso (da pasta backend/):

    python scripts/simular_impacto_dificuldade.py [--completo]

"Antes" = régua institucional A3 por NÍVEL (todo livro do nível vale a base) e,
para comparação, a tabela-semente por FAIXA das escolas (1/2/4/8/12/16).
"Depois" = v1: A3 × ajuste intrínseco (wordCount) × fator de série.
"""
from __future__ import annotations

import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # rodar de backend/

from app.services import dificuldade_livro as dl  # noqa: E402
from app.services import scoring  # noqa: E402

SEED = {"AA": 1, "BB": 1, "CC": 1, "DD": 1, "A": 2, "B": 2, "C": 2,
        **{c: 4 for c in "DEFGHIJ"}, **{c: 8 for c in "KLMNOPQR"},
        **{c: 12 for c in "STUVWX"}, "Y": 16, "Z": 16}
SERIES = ["1º Ano", "2º Ano", "3º Ano", "4º Ano", "5º Ano"]


def pct(v, p):
    v = sorted(v)
    if not v:
        return 0.0
    if len(v) == 1:
        return v[0]
    pos = (len(v) - 1) * p
    lo = int(pos)
    fr = pos - lo
    return v[lo] + (v[lo + 1] - v[lo]) * fr if lo + 1 < len(v) else v[-1]


def main(completo: bool = False) -> int:
    cat = dl.catalogo()
    regra = dl.RegraV1()
    livros = sorted(cat.por_id.values(), key=lambda b: (dl.posicao_nivel(b.nivel) or 0, b.word_count))
    ordem = list(scoring.NIVEIS_ORDENADOS) + ["A+", "Z+"]
    por_nivel = defaultdict(list)
    for b in livros:
        por_nivel[b.nivel].append(b)

    print(f"Catálogo: {len(livros)} livros | versão vigente: {dl.VERSAO_VIGENTE}\n")
    print("=== IMPACTO: antigo A3 por nível → novo v1 (5º ano, fator 1,00) ===")
    var = [(regra.valor_livro(b.nivel, b.titulo, "5º Ano") / dl.base_nivel(b.nivel) - 1) * 100
           for b in livros if dl.base_nivel(b.nivel)]
    sobe = sum(1 for v in var if v > 0.01)
    desce = sum(1 for v in var if v < -0.01)
    print(f"  livros ↑ {sobe} | ↓ {desce} | = {len(var) - sobe - desce} | mediana {st.median(var):+.1f}% "
          f"| P5 {pct(var, .05):+.1f}% | P95 {pct(var, .95):+.1f}% | mín {min(var):+.1f}% | máx {max(var):+.1f}%")
    ranking = sorted(livros, key=lambda b: regra.valor_livro(b.nivel, b.titulo, "5º Ano") / max(dl.base_nivel(b.nivel), 1e-9))
    print("  maiores reduções:")
    for b in ranking[:5]:
        print(f"    {b.nivel:<3} wc={b.word_count:>6} {(regra.valor_livro(b.nivel, b.titulo, '5º Ano') / dl.base_nivel(b.nivel) - 1) * 100:+6.1f}%  {b.titulo[:44]}")
    print("  maiores aumentos:")
    for b in ranking[-5:]:
        print(f"    {b.nivel:<3} wc={b.word_count:>6} {(regra.valor_livro(b.nivel, b.titulo, '5º Ano') / dl.base_nivel(b.nivel) - 1) * 100:+6.1f}%  {b.titulo[:44]}")

    print("\n=== TABELA REPRESENTATIVA (menor / mediano / maior de cada nível) ===")
    print(f"{'nv':<3} {'título':<30} {'wc':>6} | {'A3':>6} {'seed':>4} | " + " ".join(f"{s[:2]:>6}" for s in SERIES) + " |  var%")
    alvo = ordem if completo else ["AA", "A", "D", "H", "N", "R", "S", "X", "Z", "A+", "Z+"]
    for nv in alvo:
        bs = por_nivel.get(nv) or []
        if not bs:
            continue
        amostra = [bs[0], bs[len(bs) // 2], bs[-1]] if len(bs) >= 3 else bs
        for b in amostra:
            vals = [regra.valor_livro(nv, b.titulo, s) for s in SERIES]
            base = dl.base_nivel(nv)
            print(f"{nv:<3} {b.titulo[:30]:<30} {b.word_count:>6} | {base:>6.2f} {SEED.get(nv, '-'):>4} | "
                  + " ".join(f"{v:>6.2f}" for v in vals) + f" | {(vals[-1] / base - 1) * 100:+5.0f}%")

    print("\n=== ANTI-FARMING (v1, 5º ano; 1º ano entre parênteses) ===")
    tip = {nv: regra.valor_tipico(nv, "5º Ano") for nv in ordem if nv in por_nivel}
    print(f"  30×AA = {30 * tip['AA']:.1f} ({30 * regra.valor_tipico('AA', '1º Ano'):.1f}) | 30×A = {30 * tip['A']:.1f} | "
          f"10×N = {10 * tip['N']:.1f} | 5×S = {5 * tip['S']:.1f} | 1×Z = {tip['Z']:.1f} | 1×Z+ = {tip['Z+']:.1f}")
    print(f"  livros AA para igualar 1 Z: {tip['Z'] / tip['AA']:.0f} | A para 1 N: {tip['N'] / tip['A']:.1f} | "
          f"D para 1 V: {tip['V'] / tip['D']:.1f}")
    print(f"  5º ano lendo 2×V (típico da série) = {2 * tip['V']:.1f} vs 20×AA = {20 * tip['AA']:.1f}")

    print("\n=== FATOR DE SÉRIE: leitor típico (10 livros do nível típico da série) ===")
    tipico_serie = {"1º Ano": "F", "2º Ano": "K", "3º Ano": "N", "4º Ano": "T", "5º Ano": "V"}
    tot = {s: 10 * regra.valor_tipico(tipico_serie[s], s) for s in SERIES}
    print("  " + " | ".join(f"{s}({tipico_serie[s]})={tot[s]:.1f}" for s in SERIES)
          + f" | razão 5º/1º = {tot['5º Ano'] / tot['1º Ano']:.1f}x (sem fator: 5,2x)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--completo" in sys.argv))
