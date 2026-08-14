"""MOTOR ÚNICO de identificação de aluno (spec do dono).

Fonte de verdade compartilhada por TODOS os fluxos que decidem "este registro é o
mesmo aluno?": import do Elefante, import do Matific, import da Lista Piloto,
prévia da importação, confirmação da importação e detecção de duplicatas passivas.
Ter um só motor evita o drift em que o mesmo aluno é reconhecido num fluxo e não em
outro.

Camadas:
  * ``plausivel(a, b)`` → 'forte' | 'parcial' | 'fraco' | None — o veredito ÚNICO de
    "podem ser a mesma pessoa?" por NOME (exato/abreviação/parcial/variante/typo);
  * ``conflito_identidade`` / ``corrobora_identidade`` — sinais de identidade que
    VETAM (nascimento/RA/chamada divergentes = criança diferente) ou CONFIRMAM
    (mesma chamada/RA/nascimento/UUID) a igualdade;
  * ``classificar_linha`` → status "vinculado" | "revisar" | "novo" | "bloqueado"
    para os fluxos linha-contra-roster (imports + prévia + confirmação).

Regra de ouro: automação máxima nos casos de ALTA confiança (nome exato/abreviação,
ou variação de grafia SEGURA — num token do MEIO, com 1º nome e sobrenome idênticos —
com 1 único candidato na turma, ou identificador forte corroborando), REVISÃO manual
nos ambíguos (2+ candidatos, nome parcial, ou variação no sobrenome/1º nome) e NENHUM
vínculo quando o veto de identidade prova ser outra criança.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.services.importacao import (
    _similaridade,
    casa_abreviado,
    normalizar_nome,
    tokens_nome,
    variante_ortografica,
)

# Status de classificação de uma linha contra o roster (o que a PRÉVIA mostra e o
# que a CONFIRMAÇÃO fará — são idênticos por construção).
VINCULADO = "vinculado"     # 1 candidato de alta confiança → vincula automático
REVISAR = "revisar"         # possível duplicata (ambíguo/parcial/grafia) → decide o gestor
NOVO = "novo"               # nenhum candidato plausível → cria novo
BLOQUEADO = "bloqueado"     # nome casa mas identificador forte PROVA ser outra criança


def typo_forte(a: list[str], b: list[str]) -> bool:
    """Pequeno erro de digitação: mesmo nº de tokens e EXATAMENTE um token diferente
    (podendo ser o PRIMEIRO nome, ao contrário de ``variante_ortografica``), muito
    parecido (ratio ≥ 0.8), ambos com ≥3 letras. Casa GABRYEL/GABRIEL — mas também
    MARIA/MARTA (similaridade não os separa), por isso é sinal de REVISÃO, nunca de
    vínculo automático."""
    if len(a) != len(b) or not a:
        return False
    difs = [i for i in range(len(a)) if a[i] != b[i]]
    if len(difs) != 1:
        return False
    ta, tb = a[difs[0]], b[difs[0]]
    if len(ta) < 3 or len(tb) < 3:
        return False
    return _similaridade(ta, tb) >= 0.8


def _variante_segura_para_vincular(nome_a: str, nome_b: str) -> bool:
    """Uma variação de grafia (plausivel='fraco') é segura para AUTO-VÍNCULO de
    candidato ÚNICO? SÓ quando o 1º nome E o último sobrenome são IDÊNTICOS e a
    divergência está num token do MEIO (nome com >=3 tokens). Aí é, na prática, a
    MESMA pessoa: ABRAÃO LUÍS/LUIZ DIAS, AGATHA EMANUELE/EMANUELLE ... OLIVEIRA.
    Variação no SOBRENOME (SOUZA/SOUSA), no 1º nome ou no gênero (BRUNO/BRUNA,
    GABRYEL/GABRIEL) e nomes de <=2 tokens distinguem crianças DIFERENTES de
    altíssima frequência no Brasil → vão para REVISÃO, nunca auto-vínculo (achado do
    red-team adversarial 2026-08-04; preserva 'nunca fundir crianças diferentes')."""
    ta, tb = tokens_nome(nome_a), tokens_nome(nome_b)
    if len(ta) != len(tb) or len(ta) < 3:
        return False
    return ta[0] == tb[0] and ta[-1] == tb[-1]


def plausivel(nome_a: str, nome_b: str) -> str | None:
    """Podem ser a MESMA pessoa por NOME? 'forte' (exato/abreviação — pode
    auto-vincular), 'parcial' (subconjunto/nome parcial — só revisão), 'fraco'
    (variante/typo de grafia — só revisão), ou None (não casa)."""
    ta, tb = tokens_nome(nome_a), tokens_nome(nome_b)
    if not ta or not tb:
        return None
    sa, sb = set(ta), set(tb)
    if sa == sb:
        return "forte"                                   # exato (ignora ordem/acento)
    if casa_abreviado(ta, tb) or casa_abreviado(tb, ta):
        return "forte"                                   # abreviação/inicial/truncamento
    if sa < sb or sb < sa:
        return "parcial"                                 # nome parcial (subconjunto)
    if variante_ortografica(ta, tb) or typo_forte(ta, tb):
        return "fraco"                                   # variante/typo de grafia
    return None


def vincula_por_nome_unico(nome_a: str, nome_b: str) -> bool:
    """Critério ÚNICO de AUTO-VÍNCULO por NOME quando há 1 único candidato plausível
    na turma — COMPARTILHADO por ``classificar_linha`` (imports Elefante/Matific,
    prévia, sync) e pelo casamento da Lista Piloto (``matriculas.resolver_linha``).
    Assim a decisão "este registro é o mesmo aluno?" é a MESMA, independentemente da
    origem dos dados. True para nome exato/abreviação (forte: MARIA E ↔ MARIA EDUARDA)
    e para variação de grafia SEGURA (fraco no nome do MEIO, pontas idênticas:
    LUÍS↔LUIZ). False para variação insegura (sobrenome/1º nome: SOUZA/SOUSA,
    BRUNO/BRUNA), nome PARCIAL (subconjunto) e nomes diferentes — vão a revisão/novo
    em TODOS os fluxos."""
    v = plausivel(nome_a, nome_b)
    if v == "forte":
        return True
    if v == "fraco":
        return _variante_segura_para_vincular(nome_a, nome_b)
    return False


@dataclass(frozen=True)
class Identidade:
    """Identificadores fortes de um aluno/linha — usados para VETAR ou CORROBORAR o
    casamento por nome. Todos opcionais (o que não vier fica None/vazio)."""
    nome: str = ""
    chamada: int | None = None
    nascimento: date | None = None
    ra: str = ""
    uuids: frozenset[str] = field(default_factory=frozenset)
    da_lista_piloto: bool = False
    id: int | None = None


def _norm_ra(ra: str | None) -> str:
    return str(ra or "").strip()


def conflito_identidade(a: Identidade, b: Identidade) -> bool:
    """Sinais que PROVAM ser crianças DIFERENTES: nascimento, RA ou nº de chamada
    preenchidos NOS DOIS e DIVERGENTES. (UUID nunca veta — a mesma pessoa pode ter
    UUIDs de plataformas diferentes.)

    O nº de chamada é o sinal mais FRACO dos três: é uma posição na lista da sala,
    não um identificador da criança — a secretaria renumera a turma toda quando
    alguém sai, entra ou troca de sala. Por isso ele só prova "outra criança"
    quando NENHUM identificador ESTÁVEL (nascimento, RA, UUID) diz o contrário;
    com o mesmo nome e o mesmo nascimento/RA, chamada diferente é renumeração, e
    tratá-la como veto abriria uma 2ª ficha da mesma criança a cada reimportação
    da Lista Piloto (2026-08-11)."""
    if a.nascimento and b.nascimento and a.nascimento != b.nascimento:
        return True
    ra_a, ra_b = _norm_ra(a.ra), _norm_ra(b.ra)
    if ra_a and ra_b and ra_a != ra_b:
        return True
    if a.chamada is not None and b.chamada is not None and a.chamada != b.chamada:
        estavel_igual = (
            bool(a.nascimento and b.nascimento and a.nascimento == b.nascimento)
            or bool(ra_a and ra_b and ra_a == ra_b)
            or bool(a.uuids and b.uuids and (a.uuids & b.uuids)))
        return not estavel_igual
    return False


def corrobora_identidade(a: Identidade, b: Identidade, *, incluir_nascimento: bool = True) -> bool:
    """Identificador forte IGUAL nos dois → é a MESMA criança (sobe a confiança):
    UUID em comum, ou nº de chamada / RA iguais (únicos por turma/globais). O
    NASCIMENTO só corrobora quando ``incluir_nascimento`` (nome FORTE): aniversário
    é NÃO-único (colisões numa turma são comuns), então sobre um nome PARCIAL ele
    poderia juntar duas crianças diferentes que compartilham a data."""
    if a.uuids and b.uuids and (a.uuids & b.uuids):
        return True
    if a.chamada is not None and b.chamada is not None and a.chamada == b.chamada:
        return True
    ra_a, ra_b = _norm_ra(a.ra), _norm_ra(b.ra)
    if ra_a and ra_b and ra_a == ra_b:
        return True
    return bool(incluir_nascimento and a.nascimento and b.nascimento
                and a.nascimento == b.nascimento)


@dataclass(frozen=True)
class Resultado:
    status: str                     # VINCULADO | REVISAR | NOVO | BLOQUEADO
    aluno_id: int | None            # candidato escolhido (vinculado) ou sugerido (revisar)
    motivo: str                     # uuid|identificador|exato|abreviacao|parcial|variante|typo|conflito
    candidatos: tuple[int, ...] = ()   # todos os plausíveis (para a revisão)


def _motivo_nome(linha_nome: str, cand_nome: str) -> str:
    ta, tb = tokens_nome(linha_nome), tokens_nome(cand_nome)
    if set(ta) == set(tb):
        return "exato"
    if casa_abreviado(ta, tb) or casa_abreviado(tb, ta):
        return "abreviacao"
    if set(ta) < set(tb) or set(tb) < set(ta):
        return "parcial"
    if variante_ortografica(ta, tb):
        return "variante"
    return "typo"


def melhor_candidato(cands: dict[int, Identidade]) -> int:
    """Melhor sugestão para revisão: o da Lista Piloto vence; senão o de menor id."""
    return sorted(cands.values(), key=lambda c: (not c.da_lista_piloto, c.id or 0))[0].id  # type: ignore[return-value]


def classificar_linha(linha: Identidade, roster: list[Identidade]) -> Resultado:
    """Classifica UMA linha importada contra o ROSTER de candidatos (alunos da mesma
    escola/turma). É o mesmo cálculo na PRÉVIA e na CONFIRMAÇÃO — a prévia mostra
    exatamente o que a confirmação fará.

    Ordem de decisão (mais forte primeiro):
      1) UUID/id externo em comum → VINCULADO (identidade definitiva);
      2) identificador forte corroborando (chamada/RA/nascimento igual) um candidato
         plausível NÃO-fraco → VINCULADO;
      3) 1 único candidato FORTE (exato/abreviação), OU FRACO de variação SEGURA
         (variante/typo num token do MEIO, com 1º nome e sobrenome idênticos), e
         nenhum outro plausível → VINCULADO (decisão do dono 2026-08-04);
      4) 2+ candidatos, OU 1 candidato PARCIAL (subconjunto), OU variação de grafia
         NÃO-segura (sobrenome/1º nome, ex.: SOUZA/SOUSA, BRUNO/BRUNA) → REVISAR;
      5) o nome casava mas TODOS foram vetados por identidade divergente → BLOQUEADO;
      6) nada → NOVO.
    Nunca vincula por nome PARCIAL (subconjunto), por variação no SOBRENOME ou no
    1º nome/gênero, nem quando há 2+ candidatos — tudo isso vai a REVISAR. Variante/
    typo de candidato ÚNICO auto-vincula APENAS na variação SEGURA de nome do meio
    (pontas idênticas), a pedido do dono e sem fundir crianças diferentes."""
    fortes: dict[int, Identidade] = {}
    parciais: dict[int, Identidade] = {}
    fracos: dict[int, Identidade] = {}
    bloqueado_por_conflito = False

    for c in roster:
        if c.id is None:
            continue
        if linha.uuids and c.uuids and (linha.uuids & c.uuids):
            return Resultado(VINCULADO, c.id, "uuid", (c.id,))
        v = plausivel(linha.nome, c.nome)
        if v is None:
            continue
        if conflito_identidade(linha, c):
            bloqueado_por_conflito = True     # nome casa, identidade prova diferente
            continue
        (fortes if v == "forte" else parciais if v == "parcial" else fracos)[c.id] = c

    # (2) Corroboração por identificador FORTE (chamada/RA/UUID; nascimento só p/ nome
    # forte, pois aniversário não é único). O identificador desempata a identidade →
    # vincula até nome PARCIAL ou variação de grafia "insegura" (o mesmo RA/chamada/
    # UUID prova ser a MESMA criança). Gêmeos/homônimos com identificador DIVERGENTE já
    # saíram pelo veto (bloqueado_por_conflito) antes desta contagem.
    for c in fortes.values():
        if corrobora_identidade(linha, c):
            return Resultado(VINCULADO, c.id, "identificador", (c.id,))  # type: ignore[arg-type]
    for c in parciais.values():
        if corrobora_identidade(linha, c, incluir_nascimento=False):
            return Resultado(VINCULADO, c.id, "identificador", (c.id,))  # type: ignore[arg-type]
    for c in fracos.values():
        if corrobora_identidade(linha, c, incluir_nascimento=False):
            return Resultado(VINCULADO, c.id, "identificador", (c.id,))  # type: ignore[arg-type]

    plausiveis: dict[int, Identidade] = {**fortes, **parciais, **fracos}
    # 1 ÚNICO candidato plausível na MESMA turma → VINCULA — decisão do dono
    # (2026-08-04): fechar na ORIGEM os duplicados de grafia (ABRAÃO LUÍS×LUIZ, AGATHA
    # EMANUELE×EMANUELLE) sem gerar ficha para fundir depois. MAS com dois guard-rails
    # (red-team 2026-08-04, preserva "nunca fundir crianças diferentes"):
    #  - PARCIAL (subconjunto: "ANA"→"ANA JULIA") → REVISAR (cair um nome inteiro é
    #    ambíguo: sobrenome comum / dono ausente);
    #  - FRACO só vincula se a variação for SEGURA (nome do MEIO, pontas idênticas);
    #    variação no sobrenome/1º nome (SOUZA/SOUSA, BRUNO/BRUNA) → REVISAR.
    # Gêmeos/homônimos com identificador divergente já saíram pelo veto acima.
    unico = next(iter(plausiveis)) if len(plausiveis) == 1 else None
    if unico is not None and vincula_por_nome_unico(linha.nome, plausiveis[unico].nome):
        # Critério ÚNICO de vínculo por nome — o MESMO da Lista Piloto (matriculas):
        # forte (exato/abreviação) ou variação SEGURA de nome do meio. PARCIAL e
        # variação insegura (sobrenome/1º nome, ex.: SOUZA/SOUSA, BRUNO/BRUNA) devolvem
        # False e caem no REVISAR abaixo — preserva "nunca fundir crianças diferentes".
        return Resultado(VINCULADO, unico,
                         _motivo_nome(linha.nome, plausiveis[unico].nome), (unico,))
    if plausiveis:
        alvo = melhor_candidato(plausiveis)
        return Resultado(REVISAR, alvo, _motivo_nome(linha.nome, plausiveis[alvo].nome),
                         tuple(plausiveis))
    if bloqueado_por_conflito:
        return Resultado(BLOQUEADO, None, "conflito", ())
    return Resultado(NOVO, None, "", ())
