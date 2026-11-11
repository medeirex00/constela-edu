"""Cofre de credenciais das plataformas — cifrado em repouso (Fernet).

Reaproveita ``cifrar_segredo``/``decifrar_segredo`` (o mesmo anel de chaves da chave
de IA e da sessão do Matific, ``app.core.security.segredos_da_cifra``). Cifra com a
``DATA_ENCRYPTION_KEY``, dedicada, diferente da ``SECRET_KEY`` e obrigatória com
``ENV=producao`` (sem ela, só em dev, cai na chave legada, com aviso no boot). A DEK
fica FORA do banco: quem obtém só o dump do Postgres não lê as senhas. A
``SECRET_KEY``, que assina os JWT, só DECIFRA as cifras legadas, gravadas antes da
DEK. Trocar a chave fora do chaveiro (``DATA_ENCRYPTION_KEYS_ANTERIORES`` e
``python -m scripts.recifrar_segredos --executar``; docs/CONTINUIDADE.md §2 e
docs/operacao/PRODUCAO-ENV-E-MIGRACOES.md) deixa a credencial ``ilegivel``, e só o
recadastro resolve. O texto claro só existe em memória, efêmero, durante uma
execução. Nada aqui é logado nem devolvido ao navegador.

Isolamento multi-tenant: toda função exige ``escola_id`` e a unicidade é
``(escola_id, plataforma)`` — uma escola nunca alcança a credencial de outra.
"""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import cifrar_segredo, decifrar_segredo
from app.models.base import agora
from app.models.sincronizacao import PlataformaCredencial
from app.sync.interfaces import Credenciais


# Status DERIVADO (nunca gravado): a linha existe, mas a cifra não abre com as
# chaves deste processo (DATA_ENCRYPTION_KEY/SECRET_KEY trocadas sem recifrar, ou
# valor corrompido). O que estava gravado em ``status`` ('valida', inclusive) não
# vale mais nada — a integração só volta com o recadastro da senha.
STATUS_ILEGIVEL = "ilegivel"

# Código e textos de quem pede uma AÇÃO com a credencial ilegível (testar,
# sincronizar agora, diagnóstico). "Não configurada" seria mentira: a credencial
# existe e só precisa ser recadastrada. Nenhum detalhe interno da falha da cifra.
CODIGO_CREDENCIAL_ILEGIVEL = "credencial_ilegivel"
_NOME_PLATAFORMA = {"elefante": "Elefante", "matific": "Matific"}


def mensagem_credencial_ilegivel(plataformas) -> str:
    """"A senha salva do Elefante (e do Matific) não pode mais ser lida…" — para a
    ação que não pôde rodar porque a cifra não abre (``status_efetivo`` =
    ``ilegivel``)."""
    nomes = " e do ".join(_NOME_PLATAFORMA.get(p, str(p)) for p in plataformas)
    return (f"A senha salva do {nomes} não pode mais ser lida pelo servidor e precisa "
            "ser recadastrada: informe usuário e senha de novo em Sincronização "
            "automática e clique em “Salvar e validar”.")


def _para_credenciais(payload: dict) -> Credenciais:
    return Credenciais(
        usuario=str(payload.get("usuario", "")),
        senha=str(payload.get("senha", "")),
        extra=payload.get("extra", {}) or {},
    )


def _ler(linha: PlataformaCredencial) -> Credenciais | None:
    """Decifra a linha; None se a cifra não abrir ou o conteúdo não tiver o formato
    gravado por ``salvar_credencial`` (nunca levanta)."""
    texto = decifrar_segredo(linha.segredo_cifrado)
    if texto is None:                     # chave trocada / valor corrompido
        return None
    try:
        payload = json.loads(texto)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    return _para_credenciais(payload)


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
        linha.token_version += 1          # conta o recadastro (nada o lê hoje)
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
    return _ler(linha)


def credencial_da_linha(linha: PlataformaCredencial) -> Credenciais | None:
    """Decifra a linha já lida (uso efêmero), ou None se a cifra não abrir."""
    return _ler(linha)


def carimbo_da_credencial(linha: PlataformaCredencial) -> str:
    """Identifica ESTA credencial gravada: muda quando ela é salva de novo (outra
    conta ou a mesma), removida e recriada, ou recifrada — a cifra é nova a cada
    gravação. Não muda com o resultado da validação (``marcar_status``). Serve para
    amarrar o que foi obtido com uma credencial (o ranking ao vivo em cache, a sessão
    do Matific) a ela, em qualquer processo. É um resumo da cifra: não revela nada."""
    base = f"{linha.id}|{linha.token_version}|{linha.segredo_cifrado}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:32]


def credencial_legivel(linha: PlataformaCredencial) -> bool:
    """A cifra da linha abre com as chaves deste processo? Só o "abre ou não": o
    texto claro é descartado aqui e nunca sai desta função."""
    return _ler(linha) is not None


def status_efetivo(linha: PlataformaCredencial | None) -> str:
    """O status que a tela deve mostrar: ``nao_configurada`` sem linha,
    ``ilegivel`` quando a cifra não abre (qualquer que seja o gravado), senão o
    gravado. Lê a cifra; não grava nada."""
    if linha is None:
        return "nao_configurada"
    if not credencial_legivel(linha):
        return STATUS_ILEGIVEL
    return linha.status


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
