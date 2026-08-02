"""Motor ÚNICO de identificação (app/services/matching.py) — testado isolado, sem
banco. Cobre o veredito de plausibilidade por nome, os vetos/corroborações de
identidade e a classificação linha-contra-roster (vinculado/revisar/novo/bloqueado)."""
from datetime import date

from app.services import matching as m
from app.services.matching import (
    BLOQUEADO,
    NOVO,
    REVISAR,
    VINCULADO,
    Identidade,
    classificar_linha,
    plausivel,
)


def ident(nome, **kw):
    kw.setdefault("id", kw.pop("_id", None))
    return Identidade(nome=nome, **kw)


# --- plausivel (veredito por nome) -------------------------------------------

def test_plausivel_exato_ignora_acento_e_ordem():
    assert plausivel("ABRAÃO LUÍS DIAS", "ABRAAO LUIS DIAS") == "forte"
    assert plausivel("MARIA SILVA", "SILVA MARIA") == "forte"


def test_plausivel_abreviacao_inicial_e_truncamento():
    assert plausivel("MARIA E", "MARIA EDUARDA SILVA") == "forte"
    assert plausivel("M. EDUARDA", "MARIA EDUARDA SILVA") == "forte"
    assert plausivel("MARIA EDU", "MARIA EDUARDA SILVA") == "forte"
    assert plausivel("ABRAAO L", "ABRAÃO LUÍS DIAS") == "forte"


def test_plausivel_parcial_subconjunto():
    assert plausivel("MARIA SILVA", "MARIA EDUARDA SILVA") == "parcial"
    assert plausivel("JOAO SANTOS", "JOAO SANTOS OLIVEIRA") == "parcial"


def test_plausivel_fraco_variante_e_typo():
    assert plausivel("ABRAÃO LUÍS DIAS", "ABRAÃO LUIZ DIAS") == "fraco"     # variante
    assert plausivel("GABRYEL SILVA", "GABRIEL SILVA") == "fraco"           # typo 1º nome


def test_plausivel_nomes_diferentes_nao_casa():
    assert plausivel("MARIA E", "MARCOS EDUARDO SILVA") is None
    assert plausivel("ABRAÃO LUÍS DIAS", "ABRAÃO LUCAS DIAS") is None       # LUÍS≠LUCAS


# --- vetos / corroborações ---------------------------------------------------

def test_conflito_por_nascimento_e_chamada_e_ra():
    a = ident("MARIA E", nascimento=date(2016, 1, 1))
    b = ident("MARIA EDUARDA", nascimento=date(2017, 1, 1))
    assert m.conflito_identidade(a, b)
    assert m.conflito_identidade(ident("X", chamada=1), ident("Y", chamada=2))
    assert m.conflito_identidade(ident("X", ra="111"), ident("Y", ra="222"))
    assert not m.conflito_identidade(ident("X", chamada=1), ident("Y"))     # falta dado


def test_corrobora_por_identificador_igual():
    assert m.corrobora_identidade(ident("X", chamada=5), ident("Y", chamada=5))
    assert m.corrobora_identidade(ident("X", uuids=frozenset({"u1"})),
                                  ident("Y", uuids=frozenset({"u1"})))


# --- classificar_linha -------------------------------------------------------

def test_um_forte_unico_vincula():
    roster = [ident("MARIA EDUARDA SILVA", _id=1), ident("JOAO PEDRO", _id=2)]
    r = classificar_linha(ident("MARIA E"), roster)
    assert r.status == VINCULADO and r.aluno_id == 1


def test_dois_fortes_vao_para_revisao():
    roster = [ident("MARIA EDUARDA SILVA", _id=1), ident("MARIA ELISA SOUZA", _id=2)]
    r = classificar_linha(ident("MARIA E"), roster)
    assert r.status == REVISAR and set(r.candidatos) == {1, 2}


def test_parcial_unico_vai_para_revisao():
    roster = [ident("JOAO SANTOS OLIVEIRA", _id=1)]
    r = classificar_linha(ident("JOAO SANTOS"), roster)
    assert r.status == REVISAR and r.aluno_id == 1 and r.motivo == "parcial"


def test_typo_unico_vai_para_revisao_nunca_vincula():
    roster = [ident("GABRIEL SILVA", _id=1)]
    r = classificar_linha(ident("GABRYEL SILVA"), roster)
    assert r.status == REVISAR and r.aluno_id == 1 and r.motivo == "typo"


def test_typo_com_chamada_igual_ainda_e_revisao():
    """Grafia parecida NUNCA vira vínculo automático, mesmo com chamada igual —
    é sugestão de revisão (decisão do dono)."""
    roster = [ident("GABRIEL SILVA", _id=1, chamada=7)]
    r = classificar_linha(ident("GABRYEL SILVA", chamada=7), roster)
    assert r.status == REVISAR


def test_uuid_em_comum_vincula_direto():
    roster = [ident("QUALQUER NOME", _id=9, uuids=frozenset({"uuid-x"}))]
    r = classificar_linha(ident("OUTRO NOME", uuids=frozenset({"uuid-x"})), roster)
    assert r.status == VINCULADO and r.aluno_id == 9 and r.motivo == "uuid"


def test_chamada_corrobora_forte_vincula_mesmo_com_dois_candidatos():
    roster = [ident("MARIA EDUARDA SILVA", _id=1, chamada=7),
              ident("MARIA ELISA SOUZA", _id=2, chamada=12)]
    r = classificar_linha(ident("MARIA E", chamada=12), roster)
    assert r.status == VINCULADO and r.aluno_id == 2 and r.motivo == "identificador"


def test_conflito_de_identidade_bloqueia():
    roster = [ident("MARIA EDUARDA SILVA", _id=1, nascimento=date(2016, 5, 1))]
    r = classificar_linha(ident("MARIA E", nascimento=date(2017, 9, 20)), roster)
    assert r.status == BLOQUEADO and r.aluno_id is None


def test_nenhum_candidato_e_novo():
    roster = [ident("RICARDO GOMES", _id=1)]
    r = classificar_linha(ident("BEATRIZ CAMPOS SOUZA"), roster)
    assert r.status == NOVO and r.aluno_id is None


def test_nascimento_nao_corrobora_nome_parcial():
    """Achado adversarial: aniversário NÃO é único (colisões numa turma). Sobre um
    nome PARCIAL (subconjunto), nascimento igual NÃO pode auto-vincular — poderia
    juntar duas crianças diferentes que fazem aniversário no mesmo dia."""
    roster = [ident("ANA", _id=1, nascimento=date(2015, 5, 20))]     # só 1º nome
    r = classificar_linha(ident("ANA JULIA", nascimento=date(2015, 5, 20)), roster)
    assert r.status == REVISAR      # parcial + nascimento igual → revisão, não vínculo


def test_chamada_corrobora_nome_parcial():
    """Nº de chamada É único por turma → corrobora até nome parcial → vincula."""
    roster = [ident("ANA JULIA SOUZA", _id=1, chamada=5)]
    r = classificar_linha(ident("ANA JULIA", chamada=5), roster)
    assert r.status == VINCULADO and r.aluno_id == 1
