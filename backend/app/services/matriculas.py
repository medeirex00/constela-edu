"""Núcleo PURO da importação da planilha de matrículas (Lista Piloto).

Aqui vive a lógica DIFÍCIL — casar cada linha da planilha com os cadastros já
existentes — sem SQLAlchemy, sem I/O e sem efeitos colaterais: recebe dados
simples (nomes, RA, chave de sala, datas) e devolve DECISÕES. Assim a parte que
concentra a complexidade ciclomática (RA × roster da sala × mudança de sala ×
vetos de identidade) fica testável isoladamente.

O router (`routers/importacoes.py`) faz só a cola impura: carrega o estado do
banco para estas estruturas, chama ``resolver_linha`` e aplica o resultado.

PORTA ÚNICA (correção da 4ª causa raiz das duplicatas, 2026-08-11): a Lista
Piloto tinha um SEGUNDO motor de identidade — índices próprios (RA, nome EXATO
+ turma, "abreviado posicional" contra um pool restrito a cadastros de upload) e
um ramo que criava a ficha quando os três falhavam. Quem chegasse com variação
de grafia e sem RA virava uma segunda ficha, calada. Agora a decisão é do MOTOR
ÚNICO (``services.matching``), o mesmo dos imports de plataforma, do cadastro
manual e da detecção de duplicatas: reusa quando é seguro, manda para REVISÃO
quando é inseguro/ambíguo (não cria) e só cria quando não há candidato.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import date

from app.services import importacao as svc
from app.services import matching

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
class LinhaMatricula:
    """Uma linha da planilha já resolvida à sua turma (do ano ativo).

    ``chave_sala`` é a identidade CANÔNICA da sala (``chave_turma``: série+letra),
    não o id da turma: a MESMA sala pode ter mais de uma linha em ``turmas``
    (o Matific/Elefante cria "1 ANO A MANHA (300…)" e a Lista Piloto, "1ºA"), e
    identidade de aluno não pode depender de qual das linhas de turma o registro
    caiu."""
    nome: str
    ra: str | None            # RA já normalizado (ra_util); None se ausente
    nascimento: date | None
    turma_id: int
    chave_sala: str
    chamada: int | None = None


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


def nome_menos_informativo(novo: str, atual: str) -> bool:
    """O nome `novo` é uma versão ENCURTADA do `atual` (abreviação posicional ou
    subconjunto de tokens)? "MARIA E. SILVA" contra "MARIA EDUARDA SILVA" → True.

    A planilha é a fonte da verdade do nome, mas NUNCA para encurtar: gravar a
    abreviação por cima do nome completo degrada a identidade e enfraquece o
    casamento das importações seguintes — é assim que a MESMA criança volta a
    ficar irreconhecível e ganha uma segunda ficha depois."""
    tn, ta = svc.tokens_nome(novo), svc.tokens_nome(atual)
    if not tn or not ta or set(tn) == set(ta):
        return False
    return svc.casa_abreviado(tn, ta) or set(tn) < set(ta)


def nomes_compativeis(a: str, b: str) -> bool:
    """Dois nomes podem ser a MESMA pessoa? Veto ao casar por RA: se o RA colide
    mas os nomes são claramente de pessoas diferentes (RA placeholder), não
    casa. Conservador: na dúvida, considera compatível."""
    if normalizar(a) == normalizar(b):
        return True
    ta, tb = svc.tokens_nome(a), svc.tokens_nome(b)
    if not ta or not tb:
        return True
    if svc.casa_abreviado(ta, tb) or svc.casa_abreviado(tb, ta):
        return True                       # abreviação/inicial/truncamento (motor único)
    if ta[0] != tb[0]:
        return False
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

# Decisão devolvida por ``resolver_linha`` — o MESMO vocabulário das outras
# portas de identidade (alta/média/baixa do ``_casar_no_roster``), sem sinônimos.
REUSAR = "reusar"       # correspondência SEGURA → reaproveita a ficha existente
REVISAR = "revisar"     # INSEGURA/ambígua → NÃO cria, NÃO altera: vai para revisão
CRIAR = "criar"         # ninguém plausível (ou identidade prova ser outra criança)


@dataclass(frozen=True)
class Decisao:
    acao: str                          # REUSAR | REVISAR | CRIAR
    aluno_id: int | None = None        # quem reusar (ou o melhor candidato da revisão)
    motivo: str = ""                   # ra|uuid|identificador|exato|abreviacao|…
    candidatos: tuple[int, ...] = ()   # todos os plausíveis (para o aviso/auditoria)


@dataclass
class ContextoCasamento:
    """Índices VIVOS do estado da escola (o casamento lê; a persistência
    ``registrar``-a de volta a cada linha gravada).

    São índices de IDENTIDADE, não de matrícula:
      * ``por_ra``      — RA normalizado → aluno da escola INTEIRA (inclusive
        arquivado/excluído: RA é identificador forte, reativa em vez de duplicar);
      * roster por SALA — quem está na sala (série+letra) do ano ativo; é o roster
        que o motor único recebe, o mesmo dos imports de plataforma;
      * índice por NOME — a escola inteira, para reconhecer MUDANÇA DE SALA
        (trocar de turma não faz de ninguém uma pessoa nova).
    """
    por_ra: dict[str, matching.Identidade] = field(default_factory=dict)
    _por_sala: dict[str, dict[int, matching.Identidade]] = field(default_factory=dict)
    _por_nome: dict[str, dict[int, matching.Identidade]] = field(default_factory=dict)
    _sala_de: dict[int, str] = field(default_factory=dict)
    _nome_de: dict[int, str] = field(default_factory=dict)

    def registrar(self, ident: matching.Identidade, chave_sala: str | None = None) -> None:
        """Insere/atualiza um aluno nos índices (idempotente por id). Chamar depois
        de criar OU de alterar (nome/chamada/sala) mantém as linhas seguintes do
        MESMO arquivo enxergando o estado real — é o que impede a 2ª linha de abrir
        uma 2ª ficha do aluno que a 1ª acabou de gravar."""
        if ident.id is None:
            return
        aid = ident.id
        sala_nova = chave_sala if chave_sala is not None else self._sala_de.get(aid)
        sala_velha = self._sala_de.get(aid)
        if sala_velha is not None and sala_velha != sala_nova:
            self._por_sala.get(sala_velha, {}).pop(aid, None)
        if sala_nova is not None:
            self._por_sala.setdefault(sala_nova, {})[aid] = ident
            self._sala_de[aid] = sala_nova
        nome_novo = normalizar(ident.nome)
        nome_velho = self._nome_de.get(aid)
        if nome_velho is not None and nome_velho != nome_novo:
            self._por_nome.get(nome_velho, {}).pop(aid, None)
        self._por_nome.setdefault(nome_novo, {})[aid] = ident
        self._nome_de[aid] = nome_novo
        if ident.ra:
            self.por_ra.setdefault(ident.ra, ident)

    def registrar_ra(self, ident: matching.Identidade) -> None:
        """Só o RA (usado por quem NÃO é candidato por nome — aluno excluído):
        o RA continua identificando (reativa), o nome não."""
        if ident.id is not None and ident.ra:
            self.por_ra.setdefault(ident.ra, ident)

    def roster(self, chave_sala: str) -> list[matching.Identidade]:
        return list(self._por_sala.get(chave_sala, {}).values())

    def sala_de(self, aluno_id: int) -> str | None:
        return self._sala_de.get(aluno_id)

    def mesmo_nome(self, nome: str) -> list[matching.Identidade]:
        return list(self._por_nome.get(normalizar(nome), {}).values())


def _sem_chamada(ident: matching.Identidade) -> matching.Identidade:
    """Cópia sem o nº de chamada. Chamada é numeração DA SALA: comparar a de salas
    diferentes não prova nem refuta nada (todo 1º da chamada de toda turma seria
    'a mesma criança', e todo aluno que muda de sala 'outra criança')."""
    return replace(ident, chamada=None)


def _identidade_da_linha(linha: LinhaMatricula) -> matching.Identidade:
    return matching.Identidade(nome=linha.nome, chamada=linha.chamada,
                               nascimento=linha.nascimento, ra=linha.ra or "")


def resolver_linha(linha: LinhaMatricula, ctx: ContextoCasamento) -> Decisao:
    """PORTA ÚNICA de identidade da Lista Piloto. Ordem (mais forte primeiro):

    1. **RA** — identificador forte e único na escola inteira (vale até para quem
       está arquivado/excluído: reativa em vez de duplicar). Vetado por
       ``nomes_compativeis`` quando o RA colide mas o nome é de outra pessoa
       (RA placeholder digitado pela secretaria).
    2. **Roster da SALA** pelo MOTOR ÚNICO (``matching.classificar_linha``) — o
       mesmo cálculo do Elefante/Matific/cadastro manual: exato, abreviação,
       variante segura, corroboração por identificador, veto por identidade,
       2+ candidatos → revisão.
    3. **Mudança de sala** — nome EXATAMENTE igual em outra sala da escola. Aqui a
       chamada não conta (é numeração da sala) e exige-se prova de identidade
       (nascimento/RA/UUID iguais) para reusar; sem prova, ou com 2+ homônimos em
       outras salas, vai para REVISÃO (nunca funde duas crianças às cegas).
    4. Nada plausível → CRIAR.
    """
    ident = _identidade_da_linha(linha)
    if linha.ra:
        alvo = ctx.por_ra.get(linha.ra)
        if alvo is not None and alvo.id is not None and nomes_compativeis(linha.nome, alvo.nome):
            return Decisao(REUSAR, alvo.id, "ra", (alvo.id,))

    res = matching.classificar_linha(ident, ctx.roster(linha.chave_sala))
    if res.status == matching.VINCULADO and res.aluno_id is not None:
        return Decisao(REUSAR, res.aluno_id, res.motivo, res.candidatos)
    if res.status == matching.REVISAR:
        return Decisao(REVISAR, res.aluno_id, res.motivo, res.candidatos)

    # (3) MUDANÇA DE SALA — a matrícula muda, a pessoa não. Só nome idêntico:
    # abreviação/variante em OUTRA sala é evidência fraca demais para atravessar
    # a fronteira da turma (ver ``test_turma_divergente_nao_casa``).
    fora: list[matching.Identidade] = [
        c for c in ctx.mesmo_nome(linha.nome)
        if c.id is not None and ctx.sala_de(c.id) != linha.chave_sala
        and not matching.conflito_identidade(_sem_chamada(ident), _sem_chamada(c))
    ]
    if len(fora) == 1:
        alvo = fora[0]
        if matching.corrobora_identidade(_sem_chamada(ident), _sem_chamada(alvo)):
            return Decisao(REUSAR, alvo.id, "mudanca_de_sala", (alvo.id,))
        return Decisao(REVISAR, alvo.id, "mudanca_de_sala_sem_prova", (alvo.id,))
    if len(fora) > 1:
        return Decisao(REVISAR, matching.melhor_candidato({c.id: c for c in fora}),
                       "homonimos_em_outras_salas",
                       tuple(sorted(c.id for c in fora)))  # type: ignore[arg-type]
    return Decisao(CRIAR, None, res.motivo or "novo")


# Motivos de REUSAR decididos SÓ pela semelhança do NOME — nenhum identificador
# forte (RA/UUID/chamada/nascimento) confirmou. São os únicos em que DUAS linhas
# diferentes do mesmo arquivo podem disputar o MESMO cadastro.
_MOTIVOS_SO_NOME = frozenset({"abreviacao", "variante", "typo"})


def candidatos_disputados(linhas: list[LinhaMatricula],
                          ctx: ContextoCasamento) -> set[int]:
    """UNICIDADE 1:1 DO LOTE (só leitura, contra o estado INICIAL do arquivo).

    ``resolver_linha`` decide uma linha de cada vez e não enxerga as outras. Sem
    esta pré-passagem, um cadastro abreviado que serve a DUAS linhas ("AGATHA V"
    para "AGATHA VITORIA MOURA" e "AGATHA VALENTINA LIMA") é entregue à PRIMEIRA
    do arquivo — um cara-ou-coroa que gruda os dados de plataforma de uma criança
    na ficha da outra. Aqui só se DETECTA a disputa; quem a resolve é
    ``arbitrar_disputa``, mandando as linhas envolvidas para revisão.

    Só conta a disputa por NOME: duas linhas com o MESMO RA (ou o mesmo aluno em
    duas turmas do arquivo) são a mesma criança e não são disputa nenhuma."""
    reivindicado: dict[int, set[str]] = {}
    for linha in linhas:
        d = resolver_linha(linha, ctx)
        if d.acao == REUSAR and d.aluno_id is not None and d.motivo in _MOTIVOS_SO_NOME:
            reivindicado.setdefault(d.aluno_id, set()).add(normalizar(linha.nome))
    return {aid for aid, nomes in reivindicado.items() if len(nomes) > 1}


def arbitrar_disputa(decisao: Decisao, disputados: set[int]) -> Decisao:
    """Converte em REVISÃO o REUSAR de um cadastro DISPUTADO por várias linhas.
    Nada é criado nem alterado — é a mesma regra do resto do P0: correspondência
    insegura vai para o gestor, nunca para um chute."""
    if (decisao.acao == REUSAR and decisao.aluno_id in disputados
            and decisao.motivo in _MOTIVOS_SO_NOME):
        return replace(decisao, acao=REVISAR, motivo="disputado_por_varias_linhas")
    return decisao


def aviso_revisao(nome_linha: str, turma: str, nomes_candidatos: str) -> str:
    return (f"“{nome_linha}” (turma {turma}) parece ser o mesmo aluno de: "
            f"{nomes_candidatos} — mas a correspondência NÃO é segura. Nada foi "
            "criado nem alterado nesta linha, para não abrir uma segunda ficha da "
            "mesma criança nem misturar duas crianças diferentes. Resolva em "
            "Alunos › Fundir duplicatas; se forem pessoas diferentes, preencha RA "
            "ou data de nascimento distintos na planilha e reimporte.")
