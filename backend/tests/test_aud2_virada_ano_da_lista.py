"""Virada do ano letivo (G_VIRADA-1): a Lista Piloto de OUTRO ano não reescreve o ano
letivo da escola.

A planilha diz de que ano é ("Lista Piloto: 2027"; sem a célula, o ano no nome do
arquivo). A confirmação usava só o ano letivo ATIVO da escola: a Lista 2027 enviada com
a escola ainda em 2026 movia as matrículas de 2026 para as turmas do ano seguinte, criava
as turmas de 2027 como turmas de 2026, marcava os formandos "fora da lista piloto" e
recalculava as Notas de 2026 — sem aviso e sem volta (a matrícula não guarda histórico).
O caminho inverso (a lista de 2026 depois da virada) aplicava a lista velha a 2027.

Agora: a prévia avisa e marca ``ano_divergente`` (a tela não deixa confirmar), e a
confirmação recusa com 409 sem tocar no banco. Planilha sem o ano: segue como antes, com
um aviso para conferir. Dados fictícios.
"""
import io
from datetime import date, datetime

import openpyxl
from sqlalchemy import func, select

from app.core import tempo
from app.models import (Aluno, Escola, Importacao, LogAuditoria, Matricula, Nota,
                        SnapshotElefante, Turma)

CT_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
COLUNAS = ["N.º", "RM", "RA", "Nome", "Data de Nasc.", "Responsável",
           "Endereço", "Bairro", "Telefone", "RG", "CPF", "SUS",
           "SEXO", "RAÇA COR", "BOLSA FAMÍLIA"]

ANA = ("ANA CLARA FICTICIA SOUZA", "900.000.001-0", date(2016, 3, 1))
BETO = ("BETO FICTICIO LIMA", "900.000.002-0", date(2016, 4, 2))
DORA = ("DORA FICTICIA MELO", "900.000.004-0", date(2015, 6, 4))     # 5º ano de 2026


def _planilha(ano, *turmas) -> bytes:
    """Lista Piloto com uma aba por turma. ``ano=None``: sem a célula do ano."""
    wb = openpyxl.Workbook()
    for i, (nome_turma, alunos) in enumerate(turmas):
        ws = wb.active if i == 0 else wb.create_sheet()
        ws.title = nome_turma[:31]
        ws.append([None, None, None, "PREFEITURA MUNICIPAL FICTICIA"])
        if ano is None:
            ws.append(["Escola:", None, "EMEF FICTICIA"])
        else:
            ws.append(["Escola:", None, "EMEF FICTICIA", None, None, None, None,
                       "Lista Piloto:", ano])
        ws.append([])
        ws.append(["Professor:", None, "PROFESSORA FICTICIA", None, "Ano:", nome_turma,
                   "Turno:       TARDE", None, "N.º da Classe (SED):", 300396600 + i])
        ws.append([])
        ws.append(COLUNAS)
        for n, (nome, ra, nasc) in enumerate(alunos, start=1):
            ws.append([n, "", ra, nome, nasc, "MAE", "RUA X, 1", "BAIRRO",
                       "", "", "", "", "F", "PARDA", "NÃO"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _enviar(cliente, escola_id, conteudo, etapa="confirmar", nome="Lista.xlsx"):
    return cliente.post(
        f"/api/v1/escolas/{escola_id}/importacoes/matriculas/{etapa}",
        files={"arquivo": (nome, conteudo, CT_XLSX)})


def _ficha(db, escola_id, nome) -> Aluno:
    db.expire_all()
    return db.execute(select(Aluno).where(Aluno.escola_id == escola_id,
                                          Aluno.nome == nome)).scalar_one()


def _retrato(db, escola_id, aluno_id, livros):
    imp = Importacao(escola_id=escola_id, plataforma="elefante", tipo="seed",
                     qtd_alunos=1, status="concluida")
    db.add(imp)
    db.flush()
    db.add(SnapshotElefante(escola_id=escola_id, aluno_id=aluno_id, importacao_id=imp.id,
                            data_referencia=datetime(2026, 11, 20, 12, 0),
                            livros_unicos=livros, tempo_leitura_min=livros * 30,
                            livros_por_nivel={"D": livros}))
    db.commit()


def _foto(db, cliente, escola_id) -> dict:
    """Tudo o que a lista de outro ano não pode mudar: matrículas, turmas, status,
    Notas e o ranking do ano ativo."""
    db.expire_all()
    return {
        "matriculas": sorted(tuple(r) for r in db.execute(
            select(Matricula.aluno_id, Matricula.turma_id, Matricula.ano_letivo)
            .where(Matricula.escola_id == escola_id)).all()),
        "turmas": sorted(tuple(r) for r in db.execute(
            select(Turma.id, Turma.nome, Turma.ano_letivo)
            .where(Turma.escola_id == escola_id)).all()),
        "status": sorted(tuple(r) for r in db.execute(
            select(Aluno.id, Aluno.nome, Aluno.status, Aluno.da_lista_piloto)
            .where(Aluno.escola_id == escola_id)).all()),
        "notas": sorted(tuple(r) for r in db.execute(
            select(Nota.aluno_id, Nota.ano_letivo, Nota.nota_elefante, Nota.posicao_leitura)
            .where(Nota.escola_id == escola_id)).all()),
        "ranking": cliente.get(f"/api/v1/escolas/{escola_id}/ranking").json(),
    }


def _ano_2026_com_ranking(cliente, db, escola_id):
    r = _enviar(cliente, escola_id, _planilha(2026, ("4º Ano A", [ANA, BETO]),
                                              ("5º Ano A", [DORA])))
    assert r.status_code == 200, r.text
    for nome, livros in ((ANA[0], 12), (BETO[0], 8), (DORA[0], 20)):
        _retrato(db, escola_id, _ficha(db, escola_id, nome).id, livros)
    assert cliente.post(f"/api/v1/escolas/{escola_id}/importacoes/recalcular").status_code == 200


def test_volta_do_ano_e_recusada_depois_de_mudar_fichas_na_lista_piloto(
        cliente_global, db, escola_completa, monkeypatch):
    monkeypatch.setattr(tempo, "hoje_br", lambda: date(2026, 12, 5))
    eid = escola_completa["escola"].id
    _ano_2026_com_ranking(cliente_global, db, eid)
    url = f"/api/v1/escolas/{eid}"
    assert cliente_global.patch(url, json={"ano_letivo_ativo": 2027}).status_code == 200
    for alunos in ([ANA, BETO], [BETO]):
        lista = _planilha(2027, ("5º Ano A", alunos))
        resposta = _enviar(cliente_global, eid, lista)
        assert resposta.status_code == 200, resposta.text
    assert _ficha(db, eid, ANA[0]).status == "fora_lista_piloto"
    antes = _foto(db, cliente_global, eid)
    resposta = cliente_global.patch(url, json={"ano_letivo_ativo": 2026})
    assert resposta.status_code == 409, resposta.text
    assert "Lista Piloto" in resposta.json()["detail"]
    assert _foto(db, cliente_global, eid) == antes
    assert db.get(Escola, eid).ano_letivo_ativo == 2027


def test_lista_de_2027_com_a_escola_em_2026_e_recusada_e_2026_fica_intacto(
        cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    _ano_2026_com_ranking(cliente, db, eid)
    antes = _foto(db, cliente, eid)
    assert antes["ranking"], "o ranking de 2026 precisa ter gente para a comparação valer"

    # Fevereiro de 2027: a coordenação envia a Lista 2027 antes de o Admin Global virar
    # o ano. Ana e Beto foram para o 5º Ano A; Dora (5º ano de 2026) saiu.
    ana = _ficha(db, eid, ANA[0])
    antes_turma = [m for m in antes["matriculas"] if m[0] == ana.id]
    lista_2027 = _planilha(2027, ("5º Ano A", [ANA, BETO]))
    previa = _enviar(cliente, eid, lista_2027, "analisar")
    assert previa.status_code == 200, previa.text
    pv = previa.json()
    conf = _enviar(cliente, eid, lista_2027)
    depois = _foto(db, cliente, eid)

    # O ano letivo 2026 fica como estava: a matrícula da Ana, a Dora ativa, o ranking.
    turma_ana = [m for m in depois["matriculas"] if m[0] == ana.id]
    assert turma_ana == antes_turma, f"matrícula de 2026 da Ana mudou: {antes_turma} -> {turma_ana}"
    assert _ficha(db, eid, DORA[0]).status == "ativo"
    assert depois == antes

    # A confirmação recusa e diz por quê; a prévia já avisava.
    assert conf.status_code == 409, conf.text
    detalhe = conf.json()["detail"]
    assert "Lista Piloto de 2027" in detalhe and "ano letivo 2026" in detalhe
    assert "Nada foi gravado" in detalhe
    assert pv["ano_letivo"] == 2027
    assert pv["ano_divergente"] is True
    assert "2027" in pv["aviso_ano"] and "2026" in pv["aviso_ano"]
    assert "administrador global" in pv["aviso_ano"]
    assert db.execute(select(func.count()).select_from(LogAuditoria).where(
        LogAuditoria.acao == "matriculas.importadas")).scalar_one() == 1   # só a de 2026


def test_lista_de_2026_depois_da_virada_e_recusada(cliente, cliente_global, db,
                                                   escola_completa):
    eid = escola_completa["escola"].id
    assert _enviar(cliente, eid, _planilha(2026, ("4º Ano A", [ANA, BETO]))).status_code == 200
    r = cliente_global.patch(f"/api/v1/escolas/{eid}", json={"ano_letivo_ativo": 2027})
    assert r.status_code == 200, r.text
    assert _enviar(cliente, eid, _planilha(2027, ("5º Ano A", [ANA, BETO]))).status_code == 200
    antes = _foto(db, cliente, eid)

    # A lista velha reenviada depois da virada não volta as crianças de 2027 ao 4º ano.
    velha = _planilha(2026, ("4º Ano A", [ANA, BETO]))
    pv = _enviar(cliente, eid, velha, "analisar").json()
    assert pv["ano_divergente"] is True and "2026" in pv["aviso_ano"]
    conf = _enviar(cliente, eid, velha)
    assert conf.status_code == 409, conf.text
    assert "Lista Piloto de 2026" in conf.json()["detail"]
    assert "já está no ano letivo 2027" in conf.json()["detail"]
    assert _foto(db, cliente, eid) == antes


def test_lista_do_ano_da_escola_segue_sem_aviso_de_ano(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    lista = _planilha(2026, ("4º Ano A", [ANA, BETO]))
    pv = _enviar(cliente, eid, lista, "analisar").json()
    assert (pv["ano_letivo"], pv["ano_divergente"], pv["aviso_ano"]) == (2026, False, None)
    assert _enviar(cliente, eid, lista).status_code == 200


def test_planilha_sem_o_ano_segue_e_pede_para_conferir(cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    lista = _planilha(None, ("4º Ano A", [ANA, BETO]))
    pv = _enviar(cliente, eid, lista, "analisar").json()
    assert pv["ano_letivo"] is None and pv["ano_divergente"] is False
    assert "2026" in pv["aviso_ano"] and "confira" in pv["aviso_ano"].lower()
    conf = _enviar(cliente, eid, lista)
    assert conf.status_code == 200, conf.text
    assert conf.json()["alunos_criados"] == 2


def test_ano_so_no_nome_do_arquivo_tambem_e_conferido(cliente, db, escola_completa):
    """Sem a célula, o ano do nome do arquivo é a reserva: também recusa (o aviso diz de
    onde veio o ano, para a escola corrigir o nome se ele estiver errado)."""
    eid = escola_completa["escola"].id
    lista = _planilha(None, ("4º Ano A", [ANA, BETO]))
    pv = _enviar(cliente, eid, lista, "analisar", nome="Lista Piloto 2025.xlsx").json()
    assert pv["ano_letivo"] == 2025 and pv["ano_divergente"] is True
    assert "nome do arquivo" in pv["aviso_ano"]
    conf = _enviar(cliente, eid, lista, nome="Lista Piloto 2025.xlsx")
    assert conf.status_code == 409, conf.text
    assert "nome do arquivo" in conf.json()["detail"]
    db.expire_all()
    assert db.execute(select(func.count()).select_from(Aluno).where(
        Aluno.escola_id == eid, Aluno.nome == ANA[0])).scalar_one() == 0


def test_numero_da_classe_no_nome_do_arquivo_nao_vira_ano(cliente, db, escola_completa):
    """O nº da classe (SED) no nome do arquivo ("300320221") contém "2022": não é ano."""
    eid = escola_completa["escola"].id
    lista = _planilha(None, ("4º Ano A", [ANA, BETO]))
    pv = _enviar(cliente, eid, lista, "analisar", nome="Lista 300320221.xlsx").json()
    assert pv["ano_letivo"] is None and pv["ano_divergente"] is False
    assert _enviar(cliente, eid, lista, nome="Lista 300320221.xlsx").status_code == 200
    assert db.get(Escola, eid).ano_letivo_ativo == 2026


# --- REV2-VIRADA-1: abas de anos diferentes na mesma planilha ------------------------
# A trava conferia só o ano da PRIMEIRA aba com a célula "Lista Piloto:": uma aba velha
# de 2026 copiada à frente das de 2027 fazia o arquivo inteiro "valer" 2026 e as abas de
# 2027 eram gravadas por cima do ano ativo (a matrícula de 2026 mudava de turma).

def _planilha_por_aba(*abas) -> bytes:
    """Uma aba por turma, cada uma com o SEU ano: ``(ano, nome_turma, alunos)``;
    ``ano=None`` é a aba sem a célula do ano."""
    wb = openpyxl.Workbook()
    for i, (ano, nome_turma, alunos) in enumerate(abas):
        ws = wb.active if i == 0 else wb.create_sheet()
        ws.title = nome_turma[:31]
        ws.append([None, None, None, "PREFEITURA MUNICIPAL FICTICIA"])
        if ano is None:
            ws.append(["Escola:", None, "EMEF FICTICIA"])
        else:
            ws.append(["Escola:", None, "EMEF FICTICIA", None, None, None, None,
                       "Lista Piloto:", ano])
        ws.append([])
        ws.append(["Professor:", None, "PROFESSORA FICTICIA", None, "Ano:", nome_turma,
                   "Turno:       TARDE", None, "N.º da Classe (SED):", 300396600 + i])
        ws.append([])
        ws.append(COLUNAS)
        for n, (nome, ra, nasc) in enumerate(alunos, start=1):
            ws.append([n, "", ra, nome, nasc, "MAE", "RUA X, 1", "BAIRRO",
                       "", "", "", "", "F", "PARDA", "NÃO"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


CAIO = ("CAIO FICTICIO NUNES", "900.000.005-0", date(2017, 1, 5))


def test_aba_velha_de_2026_a_frente_das_de_2027_nao_libera_a_gravacao(
        cliente, db, escola_completa):
    """A sonda do revisor: escola em 2026, 1ª aba "Lista Piloto: 2026" (cópia velha),
    2ª aba "Lista Piloto: 2027" com a Ana — que tem matrícula de 2026 no 4º Ano A."""
    eid = escola_completa["escola"].id
    _ano_2026_com_ranking(cliente, db, eid)
    antes = _foto(db, cliente, eid)
    lista = _planilha_por_aba((2026, "3º Ano A", [CAIO]), (2027, "5º Ano A", [ANA, BETO]))

    pv = _enviar(cliente, eid, lista, "analisar").json()
    conf = _enviar(cliente, eid, lista)

    assert conf.status_code == 409, (
        f"aba de 2027 aplicada ao ano 2026: {conf.status_code} {conf.text[:300]}")
    assert _foto(db, cliente, eid) == antes, "a matrícula de 2026 mudou de turma"
    assert pv["ano_divergente"] is True
    # O aviso nomeia as abas de cada ano e diz o que fazer.
    for aviso in (pv["aviso_ano"], conf.json()["detail"]):
        assert "“3º Ano A”" in aviso and "“5º Ano A”" in aviso, aviso
        assert "2026" in aviso and "2027" in aviso
    assert "não pode ser gravada" in pv["aviso_ano"]
    assert "Nada foi gravado" in conf.json()["detail"]
    # Abas de anos diferentes: a lista não "é" de ano nenhum.
    assert pv["ano_letivo"] is None


def test_abas_de_anos_diferentes_na_ordem_inversa_tambem_sao_recusadas(
        cliente, db, escola_completa):
    eid = escola_completa["escola"].id
    _ano_2026_com_ranking(cliente, db, eid)
    antes = _foto(db, cliente, eid)
    lista = _planilha_por_aba((2027, "5º Ano A", [ANA, BETO]), (2026, "3º Ano A", [CAIO]))
    conf = _enviar(cliente, eid, lista)
    assert conf.status_code == 409, conf.text
    assert "“3º Ano A”" in conf.json()["detail"] and "“5º Ano A”" in conf.json()["detail"]
    assert _foto(db, cliente, eid) == antes


def test_abas_de_dois_anos_que_nao_sao_o_da_escola(cliente, db, escola_completa):
    """2027 e 2028 com a escola em 2026: recusada, e o aviso diz os dois anos."""
    eid = escola_completa["escola"].id
    lista = _planilha_por_aba((2027, "4º Ano A", [ANA]), (2028, "5º Ano A", [BETO]))
    pv = _enviar(cliente, eid, lista, "analisar").json()
    assert pv["ano_divergente"] is True
    assert "2027" in pv["aviso_ano"] and "2028" in pv["aviso_ano"]
    assert _enviar(cliente, eid, lista).status_code == 409


def test_todas_as_abas_do_ano_da_escola_seguem(cliente, db, escola_completa):
    """Controle: todas as abas com o ano da escola (e uma aba sem a célula, que vale o
    ano das outras, como sempre valeu) gravam normalmente."""
    eid = escola_completa["escola"].id
    lista = _planilha_por_aba((2026, "4º Ano A", [ANA]), (None, "5º Ano A", [BETO]),
                              (2026, "3º Ano A", [CAIO]))
    pv = _enviar(cliente, eid, lista, "analisar").json()
    assert (pv["ano_letivo"], pv["ano_divergente"], pv["aviso_ano"]) == (2026, False, None)
    conf = _enviar(cliente, eid, lista)
    assert conf.status_code == 200, conf.text
    assert conf.json()["alunos_criados"] == 3


def test_leitor_guarda_o_ano_de_cada_aba():
    from app.services import lista_piloto
    analise = lista_piloto.analisar_matriculas(_planilha_por_aba(
        (2026, "3º Ano A", [CAIO]), (2027, "5º Ano A", [ANA]), (None, "4º Ano B", [BETO])))
    assert analise.anos_por_aba == {"3º Ano A": 2026, "5º Ano A": 2027}
    assert analise.ano_letivo is None and analise.anos_divergentes
    uma = lista_piloto.analisar_matriculas(_planilha_por_aba(
        (2027, "5º Ano A", [ANA]), (2027, "4º Ano A", [BETO])))
    assert uma.ano_letivo == 2027 and not uma.anos_divergentes
