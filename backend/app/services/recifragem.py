"""Recifragem dos segredos em repouso para a chave ATUAL (rotação planejada).

O anel de ``app.core.security`` lê com as chaves anteriores (só de decifra) e cifra
sempre com a primária. Este módulo leva o que ainda está numa chave anterior para a
primária, para que as anteriores possam ser APAGADAS do ambiente:

* ``contar`` (só leitura): por origem, quantas cifras abrem com a primária, só com
  uma anterior, com nenhuma (ilegíveis) e quantas estão vazias;
* ``executar``: uma transação por origem (``SET LOCAL lock_timeout`` e
  ``SELECT … FOR UPDATE`` no PostgreSQL), que reescreve só o que NÃO está na
  primária — idempotente: a 2ª execução não muda nenhuma linha. A sessão salva do
  Matific é APAGADA em vez de recifrada (é refeita sozinha no próximo acesso, TTL
  de 6 h); o ilegível fica como está (só o recadastro resolve) e é contado. No
  fim, recalcula na primária o hash do código do Quest
  (``credenciais.preencher_hashes_ausentes``).

Nada aqui devolve, registra ou imprime o valor de um segredo ou de uma chave: só
números. Origens (A1 §1.3/§1.6 — os únicos chamadores de ``cifrar_segredo``):
``plataforma_credenciais.segredo_cifrado``, ``configuracoes[assistente].valor.
api_key_cifrada`` e ``configuracoes[matific_sessao].valor.cifrado``.
"""
from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.security import (
    CIFRA_ANTERIOR,
    CIFRA_ILEGIVEL,
    CIFRA_PRIMARIA,
    CIFRA_VAZIA,
    SITUACOES_CIFRA,
    recifrar,
    situacao_da_cifra,
)
from app.models.configuracao import Configuracao
from app.models.sincronizacao import PlataformaCredencial

ORIGEM_CREDENCIAIS = "plataforma_credenciais"
ORIGEM_ASSISTENTE = "configuracoes.assistente"
ORIGEM_SESSAO_MATIFIC = "configuracoes.matific_sessao"
ORIGENS = (ORIGEM_CREDENCIAIS, ORIGEM_ASSISTENTE, ORIGEM_SESSAO_MATIFIC)

# Os mesmos de app/services/assistente.py e app/sync/aovivo.py (conferido em teste).
NS_ASSISTENTE, CHAVE_ASSISTENTE, CAMPO_ASSISTENTE = "assistente", "valores", "api_key_cifrada"
NS_SESSAO_MATIFIC, CAMPO_SESSAO_MATIFIC = "matific_sessao", "cifrado"

# Espera máxima por um lock de linha: a API pode estar gravando a mesma linha (um
# recadastro, a sessão do Matific). Melhor falhar e repetir do que travar o site.
LOCK_TIMEOUT = "5s"

ACAO_AUDITORIA = "seguranca.recifragem"


def _consulta(origem: str):
    if origem == ORIGEM_CREDENCIAIS:
        return select(PlataformaCredencial).order_by(PlataformaCredencial.id)
    if origem == ORIGEM_ASSISTENTE:
        return (select(Configuracao)
                .where(Configuracao.namespace == NS_ASSISTENTE,
                       Configuracao.chave == CHAVE_ASSISTENTE)
                .order_by(Configuracao.id))
    if origem == ORIGEM_SESSAO_MATIFIC:
        return (select(Configuracao)
                .where(Configuracao.namespace == NS_SESSAO_MATIFIC)
                .order_by(Configuracao.id))
    raise ValueError(f"origem desconhecida: {origem}")


def _token(origem: str, linha) -> str | None:
    if origem == ORIGEM_CREDENCIAIS:
        return linha.segredo_cifrado or None
    valor = linha.valor if isinstance(linha.valor, dict) else {}
    campo = CAMPO_ASSISTENTE if origem == ORIGEM_ASSISTENTE else CAMPO_SESSAO_MATIFIC
    bruto = valor.get(campo)
    return str(bruto) if bruto else None


def _gravar(origem: str, linha, novo: str) -> None:
    if origem == ORIGEM_CREDENCIAIS:
        linha.segredo_cifrado = novo
        return
    valor = dict(linha.valor)              # objeto NOVO: o JSON é rastreado por atribuição
    valor[CAMPO_ASSISTENTE] = novo
    linha.valor = valor


def contar(db: Session) -> dict[str, dict[str, int]]:
    """{origem: {primaria, anterior, ilegivel, vazio}} — só leitura, só números."""
    resultado: dict[str, dict[str, int]] = {}
    for origem in ORIGENS:
        contagem = dict.fromkeys(SITUACOES_CIFRA, 0)
        for linha in db.execute(_consulta(origem)).scalars():
            contagem[situacao_da_cifra(_token(origem, linha))] += 1
        resultado[origem] = contagem
    return resultado


def pendentes(contagens: dict[str, dict[str, int]], *,
              aceitar_ilegiveis: bool = False) -> int:
    """Quantas cifras ainda impedem apagar as chaves anteriores. A sessão do Matific
    nunca conta como ilegível pendente (é descartável e o --executar a apaga)."""
    total = 0
    for origem, c in contagens.items():
        total += c.get(CIFRA_ANTERIOR, 0)
        if not aceitar_ilegiveis and origem != ORIGEM_SESSAO_MATIFIC:
            total += c.get(CIFRA_ILEGIVEL, 0)
    return total


def _abrir_transacao(db: Session) -> None:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))


def _recifrar_origem(db: Session, origem: str) -> dict[str, int]:
    feito = {"recifradas": 0, "apagadas": 0, "ilegiveis_mantidas": 0}
    _abrir_transacao(db)
    linhas = db.execute(_consulta(origem).with_for_update()).scalars().all()
    for linha in linhas:
        token = _token(origem, linha)
        situacao = situacao_da_cifra(token)
        if situacao in (CIFRA_PRIMARIA, CIFRA_VAZIA):
            continue                       # idempotência: já está na chave atual
        if origem == ORIGEM_SESSAO_MATIFIC:
            db.delete(linha)               # descartável: refeita no próximo acesso
            feito["apagadas"] += 1
            continue
        if situacao == CIFRA_ILEGIVEL:
            feito["ilegiveis_mantidas"] += 1   # só o recadastro resolve
            continue
        novo = recifrar(token)
        if novo is None:                   # mudou de chave no meio: fica para a próxima
            feito["ilegiveis_mantidas"] += 1
            continue
        _gravar(origem, linha, novo)
        feito["recifradas"] += 1
    db.flush()
    return feito


def executar(db: Session, *, registrar_auditoria: bool = True) -> dict:
    """Leva para a primária tudo o que abre com uma chave anterior. Uma transação
    por origem: uma falha no meio desfaz só a origem em curso (as anteriores ficam
    gravadas) e a próxima execução continua de onde parou. Devolve só números."""
    from app.quest.services import credenciais as quest_credenciais
    from app.services.audit import registrar

    db.rollback()                          # começa limpo: cada origem é uma transação
    antes = contar(db)
    db.rollback()
    feito: dict[str, dict[str, int]] = {}
    for origem in ORIGENS:
        try:
            feito[origem] = _recifrar_origem(db, origem)
            db.commit()
        except Exception:
            db.rollback()
            raise
    try:
        hashes_quest = quest_credenciais.preencher_hashes_ausentes(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    depois = contar(db)
    resumo = {"antes": antes, "feito": feito, "hashes_quest_corrigidos": hashes_quest,
              "depois": depois}
    if registrar_auditoria:
        registrar(db, ACAO_AUDITORIA, entidade="cifra", detalhes=resumo)
        db.commit()
    else:
        db.rollback()
    return resumo
