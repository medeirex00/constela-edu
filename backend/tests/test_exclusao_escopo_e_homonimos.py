"""Exclusão permanente de aluno: o esquecimento não pode passar do que é da criança.

Revisão de 20/10/2026 sobre a correção do achado 3 (``test_exclusao_alcance_total``):
o alcance ficou TOTAL, mas em alguns pontos passou do alvo —

1. o log de auditoria GLOBAL (sem escola) era redigido pelo critério de VALOR: um
   aluno-isca com o nome igual a um e-mail ou ao nome de uma fonte da rede
   reescrevia o que nenhum perfil de escola alcança;
2. homônimo vivo: o original e a candidata da criança que CONTINUA eram apagados
   ou redigidos junto com a excluída;
3. nome contido no de outra criança viva ("Joao Pedro Silva" dentro de "Joao Pedro
   Silva Santos"): o original dela sumia e as mensagens viravam "[removido] Santos";
4. texto em Unicode decomposto (NFD, nome de arquivo vindo de macOS) escapava;
5. ``arquivo_original`` vindo do cliente apontando para o original de OUTRA escola
   fazia a exclusão apagar o arquivo de lá;
6. falha ao apagar o original gravava o nome do arquivo (com o nome da criança) no
   log da aplicação.

Segunda passada (verificação da correção acima):

7. a candidata de revisão com ``aluno_id`` era tratada como criança viva — mas a
   fusão apaga a ficha da duplicata e não mexe nas revisões: o nome da excluída
   sobrava na candidata da duplicata já fundida;
8. o casador procurava TODOS os nomes vivos em todo texto varrido, mesmo sem o
   nome excluído no texto (minutos com a transação da exclusão aberta);
9. o original com dado de quem fica ficava no disco com o nome da excluída e sem
   ponteiro (nem prova da importação, nem apagado);
10. a conversa da IA era apagada por ``ILIKE %nome%``: excluir "Joao Pedro Silva"
    apagava a conversa sobre "Joao Pedro Silva Testelli", que continua.

Dados 100% fictícios.
"""
import logging
import unicodedata
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_senha
from app.main import app
from app.models import (
    Aluno,
    Escola,
    Importacao,
    LogAuditoria,
    Matricula,
    RevisaoIdentidade,
    SincronizacaoExecucao,
    SincronizacaoLog,
    SnapshotElefante,
    Usuario,
)
from app.services import exclusao_aluno
from app.services.audit import registrar
from app.services.exclusao_aluno import MARCA_REMOVIDO, NomesAlvo


def _base(escola_id):
    return f"/api/v1/escolas/{escola_id}"


@pytest.fixture
def pastas(tmp_path, monkeypatch):
    """Toda exclusão apaga as cópias em EXPORTS_DIR: sem pastas próprias, o teste
    apagaria o /exports do repositório."""
    uploads, exports = tmp_path / "uploads", tmp_path / "exports"
    (uploads / "elefante").mkdir(parents=True)
    exports.mkdir()
    monkeypatch.setattr(settings, "UPLOADS_DIR", uploads)
    monkeypatch.setattr(settings, "EXPORTS_DIR", exports)
    return {"uploads": uploads, "exports": exports}


def _aluno(db, escola, turma, nome):
    aluno = Aluno(escola_id=escola.id, nome=nome, status="ativo")
    db.add(aluno)
    db.flush()
    db.add(Matricula(escola_id=escola.id, aluno_id=aluno.id, turma_id=turma.id,
                     ano_letivo=2026))
    return aluno


def _original(db, pastas, escola, nome_arquivo, *, gravado=None):
    """Original confirmado como o /confirmar grava (uploads/<plataforma>/<nome>)."""
    (pastas["uploads"] / "elefante" / nome_arquivo).write_bytes(b"%PDF teste")
    imp = Importacao(escola_id=escola.id, plataforma="elefante", tipo="pdf",
                     arquivo_original=gravado or f"uploads/elefante/{nome_arquivo}")
    db.add(imp)
    db.flush()
    return imp


def _excluir(cliente, escola_id, *ids):
    r = cliente.post(f"{_base(escola_id)}/alunos/excluir-permanente",
                     json={"aluno_ids": list(ids), "confirmacao": "EXCLUIR"})
    assert r.status_code == 200, r.text


# --- 1. Log de auditoria global ------------------------------------------------

@pytest.fixture
def coordenacao(db, escola_completa):
    db.add(Usuario(escola_id=escola_completa["escola"].id, nome="Coordenação Teste",
                   email="coord@teste.local", senha_hash=hash_senha("s3nh4"),
                   cargo="coordenador"))
    db.commit()
    cliente = TestClient(app)
    r = cliente.post("/api/v1/auth/login",
                     data={"username": "coord@teste.local", "password": "s3nh4"})
    assert r.status_code == 200, r.text
    cliente.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return cliente


def test_isca_da_escola_nao_reescreve_o_log_global(coordenacao, cliente_global, db,
                                                  escola_completa, pastas):
    """A coordenação cria alunos com o nome igual ao texto de entradas GLOBAIS
    (login de conta inexistente, fonte de avaliação da rede) e eles são excluídos
    em definitivo: nada delas muda. A entrada global que é da própria criança
    (entidade/entidade_id) muda. Quem exclui é o Admin Global — a exclusão física
    de aluno é só dele (D19); para a coordenação a rota responde 403."""
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    login = {"email": "secretaria@rede.local", "ip": "200.10.x.x",
             "motivo": "conta_inexistente"}
    fonte = {"nome": "Fulano Beltrano Teste", "url": "https://exemplo.invalid/boletim"}
    registrar(db, "login.falhou", detalhes=dict(login))
    registrar(db, "avaliacao.fonte.criada", detalhes=dict(fonte))
    db.commit()

    ids = []
    for isca in ("secretaria@rede.local", "Fulano Beltrano Teste"):
        r = coordenacao.post(f"{_base(escola.id)}/alunos",
                             json={"nome": isca, "turma_id": turma.id})
        assert r.status_code in (200, 201), r.text
        ids.append(r.json()["id"])
    # Uma entrada global que comprovadamente é de uma das iscas (a criança).
    registrar(db, "rede.aluno_citado", entidade="aluno", entidade_id=ids[1],
              detalhes={"nome": "Fulano Beltrano Teste"})
    db.commit()
    _excluir(cliente_global, escola.id, *ids)
    db.expire_all()

    globais = {log.acao: log.detalhes for log in db.execute(
        select(LogAuditoria).where(LogAuditoria.escola_id.is_(None))).scalars()}
    assert globais["login.falhou"] == login
    assert globais["avaliacao.fonte.criada"] == fonte
    assert globais["rede.aluno_citado"] == {"nome": MARCA_REMOVIDO}


# --- 2 e 3. Nome que também é de quem fica -------------------------------------

def test_homonimo_vivo_mantem_original_e_candidata(cliente_global, db, escola_completa, pastas):
    """Duas fichas com o mesmo nome (a duplicata E e a que fica, L): excluir E não
    apaga o original nem redige o nome de L na fila de revisão."""
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    nome = "Fulana Teste Exemplo"
    sai, fica = _aluno(db, escola, turma, nome), _aluno(db, escola, turma, nome)
    imp = _original(db, pastas, escola, "20261001_101010_Relatorio_Fulana_Teste_Exemplo.pdf")
    candidata_viva = {"aluno_id": fica.id, "nome": nome, "status": "ativo", "turma": "3A"}
    rev = RevisaoIdentidade(escola_id=escola.id, chave="k", chave_identidade="ki",
                            plataforma="elefante", motivo="ambiguo", status="pendente",
                            nome_recebido=nome.upper(),
                            candidatos=[candidata_viva,
                                        {"aluno_id": sai.id, "nome": nome, "status": "ativo",
                                         "turma": "3A"}],
                            linhas=[{"nome": nome.upper(), "livros_unicos": 2}], contexto={})
    db.add(rev)
    db.commit()
    _excluir(cliente_global, escola.id, sai.id)
    db.expire_all()

    assert (pastas["uploads"] / "elefante"
            / "20261001_101010_Relatorio_Fulana_Teste_Exemplo.pdf").exists()
    assert db.get(Importacao, imp.id).arquivo_original.endswith("Fulana_Teste_Exemplo.pdf")
    revisao = db.get(RevisaoIdentidade, rev.id)
    assert revisao.candidatos == [candidata_viva]           # sem a excluída; L intacta
    assert revisao.linhas == [{"nome": nome.upper(), "livros_unicos": 2}]


def test_nome_contido_no_de_crianca_viva_nao_e_tocado(cliente_global, db, escola_completa, pastas):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    sai = _aluno(db, escola, turma, "Joao Pedro Silva")
    viva = _aluno(db, escola, turma, "Joao Pedro Silva Testelli")
    arquivo_viva = "20261001_120000_Joao_Pedro_Silva_Testelli.pdf"
    imp_viva = _original(db, pastas, escola, arquivo_viva)
    db.add(SnapshotElefante(escola_id=escola.id, aluno_id=viva.id,
                            importacao_id=imp_viva.id, livros_unicos=3))
    imp_sai = _original(db, pastas, escola, "20261001_120500_Joao_Pedro_Silva.pdf")
    execucao = SincronizacaoExecucao(escola_id=escola.id, plataforma="elefante",
                                     origem="manual", status="ok")
    db.add(execucao)
    db.flush()
    db.add_all([
        SincronizacaoLog(execucao_id=execucao.id, escola_id=escola.id, etapa="gravacao",
                         nivel="info", mensagem="Joao Pedro Silva Testelli: 3 livros novos"),
        SincronizacaoLog(execucao_id=execucao.id, escola_id=escola.id, etapa="validacao",
                         nivel="warn", mensagem="Falha em Joao Pedro Silva, turma 5A"),
        RevisaoIdentidade(escola_id=escola.id, chave="k", chave_identidade="ki",
                          plataforma="elefante", motivo="ambiguo", status="pendente",
                          nome_recebido="JOAO PEDRO SILVA TESTELLI",
                          candidatos=[{"aluno_id": viva.id, "nome": viva.nome}],
                          linhas=[{"nome": "JOAO PEDRO SILVA TESTELLI"}], contexto={}),
    ])
    db.commit()
    _excluir(cliente_global, escola.id, sai.id)
    db.expire_all()

    # O da criança viva: arquivo, nome do arquivo, mensagem e revisão intactos.
    assert (pastas["uploads"] / "elefante" / arquivo_viva).exists()
    assert db.get(Importacao, imp_viva.id).arquivo_original == f"uploads/elefante/{arquivo_viva}"
    mensagens = sorted(m.mensagem for m in db.execute(select(SincronizacaoLog)).scalars())
    assert mensagens == [f"Falha em {MARCA_REMOVIDO}, turma 5A",
                         "Joao Pedro Silva Testelli: 3 livros novos"]
    [rev] = db.execute(select(RevisaoIdentidade)).scalars().all()
    assert rev.linhas == [{"nome": "JOAO PEDRO SILVA TESTELLI"}]
    assert rev.candidatos == [{"aluno_id": viva.id, "nome": "Joao Pedro Silva Testelli"}]
    # O DELA continua saindo.
    assert not (pastas["uploads"] / "elefante" / "20261001_120500_Joao_Pedro_Silva.pdf").exists()
    assert db.get(Importacao, imp_sai.id).arquivo_original == MARCA_REMOVIDO


def test_original_com_dado_de_quem_fica_nao_e_apagado(db, escola_completa, pastas):
    """O nome do arquivo cita a excluída, mas a importação trouxe dado de outra
    criança: não é o relatório individual dela. O arquivo fica como prova da
    importação (§15), RENOMEADO para um nome neutro e ainda apontado pela linha:
    nem o disco nem o texto guardam o nome dela, e a prova não fica órfã."""
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    sai = _aluno(db, escola, turma, "Aluna Teste Saindo")
    fica = escola_completa["alunos"][0]
    imp = _original(db, pastas, escola, "20261001_101010_aluna_teste_saindo.pdf")
    db.add(SnapshotElefante(escola_id=escola.id, aluno_id=fica.id, importacao_id=imp.id))
    db.commit()
    pasta = pastas["uploads"] / "elefante"
    contagens = exclusao_aluno.esquecer_fora_do_cadastro(db, escola.id,
                                                         {sai.id: sai.nome}, set())
    assert contagens["arquivos_a_renomear"] == 1
    assert (pasta / "20261001_101010_aluna_teste_saindo.pdf").exists()   # antes do commit
    db.commit()
    neutro = f"20261001_101010_importacao-{imp.id}.pdf"
    assert sorted(a.name for a in pasta.iterdir()) == [neutro]
    assert (pasta / neutro).read_bytes() == b"%PDF teste"                # conteúdo intacto
    assert db.get(Importacao, imp.id).arquivo_original == f"uploads/elefante/{neutro}"


def test_renomeacao_revertida_deixa_arquivo_e_ponteiro_como_estavam(db, escola_completa,
                                                                    pastas):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    sai = _aluno(db, escola, turma, "Aluna Teste Saindo")
    imp = _original(db, pastas, escola, "20261001_101010_aluna_teste_saindo.pdf")
    db.add(SnapshotElefante(escola_id=escola.id, aluno_id=escola_completa["alunos"][0].id,
                            importacao_id=imp.id))
    db.commit()
    exclusao_aluno.esquecer_fora_do_cadastro(db, escola.id, {sai.id: sai.nome}, set())
    db.rollback()
    registrar(db, "teste.outra_operacao", escola_id=escola.id)
    db.commit()                    # commit posterior não executa o pedido revertido
    pasta = pastas["uploads"] / "elefante"
    assert sorted(a.name for a in pasta.iterdir()) == ["20261001_101010_aluna_teste_saindo.pdf"]
    assert db.get(Importacao, imp.id).arquivo_original == \
        "uploads/elefante/20261001_101010_aluna_teste_saindo.pdf"


def test_falha_ao_renomear_nao_loga_o_nome_nem_sobrescreve(tmp_path, caplog):
    nome = "Aluna Teste Ficticia Zuleica"
    (tmp_path / "elefante").mkdir()
    origem = tmp_path / "elefante" / f"20261020_120000_Relatorio {nome}.pdf"
    origem.write_bytes(b"%PDF origem")
    ocupado = tmp_path / "elefante" / "20261020_120000_importacao-1.pdf"
    ocupado.write_bytes(b"%PDF outro")
    with caplog.at_level(logging.WARNING, logger="constela.exclusao"):
        assert exclusao_aluno._renomear_arquivos([(origem, ocupado)]) == 0
    assert ocupado.read_bytes() == b"%PDF outro" and origem.exists()
    mensagens = [r.getMessage() for r in caplog.records if r.name == "constela.exclusao"]
    assert mensagens and all("Zuleica" not in m and origem.name not in m for m in mensagens)
    assert "1 arquivo" in mensagens[0] and "elefante" in mensagens[0]


# --- 4. Texto decomposto (NFD) --------------------------------------------------

def test_nome_em_nfd_dentro_do_texto_e_achado():
    alvos = NomesAlvo(["João Silva Souza"])
    nfd = unicodedata.normalize("NFD", "Relatorio_João_Silva_Souza.pdf")
    assert alvos.cita(nfd)
    assert alvos.redigir_texto(nfd) == f"Relatorio_{MARCA_REMOVIDO}.pdf"
    assert alvos.redigir_texto(unicodedata.normalize("NFD", "Falha em João Silva Souza.")) \
        == f"Falha em {MARCA_REMOVIDO}."


def test_original_individual_em_nfd_sai_na_exclusao(cliente_global, db, escola_completa, pastas):
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    sai = _aluno(db, escola, turma, "João Silva Souza")
    nome_arquivo = unicodedata.normalize("NFD", "20261001_101010_Relatorio_João_Silva_Souza.pdf")
    imp = _original(db, pastas, escola, nome_arquivo)
    db.commit()
    _excluir(cliente_global, escola.id, sai.id)
    db.expire_all()
    assert not (pastas["uploads"] / "elefante" / nome_arquivo).exists()
    assert db.get(Importacao, imp.id).arquivo_original == MARCA_REMOVIDO


# --- 5. Caminho vindo do cliente ------------------------------------------------

def test_caminho_do_cliente_nao_apaga_original_de_outra_escola(
        cliente_global, db, escola_completa, pastas):
    """Importação SEM arquivo_token guarda o ``arquivo_nome`` do cliente. Apontado
    para o original de outra escola, a exclusão de um aluno-isca não o apaga."""
    escola, turma = escola_completa["escola"], escola_completa["turma"]
    outra = Escola(nome="ESCOLA TESTE DOIS", ano_letivo_ativo=2026)
    db.add(outra)
    db.flush()
    arquivo_outra = "20261001_101010_relatorio_fulano_beltrano_teste.pdf"
    imp_outra = _original(db, pastas, outra, arquivo_outra)
    isca = _aluno(db, escola, turma, "Fulano Beltrano Teste")
    forjadas = [
        Importacao(escola_id=escola.id, plataforma="elefante", tipo="pdf",
                   arquivo_original=f"uploads/elefante/{arquivo_outra}"),
        Importacao(escola_id=escola.id, plataforma="elefante", tipo="pdf",
                   arquivo_original="uploads\\elefante\\" + arquivo_outra.upper()),
        Importacao(escola_id=escola.id, plataforma="matific", tipo="pdf",
                   arquivo_original=f"uploads/matific/../elefante/{arquivo_outra}"),
    ]
    db.add_all(forjadas)
    db.commit()
    _excluir(cliente_global, escola.id, isca.id)
    db.expire_all()

    assert (pastas["uploads"] / "elefante" / arquivo_outra).exists()
    assert db.get(Importacao, imp_outra.id).arquivo_original == \
        f"uploads/elefante/{arquivo_outra}"
    # As linhas DESTA escola citavam o nome: o texto delas sai.
    assert all(db.get(Importacao, f.id).arquivo_original == MARCA_REMOVIDO for f in forjadas)


# --- 6. Log da aplicação --------------------------------------------------------

def test_falha_ao_apagar_nao_loga_o_nome_do_arquivo(tmp_path, monkeypatch, caplog):
    nome = "Aluna Teste Ficticia Zuleica"
    (tmp_path / "elefante").mkdir()
    arquivo = tmp_path / "elefante" / f"20261020_120000_Relatorio {nome}.pdf"
    arquivo.write_bytes(b"%PDF")
    assert NomesAlvo([nome]).cita(arquivo.name)

    def _falha(self, *a, **k):
        raise PermissionError("somente leitura")

    monkeypatch.setattr(Path, "unlink", _falha)
    with caplog.at_level(logging.WARNING, logger="constela.exclusao"):
        assert exclusao_aluno._apagar_arquivos([arquivo]) == 0
    mensagens = [r.getMessage() for r in caplog.records if r.name == "constela.exclusao"]
    assert mensagens, "a falha tem de ficar registrada"
    for mensagem in mensagens:
        assert "Zuleica" not in mensagem and arquivo.name not in mensagem
        assert "1 arquivo" in mensagem and "elefante" in mensagem


# --- 7. Candidata de ficha que não existe mais ----------------------------------

def test_candidata_de_duplicata_ja_fundida_nao_guarda_o_nome(
        cliente_global, db, escola_completa, pastas):
    """A revisão pendente lista [E, D], duas fichas com o mesmo nome. D é FUNDIDA
    em E e depois E é excluída. A candidata de D não é de ninguém que continua: o
    nome sai.

    Hoje a fusão já tira D das pendências (A15). O caso continua valendo para o
    PASSIVO: as fusões de antes não mexiam nas revisões, e é o estado que elas
    deixaram (D ainda listada) que a exclusão precisa limpar."""
    from app.services.alunos_fusao import fundir_par

    escola, turma = escola_completa["escola"], escola_completa["turma"]
    nome = "Kessia Teste Ficticia"
    sai, dup = _aluno(db, escola, turma, nome), _aluno(db, escola, turma, nome)
    viva = escola_completa["alunos"][0]
    candidata_viva = {"aluno_id": viva.id, "nome": viva.nome}
    candidatos_antes = [{"aluno_id": sai.id, "nome": nome},
                        {"aluno_id": dup.id, "nome": nome, "turma": "3A"},
                        candidata_viva]
    rev = RevisaoIdentidade(escola_id=escola.id, chave="k", chave_identidade="ki",
                            plataforma="elefante", motivo="ambiguo", status="pendente",
                            nome_recebido="K. TESTE F.",
                            candidatos=list(candidatos_antes),
                            linhas=[], contexto={})
    db.add(rev)
    db.flush()
    dup_id, sai_id = dup.id, sai.id
    fundir_par(db, escola.id, sai, dup, usuario_id=escola_completa["admin"].id)
    db.commit()
    assert db.get(Aluno, dup_id) is None
    db.refresh(rev)
    assert [c["aluno_id"] for c in rev.candidatos] == [sai_id, viva.id]   # A15
    rev.candidatos = list(candidatos_antes)       # o passivo de uma fusão antiga
    db.commit()
    _excluir(cliente_global, escola.id, sai.id)
    db.expire_all()

    revisao = db.get(RevisaoIdentidade, rev.id)
    assert nome not in str(revisao.candidatos)
    assert revisao.candidatos == [{"aluno_id": dup_id, "nome": MARCA_REMOVIDO, "turma": "3A"},
                                  candidata_viva]            # a de quem fica, intacta


# --- 8. Custo do casador -------------------------------------------------------

def test_casador_so_procura_nome_vivo_que_contem_o_excluido(monkeypatch):
    """Milhares de nomes vivos e de mensagens sem o nome excluído: o casador não
    pode procurar cada nome vivo em cada mensagem (medido: 0,6 s → 64 s com 2.000
    vivos e 20.000 mensagens, dentro da transação da exclusão)."""
    examinadas = []
    original = exclusao_aluno._ocorrencias

    def _contando(sequencias, normal):
        examinadas.append(len(sequencias))
        return original(sequencias, normal)

    vivos = [f"Aluno Vivo{i} Teste Rocha" for i in range(2000)]
    vivos.append("Maria Zuleica Teste Ficticia Rocha")       # contém a excluída
    alvos = NomesAlvo(["Zuleica Teste Ficticia"], preservar=vivos)
    monkeypatch.setattr(exclusao_aluno, "_ocorrencias", _contando)
    mensagens = [f"Elefante: Aluno Vivo{i} Teste Rocha leu 3 livros" for i in range(500)]
    assert not any(alvos.cita(m) for m in mensagens)
    assert not alvos.cita("Zuleica Teste: 3 livros")         # 1ª palavra, sem o nome
    # O que continua valendo: o nome dentro do de quem fica não conta; sozinho, conta.
    assert not alvos.cita("Maria Zuleica Teste Ficticia Rocha leu 3 livros")
    assert alvos.redigir_texto("Falha em Zuleica Teste Ficticia; e Maria Zuleica Teste "
                               "Ficticia Rocha ok") == \
        f"Falha em {MARCA_REMOVIDO}; e Maria Zuleica Teste Ficticia Rocha ok"
    assert sum(examinadas) <= 10, sum(examinadas)


# --- 10. Conversas da IA ---------------------------------------------------------

def test_conversa_ia_sobre_crianca_que_fica_nao_e_apagada(
        cliente_global, db, escola_completa, pastas):
    from app.models import ConversaIA, MensagemIA

    escola, turma, admin = (escola_completa["escola"], escola_completa["turma"],
                            escola_completa["admin"])
    sai = _aluno(db, escola, turma, "Joao Pedro Ficticio")
    _aluno(db, escola, turma, "Joao Pedro Ficticio Santos")
    sai_curto = _aluno(db, escola, turma, "Ianaflor")               # nome de uma palavra
    sai_homonimo = _aluno(db, escola, turma, "Fulana Teste Exemplo")
    _aluno(db, escola, turma, "Fulana Teste Exemplo")
    textos = {
        "da_viva": "O Joao Pedro Ficticio Santos leu 3 livros esta semana.",
        "dela": "Como ajudar o Joao Pedro Ficticio na leitura?",
        "das_duas": "Joao Pedro Ficticio Santos e Joao Pedro Ficticio leram juntos.",
        "curto_dela": "A Ianaflor faltou ontem.",
        "curto_outra": "A Ianaflores leu 2 livros.",
        "homonimo": "A Fulana Teste Exemplo melhorou.",
    }
    for chave, texto in textos.items():
        conversa = ConversaIA(escola_id=escola.id, usuario_id=admin.id, titulo=chave)
        db.add(conversa)
        db.flush()
        db.add(MensagemIA(conversa_id=conversa.id, papel="usuario", conteudo=texto))
    db.commit()
    _excluir(cliente_global, escola.id, sai.id, sai_curto.id, sai_homonimo.id)
    db.expire_all()

    ficaram = {c.titulo for c in db.execute(select(ConversaIA)).scalars()}
    # A da criança que fica (nome maior) e a de outra palavra ("Ianaflores") ficam.
    # Com homônimo vivo EXATO não há como dizer de qual das duas fala: apaga-se,
    # como já era (a conversa é do usuário, não da outra criança).
    assert ficaram == {"da_viva", "curto_outra"}
