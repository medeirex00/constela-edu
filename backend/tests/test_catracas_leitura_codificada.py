"""Catracas de dado pessoal × codificação do arquivo (e97, integração 5).

A catraca de nome real de PESSOA (``test_sem_nome_real_de_pessoa``), a de nome real de
ESCOLA (``test_seed_ficticio``) e a sentinela de CPF (``test_sem_dado_pessoal_real``)
liam cada arquivo com ``read_text(encoding="utf-8", errors="ignore")``. Três formas
comuns de texto passavam sem aviso:

  * CSV em cp1252 (o padrão do Excel em português): o ``ignore`` apagava a letra
    acentuada e o nome acentuado não batia;
  * "Texto Unicode" do Excel (UTF-16): um NUL entre cada letra, nenhuma palavra nem
    número se formava (nem o nome nem o CPF eram vistos);
  * JSON do ``json.dumps`` padrão: ``\\u00e3`` no lugar do ``ã``.

Agora as três leem com ``ler_texto`` (UTF-16 por BOM ou pela assinatura dos NUL,
UTF-8 estrito, cp1252 com ``replace`` no trecho que não for UTF-8, escapes ``\\uXXXX``
imprimíveis desfeitos), e a de escola alcança também os testes de ``packages/core`` e
os mocks do web. Regressão das provas 3 (pii) e 6 (verif_rd) da integração 5,
invertidas: cada codificação é achada na MESMA linha do controle em UTF-8.

E o leitor novo não pode ficar cego onde o antigo via (revisão do grupo
catracas-quest, seção 5): um NUL solto num arquivo UTF-8 fazia o arquivo inteiro ser
lido como UTF-16 (ideogramas: as três varreduras não achavam nada), e um byte cp1252
colado numa linha UTF-8 fazia a linha inteira ser lida como cp1252 (``ã`` → ``Ã£``).

E antes de ler, a LISTA (integração 6): no checkout git, o ``git ls-files`` citava o
caminho com acento no nome e o arquivo sumia das três sem aviso (seção 6); e a
extensão em maiúsculas (``ALUNOS.CSV``) ficava fora pelo git e pelo disco (seção 7).

Nome, escola e CPF FICTÍCIOS, gerados aqui; tudo em ``tmp_path``.
"""
import inspect
import json
from pathlib import Path

import pytest

from tests import test_sem_dado_pessoal_real as cpf_mod
from tests import test_sem_nome_real_de_pessoa as nome_mod
from tests import test_seed_ficticio as escola_mod
from tests.test_sem_dado_pessoal_real import (_com_verificadores, _formatado, _git, _git_init,
                                              _utf16_sem_bom, arquivos_a_verificar,
                                              cpfs_validos, ler_texto)
from tests.test_sem_nome_real_de_pessoa import _alvos, nomes_reais_nos_arquivos
from tests.test_seed_ficticio import _normalizar, escolas_reais_nos_arquivos, no_alcance

NOME = "Tristão Simulatti Fictelli"           # fictício (o do próprio teste da catraca)
ESCOLA = "Fictícia Aurora"                    # fictícia (a do teste da catraca de escola)
ALVOS = _alvos(NOME)
ESCOLAS = {" ".join(_normalizar(ESCOLA).split())}
CPF = _formatado(_com_verificadores("123456789"))   # verificador válido, montado aqui
LINHA = f"RA;NOME;CPF;ESCOLA\n123;{NOME.upper()};{CPF};EMEF {ESCOLA.upper()}\n"

CODIFICACOES = {
    "utf-8 com BOM": lambda t: t.encode("utf-8-sig"),
    "cp1252 (CSV do Excel)": lambda t: t.encode("cp1252"),
    "latin-1": lambda t: t.encode("latin-1"),
    "utf-16 com BOM (Texto Unicode do Excel)": lambda t: t.encode("utf-16"),
    "utf-16-le sem BOM": lambda t: t.encode("utf-16-le"),
    "utf-16-be sem BOM": lambda t: t.encode("utf-16-be"),
    "utf-32 com BOM": lambda t: t.encode("utf-32"),
    "cp1252 com CRLF": lambda t: t.replace("\n", "\r\n").encode("cp1252"),
}


def _gravar(raiz: Path, rel: str, dados: bytes) -> None:
    destino = raiz / rel
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(dados)


def _varrer(raiz: Path) -> dict[str, list[str]]:
    """O que cada uma das três catracas acha no projeto de mentira (sem o valor)."""
    arquivos, _origem = arquivos_a_verificar(raiz)
    return {
        "nome": sorted(nomes_reais_nos_arquivos(raiz, arquivos, ALVOS)),
        "cpf": sorted(cpfs_validos(raiz, arquivos)),
        "escola": sorted(escolas_reais_nos_arquivos(
            raiz, [a for a in arquivos if no_alcance(a)], ESCOLAS)),
    }


# --- 1. Cada codificação é achada pelas três, na linha do controle UTF-8 ------------

@pytest.mark.parametrize("codificar", list(CODIFICACOES.values()), ids=list(CODIFICACOES))
def test_as_tres_catracas_acham_em_cada_codificacao(tmp_path, codificar):
    _gravar(tmp_path, "backend/tests/controle.csv", LINHA.encode("utf-8"))
    _gravar(tmp_path, "backend/tests/planilha.csv", codificar(LINHA))

    achou = _varrer(tmp_path)

    assert achou["nome"] == ["backend/tests/controle.csv:2", "backend/tests/planilha.csv:2"]
    assert achou["cpf"] == ["backend/tests/controle.csv:2", "backend/tests/planilha.csv:2"]
    assert achou["escola"] == ["backend/tests/controle.csv:2 (FICTICIA AURORA)",
                               "backend/tests/planilha.csv:2 (FICTICIA AURORA)"]


@pytest.mark.parametrize("indent", [None, 2])
def test_json_dumps_padrao_e_achado_na_linha_certa(tmp_path, indent):
    """``json.dumps`` sem ``ensure_ascii=False`` grava o ``ã`` como escape: o nome e a
    escola acentuados eram vistos como ``trist`` + ``u00e3o``."""
    dados = {"nome": NOME, "cpf": CPF, "escola": f"EMEF {ESCOLA}"}
    texto = json.dumps(dados, indent=indent)
    assert "\\u00e3" in texto and "ã" not in texto            # o caso do achado
    _gravar(tmp_path, "apps/web/src/test/fixtures/b.json", texto.encode("ascii"))

    achou = _varrer(tmp_path)

    linha = {None: (1, 1, 1), 2: (2, 3, 4)}[indent]          # nome, cpf, escola
    assert achou["nome"] == [f"apps/web/src/test/fixtures/b.json:{linha[0]}"]
    assert achou["cpf"] == [f"apps/web/src/test/fixtures/b.json:{linha[1]}"]
    assert achou["escola"] == [f"apps/web/src/test/fixtures/b.json:{linha[2]} (FICTICIA AURORA)"]


def test_arquivo_misto_utf8_e_cp1252_le_cada_linha_na_sua(tmp_path):
    """Uma linha colada do Excel (cp1252) num arquivo UTF-8 não estraga as outras."""
    dados = (f"# {NOME}\n".encode("utf-8") + f"# {NOME}\n".encode("cp1252")
             + f"# {NOME}\n".encode("utf-8"))
    _gravar(tmp_path, "backend/tests/misto.py", dados)
    assert _varrer(tmp_path)["nome"] == ["backend/tests/misto.py:1", "backend/tests/misto.py:2",
                                         "backend/tests/misto.py:3"]


# --- 2. O leitor não muda a numeração das linhas -----------------------------------

def test_escape_que_quebraria_linha_ou_e_controle_fica_como_esta(tmp_path):
    bruto = ("a\\u000ab \\u2028 \\u0085 \\u0009 \\ud83d\\ude00\n"
             "Trist\\u00e3o\\u00a0Simulatti Fictelli\n")
    caminho = tmp_path / "x.json"
    caminho.write_text(bruto, encoding="utf-8", newline="\n")

    texto = ler_texto(caminho)

    primeira, segunda = texto.split("\n")[:2]
    assert primeira == "a\\u000ab \\u2028 \\u0085 \\u0009 \\ud83d\\ude00"
    assert segunda == "Tristão Simulatti Fictelli"
    assert len(texto.splitlines()) == len(bruto.splitlines()) == 2
    assert nome_mod.achados(texto, ALVOS) == [2]


def test_utf8_valido_sai_igual_ao_read_text(tmp_path):
    """No texto UTF-8 sem escape (o repositório hoje), nada muda — nem as quebras de
    linha, que o ``read_text`` de antes já traduzia (CRLF e CR sozinho viram LF)."""
    texto = f"x = 1\r\n# {NOME} — ação\rmeio\n\tfim\n"
    caminho = tmp_path / "y.py"
    caminho.write_bytes(texto.encode("utf-8"))
    assert ler_texto(caminho) == caminho.read_text(encoding="utf-8")
    assert ler_texto(caminho) == f"x = 1\n# {NOME} — ação\nmeio\n\tfim\n"


# --- 3. As três varreduras usam o mesmo leitor -------------------------------------

def test_as_tres_varreduras_leem_com_ler_texto():
    for funcao in (nome_mod.nomes_reais_nos_arquivos, cpf_mod.cpfs_validos,
                   escola_mod.escolas_reais_nos_arquivos):
        fonte = inspect.getsource(funcao)
        assert "ler_texto(" in fonte and 'errors="ignore"' not in fonte, funcao.__name__
    for catraca, varredura in (
            (nome_mod.test_nenhum_nome_real_de_pessoa_versionado, "nomes_reais_nos_arquivos("),
            (cpf_mod.test_nenhum_cpf_valido_versionado, "cpfs_validos("),
            (escola_mod.test_nenhum_nome_de_escola_real_nos_seeds_e2e_e_testes,
             "escolas_reais_nos_arquivos(")):
        assert varredura in inspect.getsource(catraca), catraca.__name__


# --- 4. A catraca de escola alcança os testes de pacote e os mocks -----------------

@pytest.mark.parametrize("rel, dentro", [
    ("packages/core/src/cliente.test.ts", True),
    ("packages/core/src/cliente.semDomException.test.ts", True),
    ("apps/web/src/lib/__mocks__/api.ts", True),
    ("apps/quest/src/x.spec.tsx", True),
    ("backend/tests/test_qualquer.py", True),
    ("backend/scripts/seed.py", True),
    ("packages/core/src/cliente.ts", False),                 # código de produto
    ("apps/web/src/lib/api.ts", False),
    ("apps/web/src/pages/Escolas.tsx", False),               # o catálogo
    (escola_mod.ESTE_ARQUIVO, False),                        # a única exceção
])
def test_alcance_da_catraca_de_escola(rel, dentro):
    assert no_alcance(rel) is dentro


def test_catraca_de_escola_acha_nome_em_teste_de_pacote_e_mock(tmp_path):
    linha = f'const escola = {{ nome: "EMEF {ESCOLA}" }};\n'.encode("utf-8")
    for rel in ("packages/core/src/cliente.test.ts", "apps/web/src/lib/__mocks__/api.ts",
                "packages/core/src/cliente.ts"):
        _gravar(tmp_path, rel, linha)
    assert _varrer(tmp_path)["escola"] == [
        "apps/web/src/lib/__mocks__/api.ts:1 (FICTICIA AURORA)",
        "packages/core/src/cliente.test.ts:1 (FICTICIA AURORA)"]


# --- 5. O leitor novo não fica cego onde a leitura antiga via ----------------------
# Revisão do grupo catracas-quest (e97): um NUL solto nos primeiros 4 KiB fazia o
# arquivo UTF-8 INTEIRO ser lido como UTF-16 (nome, CPF e escola viravam ideogramas e
# o arquivo sumia das três varreduras); um byte cp1252 colado numa linha UTF-8 fazia a
# linha inteira ser lida como cp1252 (``ã`` → ``Ã£``). A leitura antiga achava os dois.

DADO = f"123;{NOME};{CPF};EMEF {ESCOLA}".encode("utf-8")
UTF8_COM_BYTE_ESTRANHO = {                       # (bytes, linha em que o dado está)
    "um NUL na linha 1 (o caso da revisao)": (b"id\x00;x\n" + DADO + b"\n", 2),
    "NULs seguidos na linha 1": (b"id;" + b"\x00" * 64 + b"\n" + DADO + b"\n", 2),
    "NUL na linha do dado": (DADO + b";\x00\n", 1),
    "bloco de NUL de preenchimento": (b"\x00" * 2048 + b"\n" + DADO + b"\n", 2),
    "byte cp1252 na linha do dado": (DADO + b";obs \xe9\n", 1),
    "byte cp1252 em outra linha": (b"obs \xe9\n" + DADO + b"\n", 2),
    "byte fora do cp1252 na linha do dado": (DADO + b";\x81\n", 1),
}


@pytest.mark.parametrize("dados, linha", list(UTF8_COM_BYTE_ESTRANHO.values()),
                         ids=list(UTF8_COM_BYTE_ESTRANHO))
def test_utf8_com_nul_ou_byte_cp1252_segue_achado_pelas_tres(tmp_path, dados, linha):
    _gravar(tmp_path, "backend/tests/a.csv", dados)

    assert _varrer(tmp_path) == {
        "nome": [f"backend/tests/a.csv:{linha}"],
        "cpf": [f"backend/tests/a.csv:{linha}"],
        "escola": [f"backend/tests/a.csv:{linha} (FICTICIA AURORA)"],
    }


def test_so_a_assinatura_do_utf16_faz_ler_como_utf16():
    """UTF-16 sem BOM: NUL em pelo menos metade de UMA paridade e quase nenhum na outra.
    NUL solto ou em bloco (cai nas duas paridades) deixa o arquivo como UTF-8."""
    assert _utf16_sem_bom((LINHA * 4).encode("utf-16-le")) == "utf-16-le"
    assert _utf16_sem_bom((LINHA * 4).encode("utf-16-be")) == "utf-16-be"
    assert _utf16_sem_bom((LINHA * 4).encode("utf-8")) is None
    for dados, _linha in UTF8_COM_BYTE_ESTRANHO.values():
        assert _utf16_sem_bom(dados[:4096]) is None


def _leitura_antiga(caminho: Path) -> str:
    return Path(caminho).read_text(encoding="utf-8", errors="ignore")


def test_o_leitor_novo_acha_tudo_o_que_a_leitura_antiga_achava(tmp_path, monkeypatch):
    """Todo achado da leitura antiga (UTF-8 com ``ignore``) segue achado, na mesma
    linha, pelas três: nos casos estranhos acima, em cada codificação e no JSON."""
    estranhos = [dados for dados, _linha in UTF8_COM_BYTE_ESTRANHO.values()]
    casos = estranhos + [codificar(LINHA) for codificar in CODIFICACOES.values()] + [
        json.dumps({"nome": NOME, "cpf": CPF, "escola": f"EMEF {ESCOLA}"},
                   indent=indent).encode("ascii") for indent in (None, 2)]
    for i, dados in enumerate(casos):
        _gravar(tmp_path, f"backend/tests/caso{i:02d}.csv", dados)

    novo = _varrer(tmp_path)
    with monkeypatch.context() as m:
        for modulo in (cpf_mod, nome_mod, escola_mod):
            m.setattr(modulo, "ler_texto", _leitura_antiga)
        antigo = _varrer(tmp_path)

    for catraca in ("nome", "cpf", "escola"):
        assert set(antigo[catraca]) <= set(novo[catraca]), catraca
    # A leitura antiga achava cada caso estranho: é deles que o leitor novo ficava cego.
    assert {f"backend/tests/caso{i:02d}.csv:{linha}"
            for i, (_dados, linha) in enumerate(UTF8_COM_BYTE_ESTRANHO.values())
            } <= set(antigo["nome"]) & set(antigo["cpf"])


# --- 6. No checkout git, o nome do arquivo chega cru às três -----------------------
# e97, integração 6 (catracas-ci): ``git ls-files`` sem ``-z``, com o padrão do git
# ``core.quotePath=true`` (o do runner do CI também), cita entre aspas e com escapes
# octais o caminho que tem byte fora do ASCII: ``"backend/tests/matr\303\255cula
# 2026.csv"``. O filtro de extensão via ``.csv"`` e descartava o arquivo (e ``raiz /
# rel`` nem existiria). No checkout git — o CI e o rodar.sh em WT — as três passavam
# verdes sem ter lido o arquivo; na cópia por git archive (pelo disco), o mesmo arquivo
# era achado. Regressão da prova 1 e da prova 3 da integração 6, invertidas.

CONTROLE = "backend/tests/lista.csv"
COM_ACENTO = {
    "acento no nome": "backend/tests/matrícula 2026.csv",
    "cedilha e til": "backend/tests/relação de alunos.csv",
    "pasta com acento": "backend/tests/relatórios/turma.csv",
}


def _checkout(raiz: Path, rels: list[str]) -> Path:
    """Checkout git de mentira com ``rels`` RASTREADOS, cada um com a ``LINHA``
    fictícia. O ``core.quotePath=true`` é o padrão do git; fica fixado no repositório
    para o teste não depender da configuração global da máquina."""
    raiz.mkdir(parents=True, exist_ok=True)
    _git_init(raiz)
    _git(raiz, "config", "core.quotePath", "true")
    for rel in rels:
        _gravar(raiz, rel, LINHA.encode("utf-8"))
    _git(raiz, "add", "--", *rels)
    return raiz


def _achados_esperados(rels: list[str]) -> dict[str, list[str]]:
    return {"nome": sorted(f"{r}:2" for r in rels),
            "cpf": sorted(f"{r}:2" for r in rels),
            "escola": sorted(f"{r}:2 (FICTICIA AURORA)" for r in rels)}


@pytest.mark.parametrize("rel", list(COM_ACENTO.values()), ids=list(COM_ACENTO))
def test_no_checkout_git_as_tres_acham_o_arquivo_com_acento_no_nome(tmp_path, rel):
    projeto = _checkout(tmp_path / "co", [CONTROLE, rel])
    citado = _git(projeto, "ls-files").splitlines()          # a armadilha está montada
    assert rel not in citado and any(c.startswith('"') for c in citado), citado

    arquivos, origem = arquivos_a_verificar(projeto)

    assert origem == "git ls-files"
    assert sorted(arquivos) == sorted([CONTROLE, rel])
    assert _varrer(projeto) == _achados_esperados([CONTROLE, rel])


def test_no_checkout_git_a_lista_e_a_mesma_da_copia_pelo_disco(tmp_path, monkeypatch):
    """O CI (checkout git) e a cópia por git archive (pelo disco) varrem os MESMOS
    arquivos. Antes o acentuado só estava na lista do disco: a validação local ficava
    vermelha e o portão do main, verde."""
    rels = [CONTROLE, *COM_ACENTO.values()]
    projeto = _checkout(tmp_path / "co", rels)
    pelo_git, origem = arquivos_a_verificar(projeto)
    monkeypatch.setattr(cpf_mod, "_pelo_git", lambda raiz: None)
    pelo_disco, origem_disco = arquivos_a_verificar(projeto)

    assert (origem, origem_disco) == ("git ls-files", "sistema de arquivos")
    assert sorted(pelo_git) == sorted(pelo_disco) == sorted(rels)


# Caracteres que o git cita mesmo com ``core.quotePath=false``: só o ``-z`` entrega o
# nome como é. O Windows não aceita esses caracteres em nome de arquivo; no Linux do CI
# eles são válidos.
CITADO_SEM_Z = {
    "aspas": 'backend/tests/lista "final".csv',
    "tab": "backend/tests/lista\tfinal.csv",
    "quebra de linha": "backend/tests/lista\nfinal.csv",
}


@pytest.mark.parametrize("rel", list(CITADO_SEM_Z.values()), ids=list(CITADO_SEM_Z))
def test_a_lista_do_git_traz_o_nome_cru_mesmo_o_que_o_quotepath_false_cita(tmp_path, rel):
    """A entrada vai só para o índice (``update-index``, sem arquivo no disco): o que se
    confere aqui é a LISTA que sai do git, igual em qualquer sistema."""
    projeto = _checkout(tmp_path / "co", [CONTROLE])
    blob = _git(projeto, "hash-object", "-w", "--", CONTROLE).strip()
    _git(projeto, "-c", "core.protectNTFS=false", "update-index", "--add", "--cacheinfo",
         f"100644,{blob},{rel}")
    assert rel not in _git(projeto, "-c", "core.quotePath=false", "ls-files").splitlines()

    arquivos, origem = arquivos_a_verificar(projeto)

    assert origem == "git ls-files"
    assert sorted(arquivos) == sorted([CONTROLE, rel])


# --- 7. A extensão vale em qualquer caixa ------------------------------------------
# e97, integração 6 (lacuna irmã): ``_EXTENSOES`` está em minúsculas e o filtro
# diferenciava caixa. ``ALUNOS.CSV`` (exportação de sistema) e ``dados.JSON`` ficavam fora
# das três, pelo git E pelo disco. Arquivo que não é texto segue fora em qualquer caixa.

CAIXA_ALTA = ["backend/tests/ALUNOS.CSV", "backend/tests/Turma.Csv",    # nomes distintos de
              "backend/tests/dados.JSON", "backend/tests/NOTAS.TXT"]   # CONTROLE no NTFS
NAO_TEXTO = "backend/tests/FOTO.PNG"


@pytest.mark.parametrize("pelo_git", [True, False], ids=["checkout git", "copia pelo disco"])
def test_extensao_em_maiusculas_e_varrida_pelas_tres(tmp_path, monkeypatch, pelo_git):
    rels = [CONTROLE, *CAIXA_ALTA]
    projeto = tmp_path / "co"
    if pelo_git:
        _checkout(projeto, [*rels, NAO_TEXTO])
    else:
        for rel in (*rels, NAO_TEXTO):
            _gravar(projeto, rel, LINHA.encode("utf-8"))
        monkeypatch.setattr(cpf_mod, "_pelo_git", lambda raiz: None)

    arquivos, origem = arquivos_a_verificar(projeto)

    assert origem == ("git ls-files" if pelo_git else "sistema de arquivos")
    assert sorted(arquivos) == sorted(rels)                 # o .PNG fica fora
    assert _varrer(projeto) == _achados_esperados(rels)
