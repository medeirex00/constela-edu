"""Reconciliação snapshot × leituras itemizadas (dificuldade v1) — cada livro
conta UMA vez, independentemente de as chaves coincidirem (faixa × letra) e da
ordem dos imports; e o INSUMO do motor quando o snapshot não existe."""
import pytest
from sqlalchemy import select

from app.models import Nota, SnapshotElefante
from app.services import dificuldade_livro as dl
from app.services import scoring

CASTELO = ("O Castelo Encantado", "Z")          # catálogo: 68.915 palavras (teto 1,35)
CORAGEM = ("A coragem das coisas simples", "Z")  # 3.233 palavras (piso 0,80)
GOLEIRO = ("Coleção Cenas: O Goleiro Eterno", "X")
DOLITTLE = ("A história do doutor Dolittle", "Z+")
XEQUE = ("Xeque-mate", "A+")


@pytest.fixture()
def regra():
    return dl.RegraV1()


def _v(regra, item, serie="5º Ano"):
    return regra.valor_livro(item[1], item[0], serie)


# --- fórmula pura -------------------------------------------------------------

def test_snapshot_por_faixa_e_leituras_por_letra_nao_dobram(regra):
    """{"nivel_5": 2} + [Z, X]: 2 livros no bucket, 2 já itemizados ⇒ restante 0
    (X é nivel_4 → cobre pelo excedente entre faixas). Antes: 80,29 (dobrado)."""
    total = regra.pontos_aluno({"nivel_5": 2}, "5º Ano", leituras=[CASTELO, GOLEIRO])
    assert total == pytest.approx(_v(regra, CASTELO) + _v(regra, GOLEIRO), abs=0.01)
    assert total < 45   # nunca os 80,29 da dupla contagem
    por_chave = regra.pontos_por_chave({"nivel_5": 2}, "5º Ano", leituras=[CASTELO, GOLEIRO])
    assert por_chave["nivel_5"] == 0.0


def test_snapshot_por_faixa_com_letras_da_mesma_faixa(regra):
    total = regra.pontos_aluno({"nivel_5": 2}, "5º Ano", leituras=[CASTELO, CORAGEM])
    assert total == pytest.approx(_v(regra, CASTELO) + _v(regra, CORAGEM), abs=0.01)


def test_snapshot_por_letra_e_leituras_por_letra(regra):
    total = regra.pontos_aluno({"Z": 2}, "5º Ano", leituras=[CASTELO])
    assert total == pytest.approx(_v(regra, CASTELO) + regra.valor_tipico("Z", "5º Ano"), abs=0.01)


def test_snapshot_por_faixa_sem_leituras_vale_o_tipico_da_faixa(regra):
    assert regra.pontos_aluno({"nivel_2": 3}, "3º Ano") == pytest.approx(
        3 * regra.valor_tipico("nivel_2", "3º Ano"), abs=0.01)


def test_leituras_sem_snapshot_bastam(regra):
    total = regra.pontos_aluno({}, "5º Ano", leituras=[CASTELO, CORAGEM])
    assert total == pytest.approx(_v(regra, CASTELO) + _v(regra, CORAGEM), abs=0.01)
    assert regra.pontos_aluno(None, "5º Ano", leituras=[CASTELO]) == pytest.approx(_v(regra, CASTELO), abs=0.01)


def test_letra_divergente_por_renivelamento_nao_dobra(regra):
    # mesma faixa (Y ↔ Z): o item cobre a contagem da outra letra
    total = regra.pontos_aluno({"Y": 2}, "5º Ano", leituras=[CASTELO, CORAGEM])
    assert total == pytest.approx(_v(regra, CASTELO) + _v(regra, CORAGEM), abs=0.01)
    # faixas diferentes (AA ↔ Z): o excedente cobre — o total nunca passa de 2 livros
    total2 = regra.pontos_aluno({"AA": 2}, "5º Ano", leituras=[CASTELO, CORAGEM])
    assert total2 == pytest.approx(_v(regra, CASTELO) + _v(regra, CORAGEM), abs=0.01)
    # e com contagem MAIOR que os itens, o que sobra vale o típico da chave do snapshot
    total3 = regra.pontos_aluno({"AA": 3}, "5º Ano", leituras=[CASTELO])
    assert total3 == pytest.approx(_v(regra, CASTELO) + 2 * regra.valor_tipico("AA", "5º Ano"), abs=0.01)


def test_z_mais_e_a_mais_reconciliam_com_a_faixa_vizinha(regra):
    assert regra.pontos_aluno({"nivel_5": 1}, "5º Ano", leituras=[DOLITTLE]) == pytest.approx(_v(regra, DOLITTLE), abs=0.01)
    assert regra.pontos_aluno({"nivel_1": 1}, "5º Ano", leituras=[XEQUE]) == pytest.approx(_v(regra, XEQUE), abs=0.01)
    assert regra.pontos_aluno({"Z+": 2}, "5º Ano", leituras=[DOLITTLE]) == pytest.approx(
        _v(regra, DOLITTLE) + regra.valor_tipico("Z+", "5º Ano"), abs=0.01)


def test_nivel_fora_da_regua_e_delta_negativo(regra):
    # chave suja no snapshot vale 0 e é coberta pelo excedente; o item vale o dele
    assert regra.pontos_aluno({"XYZ": 2}, "5º Ano", leituras=[("Domingo", "A")]) == pytest.approx(
        regra.valor_livro("A", "Domingo", "5º Ano"), abs=0.01)
    # delta negativo (evolução) passa como está
    assert regra.pontos_por_chave({"D": -2}, "5º Ano")["D"] == pytest.approx(-2 * regra.valor_tipico("D", "5º Ano"), abs=0.01)


def test_itens_alem_da_contagem_e_ordem_das_chaves_nao_importam(regra):
    itens = [("A loja do mestre André", "D"), ("Curiosidades 6", "D"), ("Enquanto o meu cabelo crescia", "S")]
    a = regra.pontos_aluno({"D": 1, "nivel_4": 1}, "2º Ano", leituras=itens)
    b = regra.pontos_aluno({"nivel_4": 1, "D": 1}, "2º Ano", leituras=list(reversed(itens)))
    assert a == b == pytest.approx(sum(_v(regra, i, "2º Ano") for i in itens), abs=0.01)


def test_execucao_repetida_e_deterministica(regra):
    args = ({"nivel_5": 2, "D": 3}, "1º Ano")
    itens = [CASTELO, GOLEIRO, ("Curiosidades 6", "D")]
    valores = {regra.pontos_aluno(*args, leituras=itens) for _ in range(50)}
    assert len(valores) == 1


def test_faixa_da_chave_mapeia_letras_slugs_e_sujeira():
    assert dl.faixa_da_chave("Z") == "nivel_5" and dl.faixa_da_chave("z+") == "nivel_5"
    assert dl.faixa_da_chave("A+") == "nivel_1" and dl.faixa_da_chave("aa") == "pre_leitor"
    assert dl.faixa_da_chave("nivel_2") == "nivel_2" and dl.faixa_da_chave("NIVEL_2") == "nivel_2"
    assert dl.faixa_da_chave("XYZ") == dl.FAIXA_OUTROS and dl.faixa_da_chave("") == dl.FAIXA_OUTROS


# --- insumo reconciliado (snapshot × itemização) -------------------------------

def test_insumo_so_leituras_so_snapshot_e_ambos():
    class Snap:  # objeto simples (não ORM)
        id = 7; importacao_id = 1; data_referencia = None
        livros_unicos = 5; tempo_leitura_min = 80; questoes_tentativas = 10; questoes_acertos = 8
        livros_por_nivel = {"D": 5}
    itens7 = [dl.LeituraItem("t", "D", 20)] * 7
    itens3 = [dl.LeituraItem("t", "D", 10)] * 3
    assert dl.reconciliar_insumo(1, None, []) is None
    so_leituras = dl.reconciliar_insumo(1, None, itens7)
    assert (so_leituras.livros_unicos, so_leituras.tempo_leitura_min, so_leituras.fonte) == (7, 140, "leituras")
    so_snap = dl.reconciliar_insumo(1, Snap(), None)
    assert (so_snap.livros_unicos, so_snap.tempo_leitura_min, so_snap.questoes_acertos, so_snap.fonte) == (5, 80, 8, "snapshot")
    ambos_mais = dl.reconciliar_insumo(1, Snap(), itens7)      # itemização maior que o snapshot
    assert (ambos_mais.livros_unicos, ambos_mais.tempo_leitura_min) == (7, 140)
    ambos_menos = dl.reconciliar_insumo(1, Snap(), itens3)     # snapshot maior: nunca soma
    assert (ambos_menos.livros_unicos, ambos_menos.tempo_leitura_min, ambos_menos.itemizadas) == (5, 80, 3)


# --- ponta a ponta: ordem dos imports e aluno sem snapshot ---------------------

def _base(escola_id):
    return f"/api/v1/escolas/{escola_id}"


def _leituras(cliente, escola_id, aluno, titulos, nivel="D"):
    r = cliente.post(f"{_base(escola_id)}/importacoes/confirmar", json={
        "plataforma": "elefante", "formato": "leituras", "tipo": "texto",
        "linhas": [{"nome": aluno.nome, "aluno_id": aluno.id,
                    "dados": {"livro": t, "nivel": nivel, "data": f"2026-03-0{i + 1}T09:00:00"}}
                   for i, t in enumerate(titulos)]})
    assert r.status_code == 200, r.text


def _resumo(cliente, escola_id, aluno, por_faixa, data_ref):
    r = cliente.post(f"{_base(escola_id)}/importacoes/confirmar", json={
        "plataforma": "elefante", "formato": "resumo", "tipo": "texto", "data_referencia": data_ref,
        "linhas": [{"nome": aluno.nome, "aluno_id": aluno.id, "dados": {"livros_por_nivel": por_faixa}}]})
    assert r.status_code == 200, r.text


def _pontos(db, escola_id, aluno_id):
    ctx = scoring._carregar_contexto(db, escola_id)
    return ctx[5][aluno_id]


def test_ordem_dos_imports_nao_muda_a_dificuldade(cliente, db, escola_completa):
    """leituras→resumo (snapshot por faixa atual), resumo→leituras (snapshot por
    faixa atual) e resumo antigo→leituras (snapshot por letra atual) dão o MESMO
    número: os 2 livros D itemizados, uma vez só."""
    esc = escola_completa["escola"]
    ana, joao, sofia = escola_completa["alunos"]
    titulos = ["A loja do mestre André", "Curiosidades 6"]
    regra = dl.RegraV1()
    esperado = sum(regra.valor_livro("D", t, "3º Ano") for t in titulos)
    # A) leituras primeiro, resumo por faixa depois (snapshot atual = faixa)
    _leituras(cliente, esc.id, ana, titulos)
    _resumo(cliente, esc.id, ana, {"nivel_2": 2}, "2026-12-31T00:00:00")
    # B) resumo por faixa primeiro, leituras depois (snapshot atual = faixa)
    _resumo(cliente, esc.id, joao, {"nivel_2": 2}, "2026-12-31T00:00:00")
    _leituras(cliente, esc.id, joao, titulos)
    # C) resumo antigo, leituras depois (snapshot atual = por letra)
    _resumo(cliente, esc.id, sofia, {"nivel_2": 2}, "2026-01-01T00:00:00")
    _leituras(cliente, esc.id, sofia, titulos)
    snaps = {s.aluno_id: s.livros_por_nivel for s in db.execute(
        select(SnapshotElefante).where(SnapshotElefante.id.in_(
            scoring.ids_snapshots_atuais(SnapshotElefante, esc.id)))).scalars()}
    assert snaps[ana.id] == {"nivel_2": 2} and snaps[joao.id] == {"nivel_2": 2} and snaps[sofia.id] == {"D": 2}
    for aluno in (ana, joao, sofia):
        assert _pontos(db, esc.id, aluno.id) == pytest.approx(esperado, abs=0.02), aluno.nome
    # e a nota gravada pelo recálculo do import bate com o contexto
    for aluno in (ana, joao, sofia):
        nota = db.execute(select(Nota).where(Nota.aluno_id == aluno.id)).scalars().one()
        assert nota.detalhes["dimensoes"]["leitura"]["dados"]["pontos_dificuldade"] == pytest.approx(esperado, abs=0.02)


def test_aluno_com_leituras_e_sem_snapshot_gera_nota_com_livros_e_tempo(cliente, db, escola_completa):
    """Sem snapshot, a itemização basta: livros = nº de leituras, tempo = Σ,
    dificuldade pelos livros — aferido, nota > 0, sem tocar o ORM."""
    from app.models import Leitura, Livro
    esc = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    livros = [Livro(escola_id=esc.id, titulo=t, nivel_codigo="D") for t in ("A loja do mestre André", "Curiosidades 6")]
    db.add_all(livros); db.flush()
    db.add_all([Leitura(escola_id=esc.id, aluno_id=ana.id, livro_id=l.id, tempo_leitura_min=15) for l in livros])
    db.commit()
    assert db.execute(select(SnapshotElefante).where(SnapshotElefante.aluno_id == ana.id)).first() is None
    ctx = scoring._carregar_contexto(db, esc.id)
    insumo = ctx[4][ana.id]
    assert (insumo.livros_unicos, insumo.tempo_leitura_min, insumo.fonte) == (2, 30, "leituras")
    scoring.recalcular_escola(db, esc.id)
    nota = db.execute(select(Nota).where(Nota.aluno_id == ana.id)).scalars().one()
    assert nota.aferido_leitura is True and nota.nota_elefante > 0
    dados = nota.detalhes["dimensoes"]["leitura"]["dados"]
    assert dados["livros_unicos"] == 2 and dados["tempo_leitura_min"] == 30 and dados["pontos_dificuldade"] > 0
    assert nota.detalhes["elefante"]["dificuldade"]["fonte"] == "leituras"
    assert nota.detalhes["regua_institucional"]["versao_dificuldade"] == dl.VERSAO_VIGENTE
    # nenhum snapshot foi criado/alterado pelo recálculo
    assert db.execute(select(SnapshotElefante).where(SnapshotElefante.aluno_id == ana.id)).first() is None


def test_snapshot_sem_niveis_e_marcado_incompleto_nao_zero(cliente, db, escola_completa):
    esc = escola_completa["escola"]
    ana = escola_completa["alunos"][0]
    r = cliente.post(f"{_base(esc.id)}/importacoes/confirmar", json={
        "plataforma": "elefante", "formato": "resumo", "tipo": "texto",
        "linhas": [{"nome": ana.nome, "aluno_id": ana.id,
                    "dados": {"livros_unicos": 5, "tempo_leitura_min": 60}}]})
    assert r.status_code == 200, r.text
    nota = db.execute(select(Nota).where(Nota.aluno_id == ana.id)).scalars().one()
    dif = nota.detalhes["elefante"]["dificuldade"]
    assert dif["incompleto"] is True and dif["fonte"] == "snapshot"
    dist = scoring.distribuicao_niveis(db, esc.id, {}, "3º Ano", aluno_id=ana.id, livros_unicos=5)
    assert dist["incompleto"] is True and dist["pontos_dificuldade"] == 0.0
    dist2 = scoring.distribuicao_niveis(db, esc.id, {"D": 2}, "3º Ano", livros_unicos=2)
    assert dist2["incompleto"] is False
