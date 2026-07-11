"""Contrato dos conectores de plataforma e os DTOs que trafegam entre camadas.

O ``Conector`` é a fronteira de desacoplamento: o orquestrador, o scheduler e o
painel NÃO sabem se por trás há uma API oficial, automação de navegador
(Playwright) ou upload manual. Trocar a estratégia de UMA plataforma (ex.:
Playwright → API oficial quando o Matific liberar um feed) é implementar um novo
``Conector`` e registrá-lo — sem tocar em mais nada.

Regra de segurança: ``Credenciais`` nunca deve ser logada nem serializada para
o cliente. Os métodos recebem um ``Contexto`` com um ``log()`` que só aceita
mensagens operacionais (sem segredos).
"""
from __future__ import annotations

import abc
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Estrategia(str, Enum):
    """Como o conector obtém os dados — documentado por plataforma (requisito)."""

    API_OFICIAL = "api_oficial"      # preferível: estável e dentro dos ToS
    NAVEGADOR = "navegador"          # Playwright: só quando não há API adequada
    UPLOAD_MANUAL = "upload_manual"  # fallback: o humano envia o arquivo


@dataclass(slots=True)
class Credenciais:
    """Segredo DECIFRADO para uso efêmero em memória. Nunca persistir/logar."""

    usuario: str = ""
    senha: str = ""
    # Campos extras específicos da plataforma (ex.: url_escola, id_conta).
    extra: dict = field(default_factory=dict)

    def __repr__(self) -> str:  # blinda contra vazamento em traceback/log
        return f"Credenciais(usuario={'***' if self.usuario else ''}, senha=***)"


@dataclass(slots=True)
class ResultadoValidacao:
    """Retorno de ``testar_credenciais`` — mensagem CLARA de erro para o admin."""

    ok: bool
    mensagem: str
    # Código estável p/ o front decidir o alerta (ex.: "senha_invalida").
    codigo: str | None = None


@dataclass(slots=True)
class RelatorioDisponivel:
    """Um relatório que o conector localizou na plataforma (ainda não baixado)."""

    plataforma: str
    tipo: str                              # ex.: "leaderboard", "turma", "resumo"
    identificador: str                     # id/rota/seletor para baixar depois
    rotulo: str = ""                       # descrição amigável p/ o log/painel
    periodo_inicio: datetime | None = None
    periodo_fim: datetime | None = None
    metadados: dict = field(default_factory=dict)


@dataclass(slots=True)
class ArquivoObtido:
    """Arquivo baixado, pronto para o PIPELINE DE IMPORTAÇÃO EXISTENTE.

    ``conteudo`` são os bytes idênticos ao que um humano faria upload — assim o
    orquestrador reaproveita o mesmo parser/analisar/confirmar sem duplicar
    nada. ``formato_hint``/``periodo_*`` ajudam o orquestrador a mapear para os
    parâmetros do ``confirmar`` (ex.: Matific por período)."""

    conteudo: bytes
    nome_arquivo: str
    plataforma: str                        # matific | elefante
    content_type: str = "application/octet-stream"
    formato_hint: str | None = None        # "resumo" | "leituras" | None
    periodo_inicio: datetime | None = None
    periodo_fim: datetime | None = None
    metadados: dict = field(default_factory=dict)


# Assinatura do logger injetado: (etapa, nivel, mensagem) — sem segredos.
Registrar = Callable[[str, str, str], None]


@dataclass(slots=True)
class Contexto:
    """Contexto de UMA execução passado aos métodos do conector.

    ``log`` grava em ``SincronizacaoLog`` (etapa/nivel/mensagem). ``timeout_s`` e
    ``cancelado`` permitem o conector respeitar limites e cancelamento."""

    escola_id: int
    execucao_id: int | None
    log: Registrar
    timeout_s: int = 120
    cancelado: Callable[[], bool] = lambda: False


class ErroConector(Exception):
    """Falha de conector com um ``codigo`` estável para alertas/retry.

    ``recuperavel`` diz se o scheduler deve tentar de novo (backoff): timeout /
    indisponibilidade = sim; senha inválida / parser incompatível = não."""

    def __init__(self, mensagem: str, *, codigo: str, recuperavel: bool = False):
        super().__init__(mensagem)
        self.codigo = codigo
        self.recuperavel = recuperavel


class Conector(abc.ABC):
    """Interface que TODA plataforma implementa. Métodos I/O são assíncronos
    (login/download são espera de rede/navegador)."""

    #: identificador da plataforma (ex.: "matific"). Único no registro.
    plataforma: str = ""
    #: versão do conector — vai para o histórico (auditoria de qual código rodou).
    versao: str = "0.0.0"
    #: estratégia adotada — DOCUMENTA a escolha técnica (requisito).
    estrategia: Estrategia = Estrategia.UPLOAD_MANUAL
    #: por que esta estratégia (para o painel/documentação).
    justificativa: str = ""

    @abc.abstractmethod
    async def testar_credenciais(self, cred: Credenciais,
                                 contexto: Contexto) -> ResultadoValidacao:
        """Valida as credenciais IMEDIATAMENTE, com mensagem de erro clara."""

    @abc.abstractmethod
    async def localizar_relatorios(self, cred: Credenciais,
                                   contexto: Contexto) -> list[RelatorioDisponivel]:
        """Descobre quais relatórios estão disponíveis para baixar."""

    @abc.abstractmethod
    async def obter(self, cred: Credenciais, relatorio: RelatorioDisponivel,
                    contexto: Contexto) -> ArquivoObtido:
        """Baixa UM relatório e devolve os bytes prontos para o pipeline."""

    async def sincronizar(self, cred: Credenciais,
                          contexto: Contexto) -> list[ArquivoObtido]:
        """Fluxo padrão: localizar → obter cada um. Conectores podem sobrescrever
        (ex.: uma sessão de navegador reaproveitada entre downloads)."""
        arquivos: list[ArquivoObtido] = []
        for rel in await self.localizar_relatorios(cred, contexto):
            if contexto.cancelado():
                break
            arquivos.append(await self.obter(cred, rel, contexto))
        return arquivos
