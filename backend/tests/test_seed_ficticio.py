"""Dado fictício não usa nome de escola real da rede (lacuna C5 do e97).

A matriz de prontidão (§4.1) proíbe nome real de escola em tela de dado fictício. O
seed da demonstração (``scripts/seed.py``, que o ``seed_e2e.py`` e os E2E usam) criava
a escola com o nome de uma escola REAL da rede, e testes copiavam nomes reais nas
fixtures. Aqui:

  * o seed cria a escola de demonstração com nome INVENTADO (``seed.ESCOLA_DEMO``),
    continua idempotente e reaproveita um banco semeado quando o nome era outro (o
    e-mail do admin inicial é único: semear de novo quebraria na constraint);
  * a catraca varre os seeds, os E2E, os testes (fixtures) e os mocks de dado
    fictício atrás dos nomes das escolas reais da rede (``no_alcance``): as pastas de
    teste, e também qualquer ``*.test.*``/``*.spec.*`` e pasta ``__mocks__`` fora
    delas (os testes de ``packages/core`` e o mock da API do web ficavam de fora até
    a integração 5 do e97). Cada arquivo é lido como texto em UTF-8, UTF-16 ou
    cp1252, com os escapes ``\\uXXXX`` do JSON desfeitos (``ler_texto``, o mesmo da
    sentinela de CPF).

De onde vêm os nomes reais: do catálogo que o produto já tem (``REDE_CARAGUA`` em
``apps/web/src/pages/Escolas.tsx`` — a relação oficial da Secretaria, dado público),
mais a escola 1, que não está no catálogo (era a que o seed criava). Para cada
escola entram o nome curto do catálogo e o nome do patrono, sem acento, sem caixa e
atravessando quebra de linha. Este arquivo é a única exceção da varredura: precisa
do nome da escola 1 para procurá-lo.

Fora do alcance (de propósito): o código de produto (o próprio catálogo, a dica do
formulário de geocodificação, comentários que explicam o casamento de nomes) e a
documentação operacional, que falam das escolas reais porque o produto as atende.
"""
import os
import re
import unicodedata
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.config import PROJECT_ROOT
from app.models import Escola, NivelDificuldade, Usuario
from scripts import seed
from tests.test_sem_dado_pessoal_real import arquivos_a_verificar, ler_texto

ESTE_ARQUIVO = "backend/tests/test_seed_ficticio.py"
CATALOGO = "apps/web/src/pages/Escolas.tsx"
# A escola 1 da rede: fora do catálogo do produto porque era a que o seed criava.
ESCOLA_1 = "JORGE PASSOS"

# Onde mora dado fictício: os seeds de demonstração/E2E, os E2E e os testes.
_PREFIXOS = ("backend/scripts/seed", "backend/tests/", "apps/web/e2e",
             "apps/web/playwright", "apps/web/src/test/", "apps/quest/src/test/",
             "apps/mobile/src/test/")
# ...e fora dessas pastas: arquivo de teste ao lado do código (packages/core/src/
# cliente.test.ts) e qualquer pasta de mock (apps/web/src/lib/__mocks__/api.ts).
_TESTE_OU_MOCK = re.compile(r"(?:^|/)__mocks__/|\.(?:test|spec)\.[cm]?[jt]sx?$")


def no_alcance(rel: str) -> bool:
    """O arquivo (relativo à raiz) é seed, E2E, teste ou mock — dado fictício."""
    if rel == ESTE_ARQUIVO:
        return False
    return rel.startswith(_PREFIXOS) or _TESTE_OU_MOCK.search(rel) is not None


_TITULOS = re.compile(r"^(?:CIEFI|EMEI/EMEF|EMEFEBS|EMEF)\s+(?:Prof\.ª|Prof\.|Dr\.)?\s*")


_ACENTOS = re.compile(r"[̀-ͯ]")
_NAO_LETRA = re.compile(r"[^A-Z0-9\n]+")


def _normalizar(texto: str) -> str:
    """Caixa alta, sem acento; a quebra de linha fica (o achado diz a linha) e o
    resto que não é letra ou número vira espaço."""
    sem_acento = _ACENTOS.sub("", unicodedata.normalize("NFKD", texto))
    return _NAO_LETRA.sub(" ", sem_acento.upper())


def _detector(nomes: set[str]) -> re.Pattern:
    """Uma regex só para todos os nomes (o mais longo primeiro), palavra inteira, com
    qualquer separador entre as palavras — espaço, pontuação ou quebra de linha."""
    alternativas = ["[^A-Z0-9]+".join(map(re.escape, nome.split()))
                    for nome in sorted(nomes, key=len, reverse=True)]
    return re.compile(r"(?<![A-Z0-9])(?:" + "|".join(alternativas) + r")(?![A-Z0-9])")


def _catalogo(raiz: Path = PROJECT_ROOT) -> list[tuple[str, str]] | None:
    """(nome curto, nome completo) de cada escola do catálogo; ``None`` sem o arquivo
    (ex.: só o backend copiado para uma imagem)."""
    caminho = raiz / CATALOGO
    if not caminho.is_file():
        return None
    texto = caminho.read_text(encoding="utf-8")
    return re.findall(r'\{\s*nome:\s*"([^"]+)",\s*completo:\s*"([^"]+)"\s*\}', texto)


def nomes_reais(catalogo: list[tuple[str, str]]) -> set[str]:
    """Os nomes a procurar: o curto e o do patrono (sem tipo de unidade, título e
    bairro) de cada escola, mais a escola 1."""
    nomes = {ESCOLA_1}
    for curto, completo in catalogo:
        nomes.add(curto)
        patrono = _TITULOS.sub("", completo.split(" — ")[0]).strip()
        nomes.add(patrono)
    return {" ".join(_normalizar(n).split()) for n in nomes if n.strip()}


def achados(texto: str, nomes: set[str] | re.Pattern) -> list[tuple[int, str]]:
    """(linha, nome) de cada nome real encontrado no texto."""
    detector = nomes if isinstance(nomes, re.Pattern) else _detector(nomes)
    normal = _normalizar(texto)
    return [(normal.count("\n", 0, m.start()) + 1, " ".join(m.group().split()))
            for m in detector.finditer(normal)]


def escolas_reais_nos_arquivos(raiz: Path, arquivos: list[str],
                               nomes: set[str] | re.Pattern) -> list[str]:
    """``arquivo:linha (nome)`` de cada nome de escola achado nos arquivos."""
    detector = nomes if isinstance(nomes, re.Pattern) else _detector(nomes)
    encontrados = []
    for rel in arquivos:
        try:
            texto = ler_texto(raiz / rel)
        except OSError:
            continue
        encontrados += [f"{rel}:{linha} ({nome})" for linha, nome in achados(texto, detector)]
    return encontrados


def _catalogo_ou_pula() -> list[tuple[str, str]]:
    catalogo = _catalogo()
    if catalogo is None:
        motivo = f"sem {CATALOGO} em {PROJECT_ROOT}: não há de onde tirar os nomes reais"
        if os.environ.get("CI", "").strip().lower() == "true":
            pytest.fail(motivo)
        pytest.skip(motivo)
    return catalogo


# --- O seed -------------------------------------------------------------------

def test_escola_de_demonstracao_tem_nome_inventado():
    assert "FICTÍCIA" in seed.ESCOLA_DEMO                    # inequívoco: está no nome
    nomes = nomes_reais(_catalogo_ou_pula())
    assert achados(seed.ESCOLA_DEMO, nomes) == []
    for nome in (*seed.DEMO_ALUNOS, *(autor for _, autor, _ in seed.DEMO_LIVROS)):
        assert achados(nome, nomes) == [], nome


def test_seed_cria_a_escola_ficticia_com_admin_e_padroes(db, capsys):
    escola = seed.seed_base(db)

    assert escola.nome == seed.ESCOLA_DEMO
    admin = db.execute(select(Usuario).where(Usuario.email == seed.ADMIN_EMAIL)).scalar_one()
    assert admin.escola_id == escola.id and admin.is_global
    assert db.scalar(select(func.count()).select_from(NivelDificuldade)
                     .where(NivelDificuldade.escola_id == escola.id)) == len(seed.NIVEIS_INICIAIS)
    assert f"Escola {seed.ESCOLA_DEMO} criada" in capsys.readouterr().out


def test_seed_e_idempotente(db, capsys):
    primeira = seed.seed_base(db)
    segunda = seed.seed_base(db)

    assert segunda.id == primeira.id
    assert db.scalar(select(func.count()).select_from(Escola)) == 1
    assert "Seed já executado anteriormente" in capsys.readouterr().out


def test_seed_reaproveita_banco_semeado_quando_a_escola_tinha_outro_nome(db, capsys):
    """Banco de desenvolvimento semeado antes da troca: a escola de demonstração tem o
    nome antigo e o admin inicial já existe. Semear de novo não cria outra escola
    (nem quebra no e-mail único): devolve a escola do admin."""
    antiga = Escola(nome="ESCOLA SEMEADA ANTES DA TROCA", ano_letivo_ativo=seed.ANO_LETIVO)
    db.add(antiga)
    db.flush()
    db.add(Usuario(escola_id=antiga.id, nome="Administrador", email=seed.ADMIN_EMAIL,
                   senha_hash="x", cargo="admin", is_global=True))
    db.commit()

    escola = seed.seed_base(db)

    assert escola.id == antiga.id
    assert db.scalar(select(func.count()).select_from(Escola)) == 1
    assert db.scalar(select(func.count()).select_from(Usuario)) == 1
    assert "Seed já executado anteriormente" in capsys.readouterr().out


def test_seed_recusa_admin_inicial_sem_escola(db):
    db.add(Usuario(escola_id=None, nome="Administrador", email=seed.ADMIN_EMAIL,
                   senha_hash="x", cargo="admin", is_global=True))
    db.commit()

    with pytest.raises(SystemExit, match="sem escola"):
        seed.seed_base(db)
    assert db.scalar(select(func.count()).select_from(Escola)) == 0


# --- A catraca ----------------------------------------------------------------

def test_catalogo_rende_os_nomes_e_o_detector_pega_as_grafias():
    """O detector não passa "vazio": o catálogo rende as escolas da rede, e cada
    nome é achado com acento, em caixa baixa, com título e quebrado em duas linhas."""
    catalogo = _catalogo_ou_pula()
    assert len(catalogo) >= 20                    # a relação tem 27 escolas de 1º–5º
    nomes = nomes_reais(catalogo)
    assert ESCOLA_1 in nomes
    for curto, completo in catalogo:
        assert achados(f'Escola(nome="{completo}")', nomes), completo
        assert achados(curto.lower().replace(" ", "\n  # "), nomes), curto
    assert achados("Caso da EMEF Prof. Jorge\nPassos", nomes) == [(1, ESCOLA_1)]
    # Nome inventado não acusa — nem quando contém um pedaço de nome real.
    for ficticio in ("EMEF FICTÍCIA AURORA", "EMEF Fictícia Bromélia", "Jorgessa Passos",
                     "Ana Beatriz Souza", "EMEI/EMEF ARISTEU FICTÍCIO DO OSÓRIO"):
        assert achados(ficticio, nomes) == [], ficticio


def test_nenhum_nome_de_escola_real_nos_seeds_e2e_e_testes():
    nomes = nomes_reais(_catalogo_ou_pula())
    arquivos, origem = arquivos_a_verificar()
    alvo = [a for a in arquivos if no_alcance(a)]
    if not alvo:
        motivo = f"nenhum seed/E2E/teste para varrer em {PROJECT_ROOT} (origem: {origem})"
        if os.environ.get("CI", "").strip().lower() == "true":
            pytest.fail(motivo)
        pytest.skip(motivo)
    assert "backend/scripts/seed.py" in alvo                    # o seed está no alcance
    # Os testes de packages/core e o mock da API do web, quando presentes, também.
    for rel in ("packages/core/src/cliente.test.ts", "apps/web/src/lib/__mocks__/api.ts"):
        assert rel not in arquivos or rel in alvo, rel

    encontrados = escolas_reais_nos_arquivos(PROJECT_ROOT, alvo, nomes)
    assert not encontrados, (
        f"Nome de escola REAL da rede em dado fictício ({origem}): {encontrados}. "
        "Use um nome inventado e inequívoco (ex.: 'EMEF Fictícia Aurora'); para citar "
        "um caso real, use o número da escola (ex.: 'escola 11').")
