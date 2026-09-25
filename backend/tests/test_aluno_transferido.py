"""Aluno TRANSFERIDO: sai da população ativa, o histórico fica, e a
reimportação da Lista Piloto não o traz de volta sozinha.

O problema real (escola João Timotheo, set/2026): crianças que saíram da escola
continuavam aparecendo nos rankings. Arquivá-las não resolvia — quem sai
CONTINUA na planilha da secretaria, com a movimentação anotada numa coluna que
este importador não interpreta. Na importação seguinte, ``_persistir_linhas``
via "consta na lista atual" e devolvia ``status="ativo"``, desfazendo a decisão
do gestor em silêncio, a cada envio.

A correção é um status terminal — o único que a importação NÃO reverte —, e um
aviso nomeando quem ficou de fora. A classificação continua sendo humana: o
importador não lê códigos de movimentação (TRB/TRE e afins são convenção de
rede, não contrato do sistema) e portanto não inventa transferência nenhuma.

Estes testes travam as duas metades: o que passa a acontecer com ``transferido``
e o que NÃO pode ter mudado para ``arquivado``/``fora_lista_piloto``.
"""
import io
from datetime import date

import openpyxl
from sqlalchemy import select

from app.models import (Aluno, IdentidadeExterna, LogAuditoria, Matricula,
                        Nota, RevisaoIdentidade, Turma)
from app.services import identidade_aluno as ida
from app.services import triagem_revisoes as tri

CT_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
COLUNAS = ["N.º", "RM", "RA", "Nome", "Data de Nasc.", "Responsável",
           "Endereço", "Bairro", "Telefone", "RG", "CPF", "SUS",
           "SEXO", "RAÇA COR", "BOLSA FAMÍLIA"]
ANO = 2026


# --- a planilha real da secretaria ------------------------------------------

def _linha(nome, *, numero=None, ra="", nasc=None, bairro="BAIRRO"):
    return [numero, "", ra, nome, nasc, "MAE", "RUA X, 1", bairro,
            "", "", "", "", "F", "PARDA", "NÃO"]


def _planilha(*turmas) -> bytes:
    wb = openpyxl.Workbook()
    for i, (nome_turma, alunos) in enumerate(turmas):
        ws = wb.active if i == 0 else wb.create_sheet()
        ws.title = nome_turma[:31]
        ws.append([None, None, None, "PREFEITURA MUNICIPAL DE CARAGUATATUBA"])
        ws.append(["Escola:", None, "EMEF TESTE", None, None, None, None,
                   "Lista Piloto:", ANO])
        ws.append([])
        ws.append(["Professor:", None, "PAULA", None, "Ano:", nome_turma,
                   "Turno:       TARDE", None, "N.º da Classe (SED):",
                   300396600 + i])
        ws.append([])
        ws.append(COLUNAS)
        for linha in alunos:
            ws.append(linha)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _confirmar(cliente, escola_id, conteudo):
    r = cliente.post(
        f"/api/v1/escolas/{escola_id}/importacoes/matriculas/confirmar",
        files={"arquivo": ("Lista.xlsx", conteudo, CT_XLSX)})
    assert r.status_code == 200, r.text
    return r.json()


def _acao(cliente, escola_id, acao, ids, **extra):
    r = cliente.post(f"/api/v1/escolas/{escola_id}/alunos/acoes",
                     json={"aluno_ids": ids, "acao": acao, **extra})
    return r


def _por_nome(db, escola_id, nome) -> Aluno:
    db.expire_all()
    achados = db.execute(select(Aluno).where(
        Aluno.escola_id == escola_id, Aluno.nome == nome)).scalars().all()
    assert len(achados) == 1, f"esperava 1 ficha de {nome!r}, achei {len(achados)}"
    return achados[0]


LISTA = _planilha(("3º Ano B", [
    _linha("CLARA MENEZES ROCHA", numero=1, ra="111.100.001-0", nasc=date(2017, 3, 1)),
    _linha("DANIEL FARIAS PINTO", numero=2, ra="111.100.002-0", nasc=date(2017, 4, 2)),
]))


def _cenario(cliente, db, escola_completa):
    """A lista chega, o gestor marca CLARA como transferida. Estado inicial de
    quase todos os testes daqui para baixo."""
    escola_id = escola_completa["escola"].id
    _confirmar(cliente, escola_id, LISTA)
    clara = _por_nome(db, escola_id, "CLARA MENEZES ROCHA")
    assert _acao(cliente, escola_id, "marcar_transferido", [clara.id]).status_code == 200
    db.expire_all()
    return escola_id, clara.id


# ---------------------------------------------------------------------------
# 1. O que "transferido" faz
# ---------------------------------------------------------------------------

def test_1_marcar_transferido_tira_da_populacao_ativa(cliente, db, escola_completa):
    escola_id, clara_id = _cenario(cliente, db, escola_completa)
    assert db.get(Aluno, clara_id).status == "transferido"

    r = cliente.get(f"/api/v1/escolas/{escola_id}/alunos")
    assert r.status_code == 200, r.text
    nomes = [a["nome"] for a in r.json()["itens"]]
    assert "CLARA MENEZES ROCHA" not in nomes
    assert "DANIEL FARIAS PINTO" in nomes, "só a transferida sai"


def test_2_o_historico_continua_inteiro(cliente, db, escola_completa):
    """Nada é apagado: a matrícula do ano, a ficha e a identidade externa ficam.
    É o que separa 'sair do ranking' de 'perder o histórico'."""
    escola_id, clara_id = _cenario(cliente, db, escola_completa)
    db.add(IdentidadeExterna(escola_id=escola_id, aluno_id=clara_id,
                             plataforma="matific", id_externo="uuid-clara"))
    db.commit()

    _confirmar(cliente, escola_id, LISTA)      # mais uma sincronização
    db.expire_all()

    clara = db.get(Aluno, clara_id)
    assert clara is not None, "a ficha não pode ser apagada"
    assert clara.ficha.get("ra"), "a ficha cadastral continua preenchida"
    assert db.execute(select(Matricula).where(
        Matricula.aluno_id == clara_id, Matricula.ano_letivo == ANO)
    ).scalars().all(), "a matrícula do ano letivo continua"
    assert db.execute(select(IdentidadeExterna).where(
        IdentidadeExterna.aluno_id == clara_id)).scalars().all(), \
        "a identidade externa continua provando de quem era a conta"


def test_3_transferido_sai_do_ranking_e_nao_ocupa_posicao(
        cliente, db, escola_completa):
    """O contrato é a VISÃO, não a tabela: a linha em ``notas`` pode sobreviver
    — ela é o histórico de quando o aluno ainda estava aqui, e o mesmo vale para
    arquivado e fora_lista_piloto. O que não pode é ele aparecer no ranking nem
    ocupar uma posição, empurrando para baixo quem ficou."""
    escola_id, clara_id = _cenario(cliente, db, escola_completa)
    from app.services import scoring
    scoring.recalcular_escola(db, escola_id)
    db.expire_all()

    r = cliente.get(f"/api/v1/escolas/{escola_id}/ranking")
    assert r.status_code == 200, r.text
    itens = r.json()
    assert clara_id not in {i["aluno_id"] for i in itens}, \
        "quem saiu da escola não disputa ranking com quem ficou"
    posicoes = sorted(i["posicao"] for i in itens)
    assert posicoes == list(range(1, len(itens) + 1)), \
        f"o transferido deixou um buraco na numeração: {posicoes}"


# ---------------------------------------------------------------------------
# 2. A trava: a reimportação não desfaz a decisão
# ---------------------------------------------------------------------------

def test_4_reimportar_a_mesma_lista_nao_ressuscita_o_transferido(
        cliente, db, escola_completa):
    """O coração da correção. A planilha continua trazendo CLARA — é assim que
    a secretaria trabalha — e isso NÃO é prova de que ela voltou."""
    escola_id, clara_id = _cenario(cliente, db, escola_completa)

    for volta in range(3):
        _confirmar(cliente, escola_id, LISTA)
        db.expire_all()
        assert db.get(Aluno, clara_id).status == "transferido", \
            f"a importação {volta + 1} reativou quem tinha saído"


def test_5_a_importacao_avisa_por_nome_quem_ficou_de_fora(
        cliente, db, escola_completa):
    """Ignorar em silêncio seria trocar um problema invisível por outro."""
    escola_id, _ = _cenario(cliente, db, escola_completa)
    corpo = _confirmar(cliente, escola_id, LISTA)

    avisos = [a for a in corpo["avisos"] if "CLARA MENEZES ROCHA" in a]
    assert len(avisos) == 1, corpo["avisos"]
    assert "TRANSFERIDO" in avisos[0]
    assert "Reativar" in avisos[0], "o aviso diz qual é o caminho de volta"


def test_6_a_linha_ainda_e_aplicada_so_o_status_nao_muda(
        cliente, db, escola_completa):
    """A trava é sobre STATUS, não sobre dados: se a secretaria corrigiu o
    endereço de quem saiu, a correção entra. O que não entra é a reativação."""
    escola_id, clara_id = _cenario(cliente, db, escola_completa)

    _confirmar(cliente, escola_id, _planilha(("3º Ano B", [
        _linha("CLARA MENEZES ROCHA DE ANDRADE", numero=1, ra="111.100.001-0",
               nasc=date(2017, 3, 1)),
        _linha("DANIEL FARIAS PINTO", numero=2, ra="111.100.002-0",
               nasc=date(2017, 4, 2)),
    ])))
    db.expire_all()

    clara = db.get(Aluno, clara_id)
    assert clara.status == "transferido", "o status é o que a trava protege"
    assert clara.nome == "CLARA MENEZES ROCHA DE ANDRADE", \
        "a correção de cadastro feita pela secretaria continua entrando"


def test_7_sumir_da_lista_nao_converte_transferido_em_fora_da_lista(
        cliente, db, escola_completa):
    """A reconciliação incremental só mexe em quem está ATIVO. O motivo da saída
    registrado pelo gestor não pode ser sobrescrito por um motivo genérico."""
    escola_id, clara_id = _cenario(cliente, db, escola_completa)

    _confirmar(cliente, escola_id, _planilha(("3º Ano B", [
        _linha("DANIEL FARIAS PINTO", numero=1, ra="111.100.002-0",
               nasc=date(2017, 4, 2)),
    ])))
    db.expire_all()
    assert db.get(Aluno, clara_id).status == "transferido"


# ---------------------------------------------------------------------------
# 3. Não regredir o que já existia
# ---------------------------------------------------------------------------

def test_8_arquivado_continua_sendo_reativado_pela_lista(
        cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    _confirmar(cliente, escola_id, LISTA)
    clara = _por_nome(db, escola_id, "CLARA MENEZES ROCHA")
    assert _acao(cliente, escola_id, "arquivar", [clara.id]).status_code == 200

    _confirmar(cliente, escola_id, LISTA)
    db.expire_all()
    assert db.get(Aluno, clara.id).status == "ativo", \
        "arquivar continua sendo uma pausa, não uma saída"


def test_9_fora_lista_piloto_continua_sendo_reativado(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    _confirmar(cliente, escola_id, LISTA)
    clara = _por_nome(db, escola_id, "CLARA MENEZES ROCHA")

    _confirmar(cliente, escola_id, _planilha(("3º Ano B", [
        _linha("DANIEL FARIAS PINTO", numero=1, ra="111.100.002-0",
               nasc=date(2017, 4, 2)),
    ])))
    db.expire_all()
    assert db.get(Aluno, clara.id).status == "fora_lista_piloto"

    _confirmar(cliente, escola_id, LISTA)      # voltou para a lista
    db.expire_all()
    assert db.get(Aluno, clara.id).status == "ativo"


def test_10_reativar_desfaz_a_marcacao(cliente, db, escola_completa):
    """Reversível por decisão explícita — a criança voltou de verdade."""
    escola_id, clara_id = _cenario(cliente, db, escola_completa)
    assert _acao(cliente, escola_id, "reativar", [clara_id]).status_code == 200
    db.expire_all()
    assert db.get(Aluno, clara_id).status == "ativo"

    r = cliente.get(f"/api/v1/escolas/{escola_id}/alunos")
    assert "CLARA MENEZES ROCHA" in [a["nome"] for a in r.json()["itens"]]


# ---------------------------------------------------------------------------
# 4. A sincronização de plataforma não escreve em ficha de quem saiu
# ---------------------------------------------------------------------------

def test_11_dado_de_plataforma_para_transferido_vai_para_revisao(
        cliente, db, escola_completa):
    """Matific/Elefante continuam mandando a linha (a conta existe lá). Aplicar
    em silêncio numa ficha de quem saiu é decidir sozinho que a criança voltou —
    exatamente o que o motor de identidade não faz com ficha inativa."""
    escola_id, clara_id = _cenario(cliente, db, escola_completa)
    assert "transferido" in ida.STATUS_INATIVOS

    ctx = ida.carregar_contexto(db, escola_id, ANO)
    linha = ida.LinhaIdentidade(plataforma="matific", nome="CLARA MENEZES ROCHA",
                                turma_nome="3º Ano B")
    decisao = ida.decidir(ctx, linha)
    assert decisao.acao == ida.REVISAR
    assert decisao.motivo == "ficha_inativa"


def test_12_a_triagem_nao_poe_ficha_transferida_na_fila_segura(
        cliente, db, escola_completa):
    """A pendência existe, mas é DECISÃO HUMANA: nenhum lote automático a pega.

    Isto importa porque a fila de revisões é processada em lote pelas categorias
    seguras. Se 'transferido' caísse em SEGURA, o lote associaria o dado e a
    criança que saiu voltaria ao ranking pela porta dos fundos."""
    escola_id, clara_id = _cenario(cliente, db, escola_completa)
    clara = db.get(Aluno, clara_id)

    rev = RevisaoIdentidade(
        escola_id=escola_id, chave="matific|id:uuid-clara|resumo||",
        chave_identidade="matific|id:uuid-clara", plataforma="matific",
        formato="resumo", id_externo="uuid-clara", nome_recebido=clara.nome,
        turma_informada="3 ANO B TARDE (300396600)", motivo="nome_casa_em_outra_sala",
        candidatos=[{"aluno_id": clara.id, "nome": clara.nome}],
        linhas=[{"atividades": 10, "estrelas": 20}],
        contexto={"tipo": "texto", "data_referencia": "2026-09-22T10:00:00"},
        origem="sincronizacao", status="pendente")
    db.add(rev)
    db.commit()

    triagem = tri.triar_escola(db, escola_id)[rev.id]
    assert triagem.classificacao == tri.DECISAO_HUMANA
    assert triagem.motivo == tri.FICHA_INATIVA
    assert any("transferido" in c for c in triagem.conflitos), triagem.conflitos


# ---------------------------------------------------------------------------
# 5. Rastro e vocabulário
# ---------------------------------------------------------------------------

def test_13_marcar_transferido_fica_auditado(cliente, db, escola_completa):
    escola_id, clara_id = _cenario(cliente, db, escola_completa)
    db.expire_all()
    logs = db.execute(select(LogAuditoria).where(
        LogAuditoria.escola_id == escola_id,
        LogAuditoria.acao == "aluno.marcar_transferido")).scalars().all()
    assert len(logs) == 1
    assert logs[0].detalhes["status"] == "transferido"
    assert clara_id in logs[0].detalhes["alunos"]


def test_14_transferir_de_turma_nao_e_marcar_transferido(
        cliente, db, escola_completa):
    """Os dois verbos convivem: um move de sala, o outro registra a saída da
    escola. Confundi-los apagaria uma turma inteira do ranking."""
    escola_id = escola_completa["escola"].id
    _confirmar(cliente, escola_id, LISTA)
    daniel = _por_nome(db, escola_id, "DANIEL FARIAS PINTO")
    destino = db.execute(select(Turma).where(
        Turma.escola_id == escola_id, Turma.nome == "3º Ano A")).scalar_one()

    r = _acao(cliente, escola_id, "transferir", [daniel.id], turma_id=destino.id)
    assert r.status_code == 200, r.text
    db.expire_all()
    assert db.get(Aluno, daniel.id).status == "ativo", \
        "mudar de sala não tira ninguém da escola"


def test_15_acao_desconhecida_continua_recusada(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    _confirmar(cliente, escola_id, LISTA)
    clara = _por_nome(db, escola_id, "CLARA MENEZES ROCHA")
    assert _acao(cliente, escola_id, "transferido", [clara.id]).status_code == 422
