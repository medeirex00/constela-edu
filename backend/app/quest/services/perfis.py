"""Perfil do astronauta: apelido seguro, código de amigo, avatar.

Apelidos vêm de listas fechadas (LGPD: fora da própria turma a criança
aparece como apelido + avatar, nunca nome completo). Não existe campo de
texto livre acessível ao papel aluno — nem aqui.
"""
from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Aluno
from app.quest.models import QuestPerfil

# Cores de traje do protótipo constela-play-v7 (COLORS) — a validação parte
# de lista fechada: o cliente nunca envia hex livre.
CORES_TRAJE = ("#FF4D9D", "#FFC93C", "#2EE6A8", "#4EA8FF", "#A78BFA", "#FF8E3C")
COR_PADRAO = CORES_TRAJE[0]

# Vestiário (estilo Roblox): slots cosméticos. O desenho de cada item vive no
# frontend (SVG do Cosmo); aqui fica a whitelist — o cliente nunca inventa
# item. Na fase Q0 tudo é gratuito; o desbloqueio por XP entra na Q2.
# Avatar HUMANOIDE (estilo Roblox/Stumble Guys): customização profunda.
PELES = ("#F6C8A0", "#E8B07E", "#C98A56", "#9C6B3F", "#8D5524", "#6E4A2C",
         "#4A3020")
CABELOS = ("espetado", "longo", "afro", "coques", "afro_puff", "liso",
           "moicano", "careca")
COR_CABELO = ("#2B2B2B", "#6B3F1D", "#C9302C", "#F4C430", "#3D7BFF",
              "#E24AA0", "#7A3DF0")
# Blusa: estilo (top) + cor (camiseta)
TOPS = ("camiseta", "moletom", "jaqueta", "jardineira")
CAMISETAS = ("#FF5470", "#FFC93C", "#2EE6A8", "#4EA8FF", "#A78BFA", "#7A3DF0",
             "#FF8E3C", "#231D4E")
# Parte de baixo: estilo (baixo) + cor (calca)
BAIXOS = ("calca", "shorts")
CALCAS = ("#3A2E66", "#4EA8FF", "#2EC77A", "#E8384F", "#5A5480", "#FFC93C",
          "#231D4E", "#F2EFFF")
TENIS = ("#FF5470", "#4EA8FF", "#2EE6A8", "#FFC93C", "#F2EFFF", "#231D4E")
# Acessórios de cabeça/rosto
CHAPEUS = ("nenhum", "oculos", "bone", "coroa", "fone", "catfone", "capacete")
# Itens de costas
COSTAS = ("nenhum", "mochila", "asas", "jetpack")
# Efeitos (aura/halo/rastro em volta do personagem)
AURAS = ("nenhum", "estelar", "halo", "rastro")
MAO = ("nenhum", "varinha")
PETS = ("nenhum", "gatinho", "dino", "estrelinha", "robo")
VEICULOS = ("nenhum", "skate", "patins")

APARENCIA = {
    "pele": PELES,
    "cabelo": CABELOS,
    "cor_cabelo": COR_CABELO,
    "top": TOPS,
    "camiseta": CAMISETAS,
    "baixo": BAIXOS,
    "calca": CALCAS,
    "tenis": TENIS,
    "chapeu": CHAPEUS,
    "costas": COSTAS,
    "aura": AURAS,
    "mao": MAO,
    "pet": PETS,
    "veiculo": VEICULOS,
    "cor": CORES_TRAJE,  # legado (Cosmo)
}
AVATAR_PADRAO = {
    "pele": PELES[0], "cabelo": "espetado", "cor_cabelo": "#6B3F1D",
    "top": "camiseta", "camiseta": "#4EA8FF", "baixo": "calca", "calca": "#3A2E66",
    "tenis": "#FF5470", "chapeu": "nenhum", "costas": "nenhum", "aura": "nenhum",
    "mao": "nenhum", "pet": "nenhum", "veiculo": "nenhum",
}

# Os 6 personagens-base (gratuitos) — ponto de partida; tudo personalizável.
PERSONAGENS_BASE = {
    "aventureiro": {"nome": "Aventureiro Estelar", "pele": "#E8B07E",
                    "cabelo": "espetado", "cor_cabelo": "#3D7BFF", "top": "camiseta",
                    "camiseta": "#231D4E", "baixo": "shorts", "calca": "#3A2E66",
                    "tenis": "#4EA8FF"},
    "exploradora": {"nome": "Exploradora Galáctica", "pele": "#F6C8A0",
                    "cabelo": "longo", "cor_cabelo": "#7A3DF0", "top": "moletom",
                    "camiseta": "#7A3DF0", "baixo": "calca", "calca": "#3A2E66",
                    "tenis": "#F2EFFF", "chapeu": "catfone"},
    "piloto": {"nome": "Piloto Cósmico", "pele": "#8D5524",
               "cabelo": "afro", "cor_cabelo": "#2B2B2B", "top": "jaqueta",
               "camiseta": "#2EE6A8", "baixo": "shorts", "calca": "#231D4E",
               "tenis": "#2EE6A8"},
    "sonhadora": {"nome": "Sonhadora Estelar", "pele": "#F6C8A0",
                  "cabelo": "coques", "cor_cabelo": "#E24AA0", "top": "jaqueta",
                  "camiseta": "#FF5470", "baixo": "calca", "calca": "#4EA8FF",
                  "tenis": "#FF5470"},
    "descobridor": {"nome": "Descobridor de Mundos", "pele": "#C98A56",
                    "cabelo": "liso", "cor_cabelo": "#6B3F1D", "top": "jaqueta",
                    "camiseta": "#4EA8FF", "baixo": "calca", "calca": "#3A2E66",
                    "tenis": "#F2EFFF", "chapeu": "bone"},
    "guardia": {"nome": "Guardiã das Constelações", "pele": "#6E4A2C",
                "cabelo": "afro_puff", "cor_cabelo": "#2B2B2B", "top": "jardineira",
                "camiseta": "#FFC93C", "baixo": "shorts", "calca": "#FFC93C",
                "tenis": "#FFC93C", "chapeu": "oculos"},
}

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


def _inserir_perfil_novo(db: Session, aluno: Aluno) -> QuestPerfil:
    """Cria o perfil com RETRY em colisão (TOCTOU) — mesmo padrão de
    _inserir_credencial_nova. Sob concorrência, dois pedidos podem inserir o
    MESMO aluno_id (unique) ou sortear o MESMO codigo_amigo (unique); o savepoint
    isola a falha do INSERT sem abortar a transação. Colisão de aluno_id →
    devolve o perfil já criado pela outra transação; colisão só de codigo_amigo →
    a próxima volta sorteia outro código."""
    for _ in range(5):
        try:
            with db.begin_nested():
                perfil = QuestPerfil(
                    escola_id=aluno.escola_id,
                    aluno_id=aluno.id,
                    apelido=gerar_apelido(db, aluno.escola_id),
                    codigo_amigo=gerar_codigo_amigo(db),
                    avatar=dict(AVATAR_PADRAO),
                    preferencias={"som": True, "musica": True, "narracao": True,
                                  "reduzir_animacoes": False},
                )
                db.add(perfil)
                db.flush()
            return perfil
        except IntegrityError:
            existente = db.execute(
                select(QuestPerfil).where(QuestPerfil.aluno_id == aluno.id)
            ).scalar_one_or_none()
            if existente is not None:
                return existente        # corrida em aluno_id: usa o existente
            # colisão só de codigo_amigo: a próxima volta sorteia outro
    raise RuntimeError("Não foi possível criar o perfil único do aluno.")


def obter_ou_criar_perfil(db: Session, aluno: Aluno) -> QuestPerfil:
    perfil = db.execute(
        select(QuestPerfil).where(QuestPerfil.aluno_id == aluno.id)
    ).scalar_one_or_none()
    if perfil is not None:
        return perfil
    return _inserir_perfil_novo(db, aluno)


# Chaves de preferências que o aluno pode alterar (whitelist estrita).
PREFERENCIAS_PERMITIDAS = {"som", "musica", "narracao", "reduzir_animacoes"}


def validar_nome_exibicao(nome: str) -> str:
    """Nome que a criança escolheu na cerimônia ("como você quer ser
    chamado?"). Único texto livre do papel aluno: curto, só letras e
    espaços, sem dígitos/símbolos/emojis — e Título Bonito na saída."""
    limpo = " ".join((nome or "").split())
    if not (2 <= len(limpo) <= 20):
        raise ValueError("O nome precisa ter entre 2 e 20 letras.")
    if not all(c.isalpha() or c == " " for c in limpo):
        raise ValueError("Use só letras, sem números ou símbolos.")
    return limpo.title()


def primeiro_nome_cadastro(nome_civil: str) -> str:
    return (nome_civil or "").strip().split(" ")[0].title()


def nome_para_falas(perfil: QuestPerfil, aluno_nome: str) -> str:
    """Nome usado em toda a interface: o escolhido pela criança, ou o
    primeiro nome do cadastro enquanto ela não escolher."""
    return (perfil.nome_exibicao or "").strip() or primeiro_nome_cadastro(aluno_nome)


def atualizar_avatar(perfil: QuestPerfil, mudancas: dict) -> None:
    """Aplica apenas os slots presentes no catálogo APARENCIA, com valores da
    whitelist de cada slot: um slot fora de APARENCIA é ignorado; um valor fora
    da lista do slot é rejeitado (ValueError). O cliente nunca deveria enviá-los.
    A whitelist é a fonte da verdade — não há lista fixa de 4 slots."""
    avatar = dict(perfil.avatar or {})
    for slot, permitidos in APARENCIA.items():
        if slot in mudancas:
            escolha = str(mudancas[slot])
            if escolha not in permitidos:
                raise ValueError(f"Opção desconhecida para {slot}.")
            avatar[slot] = escolha
    perfil.avatar = avatar


def atualizar_preferencias(perfil: QuestPerfil, mudancas: dict) -> None:
    prefs = dict(perfil.preferencias or {})
    for chave, valor in mudancas.items():
        if chave in PREFERENCIAS_PERMITIDAS:
            prefs[chave] = bool(valor)
    perfil.preferencias = prefs
