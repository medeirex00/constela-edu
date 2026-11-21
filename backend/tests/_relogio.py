"""Relógio dos testes: as classes de data com o relógio trocado (fonte única).

Usadas pelo plugin ``tests._relogio_adiantado`` (a suíte inteira com o relógio adiantado,
a guarda das bombas-relógio) e por :func:`prender`, que prende o relógio do app num
instante só durante UM teste (a fixture ``relogio_no_ano_letivo`` do conftest).

Só o RELÓGIO muda: ``now()``, ``today()`` e ``utcnow()``. Construir uma data
(``datetime(2026, 3, 1)``, ``fromisoformat``, ``combine``) devolve o tipo REAL — o
adaptador de datas do ``sqlite3`` e quem compara ``type(x) is datetime`` não percebem a
troca —, e ``isinstance``/``issubclass`` valem nos dois sentidos. ``now()`` sem fuso
devolve o UTC sem fuso, como no runner do GitHub (hora local = UTC).
"""
from __future__ import annotations

import datetime as _modulo
import sys
from collections.abc import Callable


def _real(nome: str) -> type:
    """A classe REAL do módulo ``datetime``, mesmo com o plugin já tendo trocado a dele."""
    return next(c for c in getattr(_modulo, nome).__mro__
                if c.__module__ == "datetime" and c.__name__ == nome)


INSTANTE_REAL: type = _real("datetime")
DATA_REAL: type = _real("date")


def classes_com_relogio(agora_utc: Callable[[], _modulo.datetime]) -> tuple[type, type]:
    """``(Data, Instante)``: ``date``/``datetime`` cujo relógio é ``agora_utc()``
    (um instante COM fuso)."""
    instante_real, data_real = INSTANTE_REAL, DATA_REAL

    class _MetaData(type):
        def __instancecheck__(cls, obj):
            return isinstance(obj, data_real)

        def __subclasscheck__(cls, sub):
            return issubclass(sub, data_real)

    class _MetaInstante(_MetaData):
        def __instancecheck__(cls, obj):
            return isinstance(obj, instante_real)

        def __subclasscheck__(cls, sub):
            return issubclass(sub, instante_real)

    class Data(data_real, metaclass=_MetaData):
        def __new__(cls, *args, **kwargs):
            return data_real(*args, **kwargs)

        @classmethod
        def today(cls):
            return agora_utc().astimezone(_modulo.timezone.utc).date()

    class Instante(instante_real, metaclass=_MetaInstante):
        def __new__(cls, *args, **kwargs):
            return instante_real(*args, **kwargs)

        @classmethod
        def now(cls, tz=None):
            agora = agora_utc().astimezone(_modulo.timezone.utc)
            return agora.replace(tzinfo=None) if tz is None else agora.astimezone(tz)

        @classmethod
        def utcnow(cls):
            return agora_utc().astimezone(_modulo.timezone.utc).replace(tzinfo=None)

        @classmethod
        def today(cls):
            return cls.now()

    return Data, Instante


def prender(monkeypatch, instante: _modulo.datetime) -> None:
    """Prende em ``instante`` (com fuso) o relógio de todo módulo ``app.*``, ``tests.*`` e
    ``jwt.*`` já importado que usa ``datetime``/``date`` importados pelo nome (``from
    datetime import datetime``) — o caso do app inteiro: ``models.base.agora``,
    ``core.tempo``, ``sync.fuso``, os serviços. O PyJWT entra porque confere o ``iat`` e o
    ``exp`` do token pelo relógio dele: o token emitido no relógio preso tem de valer no
    mesmo relógio. O ``monkeypatch`` desfaz no fim do teste. Não alcança ``time.time``
    nem o relógio do banco."""
    if instante.tzinfo is None:
        raise ValueError("o instante precisa de fuso")
    data, inst = classes_com_relogio(lambda: instante)
    atuais = {"datetime": (INSTANTE_REAL, _modulo.datetime),
              "date": (DATA_REAL, _modulo.date)}
    trocas = {"datetime": inst, "date": data}
    for nome_mod, mod in list(sys.modules.items()):
        if mod is None or not (nome_mod.startswith(("app.", "tests.", "jwt."))
                               or nome_mod in ("app", "jwt")):
            continue
        for nome, aceitas in atuais.items():
            if any(getattr(mod, nome, None) is classe for classe in aceitas):
                monkeypatch.setattr(mod, nome, trocas[nome])
