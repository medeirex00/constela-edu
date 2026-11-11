"""Exclusão permanente (LGPD) de uma criança que ABSORVEU uma duplicata: o nome da
ficha absorvida some também FORA do log de auditoria (REG_SEGURANCA-1).

O DEFEITO. O ALUNOS-8 (``exclusao_aluno.fichas_absorvidas``) passou a tratar as fichas
absorvidas por fusão como a MESMA criança — mas só na anonimização do log. O resto do
esquecimento (``esquecer_fora_do_cadastro``: revisões, mensagens da sincronização,
original de relatório individual; e ``conversas_ia_que_citam``) recebia só o nome
ATUAL da ficha excluída. O nome que a criança tinha no stub da importação ou da coleta
("ANA B. SOUZA") ficava na conversa da IA, nas mensagens da sincronização, na fila de
revisões e no nome do arquivo original, contra o que o RETENCAO-TECNICA §2.3 promete.

A REGRA (a mesma do log): o nome da ficha absorvida conta como dela, salvo quando é
também o nome — ou parte do nome — de uma criança que continua na escola.

Dados fictícios.
"""
import pytest
from sqlalchemy import JSON, String, Text, select

from app.core.config import settings
from app.core.database import Base
from app.models import (Aluno, ConversaIA, Importacao, Matricula, MensagemIA,
                        RevisaoIdentidade, SincronizacaoAlerta, SincronizacaoExecucao,
                        SincronizacaoLog)
from app.services.audit import registrar
from app.services.exclusao_aluno import MARCA_REMOVIDO

API = "/api/v1"
NOME_STUB = "ANA B. SOUZA"
ARQUIVO_STUB = "20261001_101010_relatorio_ana_b_souza.pdf"


@pytest.fixture
def pastas(tmp_path, monkeypatch):
    uploads, exports = tmp_path / "uploads", tmp_path / "exports"
    (uploads / "elefante").mkdir(parents=True)
    exports.mkdir()
    monkeypatch.setattr(settings, "UPLOADS_DIR", uploads)
    monkeypatch.setattr(settings, "EXPORTS_DIR", exports)
    return uploads


def _stub(db, escola, turma, admin, nome):
    """Ficha criada pela importação/coleta, com o log que ela grava."""
    stub = Aluno(escola_id=escola.id, nome=nome)
    db.add(stub)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=stub.id, turma_id=turma.id,
                     ano_letivo=2026))
    registrar(db, "aluno.criado_auto", escola_id=escola.id, usuario_id=admin.id,
              entidade="aluno", entidade_id=stub.id,
              detalhes={"origem": nome, "turma": turma.nome,
                        "decisao": "NEW_STUDENT", "fonte": "importacao"})
    db.commit()
    return stub.id


def _conversa(db, escola, admin, texto):
    cv = ConversaIA(escola_id=escola.id, usuario_id=admin.id, titulo="Leitura do 3º A")
    db.add(cv)
    db.flush()
    db.add(MensagemIA(conversa_id=cv.id, papel="usuario", conteudo="Quem leu mais?"))
    db.add(MensagemIA(conversa_id=cv.id, papel="assistente", conteudo=texto))
    db.commit()
    return cv.id


def _sync(db, escola, texto):
    exe = SincronizacaoExecucao(escola_id=escola.id, plataforma="elefante",
                                origem="manual", status="erro",
                                erro_resumo=f"Linha de {texto} sem turma")
    db.add(exe)
    db.flush()
    db.add(SincronizacaoLog(execucao_id=exe.id, escola_id=escola.id, etapa="importar",
                            nivel="info", mensagem=f"Aluno novo criado pela coleta: {texto}."))
    db.add(SincronizacaoAlerta(escola_id=escola.id, plataforma="elefante",
                               tipo="falha_download",
                               mensagem=f"Relatório de {texto} não baixou"))
    db.commit()


def _fundir_e_excluir(cliente, cliente_global, escola_id, oficial_id, stub_id):
    r = cliente.post(f"{API}/escolas/{escola_id}/alunos/fundir", json={
        "manter_id": oficial_id, "remover_id": stub_id, "confirmacao": "FUNDIR"})
    assert r.status_code == 200, r.text
    r = cliente_global.post(f"{API}/escolas/{escola_id}/alunos/excluir-permanente",
                            json={"aluno_ids": [oficial_id], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text


def _varrer_tudo(db) -> list[tuple[str, str, str]]:
    """(tabela, coluna, valor) de TODA coluna de texto/JSON de TODA tabela."""
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


def _cita_o_stub(texto: str) -> bool:
    baixo = texto.casefold()
    return "ana b. souza" in baixo or "ana_b_souza" in baixo


def test_nome_da_ficha_absorvida_some_de_todo_lugar(
        cliente, cliente_global, db, escola_completa, pastas):
    escola, turma, admin = (escola_completa["escola"], escola_completa["turma"],
                            escola_completa["admin"])
    oficial_id = escola_completa["alunos"][0].id               # "Ana Beatriz Souza"
    colega_id = escola_completa["alunos"][1].id                # continua na escola
    stub_id = _stub(db, escola, turma, admin, NOME_STUB)
    # Enquanto o stub existia, o assistente, a coleta e a importação o citaram.
    conv = _conversa(db, escola, admin, f"A {NOME_STUB} leu 3 livros este mês.")
    _sync(db, escola, f"{NOME_STUB} (3º Ano A)")
    (pastas / "elefante" / ARQUIVO_STUB).write_bytes(b"%PDF individual do stub")
    db.add(Importacao(escola_id=escola.id, usuario_id=admin.id, plataforma="elefante",
                      tipo="pdf", arquivo_original=f"uploads/elefante/{ARQUIVO_STUB}"))
    comum = dict(escola_id=escola.id, chave="k", chave_identidade="ki",
                 plataforma="elefante", motivo="correspondencia_insegura")
    db.add_all([
        # Pendência só com o nome do stub (nenhuma criança viva tem esse nome).
        RevisaoIdentidade(**comum, nome_recebido=NOME_STUB, linhas=[{"nome": NOME_STUB}]),
        # Revisão JÁ RESOLVIDA de outra criança, que listava o stub como candidato
        # (a fusão só troca o candidato nas pendências abertas).
        RevisaoIdentidade(**comum, nome_recebido="JOAO P. BARBOSA", status="resolvida",
                          aluno_escolhido_id=colega_id,
                          candidatos=[{"aluno_id": colega_id, "nome": "João Pedro Barbosa"},
                                      {"aluno_id": stub_id, "nome": NOME_STUB}],
                          linhas=[{"nome": "JOAO P. BARBOSA"}]),
    ])
    db.commit()
    assert {t for t, _, v in _varrer_tudo(db) if _cita_o_stub(v)} >= {
        "mensagens_ia", "sincronizacao_logs", "sincronizacao_alertas",
        "sincronizacao_execucoes", "importacoes", "revisoes_identidade"}

    _fundir_e_excluir(cliente, cliente_global, escola.id, oficial_id, stub_id)

    db.expire_all()
    assert db.get(Aluno, oficial_id) is None
    sobras = sorted({(t, c) for t, c, v in _varrer_tudo(db) if _cita_o_stub(v)})
    assert not sobras, (
        f"depois da exclusão permanente, o nome '{NOME_STUB}' da ficha absorvida "
        f"sobreviveu em: {sobras}")
    assert db.get(ConversaIA, conv) is None
    assert not (pastas / "elefante" / ARQUIVO_STUB).exists()
    # O contexto operacional fica, sem o nome.
    assert db.execute(select(SincronizacaoLog.mensagem)).scalar_one() == \
        f"Aluno novo criado pela coleta: {MARCA_REMOVIDO} (3º Ano A)."
    # A revisão da colega fica, sem o candidato absorvido (é a criança excluída).
    [rev] = db.execute(select(RevisaoIdentidade)).scalars().all()
    assert rev.nome_recebido == "JOAO P. BARBOSA"
    assert rev.candidatos == [{"aluno_id": colega_id, "nome": "João Pedro Barbosa"}]


def test_nome_absorvido_que_e_parte_do_nome_de_quem_fica_nao_e_tocado(
        cliente, cliente_global, db, escola_completa, pastas):
    """A mesma regra do log: o nome da ficha absorvida ("ANA SOUZA") que é também
    parte do nome de uma criança que continua ("Ana Souza Lima") não prova ser da
    excluída — o texto que o cita fica."""
    escola, turma, admin = (escola_completa["escola"], escola_completa["turma"],
                            escola_completa["admin"])
    oficial_id = escola_completa["alunos"][0].id               # "Ana Beatriz Souza"
    db.add(Aluno(escola_id=escola.id, nome="Ana Souza Lima"))
    db.commit()
    stub_id = _stub(db, escola, turma, admin, "ANA SOUZA")
    conv_viva = _conversa(db, escola, admin, "A Ana Souza Lima leu 2 livros.")
    conv_ambigua = _conversa(db, escola, admin, "A Ana Souza leu 2 livros.")
    _sync(db, escola, "Ana Souza (3º Ano A)")

    _fundir_e_excluir(cliente, cliente_global, escola.id, oficial_id, stub_id)

    db.expire_all()
    assert db.get(ConversaIA, conv_viva) is not None
    assert db.get(ConversaIA, conv_ambigua) is not None
    assert db.execute(select(SincronizacaoLog.mensagem)).scalar_one() == \
        "Aluno novo criado pela coleta: Ana Souza (3º Ano A)."


def test_candidata_de_ficha_que_nao_existe_e_nao_e_dela_so_perde_o_nome(
        cliente_global, db, escola_completa, pastas):
    """A candidata de uma ficha que não existe mais e que a excluída NÃO absorveu
    (nenhuma fusão a liga a ela) continua na lista: só o nome dela sai."""
    escola = escola_completa["escola"]
    oficial = escola_completa["alunos"][0]                     # "Ana Beatriz Souza"
    colega = escola_completa["alunos"][1]
    db.add(RevisaoIdentidade(
        escola_id=escola.id, chave="k", chave_identidade="ki", plataforma="elefante",
        motivo="correspondencia_insegura", status="resolvida",
        aluno_escolhido_id=colega.id, nome_recebido="JOAO P. BARBOSA",
        candidatos=[{"aluno_id": colega.id, "nome": colega.nome},
                    {"aluno_id": 9999, "nome": oficial.nome}],
        linhas=[{"nome": "JOAO P. BARBOSA"}]))
    db.commit()
    r = cliente_global.post(f"{API}/escolas/{escola.id}/alunos/excluir-permanente",
                            json={"aluno_ids": [oficial.id], "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text
    db.expire_all()
    [rev] = db.execute(select(RevisaoIdentidade)).scalars().all()
    assert rev.candidatos == [{"aluno_id": colega.id, "nome": "João Pedro Barbosa"},
                              {"aluno_id": 9999, "nome": MARCA_REMOVIDO}]
