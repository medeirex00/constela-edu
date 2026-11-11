"""Relatório em TEXTO (.txt/.csv/.tsv) e CSV das avaliações salvos fora do UTF-8.

Antes: o upload de relatório decodificava todo arquivo de texto com
``decode("utf-8", errors="replace")`` e o leitor das avaliações com
``decode("utf-8-sig", errors="replace")``. O "CSV" do Excel em português (Windows-1252)
virava "Jo�o" na prévia — a criança cadastrada ia para a revisão e a nova nascia com o
nome estragado — e o "Texto Unicode" (UTF-16) nem era reconhecido. No CSV das
avaliações, o componente gravado virava "Matem�tica".

Agora uma regra só (``services/codificacao.decodificar_texto``): BOM manda, senão
UTF-8 estrito, senão Windows-1252. E o "�" que ainda sobrar no nome (byte que nenhuma
das duas lê) só barra a CRIAÇÃO da ficha: a linha que criaria sai com erro na prévia e
é ignorada no /confirmar — nenhuma ficha nasce com ele. A linha que ASSOCIA (conta da
plataforma já vinculada, aluno escolhido pelo gestor) recebe os números normalmente:
associar não grava o nome em lugar nenhum (REV-IMP-1). Tudo fictício (a escola do
conftest tem "João Pedro Barbosa").
"""
import codecs

import json

import pytest
from sqlalchemy import select

from app.models import (Aluno, IdentidadeExterna, ResultadoAvaliacao,
                        RevisaoIdentidade, SnapshotMatific)
from app.services import avaliacoes
from app.services.codificacao import decodificar_texto

TEXTO_MATIFIC = (
    "Relatório Matific — Turma 3º Ano A\n"
    "Nome do aluno\tAtividades finalizadas\tPontuação média\tEstrelas\n"
    "Ana Beatriz Souza\t42\t85,5\t120\n"
    "João Pedro Barbosa\t10\t70\t35\n"
    "Lúcia Fictícia Conceição\t7\t60\t12\n"
)
NOMES = ["Ana Beatriz Souza", "João Pedro Barbosa", "Lúcia Fictícia Conceição"]

CODIFICACOES = {
    "cp1252": lambda t: t.encode("cp1252"),
    "latin-1": lambda t: t.replace("—", "-").encode("latin-1"),
    "utf-16 (Texto Unicode do Excel)": lambda t: t.encode("utf-16"),
    "utf-16-be com BOM": lambda t: codecs.BOM_UTF16_BE + t.encode("utf-16-be"),
    "utf-8 com BOM": lambda t: t.encode("utf-8-sig"),
    "utf-8": lambda t: t.encode("utf-8"),
}


def _analisar(cliente, escola_id, conteudo: bytes, nome: str = "relatorio.txt",
              ct: str = "text/plain"):
    r = cliente.post(f"/api/v1/escolas/{escola_id}/importacoes/analisar",
                     files={"arquivo": (nome, conteudo, ct)})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("codificacao", list(CODIFICACOES))
def test_decodificar_texto_le_as_codificacoes_do_excel(codificacao):
    esperado = TEXTO_MATIFIC if codificacao != "latin-1" else TEXTO_MATIFIC.replace("—", "-")
    assert decodificar_texto(CODIFICACOES[codificacao](TEXTO_MATIFIC)) == esperado


def test_decodificar_texto_nunca_levanta_e_marca_o_byte_ilegivel():
    # 0x81 não existe no Windows-1252 nem forma UTF-8: vira "�", sem exceção.
    assert decodificar_texto(b"Jo\x81o") == "Jo�o"
    assert decodificar_texto(b"") == ""


@pytest.mark.parametrize("codificacao", list(CODIFICACOES))
def test_previa_le_os_nomes_em_qualquer_codificacao_do_excel(cliente, escola_completa,
                                                            codificacao):
    corpo = _analisar(cliente, escola_completa["escola"].id,
                      CODIFICACOES[codificacao](TEXTO_MATIFIC))
    nomes = [linha["nome"] for linha in corpo["linhas"]]
    assert corpo["total_linhas"] == 3, corpo["erros_gerais"]
    assert nomes == NOMES
    status = {linha["nome"]: linha["correspondencia"]["status"] for linha in corpo["linhas"]}
    assert status["João Pedro Barbosa"] == "exato"     # a cadastrada casa, não vai à revisão
    assert status["Lúcia Fictícia Conceição"] == "nao_encontrado"


def _confirmar(cliente, escola_completa, corpo: dict, linhas: list[dict] | None = None):
    turma_id = escola_completa["turma"].id
    if linhas is None:
        linhas = []
        for linha in corpo["linhas"]:
            c = linha["correspondencia"] or {}
            casou = c.get("status") in ("exato", "vinculado")
            linhas.append({"nome": linha["nome"], "dados": linha["dados"],
                           "aluno_id": c.get("aluno_id") if casou else None,
                           "criar_em_turma_id": None if casou else turma_id})
    return cliente.post(
        f"/api/v1/escolas/{escola_completa['escola'].id}/importacoes/confirmar",
        json={"plataforma": corpo["plataforma"], "formato": corpo["formato"],
              "tipo": "texto", "linhas": linhas})


def test_confirmar_relatorio_em_cp1252_cria_a_ficha_com_o_nome_certo(cliente, db,
                                                                    escola_completa):
    corpo = _analisar(cliente, escola_completa["escola"].id,
                      TEXTO_MATIFIC.encode("cp1252"), "relatorio_matific.csv", "text/csv")
    r = _confirmar(cliente, escola_completa, corpo)
    assert r.status_code == 200, r.text
    nomes = sorted(a.nome for a in db.query(Aluno).filter(
        Aluno.escola_id == escola_completa["escola"].id))
    assert nomes == sorted([*NOMES, "Sofia Almeida Duarte"])


def test_previa_marca_com_erro_o_nome_que_ainda_tem_letra_ilegivel(cliente,
                                                                  escola_completa):
    """Byte que nem o UTF-8 nem o Windows-1252 leem (0x81): a linha sai com erro (a
    tela não a envia) em vez de oferecer criar a ficha com "�"."""
    bruto = TEXTO_MATIFIC.encode("cp1252").replace(b"L\xfacia", b"L\x81cia")
    corpo = _analisar(cliente, escola_completa["escola"].id, bruto)
    por_nome = {linha["nome"]: linha for linha in corpo["linhas"]}
    ilegivel = por_nome["L�cia Fictícia Conceição"]
    assert any("ilegível" in erro for erro in ilegivel["erros"]), ilegivel["erros"]
    assert not por_nome["João Pedro Barbosa"]["erros"]


def test_confirmar_ignora_a_linha_com_letra_ilegivel_no_nome(cliente, db, escola_completa):
    """A mesma regra no /confirmar (quem chama a API direto): a linha é ignorada com
    aviso e nenhuma ficha nasce com "�"."""
    corpo = _analisar(cliente, escola_completa["escola"].id, TEXTO_MATIFIC.encode("utf-8"))
    linhas = [{"nome": "L�cia Fict�cia", "dados": corpo["linhas"][2]["dados"],
               "aluno_id": None, "criar_em_turma_id": escola_completa["turma"].id}]
    r = _confirmar(cliente, escola_completa, corpo, linhas)
    assert r.status_code == 200, r.text
    assert any("ilegível" in aviso for aviso in r.json()["avisos"]), r.json()["avisos"]
    nomes = [a.nome for a in db.query(Aluno).filter(
        Aluno.escola_id == escola_completa["escola"].id)]
    assert not any("�" in nome for nome in nomes), nomes


@pytest.mark.parametrize("codificacao", ["cp1252", "utf-16 (Texto Unicode do Excel)",
                                         "utf-8 com BOM"])
def test_csv_de_avaliacao_grava_o_componente_com_acento(db, escola_completa, codificacao):
    escola = escola_completa["escola"]
    escola.codigo_inep = "35000001"
    db.commit()
    csv_txt = "INEP;Componente;Nota\n35000001;Matemática;210,5\n35000001;Português;198,0\n"
    avaliacoes.importar_resultados(
        db, CODIFICACOES[codificacao](csv_txt), "saresp_preparado.csv",
        avaliacao_chave="saresp", edicao=2025, indicador="proficiencia",
        unidade="escala_saresp", linha_dados=1, col_inep=0, col_valor=2,
        col_componente=1, etapa_fixa="5_ano")
    db.commit()
    assert sorted(r.componente for r in db.query(ResultadoAvaliacao)) == [
        "Matemática", "Português"]


def test_grade_das_avaliacoes_em_cp1252_le_o_municipio_com_acento():
    """O /casar-inep lê pelo mesmo leitor (``_iterar_grade``)."""
    csv_txt = "UF;Município;INEP;Escola\nSP;São José dos Campos;35000001;EMEF Fictícia\n"
    grade = avaliacoes.analisar_planilha(csv_txt.encode("cp1252"), "ideb_escolas.csv")
    assert grade["primeiras_linhas"][1] == ["SP", "São José dos Campos", "35000001",
                                           "EMEF Fictícia"]


# --- REV-IMP-1: o "�" barra só a CRIAÇÃO da ficha, não a associação ------------------

DATA = "2026-08-14T12:00:00"


def _linha_placar(nome: str, uuid: str, estrelas: int = 50, atividades: int = 10) -> dict:
    return {"nome": nome, "dados": {"matific_uuid": uuid, "estrelas": estrelas,
                                    "atividades": atividades,
                                    "pontuacao_media": round(estrelas / atividades, 2),
                                    "turma_relatorio": "3º Ano A"},
            "aluno_id": None, "criar_em_turma_id": None}


def _vincular_joao(db, escola_completa) -> Aluno:
    joao = escola_completa["alunos"][1]
    db.add(IdentidadeExterna(escola_id=escola_completa["escola"].id, aluno_id=joao.id,
                             plataforma="matific", id_externo="uuid-fict-jp"))
    db.commit()
    return joao


def test_conta_vinculada_com_letra_ilegivel_no_nome_recebe_os_numeros(cliente, db,
                                                                     escola_completa):
    """A plataforma (ou a fonte do PDF) manda o nome com "�", mas a CONTA já é do João:
    a linha associa pela conta e os números entram — a coleta não deixa a criança sem
    dados. A linha nova com "�" no mesmo envio continua sem criar ficha."""
    eid = escola_completa["escola"].id
    joao = _vincular_joao(db, escola_completa)
    r = cliente.post(f"/api/v1/escolas/{eid}/importacoes/confirmar", json={
        "plataforma": "matific", "formato": "resumo", "tipo": "texto",
        "recalcular": False, "data_referencia": DATA,
        "linhas": [_linha_placar("Jo�o Pedro Barbosa", "uuid-fict-jp"),
                   _linha_placar("L�cia Fict�cia Concei��o", "uuid-fict-nova", 12, 7)]})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["alunos_aplicados_ids"] == [joao.id], corpo
    db.expire_all()
    retratos = db.execute(select(SnapshotMatific.estrelas, SnapshotMatific.atividades)
                          .where(SnapshotMatific.aluno_id == joao.id)).all()
    assert [tuple(x) for x in retratos] == [(50, 10)], (retratos, corpo["avisos"])
    assert db.get(Aluno, joao.id).nome == "João Pedro Barbosa"   # o nome não muda
    nomes = [a.nome for a in db.query(Aluno).filter(Aluno.escola_id == eid)]
    assert not any("�" in nome for nome in nomes), nomes
    assert any("ilegível" in aviso and "L�cia" in aviso for aviso in corpo["avisos"]), \
        corpo["avisos"]


def test_aluno_escolhido_pelo_gestor_com_letra_ilegivel_recebe_os_numeros(cliente, db,
                                                                         escola_completa):
    """O gestor ESCOLHE o aluno (``aluno_id``) para a linha cujo nome veio com "�":
    nada do nome é gravado ao associar, então os números entram."""
    eid = escola_completa["escola"].id
    joao = escola_completa["alunos"][1]
    linha = {"nome": "Jo�o Pedro Barbosa",
             "dados": {"livros_unicos": 7, "tempo_leitura_min": 30,
                       "turma_relatorio": "3º Ano A"},
             "aluno_id": joao.id, "criar_em_turma_id": None}
    r = cliente.post(f"/api/v1/escolas/{eid}/importacoes/confirmar", json={
        "plataforma": "elefante", "formato": "resumo", "tipo": "pdf",
        "recalcular": False, "data_referencia": DATA, "linhas": [linha]})
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert (corpo["qtd_alunos"], corpo["qtd_erros"], corpo["alunos_aplicados_ids"]) \
        == (1, 0, [joao.id]), corpo


def test_previa_so_marca_erro_na_linha_com_letra_ilegivel_que_criaria_ficha(
        cliente, db, escola_completa):
    """PRÉVIA = CONFIRMAÇÃO: no Placar do Matific em JSON, a conta já vinculada com "�"
    no nome casa pela conta e vai sem erro (a tela a envia); a conta nova com "�" — que
    criaria a ficha — sai com erro (a tela não a envia)."""
    eid = escola_completa["escola"].id
    joao = _vincular_joao(db, escola_completa)
    placar = {"fonte": "matific-placar", "turma": "3º Ano A", "alunos": [
        {"nome": "Jo�o Pedro Barbosa", "uuid": "uuid-fict-jp", "estrelas": 50,
         "atividades": 10},
        {"nome": "L�cia Fict�cia Concei��o", "uuid": "uuid-fict-nova", "estrelas": 12,
         "atividades": 7}]}
    corpo = _analisar(cliente, eid, json.dumps(placar).encode("utf-8"), "placar.json",
                      "application/json")
    por_nome = {linha["nome"]: linha for linha in corpo["linhas"]}
    vinculada = por_nome["Jo�o Pedro Barbosa"]
    assert vinculada["correspondencia"]["status"] == "exato", vinculada
    assert vinculada["correspondencia"]["aluno_id"] == joao.id
    assert not vinculada["erros"], vinculada["erros"]
    nova = por_nome["L�cia Fict�cia Concei��o"]
    assert nova["correspondencia"]["status"] == "nao_encontrado", nova
    assert any("ilegível" in erro for erro in nova["erros"]), nova["erros"]


def test_linha_com_letra_ilegivel_deixada_para_a_revisao_nao_vira_ficha_nova(
        cliente, db, escola_completa):
    """A linha com "�" que vai para a fila de revisão continua lá para o gestor
    ASSOCIAR; "Criar novo aluno" nessa pendência é recusado (a ficha nasceria com o
    "�") e a pendência continua pendente."""
    eid = escola_completa["escola"].id
    joao = escola_completa["alunos"][1]
    linha = {**_linha_placar("Jo�o P Barbosa", "uuid-fict-revisao"),
             "deixar_para_revisao": True}
    r = cliente.post(f"/api/v1/escolas/{eid}/importacoes/confirmar", json={
        "plataforma": "matific", "formato": "resumo", "tipo": "texto",
        "recalcular": False, "data_referencia": DATA, "linhas": [linha]})
    assert r.status_code == 200, r.text
    db.expire_all()
    rev = db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == eid,
        RevisaoIdentidade.id_externo == "uuid-fict-revisao")).scalars().one_or_none()
    assert rev is not None, r.json()
    url = f"/api/v1/escolas/{eid}/importacoes/revisoes/{rev.id}/resolver"
    r = cliente.post(url, json={"criar_em_turma_id": escola_completa["turma"].id})
    assert r.status_code == 409, r.text
    assert "ilegível" in r.json()["detail"], r.json()
    db.expire_all()
    assert db.get(RevisaoIdentidade, rev.id).status == "pendente"
    nomes = [a.nome for a in db.query(Aluno).filter(Aluno.escola_id == eid)]
    assert not any("�" in nome for nome in nomes), nomes
    r = cliente.post(url, json={"aluno_id": joao.id})
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(RevisaoIdentidade, rev.id).status == "resolvida"
