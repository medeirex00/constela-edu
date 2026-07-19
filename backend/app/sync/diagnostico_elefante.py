"""Diagnóstico da Integração Elefante — auto-inventário da API interna.

Roda a investigação usando a SESSÃO AUTENTICADA do robô (sem crawler nem F12),
persiste o inventário (só estrutura/tipos, SEM PII) e o COMPARA com o anterior
para avisar quando a API do Elefante muda. É a ferramenta oficial de investigação
e manutenção da integração. Nada é exposto publicamente — o endpoint é
admin/coordenador e o resultado só aparece na tela de Diagnóstico.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.configuracao import Configuracao
from app.sync import connectors, vault
from app.sync.interfaces import Contexto, ErroConector

_NS = "elefante_inventario"
_CHAVE = "ultimo"
_TIMEOUT_S = 180


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
    Levanta ``ErroConector`` (o router traduz em HTTP)."""
    agora = agora or datetime.utcnow()
    cred = vault.obter_credencial(db, escola_id, "elefante")
    if cred is None:
        raise ErroConector(
            "As credenciais do Elefante não estão configuradas. Configure em "
            "Sincronização automática → Elefante.", codigo="sem_credencial",
            recuperavel=False)
    conector = connectors.obter("elefante")
    if conector is None or not hasattr(conector, "diagnosticar_endpoints"):
        raise ErroConector("Conector do Elefante indisponível.",
                           codigo="sem_conector", recuperavel=False)

    eventos: list[str] = []
    contexto = Contexto(escola_id=escola_id, execucao_id=None, timeout_s=_TIMEOUT_S,
                        log=lambda e, n, m: eventos.append(f"{n}: {m}"))  # noqa: ARG005

    async def _rodar():
        return await asyncio.wait_for(
            conector.diagnosticar_endpoints(cred, contexto), timeout=_TIMEOUT_S)

    try:
        inventario = asyncio.run(_rodar())
    except asyncio.TimeoutError as exc:
        raise ErroConector("O diagnóstico do Elefante demorou demais. Tente de novo.",
                           codigo="timeout", recuperavel=True) from exc

    inventario["gerado_em"] = agora.isoformat() + "Z"
    # Solta a conexão do banco (o robô rodou fora dela); relê para o diff/salvar.
    db.rollback()
    anterior = _carregar(db, escola_id)
    diff = _comparar(anterior, inventario)
    _salvar(db, escola_id, inventario)
    return {"inventario": inventario, "diff": diff,
            "anterior_em": (anterior or {}).get("gerado_em")}
