"""Toda coluna que o backup grava volta do arquivo com o tipo certo (REV-INFRA-2).

A restauração (``services.backup._desserializar``) pergunta o tipo Python
(``python_type``) da coluna de CADA valor não nulo do arquivo, para voltar o texto ISO a
``date``/``datetime``. O e5724440 trocou o tipo de toda coluna ``Mapped[datetime]`` por
``database.DataHoraUTC`` sem ``python_type`` (o ``TypeDecorator`` herda o do ``TypeEngine``,
que levanta ``NotImplementedError``): do e5724440 ao f24ede70 a restauração respondeu 500
(tests/test_backup_restauracao_sem_perda.py: 9 falhas); o 04bac680 corrigiu.

O teste do 04bac680 (test_aud_infra_datahora_python_type.py) olha só o DataHoraUTC. Esta
catraca olha TODA coluna das tabelas do backup (``backup.MODELOS``): um tipo novo de
coluna (outro ``TypeDecorator``, um tipo cifrado...) sem ``python_type`` cai aqui, num
teste de milissegundos, sem depender de alguém lembrar de rodar a bateria
tests/test_backup_*.py ao mexer no tipo das colunas.
"""
from __future__ import annotations

from datetime import date, datetime

import app.models  # noqa: F401 — registra as tabelas em Base.metadata
from app.services import backup


def _colunas():
    """(tabela, modelo, coluna) de toda coluna que o arquivo de backup leva."""
    return [(nome, modelo, coluna) for nome, modelo in backup.MODELOS
            for coluna in modelo.__table__.columns if coluna.name not in backup.IGNORADAS]


def test_toda_coluna_do_backup_responde_o_tipo_python():
    colunas = _colunas()
    assert len(colunas) > 50, "backup.MODELOS encolheu? a catraca não estaria olhando nada"
    sem_tipo = []
    for nome, _modelo, coluna in colunas:
        try:
            coluna.type.python_type
        except NotImplementedError:
            sem_tipo.append(f"{nome}.{coluna.name} ({type(coluna.type).__name__})")
    assert not sem_tipo, (
        "a restauração do backup responderia 500 no 1º valor destas colunas (o tipo não "
        f"diz o python_type): {sem_tipo}")


def test_data_e_data_hora_vao_e_voltam_pelo_arquivo_sem_mudar():
    exemplos = {datetime: datetime(2026, 3, 4, 5, 6, 7), date: date(2026, 3, 4)}
    vistos: set[type] = set()
    errados = []
    for nome, modelo, coluna in _colunas():
        tipo = coluna.type.python_type
        if tipo not in exemplos:
            continue
        vistos.add(tipo)
        valor = exemplos[tipo]
        de_volta = backup._desserializar(modelo, coluna.name, backup._serializar(valor))
        if de_volta != valor or type(de_volta) is not tipo:
            errados.append(f"{nome}.{coluna.name}: {de_volta!r}")
    assert vistos == {datetime, date}, vistos
    assert not errados, errados
