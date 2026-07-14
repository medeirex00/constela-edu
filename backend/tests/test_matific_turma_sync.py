"""Mudança AUTOMÁTICA de turma via UUID do Matific + auto-cura da agenda diária.

Segurança (dado de criança, sem humano no loop): só move quem foi identificado
por UUID; identidade de turma é por TOKENS (série+letra), não por string crua;
só move entre turmas JÁ CADASTRADAS e de forma inequívoca — NUNCA cria
turma-fantasma nem move na dúvida.
"""
from sqlalchemy import select

from app.models import IdentidadeExterna, Matricula, Turma
from app.models.sincronizacao import SincronizacaoConfig
from app.routers.importacoes import _sincronizar_turma_matific, _vincular_identidade
from app.schemas.importacao import LinhaConfirmacao
from app.services.importacao import LinhaImportacao, casar_nomes
from app.sync import service, vault
from app.sync.interfaces import Credenciais


def _linha(nome, aluno_id, via, uuid, turma):
    return LinhaConfirmacao(
        nome=nome, aluno_id=aluno_id, via=via,
        dados={"matific_uuid": uuid, "turma_relatorio": turma,
               "estrelas": 10, "atividades": 2, "pontuacao_media": 5.0})


def _turma(db, escola_id, ano, nome, ano_escolar):
    t = Turma(escola_id=escola_id, nome=nome, ano_escolar=ano_escolar, ano_letivo=ano)
    db.add(t)
    db.flush()
    return t


# --- Casamento por UUID -------------------------------------------------------

def test_casar_por_uuid_ignora_o_nome(db, escola_completa):
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    db.add(IdentidadeExterna(escola_id=escola.id, aluno_id=ana.id,
                             plataforma="matific", id_externo="u-ana"))
    db.commit()
    linha = LinhaImportacao(numero=1, nome="Nome Completamente Diferente",
                            dados={"matific_uuid": "u-ana", "turma_relatorio": "X"})
    casar_nomes(db, escola.id, [linha])
    assert linha.correspondencia["via"] == "uuid"
    assert linha.correspondencia["aluno_id"] == ana.id


# --- Mudança de turma (para turma JÁ CADASTRADA, casando por tokens) ----------

def test_move_para_turma_existente_casando_por_tokens(db, escola_completa):
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    ano = escola.ano_letivo_ativo
    turma_a = escola_completa["turma"]                       # "3º Ano A"
    turma_b = _turma(db, escola.id, ano, "4º Ano B", "4º Ano")   # destino cadastrado
    db.add(IdentidadeExterna(escola_id=escola.id, aluno_id=ana.id,
                             plataforma="matific", id_externo="u-ana"))
    db.commit()
    # klassName cru do Matific — difere por sufixo de turno/anualidade, mas é a "4º Ano B".
    resolvidos = {ana.id: (ana, [_linha(ana.nome, ana.id, "uuid", "u-ana",
                                        "4 ANO B MANHA ANUAL")])}
    avisos: list[str] = []
    n = _sincronizar_turma_matific(db, escola.id, ano, resolvidos, avisos)
    assert n == 1
    m = db.execute(select(Matricula).where(
        Matricula.aluno_id == ana.id, Matricula.ano_letivo == ano)).scalars().first()
    assert m.turma_id == turma_b.id and m.turma_id != turma_a.id


def test_nao_cria_turma_fantasma_quando_nao_casa(db, escola_completa):
    """Se o Matific aponta uma turma que NÃO casa com nenhuma cadastrada: não move
    nem cria turma nova — só avisa para revisão humana."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    ano = escola.ano_letivo_ativo
    turma_a = escola_completa["turma"]
    db.add(IdentidadeExterna(escola_id=escola.id, aluno_id=ana.id,
                             plataforma="matific", id_externo="u-ana"))
    db.commit()
    antes = db.execute(select(Turma).where(Turma.escola_id == escola.id)).scalars().all()
    resolvidos = {ana.id: (ana, [_linha(ana.nome, ana.id, "uuid", "u-ana",
                                        "9 ANO Z NOTURNO")])}   # não existe
    avisos: list[str] = []
    n = _sincronizar_turma_matific(db, escola.id, ano, resolvidos, avisos)
    assert n == 0
    depois = db.execute(select(Turma).where(Turma.escola_id == escola.id)).scalars().all()
    assert len(depois) == len(antes)                           # NENHUMA turma criada
    m = db.execute(select(Matricula).where(Matricula.aluno_id == ana.id)).scalars().first()
    assert m.turma_id == turma_a.id                            # não moveu
    assert any("revise manualmente" in a for a in avisos)


def test_nao_move_quando_e_a_mesma_turma_por_tokens(db, escola_completa):
    """klassName é a mesma turma atual (só string diferente) → NÃO move."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    ano = escola.ano_letivo_ativo
    turma_a = escola_completa["turma"]                          # "3º Ano A"
    db.add(IdentidadeExterna(escola_id=escola.id, aluno_id=ana.id,
                             plataforma="matific", id_externo="u-ana"))
    db.commit()
    resolvidos = {ana.id: (ana, [_linha(ana.nome, ana.id, "uuid", "u-ana",
                                        "3 ANO A MANHA ANUAL")])}
    n = _sincronizar_turma_matific(db, escola.id, ano, resolvidos, [])
    assert n == 0
    m = db.execute(select(Matricula).where(Matricula.aluno_id == ana.id)).scalars().first()
    assert m.turma_id == turma_a.id


def test_primeiro_encontro_vincula_uuid_sem_mover(db, escola_completa):
    """via='exato' (1ª vez): grava o UUID mas NÃO move de turma ainda."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    ano = escola.ano_letivo_ativo
    turma_a = escola_completa["turma"]
    resolvidos = {ana.id: (ana, [_linha(ana.nome, ana.id, "exato", "u-ana", "4º Ano B")])}
    n = _sincronizar_turma_matific(db, escola.id, ano, resolvidos, [])
    assert n == 0
    vinc = db.execute(select(IdentidadeExterna).where(
        IdentidadeExterna.id_externo == "u-ana")).scalars().first()
    assert vinc is not None and vinc.aluno_id == ana.id
    m = db.execute(select(Matricula).where(Matricula.aluno_id == ana.id)).scalars().first()
    assert m.turma_id == turma_a.id


def test_match_provavel_nao_vincula_nem_move(db, escola_completa):
    """Match fuzzy (via=None): NÃO vincula UUID nem move (evita erro)."""
    escola, ana = escola_completa["escola"], escola_completa["alunos"][0]
    resolvidos = {ana.id: (ana, [_linha(ana.nome, ana.id, None, "u-ana", "4º Ano B")])}
    n = _sincronizar_turma_matific(db, escola.id, escola.ano_letivo_ativo, resolvidos, [])
    assert n == 0
    assert db.execute(select(IdentidadeExterna).where(
        IdentidadeExterna.id_externo == "u-ana")).scalars().first() is None


def test_vincular_identidade_nao_reatribui(db, escola_completa):
    escola = escola_completa["escola"]
    a1, a2 = escola_completa["alunos"][0], escola_completa["alunos"][1]
    _vincular_identidade(db, escola.id, a1.id, "matific", "u-x")
    _vincular_identidade(db, escola.id, a2.id, "matific", "u-x")  # não reatribui
    linhas = db.execute(select(IdentidadeExterna).where(
        IdentidadeExterna.id_externo == "u-x")).scalars().all()
    assert len(linhas) == 1 and linhas[0].aluno_id == a1.id


# --- Auto-cura da agenda diária (elimina o "re-salvar credencial") -----------

def test_backfill_agenda_diaria_idempotente_e_respeita_opt_out(db, escola_completa):
    escola = escola_completa["escola"]
    vault.salvar_credencial(db, escola.id, "matific",
                            Credenciais(usuario="u", senha="p"))
    db.commit()

    assert service.garantir_agendas_diarias(db, ("matific",)) == 1
    conf = db.execute(select(SincronizacaoConfig).where(
        SincronizacaoConfig.escola_id == escola.id,
        SincronizacaoConfig.plataforma == "matific")).scalars().first()
    assert conf.ativo and conf.cadencia == "diaria" and conf.proxima_execucao is not None

    assert service.garantir_agendas_diarias(db, ("matific",)) == 0   # idempotente

    conf.ativo = False                                               # opt-out
    conf.cadencia = "manual"
    db.commit()
    assert service.garantir_agendas_diarias(db, ("matific",)) == 0
    db.refresh(conf)
    assert conf.ativo is False and conf.cadencia == "manual"
