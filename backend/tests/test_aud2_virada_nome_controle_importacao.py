"""PEND-13/PEND-21 (API_SEGURANCA-4, entrada pelas importações) — nome com caractere
de controle invisível não entra no banco pelas importações.

Um nome colado de PDF ou vindo da plataforma pode trazer um caractere de controle
(C0 ou DEL, ex.: ``\\x02``) que não aparece na tela. O ``' '.join(split())`` das
importações não o tira (``split()`` não separa em ``\\x01``–``\\x08``,
``\\x0e``–``\\x1b`` nem ``\\x7f``): a ficha nascia com ele, e um nome desses derruba
a exportação Excel da escola. A regra é a mesma do cadastro manual
(``schemas.comum._nome_sem_controle``): o trecho com controle vira UM espaço.

E a comparação de nomes trata o caractere de controle como espaço: "Ana\\x02Beatriz
Souza" é a Ana Beatriz Souza na prévia e na confirmação.

Dados fictícios.
"""
import io
import json
from datetime import date

import openpyxl
import pytest
from sqlalchemy import select

from app.models import Aluno, Turma
from app.services import importacao as svc
from app.services import lista_piloto

API = "/api/v1"
DATA = "2026-08-14T12:00:00"
CT_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _placar(turma, alunos):
    return json.dumps({"fonte": "matific-placar", "turma": turma, "alunos": alunos},
                      ensure_ascii=False)


def _analise(cliente, eid, texto):
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/analisar", data={"texto": texto})
    assert r.status_code == 200, r.text
    return r.json()


def _confirmar(cliente, eid, analise, linhas):
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/confirmar", json={
        "plataforma": analise["plataforma"], "formato": analise["formato"],
        "tipo": analise["tipo"], "arquivo_token": analise.get("arquivo_token"),
        "recalcular": False, "linhas": linhas, "data_referencia": DATA})
    assert r.status_code == 200, r.text
    return r.json()


def _nomes(db, escola_id):
    db.expire_all()
    return sorted(db.execute(select(Aluno.nome).where(
        Aluno.escola_id == escola_id)).scalars())


def _sem_controle(texto):
    return not any(ord(c) < 32 or ord(c) == 127 for c in texto)


@pytest.mark.parametrize("colado", [
    "Clara\x02 Moura Lins", "Clara\x02Moura Lins", "Clara Moura\x7f Lins\x1b",
])
def test_previa_e_ficha_nova_sem_o_caractere_de_controle(cliente, db, escola_completa,
                                                         colado):
    escola = escola_completa["escola"]
    turma = escola_completa["turma"]
    analise = _analise(cliente, escola.id, _placar("3º Ano A", [
        {"nome": colado, "uuid": "uuid-fict-clara", "estrelas": 9, "atividades": 3}]))
    linha = analise["linhas"][0]
    assert linha["nome"] == "Clara Moura Lins", repr(linha["nome"])

    _confirmar(cliente, escola.id, analise, [{
        "nome": linha["nome"], "dados": linha["dados"], "criar_em_turma_id": turma.id}])

    assert "Clara Moura Lins" in _nomes(db, escola.id)
    assert all(_sem_controle(n) for n in _nomes(db, escola.id))


def test_corpo_da_confirmacao_com_controle_nao_grava_o_caractere(cliente, db,
                                                                escola_completa):
    """O corpo do /confirmar vem do cliente: o nome sujo também é limpo ali, e a
    turma nova pedida pelo nome idem."""
    escola = escola_completa["escola"]
    analise = _analise(cliente, escola.id, _placar("Maternal Azul", [
        {"nome": "Clara Moura Lins", "uuid": "uuid-fict-clara", "estrelas": 9,
         "atividades": 3}]))
    linha = analise["linhas"][0]

    _confirmar(cliente, escola.id, analise, [{
        "nome": "Clara\x02Moura Lins", "dados": linha["dados"],
        "criar_em_turma_nome": "Maternal\x02 Azul"}])

    assert "Clara Moura Lins" in _nomes(db, escola.id)
    db.expire_all()
    turmas = db.execute(select(Turma.nome).where(
        Turma.escola_id == escola.id)).scalars().all()
    assert "Maternal Azul" in turmas, turmas
    assert all(_sem_controle(t) for t in turmas)


def test_turma_do_relatorio_com_controle_nasce_sem_ele(db, escola_completa):
    """A turma lida do relatório (cabeçalho do PDF, campo da plataforma) também."""
    from app.routers import importacoes as imp

    escola = escola_completa["escola"]
    turma = imp._turma_pelo_nome(db, escola.id, 2026, "Maternal\x02 Verde", [], {})
    assert turma is not None and turma.nome == "Maternal Verde"


def test_controle_entre_palavras_casa_com_a_ficha_existente(cliente, db,
                                                            escola_completa):
    """A comparação de nomes trata o controle como espaço: a linha é a Ana."""
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    analise = _analise(cliente, escola.id, _placar("3º Ano A", [
        {"nome": "Ana\x02Beatriz Souza", "uuid": "uuid-fict-ana", "estrelas": 9,
         "atividades": 3}]))
    corr = analise["linhas"][0]["correspondencia"]
    assert (corr["status"], corr["aluno_id"]) == ("exato", ana.id), corr
    assert svc.chave_nome("Ana\x02Beatriz Souza") == svc.chave_nome("Ana Beatriz Souza")


def test_sincronizacao_do_elefante_nao_traz_o_caractere(escola_completa):
    analise = svc.analisar_elefante_api({
        "courseSchoolDescriptors": {"courseName": "3 ANO A"},
        "students": [{"studentId": 7, "studentName": "Clara\x02Moura Lins",
                      "totalBooksRead": 2, "totalReadTime": 60}]}, "elefante")
    assert [l.nome for l in analise.linhas] == ["Clara Moura Lins"]


def _lista_piloto(nome_aluno, nome_turma="2º Ano B"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "2º Ano B"
    ws.append(["Escola:", None, "EMEF FICTÍCIA", None, None, None, None,
               "Lista Piloto:", 2026])
    ws.append([])
    ws.append(["Professor:", None, "PROFESSORA\x7fFICTICIA", None, "Ano:", nome_turma,
               "Turno:       TARDE", None, "N.º da Classe (SED):", 300000001])
    ws.append([])
    ws.append(["N.º", "RM", "RA", "Nome", "Data de Nasc."])
    ws.append([1, 7001, "701.000.001-0", nome_aluno, date(2018, 5, 2)])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_lista_piloto_tira_o_del_do_nome_e_da_turma(cliente, db, escola_completa):
    """Na planilha só o DEL (\\x7f) passa (o XML do .xlsx não aceita os outros)."""
    escola = escola_completa["escola"]
    conteudo = _lista_piloto("BRUNA\x7fFICTICIA TESTELLI", "2º Ano\x7f B")
    analise = lista_piloto.analisar_matriculas(conteudo, "Lista.xlsx")
    assert analise.turmas[0].alunos[0].nome == "BRUNA FICTICIA TESTELLI"
    assert analise.turmas[0].nome == "2º Ano B"
    assert analise.turmas[0].professor == "PROFESSORA FICTICIA"

    r = cliente.post(f"{API}/escolas/{escola.id}/importacoes/matriculas/confirmar",
                     files={"arquivo": ("Lista.xlsx", conteudo, CT_XLSX)})
    assert r.status_code == 200, r.text
    assert "BRUNA FICTICIA TESTELLI" in _nomes(db, escola.id)
    assert all(_sem_controle(n) for n in _nomes(db, escola.id))


def test_nome_sem_controle_nao_muda():
    linha = svc.LinhaImportacao(numero=1, nome="Bento  Fictelo Testelli", dados={})
    assert linha.nome == "Bento  Fictelo Testelli"
    assert svc.normalizar_nome("Bento  Fictelo\tTestelli") == "bento fictelo testelli"


def test_pendencia_antiga_com_controle_cria_ficha_sem_ele(cliente, db, escola_completa):
    """Uma pendência gravada antes desta correção pode guardar o nome recebido com o
    caractere: a tela promete e o "Criar novo aluno" grava o nome sem ele."""
    from app.models import RevisaoIdentidade

    escola = escola_completa["escola"]
    turma = escola_completa["turma"]
    analise = _analise(cliente, escola.id, _placar("3º Ano A", [
        {"nome": "Clara Moura Lins", "uuid": "uuid-fict-clara", "estrelas": 9,
         "atividades": 3}]))
    linha = analise["linhas"][0]
    _confirmar(cliente, escola.id, analise, [{
        "nome": linha["nome"], "dados": linha["dados"],
        "criar_em_turma_nome": "3º Ano A", "deixar_para_revisao": True}])
    rev = db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == escola.id)).scalars().one()
    rev.nome_recebido = "Clara\x02Moura Lins"     # como uma pendência antiga
    db.commit()

    lista = cliente.get(f"{API}/escolas/{escola.id}/importacoes/revisoes").json()
    assert [r["nome_ficha_nova"] for r in lista] == ["Clara Moura Lins"]
    r = cliente.post(f"{API}/escolas/{escola.id}/importacoes/revisoes/{rev.id}/resolver",
                     json={"criar_em_turma_id": turma.id})
    assert r.status_code == 200, r.text
    assert "Clara Moura Lins" in _nomes(db, escola.id)
    assert all(_sem_controle(n) for n in _nomes(db, escola.id))
