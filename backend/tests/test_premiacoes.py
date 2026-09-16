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
