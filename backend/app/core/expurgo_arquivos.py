"""Expurgo dos arquivos com PRAZO que a API grava em disco (docs/operacao/ARMAZENAMENTO.md).

* prévia não confirmada em ``UPLOADS_DIR/temporarios`` (#1 do inventário): o original do
  relatório entre "analisar" e "confirmar", gravado pela importação e pela sincronização.
  Expira em ``IDADE_MAXIMA_TEMP_S`` (24 h);
* cópia de relatório exportado em ``EXPORTS_DIR`` (#3): expira em ``EXPORTS_RETENCAO_DIAS``
  (7 dias; 0 desliga).

As duas guardam nomes de crianças. Antes, os prazos só eram aplicados dentro de OUTRA ação
(uma nova análise de PDF/XLSX, uma nova exportação): sem ela — férias, escola que importa
pouco, a sincronização, que grava no mesmo ``temporarios`` e nunca limpava — o arquivo
ficava no disco sem prazo, e o expurgo da exclusão de aluno (LGPD) deixa as prévias de fora
justamente porque "expiram sozinhas".

Agora o expurgo roda numa thread daemon por processo (cada worker uvicorn tem a sua), ligada
no startup do app (``app.main``) e parada no shutdown: uma passada logo no boot e depois a
cada ``INTERVALO_S`` (1 h). O prazo efetivo é, então, o prazo mais até uma hora. Vários
workers apagando o mesmo arquivo não é problema (``missing_ok``). Nunca derruba o boot nem a
API: um erro de disco num arquivo pula o arquivo; um erro numa pasta não impede a outra.

Só são apagados os arquivos com o NOME que o próprio app grava (``NOME_DA_PREVIA``,
``NOME_DA_COPIA``). Em desenvolvimento, sem ``DADOS_DIR``, ``EXPORTS_DIR`` é
``<raiz do repositório>/exports`` — onde o dono guarda as entregas — e o expurgo roda em todo
boot: um arquivo com outro nome ali ou em ``temporarios`` (do dono, do operador) fica, por mais
velho que seja.
Os ORIGINAIS confirmados (``UPLOADS_DIR/<plataforma>/``) NÃO entram: o prazo deles é decisão
do dono (ARMAZENAMENTO.md, seção 5). Também ficam os arquivos que começam com ponto
(``.gitkeep``) e as subpastas de ``EXPORTS_DIR``.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger("constela.expurgo")

#: Idade máxima da prévia não confirmada em ``UPLOADS_DIR/temporarios``.
IDADE_MAXIMA_TEMP_S = 24 * 3600
#: Intervalo entre duas passadas do expurgo de fundo (depois da passada do boot).
INTERVALO_S = 3600.0
_DIA_S = 86_400

#: O nome da prévia: o token que ``routers/importacoes._guardar_temporario`` grava (também
#: pela sincronização) e que a confirmação aceita (``importacoes._TOKEN_VALIDO``, a mesma
#: regra; um teste trava as duas juntas).
NOME_DA_PREVIA = re.compile(r"^[0-9a-f]{32}\.(pdf|xlsx)$")
#: O nome da cópia de relatório: ``<tipo>_AAAAMMDD_HHMMSS.<formato>`` de
#: ``routers/relatorios`` (``ranking``, ``alunos``, ``livros``, ``ranking_cartaz``,
#: ``ranking_cartaz_<matéria>``). ``[0-9]`` e não ``\d``, que aceita outros dígitos Unicode.
NOME_DA_COPIA = re.compile(r"^[a-z_]+_[0-9]{8}_[0-9]{6}\.(csv|xlsx|pdf)$")


def _apagar_se_mais_velho(arquivo: Path, limite: float, nome: re.Pattern[str]) -> bool:
    """Apaga ``arquivo`` se ele tem o ``nome`` que o app grava e é mais velho que
    ``limite``. Arquivo de outro nome (do dono, do operador) nunca é tocado."""
    if not nome.fullmatch(arquivo.name):
        return False
    try:
        if arquivo.is_file() and arquivo.stat().st_mtime < limite:
            arquivo.unlink(missing_ok=True)
            return True
    except OSError:
        pass                     # outro worker apagou antes, sem permissão, disco fora
    return False


def limpar_temporarios(agora: float | None = None) -> int:
    """Apaga as prévias (PDF/XLSX com o nome ``NOME_DA_PREVIA``) com mais de
    ``IDADE_MAXIMA_TEMP_S`` em ``UPLOADS_DIR/temporarios``. Devolve quantas apagou."""
    pasta = Path(settings.UPLOADS_DIR) / "temporarios"
    if not pasta.is_dir():
        return 0
    limite = (time.time() if agora is None else agora) - IDADE_MAXIMA_TEMP_S
    return sum(_apagar_se_mais_velho(arquivo, limite, NOME_DA_PREVIA)
               for arquivo in pasta.iterdir())


def expurgar_exports(agora: float | None = None) -> int:
    """Apaga as cópias de relatório com mais de ``EXPORTS_RETENCAO_DIAS`` em ``EXPORTS_DIR``
    (só os arquivos do primeiro nível com o nome ``NOME_DA_COPIA``; as subpastas e qualquer
    outro arquivo ficam). ``0`` desliga. Devolve quantas apagou."""
    dias = settings.EXPORTS_RETENCAO_DIAS
    pasta = Path(settings.EXPORTS_DIR)
    if dias <= 0 or not pasta.is_dir():
        return 0
    limite = (time.time() if agora is None else agora) - dias * _DIA_S
    return sum(_apagar_se_mais_velho(arquivo, limite, NOME_DA_COPIA)
               for arquivo in pasta.iterdir())


def expurgar(agora: float | None = None) -> tuple[int, int]:
    """Uma passada pelas duas pastas: (prévias apagadas, cópias apagadas). Nunca levanta."""
    apagados = []
    for nome, passo in (("prévias", limpar_temporarios), ("cópias", expurgar_exports)):
        try:
            apagados.append(passo(agora))
        except Exception as erro:  # noqa: BLE001 — o expurgo nunca derruba quem o chama
            logger.warning("Expurgo de arquivos: a limpeza das %s falhou (%s).",
                           nome, type(erro).__name__)
            apagados.append(0)
    previas, copias = apagados
    if previas or copias:
        # Só as contagens: o nome de uma cópia ou do original pode trazer nome de criança.
        logger.info("Expurgo de arquivos: %d prévia(s) não confirmada(s) e %d cópia(s) de "
                    "relatório apagada(s) por prazo.", previas, copias)
    return previas, copias


class _Expurgador:
    """A thread do processo: uma passada imediata (o boot) e depois uma a cada intervalo."""

    def __init__(self, intervalo_s: float, relogio: Callable[[], float]) -> None:
        self.intervalo_s = intervalo_s
        self._relogio = relogio
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None

    def _laco(self) -> None:
        while True:
            try:
                expurgar(self._relogio())
            except Exception as erro:  # noqa: BLE001 — o relógio também não derruba a thread
                logger.warning("Expurgo de arquivos: a passada falhou (%s).",
                               type(erro).__name__)
            if self._parar.wait(self.intervalo_s):
                return

    def iniciar(self) -> None:
        self._parar.clear()
        self._thread = threading.Thread(target=self._laco, name="expurgo-arquivos",
                                        daemon=True)
        self._thread.start()

    def parar(self, timeout: float) -> None:
        self._parar.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def vivo(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


_trava = threading.Lock()
_atual: _Expurgador | None = None


def iniciar(intervalo_s: float = INTERVALO_S,
            relogio: Callable[[], float] = time.time) -> bool:
    """Liga o expurgo de fundo do processo (startup do app). Idempotente; nunca levanta."""
    global _atual
    with _trava:
        if _atual is not None and _atual.vivo():
            return True
        try:
            expurgador = _Expurgador(intervalo_s, relogio)
            expurgador.iniciar()
        except Exception as erro:  # noqa: BLE001 — sem a thread, a API segue como antes
            logger.warning("Expurgo de arquivos não iniciou (%s).", type(erro).__name__)
            return False
        _atual = expurgador
        return True


def parar(timeout: float = 5.0) -> None:
    """Para o expurgo de fundo do processo (shutdown do app). Sem ele, nada a fazer."""
    global _atual
    with _trava:
        expurgador, _atual = _atual, None
    if expurgador is not None:
        expurgador.parar(timeout)


def ativo() -> bool:
    return _atual is not None and _atual.vivo()
