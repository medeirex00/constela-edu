"""CRITÉRIO 8 — a visão da SECRETARIA, separada e provada.

O critério tem duas metades, e elas se provam de formas diferentes:

(A) ORDENAÇÃO OFICIAL — nenhuma escola muda de posição por causa de
    ``nota_geral``, de ``Nota.posicao`` ou de qualquer ranking INDIVIDUAL.
    Prova por SABOTAGEM: as colunas legadas (e as posições por dimensão) viram
    lixo no banco e a ordem de ``rede.dashboard_rede`` e de
    ``rede.ranking_escolas`` — em TODAS as métricas — tem de sair idêntica.

(B) MÉTRICAS SECUNDÁRIAS (``media_elefante`` / ``media_matific``, 0–100):
      i.   não definem a posição da escola;
      ii.  não alimentam, nem indiretamente, o índice que ordena;
      iii. não há média individual re-agregada de forma incorreta;
      iv.  a mudança observada nelas vem EXCLUSIVAMENTE da correção da régua —
           quantificada rodando o mesmo banco com e sem a correção.

Por que (A) e (B) são separadas: a ordem oficial da Secretaria sai do ÍNDICE PER
CAPITA (``pontuacao_*``), que se calcula a partir dos TOTAIS BRUTOS dos
snapshots (livros ÷ matrículas, estrelas ÷ matrículas) — sem passar por nota de
aluno nenhuma. As médias 0–100 são normalizadas DENTRO de cada escola (P90 da
própria escola) e por isso não comparam escolas; elas informam, não ordenam.
"""
import pytest

from app.core.security import hash_senha
from app.models import (
    Aluno,
    Configuracao,
    Escola,
    Importacao,
    Matricula,
    NivelDificuldade,
    Nota,
    Rede,
    ReferenciaNormalizacao,
    SnapshotElefante,
    SnapshotMatific,
    Turma,
    Usuario,
)
from app.services import rede as svc_rede
from app.services import scoring
from tests.regua_legada import referencias_legado_com_vazamento

# ---------------------------------------------------------------------------
# Montagem de uma rede heterogênea (o pior caso para a Secretaria)
# ---------------------------------------------------------------------------

def _escola(db, rede, nome):
    esc = Escola(nome=nome, ano_letivo_ativo=2026, status="ativa", rede_id=rede.id)
    db.add(esc)
    db.flush()
    for ns, val in scoring.PESOS_PADRAO.items():
        db.add(Configuracao(escola_id=esc.id, namespace=ns, chave="valores",
                            valor=val))
    db.add(NivelDificuldade(escola_id=esc.id, nome="N2", codigo="n2",
                            codigos=["D"], pontos_padrao=4.0, ordem=1))
    db.add(ReferenciaNormalizacao(escola_id=esc.id, modo="auto"))
    turma = Turma(escola_id=esc.id, nome="5ºA", ano_escolar="5º Ano",
                  ano_letivo=2026, status="ativa")
    db.add(turma)
    db.add(Usuario(escola_id=esc.id, nome="G", email=f"g{esc.id}@sec.local",
                   senha_hash=hash_senha("s3nh4secret4ri4"), cargo="coordenador"))
    db.flush()
    imp = Importacao(escola_id=esc.id, plataforma="seed", tipo="seed")
    db.add(imp)
    db.flush()
    return esc, turma, imp


def _ele(n):
    return {"livros_unicos": n, "tempo_leitura_min": n * 11,
            "questoes_tentativas": n * 5, "questoes_acertos": n * 3,
            "livros_por_nivel": {"D": n}}


def _mat(n):
    return {"atividades": n * 7, "pontuacao_media": min(5.0, n * 0.3),
            "estrelas": n * 13}


def _aluno(db, esc, turma, imp, nome, *, ele=None, mat=None):
    a = Aluno(escola_id=esc.id, nome=nome, status="ativo")
    db.add(a)
    db.flush()
    db.add(Matricula(escola_id=esc.id, aluno_id=a.id, turma_id=turma.id,
                     ano_letivo=2026))
    if ele is not None:
        db.add(SnapshotElefante(escola_id=esc.id, aluno_id=a.id,
                                importacao_id=imp.id, **_ele(ele)))
    if mat is not None:
        db.add(SnapshotMatific(escola_id=esc.id, aluno_id=a.id,
                               importacao_id=imp.id, **_mat(mat)))
    return a


@pytest.fixture()
def municipio(db):
    """Rede com 5 escolas de formas deliberadamente diferentes — tamanhos,
    plataformas e cobertura — para que a ordem oficial tenha o que ordenar.

    * MISTA GRANDE — 12 alunos, as duas plataformas (coorte acima do gate de 8);
    * SÓ LEITURA   — 9 alunos, só Elefante;
    * SÓ MATEMÁTICA— 7 alunos, só Matific;
    * DESBALANCEADA— 11 no Matific × 3 no Elefante (a forma exata do bug);
    * SEM DADOS    — 6 alunos, nenhum snapshot (fica fora do ranking).
    """
    rede = Rede(nome="Rede Piloto", status="ativa")
    db.add(rede)
    db.flush()
    escolas = {}

    esc, turma, imp = _escola(db, rede, "EM MISTA GRANDE")
    for i in range(12):
        _aluno(db, esc, turma, imp, f"MG{i}", ele=2 + i * 3, mat=1 + i * 2)
    escolas["mista"] = esc

    esc, turma, imp = _escola(db, rede, "EM SO LEITURA")
    for i in range(9):
        _aluno(db, esc, turma, imp, f"SL{i}", ele=5 + i * 4)
    escolas["so_leitura"] = esc

    esc, turma, imp = _escola(db, rede, "EM SO MATEMATICA")
    for i in range(7):
        _aluno(db, esc, turma, imp, f"SM{i}", mat=3 + i * 5)
    escolas["so_matematica"] = esc

    esc, turma, imp = _escola(db, rede, "EM DESBALANCEADA")
    for i in range(3):
        _aluno(db, esc, turma, imp, f"DL{i}", ele=3 + i * 9)
    for i in range(11):
        _aluno(db, esc, turma, imp, f"DM{i}", mat=1 + i * 2)
    escolas["desbalanceada"] = esc

    esc, turma, imp = _escola(db, rede, "EM SEM DADOS")
    for i in range(6):
        _aluno(db, esc, turma, imp, f"SD{i}")
    escolas["sem_dados"] = esc

    db.commit()
    for esc in escolas.values():
        scoring.recalcular_escola(db, esc.id)
    return rede, escolas


# ---------------------------------------------------------------------------
# A "visão da Secretaria" inteira, num objeto comparável
# ---------------------------------------------------------------------------

def _visao(db, rede_id):
    """Tudo que a Secretaria vê e que tem ORDEM: o painel e as 13 métricas de
    ranking. Devolve ordens e posições — nunca as médias, que são o objeto da
    parte (B)."""
    painel = svc_rede.dashboard_rede(db, rede_id)
    return {
        "painel_ordem": [c["escola_id"] for c in painel["escolas"]],
        "painel_posicoes": {c["escola_id"]: c["posicao"] for c in painel["escolas"]},
        "atencao": [c["escola_id"] for c in painel["atencao"]],
        "melhor": (painel["totais"]["melhor_escola"] or {}).get("nome"),
        "rankings": {
            metrica: [(c["escola_id"], c["posicao"])
                      for c in svc_rede.ranking_escolas(db, rede_id, metrica=metrica)]
            for metrica in svc_rede.METRICAS_RANKING
        },
        # A vitrine pública da rede (sem login) entra no mesmo conjunto: é onde
        # uma ordem errada vira anúncio em praça pública.
        "publico": svc_rede.painel_publico_rede(db, rede_id),
    }


def _indices(db, rede_id):
    """Os índices per capita por escola — o número que ORDENA."""
    return {c["escola_id"]: (c["pontuacao_geral"], c["pontuacao_leitura"],
                             c["pontuacao_matematica"])
            for c in svc_rede.dashboard_rede(db, rede_id)["escolas"]}


def _medias(db, rede_id):
    """As médias 0–100 por escola — as métricas SECUNDÁRIAS."""
    return {c["escola_id"]: (c["media_geral"], c["media_elefante"],
                             c["media_matific"])
            for c in svc_rede.dashboard_rede(db, rede_id)["escolas"]}


# ===========================================================================
# (A) ORDENAÇÃO OFICIAL — sabotagem das colunas legadas e individuais
# ===========================================================================

SABOTAGENS = {
    # A nota legada vira lixo, invertida e fora de escala.
    "nota_geral embaralhada": lambda i, n: setattr(n, "nota_geral", 999.0 - i),
    # E também zerada — o outro extremo (um recálculo que nunca rodou).
    "nota_geral zerada": lambda i, n: setattr(n, "nota_geral", 0.0),
    # A ordem única legada.
    "Nota.posicao embaralhada": lambda i, n: setattr(n, "posicao", 10_000 - i),
    # O ranking INDIVIDUAL por dimensão (a ordenação oficial DO ALUNO): a
    # Secretaria não pode depender nem dele — ela vê escola, não criança.
    "posições por dimensão embaralhadas": lambda i, n: (
        setattr(n, "posicao_leitura", 500 - i),
        setattr(n, "posicao_matematica", 700 - i)),
    # Tudo junto.
    "tudo embaralhado": lambda i, n: (
        setattr(n, "nota_geral", 999.0 - i), setattr(n, "posicao", 10_000 - i),
        setattr(n, "posicao_leitura", 500 - i),
        setattr(n, "posicao_matematica", 700 - i)),
}


@pytest.mark.parametrize("nome_sabotagem", list(SABOTAGENS))
def test_ordem_das_escolas_sobrevive_a_sabotagem_das_colunas_legadas(
        db, municipio, nome_sabotagem):
    """(A) Se qualquer caminho da Secretaria ainda consumisse ``nota_geral``,
    ``Nota.posicao`` ou o ranking individual, a ordem mudaria aqui."""
    rede, _ = municipio
    antes = _visao(db, rede.id)
    assert len(antes["painel_ordem"]) == 5, "as 5 escolas têm de aparecer"
    assert len({p for _e, p in antes["rankings"]["indice_geral"]}) == \
        len(antes["rankings"]["indice_geral"]), "posições do ranking têm de ser únicas"

    sabotar = SABOTAGENS[nome_sabotagem]
    for i, n in enumerate(db.query(Nota).all()):
        sabotar(i, n)
    db.commit()

    depois = _visao(db, rede.id)
    assert depois["painel_ordem"] == antes["painel_ordem"], (
        f"[{nome_sabotagem}] a ORDEM do painel da Secretaria mudou")
    assert depois["painel_posicoes"] == antes["painel_posicoes"], (
        f"[{nome_sabotagem}] as POSIÇÕES do painel mudaram")
    assert depois["melhor"] == antes["melhor"], (
        f"[{nome_sabotagem}] a 'melhor escola' do KPI mudou")
    assert depois["atencao"] == antes["atencao"], (
        f"[{nome_sabotagem}] a lista de escolas em ATENÇÃO mudou")
    for metrica in svc_rede.METRICAS_RANKING:
        assert depois["rankings"][metrica] == antes["rankings"][metrica], (
            f"[{nome_sabotagem}] o ranking de escolas por '{metrica}' mudou de "
            f"ordem — logo ainda depende da nota antiga ou do ranking individual")


def test_o_indice_que_ordena_nao_le_nenhuma_coluna_de_nota_do_aluno(db, municipio):
    """(A, por CÓDIGO) O índice per capita é função só de TOTAIS BRUTOS.

    ``_pontuar_por_percapita`` recebe cartões e usa exclusivamente
    ``livros_por_matricula``, ``estrelas_por_matricula`` e as contagens de
    ativos. Dois cartões com médias 0–100 opostas e o MESMO per capita têm de
    receber a MESMA pontuação — é a prova direta de que a nota do aluno (geral
    ou por dimensão) não entra na conta."""
    cartoes = [
        {"nome": "A", "livros_por_matricula": 10.0, "estrelas_por_matricula": 20.0,
         "ativos_elefante": 5, "ativos_matific": 5, "modulos": ["leitura", "matematica"],
         "media_elefante": 100.0, "media_matific": 100.0, "media_geral": 100.0},
        {"nome": "B", "livros_por_matricula": 10.0, "estrelas_por_matricula": 20.0,
         "ativos_elefante": 5, "ativos_matific": 5, "modulos": ["leitura", "matematica"],
         "media_elefante": 0.0, "media_matific": 0.0, "media_geral": 0.0},
    ]
    svc_rede._pontuar_por_percapita(cartoes)
    assert cartoes[0]["pontuacao_geral"] == cartoes[1]["pontuacao_geral"]
    assert cartoes[0]["pontuacao_leitura"] == cartoes[1]["pontuacao_leitura"]
    assert cartoes[0]["pontuacao_matematica"] == cartoes[1]["pontuacao_matematica"]


def test_dashboard_global_do_admin_tambem_sobrevive_a_sabotagem(db, municipio):
    """A camada ACIMA da Secretaria (Admin Global consolidando todas as redes)
    tem a mesma exigência — e pontua as escolas de novo, com escopo global."""
    def _ordens():
        g = svc_rede.dashboard_global(db)
        return ([r["rede_id"] for r in g["redes"]],
                [e["escola_id"] for e in g["top_escolas"]])

    antes = _ordens()
    assert antes[1], "o top de escolas não pode vir vazio"
    for i, n in enumerate(db.query(Nota).all()):
        n.nota_geral = 999.0 - i
        n.posicao = 10_000 - i
        n.posicao_leitura = 500 - i
        n.posicao_matematica = 700 - i
    db.commit()
    assert _ordens() == antes


# ===========================================================================
# (B) MÉTRICAS SECUNDÁRIAS
# ===========================================================================

# As métricas do Ranking da Rede que NÃO podem depender das médias 0–100. São
# todas menos as duas opções explicitamente POR PLATAFORMA, que existem para a
# Secretaria perguntar "como vai quem usa o Elefante nesta escola?" — critério
# escolhido a dedo na tela, nunca o padrão.
METRICAS_OFICIAIS = [m for m in svc_rede.METRICAS_RANKING
                     if m not in ("elefante", "matific")]


def test_i_perturbar_as_medias_0a100_nao_move_nenhuma_escola(db, municipio):
    """(B.i) As médias 0–100 são sabotadas DIRETAMENTE nas colunas de `notas`
    (sem tocar em snapshot nenhum). A posição de todas as escolas — no painel e
    em todas as métricas oficiais — tem de ficar idêntica."""
    rede, _ = municipio
    antes = _visao(db, rede.id)
    medias_antes = _medias(db, rede.id)

    for i, n in enumerate(db.query(Nota).all()):
        # Inverte a escala: quem tinha nota alta passa a ter baixa.
        n.nota_elefante = round(100.0 - (n.nota_elefante or 0.0), 2)
        n.nota_matific = round(100.0 - (n.nota_matific or 0.0), 2)
    db.commit()

    medias_depois = _medias(db, rede.id)
    # As médias da rede saem agora das colunas INSTITUCIONAIS (imunes à config e
    # às notas LOCAIS de cada escola). Sabotar `nota_elefante`/`nota_matific`
    # (colunas locais) não move NENHUMA métrica da rede — invariante ainda mais
    # forte que o antigo "a ordem não segue as médias": nem a média muda.
    assert medias_depois == medias_antes, (
        "a sabotagem das notas LOCAIS mexeu nas médias da rede — logo a rede "
        "ainda lê `Nota.nota_elefante`/`nota_matific` em vez das institucionais")

    depois = _visao(db, rede.id)
    assert depois["painel_ordem"] == antes["painel_ordem"], (
        "a ORDEM do painel da Secretaria seguiu as médias 0–100")
    assert depois["painel_posicoes"] == antes["painel_posicoes"]
    assert depois["publico"] == antes["publico"], (
        "a VITRINE PÚBLICA da rede seguiu as médias 0–100")
    for metrica in METRICAS_OFICIAIS:
        assert depois["rankings"][metrica] == antes["rankings"][metrica], (
            f"o ranking oficial por '{metrica}' seguiu as médias 0–100")


def test_i_as_duas_metricas_por_plataforma_sao_opt_in_e_estao_documentadas(db):
    """(B.i, contraprova honesta) ``metrica='elefante'`` e ``metrica='matific'``
    ORDENAM pelas médias 0–100 — de propósito, como opção explícita da SEDUC.
    Este teste fixa que são exatamente essas duas, para que nenhuma métrica
    nova entre no conjunto oficial apontando para uma média interna."""
    por_media = {m for m, chave in svc_rede.METRICAS_RANKING.items()
                 if chave in ("media_elefante", "media_matific")}
    assert por_media == {"elefante", "matific"}, (
        "uma métrica NOVA do Ranking da Rede passou a ordenar por média 0–100, "
        "que é régua INTERNA de cada escola e não compara escolas entre si")


def test_ii_o_indice_nao_muda_quando_as_medias_0a100_mudam(db, municipio):
    """(B.ii) Alimentação INDIRETA: se as médias entrassem no índice por
    qualquer caminho, ``pontuacao_*`` mudaria junto com elas."""
    rede, _ = municipio
    indices_antes = _indices(db, rede.id)
    for n in db.query(Nota).all():
        n.nota_elefante = round(100.0 - (n.nota_elefante or 0.0), 2)
        n.nota_matific = round(100.0 - (n.nota_matific or 0.0), 2)
    db.commit()
    assert _indices(db, rede.id) == indices_antes, (
        "o índice per capita mudou junto com as médias 0–100 — logo elas "
        "alimentam o ranking de escolas por algum caminho indireto")


def test_iii_media_da_escola_exclui_ausencia_e_inclui_zero_legitimo(db, municipio):
    """(B.iii) A re-agregação da nota INDIVIDUAL, conferida na mão.

    ``_medias_por_plataforma`` corta por EXISTÊNCIA de snapshot: quem não usa a
    plataforma fica fora (ausência ≠ zero) e quem usa e produziu zero entra
    (zero legítimo). Sem isso a média mediria desempenho × cobertura."""
    rede, escolas = municipio
    esc = escolas["desbalanceada"]
    cartao = next(c for c in svc_rede.dashboard_rede(db, rede.id)["escolas"]
                  if c["escola_id"] == esc.id)

    notas = {n.aluno_id: n for n in db.query(Nota)
             .filter(Nota.escola_id == esc.id).all()}
    com_ele = [n.nota_elefante for n in notas.values() if n.aferido_leitura]
    com_mat = [n.nota_matific for n in notas.values() if n.aferido_matematica]

    assert len(com_ele) == 3 and len(com_mat) == 11
    assert cartao["alunos_com_nota_elefante"] == 3
    assert cartao["alunos_com_nota_matific"] == 11
    assert cartao["media_elefante"] == round(sum(com_ele) / len(com_ele), 1)
    assert cartao["media_matific"] == round(sum(com_mat) / len(com_mat), 1)
    # E a "geral" é a média das DIMENSÕES disponíveis, não a média das notas
    # gerais dos alunos: a diferença entre as duas é o teto de 50 do C-01.
    assert cartao["media_geral"] == round(
        (cartao["media_elefante"] + cartao["media_matific"]) / 2, 1)
    media_das_notas_gerais = round(
        sum(n.nota_geral for n in notas.values()) / len(notas), 1)
    assert cartao["media_geral"] != media_das_notas_gerais, (
        "a média da escola coincidiu com a média de `nota_geral` — o cenário "
        "deixou de ser misto e o teste não distingue mais as duas contas")


def test_iii_escola_de_uma_plataforma_so_nao_e_dividida_por_dois(db, municipio):
    """(B.iii) A outra metade da re-agregação: a escola que usa uma plataforma
    só não pode receber um zero da outra dentro de ``media_geral``."""
    rede, escolas = municipio
    cartoes = {c["escola_id"]: c
               for c in svc_rede.dashboard_rede(db, rede.id)["escolas"]}
    so_leitura = cartoes[escolas["so_leitura"].id]
    assert so_leitura["media_matific"] == 0.0
    assert so_leitura["alunos_com_nota_matific"] == 0
    assert so_leitura["dimensoes_com_dados"] == ["leitura"]
    assert so_leitura["media_geral"] == so_leitura["media_elefante"], (
        "a escola de uma plataforma só levou metade da nota — o zero da "
        "dimensão AUSENTE entrou na média")
    # A escola sem dado nenhum não inventa desempenho e sai do ranking.
    sem_dados = cartoes[escolas["sem_dados"].id]
    assert sem_dados["media_geral"] == 0.0 and sem_dados["alunos_com_dados"] == 0
    ids_ranking = {c["escola_id"]
                   for c in svc_rede.ranking_escolas(db, rede.id, metrica="geral")}
    assert escolas["sem_dados"].id not in ids_ranking


def test_iii_media_ponderada_da_rede_pesa_pelo_denominador_de_cada_dimensao(
        db, municipio):
    """(B.iii) A re-agregação de um nível acima: ``totais.media_elefante`` é a
    média da REDE. O peso de cada escola tem de ser o número de alunos AFERIDOS
    NAQUELA DIMENSÃO — não o número de alunos com dado de qualquer plataforma.

    Com o peso errado, a escola que não usa o Elefante entra na média de LEITURA
    da rede com ``media_elefante = 0`` e puxa o número para baixo: é o mesmo
    "ausência vira zero" que a Arquitetura 2 elimina no aluno, reaparecendo na
    rede."""
    rede, _ = municipio
    painel = svc_rede.dashboard_rede(db, rede.id)
    cartoes = painel["escolas"]

    def _ponderada(chave, peso):
        total = sum(c[peso] for c in cartoes)
        if not total:
            return 0.0
        return round(sum(c[chave] * c[peso] for c in cartoes) / total, 1)

    esperado_leitura = _ponderada("media_elefante", "alunos_com_nota_elefante")
    esperado_matematica = _ponderada("media_matific", "alunos_com_nota_matific")
    assert painel["totais"]["media_elefante"] == esperado_leitura, (
        "a média de LEITURA da rede não é a média ponderada pelos alunos "
        "aferidos em leitura — escolas sem Elefante estão entrando com zero")
    assert painel["totais"]["media_matific"] == esperado_matematica, (
        "a média de MATEMÁTICA da rede não é a média ponderada pelos alunos "
        "aferidos em matemática — escolas sem Matific estão entrando com zero")
    # E o número tem de ser DIFERENTE do que sairia com o peso genérico: se
    # coincidirem, esta rede não distingue os dois cálculos e o teste não prova
    # nada (todas as escolas usariam as duas plataformas).
    generico = _ponderada("media_elefante", "alunos_com_dados")
    assert esperado_leitura != generico, (
        "o cenário deixou de ter escola sem Elefante — o teste parou de "
        "distinguir o peso por dimensão do peso genérico")
    print(f"\n  (B.iii) media_elefante da rede: {esperado_leitura} com o peso "
          f"por dimensão × {generico} com o peso genérico (ausência = zero)")

    # Mesma regra um nível acima (Admin Global): a média de cada rede e a média
    # global também pesam pelo denominador da dimensão.
    global_ = svc_rede.dashboard_global(db)
    cartao_rede = next(r for r in global_["redes"] if r["rede_id"] == rede.id)
    assert cartao_rede["media_elefante"] == esperado_leitura
    assert cartao_rede["media_matific"] == esperado_matematica
    assert global_["totais"]["media_elefante"] == esperado_leitura


# ---------------------------------------------------------------------------
# (B.iv) A mudança vem EXCLUSIVAMENTE da correção da régua — quantificada
# ---------------------------------------------------------------------------

def test_iv_com_e_sem_a_correcao_muda_a_media_e_nao_muda_a_ordem(
        db, municipio, monkeypatch):
    """(B.iv) O mesmo banco, recalculado com as duas versões de
    ``scoring._referencias``. O que a Secretaria vê tem de se separar em dois
    grupos limpos:

      * ORDEM (painel + todas as métricas) e ÍNDICE per capita → delta ZERO,
        porque saem dos totais brutos dos snapshots, que a régua não toca;
      * MÉDIAS 0–100 → mudam, e a mudança é exatamente a correção da régua.

    Se a ordem mudasse aqui, a régua LOCAL estaria vazando para o ranking de
    escolas.

    SEPARAÇÃO INSTITUCIONAL × ESCOLA: a rede lê SEMPRE as colunas INSTITUCIONAIS
    (régua fixa: A3 + pesos padrão + auto/P90), que a régua LOCAL não toca. Então,
    ao reverter a correção da régua LOCAL, a visão da Secretaria sai IDÊNTICA em
    TUDO — ordem, índice per capita E médias 0–100. O que a régua local muda fica
    contido dentro da escola (controle positivo `locais_*` no fim).

    Para o teste EXERCITAR de fato a régua local, as escolas são marcadas como
    PERSONALIZADAS: só o modo personalizado passa por ``scoring._referencias`` (o
    modo PADRÃO usa a régua institucional fixa e nem chama a função monkeypatchada,
    o que tornaria o teste inócuo)."""
    rede, escolas = municipio
    # FLAG (causa B): personalizar o scoring faz `recalcular_escola` voltar a
    # passar pela `scoring._referencias` — o mesmo caminho que o monkeypatch
    # substitui. Sem isto, o modo PADRÃO usa a régua institucional fixa e o
    # monkeypatch não teria efeito. Personalizar muda só a nota LOCAL; a rede
    # segue lendo as colunas institucionais.
    for esc in escolas.values():
        db.add(Configuracao(escola_id=esc.id, namespace=scoring.PERFIL_SCORING_NS,
                            chave="modo", valor="personalizado"))
    db.commit()
    for esc in escolas.values():
        scoring.recalcular_escola(db, esc.id)

    ordem_com = _visao(db, rede.id)
    indices_com = _indices(db, rede.id)
    medias_com = _medias(db, rede.id)
    # Nota LOCAL de cada aluno — é ELA que a régua local move (controle positivo).
    locais_com = {n.aluno_id: (n.nota_elefante, n.nota_matific)
                  for n in db.query(Nota).all()}

    monkeypatch.setattr(scoring, "_referencias", referencias_legado_com_vazamento)
    for esc in escolas.values():
        scoring.recalcular_escola(db, esc.id)

    ordem_sem = _visao(db, rede.id)
    indices_sem = _indices(db, rede.id)
    medias_sem = _medias(db, rede.id)
    locais_sem = {n.aluno_id: (n.nota_elefante, n.nota_matific)
                  for n in db.query(Nota).all()}

    nomes = {e.id: e.nome for e in escolas.values()}
    print("\n  (B.iv) COM x SEM a correção da régua LOCAL, visão da Secretaria:")
    for eid, nome in nomes.items():
        g_c, e_c, m_c = medias_com[eid]
        g_s, e_s, m_s = medias_sem[eid]
        print(f"    {nome:<20} media_geral {g_c:>6.1f} -> {g_s:>6.1f} "
              f"({g_s - g_c:+.1f}) | leitura {e_c:>6.1f} -> {e_s:>6.1f} "
              f"({e_s - e_c:+.1f}) | matematica {m_c:>6.1f} -> {m_s:>6.1f} "
              f"({m_s - m_c:+.1f}) | indice {indices_com[eid][0]:>6.1f} -> "
              f"{indices_sem[eid][0]:>6.1f}")
    print(f"    ordem do painel: {ordem_com['painel_ordem']} -> "
          f"{ordem_sem['painel_ordem']}")

    assert ordem_sem["painel_ordem"] == ordem_com["painel_ordem"], (
        "a régua de normalização mudou a ORDEM das escolas — logo o ranking de "
        "escolas depende dela, e não só dos totais per capita")
    assert ordem_sem["painel_posicoes"] == ordem_com["painel_posicoes"]
    assert ordem_sem["publico"] == ordem_com["publico"], (
        "a régua de normalização mudou a VITRINE PÚBLICA da rede")
    for metrica in METRICAS_OFICIAIS:
        assert ordem_sem["rankings"][metrica] == ordem_com["rankings"][metrica], (
            f"a régua mudou o ranking oficial por '{metrica}'")
    assert indices_sem == indices_com, (
        "o índice per capita mudou com a régua — ele deveria depender só dos "
        "totais brutos dos snapshots")
    # INVARIANTE REFORÇADO (causa C): as médias da rede são INSTITUCIONAIS, então
    # reverter a régua LOCAL não move NENHUMA delas. Antes o teste exigia que
    # mudassem (a rede lia a nota local); agora a garantia é mais forte — a régua
    # da escola não vaza para a Secretaria nem nas métricas secundárias.
    assert medias_sem == medias_com, (
        "reverter a régua LOCAL mexeu nas médias da rede — logo a Secretaria "
        "ainda lê a nota LOCAL da escola em vez das colunas institucionais")
    # CONTROLE POSITIVO: a régua local FOI de fato exercitada (senão o teste não
    # mediria nada). Com a escola PERSONALIZADA, a nota LOCAL muda ao reverter a
    # correção — é exatamente o que a separação mantém contido dentro da escola.
    assert locais_sem != locais_com, (
        "a nota LOCAL não mudou ao reverter a régua: o monkeypatch não teve "
        "efeito e o teste não está exercitando a régua local")
