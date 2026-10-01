"""A Lista Piloto OFICIAL traz as abas da Educação Infantil junto com as do
Fundamental — e elas não concorrem.

Isto não é hipótese: o arquivo real da EMEI / EMEF João Thimóteo do Rosário tem
sete abas, ``1ª FASE``, ``2ª FASE``, ``1º ANO`` … ``5º ANO``. O parser lê as sete
e entrega o rótulo fiel; quem decide quem concorre é ``services.elegibilidade``.

O que este arquivo trava é a ponta que faltava: uma linha de FASE **não reativa**
ninguém. O importador reativa quem "consta na lista atual" — e essa regra,
aplicada a uma aba de Educação Infantil, devolveria à população ativa uma
criança que alguém tinha tirado de lá, por um motivo que não dá direito a prêmio
nenhum. O caso ``transferido`` já tinha a sua trava (``test_aluno_transferido``);
``arquivado`` e ``fora_lista_piloto`` não tinham.
"""
import io
from datetime import date

import openpyxl
from sqlalchemy import select

from app.models import Aluno, Matricula, Nota, Turma
from app.services import elegibilidade

CT_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
COLUNAS = ["N.º", "RM", "RA", "Nome", "Data de Nasc.", "Responsável",
           "Endereço", "Bairro", "Telefone", "RG", "CPF", "SUS",
           "SEXO", "RAÇA COR", "BOLSA FAMÍLIA"]
ANO = 2026
API = "/api/v1"


def _linha(nome, *, numero=None, ra="", nasc=None):
    return [numero, "", ra, nome, nasc, "MAE", "RUA X, 1", "BAIRRO",
            "", "", "", "", "F", "PARDA", "NÃO"]


def _planilha(*turmas) -> bytes:
    """A mesma forma do arquivo da secretaria: uma aba por turma, cabeçalho na
    linha 6, e o nome da turma na célula "Ano:"."""
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
        f"{API}/escolas/{escola_id}/importacoes/matriculas/confirmar",
        files={"arquivo": ("Lista.xlsx", conteudo, CT_XLSX)})
    assert r.status_code == 200, r.text
    return r.json()


def _por_nome(db, escola_id, nome) -> Aluno:
    db.expire_all()
    achados = db.execute(select(Aluno).where(
        Aluno.escola_id == escola_id, Aluno.nome == nome)).scalars().all()
    assert len(achados) == 1, f"esperava 1 ficha de {nome!r}, achei {len(achados)}"
    return achados[0]


def _turma_de(db, aluno_id):
    m = db.execute(select(Matricula).where(Matricula.aluno_id == aluno_id,
                                           Matricula.ano_letivo == ANO)
                   ).scalars().first()
    return db.get(Turma, m.turma_id) if m else None


# A planilha da João Thimóteo em miniatura: duas Fases e dois anos.
LISTA = _planilha(
    ("1ª FASE", [_linha("BIA DA EDUCACAO INFANTIL", numero=1, ra="111.100.011-0",
                        nasc=date(2021, 2, 1))]),
    ("2ª FASE", [_linha("CAIO DA EDUCACAO INFANTIL", numero=1, ra="111.100.012-0",
                        nasc=date(2020, 5, 2))]),
    ("1º Ano", [_linha("DORA DO FUNDAMENTAL", numero=1, ra="111.100.013-0",
                       nasc=date(2019, 7, 3))]),
    ("5º Ano", [_linha("ELIAS DO FUNDAMENTAL", numero=1, ra="111.100.014-0",
                       nasc=date(2015, 9, 4))]),
)


# ---------------------------------------------------------------------------
# A leitura: as sete abas entram, com o rótulo fiel
# ---------------------------------------------------------------------------
def test_as_abas_de_fase_sao_lidas_e_rotuladas_como_fase(cliente, db,
                                                         escola_completa):
    escola_id = escola_completa["escola"].id
    _confirmar(cliente, escola_id, LISTA)

    for nome, rotulo, concorre in (("BIA DA EDUCACAO INFANTIL", "1ª FASE", False),
                                   ("CAIO DA EDUCACAO INFANTIL", "2ª FASE", False),
                                   ("DORA DO FUNDAMENTAL", "1º Ano", True),
                                   ("ELIAS DO FUNDAMENTAL", "5º Ano", True)):
        a = _por_nome(db, escola_id, nome)
        t = _turma_de(db, a.id)
        assert t is not None, f"{nome} ficou sem turma"
        assert elegibilidade.participa_de_premiacao(t.ano_escolar) is concorre, (
            f"{nome}: turma {t.nome!r} ano_escolar {t.ano_escolar!r}")


def test_fase_nao_entra_no_ranking_mas_continua_cadastrada(cliente, db,
                                                           escola_completa):
    escola_id = escola_completa["escola"].id
    _confirmar(cliente, escola_id, LISTA)
    bia = _por_nome(db, escola_id, "BIA DA EDUCACAO INFANTIL")
    dora = _por_nome(db, escola_id, "DORA DO FUNDAMENTAL")

    r = cliente.get(f"{API}/escolas/{escola_id}/ranking")
    assert r.status_code == 200, r.text
    ids = {x["aluno_id"] for x in r.json()}
    assert bia.id not in ids, "a Fase não concorre"
    assert dora.id in ids

    assert bia.status == "ativo", "continua ATIVA no cadastro — é elegibilidade"
    assert _turma_de(db, bia.id) is not None, "continua MATRICULADA"


# ---------------------------------------------------------------------------
# A ponta que faltava: linha de FASE não reativa
# ---------------------------------------------------------------------------
def _acao(cliente, escola_id, acao, ids):
    return cliente.post(f"{API}/escolas/{escola_id}/alunos/acoes",
                        json={"aluno_ids": ids, "acao": acao})


def test_linha_de_fase_nao_reativa_aluno_arquivado(cliente, db, escola_completa):
    """O caso que não tinha trava: ``arquivado`` era reativado por "consta na
    lista", e uma aba de Fase bastava para isso."""
    escola_id = escola_completa["escola"].id
    _confirmar(cliente, escola_id, LISTA)
    bia = _por_nome(db, escola_id, "BIA DA EDUCACAO INFANTIL")
    assert _acao(cliente, escola_id, "arquivar", [bia.id]).status_code == 200
    db.expire_all()
    assert _por_nome(db, escola_id, "BIA DA EDUCACAO INFANTIL").status == "arquivado"

    resultado = _confirmar(cliente, escola_id, LISTA)

    bia = _por_nome(db, escola_id, "BIA DA EDUCACAO INFANTIL")
    assert bia.status == "arquivado", "a linha de Fase NÃO pode reativar"
    assert any("não participam das premiações" in a or "Educação Infantil" in a
               for a in resultado.get("avisos", [])), (
        f"a importação tem de AVISAR; avisos={resultado.get('avisos')}")


def test_linha_de_fase_nao_reativa_fora_da_lista_piloto(cliente, db,
                                                        escola_completa):
    escola_id = escola_completa["escola"].id
    _confirmar(cliente, escola_id, LISTA)
    caio = _por_nome(db, escola_id, "CAIO DA EDUCACAO INFANTIL")
    caio.status = "fora_lista_piloto"
    db.commit()

    _confirmar(cliente, escola_id, LISTA)

    assert _por_nome(db, escola_id, "CAIO DA EDUCACAO INFANTIL").status == \
        "fora_lista_piloto"


def test_linha_do_FUNDAMENTAL_continua_reativando(cliente, db, escola_completa):
    """A regressão a evitar: a trava nova não pode travar o 1º–5º ano, onde
    reativar por "consta na lista" é o comportamento certo e antigo."""
    escola_id = escola_completa["escola"].id
    _confirmar(cliente, escola_id, LISTA)
    dora = _por_nome(db, escola_id, "DORA DO FUNDAMENTAL")
    assert _acao(cliente, escola_id, "arquivar", [dora.id]).status_code == 200
    db.expire_all()

    _confirmar(cliente, escola_id, LISTA)

    assert _por_nome(db, escola_id, "DORA DO FUNDAMENTAL").status == "ativo"


def test_fase_nao_reativa_mas_a_linha_continua_sendo_aplicada(cliente, db,
                                                              escola_completa):
    """Só o status fica de fora: nome, ficha e turma continuam atualizando."""
    escola_id = escola_completa["escola"].id
    _confirmar(cliente, escola_id, LISTA)
    bia = _por_nome(db, escola_id, "BIA DA EDUCACAO INFANTIL")
    bia.status = "arquivado"
    bia.ficha = {}
    db.commit()

    _confirmar(cliente, escola_id, LISTA)

    bia = _por_nome(db, escola_id, "BIA DA EDUCACAO INFANTIL")
    assert bia.status == "arquivado"
    assert (bia.ficha or {}).get("ra"), "a ficha (RA) continua sendo aplicada"
    assert _turma_de(db, bia.id).ano_escolar == "1ª FASE"


# ---------------------------------------------------------------------------
# Idempotência: a mesma lista, duas vezes, dá o mesmo estado
# ---------------------------------------------------------------------------
def test_importar_duas_vezes_nao_duplica_nada(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    _confirmar(cliente, escola_id, LISTA)
    db.expire_all()

    def retrato():
        alunos = db.execute(select(Aluno).where(Aluno.escola_id == escola_id)
                            ).scalars().all()
        turmas = db.execute(select(Turma).where(Turma.escola_id == escola_id)
                            ).scalars().all()
        mats = db.execute(select(Matricula).where(Matricula.escola_id == escola_id)
                          ).scalars().all()
        return (sorted((a.nome, a.status) for a in alunos),
                sorted((t.nome, t.ano_escolar) for t in turmas),
                sorted((m.aluno_id, m.turma_id, m.ano_letivo) for m in mats))

    antes = retrato()
    _confirmar(cliente, escola_id, LISTA)
    db.expire_all()
    depois = retrato()

    assert antes[0] == depois[0], "alunos mudaram na 2ª importação"
    assert antes[1] == depois[1], "turmas mudaram (duplicata de turma?)"
    assert antes[2] == depois[2], "matrículas mudaram"


def test_a_fase_nao_ganha_posicao_no_ranking_nem_depois_de_recalcular(
        cliente, db, escola_completa):
    from app.services import scoring

    escola_id = escola_completa["escola"].id
    _confirmar(cliente, escola_id, LISTA)
    scoring.recalcular_escola(db, escola_id, commit=True)
    db.expire_all()

    bia = _por_nome(db, escola_id, "BIA DA EDUCACAO INFANTIL")
    nota = db.execute(select(Nota).where(Nota.aluno_id == bia.id)).scalars().first()
    assert nota is None or nota.posicao is None, (
        "a Fase não pode receber posição carimbada")
