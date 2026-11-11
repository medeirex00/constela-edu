"""Lista Piloto que não abre (.ods do LibreOffice, arquivo corrompido ou de outro
formato): a prévia diz o que fazer, em português, sem a exceção crua do leitor.

Antes: ``lista_piloto.analisar_matriculas`` punha ``f"Não foi possível ler a planilha:
{exc}"`` nos avisos — no .ods (zip que não é do Excel), "There is no item named
'[Content_Types].xml' in the archive". Agora: o .ods é reconhecido pelo ``mimetype``
dentro do zip e o aviso manda salvar como .xlsx; o resto recebe o aviso genérico; o
erro técnico vai para o log (sem o nome do arquivo). Tudo fictício.
"""
import io
import logging
import zipfile

import pytest

from app.services import lista_piloto

CONTEUDO_ODS = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body>'
    '<office:spreadsheet><table:table table:name="1º Ano A"><table:table-row>'
    '<table:table-cell><text:p>Nome</text:p></table:table-cell></table:table-row>'
    '<table:table-row><table:table-cell><text:p>ALUNO FICTICIO</text:p></table:table-cell>'
    '</table:table-row></table:table></office:spreadsheet></office:body>'
    '</office:document-content>')


def _ods() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet",
                   compress_type=zipfile.ZIP_STORED)
        z.writestr("content.xml", CONTEUDO_ODS, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("META-INF/manifest.xml", '<?xml version="1.0"?><manifest:manifest '
                   'xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>')
    return buf.getvalue()


def _zip_qualquer() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("leia-me.txt", "não é planilha")
    return buf.getvalue()


def _sem_texto_tecnico(avisos: list[str]) -> None:
    texto = " ".join(avisos)
    for tecnico in ("Content_Types", "archive", "zip file", "Error", "xlrd", "BOF"):
        assert tecnico not in texto, texto


def test_ods_diz_para_salvar_como_xlsx(caplog):
    caplog.set_level(logging.WARNING, logger="app.services.lista_piloto")
    a = lista_piloto.analisar_matriculas(_ods(), "Lista Piloto 2026.ods")
    assert a.turmas == []
    _sem_texto_tecnico(a.avisos)
    assert a.avisos == [
        "A planilha está no formato do LibreOffice (.ods). Abra no LibreOffice, salve "
        "como Excel (.xlsx) e envie de novo."]
    # O erro técnico fica no log, sem o nome do arquivo (pode trazer nome de aluno).
    assert any("Lista Piloto ilegível" in r.getMessage() for r in caplog.records)
    assert not any("Lista Piloto 2026" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("conteudo", [
    b"isto nao e uma planilha",                       # texto renomeado
    _zip_qualquer(),                                  # zip que não é planilha
    b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64,   # .xls corrompido
], ids=["texto", "zip", "xls-corrompido"])
def test_arquivo_que_nao_abre_recebe_o_aviso_generico(conteudo):
    a = lista_piloto.analisar_matriculas(conteudo, "lista.xlsx")
    assert a.turmas == []
    _sem_texto_tecnico(a.avisos)
    assert a.avisos == [
        "Não foi possível ler a planilha. Abra o arquivo no Excel, salve como .xlsx e "
        "envie de novo."]


def test_rota_da_previa_responde_o_aviso_do_ods(cliente, escola_completa):
    escola_id = escola_completa["escola"].id
    r = cliente.post(f"/api/v1/escolas/{escola_id}/importacoes/matriculas/analisar",
                     files={"arquivo": ("Lista Piloto 2026.ods", _ods(),
                                        "application/vnd.oasis.opendocument.spreadsheet")})
    assert r.status_code == 200, r.text
    corpo = r.json()
    _sem_texto_tecnico(corpo["avisos"])
    assert any(".ods" in aviso and ".xlsx" in aviso for aviso in corpo["avisos"])
