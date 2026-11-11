"""Fusão de fichas e o espelho de eventos: a mesma leitura não pode virar duas.

O DEFEITO (ALUNOS-3). ``eventos.chave_evento`` põe o ``aluno_id`` DENTRO da chave
de idempotência — de propósito: é a prova de origem que a restauração histórica
(``leituras_restauracao``) confere. Mas a fusão só descartava evento com a MESMA
chave, e a ingestão só procurava a chave da própria ficha. Resultado:

* a mesma linha do relatório gravada nas duas fichas virava DOIS eventos na
  ficha que fica;
* o evento movido guarda a chave da ficha absorvida, e a coleta/importação
  seguinte da mesma conta (agora na ficha que ficou) não o reconhecia e gravava
  de novo.

A linha do tempo, o espelho ("Total de eventos") e os "Registros de leitura" do
Relatório por Período dobravam.

O CONSERTO. Duas cópias são o MESMO evento quando o CONTEÚDO bate (plataforma,
tipo, título normalizado, minuto) — sem depender da ficha. Entre as duas, fica a
que prova a origem de uma ficha absorvida; a cópia nativa da ficha que fica é a
redundante. Assim a evidência da restauração continua de pé.

Dados fictícios.
"""
from datetime import datetime

from sqlalchemy import func, select

from app.models import EventoAluno, LogAuditoria
from app.services import leituras_restauracao as lr
from app.services.eventos import chave_evento, ingerir_eventos

API = "/api/v1"
TITULO = "Livro Ficticio do Espelho"
MARCO = "2026-03-10T10:00:00"
AGOSTO = "2026-08-06T00:01:00"


def _linha(data: str, tempo: int = 15) -> dict:
    return {"livro": TITULO, "nivel": "AA", "data": data, "tempo_livro_min": tempo}


def _importar(cliente, escola_id, aluno, *datas: str):
    r = cliente.post(f"{API}/escolas/{escola_id}/importacoes/confirmar", json={
        "plataforma": "elefante", "formato": "leituras", "tipo": "texto",
        "linhas": [{"nome": aluno.nome, "dados": _linha(d), "aluno_id": aluno.id}
                   for d in datas]})
    assert r.status_code == 200, r.text
    return r.json()


def _fundir(cliente, escola_id, manter_id, remover_id) -> dict:
    r = cliente.post(f"{API}/escolas/{escola_id}/alunos/fundir", json={
        "manter_id": manter_id, "remover_id": remover_id, "confirmacao": "FUNDIR"})
    assert r.status_code == 200, r.text
    return r.json()


def _eventos(db, aluno_id) -> list[EventoAluno]:
    db.expire_all()
    return list(db.execute(select(EventoAluno).where(EventoAluno.aluno_id == aluno_id)
                           .order_by(EventoAluno.ocorrido_em, EventoAluno.id)).scalars())


def _par(escola_completa):
    escola_id = escola_completa["escola"].id
    manter, remover = escola_completa["alunos"][0], escola_completa["alunos"][1]
    return escola_id, manter, remover, manter.id, remover.id


# ---------------------------------------------------------------------------
# As duas sondas do auditor
# ---------------------------------------------------------------------------
def test_reimportar_depois_da_fusao_nao_duplica_evento(cliente, db, escola_completa):
    escola_id, manter, remover, manter_id, remover_id = _par(escola_completa)
    _importar(cliente, escola_id, remover, MARCO)          # chega no stub
    _fundir(cliente, escola_id, manter_id, remover_id)
    assert len(_eventos(db, manter_id)) == 1

    # A mesma conta é coletada de novo, agora para a ficha que ficou.
    _importar(cliente, escola_id, manter, MARCO)
    eventos = _eventos(db, manter_id)
    esp = cliente.get(f"{API}/escolas/{escola_id}/alunos/{manter_id}/espelho").json()
    print("EVENTOS NA FICHA QUE FICOU:", len(eventos),
          "| espelho total_eventos:", esp["espelho"]["total_eventos"])
    assert len(eventos) == 1, "a mesma leitura virou dois eventos depois da fusão"
    assert esp["espelho"]["total_eventos"] == 1
    # Fica o evento que veio da ficha absorvida: a chave dele é a prova de origem.
    assert eventos[0].chave_natural == chave_evento(
        "elefante", "leitura", remover_id, TITULO, datetime(2026, 3, 10, 10, 0))


def test_fusao_de_fichas_com_a_mesma_leitura_nao_duplica_evento(cliente, db, escola_completa):
    escola_id, manter, remover, manter_id, remover_id = _par(escola_completa)
    _importar(cliente, escola_id, remover, MARCO)
    _importar(cliente, escola_id, manter, MARCO)
    corpo = _fundir(cliente, escola_id, manter_id, remover_id)
    eventos = _eventos(db, manter_id)
    print("FUSAO: leituras_descartadas=", corpo["leituras_descartadas"],
          "eventos_movidos=", corpo["eventos_movidos"],
          "eventos_descartados=", corpo["eventos_descartados"],
          "| EVENTOS NA FICHA QUE FICOU:", len(eventos))
    assert corpo["leituras_descartadas"] == 1
    assert len(eventos) == 1, "a mesma leitura ficou duas vezes na linha do tempo"
    assert corpo["eventos_descartados"] == 1
    # A cópia nativa da ficha que fica era a redundante; a da absorvida prova a origem.
    assert eventos[0].chave_natural == chave_evento(
        "elefante", "leitura", remover_id, TITULO, datetime(2026, 3, 10, 10, 0))
    # A cópia descartada fica registrada no log da fusão (rede de segurança).
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "aluno.fundido")).scalars().one()
    detalhe = log.detalhes["eventos_descartados_detalhe"]
    assert len(detalhe) == 1
    assert detalhe[0]["chave_natural"] == chave_evento(
        "elefante", "leitura", manter_id, TITULO, datetime(2026, 3, 10, 10, 0))
    assert detalhe[0]["igual_ao_evento_id"] == eventos[0].id


def test_controle_sem_fusao_reimportar_e_idempotente(cliente, db, escola_completa):
    escola_id, manter, _r, manter_id, _rid = _par(escola_completa)
    _importar(cliente, escola_id, manter, MARCO)
    _importar(cliente, escola_id, manter, MARCO)
    assert len(_eventos(db, manter_id)) == 1


def test_leituras_diferentes_continuam_separadas_depois_da_fusao(cliente, db, escola_completa):
    """Conteúdo diferente (outro minuto) é outro evento: a deduplicação não come
    releitura nenhuma."""
    escola_id, manter, remover, manter_id, remover_id = _par(escola_completa)
    _importar(cliente, escola_id, remover, MARCO)
    _importar(cliente, escola_id, manter, AGOSTO)
    corpo = _fundir(cliente, escola_id, manter_id, remover_id)
    assert corpo["eventos_movidos"] == 1 and corpo["eventos_descartados"] == 0
    _importar(cliente, escola_id, manter, MARCO, AGOSTO)
    assert len(_eventos(db, manter_id)) == 2


# ---------------------------------------------------------------------------
# A evidência da restauração histórica continua de pé
# ---------------------------------------------------------------------------
def test_restauracao_ainda_prova_a_origem_quando_as_duas_fichas_tinham_a_linha(
        cliente, db, escola_completa):
    """O caso que a restauração existe para resolver: a ficha que fica tem o
    histórico ANTIGO (leitura em março) e as duas fichas receberam a releitura de
    agosto. A fusão mantém março; a prova de que a ficha absorvida tinha agosto é
    o evento dela. Se a fusão descartasse esse evento (e não a cópia nativa), a
    restauração ficaria sem evidência."""
    escola_id, manter, remover, manter_id, remover_id = _par(escola_completa)
    _importar(cliente, escola_id, manter, MARCO)
    _importar(cliente, escola_id, manter, MARCO, AGOSTO)
    _importar(cliente, escola_id, remover, AGOSTO)
    _fundir(cliente, escola_id, manter_id, remover_id)

    eventos = _eventos(db, manter_id)
    assert [e.ocorrido_em for e in eventos] == [datetime(2026, 3, 10, 10, 0),
                                                datetime(2026, 8, 6, 0, 1)]
    prova = eventos[1]
    plano = lr.planejar(db, escola_id, [lr.ItemRestauracao(
        aluno_id=manter_id, aluno_origem_id=remover_id, livro_id=prova.livro_id,
        data_original=prova.ocorrido_em, tempo_original=15,
        evidencia_evento_id=prova.id, evidencia_chave_natural=prova.chave_natural,
        motivo="fusao manteve a data de marco; o evento prova agosto")])
    assert plano[0]["data_restaurada"] == datetime(2026, 8, 6, 0, 1)


# ---------------------------------------------------------------------------
# A ingestão: o ``extra`` (repetição no mesmo minuto) continua valendo
# ---------------------------------------------------------------------------
def test_ingestao_com_extra_nao_e_deduplicada_por_conteudo(db, escola_completa):
    escola_id, _m, _r, aluno_id, _rid = _par(escola_completa)
    quando = datetime(2026, 5, 3, 9, 15)
    base = {"escola_id": escola_id, "aluno_id": aluno_id, "plataforma": "matific",
            "tipo_evento": "atividade", "ocorrido_em": quando,
            "conteudo_titulo": "Atividade X", "dados": {}}
    t1 = {**base, "chave_natural": chave_evento("matific", "atividade", aluno_id,
                                                "Atividade X", quando, "1")}
    t2 = {**base, "chave_natural": chave_evento("matific", "atividade", aluno_id,
                                                "Atividade X", quando, "2")}
    assert ingerir_eventos(db, aluno_id, "matific", [t1]) == 1
    db.flush()
    assert ingerir_eventos(db, aluno_id, "matific", [t2]) == 1


# ---------------------------------------------------------------------------
# O passivo: duplicatas já gravadas antes do conserto
# ---------------------------------------------------------------------------
def _evento(db, escola_id, aluno_id, origem, quando, titulo=TITULO):
    ev = EventoAluno(escola_id=escola_id, aluno_id=aluno_id, plataforma="elefante",
                     tipo_evento="leitura", ocorrido_em=quando, conteudo_titulo=titulo,
                     tempo_segundos=900,
                     chave_natural=chave_evento("elefante", "leitura", origem, titulo, quando))
    db.add(ev)
    db.flush()
    return ev


def _fusao_antiga(db, escola_id, manter_id, remover_id):
    """O log que toda fusão grava: é por ele que a limpeza conhece as origens."""
    db.add(LogAuditoria(escola_id=escola_id, acao="aluno.fundido", entidade="aluno",
                        entidade_id=manter_id,
                        detalhes={"mantido": {"id": manter_id}, "removido": {"id": remover_id}}))


def _removidos(db):
    return db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "aluno.eventos_duplicados_removidos")).scalars().all()


def test_limpeza_do_passivo_simula_e_depois_aplica(db, escola_completa):
    from app.services.eventos import deduplicar_eventos_por_conteudo

    escola_id, _m, _r, manter_id, remover_id = _par(escola_completa)
    quando = datetime(2026, 3, 10, 10, 0)
    nativo = _evento(db, escola_id, manter_id, manter_id, quando)
    absorvido = _evento(db, escola_id, manter_id, remover_id, quando)   # movido pela fusão
    outro = _evento(db, escola_id, manter_id, manter_id, datetime(2026, 8, 6, 0, 1))
    _fusao_antiga(db, escola_id, manter_id, remover_id)
    db.commit()
    nativo_id, absorvido_id, outro_id = nativo.id, absorvido.id, outro.id

    simulado = deduplicar_eventos_por_conteudo(db, aplicar=False)
    db.rollback()
    assert simulado["eventos_duplicados"] == 1 and simulado["alunos"] == 1
    assert len(_eventos(db, manter_id)) == 3                     # nada apagado
    assert _removidos(db) == []

    aplicado = deduplicar_eventos_por_conteudo(db, aplicar=True)
    db.commit()
    assert aplicado["eventos_duplicados"] == 1
    restantes = {e.id for e in _eventos(db, manter_id)}
    assert restantes == {absorvido_id, outro_id}                 # fica a prova de origem
    log, = _removidos(db)
    assert log.entidade_id == manter_id and log.escola_id == escola_id
    assert log.detalhes["eventos"][0]["evento_id"] == nativo_id
    assert log.detalhes["eventos"][0]["igual_ao_evento_id"] == absorvido_id

    # Idempotente: a segunda passada não acha nada.
    assert deduplicar_eventos_por_conteudo(db, aplicar=True)["eventos_duplicados"] == 0


def test_limpeza_do_passivo_em_cadeia_e_sem_prova(db, escola_completa):
    """Ficha que absorveu duas (B e C, cada uma com a mesma linha): fica UMA
    cópia, a de menor id entre as absorvidas. Cópia cuja origem não se prova
    (sem log de fusão que a explique) não é tocada."""
    from app.services.eventos import deduplicar_eventos_por_conteudo

    escola_id, _m, _r, manter_id, _rid = _par(escola_completa)
    terceiro_id = escola_completa["alunos"][2].id
    b, c, sem_log = 9001, 9002, 9003          # fichas que já não existem
    quando = datetime(2026, 4, 1, 8, 30)
    da_b = _evento(db, escola_id, manter_id, b, quando)
    _evento(db, escola_id, manter_id, c, quando)
    _fusao_antiga(db, escola_id, manter_id, b)
    _fusao_antiga(db, escola_id, b, c)        # C entrou em B antes de B entrar aqui
    _evento(db, escola_id, terceiro_id, terceiro_id, quando)
    _evento(db, escola_id, terceiro_id, sem_log, quando)
    db.commit()

    resultado = deduplicar_eventos_por_conteudo(db, aplicar=True)
    db.commit()
    assert resultado == {"alunos": 1, "eventos_duplicados": 1}
    assert [e.id for e in _eventos(db, manter_id)] == [da_b.id]
    assert len(_eventos(db, terceiro_id)) == 2


def test_script_do_passivo_e_simulacao_por_padrao(db, escola_completa, monkeypatch, capsys):
    from scripts import deduplicar_eventos_por_conteudo as script

    escola_id, _m, _r, manter_id, remover_id = _par(escola_completa)
    quando = datetime(2026, 3, 10, 10, 0)
    _evento(db, escola_id, manter_id, manter_id, quando)
    _evento(db, escola_id, manter_id, remover_id, quando)
    _fusao_antiga(db, escola_id, manter_id, remover_id)
    db.commit()

    class _SessaoSemFechar:
        def __init__(self, sessao):
            self._s = sessao

        def __getattr__(self, nome):
            return getattr(self._s, nome)

        def close(self):
            pass

    monkeypatch.setattr(script, "SessionLocal", lambda: _SessaoSemFechar(db))
    assert script.main([]) == 0
    saida = capsys.readouterr().out
    assert "SIMULAÇÃO" in saida and "1 evento(s) repetido(s)" in saida
    assert len(_eventos(db, manter_id)) == 2

    assert script.main(["--aplicar", "--escola", str(escola_id)]) == 0
    assert "APLICADO" in capsys.readouterr().out
    assert len(_eventos(db, manter_id)) == 1
