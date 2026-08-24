"""C-07 — o nome civil de um menor não pode sobreviver à exclusão "irreversível".

O achado da auditoria 360: ``_anonimizar_logs_do_aluno`` filtrava
``entidade == "aluno" AND entidade_id IN (ids)`` e só apagava a chave literal
``"nome"``. A produção grava o nome em OUTRAS chaves (``origem``, ``aluno``,
``nome_antigo``, ``nome_novo``, ``origem_linha``) e, no caminho de importação,
com ``entidade_id=None`` — e ``IN`` nunca casa NULL. Resultado medido: 4 de 5
linhas continuavam com o nome do menor depois da exclusão permanente.

E o teste que "provava" o esquecimento era tautológico: consultava com o MESMO
filtro do código com defeito, então só inspecionava as linhas que o anonimizador
garantidamente tocou — não podia falhar.

Aqui a verificação é feita **sem filtro nenhum**: varre TODO o log da escola,
como faria um perito respondendo a um pedido de titular. E o outro lado é
testado com o mesmo rigor: a trilha de auditoria tem de continuar ÚTIL (quem
fez, o quê, quando, sobre qual registro) — anonimizar não é apagar a auditoria.
"""
import pytest
from sqlalchemy import select

from app.models import Aluno, LogAuditoria, Notificacao
from app.services.audit import registrar

pytestmark = pytest.mark.usefixtures("cliente")


def _base(escola_id: int) -> str:
    return f"/api/v1/escolas/{escola_id}"


def _todos_os_logs(db, escola_id) -> list[LogAuditoria]:
    """SEM filtro — o ponto do teste. Um pedido de esquecimento não pergunta
    ao código com defeito quais linhas ele considera relevantes."""
    return db.execute(select(LogAuditoria)
                      .where(LogAuditoria.escola_id == escola_id)).scalars().all()


def _semeia_logs_como_a_producao(db, escola_id, aluno_id, nome, usuario_id):
    """As 5 formas que a produção realmente grava, com a origem de cada uma.

    Copiadas dos ``registrar(...)`` reais para que este teste falhe se alguém
    reintroduzir a forma antiga. As três primeiras têm ``entidade_id=None`` —
    é o que fazia o ``IN`` não casar.
    """
    # academico.py — criação recusada por correspondência insegura
    registrar(db, "aluno.criacao_recusada", escola_id=escola_id, usuario_id=usuario_id,
              entidade="aluno", entidade_id=None,
              detalhes={"nome": nome, "decisao": "REVIEW_REQUIRED",
                        "motivo": "correspondencia_insegura"})
    # importacoes.py — revisão necessária no casamento do roster
    registrar(db, "aluno.revisao_necessaria", escola_id=escola_id,
              entidade="aluno", entidade_id=None,
              detalhes={"origem": nome, "turma": "3º Ano A",
                        "decisao": "REVIEW_REQUIRED",
                        "motivo": "correspondencia_insegura"})
    # importacoes.py — criação automática no caminho de importação NORMAL
    registrar(db, "aluno.criado_auto", escola_id=escola_id, entidade="aluno",
              entidade_id=None,
              detalhes={"origem": nome, "turma": "3º Ano A",
                        "decisao": "NEW_STUDENT",
                        "motivo": "nenhum candidato plausivel na turma"})
    # importacoes.py — vínculo automático (nome da planilha ≠ nome da base)
    registrar(db, "aluno.vinculado_auto", escola_id=escola_id,
              entidade="aluno", entidade_id=aluno_id,
              detalhes={"origem": "ANA B. SOUZA", "aluno": nome,
                        "turma": "3º Ano A", "confianca": "alta",
                        "candidatos": 1,
                        "motivo": "único candidato plausível na mesma turma"})
    # importacoes.py — identidade trocada pela Lista Piloto
    registrar(db, "aluno.identidade_vinculada", escola_id=escola_id,
              usuario_id=usuario_id, entidade="aluno", entidade_id=aluno_id,
              detalhes={"nome_antigo": "Ana Souza", "nome_novo": nome,
                        "origem_linha": nome, "ra": "12345",
                        "motivo": "abreviacao", "origem": "importacao_matriculas"})
    db.commit()


# --- 1. O esquecimento de fato ------------------------------------------------

def test_nome_do_menor_nao_sobrevive_em_nenhuma_linha_do_log(cliente, db, escola_completa):
    """O teste central do C-07, feito como a auditoria fez: varredura total."""
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    ana_id, ana_nome = ana.id, ana.nome
    _semeia_logs_como_a_producao(db, escola_id, ana_id, ana_nome,
                                 escola_completa["admin"].id)

    # Pré-condição: o nome ESTÁ lá antes (senão o teste não prova nada).
    antes = [l for l in _todos_os_logs(db, escola_id) if ana_nome in str(l.detalhes)]
    assert len(antes) >= 5, "pré-condição: as 5 formas gravam o nome"

    r = cliente.post(f"{_base(escola_id)}/alunos/excluir-permanente",
                     json={"aluno_ids": [ana_id], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text

    db.expire_all()
    sobreviventes = [l for l in _todos_os_logs(db, escola_id)
                     if ana_nome in str(l.detalhes)]
    assert not sobreviventes, (
        "o nome civil do menor sobreviveu à exclusão permanente em: "
        + ", ".join(f"{l.acao}(entidade_id={l.entidade_id})" for l in sobreviventes))


def test_esquecimento_pega_variacao_de_acento_e_caixa(cliente, db, escola_completa):
    """A planilha escreve “ABRAAO”, a base tem “Abraão”. Se o esquecimento
    comparasse string crua, o nome ficaria no log."""
    escola_id = escola_completa["escola"].id
    turma = escola_completa["turma"]
    aluno = Aluno(escola_id=escola_id, nome="Abraão Lopes Rocha")
    db.add(aluno)
    db.flush()
    from app.models import Matricula
    db.add(Matricula(escola_id=escola_id, aluno_id=aluno.id, turma_id=turma.id,
                     ano_letivo=2026))
    db.commit()
    aluno_id = aluno.id

    registrar(db, "aluno.criado_auto", escola_id=escola_id, entidade="aluno",
              entidade_id=None,
              detalhes={"origem": "ABRAAO LOPES ROCHA", "turma": "3º Ano A"})
    registrar(db, "aluno.revisao_necessaria", escola_id=escola_id, entidade="aluno",
              entidade_id=None,
              detalhes={"origem": "  abraão   lopes rocha  ", "turma": "3º Ano A"})
    db.commit()

    r = cliente.post(f"{_base(escola_id)}/alunos/excluir-permanente",
                     json={"aluno_ids": [aluno_id], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text

    db.expire_all()
    for log in _todos_os_logs(db, escola_id):
        texto = str(log.detalhes).casefold()
        assert "abraao" not in texto and "abraão" not in texto, log.acao


def test_esquecimento_alcanca_nome_aninhado_da_fusao(cliente, db, escola_completa):
    """``aluno.fundido`` guarda ``foto_pre_fusao`` — um retrato ANINHADO do
    cadastro apagado. O nome está a dois níveis de profundidade."""
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    ana_id, ana_nome = ana.id, ana.nome

    registrar(db, "aluno.fundido", escola_id=escola_id,
              usuario_id=escola_completa["admin"].id,
              entidade="aluno", entidade_id=ana_id,
              detalhes={"mantido": {"id": ana_id, "nome": ana_nome},
                        "removido": {"id": 999, "nome": ana_nome},
                        "foto_pre_fusao": {"cadastro": {"nome": ana_nome,
                                                        "numero_chamada": 7},
                                           "matriculas": [{"ano_letivo": 2026}]},
                        "leituras_movidas": 3})
    db.commit()

    r = cliente.post(f"{_base(escola_id)}/alunos/excluir-permanente",
                     json={"aluno_ids": [ana_id], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text

    db.expire_all()
    for log in _todos_os_logs(db, escola_id):
        assert ana_nome not in str(log.detalhes), log.acao


def test_esquecimento_pega_nome_solto_dentro_de_lista(cliente, db, escola_completa):
    """Nome sem chave própria (item de lista) também precisa cair."""
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    ana_id, ana_nome = ana.id, ana.nome

    registrar(db, "aluno.duplicados_corrigidos", escola_id=escola_id,
              entidade="escola", entidade_id=escola_id,
              detalhes={"fusoes": 1, "envolvidos": [ana_nome, "Outra Criança"]})
    db.commit()

    r = cliente.post(f"{_base(escola_id)}/alunos/excluir-permanente",
                     json={"aluno_ids": [ana_id], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text

    db.expire_all()
    for log in _todos_os_logs(db, escola_id):
        assert ana_nome not in str(log.detalhes), log.acao


def test_exclusao_de_turma_com_alunos_tambem_esquece(cliente, db, escola_completa):
    """O outro caminho que apaga criança em definitivo usa a mesma função —
    o esquecimento não pode depender da porta por onde se entrou."""
    escola_id = escola_completa["escola"].id
    turma = escola_completa["turma"]
    ana = escola_completa["alunos"][0]
    ana_nome = ana.nome
    _semeia_logs_como_a_producao(db, escola_id, ana.id, ana_nome,
                                 escola_completa["admin"].id)

    r = cliente.delete(f"{_base(escola_id)}/turmas/{turma.id}?com_alunos=true")
    assert r.status_code == 200, r.text

    db.expire_all()
    assert db.execute(select(Aluno).where(Aluno.escola_id == escola_id)
                      ).scalars().all() == [], "pré-condição: a turma levou os alunos"
    for log in _todos_os_logs(db, escola_id):
        assert ana_nome not in str(log.detalhes), log.acao


def test_esquecimento_pega_nome_abreviado_da_planilha(cliente, db, escola_completa):
    """O caso que motivou o casamento aproximado: a planilha trouxe “ANA B.
    SOUZA” e a base tem “Ana Beatriz Souza”. Normalizar não iguala as duas —
    é por isso que a redação por CHAVE existe."""
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    ana_id = ana.id

    registrar(db, "aluno.vinculado_auto", escola_id=escola_id, entidade="aluno",
              entidade_id=ana_id,
              detalhes={"origem": "ANA B. SOUZA", "aluno": ana.nome,
                        "turma": "3º Ano A", "confianca": "alta",
                        "motivo": "único candidato plausível na mesma turma"})
    db.commit()

    r = cliente.post(f"{_base(escola_id)}/alunos/excluir-permanente",
                     json={"aluno_ids": [ana_id], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text

    db.expire_all()
    log = db.execute(select(LogAuditoria)
                     .where(LogAuditoria.acao == "aluno.vinculado_auto")).scalars().one()
    assert log.detalhes["origem"] == "[removido]", "o nome abreviado sobreviveu"
    assert log.detalhes["aluno"] == "[removido]"
    # O que não é nome permanece — a decisão continua auditável.
    assert log.detalhes["turma"] == "3º Ano A"
    assert log.detalhes["confianca"] == "alta"


def test_procedencia_nao_e_confundida_com_nome(cliente, db, escola_completa):
    """``origem`` é sobrecarregada: ora é nome da planilha, ora é a PROCEDÊNCIA
    do dado. Apagar “matific”/“importacao” seria sobre-redação — o auditor
    perde de onde veio a mudança sem que ninguém ganhe privacidade."""
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    ana_id = ana.id

    registrar(db, "aluno.fora_lista_piloto", escola_id=escola_id, entidade="aluno",
              entidade_id=ana_id,
              detalhes={"nome": ana.nome, "origem": "importacao_matriculas"})
    registrar(db, "aluno.turma_alterada", escola_id=escola_id, entidade="aluno",
              entidade_id=ana_id,
              detalhes={"de": "3º Ano A", "para": "3º Ano B", "origem": "matific"})
    db.commit()

    r = cliente.post(f"{_base(escola_id)}/alunos/excluir-permanente",
                     json={"aluno_ids": [ana_id], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text

    db.expire_all()
    logs = {l.acao: l for l in _todos_os_logs(db, escola_id)}
    assert logs["aluno.fora_lista_piloto"].detalhes["nome"] == "[removido]"
    assert logs["aluno.fora_lista_piloto"].detalhes["origem"] == "importacao_matriculas"
    assert logs["aluno.turma_alterada"].detalhes["origem"] == "matific"
    assert logs["aluno.turma_alterada"].detalhes["para"] == "3º Ano B"


def test_esquecimento_pega_nome_citado_dentro_de_uma_frase(cliente, db, escola_completa):
    """Defesa para o futuro: se alguém passar a guardar um aviso em texto
    corrido no ``detalhes``, o nome no meio da frase não pode escapar."""
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    ana_id, ana_nome = ana.id, ana.nome

    registrar(db, "aluno.revisao_necessaria", escola_id=escola_id, entidade="aluno",
              entidade_id=None,
              detalhes={"aviso": f"“{ana_nome}” parece um aluno já cadastrado "
                                 "na turma 3º Ano A.", "turma": "3º Ano A"})
    db.commit()

    r = cliente.post(f"{_base(escola_id)}/alunos/excluir-permanente",
                     json={"aluno_ids": [ana_id], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text

    db.expire_all()
    for log in _todos_os_logs(db, escola_id):
        assert ana_nome not in str(log.detalhes), log.acao


def test_nome_curto_nao_colide_com_nome_maior_de_outra_crianca(cliente, db, escola_completa):
    """Colisão real: “Ana Souza” é substring de “Mari*ana Souza* Silva”. Sem
    fronteira de palavra, excluir uma criança apagaria o nome de outra que
    continua matriculada."""
    from app.models import Matricula

    escola_id = escola_completa["escola"].id
    turma = escola_completa["turma"]
    ana = Aluno(escola_id=escola_id, nome="Ana Souza")
    mariana = Aluno(escola_id=escola_id, nome="Mariana Souza Silva")
    db.add_all([ana, mariana])
    db.flush()
    for aluno in (ana, mariana):
        db.add(Matricula(escola_id=escola_id, aluno_id=aluno.id,
                         turma_id=turma.id, ano_letivo=2026))
    db.commit()
    ana_id, mariana_id = ana.id, mariana.id

    registrar(db, "aluno.criado", escola_id=escola_id, entidade="aluno",
              entidade_id=mariana_id, detalhes={"nome": "Mariana Souza Silva"})
    registrar(db, "aluno.revisao_necessaria", escola_id=escola_id, entidade="aluno",
              entidade_id=None,
              detalhes={"aviso": "“Mariana Souza Silva” já está cadastrada."})
    db.commit()

    r = cliente.post(f"{_base(escola_id)}/alunos/excluir-permanente",
                     json={"aluno_ids": [ana_id], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text

    db.expire_all()
    logs = {l.acao: l for l in _todos_os_logs(db, escola_id)}
    assert logs["aluno.criado"].detalhes["nome"] == "Mariana Souza Silva"
    assert "Mariana Souza Silva" in logs["aluno.revisao_necessaria"].detalhes["aviso"]
    # E a criança que continua na escola segue no banco.
    assert db.get(Aluno, mariana_id) is not None


def test_nome_de_uma_palavra_so_nao_causa_sobre_redacao(cliente, db, escola_completa):
    """O contrário do teste acima: um nome de uma palavra só não pode ser
    caçado dentro de outras palavras — “Ana” não torna “Susana” um alvo."""
    from app.models import Matricula

    escola_id = escola_completa["escola"].id
    turma = escola_completa["turma"]
    ana = Aluno(escola_id=escola_id, nome="Ana")
    db.add(ana)
    db.flush()
    db.add(Matricula(escola_id=escola_id, aluno_id=ana.id, turma_id=turma.id,
                     ano_letivo=2026))
    db.commit()
    ana_id = ana.id

    registrar(db, "aluno.criado", escola_id=escola_id, entidade="aluno",
              entidade_id=99, detalhes={"nome": "Susana Ananias Ribeiro"})
    db.commit()

    r = cliente.post(f"{_base(escola_id)}/alunos/excluir-permanente",
                     json={"aluno_ids": [ana_id], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text

    db.expire_all()
    log = db.execute(select(LogAuditoria)
                     .where(LogAuditoria.acao == "aluno.criado")).scalars().one()
    assert log.detalhes["nome"] == "Susana Ananias Ribeiro"


def test_esquecimento_alcanca_o_nome_escolhido_no_quest(cliente, db, escola_completa):
    """``quest.nome_escolhido`` guarda como a criança pediu para ser chamada —
    normalmente só o primeiro nome. Também é nome civil de menor."""
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    ana_id = ana.id

    registrar(db, "quest.nome_escolhido", escola_id=escola_id, entidade="aluno",
              entidade_id=ana_id, detalhes={"nome": "Ana"})
    db.commit()

    r = cliente.post(f"{_base(escola_id)}/alunos/excluir-permanente",
                     json={"aluno_ids": [ana_id], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text

    db.expire_all()
    log = db.execute(select(LogAuditoria)
                     .where(LogAuditoria.acao == "quest.nome_escolhido")).scalars().one()
    assert log.detalhes["nome"] == "[removido]"


# --- 2. Referências indiretas -------------------------------------------------

def test_avisos_da_crianca_excluida_nao_ficam_apontando_para_ela(cliente, db, escola_completa):
    """``Notificacao.aluno_id`` sobrevive à exclusão (não tem FK). É ponteiro
    para uma criança que pediu para ser esquecida — e o banco reaproveita IDs,
    então o aviso passaria a apontar para outra criança."""
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    ana_id = ana.id
    db.add(Notificacao(escopo="escola", escola_id=escola_id, tipo="aluno.criado",
                       titulo="Novo aluno cadastrado", rota=f"/alunos/{ana_id}",
                       entidade="aluno", entidade_id=ana_id, aluno_id=ana_id))
    db.add(Notificacao(escopo="escola", escola_id=escola_id, tipo="importacao.concluida",
                       titulo="Nova importação de dados concluída", rota="/importacoes"))
    db.commit()

    r = cliente.post(f"{_base(escola_id)}/alunos/excluir-permanente",
                     json={"aluno_ids": [ana_id], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text

    db.expire_all()
    restantes = db.execute(select(Notificacao)
                           .where(Notificacao.escola_id == escola_id)).scalars().all()
    assert all(n.aluno_id != ana_id for n in restantes)
    # Aviso que não toca criança nenhuma continua (não é faxina cega).
    assert any(n.tipo == "importacao.concluida" for n in restantes)


# --- 3. O outro lado: a auditoria continua útil -------------------------------

def test_trilha_de_auditoria_continua_util_depois_do_esquecimento(cliente, db, escola_completa):
    """Anonimizar ≠ apagar a auditoria. Depois do esquecimento, o log ainda
    responde: QUEM fez, O QUÊ, QUANDO e sobre QUAL registro (id anônimo)."""
    escola_id = escola_completa["escola"].id
    admin = escola_completa["admin"]
    ana = escola_completa["alunos"][0]
    ana_id, ana_nome = ana.id, ana.nome
    _semeia_logs_como_a_producao(db, escola_id, ana_id, ana_nome, admin.id)
    quantos_antes = len(_todos_os_logs(db, escola_id))

    r = cliente.post(f"{_base(escola_id)}/alunos/excluir-permanente",
                     json={"aluno_ids": [ana_id], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text

    db.expire_all()
    logs = _todos_os_logs(db, escola_id)
    # Nada foi DELETADO — a trilha é permanente por design (models/nota.py).
    assert len(logs) >= quantos_antes

    por_acao = {l.acao: l for l in logs}
    # O "quê/quando/por quem/sobre qual registro" sobrevive intacto.
    vinculo = por_acao["aluno.identidade_vinculada"]
    assert vinculo.usuario_id == admin.id
    assert vinculo.entidade == "aluno" and vinculo.entidade_id == ana_id
    assert vinculo.created_at is not None
    assert vinculo.detalhes["motivo"] == "abreviacao"       # o PORQUÊ técnico fica
    assert vinculo.detalhes["origem"] == "importacao_matriculas"
    assert vinculo.detalhes["ra"] == "12345"

    revisao = por_acao["aluno.revisao_necessaria"]
    assert revisao.detalhes["turma"] == "3º Ano A"          # contexto operacional fica
    assert revisao.detalhes["decisao"] == "REVIEW_REQUIRED"

    # E a própria exclusão fica registrada, com autor e alvo.
    exclusao = por_acao["aluno.excluido_permanente"]
    assert exclusao.usuario_id == admin.id and exclusao.entidade_id == ana_id

    # O que sumiu foi só o nome — trocado por marca explícita, não por vazio
    # (some o dado pessoal, fica a evidência de que ali havia um nome).
    assert vinculo.detalhes["nome_antigo"] == "[removido]"
    assert vinculo.detalhes["nome_novo"] == "[removido]"


def test_esquecimento_nao_atinge_aluno_que_continua_na_escola(cliente, db, escola_completa):
    """Sobre-redação também é defeito: apagar o nome de quem NÃO foi excluído
    destrói a auditoria de uma criança que continua matriculada."""
    escola_id = escola_completa["escola"].id
    ana, joao = escola_completa["alunos"][0], escola_completa["alunos"][1]
    ana_id, joao_nome = ana.id, joao.nome

    registrar(db, "aluno.criado", escola_id=escola_id, entidade="aluno",
              entidade_id=joao.id, detalhes={"nome": joao_nome})
    registrar(db, "aluno.revisao_necessaria", escola_id=escola_id, entidade="aluno",
              entidade_id=None, detalhes={"origem": joao_nome, "turma": "3º Ano A"})
    db.commit()

    r = cliente.post(f"{_base(escola_id)}/alunos/excluir-permanente",
                     json={"aluno_ids": [ana_id], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text

    db.expire_all()
    logs = {l.acao: l for l in _todos_os_logs(db, escola_id)}
    assert logs["aluno.criado"].detalhes["nome"] == joao_nome
    assert logs["aluno.revisao_necessaria"].detalhes["origem"] == joao_nome


def test_esquecimento_nao_vaza_para_outra_escola(cliente, db, escola_completa):
    """Escopo: o log de outra escola com um homônimo não pode ser tocado."""
    from app.models import Escola

    escola_id = escola_completa["escola"].id
    outra = Escola(nome="OUTRA", ano_letivo_ativo=2026)
    db.add(outra)
    db.flush()
    ana = escola_completa["alunos"][0]
    ana_id, ana_nome = ana.id, ana.nome
    registrar(db, "aluno.criado", escola_id=outra.id, entidade="aluno",
              entidade_id=4242, detalhes={"nome": ana_nome})
    db.commit()

    r = cliente.post(f"{_base(escola_id)}/alunos/excluir-permanente",
                     json={"aluno_ids": [ana_id], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text

    db.expire_all()
    outro_log = db.execute(select(LogAuditoria)
                           .where(LogAuditoria.escola_id == outra.id)).scalars().one()
    assert outro_log.detalhes["nome"] == ana_nome


def test_exclusao_em_lote_esquece_todos(cliente, db, escola_completa):
    escola_id = escola_completa["escola"].id
    ana, joao = escola_completa["alunos"][0], escola_completa["alunos"][1]
    nomes = [ana.nome, joao.nome]
    for aluno in (ana, joao):
        registrar(db, "aluno.criado_auto", escola_id=escola_id, entidade="aluno",
                  entidade_id=None, detalhes={"origem": aluno.nome, "turma": "3º Ano A"})
    db.commit()

    r = cliente.post(f"{_base(escola_id)}/alunos/excluir-permanente",
                     json={"aluno_ids": [ana.id, joao.id], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text

    db.expire_all()
    for log in _todos_os_logs(db, escola_id):
        for nome in nomes:
            assert nome not in str(log.detalhes), f"{log.acao}: {nome}"


def test_o_teste_antigo_nao_bastava(db, escola_completa):
    """Documenta por que a suíte dava confiança falsa: consultar com o MESMO
    filtro do anonimizador é tautológico. Este teste prova que existem linhas
    do aluno FORA daquele filtro — as que escapavam."""
    escola_id = escola_completa["escola"].id
    ana = escola_completa["alunos"][0]
    _semeia_logs_como_a_producao(db, escola_id, ana.id, ana.nome,
                                 escola_completa["admin"].id)

    filtro_antigo = db.execute(
        select(LogAuditoria).where(LogAuditoria.escola_id == escola_id,
                                   LogAuditoria.entidade == "aluno",
                                   LogAuditoria.entidade_id == ana.id)).scalars().all()
    todos = [l for l in _todos_os_logs(db, escola_id) if ana.nome in str(l.detalhes)]
    assert len(todos) > len(filtro_antigo), (
        "se o filtro antigo enxergasse tudo, o achado C-07 não existiria")
