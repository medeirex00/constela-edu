"""PDF inflado (bomba de descompressão) — recusado ANTES do pdfplumber (achado [17]
da auditoria de 31/10).

O upload só conferia o tamanho COMPRIMIDO (10 MB). Um fluxo FlateDecode de poucos
KB vira centenas de MB, e o pdfminer (motor do pdfplumber) descompacta tudo na
memória, sem teto: os 10 MB permitidos chegavam a ~10 GB e derrubavam o processo
da API de todas as redes. Agora cada fluxo é medido com descompressão LIMITADA
(``zlib.decompressobj().decompress(dado, max_length)``), seguindo os filtros em
cadeia, e o arquivo acima do teto (ou com páginas demais) é recusado com 413 —
o que o leitor não consegue medir com segurança, com 422.

Tudo fictício, gerado em memória, com tetos reduzidos por monkeypatch: os testes
provam a regra sem alocar centenas de MB.
"""
import base64
import io
import zlib

import pytest

from app.services import perfis_pdf
from app.services.perfis_pdf import PdfRecusado

MB = 1024 * 1024


def _montar(objetos: list[bytes], trailer_extra: bytes = b"") -> bytes:
    saida = bytearray(b"%PDF-1.4\n")
    posicoes = []
    for i, objeto in enumerate(objetos, 1):
        posicoes.append(len(saida))
        saida += b"%d 0 obj\n" % i + objeto + b"\nendobj\n"
    xref = len(saida)
    saida += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objetos) + 1)
    for pos in posicoes:
        saida += b"%010d 00000 n \n" % pos
    saida += (b"trailer\n<< /Size %d /Root 1 0 R %s>>\nstartxref\n%d\n%%%%EOF\n"
              % (len(objetos) + 1, trailer_extra, xref))
    return bytes(saida)


def _pdf_com_conteudo(corpo: bytes, dicionario: bytes | None = None,
                      extras: list[bytes] | None = None) -> bytes:
    """PDF de 1 página cujo conteúdo é ``corpo`` com o dicionário dado."""
    dicionario = dicionario or b"<< /Length %d /Filter /FlateDecode >>" % len(corpo)
    return _montar([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << >> >>",
        dicionario + b"\nstream\n" + corpo + b"\nendstream",
        *(extras or []),
    ])


def _bomba(n_bytes: int = 8 * MB) -> bytes:
    return zlib.compress(b" " * n_bytes, 9)


@pytest.fixture()
def teto_4mb(monkeypatch):
    monkeypatch.setattr(perfis_pdf, "PDF_MAX_DESCOMPRIMIDO", 4 * MB)


@pytest.fixture()
def espiao_pdfplumber(monkeypatch):
    """Registra se o pdfplumber chegou a abrir o arquivo."""
    import pdfplumber

    chamadas: list[int] = []
    original = pdfplumber.open

    def abrir(*args, **kwargs):
        chamadas.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(pdfplumber, "open", abrir)
    return chamadas


def _pdf_real(paginas: int = 1) -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_font("helvetica", size=11)
    for i in range(paginas):
        pdf.add_page()
        pdf.cell(0, 8, f"Relatorio Matific - Turma 3 Ano A - pagina {i + 1}")
    return bytes(pdf.output())


def _cifrar(pdf: bytes, *, senha_usuario: str = "", algoritmo: str = "AES-128") -> bytes:
    from pypdf import PdfReader, PdfWriter

    escritor = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf)))
    escritor.encrypt(user_password=senha_usuario, owner_password="dono", algorithm=algoritmo)
    saida = io.BytesIO()
    escritor.write(saida)
    return saida.getvalue()


# --- A rota: o que a auditoria reproduziu ------------------------------------

def test_rota_recusa_pdf_inflado_com_413_antes_do_pdfplumber(
        cliente, escola_completa, teto_4mb, espiao_pdfplumber):
    """Antes: HTTP 200 e o pdfplumber lia o fluxo inteiro (pico ~2x o descompactado).
    Agora: 413 com mensagem honesta, e o pdfplumber nem abre o arquivo."""
    escola_id = escola_completa["escola"].id
    pdf = _pdf_com_conteudo(_bomba(8 * MB))
    assert len(pdf) < 64 * 1024   # poucos KB enviados

    resposta = cliente.post(
        f"/api/v1/escolas/{escola_id}/importacoes/analisar",
        files={"arquivo": ("relatorio.pdf", pdf, "application/pdf")})

    assert resposta.status_code == 413, resposta.text
    assert "descompactado" in resposta.json()["detail"]
    assert espiao_pdfplumber == []


def test_rota_recusa_pdf_com_paginas_demais_com_413(cliente, escola_completa, monkeypatch):
    monkeypatch.setattr(perfis_pdf, "PDF_MAX_PAGINAS", 5)
    escola_id = escola_completa["escola"].id

    resposta = cliente.post(
        f"/api/v1/escolas/{escola_id}/importacoes/analisar",
        files={"arquivo": ("relatorio.pdf", _pdf_real(6), "application/pdf")})

    assert resposta.status_code == 413, resposta.text
    assert "mais de 5 páginas" in resposta.json()["detail"]


def test_tetos_padrao():
    assert perfis_pdf.PDF_MAX_DESCOMPRIMIDO == 50 * MB
    assert perfis_pdf.PDF_MAX_DESCOMPRIMIDO_GENERICO == 10 * MB
    assert perfis_pdf.PDF_MAX_PAGINAS == 300
    # Calibrados em 01/11 com 86 PDFs reais (máximos: ~80 mil caracteres no total,
    # ~6,5 mil numa página; ~110 mil desenhos no total — margem de só ~1,36x —, ~14,6
    # mil numa página).
    assert perfis_pdf.PDF_MAX_CARACTERES == 150_000
    assert perfis_pdf.PDF_MAX_CARACTERES_PAGINA == 30_000
    assert perfis_pdf.PDF_MAX_DESENHOS == 150_000
    assert perfis_pdf.PDF_MAX_DESENHOS_PAGINA == 30_000
    # Prazo da análise inteira (o PDF real mais lento leva ~9 a 12 s na parte com
    # orçamento, até ~15 s ao todo) e a guarda do modo layout do genérico (maior linha
    # real: 331 letras, ~224 colunas; no máximo 29 letras miúdas numa página).
    assert perfis_pdf.PDF_MAX_SEGUNDOS == 30
    assert perfis_pdf.PDF_LAYOUT_MAX_LINHA == 500
    assert perfis_pdf.PDF_LAYOUT_LETRA_MIUDA == 1.0
    assert perfis_pdf.PDF_LAYOUT_MAX_LETRAS_MIUDAS == 100


# --- O medidor ---------------------------------------------------------------

def test_relatorio_real_pequeno_passa():
    perfis_pdf.exigir_pdf_contido(_pdf_real())
    perfis_pdf.exigir_pdf_contido(_cifrar(_pdf_real()))   # senha só de dono: lê normal
    perfis_pdf.analisar_pdf(_pdf_real(3))                  # 3 páginas: abaixo do teto


def test_paginas_no_limite_passam_e_uma_a_mais_recusa(monkeypatch):
    monkeypatch.setattr(perfis_pdf, "PDF_MAX_PAGINAS", 5)
    perfis_pdf.analisar_pdf(_pdf_real(5))
    with pytest.raises(PdfRecusado) as erro:
        perfis_pdf.analisar_pdf(_pdf_real(6))
    assert erro.value.status_http == 413


def test_soma_de_varios_fluxos_conta(teto_4mb):
    """Dois fluxos de 3 MB: cada um cabe, a soma não."""
    tres = _bomba(3 * MB)
    pdf = _montar([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents [4 0 R 5 0 R] /Resources << >> >>",
        b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(tres) + tres + b"\nendstream",
        b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(tres) + tres + b"\nendstream",
    ])
    with pytest.raises(PdfRecusado):
        perfis_pdf.exigir_pdf_contido(pdf)
    perfis_pdf.exigir_pdf_contido(pdf, max_descomprimido=8 * MB)


_DISFARCES = {
    "flate_simples": lambda b: _pdf_com_conteudo(b),
    "ascii85_mais_flate": lambda b: _pdf_com_conteudo(
        base64.a85encode(b) + b"~>", b"<< /Filter [/ASCII85Decode /FlateDecode] >>"),
    "hex_mais_flate": lambda b: _pdf_com_conteudo(
        b.hex().encode() + b">", b"<< /Filter [/AHx /Fl] >>"),
    # o pdfminer devolve a "imagem" como veio e segue a cadeia
    "imagem_mais_flate": lambda b: _pdf_com_conteudo(
        b, b"<< /Filter [/DCTDecode /FlateDecode] >>"),
    "chave_F_no_lugar_de_Filter": lambda b: _pdf_com_conteudo(b, b"<< /F /Fl >>"),
    "nome_com_escape_hex": lambda b: _pdf_com_conteudo(b, b"<< /Filter /Fl#61teDecode >>"),
    "filtro_em_objeto_indireto": lambda b: _pdf_com_conteudo(
        b, b"<< /Filter 5 0 R >>", extras=[b"/FlateDecode"]),
    "lixo_na_linha_de_stream": lambda b: _pdf_com_conteudo(b).replace(
        b"stream\n", b"stream lixo\n", 1),
    "zlib_truncado": lambda b: _pdf_com_conteudo(b[:-4]),
    "dicionario_fora_do_padrao": lambda b: _pdf_com_conteudo(
        b, b"<< 12 34 /Filter /FlateDecode >>"),
}


@pytest.mark.parametrize("caso", list(_DISFARCES))
def test_cadeias_e_disfarces_sao_medidos(teto_4mb, caso):
    with pytest.raises(PdfRecusado) as erro:
        perfis_pdf.exigir_pdf_contido(_DISFARCES[caso](_bomba()))
    assert erro.value.status_http == 413, caso


def test_runlength_e_medido(teto_4mb):
    corpo = bytes([129, 32]) * 70_000          # 70 mil x "128 espaços" ≈ 8,5 MB
    with pytest.raises(PdfRecusado):
        perfis_pdf.exigir_pdf_contido(_pdf_com_conteudo(corpo, b"<< /Filter /RunLengthDecode >>"))


@pytest.mark.parametrize("algoritmo", ["RC4-128", "AES-128"])
def test_pdf_cifrado_com_senha_vazia_e_medido_depois_de_decifrado(teto_4mb, algoritmo):
    """Cifrado, o fluxo não é zlib no arquivo — o pdfminer decifra (senha vazia) e
    descompacta. A medida decifra com o decifrador do próprio pdfminer."""
    with pytest.raises(PdfRecusado) as erro:
        perfis_pdf.exigir_pdf_contido(_cifrar(_pdf_com_conteudo(_bomba()), algoritmo=algoritmo))
    assert erro.value.status_http == 413


def test_pdf_com_senha_de_abertura_e_recusado_com_mensagem_clara():
    with pytest.raises(PdfRecusado) as erro:
        perfis_pdf.exigir_pdf_contido(_cifrar(_pdf_real(), senha_usuario="segredo"))
    assert erro.value.status_http == 422
    assert "protegido por senha" in str(erro.value)


_NAO_MEDIVEIS = {
    "cadeia_em_dicionario_fora_do_padrao": lambda: _pdf_com_conteudo(
        base64.a85encode(_bomba()) + b"~>", b"<< 12 34 /Filter [/A85 /Fl] >>"),
    "tamanho_indireto_fora_do_arquivo": lambda: _pdf_com_conteudo(
        base64.a85encode(_bomba()) + b"~>", b"<< /Length 9 0 R /Filter [/A85 /Fl] >>"),
    "fax_com_largura_absurda": lambda: _pdf_com_conteudo(
        b"\xff" * 1000, b"<< /Filter /CCITTFaxDecode /DecodeParms << /K -1 /Columns 999999 >> >>"),
}


@pytest.mark.parametrize("caso", list(_NAO_MEDIVEIS))
def test_o_que_nao_da_para_medir_com_seguranca_e_recusado(teto_4mb, caso):
    with pytest.raises(PdfRecusado):
        perfis_pdf.exigir_pdf_contido(_NAO_MEDIVEIS[caso]())


_HOSTIS = {
    "stream_repetido_sem_dicionario": lambda: b"%PDF-1.4\n1 0 obj\n" + b"stream " * 200_000,
    "fecha_dicionario_e_stream_sem_objeto": lambda: b"%PDF-1.4\n" + b">> stream\n" * 200_000,
    "cabecalhos_com_dicionario_aberto": lambda: b"%PDF-1.4\n" + b"1 0 obj << /a 1 " * 300_000,
}


@pytest.mark.parametrize("caso", list(_HOSTIS))
def test_estrutura_hostil_e_recusada_sem_custo_quadratico(caso):
    """Arquivos montados para o medidor trabalhar demais: recusados (422) pelos
    limites de estrutura, sem varrer o arquivo uma vez por ocorrência."""
    with pytest.raises(PdfRecusado) as erro:
        perfis_pdf.exigir_pdf_contido(_HOSTIS[caso]())
    assert erro.value.status_http == 422


# --- Imagens: conta própria, limitada ao tamanho que cada uma declara ---------

def _pdf_com_imagem(corpo_imagem: bytes, largura: int, altura: int,
                    conteudo_como_imagem: bool = False) -> bytes:
    """Página que desenha uma imagem (XObject). Com ``conteudo_como_imagem``, o
    CONTEÚDO da página é que vem marcado como imagem (o disfarce)."""
    dic_imagem = (b"<< /Type /XObject /Subtype /Image /Width %d /Height %d "
                  b"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode "
                  b"/Length %d >>" % (largura, altura, len(corpo_imagem)))
    desenho = b"q 100 0 0 100 0 0 cm /Im1 Do Q"
    if conteudo_como_imagem:
        conteudo = dic_imagem + b"\nstream\n" + corpo_imagem + b"\nendstream"
        imagem = b"<< /Length %d >>\nstream\n" % len(desenho) + desenho + b"\nendstream"
    else:
        conteudo = b"<< /Length %d >>\nstream\n" % len(desenho) + desenho + b"\nendstream"
        imagem = dic_imagem + b"\nstream\n" + corpo_imagem + b"\nendstream"
    return _montar([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /XObject << /Im1 5 0 R >> >> >>",
        conteudo,
        imagem,
    ])


def test_imagem_grande_de_verdade_nao_conta_no_teto_do_conteudo(teto_4mb):
    """Captura de tela em PNG (FlateDecode): 2000x1000 RGB = 6 MB descompactados,
    acima do teto do conteúdo (4 MB aqui) — o pdfminer não a descompacta para ler o
    texto, e ela não infla além do que declara: passa."""
    pdf = _pdf_com_imagem(zlib.compress(b"\x80" * (2000 * 1000 * 3), 9), 2000, 1000)
    perfis_pdf.exigir_pdf_contido(pdf)
    perfis_pdf.analisar_pdf(pdf)   # e a página é lida normalmente


def test_imagem_que_infla_alem_do_que_declara_conta_como_conteudo(teto_4mb):
    pdf = _pdf_com_imagem(_bomba(8 * MB), 10, 10)   # "10x10" com 8 MB dentro
    with pytest.raises(PdfRecusado) as erro:
        perfis_pdf.exigir_pdf_contido(pdf)
    assert "depois de descompactado" in str(erro.value)


def test_imagens_tem_teto_proprio(monkeypatch):
    monkeypatch.setattr(perfis_pdf, "PDF_MAX_IMAGENS", 4 * MB)
    pdf = _pdf_com_imagem(zlib.compress(b"\x80" * (2000 * 1000 * 3), 9), 2000, 1000)
    with pytest.raises(PdfRecusado) as erro:
        perfis_pdf.exigir_pdf_contido(pdf)
    assert erro.value.status_http == 413
    assert "imagens do PDF" in str(erro.value)


def test_imagem_disfarcando_o_conteudo_da_pagina_e_recusada_antes_de_ler(teto_4mb):
    """O pdfminer descompacta o conteúdo da página sem olhar o /Subtype: um conteúdo
    marcado como imagem (geometria enorme, para caber na conta das imagens) é
    recusado assim que o documento abre, antes de qualquer página ser lida."""
    pdf = _pdf_com_imagem(_bomba(8 * MB), 4000, 4000, conteudo_como_imagem=True)
    perfis_pdf.exigir_pdf_contido(pdf)   # a medida, sozinha, aceitaria
    with pytest.raises(PdfRecusado) as erro:
        perfis_pdf.analisar_pdf(pdf)
    assert erro.value.status_http == 422


def test_imagem_disfarcando_um_fluxo_de_objetos_nao_ganha_a_conta_das_imagens(teto_4mb):
    """Contêiner de objetos (entrada tipo 2 da tabela xref em fluxo) é descompactado
    pelo pdfminer ao ABRIR o documento: marcado como imagem, conta como conteúdo."""
    corpo = zlib.compress(b"1 0 << /Type /Catalog /Pages 2 0 R >>" + b" " * (8 * MB), 9)
    objetos = [
        None,   # 1: dentro do contêiner 5
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << >> >>",
        None,   # 4: livre
        b"<< /Subtype /Image /Width 4000 /Height 4000 /BitsPerComponent 8 /N 1 /First 4 "
        b"/Filter /FlateDecode /Length %d >>\nstream\n" % len(corpo) + corpo + b"\nendstream",
    ]
    saida = bytearray(b"%PDF-1.5\n")
    posicoes = {}
    for numero, objeto in enumerate(objetos, 1):
        if objeto is not None:
            posicoes[numero] = len(saida)
            saida += b"%d 0 obj\n" % numero + objeto + b"\nendobj\n"
    linhas = b"\x00\x00\x00\x00\x00\xff\xff"                        # 0: livre
    linhas += b"\x02" + (5).to_bytes(4, "big") + b"\x00\x00"         # 1: no contêiner 5
    for numero in (2, 3):
        linhas += b"\x01" + posicoes[numero].to_bytes(4, "big") + b"\x00\x00"
    linhas += b"\x00\x00\x00\x00\x00\x00\x00"                        # 4: livre
    linhas += b"\x01" + posicoes[5].to_bytes(4, "big") + b"\x00\x00"
    inicio_xref = len(saida)
    linhas += b"\x01" + inicio_xref.to_bytes(4, "big") + b"\x00\x00"  # 6: a própria tabela
    xref = zlib.compress(linhas)
    saida += (b"6 0 obj\n<< /Type /XRef /Size 7 /W [1 4 2] /Root 1 0 R /Filter /FlateDecode "
              b"/Length %d >>\nstream\n" % len(xref)) + xref + b"\nendstream\nendobj\n"
    saida += b"startxref\n%d\n%%%%EOF\n" % inicio_xref
    with pytest.raises(PdfRecusado) as erro:
        perfis_pdf.exigir_pdf_contido(bytes(saida))
    assert "depois de descompactado" in str(erro.value)


def test_a_sincronizacao_tambem_e_protegida(teto_4mb):
    """O mesmo parser lê os PDFs baixados das plataformas (``orchestrator._parsear``),
    e a recusa vira o erro de conector da planilha recusada: sem nova tentativa."""
    from app.sync import orchestrator
    from app.sync.interfaces import ArquivoObtido, ErroConector

    arquivo = ArquivoObtido(conteudo=_pdf_com_conteudo(_bomba()), nome_arquivo="elefante.pdf",
                            plataforma="elefante", content_type="application/pdf")
    with pytest.raises(ErroConector) as erro:
        orchestrator._parsear(arquivo)
    assert erro.value.codigo == "parser_incompativel"
    assert erro.value.recuperavel is False
    assert isinstance(erro.value.__cause__, PdfRecusado)
    assert "descompactado" in str(erro.value)


# --- O medidor fala a língua do pdfminer (espaço \x0b, "#") ------------------
# Cada variante mudava UM byte e passava pelo medidor, e o pdfminer descompactava
# tudo. O medidor agora separa as palavras onde o pdfminer separa.

_UM_BYTE = {
    "tab_vertical_entre_Filter_e_o_nome": lambda b: _pdf_com_conteudo(
        b, b"<< /Length %d /Filter\x0b/FlateDecode >>" % len(b)),
    "tab_vertical_entre_dicionario_e_stream": lambda b: _pdf_com_conteudo(b).replace(
        b">>\nstream\n", b">>\x0bstream\n", 1),
    "tab_vertical_depois_de_stream": lambda b: _pdf_com_conteudo(b).replace(
        b"\nstream\n", b"\nstream\x0b\n", 1),
    "sustenido_depois_de_stream": lambda b: _pdf_com_conteudo(b).replace(
        b"\nstream\n", b"\nstream#x\n", 1),
    # "#" sem dígito hexadecimal some do nome no pdfminer: /F#lateDecode = /FlateDecode
    "sustenido_sem_hexa_no_nome": lambda b: _pdf_com_conteudo(
        b, b"<< /Length %d /Filter /F#lateDecode >>" % len(b)),
}


@pytest.mark.parametrize("caso", list(_UM_BYTE))
def test_medidor_separa_as_palavras_como_o_pdfminer(teto_4mb, caso):
    pdf = _UM_BYTE[caso](_bomba())
    with pytest.raises(PdfRecusado) as erro:
        perfis_pdf.exigir_pdf_contido(pdf)
    assert erro.value.status_http == 413, caso


def test_medidor_reconhece_cifra_escrita_com_escape(teto_4mb):
    """O nome "/Encr#79pt" é /Encrypt para o pdfminer: o medidor decifra e mede."""
    pdf = _cifrar(_pdf_com_conteudo(_bomba()), algoritmo="RC4-128")
    assert pdf.count(b"/Encrypt") == 1      # só no trailer, depois da tabela xref
    with pytest.raises(PdfRecusado) as erro:
        perfis_pdf.exigir_pdf_contido(pdf.replace(b"/Encrypt", b"/Encr#79pt"))
    assert erro.value.status_http == 413


# --- O orçamento DENTRO dos leitores (a garantia de verdade) ------------------
# Com o medidor desligado, nada que o pdfminer ou o pypdf descompactem durante a
# análise passa do teto: a recusa vem de dentro deles.

@pytest.fixture()
def sem_medidor(monkeypatch):
    monkeypatch.setattr(perfis_pdf, "exigir_pdf_contido", lambda *a, **k: None)


_POR_DENTRO = {
    "flate": lambda b: _pdf_com_conteudo(b),
    **_UM_BYTE,
    "ascii85_mais_flate": _DISFARCES["ascii85_mais_flate"],
    "zlib_truncado_leitura_de_recuperacao": _DISFARCES["zlib_truncado"],
    "runlength": lambda _b: _pdf_com_conteudo(
        bytes([129, 32]) * 70_000, b"<< /Filter /RunLengthDecode >>"),
}


@pytest.mark.parametrize("caso", list(_POR_DENTRO))
def test_orcamento_recusa_por_dentro_do_pdfminer(teto_4mb, sem_medidor, espiao_pdfplumber,
                                                 caso):
    with pytest.raises(PdfRecusado) as erro:
        perfis_pdf.analisar_pdf(_POR_DENTRO[caso](_bomba()))
    assert erro.value.status_http == 413, caso
    assert "descompactado" in str(erro.value)
    assert espiao_pdfplumber == [1]          # recusou de dentro da leitura


def _lacunas(n_linhas: int, tamanho: float = 0.01, por_linha: int = 2,
             paginas: int = 1, lacuna: int = 500) -> bytes:
    """PDF com pouquíssimas letras, mas com lacunas enormes entre elas: o pdfplumber vê
    ``por_linha × n_linhas`` caracteres; o modo layout do pypdf (leitor genérico) enche
    cada lacuna de espaços — milhões de caracteres de um arquivo de poucos KB."""
    partes = [b"BT /F1 %g Tf\n" % tamanho]
    passo = 780.0 / max(n_linhas, 1)
    for i in range(n_linhas):
        y = 790.0 - i * passo
        for k in range(por_linha):
            partes.append(b"1 0 0 1 %d %.4f Tm(a)Tj\n" % (k * lacuna, y))
    partes.append(b"ET")
    return _pdf_paginas(b"".join(partes), paginas)


@pytest.fixture()
def sem_guarda_do_layout(monkeypatch):
    """Desliga a guarda do modo layout (``_so_texto_simples``): o pypdf lê no modo layout
    mesmo a página que o pdfplumber mediu arriscada — para provar o que vem DEPOIS dela."""
    monkeypatch.setattr(perfis_pdf, "PDF_LAYOUT_MAX_LINHA", 10 ** 12)
    monkeypatch.setattr(perfis_pdf, "PDF_LAYOUT_MAX_LETRAS_MIUDAS", 10 ** 12)


@pytest.fixture()
def modo_layout(monkeypatch):
    """Registra cada página que o pypdf leu no modo layout."""
    import pypdf

    chamadas: list[int] = []
    original = pypdf.PageObject._layout_mode_text

    def layout(self, *args, **kwargs):
        chamadas.append(1)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(pypdf.PageObject, "_layout_mode_text", layout)
    return chamadas


def test_leitor_generico_tem_teto_de_bytes_proprio_menor_que_o_geral():
    """O caminho genérico (pypdf) relê o arquivo com um teto de bytes MENOR (10 MB):
    um conteúdo de 12 MB passa pela conta geral (50 MB) e pelo pdfplumber (que não
    acha texto nem perfil), mas o pypdf o recusa."""
    pdf = _pdf_com_conteudo(_bomba(12 * MB))
    perfis_pdf.exigir_pdf_contido(pdf)                 # conta geral de 50 MB: aceita
    with pytest.raises(PdfRecusado) as erro:
        perfis_pdf.analisar_pdf(pdf)
    assert erro.value.status_http == 413
    assert "10 MB" in str(erro.value)                  # o teto do leitor genérico


def test_leitor_generico_conta_o_texto_extraido(sem_medidor, sem_guarda_do_layout,
                                                monkeypatch):
    """Antes, o texto que o pypdf extraía só era limitado pelos bytes: um PDF com
    lacunas enormes (modo layout) virava milhões de caracteres. Agora o texto
    extraído conta no mesmo teto de caracteres, página a página (aqui com a guarda do
    modo layout desligada: com ela, este PDF nem chega ao modo layout). Só 4 mil
    letras: quem estoura é o teto do texto COM os espaços, e a mensagem não cita um
    número que não foi o critério."""
    monkeypatch.setattr(perfis_pdf, "PDF_MAX_CARACTERES", 20_000)
    monkeypatch.setattr(perfis_pdf, "PDF_MAX_CARACTERES_PAGINA", 10_000)
    with pytest.raises(PdfRecusado) as erro:
        perfis_pdf.analisar_pdf(_lacunas(2_000))       # ~20 milhões de caracteres
    assert erro.value.status_http == 413
    assert "texto demais" in str(erro.value)
    assert "10.000" not in str(erro.value) and "20.000" not in str(erro.value)


def test_pagina_comum_continua_no_modo_layout(sem_medidor, modo_layout):
    """O modo layout alinha as colunas (a estratégia TABELA depende dele): numa página
    comum, ele continua sendo usado."""
    corpo = b"BT /F1 10 Tf " + b"".join(
        b"1 0 0 1 72 %d Tm (Ana Maria Souza %d 34) Tj " % (700 - 14 * i, i)
        for i in range(5)) + b"ET"
    perfis_pdf.analisar_pdf(_pdf_paginas(corpo))
    assert modo_layout == [1]


@pytest.mark.parametrize("caso", ["fonte_de_fracao_de_ponto", "lacuna_enorme_fonte_comum",
                                  "letras_demais_numa_linha"])
def test_pagina_arriscada_e_lida_so_no_modo_simples(sem_medidor, modo_layout, caso):
    """O modo layout do pypdf monta a página inteira antes de qualquer conta (centenas
    de MB num PDF de poucos KB). Com o que o pdfplumber já mediu da página — linha longa
    demais na grade do layout, ou letras miúdas demais —, o genérico lê só no modo
    simples: sem recusa, sem o custo. Antes: modo layout e recusa por texto demais."""
    pdf = {
        # 4 mil letras de 0,01 pt: cada lacuna viraria 10 mil espaços.
        "fonte_de_fracao_de_ponto": lambda: _lacunas(2_000),
        # Fonte de 10 pt, mas 6 mil pontos de lacuna em cada linha (~1.100 colunas).
        "lacuna_enorme_fonte_comum": lambda: _lacunas(300, tamanho=10, lacuna=6_000),
        # Uma linha com 600 letras soltas (o modo layout emenda o texto da linha com
        # custo quadrático).
        "letras_demais_numa_linha": lambda: _pdf_paginas(b"BT /F1 10 Tf " + b"".join(
            b"1 0 0 1 %d 400 Tm (a) Tj " % (12 * k) for k in range(600)) + b"ET"),
    }[caso]()
    analise = perfis_pdf.analisar_pdf(pdf)
    assert analise is not None
    assert modo_layout == []


def test_pagina_que_o_pdfplumber_nao_mediu_e_lida_so_no_modo_simples(sem_medidor,
                                                                      modo_layout,
                                                                      monkeypatch):
    """Sem a medida (o pdfplumber falhou), o modo simples é o seguro."""
    def pdfplumber_falha(_conteudo):
        raise RuntimeError("estrutura que o pdfplumber não lê")

    monkeypatch.setattr(perfis_pdf, "extrair_paginas", pdfplumber_falha)
    perfis_pdf.analisar_pdf(_lacunas(2_000))
    assert modo_layout == []


def test_texto_do_leitor_generico_dentro_do_teto_passa(sem_medidor, monkeypatch):
    """Um relatório textual pequeno que só o genérico lê passa normalmente."""
    monkeypatch.setattr(perfis_pdf, "extrair_paginas", lambda _c: [])   # sem perfil
    analise = perfis_pdf.analisar_pdf(_pdf_paginas(_texto(2_000)))
    assert analise is not None


def test_texto_demais_pelo_leitor_generico_e_recusado(sem_medidor, monkeypatch):
    """Sem perfil (o pdfplumber não produziu linhas), o texto extraído pelo pypdf
    estoura o teto de caracteres — a lacuna que o medidor e o pdfplumber não viam."""
    monkeypatch.setattr(perfis_pdf, "extrair_paginas", lambda _c: [])
    monkeypatch.setattr(perfis_pdf, "PDF_MAX_CARACTERES", 5_000)
    monkeypatch.setattr(perfis_pdf, "PDF_MAX_CARACTERES_PAGINA", 5_000)
    with pytest.raises(PdfRecusado) as erro:
        perfis_pdf.analisar_pdf(_pdf_paginas(_texto(20_000)))
    assert erro.value.status_http == 413
    assert "texto demais" in str(erro.value)


def test_fax_disfarcado_de_conteudo_e_recusado(sem_medidor):
    pdf = _pdf_com_conteudo(b"\x00" * 64, b"<< /Filter /CCITTFaxDecode "
                            b"/DecodeParms << /K -1 /Columns 1728 >> >>")
    with pytest.raises(PdfRecusado) as erro:
        perfis_pdf.analisar_pdf(pdf)
    assert erro.value.status_http == 422


def test_leitor_generico_tambem_gasta_do_orcamento(teto_4mb, sem_medidor, monkeypatch):
    """Sem perfil (o pdfplumber falhou), o pypdf lê o arquivo: o mesmo orçamento. (Sem
    a medida do pdfplumber, o genérico lê no modo simples, que nem abre o conteúdo de
    uma página sem fonte: a página aqui tem fonte.)"""
    def pdfplumber_falha(_conteudo):
        raise RuntimeError("estrutura que o pdfplumber não lê")

    monkeypatch.setattr(perfis_pdf, "extrair_paginas", pdfplumber_falha)
    with pytest.raises(PdfRecusado) as erro:
        perfis_pdf.analisar_pdf(_pdf_paginas(b" " * (8 * MB)))
    assert erro.value.status_http == 413


def test_recusa_engolida_por_um_leitor_continua_valendo(teto_4mb, sem_medidor, monkeypatch):
    from pdfminer.pdftypes import PDFStream
    from pdfminer.psparser import LIT

    def leitor_que_engole(_conteudo):
        try:
            PDFStream({"Filter": LIT("FlateDecode")}, _bomba()).get_data()
        except Exception:  # noqa: BLE001 — o leitor engole; a análise não
            pass
        return []

    monkeypatch.setattr(perfis_pdf, "extrair_paginas", leitor_que_engole)
    with pytest.raises(PdfRecusado) as erro:
        perfis_pdf.analisar_pdf(_pdf_com_conteudo(_bomba()))
    assert "descompactado" in str(erro.value)


def test_fora_da_analise_o_pdfminer_fica_como_era(teto_4mb):
    """As funções trocadas só limitam com orçamento no contexto: fora de
    ``analisar_pdf`` (ou noutro contexto, como outra requisição) nada muda."""
    import contextvars

    from pdfminer.pdftypes import PDFStream
    from pdfminer.psparser import LIT

    perfis_pdf._instalar_tetos()

    def ler():
        return len(PDFStream({"Filter": LIT("FlateDecode")}, _bomba(5 * MB)).get_data())

    assert ler() == 5 * MB
    with perfis_pdf._orcamento_da_analise():
        assert contextvars.Context().run(ler) == 5 * MB
        with pytest.raises(PdfRecusado):
            ler()
    assert ler() == 5 * MB


def test_orcamento_e_de_cada_analise(teto_4mb):
    """3 MB por análise: cabe em cada uma — em sequência e em paralelo."""
    from concurrent.futures import ThreadPoolExecutor

    pdf = _pdf_com_conteudo(_bomba(3 * MB))
    perfis_pdf.analisar_pdf(pdf)
    perfis_pdf.analisar_pdf(pdf)
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(perfis_pdf.analisar_pdf, [pdf] * 4))


# --- O prazo da análise --------------------------------------------------------
# Os tetos limitam o que se monta, não o tempo: dentro de todos eles um PDF ainda
# segurava o processo por dezenas de segundos. O orçamento tem um prazo para a análise
# inteira, olhado a cada tantas contas, a cada página e entre as etapas.

class _Relogio:
    """Relógio falso: cada consulta avança ``passo`` segundos (``pular`` avança já)."""

    def __init__(self, passo: float = 0.0):
        self.agora, self.passo, self.consultas = 0.0, passo, 0

    def __call__(self) -> float:
        self.consultas += 1
        self.agora += self.passo
        return self.agora

    def pular(self, segundos: float) -> None:
        self.agora += segundos


@pytest.fixture()
def relogio(monkeypatch):
    falso = _Relogio()
    monkeypatch.setattr(perfis_pdf, "_agora", falso)
    monkeypatch.setattr(perfis_pdf, "PDF_MAX_SEGUNDOS", 10)
    return falso


def test_prazo_recusa_no_meio_da_leitura_de_uma_pagina(sem_medidor, espiao_pdfplumber,
                                                        relogio):
    """Cada consulta ao relógio "leva" 1 s e o prazo é de 10 s: a recusa vem de dentro do
    pdfplumber, no meio da página (8 mil caracteres, o relógio olhado a cada 256), sem
    ler o resto."""
    relogio.passo = 1.0
    with pytest.raises(PdfRecusado) as erro:
        perfis_pdf.analisar_pdf(_pdf_paginas(_texto(8_000)))
    assert erro.value.status_http == 413
    assert "pesado demais" in str(erro.value)
    assert "10 segundos" in str(erro.value)
    assert espiao_pdfplumber == [1]
    assert relogio.consultas < 8_000 // perfis_pdf._PASSOS_PRAZO   # parou no meio


def test_prazo_esgotado_nao_comeca_a_analise_do_texto(sem_medidor, relogio, monkeypatch):
    """A extração do genérico gastou o prazo: a análise do texto nem começa."""
    from app.services import importacao

    analisados: list[str] = []
    monkeypatch.setattr(perfis_pdf, "extrair_paginas", lambda _c: [])   # sem perfil

    def extrair_devagar(_conteudo):
        relogio.pular(60)
        return "Ana Maria Souza 12 34"

    monkeypatch.setattr(importacao, "extrair_texto_pdf", extrair_devagar)
    monkeypatch.setattr(importacao, "analisar_texto",
                        lambda texto, plataforma=None: analisados.append(texto))
    with pytest.raises(PdfRecusado) as erro:
        perfis_pdf.analisar_pdf(_pdf_paginas(_texto(10)))
    assert erro.value.status_http == 413
    assert "pesado demais" in str(erro.value)
    assert analisados == []


def test_analise_do_texto_que_passa_do_prazo_tambem_e_recusada(sem_medidor, relogio,
                                                               monkeypatch):
    from app.services import importacao

    original = importacao.analisar_texto
    monkeypatch.setattr(perfis_pdf, "extrair_paginas", lambda _c: [])

    def analisar_devagar(texto, plataforma=None):
        relogio.pular(60)
        return original(texto, plataforma)

    monkeypatch.setattr(importacao, "analisar_texto", analisar_devagar)
    with pytest.raises(PdfRecusado) as erro:
        perfis_pdf.analisar_pdf(_pdf_paginas(_texto(10)))
    assert "pesado demais" in str(erro.value)


def test_dentro_do_prazo_nada_muda(relogio):
    """Relógio parado: o mesmo PDF passa (o prazo só recusa quando o tempo acaba)."""
    perfis_pdf.analisar_pdf(_pdf_real(3))
    perfis_pdf.analisar_pdf(_pdf_paginas(_texto(8_000)))
    assert relogio.consultas > 0


def test_leitura_de_recuperacao_da_o_mesmo_resultado_do_pdfminer():
    """``decompress_corrupted`` limitado (em blocos) = o original (byte a byte)."""
    import random
    import zlib as _zlib

    from pdfminer import pdftypes

    perfis_pdf._instalar_tetos()
    original = pdftypes.decompress_corrupted.__wrapped__
    sorteio = random.Random(17)
    texto = bytes(sorteio.choice(b"abcdefgh \n") for _ in range(60_000))
    compacto = _zlib.compress(texto, 6)
    estragado = bytearray(compacto)
    estragado[len(compacto) // 2] ^= 0xFF
    casos = [compacto[:-2], compacto[:len(compacto) // 3], compacto[:-4] + b"\x00\x00\x00\x00",
             bytes(estragado)]
    with perfis_pdf._orcamento_da_analise() as orcamento:
        for dado in casos:
            try:
                esperado = original(dado)
            except _zlib.error:
                esperado = "erro"
            try:
                obtido = perfis_pdf._inflar_corrompido(orcamento, None, dado)
            except _zlib.error:
                obtido = "erro"
            assert obtido == esperado


def test_runlength_limitado_da_o_mesmo_resultado_do_pdfminer():
    from pdfminer.runlength import rldecode

    casos = [bytes([2, 65, 66, 67, 254, 68, 128, 1, 2]), bytes([0, 9]) * 50,
             bytes([129, 32]) * 10 + bytes([3, 1, 2, 3, 4]), b""]
    with perfis_pdf._orcamento_da_analise() as orcamento:
        for dado in casos:
            assert perfis_pdf._rl_com_teto(orcamento, None, dado) == rldecode(dado)


# --- O que o pdfplumber MONTA: caracteres, desenhos, mapas --------------------
# Dentro do teto do descompactado, um PDF de 1 KB enchia a memória: o pdfplumber
# gasta ~2 KB por caractere, um conteúdo compartilhado por várias páginas conta uma
# vez só na descompactação e as páginas só eram liberadas no fim.

_FONTE = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"


def _pdf_paginas(conteudo: bytes, paginas: int = 1, recursos: bytes = b"/Font << /F1 3 0 R >>",
                 extras: tuple[bytes, ...] = (), fonte: bytes = _FONTE) -> bytes:
    """``paginas`` páginas que apontam TODAS para o mesmo fluxo de conteúdo (obj 4)."""
    corpo = zlib.compress(conteudo, 9)
    primeira = 5 + len(extras)
    filhos = b" ".join(b"%d 0 R" % (primeira + i) for i in range(paginas))
    return _montar([
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [" + filhos + b"] /Count %d >>" % paginas,
        fonte,
        b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(corpo) + corpo + b"\nendstream",
        *extras,
        *[b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
          b"/Resources << " + recursos + b" >> >>"] * paginas,
    ])


def _texto(caracteres: int) -> bytes:
    return b"BT /F1 1 Tf 10 10 Td (" + b"a " * (caracteres // 2) + b") Tj ET"


@pytest.fixture()
def tetos_pequenos(monkeypatch):
    monkeypatch.setattr(perfis_pdf, "PDF_MAX_CARACTERES", 20_000)
    monkeypatch.setattr(perfis_pdf, "PDF_MAX_CARACTERES_PAGINA", 10_000)
    monkeypatch.setattr(perfis_pdf, "PDF_MAX_DESENHOS", 400)
    monkeypatch.setattr(perfis_pdf, "PDF_MAX_DESENHOS_PAGINA", 200)


def test_conteudo_compartilhado_por_varias_paginas_conta_em_cada_uma(tetos_pequenos):
    perfis_pdf.analisar_pdf(_pdf_paginas(_texto(8_000), paginas=2))   # 16 mil: cabe
    with pytest.raises(PdfRecusado) as erro:                           # 32 mil: não
        perfis_pdf.analisar_pdf(_pdf_paginas(_texto(8_000), paginas=4))
    assert erro.value.status_http == 413
    assert "texto demais" in str(erro.value)


def test_texto_demais_numa_pagina_so(tetos_pequenos):
    with pytest.raises(PdfRecusado) as erro:
        perfis_pdf.analisar_pdf(_pdf_paginas(_texto(12_000)))
    assert erro.value.status_http == 413
    assert "numa página" in str(erro.value)


def test_formulario_desenhado_muitas_vezes_conta_cada_desenho(tetos_pequenos):
    formulario = zlib.compress(b"BT /F1 1 Tf 10 10 Td (" + b"a" * 1_000 + b") Tj ET", 9)
    extra = (b"<< /Type /XObject /Subtype /Form /BBox [0 0 612 792] "
             b"/Resources << /Font << /F1 3 0 R >> >> /Length %d /Filter /FlateDecode >>"
             b"\nstream\n" % len(formulario) + formulario + b"\nendstream")
    pdf = _pdf_paginas(b"/Fm1 Do\n" * 30, recursos=b"/Font << /F1 3 0 R >> /XObject "
                       b"<< /Fm1 5 0 R >>", extras=(extra,))
    with pytest.raises(PdfRecusado) as erro:
        perfis_pdf.analisar_pdf(pdf)
    assert "texto demais" in str(erro.value)


def test_desenhos_demais_sao_recusados(tetos_pequenos):
    with pytest.raises(PdfRecusado) as erro:
        perfis_pdf.analisar_pdf(_pdf_paginas(b"0 0 1 1 re f\n" * 300))
    assert erro.value.status_http == 413
    assert "desenhos demais" in str(erro.value)


def test_desenhos_continuam_lidos_dentro_do_orcamento():
    """O pdfminer descobre quantos operandos cada operação tira da pilha pela aridade
    da função: as operações contadas continuam desenhando (retângulo, linha)."""
    import pdfplumber

    pdf = _pdf_paginas(b"0 0 10 10 re f\n20 20 m 30 30 l S\n" + _texto(10))
    with perfis_pdf._orcamento_da_analise() as orcamento:
        with pdfplumber.open(io.BytesIO(pdf)) as documento:
            pagina = documento.pages[0]
            assert len(pagina.rects) == 1
            assert len(pagina.lines) == 1
            assert len(pagina.chars) == 10
        assert orcamento.tetos[2] - orcamento.desenhos == 3    # re, m, l
        assert orcamento.tetos[0] - orcamento.caracteres == 10


def test_mapa_de_caracteres_com_intervalo_enorme_e_recusado(monkeypatch):
    monkeypatch.setattr(perfis_pdf, "PDF_MAX_ENTRADAS_MAPA", 1_000)
    mapa = zlib.compress(b"/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
                         b"1 begincodespacerange <0000> <FFFF> endcodespacerange\n"
                         b"1 beginbfrange <0000> <1387> <0041> endbfrange\n"
                         b"endcmap CMapName currentdict /CMap defineresource pop end end")
    extra = (b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(mapa) + mapa
             + b"\nendstream")
    pdf = _pdf_paginas(_texto(10), extras=(extra,),
                       fonte=b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
                             b"/ToUnicode 5 0 R >>")
    with pytest.raises(PdfRecusado) as erro:
        perfis_pdf.analisar_pdf(pdf)
    assert erro.value.status_http == 422


def test_cada_pagina_e_liberada_antes_de_ler_a_proxima(monkeypatch):
    """Antes, todas eram lidas e só no fim fechadas: a memória de todas se somava."""
    import pdfplumber.page

    eventos: list[tuple[str, int]] = []
    fechar_original = pdfplumber.page.Page.close
    ler_original = pdfplumber.page.Page.extract_words

    def fechar(self):
        eventos.append(("fecha", self.page_number))
        return fechar_original(self)

    def ler(self, *args, **kwargs):
        eventos.append(("lê", self.page_number))
        return ler_original(self, *args, **kwargs)

    monkeypatch.setattr(pdfplumber.page.Page, "close", fechar)
    monkeypatch.setattr(pdfplumber.page.Page, "extract_words", ler)
    paginas = perfis_pdf.extrair_paginas(_pdf_real(3))
    assert [p.numero for p in paginas] == [1, 2, 3]
    assert eventos[:6] == [("lê", 1), ("fecha", 1), ("lê", 2), ("fecha", 2),
                           ("lê", 3), ("fecha", 3)]


def test_paginas_demais_nao_percorre_o_arquivo_inteiro_ao_fechar(monkeypatch):
    """Antes, recusado por páginas demais, o ``pdf.close()`` do pdfplumber criava
    TODAS as páginas do arquivo (sem teto) para fechá-las."""
    import pdfplumber.page

    monkeypatch.setattr(perfis_pdf, "PDF_MAX_PAGINAS", 5)
    criadas: list[int] = []
    original = pdfplumber.page.Page.__init__

    def criar(self, *args, **kwargs):
        criadas.append(1)
        original(self, *args, **kwargs)

    monkeypatch.setattr(pdfplumber.page.Page, "__init__", criar)
    with pytest.raises(PdfRecusado):
        perfis_pdf.analisar_pdf(_pdf_paginas(_texto(10), paginas=40))
    assert criadas == []
