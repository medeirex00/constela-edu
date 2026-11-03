"""Migração de partida: Alembic + ajustes de dados — UM processo, ANTES do servidor.

Quem chama: o pre-deploy do Railway (``python -m scripts.migrate``) ou o entrypoint.sh
do container. Evita que os N workers do uvicorn corram entre si aplicando DDL. Leva o
banco à última revisão (cria o schema em banco novo, preserva os dados nos
existentes) e aplica as correções de dados idempotentes. Rodar de novo é no-op.

Segurança:
* advisory lock no PostgreSQL: dois migradores ao mesmo tempo se enfileiram;
* ``lock_timeout`` (MIGRACAO_LOCK_TIMEOUT): DDL que espera lock de tabela FALHA e
  REVERTE em segundos em vez de travar as consultas do site atrás dela; aí tenta de
  novo (MIGRACAO_TENTATIVAS, pausa MIGRACAO_PAUSA_S × tentativa);
* banco ADIANTE do código (rollback de imagem): não toca em nada.

Códigos de saída (o Railway só olha 0 × não-zero; o detalhe é para quem lê o log):
  0 = banco em dia (migrou ou já estava; ou adiante ACEITO por SCHEMA_ADIANTE_ACEITO)
  2 = desistiu: lock de tabela ocupado em todas as tentativas (nada foi alterado)
  3 = banco adiante do código e não aceito (nada foi alterado)
  4 = recusado pelo portão de CI (EXIGIR_CI_VERDE=1 e o CI do push no main deste
      commit não está verde — scripts/exigir_ci_verde.py; nada foi alterado)
  1 = qualquer outro erro (a transação reverteu; ver o traceback)

Portão de CI (opcional, decisão do dono): com a variável EXIGIR_CI_VERDE=1 no serviço,
o migrate consulta o CI ANTES de tocar no banco. O comando do Pre-deploy continua um só
(`python -m scripts.migrate`): o Railway roda o Pre-deploy de um serviço com Dockerfile
sem shell, e um `a && b` chegaria ao Python como argumentos — o `b` nunca rodaria.
"""
import os
import sys
import time

from app.core import observabilidade as obs
from app.core.config import settings
from app.core.database import engine, garantir_dados_base
from app.core.migracoes import SchemaAdianteDoCodigo, aplicar_migracoes, estado_do_schema
from scripts._saida import forcar_saida_utf8

SAIDA_OK, SAIDA_ERRO, SAIDA_LOCK, SAIDA_ADIANTE, SAIDA_PORTAO = 0, 1, 2, 3, 4
_ESPERA_DE_LOCK = "55P03"            # lock_not_available (lock_timeout estourado)


def _e_espera_de_lock(erro: BaseException) -> bool:
    visto = set()
    while erro is not None and id(erro) not in visto:
        visto.add(id(erro))
        if getattr(erro, "sqlstate", None) == _ESPERA_DE_LOCK:
            return True
        erro = getattr(erro, "orig", None) or erro.__cause__ or erro.__context__
    return False


def _portao_ligado() -> bool:
    """Falha fechada: qualquer valor que não seja vazio ou um "desligado" explícito
    LIGA o portão — um `yes`/`on` digitado no painel não pode desligá-lo sem aviso."""
    valor = os.environ.get("EXIGIR_CI_VERDE", "").strip().lower()
    return valor not in ("", "0", "false", "nao", "não", "off", "no")


def main() -> int:
    forcar_saida_utf8()
    # O log do Alembic ("Running upgrade ...") sai pelo MESMO logging da API
    # (stdout, JSON com "level"): a migração não lê mais o fileConfig do .ini.
    obs.configurar_logging(settings)
    if _portao_ligado():
        from scripts import exigir_ci_verde
        if exigir_ci_verde.main() != 0:
            print("RECUSADO pelo portão de CI: nada foi alterado.", file=sys.stderr, flush=True)
            return SAIDA_PORTAO
    antes = estado_do_schema(engine)
    print(f"Antes: {antes.descrever()}", flush=True)
    tentativas = max(1, settings.MIGRACAO_TENTATIVAS)
    for tentativa in range(1, tentativas + 1):
        try:
            depois = aplicar_migracoes(engine)
            break
        except SchemaAdianteDoCodigo as erro:
            print(f"RECUSADO: {erro}", file=sys.stderr, flush=True)
            return SAIDA_ADIANTE
        except Exception as erro:  # noqa: BLE001
            if not _e_espera_de_lock(erro):
                raise
            print(f"Tentativa {tentativa}/{tentativas}: lock de tabela ocupado além do "
                  "lock_timeout — a transação reverteu, nada mudou.",
                  file=sys.stderr, flush=True)
            if tentativa == tentativas:
                print("DESISTI: lock ocupado em todas as tentativas. Banco intacto: "
                      f"{estado_do_schema(engine).descrever()}", file=sys.stderr, flush=True)
                return SAIDA_LOCK
            time.sleep(settings.MIGRACAO_PAUSA_S * tentativa)
    garantir_dados_base(engine)
    print(f"Depois: {depois.descrever()}", flush=True)
    print("Migração concluída.", flush=True)
    return SAIDA_OK


if __name__ == "__main__":
    sys.exit(main())
