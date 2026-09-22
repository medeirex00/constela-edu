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
from sqlalchemy import func, select

from app.models import (
    Aluno,
    IdentidadeExterna,
    LogAuditoria,
    Matricula,
    RevisaoIdentidade,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
)
from app.routers import importacoes as imp
from app.schemas.importacao import ImportacaoConfirm, LinhaConfirmacao
from app.services import identidade_aluno as ida
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
