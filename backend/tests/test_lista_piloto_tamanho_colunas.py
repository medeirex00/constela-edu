"""Lista Piloto × tamanho das colunas (4ª revisão de integração,
esquemas-sync-docs). Dados 100% fictícios.

A importação (``/importacoes/matriculas/analisar`` e ``/confirmar``) grava direto
nas colunas ``String(n)`` — não passa pelos schemas com ``max_length``. No
PostgreSQL o valor acima da coluna era DataError no commit: a série fora do padrão
com mais de 30 caracteres, o nome de turma com mais de 100 ou o nome de aluno com
mais de 200 derrubavam o arquivo inteiro com 500, sem dizer qual célula, e a
prévia não avisava. O SQLite aceita qualquer tamanho, por isso a suíte não via.

Agora o excesso vira AVISO (na prévia e na confirmação) e as linhas boas entram:
série cortada no tamanho da coluna quando o corte não muda a leitura dela (senão
a aba fica de fora), turma NOVA com nome longo fica de fora, linha de aluno com
nome longo fica de fora (e ninguém da turma é marcado "fora da lista"), nº de
chamada fora do INTEGER e nº da classe (SED) longo são ignorados.

As rotas são reaproveitadas no PostgreSQL em ``..._tamanho_colunas_pg`` — é lá que
o 500 acontecia (prova invertida da dimensão esquemas-sync-docs)."""
import io
from datetime import date

import openpyxl
from sqlalchemy import func, select

from app.models import Aluno, Matricula, Turma
from app.services import lista_piloto as lp

CT_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
COLUNAS = ["N.º", "RM", "RA", "Nome", "Data de Nasc.", "Responsável",
           "Endereço", "Bairro", "Telefone", "RG", "CPF", "SUS",
           "SEXO", "RAÇA COR", "BOLSA FAMÍLIA"]

NOME_LONGO = "MARIA " + "X" * 195                  # 201 caracteres
SERIE_32 = "ANO CICLO MULTISSERIADO INTEGRAL A"         # série = 32 caracteres
# Cortada em 30 a série muda de 5 para 1 (e a premiação junto): não pode cortar.
SERIE_QUE_MUDA = "TURMA MULTISSERIADA DO 1º AO 5º ANO"
TURMA_LONGA = "4º ANO B" + " INTEGRAL" * 12             # 116 caracteres, chave 4|B


def _linha(nome, numero, nasc, ra=""):
    return [numero, "", ra, nome, nasc, "MAE FICTICIA", "RUA X, 1", "BAIRRO",
            "", "", "", "", "F", "PARDA", "NÃO"]


def _aba(ws, valor_ano, alunos, sed=300396600):
    ws.append([None, None, None, "PREFEITURA MUNICIPAL FICTICIA"])
    ws.append(["Escola:", None, "EMEF TESTE", None, None, None, None,
               "Lista Piloto:", 2026])
    ws.append([])
    ws.append(["Professor:", None, "PAULA FICTICIA", None, "Ano:", valor_ano,
               "Turno:       TARDE", None, "N.º da Classe (SED):", sed])
    ws.append([])
    ws.append(COLUNAS)
    for linha in alunos:
        ws.append(linha)


def _planilha(*abas) -> bytes:
    """``abas``: (título, valor de "Ano:", alunos[, sed])."""
    wb = openpyxl.Workbook()
    for i, aba in enumerate(abas):
        titulo, valor_ano, alunos, *resto = aba
        ws = wb.active if i == 0 else wb.create_sheet()
        ws.title = titulo
        _aba(ws, valor_ano, alunos, *resto)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _post(cliente, escola_id, etapa, conteudo):
    return cliente.post(
        f"/api/v1/escolas/{escola_id}/importacoes/matriculas/{etapa}",
        files={"arquivo": ("Lista Piloto 2026.xlsx", conteudo, CT_XLSX)})


def _turmas(db, escola_id):
    db.expire_all()
    return {t.nome: t for t in db.scalars(select(Turma).where(Turma.escola_id == escola_id))}


def _alunos(db, escola_id):
    db.expire_all()
    return {a.nome: a for a in db.scalars(select(Aluno).where(Aluno.escola_id == escola_id))}


# --- análise (pura) -----------------------------------------------------------

def test_tetos_saem_dos_modelos():
    assert (lp.MAX_NOME_ALUNO, lp.MAX_NOME_TURMA, lp.MAX_SERIE, lp.MAX_CODIGO_SED) == \
        (200, 100, 30, 40)


def test_nome_de_aluno_acima_da_coluna_pula_a_linha_com_aviso_sem_o_nome():
    no_limite = "ANA " + "Y" * 196                       # 200: cabe
    a = lp.analisar_matriculas(_planilha(("4º Ano B", "4º ANO B", [
        _linha("CLARA MENEZES FICTICIA", 1, date(2017, 3, 1)),
        _linha(NOME_LONGO, 2, date(2017, 5, 3)),
        _linha(no_limite, 3, date(2017, 6, 4))])))
    [t] = a.turmas
    assert [al.nome for al in t.alunos] == ["CLARA MENEZES FICTICIA", no_limite]
    assert t.linhas_puladas == 1
    [aviso] = [x for x in a.avisos if "201 caracteres" in x]
    assert "Aba “4º Ano B”, 2ª linha preenchida abaixo dos títulos (N.º 2)" in aviso
    assert "fica fora da importação" in aviso and "fora da lista piloto" in aviso
    assert "MARIA" not in aviso and "XXXX" not in aviso       # nada de dado pessoal


def test_numero_de_chamada_fora_do_inteiro_e_ignorado_e_o_aluno_entra():
    a = lp.analisar_matriculas(_planilha(("4º Ano B", "4º ANO B", [
        _linha("CLARA MENEZES FICTICIA", 2**31, date(2017, 3, 1)),
        _linha("DANIEL FARIAS FICTICIO", 2**31 - 1, date(2017, 4, 2))])))
    [t] = a.turmas
    assert [(al.nome, al.numero_chamada) for al in t.alunos] == [
        ("CLARA MENEZES FICTICIA", None), ("DANIEL FARIAS FICTICIO", 2**31 - 1)]
    assert t.linhas_puladas == 0
    [aviso] = [x for x in a.avisos if "N.º não é um número de chamada" in x]
    assert "1ª linha preenchida" in aviso and str(2**31) not in aviso


def test_sed_acima_da_coluna_e_ignorado_e_a_turma_entra():
    a = lp.analisar_matriculas(_planilha(
        ("4º Ano B", "4º ANO B", [_linha("CLARA MENEZES FICTICIA", 1, date(2017, 3, 1))],
         "9" * 41),
        ("4º Ano C", "4º ANO C", [_linha("DANIEL FARIAS FICTICIO", 1, date(2017, 4, 2))],
         "8" * 40)))
    assert [(t.nome, t.sed) for t in a.turmas] == [("4º Ano B", ""), ("4º Ano C", "8" * 40)]
    assert any("41 dígitos" in x and "Aba “4º Ano B”" in x for x in a.avisos)


def test_conferir_turma_nova_corta_a_serie_so_quando_a_leitura_nao_muda():
    t = lp.TurmaMatriculas(nome=SERIE_32, ano_escolar="ANO CICLO MULTISSERIADO INTEGRAL",
                           aba="Multi")
    serie, avisos = lp.conferir_turma_nova(t)
    assert serie == "ANO CICLO MULTISSERIADO INTEGR" and len(serie) == 30
    assert avisos and "foi gravada como" in avisos[0]
    assert "será gravada" in lp.conferir_turma_nova(t, previa=True)[1][0]

    muda = lp.TurmaMatriculas(nome=SERIE_QUE_MUDA, ano_escolar=SERIE_QUE_MUDA, aba="Multi")
    serie, avisos = lp.conferir_turma_nova(muda)
    assert serie is None and "mudaria a série ou a premiação" in avisos[0]

    no_limite = lp.TurmaMatriculas(nome="4º Ano B", ano_escolar="S" * 30)
    assert lp.conferir_turma_nova(no_limite) == ("S" * 30, [])


def test_conferir_turma_nova_recusa_nome_acima_da_coluna():
    assert lp.conferir_turma_nova(lp.TurmaMatriculas(nome="T" * 100, ano_escolar="x")) \
        == ("x", [])
    serie, avisos = lp.conferir_turma_nova(lp.TurmaMatriculas(nome="T" * 101, ano_escolar="x"))
    assert serie is None and "101 caracteres" in avisos[0] and "não foi importada" in avisos[0]


# --- rotas (reaproveitadas no PostgreSQL) -------------------------------------

def test_serie_fora_do_padrao_acima_de_30_e_cortada_com_aviso(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    arq = _planilha(("Multi", SERIE_32, [_linha("DANIEL FARIAS FICTICIO", 1, date(2017, 4, 2))]))
    previa = _post(cliente, eid, "analisar", arq)
    assert previa.status_code == 200, previa.text
    assert [t["ano_escolar"] for t in previa.json()["turmas"]] == ["ANO CICLO MULTISSERIADO INTEGR"]
    assert any("será gravada como" in x for x in previa.json()["avisos"])
    r = _post(cliente, eid, "confirmar", arq)
    assert r.status_code == 200, r.text
    assert any("foi gravada como" in x for x in r.json()["avisos"])
    assert _turmas(db, eid)[SERIE_32].ano_escolar == "ANO CICLO MULTISSERIADO INTEGR"
    assert "DANIEL FARIAS FICTICIO" in _alunos(db, eid)


def test_serie_com_30_no_limite_passa_sem_aviso(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    valor = "ANO CICLO MULTISSERIADO INTEGR A"            # série = 30 caracteres
    r = _post(cliente, eid, "confirmar", _planilha(
        ("Multi", valor, [_linha("DANIEL FARIAS FICTICIO", 1, date(2017, 4, 2))])))
    assert r.status_code == 200, r.text
    assert not any("caracteres" in x for x in r.json()["avisos"])
    assert _turmas(db, eid)[valor].ano_escolar == "ANO CICLO MULTISSERIADO INTEGR"


def test_titulo_da_aba_de_31_vira_serie_cortada(cliente, db, escola_completa):
    """Sem "ano" no valor de "Ano:", o nome vem do TÍTULO da aba (Excel: até 31)."""
    eid = escola_completa["escola"].id
    titulo = "MULTISSERIADO INTEGRAL TARDE 12"            # 31, sem letra solta no fim
    r = _post(cliente, eid, "confirmar", _planilha(
        (titulo, "MULTI", [_linha("DANIEL FARIAS FICTICIO", 1, date(2017, 4, 2))])))
    assert r.status_code == 200, r.text
    assert _turmas(db, eid)[titulo].ano_escolar == "MULTISSERIADO INTEGRAL TARDE 1"


def test_serie_que_mudaria_a_leitura_deixa_a_aba_de_fora(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    arq = _planilha(
        ("Multi", SERIE_QUE_MUDA, [_linha("DANIEL FARIAS FICTICIO", 1, date(2017, 4, 2))]),
        ("4º Ano C", "4º ANO C", [_linha("CLARA MENEZES FICTICIA", 1, date(2017, 3, 1))]))
    previa = _post(cliente, eid, "analisar", arq)
    assert previa.status_code == 200, previa.text
    assert any("não será importada" in x for x in previa.json()["avisos"])
    turmas_antes = set(_turmas(db, eid))
    r = _post(cliente, eid, "confirmar", arq)
    assert r.status_code == 200, r.text
    assert any("mudaria a série ou a premiação" in x for x in r.json()["avisos"])
    assert set(_turmas(db, eid)) - turmas_antes == {"4º Ano C"}
    alunos = _alunos(db, eid)
    assert "CLARA MENEZES FICTICIA" in alunos and "DANIEL FARIAS FICTICIO" not in alunos


def test_turma_nova_com_nome_acima_de_100_fica_de_fora(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    longa = "ANO " + "Z" * 100                            # "ano" no valor: é o nome
    r = _post(cliente, eid, "confirmar", _planilha(
        ("Longa", longa, [_linha("DANIEL FARIAS FICTICIO", 1, date(2017, 4, 2))]),
        ("4º Ano C", "4º ANO C", [_linha("CLARA MENEZES FICTICIA", 1, date(2017, 3, 1))])))
    assert r.status_code == 200, r.text
    assert r.json()["turmas_criadas"] == 1
    assert any("Aba “Longa”: o nome da turma tem 104 caracteres" in x
               for x in r.json()["avisos"])
    alunos = _alunos(db, eid)
    assert "CLARA MENEZES FICTICIA" in alunos and "DANIEL FARIAS FICTICIO" not in alunos


def test_turma_existente_com_nome_longo_na_planilha_continua_importando(
        cliente, db, escola_completa):
    """A turma que JÁ existe não grava nome nem série: recusá-la por tamanho
    quebraria um envio que funcionava."""
    eid = escola_completa["escola"].id
    db.add(Turma(escola_id=eid, nome="4º Ano B", ano_escolar="4º Ano", ano_letivo=2026))
    db.commit()
    arq = _planilha(("4B", TURMA_LONGA, [_linha("DANIEL FARIAS FICTICIO", 1, date(2017, 4, 2))]))
    previa = _post(cliente, eid, "analisar", arq)
    assert previa.status_code == 200, previa.text
    assert previa.json()["turmas"][0]["ja_existe"] is True
    assert not any("caracteres" in x for x in previa.json()["avisos"])
    r = _post(cliente, eid, "confirmar", arq)
    assert r.status_code == 200, r.text
    assert r.json()["turmas_criadas"] == 0
    aluno = _alunos(db, eid)["DANIEL FARIAS FICTICIO"]
    turma = _turmas(db, eid)["4º Ano B"]
    assert db.scalar(select(func.count(Matricula.id)).where(
        Matricula.aluno_id == aluno.id, Matricula.turma_id == turma.id)) == 1


def test_nome_de_aluno_acima_de_200_pula_so_a_linha(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    arq = _planilha(("4º Ano B", "4º ANO B", [
        _linha("CLARA MENEZES FICTICIA", 1, date(2017, 3, 1)),
        _linha(NOME_LONGO, 2, date(2017, 5, 3))]))
    previa = _post(cliente, eid, "analisar", arq)
    assert previa.status_code == 200, previa.text
    assert previa.json()["total_alunos"] == 1
    r = _post(cliente, eid, "confirmar", arq)
    assert r.status_code == 200, r.text
    assert r.json()["alunos_criados"] == 1
    [aviso] = [x for x in r.json()["avisos"] if "201 caracteres" in x]
    assert "MARIA" not in aviso
    alunos = _alunos(db, eid)
    assert "CLARA MENEZES FICTICIA" in alunos
    assert not any(len(n) > 200 for n in alunos)


def test_linha_pulada_nao_marca_ninguem_da_turma_fora_da_lista(cliente, db, escola_completa):
    """A criança da linha pulada não foi vista: a reconciliação daquela turma fica
    para o próximo envio, em vez de tirá-la (e a quem mais faltar) das visões."""
    eid = escola_completa["escola"].id
    primeira = _planilha(("4º Ano B", "4º ANO B", [
        _linha("CLARA MENEZES FICTICIA", 1, date(2017, 3, 1)),
        _linha("BRUNO PEREIRA FICTICIO", 2, date(2017, 4, 9))]))
    assert _post(cliente, eid, "confirmar", primeira).status_code == 200
    # O nome do Bruno chega estragado (célula colada com lixo): a linha é pulada.
    segunda = _planilha(("4º Ano B", "4º ANO B", [
        _linha("CLARA MENEZES FICTICIA", 1, date(2017, 3, 1)),
        _linha("BRUNO PEREIRA FICTICIO " + "Q" * 190, 2, date(2017, 4, 9))]))
    r = _post(cliente, eid, "confirmar", segunda)
    assert r.status_code == 200, r.text
    assert r.json()["alunos_fora_lista"] == 0
    assert _alunos(db, eid)["BRUNO PEREIRA FICTICIO"].status == "ativo"
    # Controle: sem linha pulada, quem saiu da lista é marcado como sempre.
    terceira = _planilha(("4º Ano B", "4º ANO B", [
        _linha("CLARA MENEZES FICTICIA", 1, date(2017, 3, 1))]))
    r = _post(cliente, eid, "confirmar", terceira)
    assert r.status_code == 200, r.text
    assert r.json()["alunos_fora_lista"] == 1
    assert _alunos(db, eid)["BRUNO PEREIRA FICTICIO"].status == "fora_lista_piloto"


def test_sed_longo_e_numero_fora_do_inteiro_nao_derrubam_o_arquivo(
        cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    r = _post(cliente, eid, "confirmar", _planilha(
        ("4º Ano B", "4º ANO B", [_linha("CLARA MENEZES FICTICIA", 2**31, date(2017, 3, 1))],
         "9" * 41)))
    assert r.status_code == 200, r.text
    turma = _turmas(db, eid)["4º Ano B"]
    assert turma.codigo_externo is None and turma.observacoes is None
    assert _alunos(db, eid)["CLARA MENEZES FICTICIA"].numero_chamada is None
    avisos = r.json()["avisos"]
    assert any("41 dígitos" in x for x in avisos)
    assert any("N.º não é um número de chamada" in x for x in avisos)
