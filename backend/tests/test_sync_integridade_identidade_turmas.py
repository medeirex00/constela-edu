"""Integridade de TURMA, MATRÍCULA e ANO LETIVO na sincronização e na Lista Piloto
(frente B, 22/10/2026 — S8, P06).

O caso real (escola 17, 23/09): a escola arquivou o "1º Ano" e a única turma ativa
da série 1 passou a ser a "1ª Fase" (Educação Infantil). Como "1ª Fase" e "1º Ano"
valem ambas série 1, o reconhecimento da sala pela série mandava a criança do 1º
Ano para a Fase — fora das premiações — e turma arquivada continuava recebendo
matrícula. O que estes testes travam, com dados FICTÍCIOS:

  * rótulo de ANO nunca vira turma de FASE, nem o contrário (a etapa entra na
    comparação), com o Ano arquivado e com as duas turmas ativas;
  * turma ARQUIVADA nunca recebe ficha nem matrícula nova pela sync (revisão
    ``turma_arquivada``), nem é destino da troca de turma do Matific;
  * a Lista Piloto não cria matrícula nova em turma arquivada, não mexe nas
    matrículas que já existem e avisa (nome da turma e como reativar);
  * turma de OUTRO ano letivo não serve de destino (revisão
    ``turma_fora_do_ano_letivo``), nem entra no reconhecimento da sala;
  * a sala reconhecida pela série não gera mais o aviso falso "não casa com
    nenhuma turma" na troca de turma do Matific.
"""
import io
from datetime import date

import openpyxl
import pytest
from sqlalchemy import select

from app.models import Aluno, LogAuditoria, Matricula, Turma
from app.routers.importacoes import (_confirmar_sem_commit, _sincronizar_turma_matific,
                                     _turma_existente_por_tokens)
from app.schemas.importacao import ImportacaoConfirm, LinhaConfirmacao
from app.services import identidade_aluno as ida
from app.services import matriculas, politica_sync
from tests.sync_integridade_comum import (ANO, aluno, aplicar, com_nome, elefante_resumo,
                                          fichas, matific, pendentes, sem_disco,
                                          snap_matific, turma, turmas_de, vincular)
from tests.test_lista_piloto import CT_XLSX, _aba

SALA_1ANO = "1 ANO A TARDE ANUAL (300000001)"
NOVA = "CRIANCA FICTICIA DO PRIMEIRO ANO"


def _fase_e_ano(db, escola_id, *, ano_arquivado: bool):
    fase = turma(db, escola_id, "1ª Fase", "1ª Fase")
    ano1 = turma(db, escola_id, "1º Ano", "1º Ano",
                 status="arquivada" if ano_arquivado else "ativa")
    db.commit()
    return fase, ano1


def _nova_matific():
    return {"nome": NOVA, "nome_abrev": "CRIANCA A", "uuid": "u-nova",
            "estrelas": 9, "atividades": 3}


# ---------------------------------------------------------------------------
# Etapa: Ano × Fase no reconhecimento da sala
# ---------------------------------------------------------------------------

def test_etapa_da_sala():
    assert matriculas.etapa_da_sala("1ª Fase") == matriculas.ETAPA_FORA_DO_FUNDAMENTAL
    assert matriculas.etapa_da_sala("1 FASE A") == matriculas.ETAPA_FORA_DO_FUNDAMENTAL
    assert matriculas.etapa_da_sala(SALA_1ANO) == matriculas.ETAPA_FUNDAMENTAL
    assert matriculas.etapa_da_sala("1º Ano") == matriculas.ETAPA_FUNDAMENTAL
    # rótulo que mente: "1º Ano" no campo, "FASE" no nome → fora do Fundamental
    assert matriculas.etapa_da_sala("1 FASE A", "1º Ano") == matriculas.ETAPA_FORA_DO_FUNDAMENTAL


def test_ano_arquivado_o_rotulo_de_ano_nao_vira_a_fase(db, escola_completa):
    escola = escola_completa["escola"]
    _fase, ano1 = _fase_e_ano(db, escola.id, ano_arquivado=True)
    ctx = ida.carregar_contexto(db, escola.id)
    assert ctx.sala_efetiva("1|A", SALA_1ANO) == "1|A"          # nunca "1 fase"
    assert ctx.sala_arquivada("1|A", SALA_1ANO) == ano1.id      # existe, mas arquivada


def test_as_duas_ativas_cada_rotulo_acha_a_turma_da_sua_etapa(db, escola_completa):
    escola = escola_completa["escola"]
    fase, ano1 = _fase_e_ano(db, escola.id, ano_arquivado=False)
    ctx = ida.carregar_contexto(db, escola.id)
    assert ctx.sala_efetiva("1|A", SALA_1ANO) == ida.chave_sala(ano1.nome)
    assert ctx.sala_efetiva(ida.chave_sala("1ª FASE B"), "1ª FASE B") == ida.chave_sala(fase.nome)


def test_sync_matific_ano_arquivado_crianca_nova_nao_nasce_na_fase(
        db, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    escola = escola_completa["escola"]
    _fase_e_ano(db, escola.id, ano_arquivado=True)
    antes = fichas(db, escola.id)

    aplicar(db, escola, matific(SALA_1ANO, [_nova_matific()]))

    assert fichas(db, escola.id) == antes and com_nome(db, escola.id, NOVA) == []
    [rev] = pendentes(db, escola.id)
    assert rev.motivo == "turma_arquivada" and rev.turma_id is None


def test_sync_elefante_ano_arquivado_crianca_nova_nao_nasce_na_fase(
        db, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    escola = escola_completa["escola"]
    _fase_e_ano(db, escola.id, ano_arquivado=True)
    antes = fichas(db, escola.id)

    aplicar(db, escola, elefante_resumo("1 ANO A TARDE ANUAL", [
        {"studentId": 9700001, "studentName": NOVA, "totalBooksRead": 2}]))

    assert fichas(db, escola.id) == antes
    assert [r.motivo for r in pendentes(db, escola.id)] == ["turma_arquivada"]


def test_ano_arquivado_com_politica_bloquear_tambem_nao_cria(db, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    escola = escola_completa["escola"]
    politica_sync.definir(db, escola.id, "bloquear")
    _fase_e_ano(db, escola.id, ano_arquivado=True)
    antes = fichas(db, escola.id)
    aplicar(db, escola, matific(SALA_1ANO, [_nova_matific()]))
    assert fichas(db, escola.id) == antes
    assert [r.motivo for r in pendentes(db, escola.id)] == ["turma_arquivada"]


def test_as_duas_ativas_crianca_do_1o_ano_vai_para_o_1o_ano(db, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    escola = escola_completa["escola"]
    fase, ano1 = _fase_e_ano(db, escola.id, ano_arquivado=False)
    ja = aluno(db, escola.id, ano1, "ELISA FICTICIA DO PRIMEIRO")
    db.commit()

    aplicar(db, escola, matific(SALA_1ANO, [
        _nova_matific(),
        {"nome": ja.nome, "nome_abrev": "ELISA D", "uuid": "u-elisa",
         "estrelas": 5, "atividades": 2}]))

    [nova] = com_nome(db, escola.id, NOVA)
    assert turmas_de(db, nova.id) == [ano1.id]              # nunca a Fase
    assert snap_matific(db, ja.id) is not None              # a do 1º Ano casa pelo nome
    assert all(fase.id not in turmas_de(db, a.id) for a in (nova, ja))


def test_as_duas_ativas_com_politica_bloquear_pendencia_sugere_o_1o_ano(
        db, escola_completa, monkeypatch):
    sem_disco(monkeypatch)
    escola = escola_completa["escola"]
    politica_sync.definir(db, escola.id, "bloquear")
    _fase, ano1 = _fase_e_ano(db, escola.id, ano_arquivado=False)
    aplicar(db, escola, matific(SALA_1ANO, [_nova_matific()]))
    [rev] = pendentes(db, escola.id)
    assert rev.motivo == "criacao_bloqueada_por_politica" and rev.turma_id == ano1.id


def test_sala_com_arquivada_e_ativa_cria_na_ativa(db, escola_completa, monkeypatch):
    """Duas turmas da MESMA sala, uma arquivada: a ficha nova nasce na ativa (antes
    a arquivada podia ganhar o desempate)."""
    sem_disco(monkeypatch)
    escola = escola_completa["escola"]
    velha = turma(db, escola.id, "4ºA", "4º Ano", status="arquivada")
    atual = turma(db, escola.id, "4 ANO A INTEGRAL", "4º Ano")
    db.commit()
    aplicar(db, escola, matific("4 ANO A INTEGRAL (300309347)", [
        {"nome": "FABIO FICTICIO QUARTO", "nome_abrev": "FABIO Q", "uuid": "u-fabio",
         "estrelas": 3, "atividades": 1}]))
    [f] = com_nome(db, escola.id, "FABIO FICTICIO QUARTO")
    assert turmas_de(db, f.id) == [atual.id] and velha.id not in turmas_de(db, f.id)


def test_importacao_manual_nunca_cria_em_turma_arquivada(db, escola_completa):
    """A rede de segurança do /confirmar vale para qualquer caminho até a turma —
    inclusive a turma ESCOLHIDA na tela."""
    escola = escola_completa["escola"]
    arquivada = turma(db, escola.id, "5º Ano B", "5º Ano", status="arquivada")
    db.commit()
    antes = fichas(db, escola.id)
    corpo = ImportacaoConfirm(plataforma="matific", formato="resumo", tipo="texto",
                              recalcular=False, linhas=[LinhaConfirmacao(
                                  nome="GABI FICTICIA QUINTO", criar_em_turma_id=arquivada.id,
                                  dados={"estrelas": 3, "atividades": 1})])
    _confirmar_sem_commit(dados=corpo, escola_id=escola.id,
                          usuario=escola_completa["admin"], db=db)
    db.flush()
    assert fichas(db, escola.id) == antes
    assert [r.motivo for r in pendentes(db, escola.id)] == ["turma_arquivada"]


# ---------------------------------------------------------------------------
# Troca de turma do Matific (pelo uuid): nunca para Fase nem para arquivada
# ---------------------------------------------------------------------------

def _linha_vinculada(a, uuid, sala):
    return LinhaConfirmacao(nome=a.nome, aluno_id=a.id, via="identidade", dados={
        "matific_uuid": uuid, "turma_relatorio": sala, "estrelas": 1, "atividades": 1})


@pytest.mark.parametrize("destino", ["fase_ativa", "ano_arquivado"])
def test_troca_de_turma_nao_move_para_a_fase_nem_para_a_arquivada(db, escola_completa, destino):
    """A única turma com a série e a letra do Matific é a "1ª Fase A" (outra etapa)
    ou o "1º Ano A" ARQUIVADO: nos dois casos a criança fica onde está, com aviso."""
    escola = escola_completa["escola"]
    segundo = turma(db, escola.id, "2º Ano A", "2º Ano")
    if destino == "fase_ativa":
        turma(db, escola.id, "1ª Fase A", "1ª Fase")               # mesma série e letra
    else:
        turma(db, escola.id, "1º Ano A", "1º Ano", status="arquivada")
    hugo = aluno(db, escola.id, segundo, "HUGO FICTICIO SEGUNDO")
    vincular(db, escola.id, hugo.id, "matific", "u-hugo")
    db.commit()
    assert _turma_existente_por_tokens(db, escola.id, ANO, SALA_1ANO) is None

    avisos: list[str] = []
    movidos = _sincronizar_turma_matific(
        db, escola.id, ANO, {hugo.id: (hugo, [_linha_vinculada(hugo, "u-hugo", SALA_1ANO)])},
        avisos)
    assert movidos == 0 and turmas_de(db, hugo.id) == [segundo.id]
    assert any("revise manualmente" in a for a in avisos)


def test_troca_de_turma_ainda_move_para_turma_ativa_da_mesma_etapa(db, escola_completa):
    # A criança sai de uma sala da MESMA série ("1º Ano B"): mudar de série é a virada
    # do ano letivo, que a coleta não faz (S_G_VIRADA-1) — antes o teste partia do
    # "2º Ano A" e afirmava a mudança de série.
    escola = escola_completa["escola"]
    segundo = turma(db, escola.id, "1º Ano B", "1º Ano")
    turma(db, escola.id, "1ª Fase A", "1ª Fase")
    primeiro = turma(db, escola.id, "1º Ano A", "1º Ano")
    iris = aluno(db, escola.id, segundo, "IRIS FICTICIA SEGUNDO")
    db.commit()
    movidos = _sincronizar_turma_matific(
        db, escola.id, ANO, {iris.id: (iris, [_linha_vinculada(iris, "u-iris", SALA_1ANO)])}, [])
    assert movidos == 1 and turmas_de(db, iris.id) == [primeiro.id]


def test_sala_reconhecida_pela_serie_nao_gera_aviso_falso(db, escola_completa):
    """Escola 17: cadastro "4º Ano" (sem letra, única da série) × Matific "4 ANO A
    INTEGRAL (…)". É a mesma sala — não move e não avisa."""
    escola = escola_completa["escola"]
    quarto = turma(db, escola.id, "4º Ano", "4º Ano")
    jade = aluno(db, escola.id, quarto, "JADE FICTICIA QUARTO")
    vincular(db, escola.id, jade.id, "matific", "u-jade")
    db.commit()
    avisos: list[str] = []
    movidos = _sincronizar_turma_matific(
        db, escola.id, ANO,
        {jade.id: (jade, [_linha_vinculada(jade, "u-jade", "4 ANO A INTEGRAL (300309347)")])},
        avisos)
    assert movidos == 0 and turmas_de(db, jade.id) == [quarto.id]
    assert not any("não casa com nenhuma turma" in a for a in avisos)


# ---------------------------------------------------------------------------
# ANO LETIVO
# ---------------------------------------------------------------------------

def test_turma_de_outro_ano_letivo_nao_serve_de_destino(db, escola_completa):
    escola = escola_completa["escola"]
    passada = turma(db, escola.id, "5º Ano A", "5º Ano", ano_letivo=ANO - 1)
    db.commit()
    antes = fichas(db, escola.id)
    corpo = ImportacaoConfirm(plataforma="matific", formato="resumo", tipo="texto",
                              recalcular=False, linhas=[LinhaConfirmacao(
                                  nome="KARLA FICTICIA QUINTO", criar_em_turma_id=passada.id,
                                  dados={"estrelas": 3, "atividades": 1})])
    _confirmar_sem_commit(dados=corpo, escola_id=escola.id,
                          usuario=escola_completa["admin"], db=db)
    db.flush()
    assert fichas(db, escola.id) == antes
    assert [r.motivo for r in pendentes(db, escola.id)] == ["turma_fora_do_ano_letivo"]


def test_outro_ano_letivo_fica_fora_da_sala_e_do_roster(db, escola_completa, monkeypatch):
    """A turma (e a matrícula) de 2025 não entra no contexto de 2026: não é a sala
    reconhecida pela série, não recebe ficha nova, e a criança que só tem matrícula
    em 2025 não está no roster de 2026 (vai para revisão por homônimo fora da sala,
    nunca é associada às cegas nem duplicada)."""
    sem_disco(monkeypatch)
    escola = escola_completa["escola"]
    quinto_2025 = turma(db, escola.id, "5º Ano", "5º Ano", ano_letivo=ANO - 1)
    lara = aluno(db, escola.id, quinto_2025, "LARA FICTICIA QUINTO", ano_letivo=ANO - 1)
    db.commit()
    ctx = ida.carregar_contexto(db, escola.id)
    assert quinto_2025.id not in ctx.turmas
    assert ctx.sala_efetiva("5|A", "5 ANO A") == "5|A"
    antes = fichas(db, escola.id)

    aplicar(db, escola, matific("5 ANO A (300000005)", [
        {"nome": lara.nome, "nome_abrev": "LARA Q", "uuid": "u-lara", "estrelas": 1,
         "atividades": 1},
        {"nome": "MARIA FICTICIA QUINTO", "nome_abrev": "MARIA Q", "uuid": "u-maria",
         "estrelas": 1, "atividades": 1}]))

    assert fichas(db, escola.id) == antes                        # nada nasce em 2025
    assert turmas_de(db, lara.id) == [quinto_2025.id]
    assert snap_matific(db, lara.id) is None
    motivos = {r.nome_recebido: r.motivo for r in pendentes(db, escola.id)}
    assert motivos["MARIA FICTICIA QUINTO"] == "turma_nao_cadastrada"
    assert motivos[lara.nome] in ("homonimo_em_outra_sala", "candidatos_multiplos")


# ---------------------------------------------------------------------------
# LISTA PILOTO em turma arquivada
# ---------------------------------------------------------------------------

def _linha_lp(numero, ra, nome):
    return [numero, 4000 + numero, ra, nome, date(2019, 2, 2), "RESP", "RUA X", "BAIRRO",
            "", "", "", "", "F", "PARDA", "NÃO"]


def _lista(*abas) -> bytes:
    wb = openpyxl.Workbook()
    primeira = True
    for titulo, linhas in abas:
        ws = wb.active if primeira else wb.create_sheet(titulo)
        ws.title = titulo
        primeira = False
        _aba(ws, titulo, "TARDE", "PROFESSORA FICTICIA", 300000000 + len(titulo), linhas)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_lista_piloto_nao_matricula_em_turma_arquivada_e_avisa(db, cliente, escola_completa):
    escola = escola_completa["escola"]
    arquivada = turma(db, escola.id, "1º Ano", "1º Ano", status="arquivada")
    segundo = turma(db, escola.id, "2º Ano", "2º Ano")
    ja_na_arquivada = aluno(db, escola.id, arquivada, "NINA FICTICIA PRIMEIRO",
                            da_lista_piloto=True, ficha={"ra": "900000011"})
    fora_da_lista = aluno(db, escola.id, arquivada, "OTTO FICTICIO PRIMEIRO",
                          da_lista_piloto=True, ficha={"ra": "900000012"})
    no_segundo = aluno(db, escola.id, segundo, "PAULA FICTICIA SEGUNDO",
                       da_lista_piloto=True, ficha={"ra": "900000013"})
    outro_segundo = aluno(db, escola.id, segundo, "RUI FICTICIO SEGUNDO",
                          da_lista_piloto=True, ficha={"ra": "900000014"})
    db.commit()
    antes = fichas(db, escola.id)
    lista = _lista(
        ("1º ANO", [_linha_lp(1, "900.000.011", ja_na_arquivada.nome),
                    _linha_lp(2, "900.000.099", "SOFIA FICTICIA RECEM CHEGADA"),
                    _linha_lp(3, "900.000.013", no_segundo.nome)]),
        ("2º ANO", [_linha_lp(1, "900.000.014", outro_segundo.nome)]))
    base = f"/api/v1/escolas/{escola.id}/importacoes/matriculas"

    previa = cliente.post(f"{base}/analisar", files={"arquivo": ("L.xlsx", lista, CT_XLSX)})
    assert previa.status_code == 200, previa.text
    assert any("1º Ano" in a and "ARQUIVADA" in a and "Reativar" in a
               for a in previa.json()["avisos"])

    r = cliente.post(f"{base}/confirmar", files={"arquivo": ("L.xlsx", lista, CT_XLSX)})
    assert r.status_code == 200, r.text
    corpo = r.json()
    db.expire_all()

    assert com_nome(db, escola.id, "SOFIA FICTICIA RECEM CHEGADA") == []   # não nasceu
    assert fichas(db, escola.id) == antes
    assert turmas_de(db, ja_na_arquivada.id) == [arquivada.id]   # matrículas intactas
    assert turmas_de(db, fora_da_lista.id) == [arquivada.id]
    assert turmas_de(db, no_segundo.id) == [segundo.id]          # não foi movida
    for a in (ja_na_arquivada, fora_da_lista, no_segundo, outro_segundo):
        assert db.get(Aluno, a.id).status == "ativo"             # ninguém saiu da lista
    assert db.get(Turma, arquivada.id).status == "arquivada"
    assert corpo["alunos_criados"] == 0 and corpo["alunos_fora_lista"] == 0
    aviso = [a for a in corpo["avisos"] if "ARQUIVADA" in a]
    assert len(aviso) == 1 and "1º Ano" in aviso[0] and "3 linha(s)" in aviso[0]
    assert "Reativar" in aviso[0] and "arquivada" in corpo["mensagem"].lower()
    assert db.scalar(select(LogAuditoria).where(
        LogAuditoria.acao == "matriculas.turma_arquivada_ignorada")) is not None


def test_lista_piloto_turma_ativa_continua_igual(db, cliente, escola_completa):
    """Controle: a mesma planilha com o 1º Ano ATIVO matricula a recém-chegada."""
    escola = escola_completa["escola"]
    primeiro = turma(db, escola.id, "1º Ano", "1º Ano")
    db.commit()
    lista = _lista(("1º ANO", [_linha_lp(2, "900.000.099", "SOFIA FICTICIA RECEM CHEGADA")]))
    r = cliente.post(f"/api/v1/escolas/{escola.id}/importacoes/matriculas/confirmar",
                     files={"arquivo": ("L.xlsx", lista, CT_XLSX)})
    assert r.status_code == 200, r.text
    db.expire_all()
    [sofia] = com_nome(db, escola.id, "SOFIA FICTICIA RECEM CHEGADA")
    assert turmas_de(db, sofia.id) == [primeiro.id]
    assert not any("ARQUIVADA" in a for a in r.json()["avisos"])
