"""Importação do relatório do Matific em Excel (.xlsx).

Reproduz em memória a estrutura REAL do "Relatório de Atividade do Aluno"
exportado pelo Matific: metadados no topo, uma linha "Toda a turma" com os
totais, contas de aluno DUPLICADAS (uma zerada, outra real) e a coluna
"Pontuação média" como fração 0–1, sem coluna de estrelas.
"""
import io

import openpyxl
import pytest

from app.models import SnapshotMatific
from app.services.planilhas import analisar_planilha

CT_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

CABECALHO = [
    "Alunos", "Total de atividades concluídas", "Atividades únicas Concluídas",
    "Tempo gasto", "Pontuação média", "Frações", "Geometria Plana",
]


def _xlsx(alunos, *, cabecalho=None, totais_rotulo="Toda a turma",
          com_abas_aluno=True) -> bytes:
    """Monta um .xlsx no formato do Matific. `alunos` são as linhas de dados."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Turma - 5 ANO B (30)"
    ws.append(["Relatório de Atividade do Aluno", None, "Exportado em: 7 jul 2026"])
    ws.append([])
    ws.append(["Turma", "5 ANO B MANHA ANUAL (300397500)"])
    ws.append(["Professor(a)", "Andressa Evangelista"])
    ws.append(["Tópico", "Tópicos da Matific"])
    ws.append(["Datas", "6 jun 2026 - 7 jul 2026"])
    ws.append([])
    ws.append(cabecalho or CABECALHO)
    ws.append([totais_rotulo, 371, 93, "28 h 33 min", 0.31, 0.5, 0.4])  # totais
    for linha in alunos:
        ws.append(linha)
    if com_abas_aluno:
        for linha in alunos:  # abas por aluno (só metadados) — devem ser ignoradas
            aba = wb.create_sheet(str(linha[0])[:28] or "aluno")
            aba.append(["Aluno", linha[0]])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


ALUNOS_PADRAO = [
    ["CARLOS EDUARDO RODRIGUES SANTOS", 0, 0, "-", "-", "-", "-"],   # conta vazia
    ["Carlos Eduardo Rodrigues Santos", 30, 22, "2 h 4 min", 0.48, 0.6, "-"],  # real
    ["EMANUELLE MOREIRA SOARES", 7, 5, "53 min", 0.64, "-", "-"],
    ["VERONICA OLIVEIRA MARCOLINO GOES", 0, 0, "-", "-", "-", "-"],
]


# --- Parser puro --------------------------------------------------------------

def test_planilha_matific_le_alunos_turma_e_pontuacao():
    analise = analisar_planilha(_xlsx(ALUNOS_PADRAO))
    assert analise.plataforma == "matific"
    assert analise.formato == "resumo"
    assert analise.estrategia == "planilha_matific"
    assert analise.turma_detectada == "5 ANO B MANHA ANUAL"  # código () removido
    assert analise.professor_detectado == "Andressa Evangelista"
    nomes = [l.nome for l in analise.linhas]
    # 4 linhas → 3 alunos (Carlos duplicado colapsa; "Toda a turma" fora).
    assert len(analise.linhas) == 3
    assert "Toda a turma" not in nomes


def test_planilha_deduplica_mantendo_conta_com_mais_atividades():
    analise = analisar_planilha(_xlsx(ALUNOS_PADRAO))
    carlos = [l for l in analise.linhas if "carlos" in l.nome.casefold()]
    assert len(carlos) == 1
    # Mantém a conta real (30 atividades), não a duplicata zerada.
    assert carlos[0].dados["atividades"] == 30.0
    # Pontuação 0.48 (escala 0–1) alinhada à escala 0–5 do PDF: ×5 = 2.4.
    assert carlos[0].dados["pontuacao_media"] == 2.4
    assert carlos[0].dados["turma_relatorio"] == "5 ANO B MANHA ANUAL"


def test_planilha_pontuacao_alinhada_a_escala_do_pdf():
    """A pontuação do Excel (0–1) é multiplicada por 5 para casar com a escala
    0–5 do relatório GERAL em PDF (senão o scoring rebaixaria ~5× o Excel)."""
    analise = analisar_planilha(_xlsx(ALUNOS_PADRAO))
    emanuelle = next(l for l in analise.linhas if l.nome.startswith("EMANUELLE"))
    assert emanuelle.dados["pontuacao_media"] == 3.2  # 0.64 × 5


def test_planilha_nao_confunde_atividades_unicas_com_total():
    analise = analisar_planilha(_xlsx(ALUNOS_PADRAO))
    emanuelle = next(l for l in analise.linhas if l.nome.startswith("EMANUELLE"))
    assert emanuelle.dados["atividades"] == 7.0     # "Total de atividades", não 5


def test_planilha_rotulo_curto_atividades_ainda_e_o_total():
    """Variação de export: a coluna de total vem só como 'Atividades' (sem
    'Total de…'). Deve continuar sendo o total, não a coluna de únicas."""
    cab = ["Alunos", "Atividades", "Atividades Únicas Concluídas",
           "Tempo gasto", "Pontuação média"]
    alunos = [["ANA SOUZA", 42, 20, "1 h", 0.5]]
    analise = analisar_planilha(_xlsx(alunos, cabecalho=cab, com_abas_aluno=False))
    ana = analise.linhas[0]
    assert ana.dados["atividades"] == 42.0   # o total, não as 20 únicas
    assert ana.dados["pontuacao_media"] == 2.5


def test_planilha_celula_traco_nao_vira_erro():
    analise = analisar_planilha(_xlsx(ALUNOS_PADRAO))
    veronica = next(l for l in analise.linhas if l.nome.startswith("VERONICA"))
    assert veronica.dados.get("atividades") == 0.0
    assert "pontuacao_media" not in veronica.dados
    assert veronica.avisos == []


def test_planilha_preserva_homonimos_reais_com_aviso():
    """Dois alunos REAIS com o mesmo nome (ambos com atividades) são
    preservados e um aviso é emitido — nunca some aluno em silêncio."""
    alunos = [
        ["JOAO SILVA", 30, 20, "2 h", 0.5, "-", "-"],
        ["JOAO SILVA", 12, 8, "1 h", 0.4, "-", "-"],
        ["MARIA LIMA", 5, 3, "20 min", 0.3, "-", "-"],
    ]
    analise = analisar_planilha(_xlsx(alunos))
    joaos = [l for l in analise.linhas if l.nome == "JOAO SILVA"]
    assert len(joaos) == 2                           # os dois preservados
    assert {j.dados["atividades"] for j in joaos} == {30.0, 12.0}
    assert any("repetido" in e.casefold() or "joao silva" in e.casefold()
               for e in analise.erros_gerais)


def test_planilha_conta_vazia_duplicada_colapsa_sem_aviso():
    alunos = [
        ["PEDRO ALVES", 0, 0, "-", "-", "-", "-"],     # conta vazia
        ["Pedro Alves", 25, 18, "2 h", 0.6, "-", "-"],  # real
    ]
    analise = analisar_planilha(_xlsx(alunos))
    pedros = [l for l in analise.linhas if "pedro" in l.nome.casefold()]
    assert len(pedros) == 1
    assert pedros[0].dados["atividades"] == 25.0
    assert analise.erros_gerais == []                # duplicata não gera aviso


@pytest.mark.parametrize("rotulo", ["Whole class", "Toda la clase", "Turma toda"])
def test_planilha_ignora_linha_de_totais_em_outro_idioma(rotulo):
    analise = analisar_planilha(_xlsx(ALUNOS_PADRAO, totais_rotulo=rotulo))
    nomes = [l.nome.casefold() for l in analise.linhas]
    assert rotulo.casefold() not in nomes
    # a linha-fantasma (371 atividades) não entra
    assert all(l.dados.get("atividades", 0) != 371.0 for l in analise.linhas)


def test_planilha_invalida_da_erro_amigavel():
    with pytest.raises(ValueError):
        analisar_planilha(b"isto nao e um arquivo excel")


# --- Fluxo pela API -----------------------------------------------------------

def test_analisar_xlsx_pela_api(cliente, escola_completa):
    escola_id = escola_completa["escola"].id
    resposta = cliente.post(
        f"/api/v1/escolas/{escola_id}/importacoes/analisar",
        files={"arquivo": ("Relatório de Atividade do Aluno - 5 ANO B.xlsx",
                           _xlsx(ALUNOS_PADRAO), CT_XLSX)},
    )
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["plataforma"] == "matific"
    assert corpo["tipo"] == "xlsx"
    assert corpo["formato"] == "resumo"
    assert corpo["turma_detectada"] == "5 ANO B MANHA ANUAL"
    assert corpo["total_alunos"] == 3
    assert corpo["arquivo_token"]  # o Excel original é arquivado (§15)


def test_confirmar_xlsx_cria_alunos_e_snapshots(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    turma_id = escola_completa["turma"].id
    analise = cliente.post(
        f"/api/v1/escolas/{escola_id}/importacoes/analisar",
        files={"arquivo": ("turma.xlsx", _xlsx(ALUNOS_PADRAO), CT_XLSX)},
    ).json()
    linhas = [
        {"nome": l["nome"], "dados": l["dados"], "criar_em_turma_id": turma_id}
        for l in analise["linhas"]
    ]
    resposta = cliente.post(
        f"/api/v1/escolas/{escola_id}/importacoes/confirmar",
        json={"plataforma": "matific", "formato": "resumo", "tipo": "xlsx",
              "arquivo_token": analise["arquivo_token"],
              "arquivo_nome": "turma.xlsx", "linhas": linhas},
    )
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["qtd_alunos"] == 3
    from app.models import Aluno
    carlos = db.query(Aluno).filter(Aluno.nome.ilike("carlos%")).one()
    snap = db.query(SnapshotMatific).filter_by(aluno_id=carlos.id).one()
    assert snap.atividades == 30
    assert snap.pontuacao_media == pytest.approx(2.4)
    assert snap.estrelas == 0  # o Excel não traz estrelas


def test_xlsx_sem_estrelas_preserva_estrelas_do_pdf_anterior(cliente, db, escola_completa):
    """Importa o PDF de estrelas (tem estrelas) e depois o Excel (não tem):
    as estrelas do PDF são PRESERVADAS em vez de zeradas."""
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    cliente.post(
        f"/api/v1/escolas/{escola_id}/importacoes/confirmar",
        json={"plataforma": "matific", "formato": "resumo", "tipo": "pdf",
              "linhas": [{"nome": ana.nome,
                          "dados": {"atividades": 100, "pontuacao_media": 3.6,
                                    "estrelas": 900},
                          "aluno_id": ana.id}]},
    )
    cliente.post(
        f"/api/v1/escolas/{escola_id}/importacoes/confirmar",
        json={"plataforma": "matific", "formato": "resumo", "tipo": "xlsx",
              "linhas": [{"nome": ana.nome,
                          "dados": {"atividades": 30, "pontuacao_media": 2.4},
                          "aluno_id": ana.id}]},
    )
    ultimo = (db.query(SnapshotMatific).filter_by(aluno_id=ana.id)
              .order_by(SnapshotMatific.id.desc()).first())
    assert ultimo.atividades == 30          # atualizado pelo Excel
    assert ultimo.pontuacao_media == pytest.approx(2.4)
    assert ultimo.estrelas == 900           # PRESERVADO do PDF anterior
