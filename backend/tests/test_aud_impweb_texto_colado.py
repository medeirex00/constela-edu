"""Auditoria (tela de Importações): o texto colado vai como arquivo .txt.

UPLOADS-9: a tela mandava o texto colado como CAMPO de formulário (``texto``). O
Starlette corta campo que não é arquivo em 1 MB e responde 400 em inglês ("Part
exceeded maximum size of 1024KB."), embora o mesmo conteúdo num .txt seja aceito até
10 MB. A tela passou a mandar o texto colado como o arquivo "texto-colado.txt" — o
mesmo caminho e o mesmo teto do .txt enviado. Aqui, o lado do backend: o arquivo é
lido como o texto (a mesma prévia) e passa de 1 MB; o campo, não. Dados fictícios.
"""
API = "/api/v1"

TEXTO = (
    "Nome do aluno\tAtividades finalizadas\tPontuação média\tEstrelas\n"
    "Ana Beatriz Souza\t42\t85,5\t120\n"
    "Crianca Ficticia Sem Ficha\t11\t71\t36\n")


def _como_campo(cliente, eid, texto):
    """Como a tela mandava: o campo ``texto`` num multipart (FormData), sem nome de arquivo."""
    return cliente.post(f"{API}/escolas/{eid}/importacoes/analisar",
                        files={"texto": (None, texto.encode("utf-8"))})


def _como_arquivo(cliente, eid, texto):
    return cliente.post(f"{API}/escolas/{eid}/importacoes/analisar", files={
        "arquivo": ("texto-colado.txt", texto.encode("utf-8"), "text/plain;charset=utf-8")})


def _o_que_a_tela_le(analise):
    return (analise["plataforma"], analise["formato"], analise["tipo"], analise["turma_detectada"],
            [(linha["nome"], linha["dados"], linha["correspondencia"]["status"])
             for linha in analise["linhas"]])


def test_texto_colado_como_arquivo_da_a_mesma_previa(cliente, escola_completa):
    eid = escola_completa["escola"].id
    campo, arquivo = _como_campo(cliente, eid, TEXTO), _como_arquivo(cliente, eid, TEXTO)
    assert campo.status_code == 200, campo.text
    assert arquivo.status_code == 200, arquivo.text
    assert _o_que_a_tela_le(arquivo.json()) == _o_que_a_tela_le(campo.json())
    # Sem original guardado: o .txt não é arquivado como o PDF ou a planilha.
    assert arquivo.json()["arquivo_token"] is None


def test_texto_colado_acima_de_1_mb_passa_como_arquivo(cliente, escola_completa):
    eid = escola_completa["escola"].id
    grande = TEXTO + "\n" * (1024 * 1024 + 50_000)
    campo = _como_campo(cliente, eid, grande)
    assert campo.status_code == 400 and "exceeded" in campo.text, campo.text
    arquivo = _como_arquivo(cliente, eid, grande)
    assert arquivo.status_code == 200, arquivo.text
    assert [linha["nome"] for linha in arquivo.json()["linhas"]] == [
        "Ana Beatriz Souza", "Crianca Ficticia Sem Ficha"]
