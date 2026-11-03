"""Cabeçalhos de segurança HTTP de toda resposta da API.

* ``X-Content-Type-Options: nosniff`` — o navegador não "adivinha" o tipo (um JSON
  com texto controlado pelo usuário nunca vira HTML/script);
* ``X-Frame-Options: DENY`` — nenhuma resposta da API é emoldurada (clickjacking).
  Conferido no apps/web: PDFs, planilhas e o SVG do QR chegam por ``fetch`` → blob →
  download (``apiDownload``); nada abre a URL da API em iframe/embed/object;
* ``Referrer-Policy: no-referrer`` — links abertos a partir de uma resposta não levam
  o caminho (que pode carregar token de painel público ou de redefinição de senha);
* ``Strict-Transport-Security`` — quando a requisição chegou por HTTPS (direto ou
  via ``X-Forwarded-Proto`` do proxy confiável, mesma régua do TRUSTED_PROXY_HOPS do
  rate limit) ou em ENV=producao. Navegadores ignoram HSTS recebido por HTTP puro,
  então um ``X-Forwarded-Proto`` forjado não tem efeito. Sem ``includeSubDomains``:
  numa instalação própria a API pode morar no mesmo domínio de outros serviços;
* ``Content-Security-Policy`` restritiva SÓ em respostas JSON (nada a carregar,
  nada a emoldurar). HTML (/docs, quando ligado), PDF e imagens não recebem CSP.

ASGI puro e por DENTRO do CORS: as respostas do CORS (preflight) saem como antes,
e a resposta 500 da rede de segurança da observabilidade também ganha os cabeçalhos.
Cabeçalho que a rota já definiu é respeitado (``setdefault``).
"""
from __future__ import annotations

from starlette.datastructures import Headers, MutableHeaders

HSTS = "max-age=31536000"
CSP_JSON = "default-src 'none'; frame-ancestors 'none'"
_FIXOS = (
    ("x-content-type-options", "nosniff"),
    ("x-frame-options", "DENY"),
    ("referrer-policy", "no-referrer"),
)


def chegou_por_https(scope, hops: int) -> bool:
    if scope.get("scheme") == "https":
        return True
    if hops <= 0:
        return False
    bruto = Headers(scope=scope).get("x-forwarded-proto") or ""
    partes = [p.strip().lower() for p in bruto.split(",") if p.strip()]
    # Cada proxy confiável acrescenta o seu à direita (como no X-Forwarded-For).
    return len(partes) >= hops and partes[-hops] == "https"


class CabecalhosSegurancaMiddleware:
    def __init__(self, app, settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        hsts = (self.settings.em_producao
                or chegou_por_https(scope, self.settings.TRUSTED_PROXY_HOPS))

        async def enviar(evento):
            if evento["type"] == "http.response.start":
                # "headers" é opcional no ASGI: garante a lista antes de editar.
                evento = {**evento, "headers": list(evento.get("headers") or [])}
                cabecalhos = MutableHeaders(scope=evento)
                for nome, valor in _FIXOS:
                    cabecalhos.setdefault(nome, valor)
                if hsts:
                    cabecalhos.setdefault("strict-transport-security", HSTS)
                tipo = (cabecalhos.get("content-type") or "").lower()
                if tipo.startswith("application/json") or "+json" in tipo.split(";")[0]:
                    cabecalhos.setdefault("content-security-policy", CSP_JSON)
            await send(evento)

        await self.app(scope, receive, enviar)
