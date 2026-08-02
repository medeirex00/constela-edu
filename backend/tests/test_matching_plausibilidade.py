"""Motor de plausibilidade de nome (spec do dono §1–§16): o vínculo de importação
conta CANDIDATOS PLAUSÍVEIS na mesma turma — 1 → vincula automático; 2+ → revisão;
0 → cria. Cobre os sinais novos: inicial no PRIMEIRO nome ("M. EDUARDA"),
truncamento ("MARIA EDU"), nome parcial e nº de chamada como âncora.

Nada aqui funde (a fusão é sempre manual, decisão do dono); o vínculo de import é
não-destrutivo. Variante de grafia (LUÍS/LUIZ) NÃO auto-vincula (fuzzy → cai em
'baixa', cria e a detecção surfaça para fusão manual).
"""
from types import SimpleNamespace

from datetime import date

from sqlalchemy import func, select

from app.models import Aluno, Escola, Matricula, Turma
from app.routers.importacoes import _casar_no_roster, _resolver_aluno
from app.services import importacao as svc
from app.services.importacao import casa_abreviado, tokens_nome


def _t(s):
    return tokens_nome(s)


# --- Primitiva casa_abreviado (unitário, sem banco) --------------------------

def test_abreviado_inicial_no_primeiro_nome():
    # "M. EDUARDA" → MARIA EDUARDA SILVA (a inicial M abrevia o 1º nome).
    assert casa_abreviado(_t("M. EDUARDA"), _t("MARIA EDUARDA SILVA"))


def test_abreviado_truncamento_de_token():
    # "MARIA EDU" → MARIA EDUARDA SILVA ("edu" é prefixo de "eduarda").
    assert casa_abreviado(_t("MARIA EDU"), _t("MARIA EDUARDA SILVA"))


def test_abreviado_inicial_no_ultimo_token():
    assert casa_abreviado(_t("ABRAAO L"), _t("ABRAAO LUIS DIAS"))


def test_abreviado_so_iniciais_sem_ancora_nao_casa():
    # "M S" (duas iniciais, nenhum token cheio) é loose demais → NÃO casa.
    assert not casa_abreviado(_t("M S"), _t("MARIA SILVA"))


def test_abreviado_e_posicional_nao_subsequencia():
    # "ELOA S" NÃO casa "ELOA MARIA SILVA" (S alinha com MARIA, não com SILVA).
    assert not casa_abreviado(_t("ELOA S"), _t("ELOA MARIA SILVA"))


def test_prefixo_puro_de_tokens_cheios_nao_e_abreviacao():
    # "JOAO SANTOS" ⊂ "JOAO SANTOS OLIVEIRA" é nome PARCIAL (token no fim), não
    # abreviação — casa_abreviado deve retornar False (vai p/ subconjunto/revisão).
    assert not casa_abreviado(_t("JOAO SANTOS"), _t("JOAO SANTOS OLIVEIRA"))
    assert not casa_abreviado(_t("ABRAAO LUIS"), _t("ABRAAO LUIS DIAS"))


def test_abreviado_primeiro_nome_diferente_nao_casa():
    assert not casa_abreviado(_t("MARIA E"), _t("MARCOS EDUARDO SILVA"))


# --- Vínculo no roster (integração) ------------------------------------------

def _linha(nome, turma_nome, numero_chamada=None, dados=None):
    return SimpleNamespace(nome=nome, aluno_id=None, criar_em_turma_id=None,
                           criar_em_turma_nome=turma_nome,
                           numero_chamada=numero_chamada, dados=dados or {})


def _escola_turma(db):
    esc = Escola(nome="EMEF Teste", ano_letivo_ativo=2026, status="ativa")
    db.add(esc)
    db.flush()
    turma = Turma(escola_id=esc.id, nome="5ºA", ano_escolar="5º Ano",
                  ano_letivo=2026, status="ativa")
    db.add(turma)
    db.flush()
    return esc, turma


def _matricular(db, esc, turma, nome, numero_chamada=None, piloto=True):
    a = Aluno(escola_id=esc.id, nome=nome, status="ativo", da_lista_piloto=piloto,
              numero_chamada=numero_chamada)
    db.add(a)
    db.flush()
    db.add(Matricula(escola_id=esc.id, aluno_id=a.id, turma_id=turma.id,
                     ano_letivo=2026))
    return a


def _conta(db, esc_id):
    return db.execute(select(func.count()).select_from(Aluno)
                      .where(Aluno.escola_id == esc_id)).scalar_one()


def test_maria_e_candidata_unica_vincula(db):
    """Spec §2/§9: 'MARIA E' com uma ÚNICA MARIA plausível na turma → alta."""
    esc, turma = _escola_turma(db)
    maria = _matricular(db, esc, turma, "MARIA EDUARDA SILVA")
    _matricular(db, esc, turma, "JOAO PEDRO SOUZA")
    _matricular(db, esc, turma, "ANA BEATRIZ OLIVEIRA")
    db.commit()
    aluno, conf = _casar_no_roster(db, esc.id, 2026, "MARIA E", turma)
    assert conf == "alta" and aluno is not None and aluno.id == maria.id


def test_m_ponto_eduarda_inicial_primeiro_nome_vincula(db):
    """Spec §2: inicial no PRIMEIRO nome ('M. EDUARDA') com candidata única → alta."""
    esc, turma = _escola_turma(db)
    maria = _matricular(db, esc, turma, "MARIA EDUARDA SILVA")
    db.commit()
    aluno, conf = _casar_no_roster(db, esc.id, 2026, "M. EDUARDA", turma)
    assert conf == "alta" and aluno.id == maria.id


def test_maria_edu_truncamento_vincula(db):
    esc, turma = _escola_turma(db)
    maria = _matricular(db, esc, turma, "MARIA EDUARDA SILVA")
    db.commit()
    aluno, conf = _casar_no_roster(db, esc.id, 2026, "MARIA EDU", turma)
    assert conf == "alta" and aluno.id == maria.id


def test_maria_e_duas_candidatas_e_ambiguo(db):
    """Spec §6/§16: 'MARIA E' com Maria EDUARDA e Maria ELISA → 2 candidatas →
    NÃO vincula (media), vai para revisão manual."""
    esc, turma = _escola_turma(db)
    _matricular(db, esc, turma, "MARIA EDUARDA SILVA")
    _matricular(db, esc, turma, "MARIA ELISA SOUZA")
    db.commit()
    aluno, conf = _casar_no_roster(db, esc.id, 2026, "MARIA E", turma)
    assert conf == "media" and aluno is None


def test_nome_parcial_subconjunto_nao_auto_vincula(db):
    """SEGURANÇA (revisão adversarial): nome PARCIAL por subconjunto ('MARIA SILVA'
    ⊂ 'MARIA EDUARDA SILVA', ou 'JOAO SANTOS' ⊂ 'JOAO SANTOS OLIVEIRA') NÃO
    auto-vincula (sobrenome comum + dono real ausente poderia colar na criança
    errada). Com 1 candidato, NÃO retorna "alta": cria (baixa) e a detecção o surfaça
    como possível duplicata p/ fusão manual — nunca vínculo automático."""
    esc, turma = _escola_turma(db)
    _matricular(db, esc, turma, "MARIA EDUARDA SILVA")       # token faltando no MEIO
    _matricular(db, esc, turma, "JOAO SANTOS OLIVEIRA")      # token faltando no FIM
    db.commit()
    for parcial in ("MARIA SILVA", "JOAO SANTOS"):
        aluno, conf = _casar_no_roster(db, esc.id, 2026, parcial, turma)
        assert conf != "alta" and aluno is None            # nunca auto-vincula


def test_nome_parcial_ambiguo_segura_sem_criar(db):
    """Nome parcial que casa DUAS crianças (ambíguo) → 'media' (não cria órfão)."""
    esc, turma = _escola_turma(db)
    _matricular(db, esc, turma, "MARIA EDUARDA SILVA")
    _matricular(db, esc, turma, "MARIA SILVA SANTOS")       # 2 candidatas p/ "MARIA SILVA"
    db.commit()
    aluno, conf = _casar_no_roster(db, esc.id, 2026, "MARIA SILVA", turma)
    assert conf == "media" and aluno is None


def test_veto_nascimento_divergente_nao_vincula(db):
    """VETO de identidade: mesma abreviação plausível, mas data de nascimento
    DIVERGENTE prova serem crianças diferentes → não vincula (cria/revisa)."""
    esc, turma = _escola_turma(db)
    from datetime import date
    m = _matricular(db, esc, turma, "MARIA EDUARDA SILVA")
    m.data_nascimento = date(2016, 5, 1)
    db.commit()
    aluno, conf = _casar_no_roster(db, esc.id, 2026, "MARIA E", turma,
                                   nascimento=date(2017, 9, 20))
    assert aluno is None and conf == "baixa"     # vetada → nenhum candidato


def test_numero_de_chamada_desfaz_ambiguidade(db):
    """Spec (nº de chamada como sinal): duas MARIA E plausíveis, mas a chamada bate
    exatamente uma → âncora resolve → alta na aluna certa."""
    esc, turma = _escola_turma(db)
    _matricular(db, esc, turma, "MARIA EDUARDA SILVA", numero_chamada=7)
    elisa = _matricular(db, esc, turma, "MARIA ELISA SOUZA", numero_chamada=12)
    db.commit()
    aluno, conf = _casar_no_roster(db, esc.id, 2026, "MARIA E", turma, numero_chamada=12)
    assert conf == "alta" and aluno.id == elisa.id


def test_nenhum_candidato_plausivel_cria_novo(db):
    """Spec §11/§14: sem candidato plausível → cria novo (baixa)."""
    esc, turma = _escola_turma(db)
    _matricular(db, esc, turma, "MARIA EDUARDA SILVA")
    db.commit()
    antes = _conta(db, esc.id)
    r = _resolver_aluno(db, esc.id, 2026,
                        _linha("RICARDO GOMES LEAL", "5ºA"), [], {}, {})
    assert r is not None and r.nome == "RICARDO GOMES LEAL"
    assert _conta(db, esc.id) == antes + 1


def test_previa_usa_o_mesmo_motor_da_confirmacao(db):
    """PONTO 2: a PRÉVIA (casar_nomes) passa pelo MESMO motor que a confirmação.
    'M. EDUARDA' (que a busca difusa marcaria 'nao_encontrado') com turma no
    relatório e uma única Maria plausível → prévia mostra 'vinculado' (= o que a
    confirmação fará), nunca 'aluno novo'."""
    esc, turma = _escola_turma(db)
    _matricular(db, esc, turma, "MARIA EDUARDA SILVA")
    db.commit()
    linhas = [svc.LinhaImportacao(numero=1, nome="M. EDUARDA",
                                  dados={"turma_relatorio": "5ºA"})]
    svc.casar_nomes(db, esc.id, linhas)
    assert linhas[0].correspondencia["status"] == "vinculado"


def test_previa_typo_mostra_possivel_duplicata_sem_pre_selecionar(db):
    """PONTO 1+2: typo no 1º nome (GABRYEL/GABRIEL) na mesma turma → 'revisar'
    (possível duplicata) na PRÉVIA — NÃO 'provavel' (que pré-selecionaria e viraria
    vínculo por um clique). Grafia parecida nunca vincula sozinha."""
    esc, turma = _escola_turma(db)
    _matricular(db, esc, turma, "GABRIEL SILVA")
    db.commit()
    linhas = [svc.LinhaImportacao(numero=1, nome="GABRYEL SILVA",
                                  dados={"turma_relatorio": "5ºA"})]
    svc.casar_nomes(db, esc.id, linhas)
    assert linhas[0].correspondencia["status"] == "revisar"
    assert linhas[0].correspondencia["aluno_id"] is not None      # sugere o candidato


def test_previa_bloqueado_por_conflito_de_identidade(db):
    """PONTO 2: nome casa (M. EDUARDA → MARIA EDUARDA) mas o nascimento diverge →
    prévia mostra 'bloqueado' (não vincula; cria como criança diferente)."""
    esc, turma = _escola_turma(db)
    m = _matricular(db, esc, turma, "MARIA EDUARDA SILVA")
    m.data_nascimento = date(2016, 5, 1)
    db.commit()
    linhas = [svc.LinhaImportacao(numero=1, nome="M. EDUARDA",
                                  dados={"turma_relatorio": "5ºA",
                                         "data_nascimento": "2017-09-20"})]
    svc.casar_nomes(db, esc.id, linhas)
    assert linhas[0].correspondencia["status"] == "bloqueado"


def test_inicial_primeiro_nome_reimport_idempotente(db):
    """Spec §13: reimportar 'M. EDUARDA' 3x nunca cria duplicata (vincula à mesma)."""
    esc, turma = _escola_turma(db)
    maria = _matricular(db, esc, turma, "MARIA EDUARDA SILVA")
    db.commit()
    antes = _conta(db, esc.id)
    for _ in range(3):
        r = _resolver_aluno(db, esc.id, 2026,
                            _linha("M. EDUARDA", "5ºA"), [], {}, {})
        assert r is not None and r.id == maria.id
    assert _conta(db, esc.id) == antes
