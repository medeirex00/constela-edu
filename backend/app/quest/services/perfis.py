"""Perfil do astronauta: apelido seguro, código de amigo, avatar.

Apelidos vêm de listas fechadas (LGPD: fora da própria turma a criança
aparece como apelido + avatar, nunca nome completo). Não existe campo de
texto livre acessível ao papel aluno — nem aqui.
"""
from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Aluno
from app.quest.models import QuestPerfil

# Cores de traje do protótipo constela-play-v7 (COLORS) — a validação parte
# de lista fechada: o cliente nunca envia hex livre.
CORES_TRAJE = ("#FF4D9D", "#FFC93C", "#2EE6A8", "#4EA8FF", "#A78BFA", "#FF8E3C")
COR_PADRAO = CORES_TRAJE[0]

# Apelido = "SUBSTANTIVO ADJETIVO" de listas seguras e positivas.
_SUBSTANTIVOS = (
    "Estrela", "Cometa", "Foguete", "Planeta", "Aurora", "Satelite",
    "Meteoro", "Galaxia", "Estrela-Guia", "Luar", "Sol", "Nebulosa",
    "Astronauta", "Explorador", "Piloto", "Guardiao",
)
_ADJETIVOS = (
    "Corajoso", "Veloz", "Brilhante", "Curioso", "Gigante", "Dourado",
    "Saltitante", "Radiante", "Valente", "Esperto", "Alegre", "Tranquilo",
    "Sonhador", "Reluzente", "Fascinante", "Incrivel",
)


def _flexionar(substantivo: str, adjetivo: str) -> str:
    """Concordância simples: substantivos femininos pedem adjetivo em -a."""
    femininos = {"Estrela", "Aurora", "Galaxia", "Estrela-Guia", "Nebulosa"}
    if substantivo in femininos and adjetivo.endswith("o"):
        adjetivo = adjetivo[:-1] + "a"
    return f"{substantivo} {adjetivo}"


def gerar_apelido(db: Session, escola_id: int) -> str:
    """Apelido único dentro da escola (evita duas 'Estrela Valente' na rede
    local da criança); com sufixo numérico se as combinações esgotarem."""
    for _ in range(60):
        apelido = _flexionar(secrets.choice(_SUBSTANTIVOS),
                             secrets.choice(_ADJETIVOS))
        existe = db.execute(
            select(QuestPerfil.id)
            .where(QuestPerfil.escola_id == escola_id,
                   QuestPerfil.apelido == apelido)
        ).first()
        if existe is None:
            return apelido
    return _flexionar(secrets.choice(_SUBSTANTIVOS),
                      secrets.choice(_ADJETIVOS)) + f" {secrets.randbelow(90) + 10}"


def gerar_codigo_amigo(db: Session) -> str:
    """COSMO-XXXX (sem 0/O/1/I — criança não confunde ao ditar)."""
    alfabeto = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    for _ in range(200):
        sufixo = "".join(secrets.choice(alfabeto) for _ in range(4))
        codigo = f"COSMO-{sufixo}"
        existe = db.execute(
            select(QuestPerfil.id).where(QuestPerfil.codigo_amigo == codigo)
        ).first()
        if existe is None:
            return codigo
    raise RuntimeError("Não foi possível gerar um código de amigo único.")


def obter_ou_criar_perfil(db: Session, aluno: Aluno) -> QuestPerfil:
    perfil = db.execute(
        select(QuestPerfil).where(QuestPerfil.aluno_id == aluno.id)
    ).scalar_one_or_none()
    if perfil is not None:
        return perfil
    perfil = QuestPerfil(
        escola_id=aluno.escola_id,
        aluno_id=aluno.id,
        apelido=gerar_apelido(db, aluno.escola_id),
        codigo_amigo=gerar_codigo_amigo(db),
        avatar={"cor": COR_PADRAO},
        preferencias={"som": True, "musica": True, "narracao": True,
                      "reduzir_animacoes": False},
    )
    db.add(perfil)
    db.flush()
    return perfil


# Chaves de preferências que o aluno pode alterar (whitelist estrita).
PREFERENCIAS_PERMITIDAS = {"som", "musica", "narracao", "reduzir_animacoes"}


def atualizar_avatar(perfil: QuestPerfil, mudancas: dict) -> None:
    """Só aceita slots conhecidos com valores do catálogo. Na fase Q0 o
    único slot equipável é a cor do traje."""
    avatar = dict(perfil.avatar or {})
    if "cor" in mudancas:
        cor = str(mudancas["cor"])
        if cor not in CORES_TRAJE:
            raise ValueError("Cor de traje desconhecida.")
        avatar["cor"] = cor
    perfil.avatar = avatar


def atualizar_preferencias(perfil: QuestPerfil, mudancas: dict) -> None:
    prefs = dict(perfil.preferencias or {})
    for chave, valor in mudancas.items():
        if chave in PREFERENCIAS_PERMITIDAS:
            prefs[chave] = bool(valor)
    perfil.preferencias = prefs
