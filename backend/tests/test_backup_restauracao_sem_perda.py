"""C-06 — a restauração de backup não pode destruir o que o backup não captura.

O achado da auditoria 360: ``MODELOS`` exportava 15 tabelas, mas o ``delete``
da restauração apagava ``alunos`` — e ``alunos.id`` tem ``ON DELETE CASCADE``
para tabelas que NÃO estavam no arquivo (``identidades_externas``,
``eventos_aluno``, os perfis/credenciais do Quest, os responsáveis). O usuário
via "Backup restaurado: N registros" e perdia, em silêncio, o mapa de UUIDs
(reabrindo o P0 de duplicatas do commit 7f6fe4e), a linha do tempo da criança e
o login dela no Quest.

Este arquivo é a rede de proteção permanente:

* a **varredura estrutural** (``test_nenhuma_tabela_em_risco_fora_do_radar``)
  falha sozinha quando alguém criar amanhã uma tabela nova que o cascade
  apagaria — sem depender de ninguém lembrar de atualizar uma lista;
* os testes de roundtrip provam que o que entrou no ``MODELOS`` volta idêntico;
* os testes de recusa provam que o que fica de fora **bloqueia** a operação em
  vez de ser destruído.
"""
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.database import Base
from app.models import (
    Aluno,
    EventoAluno,
    IdentidadeExterna,
    Importacao,
    Leitura,
    Livro,
    Matricula,
    Nota,
    SnapshotElefante,
    SnapshotMatific,
    SyncMarcador,
    Turma,
)
from app.quest.models import QuestCredencialAluno, QuestPerfil
from app.services import backup as svc_backup

pytestmark = pytest.mark.usefixtures("cliente")


def _base(escola_id: int) -> str:
    return f"/api/v1/escolas/{escola_id}"


def _dados_do_aluno(db, escola, aluno, *, uuid="uuid-matific-abc"):
    """Cria o conjunto de dados que a auditoria provou serem perdidos."""
    importacao = Importacao(escola_id=escola.id, plataforma="matific", tipo="pdf",
                            arquivo_original="planilha.xlsx", qtd_alunos=1)
    db.add(importacao)
    livro = Livro(escola_id=escola.id, titulo="O Pequeno Príncipe", nivel_codigo="D")
    db.add(livro)
    db.flush()
    db.add(Leitura(escola_id=escola.id, aluno_id=aluno.id, livro_id=livro.id,
                   data=date(2026, 5, 4)))
    db.add(SnapshotMatific(escola_id=escola.id, aluno_id=aluno.id,
                           importacao_id=importacao.id, atividades=40,
                           estrelas=120, pontuacao_media=88.0))
    db.add(SnapshotElefante(escola_id=escola.id, aluno_id=aluno.id,
                            importacao_id=importacao.id, livros_unicos=7,
                            tempo_leitura_min=300, livros_por_nivel={"D": 7}))
    # --- o que a auditoria provou que sumia -----------------------------------
    db.add(IdentidadeExterna(escola_id=escola.id, aluno_id=aluno.id,
                             plataforma="matific", id_externo=uuid))
    db.add(EventoAluno(escola_id=escola.id, aluno_id=aluno.id,
                       importacao_id=importacao.id, livro_id=livro.id,
                       plataforma="elefante", tipo_evento="leitura",
                       ocorrido_em=datetime(2026, 5, 4, 9, 30),
                       chave_natural="hash-determinístico-1",
                       conteudo_titulo="O Pequeno Príncipe", nivel_codigo="D",
                       dados={"genero": "ficção"}))
    db.add(SyncMarcador(escola_id=escola.id, plataforma="elefante",
                        tipo_evento="leitura", historico_completo=True,
                        ultimo_evento_em=datetime(2026, 5, 4, 9, 30),
                        ultima_chave_natural="hash-determinístico-1"))
    db.commit()
    return {"importacao": importacao, "livro": livro}


def _quest_do_aluno(db, escola, aluno):
    perfil = QuestPerfil(escola_id=escola.id, aluno_id=aluno.id, apelido="Estrela",
                         codigo_amigo="AMIGO123", nivel=7, xp_total=4200)
    credencial = QuestCredencialAluno(escola_id=escola.id, aluno_id=aluno.id,
                                      codigo_login="SOL1234", qr_token="qr-token-1")
    db.add_all([perfil, credencial])
    db.commit()
    return perfil, credencial


# --- 1. A varredura estrutural (o teste que não deixa a regressão voltar) ------

def test_nenhuma_tabela_em_risco_fora_do_radar():
    """Toda tabela que a restauração destruiria precisa estar no backup OU na
    lista explícita de recusa. Uma tabela nova com ``aluno_id`` CASCADE, criada
    daqui a um ano, cai aqui — e não em produção."""
    import app.models  # noqa: F401  (popula o metadata)
    import app.quest.models  # noqa: F401

    no_backup = {m.__tablename__ for _, m in svc_backup.MODELOS}
    destruidas = svc_backup._tabelas_destruidas(Base.metadata)
    # Bloquear a raiz do cascade já protege os filhos (FK NOT NULL: eles não
    # existem sem o pai), então a cobertura é o FECHO das raízes recusadas.
    cobertas_pela_recusa = svc_backup._fecho_cascade(
        Base.metadata, set(svc_backup.PROTEGIDAS_POR_RECUSA))

    fora = destruidas - no_backup - cobertas_pela_recusa
    assert not fora, (
        "Estas tabelas seriam APAGADAS por uma restauração sem estar no backup "
        f"nem cobertas pela recusa: {sorted(fora)}. Inclua no MODELOS (com FK "
        "remapeada) ou em PROTEGIDAS_POR_RECUSA.")

    # E o inverso: nada na lista de recusa que já esteja no backup (contradição).
    assert not (set(svc_backup.PROTEGIDAS_POR_RECUSA) & no_backup)
    # Toda raiz recusada precisa ser contável por escola (é assim que a
    # checagem sabe se há dado em risco).
    for nome in svc_backup.PROTEGIDAS_POR_RECUSA:
        assert "escola_id" in Base.metadata.tables[nome].c, nome
    # E toda tabela citada na recusa precisa de rótulo legível para o gestor.
    for nome in svc_backup.PROTEGIDAS_POR_RECUSA:
        assert nome in svc_backup.ROTULOS, f"sem rótulo humano: {nome}"


def test_tabelas_destruidas_enxerga_o_cascade_transitivo():
    """A varredura precisa seguir o cascade em CADEIA (aluno → perfil Quest →
    progresso/tentativas/habilidades), não só o primeiro nível."""
    import app.quest.models  # noqa: F401

    destruidas = svc_backup._tabelas_destruidas(Base.metadata)
    assert "quest_perfis" in destruidas            # 1º nível (aluno_id CASCADE)
    assert "quest_progresso" in destruidas         # 2º nível (perfil_id CASCADE)
    assert "quest_tentativas" in destruidas
    assert "quest_habilidades" in destruidas
    # E não confunde com quem NÃO some: usuários não têm escola apagada aqui.
    assert "usuarios" not in destruidas
    assert "logs_auditoria" not in destruidas


def test_portao_nao_depende_de_import_alheio_para_enxergar_o_quest():
    """O portão consulta as tabelas protegidas POR NOME, e um nome só existe no
    metadata depois que o módulo que o declara é importado. ``app.models`` NÃO
    importa o Quest: quem chega em ``backup`` sem passar pelo ``main`` (script
    de manutenção, tarefa de fila) via ``KeyError: 'quest_perfis'`` — e
    ``KeyError`` não é tratado em ``admin.restaurar_backup``, virando 500 no
    lugar da recusa clara. O serviço tem de repor a própria pré-condição.

    Roda em SUBPROCESSO porque é a única forma honesta de ter um interpretador
    que nunca importou o Quest: mexer no ``sys.modules``/metadata do processo de
    teste corromperia o estado global para os outros testes.
    """
    import subprocess
    import sys
    import tempfile
    import textwrap

    raiz = str(Path(__file__).resolve().parents[1])
    with tempfile.TemporaryDirectory() as pasta:
        banco = Path(pasta, "escola.db").as_posix()

        # FASE 1 — processo que IMPORTA o Quest, só para criar o schema completo
        # em disco (o banco real de uma escola tem essas tabelas).
        cria = textwrap.dedent(f"""
            from sqlalchemy import create_engine
            from app.core.database import Base
            import app.models          # noqa: F401
            import app.quest.models    # noqa: F401
            Base.metadata.create_all(create_engine("sqlite:///{banco}"))
            print("SCHEMA OK")
        """)
        r1 = subprocess.run([sys.executable, "-c", cria], capture_output=True,
                            text=True, cwd=raiz)
        assert "SCHEMA OK" in r1.stdout, r1.stderr[-2000:]

        # FASE 2 — processo que NUNCA importa o Quest (o script de manutenção).
        # Antes da correção, `perdas_da_restauracao` morria aqui com
        # `KeyError: 'quest_perfis'` — antes mesmo de tocar no banco.
        usa = textwrap.dedent(f"""
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker

            from app.core.database import Base
            import app.models  # o que um script de manutenção importa
            from app.services import backup as svc

            assert "quest_perfis" not in Base.metadata.tables, \\
                "pré-condição: este processo não importou o Quest"

            db = sessionmaker(bind=create_engine("sqlite:///{banco}"))()
            perdas = svc.perdas_da_restauracao(db, 1, {{n for n, _ in svc.MODELOS}})
            assert perdas == {{}}, perdas
            print("OK")
        """)
        r2 = subprocess.run([sys.executable, "-c", usa], capture_output=True,
                            text=True, cwd=raiz)
        assert "OK" in r2.stdout, f"stdout={r2.stdout!r}\nstderr={r2.stderr[-2000:]}"


# --- 2. Roundtrip: o que está no backup volta idêntico -------------------------

def test_roundtrip_preserva_identidade_externa_evento_e_marcador(cliente, db, escola_completa):
    """O caso que reabria o P0: o mapa UUID↔aluno tem de sobreviver ao restore.

    Antes da correção este teste falhava em ``IdentidadeExterna 1 → 0``.
    """
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    _dados_do_aluno(db, escola, ana)

    baixado = cliente.get(f"{_base(escola.id)}/backup")
    assert baixado.status_code == 200

    resposta = cliente.post(f"{_base(escola.id)}/restaurar",
                            files={"arquivo": ("backup.json", baixado.content,
                                               "application/json")})
    assert resposta.status_code == 200, resposta.text

    db.expire_all()
    nova_ana = db.execute(select(Aluno).where(Aluno.escola_id == escola.id,
                                              Aluno.nome == ana.nome)).scalars().one()

    identidades = db.execute(select(IdentidadeExterna)
                             .where(IdentidadeExterna.escola_id == escola.id)).scalars().all()
    assert len(identidades) == 1, "o mapa UUID↔aluno foi destruído (reabre o P0)"
    assert identidades[0].id_externo == "uuid-matific-abc"
    assert identidades[0].aluno_id == nova_ana.id, "FK precisa apontar para o ID NOVO"

    eventos = db.execute(select(EventoAluno)
                         .where(EventoAluno.escola_id == escola.id)).scalars().all()
    assert len(eventos) == 1, "a linha do tempo da criança foi destruída"
    evento = eventos[0]
    assert evento.aluno_id == nova_ana.id
    assert evento.conteudo_titulo == "O Pequeno Príncipe"
    assert evento.ocorrido_em == datetime(2026, 5, 4, 9, 30)
    assert evento.chave_natural == "hash-determinístico-1"
    assert evento.dados == {"genero": "ficção"}
    # FKs para livro e importação também remapeadas (não apontam para o ID velho)
    livro = db.get(Livro, evento.livro_id)
    assert livro is not None and livro.titulo == "O Pequeno Príncipe"
    assert db.get(Importacao, evento.importacao_id) is not None

    marcadores = db.execute(select(SyncMarcador)
                            .where(SyncMarcador.escola_id == escola.id)).scalars().all()
    assert len(marcadores) == 1, "o cursor do incremental sumiu (a sync recomeçaria do zero)"
    assert marcadores[0].historico_completo is True


def test_roundtrip_preserva_todas_as_tabelas_do_modelos(cliente, db, escola_completa):
    """Backup completo → restore completo: nenhuma tabela do MODELOS encolhe."""
    escola = escola_completa["escola"]
    _dados_do_aluno(db, escola, escola_completa["alunos"][0])
    from app.services import scoring
    scoring.recalcular_escola(db, escola.id)
    db.commit()

    def _contagens() -> dict[str, int]:
        return {nome: len(db.execute(
            select(modelo.id).where(modelo.escola_id == escola.id)).scalars().all())
            for nome, modelo in svc_backup.MODELOS}

    antes = _contagens()
    assert antes["alunos"] == 3 and antes["identidades_externas"] == 1

    baixado = cliente.get(f"{_base(escola.id)}/backup")
    resposta = cliente.post(f"{_base(escola.id)}/restaurar",
                            files={"arquivo": ("backup.json", baixado.content,
                                               "application/json")})
    assert resposta.status_code == 200, resposta.text

    db.expire_all()
    assert _contagens() == antes


def test_backup_exporta_toda_tabela_do_modelos(cliente, db, escola_completa):
    """O arquivo precisa conter uma seção por tabela declarada (senão o restore
    apaga a tabela e insere zero linha — perda silenciosa por omissão)."""
    escola = escola_completa["escola"]
    _dados_do_aluno(db, escola, escola_completa["alunos"][0])

    dados = json.loads(cliente.get(f"{_base(escola.id)}/backup").content)
    for nome, _ in svc_backup.MODELOS:
        assert nome in dados["tabelas"], f"tabela “{nome}” ausente do arquivo"
    assert len(dados["tabelas"]["identidades_externas"]) == 1
    assert len(dados["tabelas"]["eventos_aluno"]) == 1


# --- 3. Recusa: o que não está no backup nunca é destruído em silêncio ---------

def test_restaurar_recusa_quando_ha_dado_do_quest(cliente, db, escola_completa):
    """Cenário exato da auditoria: perfil Quest (XP 4200, nível 7) + credencial.

    Antes: apagados em silêncio, com mensagem de sucesso. Agora: 409 e nada
    é tocado.
    """
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    _dados_do_aluno(db, escola, ana)
    _quest_do_aluno(db, escola, ana)

    baixado = cliente.get(f"{_base(escola.id)}/backup")
    resposta = cliente.post(f"{_base(escola.id)}/restaurar",
                            files={"arquivo": ("backup.json", baixado.content,
                                               "application/json")})

    assert resposta.status_code == 409, resposta.text
    # A mensagem fala a língua do gestor (não nomes de tabela) e diz o que
    # estava em risco — perfil E credencial, os dois casos da auditoria.
    detalhe = resposta.json()["detail"]
    assert svc_backup.ROTULOS["quest_perfis"] in detalhe
    assert svc_backup.ROTULOS["quest_credenciais_aluno"] in detalhe
    assert "Nada foi alterado" in detalhe

    # NADA foi destruído: o perfil, a credencial e os alunos continuam lá.
    db.expire_all()
    assert db.execute(select(QuestPerfil)
                      .where(QuestPerfil.escola_id == escola.id)).scalars().one().xp_total == 4200
    assert db.execute(select(QuestCredencialAluno)
                      .where(QuestCredencialAluno.escola_id == escola.id)
                      ).scalars().one().codigo_login == "SOL1234"
    assert len(db.execute(select(Aluno).where(Aluno.escola_id == escola.id)).scalars().all()) == 3


def test_restaurar_recusa_lista_tudo_que_perderia(cliente, db, escola_completa):
    """A mensagem precisa NOMEAR o que seria perdido — o operador decide com
    informação, não com um 'deu erro'."""
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    _quest_do_aluno(db, escola, ana)

    baixado = cliente.get(f"{_base(escola.id)}/backup")
    resposta = cliente.post(f"{_base(escola.id)}/restaurar",
                            files={"arquivo": ("backup.json", baixado.content,
                                               "application/json")})
    assert resposta.status_code == 409
    detalhe = resposta.json()["detail"]
    assert "1" in detalhe                      # a contagem de registros em risco
    assert "backup do banco" in detalhe.lower() or "banco de dados" in detalhe.lower()

    # A tentativa bloqueada fica na auditoria (quem tentou, o que estava em
    # risco) — recusar em silêncio seria só outro tipo de silêncio.
    from app.models import LogAuditoria
    log = db.execute(select(LogAuditoria)
                     .where(LogAuditoria.acao == "backup.restauracao_bloqueada")
                     ).scalars().one()
    assert log.escola_id == escola.id and log.usuario_id is not None
    assert log.detalhes["perdas"]["quest_perfis"] == 1


def test_escola_sem_dado_extra_restaura_normalmente(cliente, db, escola_completa):
    """A recusa é por DADO existente, não por tabela existir: escola sem Quest
    restaura como sempre (a proteção não pode virar um bloqueio permanente)."""
    escola = escola_completa["escola"]
    _dados_do_aluno(db, escola, escola_completa["alunos"][0])

    baixado = cliente.get(f"{_base(escola.id)}/backup")
    resposta = cliente.post(f"{_base(escola.id)}/restaurar",
                            files={"arquivo": ("backup.json", baixado.content,
                                               "application/json")})
    assert resposta.status_code == 200, resposta.text


def test_recusa_olha_so_a_escola_do_restore(cliente, db, escola_completa):
    """Dado do Quest de OUTRA escola não pode bloquear esta restauração."""
    from app.core.security import hash_senha
    from app.models import Escola, Usuario

    escola = escola_completa["escola"]
    outra = Escola(nome="OUTRA ESCOLA", ano_letivo_ativo=2026)
    db.add(outra)
    db.flush()
    db.add(Usuario(escola_id=outra.id, nome="Adm2", email="adm2@teste.local",
                   senha_hash=hash_senha("s3nh4"), cargo="admin"))
    turma_outra = Turma(escola_id=outra.id, nome="1º Ano B", ano_escolar="1º Ano",
                        ano_letivo=2026)
    aluno_outra = Aluno(escola_id=outra.id, nome="Criança da Outra")
    db.add_all([turma_outra, aluno_outra])
    db.flush()
    db.add(Matricula(escola_id=outra.id, aluno_id=aluno_outra.id,
                     turma_id=turma_outra.id, ano_letivo=2026))
    db.commit()
    _quest_do_aluno(db, outra, aluno_outra)

    baixado = cliente.get(f"{_base(escola.id)}/backup")
    resposta = cliente.post(f"{_base(escola.id)}/restaurar",
                            files={"arquivo": ("backup.json", baixado.content,
                                               "application/json")})
    assert resposta.status_code == 200, resposta.text
    db.expire_all()
    assert db.execute(select(QuestPerfil)
                      .where(QuestPerfil.escola_id == outra.id)).scalars().one().xp_total == 4200


# --- 4. Transacionalidade: erro no meio não deixa a escola destruída ----------

def test_erro_no_meio_da_restauracao_faz_rollback_total(cliente, db, escola_completa):
    """Backup com FK quebrada (leitura apontando para livro inexistente): a
    escola tem de continuar EXATAMENTE como estava — nada apagado."""
    escola = escola_completa["escola"]
    _dados_do_aluno(db, escola, escola_completa["alunos"][0])

    dados = json.loads(cliente.get(f"{_base(escola.id)}/backup").content)
    dados["tabelas"]["leituras"][0]["livro_id"] = 999999   # não existe no arquivo

    resposta = cliente.post(
        f"{_base(escola.id)}/restaurar",
        files={"arquivo": ("backup.json", json.dumps(dados).encode("utf-8"),
                           "application/json")})
    assert resposta.status_code == 400, resposta.text

    db.expire_all()
    assert len(db.execute(select(Aluno).where(Aluno.escola_id == escola.id)).scalars().all()) == 3
    assert len(db.execute(select(Leitura).where(Leitura.escola_id == escola.id)).scalars().all()) == 1
    assert len(db.execute(select(IdentidadeExterna)
                          .where(IdentidadeExterna.escola_id == escola.id)).scalars().all()) == 1
    assert len(db.execute(select(EventoAluno)
                          .where(EventoAluno.escola_id == escola.id)).scalars().all()) == 1


def test_arquivo_de_outra_versao_nao_apaga_nada(cliente, db, escola_completa):
    escola = escola_completa["escola"]
    _dados_do_aluno(db, escola, escola_completa["alunos"][0])

    resposta = cliente.post(
        f"{_base(escola.id)}/restaurar",
        files={"arquivo": ("backup.json",
                           json.dumps({"versao": 99, "tabelas": {}}).encode("utf-8"),
                           "application/json")})
    assert resposta.status_code == 400

    db.expire_all()
    assert len(db.execute(select(Aluno).where(Aluno.escola_id == escola.id)).scalars().all()) == 3
    assert len(db.execute(select(EventoAluno)
                          .where(EventoAluno.escola_id == escola.id)).scalars().all()) == 1


def test_backup_antigo_v1_nao_apaga_o_que_nao_carrega(cliente, db, escola_completa):
    """Arquivo da versão 1 (sem identidades/eventos) restaurado sobre uma escola
    que TEM esses dados: a perda seria por OMISSÃO — a tabela é apagada e o
    arquivo insere zero linha. Precisa ser recusada igual."""
    escola = escola_completa["escola"]
    _dados_do_aluno(db, escola, escola_completa["alunos"][0])

    dados = json.loads(cliente.get(f"{_base(escola.id)}/backup").content)
    antigo = {**dados, "versao": 1,
              "tabelas": {n: linhas for n, linhas in dados["tabelas"].items()
                          if n not in ("identidades_externas", "eventos_aluno",
                                       "sync_marcadores")}}

    resposta = cliente.post(
        f"{_base(escola.id)}/restaurar",
        files={"arquivo": ("backup.json", json.dumps(antigo).encode("utf-8"),
                           "application/json")})
    assert resposta.status_code == 409, resposta.text
    assert svc_backup.ROTULOS["identidades_externas"] in resposta.json()["detail"]

    db.expire_all()
    assert len(db.execute(select(IdentidadeExterna)
                          .where(IdentidadeExterna.escola_id == escola.id)).scalars().all()) == 1
    assert len(db.execute(select(EventoAluno)
                          .where(EventoAluno.escola_id == escola.id)).scalars().all()) == 1


def test_backup_antigo_v1_ainda_restaura_quando_nada_se_perde(cliente, db, escola_completa):
    """Compatibilidade: quem tem um arquivo v1 e uma escola sem os dados novos
    continua conseguindo restaurar (a recusa é por PERDA, não por versão)."""
    escola = escola_completa["escola"]
    dados = json.loads(cliente.get(f"{_base(escola.id)}/backup").content)
    antigo = {**dados, "versao": 1,
              "tabelas": {n: linhas for n, linhas in dados["tabelas"].items()
                          if n not in ("identidades_externas", "eventos_aluno",
                                       "sync_marcadores")}}

    resposta = cliente.post(
        f"{_base(escola.id)}/restaurar",
        files={"arquivo": ("backup.json", json.dumps(antigo).encode("utf-8"),
                           "application/json")})
    assert resposta.status_code == 200, resposta.text
    db.expire_all()
    assert len(db.execute(select(Aluno).where(Aluno.escola_id == escola.id)).scalars().all()) == 3


def test_modelos_esta_em_ordem_segura_para_inserir_e_para_apagar():
    """A ordem do MODELOS é usada nos DOIS sentidos. Se ela furar, o restore
    quebra com “FOREIGN KEY constraint failed” e acusa o ARQUIVO de inválido —
    foi assim que ``eventos_aluno`` quase entrou errado (aponta para livros e
    importações, que são apagados depois dele)."""
    posicao = {nome: i for i, (nome, _) in enumerate(svc_backup.MODELOS)}
    for nome, modelo in svc_backup.MODELOS:
        for fk in modelo.__table__.foreign_keys:
            pai = fk.column.table.name
            if pai not in posicao or pai == nome:
                continue
            assert posicao[pai] < posicao[nome], (
                f"“{nome}” aponta para “{pai}”, então precisa vir DEPOIS dele "
                "(inserção) — e, em reversed(), ser apagado antes.")


def test_ids_do_arquivo_nao_viram_pk_e_as_fks_sao_remapeadas(cliente, db, escola_completa):
    """PKs: o ``_id`` gravado no arquivo é só um rótulo para religar as FKs —
    nunca é reusado como chave primária (poderia colidir com outra escola do
    mesmo banco). O que precisa valer é a CONSISTÊNCIA: nenhum filho aponta
    para um pai que não existe ou que é de outra escola."""
    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    _dados_do_aluno(db, escola, ana)

    baixado = cliente.get(f"{_base(escola.id)}/backup")
    arquivo = json.loads(baixado.content)
    assert cliente.post(f"{_base(escola.id)}/restaurar",
                        files={"arquivo": ("backup.json", baixado.content,
                                           "application/json")}).status_code == 200

    db.expire_all()
    alunos = db.execute(select(Aluno).where(Aluno.escola_id == escola.id)).scalars().all()
    ids_novos = {a.id for a in alunos}
    # O ``_id`` do arquivo é rótulo interno; a coluna `id` nunca é importada.
    assert "id" not in arquivo["tabelas"]["alunos"][0]
    assert all("_id" in linha for linha in arquivo["tabelas"]["alunos"])

    # Toda FK aponta para linha existente DESTA escola (nada órfão, nada cruzado).
    for matricula in db.execute(select(Matricula)
                                .where(Matricula.escola_id == escola.id)).scalars():
        assert matricula.aluno_id in ids_novos
        assert db.get(Turma, matricula.turma_id).escola_id == escola.id
    for identidade in db.execute(select(IdentidadeExterna)
                                 .where(IdentidadeExterna.escola_id == escola.id)).scalars():
        assert identidade.aluno_id in ids_novos
    for evento in db.execute(select(EventoAluno)
                             .where(EventoAluno.escola_id == escola.id)).scalars():
        assert evento.aluno_id in ids_novos


def test_restauracao_nao_deixa_aviso_apontando_para_outra_crianca(cliente, db, escola_completa):
    """``Notificacao.aluno_id`` é int solto (sem FK) e o banco REAPROVEITA os
    IDs apagados — sem limpar, o aviso “Novo aluno cadastrado” do aluno #1
    antigo passa a apontar para o aluno #1 novo, que é outra criança."""
    from app.models import Notificacao

    escola = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    db.add(Notificacao(escopo="escola", escola_id=escola.id, tipo="aluno.criado",
                       titulo="Novo aluno cadastrado", rota=f"/alunos/{ana.id}",
                       entidade="aluno", entidade_id=ana.id, aluno_id=ana.id))
    db.add(Notificacao(escopo="escola", escola_id=escola.id, tipo="backup.gerado",
                       titulo="Backup gerado", rota="/configuracoes"))
    db.commit()

    baixado = cliente.get(f"{_base(escola.id)}/backup")
    assert cliente.post(f"{_base(escola.id)}/restaurar",
                        files={"arquivo": ("backup.json", baixado.content,
                                           "application/json")}).status_code == 200

    db.expire_all()
    restantes = db.execute(select(Notificacao)
                           .where(Notificacao.escola_id == escola.id)).scalars().all()
    assert all(n.aluno_id is None for n in restantes), \
        "sobrou aviso apontando para um ID de aluno que agora é outra criança"
    # O aviso que não toca criança nenhuma continua no mural (não é faxina cega).
    assert any(n.tipo == "backup.gerado" for n in restantes)


def test_snapshots_voltam_com_os_valores_exatos(cliente, db, escola_completa):
    """Snapshots são imutáveis e são a base do scoring: nenhum número pode
    mudar no roundtrip (inclusive o JSON de livros por nível e o float)."""
    escola = escola_completa["escola"]
    _dados_do_aluno(db, escola, escola_completa["alunos"][0])

    baixado = cliente.get(f"{_base(escola.id)}/backup")
    assert cliente.post(f"{_base(escola.id)}/restaurar",
                        files={"arquivo": ("backup.json", baixado.content,
                                           "application/json")}).status_code == 200

    db.expire_all()
    matific = db.execute(select(SnapshotMatific)
                         .where(SnapshotMatific.escola_id == escola.id)).scalars().one()
    assert (matific.atividades, matific.estrelas, matific.pontuacao_media) == (40, 120, 88.0)
    elefante = db.execute(select(SnapshotElefante)
                          .where(SnapshotElefante.escola_id == escola.id)).scalars().one()
    assert elefante.livros_unicos == 7 and elefante.tempo_leitura_min == 300
    assert elefante.livros_por_nivel == {"D": 7}
    # E continuam ligados a uma importação real desta escola.
    assert db.get(Importacao, matific.importacao_id).escola_id == escola.id


def test_restaurar_backup_de_escola_vazia_sobre_escola_com_dados(cliente, db, escola_completa):
    """Substituição legítima e completa: o backup vazio é o estado desejado, e
    a operação continua permitida (não viramos um sistema que nunca restaura)."""
    escola = escola_completa["escola"]
    vazio = {"versao": svc_backup.VERSAO_BACKUP, "gerado_em": datetime.now(timezone.utc).isoformat(),
             "escola": {"nome": escola.nome, "ano_letivo_ativo": 2026},
             "tabelas": {nome: [] for nome, _ in svc_backup.MODELOS}}

    resposta = cliente.post(
        f"{_base(escola.id)}/restaurar",
        files={"arquivo": ("backup.json", json.dumps(vazio).encode("utf-8"),
                           "application/json")})
    assert resposta.status_code == 200, resposta.text

    db.expire_all()
    assert db.execute(select(Aluno).where(Aluno.escola_id == escola.id)).scalars().all() == []
    assert db.execute(select(Nota).where(Nota.escola_id == escola.id)).scalars().all() == []
