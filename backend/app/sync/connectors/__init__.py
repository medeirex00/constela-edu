"""Registro de conectores plugáveis.

Adicionar uma plataforma = criar um módulo aqui com uma subclasse de
``Conector`` e chamar ``registrar(MinhaClasse())``. O resto do sistema
(orquestrador, scheduler, painel) descobre tudo por ``obter``/``listar`` —
nunca por ``if plataforma == "matific"``.
"""
from __future__ import annotations

from app.sync.interfaces import Conector

_REGISTRO: dict[str, Conector] = {}


def registrar(conector: Conector) -> None:
    if not conector.plataforma:
        raise ValueError("Conector sem `plataforma` definida.")
    _REGISTRO[conector.plataforma] = conector


def obter(plataforma: str) -> Conector | None:
    return _REGISTRO.get(plataforma)


def listar() -> list[Conector]:
    return list(_REGISTRO.values())


def plataformas_automatizaveis() -> list[str]:
    """Plataformas com obtenção automática (exclui o fallback manual)."""
    from app.sync.interfaces import Estrategia
    return [c.plataforma for c in _REGISTRO.values()
            if c.estrategia != Estrategia.UPLOAD_MANUAL]


def _registrar_embutidos() -> None:
    """Importa e registra os conectores que vêm no projeto. Idempotente."""
    from app.sync.connectors.elefante import ConectorElefante
    from app.sync.connectors.manual import ConectorManual
    from app.sync.connectors.matific import ConectorMatific

    for c in (ConectorManual(), ConectorMatific(), ConectorElefante()):
        registrar(c)


_registrar_embutidos()
