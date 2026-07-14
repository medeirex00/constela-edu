"""Crawler de engenharia reversa da API interna do Matific (uso legítimo: a conta
da própria escola). Percorre TODAS as telas do painel do administrador, intercepta
TODAS as requisições/respostas JSON e documenta a API descoberta.

COMO USAR (roda na SUA máquina, com o Playwright do backend):

    cd backend
    ./.venv/Scripts/python.exe ../tools/matific_crawler.py
    # (Linux/Mac: .venv/bin/python ../tools/matific_crawler.py)

O navegador abre VISÍVEL. Você faz o LOGIN À MÃO (digita e-mail/senha, passa o
reCAPTCHA) e volta ao terminal e aperta ENTER. Daí o crawler:
  - segue automaticamente os links do admin (/teachers/…), BFS limitado;
  - intercepta cada resposta JSON e salva em matific_captura/NNN_<rota>.json;
  - grava matific_captura/_index.json (todas as chamadas) e _endpoints.json
    (rotas ÚNICAS, com {id} no lugar de UUIDs/números);
  - gera matific_captura/matific-openapi-auto.yaml a partir do que viu.

NÃO commite a pasta matific_captura/ (contém dados reais de alunos). Anonimize
antes de compartilhar. O login é MANUAL de propósito: este script NUNCA recebe
nem guarda a sua senha.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from urllib.parse import urlsplit

from playwright.async_api import async_playwright

BASE = "https://www.matific.com"
LOGIN = f"{BASE}/bra/pt-br/login-page/"
# Semente de telas do admin (o crawler descobre o resto pelos links).
SEMENTES = [
    f"{BASE}/bra/pt-br/teachers/admin/school-leaderboard/",
    f"{BASE}/bra/pt-br/teachers/",
    f"{BASE}/bra/pt-br/teachers/admin/",
]
SAIDA = os.path.join(os.getcwd(), "matific_captura")
MAX_TELAS = 40          # trava de segurança do BFS
ESPERA_MS = 3500        # tempo p/ a tela disparar as chamadas
MAX_POR_ROTA = 2        # salva no máx. 2 exemplos de cada rota (corta o ruído
                        # de polls como user-tutorial-state, que repetem centenas de vezes)


def _slug(url: str) -> str:
    p = urlsplit(url)
    return (re.sub(r"[^a-z0-9]+", "_", (p.path + "_" + p.query).lower()).strip("_"))[:80] or "root"


def _rota_template(url: str) -> str:
    """Rota com {id} no lugar de UUID/números — agrupa chamadas iguais."""
    p = urlsplit(url)
    caminho = re.sub(r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "/{uuid}", p.path, flags=re.I)
    caminho = re.sub(r"/\d+", "/{id}", caminho)
    params = sorted(re.findall(r"[?&]([a-z_]+)=", p.query or "", re.I))
    return f"{p.path and caminho}{'?' + '&'.join(params) if params else ''}"


async def main() -> None:
    os.makedirs(SAIDA, exist_ok=True)
    capturas: list[dict] = []
    vistos_rota: dict[str, dict] = {}
    contador_rota: dict[str, int] = {}

    async with async_playwright() as pw:
        nav = await pw.chromium.launch(headless=False)   # VISÍVEL p/ login manual
        ctx = await nav.new_context()
        pag = await ctx.new_page()

        async def on_response(resp):
            try:
                url = resp.url
                if "matific.com" not in url:
                    return
                ct = (resp.headers or {}).get("content-type", "")
                if "json" not in ct:
                    return
                # Corta o ruído: cada rota é salva no máx. MAX_POR_ROTA vezes.
                rota = _rota_template(resp.url)
                contador_rota[rota] = contador_rota.get(rota, 0) + 1
                vistos_rota.setdefault(rota, {
                    "metodo": resp.request.method, "rota": rota,
                    "exemplo_url": resp.url, "status": resp.status})
                if contador_rota[rota] > MAX_POR_ROTA:
                    return
                try:
                    corpo = await resp.json()
                except Exception:  # noqa: BLE001
                    corpo = None
                rec = {
                    "url": url,
                    "metodo": resp.request.method,
                    "status": resp.status,
                    "rota": rota,
                    "request_headers": dict(resp.request.headers),
                    "response": corpo,
                }
                capturas.append(rec)
                idx = len(capturas)
                with open(os.path.join(SAIDA, f"{idx:03d}_{_slug(url)}.json"),
                          "w", encoding="utf-8") as f:
                    json.dump(rec, f, ensure_ascii=False, indent=2)
                print(f"  [{idx:03d}] {rec['metodo']} {resp.status}  {rota}")
            except Exception as exc:  # noqa: BLE001 — nunca derruba o crawl
                print(f"  (erro ao capturar: {str(exc)[:80]})")

        pag.on("response", on_response)

        # 1) LOGIN MANUAL (você passa o reCAPTCHA; a senha nunca vem para o script).
        await pag.goto(LOGIN)
        print("\n================ LOGIN MANUAL ================")
        print("Faça login na janela do navegador (e-mail, senha, reCAPTCHA).")
        print("Quando estiver DENTRO do painel, volte aqui e aperte ENTER.")
        print("=============================================\n")
        await asyncio.get_event_loop().run_in_executor(None, input)

        # 2) BFS pelas telas do admin, seguindo os links /teachers/…
        fila = list(SEMENTES)
        visitadas: set[str] = set()
        while fila and len(visitadas) < MAX_TELAS:
            url = fila.pop(0)
            if url in visitadas:
                continue
            visitadas.add(url)
            print(f"\n>>> Tela {len(visitadas)}: {url}")
            try:
                await pag.goto(url, wait_until="networkidle", timeout=30000)
            except Exception:  # noqa: BLE001 — networkidle pode estourar em SPA
                pass
            await pag.wait_for_timeout(ESPERA_MS)
            # descobre novos links do admin
            try:
                hrefs = await pag.eval_on_selector_all(
                    "a[href]", "els => els.map(e => e.href)")
            except Exception:  # noqa: BLE001
                hrefs = []
            for h in hrefs:
                if ("/teachers/" in h and h.startswith(BASE)
                        and "logout" not in h and h not in visitadas and h not in fila):
                    fila.append(h.split("#")[0])

        # 3) Índices + OpenAPI
        with open(os.path.join(SAIDA, "_index.json"), "w", encoding="utf-8") as f:
            json.dump([{k: c[k] for k in ("metodo", "status", "rota", "url")}
                       for c in capturas], f, ensure_ascii=False, indent=2)
        with open(os.path.join(SAIDA, "_endpoints.json"), "w", encoding="utf-8") as f:
            json.dump(sorted(vistos_rota.values(), key=lambda r: r["rota"]),
                      f, ensure_ascii=False, indent=2)
        _gerar_openapi(vistos_rota, capturas)

        print(f"\n✅ {len(capturas)} respostas em {len(vistos_rota)} rotas únicas.")
        print(f"   Saída: {SAIDA}")
        print("   Envie _endpoints.json + _index.json (sem nomes de alunos) para completar o MATIFIC_API.md.")
        await nav.close()


def _gerar_openapi(rotas: dict, capturas: list) -> None:
    """OpenAPI 3.0 aproximado a partir das rotas capturadas (1 exemplo por rota)."""
    exemplo_por_rota: dict[str, dict] = {}
    for c in capturas:
        exemplo_por_rota.setdefault(c["rota"], c)
    linhas = [
        "openapi: 3.0.3",
        "info:",
        "  title: Matific — API interna (descoberta)",
        "  version: '0.1-descoberta'",
        "  description: Gerado automaticamente pelo matific_crawler.py (não oficial).",
        "servers:",
        "  - url: https://www.matific.com",
        "components:",
        "  securitySchemes:",
        "    sessaoCookie: { type: apiKey, in: cookie, name: sessionid }",
        "security:",
        "  - sessaoCookie: []",
        "paths:",
    ]
    for rota in sorted(rotas):
        caminho = rota.split("?")[0]
        metodo = rotas[rota]["metodo"].lower()
        ex = exemplo_por_rota.get(rota, {})
        linhas += [
            f"  {caminho}:",
            f"    {metodo}:",
            f"      summary: {rota}",
            "      responses:",
            f"        '{ex.get('status', 200)}':",
            "          description: OK",
            "          content:",
            "            application/json: {}",
        ]
    with open(os.path.join(SAIDA, "matific-openapi-auto.yaml"), "w", encoding="utf-8") as f:
        f.write("\n".join(linhas) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
