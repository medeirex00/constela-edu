"""Revisão de identidade JÁ RESPONDIDA é encerrada pela própria importação (2026-10-07).

Antes: quando a sincronização/importação passava a ASSOCIAR uma linha — porque o
matching ficou mais capaz, porque a duplicata foi excluída, porque a ficha foi
reativada —, a revisão PENDENTE daquela mesma identidade continuava "pendente"
para sempre: só o /resolver e o /descartar mudam o status. A fila acumulava
perguntas que a confirmação já tinha respondido.

Agora (``routers.importacoes._encerrar_revisoes_respondidas``):
  * ao ASSOCIAR, a pendência da MESMA ``chave_identidade`` e do MESMO tipo de dado
    (a que esta linha substitui) vira "resolvida" — pelo SISTEMA na sincronização
    (``resolvida_por_id`` None, ``resolucao.automatica``, via, regra, preteridos;
    auditoria ``revisao.encerrada_automaticamente``) ou por QUEM CONFIRMOU quando a
    ficha foi fixada na tela (auditoria ``identidade.revisao_resolvida``);
  * a irmã de OUTRO tipo (leituras numa importação de resumo), o retrato congelado
    MAIS NOVO que o arquivo, as leituras de um arquivo manual (pode ser parcial) e
    a conta CONTESTADA (``identidade_de_outro_aluno``) continuam pendentes — nada
    que só a pendência guardava se perde;
  * a escolha automática vale em ``ctx.resolvidas`` só na importação que a fez:
    não volta como "decisão humana" (a guarda de ficha inativa continua valendo);
  * a PRÉVIA não encerra nada; REVISAR e CRIAR não encerram; o /resolver do gestor
    não vira "encerramento automático";
  * as pendências são lidas UMA vez por importação (não uma consulta por linha).

E o rastro do desempate "oficial × duplicata" em ``aluno.vinculado_auto`` diz
quantos candidatos havia e quem ficou de fora, em vez de "1 candidato".

Nomes FICTÍCIOS (conferidos contra o backup de produção: nenhum bate).
"""
import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import event, func, select

from app.models import (
    Aluno,
    IdentidadeExterna,
    Leitura,
    Livro,
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
from app.sync import orchestrator
from app.sync.interfaces import ArquivoObtido, Contexto

ANO = 2026
SALA = "2 ANO B TARDE ANUAL"                 # como o Elefante escreve a turma
SALA_MATIFIC = "2 ANO B TARDE (300399001)"   # como o Matific escreve
ACAO_AUTO = "revisao.encerrada_automaticamente"
ACAO_HUMANA = "identidade.revisao_resolvida"
DATA_CONGELADA = "2025-09-22T10:00:00+00:00"  # sempre anterior a "agora"


# --- montagem ------------------------------------------------------------------

def _turma(db, escola, nome, ano_escolar, codigo=None):
    t = Turma(escola_id=escola.id, nome=nome, ano_escolar=ano_escolar, ano_letivo=ANO,
              codigo_externo=codigo)
    db.add(t)
    db.flush()
    return t


def _aluno(db, escola, turma, nome, *, lp=True, status="ativo", chamada=None):
    a = Aluno(escola_id=escola.id, nome=nome, status=status, numero_chamada=chamada,
              da_lista_piloto=lp)
    db.add(a)
    db.flush()
    if turma is not None:
        db.add(Matricula(escola_id=escola.id, aluno_id=a.id, turma_id=turma.id,
                         ano_letivo=ANO))
        db.flush()
    return a


def _conta(db, escola, aluno, plataforma, id_externo):
    db.add(IdentidadeExterna(escola_id=escola.id, aluno_id=aluno.id, plataforma=plataforma,
                             id_externo=id_externo))
    db.flush()


def _pendencia(db, esc, *, chave_ident, formato="resumo", plataforma="elefante",
               id_externo=None, nome="", motivo="candidatos_multiplos", candidatos=(),
               linhas=None, data_referencia=DATA_CONGELADA, origem="sincronizacao"):
    """Pendência como o coletor a grava (o teste controla o conteúdo congelado)."""
    rev = RevisaoIdentidade(
        escola_id=esc.id, chave=ida.chave_pendencia(chave_ident, formato),
        chave_identidade=chave_ident, plataforma=plataforma, formato=formato,
        id_externo=id_externo, nome_recebido=nome, turma_informada=SALA, motivo=motivo,
        candidatos=[{"aluno_id": a.id, "nome": a.nome} for a in candidatos],
        linhas=linhas if linhas is not None else [{"livros_unicos": 3}],
        contexto={"tipo": "texto", "data_referencia": data_referencia,
                  "periodo_inicio": "", "periodo_fim": ""},
        origem=origem, status="pendente")
    db.add(rev)
    db.commit()
    return rev


def _revisoes(db, esc):
    db.expire_all()
    return db.execute(select(RevisaoIdentidade).where(RevisaoIdentidade.escola_id == esc.id)
                      .order_by(RevisaoIdentidade.id)).scalars().all()


def _pendentes(db, esc):
    return [r for r in _revisoes(db, esc) if r.status == "pendente"]


def _logs(db, acao):
    return db.execute(select(LogAuditoria).where(LogAuditoria.acao == acao)
                      .order_by(LogAuditoria.id)).scalars().all()


def _n_alunos(db, esc):
    return db.execute(select(func.count()).select_from(Aluno)
                      .where(Aluno.escola_id == esc.id)).scalar_one()


def _titulos(db, aluno_id):
    db.expire_all()
    return sorted(db.execute(select(Livro.titulo).join(Leitura, Leitura.livro_id == Livro.id)
                             .where(Leitura.aluno_id == aluno_id)).scalars())


def _n_snapshots(db, aluno_id):
    return db.execute(select(func.count()).select_from(SnapshotElefante)
                      .where(SnapshotElefante.aluno_id == aluno_id)).scalar_one()


def _elefante(nome, sid=None, livros=7, turma=SALA, aluno_id=None):
    dados = {"turma_relatorio": turma, "livros_unicos": livros, "tempo_leitura_min": 40,
             "questoes_tentativas": 5, "questoes_acertos": 4}
    if sid is not None:
        dados["elefante_student_id"] = str(sid)
    return LinhaConfirmacao(nome=nome, dados=dados, criar_em_turma_nome=turma,
                            aluno_id=aluno_id)


def _livro(nome, sid, titulo, data="2025-09-01"):
    dados = {"turma_relatorio": SALA, "livro": titulo, "nivel": "A", "data": data,
             "elefante_student_id": str(sid)}
    return LinhaConfirmacao(nome=nome, dados=dados, criar_em_turma_nome=SALA)


def _matific(nome, uuid, turma=SALA_MATIFIC, aluno_id=None):
    dados = {"turma_relatorio": turma, "estrelas": 120, "atividades": 30,
             "pontuacao_media": 4.0, "matific_uuid": uuid}
    return LinhaConfirmacao(nome=nome, dados=dados, criar_em_turma_nome=turma,
                            aluno_id=aluno_id)


def _confirmar(db, esc, admin, plataforma, linhas, **kw):
    # Como um arquivo COM a data do relatório (o de hoje). Sem data, o encerramento
    # não trata retrato de outro dia — ver test_arquivo_sem_data_nao_encerra_retrato.
    if kw.pop("sem_data", False) is False:
        kw.setdefault("data_referencia", datetime.now(timezone.utc))
    conf = ImportacaoConfirm(plataforma=plataforma, formato=kw.pop("formato", "resumo"),
                             tipo="texto", linhas=linhas, recalcular=False, **kw)
    return imp.confirmar(dados=conf, escola_id=esc.id, usuario=admin, db=db)


def _previa(db, esc, plataforma, linhas):
    brutas = [svc.LinhaImportacao(numero=i, nome=l.nome, dados=dict(l.dados))
              for i, l in enumerate(linhas, start=1)]
    svc.casar_nomes(db, esc.id, brutas, plataforma=plataforma)
    return [l.correspondencia for l in brutas]


def _aplicar_sync(db, esc, monkeypatch, payload, formato):
    """O orquestrador REAL da sincronização (o caminho de produção)."""
    monkeypatch.setattr(orchestrator.imp, "_guardar_temporario", lambda *a, **k: None)
    return orchestrator.aplicar_arquivo(
        db, esc, ArquivoObtido(conteudo=json.dumps(payload).encode("utf-8"),
                               nome_arquivo="e.json", plataforma="elefante",
                               content_type=orchestrator.CT_ELEFANTE_API,
                               formato_hint=formato),
        usuario_id=None, recalcular=False,
        contexto=Contexto(escola_id=esc.id, execucao_id=None, log=lambda *a: None))


def _sincronizar_elefante(db, esc, monkeypatch, alunos):
    """Coleta diária: o RESUMO da turma (``students``)."""
    return _aplicar_sync(db, esc, monkeypatch, {
        "courseSchoolDescriptors": {"courseName": SALA},
        "students": [{"studentId": sid, "studentName": nome, "totalBooksRead": 9}
                     for sid, nome in alunos]}, "resumo")


def _sincronizar_leituras(db, esc, monkeypatch, livros):
    """Os livros de quem MUDOU (ou de todos, na coleta completa): a lista LIFETIME
    de cada criança — ``livros`` = [(studentId, nome, título, data)]."""
    return _aplicar_sync(db, esc, monkeypatch, {
        "courseSchoolDescriptors": {"courseName": SALA},
        "leituras": [{"nome": nome, "studentId": sid, "bookTitle": titulo,
                      "levelName": "A", "lastReadWhen": data}
                     for sid, nome, titulo, data in livros]}, "leituras")


@pytest.fixture()
def sala(db, escola_completa):
    esc = escola_completa["escola"]
    b = _turma(db, esc, "2º Ano B", "2º Ano", codigo="300399001")
    db.commit()
    return {"escola": esc, "admin": escola_completa["admin"], "b": b}


@pytest.fixture()
def oficial_e_stub(db, sala):
    """Ficha OFICIAL da Lista Piloto + o stub abreviado que o Matific criou ao lado
    dela (com a conta Matific dele). O Elefante manda o nome completo com um typo
    no meio: antes era revisão "candidatos_multiplos" a cada sincronização."""
    esc = sala["escola"]
    oficial = _aluno(db, esc, sala["b"], "GIOVANA ESTER MENDONCA RAMOS", chamada=7)
    stub = _aluno(db, esc, sala["b"], "GIOVANA E", lp=False)
    _conta(db, esc, stub, "matific", "u-stub-giovana")
    _aluno(db, esc, sala["b"], "PRISCILA NUNES TAVARES")       # colega sem relação
    db.commit()
    return {**sala, "oficial": oficial, "stub": stub}


SID_GIOVANA = 4410001
NOME_ELEFANTE_GIOVANA = "GIOVANA ESTER MENDONSA RAMOS"       # typo no nome do meio
CHAVE_GIOVANA = f"elefante|id:{SID_GIOVANA}"
REGRA_DESEMPATE = ("única ficha da Lista Piloto compatível; as demais são "
                   "duplicatas dela (mesmo nome ou abreviado), fora da Lista Piloto")


def _irmas_giovana(db, c):
    """As duas pendências que a sincronização antiga deixou: resumo e leituras."""
    cands = (c["oficial"], c["stub"])
    resumo = _pendencia(db, c["escola"], chave_ident=CHAVE_GIOVANA, formato="resumo",
                        id_externo=str(SID_GIOVANA), nome=NOME_ELEFANTE_GIOVANA,
                        candidatos=cands,
                        linhas=[{"turma_relatorio": SALA, "livros_unicos": 3,
                                 "elefante_student_id": str(SID_GIOVANA)}])
    leituras = _pendencia(db, c["escola"], chave_ident=CHAVE_GIOVANA, formato="leituras",
                          id_externo=str(SID_GIOVANA), nome=NOME_ELEFANTE_GIOVANA,
                          candidatos=cands,
                          linhas=[{"turma_relatorio": SALA, "livro": "O barco",
                                   "nivel": "A", "data": "2025-09-01",
                                   "elefante_student_id": str(SID_GIOVANA)}])
    return resumo, leituras


def _superados(rev, formato):
    """``dados_superados`` gravado no encerramento (a data desta importação é
    "agora" — conferida à parte)."""
    d = dict(rev.resolucao["dados_superados"])
    agora = datetime.fromisoformat(d.pop("data_desta_importacao"))
    assert agora.date() >= datetime.fromisoformat(DATA_CONGELADA).date()
    assert d == {"motivo": "substituidos_pela_linha_desta_importacao", "formato": formato,
                 "plataforma": "elefante", "data_congelada": DATA_CONGELADA}
    return True


# --- 1. a sincronização encerra cada irmã com a linha do tipo dela ---------------

def test_sincronizacao_encerra_cada_irma_com_a_linha_do_tipo_dela(
        db, oficial_e_stub, monkeypatch):
    c = oficial_e_stub
    esc, oficial, stub = c["escola"], c["oficial"], c["stub"]
    resumo, leituras = _irmas_giovana(db, c)
    antes = _n_alunos(db, esc)

    # 1) Coleta diária (RESUMO): encerra a pendência de resumo. A de LEITURAS
    # guarda livros que este arquivo não traz → continua pendente, intacta.
    res = _sincronizar_elefante(db, esc, monkeypatch, [(SID_GIOVANA, NOME_ELEFANTE_GIOVANA)])
    revs = {r.id: r for r in _revisoes(db, esc)}
    assert set(revs) == {resumo.id, leituras.id}          # nenhuma pendência nova
    r = revs[resumo.id]
    assert (r.status, r.aluno_escolhido_id, r.resolvida_por_id) == (
        "resolvida", oficial.id, None)                    # sistema, ninguém clicou
    assert r.resolvida_em is not None
    imp1 = res["importacao_id"]
    assert {k: v for k, v in r.resolucao.items() if k != "dados_superados"} == {
        "acao": "associar", "aluno_id": oficial.id, "automatica": True,
        "via": "lista_piloto_unica", "regra": REGRA_DESEMPATE,
        "preteridos": [{"aluno_id": stub.id, "nome": "GIOVANA E"}],
        "importacao_id": imp1,
    }
    assert _superados(r, "resumo")
    pend = revs[leituras.id]
    assert pend.status == "pendente" and pend.resolucao is None
    assert pend.linhas[0]["livro"] == "O barco"           # o congelado continua lá
    assert any("Continuam na fila 1 pendência(s) dela (leituras)" in a
               for a in res["avisos"])

    # 2) Os livros da criança (lista LIFETIME do conector): encerra a de leituras —
    # e o livro que só a pendência guardava chega pela própria linha.
    res2 = _sincronizar_leituras(db, esc, monkeypatch, [
        (SID_GIOVANA, NOME_ELEFANTE_GIOVANA, "O barco", "2025-09-01T10:00:00"),
        (SID_GIOVANA, NOME_ELEFANTE_GIOVANA, "A ponte", "2025-09-20T10:00:00")])
    r2 = db.get(RevisaoIdentidade, leituras.id)
    assert (r2.status, r2.aluno_escolhido_id, r2.resolvida_por_id) == (
        "resolvida", oficial.id, None)
    # A conta já foi gravada na ficha pela 1ª coleta: agora casa pela identidade.
    assert {k: v for k, v in r2.resolucao.items() if k != "dados_superados"} == {
        "acao": "associar", "aluno_id": oficial.id, "automatica": True,
        "via": "identidade", "regra": "vínculo pela conta da plataforma",
        "importacao_id": res2["importacao_id"],
    }
    assert _superados(r2, "leituras")
    assert _titulos(db, oficial.id) == ["A ponte", "O barco"]

    # Uma auditoria por pendência encerrada, com o rastro completo.
    logs = _logs(db, ACAO_AUTO)
    assert [l.detalhes["revisao_id"] for l in logs] == [resumo.id, leituras.id]
    d = logs[0].detalhes
    assert logs[0].entidade == "aluno" and logs[0].entidade_id == oficial.id
    assert logs[0].usuario_id == c["admin"].id            # o ator da sincronização
    assert d["via"] == "lista_piloto_unica" and d["aluno"] == oficial.nome
    assert d["preteridos"] == [{"aluno_id": stub.id, "nome": "GIOVANA E"}]
    assert d["motivo"] == "candidatos_multiplos"          # o motivo ORIGINAL da pendência
    assert d["candidatos"] == [oficial.id, stub.id]
    assert d["importacao_id"] == imp1
    assert d["dados_superados"]["formato"] == "resumo"
    assert _logs(db, ACAO_HUMANA) == []
    # Nada criado, nada fundido.
    assert _n_alunos(db, esc) == antes
    assert db.get(Aluno, stub.id).status == "ativo"

    # As coletas seguintes não reabrem nada.
    _sincronizar_elefante(db, esc, monkeypatch, [(SID_GIOVANA, NOME_ELEFANTE_GIOVANA)])
    _sincronizar_leituras(db, esc, monkeypatch, [
        (SID_GIOVANA, NOME_ELEFANTE_GIOVANA, "O barco", "2025-09-01T10:00:00")])
    assert _pendentes(db, esc) == [] and len(_logs(db, ACAO_AUTO)) == 2


def test_so_o_resumo_chega_e_os_livros_da_irma_ficam_para_o_gestor(
        db, oficial_e_stub, monkeypatch, cliente):
    """O caso real do backup (05/10): o cursor incremental já tinha o total de
    livros dessas crianças, então a coleta diária traz SÓ o resumo delas. A irmã
    de leituras não pode ser encerrada ali — os livros dela não viriam."""
    c = oficial_e_stub
    esc, oficial = c["escola"], c["oficial"]
    resumo, leituras = _irmas_giovana(db, c)
    _sincronizar_elefante(db, esc, monkeypatch, [(SID_GIOVANA, NOME_ELEFANTE_GIOVANA)])
    assert [r.id for r in _pendentes(db, esc)] == [leituras.id]
    assert _titulos(db, oficial.id) == []

    # O gestor resolve a que ficou: o /resolver aplica os livros guardados.
    resp = cliente.post(
        f"/api/v1/escolas/{esc.id}/importacoes/revisoes/{leituras.id}/resolver",
        json={"aluno_id": oficial.id})
    assert resp.status_code == 200, resp.text
    assert _titulos(db, oficial.id) == ["O barco"]
    assert _pendentes(db, esc) == []


def test_dados_congelados_da_pendencia_nao_sao_aplicados(db, oficial_e_stub):
    """Encerrar NÃO reaplica a linha congelada: o retrato que vale é o desta
    confirmação (mais novo), que substitui o guardado."""
    c = oficial_e_stub
    esc, oficial = c["escola"], c["oficial"]
    _pendencia(db, esc, chave_ident=CHAVE_GIOVANA, id_externo=str(SID_GIOVANA),
               nome=NOME_ELEFANTE_GIOVANA, candidatos=(oficial, c["stub"]),
               linhas=[{"turma_relatorio": SALA, "livros_unicos": 2,
                        "elefante_student_id": str(SID_GIOVANA)}])
    r = _confirmar(db, esc, c["admin"], "elefante",
                   [_elefante(NOME_ELEFANTE_GIOVANA, SID_GIOVANA, livros=11)])
    assert _pendentes(db, esc) == []
    snaps = db.execute(select(SnapshotElefante).where(
        SnapshotElefante.aluno_id == oficial.id)).scalars().all()
    assert [s.livros_unicos for s in snaps] == [11]      # só o vigente; o congelado (2) não
    assert any("encerradas automaticamente" in a and "substitui o que elas guardavam" in a
               for a in r.avisos)


def test_retrato_congelado_mais_novo_que_o_arquivo_fica_pendente(db, oficial_e_stub):
    """Relatório ANTIGO importado à mão: o retrato da pendência é de um dia
    posterior — ele é o mais novo, e encerrar o descartaria. Fica para o
    /resolver (que o aplicaria). Um arquivo de hoje o substitui e encerra."""
    c = oficial_e_stub
    esc, oficial = c["escola"], c["oficial"]
    rev = _pendencia(db, esc, chave_ident=CHAVE_GIOVANA, id_externo=str(SID_GIOVANA),
                     nome=NOME_ELEFANTE_GIOVANA, candidatos=(oficial, c["stub"]))
    _confirmar(db, esc, c["admin"], "elefante",
               [_elefante(NOME_ELEFANTE_GIOVANA, SID_GIOVANA, livros=1)],
               data_referencia=datetime(2025, 9, 1, tzinfo=timezone.utc))
    assert [r.id for r in _pendentes(db, esc)] == [rev.id]
    assert _logs(db, ACAO_AUTO) == []

    _confirmar(db, esc, c["admin"], "elefante",
               [_elefante(NOME_ELEFANTE_GIOVANA, SID_GIOVANA, livros=12)])
    assert _pendentes(db, esc) == [] and len(_logs(db, ACAO_AUTO)) == 1


def test_arquivo_manual_de_leituras_nao_encerra_a_pendencia_de_leituras(db, oficial_e_stub):
    """Um arquivo de leituras feito à mão pode trazer só parte dos livros: os que
    só a pendência guardava se perderiam. Só a sincronização (lista LIFETIME)
    encerra leituras; o arquivo manual aplica o que traz e a pendência fica."""
    c = oficial_e_stub
    esc, oficial = c["escola"], c["oficial"]
    resumo, leituras = _irmas_giovana(db, c)
    _confirmar(db, esc, c["admin"], "elefante",
               [_livro(NOME_ELEFANTE_GIOVANA, SID_GIOVANA, "A ponte")], formato="leituras")
    assert _titulos(db, oficial.id) == ["A ponte"]        # a linha foi aplicada
    assert [r.id for r in _pendentes(db, esc)] == [resumo.id, leituras.id]
    assert _logs(db, ACAO_AUTO) == [] and _logs(db, ACAO_HUMANA) == []


# --- 2. a prévia não encerra ----------------------------------------------------

def test_previa_nao_encerra_so_a_confirmacao(db, oficial_e_stub):
    c = oficial_e_stub
    esc, oficial = c["escola"], c["oficial"]
    resumo, leituras = _irmas_giovana(db, c)
    linha = _elefante(NOME_ELEFANTE_GIOVANA, SID_GIOVANA)

    [corr] = _previa(db, esc, "elefante", [linha])
    db.commit()
    assert (corr["status"], corr["aluno_id"]) == ("vinculado", oficial.id)
    assert [r.id for r in _pendentes(db, esc)] == [resumo.id, leituras.id]
    assert _logs(db, ACAO_AUTO) == []

    _confirmar(db, esc, c["admin"], "elefante", [linha])
    assert [r.id for r in _pendentes(db, esc)] == [leituras.id]   # só a do resumo
    assert [l.detalhes["revisao_id"] for l in _logs(db, ACAO_AUTO)] == [resumo.id]


# --- 3. só ASSOCIAR encerra — e não toda associação --------------------------------

def test_decisao_revisar_mantem_a_pendencia(db, sala):
    """Duas fichas da Lista Piloto servem para "TALITA R": ambiguidade real."""
    esc = sala["escola"]
    _aluno(db, esc, sala["b"], "TALITA REGINA FONTES")
    _aluno(db, esc, sala["b"], "TALITA ROCHA FARIAS")
    db.commit()
    linha = _matific("TALITA R", "u-talita")
    _confirmar(db, esc, sala["admin"], "matific", [linha])
    [rev] = _pendentes(db, esc)
    assert rev.motivo == "candidatos_multiplos" and rev.ocorrencias == 1

    _confirmar(db, esc, sala["admin"], "matific", [linha])
    [rev2] = _pendentes(db, esc)
    assert rev2.id == rev.id and rev2.ocorrencias == 2   # continua pendente, atualizada
    assert rev2.resolvida_em is None and rev2.resolucao is None
    assert _logs(db, ACAO_AUTO) == []


def test_conta_contestada_nao_e_encerrada_pela_mesma_conta(db, sala):
    """Quem confirmou disse que a linha da conta U é de BRUNA, mas U está na ficha
    de BEATRIZ: revisão "identidade_de_outro_aluno". A sincronização seguinte casa
    por essa MESMA conta (BEATRIZ) — só repete o estado contestado. A pendência
    fica para o /resolver (o único que transfere a conta) e não vira memória."""
    esc = sala["escola"]
    beatriz = _aluno(db, esc, sala["b"], "BEATRIZ HELENA CAMPOS")
    bruna = _aluno(db, esc, sala["b"], "BRUNA HELENA CAMPOS")
    _conta(db, esc, beatriz, "matific", "u-disputada")
    db.commit()
    _confirmar(db, esc, sala["admin"], "matific",
               [_matific("BRUNA HELENA CAMPOS", "u-disputada", aluno_id=bruna.id)])
    [rev] = _pendentes(db, esc)
    assert rev.motivo == "identidade_de_outro_aluno"

    for _ in range(2):                                    # a sync diária, duas vezes
        _confirmar(db, esc, sala["admin"], "matific",
                   [_matific("BRUNA HELENA CAMPOS", "u-disputada")])
    [r] = _revisoes(db, esc)
    assert (r.id, r.status, r.ocorrencias) == (rev.id, "pendente", 1)
    assert r.resolucao is None and r.aluno_escolhido_id is None
    assert r.linhas and r.linhas[0]["matific_uuid"] == "u-disputada"   # linha intacta
    assert _logs(db, ACAO_AUTO) == [] and _logs(db, ACAO_HUMANA) == []
    assert rev.chave_identidade not in ida.carregar_contexto(db, esc.id).resolvidas


def test_criar_nao_encerra_mas_a_associacao_seguinte_sim(db, sala):
    """CRIAR não responde a pergunta "de quem é" — só a próxima linha que ASSOCIA
    (agora pela conta gravada na ficha nova) encerra a pendência."""
    esc = sala["escola"]
    chave = "elefante|id:4410555"
    rev = _pendencia(db, esc, chave_ident=chave, id_externo="4410555",
                     nome="NAIARA QUINTELA BORGES", motivo="criacao_bloqueada_por_politica")
    antes = _n_alunos(db, esc)
    _confirmar(db, esc, sala["admin"], "elefante",
               [_elefante("NAIARA QUINTELA BORGES", 4410555)])
    assert _n_alunos(db, esc) == antes + 1                # criou a ficha
    assert [r.id for r in _pendentes(db, esc)] == [rev.id]
    assert _logs(db, ACAO_AUTO) == []

    _confirmar(db, esc, sala["admin"], "elefante",
               [_elefante("NAIARA QUINTELA BORGES", 4410555, livros=8)])
    [r] = _revisoes(db, esc)
    nova = db.execute(select(Aluno).where(Aluno.nome == "NAIARA QUINTELA BORGES")).scalar_one()
    assert r.status == "resolvida" and r.aluno_escolhido_id == nova.id
    assert r.resolucao["via"] == "identidade"
    assert r.resolucao["regra"] == "vínculo pela conta da plataforma"
    assert "preteridos" not in r.resolucao


def test_reativar_a_ficha_da_conta_encerra_a_revisao_de_ficha_inativa(db, sala):
    esc = sala["escola"]
    caio = _aluno(db, esc, sala["b"], "CAIO RENATO FEITOSA", status="arquivado")
    _conta(db, esc, caio, "elefante", "4410077")
    db.commit()
    linha = _elefante("CAIO RENATO FEITOSA", 4410077)
    _confirmar(db, esc, sala["admin"], "elefante", [linha])
    [rev] = _pendentes(db, esc)
    assert rev.motivo == "identidade_de_ficha_inativa"

    caio = db.get(Aluno, caio.id)
    caio.status = "ativo"
    db.commit()
    _confirmar(db, esc, sala["admin"], "elefante", [linha])
    [r] = _revisoes(db, esc)
    assert (r.status, r.aluno_escolhido_id, r.resolvida_por_id) == ("resolvida", caio.id, None)
    assert r.resolucao["via"] == "identidade" and r.resolucao["automatica"] is True


# --- 4. a escolha automática não vira decisão humana -----------------------------

def test_ficha_transferida_depois_do_encerramento_volta_a_pedir_revisao(
        db, oficial_e_stub, monkeypatch):
    """A guarda de ficha INATIVA continua valendo: o encerramento automático não
    conta como "um gestor já escolheu esta ficha" (``_confirmado_por_humano``)."""
    c = oficial_e_stub
    esc, oficial = c["escola"], c["oficial"]
    resumo, _leituras = _irmas_giovana(db, c)
    _sincronizar_elefante(db, esc, monkeypatch, [(SID_GIOVANA, NOME_ELEFANTE_GIOVANA)])
    assert db.get(RevisaoIdentidade, resumo.id).status == "resolvida"
    assert CHAVE_GIOVANA not in ida.carregar_contexto(db, esc.id).resolvidas
    snaps = _n_snapshots(db, oficial.id)

    db.get(Aluno, oficial.id).status = "transferido"
    db.commit()
    _sincronizar_elefante(db, esc, monkeypatch, [(SID_GIOVANA, NOME_ELEFANTE_GIOVANA)])
    novas = [r for r in _pendentes(db, esc) if r.formato == "resumo"]
    assert [(r.motivo, r.chave_identidade) for r in novas] == [
        ("identidade_de_ficha_inativa", CHAVE_GIOVANA)]
    assert _n_snapshots(db, oficial.id) == snaps          # nada aplicado na ficha inativa


def test_pendencia_por_nome_e_sala_encerra_sem_virar_memoria(db, sala):
    """Sem conta da plataforma (PDF do Elefante): a chave é nome + sala. Dois
    homônimos exatos na sala, AMBOS da Lista Piloto → revisão; a duplicata é
    excluída → a importação seguinte associa e encerra. A escolha automática NÃO
    volta como memória: com o mesmo cadastro a regra decide igual (estável), e um
    homônimo novo da Lista Piloto na sala reabre a dúvida — como antes."""
    esc = sala["escola"]
    otavio = _aluno(db, esc, sala["b"], "OTAVIO LEMOS BRANDAO")
    dup = _aluno(db, esc, sala["b"], "OTAVIO LEMOS BRANDAO")
    db.commit()
    linha = _elefante("OTAVIO LEMOS BRANDAO")            # sem studentId
    _confirmar(db, esc, sala["admin"], "elefante", [linha])
    [rev] = _pendentes(db, esc)
    assert rev.chave_identidade.startswith("elefante|nome:") and rev.id_externo is None

    db.get(Aluno, dup.id).status = "excluido"
    db.commit()
    _confirmar(db, esc, sala["admin"], "elefante", [linha])
    [r] = _revisoes(db, esc)
    assert (r.status, r.aluno_escolhido_id) == ("resolvida", otavio.id)
    assert r.resolucao["via"] == "exato"
    assert r.resolucao["regra"] == "nome idêntico, candidato único"

    ctx = ida.carregar_contexto(db, esc.id)
    assert r.chave_identidade not in ctx.resolvidas and r.chave_identidade not in ctx.pendentes
    res = _confirmar(db, esc, sala["admin"], "elefante", [linha])
    assert res.qtd_revisoes == 0 and _pendentes(db, esc) == []

    _aluno(db, esc, sala["b"], "OTAVIO LEMOS BRANDAO")    # outro, também da Lista Piloto
    db.commit()
    res = _confirmar(db, esc, sala["admin"], "elefante", [linha])
    assert res.qtd_revisoes == 1
    [nova] = _pendentes(db, esc)
    assert nova.motivo == "candidatos_multiplos" and nova.id != r.id


def test_contexto_registra_a_escolha_so_nesta_importacao(db, oficial_e_stub):
    """Dentro da MESMA importação: a 1ª linha encerra, ``ctx.resolvidas`` ganha a
    escolha e ``ctx.pendentes`` perde a chave — a 2ª linha não reencerra nada. A
    irmã de leituras (outro tipo de dado) fica pendente no banco."""
    c = oficial_e_stub
    esc, oficial = c["escola"], c["oficial"]
    resumo, leituras = _irmas_giovana(db, c)
    ctx = ida.carregar_contexto(db, esc.id, ANO)
    assert ctx.pendentes[CHAVE_GIOVANA] == [resumo.id, leituras.id]
    coletor = ida.ColetorRevisoes(
        formato="resumo", origem="sincronizacao",
        contexto={"data_referencia": datetime.now(timezone.utc).isoformat()})
    avisos: list[str] = []
    for livros in (5, 6):
        aluno = imp._resolver_aluno(db, esc.id, ANO,
                                    _elefante(NOME_ELEFANTE_GIOVANA, SID_GIOVANA, livros),
                                    avisos, {}, {}, plataforma="elefante", ctx=ctx,
                                    revisoes=coletor, usuario_id=c["admin"].id)
        assert aluno.id == oficial.id
    assert CHAVE_GIOVANA not in ctx.pendentes
    assert ctx.resolvidas[CHAVE_GIOVANA] == oficial.id
    assert [l.detalhes["revisao_id"] for l in _logs(db, ACAO_AUTO)] == [resumo.id]
    assert db.get(RevisaoIdentidade, leituras.id).status == "pendente"


def test_sem_o_coletor_da_importacao_nada_e_encerrado(db, oficial_e_stub):
    """Sem o coletor não se sabe que tipo de dado a linha traz: não encerra."""
    c = oficial_e_stub
    esc = c["escola"]
    _irmas_giovana(db, c)
    ctx = ida.carregar_contexto(db, esc.id, ANO)
    imp._resolver_aluno(db, esc.id, ANO, _elefante(NOME_ELEFANTE_GIOVANA, SID_GIOVANA),
                        [], {}, {}, plataforma="elefante", ctx=ctx,
                        usuario_id=c["admin"].id)
    assert len(_pendentes(db, esc)) == 2 and _logs(db, ACAO_AUTO) == []


# --- 5. o gestor continua sendo o autor do que ele resolve ----------------------

def test_ficha_fixada_na_confirmacao_resolve_em_nome_de_quem_confirmou(db, sala):
    """Na tela de importação, quem confirma FIXA a ficha da linha (prévia aceita ou
    alternativa escolhida): a pendência é resolvida por essa pessoa — não "pelo
    sistema" — e a escolha vale como decisão humana nas próximas importações."""
    esc, admin = sala["escola"], sala["admin"]
    talita = _aluno(db, esc, sala["b"], "TALITA REGINA FONTES")
    _aluno(db, esc, sala["b"], "TALITA ROCHA FARIAS")
    db.commit()
    _confirmar(db, esc, admin, "matific", [_matific("TALITA R", "u-talita")])
    [rev] = _pendentes(db, esc)

    _confirmar(db, esc, admin, "matific", [_matific("TALITA R", "u-talita", aluno_id=talita.id)])
    [r] = _revisoes(db, esc)
    assert (r.status, r.aluno_escolhido_id, r.resolvida_por_id) == (
        "resolvida", talita.id, admin.id)
    assert r.resolucao["automatica"] is False
    assert r.resolucao["resolvida_na"] == "confirmacao_da_importacao"
    assert r.resolucao["via"] == "explicito"
    assert r.resolucao["regra"] == ("ficha fixada por quem confirmou a importação "
                                    "(prévia aceita ou alternativa escolhida)")
    assert _logs(db, ACAO_AUTO) == []
    [log] = _logs(db, ACAO_HUMANA)
    assert (log.usuario_id, log.entidade_id) == (admin.id, talita.id)
    assert log.detalhes["revisao_id"] == rev.id
    assert log.detalhes["resolvida_na"] == "confirmacao_da_importacao"
    assert ida.carregar_contexto(db, esc.id).resolvidas[rev.chave_identidade] == talita.id


def test_resolver_do_gestor_nao_vira_encerramento_automatico(db, oficial_e_stub, cliente):
    c = oficial_e_stub
    esc, oficial = c["escola"], c["oficial"]
    resumo, leituras = _irmas_giovana(db, c)
    resp = cliente.post(f"/api/v1/escolas/{esc.id}/importacoes/revisoes/{resumo.id}/resolver",
                        json={"aluno_id": oficial.id})
    assert resp.status_code == 200, resp.text
    for r in _revisoes(db, esc):
        assert r.status == "resolvida" and r.resolvida_por_id == c["admin"].id
        assert "automatica" not in (r.resolucao or {})
        assert r.resolucao["revisao_origem"] == resumo.id
    assert _logs(db, ACAO_AUTO) == []
    assert len(_logs(db, ACAO_HUMANA)) == 2
    assert all("resolvida_na" not in l.detalhes for l in _logs(db, ACAO_HUMANA))


# --- 6. desempenho: as pendências são lidas UMA vez -------------------------------

_PRIMEIROS = ["ALICE", "BRENO", "CECILIA", "DANILO", "ELISA", "FABIO", "GRETA", "HUGO",
              "IARA", "JONAS", "KAREN", "LEVI", "MALU", "NILO", "OLGA", "PAULO", "QUIRINO",
              "RITA", "SAULO", "TERESA", "ULISSES", "VERA", "WAGNER", "XENIA", "YURI"]


def _contar_consultas_de_revisao(db, esc, turma, admin, sobrenome, n):
    linhas = []
    for i, primeiro in enumerate(_PRIMEIROS[:n]):
        nome = f"{primeiro} {sobrenome}"
        _aluno(db, esc, turma, nome)
        linhas.append(_matific(nome, f"u-perf-{sobrenome[:4]}-{i}"))
    db.commit()
    consultas = {"n": 0}

    def contar(_conn, _cursor, sql, *_a):
        if "FROM revisoes_identidade" in sql and sql.lstrip().upper().startswith("SELECT"):
            consultas["n"] += 1

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", contar)
    try:
        r = _confirmar(db, esc, admin, "matific", linhas)
    finally:
        event.remove(engine, "before_cursor_execute", contar)
    assert r.qtd_alunos == n and r.qtd_revisoes == 0
    return consultas["n"]


def test_pendencias_sao_lidas_uma_vez_por_importacao(db, sala):
    esc, admin = sala["escola"], sala["admin"]
    poucas = _contar_consultas_de_revisao(db, esc, sala["b"], admin, "ZANETTI CORDEIRO", 3)
    muitas = _contar_consultas_de_revisao(db, esc, sala["b"], admin, "VALADARES PIMENTA", 25)
    assert poucas == muitas                               # não cresce com as linhas
    assert muitas <= 2                                    # resolvidas + pendentes


# --- 7. TAREFA 2: o rastro do desempate em aluno.vinculado_auto -------------------

def test_vinculado_auto_do_desempate_registra_candidatos_e_preteridos(db, oficial_e_stub):
    c = oficial_e_stub
    esc, oficial, stub = c["escola"], c["oficial"], c["stub"]
    _confirmar(db, esc, c["admin"], "elefante",
               [_elefante(NOME_ELEFANTE_GIOVANA, SID_GIOVANA)])
    [log] = [l for l in _logs(db, "aluno.vinculado_auto") if l.entidade_id == oficial.id]
    d = log.detalhes
    assert d["correspondencia"] == "lista_piloto_unica"
    assert d["candidatos"] == 2                           # a oficial + o stub
    assert d["preteridos"] == [{"aluno_id": stub.id, "nome": "GIOVANA E"}]
    assert d["motivo"] == ("única ficha da Lista Piloto compatível na sala; as outras "
                           "são duplicatas dela (mesmo nome ou abreviado), fora da Lista "
                           "Piloto")
    assert "único candidato plausível" not in d["motivo"]


def test_vinculado_auto_sem_desempate_continua_como_era(db, sala):
    esc = sala["escola"]
    rosa = _aluno(db, esc, sala["b"], "ROSANA MELO QUEIROZ")
    db.commit()
    _confirmar(db, esc, sala["admin"], "matific", [_matific("ROSANA M", "u-rosana")])
    [log] = [l for l in _logs(db, "aluno.vinculado_auto") if l.entidade_id == rosa.id]
    d = log.detalhes
    assert (d["candidatos"], d["correspondencia"]) == (1, "abreviacao")
    assert d["motivo"] == "único candidato plausível na mesma sala"
    assert "preteridos" not in d


# --- 8. a regra gravada diz a verdade ---------------------------------------------

def test_regra_diz_quando_o_sufixo_de_turma_saiu_do_nome(db, sala):
    """'… ROCHA 2B' casa como nome idêntico depois que o sufixo de turma sai do
    casamento: a regra gravada diz isso, para ninguém achar que o nome era igual."""
    esc = sala["escola"]
    yago = _aluno(db, esc, sala["b"], "YAGO FERRAZ ROCHA")
    db.commit()
    chave = "elefante|id:4410900"
    _pendencia(db, esc, chave_ident=chave, id_externo="4410900", nome="YAGO FERRAZ ROCHA 2B",
               motivo="correspondencia_insegura", candidatos=(yago,))
    _confirmar(db, esc, sala["admin"], "elefante", [_elefante("YAGO FERRAZ ROCHA 2B", 4410900)])
    [r] = _revisoes(db, esc)
    assert (r.status, r.aluno_escolhido_id) == ("resolvida", yago.id)
    assert r.resolucao["via"] == "exato"
    assert r.resolucao["regra"] == ("nome idêntico, candidato único, sem o sufixo de turma "
                                    "digitado junto do nome")


def test_regra_da_conta_nao_fala_de_sufixo(db, sala):
    """Pela conta da plataforma o nome não entrou no casamento: o sufixo de turma
    no nome recebido não aparece na regra."""
    esc = sala["escola"]
    yara = _aluno(db, esc, sala["b"], "YARA DUTRA PEIXOTO", status="arquivado")
    _conta(db, esc, yara, "elefante", "4410321")
    db.commit()
    linha = _elefante("YARA DUTRA PEIXOTO 2B", 4410321)
    _confirmar(db, esc, sala["admin"], "elefante", [linha])   # ficha inativa → pendente
    db.get(Aluno, yara.id).status = "ativo"
    db.commit()
    _confirmar(db, esc, sala["admin"], "elefante", [linha])   # reativada → identidade
    [r] = _revisoes(db, esc)
    assert r.status == "resolvida" and r.resolucao["via"] == "identidade"
    assert r.resolucao["regra"] == "vínculo pela conta da plataforma"


# --- revisão adversarial de 2026-10-11 --------------------------------------------

def test_arquivo_sem_data_nao_encerra_retrato_de_outro_dia(db, oficial_e_stub):
    """Arquivo enviado à mão SEM a data do relatório: a "data desta importação" é
    só o relógio de agora e o relatório pode ser antigo. O retrato guardado fica
    para o /resolver."""
    c = oficial_e_stub
    esc, oficial = c["escola"], c["oficial"]
    rev = _pendencia(db, esc, chave_ident=CHAVE_GIOVANA, id_externo=str(SID_GIOVANA),
                     nome=NOME_ELEFANTE_GIOVANA, candidatos=(oficial, c["stub"]))
    _confirmar(db, esc, c["admin"], "elefante",
               [_elefante(NOME_ELEFANTE_GIOVANA, SID_GIOVANA, livros=3)], sem_data=True)
    assert [r.id for r in _pendentes(db, esc)] == [rev.id]
    assert _logs(db, ACAO_AUTO) == [] and _logs(db, ACAO_HUMANA) == []


def test_sugestao_da_previa_aceita_como_veio_encerra_como_automatica(db, sala):
    """Quem confirma a importação com a ficha que o PRÓPRIO motor sugeriu não
    decidiu nada: a pendência encerra como automática e não vira memória (que
    desligaria a guarda de homônimo novo e a de ficha inativa depois)."""
    esc, admin = sala["escola"], sala["admin"]
    talita = _aluno(db, esc, sala["b"], "TALITA REGINA FONTES")
    db.commit()
    chave = ida.chave_identidade(
        ida.linha_de_dados("TALITA REGINA FONTES", {"matific_uuid": "u-talita"},
                           plataforma="matific", turma_nome=SALA_MATIFIC), "")
    _pendencia(db, esc, chave_ident=chave, plataforma="matific", id_externo="u-talita",
               nome="TALITA REGINA FONTES", candidatos=(talita,))
    _confirmar(db, esc, admin, "matific",
               [_matific("TALITA REGINA FONTES", "u-talita", aluno_id=talita.id)])
    [r] = _revisoes(db, esc)
    assert (r.status, r.aluno_escolhido_id, r.resolvida_por_id) == ("resolvida", talita.id, None)
    assert r.resolucao["automatica"] is True
    assert _logs(db, ACAO_HUMANA) == [] and len(_logs(db, ACAO_AUTO)) == 1
    assert r.chave_identidade not in ida.carregar_contexto(db, esc.id).resolvidas
