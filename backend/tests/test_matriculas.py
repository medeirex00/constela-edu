"""Testes unitários do núcleo PURO do casamento de matrículas (matriculas.py).

Sem banco e sem I/O: dados simples entram, decisões saem. É aqui que a lógica
difícil (RA × roster da sala × mudança de sala × vetos de identidade) fica
coberta isoladamente — as integrações ficam em test_lista_piloto.py.

Estes testes foram REESCRITOS junto com a 4ª causa raiz das duplicatas
(2026-08-11): o que existia aqui cobria o SEGUNDO motor de identidade da Lista
Piloto (``casa_forte``/``candidatos_abreviados``/``casar_abreviados`` sobre um
pool restrito a cadastros de upload), que foi eliminado. A decisão agora é do
motor único, através de ``resolver_linha``; cada caso do motor antigo tem aqui o
seu equivalente, com o desfecho novo quando a regra mudou (ambíguo/inseguro não
cria mais: vai para REVISÃO).
"""
from datetime import date

from app.services import matching
from app.services import matriculas as m
from app.services.importacao import tokens_turma
from app.services.matriculas import ContextoCasamento, LinhaMatricula


# --- helpers de montagem --------------------------------------------------

def _linha(nome, *, ra=None, turma_id=1, turma="1º Ano A", nasc=None,
           chamada=None) -> LinhaMatricula:
    return LinhaMatricula(nome=nome, ra=ra, nascimento=nasc, turma_id=turma_id,
                          chave_sala=m.chave_turma(turma), chamada=chamada)


def _ident(id_, nome, *, nasc=None, ra="", chamada=None, piloto=False):
    return matching.Identidade(id=id_, nome=nome, nascimento=nasc, ra=ra,
                               chamada=chamada, da_lista_piloto=piloto)


def _ctx(*pares) -> ContextoCasamento:
    """Contexto a partir de (Identidade, nome da sala) — sala None = aluno sem
    matrícula no ano ativo."""
    ctx = ContextoCasamento()
    for ident, sala in pares:
        ctx.registrar(ident, m.chave_turma(sala) if sala else None)
    return ctx


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


def test_chave_turma_ignora_turno_do_nome():
    """O turno embutido no NOME (ruído do SED) NÃO entra na chave — senão a
    importação recria a duplicata. "2ºA", "2 ANO A INTEGRAL" e "2 ANO A MANHA"
    são a MESMA sala (a diferença de turno real vive no campo, não no nome)."""
    base = m.chave_turma("2ºA")
    assert m.chave_turma("2 ANO A INTEGRAL (300303111)") == base
    assert m.chave_turma("2 ANO A MANHA ANUAL") == base
    assert m.chave_turma("2 ANO A TARDE") == base
    # Série/letra continuam separando salas de verdade.
    assert m.chave_turma("2 ANO B INTEGRAL") != base
    assert m.chave_turma("3 ANO A INTEGRAL") != base


def test_turno_codigo_do_campo_vs_do_nome():
    assert m.turno_codigo("Tarde") == "T"
    assert m.turno_codigo("vespertino") == "T"
    assert m.turno_codigo("Manhã") == "M"
    assert m.turno_codigo("") == "" and m.turno_codigo(None) == ""
    # Do nome (sinal fraco): reconhece o turno nominal, mas é só fallback.
    assert m.turno_do_nome("2 ANO A INTEGRAL (300303111)") == "I"
    assert m.turno_do_nome("3 ANO A MANHA ANUAL") == "M"
    assert m.turno_do_nome("2ºA") == ""          # nome curto não tem turno


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


# --- resolver_linha: RA (identificador mais forte) --------------------------

def test_ra_reusa_o_cadastro_da_escola_inteira():
    ctx = _ctx((_ident(1, "AGATHA VITORIA MOURA", ra="123"), "5º Ano B"))
    d = m.resolver_linha(_linha("AGATHA VITORIA MOURA DA SILVA", ra="123"), ctx)
    assert (d.acao, d.aluno_id, d.motivo) == (m.REUSAR, 1, "ra")


def test_ra_de_outra_pessoa_nao_reusa():
    """RA colidindo com nome de outra pessoa (placeholder digitado pela
    secretaria) não identifica ninguém — cai no roster e vira aluno novo."""
    ctx = _ctx((_ident(1, "AGATHA VITORIA MOURA", ra="123"), "1º Ano A"))
    d = m.resolver_linha(_linha("JOAO PEDRO SILVA", ra="123"), ctx)
    assert d.acao == m.CRIAR


# --- resolver_linha: roster da SALA (motor único) ---------------------------

def test_nome_exato_na_sala_reusa():
    ctx = _ctx((_ident(2, "ANA BEATRIZ SOUZA"), "1º Ano A"))
    assert m.resolver_linha(_linha("Ana  Beatriz  Souza"), ctx).aluno_id == 2


def test_abreviacao_na_sala_reusa():
    ctx = _ctx((_ident(1, "AGATHA V"), "1º Ano A"))
    d = m.resolver_linha(_linha("AGATHA VITORIA MOURA DA SILVA"), ctx)
    assert (d.acao, d.aluno_id) == (m.REUSAR, 1)


def test_sala_divergente_nao_casa_por_abreviacao():
    """Abreviação em OUTRA sala é evidência fraca demais para atravessar a
    fronteira da turma — cria (e a fusão manual continua disponível)."""
    ctx = _ctx((_ident(1, "AGATHA V"), "5º Ano B"))
    assert m.resolver_linha(_linha("AGATHA VITORIA MOURA"), ctx).acao == m.CRIAR


def test_veta_nascimento_divergente_e_cria():
    ctx = _ctx((_ident(1, "AGATHA V", nasc=date(2018, 3, 1)), "1º Ano A"))
    d = m.resolver_linha(_linha("AGATHA VITORIA MOURA", nasc=date(2019, 7, 10)), ctx)
    assert d.acao == m.CRIAR       # identidade prova ser outra criança


def test_nome_parcial_vai_para_revisao():
    """REGRA ATUALIZADA: "ANA" contra "ANA BEATRIZ" é nome PARCIAL — inseguro. O
    motor antigo devolvia "nenhum candidato" (nome < 2 tokens) e a Lista Piloto
    criava a segunda ficha; agora vai para revisão e NÃO cria."""
    ctx = _ctx((_ident(1, "ANA BEATRIZ"), "1º Ano A"))
    assert m.resolver_linha(_linha("ANA"), ctx).acao == m.REVISAR


def test_recusa_subsequencia_nao_posicional():
    # "ELOA S" não abrevia "ELOA VITORIA DA SILVA MARADEI" (S não é o 2º token).
    ctx = _ctx((_ident(1, "ELOA S"), "1º Ano A"))
    assert m.resolver_linha(_linha("ELOA VITORIA DA SILVA MARADEI"), ctx).acao == m.CRIAR


def test_variante_segura_de_nome_do_meio_reusa():
    """LUÍS↔LUIZ (nome do meio, pontas idênticas) é a mesma criança — a MESMA
    regra dos imports de plataforma (matching.vincula_por_nome_unico)."""
    ctx = _ctx((_ident(1, "ABRAAO LUIZ DIAS"), "1º Ano A"))
    d = m.resolver_linha(_linha("ABRAÃO LUÍS DIAS"), ctx)
    assert (d.acao, d.aluno_id) == (m.REUSAR, 1)


def test_variante_no_sobrenome_vai_para_revisao():
    """SOUZA/SOUSA (último token) pode ser outra família: nunca auto-vincula. E
    também não cria mais às cegas — vai para revisão."""
    ctx = _ctx((_ident(1, "GABRIEL PEDRO SOUSA"), "1º Ano A"))
    assert m.resolver_linha(_linha("GABRIEL PEDRO SOUZA"), ctx).acao == m.REVISAR


def test_veta_variante_com_nascimento_divergente():
    ctx = _ctx((_ident(1, "ABRAAO LUIZ DIAS", nasc=date(2017, 5, 1)), "1º Ano A"))
    d = m.resolver_linha(_linha("ABRAÃO LUÍS DIAS", nasc=date(2018, 9, 20)), ctx)
    assert d.acao == m.CRIAR


def test_dois_candidatos_na_sala_vao_para_revisao():
    ctx = _ctx((_ident(1, "AGATHA V"), "1º Ano A"), (_ident(2, "AGATHA V"), "1º Ano A"))
    d = m.resolver_linha(_linha("AGATHA VITORIA MOURA"), ctx)
    assert d.acao == m.REVISAR and set(d.candidatos) == {1, 2}


def test_chamada_diferente_com_mesmo_nascimento_e_renumeracao_nao_duplicata():
    """A secretaria renumera a turma quando alguém sai. Nome igual + nascimento
    igual + chamada diferente é RENUMERAÇÃO, não outra criança."""
    ctx = _ctx((_ident(1, "MARIA EDUARDA SILVA", nasc=date(2015, 3, 1), chamada=5),
                "1º Ano A"))
    d = m.resolver_linha(
        _linha("MARIA EDUARDA SILVA", nasc=date(2015, 3, 1), chamada=4), ctx)
    assert (d.acao, d.aluno_id) == (m.REUSAR, 1)


def test_chamada_diferente_sem_nada_estavel_separa_homonimos():
    """Sem nascimento/RA, o nº de chamada volta a ser o único sinal — e separa."""
    ctx = _ctx((_ident(1, "JOAO SILVA", chamada=1), "1º Ano A"))
    d = m.resolver_linha(_linha("JOAO SILVA", chamada=2), ctx)
    assert d.acao == m.CRIAR


# --- unicidade 1:1 do LOTE (o candidato disputado por duas linhas) ----------
# Herdeiro do antigo ``test_casar_um_candidato_para_duas_linhas_e_ambiguo``: o
# motor antigo tinha unicidade BIPARTIDA e recusava o 1:N; ``resolver_linha``
# decide uma linha por vez e sozinho entregaria o cadastro à PRIMEIRA do arquivo.

def test_candidato_que_abrevia_duas_linhas_e_disputado():
    ctx = _ctx((_ident(1, "AGATHA V"), "1º Ano A"))
    linhas = [_linha("AGATHA VITORIA MOURA"), _linha("AGATHA VALENTINA LIMA")]
    assert m.candidatos_disputados(linhas, ctx) == {1}


def test_disputa_manda_as_duas_linhas_para_revisao_em_vez_de_chutar():
    """Sem isto, a 1ª linha do arquivo levava o cadastro (e os dados de
    plataforma presos a ele) — 50% de chance de grudar na criança errada."""
    ctx = _ctx((_ident(1, "AGATHA V"), "1º Ano A"))
    linhas = [_linha("AGATHA VITORIA MOURA"), _linha("AGATHA VALENTINA LIMA")]
    disputados = m.candidatos_disputados(linhas, ctx)
    for linha in linhas:
        d = m.arbitrar_disputa(m.resolver_linha(linha, ctx), disputados)
        assert d.acao == m.REVISAR and d.motivo == "disputado_por_varias_linhas"


def test_uma_linha_so_nao_e_disputa():
    ctx = _ctx((_ident(1, "AGATHA V"), "1º Ano A"))
    linhas = [_linha("AGATHA VITORIA MOURA")]
    assert m.candidatos_disputados(linhas, ctx) == set()
    d = m.arbitrar_disputa(m.resolver_linha(linhas[0], ctx), set())
    assert (d.acao, d.aluno_id) == (m.REUSAR, 1)


def test_mesmo_ra_em_duas_linhas_nao_e_disputa():
    """Duas linhas do MESMO aluno (mesmo RA, ex.: aparece em duas turmas do
    arquivo) são a mesma criança — não podem virar revisão."""
    ctx = _ctx((_ident(1, "MARIA EDUARDA SILVA", ra="123"), "1º Ano A"))
    linhas = [_linha("MARIA EDUARDA SILVA", ra="123"),
              _linha("MARIA EDUARDA SILVA", ra="123", turma="1º Ano B")]
    assert m.candidatos_disputados(linhas, ctx) == set()


def test_mesma_linha_repetida_nao_e_disputa():
    """Duas linhas com o MESMO nome apontando para o mesmo cadastro é repetição,
    não disputa: só nomes DIFERENTES caracterizam o 1:N."""
    ctx = _ctx((_ident(1, "AGATHA V"), "1º Ano A"))
    linhas = [_linha("AGATHA VITORIA MOURA"), _linha("AGATHA VITORIA MOURA")]
    assert m.candidatos_disputados(linhas, ctx) == set()


# --- resolver_linha: mudança de SALA ---------------------------------------

def test_mudanca_de_sala_com_prova_reusa():
    """Trocar de turma não faz de ninguém uma pessoa nova: nome idêntico + prova
    de identidade (nascimento) → é a mesma criança, só a matrícula muda."""
    ctx = _ctx((_ident(1, "MARIA EDUARDA SILVA", nasc=date(2015, 3, 1)), "1º Ano A"))
    d = m.resolver_linha(
        _linha("MARIA EDUARDA SILVA", turma="1º Ano B", nasc=date(2015, 3, 1)), ctx)
    assert (d.acao, d.aluno_id, d.motivo) == (m.REUSAR, 1, "mudanca_de_sala")


def test_mudanca_de_sala_sem_prova_vai_para_revisao():
    """Nome idêntico em outra sala, sem nascimento/RA em nenhum dos lados: pode
    ser mudança de sala OU dois homônimos. Não decide sozinho."""
    ctx = _ctx((_ident(1, "JOAO SILVA"), "1º Ano A"))
    d = m.resolver_linha(_linha("JOAO SILVA", turma="1º Ano B"), ctx)
    assert d.acao == m.REVISAR and d.aluno_id == 1


def test_homonimo_em_outra_sala_com_nascimento_distinto_e_pessoa_nova():
    ctx = _ctx((_ident(1, "JOAO SILVA", nasc=date(2015, 1, 1)), "1º Ano A"))
    d = m.resolver_linha(
        _linha("JOAO SILVA", turma="1º Ano B", nasc=date(2016, 8, 9)), ctx)
    assert d.acao == m.CRIAR


def test_homonimos_em_varias_salas_vao_para_revisao():
    ctx = _ctx((_ident(1, "JOAO SILVA"), "1º Ano A"), (_ident(2, "JOAO SILVA"), "2º Ano C"))
    d = m.resolver_linha(_linha("JOAO SILVA", turma="1º Ano B"), ctx)
    assert d.acao == m.REVISAR and set(d.candidatos) == {1, 2}


def test_aluno_sem_matricula_no_ano_e_reconhecido():
    """Quem perdeu a matrícula (ou só existe de anos anteriores) continua sendo
    identidade — rematricular não pode abrir ficha nova."""
    ctx = _ctx((_ident(7, "CARLA PILOTO TRES", nasc=date(2018, 1, 1)), None))
    d = m.resolver_linha(_linha("CARLA PILOTO TRES", nasc=date(2018, 1, 1)), ctx)
    assert (d.acao, d.aluno_id) == (m.REUSAR, 7)


# --- índices vivos ---------------------------------------------------------

def test_registrar_move_o_aluno_de_sala_e_de_nome():
    ctx = _ctx((_ident(1, "AGATHA V"), "1º Ano A"))
    ctx.registrar(_ident(1, "AGATHA VITORIA MOURA"), m.chave_turma("1º Ano B"))
    assert ctx.roster(m.chave_turma("1º Ano A")) == []
    assert [i.id for i in ctx.roster(m.chave_turma("1º Ano B"))] == [1]
    assert [i.id for i in ctx.mesmo_nome("AGATHA VITORIA MOURA")] == [1]
    assert ctx.mesmo_nome("AGATHA V") == []      # nome antigo sai do índice


def test_aviso_revisao_menciona_fundir():
    msg = m.aviso_revisao("AGATHA VITORIA", "1º Ano A", "AGATHA V, AGATHA VALENTINA")
    assert "AGATHA VITORIA" in msg and "Fundir duplicatas" in msg
