"""Quest — "apelido único dentro da escola" vale também depois de 256 perfis (G_QUEST-5).

``gerar_apelido`` sorteava SUBSTANTIVO + ADJETIVO (16 × 16 = 256 combinações) e
conferia a unicidade só nessas 60 tentativas. Esgotadas as combinações, a reserva
acrescentava um sufixo de 10 a 99 SEM conferir nada: numa escola de 1.000 alunos com
cartão do Quest saíam 12 a 15 apelidos repetidos. O apelido vai impresso no cartão e é
a identidade da criança fora da turma (LGPD). Agora o sufixo também é conferido, até
achar um livre.

Sem migração: o índice único (escola_id, apelido), que valeria também sob
concorrência, ficou para a decisão do dono. Dados fictícios.
"""
from collections import Counter

from sqlalchemy import select

from app.models import Aluno, Escola, Matricula
from app.quest.models import QuestPerfil
from app.quest.services import perfis


def _todas_as_bases() -> list[str]:
    return [perfis._flexionar(s, a) for s in perfis._SUBSTANTIVOS for a in perfis._ADJETIVOS]


def _apelidos(db, escola_id: int) -> list[str]:
    return list(db.execute(select(QuestPerfil.apelido)
                           .where(QuestPerfil.escola_id == escola_id)).scalars())


def _criar_perfis(db, escola, turma, quantos: int, prefixo: str) -> None:
    for i in range(quantos):
        aluno = Aluno(escola_id=escola.id, nome=f"{prefixo} Ficticio {i:04d}")
        db.add(aluno)
        db.flush()
        db.add(Matricula(escola_id=escola.id, aluno_id=aluno.id, turma_id=turma.id,
                         ano_letivo=2026))
        perfis.obter_ou_criar_perfil(db, aluno)
    db.commit()


def test_escola_grande_nao_repete_apelido(db, escola_completa):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    _criar_perfis(db, escola, turma, 1000, "Aluno")
    apelidos = _apelidos(db, escola.id)
    repetidos = {a: n for a, n in Counter(apelidos).items() if n > 1}
    assert len(apelidos) == 1000
    assert not repetidos, f"{len(repetidos)} apelidos repetidos: {sorted(repetidos.items())[:4]}"


def test_combinacoes_esgotadas_o_sufixo_e_conferido(db, escola_completa, monkeypatch):
    """Todas as 256 combinações já têm dono na escola e o sorteio do sufixo sempre dá
    o mesmo número: cada perfil novo ainda sai com um apelido livre."""
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    for i, base in enumerate(_todas_as_bases()):
        aluno = Aluno(escola_id=escola.id, nome=f"Base Ficticia {i:03d}")
        db.add(aluno)
        db.flush()
        db.add(QuestPerfil(escola_id=escola.id, aluno_id=aluno.id, apelido=base,
                           codigo_amigo=f"COSMO-B{i:03d}", avatar={}, preferencias={}))
    db.commit()
    monkeypatch.setattr(perfis.secrets, "randbelow", lambda _n: 0)

    _criar_perfis(db, escola, turma, 40, "Novo")
    apelidos = _apelidos(db, escola.id)
    repetidos = {a: n for a, n in Counter(apelidos).items() if n > 1}
    assert len(apelidos) == 256 + 40
    assert not repetidos, sorted(repetidos.items())[:4]
    # Os novos levam sufixo numérico sobre uma combinação da lista fechada.
    novos = set(apelidos) - set(_todas_as_bases())
    assert len(novos) == 40
    assert all(a.rsplit(" ", 1)[0] in set(_todas_as_bases()) and a.rsplit(" ", 1)[1].isdigit()
               for a in novos)


def test_apelido_de_outra_escola_nao_conta(db, escola_completa):
    """A unicidade é por escola: a mesma combinação noutra escola continua livre."""
    escola = escola_completa["escola"]
    outra = Escola(nome="Escola Ficticia Vizinha", ano_letivo_ativo=2026)
    db.add(outra)
    db.flush()
    for i, base in enumerate(_todas_as_bases()):
        aluno = Aluno(escola_id=outra.id, nome=f"Vizinho Ficticio {i:03d}")
        db.add(aluno)
        db.flush()
        db.add(QuestPerfil(escola_id=outra.id, aluno_id=aluno.id, apelido=base,
                           codigo_amigo=f"COSMO-V{i:03d}", avatar={}, preferencias={}))
    db.commit()
    assert perfis.gerar_apelido(db, escola.id) in set(_todas_as_bases())
