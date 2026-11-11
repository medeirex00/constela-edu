"""Virada do ano letivo (G_VIRADA-8): a linha da Lista Piloto que vai para revisão por
"mudança de sala sem prova" diz um caminho que FUNCIONA.

Na virada toda criança muda de sala. A ficha criada pela coleta (sem RA nem nascimento)
cai no passo 3 de ``resolver_linha``: nome idêntico em outra sala (ou sem turma no ano),
nada que prove ser a mesma criança → REVISÃO, que não cria nem altera nada (a regra de
identidade é essa, e fica). O defeito era o aviso: mandava resolver em "Alunos › Fundir
duplicatas", mas não há duplicata nenhuma, e quem está sem turma no ano ativo nem
aparece lá — a tela ficava vazia e a criança, sem matrícula no ano novo para sempre.

Agora o aviso desse motivo leva à ficha (pesquisa do topo › três pontinhos › Editar
dados › Turma) e diz o que fazer se forem crianças diferentes; o teste segue os dois
caminhos até o fim. A prévia conta essas linhas como "em revisão", não como novas.
Dados fictícios.
"""
import io
from datetime import date

import openpyxl
import pytest
from sqlalchemy import select

from app.models import Aluno, Matricula, Turma
from app.services import matriculas

CT_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
COLUNAS = ["N.º", "RM", "RA", "Nome", "Data de Nasc.", "Responsável",
           "Endereço", "Bairro", "Telefone", "RG", "CPF", "SUS",
           "SEXO", "RAÇA COR", "BOLSA FAMÍLIA"]
BRUNO = ("BRUNO FICTICIO ALVES", "900.000.020-0", date(2016, 2, 20))


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


def _bruno_da_coleta_no_4a_de_2026(db, escola_id) -> int:
    t4a = Turma(escola_id=escola_id, nome="4º Ano A", ano_escolar="4º Ano", ano_letivo=2026)
    db.add(t4a)
    db.flush()
    bruno = Aluno(escola_id=escola_id, nome=BRUNO[0])       # criado pela coleta
    db.add(bruno)
    db.flush()
    db.add(Matricula(escola_id=escola_id, aluno_id=bruno.id, turma_id=t4a.id,
                     ano_letivo=2026))
    db.commit()
    return bruno.id


def _matricula(db, aluno_id, ano):
    db.expire_all()
    linha = db.execute(select(Turma.nome).join(Matricula, Matricula.turma_id == Turma.id)
                       .where(Matricula.aluno_id == aluno_id,
                              Matricula.ano_letivo == ano)).first()
    return linha[0] if linha else None


def _aviso_do_bruno(avisos):
    do_bruno = [a for a in avisos if BRUNO[0] in a]
    assert len(do_bruno) == 1, avisos
    return do_bruno[0]


def test_promovido_sem_ra_o_aviso_leva_a_ficha_e_o_caminho_funciona(
        cliente, cliente_global, db, escola_completa):
    eid = escola_completa["escola"].id
    bid = _bruno_da_coleta_no_4a_de_2026(db, eid)
    assert cliente_global.patch(f"/api/v1/escolas/{eid}",
                                json={"ano_letivo_ativo": 2027}).status_code == 200
    lista = _planilha(2027, ("5º Ano A", [BRUNO]))

    # A prévia conta a linha como "em revisão", não como aluno novo.
    previa = _enviar(cliente, eid, lista, "analisar")
    assert (previa["alunos_novos"], previa["alunos_atualizar"],
            previa["alunos_em_revisao"]) == (0, 0, 1)
    resultado = _enviar(cliente, eid, lista)
    assert resultado["alunos_em_revisao"] == 1 and resultado["alunos_criados"] == 0
    aviso = _aviso_do_bruno(resultado["avisos"])
    # "Fundir duplicatas" não mostra nada aqui (não há duplicata, e sem turma no ano a
    # ficha nem aparece lá): o aviso não pode mandar para lá.
    dedup = cliente.get(f"/api/v1/escolas/{eid}/alunos/duplicados").json()
    assert dedup["total"] == 0
    assert "Fundir duplicatas" not in aviso, aviso
    assert "pesquisa do topo" in aviso and "Editar dados" in aviso
    assert "turma 5º Ano A" in aviso
    assert _matricula(db, bid, 2027) is None

    # Seguindo o aviso: a pesquisa do topo acha a ficha...
    achados = cliente.get(f"/api/v1/escolas/{eid}/pesquisa", params={"q": "BRUNO"}).json()
    assert bid in [a["id"] for a in achados["alunos"]]
    # ...e Editar dados › Turma (a tela manda /alunos/acoes "transferir") a matricula.
    t5a = db.execute(select(Turma.id).where(Turma.escola_id == eid, Turma.ano_letivo == 2027,
                                            Turma.nome == "5º Ano A")).scalar_one()
    r = cliente.post(f"/api/v1/escolas/{eid}/alunos/acoes",
                     json={"aluno_ids": [bid], "acao": "transferir", "turma_id": t5a})
    assert r.status_code == 200, r.text
    # No próximo envio da planilha, a ficha recebe os dados da linha.
    de_novo = _enviar(cliente, eid, lista)
    assert (de_novo["alunos_em_revisao"], de_novo["alunos_criados"]) == (0, 0)
    db.expire_all()
    ficha = db.get(Aluno, bid)
    assert ficha.data_nascimento == BRUNO[2]
    assert (ficha.ficha or {}).get("ra")
    assert _matricula(db, bid, 2027) == "5º Ano A"


def test_criancas_diferentes_o_nascimento_separa_e_a_linha_vira_cadastro_novo(
        cliente, cliente_global, db, escola_completa):
    """A outra metade do aviso: se forem crianças diferentes, registrar o nascimento da
    que já está cadastrada faz o próximo envio criar a ficha da linha."""
    eid = escola_completa["escola"].id
    bid = _bruno_da_coleta_no_4a_de_2026(db, eid)
    assert cliente_global.patch(f"/api/v1/escolas/{eid}",
                                json={"ano_letivo_ativo": 2027}).status_code == 200
    lista = _planilha(2027, ("5º Ano A", [BRUNO]))
    assert _enviar(cliente, eid, lista)["alunos_em_revisao"] == 1
    r = cliente.patch(f"/api/v1/escolas/{eid}/alunos/{bid}",
                      json={"data_nascimento": "2015-12-01"})
    assert r.status_code == 200, r.text
    de_novo = _enviar(cliente, eid, lista)
    assert (de_novo["alunos_em_revisao"], de_novo["alunos_criados"]) == (0, 1)
    db.expire_all()
    assert db.get(Aluno, bid).data_nascimento == date(2015, 12, 1)
    assert _matricula(db, bid, 2027) is None


def test_dentro_do_ano_o_aviso_da_mudanca_de_sala_sem_prova_tambem_leva_a_ficha(
        cliente, db, escola_completa):
    """O mesmo motivo dentro do ano (a ficha da coleta no 4º A, a lista no 5º A): o
    aviso também não manda para "Fundir duplicatas"."""
    eid = escola_completa["escola"].id
    bid = _bruno_da_coleta_no_4a_de_2026(db, eid)
    resultado = _enviar(cliente, eid, _planilha(2026, ("5º Ano A", [BRUNO])))
    assert resultado["alunos_em_revisao"] == 1
    aviso = _aviso_do_bruno(resultado["avisos"])
    assert "Fundir duplicatas" not in aviso and "Editar dados" in aviso
    assert _matricula(db, bid, 2026) == "4º Ano A"


def test_outros_motivos_de_revisao_continuam_com_o_caminho_de_antes():
    """Só o motivo da mudança de sala sem prova muda de texto: a ambiguidade de nome na
    mesma sala continua em "Fundir duplicatas"."""
    geral = matriculas.aviso_revisao("AGATHA VIOLETA", "1º Ano A", "AGATHA V, AGATHA V")
    assert "Fundir duplicatas" in geral
    assert matriculas.aviso_revisao("AGATHA VIOLETA", "1º Ano A", "AGATHA V, AGATHA V",
                                    "disputado_por_varias_linhas") == geral
    sem_prova = matriculas.aviso_revisao("JOAO FICTICIO", "1º Ano B", "JOAO FICTICIO",
                                         "mudanca_de_sala_sem_prova")
    assert "Fundir duplicatas" not in sem_prova and "turma 1º Ano B" in sem_prova


# --- REV2-VIRADA-4: a ficha parecida não está ativa ----------------------------------
# O aviso mandava procurar o nome na pesquisa do topo da página, mas a pesquisa só acha
# fichas ATIVAS: com a ficha arquivada, transferida ou fora da Lista Piloto, o caminho
# indicado não levava a lugar nenhum. Agora o aviso diz a situação da ficha e o caminho
# que a abre (o painel da turma dela, com "Mostrar arquivados").

def _ficha_inativa_no_4a_de_2026(db, escola_id, nome, status) -> int:
    t4a = Turma(escola_id=escola_id, nome="4º Ano A", ano_escolar="4º Ano", ano_letivo=2026)
    db.add(t4a)
    db.flush()
    aluno = Aluno(escola_id=escola_id, nome=nome, status=status)
    db.add(aluno)
    db.flush()
    db.add(Matricula(escola_id=escola_id, aluno_id=aluno.id, turma_id=t4a.id,
                     ano_letivo=2026))
    db.commit()
    return aluno.id


@pytest.mark.parametrize("status,situacao", [
    ("arquivado", "arquivada"),
    ("transferido", "marcada como transferida"),
    ("fora_lista_piloto", "fora da Lista Piloto"),
], ids=["arquivado", "transferido", "fora_lista"])
def test_ficha_parecida_inativa_o_aviso_diz_a_situacao_e_o_caminho_funciona(
        cliente, cliente_global, db, escola_completa, status, situacao):
    eid = escola_completa["escola"].id
    nome = f"CAIO FICTICIO {status.upper()}"
    cid = _ficha_inativa_no_4a_de_2026(db, eid, nome, status)
    assert cliente_global.patch(f"/api/v1/escolas/{eid}",
                                json={"ano_letivo_ativo": 2027}).status_code == 200
    linha = (nome, "900.000.040-0", date(2016, 5, 1))
    lista = _planilha(2027, ("5º Ano A", [linha]))

    previa = _enviar(cliente, eid, lista, "analisar")
    resultado = _enviar(cliente, eid, lista)
    assert resultado["alunos_em_revisao"] == 1 and resultado["alunos_criados"] == 0
    for avisos in (previa["avisos"], resultado["avisos"]):
        aviso = next(a for a in avisos if nome in a and "mesmo nome" in a)
        # A pesquisa do topo não acha a ficha inativa: o aviso não pode mandar para lá.
        achados = cliente.get(f"/api/v1/escolas/{eid}/pesquisa",
                              params={"q": "CAIO"}).json()
        assert cid not in [a["id"] for a in achados["alunos"]]
        assert "procure o nome na pesquisa do topo" not in aviso, aviso
        assert f"está {situacao}" in aviso, aviso
        assert "não aparece na pesquisa do topo da página" in aviso
        assert "Mostrar arquivadas e de outros anos" in aviso
        assert "turma 4º Ano A de 2026" in aviso and "Mostrar arquivados" in aviso
        assert "Reativar" in aviso and "turma 5º Ano A" in aviso

    # Seguindo o aviso: o painel da turma de 2026, com "Mostrar arquivados", mostra a
    # ficha...
    t4a = db.execute(select(Turma.id).where(Turma.escola_id == eid, Turma.ano_letivo == 2026,
                                            Turma.nome == "4º Ano A")).scalar_one()
    painel = cliente.get(f"/api/v1/escolas/{eid}/turmas/{t4a}/alunos",
                         params={"incluir_inativos": "true"})
    assert painel.status_code == 200, painel.text
    assert cid in [a["id"] for a in painel.json()]
    # ...Editar dados › Turma a leva ao 5º Ano A de 2027 e "Reativar" a traz de volta...
    t5a = db.execute(select(Turma.id).where(Turma.escola_id == eid, Turma.ano_letivo == 2027,
                                            Turma.nome == "5º Ano A")).scalar_one()
    r = cliente.post(f"/api/v1/escolas/{eid}/alunos/acoes",
                     json={"aluno_ids": [cid], "acao": "transferir", "turma_id": t5a})
    assert r.status_code == 200, r.text
    r = cliente.post(f"/api/v1/escolas/{eid}/alunos/acoes",
                     json={"aluno_ids": [cid], "acao": "reativar"})
    assert r.status_code == 200, r.text
    # ...e o próximo envio da planilha aplica a linha na mesma ficha.
    de_novo = _enviar(cliente, eid, lista)
    assert (de_novo["alunos_em_revisao"], de_novo["alunos_criados"]) == (0, 0)
    db.expire_all()
    ficha = db.get(Aluno, cid)
    assert ficha.status == "ativo" and ficha.data_nascimento == linha[2]
    assert _matricula(db, cid, 2027) == "5º Ano A"


def test_ficha_ativa_continua_com_o_caminho_da_pesquisa():
    """Controle: a ficha ATIVA (a pesquisa do topo a acha) mantém o texto de antes."""
    ativa = matriculas.aviso_revisao("JOAO FICTICIO", "1º Ano B", "JOAO FICTICIO",
                                     "mudanca_de_sala_sem_prova",
                                     ficha=matriculas.FichaCandidata(
                                         nome="JOAO FICTICIO", status="ativo",
                                         turma="1º Ano A", ano=2026, turma_a_vista=True))
    assert ativa == matriculas.aviso_revisao("JOAO FICTICIO", "1º Ano B", "JOAO FICTICIO",
                                             "mudanca_de_sala_sem_prova")
    assert "pesquisa do topo da página" in ativa


def test_ficha_inativa_numa_turma_do_ano_nao_pede_para_ligar_outros_anos():
    """A ficha arquivada numa turma ATIVA do ano letivo: a turma já aparece em Turmas."""
    aviso = matriculas.aviso_revisao(
        "JOAO FICTICIO", "1º Ano B", "JOAO FICTICIO", "mudanca_de_sala_sem_prova",
        ficha=matriculas.FichaCandidata(nome="JOAO FICTICIO", status="arquivado",
                                        turma="1º Ano A", ano=2026, turma_a_vista=True))
    assert "abra a turma 1º Ano A" in aviso and "Mostrar arquivados" in aviso
    assert "Mostrar arquivadas e de outros anos" not in aviso


def test_ficha_inativa_sem_turma_nao_promete_caminho_que_nao_existe():
    aviso = matriculas.aviso_revisao(
        "JOAO FICTICIO", "1º Ano B", "JOAO FICTICIO", "mudanca_de_sala_sem_prova",
        ficha=matriculas.FichaCandidata(nome="JOAO FICTICIO", status="arquivado"))
    assert "pesquisa do topo da página e abra" not in aviso
    assert "sem turma" in aviso and "Suporte" in aviso
