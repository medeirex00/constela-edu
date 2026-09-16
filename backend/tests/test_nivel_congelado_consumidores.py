"""NÍVEL CONGELADO da leitura — corrigir o catálogo NÃO reescreve o passado.

CONTRATO (exigência do dono): quem pontua uma leitura usa o nível carimbado NA
LEITURA (``Leitura.nivel_codigo``, gravado pela importação que a criou) e, só
quando ele é nulo — leitura anterior a esta versão —, cai no nível ATUAL do
livro. Em SQL: ``coalesce(Leitura.nivel_codigo, Livro.nivel_codigo)``.

O que estes testes provam, todos sobre o MESMO livro renivelado no meio do
caminho (o único jeito de flagrar uma tela que ficou para trás é comparar as
cinco na mesma corrida):

  (a) a NOTA GRAVADA pelo recálculo         — ``scoring.recalcular_escola``
  (b) ``/ranking/leitura`` por período      — ``rankings.ranking_leitura``
  (c) o pódio "Melhor Leitor"               — ``premiacoes._leitura_no_periodo``
  (d) o histórico do aluno                  — ``academico`` ``/alunos/{id}/leituras``
  (e) a evolução (série do aluno e janela)  — ``evolucao.evolucao_leitura`` e
                                              ``evolucao._leituras_no_periodo``

seguem todas com o valor do nível ANTIGO; uma leitura NOVA, importada depois do
renivelamento, vale pelo nível NOVO; e a leitura ANTIGA sem carimbo (nível nulo)
acompanha o livro — o fallback, deliberado e visível.

O livro usado está FORA do catálogo oficial de propósito: sem ``wordCount``, o
ajuste intrínseco é 1,0 nos dois níveis, e a única coisa que separa os valores é
a BASE DO NÍVEL. Se a asserção quebrar, quebrou por causa do nível — não por uma
mediana do catálogo.

No fim do arquivo ficam os dois AJUSTES PEQUENOS que vieram na mesma frente,
ambos em ``/ranking/matematica``: o filtro de ano letivo que passou a valer
SEMPRE (inclusive no preset padrão "todo o histórico") e o desempate final pelo
id do aluno.
"""
from datetime import datetime

import pytest
from sqlalchemy import select

from app.models import Aluno, Leitura, Livro, Matricula, Nota
from app.services import dificuldade_livro as dl
from app.services import evolucao as svc_evolucao
from app.services import scoring

TITULO = "A Ponte de Vidro Azul (livro de teste)"
NIVEL_ANTIGO = "Z"      # o nível pelo qual a leitura foi pontuada
NIVEL_NOVO = "B"        # o nível para o qual o livro é corrigido depois
SERIE = "3º Ano"        # a turma de escola_completa
JANELA = "?periodo=personalizado&inicio=2026-07-01&fim=2026-07-31"
INI = datetime(2026, 7, 1)
FIM = datetime(2026, 7, 31, 23, 59, 59)


def _base(escola_id: int) -> str:
    return f"/api/v1/escolas/{escola_id}"


def _importar(cliente, escola_id, aluno, nivel, data_iso="2026-07-05T09:00:00"):
    """Importa UMA leitura pelo caminho real (é ele que carimba o nível)."""
    r = cliente.post(f"{_base(escola_id)}/importacoes/confirmar", json={
        "plataforma": "elefante", "formato": "leituras", "tipo": "texto",
        "linhas": [{"nome": aluno.nome, "aluno_id": aluno.id,
                    "dados": {"livro": TITULO, "nivel": nivel, "data": data_iso,
                              "tempo_livro_min": 20}}]})
    assert r.status_code == 200, r.text
    return r


def _livro_do_teste(db, escola_id) -> Livro:
    return db.execute(
        select(Livro).where(Livro.escola_id == escola_id, Livro.titulo == TITULO)
    ).scalars().one()


def _renivelar(db, escola_id, para: str) -> None:
    """A correção de catálogo: o livro passa a valer OUTRO nível de hoje em
    diante. (Quem pode fazê-la é assunto da governança do catálogo; aqui o que
    importa é o EFEITO dela sobre quem pontua.)"""
    livro = _livro_do_teste(db, escola_id)
    livro.nivel_codigo = para
    livro.nivel_fonte = para
    db.commit()


def _recalcular(db, escola_id) -> None:
    scoring.recalcular_escola(db, escola_id)
    db.commit()


def _nota_leitura(db, aluno_id) -> float:
    nota = db.execute(select(Nota).where(Nota.aluno_id == aluno_id)).scalars().one()
    db.refresh(nota)
    return nota.detalhes["dimensoes"]["leitura"]["dados"]["pontos_dificuldade"]


def _pontos_ranking(cliente, escola_id, nome) -> float:
    linhas = cliente.get(f"{_base(escola_id)}/ranking/leitura{JANELA}").json()
    return next(i["pontos"] for i in linhas if i["nome"] == nome)


def _pontos_podio(cliente, escola_id, nome) -> float:
    dados = cliente.get(f"{_base(escola_id)}/premiacoes{JANELA}").json()
    podio = {c["chave"]: c["podio"] for c in dados["categorias"]}["melhor_leitor"]
    return next(i["valor"] for i in podio if i["nome"] == nome)


def _historico(cliente, escola_id, aluno_id) -> dict:
    return cliente.get(f"{_base(escola_id)}/alunos/{aluno_id}/leituras{JANELA}").json()


def _evolucao(cliente, escola_id, aluno_id) -> list[dict]:
    r = cliente.get(f"{_base(escola_id)}/alunos/{aluno_id}/evolucao-leitura"
                    "?granularidade=mes&inicio=2026-07-01&fim=2026-07-31")
    assert r.status_code == 200, r.text
    return r.json()["series"]


@pytest.fixture()
def regra():
    return dl.RegraV1()


@pytest.fixture()
def valores(regra):
    """(valor pelo nível ANTIGO, valor pelo nível NOVO) da MESMA leitura."""
    # Fora do catálogo: sem wordCount o ajuste intrínseco é 1,0 nos dois níveis —
    # a diferença entre os valores é SÓ a base do nível.
    assert regra.metadados(TITULO, NIVEL_ANTIGO) is None
    assert regra.metadados(TITULO, NIVEL_NOVO) is None
    antigo = regra.valor_livro(NIVEL_ANTIGO, TITULO, SERIE)
    novo = regra.valor_livro(NIVEL_NOVO, TITULO, SERIE)
    assert antigo > novo > 0, "os dois níveis precisam valer números diferentes"
    return antigo, novo


@pytest.fixture()
def cenario(cliente, db, escola_completa, valores):
    """Ana leu o livro quando ele era Z; DEPOIS o livro é corrigido para B."""
    esc = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    _importar(cliente, esc.id, ana, NIVEL_ANTIGO)
    leitura = db.execute(
        select(Leitura).where(Leitura.aluno_id == ana.id)).scalars().one()
    # A importação carimbou o nível efetivo do livro NAQUELE instante.
    assert leitura.nivel_codigo == NIVEL_ANTIGO
    return {"escola": esc, "ana": ana, "alunos": escola_completa["alunos"]}


# --- (a)…(e): renivelar NÃO mexe no que já foi pontuado -----------------------

def test_as_cinco_telas_ficam_no_nivel_congelado_depois_do_renivelamento(
        cliente, db, cenario, valores):
    esc, ana = cenario["escola"], cenario["ana"]
    antigo, _novo = valores

    # ANTES: as cinco leituras do mesmo fato batem no mesmo número.
    assert _nota_leitura(db, ana.id) == pytest.approx(antigo, abs=0.02)
    assert _pontos_ranking(cliente, esc.id, ana.nome) == pytest.approx(antigo, abs=0.02)
    assert _pontos_podio(cliente, esc.id, ana.nome) == pytest.approx(antigo, abs=0.02)
    assert _historico(cliente, esc.id, ana.id)["resumo"]["pontos"] == pytest.approx(
        antigo, abs=0.02)
    assert _evolucao(cliente, esc.id, ana.id)[0]["pontos"] == pytest.approx(
        antigo, abs=0.02)

    # A CORREÇÃO DE CATÁLOGO + um recálculo completo depois dela.
    _renivelar(db, esc.id, NIVEL_NOVO)
    _recalcular(db, esc.id)
    assert _livro_do_teste(db, esc.id).nivel_codigo == NIVEL_NOVO

    # DEPOIS: nada se moveu. (a) nota gravada…
    assert _nota_leitura(db, ana.id) == pytest.approx(antigo, abs=0.02)
    # (b) ranking de leitura por período…
    assert _pontos_ranking(cliente, esc.id, ana.nome) == pytest.approx(antigo, abs=0.02)
    # (c) pódio Melhor Leitor…
    assert _pontos_podio(cliente, esc.id, ana.nome) == pytest.approx(antigo, abs=0.02)
    # (d) histórico do aluno — pontos E o nível exibido…
    historico = _historico(cliente, esc.id, ana.id)
    assert historico["resumo"]["pontos"] == pytest.approx(antigo, abs=0.02)
    assert [i["nivel"] for i in historico["itens"]] == [NIVEL_ANTIGO]
    assert historico["itens"][0]["pontos"] == pytest.approx(antigo, abs=0.02)
    # (e) evolução: a série do aluno e a janela que alimenta o ranking de evolução.
    assert _evolucao(cliente, esc.id, ana.id)[0]["pontos"] == pytest.approx(
        antigo, abs=0.02)
    _, no_periodo = svc_evolucao._leituras_no_periodo(db, esc.id, INI, FIM)
    assert no_periodo[ana.id]["por_nivel"] == {NIVEL_ANTIGO: 1}

    # E o PRESET PADRÃO do ranking de leitura ("todo o histórico"), que é outro
    # caminho de código — sem recorte de datas ele reconcilia com o agregado do
    # Elefante. Sem snapshot (o caso desta escola) o valor tem de ser o mesmo da
    # janela; é a tela que o usuário abre primeiro.
    tudo = cliente.get(f"{_base(esc.id)}/ranking/leitura?periodo=tudo").json()
    assert next(i["pontos"] for i in tudo if i["nome"] == ana.nome) == pytest.approx(
        antigo, abs=0.02)


def test_motor_le_o_nivel_congelado(db, cliente, cenario):
    """A fonte que alimenta o MOTOR (``leituras_por_aluno``) devolve o nível
    CONGELADO, não o do livro — é daí que sai a nota gravada."""
    esc, ana = cenario["escola"], cenario["ana"]
    _renivelar(db, esc.id, NIVEL_NOVO)
    itens = dl.leituras_por_aluno(db, esc.id, {ana.id})[ana.id]
    assert [(i.titulo, i.nivel) for i in itens] == [(TITULO, NIVEL_ANTIGO)]


# --- leitura NOVA depois do renivelamento: vale o nível NOVO ------------------

def test_leitura_nova_importada_depois_vale_pelo_nivel_novo(
        cliente, db, cenario, valores):
    """O congelamento não congela o CATÁLOGO: quem lê o livro depois da correção
    pontua pelo nível novo — no mesmo ranking, lado a lado com quem leu antes."""
    esc, ana = cenario["escola"], cenario["ana"]
    joao = cenario["alunos"][1]
    antigo, novo = valores

    _renivelar(db, esc.id, NIVEL_NOVO)
    _importar(cliente, esc.id, joao, NIVEL_NOVO, data_iso="2026-07-20T09:00:00")
    _recalcular(db, esc.id)

    nova = db.execute(
        select(Leitura).where(Leitura.aluno_id == joao.id)).scalars().one()
    assert nova.nivel_codigo == NIVEL_NOVO

    for valor_de in (
        lambda nome, aid: _pontos_ranking(cliente, esc.id, nome),
        lambda nome, aid: _pontos_podio(cliente, esc.id, nome),
        lambda nome, aid: _historico(cliente, esc.id, aid)["resumo"]["pontos"],
        lambda nome, aid: _evolucao(cliente, esc.id, aid)[0]["pontos"],
    ):
        assert valor_de(ana.nome, ana.id) == pytest.approx(antigo, abs=0.02)
        assert valor_de(joao.nome, joao.id) == pytest.approx(novo, abs=0.02)
    assert _nota_leitura(db, ana.id) == pytest.approx(antigo, abs=0.02)
    assert _nota_leitura(db, joao.id) == pytest.approx(novo, abs=0.02)


# --- leitura ANTIGA sem carimbo: o fallback ----------------------------------

def test_leitura_antiga_sem_nivel_congelado_segue_o_nivel_do_livro(
        cliente, db, cenario, valores):
    """Leitura anterior a esta versão (``nivel_codigo`` nulo, sem backfill): não
    há passado carimbado a preservar, então ela vale o nível ATUAL do livro. É o
    fallback determinístico — e o contraste que prova que o congelamento da Ana
    não é um acaso da consulta."""
    esc, ana = cenario["escola"], cenario["ana"]
    sofia = cenario["alunos"][2]
    antigo, novo = valores

    livro = _livro_do_teste(db, esc.id)
    db.add(Leitura(escola_id=esc.id, aluno_id=sofia.id, livro_id=livro.id,
                   data=datetime(2026, 7, 6, 9, 0), tempo_leitura_min=20,
                   nivel_codigo=None))          # leitura ANTIGA, sem carimbo
    db.commit()
    _recalcular(db, esc.id)

    # Com o livro ainda em Z, a leitura sem carimbo vale como a da Ana.
    assert _pontos_ranking(cliente, esc.id, sofia.nome) == pytest.approx(antigo, abs=0.02)
    assert _nota_leitura(db, sofia.id) == pytest.approx(antigo, abs=0.02)

    _renivelar(db, esc.id, NIVEL_NOVO)
    _recalcular(db, esc.id)

    # Sofia acompanha o livro; Ana, não.
    assert _pontos_ranking(cliente, esc.id, sofia.nome) == pytest.approx(novo, abs=0.02)
    assert _pontos_podio(cliente, esc.id, sofia.nome) == pytest.approx(novo, abs=0.02)
    assert _nota_leitura(db, sofia.id) == pytest.approx(novo, abs=0.02)
    assert _historico(cliente, esc.id, sofia.id)["itens"][0]["nivel"] == NIVEL_NOVO
    assert _pontos_ranking(cliente, esc.id, ana.nome) == pytest.approx(antigo, abs=0.02)
    assert _nota_leitura(db, ana.id) == pytest.approx(antigo, abs=0.02)
    _, no_periodo = svc_evolucao._leituras_no_periodo(db, esc.id, INI, FIM)
    assert no_periodo[sofia.id]["por_nivel"] == {NIVEL_NOVO: 1}
    assert no_periodo[ana.id]["por_nivel"] == {NIVEL_ANTIGO: 1}


# =============================================================================
# AJUSTES PEQUENOS em /ranking/matematica (mesma frente)
# =============================================================================

def _importar_matific(cliente, escola_id, aluno, inicio, fim, ativ, estrelas,
                      media=4.0):
    r = cliente.post(f"{_base(escola_id)}/importacoes/confirmar", json={
        "plataforma": "matific", "formato": "resumo", "tipo": "pdf",
        "periodo_inicio": inicio, "periodo_fim": fim,
        "linhas": [{"nome": aluno.nome, "aluno_id": aluno.id,
                    "dados": {"atividades": ativ, "pontuacao_media": media,
                              "estrelas": estrelas}}]})
    assert r.status_code == 200, r.text


def _ranking_matematica(cliente, escola_id, query="?periodo=tudo") -> list[dict]:
    r = cliente.get(f"{_base(escola_id)}/ranking/matematica{query}")
    assert r.status_code == 200, r.text
    return r.json()


def test_preset_padrao_da_matematica_ignora_snapshot_de_outro_ano_letivo(
        cliente, db, escola_completa):
    """AJUSTE 1 — o filtro de ano letivo vale SEMPRE, inclusive no preset padrão.

    Contadores do Matific são DO ANO. Antes, com ``periodo=tudo`` (sem início),
    o ano letivo não era passado para ``_janela``: o acumulado de dez/2025 de uma
    criança virava o "estado atual" de 2026 e ela aparecia no ranking do ano
    corrente com números do ano passado. A premiação "todo o histórico" nunca
    teve esse defeito (``matific_destaque.ganho_no_periodo`` sempre exigiu o
    ano) — a divergência entre as duas telas ERA o bug. Agora as duas concordam.
    """
    esc = escola_completa["escola"]
    assert esc.ano_letivo_ativo == 2026
    ana = escola_completa["alunos"][0]        # só dado de 2025
    joao = escola_completa["alunos"][1]       # dado de 2026

    _importar_matific(cliente, esc.id, ana, "2025-11-01", "2025-12-01", 80, 300)
    _importar_matific(cliente, esc.id, joao, "2026-03-01", "2026-04-01", 40, 150)

    nomes = [i["nome"] for i in _ranking_matematica(cliente, esc.id)]
    assert nomes == [joao.nome], (
        "quem só tem dado de OUTRO ano letivo não pode ocupar o ranking do ano "
        "corrente (é ausência no ano, não zero)")

    # A MESMA pergunta na tela irmã ("todo o histórico" das premiações) responde
    # igual — é essa concordância que o ajuste comprou.
    dados = cliente.get(f"{_base(esc.id)}/premiacoes?periodo=tudo").json()
    podio = {c["chave"]: c["podio"] for c in dados["categorias"]}["melhor_matematica"]
    assert [i["nome"] for i in podio] == [joao.nome]


def test_preset_padrao_da_matematica_bate_com_o_todo_o_historico_das_premiacoes(
        cliente, db, escola_completa):
    """AJUSTE 1, o outro lado: para quem TEM dado do ano, as DUAS telas dão o
    MESMO número — que é o ponto do ajuste (elas divergiam).

    O que cada uma faz com ``periodo=tudo``: toma o ÚLTIMO snapshot DENTRO do ano
    letivo, a partir do zero (``base = None``, porque não há período a recortar).
    O teste compara as duas em vez de fixar um número mágico: é a CONCORDÂNCIA
    que o ajuste comprou, e ela continua valendo se a régua do acumulado mudar.

    CAVEAT DELIBERADO (fica registrado porque surpreende): o filtro por ano
    descarta os SNAPSHOTS de 2025, mas não limpa o que está DENTRO de um snapshot
    de 2026 — a importação por período acumula sobre o último snapshot anterior
    ao intervalo, mesmo que ele seja de dezembro do ano passado
    (``importacoes._importar_matific_periodo``). Por isso o acumulado de 2025
    (300) segue embutido no valor de 2026. Isso é da IMPORTAÇÃO, não destas
    telas, e as duas carregam o mesmo embutido — que é exatamente por que este
    teste afirma a igualdade entre elas, e não um total "limpo" do ano.
    """
    esc = escola_completa["escola"]
    ana = escola_completa["alunos"][0]

    _importar_matific(cliente, esc.id, ana, "2025-11-01", "2025-12-01", 80, 300)
    _importar_matific(cliente, esc.id, ana, "2026-03-01", "2026-04-01", 50, 200)
    _importar_matific(cliente, esc.id, ana, "2026-04-01", "2026-05-01", 30, 90)

    linha = next(i for i in _ranking_matematica(cliente, esc.id)
                 if i["nome"] == ana.nome)
    dados = cliente.get(f"{_base(esc.id)}/premiacoes?periodo=tudo").json()
    podio = {c["chave"]: c["podio"] for c in dados["categorias"]}["melhor_matematica"]
    item = next(i for i in podio if i["nome"] == ana.nome)
    assert (linha["estrelas"], linha["atividades"]) == (item["estrelas"],
                                                        item["atividades"])
    # Última coleta DE 2026 (a de maio), nunca a de dez/2025 — que tem menos.
    assert linha["estrelas"] > 300 and linha["atividades"] > 80


def test_matematica_empatada_desempata_pelo_id_do_aluno(
        cliente, db, escola_completa):
    """AJUSTE 2 — a chave de ordenação termina no id do aluno.

    Dois HOMÔNIMOS com exatamente os mesmos números empatavam até o
    ``nome.casefold()`` e, dali para a frente, a ordem era a que o banco
    devolvesse: duas requisições idênticas podiam trocar as posições. Com o id
    no fim da chave, a ordem é total e a mesma sempre.
    """
    esc = escola_completa["escola"]
    turma = escola_completa["turma"]
    homonimos = []
    for _ in range(2):
        aluno = Aluno(escola_id=esc.id, nome="Maria Clara Nogueira")
        db.add(aluno)
        db.flush()
        homonimos.append(aluno)
    # MATRÍCULAS EM ORDEM INVERSA à dos alunos, de propósito: a consulta do
    # ranking varre as matrículas, então a ordem CRUA do banco sai ao contrário
    # da ordem dos ids. Sem isso o teste passaria mesmo sem a correção (o banco
    # já devolveria por id) e não provaria nada.
    for aluno in reversed(homonimos):
        db.add(Matricula(escola_id=esc.id, aluno_id=aluno.id,
                         turma_id=turma.id, ano_letivo=2026))
        db.flush()
    db.commit()
    for aluno in homonimos:
        _importar_matific(cliente, esc.id, aluno, "2026-03-01", "2026-04-01", 40, 150)

    ids_esperados = sorted(a.id for a in homonimos)
    corridas = []
    for _ in range(5):
        linhas = _ranking_matematica(cliente, esc.id)
        empatados = [i for i in linhas if i["nome"] == "Maria Clara Nogueira"]
        assert len(empatados) == 2
        corridas.append([i["aluno_id"] for i in empatados])
    assert all(corrida == ids_esperados for corrida in corridas), (
        "empate total: a ordem tem de ser a do id do aluno, igual em toda "
        f"requisição — saiu {corridas}")

    # O MESMO desempate no endpoint-irmão /ranking/leitura (o defeito era o
    # mesmo, no mesmo arquivo): duas leituras idênticas, importadas em ordem
    # inversa à dos ids, também empatam até o nome.
    for aluno in reversed(homonimos):
        _importar(cliente, esc.id, aluno, NIVEL_ANTIGO)
    linhas = cliente.get(f"{_base(esc.id)}/ranking/leitura{JANELA}").json()
    empatados = [i for i in linhas if i["nome"] == "Maria Clara Nogueira"]
    assert [i["aluno_id"] for i in empatados] == ids_esperados
    assert len({i["pontos"] for i in empatados}) == 1, "o empate tem de ser real"
