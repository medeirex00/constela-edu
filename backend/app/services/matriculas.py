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


def serie_da_sala(nome: str, ano_escolar: str = "") -> int | None:
    """SÉRIE (1, 2, 3…) da sala, ou ``None`` quando o rótulo não marca série.

    FONTE ÚNICA da leitura de série no sistema: delega para
    ``dificuldade_livro.serie_numero``, a mesma que o motor de pontuação usa para
    o fator de série — para "4º Ano" valer 4 em todo lugar, e "EJA 2", "Turma 3",
    "Maternal" ou "EF1 - 1º ao 5º" não valerem série nenhuma em lugar nenhum.

    Aceita os dois lados do casamento: o rótulo da turma CADASTRADA
    (``ano_escolar``, o campo semântico, tentado primeiro) e o nome cru do
    RELATÓRIO ("4 ANO A INTEGRAL (300309347)" → 4). Sem série marcada devolve
    ``None`` — quem chama trata isso como "não dá para decidir", nunca como 0."""
    from app.services.dificuldade_livro import serie_numero
    for rotulo in (ano_escolar, nome):
        serie = serie_numero(rotulo) if rotulo else None
        if serie is not None:
            return serie
    return None


#: As duas ETAPAS que a correspondência de sala distingue. ``serie_da_sala`` sozinha
#: não basta: ``serie_da_sala("1ª Fase") == serie_da_sala("1º Ano") == 1``.
ETAPA_FUNDAMENTAL = "fundamental"
ETAPA_FORA_DO_FUNDAMENTAL = "fora_do_fundamental"   # Fase/EMEI/Pré/Maternal/EJA…


def etapa_da_sala(nome: str, ano_escolar: str = "") -> str:
    """ETAPA da sala: ``"fora_do_fundamental"`` quando o rótulo nomeia Educação
    Infantil (ou outra etapa que não é o Fundamental — Fase, EMEI, Pré, Maternal,
    EJA…), senão ``"fundamental"``.

    Mesma regra da elegibilidade (``elegibilidade.e_etapa_fora_da_premiacao``),
    para "Fase" querer dizer a mesma coisa na premiação e na correspondência de
    sala. Lê os DOIS rótulos da turma cadastrada (``ano_escolar`` e ``nome``): se
    qualquer um deles nomeia uma etapa fora do Fundamental, a sala é tratada como
    tal — o rótulo já chegou ao banco mentindo ("1º Ano" derivado de "1 FASE A"),
    e na dúvida a sala NÃO é dada como a mesma do relatório (a linha vai para
    revisão em vez de cair na turma de outra etapa)."""
    from app.services.elegibilidade import e_etapa_fora_da_premiacao
    for rotulo in (ano_escolar, nome):
        if rotulo and e_etapa_fora_da_premiacao(rotulo):
            return ETAPA_FORA_DO_FUNDAMENTAL
    return ETAPA_FUNDAMENTAL


def overlap_turma(a: frozenset[str] | set[str], b: frozenset[str] | set[str]) -> int:
    """Tokens de turma em comum, ignorando palavras ubíquas — para "1º Ano A"
    casar com "1 ANO A MANHÃ" (série+letra) mas NÃO com "4º Ano A"."""
    return len((set(a) & set(b)) - _STOP_TURMA)


def nome_menos_informativo(novo: str, atual: str) -> bool:
    """O nome `novo` é uma versão ENCURTADA do `atual` (abreviação posicional ou
    subconjunto de tokens)? "MARIA E. TESTELLI" contra "MARIA EDUARDA TESTELLI" → True.

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
    if svc.chave_nome(a) == svc.chave_nome(b):
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
    # Fichas que ESTE arquivo já atribuiu a alguma linha (reuso seguro ou criação):
    # quem já tem dono no arquivo não é a ficha "renumerada" de outra linha.
    reivindicados: set[int] = field(default_factory=set)

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
        nome_novo = svc.chave_nome(ident.nome)
        nome_velho = self._nome_de.get(aid)
        if nome_velho is not None and nome_velho != nome_novo:
            self._por_nome.get(nome_velho, {}).pop(aid, None)
        self._por_nome.setdefault(nome_novo, {})[aid] = ident
        self._nome_de[aid] = nome_novo
        if ident.ra:
            self.por_ra.setdefault(ident.ra, ident)

    def registrar_ra(self, ident: matching.Identidade) -> None:
        """Só o RA (usado por quem NÃO é candidato por nome — aluno excluído):
        o RA continua identificando (reativa), o nome não. Reconhecer não é
        reativar: a persistência não reativa a ficha excluída cuja conta da
        plataforma hoje vale em outra escola (D10,
        ``routers.importacoes._reter_reativacao_conta_de_outra_escola``)."""
        if ident.id is not None and ident.ra:
            self.por_ra.setdefault(ident.ra, ident)

    def roster(self, chave_sala: str) -> list[matching.Identidade]:
        return list(self._por_sala.get(chave_sala, {}).values())

    def sala_de(self, aluno_id: int) -> str | None:
        return self._sala_de.get(aluno_id)

    def mesmo_nome(self, nome: str) -> list[matching.Identidade]:
        return list(self._por_nome.get(svc.chave_nome(nome), {}).values())


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

    VETO SÓ PELO Nº DE CHAMADA não abre ficha nova: a chamada é numeração da SALA
    (a secretaria renumera a turma), então um cadastro de nome plausível que só
    diverge nela é, muito provavelmente, a MESMA criança renumerada. Criar ali
    fazia a 2ª ficha E deixava a ficha verdadeira fora de ``vistos`` — e a
    reconciliação a marcava "fora da lista" (a ficha certa sumia do ranking com
    todos os dados das plataformas). Agora vai para REVISÃO com esses cadastros
    entre os candidatos (protegidos da reconciliação), salvo quando um
    identificador forte (RA/nascimento/UUID/chamada igual) corrobora outro — ou
    quando a ficha vetada JÁ tem dono neste arquivo (``ctx.reivindicados``: outra
    linha a reusa/criou), e aí é mesmo um segundo homônimo e a criação é correta.
    """
    ident = _identidade_da_linha(linha)
    if linha.ra:
        alvo = ctx.por_ra.get(linha.ra)
        if alvo is not None and alvo.id is not None and nomes_compativeis(linha.nome, alvo.nome):
            return Decisao(REUSAR, alvo.id, "ra", (alvo.id,))

    res = matching.classificar_linha(ident, ctx.roster(linha.chave_sala))
    so_chamada = tuple(i for i in res.vetados_so_chamada if i not in ctx.reivindicados)
    if so_chamada and not (res.status == matching.VINCULADO
                           and res.motivo in ("identificador", "uuid")):
        todos = tuple(dict.fromkeys((*res.candidatos, *so_chamada)))
        return Decisao(REVISAR, res.aluno_id if res.aluno_id is not None else so_chamada[0],
                       "chamada_divergente", todos)
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
    para "AGATHA VIOLETA MONTESTELLI" e "AGATHA VALENTINA LIMA") é entregue à PRIMEIRA
    do arquivo — um cara-ou-coroa que gruda os dados de plataforma de uma criança
    na ficha da outra. Aqui só se DETECTA a disputa; quem a resolve é
    ``arbitrar_disputa``, mandando as linhas envolvidas para revisão.

    Só conta a disputa por NOME: duas linhas com o MESMO RA (ou o mesmo aluno em
    duas turmas do arquivo) são a mesma criança e não são disputa nenhuma."""
    reivindicado: dict[int, set[str]] = {}
    for linha in linhas:
        d = resolver_linha(linha, ctx)
        if d.acao == REUSAR and d.aluno_id is not None and d.motivo in _MOTIVOS_SO_NOME:
            reivindicado.setdefault(d.aluno_id, set()).add(svc.chave_nome(linha.nome))
    return {aid for aid, nomes in reivindicado.items() if len(nomes) > 1}


def reivindicados_no_arquivo(linhas: list[LinhaMatricula],
                             ctx: ContextoCasamento) -> set[int]:
    """Fichas que alguma linha do arquivo REUSA com segurança (só leitura, contra o
    estado INICIAL) — ponto de partida de ``ctx.reivindicados``."""
    return {d.aluno_id for d in (resolver_linha(l, ctx) for l in linhas)
            if d.acao == REUSAR and d.aluno_id is not None}


def arbitrar_disputa(decisao: Decisao, disputados: set[int]) -> Decisao:
    """Converte em REVISÃO o REUSAR de um cadastro DISPUTADO por várias linhas.
    Nada é criado nem alterado — é a mesma regra do resto do P0: correspondência
    insegura vai para o gestor, nunca para um chute."""
    if (decisao.acao == REUSAR and decisao.aluno_id in disputados
            and decisao.motivo in _MOTIVOS_SO_NOME):
        return replace(decisao, acao=REVISAR, motivo="disputado_por_varias_linhas")
    return decisao


def aviso_nascimento_divergente(nome: str, turma: str, na_ficha, na_planilha) -> str:
    """A planilha traz um nascimento DIFERENTE do que já está na ficha.

    A importação não sobrescreve — a data cadastrada pode ter vindo de uma fonte
    melhor, e escolher sozinha entre duas datas é decidir quem é a criança. Mas
    calar também não serve: divergência de nascimento é o sinal de identidade
    mais forte do motor, e é assim que uma ficha duplicada começa. Então
    preserva e AVISA, para um humano conferir na fonte."""
    return (f"“{nome}” (turma {turma}) está cadastrado(a) com nascimento "
            f"{na_ficha}, mas a planilha traz {na_planilha}. A importação NÃO "
            "alterou a data: escolher entre as duas é decisão de gente, não do "
            "sistema. Confira na certidão ou no RA do aluno e, se a planilha "
            "estiver certa, corrija a ficha em Alunos › Editar dados. Enquanto "
            "as duas datas divergirem, o motor de identidade trata os dois "
            "registros como crianças diferentes.")


def aviso_fase_nao_reativa(nome: str, turma: str) -> str:
    """A planilha traz, numa aba de FASE, um aluno que está inativo na escola.

    A linha é aplicada (nome, ficha, turma), mas o status NÃO volta para ativo:
    as Fases não concorrem às premiações, então deixar uma linha de Educação
    Infantil reativar uma ficha seria trazer de volta à população ativa alguém
    por um motivo que não dá direito a prêmio nenhum — e desfazendo, em
    silêncio, uma decisão que alguém tomou antes."""
    return (f"“{nome}” consta na aba {turma} (Educação Infantil), mas está "
            "inativo(a) nesta escola — a importação NÃO o(a) reativou. As Fases "
            "não participam das premiações, e por isso uma linha de Fase não "
            "devolve ninguém à população ativa. Os dados continuam preservados; "
            "se a criança deve mesmo voltar, use Alunos › Reativar.")


def aviso_transferido(nome: str, turma: str) -> str:
    """A planilha traz um aluno que a escola marcou como TRANSFERIDO.

    Continuar na lista é o normal: a planilha costuma manter a linha e anotar a
    movimentação numa coluna própria, que esta importação não interpreta. Então
    a linha é aplicada (nome, ficha, turma) mas o status NÃO volta para ativo."""
    return (f"“{nome}” (turma {turma}) consta na planilha, mas está marcado como "
            "TRANSFERIDO nesta escola — a importação NÃO o trouxe de volta para a "
            "população ativa, para não desfazer essa decisão sozinha. Os dados "
            "dele continuam preservados. Se a criança de fato retornou, use "
            "Alunos › Reativar; a planilha, por si só, não é prova de retorno.")


def aviso_reativacao_retida_conta_de_outra_escola(nome: str, turma: str) -> str:
    """A planilha reconhece (pelo RA) um aluno EXCLUÍDO que ela reativaria, mas a
    conta da plataforma da ficha dele hoje é a identidade de um aluno de OUTRA
    escola do Constela (D10). A linha não é aplicada e o status não muda — ver
    ``routers.importacoes._reter_reativacao_conta_de_outra_escola``."""
    return (f"“{nome}” (turma {turma}) consta na planilha e está EXCLUÍDO nesta "
            "escola, mas a conta da plataforma da ficha dele hoje é a identidade de "
            "um aluno de OUTRA escola do Constela. A importação NÃO o reativou e não "
            "alterou nada na ficha: reativar faria a conta valer nas duas escolas, e "
            "a criança de lá deixaria de ser atualizada. Se a criança voltou mesmo "
            "para esta escola, o Admin Global confere com as duas escolas e reativa "
            "em Alunos › Reativar; depois disso (ou quando a conta deixar de valer "
            "na outra escola), o próximo envio da planilha aplica esta linha.")


def aviso_turma_arquivada(turma: str, linhas: int, *, previa: bool = False) -> str:
    """A planilha traz alunos numa turma que está ARQUIVADA no cadastro.

    Turma arquivada não recebe ficha nem matrícula nova — arquivar existe para
    tirá-la de circulação sem apagar o histórico. Mas matricular "por cima" em
    silêncio também não serve (foi assim que o 1º Ano arquivado da escola 17
    deixou de receber crianças sem ninguém saber), e escolher outra turma por
    conta própria seria pior. Então a importação não aplica as linhas dessa
    turma, não mexe nas matrículas que já existem nela e diz como resolver.
    ``previa=True`` é o texto da análise, antes de confirmar."""
    if previa:
        return (f"A turma “{turma}” está ARQUIVADA no cadastro: as {linhas} linha(s) "
                "da planilha nessa turma NÃO serão aplicadas ao confirmar — nenhuma "
                "ficha nem matrícula nova nasce em turma arquivada, e as matrículas "
                "que já existem nela continuam como estão. Se a turma deve receber "
                "alunos, reative-a antes em Minha Escola › Turmas: ligue “Mostrar "
                "arquivadas e de outros anos” e use “Reativar” na linha dela.")
    return (f"A turma “{turma}” está ARQUIVADA no cadastro: {linhas} linha(s) da "
            "planilha nessa turma NÃO foram aplicadas — nenhuma ficha nem "
            "matrícula nova foi criada nela, e as matrículas que já existiam "
            "continuam como estavam. Se a turma deve receber alunos, reative-a em "
            "Minha Escola › Turmas (ligue “Mostrar arquivadas e de outros anos” e "
            "use “Reativar” na linha dela) e envie a planilha de novo.")


def ano_da_lista_diverge(ano_lista: int | None, ano_escola: int,
                         anos_por_aba: dict[str, int] | None = None) -> bool:
    """A Lista Piloto é de OUTRO ano letivo que o ativo da escola? Sem o ano (nem na
    planilha nem no nome do arquivo) não dá para saber: não diverge.

    ``anos_por_aba`` (``ListaPilotoAnalise.anos_por_aba``): basta UMA aba importada
    de outro ano — uma aba velha de 2026 à frente das de 2027 não libera as de 2027
    para o ano 2026 (as abas de anos diferentes entre si sempre divergem)."""
    if anos_por_aba and any(a != ano_escola for a in anos_por_aba.values()):
        return True
    return ano_lista is not None and ano_lista != ano_escola


def _abas_de_cada_ano(anos_por_aba: dict[str, int], limite: int = 6) -> str:
    """"2026 na aba “3º Ano A”; 2027 nas abas “5º Ano A” e “5º Ano B”" — por ano."""
    por_ano: dict[int, list[str]] = {}
    for aba, ano in anos_por_aba.items():
        por_ano.setdefault(ano, []).append(aba)
    partes = []
    for ano in sorted(por_ano):
        abas = por_ano[ano]
        nomes = [f"“{a}”" for a in abas[:limite]]
        if len(abas) > limite:
            nomes.append(f"mais {len(abas) - limite}")
        lista = nomes[0] if len(nomes) == 1 else f"{', '.join(nomes[:-1])} e {nomes[-1]}"
        partes.append(f"{ano} na aba {lista}" if len(abas) == 1
                      else f"{ano} nas abas {lista}")
    return "; ".join(partes)


def aviso_ano_da_lista(ano_lista: int | None, origem: str | None, ano_escola: int, *,
                       previa: bool, anos_por_aba: dict[str, int] | None = None,
                       ) -> str | None:
    """O aviso do ANO da Lista Piloto, ou ``None`` quando é o ano da escola.

    A confirmação aplica a lista ao ano letivo ATIVO da escola: a de 2027 enviada com a
    escola ainda em 2026 moveria as matrículas de 2026 para as turmas do ano seguinte,
    marcaria os formandos "fora da lista piloto" e recalcularia as Notas de 2026 — e a
    matrícula não guarda histórico para desfazer. Por isso a lista de outro ano é
    recusada (a confirmação devolve este texto com 409; ``previa=True`` é o da prévia).
    ``origem`` diz onde corrigir o ano, se ele é que está errado: "planilha" (a célula
    "Lista Piloto:") ou "arquivo" (o nome do arquivo, quando a célula falta).

    Abas de anos DIFERENTES entre si (``anos_por_aba``): o aviso nomeia as abas de
    cada ano — a lista não é de ano nenhum, e só as abas do ano da escola podem ir.

    Sem o ano, a prévia pede para conferir (a confirmação segue, como sempre seguiu)."""
    efeito = "Ela não pode ser gravada" if previa else "Nada foi gravado"
    if anos_por_aba and len(set(anos_por_aba.values())) > 1:
        return (f"As abas desta Lista Piloto são de anos letivos diferentes "
                f"({_abas_de_cada_ano(anos_por_aba)}), e a escola está no ano letivo "
                f"{ano_escola}. {efeito}: gravar as abas de outro ano mudaria as turmas, "
                f"as matrículas e o ranking de {ano_escola}. Deixe na planilha só as abas "
                f"da Lista Piloto de {ano_escola} e envie de novo; se o ano escrito no "
                "topo de uma aba (“Lista Piloto:”) está errado, corrija-o.")
    if ano_lista is None:
        if not previa:
            return None
        return (f"A planilha não diz de que ano é esta Lista Piloto: ao gravar, ela vale "
                f"para o ano letivo {ano_escola} da escola. Confira se é a lista de "
                f"{ano_escola} antes de gravar.")
    if not ano_da_lista_diverge(ano_lista, ano_escola):
        return None
    if origem == "arquivo":
        de_onde = (f"O nome do arquivo indica a Lista Piloto de {ano_lista} (a planilha "
                   "não traz o ano)")
        onde_corrigir = "corrija o ano no nome do arquivo"
    else:
        de_onde = f"Esta é a Lista Piloto de {ano_lista}"
        onde_corrigir = "corrija o ano escrito no topo da planilha (“Lista Piloto:”)"
    if ano_lista > ano_escola:
        situacao = f"e a escola ainda está no ano letivo {ano_escola}"
        caminho = (f"Peça ao administrador global para trocar o ano letivo ativo da escola "
                   f"para {ano_lista} e envie a planilha de novo.")
    else:
        situacao = f"e a escola já está no ano letivo {ano_escola}"
        caminho = (f"Envie a Lista Piloto de {ano_escola}; se o ano letivo da escola é que "
                   "está errado, peça ao administrador global para corrigi-lo.")
    return (f"{de_onde}, {situacao}. {efeito}: gravá-la mudaria as turmas, as matrículas "
            f"e o ranking de {ano_escola}. {caminho} Se a lista é mesmo de {ano_escola}, "
            f"{onde_corrigir} e envie de novo.")


#: Situação de uma ficha que não está ativa, como os avisos da importação a descrevem.
_SITUACAO_DA_FICHA = {"arquivado": "arquivada", "transferido": "marcada como transferida",
                      "fora_lista_piloto": "fora da Lista Piloto"}


@dataclass(frozen=True)
class FichaCandidata:
    """Onde está a ficha que um aviso manda abrir: a situação (``Aluno.status``) e a
    turma da matrícula mais recente (a do ano letivo ativo, quando houver).

    ``turma_a_vista``: a turma aparece em Minha Escola › Turmas sem ligar "Mostrar
    arquivadas e de outros anos" (turma ativa, do ano letivo ativo)."""
    nome: str
    status: str = "ativo"
    turma: str | None = None
    ano: int | None = None
    turma_a_vista: bool = True


def como_abrir_ficha_inativa(ficha: FichaCandidata) -> str:
    """A frase que diz como ABRIR uma ficha que não está ativa. A pesquisa do topo da
    página só acha fichas ativas (``routers.sistema.pesquisa_global``), e a lista de
    Alunos só mostra os ativos do ano: o caminho é o painel da turma da ficha, com
    "Mostrar arquivados" (``GET /turmas/{id}/alunos?incluir_inativos``), que lista a
    turma pelas matrículas do ano DELA — inclusive a de um ano anterior."""
    situacao = _SITUACAO_DA_FICHA.get(ficha.status, "inativa")
    if not ficha.turma:
        # Sem matrícula nenhuma, nenhuma tela de lista a mostra: não prometer caminho.
        return (f"A ficha “{ficha.nome}” está {situacao} e sem turma, por isso não "
                "aparece na pesquisa do topo da página nem nas turmas: para abri-la, "
                "fale com a equipe que implantou o Constela (Suporte › Ainda precisa "
                "de ajuda?).")
    if ficha.turma_a_vista:
        turma = f"abra a turma {ficha.turma}"
    else:
        turma = ("ligue “Mostrar arquivadas e de outros anos”, abra a turma "
                 f"{ficha.turma}" + (f" de {ficha.ano}" if ficha.ano else ""))
    return (f"A ficha “{ficha.nome}” está {situacao} e por isso não aparece na pesquisa "
            f"do topo da página: para abri-la, vá a Minha Escola › Turmas, {turma}, "
            "ligue “Mostrar arquivados” e use “Visualizar” na linha dela.")


def aviso_revisao(nome_linha: str, turma: str, nomes_candidatos: str,
                  motivo: str = "", *, previa: bool = False,
                  ficha: FichaCandidata | None = None) -> str:
    """O aviso da linha que foi para REVISÃO (nada criado nem alterado nela).

    ``mudanca_de_sala_sem_prova`` (nome idêntico em outra sala, ou numa ficha sem turma
    no ano, sem RA/nascimento que provem ser a mesma criança — o caso em massa da
    virada, com as fichas criadas pela coleta) tem o seu caminho: não há duplicata
    nenhuma, e "Fundir duplicatas" nem mostra quem está sem turma no ano ativo. O
    caminho que funciona é a própria ficha (a pesquisa do topo a acha; Editar dados ›
    Turma a matricula, e o próximo envio da planilha a reconhece pelo roster da sala).
    Os outros motivos (nomes parecidos na mesma sala, disputa entre linhas) continuam
    em "Fundir duplicatas".

    ``ficha``: onde está a ficha candidata. Quando ela NÃO está ativa (arquivada,
    transferida, fora da Lista Piloto), a pesquisa do topo não a acha: o aviso diz a
    situação, como abri-la (``como_abrir_ficha_inativa``) e que, depois de levá-la à
    turma, é preciso "Reativar". Sem ``ficha`` (ou com a ficha ativa), o texto de antes.

    ``previa=True``: a redação da PRÉVIA (nada foi gravado ainda) — "Esta linha
    ficará para revisão: nada será criado nem alterado nela"."""
    nada = ("Esta linha ficará para revisão: nada será criado nem alterado nela"
            if previa else "Nada foi criado nem alterado nesta linha")
    if motivo == "mudanca_de_sala_sem_prova":
        if ficha is not None and ficha.status != "ativo":
            mesma = (f"{como_abrir_ficha_inativa(ficha)} Se for a mesma criança, nos três "
                     f"pontinhos da ficha › Editar dados, escolha a turma {turma} e, "
                     "depois, nos três pontinhos, use “Reativar”; no próximo envio desta "
                     "planilha, a ficha recebe os dados da linha.")
        else:
            mesma = ("Se for a mesma criança, procure o nome na "
                     "pesquisa do topo da página, abra a ficha e, nos três pontinhos › "
                     f"Editar dados, escolha a turma {turma}; no próximo envio desta "
                     "planilha, a ficha recebe os dados da linha.")
        return (f"“{nome_linha}” (turma {turma}) tem o mesmo nome de um aluno já "
                "cadastrado em outra turma ou sem turma neste ano letivo "
                f"({nomes_candidatos}), mas nenhum dado dos dois registros (RA ou data "
                f"de nascimento) confirma que é a mesma criança. {nada}. {mesma} "
                "Se forem crianças "
                "diferentes, registre a data de nascimento de cada uma (na ficha, em "
                "Editar dados, e na planilha) e envie de novo: com datas diferentes, a "
                "linha vira um cadastro novo.")
    return (f"“{nome_linha}” (turma {turma}) parece ser o mesmo aluno de: "
            f"{nomes_candidatos} — mas a correspondência NÃO é segura. {nada}, "
            "para não abrir uma segunda ficha da "
            "mesma criança nem misturar duas crianças diferentes. Resolva em "
            "Alunos › Fundir duplicatas; se forem pessoas diferentes, preencha RA "
            "ou data de nascimento distintos na planilha e reimporte.")
