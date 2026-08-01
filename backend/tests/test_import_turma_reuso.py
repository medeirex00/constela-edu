"""Criação de aluno na importação de plataforma reaproveita a turma CANÔNICA.

Regressão da auditoria (fluxo Lista Piloto → Elefante/Matific): a base cria a
turma "1º Ano B"; um relatório de plataforma traz o MESMO grupo com outro
formato ("1 ANO B TARDE ANUAL"). Antes, o caminho de criação (_turma_pelo_nome)
só casava por nome EXATO e criava uma TURMA-FANTASMA paralela na sync não
supervisionada. Agora reaproveita a turma existente por tokens (série+letra) —
a mesma identidade de turma da base e do move do Matific — e só cria quando não
há correspondente inequívoco.
"""
from sqlalchemy import func, select

from app.models import Turma
from app.routers.importacoes import _turma_pelo_nome


def _conta_turmas(db, escola_id, ano) -> int:
    return db.execute(
        select(func.count()).select_from(Turma)
        .where(Turma.escola_id == escola_id, Turma.ano_letivo == ano)
    ).scalar_one()


def _nova_turma(db, escola_id, ano, nome, ano_escolar) -> Turma:
    t = Turma(escola_id=escola_id, nome=nome, ano_escolar=ano_escolar, ano_letivo=ano)
    db.add(t)
    db.flush()
    return t


def test_reusa_turma_canonica_em_vez_de_criar_fantasma(db, escola_completa):
    escola = escola_completa["escola"]
    ano = escola.ano_letivo_ativo
    base = _nova_turma(db, escola.id, ano, "1º Ano B", "1º Ano")
    antes = _conta_turmas(db, escola.id, ano)

    # Formato divergente do relatório de plataforma para o MESMO grupo.
    turma = _turma_pelo_nome(db, escola.id, ano, "1 ANO B TARDE ANUAL", [], {})

    assert turma is not None and turma.id == base.id          # reaproveitou a base
    assert _conta_turmas(db, escola.id, ano) == antes          # nenhuma turma-fantasma


def test_cria_quando_nao_ha_correspondente_inequivoco(db, escola_completa):
    escola = escola_completa["escola"]
    ano = escola.ano_letivo_ativo
    _nova_turma(db, escola.id, ano, "1º Ano B", "1º Ano")
    antes = _conta_turmas(db, escola.id, ano)

    # Turma genuinamente diferente (série + letra) → cria uma nova, sem reusar.
    # O nome é gravado NORMALIZADO ("5ºC"), não o cru do relatório.
    turma = _turma_pelo_nome(db, escola.id, ano, "5 ANO C MANHA", [], {})

    assert turma is not None and turma.nome == "5ºC"
    assert _conta_turmas(db, escola.id, ano) == antes + 1


def test_formato_sed_com_codigo_reusa_canonica_e_guarda_codigo(db, escola_completa):
    """Caso ABRAÃO (Debora Pilon): a base tem "4ºC"; o relatório traz
    "4 ANO C INTEGRAL (300303525)". Deve REUSAR a "4ºC" (não criar fantasma) e o
    código externo (SED) NÃO entra no nome — vai para Turma.codigo_externo."""
    escola = escola_completa["escola"]
    ano = escola.ano_letivo_ativo
    base = _nova_turma(db, escola.id, ano, "4ºC", "4º Ano")
    antes = _conta_turmas(db, escola.id, ano)

    turma = _turma_pelo_nome(db, escola.id, ano, "4 ANO C INTEGRAL (300303525)", [], {})

    assert turma.id == base.id                                  # reaproveitou a "4ºC"
    assert _conta_turmas(db, escola.id, ano) == antes           # nenhuma fantasma
    assert turma.nome == "4ºC"                                  # nome curto, sem código
    assert turma.codigo_externo == "300303525"                 # código guardado fora do nome


def test_cria_turma_sed_com_nome_normalizado_e_codigo(db, escola_completa):
    """Sem turma prévia, o relatório SED cria a turma já normalizada ("1ºA") com o
    código fora do nome — e o cache do lote colapsa a variante compacta ("1A")."""
    escola = escola_completa["escola"]
    ano = escola.ano_letivo_ativo
    antes = _conta_turmas(db, escola.id, ano)
    cache: dict = {}

    t1 = _turma_pelo_nome(db, escola.id, ano, "1 ANO A TARDE ANUAL (300302821)", [], cache)
    # Mesma sala em formato compacto no MESMO lote → colapsa (não cria 2ª).
    t2 = _turma_pelo_nome(db, escola.id, ano, "1A", [], cache)

    assert t1.id == t2.id
    assert t1.nome == "1ºA" and t1.codigo_externo == "300302821"
    assert _conta_turmas(db, escola.id, ano) == antes + 1
