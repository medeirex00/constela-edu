"""Conector de FALLBACK — upload manual (o pipeline que já existe).

Existe para que o fallback seja de PRIMEIRA CLASSE na mesma arquitetura: o
painel lista "Manual" como uma opção, e nada no orquestrador precisa de um caso
especial. Ele não obtém nada automaticamente — a obtenção é o humano subindo o
arquivo pela tela ``/importacoes`` já existente.
"""
from __future__ import annotations

from app.sync.interfaces import (
    Conector,
    Contexto,
    Credenciais,
    ErroConector,
    Estrategia,
    RelatorioDisponivel,
    ResultadoValidacao,
)


class ConectorManual(Conector):
    plataforma = "manual"
    versao = "1.0.0"
    estrategia = Estrategia.UPLOAD_MANUAL
    justificativa = (
        "Fallback sempre disponível: o professor/coordenador envia o PDF/XLSX "
        "pela tela de importação. Não depende das plataformas externas nem de "
        "guardar senhas — é o caminho robusto que já existe.")

    async def testar_credenciais(self, cred: Credenciais,
                                 contexto: Contexto) -> ResultadoValidacao:
        return ResultadoValidacao(
            ok=True, mensagem="O modo manual não usa credenciais.",
            codigo="manual")

    async def localizar_relatorios(self, cred: Credenciais,
                                   contexto: Contexto) -> list[RelatorioDisponivel]:
        return []

    async def obter(self, cred, relatorio, contexto):
        raise ErroConector(
            "O modo manual não baixa relatórios — o arquivo é enviado pela tela "
            "de importação.", codigo="manual", recuperavel=False)
