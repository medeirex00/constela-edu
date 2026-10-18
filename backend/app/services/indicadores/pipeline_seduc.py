"""Prévia, aplicação e desfazer do SARESP OFICIAL (SEDUC-SP) — etapa E4.

Três arquivos públicos da SEDUC entram pelo MESMO fluxo, detectados pelo
cabeçalho (``seduc``): o IEE por escola, o SARESP por município e o SARESP por
instância (Estado). Cada número vai para a tabela certa:

* PROFICIÊNCIA POR ESCOLA (IEE: LP e MT do 2º e do 5º ano) → ``resultados_avaliacao``
  (chave ``saresp``, etapa ``2_ano``/``5_ano``), com ``importacao_id`` e, sem
  número, ``valor`` nulo + ``motivo_ausencia`` (0035);
* o RESTO → ``indicadores_referencia``: participação e TPS por escola (``saresp``),
  nota, meta e ICM do IEE por escola (``iee``), e a proficiência da rede municipal
  e da rede estadual no município (CODMUN da rede) e do Estado (``saresp``).

Fluxo (só o admin global — a regra mais restrita até a decisão D4), o mesmo do ICA:

1. **Prévia** — lê, recorta a rede (INEP do cadastro; CODMUN da rede; UF) e mostra
   o que mudaria. Registra a importação (``importacoes_indicador``, status
   ``previa``, sha256) e NÃO grava número nenhum.
2. **Aplicação** — exige o MESMO arquivo (sha256), relê-o com o NOME e a edição
   informada da PRÉVIA (o sha256 não cobre o nome, e no SARESP por município e por
   instância a edição sai do nome) e recusa se a edição lida, o CODMUN da rede ou as
   substituições da D2 não forem os da prévia. Recalcula sobre o estado atual e
   grava numa transação só, guardando o estado anterior de cada linha tocada.
3. **Desfazer pelo id** — devolve exatamente o estado anterior (apaga o que criou,
   restaura o que alterou). Recusa se uma importação aplicada DEPOIS viu um dos
   números que esta tocou, ou se as linhas já não estão como ela deixou.

SUBSTITUIÇÃO DA MÉDIA CALCULADA (decisão D2 do dono): uma linha de
``resultados_avaliacao`` SEM ``importacao_id`` (importação manual — como as médias
do SARESP 5º ano de 2025 que o Constela calculou dos microdados em 26/07) nunca é
trocada em silêncio. A prévia lista cada uma, ANTES × DEPOIS por escola, e a
aplicação exige a resposta explícita ``substituir_calculadas``: sim (troca pelo
número oficial — e o desfazer devolve o calculado, com a fonte antiga) ou não
(fica o calculado; o resto da importação é aplicado). Sem resposta: recusa. A
resposta vale para o ANTES × DEPOIS que a prévia mostrou: a prévia guarda a
assinatura das substituições (chave + valor, motivo, unidade e fonte do ANTES) e,
se o conjunto recalculado na aplicação for outro (uma importação manual no meio,
por exemplo), a aplicação recusa e pede uma prévia nova.

PRECEDÊNCIA: o arquivo de edição mais nova nunca é sobrescrito por um de edição
mais antiga (``mantida``); valores iguais não mexem em nada (nem na
proveniência), então reaplicar o mesmo arquivo deixa o mesmo estado. Na família
que traz a data interna do arquivo (``Familia.desempate_por_data``: o Ideb, pela
entrada do zip do INEP), a MESMA edição desempata por ela, como no ICA: a versão
retificada (mais nova) não é desfeita por um pacote da versão anterior — este vira
``mantida`` e a prévia avisa; arquivo sem data fica atrás do datado. No SARESP o
upload não tem data interna e a regra é só a da edição.

FAMÍLIAS (E6a): o mesmo fluxo — números por escola em ``resultados_avaliacao`` + o
resto em ``indicadores_referencia``, prévia, substituição explícita, desfazer —
recebe outra família de arquivos pela ``Familia`` (como ler o arquivo, quais
parsers, sob qual avaliação a importação fica). ``SEDUC`` é a padrão; o Ideb do INEP
(pacote do ``preparar``: por escola, E6a, e do município, da UF e do Brasil, E6b) entra
por ``pipeline_ideb.FAMILIA`` e a planilha do Saeb (E7, só referência) por
``pipeline_saeb.FAMILIA``. Cada família lista e desfaz só as suas importações — e as
chaves de uma família nunca são as de outra (avaliação, abrangência ou indicador
diferentes), para o desfazer de uma não depender da outra.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Escola, ImportacaoIndicador, IndicadorReferencia, Rede, ResultadoAvaliacao
from app.services.avaliacoes import ImportacaoRecusada, normalizar_inep, obter_avaliacao
from app.services.indicadores import seduc
from app.services.indicadores.pipeline import (MSG_SEM_PLANO, _exigir_codigo, carregar_planos,
                                               codigo_ibge_da_rede, plano_desfazer,
                                               planos_da_lista)

AVALIACAO_IMPORTACAO = seduc.AVALIACAO_SARESP    # a importação fica sob o SARESP
FONTE_NOME = {
    seduc.PARSER_IEE: "SEDUC-SP — Índice de Excelência Educacional (IEE)",
    seduc.PARSER_SARESP_MUNICIPIO: "SEDUC-SP — Proficiência do SARESP por município",
    seduc.PARSER_SARESP_INSTANCIA: "SEDUC-SP — Proficiência do SARESP por instância",
}
CITACAO = {
    seduc.PARSER_IEE: ("Fonte: Secretaria da Educação do Estado de São Paulo (SEDUC-SP) — "
                       "Índice de Excelência Educacional (IEE), dados abertos."),
    seduc.PARSER_SARESP_MUNICIPIO: ("Fonte: Secretaria da Educação do Estado de São Paulo "
                                    "(SEDUC-SP) — Proficiência do SARESP por município, "
                                    "dados abertos."),
    seduc.PARSER_SARESP_INSTANCIA: ("Fonte: Secretaria da Educação do Estado de São Paulo "
                                    "(SEDUC-SP) — Proficiência do SARESP por instância, "
                                    "dados abertos."),
}
# Cabe em importacoes_indicador.licenca (String(200)) — o teste confere.
LICENCA = ("Dados abertos da SEDUC-SP (dados.educacao.sp.gov.br/termos): uso livre, com "
           "citação obrigatória da Secretaria da Educação do Estado de São Paulo.")

# Campos comparados ("alterada") e guardados para o desfazer.
_VALOR_REF = ("valor", "casas_decimais", "operador", "motivo_ausencia", "unidade", "desenho")
_ESTADO_REF = (*_VALOR_REF, "importacao_id", "valor_detalhado", "casas_decimais_detalhe",
               "detalhe_importacao_id")
_CHAVE_REF = ("edicao", "indicador", "abrangencia", "codigo_territorio", "codigo_inep",
              "rede_ensino", "localizacao", "etapa", "componente", "nivel")
_VALOR_ESC = ("valor", "unidade", "motivo_ausencia")
_ESTADO_ESC = (*_VALOR_ESC, "fonte", "importacao_id", "codigo_inep", "rede_id")
_MINIMO = datetime(1, 1, 1)


def _agora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _texto(valor: str | None, maximo: int) -> str | None:
    valor = (valor or "").strip()
    return valor[:maximo] or None


def _isoformat(valor):
    return valor.isoformat() if isinstance(valor, datetime) else valor


# --- Leitura + recorte (comum à prévia e à aplicação) -------------------------

def escolas_por_inep(db: Session, rede: Rede) -> dict[str, dict]:
    """INEP → escola, das escolas DESTA rede. INEP repetido no cadastro: recusa
    (casar com uma delas seria escolher em silêncio de quem é o resultado)."""
    saida: dict[str, dict] = {}
    nomes: dict[str, list[str]] = {}
    for eid, rid, codigo, nome in db.execute(
            select(Escola.id, Escola.rede_id, Escola.codigo_inep, Escola.nome).where(
                Escola.rede_id == rede.id, Escola.codigo_inep.isnot(None))
            .order_by(Escola.nome, Escola.id)):
        inep = normalizar_inep(codigo)
        if not inep:
            continue
        saida[inep] = {"id": eid, "rede_id": rid, "nome": nome}
        nomes.setdefault(inep, []).append(nome)
    repetidos = {k: v for k, v in nomes.items() if len(v) > 1}
    if repetidos:
        lista = "; ".join(f"{k} ({', '.join(v)})" for k, v in sorted(repetidos.items()))
        raise ImportacaoRecusada(
            "O mesmo código INEP está cadastrado em mais de uma escola da rede — "
            f"{lista}. Corrija o cadastro e envie a prévia de novo. Nada foi gravado.")
    return saida


def _codmun(rede: Rede) -> str | None:
    """O CODMUN da SEDUC gravado na rede, normalizado como o parser o compara (sem
    zeros à esquerda) — ``None`` quando a rede não tem o código."""
    bruto = (rede.codigo_municipio_estadual or "").strip()
    return (bruto.lstrip("0") or "0") if bruto else None


def _ler(db: Session, rede: Rede, conteudo: bytes, nome: str,
         edicao: int | None) -> seduc.LeituraSeduc:
    codigo = _exigir_codigo(rede)
    leitura = seduc.ler_arquivo(conteudo, nome, codigo_ibge=codigo,
                                codmun=rede.codigo_municipio_estadual, edicao_informada=edicao)
    if leitura.parser == seduc.PARSER_IEE:
        seduc.recortar_iee(leitura, escolas_por_inep(db, rede), codigo_ibge=codigo)
    return leitura


# --- Famílias de arquivo -------------------------------------------------------

@dataclass
class Lido:
    """O arquivo enviado, lido e recortado, e a proveniência da importação. No upload
    direto (``modo='upload'``) a proveniência é a do envio (nome, sha256 e tamanho do
    conteúdo; URL e Last-Modified digitados); num pacote, a do MANIFESTO."""

    leitura: seduc.LeituraSeduc
    versao_parser: str
    fonte_nome: str
    citacao: str
    licenca: str
    fonte_curta: str                       # o começo do campo ``fonte`` por escola
    modo: str = "upload"
    arquivo_nome: str | None = None
    arquivo_sha256: str | None = None
    arquivo_bytes: int | None = None
    arquivo_data: datetime | None = None
    versao_rotulo: str | None = None
    url_origem: str | None = None
    last_modified_origem: str | None = None
    coletado_em: datetime | None = None
    pacote_sha256: str | None = None
    resumo_extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Familia:
    """Uma família de arquivos que entra por este fluxo."""

    rotulo: str                             # nas mensagens ("SARESP/IEE", "Ideb/Saeb")
    parsers: tuple[str, ...]
    avaliacao_importacao: str               # a avaliação sob a qual a importação fica
    ler: Callable[[Session, Rede, bytes, str, int | None], Lido]
    # Número por escola SEM proveniência oficial e IGUAL ao oficial (valor, unidade e
    # motivo): ``igual`` (não mexe em nada) em vez de ``substituicao``. No Ideb/Saeb, os
    # números de 2023 da produção vieram do MESMO arquivo oficial pelo 1 clique; no
    # SARESP, as médias sem proveniência foram calculadas pelo Constela e a troca é
    # sempre explícita (D2), mesmo quando o número bate.
    manual_igual_fica: bool = False
    # Na MESMA edição, a data interna do arquivo (``arquivo_data``) desempata: o número
    # que veio de um arquivo mais novo fica (``mantida``). Só na família cujo arquivo
    # traz essa data de forma confiável (o Ideb: a da entrada do zip do INEP).
    desempate_por_data: bool = False


def _ler_seduc(db: Session, rede: Rede, conteudo: bytes, nome: str, edicao: int | None) -> Lido:
    leitura = _ler(db, rede, conteudo, nome, edicao)
    return Lido(leitura=leitura, versao_parser=seduc.VERSAO_PARSER,
                fonte_nome=FONTE_NOME[leitura.parser], citacao=CITACAO[leitura.parser],
                licenca=LICENCA, fonte_curta=_fonte_curta(leitura))


SEDUC = Familia(rotulo="SARESP/IEE", parsers=seduc.PARSERS,
                avaliacao_importacao=AVALIACAO_IMPORTACAO, ler=_ler_seduc)


# --- Plano --------------------------------------------------------------------

def _estado(linha, campos: tuple[str, ...]) -> dict:
    return {c: getattr(linha, c) for c in campos}


def _tupla(alvo: str, avaliacao_id: int, chave: dict) -> tuple:
    """Chave comparável entre importações. Na escola, as dimensões nulas valem ''
    (a mesma regra do ``uq_resultado_natural``)."""
    if alvo == "ref":
        return (alvo, avaliacao_id, *(chave[c] for c in _CHAVE_REF))
    return (alvo, avaliacao_id, chave["edicao"], chave["indicador"], chave["escola_id"],
            chave["etapa"] or "", chave["componente"] or "", chave["turma"] or "")


def _chave_ref(ln) -> dict:
    return {c: getattr(ln, c) for c in _CHAVE_REF}


def _chave_esc(ln: seduc.LinhaEscola) -> dict:
    return {"edicao": ln.edicao, "indicador": ln.indicador, "escola_id": ln.escola_id,
            "etapa": ln.etapa, "componente": ln.componente, "turma": None}


def _avaliacoes(db: Session, leitura: seduc.LeituraSeduc,
                familia: Familia | None = None) -> dict[str, int]:
    chaves = {(familia or SEDUC).avaliacao_importacao} | {
        n.avaliacao for n in leitura.referencia} | {ln.avaliacao for ln in leitura.escolares}
    return {chave: obter_avaliacao(db, chave).id for chave in sorted(chaves)}


def _importacoes(db: Session, ids: set[int]) -> dict[int, ImportacaoIndicador]:
    if not ids:
        return {}
    return {i.id: i for i in db.execute(select(ImportacaoIndicador).where(
        ImportacaoIndicador.id.in_(ids))).scalars()}


def _mais_nova_por_data(atual_imp: ImportacaoIndicador | None,
                        imp: ImportacaoIndicador) -> bool:
    """O número atual veio de um arquivo da MESMA edição com data interna mais nova
    que a deste (ou este não tem data)? Data igual (o mesmo arquivo) não é mais nova."""
    if (atual_imp is None or atual_imp.edicao_arquivo != imp.edicao_arquivo
            or atual_imp.arquivo_data is None):
        return False
    return imp.arquivo_data is None or atual_imp.arquivo_data > imp.arquivo_data


def _tipo(atual_imp: ImportacaoIndicador | None, imp: ImportacaoIndicador,
          antes: dict, depois: dict, campos_valor: tuple[str, ...], *,
          por_data: bool = False) -> str:
    if atual_imp is not None and atual_imp.edicao_arquivo > imp.edicao_arquivo:
        return "mantida"            # o número veio de um arquivo de edição mais nova
    if por_data and _mais_nova_por_data(atual_imp, imp):
        return "mantida"            # mesma edição, arquivo mais novo (a retificação)
    if all(antes[c] == depois[c] for c in campos_valor):
        return "igual"              # mesmo número: nem a proveniência muda
    return "alterada"


def _planejar(db: Session, leitura: seduc.LeituraSeduc, imp: ImportacaoIndicador,
              avaliacoes: dict[str, int], arquivo_nome: str, *,
              fonte_curta: str | None = None, manual_igual_fica: bool = False,
              desempate_por_data: bool = False) -> list[dict]:
    """O que esta importação faria em cada número. Não grava nada. Cada item leva a
    importação de onde veio o número atual (``imp_atual``; None se novo ou manual)."""
    plano: list[dict] = []
    # --- indicadores_referencia
    chaves_ref = [(avaliacoes[n.avaliacao], n.linha.chave) for n in leitura.referencia]
    if len(set(chaves_ref)) != len(chaves_ref):
        raise ImportacaoRecusada("O arquivo produziu o mesmo número duas vezes. Nada foi "
                                 "gravado.")
    existentes_ref: dict[tuple, IndicadorReferencia] = {}
    territorios = {n.linha.codigo_territorio for n in leitura.referencia}
    if territorios:
        for linha in db.execute(select(IndicadorReferencia).where(
                IndicadorReferencia.avaliacao_id.in_(set(avaliacoes.values())),
                IndicadorReferencia.codigo_territorio.in_(territorios))).scalars():
            existentes_ref[(linha.avaliacao_id,
                            tuple(getattr(linha, c) for c in _CHAVE_REF))] = linha
    # --- resultados_avaliacao (por escola)
    existentes_esc: dict[tuple, ResultadoAvaliacao] = {}
    if leitura.escolares:
        for linha in db.execute(select(ResultadoAvaliacao).where(
                ResultadoAvaliacao.avaliacao_id.in_(
                    {avaliacoes[ln.avaliacao] for ln in leitura.escolares}),
                ResultadoAvaliacao.edicao.in_({ln.edicao for ln in leitura.escolares}),
                ResultadoAvaliacao.indicador.in_({ln.indicador for ln in leitura.escolares}),
                ResultadoAvaliacao.escola_id.in_({ln.escola_id for ln in leitura.escolares}))
                ).scalars():
            existentes_esc[(linha.avaliacao_id, linha.edicao, linha.indicador, linha.escola_id,
                            linha.etapa or "", linha.componente or "", linha.turma or "")] = linha
    ids = {ln.importacao_id for ln in (*existentes_ref.values(), *existentes_esc.values())
           if ln.importacao_id is not None}
    imps = _importacoes(db, ids)
    nomes_escola = {e["escola_id"]: e["escola"] for e in leitura.escolas_casadas}

    for n in leitura.referencia:
        ln, avaliacao_id = n.linha, avaliacoes[n.avaliacao]
        depois = {"valor": ln.valor, "casas_decimais": ln.casas_decimais,
                  "operador": ln.operador, "motivo_ausencia": ln.motivo_ausencia,
                  "unidade": ln.unidade, "desenho": ln.desenho, "importacao_id": imp.id,
                  "valor_detalhado": None, "casas_decimais_detalhe": None,
                  "detalhe_importacao_id": None}
        atual = existentes_ref.get((avaliacao_id, ln.chave))
        atual_imp = imps.get(atual.importacao_id) if atual is not None else None
        if atual is None:
            tipo, antes = "nova", None
        else:
            antes = _estado(atual, _ESTADO_REF)
            tipo = _tipo(atual_imp, imp, antes, depois, _VALOR_REF, por_data=desempate_por_data)
        onde = (f"escola INEP {ln.codigo_inep}" if ln.abrangencia == "escola"
                else leitura.territorios.get(ln.codigo_territorio, ln.codigo_territorio))
        plano.append({"alvo": "ref", "avaliacao": n.avaliacao, "avaliacao_id": avaliacao_id,
                      "chave": _chave_ref(ln), "tipo": tipo, "antes": antes, "depois": depois,
                      "linha": atual, "onde": onde, "imp_atual": atual_imp})

    fonte = f"{fonte_curta or _fonte_curta(leitura)} — {arquivo_nome}"[:200]
    for ln in leitura.escolares:
        avaliacao_id = avaliacoes[ln.avaliacao]
        depois = {"valor": ln.valor, "unidade": ln.unidade, "motivo_ausencia": ln.motivo_ausencia,
                  "fonte": fonte, "importacao_id": imp.id, "codigo_inep": ln.codigo_inep,
                  "rede_id": ln.rede_id}
        atual = existentes_esc.get((avaliacao_id, *ln.chave))
        atual_imp = imps.get(atual.importacao_id) if atual is not None else None
        if atual is None:
            tipo, antes = "nova", None
        else:
            antes = _estado(atual, _ESTADO_ESC)
            if atual.importacao_id is None:
                if manual_igual_fica and all(antes[c] == depois[c] for c in _VALOR_ESC):
                    tipo = "igual"      # o mesmo número oficial, sem proveniência: fica
                else:
                    tipo = "substituicao"   # manual/calculado: só com resposta explícita (D2)
            else:
                tipo = _tipo(atual_imp, imp, antes, depois, _VALOR_ESC,
                             por_data=desempate_por_data)
        plano.append({"alvo": "esc", "avaliacao": ln.avaliacao, "avaliacao_id": avaliacao_id,
                      "chave": _chave_esc(ln), "tipo": tipo, "antes": antes, "depois": depois,
                      "linha": atual, "onde": nomes_escola.get(ln.escola_id) or
                      f"escola INEP {ln.codigo_inep}", "imp_atual": atual_imp})
    return plano


def _avisos_data_anterior(plano: list[dict], imp: ImportacaoIndicador) -> list[str]:
    """Na MESMA edição, números que já vieram de um arquivo com data interna mais nova
    (a versão retificada) ficam (``mantida``): a prévia diz por que este não os troca."""
    mais_novas: dict[int, ImportacaoIndicador] = {}
    n = 0
    for p in plano:
        atual = p.get("imp_atual")
        if p["tipo"] == "mantida" and _mais_nova_por_data(atual, imp):
            mais_novas[atual.id] = atual
            n += 1
    if not n:
        return []
    deste = (f"é de {imp.arquivo_data:%d/%m/%Y %H:%M}" if imp.arquivo_data
             else "não tem data interna")
    ja = "; ".join(f"#{i.id} — {i.arquivo_nome}, de {i.arquivo_data:%d/%m/%Y %H:%M}"
                   for i in sorted(mais_novas.values(), key=lambda i: i.id))
    return [f"Arquivo de data anterior à do já aplicado nesta edição ({imp.edicao_arquivo}): "
            f"o deste pacote {deste}, e o já aplicado ({ja}) é mais novo — a versão "
            f"retificada. {n} número(s) ficam como estão (“mantida”): vale o arquivo mais "
            "recente."]


def _fonte_curta(leitura: seduc.LeituraSeduc) -> str:
    e = leitura.edicao_arquivo
    if leitura.parser == seduc.PARSER_IEE:
        return f"SARESP {e} oficial (SEDUC-SP, IEE {e}-{e + 1})"
    return f"SARESP {e} oficial (SEDUC-SP)"


def _contadores(plano: list[dict], leitura: seduc.LeituraSeduc) -> dict:
    tipos = [p["tipo"] for p in plano]
    # Números por escola sem proveniência oficial que BATEM com o oficial e ficam como
    # estão (só na família que aceita isso — ver ``Familia.manual_igual_fica``).
    iguais_sem = sum(1 for p in plano if p["tipo"] == "igual" and p["alvo"] == "esc"
                     and (p["antes"] or {}).get("importacao_id") is None)
    return {
        **({"iguais_sem_proveniencia": iguais_sem} if iguais_sem else {}),
        "lidas": leitura.linhas_lidas,
        "recortadas": len(plano),
        "novas": tipos.count("nova"), "alteradas": tipos.count("alterada"),
        "iguais": tipos.count("igual"), "mantidas": tipos.count("mantida"),
        "substituicoes": tipos.count("substituicao"),
        "ausentes": sum(1 for p in plano if p["depois"]["valor"] is None),
        "escolas_casadas": len(leitura.escolas_casadas),
        "fora_do_cadastro": len(leitura.fora_do_cadastro),
        "territorios": len({n.linha.codigo_territorio for n in leitura.referencia}),
    }


def _mudancas(plano: list[dict]) -> list[dict]:
    saida = []
    for p in plano:
        if p["tipo"] == "igual":
            continue
        antes = p["antes"] or {}
        chave = p["chave"]
        saida.append({
            "alvo": "escola" if p["alvo"] == "esc" else "referencia",
            "tipo": p["tipo"], "avaliacao": p["avaliacao"], "onde": p["onde"],
            "abrangencia": chave.get("abrangencia", "escola"),
            "rede_ensino": chave.get("rede_ensino"), "codigo_inep": (
                chave.get("codigo_inep") or p["depois"].get("codigo_inep") or None),
            "indicador": chave["indicador"], "edicao": chave["edicao"],
            "etapa": chave["etapa"] or None, "componente": chave["componente"] or None,
            # Só nos números de referência (o Saeb da planilha: localização e nível).
            "localizacao": chave.get("localizacao"), "nivel": chave.get("nivel") or None,
            "antes": antes.get("valor"), "antes_motivo": antes.get("motivo_ausencia"),
            "antes_fonte": antes.get("fonte"),
            "depois": p["depois"]["valor"], "depois_motivo": p["depois"]["motivo_ausencia"],
        })
    saida.sort(key=lambda m: (m["alvo"], m["onde"] or "", m["indicador"], m["etapa"] or "",
                              m["componente"] or "", m["rede_ensino"] or "",
                              m["localizacao"] or "", int(m["nivel"] or -1), m["edicao"]))
    return saida


def _substituicoes(plano: list[dict]) -> list[dict]:
    """ANTES (número sem proveniência oficial — ex.: a média calculada pelo Constela)
    × DEPOIS (número oficial, ou a ausência dele) por escola."""
    saida = []
    for p in plano:
        if p["tipo"] != "substituicao":
            continue
        antes, depois = p["antes"], p["depois"]
        diferenca = (round(depois["valor"] - antes["valor"], 2)
                     if depois["valor"] is not None and antes["valor"] is not None else None)
        saida.append({
            "escola_id": p["chave"]["escola_id"], "escola": p["onde"],
            "codigo_inep": depois["codigo_inep"], "edicao": p["chave"]["edicao"],
            "etapa": p["chave"]["etapa"], "componente": p["chave"]["componente"],
            "antes": {"valor": antes["valor"], "fonte": antes["fonte"],
                      "motivo_ausencia": antes["motivo_ausencia"]},
            "depois": {"valor": depois["valor"], "motivo_ausencia": depois["motivo_ausencia"],
                       "fonte": depois["fonte"]},
            "diferenca": diferenca,
        })
    saida.sort(key=lambda s: (s["escola"] or "", s["edicao"], s["etapa"] or "",
                              s["componente"] or ""))
    return saida


def _assinatura_substituicoes(plano: list[dict]) -> list[list]:
    """O que a prévia mostrou como ANTES de cada substituição (D2): a chave do número
    por escola + valor, motivo, unidade e fonte do número sem proveniência oficial.
    O DEPOIS não entra: sai do mesmo arquivo (sha256), lido do mesmo jeito. Lista de
    listas, ordenada — cabe no JSON do ``resumo`` e volta comparável."""
    saida = []
    for p in plano:
        if p["tipo"] != "substituicao":
            continue
        chave, antes = p["chave"], p["antes"]
        saida.append([p["avaliacao_id"], chave["edicao"], chave["indicador"], chave["escola_id"],
                      chave["etapa"], chave["componente"], antes["valor"],
                      antes["motivo_ausencia"], antes["unidade"], antes["fonte"]])
    return sorted(saida, key=repr)


def _saida(imp: ImportacaoIndicador, *, plano: list[dict] | None = None) -> dict:
    resumo = imp.resumo or {}
    return {
        "id": imp.id, "status": imp.status, "parser": imp.parser, "modo": imp.modo,
        "arquivo_nome": imp.arquivo_nome, "arquivo_sha256": imp.arquivo_sha256,
        "edicao_arquivo": imp.edicao_arquivo, "versao_rotulo": imp.versao_rotulo,
        "url_origem": imp.url_origem, "last_modified_origem": imp.last_modified_origem,
        "codigo_territorio_alvo": imp.codigo_territorio_alvo,
        "fonte_nome": imp.fonte_nome, "citacao": imp.citacao, "licenca": imp.licenca,
        "contadores": imp.contadores or {}, "avisos": resumo.get("avisos", []),
        "territorios": resumo.get("territorios", {}),
        "escolas_casadas": resumo.get("escolas_casadas", []),
        "fora_do_cadastro": resumo.get("fora_do_cadastro", []),
        "colunas_ignoradas": resumo.get("colunas_ignoradas", []),
        "encoding": resumo.get("encoding"),
        "pacote_sha256": imp.pacote_sha256,
        "arquivo_data": imp.arquivo_data.isoformat() if imp.arquivo_data else None,
        "created_at": imp.created_at.isoformat() if imp.created_at else None,
        "aplicado_em": imp.aplicado_em.isoformat() if imp.aplicado_em else None,
        "desfeito_em": imp.desfeito_em.isoformat() if imp.desfeito_em else None,
        # O que é só de uma família (Ideb: edições, cobertura, notas do arquivo...).
        **{k: resumo[k] for k in _EXTRAS_SAIDA if k in resumo},
        **({"mudancas": _mudancas(plano), "substituicoes": _substituicoes(plano)}
           if plano is not None else {}),
    }


_EXTRAS_SAIDA = ("edicoes", "anos_meta", "cobertura", "marcadores", "asteriscos",
                 "notas_arquivo", "sem_linha_no_arquivo", "pacote",
                 # Ideb do território (E6b) e planilha do Saeb (E7).
                 "abrangencia", "redes_no_arquivo", "colunas_repetidas", "universo_saeb",
                 "origem_edicao", "abas", "abas_ignoradas", "escala_niveis", "escala_tx")


def _versao_rotulo(nome: str) -> str | None:
    base = (nome or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1].rsplit(".", 1)[0]
    return base[:60] or None


# --- Prévia -------------------------------------------------------------------

def previa(db: Session, rede: Rede, conteudo: bytes, nome: str, *, usuario_id: int | None,
           edicao: int | None = None, url_origem: str | None = None,
           last_modified_origem: str | None = None,
           coletado_em: datetime | None = None, familia: Familia = SEDUC) -> dict:
    """Lê, recorta e compara com o banco; registra a importação como ``previa`` e
    NÃO grava número nenhum. LEVANTA ``ImportacaoRecusada``."""
    codigo = _exigir_codigo(rede)
    lido = familia.ler(db, rede, conteudo, nome, edicao)
    leitura = lido.leitura
    avaliacoes = _avaliacoes(db, leitura, familia)
    if lido.modo == "upload":
        arquivo_nome = (nome or "arquivo.csv")[:255]
        arquivo_sha256, arquivo_bytes = hashlib.sha256(conteudo).hexdigest(), len(conteudo)
        url_origem, last_modified_origem = (_texto(url_origem, 500),
                                            _texto(last_modified_origem, 64))
        versao = _versao_rotulo(nome)
    else:
        # Pacote: a origem é a do MANIFESTO (o arquivo do órgão), não a digitada.
        arquivo_nome = (lido.arquivo_nome or nome or "pacote.zip")[:255]
        arquivo_sha256, arquivo_bytes = lido.arquivo_sha256, lido.arquivo_bytes or 0
        url_origem, last_modified_origem = (_texto(lido.url_origem, 500),
                                            _texto(lido.last_modified_origem, 64))
        versao, coletado_em = lido.versao_rotulo, lido.coletado_em
    imp = ImportacaoIndicador(
        avaliacao_id=avaliacoes[familia.avaliacao_importacao], parser=leitura.parser,
        parser_versao=lido.versao_parser, fonte_nome=lido.fonte_nome,
        url_origem=url_origem, arquivo_nome=arquivo_nome,
        arquivo_sha256=arquivo_sha256, arquivo_bytes=arquivo_bytes,
        last_modified_origem=last_modified_origem, arquivo_data=lido.arquivo_data,
        edicao_arquivo=leitura.edicao_arquivo, versao_rotulo=versao,
        codigo_territorio_alvo=codigo, citacao=lido.citacao, licenca=lido.licenca,
        modo=lido.modo, status="previa", pacote_sha256=lido.pacote_sha256,
        usuario_id=usuario_id, coletado_em=coletado_em, contadores={}, resumo={})
    db.add(imp)
    db.flush()
    plano = _planejar(db, leitura, imp, avaliacoes, arquivo_nome, fonte_curta=lido.fonte_curta,
                      manual_igual_fica=familia.manual_igual_fica,
                      desempate_por_data=familia.desempate_por_data)
    if familia.desempate_por_data:
        leitura.avisos.extend(_avisos_data_anterior(plano, imp))
    imp.contadores = _contadores(plano, leitura)
    imp.resumo = {**_resumo(leitura, edicao, codmun=_codmun(rede),
                            substituicoes=_assinatura_substituicoes(plano)),
                  **lido.resumo_extra}
    return _saida(imp, plano=plano)


def _resumo(leitura: seduc.LeituraSeduc, edicao_informada: int | None, *,
            codmun: str | None, substituicoes: list[list]) -> dict:
    """``codmun_seduc`` (só no SARESP por município: o recorte que a prévia mostrou) e
    ``substituicoes_previa`` (a assinatura da D2) são conferidos na aplicação."""
    return {"avisos": list(leitura.avisos), "territorios": dict(leitura.territorios),
            "colunas_ignoradas": list(leitura.colunas_ignoradas),
            "encoding": leitura.encoding, "edicao_informada": edicao_informada,
            "escolas_casadas": list(leitura.escolas_casadas),
            "fora_do_cadastro": list(leitura.fora_do_cadastro),
            "codmun_seduc": (codmun if leitura.parser == seduc.PARSER_SARESP_MUNICIPIO
                             else None),
            "substituicoes_previa": substituicoes,
            **({"ponte_cie_inep": dict(leitura.ponte)} if leitura.ponte else {})}


def resumo_importacao(imp: ImportacaoIndicador) -> dict:
    return _saida(imp)


# --- Aplicação ----------------------------------------------------------------

def _da_rede(db: Session, rede: Rede, importacao_id: int,
             familia: Familia | None = None) -> ImportacaoIndicador:
    familia = familia or SEDUC
    imp = db.get(ImportacaoIndicador, importacao_id)
    if (imp is None or imp.parser not in familia.parsers
            or imp.codigo_territorio_alvo != codigo_ibge_da_rede(rede)):
        raise LookupError(f"Importação do {familia.rotulo} não encontrada para esta rede.")
    return imp


def aplicar(db: Session, rede: Rede, previa_id: int, conteudo: bytes, nome: str, *,
            usuario_id: int | None, substituir_calculadas: bool | None = None,
            familia: Familia = SEDUC) -> dict:
    """Grava o que a prévia mostrou (recalculado sobre o estado atual), numa
    transação só (o commit é do chamador). Reaplicar o mesmo arquivo não muda nada.

    O arquivo é relido com o NOME e a edição informada da PRÉVIA (``imp.arquivo_nome``),
    não com o ``nome`` deste envio: o sha256 não cobre o nome, e no SARESP por
    município e por instância a edição sai do nome — o mesmo conteúdo com outro nome
    seria gravado noutra edição, que a prévia não mostrou. No pacote, o sha256
    conferido é o do PACOTE enviado (``arquivo_sha256`` é o do arquivo do órgão)."""
    _exigir_codigo(rede)
    imp = _da_rede(db, rede, previa_id, familia)
    if imp.status != "previa":
        raise ImportacaoRecusada(
            f"Esta prévia já foi {'aplicada' if imp.status == 'aplicada' else imp.status}. "
            "Para importar de novo, gere uma prévia nova.")
    if hashlib.sha256(conteudo).hexdigest() != (imp.pacote_sha256 or imp.arquivo_sha256):
        raise ImportacaoRecusada(
            "O arquivo enviado não é o mesmo da prévia (sha256 diferente). Envie o mesmo "
            "arquivo, ou gere uma prévia nova. Nada foi gravado.")
    resumo_previa = imp.resumo or {}
    if imp.parser == seduc.PARSER_SARESP_MUNICIPIO:
        na_previa, agora_rede = resumo_previa.get("codmun_seduc"), _codmun(rede)
        if agora_rede != na_previa:
            raise ImportacaoRecusada(
                f"O código do município na SEDUC (CODMUN) da rede mudou desde a prévia "
                f"({na_previa or 'vazio'} → {agora_rede or 'vazio'}): a prévia mostrou o "
                "recorte de outro código. Gere uma prévia nova. Nada foi gravado.")
    edicao = resumo_previa.get("edicao_informada")
    lido = familia.ler(db, rede, conteudo, imp.arquivo_nome, edicao)
    leitura = lido.leitura
    if leitura.parser != imp.parser:
        raise ImportacaoRecusada("O arquivo não é do mesmo tipo da prévia. Nada foi gravado.")
    if leitura.edicao_arquivo != imp.edicao_arquivo:
        raise ImportacaoRecusada(
            f"A edição lida agora ({leitura.edicao_arquivo}) não é a da prévia "
            f"({imp.edicao_arquivo}). Gere uma prévia nova. Nada foi gravado.")
    avaliacoes = _avaliacoes(db, leitura, familia)
    plano = _planejar(db, leitura, imp, avaliacoes, imp.arquivo_nome,
                      fonte_curta=lido.fonte_curta, manual_igual_fica=familia.manual_igual_fica,
                      desempate_por_data=familia.desempate_por_data)
    if familia.desempate_por_data:
        leitura.avisos.extend(_avisos_data_anterior(plano, imp))
    assinatura = _assinatura_substituicoes(plano)
    vista = resumo_previa.get("substituicoes_previa") or []
    if assinatura != [list(item) for item in vista]:
        raise ImportacaoRecusada(
            "Os números por escola sem proveniência oficial que esta importação "
            f"substituiria mudaram desde a prévia (a prévia mostrou {len(vista)}; agora são "
            f"{len(assinatura)}, ou com outro ANTES). A resposta sobre substituí-los "
            "valeria para números que a prévia não mostrou: gere uma prévia nova. Nada "
            "foi gravado.")
    n_subst = len(assinatura)
    if n_subst and substituir_calculadas is None:
        raise ImportacaoRecusada(
            f"A importação substituiria {n_subst} número(s) por escola gravados SEM "
            "proveniência oficial (ex.: a média do SARESP calculada pelo Constela). "
            "Confira o antes × depois da prévia e responda explicitamente: substituir "
            "pelos números oficiais (decisão D2) ou manter os atuais. Nada foi gravado.")
    agora = _agora()
    criadas, alteradas, recusadas = [], [], 0
    for p in plano:
        if p["tipo"] in ("igual", "mantida"):
            continue
        if p["tipo"] == "substituicao" and not substituir_calculadas:
            recusadas += 1
            continue
        if p["tipo"] == "nova":
            criadas.append(_criar(db, p, agora))
            continue
        alteradas.append(_alterar(p, agora))
    imp.status = "aplicada"
    imp.aplicado_em = agora
    imp.usuario_id = usuario_id or imp.usuario_id
    imp.contadores = {**_contadores(plano, leitura),
                      "substituicoes_aplicadas": n_subst - recusadas,
                      "substituicoes_mantidas": recusadas}
    imp.resumo = {**_resumo(leitura, edicao, codmun=_codmun(rede), substituicoes=assinatura),
                  **lido.resumo_extra,
                  "substituir_calculadas": substituir_calculadas,
                  # As etapas de TODAS as chaves do plano (iguais inclusive): a consulta
                  # do Saeb sabe se a planilha trouxe o 5º ano sem ler o ``desfazer``.
                  "etapas_vistas": sorted({p["chave"].get("etapa") or "" for p in plano})}
    # Fora do ``resumo`` (coluna própria, ``deferred``): as consultas não o leem.
    # ``chaves``: TODAS as que o plano viu (inclusive iguais e mantidas) — decidem o
    # conflito no desfazer de uma importação anterior.
    imp.desfazer = {"criadas": criadas, "alteradas": alteradas,
                    "chaves": [_chave_guardada(p) for p in plano]}
    db.flush()
    return _saida(imp, plano=plano)


def _chave_guardada(p: dict) -> dict:
    return {"alvo": p["alvo"], "avaliacao_id": p["avaliacao_id"], **p["chave"]}


def _criar(db: Session, p: dict, agora: datetime) -> dict:
    chave, depois = p["chave"], p["depois"]
    if p["alvo"] == "ref":
        db.add(IndicadorReferencia(avaliacao_id=p["avaliacao_id"], **chave, **depois,
                                   created_at=agora, updated_at=agora))
    else:
        db.add(ResultadoAvaliacao(avaliacao_id=p["avaliacao_id"], **chave, **depois,
                                  created_at=agora))
    return {"chave": _chave_guardada(p), "depois": depois}


def _alterar(p: dict, agora: datetime) -> dict:
    linha = p["linha"]
    antes = dict(p["antes"])
    if p["alvo"] == "ref":
        antes["updated_at"] = _isoformat(linha.updated_at)
        linha.updated_at = agora
    for campo, valor in p["depois"].items():
        setattr(linha, campo, valor)
    return {"chave": _chave_guardada(p), "antes": antes, "depois": p["depois"],
            "tipo": p["tipo"]}


# --- Desfazer -----------------------------------------------------------------

def _linhas_atuais(db: Session, chaves: list[dict]) -> dict[tuple, object]:
    """As linhas de HOJE de todas as chaves do plano (``_tupla_guardada`` → linha), num
    SELECT por tabela filtrado pelos conjuntos do plano — e não um SELECT por número
    (milhares no Ideb por escola). Na escola, dimensão vazia (o Ideb não tem
    componente; nenhuma tem turma) casa nulo OU '' — a regra do
    ``uq_resultado_natural`` (COALESCE), que também garante uma linha por tupla."""
    saida: dict[tuple, object] = {}
    refs = [c for c in chaves if c["alvo"] == "ref"]
    if refs:
        for linha in db.execute(select(IndicadorReferencia).where(
                IndicadorReferencia.avaliacao_id.in_({c["avaliacao_id"] for c in refs}),
                IndicadorReferencia.codigo_territorio.in_({c["codigo_territorio"] for c in refs}),
                IndicadorReferencia.edicao.in_({c["edicao"] for c in refs}),
                IndicadorReferencia.indicador.in_({c["indicador"] for c in refs}))).scalars():
            saida[_tupla("ref", linha.avaliacao_id, _chave_ref(linha))] = linha
    escolares = [c for c in chaves if c["alvo"] != "ref"]
    if escolares:
        for linha in db.execute(select(ResultadoAvaliacao).where(
                ResultadoAvaliacao.avaliacao_id.in_({c["avaliacao_id"] for c in escolares}),
                ResultadoAvaliacao.escola_id.in_({c["escola_id"] for c in escolares}),
                ResultadoAvaliacao.edicao.in_({c["edicao"] for c in escolares}),
                ResultadoAvaliacao.indicador.in_({c["indicador"] for c in escolares}),
                or_(ResultadoAvaliacao.turma.is_(None), ResultadoAvaliacao.turma == ""),
        )).scalars():
            saida[_tupla("esc", linha.avaliacao_id, {
                "edicao": linha.edicao, "indicador": linha.indicador,
                "escola_id": linha.escola_id, "etapa": linha.etapa,
                "componente": linha.componente, "turma": linha.turma})] = linha
    return saida


def _mesmo_estado(linha, esperado: dict, alvo: str) -> bool:
    campos = _ESTADO_REF if alvo == "ref" else _ESTADO_ESC
    return all(getattr(linha, c) == esperado.get(c) for c in campos)


def _tupla_guardada(chave: dict) -> tuple:
    return _tupla(chave["alvo"], chave["avaliacao_id"], chave)


def _tocadas(imp: ImportacaoIndicador) -> set[tuple]:
    plano = plano_desfazer(imp) or {}
    return {_tupla_guardada(item["chave"])
            for item in [*plano.get("criadas", []), *plano.get("alteradas", [])]}


def _vistas(imp: ImportacaoIndicador) -> set[tuple]:
    plano = plano_desfazer(imp) or {}
    return {_tupla_guardada(c) for c in plano.get("chaves", [])}


def _posicao(imp: ImportacaoIndicador) -> tuple:
    return (imp.aplicado_em or _MINIMO, imp.id or 0)


def _aplicadas(db: Session, parsers: tuple[str, ...] = seduc.PARSERS) -> list[ImportacaoIndicador]:
    return sorted(db.execute(select(ImportacaoIndicador).where(
        ImportacaoIndicador.parser.in_(parsers),
        ImportacaoIndicador.status == "aplicada")).scalars(), key=_posicao)


def _conflito(imp: ImportacaoIndicador, posteriores: list[ImportacaoIndicador],
              vistas_de: dict[int, set[tuple]] | None = None):
    """``vistas_de``: cache (id → chaves vistas) entre chamadas — a lista confere cada
    importação contra as MESMAS posteriores, sem remontar o conjunto delas a cada uma."""
    tocadas = _tocadas(imp)
    if not tocadas:
        return None
    cache = {} if vistas_de is None else vistas_de
    for posterior in posteriores:
        if posterior.id not in cache:
            cache[posterior.id] = _vistas(posterior)
        comuns = tocadas & cache[posterior.id]
        if comuns:
            return posterior, len(comuns)
    return None


_MSG_ESTADO_MUDOU = ("Os números desta importação já não estão como ela os deixou; desfazer "
                     "agora não voltaria ao estado anterior. Nada foi alterado.")


def desfazer(db: Session, rede: Rede, importacao_id: int, *, usuario_id: int | None,
             familia: Familia = SEDUC) -> dict:
    """Volta EXATAMENTE ao estado anterior à aplicação (o commit é do chamador): apaga
    o que a importação criou e restaura o que alterou — inclusive a média calculada
    que ela substituiu (valor e fonte antigos, sem ``importacao_id``)."""
    imp = _da_rede(db, rede, importacao_id, familia)
    if imp.status != "aplicada":
        raise ImportacaoRecusada(
            f"Só uma importação APLICADA pode ser desfeita (esta está como “{imp.status}”).")
    posteriores = [i for i in _aplicadas(db, familia.parsers) if _posicao(i) > _posicao(imp)]
    carregar_planos(db, [imp, *posteriores])         # um SELECT, não um por importação
    if plano_desfazer(imp) is None:
        raise ImportacaoRecusada(MSG_SEM_PLANO)
    conflito = _conflito(imp, posteriores)
    if conflito:
        posterior, n = conflito
        raise ImportacaoRecusada(
            f"A importação #{posterior.id} ({posterior.arquivo_nome}), aplicada depois desta, "
            f"usa {n} dos números que esta importação gravou. Desfazer esta agora não "
            f"voltaria exatamente ao estado anterior: desfaça antes a #{posterior.id}. Nada "
            "foi alterado.")
    plano = plano_desfazer(imp) or {}
    atuais = _linhas_atuais(db, [item["chave"] for item in (*plano.get("criadas", []),
                                                            *plano.get("alteradas", []))])
    alvos = []
    for item in plano.get("criadas", []):
        linha = atuais.get(_tupla_guardada(item["chave"]))
        if linha is None or not _mesmo_estado(linha, item["depois"], item["chave"]["alvo"]):
            raise ImportacaoRecusada(_MSG_ESTADO_MUDOU)
        alvos.append(("apagar", linha, None, item["chave"]["alvo"]))
    for item in plano.get("alteradas", []):
        linha = atuais.get(_tupla_guardada(item["chave"]))
        if linha is None or not _mesmo_estado(linha, item["depois"], item["chave"]["alvo"]):
            raise ImportacaoRecusada(_MSG_ESTADO_MUDOU)
        alvos.append(("restaurar", linha, item["antes"], item["chave"]["alvo"]))
    # Conferido TUDO antes de mexer em qualquer linha (ou desfaz tudo, ou nada).
    for acao, linha, antes, alvo in alvos:
        if acao == "apagar":
            db.delete(linha)
            continue
        for campo in (_ESTADO_REF if alvo == "ref" else _ESTADO_ESC):
            setattr(linha, campo, antes[campo])
        if alvo == "ref" and antes.get("updated_at"):
            linha.updated_at = datetime.fromisoformat(antes["updated_at"])
    imp.status = "desfeita"
    imp.desfeito_em = _agora()
    imp.contadores = {**(imp.contadores or {}), "desfeitas": len(alvos)}
    db.flush()
    return _saida(imp)


def listar(db: Session, rede: Rede, *, familia: Familia = SEDUC) -> list[dict]:
    """Importações da família (SARESP/IEE por padrão) desta rede (mais recentes primeiro)."""
    codigo = codigo_ibge_da_rede(rede)
    if codigo is None:
        return []
    linhas = db.execute(
        select(ImportacaoIndicador)
        .where(ImportacaoIndicador.parser.in_(familia.parsers),
               ImportacaoIndicador.codigo_territorio_alvo == codigo)
        .order_by(ImportacaoIndicador.created_at.desc(), ImportacaoIndicador.id.desc())
        .limit(50)).scalars().all()
    aplicadas = _aplicadas(db, familia.parsers)
    # Os planos (coluna deferred) que a lista lê, num SELECT — não um por importação.
    carregar_planos(db, planos_da_lista(linhas, aplicadas))
    vistas_de: dict[int, set[tuple]] = {}
    saida = []
    for i in linhas:
        bloqueio = None
        if i.status == "aplicada":
            conflito = _conflito(i, [p for p in aplicadas if _posicao(p) > _posicao(i)],
                                 vistas_de)
            bloqueio = conflito[0].id if conflito else None
        saida.append({**_saida(i), "pode_desfazer": (i.status == "aplicada" and bloqueio is None
                                                     and plano_desfazer(i) is not None),
                      "bloqueada_por": bloqueio})
    return saida


def ponte_cie_inep(db: Session, rede: Rede) -> dict[str, dict]:
    """CIE → INEP das escolas do município da rede, pelas importações APLICADAS do
    IEE (a mais nova vence; divergência entre edições fica marcada). É a ponte que
    o ``seduc_saresp_escola`` (só CIE) vai usar quando entrar."""
    codigo = codigo_ibge_da_rede(rede)
    if codigo is None:
        return {}
    imps = db.execute(select(ImportacaoIndicador).where(
        ImportacaoIndicador.parser == seduc.PARSER_IEE,
        ImportacaoIndicador.status == "aplicada",
        ImportacaoIndicador.codigo_territorio_alvo == codigo)).scalars().all()
    ponte: dict[str, dict] = {}
    for imp in sorted(imps, key=lambda i: (i.edicao_arquivo, i.id)):
        for cie, inep in ((imp.resumo or {}).get("ponte_cie_inep") or {}).items():
            anterior = ponte.get(cie)
            ponte[cie] = {"codigo_inep": inep, "edicao": imp.edicao_arquivo,
                          "divergente": bool(anterior and anterior["codigo_inep"] != inep)}
    return ponte
