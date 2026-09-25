"""Identidade de aluno nas importações de PLATAFORMA — porta única, fila de revisão
e identidade externa (UUID do Matific / studentId do Elefante).

Regras do dono (2026-09-21) cobertas aqui:
  * identidade externa consultada ANTES do nome (ficha ativa ou inativa); ficha
    excluída não é reutilizada; identidade de ficha inativa → revisão, sem ficha nova;
  * studentId do Elefante e UUID do Matific percorrem o fluxo inteiro e ficam
    gravados; a próxima sincronização casa por eles;
  * UMA normalização de "mesmo nome" (asterisco, pontuação, acento, espaços);
  * ordem: identidade → RA → sala (nome idêntico, identificador, candidato único
    ESTRUTURAL) → revisão → criação só sem candidato;
  * sala = escola + série + letra (todas as turmas dela), nunca "a primeira";
  * nunca escolhe o primeiro candidato, nunca funde fichas;
  * homônimo de OUTRA série não casa (o bug do token "ano");
  * REVISAR não descarta a linha: fica na fila até um gestor decidir;
  * prévia e confirmação decidem igual;
  * Lista Piloto: veto só pelo nº de chamada não inativa a ficha correta;
  * aluno.criado_auto registra o id da ficha criada.
"""
import json

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session as SASession

from app.models import (
    Aluno,
    Escola,
    IdentidadeExterna,
    LogAuditoria,
    Leitura,
    Livro,
    Matricula,
    RevisaoIdentidade,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
)
from app.routers import importacoes as imp
from app.schemas.importacao import ImportacaoConfirm, LinhaConfirmacao
from app.services import identidade_aluno as ida
from app.services import scoring
from app.services import importacao as svc
from app.services import matching, matriculas
from app.services.alunos_fusao import fundir_par
from app.sync import orchestrator
from app.sync.interfaces import ArquivoObtido, Contexto

ANO = 2026


# --- montagem ------------------------------------------------------------------

def _turma(db, escola, nome, ano_escolar="5º Ano", codigo=None):
    t = Turma(escola_id=escola.id, nome=nome, ano_escolar=ano_escolar, ano_letivo=ANO,
              codigo_externo=codigo)
    db.add(t)
    db.flush()
    return t


def _aluno(db, escola, turma, nome, *, status="ativo", chamada=None, lp=True):
    a = Aluno(escola_id=escola.id, nome=nome, status=status, numero_chamada=chamada,
              da_lista_piloto=lp)
    db.add(a)
    db.flush()
    if turma is not None:
        db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=turma.id,
                         ano_letivo=ANO))
        db.flush()
    return a


def _vincular(db, escola, aluno, plataforma, id_externo):
    db.add(IdentidadeExterna(escola_id=escola.id, aluno_id=aluno.id,
                             plataforma=plataforma, id_externo=id_externo))
    db.flush()


def _n_alunos(db, escola):
    return db.execute(select(func.count()).select_from(Aluno)
                      .where(Aluno.escola_id == escola.id)).scalar_one()


def _dono(db, escola, plataforma, id_externo):
    return db.execute(select(IdentidadeExterna.aluno_id).where(
        IdentidadeExterna.escola_id == escola.id,
        IdentidadeExterna.plataforma == plataforma,
        IdentidadeExterna.id_externo == id_externo)).scalar_one_or_none()


def _pendentes(db, escola):
    return db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == escola.id,
        RevisaoIdentidade.status == "pendente").order_by(RevisaoIdentidade.id)).scalars().all()


def _snap_matific(db, aluno_id):
    return db.execute(select(SnapshotMatific).where(
        SnapshotMatific.aluno_id == aluno_id)).scalars().first()


def _snap_elefante(db, aluno_id):
    return db.execute(select(SnapshotElefante).where(
        SnapshotElefante.aluno_id == aluno_id)).scalars().first()


def _matific(nome, turma, uuid="", estrelas=120, atividades=30, aluno_id=None):
    dados = {"turma_relatorio": turma, "estrelas": estrelas, "atividades": atividades,
             "pontuacao_media": round(estrelas / atividades, 2)}
    if uuid:
        dados["matific_uuid"] = uuid
    return LinhaConfirmacao(nome=nome, dados=dados, aluno_id=aluno_id,
                            criar_em_turma_nome=None if aluno_id else turma)


def _elefante(nome, turma, sid="", livros=7, aluno_id=None):
    dados = {"turma_relatorio": turma, "livros_unicos": livros, "tempo_leitura_min": 40,
             "questoes_tentativas": 5, "questoes_acertos": 4}
    if sid:
        dados["elefante_student_id"] = str(sid)
    return LinhaConfirmacao(nome=nome, dados=dados, aluno_id=aluno_id,
                            criar_em_turma_nome=None if aluno_id else turma)


def _confirmar(db, escola, admin, plataforma, linhas, **kw):
    conf = ImportacaoConfirm(plataforma=plataforma, formato=kw.pop("formato", "resumo"),
                             tipo="texto", linhas=linhas, recalcular=False, **kw)
    return imp.confirmar(dados=conf, escola_id=escola.id, usuario=admin, db=db)


def _previa(db, escola, plataforma, linhas):
    brutas = [svc.LinhaImportacao(numero=i, nome=l.nome, dados=dict(l.dados))
              for i, l in enumerate(linhas, start=1)]
    svc.casar_nomes(db, escola.id, brutas, plataforma=plataforma)
    return [l.correspondencia for l in brutas]


@pytest.fixture()
def sala(db, escola_completa):
    """5ºA com os três casos reais (nomes completos da Lista Piloto) + colegas."""
    esc = escola_completa["escola"]
    t = _turma(db, esc, "5ºA", codigo="300300001")
    alunos = {
        "heloisa": _aluno(db, esc, t, "HELOISA DEL GIUDICE DE SOUZA FIDELIX"),
        "taufik": _aluno(db, esc, t, "TAUFIK DE OLIVEIRA SANTOS"),
        "mathias": _aluno(db, esc, t, "MATHIAS RICARDO RODRIGUES MARADEI"),
        "heitor": _aluno(db, esc, t, "HEITOR DE SOUZA LIMA"),
        "maria": _aluno(db, esc, t, "MARIA CLARA SOUZA"),
        "joao": _aluno(db, esc, t, "JOÃO VÍTOR ARAÚJO"),
    }
    db.commit()
    return {"escola": esc, "admin": escola_completa["admin"], "turma": t, **alunos}


# --- 1. chave única de "mesmo nome" ------------------------------------------------

def test_chave_nome_e_a_unica_definicao_de_mesmo_nome():
    base = svc.chave_nome("MARIA CLARA SOUZA")
    for variante in ("MARIA CLARA* SOUZA", "Maria Clara Souza.", "  MARIA   CLARA  SOUZA ",
                     "MARÍA CLÁRA SOUZA", "maria clara souza*"):
        assert svc.chave_nome(variante) == base, variante
    assert svc.chave_nome("MARIA CLARA SOUZA") != svc.chave_nome("MARIA CLARA SOUSA")


# --- 2. os três casos reais ------------------------------------------------------

def test_heloisa_nome_do_meio_omitido_vai_para_a_ficha_completa(db, sala):
    esc, heloisa = sala["escola"], sala["heloisa"]
    antes = _n_alunos(db, esc)
    linha = _elefante("HELOISA DE SOUZA FIDELIX", "5 ANO A MANHA ANUAL (300300001)", sid=9001)

    [corr] = _previa(db, esc, "elefante", [linha])
    assert (corr["status"], corr["aluno_id"], corr["via"]) == ("vinculado", heloisa.id, "parcial")

    r = _confirmar(db, esc, sala["admin"], "elefante", [linha])
    assert (r.qtd_alunos, r.qtd_revisoes) == (1, 0)
    assert _n_alunos(db, esc) == antes                       # nenhuma ficha nova
    assert _snap_elefante(db, heloisa.id) is not None       # dados na ficha completa
    assert _dono(db, esc, "elefante", "9001") == heloisa.id  # studentId gravado


@pytest.mark.parametrize("chave,abreviado,uuid", [
    ("taufik", "TAUFIK D", "u-taufik"),
    ("mathias", "MATHIAS R", "u-mathias"),
])
def test_nome_abreviado_do_matific_vai_para_a_ficha_completa(db, sala, chave, abreviado, uuid):
    esc, dono = sala["escola"], sala[chave]
    antes = _n_alunos(db, esc)
    linha = _matific(abreviado, "5 ANO A", uuid)

    [corr] = _previa(db, esc, "matific", [linha])
    assert (corr["status"], corr["aluno_id"], corr["via"]) == ("vinculado", dono.id, "abreviacao")

    r = _confirmar(db, esc, sala["admin"], "matific", [linha])
    assert r.qtd_revisoes == 0 and _n_alunos(db, esc) == antes
    assert _snap_matific(db, dono.id) is not None
    assert _dono(db, esc, "matific", uuid) == dono.id


def test_abreviado_com_dois_donos_possiveis_vai_para_revisao(db, sala):
    esc = sala["escola"]
    _aluno(db, esc, sala["turma"], "MATHIAS ROCHA LIMA")
    db.commit()
    antes = _n_alunos(db, esc)
    linha = _matific("MATHIAS R", "5 ANO A", "u-mr")

    [corr] = _previa(db, esc, "matific", [linha])
    assert corr["status"] == "revisar" and corr["motivo"] == "candidatos_multiplos"
    assert len(corr["alternativas"]) == 2

    r = _confirmar(db, esc, sala["admin"], "matific", [linha])
    assert r.qtd_alunos == 0 and r.qtd_revisoes == 1 and _n_alunos(db, esc) == antes
    assert _dono(db, esc, "matific", "u-mr") is None        # ninguém ficou com a conta


# --- 3. grafia: asterisco, acento, espaços ------------------------------------------

@pytest.mark.parametrize("recebido,chave", [
    ("MARIA CLARA* SOUZA", "maria"),
    ("JOAO VITOR ARAUJO", "joao"),
    ("  JOÃO   VÍTOR    ARAÚJO ", "joao"),
])
def test_grafia_nao_cria_ficha_nova(db, sala, recebido, chave):
    esc, dono = sala["escola"], sala[chave]
    antes = _n_alunos(db, esc)
    linha = _matific(recebido, "5ºA", "u-" + chave)
    [corr] = _previa(db, esc, "matific", [linha])
    assert (corr["status"], corr["aluno_id"], corr["via"]) == ("exato", dono.id, "exato")
    _confirmar(db, esc, sala["admin"], "matific", [linha])
    assert _n_alunos(db, esc) == antes and _snap_matific(db, dono.id) is not None


def test_nome_parcial_sem_o_ultimo_sobrenome_vai_para_revisao(db, sala):
    """Subconjunto que perde o ÚLTIMO sobrenome não é estrutural: o dono real desse
    nome pode ser outra criança. Não associa, não cria."""
    esc = sala["escola"]
    antes = _n_alunos(db, esc)
    linha = _elefante("HELOISA DEL GIUDICE", "5ºA", sid=9100)
    [corr] = _previa(db, esc, "elefante", [linha])
    assert corr["status"] == "revisar" and corr["motivo"] == "correspondencia_insegura"
    r = _confirmar(db, esc, sala["admin"], "elefante", [linha])
    assert r.qtd_revisoes == 1 and _n_alunos(db, esc) == antes
    assert _snap_elefante(db, sala["heloisa"].id) is None


def test_matching_subconjunto_so_estrutural():
    ficha = matching.Identidade(id=1, nome="HELOISA DEL GIUDICE DE SOUZA FIDELIX")
    assert matching.classificar_linha(
        matching.Identidade(nome="HELOISA DE SOUZA FIDELIX"), [ficha],
        permitir_subconjunto_unico=True).status == matching.VINCULADO
    assert matching.classificar_linha(
        matching.Identidade(nome="HELOISA DE SOUZA"), [ficha],
        permitir_subconjunto_unico=True).status == matching.REVISAR


def test_variante_de_grafia_sem_corroboracao_vai_para_revisao(db, sala):
    """"RICADO" × "RICARDO" (typo no nome do meio, pontas iguais): parecido não é
    prova. Na plataforma não associa só pelo nome — revisão."""
    esc, mathias = sala["escola"], sala["mathias"]
    linha = _matific("MATHIAS RICADO RODRIGUES MARADEI", "5ºA", "u-ricado")
    [corr] = _previa(db, esc, "matific", [linha])
    assert corr["status"] == "revisar" and corr["aluno_id"] == mathias.id
    antes = _n_alunos(db, esc)
    r = _confirmar(db, esc, sala["admin"], "matific", [linha])
    assert r.qtd_revisoes == 1 and _n_alunos(db, esc) == antes
    assert _snap_matific(db, mathias.id) is None


def test_nome_que_so_casa_em_outra_turma_nao_vira_ficha_stub(db, sala):
    """O padrão histórico dos stubs: "TAUFIK D" chegando por uma turma onde ele NÃO
    está. Antes: ninguém na sala → criava a ficha "TAUFIK D". Agora: o nome casa
    com aluno de OUTRA turma → revisão, nenhuma ficha nova."""
    esc = sala["escola"]
    _turma(db, esc, "5ºB")
    db.commit()
    antes = _n_alunos(db, esc)
    linha = _matific("TAUFIK D", "5 ANO B", "u-tb")
    [corr] = _previa(db, esc, "matific", [linha])
    assert corr["status"] == "revisar" and corr["motivo"] == "nome_casa_em_outra_sala"
    assert corr["aluno_id"] == sala["taufik"].id
    r = _confirmar(db, esc, sala["admin"], "matific", [linha])
    assert r.qtd_revisoes == 1 and _n_alunos(db, esc) == antes


# --- 4. identidade externa -----------------------------------------------------

def test_identidade_externa_decide_antes_do_nome(db, sala):
    """O Matific renomeou a conta e a turma do relatório é outra: o UUID já
    vinculado continua sendo a identidade."""
    esc, taufik = sala["escola"], sala["taufik"]
    _vincular(db, esc, taufik, "matific", "u-t1")
    db.commit()
    antes = _n_alunos(db, esc)
    linha = _matific("TAUFIK OLIVEIRA", "4 ANO B", "u-t1")
    [corr] = _previa(db, esc, "matific", [linha])
    assert (corr["status"], corr["aluno_id"], corr["via"]) == ("exato", taufik.id, "identidade")
    _confirmar(db, esc, sala["admin"], "matific", [linha])
    assert _n_alunos(db, esc) == antes and _snap_matific(db, taufik.id) is not None


def test_identidade_de_ficha_inativa_vai_para_revisao_sem_ficha_nova(db, sala):
    esc = sala["escola"]
    luana = _aluno(db, esc, sala["turma"], "LUANA MOTA", status="fora_lista_piloto")
    _vincular(db, esc, luana, "matific", "u-luana")
    db.commit()
    antes = _n_alunos(db, esc)
    linha = _matific("LUANA MOTA", "5ºA", "u-luana")

    [corr] = _previa(db, esc, "matific", [linha])
    assert corr["status"] == "revisar" and corr["motivo"] == "identidade_de_ficha_inativa"

    r = _confirmar(db, esc, sala["admin"], "matific", [linha])
    assert r.qtd_alunos == 0 and r.qtd_revisoes == 1
    assert _n_alunos(db, esc) == antes                     # nenhuma ficha nova
    assert _dono(db, esc, "matific", "u-luana") == luana.id  # identidade preservada
    assert _snap_matific(db, luana.id) is None


def test_ficha_excluida_nao_e_reutilizada(db, sala):
    esc = sala["escola"]
    rafael = _aluno(db, esc, sala["turma"], "RAFAEL PINTO", status="excluido")
    _vincular(db, esc, rafael, "matific", "u-rafa")
    db.commit()
    antes = _n_alunos(db, esc)
    linha = _matific("RAFAEL PINTO", "5ºA", "u-rafa")

    [corr] = _previa(db, esc, "matific", [linha])
    assert corr["status"] == "nao_encontrado"

    _confirmar(db, esc, sala["admin"], "matific", [linha])
    assert _n_alunos(db, esc) == antes + 1
    novo = db.execute(select(Aluno).where(Aluno.escola_id == esc.id, Aluno.nome == "RAFAEL PINTO",
                                          Aluno.status == "ativo")).scalar_one()
    assert _dono(db, esc, "matific", "u-rafa") == novo.id
    assert db.get(Aluno, rafael.id).status == "excluido" and _snap_matific(db, rafael.id) is None
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "identidade.reatribuida")).scalar_one()
    assert log.detalhes["de_aluno_id"] == rafael.id and log.detalhes["para_aluno_id"] == novo.id


def test_escolha_explicita_contra_a_identidade_de_outro_aluno_vai_para_revisao(db, sala):
    esc = sala["escola"]
    _vincular(db, esc, sala["taufik"], "matific", "u-t2")
    db.commit()
    linha = _matific("TAUFIK D", "5ºA", "u-t2", aluno_id=sala["mathias"].id)
    r = _confirmar(db, esc, sala["admin"], "matific", [linha])
    assert r.qtd_alunos == 0 and r.qtd_revisoes == 1
    assert _pendentes(db, esc)[0].motivo == "identidade_de_outro_aluno"
    assert _snap_matific(db, sala["mathias"].id) is None
    assert _dono(db, esc, "matific", "u-t2") == sala["taufik"].id


def test_student_id_do_elefante_percorre_parser_e_conector():
    resumo = svc.analisar_elefante_api({
        "courseSchoolDescriptors": {"courseName": "5 ANO A"},
        "students": [{"studentId": 4242, "studentName": "HELOISA DE SOUZA FIDELIX",
                      "totalBooksRead": 3}]})
    assert resumo.linhas[0].dados["elefante_student_id"] == "4242"
    leituras = svc.analisar_elefante_api({
        "courseSchoolDescriptors": {"courseName": "5 ANO A"},
        "leituras": [{"nome": "HELOISA DE SOUZA FIDELIX", "studentId": "4242",
                      "bookTitle": "Livro", "lastReadWhen": "2026-09-01T10:00:00"}]})
    assert leituras.linhas[0].dados["elefante_student_id"] == "4242"


# --- 5. dois candidatos, homônimos e salas -------------------------------------

def test_dois_homonimos_na_sala_vao_para_revisao(db, sala):
    esc = sala["escola"]
    a1 = _aluno(db, esc, sala["turma"], "ANA LIMA")
    a2 = _aluno(db, esc, sala["turma"], "ANA LIMA")
    db.commit()
    antes = _n_alunos(db, esc)
    linha = _matific("ANA LIMA", "5ºA", "u-ana")
    [corr] = _previa(db, esc, "matific", [linha])
    assert corr["status"] == "revisar" and {c["aluno_id"] for c in corr["alternativas"]} == {a1.id, a2.id}
    _confirmar(db, esc, sala["admin"], "matific", [linha])
    assert _n_alunos(db, esc) == antes
    assert _snap_matific(db, a1.id) is None and _snap_matific(db, a2.id) is None


@pytest.mark.parametrize("turma_4a_cadastrada", [True, False])
def test_homonimo_de_outra_serie_nao_casa(db, sala, turma_4a_cadastrada):
    """O bug do token "ano": "4 ANO A" × "5ºA ..." dividiam {ano, a} e o homônimo da
    OUTRA série passava como o mesmo aluno. Agora: revisão, nunca vínculo."""
    esc = sala["escola"]
    joao5 = _aluno(db, esc, sala["turma"], "JOAO SILVA SANTOS")
    if turma_4a_cadastrada:
        _turma(db, esc, "4ºA", ano_escolar="4º Ano")
    db.commit()
    antes = _n_alunos(db, esc)
    linha = _matific("JOAO SILVA SANTOS", "4 ANO A MANHA ANUAL", "u-j4")

    [corr] = _previa(db, esc, "matific", [linha])
    assert corr["status"] == "revisar" and corr["motivo"] == "homonimo_em_outra_sala"

    r = _confirmar(db, esc, sala["admin"], "matific", [linha])
    assert r.qtd_alunos == 0 and r.qtd_revisoes == 1 and _n_alunos(db, esc) == antes
    assert _snap_matific(db, joao5.id) is None


def test_duas_turmas_da_mesma_sala_nao_escolhem_arbitrariamente(db, escola_completa):
    esc, admin = escola_completa["escola"], escola_completa["admin"]
    manha = _turma(db, esc, "5 ANO A MANHA")
    tarde = _turma(db, esc, "5 ANO A TARDE")
    bruno = _aluno(db, esc, tarde, "BRUNO COSTA")
    db.commit()

    # O roster é a SALA inteira (as duas turmas): Bruno é achado mesmo com o
    # relatório apontando a outra linha de turma da mesma sala.
    [corr] = _previa(db, esc, "matific", [_matific("BRUNO COSTA", "5 ANO A MANHA", "u-b")])
    assert (corr["status"], corr["aluno_id"]) == ("exato", bruno.id)

    # Aluno novo sem turma decidível (duas turmas na sala, nome não bate com
    # nenhuma) → revisão, não "a primeira turma".
    antes = _n_alunos(db, esc)
    r = _confirmar(db, esc, admin, "matific", [_matific("CAIO NUNES", "5 ANO A", "u-c")])
    assert r.qtd_revisoes == 1 and _n_alunos(db, esc) == antes
    assert _pendentes(db, esc)[0].motivo == "turma_ambigua"

    # Com o nome da turma idêntico, a escolha é determinística.
    _confirmar(db, esc, admin, "matific", [_matific("DAVI NUNES", "5 ANO A TARDE", "u-d")])
    davi = db.execute(select(Aluno).where(Aluno.nome == "DAVI NUNES")).scalar_one()
    mat = db.execute(select(Matricula).where(Matricula.aluno_id == davi.id)).scalar_one()
    assert mat.turma_id == tarde.id and mat.turma_id != manha.id


# --- 6. REVISAR não descarta a linha; resolução explícita ---------------------------

def test_revisar_preserva_a_linha_inteira_e_nao_duplica_a_pendencia(db, sala):
    esc = sala["escola"]
    linha = _elefante("HELOISA DEL GIUDICE", "5 ANO A (300300001)", sid=9200, livros=12)
    r = _confirmar(db, esc, sala["admin"], "elefante", [linha])
    assert r.qtd_revisoes == 1 and svc.chave_nome("HELOISA DEL GIUDICE") in r.ignorados

    [rev] = _pendentes(db, esc)
    assert rev.plataforma == "elefante" and rev.formato == "resumo"
    assert rev.id_externo == "9200"
    assert rev.nome_recebido == "HELOISA DEL GIUDICE"
    assert rev.turma_informada == "5 ANO A (300300001)" and rev.turma_id == sala["turma"].id
    assert rev.motivo == "correspondencia_insegura"
    assert [c["aluno_id"] for c in rev.candidatos] == [sala["heloisa"].id]
    assert rev.linhas[0]["livros_unicos"] == 12 and rev.linhas[0]["elefante_student_id"] == "9200"
    assert rev.contexto["tipo"] == "texto" and rev.contexto["data_referencia"]
    assert rev.importacao_id == r.importacao_id and rev.origem == "importacao"
    assert rev.status == "pendente" and rev.ocorrencias == 1 and rev.created_at
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "aluno.revisao_necessaria")).scalars().all()
    assert log and log[-1].detalhes["revisao_id"] == rev.id

    # Reimportar o mesmo relatório ATUALIZA a pendência (não empilha outra).
    _confirmar(db, esc, sala["admin"], "elefante", [_elefante(
        "HELOISA DEL GIUDICE", "5 ANO A (300300001)", sid=9200, livros=13)])
    [rev2] = _pendentes(db, esc)
    assert rev2.id == rev.id and rev2.ocorrencias == 2 and rev2.linhas[0]["livros_unicos"] == 13


def test_resolucao_associa_ao_aluno_escolhido_e_a_proxima_sync_nao_duplica(
        db, sala, cliente, monkeypatch):
    esc, heloisa = sala["escola"], sala["heloisa"]
    _confirmar(db, esc, sala["admin"], "elefante",
               [_elefante("HELOISA DEL GIUDICE", "5ºA", sid=9300, livros=15)])
    [rev] = _pendentes(db, esc)
    antes = _n_alunos(db, esc)

    base = f"/api/v1/escolas/{esc.id}/importacoes/revisoes"
    lista = cliente.get(base)
    assert lista.status_code == 200 and [r["id"] for r in lista.json()] == [rev.id]
    assert lista.json()[0]["motivo_texto"]

    resp = cliente.post(f"{base}/{rev.id}/resolver", json={"aluno_id": heloisa.id})
    assert resp.status_code == 200, resp.text
    corpo = resp.json()
    assert corpo["aluno_id"] == heloisa.id and corpo["revisao"]["status"] == "resolvida"
    assert corpo["importacoes"]

    db.expire_all()
    rev = db.get(RevisaoIdentidade, rev.id)
    assert rev.aluno_escolhido_id == heloisa.id and rev.resolvida_por_id and rev.resolvida_em
    assert _dono(db, esc, "elefante", "9300") == heloisa.id       # identidade gravada
    snap = _snap_elefante(db, heloisa.id)
    assert snap is not None and snap.livros_unicos == 15           # dados aplicados
    assert _n_alunos(db, esc) == antes                             # nada criado
    assert db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "identidade.revisao_resolvida")).scalars().first() is not None
    # Resolver de novo é recusado.
    assert cliente.post(f"{base}/{rev.id}/resolver",
                        json={"aluno_id": heloisa.id}).status_code == 409

    # Próxima SINCRONIZAÇÃO (orquestrador real): casa pelo studentId, sem revisão
    # nova e sem ficha nova — mesmo com o nome parcial de sempre.
    monkeypatch.setattr(orchestrator.imp, "_guardar_temporario", lambda *a, **k: None)
    payload = {"courseSchoolDescriptors": {"courseName": "5 ANO A"},
               "students": [{"studentId": 9300, "studentName": "HELOISA DEL GIUDICE",
                             "totalBooksRead": 16}]}
    orchestrator.aplicar_arquivo(
        db, esc, ArquivoObtido(conteudo=json.dumps(payload).encode("utf-8"),
                               nome_arquivo="e.json", plataforma="elefante",
                               content_type=orchestrator.CT_ELEFANTE_API,
                               formato_hint="resumo"),
        usuario_id=None, recalcular=False,
        contexto=Contexto(escola_id=esc.id, execucao_id=None, log=lambda *a: None))
    db.expire_all()
    assert _n_alunos(db, esc) == antes and _pendentes(db, esc) == []
    ultimo = db.execute(select(SnapshotElefante).where(SnapshotElefante.aluno_id == heloisa.id)
                        .order_by(SnapshotElefante.id.desc())).scalars().first()
    assert ultimo.livros_unicos == 16


def test_resolucao_para_ficha_inativa_nao_reabre_a_revisao(db, sala, cliente):
    esc = sala["escola"]
    luana = _aluno(db, esc, sala["turma"], "LUANA MOTA", status="arquivado")
    _vincular(db, esc, luana, "matific", "u-lu")
    db.commit()
    _confirmar(db, esc, sala["admin"], "matific", [_matific("LUANA MOTA", "5ºA", "u-lu")])
    [rev] = _pendentes(db, esc)
    resp = cliente.post(f"/api/v1/escolas/{esc.id}/importacoes/revisoes/{rev.id}/resolver",
                        json={"aluno_id": luana.id})
    assert resp.status_code == 200 and resp.json()["avisos"]
    db.expire_all()
    r = _confirmar(db, esc, sala["admin"], "matific",
                   [_matific("LUANA MOTA", "5ºA", "u-lu", estrelas=150)])
    assert r.qtd_revisoes == 0 and _pendentes(db, esc) == []
    assert db.get(Aluno, luana.id).status == "arquivado"          # não reativa sozinho


def test_resolucao_pode_criar_ficha_nova_explicitamente(db, sala, cliente):
    esc = sala["escola"]
    _aluno(db, esc, sala["turma"], "JOAO SILVA SANTOS")
    t4 = _turma(db, esc, "4ºA", ano_escolar="4º Ano")
    db.commit()
    _confirmar(db, esc, sala["admin"], "matific", [_matific("JOAO SILVA SANTOS", "4ºA", "u-j")])
    [rev] = _pendentes(db, esc)
    antes = _n_alunos(db, esc)
    resp = cliente.post(f"/api/v1/escolas/{esc.id}/importacoes/revisoes/{rev.id}/resolver",
                        json={"criar_em_turma_id": t4.id})
    assert resp.status_code == 200, resp.text
    novo_id = resp.json()["aluno_id"]
    db.expire_all()
    assert _n_alunos(db, esc) == antes + 1 and _dono(db, esc, "matific", "u-j") == novo_id
    assert _snap_matific(db, novo_id) is not None
    # Próxima importação: identidade → a ficha nova; sem revisão.
    r = _confirmar(db, esc, sala["admin"], "matific", [_matific("JOAO SILVA SANTOS", "4ºA", "u-j")])
    assert r.qtd_revisoes == 0 and _n_alunos(db, esc) == antes + 1


def test_descartar_revisao(db, sala, cliente):
    esc = sala["escola"]
    _confirmar(db, esc, sala["admin"], "elefante", [_elefante("HELOISA DEL GIUDICE", "5ºA", sid=1)])
    [rev] = _pendentes(db, esc)
    base = f"/api/v1/escolas/{esc.id}/importacoes/revisoes/{rev.id}"
    assert cliente.post(f"{base}/resolver", json={}).status_code == 400
    resp = cliente.post(f"{base}/descartar", json={"motivo": "conta de teste"})
    assert resp.status_code == 200 and resp.json()["status"] == "descartada"
    assert _pendentes(db, esc) == []


# --- 7. o histórico dos stubs + fusão administrativa --------------------------------

def test_stub_existente_e_fusao_administrativa_sem_recriar(db, sala):
    """Enquanto a ficha-stub existir, a conta dela continua sendo dela (identidade
    primeiro). A FUSÃO é ação explícita do gestor; depois dela, a sincronização
    casa pela identidade transferida e não recria a duplicata."""
    esc, taufik = sala["escola"], sala["taufik"]
    stub = _aluno(db, esc, sala["turma"], "TAUFIK D", lp=False)
    _vincular(db, esc, stub, "matific", "u-tf")
    db.commit()
    [corr] = _previa(db, esc, "matific", [_matific("TAUFIK D", "5 ANO A", "u-tf")])
    assert corr["aluno_id"] == stub.id and corr["via"] == "identidade"
    # O nome completo, sem identidade, vai para a ficha de nome idêntico.
    [corr] = _previa(db, esc, "elefante", [_elefante("TAUFIK DE OLIVEIRA SANTOS", "5ºA")])
    assert corr["aluno_id"] == taufik.id

    fundir_par(db, esc.id, taufik, stub, usuario_id=sala["admin"].id)
    db.commit()
    antes = _n_alunos(db, esc)
    r = _confirmar(db, esc, sala["admin"], "matific", [_matific("TAUFIK D", "5 ANO A", "u-tf")])
    assert r.qtd_revisoes == 0 and _n_alunos(db, esc) == antes
    assert _snap_matific(db, taufik.id) is not None


# --- 8. prévia == confirmação -------------------------------------------------------

CASOS = [
    ("MARIA CLARA* SOUZA", "u-1"),            # exato (asterisco)
    ("TAUFIK D", "u-2"),                      # abreviação única
    ("HELOISA DE SOUZA FIDELIX", "u-3"),      # parcial estrutural
    ("HELOISA DEL GIUDICE", "u-4"),           # parcial não estrutural → revisão
    ("MATHIAS R", "u-5"),                     # dois candidatos (com o extra) → revisão
    ("JOAO SILVA SANTOS", "u-6"),             # homônimo em outra série → revisão
    ("KAUA MENDES", "u-7"),                   # ninguém → cria
    ("QUALQUER NOME", "u-8"),                 # identidade vinculada → dono
]


@pytest.mark.parametrize("modo", ["tela", "sincronizacao"])
@pytest.mark.parametrize("nome,uuid", CASOS)
def test_previa_e_confirmacao_decidem_igual(db, sala, nome, uuid, modo):
    esc = sala["escola"]
    _aluno(db, esc, sala["turma"], "MATHIAS ROCHA LIMA")
    outra = _turma(db, esc, "4ºA", ano_escolar="4º Ano")
    _aluno(db, esc, outra, "JOAO SILVA SANTOS")
    _vincular(db, esc, sala["maria"], "matific", "u-8")
    db.commit()
    linha = _matific(nome, "5 ANO A", uuid)
    [corr] = _previa(db, esc, "matific", [linha])
    antes = _n_alunos(db, esc)

    if modo == "tela" and corr["status"] in ("exato", "vinculado"):
        # a tela manda o aluno pré-selecionado; a sync manda a linha crua
        linha = _matific(nome, "5 ANO A", uuid, aluno_id=corr["aluno_id"])
    r = _confirmar(db, esc, sala["admin"], "matific", [linha],
                   sincronizar_turma=(modo == "sincronizacao"),
                   permitir_criar_turma=(modo == "tela"))

    if corr["status"] in ("exato", "vinculado"):
        assert r.qtd_revisoes == 0 and _n_alunos(db, esc) == antes
        assert _snap_matific(db, corr["aluno_id"]) is not None
        assert _dono(db, esc, "matific", uuid) == corr["aluno_id"]
    elif corr["status"] == "revisar":
        assert r.qtd_alunos == 0 and r.qtd_revisoes == 1 and _n_alunos(db, esc) == antes
    else:
        assert corr["status"] == "nao_encontrado"
        assert r.qtd_revisoes == 0 and _n_alunos(db, esc) == antes + 1


# --- 9. auditoria da criação ------------------------------------------------------

def test_criado_auto_registra_o_id_da_ficha(db, sala):
    esc = sala["escola"]
    _confirmar(db, esc, sala["admin"], "matific", [_matific("KAUA MENDES", "5ºA", "u-k")])
    novo = db.execute(select(Aluno).where(Aluno.nome == "KAUA MENDES")).scalar_one()
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "aluno.criado_auto")).scalar_one()
    assert log.entidade_id == novo.id and log.entidade == "aluno"
    assert _dono(db, esc, "matific", "u-k") == novo.id           # identidade já na criação


# --- 10. Lista Piloto: chamada renumerada não prejudica a ficha correta -------------

def test_lista_piloto_chamada_renumerada_nao_cria_nem_inativa():
    ctx = matriculas.ContextoCasamento()
    ctx.registrar(matching.Identidade(id=7, nome="HELOISA DEL GIUDICE DE SOUZA FIDELIX",
                                      chamada=11, da_lista_piloto=True), "5|A")
    linha = matriculas.LinhaMatricula(nome="HELOISA DEL GIUDICE DE SOUZA FIDELIX", ra=None,
                                      nascimento=None, turma_id=1, chave_sala="5|A", chamada=12)
    d = matriculas.resolver_linha(linha, ctx)
    assert d.acao == matriculas.REVISAR and 7 in d.candidatos     # protegido do "fora da lista"


def test_lista_piloto_chamada_renumerada_ponta_a_ponta(db, escola_completa, cliente):
    from tests.test_lista_piloto_identidade import _aluno as linha_lp
    from tests.test_lista_piloto_identidade import _confirmar as confirmar_lp
    from tests.test_lista_piloto_identidade import _planilha

    esc = escola_completa["escola"]
    confirmar_lp(cliente, esc.id, _planilha(("5º ANO A", [
        linha_lp("HELOISA DEL GIUDICE DE SOUZA FIDELIX", numero=11),
        linha_lp("TAUFIK DE OLIVEIRA SANTOS", numero=12)])))
    db.expire_all()
    heloisa = db.execute(select(Aluno).where(
        Aluno.nome == "HELOISA DEL GIUDICE DE SOUZA FIDELIX")).scalar_one()
    antes = _n_alunos(db, esc)

    # Nova lista: a secretaria renumerou (Heloisa 11 → 12) e ninguém tem RA.
    confirmar_lp(cliente, esc.id, _planilha(("5º ANO A", [
        linha_lp("TAUFIK DE OLIVEIRA SANTOS", numero=11),
        linha_lp("HELOISA DEL GIUDICE DE SOUZA FIDELIX", numero=12)])))
    db.expire_all()
    assert _n_alunos(db, esc) == antes                             # nenhuma 2ª ficha
    assert db.get(Aluno, heloisa.id).status == "ativo"             # ficha correta intacta


def test_decisao_e_so_leitura(db, sala):
    """A porta única não grava nada: a prévia pode rodar quantas vezes quiser."""
    esc = sala["escola"]
    ctx = ida.carregar_contexto(db, esc.id)
    antes = (_n_alunos(db, esc), len(_pendentes(db, esc)))
    for nome in ("KAUA MENDES", "HELOISA DEL GIUDICE", "TAUFIK D"):
        ida.decidir(ctx, ida.linha_de_dados(nome, {"matific_uuid": "x"}, plataforma="matific",
                                            turma_nome="5ºA"))
    db.flush()
    assert (_n_alunos(db, esc), len(_pendentes(db, esc))) == antes


# --- 12. sala do relatório × turma cadastrada SEM letra (série única) --------------
#
# Regressão real (escola 17, 2026-09-22): a escola cadastrou "4º Ano" — única turma
# da série — e o relatório traz "4 ANO A INTEGRAL (300309347)". A sala do relatório
# ("4|A") não existia no cadastro ("4 ano"), então TODA linha caía em revisão: 139
# pendências, 0 snapshot, ranking vazio. A sala passa a ser reconhecida pela SÉRIE
# quando — e só quando — a escola tem UMA turma ativa dela.

def test_serie_da_sala_le_relatorio_e_cadastro():
    """A leitura de série é a MESMA do motor de dificuldade — e nunca inventa série."""
    assert matriculas.serie_da_sala("4 ANO A INTEGRAL (300309347)") == 4
    assert matriculas.serie_da_sala("3 ANO B") == 3
    assert matriculas.serie_da_sala("4º Ano") == 4
    assert matriculas.serie_da_sala("", "5º Ano") == 5          # rótulo da turma cadastrada
    assert matriculas.serie_da_sala("Turma 3") is None
    assert matriculas.serie_da_sala("EJA 2") is None
    assert matriculas.serie_da_sala("Maternal") is None


def test_sala_do_relatorio_casa_com_a_turma_unica_da_serie(db, escola_completa):
    """(A) "4 ANO A INTEGRAL (300…)" + única turma "4º Ano" → é a mesma sala."""
    esc, admin = escola_completa["escola"], escola_completa["admin"]
    quarto = _turma(db, esc, "4º Ano", ano_escolar="4º Ano")
    isaac = _aluno(db, esc, quarto, "ISAAC ALMEIDA RODRIGUES")
    db.commit()
    antes = _n_alunos(db, esc)
    linha = _matific("ISAAC A", "4 ANO A INTEGRAL (300309347)", "uuid-isaac")

    [corr] = _previa(db, esc, "matific", [linha])
    assert (corr["status"], corr["aluno_id"], corr["via"]) == ("vinculado", isaac.id,
                                                              "abreviacao")

    r = _confirmar(db, esc, admin, "matific", [linha])
    assert (r.qtd_alunos, r.qtd_revisoes) == (1, 0) and _n_alunos(db, esc) == antes
    assert _snap_matific(db, isaac.id) is not None
    assert _dono(db, esc, "matific", "uuid-isaac") == isaac.id   # UUID fica vinculado


def test_sala_com_outra_letra_casa_com_a_turma_unica_da_serie(db, escola_completa):
    """(B) "2 ANO B" + única turma "2º Ano": a letra do relatório não inventa sala."""
    esc = escola_completa["escola"]
    segundo = _turma(db, esc, "2º Ano", ano_escolar="2º Ano")
    joana = _aluno(db, esc, segundo, "JOANA PEREIRA LIMA")
    db.commit()
    [corr] = _previa(db, esc, "matific", [_matific("JOANA PEREIRA LIMA", "2 ANO B", "u-j")])
    assert (corr["status"], corr["aluno_id"]) == ("exato", joana.id)


def test_duas_turmas_da_serie_com_relatorio_distinguivel_usa_a_logica_existente(
        db, escola_completa):
    """(C) Havendo duas turmas da série, quem decide é a sala série+letra de sempre."""
    esc = escola_completa["escola"]
    sem_letra = _turma(db, esc, "4º Ano", ano_escolar="4º Ano")
    com_letra = _turma(db, esc, "4ºB", ano_escolar="4º Ano")
    bruno = _aluno(db, esc, com_letra, "BRUNO TEIXEIRA ALVES")
    db.commit()
    [corr] = _previa(db, esc, "matific", [_matific("BRUNO TEIXEIRA ALVES", "4 ANO B", "u-b")])
    assert (corr["status"], corr["aluno_id"]) == ("exato", bruno.id)
    assert sem_letra.id != com_letra.id


def test_duas_turmas_da_serie_sem_como_distinguir_continua_em_revisao(db, escola_completa):
    """(D) Duas turmas da série e o relatório não diz qual: revisão, nunca escolher."""
    esc, admin = escola_completa["escola"], escola_completa["admin"]
    _turma(db, esc, "4º Ano", ano_escolar="4º Ano")
    _turma(db, esc, "4º Ano Tarde", ano_escolar="4º Ano")
    segundo = _turma(db, esc, "2º Ano", ano_escolar="2º Ano")
    _aluno(db, esc, segundo, "CARLA SOUZA MELO")
    db.commit()
    antes = _n_alunos(db, esc)
    linha = _matific("CARLA SOUZA MELO", "4 ANO A INTEGRAL", "u-c")
    [corr] = _previa(db, esc, "matific", [linha])
    assert corr["status"] == "revisar"
    r = _confirmar(db, esc, admin, "matific", [linha])
    assert (r.qtd_alunos, r.qtd_revisoes) == (0, 1) and _n_alunos(db, esc) == antes


def test_serie_diferente_nunca_casa_pela_turma_unica(db, escola_completa):
    """(E) O fallback resolve a SALA, não a identidade: aluno de outra série não casa."""
    esc, admin = escola_completa["escola"], escola_completa["admin"]
    _turma(db, esc, "4º Ano", ano_escolar="4º Ano")                  # única da série 4
    quinto = _turma(db, esc, "5º Ano", ano_escolar="5º Ano")
    pedro = _aluno(db, esc, quinto, "PEDRO HENRIQUE RAMOS")          # está no 5º
    db.commit()
    antes = _n_alunos(db, esc)
    linha = _matific("PEDRO HENRIQUE RAMOS", "4 ANO A INTEGRAL", "u-p")
    [corr] = _previa(db, esc, "matific", [linha])
    assert corr["status"] == "revisar" and corr["motivo"] == "homonimo_em_outra_sala"
    r = _confirmar(db, esc, admin, "matific", [linha])
    assert (r.qtd_alunos, r.qtd_revisoes) == (0, 1) and _n_alunos(db, esc) == antes
    assert _snap_matific(db, pedro.id) is None


def test_identidade_externa_continua_mandando_sobre_a_sala_reconhecida(db, escola_completa):
    """(F) UUID vinculado decide antes da sala, mesmo com a sala agora reconhecida."""
    esc = escola_completa["escola"]
    _turma(db, esc, "4º Ano", ano_escolar="4º Ano")
    quinto = _turma(db, esc, "5º Ano", ano_escolar="5º Ano")
    lia = _aluno(db, esc, quinto, "LIA MARTINS ROCHA")
    _vincular(db, esc, lia, "matific", "u-lia")
    db.commit()
    [corr] = _previa(db, esc, "matific", [_matific("LIA M", "4 ANO A INTEGRAL", "u-lia")])
    assert (corr["status"], corr["aluno_id"], corr["via"]) == ("exato", lia.id, "identidade")


def test_decisao_humana_anterior_sobrevive_ao_reconhecimento_da_sala(db, escola_completa):
    """(G) A revisão resolvida sob a sala do RELATÓRIO continua valendo depois que a
    sala passou a ser reconhecida pela série."""
    esc = escola_completa["escola"]
    quarto = _turma(db, esc, "4º Ano", ano_escolar="4º Ano")
    quinto = _turma(db, esc, "5º Ano", ano_escolar="5º Ano")
    duda = _aluno(db, esc, quinto, "EDUARDA VIEIRA")        # o gestor escolheu esta ficha
    linha_ident = ida.LinhaIdentidade(nome="DUDA V", plataforma="matific",
                                      turma_nome="4 ANO A INTEGRAL")
    db.add(RevisaoIdentidade(
        escola_id=esc.id, chave="k", chave_identidade=ida.chave_identidade(
            linha_ident, matriculas.chave_turma_norm("4 ANO A INTEGRAL")),
        plataforma="matific", nome_recebido="DUDA V", motivo="nome_casa_em_outra_sala",
        status="resolvida", aluno_escolhido_id=duda.id))
    db.commit()
    ctx = ida.carregar_contexto(db, esc.id)
    assert ctx.sala_efetiva("4|A", "4 ANO A INTEGRAL") == ida.chave_sala(quarto.nome)
    d = ida.decidir(ctx, ida.linha_de_dados("DUDA V", {}, plataforma="matific",
                                            turma_nome="4 ANO A INTEGRAL"))
    assert (d.acao, d.aluno_id, d.via) == (ida.ASSOCIAR, duda.id, "revisao")


def test_homonimos_na_turma_unica_continuam_em_revisao(db, escola_completa):
    """(H) Reconhecer a sala não enfraquece a proteção contra homônimo."""
    esc, admin = escola_completa["escola"], escola_completa["admin"]
    quarto = _turma(db, esc, "4º Ano", ano_escolar="4º Ano")
    a1 = _aluno(db, esc, quarto, "LUCAS SILVA")
    a2 = _aluno(db, esc, quarto, "LUCAS SILVA")
    db.commit()
    antes = _n_alunos(db, esc)
    linha = _matific("LUCAS SILVA", "4 ANO A INTEGRAL", "u-l")
    [corr] = _previa(db, esc, "matific", [linha])
    assert corr["status"] == "revisar"
    r = _confirmar(db, esc, admin, "matific", [linha])
    assert (r.qtd_alunos, r.qtd_revisoes) == (0, 1) and _n_alunos(db, esc) == antes
    cands = {c["aluno_id"] for c in _pendentes(db, esc)[0].candidatos}
    assert cands == {a1.id, a2.id}


def test_turma_unica_de_outra_escola_nunca_e_usada(db, escola_completa):
    """(I) O contexto é por escola: a turma única da série da vizinha não conta."""
    esc = escola_completa["escola"]
    vizinha = Escola(nome="ESCOLA VIZINHA", ano_letivo_ativo=ANO)
    db.add(vizinha)
    db.flush()
    _turma(db, vizinha, "4º Ano", ano_escolar="4º Ano")
    db.commit()
    ctx = ida.carregar_contexto(db, esc.id)
    assert ctx.sala_efetiva("4|A", "4 ANO A INTEGRAL") == "4|A"   # nada muda
    assert all(t.escola_id == esc.id for t in ctx.turmas.values())


def test_turma_arquivada_nao_serve_de_sala_unica(db, escola_completa):
    """A turma precisa estar ATIVA: uma arquivada não recebe aluno."""
    esc = escola_completa["escola"]
    t = _turma(db, esc, "4º Ano", ano_escolar="4º Ano")
    t.status = "arquivada"
    db.commit()
    ctx = ida.carregar_contexto(db, esc.id)
    assert ctx.sala_efetiva("4|A", "4 ANO A INTEGRAL") == "4|A"


def test_fase_e_ano_da_mesma_serie_nao_decidem(db, escola_completa):
    """Escola 17 real: "1ª Fase" e "1º Ano" contam ambas como série 1 → sem fallback."""
    esc = escola_completa["escola"]
    _turma(db, esc, "1ª Fase", ano_escolar="1ª Fase")
    _turma(db, esc, "1º Ano", ano_escolar="1º Ano")
    db.commit()
    ctx = ida.carregar_contexto(db, esc.id)
    assert ctx.sala_efetiva("1|A", "1 ANO A TARDE ANUAL") == "1|A"


def test_aluno_novo_nasce_na_turma_unica_da_serie(db, escola_completa):
    """Sem candidato algum, a ficha nova nasce na turma única da série — antes isso
    ia para revisão como 'turma não cadastrada' e nenhum dado entrava."""
    esc, admin = escola_completa["escola"], escola_completa["admin"]
    quarto = _turma(db, esc, "4º Ano", ano_escolar="4º Ano")
    db.commit()
    antes = _n_alunos(db, esc)
    _confirmar(db, esc, admin, "matific",
               [_matific("NOEMI CASTRO BRAGA", "4 ANO A INTEGRAL (300309347)", "u-n")])
    novo = db.execute(select(Aluno).where(Aluno.nome == "NOEMI CASTRO BRAGA")).scalar_one()
    mat = db.execute(select(Matricula).where(Matricula.aluno_id == novo.id)).scalar_one()
    assert _n_alunos(db, esc) == antes + 1 and mat.turma_id == quarto.id


def test_letras_que_se_contradizem_nao_viram_a_mesma_sala(db, escola_completa):
    """Guarda: o cadastro declara a letra ("4ºA") e o relatório declara OUTRA
    ("4 ANO B"). As duas afirmam a sala e discordam — não é a mesma turma, ainda
    que seja a única da série. Continua revisão, como hoje."""
    esc, admin = escola_completa["escola"], escola_completa["admin"]
    quarto_a = _turma(db, esc, "4ºA", ano_escolar="4º Ano")
    joao = _aluno(db, esc, quarto_a, "JOAO VITOR SANTOS")
    db.commit()
    ctx = ida.carregar_contexto(db, esc.id)
    assert ctx.sala_efetiva("4|B", "4 ANO B INTEGRAL") == "4|B"      # não reinterpreta

    antes = _n_alunos(db, esc)
    linha = _matific("JOAO VITOR SANTOS", "4 ANO B INTEGRAL", "u-jv")
    [corr] = _previa(db, esc, "matific", [linha])
    assert corr["status"] == "revisar" and corr["motivo"] == "homonimo_em_outra_sala"
    r = _confirmar(db, esc, admin, "matific", [linha])
    assert (r.qtd_alunos, r.qtd_revisoes) == (0, 1) and _n_alunos(db, esc) == antes
    assert _snap_matific(db, joao.id) is None


def test_relatorio_sem_letra_casa_com_a_turma_unica_que_tem_letra(db, escola_completa):
    """O outro lado da guarda: só o CADASTRO declara a letra ("4ºA") e o relatório
    vem sem ela ("4 ANO"). Não há contradição — é a única turma da série."""
    esc = escola_completa["escola"]
    quarto_a = _turma(db, esc, "4ºA", ano_escolar="4º Ano")
    tereza = _aluno(db, esc, quarto_a, "TEREZA BATISTA NOGUEIRA")
    db.commit()
    ctx = ida.carregar_contexto(db, esc.id)
    assert ctx.sala_efetiva(ida.chave_sala("4 ANO"), "4 ANO") == ida.chave_sala(quarto_a.nome)
    [corr] = _previa(db, esc, "matific", [_matific("TEREZA BATISTA NOGUEIRA", "4 ANO", "u-t")])
    assert (corr["status"], corr["aluno_id"]) == ("exato", tereza.id)


# ---------------------------------------------------------------------------
# RETRATO SUPERADO + ORDEM DA TRANSAÇÃO no /resolver
#
# Uma pendência guarda a linha do dia em que foi aberta. Se uma sincronização
# posterior já gravou o retrato daquele aluno, reaplicar a linha velha não
# acrescenta nada e ainda retrodata o histórico. O vínculo de identidade, esse
# sim, continua valendo sempre.
#
# E a ordem importa: aplicar PRIMEIRO, fechar DEPOIS — senão uma falha no meio
# deixa pendência fechada com dado que nunca entrou, sem caminho de volta.
# ---------------------------------------------------------------------------

def _pendencia(db, esc, *, plataforma="matific", formato="resumo", id_externo="U-1",
               nome="ALUNO PARCIAL", turma_informada="5ºA", linhas=None,
               data_referencia="2026-09-22T16:51:00+00:00", candidatos=None):
    """Insere uma pendência como o coletor a gravaria, com o contexto CONGELADO
    sob controle do teste (é a data congelada que o resolver compara)."""
    chave_ident = f"{plataforma}|id:{id_externo}"
    contexto = {"tipo": "texto", "periodo_inicio": "", "periodo_fim": ""}
    if data_referencia is not None:
        contexto["data_referencia"] = data_referencia
    rev = RevisaoIdentidade(
        escola_id=esc.id, chave=f"{chave_ident}|{formato}||",
        chave_identidade=chave_ident, plataforma=plataforma, formato=formato,
        id_externo=id_externo, nome_recebido=nome, turma_informada=turma_informada,
        motivo="nome_casa_em_outra_sala", candidatos=candidatos or [],
        linhas=linhas or [], contexto=contexto, origem="sincronizacao", status="pendente")
    db.add(rev)
    db.flush()
    db.commit()
    return rev


def _resolver(cliente, esc, rev_id, aluno_id):
    return cliente.post(
        f"/api/v1/escolas/{esc.id}/importacoes/revisoes/{rev_id}/resolver",
        json={"aluno_id": aluno_id})


def _snaps_matific(db, aluno_id):
    return db.execute(select(SnapshotMatific).where(SnapshotMatific.aluno_id == aluno_id)
                      .order_by(SnapshotMatific.id)).scalars().all()


def test_retrato_congelado_mais_antigo_nao_rebaixa_o_estado_atual(db, sala, cliente):
    """1) O congelado é de ONTEM e a sync já gravou o de HOJE: a identidade é
    resolvida, e o retrato atual fica como está."""
    esc, admin, heloisa = sala["escola"], sala["admin"], sala["heloisa"]
    # O que a sincronização de HOJE já gravou.
    _confirmar(db, esc, admin, "matific",
               [_matific("HELOISA DEL GIUDICE DE SOUZA FIDELIX", "5ºA", uuid="U-9",
                         atividades=139, estrelas=580, aluno_id=heloisa.id)])
    db.commit()
    atual = _snaps_matific(db, heloisa.id)[-1]
    assert (atual.atividades, atual.estrelas) == (139, 580)

    # A pendência congelada ONTEM, com números menores.
    rev = _pendencia(db, esc, id_externo="U-VELHO", nome="HELOISA D",
                     linhas=[{"turma_relatorio": "5ºA", "matific_uuid": "U-VELHO",
                              "atividades": 136, "estrelas": 567, "pontuacao_media": 4.17}])

    resp = _resolver(cliente, esc, rev.id, heloisa.id)
    assert resp.status_code == 200, resp.text
    db.expire_all()

    # Identidade resolvida…
    assert _dono(db, esc, "matific", "U-VELHO") == heloisa.id
    rev = db.get(RevisaoIdentidade, rev.id)
    assert rev.status == "resolvida" and rev.aluno_escolhido_id == heloisa.id
    # …e o retrato atual intacto: nenhuma linha nova, nenhum número mexido.
    snaps = _snaps_matific(db, heloisa.id)
    assert [(s.atividades, s.estrelas) for s in snaps] == [(139, 580)]
    assert resp.json()["importacoes"] == []
    # Fica auditado POR QUE não se reaplicou.
    assert rev.resolucao["dados_superados"]["motivo"] == "snapshot_mais_recente"
    assert any("superados pela sincronização" in a for a in resp.json()["avisos"])


def test_retrato_do_mesmo_dia_nao_muda_o_atual_no_lugar(db, sala, cliente):
    """2) Mesmo dia UTC: o pipeline atualizaria o retrato NO LUGAR e o valor novo
    sumiria sem deixar linha. O guarda impede isso."""
    esc, admin, taufik = sala["escola"], sala["admin"], sala["taufik"]
    _confirmar(db, esc, admin, "matific",
               [_matific("TAUFIK DE OLIVEIRA SANTOS", "5ºA", uuid="T-9",
                         atividades=200, estrelas=800, aluno_id=taufik.id)])
    db.commit()
    atual = _snaps_matific(db, taufik.id)[-1]
    hoje = atual.data_referencia.replace(hour=3, minute=0).isoformat()

    rev = _pendencia(db, esc, id_externo="T-VELHO", nome="TAUFIK D",
                     data_referencia=hoje,
                     linhas=[{"turma_relatorio": "5ºA", "matific_uuid": "T-VELHO",
                              "atividades": 10, "estrelas": 20, "pontuacao_media": 2.0}])

    assert _resolver(cliente, esc, rev.id, taufik.id).status_code == 200
    db.expire_all()
    snaps = _snaps_matific(db, taufik.id)
    assert [(s.atividades, s.estrelas) for s in snaps] == [(200, 800)]   # nada mutado
    assert db.get(RevisaoIdentidade, rev.id).resolucao["dados_superados"]["motivo"] \
        == "mesmo_dia_do_snapshot_atual"


def test_retrato_sem_data_de_referencia_nao_vira_estado_atual(db, sala, cliente):
    """3) Sem data congelada o pipeline gravaria com a data de HOJE, e o número
    velho viraria o estado atual. É o pior caso: nunca reaplicar."""
    esc, admin, mathias = sala["escola"], sala["admin"], sala["mathias"]
    _confirmar(db, esc, admin, "matific",
               [_matific("MATHIAS RICARDO RODRIGUES MARADEI", "5ºA", uuid="M-9",
                         atividades=90, estrelas=360, aluno_id=mathias.id)])
    db.commit()

    rev = _pendencia(db, esc, id_externo="M-VELHO", nome="MATHIAS R",
                     data_referencia=None,
                     linhas=[{"turma_relatorio": "5ºA", "matific_uuid": "M-VELHO",
                              "atividades": 5, "estrelas": 10, "pontuacao_media": 2.0}])

    assert _resolver(cliente, esc, rev.id, mathias.id).status_code == 200
    db.expire_all()
    assert [(s.atividades, s.estrelas) for s in _snaps_matific(db, mathias.id)] == [(90, 360)]
    assert db.get(RevisaoIdentidade, rev.id).resolucao["dados_superados"]["motivo"] \
        == "data_referencia_ausente"


def test_leituras_do_elefante_sempre_se_aplicam_e_sao_idempotentes(db, sala, cliente):
    """4) Leituras ACUMULAM: o guarda não as filtra. A que já existe não duplica,
    a que falta entra."""
    esc, admin, heitor = sala["escola"], sala["admin"], sala["heitor"]
    # Já gravado: uma leitura.
    _confirmar(db, esc, admin, "elefante", formato="leituras", linhas=[
        LinhaConfirmacao(nome="HEITOR DE SOUZA LIMA", aluno_id=heitor.id,
                         dados={"turma_relatorio": "5ºA", "livro": "O gato",
                                "nivel": "A", "data": "2026-03-02"})])
    db.commit()
    antes = db.scalar(select(func.count()).select_from(Leitura)
                      .where(Leitura.aluno_id == heitor.id))
    assert antes == 1
    # Snapshot do Elefante MAIS NOVO que a pendência — mesmo assim leituras entram.
    _confirmar(db, esc, admin, "elefante",
               [_elefante("HEITOR DE SOUZA LIMA", "5ºA", sid=7777, livros=1,
                          aluno_id=heitor.id)])
    db.commit()

    rev = _pendencia(db, esc, plataforma="elefante", formato="leituras",
                     id_externo="7777", nome="HEITOR DE SOUZA LIMA",
                     linhas=[{"turma_relatorio": "5ºA", "livro": "O gato",
                              "nivel": "A", "data": "2026-03-02",
                              "elefante_student_id": "7777"},
                             {"turma_relatorio": "5ºA", "livro": "A lua nova",
                              "nivel": "A", "data": "2026-03-03",
                              "elefante_student_id": "7777"}])

    resp = _resolver(cliente, esc, rev.id, heitor.id)
    assert resp.status_code == 200, resp.text
    db.expire_all()
    # A que faltava entrou; a repetida não duplicou.
    titulos = sorted(db.execute(select(Livro.titulo).join(
        Leitura, Leitura.livro_id == Livro.id)
        .where(Leitura.aluno_id == heitor.id)).scalars())
    assert titulos == ["A lua nova", "O gato"]
    assert db.get(RevisaoIdentidade, rev.id).resolucao.get("dados_superados") is None
    assert resp.json()["importacoes"]           # passou pelo pipeline de verdade

    # Idempotência: reaplicar o MESMO payload não cria leitura nova.
    rev2 = _pendencia(db, esc, plataforma="elefante", formato="leituras",
                      id_externo="7777", nome="HEITOR DE SOUZA LIMA",
                      linhas=list(rev.linhas))
    assert _resolver(cliente, esc, rev2.id, heitor.id).status_code == 200
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Leitura)
                     .where(Leitura.aluno_id == heitor.id)) == 2


def test_irmas_da_mesma_chave_sao_fechadas_so_depois_de_todas_aplicadas(db, sala, cliente):
    """5) Resumo + leituras da MESMA identidade: as duas se aplicam, e o
    fechamento acontece depois."""
    esc, maria = sala["escola"], sala["maria"]
    linhas_resumo = [{"turma_relatorio": "5ºA", "elefante_student_id": "8888",
                      "livros_unicos": 9, "tempo_leitura_min": 45,
                      "questoes_tentativas": 6, "questoes_acertos": 5}]
    rev_a = _pendencia(db, esc, plataforma="elefante", formato="resumo",
                       id_externo="8888", nome="MARIA CLARA SOUZA",
                       linhas=linhas_resumo)
    rev_b = _pendencia(db, esc, plataforma="elefante", formato="leituras",
                       id_externo="8888", nome="MARIA CLARA SOUZA",
                       linhas=[{"turma_relatorio": "5ºA", "livro": "O sol",
                                "nivel": "A", "data": "2026-03-04",
                                "elefante_student_id": "8888"}])

    resp = _resolver(cliente, esc, rev_a.id, maria.id)
    assert resp.status_code == 200, resp.text
    assert sorted(resp.json()["revisoes_resolvidas"]) == sorted([rev_a.id, rev_b.id])
    db.expire_all()
    for r in (rev_a, rev_b):
        atual = db.get(RevisaoIdentidade, r.id)
        assert atual.status == "resolvida" and atual.aluno_escolhido_id == maria.id
    # As duas aplicações aconteceram: snapshot do resumo e a leitura.
    assert _snap_elefante(db, maria.id).livros_unicos >= 1
    assert db.scalar(select(func.count()).select_from(Leitura)
                     .where(Leitura.aluno_id == maria.id)) == 1
    assert len(resp.json()["importacoes"]) == 2


def test_falha_no_meio_faz_rollback_de_tudo(db, sala, cliente, monkeypatch):
    """6) A 2ª aplicação falha: ROLLBACK completo. Nada da 1ª fica gravado,
    nenhuma irmã fecha, a identidade não é vinculada, a auditoria não sobra —
    e a nova tentativa conclui sem ninguém mexer no banco."""
    esc, joao = sala["escola"], sala["joao"]
    rev_a = _pendencia(db, esc, plataforma="elefante", formato="resumo",
                       id_externo="9999", nome="JOÃO VÍTOR ARAÚJO",
                       linhas=[{"turma_relatorio": "5ºA", "elefante_student_id": "9999",
                                "livros_unicos": 4, "tempo_leitura_min": 20,
                                "questoes_tentativas": 3, "questoes_acertos": 2}])
    rev_b = _pendencia(db, esc, plataforma="elefante", formato="leituras",
                       id_externo="9999", nome="JOÃO VÍTOR ARAÚJO",
                       linhas=[{"turma_relatorio": "5ºA", "livro": "A chuva",
                                "nivel": "A", "data": "2026-03-05",
                                "elefante_student_id": "9999"}])
    logs_antes = db.scalar(select(func.count()).select_from(LogAuditoria))

    # A falha entra pelo NÚCLEO sem commit — é ele que o resolver chama agora.
    real = imp._confirmar_sem_commit
    chamadas = {"n": 0}

    def nucleo_que_falha_na_segunda(**kw):
        chamadas["n"] += 1
        if chamadas["n"] == 2:
            raise RuntimeError("falha simulada na 2ª aplicação")
        return real(**kw)

    monkeypatch.setattr(imp, "_confirmar_sem_commit", nucleo_que_falha_na_segunda)
    assert _resolver(cliente, esc, rev_a.id, joao.id).status_code >= 500
    monkeypatch.undo()
    assert chamadas["n"] == 2                      # a 1ª rodou, a 2ª estourou

    # Descarta o que ficou na sessão: o que sobreviver aqui é o que foi COMMITADO.
    db.rollback()
    db.expire_all()

    # 1+2) nenhuma das duas aplicações ficou persistida
    assert _snap_elefante(db, joao.id) is None
    assert db.scalar(select(func.count()).select_from(Leitura)
                     .where(Leitura.aluno_id == joao.id)) == 0
    # 3) nenhuma irmã fechada
    for r in (rev_a, rev_b):
        atual = db.get(RevisaoIdentidade, r.id)
        assert atual.status == "pendente", f"revisão {r.id} não devia ter fechado"
        assert atual.aluno_escolhido_id is None and atual.resolvida_em is None
    # 4) identidade não ficou vinculada nem pela metade
    assert _dono(db, esc, "elefante", "9999") is None
    # 5) auditoria não sobrou: nenhum log novo foi commitado
    assert db.scalar(select(func.count()).select_from(LogAuditoria)) == logs_antes

    # 6) nova tentativa conclui normalmente
    resp = _resolver(cliente, esc, rev_a.id, joao.id)
    assert resp.status_code == 200, resp.text
    db.expire_all()
    assert db.get(RevisaoIdentidade, rev_b.id).status == "resolvida"
    assert _dono(db, esc, "elefante", "9999") == joao.id
    assert _snap_elefante(db, joao.id) is not None
    assert db.scalar(select(func.count()).select_from(Leitura)
                     .where(Leitura.aluno_id == joao.id)) == 1


def test_duas_irmas_aplicam_e_fecham_num_unico_commit(db, sala, cliente, monkeypatch):
    """Sucesso: duas irmãs aplicadas, scoring executado, as duas resolvidas — e
    UM único commit no fluxo inteiro."""
    esc, heitor = sala["escola"], sala["heitor"]
    rev_a = _pendencia(db, esc, plataforma="elefante", formato="resumo",
                       id_externo="4242", nome="HEITOR DE SOUZA LIMA",
                       linhas=[{"turma_relatorio": "5ºA", "elefante_student_id": "4242",
                                "livros_unicos": 6, "tempo_leitura_min": 30,
                                "questoes_tentativas": 4, "questoes_acertos": 3}])
    rev_b = _pendencia(db, esc, plataforma="elefante", formato="leituras",
                       id_externo="4242", nome="HEITOR DE SOUZA LIMA",
                       linhas=[{"turma_relatorio": "5ºA", "livro": "O vento",
                                "nivel": "A", "data": "2026-03-06",
                                "elefante_student_id": "4242"}])

    # A rota roda numa sessão PRÓPRIA (conftest `_get_db`), então contar commits
    # tem de ser por evento do SQLAlchemy, não pelo objeto `db` do teste.
    commits = {"n": 0}

    def contar_commit(_sessao):
        commits["n"] += 1

    recalculos = {"n": 0}
    recalcular_real = scoring.recalcular_escola

    def contar_recalculo(*a, **kw):
        recalculos["n"] += 1
        return recalcular_real(*a, **kw)

    monkeypatch.setattr(scoring, "recalcular_escola", contar_recalculo)
    event.listen(SASession, "after_commit", contar_commit)
    try:
        resp = _resolver(cliente, esc, rev_a.id, heitor.id)
    finally:
        event.remove(SASession, "after_commit", contar_commit)
    monkeypatch.undo()

    assert resp.status_code == 200, resp.text
    assert sorted(resp.json()["revisoes_resolvidas"]) == sorted([rev_a.id, rev_b.id])
    assert len(resp.json()["importacoes"]) == 2          # as DUAS aplicadas
    assert commits["n"] == 1, f"esperado 1 commit, houve {commits['n']}"
    assert recalculos["n"] == 1                          # scoring rodou, uma vez
    db.expire_all()
    for r in (rev_a, rev_b):
        assert db.get(RevisaoIdentidade, r.id).status == "resolvida"
    assert _dono(db, esc, "elefante", "4242") == heitor.id
    assert _snap_elefante(db, heitor.id) is not None
    assert db.scalar(select(func.count()).select_from(Leitura)
                     .where(Leitura.aluno_id == heitor.id)) == 1


def test_identidade_vale_mesmo_quando_o_retrato_e_superado(db, sala, cliente):
    """7) O gestor decidiu QUEM é — a identidade fica vinculada à ficha escolhida
    e o número velho NÃO volta: nenhum snapshot nasce do payload superado.

    ATUALIZADO (colisão de identidades): resolver esta pendência deixa a ficha com
    DUAS contas Matific, e a partir daí a próxima sincronização NÃO associa
    sozinha — ela abre revisão. O gestor decidiu QUEM é a criança; ninguém decidiu
    QUAIS números valem, e aplicar um dos dois sobrescreveria o outro em silêncio.
    Era exatamente assim que a ficha da Allyce (139 atividades × 3) perdia dado."""
    esc, admin, heloisa = sala["escola"], sala["admin"], sala["heloisa"]
    _confirmar(db, esc, admin, "matific",
               [_matific("HELOISA DEL GIUDICE DE SOUZA FIDELIX", "5ºA", uuid="H-NOVO",
                         atividades=150, estrelas=600, aluno_id=heloisa.id)])
    db.commit()
    snaps_antes = len(_snaps_matific(db, heloisa.id))

    rev = _pendencia(db, esc, id_externo="H-VELHO", nome="HELOISA D",
                     linhas=[{"turma_relatorio": "5ºA", "matific_uuid": "H-VELHO",
                              "atividades": 1, "estrelas": 2, "pontuacao_media": 2.0}])
    assert _resolver(cliente, esc, rev.id, heloisa.id).status_code == 200
    db.expire_all()

    # NENHUM snapshot nasceu do payload superado.
    assert len(_snaps_matific(db, heloisa.id)) == snaps_antes
    assert _snaps_matific(db, heloisa.id)[-1].atividades == 150

    # A identidade decidida VALE — o motor sabe de quem ela é (aluno_id certo,
    # via "identidade", nenhum candidato inventado) — mas não aplica sozinha,
    # porque a ficha ficou com duas contas da mesma plataforma.
    ctx = ida.carregar_contexto(db, esc.id, ANO)
    assert ctx.identidade[("matific", "H-VELHO")] == heloisa.id
    d = ida.decidir(ctx, ida.LinhaIdentidade(nome="HELOISA D", plataforma="matific",
                                             id_externo="H-VELHO", turma_nome="5ºA"))
    assert d.acao == ida.REVISAR and d.aluno_id == heloisa.id and d.via == "identidade"
    assert d.motivo == "outra_identidade_na_plataforma"
    # A conta com UMA identidade só segue associando normalmente.
    d_ok = ida.decidir(ctx, ida.LinhaIdentidade(nome="TAUFIK DE OLIVEIRA SANTOS",
                                                plataforma="matific",
                                                turma_nome="5ºA"))
    assert d_ok.acao in (ida.ASSOCIAR, ida.REVISAR)   # não é afetada pela colisão
    assert d_ok.motivo != "outra_identidade_na_plataforma"
    # E a decisão fica marcada como "dados superados", para auditoria distinguir.
    assert db.get(RevisaoIdentidade, rev.id).resolucao["dados_superados"]["motivo"]
