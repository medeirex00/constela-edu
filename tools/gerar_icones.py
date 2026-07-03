"""Gera os ícones do app desktop (PNG, ICO e ICNS) sem dependências externas.

Desenha um quadrado índigo (#4F46E5) com um "C" branco em blocos — a marca
do Constela Edu — e escreve os formatos que o empacotador do Tauri exige.

Uso:  python tools/gerar_icones.py
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

DESTINO = Path(__file__).resolve().parent.parent / "apps" / "desktop" / "src-tauri" / "icons"

INDIGO = (79, 70, 229, 255)
BRANCO = (255, 255, 255, 255)

# "C" em uma grade 5x7 (1 = pixel aceso)
LETRA = [
    "01110",
    "10001",
    "10000",
    "10000",
    "10000",
    "10001",
    "01110",
]


def desenhar(tamanho: int) -> bytes:
    """RGBA do ícone: fundo índigo, cantos arredondados e S branco."""
    pixels = bytearray()
    raio = tamanho // 8
    escala = max(1, tamanho // 12)
    largura_s = 5 * escala
    altura_s = 7 * escala
    origem_x = (tamanho - largura_s) // 2
    origem_y = (tamanho - altura_s) // 2

    for y in range(tamanho):
        for x in range(tamanho):
            # Cantos arredondados: fora do raio vira transparente
            dx = min(x, tamanho - 1 - x)
            dy = min(y, tamanho - 1 - y)
            if dx < raio and dy < raio:
                if (dx - raio) ** 2 + (dy - raio) ** 2 > raio ** 2:
                    pixels += bytes((0, 0, 0, 0))
                    continue

            cor = INDIGO
            if origem_x <= x < origem_x + largura_s and origem_y <= y < origem_y + altura_s:
                coluna = (x - origem_x) // escala
                linha = (y - origem_y) // escala
                if LETRA[linha][coluna] == "1":
                    cor = BRANCO
            pixels += bytes(cor)
    return bytes(pixels)


def png(tamanho: int) -> bytes:
    rgba = desenhar(tamanho)
    linhas = b"".join(
        b"\x00" + rgba[y * tamanho * 4:(y + 1) * tamanho * 4]
        for y in range(tamanho)
    )

    def chunk(tipo: bytes, dados: bytes) -> bytes:
        return (struct.pack(">I", len(dados)) + tipo + dados
                + struct.pack(">I", zlib.crc32(tipo + dados)))

    ihdr = struct.pack(">IIBBBBB", tamanho, tamanho, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(linhas, 9))
            + chunk(b"IEND", b""))


def ico(pngs: dict[int, bytes]) -> bytes:
    """ICO com entradas PNG (suportado desde o Windows Vista)."""
    tamanhos = sorted(pngs)
    cabecalho = struct.pack("<HHH", 0, 1, len(tamanhos))
    entradas = b""
    dados = b""
    offset = len(cabecalho) + 16 * len(tamanhos)
    for tamanho in tamanhos:
        corpo = pngs[tamanho]
        dimensao = 0 if tamanho >= 256 else tamanho
        entradas += struct.pack("<BBBBHHII", dimensao, dimensao, 0, 0, 1, 32,
                                len(corpo), offset)
        dados += corpo
        offset += len(corpo)
    return cabecalho + entradas + dados


def icns(pngs: dict[int, bytes]) -> bytes:
    """ICNS moderno: blocos PNG (ic07=128, ic08=256, ic09=512)."""
    tipos = {128: b"ic07", 256: b"ic08", 512: b"ic09"}
    blocos = b""
    for tamanho, tipo in tipos.items():
        if tamanho in pngs:
            corpo = pngs[tamanho]
            blocos += tipo + struct.pack(">I", len(corpo) + 8) + corpo
    return b"icns" + struct.pack(">I", len(blocos) + 8) + blocos


def main() -> None:
    DESTINO.mkdir(parents=True, exist_ok=True)
    pngs = {tamanho: png(tamanho) for tamanho in (32, 128, 256, 512)}
    (DESTINO / "32x32.png").write_bytes(pngs[32])
    (DESTINO / "128x128.png").write_bytes(pngs[128])
    (DESTINO / "128x128@2x.png").write_bytes(pngs[256])
    (DESTINO / "icon.png").write_bytes(pngs[512])
    (DESTINO / "icon.ico").write_bytes(ico({32: pngs[32], 128: pngs[128], 256: pngs[256]}))
    (DESTINO / "icon.icns").write_bytes(icns(pngs))
    print(f"Ícones gerados em {DESTINO}")


if __name__ == "__main__":
    main()
