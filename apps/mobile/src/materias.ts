/**
 * Notas e rankings POR MATÉRIA no app (Arquitetura 2) — a lógica pura das três
 * telas que exibiam a nota geral composta (Painel, Ranking e Perfil do aluno).
 *
 * Por que um módulo próprio, sem React Native: é aqui que moram as regras que
 * não podem escorregar, e elas precisam ser testadas com o código REAL no
 * Vitest (ambiente Node), como a cifra e a fila offline:
 *
 *  * o app NUNCA compõe nota entre matérias nem calcula posição — ele mostra a
 *    nota e a posição que o servidor carimbou em cada matéria (compor é
 *    justamente o que a Arquitetura 2 elimina);
 *  * AUSÊNCIA ≠ ZERO: sem dado da plataforma, a matéria mostra "—". O "0,0"
 *    fica reservado ao zero legítimo (o aluno usa a plataforma e ainda não
 *    produziu), que é outra afirmação, e verdadeira;
 *  * CONTRATO → DADO: matéria fora do plano da rede não vira "—" — ela some,
 *    porque ninguém é "sem dado" num produto que a rede não comprou;
 *  * O ALUNO NÃO SOME: quem sai do ranking da matéria por não ter dado entra
 *    na lista "Ainda não aferidos em <matéria>" — sem nota e sem posição —,
 *    que é a lista de ação da coordenação e a porta do app para o perfil dele;
 *  * COMPATIBILIDADE: o app guarda o pacote de sincronização no cache cifrado
 *    por até uma semana e pode falar com um servidor anterior durante o
 *    rollout. Campo ausente degrada para uma MENSAGEM — nunca para um crash e
 *    nunca de volta para a nota composta.
 *
 * Referências: docs/spec-arquitetura-2.md §1.2, §2.4, §3.5, §10.6 e
 * docs/plano-retirada-nota-geral.md §4, item 11.
 */
import {
  notaDaMateria,
  numero,
  type AlunoNaoAferido,
  type Dashboard,
  type DesempenhoDimensao,
  type Dimensao,
  type NaoAferidos,
  type PacoteSincronizacao,
  type PerfilAluno,
  type RankingItem,
} from "@constela/core";

/** As matérias na ordem do catálogo (a mesma do backend, `scoring.DIMENSOES`). */
export const MATERIAS: readonly { chave: Dimensao; rotulo: string }[] = [
  { chave: "leitura", rotulo: "Leitura" },
  { chave: "matematica", rotulo: "Matemática" },
];

const ROTULOS: Record<Dimensao, string> = { leitura: "Leitura", matematica: "Matemática" };

// Campos POR PLATAFORMA do item do Top do painel (`RankingItem` sem `?dimensao=`):
// a nota da matéria e o carimbo de AFERIDO dela.
const CAMPO_NOTA: Record<Dimensao, "nota_elefante" | "nota_matific"> = {
  leitura: "nota_elefante",
  matematica: "nota_matific",
};
const CAMPO_AFERIDO: Record<Dimensao, "aferido_leitura" | "aferido_matematica"> = {
  leitura: "aferido_leitura",
  matematica: "aferido_matematica",
};

// Bloco do "como esta nota foi calculada" de cada matéria em `detalhes`.
const CAMPO_DETALHE: Record<Dimensao, "elefante" | "matific"> = {
  leitura: "elefante",
  matematica: "matific",
};

export function rotuloDaMateria(materia: Dimensao): string {
  return ROTULOS[materia];
}

/** A nota de UMA matéria pronta para a tela.
 *
 *  Delega para `notaDaMateria` (packages/core) — web e app têm de dizer a MESMA
 *  coisa sobre a mesma criança — com um corte a mais: valor que NÃO veio no
 *  payload (`undefined`) é ausência e vira "—". O `notaDaMateria` o mostraria
 *  como "0,0", e um item de um pacote antigo sem a nota da matéria passaria a
 *  afirmar um zero que ninguém mediu. */
export function valorDaMateria(valor: number | null | undefined,
                               aferido?: boolean | null): string {
  return typeof valor === "number" ? notaDaMateria(valor, aferido) : "—";
}

/** Matérias que o USUÁRIO tem, a partir dos módulos de /auth/me (guardados na
 *  sessão cifrada). Mesma regra do web (`hooks/useModulos`): lista ausente ou
 *  vazia = payload antigo ⇒ as duas — sumir conteúdo é pior do que mostrar o
 *  que a pessoa já via. */
export function materiasDoUsuario(modulos?: readonly string[] | null): Dimensao[] {
  const lista = modulos && modulos.length > 0 ? modulos : ["leitura", "matematica"];
  return MATERIAS.map((m) => m.chave).filter((chave) => lista.includes(chave));
}

/** Matérias que a ESCOLA tem, com a melhor prova que o pacote oferece.
 *
 *  Os módulos do usuário não bastam sozinhos: o Admin Global recebe o catálogo
 *  INTEIRO (ele administra todas as redes), não o contrato da escola que está
 *  olhando. Por isso o pacote refina:
 *
 *   1. `ranking_por_dimensao` presente → as chaves dele SÃO o contrato da
 *      escola (o servidor só manda as matérias contratadas);
 *   2. senão (servidor anterior ou cache antigo) → o Top do painel: o servidor
 *      manda `nota_matific`/`nota_elefante` NULA quando o módulo está fora do
 *      plano da rede (`routers/rankings.py::_ranking`). Lista vazia não prova
 *      nada, e aí valem os módulos do usuário.
 *
 *  Nunca lê o `ranking` legado do pacote: o critério de saída do item 11 do
 *  plano é justamente o app parar de lê-lo. */
export function materiasDaEscola(pacote: PacoteSincronizacao | undefined,
                                 modulos?: readonly string[] | null): Dimensao[] {
  const doUsuario = materiasDoUsuario(modulos);
  const porDimensao = pacote?.ranking_por_dimensao;
  if (porDimensao && typeof porDimensao === "object") {
    return doUsuario.filter((materia) => Array.isArray(porDimensao[materia]));
  }
  const recebido = pacote?.dashboard?.top10;
  const top = Array.isArray(recebido) ? recebido : [];
  if (top.length === 0) return doUsuario;
  return doUsuario.filter((materia) => top.some((item) => item[CAMPO_NOTA[materia]] !== null));
}

// --- Ranking por matéria -------------------------------------------------------

/** A lista POR MATÉRIA que viaja no pacote de sincronização, ou `null` quando o
 *  pacote não a traz (servidor anterior, ou cache salvo antes dela existir). */
export function rankingDoPacote(pacote: PacoteSincronizacao | undefined,
                                materia: Dimensao): RankingItem[] | null {
  const lista = pacote?.ranking_por_dimensao?.[materia];
  return Array.isArray(lista) ? lista : null;
}

/** Valida a resposta de `GET /escolas/{id}/ranking?dimensao=` (a rota oficial,
 *  a mesma do web). Um servidor que não conhece o parâmetro o IGNORA e devolve
 *  o Ranking Geral legado — ordenado pela nota composta. Só aceitamos itens
 *  carimbados com a própria matéria; qualquer outra coisa é `null`
 *  ("indisponível"), nunca a lista legada disfarçada de ranking da matéria. */
export function rankingDaRota(resposta: unknown, materia: Dimensao): RankingItem[] | null {
  if (!Array.isArray(resposta)) return null;
  const carimbados = resposta.every(
    (item) => typeof item === "object" && item !== null
      && (item as { dimensao?: unknown }).dimensao === materia);
  return carimbados ? (resposta as RankingItem[]) : null;
}

export type EstadoRankingMateria =
  | { tipo: "lista"; itens: RankingItem[] }
  | { tipo: "carregando" }
  | { tipo: "aviso"; texto: string };

/** O que a aba de UMA matéria mostra, a partir do pacote e da consulta à rota.
 *
 *  Ordem: a lista do pacote (uma viagem de rede, disponível offline) → a da
 *  rota oficial (também persistida no cache cifrado) → um aviso. O aviso diz
 *  POR QUE não há lista, porque "Sem dados" leria como "ninguém aqui usa a
 *  plataforma" — e não é isso. */
export function estadoDoRanking(
  materia: Dimensao,
  pacote: PacoteSincronizacao | undefined,
  rota: { dados?: unknown; erro?: unknown; carregando: boolean },
): EstadoRankingMateria {
  const rotulo = ROTULOS[materia];
  const doPacote = rankingDoPacote(pacote, materia);
  if (doPacote) return { tipo: "lista", itens: doPacote };

  if (rota.dados !== undefined) {
    const daRota = rankingDaRota(rota.dados, materia);
    if (daRota) return { tipo: "lista", itens: daRota };
    return {
      tipo: "aviso",
      texto: `O servidor ainda não envia o ranking de ${rotulo} por matéria. `
        + "Ele aparece aqui assim que o servidor for atualizado.",
    };
  }
  if (rota.carregando) return { tipo: "carregando" };
  // Por campo, e não `instanceof ApiError`: o erro pode vir de outra cópia do
  // pacote compartilhado (testes, bundles), e a classe deixaria de casar.
  const status = (rota.erro as { status?: unknown } | null | undefined)?.status;
  if (status === 403) {
    return { tipo: "aviso", texto: `${rotulo} não faz parte do plano desta rede.` };
  }
  return {
    tipo: "aviso",
    texto: `Sem o ranking de ${rotulo} neste aparelho — conecte-se uma vez para sincronizar.`,
  };
}

export interface LinhaRanking {
  chave: number;
  posicao: number;
  nome: string;
  detalhe: string;
  valor: string;
}

/** Linhas da aba de uma matéria: a posição e a nota DAQUELA matéria, como o
 *  servidor carimbou. A lista só traz alunos AFERIDOS nela (quem não tem dado
 *  sai da lista em vez de entrar com 0,0 — e aparece em `naoAferidosDaMateria`). */
export function linhasDaMateria(itens: RankingItem[]): LinhaRanking[] {
  return itens.map((item) => ({
    chave: item.aluno_id,
    posicao: item.posicao,
    nome: item.nome,
    detalhe: item.turma ?? "",
    valor: valorDaMateria(item.nota, item.aferido),
  }));
}

/** Denominador da posição ("de 21 aferidos"): sem ele, "3º" em Leitura e "3º"
 *  em Matemática parecem comparáveis, e não são. */
export function totalAferidos(itens: RankingItem[]): number {
  const carimbado = itens[0]?.n_aferidos;
  return typeof carimbado === "number" ? carimbado : itens.length;
}

// --- Ainda não aferidos ---------------------------------------------------------

/** Uma criança da lista "Ainda não aferidos": nome e turma, SEM nota e SEM
 *  posição — de propósito (spec §2.4). Quem nunca foi alcançado não é o último
 *  da escola: é quem a coordenação precisa ver. */
export interface LinhaNaoAferido {
  chave: number;
  nome: string;
  detalhe: string;
}

export type EstadoNaoAferidos =
  | { tipo: "lista"; titulo: string; explicacao: string; linhas: LinhaNaoAferido[] }
  /** Nada a mostrar: matéria fora do plano da rede, ou ninguém sem dado no
   *  recorte (inclui a Secretaria, que recebe as listas vazias do servidor). */
  | { tipo: "oculto" }
  | { tipo: "carregando" }
  | { tipo: "aviso"; texto: string };

function ehAlunoNaoAferido(valor: unknown): valor is AlunoNaoAferido {
  return typeof valor === "object" && valor !== null
    && typeof (valor as AlunoNaoAferido).aluno_id === "number"
    && typeof (valor as AlunoNaoAferido).nome === "string";
}

/** O bloco "Ainda não aferidos em <matéria>" da aba do Ranking, a partir de
 *  `GET /escolas/{id}/nao-aferidos` (a mesma rota do web; o pacote de
 *  sincronização não a traz).
 *
 *  É a contrapartida obrigatória do corte "ausência não é zero" (spec §1.2,
 *  consequência 3): ao sair do ranking da matéria, a criança sem dado não pode
 *  sumir do app — e a aba do Ranking é a única porta do app para o perfil.
 *
 *  O escopo vem pronto do servidor (professor: só as turmas dele; Secretaria:
 *  listas vazias, porque não enxerga criança individual) — o app não filtra
 *  nada. Matéria fora de `contratadas` não tem bloco: ninguém é "não aferido"
 *  num produto que a rede não comprou. Quem não tem dado em NENHUMA matéria
 *  aparece aqui em todas elas (spec §2.4); com mais de uma matéria no plano, a
 *  linha diz isso (adoção 0%).
 *
 *  Sem a resposta (rota que o servidor ainda não tem, cache antigo salvo antes
 *  desta consulta existir, sem rede), o bloco vira uma MENSAGEM — nunca some
 *  calado, porque sumir é justamente o defeito que ele existe para impedir. */
export function naoAferidosDaMateria(
  materia: Dimensao,
  consulta: { dados?: unknown; erro?: unknown; carregando: boolean },
): EstadoNaoAferidos {
  const rotulo = ROTULOS[materia];
  const indisponivel: EstadoNaoAferidos = {
    tipo: "aviso",
    texto: `A lista de quem ainda não foi aferido em ${rotulo} não veio num formato que `
      + "este app reconheça. Atualize o app ou consulte pelo sistema web.",
  };

  if (consulta.dados !== undefined) {
    const resposta = consulta.dados as Partial<NaoAferidos> | null;
    const contratadas = resposta?.contratadas;
    const dimensoes = resposta?.dimensoes;
    if (!Array.isArray(contratadas) || !Array.isArray(dimensoes)) return indisponivel;
    if (!contratadas.includes(materia)) return { tipo: "oculto" };

    const daMateria = dimensoes.find(
      (d) => typeof d === "object" && d !== null && d.dimensao === materia);
    const alunos: unknown = daMateria?.alunos;
    if (!Array.isArray(alunos) || !alunos.every(ehAlunoNaoAferido)) return indisponivel;
    if (alunos.length === 0) return { tipo: "oculto" };

    // "Sem nenhuma" só acrescenta informação quando o plano tem mais de uma
    // matéria; com uma só, todo não aferido nela já está sem nenhuma.
    const variasMaterias = contratadas.filter((c) => c in ROTULOS).length > 1;
    const recebidos: unknown = resposta?.sem_nenhuma;
    const semNenhuma = new Set(
      variasMaterias && Array.isArray(recebidos)
        ? recebidos.filter(ehAlunoNaoAferido).map((a) => a.aluno_id)
        : []);

    const linhas = alunos.map((aluno) => ({
      chave: aluno.aluno_id,
      nome: aluno.nome,
      detalhe: [
        aluno.turma ?? "",
        semNenhuma.has(aluno.aluno_id) ? "sem dado em nenhuma matéria (adoção 0%)" : "",
      ].filter(Boolean).join(" · "),
    }));
    const nenhuma = linhas.filter((linha) => semNenhuma.has(linha.chave)).length;
    return {
      tipo: "lista",
      titulo: `Ainda não aferidos em ${rotulo} (${numero(linhas.length)})`,
      explicacao: "Sem dado da plataforma desta matéria: não entram no ranking nem na média "
        + "— ausência não é nota zero."
        + (nenhuma > 0
          ? ` ${numero(nenhuma)} ${nenhuma === 1 ? "não tem" : "não têm"} dado em nenhuma matéria.`
          : ""),
      linhas,
    };
  }

  if (consulta.carregando) return { tipo: "carregando" };
  // Por campo, e não `instanceof ApiError` (mesma razão de `estadoDoRanking`).
  const status = (consulta.erro as { status?: unknown } | null | undefined)?.status;
  if (status === 404) {
    return {
      tipo: "aviso",
      texto: `O servidor ainda não envia a lista de quem não foi aferido em ${rotulo}. `
        + "Ela aparece aqui assim que o servidor for atualizado.",
    };
  }
  if (status === 403) {
    return {
      tipo: "aviso",
      texto: "Seu acesso não inclui a lista de quem ainda não foi aferido nesta escola.",
    };
  }
  return {
    tipo: "aviso",
    texto: `Sem a lista de quem ainda não foi aferido em ${rotulo} neste aparelho `
      + "— conecte-se uma vez para sincronizar.",
  };
}

// --- Painel ---------------------------------------------------------------------

export interface NotaDaMateria {
  materia: Dimensao;
  rotulo: string;
  valor: string;
}

/** As notas por matéria de um item do Top do painel — "—" para quem não tem
 *  dado da plataforma (carimbo `aferido_*` do servidor), só das matérias que a
 *  escola tem. A ORDEM do Top continua a que o servidor decide. */
export function notasDoItem(item: RankingItem, materias: readonly Dimensao[]): NotaDaMateria[] {
  return materias.map((materia) => ({
    materia,
    rotulo: ROTULOS[materia],
    valor: valorDaMateria(item[CAMPO_NOTA[materia]], item[CAMPO_AFERIDO[materia]]),
  }));
}

export interface MediaDaMateria extends NotaDaMateria {
  /** Quantos alunos TÊM dado da plataforma — o denominador da média. */
  comDado: number;
}

/** Médias da escola POR MATÉRIA, cada uma só sobre quem tem dado da plataforma
 *  dela. `null` = o pacote não traz as médias por matéria (servidor anterior):
 *  a tela avisa em vez de cair na média composta. */
export function mediasDaEscola(painel: Dashboard,
                               materias: readonly Dimensao[]): MediaDaMateria[] | null {
  const campos = {
    leitura: { media: painel.media_leitura, n: painel.alunos_com_dado_leitura },
    matematica: { media: painel.media_matematica, n: painel.alunos_com_dado_matematica },
  } as const;
  const algumaVeio = materias.some(
    (materia) => typeof campos[materia].n === "number" || typeof campos[materia].media === "number");
  if (!algumaVeio) return null;
  return materias.map((materia) => {
    const { media, n } = campos[materia];
    const comDado = typeof n === "number" ? n : 0;
    return {
      materia,
      rotulo: ROTULOS[materia],
      comDado,
      // Ninguém com dado = AUSÊNCIA ("—"), não média zero.
      valor: comDado > 0 && typeof media === "number" ? valorDaMateria(media) : "—",
    };
  });
}

// --- Perfil do aluno ------------------------------------------------------------

export interface BlocoMateria {
  materia: Dimensao;
  rotulo: string;
  /** `null` = o servidor não declarou se há dado (perfil sem o carimbo). */
  aferido: boolean | null;
  valor: string;
  /** "3º de 21" — `null` quando não há posição carimbada naquela matéria. */
  posicao: string | null;
}

/** Bloco por matéria gravado pelo motor em `detalhes.dimensoes` (o perfil manda
 *  `detalhes` cru). Tipado aqui, e não no pacote compartilhado, porque só o
 *  app precisa desta rota de fallback. */
type BlocoGravado = Partial<Pick<DesempenhoDimensao,
  "contratada" | "aferido" | "nota" | "posicao" | "n_aferidos">>;

function posicaoNaMateria(aferido: boolean | null, posicao: unknown,
                          nAferidos: unknown): string | null {
  if (aferido !== true || typeof posicao !== "number" || posicao <= 0) return null;
  return typeof nAferidos === "number" && nAferidos > 0
    ? `${posicao}º de ${numero(nAferidos)}`
    : `${posicao}º`;
}

function blocoCarimbado(materia: Dimensao, origem: BlocoGravado): BlocoMateria {
  const aferido = origem.aferido === true;
  return {
    materia,
    rotulo: ROTULOS[materia],
    aferido,
    valor: aferido ? valorDaMateria(origem.nota, true) : "—",
    posicao: posicaoNaMateria(aferido, origem.posicao, origem.n_aferidos),
  };
}

/** Os blocos por matéria do perfil, da fonte mais oficial para a mais antiga:
 *
 *   1. `perfil.dimensoes` — o desempenho por matéria que o servidor monta (já
 *      só com as matérias contratadas);
 *   2. `detalhes.dimensoes` — o mesmo bloco, como o motor o gravou no último
 *      recálculo (servidor que ainda não monta o item 1); matéria marcada
 *      `contratada: false` some;
 *   3. as colunas por plataforma (`nota_elefante`/`nota_matific`) — escola
 *      ainda não recalculada nesta arquitetura. Sem carimbo de aferição, vale
 *      a regra do `notaDaMateria`: mostrar o número (dizer "—" inventaria uma
 *      ausência que o servidor não declarou) — exceto quando não há nota
 *      calculada nenhuma (`calculada_em` nulo), que é ausência declarada;
 *      `carimbado: false` faz a tela avisar que a posição por matéria chega no
 *      próximo recálculo.
 *
 *  Em todos os casos, só as matérias que o usuário tem (módulos de /auth/me). */
export function blocosDoPerfil(perfil: PerfilAluno, modulos?: readonly string[] | null):
  { blocos: BlocoMateria[]; carimbado: boolean } {
  const permitidas = materiasDoUsuario(modulos);

  const oficiais = Array.isArray(perfil.dimensoes) ? perfil.dimensoes : [];
  if (oficiais.length > 0) {
    const blocos = permitidas.flatMap((materia) => {
      const origem = oficiais.find((d) => d.dimensao === materia);
      return origem && origem.contratada !== false ? [blocoCarimbado(materia, origem)] : [];
    });
    return { blocos, carimbado: true };
  }

  const gravados = (perfil.detalhes as { dimensoes?: Record<string, BlocoGravado | undefined> } | undefined)
    ?.dimensoes;
  if (gravados && typeof gravados === "object") {
    const blocos = permitidas.flatMap((materia) => {
      const origem = gravados[materia];
      return origem && origem.contratada !== false ? [blocoCarimbado(materia, origem)] : [];
    });
    return { blocos, carimbado: true };
  }

  // Sem `calculada_em` o servidor não tem linha de nota nenhuma para o aluno e
  // manda 0,0 de preenchimento — isso é ausência, e vira "—".
  const calculada = Boolean(perfil.calculada_em);
  const blocos = permitidas.map((materia) => ({
    materia,
    rotulo: ROTULOS[materia],
    aferido: null,
    valor: calculada ? valorDaMateria(perfil[CAMPO_NOTA[materia]]) : "—",
    posicao: null,
  }));
  return { blocos, carimbado: false };
}

/** O "como esta nota foi calculada" de uma matéria, só quando ela TEM dado:
 *  o motor grava o bloco também para quem não usa a plataforma, e a tabela
 *  mostraria uma conta de zeros afirmando uma nota 0,0 que ninguém mediu. */
export function calculoDaMateria(perfil: PerfilAluno, bloco: BlocoMateria) {
  if (bloco.aferido === false) return null;
  return perfil.detalhes?.[CAMPO_DETALHE[bloco.materia]] ?? null;
}
