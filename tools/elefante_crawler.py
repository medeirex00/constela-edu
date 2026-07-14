"""Crawler de engenharia reversa da API interna do Elefante Letrado (uso legítimo:
a conta da própria escola). Diferente do Matific (telas navegáveis por link), os
dados do Elefante vêm de **POST /report/\\*** disparados ao clicar na UI — então
AQUI VOCÊ DIRIGE o fluxo à mão e o crawler intercepta TUDO (inclusive o CORPO da
requisição, que é onde vão studentId/period/products).

COMO USAR (roda na SUA máquina, com o Playwright do backend):

    cd backend
    ./.venv/Scripts/python.exe ../tools/elefante_crawler.py
    # (Linux/Mac: .venv/bin/python ../tools/elefante_crawler.py)

O navegador abre VISÍVEL. Então:
  1) Faça o LOGIN à mão.
  2) Percorra o fluxo que quer documentar, SEM pressa (o crawler grava tudo):
     Relatórios → Escola → Desde o início → Pesquisar → selecione uma turma
     (ex.: 5º B) → selecione um aluno (ex.: Verônica) → role até
     "Questões Respondidas". Se quiser, TROQUE o período no filtro e role a
     tabela até o fim (para revelar paginação, se houver).
  3) Volte ao terminal e aperte ENTER. O crawler salva:
     - elefante_captura/NNN_<rota>.json  (cada chamada: método, URL, CORPO da
       requisição, status e o JSON de resposta);
     - elefante_captura/_index.json      (todas as chamadas, em ordem);
     - elefante_captura/_endpoints.json  (rotas ÚNICAS, com {id}/{uuid}, os
       parâmetros de query e as chaves do corpo — o "mapa" da API);
     - elefante_captura/_estrutura.json  (a FORMA de cada resposta: tipos/chaves,
       sem valores — o que preciso para montar o parser).

SEGURANÇA: o login é MANUAL de propósito — este script NUNCA recebe nem guarda a
sua senha. O token Authorization é REDIGIDO (não é salvo). As respostas contêm
dados reais de alunos: a pasta elefante_captura/ é gitignored; anonimize antes de
compartilhar (pode colar aqui só o _estrutura.json + _endpoints.json, que não têm
nome de criança).
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from urllib.parse import urlsplit

from playwright.async_api import async_playwright

LOGIN = "https://login.elefanteletrado.com.br/manager"
APP = "https://admin.elefanteletrado.com.br/reports/menu"
SAIDA = os.path.join(os.getcwd(), "elefante_captura")
MAX_POR_ROTA = 4      # guarda até 4 exemplos de cada rota (o resto vira só contagem)


def _slug(url: str, metodo: str) -> str:
    p = urlsplit(url)
    base = re.sub(r"[^a-z0-9]+", "_", (p.path + "_" + p.query).lower()).strip("_")
    return f"{metodo.lower()}_{base}"[:80] or "root"


def _rota_template(url: str) -> str:
    """Rota com {uuid}/{id} no lugar dos identificadores — agrupa chamadas iguais."""
    p = urlsplit(url)
    caminho = re.sub(r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                     "/{uuid}", p.path, flags=re.I)
    caminho = re.sub(r"/\d+", "/{id}", caminho)
    params = sorted(set(re.findall(r"[?&]([a-zA-Z_]+)=", p.query or "")))
    return caminho + (f"?{'&'.join(params)}" if params else "")


def _estrutura(obj, prof: int = 0, max_prof: int = 6):
    """FORMA do JSON: tipos e chaves, NUNCA os valores (sem PII)."""
    if prof >= max_prof:
        return "…"
    if isinstance(obj, dict):
        return {k: _estrutura(v, prof + 1, max_prof) for k, v in list(obj.items())[:60]}
    if isinstance(obj, list):
        return [] if not obj else [f"list[{len(obj)}]", _estrutura(obj[0], prof + 1, max_prof)]
    if isinstance(obj, bool):
        return "bool"
    if isinstance(obj, (int, float)):
        return "num"
    if isinstance(obj, str):
        return "str"
    return "null"


async def main() -> None:
    os.makedirs(SAIDA, exist_ok=True)
    capturas: list[dict] = []
    contador_rota: dict[str, int] = {}
    endpoints: dict[str, dict] = {}
    estrutura: dict[str, object] = {}

    async with async_playwright() as pw:
        nav = await pw.chromium.launch(headless=False)      # VISÍVEL p/ o login manual
        ctx = await nav.new_context(locale="pt-BR")
        pag = await ctx.new_page()

        async def on_response(resp):
            try:
                req = resp.request
                if req.resource_type not in ("xhr", "fetch"):
                    return
                ctype = (resp.headers or {}).get("content-type", "")
                if "json" not in ctype:
                    return
                try:
                    corpo = await resp.json()
                except Exception:
                    return
                url = resp.url
                metodo = req.method
                rota = f"{metodo} {_rota_template(url)}"
                contador_rota[rota] = contador_rota.get(rota, 0) + 1
                # Corpo da requisição (POST /report/*): studentId/period/products…
                post = None
                try:
                    raw = req.post_data
                    post = json.loads(raw) if raw else None
                except Exception:
                    post = req.post_data if req.post_data else None
                # Mapa de endpoints únicos (query params + chaves do corpo).
                ep = endpoints.setdefault(rota, {
                    "rota": rota, "exemplos_url": [],
                    "query_params": set(), "body_keys": set(), "vezes": 0})
                ep["vezes"] = contador_rota[rota]
                for k in re.findall(r"[?&]([a-zA-Z_]+)=", urlsplit(url).query or ""):
                    ep["query_params"].add(k)
                if isinstance(post, dict):
                    ep["body_keys"].update(post.keys())
                if len(ep["exemplos_url"]) < 3:
                    ep["exemplos_url"].append(url)
                # Forma da resposta (uma vez por rota).
                if rota not in estrutura:
                    estrutura[rota] = _estrutura(corpo)
                # Guarda exemplos completos (redigindo o Authorization).
                if contador_rota[rota] <= MAX_POR_ROTA:
                    reg = {"url": url, "metodo": metodo, "status": resp.status,
                           "request_body": post,
                           "tem_authorization": bool((req.headers or {}).get("authorization")),
                           "n_itens": len(corpo) if isinstance(corpo, list) else None,
                           "response": corpo}
                    capturas.append(reg)
                    n = len(capturas)
                    with open(os.path.join(SAIDA, f"{n:03d}_{_slug(url, metodo)}.json"),
                              "w", encoding="utf-8") as fh:
                        json.dump(reg, fh, ensure_ascii=False, indent=1)
                    marca = "  ⭐ QUESTÕES" if "answered-questions" in url else ""
                    print(f"  [{resp.status}] {metodo} …{urlsplit(url).path[-52:]}"
                          f" (itens={reg['n_itens']}){marca}")
            except Exception:
                pass

        pag.on("response", on_response)

        await pag.goto(LOGIN, wait_until="domcontentloaded")
        print("\n" + "=" * 70)
        print("1) FAÇA O LOGIN à mão na janela do navegador.")
        print("2) Percorra: Relatórios → Escola → Desde o início → Pesquisar →")
        print("   turma (5º B) → aluno (Verônica) → role até 'Questões Respondidas'.")
        print("   Troque o PERÍODO no filtro e role a tabela até o fim (paginação).")
        print("3) Volte AQUI e aperte ENTER para salvar tudo.")
        print("=" * 70 + "\n")
        try:
            await asyncio.get_event_loop().run_in_executor(None, input)
        except (EOFError, KeyboardInterrupt):
            pass

        # Serializa os sets para JSON.
        eps = []
        for ep in endpoints.values():
            eps.append({**ep,
                        "query_params": sorted(ep["query_params"]),
                        "body_keys": sorted(ep["body_keys"])})
        eps.sort(key=lambda e: e["rota"])
        with open(os.path.join(SAIDA, "_index.json"), "w", encoding="utf-8") as fh:
            json.dump([{"url": c["url"], "metodo": c["metodo"], "status": c["status"],
                        "n_itens": c["n_itens"], "request_body": c["request_body"]}
                       for c in capturas], fh, ensure_ascii=False, indent=1)
        with open(os.path.join(SAIDA, "_endpoints.json"), "w", encoding="utf-8") as fh:
            json.dump(eps, fh, ensure_ascii=False, indent=1)
        with open(os.path.join(SAIDA, "_estrutura.json"), "w", encoding="utf-8") as fh:
            json.dump(estrutura, fh, ensure_ascii=False, indent=1)

        print(f"\nOK: {len(capturas)} chamada(s) salvas, {len(eps)} rota(s) únicas em "
              f"{SAIDA}")
        print("Rotas capturadas:")
        for e in eps:
            q = ("?" + ",".join(e["query_params"])) if e["query_params"] else ""
            b = (" body=" + ",".join(e["body_keys"])) if e["body_keys"] else ""
            print(f"  {e['vezes']:>3}× {e['rota']}{q}{b}")
        print("\nMe mande _endpoints.json e _estrutura.json (não têm nome de criança).")
        await nav.close()


if __name__ == "__main__":
    asyncio.run(main())
