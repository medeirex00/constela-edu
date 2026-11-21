"""Virada do ano letivo (G_VIRADA-7): a "sala" de uma matrícula de ANO ANTERIOR não é
a mesma sala no ano novo.

``_carregar_estado`` dava a quem não tem matrícula no ano ativo a sala (série+letra) da
matrícula mais recente, supondo "rematriculado na MESMA sala". Na virada toda criança
avança uma série: o roster do "4º A" usado para as linhas do 4º Ano A de 2027 continha
as crianças do 4º A de 2026, que agora estão no 5º A. O motor aceita abreviação com
candidato único sem identificador nenhum — e a criança NOVA de 2027 herdava a ficha (a
conta da plataforma, o histórico, o cartão do Quest) de quem era do 4º A em 2026.

Agora o roster da sala tem só quem tem matrícula no ANO ATIVO; quem só tem matrícula de
ano anterior continua reconhecível pelo RA e, com nome idêntico, pela mudança de sala
(que exige prova de identidade). Dados fictícios.
"""
import io
from datetime import date

import openpyxl
from sqlalchemy import select

from app.models import Aluno, IdentidadeExterna, LogAuditoria, Matricula, Turma

CT_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
COLUNAS = ["N.º", "RM", "RA", "Nome", "Data de Nasc.", "Responsável",
           "Endereço", "Bairro", "Telefone", "RG", "CPF", "SUS",
           "SEXO", "RAÇA COR", "BOLSA FAMÍLIA"]


def _planilha(ano, *turmas) -> bytes:
    wb = openpyxl.Workbook()
    for i, (nome_turma, alunos) in enumerate(turmas):
        ws = wb.active if i == 0 else wb.create_sheet()
        ws.title = nome_turma[:31]
        ws.append([None, None, None, "PREFEITURA MUNICIPAL FICTICIA"])
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


def _enviar(cliente, escola_id, conteudo, etapa="confirmar"):
    r = cliente.post(f"/api/v1/escolas/{escola_id}/importacoes/matriculas/{etapa}",
                     files={"arquivo": ("Lista.xlsx", conteudo, CT_XLSX)})
    assert r.status_code == 200, r.text
    return r.json()


def _ficha_de_2026(db, escola_id, nome, sala="4º Ano A", conta=None, **campos) -> int:
    """Ficha com matrícula SÓ em 2026 (criada pela coleta, sem RA/nascimento)."""
    turma = db.execute(select(Turma).where(Turma.escola_id == escola_id,
                                           Turma.ano_letivo == 2026,
                                           Turma.nome == sala)).scalar_one_or_none()
    if turma is None:
        turma = Turma(escola_id=escola_id, nome=sala, ano_escolar=sala[:6], ano_letivo=2026)
        db.add(turma)
        db.flush()
    aluno = Aluno(escola_id=escola_id, nome=nome, **campos)
    db.add(aluno)
    db.flush()
    db.add(Matricula(escola_id=escola_id, aluno_id=aluno.id, turma_id=turma.id,
                     ano_letivo=2026))
    if conta:
        db.add(IdentidadeExterna(escola_id=escola_id, aluno_id=aluno.id,
                                 plataforma="matific", id_externo=conta))
    db.commit()
    return aluno.id


def _virar_para_2027(cliente_global, escola_id):
    r = cliente_global.patch(f"/api/v1/escolas/{escola_id}", json={"ano_letivo_ativo": 2027})
    assert r.status_code == 200, r.text


def _matricula_2027(db, aluno_id):
    db.expire_all()
    linha = db.execute(select(Turma.nome).join(Matricula, Matricula.turma_id == Turma.id)
                       .where(Matricula.aluno_id == aluno_id,
                              Matricula.ano_letivo == 2027)).first()
    return linha[0] if linha else None


def test_crianca_nova_do_4a_de_2027_nao_herda_a_ficha_do_4a_de_2026(
        cliente, cliente_global, db, escola_completa):
    eid = escola_completa["escola"].id
    stub = _ficha_de_2026(db, eid, "MARIA E SANTOS", conta="u-maria-ficticia-2026")
    _virar_para_2027(cliente_global, eid)
    # 2027: a menina de 2026 foi para o 5º A (nome completo, RA); no 4º A chega uma
    # criança NOVA, de outra família, com nome parecido.
    antiga = ("MARIA ELISA SANTOS", "900.000.010-0", date(2016, 1, 10))
    nova = ("MARIA EDUARDA SANTOS", "900.000.011-0", date(2017, 9, 9))
    lista = _planilha(2027, ("4º Ano A", [nova]), ("5º Ano A", [antiga]))

    previa = _enviar(cliente, eid, lista, "analisar")
    resultado = _enviar(cliente, eid, lista)

    db.expire_all()
    ficha = db.get(Aluno, stub)
    vinculos = [log.detalhes for log in db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "aluno.identidade_vinculada")).scalars()]
    assert ficha.nome == "MARIA E SANTOS", (
        f"a criança nova herdou a ficha (e a conta) da coorte anterior: {vinculos}")
    assert _matricula_2027(db, stub) is None
    assert vinculos == []
    assert (resultado["alunos_criados"], resultado["alunos_atualizados"]) == (2, 0)
    # A prévia conta o mesmo que a confirmação.
    assert (previa["alunos_novos"], previa["alunos_atualizar"], previa["alunos_em_revisao"]) \
        == (2, 0, 0)
    nova_id = db.execute(select(Aluno.id).where(Aluno.escola_id == eid,
                                                Aluno.nome == nova[0])).scalar_one()
    assert _matricula_2027(db, nova_id) == "4º Ano A"
    conta = db.execute(select(IdentidadeExterna.aluno_id).where(
        IdentidadeExterna.id_externo == "u-maria-ficticia-2026")).scalar_one()
    assert conta == stub


def test_homonimo_novo_na_sala_de_mesmo_nome_vai_para_revisao_sem_prova(
        cliente, cliente_global, db, escola_completa):
    """Nome IDÊNTICO ao de quem era do 4º A em 2026, sem nada que prove ser a mesma
    criança: antes reusava a ficha pelo roster herdado (passo 2, "exato"); agora é a
    mudança de sala sem prova — revisão, nada criado nem alterado."""
    eid = escola_completa["escola"].id
    stub = _ficha_de_2026(db, eid, "JOAO FICTICIO PRADO", conta="u-joao-ficticio-2026")
    _virar_para_2027(cliente_global, eid)
    lista = _planilha(2027, ("4º Ano A", [("JOAO FICTICIO PRADO", "900.000.030-0",
                                          date(2017, 4, 4))]))
    resultado = _enviar(cliente, eid, lista)
    assert resultado["alunos_em_revisao"] == 1
    assert resultado["alunos_criados"] == 0
    db.expire_all()
    ficha = db.get(Aluno, stub)
    assert _matricula_2027(db, stub) is None
    assert (ficha.ficha or {}).get("ra") is None and ficha.data_nascimento is None


def test_quem_tem_ra_da_lista_anterior_continua_reconhecido_na_virada(
        cliente, cliente_global, db, escola_completa):
    """O RA (gravado pela Lista Piloto de 2026) continua reconhecendo a criança na
    virada, em qualquer sala — nada de ficha nova para quem avançou de série."""
    eid = escola_completa["escola"].id
    ana = ("ANA FICTICIA ROCHA", "900.000.040-0", date(2016, 7, 7))
    _enviar(cliente, eid, _planilha(2026, ("4º Ano A", [ana])))
    db.expire_all()
    ana_id = db.execute(select(Aluno.id).where(Aluno.escola_id == eid,
                                               Aluno.nome == ana[0])).scalar_one()
    _virar_para_2027(cliente_global, eid)
    resultado = _enviar(cliente, eid, _planilha(2027, ("5º Ano A", [ana])))
    assert (resultado["alunos_criados"], resultado["alunos_atualizados"],
            resultado["alunos_em_revisao"]) == (0, 1, 0)
    assert _matricula_2027(db, ana_id) == "5º Ano A"


def test_mesma_sala_no_ano_novo_com_nascimento_igual_e_reconhecida(
        cliente, cliente_global, db, escola_completa):
    """Quem repete o 4º A (só matrícula de 2026, sem RA) e traz o MESMO nascimento é
    reconhecido pela mudança de sala com prova — não vira ficha nova."""
    eid = escola_completa["escola"].id
    caio = _ficha_de_2026(db, eid, "CAIO FICTICIO VALE", data_nascimento=date(2016, 5, 5))
    _virar_para_2027(cliente_global, eid)
    resultado = _enviar(cliente, eid, _planilha(2027, ("4º Ano A", [
        ("CAIO FICTICIO VALE", "900.000.050-0", date(2016, 5, 5))])))
    assert (resultado["alunos_criados"], resultado["alunos_atualizados"]) == (0, 1)
    assert _matricula_2027(db, caio) == "4º Ano A"


# --- REV2-VIRADA-2: quem repete (ou passa de ano) com ficha de nome abreviado --------
# O roster da sala ficou só com quem tem matrícula no ano ativo (acima). A criança que
# REPETE o 4º A, cuja ficha veio da coleta com nome abreviado e sem RA nem nascimento
# ("LUIZA F COSTA"), deixou de ser reconhecida no 4º A do ano novo: a Lista Piloto criava
# uma SEGUNDA ficha sem aviso nenhum — e a ficha antiga, com a conta da plataforma e o
# histórico, ficava sem matrícula no ano (fora de "Fundir duplicatas"). Agora a linha é
# conferida contra a sala do ANO ANTERIOR: com identificador forte (nascimento/RA) a
# ficha é reaproveitada; só pelo nome, a ficha nova nasce (a regra da G_VIRADA-7 fica)
# COM um aviso que nomeia a ficha parecida e o caminho para conferir e fundir.

LUIZA = ("LUIZA FICTICIA COSTA", "900.000.050-0", date(2016, 6, 1))


def _fichas_luiza(db, escola_id):
    db.expire_all()
    return db.execute(select(Aluno.id, Aluno.nome).where(
        Aluno.escola_id == escola_id, Aluno.nome.like("LUIZA%")).order_by(Aluno.id)).all()


def _avisos_de(avisos, nome):
    return [a for a in avisos if nome in a and "se parece" in a]


def test_repetente_com_ficha_abreviada_ganha_aviso_e_o_caminho_para_fundir_funciona(
        cliente, cliente_global, db, escola_completa):
    eid = escola_completa["escola"].id
    stub = _ficha_de_2026(db, eid, "LUIZA F COSTA", conta="u-luiza-ficticia-2026")
    _virar_para_2027(cliente_global, eid)
    lista = _planilha(2027, ("4º Ano A", [LUIZA]))

    previa = _enviar(cliente, eid, lista, "analisar")
    resultado = _enviar(cliente, eid, lista)

    # A regra não muda (a ficha nova nasce: o nome sozinho não atravessa o ano)...
    assert resultado["alunos_criados"] == 1
    # ...mas não calada: a prévia e a confirmação avisam a ficha parecida.
    for avisos, verbo in ((previa["avisos"], "será cadastrado"),
                          (resultado["avisos"], "foi cadastrado")):
        do_par = _avisos_de(avisos, "LUIZA F COSTA")
        assert len(do_par) == 1, avisos
        aviso = do_par[0]
        assert LUIZA[0] in aviso and verbo in aviso, aviso
        assert "4º Ano A em 2026" in aviso
        assert "Fundir com outro aluno" in aviso and "pesquisa do topo da página" in aviso
    nova = next(i for i, _n in _fichas_luiza(db, eid) if i != stub)

    # Seguindo o aviso: a pesquisa do topo acha a ficha antiga (ativa, sem turma no ano)
    # e, a partir dela, a busca do "Fundir com outro aluno" acha a ficha nova.
    achados = cliente.get(f"/api/v1/escolas/{eid}/pesquisa", params={"q": "LUIZA F"}).json()
    assert stub in [a["id"] for a in achados["alunos"]]
    busca = cliente.get(f"/api/v1/escolas/{eid}/alunos",
                        params={"busca": "LUIZA", "por_pagina": 8}).json()
    assert nova in [a["id"] for a in busca["itens"]]
    r = cliente.post(f"/api/v1/escolas/{eid}/alunos/fundir",
                     json={"manter_id": stub, "remover_id": nova, "confirmacao": "FUNDIR"})
    assert r.status_code == 200, r.text
    assert [i for i, _n in _fichas_luiza(db, eid)] == [stub]
    assert _matricula_2027(db, stub) == "4º Ano A"
    conta = db.execute(select(IdentidadeExterna.aluno_id).where(
        IdentidadeExterna.id_externo == "u-luiza-ficticia-2026")).scalar_one()
    assert conta == stub


def test_repetente_com_nascimento_igual_reaproveita_a_ficha_abreviada(
        cliente, cliente_global, db, escola_completa):
    """Com identificador forte (o mesmo nascimento), a sala do ano anterior reconhece a
    criança que repetiu mesmo com o nome abreviado: nada de segunda ficha."""
    eid = escola_completa["escola"].id
    stub = _ficha_de_2026(db, eid, "LUIZA F COSTA", data_nascimento=LUIZA[2])
    _virar_para_2027(cliente_global, eid)
    lista = _planilha(2027, ("4º Ano A", [LUIZA]))
    previa = _enviar(cliente, eid, lista, "analisar")
    resultado = _enviar(cliente, eid, lista)
    assert (resultado["alunos_criados"], resultado["alunos_atualizados"]) == (0, 1)
    assert (previa["alunos_novos"], previa["alunos_atualizar"]) == (0, 1)
    assert [i for i, _n in _fichas_luiza(db, eid)] == [stub]
    db.expire_all()
    assert db.get(Aluno, stub).nome == LUIZA[0]
    assert _matricula_2027(db, stub) == "4º Ano A"


def test_promovido_com_ficha_abreviada_tambem_ganha_aviso(
        cliente, cliente_global, db, escola_completa):
    """Quem passou do 4º A para o 5º A com a ficha abreviada da coleta: a linha do 5º A
    nasce como ficha nova, mas com o aviso da ficha parecida do 4º A do ano anterior."""
    eid = escola_completa["escola"].id
    _ficha_de_2026(db, eid, "LUIZA F COSTA")
    _virar_para_2027(cliente_global, eid)
    resultado = _enviar(cliente, eid, _planilha(2027, ("5º Ano A", [LUIZA])))
    assert resultado["alunos_criados"] == 1
    assert len(_avisos_de(resultado["avisos"], "LUIZA F COSTA")) == 1, resultado["avisos"]


def test_ficha_parecida_arquivada_o_aviso_diz_como_abrir_e_reativar(
        cliente, cliente_global, db, escola_completa):
    eid = escola_completa["escola"].id
    _ficha_de_2026(db, eid, "LUIZA F COSTA", status="arquivado")
    _virar_para_2027(cliente_global, eid)
    resultado = _enviar(cliente, eid, _planilha(2027, ("4º Ano A", [LUIZA])))
    do_par = _avisos_de(resultado["avisos"], "LUIZA F COSTA")
    assert len(do_par) == 1, resultado["avisos"]
    aviso = do_par[0]
    assert "está arquivada" in aviso and "Mostrar arquivados" in aviso
    assert "Reativar" in aviso and "Fundir com outro aluno" in aviso


def test_maria_eduarda_continua_sem_herdar_a_ficha_e_o_aviso_nomeia_a_parecida(
        cliente, cliente_global, db, escola_completa):
    """A G_VIRADA-7 fica: a criança nova do 4º A de 2027 ganha ficha própria; o aviso só
    pede para conferir (se forem crianças diferentes, nada a fazer)."""
    eid = escola_completa["escola"].id
    stub = _ficha_de_2026(db, eid, "MARIA E SANTOS")
    _virar_para_2027(cliente_global, eid)
    nova = ("MARIA EDUARDA SANTOS", "900.000.011-0", date(2017, 9, 9))
    resultado = _enviar(cliente, eid, _planilha(2027, ("4º Ano A", [nova])))
    assert resultado["alunos_criados"] == 1
    db.expire_all()
    assert db.get(Aluno, stub).nome == "MARIA E SANTOS"
    assert _matricula_2027(db, stub) is None
    do_par = _avisos_de(resultado["avisos"], "MARIA E SANTOS")
    assert len(do_par) == 1, resultado["avisos"]
    assert "crianças diferentes, não é preciso fazer nada" in do_par[0]


def test_ficha_ja_reconhecida_por_outra_linha_nao_gera_aviso(
        cliente, cliente_global, db, escola_completa):
    """A ficha antiga que OUTRA linha do arquivo reconhece pelo RA não é "parecida" de
    ninguém: ela já tem dono neste envio."""
    eid = escola_completa["escola"].id
    # A ficha antiga tem RA (sem nascimento); a linha do 4º A não tem RA: nada veta o
    # par pelo nome — só o dono (a linha do 5º A, pelo RA) tira a ficha da conferência.
    luiza = ("LUIZA F COSTA", "900.000.060-0", None)
    _enviar(cliente, eid, _planilha(2026, ("4º Ano A", [luiza])))
    _virar_para_2027(cliente_global, eid)
    resultado = _enviar(cliente, eid, _planilha(
        2027, ("4º Ano A", [(LUIZA[0], "", LUIZA[2])]), ("5º Ano A", [luiza])))
    assert resultado["alunos_criados"] == 1 and resultado["alunos_atualizados"] == 1
    assert _avisos_de(resultado["avisos"], "LUIZA F COSTA") == [], resultado["avisos"]


def test_dentro_do_ano_nada_muda(cliente, db, escola_completa):
    """Controle: a ficha abreviada com matrícula NO ANO ATIVO continua reconhecida pelo
    roster da sala (abreviação, candidato único), sem aviso."""
    eid = escola_completa["escola"].id
    stub = _ficha_de_2026(db, eid, "LUIZA F COSTA")
    resultado = _enviar(cliente, eid, _planilha(2026, ("4º Ano A", [LUIZA])))
    assert (resultado["alunos_criados"], resultado["alunos_atualizados"]) == (0, 1)
    assert [i for i, _n in _fichas_luiza(db, eid)] == [stub]
    assert _avisos_de(resultado["avisos"], "LUIZA") == []
