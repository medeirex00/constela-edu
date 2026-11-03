"""Planilha inflada (bomba de descompressão) e célula gigante — regressão do e97.

Antes: as rotas de upload da escola só conferiam o tamanho COMPRIMIDO (10 MB). Um
.xlsx de 83 KB com 84 MB de texto repetido levou o worker de 157 MB para 1,5 GB na
Lista Piloto, e 1 MB numa só célula prendia ~6 s de CPU no relatório do Matific
(casamento difuso do cabeçalho). Agora ``planilhas.exigir_xlsx_contido`` recusa o
arquivo ANTES do openpyxl (413/400) e o texto de cada célula é cortado na leitura.

Tudo aqui é fictício e gerado em memória.
"""
import io
import os
import struct
import time
import tracemalloc
import zipfile
from difflib import SequenceMatcher
from xml.sax.saxutils import escape

import openpyxl
import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_senha
from app.main import app
from app.models import Usuario
from app.services import lista_piloto, planilhas
from app.services.importacao import _semelhante
from app.sync import orchestrator
from app.sync.interfaces import ArquivoObtido, ErroConector

CT_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MB = 1024 * 1024
# Teto de tempo dos testes "rápidos": 2 s numa máquina comum. No CI (cobertura ligada,
# runner compartilhado) tudo fica 2–3x mais lento, e o teto fixo de 2 s reprovou o
# espelho do CI por 0,2–0,9 s (e97). Os casos patológicos levavam 7–33 s; as asserções
# de orçamento (contagem de células/linhas e status 413) continuam determinísticas e
# pegam a regressão mesmo com o teto folgado. TESTE_TETO_TEMPO_S sobrepõe o valor.
TETO_S = float(os.environ.get("TESTE_TETO_TEMPO_S") or (12 if os.environ.get("CI") else 2))

_PARTES = {
    "[Content_Types].xml": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
        'relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-'
        'officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/></Types>'),
    "_rels/.rels": (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'),
    "xl/workbook.xml": (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Planilha1" sheetId="1" r:id="rId1"/></sheets></workbook>'),
    "xl/_rels/workbook.xml.rels": (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/sharedStrings" Target="sharedStrings.xml"/></Relationships>'),
    "xl/worksheets/sheet1.xml": (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData><row r="1"><c r="A1" t="s"><v>0</v></c></row></sheetData></worksheet>'),
}


def _xlsx_celula_gigante(tamanho: int, letra: bytes = b"A") -> bytes:
    """Um .xlsx válido com UMA célula (A1) de ``tamanho`` bytes na sharedStrings."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for nome, texto in _PARTES.items():
            z.writestr(nome, texto)
        with z.open("xl/sharedStrings.xml", "w", force_zip64=True) as f:
            f.write(b'<?xml version="1.0" encoding="UTF-8"?><sst xmlns="http://schemas.'
                    b'openxmlformats.org/spreadsheetml/2006/main" count="1" uniqueCount="1">'
                    b"<si><t>")
            restante = tamanho
            while restante > 0:
                pedaco = min(MB, restante)
                f.write(letra * pedaco)
                restante -= pedaco
            f.write(b"</t></si></sst>")
    return buf.getvalue()


def _xlsx_bruto(linhas: list[list]) -> bytes:
    """.xlsx escrito à mão (strings inline). Quem ataca não usa o openpyxl, que corta
    a célula em 32.767 caracteres ao GRAVAR — ao LER, ele devolve o texto inteiro."""
    corpo = []
    for r, linha in enumerate(linhas, 1):
        celulas = []
        for c, valor in enumerate(linha):
            ref = f"{chr(ord('A') + c)}{r}"
            if isinstance(valor, (int, float)):
                celulas.append(f'<c r="{ref}"><v>{valor}</v></c>')
            else:
                celulas.append(f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">'
                               f"{escape(valor)}</t></is></c>")
        corpo.append(f'<row r="{r}">{"".join(celulas)}</row>')
    partes = dict(_PARTES)
    partes["xl/worksheets/sheet1.xml"] = (
        '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.'
        'openxmlformats.org/spreadsheetml/2006/main"><sheetData>' + "".join(corpo)
        + "</sheetData></worksheet>")
    partes["xl/sharedStrings.xml"] = (
        '<?xml version="1.0" encoding="UTF-8"?><sst xmlns="http://schemas.openxmlformats.'
        'org/spreadsheetml/2006/main" count="0" uniqueCount="0"/>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for nome, texto in partes.items():
            z.writestr(nome, texto)
    return buf.getvalue()


def _descomprimido(conteudo: bytes) -> int:
    with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
        return sum(i.file_size for i in z.infolist())


def _xlsx_matific(primeira_celula: str = "Alunos", turma: str = "5 ANO B (300)") -> bytes:
    """Relatório do Matific mínimo (cabeçalho + 1 aluno fictício)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Relatório de Atividade do Aluno"])
    ws.append(["Turma", turma])
    ws.append([primeira_celula, "Total de atividades concluídas", "Pontuação média"])
    ws.append(["Toda a turma", 10, 0.5])
    ws.append(["Teobaldo Ficticio Exemplar", 10, 0.5])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture()
def bomba() -> bytes:
    conteudo = _xlsx_celula_gigante(80 * MB)
    assert len(conteudo) < 100_000 and _descomprimido(conteudo) > 80 * MB
    return conteudo


@pytest.fixture()
def coordenador(db, escola_completa) -> TestClient:
    """Papel COORDENADOR (o achado vale para admin e coordenador da escola)."""
    db.add(Usuario(escola_id=escola_completa["escola"].id, nome="Coord Ficticio",
                   email="coord.inflada@teste.local", senha_hash=hash_senha("s3nh4"),
                   cargo="coordenador"))
    db.commit()
    c = TestClient(app)
    r = c.post("/api/v1/auth/login",
               data={"username": "coord.inflada@teste.local", "password": "s3nh4"})
    assert r.status_code == 200, r.text
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


# --- O auxiliar único ----------------------------------------------------------------

def test_bomba_recusada_sem_descomprimir_e_sem_alocar(bomba):
    tracemalloc.start()
    t0 = time.monotonic()
    with pytest.raises(planilhas.PlanilhaRecusada) as erro:
        planilhas.exigir_xlsx_contido(bomba)
    dt = time.monotonic() - t0
    _, pico = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert erro.value.status_http == 413
    assert "30 MB" in str(erro.value)
    assert dt < TETO_S, dt
    assert pico < 5 * MB, pico


def test_razao_de_compressao_anomala_recusada_abaixo_do_teto():
    conteudo = _xlsx_celula_gigante(5 * MB)          # 5 MB < 30 MB, mas infla ~1.000×
    with pytest.raises(planilhas.PlanilhaRecusada) as erro:
        planilhas.exigir_xlsx_contido(conteudo)
    assert erro.value.status_http == 413
    assert "100 vezes" in str(erro.value)


def test_arquivo_pequeno_nao_tem_razao_conferida():
    planilhas.exigir_xlsx_contido(_xlsx_celula_gigante(600 * 1024))   # < 1 MB: passa


def test_planilha_legitima_passa():
    planilhas.exigir_xlsx_contido(_xlsx_matific())


def test_parser_do_matific_tem_a_guarda_dentro(bomba, monkeypatch):
    """Quem chama ``analisar_planilha`` direto (sem a rota nem a sync) também está
    protegido: a guarda roda ANTES do openpyxl, dentro do parser."""
    import openpyxl as modulo

    def _nao_abre(*a, **k):
        raise AssertionError("o openpyxl não pode abrir a planilha inflada")

    monkeypatch.setattr(modulo, "load_workbook", _nao_abre)
    t0 = time.monotonic()
    with pytest.raises(planilhas.PlanilhaRecusada) as erro:
        planilhas.analisar_planilha(bomba)
    assert erro.value.status_http == 413
    assert time.monotonic() - t0 < TETO_S


def test_nao_zip_passa_para_o_leitor_recusar():
    planilhas.exigir_xlsx_contido(b"isto nao e um zip")
    planilhas.exigir_xlsx_contido(b"")


@pytest.mark.parametrize("compactacao", [zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA])
def test_compactacao_que_o_excel_nao_gera_e_recusada_antes_de_ler(compactacao):
    """bzip2/LZMA: o ``zipfile`` descomprime sem teto por leitura — nem chega a ler."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compactacao) as z:
        for nome, texto in _PARTES.items():
            z.writestr(nome, texto)
    with pytest.raises(planilhas.PlanilhaRecusada) as erro:
        planilhas.exigir_xlsx_contido(buf.getvalue())
    assert erro.value.status_http == 400


def test_tamanho_declarado_mentiroso_nao_aloca_alem_do_declarado():
    """O zip DECLARA 100 bytes, mas o fluxo infla 10 MB: a leitura limitada para no
    declarado (e o CRC acusa), sem materializar o fluxo inteiro."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/sharedStrings.xml", b"A" * (10 * MB))
    dados = bytearray(buf.getvalue())
    local = dados.find(b"PK\x03\x04")
    central = dados.find(b"PK\x01\x02")
    struct.pack_into("<I", dados, local + 22, 100)     # tamanho descomprimido (local)
    struct.pack_into("<I", dados, central + 24, 100)   # idem (diretório central)
    with zipfile.ZipFile(io.BytesIO(bytes(dados))) as z:
        assert z.infolist()[0].file_size == 100
    tracemalloc.start()
    planilhas.exigir_xlsx_contido(bytes(dados))        # corrompido: o leitor recusa
    _, pico = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert pico < 5 * MB, pico


def test_celula_limitada_so_corta_texto():
    longo = "x" * (planilhas.MAX_TEXTO_CELULA + 50)
    assert len(planilhas.limitar_celula(longo)) == planilhas.MAX_TEXTO_CELULA
    assert planilhas.limitar_celula("Ana") == "Ana"
    assert planilhas.limitar_celula(12345) == 12345
    assert planilhas.limitar_celula(None) is None


# --- As rotas (papel coordenador) ----------------------------------------------------

def test_rota_relatorio_matific_recusa_bomba_rapido(coordenador, escola_completa, bomba):
    eid = escola_completa["escola"].id
    t0 = time.monotonic()
    r = coordenador.post(f"/api/v1/escolas/{eid}/importacoes/analisar",
                         files={"arquivo": ("relatorio.xlsx", bomba, CT_XLSX)})
    dt = time.monotonic() - t0
    assert r.status_code == 413, r.text
    assert "descompactada" in r.json()["detail"]
    assert dt < TETO_S, dt


@pytest.mark.parametrize("acao", ["analisar", "confirmar"])
def test_rota_lista_piloto_recusa_bomba_rapido(coordenador, escola_completa, bomba, acao):
    eid = escola_completa["escola"].id
    t0 = time.monotonic()
    r = coordenador.post(f"/api/v1/escolas/{eid}/importacoes/matriculas/{acao}",
                         files={"arquivo": ("lista.xlsx", bomba, CT_XLSX)})
    dt = time.monotonic() - t0
    assert r.status_code == 413, r.text   # antes: 200 com +1,3 GB de pico
    assert dt < TETO_S, dt


def test_rota_relatorio_matific_com_celula_grande_responde_rapido(coordenador,
                                                                  escola_completa):
    """Abaixo de 1 MB a razão não é conferida e o arquivo chega ao openpyxl: o corte
    da célula impede o casamento difuso de rodar sobre 900 KB (antes ~5 s)."""
    conteudo = _xlsx_celula_gigante(900 * 1024, b"A")
    eid = escola_completa["escola"].id
    t0 = time.monotonic()
    r = coordenador.post(f"/api/v1/escolas/{eid}/importacoes/analisar",
                         files={"arquivo": ("relatorio.xlsx", conteudo, CT_XLSX)})
    dt = time.monotonic() - t0
    assert r.status_code == 400, r.text           # não é relatório do Matific
    assert dt < TETO_S, dt


def test_rota_relatorio_matific_legitimo_continua(coordenador, escola_completa):
    eid = escola_completa["escola"].id
    r = coordenador.post(f"/api/v1/escolas/{eid}/importacoes/analisar",
                         files={"arquivo": ("relatorio.xlsx", _xlsx_matific(), CT_XLSX)})
    assert r.status_code == 200, r.text
    assert r.json()["plataforma"] == "matific"
    assert r.json()["total_linhas"] == 1


# --- Parser: célula gigante e casamento difuso ----------------------------------------

def test_turma_com_espacos_internos_nao_dispara_regex_quadratica():
    """O valor de "Turma" passa por ``\\s*\\(\\d+\\)\\s*$``: com 100 mil espaços no
    meio, a regex custava ~19 s (quadrática). Cortado na leitura, é instantâneo."""
    conteudo = _xlsx_bruto([
        ["Relatório de Atividade do Aluno"],
        ["Turma", "A" + " " * 100_000 + "A"],
        ["Alunos", "Total de atividades concluídas", "Pontuação média"],
        ["Toda a turma", 10, 0.5],
        ["Teobaldo Ficticio Exemplar", 10, 0.5],
    ])
    assert _descomprimido(conteudo) < 1024 * 1024        # passa pelo teto do pacote
    t0 = time.monotonic()
    analise = planilhas.analisar_planilha(conteudo)
    assert time.monotonic() - t0 < TETO_S
    assert analise.turma_detectada == "A"
    assert [linha.nome for linha in analise.linhas] == ["Teobaldo Ficticio Exemplar"]


def test_semelhante_texto_longo_e_falso_e_rapido():
    """2 MB contra os sinônimos da coluna de nome: antes ~0,8 s de SequenceMatcher
    POR sinônimo; o teto exato da razão (2·min/soma) já decide False."""
    from app.services.importacao import _COL_NOME
    longo = "x" + "a" * 2_000_000
    t0 = time.monotonic()
    assert not any(_semelhante(longo, s) for s in _COL_NOME)
    assert time.monotonic() - t0 < TETO_S / 2


@pytest.mark.parametrize("texto,sinonimo", [
    ("aluno", "alunos"), ("alnuos", "alunos"), ("nome do aluno", "nome"),
    ("estudante", "estudantes"), ("x", "alunos"), ("atividades", "atividade"),
    ("nome completo", "nome completo do aluno"), ("pontuacao media", "pontuacao"),
])
def test_semelhante_decide_igual_ao_sequencematcher(texto, sinonimo):
    """O atalho pelo tamanho é um teto EXATO: a decisão não muda."""
    from app.services.importacao import _semelhante_forte
    esperado = (_semelhante_forte(texto, sinonimo)
                or SequenceMatcher(None, texto, sinonimo).ratio() >= 0.82)
    assert _semelhante(texto, sinonimo) == esperado


def test_lista_piloto_corta_celula_e_recusa_bomba(bomba):
    wb = openpyxl.Workbook()
    wb.active.append(["Nome", "x" * 50_000])
    buf = io.BytesIO()
    wb.save(buf)
    [(_, linhas)] = lista_piloto._abrir(buf.getvalue())
    assert len(linhas[0][1]) == planilhas.MAX_TEXTO_CELULA
    with pytest.raises(planilhas.PlanilhaRecusada):
        lista_piloto._abrir(bomba)
    # O serviço deixa a recusa subir (a rota responde 413 com a mensagem), sem 500.
    with pytest.raises(planilhas.PlanilhaRecusada):
        lista_piloto.analisar_matriculas(bomba)


# --- Sincronização --------------------------------------------------------------------

def test_sync_recusa_planilha_inflada_como_parser_incompativel(bomba):
    arquivo = ArquivoObtido(conteudo=bomba, nome_arquivo="relatorio.xlsx",
                            plataforma="matific", content_type=CT_XLSX)
    t0 = time.monotonic()
    with pytest.raises(ErroConector) as erro:
        orchestrator._parsear(arquivo)
    assert erro.value.codigo == "parser_incompativel"
    assert erro.value.recuperavel is False
    assert time.monotonic() - t0 < TETO_S


# --- Dimensão declarada enorme: o que a leitura PERCORRE -----------------------------
# Um .xlsx de ~2 KB que DECLARA <dimension ref="A1:XFD5000"/> e tem uma só célula em
# A5000 passa pelo teto do descomprimido. O openpyxl (read_only) entregava 5.000
# linhas de 16.384 colunas — completando as linhas que faltam e cada linha até a
# dimensão: 7 s e +655 MB no relatório do Matific, 33 s na Lista Piloto (e97). Uma
# célula na coluna XFD em cada linha fazia o mesmo sem a dimensão.

def _xlsx_folhas(folhas: list[tuple[str | None, str]]) -> bytes:
    """.xlsx escrito à mão com várias abas: (dimensão declarada ou None, miolo do
    <sheetData>)."""
    n = len(folhas)
    tipos = "".join(
        f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/'
        'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(1, n + 1))
    abas = "".join(f'<sheet name="Aba{i}" sheetId="{i}" r:id="rId{i}"/>'
                   for i in range(1, n + 1))
    relacoes = "".join(
        f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/'
        f'officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, n + 1))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr("[Content_Types].xml", _PARTES["[Content_Types].xml"].replace(
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.'
            'openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>', "", 1).replace(
            "</Types>", tipos + "</Types>"))
        z.writestr("_rels/.rels", _PARTES["_rels/.rels"])
        z.writestr("xl/workbook.xml", _PARTES["xl/workbook.xml"].replace(
            '<sheet name="Planilha1" sheetId="1" r:id="rId1"/>', abas))
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://'
                   'schemas.openxmlformats.org/package/2006/relationships">' + relacoes
                   + "</Relationships>")
        z.writestr("xl/sharedStrings.xml",
                   '<?xml version="1.0" encoding="UTF-8"?><sst xmlns="http://schemas.'
                   'openxmlformats.org/spreadsheetml/2006/main" count="0" uniqueCount="0"/>')
        for i, (dimensao, miolo) in enumerate(folhas, start=1):
            dim = f'<dimension ref="{dimensao}"/>' if dimensao else ""
            z.writestr(f"xl/worksheets/sheet{i}.xml",
                       '<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://'
                       'schemas.openxmlformats.org/spreadsheetml/2006/main">' + dim
                       + "<sheetData>" + miolo + "</sheetData></worksheet>")
    return buf.getvalue()


def _celula(ref: str, valor) -> str:
    if isinstance(valor, (int, float)):
        return f'<c r="{ref}"><v>{valor}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t>{escape(valor)}</t></is></c>'


def _uma_por_linha(coluna: str, linhas, valor=1) -> str:
    return "".join(f'<row r="{r}">{_celula(f"{coluna}{r}", valor)}</row>' for r in linhas)


def _dimensao_enorme(ultima_linha: int) -> bytes:
    """~2 KB: declara A1:XFD<ultima_linha> e tem UMA célula, em A<ultima_linha>."""
    conteudo = _xlsx_folhas([(f"A1:XFD{ultima_linha}",
                              _uma_por_linha("A", [ultima_linha]))])
    assert len(conteudo) < 4096
    return conteudo


def _xfd_em_cada_linha(linhas: int) -> bytes:
    """Sem dimensão: uma célula na coluna XFD (16.384) em cada linha."""
    return _xlsx_folhas([(None, _uma_por_linha("XFD", range(1, linhas + 1)))])


def _aba_read_only(conteudo: bytes):
    wb = openpyxl.load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    return wb, wb.worksheets[0]


def test_dimensao_declarada_nao_alarga_a_leitura():
    wb, ws = _aba_read_only(_dimensao_enorme(5000))
    assert ws.max_column == 16384 and ws.max_row == 5000   # o que o arquivo declara
    orcamento = planilhas.OrcamentoLeitura(10**9, 10**9)
    linhas = planilhas.linhas_contidas(ws, orcamento, 5000)
    wb.close()
    assert len(linhas) == 5000                 # a posição das linhas não muda
    assert linhas[-1] == [1]                   # só até a última célula preenchida
    assert all(linha == [] for linha in linhas[:-1])
    assert orcamento.linhas == 5000 and orcamento.celulas == 1

    wb, ws = _aba_read_only(_dimensao_enorme(5000))
    assert planilhas.linhas_contidas(ws, planilhas.OrcamentoLeitura(10**9, 10**9), 5000,
                                     manter_vazias=False) == [[1]]
    wb.close()


def test_celula_alem_do_teto_de_colunas_nao_alarga_a_linha():
    wb, ws = _aba_read_only(_xlsx_folhas([("A1:XFD1", '<row r="1">' + _celula("A1", "a")
                                           + _celula("C1", "b") + _celula("XFD1", "z")
                                           + "</row>")]))
    orcamento = planilhas.OrcamentoLeitura(10**9, 10**9)
    assert planilhas.linhas_contidas(ws, orcamento, 10) == [["a", None, "b"]]
    wb.close()
    assert orcamento.celulas == 3              # vazias no meio contam; à direita, não

    wb, ws = _aba_read_only(_xfd_em_cada_linha(5000))
    orcamento = planilhas.OrcamentoLeitura(10**9, 10**9)
    linhas = planilhas.linhas_contidas(ws, orcamento, 5000)
    wb.close()
    assert linhas == [[]] * 5000 and orcamento.celulas == 0


def test_orcamento_conta_as_celulas_vazias_percorridas():
    """Uma célula na coluna 256 (dentro do teto de colunas) em cada linha: cada linha
    percorre 256 células, ainda que só uma tenha conteúdo — e isso conta."""
    conteudo = _xlsx_folhas([(None, _uma_por_linha("IV", range(1, 50_001)))])
    t0 = time.monotonic()
    with pytest.raises(planilhas.PlanilhaRecusada) as erro:
        lista_piloto._abrir(conteudo)
    assert time.monotonic() - t0 < TETO_S
    assert erro.value.status_http == 413
    assert "linhas ou células demais" in str(erro.value)

    matific = _xlsx_folhas([(None, "".join(
        f'<row r="{r}">{_celula(f"A{r}", "Alunos")}{_celula(f"IV{r}", 1)}</row>'
        for r in range(1, 5001)))])
    t0 = time.monotonic()
    with pytest.raises(planilhas.PlanilhaRecusada):
        planilhas.analisar_planilha(matific)
    assert time.monotonic() - t0 < TETO_S


def test_orcamento_vale_para_o_arquivo_inteiro():
    """200 abas de ~150 bytes, cada uma com uma célula na última linha lida: por aba
    passava; somadas, as linhas vazias completadas estouram o orçamento do arquivo."""
    lista = _xlsx_folhas([("A1:XFD50000", _uma_por_linha("A", [50_000]))] * 200)
    t0 = time.monotonic()
    with pytest.raises(planilhas.PlanilhaRecusada):
        lista_piloto._abrir(lista)
    assert time.monotonic() - t0 < TETO_S

    matific = _xlsx_folhas([("A1:XFD5000", _uma_por_linha("A", [5000]))] * 200)
    t0 = time.monotonic()
    with pytest.raises(planilhas.PlanilhaRecusada):
        planilhas.analisar_planilha(matific)
    assert time.monotonic() - t0 < TETO_S


def test_relatorio_matific_legitimo_com_dimensao_declarada_continua():
    """A formatação aplicada à aba inteira (dimensão até XFD) não atrapalha o
    relatório real."""
    linhas = [["Relatório de Atividade do Aluno"], ["Turma", "5 ANO B (300)"],
              ["Alunos", "Total de atividades concluídas", "Pontuação média"],
              ["Toda a turma", 10, 0.5], ["Teobaldo Ficticio Exemplar", 10, 0.5]]
    miolo = "".join(
        f'<row r="{r}">' + "".join(_celula(f"{chr(ord('A') + c)}{r}", v)
                                   for c, v in enumerate(linha)) + "</row>"
        for r, linha in enumerate(linhas, start=1))
    analise = planilhas.analisar_planilha(_xlsx_folhas([("A1:XFD5000", miolo)]))
    assert analise.turma_detectada == "5 ANO B"
    assert [linha.nome for linha in analise.linhas] == ["Teobaldo Ficticio Exemplar"]
    assert analise.linhas[0].dados["pontuacao_media"] == 2.5


def test_rota_relatorio_matific_dimensao_enorme_rapida_e_sem_inflar(coordenador,
                                                                   escola_completa):
    eid = escola_completa["escola"].id
    conteudo = _dimensao_enorme(5000)
    tracemalloc.start()
    t0 = time.monotonic()
    r = coordenador.post(f"/api/v1/escolas/{eid}/importacoes/analisar",
                         files={"arquivo": ("relatorio.xlsx", conteudo, CT_XLSX)})
    dt = time.monotonic() - t0
    _, pico = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert r.status_code == 400, r.text        # não é relatório do Matific
    assert dt < TETO_S, dt                          # antes: ~7 s
    assert pico < 50 * MB, pico                # antes: +655 MB de pico


@pytest.mark.parametrize("acao,esperado", [("analisar", 200), ("confirmar", 400)])
def test_rota_lista_piloto_dimensao_enorme_rapida(coordenador, escola_completa, acao,
                                                  esperado):
    eid = escola_completa["escola"].id
    t0 = time.monotonic()
    r = coordenador.post(f"/api/v1/escolas/{eid}/importacoes/matriculas/{acao}",
                         files={"arquivo": ("lista.xlsx", _dimensao_enorme(50_000),
                                            CT_XLSX)})
    dt = time.monotonic() - t0
    assert r.status_code == esperado, r.text   # nenhuma turma reconhecida
    assert dt < TETO_S, dt                          # antes: ~33 s


@pytest.mark.parametrize("rota,linhas", [
    ("importacoes/analisar", 5000),
    ("importacoes/matriculas/analisar", 50_000),
])
def test_rota_celula_em_xfd_em_cada_linha_rapida(coordenador, escola_completa, rota,
                                                 linhas):
    eid = escola_completa["escola"].id
    t0 = time.monotonic()
    r = coordenador.post(f"/api/v1/escolas/{eid}/{rota}",
                         files={"arquivo": ("planilha.xlsx", _xfd_em_cada_linha(linhas),
                                            CT_XLSX)})
    dt = time.monotonic() - t0
    assert r.status_code in (200, 400), r.text
    assert dt < TETO_S, dt                          # antes: ~7 s (Matific) e ~33 s (Lista)


def test_rota_lista_piloto_recusa_quando_estoura_o_orcamento(coordenador,
                                                             escola_completa):
    eid = escola_completa["escola"].id
    conteudo = _xlsx_folhas([(None, _uma_por_linha("IV", range(1, 50_001)))])
    r = coordenador.post(f"/api/v1/escolas/{eid}/importacoes/matriculas/analisar",
                         files={"arquivo": ("lista.xlsx", conteudo, CT_XLSX)})
    assert r.status_code == 413, r.text        # recusa com a mensagem, não aviso
    assert "linhas ou células demais" in r.json()["detail"]


def test_sync_dimensao_enorme_rapida_e_orcamento_vira_parser_incompativel():
    arquivo = ArquivoObtido(conteudo=_dimensao_enorme(5000), nome_arquivo="r.xlsx",
                            plataforma="matific", content_type=CT_XLSX)
    t0 = time.monotonic()
    with pytest.raises(ValueError, match="não reconhecida"):
        orchestrator._parsear(arquivo)
    assert time.monotonic() - t0 < TETO_S

    estoura = _xlsx_folhas([("A1:XFD5000", _uma_por_linha("A", [5000]))] * 200)
    arquivo = ArquivoObtido(conteudo=estoura, nome_arquivo="r.xlsx",
                            plataforma="matific", content_type=CT_XLSX)
    with pytest.raises(ErroConector) as erro:
        orchestrator._parsear(arquivo)
    assert erro.value.codigo == "parser_incompativel"
    assert erro.value.recuperavel is False


# --- Lista Piloto em .xls (xlrd) -------------------------------------------------------
# Sem ``ragged_rows``, o xlrd completava TODA linha até a coluna mais à direita da
# aba: um .xls de 5,6 KB com uma célula em (65535, 255) virava 16,7 milhões de
# células — 33 s e +259 MB na Lista Piloto (e97).

_FIM, _LIVRE, _SETOR_FAT = 0xFFFFFFFE, 0xFFFFFFFF, 0xFFFFFFFD
CT_XLS = "application/vnd.ms-excel"


def _registro(op: int, dados: bytes = b"") -> bytes:
    return struct.pack("<HH", op, len(dados)) + dados


def _bof(tipo: int) -> bytes:
    return _registro(0x0809, struct.pack("<HHHHII", 0x0600, tipo, 0x0DBB, 0x07CC, 0, 6))


def _xls(celulas: list[tuple[int, int, str]], nome_aba: str = "1º Ano A") -> bytes:
    """.xls mínimo (BIFF8 num contêiner OLE2) com UMA aba de células de texto
    (LABEL): (linha, coluna, texto), base zero. Escrito à mão, como faria quem ataca."""
    folha = _bof(0x0010) + _registro(0x0200, struct.pack(
        "<IIHHH", 0, max(r for r, _, _ in celulas) + 1, 0, max(c for _, c, _ in celulas) + 1,
        0))
    for r, c, texto in celulas:
        t = texto.encode("latin-1")
        folha += _registro(0x0204, struct.pack("<HHHHB", r, c, 0, len(t), 0) + t)
    folha += _registro(0x000A)
    nome = nome_aba.encode("latin-1")
    cabeca = _bof(0x0005) + _registro(0x0042, struct.pack("<H", 1200))
    aba = _registro(0x0085, struct.pack("<IBBBB", 0, 0, 0, len(nome), 0) + nome)
    inicio_folha = len(cabeca) + len(aba) + 4
    aba = _registro(0x0085, struct.pack("<IBBBB", inicio_folha, 0, 0, len(nome), 0) + nome)
    fluxo = cabeca + aba + _registro(0x000A) + folha
    tamanho = len(fluxo)
    fluxo = fluxo.ljust(max(4096, -(-tamanho // 512) * 512), b"\x00")   # sem mini-fluxo
    n_dados = len(fluxo) // 512
    n_fat = 1
    while n_dados + n_fat + 1 > n_fat * 128:
        n_fat += 1
    fat = [i + 1 for i in range(n_dados - 1)] + [_FIM] + [_SETOR_FAT] * n_fat + [_FIM]
    fat += [_LIVRE] * (n_fat * 128 - len(fat))

    def entrada(nome_entrada: str, tipo: int, filho: int, setor: int, tam: int) -> bytes:
        n = (nome_entrada + "\x00").encode("utf-16-le")
        return (n.ljust(64, b"\x00") + struct.pack("<HBBiii", len(n), tipo, 1, -1, -1, filho)
                + b"\x00" * 36 + struct.pack("<II", setor, tam) + b"\x00" * 4)

    vazia = b"\x00" * 64 + struct.pack("<HBBiii", 0, 0, 0, -1, -1, -1) + b"\x00" * 48
    diretorio = (entrada("Root Entry", 5, 1, _FIM, 0)
                 + entrada("Workbook", 2, -1, 0, len(fluxo)) + vazia * 2)
    msat = [n_dados + i for i in range(n_fat)] + [_LIVRE] * (109 - n_fat)
    cabecalho = (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 16
                 + struct.pack("<HHHHH", 0x3E, 3, 0xFFFE, 9, 6) + b"\x00" * 6
                 + struct.pack("<IIIIIIIII", 0, n_fat, n_dados + n_fat, 0, 4096, _FIM, 0,
                               _FIM, 0)
                 + struct.pack("<109I", *msat))
    return cabecalho + fluxo + struct.pack(f"<{len(fat)}I", *fat) + diretorio


def _celulas_lista_piloto_xls() -> list[tuple[int, int, str]]:
    """Uma turma fictícia: metadados, títulos e dois alunos (o 2º sem RA)."""
    linhas = [["Escola: EMEF Ficticia"], ["Ano: 1º Ano A"], ["Turno: TARDE"],
              ["Professor: PROFESSORA FICTICIA"],
              ["N.º", "RA", "Nome", "Data de Nasc."],
              ["1", "900000001", "AGATHA VIOLETA FICTICIA", "14/08/2019"],
              ["2", "", "BENTO TEODORO FICTICIO", "02/03/2019"]]
    return [(r, c, v) for r, linha in enumerate(linhas) for c, v in enumerate(linha) if v]


def test_lista_piloto_xls_legitima_continua():
    analise = lista_piloto.analisar_matriculas(_xls(_celulas_lista_piloto_xls()), "L.xls")
    [turma] = analise.turmas
    assert (turma.nome, turma.turno, turma.professor) == (
        "1º Ano A", "tarde", "PROFESSORA FICTICIA")
    assert [(a.nome, a.numero_chamada, a.data_nascimento, a.ficha.get("ra"))
            for a in turma.alunos] == [
        ("AGATHA VIOLETA FICTICIA", 1, "2019-08-14", "900000001"),
        ("BENTO TEODORO FICTICIO", 2, "2019-03-02", None)]


def test_lista_piloto_xls_celula_no_canto_rapida_e_sem_inflar():
    conteudo = _xls(_celulas_lista_piloto_xls() + [(65535, 255, "x")])
    assert len(conteudo) < 8192
    tracemalloc.start()
    t0 = time.monotonic()
    analise = lista_piloto.analisar_matriculas(conteudo, "L.xls")
    dt = time.monotonic() - t0
    _, pico = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert dt < TETO_S, dt                          # antes: ~33 s
    assert pico < 50 * MB, pico                # antes: ~259 MB
    assert [len(t.alunos) for t in analise.turmas] == [2]   # a turma real continua


def test_lista_piloto_xls_coluna_256_em_cada_linha_estoura_o_orcamento():
    conteudo = _xls([(r, 255, "x") for r in range(50_000)])
    t0 = time.monotonic()
    with pytest.raises(planilhas.PlanilhaRecusada) as erro:
        lista_piloto._abrir(conteudo)
    assert time.monotonic() - t0 < TETO_S
    assert erro.value.status_http == 413


def test_rota_lista_piloto_xls_canto_rapida_e_orcamento_recusado(coordenador,
                                                                 escola_completa):
    eid = escola_completa["escola"].id
    t0 = time.monotonic()
    r = coordenador.post(f"/api/v1/escolas/{eid}/importacoes/matriculas/analisar",
                         files={"arquivo": ("lista.xls", _xls([(65535, 255, "x")]), CT_XLS)})
    assert r.status_code == 200, r.text        # nenhuma turma, aviso
    assert time.monotonic() - t0 < TETO_S
    r = coordenador.post(f"/api/v1/escolas/{eid}/importacoes/matriculas/analisar",
                         files={"arquivo": ("lista.xls",
                                            _xls([(i, 255, "x") for i in range(50_000)]),
                                            CT_XLS)})
    assert r.status_code == 413, r.text
    assert "linhas ou células demais" in r.json()["detail"]
