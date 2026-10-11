"""Identidade AUTOMÁTICA nas linhas de PLATAFORMA (Elefante/Matific) — menos
revisão manual, sem falso positivo (implantação na rede, 2026-10-07).

O que ``identidade_aluno.decidir`` passou a resolver sozinho, SÓ no caminho de
plataforma (a Lista Piloto e o cadastro manual não mudam):

  (A) variação de grafia SEGURA de candidato único — o mesmo critério já aprovado
      para a Lista Piloto (``matching.vincula_por_nome_unico``), com 1º nome e
      último sobrenome idênticos ("RICADO"/"RICARDO") — e, na plataforma, em UM
      nome do meio só (dois nomes do meio diferentes seguem em revisão).
      Sobrenome ou 1º nome diferentes (SOUZA/SOUSA, BRUNO/BRUNA) seguem em revisão,
      e nome IDÊNTICO em outra sala vence o nome só parecido da sala (revisão);
  (B) ficha OFICIAL da Lista Piloto × duplicata dela na mesma sala (o stub de nome
      abreviado criado pelo Matific ao lado da oficial): associa à oficial só com
      TODAS as condições — um único candidato da Lista Piloto e ativo; a linha
      casaria com ele sozinho; cada outro candidato fora da Lista Piloto, forma
      curta do nome oficial, sem identificador divergente e sem conta nesta
      plataforma; e, se a linha não é o nome idêntico da oficial, nenhum nome
      idêntico em outra sala. Qualquer outra coisa continua revisão;
  (C) o sufixo de TURMA no nome RECEBIDO ("2B", "2ºB", "PINTO2B" — o professor
      digita a turma junto no Elefante) não participa do casamento; número puro
      ("… SOUZA 2") fica, e o nome gravado continua o recebido.

Os nomes são FICTÍCIOS: reproduzem os padrões reais da escola 1 (oficial + stub
abreviado do Matific + nome do Elefante com typo no meio; partícula "DE" omitida;
sufixo de turma) sem usar nome de criança de verdade.
"""
import json
from datetime import date

import pytest
from sqlalchemy import func, select

from app.models import (
    Aluno,
    IdentidadeExterna,
    LogAuditoria,
    Matricula,
    RevisaoIdentidade,
    SnapshotElefante,
    Turma,
)
from app.routers import importacoes as imp
from app.schemas.importacao import ImportacaoConfirm, LinhaConfirmacao
from app.services import identidade_aluno as ida
from app.services import importacao as svc
from app.services import matching
from app.sync import orchestrator
from app.sync.interfaces import ArquivoObtido, Contexto

ANO = 2026
SALA_2B = "2 ANO B TARDE ANUAL"                # como o Elefante escreve a turma
SALA_2B_MATIFIC = "2 ANO B TARDE (300399001)"  # como o Matific escreve (com código SED)


# --- montagem ------------------------------------------------------------------

def _turma(db, escola, nome, ano_escolar, codigo=None):
    t = Turma(escola_id=escola.id, nome=nome, ano_escolar=ano_escolar, ano_letivo=ANO,
              codigo_externo=codigo)
    db.add(t)
    db.flush()
    return t


def _aluno(db, escola, turma, nome, *, lp=True, status="ativo", chamada=None,
           nascimento=None, ra=None):
    a = Aluno(escola_id=escola.id, nome=nome, status=status, numero_chamada=chamada,
              da_lista_piloto=lp, data_nascimento=nascimento,
              ficha={"ra": ra} if ra else {})
    db.add(a)
    db.flush()
    if turma is not None:
        db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=turma.id,
                         ano_letivo=ANO))
        db.flush()
    return a


def _conta(db, escola, aluno, plataforma, id_externo, status="efetiva"):
    db.add(IdentidadeExterna(escola_id=escola.id, aluno_id=aluno.id, plataforma=plataforma,
                             id_externo=id_externo, status=status))
    db.flush()


def _decidir(db, escola, nome, turma_nome, *, plataforma="elefante", id_externo="9999"):
    ctx = ida.carregar_contexto(db, escola.id)
    campo = ida.CAMPO_ID_EXTERNO[plataforma]
    return ida.decidir(ctx, ida.linha_de_dados(
        nome, {campo: id_externo}, plataforma=plataforma, turma_nome=turma_nome))


def _n_alunos(db, escola):
    return db.execute(select(func.count()).select_from(Aluno)
                      .where(Aluno.escola_id == escola.id)).scalar_one()


def _pendentes(db, escola):
    return db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == escola.id,
        RevisaoIdentidade.status == "pendente").order_by(RevisaoIdentidade.id)).scalars().all()


def _dono(db, escola, plataforma, id_externo):
    return db.execute(select(IdentidadeExterna.aluno_id).where(
        IdentidadeExterna.escola_id == escola.id,
        IdentidadeExterna.plataforma == plataforma,
        IdentidadeExterna.id_externo == id_externo)).scalar_one_or_none()


def _elefante(nome, turma, sid, livros=7):
    dados = {"turma_relatorio": turma, "livros_unicos": livros, "tempo_leitura_min": 40,
             "questoes_tentativas": 5, "questoes_acertos": 4,
             "elefante_student_id": str(sid)}
    return LinhaConfirmacao(nome=nome, dados=dados, criar_em_turma_nome=turma)


def _matific(nome, turma, uuid, estrelas=120, atividades=30):
    dados = {"turma_relatorio": turma, "estrelas": estrelas, "atividades": atividades,
             "pontuacao_media": round(estrelas / atividades, 2), "matific_uuid": uuid}
    return LinhaConfirmacao(nome=nome, dados=dados, criar_em_turma_nome=turma)


def _confirmar(db, escola, admin, plataforma, linhas, **kw):
    conf = ImportacaoConfirm(plataforma=plataforma, formato="resumo", tipo="texto",
                             linhas=linhas, recalcular=False, **kw)
    return imp.confirmar(dados=conf, escola_id=escola.id, usuario=admin, db=db)


def _previa(db, escola, plataforma, linhas):
    brutas = [svc.LinhaImportacao(numero=i, nome=l.nome, dados=dict(l.dados))
              for i, l in enumerate(linhas, start=1)]
    svc.casar_nomes(db, escola.id, brutas, plataforma=plataforma)
    return [l.correspondencia for l in brutas]


@pytest.fixture()
def rede(db, escola_completa):
    """Escola com 2ºB (a sala dos casos) e 2ºC (outra sala da mesma série)."""
    esc = escola_completa["escola"]
    b = _turma(db, esc, "2º Ano B", "2º Ano", codigo="300399001")
    c = _turma(db, esc, "2º Ano C", "2º Ano", codigo="300399002")
    db.commit()
    return {"escola": esc, "admin": escola_completa["admin"], "b": b, "c": c}


# --- 1. nome igual e grafia ------------------------------------------------------

def test_nome_exatamente_igual_associa(db, rede):
    esc = rede["escola"]
    beatriz = _aluno(db, esc, rede["b"], "BEATRIZ HELENA CAMPOS")
    db.commit()
    d = _decidir(db, esc, "BEATRIZ HELENA CAMPOS", SALA_2B)
    assert (d.acao, d.aluno_id, d.via) == (ida.ASSOCIAR, beatriz.id, "exato")


@pytest.mark.parametrize("recebido", [
    "LIVIA MARCAL AVILA",
    "lívia marçal ávila",
    "  LÍVIA   MARÇAL  ÁVILA ",
    "LÍVIA MARÇAL ÁVILA.",
    "LÍVIA* MARÇAL ÁVILA",
])
def test_igual_com_acento_caixa_espaco_e_pontuacao_diferentes_associa(db, rede, recebido):
    esc = rede["escola"]
    livia = _aluno(db, esc, rede["b"], "Lívia Marçal Ávila")
    db.commit()
    d = _decidir(db, esc, recebido, SALA_2B)
    assert (d.acao, d.aluno_id, d.via) == (ida.ASSOCIAR, livia.id, "exato")


@pytest.mark.parametrize("recebido,via", [
    ("ANA C", "abreviacao"),                     # abreviado (Matific)
    ("ANA CLARA M PINTO", "abreviacao"),         # parcialmente abreviado
    ("ANA CLARA MOREIRA P", "abreviacao"),       # parcialmente abreviado (fim)
    ("ANA CLARA PINTO", "parcial"),              # meio omitido, pontas iguais
])
def test_nome_abreviado_ou_parcial_com_candidato_unico_associa(db, rede, recebido, via):
    esc = rede["escola"]
    ana = _aluno(db, esc, rede["b"], "ANA CLARA MOREIRA PINTO")
    _aluno(db, esc, rede["b"], "BIANCA SOARES TEIXEIRA")      # colega sem relação
    db.commit()
    d = _decidir(db, esc, recebido, SALA_2B_MATIFIC, plataforma="matific", id_externo="u-ana")
    assert (d.acao, d.aluno_id, d.via) == (ida.ASSOCIAR, ana.id, via)


# --- 2. candidatos na turma × na escola -----------------------------------------

def test_dois_candidatos_da_lista_piloto_na_mesma_turma_vao_para_revisao(db, rede):
    """'MARIA L' com duas Marias L… oficiais: ambiguidade REAL — ninguém é sombra."""
    esc = rede["escola"]
    m1 = _aluno(db, esc, rede["b"], "MARIA LUIZA ROCHA")
    m2 = _aluno(db, esc, rede["b"], "MARIA LETICIA PRADO")
    db.commit()
    d = _decidir(db, esc, "MARIA L", SALA_2B_MATIFIC, plataforma="matific", id_externo="u-m")
    assert (d.acao, d.motivo) == (ida.REVISAR, "candidatos_multiplos")
    assert set(d.candidatos) == {m1.id, m2.id}


def test_dois_candidatos_na_escola_mas_um_so_na_turma_associa_o_da_turma(db, rede):
    esc = rede["escola"]
    da_turma = _aluno(db, esc, rede["b"], "JULIA COSTA RAMOS")
    _aluno(db, esc, rede["c"], "JULIA CARDOSO NUNES")         # outra sala, mesma série
    db.commit()
    d = _decidir(db, esc, "JULIA C", SALA_2B_MATIFIC, plataforma="matific", id_externo="u-j")
    assert (d.acao, d.aluno_id) == (ida.ASSOCIAR, da_turma.id)


def test_homonimo_exato_em_outra_turma_nao_atrapalha_o_da_turma(db, rede):
    esc = rede["escola"]
    da_turma = _aluno(db, esc, rede["b"], "PEDRO LUCAS FARIAS")
    _aluno(db, esc, rede["c"], "PEDRO LUCAS FARIAS")
    db.commit()
    d = _decidir(db, esc, "PEDRO LUCAS FARIAS", SALA_2B)
    assert (d.acao, d.aluno_id, d.via) == (ida.ASSOCIAR, da_turma.id, "exato")


# --- 3. sem turma: comportamento de sempre ------------------------------------------

def test_sem_turma_nome_identico_unico_na_escola_associa(db, rede):
    esc = rede["escola"]
    beatriz = _aluno(db, esc, rede["b"], "BEATRIZ HELENA CAMPOS")
    db.commit()
    d = _decidir(db, esc, "BEATRIZ HELENA CAMPOS", "")
    assert (d.acao, d.aluno_id, d.via) == (ida.ASSOCIAR, beatriz.id, "exato")


def test_sem_turma_nome_abreviado_vai_para_revisao(db, rede):
    esc = rede["escola"]
    beatriz = _aluno(db, esc, rede["b"], "BEATRIZ HELENA CAMPOS")
    db.commit()
    d = _decidir(db, esc, "BEATRIZ H", "", plataforma="matific", id_externo="u-b")
    assert (d.acao, d.motivo, d.aluno_id) == (ida.REVISAR, "correspondencia_insegura",
                                              beatriz.id)


def test_sem_turma_dois_homonimos_na_escola_vao_para_revisao(db, rede):
    esc = rede["escola"]
    _aluno(db, esc, rede["b"], "PEDRO LUCAS FARIAS")
    _aluno(db, esc, rede["c"], "PEDRO LUCAS FARIAS")
    db.commit()
    d = _decidir(db, esc, "PEDRO LUCAS FARIAS", "")
    assert (d.acao, d.motivo) == (ida.REVISAR, "candidatos_multiplos")


# --- 4. nomes realmente ambíguos ---------------------------------------------------

def test_homonimos_exatos_na_turma_vao_para_revisao(db, rede):
    esc = rede["escola"]
    a1 = _aluno(db, esc, rede["b"], "LUCAS SILVA")
    a2 = _aluno(db, esc, rede["b"], "LUCAS SILVA")
    db.commit()
    d = _decidir(db, esc, "LUCAS SILVA", SALA_2B)
    assert d.acao == ida.REVISAR and set(d.candidatos) == {a1.id, a2.id}


def test_abreviado_que_serve_a_duas_fichas_fora_da_lista_vai_para_revisao(db, rede):
    """Sem ficha da Lista Piloto entre os candidatos não há 'oficial' para desempatar."""
    esc = rede["escola"]
    _aluno(db, esc, rede["b"], "PEDRO HENRIQUE ALVES", lp=False)
    _aluno(db, esc, rede["b"], "PEDRO HUGO LIMA", lp=False)
    db.commit()
    d = _decidir(db, esc, "PEDRO H", SALA_2B_MATIFIC, plataforma="matific", id_externo="u-p")
    assert (d.acao, d.motivo) == (ida.REVISAR, "candidatos_multiplos")


# --- 5. regressões dos padrões reais (nomes fictícios) ------------------------------

@pytest.fixture()
def oficial_e_stub(db, rede):
    """(i) O padrão da 2ºB da escola 1: a ficha OFICIAL da Lista Piloto e, na mesma
    sala, o stub que a sincronização do Matific criou com o nome abreviado — o stub
    tem a conta Matific, a oficial ainda não tem conta nenhuma."""
    esc = rede["escola"]
    oficial = _aluno(db, esc, rede["b"], "LARISSA VITORIA MENEZES COSTA", chamada=23,
                     ra="120.555.111-0")
    stub = _aluno(db, esc, rede["b"], "LARISSA V", lp=False)
    _conta(db, esc, stub, "matific", "u-stub-larissa")
    _aluno(db, esc, rede["b"], "BIANCA SOARES TEIXEIRA")
    db.commit()
    return {**rede, "oficial": oficial, "stub": stub}


def test_i_oficial_mais_stub_abreviado_e_typo_no_meio_vai_para_a_oficial(db, oficial_e_stub):
    c = oficial_e_stub
    esc, oficial, stub = c["escola"], c["oficial"], c["stub"]
    d = _decidir(db, esc, "LARISSA VITORIA MENEZEZ COSTA", SALA_2B, id_externo="4400001")
    assert (d.acao, d.aluno_id, d.via) == (ida.ASSOCIAR, oficial.id, "lista_piloto_unica")
    assert d.candidatos == (oficial.id,)
    assert d.preteridos == (stub.id,)        # rastro de quem ficou de fora do desempate

    # Ponta a ponta: prévia == confirmação, dado na oficial, conta Elefante gravada
    # nela, nada criado, nada na fila — e o stub fica intacto, com a conta dele.
    linha = _elefante("LARISSA VITORIA MENEZEZ COSTA", SALA_2B, 4400001)
    [corr] = _previa(db, esc, "elefante", [linha])
    assert (corr["status"], corr["aluno_id"], corr["via"]) == ("vinculado", oficial.id,
                                                              "lista_piloto_unica")
    antes = _n_alunos(db, esc)
    r = _confirmar(db, esc, c["admin"], "elefante", [linha])
    assert (r.qtd_alunos, r.qtd_revisoes) == (1, 0)
    assert _n_alunos(db, esc) == antes and _pendentes(db, esc) == []
    assert _dono(db, esc, "elefante", "4400001") == oficial.id
    assert _dono(db, esc, "matific", "u-stub-larissa") == stub.id
    assert db.execute(select(SnapshotElefante).where(
        SnapshotElefante.aluno_id == oficial.id)).scalars().first() is not None
    assert db.get(Aluno, stub.id).status == "ativo"           # nada fundido
    # Rastro auditável do desempate.
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "aluno.vinculado_auto",
        LogAuditoria.entidade_id == oficial.id)).scalars().one()
    assert log.detalhes["correspondencia"] == "lista_piloto_unica"


def test_i_a_sincronizacao_do_elefante_associa_a_oficial(db, oficial_e_stub, monkeypatch):
    """O mesmo caso pelo orquestrador real da sincronização (o caminho de produção)."""
    c = oficial_e_stub
    esc, oficial = c["escola"], c["oficial"]
    monkeypatch.setattr(orchestrator.imp, "_guardar_temporario", lambda *a, **k: None)
    payload = {"courseSchoolDescriptors": {"courseName": SALA_2B},
               "students": [{"studentId": 4400001,
                             "studentName": "LARISSA VITORIA MENEZEZ COSTA",
                             "totalBooksRead": 9}]}
    antes = _n_alunos(db, esc)
    orchestrator.aplicar_arquivo(
        db, esc, ArquivoObtido(conteudo=json.dumps(payload).encode("utf-8"),
                               nome_arquivo="e.json", plataforma="elefante",
                               content_type=orchestrator.CT_ELEFANTE_API,
                               formato_hint="resumo"),
        usuario_id=None, recalcular=False,
        contexto=Contexto(escola_id=esc.id, execucao_id=None, log=lambda *a: None))
    db.expire_all()
    assert _n_alunos(db, esc) == antes and _pendentes(db, esc) == []
    assert _dono(db, esc, "elefante", "4400001") == oficial.id


def test_ii_particula_omitida_mais_stub_abreviado_vai_para_a_oficial(db, rede):
    """(ii) Oficial com "DE" + stub abreviado do Matific + nome sem a partícula."""
    esc = rede["escola"]
    oficial = _aluno(db, esc, rede["b"], "GUSTAVO ALMEIDA DE FREITAS")
    stub = _aluno(db, esc, rede["b"], "GUSTAVO A", lp=False)
    _conta(db, esc, stub, "matific", "u-stub-gustavo")
    db.commit()
    d = _decidir(db, esc, "GUSTAVO ALMEIDA FREITAS", SALA_2B, id_externo="4400002")
    assert (d.acao, d.aluno_id, d.via) == (ida.ASSOCIAR, oficial.id, "lista_piloto_unica")


def test_ii_duas_sombras_da_mesma_oficial_ainda_vao_para_a_oficial(db, rede):
    """Dois stubs fora da lista ("GUSTAVO A", "GUSTAVO ALM"), os dois formas curtas
    da MESMA oficial e sem conta nesta plataforma."""
    esc = rede["escola"]
    oficial = _aluno(db, esc, rede["b"], "GUSTAVO ALMEIDA DE FREITAS")
    s1 = _aluno(db, esc, rede["b"], "GUSTAVO A", lp=False)
    s2 = _aluno(db, esc, rede["b"], "GUSTAVO ALM", lp=False)
    db.commit()
    d = _decidir(db, esc, "GUSTAVO ALMEIDA FREITAS", SALA_2B, id_externo="4400003")
    assert (d.acao, d.aluno_id, d.via) == (ida.ASSOCIAR, oficial.id, "lista_piloto_unica")
    assert {s1.id, s2.id}.isdisjoint(d.candidatos)
    assert set(d.preteridos) == {s1.id, s2.id}


def test_ii_duplicata_de_nome_identico_fora_da_lista_vai_para_a_oficial(db, rede):
    """Padrão real da escola 1 (2ºA): a oficial "… DA SILVA*" da Lista Piloto, uma
    ficha antiga do Elefante com o MESMO nome (sem o asterisco, fora da lista, sem
    conta) e o stub abreviado do Matific. Nome idêntico em DUAS fichas não decide
    no passo 3a; o desempate entrega à oficial."""
    esc = rede["escola"]
    oficial = _aluno(db, esc, rede["b"], "CECILIA MOURA DA SILVA*", chamada=14,
                     ra="120.555.222-0")
    _aluno(db, esc, rede["b"], "CECILIA MOURA DA SILVA", lp=False)
    stub = _aluno(db, esc, rede["b"], "CECILIA M", lp=False)
    _conta(db, esc, stub, "matific", "u-stub-cecilia")
    db.commit()
    d = _decidir(db, esc, "CECILIA MOURA DA SILVA", SALA_2B, id_externo="4400004")
    assert (d.acao, d.aluno_id, d.via) == (ida.ASSOCIAR, oficial.id, "lista_piloto_unica")


def test_ii_ficha_fora_da_lista_com_nome_parcial_nao_e_sombra(db, rede):
    """'GUSTAVO ALMEIDA' (fora da lista) perdeu o último sobrenome: não é forma
    curta segura da oficial — pode ser outra criança. Revisão."""
    esc = rede["escola"]
    _aluno(db, esc, rede["b"], "GUSTAVO ALMEIDA DE FREITAS")
    _aluno(db, esc, rede["b"], "GUSTAVO ALMEIDA", lp=False)
    db.commit()
    d = _decidir(db, esc, "GUSTAVO ALMEIDA FREITAS", SALA_2B, id_externo="4400003")
    assert (d.acao, d.motivo) == (ida.REVISAR, "candidatos_multiplos")


def test_iii_typo_num_nome_do_meio_com_candidato_unico_associa(db, rede):
    esc = rede["escola"]
    rafaela = _aluno(db, esc, rede["b"], "RAFAELA CRISTINA NOGUEIRA LOPES")
    db.commit()
    d = _decidir(db, esc, "RAFAELA CRISTIANA NOGUEIRA LOPES", SALA_2B)
    assert (d.acao, d.aluno_id) == (ida.ASSOCIAR, rafaela.id)
    assert d.via in ("variante", "typo")


@pytest.mark.parametrize("recebido,associa", [
    ("NATALIA HELENA BRITTO SOUSA RIBAS", True),      # UM nome do meio diferente
    ("NATALIA HELENA BRITTO SOUZA RIBAS", False),     # DOIS nomes do meio diferentes
])
def test_iii_grafia_vincula_so_com_um_nome_do_meio_diferente(db, rede, recebido, associa):
    """Fronteira do vínculo por grafia na plataforma: o motor aceita até DOIS
    tokens do meio diferentes (``variante_ortografica``); aqui só UM associa —
    com dois, a revisão de antes (candidato único, "correspondencia_insegura")."""
    esc = rede["escola"]
    natalia = _aluno(db, esc, rede["b"], "NATALIA HELENA BRITO SOUSA RIBAS")
    db.commit()
    assert matching.vincula_por_nome_unico(recebido, natalia.nome)   # o motor aceitaria
    d = _decidir(db, esc, recebido, SALA_2B)
    if associa:
        assert (d.acao, d.aluno_id) == (ida.ASSOCIAR, natalia.id)
    else:
        assert (d.acao, d.motivo, d.candidatos) == (ida.REVISAR, "correspondencia_insegura",
                                                    (natalia.id,))


@pytest.mark.parametrize("recebido,associa", [
    ("NATALIA HELENA BRITTO SOUSA RIBAS", True),
    ("NATALIA HELENA BRITTO SOUZA RIBAS", False),
])
def test_desempate_tambem_exige_grafia_em_um_nome_do_meio_so(db, rede, recebido, associa):
    """O desempate usa o MESMO critério de "casaria com a oficial sozinha"."""
    esc = rede["escola"]
    oficial = _aluno(db, esc, rede["b"], "NATALIA HELENA BRITO SOUSA RIBAS")
    stub = _aluno(db, esc, rede["b"], "NATALIA H", lp=False)
    _conta(db, esc, stub, "matific", "u-stub-natalia")
    db.commit()
    d = _decidir(db, esc, recebido, SALA_2B)
    if associa:
        assert (d.acao, d.aluno_id, d.via) == (ida.ASSOCIAR, oficial.id, "lista_piloto_unica")
    else:
        assert (d.acao, d.motivo) == (ida.REVISAR, "candidatos_multiplos")
        assert set(d.candidatos) == {oficial.id, stub.id}


# --- nome IDÊNTICO em outra sala vence o nome só parecido desta -----------------------

def test_grafia_na_sala_nao_vence_nome_identico_em_outra_sala(db, rede):
    """A sala da plataforma pode estar errada (é o que mais aparece na fila real).
    'ISADORA ALICE …' chega como 2ºB; a 2ºB só tem 'ISADORA ALINE …' (grafia de um
    nome do meio), e a 2ºC tem a 'ISADORA ALICE …' de nome IDÊNTICO — que pode ser
    a dona do dado. Antes da mudança: revisão; agora também — com as duas fichas."""
    esc = rede["escola"]
    identica = _aluno(db, esc, rede["c"], "ISADORA ALICE VIANA FROTA")
    parecida = _aluno(db, esc, rede["b"], "ISADORA ALINE VIANA FROTA")
    db.commit()
    assert matching.vincula_por_nome_unico("ISADORA ALICE VIANA FROTA", parecida.nome)
    d = _decidir(db, esc, "ISADORA ALICE VIANA FROTA", SALA_2B)
    assert (d.acao, d.motivo, d.aluno_id) == (ida.REVISAR, "homonimo_em_outra_sala",
                                              identica.id)
    assert set(d.candidatos) == {identica.id, parecida.id}


def test_homonimo_em_outra_sala_com_identificador_divergente_nao_trava_a_grafia(db, rede):
    """O homônimo de fora só trava quando PODE ser a dona: nascimento divergente do
    da linha prova que é outra criança (o mesmo filtro do passo 4)."""
    esc = rede["escola"]
    _aluno(db, esc, rede["c"], "ISADORA ALICE VIANA FROTA", nascimento=date(2017, 3, 3))
    parecida = _aluno(db, esc, rede["b"], "ISADORA ALINE VIANA FROTA")
    db.commit()
    ctx = ida.carregar_contexto(db, esc.id)
    d = ida.decidir(ctx, ida.linha_de_dados(
        "ISADORA ALICE VIANA FROTA",
        {"elefante_student_id": "9999", "data_nascimento": "2019-05-10"},
        plataforma="elefante", turma_nome=SALA_2B))
    assert (d.acao, d.aluno_id) == (ida.ASSOCIAR, parecida.id)


@pytest.mark.parametrize("oficial_nome,sombra_nome,fora_nome,recebido", [
    # oficial por grafia de um nome do meio
    ("ISADORA ALINE VIANA FROTA", "ISADORA A", "ISADORA ALICE VIANA FROTA",
     "ISADORA ALICE VIANA FROTA"),
    # oficial por subconjunto (partícula omitida)
    ("OTAVIANO BRAGA DE MELO", "OTAVIANO B", "OTAVIANO BRAGA MELO", "OTAVIANO BRAGA MELO"),
])
def test_desempate_nao_vence_nome_identico_em_outra_sala(db, rede, oficial_nome, sombra_nome,
                                                         fora_nome, recebido):
    esc = rede["escola"]
    identica = _aluno(db, esc, rede["c"], fora_nome)
    oficial = _aluno(db, esc, rede["b"], oficial_nome)
    stub = _aluno(db, esc, rede["b"], sombra_nome, lp=False)
    _conta(db, esc, stub, "matific", "u-stub-fora")
    db.commit()
    d = _decidir(db, esc, recebido, SALA_2B)
    assert (d.acao, d.motivo, d.aluno_id) == (ida.REVISAR, "homonimo_em_outra_sala",
                                              identica.id)
    assert set(d.candidatos) == {identica.id, oficial.id, stub.id}
    assert d.preteridos == ()


def test_iv_stub_com_conta_da_mesma_plataforma_vai_para_revisao(db, oficial_e_stub):
    """O stub já tem conta NO ELEFANTE: pode ser a conta de outra criança."""
    c = oficial_e_stub
    esc, oficial, stub = c["escola"], c["oficial"], c["stub"]
    _conta(db, esc, stub, "elefante", "4400999")
    db.commit()
    d = _decidir(db, esc, "LARISSA VITORIA MENEZEZ COSTA", SALA_2B, id_externo="4400001")
    assert (d.acao, d.motivo) == (ida.REVISAR, "candidatos_multiplos")
    assert set(d.candidatos) == {oficial.id, stub.id}
    assert d.aluno_id == oficial.id                       # só sugestão


def test_iv_stub_com_conta_aposentada_da_mesma_plataforma_vai_para_revisao(db, oficial_e_stub):
    c = oficial_e_stub
    esc, stub = c["escola"], c["stub"]
    _conta(db, esc, stub, "elefante", "4400998", status="aposentada")
    db.commit()
    d = _decidir(db, esc, "LARISSA VITORIA MENEZEZ COSTA", SALA_2B, id_externo="4400001")
    assert (d.acao, d.motivo) == (ida.REVISAR, "candidatos_multiplos")


@pytest.mark.parametrize("divergencia", [
    {"ra": "999.000.111-2"},                       # RA diferente do da oficial
    {"nascimento": date(2018, 1, 1)},              # nascimento diferente
    {"chamada": 5},                                # nº de chamada diferente (23)
])
def test_v_stub_com_identificador_divergente_da_oficial_vai_para_revisao(db, rede,
                                                                         divergencia):
    esc = rede["escola"]
    _aluno(db, esc, rede["b"], "LARISSA VITORIA MENEZES COSTA", chamada=23,
           ra="120.555.111-0", nascimento=date(2019, 5, 10))
    _aluno(db, esc, rede["b"], "LARISSA V", lp=False, **divergencia)
    db.commit()
    d = _decidir(db, esc, "LARISSA VITORIA MENEZEZ COSTA", SALA_2B, id_externo="4400001")
    assert (d.acao, d.motivo) == (ida.REVISAR, "candidatos_multiplos")


@pytest.mark.parametrize("recebido", [
    "ARTUR HENRIQUE PRADO LIMA 2B",
    "ARTUR HENRIQUE PRADO LIMA 2ºB",
    "ARTUR HENRIQUE PRADO LIMA 2°B",
    "Artur Henrique Prado Lima  2b",
    "ARTUR HENRIQUE PRADO LIMA2B",               # sufixo grudado no último nome
])
def test_vi_sufixo_de_turma_no_nome_recebido_associa(db, rede, recebido):
    esc = rede["escola"]
    artur = _aluno(db, esc, rede["b"], "ARTUR HENRIQUE PRADO LIMA*")
    db.commit()
    d = _decidir(db, esc, recebido, SALA_2B)
    assert (d.acao, d.aluno_id, d.via) == (ida.ASSOCIAR, artur.id, "exato")


def test_vi_sufixo_de_turma_some_so_do_casamento_nao_do_nome_gravado(db, rede):
    """Indo para a revisão, a pendência guarda o nome RECEBIDO, com o sufixo."""
    esc = rede["escola"]
    _aluno(db, esc, rede["b"], "MARIA LUIZA ROCHA")
    _aluno(db, esc, rede["b"], "MARIA LETICIA PRADO")
    db.commit()
    r = _confirmar(db, esc, rede["admin"], "elefante",
                   [_elefante("MARIA L 2B", SALA_2B, 4400010)])
    assert r.qtd_revisoes == 1
    [rev] = _pendentes(db, esc)
    assert rev.nome_recebido == "MARIA L 2B" and rev.motivo == "candidatos_multiplos"
    assert rev.chave_identidade == "elefante|id:4400010"


def test_vi_nome_so_de_digitos_nao_vira_nome_vazio(db, rede):
    esc = rede["escola"]
    _aluno(db, esc, rede["b"], "BEATRIZ HELENA CAMPOS")
    db.commit()
    assert ida._nome_para_casar("2B 4A") == "2B 4A"
    assert ida._nome_para_casar("BEATRIZ HELENA CAMPOS") == "BEATRIZ HELENA CAMPOS"
    d = _decidir(db, esc, "2B", SALA_2B)
    assert d.acao == ida.CRIAR


@pytest.mark.parametrize("recebido,para_casar", [
    ("ARTUR PRADO LIMA 2B", "artur prado lima"),
    ("ARTUR PRADO LIMA2B", "artur prado lima"),            # só o sufixo sai do token
    ("ARTUR PRADO LIMA 2", "ARTUR PRADO LIMA 2"),          # número puro fica
    ("ARTUR PRADO LIMA2", "ARTUR PRADO LIMA2"),
    ("ARTUR PRADO LIMA 123B", "ARTUR PRADO LIMA 123B"),    # não tem forma de turma
])
def test_vi_so_o_sufixo_de_turma_sai_do_casamento(recebido, para_casar):
    assert ida._nome_para_casar(recebido) == para_casar


def test_vi_numero_puro_no_nome_nao_e_sufixo_de_turma(db, rede):
    """"… LIMA 2" pode ser o número com que a escola separa dois homônimos: se o
    número sumisse, o dado da 2ª criança iria para a ficha da 1ª. Revisão, como
    antes da mudança."""
    esc = rede["escola"]
    artur = _aluno(db, esc, rede["b"], "ARTUR HENRIQUE PRADO LIMA")
    db.commit()
    d = _decidir(db, esc, "ARTUR HENRIQUE PRADO LIMA 2", SALA_2B)
    assert (d.acao, d.motivo, d.aluno_id) == (ida.REVISAR, "correspondencia_insegura",
                                              artur.id)


@pytest.mark.parametrize("ficha,recebido", [
    ("GABRIELA MENDES SOUZA", "GABRIELA MENDES SOUSA"),      # último sobrenome
    ("LETICIA MARINA CORREIA", "LETICIA MARINA CORREA"),     # último sobrenome
    ("BRUNO TAVARES MELO", "BRUNA TAVARES MELO"),            # 1º nome / gênero
])
def test_vii_variacao_no_sobrenome_ou_primeiro_nome_continua_em_revisao(db, rede, ficha,
                                                                        recebido):
    """Candidato ÚNICO na sala, mas a variação está numa PONTA do nome: pode ser
    outra família ou outra criança (red-team 2026-08-04). Revisão, como antes."""
    esc = rede["escola"]
    unico = _aluno(db, esc, rede["b"], ficha)
    db.commit()
    d = _decidir(db, esc, recebido, SALA_2B)
    assert (d.acao, d.motivo, d.aluno_id) == (ida.REVISAR, "correspondencia_insegura",
                                              unico.id)


# --- 6. o desempate tem guardas ---------------------------------------------------

def test_desempate_respeita_a_guarda_de_outra_conta_na_plataforma(db, oficial_e_stub):
    """A oficial já tem OUTRA conta no Elefante: o desempate não passa por cima da
    guarda de ``_para_aluno`` — revisão."""
    c = oficial_e_stub
    esc, oficial = c["escola"], c["oficial"]
    _conta(db, esc, oficial, "elefante", "4400555")
    db.commit()
    d = _decidir(db, esc, "LARISSA VITORIA MENEZEZ COSTA", SALA_2B, id_externo="4400001")
    assert (d.acao, d.motivo, d.aluno_id) == (ida.REVISAR, "outra_identidade_na_plataforma",
                                              oficial.id)
    assert set(d.candidatos) == {oficial.id, c["stub"].id}


def test_desempate_exige_oficial_ativa(db, rede):
    esc = rede["escola"]
    _aluno(db, esc, rede["b"], "LARISSA VITORIA MENEZES COSTA", status="transferido")
    _aluno(db, esc, rede["b"], "LARISSA V", lp=False)
    db.commit()
    d = _decidir(db, esc, "LARISSA VITORIA MENEZEZ COSTA", SALA_2B, id_externo="4400001")
    assert (d.acao, d.motivo) == (ida.REVISAR, "candidatos_multiplos")


def test_stub_sem_dono_compativel_na_lista_piloto_nao_e_sombra(db, rede):
    """'CAIO RIBEIRO' (fora da lista) não é forma curta de 'CAIO MATEUS RIBEIRO'
    (é nome parcial: pode ser outra criança) — revisão."""
    esc = rede["escola"]
    _aluno(db, esc, rede["b"], "CAIO MATEUS RIBEIRO")
    _aluno(db, esc, rede["b"], "CAIO RIBEIRO", lp=False)
    db.commit()
    d = _decidir(db, esc, "CAIO MATHEUS RIBEIRO", SALA_2B)
    assert (d.acao, d.motivo) == (ida.REVISAR, "candidatos_multiplos")


def test_linha_que_nao_casaria_com_a_oficial_sozinha_vai_para_revisao(db, rede):
    """A linha só é compatível com a oficial como nome PARCIAL sem o último
    sobrenome — sozinha também seria revisão; o stub não muda isso."""
    esc = rede["escola"]
    _aluno(db, esc, rede["b"], "GUSTAVO ALMEIDA DE FREITAS")
    _aluno(db, esc, rede["b"], "GUSTAVO A", lp=False)
    db.commit()
    d = _decidir(db, esc, "GUSTAVO ALMEIDA", SALA_2B)
    assert d.acao == ida.REVISAR


def test_nome_identico_ao_do_stub_nao_passa_pelo_desempate(db, oficial_e_stub):
    """O desempate só age quando o motor devolve REVISAR. Nome IDÊNTICO ao de uma
    ficha da sala é o passo 3a, anterior — o comportamento dele não mudou."""
    c = oficial_e_stub
    d = _decidir(db, c["escola"], "LARISSA V", SALA_2B, id_externo="4400020")
    assert (d.acao, d.aluno_id, d.via) == (ida.ASSOCIAR, c["stub"].id, "exato")


# --- 7. a mudança é SÓ do caminho de plataforma --------------------------------------

def test_motor_compartilhado_nao_tem_o_desempate():
    """O motor único (``matching.classificar_linha``) continua com o mesmo
    contrato: oficial + stub = revisão. O desempate mora só em ``decidir``."""
    oficial = matching.Identidade(id=1, nome="LARISSA VITORIA MENEZES COSTA",
                                  da_lista_piloto=True)
    stub = matching.Identidade(id=2, nome="LARISSA V")
    res = matching.classificar_linha(
        matching.Identidade(nome="LARISSA VITORIA MENEZEZ COSTA"), [oficial, stub])
    assert res.status == matching.REVISAR and set(res.candidatos) == {1, 2}
    assert matching.classificar_linha(
        matching.Identidade(nome="LARISSA VITORIA MENEZEZ COSTA"), [oficial],
        vincular_variante=False).status == matching.REVISAR


def test_lista_piloto_com_oficial_e_stub_continua_em_revisao():
    """A porta da Lista Piloto (``matriculas.resolver_linha``) não ganhou o
    desempate: o mesmo cenário da plataforma (oficial + stub abreviado + typo no
    meio) segue para a revisão lá."""
    from app.services import matriculas

    ctx = matriculas.ContextoCasamento()
    ctx.registrar(matching.Identidade(id=1, nome="LARISSA VITORIA MENEZES COSTA",
                                      da_lista_piloto=True), "2|B")
    ctx.registrar(matching.Identidade(id=2, nome="LARISSA V"), "2|B")
    linha = matriculas.LinhaMatricula(nome="LARISSA VITORIA MENEZEZ COSTA", ra=None,
                                      nascimento=None, turma_id=1, chave_sala="2|B")
    d = matriculas.resolver_linha(linha, ctx)
    assert d.acao == matriculas.REVISAR and set(d.candidatos) == {1, 2}


def test_cadastro_manual_com_oficial_e_stub_continua_recusando_por_semelhanca(
        db, oficial_e_stub, cliente):
    """O cadastro manual (``_casar_no_roster`` do POST /alunos) também não ganhou o
    desempate: o nome com typo é "muito parecido" (revisão), não "já cadastrado"
    na oficial — e nenhuma ficha é criada."""
    c = oficial_e_stub
    esc, turma = c["escola"], c["b"]
    assert imp._casar_no_roster(db, esc.id, ANO, "LARISSA VITORIA MENEZEZ COSTA",
                                turma) == (None, "media")
    antes = _n_alunos(db, esc)
    r = cliente.post(f"/api/v1/escolas/{esc.id}/alunos",
                     json={"nome": "LARISSA VITORIA MENEZEZ COSTA", "turma_id": turma.id})
    assert r.status_code == 409 and "muito parecido" in r.json()["detail"]
    assert _n_alunos(db, esc) == antes
