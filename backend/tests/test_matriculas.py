"""Testes unitários do núcleo PURO do casamento de matrículas (matriculas.py).

Sem banco e sem I/O: dados simples entram, decisões saem. É aqui que a lógica
difícil (RA × nome-exato × abreviação posicional, unicidade bipartida, vetos)
fica coberta isoladamente — as integrações ficam em test_lista_piloto.py.
"""
from datetime import date

from app.services import matriculas as m
from app.services.importacao import tokens_nome, tokens_turma
from app.services.matriculas import AlunoRef, ContextoCasamento, LinhaMatricula


# --- helpers de montagem --------------------------------------------------

def _linha(nome, *, ra=None, turma_id=1, turma="1º Ano A", nasc=None) -> LinhaMatricula:
    return LinhaMatricula(nome=nome, ra=ra, nascimento=nasc, turma_id=turma_id,
                          turma_tokens=frozenset(tokens_turma(turma)))


def _ref(id_, nome, *, nasc=None, turmas=("1º Ano A",)) -> AlunoRef:
    return AlunoRef(id=id_, nome=nome, data_nascimento=nasc,
                    turmas_tokens=tuple(frozenset(tokens_turma(t)) for t in turmas))


def _pool(*refs) -> ContextoCasamento:
    """Contexto só com o POOL, chaveado como o código real (1º token do nome)."""
    pool: dict[str, list[AlunoRef]] = {}
    for r in refs:
        pool.setdefault(tokens_nome(r.nome)[0], []).append(r)
    return ContextoCasamento(pool_por_primeiro={k: tuple(v) for k, v in pool.items()})


# --- parse_nascimento ------------------------------------------------------

def test_parse_nascimento():
    assert m.parse_nascimento("2019-09-18") == date(2019, 9, 18)
    assert m.parse_nascimento(None) is None
    assert m.parse_nascimento("") is None
    assert m.parse_nascimento("18/09/2019") is None    # formato inválido → None
    assert m.parse_nascimento("2019-13-40") is None     # data impossível → None


# --- chave_turma -----------------------------------------------------------

def test_chave_turma_ignora_ordinal_acento_caixa():
    assert m.chave_turma("5º Ano B") == m.chave_turma("5 ANO B")
    assert m.chave_turma("1º Ano A") == m.chave_turma("1 ano a")
    assert m.chave_turma("1º Ano A") != m.chave_turma("1º Ano B")


# --- overlap_turma ---------------------------------------------------------

def test_overlap_turma_ignora_palavras_ubiquas():
    a = frozenset(tokens_turma("1º Ano A"))
    assert m.overlap_turma(a, frozenset(tokens_turma("1 ANO A MANHA"))) >= 2  # série+letra
    assert m.overlap_turma(a, frozenset(tokens_turma("4º Ano A"))) < 2         # só a letra
    assert m.overlap_turma(a, frozenset(tokens_turma("1º Ano B"))) < 2         # só a série


# --- nomes_compativeis -----------------------------------------------------

def test_nomes_compativeis():
    assert m.nomes_compativeis("AGATHA VITORIA", "AGATHA VITORIA")
    assert m.nomes_compativeis("AGATHA V", "AGATHA VITORIA MOURA")   # abreviação
    assert not m.nomes_compativeis("JOAO PEDRO SILVA", "MARIA SOUZA LIMA")  # 1º token difere
    assert m.nomes_compativeis("", "QUALQUER")                       # vazio → conservador


# --- casa_forte ------------------------------------------------------------

def test_casa_forte_por_ra_com_nome_compativel():
    ctx = ContextoCasamento(por_ra={"123": AlunoRef(1, "AGATHA VITORIA MOURA")})
    assert m.casa_forte(_linha("AGATHA VITORIA MOURA DA SILVA", ra="123"), ctx)


def test_casa_forte_por_ra_recusa_nome_de_outra_pessoa():
    ctx = ContextoCasamento(por_ra={"123": AlunoRef(1, "AGATHA VITORIA MOURA")})
    assert not m.casa_forte(_linha("JOAO PEDRO SILVA", ra="123"), ctx)


def test_casa_forte_por_nome_na_mesma_turma():
    ctx = ContextoCasamento(
        por_nome_turma={(m.normalizar("ANA BEATRIZ"), 1): AlunoRef(2, "ANA BEATRIZ")})
    assert m.casa_forte(_linha("Ana Beatriz", turma_id=1), ctx)
    assert not m.casa_forte(_linha("Ana Beatriz", turma_id=2), ctx)   # outra turma


# --- candidatos_abreviados -------------------------------------------------

def test_candidatos_casa_por_abreviacao_na_mesma_turma():
    ctx = _pool(_ref(1, "AGATHA V"))
    cands = m.candidatos_abreviados(_linha("AGATHA VITORIA MOURA DA SILVA"), ctx)
    assert [c.id for c in cands] == [1]


def test_candidatos_veta_turma_divergente():
    ctx = _pool(_ref(1, "AGATHA V", turmas=("5º Ano B",)))
    assert m.candidatos_abreviados(_linha("AGATHA VITORIA MOURA"), ctx) == []


def test_candidatos_veta_nascimento_divergente():
    ctx = _pool(_ref(1, "AGATHA V", nasc=date(2018, 3, 1)))
    linha = _linha("AGATHA VITORIA MOURA", nasc=date(2019, 7, 10))
    assert m.candidatos_abreviados(linha, ctx) == []


def test_candidatos_nome_curto_nao_casa():
    ctx = _pool(_ref(1, "ANA B"))
    assert m.candidatos_abreviados(_linha("ANA"), ctx) == []   # < 2 tokens


def test_candidatos_recusa_subsequencia_nao_posicional():
    # "ELOA S" não abrevia "ELOA VITORIA DA SILVA MARADEI" (S não é o 2º token).
    ctx = _pool(_ref(1, "ELOA S"))
    assert m.candidatos_abreviados(_linha("ELOA VITORIA DA SILVA MARADEI"), ctx) == []


# --- casar_abreviados (unicidade bipartida) --------------------------------

def test_casar_um_para_um_inequivoco():
    ctx = _pool(_ref(9, "PEDRO L"))
    casar, avisos = m.casar_abreviados([_linha("PEDRO LUCAS SANTOS")], ctx)
    assert casar == {0: 9} and avisos == []


def test_casar_um_candidato_para_duas_linhas_e_ambiguo():
    # O mesmo antigo abrevia DUAS linhas do lote → nenhuma casa (evita erro 1:N).
    ctx = _pool(_ref(1, "AGATHA V"))
    linhas = [_linha("AGATHA VITORIA MOURA"), _linha("AGATHA VALENTINA LIMA")]
    casar, avisos = m.casar_abreviados(linhas, ctx)
    assert casar == {}
    assert len(avisos) == 2 and all("Fundir alunos" in a for a in avisos)


def test_casar_dois_candidatos_para_uma_linha_e_ambiguo():
    ctx = _pool(_ref(1, "AGATHA V"), _ref(2, "AGATHA V"))
    casar, avisos = m.casar_abreviados([_linha("AGATHA VITORIA MOURA")], ctx)
    assert casar == {} and len(avisos) == 1


def test_casar_ignora_quem_ja_casa_forte():
    ctx = ContextoCasamento(
        por_ra={"123": AlunoRef(5, "AGATHA VITORIA MOURA")},
        pool_por_primeiro={tokens_nome("AGATHA V")[0]: (_ref(1, "AGATHA V"),)})
    casar, avisos = m.casar_abreviados(
        [_linha("AGATHA VITORIA MOURA DA SILVA", ra="123")], ctx)
    assert casar == {} and avisos == []   # casou forte por RA → fora do abreviado


# --- aviso_ambiguidade -----------------------------------------------------

def test_aviso_ambiguidade_menciona_fundir():
    msg = m.aviso_ambiguidade("AGATHA VITORIA", "AGATHA V, AGATHA VALENTINA")
    assert "AGATHA VITORIA" in msg and "Fundir alunos" in msg
