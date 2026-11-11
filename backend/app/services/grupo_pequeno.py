"""GRUPO PEQUENO: o que a Secretaria não vê nos números por turma (LGPD).

A Secretaria (``permissoes.e_secretaria``) agrega a rede e NUNCA vê dado
individual de criança. O resumo por turma é agregado e continua aberto a ela,
mas, com pouca adesão (comum no começo do piloto), uma turma com 1 ou 2 alunos
aferidos numa matéria entregava os números DAQUELA criança: a média de um aluno
é a nota dele, e a soma de um aluno são os livros, o tempo e as questões dele.

Regra, aplicada SÓ à Secretaria (a gestão da escola e o Admin Global veem tudo
como antes; o professor nem abre estas rotas):

1. PRIMÁRIA. Turma com 1 a ``K_MINIMO_TURMA - 1`` alunos aferidos numa matéria:
   a média e os indicadores DESSA matéria saem nulos, com o motivo
   ``"grupo_pequeno"``. A outra matéria da mesma turma segue visível se tiver
   alunos suficientes. A média geral da turma sai nula (com a outra matéria ela
   refaria a escondida).
2. COMPLEMENTAR. Esconder só a turma pequena não basta: o total da escola (o
   comparador e o painel da rede mostram) menos as turmas visíveis devolveria o
   número dela. Por isso, dentro da mesma série, da mesma condição de concorrer
   (as Fases não concorrem e ficam fora da média da escola) e da escola inteira,
   enquanto as turmas escondidas somarem de 1 a ``K_MINIMO_TURMA - 1`` alunos,
   a menor turma visível com dado também é escondida (motivo
   ``"complementar"``). É a mesma ideia da supressão complementar da análise
   educacional (``services/analise/plataformas.suprimir``, METODOLOGIA §3.5).

A decisão é da ESCOLA inteira e vale igual nas três rotas (resumo da escola,
ranking de turmas e comparador): decidir de novo em cada recorte abriria a conta
"total − visíveis" entre duas respostas.

A quantidade de alunos aferidos (``n_*``) e a adoção continuam visíveis: são
contagens de quem tem dado, não o desempenho de ninguém, e é com elas que a
tela explica "menos de 3 alunos com dado".

CONTRIBUINTES. Ter retrato não é somar no total: o import do relatório da turma
grava um retrato para cada linha, inclusive as zeradas. Numa turma de 20
retratos em que só 1 criança leu, os 20 "aferidos" passavam do k, e o total de
livros e o tempo eram os dela. Por isso conta também, por campo somado (os
``INDICADORES_DA_DIMENSAO``), quantas crianças têm o campo > 0; e, na média,
quantas têm nota > 0 (com 1 ou 2 e o resto em zero, média × n é a soma das
notas delas). Qualquer uma dessas contagens de 1 a k − 1 é grupo pequeno da
matéria inteira, como as outras. É o mesmo k sobre quem soma que a vitrine
pública (``rede._top_escolas``) já usava.

NÍVEL DA ESCOLA (painel e ranking da rede, lado "escola" do comparador). A
MESMA regra, um nível acima: a escola inteira com 1 a ``K_MINIMO_TURMA - 1``
alunos com dado numa matéria entregava, no cartão da rede e no comparador, o
número daquela criança (a média de um é a nota dele). Por escola e matéria
contam três populações, cada uma por trás de um grupo de números do cartão:

* ``media``: quem entra na MÉDIA (só quem concorre, com nota);
* ``indicadores``: todos os matriculados com dado (os totais brutos);
* ``concorrem``: quem concorre e tem dado (os totais e o per capita do ranking).

E, ao lado delas, os contribuintes (ver acima): ``media_positiva`` (da média,
quem tem nota > 0), ``contribuintes`` (de todos, quem soma em cada campo) e
``contribuintes_concorrem`` (de quem concorre, nos campos do per capita).

Qualquer uma de 1 a k − 1 esconde a matéria daquela escola inteira (média,
totais, per capita e índice), motivo ``"grupo_pequeno"``. Se só a DIFERENÇA
"todos − quem concorre" (as turmas que não concorrem, Educação Infantil) fica
de 1 a k − 1, nos retratos ou nos contribuintes de um campo, o cartão, que traz
os dois totais, entregaria a soma delas: saem só os totais de TODOS (motivo
``"complementar"``, ``parcial``), e a média e os números de quem concorre
continuam.

Na REDE não há supressão complementar entre escolas: para a Secretaria, a
matéria escondida de uma escola fica FORA dos totais, das médias ponderadas e
da régua do índice da rede (``services/rede.py``). Somar a escola escondida no
total da rede e escondê-la só no cartão não protegeria ninguém: o total menos
as escolas visíveis (e, das que fossem escondidas por complemento, a soma das
turmas delas, que o resumo da escola mostra) devolveria a criança.
"""
from __future__ import annotations

import re
import unicodedata

from sqlalchemy.orm import Session

from app.models import Escola, Usuario
from app.services import elegibilidade, permissoes
from app.services import evolucao as svc_evolucao

# Mínimo de alunos AFERIDOS numa matéria para a Secretaria ver a média e os
# indicadores da turma nessa matéria. Abaixo de 3, o número é o de uma criança
# (1 aluno) ou, para quem conhece o de uma, o da outra (2 alunos). A análise
# educacional usa 5 (``services.analise.K_MINIMO``) para escola × série; aqui o
# recorte é a turma, e 3 é o mínimo combinado para esta correção.
K_MINIMO_TURMA = 3

MOTIVO_GRUPO_PEQUENO = "grupo_pequeno"
MOTIVO_COMPLEMENTAR = "complementar"

# "Com resultado acima de zero" é o caso dos CONTRIBUINTES: 20 alunos com dado e
# só 1 que leu (ou com nota > 0). Sem ele, o texto contradiria a contagem de
# alunos com dado que a tela mostra ao lado.
_OU_POUCOS_ACIMA_DE_ZERO = f"(ou só 1 ou {K_MINIMO_TURMA - 1} com resultado acima de zero)"

TEXTOS = {
    MOTIVO_GRUPO_PEQUENO: (
        f"Menos de {K_MINIMO_TURMA} alunos com dado nesta matéria "
        f"{_OU_POUCOS_ACIMA_DE_ZERO}: para proteger as crianças, a média e os totais "
        "da turma não aparecem."),
    MOTIVO_COMPLEMENTAR: (
        f"Oculto para proteger outra turma com menos de {K_MINIMO_TURMA} alunos com "
        "dado: com este número e o total da escola daria para descobrir o dela."),
}

DIMENSOES = tuple(svc_evolucao.DIMENSOES)

# Chaves do resumo da turma que carregam a MÉDIA de cada matéria (a histórica e
# a da Arquitetura 2 são o mesmo número).
MEDIAS_DA_DIMENSAO = {
    "leitura": ("media_leitura", "media_elefante"),
    "matematica": ("media_matematica", "media_matific"),
}
# Indicadores (``evolucao._indicadores_atuais``) que saem do snapshot de cada
# plataforma: somas (e a média do Matific) das crianças da turma. São também os
# campos cujos CONTRIBUINTES (quem tem o campo > 0) a decisão conta.
INDICADORES_DA_DIMENSAO = svc_evolucao.CAMPOS_DOS_INDICADORES
# Os que o cartão da rede soma também só de quem concorre (``rede._kpis_da_rede``).
CAMPOS_DO_PER_CAPITA = svc_evolucao.CAMPOS_DO_PER_CAPITA
# Ordem fixa das colunas de contribuintes de uma turma em ``decidir``.
_COLUNAS_CONTRIBUINTES = {d: ("nota", *campos)
                          for d, campos in INDICADORES_DA_DIMENSAO.items()}
# Chave do bloco ``notas`` do comparador para cada matéria.
NOTA_DO_COMPARADOR = {"leitura": "elefante", "matematica": "matific"}


# Os mesmos motivos, ditos da ESCOLA (painel e ranking da rede, comparador).
TEXTOS_ESCOLA = {
    MOTIVO_GRUPO_PEQUENO: (
        f"Menos de {K_MINIMO_TURMA} alunos com dado nesta matéria na escola "
        f"{_OU_POUCOS_ACIMA_DE_ZERO}: para proteger as crianças, a média e os totais "
        "não aparecem."),
    MOTIVO_COMPLEMENTAR: (
        "Totais da escola ocultos para proteger as turmas que não concorrem "
        f"(Educação Infantil), com menos de {K_MINIMO_TURMA} alunos com dado nesta "
        f"matéria {_OU_POUCOS_ACIMA_DE_ZERO}: a média e os números de quem concorre "
        "continuam aparecendo."),
}
# Totais da REDE que deixam de fora as matérias escondidas das escolas. Saem os números
# da matéria (``rede.CAMPOS_DA_MATERIA_NO_CARTAO``: livros, tempo, atividades, estrelas e
# as médias); as CONTAGENS ficam no cartão de propósito (``rede.CONTAGENS_NO_CARTAO``,
# ``alunos_com_dados`` e a adoção) e a rede as soma — o texto diz as duas coisas.
TEXTO_FORA_DOS_TOTAIS_DA_REDE = (
    f"Escolas com menos de {K_MINIMO_TURMA} alunos com dado numa matéria "
    f"{_OU_POUCOS_ACIMA_DE_ZERO} ficam fora "
    "dos livros, do tempo de leitura, das atividades, das estrelas e das médias da rede "
    "nessa matéria, para proteger as crianças. As contagens de alunos com dados e a adoção "
    "continuam contando essas escolas.")


def _bloco_oculto(motivo: str | None) -> dict | None:
    return {"motivo": motivo, "texto": TEXTOS[motivo]} if motivo else None


def bloco_oculto_escola(motivo: str | None) -> dict | None:
    """Marca ``oculto`` de UMA matéria da escola. ``parcial``: só os totais de
    todos os matriculados saíram (a média e os números de quem concorre ficam)."""
    if not motivo:
        return None
    return {"motivo": motivo, "texto": TEXTOS_ESCOLA[motivo],
            "parcial": motivo == MOTIVO_COMPLEMENTAR}


# --- Decisão ------------------------------------------------------------------

def _serie(ano_escolar: str | None) -> tuple:
    """Chave da SÉRIE para a supressão complementar. O rótulo é texto livre:
    '4º Ano', '4° ano' e '4ºB' são a mesma série, e agrupar pelo texto cru os
    separava (o total da série menos as turmas visíveis voltava a entregar a
    turma pequena). A série é ``elegibilidade.ano_premiavel``, a mesma da análise
    educacional; o que não é série premiável (as Fases) fica pelo rótulo
    NORMALIZADO (``_rotulo_normalizado``): '1ª Fase', '1° Fase' e '1a fase',
    '6º Ano' e '6° ano', ou 'Pré I' e 'pre i', são a mesma série."""
    ano = elegibilidade.ano_premiavel(ano_escolar)
    return ("ano", ano) if ano is not None else ("rotulo", _rotulo_normalizado(ano_escolar))


def _rotulo_normalizado(ano_escolar: str | None) -> str:
    """O rótulo livre da turma sem as variações de digitação que não mudam a
    série: caixa, espaços repetidos, acentos ('Pré I' e 'pre i') e QUALQUER
    marcador ordinal logo depois do número, reduzido a um só: 'º', 'ª' e '°'
    (grau, com ou sem espaço antes) e 'o'/'a' colados ao número. '1° Fase' (o
    grau no ordinal feminino é erro comum) cai com '1ª Fase' e '1a fase'.

    O '°' não é letra, e um ``\\b`` depois dele não casa ('1° fase' ficaria de
    fora); por isso só o 'o'/'a' exige o fim da palavra. E só ele vem colado ao
    número: '1 a' pode ser a letra da turma. A chave é interna: o NFKD ainda
    troca o 'º' por 'o', igual para todas as variações."""
    texto = " ".join((ano_escolar or "").casefold().split())
    texto = re.sub(r"(\d)(?:\s*[º°ª]|[oa]\b)", r"\1º", texto)
    return "".join(c for c in unicodedata.normalize("NFKD", texto)
                   if not unicodedata.combining(c))


def _completar(membros: list[int], contagens: dict[int, tuple[int, ...]],
               motivos: dict[int, dict[str, str | None]], dimensao: str,
               ordem: dict[int, int], k: int) -> None:
    """Supressão complementar num grupo de turmas (série, condição de concorrer
    ou escola): enquanto as escondidas somarem de 1 a k − 1 alunos numa coluna
    (média, retratos ou contribuintes de um campo), esconde a menor turma
    visível que TEM alguém nessa coluna. Esconder uma turma sem ninguém na
    coluna em falta não muda a soma dela; e, se nenhuma visível tem, o total
    do grupo nessa coluna já é o das escondidas, de 1 a k − 1 crianças, e quem
    o esconde é a regra da escola (``decidir_escola``), na mesma contagem."""
    def em_falta() -> list[int]:
        escondidas = [t for t in membros if motivos[t][dimensao]]
        somas = [sum(coluna) for coluna in zip(*(contagens[t] for t in escondidas))]
        return [i for i, s in enumerate(somas) if 0 < s < k]

    while colunas := em_falta():
        candidatas = [t for t in membros if not motivos[t][dimensao]
                      and any(contagens[t][i] for i in colunas)]
        if not candidatas:
            return
        turma_id = min(candidatas, key=lambda t: (max(contagens[t]), ordem[t]))
        motivos[turma_id][dimensao] = MOTIVO_COMPLEMENTAR


def _colunas_da_turma(item: dict, dimensao: str) -> tuple[int, ...]:
    """As contagens de uma turma numa matéria, na ordem fixa: alunos da média
    (``n_*``), retratos (``_aferidos``) e contribuintes (``_contribuintes``:
    nota > 0 e cada indicador > 0). Chave ausente = 0."""
    contribuintes = (item.get("_contribuintes") or {}).get(dimensao) or {}
    return (int(item.get("n_" + dimensao) or 0),
            int((item.get("_aferidos") or {}).get(dimensao) or 0),
            *(int(contribuintes.get(c) or 0) for c in _COLUNAS_CONTRIBUINTES[dimensao]))


def decidir(turmas: list[dict], premiaveis: set[int],
            k: int = K_MINIMO_TURMA) -> dict[int, dict[str, str | None]]:
    """{turma_id: {dimensão: motivo | None}} para as turmas de ``resumo_escola``
    (pedido com ``com_contagem_aferidos=True``). Função pura: só as contagens.

    Por turma e matéria contam os alunos da MÉDIA (``n_*``), os dos INDICADORES
    (``_aferidos``) e os CONTRIBUINTES (``_contribuintes``: quem tem nota > 0 e
    quem tem cada indicador > 0). Os dois primeiros coincidem depois do
    recálculo; antes dele o segundo pode ser maior. Qualquer um deles de 1 a
    k − 1 já entrega uma criança."""
    ordem = {t["turma"]["id"]: i for i, t in enumerate(turmas)}
    motivos: dict[int, dict[str, str | None]] = {
        tid: dict.fromkeys(DIMENSOES) for tid in ordem}
    serie = {t["turma"]["id"]: _serie(t["turma"].get("ano_escolar")) for t in turmas}
    niveis = (
        lambda tid: ("serie", serie[tid]),          # total por série
        lambda tid: ("concorre", tid in premiaveis),  # média da escola (só quem concorre)
        lambda tid: ("escola",),                     # totais da escola inteira
    )
    for dimensao in DIMENSOES:
        contagens = {t["turma"]["id"]: _colunas_da_turma(t, dimensao) for t in turmas}
        for tid, ns in contagens.items():
            if any(0 < n < k for n in ns):
                motivos[tid][dimensao] = MOTIVO_GRUPO_PEQUENO
        for chave in niveis:
            grupos: dict[tuple, list[int]] = {}
            for tid in ordem:
                grupos.setdefault(chave(tid), []).append(tid)
            for membros in grupos.values():
                _completar(membros, contagens, motivos, dimensao, ordem, k)
    return motivos


def decidir_escola(contagens: dict[str, dict[str, int]],
                   k: int = K_MINIMO_TURMA) -> dict[str, str | None]:
    """{dimensão: motivo | None} de UMA escola. Função pura: só as contagens.

    ``contagens[dimensão]`` = ``{"media": n, "indicadores": n, "concorrem": n,
    "media_positiva": n, "contribuintes": {campo: n},
    "contribuintes_concorrem": {campo: n}}`` (ver a docstring do módulo; as três
    últimas são opcionais). ``"grupo_pequeno"`` esconde a matéria inteira;
    ``"complementar"`` esconde só os totais de todos os matriculados."""
    motivos: dict[str, str | None] = {}
    for dimensao in DIMENSOES:
        c = contagens.get(dimensao) or {}
        media, positiva, todos, concorrem = (
            int(c.get(chave) or 0)
            for chave in ("media", "media_positiva", "indicadores", "concorrem"))
        somam = {campo: int(n or 0) for campo, n in (c.get("contribuintes") or {}).items()}
        somam_concorrem = {campo: int(n or 0) for campo, n
                           in (c.get("contribuintes_concorrem") or {}).items()}
        pequenos = (media, positiva, todos, concorrem,
                    *somam.values(), *somam_concorrem.values())
        # "Todos − quem concorre", nos retratos e em cada campo que as duas
        # populações somam (o cartão traz os dois totais).
        diferencas = (todos - concorrem,
                      *(somam[campo] - somam_concorrem[campo]
                        for campo in somam if campo in somam_concorrem))
        if any(0 < n < k for n in pequenos):
            motivos[dimensao] = MOTIVO_GRUPO_PEQUENO
        elif any(0 < n < k for n in diferencas):
            motivos[dimensao] = MOTIVO_COMPLEMENTAR
        else:
            motivos[dimensao] = None
    return motivos


def _tirar_contagens(item: dict) -> None:
    """Tira as chaves internas de contagem de uma linha ou de um lado."""
    item.pop("_aferidos", None)
    item.pop("_contribuintes", None)


def decisao_da_escola(db: Session, escola_id: int) -> tuple[dict, dict[int, dict]]:
    """(resumo da escola SEM as chaves internas, decisão por turma)."""
    resumo = svc_evolucao.resumo_escola(db, escola_id, com_contagem_aferidos=True)
    escola = db.get(Escola, escola_id)
    premiaveis = set(elegibilidade.turmas_premiaveis(db, escola_id, escola.ano_letivo_ativo))
    motivos = decidir(resumo["turmas"], premiaveis)
    for item in resumo["turmas"]:
        _tirar_contagens(item)
    return resumo, motivos


# --- Aplicação ----------------------------------------------------------------

def ocultar_turma(item: dict, motivos: dict[str, str | None]) -> None:
    """Anula, numa linha de ``resumo_escola``, a média e os indicadores de cada
    matéria escondida e põe as marcas (``grupo_pequeno`` e ``oculto``)."""
    for dimensao, motivo in motivos.items():
        if not motivo:
            continue
        for chave in MEDIAS_DA_DIMENSAO[dimensao]:
            item[chave] = None
        for chave in INDICADORES_DA_DIMENSAO[dimensao]:
            if chave in item["indicadores"]:
                item["indicadores"][chave] = None
    if any(motivos.values()):
        item["media_geral"] = None
    item["grupo_pequeno"] = MOTIVO_GRUPO_PEQUENO in motivos.values()
    item["oculto"] = {d: _bloco_oculto(motivos.get(d)) for d in DIMENSOES}


def resumo_escola_do_usuario(db: Session, escola_id: int, usuario: Usuario) -> dict:
    """``resumo_escola`` como o usuário pode vê-lo: para a Secretaria, com os
    grupos pequenos escondidos; para os demais, exatamente o resumo de sempre."""
    if not permissoes.e_secretaria(usuario):
        return svc_evolucao.resumo_escola(db, escola_id)
    resumo, motivos = decisao_da_escola(db, escola_id)
    for item in resumo["turmas"]:
        ocultar_turma(item, motivos.get(item["turma"]["id"], dict.fromkeys(DIMENSOES)))
    return resumo


def _motivos_fora_da_escola(lado: dict, k: int = K_MINIMO_TURMA) -> dict[str, str | None]:
    """Turma fora do resumo da escola (de outro ano letivo), decidida sozinha:
    esconde a matéria que tem algum número e menos de k alunos na média (regra
    conservadora, de quando não há a contagem dos indicadores) e, se o lado
    TURMA trouxe as contagens internas (``_aferidos``/``_contribuintes``), também
    a que tem de 1 a k − 1 crianças nos retratos ou nos contribuintes."""
    motivos: dict[str, str | None] = {}
    for dimensao in DIMENSOES:
        n = int((lado["dimensoes"].get(dimensao) or {}).get("n_aferidos") or 0)
        tem_numero = n > 0 or any(lado["indicadores"].get(c)
                                  for c in INDICADORES_DA_DIMENSAO[dimensao])
        colunas = _colunas_da_turma(
            {"n_" + dimensao: n, "_aferidos": lado.get("_aferidos"),
             "_contribuintes": lado.get("_contribuintes")}, dimensao)
        pequeno = (tem_numero and n < k) or any(0 < c < k for c in colunas)
        motivos[dimensao] = MOTIVO_GRUPO_PEQUENO if pequeno else None
    return motivos


def ocultar_lado_turma(lado: dict, motivos: dict[str, str | None]) -> None:
    """O mesmo de ``ocultar_turma`` para um lado TURMA do comparador."""
    for dimensao, motivo in motivos.items():
        if not motivo:
            continue
        for chave in INDICADORES_DA_DIMENSAO[dimensao]:
            if chave in lado["indicadores"]:
                lado["indicadores"][chave] = None
        bloco = lado["dimensoes"].get(dimensao)
        if bloco is not None:
            bloco["nota"] = None
            bloco["oculto"] = _bloco_oculto(motivo)
        lado["notas"][NOTA_DO_COMPARADOR[dimensao]] = None
    if any(motivos.values()):
        lado["notas"]["geral"] = None
    lado["grupo_pequeno"] = MOTIVO_GRUPO_PEQUENO in motivos.values()
    lado["oculto"] = {d: _bloco_oculto(motivos.get(d)) for d in DIMENSOES}


def ocultar_lado_escola(lado: dict, motivos: dict[str, str | None]) -> None:
    """Lado ESCOLA do comparador (``evolucao._lado_escola``): a matéria escondida
    sai com a nota e os indicadores nulos; a ``complementar`` só com os
    indicadores (totais de todos os matriculados) nulos. A ``geral`` passa a ser
    a média das matérias VISÍVEIS com dado (a mesma régua de ``_lado_escola``,
    sem o número escondido); nula se nenhuma sobra."""
    for dimensao, motivo in motivos.items():
        if not motivo:
            continue
        for chave in INDICADORES_DA_DIMENSAO[dimensao]:
            if chave in lado["indicadores"]:
                lado["indicadores"][chave] = None
        bloco = lado["dimensoes"].get(dimensao)
        if motivo == MOTIVO_GRUPO_PEQUENO:
            if bloco is not None:
                bloco["nota"] = None
            lado["notas"][NOTA_DO_COMPARADOR[dimensao]] = None
        if bloco is not None:
            bloco["oculto"] = bloco_oculto_escola(motivo)
    if MOTIVO_GRUPO_PEQUENO in motivos.values():
        visiveis = [b["nota"] for b in lado["dimensoes"].values()
                    if b.get("nota") is not None and b.get("n_aferidos")]
        lado["notas"]["geral"] = (round(sum(visiveis) / len(visiveis), 1)
                                  if visiveis else None)
    lado["grupo_pequeno"] = MOTIVO_GRUPO_PEQUENO in motivos.values()
    lado["oculto"] = {d: bloco_oculto_escola(motivos.get(d)) for d in DIMENSOES}


def _motivos_do_lado_escola(lado: dict) -> dict[str, str | None]:
    """Decisão do lado ESCOLA pelas contagens que ``_lado_escola`` anexou
    (``_aferidos``, pedido com ``com_contagem_aferidos=True``). Sem elas (não
    deveria acontecer para a Secretaria), a regra conservadora das turmas de
    fora do resumo: esconde a matéria com número e menos de k na média."""
    contagens = lado.pop("_aferidos", None)
    if contagens is None:
        return _motivos_fora_da_escola(lado)
    return decidir_escola(contagens)


def proteger_comparacao(db: Session, escola_id: int, usuario: Usuario,
                        resultado: dict) -> dict:
    """Esconde, para a Secretaria, os grupos pequenos dos lados TURMA (com a
    MESMA decisão do resumo da escola) e ESCOLA (com a regra da escola, a mesma
    do cartão da rede) do comparador. Outros perfis e o lado aluno não mudam."""
    lados = [resultado[c] for c in ("a", "b")]
    if not permissoes.e_secretaria(usuario):
        for lado in lados:  # só vem com a flag da Secretaria; por garantia
            _tirar_contagens(lado)
        return resultado
    turmas = [lado for lado in lados if lado.get("tipo") == "turma"]
    if turmas:
        _resumo, motivos = decisao_da_escola(db, escola_id)
        for lado in turmas:
            decisao = (motivos[lado["id"]] if lado["id"] in motivos
                       else _motivos_fora_da_escola(lado))
            _tirar_contagens(lado)
            ocultar_lado_turma(lado, decisao)
    for lado in lados:
        if lado.get("tipo") == "escola":
            ocultar_lado_escola(lado, _motivos_do_lado_escola(lado))
    return resultado
