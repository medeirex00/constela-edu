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


def test_variante_segura_nome_do_meio_vincula():
    """Caso real (Débora Pilon): variação no NOME DO MEIO com 1º nome e sobrenome
    idênticos (ABRAÃO LUÍS/LUIZ DIAS), 1 único candidato → VINCULA na origem, sem
    criar 2ª ficha. É a decisão do dono (2026-08-04)."""
    roster = [ident("ABRAÃO LUÍS DIAS", _id=1), ident("BEATRIZ SOUZA", _id=2)]
    r = classificar_linha(ident("ABRAAO LUIZ DIAS"), roster)
    assert r.status == VINCULADO and r.aluno_id == 1


def test_variante_no_sobrenome_vai_para_revisao():
    """SEGURANÇA (red-team 2026-08-04): variação no SOBRENOME (GABRIEL SOUZA/SOUSA)
    NÃO auto-vincula, mesmo com 1 único candidato — Souza e Sousa são famílias
    DIFERENTES, comuns no Brasil. Vai a REVISAR."""
    roster = [ident("GABRIEL SOUSA", _id=1)]
    r = classificar_linha(ident("GABRIEL SOUZA"), roster)
    assert r.status == REVISAR and r.aluno_id == 1


def test_variante_primeiro_nome_ou_genero_vai_para_revisao():
    """SEGURANÇA (red-team 2026-08-04): variação no 1º nome/gênero (BRUNO/BRUNA SILVA,
    GABRYEL/GABRIEL) NÃO auto-vincula — distingue crianças diferentes. Vai a REVISAR."""
    r1 = classificar_linha(ident("BRUNO SILVA"), [ident("BRUNA SILVA", _id=1)])
    assert r1.status == REVISAR and r1.aluno_id == 1
    r2 = classificar_linha(ident("GABRYEL SILVA"), [ident("GABRIEL SILVA", _id=2)])
    assert r2.status == REVISAR and r2.aluno_id == 2


def test_variante_insegura_com_chamada_igual_vincula_por_identificador():
    """Variação de grafia mesmo INSEGURA + nº de chamada IGUAL (único na turma) →
    vincula: o identificador prova ser a mesma criança, desempata a grafia."""
    roster = [ident("GABRIEL SILVA", _id=1, chamada=7)]
    r = classificar_linha(ident("GABRYEL SILVA", chamada=7), roster)
    assert r.status == VINCULADO and r.aluno_id == 1


def test_variante_dois_candidatos_vai_para_revisao():
    """A régua de segurança continua na AMBIGUIDADE: 'ANA LUZIA' casa como variante
    de 'ANA LUIZA' E de 'ANA LUCIA' → 2 candidatos → REVISAR (nunca auto-funde
    crianças diferentes)."""
    roster = [ident("ANA LUIZA SOUZA", _id=1), ident("ANA LUCIA SOUZA", _id=2)]
    r = classificar_linha(ident("ANA LUZIA SOUZA"), roster)
    assert r.status == REVISAR and set(r.candidatos) == {1, 2}


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
