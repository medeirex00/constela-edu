"""PEND-15 (REV-ALUNOS-1-script): o cabeçalho do script de limpeza do passivo de
eventos diz a EXCEÇÃO que o código aplica.

``deduplicar_eventos_por_conteudo`` deixa, em cada grupo de cópias, a que veio da
ficha absorvida — mas nunca tira a primeira leitura de uma ficha que tem releitura
do mesmo livro (``eventos.primeiras_ocorrencias``). O cabeçalho do script, que é o
que quem vai rodá-lo em produção lê, descrevia só a preferência. Dados fictícios.
"""
from scripts import deduplicar_eventos_por_conteudo as script


def test_o_cabecalho_do_script_diz_que_a_primeira_leitura_nunca_sai():
    doc = " ".join((script.__doc__ or "").split())
    assert "fica a que veio da ficha absorvida" in doc
    assert ("a primeira leitura de uma ficha que tem releitura do mesmo livro nunca sai "
            "(``eventos.primeiras_ocorrencias``)") in doc
