"""Réplica CONGELADA de ``scoring._referencias`` ANTES da correção do vazamento.

Não é um teste (o nome não começa com ``test_``, então o pytest não coleta este
arquivo): é o "grupo de controle" usado por dois testes diferentes —
``test_vazamento_dimensoes`` (quanto a nota do aluno muda) e
``test_criterio8_secretaria`` (o que muda, e o que NÃO muda, na visão da
Secretaria). Ter uma cópia só evita que as duas medições divirjam.

O DEFEITO que esta cópia preserva de propósito: o tamanho da amostra que decide
"régua robusta (P90 + saturação) × escala simples (máximo)" era
``max(len(matific), len(elefante))`` — UM número para as DUAS dimensões. Numa
escola com muitos alunos no Matific e poucos no Elefante, a coorte de MATEMÁTICA
ligava a régua robusta dos indicadores de LEITURA, e importar o Matific mudava a
nota de Leitura de quem nunca tinha aberto o Matific.

É uma CÓPIA deliberada, não um import do código de produção: assim a medida
"quanto muda ao reverter a correção" continua significando a mesma coisa mesmo
que ``scoring._referencias`` evolua.
"""
from sqlalchemy import select

from app.models import ReferenciaNormalizacao
from app.services import scoring


def referencias_legado_com_vazamento(db, escola_id, matific, elefante,
                                     pontos_dificuldade):
    """O ``_referencias`` de ANTES: uma única amostra para as duas dimensões."""
    listas = {
        "atividades": [s.atividades for s in matific.values()],
        "media": [s.pontuacao_media for s in matific.values()],
        "estrelas": [s.estrelas for s in matific.values()],
        "livros": [s.livros_unicos for s in elefante.values()],
        "pontos_dificuldade": list(pontos_dificuldade.values()),
        "tentativas": [s.questoes_tentativas for s in elefante.values()],
        "acertos": [s.questoes_acertos for s in elefante.values()],
        "tempo": [s.tempo_leitura_min for s in elefante.values()],
    }
    # <<< O CANAL: UM número decide a régua das DUAS dimensões.
    n_alunos = max(len(matific), len(elefante))
    auto: dict[str, float] = {}
    k_vol: dict[str, float] = {}
    for indicador, valores in listas.items():
        chave = "max_" + indicador
        ativos = [x for x in valores if x and x > 0]
        if n_alunos >= scoring.MIN_ALUNOS_ROBUSTO and len(ativos) >= 2:
            auto[chave] = scoring._percentil(ativos, 0.90)
            if indicador in scoring.INDICADORES_VOLUME:
                k_vol[indicador] = scoring._percentil(ativos, 0.50)
        else:
            auto[chave] = max(valores, default=0)

    ref_row = db.execute(
        select(ReferenciaNormalizacao)
        .where(ReferenciaNormalizacao.escola_id == escola_id)
    ).scalar_one_or_none()
    if ref_row is None or ref_row.modo == "auto":
        return auto, "auto", k_vol
    manuais = ref_row.valores_manuais or {}
    return ({c: float(manuais.get(c) or auto[c])
             for c in scoring.CHAVES_REFERENCIA}, "manual", {})
