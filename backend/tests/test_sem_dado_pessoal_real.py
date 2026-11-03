"""Sentinela: nenhum CPF válido nos arquivos versionados do repositório.

Em 20/10/2026 a varredura do repositório (público) achou, em testes, linhas da Lista
Piloto copiadas da planilha real — com CPF, telefone e SUS de crianças. Os dados foram
trocados por fictícios; esta trava impede que um CPF de verdade volte por cópia de
planilha. Fictício aqui é CPF com dígito verificador ERRADO por construção.

O que conta como CPF: o formato ``000.000.000-00`` em qualquer linha, ou 11 dígitos
seguidos numa linha que fala de CPF. Só reprova se os dígitos verificadores baterem.
Nomes reais não dá para conferir aqui (a lista real não pode entrar no repositório):
isso fica para a conferência local contra as Listas Piloto, fora do CI.

De onde vêm os arquivos: num checkout real (o topo do git É a raiz do projeto e
``git ls-files`` lista arquivos), os versionados. Fora disso — cópia por ``git
archive`` dentro de outra pasta que é repositório (a pasta pessoal desta máquina é
um), ou sem git —, o ``ls-files`` devolvia ZERO arquivos e a sentinela passava sem
verificar nada (e97, A3 "Achado novo"). Agora ela varre o sistema de arquivos; se
nem assim houver o que verificar, pula com o motivo — e no CI (``CI=true``) FALHA.

O nome do arquivo é lido CRU do git: ``git -c core.quotePath=false ls-files -z``,
separado por NUL. Sem isso, o padrão do git (``core.quotePath=true``, o do runner do
CI também) cita entre aspas e com escapes octais todo caminho com byte fora do ASCII
(``"backend/tests/matr\\303\\255cula.csv"``): o filtro de extensão via ``.csv"``, o
arquivo versionado com acento no nome sumia das três catracas sem aviso, e o CI e o
worktree davam verde onde a cópia por ``git archive`` (pelo disco) dava vermelho (e97,
integração 6). O ``-z`` entrega cru também o nome com aspas, tab ou quebra de linha,
que o ``quotePath=false`` sozinho ainda citaria. Arquivo listado que não se consegue
ler (``OSError``: rastreado mas ausente do disco, como num checkout esparso) segue
pulado. A extensão de texto vale em qualquer caixa (``ALUNOS.CSV``, ``dados.JSON``):
antes, pelo git e pelo disco, o filtro diferenciava caixa e esses ficavam fora.

Como cada arquivo é lido (``ler_texto``, o mesmo das catracas de nome real de pessoa e
de escola): texto em UTF-8, UTF-16 ou cp1252, com os escapes ``\\uXXXX`` do JSON
desfeitos. A leitura antiga (UTF-8 com ``errors="ignore"``) apagava a letra acentuada
do CSV que o Excel grava em cp1252, não formava palavra nem número no "Texto Unicode"
(UTF-16, um NUL entre cada letra) e via ``trist`` + ``u00e3o`` no ``json.dumps``
padrão: o nome e o CPF passavam sem aviso (e97, integração 5).
"""
import codecs
import os
import re
import subprocess
from pathlib import Path

import pytest

from app.core.config import PROJECT_ROOT

_FORMATADO = re.compile(r"(?<![\d.])(\d{3})\.(\d{3})\.(\d{3})-(\d{2})(?![\d-])")
_CRU = re.compile(r"(?<!\d)(\d{11})(?!\d)")
_EXTENSOES = {".py", ".ts", ".tsx", ".js", ".mjs", ".json", ".md", ".txt", ".yml", ".yaml",
              ".csv", ".html", ".sql", ".sh"}


def cpf_valido(digitos: str) -> bool:
    if len(digitos) != 11 or len(set(digitos)) == 1:
        return False
    for n in (9, 10):
        resto = (sum(int(digitos[i]) * (n + 1 - i) for i in range(n)) * 10) % 11 % 10
        if resto != int(digitos[n]):
            return False
    return True


# Pastas que a varredura pelo sistema de arquivos pula: dependências, caches, saídas
# geradas e os dados locais que o .gitignore deixa fora (uploads, exports, database —
# delas só o .gitkeep é versionado).
_PASTAS_FORA = {".git", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache",
                ".ruff_cache", ".mypy_cache", "htmlcov", "coverage", "dist", "build", ".expo",
                "playwright-report", "test-results", "blob-report", ".auth", "target",
                "uploads", "exports", "database", "matific_captura", "elefante_captura"}


def _git(raiz: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "core.longpaths=true", "-C", str(raiz), *args],
                          capture_output=True, text=True, encoding="utf-8",
                          check=True).stdout


def _pelo_git(raiz: Path) -> list[str] | None:
    """Os arquivos versionados, quando ``raiz`` é o TOPO de um checkout git que lista
    arquivos; ``None`` quando não é (sem git, outra pasta é o topo, ou lista vazia).

    O nome de cada arquivo sai CRU: ``-z`` (separado por NUL, sem aspas nem escape) e
    ``core.quotePath=false`` explícito. Os bytes do git viram texto como o sistema de
    arquivos os lê (``os.fsdecode``), para ``raiz / rel`` reabrir o mesmo arquivo."""
    try:
        topo = _git(raiz, "rev-parse", "--show-toplevel").strip()
        if not topo or Path(topo).resolve() != Path(raiz).resolve():
            return None
        saida = subprocess.run(
            ["git", "-c", "core.longpaths=true", "-c", "core.quotePath=false", "-C", str(raiz),
             "ls-files", "-z"], capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    arquivos = [os.fsdecode(nome) for nome in saida.split(b"\0") if nome]
    return arquivos or None


def _pelo_disco(raiz: Path) -> list[str]:
    # A raiz do sistema de arquivos não é o projeto (ex.: backend instalado na raiz de
    # uma imagem, PROJECT_ROOT='/'): varrê-la percorreria o disco inteiro sem dizer
    # nada sobre o repositório. Lista vazia — a sentinela pula com o motivo e, no
    # CI, falha.
    resolvida = Path(raiz).resolve()
    if resolvida == Path(resolvida.anchor):
        return []
    arquivos = []
    for pasta, subpastas, nomes in os.walk(raiz):
        subpastas[:] = [s for s in subpastas if s not in _PASTAS_FORA]
        arquivos += [Path(pasta, nome).relative_to(raiz).as_posix() for nome in nomes]
    return arquivos


def arquivos_a_verificar(raiz: Path = PROJECT_ROOT) -> tuple[list[str], str]:
    """(arquivos relativos a ``raiz`` com extensão de texto, origem da lista).

    A extensão é conferida sem diferenciar caixa: ``ALUNOS.CSV`` é texto como
    ``alunos.csv``."""
    arquivos, origem = _pelo_git(raiz), "git ls-files"
    if arquivos is None:
        arquivos, origem = _pelo_disco(raiz), "sistema de arquivos"
    return ([a for a in arquivos if "node_modules" not in a
             and any(a.lower().endswith(e) for e in _EXTENSOES)], origem)


def _exigir_o_que_verificar(arquivos: list[str], origem: str, raiz: Path) -> None:
    """Nada para verificar NÃO é aprovação: pula com o motivo; no CI, falha."""
    if arquivos:
        return
    motivo = (f"sentinela de CPF sem nenhum arquivo para verificar em {raiz} "
              f"(origem: {origem})")
    if os.environ.get("CI", "").strip().lower() == "true":
        pytest.fail(motivo)
    pytest.skip(motivo)


_ESCAPE_U = re.compile(r"\\u([0-9a-fA-F]{4})")
_AMOSTRA = 4096          # bytes olhados atrás da assinatura do UTF-16 sem BOM


def _desfazer_escape(m: re.Match) -> str:
    """``\\uXXXX`` vira o caractere quando ele é imprimível e não quebra linha (a
    numeração das linhas, que o achado informa, não muda). Controle, separador de
    linha (U+0085, U+2028...) e metade de par substituto ficam como estão."""
    codigo = int(m[1], 16)
    caractere = chr(codigo)
    if codigo < 0x20 or 0xD800 <= codigo <= 0xDFFF or len(f"a{caractere}b".splitlines()) != 1:
        return m[0]
    return caractere


def _utf16_sem_bom(amostra: bytes) -> str | None:
    """``"utf-16-le"``/``"utf-16-be"`` quando a amostra tem a assinatura de texto
    latino em UTF-16 sem BOM; ``None`` senão.

    Nesse texto cada letra ocupa dois bytes e um deles é NUL: os NUL enchem UMA das
    paridades (os bytes ímpares no LE, os pares no BE) e quase não caem na outra.
    Exige-se NUL em pelo menos metade dos bytes de uma paridade (um quarto da amostra)
    e, na outra, no máximo um quarto disso. Um NUL solto num arquivo UTF-8, ou um
    bloco de NUL de preenchimento (cai nas duas paridades), não basta: o arquivo segue
    como UTF-8, igual ao ``read_text`` de antes. Lido como UTF-16 ele viraria
    ideogramas e sumiria das três varreduras sem aviso (e97, revisão do grupo
    catracas-quest)."""
    par, impar = amostra[0::2].count(0), amostra[1::2].count(0)
    maior, menor = max(par, impar), min(par, impar)
    if maior == 0 or maior * 4 < len(amostra) or menor * 4 > maior:
        return None
    return "utf-16-be" if par > impar else "utf-16-le"


def _cp1252_no_trecho_invalido(erro: UnicodeDecodeError) -> tuple[str, int]:
    """Tratador de erro do UTF-8: só o trecho que não é UTF-8 é lido como cp1252."""
    return erro.object[erro.start:erro.end].decode("cp1252", errors="replace"), erro.end


codecs.register_error("catraca_cp1252", _cp1252_no_trecho_invalido)


def _utf8_ou_cp1252(dados: bytes) -> str:
    """UTF-8 estrito; o trecho que não for UTF-8 — e só ele — é lido como cp1252 (o
    CSV do Excel em português) com ``replace``. Um byte cp1252 colado numa linha em
    UTF-8 não estraga o resto dela: ler a linha inteira como cp1252 trocava o ``ã``
    do UTF-8 por ``Ã£`` e o nome que a leitura antiga (``ignore``) achava sumia. O
    decodificador do UTF-8 nunca põe byte ASCII no trecho inválido e o cp1252 não tem
    quebra de linha acima de 0x7F: as linhas não mudam de número."""
    return dados.decode("utf-8", errors="catraca_cp1252")


def ler_texto(caminho: Path) -> str:
    """O texto de um arquivo como as catracas de dado pessoal o leem — UTF-8, UTF-16
    ou cp1252, com os escapes ``\\uXXXX`` desfeitos.

    * BOM de UTF-32/UTF-16, ou, sem BOM, os NUL dos primeiros 4 KiB enchendo uma só
      paridade (``_utf16_sem_bom``; a ordem dos bytes sai do lado em que caem):
      UTF-16 (o "Texto Unicode" do Excel). Um NUL solto não faz o UTF-8 virar UTF-16;
    * senão UTF-8 estrito e, no trecho que não for UTF-8, cp1252 com ``replace``;
    * ``\\r\\n`` e ``\\r`` viram ``\\n``, como no ``read_text`` (a linha do achado é a
      mesma de antes);
    * por fim, ``\\u00e3`` → ``ã`` (``json.dumps`` padrão grava assim).

    Arquivo ilegível levanta ``OSError``, como o ``read_text`` de antes."""
    dados = Path(caminho).read_bytes()
    if dados.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
        texto = dados.decode("utf-32", errors="replace")
    elif dados.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        texto = dados.decode("utf-16", errors="replace")
    elif (ordem := _utf16_sem_bom(dados[:_AMOSTRA])) is not None:
        texto = dados.decode(ordem, errors="replace")
    else:
        texto = _utf8_ou_cp1252(dados)
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    return _ESCAPE_U.sub(_desfazer_escape, texto)


def cpfs_validos(raiz: Path, arquivos: list[str]) -> list[str]:
    """``arquivo:linha`` de cada CPF com verificador válido (sem o valor)."""
    achados = []
    for rel in arquivos:
        try:
            texto = ler_texto(raiz / rel)
        except OSError:
            continue
        for numero, linha in enumerate(texto.splitlines(), 1):
            candidatos = ["".join(m.groups()) for m in _FORMATADO.finditer(linha)]
            if "cpf" in linha.lower():
                candidatos += _CRU.findall(linha)
            if any(cpf_valido(c) for c in candidatos):
                achados.append(f"{rel}:{numero}")
    return achados


def _com_verificadores(base9: str) -> str:
    """Completa 9 dígitos com os 2 verificadores — montado em tempo de teste para que
    nenhum CPF válido apareça escrito neste arquivo (a própria sentinela o acusaria)."""
    digitos = base9
    for n in (9, 10):
        digitos += str((sum(int(digitos[i]) * (n + 1 - i) for i in range(n)) * 10) % 11 % 10)
    return digitos


def test_cpf_valido_e_cpf_ficticio():
    valido = _com_verificadores("123456789")
    assert cpf_valido(valido)
    errado = valido[:-1] + str((int(valido[-1]) + 1) % 10)   # verificador errado = fictício
    assert not cpf_valido(errado)
    assert not cpf_valido("11111111111")


def test_nenhum_cpf_valido_versionado():
    arquivos, origem = arquivos_a_verificar()
    _exigir_o_que_verificar(arquivos, origem, PROJECT_ROOT)
    achados = cpfs_validos(PROJECT_ROOT, arquivos)
    assert not achados, (
        f"CPF com dígito verificador VÁLIDO ({origem}; sem reproduzir o valor): "
        f"{achados}. Use dado fictício com o verificador errado.")


# --- A própria sentinela: nunca passa "vazia" -------------------------------------

def _formatado(digitos: str) -> str:
    return f"{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:]}"


def _projeto_com_cpf(raiz: Path) -> None:
    """Projeto de mentira com um CPF VÁLIDO (gerado em tempo de teste, em tmp) num
    arquivo de código e cópias nas pastas que a varredura deve pular."""
    linha = f"aluno = {{'cpf': '{_formatado(_com_verificadores('987654321'))}'}}\n"
    for rel in ("backend/tests/test_copiado.py", "apps/web/node_modules/x/dados.json",
                "uploads/lista.csv", "backend/.venv/lib/x.py"):
        destino = raiz / rel
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(linha, encoding="utf-8")


def _git_init(pasta: Path) -> None:
    """``git init`` na pasta, ou pula (sem git; ou o Windows recusa o caminho longo
    do diretório temporário — core.longpaths ajuda quando o Git for Windows deixa)."""
    try:
        subprocess.run(["git", "-c", "core.longpaths=true", "-C", str(pasta), "init", "-q"],
                       capture_output=True, text=True, encoding="utf-8", check=True)
    except OSError:
        pytest.skip("git ausente: o repositório de teste não se monta")
    except subprocess.CalledProcessError as erro:
        pytest.skip(f"git init recusado neste ambiente: {erro.stderr.strip()[:200]}")


def test_copia_dentro_de_outro_repositorio_e_varrida_pelo_disco(tmp_path):
    """O caso do e97: cópia por git archive dentro de uma pasta que é repositório sem
    esses arquivos rastreados — o ls-files dava 0 e a sentinela passava vazia."""
    externo = tmp_path / "pp"
    projeto = externo / "copia"
    projeto.mkdir(parents=True)
    _git_init(externo)
    _projeto_com_cpf(projeto)
    assert _git(projeto, "ls-files") == ""                 # o que enganava antes

    arquivos, origem = arquivos_a_verificar(projeto)

    assert origem == "sistema de arquivos"
    assert arquivos == ["backend/tests/test_copiado.py"]   # pastas de fora puladas
    assert cpfs_validos(projeto, arquivos) == ["backend/tests/test_copiado.py:1"]


def test_pasta_sem_git_e_varrida_pelo_disco(tmp_path, monkeypatch):
    projeto = tmp_path / "sem_git"
    projeto.mkdir()
    _projeto_com_cpf(projeto)
    monkeypatch.setattr(subprocess, "run", _sem_git)
    arquivos, origem = arquivos_a_verificar(projeto)
    assert origem == "sistema de arquivos"
    assert cpfs_validos(projeto, arquivos) == ["backend/tests/test_copiado.py:1"]


def _sem_git(*args, **kwargs):
    raise FileNotFoundError("git")


def test_checkout_real_usa_so_os_versionados(tmp_path):
    projeto = tmp_path / "co"
    projeto.mkdir()
    _git_init(projeto)
    (projeto / "backend").mkdir()
    (projeto / "backend" / "limpo.py").write_text("x = 1\n", encoding="utf-8")
    _git(projeto, "add", "backend/limpo.py")
    _projeto_com_cpf(projeto)                              # NÃO rastreado: fica fora

    arquivos, origem = arquivos_a_verificar(projeto)

    assert origem == "git ls-files"
    assert arquivos == ["backend/limpo.py"]
    assert cpfs_validos(projeto, arquivos) == []


def test_raiz_do_sistema_de_arquivos_nao_e_varrida(monkeypatch):
    """PROJECT_ROOT na raiz do disco (backend na raiz de uma imagem): nada de
    percorrer o sistema de arquivos inteiro — vazio, e a sentinela pula/falha."""
    raiz = Path(Path.cwd().anchor)
    caminhadas = []
    monkeypatch.setattr(os, "walk", lambda *a, **k: caminhadas.append(a) or iter(()))
    monkeypatch.setattr(subprocess, "run", _sem_git)
    assert arquivos_a_verificar(raiz) == ([], "sistema de arquivos")
    assert caminhadas == []                                # nem começou a varrer


def test_nada_para_verificar_pula_fora_do_ci_e_falha_no_ci(monkeypatch, tmp_path):
    monkeypatch.delenv("CI", raising=False)
    with pytest.raises(pytest.skip.Exception):
        _exigir_o_que_verificar([], "sistema de arquivos", tmp_path)
    monkeypatch.setenv("CI", "true")
    with pytest.raises(pytest.fail.Exception):
        _exigir_o_que_verificar([], "sistema de arquivos", tmp_path)
    _exigir_o_que_verificar(["a.py"], "git ls-files", tmp_path)   # com arquivos: segue
