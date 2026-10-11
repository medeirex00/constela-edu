"""Vinculação automática: os casos OBRIGATÓRIOS da missão de 2026-10-11, um a um.

Cada teste diz em qual dos TRÊS estados a linha da plataforma cai — e por quê:

  1. correspondência automática SEGURA → ASSOCIAR (evidência forte, candidato
     único, nenhum conflito);
  2. correspondência AMBÍGUA → REVISAR (vários candidatos plausíveis, evidência
     insuficiente ou conflito de conta) — continua na tela de revisão;
  3. SEM correspondência confiável → nunca ASSOCIAR por aproximação (CRIAR quando a
     escola permite, ou revisão).

Os casos relatados pelo dono na escola 1 aparecem com nomes FICTÍCIOS que
reproduzem o padrão real (medido em produção, só leitura, sem nomes no relatório):
  * "Matias" — linha do Elefante com UMA letra diferente num nome do meio, único
    candidato da sala, ficha oficial que já tem a conta do Matific;
  * "Wendy" — ficha oficial + ficha "abreviada" criada pela sync do Matific na
    mesma sala; o Elefante manda o nome completo (``test_identidade_automatica``,
    casos ``test_i_*``).

Os casos já cobertos noutros arquivos são citados no teste do mapa, ao fim.
"""
from datetime import date

import pytest
from sqlalchemy import func, select

from app.models import Aluno, IdentidadeExterna, LogAuditoria
from app.services import identidade_aluno as ida
from tests.test_identidade_automatica import (  # noqa: F401 — fixtures reutilizadas
    SALA_2B,
    SALA_2B_MATIFIC,
    _aluno,
    _confirmar,
    _conta,
    _decidir,
    _dono,
    _elefante,
    _matific,
    _n_alunos,
    _pendentes,
    rede,
)


def _contas(db, escola, plataforma, id_externo):
    return db.execute(select(func.count()).select_from(IdentidadeExterna).where(
        IdentidadeExterna.escola_id == escola.id,
        IdentidadeExterna.plataforma == plataforma,
        IdentidadeExterna.id_externo == id_externo)).scalar_one()


# --- nome completo × abreviado; iniciais com turma e escola --------------------

@pytest.mark.parametrize("recebido,via", [
    ("MARIA EDUARDA SANTOS LIMA", "exato"),     # completo
    ("MARIA E", "abreviacao"),                  # abreviado (Matific)
    ("MARIA E S LIMA", "abreviacao"),           # iniciais no meio
])
def test_completo_ou_abreviado_com_candidato_unico_na_sala_associa(db, rede, recebido, via):
    esc = rede["escola"]
    maria = _aluno(db, esc, rede["b"], "MARIA EDUARDA SANTOS LIMA")
    _aluno(db, esc, rede["b"], "PEDRO HENRIQUE ALVES")
    db.commit()
    d = _decidir(db, esc, recebido, SALA_2B_MATIFIC, plataforma="matific", id_externo="u-1")
    assert (d.acao, d.aluno_id, d.via) == (ida.ASSOCIAR, maria.id, via)


def test_iniciais_que_servem_a_duas_criancas_da_sala_vao_para_revisao(db, rede):
    esc = rede["escola"]
    a = _aluno(db, esc, rede["b"], "ANA CLARA SOUZA")
    b = _aluno(db, esc, rede["b"], "ANA CAROLINA SANTOS")
    db.commit()
    d = _decidir(db, esc, "ANA C S", SALA_2B_MATIFIC, plataforma="matific", id_externo="u-2")
    assert (d.acao, d.motivo) == (ida.REVISAR, "candidatos_multiplos")
    assert set(d.candidatos) == {a.id, b.id}


def test_iniciais_que_so_casam_em_outra_sala_nunca_associam(db, rede):
    """A sala do relatório não tem ninguém compatível; a única ficha que casa pelas
    iniciais está em OUTRA turma — pode ser outra criança: revisão, nunca vínculo."""
    esc = rede["escola"]
    outra_sala = _aluno(db, esc, rede["c"], "ANA CLARA SOUZA")
    _aluno(db, esc, rede["b"], "PEDRO HENRIQUE ALVES")
    db.commit()
    d = _decidir(db, esc, "ANA C S", SALA_2B_MATIFIC, plataforma="matific", id_externo="u-3")
    assert (d.acao, d.motivo, d.aluno_id) == (ida.REVISAR, "nome_casa_em_outra_sala",
                                              outra_sala.id)


def test_so_iniciais_sem_nenhum_nome_inteiro_nao_casam_ninguem(db, rede):
    """"A C S" não tem âncora (nenhum nome inteiro igual): não é evidência de quem é."""
    esc = rede["escola"]
    _aluno(db, esc, rede["b"], "ANA CLARA SOUZA")
    db.commit()
    d = _decidir(db, esc, "A C S", SALA_2B_MATIFIC, plataforma="matific", id_externo="u-4")
    assert d.acao != ida.ASSOCIAR and d.aluno_id is None


# --- sobrenomes em ordem diferente --------------------------------------------

def test_mesmos_nomes_em_outra_ordem_com_candidato_unico_associa(db, rede):
    esc = rede["escola"]
    maria = _aluno(db, esc, rede["b"], "MARIA EDUARDA SANTOS LIMA")
    db.commit()
    d = _decidir(db, esc, "SANTOS LIMA MARIA EDUARDA", SALA_2B)
    assert (d.acao, d.aluno_id, d.via) == (ida.ASSOCIAR, maria.id, "exato")


def test_outra_ordem_que_serve_a_duas_fichas_vai_para_revisao(db, rede):
    esc = rede["escola"]
    a = _aluno(db, esc, rede["b"], "MARIA EDUARDA SANTOS LIMA")
    b = _aluno(db, esc, rede["b"], "MARIA EDUARDA LIMA SANTOS")
    db.commit()
    d = _decidir(db, esc, "LIMA SANTOS MARIA EDUARDA", SALA_2B)
    assert d.acao == ida.REVISAR and set(d.candidatos) == {a.id, b.id}


# --- dois estudantes com o mesmo nome; turmas diferentes -----------------------

def test_mesmo_nome_em_duas_turmas_cada_linha_vai_para_a_da_sua_sala(db, rede):
    esc = rede["escola"]
    na_b = _aluno(db, esc, rede["b"], "PEDRO LUCAS FARIAS")
    na_c = _aluno(db, esc, rede["c"], "PEDRO LUCAS FARIAS")
    db.commit()
    assert _decidir(db, esc, "PEDRO LUCAS FARIAS", "2 ANO B TARDE ANUAL").aluno_id == na_b.id
    assert _decidir(db, esc, "PEDRO LUCAS FARIAS", "2 ANO C TARDE ANUAL").aluno_id == na_c.id


def test_mesmo_nome_duas_vezes_na_mesma_sala_vai_para_revisao(db, rede):
    esc = rede["escola"]
    _aluno(db, esc, rede["b"], "LUCAS SILVA")
    _aluno(db, esc, rede["b"], "LUCAS SILVA")
    db.commit()
    d = _decidir(db, esc, "LUCAS SILVA", SALA_2B)
    assert d.acao == ida.REVISAR


# --- identificadores conflitantes ---------------------------------------------

@pytest.mark.parametrize("ficha,linha", [
    ({"ra": "000123456789"}, {"ra": "000987654321"}),                    # RA divergente
    ({"nascimento": date(2018, 3, 1)}, {"data_nascimento": "2017-11-20"}),  # nascimento
])
def test_identificador_divergente_veta_o_candidato_unico(db, rede, ficha, linha):
    """Nome idêntico e candidato único NÃO vencem RA/nascimento que provam outra
    criança: a linha nunca vai para essa ficha."""
    esc = rede["escola"]
    maria = _aluno(db, esc, rede["b"], "MARIA EDUARDA SANTOS LIMA",
                   ra=ficha.get("ra"), nascimento=ficha.get("nascimento"))
    db.commit()
    ctx = ida.carregar_contexto(db, esc.id)
    d = ida.decidir(ctx, ida.linha_de_dados(
        "MARIA EDUARDA SANTOS LIMA", {**linha, "elefante_student_id": "77"},
        plataforma="elefante", turma_nome=SALA_2B))
    # Vetada, ela deixa de ser candidata: a linha é de OUTRA criança (ficha nova
    # onde a escola permite; na sincronização sem permissão, revisão).
    assert (d.acao, d.aluno_id) == (ida.CRIAR, None)
    assert maria.id in d.vetados


def test_identificador_igual_confirma_nome_parcial(db, rede):
    """O mesmo RA nos dois lados é evidência forte: associa mesmo com nome parcial."""
    esc = rede["escola"]
    maria = _aluno(db, esc, rede["b"], "MARIA EDUARDA SANTOS LIMA", ra="000123456789")
    db.commit()
    ctx = ida.carregar_contexto(db, esc.id)
    d = ida.decidir(ctx, ida.linha_de_dados(
        "MARIA EDUARDA LIMA", {"ra": "000123456789", "elefante_student_id": "78"},
        plataforma="elefante", turma_nome=SALA_2B))
    assert (d.acao, d.aluno_id, d.via) == (ida.ASSOCIAR, maria.id, "ra")


# --- vínculo já existente -----------------------------------------------------

def test_conta_ja_vinculada_manda_mesmo_com_nome_diferente(db, rede):
    """A conta da plataforma é a evidência mais forte: vale antes de qualquer nome."""
    esc = rede["escola"]
    maria = _aluno(db, esc, rede["b"], "MARIA EDUARDA SANTOS LIMA")
    _conta(db, esc, maria, "elefante", "500")
    db.commit()
    d = _decidir(db, esc, "DUDA S L", SALA_2B, id_externo="500")
    assert (d.acao, d.aluno_id, d.via) == (ida.ASSOCIAR, maria.id, "identidade")


def test_segunda_conta_da_mesma_plataforma_na_mesma_ficha_vai_para_revisao(db, rede):
    """Duas contas na mesma ficha sobrescrevem uma à outra: decide gente."""
    esc = rede["escola"]
    maria = _aluno(db, esc, rede["b"], "MARIA EDUARDA SANTOS LIMA")
    _conta(db, esc, maria, "elefante", "500")
    db.commit()
    d = _decidir(db, esc, "MARIA EDUARDA SANTOS LIMA", SALA_2B, id_externo="501")
    assert (d.acao, d.motivo, d.aluno_id) == (ida.REVISAR, "outra_identidade_na_plataforma",
                                              maria.id)


# --- registros de diferentes plataformas ---------------------------------------

def test_caso_matias_grafia_no_meio_e_conta_de_outra_plataforma_associa(db, rede):
    """Padrão do caso relatado (nome fictício): a ficha oficial já tem a conta do
    MATIFIC; o ELEFANTE manda o nome com UMA letra diferente num nome do meio.
    A conta de outra plataforma não é conflito — só a da MESMA plataforma seria."""
    esc = rede["escola"]
    otavio = _aluno(db, esc, rede["b"], "OTAVIO RICARDO RODRIGUES MARQUES")
    _conta(db, esc, otavio, "matific", "u-otavio")
    _aluno(db, esc, rede["b"], "BIANCA SOARES TEIXEIRA")
    db.commit()
    d = _decidir(db, esc, "OTAVIO RICARDO RODRIGUEZ MARQUES", SALA_2B, id_externo="600")
    assert (d.acao, d.aluno_id, d.via) == (ida.ASSOCIAR, otavio.id, "variante")


def test_conta_de_uma_plataforma_nao_casa_linha_de_outra(db, rede):
    """O id do Matific não identifica ninguém no Elefante (e vice-versa): a linha do
    Elefante com o MESMO texto de id não vai para a dona da conta Matific por isso."""
    esc = rede["escola"]
    dona = _aluno(db, esc, rede["b"], "MARIA EDUARDA SANTOS LIMA")
    _conta(db, esc, dona, "matific", "700")
    outra = _aluno(db, esc, rede["b"], "JULIA COSTA RAMOS")
    db.commit()
    d = _decidir(db, esc, "JULIA COSTA RAMOS", SALA_2B, id_externo="700")
    assert (d.acao, d.aluno_id, d.via) == (ida.ASSOCIAR, outra.id, "exato")


# --- ausência de dados --------------------------------------------------------

def test_sem_turma_e_sem_candidato_nao_associa_por_aproximacao(db, rede):
    esc = rede["escola"]
    _aluno(db, esc, rede["b"], "MARIA EDUARDA SANTOS LIMA")
    db.commit()
    d = _decidir(db, esc, "JOAQUIM PEREIRA NUNES", "")
    assert (d.acao, d.aluno_id, d.motivo) == (ida.CRIAR, None, "sem_turma")


def test_sem_turma_e_nome_parecido_vai_para_revisao(db, rede):
    esc = rede["escola"]
    maria = _aluno(db, esc, rede["b"], "MARIA EDUARDA SANTOS LIMA")
    db.commit()
    d = _decidir(db, esc, "MARIA EDUARDA LIMA", "", plataforma="matific", id_externo="u-5")
    assert (d.acao, d.aluno_id) == (ida.REVISAR, maria.id)


# --- execução repetida (idempotência) -----------------------------------------

def test_reimportar_a_mesma_linha_nao_cria_vinculo_nem_ficha_nem_rastro_novo(db, rede):
    esc, admin = rede["escola"], rede["admin"]
    otavio = _aluno(db, esc, rede["b"], "OTAVIO RICARDO RODRIGUES MARQUES")
    db.commit()
    linha = _elefante("OTAVIO RICARDO RODRIGUEZ MARQUES", SALA_2B, 600)
    antes = _n_alunos(db, esc)

    _confirmar(db, esc, admin, "elefante", [linha])
    assert _dono(db, esc, "elefante", "600") == otavio.id
    logs_1 = db.execute(select(func.count()).select_from(LogAuditoria).where(
        LogAuditoria.acao == "aluno.vinculado_auto")).scalar_one()

    for _ in range(2):                                   # roda de novo, duas vezes
        _confirmar(db, esc, admin, "elefante",
                   [_elefante("OTAVIO RICARDO RODRIGUEZ MARQUES", SALA_2B, 600)])
    db.expire_all()
    assert _dono(db, esc, "elefante", "600") == otavio.id
    assert _contas(db, esc, "elefante", "600") == 1          # nenhum vínculo a mais
    assert _n_alunos(db, esc) == antes                       # nenhuma ficha nova
    assert _pendentes(db, esc) == []
    logs_3 = db.execute(select(func.count()).select_from(LogAuditoria).where(
        LogAuditoria.acao == "aluno.vinculado_auto")).scalar_one()
    assert logs_3 == logs_1 == 1     # 2ª e 3ª vez casam pela conta, sem novo "auto"


def test_rastro_do_vinculo_automatico_registra_regra_origem_e_momento(db, rede):
    esc, admin = rede["escola"], rede["admin"]
    otavio = _aluno(db, esc, rede["b"], "OTAVIO RICARDO RODRIGUES MARQUES")
    db.commit()
    _confirmar(db, esc, admin, "elefante",
               [_elefante("OTAVIO RICARDO RODRIGUEZ MARQUES", SALA_2B, 600)])
    log = db.execute(select(LogAuditoria).where(
        LogAuditoria.acao == "aluno.vinculado_auto",
        LogAuditoria.entidade_id == otavio.id)).scalars().one()
    assert log.detalhes["correspondencia"] == "variante"           # a regra
    assert log.detalhes["origem"] == "OTAVIO RICARDO RODRIGUEZ MARQUES"  # o recebido
    assert log.created_at is not None                               # o momento
    # A origem e o identificador originais ficam preservados: a conta gravada é a
    # da plataforma, e o nome da ficha não é trocado pelo recebido.
    assert _dono(db, esc, "elefante", "600") == otavio.id
    db.expire_all()
    assert db.get(Aluno, otavio.id).nome == "OTAVIO RICARDO RODRIGUES MARQUES"


def test_mapa_dos_casos_cobertos_em_outros_arquivos():
    """Onde estão os demais casos obrigatórios (para quem revisa a cobertura)."""
    import tests.test_identidade_automatica as auto
    import tests.test_revisao_encerramento_automatico as enc
    for nome in ("test_i_oficial_mais_stub_abreviado_e_typo_no_meio_vai_para_a_oficial",
                 "test_dois_candidatos_da_lista_piloto_na_mesma_turma_vao_para_revisao",
                 "test_iv_stub_com_conta_da_mesma_plataforma_vai_para_revisao",
                 "test_v_stub_com_identificador_divergente_da_oficial_vai_para_revisao",
                 "test_grafia_na_sala_nao_vence_nome_identico_em_outra_sala",
                 "test_vii_variacao_no_sobrenome_ou_primeiro_nome_continua_em_revisao"):
        assert hasattr(auto, nome), nome
    for nome in ("test_sincronizacao_encerra_cada_irma_com_a_linha_do_tipo_dela",
                 "test_decisao_revisar_mantem_a_pendencia",
                 "test_conta_contestada_nao_e_encerrada_pela_mesma_conta"):
        assert hasattr(enc, nome), nome
