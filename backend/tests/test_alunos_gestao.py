"""Gestão de alunos por turma: editar, arquivar/reativar, transferir, excluir
(lógico e em massa) e EXCLUSÃO PERMANENTE (remove o aluno e todos os vínculos).
"""
from sqlalchemy import func, select

from app.models import (
    Aluno,
    Leitura,
    LogAuditoria,
    Matricula,
    Nota,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
)


def _base(escola_id: int) -> str:
    return f"/api/v1/escolas/{escola_id}"


def _popular_dados(cliente, escola_id: int, aluno) -> None:
    """Importa Matific + Elefante para o aluno — cria snapshots, leitura e nota."""
    cliente.post(f"{_base(escola_id)}/importacoes/confirmar", json={
        "plataforma": "matific", "formato": "resumo", "tipo": "texto",
        "linhas": [{"nome": aluno.nome,
                    "dados": {"atividades": 40, "pontuacao_media": 3.5, "estrelas": 100},
                    "aluno_id": aluno.id}]})
    cliente.post(f"{_base(escola_id)}/importacoes/confirmar", json={
        "plataforma": "elefante", "formato": "leituras", "tipo": "texto",
        "linhas": [{"nome": aluno.nome,
                    "dados": {"livro": "O Gato e a Lua", "nivel": "AA"},
                    "aluno_id": aluno.id}]})


# --- Editar -----------------------------------------------------------------

def test_editar_aluno(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    r = cliente.patch(f"{_base(escola_id)}/alunos/{ana.id}",
                      json={"nome": "Ana Beatriz S. Corrigida", "numero_chamada": 7})
    assert r.status_code == 200, r.text
    assert r.json()["nome"] == "Ana Beatriz S. Corrigida"
    db.refresh(ana)
    assert ana.numero_chamada == 7


# --- Arquivar / reativar (soft) + contagem da turma -------------------------

def test_arquivar_remove_da_contagem_e_reativar_restaura(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    turma = escola_completa["turma"]
    ana = escola_completa["alunos"][0]

    def total_turma() -> int:
        turmas = cliente.get(f"{_base(escola_id)}/turmas").json()
        return next(t["total_alunos"] for t in turmas if t["id"] == turma.id)

    assert total_turma() == 3
    r = cliente.post(f"{_base(escola_id)}/alunos/acoes",
                     json={"aluno_ids": [ana.id], "acao": "arquivar"})
    assert r.status_code == 200, r.text
    db.refresh(ana)
    assert ana.status == "arquivado"
    assert total_turma() == 2  # sumiu da contagem sem recarregar

    # Some da listagem padrão, mas aparece com incluir_inativos
    ativos = cliente.get(f"{_base(escola_id)}/turmas/{turma.id}/alunos").json()
    assert ana.id not in [a["id"] for a in ativos]
    todos = cliente.get(f"{_base(escola_id)}/turmas/{turma.id}/alunos?incluir_inativos=true").json()
    assert ana.id in [a["id"] for a in todos]

    cliente.post(f"{_base(escola_id)}/alunos/acoes",
                 json={"aluno_ids": [ana.id], "acao": "reativar"})
    db.refresh(ana)
    assert ana.status == "ativo"
    assert total_turma() == 3


def test_excluir_logico_em_massa(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    ids = [a.id for a in escola_completa["alunos"][:2]]
    r = cliente.post(f"{_base(escola_id)}/alunos/acoes",
                     json={"aluno_ids": ids, "acao": "excluir"})
    assert r.status_code == 200, r.text
    assert r.json()["afetados"] == 2
    for aluno in escola_completa["alunos"][:2]:
        db.refresh(aluno)
        assert aluno.status == "excluido"


# --- Transferir de turma ----------------------------------------------------

def test_transferir_de_turma_em_massa(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    origem = escola_completa["turma"]
    destino = Turma(escola_id=escola_id, nome="4º Ano B", ano_escolar="4º Ano", ano_letivo=2026)
    db.add(destino)
    db.commit()
    ids = [a.id for a in escola_completa["alunos"][:2]]

    r = cliente.post(f"{_base(escola_id)}/alunos/acoes",
                     json={"aluno_ids": ids, "acao": "transferir", "turma_id": destino.id})
    assert r.status_code == 200, r.text
    db.expire_all()
    for aid in ids:
        matricula = db.execute(
            select(Matricula).where(Matricula.aluno_id == aid, Matricula.ano_letivo == 2026)
        ).scalar_one()
        assert matricula.turma_id == destino.id
    # contagens: origem perde 2, destino ganha 2
    turmas = {t["id"]: t["total_alunos"] for t in cliente.get(f"{_base(escola_id)}/turmas").json()}
    assert turmas[origem.id] == 1
    assert turmas[destino.id] == 2


def test_transferir_exige_turma_destino(cliente, escola_completa):
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    r = cliente.post(f"{_base(escola_id)}/alunos/acoes",
                     json={"aluno_ids": [ana.id], "acao": "transferir"})
    assert r.status_code == 400


# --- Exclusão PERMANENTE (cascata) ------------------------------------------

def test_exclusao_permanente_remove_todos_os_vinculos(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    ana, joao = escola_completa["alunos"][0], escola_completa["alunos"][1]
    ana_id, ana_nome = ana.id, ana.nome
    _popular_dados(cliente, escola_id, ana)
    _popular_dados(cliente, escola_id, joao)

    # Pré-condição: Ana tem vínculos em todas as tabelas.
    def conta(modelo, aluno_id):
        return db.execute(select(func.count()).select_from(modelo)
                          .where(modelo.aluno_id == aluno_id)).scalar_one()
    assert conta(Matricula, ana.id) == 1
    assert conta(SnapshotMatific, ana.id) >= 1
    assert conta(SnapshotElefante, ana.id) >= 1
    assert conta(Leitura, ana.id) >= 1
    assert conta(Nota, ana.id) == 1

    r = cliente.post(f"{_base(escola_id)}/alunos/excluir-permanente",
                     json={"aluno_ids": [ana.id], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text
    assert r.json()["afetados"] == 1

    db.expire_all()  # descarta o cache da sessão de teste (a API usou outra)
    # Ana e TODOS os vínculos sumiram; nenhum órfão.
    assert db.get(Aluno, ana_id) is None
    for modelo in (Matricula, SnapshotMatific, SnapshotElefante, Leitura, Nota):
        assert conta(modelo, ana_id) == 0, modelo.__name__

    # João permanece intacto.
    assert db.get(Aluno, joao.id) is not None
    assert conta(SnapshotMatific, joao.id) >= 1

    # Auditoria preservada (§17) — mas SEM o nome do menor em texto claro
    # (LGPD/esquecimento): o entidade_id basta como referência anônima.
    log = db.execute(select(LogAuditoria)
                     .where(LogAuditoria.acao == "aluno.excluido_permanente")
                     .order_by(LogAuditoria.id.desc())).scalars().first()
    assert log is not None
    assert "nome" not in log.detalhes           # nome NÃO persiste em claro
    assert log.entidade_id == ana_id            # referência anônima preservada
    assert ana_nome not in str(log.detalhes)


def test_exclusao_permanente_esquece_nome_nos_logs_anteriores(cliente, db, escola_completa):
    """Direito ao esquecimento: ao excluir o aluno em definitivo, o nome civil
    do menor é anonimizado também nas entradas ANTERIORES do log (ex.: edição),
    não só omitido na entrada da exclusão."""
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    ana_id, ana_nome = ana.id, ana.nome

    # Uma edição gera um log com o nome do aluno em detalhes.
    cliente.patch(f"{_base(escola_id)}/alunos/{ana_id}",
                  json={"observacoes": "anotação"})
    logs_antes = db.execute(
        select(LogAuditoria).where(LogAuditoria.entidade == "aluno",
                                   LogAuditoria.entidade_id == ana_id)).scalars().all()
    assert any(ana_nome in str(l.detalhes) for l in logs_antes), \
        "pré-condição: algum log anterior cita o nome"

    r = cliente.post(f"{_base(escola_id)}/alunos/excluir-permanente",
                     json={"aluno_ids": [ana_id], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text

    db.expire_all()
    logs_depois = db.execute(
        select(LogAuditoria).where(LogAuditoria.entidade == "aluno",
                                   LogAuditoria.entidade_id == ana_id)).scalars().all()
    # Nenhuma entrada do aluno excluído ainda contém o nome civil em claro.
    for log in logs_depois:
        assert ana_nome not in str(log.detalhes), log.acao


def test_exclusao_permanente_exige_confirmacao(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    r = cliente.post(f"{_base(escola_id)}/alunos/excluir-permanente",
                     json={"aluno_ids": [ana.id], "confirmacao": "sim"})
    assert r.status_code == 400
    assert db.get(Aluno, ana.id) is not None  # nada foi apagado


# --- Listagem: busca e ordenação --------------------------------------------

def test_listar_alunos_da_turma_busca_e_ordena(cliente, escola_completa):
    escola_id = escola_completa["escola"].id
    turma = escola_completa["turma"]

    tudo = cliente.get(f"{_base(escola_id)}/turmas/{turma.id}/alunos?ordenar=nome").json()
    nomes = [a["nome"] for a in tudo]
    assert nomes == sorted(nomes)  # ordem alfabética
    assert all("created_at" in a for a in tudo)

    busca = cliente.get(f"{_base(escola_id)}/turmas/{turma.id}/alunos?busca=jo%C3%A3o").json()
    assert len(busca) == 1
    assert "João" in busca[0]["nome"]


# --- Fundir alunos duplicados -----------------------------------------------

def test_fundir_combina_matific_e_elefante_e_deduplica_leituras(cliente, db, escola_completa):
    """Caso real: os dados do mesmo aluno vieram em dois cadastros — Matific
    num, Elefante noutro. Fundir junta tudo num só, sem duplicar leituras."""
    escola_id = escola_completa["escola"].id
    manter, remover = escola_completa["alunos"][0], escola_completa["alunos"][1]

    # `manter` tem Matific + a leitura "O Gato e a Lua".
    _popular_dados(cliente, escola_id, manter)
    # `remover` tem Elefante: a MESMA "O Gato e a Lua" (duplicada) + uma única.
    for livro in ("O Gato e a Lua", "O Mapa Secreto"):
        cliente.post(f"{_base(escola_id)}/importacoes/confirmar", json={
            "plataforma": "elefante", "formato": "leituras", "tipo": "texto",
            "linhas": [{"nome": remover.nome,
                        "dados": {"livro": livro, "nivel": "AA"},
                        "aluno_id": remover.id}]})

    manter_id, remover_id = manter.id, remover.id  # antes de a fusão apagar
    resposta = cliente.post(f"{_base(escola_id)}/alunos/fundir", json={
        "manter_id": manter_id, "remover_id": remover_id, "confirmacao": "FUNDIR"})
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["leituras_movidas"] == 1        # só "O Mapa Secreto"
    assert resposta.json()["leituras_descartadas"] == 1    # "O Gato e a Lua" repetida

    # O `remover` deixou de existir; o `manter` ficou com tudo.
    db.expire_all()  # a fusão gravou por outra sessão; recarrega do banco
    assert db.get(Aluno, remover_id) is None
    assert db.execute(select(func.count()).select_from(SnapshotMatific)
                      .where(SnapshotMatific.aluno_id == manter_id)).scalar_one() >= 1
    assert db.execute(select(func.count()).select_from(SnapshotElefante)
                      .where(SnapshotElefante.aluno_id == manter_id)).scalar_one() >= 1
    livros = db.execute(select(func.count()).select_from(Leitura)
                        .where(Leitura.aluno_id == manter_id)).scalar_one()
    assert livros == 2                                     # união, sem repetir
    # Nenhum órfão apontando para o aluno removido.
    for modelo in (Leitura, SnapshotMatific, SnapshotElefante, Nota, Matricula):
        sobra = db.execute(select(func.count()).select_from(modelo)
                           .where(modelo.aluno_id == remover_id)).scalar_one()
        assert sobra == 0, modelo.__name__


def test_fundir_preserva_eventos_e_identidade_externa(cliente, db, escola_completa):
    """A fusão leva a linha do tempo (EventoAluno) e o vínculo UUID
    (IdentidadeExterna) do `remover` para o `manter`. Sem isso, o ON DELETE
    CASCADE apagaria em silêncio o histórico e o vínculo — e a próxima
    sincronização poderia recriar a duplicata, DESFAZENDO a fusão."""
    from datetime import datetime, timezone

    from app.models import EventoAluno, IdentidadeExterna

    escola_id = escola_completa["escola"].id
    manter, remover = escola_completa["alunos"][0], escola_completa["alunos"][1]
    manter_id, remover_id = manter.id, remover.id

    # `remover` carrega o vínculo UUID do Matific e um evento na linha do tempo.
    db.add(IdentidadeExterna(escola_id=escola_id, aluno_id=remover_id,
                             plataforma="matific", id_externo="uuid-abc-123"))
    db.add(EventoAluno(escola_id=escola_id, aluno_id=remover_id,
                       plataforma="matific", tipo_evento="atividade",
                       ocorrido_em=datetime(2026, 3, 1, tzinfo=timezone.utc),
                       chave_natural="evt-natural-1"))
    db.commit()

    resposta = cliente.post(f"{_base(escola_id)}/alunos/fundir", json={
        "manter_id": manter_id, "remover_id": remover_id, "confirmacao": "FUNDIR"})
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["eventos_movidos"] == 1
    assert resposta.json()["identidades_movidas"] == 1

    db.expire_all()
    assert db.get(Aluno, remover_id) is None
    # Evento e identidade agora pertencem ao `manter` (não sumiram no cascade).
    assert db.execute(select(func.count()).select_from(EventoAluno)
                      .where(EventoAluno.aluno_id == manter_id)).scalar_one() == 1
    ident = db.execute(select(IdentidadeExterna)
                       .where(IdentidadeExterna.aluno_id == manter_id)).scalar_one()
    assert ident.id_externo == "uuid-abc-123"    # vínculo UUID preservado
    # Nenhum órfão do aluno removido.
    for modelo in (EventoAluno, IdentidadeExterna):
        sobra = db.execute(select(func.count()).select_from(modelo)
                           .where(modelo.aluno_id == remover_id)).scalar_one()
        assert sobra == 0, modelo.__name__


def test_fundir_preserva_perfil_e_telemetria_do_quest(cliente, db, escola_completa):
    """A fusão leva o lado Quest (perfil + telemetria) do `remover` para o
    `manter`. Sem isso, o ON DELETE CASCADE apagaria tudo ao deletar o remover."""
    from datetime import datetime, timezone

    from app.quest.models import (
        QuestJornada, QuestMissao, QuestMundo, QuestPerfil, QuestTentativa,
    )

    escola_id = escola_completa["escola"].id
    manter, remover = escola_completa["alunos"][0], escola_completa["alunos"][1]
    # Missão real do catálogo (mundo→jornada→missão): a tentativa referencia uma
    # missão que EXISTE — como em produção, onde a integridade de FK está ligada.
    mundo = QuestMundo(slug="mat", nome="Planeta Matemática")
    db.add(mundo)
    db.flush()
    jornada = QuestJornada(mundo_id=mundo.id, nome="Trilha 1", ano_escolar="3º Ano")
    db.add(jornada)
    db.flush()
    missao = QuestMissao(jornada_id=jornada.id, nome="Missão 1")
    db.add(missao)
    db.flush()
    # `remover` tem perfil Quest com uma tentativa; `manter` não tem perfil.
    perfil = QuestPerfil(escola_id=escola_id, aluno_id=remover.id,
                         apelido="Astro", codigo_amigo="AST123")
    db.add(perfil)
    db.flush()
    db.add(QuestTentativa(escola_id=escola_id, perfil_id=perfil.id,
                          missao_id=missao.id,
                          iniciada_em=datetime.now(timezone.utc)))
    db.commit()
    perfil_id, manter_id, remover_id = perfil.id, manter.id, remover.id

    r = cliente.post(f"{_base(escola_id)}/alunos/fundir", json={
        "manter_id": manter_id, "remover_id": remover_id, "confirmacao": "FUNDIR"})
    assert r.status_code == 200, r.text
    assert r.json()["quest_perfil_movido"] == 1

    db.expire_all()
    # O perfil foi REATRIBUÍDO ao `manter` (não apagado), com a telemetria intacta.
    p = db.get(QuestPerfil, perfil_id)
    assert p is not None and p.aluno_id == manter_id
    assert db.execute(select(func.count()).select_from(QuestTentativa)
                      .where(QuestTentativa.perfil_id == perfil_id)).scalar_one() == 1


def test_fundir_exige_confirmacao_e_alunos_distintos(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    a, b = escola_completa["alunos"][0], escola_completa["alunos"][1]
    # Confirmação errada não funde nada.
    r1 = cliente.post(f"{_base(escola_id)}/alunos/fundir", json={
        "manter_id": a.id, "remover_id": b.id, "confirmacao": "sim"})
    assert r1.status_code == 400
    assert db.get(Aluno, b.id) is not None
    # Mesmo aluno dos dois lados é recusado.
    r2 = cliente.post(f"{_base(escola_id)}/alunos/fundir", json={
        "manter_id": a.id, "remover_id": a.id, "confirmacao": "FUNDIR"})
    assert r2.status_code == 400


def test_fundir_recusa_aluno_inativo(cliente, db, escola_completa):
    """Não pode manter um arquivado absorvendo um ativo — o aluno sumiria de
    todas as telas (que filtram status ativo)."""
    escola_id = escola_completa["escola"].id
    manter, remover = escola_completa["alunos"][0], escola_completa["alunos"][1]
    manter.status = "arquivado"
    db.commit()
    r = cliente.post(f"{_base(escola_id)}/alunos/fundir", json={
        "manter_id": manter.id, "remover_id": remover.id, "confirmacao": "FUNDIR"})
    assert r.status_code == 400
    db.expire_all()
    assert db.get(Aluno, remover.id) is not None       # nada foi apagado


def test_fundir_preserva_nota_de_ano_anterior(cliente, db, escola_completa):
    """Ao migrar a matrícula de um ano anterior, a NOTA daquele ano também
    precisa migrar — senão o histórico daquele ano some."""
    from app.models import Nota

    escola_id = escola_completa["escola"].id
    manter, remover = escola_completa["alunos"][0], escola_completa["alunos"][1]
    turma_id = escola_completa["turma"].id
    # `remover` tem matrícula + nota em 2025 (ano anterior); `manter` não.
    db.add(Matricula(escola_id=escola_id, aluno_id=remover.id,
                     turma_id=turma_id, ano_letivo=2025))
    db.add(Nota(escola_id=escola_id, aluno_id=remover.id, ano_letivo=2025,
                nota_matific=8.0, nota_elefante=7.0, nota_geral=7.5, posicao=1))
    db.commit()
    manter_id, remover_id = manter.id, remover.id

    r = cliente.post(f"{_base(escola_id)}/alunos/fundir", json={
        "manter_id": manter_id, "remover_id": remover_id, "confirmacao": "FUNDIR"})
    assert r.status_code == 200, r.text

    db.expire_all()
    nota_2025 = db.execute(select(Nota).where(
        Nota.aluno_id == manter_id, Nota.ano_letivo == 2025)).scalar_one_or_none()
    assert nota_2025 is not None                       # histórico preservado
    assert nota_2025.nota_geral == 7.5
    # E sem nota órfã apontando para o removido.
    assert db.execute(select(func.count()).select_from(Nota)
                      .where(Nota.aluno_id == remover_id)).scalar_one() == 0


def test_esquecimento_apaga_conversa_ia_que_cita_o_aluno(cliente, db, escola_completa):
    """LGPD (direito ao esquecimento): excluir aluno permanentemente apaga as
    conversas do assistente que citam o nome COMPLETO dele; conversa que cita
    OUTRO aluno permanece."""
    from app.models import ConversaIA, MensagemIA
    escola, admin = escola_completa["escola"], escola_completa["admin"]
    alvo, outro = escola_completa["alunos"][0], escola_completa["alunos"][1]

    cita = ConversaIA(escola_id=escola.id, usuario_id=admin.id, titulo="cita")
    naocita = ConversaIA(escola_id=escola.id, usuario_id=admin.id, titulo="nao")
    db.add_all([cita, naocita])
    db.flush()
    db.add_all([
        MensagemIA(conversa_id=cita.id, papel="assistente",
                   conteudo=f"O {alvo.nome} foi bem no Matific."),
        MensagemIA(conversa_id=naocita.id, papel="assistente",
                   conteudo=f"O {outro.nome} foi bem no Elefante."),
    ])
    db.commit()
    cita_id, naocita_id = cita.id, naocita.id

    r = cliente.post(f"{_base(escola.id)}/alunos/excluir-permanente",
                     json={"aluno_ids": [alvo.id], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text
    vivas = set(db.execute(select(ConversaIA.id)).scalars())
    assert cita_id not in vivas        # esquecida (citava o excluído)
    assert naocita_id in vivas          # preservada (cita outro aluno)


def test_esquecimento_e_case_insensitive_e_restrito_a_escola(cliente, db, escola_completa):
    """A correspondência do nome ignora caixa; e o esquecimento não toca conversa
    de OUTRA escola (mesmo com nome homônimo)."""
    from app.core.security import hash_senha
    from app.models import ConversaIA, Escola, MensagemIA, Usuario
    escola, admin = escola_completa["escola"], escola_completa["admin"]
    alvo = escola_completa["alunos"][0]

    outra = Escola(nome="OUTRA", ano_letivo_ativo=2026)
    db.add(outra)
    db.flush()
    admin_b = Usuario(escola_id=outra.id, nome="AdminB", email="b@e.local",
                      senha_hash=hash_senha("s3nh4"), cargo="admin")
    db.add(admin_b)
    db.flush()
    minusc = ConversaIA(escola_id=escola.id, usuario_id=admin.id, titulo="min")
    homonimo = ConversaIA(escola_id=outra.id, usuario_id=admin_b.id, titulo="B")
    db.add_all([minusc, homonimo])
    db.flush()
    db.add_all([
        MensagemIA(conversa_id=minusc.id, papel="usuario",
                   conteudo=f"como esta {alvo.nome.lower()}?"),   # minúsculas
        MensagemIA(conversa_id=homonimo.id, papel="assistente",
                   conteudo=f"O {alvo.nome} da outra escola."),
    ])
    db.commit()
    minusc_id, homonimo_id = minusc.id, homonimo.id

    r = cliente.post(f"{_base(escola.id)}/alunos/excluir-permanente",
                     json={"aluno_ids": [alvo.id], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text
    vivas = set(db.execute(select(ConversaIA.id)).scalars())
    assert minusc_id not in vivas       # caixa diferente também é apagada
    assert homonimo_id in vivas          # outra escola: intocada
