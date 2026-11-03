"""Exclusão permanente de aluno: NENHUMA ocorrência do nome (nem do id) sobra.

Achado 3 da auditoria de 20/10/2026: o esquecimento anonimizava o log de auditoria,
mas o nome e o id da criança continuavam na fila de revisões de identidade (nome
recebido, linhas, candidatos), em mensagens de sincronização, no nome do arquivo
original de relatório individual (e no arquivo) e nas cópias em /exports.

A verificação é feita como um perito faria: varre TODAS as tabelas do schema, todas
as colunas de texto e JSON, sem perguntar ao código quais ele considera relevantes.
Dados 100% fictícios.
"""
from datetime import datetime

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.database import Base
from app.models import (
    Aluno,
    EventoAluno,
    IdentidadeExterna,
    Importacao,
    LogAuditoria,
    Matricula,
    Nota,
    Notificacao,
    RevisaoIdentidade,
    SincronizacaoAlerta,
    SincronizacaoExecucao,
    SincronizacaoLog,
    SnapshotMatific,
    Usuario,
)
from app.quest.models import QuestCredencialAluno, QuestPerfil
from app.quest.services import credenciais as svc_credenciais
from app.routers import academico
from app.services.audit import registrar
from app.services.exclusao_aluno import MARCA_REMOVIDO, NomesAlvo

NOME = "Aluna Teste Exclusiva Lima"
APELIDO_ESCOLHIDO = "Bibi"           # escolhido no Quest — sem pedaço do nome civil
NOME_FICA = "Aluno Teste Permanece Rocha"
SOBRENOME_DISTINTO = "exclusiva"     # só a criança excluída tem esta palavra


def _base(escola_id):
    return f"/api/v1/escolas/{escola_id}"


def _normal(texto: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", texto)
                   if unicodedata.category(c) != "Mn").casefold()


def _varrer_tudo(db) -> list[tuple[str, str, str]]:
    """(tabela, coluna, valor) de TODA coluna de texto/JSON de TODA tabela."""
    from sqlalchemy import JSON, String, Text

    achados = []
    for tabela in Base.metadata.sorted_tables:
        colunas = [c for c in tabela.columns if isinstance(c.type, (String, Text, JSON))]
        if not colunas:
            continue
        for linha in db.execute(select(*colunas)).all():
            for coluna, valor in zip(colunas, linha):
                if valor is not None:
                    achados.append((tabela.name, coluna.name, str(valor)))
    return achados


@pytest.fixture
def pastas(tmp_path, monkeypatch):
    uploads, exports = tmp_path / "uploads", tmp_path / "exports"
    (uploads / "elefante").mkdir(parents=True)
    exports.mkdir()
    monkeypatch.setattr(settings, "UPLOADS_DIR", uploads)
    monkeypatch.setattr(settings, "EXPORTS_DIR", exports)
    return {"uploads": uploads, "exports": exports}


@pytest.fixture
def cenario(db, escola_completa, pastas):
    """A criança a excluir com dado em TODO lugar que a produção grava, e uma
    colega que fica (para provar que nada dela é tocado além do necessário)."""
    esc, turma, admin = escola_completa["escola"], escola_completa["turma"], \
        escola_completa["admin"]
    sai = Aluno(escola_id=esc.id, nome=NOME, status="ativo")
    fica = Aluno(escola_id=esc.id, nome=NOME_FICA, status="ativo")
    db.add_all([sai, fica])
    db.flush()
    for aluno in (sai, fica):
        db.add(Matricula(escola_id=esc.id, aluno_id=aluno.id, turma_id=turma.id,
                         ano_letivo=2026))
    db.add(IdentidadeExterna(escola_id=esc.id, aluno_id=sai.id, plataforma="matific",
                             id_externo="uuid-teste-sai"))
    individual = "20261001_101010_relatorio_aluna_teste_exclusiva_lima.pdf"
    de_turma = "20261001_101010_relatorio_turma_5a.pdf"
    (pastas["uploads"] / "elefante" / individual).write_bytes(b"%PDF individual")
    (pastas["uploads"] / "elefante" / de_turma).write_bytes(b"%PDF turma")
    (pastas["exports"] / "ranking_20261001_101010.pdf").write_bytes(b"%PDF copia")
    (pastas["exports"] / ".gitkeep").write_bytes(b"")
    imp_ind = Importacao(escola_id=esc.id, usuario_id=admin.id, plataforma="elefante",
                         tipo="pdf", arquivo_original=f"uploads/elefante/{individual}")
    imp_turma = Importacao(escola_id=esc.id, usuario_id=admin.id, plataforma="elefante",
                           tipo="pdf", arquivo_original=f"uploads/elefante/{de_turma}")
    db.add_all([imp_ind, imp_turma])
    db.flush()
    db.add(SnapshotMatific(escola_id=esc.id, aluno_id=sai.id, importacao_id=imp_turma.id,
                           estrelas=10))
    db.add(EventoAluno(escola_id=esc.id, aluno_id=sai.id, plataforma="elefante",
                       tipo_evento="leitura", ocorrido_em=datetime(2026, 10, 1, 10),
                       chave_natural="evento-teste-1", conteudo_titulo="Livro Teste"))
    db.add(Nota(escola_id=esc.id, aluno_id=sai.id, ano_letivo=2026))
    # Quest: credencial, perfil com o nome escolhido e o log da cerimônia.
    item = svc_credenciais.garantir_credencial_aluno(db, esc.id, sai)
    item["perfil"].nome_exibicao = APELIDO_ESCOLHIDO
    registrar(db, "quest.nome_escolhido", escola_id=esc.id, entidade="aluno",
              entidade_id=sai.id, detalhes={"nome": APELIDO_ESCOLHIDO})
    # Revisões: 3 dela (resolvida para ela; pela identidade externa; pelo nome) e
    # 1 da colega que a listava como candidata.
    comum = dict(escola_id=esc.id, chave="k", chave_identidade="ki", motivo="ambiguo")
    db.add_all([
        RevisaoIdentidade(**comum, plataforma="elefante", nome_recebido="ALUNA TESTE EXCLUSIVA",
                          status="resolvida", aluno_escolhido_id=sai.id,
                          candidatos=[{"aluno_id": sai.id, "nome": NOME}],
                          linhas=[{"nome": "ALUNA TESTE EXCLUSIVA", "livros_unicos": 3}],
                          resolucao={"acao": "associar", "aluno_id": sai.id}),
        RevisaoIdentidade(**comum, plataforma="matific", id_externo="uuid-teste-sai",
                          nome_recebido="A. T. EXCLUSIVA",
                          linhas=[{"nome": "A. T. EXCLUSIVA", "estrelas": 5}]),
        RevisaoIdentidade(**comum, plataforma="elefante", nome_recebido=NOME.upper(),
                          linhas=[{"nome": NOME.upper()}]),
        RevisaoIdentidade(**comum, plataforma="elefante", nome_recebido="ALUNO TESTE PERMANECE",
                          candidatos=[{"aluno_id": fica.id, "nome": NOME_FICA},
                                      {"aluno_id": sai.id, "nome": NOME}],
                          linhas=[{"nome": "ALUNO TESTE PERMANECE", "livros_unicos": 2}],
                          contexto={"observacao": f"parecido com {NOME} da mesma sala"}),
    ])
    # Avisos: pelo aluno_id e só pela entidade.
    db.add_all([
        Notificacao(escopo="escola", escola_id=esc.id, tipo="aluno.criado",
                    titulo="Novo aluno cadastrado", aluno_id=sai.id),
        Notificacao(escopo="escola", escola_id=esc.id, tipo="aluno.revisao_necessaria",
                    titulo="Importação: aluno com correspondência insegura — revisar",
                    entidade="aluno", entidade_id=sai.id),
        Notificacao(escopo="escola", escola_id=esc.id, tipo="importacao.concluida",
                    titulo="Nova importação de dados concluída"),
    ])
    # Sincronização com o nome em mensagem de erro (ex.: texto de exceção do parser).
    execucao = SincronizacaoExecucao(escola_id=esc.id, plataforma="elefante",
                                     origem="manual", status="erro",
                                     erro_resumo=f"Linha de {NOME.upper()} sem turma")
    db.add(execucao)
    db.flush()
    db.add(SincronizacaoLog(execucao_id=execucao.id, escola_id=esc.id, etapa="validacao",
                            nivel="warn", mensagem=f"Aluna “{NOME}” ignorada; 3 linhas ok"))
    db.add(SincronizacaoAlerta(escola_id=esc.id, plataforma="elefante", tipo="falha_download",
                               mensagem=f"Relatório de {NOME} não baixou"))
    # Log de auditoria: com nome recebido (chave nova), sem escola (rede) e da colega.
    # A entrada sem escola é DELA (entidade/entidade_id): é só essa que a exclusão
    # feita pela escola alcança entre as globais (as demais: test_exclusao_escopo_
    # e_homonimos.py prova que ficam intactas).
    registrar(db, "identidade.revisao_resolvida", escola_id=esc.id, usuario_id=admin.id,
              entidade="aluno", entidade_id=sai.id,
              detalhes={"nome_recebido": "A. T. EXCLUSIVA", "acao": "associar"})
    registrar(db, "rede.relatorio_exportado", entidade="aluno", entidade_id=sai.id,
              detalhes={"citados": [NOME, "Outra Pessoa"]})
    registrar(db, "aluno.criado", escola_id=esc.id, entidade="aluno", entidade_id=fica.id,
              detalhes={"nome": NOME_FICA})
    db.commit()
    return {"escola": esc, "sai": sai.id, "fica": fica.id, "admin": admin,
            "individual": pastas["uploads"] / "elefante" / individual,
            "de_turma": pastas["uploads"] / "elefante" / de_turma,
            "copia": pastas["exports"] / "ranking_20261001_101010.pdf",
            "gitkeep": pastas["exports"] / ".gitkeep"}


def _excluir(cliente, cenario):
    """Exclusão permanente pela API. ``cliente`` é o Admin Global: a exclusão
    física de aluno é só dele (D19 — test_aluno_exclusao_permanente_admin_global)."""
    r = cliente.post(f"{_base(cenario['escola'].id)}/alunos/excluir-permanente",
                     json={"aluno_ids": [cenario["sai"]], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text


def test_pre_condicao_o_nome_esta_espalhado(db, cenario):
    """Sem isto o teste principal não provaria nada."""
    onde = {t for t, _, v in _varrer_tudo(db) if SOBRENOME_DISTINTO in _normal(v)}
    assert {"revisoes_identidade", "sincronizacao_logs", "sincronizacao_alertas",
            "sincronizacao_execucoes", "importacoes", "logs_auditoria", "alunos"} <= onde


def test_nenhuma_ocorrencia_do_nome_sobra_em_tabela_nenhuma(cliente_global, db, cenario):
    _excluir(cliente_global, cenario)
    db.expire_all()
    sobras = [(t, c) for t, c, v in _varrer_tudo(db)
              if SOBRENOME_DISTINTO in _normal(v) or _normal(NOME) in _normal(v)]
    assert not sobras, f"o nome sobreviveu em: {sorted(set(sobras))}"
    # O nome escolhido no Quest também (não tem pedaço do nome civil).
    log = db.execute(select(LogAuditoria)
                     .where(LogAuditoria.acao == "quest.nome_escolhido")).scalars().one()
    assert log.detalhes["nome"] == MARCA_REMOVIDO
    assert not any(APELIDO_ESCOLHIDO in v for _, _, v in _varrer_tudo(db))


def test_nenhum_ponteiro_para_o_id_da_crianca_sobra(cliente_global, db, cenario):
    sai = cenario["sai"]
    _excluir(cliente_global, cenario)
    db.expire_all()
    for tabela in Base.metadata.sorted_tables:
        for coluna in ("aluno_id", "aluno_escolhido_id"):
            if coluna in tabela.c:
                n = db.execute(select(tabela.c[coluna]).where(tabela.c[coluna] == sai)).all()
                assert not n, f"{tabela.name}.{coluna} ainda aponta a criança"
    assert not db.execute(select(Notificacao).where(Notificacao.entidade == "aluno",
                                                    Notificacao.entidade_id == sai)).all()
    for rev in db.execute(select(RevisaoIdentidade)).scalars():
        assert all(c.get("aluno_id") != sai for c in rev.candidatos or [])
        assert (rev.resolucao or {}).get("aluno_id") != sai
    # Fica por obrigação de auditoria, SEM nome: o id como referência anônima.
    exclusao = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "aluno.excluido_permanente")).scalars().one()
    autor = db.execute(select(Usuario).where(Usuario.is_global.is_(True))).scalar_one()
    assert exclusao.entidade_id == sai and exclusao.usuario_id == autor.id


def test_o_que_e_apagado_anonimizado_e_mantido(cliente_global, db, cenario):
    _excluir(cliente_global, cenario)
    db.expire_all()
    # Apagado: as 3 revisões DELA; a da colega fica, sem a candidata excluída.
    revisoes = db.execute(select(RevisaoIdentidade)).scalars().all()
    assert len(revisoes) == 1
    [rev] = revisoes
    assert rev.nome_recebido == "ALUNO TESTE PERMANECE"
    assert rev.candidatos == [{"aluno_id": cenario["fica"], "nome": NOME_FICA}]
    assert rev.contexto["observacao"] == f"parecido com {MARCA_REMOVIDO} da mesma sala"
    assert rev.linhas == [{"nome": "ALUNO TESTE PERMANECE", "livros_unicos": 2}]
    # Anonimizado: a mensagem de sync mantém o contexto operacional.
    log_sync = db.execute(select(SincronizacaoLog)).scalars().one()
    assert log_sync.mensagem == f"Aluna “{MARCA_REMOVIDO}” ignorada; 3 linhas ok"
    assert db.execute(select(SincronizacaoExecucao)).scalars().one().erro_resumo == \
        f"Linha de {MARCA_REMOVIDO} sem turma"
    # Importação: o registro fica (quem/quando/quantos); o nome do arquivo não.
    arquivos = sorted(i.arquivo_original for i in db.execute(select(Importacao)).scalars())
    assert MARCA_REMOVIDO in arquivos and any("turma_5a" in a for a in arquivos)
    # A colega segue inteira.
    assert db.get(Aluno, cenario["fica"]).nome == NOME_FICA
    assert db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "aluno.criado")).scalars().one().detalhes["nome"] == NOME_FICA
    # Aviso que não toca criança nenhuma continua — e o da colega também.
    assert sorted((n.tipo, n.aluno_id) for n in db.execute(select(Notificacao)).scalars()) \
        == [("aluno.criado", cenario["fica"]), ("importacao.concluida", None)]
    # Filhos diretos e o Quest: sumiram.
    for modelo in (EventoAluno, SnapshotMatific, Nota, IdentidadeExterna,
                   QuestCredencialAluno, QuestPerfil):
        assert not db.execute(select(modelo).where(modelo.aluno_id == cenario["sai"])).all()


def test_arquivos_individual_e_copias_somem_os_de_turma_ficam(cliente_global, db, cenario):
    _excluir(cliente_global, cenario)
    assert not cenario["individual"].exists()      # relatório individual dela
    assert not cenario["copia"].exists()           # cópia em /exports
    assert cenario["de_turma"].exists()            # várias crianças: fica (documentado)
    assert cenario["gitkeep"].exists()             # infraestrutura


def test_exclusao_revertida_nao_apaga_arquivo(db, cenario):
    """Arquivo só some no COMMIT da transação da exclusão: se ela reverter, o
    original de uma criança que continua cadastrada não pode ter sumido."""
    academico._apagar_alunos_e_dados(db, cenario["escola"].id, cenario["admin"],
                                     [cenario["sai"]])
    db.rollback()
    assert cenario["individual"].exists() and cenario["copia"].exists()
    # Um commit POSTERIOR, de outra operação, não executa o pedido revertido.
    registrar(db, "teste.outra_operacao", escola_id=cenario["escola"].id)
    db.commit()
    assert cenario["individual"].exists() and cenario["copia"].exists()
    assert db.get(Aluno, cenario["sai"]) is not None


def test_savepoint_no_meio_nao_antecipa_a_exclusao_dos_arquivos(db, cenario):
    academico._apagar_alunos_e_dados(db, cenario["escola"].id, cenario["admin"],
                                     [cenario["sai"]])
    with db.begin_nested():                        # RELEASE dispara after_commit
        registrar(db, "teste.savepoint", escola_id=cenario["escola"].id)
    assert cenario["individual"].exists()          # ainda não: a raiz não commitou
    db.commit()
    assert not cenario["individual"].exists()


def test_exclusao_de_turma_com_alunos_alcanca_o_mesmo(cliente_global, db, cenario,
                                                     escola_completa):
    turma = escola_completa["turma"]
    # Excluir turma com alunos é do Admin Global (D19).
    r = cliente_global.delete(f"{_base(cenario['escola'].id)}/turmas/{turma.id}?com_alunos=true")
    assert r.status_code == 200, r.text
    db.expire_all()
    sobras = [(t, c) for t, c, v in _varrer_tudo(db) if SOBRENOME_DISTINTO in _normal(v)]
    assert not sobras, sobras
    assert not cenario["individual"].exists()


def test_homonimo_vivo_preserva_a_revisao_com_o_nome(cliente_global, db, cenario):
    """Outra criança da escola com o MESMO nome: a revisão com esse nome também
    pode ser dela — não é apagada só pelo nome."""
    esc = cenario["escola"]
    db.add(Aluno(escola_id=esc.id, nome=NOME, status="ativo"))
    db.commit()
    _excluir(cliente_global, cenario)
    db.expire_all()
    nomes = {r.nome_recebido for r in db.execute(select(RevisaoIdentidade)).scalars()}
    assert NOME.upper() in nomes


# --- O casador de nome ------------------------------------------------------------

def test_casador_por_palavra_inteira_sem_acento_e_sem_colisao():
    alvos = NomesAlvo(["Tristão Simulatti Fictelli", "Ana"])
    assert alvos.e_o_nome("TRISTAO  SIMULATTI fictelli")
    assert alvos.redigir_texto("falha em TRISTÃO SIMULATTI FICTELLI, turma 5A") == \
        f"falha em {MARCA_REMOVIDO}, turma 5A"
    assert alvos.cita("relatorio_tristao_simulatti_fictelli.pdf")
    # "Ana" (uma palavra) não é caçada no meio de frase; e não casa "Susana".
    assert not alvos.cita("Susana Ananias leu 3 livros")
    assert alvos.redigir_texto("Ana") == MARCA_REMOVIDO
    assert not NomesAlvo(["Ana Souza"]).cita("Mariana Souza Silva")
