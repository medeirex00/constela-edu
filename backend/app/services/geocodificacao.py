"""Geocodificação de escolas (latitude/longitude) via Nominatim (OpenStreetMap).

Sem serviço pago e sem chave de API — o mesmo OSM do mapa da Secretaria. Enche o
mapa a partir do endereço que a escola já tem (hoje: nome + cidade + UF), sem o
gestor digitar coordenada por coordenada; o ajuste manual (PATCH /redes/escolas/
{id}) segue como conserto dos poucos que não forem localizados.

Cuidados desta superfície (chamada HTTP EXTERNA):
  * URL FIXA do Nominatim (nunca montada a partir de dado do usuário) — sem SSRF;
  * User-Agent identificável e ``countrycodes=br`` (política de uso do OSM);
  * rate-limit respeitado por quem chama em lote (>= 1 req/s);
  * NUNCA levanta: erro de rede/HTTP/parsing vira ``None`` (o chamador registra e
    segue) — geocodificar é acessório, jamais derruba a operação;
  * o geocodificador é INJETÁVEL para os testes NÃO fazerem chamada externa.
"""
from __future__ import annotations

import time
from typing import Callable, Optional

import httpx

from app.models import Escola

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# A política de uso do OSM exige uma User-Agent identificável com contato.
USER_AGENT = "ConstelaEdu/1.0 (geocodificacao de escolas; contato: suporte@constelaedu.com)"
# Intervalo mínimo entre chamadas ao OSM (política: ~1 req/s). Nunca abaixo de 1s.
INTERVALO_PADRAO = 1.1

# Um geocodificador recebe uma consulta textual e devolve (lat, lng) ou None.
Geocoder = Callable[[str], Optional[tuple[float, float]]]


def montar_consulta(escola: Escola) -> str:
    """Endereço textual a partir do que a escola tiver preenchido (nome, cidade,
    UF). Ordem do mais específico ao mais geral; ignora campos vazios."""
    partes = [escola.nome, escola.cidade, escola.estado, "Brasil"]
    return ", ".join(p.strip() for p in partes if p and str(p).strip())


def _nominatim(consulta: str, *, timeout: float = 5.0) -> Optional[tuple[float, float]]:
    """Geocodificador real (Nominatim/OSM). Nunca levanta: erro de rede/HTTP/
    parsing vira None."""
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
        lat, lon = float(dados[0]["lat"]), float(dados[0]["lon"])
        # Sanidade: descarta coordenada fora da faixa válida (resposta corrompida).
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        return lat, lon
    except Exception:
        return None


def geocodificar_escola(escola: Escola, geocoder: Geocoder = _nominatim) -> Optional[tuple[float, float]]:
    """(lat, lng) da escola, ou None se sem endereço suficiente / não encontrada.
    Exige ao menos a CIDADE — só "Nome, Brasil" quase nunca localiza um prédio.
    ``geocoder`` é injetável (testes passam um falso — sem rede)."""
    if not escola.cidade:
        return None
    consulta = montar_consulta(escola)
    if not consulta:
        return None
    return geocoder(consulta)


def geocodificar_lote(escolas: list[Escola], geocoder: Geocoder,
                      intervalo: float = INTERVALO_PADRAO) -> dict:
    """Geocodifica uma lista de escolas, respeitando o rate-limit entre chamadas.
    Preenche latitude/longitude das que forem localizadas (NÃO commita — quem
    chama decide a transação). Devolve a contagem {encontradas, falhas}.

    Dorme ANTES de cada chamada (não só entre elas): como o endpoint fatia a rede
    em vários lotes, isso garante o espaçamento do OSM também na FRONTEIRA entre
    lotes (a 1ª chamada de um lote não sai colada na última do lote anterior)."""
    encontradas = falhas = 0
    for escola in escolas:
        if intervalo > 0:
            time.sleep(intervalo)  # respeita o limite do OSM (inclusive entre lotes)
        coord = geocodificar_escola(escola, geocoder)
        if coord:
            escola.latitude, escola.longitude = coord
            encontradas += 1
        else:
            falhas += 1
    return {"encontradas": encontradas, "falhas": falhas}


# --- Dependências injetáveis (testes sobrescrevem para não bater na rede) ----

def get_geocoder() -> Geocoder:
    return _nominatim


def get_intervalo_geocode() -> float:
    return INTERVALO_PADRAO
