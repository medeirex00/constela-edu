"""Diagnóstico do armazenamento em disco: as pastas da API sobrevivem a um deploy?

O que a API grava (inventário em docs/operacao/ARMAZENAMENTO.md):
  * ``UPLOADS_DIR/temporarios`` — original do relatório entre "analisar" e
    "confirmar" (expira em horas; perder num deploy só tira o arquivamento);
  * ``UPLOADS_DIR/<plataforma>/`` — arquivo do original confirmado (só escrito,
    nunca relido pela API; ``importacoes.arquivo_original`` guarda o caminho);
  * ``EXPORTS_DIR`` — cópia dos relatórios exportados (retenção de
    EXPORTS_RETENCAO_DIAS; o download nunca depende dela).
Tudo é "melhor esforço": sem disco gravável a importação e o download seguem.

No Railway, sem volume, o disco é do contêiner e é DESCARTADO a cada deploy. Quando
há volume, o Railway injeta ``RAILWAY_VOLUME_MOUNT_PATH``; uma pasta é persistente
se estiver dentro dele. Fora do Railway (docker-compose com volumes nomeados) não dá
para saber pelo ambiente: o diagnóstico responde ``None`` (desconhecido).
"""
from __future__ import annotations

import os
from pathlib import Path

# Variáveis que o Railway injeta em todo serviço (sinal de "estou no Railway").
_SINAIS_RAILWAY = ("RAILWAY_ENVIRONMENT_NAME", "RAILWAY_ENVIRONMENT_ID",
                   "RAILWAY_ENVIRONMENT", "RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID")


def _no_railway() -> bool:
    return any(os.environ.get(nome) for nome in _SINAIS_RAILWAY)


def _gravavel(pasta: Path) -> bool:
    """A pasta aceita escrita (ou pode ser criada) pelo usuário do processo?
    Sem escrever nada: só permissões (o volume do Railway nasce do root)."""
    alvo = pasta
    while not alvo.exists():
        if alvo.parent == alvo:
            return False
        alvo = alvo.parent
    return alvo.is_dir() and os.access(alvo, os.W_OK | os.X_OK)


def _dentro(pasta: Path, raiz: Path) -> bool:
    try:
        return pasta.resolve().is_relative_to(raiz.resolve())
    except OSError:
        return False


def diagnostico(settings) -> dict:
    volume_txt = (settings.RAILWAY_VOLUME_MOUNT_PATH or "").strip()
    volume = Path(volume_txt) if volume_txt else None
    pastas = {"uploads": Path(settings.UPLOADS_DIR), "exports": Path(settings.EXPORTS_DIR)}
    detalhe = {}
    for nome, pasta in pastas.items():
        detalhe[nome] = {
            "caminho": str(pasta),
            "existe": pasta.is_dir(),
            "gravavel": _gravavel(pasta),
            "no_volume": bool(volume) and _dentro(pasta, volume),
        }
    if volume is not None:
        persistente: bool | None = all(p["no_volume"] for p in detalhe.values())
    elif _no_railway():
        persistente = False
    else:
        persistente = None

    avisos = []
    if persistente is False:
        avisos.append("Sem volume (ou fora dele): os arquivos somem a cada deploy. "
                      "Anexe um volume em /dados (docs/operacao/ARMAZENAMENTO.md).")
    if any(not p["gravavel"] for p in detalhe.values()):
        avisos.append("Pasta sem permissão de escrita: os originais/cópias não são "
                      "guardados (a API segue). Volume do Railway nasce do root — ver "
                      "RAILWAY_RUN_UID em docs/operacao/ARMAZENAMENTO.md.")
    return {
        "base": str(settings.DADOS_DIR) if settings.DADOS_DIR else None,
        "volume": volume_txt or None,
        "no_railway": _no_railway(),
        "persistente": persistente,
        "pastas": detalhe,
        "avisos": avisos,
    }
