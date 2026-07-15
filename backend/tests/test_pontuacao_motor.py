"""Fundação do Motor de Pontuação genérico: catálogo de indicadores + registro
de métodos de normalização (código puro, sem banco). O foco é a normalização
ROBUSTA A OUTLIERS (o caso da 'Antonella')."""
from app.services.pontuacao import catalogo, normalizacao


# --- Catálogo ----------------------------------------------------------------

def test_catalogo_indicadores_iniciais():
    ids = {i.id for i in catalogo.CATALOGO}
    assert ids == {"elefante.tempo_leitura", "elefante.pontos_leitura",
                   "elefante.questoes_respondidas", "elefante.taxa_acerto"}
    # Todos rotulados p/ a IA (nome, descrição, categoria, unidade).
    for ind in catalogo.CATALOGO:
        assert ind.nome and ind.descricao and ind.categoria and ind.unidade


def test_criterios_padrao_somam_100():
    crit = catalogo.criterios_padrao("elefante")
    assert sum(c["peso"] for c in crit) == 100.0
    assert all(c["ativo"] and c["referencia"]["metodo"] for c in crit)


def test_taxa_acerto_extrator():
    tx = catalogo.obter("elefante.taxa_acerto")
    assert tx.valor({"questoes_tentativas": 20, "questoes_acertos": 16}) == 0.8
    assert tx.valor({"questoes_tentativas": 0, "questoes_acertos": 0}) == 0.0  # sem div/0
    assert tx.metodo_padrao == "fixa"          # qualidade, nunca percentil
    assert tx.ao_vivo is False


def test_questoes_respondidas_ao_vivo_com_cache():
    q = catalogo.obter("elefante.questoes_respondidas")
    assert q.ao_vivo is True and q.cache_s == 1800   # consulta ao vivo + 30 min


# --- Normalização: o caso da Antonella --------------------------------------

def test_percentil_nao_deixa_outlier_achatar_a_turma():
    """Antonella (1200) numa turma que lê 20–90: com P90 ela segue em 1º, mas os
    demais recuperam a faixa inteira (não colapsam para 2–8 como no 'máximo')."""
    turma = [20, 30, 40, 45, 50, 55, 60, 70, 80, 90, 1200]

    def norm(v):
        return normalizacao.normalizar("percentil", v, turma, "maior_melhor", {})[0]

    assert norm(1200) == 100.0          # Antonella: teto, continua campeã
    assert norm(90) == 100.0            # topo saudável: recupera o topo
    assert 45 <= norm(45) <= 55         # mediano perto de 50 (não 3,8)
    assert 18 <= norm(20) <= 26         # base perto de 22 (não 1,7)
    # Máximo (legado) achataria: 45/1200*100 = 3,75
    assert normalizacao.normalizar("max_manual", 45, turma, "maior_melhor", {})[0] < 5


def test_percentil_amostra_pequena_cai_para_mediana():
    """Turma minúscula (< 10 alunos com valor): percentil é instável → mediana×1.5."""
    poucos = [10, 20, 30]
    val, regua = normalizacao.normalizar("percentil", 30, poucos, "maior_melhor", {})
    assert regua["modo"] == "mediana_x1.5"
    assert regua["regua"] == 30.0       # mediana 20 × 1.5
    assert val == 100.0


def test_metodo_meta_fixa_imune_a_outlier():
    """Meta pedagógica (ex.: 1200 min = 100%): régua fixa, ninguém a move."""
    turma = [600, 1200, 30000]          # o 30000 não muda a régua
    val, regua = normalizacao.normalizar("meta", 600, turma, "maior_melhor",
                                         {"meta": 1200})
    assert regua["regua"] == 1200 and val == 50.0


def test_metodo_fixa_para_taxa_de_acerto():
    """Taxa 0–1: régua fixa 1.0 (100% = tudo certo)."""
    val, _ = normalizacao.normalizar("fixa", 0.8, [], "maior_melhor", {})
    assert val == 80.0


def test_metodo_media_da_coorte():
    val, regua = normalizacao.normalizar("media", 60, [30, 60, 90], "maior_melhor", {})
    assert regua["regua"] == 60.0 and val == 100.0   # aluno médio ≈ 100


def test_sentido_menor_melhor_invertido():
    """Indicador 'menos é melhor' (ex.: erros) funciona sem tocar no motor."""
    val, _ = normalizacao.normalizar("percentil", 0, [10, 20, 30, 40, 50, 60, 70, 80, 90, 100],
                                     "menor_melhor", {})
    assert val == 100.0                 # zero erros = nota máxima


def test_registro_de_metodos_extensivel():
    # Todos os métodos pedidos existem e declaram coortes válidas.
    assert set(normalizacao.REGISTRO) >= {"percentil", "meta", "max_manual", "media", "fixa"}
    assert "turma" in normalizacao.obter("percentil").coortes_validas
