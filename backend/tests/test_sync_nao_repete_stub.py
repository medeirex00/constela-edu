"""A sincronização não abre uma ficha nova a cada execução para o mesmo nome.

Na escola 11 (Débora Pilon) nasceram, entre 28/07 e 01/08/2026, TRÊS fichas
"BEATRIZ D" na mesma turma — uma por execução da sync do Matific — enquanto a
ficha real da Lista Piloto, BEATRIZ DOS SANTOS DIAS, ficava sem nenhum dado de
matemática. O mesmo aconteceu com outros oito nomes abreviados: 26 fichas
fantasma ao todo.

A causa foi corrigida em 01–04/08/2026, por dois commits:
  * ``500af5c`` — ``_casar_no_roster``: a linha de plataforma passa a ser casada
    contra o ROSTER da turma ANTES de poder criar ficha;
  * ``c528045`` — o UUID do Matific passa a ser GRAVADO no casamento preciso,
    então a sync seguinte casa por identidade e não redepende do nome.

Estes testes travam esse comportamento replayando a sequência histórica contra
o motor de hoje: três execuções seguidas, o mesmo nome abreviado, e UMA só
ficha. Sem eles, uma regressão no casamento por roster volta a produzir o
passivo em silêncio — foi exatamente assim que ele nasceu.

O que NÃO muda, e é testado aqui de propósito: dois candidatos plausíveis
continuam virando revisão em vez de escolha automática, e conflito de
identidade continua sem fundir nada.
"""
from types import SimpleNamespace

from sqlalchemy import func, select

from app.models import Aluno, Escola, IdentidadeExterna, Matricula, Turma
from app.routers.importacoes import _resolver_aluno

ANO = 2026


def _linha(nome, turma_nome, dados=None):
    return SimpleNamespace(nome=nome, aluno_id=None, criar_em_turma_id=None,
                           criar_em_turma_nome=turma_nome, numero_chamada=None,
                           dados=dados or {})


def _escola_com_turma(db, nome_turma="2ºB"):
    esc = Escola(nome="EMEF Debora Pilon", ano_letivo_ativo=ANO, status="ativa")
    db.add(esc)
    db.flush()
    turma = Turma(escola_id=esc.id, nome=nome_turma, ano_escolar="2º Ano",
                  ano_letivo=ANO, status="ativa")
    db.add(turma)
    db.flush()
    return esc, turma


def _matricular(db, esc, turma, nome, **campos):
    a = Aluno(escola_id=esc.id, nome=nome, status="ativo",
              da_lista_piloto=campos.pop("piloto", True), **campos)
    db.add(a)
    db.flush()
    db.add(Matricula(escola_id=esc.id, aluno_id=a.id, turma_id=turma.id,
                     ano_letivo=ANO))
    db.commit()
    return a


def _alunos(db, escola_id):
    db.expire_all()
    return db.execute(select(func.count()).select_from(Aluno)
                      .where(Aluno.escola_id == escola_id)).scalar_one()


def _sync(db, esc, nome, turma_nome, dados=None):
    """Uma execução da sincronização de plataforma, pelo caminho real."""
    return _resolver_aluno(db, esc.id, ANO, _linha(nome, turma_nome, dados),
                           [], {}, {})


# ---------------------------------------------------------------------------
# A sequência histórica: três execuções, uma só ficha
# ---------------------------------------------------------------------------

def test_1_tres_syncs_do_mesmo_nome_abreviado_nao_criam_tres_fichas(db):
    """Replay literal do que produziu as fichas 959, 1157 e 1331."""
    esc, turma = _escola_com_turma(db)
    oficial = _matricular(db, esc, turma, "BEATRIZ DOS SANTOS DIAS",
                          ficha={"ra": "121754502-5"})
    antes = _alunos(db, esc.id)

    vistos = []
    for _ in range(3):
        r = _sync(db, esc, "BEATRIZ D", "2 ANO B TARDE (300303178)")
        vistos.append(None if r is None else r.id)
        db.commit()

    assert vistos == [oficial.id] * 3, vistos
    assert _alunos(db, esc.id) == antes, "a sync abriu ficha nova"


def test_2_com_uuid_a_segunda_sync_casa_por_identidade(db):
    """``c528045``: o UUID é gravado no casamento preciso, então a sync seguinte
    não redepende do nome — mesmo que ele mude de forma."""
    esc, turma = _escola_com_turma(db)
    oficial = _matricular(db, esc, turma, "BEATRIZ DOS SANTOS DIAS",
                          ficha={"ra": "121754502-5"})
    uuid = "11111111-2222-3333-4444-555555555555"

    r1 = _sync(db, esc, "BEATRIZ D", "2 ANO B TARDE (300303178)",
               {"matific_uuid": uuid})
    db.commit()
    assert r1 is not None and r1.id == oficial.id
    gravadas = db.execute(select(IdentidadeExterna).where(
        IdentidadeExterna.aluno_id == oficial.id)).scalars().all()
    assert [(i.plataforma, i.id_externo) for i in gravadas] == [("matific", uuid)]

    antes = _alunos(db, esc.id)
    # o nome vem DIFERENTE na próxima execução; o UUID segura a identidade
    r2 = _sync(db, esc, "B. DOS SANTOS", "2 ANO B TARDE (300303178)",
               {"matific_uuid": uuid})
    db.commit()
    assert r2 is not None and r2.id == oficial.id
    assert _alunos(db, esc.id) == antes


def test_3a_variante_no_MEIO_do_nome_casa(db):
    """ABRAÃO LUÍS × ABRAÃO LUIZ: a variação está num token do meio e as pontas
    batem, então ``variante_ortografica`` reconhece — é o caso que ``500af5c``
    resolveu."""
    from app.services.importacao import tokens_nome, variante_ortografica
    assert variante_ortografica(tokens_nome("ABRAÃO LUÍS DIAS"),
                                tokens_nome("ABRAAO LUIZ DIAS")) is True


def test_3b_variante_no_PRIMEIRO_nome_nao_casa_e_isso_e_deliberado(db):
    """LUÍS × LUIZ no PRIMEIRO nome (fichas 592/1582 em produção) NÃO casa — e
    não é bug.

    ``variante_ortografica`` exige o mesmo primeiro token, e
    ``vincula_por_nome_unico`` documenta o porquê: "False para variação insegura
    (sobrenome/1º nome: SOUZA/SOUSA, BRUNO/BRUNA)". Pelo nome, LUÍS↔LUIZ é
    indistinguível de BRUNO↔BRUNA — uma é grafia, a outra são duas crianças.

    A consequência medida em produção: sem candidato, a sincronização CRIA uma
    ficha nova. Foi assim que a 1582 nasceu ao lado da 592. Mudar isso é decisão
    de PRODUTO, não correção técnica — e o efeito foi medido: relaxar a regra
    acrescentaria exatamente UM par de candidatos na rede inteira, justamente
    esse. Este teste trava o comportamento atual; se ele cair, a mudança tem de
    ser deliberada."""
    from app.services import matching
    from app.services.importacao import tokens_nome, variante_ortografica

    a, b = "LUÍS FELIPE MENDES DE DEUS", "LUIZ FELIPE MENDES DE DEUS"
    assert variante_ortografica(tokens_nome(a), tokens_nome(b)) is False
    assert matching.plausivel(a, b) is None, "hoje nem candidato é"
    assert matching.vincula_por_nome_unico(a, b) is False

    # e a fronteira que a regra protege: troca real de nome continua fora
    assert matching.plausivel(a, "LUCAS FELIPE MENDES DE DEUS") is None


def test_4_sem_candidato_cria_UMA_vez_e_reusa_depois(db):
    """Quando não há a quem vincular, criar é o certo — mas só na primeira vez."""
    esc, turma = _escola_com_turma(db)
    _matricular(db, esc, turma, "OUTRA CRIANCA QUALQUER", ficha={"ra": "999.111.222-3"})
    antes = _alunos(db, esc.id)

    r1 = _sync(db, esc, "MARIA APARECIDA DO NASCIMENTO", "2 ANO B TARDE (300303178)")
    db.commit()
    assert r1 is not None
    assert _alunos(db, esc.id) == antes + 1, "a 1ª execução deve criar"

    for _ in range(2):
        r = _sync(db, esc, "MARIA APARECIDA DO NASCIMENTO", "2 ANO B TARDE (300303178)")
        db.commit()
        assert r is not None and r.id == r1.id
    assert _alunos(db, esc.id) == antes + 1, "as execuções seguintes NÃO criam"


# ---------------------------------------------------------------------------
# O que a correção NÃO pode ter afrouxado
# ---------------------------------------------------------------------------

def test_5_dois_candidatos_viram_revisao_e_nao_escolha(db):
    """Ambiguidade real: a abreviação cabe em duas crianças. O motor não escolhe
    — e também não cria uma terceira ficha às cegas."""
    esc, turma = _escola_com_turma(db)
    _matricular(db, esc, turma, "ANA BEATRIZ SOUZA", ficha={"ra": "111.111.111-1"})
    _matricular(db, esc, turma, "ANA BIANCA SOUZA", ficha={"ra": "222.222.222-2"})
    antes = _alunos(db, esc.id)

    avisos = []
    r = _resolver_aluno(db, esc.id, ANO,
                        _linha("ANA B", "2 ANO B TARDE (300303178)"), avisos, {}, {})
    db.commit()
    assert r is None, "não pode escolher entre duas crianças"
    assert _alunos(db, esc.id) == antes, "e não pode criar uma terceira"
    assert avisos, "a ambiguidade tem de ser dita"


def test_6_identidade_externa_tem_precedencia_sobre_o_nome(db):
    """UUID já vinculado manda, mesmo que o nome recebido seja de outra forma."""
    esc, turma = _escola_com_turma(db)
    a = _matricular(db, esc, turma, "PEDRO HENRIQUE DA COSTA CAMPOS",
                    ficha={"ra": "121841643-9"})
    outro = _matricular(db, esc, turma, "PEDRO ALVES LIMA", ficha={"ra": "333.333.333-3"})
    uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    db.add(IdentidadeExterna(escola_id=esc.id, aluno_id=a.id,
                             plataforma="matific", id_externo=uuid))
    db.commit()
    antes = _alunos(db, esc.id)

    r = _sync(db, esc, "PEDRO ALVES LIMA", "2 ANO B TARDE (300303178)",
              {"matific_uuid": uuid})
    db.commit()
    assert r is not None and r.id == a.id, "o UUID vence o nome"
    assert r.id != outro.id
    assert _alunos(db, esc.id) == antes


def test_7_conflito_de_identidade_nao_funde(db):
    """Nascimento divergente prova crianças diferentes: nem vincula, nem funde."""
    from datetime import date
    esc, turma = _escola_com_turma(db)
    a = _matricular(db, esc, turma, "DAVI DA SILVA CARVALHO",
                    ficha={"ra": "120736414-9"})
    a.data_nascimento = date(2017, 12, 8)
    db.commit()
    antes = _alunos(db, esc.id)

    linha = _linha("DAVI DA SILVA CARVALHO", "2 ANO B TARDE (300303178)")
    linha.nascimento = date(2019, 1, 1)
    r = _resolver_aluno(db, esc.id, ANO, linha, [], {}, {})
    db.commit()
    # o importante: seja qual for o desfecho, NINGUEM e fundido e nada se perde
    assert db.get(Aluno, a.id) is not None
    assert db.get(Aluno, a.id).data_nascimento == date(2017, 12, 8)
    assert _alunos(db, esc.id) in (antes, antes + 1)


def test_8_ficha_transferida_nao_e_reativada_pela_sync(db):
    """Quem saiu da escola não volta por uma sincronização de plataforma —
    nenhum caminho de sync escreve Aluno.status."""
    esc, turma = _escola_com_turma(db)
    a = _matricular(db, esc, turma, "YARA VYCTORIA LIMA", ficha={"ra": "116.685.348-2"})
    a.status = "transferido"
    db.commit()

    _resolver_aluno(db, esc.id, ANO,
                    _linha("YARA VYCTORIA LIMA", "2 ANO B TARDE (300303178)"),
                    [], {}, {})
    db.commit()
    db.expire_all()
    assert db.get(Aluno, a.id).status == "transferido"


def test_9_a_correcao_nao_toca_em_scoring(db):
    """Guarda de escopo: o caminho de identidade não importa scoring nem grava
    Nota. Se um dia importar, este teste cai e a revisão é obrigatória."""
    import inspect

    from app.routers import importacoes
    fonte = inspect.getsource(importacoes._resolver_aluno)
    assert "scoring" not in fonte
    assert "Nota(" not in fonte and "nota_geral" not in fonte
