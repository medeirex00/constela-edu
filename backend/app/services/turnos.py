"""Rótulo e ordem de APRESENTAÇÃO dos turnos escolares (``Turma.turno``).

Fonte ÚNICA compartilhada pelo ranking de leitura por turno e pelas premiações
por turno. NÃO define QUAIS turnos existem — isso vem sempre do banco
(``Turma.turno``); aqui só se formata e ordena o que aparecer. Turno desconhecido
cai no title-case do valor cru; ``None`` (turma sem turno cadastrado) vira "Sem
turno" e vai por último. Nada de turma/turno hardcoded como "os turnos da escola".

IMPORTANTE: turno (manhã/tarde/noite) é o PERÍODO ESCOLAR — eixo ORTOGONAL ao
PERÍODO TEMPORAL (intervalo de datas). Os dois nunca se misturam.
"""
from __future__ import annotations

_ROTULO_TURNO = {"manha": "Manhã", "tarde": "Tarde", "noite": "Noite",
                 "integral": "Integral"}
_ORDEM_TURNO = {"manha": 0, "tarde": 1, "noite": 2, "integral": 3}


def rotulo_turno(turno: str | None) -> str:
    if turno is None:
        return "Sem turno"
    return _ROTULO_TURNO.get(turno, turno.replace("_", " ").strip().title() or turno)


def ordem_turno(turno: str | None) -> tuple:
    """Chave de ordenação estável (conhecidos na ordem pedagógica, desconhecidos
    em ordem alfabética, ``None`` por último)."""
    if turno is None:
        return (2, 0, "")
    return (0, _ORDEM_TURNO.get(turno, 99), turno)
