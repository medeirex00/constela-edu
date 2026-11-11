"""Diagnóstico da Integração Elefante — auto-inventário da API interna.

Roda a investigação usando a SESSÃO AUTENTICADA do robô (sem crawler nem F12),
persiste o inventário (só estrutura/tipos, SEM PII) e o COMPARA com o anterior
para avisar quando a API do Elefante muda. É a ferramenta oficial de investigação
e manutenção da integração. Nada é exposto publicamente — o endpoint é
admin/coordenador e o resultado só aparece na tela de Diagnóstico.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.configuracao import Configuracao
from app.sync import connectors, vault
from app.sync.connectors.navegador import (
    FALHA_CONHECIDA,
    FALHA_NOSSA,
    FALHA_TEMPO,
    classificar_falha_da_coleta,
    erro_conector_de_dentro,
)
from app.sync.interfaces import Contexto, ErroConector

logger = logging.getLogger("constela.sync")

_NS = "elefante_inventario"
_CHAVE = "ultimo"
_TIMEOUT_S = 180

_DEMOROU = "O diagnóstico do Elefante demorou demais. Tente de novo."
_FORA_DO_AR = ("Não foi possível rodar o diagnóstico agora: a conexão com o site do "
               "Elefante falhou ou ele não respondeu. Tente de novo em alguns minutos.")


def _erro_da_coleta(exc: BaseException) -> Exception | None:
    """O que levantar no lugar de uma falha no meio da coleta, pelo critério único
    de ``navegador.classificar_falha_da_coleta`` (o mesmo do placar ao vivo do
    Matific, ``aovivo._erro_da_consulta``):

    * REDE (DNS, conexão recusada, TLS, página que não abriu — o ``OSError`` da rede,
      a exceção do Playwright/httpx que não é nenhuma das abaixo) vira um
      ``ErroConector`` que diz que foi o Elefante (502), e o tempo esgotado, 504 —
      não um 500 "Erro interno" que põe a culpa no Constela. O detalhe fica no log
      WARNING; a resposta não leva nada interno;
    * o NOSSO navegador que caiu no meio da coleta (``TargetClosedError``, "Page
      crashed", o driver do Playwright morto) vira 503 ``navegador_indisponivel``,
      sem culpar o Elefante: o ``ErroConector`` vem de ``erro_conector_de_dentro``,
      que grava o log ERROR (a falha é do servidor). O que NÃO ABRIU já chega como
      esse ``ErroConector`` (``abrir_playwright``, também com log ERROR);
    * um ``ErroConector`` de dentro de um grupo de exceções passa com a mensagem dele;
    * DEFEITO NOSSO (KeyError, TypeError, AttributeError…) vai para o log ERROR (o
      Sentry o vê) e devolve None: quem chama relança a exceção crua (500). O
      ``asyncio.CancelledError`` de dentro do conector também é nosso, mas não pode
      subir cru (é BaseException: escaparia do tratamento de erro da rota) — volta um
      ``RuntimeError`` com ele como causa."""
    tipo = classificar_falha_da_coleta(exc)
    if tipo == FALHA_NOSSA:
        logger.exception("Diagnóstico do Elefante falhou na coleta por um defeito do "
                         "Constela (%s).", type(exc).__name__)
        if isinstance(exc, asyncio.CancelledError):
            return RuntimeError("A coleta do diagnóstico do Elefante foi cancelada por "
                                "dentro do conector, sem tempo esgotado.")
        return None
    if tipo == FALHA_CONHECIDA:
        return erro_conector_de_dentro(exc)
    demorou = tipo == FALHA_TEMPO
    logger.warning("Diagnóstico do Elefante falhou na coleta (%s): %s",
                   "tempo esgotado" if demorou else "rede",
                   type(exc).__name__, exc_info=True)
    if demorou:
        return ErroConector(_DEMOROU, codigo="timeout", recuperavel=True)
    return ErroConector(_FORA_DO_AR, codigo="indisponivel_externo", recuperavel=True)


def _linha(db: Session, escola_id: int) -> Configuracao | None:
    return db.execute(select(Configuracao).where(
        Configuracao.escola_id == escola_id,
        Configuracao.namespace == _NS,
        Configuracao.chave == _CHAVE)).scalar_one_or_none()


def _carregar(db: Session, escola_id: int) -> dict | None:
    row = _linha(db, escola_id)
    return dict(row.valor) if row and isinstance(row.valor, dict) else None


def _salvar(db: Session, escola_id: int, inventario: dict) -> None:
    row = _linha(db, escola_id)
    if row is None:
        db.add(Configuracao(escola_id=escola_id, namespace=_NS, chave=_CHAVE,
                            valor=inventario))
    else:
        row.valor = inventario
    db.commit()


def _comparar(anterior: dict | None, atual: dict) -> dict:
    """Diff endpoint a endpoint + períodos, gerando AVISOS de mudança da API."""
    at = {e["nome"]: e for e in atual.get("endpoints", []) if e.get("nome")}
    if not anterior:
        return {"primeira_vez": True, "novos_endpoints": sorted(at),
                "endpoints_sumidos": [], "estrutura_mudou": [], "avisos": [
                    "Primeiro inventário — nada a comparar ainda."]}
    ant = {e["nome"]: e for e in anterior.get("endpoints", []) if e.get("nome")}
    novos = sorted(n for n in at if n not in ant)
    sumidos = sorted(n for n in ant if n not in at)
    mudou = sorted(
        n for n in at if n in ant
        and at[n].get("estrutura") and ant[n].get("estrutura")
        and at[n]["estrutura"] != ant[n]["estrutura"])
    avisos: list[str] = []
    for n in novos:
        avisos.append(f"Novo endpoint detectado: {n}.")
    for n in sumidos:
        avisos.append(f"⚠️ Endpoint sumiu (a API pode ter mudado): {n}.")
    for n in mudou:
        avisos.append(f"⚠️ A estrutura de {n} mudou desde o último diagnóstico.")
    p_novos = sorted(set(atual.get("periodos_no_trafego", []))
                     - set(anterior.get("periodos_no_trafego", [])))
    for p in p_novos:
        avisos.append(f"Novo período visto no tráfego: {p}.")
    return {"primeira_vez": False, "novos_endpoints": novos,
            "endpoints_sumidos": sumidos, "estrutura_mudou": mudou, "avisos": avisos}


def executar(db: Session, escola_id: int, *, agora: datetime | None = None) -> dict:
    """Roda o diagnóstico ao vivo, persiste e devolve inventário + diff + avisos.
    Levanta ``ErroConector`` (o router traduz em HTTP): o do próprio conector passa
    com a mensagem dele; na COLETA, tempo esgotado vira ``timeout`` (504), falha de
    REDE (DNS, conexão, TLS, página que não abriu) vira ``indisponivel_externo``
    (502, log WARNING) e o NOSSO navegador que caiu ou não abriu vira
    ``navegador_indisponivel`` (503, log ERROR — o que caiu, por
    ``erro_conector_de_dentro``; o que não abriu, por ``abrir_playwright``).
    Defeito nosso — dentro da coleta (com log ERROR) ou fora dela — não é traduzido
    (segue 500)."""
    agora = agora or datetime.utcnow()
    cred = vault.obter_credencial(db, escola_id, "elefante")
    if cred is None:
        if vault.obter_linha(db, escola_id, "elefante") is not None:
            # A credencial existe, mas a cifra não abre (status 'ilegivel'):
            # "não configurada" seria mentira. Recadastro, sem detalhe da falha.
            raise ErroConector(vault.mensagem_credencial_ilegivel(["elefante"]),
                               codigo=vault.CODIGO_CREDENCIAL_ILEGIVEL, recuperavel=False)
        raise ErroConector(
            "As credenciais do Elefante não estão configuradas. Configure em "
            "Integrações → Elefante → “Configurar conexão”.", codigo="sem_credencial",
            recuperavel=False)
    conector = connectors.obter("elefante")
    if conector is None or not hasattr(conector, "diagnosticar_endpoints"):
        raise ErroConector("Conector do Elefante indisponível.",
                           codigo="sem_conector", recuperavel=False)

    eventos: list[str] = []
    contexto = Contexto(escola_id=escola_id, execucao_id=None, timeout_s=_TIMEOUT_S,
                        log=lambda e, n, m: eventos.append(f"{n}: {m}"))  # noqa: ARG005

    async def _coletar():
        # Só a COLETA (login + sondagem no site do Elefante) é protegida: o que vem
        # depois (diff, gravação) segue sendo erro nosso, e não do Elefante.
        try:
            return await asyncio.wait_for(
                conector.diagnosticar_endpoints(cred, contexto), timeout=_TIMEOUT_S)
        except ErroConector:
            raise           # já diz o que houve (CAPTCHA, senha, navegador ausente…)
        except asyncio.CancelledError as exc:
            tarefa = asyncio.current_task()
            if tarefa is not None and tarefa.cancelling():
                raise       # cancelada de FORA (o próprio teto já virou TimeoutError)
            raise _erro_da_coleta(exc) from exc     # de dentro do conector: nosso
        except Exception as exc:  # noqa: BLE001 — classificada em _erro_da_coleta
            erro = _erro_da_coleta(exc)
            if erro is None:
                raise       # defeito nosso: sobe cru (500), já no log ERROR
            raise erro from exc

    # Solta a conexão do banco ANTES do robô (login + sondagem, até ``_TIMEOUT_S``):
    # a leitura da credencial (e a autenticação da requisição) abriu a transação, e
    # ela ficaria "idle in transaction" segurando uma conexão do pool durante toda a
    # I/O externa — a regra do módulo (coleta, placar ao vivo, "Testar conexão").
    # Só leituras até aqui; a credencial já está decifrada em memória. O diff e a
    # gravação abaixo reabrem a conexão sob demanda.
    db.rollback()
    inventario = asyncio.run(_coletar())

    inventario["gerado_em"] = agora.isoformat() + "Z"
    anterior = _carregar(db, escola_id)
    diff = _comparar(anterior, inventario)
    _salvar(db, escola_id, inventario)
    return {"inventario": inventario, "diff": diff,
            "anterior_em": (anterior or {}).get("gerado_em")}
