"""Plugin do pytest: a suíte roda com o relógio ADIANTADO (guarda das bombas-relógio).

Uso (de ``backend/``)::

    RELOGIO_ADIANTADO=2027-01-15T12:00:00+00:00 python -m pytest -p tests._relogio_adiantado ...

Carregado com ``-p`` ANTES do conftest — antes de qualquer import do app —, troca
``datetime.date`` e ``datetime.datetime`` pelas classes de ``tests._relogio``, cujo
relógio parte do instante pedido (ISO com fuso) e continua andando. Emula o runner do
GitHub: hora local = UTC. Construir uma data continua devolvendo o tipo real (ver
``tests._relogio``). O que o relógio não alcança: quem importou ``datetime`` antes do
plugin (o próprio pytest), o relógio do banco (``CURRENT_TIMESTAMP``) e o do sistema —
``time.time`` fica com ele de propósito, porque é contra ele que se medem a data dos
arquivos (o expurgo compara ``time.time()`` com o ``mtime``) e as durações.

Sem ``RELOGIO_ADIANTADO`` no ambiente, não faz nada. Achados TESTES-1 e PERIODOS-9: a
suíte não pode depender do ano em que roda.
"""
import datetime as _modulo
import importlib
import os

_ALVO = os.environ.get("RELOGIO_ADIANTADO")

if _ALVO:
    from tests._relogio import DATA_REAL, INSTANTE_REAL, classes_com_relogio

    # Quem guarda o TIPO da data num registro na importação (o adaptador do sqlite3 e o
    # do psycopg dos testes de PostgreSQL, o formato de célula do openpyxl) é importado
    # antes da troca: o registro fica com o tipo real, que é o que as datas construídas
    # continuam sendo. O pydantic e o SQLAlchemy não: eles comparam a anotação dos
    # modelos do app — já a classe trocada — com a classe que viram na importação, e as
    # duas têm de ser a mesma (o SQLAlchemy ganha, logo abaixo, o tipo real no mapa com
    # que escolhe o tipo de um valor solto). O ``cryptography`` confere o tipo EXATO em
    # código nativo e guarda a classe na primeira assinatura de certificado: assina um,
    # descartável, antes da troca.
    for _nome in ("sqlite3", "psycopg", "openpyxl"):
        try:
            importlib.import_module(_nome)
        except ImportError:
            pass
    try:
        from cryptography import x509 as _x509
        from cryptography.hazmat.primitives.asymmetric import ed25519 as _ed25519
        from cryptography.x509.oid import NameOID as _NameOID
    except ImportError:
        pass
    else:
        _chave = _ed25519.Ed25519PrivateKey.generate()
        _nome_x509 = _x509.Name([_x509.NameAttribute(_NameOID.COMMON_NAME, "relogio")])
        _inicio = _modulo.datetime(2000, 1, 1, tzinfo=_modulo.timezone.utc)
        (_x509.CertificateBuilder().subject_name(_nome_x509).issuer_name(_nome_x509)
         .public_key(_chave.public_key()).serial_number(1).not_valid_before(_inicio)
         .not_valid_after(_inicio + _modulo.timedelta(days=1)).sign(_chave, None))

    _alvo = INSTANTE_REAL.fromisoformat(_ALVO)
    if _alvo.tzinfo is None:
        raise ValueError("RELOGIO_ADIANTADO precisa de fuso, ex.: 2027-01-15T12:00:00+00:00")
    _DESLOCAMENTO = _alvo - INSTANTE_REAL.now(_modulo.timezone.utc)

    def _agora_utc():
        return INSTANTE_REAL.now(_modulo.timezone.utc) + _DESLOCAMENTO

    _modulo.date, _modulo.datetime = classes_com_relogio(_agora_utc)

    # O SQLAlchemy, importado agora, mapeia o tipo de um valor solto (um parâmetro de
    # ``text()``, um ``literal``) pela classe EXATA: sem o tipo real no mapa, a data real
    # iria ao banco pelo adaptador padrão do sqlite3, em outro formato de texto, e as
    # comparações de borda mudariam só sob o plugin.
    from sqlalchemy.sql import sqltypes as _sqltypes

    for _real, _trocada in ((INSTANTE_REAL, _modulo.datetime), (DATA_REAL, _modulo.date)):
        if _trocada in _sqltypes._type_map:
            _sqltypes._type_map.setdefault(_real, _sqltypes._type_map[_trocada])


def pytest_report_header(config):
    if _ALVO:
        return f"RELOGIO_ADIANTADO={_ALVO} (agora, em UTC: {_agora_utc().isoformat()})"
    return None
