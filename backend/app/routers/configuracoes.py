"""Configurações de métricas — o coração da flexibilidade do sistema.

Tudo que o motor de cálculo usa é editável por aqui (PRD §5, §29, §58–§62).
Qualquer alteração dispara recálculo integral (PRD §43) e fica no log.
"""
import math

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import (
    escola_autorizada,
    exigir_admin_global,
    exigir_modulo_da_escola,
    exigir_papeis,
)
from app.core.tempo import hoje_br
from app.models import (
    Configuracao,
    DificuldadeTurma,
    Escola,
    Livro,
    NivelDificuldade,
    PontuacaoNivelTurma,
    ReferenciaNormalizacao,
    Turma,
    Usuario,
)
from app.models.configuracao import slug_nivel
from pydantic import BaseModel, Field
from app.schemas import (
    DificuldadeUpdate,
    ElefanteExtraOut,
    ElefanteExtraUpdate,
    NivelCreate,
    NivelOut,
    NivelUpdate,
    PesosOut,
    PesosUpdate,
    PoliticaSincronizacaoIn,
    PoliticaSincronizacaoOut,
    ReferenciasOut,
    ReferenciasUpdate,
)
from app.services import (dificuldade_livro, elegibilidade, matific_destaque,
                          periodos, politica_sync, provisionamento, scoring)
from app.services import premiacoes as svc_premiacoes
from app.services.audit import registrar

router = APIRouter(prefix="/escolas/{escola_id}/configuracoes", tags=["Configurações"])

NAMESPACES_PESOS = {"matific", "elefante", "questoes", "geral"}
MODOS_PERFIL_SCORING = {"institucional", "personalizado"}

# GOVERNANÇA DA FÓRMULA — quem pode ESCREVER parâmetros matemáticos.
#
# "A escola usa o Constela; a escola não administra a matemática interna."
# Pesos, referências de normalização, pontos extras, dificuldade por série e
# pontuação por turma são PARÂMETROS OFICIAIS do motor. No perfil
# ``institucional`` (o padrão de toda escola) o motor os IGNORA por completo
# (``scoring._insumos_institucionais`` usa ``PESOS_PADRAO`` e as referências
# automáticas); eles só passam a valer no perfil ``personalizado`` — e ligar
# esse perfil já é decisão exclusiva do Admin Global (``PUT /perfil-scoring``).
# Deixar a escola editar um parâmetro que não vale (ou que só vale se o Admin
# Global autorizar) gerava a ilusão de controle e pedidos de suporte. Por isso
# TODAS as rotas de ESCRITA abaixo exigem ``exigir_admin_global`` — o mesmo
# critério já aplicado aos níveis (``/niveis``) e ao perfil. As LEITURAS (GET)
# continuam abertas a admin/coordenador (e à Secretaria): a escola CONSULTA.
# Nenhum endpoint foi removido — a escola perde só o botão de gravar.


# --- Perfil de scoring: institucional (rede) × personalizado (interno) -------

class PerfilScoringOut(BaseModel):
    modo: str  # "institucional" | "personalizado"


class PerfilScoringIn(BaseModel):
    modo: str = Field(description='"institucional" (padrão Constela) ou "personalizado"')


@router.get("/perfil-scoring", response_model=PerfilScoringOut)
def obter_perfil_scoring(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
):
    """Régua do ranking INTERNO da escola: ``institucional`` (padrão Constela) ou
    ``personalizado`` (config da própria escola). NÃO afeta o ranking da rede."""
    modo = scoring.obter_config(db, escola_id, scoring.PERFIL_SCORING_NS, "modo",
                                "institucional")
    return PerfilScoringOut(modo=str(modo))


@router.put("/perfil-scoring", response_model=PerfilScoringOut)
def definir_perfil_scoring(
    dados: PerfilScoringIn,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """Escolhe a régua do ranking INTERNO da escola. IMPORTANTE: personalizar NÃO
    muda a posição da escola no ranking da REDE — esse usa sempre a régua
    institucional (colunas ``nota_*_institucional``). Dispara recálculo.

    GOVERNANÇA: a dificuldade por livro (``dificuldade_livro``, v1) é a regra
    GLOBAL de todas as escolas; o perfil ``personalizado`` é o único override
    (régua legada por faixa da escola) e é AUTORIZADO só pelo Admin Global —
    um coordenador não pode tirar a própria escola da regra da rede."""
    modo = str(dados.modo).strip().lower()
    if modo not in MODOS_PERFIL_SCORING:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            'modo deve ser "institucional" ou "personalizado".')
    row = db.execute(
        select(Configuracao).where(
            Configuracao.escola_id == escola_id,
            Configuracao.namespace == scoring.PERFIL_SCORING_NS,
            Configuracao.chave == "modo",
        )
    ).scalar_one_or_none()
    anterior = str(row.valor) if row else "institucional"
    if row is None:
        row = Configuracao(escola_id=escola_id, namespace=scoring.PERFIL_SCORING_NS,
                           chave="modo", valor=modo)
        db.add(row)
    else:
        row.valor = modo
    registrar(db, "pesos.alterados", escola_id=escola_id, usuario_id=usuario.id,
              entidade="configuracao",
              detalhes={"perfil_scoring": {"de": anterior, "para": modo}})
    db.commit()
    scoring.recalcular_escola(db, escola_id)
    return PerfilScoringOut(modo=modo)


# --- Dificuldade por LIVRO (regra GLOBAL, somente leitura) ---------------------

@router.get("/dificuldade-livro")
def dificuldade_livro_vigente(
    escola_id: int = Depends(escola_autorizada),
    nivel: str | None = Query(default=None),
    titulo: str | None = Query(default=None),
    ano_escolar: str | None = Query(default=None),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
):
    """Versão vigente e parâmetros da dificuldade por livro (regra da REDE) e qual
    regra esta escola usa no contexto interno (``v1`` global ou a legada, se
    personalizada). Com ``nivel`` (+ ``titulo``, ``ano_escolar``) devolve a
    DECOMPOSIÇÃO do valor de uma leitura — a explicação para coordenação e
    professores. Nada aqui é editável: os parâmetros são constantes versionadas."""
    regra = dificuldade_livro.regra_da_escola(db, escola_id)
    cat = dificuldade_livro.catalogo()
    saida = {
        "versao_vigente": dificuldade_livro.VERSAO_VIGENTE,
        "regra_da_escola": regra.versao,
        "parametros": dificuldade_livro.parametros_publicos(),
        "catalogo": {"n": len(cat), **cat.meta},
    }
    if nivel:
        saida["exemplo"] = regra.explicar(nivel, titulo, ano_escolar)
    return saida


# --- "Quer ver um exemplo?" — a conta REAL de um caso, por plataforma ---------
#
# Somente leitura e sem nenhum dado de aluno. Cada rota chama a MESMA função que
# pontua de verdade (a regra da escola no Elefante; a régua e o índice da
# premiação "Melhor Matemática" no Matific) e devolve as peças da conta para a
# tela mostrar — a tela não refaz nenhuma conta. Leitura aberta a admin e
# coordenador (e à Secretaria, por GET, nas escolas da rede dela), como os
# demais GETs desta página; professor não entra.

# DECISÃO PROVISÓRIA (privacidade): com menos alunos do que isto fazendo
# atividade no período, a mediana ``k`` da escola praticamente revela a contagem
# de uma criança — o exemplo do Matific não mostra o ``k`` nem o índice (que
# permitiria deduzir o ``k``). Mudar o número é decisão do dono.
MINIMO_ALUNOS_REFERENCIA_MATIFIC = 5
# Um exemplo é de UM aluno: acima disto o número não é de criança (e um inteiro
# gigante estouraria o float da conta).
LIMITE_ATIVIDADES_EXEMPLO = 100_000
LIMITE_ESTRELAS_EXEMPLO = int(LIMITE_ATIVIDADES_EXEMPLO
                              * matific_destaque.ESTRELAS_MAX_POR_ATIVIDADE)
# Rótulo do "título único": o título só existe UMA vez no catálogo e foi aceito
# mesmo com outro nível (``Catalogo.buscar``). A regra chama os dois casos de
# ``titulo_nivel``; o exemplo os separa porque o segundo mistura as palavras de
# um livro com a mediana de outro nível — e a escola precisa ver isso.
RESOLVIDO_POR_TITULO_UNICO = "titulo_unico"


def _serie_do_exemplo(serie: str | None) -> int:
    """Ano escolar 1–5 pela MESMA régua de quem concorre às premiações
    (``elegibilidade.ano_premiavel``): "3", "3º Ano" → 3; "1ª Fase", "6" → 422."""
    numero = elegibilidade.ano_premiavel(serie)
    if numero is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Escolha o ano escolar do aluno: do 1º ao 5º ano (as premiações são do "
            "Ensino Fundamental I).")
    return numero


def _texto_decimal(valor: float, casas: int = 2) -> str:
    return f"{valor:.{casas}f}".replace(".", ",")


def _texto_inteiro(valor: int) -> str:
    """100000 → "100.000" (milhar com ponto, como a tela)."""
    return f"{int(valor):,}".replace(",", ".")


def _descrever_posicao(posicao: float | None) -> str | None:
    """Onde o nível fica na escada do Elefante, em palavras para a coordenação.

    A posição interna começa em zero (AA = 0, B = 5) e tem meios-degraus (A+ =
    4,5): mostrada crua, "degrau 0" ou "degrau 4,5" não faz sentido para quem lê.
    Por isso: "6º nível da escada, que começa no AA" (B) e "entre A e B na escada"
    (A+). A conta continua usando a posição — isto é só o texto."""
    if posicao is None or not math.isfinite(posicao):
        return None
    if float(posicao).is_integer():
        return f"{int(posicao) + 1}º nível da escada, que começa no AA"
    codigo_na_posicao = {float(p): cod for cod, p in scoring.POS_DO_NIVEL.items()}
    for cod, p in dificuldade_livro.PARAMS_VIGENTES["posicoes_extra"].items():
        codigo_na_posicao.setdefault(float(p), cod)
    abaixo = codigo_na_posicao.get(float(math.floor(posicao)))
    acima = codigo_na_posicao.get(float(math.ceil(posicao)))
    if abaixo and acima:
        return f"entre {abaixo} e {acima} na escada"
    return None


def _turmas_da_serie(db: Session, escola_id: int, serie: int) -> list[tuple[int, str, str]]:
    """``[(turma_id, nome, ano_escolar)]`` das turmas da escola, no ano letivo
    ativo, cuja série é ``serie`` pela MESMA régua da premiação
    (``elegibilidade.ano_premiavel``). Só a régua legada precisa disto: nela o
    valor do nível pode mudar por SÉRIE e por TURMA (``mapa_pontos_turmas``)."""
    escola = db.get(Escola, escola_id)
    linhas = db.execute(
        select(Turma.id, Turma.nome, Turma.ano_escolar)
        .where(Turma.escola_id == escola_id, Turma.ano_letivo == escola.ano_letivo_ativo)
        .order_by(Turma.nome, Turma.id)
    ).all()
    return [(tid, nome, rotulo) for tid, nome, rotulo in linhas
            if elegibilidade.ano_premiavel(rotulo) == serie]


def _exemplo_legado(regra, saida: dict, explicacao: dict, *, nivel: str | None,
                    titulo: str | None, elefante_id: int | None, serie: int,
                    turmas_da_serie: list[tuple[int, str, str]]) -> dict:
    """Perfil PERSONALIZADO (régua legada por faixa): a regra não decompõe o valor
    — só nível e valor existem, e nada é inventado no lugar dos fatores.

    O valor de um aluno do ano escolhido é o que a premiação paga: ela chama
    ``regra.valor_livro(nível, título, ano_escolar_da_turma, turma_id)`` para
    cada leitura, e a régua legada resolve TURMA > SÉRIE > padrão. O exemplo faz
    a MESMA chamada para cada turma da série. Se todas dão o mesmo valor, ele é o
    valor do ano; se diferem, o exemplo mostra o valor de cada turma; sem turma
    daquele ano, só o padrão da escola existe — e o texto diz isso."""
    avisos: list[str] = saida["avisos"]
    padrao = explicacao["valor"]            # turma_id=None → padrão da escola
    nivel_usado = explicacao.get("nivel")
    por_turma = []
    for turma_id, nome, rotulo in turmas_da_serie:
        valor_turma = regra.valor_livro(nivel, titulo, rotulo, turma_id,
                                        elefante_id=elefante_id)
        por_turma.append({"turma_id": turma_id, "turma": nome, "valor": valor_turma,
                          "valor_exibido": round(valor_turma, 2)})
    distintos = sorted({item["valor"] for item in por_turma})
    avisos.append(
        "Esta escola usa uma régua própria, autorizada pela Constela: todo livro do "
        "mesmo nível vale o mesmo, e o valor pode mudar por série ou por turma. Não há "
        "divisão em fatores como na regra da rede.")
    if not por_turma:
        valor, base_do_valor = padrao, "padrao"
        avisos.append(
            f"Esta escola não tem turma do {serie}º ano neste ano letivo: aparece o valor "
            "padrão da escola para o nível.")
    elif len(distintos) == 1:
        valor, base_do_valor = distintos[0], "serie"
        if valor != padrao:
            avisos.append(
                f"Para o {serie}º ano, a escola ajustou o valor do nível {nivel_usado}: "
                f"o padrão da escola é {_texto_decimal(padrao)}.")
    else:
        valor, base_do_valor = None, "turmas"
        avisos.append(
            f"Nesta escola o valor muda conforme a turma do {serie}º ano: veja o valor "
            "de cada turma.")
    saida.update({
        "personalizada": True,
        "livro": {"titulo": titulo, "nivel": nivel_usado},
        "calculo": None,
        "valor": valor,
        "valor_exibido": round(valor, 2) if valor is not None else None,
        # "serie": vale para todo aluno do ano; "turmas": depende da turma (ver
        # ``por_turma``); "padrao": a escola não tem turma do ano.
        "base_do_valor": base_do_valor,
        "valor_padrao_escola": padrao,
        "valor_minimo": distintos[0] if distintos else None,
        "valor_maximo": distintos[-1] if distintos else None,
        "por_turma": por_turma,
    })
    return saida


def montar_exemplo_elefante(regra, *, nivel: str | None, titulo: str | None,
                            elefante_id: int | None, serie: int,
                            entrada: dict,
                            turmas_da_serie: list[tuple[int, str, str]] | None = None,
                            ) -> dict:
    """O exemplo do Elefante: ``regra.explicar`` — a decomposição da MESMA conta
    que ``regra.valor_livro`` faz nas premiações e nos rankings — com as peças
    nomeadas para a tela. ``serie`` já validada (1–5); vira o rótulo "Nº Ano",
    o mesmo formato de ``Turma.ano_escolar`` que a premiação lê.
    ``turmas_da_serie`` só importa na régua legada (``_exemplo_legado``); a regra
    da rede não muda por turma."""
    ano_escolar = f"{serie}º Ano"
    explicacao = regra.explicar(nivel, titulo, ano_escolar, elefante_id=elefante_id)
    valor = explicacao["valor"]
    avisos: list[str] = []
    saida: dict = {
        "plataforma": "elefante",
        "regra": regra.versao,
        "regra_da_rede": dificuldade_livro.VERSAO_VIGENTE,
        "catalogo": dificuldade_livro.versao_catalogo(),
        "entrada": entrada,
        "serie": serie,
        "valor": valor,
        # Como o pódio "Melhor Leitor" mostra (2 casas): a ordem usa o valor bruto.
        "valor_exibido": round(valor, 2),
        "avisos": avisos,
    }
    if not isinstance(regra, dificuldade_livro.RegraGlobal):
        return _exemplo_legado(regra, saida, explicacao, nivel=nivel, titulo=titulo,
                               elefante_id=elefante_id, serie=serie,
                               turmas_da_serie=turmas_da_serie or [])

    params = dificuldade_livro.PARAMS_VIGENTES
    nivel_usado = explicacao["nivel"]
    # Mesma normalização da busca no catálogo (``Catalogo.buscar``).
    nivel_normalizado = str(nivel or "").strip().upper()
    meta = regra.metadados(titulo, nivel, elefante_id=elefante_id)
    via = explicacao["resolvido_por"]
    if (via == dificuldade_livro.RESOLVIDO_POR_TITULO and meta is not None
            and meta.nivel != nivel_normalizado):
        via = RESOLVIDO_POR_TITULO_UNICO
    status_palavras = explicacao["word_count_status"]
    ajuste = explicacao["ajuste_intrinseco"]
    limite = None
    if status_palavras == dificuldade_livro.WC_CATALOGO:
        if ajuste == params["piso"]:
            limite = "piso"
        elif ajuste == params["teto"]:
            limite = "teto"

    saida.update({
        "personalizada": False,
        "livro": {
            "titulo": titulo if titulo else (meta.titulo if meta is not None else None),
            "nivel": nivel_usado,
            "palavras": explicacao["word_count"],
            "palavras_status": status_palavras,
            "resolvido_por": via,
            "encontrado_no_catalogo": explicacao["encontrado_no_catalogo"],
            "elefante_id": explicacao["elefante_id"],
            "titulo_no_catalogo": meta.titulo if meta is not None else None,
            "nivel_no_catalogo": meta.nivel if meta is not None else None,
        },
        "calculo": {
            "posicao_nivel": explicacao["posicao"],
            "posicao_descricao": _descrever_posicao(explicacao["posicao"]),
            "base_nivel": explicacao["base_nivel"],
            "mediana_palavras_nivel": explicacao["mediana_nivel"],
            "fator_tamanho": ajuste,
            "limite_tamanho": limite,
            "piso_tamanho": params["piso"],
            "teto_tamanho": params["teto"],
            "fator_serie": explicacao["fator_serie"],
            "valor": valor,
        },
    })

    if explicacao["posicao"] is None:
        avisos.append(
            f"O nível “{nivel_usado or '(vazio)'}” não faz parte da escada oficial do "
            "Elefante Letrado, então o livro vale 0 ponto na regra atual.")
    if entrada.get("origem") == "nivel" and not titulo:
        avisos.append(
            "Sem um livro escolhido, o exemplo mostra o livro típico do nível "
            "(fator de tamanho 1,00).")
    elif status_palavras != dificuldade_livro.WC_CATALOGO:
        if status_palavras == dificuldade_livro.WC_SEM_MEDIANA:
            avisos.append(
                "Este nível não tem um tamanho típico de referência, então o livro vale "
                "o típico do nível (fator de tamanho 1,00).")
        else:
            avisos.append(
                "Não há contagem de palavras deste livro no catálogo oficial, então ele "
                "vale o livro típico do nível (fator de tamanho 1,00).")
    if limite == "teto":
        avisos.append(
            "O livro é bem maior que o típico do nível: o fator de tamanho parou no "
            f"máximo ({_texto_decimal(params['teto'])}).")
    elif limite == "piso":
        avisos.append(
            "O livro é bem menor que o típico do nível: o fator de tamanho parou no "
            f"mínimo ({_texto_decimal(params['piso'])}).")
    if meta is not None and meta.nivel != nivel_normalizado:
        if via == RESOLVIDO_POR_TITULO_UNICO:
            avisos.append(
                f"O título foi achado no catálogo oficial no nível {meta.nivel}. A conta "
                f"usa as palavras desse livro com o nível {nivel_usado} — é assim que a "
                "pontuação real faz com este título.")
        else:
            avisos.append(
                f"No catálogo oficial este livro é do nível {meta.nivel}; vale o nível "
                f"{nivel_usado}, que é o registrado no acervo da escola.")
    if entrada.get("origem") == "acervo":
        avisos.append(
            "O exemplo usa o nível atual do livro no acervo. Uma leitura já registrada "
            "guarda o nível que valia quando o aluno leu.")
    return saida


@router.get("/pontuacao/exemplo/elefante",
            dependencies=[Depends(exigir_modulo_da_escola("leitura"))])
def exemplo_pontuacao_elefante(
    escola_id: int = Depends(escola_autorizada),
    serie: str = Query(..., description="Ano escolar do aluno, de 1 a 5."),
    livro_id: int | None = Query(default=None, description="Livro do acervo desta escola."),
    elefante_id: int | None = Query(default=None,
                                    description="Id do livro no catálogo oficial do Elefante."),
    nivel: str | None = Query(default=None, description="Só o nível (livro típico)."),
    titulo: str | None = Query(default=None, description="Título, junto com o nível."),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
):
    """Quanto UMA leitura vale para um aluno do ano escolar dado, com a conta
    aberta: nível, palavras do livro e de onde vieram, mediana do nível, base,
    fator de tamanho, fator de série e o valor — pela regra desta escola, a
    mesma das premiações e dos rankings. Use UMA forma de escolher o livro:
    ``livro_id`` (acervo da escola), ``elefante_id`` (catálogo oficial) ou
    ``nivel`` (+ ``titulo`` opcional)."""
    numero_serie = _serie_do_exemplo(serie)
    titulo = (titulo or "").strip() or None
    nivel_bruto = (nivel or "").strip()
    formas = sum([livro_id is not None, elefante_id is not None,
                  bool(nivel_bruto) or titulo is not None])
    if formas != 1:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Escolha um livro do acervo ou informe o nível do livro (uma forma só).")

    regra = dificuldade_livro.regra_da_escola(db, escola_id)

    def _montar(**kwargs) -> dict:
        # Na régua legada o valor pode mudar por série/turma: o exemplo precisa
        # das turmas do ano escolhido. A regra da rede não muda por turma.
        turmas = (None if isinstance(regra, dificuldade_livro.RegraGlobal)
                  else _turmas_da_serie(db, escola_id, numero_serie))
        return montar_exemplo_elefante(regra, serie=numero_serie,
                                       turmas_da_serie=turmas, **kwargs)

    if livro_id is not None:
        livro = db.execute(select(Livro).where(
            Livro.id == livro_id, Livro.escola_id == escola_id)).scalar_one_or_none()
        if livro is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                "Livro não encontrado no acervo desta escola.")
        entrada = {"origem": "acervo", "livro_id": livro.id,
                   "elefante_id": livro.elefante_id, "titulo": livro.titulo,
                   "nivel": livro.nivel_codigo, "serie": numero_serie}
        return _montar(nivel=livro.nivel_codigo, titulo=livro.titulo,
                       elefante_id=livro.elefante_id, entrada=entrada)

    if elefante_id is not None:
        meta = dificuldade_livro.catalogo().buscar_por_id(elefante_id)
        if meta is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                "Livro não encontrado no catálogo oficial do Elefante Letrado.")
        entrada = {"origem": "catalogo", "livro_id": None, "elefante_id": meta.id,
                   "titulo": meta.titulo, "nivel": meta.nivel, "serie": numero_serie}
        return _montar(nivel=meta.nivel, titulo=meta.titulo, elefante_id=meta.id,
                       entrada=entrada)

    if not nivel_bruto:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Informe o nível do livro junto com o título.")
    # Vocabulário OFICIAL — o mesmo que o catálogo de livros valida. Um nível
    # inventado não vira "0 ponto" silencioso.
    from app.routers.plataformas import NIVEIS_OFICIAIS
    codigo = nivel_bruto.upper()
    if codigo not in NIVEIS_OFICIAIS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Nível “{nivel_bruto}” não existe no Elefante Letrado. Use um nível oficial: "
            "AA, BB, CC, DD, A…Z, Z+ ou A+.")
    entrada = {"origem": "nivel", "livro_id": None, "elefante_id": None,
               "titulo": titulo, "nivel": codigo, "serie": numero_serie}
    return _montar(nivel=codigo, titulo=titulo, elefante_id=None, entrada=entrada)


def montar_exemplo_matific(regua: dict, atividades: int, estrelas: int) -> dict:
    """O exemplo da premiação "Melhor Matemática" com os números digitados e a
    régua REAL da escola no período (``premiacoes.regua_matematica``). O teto de
    estrelas e o índice saem de ``matific_destaque`` — as mesmas funções da
    premiação. Sem nenhum dado de aluno: só a régua agregada."""
    consideradas = matific_destaque.limitar_estrelas(atividades, estrelas)
    n_alunos = int(regua.get("alunos_com_atividade") or 0)
    k = regua.get("k_mediana_atividades")
    modo = regua.get("modo")
    avisos: list[str] = []
    if consideradas < estrelas:
        avisos.append(
            f"Foram informadas {estrelas} estrelas, mas cada atividade dá no máximo "
            f"{int(matific_destaque.ESTRELAS_MAX_POR_ATIVIDADE)}: contam "
            f"{_texto_decimal(consideradas, 0)}.")
    if modo == "situacao_atual":
        avisos.append(
            "Período “todo o histórico”: a referência usa o último dado do Matific no "
            "ano letivo.")

    if modo == "fora_do_ano_letivo":
        motivo = "fora_do_ano_letivo"
        mensagem = (f"O período escolhido não cai no ano letivo {regua.get('ano_letivo')}: "
                    "a premiação não mede nada fora dele.")
    elif modo == "periodo_invalido":
        motivo = "periodo_invalido"
        mensagem = "As datas do período estão trocadas: o início vem depois do fim."
    elif k is None or n_alunos == 0:
        motivo = "sem_atividade"
        mensagem = ("Nenhum aluno do 1º ao 5º ano fez atividade no Matific neste período, "
                    "então ainda não há referência da escola para comparar.")
    elif n_alunos < MINIMO_ALUNOS_REFERENCIA_MATIFIC:
        motivo = "poucos_alunos"
        mensagem = (f"Poucos alunos no período para mostrar a referência: só {n_alunos} "
                    f"fizeram atividades. A referência da escola aparece a partir de "
                    f"{MINIMO_ALUNOS_REFERENCIA_MATIFIC} alunos, para não expor o resultado "
                    "de uma criança.")
    else:
        motivo = None
        mensagem = None

    disponivel = motivo is None
    calculo = None
    if disponivel:
        # O índice OFICIAL sai de ``matific_destaque.indice``; zeros, denominador
        # e o valor antes do teto são só as etapas, para a tela mostrar a conta.
        # ``k`` é a mediana de contagens inteiras (n ou n,5): o arredondamento a 4
        # casas da régua não o altera — é o mesmo ``k`` da premiação.
        valor = matific_destaque.indice(atividades, consideradas, k)
        # As etapas usam a MESMA expressão do índice, SEM arredondar: comparar o
        # índice com uma divisão por valores arredondados dava "parou no teto"
        # por ruído de float (0,2 × 41 = 8,200000000000001 → 2,48 "no máximo").
        # Só os campos de exibição são arredondados.
        zeros_brutos = matific_destaque.FRACAO_ZEROS_EXTRAS * max(0.0, float(k))
        denominador_bruto = float(atividades) + zeros_brutos
        sem_teto = max(0.0, consideradas) / denominador_bruto
        calculo = {
            "zeros_extras": round(zeros_brutos, 4),
            "denominador": round(denominador_bruto, 4),
            "indice_sem_teto": sem_teto,
            "indice": valor,
            # Como o pódio mostra (2 casas); a ordem da premiação usa o bruto.
            "indice_exibido": round(valor, 2) if valor is not None else None,
            "teto_indice": matific_destaque.ESTRELAS_MAX_POR_ATIVIDADE,
            # Com as estrelas já limitadas a 5 por atividade e k > 0, o índice
            # nunca passa de 5 — o campo fica por clareza do contrato.
            "teto_aplicado": sem_teto > matific_destaque.ESTRELAS_MAX_POR_ATIVIDADE,
        }
    return {
        "plataforma": "matific",
        "premiacao": "Melhor Matemática",
        "entrada": {"atividades": atividades, "estrelas": estrelas},
        "estrelas_consideradas": consideradas,
        "teto_estrelas_por_atividade": matific_destaque.ESTRELAS_MAX_POR_ATIVIDADE,
        "regua": {
            "modo": modo,
            "ano_letivo": regua.get("ano_letivo"),
            "inicio_efetivo": regua.get("inicio_efetivo"),
            "fim_efetivo": regua.get("fim_efetivo"),
            "alunos_com_atividade": n_alunos,
            "minimo_alunos": MINIMO_ALUNOS_REFERENCIA_MATIFIC,
            "fracao_zeros_extras": matific_destaque.FRACAO_ZEROS_EXTRAS,
            # Abaixo do mínimo de alunos o k NÃO sai (nem o que permitiria deduzi-lo).
            "k_mediana_atividades": k if disponivel else None,
            "zeros_extras": calculo["zeros_extras"] if calculo else None,
        },
        "referencia_disponivel": disponivel,
        "motivo": motivo,
        "mensagem": mensagem,
        "calculo": calculo,
        "avisos": avisos,
    }


@router.get("/pontuacao/exemplo/matific",
            dependencies=[Depends(exigir_modulo_da_escola("matematica"))])
def exemplo_pontuacao_matific(
    escola_id: int = Depends(escola_autorizada),
    atividades: int = Query(..., description="Atividades feitas no período (≥ 1)."),
    estrelas: int = Query(..., description="Estrelas ganhas no período (≥ 0)."),
    periodo: str = Query(default="mes"),
    inicio: str | None = Query(default=None),
    fim: str | None = Query(default=None),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
):
    """O índice da premiação "Melhor Matemática" para atividades e estrelas
    digitadas, com a régua REAL da escola no período (o mesmo período e o mesmo
    padrão da tela de Premiações): estrelas que contam (até 5 por atividade), a
    mediana de atividades ``k`` da escola, os "zeros extras" (0,2·k), o
    denominador e o índice com o teto de 5. Nenhum aluno aparece na resposta."""
    if atividades <= 0:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Informe pelo menos 1 atividade: sem atividade não há média de estrelas.")
    if estrelas < 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "As estrelas não podem ser negativas.")
    if atividades > LIMITE_ATIVIDADES_EXEMPLO:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Use números de um aluno: até {_texto_inteiro(LIMITE_ATIVIDADES_EXEMPLO)} "
            "atividades no período.")
    if estrelas > LIMITE_ESTRELAS_EXEMPLO:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Use números de um aluno: até {_texto_inteiro(LIMITE_ESTRELAS_EXEMPLO)} "
            "estrelas no período.")
    escola = db.get(Escola, escola_id)
    try:
        ini, fim_dt, rotulo = periodos.resolver(
            periodo, hoje_br(), escola.ano_letivo_ativo,
            periodos._parse_data(inicio), periodos._parse_data(fim))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Data inválida (use AAAA-MM-DD).") from exc
    regua = svc_premiacoes.regua_matematica(db, escola_id, ini, fim_dt)
    saida = montar_exemplo_matific(regua, atividades, estrelas)
    saida["periodo"] = {"chave": periodo, "rotulo": rotulo,
                        "inicio": ini.isoformat() if ini else None,
                        "fim": fim_dt.isoformat() if fim_dt else None}
    return saida


# --- Pesos (PRD §29, §59, §60) ----------------------------------------------

@router.get("/pesos/{namespace}", response_model=PesosOut)
def obter_pesos(
    namespace: str,
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
):
    if namespace not in NAMESPACES_PESOS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Grupo de pesos inexistente.")
    valores = scoring.obter_pesos_brutos(db, escola_id, f"pesos.{namespace}")
    return PesosOut(namespace=namespace, valores=valores, soma=round(sum(valores.values()), 2))


@router.put("/pesos/{namespace}", response_model=PesosOut)
def salvar_pesos(
    namespace: str,
    dados: PesosUpdate,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_admin_global),  # parâmetro oficial: só Admin Global
    db: Session = Depends(get_db),
):
    if namespace not in NAMESPACES_PESOS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Grupo de pesos inexistente.")

    esperados = set(scoring.PESOS_PADRAO[f"pesos.{namespace}"].keys())
    if set(dados.valores.keys()) != esperados:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Indicadores esperados: {', '.join(sorted(esperados))}.",
        )
    soma = round(sum(dados.valores.values()), 2)
    if abs(soma - 100.0) > 0.01:
        # A soma dos pesos deve sempre resultar em 100% (PRD §33, §59)
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"A soma dos pesos deve ser 100%. Soma atual: {soma}%.",
        )

    chave_ns = f"pesos.{namespace}"
    row = db.execute(
        select(Configuracao).where(
            Configuracao.escola_id == escola_id,
            Configuracao.namespace == chave_ns,
            Configuracao.chave == "valores",
        )
    ).scalar_one_or_none()
    anterior = dict(row.valor) if row else scoring.PESOS_PADRAO[chave_ns]
    if row is None:
        row = Configuracao(escola_id=escola_id, namespace=chave_ns, chave="valores", valor=dados.valores)
        db.add(row)
    else:
        row.valor = dados.valores

    registrar(db, "pesos.alterados", escola_id=escola_id, usuario_id=usuario.id,
              entidade="configuracao", detalhes={"namespace": namespace, "de": anterior, "para": dados.valores})
    db.commit()
    scoring.recalcular_escola(db, escola_id)
    return PesosOut(namespace=namespace, valores=dados.valores, soma=soma)


# --- Referências de normalização (PRD §31, §62) -----------------------------

@router.get("/referencias", response_model=ReferenciasOut)
def obter_referencias(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
):
    row = db.execute(
        select(ReferenciaNormalizacao).where(ReferenciaNormalizacao.escola_id == escola_id)
    ).scalar_one_or_none()
    em_uso, modo = scoring.referencias_em_uso(db, escola_id)
    return ReferenciasOut(
        modo=row.modo if row else "auto",
        valores_manuais=row.valores_manuais if row else {},
        valores_em_uso=em_uso,
    )


@router.put("/referencias", response_model=ReferenciasOut)
def salvar_referencias(
    dados: ReferenciasUpdate,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_admin_global),  # parâmetro oficial: só Admin Global
    db: Session = Depends(get_db),
):
    invalidas = set(dados.valores_manuais) - set(scoring.CHAVES_REFERENCIA)
    if invalidas:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Referências desconhecidas: {', '.join(sorted(invalidas))}.",
        )
    row = db.execute(
        select(ReferenciaNormalizacao).where(ReferenciaNormalizacao.escola_id == escola_id)
    ).scalar_one_or_none()
    if row is None:
        row = ReferenciaNormalizacao(escola_id=escola_id)
        db.add(row)
    row.modo = dados.modo
    row.valores_manuais = dados.valores_manuais

    registrar(db, "referencias.alteradas", escola_id=escola_id, usuario_id=usuario.id,
              entidade="referencia_normalizacao",
              detalhes={"modo": dados.modo, "valores": dados.valores_manuais})
    db.commit()
    scoring.recalcular_escola(db, escola_id)
    em_uso, _ = scoring.referencias_em_uso(db, escola_id)
    return ReferenciasOut(modo=row.modo, valores_manuais=row.valores_manuais, valores_em_uso=em_uso)


# --- Pontos extras por livro lido na escola (Elefante) ----------------------
# Config própria (namespace pesos.elefante_extra) — NÃO usa /pesos, que exige
# soma 100%. A regra de horário (janela do turno) vive no scoring.

@router.get("/elefante-extra", response_model=ElefanteExtraOut)
def obter_elefante_extra(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
):
    v = scoring.obter_config(db, escola_id, "pesos.elefante_extra", "valores",
                             {"ativo": False, "pontos_por_livro": 0.0})
    return ElefanteExtraOut(ativo=bool(v.get("ativo", False)),
                            pontos_por_livro=float(v.get("pontos_por_livro", 0) or 0))


@router.put("/elefante-extra", response_model=ElefanteExtraOut)
def salvar_elefante_extra(
    dados: ElefanteExtraUpdate,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_admin_global),  # parâmetro oficial: só Admin Global
    db: Session = Depends(get_db),
):
    """Liga/desliga os pontos extras e define quanto cada livro lido na escola
    vale. Desligar NÃO apaga nenhuma leitura — só deixa de somar o bônus. Recalcula."""
    valor = {"ativo": bool(dados.ativo), "pontos_por_livro": round(float(dados.pontos_por_livro), 2)}
    row = db.execute(
        select(Configuracao).where(
            Configuracao.escola_id == escola_id,
            Configuracao.namespace == "pesos.elefante_extra",
            Configuracao.chave == "valores")
    ).scalar_one_or_none()
    if row is None:
        row = Configuracao(escola_id=escola_id, namespace="pesos.elefante_extra",
                           chave="valores", valor=valor)
        db.add(row)
    else:
        row.valor = valor
    registrar(db, "elefante_extra.alterado", escola_id=escola_id, usuario_id=usuario.id,
              entidade="configuracao", detalhes=valor)
    db.commit()
    scoring.recalcular_escola(db, escola_id)
    return ElefanteExtraOut(**valor)


# --- Dificuldade por turma/série (PRD §39, §61) -----------------------------

@router.get("/dificuldade")
def obter_dificuldade(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
):
    niveis = db.execute(
        select(NivelDificuldade)
        .where(NivelDificuldade.escola_id == escola_id)
        .order_by(NivelDificuldade.ordem)
    ).scalars().all()
    series = [
        linha[0]
        for linha in db.execute(
            select(Turma.ano_escolar).where(Turma.escola_id == escola_id).distinct().order_by(Turma.ano_escolar)
        ).all()
    ]
    overrides = db.execute(
        select(DificuldadeTurma).where(DificuldadeTurma.escola_id == escola_id)
    ).scalars().all()
    mapa = {}
    for override in overrides:
        mapa.setdefault(override.ano_escolar, {})[override.nivel_id] = override.pontos

    tabelas = []
    for serie in series:
        pontos = {
            nivel.id: mapa.get(serie, {}).get(nivel.id, nivel.pontos_padrao)
            for nivel in niveis
        }
        tabelas.append({"ano_escolar": serie, "pontos": pontos})

    return {
        "niveis": [NivelOut.model_validate(n) for n in niveis],
        "series": tabelas,
    }


@router.put("/dificuldade")
def salvar_dificuldade(
    alteracoes: list[DificuldadeUpdate],
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_admin_global),  # parâmetro oficial: só Admin Global
    db: Session = Depends(get_db),
):
    for alteracao in alteracoes:
        nivel = db.get(NivelDificuldade, alteracao.nivel_id)
        if nivel is None or nivel.escola_id != escola_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nível inválido para esta escola.")
        row = db.execute(
            select(DificuldadeTurma).where(
                DificuldadeTurma.escola_id == escola_id,
                DificuldadeTurma.ano_escolar == alteracao.ano_escolar,
                DificuldadeTurma.nivel_id == alteracao.nivel_id,
            )
        ).scalar_one_or_none()
        if row is None:
            row = DificuldadeTurma(
                escola_id=escola_id,
                ano_escolar=alteracao.ano_escolar,
                nivel_id=alteracao.nivel_id,
            )
            db.add(row)
        row.pontos = alteracao.pontos

    registrar(db, "dificuldade.alterada", escola_id=escola_id, usuario_id=usuario.id,
              entidade="dificuldade_turma",
              detalhes={"alteracoes": [a.model_dump() for a in alteracoes]})
    db.commit()
    scoring.recalcular_escola(db, escola_id)
    return {"mensagem": f"{len(alteracoes)} valores atualizados. Notas recalculadas."}


# --- Cadastro dos níveis de dificuldade (faixas) — CRUD (PRD §38) ------------
# As faixas (NivelDificuldade) são a BASE de tudo no Elefante: sem elas, não há
# catálogo de códigos para pontuar por turma nem para informar "livros por
# nível". Estas rotas permitem cadastrá-las/editá-las pela interface (antes,
# só o seed criava faixas — escola criada pela tela ficava sem nenhuma).

def _normalizar_codigos(codigos: list[str] | None) -> list[str]:
    """Códigos de letra em MAIÚSCULA, sem espaços, sem vazios nem repetidos."""
    limpos: list[str] = []
    vistos: set[str] = set()
    for bruto in codigos or []:
        cod = str(bruto).strip().upper()
        if cod and cod not in vistos:
            vistos.add(cod)
            limpos.append(cod)
    return limpos


@router.post("/niveis", response_model=NivelOut, status_code=status.HTTP_201_CREATED)
def criar_nivel(
    dados: NivelCreate,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_admin_global),  # níveis = referência: só admin global edita
    db: Session = Depends(get_db),
):
    ordem_max = db.execute(
        select(func.max(NivelDificuldade.ordem)).where(NivelDificuldade.escola_id == escola_id)
    ).scalar()
    nome = dados.nome.strip()
    nivel = NivelDificuldade(
        escola_id=escola_id,
        nome=nome,
        codigo=slug_nivel(nome),
        codigos=_normalizar_codigos(dados.codigos),
        pontos_padrao=float(dados.pontos_padrao),
        ordem=0 if ordem_max is None else ordem_max + 1,
    )
    db.add(nivel)
    registrar(db, "nivel.criado", escola_id=escola_id, usuario_id=usuario.id,
              entidade="nivel_dificuldade",
              detalhes={"nome": nome, "codigos": nivel.codigos, "pontos": nivel.pontos_padrao})
    db.commit()
    db.refresh(nivel)
    scoring.recalcular_escola(db, escola_id)
    return NivelOut.model_validate(nivel)


@router.put("/niveis/{nivel_id}", response_model=NivelOut)
def atualizar_nivel(
    nivel_id: int,
    dados: NivelUpdate,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_admin_global),  # níveis = referência: só admin global edita
    db: Session = Depends(get_db),
):
    nivel = db.get(NivelDificuldade, nivel_id)
    if nivel is None or nivel.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nível não encontrado nesta escola.")
    if dados.nome is not None:
        nivel.nome = dados.nome.strip()
        nivel.codigo = slug_nivel(nivel.nome)
    if dados.codigos is not None:
        nivel.codigos = _normalizar_codigos(dados.codigos)
    if dados.pontos_padrao is not None:
        nivel.pontos_padrao = float(dados.pontos_padrao)
    if dados.ordem is not None:
        nivel.ordem = dados.ordem
    registrar(db, "nivel.alterado", escola_id=escola_id, usuario_id=usuario.id,
              entidade="nivel_dificuldade", entidade_id=nivel.id,
              detalhes={"nome": nivel.nome, "codigos": nivel.codigos, "pontos": nivel.pontos_padrao})
    db.commit()
    db.refresh(nivel)
    scoring.recalcular_escola(db, escola_id)
    return NivelOut.model_validate(nivel)


@router.delete("/niveis/{nivel_id}")
def excluir_nivel(
    nivel_id: int,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_admin_global),  # níveis = referência: só admin global edita
    db: Session = Depends(get_db),
):
    nivel = db.get(NivelDificuldade, nivel_id)
    if nivel is None or nivel.escola_id != escola_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nível não encontrado nesta escola.")
    nome = nivel.nome
    # Remove antes os pontos por série que referenciam este nível (FK) — de forma
    # explícita, sem depender do CASCADE do banco (portável entre SQLite/Postgres).
    db.execute(delete(DificuldadeTurma).where(
        DificuldadeTurma.escola_id == escola_id, DificuldadeTurma.nivel_id == nivel_id))
    db.delete(nivel)
    registrar(db, "nivel.excluido", escola_id=escola_id, usuario_id=usuario.id,
              entidade="nivel_dificuldade", entidade_id=nivel_id, detalhes={"nome": nome})
    db.commit()
    scoring.recalcular_escola(db, escola_id)
    return {"mensagem": f"Nível “{nome}” removido. Notas recalculadas."}


@router.post("/niveis/padrao")
def restaurar_niveis_padrao(
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_admin_global),  # níveis = referência: só admin global edita
    db: Session = Depends(get_db),
):
    """Cria os níveis de dificuldade PADRÃO do Elefante Letrado — atalho de 1
    clique para escolas que nasceram sem faixas. Se já houver níveis, não mexe
    (não duplica); devolve os atuais."""
    vazia = provisionamento.escola_sem_niveis(db, escola_id)
    niveis = provisionamento.semear_niveis_padrao(db, escola_id)
    if vazia:
        registrar(db, "niveis.padrao_criados", escola_id=escola_id, usuario_id=usuario.id,
                  entidade="nivel_dificuldade", detalhes={"quantidade": len(niveis)})
        db.commit()
        for n in niveis:
            db.refresh(n)
        scoring.recalcular_escola(db, escola_id)
    return {
        "criados": len(niveis) if vazia else 0,
        "niveis": [NivelOut.model_validate(n) for n in niveis],
    }


# --- Pontuação LIVRE por nível, por TURMA (PRD §39) --------------------------

class PontuacaoTurmaUpdate(BaseModel):
    turma_id: int
    # {"AA": 1.0, "M": 2.0, ...} — parcial; código ausente herda o padrão.
    pontos: dict[str, float] = Field(default_factory=dict)
    # Replicar a MESMA configuração para estas OUTRAS turmas (opcional). Cada uma
    # continua editável individualmente depois.
    aplicar_em: list[int] = Field(default_factory=list)


def _catalogo_niveis(db: Session, escola_id: int) -> list[dict]:
    """Catálogo canônico e ORDENADO dos códigos de nível (AA..Z) da escola, com o
    ponto PADRÃO de cada um e a faixa a que pertence. Derivado das faixas
    (NivelDificuldade.codigos) — sem tabela nova, sem código fixo."""
    niveis = db.execute(
        select(NivelDificuldade)
        .where(NivelDificuldade.escola_id == escola_id)
        .order_by(NivelDificuldade.ordem)
    ).scalars().all()
    catalogo: list[dict] = []
    vistos: set[str] = set()
    for nivel in niveis:
        for codigo in (nivel.codigos or []):
            cod = str(codigo).strip().upper()
            if not cod or cod in vistos:
                continue
            vistos.add(cod)
            catalogo.append({"codigo": cod, "pontos_padrao": float(nivel.pontos_padrao),
                             "faixa": nivel.nome})
    return catalogo


@router.get("/pontuacao-turma")
def obter_pontuacao_turma(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(exigir_papeis("admin", "coordenador")),
):
    """Catálogo de níveis (com padrões) + a config LIVRE já salva por turma."""
    catalogo = _catalogo_niveis(db, escola_id)
    turmas = db.execute(
        select(Turma).where(Turma.escola_id == escola_id, Turma.status == "ativa")
        .order_by(Turma.ano_escolar, Turma.nome)
    ).scalars().all()
    overrides = {
        row.turma_id: {str(k).upper(): float(v) for k, v in (row.pontos_por_codigo or {}).items()}
        for row in db.execute(
            select(PontuacaoNivelTurma).where(PontuacaoNivelTurma.escola_id == escola_id)
        ).scalars()
    }
    return {
        "catalogo": catalogo,
        "turmas": [{"turma_id": t.id, "nome": t.nome, "ano_escolar": t.ano_escolar,
                    "pontos": overrides.get(t.id, {})} for t in turmas],
    }


@router.put("/pontuacao-turma")
def salvar_pontuacao_turma(
    dados: PontuacaoTurmaUpdate,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_admin_global),  # parâmetro oficial: só Admin Global
    db: Session = Depends(get_db),
):
    """Salva a tabela de pontos por nível de UMA turma e, opcionalmente, REPLICA a
    mesma config para outras turmas (aplicar_em) — cada uma continua editável
    depois. Guarda só o que difere do padrão (config esparsa). UM recálculo no fim."""
    # Turmas-alvo = a principal + as marcadas para replicar (sem repetir).
    alvos = list(dict.fromkeys([dados.turma_id, *dados.aplicar_em]))
    turmas: dict[int, Turma] = {}
    for tid in alvos:
        t = db.get(Turma, tid)
        if t is None or t.escola_id != escola_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Turma inválida para esta escola.")
        turmas[tid] = t

    validos = {c["codigo"] for c in _catalogo_niveis(db, escola_id)}
    limpos: dict[str, float] = {}
    for codigo, pontos in (dados.pontos or {}).items():
        cod = str(codigo).strip().upper()
        if cod not in validos:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Nível “{codigo}” não existe nesta escola.")
        if pontos is None or float(pontos) < 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pontos não podem ser negativos.")
        limpos[cod] = round(float(pontos), 2)

    for tid in alvos:
        row = db.execute(
            select(PontuacaoNivelTurma).where(
                PontuacaoNivelTurma.escola_id == escola_id,
                PontuacaoNivelTurma.turma_id == tid)
        ).scalar_one_or_none()
        if row is None:
            row = PontuacaoNivelTurma(escola_id=escola_id, turma_id=tid)
            db.add(row)
        row.pontos_por_codigo = dict(limpos)

    registrar(db, "pontuacao_turma.alterada", escola_id=escola_id, usuario_id=usuario.id,
              entidade="pontuacao_nivel_turma",
              detalhes={"turmas": alvos, "n_codigos": len(limpos)})
    db.commit()
    scoring.recalcular_escola(db, escola_id)   # 1 recálculo, mesmo replicando em N turmas

    n = len(alvos)
    msg = (f"Pontuação aplicada a {n} turmas. Notas recalculadas." if n > 1
           else f"Pontuação da turma {turmas[dados.turma_id].nome} salva. Notas recalculadas.")
    return {"mensagem": msg, "turma_id": dados.turma_id, "turmas": alvos, "pontos": limpos}


@router.get("/sincronizacao", response_model=PoliticaSincronizacaoOut,
            dependencies=[Depends(exigir_papeis("admin", "coordenador"))])
def obter_politica_sincronizacao(
    escola_id: int = Depends(escola_autorizada),
    db: Session = Depends(get_db),
):
    """A política de sincronização da escola — hoje, se a sync pode criar ficha.

    Escola que nunca configurou responde ``permitir``, o comportamento de
    sempre: a trava é opt-in e não muda nada retroativamente."""
    return politica_sync.obter(db, escola_id)


@router.put("/sincronizacao", response_model=PoliticaSincronizacaoOut)
def salvar_politica_sincronizacao(
    dados: PoliticaSincronizacaoIn,
    escola_id: int = Depends(escola_autorizada),
    usuario: Usuario = Depends(exigir_admin_global),
    db: Session = Depends(get_db),
):
    """Declara quem é a FONTE DE VERDADE da matrícula desta escola.

    ``bloquear`` diz que a plataforma não matricula ninguém: na sincronização, a
    linha que não casa com segurança vira PENDÊNCIA de identidade em vez de
    ficha nova — sem perder o nome recebido, o id externo, a turma do relatório
    nem os candidatos. É o que impede um nome truncado pelo relatório ("ANNA E")
    ou uma criança de outra unidade de nascer como ficha ativa, sem RA e sem
    nascimento, já pesando no ranking e na régua da escola.

    Não toca em nenhum dado já gravado e não recalcula nada: vale da próxima
    sincronização em diante. O caminho da Lista Piloto segue criando — ele é a
    fonte. Governança igual à da fórmula: só Admin Global."""
    anterior = politica_sync.obter(db, escola_id)
    try:
        valores = politica_sync.definir(db, escola_id, dados.criar_aluno)
    except ValueError as erro:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(erro)) from erro
    registrar(db, "sincronizacao.politica_alterada", escola_id=escola_id,
              usuario_id=usuario.id, entidade="escola", entidade_id=escola_id,
              detalhes={"de": anterior, "para": valores,
                        "motivo": (dados.motivo or "").strip() or None})
    db.commit()
    return valores
