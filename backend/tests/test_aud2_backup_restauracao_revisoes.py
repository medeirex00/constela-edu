"""G_LGPD-4 — a restauração do backup reaponta o que fica FORA do arquivo e aponta
para as fichas, turmas e importações que ela recria com id novo.

``revisoes_identidade`` e ``sincronizacao_execucoes`` não entram no arquivo e apontam
para ``alunos``, ``turmas`` e ``importacoes`` com ``ON DELETE SET NULL``; os
candidatos da revisão ficam num JSON (``candidatos[].aluno_id``), sem FK. A
restauração apagava as linhas da escola e as recriava com id novo sem reapontar nada:

* ``aluno_escolhido_id`` — a MEMÓRIA da decisão humana que ``carregar_contexto`` lê
  em ``ctx.resolvidas`` — virava NULL, e a coleta seguinte mandava de novo para a
  revisão a conta que o Admin Global já tinha confirmado (D10), com 403 para a gestão;
* as pendências ofereciam candidatos que não existem (o clique dava 400);
* a pendência perdia a turma e a importação de origem (a marca S9 "sem questões" da
  importação decide como a linha guardada é reaplicada);
* a execução da sincronização perdia a importação que gerou.

O radar das perdas só seguia o ``ON DELETE CASCADE``: o ``SET NULL`` destruía o
vínculo sem que ninguém visse. ``test_toda_referencia_de_fora_do_arquivo_esta_no_radar``
acusa a próxima tabela nessa situação.

As fichas, turmas e importações de OUTRA escola (``_ocupar_ids``) são criadas antes de
restaurar para o SQLite não reaproveitar os ids apagados: assim os ids mudam como no
PostgreSQL, que nunca reaproveita (``test_aud2_backup_restauracao_revisoes_pg.py``).

Dados 100% fictícios (escolas e crianças inventadas); sem rede.
"""
from sqlalchemy import select

from app.core.database import Base
from app.models import (
    Aluno,
    Escola,
    IdentidadeExterna,
    Importacao,
    LogAuditoria,
    Matricula,
    RevisaoIdentidade,
    SincronizacaoExecucao,
    Turma,
)
from app.models.plataformas import SnapshotMatific
from app.services import backup as svc_backup

API = "/api/v1"
U = "u-ficticia-aud2-restauracao-d10"
NOME_DEPOIS = "Crianca Ficticia Aud2 Depois Do Backup"


def _importar(cliente, eid, nome, estrelas, turma, uuid=U):
    linha = {"nome": nome, "dados": {"matific_uuid": uuid, "estrelas": estrelas,
                                     "atividades": 10, "pontuacao_media": 80,
                                     "turma_relatorio": turma}}
    r = cliente.post(f"{API}/escolas/{eid}/importacoes/confirmar", json={
        "plataforma": "matific", "formato": "resumo", "tipo": "pdf",
        "recalcular": False, "linhas": [linha]})
    assert r.status_code == 200, r.text
    return r.json()


def _pendentes(db, eid):
    db.expire_all()
    return db.execute(select(RevisaoIdentidade).where(
        RevisaoIdentidade.escola_id == eid,
        RevisaoIdentidade.status == "pendente")).scalars().all()


def _baixar(cliente, eid) -> bytes:
    r = cliente.get(f"{API}/escolas/{eid}/backup")
    assert r.status_code == 200, r.text
    return r.content


def _restaurar(cliente_global, eid, arquivo: bytes) -> dict:
    r = cliente_global.post(f"{API}/escolas/{eid}/restaurar",
                            files={"arquivo": ("b.json", arquivo, "application/json")})
    assert r.status_code == 200, r.text
    return r.json()


def _ocupar_ids(db, sufixo: str) -> None:
    """Ficha, turma e importação de OUTRA escola, com id maior que os da escola: o
    SQLite não reaproveita os ids que a restauração apaga (o PostgreSQL nunca)."""
    outra = Escola(nome=f"ESCOLA FICTICIA AUD2 OCUPA {sufixo}", ano_letivo_ativo=2026)
    db.add(outra)
    db.flush()
    db.add_all([Aluno(escola_id=outra.id, nome=f"Crianca Ficticia Ocupa {sufixo}"),
                Turma(escola_id=outra.id, nome="9º Ano Z", ano_escolar="9º Ano",
                      ano_letivo=2026),
                Importacao(escola_id=outra.id, plataforma="matific", tipo="seed")])
    db.commit()


def _ficha(db, eid, nome) -> Aluno:
    db.expire_all()
    return db.execute(select(Aluno).where(Aluno.escola_id == eid,
                                          Aluno.nome == nome)).scalar_one()


def test_restauracao_mantem_a_memoria_da_decisao_humana(db, escola_completa, cliente,
                                                        cliente_global):
    from tests.test_sync_escola_cruzada import _nova_escola

    e1 = escola_completa["escola"].id
    turma = escola_completa["turma"].nome
    ficha = escola_completa["alunos"][0]
    nome, ficha_id = ficha.nome, ficha.id
    # A conta U é efetiva na escola B; a coleta de A a traz (revisão D10 aqui).
    escola_b, _t, (y,) = _nova_escola(db, nome="ESCOLA FICTICIA B AUD2 BACKUP",
                                      com_alunos=("Crianca Ficticia B Aud2",))
    db.add(IdentidadeExterna(escola_id=escola_b.id, aluno_id=y.id,
                             plataforma="matific", id_externo=U))
    db.commit()
    assert _importar(cliente, e1, nome, 30, turma)["ids_de_outra_escola"] == [U]
    [rev] = _pendentes(db, e1)
    rev_id = rev.id
    # O Admin Global confirma: a conta U é desta criança de A.
    r = cliente_global.post(f"{API}/escolas/{e1}/importacoes/revisoes/{rev_id}/resolver",
                            json={"aluno_id": ficha_id})
    assert r.status_code == 200, r.text
    assert _importar(cliente, e1, nome, 40, turma)["ids_de_outra_escola"] == []

    _restaurar(cliente_global, e1, _baixar(cliente, e1))
    nova = _ficha(db, e1, nome)
    assert nova.id != ficha_id                  # a restauração recriou a ficha
    assert db.get(RevisaoIdentidade, rev_id).aluno_escolhido_id == nova.id, (
        "a restauração apagou a memória da decisão humana (aluno_escolhido_id)")

    # A coleta seguinte (a plataforma manda a mesma conta, como toda noite).
    coleta = _importar(cliente, e1, nome, 50, turma)
    assert coleta["ids_de_outra_escola"] == [] and _pendentes(db, e1) == []
    estrelas = db.execute(select(SnapshotMatific.estrelas).where(
        SnapshotMatific.aluno_id == nova.id)).scalars().all()
    assert 50 in estrelas


def test_restauracao_reaponta_candidatos_turma_e_importacao_da_pendencia(
        db, escola_completa, cliente, cliente_global):
    e1 = escola_completa["escola"].id
    turma = escola_completa["turma"]
    turma_nome = turma.nome
    # Homônimo na mesma sala: a linha da plataforma não tem dono certo -> pendência.
    homonimo = Aluno(escola_id=e1, nome="Ana Beatriz Souza")
    db.add(homonimo)
    db.flush()
    db.add(Matricula(escola_id=e1, aluno_id=homonimo.id, turma_id=turma.id, ano_letivo=2026))
    db.commit()
    _importar(cliente, e1, "Ana Beatriz Souza", 20, turma_nome, uuid="u-aud2-homonimo")
    [rev] = _pendentes(db, e1)
    rev_id = rev.id
    ids_antes = [c["aluno_id"] for c in rev.candidatos]
    assert len(ids_antes) == 2, rev.candidatos
    origem = db.get(Importacao, rev.importacao_id)
    origem_antes = (origem.plataforma, origem.tipo, origem.created_at)
    assert rev.turma_id == turma.id

    arquivo = _baixar(cliente, e1)
    _ocupar_ids(db, "1")
    _restaurar(cliente_global, e1, arquivo)

    lista = cliente.get(f"{API}/escolas/{e1}/importacoes/revisoes").json()
    [item] = [x for x in lista if x["id"] == rev_id]
    ids_tela = [c["aluno_id"] for c in item["candidatos"]]
    db.expire_all()
    fichas = [db.get(Aluno, i) for i in ids_tela]
    assert all(f is not None and f.escola_id == e1 for f in fichas), (
        f"a tela oferece candidatos que a restauração apagou: {ids_tela}")
    assert [f.nome for f in fichas] == ["Ana Beatriz Souza", "Ana Beatriz Souza"]
    assert not set(ids_tela) & set(ids_antes)   # ids novos: reapontados, não por acaso
    assert item["turma_id"] is not None, "a pendência perdeu a turma"
    assert db.get(Turma, item["turma_id"]).nome == turma_nome
    assert item["importacao_id"] is not None, "a pendência perdeu a importação de origem"
    nova_origem = db.get(Importacao, item["importacao_id"])
    assert nova_origem.escola_id == e1
    assert (nova_origem.plataforma, nova_origem.tipo, nova_origem.created_at) == origem_antes

    r = cliente.post(f"{API}/escolas/{e1}/importacoes/revisoes/{rev_id}/resolver",
                     json={"aluno_id": ids_tela[0]})
    assert r.status_code == 200, r.text


def test_restauracao_mantem_a_importacao_da_execucao_da_sincronizacao(
        db, escola_completa, cliente, cliente_global):
    e1 = escola_completa["escola"].id
    imp = Importacao(escola_id=e1, plataforma="matific", tipo="texto", qtd_alunos=7)
    db.add(imp)
    db.flush()
    execucao = SincronizacaoExecucao(escola_id=e1, plataforma="matific", origem="manual",
                                     status="concluida", importacao_id=imp.id)
    db.add(execucao)
    db.commit()
    execucao_id, imp_id = execucao.id, imp.id

    arquivo = _baixar(cliente, e1)
    _ocupar_ids(db, "1")
    _restaurar(cliente_global, e1, arquivo)
    db.expire_all()
    nova = db.get(SincronizacaoExecucao, execucao_id).importacao_id
    assert nova is not None, "a execução da sincronização perdeu a importação que gerou"
    assert nova != imp_id
    recriada = db.get(Importacao, nova)
    assert (recriada.escola_id, recriada.tipo, recriada.qtd_alunos) == (e1, "texto", 7)


def test_o_que_o_arquivo_nao_traz_sai_da_fila_e_fica_contado_no_log(
        db, escola_completa, cliente, cliente_global):
    """A ficha e a importação de DEPOIS do backup não voltam: a decisão que apontava
    para a ficha fica sem escolhido, a candidata dela sai da pendência, e o log da
    restauração conta o que foi reapontado e o que ficou sem equivalente."""
    e1 = escola_completa["escola"].id
    turma = escola_completa["turma"]
    a = escola_completa["alunos"][0]
    nome_a, turma_nome = a.nome, turma.nome
    arquivo = _baixar(cliente, e1)

    depois = Aluno(escola_id=e1, nome=NOME_DEPOIS)
    imp_depois = Importacao(escola_id=e1, plataforma="matific", tipo="texto")
    db.add_all([depois, imp_depois])
    db.flush()
    db.add(Matricula(escola_id=e1, aluno_id=depois.id, turma_id=turma.id, ano_letivo=2026))

    def _candidata(aluno):
        return {"aluno_id": aluno.id, "nome": aluno.nome, "status": "ativo",
                "turma": turma_nome}

    resolvida = RevisaoIdentidade(
        escola_id=e1, chave="aud2-k1", chave_identidade="aud2-ci1", plataforma="matific",
        nome_recebido=NOME_DEPOIS, motivo="candidatos_multiplos", status="resolvida",
        aluno_escolhido_id=depois.id, candidatos=[_candidata(depois)],
        importacao_id=imp_depois.id, turma_id=turma.id,
        resolucao={"acao": "associar", "aluno_id": depois.id, "automatica": False})
    pendente = RevisaoIdentidade(
        escola_id=e1, chave="aud2-k2", chave_identidade="aud2-ci2", plataforma="matific",
        nome_recebido="Crianca Ficticia Aud2 Recebida", motivo="candidatos_multiplos",
        candidatos=[_candidata(a), _candidata(depois), {"nome": "sem ficha"}],
        turma_id=turma.id)
    db.add_all([resolvida, pendente])
    db.commit()
    resolvida_id, pendente_id = resolvida.id, pendente.id

    _ocupar_ids(db, "1")
    _restaurar(cliente_global, e1, arquivo)
    nova_a = _ficha(db, e1, nome_a)
    turma_nova = db.execute(select(Turma).where(Turma.escola_id == e1,
                                                Turma.nome == turma_nome)).scalar_one()
    r1 = db.get(RevisaoIdentidade, resolvida_id)
    assert (r1.aluno_escolhido_id, r1.importacao_id) == (None, None)
    assert r1.turma_id == turma_nova.id
    r2 = db.get(RevisaoIdentidade, pendente_id)
    assert [c.get("aluno_id") for c in r2.candidatos] == [nova_a.id, None]
    assert r2.candidatos[0]["nome"] == nome_a
    assert r2.turma_id == turma_nova.id

    [log] = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "backup.restaurado")).scalars().all()
    contas = log.detalhes["referencias_reapontadas"]
    assert contas["revisoes_identidade.aluno_escolhido_id"] == {
        "reapontadas": 0, "sem_equivalente": 1}
    assert contas["revisoes_identidade.turma_id"] == {"reapontadas": 2, "sem_equivalente": 0}
    assert contas["revisoes_identidade.importacao_id"] == {
        "reapontadas": 0, "sem_equivalente": 1}
    assert contas["revisoes_identidade.candidatos"] == {
        "reapontadas": 1, "sem_equivalente": 2}
    assert NOME_DEPOIS not in str(log.detalhes) and nome_a not in str(log.detalhes)


def test_arquivo_anterior_a_outra_restauracao_reaponta_pela_linhagem(
        db, escola_completa, cliente, cliente_global):
    """O arquivo gerado ANTES de outra restauração leva os ids antigos; as revisões e
    as execuções já apontam para os ids da restauração do meio. A linhagem gravada em
    ``backup.restaurado`` (fichas, turmas e importações) liga os dois."""
    e1 = escola_completa["escola"].id
    turma = escola_completa["turma"]
    a = escola_completa["alunos"][0]
    nome_a, turma_nome = a.nome, turma.nome
    imp = Importacao(escola_id=e1, plataforma="matific", tipo="texto", qtd_alunos=3)
    db.add(imp)
    db.flush()
    rev = RevisaoIdentidade(
        escola_id=e1, chave="aud2-k3", chave_identidade="aud2-ci3", plataforma="matific",
        nome_recebido=nome_a, motivo="candidatos_multiplos", status="resolvida",
        aluno_escolhido_id=a.id, turma_id=turma.id, importacao_id=imp.id,
        candidatos=[{"aluno_id": a.id, "nome": nome_a, "status": "ativo",
                     "turma": turma_nome}],
        resolucao={"acao": "associar", "aluno_id": a.id, "automatica": False})
    execucao = SincronizacaoExecucao(escola_id=e1, plataforma="matific", origem="manual",
                                     status="concluida", importacao_id=imp.id)
    db.add_all([rev, execucao])
    db.commit()
    rev_id, execucao_id = rev.id, execucao.id

    antigo = _baixar(cliente, e1)
    _ocupar_ids(db, "1")
    _restaurar(cliente_global, e1, antigo)      # a restauração do meio
    _ocupar_ids(db, "2")
    _restaurar(cliente_global, e1, antigo)      # o mesmo arquivo, anterior a ela

    a_final = _ficha(db, e1, nome_a)
    turma_final = db.execute(select(Turma).where(Turma.escola_id == e1,
                                                 Turma.nome == turma_nome)).scalar_one()
    imp_final = db.execute(select(Importacao).where(
        Importacao.escola_id == e1, Importacao.tipo == "texto")).scalar_one()
    rev = db.get(RevisaoIdentidade, rev_id)
    assert rev.aluno_escolhido_id == a_final.id
    assert rev.candidatos[0]["aluno_id"] == a_final.id
    assert rev.turma_id == turma_final.id
    assert rev.importacao_id == imp_final.id
    assert db.get(SincronizacaoExecucao, execucao_id).importacao_id == imp_final.id


def test_toda_referencia_de_fora_do_arquivo_esta_no_radar():
    """Toda FK de uma tabela FORA do arquivo para uma tabela do arquivo: o CASCADE é o
    radar das perdas (``test_nenhuma_tabela_em_risco_fora_do_radar``); o resto tem de
    ser ``SET NULL`` (a restauração reaponta) para uma tabela com linhagem gravada.
    Uma FK sem ``ondelete`` faria a restauração cair com 400 "dados inconsistentes", e
    uma tabela nova com ``SET NULL`` para outra do arquivo perderia o vínculo calada."""
    import app.models  # noqa: F401  (popula o metadata)
    import app.quest.models  # noqa: F401

    no_arquivo = {m.__tablename__ for _, m in svc_backup.MODELOS}
    nao_cobertas = []
    for tabela in Base.metadata.tables.values():
        if tabela.name in no_arquivo:
            continue
        for fk in tabela.foreign_keys:
            alvo = fk.column.table.name
            regra = (fk.ondelete or "").upper()
            if alvo not in no_arquivo or regra == "CASCADE":
                continue
            if regra != "SET NULL" or alvo not in svc_backup.CHAVES_DE_LINHAGEM:
                nao_cobertas.append(f"{tabela.name}.{fk.parent.name} -> {alvo} ({regra})")
    assert not nao_cobertas, nao_cobertas
    reapontadas = {(t, c, a) for t, c, a in svc_backup._referencias_de_fora(Base.metadata)}
    assert {("revisoes_identidade", "aluno_escolhido_id", "alunos"),
            ("revisoes_identidade", "turma_id", "turmas"),
            ("revisoes_identidade", "importacao_id", "importacoes"),
            ("sincronizacao_execucoes", "importacao_id", "importacoes")} <= reapontadas
