"""Documentação do cofre de credenciais da sincronização × o que o código faz.

Integração 3 do e97, dimensão esquemas-sync-docs (provas invertidas como regressão):

* achado 1 — o docs/SINCRONIZACAO.md ("Senha salva ilegível") dizia que o "Testar
  conexão" pedia o recadastro com o MESMO texto do ``vault.mensagem_credencial_ilegivel``,
  mas a rota usa ``router.MENSAGEM_CREDENCIAL_ILEGIVEL`` (o aviso do formulário);
* achado 2 — o docs/SINCRONIZACAO.md ("Decisões arquiteturais") e a docstring do
  ``app/sync/vault.py`` diziam que a chave do cofre "deriva da SECRET_KEY". A chave é a
  ``DATA_ENCRYPTION_KEY`` (obrigatória com ENV=producao); a SECRET_KEY só decifra as
  cifras legadas, e a rotação é pelo chaveiro + ``scripts.recifrar_segredos``. Quem
  seguisse o texto velho trocaria a DEK achando que a SECRET_KEY bastava, e as senhas
  das escolas ficariam ilegíveis.

Só leitura de arquivos do repositório e cifra em memória; chaves fictícias.
"""
from __future__ import annotations

import re
import secrets

import pytest

from app.core.config import PROJECT_ROOT, settings

_DOCS = PROJECT_ROOT / "docs"
_SINCRONIZACAO = _DOCS / "SINCRONIZACAO.md"

# "deriva da SECRET_KEY", "derivado da `SECRET_KEY`", "derived from `SECRET_KEY`",
# "a chave de cifra vem da SECRET_KEY" — a afirmação velha, em qualquer redação.
_RE_DERIVA_DA_SECRET_KEY = (
    re.compile(r"deriv\w*\s+(?:d[ao]|from)\s+(?:the\s+|a\s+)?`*SECRET_KEY", re.IGNORECASE),
    re.compile(r"(?:chave|key)[^.]{0,40}\s(?:vem|comes)\s+(?:da|from)\s+(?:the\s+|a\s+)?"
               r"`*SECRET_KEY", re.IGNORECASE),
)


def _norm(texto: str) -> str:
    return " ".join(texto.split())


def _afirmacoes_de_derivacao(texto: str) -> list[str]:
    plano = _norm(texto)
    return [plano[max(0, m.start() - 60):m.end() + 20]
            for regex in _RE_DERIVA_DA_SECRET_KEY for m in regex.finditer(plano)]


def _item_do_cofre(texto: str) -> str:
    """O item "Cofre Fernet ..." das "Decisões arquiteturais" (até o próximo item)."""
    secao = texto.split("## Decisões arquiteturais", 1)[1].split("\n## ", 1)[0]
    itens = [i for i in secao.split("\n- ") if i.lstrip("- ").startswith("**Cofre")]
    assert len(itens) == 1, itens
    return _norm(itens[0])


def _paragrafo_ilegivel(texto: str) -> str:
    plano = _norm(texto)
    inicio = plano.index("**Senha salva ilegível**")
    fim = plano.index("## Segurança / LGPD", inicio)
    return plano[inicio:fim]


# --- achado 2: a chave do cofre não deriva da SECRET_KEY --------------------------

def test_sincronizacao_md_nao_diz_que_a_chave_deriva_da_secret_key():
    texto = _SINCRONIZACAO.read_text(encoding="utf-8")
    assert _afirmacoes_de_derivacao(texto) == []
    item = _item_do_cofre(texto)
    assert "chave deriva" not in item
    assert "`DATA_ENCRYPTION_KEY`" in item and "obrigatória em produção" in item
    assert "só **decifra** as credenciais legadas" in item
    assert "`DATA_ENCRYPTION_KEYS_ANTERIORES`" in item
    assert "`CHAVE_CIFRA_LEGADA_ANTERIOR`" in item
    assert "python -m scripts.recifrar_segredos --executar" in item
    assert "Rotação futura já modelada" not in item
    # Os documentos para onde o item manda existem (links relativos ao docs/).
    for alvo in re.findall(r"\]\(([^)#]+)\)", item):
        assert (_DOCS / alvo).is_file(), alvo
    assert "CONTINUIDADE.md" in item and "PRODUCAO-ENV-E-MIGRACOES.md" in item


def test_docstrings_do_cofre_nao_dizem_que_a_chave_deriva_da_secret_key():
    from app.models import sincronizacao
    from app.services import assistente
    from app.sync import aovivo, vault

    for nome, doc in (("app.sync.vault", vault.__doc__),
                      ("app.models.sincronizacao", sincronizacao.__doc__),
                      ("assistente.salvar_config_assistente",
                       assistente.salvar_config_assistente.__doc__)):
        assert _afirmacoes_de_derivacao(doc or "") == [], nome
        assert "DATA_ENCRYPTION_KEY" in (doc or ""), nome
    assert "recifrar_segredos" in vault.__doc__
    # A sessão do Matific também fica ilegível com a DEK trocada, não só com a SECRET_KEY.
    assert "DATA_ENCRYPTION_KEY" in aovivo._carregar_sessao.__doc__


def test_bible_14_cripto_em_repouso_nao_diz_derivado_da_secret_key():
    texto = (_DOCS / "bible" / "14-infra-deploy-dr.md").read_text(encoding="utf-8")
    assert _afirmacoes_de_derivacao(texto) == []
    plano = _norm(texto)
    for rotulo in ("**Cripto em repouso**", "**Encryption at rest**"):
        inicio = plano.index(rotulo)
        item = plano[inicio:plano.index("- **", inicio + len(rotulo))]
        assert "`DATA_ENCRYPTION_KEY`" in item and "`SECRET_KEY`" in item, rotulo
        assert "recifrar_segredos" in item, rotulo


@pytest.fixture
def _anel_limpo(monkeypatch):
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEYS_ANTERIORES", "")
    monkeypatch.setattr(settings, "CHAVE_CIFRA_LEGADA_ANTERIOR", "")
    return monkeypatch


def test_o_que_o_documento_afirma_e_o_que_a_cifra_faz(_anel_limpo):
    """O porquê, no código: com a DEK (obrigatória em produção), a credencial cifrada
    abre com a DEK mesmo trocando a SECRET_KEY, e NÃO abre com a SECRET_KEY sozinha."""
    from app.core import security

    monkeypatch = _anel_limpo
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", "")
    assert any("DATA_ENCRYPTION_KEY ausente" in r for r in settings.riscos_de_producao())

    sk0 = "sk0-" + secrets.token_urlsafe(40)
    dek = "dek-" + secrets.token_urlsafe(40)
    monkeypatch.setattr(settings, "SECRET_KEY", sk0)
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", dek)
    cifra = security.cifrar_segredo('{"usuario": "robo@escola.invalid", "senha": "ficticia"}')
    assert security.situacao_da_cifra(cifra) == security.CIFRA_PRIMARIA

    monkeypatch.setattr(settings, "SECRET_KEY", "sk1-" + secrets.token_urlsafe(40))
    assert security.decifrar_segredo(cifra) is not None          # não deriva da SECRET_KEY

    monkeypatch.setattr(settings, "SECRET_KEY", sk0)
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", "")
    assert security.decifrar_segredo(cifra) is None              # a SECRET_KEY não basta

    # A rotação pelo chaveiro: a DEK que saiu, em DATA_ENCRYPTION_KEYS_ANTERIORES, ainda
    # decifra (até o recifrar_segredos levar tudo para a nova).
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEY", "dek2-" + secrets.token_urlsafe(40))
    monkeypatch.setattr(settings, "DATA_ENCRYPTION_KEYS_ANTERIORES", dek)
    assert security.situacao_da_cifra(cifra) == security.CIFRA_ANTERIOR


# --- achado 1: o texto do "Testar conexão" com a credencial ilegível -------------

def test_sincronizacao_md_descreve_o_texto_de_cada_acao_com_credencial_ilegivel():
    from app.sync import router as sync_router
    from app.sync import vault

    par = _paragrafo_ilegivel(_SINCRONIZACAO.read_text(encoding="utf-8"))
    assert "mesmo texto (`vault.mensagem_credencial_ilegivel`)" not in par
    assert '"Testar conexão"' in par and "`router.MENSAGEM_CREDENCIAL_ILEGIVEL`" in par
    assert "`vault.mensagem_credencial_ilegivel`" in par
    assert "`codigo=credencial_ilegivel`" in par
    # Os nomes citados existem no código.
    assert sync_router.CODIGO_CREDENCIAL_ILEGIVEL == "credencial_ilegivel"
    assert callable(vault.mensagem_credencial_ilegivel)
    assert sync_router.MENSAGEM_CREDENCIAL_ILEGIVEL != vault.mensagem_credencial_ilegivel(
        ["elefante"])

    # O documento diz que é a frase do aviso do formulário, com "desta plataforma" no
    # lugar do nome: confere com o CredenciaisForm.
    tsx = _norm((PROJECT_ROOT / "apps" / "web" / "src" / "components"
                 / "CredenciaisForm.tsx").read_text(encoding="utf-8"))
    # (O formulário trata as plataformas no masculino: "do Matific", "do Elefante Letrado".)
    aviso = tsx.replace("A senha salva do {nome}", "A senha salva desta plataforma")
    assert _norm(sync_router.MENSAGEM_CREDENCIAL_ILEGIVEL) in aviso
    assert "ilegivel}" in tsx and "disabled={testar.enviando" in tsx
