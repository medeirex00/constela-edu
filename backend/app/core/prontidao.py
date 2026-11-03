"""Prontidão do processo: banco acessível E schema na revisão que o código espera.

Por que existe: com ``ENV=producao`` o app NÃO migra na importação — quem migra é
``python -m scripts.migrate`` (pre-deploy do Railway ou entrypoint.sh). Se esse passo
faltar, falhar ou for pulado, o código novo subiria sobre o schema velho e o readiness
antigo (só ``SELECT 1``) diria "ok": o Railway trocaria o tráfego para um processo que
devolve 500 nas rotas que leem colunas novas (no ensaio de 18/10: 19 de 84 rotas).
Com o banco atrás, o readiness responde 503 ``migracao_pendente``, o healthcheck do
deploy reprova e o deploy anterior continua no ar.

Regras (iguais em dev e produção; em dev a migração da importação já deixa em dia):

* ``em_dia``                → pronto.
* ``atras`` / ``sem_versao`` → NÃO pronto (``migracao_pendente``).
* ``adiante`` (o banco tem revisão que o código não conhece = código mais velho):
  - se o processo NUNCA ficou pronto → NÃO pronto (``schema_adiante``): um rollback de
    imagem sobre schema novo não entra no ar às cegas, salvo ``SCHEMA_ADIANTE_ACEITO``;
  - se JÁ ficou pronto → continua pronto (``adiante_apos_boot``): é a janela normal em
    que o pre-deploy do PRÓXIMO deploy migrou enquanto este ainda atende.
* Processo que BOOTOU com o schema errado (``migracao_pendente``/``schema_adiante`` no
  import do ``app.main``) → NUNCA fica pronto (``reinicio_pendente``), mesmo que o
  schema fique em dia depois. Esse boot pulou o agendador de sync, os ajustes de dados
  e a liberação de órfãs, e nada disso roda sozinho depois; se a migração fosse
  aplicada por fora com ele de pé (dentro dos 600 s do healthcheck), o Railway
  trocaria o tráfego para um processo sem a coleta automática — e o ``/status`` das
  escolas, que lê só a configuração, diria "agendador ativo". Com 503 o deploy reprova
  e o próximo boot, já com o schema certo, sobe completo.

O corpo HTTP leva só o motivo; as revisões (banco × código) vão para o log.
"""
from __future__ import annotations

import logging
import threading
import time

from sqlalchemy import text

from app.core import migracoes

logger = logging.getLogger("constela")

# Início do processo (o app importa este módulo no boot): base do tempo no ar.
INICIO = time.time()

PRONTOS = ("em_dia", "adiante_aceito", "adiante_apos_boot")
REINICIO_PENDENTE = "reinicio_pendente"


class Prontidao:
    def __init__(self) -> None:
        self.ja_pronto = False           # ficou pronto alguma vez neste processo
        self._mutex = threading.Lock()
        self._ultimo_motivo: str | None = None
        # Motivo do schema errado no BOOT (None = o boot foi completo).
        self._boot_incompleto: str | None = None

    def exigir_reinicio(self, motivo_boot: str) -> None:
        """Marca que o boot deste processo pulou o agendador, os ajustes de dados e a
        liberação de órfãs por causa do schema errado (``motivo_boot``). Daí em diante
        o readiness responde 503 ``reinicio_pendente`` mesmo com o schema em dia: só
        um boot novo sobe essas peças."""
        self._boot_incompleto = motivo_boot

    def avaliar(self, engine) -> tuple[bool, str, migracoes.EstadoSchema | None]:
        """(pronto, motivo, estado). Uma conexão: ``SELECT 1`` + leitura da versão."""
        try:
            with engine.connect() as conexao:
                conexao.execute(text("SELECT 1"))
                estado = migracoes.estado_do_schema(conexao)
        except Exception:  # noqa: BLE001 — qualquer falha aqui = banco fora
            logger.exception("Healthcheck: banco de dados inacessível")
            return False, "banco_inacessivel", None
        if estado.situacao == "em_dia":
            pronto, motivo = True, "em_dia"
        elif estado.situacao == "adiante":
            if migracoes.adiante_aceito(estado):
                pronto, motivo = True, "adiante_aceito"
            elif self.ja_pronto:
                pronto, motivo = True, "adiante_apos_boot"
            else:
                pronto, motivo = False, "schema_adiante"
        else:                                 # atras | sem_versao
            pronto, motivo = False, "migracao_pendente"
        if pronto and self._boot_incompleto:
            # O schema ficou bom, mas o processo não: ver o docstring do módulo. Não
            # marca ja_pronto — este processo nunca serviu.
            pronto, motivo = False, REINICIO_PENDENTE
        if pronto:
            self.ja_pronto = True
        self._registrar(pronto, motivo, estado)
        return pronto, motivo, estado

    def _registrar(self, pronto: bool, motivo: str, estado: migracoes.EstadoSchema) -> None:
        """Loga só quando o motivo MUDA (o healthcheck sonda a cada poucos segundos)."""
        with self._mutex:
            if motivo == self._ultimo_motivo:
                return
            self._ultimo_motivo = motivo
        extra = {"componente": "prontidao", "schema": motivo,
                 "revisoes_banco": list(estado.banco), "revisoes_codigo": list(estado.codigo)}
        if motivo == REINICIO_PENDENTE:
            logger.error(
                "NÃO PRONTO — REINICIE o serviço (novo Deploy ou Restart). O schema agora "
                "bate (%s), mas este processo bootou com o schema errado (%s) e subiu SEM "
                "o agendador de sync, sem os ajustes de dados e sem liberar execuções "
                "órfãs; nada disso sobe sem um boot novo. O readiness responde 503 até lá.",
                estado.descrever(), self._boot_incompleto,
                extra={**extra, "boot": self._boot_incompleto})
        elif motivo == "em_dia":
            logger.info("Schema em dia: %s", estado.descrever(), extra=extra)
        elif pronto:
            logger.warning("Schema ADIANTE do código, servindo (%s): %s", motivo,
                           estado.descrever(), extra=extra)
        else:
            logger.error(
                "NÃO PRONTO — %s. O readiness responde 503 até o schema bater. "
                "Atrás = falta `python -m scripts.migrate` (pre-deploy); adiante = código "
                "mais velho que o banco (descer o schema ou SCHEMA_ADIANTE_ACEITO).",
                estado.descrever(), extra=extra)


prontidao = Prontidao()
