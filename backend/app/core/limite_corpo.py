"""Teto do tamanho do corpo da requisição, ANTES da autenticação.

Por quê: o FastAPI lê e interpreta o corpo (``await request.form()`` /
``request.body()``) antes de resolver as dependências — inclusive a de login. Sem
teto, qualquer pessoa, sem conta, manda um corpo gigante para qualquer rota com
corpo e o processo o carrega. No starlette 0.47 (preso pelo FastAPI 0.116), o
``request.form()`` de ``x-www-form-urlencoded`` ignora ``max_fields`` e
``max_part_size`` (GHSA-82w8-qh3p-5jfq): o corpo inteiro vira lista na memória —
e o ``/auth/login`` é exatamente um formulário desses. A correção do framework
exige starlette 1.3.1 / FastAPI 0.133+ (troca grande, depois do piloto); este teto
é o controle compensatório até lá.

Tetos (configuráveis em ``Settings``):

* ``application/x-www-form-urlencoded`` — 64 KB, em qualquer rota: o maior
  formulário legítimo é o de login (usuário + senha);
* ``multipart/form-data`` GRANDE — 160 MB, SÓ nas rotas de upload de 150 MB
  (avaliações oficiais e casamento do INEP, Admin Global) e SÓ com um token de
  acesso válido: o teto não pode vir do tipo que o cliente declara (um JSON
  disfarçado de multipart levaria 160 MB a qualquer rota) nem valer para anônimos;
* todo o resto (JSON, multipart das outras rotas — a maior é o backup, 25 MB) —
  32 MB: a confirmação de importação manda as linhas do arquivo em JSON.

Como: ``Content-Length`` acima do teto → 413 sem guardar nada. Se o excesso for
moderado (até 2 × o teto), o corpo é LIDO E DESCARTADO antes da resposta: fechar a
conexão com dados pendentes faz o sistema mandar RST e o navegador mostra "sem
internet" em vez do 413. Acima disso, responde e fecha. Sem ``Content-Length``
(chunked), os bytes são contados ao chegar e, passado o teto, ``receive`` levanta
``HTTPException(413)`` — o FastAPI repassa ``HTTPException`` de dentro da leitura
do corpo, e o ``ExceptionMiddleware`` (por dentro deste) a transforma em resposta.

ASGI puro e o middleware MAIS INTERNO dos nossos: a resposta 413 passa pela
observabilidade (log/métrica), pelos cabeçalhos de segurança e pelo CORS.
"""
from __future__ import annotations

import json
import re

from fastapi import HTTPException, status
from starlette.datastructures import Headers

MENSAGEM = "Requisição grande demais."
# Rotas de upload de 150 MB (sem o prefixo da API): avaliações oficiais e INEP.
ROTAS_DE_UPLOAD_GRANDE = r"avaliacoes/(?:analisar|importar|importar-preset)|redes/\d+/casar-inep"


def _token_valido(cabecalhos: Headers) -> bool:
    """Token de acesso de PESSOA da equipe, bem assinado e no prazo. Tokens com
    ``papel`` (o do aluno do Quest: 30 dias, obtido só com o código do cartão)
    usam a mesma chave e passariam na assinatura, mas nunca valem nas rotas do
    Edu (``deps.get_usuario_atual``) — não podem levar o teto de 160 MB."""
    from app.core.security import decodificar_token

    esquema, _, token = (cabecalhos.get("authorization") or "").partition(" ")
    if esquema.lower() != "bearer" or not token:
        return False
    payload = decodificar_token(token.strip())
    return payload is not None and not payload.get("papel")


class LimiteDeCorpoMiddleware:
    def __init__(self, app, settings) -> None:
        self.app = app
        self.settings = settings
        prefixo = re.escape(settings.API_V1_PREFIX.rstrip("/"))
        self._upload_grande = re.compile(rf"^{prefixo}/(?:{ROTAS_DE_UPLOAD_GRANDE})/?$")

    def _teto(self, scope, cabecalhos: Headers) -> int:
        tipo = cabecalhos.get("content-type", "").split(";", 1)[0].strip().lower()
        if tipo == "application/x-www-form-urlencoded":
            return self.settings.LIMITE_CORPO_FORMULARIO_BYTES
        if (tipo == "multipart/form-data" and self._upload_grande.match(scope.get("path", ""))
                and _token_valido(cabecalhos)):
            return self.settings.LIMITE_CORPO_MULTIPART_BYTES
        return self.settings.LIMITE_CORPO_OUTROS_BYTES

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        cabecalhos = Headers(scope=scope)
        teto = self._teto(scope, cabecalhos)
        declarado = cabecalhos.get("content-length")
        if declarado is not None:
            try:
                tamanho = int(declarado)
            except ValueError:
                tamanho = -1
            if tamanho < 0:
                await _responder(send, status.HTTP_400_BAD_REQUEST, "Content-Length inválido.", fechar=True)
                return
            if tamanho > teto:
                drenado = tamanho <= 2 * teto and await _descartar_corpo(receive, tamanho)
                await _responder(send, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, MENSAGEM,
                                 fechar=not drenado)
                return

        recebido = 0

        async def receber():
            nonlocal recebido
            evento = await receive()
            if evento["type"] == "http.request":
                recebido += len(evento.get("body", b""))
                if recebido > teto:
                    raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, MENSAGEM)
            return evento

        await self.app(scope, receber, send)


async def _descartar_corpo(receive, declarado: int) -> bool:
    """Lê e joga fora o corpo (nada fica na memória). True se chegou ao fim."""
    lido = 0
    while True:
        evento = await receive()
        if evento["type"] != "http.request":
            return False                      # o cliente desistiu (http.disconnect)
        lido += len(evento.get("body", b""))
        if lido > declarado:
            return False
        if not evento.get("more_body"):
            return True


async def _responder(send, codigo: int, detalhe: str, *, fechar: bool) -> None:
    corpo = json.dumps({"detail": detalhe}, ensure_ascii=False).encode("utf-8")
    cabecalhos = [(b"content-type", b"application/json"),
                  (b"content-length", str(len(corpo)).encode("ascii"))]
    if fechar:
        cabecalhos.append((b"connection", b"close"))
    await send({"type": "http.response.start", "status": codigo, "headers": cabecalhos})
    await send({"type": "http.response.body", "body": corpo})
