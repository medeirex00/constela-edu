"""C-02 — a métrica que GOVERNA o painel da Secretaria tem de comparar escolas.

O defeito: ``media_geral`` (0–100) é a média das notas do motor, que normaliza
cada aluno contra o **P90 da própria escola**. Ela mede a FORMA da distribuição
interna (homogeneidade), não o nível — então a escola em que todos leem pouco e
igual pontua acima da escola que lê muito com uma cauda parada. Com essa régua a
Secretaria ordenava o ranking, elegia a "melhor escola", disparava o alerta de
atenção, media equidade, avaliava metas, publicava boletim e vitrine e
correlacionava com o SAEB.

O antídoto já existia e está correto: ``pontuacao_geral`` — índice 0–1000 PER
CAPITA com escopo REDE (``_indice_da_rede``/``_pontuar_por_percapita``). Estes
testes travam que ele é quem governa, e que ``media_geral`` continua exposta
onde de fato significa desempenho (média das notas de quem usa a plataforma).
"""
import pytest

from app.models import (
    Aluno,
    Configuracao,
    Escola,
    Importacao,
    Matricula,
    NivelDificuldade,
    Rede,
    ReferenciaNormalizacao,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
)
from app.services import avaliacoes as svc_avaliacoes
from app.services import rede as svc
from app.services import relatorios as svc_relatorios
from app.services import scoring


def _rede(db, nome="Rede Comparavel"):
    r = Rede(nome=nome, status="ativa")
    db.add(r)
    db.flush()
    return r


def _escola(db, rede_id, nome, *, livros_por_aluno: list[int],
            estrelas_por_aluno: list[int] | None = None):
    """Escola com um aluno por item da lista, e as NOTAS calculadas pelo motor
    real (não fabricadas): é assim que a distribuição interna vira `media_*`."""
    esc = Escola(nome=nome, ano_letivo_ativo=2026, rede_id=rede_id, status="ativa")
    db.add(esc)
    db.flush()
    for namespace, valores in scoring.PESOS_PADRAO.items():
        db.add(Configuracao(escola_id=esc.id, namespace=namespace,
                            chave="valores", valor=valores))
    db.add(NivelDificuldade(escola_id=esc.id, nome="Nível 2", codigo="nivel_2",
                            codigos=["D"], pontos_padrao=4.0, ordem=1))
    db.add(ReferenciaNormalizacao(escola_id=esc.id, modo="auto"))
    turma = Turma(escola_id=esc.id, nome="1ºA", ano_escolar="1º Ano",
                  ano_letivo=2026, status="ativa")
    db.add(turma)
    db.flush()
    imp = Importacao(escola_id=esc.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    estrelas_por_aluno = estrelas_por_aluno or [0] * len(livros_por_aluno)
    for i, livros in enumerate(livros_por_aluno):
        a = Aluno(escola_id=esc.id, nome=f"Crianca {nome} {i}", status="ativo")
        db.add(a)
        db.flush()
        db.add(Matricula(escola_id=esc.id, aluno_id=a.id, turma_id=turma.id,
                         ano_letivo=2026))
        db.add(SnapshotElefante(
            escola_id=esc.id, aluno_id=a.id, importacao_id=imp.id,
            livros_unicos=livros, tempo_leitura_min=livros * 20,
            questoes_tentativas=livros * 3, questoes_acertos=livros * 3,
            livros_por_nivel={"D": livros}))
        if estrelas_por_aluno[i]:
            db.add(SnapshotMatific(escola_id=esc.id, aluno_id=a.id,
                                   importacao_id=imp.id,
                                   atividades=estrelas_por_aluno[i],
                                   estrelas=estrelas_por_aluno[i],
                                   pontuacao_media=50.0))
    db.commit()
    scoring.recalcular_escola(db, esc.id)
    return esc


@pytest.fixture()
def rede_desigual(db):
    """O caso da auditoria, com o motor real.

    * PEQUENA HOMOGÊNEA: 30 alunos lendo 2 livros CADA — distribuição achatada,
      todo mundo bate o P90 da própria escola ⇒ ``media_elefante`` altíssima.
    * GRANDE LEITORA: 40 alunos, 40 livros por aluno em média, com dispersão
      real ⇒ ``media_elefante`` baixa, apesar de ler ~20× mais POR ALUNO.
    """
    rede = _rede(db)
    pequena = _escola(db, rede.id, "EM Pequena Homogenea", livros_por_aluno=[2] * 30)
    dispersos = [120, 110, 100, 95, 90] + [40] * 20 + [10] * 15
    grande = _escola(db, rede.id, "EM Grande Leitora", livros_por_aluno=dispersos)
    return rede, pequena, grande


# --- O TESTE QUE IMPORTA ------------------------------------------------------

def test_escolas_de_tamanhos_diferentes_sao_comparadas_pelo_indice(rede_desigual, db):
    """A escola que lê ~20× mais POR ALUNO tem de vir em 1º e NÃO pode ser
    rotulada 'precisa de atenção' — mesmo tendo a média interna mais baixa."""
    rede, pequena, grande = rede_desigual
    dados = svc.dashboard_rede(db, rede.id)
    cartoes = {c["nome"]: c for c in dados["escolas"]}
    c_peq, c_gra = cartoes["EM Pequena Homogenea"], cartoes["EM Grande Leitora"]

    # A métrica INVÁLIDA continua exposta (é honesta como distribuição interna) —
    # e continua dizendo o contrário do mundo real. É exatamente o defeito.
    assert c_peq["media_elefante"] > c_gra["media_elefante"]
    # A métrica COMPARÁVEL diz a verdade: 20× mais livros por aluno.
    assert c_gra["livros_por_matricula"] > c_peq["livros_por_matricula"] * 10
    assert c_gra["pontuacao_geral"] > c_peq["pontuacao_geral"]

    # ORDEM e POSIÇÃO do painel seguem o índice.
    assert [c["nome"] for c in dados["escolas"]] == [
        "EM Grande Leitora", "EM Pequena Homogenea"]
    assert c_gra["posicao"] == 1 and c_peq["posicao"] == 2

    # KPI "Melhor escola" = a que mais lê por aluno, com o índice ao lado.
    melhor = dados["totais"]["melhor_escola"]
    assert melhor["nome"] == "EM Grande Leitora"
    assert melhor["pontuacao_geral"] == c_gra["pontuacao_geral"]

    # ALERTA DE ATENÇÃO: a leitora não entra; a homogênea que quase não lê, sim.
    assert "EM Grande Leitora" not in [c["nome"] for c in dados["atencao"]]
    assert c_peq["precisa_atencao"] and "índice" in c_peq["motivo_atencao"]

    # RANKING (mesmo motor, critério "geral") concorda com o painel.
    ranking = svc.ranking_escolas(db, rede.id, metrica="geral")
    assert [c["nome"] for c in ranking] == ["EM Grande Leitora", "EM Pequena Homogenea"]


def test_equidade_mede_a_distancia_no_indice_comparavel(rede_desigual, db):
    """Equidade é comparação ENTRE escolas: a distância tem de ser medida na
    régua comparável. A leitura em `media_*` fica no payload, rotulada."""
    rede, _, _ = rede_desigual
    eq = svc.dashboard_rede(db, rede.id)["equidade"]
    assert eq["escola_maior_indice"] == 1000.0        # a melhor da rede define a régua
    assert eq["gap_indice"] == pytest.approx(
        eq["escola_maior_indice"] - eq["escola_menor_indice"], abs=0.1)
    assert eq["gap_indice"] > 0
    # A equidade pela média INTERNA continua no payload (compatibilidade), mas
    # aponta para o lado errado — é justamente por isso que não governa mais.
    assert eq["gap_media"] >= 0


def test_media_geral_continua_sendo_desempenho_de_quem_usa(rede_desigual, db):
    """PRESERVADO: `media_geral` (0–100) não sumiu nem mudou de significado — é a
    média das notas de quem TEM dado da plataforma, e segue no painel."""
    rede, _, _ = rede_desigual
    dados = svc.dashboard_rede(db, rede.id)
    for c in dados["escolas"]:
        assert 0 < c["media_geral"] <= 100
        assert c["media_geral"] == pytest.approx(c["media_elefante"], abs=0.1)
        assert c["dimensoes_com_dados"] == ["leitura"]
    assert 0 < dados["totais"]["media_geral"] <= 100


def test_escola_sem_dado_nao_entra_no_alerta_por_desempenho(db):
    """Índice 0 por AUSÊNCIA de dado não vira 'desempenho baixo': o motivo tem de
    continuar sendo o de cobertura (a mesma distinção que o produto já fazia)."""
    rede = _rede(db, "Rede Sem Dado")
    esc = Escola(nome="EM Vazia", ano_letivo_ativo=2026, rede_id=rede.id, status="ativa")
    db.add(esc)
    db.flush()
    turma = Turma(escola_id=esc.id, nome="1ºA", ano_escolar="1º Ano",
                  ano_letivo=2026, status="ativa")
    db.add(turma)
    db.flush()
    aluno = Aluno(escola_id=esc.id, nome="Crianca Sem Dado", status="ativo")
    db.add(aluno)
    db.flush()
    db.add(Matricula(escola_id=esc.id, aluno_id=aluno.id, turma_id=turma.id,
                     ano_letivo=2026))
    db.commit()

    cartao = svc._kpis_da_rede(db, rede.id)[0]
    assert cartao["pontuacao_geral"] == 0.0
    assert cartao["motivo_atencao"] == "Nenhum aluno com dados das plataformas ainda."


# --- Metas --------------------------------------------------------------------

def test_meta_no_indice_conta_escolas_e_meta_na_media_nao_finge_comparar(
        rede_desigual, db):
    rede, _, _ = rede_desigual
    svc.definir_meta(db, rede.id, "pontuacao_geral", 500.0)
    svc.definir_meta(db, rede.id, "media_geral", 50.0)
    db.commit()

    metas = {m["metrica"]: m for m in svc.metas_com_progresso(db, rede.id)}
    indice = metas["pontuacao_geral"]
    assert indice["comparavel"] is True
    assert indice["escolas_total"] == 2
    assert indice["escolas_atingiram"] == 1          # só a leitora passa de 500

    media = metas["media_geral"]
    assert media["comparavel"] is False
    # Não publica uma contagem entre escolas com uma régua que não compara.
    assert media["escolas_atingiram"] is None and media["escolas_total"] is None
    assert media["atual"] > 0                        # o progresso da REDE continua


# --- Vitrine pública (sem login) ---------------------------------------------

def test_vitrine_publica_destaca_quem_le_mais_por_aluno(rede_desigual, db):
    """A vitrine é a face pública do município: ordenar por média interna
    coroaria a escola que quase não lê. O critério é o per capita, com unidade
    escrita — e continua sem qualquer PII de criança."""
    rede, _, _ = rede_desigual
    painel = svc.painel_publico_rede(db, rede.id)
    assert [e["nome"] for e in painel["top_leitura"]] == [
        "EM Grande Leitora", "EM Pequena Homogenea"]
    assert painel["unidade_leitura"] == "livros por aluno"
    assert painel["top_leitura"][0]["valor"] > painel["top_leitura"][1]["valor"] * 10
    assert "Crianca" not in str(painel)


# --- Correlação com a avaliação oficial (SAEB/IDEB) --------------------------

def test_correlacao_usa_o_indice_por_padrao(rede_desigual, db, monkeypatch):
    """O gráfico mais defensável do produto não pode cruzar o SAEB com um número
    que não compara escolas. O default passa a ser o índice."""
    rede, _, grande = rede_desigual
    chamadas = {}

    def _falso(db_, rede_id, **kwargs):
        chamadas.update(kwargs)
        return {"pontos": []}

    monkeypatch.setattr(svc_avaliacoes, "correlacao_rede", _falso)
    from fastapi.testclient import TestClient

    from app.core.security import hash_senha
    from app.main import app
    from app.models import Usuario
    db.add(Usuario(nome="Sec", email="sec.corr@rede.gov",
                   senha_hash=hash_senha("s3nh4secretaria"), cargo="coordenador",
                   rede_id=rede.id))
    db.commit()
    cliente = TestClient(app)
    r = cliente.post("/api/v1/auth/login",
                     data={"username": "sec.corr@rede.gov", "password": "s3nh4secretaria"})
    cliente.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    resp = cliente.get(f"/api/v1/redes/{rede.id}/avaliacoes/correlacao",
                       params={"avaliacao": "saeb", "indicador": "proficiencia",
                               "edicao": 2023})
    assert resp.status_code == 200, resp.text
    assert chamadas["metrica"] == "pontuacao_geral"


def test_correlacao_recusa_metrica_desconhecida_caindo_no_indice(rede_desigual, db):
    rede, _, _ = rede_desigual
    dados = svc_avaliacoes.correlacao_rede(
        db, rede.id, avaliacao_chave="saeb", indicador="proficiencia",
        edicao=2023, metrica="inventada")
    assert dados["metrica"] == "pontuacao_geral"


# --- Boletim PDF da rede ------------------------------------------------------

def test_boletim_mostra_o_indice_que_ordena_o_ranking(rede_desigual, db):
    """Se o boletim listasse só a média, a Secretaria leria '1º lugar com 25,8'
    ao lado de '2º lugar com 100' e concluiria que o relatório está quebrado."""
    rede, _, _ = rede_desigual
    dados = svc.dashboard_rede(db, rede.id)
    cabecalho, linhas = svc_relatorios.linhas_boletim_rede(dados)
    assert any("ndice" in c for c in cabecalho)
    coluna = next(i for i, c in enumerate(cabecalho) if "ndice" in c)
    # A coluna do índice é decrescente: a ordem da tabela é explicada por ela.
    valores = [linha[coluna] for linha in linhas]
    assert valores == sorted(valores, reverse=True)
    assert linhas[0][1] == "EM Grande Leitora"


# --- Panorama global (Admin Global) -------------------------------------------

def test_panorama_global_compara_redes_per_capita(db):
    """Uma REDE grande não pode liderar por volume bruto, nem por média interna:
    a comparação entre redes também é per capita, na régua da melhor rede."""
    rede_a = _rede(db, "Rede Pouco Leitora")
    _escola(db, rede_a.id, "EM A", livros_por_aluno=[2] * 30)
    rede_b = _rede(db, "Rede Leitora")
    _escola(db, rede_b.id, "EM B", livros_por_aluno=[100, 90, 80, 70, 60, 50, 40, 30, 20, 10])

    global_ = svc.dashboard_global(db)
    nomes = [r["nome"] for r in global_["redes"]]
    assert nomes == ["Rede Leitora", "Rede Pouco Leitora"]
    por_nome = {r["nome"]: r for r in global_["redes"]}
    assert por_nome["Rede Leitora"]["pontuacao_geral"] == 1000.0
    assert por_nome["Rede Leitora"]["livros_por_matricula"] > \
        por_nome["Rede Pouco Leitora"]["livros_por_matricula"]

    # As melhores escolas de TODAS as redes usam um índice de escopo GLOBAL —
    # comparar o índice DE REDE entre redes seria inválido (cada um é
    # normalizado contra a melhor escola da própria rede).
    top = global_["top_escolas"]
    assert [e["nome"] for e in top] == ["EM B", "EM A"]
    assert top[0]["pontuacao_geral_global"] == 1000.0
