"""Registro de MÉTODOS de normalização — plugável, como o catálogo de indicadores.

Cada método é uma ESTRATÉGIA com duas funções:
  * ``reduzir(valores, params)``  → a "régua" (calculada UMA vez por coorte/janela);
  * ``transformar(valor, regua, sentido, params)`` → 0–100 (aplicada por aluno).

Adicionar um método novo (ex.: z-score) = acrescentar uma entrada aqui. O motor
NUNCA muda — ele só chama ``reduzir`` e ``transformar`` do método escolhido.

A coorte (escola | turma | série) é um EIXO ORTOGONAL: o motor passa a
distribuição da coorte certa; o método só calcula sobre o que recebe.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Metodo:
    id: str
    label: str
    coortes_validas: tuple[str, ...]
    reduzir: Callable[[list[float], dict], dict]
    transformar: Callable[[float, dict, str, dict], float]
    depende_da_coorte: bool = True    # meta/max/fixa não dependem da distribuição


def _percentil(valores: list[float], p: float) -> float:
    """Percentil p (0–100) por interpolação linear. Lista pode vir desordenada."""
    xs = sorted(v for v in valores if v is not None)
    if not xs:
        return 0.0
    if len(xs) == 1:
        return float(xs[0])
    k = (len(xs) - 1) * (p / 100.0)
    baixo = int(k)
    alto = min(baixo + 1, len(xs) - 1)
    return float(xs[baixo] + (xs[alto] - xs[baixo]) * (k - baixo))


def _transformar_linear(valor: float, regua: dict, sentido: str, params: dict) -> float:
    """valor ÷ régua → 0–100 (teto 100). Respeita 'menor_melhor' invertendo."""
    r = float(regua.get("regua", 0.0))
    if r <= 0:
        return 0.0
    frac = float(valor) / r
    if sentido == "menor_melhor":
        frac = 1.0 - min(max(frac, 0.0), 1.0)
    return round(max(0.0, min(1.0, frac)) * 100.0, 2)


# --- reduções (cada uma define QUEM é a régua) -------------------------------

def _reduzir_percentil(valores: list[float], params: dict) -> dict:
    """Percentil ENDURECIDO (padrão P90). Winsoriza no P{winsor} e, em amostra
    pequena (< min_n valores > 0), cai para mediana × 1.5 (mais estável). É isto
    que impede um único aluno excepcional (a 'Antonella') de achatar os demais."""
    p = float(params.get("p", 90))
    winsor = float(params.get("winsor", 95))
    min_n = int(params.get("min_n", 10))
    positivos = [float(v) for v in valores if v and float(v) > 0]
    if len(positivos) < min_n:
        med = _percentil(positivos, 50)
        return {"regua": round(med * 1.5, 4), "modo": "mediana_x1.5",
                "n": len(positivos)}
    teto = _percentil(positivos, winsor)
    winsorizados = [min(v, teto) for v in positivos]
    regua = _percentil(winsorizados, p) or teto
    return {"regua": round(regua, 4), "modo": f"p{int(p)}", "n": len(positivos)}


def _reduzir_meta(valores: list[float], params: dict) -> dict:
    """Meta pedagógica FIXA (ex.: 1200 min = 100%). Não depende dos alunos —
    imune a outlier e resolve o 'início do ano' (todos baixos → notas baixas)."""
    return {"regua": float(params.get("meta") or 0.0), "modo": "meta"}


def _reduzir_max_manual(valores: list[float], params: dict) -> dict:
    """Máximo MANUAL informado; se ausente, o máximo da coorte (comportamento
    legado — desencorajado, é o que causa o achatamento)."""
    manual = params.get("max")
    if manual:
        return {"regua": float(manual), "modo": "max_manual"}
    positivos = [float(v) for v in valores if v is not None]
    return {"regua": max(positivos, default=0.0), "modo": "max_coorte"}


def _reduzir_media(valores: list[float], params: dict) -> dict:
    """Média da coorte (escola/turma). Aluno médio ≈ 100; acima passa do teto."""
    positivos = [float(v) for v in valores if v and float(v) > 0]
    media = sum(positivos) / len(positivos) if positivos else 0.0
    return {"regua": round(media, 4), "modo": "media", "n": len(positivos)}


def _reduzir_fixa(valores: list[float], params: dict) -> dict:
    """Constante (1.0 para proporções como taxa de acerto: 100% = tudo certo)."""
    return {"regua": float(params.get("valor", 1.0)), "modo": "fixa"}


REGISTRO: dict[str, Metodo] = {
    m.id: m for m in [
        Metodo("percentil", "Percentil 90 (recomendado)",
               ("escola", "turma", "serie"), _reduzir_percentil, _transformar_linear),
        Metodo("meta", "Meta pedagógica fixa",
               ("escola",), _reduzir_meta, _transformar_linear, depende_da_coorte=False),
        Metodo("max_manual", "Valor máximo manual",
               ("escola", "turma"), _reduzir_max_manual, _transformar_linear),
        Metodo("media", "Média (da escola ou da turma)",
               ("escola", "turma", "serie"), _reduzir_media, _transformar_linear),
        Metodo("fixa", "Percentual fixo (100%)",
               ("escola",), _reduzir_fixa, _transformar_linear, depende_da_coorte=False),
    ]
}


def obter(metodo_id: str) -> Metodo | None:
    return REGISTRO.get(metodo_id)


def normalizar(metodo_id: str, valor: float, valores_coorte: list[float],
               sentido: str, parametros: dict) -> tuple[float, dict]:
    """Atalho p/ teste/uso pontual: reduz + transforma de uma vez. O motor real
    chama ``reduzir`` UMA vez por coorte e ``transformar`` por aluno (mais rápido)."""
    m = obter(metodo_id) or REGISTRO["percentil"]
    regua = m.reduzir(valores_coorte, parametros or {})
    return m.transformar(valor, regua, sentido, parametros or {}), regua
