"""Geocodificação de escolas (latitude/longitude) via Nominatim (OpenStreetMap).

Sem serviço pago e sem chave de API. Um script one-off
(`scripts/geocodificar_escolas.py`) chama isto em lote, respeitando o
rate-limit do Nominatim (~1 req/s) e uma User-Agent identificável (política de
uso do OSM). O geocodificador é **INJETÁVEL** para os testes automatizados NÃO
fazerem chamada externa — passe um `geocoder` falso nos testes.
"""
from __future__ import annotations

from typing import Callable, Optional

import httpx

from app.models import Escola

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# A política de uso do OSM exige uma User-Agent identificável com contato.
USER_AGENT = "ConstelaEdu/1.0 (geocodificacao de escolas; contato: suporte@constelaedu.com)"

# Um geocodificador recebe uma consulta textual e devolve (lat, lng) ou None.
Geocoder = Callable[[str], Optional[tuple[float, float]]]


def montar_consulta(escola: Escola) -> str:
    """Monta o endereço textual a partir do que a escola tiver preenchido.
    Ordem do mais específico ao mais geral; ignora campos vazios."""
    partes = [escola.nome, escola.endereco, escola.bairro, escola.cidade, escola.estado, "Brasil"]
    return ", ".join(p.strip() for p in partes if p and str(p).strip())


def _nominatim(consulta: str, *, timeout: float = 10.0) -> Optional[tuple[float, float]]:
    """Geocodificador real (Nominatim/OSM). Nunca levanta: erro de rede/HTTP/
    parsing vira None (o chamador em lote registra e segue)."""
    try:
        resposta = httpx.get(
            NOMINATIM_URL,
            params={"q": consulta, "format": "json", "limit": 1, "countrycodes": "br"},
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
        )
        resposta.raise_for_status()
        dados = resposta.json()
        if not dados:
            return None
        return float(dados[0]["lat"]), float(dados[0]["lon"])
    except Exception:
        return None


def geocodificar_escola(escola: Escola, geocoder: Geocoder = _nominatim) -> Optional[tuple[float, float]]:
    """(lat, lng) da escola, ou None se sem endereço suficiente / não encontrada.
    `geocoder` é injetável (testes passam um falso — sem rede)."""
    consulta = montar_consulta(escola)
    # Só "Nome, Brasil" quase nunca localiza um prédio — exige ao menos cidade.
    if not escola.cidade or not consulta:
        return None
    return geocoder(consulta)
