"""Cofre de credenciais das plataformas — cifrado em repouso (Fernet).

Reaproveita ``cifrar_segredo``/``decifrar_segredo`` (mesma cifra da chave de IA):
a chave deriva da ``SECRET_KEY``, que fica FORA do banco — quem obtém só o dump
do Postgres não lê as senhas. O texto claro só existe em memória, efêmero,
durante uma execução. Nada aqui é logado nem devolvido ao navegador.

Isolamento multi-tenant: toda função exige ``escola_id`` e a unicidade é
``(escola_id, plataforma)`` — uma escola nunca alcança a credencial de outra.
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import cifrar_segredo, decifrar_segredo
from app.models.base import agora
from app.models.sincronizacao import PlataformaCredencial
from app.sync.interfaces import Credenciais


def _para_credenciais(payload: dict) -> Credenciais:
    return Credenciais(
        usuario=str(payload.get("usuario", "")),
        senha=str(payload.get("senha", "")),
        extra=payload.get("extra", {}) or {},
    )


def salvar_credencial(db: Session, escola_id: int, plataforma: str,
                      credenciais: Credenciais) -> PlataformaCredencial:
    """Cifra e grava (upsert) a credencial da plataforma para a escola.

    Guardar SEMPRE reseta o status para ``nao_validada`` — quem salva precisa
    revalidar (o router chama ``testar_credenciais`` em seguida)."""
    segredo = json.dumps({
        "usuario": credenciais.usuario,
        "senha": credenciais.senha,
        "extra": credenciais.extra,
    }, ensure_ascii=False)
    cifrado = cifrar_segredo(segredo)

    linha = db.execute(
        select(PlataformaCredencial).where(
            PlataformaCredencial.escola_id == escola_id,
            PlataformaCredencial.plataforma == plataforma,
        )
    ).scalar_one_or_none()

    if linha is None:
        linha = PlataformaCredencial(escola_id=escola_id, plataforma=plataforma,
                                     segredo_cifrado=cifrado)
        db.add(linha)
    else:
        linha.segredo_cifrado = cifrado
        linha.token_version += 1          # rotação: invalida sessão antiga
    linha.status = "nao_validada"
    linha.validada_em = None
    linha.ultimo_erro = None
    db.flush()
    return linha


def obter_credencial(db: Session, escola_id: int,
                     plataforma: str) -> Credenciais | None:
    """Decifra a credencial para uso efêmero, ou None se não houver/decifra falhar."""
    linha = db.execute(
        select(PlataformaCredencial).where(
            PlataformaCredencial.escola_id == escola_id,
            PlataformaCredencial.plataforma == plataforma,
        )
    ).scalar_one_or_none()
    if linha is None:
        return None
    texto = decifrar_segredo(linha.segredo_cifrado)
    if texto is None:                     # SECRET_KEY trocada / valor corrompido
        return None
    try:
        return _para_credenciais(json.loads(texto))
    except (ValueError, TypeError):
        return None


def obter_linha(db: Session, escola_id: int,
                plataforma: str) -> PlataformaCredencial | None:
    return db.execute(
        select(PlataformaCredencial).where(
            PlataformaCredencial.escola_id == escola_id,
            PlataformaCredencial.plataforma == plataforma,
        )
    ).scalar_one_or_none()


def marcar_status(db: Session, linha: PlataformaCredencial, status: str,
                  erro: str | None = None) -> None:
    """Registra o resultado da validação (valida/invalida/expirada)."""
    linha.status = status
    linha.ultimo_erro = (erro or "")[:300] or None
    if status == "valida":
        linha.validada_em = agora()
    db.flush()


def remover_credencial(db: Session, escola_id: int, plataforma: str) -> bool:
    linha = obter_linha(db, escola_id, plataforma)
    if linha is None:
        return False
    db.delete(linha)
    db.flush()
    return True
