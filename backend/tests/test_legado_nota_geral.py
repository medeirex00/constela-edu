"""LEGADO ``nota_geral`` — inventário travado + catraca contra novo consumidor.

REGRA (Arquitetura 2, `docs/spec-arquitetura-2.md`; plano de saída em
`docs/plano-retirada-nota-geral.md`):

    ``Nota.nota_geral`` e ``Nota.posicao`` são LEGADO / COMPATIBILIDADE.
    Elas NÃO são fonte oficial de ranking, de premiação nem de qualquer
    decisão de negócio. Continuam sendo GRAVADAS apenas enquanto os
    consumidores ainda não migrados (vitrines, web, mobile, exportações)
    leem o campo. A verdade oficial é o desempenho POR DIMENSÃO:
    ``nota_elefante``/``posicao_leitura`` e ``nota_matific``/
    ``posicao_matematica``, cada uma medida só com dado da SUA plataforma.

Este arquivo é a proteção mecânica dessa regra, em três camadas:

1. INVENTÁRIO (`ALLOWLIST`): a lista EXPLÍCITA dos leitores/escritores
   conhecidos, com o papel de cada um. Um arquivo novo que mencione
   ``nota_geral``, ou uma ocorrência a mais num arquivo já listado, reprova o
   teste — quem for adicionar precisa passar por aqui e declarar o papel.
2. VARREDURA DE DECISÃO: ``nota_geral`` numa linha que ORDENA, PREMIA ou
   COMPARA (``order_by``, ``sort``, ``key=``, ``max``/``min``, ``>``/``<``,
   "premiação"/"certificado"), ou dentro de uma função cujo nome é de
   ordenação/premiação, reprova — a não ser que seja um dos sítios legados já
   inventariados.
3. SABOTAGEM EM TEMPO DE EXECUÇÃO: com ``nota_geral`` embaralhada no banco,
   tudo que é OFICIAL (rankings por dimensão, posições carimbadas, médias da
   escola, alertas, certificado, lista de não aferidos) tem de sair idêntico.
   É a camada que pega o que a varredura estática não vê. O **Top 10** do
   painel fica FORA desse conjunto de propósito: ele ainda é vitrine na ordem
   única, e isso está pinado num teste próprio para não virar surpresa.

A camada 3 é a que decide: se ela falhar, existe dependência real, por mais
limpo que o inventário esteja.
"""
import ast
import pathlib
import re
import tokenize

import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import (
    Aluno,
    Configuracao,
    Escola,
    Importacao,
    Matricula,
    NivelDificuldade,
    Nota,
    ReferenciaNormalizacao,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
    Usuario,
)
from app.services import dimensoes as svc_dimensoes
from app.services import insights as svc_insights
from app.services import scoring

RAIZ_BACKEND = pathlib.Path(__file__).resolve().parents[1]
RAIZ_REPO = RAIZ_BACKEND.parent

# ===========================================================================
# 1) INVENTÁRIO — os leitores/escritores CONHECIDOS e o papel de cada um
# ===========================================================================
# `ocorrencias` conta tokens de CÓDIGO (nomes e chaves de dicionário), nunca
# comentário nem docstring: falar de `nota_geral` numa explicação é livre;
# USAR é que passa por aqui.
#
# `papel`:
#   escrita-legado  — grava a coluna no recálculo (o motor);
#   contrato-api    — devolve o campo num payload para cliente não migrado;
#   ordem-legado    — a ordenação ÚNICA antiga (`Nota.posicao`), ainda usada
#                     pelas vitrines que exigem uma lista só;
#   schema          — declaração de tipo do payload;
#   modelo          — a coluna em si.
#
# `pode_sair` = o que precisa acontecer antes de o consumidor ser removido.

ALLOWLIST: dict[str, dict] = {
    "app/models/nota.py": {
        "ocorrencias": 1, "papel": "modelo",
        "porque": "a coluna. Só some com migração (fase 3 do plano de retirada).",
        "pode_sair": "depois que ninguém mais LÊ e o motor parar de gravar",
    },
    "app/services/scoring.py": {
        "ocorrencias": 8, "papel": "escrita-legado + ordem-legado",
        "porque": ("o motor calcula a composição entre dimensões e grava "
                   "`nota_geral` + `Nota.posicao`. É a ÚNICA conta do sistema "
                   "que cruza dimensões e ela não ordena mais nada oficial."),
        "pode_sair": "quando nenhum leitor funcional restar (gatilho 1 do plano)",
    },
    "app/routers/academico.py": {
        "ocorrencias": 6, "papel": "contrato-api + ordem-legado",
        "porque": ("perfil do aluno e lista da turma devolvem o campo; "
                   "`ordenar=desempenho` (sem dimensão) ainda ordena por ele. "
                   "As opções oficiais são `desempenho_leitura`/"
                   "`desempenho_matematica`."),
        "pode_sair": "quando o web parar de pedir `ordenar=desempenho`",
    },
    "app/routers/rankings.py": {
        "ocorrencias": 4, "papel": "contrato-api",
        "porque": ("dois pontos, ambos PAYLOAD (o campo faz parte do "
                   "`RankingItemOut`), nunca chave de ordem: (1) o Ranking Geral "
                   "LEGADO (sem `?dimensao=`), cuja ordem vem de `Nota.posicao`; "
                   "(2) a competição de leitura POR TURNO (`ranking_leitura_por_"
                   "turno`), cuja ordem vem de `Nota.posicao_leitura` (dimensão), "
                   "não deste valor."),
        "pode_sair": "quando web e mobile só chamarem `?dimensao=`",
    },
    "app/routers/publico.py": {
        "ocorrencias": 4, "papel": "contrato-api",
        "porque": ("telão e perfil público sem login. Trocar o slide muda QUEM "
                   "aparece com nome — decisão de privacidade do dono, não "
                   "conversão mecânica."),
        "pode_sair": "quando o dono aprovar os slides por dimensão como padrão",
    },
    "app/routers/sistema.py": {
        "ocorrencias": 2, "papel": "contrato-api",
        "porque": ("o Simulador reproduz o motor bit a bit; enquanto o motor "
                   "compõe, o simulador mostra a composição (marcada "
                   "`legado: True`), senão ele passaria a mentir."),
        "pode_sair": "junto com a parada de escrita no motor",
    },
    "app/schemas/comum.py": {
        "ocorrencias": 3, "papel": "schema",
        "porque": "declara o campo nos três payloads acima.",
        "pode_sair": "junto com os contratos que o declaram",
    },
    "app/services/evolucao.py": {
        "ocorrencias": 1, "papel": "contrato-api",
        "porque": ("o comparador devolve `notas.geral` (chave histórica) ao "
                   "lado do bloco por dimensão, que é a leitura oficial."),
        "pode_sair": "quando o web ler `dimensoes` no comparador",
    },
    "app/services/relatorios.py": {
        "ocorrencias": 1, "papel": "contrato-api",
        "porque": ("a exportação CSV/PDF do Ranking Geral legado tem a coluna "
                   "'Nota Geral'. `linhas_ranking_dimensao` é a forma nova."),
        "pode_sair": "quando o cartaz/exportação padrão for por dimensão",
    },
}

# Frontend: mesma regra, varredura por linha (sem AST de TS). Arquivos de teste
# entram porque são fixtures do payload legado.
ALLOWLIST_FRONT: dict[str, dict] = {
    "packages/core/src/tipos.ts": {
        "ocorrencias": 3, "papel": "schema",
        "porque": "tipos dos três payloads legados.",
    },
    "apps/web/src/pages/RankingGeral.tsx": {
        "ocorrencias": 1, "papel": "exibição",
        "porque": "coluna 'Nota' da aba Geral (legada). A ordem vem do backend.",
    },
    "apps/web/src/pages/publico/PainelPublico.tsx": {
        "ocorrencias": 4, "papel": "exibição",
        "porque": "slide `ranking` do telão (legado, opt-in do dono).",
    },
    "apps/web/src/pages/publico/PerfilPublico.tsx": {
        "ocorrencias": 1, "papel": "schema",
        "porque": "tipo do perfil público legado.",
    },
    "apps/web/src/test/utils.tsx": {
        "ocorrencias": 2, "papel": "fixture de teste", "porque": "payload falso.",
    },
    "apps/web/src/test/ExplicacaoDaNota.test.tsx": {
        "ocorrencias": 1, "papel": "fixture de teste", "porque": "payload falso.",
    },
    "apps/web/src/test/CompeticaoLeituraTurno.test.tsx": {
        "ocorrencias": 1, "papel": "fixture de teste",
        "porque": ("`RankingItem` fake exige o campo `nota_geral`; o componente "
                   "nem o lê (usa `nota_elefante`)."),
    },
}

# Sítios legados que ORDENAM (ou vivem numa função de ordenação/premiação).
# Qualquer outro par (arquivo, função) flagrado pela varredura reprova.
ORDENACOES_LEGADAS: set[tuple[str, str]] = {
    # A ordem ÚNICA (`Nota.posicao`), ancorada em `nota_geral`. Alimenta as
    # vitrines que exigem uma lista só (Top 10, cartaz, telão).
    ("app/services/scoring.py", "_chave_ordenacao"),
    # `ordenar=desempenho` na lista de alunos da turma — opção legada da tela.
    ("app/routers/academico.py", "_ordem_alunos"),
    # Montagem do item do Ranking Geral legado (a função se chama `_ranking`,
    # o que dispara o vocabulário; o campo aqui é payload, não chave de ordem).
    ("app/routers/rankings.py", "_ranking"),
    # Competição de leitura POR TURNO: o nome contém "ranking" (dispara o
    # vocabulário), mas ordena por `Nota.posicao_leitura` (dimensão) — o
    # `nota_geral` aqui é só o campo do `RankingItemOut`, nunca a chave de ordem.
    ("app/routers/rankings.py", "ranking_leitura_por_turno"),
    # Coluna 'Nota Geral' da exportação legada (idem).
    ("app/services/relatorios.py", "linhas_ranking"),
}

# ---------------------------------------------------------------------------
# O CANAL DE ORDENAÇÃO do legado é `Nota.posicao` — ela É a ordem única
# derivada de `nota_geral`. Quem ordenar por ela está ordenando pela nota
# antiga, mesmo sem escrever `nota_geral` em lugar nenhum. Por isso a coluna
# tem o seu próprio inventário: um consumidor NOVO que faça
# `.order_by(Nota.posicao)` reprova o teste.
#
# A varredura é pelo acesso QUALIFICADO `Nota.posicao` (AST), não pela palavra
# "posicao" — que aparece em dezenas de contextos legítimos (posição da escola
# no painel da rede, posição por dimensão, subconsulta de snapshot atual).
ORDEM_UNICA_LEGADA: dict[tuple[str, str], str] = {
    ("app/routers/rankings.py", "_ranking"):
        "Ranking Geral legado (sem `?dimensao=`) e o Top 10 do painel.",
    ("app/routers/publico.py", "_dados_publicos"):
        "slide `ranking` do telão — trocar muda QUEM aparece com nome sem "
        "login (decisão de privacidade do dono).",
    ("app/routers/publico.py", "_ids_visiveis"):
        "quais perfis públicos podem ser abertos: tem de casar exatamente com "
        "o slide acima, senão abre perfil de quem não está no telão.",
    ("app/services/relatorios.py", "linhas_ranking"):
        "exportação/cartaz do Ranking Geral legado.",
    ("app/services/assistente.py", "montar_contexto"):
        "ACHADO REGISTRADO (risco médio): só a seção `### ALUNOS` do contexto "
        "da IA herda esta ordem. As seções RANKING_LEITURA/RANKING_MATEMATICA "
        "reordenam pela posição DA DIMENSÃO antes de escrever. Trocar por ordem "
        "alfabética é neutro e desejável, mas muda o prompt de uma feature de "
        "IA — item para o dono, não conversão mecânica.",
}

MENSAGEM = (
    "\n\n>>> REGRA: `nota_geral` (e `Nota.posicao`) são LEGADO/compatibilidade.\n"
    ">>> NÃO são fonte oficial de ranking, premiação ou decisão de negócio.\n"
    ">>> A verdade oficial é POR DIMENSÃO: nota_elefante/posicao_leitura e\n"
    ">>> nota_matific/posicao_matematica (só com dado da própria plataforma).\n"
    ">>> Se você precisa mesmo de um número por aluno, use `dimensoes.bloco()`.\n"
    ">>> Para ordenar/premiar, use a posição da DIMENSÃO. Se ainda assim este\n"
    ">>> uso for legítimo (compatibilidade de contrato), declare-o na ALLOWLIST\n"
    ">>> deste arquivo, com papel e critério de saída — e atualize\n"
    ">>> docs/plano-retirada-nota-geral.md.\n"
)

_VOCAB_ORDEM = re.compile(
    r"ordem|ordena|rank|premi|medalha|top|classific|sort|vencedor|destaque|"
    r"cartaz|certificad", re.IGNORECASE)
_PADROES_DECISAO = [
    (r"\.order_by\(", "ORDER BY"),
    (r"\.desc\(\)|\.asc\(\)", "ORDER BY (desc/asc)"),
    (r"\bsorted\(|\.sort\(", "sort/sorted"),
    (r"\bkey\s*=", "chave de ordenação"),
    (r"\bmax\(|\bmin\(|nlargest|nsmallest", "máximo/mínimo"),
    (r"nota_geral\s*(>=|<=|>|<)|(>=|<=|>|<)\s*[\w.\[\]\"']*nota_geral",
     "comparação de valor"),
    (r"premi|medalha|certificad|vencedor", "premiação"),
]

# Construções que ORDENAM/ESCOLHEM na própria linha. Usado pelo braço (b) da
# varredura de `.posicao` (ver `test_ninguem_novo_ordena_pela_ordem_unica_legada`):
# é o que transforma um acesso qualquer ao atributo em uso da ORDEM ÚNICA.
_ORDENA_NA_LINHA = re.compile(
    r"\.order_by\(|\bsorted\(|\.sort\(|\bkey\s*=|\bmax\(|\bmin\(|"
    r"nlargest|nsmallest|premi|medalha|vencedor")


def _linhas_com_nota_geral(caminho: pathlib.Path) -> set[int]:
    """Linhas com um token de CÓDIGO ``nota_geral`` (nome ou chave de dict).

    Usa `tokenize` de propósito: comentário e docstring ficam de fora, então
    documentar o legado (que este projeto faz bastante) nunca reprova o teste."""
    linhas: set[int] = set()
    with tokenize.open(caminho) as arquivo:
        for token in tokenize.generate_tokens(arquivo.readline):
            if token.type == tokenize.NAME and token.string == "nota_geral":
                linhas.add(token.start[0])
            elif (token.type == tokenize.STRING
                  and token.string.strip() in ('"nota_geral"', "'nota_geral'")):
                linhas.add(token.start[0])
    return linhas


def _ocorrencias_backend() -> dict[str, int]:
    achados: dict[str, int] = {}
    for caminho in sorted((RAIZ_BACKEND / "app").rglob("*.py")):
        total = 0
        with tokenize.open(caminho) as arquivo:
            for token in tokenize.generate_tokens(arquivo.readline):
                if token.type == tokenize.NAME and token.string == "nota_geral":
                    total += 1
                elif (token.type == tokenize.STRING
                      and token.string.strip() in ('"nota_geral"', "'nota_geral'")):
                    total += 1
        if total:
            achados[caminho.relative_to(RAIZ_BACKEND).as_posix()] = total
    return achados


def test_inventario_do_backend_esta_travado():
    """Nenhum arquivo novo, e nenhuma ocorrência a mais, sem passar por aqui."""
    achados = _ocorrencias_backend()
    novos = sorted(set(achados) - set(ALLOWLIST))
    assert not novos, (
        f"arquivo(s) NOVO(S) usando `nota_geral`: {novos}." + MENSAGEM)

    cresceu = {a: (ALLOWLIST[a]["ocorrencias"], n)
               for a, n in achados.items()
               if n > ALLOWLIST[a]["ocorrencias"]}
    assert not cresceu, (
        f"usos NOVOS de `nota_geral` em arquivo já conhecido "
        f"(esperado, encontrado): {cresceu}." + MENSAGEM)

    # Encolher é bom (é migração acontecendo) — mas o inventário precisa
    # acompanhar, senão a catraca afrouxa em silêncio.
    encolheu = {a: (m["ocorrencias"], achados.get(a, 0))
                for a, m in ALLOWLIST.items()
                if achados.get(a, 0) < m["ocorrencias"]}
    assert not encolheu, (
        f"`nota_geral` foi REMOVIDA de {sorted(encolheu)} — ótimo. Atualize a "
        f"ALLOWLIST (esperado, encontrado): {encolheu}, e registre o avanço em "
        f"docs/plano-retirada-nota-geral.md.")


def test_todo_item_da_allowlist_declara_papel_e_criterio_de_saida():
    """A allowlist não pode virar um depósito: cada entrada explica POR QUE
    ainda existe e O QUE precisa acontecer para sair."""
    for arquivo, meta in ALLOWLIST.items():
        assert meta.get("papel"), f"{arquivo}: falta `papel`"
        assert len(meta.get("porque", "")) > 30, f"{arquivo}: falta `porque`"
        assert meta.get("pode_sair"), f"{arquivo}: falta `pode_sair`"


def test_nenhum_uso_novo_de_nota_geral_para_ordenar_premiar_ou_decidir():
    """A camada que pega o risco de verdade: ``nota_geral`` voltando a ORDENAR.

    Flagra a ocorrência quando (a) a linha tem construção de ordenação/
    comparação/premiação, ou (b) ela vive numa função cujo nome é de
    ordenação/premiação. Os sítios legados conhecidos estão em
    ``ORDENACOES_LEGADAS``; qualquer outro reprova."""
    suspeitos = []
    for caminho in sorted((RAIZ_BACKEND / "app").rglob("*.py")):
        fonte = caminho.read_text(encoding="utf-8")
        if "nota_geral" not in fonte:
            continue
        relativo = caminho.relative_to(RAIZ_BACKEND).as_posix()
        escopo: dict[int, str] = {}
        for no in ast.walk(ast.parse(fonte)):
            if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for linha in range(no.lineno, (no.end_lineno or no.lineno) + 1):
                    escopo.setdefault(linha, no.name)
        texto = fonte.splitlines()
        for numero in sorted(_linhas_com_nota_geral(caminho)):
            funcao = escopo.get(numero, "<módulo>")
            linha = texto[numero - 1].strip()
            marcas = [rotulo for padrao, rotulo in _PADROES_DECISAO
                      if re.search(padrao, linha)]
            if not marcas and not _VOCAB_ORDEM.search(funcao):
                continue
            if (relativo, funcao) in ORDENACOES_LEGADAS:
                continue
            suspeitos.append(f"{relativo}:{numero} em {funcao}() "
                             f"[{', '.join(marcas) or 'nome da função'}] :: {linha}")
    assert not suspeitos, (
        "`nota_geral` apareceu num caminho de ORDENAÇÃO/PREMIAÇÃO/DECISÃO "
        "novo:\n  - " + "\n  - ".join(suspeitos) + MENSAGEM)


def test_ninguem_novo_ordena_pela_ordem_unica_legada():
    """A OUTRA porta de entrada, e a mais fácil de atravessar sem perceber:
    a ORDEM ÚNICA (``Nota.posicao``).

    Quem faz ``.order_by(Nota.posicao)`` está ordenando por ``nota_geral`` —
    a coluna É a ordem única derivada dela — sem escrever `nota_geral` em
    lugar nenhum, então a varredura anterior não pegaria. Este teste inventaria
    esse consumo por (arquivo, função), e NÃO pela grafia exata ``Nota.posicao``:
    a mesma ordem chega por aliás (``from app.models import Nota as N``), por
    módulo (``models.Nota.posicao``) ou já em Python, sobre a instância
    (``sorted(notas, key=lambda n: n.posicao)``). Todas essas formas são o
    mesmo canal e todas reprovam.

    Por isso a varredura tem dois braços:
      (a) o acesso QUALIFICADO ``Nota.posicao`` (AST), em qualquer contexto; e
      (b) QUALQUER acesso ao atributo ``.posicao`` numa linha que ORDENE ou
          PREMIE (``order_by``/``sorted``/``sort``/``key=``/``max``/``min``),
          seja qual for o objeto — inclusive ``item["posicao"]``.
    O braço (b) é largo de propósito e custa zero ruído: hoje ele acende
    exatamente nos 5 sítios legados já inventariados. `posicao_leitura` e
    `posicao_matematica` (as oficiais) são atributos DIFERENTES e não entram."""
    achados: set[tuple[str, str]] = set()
    for caminho in sorted((RAIZ_BACKEND / "app").rglob("*.py")):
        fonte = caminho.read_text(encoding="utf-8")
        if "posicao" not in fonte:
            continue
        relativo = caminho.relative_to(RAIZ_BACKEND).as_posix()
        arvore = ast.parse(fonte)
        texto = fonte.splitlines()
        escopo: dict[int, str] = {}
        for no in ast.walk(arvore):
            if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for linha in range(no.lineno, (no.end_lineno or no.lineno) + 1):
                    escopo.setdefault(linha, no.name)
        for no in ast.walk(arvore):
            # (a) `Nota.posicao` — a grafia canônica, em qualquer contexto.
            qualificado = (
                isinstance(no, ast.Attribute) and no.attr == "posicao"
                and isinstance(no.value, ast.Name) and no.value.id == "Nota")
            # (b) qualquer `.posicao` / `["posicao"]` numa linha de ordenação.
            atributo = isinstance(no, ast.Attribute) and no.attr == "posicao"
            chave = (isinstance(no, ast.Subscript)
                     and isinstance(no.slice, ast.Constant)
                     and no.slice.value == "posicao")
            if not (qualificado or atributo or chave):
                continue
            linha = texto[no.lineno - 1].strip()
            if not qualificado and not _ORDENA_NA_LINHA.search(linha):
                continue
            achados.add((relativo, escopo.get(no.lineno, "<módulo>")))

    novos = sorted(achados - set(ORDEM_UNICA_LEGADA))
    assert not novos, (
        f"consumidor NOVO da ordem única legada (`Nota.posicao`): {novos}."
        + MENSAGEM)
    sumiram = sorted(set(ORDEM_UNICA_LEGADA) - achados)
    assert not sumiram, (
        f"{sumiram} deixaram de usar `Nota.posicao` — ótimo. Remova-os de "
        f"ORDEM_UNICA_LEGADA e registre o avanço em "
        f"docs/plano-retirada-nota-geral.md.")


def test_inventario_do_frontend_esta_travado():
    """Mesma catraca no web/mobile: um `nota_geral` novo numa tela reprova."""
    if not (RAIZ_REPO / "packages").exists():
        pytest.skip("repositório sem o frontend (backend isolado)")
    padrao = re.compile(r"\b(nota_geral|notaGeral)\b")
    achados: dict[str, int] = {}
    for base in ("apps", "packages"):
        for caminho in sorted((RAIZ_REPO / base).rglob("*")):
            if (caminho.suffix not in (".ts", ".tsx")
                    or "node_modules" in caminho.parts):
                continue
            total = sum(
                1 for linha in caminho.read_text(encoding="utf-8",
                                                 errors="ignore").splitlines()
                if padrao.search(linha)
                and not linha.strip().startswith(("//", "*", "/*")))
            if total:
                achados[caminho.relative_to(RAIZ_REPO).as_posix()] = total

    novos = sorted(set(achados) - set(ALLOWLIST_FRONT))
    assert not novos, (
        f"arquivo(s) NOVO(S) do frontend usando `nota_geral`: {novos}."
        + MENSAGEM)
    divergentes = {a: (ALLOWLIST_FRONT[a]["ocorrencias"], n)
                   for a, n in achados.items()
                   if n != ALLOWLIST_FRONT[a]["ocorrencias"]}
    assert not divergentes, (
        f"o número de usos mudou no frontend (esperado, encontrado): "
        f"{divergentes}." + MENSAGEM)


# ===========================================================================
# 3) SABOTAGEM EM TEMPO DE EXECUÇÃO — a camada que decide
# ===========================================================================

LEITOR = {"livros_unicos": 30, "tempo_leitura_min": 600,
          "questoes_tentativas": 100, "questoes_acertos": 90,
          "livros_por_nivel": {"D": 30}}
LEITOR_FRACO = {"livros_unicos": 4, "tempo_leitura_min": 60,
                "questoes_tentativas": 20, "questoes_acertos": 10,
                "livros_por_nivel": {"D": 4}}
MATIFIC_TOPO = {"atividades": 100, "pontuacao_media": 5.0, "estrelas": 300}
MATIFIC_FRACO = {"atividades": 10, "pontuacao_media": 2.0, "estrelas": 20}


@pytest.fixture()
def escola_mista(db):
    """Escola com as quatro situações que a arquitetura distingue: usa as duas,
    usa só uma, usa só a outra, não usa nenhuma."""
    escola = Escola(nome="EM LEGADO", ano_letivo_ativo=2026, status="ativa")
    db.add(escola)
    db.flush()
    for namespace, valores in scoring.PESOS_PADRAO.items():
        db.add(Configuracao(escola_id=escola.id, namespace=namespace,
                            chave="valores", valor=valores))
    db.add(NivelDificuldade(escola_id=escola.id, nome="Nível 2", codigo="nivel_2",
                            codigos=["D", "E"], pontos_padrao=4.0, ordem=1))
    db.add(ReferenciaNormalizacao(escola_id=escola.id, modo="auto"))
    turma = Turma(escola_id=escola.id, nome="4ºA", ano_escolar="4º Ano",
                  ano_letivo=2026, status="ativa")
    db.add(turma)
    db.add(Usuario(escola_id=escola.id, nome="Gestora",
                   email="gestora@legado.local",
                   senha_hash=hash_senha("s3nh4gestora"), cargo="coordenador"))
    db.flush()
    imp = Importacao(escola_id=escola.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()

    def _aluno(nome, elefante=None, matific=None):
        aluno = Aluno(escola_id=escola.id, nome=nome, status="ativo")
        db.add(aluno)
        db.flush()
        db.add(Matricula(escola_id=escola.id, aluno_id=aluno.id,
                         turma_id=turma.id, ano_letivo=2026))
        if elefante is not None:
            db.add(SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id,
                                    importacao_id=imp.id, **elefante))
        if matific is not None:
            db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id,
                                   importacao_id=imp.id, **matific))
        return aluno

    alunos = {
        "duas": _aluno("Usa As Duas", dict(LEITOR_FRACO), dict(MATIFIC_TOPO)),
        "so_le": _aluno("So Leitura", dict(LEITOR)),
        "so_conta": _aluno("So Conta", None, dict(MATIFIC_FRACO)),
        "nenhuma": _aluno("Nenhuma Plataforma"),
    }
    db.commit()
    scoring.recalcular_escola(db, escola.id)
    return escola, alunos


def _logar():
    cliente = TestClient(app)
    resposta = cliente.post("/api/v1/auth/login",
                            data={"username": "gestora@legado.local",
                                  "password": "s3nh4gestora"})
    assert resposta.status_code == 200, resposta.text
    cliente.headers["Authorization"] = f"Bearer {resposta.json()['access_token']}"
    return cliente


def _oficial(db, cliente, escola):
    """Tudo que é OFICIAL na visão da ESCOLA — nada disso pode depender do
    legado."""
    def _rk(dimensao):
        r = cliente.get(f"/api/v1/escolas/{escola.id}/ranking?dimensao={dimensao}")
        assert r.status_code == 200, r.text
        return [(i["aluno_id"], i["posicao"], i["nota"]) for i in r.json()]

    resposta = cliente.get(f"/api/v1/escolas/{escola.id}/dashboard")
    assert resposta.status_code == 200, resposta.text
    painel = resposta.json()
    # Sem isto, uma rota que passasse a 404 devolveria `None` nos dois lados da
    # comparação e a sabotagem "passaria" sem provar nada.
    assert painel["media_leitura"] and painel["media_matematica"], (
        "o painel veio sem média por dimensão — o comparativo ficaria vazio")
    resposta = cliente.get(f"/api/v1/escolas/{escola.id}/nao-aferidos")
    assert resposta.status_code == 200, resposta.text
    nao_aferidos = resposta.json()
    notas = {n.aluno_id: n for n in db.query(Nota)
             .filter(Nota.escola_id == escola.id).all()}
    alertas = svc_insights.alertas_da_escola(db, escola.id)
    return {
        "ranking_leitura": _rk("leitura"),
        "ranking_matematica": _rk("matematica"),
        "colunas": {aid: (n.nota_elefante, n.nota_matific, n.posicao_leitura,
                          n.posicao_matematica, n.aferido_leitura,
                          n.aferido_matematica)
                    for aid, n in notas.items()},
        "media_leitura": painel["media_leitura"],
        "media_matematica": painel["media_matematica"],
        "media_geral": painel["media_geral"],
        "nao_aferidos": [
            (d["dimensao"], sorted(a["aluno_id"] for a in d["alunos"]))
            for d in nao_aferidos["dimensoes"]],
        "alertas": sorted(
            (a.get("tipo"), a.get("aluno_id"), a.get("dimensao") or "")
            for a in alertas),
        "certificaveis": sorted(
            aid for aid, n in notas.items()
            if svc_dimensoes.com_desempenho(db, escola, n)),
    }


SABOTAGENS = {
    "nota_geral invertida": lambda i, n: setattr(n, "nota_geral", 100.0 - i),
    "nota_geral zerada": lambda i, n: setattr(n, "nota_geral", 0.0),
    "nota_geral no teto": lambda i, n: setattr(n, "nota_geral", 100.0),
    "posicao legada invertida": lambda i, n: setattr(n, "posicao", 9_000 - i),
    "as duas juntas": lambda i, n: (setattr(n, "nota_geral", 100.0 - i),
                                    setattr(n, "posicao", 9_000 - i)),
}


@pytest.mark.parametrize("nome_sabotagem", list(SABOTAGENS))
def test_a_visao_oficial_da_escola_nao_muda_com_o_legado_adulterado(
        db, escola_mista, nome_sabotagem):
    """Se qualquer ranking, alerta, média ou certificado ainda consumisse
    `nota_geral`/`Nota.posicao`, alguma coisa mudaria aqui."""
    escola, _ = escola_mista
    cliente = _logar()
    antes = _oficial(db, cliente, escola)
    assert antes["ranking_leitura"] and antes["ranking_matematica"], (
        "cenário sem sinal: os rankings por dimensão vieram vazios")

    sabotar = SABOTAGENS[nome_sabotagem]
    for indice, nota in enumerate(db.query(Nota).all()):
        sabotar(indice, nota)
    db.commit()

    depois = _oficial(db, cliente, escola)
    for chave in antes:
        assert depois[chave] == antes[chave], (
            f"[{nome_sabotagem}] '{chave}' mudou ao adulterar o legado — "
            f"logo ele ainda é consumido." + MENSAGEM)


def test_o_top10_do_painel_AINDA_segue_a_ordem_legada(db, escola_mista):
    """ACHADO REGISTRADO, não corrigido: o Top 10 do painel da escola continua
    saindo da ordem ÚNICA (`Nota.posicao`), e não das ordens por dimensão.

    Está assim de propósito (`rankings.py`, comentário do `top10`): virar
    "Top N por dimensão" muda QUEM sobe ao pódio em toda escola mista, o que é
    decisão de produto do dono — não conversão mecânica. Este teste existe para
    que o fato fique VISÍVEL: é o consumidor legado de maior risco de ser
    confundido com fonte oficial, porque é vitrine (pódio, cartaz, telão).

    Quando o dono decidir, este teste é o primeiro a cair — e a queda dele é o
    sinal de que o item 7 do `docs/plano-retirada-nota-geral.md` andou."""
    escola, _ = escola_mista
    cliente = _logar()
    painel = cliente.get(f"/api/v1/escolas/{escola.id}/dashboard").json()
    top10 = [(i["aluno_id"], i["posicao"]) for i in painel["top10"]]

    notas = {n.aluno_id: n for n in db.query(Nota)
             .filter(Nota.escola_id == escola.id).all()}
    esperado = sorted(notas, key=lambda aid: notas[aid].posicao)[:10]
    assert [aid for aid, _pos in top10] == esperado, (
        "o Top 10 mudou de critério — se foi para a ordem POR DIMENSÃO, "
        "atualize este teste e o item 7 do plano de retirada")


def test_o_legado_continua_sendo_gravado_e_marcado_como_legado(db, escola_mista):
    """A outra metade da catraca: enquanto o plano de retirada não chegar ao
    gatilho de PARADA DE ESCRITA, `nota_geral` tem de continuar sendo gravada —
    e carimbada como legado — senão os clientes não migrados quebram em
    silêncio."""
    escola, alunos = escola_mista
    nota = db.query(Nota).filter(Nota.aluno_id == alunos["duas"].id).one()
    assert nota.nota_geral > 0, "o motor parou de gravar `nota_geral`"
    assert nota.posicao is not None, "o motor parou de gravar `Nota.posicao`"
    assert nota.detalhes["geral"]["legado"] is True, (
        "o carimbo `detalhes.geral.legado` sumiu — é ele que avisa a quem lê "
        "que aquele número não é oficial")
    assert nota.detalhes["composicao"] == scoring.COMPOSICAO_ATUAL


def test_as_tres_ordens_do_cenario_sao_de_fato_diferentes(db, escola_mista):
    """Sanidade do próprio cenário: se as ordens coincidissem, a sabotagem acima
    não distinguiria nada.

    Aqui a criança que só lê é 1ª em LEITURA; a que usa as duas é 1ª em
    MATEMÁTICA; e a ordem ÚNICA legada é uma terceira lista, que inclui até quem
    não é aferido em dimensão nenhuma (com `nota_geral = 0`)."""
    escola, alunos = escola_mista
    notas = {n.aluno_id: n for n in db.query(Nota)
             .filter(Nota.escola_id == escola.id).all()}
    assert notas[alunos["so_le"].id].posicao_leitura == 1
    assert notas[alunos["duas"].id].posicao_matematica == 1
    assert notas[alunos["so_conta"].id].posicao_matematica == 2
    # Sem snapshot da dimensão: fora da ordenação dela (e nunca com zero).
    assert notas[alunos["nenhuma"].id].posicao_leitura is None
    assert notas[alunos["nenhuma"].id].posicao_matematica is None

    por_leitura = sorted((aid for aid, n in notas.items() if n.aferido_leitura),
                         key=lambda aid: notas[aid].posicao_leitura)
    por_matematica = sorted(
        (aid for aid, n in notas.items() if n.aferido_matematica),
        key=lambda aid: notas[aid].posicao_matematica)
    ordem_legada = sorted(notas, key=lambda aid: notas[aid].posicao)

    assert por_leitura != por_matematica, (
        "as duas dimensões produziram a MESMA ordem — o cenário deixou de "
        "distinguir matérias e a sabotagem vira decorativa")
    assert ordem_legada != por_matematica, (
        "a ordem única legada coincidiu com a de matemática — o cenário parou "
        "de separar o legado do oficial")
    # A ordem legada carrega quem não é aferido em NADA; as oficiais, não.
    assert alunos["nenhuma"].id in ordem_legada
    assert alunos["nenhuma"].id not in por_leitura
    assert alunos["nenhuma"].id not in por_matematica
