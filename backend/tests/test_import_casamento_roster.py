"""Caso ABRAÃO (Debora Pilon): o import de Elefante/Matific VINCULA ao aluno da
Lista Piloto em vez de criar um novo — mesmo com o nome abreviado ("ABRAAO L"),
variação ortográfica ("ABRAAO LUIZ DIAS") e a turma em outro formato
("4 ANO C INTEGRAL (300303525)"). E NUNCA funde nomes parecidos de crianças
diferentes (ABRAÃO LUÍS × ABRAÃO LUCAS → ambíguo, fica para revisão).
"""
from types import SimpleNamespace

from sqlalchemy import func, select

from app.core.security import hash_senha
from app.models import Aluno, Escola, Matricula, Turma, Usuario
from app.routers.importacoes import _resolver_aluno


def _linha(nome, turma_nome, dados=None):
    return SimpleNamespace(nome=nome, aluno_id=None, criar_em_turma_id=None,
                           criar_em_turma_nome=turma_nome, numero_chamada=None,
                           dados=dados or {})


def _cenario(db):
    esc = Escola(nome="EMEF Debora Pilon", ano_letivo_ativo=2026, status="ativa")
    db.add(esc)
    db.flush()
    turma = Turma(escola_id=esc.id, nome="4ºC", ano_escolar="4º Ano",
                  ano_letivo=2026, status="ativa")
    db.add(turma)
    db.flush()

    def matricular(nome):
        a = Aluno(escola_id=esc.id, nome=nome, status="ativo", da_lista_piloto=True)
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=esc.id, aluno_id=a.id, turma_id=turma.id,
                         ano_letivo=2026))
        return a

    abraao = matricular("ABRAÃO LUÍS DIAS")
    db.commit()
    return esc, turma, abraao


def _conta_alunos(db, escola_id):
    return db.execute(select(func.count()).select_from(Aluno)
                      .where(Aluno.escola_id == escola_id)).scalar_one()


def test_elefante_abreviado_vincula_ao_aluno_da_lista_piloto(db):
    esc, turma, abraao = _cenario(db)
    antes = _conta_alunos(db, esc.id)

    # Elefante manda "ABRAAO L" na turma em formato SED → vincula, não cria.
    r = _resolver_aluno(db, esc.id, 2026,
                        _linha("ABRAAO L", "4 ANO C INTEGRAL (300303525)"),
                        [], {}, {})
    assert r is not None and r.id == abraao.id
    assert _conta_alunos(db, esc.id) == antes                 # NENHUM aluno novo


def test_matific_variante_ortografica_vincula(db):
    esc, turma, abraao = _cenario(db)
    antes = _conta_alunos(db, esc.id)

    # Matific manda "ABRAAO LUIZ DIAS" (LUIZ≈LUÍS) → variante → vincula.
    r = _resolver_aluno(db, esc.id, 2026,
                        _linha("ABRAAO LUIZ DIAS", "4 ANO C INTEGRAL"),
                        [], {}, {})
    assert r is not None and r.id == abraao.id
    assert _conta_alunos(db, esc.id) == antes


def test_ambiguo_entre_criancas_diferentes_nao_funde(db):
    esc, turma, abraao = _cenario(db)
    # Existe TAMBÉM um ABRAÃO LUCAS DIAS (outra criança) na mesma turma.
    lucas = Aluno(escola_id=esc.id, nome="ABRAÃO LUCAS DIAS", status="ativo",
                  da_lista_piloto=True)
    db.add(lucas)
    db.flush()
    db.add(Matricula(escola_id=esc.id, aluno_id=lucas.id, turma_id=turma.id,
                     ano_letivo=2026))
    db.commit()
    antes = _conta_alunos(db, esc.id)
    avisos: list[str] = []

    # "ABRAAO L" serve aos DOIS → ambíguo → NÃO cria, NÃO funde, avisa.
    r = _resolver_aluno(db, esc.id, 2026,
                        _linha("ABRAAO L", "4 ANO C INTEGRAL"), avisos, {}, {})
    assert r is None
    assert _conta_alunos(db, esc.id) == antes                 # nada criado nem fundido
    assert any("mais de um candidato" in a for a in avisos)


def test_aluno_genuinamente_novo_e_criado(db):
    esc, turma, abraao = _cenario(db)
    antes = _conta_alunos(db, esc.id)

    r = _resolver_aluno(db, esc.id, 2026,
                        _linha("BEATRIZ CAMPOS SOUZA", "4ºC"), [], {}, {})
    assert r is not None and r.nome == "BEATRIZ CAMPOS SOUZA"
    assert _conta_alunos(db, esc.id) == antes + 1             # criou o novo


def test_casar_no_roster_vincula_uuid_do_matific(db):
    """Ao casar 'ABRAAO L' (Matific, com UUID) ao aluno da Lista Piloto, o UUID é
    VINCULADO — a próxima sync casa direto por UUID (convergência), sem redepender
    do nome."""
    from app.models import IdentidadeExterna
    esc, turma, abraao = _cenario(db)

    r = _resolver_aluno(db, esc.id, 2026,
                        _linha("ABRAAO L", "4 ANO C INTEGRAL (300303525)",
                               dados={"matific_uuid": "uuid-abraao-123"}),
                        [], {}, {})
    db.flush()
    assert r.id == abraao.id
    vinc = db.execute(select(IdentidadeExterna).where(
        IdentidadeExterna.escola_id == esc.id,
        IdentidadeExterna.plataforma == "matific",
        IdentidadeExterna.id_externo == "uuid-abraao-123")).scalars().first()
    assert vinc is not None and vinc.aluno_id == abraao.id


def test_reimport_do_mesmo_relatorio_e_idempotente(db):
    esc, turma, abraao = _cenario(db)
    antes = _conta_alunos(db, esc.id)

    for _ in range(3):                        # 3 reimports do MESMO "ABRAAO L"
        _resolver_aluno(db, esc.id, 2026,
                        _linha("ABRAAO L", "4 ANO C INTEGRAL (300303525)"),
                        [], {}, {})
    assert _conta_alunos(db, esc.id) == antes                 # nunca duplica
