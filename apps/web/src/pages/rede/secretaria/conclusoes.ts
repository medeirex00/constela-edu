/**
 * As FRASES-CONCLUSÃO das telas principais da Secretaria (DESENHO2 §1.1 "conclusão primeiro"):
 * funções puras que transformam a resposta da API na frase que diz o que o número significa —
 * "ICA 2025: 58% — abaixo da meta de 60%." —, antes de qualquer detalhe.
 *
 * Regras de todas elas: ausência por extenso (nunca 0); a precisão é a que a API manda; nada
 * de causalidade (a frase descreve, não explica o porquê); escolas sempre em ordem alfabética.
 */
import { colunasDaComparacao, oficiaisNaReferencia, type ColunaDaComparacao } from "../../analise/AvaliacoesExternas";
import { decimal, diaBR, porNome, rotuloComponente, rotuloEtapa, rotuloSerie, valorComUnidade } from "../../analise/formato";
import type {
  DestaqueAnalise, IndicadorAnalise, JanelaAnalise, RespostaIndicadoresRede, RespostaPlataformas, SituacaoMeta,
} from "../../analise/tipos";
import type { RespostaDiagnostico } from "../../analise/tiposDiagnostico";
import { explicacaoDe } from "./oQueMede";
import type { EstadoUso } from "./situacaoDeUso";
import { anoDaJanela } from "./useRedeDaPagina";

const pct = (v: number | null | undefined) => (v == null ? null : `${decimal(v, 1)}%`);
const ETAPA_CURTA: Record<string, string> = { "2_ano": "2º ano", "5_ano": "5º ano" };

/** "(5º ano, Língua Portuguesa)" — o recorte de um destaque (o ICA é sempre do 2º ano, em
 *  Língua Portuguesa, e o Ideb, dos anos iniciais: aí a sigla basta, o "O que mede" diz). */
function recorteDoDestaque(d: DestaqueAnalise): string {
  if (d.indicador === "ica") return "";
  const partes = [
    d.etapa ? ETAPA_CURTA[d.etapa] ?? null : null,
    d.componente ? rotuloComponente(d.componente) : null,
  ].filter(Boolean);
  return partes.length ? ` (${partes.join(", ")})` : "";
}

/** "atingiu a meta de 60%" / "abaixo da meta de 60%" / "igual à meta de 60% na precisão divulgada". */
export function situacaoDaMetaEmTexto(situacao: SituacaoMeta | null, meta: string): string {
  if (situacao === "atingiu") return `atingiu a meta de ${meta}`;
  if (situacao === "nao_atingiu") return `abaixo da meta de ${meta}`;
  return `igual à meta de ${meta} na precisão divulgada`;
}

/** "SARESP 2025 (5º ano, Língua Portuguesa)" — a sigla, a edição e o recorte da série. */
export function nomeDoDestaque(d: DestaqueAnalise, catalogo: RespostaIndicadoresRede): string {
  const sigla = explicacaoDe(d.indicador)?.sigla
    ?? catalogo.indicadores.find((i) => i.chave === d.indicador)?.nome ?? d.indicador.toUpperCase();
  return `${sigla} ${d.edicao}${recorteDoDestaque(d)}`;
}

/** A conclusão das avaliações no Panorama: a do primeiro destaque COM meta (a meta diz se o
 *  resultado está bom); sem meta nenhuma, o resultado oficial de edição mais nova (os destaques
 *  vêm na ordem fixa dos indicadores, não por edição; no empate, fica a ordem fixa) — e o "sem
 *  meta" diz se falta a meta só daquela edição (o indicador tem meta) ou se não há meta oficial. */
export function conclusaoAvaliacoes(destaques: DestaqueAnalise[], catalogo: RespostaIndicadoresRede): string {
  const comValor = destaques.filter((d) => d.valor != null);
  if (comValor.length === 0) return "Nenhum resultado oficial da rede importado ainda.";
  const comMeta = comValor.find((d) => d.meta != null && d.situacao_meta != null);
  const d = comMeta ?? comValor.reduce((a, b) => (b.edicao > a.edicao ? b : a));
  const valor = valorComUnidade(d.valor as number, d.casas, d.unidade);
  const nome = nomeDoDestaque(d, catalogo);
  if (!comMeta) {
    const temMeta = catalogo.indicadores.find((i) => i.chave === d.indicador)?.tem_meta;
    return `Resultado oficial mais recente: ${nome}: ${valor} (${temMeta ? "sem meta para esta edição" : "sem meta oficial"}).`;
  }
  const meta = valorComUnidade(d.meta as number, d.meta_casas ?? d.casas, d.unidade);
  return `${nome}: ${valor} — ${situacaoDaMetaEmTexto(d.situacao_meta, meta)}.`;
}

/** A conclusão do cartão de UM indicador (Avaliações externas): o resultado da rede na edição
 *  mais recente e a meta; no indicador só por escola (IEE), que ele é por escola. Quando a edição
 *  mais recente importada não tem número oficial da rede, a frase diz — senão "Rede em 2021" ao
 *  lado de "Edição mais recente: 2023" parece contradição. */
export function conclusaoIndicador(ind: IndicadorAnalise, c: RespostaIndicadoresRede): string {
  const d = c.destaques.find((x) => x.indicador === ind.chave && x.valor != null);
  if (d) {
    const valor = valorComUnidade(d.valor as number, d.casas, d.unidade);
    const depois = ind.edicao_mais_recente != null && ind.edicao_mais_recente > d.edicao
      ? ` Na edição de ${ind.edicao_mais_recente}, não há resultado oficial da rede.` : "";
    if (d.meta == null || !d.situacao_meta) {
      return `Rede em ${d.edicao}${recorteDoDestaque(d)}: ${valor}${ind.tem_meta ? " (sem meta para esta edição)" : ""}.${depois}`;
    }
    const meta = valorComUnidade(d.meta, d.meta_casas ?? d.casas, d.unidade);
    return `Rede em ${d.edicao}${recorteDoDestaque(d)}: ${valor} — ${situacaoDaMetaEmTexto(d.situacao_meta, meta)}.${depois}`;
  }
  const ultima = ind.edicao_mais_recente != null ? ` Edição mais recente: ${ind.edicao_mais_recente}.` : "";
  if (!ind.abrangencias.includes("rede")) {
    return `Por escola: cada escola tem o seu resultado${ind.tem_meta ? " e a sua meta" : ""} (não existe número da rede).${ultima}`;
  }
  return `Só há resultado por escola importado (sem número oficial da rede).${ultima}`;
}

/** É a janela do ano letivo inteiro? (o serviço manda o preset; o rótulo é o plano B). */
const ehAnoLetivo = (j: JanelaAnalise) => j.preset === "ano_letivo" || (!j.preset && /^ano letivo/i.test(j.rotulo));

/** "No ano letivo de 2026" ou "No período (este mês, de 01/10/2026 a 31/10/2026)". */
export function quandoDaJanela(j: JanelaAnalise): string {
  const ano = anoDaJanela(j);
  if (ehAnoLetivo(j)) return ano != null ? `No ano letivo de ${ano}` : "No ano letivo";
  const datas = j.inicio && j.fim ? `, de ${diaBR(j.inicio)} a ${diaBR(j.fim)}` : "";
  return `No período (${j.rotulo.toLowerCase()}${datas})`;
}

/** A participação da rede escondida para proteger um grupo pequeno (`metricas_protegidas`):
 *  "protegida", não "sem dado" — o número existe e não aparece. */
const participacaoProtegida = (bloco: { metricas_protegidas?: string[] } | null | undefined) =>
  (bloco?.metricas_protegidas ?? []).includes("participacao_pct");

/** "No ano letivo de 2026, 70% dos alunos com conta leram ao menos um livro no Elefante e 80% …"
 *  (com uma série escolhida: "No ano letivo de 2026, no 2º ano, …" — a frase diz o recorte). Sem
 *  o número, a frase separa a participação protegida (poucos alunos) da que ficou sem dado. */
export function conclusaoPlataformas(p: RespostaPlataformas, serie: number | null = null): string {
  const quando = `${quandoDaJanela(p.janela)}${serie != null ? `, no ${rotuloSerie(serie)}` : ""}`;
  if (!p.modulos.elefante && !p.modulos.matific) return "A rede não tem Elefante nem Matific contratado.";
  if (p.rede.suprimido) return `${quando}, os números da rede ficam ocultos: poucos alunos, para proteger as crianças.`;
  const partes: string[] = [];
  if (p.modulos.elefante) {
    const v = pct(p.rede.elefante?.participacao_pct);
    partes.push(v ? `${v} dos alunos com conta leram ao menos um livro no Elefante`
      : participacaoProtegida(p.rede.elefante) ? "a participação no Elefante fica protegida (poucos alunos)"
        : "o Elefante ficou sem dado");
  }
  if (p.modulos.matific) {
    const v = pct(p.rede.matific?.participacao_pct);
    partes.push(v ? `${v} dos alunos com dado no período fizeram ao menos uma atividade no Matific`
      : participacaoProtegida(p.rede.matific) ? "a participação no Matific fica protegida (poucos alunos)"
        : "o Matific ficou sem dado");
  }
  return `${quando}, ${partes.join(" e ")}.`;
}

/**
 * DESENHO3 §2.2 — "6 escolas cadastradas, 5 ativas no cadastro; 3 com uso do Constela no ano
 * letivo de 2026." Cadastradas, ativas e com uso por extenso e separados (não são sinônimos);
 * sem a leitura do uso (`comUso` null), só o cadastro.
 */
export function conclusaoRedeNoConstela(cadastradas: number, ativas: number, comUso: number | null,
                                        ano: number | null): string {
  if (cadastradas === 0) return "Nenhuma escola cadastrada na rede ainda.";
  const escolas = `${cadastradas} ${cadastradas === 1 ? "escola cadastrada" : "escolas cadastradas"}`;
  const ativasTexto = ativas === 0 ? "nenhuma ativa no cadastro" : `${ativas} ${ativas === 1 ? "ativa" : "ativas"} no cadastro`;
  if (comUso == null) return `${escolas}, ${ativasTexto}.`;
  const quando = ano != null ? `no ano letivo de ${ano}` : "no ano letivo";
  const uso = comUso === 0 ? "nenhuma" : String(comUso);
  return `${escolas}, ${ativasTexto}; ${uso} com uso do Constela ${quando}.`;
}

/** "1 sem uso registrado · 1 sem uso registrado até 15/03/2026 (coleta parcial) · 1 sem dado ·
 *  1 protegida" — as escolas sem uso, por situação, por extenso (sem nenhuma: "nenhuma").
 *  `semUsoParcial`: a data de cada escola "sem uso registrado" com coleta PARCIAL (`ateGeral`;
 *  null sem a data) — elas saem da conta em dia e aparecem com a data, a mais antiga primeiro. */
export function textoDemaisSituacoes(conta: Record<EstadoUso, number>,
                                     semUsoParcial: readonly (string | null)[] = []): string {
  const porData = new Map<string | null, number>();
  for (const d of semUsoParcial) porData.set(d, (porData.get(d) ?? 0) + 1);
  const chave = (d: string | null) => (d == null ? "99999999" : d.split("/").reverse().join(""));
  const parciais = [...porData.entries()]
    .sort(([a], [b]) => chave(a).localeCompare(chave(b)))
    .map(([d, n]) => `${n} sem uso registrado ${d ? `até ${d} ` : ""}(coleta parcial)`);
  const emDia = conta.sem_uso - semUsoParcial.length;
  const partes = [
    emDia > 0 ? `${emDia} sem uso registrado` : null,
    ...parciais,
    conta.sem_dado > 0 ? `${conta.sem_dado} sem dado` : null,
    conta.protegido > 0 ? `${conta.protegido} ${conta.protegido === 1 ? "protegida" : "protegidas"}` : null,
  ].filter(Boolean);
  return partes.length ? partes.join(" · ") : "nenhuma";
}

/** "1 escola ficou fora desta lista para proteger as crianças: o número dela fica protegido
 *  (poucos alunos)." — os destaques que a Secretaria não vê (`fora_por_protecao`), abaixo de uma
 *  lista COM escolas (a lista vazia tem a frase própria: `textoDestaquesVazio`). */
export function textoForaPorProtecao(n: number): string | null {
  if (n <= 0) return null;
  return n === 1
    ? "1 escola ficou fora desta lista para proteger as crianças: o número dela fica protegido (poucos alunos)."
    : `${n} escolas ficaram fora desta lista para proteger as crianças: o número delas fica protegido (poucos alunos).`;
}

/** A lista de destaques VAZIA, numa frase só: sem escola com dados suficientes; ou, quando as que
 *  entrariam ficaram TODAS fora para proteger as crianças (`fora_por_protecao`), isso — elas têm
 *  dados, só estão protegidas. */
export function textoDestaquesVazio(foraPorProtecao: number): string {
  if (foraPorProtecao <= 0) return "Nenhuma escola com dados suficientes para este critério ainda.";
  return foraPorProtecao === 1
    ? "Nenhuma escola aparece nesta lista: a única que entraria ficou fora para proteger as crianças — o número "
      + "dela fica protegido (poucos alunos)."
    : `Nenhuma escola aparece nesta lista: as ${foraPorProtecao} que entrariam ficaram fora para proteger as `
      + "crianças — o número delas fica protegido (poucos alunos).";
}

/** A descrição do "Reconhecimento público": a vitrine usa o MESMO critério dos destaques; quando
 *  alguma escola ficou fora dos destaques para proteger as crianças (`fora_por_protecao`, só a
 *  Secretaria), a frase diz que a lista daqui tem menos escolas que a vitrine. */
export function textoReconhecimentoPublico(foraPorProtecao: number): string {
  const base = "A vitrine pública usa o mesmo critério das escolas em destaque e as mostra num link aberto — sem "
    + "login e sem nome de criança.";
  if (foraPorProtecao <= 0) return base;
  return `${base} Os destaques acima têm menos escolas que a vitrine: aqui fica de fora a escola com o número `
    + "protegido (poucos alunos).";
}

/** As escolas com ao menos um sinal de ATENÇÃO nas avaliações ou nas plataformas (os sinais de
 *  "dados" são informativos e nunca contam aqui). Em ordem alfabética. */
export function escolasComAtencao(diag: RespostaDiagnostico) {
  return porNome(diag.escolas).filter((e) => e.sinais.some(
    (s) => s.direcao === "atencao" && (s.eixo === "avaliacao" || s.eixo === "plataforma")));
}

/** "3 de 4 escolas têm algum sinal de atenção." (sem sinal: diz isso, sem afirmar que vai bem). */
export function conclusaoAcompanhamento(diag: RespostaDiagnostico): string {
  const total = diag.escolas.length;
  const n = escolasComAtencao(diag).length;
  if (total === 0) return "A rede não tem escolas cadastradas.";
  if (n === 0) return "Nenhuma escola com sinal de atenção nesta leitura.";
  return `${n} de ${total} escolas ${n === 1 ? "tem" : "têm"} algum sinal de atenção.`;
}

/** "a", "a e b", "a, b e c". */
const emLista = (itens: string[]) =>
  (itens.length <= 1 ? itens.join("") : `${itens.slice(0, -1).join(", ")} e ${itens[itens.length - 1]}`);

/** O recorte de uma série na frase: "no 5º ano", "nos anos iniciais" — e o componente quando a
 *  mesma etapa aparece em mais de uma edição ("no 5º ano em Matemática"). */
function recorteDaColuna(c: ColunaDaComparacao, comComponente: boolean): string {
  const etapa = !c.etapa ? "" : c.etapa === "anos_iniciais" ? "nos anos iniciais"
    : `no ${ETAPA_CURTA[c.etapa] ?? rotuloEtapa(c.etapa)}`;
  const componente = comComponente && c.componente ? `em ${rotuloComponente(c.componente)}` : "";
  return [etapa, componente].filter(Boolean).join(" ");
}

/** "IEE 2025, Ideb 2023, SARESP 2025" — a edição de referência de cada avaliação, na ordem da
 *  tabela. Avaliação com edições de referência diferentes entre as séries (o 5º ano já tem 2025 e
 *  o 2º ano, só 2024): cada edição com o seu recorte — "SARESP 2025 no 5º ano e 2024 no 2º ano"
 *  (e as avaliações separadas por ";", para a frase não embaralhar). */
function edicoesDeReferenciaEmTexto(colunas: ColunaDaComparacao[]): string {
  const porIndicador = new Map<string, ColunaDaComparacao[]>();
  for (const c of colunas) porIndicador.set(c.indicador, [...(porIndicador.get(c.indicador) ?? []), c]);
  let composta = false;
  const textos = [...porIndicador.entries()].map(([indicador, cs]) => {
    const sigla = explicacaoDe(indicador)?.sigla ?? indicador.toUpperCase();
    const edicoes = [...new Set(cs.map((c) => c.edicao))].sort((a, b) => b - a);
    if (edicoes.length === 1) return `${sigla} ${edicoes[0]}`;
    composta = true;
    // A mesma etapa em duas edições (LP numa, MT noutra): o componente desfaz a dúvida.
    const etapaRepetida = (etapa: string | null) =>
      new Set(cs.filter((c) => c.etapa === etapa).map((c) => c.edicao)).size > 1;
    const partes = edicoes.map((ed) => {
      const recortes = [...new Set(cs.filter((c) => c.edicao === ed)
        .map((c) => recorteDaColuna(c, etapaRepetida(c.etapa))).filter(Boolean))];
      return recortes.length ? `${ed} ${emLista(recortes)}` : String(ed);
    });
    return `${sigla} ${emLista(partes)}`;
  });
  return textos.join(composta ? "; " : ", ");
}

/**
 * "3 de 4 escolas têm resultado oficial na edição mais recente de cada avaliação (IEE 2025, Ideb
 * 2023, SARESP 2025). Em ao menos uma avaliação, 1 fica abaixo da rede municipal e 1 acima." —
 * a conclusão da tabela "Todas as escolas na edição mais recente de cada avaliação", com a MESMA
 * regra dela (não misturar edições): cada série conta só os resultados da sua edição de
 * referência, a mais recente com resultado entre as escolas. A escola que só tem resultado de
 * edição anterior não conta como "com resultado" nem entra no acima/abaixo: a frase diz quantas
 * são e que o último oficial delas fica na ficha da escola.
 */
export function conclusaoComparacaoAvaliacoes(d: RespostaDiagnostico): string {
  const total = d.escolas.length;
  if (total === 0) return "A rede não tem escolas cadastradas.";
  const colunas = colunasDaComparacao(d.escolas);
  if (colunas.length === 0) return "Nenhuma escola da rede tem resultado oficial importado ainda.";
  const naReferencia = d.escolas.map((e) => oficiaisNaReferencia(e, colunas));
  const com = naReferencia.filter((os) => os.length > 0).length;
  const soAnterior = d.escolas.filter((e, i) => e.oficiais.length > 0 && naReferencia[i].length === 0).length;
  const abaixo = naReferencia.filter((os) => os.some((o) => o.posicao_rede === "abaixo")).length;
  const acima = naReferencia.filter((os) => os.some((o) => o.posicao_rede === "acima")).length;
  // "nenhuma fica", não "0 ficam" (contagem de escolas por extenso, como o resto da frase).
  const quantas = (n: number) => (n === 0 ? "nenhuma fica" : `${n} ${n === 1 ? "fica" : "ficam"}`);
  const posicao = abaixo + acima > 0
    ? ` Em ao menos uma avaliação, ${quantas(abaixo)} abaixo da rede municipal e ${acima === 0 ? "nenhuma" : acima} acima.`
    : "";
  const anterior = soAnterior === 0 ? ""
    : soAnterior === 1
      ? " 1 escola só tem resultado de edição anterior: o último oficial dela fica na ficha da escola."
      : ` ${soAnterior} escolas só têm resultado de edição anterior: o último oficial de cada uma fica na ficha da escola.`;
  return `${com} de ${total} escolas ${com === 1 ? "tem" : "têm"} resultado oficial na edição mais recente de cada `
    + `avaliação (${edicoesDeReferenciaEmTexto(colunas)}).${posicao}${anterior}`;
}

/** "Ano letivo de 2026 (01/01/2026 a 31/12/2026): das 4 escolas, 3 com número do Elefante e 2 …". */
export function conclusaoComparacaoPlataformas(p: RespostaPlataformas, serie: number | null = null): string {
  const total = p.escolas.length;
  if (total === 0) return "Nenhuma escola da rede neste recorte.";
  if (!p.modulos.elefante && !p.modulos.matific) return "A rede não tem Elefante nem Matific contratado.";
  const visiveis = p.escolas.filter((e) => !e.suprimido);
  const partes = [
    p.modulos.elefante ? `${visiveis.filter((e) => e.elefante?.participacao_pct != null).length} com número do Elefante` : null,
    p.modulos.matific ? `${visiveis.filter((e) => e.matific?.participacao_pct != null).length} com número do Matific` : null,
  ].filter(Boolean);
  const datas = p.janela.inicio && p.janela.fim ? ` (${diaBR(p.janela.inicio)} a ${diaBR(p.janela.fim)})` : "";
  const recorte = serie != null ? `, ${rotuloSerie(serie)}` : "";
  return `${p.janela.rotulo}${datas}${recorte}: das ${total} escolas, ${partes.join(" e ")}.`;
}
