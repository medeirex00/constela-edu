"""Catraca: nenhum nome completo de PESSOA real nos arquivos versionados (LGPD).

Testes e comentários de código copiavam nomes de crianças e de uma professora dos
casos reais da Lista Piloto (o caso de homônimos com nome abreviado da escola 11, o
caso de esquecimento com acento, a convenção do @ dos professores, a triagem de
candidatos múltiplos da escola 17...). Foram trocados por nomes fictícios; esta
trava impede que voltem por cópia de planilha ou de relatório.

Como procurar um nome sem escrevê-lo: este arquivo guarda só o SHA-256 de cada nome
real NORMALIZADO — CamelCase separado (o @ "PrimeiroUltimo" conta como duas
palavras), sem acento, casefold, só as palavras ``[a-z0-9]+`` unidas por um espaço.
A varredura normaliza cada arquivo do mesmo jeito, calcula o SHA-256 de toda janela
de 2 a 4 palavras seguidas (atravessando quebra de linha, pontuação, ``#`` e ``_``)
e reprova se alguma bater. O achado diz ``arquivo:linha``, nunca o nome.

Para incluir um nome, gere o hash localmente e cole SÓ o hash:
``python -c "from tests.test_sem_nome_real_de_pessoa import digest; print(digest('…'))"``
(rodado em ``backend/``). Nunca escreva o nome real aqui, num commit ou num relatório.

Limites (de propósito):
  * só nome de 2 a 4 palavras: primeiro nome sozinho não é procurado (não dá para
    distinguir de um fictício). Os primeiros nomes de crianças reais que apareciam
    ao lado de "caso real" foram tirados à mão;
  * só as grafias listadas: um nome real que nunca entrou no repositório não está
    aqui — pôr o hash dele seria publicar um "esse nome é de uma criança da rede";
  * SHA-256 sem sal não esconde o nome de quem já o tem: um dicionário de nomes
    confirma o hash. O que a catraca protege é o repositório, não o segredo do nome;
  * arquivo binário (PDF, imagem, planilha) fica fora, como na sentinela de CPF;
  * texto em UTF-8, UTF-16 ou cp1252, com os escapes ``\\uXXXX`` do JSON desfeitos
    (``ler_texto``, o mesmo da sentinela de CPF): o CSV do Excel em cp1252, o "Texto
    Unicode" e o ``json.dumps`` padrão passavam com o nome acentuado (e97,
    integração 5). Outra codificação (EBCDIC, UTF-7...) e outro escape (entidade
    HTML, ``%XX``) não são desfeitos.
"""
import hashlib
import os
import re
import unicodedata
from pathlib import Path

import pytest

from app.core.config import PROJECT_ROOT
from tests.test_sem_dado_pessoal_real import arquivos_a_verificar, ler_texto

JANELAS = (2, 3, 4)

# SHA-256 dos nomes reais normalizados (ver ``normalizar``). Só hashes, nunca o nome.
NOMES_REAIS_SHA256 = frozenset({
    # Caso de homônimos com nome abreviado (escola 11): a criança, as grafias que as
    # plataformas mandavam e a outra criança de mesmo sobrenome na turma.
    "c4af00d50681fd7c438107615209d072b44ba003998da1bfa401b73a735ae96c",
    "4829e047a99c7efd3d5190502178c3eba437ea66db631965f5f46623414ceacf",
    "41034ca24769400efdd9fb6e6dfdbf58f67b0165aeb755c6679b27726d6314b1",
    "d7b5ace27c8891ea2f1528a57693c5326ef48d105a9090e93d82c5a3c9e2c748",
    "d8a1776156589b93a84b77987ba3f955d057501e8f20f0f6d5d5222a4eb22a60",
    "944eabee0de40321e7ec800fbd768fa21a3f73c1bab2eafd3fcf6d3161ee79f7",
    "58e768f59471935c4f657ca4082834f0df42481f1985bb96a639dc1fd568ea5d",
    "da359ad37fa8039d20ada4b811d5d69b556a8aa392256f335a922268ec57c09c",
    "687c0e52e0fc0c0e22d02a49d15cf1c827f586bbab0c8ec3c37aba2b113774f0",
    "0c6a4b43fdb661ae302d567cfca0bb5aeb8fd67fc9ed398c78ac243ee8be6a73",
    # Caso do esquecimento que precisa ignorar acento e caixa (escola 11).
    "95c88ef5e260ecb6623f0791b12b3cbe42abf1b6af31c16aac43206738bca7aa",
    "a1dd382b3836d3b7ed89449cc015f8075a88c06b0649e1ec88dc4d140b216f6a",
    "b50874f1aa68825b084509266b264e15c0e037cebaaaabdf2fd2e8cbde247e01",
    # Professora do exemplo da convenção do @ (partícula no meio do sobrenome).
    "a36f671d576c70ee16947ffb0320ea1aa25adcbfcf20959353199d2256961897",
    "c928328274b8b8f5599482f8ea50b900ff35c483e840cd024ee1f47e2eef6070",
    "c0fbd8514fa80c6327b006638de086d6fa0de2949aa38613cda539f85a3b344f",
    "ded2e67e09ce8565034318c8ee125e162813f94a36efeb74a5ea451418e16627",
    "3ee4b8a4661b241b29b24bc4923484db79700613a6d60b8e6cb4834b7aa065c1",
    # Variação de grafia no nome do meio (decisão do dono de 2026-08-04).
    "84af2927ea33aae313fcfef68b818ffab85fbc506db5e6ac5014485ecd8f4d34",
    "7e993e8fbfaf6aebcc0aebcb8a04c6cd17c567a2c79a588b088672a69bd60671",
    "4a7e1ecd6c741b489336901da942fdadc09b43876ef148d2e6550a9a44b272c3",
    "0874faf4b8429196c8f3cf09b7fce53fb697ad6ce15afa1a6a0e3120b39917a4",
    # Triagem de candidatos múltiplos (escola 17): as duas crianças.
    "2cc9a38b6aad37958bcc759016905b3dddc53521abce6cf79a3f31b0c29aadb0",
    "35ad5a89508d8e167536e36514c955019317212e7c44d7dc277642bd57753725",
    "cbf30d32a3d463513a85fc49c0554fdf85570543eaf4a92f976ab85f43d0711b",
    # Nome do meio omitido (parcial estrutural): primeiro nome + sobrenome reais.
    "0a38d8d993e596f4e78ce7b98b78030b2b7ea3f3a5b72bf68e7ae371b3b71fd0",
})
_ALVOS = frozenset(bytes.fromhex(h) for h in NOMES_REAIS_SHA256)

_CAMEL = re.compile(r"(?<=[a-zà-ÿ])(?=[A-ZÀ-Þ])")
_PALAVRA = re.compile(r"[a-z0-9]+")


def _sem_acento_casefold(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", _CAMEL.sub(" ", texto))
    return "".join(c for c in decomposto if not unicodedata.combining(c)).casefold()


def normalizar(nome: str) -> str:
    """CamelCase separado, sem acento, casefold, palavras [a-z0-9] por um espaço."""
    return " ".join(_PALAVRA.findall(_sem_acento_casefold(nome)))


def digest(nome: str) -> str:
    """O SHA-256 (hex) do nome normalizado — o que entra em ``NOMES_REAIS_SHA256``."""
    return hashlib.sha256(normalizar(nome).encode()).hexdigest()


def achados(texto: str, alvos: frozenset[bytes] = _ALVOS) -> list[int]:
    """Linhas (1 = primeira) onde começa uma janela de 2–4 palavras cujo SHA-256
    está em ``alvos``. A janela atravessa quebra de linha: um nome quebrado no
    meio de um comentário continua sendo achado (na linha em que começa)."""
    palavras: list[str] = []
    linhas: list[int] = []
    for numero, linha in enumerate(_sem_acento_casefold(texto).split("\n"), 1):
        achadas = _PALAVRA.findall(linha)
        palavras += achadas
        linhas += [numero] * len(achadas)

    def janelas():
        for n in JANELAS:
            for i in range(len(palavras) - n + 1):
                yield i, " ".join(palavras[i:i + n])

    # Cada janela distinta é calculada uma vez; a linha só é procurada se bater.
    reais = {j for j in {j for _, j in janelas()}
             if hashlib.sha256(j.encode()).digest() in alvos}
    return sorted({linhas[i] for i, j in janelas() if j in reais}) if reais else []


def nomes_reais_nos_arquivos(raiz: Path, arquivos: list[str],
                             alvos: frozenset[bytes] = _ALVOS) -> list[str]:
    """``arquivo:linha`` de cada nome cujo hash está em ``alvos`` (sem o nome)."""
    encontrados = []
    for rel in arquivos:
        try:
            texto = ler_texto(raiz / rel)
        except OSError:
            continue
        encontrados += [f"{rel}:{linha}" for linha in achados(texto, alvos)]
    return encontrados


# --- O detector (com nome FICTÍCIO, gerado aqui) -----------------------------------

def _alvos(*nomes: str) -> frozenset[bytes]:
    return frozenset(bytes.fromhex(digest(n)) for n in nomes)


def test_normalizacao_ignora_acento_caixa_separador_e_camelcase():
    assert normalizar("  Tristão   SIMULATTI-fictelli ") == "tristao simulatti fictelli"
    assert normalizar("TristãoSimulatti") == "tristao simulatti"
    assert normalizar("relatorio_tristao_simulatti.pdf") == "relatorio tristao simulatti pdf"
    assert digest("TRISTAO SIMULATTI") == digest("Tristão Simulatti")
    assert len(digest("x y")) == 64


def test_detector_pega_as_grafias_e_diz_a_linha():
    alvos = _alvos("Tristão Simulatti Fictelli", "Gertrudes Fictelo")
    assert achados('nome="TRISTAO SIMULATTI FICTELLI"', alvos) == [1]
    assert achados("x = 1\n# caso da tristão simulatti\n#   Fictelli, escola 11", alvos) == [2]
    assert achados("relatorio_tristao_simulatti_fictelli.pdf", alvos) == [1]
    assert achados("a\nb\nusername == 'GertrudesFictelo'", alvos) == [3]
    assert achados("Gertrudes   Fictelo,\nTristão Simulatti Fictelli", alvos) == [1, 2]


def test_detector_nao_acusa_pedaco_nem_palavra_maior():
    alvos = _alvos("Tristão Simulatti Fictelli")
    assert achados("TRISTAO SIMULATTI", alvos) == []                 # falta o sobrenome
    assert achados("TRISTAO X SIMULATTI FICTELLI", alvos) == []      # palavra no meio
    assert achados("MTRISTAO SIMULATTI FICTELLIS", alvos) == []      # palavra maior
    assert achados("", alvos) == [] and achados("Tristão", alvos) == []


def test_lista_so_tem_hashes_sha256():
    assert len(NOMES_REAIS_SHA256) >= 26
    for h in NOMES_REAIS_SHA256:
        assert re.fullmatch(r"[0-9a-f]{64}", h), h
    # O próprio arquivo não tem nome real (a varredura abaixo também o lê).
    with open(__file__, encoding="utf-8") as f:
        assert achados(f.read()) == []


# --- A catraca ---------------------------------------------------------------------

def test_nenhum_nome_real_de_pessoa_versionado():
    arquivos, origem = arquivos_a_verificar()
    if not arquivos:
        motivo = f"nenhum arquivo para varrer em {PROJECT_ROOT} (origem: {origem})"
        if os.environ.get("CI", "").strip().lower() == "true":
            pytest.fail(motivo)
        pytest.skip(motivo)
    assert any(a.startswith("backend/tests/") for a in arquivos)     # varre os testes

    encontrados = nomes_reais_nos_arquivos(PROJECT_ROOT, arquivos)
    assert not encontrados, (
        f"Nome de PESSOA real em arquivo versionado ({origem}; sem reproduzir o nome): "
        f"{encontrados}. Troque por um nome inventado e inequívoco (ex.: sobrenome "
        "'Fictelli'/'Simulatti'); para citar o caso real, descreva-o ('caso de "
        "homônimos com nome abreviado, escola 11').")
