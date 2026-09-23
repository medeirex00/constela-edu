"""Premiações por período — a camada de PREMIAÇÃO (NÃO o scoring oficial).

Trava as decisões desta fase:
  * "Melhor Matemática" ordena pela MÉDIA AJUSTADA DE ESTRELAS POR ATIVIDADE
    feita no período (decisão do dono 2026-09-15, que substituiu a nota oficial
    do estado), NÃO por quantidade de atividades (volume puro);
  * quebra por TURNO (``Turma.turno``, vindo do banco) não mistura alunos de
    turnos diferentes;
  * o PERÍODO temporal muda os dados (snapshot depois do fim não conta);
  * sem snapshot no período → o aluno não entra no pódio de Matemática (ausência,
    não zero); desempate estável;
  * só conta o GANHO observado no período: por isso os cenários de Matemática
    gravam uma BASE antes da janela (`_cresceu`).
NADA aqui altera pesos/A3/P90/normalização (só lê o motor read-only).
"""
from datetime import datetime

from sqlalchemy import select

from app.core.security import hash_senha
from app.models import (
    Aluno, Escola, Importacao, Leitura, Livro, Matricula, SnapshotMatific, Turma, Usuario,
)
from app.services import premiacoes, provisionamento

JAN = datetime(2026, 8, 10)          # dentro da janela padrão do teste
FORA = datetime(2026, 9, 15)         # depois do fim da janela
BASE = datetime(2026, 7, 20)         # antes do início da janela (ponto de partida)


def _cenario(db):
    esc = Escola(nome="EMEF Premio", ano_letivo_ativo=2026, status="ativa")
    db.add(esc)
    db.flush()
    db.add(Usuario(escola_id=esc.id, nome="A", email="a@a.local",
                   senha_hash=hash_senha("x"), cargo="admin"))
    provisionamento.semear_config_inicial(db, esc.id)
    imp = Importacao(escola_id=esc.id, plataforma="matific", tipo="seed")
    db.add(imp)
    db.flush()
    turmas = {}
    for nome, turno in [("Manhã A", "manha"), ("Tarde A", "tarde")]:
        t = Turma(escola_id=esc.id, nome=nome, ano_escolar="3º Ano",
                  ano_letivo=2026, turno=turno, status="ativa")
        db.add(t)
        db.flush()
        turmas[turno] = t
    return esc, imp, turmas


def _aluno(db, esc, turma, nome):
    a = Aluno(escola_id=esc.id, nome=nome, status="ativo")
    db.add(a)
    db.flush()
    db.add(Matricula(escola_id=esc.id, aluno_id=a.id, turma_id=turma.id, ano_letivo=2026))
    return a


def _snap(db, esc, imp, aluno, atividades, estrelas, media, quando=JAN):
    db.add(SnapshotMatific(escola_id=esc.id, aluno_id=aluno.id, importacao_id=imp.id,
                           data_referencia=quando, atividades=atividades,
                           estrelas=estrelas, pontuacao_media=media))


def _cresceu(db, esc, imp, aluno, atividades, estrelas, media, quando=JAN):
    """Base zerada ANTES da janela + estado em ``quando``: o ganho do período é
    exatamente (atividades, estrelas). Desde 2026-09-15 só o que foi feito DENTRO
    do período conta — um snapshot solitário na janela não prova atividade."""
    _snap(db, esc, imp, aluno, 0, 0, 0.0, quando=BASE)
    _snap(db, esc, imp, aluno, atividades, estrelas, media, quando=quando)


def _podio(dados, chave):
    cat = next(c for c in dados["categorias"] if c["chave"] == chave)
    return cat["podio"]


# ---------------------------------------------------------------------------
# 1) CRITÉRIO: média ajustada de estrelas por atividade, não quantidade
# ---------------------------------------------------------------------------
def test_melhor_matematica_usa_media_ajustada_nao_so_atividades(db):
    esc, imp, turmas = _cenario(db)
    # VOLUME: muitas atividades, poucas estrelas por atividade. GANHARIA no
    # critério antigo (só atividades).
    volume = _aluno(db, esc, turmas["manha"], "Volumoso Volume")
    _cresceu(db, esc, imp, volume, atividades=100, estrelas=100, media=1.0)
    # QUALIDADE: menos atividades, muitas estrelas por atividade.
    qualidade = _aluno(db, esc, turmas["manha"], "Quali Dade")
    _cresceu(db, esc, imp, qualidade, atividades=50, estrelas=200, media=4.0)
    db.commit()

    dados = premiacoes.premiacoes(db, esc.id, datetime(2026, 8, 1), datetime(2026, 8, 31))
    categoria = next(c for c in dados["categorias"] if c["chave"] == "melhor_matematica")
    assert categoria["unidade"] == "estrelas/atividade"
    podio = categoria["podio"]
    assert [p["nome"] for p in podio[:2]] == ["Quali Dade", "Volumoso Volume"]
    # Escala 0 a 5 (estrelas por atividade), não contagem de atividades nem nota 0–100.
    assert podio[0]["valor"] <= 5 and podio[0]["valor"] > podio[1]["valor"]


# ---------------------------------------------------------------------------
# 2) TURNO: pódios por Turma.turno, sem misturar
# ---------------------------------------------------------------------------
def test_premiacao_por_turno_nao_mistura_alunos(db):
    esc, imp, turmas = _cenario(db)
    manha = _aluno(db, esc, turmas["manha"], "Ana Manha")
    _cresceu(db, esc, imp, manha, 40, 120, 3.0)
    tarde = _aluno(db, esc, turmas["tarde"], "Bruno Tarde")
    _cresceu(db, esc, imp, tarde, 30, 90, 3.0)
    db.commit()

    dados = premiacoes.premiacoes(db, esc.id, datetime(2026, 8, 1), datetime(2026, 8, 31),
                                  por_turno=True)
    turnos = {g["turno"]: g for g in dados["turnos"]}
    assert set(turnos) == {"manha", "tarde"}
    assert turnos["manha"]["turno_rotulo"] == "Manhã"
    nomes_manha = [p["nome"] for p in _categoria(turnos["manha"], "melhor_matematica")]
    nomes_tarde = [p["nome"] for p in _categoria(turnos["tarde"], "melhor_matematica")]
    assert nomes_manha == ["Ana Manha"] and nomes_tarde == ["Bruno Tarde"]
    # ordem de apresentação: manhã antes de tarde
    assert [g["turno"] for g in dados["turnos"]] == ["manha", "tarde"]


def _categoria(grupo, chave):
    return next(c for c in grupo["categorias"] if c["chave"] == chave)["podio"]


def test_um_unico_turno_devolve_so_um_grupo(db):
    esc, imp, turmas = _cenario(db)
    a = _aluno(db, esc, turmas["manha"], "So Manha")
    _snap(db, esc, imp, a, 20, 40, 2.0)
    db.commit()
    dados = premiacoes.premiacoes(db, esc.id, datetime(2026, 8, 1), datetime(2026, 8, 31),
                                  por_turno=True)
    assert [g["turno"] for g in dados["turnos"]] == ["manha"]  # front decide não mostrar aba


# ---------------------------------------------------------------------------
# 3) PERÍODO temporal muda os dados
# ---------------------------------------------------------------------------
def test_periodo_muda_os_dados_snapshot_depois_do_fim_nao_conta(db):
    esc, imp, turmas = _cenario(db)
    fut = _aluno(db, esc, turmas["manha"], "Futuro Aluno")
    _cresceu(db, esc, imp, fut, 60, 180, 3.5, quando=FORA)  # base 20/07, estado 15/09
    db.commit()
    # Janela que termina em 31/08 → o snapshot de 15/09 ainda não existe → fora.
    ago = premiacoes.premiacoes(db, esc.id, datetime(2026, 8, 1), datetime(2026, 8, 31))
    assert _podio(ago, "melhor_matematica") == []
    # Janela que alcança 30/09 → entra.
    set_ = premiacoes.premiacoes(db, esc.id, datetime(2026, 8, 1), datetime(2026, 9, 30))
    assert [p["nome"] for p in _podio(set_, "melhor_matematica")] == ["Futuro Aluno"]


# ---------------------------------------------------------------------------
# 4) AUSÊNCIA e DESEMPATE
# ---------------------------------------------------------------------------
def test_sem_snapshot_nao_entra_no_podio_de_matematica(db):
    esc, imp, turmas = _cenario(db)
    com = _aluno(db, esc, turmas["manha"], "Com Snapshot")
    _cresceu(db, esc, imp, com, 30, 90, 3.0)
    _aluno(db, esc, turmas["manha"], "Sem Snapshot")  # sem SnapshotMatific
    db.commit()
    dados = premiacoes.premiacoes(db, esc.id, datetime(2026, 8, 1), datetime(2026, 8, 31))
    nomes = [p["nome"] for p in _podio(dados, "melhor_matematica")]
    assert nomes == ["Com Snapshot"]


def test_desempate_estavel_por_nome_em_notas_iguais(db):
    esc, imp, turmas = _cenario(db)
    # Mesmos números → mesmo índice → desempate por estrelas/atividades (iguais)
    # e por fim NOME (alfabético, estável).
    for nome in ["Zulmira Z", "Amanda A"]:
        a = _aluno(db, esc, turmas["manha"], nome)
        _cresceu(db, esc, imp, a, 50, 150, 3.0)
    db.commit()
    dados = premiacoes.premiacoes(db, esc.id, datetime(2026, 8, 1), datetime(2026, 8, 31))
    nomes = [p["nome"] for p in _podio(dados, "melhor_matematica")]
    assert nomes == ["Amanda A", "Zulmira Z"]


# ---------------------------------------------------------------------------
# 4b) EVOLUÇÃO respeita o TURNO (eixo ortogonal ao período)
# ---------------------------------------------------------------------------
def test_evolucao_respeita_o_turno(db):
    """A aba "Melhor Evolução" filtra pelo MESMO turno das premiações: com
    turno=manha, um aluno da tarde NÃO aparece. Turno vem de Turma.turno."""
    from app.services import evolucao
    esc, imp, turmas = _cenario(db)
    manha = _aluno(db, esc, turmas["manha"], "Ana Manha")
    _snap(db, esc, imp, manha, 50, 100, 3.0, quando=datetime(2026, 7, 1))   # base
    _snap(db, esc, imp, manha, 90, 180, 3.0, quando=JAN)                     # +40 no período
    tarde = _aluno(db, esc, turmas["tarde"], "Bruno Tarde")
    _snap(db, esc, imp, tarde, 50, 100, 3.0, quando=datetime(2026, 7, 1))
    _snap(db, esc, imp, tarde, 80, 160, 3.0, quando=JAN)
    db.commit()

    itens = evolucao.ranking_evolucao(db, esc.id, datetime(2026, 8, 1),
                                      datetime(2026, 8, 31), turno="manha",
                                      base_no_periodo=True)
    nomes = [i.nome for i in itens]
    assert "Ana Manha" in nomes and "Bruno Tarde" not in nomes
    # "Todas" (sem turno) traz os dois.
    todos = evolucao.ranking_evolucao(db, esc.id, datetime(2026, 8, 1),
                                      datetime(2026, 8, 31), base_no_periodo=True)
    nomes_todos = {i.nome for i in todos}
    assert {"Ana Manha", "Bruno Tarde"} <= nomes_todos


# ---------------------------------------------------------------------------
# 5) LEITURA preservada (o Melhor Leitor continua por pontos de dificuldade)
# ---------------------------------------------------------------------------
def test_melhor_leitor_preservado_por_periodo(db):
    esc, imp, turmas = _cenario(db)
    leitor = _aluno(db, esc, turmas["manha"], "Leo Leitor")
    livro = Livro(escola_id=esc.id, titulo="Livro G", nivel_codigo="G")
    db.add(livro)
    db.flush()
    db.add(Leitura(escola_id=esc.id, aluno_id=leitor.id, livro_id=livro.id,
                   data=JAN, tempo_leitura_min=30))
    db.commit()
    dados = premiacoes.premiacoes(db, esc.id, datetime(2026, 8, 1), datetime(2026, 8, 31))
    assert [p["nome"] for p in _podio(dados, "melhor_leitor")] == ["Leo Leitor"]
    assert [p["nome"] for p in _podio(dados, "mais_livros")] == ["Leo Leitor"]


# ---------------------------------------------------------------------------
# 8) RANKING COMPLETO: o mesmo pódio com mais linhas (`limite`)
#
# O cartão da tela mostra o Top 5; "Ver ranking completo" pede a MESMA premiação
# com um limite maior. Estes testes travam o que não pode mudar: a ordem, as
# posições, o desempate e o valor de cada linha são os mesmos — só o tamanho da
# lista muda. Nenhuma fórmula nova, nenhuma segunda ordenação.
# ---------------------------------------------------------------------------

def _leitores(db, esc, turma, quantos):
    """`quantos` leitores com pontos estritamente decrescentes (sem empate).

    Livros DISTINTOS por leitura: releitura do mesmo livro não pontua (§35, e o
    banco barra por `uq_leitura_unica`)."""
    livros = []
    for n in range(quantos):
        livro = Livro(escola_id=esc.id, titulo=f"Livro {n:02d}", nivel_codigo="Z")
        db.add(livro)
        db.flush()
        livros.append(livro)
    alunos = []
    for i in range(quantos):
        a = _aluno(db, esc, turma, f"Leitor {i:02d}")
        # O leitor i lê os (quantos - i) primeiros livros: quem vem antes lê mais.
        for n in range(quantos - i):
            db.add(Leitura(escola_id=esc.id, aluno_id=a.id, livro_id=livros[n].id,
                           data=JAN, tempo_leitura_min=10 + n))
        alunos.append(a)
    return alunos


def _premiar(db, esc, **kw):
    return premiacoes.premiacoes(db, esc.id, datetime(2026, 8, 1), datetime(2026, 8, 31), **kw)


def test_limite_padrao_continua_sendo_o_top_5(db):
    """A) O cartão não muda: sem `limite`, cada pódio traz no máximo 5."""
    esc, imp, turmas = _cenario(db)
    _leitores(db, esc, turmas["manha"], 12)
    db.commit()

    dados = _premiar(db, esc)
    for categoria in dados["categorias"]:
        assert len(categoria["podio"]) <= 5, categoria["chave"]
    assert len(_podio(dados, "melhor_leitor")) == 5


def test_ranking_completo_estende_o_top_5_sem_mudar_ordem_nem_posicao(db):
    """C + I) As 5 primeiras linhas do ranking completo são EXATAMENTE o Top 5
    (mesma ordem, mesmo valor, mesma posição), e a partir da 6ª vêm os demais."""
    esc, imp, turmas = _cenario(db)
    _leitores(db, esc, turmas["manha"], 12)
    db.commit()

    top5 = _podio(_premiar(db, esc), "melhor_leitor")
    completo = _podio(_premiar(db, esc, limite=50), "melhor_leitor")

    assert completo[:5] == top5                      # prefixo idêntico, campo a campo
    assert len(completo) == 12                       # todos os premiáveis
    assert [p["posicao"] for p in completo] == list(range(1, 13))
    # A posição é a REAL da premiação, não uma renumeração do recorte.
    assert completo[5]["posicao"] == 6
    # Ordem decrescente pelo valor, como no Top 5.
    valores = [p["valor"] for p in completo]
    assert valores == sorted(valores, reverse=True)


def test_total_da_categoria_conta_os_premiaveis(db):
    """O `total` é quem tem valor > 0 — é ele que diz à tela se há mais ranking."""
    esc, imp, turmas = _cenario(db)
    _leitores(db, esc, turmas["manha"], 7)
    _aluno(db, esc, turmas["manha"], "Sem Leitura Alguma")   # valor 0: não é premiável
    db.commit()

    dados = _premiar(db, esc)
    categoria = next(c for c in dados["categorias"] if c["chave"] == "melhor_leitor")
    assert categoria["total"] == 7 and len(categoria["podio"]) == 5
    completo = next(c for c in _premiar(db, esc, limite=50)["categorias"]
                    if c["chave"] == "melhor_leitor")
    assert completo["total"] == 7 and len(completo["podio"]) == 7


def test_carregar_mais_nao_duplica_nem_pula_aluno(db):
    """H) Cada limite maior devolve um PREFIXO do anterior: nenhum aluno some,
    nenhum aparece duas vezes, nenhuma posição se repete."""
    esc, imp, turmas = _cenario(db)
    _leitores(db, esc, turmas["manha"], 14)
    db.commit()

    pagina1 = _podio(_premiar(db, esc, limite=5), "melhor_leitor")
    pagina2 = _podio(_premiar(db, esc, limite=10), "melhor_leitor")
    pagina3 = _podio(_premiar(db, esc, limite=15), "melhor_leitor")

    assert pagina2[:5] == pagina1 and pagina3[:10] == pagina2
    ids = [p["aluno_id"] for p in pagina3]
    assert len(ids) == len(set(ids)) == 14
    assert [p["posicao"] for p in pagina3] == list(range(1, 15))


def test_limite_maior_preserva_o_desempate_da_matematica(db):
    """G) Empate no índice: a ordem continua sendo estrelas → atividades → nome,
    com ou sem limite maior."""
    esc, imp, turmas = _cenario(db)
    # EMPATE REAL: mesmas atividades e mesmas estrelas no período → mesmo índice,
    # mesmo desempate de estrelas e de atividades. Quem decide é o nome.
    zz = _aluno(db, esc, turmas["manha"], "Zz Empatado")
    _cresceu(db, esc, imp, zz, atividades=10, estrelas=20, media=2.0)
    aa = _aluno(db, esc, turmas["manha"], "Aa Empatada")
    _cresceu(db, esc, imp, aa, atividades=10, estrelas=20, media=2.0)
    # E um terceiro com MAIS estrelas na mesma quantidade de atividades: vence os dois.
    lider = _aluno(db, esc, turmas["manha"], "Mm Lider")
    _cresceu(db, esc, imp, lider, atividades=10, estrelas=40, media=4.0)
    db.commit()

    top5 = _podio(_premiar(db, esc), "melhor_matematica")
    completo = _podio(_premiar(db, esc, limite=50), "melhor_matematica")
    assert [p["nome"] for p in top5] == [p["nome"] for p in completo]
    assert [p["nome"] for p in completo] == ["Mm Lider", "Aa Empatada", "Zz Empatado"]
    assert completo[1]["valor"] == completo[2]["valor"]   # empate de verdade
    assert completo[1]["estrelas"] == completo[2]["estrelas"]


def test_limite_maior_nao_muda_as_outras_premiacoes(db):
    """J) Pedir mais linhas de uma premiação não altera as demais: todas as
    categorias continuam com a mesma ordem e os mesmos valores."""
    esc, imp, turmas = _cenario(db)
    alunos = _leitores(db, esc, turmas["manha"], 8)
    _cresceu(db, esc, imp, alunos[0], atividades=10, estrelas=40, media=4.0)
    db.commit()

    padrao = {c["chave"]: c["podio"] for c in _premiar(db, esc)["categorias"]}
    maior = {c["chave"]: c["podio"] for c in _premiar(db, esc, limite=50)["categorias"]}
    assert set(padrao) == set(maior)
    for chave, podio in padrao.items():
        assert maior[chave][:len(podio)] == podio, chave


def test_ranking_completo_respeita_periodo_turma_e_turno(db):
    """E + F) O limite não é um filtro: período, turma e turno continuam valendo
    exatamente como no Top 5."""
    esc, imp, turmas = _cenario(db)
    manha = _leitores(db, esc, turmas["manha"], 6)
    tarde = _aluno(db, esc, turmas["tarde"], "Tarde Unica")
    livro = db.execute(select(Livro).where(Livro.escola_id == esc.id)).scalars().first()
    db.add(Leitura(escola_id=esc.id, aluno_id=tarde.id, livro_id=livro.id,
                   data=JAN, tempo_leitura_min=5))
    fora = _aluno(db, esc, turmas["manha"], "Fora Do Periodo")
    db.add(Leitura(escola_id=esc.id, aluno_id=fora.id, livro_id=livro.id,
                   data=FORA, tempo_leitura_min=99))
    db.commit()

    # PERÍODO: quem leu fora da janela não entra, nem com limite alto.
    completo = _podio(_premiar(db, esc, limite=50), "melhor_leitor")
    nomes = [p["nome"] for p in completo]
    assert "Fora Do Periodo" not in nomes and "Tarde Unica" in nomes

    # TURMA: o recorte continua sendo o da turma escolhida.
    so_manha = _podio(_premiar(db, esc, limite=50, turma_id=turmas["manha"].id), "melhor_leitor")
    assert "Tarde Unica" not in [p["nome"] for p in so_manha]
    assert len(so_manha) == len(manha)

    # TURNO: a quebra por turno também estende, sem misturar alunos.
    por_turno = _premiar(db, esc, limite=50, por_turno=True)
    grupo_tarde = next(g for g in por_turno["turnos"] if g["turno"] == "tarde")
    leitor_tarde = next(c for c in grupo_tarde["categorias"] if c["chave"] == "melhor_leitor")
    assert [p["nome"] for p in leitor_tarde["podio"]] == ["Tarde Unica"]
    grupo_manha = next(g for g in por_turno["turnos"] if g["turno"] == "manha")
    leitor_manha = next(c for c in grupo_manha["categorias"] if c["chave"] == "melhor_leitor")
    assert len(leitor_manha["podio"]) == len(manha)


def test_endpoint_aceita_limite_e_mantem_o_padrao_em_5(db, cliente, escola_completa):
    """B) O endpoint oficial serve as duas visões pela MESMA rota."""
    escola = escola_completa["escola"]
    resposta = cliente.get(f"/api/v1/escolas/{escola.id}/premiacoes?periodo=tudo")
    assert resposta.status_code == 200
    for categoria in resposta.json()["categorias"]:
        assert len(categoria["podio"]) <= 5 and "total" in categoria

    completo = cliente.get(f"/api/v1/escolas/{escola.id}/premiacoes?periodo=tudo&limite=50")
    assert completo.status_code == 200
    padrao = {c["chave"]: c["podio"] for c in resposta.json()["categorias"]}
    for categoria in completo.json()["categorias"]:
        assert categoria["podio"][:len(padrao[categoria["chave"]])] == padrao[categoria["chave"]]

    # Limite fora da faixa é recusado pela própria rota (nada de lista infinita).
    assert cliente.get(f"/api/v1/escolas/{escola.id}/premiacoes?limite=0").status_code == 422
    assert cliente.get(f"/api/v1/escolas/{escola.id}/premiacoes?limite=5000").status_code == 422
