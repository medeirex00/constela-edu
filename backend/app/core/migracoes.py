"""Aplicação das migrações Alembic dentro da própria aplicação.

Substitui o antigo `Base.metadata.create_all` + micro-migrações manuais. É
chamado pelo entrypoint do container (``scripts.migrate``, UMA vez antes dos
workers) e pelo startup de desenvolvimento (``app.main``). Idempotente e
seguro para bancos já existentes.

Estratégia de adoção (preserva 100% dos dados):

* Banco NOVO (sem tabelas) → ``upgrade heads`` cria todo o schema.
* Banco JÁ versionado pelo Alembic → ``upgrade heads`` aplica o que faltar.
* Banco EXISTENTE anterior ao Alembic (tem tabelas, mas sem
  ``alembic_version``) → ``stamp`` da revisão base (assume que o schema já é
  o da base — as micro-migrações antigas o mantinham em dia — SEM recriar
  nada) e, em seguida, ``upgrade heads`` para migrações futuras.

RAMOS: o destino é ``heads`` (plural), não ``head``. Frentes independentes podem
partir da MESMA revisão (ex.: currículo e catálogo de livros, que tocam tabelas
diferentes) sem que uma precise esperar a outra entrar no histórico; ``heads``
aplica todos os ramos existentes, e com um ramo só é idêntico ao antigo ``head``.

PRONTIDÃO: ``estado_do_schema`` compara o banco com as revisões que os arquivos
DESTA imagem conhecem. É o que o readiness (``/api/health/ready``) usa para não
declarar pronto um processo cujo código é mais novo que o banco (migração que não
rodou) — o Railway então não troca o tráfego e o deploy anterior segue no ar.
Sequência de produção (pre-deploy + ENV=producao): docs/operacao/PRODUCAO-ENV-E-MIGRACOES.md.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

from app.core.config import BASE_DIR

logger = logging.getLogger("constela.migracoes")

# Revisão que representa o schema completo no momento em que o Alembic foi
# adotado. Bancos pré-Alembic são "carimbados" com ela.
_REVISAO_BASE = "0001"
# Tabela âncora do sistema: se existe mas não há `alembic_version`, o banco é
# de uma instalação anterior à adoção do Alembic.
_TABELA_ANCORA = "usuarios"
# Tabela de versão padrão do Alembic (o env.py não configura outra).
_TABELA_VERSAO = "alembic_version"

# Namespace do advisory lock da MIGRAÇÃO (4711–4713 são importação, coleta e
# recálculo — ver app/core/database.py). Um só migrador por vez no banco inteiro.
_NS_MIGRACAO = 4714
_INTERVALO_PG = re.compile(r"^\d+(ms|s|min)?$")


def _config() -> Config:
    """Config do Alembic com caminhos ABSOLUTOS (independe do diretório atual)."""
    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "alembic"))
    return cfg


def _config_da_aplicacao() -> Config:
    """A mesma Config, mas SEM o caminho do ``alembic.ini``.

    Com o arquivo, o ``env.py`` roda ``fileConfig(alembic.ini)``, que troca o
    handler da raiz por um ``StreamHandler(sys.stderr)`` em texto e baixa a raiz
    para WARNING. Dentro do processo da API (migração no import, modo dev) isso
    desfazia o ``configurar_logging``: o log de acesso INFO sumia e o resto ia
    para o stderr, que o Railway pinta de erro. Sem o arquivo o env.py pula o
    fileConfig e as mensagens do Alembic saem pelo logging da aplicação. O
    ``[alembic]`` do .ini só tem ``script_location`` (abaixo), ``prepend_sys_path``
    (inócuo: o pacote ``app`` já está importável aqui) e ``file_template`` (só para
    ``alembic revision``). A linha de comando ``alembic`` continua lendo o .ini."""
    cfg = Config()
    cfg.set_main_option("script_location", str(BASE_DIR / "alembic"))
    return cfg


class SchemaAdianteDoCodigo(RuntimeError):
    """O banco está numa revisão que este código NÃO conhece: o código é mais antigo
    que o banco (rollback de código sem descer o schema, ou imagem velha)."""


@dataclass(frozen=True)
class EstadoSchema:
    """Banco × código. ``situacao``:

    * ``em_dia``     — as revisões do banco são exatamente as heads do código;
    * ``atras``      — o banco é conhecido, mas falta migração (código mais novo);
    * ``sem_versao`` — sem ``alembic_version`` (banco vazio ou pré-Alembic);
    * ``adiante``    — o banco tem revisão que o código não conhece (código mais velho).
    """
    situacao: str
    banco: tuple[str, ...]
    codigo: tuple[str, ...]
    desconhecidas: tuple[str, ...] = ()

    @property
    def falta_migrar(self) -> bool:
        return self.situacao in ("atras", "sem_versao")

    def descrever(self) -> str:
        return (f"schema {self.situacao}: banco={list(self.banco) or '-'} "
                f"código={list(self.codigo)}"
                + (f" desconhecidas={list(self.desconhecidas)}" if self.desconhecidas else ""))


@lru_cache(maxsize=1)
def _revisoes_do_codigo() -> tuple[frozenset[str], frozenset[str]]:
    """(heads, todas as revisões) dos arquivos de migração DESTA imagem — lido UMA
    vez por processo (o readiness consulta a cada sonda; o diretório não muda)."""
    script = ScriptDirectory.from_config(_config())
    return (frozenset(script.get_heads()),
            frozenset(r.revision for r in script.walk_revisions()))


def revisoes_do_banco(conexao: Connection) -> frozenset[str]:
    """Revisões gravadas em ``alembic_version`` (vazio se a tabela não existe).

    Lê a tabela direto, sem ``MigrationContext``: o construtor dele loga em INFO
    ("Context impl ...", "Will assume ... DDL") a cada chamada, e o readiness chama
    isto a cada sonda — eram 2 linhas por sonda no log de produção. É a mesma
    leitura que o ``get_current_heads`` do Alembic faz (tabela padrão, sem schema
    próprio: o env.py não muda ``version_table``)."""
    if not inspect(conexao).has_table(_TABELA_VERSAO):
        return frozenset()
    return frozenset(conexao.execute(
        text(f"SELECT version_num FROM {_TABELA_VERSAO}")).scalars())


def estado_do_schema(alvo: Engine | Connection) -> EstadoSchema:
    """Compara as revisões do banco com as do código. Só LÊ (uma consulta barata)."""
    heads, todas = _revisoes_do_codigo()
    if isinstance(alvo, Engine):
        with alvo.connect() as conexao:
            banco = revisoes_do_banco(conexao)
    else:
        banco = revisoes_do_banco(alvo)
    desconhecidas = tuple(sorted(banco - todas))
    if desconhecidas:
        situacao = "adiante"
    elif not banco:
        situacao = "sem_versao"
    elif banco == heads:
        situacao = "em_dia"
    else:
        situacao = "atras"
    return EstadoSchema(situacao, tuple(sorted(banco)), tuple(sorted(heads)), desconhecidas)


def revisoes_adiante_aceitas() -> frozenset[str]:
    from app.core.config import settings
    return frozenset(x.strip() for x in (settings.SCHEMA_ADIANTE_ACEITO or "").split(",")
                     if x.strip())


def adiante_aceito(estado: EstadoSchema) -> bool:
    """Banco adiante, mas TODAS as revisões desconhecidas foram declaradas compatíveis
    (ids exatos em ``SCHEMA_ADIANTE_ACEITO``)."""
    return (estado.situacao == "adiante"
            and set(estado.desconhecidas) <= revisoes_adiante_aceitas())


def _intervalo(valor: str) -> str:
    """Valor de lock_timeout vindo do ambiente: só dígitos + unidade (nada de SQL)."""
    valor = (valor or "").strip()
    if not _INTERVALO_PG.fullmatch(valor):
        raise ValueError(f"intervalo inválido para o PostgreSQL: {valor!r} (ex.: 5s, 500ms)")
    return valor


def _tomar_a_vez(conexao: Connection) -> None:
    """PostgreSQL: UM migrador por vez (advisory lock transacional — cai no commit ou
    no rollback, então também funciona atrás do pooler do Supabase) e prazo para
    esperar lock de tabela. Vale para o pre-deploy, para o entrypoint e para o boot
    em modo dev (N workers/réplicas se enfileiram em vez de correr com DDL). As
    migrações podem apertar o prazo com o próprio ``SET LOCAL lock_timeout``."""
    if conexao.dialect.name != "postgresql":
        return
    from app.core.config import settings
    conexao.exec_driver_sql(
        f"SET LOCAL lock_timeout = '{_intervalo(settings.MIGRACAO_ESPERA_VEZ)}'")
    conexao.exec_driver_sql(f"SELECT pg_advisory_xact_lock({_NS_MIGRACAO}, 0)")
    conexao.exec_driver_sql(
        f"SET LOCAL lock_timeout = '{_intervalo(settings.MIGRACAO_LOCK_TIMEOUT)}'")


def _mensagem_adiante(estado: EstadoSchema) -> str:
    return (f"O banco está em {list(estado.desconhecidas)}, revisão que este código não "
            f"conhece (heads do código: {list(estado.codigo)}): o código é MAIS ANTIGO que "
            "o banco. Nada foi alterado. Saídas: descer o schema com o código que conhece "
            "a revisão, ou — só se ela for aditiva/compatível — declarar "
            "SCHEMA_ADIANTE_ACEITO com o id exato.")


def aplicar_migracoes(engine: Engine) -> EstadoSchema:
    """Leva o banco até a última revisão, preservando dados existentes.

    Recusa (``SchemaAdianteDoCodigo``) tocar num banco ADIANTE do código, a não ser
    que as revisões desconhecidas estejam em ``SCHEMA_ADIANTE_ACEITO`` (aí é no-op).
    Devolve o estado do schema ao fim."""
    tabelas = set(inspect(engine).get_table_names())
    pre_alembic = _TABELA_ANCORA in tabelas and _TABELA_VERSAO not in tabelas
    sqlite = engine.dialect.name == "sqlite"

    cfg = _config_da_aplicacao()
    # Conexão única compartilhada entre os comandos (padrão recomendado pelo
    # Alembic para uso programático): stamp e upgrade veem o MESMO banco.
    with engine.connect() as conexao:
        if sqlite:
            # PRAGMA foreign_keys só muda FORA de transação; desligamos ANTES
            # de qualquer BEGIN. Migrações que recriam tabelas em lote (SQLite
            # não altera constraint no lugar) fariam DROP TABLE de tabelas
            # referenciadas — com a checagem ligada, isso falharia.
            conexao.exec_driver_sql("PRAGMA foreign_keys=OFF")
        try:
            _tomar_a_vez(conexao)
            antes = estado_do_schema(conexao)
            if antes.situacao == "adiante":
                if not adiante_aceito(antes):
                    raise SchemaAdianteDoCodigo(_mensagem_adiante(antes))
                logger.warning("Migração NÃO aplicada: banco adiante do código, aceito por "
                               "SCHEMA_ADIANTE_ACEITO (%s)", antes.descrever())
                conexao.rollback()
                depois = antes
            else:
                cfg.attributes["connection"] = conexao
                if pre_alembic:
                    command.stamp(cfg, _REVISAO_BASE)
                command.upgrade(cfg, "heads")
                conexao.commit()
                depois = estado_do_schema(conexao)
                conexao.rollback()
        except Exception:
            # Nunca devolver ao pool uma conexão com a checagem desligada:
            # descarta a conexão física (o próximo checkout religa via evento).
            if sqlite:
                conexao.invalidate()
            raise
        else:
            if sqlite:
                conexao.exec_driver_sql("PRAGMA foreign_keys=ON")
    return depois
