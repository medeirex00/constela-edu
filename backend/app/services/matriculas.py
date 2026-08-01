"""Núcleo PURO da importação da planilha de matrículas (Lista Piloto).

Aqui vive a lógica DIFÍCIL — casar cada linha da planilha com os cadastros já
existentes — sem SQLAlchemy, sem I/O e sem efeitos colaterais: recebe dados
simples (nomes, RA, tokens de turma, datas) e devolve DECISÕES. Assim a parte
que concentra a complexidade ciclomática (RA × nome-exato × abreviação
posicional, unicidade bipartida, vetos por turma/nascimento) fica testável
isoladamente.

O router (`routers/importacoes.py`) faz só a cola impura: carrega o estado do
banco para estas estruturas, chama estas funções e aplica o resultado.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from app.services import importacao as svc

# Tokens que aparecem em QUALQUER turma e não discriminam uma da outra — ficam
# de fora do overlap, senão "1º Ano A" e "4º Ano A" pareceriam a mesma sala
# (partilham "ano"; o que importa é série + letra).
_STOP_TURMA = frozenset({
    "ano", "anos", "manha", "tarde", "noite", "integral", "anual",
    "matutino", "vespertino", "noturno", "turma", "sala",
})


# ---------------------------------------------------------------------------
# Valores de entrada (imutáveis, sem ORM)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AlunoRef:
    """Visão mínima de um aluno JÁ existente, para o casamento em memória."""
    id: int
    nome: str
    data_nascimento: date | None = None
    # Tokens de cada turma do aluno (de QUALQUER ano) — para o overlap de sala.
    turmas_tokens: tuple[frozenset[str], ...] = ()


@dataclass(frozen=True)
class LinhaMatricula:
    """Uma linha da planilha já resolvida à sua turma (do ano ativo)."""
    nome: str
    ra: str | None            # RA já normalizado (ra_util); None se ausente
    nascimento: date | None
    turma_id: int
    turma_tokens: frozenset[str]


@dataclass(frozen=True)
class ContextoCasamento:
    """Índices do estado da escola consultados pelo casamento (só leitura)."""
    # RA normalizado → aluno (para casar por RA, o mais forte).
    por_ra: dict[str, AlunoRef] = field(default_factory=dict)
    # (nome normalizado, turma_id) → aluno já matriculado naquela turma no ano.
    por_nome_turma: dict[tuple[str, int], AlunoRef] = field(default_factory=dict)
    # 1º token do nome → candidatos do POOL (cadastros de upload, sem RA).
    pool_por_primeiro: dict[str, tuple[AlunoRef, ...]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Predicados puros (compartilháveis com o router e a análise)
# ---------------------------------------------------------------------------

def normalizar(texto: str) -> str:
    return svc.normalizar_nome(texto or "")


_TURNO_COD = {"manha": "M", "tarde": "T", "noite": "N", "integral": "I"}
_TURNO_TXT = {
    "matutino": "manha", "manha": "manha", "tarde": "tarde", "vespertino": "tarde",
    "noturno": "noite", "noite": "noite", "integral": "integral",
}
# número da série + ordinal opcional + 'ano/série' opcional + LETRA ISOLADA da
# sala (\b…\b — 1 caractere, p/ NÃO capturar o "A" de "ANUAL").
_RE_CANON = re.compile(r"(\d+)\s*[ºªo°]?\s*(?:ano|serie)?\s*\b([a-z])\b", re.IGNORECASE)


def chave_canonica(nome: str, ano_escolar: str = "", turno: str | None = None) -> str:
    """Identidade CANÔNICA de uma turma, reconhecendo a MESMA sala escrita de
    formas diferentes: "1 ANO A TARDE ANUAL (300302821)" e "1ºA" (turno tarde)
    → ambos ``"1|A|T"`` (série · letra · turno). Reune número da série + letra
    da sala + turno (do campo `turno`, senão inferido do texto do nome). É
    CONSERVADORA: nomes sem o padrão número+letra (Maternal, Pré, EJA, AEE,
    Multisseriado…) caem no nome normalizado e nunca são fundidos por engano;
    turnos diferentes (1ºA manhã ≠ 1ºA tarde) geram chaves diferentes."""
    # Tira o código (SED) entre () e troca o ordinal (º ª °) por espaço — senão
    # "1ºA" cola o º no "A" e o \b da letra não casa.
    limpo = re.sub(r"[ºª°]", " ", re.sub(r"\(.*?\)", " ", nome or ""))
    base = normalizar(limpo)
    m = _RE_CANON.search(base) or _RE_CANON.search(normalizar(re.sub(r"[ºª°]", " ", ano_escolar or "")))
    ano_num = m.group(1) if m else ""
    letra = m.group(2).upper() if m else ""
    t = (turno or "").strip().lower()                          # 1º: campo/metadado 'Turno:'
    if t not in _TURNO_COD:                                    # 2º: inferir do próprio nome
        t = next((v for k, v in _TURNO_TXT.items() if k in base.split()), "")
    if not ano_num and not letra:
        return base                                            # formato desconhecido: não funde
    return f"{ano_num}|{letra}|{_TURNO_COD.get(t, '')}"


def codigo_externo_do_nome(nome: str) -> str:
    """Extrai o código da sala entre parênteses do nome do relatório (nº SED/
    Censo): "4 ANO C INTEGRAL (300303525)" → "300303525". "" se não houver."""
    m = re.search(r"\((\d{3,})\)", nome or "")
    return m.group(1) if m else ""


def _espacar_serie_letra(nome: str) -> str:
    """Separa a série da letra quando vierem GRUDADAS ("1A"→"1 A", "4C"→"4 C"),
    para o compacto casar no mesmo padrão série+letra. Só afeta dígito seguido de
    UMA letra imediatamente (o código externo entre () não é tocado aqui)."""
    return re.sub(r"(\d)([A-Za-z])", r"\1 \2", nome or "")


def chave_turma_norm(nome: str) -> str:
    """chave_turma tolerante ao compacto "1A" (via _espacar_serie_letra)."""
    return chave_turma(_espacar_serie_letra(nome))


def nome_turma_exibicao(nome: str, ano_escolar: str = "", turno: str | None = None) -> str:
    """Nome VISÍVEL, curto e normalizado da turma: "1 ANO A TARDE ANUAL
    (300302821)" → "1ºA"; "4ºC" → "4ºC"; "4 C" → "4ºC"; "1A" → "1ºA". Formatos
    sem série+letra (Maternal, Pré, EJA, AEE, Multisseriado) caem no nome limpo
    (sem o código, espaços colapsados, Capitalizado) — nunca são forçados a um
    padrão que não têm. O código externo NUNCA entra aqui (vai para
    Turma.codigo_externo)."""
    k = chave_canonica(_espacar_serie_letra(nome), ano_escolar, turno)
    if "|" in k:
        num, letra, _t = k.split("|")
        if num and letra:
            return f"{num}º{letra}"                 # letra já vem em CAIXA ALTA
    limpo = re.sub(r"\s+", " ", re.sub(r"\(.*?\)", " ", nome or "")).strip()
    return limpo.title() or (nome or "").strip()


def turno_codigo(turno: str | None) -> str:
    """Código do turno a partir do CAMPO `turno` (sinal FORTE/confiável): um de
    ``M/T/N/I``, ou ``""`` se vazio/desconhecido. Normaliza acento e caixa (o
    campo real vem "Manhã"/"Tarde") e aceita matutino/vespertino/noturno. É o
    turno em que a consolidação de turmas deve confiar."""
    t = normalizar(turno or "").strip()          # tira acento e caixa ("Manhã"→"manha")
    t = _TURNO_TXT.get(t, t)
    return _TURNO_COD.get(t, "")


def turno_do_nome(nome: str) -> str:
    """Código do turno INFERIDO do NOME (sinal FRACO): ``M/T/N/I`` ou ``""``. Os
    nomes administrativos do SED trazem um turno nominal que muitas vezes está
    ERRADO ("2 ANO A INTEGRAL"/"3 ANO A MANHA" numa escola de tarde), então isto
    só deve ser usado quando não há turno no campo de nenhuma turma da sala."""
    base = normalizar(re.sub(r"\(.*?\)", " ", nome or ""))
    for palavra in base.split():
        alvo = _TURNO_TXT.get(palavra)
        if alvo:
            return _TURNO_COD[alvo]
    return ""


def chave_turma(nome: str) -> str:
    """Chave de casamento de turma na IMPORTAÇÃO (só o NOME está disponível). Usa
    apenas SÉRIE + LETRA — o turno embutido no NOME é RUÍDO não confiável: o SED
    grava "2 ANO A INTEGRAL"/"3 ANO A MANHA" mesmo quando a sala real é de outro
    turno, e isso fazia a importação criar uma turma SEPARADA (a duplicata). O
    turno REAL vive no CAMPO `turno` e é tratado na consolidação (turmas_dedup).
    Assim "2ºA", "2 ANO A INTEGRAL (cod)" e "2 ANO A MANHA" casam na MESMA turma.
    Formatos fora do padrão série+letra caem no nome normalizado (não fundem)."""
    k = chave_canonica(nome)
    if "|" not in k:
        return k
    num, letra, _turno = k.split("|")
    return f"{num}|{letra}"


def overlap_turma(a: frozenset[str] | set[str], b: frozenset[str] | set[str]) -> int:
    """Tokens de turma em comum, ignorando palavras ubíquas — para "1º Ano A"
    casar com "1 ANO A MANHÃ" (série+letra) mas NÃO com "4º Ano A"."""
    return len((set(a) & set(b)) - _STOP_TURMA)


def nomes_compativeis(a: str, b: str) -> bool:
    """Dois nomes podem ser a MESMA pessoa? Veto ao casar por RA: se o RA colide
    mas os nomes são claramente de pessoas diferentes (RA placeholder), não
    casa. Conservador: na dúvida, considera compatível."""
    if normalizar(a) == normalizar(b):
        return True
    ta, tb = svc.tokens_nome(a), svc.tokens_nome(b)
    if not ta or not tb:
        return True
    if ta[0] != tb[0]:
        return False
    if svc.casa_abreviado_posicional(ta, tb) or svc.casa_abreviado_posicional(tb, ta):
        return True
    return svc._similaridade(normalizar(a), normalizar(b)) >= 0.6


def parse_nascimento(iso: str | None) -> date | None:
    """'YYYY-MM-DD' → date; None se vazio/ inválido (nunca levanta exceção)."""
    if not iso:
        return None
    try:
        return date.fromisoformat(iso)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Casamento (o coração)
# ---------------------------------------------------------------------------

def casa_forte(linha: LinhaMatricula, ctx: ContextoCasamento) -> bool:
    """A linha já casa por RA (com nome compatível) ou por nome-exato na turma?
    Quando SIM, não entra no casamento abreviado (que é o caminho ambíguo)."""
    if (linha.ra and linha.ra in ctx.por_ra
            and nomes_compativeis(linha.nome, ctx.por_ra[linha.ra].nome)):
        return True
    return (normalizar(linha.nome), linha.turma_id) in ctx.por_nome_turma


def candidatos_abreviados(linha: LinhaMatricula, ctx: ContextoCasamento) -> list[AlunoRef]:
    """Cadastros do pool cujo nome ABREVIADO posicional bate com esta linha,
    na MESMA turma (overlap série+letra) e sem nascimento divergente."""
    tokens = svc.tokens_nome(linha.nome)
    if len(tokens) < 2:
        return []
    achados: list[AlunoRef] = []
    for antigo in ctx.pool_por_primeiro.get(tokens[0], ()):
        if not svc.casa_abreviado_posicional(svc.tokens_nome(antigo.nome), tokens):
            continue
        # Precisa bater com ALGUMA turma real do aluno (série+letra), não com a
        # união de turmas de anos diferentes.
        if not any(overlap_turma(linha.turma_tokens, ts) >= 2
                   for ts in antigo.turmas_tokens):
            continue
        if (linha.nascimento and antigo.data_nascimento
                and linha.nascimento != antigo.data_nascimento):
            continue                      # veto por nascimento divergente
        achados.append(antigo)
    return achados


def aviso_ambiguidade(nome_linha: str, nomes_candidatos: str) -> str:
    return (f"“{nome_linha}” pode ser o mesmo aluno de: {nomes_candidatos} "
            "(cadastro(s) de importação anterior). Criado como novo — confira "
            "em Alunos e use “Fundir alunos” se for a mesma pessoa.")


def casar_abreviados(
    linhas: list[LinhaMatricula], ctx: ContextoCasamento,
) -> tuple[dict[int, int], list[str]]:
    """Resolve o casamento abreviado de TODO o lote com unicidade BIPARTIDA.

    Devolve (casamentos, avisos):
      * casamentos: índice da linha → id do aluno existente, SÓ quando 1:1
        inequívoco (a linha tem um único candidato E esse candidato não
        abrevia nenhuma outra linha do lote);
      * avisos: mensagem por linha ambígua (vira aluno novo).
    """
    candidatos_por_idx: dict[int, list[AlunoRef]] = {}
    usos_por_aluno: dict[int, list[int]] = {}   # aluno_id → índices que o citam
    for idx, linha in enumerate(linhas):
        if casa_forte(linha, ctx):
            continue
        cands = candidatos_abreviados(linha, ctx)
        if not cands:
            continue
        candidatos_por_idx[idx] = cands
        for c in cands:
            usos_por_aluno.setdefault(c.id, []).append(idx)

    casamentos: dict[int, int] = {}
    avisos: list[str] = []
    for idx, cands in candidatos_por_idx.items():
        if len(cands) == 1 and len(usos_por_aluno[cands[0].id]) == 1:
            casamentos[idx] = cands[0].id
        else:
            nomes = ", ".join(sorted({c.nome for c in cands}))
            avisos.append(aviso_ambiguidade(linhas[idx].nome, nomes))
    return casamentos, avisos
